"""Offline tool roundtrips: production native encoding, no real model or Mod."""
import json
import hashlib
from pathlib import Path
from copy import deepcopy
from dataclasses import replace

import pytest

from src.libs.llm.agent_turn import AgentMessage, OllamaChatAgentAdapter
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopError, _plan_source_reads, expand_patch_source_observations,
    run_patch_agent_loop,
)
from tests.unit.test_patch_agent_loop import _final_format, _response, _ScriptedClient, _tool_call
from tests.unit.test_patch_source_coverage_reuse import _coverage_inspector


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("This is an offline tool serialization test.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


def _native_client(wires):
    def sender(url, payload, headers):
        wires.append(deepcopy(payload))
        message = ({"role": "assistant", "tool_calls": [{"function": {
            "name": "inspect_plan_binding_source", "arguments": {"binding_id": f"edit_binding_{i:03d}"}}}
            for i in range(1, 6)]} if len(wires) == 1 else
            {"role": "assistant", "content": '{"changes":[]}'})
        return {"model": "offline-roundtrip", "message": message, "done": True,
                "prompt_eval_count": 100, "eval_count": 1}
    return OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="offline-roundtrip",
        max_output_tokens=4096, context_window=49152, request_sender=sender)


def test_partial_overlap_reaches_native_second_request_and_validation_callback(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    wires, validations = [], []
    result = run_patch_agent_loop(client=_native_client(wires),
        initial_messages=(AgentMessage("user", "Use the bound source."),), final_response_format=_final_format(),
        source_inspector=inspector, submission_validator=lambda response: validations.append(response.content))
    assert result.completed and len(wires) == 2 and validations == ['{"changes":[]}']
    results = [json.loads(row["content"]) for row in wires[1]["messages"] if row["role"] == "tool"]
    assert len(results) == 5
    assert [row["binding_id"] for row in results] == [f"edit_binding_{i:03d}" for i in range(1, 6)]
    assert "excerpt_ref" in results[2] and "excerpt_ref" in results[3]
    assert "excerpt_parts" in results[4] and "excerpt" not in results[4]
    expanded = expand_patch_source_observations(results)
    assert all(row == inspector.inspect(binding_id=row["binding_id"], observation_id=row["observation_id"]).model_view()
        for row in expanded)
    assert result.tool_rounds_used == 3 and result.reused_source_observations == 2
    assert all(row["admitted_to_model"] for row in result.observation_trace)
    assert result.total_observation_bytes == sum(len(json.dumps(row, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()) for row in results)


@pytest.mark.parametrize("damage", ["missing_anchor", "wrong_hash", "wrong_span", "wrong_prefix", "wrong_source"])
def test_partial_overlap_refuses_missing_or_tampered_source(damage, tmp_path):
    inspector = _coverage_inspector(tmp_path)
    rows = _plan_source_reads(inspector, ["edit_binding_001", "edit_binding_005"], {}, 0)
    first, last = [deepcopy(row[1]) for row in rows]
    assert "excerpt_parts" in last
    ref = next(part for part in last["excerpt_parts"] if isinstance(part, dict))
    if damage == "missing_anchor":
        ref["observation_id"] = "not-visible"
    elif damage == "wrong_hash":
        ref["excerpt_sha256"] = "a" * 64
    elif damage == "wrong_span":
        ref["source_excerpt_span"]["start_line"] += 1
    elif damage == "wrong_prefix":
        last["excerpt_parts"][0] += "changed\n"
    else:
        last["source_hash"] = "b" * 64
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_EXCERPT_REFERENCE_INVALID"):
        expand_patch_source_observations([first, last])


@pytest.mark.parametrize("budget", [2500, 1001])
def test_insufficient_batch_answers_every_call_or_stops_when_even_feedback_does_not_fit(budget, tmp_path):
    inspector = _coverage_inspector(tmp_path)
    inspector.policy = replace(inspector.policy, max_observation_bytes=budget)
    wires = []
    result = run_patch_agent_loop(client=_native_client(wires),
        initial_messages=(AgentMessage("user", "Preserve current input."),), final_response_format=_final_format(),
        source_inspector=inspector, consumed_observation_bytes=1000)
    assert result.tool_rounds_used == 0
    assert len(result.tool_call_trace) == 5 and not any(row["dispatch_started"] for row in result.tool_call_trace)
    assert 1000 + result.total_observation_bytes <= budget
    if budget == 2500:
        assert result.completed and len(wires) == 2
        outputs = [json.loads(row["content"]) for row in wires[1]["messages"] if row["role"] == "tool"]
        assert len(outputs) == 5
        assert all(row["error_code"] == "PATCH_AGENT_TOOL_RESULT_BUDGET_EXCEEDED" for row in outputs)
        assert "tools" not in wires[1]
    else:
        assert len(wires) == 1 and result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
        assert not any(row["feedback_queued"] for row in result.tool_call_trace)


def test_old_overdrawn_ledger_cannot_be_refunded_by_new_encoding(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    client = _ScriptedClient([])
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage("user", "Retained context."),),
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=1, consumed_tool_rounds=3, consumed_observation_bytes=34351)
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    assert client.requests == []
    assert result.model_turns_used == result.tool_rounds_used == result.total_observation_bytes == 0


def test_visible_partial_recipe_reuse_does_not_charge_a_new_source_window(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in (1, 5))),
        _response(turn=2, tool_calls=(_tool_call("edit_binding_005", turn=6),)),
        _response(turn=3, content='{"changes":[]}'),
    ])
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage("user", "Use current source."),),
        final_response_format=_final_format(), source_inspector=inspector)
    assert result.completed and result.tool_rounds_used == 2
    assert [row["read_cost"] for row in result.observation_trace] == [1, 1, 0]
    request = result.final_request
    payloads = [row.output for exchange in request.historical_tool_exchanges for row in exchange.tool_results]
    payloads += [row.output for row in request.tool_results]
    assert len(expand_patch_source_observations(payloads)) == 3


def test_resume_cannot_drop_prior_observation_bytes(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    first = run_patch_agent_loop(client=_native_client([]),
        initial_messages=(AgentMessage("user", "Use current source."),), final_response_format=_final_format(),
        source_inspector=inspector)
    client = _ScriptedClient([])
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_LOOP_BUDGET_INVALID"):
        run_patch_agent_loop(client=client, initial_messages=first.final_request.messages,
            resume_request=first.final_request, final_response_format=_final_format(), source_inspector=inspector,
            consumed_model_turns=2, consumed_tool_rounds=3, consumed_observation_bytes=first.total_observation_bytes - 1)
    assert not client.requests


def test_resume_preserves_recorded_reads_before_retained_window_inventory(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    first = run_patch_agent_loop(client=_native_client([]),
        initial_messages=(AgentMessage("user", "Use current source."),), final_response_format=_final_format(),
        source_inspector=inspector, consumed_tool_rounds=1)
    assert first.completed and first.tool_rounds_used == 3
    assert first.final_request.messages[-1].content["budget_state"]["tool_rounds_used"] == 4
    client = _ScriptedClient([])
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_LOOP_BUDGET_INVALID"):
        run_patch_agent_loop(client=client, initial_messages=first.final_request.messages,
            resume_request=first.final_request, final_response_format=_final_format(), source_inspector=inspector,
            consumed_model_turns=2, consumed_tool_rounds=3, consumed_observation_bytes=first.total_observation_bytes)
    assert not client.requests
    resumed = run_patch_agent_loop(client=_ScriptedClient([_response(turn=3, content='{"changes":[]}')]),
        initial_messages=first.final_request.messages, resume_request=first.final_request,
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=2, consumed_tool_rounds=4, consumed_observation_bytes=first.total_observation_bytes)
    assert resumed.completed and resumed.tool_rounds_used == 0


def test_source_drift_still_stops_before_transport(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    (tmp_path / "Spread.cs").write_text("changed source", encoding="utf-8")
    wires = []
    result = run_patch_agent_loop(client=_native_client(wires),
        initial_messages=(AgentMessage("user", "Use current source."),), final_response_format=_final_format(),
        source_inspector=inspector)
    assert not wires and result.termination["code"] == "PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"


def test_native_roundtrip_reaches_shared_worker_materialization_and_bound_verifier(tmp_path):
    """Owned marker fixture validates the original worker seam, not Mod quality."""
    from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
    from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
    from tests.unit.test_fresh_planning_continuation import _inputs, _patch_request, _PatchAgentTurnClient, _source_hashes
    from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle

    inputs = _inputs(tmp_path)
    request = _patch_request(inputs)
    before = _source_hashes(inputs.workspace)
    fixture = _PatchAgentTurnClient()

    class Client:
        provider, model = fixture.provider, fixture.model

        def __init__(self):
            self.requests, self.wires, self.outputs = [], [], []
            self.native = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model=self.model,
                max_output_tokens=1024, context_window=49152, request_sender=self.send)

        def send(self, url, payload, headers):
            self.wires.append(deepcopy(payload))
            response = fixture.complete_turn(self.requests[-1])
            self.outputs.append(response.content)
            return {"model": self.model, "done": True, "prompt_eval_count": 100, "eval_count": 20,
                "message": {"role": "assistant", "content": response.content,
                    "tool_calls": [{"function": {"name": call.name, "arguments": call.arguments}}
                        for call in response.tool_calls]}}

        def complete_turn(self, current):
            self.requests.append(current)
            return self.native.complete_turn(current)

    client = Client()
    verifier = _BehaviorOracle(tmp_path / "declared-verification-fixture")
    adapter = _adapter(inputs, client, verifier)
    adapter.enable_recovery_loop = True
    adapter.profile = replace(adapter.profile, context_window=49152)
    original_identity = adapter.identity_reader
    adapter.identity_reader = lambda *args: {**original_identity(*args), "details": {"context_length": 49152}}
    adapter.patch_agent_loop_policy = replace(adapter.patch_agent_loop_policy,
        max_total_model_turns=5, require_source_inspection=False, finalize_after_first_observation=False,
        allow_batched_reads=True, deduplicate_source_excerpts=True, reuse_covered_source_observations=True)
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.status == "terminal", (result.reason, result.first_failure)
    assert len(client.wires) == 2 and any(row["role"] == "tool" for row in client.wires[1]["messages"])
    assert len(verifier.contexts) == 1
    context = verifier.contexts[0]
    final_content = client.outputs[-1]
    assert Path(context["model_response"]["path"]).read_text(encoding="utf-8") == final_content
    assert context["model_response"]["output_sha256"] == hashlib.sha256(final_content.encode("utf-8")).hexdigest()
    assert context["generated_changes"] and verifier.reports[0]["status"] == "passed"
    assert _source_hashes(inputs.workspace) == before
    assert result.execution_counts["review"] == result.execution_counts["dry_run"] == 1
    assert all(result.execution_counts[key] == 0 for key in ("apply", "build", "runtime"))
