"""Bounded Plan-bound source inspection loop for Patch generation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolCall,
    AgentToolDefinition,
    AgentToolResult,
    AgentTurnClient,
    AgentTurnProviderError,
    AgentTurnRequest,
    AgentTurnResponse,
)

PATCH_SOURCE_INSPECTION_TOOL_NAME = "inspect_plan_binding_source"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PatchAgentLoopError(RuntimeError):
    """Reject an invalid Patch loop input or a drifted source boundary."""

    def __init__(self, code: str, *, stage: str, reason: str) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class PatchAgentLoopPolicy:
    """Fixed turn limits plus bounded source-observation controls."""

    max_observation_bytes: int = 32_768
    context_radius_lines: int = 64
    finalize_after_first_observation: bool = True
    max_tool_rounds: int = field(default=3, init=False)
    max_total_model_turns: int = field(default=5, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.finalize_after_first_observation, bool):
            raise PatchAgentLoopError(
                "PATCH_AGENT_POLICY_INVALID",
                stage="policy",
                reason="finalize_after_first_observation must be a boolean.",
            )
        for name in ("max_observation_bytes", "context_radius_lines"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise PatchAgentLoopError(
                    "PATCH_AGENT_POLICY_INVALID",
                    stage="policy",
                    reason=f"{name} must be a positive integer.",
                )


@dataclass(frozen=True)
class PatchSourceObservation:
    """One path-hidden source excerpt bound to an admitted Plan edit binding."""

    observation_id: str
    binding_id: str
    source_ref: str
    source_hash: str
    source_snapshot_sha256: str
    target_span: dict[str, int]
    excerpt_span: dict[str, int]
    excerpt: str
    truncated: bool
    payload_sha256: str
    model_payload_bytes: int

    def model_view(self) -> dict[str, object]:
        """Return the bounded ref-first payload visible to the model."""

        return {
            "observation_id": self.observation_id,
            "binding_id": self.binding_id,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "target_span": dict(self.target_span),
            "excerpt_span": dict(self.excerpt_span),
            "excerpt": self.excerpt,
            "truncated": self.truncated,
            "observation_sha256": self.payload_sha256,
        }


@dataclass(frozen=True)
class PatchAgentLoopResult:
    """Complete in-process Patch loop result and bounded execution receipt."""

    status: Literal["completed", "blocked"]
    final_content: str | None
    provider: str
    model: str
    model_turns_used: int
    tool_rounds_used: int
    total_observation_bytes: int
    usage_by_turn: tuple[dict[str, object], ...]
    tool_call_trace: tuple[dict[str, object], ...]
    observation_trace: tuple[dict[str, object], ...]
    termination: dict[str, object]
    # In-process context for a subsequent correction; deliberately excluded from receipts.
    final_request: AgentTurnRequest | None = field(default=None, repr=False, compare=False)

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, object]:
        final_bytes = (
            None
            if self.final_content is None
            else self.final_content.encode("utf-8")
        )
        return {
            "status": self.status,
            "final_content_sha256": (
                None if final_bytes is None else hashlib.sha256(final_bytes).hexdigest()
            ),
            "final_content_utf8_bytes": (
                None if final_bytes is None else len(final_bytes)
            ),
            "provider": self.provider,
            "model": self.model,
            "model_turns_used": self.model_turns_used,
            "tool_rounds_used": self.tool_rounds_used,
            "total_observation_bytes": self.total_observation_bytes,
            "usage_by_turn": [deepcopy(item) for item in self.usage_by_turn],
            "tool_call_trace": [deepcopy(item) for item in self.tool_call_trace],
            "observation_trace": [
                deepcopy(item) for item in self.observation_trace
            ],
            "termination": deepcopy(self.termination),
        }


@dataclass(frozen=True)
class _BoundSource:
    binding_id: str
    path: Path
    relative_path: str
    source_hash: str
    target_span: dict[str, int]


class PlanBoundSourceInspector:
    """Read only source bytes already authorized by Plan edit bindings."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        implementation_plan: Mapping[str, Any],
        policy: PatchAgentLoopPolicy,
    ) -> None:
        if not isinstance(policy, PatchAgentLoopPolicy):
            raise PatchAgentLoopError(
                "PATCH_AGENT_POLICY_INVALID",
                stage="source_admission",
                reason="A PatchAgentLoopPolicy is required.",
            )
        try:
            root = Path(workspace_root).resolve(strict=True)
        except OSError as exc:
            raise PatchAgentLoopError(
                "PATCH_AGENT_WORKSPACE_INVALID",
                stage="source_admission",
                reason="The workspace root is unavailable.",
            ) from exc
        if not root.is_dir():
            raise PatchAgentLoopError(
                "PATCH_AGENT_WORKSPACE_INVALID",
                stage="source_admission",
                reason="The workspace root must be a directory.",
            )
        registry = implementation_plan.get("binding_registry")
        raw_bindings = registry.get("edit_bindings") if isinstance(registry, Mapping) else None
        if not isinstance(raw_bindings, (list, tuple)) or not raw_bindings:
            raise PatchAgentLoopError(
                "PATCH_AGENT_PLAN_BINDINGS_INVALID",
                stage="source_admission",
                reason="The ImplementationPlan has no edit bindings.",
            )
        raw_changes = implementation_plan.get("proposed_changes")
        if not isinstance(raw_changes, (list, tuple)) or not raw_changes:
            raise PatchAgentLoopError(
                "PATCH_AGENT_PLAN_CHANGES_INVALID",
                stage="source_admission",
                reason="The ImplementationPlan has no selected changes.",
            )
        selected_binding_ids: list[str] = []
        for raw_change in raw_changes:
            binding_id = (
                raw_change.get("edit_binding_id")
                if isinstance(raw_change, Mapping)
                else None
            )
            if type(binding_id) is not str or not binding_id:
                raise PatchAgentLoopError(
                    "PATCH_AGENT_PLAN_CHANGES_INVALID",
                    stage="source_admission",
                    reason="Every selected Plan change must name one edit binding id.",
                )
            selected_binding_ids.append(binding_id)
        if len(selected_binding_ids) != len(set(selected_binding_ids)):
            raise PatchAgentLoopError(
                "PATCH_AGENT_PLAN_CHANGES_INVALID",
                stage="source_admission",
                reason="Selected Plan change binding ids must be unique.",
            )
        selected_binding_set = set(selected_binding_ids)

        bindings: dict[str, _BoundSource] = {}
        binding_order: list[str] = []
        source_hashes: dict[str, str] = {}
        source_paths: dict[str, Path] = {}
        for raw_binding in raw_bindings:
            if not isinstance(raw_binding, Mapping):
                raise PatchAgentLoopError(
                    "PATCH_AGENT_PLAN_BINDINGS_INVALID",
                    stage="source_admission",
                    reason="Every edit binding must be an object.",
                )
            if raw_binding.get("binding_id") not in selected_binding_set:
                continue
            binding = self._admit_binding(root, raw_binding)
            if binding.binding_id in bindings:
                raise PatchAgentLoopError(
                    "PATCH_AGENT_PLAN_BINDINGS_INVALID",
                    stage="source_admission",
                    reason="Edit binding ids must be unique.",
                )
            previous_hash = source_hashes.get(binding.relative_path)
            if previous_hash is not None and previous_hash != binding.source_hash:
                raise PatchAgentLoopError(
                    "PATCH_AGENT_PLAN_SOURCE_IDENTITY_CONFLICT",
                    stage="source_admission",
                    reason="One source path has conflicting Plan hashes.",
                )
            bindings[binding.binding_id] = binding
            binding_order.append(binding.binding_id)
            source_hashes[binding.relative_path] = binding.source_hash
            source_paths[binding.relative_path] = binding.path
        if set(bindings) != selected_binding_set:
            raise PatchAgentLoopError(
                "PATCH_AGENT_PLAN_CHANGES_INVALID",
                stage="source_admission",
                reason="A selected Plan change does not resolve to one edit binding.",
            )
        binding_order = selected_binding_ids

        self.workspace_root = root
        self.policy = policy
        self._bindings = bindings
        self._binding_order = tuple(binding_order)
        self._source_hashes = source_hashes
        self._source_paths = source_paths
        self._assert_snapshot_current(code="PATCH_AGENT_SOURCE_HASH_MISMATCH")
        self.source_snapshot_sha256 = _canonical_sha256(
            [
                {"source_path": relative_path, "source_hash": source_hashes[relative_path]}
                for relative_path in sorted(source_hashes)
            ]
        )

    @property
    def available_binding_ids(self) -> tuple[str, ...]:
        return self._binding_order

    def validate_snapshot(self) -> str:
        """Revalidate every Plan-bound source and return the frozen snapshot hash."""

        self._assert_snapshot_current(code="PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT")
        return self.source_snapshot_sha256

    def inspect(
        self,
        *,
        binding_id: str,
        observation_id: str,
    ) -> PatchSourceObservation:
        if type(binding_id) is not str or binding_id not in self._bindings:
            raise PatchAgentLoopError(
                "PATCH_AGENT_BINDING_UNKNOWN",
                stage="tool_admission",
                reason="The requested binding id is not in the exact Plan edit registry.",
            )
        if type(observation_id) is not str or not observation_id:
            raise PatchAgentLoopError(
                "PATCH_AGENT_OBSERVATION_ID_INVALID",
                stage="tool_admission",
                reason="The tool observation id must be non-empty text.",
            )
        self.validate_snapshot()
        binding = self._bindings[binding_id]
        try:
            source_bytes = binding.path.read_bytes()
            source_text = source_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_READ_FAILED",
                stage="tool_execution",
                reason="The bound source could not be read as UTF-8.",
            ) from exc
        if hashlib.sha256(source_bytes).hexdigest() != binding.source_hash:
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_SNAPSHOT_DRIFT",
                stage="tool_execution",
                reason="The bound source changed during inspection.",
            )

        lines = source_text.splitlines(keepends=True)
        start_line = binding.target_span["start_line"]
        end_line = binding.target_span["end_line"]
        excerpt_start = max(1, start_line - self.policy.context_radius_lines)
        excerpt_end = min(len(lines), end_line + self.policy.context_radius_lines)
        excerpt = "".join(lines[excerpt_start - 1 : excerpt_end])
        base_payload: dict[str, object] = {
            "observation_id": observation_id,
            "binding_id": binding_id,
            "source_ref": f"binding://{binding_id}",
            "source_hash": binding.source_hash,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "target_span": dict(binding.target_span),
            "excerpt_span": {
                "start_line": excerpt_start,
                "end_line": excerpt_end,
            },
            "excerpt": excerpt,
            "truncated": excerpt_start > 1 or excerpt_end < len(lines),
        }
        payload_sha256 = _canonical_sha256(base_payload)
        model_view = {**base_payload, "observation_sha256": payload_sha256}
        model_payload_bytes = len(_canonical_json(model_view).encode("utf-8"))
        return PatchSourceObservation(
            observation_id=observation_id,
            binding_id=binding_id,
            source_ref=str(base_payload["source_ref"]),
            source_hash=binding.source_hash,
            source_snapshot_sha256=self.source_snapshot_sha256,
            target_span=dict(binding.target_span),
            excerpt_span={"start_line": excerpt_start, "end_line": excerpt_end},
            excerpt=excerpt,
            truncated=bool(base_payload["truncated"]),
            payload_sha256=payload_sha256,
            model_payload_bytes=model_payload_bytes,
        )

    @staticmethod
    def _admit_binding(root: Path, raw_binding: Mapping[str, Any]) -> _BoundSource:
        binding_id = raw_binding.get("binding_id")
        relative_path = raw_binding.get("canonical_target_path")
        source_hash = raw_binding.get("source_hash")
        target_span = raw_binding.get("target_span")
        if type(binding_id) is not str or not binding_id:
            raise PatchAgentLoopError(
                "PATCH_AGENT_PLAN_BINDINGS_INVALID",
                stage="source_admission",
                reason="An edit binding id is missing.",
            )
        if type(relative_path) is not str or not relative_path:
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_PATH_INVALID",
                stage="source_admission",
                reason="An edit binding source path is missing.",
            )
        pure_path = PurePosixPath(relative_path)
        if (
            pure_path.is_absolute()
            or Path(relative_path).is_absolute()
            or ".." in pure_path.parts
            or "\\" in relative_path
        ):
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_PATH_ESCAPE",
                stage="source_admission",
                reason="An edit binding source path escapes the workspace.",
            )
        try:
            source_path = (root / Path(*pure_path.parts)).resolve(strict=True)
        except OSError as exc:
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_UNAVAILABLE",
                stage="source_admission",
                reason="A bound source file is unavailable.",
            ) from exc
        if not source_path.is_file() or not source_path.is_relative_to(root):
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_PATH_ESCAPE",
                stage="source_admission",
                reason="A bound source file is outside the workspace.",
            )
        if type(source_hash) is not str or _SHA256_RE.fullmatch(source_hash) is None:
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_HASH_INVALID",
                stage="source_admission",
                reason="An edit binding source hash is invalid.",
            )
        if not isinstance(target_span, Mapping):
            raise PatchAgentLoopError(
                "PATCH_AGENT_TARGET_SPAN_INVALID",
                stage="source_admission",
                reason="An edit binding target span is missing.",
            )
        start_line = target_span.get("start_line")
        end_line = target_span.get("end_line")
        if (
            type(start_line) is not int
            or type(end_line) is not int
            or start_line < 1
            or end_line < start_line
        ):
            raise PatchAgentLoopError(
                "PATCH_AGENT_TARGET_SPAN_INVALID",
                stage="source_admission",
                reason="An edit binding target span is invalid.",
            )
        try:
            source_bytes = source_path.read_bytes()
            line_count = len(source_bytes.decode("utf-8").splitlines())
        except (OSError, UnicodeDecodeError) as exc:
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_READ_FAILED",
                stage="source_admission",
                reason="A bound source could not be read as UTF-8.",
            ) from exc
        if hashlib.sha256(source_bytes).hexdigest() != source_hash:
            raise PatchAgentLoopError(
                "PATCH_AGENT_SOURCE_HASH_MISMATCH",
                stage="source_admission",
                reason="A Plan binding source hash does not match current source.",
            )
        if end_line > line_count:
            raise PatchAgentLoopError(
                "PATCH_AGENT_TARGET_SPAN_INVALID",
                stage="source_admission",
                reason="An edit binding target span exceeds current source.",
            )
        return _BoundSource(
            binding_id=binding_id,
            path=source_path,
            relative_path=pure_path.as_posix(),
            source_hash=source_hash,
            target_span={"start_line": start_line, "end_line": end_line},
        )

    def _assert_snapshot_current(self, *, code: str) -> None:
        for relative_path, expected_hash in self._source_hashes.items():
            source_path = self._source_paths[relative_path]
            try:
                observed_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            except OSError as exc:
                raise PatchAgentLoopError(
                    code,
                    stage="source_freshness",
                    reason="A Plan-bound source is unavailable.",
                ) from exc
            if observed_hash != expected_hash:
                raise PatchAgentLoopError(
                    code,
                    stage="source_freshness",
                    reason="A Plan-bound source changed after admission.",
                )


def run_patch_agent_loop(
    *,
    client: AgentTurnClient,
    initial_messages: tuple[AgentMessage, ...],
    final_response_format: AgentResponseFormat,
    source_inspector: PlanBoundSourceInspector,
    policy: PatchAgentLoopPolicy | None = None,
) -> PatchAgentLoopResult:
    """Run bounded source inspection turns and return final Patch content or a receipt."""

    selected_policy = policy or source_inspector.policy
    if selected_policy != source_inspector.policy:
        raise PatchAgentLoopError(
            "PATCH_AGENT_POLICY_MISMATCH",
            stage="loop_admission",
            reason="The loop and source inspector must use one policy instance value.",
        )
    if (
        not initial_messages
        or any(not isinstance(message, AgentMessage) for message in initial_messages)
        or not isinstance(final_response_format, AgentResponseFormat)
    ):
        raise PatchAgentLoopError(
            "PATCH_AGENT_LOOP_INPUT_INVALID",
            stage="loop_admission",
            reason="Initial messages and a final response format are required.",
        )

    provider = str(getattr(client, "provider", "") or "unknown")
    model = str(getattr(client, "model", "") or "unknown")
    usage_by_turn: list[dict[str, object]] = []
    tool_call_trace: list[dict[str, object]] = []
    observation_trace: list[dict[str, object]] = []
    observations: list[PatchSourceObservation] = []
    inspected_binding_ids: set[str] = set()
    seen_tool_call_ids: set[str] = set()
    total_observation_bytes = 0
    tool_rounds_used = 0
    pending_response: AgentTurnResponse | None = None
    pending_observation: PatchSourceObservation | None = None
    force_final = False

    for turn_index in range(1, selected_policy.max_total_model_turns + 1):
        try:
            source_inspector.validate_snapshot()
        except PatchAgentLoopError as exc:
            return _loop_result(
                status="blocked",
                final_content=None,
                provider=provider,
                model=model,
                model_turns_used=turn_index - 1,
                tool_rounds_used=tool_rounds_used,
                total_observation_bytes=total_observation_bytes,
                usage_by_turn=usage_by_turn,
                tool_call_trace=tool_call_trace,
                observation_trace=observation_trace,
                termination=_termination(exc.code, exc.reason, turn_index - 1),
            )

        remaining_binding_ids = tuple(
            binding_id
            for binding_id in source_inspector.available_binding_ids
            if binding_id not in inspected_binding_ids
        )
        must_finish = (
            force_final
            or tool_rounds_used >= selected_policy.max_tool_rounds
            or (
                selected_policy.finalize_after_first_observation
                and tool_rounds_used >= 1
            )
            or not remaining_binding_ids
        )
        prior_observations = (
            observations[:-1] if pending_observation is not None else observations
        )
        state_message = _loop_state_message(
            policy=selected_policy,
            source_inspector=source_inspector,
            prior_observations=prior_observations,
            model_turns_used=turn_index - 1,
            tool_rounds_used=tool_rounds_used,
            force_final=must_finish,
            final_response_format=final_response_format,
        )
        tool_results = (
            (
                AgentToolResult(
                    call_id=pending_response.tool_calls[0].call_id,
                    name=pending_response.tool_calls[0].name,
                    output=pending_observation.model_view(),
                ),
            )
            if pending_response is not None and pending_observation is not None
            else ()
        )
        request = AgentTurnRequest(
            messages=(*initial_messages, state_message),
            tools=(
                ()
                if must_finish
                else (
                    _source_tool_definition(
                        source_inspector,
                        binding_ids=remaining_binding_ids,
                    ),
                )
            ),
            tool_choice=(
                "none"
                if must_finish
                else "required"
                if turn_index == 1 and tool_rounds_used == 0
                else "auto"
            ),
            parallel_tool_calls=False,
            response_format=final_response_format if must_finish else None,
            tool_results=tool_results,
            tool_result_insert_index=(len(initial_messages) if tool_results else None),
            provider_state=(pending_response.provider_state if tool_results else None),
            temperature=0.0,
        )
        try:
            response = client.complete_turn(request)
        except AgentTurnProviderError as exc:
            usage_by_turn.append(
                {
                    "turn_index": turn_index,
                    "provider": provider,
                    "model": model,
                    "request_id": None,
                    "stop_reason": None,
                    "usage": None,
                    "usage_available": False,
                }
            )
            return _loop_result(
                status="blocked",
                final_content=None,
                provider=provider,
                model=model,
                model_turns_used=turn_index,
                tool_rounds_used=tool_rounds_used,
                total_observation_bytes=total_observation_bytes,
                usage_by_turn=usage_by_turn,
                tool_call_trace=tool_call_trace,
                observation_trace=observation_trace,
                termination=_termination(
                    "PATCH_AGENT_PROVIDER_TURN_FAILED",
                    str(exc) or "The Patch Agent provider turn failed.",
                    turn_index,
                    provider_diagnostic=exc.diagnostic,
                ),
            )
        if not isinstance(response, AgentTurnResponse):
            return _loop_result(
                status="blocked",
                final_content=None,
                provider=provider,
                model=model,
                model_turns_used=turn_index,
                tool_rounds_used=tool_rounds_used,
                total_observation_bytes=total_observation_bytes,
                usage_by_turn=usage_by_turn,
                tool_call_trace=tool_call_trace,
                observation_trace=observation_trace,
                termination=_termination(
                    "PATCH_AGENT_RESPONSE_INVALID",
                    "The Patch Agent response type is invalid.",
                    turn_index,
                ),
            )
        provider = response.provider
        model = response.model
        usage_by_turn.append(_usage_record(turn_index, response))
        pending_response = None
        pending_observation = None

        if len(response.tool_calls) > 1:
            code = "PATCH_AGENT_PARALLEL_TOOL_CALLS_FORBIDDEN"
            for call in response.tool_calls:
                tool_call_trace.append(
                    _tool_trace(call, turn_index=turn_index, status="rejected", code=code)
                )
            return _loop_result(
                status="blocked",
                final_content=None,
                provider=provider,
                model=model,
                model_turns_used=turn_index,
                tool_rounds_used=tool_rounds_used,
                total_observation_bytes=total_observation_bytes,
                usage_by_turn=usage_by_turn,
                tool_call_trace=tool_call_trace,
                observation_trace=observation_trace,
                termination=_termination(
                    code,
                    "Only one source-inspection tool call is allowed per turn.",
                    turn_index,
                ),
            )

        if response.tool_calls:
            call = response.tool_calls[0]
            code: str | None = None
            reason = ""
            if type(call.call_id) is not str or not call.call_id:
                code = "PATCH_AGENT_TOOL_CALL_ID_INVALID"
                reason = "The provider tool call id is missing."
            elif call.name != PATCH_SOURCE_INSPECTION_TOOL_NAME:
                code = "PATCH_AGENT_UNKNOWN_TOOL"
                reason = "The model requested an unregistered Patch tool."
            elif tool_rounds_used >= selected_policy.max_tool_rounds:
                code = "PATCH_AGENT_TOOL_ROUND_BUDGET_EXHAUSTED"
                reason = "The fixed source-inspection tool-round budget was exhausted."
            elif turn_index >= selected_policy.max_total_model_turns:
                code = "PATCH_AGENT_MODEL_TURN_BUDGET_EXHAUSTED"
                reason = "No model turn remains to consume another tool observation."
            elif (
                set(call.arguments) != {"binding_id"}
                or type(call.arguments.get("binding_id")) is not str
                or not call.arguments["binding_id"]
            ):
                code = "PATCH_AGENT_TOOL_ARGUMENTS_INVALID"
                reason = "The source-inspection tool accepts only one binding_id."
            else:
                binding_id = str(call.arguments["binding_id"])
                if binding_id in inspected_binding_ids:
                    code = "PATCH_AGENT_REPEATED_TOOL_CALL"
                    reason = "The same Plan binding cannot be inspected twice."
                elif call.call_id in seen_tool_call_ids:
                    code = "PATCH_AGENT_TOOL_CALL_ID_REUSED"
                    reason = "The provider reused a tool call id."
                elif binding_id not in source_inspector.available_binding_ids:
                    code = "PATCH_AGENT_BINDING_UNKNOWN"
                    reason = "The requested binding id is not selected by the Plan."
            if code is not None:
                tool_call_trace.append(
                    _tool_trace(call, turn_index=turn_index, status="rejected", code=code)
                )
                return _loop_result(
                    status="blocked",
                    final_content=None,
                    provider=provider,
                    model=model,
                    model_turns_used=turn_index,
                    tool_rounds_used=tool_rounds_used,
                    total_observation_bytes=total_observation_bytes,
                    usage_by_turn=usage_by_turn,
                    tool_call_trace=tool_call_trace,
                    observation_trace=observation_trace,
                    termination=_termination(code, reason, turn_index),
                )

            binding_id = str(call.arguments["binding_id"])
            seen_tool_call_ids.add(call.call_id)
            tool_rounds_used += 1
            try:
                observation = source_inspector.inspect(
                    binding_id=binding_id,
                    observation_id=f"patch-observation-{tool_rounds_used:03d}",
                )
            except PatchAgentLoopError as exc:
                tool_call_trace.append(
                    _tool_trace(
                        call,
                        turn_index=turn_index,
                        status="rejected",
                        code=exc.code,
                        dispatch_started=True,
                    )
                )
                return _loop_result(
                    status="blocked",
                    final_content=None,
                    provider=provider,
                    model=model,
                    model_turns_used=turn_index,
                    tool_rounds_used=tool_rounds_used,
                    total_observation_bytes=total_observation_bytes,
                    usage_by_turn=usage_by_turn,
                    tool_call_trace=tool_call_trace,
                    observation_trace=observation_trace,
                    termination=_termination(exc.code, exc.reason, turn_index),
                )
            total_observation_bytes += observation.model_payload_bytes
            admitted_to_model = (
                total_observation_bytes <= selected_policy.max_observation_bytes
            )
            observation_trace.append(
                _observation_trace(
                    observation,
                    turn_index=turn_index,
                    admitted_to_model=admitted_to_model,
                )
            )
            if not admitted_to_model:
                code = "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED"
                tool_call_trace.append(
                    _tool_trace(
                        call,
                        turn_index=turn_index,
                        status="rejected",
                        code=code,
                        dispatch_started=True,
                    )
                )
                return _loop_result(
                    status="blocked",
                    final_content=None,
                    provider=provider,
                    model=model,
                    model_turns_used=turn_index,
                    tool_rounds_used=tool_rounds_used,
                    total_observation_bytes=total_observation_bytes,
                    usage_by_turn=usage_by_turn,
                    tool_call_trace=tool_call_trace,
                    observation_trace=observation_trace,
                    termination=_termination(
                        code,
                        "The cumulative source-observation byte budget was exhausted.",
                        turn_index,
                    ),
                )
            tool_call_trace.append(
                _tool_trace(
                    call,
                    turn_index=turn_index,
                    status="accepted",
                    dispatch_started=True,
                )
            )
            inspected_binding_ids.add(binding_id)
            observations.append(observation)
            pending_response = response
            pending_observation = observation
            continue

        content = response.content
        if turn_index == 1 and tool_rounds_used == 0:
            return _loop_result(
                status="blocked",
                final_content=None,
                provider=provider,
                model=model,
                model_turns_used=turn_index,
                tool_rounds_used=tool_rounds_used,
                total_observation_bytes=total_observation_bytes,
                usage_by_turn=usage_by_turn,
                tool_call_trace=tool_call_trace,
                observation_trace=observation_trace,
                termination=_termination(
                    "PATCH_AGENT_SOURCE_INSPECTION_REQUIRED",
                    "The first Patch Agent turn must inspect one Plan binding.",
                    turn_index,
                ),
            )
        if isinstance(content, str) and content.strip():
            try:
                source_inspector.validate_snapshot()
            except PatchAgentLoopError as exc:
                return _loop_result(
                    status="blocked",
                    final_content=None,
                    provider=provider,
                    model=model,
                    model_turns_used=turn_index,
                    tool_rounds_used=tool_rounds_used,
                    total_observation_bytes=total_observation_bytes,
                    usage_by_turn=usage_by_turn,
                    tool_call_trace=tool_call_trace,
                    observation_trace=observation_trace,
                    termination=_termination(exc.code, exc.reason, turn_index),
                )
            return _loop_result(
                status="completed",
                final_content=content,
                final_request=request,
                provider=provider,
                model=model,
                model_turns_used=turn_index,
                tool_rounds_used=tool_rounds_used,
                total_observation_bytes=total_observation_bytes,
                usage_by_turn=usage_by_turn,
                tool_call_trace=tool_call_trace,
                observation_trace=observation_trace,
                termination=_termination(
                    "PATCH_AGENT_MODEL_FINISHED",
                    "The model returned final Patch content.",
                    turn_index,
                    status="completed",
                ),
            )

        if turn_index >= selected_policy.max_total_model_turns:
            return _loop_result(
                status="blocked",
                final_content=None,
                provider=provider,
                model=model,
                model_turns_used=turn_index,
                tool_rounds_used=tool_rounds_used,
                total_observation_bytes=total_observation_bytes,
                usage_by_turn=usage_by_turn,
                tool_call_trace=tool_call_trace,
                observation_trace=observation_trace,
                termination=_termination(
                    "PATCH_AGENT_MODEL_TURN_BUDGET_EXHAUSTED",
                    "The model-turn budget ended without final Patch content.",
                    turn_index,
                ),
            )
        force_final = True

    raise AssertionError("Patch Agent loop exceeded its fixed model-turn bound.")


def _source_tool_definition(
    inspector: PlanBoundSourceInspector,
    *,
    binding_ids: tuple[str, ...] | None = None,
) -> AgentToolDefinition:
    allowed_binding_ids = binding_ids or inspector.available_binding_ids
    return AgentToolDefinition(
        name=PATCH_SOURCE_INSPECTION_TOOL_NAME,
        description=(
            "Read a bounded current-source excerpt for one exact ImplementationPlan "
            "edit binding. Select only a listed binding_id; paths are not accepted."
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "required": ["binding_id"],
            "properties": {
                "binding_id": {
                    "type": "string",
                    "enum": list(allowed_binding_ids),
                }
            },
        },
        strict=True,
    )


def _loop_state_message(
    *,
    policy: PatchAgentLoopPolicy,
    source_inspector: PlanBoundSourceInspector,
    prior_observations: list[PatchSourceObservation],
    model_turns_used: int,
    tool_rounds_used: int,
    force_final: bool,
    final_response_format: AgentResponseFormat,
) -> AgentMessage:
    return AgentMessage(
        role="user",
        content={
            "message_type": "patch_agent_loop_state",
            "allowed_binding_ids": list(source_inspector.available_binding_ids),
            "source_snapshot_sha256": source_inspector.source_snapshot_sha256,
            "prior_observations": [
                observation.model_view() for observation in prior_observations
            ],
            "budget_state": {
                "model_turns_used": model_turns_used,
                "remaining_model_turns": policy.max_total_model_turns
                - model_turns_used,
                "tool_rounds_used": tool_rounds_used,
                "remaining_tool_rounds": policy.max_tool_rounds
                - tool_rounds_used,
            },
            "required_next_action": "finish" if force_final else "inspect_or_finish",
            "final_response_contract": {
                "name": final_response_format.name,
                "description": final_response_format.description,
                "schema_sha256": _canonical_sha256(
                    final_response_format.schema
                ),
            },
        },
    )


def _usage_record(turn_index: int, response: AgentTurnResponse) -> dict[str, object]:
    return {
        "turn_index": turn_index,
        "provider": response.provider,
        "model": response.model,
        "request_id": response.request_id,
        "stop_reason": response.stop_reason,
        "usage": response.usage.to_dict(),
        **(
            {"provider_diagnostic": deepcopy(response.provider_diagnostic)}
            if response.provider_diagnostic is not None else {}
        ),
    }


def _tool_trace(
    call: AgentToolCall,
    *,
    turn_index: int,
    status: Literal["accepted", "rejected"],
    code: str | None = None,
    dispatch_started: bool | None = None,
) -> dict[str, object]:
    trace: dict[str, object] = {
        "turn_index": turn_index,
        "tool_call_id": call.call_id,
        "tool": call.name,
        "binding_id": (
            call.arguments.get("binding_id")
            if isinstance(call.arguments.get("binding_id"), str)
            else None
        ),
        "arguments_sha256": _canonical_sha256(call.arguments),
        "status": status,
    }
    if dispatch_started is not None:
        trace["dispatch_started"] = dispatch_started
    if code is not None:
        trace["error_code"] = code
    return trace


def _observation_trace(
    observation: PatchSourceObservation,
    *,
    turn_index: int,
    admitted_to_model: bool,
) -> dict[str, object]:
    return {
        "turn_index": turn_index,
        "observation_id": observation.observation_id,
        "binding_id": observation.binding_id,
        "source_ref": observation.source_ref,
        "source_hash": observation.source_hash,
        "source_snapshot_sha256": observation.source_snapshot_sha256,
        "observation_sha256": observation.payload_sha256,
        "model_payload_bytes": observation.model_payload_bytes,
        "admitted_to_model": admitted_to_model,
    }


def _termination(
    code: str,
    reason: str,
    turn_index: int,
    *,
    status: Literal["completed", "blocked"] = "blocked",
    provider_diagnostic: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": status,
        "code": code,
        "reason": reason,
        "turn_index": turn_index,
    }
    if provider_diagnostic:
        result["provider_diagnostic"] = deepcopy(dict(provider_diagnostic))
    return result


def _loop_result(
    *,
    status: Literal["completed", "blocked"],
    final_content: str | None,
    provider: str,
    model: str,
    model_turns_used: int,
    tool_rounds_used: int,
    total_observation_bytes: int,
    usage_by_turn: list[dict[str, object]],
    tool_call_trace: list[dict[str, object]],
    observation_trace: list[dict[str, object]],
    termination: dict[str, object],
    final_request: AgentTurnRequest | None = None,
) -> PatchAgentLoopResult:
    return PatchAgentLoopResult(
        status=status,
        final_content=final_content,
        provider=provider,
        model=model,
        model_turns_used=model_turns_used,
        tool_rounds_used=tool_rounds_used,
        total_observation_bytes=total_observation_bytes,
        usage_by_turn=tuple(deepcopy(item) for item in usage_by_turn),
        tool_call_trace=tuple(deepcopy(item) for item in tool_call_trace),
        observation_trace=tuple(deepcopy(item) for item in observation_trace),
        termination=deepcopy(termination),
        final_request=deepcopy(final_request),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
