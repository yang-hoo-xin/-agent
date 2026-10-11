"""Read-only input/decision/outcome joins over explicitly selected Product records.

This is an evidence projection, not a semantic judge or a new execution owner.
为什么要有它：a recorded contract pass or supplied context cannot prove understanding.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.mod_agent.upstream_trace import model_input_materials
from src.observability.dashboard.services.trace_service import TraceService

_STAGES = {
    "requirement_projection": "requirements",
    "requirement_projection_correction": "requirements",
    "requirement_findings": "findings",
    "requirement_findings_correction": "findings",
    "initial_findings_queries": "query",
    "upstream_evidence_queries": "query",
    "planning": "planning",
    "patch_upstream_planning": "planning",
}


def _unknown(reason):
    return {"status": "unknown", "basis": reason}


def _json_equal(left, right):
    # Python considers True == 1. JSON identity must retain that distinction.
    # 为什么要有它：a schema enum or message value must not change type unnoticed.
    options = {"ensure_ascii": False, "sort_keys": True, "allow_nan": False, "separators": (",", ":")}
    return json.dumps(left, **options) == json.dumps(right, **options)


def _bound_record(ref, root):
    value, digest = TraceService._read_product_json(Path(ref["path"]), root=root)
    if digest != ref["sha256"]:
        raise ValueError("Context chain record changed during inspection.")
    return value


def _details(refs, root):
    """Read only the exact local references, never derive a filename from an ID."""
    values, bound = {}, {}
    for kind, ref in refs.items():
        if not isinstance(ref, dict):
            raise ValueError("Context chain detail reference must be an object.")
        integrity = TraceService._local_ref_summary(ref, root=root)
        if integrity["integrity"] != "verified_bytes":
            raise ValueError("Context chain detail is missing, changed or outside the run.")
        path = Path(ref["path"])
        path = (path if path.is_absolute() else root / path).resolve()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("Context chain detail changed during inspection.")
        bound[kind] = {"path": str(path), "sha256": ref["sha256"]}
        if kind in {"request", "provider_request", "response"}:
            try:
                values[kind] = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                values[kind] = None
    return values, bound


def _payloads(request):
    if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
        return []
    result = []
    for index, message in enumerate(request["messages"]):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        value = message.get("content")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                continue
        if isinstance(value, dict):
            result.append((index, value))
    return result


def _shape(value):
    return {key: {"type": type(item).__name__,
                  "count": len(item) if isinstance(item, (dict, list)) else None}
            for key, item in value.items()}


def _response_summary(value):
    if not isinstance(value, dict):
        return {"json_object": False, "semantic_correctness": "unknown"}
    result = {"json_object": True, "fields": _shape(value)}
    # Keep decisions, not full source excerpts or generated code. Original bytes
    # remain available via exact references. 为什么要有它：the report is an index.
    for key in ("requirements", "input_dispositions", "findings", "queries"):
        if isinstance(value.get(key), list):
            result[key] = value[key]
    if isinstance(value.get("findings"), list):
        result["relationship_counts"] = dict(Counter(
            row.get("relationship", "unknown") for row in value["findings"] if isinstance(row, dict)))
    return result


def _ancestor_checks(generation, observations):
    checks, visited = [], set()
    parent = generation.get("parent_id")
    while parent in observations and parent not in visited:
        visited.add(parent)
        row = observations[parent]
        audit = row.get("attributes", {}).get("requirement_findings_attempt_audit")
        if isinstance(audit, list):
            checks.append({"observation_id": parent, "recorded_attempts": audit,
                           "association": "ancestor_span_group_not_individual_attempt",
                           "claim": "recorded_contract_admission_not_independent_semantic_judgment"})
        parent = row.get("parent_id")
    return checks


def _material_links(materials, sources, before, current_segment):
    if materials is None:
        return None
    result = []
    for material in materials:
        matches = []
        evidence_id, excerpt = material.get("evidence_id"), material.get("excerpt_sha256")
        cutoff = _timestamp(before)
        if isinstance(evidence_id, str) and isinstance(excerpt, str) and cutoff is not None:
            for source in sources:
                for row in source["observations"].values():
                    finished = _timestamp(row.get("finished_at"))
                    if finished is None or finished > cutoff:
                        continue
                    for produced in row.get("attributes", {}).get("produced_materials", []):
                        if (isinstance(produced, dict) and produced.get("evidence_id") == evidence_id
                                and produced.get("excerpt_sha256") == excerpt):
                            matches.append({"observation_id": row["id"], "source_hash": produced.get("source_hash"),
                                            "segment": source["segment"], "manifest_ref": source["manifest_ref"],
                                            "origin": "current_segment" if source["segment"] == current_segment
                                            else "selected_parent"})
        result.append({**material, "producer_matches": matches,
                       "match_basis": "exact_evidence_id_and_excerpt_sha256_before_request_in_bound_selected_lineage",
                       "lookup_status": "matched" if matches else "no_match_in_selected_bound_lineage",
                       "model_utilization": "unknown"})
    return result


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _query_links(response, parent, observations):
    """Match the recorded rg query hash, owning span and dispatch time."""
    if not isinstance(response, dict) or not isinstance(response.get("queries"), list):
        return []
    after = _timestamp(parent.get("finished_at"))
    owner = parent.get("parent_id")
    if after is None or not isinstance(owner, str):
        return []
    later = [_timestamp(row.get("started_at")) for row in observations.values()
             if row.get("name") == "model.request" and row.get("parent_id") == owner
             and (_timestamp(row.get("started_at")) or 0) > after]
    before = min(later) if later else float("inf")
    links = []
    for index, query in enumerate(response["queries"]):
        if not isinstance(query, dict) or not isinstance(query.get("query"), str):
            continue
        digest = hashlib.sha256(query["query"].encode("utf-8")).hexdigest()
        matches = []
        for row in observations.values():
            attrs = row.get("attributes", {})
            started = _timestamp(row.get("started_at"))
            if (row.get("name") == "evidence.source_query" and row.get("parent_id") == owner
                    and attrs.get("query_sha256") == digest and started is not None
                    and after <= started < before):
                matches.append({"observation_id": row["id"], "evidence_item_count": attrs.get("evidence_item_count"),
                                "retrieval_status": attrs.get("retrieval_status")})
        links.append({"output_query_index": index, "query_sha256": digest, "observations": matches,
                      "match_basis": "exact_query_sha256_same_owner_after_response_before_next_request",
                      "new_fact_or_decision_improvement": "unknown"})
    return links


def _model_record(call, manifest, root, sources):
    observations = manifest["execution_observations"]
    by_id = {row["id"]: row for row in observations.values()}
    generation = by_id[call["generation_span_id"]]
    parent = by_id[call["request_span_id"]]
    attrs = {**parent.get("attributes", {}), **generation.get("attributes", {})}
    values, refs = _details(attrs.get("local_detail_refs", {}), root)
    request, native = values.get("request"), values.get("provider_request")
    payloads = _payloads(request)
    supplied = []
    for index, payload in payloads:
        supplied.append({"message_index": index, "message_type": payload.get("message_type"),
                         "fields": _shape(payload), "materials": _material_links(
                             model_input_materials(payload) if "source_observations" in payload else None,
                             sources, parent.get("started_at"), call["segment"])})
    native_match = _unknown("native_messages_or_application_messages_not_recorded")
    if (isinstance(request, dict) and isinstance(native, dict)
            and isinstance(request.get("messages"), list) and isinstance(native.get("messages"), list)):
        native_match = {"status": "compared", "equal": _json_equal(request["messages"], native["messages"]),
                        "basis": "canonical_json_equality_not_model_attention_or_wire_packet_capture"}
    schema_match = _unknown("application_response_format_or_native_format_not_recorded")
    if (isinstance(request, dict) and isinstance(native, dict)
            and isinstance(request.get("response_format"), (dict, bool))
            and isinstance(native.get("format"), (dict, bool))):
        schema_match = {"status": "compared", "equal": _json_equal(request["response_format"], native["format"]),
                        "application_field": "response_format", "native_field": "format",
                        "basis": "canonical_json_equality_not_schema_equivalence_or_backend_grammar"}
    stage = _STAGES.get(call["role"], "unknown")
    if generation.get("name") == "patch.generate":
        stage = "patch"
    return {
        "id": generation["id"], "kind": "model", "stage": stage,
        "name": generation.get("name"), "role": call["role"],
        "parent_id": generation.get("parent_id"), "started_at": generation.get("started_at"),
        "input": {"refs": refs, "payloads": supplied,
                  "recorded_consumed_materials": attrs.get("consumed_materials"),
                  "recorded_consumed_tool_results": attrs.get("consumed_tool_results"),
                  "native_messages_comparison": native_match,
                  "native_schema_comparison": schema_match,
                  "provider_request_metadata": call.get("provider_request_metadata"),
                  "key_fact_coverage": _unknown("independent_key_fact_labels_not_provided")},
        "judgment": {"contract_checks": _ancestor_checks(generation, by_id),
                     "semantic_correctness": _unknown("no_independent_decision_judgment"),
                     "reviewer_origin": "none"},
        "result": {"status": call["status"], "transport": call["transport"],
                   "response_ref": refs.get("response"),
                   "model_declared_output": _response_summary(values.get("response")),
                   "query_execution_links": _query_links(values.get("response"), parent, by_id),
                   "semantic_correctness": "unknown"},
        "cost": {"usage": call["usage"], "elapsed_ms": call["elapsed_ms"]},
    }


def _prepared_record(row, root):
    attrs = row.get("attributes", {})
    values, refs = _details(attrs.get("local_detail_refs", {}), root)
    return {"id": row["id"], "kind": "request_without_generation",
            "stage": _STAGES.get(attrs.get("model_role"), "unknown"),
            "name": row.get("name"), "parent_id": row.get("parent_id"),
            "started_at": row.get("started_at"),
            "input": {"refs": refs, "payload_fields": [_shape(v) for _, v in _payloads(values.get("request"))]},
            "judgment": {"semantic_correctness": _unknown("no_independent_decision_judgment")},
            "result": {"status": row.get("status"), "recorded_decision": {
                "transport_started": attrs.get("transport_started"),
                "response_received": attrs.get("response_received"),
                "generation_record": "not_observed_not_proof_request_was_never_sent"}},
            "cost": {"elapsed_ms": row.get("elapsed_ms")}}


def _observation_record(row, root):
    attrs = row.get("attributes", {})
    if row.get("name") == "evidence.source_query":
        stage = "evidence"
        inputs = {key: attrs.get(key) for key in ("query_sha256", "input_payload_sha256")}
        output = {key: attrs.get(key) for key in (
            "retrieval_status", "evidence_item_count", "produced_materials",
            "tool_dispatch_performed", "tool_exit_code", "output_payload_sha256")}
    elif row.get("name") == "requirements.coverage":
        stage = "findings_gate"
        inputs = {key: attrs.get(key) for key in ("input_payload_sha256", "consumed_materials")}
        output = {key: attrs.get(key) for key in (
            "decision", "readiness", "can_generate_patch", "selected_evidence_ids",
            "relationship_counts", "unresolved_gap_count", "reason_status")}
    elif row.get("name") == "planning.decision":
        stage = "planning_gate"
        inputs = {key: attrs.get(key) for key in (
            "feature_payload_sha256", "evidence_payload_sha256", "consumed_materials")}
        # Inspect this event, not the first event of the segment. 为什么要有它：
        # a later planning attempt must not inherit an earlier gate's receipt.
        output = TraceService()._planning_decision(root, [row])
        refs = attrs.get("local_detail_refs", {})
        output["receipt_ref"] = refs.get("planning_receipt") if output["receipt_status"] == "verified_bytes" else None
    elif row.get("name") == "workflow.route":
        stage = "routing"
        inputs = {key: attrs.get(key) for key in ("route_inputs", "route_input_sha256", "artifact_refs")}
        output = {key: attrs.get(key) for key in ("from_node", "selected_route", "selected_next_node")}
        output["target_execution_proven"] = False
    elif row.get("kind") == "tool":
        stage = "tool_observation"
        inputs = {key: attrs.get(key) for key in ("input_payload_sha256", "consumed_materials", "consumed_tool_results")}
        output = {"recorded_attribute_fields": _shape(attrs),
                  "output_payload_sha256": attrs.get("output_payload_sha256"),
                  "produced_materials": attrs.get("produced_materials")}
    else:
        return None
    return {"id": row["id"], "kind": row.get("kind"), "stage": stage,
            "name": row.get("name"), "parent_id": row.get("parent_id"),
            "started_at": row.get("started_at"), "input": inputs,
            "judgment": {"semantic_correctness": _unknown("no_independent_decision_judgment")},
            "result": {"status": row.get("status"), "recorded_decision": output},
            "cost": {"elapsed_ms": row.get("elapsed_ms")}}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _cost(calls, orphan_requests):
    incomplete = any(row["result"]["recorded_decision"]["transport_started"] is not False
                     for row in orphan_requests)
    result = {"generation_records": len(calls), "money": "unknown",
              "scope": "selected_generation_records", "unaccounted_request_possible": incomplete}
    for name in ("input_tokens", "output_tokens"):
        values = [(row.get("usage") or {}).get(name) for row in calls]
        valid = [value for value in values if type(value) is int and value >= 0]
        result[name] = {"total": sum(valid) if len(valid) == len(values) and not incomplete else None,
                        "known_subtotal": sum(valid), "observed_calls": len(valid)}
    values = [row.get("elapsed_ms") for row in calls]
    result["generation_elapsed_ms_sum"] = sum(values) if all(_number(v) for v in values) and not incomplete else None
    result["elapsed_scope"] = "sum_of_model_spans_not_end_to_end_or_tool_total"
    return result


def _selected_parent_sources(manifest, previous):
    ref = manifest.get("parent_result_ref")
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not Path(ref["path"]).is_absolute():
        return [], _unknown("no_absolute_parent_result_ref")
    for prior in previous:
        expected = prior["result_ref"]
        if Path(ref["path"]).resolve() == Path(expected["path"]).resolve():
            if ref.get("sha256") != expected["sha256"]:
                raise ValueError("Context chain selected parent result hash mismatch.")
            return prior["sources"], {"status": "verified_selected_parent", "result_ref": expected}
    # Do not discover or open an unselected ancestor. 为什么要有它：matching
    # material IDs alone cannot expand the explicitly selected lineage.
    return [], _unknown("parent_result_not_among_selected_segments")


def inspect_context_chain(**selection):
    """Reuse TraceService's run/ref checks; never write to execution records."""
    if selection.get("include_local_raw") is not True:
        raise ValueError("Context chain requires explicit --include-local-raw.")
    # Do not base exact-byte assessment on TraceService's sanitized raw display.
    view = TraceService().inspect_product_run(**{**selection, "include_local_raw": False})
    segments, previous = [], []
    for selected in view["segments"]:
        root = Path(selected["run_root"])
        manifest = _bound_record(selected["manifest_ref"], root)
        result = _bound_record(selected["result_ref"], root)
        inherited, parent_link = _selected_parent_sources(manifest, previous)
        sources = [*inherited, {"segment": selected["segment"], "manifest_ref": selected["manifest_ref"],
                               "observations": manifest["execution_observations"]}]
        rows = [_model_record(call, manifest, root, sources) for call in selected["calls"]]
        parents = {call["request_span_id"] for call in selected["calls"]}
        rows.extend(_prepared_record(row, root) for row in manifest["execution_observations"].values()
                    if row.get("name") == "model.request" and row["id"] not in parents)
        rows.extend(value for row in manifest["execution_observations"].values()
                    if (value := _observation_record(row, root)) is not None)
        rows.sort(key=lambda row: (row["started_at"] or "", row["id"]))
        stages = {}
        for stage, budget_name in (("requirements", "requirement_projection"), ("findings", "requirement_findings"),
                                   ("query", None), ("planning", "planning"), ("patch", "initial_patch")):
            calls = [row["id"] for row in rows if row["kind"] == "model" and row["stage"] == stage]
            budget = (selected.get("model_call_budget") or {}).get("by_stage") or {}
            used = budget.get(budget_name, {}).get("consumed")
            decisions = [row for row in rows if stage == "planning" and row["stage"] == "planning_gate"]
            no_invocations = bool(decisions) and all(
                (item := row["result"]["recorded_decision"])["receipt_status"] == "verified_bytes"
                and all(type(item.get("selection", {}).get(key)) is int and item["selection"][key] == 0
                        for key in ("model_turns_attempted", "model_responses_received")) for row in decisions)
            stages[stage] = {"record_ids": calls, "status": "observed" if calls else
                             "decision_observed" if decisions else "unknown",
                             "decision_record_ids": [row["id"] for row in decisions],
                             "model_invocation_status": "observed" if calls else
                             "not_invoked_by_recorded_gates" if no_invocations else "unknown",
                             "recorded_budget_consumed": used,
                             "request_records_without_generation": [row["id"] for row in rows
                                 if row["kind"] == "request_without_generation" and row["stage"] == stage],
                             "basis": "selected_generation_records_and_recorded_stage_budget"}
        terminal = {key: result.get(key) for key in (
            "completion_classification", "current_stage", "product_execution_result", "blockers",
            "patch_payload_parser_entered", "actual_write_performed", "build_summary", "runtime_summary")}
        product = terminal["product_execution_result"]
        if isinstance(product, dict):
            terminal["product_execution_result"] = {key: product.get(key) for key in (
                "run_id", "request_id", "feature_id", "requested_completion_scope", "platform_status",
                "execution_disposition", "failure_stage", "side_effects_may_have_started", "terminal_node", "blockers")}
        terminal["detail_basis"] = "selected_result_ref; variant payload and full artifacts remain in the original"
        segments.append({"segment": selected["segment"], "run_root": str(root),
                         "manifest_ref": selected["manifest_ref"], "result_ref": selected["result_ref"],
                         "trace": selected["trace"], "stages": stages, "records": rows,
                         "parent_link": parent_link,
                         "recorded_reassessment": selected.get("initial_findings_reassessment"),
                         "recorded_diagnostics": selected["diagnostics"],
                         "terminal": terminal, "cost": _cost(selected["calls"], [
                             row for row in rows if row["kind"] == "request_without_generation"])})
        previous.append({"result_ref": selected["result_ref"], "sources": sources})
    return {"schema_version": "product_context_chain_v2", "run_id": view["run_id"], "read_only": True,
            "scope": "only_explicitly_selected_segments_not_all_later_task_history",
            "inspection_model_calls": 0, "segments": segments,
            "last_selected_result_ref": segments[-1]["result_ref"],
            "quality_assessment": {
                "input_semantic_completeness": _unknown("no_independent_fact_set"),
                "decision_correctness": _unknown("no_independent_stage_judgments"),
                "task_or_cost_improvement": _unknown("no_comparable_paired_run")},
            "limits": ["Material links show supplied bytes, not model understanding or utilization.",
                       "Admission and HTTP completion are not independent semantic judgments.",
                       "Recorded model decisions are observations, not reference answers.",
                       "Baseline compilation is not task Build; missing Runtime remains unknown.",
                       "A route target is not proof that its destination executed."]}


def render_context_chain(report):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [f"# 上下文关联：{report['run_id']}", "",
             "只读原件投影；输入事实覆盖、语义决策正确性和收益尚无独立判定，均为 unknown。", ""]
    for segment in report["segments"]:
        lines += [f"## {segment['segment']}", "",
                  f"原件：[manifest]({Path(segment['manifest_ref']['path']).as_posix()}) · "
                  f"[result]({Path(segment['result_ref']['path']).as_posix()})", "",
                  "| 阶段 / 记录 | 收到什么 | 判断依据 | 实际结果 |",
                  "|---|---|---|---|"]
        for row in segment["records"]:
            if row["kind"] == "model":
                payloads = row["input"]["payloads"]
                fields = ", ".join(dict.fromkeys(k for p in payloads for k in p["fields"])) or "unknown"
                checks = row["judgment"]["contract_checks"]
                admission = [a.get("status") for group in checks for a in group["recorded_attempts"]]
                summary = row["result"]["model_declared_output"]
                outcome = {"transport": row["result"]["transport"], "output_fields": list(summary.get("fields", {}))}
                if "relationship_counts" in summary:
                    outcome["relationship_counts"] = summary["relationship_counts"]
                if row["result"]["query_execution_links"]:
                    outcome["query_execution_links"] = row["result"]["query_execution_links"]
                matches = [m for p in payloads for material in (p["materials"] or [])
                           for m in material["producer_matches"]]
                outcome["material_origins"] = [{"segment": m["segment"], "observation_id": m["observation_id"]}
                                               for m in matches]
                outcome["messages_comparison"] = row["input"]["native_messages_comparison"]
                outcome["schema_comparison"] = row["input"]["native_schema_comparison"]
                ref = row["input"]["refs"].get("request")
                if ref:
                    fields = f"[请求原件]({Path(ref['path']).as_posix()})：" + fields
                verdict = f"父阶段契约记录 {admission or 'unknown'}；语义 unknown"
            else:
                fields = json.dumps(row["input"], ensure_ascii=False)
                outcome = row["result"]["recorded_decision"]
                verdict = "执行记录；独立语义判定 unknown"
            lines.append(f"| {cell(row['stage'])} / `{row['id']}` | {cell(fields)} | {verdict} | "
                         f"{cell(json.dumps(outcome, ensure_ascii=False))} |")
        lines += ["", "父段关联：`" + json.dumps(segment["parent_link"], ensure_ascii=False) + "`", "",
                  "阶段入口与模型调用：`" + json.dumps(segment["stages"], ensure_ascii=False) + "`", "",
                  "已记录补查汇总：", "```json", json.dumps(segment["recorded_reassessment"], ensure_ascii=False, indent=2), "```", "",
                  "本段终点（保留首因）：", "```json", json.dumps(segment["terminal"], ensure_ascii=False, indent=2), "```", "",
                  "成本：`" + json.dumps(segment["cost"], ensure_ascii=False) + "`", ""]
    return "\n".join(lines) + "\n"
