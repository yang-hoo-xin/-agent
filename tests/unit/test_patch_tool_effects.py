"""Tool effects describe the configured owner without changing model authority."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.libs.llm.agent_turn import AgentMessage, AgentToolCall
from src.mod_agent.fresh_planning_continuation import (
    _bind_patch_attempt_recorder,
    _patch_continuation_state,
    preflight_patch_continuation,
)
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_SOURCE_INSPECTION_TOOL_NAME,
    PATCH_UPSTREAM_REQUEST_TOOL_NAME,
    PatchAgentLoopPolicy,
    run_patch_agent_loop,
)
from src.mod_agent.workflow import build_graph
from tests.unit.test_model_planning_selection import _Client, _selector
from tests.unit.test_patch_agent_loop import (
    _final_format,
    _fixture,
    _response,
    _ScriptedClient,
    _tool_call,
)
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle
from tests.unit.test_patch_repair_continuation import _repair_case
from tests.unit.test_patch_upstream_replanning import _RequestUpstream


def _run(tmp_path, replies, *, effects=None):
    policy = PatchAgentLoopPolicy(require_source_inspection=False,
        finalize_after_first_observation=False, allow_upstream_request=True)
    _, source, _, inspector = _fixture(tmp_path, policy=policy)
    before = source.read_bytes()
    client = _ScriptedClient(replies)
    result = run_patch_agent_loop(client=client,
        initial_messages=(AgentMessage(role="user", content="Synthetic behavior needs verification."),),
        final_response_format=_final_format(), source_inspector=inspector, policy=policy,
        **({"upstream_effects": effects} if effects is not None else {}))
    assert source.read_bytes() == before
    return result, client, inspector


def _state(request):
    return next(message.content for message in reversed(request.messages)
        if isinstance(message.content, dict) and message.content.get("message_type") == "patch_agent_loop_state")


@pytest.mark.parametrize("effects", [
    None,
    {"evidence": "provider_unavailable_stop", "planning": "assess_then_stop"},
    {"evidence": "assess_and_continue", "planning": "assess_and_continue"},
])
def test_declared_owner_effects_keep_original_tool_arguments_and_direct_finish(tmp_path, effects):
    result, client, inspector = _run(tmp_path, [_response(turn=1, content='{"changes":[]}')], effects=effects)
    assert result.completed and result.tool_rounds_used == 0
    expected = effects or {"evidence": "record_and_stop", "planning": "record_and_stop"}
    request = client.requests[0]
    assert _state(request)["upstream_effects"] == expected
    tools = {tool.name: tool for tool in request.tools}
    assert set(tools) == {PATCH_SOURCE_INSPECTION_TOOL_NAME, PATCH_UPSTREAM_REQUEST_TOOL_NAME}
    assert tools[PATCH_SOURCE_INSPECTION_TOOL_NAME].parameters == {
        "type": "object", "additionalProperties": False, "required": ["binding_id"],
        "properties": {"binding_id": {"type": "string", "enum": list(inspector.available_read_binding_ids)}},
    }
    assert tools[PATCH_UPSTREAM_REQUEST_TOOL_NAME].parameters == {
        "type": "object", "additionalProperties": False,
        "required": ["required_owner", "reason", "source_refs"], "properties": {
            "required_owner": {"type": "string", "enum": ["evidence", "planning"]},
            "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
            "source_refs": {"type": "array", "minItems": 1, "uniqueItems": True,
                "items": {"type": "string", "enum": [f"binding://{binding}"
                    for binding in inspector.available_read_binding_ids]}},
        },
    }


def test_known_ref_can_be_read_without_requesting_reassessment(tmp_path):
    result, client, _ = _run(tmp_path, [
        _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
        _response(turn=2, content='{"changes":[]}'),
    ], effects={"evidence": "assess_then_stop", "planning": "assess_then_stop"})
    assert result.completed and result.tool_rounds_used == 1
    assert len(client.requests) == 2
    assert result.observation_trace[0]["binding_id"] == "edit_binding_001"
    assert result.observation_trace[0]["admitted_to_model"] is True
    assert "upstream_request" not in result.termination


@pytest.mark.parametrize("reason", [
    "The current coverage interpretation conflicts with the failed preservation check for this known method.",
    "这个位置可以读取，但原覆盖判断没有解释冷启动状态；需要重新判断需求与证据的关系。",
])
def test_same_known_ref_can_request_reassessment_with_free_form_semantic_reason(tmp_path, reason):
    arguments = {"required_owner": "evidence", "reason": reason,
        "source_refs": ["binding://edit_binding_001"]}
    result, client, _ = _run(tmp_path, [_response(turn=1, tool_calls=(AgentToolCall(
        call_id="semantic-review", name=PATCH_UPSTREAM_REQUEST_TOOL_NAME, arguments=deepcopy(arguments)),))],
        effects={"evidence": "assess_then_stop", "planning": "assess_then_stop"})
    assert result.termination["code"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    accepted = result.termination["upstream_request"]
    assert {key: accepted[key] for key in arguments} == arguments
    assert accepted["assessment_required"] is True
    assert result.tool_rounds_used == 0 and len(client.requests) == 1
    # The worker validates and records a request; this alone is not a Graph run,
    # a correct semantic judgment, a new binding, or permission to write.
    assert not result.completed and result.final_content is None


@pytest.mark.parametrize("requested_owner", ["planning", "evidence"])
def test_direct_graph_declares_plan_stop_and_missing_evidence_provider(tmp_path, requested_owner):
    inputs, request, _ = _repair_case(tmp_path)

    class RecordingClient(_RequestUpstream):
        def __init__(self):
            super().__init__(requested_owner)
            self.requests = []

        def complete_turn(self, request):
            self.requests.append(request)
            return super().complete_turn(request)

    client = RecordingClient()
    adapter = _adapter(inputs, client, _BehaviorOracle(tmp_path / "unused-verifier"))
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(require_source_inspection=False,
        allow_upstream_request=True, enable_supporting_reads=True, finalize_after_first_observation=False)
    events = []
    _bind_patch_attempt_recorder(adapter, events.append)
    admitted = preflight_patch_continuation(request)
    state = _patch_continuation_state(run_id="direct-graph-effects", request_id="direct-graph-effects",
        request=request, admitted=admitted)
    planning_client = _Client()
    graph = build_graph(inputs.store, use_default_proposal_git_binding=False,
        patch_continuation_mode=request, enable_patch_upstream_replanning=True,
        patch_change_factory=adapter, evidence_pack_factory=None,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
        patch_continuation_max_model_calls=5, patch_continuation_attempt_recorder=events.append,
        planning_target_selection_factory=_selector(inputs, planning_client))
    result = graph.invoke(state)
    assert len(client.requests) == 1
    assert _state(client.requests[0])["upstream_effects"] == {
        "evidence": "provider_unavailable_stop", "planning": "assess_then_stop",
    }
    if requested_owner == "planning":
        assert not result["blockers"] and len(planning_client.calls) == 1
        assert result["current_stage"] == "implementation_plan"
    else:
        assert not planning_client.calls
        assert result["blockers"][0]["code"] == "PATCH_UPSTREAM_EVIDENCE_PROVIDER_REQUIRED"
