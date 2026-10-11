"""Diagnosis inputs retain facts without granting tool or Patch authority."""
from copy import deepcopy
import json

import pytest

from src.libs.llm.agent_turn import (
    AgentMessage, AgentResponseFormat, AgentToolDefinition, AgentToolExchange,
    AgentToolResult, AgentTurnRequest,
)
from src.mod_agent.proposal.repair_diagnosis import build_repair_diagnosis_request


def _contract():
    return {
        "request": "Change the requested behavior while preserving existing behavior.",
        "constraints": ["Do not change tests or widen the edit scope."],
        "acceptance_criteria": ["Preserve empty-input behavior."],
        "target_behavior": ["Follow all declared requirements."],
        "required_change_units": [{"edit_binding_id": "edit_1", "preserve": "unrelated members"}],
        "required_validation_by_binding": {"edit_1": ["public cases"]},
        "runtime_verification_plan": {"required": False},
        "edit_binding_contexts": {"edit_1": {"source_excerpt": "historical B0\n原文", "source_hash": "original-hash"}},
        "required_output_schema": {"type": "object", "required": ["changes"]},
        "future_contract_field": {"preservation": ["keep this obligation"]},
    }


def _feedback():
    return {
        "observations": [
            {"case": "first", "expected": {"state": [1, 2]}, "observed": {"state": [1, 3]}},
            {"case": "second", "status": "passed", "observed": "unchanged"},
        ],
        "working_code_view": {"code_sha256": "current-hash", "files": [
            {"complete": True, "hunks": [{"text": "current checked code\n受测正文"}]}]},
        "report_sha256": "report-hash", "unknown_fact": {"keep": [False, None]},
    }


@pytest.mark.parametrize("encoded", [False, True])
def test_native_contract_current_candidate_and_every_observation_are_preserved(encoded):
    contract, feedback = _contract(), _feedback()
    content = json.dumps(contract, ensure_ascii=False) if encoded else contract
    request = AgentTurnRequest(messages=(AgentMessage("system", "Return a Patch."), AgentMessage("user", content)))
    previous = ' {"changes": [{"after_text": "current\\n受测正文"}]}\n'
    result = build_repair_diagnosis_request(request, previous_response=previous, feedback=feedback)
    payload = result.messages[1].content
    assert payload["task_contract"] == contract
    assert payload["previous_response"] == previous
    assert payload["validator_feedback"] == feedback
    assert payload["original_context"] == [{"role": "system", "content": "Return a Patch."}]
    assert list(payload).index("previous_response") < list(payload).index("task_contract")
    assert "historical baseline B0, not the current candidate" in result.messages[0].content


@pytest.mark.parametrize("content", ["Original free-form request.", {"custom": ["keep", None]}, '["original", "context"]'])
def test_nonstandard_context_is_retained_without_fabricating_a_contract(content):
    request = AgentTurnRequest(messages=(AgentMessage("user", content), AgentMessage("assistant", "earlier response")))
    result = build_repair_diagnosis_request(request, previous_response="current", feedback={"observations": []})
    payload = result.messages[1].content
    assert "task_contract" not in payload
    assert payload["context_representation"] == "unrecognized_or_ambiguous_original_context"
    assert payload["original_context"] == [
        {"role": "user", "content": content}, {"role": "assistant", "content": "earlier response"}]
    assert payload["validator_feedback"] == {"observations": []}


def test_ambiguous_contracts_are_preserved_without_selecting_one():
    first, second = _contract(), _contract()
    second["request"] = "Different recorded contract."
    request = AgentTurnRequest(messages=(AgentMessage("user", first), AgentMessage("user", second)))
    payload = build_repair_diagnosis_request(request, previous_response="current", feedback={}).messages[1].content
    assert "task_contract" not in payload
    assert [row["content"] for row in payload["original_context"]] == [first, second]


def test_native_context_retains_user_clarifications_but_not_stale_model_speculation():
    request = AgentTurnRequest(messages=(
        AgentMessage("user", _contract()), AgentMessage("assistant", "old speculative candidate"),
        AgentMessage("user", {"message_type": "patch_behavior_correction", "validator_feedback": {"old": True}}),
        AgentMessage("user", "Also preserve the documented special case."),
        AgentMessage("user", {"message_type": "future_user_context", "requirement": "retain"}),
        AgentMessage("user", {"message_type": ["nonstandard"], "fact": "keep"}),
    ))
    payload = build_repair_diagnosis_request(request, previous_response="current", feedback=_feedback()).messages[1].content
    assert payload["original_context"] == [
        {"role": "user", "content": "Also preserve the documented special case."},
        {"role": "user", "content": {"message_type": "future_user_context", "requirement": "retain"}},
        {"role": "user", "content": {"message_type": ["nonstandard"], "fact": "keep"}},
    ]


def test_tools_become_observed_data_and_diagnosis_has_no_patch_or_tool_authority():
    old = AgentToolResult("old-call", "inspect_plan_binding_source", {"excerpt": "B0 source", "truncated": False})
    latest = AgentToolResult("latest-call", "other_read", {"fact": "actual supplied result"})
    request = AgentTurnRequest(
        messages=(AgentMessage("user", _contract()),),
        tools=(AgentToolDefinition("source", "read", {"type": "object"}),), tool_choice="required",
        parallel_tool_calls=True, response_format=AgentResponseFormat("patch", "write Patch", {"required": ["changes"]}),
        tool_results=(latest,), tool_result_insert_index=1, provider_state={"pending": "call"},
        historical_tool_exchanges=(AgentToolExchange((old,), {"old": "provider state"}, 1),), temperature=0.25,
    )
    result = build_repair_diagnosis_request(request, previous_response="current", feedback=_feedback())
    assert result.messages[1].content["observed_tool_results"] == [
        {"call_id": "old-call", "name": "inspect_plan_binding_source", "output": old.output},
        {"call_id": "latest-call", "name": "other_read", "output": latest.output},
    ]
    assert result.tools == result.tool_results == result.historical_tool_exchanges == ()
    assert result.tool_choice == "none" and not result.parallel_tool_calls
    assert result.response_format is None and result.provider_state is None and result.tool_result_insert_index is None
    assert result.temperature == request.temperature
    assert "not a Patch, replacement code, or tool calls" in result.messages[0].content
    assert "unverified hypothesis" in result.messages[0].content
    assert "permission to change source, tests, scope, or approvals" in result.messages[0].content


def test_request_and_feedback_are_not_mutated_or_aliased():
    request = AgentTurnRequest(messages=(AgentMessage("user", _contract()),), tool_results=(
        AgentToolResult("read", "source", {"lines": ["original"]}),))
    feedback = _feedback()
    original_request, original_feedback = deepcopy(request), deepcopy(feedback)
    result = build_repair_diagnosis_request(request, previous_response="current", feedback=feedback)
    assert request == original_request and feedback == original_feedback
    payload = result.messages[1].content
    payload["task_contract"]["constraints"].append("changed")
    payload["validator_feedback"]["observations"].clear()
    payload["observed_tool_results"][0]["output"]["lines"].append("changed")
    assert request == original_request and feedback == original_feedback


def test_nonstandard_context_is_not_aliased():
    request = AgentTurnRequest(messages=(AgentMessage("user", {"custom": ["original"]}),))
    result = build_repair_diagnosis_request(request, previous_response="current", feedback={})
    result.messages[1].content["original_context"][0]["content"]["custom"].append("changed")
    assert request.messages[0].content == {"custom": ["original"]}
