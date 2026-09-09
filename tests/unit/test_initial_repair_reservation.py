"""An admitted Repair consumes its current feedback without reserving it again."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from src.libs.llm.agent_turn import AgentMessage
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter, _patch_agent_context_json
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, run_patch_agent_loop
from tests.unit.test_patch_agent_loop import _final_format, _fixture, _response, _ScriptedClient


def _repair_message(byte_count):
    content = {"message_type": "patch_repair_context", "recorded_observation": ""}
    message = AgentMessage("user", content)
    overhead = len(_patch_agent_context_json([asdict(message)]).encode("utf-8"))
    content["recorded_observation"] = "x" * (byte_count - overhead)
    assert len(_patch_agent_context_json([asdict(message)]).encode("utf-8")) == byte_count
    return message


def _reservations(inspector, *, repair, consumed):
    worker = SimpleNamespace(
        enable_recovery_loop=True, behavior_evaluator=object(),
        _repair_context={"failure_source": "bound_test_observation"} if repair else None,
        _recovery_observation_bytes=consumed, patch_agent_loop_policy=inspector.policy,
        _receipt={}, _emit=lambda _: None,
    )
    return LocalOllamaInitialPatchAdapter._initial_recovery_reservations(worker, inspector), worker


@pytest.mark.parametrize("consumed", [26737, 32768])
def test_existing_repair_context_can_use_original_budget_for_first_request(tmp_path, consumed):
    policy = PatchAgentLoopPolicy(max_total_model_turns=5, max_tool_rounds=6,
        max_observation_bytes=32768, require_source_inspection=False,
        finalize_after_first_observation=False)
    _, source, _, inspector = _fixture(tmp_path, policy=policy)
    before = source.read_bytes()
    repair_message = _repair_message(consumed)
    reservation, _ = _reservations(inspector, repair=True, consumed=consumed)
    client = _ScriptedClient([_response(turn=1, content='{"changes":[]}')])
    result = run_patch_agent_loop(client=client,
        initial_messages=(AgentMessage("system", "Return the bounded revision."), repair_message),
        final_response_format=_final_format(), source_inspector=inspector, policy=policy,
        consumed_observation_bytes=consumed, **reservation)
    assert result.completed and len(client.requests) == 1
    assert client.requests[0].messages[1] == repair_message
    budget = client.requests[0].messages[-1].content["budget_state"]
    assert budget["observation_bytes_used"] == consumed
    assert budget["remaining_observation_bytes"] == 32768 - consumed
    assert budget["reserved_observation_bytes"] == 0
    assert result.total_observation_bytes == 0
    assert source.read_bytes() == before


def test_actual_over_budget_repair_still_stops_without_request(tmp_path):
    policy = PatchAgentLoopPolicy(max_observation_bytes=32768, require_source_inspection=False)
    _, _, _, inspector = _fixture(tmp_path, policy=policy)
    reservation, _ = _reservations(inspector, repair=True, consumed=32769)
    client = _ScriptedClient([])
    result = run_patch_agent_loop(client=client,
        initial_messages=(AgentMessage("system", "Return the bounded revision."), _repair_message(32769)),
        final_response_format=_final_format(), source_inspector=inspector, policy=policy,
        consumed_observation_bytes=32769, **reservation)
    assert not result.completed and not client.requests
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"


def test_fresh_generation_keeps_original_future_recovery_reservation(tmp_path):
    policy = PatchAgentLoopPolicy(max_total_model_turns=5, max_tool_rounds=6,
        max_observation_bytes=32768, require_source_inspection=False)
    _, _, _, inspector = _fixture(tmp_path, policy=policy)
    reservation, worker = _reservations(inspector, repair=False, consumed=0)
    assert reservation["reserve_model_turns"] == 2
    assert reservation["reserve_tool_reads"] == 1
    assert worker._receipt["recovery_reservation"]["feedback_allowance_bytes"] == 1024
    assert reservation["reserve_observation_bytes"] == (
        worker._receipt["recovery_reservation"]["maximum_registered_read_bytes"] + 1024)
