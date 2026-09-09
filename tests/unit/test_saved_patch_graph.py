"""Saved output admission feeds the original Graph nodes without a model adapter."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from src.libs.llm import ChatResponse
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationError,
    _patch_continuation_state,
    preflight_patch_continuation,
)
from src.mod_agent.local_entry import (
    _patch_generation_obligation_projection,
    make_exact_no_write_dry_run_factory,
)
from src.mod_agent.proposal import LLMExactPatchGenerator, PatchProposalBuilder, ProposalReviewer
from src.mod_agent.workflow.graph import build_graph
from tests.unit.test_fresh_planning_continuation import _inputs, _patch_request, _source_hashes


def _saved_inputs(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    request = _patch_request(inputs)
    admitted = preflight_patch_continuation(request)
    plan, evidence = admitted.implementation_plan, admitted.evidence_pack
    obligations = _patch_generation_obligation_projection(
        feature_spec=admitted.feature_spec, implementation=plan,
        planned_changes=plan["proposed_changes"],
    )
    generator = LLMExactPatchGenerator(object())
    prepared = generator.prepare_native_contract(
        user_request=admitted.feature_spec["user_request"], evidence_items=evidence["items"],
        binding_registry=plan["binding_registry"], constraints=obligations["side_effect_boundaries"],
        target_behavior=obligations["target_behavior"], acceptance_criteria=obligations["acceptance_criteria"],
        runtime_verification_plan=obligations["runtime_verification_plan"],
        required_change_units=obligations["required_change_units"],
        required_validation_by_binding={item["edit_binding_id"]: item["expected_validation"]
                                        for item in obligations["required_change_units"]},
    )
    prompt = json.loads(prepared.messages[1].content)
    response = ChatResponse(model="test_saved_output", content=json.dumps({"changes": [
        {"edit_binding_id": item["edit_binding_id"], "rationale": "Retain feedback and record marker.",
         "rollback_hint": "Restore the selected span.",
         "after_text": prompt["edit_binding_contexts"][item["edit_binding_id"]]["source_excerpt"].replace(
             "KeepExistingFeedback();", "KeepExistingFeedback();\n        RecordRuntimeMarker();")}
        for item in prompt["required_change_units"]
    ]}))
    changes = list(generator.materialize_prepared_native(prepared, response).changes)
    hashes = {kind: getattr(request, kind + "_ref").artifact_hash
              for kind in ("feature_spec", "evidence_pack", "implementation_plan")}
    old_proposal = PatchProposalBuilder().build(
        {**plan, "proposed_changes": changes}, evidence_pack=evidence, artifact_hashes=hashes,
        source_snippet_char_limit=1,
    ).to_artifact_payload()
    proposal_ref = inputs.store.write(feature_id=inputs.feature_ref.feature_id,
        artifact_type="patch_proposal", payload=old_proposal, status="success",
        upstream_refs=[request.implementation_plan_ref, request.evidence_pack_ref])
    old_review = ProposalReviewer().review(old_proposal, implementation_plan=plan,
        evidence_pack=evidence, feature_spec=admitted.feature_spec,
        artifact_hashes={**hashes, "patch_proposal": proposal_ref.artifact_hash},
        require_executable_patch=True).to_artifact_payload()
    review_ref = inputs.store.write(feature_id=inputs.feature_ref.feature_id,
        artifact_type="proposal_review", payload=old_review, status="blocked", upstream_refs=[proposal_ref])
    saved = {
        "changes": changes, "source_attempt_ref": {"path": str(tmp_path / "old-attempt.json"), "sha256": "a" * 64},
        "source_proposal_ref": proposal_ref, "source_review_ref": review_ref,
        "response_ref": {"path": str(tmp_path / "old-response.txt"), "sha256": "b" * 64},
        "historical_verification": {"status": "passed", "executed_in_current_attempt": False},
        "request_id": "original_logical_request", "parent_run_id": "original_product_run",
        "inherited_model_budget": {"calls_used": 7}, "logical_budget": {"maximum": 14, "remaining": 7},
        "source_snapshot_sha256": "c" * 64,
    }
    # This file isolates the Graph from source-attempt admission, which has its own tests.
    object.__setattr__(request, "saved_patch_selection", {"source_attempt_ref": saved["source_attempt_ref"]})
    object.__setattr__(admitted, "saved_patch", saved)
    calls = []
    def admit(mode, *, artifact_store):
        assert mode is request and artifact_store is inputs.store
        calls.append("preflight")
        return admitted
    monkeypatch.setattr("src.mod_agent.workflow.graph.preflight_patch_continuation", admit)
    def forbidden(*args, **kwargs):
        pytest.fail("Saved output must not invoke a model or upstream adapter.")
    monkeypatch.setattr("src.mod_agent.workflow.graph._run_patch_continuation_factory", forbidden)
    state = _patch_continuation_state(run_id="new_saved_attempt", request_id=saved["request_id"],
        request=request, admitted=admitted)
    events = []
    kwargs = dict(dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
        use_default_proposal_git_binding=False, patch_continuation_mode=request,
        patch_continuation_max_model_calls=0, patch_continuation_attempt_recorder=events.append)
    return inputs, request, admitted, state, kwargs, events, calls


def test_saved_output_runs_original_proposal_review_and_real_dry_run(tmp_path, monkeypatch):
    inputs, request, admitted, state, kwargs, events, calls = _saved_inputs(tmp_path, monkeypatch)
    before = _source_hashes(inputs.workspace)
    old_refs = [admitted.saved_patch[name] for name in ("source_proposal_ref", "source_review_ref")]
    old_bytes = {ref.path: Path(ref.path).read_bytes() for ref in old_refs}
    graph = build_graph(inputs.store, **kwargs)
    result = graph.invoke(state)
    assert result["current_stage"] == "dry_run_apply"
    assert result["blockers"] == [] and result["approvals"] == {}
    assert [row["node_name"] for row in result["trace_events"] if row["event_type"] == "node_started"] == [
        "generate_patch_proposal", "review_proposal", "dry_run_apply"]
    assert len(calls) >= 2
    def read(kind):
        return inputs.store.read(ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
            path=result["artifacts"][kind], artifact_hash=result["artifact_hashes"][kind]))
    proposal, review, dry_run = [read(kind) for kind in ("patch_proposal", "proposal_review", "dry_run_result")]
    assert proposal["data"]["diff_intent"] == inputs.store.read(old_refs[0])["data"]["diff_intent"]
    lineage = proposal["data"]["context_pack"]["saved_patch_lineage"]
    assert lineage["source_proposal_ref"] == asdict(old_refs[0])
    assert lineage["source_review_ref"] == asdict(old_refs[1])
    assert lineage["response_ref"] == admitted.saved_patch["response_ref"]
    assert lineage["historical_verification"] == admitted.saved_patch["historical_verification"]
    assert review["data"]["allowed_next_stage"] == "dry_run_apply"
    assert dry_run["data"]["execution_mode"] == "dry_run"
    assert dry_run["data"]["actual_write_performed"] is False
    assert dry_run["data"]["diff_hash"]
    assert old_bytes == {ref.path: Path(ref.path).read_bytes() for ref in old_refs}
    assert _source_hashes(inputs.workspace) == before
    assert all(event.get("model_call_count", 0) == 0 and "factory_receipt" not in event for event in events)
    assert any(event["phase"] == "saved_patch_reassembled" for event in events)
    assert {edge.target for edge in graph.get_graph().edges} <= {
        "generate_patch_proposal", "review_proposal", "dry_run_apply", "__end__"}


@pytest.mark.parametrize("overrides", [
    {"patch_change_factory": lambda *args: ()}, {"patch_continuation_max_model_calls": 1},
    {"patch_continuation_max_model_calls": False}, {"dry_run_factory": None},
    {"patch_continuation_attempt_recorder": None},
])
def test_saved_output_rejects_execution_controls(tmp_path, monkeypatch, overrides):
    inputs, _, _, _, kwargs, _, _ = _saved_inputs(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        build_graph(inputs.store, **{**kwargs, **overrides})


def test_saved_output_rejects_new_logical_task_identity(tmp_path, monkeypatch):
    inputs, _, _, state, kwargs, events, _ = _saved_inputs(tmp_path, monkeypatch)
    state["request_id"] = "another_request"
    with pytest.raises(PatchContinuationError):
        build_graph(inputs.store, **kwargs).invoke(state)
    assert events == []


def test_saved_output_rechecks_admission_inside_proposal_node(tmp_path, monkeypatch):
    inputs, _, admitted, state, kwargs, events, _ = _saved_inputs(tmp_path, monkeypatch)
    calls = []
    def changed(mode, *, artifact_store):
        calls.append(True)
        if len(calls) > 1:
            raise PatchContinuationError("SAVED_SOURCE_CHANGED", "source_validation", "Bound source changed.")
        return admitted
    monkeypatch.setattr("src.mod_agent.workflow.graph.preflight_patch_continuation", changed)
    with pytest.raises(PatchContinuationError, match="SAVED_SOURCE_CHANGED"):
        build_graph(inputs.store, **kwargs).invoke(state)
    assert len(calls) == 2 and events == []


def test_saved_output_keeps_executable_patch_review_required(tmp_path, monkeypatch):
    inputs, _, admitted, state, kwargs, _, _ = _saved_inputs(tmp_path, monkeypatch)
    # Even a defective admitted change must face the real executable-patch Reviewer.
    admitted.saved_patch["changes"] = deepcopy(admitted.implementation_plan["proposed_changes"])
    result = build_graph(inputs.store, **kwargs).invoke(state)
    assert result["current_stage"] == "proposal_review"
    assert result["blockers"]
    assert "dry_run_result" not in result["artifacts"]
