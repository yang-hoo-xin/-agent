"""Read Cloud execution evidence without prompts, model calls or workflow writes.

The Cloud MCP is self-describing: discover its current input and field schemas
before querying. This is a disposable projection, not another execution index.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import jsonschema

from src.observability.patch_langfuse import LangfuseHttpTransport, PatchLangfuseError

_TOOLS = {"getObservationFieldSchema", "listObservations", "listScores"}
_FIELDS = (
    "id", "traceId", "parentObservationId", "isRootObservation", "type", "name",
    "startTime", "endTime", "level", "statusMessage", "providedModelName", "usageDetails",
    "totalCost", "completionStartTime", "promptName", "metadata", "sessionId",
)
_EXPAND = ("artifact_refs", "consumed_tool_results", "tool_call_id_sha256s")
_FACTS = (
    "turn_index", "evaluation_index", "workflow_status", "terminal_stage", "failure_code",
    "verification_status", "failure_owner", "execution_origin", "callback_invoked",
    "checks_run", "checks_failed", "request_sha256", "response_sha256", "output_sha256",
    "output_code_sha256", "generated_changes_sha256", "behavior_report_sha256",
    "request_bytes", "encoded_payload_bytes", "encoded_payload_sha256", "byte_count",
    "failure_boundary", "failure_classification", "context_admission_mode", "provider_body_utf8_bytes",
    "configured_num_ctx", "num_predict", "conservative_required_context",
    "call_id_sha256", "transport_started", "response_received", "response_complete",
    "usage_available", "usage_mapping_status", "upstream_execution_performed",
    "request_registered", "result_code", "admission_result", "tool_dispatch_performed",
    "observation_queued", "model_consumption_proven", "historical_import", "metadata_only",
    "observation_status", "source_prompt_output_included", "score_eligible", "score_basis",
    "verification_executions", "verification_matrix_sha256", *_EXPAND,
)


def _fail(code):
    raise PatchLangfuseError(code)


class CloudExecutionReader:
    """Bounded, read-only MCP access through the existing HTTP transport."""

    def __init__(self, transport, *, page_budget=5):
        if type(page_budget) is not int or not 1 <= page_budget <= 10:
            _fail("LANGFUSE_QUERY_PAGE_BUDGET_INVALID")
        self.transport, self.page_budget = transport, page_budget
        self.schemas = None

    def _rpc(self, method, params=None):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            payload["params"] = params
        envelope = self.transport._request("POST", "/api/public/mcp", payload=payload)
        if not isinstance(envelope, dict) or envelope.get("error") or not isinstance(envelope.get("result"), dict):
            _fail("LANGFUSE_QUERY_RPC_INVALID")
        return envelope["result"]

    def _discover(self):
        result = self._rpc("tools/list")
        rows = result.get("tools")
        if not isinstance(rows, list):
            _fail("LANGFUSE_QUERY_SCHEMA_UNAVAILABLE")
        self.schemas = {r["name"]: r["inputSchema"] for r in rows
                        if isinstance(r, dict) and r.get("name") in _TOOLS and isinstance(r.get("inputSchema"), dict)}
        if not _TOOLS <= self.schemas.keys():
            _fail("LANGFUSE_QUERY_SCHEMA_UNAVAILABLE")

    def _call(self, name, arguments):
        if name not in _TOOLS:
            _fail("LANGFUSE_QUERY_READ_ONLY")
        if self.schemas is None:
            self._discover()
        try:
            jsonschema.validate(arguments, self.schemas[name])
        except (jsonschema.ValidationError, jsonschema.SchemaError):
            _fail("LANGFUSE_QUERY_SCHEMA_CHANGED")
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            _fail("LANGFUSE_QUERY_TOOL_FAILED")
        content = result.get("content")
        if not isinstance(content, list):
            _fail("LANGFUSE_QUERY_CONTENT_INVALID")
        try:
            value = json.loads(next(r["text"] for r in content if isinstance(r, dict) and r.get("type") == "text"))
        except (ValueError, KeyError, StopIteration, TypeError):
            _fail("LANGFUSE_QUERY_CONTENT_INVALID")
        if not isinstance(value, dict):
            _fail("LANGFUSE_QUERY_CONTENT_INVALID")
        return value

    def _pages(self, tool, arguments):
        rows, cursor, seen = [], None, set()
        for _ in range(self.page_budget):
            value = self._call(tool, {**arguments, **({"cursor": cursor} if cursor else {})})
            data, meta = value.get("data"), value.get("meta", {})
            if not isinstance(data, list) or not isinstance(meta, dict) or any(not isinstance(r, dict) for r in data):
                _fail("LANGFUSE_QUERY_PAGE_INVALID")
            rows.extend(data)
            cursor = meta.get("cursor")
            if not cursor:
                return rows
            if not isinstance(cursor, str) or cursor in seen:
                _fail("LANGFUSE_QUERY_CURSOR_INVALID")
            seen.add(cursor)
        _fail("LANGFUSE_QUERY_PAGE_BUDGET_EXHAUSTED")

    def read(self, trace_id):
        if not isinstance(trace_id, str) or not re.fullmatch(r"[a-f0-9]{32}", trace_id):
            _fail("LANGFUSE_TRACE_ID_INVALID")
        schema = self._call("getObservationFieldSchema", {})
        if not isinstance(schema.get("fields"), dict) or not set(_FIELDS) <= schema["fields"].keys():
            _fail("LANGFUSE_QUERY_FIELDS_CHANGED")
        observations = self._pages("listObservations", {"traceId": trace_id, "limit": 100,
            "fields": list(_FIELDS), "expandMetadataKeys": list(_EXPAND)})
        scores = self._pages("listScores", {"traceId": [trace_id], "limit": 100})
        return summarize_execution(trace_id, observations, scores)


def _milliseconds(start, end):
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        a, b = (datetime.fromisoformat(x.replace("Z", "+00:00")) for x in (start, end))
        if a.utcoffset() is None or b.utcoffset() is None or b < a:
            return None
        return round((b - a).total_seconds() * 1000, 4)
    except ValueError:
        return None


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _usage(row):
    raw = row.get("usageDetails")
    meta = row.get("metadata", {})
    if (not isinstance(raw, dict) or meta.get("usage_available") is not True
            or meta.get("usage_mapping_status") != "inclusive_provider_counts_to_exclusive_buckets"):
        return None
    # Our mapper writes exclusive buckets; Cloud may also add a derived total.
    if not all(_number(raw.get(k)) for k in ("input", "output")):
        return None
    if any(not _number(raw[k]) for k in ("input_cached_tokens", "output_reasoning_tokens") if k in raw):
        return None
    if raw.keys() - {"input", "output", "total", "input_cached_tokens", "output_reasoning_tokens"}:
        return None
    input_tokens = raw["input"] + raw.get("input_cached_tokens", 0)
    output_tokens = raw["output"] + raw.get("output_reasoning_tokens", 0)
    if "total" in raw and (not _number(raw["total"]) or raw["total"] != input_tokens + output_tokens):
        return None
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens}


def summarize_execution(trace_id, observations, scores=()):
    """Explain recorded bindings; absence is not proof that a stage never ran."""
    unique = {}
    for row in observations:
        if (not isinstance(row, dict) or row.get("traceId") != trace_id
                or not isinstance(row.get("id"), str) or not isinstance(row.get("metadata", {}), dict)):
            _fail("LANGFUSE_QUERY_OBSERVATION_IDENTITY_MISMATCH")
        if row["id"] in unique and unique[row["id"]] != row:
            _fail("LANGFUSE_QUERY_CONFLICTING_OBSERVATION")
        unique[row["id"]] = row
    rows = sorted(unique.values(), key=lambda r: (r.get("startTime") or "", r["id"]))
    generations = [r for r in rows if r.get("type") == "GENERATION"]
    roots = [r for r in rows if r.get("isRootObservation") is True]
    tools = [r for r in rows if r.get("name") == "source.inspect" and r.get("type") == "TOOL"]
    generation_results, links, verification = [], [], []
    for row in generations:
        meta = row.get("metadata", {})
        generation_results.append({"observation_id": row["id"], "parent_id": row.get("parentObservationId"),
            "model": row.get("providedModelName"), "level": row.get("level"), "status_message": row.get("statusMessage"),
            "duration_ms": _milliseconds(row.get("startTime"), row.get("endTime")),
            "ttft_ms": _milliseconds(row.get("startTime"), row.get("completionStartTime")),
            "usage": _usage(row), "cost": row.get("totalCost") if _number(row.get("totalCost")) else None,
            "prompt_name": row.get("promptName") or None, "facts": {k: meta[k] for k in _FACTS if k in meta}})
        consumed = meta.get("consumed_tool_results")
        if isinstance(consumed, list):
            for fact in consumed:
                if not isinstance(fact, dict):
                    continue
                call, digest = fact.get("call_id_sha256"), fact.get("observation_sha256")
                matches = [t["id"] for t in tools if isinstance(call, str) and isinstance(digest, str)
                           and t.get("metadata", {}).get("call_id_sha256") == call
                           and t.get("metadata", {}).get("encoded_payload_sha256") == digest]
                links.append({"generation_id": row["id"], "source_observation_ids": matches,
                    "call_id_sha256": call, "observation_sha256": digest,
                    "binding": "matched_recorded_consumption" if len(matches) == 1 else "unresolved"})
    for row in rows:
        if row.get("name") != "patch.verify":
            continue
        meta = row.get("metadata", {})
        output = meta.get("output_sha256")
        matches = [g["id"] for g in generations if isinstance(output, str)
                   and g.get("metadata", {}).get("output_sha256") == output]
        verification.append({"observation_id": row["id"], "level": row.get("level"),
            "matching_generation_ids": matches,
            "binding": "recorded_output_hash_match" if matches else "unresolved",
            "facts": {k: meta[k] for k in _FACTS if k in meta}})
    score_results = []
    for score in scores:
        subject = score.get("subject") if isinstance(score, dict) else None
        if (not isinstance(subject, dict)
                or not (subject.get("traceId") == trace_id or subject.get("kind") == "trace" and subject.get("id") == trace_id)):
            _fail("LANGFUSE_QUERY_SCORE_IDENTITY_MISMATCH")
        score_results.append({k: score[k] for k in ("id", "name", "dataType", "value", "source", "subject") if k in score})
    known_usage = [g["usage"] for g in generation_results if g["usage"] is not None]
    durations = [g for g in generation_results if g["duration_ms"] is not None]
    parent_missing = sorted({r["parentObservationId"] for r in rows
                             if r.get("parentObservationId") and r["parentObservationId"] not in unique})
    return {"trace_id": trace_id, "source": "langfuse_cloud", "read_only": True,
        "observation_count": len(rows), "levels": dict(Counter(r.get("level") for r in rows)),
        "generation_count": len(generations), "model_request_observations": sum(r.get("name") == "model.request" for r in rows),
        "generation_count_scope": "recorded_generations_not_reserved_worker_calls",
        "generations": generation_results,
        "slowest_measured_generation_id": max(durations, key=lambda r: r["duration_ms"])["observation_id"] if durations else None,
        "usage": {"measured_generations": len(known_usage), "missing_generations": len(generations) - len(known_usage),
                  "measured_totals": {k: sum(u[k] for u in known_usage) for k in ("input_tokens", "output_tokens", "total_tokens")} if known_usage else None},
        "verification": verification, "tool_consumption_links": links,
        "roots": [{"observation_id": r["id"], "facts": {k: r.get("metadata", {})[k] for k in _FACTS if k in r.get("metadata", {})}} for r in roots],
        "upstream_requests": [{"observation_id": r["id"], "facts": {k: r.get("metadata", {})[k] for k in _FACTS if k in r.get("metadata", {})}}
                              for r in rows if r.get("name") == "patch.upstream_request"],
        "observed_operations": sorted({r["name"] for r in rows if isinstance(r.get("name"), str)}),
        "execution_tree": [{"observation_id": r["id"], "parent_id": r.get("parentObservationId"),
            "type": r.get("type"), "name": r.get("name"), "level": r.get("level"), "status_message": r.get("statusMessage"),
            "start_time": r.get("startTime"), "end_time": r.get("endTime"),
            "duration_ms": _milliseconds(r.get("startTime"), r.get("endTime")),
            "facts": {k: r.get("metadata", {})[k] for k in _FACTS if k in r.get("metadata", {})}} for r in rows],
        "missing_parent_observation_ids": parent_missing, "scores": score_results,
        "limits": ["Default is observation severity, not task success.",
                   "Missing operations are unobserved; execution/nonexecution requires bound journal evidence.",
                   "Hash joins show recorded identity, not semantic correctness or a unique causal explanation.",
                   "No raw prompt, response or source was requested; full Mod delivery is not inferred."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read one Langfuse execution and its recorded diagnostic bindings.")
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = CloudExecutionReader(LangfuseHttpTransport.from_environment()).read(args.trace_id)
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
