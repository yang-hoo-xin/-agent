"""Planning correction counterexamples; controlled responses, no model/network."""
from __future__ import annotations

import hashlib
import json
import socket
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.libs.llm.agent_turn import AgentMessage, AgentTurnResponse, AgentUsage
from src.mod_agent.evidence import RgLiveEvidenceProvider, build_requirement_coverage_pack
from src.mod_agent.evidence.requirement_coverage import materialize_requirement_coverage_projection
from src.mod_agent.planning import ImplementationPlanner
from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
from src.mod_agent.planning.target_correction import correct_unsafe_target_selection
from src.mod_agent.workflow.graph import _feature_spec_from_payload, _run_create_implementation_plan
from tests.unit.test_fresh_planning_continuation import (
    _direct_graph_state,
    _inputs,
    _positive_findings,
    _projection,
    _write_evidence_revision,
)
from tests.unit.test_model_planning_selection import _stored_plan


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Planning correction tests are offline"))


def _overlap_inputs(tmp_path):
    inputs = _inputs(tmp_path)
    materialized = materialize_requirement_coverage_projection(feature_data=inputs.feature_payload,
        request=inputs.feature_payload["user_request"], projection=_projection())
    retrieved = RgLiveEvidenceProvider(inputs.workspace).collect_query_set(
        queries=tuple(dict(row) for row in materialized["queries"]),
        search_root="generated_mods/SyntheticMod", max_items=len(materialized["queries"]))
    findings = _positive_findings(materialized, retrieved)
    first_id = findings["findings"][0]["edit_target_evidence_ids"][0]
    method = next(item for item in retrieved.items if item.evidence_id == first_id)
    lines = (inputs.workspace / method.source_path).read_text(encoding="utf-8").splitlines(keepends=True)
    window = replace(method, evidence_id="overlapping-anonymous-window", chunk_id="overlapping-window",
        span={"start_line": 1, "end_line": method.span["start_line"]},
        excerpt="".join(lines[:method.span["start_line"]]), declaring_type=None,
        declaring_type_full_name=None, method_name=None, method_kind=None, parameter_types=None,
        return_type=None)
    retrieved = replace(retrieved, items=(*retrieved.items, window))
    findings["findings"][0]["evidence_ids"].append(window.evidence_id)
    evidence = build_requirement_coverage_pack(query=inputs.feature_payload["user_request"],
        materialized_projection=materialized, retrieved_pack=retrieved, findings=findings).to_artifact_payload()
    ref = _write_evidence_revision(inputs, payload=evidence)
    inputs = replace(inputs, evidence_ref=ref)
    selected = (method.evidence_id, window.evidence_id)
    initial = ImplementationPlanner().build(feature_spec=_feature_spec_from_payload(inputs.feature_payload),
        evidence_pack=evidence, formal_requirement_coverage_required=True,
        planning_target_evidence_ids=selected)
    assert initial.blocking and [row["code"] for row in initial.blockers] == ["EDIT_TARGET_NORMALIZATION_UNSAFE"]
    return inputs, evidence, selected


class _Client:
    provider = "controlled-local"
    model = "controlled-planning"

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def complete_turn(self, request):
        self.calls.append(request)
        response = self.responses[len(self.calls) - 1]
        if callable(response):
            response = response(request)
        return AgentTurnResponse(provider=self.provider, model=self.model,
            content=json.dumps(response), usage=AgentUsage(input_tokens=30, output_tokens=10))


def _selection(ids):
    return {"decision": "select_targets", "selected_evidence_ids": list(ids),
            "rationale": "Controlled semantic decision for the selected current source.", "missing_evidence": []}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _strings(item)


def _run(inputs, client, *, selector=None, **kwargs):
    selector = selector or ModelPlanningTargetSelector(client=client, workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "initial-selection.json", semantic_feedback=("Preserve existing behavior.",))
    state = _run_create_implementation_plan(_direct_graph_state(inputs), inputs.store,
        formal_requirement_coverage_required=True, planning_target_selection_factory=selector, **kwargs)
    return selector, _stored_plan(inputs, state)


def test_normalization_failure_reaches_one_child_selection_and_full_original_planner(tmp_path):
    inputs, _, ids = _overlap_inputs(tmp_path)
    client = _Client([_selection(ids), _selection(ids[:1])])
    selector, plan = _run(inputs, client)
    assert len(client.calls) == 2
    assert plan["status"] == "success"
    assert [row["evidence_id"] for row in plan["data"]["binding_registry"]["edit_bindings"]] == list(ids[:1])
    assert len(selector.planning_trace_refs()) == 2


def test_child_only_adds_feedback_preserving_memory_payload_schema_and_first_receipt(tmp_path, monkeypatch):
    inputs, _, ids = _overlap_inputs(tmp_path)
    memory = object()
    calls = []
    client = _Client([_selection(ids), _selection(ids[:1])])
    selector = ModelPlanningTargetSelector(client=client, workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "selection.json", task_memory=memory,
        semantic_feedback=("Keep existing independent controls.",), model_identity={"digest": "frozen-model"})

    def original_memory(_feature, _observations):
        calls.append("retrieved")
        selector._task_memory_receipt = {"original": "memory snapshot"}
        return {"lessons": [{"fact": "first observed memory"}], "authority": "planning_only"}

    monkeypatch.setattr(selector, "_prepare_task_memory", original_memory)
    trace = ExecutionTrace("planning-trace", "session", "test")
    with trace.activate():
        selector, plan = _run(inputs, client, selector=selector)
    assert calls == ["retrieved"]
    first, second = client.calls
    corrected_payload = deepcopy(second.messages[1].content)
    correction = corrected_payload.pop("correction_context")
    restored = replace(second, messages=(second.messages[0], AgentMessage(role="user", content=corrected_payload)))
    assert restored == first
    assert correction["previous_selection"] == _selection(ids)
    assert correction["deterministic_blocker"]["code"] == "EDIT_TARGET_NORMALIZATION_UNSAFE"
    child = selector._target_correction
    local_correction = child.correction_context
    parent = Path(local_correction["first_receipt_ref"]["path"])
    assert correction["first_receipt_ref"] == {"sha256": local_correction["first_receipt_ref"]["sha256"]}
    assert all(str(parent) not in value for value in _strings(second.messages[1].content))
    assert hashlib.sha256(parent.read_bytes()).hexdigest() == correction["first_receipt_ref"]["sha256"]
    assert json.loads(parent.read_text(encoding="utf-8"))["selection"] == _selection(ids)
    decisions = [row["data"] for row in trace.context.stages if row["data"]["name"] == "planning.decision"
                 and row["data"]["status"] == "completed"]
    assert any(row["attributes"]["local_detail_refs"]["planning_receipt"] == local_correction["first_receipt_ref"]
               for row in decisions)
    assert child.client is client and child.task_memory is memory
    assert child.semantic_feedback == selector.semantic_feedback and child.model_identity == selector.model_identity
    assert len(plan["trace_refs"]) == 2
    receipts = [json.loads(Path(ref.split("#sha256=")[0]).read_text(encoding="utf-8")) for ref in plan["trace_refs"]]
    assert all(receipt["response_content"] for receipt in receipts)
    assert receipts[1]["correction_context"] == local_correction
    assert plan["data"]["side_effect_boundaries"].count("Keep existing independent controls.") == 1
    assert correction["deterministic_blocker"]["message"] not in plan["data"]["side_effect_boundaries"]


def test_second_normalization_failure_does_not_get_a_third_call(tmp_path):
    inputs, _, ids = _overlap_inputs(tmp_path)
    client = _Client([_selection(ids), _selection(ids)])
    selector, plan = _run(inputs, client)
    assert len(client.calls) == 2 and plan["status"] == "blocked"
    assert [row["code"] for row in plan["data"]["blockers"]] == ["EDIT_TARGET_NORMALIZATION_UNSAFE"]
    assert len(selector.planning_trace_refs()) == 2


def test_needs_evidence_preserves_first_failure_and_child_raw_response(tmp_path):
    inputs, _, ids = _overlap_inputs(tmp_path)
    response = {"decision": "needs_evidence", "selected_evidence_ids": [],
                "rationale": "The present ranges do not explain the whole edit.",
                "missing_evidence": ["A complete source unit is needed."]}
    client = _Client([_selection(ids), response])
    selector, plan = _run(inputs, client)
    assert len(client.calls) == 2 and plan["status"] == "blocked"
    assert [row["code"] for row in plan["data"]["blockers"]] == [
        "EDIT_TARGET_NORMALIZATION_UNSAFE", "PLANNING_MODEL_NEEDS_EVIDENCE"]
    child_receipt = json.loads(selector._target_correction.receipt_path.read_text(encoding="utf-8"))
    assert json.loads(child_receipt["response_content"]) == response
    assert child_receipt["correction_context"]["previous_selection"] == _selection(ids)


def test_source_drift_after_first_plan_prevents_second_model_call(tmp_path, monkeypatch):
    inputs, _, ids = _overlap_inputs(tmp_path)
    build = ImplementationPlanner.build

    def drift_after_rejection(planner, **kwargs):
        result = build(planner, **kwargs)
        inputs.behavior.write_text(inputs.behavior.read_text(encoding="utf-8") + "// drift\n", encoding="utf-8")
        return result

    monkeypatch.setattr(ImplementationPlanner, "build", drift_after_rejection)
    client = _Client([_selection(ids)])
    selector, plan = _run(inputs, client)
    assert len(client.calls) == 1 and plan["status"] == "blocked"
    receipt = json.loads(selector._target_correction.receipt_path.read_text(encoding="utf-8"))
    assert receipt["model_turns_attempted"] == receipt["model_responses_received"] == 0
    assert receipt["correction_context"]["deterministic_blocker"]["code"] == "EDIT_TARGET_NORMALIZATION_UNSAFE"


def test_existing_budget_reservation_rejects_child_without_refund_or_new_provider_call(tmp_path):
    from src.mod_agent.local_entry import _reserve_request_model_call

    inputs, _, ids = _overlap_inputs(tmp_path)

    class BudgetClient(_Client):
        def __init__(self):
            super().__init__([_selection(ids)])
            self.budget = {"maximum": 1, "consumed": 0, "remaining": 1, "policy": "task_total_only",
                "count_basis": "reserved_provider_invocations_not_transport_proof", "by_stage": {"planning": {"consumed": 0}}}
            self.entries = 0

        def complete_turn(self, request):
            self.entries += 1
            self.budget = _reserve_request_model_call(self.budget, "planning")
            return super().complete_turn(request)

    client = BudgetClient()
    selector, plan = _run(inputs, client)
    assert client.entries == 2 and len(client.calls) == 1
    assert client.budget["consumed"] == 1 and client.budget["remaining"] == 0
    assert plan["status"] == "blocked"
    receipt = json.loads(selector._target_correction.receipt_path.read_text(encoding="utf-8"))
    assert receipt["model_responses_received"] == 0
    assert receipt["model_call_boundary"]["reservation_succeeded"] is False
    assert receipt["model_call_boundary"]["model_transport_started"] is False
    assert "PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED" in receipt["failure"]["message"]


def test_normal_success_remains_one_call(tmp_path):
    inputs = _inputs(tmp_path)
    client = _Client([_selection(inputs.request.planning_target_evidence_ids)])
    selector, plan = _run(inputs, client)
    assert plan["status"] == "success" and len(client.calls) == 1
    assert selector._target_correction is None and len(plan["trace_refs"]) == 1


def test_upstream_assessment_does_not_automatically_correct_targets(tmp_path):
    inputs, _, ids = _overlap_inputs(tmp_path)
    client = _Client([_selection(ids)])
    selector = ModelPlanningTargetSelector(client=client, workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "upstream.json")
    selector.upstream_assessment = {"retain_current_plan_allowed": False}
    selector, plan = _run(inputs, client, selector=selector)
    assert len(client.calls) == 1 and plan["status"] == "blocked"
    assert selector._target_correction is None


def test_explicit_planning_continuation_does_not_invoke_autonomous_selection(tmp_path):
    inputs = _inputs(tmp_path)
    client = _Client([])
    selector, plan = _run(inputs, client, planning_continuation_mode=inputs.request)
    assert client.calls == [] and plan["status"] == "blocked"
    assert selector._target_correction is None


def test_multiple_blockers_do_not_expand_the_correction_trigger(tmp_path):
    inputs, evidence, ids = _overlap_inputs(tmp_path)
    spec = _feature_spec_from_payload(inputs.feature_payload)
    initial = ImplementationPlanner().build(feature_spec=spec, evidence_pack=evidence,
        formal_requirement_coverage_required=True, planning_target_evidence_ids=ids)
    initial = replace(initial, blockers=(*initial.blockers, {"code": "ANOTHER_FAILURE", "message": "Keep blocked."}))
    client = _Client([])
    selector = ModelPlanningTargetSelector(client=client, workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "selection.json")
    result = correct_unsafe_target_selection(implementation=initial, selector=selector, feature_spec=spec,
        evidence_pack=evidence, formal_requirement_coverage_required=True, allow_correction=True)
    assert result is initial and client.calls == []
