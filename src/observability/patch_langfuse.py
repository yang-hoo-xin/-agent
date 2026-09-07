"""Metadata-only historical Patch imports through Langfuse's public HTTP APIs.

This consumer never runs an Agent, verifier, Graph, or Artifact write. Imported
observations are snapshots at import time, not fabricated historical executions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.observability.patch_execution_index import project_patch_executions

IMPORT_VERSION = "patch_langfuse_metadata_import_v1"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
_HEX = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
_SAFE_LABEL_VALUES = frozenset({
    "terminal", "partial", "blocked", "success", "failed", "responded", "requested", "accepted", "rejected",
    "passed", "behavior_failed", "identity_failed", "infrastructure_failed", "needs_evidence", "unknown", "incomplete",
    "executed", "reused", "initial", "correction", "behavior_correction", "recorded", "not_executed", "dispatch_started",
    "patch_implementation", "evidence", "planning", "validator", "environment", "evidence_query", "evidence_findings",
    "generate_patch_proposal", "patch_proposal", "proposal_review", "review_proposal", "dry_run_apply", "implementation_plan",
    "exact_diff_approval", "model_admission", "patch_generation", "source_validation", "workflow", "configuration_admission",
    "live_provider_response", "verified_prior_response", "current_source_read", "prior_visible_source_reuse",
    "journal_claim_live_response_with_verified_ref", "journal_claim_replay_with_verified_response_refs",
    "requested_send_unconfirmed", "unknown_response_evidence_unavailable",
    "journal_claim_with_reference_checks_not_independent_send_proof",
    "explicit_journal_field_with_retained_report_not_new_execution",
    "PATCH_AGENT_UPSTREAM_REQUESTED", "PATCH_BEHAVIOR_CORRECTION_FAILED", "PATCH_CONTINUATION_MODEL_CALL_BUDGET_EXHAUSTED",
    "LocalEntryError", "PatchGenerationError", "PatchContinuationError", "ValueError", "TimeoutError",
})


class PatchLangfuseError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else _json(value)).hexdigest()


def _digest(value: Any) -> str | None:
    return value if isinstance(value, str) and _HEX.fullmatch(value) else None


def _label(value: Any) -> str | None:
    # Only machine labels are eligible. Free-form explanations are never sent.
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else None


def _ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {key: _digest(value.get(key)) for key in ("sha256", "artifact_hash", "output_sha256")}
    result["integrity"] = _label(value.get("integrity"))
    if isinstance(value.get("path"), str):
        result["locator_sha256"] = _sha(value["path"].encode())
    return {key: item for key, item in result.items() if item is not None}


def _numbers(value: Any) -> dict[str, int | float | bool]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if _label(key) and
            (type(item) in (bool, int) or type(item) is float and math.isfinite(item))}


def _metadata(row: Mapping[str, Any], *, labels=(), numbers=(), digests=(), refs=()):
    result = {}
    for key in labels:
        value = row.get(key)
        if isinstance(value, str):
            result[key] = value if value in _SAFE_LABEL_VALUES else "redacted:sha256:" + _sha(value.encode())
    for key in numbers:
        value = row.get(key)
        if type(value) in (bool, int) or type(value) is float and math.isfinite(value):
            result[key] = value
    for key in digests:
        if _digest(row.get(key)) is not None:
            result[key] = row[key]
    for key in refs:
        result[key] = _ref(row.get(key))
    return result


def _attribute(key, value):
    if type(value) is bool:
        payload = {"boolValue": value}
    elif type(value) is int:
        payload = {"intValue": str(value)}
    elif type(value) is float:
        payload = {"doubleValue": value}
    else:
        payload = {"stringValue": value if isinstance(value, str) else _json(value).decode()}
    return {"key": key, "value": payload}


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PatchLangfuseError("IMPORT_TIME_REQUIRES_EXPLICIT_TIMEZONE")
    return value.astimezone(timezone.utc)


def _read_verified_json(ref):
    if not isinstance(ref, dict) or ref.get("integrity") != "verified_bytes":
        return None
    try:
        raw = Path(ref["path"]).read_bytes()
        if len(raw) > MAX_PAYLOAD_BYTES or _sha(raw) != ref.get("sha256"):
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, KeyError):
        return None


def _verified_check_counts(evaluation):
    """Import measured local checks, never convert them into model qualification."""
    if (evaluation.get("execution_observation") != "executed" or evaluation.get("admission") != "accepted"
            or evaluation.get("generated_changes_report_link") != "matching_explicit_identity"
            or evaluation.get("materialized_code_report_link") != "matching_explicit_identity"
            or evaluation.get("code_response_link") != "matching_explicit_response_hash"):
        return None
    report = _read_verified_json(evaluation.get("report_ref"))
    matrix = _read_verified_json(evaluation.get("verification_ref"))
    if report is None or matrix is None:
        return None
    recorded_matrix = report.get("verification_ref")
    selected_matrix = evaluation.get("verification_ref")
    if (not isinstance(recorded_matrix, dict) or not isinstance(selected_matrix, dict)
            or not isinstance(recorded_matrix.get("path"), str)
            or any(recorded_matrix.get(key) != selected_matrix.get(key) for key in ("path", "sha256"))
            or _digest(recorded_matrix.get("sha256")) is None):
        return None
    # A matching declared output hash is insufficient when its retained bytes
    # are missing or corrupt. The projection exposes both pieces independently.
    responses = evaluation.get("code_response_refs")
    if not isinstance(responses, list) or not any(isinstance(ref, dict)
            and ref.get("integrity") == "verified_bytes"
            and ref.get("output_sha256") == evaluation.get("model_response_sha256")
            for ref in responses):
        return None
    if (report.get("execution_origin") != "executed"
            or report.get("status") != evaluation.get("status")
            or _digest(report.get("source_snapshot_sha256")) is None
            or report["source_snapshot_sha256"] != evaluation.get("source_snapshot_sha256")):
        return None
    # Older matrices bind code transitively through the report's exact matrix
    # reference. Newer matrices may also state identities; contradictory values
    # must never be ignored merely because their check counts happen to match.
    for key in ("source_snapshot_sha256", "generated_changes_sha256", "materialized_code_identity", "verification_identity"):
        values = [owner[key] for owner in (evaluation, report, matrix) if key in owner]
        if values and any(value != values[0] for value in values[1:]):
            return None
    rows = matrix.get("checks")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict)
            or not isinstance(row.get("check"), str) or type(row.get("passed")) is not bool for row in rows):
        return None
    if len({row["check"] for row in rows}) != len(rows):
        return None
    failed = sum(not row["passed"] for row in rows)
    summary = evaluation.get("verification_summary") or {}
    if (type(summary.get("checks")) is not int or type(summary.get("failed_checks")) is not int
            or summary["checks"] != len(rows) or summary["failed_checks"] != failed):
        return None
    if (type(matrix.get("executions")) is not int or matrix["executions"] < 1
            or type(summary.get("executions")) is not int or summary["executions"] != matrix["executions"]):
        return None
    reported_summary = report.get("verification_summary")
    if reported_summary is not None and (not isinstance(reported_summary, dict)
            or any(type(reported_summary.get(key)) is not int or reported_summary[key] != summary[key]
                   for key in ("checks", "failed_checks", "executions"))):
        return None
    if report.get("status") != ("behavior_failed" if failed else "passed"):
        return None
    return len(rows), failed


@dataclass(frozen=True)
class PatchLangfuseImport:
    artifact_store_root: str
    attempt_locator: str
    imported_at: str
    projection_sha256: str
    journal_sha256: str
    trace_id: str
    otlp: dict[str, Any]
    scores: tuple[dict[str, Any], ...]
    observation_ids: tuple[str, ...]

    def preview(self):
        return {"schema_version": IMPORT_VERSION, "historical_import": True,
                "timing_basis": "import_snapshot_not_original_execution", "original_event_time": "unknown",
                "trace_id": self.trace_id, "journal_sha256": self.journal_sha256,
                "observation_ids": list(self.observation_ids), "score_ids": [score["id"] for score in self.scores],
                "otlp": self.otlp, "scores": list(self.scores), "source_or_prompt_uploaded": False,
                "new_model_calls": 0, "new_verifier_executions": 0, "network_requests": 0}


def prepare_patch_import(artifact_store_root: str | Path, *, attempt_locator: str,
                         imported_at: datetime | None = None) -> PatchLangfuseImport:
    """Read one retained terminal attempt and prepare whitelisted JSON without I/O sinks."""
    timestamp = _utc(imported_at or datetime.now(timezone.utc))
    projection = project_patch_executions(artifact_store_root, attempt_locator=attempt_locator)
    if projection["match_count"] != 1 or projection["unreadable_journals"]:
        raise PatchLangfuseError("EXACTLY_ONE_READABLE_ATTEMPT_REQUIRED")
    row = projection["attempts"][0]
    if row["journal_identity_checks"]["terminal_result_hash"]["status"] != "verified":
        raise PatchLangfuseError("VERIFIED_TERMINAL_JOURNAL_REQUIRED")
    journal_hash = row["journal_ref"]["sha256"]
    trace_id = _sha(("patch-journal:" + journal_hash).encode())[:32]
    root_id = _sha((trace_id + ":root").encode())[:16]
    nanos = str(int(timestamp.timestamp()) * 1_000_000_000 + timestamp.microsecond * 1000)
    common = {"historical_import": True, "original_event_time": "unknown",
              "timing_basis": "import_snapshot_not_original_execution", "source_journal_sha256": journal_hash,
              "import_version": IMPORT_VERSION, "source_or_prompt_included": False}
    spans = []

    def add(kind, ordinal, data):
        span_id = root_id if kind == "attempt" else _sha(f"{trace_id}:{kind}:{ordinal}".encode())[:16]
        metadata = {**common, "record_kind": kind, "record_ordinal": ordinal, **data}
        attributes = [_attribute("langfuse.observation.type", "event"),
                      _attribute("langfuse.trace.name", "Patch/Repair historical import"),
                      {"key": "langfuse.trace.tags", "value": {"arrayValue": {"values": [
                          {"stringValue": "historical_import"}, {"stringValue": "metadata_only"}]}}},
                      *[_attribute("langfuse.observation.metadata." + key, value) for key, value in metadata.items()]]
        span = {"traceId": trace_id, "spanId": span_id, "name": "historical." + kind,
                "kind": 1, "startTimeUnixNano": nanos, "endTimeUnixNano": nanos, "attributes": attributes}
        if kind != "attempt":
            span["parentSpanId"] = root_id
        spans.append(span)
        return span_id

    root_meta = _metadata(row.get("terminal") or {}, labels=("status", "terminal_stage", "stopped_before"))
    root_meta.update(run_id_sha256=_sha(str(row.get("run_id")).encode()),
                     feature_id_sha256=_sha(str(row.get("feature_id")).encode()),
                     counts_recorded=_numbers(row.get("budget_and_counts_recorded")),
                     reference_integrity_counts=_numbers(row.get("reference_integrity_counts")),
                     original_execution_duration_seconds="unknown", product_success_not_inferred=True)
    root_meta["failure"] = _metadata(row.get("failure") or {}, labels=("code", "failure_class", "stage"))
    add("attempt", 0, root_meta)
    for index, turn in enumerate(row["worker_turns"]):
        data = _metadata(turn, labels=("status", "response_origin", "send_observation", "send_observation_basis"),
                         numbers=("segment_index", "turn_index"), digests=("request_sha256",), refs=("response_ref", "original_response_ref"))
        data["recorded_usage"] = _numbers(turn.get("usage"))
        data["provider_request_identity"] = _metadata(turn.get("provider_request_identity") or {},
            digests=("provider_body_sha256",), numbers=("provider_body_utf8_bytes",))
        add("model_turn_record", index, data)
    for index, call in enumerate(row["tool_execution"]):
        data = _metadata(call, labels=("phase", "status", "execution_observation", "observation_origin"),
                         numbers=("segment_index", "turn_index", "dispatch_started", "read_cost"), digests=("arguments_sha256",))
        name = call.get("tool")
        data["tool"] = name if name in {"inspect_plan_binding_source", "request_patch_upstream"} else "other_recorded_tool"
        data["binding_id_sha256"] = _sha(str(call.get("binding_id")).encode())
        data["observation_summaries"] = [_metadata(item,
            numbers=("admitted_to_model", "payload_admitted", "consumed_in_model_turn", "read_cost", "encoded_payload_bytes"),
            digests=("observation_sha256", "source_hash", "source_snapshot_sha256", "encoded_payload_sha256"))
            for item in call.get("returned_observations", [])]
        add("tool_record", index, data)
    for index, response in enumerate(row["code_responses"]):
        add("code_response_reference", index, _ref(response))
    scores = []
    for index, evaluation in enumerate(row["behavior_evaluations"]):
        data = _metadata(evaluation, labels=("status", "failure_owner", "execution_observation", "execution_basis", "admission"),
                         numbers=("segment_index", "evaluation_index", "callback_invoked"),
                         refs=("report_ref", "verification_ref", "reused_from_report_ref"),
                         digests=("generated_changes_sha256", "model_response_sha256", "source_snapshot_sha256"))
        data["materialized_code_identity"] = _metadata(evaluation.get("materialized_code_identity") or {},
            digests=("baseline_sha256", "code_sha256"))
        data["summary_recorded"] = _numbers(evaluation.get("verification_summary"))
        counts = _verified_check_counts(evaluation)
        data["score_eligible"] = counts is not None
        data["score_basis"] = ("report_binds_retained_code_and_exact_matrix_local_checks" if counts is not None
                               else "not_emitted_missing_or_inconsistent_bound_verification")
        span_id = add("behavior_verification_record", index, data)
        if counts is not None:
            checks, failures = counts
            scores.append({"id": _sha(f"{trace_id}:{span_id}:local_check_pass_fraction".encode()),
                "traceId": trace_id, "observationId": span_id, "name": "historical_local_check_pass_fraction",
                "value": (checks - failures) / checks, "dataType": "NUMERIC",
                "comment": f"historical_import; {checks - failures}/{checks} bound local checks; not cross-task qualification or Runtime."})
    for index, turn in enumerate(row.get("upstream_provider_turns", [])):
        data = _metadata(turn, labels=("role", "status", "send_observation", "send_observation_basis"),
                         refs=("request_ref", "response_ref"))
        data["recorded_usage"] = _numbers(turn.get("usage"))
        add("upstream_provider_record", index, data)
    otlp = {"resourceSpans": [{"resource": {"attributes": [_attribute("service.name", "mod-agent-history-import")]},
        "scopeSpans": [{"scope": {"name": "mod_agent.patch_history", "version": IMPORT_VERSION}, "spans": spans}]}]}
    if len(_json(otlp)) > MAX_PAYLOAD_BYTES:
        raise PatchLangfuseError("HISTORICAL_PAYLOAD_TOO_LARGE")
    return PatchLangfuseImport(str(Path(artifact_store_root).resolve()), attempt_locator, timestamp.isoformat(),
        _sha(row), journal_hash, trace_id, otlp, tuple(scores), tuple(span["spanId"] for span in spans))


@dataclass
class LangfuseHttpTransport:
    base_url: str
    public_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    timeout_seconds: float = 10.0
    readback_attempts: int = 3
    readback_delay_seconds: float = 0.5
    _submitted: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if (url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in {"", "/"}
                or url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}):
            raise PatchLangfuseError("LANGFUSE_BASE_URL_INVALID")
        if not self.public_key or not self.secret_key:
            raise PatchLangfuseError("LANGFUSE_PROJECT_KEYS_REQUIRED")
        if (type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds)
                or self.timeout_seconds <= 0 or type(self.readback_attempts) is not int
                or not 1 <= self.readback_attempts <= 5 or type(self.readback_delay_seconds) not in (int, float)
                or not math.isfinite(self.readback_delay_seconds) or not 0 <= self.readback_delay_seconds <= 2):
            raise PatchLangfuseError("LANGFUSE_TRANSPORT_BUDGET_INVALID")
        self.base_url = self.base_url.rstrip("/")

    @classmethod
    def from_environment(cls):
        return cls(base_url=os.environ.get("LANGFUSE_BASE_URL", ""),
                   public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
                   secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""))

    def _request(self, method, path, *, params=None, payload=None):
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False, trust_env=False,
                              auth=(self.public_key, self.secret_key)) as client:
                response = client.request(method, self.base_url + path, params=params, json=payload,
                    headers={"Content-Type": "application/json", "x-langfuse-ingestion-version": "4"})
            if not 200 <= response.status_code < 300:
                raise PatchLangfuseError("LANGFUSE_HTTP_" + str(response.status_code))
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise PatchLangfuseError("LANGFUSE_RESPONSE_TOO_LARGE")
            value = response.json() if response.content else {}
            if not isinstance(value, dict):
                raise PatchLangfuseError("LANGFUSE_RESPONSE_INVALID")
            return value
        except PatchLangfuseError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise PatchLangfuseError("LANGFUSE_TRANSPORT_" + type(exc).__name__) from None

    def read_trace(self, trace_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", trace_id):
            raise PatchLangfuseError("LANGFUSE_TRACE_ID_INVALID")
        rows, cursor = [], None
        for _ in range(5):
            params = {"traceId": trace_id, "fields": "core,basic,metadata", "limit": 1000}
            if cursor is not None:
                params["cursor"] = cursor
            result = self._request("GET", "/api/public/v2/observations", params=params)
            if not isinstance(result.get("data"), list):
                raise PatchLangfuseError("LANGFUSE_OBSERVATIONS_RESPONSE_INVALID")
            for row in result["data"]:
                if not isinstance(row, dict) or row.get("traceId") != trace_id or not isinstance(row.get("id"), str):
                    raise PatchLangfuseError("LANGFUSE_OBSERVATION_IDENTITY_MISMATCH")
            rows.extend(result["data"])
            meta = result.get("meta") or {}
            if not isinstance(meta, dict):
                raise PatchLangfuseError("LANGFUSE_OBSERVATIONS_RESPONSE_INVALID")
            next_cursor = meta.get("cursor")
            if not next_cursor:
                return rows
            if next_cursor == cursor:
                break
            cursor = next_cursor
        raise PatchLangfuseError("LANGFUSE_READBACK_PAGE_BUDGET_EXHAUSTED")

    def read_observation(self, trace_id: str, observation_id: str):
        return next((row for row in self.read_trace(trace_id) if row["id"] == observation_id), None)

    def read_score(self, score_id: str):
        result = self._request("GET", "/api/public/v3/scores", params={"id": score_id, "fields": "subject", "limit": 100})
        if not isinstance(result.get("data"), list):
            raise PatchLangfuseError("LANGFUSE_SCORES_RESPONSE_INVALID")
        return next((row for row in result["data"] if isinstance(row, dict) and row.get("id") == score_id), None)

    def _readback(self, batch):
        observed = {row["id"]: row for row in self.read_trace(batch.trace_id)}
        mismatches = [key for key in batch.observation_ids if key in observed
                      and (not isinstance(observed[key].get("metadata"), dict)
                           or observed[key]["metadata"].get("source_journal_sha256") != batch.journal_sha256)]
        if mismatches:
            raise PatchLangfuseError("LANGFUSE_IMPORTED_SOURCE_IDENTITY_MISMATCH")
        missing_scores = []
        for expected in batch.scores:
            score = self.read_score(expected["id"])
            if score is None:
                missing_scores.append(expected["id"])
            elif (score.get("name") != expected["name"] or score.get("value") != expected["value"]
                    or not isinstance(score.get("subject"), dict)
                    or (score.get("subject") or {}).get("traceId") != batch.trace_id
                    or (score.get("subject") or {}).get("id") != expected["observationId"]):
                raise PatchLangfuseError("LANGFUSE_SCORE_IDENTITY_MISMATCH")
        return {"missing_observation_ids": [key for key in batch.observation_ids if key not in observed],
                "missing_score_ids": missing_scores, "observed_count": len(observed)}

    def verify_import(self, batch):
        last = None
        for index in range(self.readback_attempts):
            last = self._readback(batch)
            if not last["missing_observation_ids"] and not last["missing_score_ids"]:
                return {"status": "verified_remote_readback", "trace_id": batch.trace_id, **last}
            if index + 1 < self.readback_attempts:
                time.sleep(self.readback_delay_seconds)
        return {"status": "readback_pending", "trace_id": batch.trace_id, **last}

    def import_history(self, batch: PatchLangfuseImport):
        """Submit once; uncertainty requires readback, never an automatic POST retry."""
        result = {"trace_id": batch.trace_id, "historical_import": True,
                  "product_state_changed": False, "observation_posts": 0, "score_posts": 0}
        try:
            current = prepare_patch_import(batch.artifact_store_root, attempt_locator=batch.attempt_locator,
                                           imported_at=datetime.fromisoformat(batch.imported_at))
            if current.projection_sha256 != batch.projection_sha256 or _json(current.preview()) != _json(batch.preview()):
                raise PatchLangfuseError("HISTORICAL_SOURCE_CHANGED_SINCE_PREPARATION")
            existing = self._readback(batch)
            if not existing["missing_observation_ids"] and not existing["missing_score_ids"]:
                return {**result, "status": "already_present", **existing}
            if batch.trace_id in self._submitted or existing["observed_count"]:
                return {**result, "status": "reconciliation_required_no_resend", **existing}
            self._submitted.add(batch.trace_id)
            result["observation_posts"] = 1
            response = self._request("POST", "/api/public/otel/v1/traces", payload=batch.otlp)
            partial = response.get("partialSuccess") or {}
            if not isinstance(partial, dict):
                raise PatchLangfuseError("LANGFUSE_OTLP_RESPONSE_INVALID")
            if int(partial.get("rejectedSpans") or 0) > 0:
                return {**result, "status": "partial_ingestion", "rejected_spans": int(partial["rejectedSpans"])}
            for score in batch.scores:
                result["score_posts"] += 1
                self._request("POST", "/api/public/scores", payload=score)
            return {**result, **self.verify_import(batch)}
        except (PatchLangfuseError, OSError, ValueError) as exc:
            return {**result, "status": "export_failed_open", "error_code": getattr(exc, "code", type(exc).__name__),
                    "remote_delivery_uncertain": bool(result["observation_posts"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Metadata-only historical Patch telemetry, outside the product workflow.")
    parser.add_argument("mode", choices=("prepare", "send", "verify"))
    parser.add_argument("--artifact-store-root", required=True)
    parser.add_argument("--attempt-locator", required=True)
    args = parser.parse_args(argv)
    try:
        batch = prepare_patch_import(args.artifact_store_root, attempt_locator=args.attempt_locator)
        if args.mode == "prepare":
            result = batch.preview()
        else:
            client = LangfuseHttpTransport.from_environment()
            result = client.import_history(batch) if args.mode == "send" else client.verify_import(batch)
    except (PatchLangfuseError, OSError, ValueError) as exc:
        result = {"status": "export_failed_open", "error_code": getattr(exc, "code", type(exc).__name__), "product_state_changed": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") in {"export_failed_open", "partial_ingestion"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
