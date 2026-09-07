"""Submission admission and format feedback use the original Patch loop budget."""
from dataclasses import replace

import pytest

from src.libs.llm.agent_turn import AgentMessage, AgentResponseFormat, AgentTurnProviderError
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopError,
    PatchAgentLoopPolicy,
    run_patch_agent_loop,
)
from tests.unit.test_patch_agent_loop import (
    _final_format,
    _fixture,
    _response,
    _ScriptedClient,
    _tool_call,
)


def _run(tmp_path, replies, *, policy=None, reserve=0, response_format=None):
    policy = policy or PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False)
    _, _, _, inspector = _fixture(tmp_path, policy=policy)
    client = _ScriptedClient(replies)
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage('system', 'Return the registered Patch object.'),),
        final_response_format=response_format or _final_format(), source_inspector=inspector, policy=policy,
        reserve_model_turns=reserve)
    return result, client


def test_complete_invalid_submission_receives_feedback_then_valid_submission_in_same_loop(tmp_path):
    raw = 'Explanation first.\n{"changes":[]}'
    good = '{"changes": []}'
    result, client = _run(tmp_path, [_response(turn=1, content=raw), _response(turn=2, content=good)])
    assert result.completed and result.final_content == good and len(client.requests) == 2
    request = client.requests[1]
    assert any(message.role == 'assistant' and message.content == raw for message in request.messages)
    feedback = next(message.content for message in request.messages if isinstance(message.content, dict)
        and message.content.get('message_type') == 'patch_submission_feedback')
    assert feedback['diagnostics']['failure_classification'] == 'malformed_structured_output'
    assert feedback['code_validation_performed'] is False
    assert request.response_format.schema == _final_format().schema
    assert request.tools and request.tool_choice == 'auto'
    assert result.submission_trace[0]['feedback_in_request'] is True
    assert result.submission_trace[0]['followup_response_observed'] is True
    assert result.submission_trace[0]['consumed_in_model_turn'] == 2
    assert result.turn_progress_trace[0]['submitted_patch'] is False
    assert result.turn_progress_trace[1]['submitted_patch'] is True
    assert result.total_observation_bytes == result.submission_trace[0]['feedback_payload_bytes']


def test_tool_with_explanatory_content_is_not_submitted_or_format_corrected(tmp_path):
    result, client = _run(tmp_path, [_response(turn=1, content='I will inspect the source.',
        tool_calls=(_tool_call('edit_binding_001', turn=1),)), _response(turn=2, content='{"changes":[]}')])
    assert result.completed and result.tool_rounds_used == 1 and len(client.requests) == 2
    assert len(result.submission_trace) == 1 and result.submission_trace[0]['status'] == 'accepted'
    assert not result.turn_progress_trace[0]['submitted_patch']


@pytest.mark.parametrize('stop', ['length', 'max_tokens', 'max_output_tokens', 'incomplete'])
def test_explicitly_incomplete_output_is_not_dispatched_or_repaired_as_format(tmp_path, stop):
    reply = replace(_response(turn=1, content='{"changes":[]}',
        tool_calls=(_tool_call('edit_binding_001', turn=1),)), stop_reason=stop)
    result, client = _run(tmp_path, [reply])
    assert not result.completed and result.termination['code'] == 'PATCH_AGENT_RESPONSE_INCOMPLETE'
    assert len(client.requests) == 1 and result.tool_rounds_used == 0 and not result.tool_call_trace
    assert result.submission_trace[0]['status'] == 'incomplete'


def test_identical_invalid_submission_stops_without_extra_credit(tmp_path):
    raw = 'No valid submission.'
    result, client = _run(tmp_path, [_response(turn=1, content=raw), _response(turn=2, content=raw)])
    assert not result.completed and len(client.requests) == 2
    assert result.termination['code'] == 'PATCH_AGENT_REPEATED_INVALID_SUBMISSION'
    assert result.final_content is None and len(result.submission_trace) == 2


def test_format_feedback_does_not_spend_reserved_behavior_turns(tmp_path):
    policy = PatchAgentLoopPolicy(max_total_model_turns=2, require_source_inspection=False)
    result, client = _run(tmp_path, [_response(turn=1, content='not JSON')], policy=policy, reserve=1)
    assert not result.completed and len(client.requests) == 1
    assert result.termination['code'] == 'PATCH_AGENT_SUBMISSION_CORRECTION_BUDGET_EXHAUSTED'
    assert result.submission_trace[0]['feedback_queued'] is False


def test_format_feedback_obeys_existing_observation_byte_budget(tmp_path):
    policy = PatchAgentLoopPolicy(max_observation_bytes=1, require_source_inspection=False)
    result, client = _run(tmp_path, [_response(turn=1, content='not JSON')], policy=policy)
    assert not result.completed and len(client.requests) == 1
    assert result.termination['code'] == 'PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED'
    assert result.total_observation_bytes == 0


def test_invalid_submission_contract_is_rejected_before_model_call(tmp_path):
    invalid = AgentResponseFormat(name='invalid', description='Invalid operator schema', schema={'type': 'unknown'})
    with pytest.raises(PatchAgentLoopError, match='PATCH_AGENT_SUBMISSION_CONTRACT_INVALID'):
        _run(tmp_path, [], response_format=invalid)


def test_provider_transport_failure_is_not_rephrased_as_format_feedback(tmp_path):
    policy = PatchAgentLoopPolicy(require_source_inspection=False)
    _, _, _, inspector = _fixture(tmp_path, policy=policy)
    def fail(_):
        raise AgentTurnProviderError('Unavailable transport')
    client = _ScriptedClient([], before_response=fail)
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage('system', 'Return JSON'),),
        final_response_format=_final_format(), source_inspector=inspector, policy=policy)
    assert not result.completed and result.termination['code'] == 'PATCH_AGENT_PROVIDER_TURN_FAILED'
    assert len(client.requests) == 1 and not result.submission_trace
