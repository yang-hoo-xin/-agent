"""Offline real-Graph acceptance for one explicitly requested semantic return."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.libs.llm.agent_turn import AgentToolCall, AgentTurnResponse, AgentUsage
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.evidence import RgLiveEvidenceProvider
from src.mod_agent.evidence.reassessment import RequirementCoverageReassessmentFactory
from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationError,
    _bind_patch_attempt_recorder,
    _patch_continuation_state,
    preflight_patch_continuation,
    run_fresh_patch_continuation,
)
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_UPSTREAM_REQUEST_TOOL_NAME,
    PatchAgentLoopPolicy,
)
from src.mod_agent.repair.upstream import (
    prepare_replanned_patch_input,
    run_patch_upstream_replanning,
)
from src.mod_agent.workflow import build_graph
from tests.unit.test_fresh_planning_continuation import _source_hashes
from tests.unit.test_model_planning_selection import _Client, _selector
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle
from tests.unit.test_patch_repair_continuation import _file_ref, _repair_case


def _selection(owner="planning"):
    return {"origin": "human", "required_owner": owner,
        "reason": "The executed preservation check requires reassessing the shared state owner.",
        "source_refs": ["binding://edit_binding_001"], "source_attempt_ref": None}


def _artifact(inputs, state, kind):
    return inputs.store.semantic_read_immutable(ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
        path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind]))


def test_human_finding_runs_repair_then_model_planning_in_the_existing_graph(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    before = _source_hashes(inputs.workspace)
    client = _Client()
    state = run_patch_upstream_replanning(request=request, selection=_selection(),
        planning_target_selection_factory=_selector(inputs, client))
    assert not state["blockers"] and state["current_stage"] == "implementation_plan"
    assert len(client.calls) == 1
    assert state["artifact_hashes"]["implementation_plan"] != request.implementation_plan_ref.artifact_hash
    repair = _artifact(inputs, state, "repair_plan")["data"]
    assert repair["semantic_decision"]["required_next_owner"] == "planning"
    assert repair["repair_context"]["failure_report"]["failure_owner"] == "patch_implementation"
    assert repair["scope_expansion_allowed"] is False and repair["minimal_changes"] == []
    assert _source_hashes(inputs.workspace) == before and state["approvals"] == {}
    started = [item["node_name"] for item in state["trace_events"] if item["event_type"] == "node_started"]
    assert started == ["create_repair_plan", "create_implementation_plan"]
    assert _selection()["reason"] in client.calls[0].messages[1].content["semantic_feedback"]
    ready = prepare_replanned_patch_input(prior_request=request, state=state, attempt_id="next-replanned-patch")
    assert ready.implementation_plan_ref.artifact_hash == state["artifact_hashes"]["implementation_plan"]
    assert ready.repair_parent_proposal_ref is None


@pytest.mark.parametrize("run_id", ["a4-planning-001-preview", "a4-planning-001-actual"])
def test_upstream_invocation_identity_is_separate_from_logical_request(tmp_path, run_id):
    inputs, request, _ = _repair_case(tmp_path)
    state = run_patch_upstream_replanning(request=request, selection=_selection(),
        planning_target_selection_factory=_selector(inputs, _Client()), run_id=run_id)
    assert not state["blockers"]
    assert state["run_id"] == run_id
    assert state["request_id"].startswith("patch_upstream_")
    assert state["request_id"] != state["run_id"]


class _Findings:
    def __init__(self, findings):
        self.value = findings
        self.calls = []

    def findings(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.value)


def _evidence_factory(inputs, findings):
    return RequirementCoverageReassessmentFactory(artifact_store=inputs.store, workspace_root=inputs.workspace,
        search_root="generated_mods/SyntheticMod", source_provider=RgLiveEvidenceProvider(inputs.workspace),
        semantic_provider=findings, query_selector=lambda feature, projection, old, feedback: [{
            "query": "ChangeMarker", "requirement_id": projection["requirements"][0]["requirement_id"]}])


def test_evidence_return_recomputes_complete_coverage_before_model_planning(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    old = preflight_patch_continuation(request).evidence_pack
    normalized = old["requirement_coverage"]["findings"]
    findings = _Findings({"findings": [{"relation_index": i, **{key: row[key] for key in (
        "relationship", "evidence_ids", "edit_target_evidence_ids", "unresolved_gaps")}}
        for i, row in enumerate(normalized, 1)]})
    client = _Client()
    state = run_patch_upstream_replanning(request=request, selection=_selection("evidence"),
        evidence_pack_factory=_evidence_factory(inputs, findings), planning_target_selection_factory=_selector(inputs, client))
    assert not state["blockers"]
    assert len(findings.calls) == len(client.calls) == 1
    received_ids = {item.evidence_id for item in findings.calls[0]["retrieved_pack"].items}
    assert {item["evidence_id"] for item in old["items"]} <= received_ids
    assert findings.calls[0]["semantic_feedback"]["observed_failure"]
    new = _artifact(inputs, state, "evidence_pack")["data"]
    assert new["requirement_coverage"]["projection_identity"] == old["requirement_coverage"]["projection_identity"]
    assert "fresh_coverage_model_execution" not in new["budget_summary"]
    assert new["budget_summary"]["reassessment"]["fresh_execution"] is False
    started = [item["node_name"] for item in state["trace_events"] if item["event_type"] == "node_started"]
    assert started == ["create_repair_plan", "retrieve_evidence", "create_implementation_plan"]


@pytest.mark.parametrize("change", ["unknown_ref", "owner", "source", "model_without_receipt"])
def test_invalid_upstream_selection_stops_before_any_model(tmp_path, change):
    inputs, request, _ = _repair_case(tmp_path)
    selection = _selection()
    if change == "unknown_ref":
        selection["source_refs"] = ["binding://not_registered"]
    elif change == "owner":
        selection["required_owner"] = "patch_implementation"
    elif change == "source":
        inputs.behavior.write_text(inputs.behavior.read_text() + "\n// drift", encoding="utf-8")
    else:
        selection["origin"] = "model"
    client = _Client()
    with pytest.raises((PatchContinuationError, ValueError, TypeError)):
        run_patch_upstream_replanning(request=request, selection=selection,
            planning_target_selection_factory=_selector(inputs, client))
    assert not client.calls


class _RequestUpstream:
    provider = "local_offline_test"
    model = "test-patch-model"

    def __init__(self, owner="planning"):
        self.owner = owner

    def complete_turn(self, request):
        selected = _selection(self.owner)
        return AgentTurnResponse(provider=self.provider, model=self.model, content=None,
            tool_calls=(AgentToolCall(call_id="semantic-return", name=PATCH_UPSTREAM_REQUEST_TOOL_NAME,
                arguments={key: selected[key] for key in ("required_owner", "reason", "source_refs")}),),
            usage=AgentUsage(input_tokens=100, output_tokens=20))


def test_model_upstream_request_is_bound_to_raw_response_then_executes_planning(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    adapter = _adapter(inputs, _RequestUpstream(), _BehaviorOracle(tmp_path / "unused-verifier"))
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(require_source_inspection=False,
        allow_upstream_request=True, enable_supporting_reads=True, finalize_after_first_observation=False)
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    journal = json.loads(Path(result.attempt_receipt["path"]).read_text())
    assert journal["factory_receipt"]["upstream_decision"]["code"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    selection = {**_selection(), "origin": "model", "source_attempt_ref": _file_ref(Path(result.attempt_receipt["path"]))}
    client = _Client()
    state = run_patch_upstream_replanning(request=request, selection=selection,
        planning_target_selection_factory=_selector(inputs, client))
    assert not state["blockers"] and len(client.calls) == 1
    assert _artifact(inputs, state, "repair_plan")["data"]["semantic_decision"]["origin"] == "model"


@pytest.mark.parametrize("decision", ["needs_evidence", "invalid_target"])
def test_planning_does_not_fall_back_to_operator_targets(tmp_path, decision):
    inputs, request, _ = _repair_case(tmp_path)
    client = _Client(override=lambda payload: {**payload, **(
        {"decision": "needs_evidence", "selected_evidence_ids": [], "missing_evidence": ["Shared state owner is not evidenced."]}
        if decision == "needs_evidence" else {"selected_evidence_ids": ["unknown_evidence"]})})
    state = run_patch_upstream_replanning(request=request, selection=_selection(),
        planning_target_selection_factory=_selector(inputs, client))
    assert state["blockers"] and len(client.calls) == 1
    with pytest.raises(ValueError):
        prepare_replanned_patch_input(prior_request=request, state=state)


def test_missing_recomputed_coverage_blocks_before_planning_model(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    findings = _Findings({"findings": []})
    client = _Client()
    state = run_patch_upstream_replanning(request=request, selection=_selection("evidence"),
        evidence_pack_factory=_evidence_factory(inputs, findings), planning_target_selection_factory=_selector(inputs, client))
    assert state["blockers"] and not client.calls
    assert len(findings.calls) == 1


@pytest.mark.parametrize("owner,configured", [("planning", True), ("evidence", True), ("evidence", False)])
def test_worker_return_is_consumed_automatically_without_copying_selection(tmp_path, owner, configured):
    inputs, request, _ = _repair_case(tmp_path)
    adapter = _adapter(inputs, _RequestUpstream(owner), _BehaviorOracle(tmp_path / "unused-verifier"))
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(require_source_inspection=False,
        allow_upstream_request=True, enable_supporting_reads=True, finalize_after_first_observation=False)
    planning_client = _Client()
    events = []
    _bind_patch_attempt_recorder(adapter, events.append)
    admitted = preflight_patch_continuation(request)
    evidence_factory = None
    if owner == "evidence" and configured:
        normalized = admitted.evidence_pack["requirement_coverage"]["findings"]
        findings = _Findings({"findings": [{"relation_index": i, **{key: row[key] for key in (
            "relationship", "evidence_ids", "edit_target_evidence_ids", "unresolved_gaps")}}
            for i, row in enumerate(normalized, 1)]})
        evidence_factory = _evidence_factory(inputs, findings)
    state = _patch_continuation_state(run_id="auto-upstream", request_id="auto-upstream", request=request, admitted=admitted)
    graph = build_graph(inputs.store, use_default_proposal_git_binding=False, patch_continuation_mode=request,
        enable_patch_upstream_replanning=True, patch_change_factory=adapter,
        evidence_pack_factory=evidence_factory,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), patch_continuation_max_model_calls=5,
        patch_continuation_attempt_recorder=events.append, planning_target_selection_factory=_selector(inputs, planning_client))
    result = graph.invoke(state)
    if not configured:
        assert result["blockers"][0]["code"] == "PATCH_UPSTREAM_EVIDENCE_PROVIDER_REQUIRED"
        assert not planning_client.calls
        return
    assert not result["blockers"] and result["current_stage"] == "implementation_plan"
    assert len(planning_client.calls) == 1
    assert any(event.get("phase") == "patch_upstream_assessment_admitted" for event in events)
    started = [item["node_name"] for item in result["trace_events"] if item["event_type"] == "node_started"]
    assert started == ["create_repair_plan", "generate_patch_proposal", "create_repair_plan",
        *(["retrieve_evidence"] if owner == "evidence" else []), "create_implementation_plan"]
    generation = next(item for item in result["trace_events"]
        if item["node_name"] == "generate_patch_proposal" and item["event_type"] == "node_finished")
    assert generation["status"] == "partial" and generation["artifact_refs"] == []
    assert _artifact(inputs, result, "repair_plan")["data"]["retry_count"] == 1
    assert _artifact(inputs, result, "repair_plan")["data"]["repair_context"]["upstream_request"]["source_worker_response_ref"]


def test_preflight_failure_does_not_pollute_unused_selector_feedback(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    selector = _selector(inputs, _Client(), feedback=("Existing feedback",))
    with pytest.raises(ValueError):
        run_patch_upstream_replanning(request=request, selection=_selection("evidence"),
            planning_target_selection_factory=selector)
    assert selector.semantic_feedback == ("Existing feedback",) and selector._used is False


def test_different_failure_in_same_plan_cannot_borrow_model_upstream_request(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    adapter = _adapter(inputs, _RequestUpstream(), _BehaviorOracle(tmp_path / "unused-verifier"))
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(require_source_inspection=False,
        allow_upstream_request=True, enable_supporting_reads=True, finalize_after_first_observation=False)
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    report = json.loads(Path(request.repair_failure_report_ref["path"]).read_text())
    report["observations"][0]["input"] = {"enabled": False}
    other = tmp_path / "sibling-failure.json"
    other.write_text(json.dumps(report), encoding="utf-8")
    changed = replace(request, repair_failure_report_ref=_file_ref(other))
    selection = {**_selection(), "origin": "model", "source_attempt_ref": _file_ref(Path(result.attempt_receipt["path"]))}
    client = _Client()
    with pytest.raises(PatchContinuationError, match="PATCH_UPSTREAM_FAILURE_BINDING_REQUIRED"):
        run_patch_upstream_replanning(request=changed, selection=selection,
            planning_target_selection_factory=_selector(inputs, client))
    assert not client.calls


def test_original_plan_semantic_clarification_survives_without_operator_feedback(tmp_path, monkeypatch):
    from src.mod_agent.planning import ImplementationPlanner
    original = ImplementationPlanner.build
    calls = []
    clarification = "Preserve the existing absolute sizing semantics when the independent switch is disabled."
    def initial_clarification(self, **kwargs):
        result = original(self, **kwargs)
        calls.append(True)
        return replace(result, side_effect_boundaries=(*result.side_effect_boundaries, clarification)) if len(calls) == 1 else result
    monkeypatch.setattr(ImplementationPlanner, "build", initial_clarification)
    inputs, request, _ = _repair_case(tmp_path)
    client = _Client()
    selector = _selector(inputs, client)
    state = run_patch_upstream_replanning(request=request, selection=_selection(), planning_target_selection_factory=selector)
    assert len(calls) == 2
    assert clarification in client.calls[0].messages[1].content["semantic_feedback"]
    assert clarification in _artifact(inputs, state, "implementation_plan")["data"]["side_effect_boundaries"]
    assert selector.semantic_feedback == ()


def test_new_source_and_old_full_evidence_jointly_determine_new_binding_revision(tmp_path, monkeypatch):
    from tests.unit import test_fresh_planning_continuation as fixtures
    original = fixtures._write_sources
    def with_existing_unretrieved_source(workspace):
        path = original(workspace)
        (path.parent / "SharedState.cs").write_text(
            "public class SharedState\n{\n    public void RefreshSharedState()\n    {\n        int value = 1;\n    }\n}\n", encoding="utf-8")
        return path
    monkeypatch.setattr(fixtures, "_write_sources", with_existing_unretrieved_source)
    inputs, request, _ = _repair_case(tmp_path)
    old = preflight_patch_continuation(request).evidence_pack
    old_ids = {row["evidence_id"] for row in old["items"]}
    rows = [{"relation_index": i, **{key: row[key] for key in (
        "relationship", "evidence_ids", "edit_target_evidence_ids", "unresolved_gaps")}}
        for i, row in enumerate(old["requirement_coverage"]["findings"], 1)]
    class NewFindings(_Findings):
        def findings(self, **kwargs):
            result = super().findings(**kwargs)
            new_ids = {item.evidence_id for item in kwargs["retrieved_pack"].items} - old_ids
            assert len(new_ids) == 1
            result["findings"][0]["evidence_ids"].extend(sorted(new_ids))
            result["findings"][0]["edit_target_evidence_ids"].extend(sorted(new_ids))
            return result
    findings = NewFindings({"findings": rows})
    factory = _evidence_factory(inputs, findings)
    factory.query_selector = lambda feature, projection, old, feedback: [{
        "query": "RefreshSharedState", "requirement_id": projection["requirements"][0]["requirement_id"]}]
    state = run_patch_upstream_replanning(request=request, selection=_selection("evidence"),
        evidence_pack_factory=factory, planning_target_selection_factory=_selector(inputs, _Client()))
    assert not state["blockers"]
    evidence = _artifact(inputs, state, "evidence_pack")["data"]
    assert evidence["budget_summary"]["reassessment"]["new_item_count"] == 1
    assert {row["evidence_id"] for row in evidence["items"]} > old_ids
    plan = _artifact(inputs, state, "implementation_plan")["data"]
    assert len(plan["binding_registry"]["edit_bindings"]) == 2
    prepared = prepare_replanned_patch_input(prior_request=request, state=state)
    assert preflight_patch_continuation(prepared).implementation_plan == plan
