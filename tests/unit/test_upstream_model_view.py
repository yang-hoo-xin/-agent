"""Upstream views deduplicate facts without narrowing source or changing local Plans."""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
from src.mod_agent.planning.upstream_model_view import project_upstream_model_view
from tests.unit.test_fresh_planning_continuation import _direct_graph_state, _inputs
from tests.unit.test_model_planning_selection import _Client, _stored_plan


def _payload():
    return {
        "feature": {"feature_id": "F", "user_request": "Keep user intent unchanged.",
            "acceptance_criteria": ["Exact acceptance identity."], "runtime_verification_plan": ["Observe behavior."]},
        "requirements": [{"text": "Keep user intent unchanged."}],
        "allowed_edit_evidence_ids": ["E"], "semantic_feedback": ["Keep the boundary.", "Investigate the new failure."],
        "source_observations": [{"evidence_id": "E", "source_identity_ref": 0, "source_path": "Mod/Config.cs",
            "span": {"start_line": 1, "end_line": 8}, "symbol": None, "claim_supported": "Current source.",
            "excerpt": "class Config {\n// 中文原文\n}\n", "selectable_for_edit": True}],
        "source_identity_table": [{"source_path": "Mod/Config.cs", "source_hash": "a" * 64, "source_type": "target_source"}],
        "upstream_assessment": {"current_failure_available": True, "failure_report": {"observed": "failure fact"},
            "previous_response": "the actual previous response", "retain_current_plan_allowed": False,
            "selected_artifact_hashes": {"implementation_plan": "b" * 64}, "current_plan": {
                "node_name": "create_implementation_plan", "stage": "implementation_plan", "feature_id": "F",
                "message": "Implementation plan is evidence-bound.", "blocking": False, "blockers": [], "open_questions": [],
                "evidence_refs": ["E"], "evidence_source_paths": ["Mod/Config.cs"], "target_files": ["Mod/Config.cs"],
                "test_plan": ["Observe behavior."], "side_effect_boundaries": ["Keep the boundary."],
                "verification_questions": ["Check this behavior."], "proposed_changes": [{"rationale": "Novel rationale."}],
                "binding_registry": {"owner_artifact_type": "implementation_plan", "schema_version": "binding_registry_v1",
                    "edit_bindings": [{"binding_id": "B", "evidence_id": "E", "canonical_target_path": "Mod/Config.cs",
                        "source_hash": "a" * 64, "source_type": "target_source", "claim_supported": "Current source.",
                        "target_span": {"start_line": 2, "end_line": 5}, "target_symbol": None,
                        "authority": "mod_agent_deterministic", "retrieval_method": "rg_live_read",
                        "usage": "edit_target_scope", "method_name": None, "verified_member_accesses": []}],
                    "supporting_bindings": []}}},
    }


def test_current_selector_uses_view_but_keeps_full_assessment_and_local_plan(tmp_path):
    from src.mod_agent.workflow.graph import _run_create_implementation_plan

    inputs = _inputs(tmp_path)
    initial = ModelPlanningTargetSelector(client=_Client(), workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "initial.json")
    state = _run_create_implementation_plan(_direct_graph_state(inputs), inputs.store,
        planning_target_selection_factory=initial)
    envelope = _stored_plan(inputs, state)
    original_bytes = (inputs.store.root / state["artifacts"]["implementation_plan"]).read_bytes()
    selector = ModelPlanningTargetSelector(client=_Client(), workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "upstream.json")
    assessment = {"current_plan": deepcopy(envelope["data"]), "retain_current_plan_allowed": True}
    selector.upstream_assessment = assessment
    selector.semantic_feedback = (*envelope["data"]["side_effect_boundaries"], "A new observation.")
    request = selector.prepare(inputs.feature_payload, inputs.store.read(inputs.evidence_ref)["data"])
    payload = request.messages[1].content
    assert "upstream_context_view" in payload
    assert payload["feature"] == inputs.feature_payload
    assert payload["semantic_feedback"] == ["A new observation."]
    assert selector.upstream_assessment == assessment
    assert assessment["current_plan"] == envelope["data"]
    assert (inputs.store.root / state["artifacts"]["implementation_plan"]).read_bytes() == original_bytes


def test_view_keeps_source_acceptance_ids_spans_and_failure_facts_verbatim():
    payload = _payload()
    before = deepcopy(payload)
    view = project_upstream_model_view(payload)
    assert payload == before
    for key in ("feature", "requirements", "source_observations", "source_identity_table", "allowed_edit_evidence_ids"):
        assert view[key] == before[key]
    plan = view["upstream_assessment"]["current_plan"]
    binding = plan["binding_registry"]["edit_bindings"][0]
    assert binding == {"binding_id": "B", "evidence_id": "E", "target_span": {"start_line": 2, "end_line": 5}}
    assert plan["target_files"] == before["upstream_assessment"]["current_plan"]["target_files"]
    assert plan["test_plan_ref"] == "/feature/runtime_verification_plan"
    assert view["semantic_feedback"] == ["Investigate the new failure."]
    for key in ("failure_report", "previous_response", "retain_current_plan_allowed", "selected_artifact_hashes"):
        assert view["upstream_assessment"][key] == before["upstream_assessment"][key]


@pytest.mark.parametrize("field,value", [
    ("canonical_target_path", "Different/File.cs"), ("source_hash", "c" * 64),
    ("claim_supported", "A different claim."), ("target_span", {"start_line": 3, "end_line": 7}),
    ("method_name", "ChangedMethod"), ("authority", "other_authority"),
    ("verified_member_accesses", [{"member": "CurrentApi"}]), ("unknown_field", None),
])
def test_novel_binding_facts_and_range_differences_are_retained(field, value):
    payload = _payload()
    payload["upstream_assessment"]["current_plan"]["binding_registry"]["edit_bindings"][0][field] = value
    binding = project_upstream_model_view(payload)["upstream_assessment"]["current_plan"]["binding_registry"]["edit_bindings"][0]
    assert binding[field] == value


def test_nonidentical_feedback_and_custom_plan_fields_are_not_discarded():
    payload = _payload()
    plan = payload["upstream_assessment"]["current_plan"]
    plan.update(test_plan=["A different acceptance check."], message="Novel diagnostic message.",
        blockers=[{"reason": "Keep this actual blocker."}], open_questions=["New question."], custom_fact="preserved")
    payload["semantic_feedback"].append("Keep the boundary. More detail.")
    view = project_upstream_model_view(payload)
    projected = view["upstream_assessment"]["current_plan"]
    for field in ("test_plan", "message", "blockers", "open_questions", "custom_fact", "proposed_changes", "verification_questions"):
        assert projected[field] == plan[field]
    assert "test_plan_ref" not in projected
    assert "Keep the boundary. More detail." in view["semantic_feedback"]


def test_ambiguous_or_missing_source_identity_does_not_invent_a_join():
    payload = _payload()
    payload["source_observations"].append(deepcopy(payload["source_observations"][0]))
    assert project_upstream_model_view(payload) == payload
    payload = _payload()
    binding = payload["upstream_assessment"]["current_plan"]["binding_registry"]["edit_bindings"][0]
    binding["evidence_id"] = "unknown"
    assert project_upstream_model_view(payload)["upstream_assessment"]["current_plan"]["binding_registry"]["edit_bindings"][0] == binding


def test_non_upstream_payload_is_unchanged():
    payload = _payload()
    payload.pop("upstream_assessment")
    assert project_upstream_model_view(payload) == payload
