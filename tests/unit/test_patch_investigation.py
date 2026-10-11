"""Investigation preserves gaps between retained material, delivery and understanding."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.fresh_planning_continuation import _canonical_sha256
from src.mod_agent.local_entry import _compact_patch_agent_context
from src.observability.patch_execution_index import _attempt, _References
from src.observability.patch_investigation import build_investigation_chain


def _retain(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


class _Reader(_References):
    """Small Artifact fixture; real byte reads and request checks retain their owner."""

    def __init__(self, root):
        super().__init__(root)
        self.artifacts = {}
        self.reads = []

    def add_artifact(self, name, data):
        reference = {"path": str(self.root / name), "artifact_hash": _canonical_sha256(data),
                     "artifact_type": name, "feature_id": "feature_fixture"}
        self.artifacts[reference["path"]] = (reference, {"data": data})
        return reference

    def check(self, value):
        self.reads.append(value)
        if isinstance(value, dict) and value.get("path") in self.artifacts:
            expected, document = self.artifacts[value["path"]]
            if value.get("artifact_hash") == expected["artifact_hash"]:
                return {**value, "integrity": "verified_artifact"}, document
            return {**value, "integrity": "hash_mismatch"}, {}
        return super().check(value)


def _fixture(tmp_path):
    reader = _Reader(tmp_path / "store")
    source = tmp_path / "Bound.cs"
    source.write_text("private void Refresh() {}\n", encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    item = {"evidence_id": "fact-refresh", "source_type": "target_source", "source_path": "Bound.cs",
            "source_ref": str(source), "source_hash": source_hash,
            "symbol": "Refresh", "span": {"start_line": 1, "end_line": 1},
            "excerpt": "SECRET_SOURCE_BODY"}
    binding = {"binding_id": "edit_refresh", "evidence_id": item["evidence_id"],
               "source_type": item["source_type"], "canonical_target_path": item["source_path"],
               "source_hash": source_hash, "target_symbol": item["symbol"], "target_span": item["span"]}
    supporting = {"binding_id": "support_refresh", "evidence_id": item["evidence_id"],
                  "source_type": item["source_type"], "source_path": item["source_path"],
                  "target_symbol": item["symbol"], "target_span": item["span"]}
    journal = {"feature_id": "feature_fixture", "run_id": "run_fixture", "status": "continuation_failed",
        "continuation_selection": "explicit_exact_implementation_plan_ref",
        "latest_observations": {"implementation_plan": {"selected_is_latest": False}},
        "selected_artifacts": {
            "evidence_pack": reader.add_artifact("evidence_pack", {"items": [item]}),
            "implementation_plan": reader.add_artifact("implementation_plan", {
                "binding_registry": {"edit_bindings": [binding], "supporting_bindings": [supporting]}}),
            "feature_spec": reader.add_artifact("feature_spec", {"acceptance_criteria": ["SECRET_REQUIREMENT"]})},
        "factory_receipt": {"worker_turns": [], "patch_agent_loop": {"tool_call_trace": [], "observation_trace": []}},
        "terminal_result": {"terminal_stage": "generate_patch_proposal", "execution_counts": {"apply": 0, "build": 0, "runtime": 0}}}
    context = {"edit_binding_contexts": {"edit_refresh": binding}, "supporting_evidence": [supporting],
        "allowed_edit_binding_ids": ["edit_refresh"],
        "required_change_units": [{"change_id": "change_refresh", "edit_binding_id": "edit_refresh",
                                   "operation": "minimal_evidence_bound_change", "supporting_binding_ids": ["support_refresh"]}],
        "required_output_schema": {"type": "object", "properties": {"changes": {
            "type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "object",
            "required": ["edit_binding_id", "after_text"], "properties": {
                "edit_binding_id": {"type": "string", "enum": ["edit_refresh"]}}}}}}}
    return journal, reader, source, context


def _request(journal, reader, context, *, tool_results=None, response=True):
    index = len(journal["factory_receipt"]["worker_turns"]) + 1
    request = {"messages": [{"role": "user", "content": json.dumps(context)}],
        "tools": [{"name": "inspect_plan_binding_source", "parameters": {"properties": {
            "binding_id": {"enum": ["edit_refresh", "support_refresh"]}}}}],
        "tool_results": tool_results or [], "historical_tool_exchanges": []}
    reference = _retain(reader.root / "cr" / f"request-{index}.json", request)
    turn = {"turn_index": index, "request_ref": reference, "request_sha256": _canonical_sha256(request),
            "status": "responded" if response else "failed"}
    if response:
        turn.update(response_origin="live_provider_response", response_ref=_retain(
            reader.root / "cr" / f"response-{index}.json", {"content": "SECRET_MODEL_CONTENT"}))
    journal["factory_receipt"]["worker_turns"].append(turn)
    return turn


def _observation(journal, source):
    payload = {"observation_id": "observed-refresh", "binding_id": "edit_refresh",
        "source_ref": "binding://edit_refresh", "source_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_snapshot_sha256": "a" * 64, "target_span": {"start_line": 1, "end_line": 1},
        "excerpt_span": {"start_line": 1, "end_line": 1}, "excerpt": source.read_text(encoding="utf-8"),
        "truncated": False}
    payload["observation_sha256"] = _canonical_sha256(payload)
    journal["factory_receipt"]["patch_agent_loop"].update(
        tool_call_trace=[{"turn_index": 1, "tool_call_id": "read-refresh", "tool": "inspect_plan_binding_source",
                          "binding_id": "edit_refresh", "dispatch_started": True, "status": "accepted"}],
        observation_trace=[{**{key: value for key, value in payload.items() if key != "excerpt"},
                            "turn_index": 1, "encoded_payload_sha256": _canonical_sha256(payload),
                            "admitted_to_model": True, "consumed_in_model_turn": 2}])
    return {"call_id": "read-refresh", "name": "inspect_plan_binding_source", "output": payload}


def _project(journal, reader):
    path = reader.root / "cr" / "attempt.json"
    raw = json.dumps(journal).encode()
    attempt = _attempt(path, raw, journal, reader)
    result = build_investigation_chain(journal, attempt, reader.check)
    return {row["stage_id"]: row for row in result["stages"]}, result


def test_material_can_exist_without_a_request_or_proven_understanding(tmp_path):
    journal, reader, _, _ = _fixture(tmp_path)
    stages, result = _project(journal, reader)
    assert len(stages) == 6
    assert stages["material_availability"]["observations"]["current_source_integrity_counts"] == {"verified_bytes": 1}
    assert stages["request_delivery"]["observations"]["verified_request_count"] == 0
    assert stages["judgment_alignment"]["status"] == "unknown_semantic_alignment"
    assert stages["necessary_fact_recall"]["observations"]["necessary_fact_denominator"] is None
    assert "SECRET_" not in json.dumps(result)
    assert all(row["method"] and row["next_verification"] and row["unknowns"] for row in stages.values())


def test_returned_source_not_in_request_is_distinct_from_admission_claim(tmp_path):
    journal, reader, source, context = _fixture(tmp_path)
    _observation(journal, source)
    _request(journal, reader, context)
    stages, _ = _project(journal, reader)
    row = stages["request_delivery"]["observations"]["source_observations"][0]
    assert row["admitted_to_model"] is True
    assert row["request_binding"] == "not_found_in_verified_retained_requests"


def test_request_without_source_observations_does_not_claim_verified_tool_delivery(tmp_path):
    journal, reader, _, context = _fixture(tmp_path)
    _request(journal, reader, context)
    stages, _ = _project(journal, reader)
    assert stages["request_delivery"]["status"] == "no_source_observation_record"


def test_verified_delivery_still_does_not_assert_evidence_sufficiency(tmp_path):
    journal, reader, source, context = _fixture(tmp_path)
    tool = _observation(journal, source)
    _request(journal, reader, context)
    _request(journal, reader, context, tool_results=[tool])
    stages, _ = _project(journal, reader)
    assert stages["request_delivery"]["status"] == "retained_request_links_verified"
    assert stages["request_delivery"]["observations"]["source_observations"][0]["request_binding"] == "matched_retained_request"
    assert stages["judgment_alignment"]["observations"]["model_understanding"] == "not_established"
    assert stages["necessary_fact_recall"]["status"] == "unknown_necessary_fact_coverage"


def test_payload_mismatch_cannot_become_delivery_by_observation_id(tmp_path):
    journal, reader, source, context = _fixture(tmp_path)
    tool = _observation(journal, source)
    tool["output"]["excerpt"] = "different bytes"
    _request(journal, reader, context, tool_results=[tool])
    stages, _ = _project(journal, reader)
    assert stages["request_delivery"]["status"] == "partial_or_unknown_delivery"
    assert stages["request_delivery"]["observations"]["observations_without_matched_request_count"] == 1


def test_timeout_with_transport_marker_keeps_sent_request_and_no_response_separate(tmp_path):
    journal, reader, source, context = _fixture(tmp_path)
    tool = _observation(journal, source)
    turn = _request(journal, reader, context, tool_results=[tool], response=False)
    turn.update(error="Local Agent request timed out after 600 seconds.",
                error_type="AgentTurnProviderError", model_request_observation_id="native-request")
    journal["execution_observations"] = {"native-request": {"id": "native-request", "name": "model.request",
        "status": "failed", "elapsed_ms": 600123, "attributes": {"request_sha256": turn["request_sha256"],
        "transport_started": True, "response_received": False}}}
    stages, _ = _project(journal, reader)
    reliability = stages["execution_reliability"]["observations"]["turns"][0]
    assert reliability["boundary"] == "timeout_after_transport_started"
    assert reliability["transport_started"] is True
    assert reliability["response_after_request_observed"] is False
    assert stages["request_delivery"]["status"] == "retained_request_links_verified"
    assert stages["code_verification"]["status"] == "no_current_verification_record"


@pytest.mark.parametrize("damage, expected", [("remove", "missing"), ("change", "hash_mismatch")])
def test_bound_reference_loss_and_source_drift_are_visible(tmp_path, damage, expected):
    journal, reader, source, context = _fixture(tmp_path)
    turn = _request(journal, reader, context)
    request_path = Path(turn["request_ref"]["path"])
    if damage == "remove":
        source.unlink()
        request_path.unlink()
    else:
        source.write_text("changed", encoding="utf-8")
        request_path.write_text("{}", encoding="utf-8")
    stages, _ = _project(journal, reader)
    assert stages["material_availability"]["observations"]["current_source_integrity_counts"] == {expected: 1}
    assert stages["request_delivery"]["observations"]["verified_request_count"] == 0
    assert stages["material_availability"]["status"] == "references_need_attention"


def test_fixed_selection_records_required_item_count_and_original_input_tables(tmp_path):
    journal, reader, _, context = _fixture(tmp_path)
    _request(journal, reader, _compact_patch_agent_context(context))
    stages, _ = _project(journal, reader)
    facts = stages["necessary_fact_recall"]["observations"]
    assert facts["continuation_selection"] == "explicit_exact_implementation_plan_ref"
    assert facts["selected_is_latest"] is False
    assert facts["edit_binding_count"] == 1
    assert facts["supporting_binding_count"] == 1
    assert facts["bindings"][1]["source_hash_binding"] == "missing_in_plan_resolved_from_evidence"
    assert facts["request_scopes"][0]["tool_readable_binding_count"] == 2
    assert facts["request_scopes"][0]["required_change_unit_count"] == 1
    assert facts["request_scopes"][0]["output_changes_constraint"]["minItems"] == 1
    assert facts["request_scopes"][0]["output_changes_constraint"]["maxItems"] == 1
    assert facts["necessary_fact_recall"] is None


@pytest.mark.parametrize("origin, verdict", [("executed", "executed_bound_report"),
                                             ("reused", "reused_bound_report"),
                                             ("unknown", "unknown_execution_or_report_binding")])
def test_verification_failure_reuse_and_unknown_execution_are_distinct(tmp_path, origin, verdict):
    journal, reader, _, _ = _fixture(tmp_path)
    report = _retain(reader.root / "report.json", {"status": "behavior_failed", "generated_changes_sha256": "b" * 64})
    journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"] = [{
        "evaluation_index": 1, "status": "behavior_failed", "execution_origin": origin,
        "generated_changes_sha256": "b" * 64, "report_ref": report,
        "verification_summary": {"checks": 3, "failed_checks": 1}}]
    stages, _ = _project(journal, reader)
    observed = stages["code_verification"]["observations"]["current_evaluations"][0]
    assert observed["result_binding"] == verdict
    assert observed["status"] == "behavior_failed"
    assert observed["verification_summary"]["failed_checks"] == 1


def test_prior_failed_report_without_current_code_is_not_current_verification(tmp_path):
    journal, reader, _, _ = _fixture(tmp_path)
    journal["repair_context"] = {"failure_report_ref": _retain(reader.root / "prior.json", {"status": "behavior_failed"})}
    stages, _ = _project(journal, reader)
    stage = stages["code_verification"]
    assert stage["status"] == "no_current_verification_record"
    assert stage["observations"]["prior_failure_report_ref"]["integrity"] == "verified_bytes"
    assert stage["observations"]["current_evaluation_count"] == 0


def test_evidence_id_alone_does_not_resolve_a_different_source_identity(tmp_path):
    journal, reader, _, _ = _fixture(tmp_path)
    plan = reader.artifacts[journal["selected_artifacts"]["implementation_plan"]["path"]][1]["data"]
    plan["binding_registry"]["supporting_bindings"][0]["source_path"] = "Different.cs"
    stages, _ = _project(journal, reader)
    binding = stages["necessary_fact_recall"]["observations"]["bindings"][1]
    assert binding["evidence_match"] == "identity_fields_mismatch"
    assert binding["source_hash_binding"] == "unverified_evidence_identity"


def test_repeated_observation_hash_does_not_borrow_delivery_from_another_segment(tmp_path):
    journal, reader, source, context = _fixture(tmp_path)
    tool = _observation(journal, source)
    _request(journal, reader, context)
    initial = deepcopy(journal["factory_receipt"])
    following_turn = _request(journal, reader, context, tool_results=[tool])
    following = {"worker_turns": [following_turn], "patch_agent_loop": deepcopy(initial["patch_agent_loop"])}
    journal["patch_execution_segments"] = [
        {"segment_index": 0, "factory_receipt": initial, "selected_artifacts": journal["selected_artifacts"]},
        {"segment_index": 1, "factory_receipt": following, "selected_artifacts": journal["selected_artifacts"]}]
    stages, _ = _project(journal, reader)
    observations = stages["request_delivery"]["observations"]["source_observations"]
    assert observations[0]["segment_index"] == 0
    assert observations[0]["request_binding"] == "not_found_in_verified_retained_requests"
    assert observations[1]["segment_index"] == 1
    assert observations[1]["request_binding"] == "matched_retained_request"


def test_query_uses_only_bound_refs_and_never_writes(tmp_path, monkeypatch):
    journal, reader, source, context = _fixture(tmp_path)
    turn = _request(journal, reader, context)
    def forbidden(*args, **kwargs):
        pytest.fail("query attempted a filesystem write")
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    _project(journal, reader)
    allowed = {str(source), *(ref["path"] for ref in journal["selected_artifacts"].values()),
               turn["request_ref"]["path"], turn["response_ref"]["path"]}
    assert all(value.get("path") in allowed for value in reader.reads if isinstance(value, dict) and "path" in value)
