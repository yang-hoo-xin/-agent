"""Whole no-op code must not consume observation bytes as another full source copy."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from src.libs.llm import ChatResponse
from src.libs.llm.agent_turn import AgentMessage, AgentResponseFormat
from src.mod_agent.proposal.code_generator import (
    LLMExactPatchGenerator,
    PatchSubmissionValidationError,
)
from src.mod_agent.proposal.noop_submission_feedback import (
    noop_code_identity,
    project_whole_noop_response,
    whole_noop_facts,
)
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    run_patch_agent_loop,
)
from tests.unit.test_patch_agent_loop import _response, _ScriptedClient
from tests.unit.test_repair_submission_validation import _inputs, _payload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No-op feedback checks must not use a real model or network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


def _run(tmp_path, *, repeat=False):
    before = "\ufeffusing System;\nclass Subject { public int Apply() => 1; }\n" + "// unchanged source\n" * 320
    (tmp_path / "Subject.cs").write_text(before, encoding="utf-8", newline="")
    inputs = _inputs(before)
    plan = {"binding_registry": inputs["binding_registry"], "proposed_changes": inputs["required_change_units"]}
    generator = LLMExactPatchGenerator(None)
    prepared = generator.prepare_native_contract(**inputs)
    policy = PatchAgentLoopPolicy(max_total_model_turns=3, max_observation_bytes=4000, require_source_inspection=False)
    inspector = PlanBoundSourceInspector(workspace_root=tmp_path, implementation_plan=plan, policy=policy)
    first = _payload(before.removeprefix("\ufeff"))
    second = _payload(before.removeprefix("\ufeff") if repeat else before.replace("=> 1", "=> 2"))
    second["changes"][0]["rationale"] = "A different description, not evidence that code changed."
    client = _ScriptedClient([_response(turn=1, content=json.dumps(first)), _response(turn=2, content=json.dumps(second))])

    def validate(response):
        generator.materialize_prepared_native(prepared, ChatResponse(content=response.content, model=response.model))

    result = run_patch_agent_loop(client=client,
        initial_messages=tuple(AgentMessage(row.role, row.content) for row in prepared.messages),
        final_response_format=AgentResponseFormat(name="patch", description="Exact bound output", schema=prepared.response_schema),
        source_inspector=inspector, policy=policy, submission_validator=validate)
    assert (tmp_path / "Subject.cs").read_bytes() == before.encode()
    return result, client, first


def test_large_whole_noop_gets_small_factual_feedback_then_real_change(tmp_path):
    result, client, original = _run(tmp_path)
    assert result.completed
    assert len(client.requests) == 2
    assert result.total_observation_bytes < 4000
    feedback = next(row.content for row in client.requests[1].messages if isinstance(row.content, dict)
        and row.content.get("message_type") == "patch_submission_feedback")
    assert feedback["diagnostics"]["whole_submission_unchanged"] is True
    projection = next(json.loads(row.content) for row in client.requests[1].messages if row.role == "assistant")
    assert projection["input_only"] == "unchanged_submission_view"
    assert projection["changes"][0]["rationale"] == original["changes"][0]["rationale"]
    assert "after_text" not in projection["changes"][0]


def test_new_rationale_does_not_disguise_same_effective_noop_code(tmp_path):
    result, client, _ = _run(tmp_path, repeat=True)
    assert len(client.requests) == 2
    assert result.termination["code"] == "PATCH_AGENT_REPEATED_INVALID_SUBMISSION"
    assert result.submission_trace[0]["response_sha256"] != result.submission_trace[1]["response_sha256"]
    assert result.submission_trace[0]["effective_code_sha256"] == result.submission_trace[1]["effective_code_sha256"]


def test_mixed_noop_and_real_change_keeps_complete_original_feedback(tmp_path):
    before = "class Subject { public int Apply() => 1; }\n"
    other = before.replace("Subject", "Other")
    inputs = _inputs(before)
    extra = _inputs(other)
    extra["evidence_items"][0].update(evidence_id="ev_002", source_path="Other.cs", symbol="Other.Apply")
    extra["binding_registry"]["edit_bindings"][0].update(binding_id="edit_binding_002", evidence_id="ev_002",
        canonical_target_path="Other.cs", target_symbol="Other.Apply")
    extra["required_change_units"][0].update(change_id="change_002", edit_binding_id="edit_binding_002")
    inputs["evidence_items"].extend(extra["evidence_items"])
    inputs["binding_registry"]["edit_bindings"].extend(extra["binding_registry"]["edit_bindings"])
    inputs["required_change_units"].extend(extra["required_change_units"])
    (tmp_path / "Subject.cs").write_bytes(before.encode())
    (tmp_path / "Other.cs").write_bytes(other.encode())
    initial = {"changes": [_payload(before)["changes"][0],
        {**_payload(other.replace("=> 1", "=> 2"))["changes"][0], "edit_binding_id": "edit_binding_002"}]}
    revised = deepcopy(initial)
    revised["changes"][0]["after_text"] = before.replace("=> 1", "=> 2")
    generator = LLMExactPatchGenerator(None)
    prepared = generator.prepare_native_contract(**inputs)
    policy = PatchAgentLoopPolicy(require_source_inspection=False)
    inspector = PlanBoundSourceInspector(workspace_root=tmp_path, implementation_plan={
        "binding_registry": inputs["binding_registry"], "proposed_changes": inputs["required_change_units"]}, policy=policy)
    raw = json.dumps(initial)
    client = _ScriptedClient([_response(turn=1, content=raw), _response(turn=2, content=json.dumps(revised))])
    result = run_patch_agent_loop(client=client,
        initial_messages=tuple(AgentMessage(row.role, row.content) for row in prepared.messages),
        final_response_format=AgentResponseFormat(name="patch", description="Bound native output", schema=prepared.response_schema),
        source_inspector=inspector, policy=policy, submission_validator=lambda response:
            generator.materialize_prepared_native(prepared, ChatResponse(content=response.content, model=response.model)))
    assert result.completed
    assert "effective_code_sha256" not in result.submission_trace[0]
    assert any(row.role == "assistant" and row.content == raw for row in client.requests[1].messages)


@pytest.mark.parametrize("damage", ["identity", "binding", "code", "scope", "classification"])
def test_noop_projection_requires_exact_validated_code_identity(damage):
    after = "original code"
    diagnostics = {"failure_classification": "native_after_text_not_replacement",
        **whole_noop_facts(({"edit_binding_id": "edit_binding_001", "patch": {"before_text": after, "after_text": after}},))}
    payload = _payload(after)
    if damage == "identity":
        diagnostics["effective_code_sha256"] = "0" * 64
    elif damage == "binding":
        payload["changes"][0]["edit_binding_id"] = "other_binding"
    elif damage == "code":
        payload["changes"][0]["after_text"] = "real changed code"
    elif damage == "scope":
        payload["changes"].append({**payload["changes"][0], "edit_binding_id": "another_binding"})
    else:
        diagnostics["failure_classification"] = "other_failure"
    assert project_whole_noop_response(json.dumps(payload), diagnostics) is None


def test_noop_facts_are_absent_for_any_real_change_and_error_remains_typed():
    changes = ({"edit_binding_id": "b", "patch": {"before_text": "before", "after_text": "after"}},)
    assert whole_noop_facts(changes) == {}
    assert noop_code_identity({}) is None
    generator = LLMExactPatchGenerator(None)
    before = "class Subject { public int Apply() => 1; }\n"
    prepared = generator.prepare_native_contract(**_inputs(before))
    with pytest.raises(PatchSubmissionValidationError) as caught:
        generator.materialize_prepared_native(prepared, ChatResponse(content=json.dumps(_payload(before)), model="controlled"))
    assert caught.value.diagnostics["whole_submission_unchanged"] is True
