"""Lossless repeated-source excerpts preserve each binding and actual read count."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.libs.llm.agent_turn import AgentMessage, AgentToolResult, AgentTurnRequest
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_SOURCE_INSPECTION_TOOL_NAME,
    PatchAgentLoopError,
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    _encode_source_excerpt,
    expand_patch_source_observations,
    run_patch_agent_loop,
)
from tests.unit.test_patch_agent_loop import (
    _api_fixture,
    _final_format,
    _response,
    _run,
    _ScriptedClient,
    _tool_call,
)


def _canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _inspector(tmp_path, *, enabled=True, byte_limit=32768):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    # 005's relevant shape: three config bindings repeat one complete file,
    # while the two larger-file views overlap but are not identical.
    config = workspace / "Configuration.cs"
    spread = workspace / "Behavior.cs"
    config.write_text("".join(f"// config line {i:03d} " + "x" * 160 + "\n" for i in range(40)), encoding="utf-8")
    spread.write_text("".join(f"// source line {i:03d} " + "y" * 70 + "\n" for i in range(160)), encoding="utf-8")
    refs = ((spread, 40), (config, 10), (config, 20), (config, 30), (spread, 125), (config, 5))
    bindings = [{"binding_id": f"edit_binding_{i:03d}", "canonical_target_path": path.name,
        "source_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "target_span": {"start_line": line, "end_line": line}}
        for i, (path, line) in enumerate(refs, 1)]
    plan = {"binding_registry": {"edit_bindings": bindings, "supporting_bindings": []},
        "proposed_changes": [{"change_id": f"change_{i:03d}", "edit_binding_id": binding["binding_id"]}
            for i, binding in enumerate(bindings, 1)]}
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False,
        allow_batched_reads=True, deduplicate_source_excerpts=enabled, max_tool_rounds=6,
        max_observation_bytes=byte_limit)
    return PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan, policy=policy)


def _batch_client():
    return _ScriptedClient([
        _response(turn=1, tool_calls=tuple(_tool_call(f"edit_binding_{i:03d}", turn=i) for i in range(1, 6))),
        _response(turn=2, content='{"changes":[]}'),
    ])


def test_005_repeated_complete_file_shape_exceeds_old_budget_but_exact_refs_fit(tmp_path):
    legacy = _inspector(tmp_path / "legacy", enabled=False)
    rejected = _run(_batch_client(), legacy)
    assert rejected.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    inspector = _inspector(tmp_path / "references")
    client = _batch_client()
    result = _run(client, inspector)
    assert result.completed and result.tool_rounds_used == 5 and result.model_turns_used == 2
    payloads = [item.output for item in client.requests[1].tool_results]
    expected = [inspector.inspect(binding_id=f"edit_binding_{i:03d}", observation_id=f"patch-observation-{i:03d}").model_view()
        for i in range(1, 6)]
    assert list(expand_patch_source_observations(payloads)) == expected
    assert payloads[0] == expected[0] and payloads[1] == expected[1] and payloads[4] == expected[4]
    for index in (2, 3):
        assert "excerpt" not in payloads[index]
        assert payloads[index]["excerpt_ref"] == {"observation_id": payloads[1]["observation_id"],
            "observation_sha256": payloads[1]["observation_sha256"],
            "excerpt_sha256": hashlib.sha256(payloads[1]["excerpt"].encode()).hexdigest()}
        assert payloads[index]["target_span"] == expected[index]["target_span"]
        assert payloads[index]["observation_sha256"] == expected[index]["observation_sha256"]
    encoded_bytes = sum(len(_canonical_bytes(item)) for item in payloads)
    expanded_bytes = sum(len(_canonical_bytes(item)) for item in expected)
    assert encoded_bytes < inspector.policy.max_observation_bytes < expanded_bytes
    assert result.total_observation_bytes == encoded_bytes
    for trace, encoded, full in zip(result.observation_trace, payloads, expected):
        assert trace["encoded_payload_sha256"] == hashlib.sha256(_canonical_bytes(encoded)).hexdigest()
        assert trace["encoded_payload_bytes"] == len(_canonical_bytes(encoded))
        assert trace["expanded_payload_bytes"] == trace["model_payload_bytes"] == len(_canonical_bytes(full))
        assert trace["admitted_to_model"] is True and trace["consumed_in_model_turn"] == 2


def test_same_batch_not_sent_is_not_recorded_as_consumed_by_model(tmp_path):
    inspector = _inspector(tmp_path, byte_limit=20000)
    client = _batch_client()
    result = _run(client, inspector)
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    assert len(client.requests) == 1
    assert any(item["payload_admitted"] for item in result.observation_trace)
    assert all(item["admitted_to_model"] is False for item in result.observation_trace)


def test_response_with_invalid_new_action_still_received_prior_observation(tmp_path):
    inspector = _inspector(tmp_path)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_002", turn=1),)),
        _response(turn=2, tool_calls=(_tool_call("edit_binding_003", turn=2),
            _tool_call("edit_binding_004", turn=3, name="unregistered_write"))),
    ])
    result = _run(client, inspector)
    assert result.status == "blocked" and result.model_turns_used == 2
    assert result.observation_trace[0]["admitted_to_model"] is True
    assert result.observation_trace[0]["consumed_in_model_turn"] == 2
    assert client.requests[1].tool_results[0].output["excerpt"]


def test_behavior_resume_can_reference_full_excerpt_in_actual_prior_tool_history(tmp_path):
    inspector = _inspector(tmp_path)
    first_client = _ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_002", turn=1),)),
        _response(turn=2, content='{"changes":[]}'),
    ])
    first = _run(first_client, inspector)
    request = replace(first.final_request, messages=(*first.final_request.messages,
        AgentMessage(role="assistant", content=first.final_content),
        AgentMessage(role="user", content={"observed": "test failure", "expected": "preserved behavior"})))
    second_client = _ScriptedClient([
        _response(turn=3, tool_calls=(_tool_call("edit_binding_003", turn=3),)),
        _response(turn=4, content='{"changes":[]}'),
    ])
    second = run_patch_agent_loop(client=second_client, initial_messages=request.messages, resume_request=request,
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=first.model_turns_used, consumed_tool_rounds=first.tool_rounds_used,
        consumed_observation_bytes=first.total_observation_bytes)
    assert second.completed and second.tool_rounds_used == 1
    final = second_client.requests[1]
    prior = final.historical_tool_exchanges[0].tool_results[0].output
    current = final.tool_results[0].output
    assert current["excerpt_ref"]["observation_id"] == prior["observation_id"]
    assert expand_patch_source_observations([prior, current])[1] == inspector.inspect(
        binding_id="edit_binding_003", observation_id="patch-observation-002").model_view()
    assert second.total_observation_bytes == len(_canonical_bytes(current))


@pytest.mark.parametrize("field,value", [
    ("source_snapshot_sha256", "a" * 64), ("source_hash", "b" * 64),
    ("excerpt_span", {"start_line": 2, "end_line": 41}), ("excerpt", "different source bytes\n" * 100),
])
def test_source_identity_span_or_bytes_difference_does_not_deduplicate(tmp_path, field, value):
    inspector = _inspector(tmp_path)
    first = inspector.inspect(binding_id="edit_binding_002", observation_id="observation-1")
    next_observation = inspector.inspect(binding_id="edit_binding_003", observation_id="observation-2")
    changed = replace(next_observation, **{field: value})
    anchors = {}
    assert "excerpt_ref" not in _encode_source_excerpt(first, anchors)
    assert "excerpt_ref" not in _encode_source_excerpt(changed, anchors)


@pytest.mark.parametrize("mutation", ["missing", "anchor_hash", "excerpt_hash", "span", "own_hash", "null"])
def test_decoder_rejects_missing_or_tampered_excerpt_identity(tmp_path, mutation):
    inspector = _inspector(tmp_path)
    anchors = {}
    original = _encode_source_excerpt(inspector.inspect(binding_id="edit_binding_002", observation_id="one"), anchors)
    repeated = _encode_source_excerpt(inspector.inspect(binding_id="edit_binding_003", observation_id="two"), anchors)
    if mutation == "missing":
        repeated["excerpt_ref"]["observation_id"] = "absent"
    elif mutation == "anchor_hash":
        repeated["excerpt_ref"]["observation_sha256"] = "a" * 64
    elif mutation == "excerpt_hash":
        repeated["excerpt_ref"]["excerpt_sha256"] = "a" * 64
    elif mutation == "span":
        repeated["excerpt_span"]["start_line"] = 2
    elif mutation == "own_hash":
        repeated["observation_sha256"] = "a" * 64
    else:
        repeated["excerpt_ref"] = None
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_EXCERPT_REFERENCE_INVALID"):
        expand_patch_source_observations([original, repeated])


@pytest.mark.parametrize("mutation", ["dangling", "self_consistent_wrong_code"])
def test_resume_rejects_invalid_history_before_model_call(tmp_path, mutation):
    inspector = _inspector(tmp_path)
    anchors = {}
    original = _encode_source_excerpt(inspector.inspect(binding_id="edit_binding_002", observation_id="one"), anchors)
    repeated = _encode_source_excerpt(inspector.inspect(binding_id="edit_binding_003", observation_id="two"), anchors)
    if mutation == "dangling":
        payload = repeated
    else:
        payload = deepcopy(original)
        payload["excerpt"] += "// invented source\n"
        payload["observation_sha256"] = hashlib.sha256(_canonical_bytes(
            {key: value for key, value in payload.items() if key != "observation_sha256"})).hexdigest()
    request = AgentTurnRequest(messages=(AgentMessage(role="user", content="Repair."),),
        tool_results=(AgentToolResult(call_id="old-call", name=PATCH_SOURCE_INSPECTION_TOOL_NAME, output=payload),))
    client = _ScriptedClient([])
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_EXCERPT_REFERENCE_INVALID"):
        run_patch_agent_loop(client=client, initial_messages=request.messages, resume_request=request,
            final_response_format=_final_format(), source_inspector=inspector,
            consumed_model_turns=2, consumed_tool_rounds=1)
    assert not client.requests


def test_registered_api_evidence_is_never_replaced_with_excerpt_reference(tmp_path):
    _, _, inspector, _ = _api_fixture(tmp_path)
    first = inspector.inspect(binding_id="support_api_1", observation_id="one")
    second = inspector.inspect(binding_id="support_api_1", observation_id="two")
    anchors = {}
    payloads = [_encode_source_excerpt(first, anchors), _encode_source_excerpt(second, anchors)]
    assert payloads == [first.model_view(), second.model_view()]
    assert list(expand_patch_source_observations(payloads)) == payloads
    assert not anchors


def test_false_policy_preserves_old_full_tool_payload_and_description(tmp_path):
    inspector = _inspector(tmp_path, enabled=False, byte_limit=65536)
    client = _batch_client()
    result = _run(client, inspector)
    assert result.completed
    expected = [inspector.inspect(binding_id=f"edit_binding_{i:03d}", observation_id=f"patch-observation-{i:03d}").model_view()
        for i in range(1, 6)]
    assert [item.output for item in client.requests[1].tool_results] == expected
    assert "excerpt_ref" not in client.requests[0].tools[0].description
    assert all("encoded_payload_bytes" not in entry for entry in result.observation_trace)
