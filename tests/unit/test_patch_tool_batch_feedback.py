"""Recorded protocol errors are feedback, never partial tool or routing execution."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.libs.llm.agent_turn import AgentToolCall
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_patch_agent_loop import _fixture, _response, _run, _ScriptedClient, _tool_call


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Batch protocol replay must not use a model or network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


def _recorded_batch():
    path = Path(__file__).parents[1] / "fixtures/patch_multiple_upstream_response_20260926.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    calls = tuple(AgentToolCall(**row) for row in record["normalized_tool_calls"])
    return replace(_response(turn=1, tool_calls=calls),
        provider_state=record["raw_response"]["message"])


@pytest.mark.parametrize("allow_batched_reads", [False, True])
def test_recorded_two_upstream_requests_get_feedback_then_one_existing_route(tmp_path, allow_batched_reads):
    batch = _recorded_batch()
    assert [row.name for row in batch.tool_calls] == ["request_patch_upstream"] * 2
    assert len({row.call_id for row in batch.tool_calls}) == 2
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=allow_batched_reads, allow_upstream_request=True, require_source_inspection=False,
        finalize_after_first_observation=False, max_total_model_turns=3))
    client = _ScriptedClient([batch, _response(turn=2, tool_calls=batch.tool_calls[:1])])
    result = _run(client, inspector)
    assert len(client.requests) == 2
    assert result.termination["code"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    assert result.termination["upstream_request"]["required_owner"] == "planning"
    assert result.tool_rounds_used == 0 and not result.observation_trace
    feedback = client.requests[1].tool_results
    assert [row.call_id for row in feedback] == [row.call_id for row in batch.tool_calls]
    assert all(row.output["status"] == "not_executed" for row in feedback)
    assert all(row.output["error_code"] == "PATCH_AGENT_MULTIPLE_UPSTREAM_REQUESTS" for row in feedback)
    assert client.requests[1].provider_state == batch.provider_state
    assert all(row["dispatch_started"] is False for row in result.tool_call_trace)
    assert all(row["feedback_queued"] for row in result.tool_call_trace[:2])
    assert result.total_observation_bytes > 0


@pytest.mark.parametrize("kind", ["two_upstream", "mixed", "unknown"])
@pytest.mark.parametrize("reuse", [False, True])
def test_rejected_batch_does_not_satisfy_inspection_and_next_legal_read_uses_original_budget(tmp_path, kind, reuse):
    batch = _recorded_batch()
    expected = "PATCH_AGENT_MULTIPLE_UPSTREAM_REQUESTS"
    if kind != "two_upstream":
        second = batch.tool_calls[0] if kind == "mixed" else AgentToolCall(
            call_id="unregistered", name="unregistered_write", arguments={"path": "not-executed"})
        batch = _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=10), second))
        expected = "PATCH_AGENT_MIXED_TOOL_BATCH_FORBIDDEN" if kind == "mixed" else "PATCH_AGENT_UNKNOWN_TOOL"
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=True,
        finalize_after_first_observation=False, max_total_model_turns=3,
        deduplicate_source_excerpts=reuse, reuse_covered_source_observations=reuse))
    dispatched = []
    inspect = inspector.inspect

    def record_inspection(**kwargs):
        dispatched.append(kwargs)
        return inspect(**kwargs)

    inspector.inspect = record_inspection
    client = _ScriptedClient([batch,
        _response(turn=2, tool_calls=(_tool_call("edit_binding_001", turn=10),)),
        _response(turn=3, content='{"changes":[]}')])
    result = _run(client, inspector)
    assert result.completed and result.model_turns_used == 3
    assert result.tool_rounds_used == result.dispatched_binding_reads == 1
    assert len(dispatched) == len(result.observation_trace) == 1
    assert client.requests[1].tool_choice == "required"
    assert all(row.output["error_code"] == expected for row in client.requests[1].tool_results)
    assert all(row["read_cost"] == 0 for row in result.tool_call_trace[:2])
    assert all(row["upstream_request_registered"] is False for row in result.tool_call_trace[:2])
    assert result.turn_progress_trace[0]["dispatched_binding_reads"] == 0
    assert result.turn_progress_trace[0]["observation_bytes_added"] > 0
    assert result.tool_call_trace[2]["dispatch_started"] is True


def test_rejected_batch_cannot_fake_required_source_inspection(tmp_path):
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=True))
    result = _run(_ScriptedClient([_recorded_batch(), _response(turn=2, content='{"changes":[]}')]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_SOURCE_INSPECTION_REQUIRED"
    assert result.tool_rounds_used == 0 and not result.observation_trace


def test_repeated_protocol_error_ends_at_original_model_budget_without_effects(tmp_path):
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=False,
        max_total_model_turns=2))
    client = _ScriptedClient([_recorded_batch(), _recorded_batch()])
    result = _run(client, inspector)
    assert len(client.requests) == result.model_turns_used == 2
    assert result.termination["code"] == "PATCH_AGENT_MODEL_TURN_BUDGET_EXHAUSTED"
    assert result.tool_rounds_used == 0 and not result.observation_trace
    assert "upstream_request" not in result.termination
    assert all(row["dispatch_started"] is False for row in result.tool_call_trace)
    assert all(row["feedback_queued"] is False for row in result.tool_call_trace[-2:])
    assert result.total_observation_bytes == sum(row["feedback_payload_bytes"] for row in result.tool_call_trace)


def test_rejection_feedback_must_fit_remaining_observation_budget(tmp_path):
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=False,
        max_observation_bytes=1))
    client = _ScriptedClient([_recorded_batch()])
    result = _run(client, inspector)
    assert len(client.requests) == 1
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    assert result.total_observation_bytes == 0
    assert result.tool_rounds_used == 0
    assert all(row["feedback_queued"] is False for row in result.tool_call_trace)


@pytest.mark.parametrize("invalid_id", [None, ""])
def test_missing_id_stops_without_inventing_correlated_feedback(tmp_path, invalid_id):
    batch = _recorded_batch()
    batch = replace(batch, tool_calls=(replace(batch.tool_calls[0], call_id=invalid_id), batch.tool_calls[1]))
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=False))
    result = _run(_ScriptedClient([batch]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_TOOL_CALL_ID_INVALID"
    assert result.total_observation_bytes == result.tool_rounds_used == 0


def test_duplicate_id_in_batch_is_terminal_before_any_effect(tmp_path):
    batch = _recorded_batch()
    batch = replace(batch, tool_calls=(batch.tool_calls[0],
        replace(batch.tool_calls[1], call_id=batch.tool_calls[0].call_id)))
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=False))
    result = _run(_ScriptedClient([batch]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_TOOL_CALL_ID_REUSED"
    assert result.total_observation_bytes == result.tool_rounds_used == 0


@pytest.mark.parametrize("batch_size", [1, 2])
def test_executed_read_id_cannot_be_reused_to_request_upstream(tmp_path, batch_size):
    batch = _recorded_batch()
    upstream = replace(batch.tool_calls[0], call_id="call-001")
    calls = (upstream,) if batch_size == 1 else (upstream, batch.tool_calls[1])
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=True))
    result = _run(_ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
        _response(turn=2, tool_calls=calls)]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_TOOL_CALL_ID_REUSED"
    assert result.tool_rounds_used == 1
    assert "upstream_request" not in result.termination


def test_source_drift_after_batch_rejection_stops_before_next_model_turn(tmp_path):
    _, source, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=False))
    client = _ScriptedClient([_recorded_batch()], before_response=lambda _turn:
        source.write_text("changed source", encoding="utf-8"))
    result = _run(client, inspector)
    assert len(client.requests) == 1
    assert result.termination["code"] == "PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"
    assert result.tool_rounds_used == 0 and not result.observation_trace


def test_recorded_provider_history_serializes_both_rejections_before_next_turn(tmp_path):
    from src.libs.llm import OllamaChatAgentAdapter

    batch = _recorded_batch()
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=False))
    client = _ScriptedClient([batch, _response(turn=2, tool_calls=batch.tool_calls[:1])])
    _run(client, inspector)
    wire = []

    def send(_url, payload, _headers):
        wire.append(payload)
        return {"model": "qwen3-coder:30b", "message": {"content": '{}'}, "done": True}

    OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="qwen3-coder:30b",
        max_output_tokens=4096, request_sender=send).complete_turn(client.requests[1])
    messages = wire[0]["messages"]
    errors = [json.loads(row["content"]) for row in messages if row["role"] == "tool"]
    assert len(errors) == 2 and all(row["status"] == "not_executed" for row in errors)
    assistant = next(row for row in messages if row["role"] == "assistant")
    assert assistant["tool_calls"] == batch.provider_state["tool_calls"]
