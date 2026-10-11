"""Offline explicit upstream assessments may retain an unchanged bound Plan."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from src.mod_agent.fresh_planning_continuation import preflight_patch_continuation
from src.mod_agent.local_entry import _patch_agent_context_json, _restore_patch_agent_context
from src.mod_agent.planning.model_selection import PlanningTargetSelectionError
from src.mod_agent.proposal.patch_agent_loop import PATCH_UPSTREAM_REQUEST_TOOL_NAME
from src.mod_agent.repair.upstream import run_patch_upstream_replanning
from tests.unit.test_model_planning_selection import _Client, _selector
from tests.unit.test_patch_repair_cli import _message_jsons, _sha, _source_hashes, _write_json
from tests.unit.test_patch_repair_continuation import _repair_case
from tests.unit.test_patch_upstream_budget import _ConsumedReadTransport
from tests.unit.test_patch_upstream_cli import _case, _run
from tests.unit.test_patch_upstream_replanning import _evidence_factory, _Findings, _selection


def _retain(_result):
    return {
        "decision": "retain_current_plan",
        "selected_evidence_ids": [],
        "rationale": "The observed failure is in the local implementation; the current scope still covers the repair.",
        "missing_evidence": [],
    }


def test_explicit_upstream_retain_keeps_original_plan_and_explains_repair(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    old_revisions = inputs.store.list_feature_artifact_revisions(
        request.feature_spec_ref.feature_id, "implementation_plan"
    )
    client = _Client(override=_retain)
    selector = _selector(inputs, client)
    state = run_patch_upstream_replanning(
        request=request,
        selection=_selection(),
        planning_target_selection_factory=selector,
    )
    assert not state["blockers"]
    assert state["artifacts"]["implementation_plan"] == request.implementation_plan_ref.path
    assert state["artifact_hashes"]["implementation_plan"] == request.implementation_plan_ref.artifact_hash
    assert inputs.store.list_feature_artifact_revisions(
        request.feature_spec_ref.feature_id, "implementation_plan"
    ) == old_revisions
    assert len(client.calls) == 1
    assessment = client.calls[0].messages[1].content["upstream_assessment"]
    original_plan = inputs.store.read(request.implementation_plan_ref)["data"]
    for field in ("target_files", "target_symbols", "proposed_changes", "side_effect_boundaries"):
        assert assessment["current_plan"][field] == original_plan[field]
    assert assessment["failure_report"]
    assert assessment["previous_response"]
    assert assessment["retain_current_plan_allowed"] is True
    assert state["runtime_summary"]["planning_upstream_assessment"]["decision"] == "retain_current_plan"
    assert state["runtime_summary"]["planning_upstream_assessment"]["rationale"] == _retain({})["rationale"]
    assert state["approvals"] == {}
    assert selector.upstream_assessment is None


def test_initial_planning_cannot_return_retain_current_plan(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    selector = _selector(inputs, _Client(override=_retain))
    with pytest.raises(PlanningTargetSelectionError):
        selector(
            inputs.store.read(request.feature_spec_ref)["data"],
            inputs.store.read(request.evidence_pack_ref)["data"],
        )


def test_same_target_selection_is_not_an_implicit_retention(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    state = run_patch_upstream_replanning(request=request, selection=_selection(),
        planning_target_selection_factory=_selector(inputs, _Client()))
    assert not state["blockers"]
    assert state["artifact_hashes"]["implementation_plan"] != request.implementation_plan_ref.artifact_hash
    assert "planning_upstream_assessment" not in state["runtime_summary"]


def test_changed_evidence_cannot_silently_retain_old_plan_dependencies(tmp_path):
    inputs, request, _ = _repair_case(tmp_path)
    old = preflight_patch_continuation(request).evidence_pack
    findings = _Findings({"findings": [
        {"relation_index": index, **{key: row[key] for key in (
            "relationship", "evidence_ids", "edit_target_evidence_ids", "unresolved_gaps")}}
        for index, row in enumerate(old["requirement_coverage"]["findings"], 1)
    ]})
    client = _Client(override=_retain)
    state = run_patch_upstream_replanning(request=request, selection=_selection("evidence"),
        evidence_pack_factory=_evidence_factory(inputs, findings),
        planning_target_selection_factory=_selector(inputs, client))
    assert state["artifact_hashes"]["evidence_pack"] != request.evidence_pack_ref.artifact_hash
    assert state["blockers"][0]["code"] == "PLANNING_MODEL_RETAIN_PLAN_NOT_ADMITTED"
    assert client.calls[0].messages[1].content["upstream_assessment"]["retain_current_plan_allowed"] is False
    assert "retain_current_plan" not in client.calls[0].response_format.schema["properties"]["decision"]["enum"]
    assert "planning_upstream_assessment" not in state["runtime_summary"]


@pytest.mark.parametrize("mutation", ["source", "plan", "failure"])
def test_post_model_identity_drift_prevents_retention(tmp_path, mutation):
    inputs, request, _ = _repair_case(tmp_path)
    if mutation == "source":
        evidence = inputs.store.read(request.evidence_pack_ref)["data"]
        target = inputs.workspace / next(item["source_path"] for item in evidence["items"]
                                         if item["source_type"] == "target_source")
    elif mutation == "plan":
        target = Path(request.implementation_plan_ref.path)
    else:
        target = Path(request.repair_failure_report_ref["path"])
    original = target.read_bytes()

    def change():
        if mutation == "plan":
            value = json.loads(original)
            value["data"]["side_effect_boundaries"].append("Synthetic changed Plan boundary.")
            target.write_text(json.dumps(value), encoding="utf-8")
        else:
            target.write_bytes(original + b"\n ")

    try:
        state = run_patch_upstream_replanning(request=request, selection=_selection(),
            planning_target_selection_factory=_selector(inputs, _Client(override=_retain, mutate=change)))
        assert state["blockers"]
        assert "planning_upstream_assessment" not in state["runtime_summary"]
    finally:
        target.write_bytes(original)


@pytest.mark.parametrize("rationale", [
    "The current Plan remains complete; fix the local code.",
    "保持现有范围；失败涉及局部实现，仍需按当前证据完成修改。",
])
def test_retention_rationale_is_model_semantics_without_keyword_routing(tmp_path, rationale):
    inputs, request, _ = _repair_case(tmp_path)
    state = run_patch_upstream_replanning(request=request, selection=_selection(),
        planning_target_selection_factory=_selector(inputs, _Client(
            override=lambda result: {**_retain(result), "rationale": rationale})))
    assert not state["blockers"]
    assert state["runtime_summary"]["planning_upstream_assessment"]["rationale"] == rationale


class _RetainTransport(_ConsumedReadTransport):
    """Scripted provider responses; production CLI, Graph and worker execute."""

    def __init__(self, root, case, *, repeat_upstream=False):
        super().__init__(root, case)
        self.repeat_upstream = repeat_upstream

    def __call__(self, request):
        if request.method != "POST" or request.url.path != "/api/chat":
            return super().__call__(request)
        payload = json.loads(request.content)
        values = [value for _, value in _message_jsons(payload)]
        planning = next((value for value in values if "allowed_edit_evidence_ids" in value), None)
        if planning is not None:
            super().__call__(request)
            assert planning["upstream_assessment"]["previous_response"] == self.latest_failed_raw
            assert planning["upstream_assessment"]["failure_report"]["generated_changes_sha256"] == self.new_failure["generated_changes_sha256"]
            selection = _retain({})
            # 为什么要有它：配置行为检查器时真实 Planning 合同使用 verification_questions，模拟响应须遵守当前 schema。
            if "verification_questions" in payload["format"]["properties"]:
                selection["verification_questions"] = selection.pop("missing_evidence")
            assert set(selection) == set(payload["format"]["required"])
            return self._response(request, {"role": "assistant", "content": json.dumps(selection)})
        if not self.planning_sent:
            return super().__call__(request)
        self.requests.append((request.method, str(request.url)))
        self.chat_requests.append((request.content, payload))
        self.stage_roles.append("patch")
        self.retained_payload = deepcopy(payload)
        if self.repeat_upstream:
            return self._response(request, {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": PATCH_UPSTREAM_REQUEST_TOOL_NAME, "arguments": {
                    "required_owner": "planning", "reason": "Synthetic repeated upstream request.",
                    "source_refs": ["binding://edit_binding_001"],
                }},
            }]})
        prompt = _restore_patch_agent_context(next(value for value in values if "required_change_units" in value))
        self.patch_prompts.append(prompt)
        content = self._patch(prompt, passed=True)
        self.generated_texts.append(json.dumps(content))
        return self._response(request, {"role": "assistant", "content": json.dumps(content)})


@pytest.mark.parametrize("repeat_upstream", [False, True], ids=["finish", "no-second-upstream"])
def test_public_cli_retains_plan_tool_history_and_last_model_allowance(tmp_path, monkeypatch, capsys, repeat_upstream):
    case = _case(tmp_path, monkeypatch)
    case.config["policy"]["max_tool_rounds"] = 1
    _write_json(case.config_path, case.config)
    before = _source_hashes(case.inputs.workspace)
    revisions = case.inputs.store.list_feature_artifact_revisions(
        case.request.feature_spec_ref.feature_id, "implementation_plan")
    handler = _RetainTransport(tmp_path / "wire", case, repeat_upstream=repeat_upstream)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
        lambda _self, request: transport.handle_request(request))

    def forbid(*_args, **_kwargs):
        raise AssertionError("This scripted acceptance must not use real network or a real model.")

    monkeypatch.setattr("socket.socket.connect", forbid)
    monkeypatch.setattr("socket.socket.connect_ex", forbid)
    code, result = _run(case, capsys)
    diagnostic = {key: result.get(key) for key in ("status", "reason", "first_failure")}
    assert (code != 0) if repeat_upstream else (code == 0), diagnostic
    assert handler.stage_roles == ["patch", "patch", "patch", "planning", "patch"], diagnostic
    assert result["implementation_plan_artifact"]["artifact_hash"] == case.request.implementation_plan_ref.artifact_hash
    assert case.inputs.store.list_feature_artifact_revisions(
        case.request.feature_spec_ref.feature_id, "implementation_plan") == revisions
    assert result["execution_counts"]["model"] == 5
    assert result["execution_counts"]["planning"] == 1
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == (0 if repeat_upstream else 1)
    assert result["execution_counts"]["apply"] == result["execution_counts"]["build"] == result["execution_counts"]["runtime"] == 0
    journal = json.loads(Path(result["attempt_receipt"]["path"]).read_text())
    first, second = journal["patch_execution_segments"]
    assert first["selected_artifacts"] == second["selected_artifacts"]
    assert second["factory_receipt"]["context_calibration_inheritance"] == {
        "status": "inherited", "observed_calibration_count": 3,
        "client_transport_reused": False, "context_window_changed": False}
    loop = second["factory_receipt"]["patch_agent_loop"]
    assert loop["prior_worker_budget"]["consumed_model_turns"] == 3
    assert loop["prior_worker_budget"]["consumed_tool_rounds"] == 1
    old_loop = first["factory_receipt"]["patch_agent_loop"]
    old_source_bytes = old_loop["total_observation_bytes"] + old_loop["behavior_correction"]["execution"]["total_observation_bytes"]
    assert loop["prior_worker_budget"]["consumed_observation_bytes"] == old_source_bytes + old_loop["recovery_observation_bytes"]
    assert loop["model_turns_used"] == 1
    assert loop["tool_rounds_used"] == 0
    old_payload = handler.chat_requests[2][1]
    old_tools = [message for message in old_payload["messages"] if message["role"] == "tool"]
    assert old_tools
    retained_messages = handler.retained_payload["messages"]
    retained_tools = [message for message in retained_messages if message["role"] == "tool"]
    assert len(retained_tools) == len(old_tools) + 1
    for message in old_tools:
        assert retained_tools.count(message) == 1
    # 为什么要有它：同 Plan 续接要保留旧源码观察并恰好闭合一次原生补查请求，不能伪造批准或重复交换。
    upstream_results = [message for message in retained_tools
                        if message.get("tool_name") == PATCH_UPSTREAM_REQUEST_TOOL_NAME]
    assert len(upstream_results) == 1
    upstream_message = upstream_results[0]
    response_ref = first["factory_receipt"]["worker_turns"][-1]["response_ref"]
    response_bytes = Path(response_ref["path"]).read_bytes()
    assert _sha(response_bytes) == response_ref["sha256"]
    response = json.loads(response_bytes)
    prior_call, = response["tool_calls"]
    assert prior_call["name"] == PATCH_UPSTREAM_REQUEST_TOOL_NAME
    native_call = retained_messages[retained_messages.index(upstream_message) - 1]
    assert native_call["role"] == "assistant"
    assert native_call["tool_calls"] == response["provider_state"]["tool_calls"]
    assert native_call["content"] == response["provider_state"]["content"]
    upstream_result = json.loads(upstream_message["content"])
    assert upstream_result == {"status": "completed", "decision": "retain_current_plan",
                               "new_material": False, "approval_inherited": False}
    assert any(message.get("content") == handler.latest_failed_raw
               for message in handler.retained_payload["messages"] if message["role"] == "assistant")
    assessments = [value for _, value in _message_jsons(handler.retained_payload)
                   if value.get("message_type") == "patch_same_plan_assessment"]
    assert len(assessments) == 1
    assert _retain({})["rationale"] in json.dumps(assessments[0])
    new_feedback_bytes = len(_patch_agent_context_json([
        {"role": "user", "content": assessments[0]}]).encode("utf-8"))
    # 为什么要有它：从实际 wire 结果和已绑定 call_id 重建新增观察，检验补查回复也计入原有字节预算。
    upstream_result_bytes = len(_patch_agent_context_json([{
        "call_id": prior_call["call_id"], "name": prior_call["name"], "output": upstream_result,
    }]).encode("utf-8"))
    assert loop["recovery_observation_bytes"] == new_feedback_bytes + upstream_result_bytes
    assert loop["total_observation_bytes"] == 0
    for kind in ("patch_repair_context", "patch_behavior_correction"):
        assert sum(value.get("message_type") == kind for _, value in _message_jsons(handler.retained_payload)) == 1
    if repeat_upstream:
        assert result["patch_proposal_artifact"] is None
        assert loop["termination"]["code"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    assert _source_hashes(case.inputs.workspace) == before
