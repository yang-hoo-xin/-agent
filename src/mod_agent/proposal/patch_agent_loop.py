"""Bounded Plan-bound source inspection loop for Patch generation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolCall,
    AgentToolDefinition,
    AgentToolExchange,
    AgentToolResult,
    AgentTurnClient,
    AgentTurnProviderError,
    AgentTurnRequest,
    AgentTurnResponse,
)

PATCH_SOURCE_INSPECTION_TOOL_NAME = "inspect_plan_binding_source"
PATCH_UPSTREAM_REQUEST_TOOL_NAME = "request_patch_upstream"
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
    enable_supporting_reads: bool = False
    require_source_inspection: bool = True
    allow_upstream_request: bool = False
    allow_batched_reads: bool = False
    max_tool_rounds: int = field(default=3, init=False)
    max_total_model_turns: int = 5

    def __post_init__(self) -> None:
        if any(type(getattr(self, name)) is not bool for name in (
            "finalize_after_first_observation", "enable_supporting_reads",
            "require_source_inspection", "allow_upstream_request", "allow_batched_reads",
        )):
            raise PatchAgentLoopError(
                "PATCH_AGENT_POLICY_INVALID",
                stage="policy",
                reason="Patch strategy switches must be boolean values.",
            )
        if type(self.max_total_model_turns) is not int or not 1 <= self.max_total_model_turns <= 5:
            raise PatchAgentLoopError("PATCH_AGENT_POLICY_INVALID", stage="policy",
                reason="The selected model-turn limit must be between one and the shared maximum of five.")
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
    target_span: dict[str, int] | None
    excerpt_span: dict[str, int] | None
    excerpt: str
    truncated: bool
    payload_sha256: str
    model_payload_bytes: int
    registered_evidence_identity: Mapping[str, str] | None = None

    def model_view(self) -> dict[str, object]:
        """Return the bounded ref-first payload visible to the model."""

        return {
            "observation_id": self.observation_id,
            "binding_id": self.binding_id,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "target_span": dict(self.target_span) if self.target_span is not None else None,
            "excerpt_span": dict(self.excerpt_span) if self.excerpt_span is not None else None,
            "excerpt": self.excerpt,
            "truncated": self.truncated,
            "observation_sha256": self.payload_sha256,
            **(dict(self.registered_evidence_identity) if self.registered_evidence_identity is not None else {}),
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
    tool_availability_trace: tuple[dict[str, object], ...] = ()

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
            "tool_availability_trace": [deepcopy(item) for item in self.tool_availability_trace],
        }


@dataclass(frozen=True)
class _BoundSource:
    binding_id: str
    path: Path
    relative_path: str
    source_hash: str
    target_span: dict[str, int]


@dataclass(frozen=True)
class _RegisteredApiEvidence:
    """Immutable registered Evidence content; its source file is never opened here."""

    binding_id: str
    source_hash: str
    excerpt: str
    evidence_id: str
    evidence_item_sha256: str
    excerpt_sha256: str


class PlanBoundSourceInspector:
    """Read current registered source without promoting read scope into edit authority."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        implementation_plan: Mapping[str, Any],
        policy: PatchAgentLoopPolicy,
        evidence_pack: Mapping[str, Any] | None = None,
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

        edit_source_hashes = dict(source_hashes)
        read_binding_order = list(binding_order)
        registered_api: dict[str, _RegisteredApiEvidence] = {}
        if policy.enable_supporting_reads:
            raw_supporting = registry.get("supporting_bindings", [])
            if not isinstance(raw_supporting, (list, tuple)):
                raise PatchAgentLoopError("PATCH_AGENT_PLAN_BINDINGS_INVALID",
                    stage="source_admission", reason="Supporting bindings must be a list.")
            raw_items = evidence_pack.get("items") if isinstance(evidence_pack, Mapping) else None
            if raw_supporting and not isinstance(raw_items, (list, tuple)):
                raise PatchAgentLoopError("PATCH_AGENT_SUPPORTING_EVIDENCE_REQUIRED",
                    stage="source_admission", reason="Supporting reads require their EvidencePack.")
            evidence_by_id: dict[str, Mapping[str, Any]] = {}
            for item in raw_items or ():
                evidence_id = item.get("evidence_id") if isinstance(item, Mapping) else None
                if type(evidence_id) is not str or not evidence_id or evidence_id in evidence_by_id:
                    raise PatchAgentLoopError("PATCH_AGENT_SUPPORTING_EVIDENCE_MISMATCH",
                        stage="source_admission", reason="Evidence identities must be present and unique.")
                evidence_by_id[evidence_id] = item
            for raw_support in raw_supporting:
                if not isinstance(raw_support, Mapping):
                    raise PatchAgentLoopError("PATCH_AGENT_PLAN_BINDINGS_INVALID",
                        stage="source_admission", reason="Every supporting binding must be an object.")
                if raw_support.get("source_type") not in {"target_source", "decompiled_api"}:
                    continue
                item = evidence_by_id.get(raw_support.get("evidence_id"))
                if item is None or any(raw_support.get(plan_key) != item.get(evidence_key)
                    for plan_key, evidence_key in (("source_path", "source_path"),
                        ("source_type", "source_type"), ("target_span", "span"),
                        ("target_symbol", "symbol"))):
                    raise PatchAgentLoopError("PATCH_AGENT_SUPPORTING_EVIDENCE_MISMATCH",
                        stage="source_admission", reason="Supporting source identity differs from its exact Evidence item.")
                if item["source_type"] == "decompiled_api":
                    binding_id = raw_support.get("binding_id")
                    source_hash = item.get("source_hash")
                    excerpt = item.get("excerpt")
                    if (type(binding_id) is not str or not binding_id or binding_id in read_binding_order
                        or type(source_hash) is not str or re.fullmatch(r"[0-9a-fA-F]{64}", source_hash) is None
                        or type(excerpt) is not str or not excerpt
                        or (item.get("file_hash") is not None and item["file_hash"] != source_hash)):
                        raise PatchAgentLoopError("PATCH_AGENT_REGISTERED_API_EVIDENCE_INVALID", stage="source_admission",
                            reason="Registered API content requires an exact source identity and nonempty excerpt.")
                    registered_api[binding_id] = _RegisteredApiEvidence(binding_id=binding_id,
                        source_hash=source_hash, excerpt=excerpt, evidence_id=item["evidence_id"],
                        evidence_item_sha256=_canonical_sha256(item),
                        excerpt_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest())
                    read_binding_order.append(binding_id)
                    continue
                binding = self._admit_binding(root, {
                    "binding_id": raw_support.get("binding_id"),
                    "canonical_target_path": item.get("source_path"),
                    "source_hash": item.get("source_hash"), "target_span": item.get("span"),
                })
                if binding.binding_id in read_binding_order:
                    raise PatchAgentLoopError("PATCH_AGENT_PLAN_BINDINGS_INVALID",
                        stage="source_admission", reason="Read binding ids must be unique across edit and supporting scopes.")
                if binding.relative_path in source_hashes and source_hashes[binding.relative_path] != binding.source_hash:
                    raise PatchAgentLoopError("PATCH_AGENT_PLAN_SOURCE_IDENTITY_CONFLICT",
                        stage="source_admission", reason="Read and edit source identities conflict.")
                bindings[binding.binding_id] = binding
                read_binding_order.append(binding.binding_id)
                source_hashes[binding.relative_path] = binding.source_hash
                source_paths[binding.relative_path] = binding.path

        self.workspace_root = root
        self.policy = policy
        self._bindings = bindings
        self._registered_api = registered_api
        self._binding_order = tuple(binding_order)
        self._read_binding_order = tuple(read_binding_order)
        self._source_hashes = source_hashes
        self._source_paths = source_paths
        self._assert_snapshot_current(code="PATCH_AGENT_SOURCE_HASH_MISMATCH")
        self.source_snapshot_sha256 = _canonical_sha256(
            [
                {"source_path": relative_path, "source_hash": edit_source_hashes[relative_path]}
                for relative_path in sorted(edit_source_hashes)
            ]
        )
        self.read_source_snapshot_sha256 = _canonical_sha256([
            {"source_path": path, "source_hash": source_hashes[path]} for path in sorted(source_hashes)
        ])

    @property
    def available_binding_ids(self) -> tuple[str, ...]:
        return self._binding_order

    @property
    def available_read_binding_ids(self) -> tuple[str, ...]:
        return self._read_binding_order

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
        if type(binding_id) is not str or binding_id not in self._read_binding_order:
            raise PatchAgentLoopError(
                "PATCH_AGENT_BINDING_UNKNOWN",
                stage="tool_admission",
                reason="The requested binding id is not in the admitted Plan read scope.",
            )
        if type(observation_id) is not str or not observation_id:
            raise PatchAgentLoopError(
                "PATCH_AGENT_OBSERVATION_ID_INVALID",
                stage="tool_admission",
                reason="The tool observation id must be non-empty text.",
            )
        self.validate_snapshot()
        if binding_id in self._registered_api:
            return self._inspect_registered_api(binding_id=binding_id, observation_id=observation_id)
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

    def _inspect_registered_api(self, *, binding_id: str, observation_id: str) -> PatchSourceObservation:
        item = self._registered_api[binding_id]
        identity = {
            "observation_kind": "registered_api_evidence",
            "source_identity_status": "registered_not_live_revalidated",
            "evidence_id": item.evidence_id,
            "evidence_item_sha256": item.evidence_item_sha256,
            "excerpt_sha256": item.excerpt_sha256,
        }
        base_payload = {
            "observation_id": observation_id, "binding_id": binding_id,
            "source_ref": f"binding://{binding_id}", "source_hash": item.source_hash,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "target_span": None, "excerpt_span": None,
            "excerpt": item.excerpt, "truncated": False, **identity,
        }
        payload_hash = _canonical_sha256(base_payload)
        return PatchSourceObservation(observation_id=observation_id, binding_id=binding_id,
            source_ref=f"binding://{binding_id}", source_hash=item.source_hash,
            source_snapshot_sha256=self.source_snapshot_sha256, target_span=None, excerpt_span=None,
            excerpt=item.excerpt, truncated=False, payload_sha256=payload_hash,
            model_payload_bytes=len(_canonical_json({**base_payload, "observation_sha256": payload_hash}).encode("utf-8")),
            registered_evidence_identity=identity)

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
    resume_request: AgentTurnRequest | None = None,
    consumed_model_turns: int = 0,
    consumed_tool_rounds: int = 0,
    consumed_observation_bytes: int = 0,
    reserve_model_turns: int = 0,
) -> PatchAgentLoopResult:
    """Run bounded source inspection turns and return final Patch content or a receipt."""

    selected_policy = policy or source_inspector.policy
    for value in (consumed_model_turns, consumed_tool_rounds, consumed_observation_bytes, reserve_model_turns):
        if type(value) is not int or value < 0:
            raise PatchAgentLoopError("PATCH_AGENT_LOOP_BUDGET_INVALID", stage="loop_admission",
                reason="Consumed and reserved budget counters must be non-negative integers.")
    if consumed_model_turns > selected_policy.max_total_model_turns or consumed_tool_rounds > selected_policy.max_tool_rounds:
        raise PatchAgentLoopError("PATCH_AGENT_LOOP_BUDGET_INVALID", stage="loop_admission",
            reason="Consumed counters exceed the shared policy.")
    if resume_request is not None and not isinstance(resume_request, AgentTurnRequest):
        raise PatchAgentLoopError("PATCH_AGENT_LOOP_INPUT_INVALID", stage="loop_admission",
            reason="Resuming requires an AgentTurnRequest.")
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
    observations: list[PatchSourceObservation | Mapping[str, object]] = []
    tool_availability_trace: list[dict[str, object]] = []
    inspected_binding_ids: set[str] = set()
    seen_tool_call_ids: set[str] = set()
    rejected_read_batches: set[str] = set()
    total_observation_bytes = consumed_observation_bytes
    tool_rounds_used = consumed_tool_rounds
    allowed_model_end = selected_policy.max_total_model_turns - reserve_model_turns
    base_request = deepcopy(resume_request) if resume_request is not None else AgentTurnRequest(messages=initial_messages)
    old_states = [message.content for message in base_request.messages
        if _is_loop_state(message)]
    for state in old_states:
        for observation in state.get("prior_observations", []):
            if isinstance(observation, Mapping):
                observations.append(deepcopy(observation))
    retained_exchanges = list(base_request.historical_tool_exchanges)
    if base_request.tool_results:
        retained_exchanges.append(AgentToolExchange(base_request.tool_results, base_request.provider_state,
            base_request.tool_result_insert_index if base_request.tool_result_insert_index is not None else len(base_request.messages)))
    for exchange in retained_exchanges:
        rejected_bindings = [result.output.get("binding_id") for result in exchange.tool_results
            if isinstance(result.output, Mapping)
            and result.output.get("error_code") == "PATCH_AGENT_TOOL_BATCH_BUDGET_EXCEEDED"]
        if rejected_bindings and all(isinstance(binding, str) for binding in rejected_bindings):
            rejected_read_batches.add(_canonical_sha256(sorted(rejected_bindings)))
        for tool_result in exchange.tool_results:
            seen_tool_call_ids.add(tool_result.call_id)
            if (tool_result.name == PATCH_SOURCE_INSPECTION_TOOL_NAME and isinstance(tool_result.output, Mapping)
                and isinstance(tool_result.output.get("observation_sha256"), str)):
                binding_id = tool_result.output.get("binding_id")
                if isinstance(binding_id, str):
                    inspected_binding_ids.add(binding_id)
    for observation in observations:
        binding_id = observation.get("binding_id")
        if isinstance(binding_id, str):
            inspected_binding_ids.add(binding_id)
    if resume_request is not None:
        prior_model_floor = max((state.get("budget_state", {}).get("model_turns_used", 0) + 1
            for state in old_states), default=0)
        if consumed_model_turns < prior_model_floor or consumed_tool_rounds < len(inspected_binding_ids):
            raise PatchAgentLoopError("PATCH_AGENT_LOOP_BUDGET_INVALID", stage="loop_admission",
                reason="Resume counters cannot discard calls or inspections recorded in the prior request.")
    base_request = _without_loop_states(base_request)

    def result_for_segment(**kwargs: Any) -> PatchAgentLoopResult:
        kwargs["model_turns_used"] -= consumed_model_turns
        kwargs["tool_rounds_used"] -= consumed_tool_rounds
        kwargs["total_observation_bytes"] -= consumed_observation_bytes
        return replace(_loop_result(**kwargs), tool_availability_trace=tuple(deepcopy(tool_availability_trace)))
    pending_response: AgentTurnResponse | None = None
    pending_observation: PatchSourceObservation | None = None
    pending_tool_results: tuple[AgentToolResult, ...] = ()
    force_final = False

    if consumed_model_turns >= allowed_model_end or consumed_observation_bytes > selected_policy.max_observation_bytes:
        return result_for_segment(status="blocked", final_content=None, provider=provider, model=model,
            model_turns_used=consumed_model_turns, tool_rounds_used=tool_rounds_used,
            total_observation_bytes=total_observation_bytes, usage_by_turn=usage_by_turn,
            tool_call_trace=tool_call_trace, observation_trace=observation_trace,
            termination=_termination("PATCH_AGENT_MODEL_TURN_BUDGET_EXHAUSTED" if consumed_model_turns >= allowed_model_end
                else "PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED", "No shared budget remains for this segment.", consumed_model_turns))

    for turn_index in range(consumed_model_turns + 1, allowed_model_end + 1):
        try:
            source_inspector.validate_snapshot()
        except PatchAgentLoopError as exc:
            return result_for_segment(
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
            for binding_id in source_inspector.available_read_binding_ids
            if binding_id not in inspected_binding_ids
        )
        must_finish = (
            force_final
            or turn_index >= allowed_model_end
            or tool_rounds_used >= selected_policy.max_tool_rounds
            or (
                selected_policy.finalize_after_first_observation
                and tool_rounds_used >= 1
            )
            or not remaining_binding_ids
        )
        native_observation_ids = {
            result.output.get("observation_id")
            for exchange in base_request.historical_tool_exchanges
            for result in exchange.tool_results
            if isinstance(result.output, Mapping)
        }
        native_observation_ids.update(result.output.get("observation_id")
            for result in base_request.tool_results if isinstance(result.output, Mapping))
        if pending_observation is not None:
            native_observation_ids.add(pending_observation.observation_id)
        native_observation_ids.update(result.output.get("observation_id") for result in pending_tool_results
            if isinstance(result.output, Mapping))
        # Keep older non-native observations, but do not duplicate retained native payloads.
        prior_observations = [observation for observation in observations
            if (observation.observation_id if isinstance(observation, PatchSourceObservation)
                else observation.get("observation_id")) not in native_observation_ids]
        state_message = _loop_state_message(
            policy=selected_policy,
            source_inspector=source_inspector,
            prior_observations=prior_observations,
            model_turns_used=turn_index - 1,
            tool_rounds_used=tool_rounds_used,
            force_final=must_finish,
            final_response_format=final_response_format,
            reserve_model_turns=reserve_model_turns,
        )
        tool_results = pending_tool_results or (
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
        history = base_request.historical_tool_exchanges
        if tool_results and base_request.tool_results:
            history = (*history, AgentToolExchange(base_request.tool_results, base_request.provider_state,
                base_request.tool_result_insert_index if base_request.tool_result_insert_index is not None else len(base_request.messages)))
        available_tools = (
            () if must_finish else (_source_tool_definition(source_inspector, binding_ids=remaining_binding_ids),)
        ) + ((_upstream_tool_definition(source_inspector),) if selected_policy.allow_upstream_request else ())
        request = AgentTurnRequest(
            messages=(*base_request.messages, state_message),
            tools=available_tools,
            tool_choice=(
                "none"
                if not available_tools
                else "required"
                if selected_policy.require_source_inspection and tool_rounds_used == 0
                else "auto"
            ),
            parallel_tool_calls=False,
            response_format=final_response_format if must_finish else None,
            tool_results=tool_results or base_request.tool_results,
            tool_result_insert_index=(len(base_request.messages) if tool_results else base_request.tool_result_insert_index),
            provider_state=(pending_response.provider_state if tool_results else base_request.provider_state),
            temperature=0.0,
            historical_tool_exchanges=history,
        )
        availability: dict[str, object] = {"turn_index": turn_index,
            "allowed_tools": [tool.name for tool in request.tools],
            "selection": "forbidden" if not request.tools else "allowed_not_selected"}
        tool_availability_trace.append(availability)
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
            return result_for_segment(
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
            return result_for_segment(
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
        if response.tool_calls:
            availability["selection"] = "selected" if request.tools else "forbidden_attempt"
        usage_by_turn.append(_usage_record(turn_index, response))
        pending_response = None
        pending_observation = None
        pending_tool_results = ()

        if len(response.tool_calls) > 1 and not selected_policy.allow_batched_reads:
            code = "PATCH_AGENT_PARALLEL_TOOL_CALLS_FORBIDDEN"
            for call in response.tool_calls:
                tool_call_trace.append(
                    _tool_trace(call, turn_index=turn_index, status="rejected", code=code)
                )
            return result_for_segment(
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

        if len(response.tool_calls) > 1:
            calls = response.tool_calls
            code, reason = _validate_read_batch(calls, source_inspector,
                inspected_binding_ids=inspected_binding_ids, seen_tool_call_ids=seen_tool_call_ids)
            if code is None and not any(tool.name == PATCH_SOURCE_INSPECTION_TOOL_NAME for tool in request.tools):
                code, reason = "PATCH_AGENT_TOOL_FORBIDDEN", "Source inspection is disabled for this turn."
            if code is not None:
                for call in calls:
                    tool_call_trace.append(_tool_trace(call, turn_index=turn_index,
                        status="rejected_not_executed", code=code, dispatch_started=False))
                return result_for_segment(status="blocked", final_content=None, provider=provider, model=model,
                    model_turns_used=turn_index, tool_rounds_used=tool_rounds_used,
                    total_observation_bytes=total_observation_bytes, usage_by_turn=usage_by_turn,
                    tool_call_trace=tool_call_trace, observation_trace=observation_trace,
                    termination=_termination(code, reason, turn_index))
            remaining_reads = selected_policy.max_tool_rounds - tool_rounds_used
            if len(calls) > remaining_reads:
                code = "PATCH_AGENT_TOOL_BATCH_BUDGET_EXCEEDED"
                batch_identity = _canonical_sha256(sorted(call.arguments["binding_id"] for call in calls))
                if rejected_read_batches:
                    code = ("PATCH_AGENT_REPEATED_TOOL_BATCH" if batch_identity in rejected_read_batches
                        else "PATCH_AGENT_TOOL_BATCH_BUDGET_RETRY_EXHAUSTED")
                    for call in calls:
                        tool_call_trace.append(_tool_trace(call, turn_index=turn_index,
                            status="rejected_not_executed", code=code, dispatch_started=False))
                    availability["selection"] = "rejected_not_executed"
                    return result_for_segment(status="blocked", final_content=None, provider=provider, model=model,
                        model_turns_used=turn_index, tool_rounds_used=tool_rounds_used,
                        total_observation_bytes=total_observation_bytes, usage_by_turn=usage_by_turn,
                        tool_call_trace=tool_call_trace, observation_trace=observation_trace,
                        termination=_termination(code, "One bounded batch-budget correction opportunity was already used.", turn_index))
                rejected_read_batches.add(batch_identity)
                results = tuple(AgentToolResult(call_id=call.call_id, name=call.name, output={
                    "status": "not_executed", "error_code": code, "reason": "budget_exceeded",
                    "binding_id": call.arguments["binding_id"], "requested_read_count": len(calls),
                    "remaining_read_count": remaining_reads,
                    "required_action": "Select no more than the remaining read count, or finish from existing context.",
                    "source_snapshot_sha256": source_inspector.source_snapshot_sha256,
                }) for call in calls)
                for call, result in zip(calls, results):
                    feedback_bytes = len(_canonical_json(result.output).encode("utf-8"))
                    total_observation_bytes += feedback_bytes
                    trace = _tool_trace(call, turn_index=turn_index, status="rejected_not_executed",
                        code=code, dispatch_started=False)
                    trace["feedback_payload_bytes"] = feedback_bytes
                    tool_call_trace.append(trace)
                availability["selection"] = "rejected_not_executed"
                if total_observation_bytes > selected_policy.max_observation_bytes:
                    return result_for_segment(status="blocked", final_content=None, provider=provider, model=model,
                        model_turns_used=turn_index, tool_rounds_used=tool_rounds_used,
                        total_observation_bytes=total_observation_bytes, usage_by_turn=usage_by_turn,
                        tool_call_trace=tool_call_trace, observation_trace=observation_trace,
                        termination=_termination("PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED",
                            "The bounded batch rejection feedback exceeds the observation budget.", turn_index))
                seen_tool_call_ids.update(call.call_id for call in calls)
                pending_response, pending_tool_results = response, results
                base_request = _without_loop_states(request)
                continue
            batch_results: list[AgentToolResult] = []
            for index, call in enumerate(calls):
                tool_rounds_used += 1
                seen_tool_call_ids.add(call.call_id)
                try:
                    observation = source_inspector.inspect(binding_id=call.arguments["binding_id"],
                        observation_id=f"patch-observation-{tool_rounds_used:03d}")
                    total_observation_bytes += observation.model_payload_bytes
                    admitted = total_observation_bytes <= selected_policy.max_observation_bytes
                    observation_trace.append(_observation_trace(observation, turn_index=turn_index, admitted_to_model=admitted))
                    if not admitted:
                        raise PatchAgentLoopError("PATCH_AGENT_OBSERVATION_BUDGET_EXHAUSTED", stage="tool_execution",
                            reason="The cumulative source-observation byte budget was exhausted.")
                except PatchAgentLoopError as exc:
                    availability["selection"] = "execution_failed"
                    tool_call_trace.append(_tool_trace(call, turn_index=turn_index, status="rejected",
                        code=exc.code, dispatch_started=True))
                    for remaining_call in calls[index + 1:]:
                        tool_call_trace.append(_tool_trace(remaining_call, turn_index=turn_index,
                            status="rejected_not_executed", code=exc.code, dispatch_started=False))
                    return result_for_segment(status="blocked", final_content=None, provider=provider, model=model,
                        model_turns_used=turn_index, tool_rounds_used=tool_rounds_used,
                        total_observation_bytes=total_observation_bytes, usage_by_turn=usage_by_turn,
                        tool_call_trace=tool_call_trace, observation_trace=observation_trace,
                        termination=_termination(exc.code, exc.reason, turn_index))
                inspected_binding_ids.add(call.arguments["binding_id"])
                observations.append(observation)
                batch_results.append(AgentToolResult(call_id=call.call_id, name=call.name, output=observation.model_view()))
                tool_call_trace.append(_tool_trace(call, turn_index=turn_index, status="accepted", dispatch_started=True))
            pending_response, pending_tool_results = response, tuple(batch_results)
            base_request = _without_loop_states(request)
            continue

        if response.tool_calls:
            call = response.tool_calls[0]
            if call.name == PATCH_UPSTREAM_REQUEST_TOOL_NAME:
                code, upstream = _validate_upstream_request(call, source_inspector, selected_policy,
                    tool_available=any(tool.name == PATCH_UPSTREAM_REQUEST_TOOL_NAME for tool in request.tools))
                tool_call_trace.append(_tool_trace(call, turn_index=turn_index,
                    status="accepted" if upstream is not None else "rejected", code=code,
                    dispatch_started=False))
                termination = _termination(code, "The model requested upstream assessment; no route or authority was granted.", turn_index)
                if upstream is not None:
                    termination["upstream_request"] = upstream
                return result_for_segment(status="blocked", final_content=None, provider=provider, model=model,
                    model_turns_used=turn_index, tool_rounds_used=tool_rounds_used,
                    total_observation_bytes=total_observation_bytes, usage_by_turn=usage_by_turn,
                    tool_call_trace=tool_call_trace, observation_trace=observation_trace, termination=termination,
                    final_request=request)
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
            elif turn_index >= allowed_model_end:
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
                elif binding_id not in source_inspector.available_read_binding_ids:
                    code = "PATCH_AGENT_BINDING_UNKNOWN"
                    reason = "The requested binding id is not selected by the Plan."
                elif not any(tool.name == PATCH_SOURCE_INSPECTION_TOOL_NAME for tool in request.tools):
                    code = "PATCH_AGENT_TOOL_FORBIDDEN"
                    reason = "Source inspection is disabled for this turn."
            if code is not None:
                tool_call_trace.append(
                    _tool_trace(call, turn_index=turn_index, status="rejected", code=code)
                )
                return result_for_segment(
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
                availability["selection"] = "execution_failed"
                tool_call_trace.append(
                    _tool_trace(
                        call,
                        turn_index=turn_index,
                        status="rejected",
                        code=exc.code,
                        dispatch_started=True,
                    )
                )
                return result_for_segment(
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
                return result_for_segment(
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
            base_request = _without_loop_states(request)
            continue

        content = response.content
        if selected_policy.require_source_inspection and tool_rounds_used == 0:
            return result_for_segment(
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
                return result_for_segment(
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
            return result_for_segment(
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

        if turn_index >= allowed_model_end:
            return result_for_segment(
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


def _validate_read_batch(calls: tuple[AgentToolCall, ...], inspector: PlanBoundSourceInspector,
    *, inspected_binding_ids: set[str], seen_tool_call_ids: set[str]) -> tuple[str | None, str]:
    if any(call.name == PATCH_UPSTREAM_REQUEST_TOOL_NAME for call in calls):
        return "PATCH_AGENT_MIXED_TOOL_BATCH_FORBIDDEN", "Upstream requests must be separate from source reads."
    if any(call.name != PATCH_SOURCE_INSPECTION_TOOL_NAME for call in calls):
        return "PATCH_AGENT_UNKNOWN_TOOL", "The batch contains an unregistered Patch tool."
    selected: set[str] = set()
    call_ids: set[str] = set()
    for call in calls:
        if type(call.call_id) is not str or not call.call_id:
            return "PATCH_AGENT_TOOL_CALL_ID_INVALID", "A provider tool call id is missing."
        if call.call_id in call_ids or call.call_id in seen_tool_call_ids:
            return "PATCH_AGENT_TOOL_CALL_ID_REUSED", "The provider reused a tool call id."
        if (set(call.arguments) != {"binding_id"} or type(call.arguments.get("binding_id")) is not str
            or not call.arguments["binding_id"]):
            return "PATCH_AGENT_TOOL_ARGUMENTS_INVALID", "Each source read requires exactly one binding_id."
        binding_id = call.arguments["binding_id"]
        if binding_id in selected or binding_id in inspected_binding_ids:
            return "PATCH_AGENT_REPEATED_TOOL_CALL", "The same Plan binding cannot be inspected twice."
        if binding_id not in inspector.available_read_binding_ids:
            return "PATCH_AGENT_BINDING_UNKNOWN", "A batch binding is outside the admitted read scope."
        call_ids.add(call.call_id)
        selected.add(binding_id)
    return None, ""


def _source_tool_definition(
    inspector: PlanBoundSourceInspector,
    *,
    binding_ids: tuple[str, ...] | None = None,
) -> AgentToolDefinition:
    allowed_binding_ids = inspector.available_read_binding_ids if binding_ids is None else binding_ids
    return AgentToolDefinition(
        name=PATCH_SOURCE_INSPECTION_TOOL_NAME,
        description=(
            "Read a bounded current-source excerpt for one exact ImplementationPlan "
            "read binding. Reading supporting source does not grant edit permission. "
            "Registered API bindings return the complete saved Evidence excerpt, not a new live API inspection. "
            "When batched reads are enabled, calls execute sequentially and each consumes one read budget unit. "
            "Select only a listed binding_id; paths are not accepted."
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
    prior_observations: list[PatchSourceObservation | Mapping[str, object]],
    model_turns_used: int,
    tool_rounds_used: int,
    force_final: bool,
    final_response_format: AgentResponseFormat,
    reserve_model_turns: int = 0,
) -> AgentMessage:
    return AgentMessage(
        role="user",
        content={
            "message_type": "patch_agent_loop_state",
            "allowed_binding_ids": list(source_inspector.available_binding_ids),
            "allowed_read_binding_ids": list(source_inspector.available_read_binding_ids),
            "source_snapshot_sha256": source_inspector.source_snapshot_sha256,
            "read_source_snapshot_sha256": source_inspector.read_source_snapshot_sha256,
            **({"read_execution": {"allow_batched_reads": True, "execution": "sequential",
                "batch_must_fit_remaining_reads": True}} if policy.allow_batched_reads else {}),
            "prior_observations": [
                observation.model_view() if isinstance(observation, PatchSourceObservation) else deepcopy(dict(observation))
                for observation in prior_observations
            ],
            "budget_state": {
                "model_turns_used": model_turns_used,
                "remaining_model_turns": policy.max_total_model_turns
                - model_turns_used - reserve_model_turns,
                "reserved_model_turns": reserve_model_turns,
                "tool_rounds_used": tool_rounds_used,
                "remaining_tool_rounds": policy.max_tool_rounds
                - tool_rounds_used,
            },
            "required_next_action": (
                "finish_or_request_upstream" if force_final and policy.allow_upstream_request
                else "finish" if force_final else "inspect_or_finish_or_request_upstream"
                if policy.allow_upstream_request else "inspect_or_finish"
            ),
            "final_response_contract": {
                "name": final_response_format.name,
                "description": final_response_format.description,
                "schema_sha256": _canonical_sha256(
                    final_response_format.schema
                ),
            },
        },
    )


def _is_loop_state(message: AgentMessage) -> bool:
    return (message.role == "user" and isinstance(message.content, Mapping)
        and message.content.get("message_type") == "patch_agent_loop_state")


def _without_loop_states(request: AgentTurnRequest) -> AgentTurnRequest:
    """Replace dynamic loop state while preserving native exchange message boundaries."""

    kept_indexes = [index for index, message in enumerate(request.messages) if not _is_loop_state(message)]

    def remap(index: int | None) -> int | None:
        if index is None:
            return None
        if type(index) is not int or not 0 <= index <= len(request.messages):
            raise PatchAgentLoopError("PATCH_AGENT_LOOP_INPUT_INVALID", stage="loop_admission",
                reason="A historical tool exchange has an invalid insertion boundary.")
        return sum(old_index < index for old_index in kept_indexes)

    return replace(request, messages=tuple(request.messages[index] for index in kept_indexes),
        tool_result_insert_index=remap(request.tool_result_insert_index),
        historical_tool_exchanges=tuple(replace(exchange, insert_index=remap(exchange.insert_index))
            for exchange in request.historical_tool_exchanges))


def _upstream_tool_definition(inspector: PlanBoundSourceInspector) -> AgentToolDefinition:
    return AgentToolDefinition(name=PATCH_UPSTREAM_REQUEST_TOOL_NAME,
        description="Request Evidence or Planning assessment with bound facts. This does not change routing or edit authority.",
        parameters={"type": "object", "additionalProperties": False,
            "required": ["required_owner", "reason", "source_refs"], "properties": {
                "required_owner": {"type": "string", "enum": ["evidence", "planning"]},
                "reason": {"type": "string", "minLength": 1, "maxLength": 2000},
                "source_refs": {"type": "array", "minItems": 1, "uniqueItems": True,
                    "items": {"type": "string", "enum": [f"binding://{binding}" for binding in inspector.available_read_binding_ids]}}
            }})


def _validate_upstream_request(call: AgentToolCall, inspector: PlanBoundSourceInspector,
    policy: PatchAgentLoopPolicy, *, tool_available: bool) -> tuple[str, dict[str, object] | None]:
    if not policy.allow_upstream_request or not tool_available:
        return "PATCH_AGENT_TOOL_FORBIDDEN", None
    arguments = call.arguments
    refs = arguments.get("source_refs")
    reason = arguments.get("reason")
    if (not isinstance(call.call_id, str) or not call.call_id
        or set(arguments) != {"required_owner", "reason", "source_refs"}
        or arguments.get("required_owner") not in ("evidence", "planning")
        or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
        or not isinstance(refs, list) or not refs
        or any(not isinstance(ref, str) for ref in refs)
        or len(refs) != len(set(refs))
        or not set(refs) <= {f"binding://{binding}" for binding in inspector.available_read_binding_ids}):
        return "PATCH_AGENT_UPSTREAM_REQUEST_INVALID", None
    try:
        inspector.validate_snapshot()
    except PatchAgentLoopError as exc:
        return exc.code, None
    return "PATCH_AGENT_UPSTREAM_REQUESTED", {**deepcopy(arguments),
        "source_snapshot_sha256": inspector.source_snapshot_sha256,
        "read_source_snapshot_sha256": inspector.read_source_snapshot_sha256,
        "assessment_required": True}


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
    status: Literal["accepted", "rejected", "rejected_not_executed"],
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
        **(dict(observation.registered_evidence_identity) if observation.registered_evidence_identity is not None else {}),
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
