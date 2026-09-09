"""Recoverable static submission checks stay in the original worker budget."""
from dataclasses import replace

import pytest

from src.libs.llm.agent_turn import AgentMessage
from src.mod_agent.proposal.code_generator import (
    PatchGenerationError,
    PatchSubmissionValidationError,
)
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, run_patch_agent_loop
from tests.unit.test_patch_agent_loop import _final_format, _fixture, _response, _ScriptedClient


def _run(tmp_path, replies, validator, *, policy=None, reserve=0):
    policy = policy or PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False)
    _, source, _, inspector = _fixture(tmp_path, policy=policy)
    original = source.read_bytes()
    client = _ScriptedClient(replies)
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage("system", "Return a bound Patch."),),
        final_response_format=_final_format(), source_inspector=inspector, policy=policy,
        reserve_model_turns=reserve, submission_validator=validator)
    assert source.read_bytes() == original
    return result, client


def _reject(_):
    raise PatchSubmissionValidationError("Unified diff introduces trailing whitespace on 3 added line(s).",
        diagnostics={"failure_classification": "added_diff_trailing_whitespace", "added_trailing_whitespace_count": 3})


def test_static_rejection_returns_current_output_and_measured_diagnostic(tmp_path):
    calls = []
    def validate(response):
        calls.append(response)
        if len(calls) == 1:
            _reject(response)
    first, last = '{"changes":[]}', '{"changes": []}'
    result, client = _run(tmp_path, [_response(turn=1, content=first), _response(turn=2, content=last)], validate)
    assert result.completed and result.final_content == last
    assert len(client.requests) == len(calls) == 2
    feedback = next(m.content for m in client.requests[1].messages if isinstance(m.content, dict)
        and m.content.get("message_type") == "patch_submission_feedback")
    assert feedback["code_validation_performed"] is True
    assert feedback["diagnostics"]["added_trailing_whitespace_count"] == 3
    assert any(m.role == "assistant" and m.content == first for m in client.requests[1].messages)
    assert result.submission_trace[0]["feedback_in_request"]
    assert result.submission_trace[0]["followup_response_observed"]
    assert result.total_observation_bytes == result.submission_trace[0]["feedback_payload_bytes"]


@pytest.mark.parametrize("error", [PatchGenerationError("Bound source identity changed"), RuntimeError("Environment failed")])
def test_untyped_errors_do_not_receive_retry_credit(tmp_path, error):
    def validate(_):
        raise error
    result, client = _run(tmp_path, [_response(turn=1, content='{"changes":[]}')], validate)
    assert not result.completed and len(client.requests) == 1
    assert result.termination["code"] == type(error).__name__
    assert result.submission_trace[0]["failure_class"] == type(error).__name__
    assert not result.submission_trace[0]["feedback_queued"]


def test_repeated_static_rejection_stops_with_budget_remaining(tmp_path):
    result, client = _run(tmp_path, [_response(turn=1, content='{"changes":[]}'),
        _response(turn=2, content='{"changes":[]}')], _reject)
    assert not result.completed and len(client.requests) == 2
    assert result.termination["code"] == "PATCH_AGENT_REPEATED_INVALID_SUBMISSION"


def test_complete_static_failure_can_spend_existing_recovery_reserve(tmp_path):
    policy = PatchAgentLoopPolicy(max_total_model_turns=2, require_source_inspection=False)
    def validate(response):
        if response.content == '{"changes":[]}':
            _reject(response)
    result, client = _run(tmp_path, [_response(turn=1, content='{"changes":[]}'),
        _response(turn=2, content='{"changes": []}')], validate, policy=policy, reserve=1)
    assert result.completed and len(client.requests) == 2
    assert result.submission_trace[0]["released_recovery_reservation"]["model_turns"] == 1


def test_static_recovery_still_stops_at_original_total_model_limit(tmp_path):
    policy = PatchAgentLoopPolicy(max_total_model_turns=2, require_source_inspection=False)
    result, client = _run(tmp_path, [_response(turn=1, content='{"changes":[]}'),
        _response(turn=2, content='{"changes": []}')], _reject, policy=policy, reserve=1)
    assert len(client.requests) == 2 and not result.completed
    assert result.termination["code"] == "PATCH_AGENT_SUBMISSION_CORRECTION_BUDGET_EXHAUSTED"


def test_static_feedback_exhausts_bytes_without_next_model_send(tmp_path):
    policy = PatchAgentLoopPolicy(max_observation_bytes=1, require_source_inspection=False)
    result, client = _run(tmp_path, [_response(turn=1, content='{"changes":[]}')], _reject, policy=policy)
    assert len(client.requests) == 1
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"


def test_incomplete_response_never_reaches_static_submission_validator(tmp_path):
    def validate(_):
        pytest.fail("Incomplete output is not an admitted submission")
    result, _ = _run(tmp_path, [replace(_response(turn=1, content='{"changes":[]}'), stop_reason="length")], validate)
    assert result.termination["code"] == "PATCH_AGENT_RESPONSE_INCOMPLETE"


@pytest.mark.parametrize("failure", ["no_op", "header", "whitespace"])
def test_real_prepared_submission_uses_recovery_reserve_without_editing_source(tmp_path, failure):
    import json

    from src.libs.llm import ChatResponse
    from src.libs.llm.agent_turn import AgentResponseFormat
    from src.mod_agent.execution.patch_apply import (
        materialize_exact_text_patch,
        validate_materialized_patch_submission,
    )
    from src.mod_agent.proposal.code_generator import LLMExactPatchGenerator
    from src.mod_agent.proposal.patch_agent_loop import PlanBoundSourceInspector
    from tests.unit.test_repair_submission_validation import _inputs, _payload

    before = "using System;\nclass Subject { public int Apply() => 1; }\n"
    good = before.replace("=> 1", "=> 2")
    bad = {"no_op": before, "header": good.removeprefix("using System;\n"),
           "whitespace": good.replace("=> 2; }", "=> 2; }  ")}[failure]
    (tmp_path / "Subject.cs").write_text(before, encoding="utf-8", newline="")
    inputs = _inputs(before)
    plan = {"binding_registry": inputs["binding_registry"], "proposed_changes": inputs["required_change_units"]}
    generator = LLMExactPatchGenerator(None)
    prepared = generator.prepare_native_contract(**inputs)
    policy = PatchAgentLoopPolicy(max_total_model_turns=3, require_source_inspection=False)
    inspector = PlanBoundSourceInspector(workspace_root=tmp_path, implementation_plan=plan, policy=policy)
    client = _ScriptedClient([_response(turn=1, content=json.dumps(_payload(bad))),
                             _response(turn=2, content=json.dumps(_payload(good)))])

    def check(response):
        generated = generator.materialize_prepared_native(prepared, ChatResponse(content=response.content, model=response.model))
        materialized = materialize_exact_text_patch(workspace_root=tmp_path, diff_intent=generated.changes, implementation_plan=plan)
        validate_materialized_patch_submission(materialized)

    result = run_patch_agent_loop(client=client, initial_messages=tuple(AgentMessage(m.role, m.content) for m in prepared.messages),
        final_response_format=AgentResponseFormat(name="patch", description="Bound output", schema=prepared.response_schema),
        source_inspector=inspector, policy=policy, reserve_model_turns=2, submission_validator=check)
    assert result.completed and len(client.requests) == 2
    assert result.submission_trace[0]["released_recovery_reservation"]["model_turns"] == 2
    assert result.submission_trace[1]["status"] == "accepted"
    assert (tmp_path / "Subject.cs").read_bytes() == before.encode()
