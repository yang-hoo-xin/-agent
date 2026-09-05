from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.libs.llm.agent_turn import AgentTurnResponse, AgentUsage
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.evidence import (
    RgLiveEvidenceProvider,
    build_requirement_coverage_pack,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.local_entry import _patch_generation_obligation_projection
from src.mod_agent.planning.model_selection import (
    ModelPlanningTargetSelector,
    PlanningTargetSelectionError,
)
from src.mod_agent.workflow import build_graph
from src.mod_agent.workflow.graph import _run_create_implementation_plan
from src.mod_agent.workflow.transitions import route_after_implementation_plan
from tests.unit.test_fresh_planning_continuation import (
    _direct_graph_state,
    _inputs,
    _positive_findings,
    _projection,
    _write_evidence_revision,
)


class _Client:
    provider = "local_test"
    model = "planning-test-model"

    def __init__(self, *, override=None, mutate=None):
        self.calls = []
        self.override = override
        self.mutate = mutate

    def complete_turn(self, request):
        self.calls.append(request)
        if self.mutate:
            self.mutate()
        payload = {
            "decision": "select_targets",
            "selected_evidence_ids": request.messages[1].content["allowed_edit_evidence_ids"],
            "rationale": "The selected source implements the requested change and preserves feedback.",
            "missing_evidence": [],
        }
        if self.override is not None:
            payload = self.override(payload)
        return AgentTurnResponse(
            provider=self.provider,
            model=self.model,
            content=payload if isinstance(payload, str) else json.dumps(payload),
            usage=AgentUsage(input_tokens=100, output_tokens=20),
        )


def _selector(inputs, client, *, feedback=()):
    return ModelPlanningTargetSelector(
        client=client,
        workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "selection.json",
        semantic_feedback=feedback,
    )


def _stored_plan(inputs, state):
    return inputs.store.read(
        ArtifactRef(
            feature_id=inputs.feature_ref.feature_id,
            artifact_type="implementation_plan",
            path=state["artifacts"]["implementation_plan"],
            artifact_hash=state["artifact_hashes"]["implementation_plan"],
        )
    )


def test_model_selection_is_consumed_by_production_planning_node(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    client = _Client()
    feedback = "Preserve independent feedback on cold start."
    selector = _selector(inputs, client, feedback=(feedback, feedback))
    state = _run_create_implementation_plan(
        _direct_graph_state(inputs),
        inputs.store,
        formal_requirement_coverage_required=True,
        planning_target_selection_factory=selector,
    )
    plan = _stored_plan(inputs, state)
    receipt = json.loads(selector.receipt_path.read_text(encoding="utf-8"))
    selected = receipt["selection"]["selected_evidence_ids"]
    assert len(client.calls) == 1
    assert {b["evidence_id"] for b in plan["data"]["binding_registry"]["edit_bindings"]} == set(
        selected
    )
    assert plan["status"] == "success"
    assert route_after_implementation_plan(state) == "continue"
    assert receipt["selection_mode"] == "model"
    assert receipt["operator_target_ids_supplied"] is False
    assert receipt["response_content"]
    assert receipt["usage"]["input_tokens"] == 100
    assert plan["trace_refs"] == selector.planning_trace_refs()
    payload = client.calls[0].messages[1].content
    assert payload["semantic_feedback"] == [feedback, feedback]
    assert plan["data"]["side_effect_boundaries"].count(feedback) == 1
    obligations = _patch_generation_obligation_projection(
        feature_spec=inputs.feature_payload,
        implementation=plan["data"],
        planned_changes=plan["data"]["proposed_changes"],
    )
    assert obligations["side_effect_boundaries"].count(feedback) == 1
    assert "edit_target_evidence_ids" not in payload
    assert set(state["artifacts"]) == {"feature_spec", "evidence_pack", "implementation_plan"}


def test_compiled_graph_installs_model_selector_on_existing_node(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    client = _Client()
    graph = build_graph(inputs.store, planning_target_selection_factory=_selector(inputs, client))
    # Exercise the production runnable installed by build_graph, not a parallel planner.
    node = graph.get_graph().nodes["create_implementation_plan"].data
    state = node.invoke(_direct_graph_state(inputs))
    assert _stored_plan(inputs, state)["status"] == "success"
    assert len(client.calls) == 1


def test_model_selection_can_differ_from_findings_hints(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    materialized = materialize_requirement_coverage_projection(
        feature_data=inputs.feature_payload,
        request=str(inputs.feature_payload["user_request"]),
        projection=_projection(),
    )
    retrieved = RgLiveEvidenceProvider(inputs.workspace).collect_query_set(
        queries=tuple(dict(q) for q in materialized["queries"]),
        search_root="generated_mods/SyntheticMod",
        max_items=len(materialized["queries"]),
    )
    findings = _positive_findings(materialized, retrieved)
    hint_ids = findings["findings"][0]["edit_target_evidence_ids"]
    source_ids = [item.evidence_id for item in retrieved.items]
    selected = next(value for value in source_ids if value not in hint_ids)
    findings["findings"][0]["evidence_ids"] = source_ids
    evidence = build_requirement_coverage_pack(
        query=str(inputs.feature_payload["user_request"]),
        materialized_projection=materialized,
        retrieved_pack=retrieved,
        findings=findings,
    ).to_artifact_payload()
    evidence_ref = _write_evidence_revision(inputs, payload=evidence)
    client = _Client(override=lambda payload: {**payload, "selected_evidence_ids": [selected]})
    selector = _selector(inputs, client)
    state = _direct_graph_state(inputs)
    state["artifacts"]["evidence_pack"] = evidence_ref.path
    state["artifact_hashes"]["evidence_pack"] = evidence_ref.artifact_hash
    result = _run_create_implementation_plan(
        state,
        inputs.store,
        formal_requirement_coverage_required=True,
        planning_target_selection_factory=selector,
    )
    plan = _stored_plan(inputs, result)
    assert plan["status"] == "success"
    assert [b["evidence_id"] for b in plan["data"]["binding_registry"]["edit_bindings"]] == [
        selected
    ]
    assert selected not in hint_ids


@pytest.mark.parametrize("kind", ["missing", "unknown", "duplicate", "malformed"])
def test_model_selection_failure_stores_blocked_plan_without_fallback(
    tmp_path: Path, kind: str
) -> None:
    inputs = _inputs(tmp_path)

    def override(payload):
        if kind == "missing":
            return {
                **payload,
                "decision": "needs_evidence",
                "selected_evidence_ids": [],
                "missing_evidence": ["Caller state is unavailable."],
            }
        if kind == "unknown":
            return {**payload, "selected_evidence_ids": ["unknown_source"]}
        if kind == "duplicate":
            return {**payload, "selected_evidence_ids": payload["selected_evidence_ids"] * 2}
        return "not json"

    client = _Client(override=override)
    selector = _selector(inputs, client)
    state = _run_create_implementation_plan(
        _direct_graph_state(inputs),
        inputs.store,
        formal_requirement_coverage_required=True,
        planning_target_selection_factory=selector,
    )
    plan = _stored_plan(inputs, state)
    assert plan["status"] == "blocked"
    assert plan["data"]["proposed_changes"] == []
    assert route_after_implementation_plan(state) == "blocked"
    assert len(client.calls) == 1
    assert json.loads(selector.receipt_path.read_text())["response_content"]


@pytest.mark.parametrize("when", ["before", "after"])
def test_model_selection_checks_live_source_on_both_sides(tmp_path: Path, when: str) -> None:
    inputs = _inputs(tmp_path)

    def mutate():
        inputs.behavior.write_text(inputs.behavior.read_text() + "// source drift\n")

    client = _Client(mutate=mutate if when == "after" else None)
    if when == "before":
        mutate()
    selector = _selector(inputs, client)
    state = _run_create_implementation_plan(
        _direct_graph_state(inputs),
        inputs.store,
        formal_requirement_coverage_required=True,
        planning_target_selection_factory=selector,
    )
    assert _stored_plan(inputs, state)["status"] == "blocked"
    assert len(client.calls) == int(when == "after")
    receipt = json.loads(selector.receipt_path.read_text())
    assert receipt["status"] == "blocked"
    assert receipt["model_responses_received"] == int(when == "after")


def test_prepare_is_no_call_and_attempt_cannot_overwrite_receipt(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    client = _Client()
    selector = _selector(inputs, client)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    prepared = selector.prepare(inputs.feature_payload, evidence)
    assert prepared.tools == ()
    assert not selector.receipt_path.exists()
    selector(inputs.feature_payload, evidence)
    before = selector.receipt_path.read_bytes()
    with pytest.raises(PlanningTargetSelectionError, match="already been consumed"):
        selector(inputs.feature_payload, evidence)
    with pytest.raises(PlanningTargetSelectionError):
        _selector(inputs, client)(inputs.feature_payload, evidence)
    assert selector.receipt_path.read_bytes() == before
    assert len(client.calls) == 1
