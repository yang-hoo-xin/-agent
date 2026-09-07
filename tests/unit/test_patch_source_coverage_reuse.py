"""Whole-window reuse preserves the 007 investigation shape and shared budgets."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.libs.llm.agent_turn import AgentMessage
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopError,
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    _encode_source_excerpt,
    estimate_patch_source_reads,
    expand_patch_source_observations,
    run_patch_agent_loop,
)
from tests.unit.test_patch_agent_loop import (
    _final_format,
    _response,
    _run,
    _ScriptedClient,
    _tool_call,
)


def _coverage_inspector(tmp_path, *, enabled=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, count in (("Spread.cs", 179), ("Configuration.cs", 80), ("Loader.cs", 56), ("FirstShot.cs", 76)):
        path = tmp_path / name
        path.write_text("".join(f"// {name} line {line:03d}\n" for line in range(1, count + 1)), encoding="utf-8")
        files[name] = path
    # Full windows: 51-179, 1-80 three times, 1-124; then 1-80,
    # 96-179, 103-179, Loader 1-56, FirstShot 1-76.
    targets = (("Spread.cs", 115, 145), ("Configuration.cs", 50, 78),
        ("Configuration.cs", 35, 48), ("Configuration.cs", 1, 21), ("Spread.cs", 53, 60),
        ("Configuration.cs", 23, 27), ("Spread.cs", 160, 165), ("Spread.cs", 167, 167),
        ("Loader.cs", 1, 20), ("FirstShot.cs", 35, 52))
    bindings = [{"binding_id": f"edit_binding_{i:03d}", "canonical_target_path": name,
        "source_hash": hashlib.sha256(files[name].read_bytes()).hexdigest(),
        "target_span": {"start_line": start, "end_line": end}}
        for i, (name, start, end) in enumerate(targets, 1)]
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False,
        allow_batched_reads=True, deduplicate_source_excerpts=True,
        reuse_covered_source_observations=enabled, max_tool_rounds=6)
    plan = {"binding_registry": {"edit_bindings": bindings, "supporting_bindings": []},
        "proposed_changes": [{"change_id": f"change_{i:03d}", "edit_binding_id": item["binding_id"]}
            for i, item in enumerate(bindings, 1)]}
    return PlanBoundSourceInspector(workspace_root=tmp_path, implementation_plan=plan, policy=policy)


def test_007_shape_reuses_complete_visible_windows_in_initial_and_failure_rounds(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in range(1, 6))),
        _response(turn=2, content='{"changes":[]}'),
        _response(turn=3, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in range(6, 11))),
        _response(turn=4, content='{"changes":[]}'),
    ])
    first = run_patch_agent_loop(client=client, initial_messages=(AgentMessage(role="user", content="Preserve behavior."),),
        final_response_format=_final_format(), source_inspector=inspector, reserve_model_turns=2, reserve_tool_reads=1)
    assert first.completed and first.tool_rounds_used == 3
    assert first.to_dict()["dispatched_binding_reads"] == 5
    assert first.to_dict()["reused_source_observations"] == 2
    request = replace(first.final_request, messages=(*first.final_request.messages,
        AgentMessage(role="assistant", content=first.final_content),
        AgentMessage(role="user", content={"failure": "Executed original behavior check failed."})))
    second = run_patch_agent_loop(client=client, initial_messages=request.messages, resume_request=request,
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=2, consumed_tool_rounds=3, consumed_observation_bytes=first.total_observation_bytes)
    assert second.completed and second.tool_rounds_used == 2
    assert second.to_dict()["dispatched_binding_reads"] == 5
    assert second.to_dict()["reused_source_observations"] == 3
    assert second.to_dict()["read_accounting_version"] == "new_source_window_v2"
    assert [row["read_cost"] for row in second.observation_trace] == [0, 0, 0, 1, 1]
    final = client.requests[-1]
    payloads = [result.output for exchange in final.historical_tool_exchanges for result in exchange.tool_results]
    payloads.extend(result.output for result in final.tool_results)
    expanded = expand_patch_source_observations(payloads)
    assert len({row["observation_id"] for row in expanded}) == 10
    for i, row in enumerate(expanded, 1):
        assert row == inspector.inspect(binding_id=f"edit_binding_{i:03d}", observation_id=row["observation_id"]).model_view()
    assert all(row["admitted_to_model"] for row in second.observation_trace)
    assert first.total_observation_bytes + second.total_observation_bytes <= 32768


def test_legacy_mode_still_counts_each_dispatched_binding(tmp_path):
    inspector = _coverage_inspector(tmp_path, enabled=False)
    result = _run(_ScriptedClient([
        _response(turn=1, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in range(1, 6))),
        _response(turn=2, content='{"changes":[]}'),
    ]), inspector)
    assert result.completed and result.tool_rounds_used == 5


def test_same_binding_provider_id_can_reuse_but_repeating_without_new_information_stops(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    call = _tool_call("edit_binding_002", turn=1)
    client = _ScriptedClient([_response(turn=i, tool_calls=(call,)) for i in range(1, 4)])
    result = _run(client, inspector)
    assert result.termination["code"] == "PATCH_AGENT_REPEATED_TOOL_CALL"
    assert result.model_turns_used == 3 and result.tool_rounds_used == 1
    assert result.to_dict()["dispatched_binding_reads"] == 2
    assert [row["read_cost"] for row in result.observation_trace] == [1, 0]
    assert result.observation_trace[0]["observation_id"] != result.observation_trace[1]["observation_id"]
    assert result.to_dict()["turn_progress_trace"][1]["no_new_source_information"] is True
    assert len(client.requests[-1].historical_tool_exchanges) == 1
    assert client.requests[-1].tool_results[0].output["excerpt_ref"]


@pytest.mark.parametrize("changed_code", [False, True])
def test_new_failure_segment_can_recheck_the_same_reference_without_resetting_budget(tmp_path, changed_code):
    """A new checked-output context permits review, even when no new source is needed."""
    inspector = _coverage_inspector(tmp_path)
    prior_output = json.dumps({"changes": [{"after_text": "void Run() { First(); }"}]})
    checked_output = (json.dumps({"changes": [{"after_text": "void Run() { Second(); }"}]})
                      if changed_code else prior_output)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_002", turn=1),)),
        _response(turn=2, tool_calls=(_tool_call("edit_binding_002", turn=2),)),
        _response(turn=3, content=checked_output),
        _response(turn=4, tool_calls=(_tool_call("edit_binding_002", turn=4),)),
        _response(turn=5, content='{"changes":[]}'),
    ])
    initial = (
        AgentMessage(role="user", content="Preserve the original behavior on B0."),
        AgentMessage(role="assistant", content=prior_output),
        AgentMessage(role="user", content={"failure": "prior verification result"}),
    )
    first = run_patch_agent_loop(client=client, initial_messages=initial,
        final_response_format=_final_format(), source_inspector=inspector, reserve_model_turns=2)
    assert first.completed and first.model_turns_used == 3
    assert [row["read_cost"] for row in first.observation_trace] == [1, 0]
    feedback = {"status": "behavior_failed", "observations": [
        {"check_id": "new_check", "expected": True, "observed": False}]}
    revision_messages = LocalOllamaInitialPatchAdapter._revision_messages(
        checked_output, feedback, message_type="patch_behavior_correction",
        visible_messages=first.final_request.messages)
    resumed = replace(first.final_request,
        messages=(*first.final_request.messages, *revision_messages))
    second = run_patch_agent_loop(client=client, initial_messages=resumed.messages, resume_request=resumed,
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=first.model_turns_used, consumed_tool_rounds=first.tool_rounds_used,
        consumed_observation_bytes=first.total_observation_bytes)
    assert second.completed and second.model_turns_used == 2
    assert second.tool_rounds_used == 0 and second.dispatched_binding_reads == 1
    assert second.reused_source_observations == 1 and second.total_observation_bytes > 0
    assert second.observation_trace[0]["admitted_to_model"] is True
    assert second.observation_trace[0]["consumed_in_model_turn"] == 5
    assert client.requests[-1].tool_results[0].output["excerpt_ref"]
    assert len(client.requests) == 5
    assert first.tool_rounds_used + second.tool_rounds_used == 1
    assert any(message.role == "assistant" and message.content == checked_output
               for message in client.requests[-1].messages)
    assert next(message.content for message in client.requests[-1].messages
                if isinstance(message.content, dict)
                and message.content.get("message_type") == "patch_behavior_correction")["validator_feedback"] == feedback
    state = next(message.content for message in client.requests[-1].messages
                 if isinstance(message.content, dict)
                 and message.content.get("message_type") == "patch_agent_loop_state")
    assert isinstance(state["source_read_semantics"], str) and state["source_read_semantics"]
    assert state["source_snapshot_sha256"] == inspector.source_snapshot_sha256
    final_request = client.requests[-1]
    wire_results = [result.output for exchange in final_request.historical_tool_exchanges
                    for result in exchange.tool_results]
    wire_results.extend(result.output for result in final_request.tool_results)
    restored = expand_patch_source_observations(wire_results)
    assert restored[-1]["excerpt"] == (tmp_path / "Configuration.cs").read_bytes().decode("utf-8")


def test_new_window_budget_exhaustion_keeps_reference_tool_available(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    inspector.policy = replace(inspector.policy, max_tool_rounds=1)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_002", turn=1),)),
        _response(turn=2, tool_calls=(_tool_call("edit_binding_003", turn=2),)),
        _response(turn=3, content='{"changes":[]}'),
    ])
    result = _run(client, inspector)
    assert result.completed and result.tool_rounds_used == 1 and result.model_turns_used == 3
    assert "edit_binding_003" in client.requests[1].tools[0].parameters["properties"]["binding_id"]["enum"]
    assert "edit_binding_009" not in client.requests[1].tools[0].parameters["properties"]["binding_id"]["enum"]
    assert result.observation_trace[1]["read_cost"] == 0


def test_subset_requires_whole_window_identity_and_visible_anchor(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    anchors = {}
    full = _encode_source_excerpt(inspector.inspect(binding_id="edit_binding_001", observation_id="one"), anchors,
        reuse_covered=True)
    requested = inspector.inspect(binding_id="edit_binding_007", observation_id="two")
    subset = _encode_source_excerpt(requested, anchors, reuse_covered=True)
    assert subset["excerpt_ref"]["source_excerpt_span"] == {"start_line": 51, "end_line": 179}
    assert expand_patch_source_observations([full, subset])[1] == requested.model_view()
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_EXCERPT_REFERENCE_INVALID"):
        expand_patch_source_observations([subset])
    wrong_source = replace(requested, source_identity_sha256="a" * 64)
    assert "excerpt_ref" not in _encode_source_excerpt(wrong_source, deepcopy(anchors), reuse_covered=True)
    # The edit target 53-60 is visible, but its required window 1-124 is not.
    overlap = inspector.inspect(binding_id="edit_binding_005", observation_id="three")
    assert "excerpt_ref" not in _encode_source_excerpt(overlap, anchors, reuse_covered=True)


@pytest.mark.parametrize("mutation", ["source_identity", "source_span", "own_span", "source_hash"])
def test_tampered_subset_reference_is_rejected(tmp_path, mutation):
    inspector = _coverage_inspector(tmp_path)
    anchors = {}
    full = _encode_source_excerpt(inspector.inspect(binding_id="edit_binding_001", observation_id="one"), anchors,
        reuse_covered=True)
    subset = _encode_source_excerpt(inspector.inspect(binding_id="edit_binding_007", observation_id="two"), anchors,
        reuse_covered=True)
    if mutation == "source_identity":
        subset["source_identity_sha256"] = "a" * 64
    elif mutation == "source_span":
        subset["excerpt_ref"]["source_excerpt_span"]["start_line"] = 50
    elif mutation == "own_span":
        subset["excerpt_span"]["start_line"] = 50
    else:
        subset["source_hash"] = "a" * 64
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_EXCERPT_REFERENCE_INVALID"):
        expand_patch_source_observations([full, subset])


def test_resume_cost_floor_uses_new_windows_and_planning_helper_matches_actual_encoding(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    first = _run(_ScriptedClient([
        _response(turn=1, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in range(1, 6))),
        _response(turn=2, content='{"changes":[]}'),
    ]), inspector)
    planned = estimate_patch_source_reads(source_inspector=inspector, prior_request=first.final_request,
        binding_ids=[f"edit_binding_{i:03d}" for i in range(6, 11)])
    assert [row["read_cost"] for row in planned] == [0, 0, 0, 1, 1]
    client = _ScriptedClient([])
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_LOOP_BUDGET_INVALID"):
        run_patch_agent_loop(client=client, initial_messages=first.final_request.messages, resume_request=first.final_request,
            final_response_format=_final_format(), source_inspector=inspector,
            consumed_model_turns=2, consumed_tool_rounds=2, consumed_observation_bytes=first.total_observation_bytes)
    assert not client.requests


def test_visible_reference_still_costs_bytes_and_snapshot_drift_blocks(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    first = _run(_ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_002", turn=1),)),
        _response(turn=2, content='{"changes":[]}'),
    ]), inspector)
    client = _ScriptedClient([_response(turn=3, tool_calls=(_tool_call("edit_binding_003", turn=3),))])
    result = run_patch_agent_loop(client=client, initial_messages=first.final_request.messages, resume_request=first.final_request,
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=2, consumed_tool_rounds=1, consumed_observation_bytes=32767)
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    assert result.tool_rounds_used == 0 and result.total_observation_bytes > 1
    (tmp_path / "Configuration.cs").write_text("changed", encoding="utf-8")
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"):
        estimate_patch_source_reads(source_inspector=inspector, prior_request=first.final_request,
            binding_ids=["edit_binding_003"])


def test_over_budget_batch_does_not_claim_coverage_or_pollute_reselection(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    inspector.policy = replace(inspector.policy, max_tool_rounds=2)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in range(1, 6))),
        _response(turn=2, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in (2, 3, 4))),
        _response(turn=3, content='{"changes":[]}'),
    ])
    result = _run(client, inspector)
    assert result.completed and result.tool_rounds_used == 1
    assert result.to_dict()["dispatched_binding_reads"] == 3
    assert all(row["turn_index"] == 2 for row in result.observation_trace)
    feedback = client.requests[1].tool_results
    assert all(row.output["requested_new_source_windows"] == 3 for row in feedback)
    assert all(row.output["remaining_read_count"] == 2 for row in feedback)
    assert client.requests[2].tool_results[0].output["excerpt"]


def test_source_call_id_cannot_be_reused_for_a_different_binding(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_002", turn=1),)),
        _response(turn=2, tool_calls=(_tool_call("edit_binding_003", turn=1),)),
    ])
    result = _run(client, inspector)
    assert result.termination["code"] == "PATCH_AGENT_TOOL_CALL_ID_REUSED"
    assert result.tool_rounds_used == 1
