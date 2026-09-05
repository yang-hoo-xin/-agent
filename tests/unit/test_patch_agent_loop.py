"""Focused tests for the bounded Plan-bound Patch source inspection loop."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

import pytest

from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolCall,
    AgentTurnProviderError,
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


def test_policy_has_fixed_turn_limits_and_real_context_default() -> None:
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


def test_loop_uses_fifth_turn_only_for_one_forced_final_retry(tmp_path: Path) -> None:
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
    assert result.termination["code"] == "PATCH_AGENT_MODEL_TURN_BUDGET_EXHAUSTED"
    assert result.model_turns_used == 5
    assert result.tool_rounds_used == 3
    assert len(result.usage_by_turn) == 5
    assert client.requests[4].tools == ()
    assert client.requests[4].tool_choice == "none"
    assert client.requests[4].response_format == _final_format()


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
