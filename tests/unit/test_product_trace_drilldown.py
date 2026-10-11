"""Local Product trace drill-down service and Controlled Agent rendering."""
from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.observability.dashboard.services.trace_service import TraceService

RUN_ID = "run-one"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("No network in local drill-down"))


def _write(path: Path, value: object) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value) if not isinstance(value, str) else value).encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _call(root: Path, trace: str, suffix: str, role: str, started: str, *, schema_failure=False,
          native_provider=False):
    request_ref = _write(root / "model_trace_bodies" / f"{suffix}.request.json", {
        "messages": [{"role": "system", "content": "MODEL_MESSAGES"},
                     {"role": "user", "content": "PUBLIC_REQUEST"}],
        "response_format": {"type": "object", "required": ["findings"], "properties": {
            "findings": {"type": "array", "minItems": 1, "maxItems": 2,
                         "items": {"type": "object", "required": ["evidence_ids"],
                                   "oneOf": [{"properties": {"relationship": {"const": "support"}}}]}}}},
        "max_tokens": 64,
    })
    response_ref = _write(root / "model_trace_bodies" / f"{suffix}.response.txt", '{"findings": []}')
    provider_ref = _write(root / "model_trace_bodies" / f"{suffix}.provider-request.json", {
        "model": "model-1", "messages": [{"role": "user", "content": "PRIVATE_PROVIDER_MESSAGE"}],
        "format": {"type": "object", "required": ["findings"], "properties": {
            "findings": {"type": "array", "minItems": 1, "maxItems": 2,
                         "items": {"type": "object", "required": ["evidence_ids"],
                                   "oneOf": [{"properties": {"relationship": {"const": "support"}}}]}}}},
        "stream": False, "think": False,
    }) if native_provider else None
    request_id, generation_id = f"req-{suffix}", f"gen-{suffix}"
    facts = {"model": "model-1", "provider": "local", "model_role": role,
             "transport_started": True, "response_received": True, "response_complete": True,
             "http_status": 200, "response_origin": "live_provider_response",
             "usage": {"input_tokens": 10, "output_tokens": 3},
             "input_payload_sha256": "a" * 64, "output_sha256": "b" * 64,
             "local_detail_refs": {"request": request_ref, "response": response_ref,
                                   **({"provider_request": provider_ref} if provider_ref else {})},
             **({"provider_request_sha256": provider_ref["sha256"], "provider_request_bytes": 100,
                 "provider_request_metadata": {"method": "POST", "destination": "http://127.0.0.1:11434/api/chat",
                    "response_format_sha256": "c" * 64}} if provider_ref else {})}
    observations = {
        request_id: {"id": request_id, "parent_id": "coverage", "trace_id": trace,
                     "name": "model.request", "kind": "span", "status": "completed",
                     "started_at": started, "finished_at": "2026-09-21T00:00:02+00:00",
                     "elapsed_ms": 1000, "attributes": facts},
        generation_id: {"id": generation_id, "parent_id": request_id, "trace_id": trace,
                        "name": "requirements.findings", "kind": "generation", "status": "completed",
                        "started_at": started, "finished_at": "2026-09-21T00:00:02+00:00",
                        "elapsed_ms": 900, "attributes": facts},
    }
    if schema_failure:
        observations["coverage"] = {"id": "coverage", "parent_id": None, "trace_id": trace,
            "name": "requirements.coverage", "kind": "span", "status": "failed",
            "started_at": started, "finished_at": "2026-09-21T00:00:03+00:00", "elapsed_ms": 2000,
            "attributes": {"requirement_findings_attempt_audit": [{"attempt_index": 2, "status": "failed",
                "error_code": "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
                "diagnostic": {"phase": "response_schema_admission",
                    "failure_category": "schema_required_property_missing",
                    "json_path": "$.findings[0].evidence_ids", "schema_keyword": "required",
                    "allowed_boundary": {"required_property": "evidence_ids"}}}]}}
    return observations


def run_records(tmp_path: Path):
    allowed = tmp_path / "runs"
    original = allowed / "hotkey" / RUN_ID
    original.mkdir(parents=True)
    original_result = {"run_id": RUN_ID, "status": "blocked", "model_call_count": 2,
        "model_call_budget": {"maximum": 11, "consumed": 2, "remaining": 9,
            "by_stage": {"requirement_findings": {"maximum": 1, "consumed": 1, "remaining": 0}}}}
    result_ref = _write(original / "run_result.json", original_result)
    original_manifest = {"run_id": RUN_ID, "status": "blocked", "model_call_count": 2,
        "terminal_record": result_ref,
        "execution_trace": {"trace_id": "1" * 32, "session_id": "session", "environment": "local",
                            "mode": "local_only", "cloud_readback": "not_performed"},
        "execution_observations": _call(original, "1" * 32, "old", "requirement_findings",
                                         "2026-09-20T00:00:01+00:00")}
    _write(original / "run_manifest.json", original_manifest)

    continuation = original / "continuations" / "cont-one"
    continuation.mkdir(parents=True)
    cause = {"reconstruction_origin": "offline_exact_input_replay", "correction_payload_prepared": True,
             "correction_model_request_sent": False,
             "correction_model_request_sent_basis": "offline_preparation_performs_no_model_call",
             "historical_correction_boundary": None,
             "first_rejection_reconstruction": {"attempt_index": 1, "status": "rejected",
                 "error_code": "REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID",
                 "diagnostic": {"relation_index": 1,
                                "violated_rules": ["nonempty_edit_targets_require_no_unresolved_gaps"]}}}
    continuation_manifest = {"run_id": RUN_ID, "status": "partial", "model_call_count": 3,
        "current_invocation_model_call_count": 1,
        "model_call_budget": {"maximum": 11, "consumed": 3, "remaining": 8,
            "by_stage": {"requirement_findings": {"maximum": 3, "consumed": 2, "remaining": 1}}},
        "initial_findings_cause_chain": cause,
        "execution_trace": {"trace_id": "2" * 32, "session_id": "session", "environment": "local",
                            "mode": "local_only", "cloud_readback": "not_performed"},
        "execution_observations": _call(continuation, "2" * 32, "new", "requirement_findings_correction",
                                         "2026-09-21T00:00:01+00:00", schema_failure=True)}
    _write(continuation / "run_manifest.json", continuation_manifest)
    _write(continuation / "run_result.json", {"run_id": RUN_ID, "status": "partial", "model_call_count": 3,
        "current_invocation_model_call_count": 1, "model_call_budget": continuation_manifest["model_call_budget"]})
    return allowed, original, continuation


def test_service_combines_calls_without_double_count_and_layers_diagnostics(tmp_path):
    allowed, original, continuation = run_records(tmp_path)
    result = TraceService(max_string_chars=262_144).inspect_product_run(
        allowed_root=allowed, run_root=original, run_id=RUN_ID,
        continuation_root=continuation, include_local_raw=True)
    assert result["call_accounting"]["original"] == {"maximum": 11, "consumed": 2, "remaining": 9}
    assert result["call_accounting"]["latest"] == {"maximum": 11, "consumed": 3, "remaining": 8}
    assert result["call_accounting"]["latest_requirement_findings"] == {"maximum": 3, "consumed": 2, "remaining": 1}
    assert len(result["calls"]) == 2
    assert all(call["request_span_id"] != call["generation_span_id"] for call in result["calls"])
    assert result["calls"][1]["raw"]["request"]["messages"][0]["content"] == "MODEL_MESSAGES"
    assert result["calls"][1]["raw"]["request"]["response_format"]["required"] == ["findings"]
    offline, prepared, current = result["diagnostic_timeline"]
    assert offline["origin"] == prepared["origin"] == "offline_exact_input_replay"
    assert offline["time"] is prepared["time"] is None
    assert prepared["status"] == "prepared_not_sent" and prepared["request_sent"] is False
    assert current["validation"]["schema"]["failure_category"] == "schema_required_property_missing"
    assert current["validation"]["schema"]["json_path"] == "$.findings[0].evidence_ids"
    assert current["validation"]["business"] == "not_reached_after_schema_failure"
    assert all(segment["trace"]["cloud_readback"] == "not_performed" for segment in result["segments"])
    layers = result["schema_failure_drilldown"]
    assert layers["layer_1_schema_builder"]["constraints"]["root_required"] == ["findings"]
    assert layers["layer_2_application_to_native_provider"]["actual_preservation_result"] == "unknown_not_captured"
    assert layers["layer_3_provider_runtime_support"]["original_run_recorded_ollama_version"] is None
    assert layers["layer_3_provider_runtime_support"]["llama_cpp_version_status"] == "unknown_not_recorded"
    assert layers["layer_3_provider_runtime_support"]["schema_to_grammar_result"] == "unknown_not_recorded"
    assert layers["layer_4_raw_response_against_recorded_schema"]["schema_violation"]["json_path"] == "$.findings[0].evidence_ids"
    assert layers["layer_5_local_validators"]["business_validator"] == "not_reached_after_schema_failure"
    assert layers["layer_5_local_validators"]["negative_training_status"] == "not_recorded_as_dpo_negative"


def test_accepted_findings_and_planning_precondition_are_distinct(tmp_path):
    allowed, original, continuation = run_records(tmp_path)
    manifest = json.loads((continuation / "run_manifest.json").read_text())
    coverage = manifest["execution_observations"]["coverage"]
    coverage["status"] = "completed"
    coverage["attributes"]["requirement_findings_attempt_audit"] = [
        {"attempt_index": 2, "status": "accepted", "error_code": None}]
    planning_ref = _write(continuation / "planning_model_selection.json", {
        "status": "blocked", "selection_mode": "model", "provider": "ollama_chat_local",
        "model": "model-1", "automatic_retry": False, "model_turns_attempted": 0,
        "model_responses_received": 0, "operator_target_ids_supplied": False,
        "evidence_payload_sha256": "d" * 64, "feature_payload_sha256": "e" * 64,
        "failure": {"code": "PLANNING_MODEL_EVIDENCE_INVALID",
                    "message": "Planning requires current sufficient formal coverage.",
                    "stage": "implementation_plan"}})
    manifest["execution_observations"]["planning"] = {
        "id": "planning", "parent_id": None, "trace_id": "2" * 32, "name": "planning.decision",
        "kind": "span", "status": "completed", "started_at": "2026-09-21T00:00:04+00:00",
        "finished_at": "2026-09-21T00:00:04+00:00", "elapsed_ms": 1,
        "attributes": {"decision_status": "blocked", "reason_status": "reason_unavailable",
                       "local_detail_refs": {"planning_receipt": planning_ref}}}
    (continuation / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result_record = json.loads((continuation / "run_result.json").read_text())
    result_record["status"] = "domain_blocked"
    result_record["blockers"] = [{"owner": "domain", "stage": "implementation_plan",
        "code": "PLANNING_MODEL_EVIDENCE_INVALID",
        "message": "Planning requires current sufficient formal coverage.", "source_node": "blocked"}]
    result_record["patch_execution_receipts"] = []
    (continuation / "run_result.json").write_text(json.dumps(result_record), encoding="utf-8")
    result = TraceService().inspect_product_run(allowed_root=allowed, run_root=original,
        run_id=RUN_ID, continuation_root=continuation)
    latest = result["segments"][-1]
    assert latest["post_findings_gate"]["findings_status"] == "accepted"
    selection = latest["post_findings_gate"]["planning_model_selection"]["selection"]
    assert selection["model_turns_attempted"] == selection["model_responses_received"] == 0
    assert selection["failure"]["code"] == "PLANNING_MODEL_EVIDENCE_INVALID"
    assert latest["post_findings_gate"]["supplemental_query_status"] == "not_observed_in_selected_continuation"
    assert latest["post_findings_gate"]["patch_execution_receipt_count"] == 0
    current = latest["diagnostics"][0]
    assert current["validation"] == {"parsing": "passed", "schema": {
        "status": "passed", "failure_category": None, "json_path": None,
        "schema_keyword": None, "allowed_boundary": None}, "business": "accepted"}


def test_reassessment_separates_source_queries_metadata_requests_and_findings_input(tmp_path):
    allowed, original, continuation = run_records(tmp_path)
    manifest = json.loads((continuation / "run_manifest.json").read_text())
    trace_id = manifest["execution_trace"]["trace_id"]
    prior_hash = "9" * 64
    prior_path = original / "a" / "evidence-pack.json"
    _write(prior_path, {"artifact_hash": prior_hash, "data": {"items": [
        {"evidence_id": "old-source", "source_type": "target_source"}]}})

    payload = {"source_observations": [
        {"evidence_id": "old-source", "source_type": "target_source",
         "source_path": "generated_mods/AccurateCrosshair/Old.cs", "symbol": "Old"},
        {"evidence_id": "new-source", "source_type": "target_source",
         "source_path": "generated_mods/AccurateCrosshair/New.cs", "symbol": "New",
         "span": {"start_line": 4, "end_line": 8}},
    ]}
    request_ref = _write(continuation / "model_trace_bodies" / "reassessment.request.json", {
        "messages": [{"role": "user", "content": json.dumps(payload)}]})
    response_ref = _write(continuation / "model_trace_bodies" / "reassessment.response.txt", {
        "findings": [{"relation_index": 1, "relationship": "missing",
                      "evidence_ids": ["old-source"], "edit_target_evidence_ids": [],
                      "unresolved_gaps": ["input API unknown"]}]})
    for observation_id in ("req-new", "gen-new"):
        attrs = manifest["execution_observations"][observation_id]["attributes"]
        attrs["model_role"] = "requirement_findings"
        attrs["local_detail_refs"] = {"request": request_ref, "response": response_ref}
    manifest["execution_observations"].update({
        "query-request": {"id": "query-request", "parent_id": None, "trace_id": trace_id,
            "name": "model.request", "kind": "span", "status": "completed",
            "started_at": "2026-09-21T00:00:00+00:00", "finished_at": "2026-09-21T00:00:01+00:00",
            "elapsed_ms": 1000, "attributes": {"model_role": "initial_findings_queries",
                "transport_started": True, "response_received": True, "response_complete": True,
                "http_status": 200, "response_origin": "live_provider_response"}},
        "query-generation": {"id": "query-generation", "parent_id": "query-request", "trace_id": trace_id,
            "name": "evidence.query", "kind": "generation", "status": "completed",
            "started_at": "2026-09-21T00:00:00+00:00", "finished_at": "2026-09-21T00:00:01+00:00",
            "elapsed_ms": 900, "attributes": {"model_role": "initial_findings_queries",
                "transport_started": True, "response_received": True, "response_complete": True,
                "http_status": 200, "response_origin": "live_provider_response"}},
        "source-query": {"id": "source-query", "parent_id": None, "trace_id": trace_id,
            "name": "evidence.source_query", "kind": "tool", "status": "completed",
            "started_at": "2026-09-21T00:00:01+00:00", "finished_at": "2026-09-21T00:00:01+00:00",
            "elapsed_ms": 1, "attributes": {"retrieval_status": "source_observations_returned"}},
    })
    (continuation / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result_record = json.loads((continuation / "run_result.json").read_text())
    result_record.update({"status": "domain_blocked", "blockers": [{
        "code": "REQUIREMENT_COVERAGE_INSUFFICIENT", "message": "required_requirement_unresolved:req-1",
        "source_node": "blocked"}], "initial_findings_reassessment_stop": {
            "code": "INITIAL_FINDINGS_NO_NEW_INFORMATION_STOP", "cycle": 1,
            "prior_item_count": 1, "new_item_count": 0, "new_evidence_ids": [],
            "sufficiency_status": "insufficient",
            "not_started": ["initial_findings_queries_cycle_2", "planning", "patch"],
            "fact_boundary": "deterministic_new_information_false",
        }})
    result_record["product_execution_result"] = {"validation_facts": {"details": [{"payload": [{
        "data": {"budget_summary": {
            "dependency_api_supplement": {"metadata_query_count": 0, "model_calls_performed": 0,
                "query_source": "metadata_queries", "reason": "DEPENDENCY_API_METADATA_QUERY_NOT_REQUESTED",
                "status": "not_requested", "tool_calls_completed": 0},
            "initial_findings_reassessment": {"prior_evidence_ref": {
                "artifact_hash": prior_hash, "path": str(prior_path)}},
            "reassessment": {"old_evidence_hash": prior_hash, "prior_item_count": 1,
                "new_item_count": 1, "queries": [{"query_id": "q1", "requirement_id": "req-1",
                    "query": "Find current input handling", "metadata_queries": []}],
                "per_query_execution": [{"query_id": "q1", "requirement_id": "req-1",
                    "retrieval_status": "source_observations_returned",
                    "evidence_ids": ["old-source", "new-source"]}]},
        }}}
    ]}]}}
    (continuation / "run_result.json").write_text(json.dumps(result_record), encoding="utf-8")

    projected = TraceService().inspect_product_run(
        allowed_root=allowed, run_root=original, run_id=RUN_ID, continuation_root=continuation)
    chain = projected["segments"][-1]["initial_findings_reassessment"]
    assert chain["stop"] == result_record["initial_findings_reassessment_stop"]
    assert chain["query_groups"][0]["metadata_queries"] == []
    assert chain["metadata_supplement"] == {
        "query_source": "metadata_queries", "status": "not_requested",
        "reason": "DEPENDENCY_API_METADATA_QUERY_NOT_REQUESTED", "metadata_query_count": 0,
        "tool_calls_completed": 0, "model_calls_performed": 0,
        "visible_metadata": None,
        "recorded_metadata_observation_count": 0, "recorded_metadata_observations": [],
        "observation_count_basis": "tool_or_retrieval_method_equals_search_dotnet_metadata"}
    assert chain["transport_boundaries"]["initial_findings_queries"]["http_status"] == 200
    assert chain["transport_boundaries"]["metadata_supplement"] == "not_requested"
    assert chain["evidence_revision"]["new_inputs"] == [{
        "evidence_id": "new-source", "source_type": "target_source",
        "source_path": "generated_mods/AccurateCrosshair/New.cs",
        "symbol": "New", "span": {"start_line": 4, "end_line": 8},
        "entered_findings_input": True, "cited_by_findings_output": False}]
    assert chain["findings_outcomes"] == [{
        "relation_index": 1, "relationship": "missing", "unresolved_gap_count": 1}]
    assert chain["terminal"]["status"] == "domain_blocked"


@pytest.mark.parametrize("damage", ["outside", "hash", "wrong_id"])
def test_service_rejects_unselected_or_unbound_local_records(tmp_path, damage):
    allowed, original, continuation = run_records(tmp_path)
    run_id = RUN_ID
    if damage == "outside":
        allowed = tmp_path / "different"
        allowed.mkdir()
    elif damage == "hash":
        result = json.loads((original / "run_result.json").read_text())
        result["changed"] = True
        (original / "run_result.json").write_text(json.dumps(result), encoding="utf-8")
    else:
        run_id = "different-id"
    with pytest.raises(ValueError):
        TraceService().inspect_product_run(allowed_root=allowed, run_root=original,
                                           run_id=run_id, continuation_root=continuation)


def render_page():
    from src.observability.dashboard.pages.mod_agent_dashboard import render
    render()


def test_controlled_agent_page_opens_hash_verified_raw_on_demand(tmp_path, monkeypatch):
    from src.observability.dashboard.pages import mod_agent_dashboard as page
    allowed, original, continuation = run_records(tmp_path)
    monkeypatch.setattr(page, "DEFAULT_PRODUCT_RUNS_ROOT", allowed)
    app = AppTest.from_function(render_page).run()
    app.text_input(key="product_trace_run_root").set_value(str(original))
    app.text_input(key="product_trace_run_id").set_value(RUN_ID)
    app.text_input(key="product_trace_continuation_root").set_value(str(continuation))
    app.checkbox(key="product_trace_show_raw").set_value(True)
    app.run()
    app.button(key="product_trace_inspect").click().run()
    assert not app.exception
    assert any(metric.label == "Actual calls" and metric.value == "2" for metric in app.metric)
    rendered = "\n".join(item.value for item in app.json)
    assert "schema_required_property_missing" in rendered
    assert "$.findings[0].evidence_ids" in rendered
    assert any("service_output_constraint_not_proof_full_schema_was_model_visible" in item.value
               for item in app.caption)
    assert "unknown_not_captured" in rendered
    assert "unknown_not_recorded" in rendered
    assert "not_recorded_as_dpo_negative" in rendered
    assert any("Recorded application response" in item.value for item in app.markdown)
    assert any("Local-only trace" in item.value for item in app.info)


def test_cli_reads_same_projection_without_starting_work(tmp_path, capsys):
    from scripts.product_trace import main

    allowed, original, continuation = run_records(tmp_path)
    assert main(["--allowed-root", str(allowed), "--run-root", str(original), "--run-id", RUN_ID,
                 "--continuation-root", str(continuation), "--include-local-raw"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["read_only"] is True
    assert result["query_execution"] == {"model_calls_performed": 0, "writes_performed": False}
    assert result["call_accounting"]["actual_generation_records"] == 2
    assert result["schema_failure_drilldown"]["layer_2_application_to_native_provider"][
        "actual_preservation_result"] == "unknown_not_captured"


def test_native_provider_request_exposes_format_without_messages_or_raw_body(tmp_path):
    allowed, original, continuation = run_records(tmp_path)
    manifest = json.loads((continuation / "run_manifest.json").read_text())
    manifest["execution_observations"] = _call(
        continuation, "2" * 32, "new-native", "requirement_findings_correction",
        "2026-09-21T00:00:01+00:00", schema_failure=True, native_provider=True)
    (continuation / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = TraceService(max_string_chars=262_144).inspect_product_run(
        allowed_root=allowed, run_root=original, run_id=RUN_ID,
        continuation_root=continuation, include_local_raw=True)
    provider = result["calls"][-1]["raw"]["provider_request"]
    assert provider["messages"] == provider["raw_body"] == "not_displayed_by_trace_drilldown"
    assert "PRIVATE_PROVIDER_MESSAGE" not in json.dumps(result)
    layer = result["schema_failure_drilldown"]["layer_2_application_to_native_provider"]
    assert layer["actual_preservation_result"] == "verified_equal_application_schema"
    assert layer["native_messages_display"] == "not_displayed"
