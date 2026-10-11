"""Retained native Product observations and Findings diagnostics; no Cloud/model."""
import hashlib
import json

import pytest

from src.observability import patch_live_langfuse as live
from src.observability.patch_langfuse_query import summarize_execution


def native_row():
    return {"id": "1" * 16, "trace_id": "a" * 32, "parent_id": None,
            "name": "requirements.coverage", "kind": "span", "status": "failed",
            "started_at": "2026-09-20T06:08:00.161367+00:00",
            "finished_at": "2026-09-20T06:09:01.853593+00:00",
            "attributes": {"trace_scope": "product_execution"}}


def audit():
    return [{"attempt_index": 1, "status": "rejected",
             "error_code": "REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID",
             "rejected_output_sha256": "b" * 64,
             "diagnostic": {"relation_index": 1, "relationship": "support", "parent_roles": ["change"],
                            "edit_target_evidence_ids": ["private-source-id"], "evidence_ids": ["private-source-id"],
                            "unresolved_gaps": ["PRIVATE_SOURCE_TEXT"], "rule": "PRIVATE_RULE_TEXT"}},
            {"attempt_index": 2, "status": "failed", "error_code": "PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED",
             "correction_payload_prepared": True, "correction_payload_sha256": "c" * 64,
             "response_schema_sha256": "d" * 64,
             "call_boundary": {"budget_stage": "requirement_findings", "reservation_succeeded": False,
                               "model_request_invoked": False, "model_transport_started": False,
                               "budget": {"maximum": 11, "consumed": 2, "remaining": 9,
                                          "by_stage": {"requirement_findings": {"maximum": 1, "consumed": 1, "remaining": 0}}}}}]


def metadata(payload):
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    return {a["key"].removeprefix("langfuse.observation.metadata."): next(iter(a["value"].values()))
            for a in span["attributes"] if a["key"].startswith("langfuse.observation.metadata.")}


def test_native_findings_rejection_and_budget_boundary_survive_without_free_text():
    row = native_row()
    row["attributes"]["requirement_findings_attempt_audit"] = audit()
    payload = live.build_patch_live_otlp(row)
    meta = metadata(payload)
    kept = json.loads(meta["requirement_findings_attempt_audit"])
    assert kept[0]["diagnostic"]["unresolved_gap_count"] == 1
    assert kept[0]["error_code"] == "REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID"
    assert kept[1]["call_boundary"]["model_transport_started"] is False
    assert kept[1]["call_boundary"]["budget"]["remaining"] == 9
    assert "PRIVATE" not in json.dumps(payload) and "private-source-id" not in json.dumps(payload)
    remote = {"id": row["id"], "traceId": row["trace_id"], "name": row["name"], "type": "SPAN",
              "metadata": {"requirement_findings_attempt_audit": kept}}
    result = summarize_execution(row["trace_id"], [remote])
    assert result["execution_tree"][0]["facts"]["requirement_findings_attempt_audit"] == kept


def test_missing_call_boundary_is_not_fabricated_false():
    row = native_row()
    values = audit()
    values[1].pop("call_boundary")
    values[1]["error_code"] = "private provider exception body"
    row["attributes"]["requirement_findings_attempt_audit"] = values
    kept = json.loads(metadata(live.build_patch_live_otlp(row))["requirement_findings_attempt_audit"])
    assert "call_boundary" not in kept[1]
    assert kept[1]["error_code"] == "unclassified_error"
    assert "private provider" not in json.dumps(kept)


def write_journal(tmp_path, row):
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps({"run_id": "run-test", "execution_observations": {row["id"]: row}}), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_retained_native_export_keeps_recorded_identity_and_times(tmp_path):
    row = native_row()
    path, digest = write_journal(tmp_path, row)
    prepared = live.prepare_product_journal_export(path, digest, trace_id=row["trace_id"])
    span = prepared["otlp"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == row["trace_id"] and span["spanId"] == row["id"]
    assert span["startTimeUnixNano"] == str(live._utc_nanos(row["started_at"]))
    assert span["endTimeUnixNano"] == str(live._utc_nanos(row["finished_at"]))
    meta = metadata(prepared["otlp"])
    assert meta["historical_import"] is True
    assert meta["timing_basis"] == "recorded_original_execution"
    assert meta["source_journal_sha256"] == digest
    assert "requirement_findings_attempt_audit" not in meta
    assert prepared["scores"] == []
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("change", ["hash", "trace", "missing_time"])
def test_retained_export_rejects_unbound_input(tmp_path, change):
    row = native_row()
    if change == "missing_time":
        row["finished_at"] = None
    path, digest = write_journal(tmp_path, row)
    with pytest.raises(ValueError):
        live.prepare_product_journal_export(path, "0" * 64 if change == "hash" else digest,
                                            trace_id="f" * 32 if change == "trace" else row["trace_id"])
