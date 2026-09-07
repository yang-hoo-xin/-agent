"""Focused tests for the bounded Plan-bound Patch source inspection loop."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolCall,
    AgentTurnProviderError,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentUsage,
)
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_SOURCE_INSPECTION_TOOL_NAME,
    PatchAgentLoopError,
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    run_patch_agent_loop,
)


class _ScriptedClient:
    provider = "test_patch_agent"
    model = "test-patch-model"

    def __init__(
        self,
        responses: list[AgentTurnResponse],
        *,
        before_response: Callable[[int], None] | None = None,
    ) -> None:
        self.responses = list(responses)
        self.before_response = before_response
        self.requests = []

    def complete_turn(self, request):
        self.requests.append(request)
        if self.before_response is not None:
            self.before_response(len(self.requests))
        return self.responses.pop(0)


def _response(
    *,
    turn: int,
    content: str | None = None,
    tool_calls: tuple[AgentToolCall, ...] = (),
) -> AgentTurnResponse:
    return AgentTurnResponse(
        provider="test_patch_agent",
        model="test-patch-model",
        content=content,
        tool_calls=tool_calls,
        stop_reason="tool_calls" if tool_calls else "stop",
        request_id=f"request-{turn:03d}",
        usage=AgentUsage(input_tokens=turn * 10, output_tokens=turn),
        provider_state=(
            {"content": content, "tool_calls": [{"id": call.call_id} for call in tool_calls]}
            if tool_calls
            else None
        ),
    )


def _tool_call(
    binding_id: str,
    *,
    turn: int,
    name: str = PATCH_SOURCE_INSPECTION_TOOL_NAME,
    extra_arguments: dict[str, object] | None = None,
) -> AgentToolCall:
    return AgentToolCall(
        call_id=f"call-{turn:03d}",
        name=name,
        arguments={"binding_id": binding_id, **dict(extra_arguments or {})},
    )


def _final_format() -> AgentResponseFormat:
    return AgentResponseFormat(
        name="patch_response",
        description="One binding-only Patch response.",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["changes"],
            "properties": {"changes": {"type": "array"}},
        },
    )


def _fixture(
    tmp_path: Path,
    *,
    binding_count: int = 1,
    policy: PatchAgentLoopPolicy | None = None,
) -> tuple[Path, Path, dict[str, object], PlanBoundSourceInspector]:
    workspace = tmp_path / "workspace"
    source = workspace / "Mod" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "".join(f"line {index:03d}\n" for index in range(1, 221)),
        encoding="utf-8",
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    bindings = [
        {
            "binding_id": f"edit_binding_{index:03d}",
            "canonical_target_path": "Mod/Behavior.cs",
            "source_hash": source_hash,
            "target_span": {
                "start_line": 20 + index * 20,
                "end_line": 21 + index * 20,
            },
        }
        for index in range(1, binding_count + 1)
    ]
    plan: dict[str, object] = {
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "edit_bindings": bindings,
            "supporting_bindings": [],
        },
        "proposed_changes": [
            {
                "change_id": f"change_{index:03d}",
                "edit_binding_id": f"edit_binding_{index:03d}",
            }
            for index in range(1, binding_count + 1)
        ],
    }
    selected_policy = policy or PatchAgentLoopPolicy(
        finalize_after_first_observation=False
    )
    inspector = PlanBoundSourceInspector(
        workspace_root=workspace,
        implementation_plan=plan,
        policy=selected_policy,
    )
    return workspace, source, plan, inspector


def _run(client: _ScriptedClient, inspector: PlanBoundSourceInspector):
    return run_patch_agent_loop(
        client=client,
        initial_messages=(
            AgentMessage(role="system", content="Generate an exact Plan-bound Patch."),
            AgentMessage(role="user", content={"request": "Change the bound behavior."}),
        ),
        final_response_format=_final_format(),
        source_inspector=inspector,
    )


def test_policy_keeps_default_limits_and_real_context_default() -> None:
    policy = PatchAgentLoopPolicy()

    assert policy.max_tool_rounds == 3
    assert policy.max_total_model_turns == 5
    assert policy.max_observation_bytes == 32_768
    assert policy.context_radius_lines == 64
    assert policy.finalize_after_first_observation is True


def test_loop_keeps_provider_request_identity_in_usage_receipt(tmp_path: Path) -> None:
    from dataclasses import replace

    _, _, _, inspector = _fixture(tmp_path)
    diagnostic = {"request_identity": {"provider_body_sha256": "a" * 64}}
    first = replace(
        _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
        provider_diagnostic=diagnostic,
    )
    result = _run(_ScriptedClient([first, _response(turn=2, content='{"changes":[]}')]), inspector)
    assert result.completed
    assert result.usage_by_turn[0]["provider_diagnostic"] == diagnostic
    diagnostic["request_identity"]["provider_body_sha256"] = "changed"
    assert result.usage_by_turn[0]["provider_diagnostic"]["request_identity"]["provider_body_sha256"] == "a" * 64


def test_source_inspector_returns_ref_first_bounded_context_without_path(
    tmp_path: Path,
) -> None:
    policy = PatchAgentLoopPolicy(context_radius_lines=2)
    workspace, _, _, inspector = _fixture(tmp_path, policy=policy)

    observation = inspector.inspect(
        binding_id="edit_binding_001",
        observation_id="patch-observation-001",
    )
    model_view = observation.model_view()

    assert observation.source_ref == "binding://edit_binding_001"
    assert observation.target_span == {"start_line": 40, "end_line": 41}
    assert observation.excerpt_span == {"start_line": 38, "end_line": 43}
    assert observation.excerpt.splitlines()[0] == "line 038"
    assert observation.excerpt.splitlines()[-1] == "line 043"
    assert observation.truncated is True
    assert len(observation.payload_sha256) == 64
    assert observation.model_payload_bytes == len(
        json.dumps(
            model_view,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    serialized = json.dumps(model_view, ensure_ascii=False, sort_keys=True)
    assert str(workspace) not in serialized
    assert "canonical_target_path" not in serialized


def test_source_inspector_rejects_path_escape_and_plan_hash_mismatch(
    tmp_path: Path,
) -> None:
    workspace, _, plan, _ = _fixture(tmp_path)
    binding = plan["binding_registry"]["edit_bindings"][0]
    escaped = json.loads(json.dumps(plan))
    escaped["binding_registry"]["edit_bindings"][0]["canonical_target_path"] = (
        "../outside.cs"
    )
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_SOURCE_PATH_ESCAPE"):
        PlanBoundSourceInspector(
            workspace_root=workspace,
            implementation_plan=escaped,
            policy=PatchAgentLoopPolicy(),
        )

    mismatched = json.loads(json.dumps(plan))
    mismatched["binding_registry"]["edit_bindings"][0]["source_hash"] = "0" * 64
    assert binding["source_hash"] != "0" * 64
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_SOURCE_HASH_MISMATCH"):
        PlanBoundSourceInspector(
            workspace_root=workspace,
            implementation_plan=mismatched,
            policy=PatchAgentLoopPolicy(),
        )


def test_source_inspector_rejects_snapshot_drift_after_construction(
    tmp_path: Path,
) -> None:
    _, source, _, inspector = _fixture(tmp_path)
    source.write_text("changed after snapshot\n", encoding="utf-8")

    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"):
        inspector.inspect(
            binding_id="edit_binding_001",
            observation_id="patch-observation-001",
        )


def test_source_inspector_exposes_only_bindings_selected_by_plan(tmp_path: Path) -> None:
    workspace, _, plan, _ = _fixture(tmp_path, binding_count=2)
    plan["proposed_changes"] = [plan["proposed_changes"][0]]

    inspector = PlanBoundSourceInspector(
        workspace_root=workspace,
        implementation_plan=plan,
        policy=PatchAgentLoopPolicy(),
    )

    assert inspector.available_binding_ids == ("edit_binding_001",)
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_BINDING_UNKNOWN"):
        inspector.inspect(
            binding_id="edit_binding_002",
            observation_id="patch-observation-001",
        )


def test_loop_inspects_one_binding_then_records_final_termination(
    tmp_path: Path,
) -> None:
    _, _, _, inspector = _fixture(tmp_path)
    final_content = '{"changes":[]}'
    client = _ScriptedClient(
        [
            _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
            _response(turn=2, content=final_content),
        ]
    )

    result = _run(client, inspector)

    assert result.status == "completed"
    assert result.final_content == final_content
    assert result.model_turns_used == 2
    assert result.tool_rounds_used == 1
    assert len(result.usage_by_turn) == 2
    assert result.usage_by_turn[0]["usage"]["total_tokens"] == 11
    assert result.tool_call_trace == (
        {
            "turn_index": 1,
            "tool_call_id": "call-001",
            "tool": PATCH_SOURCE_INSPECTION_TOOL_NAME,
            "binding_id": "edit_binding_001",
            "arguments_sha256": result.tool_call_trace[0]["arguments_sha256"],
            "status": "accepted",
            "dispatch_started": True,
        },
    )
    assert len(result.observation_trace) == 1
    assert result.observation_trace[0]["observation_sha256"]
    assert result.observation_trace[0]["admitted_to_model"] is True
    assert result.termination == {
        "status": "completed",
        "code": "PATCH_AGENT_MODEL_FINISHED",
        "reason": "The model returned final Patch content.",
        "turn_index": 2,
    }

    first_request = client.requests[0]
    assert len(first_request.tools) == 1
    tool_schema = first_request.tools[0].parameters
    assert set(tool_schema["properties"]) == {"binding_id"}
    assert tool_schema["properties"]["binding_id"]["enum"] == [
        "edit_binding_001"
    ]
    assert first_request.parallel_tool_calls is False
    assert first_request.tool_choice == "required"
    second_request = client.requests[1]
    assert second_request.tools == ()
    assert second_request.tool_results[0].call_id == "call-001"
    assert second_request.tool_results[0].name == PATCH_SOURCE_INSPECTION_TOOL_NAME
    assert second_request.tool_results[0].output["source_ref"] == (
        "binding://edit_binding_001"
    )


def test_default_policy_forces_final_after_first_observation(
    tmp_path: Path,
) -> None:
    policy = PatchAgentLoopPolicy()
    _, _, _, inspector = _fixture(
        tmp_path,
        binding_count=2,
        policy=policy,
    )
    client = _ScriptedClient(
        [
            _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
            _response(turn=2, content='{"changes":[]}'),
        ]
    )

    result = _run(client, inspector)

    assert result.status == "completed"
    assert result.tool_rounds_used == 1
    assert client.requests[1].tools == ()
    assert client.requests[1].tool_choice == "none"
    assert client.requests[1].response_format == _final_format()


@pytest.mark.parametrize(
    ("second_call", "error_code"),
    [
        (
            _tool_call("edit_binding_001", turn=2),
            "PATCH_AGENT_REPEATED_TOOL_CALL",
        ),
        (
            _tool_call("edit_binding_002", turn=2, name="read_arbitrary_path"),
            "PATCH_AGENT_UNKNOWN_TOOL",
        ),
        (
            _tool_call(
                "edit_binding_002",
                turn=2,
                extra_arguments={"path": "Mod/Behavior.cs"},
            ),
            "PATCH_AGENT_TOOL_ARGUMENTS_INVALID",
        ),
    ],
)
def test_loop_rejects_repeated_unknown_or_path_bearing_tool_calls(
    tmp_path: Path,
    second_call: AgentToolCall,
    error_code: str,
) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=2)
    client = _ScriptedClient(
        [
            _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
            _response(turn=2, tool_calls=(second_call,)),
        ]
    )

    result = _run(client, inspector)

    assert result.status == "blocked"
    assert result.termination["code"] == error_code
    assert result.model_turns_used == 2
    assert result.tool_rounds_used == 1
    assert result.tool_call_trace[-1]["status"] == "rejected"
    assert result.tool_call_trace[-1]["error_code"] == error_code


def test_loop_rejects_unknown_binding_and_parallel_tool_calls(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=2)
    unknown = _ScriptedClient(
        [
            _response(
                turn=1,
                tool_calls=(_tool_call("edit_binding_999", turn=1),),
            )
        ]
    )

    unknown_result = _run(unknown, inspector)

    assert unknown_result.status == "blocked"
    assert unknown_result.termination["code"] == "PATCH_AGENT_BINDING_UNKNOWN"
    assert unknown_result.tool_rounds_used == 0

    parallel = _ScriptedClient(
        [
            _response(
                turn=1,
                tool_calls=(
                    _tool_call("edit_binding_001", turn=1),
                    _tool_call("edit_binding_002", turn=2),
                ),
            )
        ]
    )

    parallel_result = _run(parallel, inspector)

    assert parallel_result.status == "blocked"
    assert parallel_result.termination["code"] == (
        "PATCH_AGENT_PARALLEL_TOOL_CALLS_FORBIDDEN"
    )
    assert len(parallel_result.tool_call_trace) == 2
    assert all(
        item["status"] == "rejected" for item in parallel_result.tool_call_trace
    )


def test_loop_rejects_a_first_turn_final_without_source_inspection(
    tmp_path: Path,
) -> None:
    _, _, _, inspector = _fixture(tmp_path)
    client = _ScriptedClient([_response(turn=1, content='{"changes":[]}')])

    result = _run(client, inspector)

    assert client.requests[0].tool_choice == "required"
    assert result.status == "blocked"
    assert result.final_content is None
    assert result.termination["code"] == "PATCH_AGENT_SOURCE_INSPECTION_REQUIRED"


def test_loop_rejects_reused_provider_tool_call_id(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=2)
    reused_call_id = AgentToolCall(
        call_id="call-001",
        name=PATCH_SOURCE_INSPECTION_TOOL_NAME,
        arguments={"binding_id": "edit_binding_002"},
    )
    client = _ScriptedClient(
        [
            _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
            _response(turn=2, tool_calls=(reused_call_id,)),
        ]
    )

    result = _run(client, inspector)

    assert result.status == "blocked"
    assert result.termination["code"] == "PATCH_AGENT_TOOL_CALL_ID_REUSED"
    assert result.tool_rounds_used == 1
    assert result.tool_call_trace[-1]["status"] == "rejected"


def test_loop_stops_before_fourth_tool_execution(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=4)
    client = _ScriptedClient(
        [
            _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
            _response(turn=2, tool_calls=(_tool_call("edit_binding_002", turn=2),)),
            _response(turn=3, tool_calls=(_tool_call("edit_binding_003", turn=3),)),
            _response(turn=4, tool_calls=(_tool_call("edit_binding_004", turn=4),)),
        ]
    )

    result = _run(client, inspector)

    assert result.status == "blocked"
    assert result.termination["code"] == "PATCH_AGENT_TOOL_ROUND_BUDGET_EXHAUSTED"
    assert result.model_turns_used == 4
    assert result.tool_rounds_used == 3
    assert len(result.observation_trace) == 3
    assert client.requests[1].tools[0].parameters["properties"]["binding_id"][
        "enum"
    ] == ["edit_binding_002", "edit_binding_003", "edit_binding_004"]
    assert client.requests[2].tools[0].parameters["properties"]["binding_id"][
        "enum"
    ] == ["edit_binding_003", "edit_binding_004"]
    assert client.requests[3].tools == ()
    assert client.requests[3].tool_choice == "none"
    assert client.requests[3].response_format == _final_format()


def test_loop_stops_when_total_observation_bytes_would_be_exceeded(
    tmp_path: Path,
) -> None:
    policy = PatchAgentLoopPolicy(
        max_observation_bytes=256,
        context_radius_lines=64,
    )
    _, _, _, inspector = _fixture(tmp_path, policy=policy)
    client = _ScriptedClient(
        [_response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),))]
    )

    result = _run(client, inspector)

    assert result.status == "blocked"
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    assert result.tool_rounds_used == 1
    assert result.total_observation_bytes > policy.max_observation_bytes
    assert result.observation_trace[0]["admitted_to_model"] is False


def test_loop_uses_remaining_fifth_turn_for_feedback_then_stops_repeated_empty_output(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=3)
    client = _ScriptedClient(
        [
            _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
            _response(turn=2, tool_calls=(_tool_call("edit_binding_002", turn=2),)),
            _response(turn=3, tool_calls=(_tool_call("edit_binding_003", turn=3),)),
            _response(turn=4, content=""),
            _response(turn=5, content=""),
        ]
    )

    result = _run(client, inspector)

    assert result.status == "blocked"
    assert result.termination["code"] == "PATCH_AGENT_REPEATED_INVALID_SUBMISSION"
    assert result.model_turns_used == 5
    assert result.tool_rounds_used == 3
    assert len(result.usage_by_turn) == 5
    assert client.requests[4].tools == ()
    assert client.requests[4].tool_choice == "none"
    assert client.requests[4].response_format == _final_format()
    assert result.submission_trace[0]["feedback_in_request"] is True
    assert result.submission_trace[0]["consumed_in_model_turn"] == 5
    assert result.submission_trace[1]["feedback_queued"] is False


def test_loop_records_source_drift_after_model_tool_selection(tmp_path: Path) -> None:
    _, source, _, inspector = _fixture(tmp_path)

    def drift(turn: int) -> None:
        if turn == 1:
            source.write_text("changed during provider turn\n", encoding="utf-8")

    client = _ScriptedClient(
        [_response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),))],
        before_response=drift,
    )

    result = _run(client, inspector)

    assert result.status == "blocked"
    assert result.termination["code"] == "PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"
    assert result.model_turns_used == 1
    assert result.tool_rounds_used == 1
    assert result.tool_call_trace[0]["status"] == "rejected"
    assert result.tool_call_trace[0]["dispatch_started"] is True


def test_loop_records_provider_failure_as_usage_unavailable(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path)

    class _FailingClient:
        provider = "failing_provider"
        model = "failing_model"

        @staticmethod
        def complete_turn(_request):
            raise AgentTurnProviderError(
                "provider unavailable",
                diagnostic={"failure_boundary": "provider_request_gate"},
            )

    result = run_patch_agent_loop(
        client=_FailingClient(),
        initial_messages=(AgentMessage(role="user", content="patch"),),
        final_response_format=_final_format(),
        source_inspector=inspector,
    )

    assert result.status == "blocked"
    assert result.termination["code"] == "PATCH_AGENT_PROVIDER_TURN_FAILED"
    assert result.termination["reason"] == "provider unavailable"
    assert result.termination["provider_diagnostic"] == {
        "failure_boundary": "provider_request_gate"
    }
    assert result.model_turns_used == 1
    assert result.usage_by_turn == (
        {
            "turn_index": 1,
            "provider": "failing_provider",
            "model": "failing_model",
            "request_id": None,
            "stop_reason": None,
            "usage": None,
            "usage_available": False,
        },
    )


def _supporting_fixture(tmp_path: Path):
    workspace, _, plan, baseline = _fixture(tmp_path)
    support = workspace / "Mod" / "Consumer.cs"
    support.write_text("void Consume() {}\n", encoding="utf-8")
    item = {"evidence_id": "evidence-consumer", "source_type": "target_source",
            "source_path": "Mod/Consumer.cs", "source_hash": hashlib.sha256(support.read_bytes()).hexdigest(),
            "span": {"start_line": 1, "end_line": 1}, "symbol": "Consume"}
    plan["binding_registry"]["supporting_bindings"] = [{
        "binding_id": "support_binding_consumer", "evidence_id": item["evidence_id"],
        "source_type": item["source_type"], "source_path": item["source_path"],
        "target_span": item["span"], "target_symbol": item["symbol"]}]
    return workspace, support, plan, baseline, {"items": [item]}


def test_supporting_read_preserves_edit_authority_and_snapshot(tmp_path: Path) -> None:
    workspace, source, plan, baseline, evidence = _supporting_fixture(tmp_path)
    inspector = PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan,
        evidence_pack=evidence, policy=PatchAgentLoopPolicy(enable_supporting_reads=True))
    assert inspector.available_binding_ids == baseline.available_binding_ids
    assert inspector.source_snapshot_sha256 == baseline.source_snapshot_sha256
    assert inspector.read_source_snapshot_sha256 != inspector.source_snapshot_sha256
    assert inspector.available_read_binding_ids == ("edit_binding_001", "support_binding_consumer")
    observation = inspector.inspect(binding_id="support_binding_consumer", observation_id="read-1")
    assert "Consume" in observation.excerpt
    source.write_text("changed\n", encoding="utf-8")
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"):
        inspector.validate_snapshot()


def test_supporting_read_requires_matching_evidence(tmp_path: Path) -> None:
    workspace, _, plan, _, evidence = _supporting_fixture(tmp_path)
    evidence["items"][0]["span"]["end_line"] = 2
    plan["binding_registry"]["supporting_bindings"][0]["target_span"] = {"start_line": 1, "end_line": 1}
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_SUPPORTING_EVIDENCE_MISMATCH"):
        PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan,
            evidence_pack=evidence, policy=PatchAgentLoopPolicy(enable_supporting_reads=True))


def test_optional_inspection_can_finish_without_forced_read(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(require_source_inspection=False))
    client = _ScriptedClient([_response(turn=1, content='{"changes":[]}')])
    result = _run(client, inspector)
    assert result.completed
    assert client.requests[0].tool_choice == "auto"
    assert result.to_dict()["tool_availability_trace"][0]["selection"] == "allowed_not_selected"


def test_resume_keeps_tool_history_and_shares_budgets(tmp_path: Path) -> None:
    from dataclasses import replace
    _, _, _, inspector = _fixture(tmp_path, binding_count=2,
        policy=PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False))
    original = _ScriptedClient([_response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
                                _response(turn=2, content='{"changes":[]}')])
    first = _run(original, inspector)
    previous = replace(first.final_request, messages=(*first.final_request.messages,
        AgentMessage(role="assistant", content=first.final_content), AgentMessage(role="user", content="failure")))
    resumed = _ScriptedClient([_response(turn=3, tool_calls=(_tool_call("edit_binding_002", turn=3),)),
                              _response(turn=4, content='{"changes":[]}')])
    result = run_patch_agent_loop(client=resumed, initial_messages=previous.messages,
        resume_request=previous, final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=2, consumed_tool_rounds=1, consumed_observation_bytes=first.total_observation_bytes,
        reserve_model_turns=1)
    assert result.completed and result.model_turns_used == 2 and result.tool_rounds_used == 1
    assert resumed.requests[0].tool_results == previous.tool_results
    assert resumed.requests[0].provider_state == previous.provider_state
    states = [m.content for m in resumed.requests[0].messages if isinstance(m.content, dict)
              and m.content.get("message_type") == "patch_agent_loop_state"]
    assert len(states) == 1 and states[0]["budget_state"]["model_turns_used"] == 2
    assert resumed.requests[1].tools == ()
    assert resumed.requests[1].historical_tool_exchanges[0].tool_results == previous.tool_results
    assert resumed.requests[1].historical_tool_exchanges[0].provider_state == previous.provider_state
    assert resumed.requests[1].tool_results[0].output["binding_id"] == "edit_binding_002"


def test_reserved_budget_stops_before_provider_call(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path)
    client = _ScriptedClient([])
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage(role="user", content="patch"),),
        source_inspector=inspector, final_response_format=_final_format(), consumed_model_turns=4, reserve_model_turns=1)
    assert not client.requests and result.model_turns_used == 0
    assert result.termination["code"] == "PATCH_AGENT_MODEL_TURN_BUDGET_EXHAUSTED"


def test_upstream_request_is_validated_and_does_not_edit(tmp_path: Path) -> None:
    _, source, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        require_source_inspection=False, allow_upstream_request=True))
    before = source.read_bytes()
    client = _ScriptedClient([_response(turn=1, tool_calls=(AgentToolCall(call_id="upstream-1",
        name="request_patch_upstream", arguments={"required_owner": "planning", "reason": "Required edit is outside current bindings.",
        "source_refs": ["binding://edit_binding_001"]}),))])
    result = _run(client, inspector)
    assert result.termination["code"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    assert result.termination["upstream_request"]["required_owner"] == "planning"
    assert source.read_bytes() == before and result.tool_rounds_used == 0


@pytest.mark.parametrize("arguments", [
    {"required_owner": "apply", "reason": "request", "source_refs": ["binding://edit_binding_001"]},
    {"required_owner": "planning", "reason": "request", "source_refs": ["binding://unregistered"]},
    {"required_owner": "evidence", "reason": "", "source_refs": ["binding://edit_binding_001"]},
])
def test_upstream_request_cannot_create_route_or_source_authority(tmp_path: Path, arguments) -> None:
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        require_source_inspection=False, allow_upstream_request=True))
    result = _run(_ScriptedClient([_response(turn=1, tool_calls=(AgentToolCall(
        call_id="request-1", name="request_patch_upstream", arguments=arguments),))]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_UPSTREAM_REQUEST_INVALID"
    assert "upstream_request" not in result.termination


def test_resume_cannot_repeat_prior_read_or_reset_observation_budget(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=2)
    first = _run(_ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
        _response(turn=2, content='{"changes":[]}'),
    ]), inspector)
    repeated = _ScriptedClient([_response(turn=3, tool_calls=(_tool_call("edit_binding_001", turn=3),))])
    result = run_patch_agent_loop(client=repeated, initial_messages=first.final_request.messages,
        resume_request=first.final_request, final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=2, consumed_tool_rounds=1, consumed_observation_bytes=first.total_observation_bytes)
    assert result.termination["code"] == "PATCH_AGENT_REPEATED_TOOL_CALL"
    assert result.model_turns_used == 1 and result.tool_rounds_used == 0
    no_budget = _ScriptedClient([_response(turn=3, tool_calls=(_tool_call("edit_binding_002", turn=3),))])
    result = run_patch_agent_loop(client=no_budget, initial_messages=first.final_request.messages,
        resume_request=first.final_request, final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=2, consumed_tool_rounds=1, consumed_observation_bytes=inspector.policy.max_observation_bytes)
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    assert result.total_observation_bytes == 0


def test_loop_source_policy_disable_is_traced_separately(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=2, policy=PatchAgentLoopPolicy())
    result = _run(_ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
        _response(turn=2, tool_calls=(_tool_call("edit_binding_002", turn=2),)),
    ]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_TOOL_FORBIDDEN"
    assert result.tool_availability_trace[-1]["selection"] == "forbidden_attempt"
    assert result.tool_rounds_used == 1


def test_final_budgeted_turn_can_request_upstream_instead_of_forcing_patch(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        require_source_inspection=False, allow_upstream_request=True))
    client = _ScriptedClient([_response(turn=5, tool_calls=(AgentToolCall(call_id="upstream-5",
        name="request_patch_upstream", arguments={"required_owner": "evidence", "reason": "More evidence is required.",
        "source_refs": ["binding://edit_binding_001"]}),))])
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage(role="user", content="failure"),),
        source_inspector=inspector, final_response_format=_final_format(), consumed_model_turns=4)
    assert result.model_turns_used == 1
    assert result.termination["code"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    assert [tool.name for tool in client.requests[0].tools] == ["request_patch_upstream"]


def _api_fixture(tmp_path: Path):
    workspace, source, plan, baseline = _fixture(tmp_path)
    item = {
        "evidence_id": "api-method-1", "source_type": "decompiled_api",
        "source_path": "Library.dll", "source_ref": "source://registered/Library.dll",
        "source_hash": "A1" * 32, "file_hash": "A1" * 32,
        "span": None, "symbol": "Library.ReadState",
        "module_mvid": "85155e68-33a5-4fa5-a419-c563e7ea5e60",
        "metadata_token": "0x06003CAC", "signature_blob": "2001010C",
        "excerpt": "registered IL information " * 100 + "END_OF_REGISTERED_EVIDENCE",
    }
    plan["binding_registry"]["supporting_bindings"] = [{
        "binding_id": "support_api_1", "evidence_id": item["evidence_id"],
        "source_type": item["source_type"], "source_path": item["source_path"],
        "target_span": None, "target_symbol": item["symbol"],
    }]
    inspector = PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan,
        evidence_pack={"items": [item]}, policy=PatchAgentLoopPolicy(enable_supporting_reads=True))
    return source, baseline, inspector, item


def test_registered_api_read_returns_complete_evidence_without_live_read_or_edit_authority(tmp_path: Path) -> None:
    _, baseline, inspector, item = _api_fixture(tmp_path)
    assert inspector.available_binding_ids == baseline.available_binding_ids
    assert inspector.source_snapshot_sha256 == baseline.source_snapshot_sha256
    assert inspector.read_source_snapshot_sha256 == baseline.read_source_snapshot_sha256
    assert "support_api_1" in inspector.available_read_binding_ids
    observation = inspector.inspect(binding_id="support_api_1", observation_id="api-read-1")
    payload = observation.model_view()
    assert payload["excerpt"] == item["excerpt"] and not payload["truncated"]
    assert payload["observation_kind"] == "registered_api_evidence"
    assert payload["source_identity_status"] == "registered_not_live_revalidated"
    assert payload["source_hash"] == item["source_hash"]
    assert payload["source_hash"] != payload["excerpt_sha256"]
    assert payload["target_span"] is None and payload["excerpt_span"] is None
    assert payload["evidence_id"] == item["evidence_id"]
    assert len(payload["evidence_item_sha256"]) == 64
    item["excerpt"] = "caller mutation after admission"
    assert inspector.inspect(binding_id="support_api_1", observation_id="api-read-2").excerpt == observation.excerpt


def test_registered_api_read_uses_same_observation_budget_and_checks_live_drift(tmp_path: Path) -> None:
    source, _, inspector, _ = _api_fixture(tmp_path)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("support_api_1", turn=1),)),
        _response(turn=2, content='{"changes":[]}'),
    ])
    result = _run(client, inspector)
    assert result.completed and result.tool_rounds_used == 1
    assert result.observation_trace[0]["observation_kind"] == "registered_api_evidence"
    assert result.total_observation_bytes > 1024
    source.write_text("source drift", encoding="utf-8")
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"):
        inspector.inspect(binding_id="support_api_1", observation_id="api-read-2")


def test_real_five_read_response_gets_feedback_then_reselects_within_budget(tmp_path: Path) -> None:
    from src.libs.llm import OllamaChatAgentAdapter
    raw = json.loads((Path(__file__).parents[1] / "fixtures" / "patch_multi_read_response_20260905.json").read_text(encoding="utf-8"))
    recorded = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="qwen3-coder:30b", max_output_tokens=4096,
        request_sender=lambda *_: raw).complete_turn(
            AgentTurnRequest(messages=(AgentMessage(role="user", content="replay recorded response"),)))
    _, _, _, inspector = _fixture(tmp_path, binding_count=5, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, require_source_inspection=False, finalize_after_first_observation=False,
        max_total_model_turns=4))
    calls = tuple(_tool_call(f"edit_binding_{index:03d}", turn=index + 10) for index in (1, 2, 3))
    client = _ScriptedClient([recorded, _response(turn=2, tool_calls=calls), _response(turn=3, content='{"changes":[]}')])
    result = _run(client, inspector)
    assert result.completed and result.model_turns_used == 3 and result.tool_rounds_used == 3
    assert len(result.observation_trace) == 3
    rejected = result.tool_call_trace[:5]
    assert all(item["status"] == "rejected_not_executed" and item["dispatch_started"] is False for item in rejected)
    feedback = client.requests[1].tool_results
    assert len(feedback) == 5 and client.requests[1].provider_state == recorded.provider_state
    assert all(item.output["status"] == "not_executed" and item.output["remaining_read_count"] == 3 for item in feedback)
    assert len(client.requests[2].tool_results) == 3
    assert all(item["dispatch_started"] for item in result.tool_call_trace[5:])


@pytest.mark.parametrize("limit", [0, 6, True])
def test_model_turn_policy_rejects_limits_outside_shared_cap(limit) -> None:
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_POLICY_INVALID"):
        PatchAgentLoopPolicy(max_total_model_turns=limit)


def test_batched_reads_reject_duplicates_before_dispatch(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(allow_batched_reads=True))
    result = _run(_ScriptedClient([_response(turn=1, tool_calls=(
        _tool_call("edit_binding_001", turn=1), _tool_call("edit_binding_001", turn=2),
    ))]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_REPEATED_TOOL_CALL"
    assert result.tool_rounds_used == 0 and not result.observation_trace


def test_repeated_oversized_batch_stops_even_with_new_call_ids(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=5, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, require_source_inspection=False, finalize_after_first_observation=False,
        max_total_model_turns=4))
    initial = tuple(_tool_call(f"edit_binding_{index:03d}", turn=index) for index in range(1, 6))
    repeated = tuple(_tool_call(f"edit_binding_{index:03d}", turn=index + 10) for index in range(5, 0, -1))
    client = _ScriptedClient([_response(turn=1, tool_calls=initial), _response(turn=2, tool_calls=repeated)])
    result = _run(client, inspector)
    assert result.termination["code"] == "PATCH_AGENT_REPEATED_TOOL_BATCH"
    assert result.model_turns_used == 2 and result.tool_rounds_used == 0
    assert len(client.requests) == 2 and not result.observation_trace


@pytest.mark.parametrize("tool_name", ["request_patch_upstream", "unregistered_tool"])
def test_read_batch_rejects_mixed_tools_before_any_read(tmp_path: Path, tool_name) -> None:
    _, _, _, inspector = _fixture(tmp_path, binding_count=2, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, allow_upstream_request=True, require_source_inspection=False))
    result = _run(_ScriptedClient([_response(turn=1, tool_calls=(
        _tool_call("edit_binding_001", turn=1), _tool_call("edit_binding_002", turn=2, name=tool_name),
    ))]), inspector)
    assert result.tool_rounds_used == 0 and not result.observation_trace
    assert all(item["status"] == "rejected_not_executed" for item in result.tool_call_trace)


def test_batch_stops_on_snapshot_drift_without_executing_remaining_reads(tmp_path: Path) -> None:
    _, source, _, inspector = _fixture(tmp_path, binding_count=3, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, require_source_inspection=False, finalize_after_first_observation=False))
    original_inspect = inspector.inspect
    def inspect_then_drift(**kwargs):
        observation = original_inspect(**kwargs)
        source.write_text("source drift after first read", encoding="utf-8")
        return observation
    inspector.inspect = inspect_then_drift
    result = _run(_ScriptedClient([_response(turn=1, tool_calls=tuple(
        _tool_call(f"edit_binding_{index:03d}", turn=index) for index in range(1, 4)
    ))]), inspector)
    assert result.termination["code"] == "PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT"
    assert result.tool_rounds_used == 2
    assert [item["dispatch_started"] for item in result.tool_call_trace] == [True, True, False]


def test_real_budget_reselection_does_not_reserve_unexecuted_provider_call_ids(tmp_path: Path) -> None:
    from src.libs.llm import OllamaChatAgentAdapter
    fixture_root = Path(__file__).parents[1] / "fixtures"
    replies = [json.loads((fixture_root / name).read_text(encoding="utf-8")) for name in (
        "patch_multi_read_budget_response_20260905.json", "patch_multi_read_reselection_response_20260905.json")]
    replies.append({"model": "qwen3-coder:30b", "done": True, "message": {"content": '{"changes":[]}'}})
    requests = []
    def send(_url, payload, _headers):
        requests.append(payload)
        return replies.pop(0)
    client = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="qwen3-coder:30b",
        max_output_tokens=4096, request_sender=send)
    _, _, _, inspector = _fixture(tmp_path, binding_count=5, policy=PatchAgentLoopPolicy(
        allow_batched_reads=True, require_source_inspection=False, finalize_after_first_observation=False,
        max_total_model_turns=4))
    result = _run(client, inspector)
    assert result.completed, result.termination
    assert result.model_turns_used == 3 and result.tool_rounds_used == 2
    assert result.tool_call_trace[0]["tool_call_id"] == result.tool_call_trace[5]["tool_call_id"]
    assert [entry["binding_id"] for entry in result.observation_trace] == ["edit_binding_001", "edit_binding_005"]
    assert all(entry["dispatch_started"] is False for entry in result.tool_call_trace[:5])
    assert len(requests) == 3 and not replies


def test_resume_budget_feedback_does_not_mark_rejected_reads_as_executed(tmp_path: Path) -> None:
    from src.libs.llm.agent_turn import AgentToolExchange, AgentToolResult
    _, _, _, inspector = _fixture(tmp_path, binding_count=2, policy=PatchAgentLoopPolicy(
        require_source_inspection=False, allow_batched_reads=True, finalize_after_first_observation=False))
    previous = AgentTurnRequest(messages=(AgentMessage(role="user", content="source request"),),
        historical_tool_exchanges=(AgentToolExchange(tool_results=(AgentToolResult(
            call_id="call-001", name="inspect_plan_binding_source", output={"status": "not_executed",
                "error_code": "PATCH_AGENT_TOOL_BATCH_BUDGET_EXCEEDED", "binding_id": "edit_binding_001"}),),
            provider_state={"content": "", "tool_calls": [{"id": "call-001"}]}, insert_index=1),))
    client = _ScriptedClient([_response(turn=2, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
        _response(turn=3, content='{"changes":[]}')])
    result = run_patch_agent_loop(client=client, initial_messages=previous.messages, resume_request=previous,
        source_inspector=inspector, final_response_format=_final_format(), consumed_model_turns=1)
    assert result.completed and result.tool_rounds_used == 1


def _budget_state(request: AgentTurnRequest) -> dict[str, object]:
    return next(message.content["budget_state"] for message in request.messages
        if isinstance(message.content, dict) and message.content.get("message_type") == "patch_agent_loop_state")


def _checked_patch_output(content: str) -> dict[str, object]:
    """Execute a fixed test-only Python function; this is not a product model or Mod."""
    code = json.loads(content)["changes"][0]["after_text"]
    namespace: dict[str, object] = {}
    exec(compile(code, "offline_patch_behavior", "exec"), namespace)
    actual = namespace["scale"](2)
    return {"status": "passed" if actual == 4 else "behavior_failed", "input": 2,
        "expected": 4, "observed": actual, "code_sha256": hashlib.sha256(code.encode()).hexdigest()}


def _after_behavior_check(result, observation: dict[str, object]) -> AgentTurnRequest:
    from dataclasses import replace
    assert result.final_request is not None
    return replace(result.final_request, messages=(*result.final_request.messages,
        AgentMessage(role="assistant", content=result.final_content),
        AgentMessage(role="user", content=observation)))


@pytest.mark.parametrize("initial_reads", [1, 5])
def test_reserved_read_and_model_budget_is_used_after_executed_behavior_failure(tmp_path: Path, initial_reads: int) -> None:
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False,
        allow_batched_reads=True, max_tool_rounds=initial_reads + 1, context_radius_lines=2)
    _, source, _, inspector = _fixture(tmp_path, binding_count=initial_reads + 1, policy=policy)
    baseline = source.read_bytes()
    failed = json.dumps({"changes": [{"after_text": "def scale(value):\n    return value + 1\n"}]})
    revised = json.dumps({"changes": [{"after_text": "def scale(value):\n    return value * 2\n"}]})
    next_binding = f"edit_binding_{initial_reads + 1:03d}"
    client = _ScriptedClient([
        _response(turn=1, tool_calls=tuple(_tool_call(f"edit_binding_{index:03d}", turn=index)
            for index in range(1, initial_reads + 1))),
        _response(turn=2, content=failed),
        _response(turn=3, tool_calls=(_tool_call(next_binding, turn=initial_reads + 10),)),
        _response(turn=4, content=revised),
    ])
    first = run_patch_agent_loop(client=client,
        initial_messages=(AgentMessage(role="user", content="Repair scale(2) to return 4; keep the baseline unchanged."),),
        final_response_format=_final_format(), source_inspector=inspector,
        reserve_model_turns=2, reserve_tool_reads=1)
    assert first.completed and first.tool_rounds_used == initial_reads
    first_check = _checked_patch_output(first.final_content)
    assert first_check["status"] == "behavior_failed" and first_check["observed"] == 3
    assert len(client.requests[1].tool_results) == initial_reads
    initial_budget = _budget_state(client.requests[0])
    assert initial_budget["total_remaining_tool_rounds"] == initial_reads + 1
    assert initial_budget["remaining_tool_rounds"] == initial_reads
    assert initial_budget["reserved_tool_reads"] == 1
    assert _budget_state(client.requests[1])["remaining_tool_rounds"] == 0
    assert client.requests[1].tools == ()

    previous = _after_behavior_check(first, first_check)
    feedback_bytes = len(json.dumps(first_check).encode())
    second = run_patch_agent_loop(client=client, initial_messages=previous.messages, resume_request=previous,
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=first.model_turns_used, consumed_tool_rounds=first.tool_rounds_used,
        consumed_observation_bytes=first.total_observation_bytes + feedback_bytes)
    assert second.completed and second.tool_rounds_used == 1
    assert first.model_turns_used + second.model_turns_used == 4 < policy.max_total_model_turns
    failure_request, revision_request = client.requests[2:]
    assert any(tool.name == PATCH_SOURCE_INSPECTION_TOOL_NAME for tool in failure_request.tools)
    assert _budget_state(failure_request)["remaining_tool_rounds"] == 1
    assert _budget_state(failure_request)["remaining_model_turns"] >= 2
    assert second.to_dict()["tool_availability_trace"][0]["budget_state"] == _budget_state(failure_request)
    assert first_check in [message.content for message in failure_request.messages]
    assert failed in [message.content for message in failure_request.messages if message.role == "assistant"]
    assert revision_request.tool_results[0].output["binding_id"] == next_binding
    assert revision_request.tool_results[0].output["excerpt"]
    assert all(entry["admitted_to_model"] for entry in second.observation_trace)
    assert _checked_patch_output(second.final_content)["status"] == "passed"
    assert source.read_bytes() == baseline


@pytest.mark.parametrize("exhausted", ["reads", "model", "observation_bytes"])
def test_executed_failure_does_not_hide_missing_post_failure_read_capacity(tmp_path: Path, exhausted: str) -> None:
    initial_reads = 3 if exhausted == "model" else 1
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False,
        max_tool_rounds=initial_reads if exhausted == "reads" else initial_reads + 1, context_radius_lines=2)
    _, _, _, inspector = _fixture(tmp_path, binding_count=initial_reads + 1, policy=policy)
    failed = json.dumps({"changes": [{"after_text": "def scale(value):\n    return value + 1\n"}]})
    client = _ScriptedClient([
        *[_response(turn=index, tool_calls=(_tool_call(f"edit_binding_{index:03d}", turn=index),))
            for index in range(1, initial_reads + 1)],
        _response(turn=initial_reads + 1, content=failed),
        _response(turn=initial_reads + 2, tool_calls=(_tool_call(f"edit_binding_{initial_reads + 1:03d}", turn=20),)),
    ])
    first = _run(client, inspector)
    check = _checked_patch_output(first.final_content)
    assert check["status"] == "behavior_failed"
    previous = _after_behavior_check(first, check)
    second = run_patch_agent_loop(client=client, initial_messages=previous.messages, resume_request=previous,
        final_response_format=_final_format(), source_inspector=inspector,
        consumed_model_turns=first.model_turns_used, consumed_tool_rounds=first.tool_rounds_used,
        consumed_observation_bytes=(policy.max_observation_bytes if exhausted == "observation_bytes"
            else first.total_observation_bytes))
    assert second.status == "blocked" and second.tool_rounds_used == 0
    assert client.requests[-1].tools == ()
    assert second.termination["code"] == {"reads": "PATCH_AGENT_TOOL_ROUND_BUDGET_EXHAUSTED",
        "model": "PATCH_AGENT_MODEL_TURN_BUDGET_EXHAUSTED",
        "observation_bytes": "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"}[exhausted]
    remaining = _budget_state(client.requests[-1])
    if exhausted == "reads":
        assert remaining["remaining_tool_rounds"] == 0
    elif exhausted == "model":
        assert remaining["remaining_model_turns"] == 1
    else:
        assert remaining["remaining_observation_bytes"] == 0


def test_reservations_do_not_force_reads_when_first_output_passes(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(require_source_inspection=False))
    client = _ScriptedClient([_response(turn=1,
        content=json.dumps({"changes": [{"after_text": "def scale(value):\n    return value * 2\n"}]}))])
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage(role="user", content="Repair scale."),),
        final_response_format=_final_format(), source_inspector=inspector,
        reserve_model_turns=2, reserve_tool_reads=1)
    assert result.completed and result.model_turns_used == 1 and result.tool_rounds_used == 0
    assert client.requests[0].tool_choice == "auto"
    assert _checked_patch_output(result.final_content)["status"] == "passed"
    assert not client.responses


def test_failed_output_can_be_revised_without_forcing_a_new_read(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        require_source_inspection=False, finalize_after_first_observation=False))
    failed = json.dumps({"changes": [{"after_text": "def scale(value):\n    return value + 1\n"}]})
    revised = json.dumps({"changes": [{"after_text": "def scale(value):\n    return value * 2\n"}]})
    client = _ScriptedClient([_response(turn=1, content=failed), _response(turn=2, content=revised)])
    first = run_patch_agent_loop(client=client, initial_messages=(AgentMessage(role="user", content="Repair scale."),),
        final_response_format=_final_format(), source_inspector=inspector, reserve_model_turns=2, reserve_tool_reads=1)
    check = _checked_patch_output(first.final_content)
    assert check["status"] == "behavior_failed"
    previous = _after_behavior_check(first, check)
    second = run_patch_agent_loop(client=client, initial_messages=previous.messages, resume_request=previous,
        final_response_format=_final_format(), source_inspector=inspector, consumed_model_turns=first.model_turns_used)
    assert second.completed and second.tool_rounds_used == 0
    assert client.requests[1].tool_choice == "auto"
    assert any(tool.name == PATCH_SOURCE_INSPECTION_TOOL_NAME for tool in client.requests[1].tools)
    assert _checked_patch_output(second.final_content)["status"] == "passed"


def test_observation_reservation_limits_initial_segment_and_is_visible(tmp_path: Path) -> None:
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(require_source_inspection=False))
    client = _ScriptedClient([_response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),))])
    reserved = inspector.policy.max_observation_bytes - 1
    result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage(role="user", content="Repair."),),
        final_response_format=_final_format(), source_inspector=inspector, reserve_observation_bytes=reserved)
    assert result.termination["code"] == "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
    assert result.observation_trace[0]["admitted_to_model"] is False
    budget = _budget_state(client.requests[0])
    assert budget["total_remaining_observation_bytes"] == 32768
    assert budget["remaining_observation_bytes"] == 1
    assert budget["reserved_observation_bytes"] == reserved


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_binding_read_limit_rejects_non_positive_integers(limit) -> None:
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_POLICY_INVALID"):
        PatchAgentLoopPolicy(max_tool_rounds=limit)


@pytest.mark.parametrize("reservations", [
    {"reserve_tool_reads": True}, {"reserve_tool_reads": 4},
    {"reserve_observation_bytes": -1}, {"reserve_observation_bytes": 32769},
])
def test_reservations_cannot_create_extra_shared_budget(tmp_path: Path, reservations: dict[str, object]) -> None:
    _, _, _, inspector = _fixture(tmp_path)
    client = _ScriptedClient([])
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_LOOP_BUDGET_INVALID"):
        run_patch_agent_loop(client=client, initial_messages=(AgentMessage(role="user", content="Repair."),),
            final_response_format=_final_format(), source_inspector=inspector, **reservations)
    assert not client.requests
