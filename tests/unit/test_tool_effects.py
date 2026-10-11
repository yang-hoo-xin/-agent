"""Counterexamples for tool effectiveness and recovery overclaiming."""
import hashlib
import json

import pytest

from src.mod_agent.evaluation.tool_effects import extract_tool_effects


def selection(tmp_path, rows):
    path = tmp_path / "run_manifest.json"
    manifest = {"execution_trace": {"trace_id": "trace"},
                "execution_observations": {r["id"]: r for r in rows}}
    raw = json.dumps(manifest).encode()
    path.write_bytes(raw)
    return {"schema_version": "product_task_measurement_v1", "run_id": "run",
        "segments": [{"run_root": str(tmp_path), "segment_index": 0,
            "manifest_ref": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}}],
        "model": {"usage": {"input_tokens": {"total": 12}}},
        "last_selected_terminal": {"status": "delivered"}}


def row(identity="1", **attrs):
    return {"id": identity, "kind": "tool", "name": "evidence.source_query",
        "status": "completed", "started_at": identity, "elapsed_ms": 3,
        "attributes": {"input_payload_sha256": "same", "tool_dispatch_performed": True,
            "tool_exit_code": 0, "retrieval_status": "source_observations_returned", **attrs}}


def test_success_is_not_usefulness_or_recovery_or_delivery(tmp_path):
    report = extract_tool_effects(selection(tmp_path, [row()]))
    call = report["observations"][0]
    assert call["first_effective"] is True
    assert call["content_usefulness"] == "unknown"
    assert call["recovery_success"] is None
    assert report["task_delivered"] is None


def test_no_match_is_completed_search_not_error(tmp_path):
    report = extract_tool_effects(selection(tmp_path, [row(tool_exit_code=1, retrieval_status="no_matches")]))
    assert report["observations"][0]["operation_effective"] is True
    assert report["observations"][0]["content_usefulness"] == "unknown"


@pytest.mark.parametrize(("status", "category"), [
    ("query_terms_missing", "parameter_error"), ("source_root_missing", "environment_failure"),
    ("tool_failed", "unknown")])
def test_structured_failure_classification(tmp_path, status, category):
    report = extract_tool_effects(selection(tmp_path, [row(retrieval_status=status)]))
    assert report["observations"][0]["operation_effective"] is False
    assert report["observations"][0]["failure_category"] == category


def test_later_valid_result_does_not_prove_task_continued(tmp_path):
    report = extract_tool_effects(selection(tmp_path, [row("1", retrieval_status="source_root_missing"), row("2")]))
    call = report["observations"][1]
    assert call["later_effective_after_failure"] == ["1"]
    assert call["recovery_success"] is None
    assert report["repeated_input_cost"]["tool_elapsed_ms_sum"] == 3
    assert report["recovery_cost"]["model_calls"] is None


def test_different_queries_are_not_retries(tmp_path):
    report = extract_tool_effects(selection(tmp_path, [row(), row("2", input_payload_sha256="other")]))
    assert report["repeated_input_cost"]["observed_tool_calls"] == 0


def test_duplicate_observations_not_added(tmp_path):
    measured = selection(tmp_path, [row()])
    measured["segments"].append(measured["segments"][0])
    assert extract_tool_effects(measured)["counts"]["observed"] == 1


def test_manifest_drift_rejected(tmp_path):
    measured = selection(tmp_path, [row()])
    (tmp_path / "run_manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        extract_tool_effects(measured)


def test_unbound_body_rejected(tmp_path):
    ref = {"path": str(tmp_path / "body.json"), "sha256": "wrong"}
    (tmp_path / "body.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        extract_tool_effects(selection(tmp_path, [row(local_detail_refs={"request": ref})]))


def test_external_body_rejected_before_read(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        extract_tool_effects(selection(tmp_path, [row(local_detail_refs={
            "request": {"path": str(tmp_path.parent / "outside.json"), "sha256": "unused"}})]))


def test_unknown_tool_completed_is_unknown(tmp_path):
    r = row()
    r["name"] = "future.tool"
    assert extract_tool_effects(selection(tmp_path, [r]))["observations"][0]["operation_effective"] is None


def test_cli_option_embeds_effects_without_execution(tmp_path, monkeypatch, capsys):
    from scripts import measure_product_task as cli
    measured = selection(tmp_path, [row()])
    monkeypatch.setattr(cli, "measure_product_task", lambda **_: measured)
    assert cli.main(["--allowed-root", str(tmp_path), "--run-root", str(tmp_path),
                     "--run-id", "run", "--tool-effects"]) == 0
    assert json.loads(capsys.readouterr().out)["tool_effects"]["inspection_model_calls"] == 0


def body(tmp_path, name, value):
    path = tmp_path / name
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def inspection(**attrs):
    r = row(input_payload_sha256=None, observation_queued=True, encoded_payload_sha256="payload",
            source_observation_id="read-1", source_snapshot_sha256="snapshot", encoded_payload_bytes=12,
            **attrs)
    r["name"] = "source.inspect"
    return r


def test_verified_parameter_body_fallback(tmp_path):
    ref = body(tmp_path, "request.json", {"binding_id": "edit_binding_001"})
    r = inspection(local_detail_refs={"request": ref})
    call = extract_tool_effects(selection(tmp_path, [r]))["observations"][0]
    assert call["request_fingerprint"] == ref["sha256"]
    assert call["request_fingerprint_basis"] == "verified_request_bytes_pure_binding_parameter"
    assert call["first_effective"] is True


def test_request_wrapper_not_guessed_or_normalized(tmp_path):
    ref = body(tmp_path, "request.json", {"binding_id": "edit_binding_001", "turn_index": 2})
    call = extract_tool_effects(selection(tmp_path, [inspection(local_detail_refs={"request": ref})]))["observations"][0]
    assert call["request_fingerprint"] is None
    assert call["first_effective"] is None


def test_queued_error_payload_is_not_success(tmp_path):
    ref = body(tmp_path, "response.json", {"status": "not_executed", "error_code": "PATCH_AGENT_TOOL_RESULT_BUDGET_EXCEEDED"})
    call = extract_tool_effects(selection(tmp_path, [inspection(local_detail_refs={"response": ref})]))["observations"][0]
    assert call["operation_effective"] is False


def test_queue_without_source_observation_does_not_establish_read(tmp_path):
    r = inspection()
    del r["attributes"]["source_observation_id"]
    call = extract_tool_effects(selection(tmp_path, [r]))["observations"][0]
    assert call["operation_effective"] is None


def test_successful_historical_source_read_without_arguments_stays_first_unknown(tmp_path):
    call = extract_tool_effects(selection(tmp_path, [inspection()]))["observations"][0]
    assert call["operation_effective"] is True
    assert call["first_effective"] is None
