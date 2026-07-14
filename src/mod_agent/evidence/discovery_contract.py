"""Contracts and model boundaries for bounded intelligent evidence discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.libs.llm import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolDefinition,
    AgentToolResult,
    AgentTurnClient,
    AgentTurnRequest,
    AgentTurnResponse,
    BaseLLM,
    Message,
)
from src.mod_agent.knowledge.source_registry import SourceDefinition

from .models import EvidenceItem, EvidencePack

EVIDENCE_DISCOVERY_TOOLS = frozenset(
    {"search_dotnet_metadata", "inspect_method_il"}
)
EVIDENCE_DISCOVERY_RESULT_KINDS = frozenset({"methods", "types", "fields"})
EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION = "evidence_discovery_prompt_v2"
EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES = (
    "natural_language_request",
    "source_registry_model_views",
    "tool_observation_metadata_and_il",
)


class EvidenceDiscoveryModel(Protocol):
    """Return one strict JSON action from a bounded discovery turn."""

    def complete(self, messages: tuple[dict[str, object], ...]) -> str:
        ...


@dataclass(frozen=True)
class EvidenceDiscoveryDisclosure:
    """Explicit one-run approval for data sent through an external model."""

    approved: bool
    approval_id: str
    destination: dict[str, str]
    approved_data_classes: tuple[str, ...]
    scope: str = "this_run_only"

    def validate(self) -> None:
        if not self.approved or not self.approval_id.strip():
            raise ValueError("EVIDENCE_MODEL_DISCLOSURE_NOT_APPROVED")
        if self.scope != "this_run_only":
            raise ValueError("EVIDENCE_MODEL_DISCLOSURE_SCOPE_INVALID")
        missing = sorted(
            set(EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES)
            - set(self.approved_data_classes)
        )
        if missing:
            raise ValueError(
                "EVIDENCE_MODEL_DISCLOSURE_DATA_CLASS_MISSING: " + ", ".join(missing)
            )
        if not self.destination.get("provider") or not self.destination.get("model"):
            raise ValueError("EVIDENCE_MODEL_DISCLOSURE_DESTINATION_INVALID")

    def to_audit_record(self) -> dict[str, object]:
        self.validate()
        return {
            "approved": True,
            "approval_id": self.approval_id,
            "destination": dict(self.destination),
            "approved_data_classes": list(self.approved_data_classes),
            "scope": self.scope,
        }


class EvidenceDiscoveryAgentModel:
    """Map provider-neutral structured turns to the local discovery action contract."""

    def __init__(
        self,
        client: AgentTurnClient,
        *,
        disclosure: EvidenceDiscoveryDisclosure,
    ) -> None:
        disclosure.validate()
        self.client = client
        self.disclosure = disclosure
        self._pending_response: AgentTurnResponse | None = None
        self._usage_records: list[dict[str, object]] = []

    @property
    def disclosure_record(self) -> dict[str, object]:
        return self.disclosure.to_audit_record()

    @property
    def usage_records(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._usage_records)

    def begin_run(self) -> None:
        self._pending_response = None
        self._usage_records.clear()

    def complete(self, messages: tuple[dict[str, object], ...]) -> str:
        agent_messages: list[AgentMessage] = []
        latest_observation: object | None = None
        tool_result_insert_index: int | None = None
        force_finish = False
        for item in messages:
            role = str(item.get("role") or "")
            content = item.get("content")
            if role == "tool":
                latest_observation = content
                tool_result_insert_index = len(agent_messages)
                continue
            if role not in {"system", "user", "assistant"}:
                raise ValueError("EVIDENCE_MODEL_MESSAGE_ROLE_INVALID")
            if isinstance(content, dict) and content.get("required_next_action") == "finish":
                force_finish = True
            if isinstance(content, dict) and content.get("message_type") == "finish_validation_error":
                force_finish = True
            agent_messages.append(AgentMessage(role=role, content=content))

        tool_results: tuple[AgentToolResult, ...] = ()
        provider_state: object | None = None
        if latest_observation is not None:
            pending = self._pending_response
            if pending is None or len(pending.tool_calls) != 1:
                raise ValueError("EVIDENCE_MODEL_TOOL_RESULT_WITHOUT_CALL")
            call = pending.tool_calls[0]
            tool_results = (
                AgentToolResult(
                    call_id=call.call_id,
                    name=call.name,
                    output=latest_observation,
                ),
            )
            provider_state = pending.provider_state

        response = self.client.complete_turn(
            AgentTurnRequest(
                messages=tuple(agent_messages),
                tools=() if force_finish else _discovery_tool_definitions(),
                tool_choice="none" if force_finish else "auto",
                parallel_tool_calls=False,
                response_format=_finish_response_format() if force_finish else None,
                tool_results=tool_results,
                tool_result_insert_index=tool_result_insert_index,
                provider_state=provider_state,
                temperature=0.0,
            )
        )
        self._usage_records.append(
            {
                "provider": response.provider,
                "model": response.model,
                "request_id": response.request_id,
                "stop_reason": response.stop_reason,
                **response.usage.to_dict(),
            }
        )
        if len(response.tool_calls) > 1:
            raise ValueError("EVIDENCE_MODEL_PARALLEL_TOOL_CALLS_FORBIDDEN")
        if response.tool_calls:
            call = response.tool_calls[0]
            action = _action_from_tool_call(call.name, call.arguments)
            self._pending_response = response
            return json.dumps(action, ensure_ascii=False, separators=(",", ":"))
        self._pending_response = None
        if not response.content or not response.content.strip():
            raise ValueError("EVIDENCE_MODEL_EMPTY_RESPONSE")
        return response.content


class ChatEvidenceDiscoveryModel:
    """Compatibility adapter for existing text-only BaseLLM callers."""

    def __init__(
        self,
        llm: BaseLLM,
        *,
        disclosure: EvidenceDiscoveryDisclosure,
    ) -> None:
        disclosure.validate()
        self.llm = llm
        self.disclosure = disclosure

    @property
    def disclosure_record(self) -> dict[str, object]:
        return self.disclosure.to_audit_record()

    def complete(self, messages: tuple[dict[str, object], ...]) -> str:
        converted: list[Message] = []
        for item in messages:
            role = str(item.get("role") or "")
            content = item.get("content")
            if role == "tool":
                role = "user"
                content = {"message_type": "tool_observation", "payload": content}
            if role not in {"system", "user", "assistant"}:
                raise ValueError("EVIDENCE_MODEL_MESSAGE_ROLE_INVALID")
            converted.append(
                Message(
                    role=role,
                    content=json.dumps(
                        content, ensure_ascii=False, separators=(",", ":")
                    ),
                )
            )
        response = self.llm.chat(converted, temperature=0)
        return response.content


class EvidenceDiscoveryToolExecutor(Protocol):
    """Execute one already-authorized structured read-only action."""

    def execute(
        self,
        *,
        action: dict[str, object],
        source: "EvidenceDiscoverySource",
        observation_id: str,
    ) -> "ToolObservation":
        ...


@dataclass(frozen=True)
class EvidenceDiscoverySource:
    """Local source binding with a path-hidden projection for the model."""

    source_id: str
    source_type: str
    kind: str
    evidence_class: str
    description: str
    root_path: str | Path
    allowed_tools: tuple[str, ...]
    assembly_relative_paths: tuple[str, ...] = ()
    version_identity: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.source_id or any(value in self.source_id for value in ("/", "\\", "..")):
            raise ValueError("Evidence discovery source_id is invalid.")
        root = Path(self.root_path).resolve()
        if not root.is_dir():
            raise ValueError(f"Evidence discovery source root is not a directory: {root}")
        unknown = set(self.allowed_tools) - EVIDENCE_DISCOVERY_TOOLS
        if unknown:
            raise ValueError(
                "Evidence discovery source uses unsupported tools: "
                + ", ".join(sorted(unknown))
            )
        normalized_paths: list[str] = []
        for relative_text in self.assembly_relative_paths:
            relative = Path(relative_text)
            if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".dll":
                raise ValueError("Evidence discovery assembly_relative_paths is invalid.")
            resolved = (root / relative).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    "Evidence discovery assembly path leaves the source root."
                ) from exc
            if not resolved.is_file():
                raise ValueError(
                    "Evidence discovery assembly is missing: " + relative.as_posix()
                )
            normalized_paths.append(relative.as_posix())
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ValueError("Evidence discovery assembly_relative_paths must be unique.")
        object.__setattr__(self, "root_path", root)
        object.__setattr__(self, "assembly_relative_paths", tuple(normalized_paths))

    def model_view(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "kind": self.kind,
            "evidence_class": self.evidence_class,
            "description": self.description,
            "allowed_tools": list(self.allowed_tools),
            "assembly_relative_paths": list(self.assembly_relative_paths),
            "version_identity": dict(self.version_identity or {}),
        }


def evidence_discovery_source_from_definition(
    definition: SourceDefinition,
) -> EvidenceDiscoverySource:
    """Project one registered source through an exact discovery metadata contract."""

    metadata = definition.metadata
    values: dict[str, str] = {}
    for field_name in ("evidence_discovery_kind", "evidence_class", "description"):
        value = metadata.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Evidence discovery source metadata requires {field_name}.")
        values[field_name] = value
    allowed_tools = metadata.get("allowed_tools")
    assembly_relative_paths = metadata.get("assembly_relative_paths", [])
    version_identity = metadata.get("version_identity", {})
    if not isinstance(allowed_tools, list) or any(
        not isinstance(item, str) for item in allowed_tools
    ):
        raise ValueError("Evidence discovery source metadata allowed_tools must be a list.")
    if not isinstance(assembly_relative_paths, list) or any(
        not isinstance(item, str) for item in assembly_relative_paths
    ):
        raise ValueError(
            "Evidence discovery source metadata assembly_relative_paths must be a list."
        )
    if not isinstance(version_identity, dict):
        raise ValueError("Evidence discovery source metadata version_identity must be an object.")
    return EvidenceDiscoverySource(
        source_id=definition.source_id,
        source_type=definition.source_type,
        kind=values["evidence_discovery_kind"],
        evidence_class=values["evidence_class"],
        description=values["description"],
        root_path=definition.root_path,
        allowed_tools=tuple(allowed_tools),
        assembly_relative_paths=tuple(assembly_relative_paths),
        version_identity=dict(version_identity),
    )


@dataclass(frozen=True)
class EvidenceDiscoveryRequest:
    """One evidence-only intelligent run with no precomputed discovery decisions."""

    request_id: str
    natural_language_request: str
    sources: tuple[EvidenceDiscoverySource, ...]
    max_tool_calls: int = 6
    max_model_steps: int = 8
    max_result_bytes_per_call: int = 65_536
    max_total_observation_bytes: int = 262_144
    manual_symbols: tuple[str, ...] = ()
    manual_tool_sequence: tuple[str, ...] = ()
    precomputed_reports: tuple[str, ...] = ()
    operator_intervention_count: int = 0

    def __post_init__(self) -> None:
        if not self.request_id.strip() or not self.natural_language_request.strip():
            raise ValueError("Evidence discovery request id and goal are required.")
        if not self.sources:
            raise ValueError("Evidence discovery requires at least one authorized source.")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Evidence discovery source_ids must be unique.")
        for name, value in (
            ("max_tool_calls", self.max_tool_calls),
            ("max_model_steps", self.max_model_steps),
            ("max_result_bytes_per_call", self.max_result_bytes_per_call),
            ("max_total_observation_bytes", self.max_total_observation_bytes),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")
        if self.operator_intervention_count < 0:
            raise ValueError("operator_intervention_count cannot be negative.")
        if self.manual_symbols or self.manual_tool_sequence or self.precomputed_reports:
            raise ValueError(
                "Intelligent evidence acceptance forbids manual symbols, tool sequences, "
                "and precomputed reports."
            )


@dataclass(frozen=True)
class ToolObservation:
    """One deterministic tool result returned without machine-local roots."""

    observation_id: str
    tool: str
    source_id: str
    summary: str
    data: dict[str, object]
    evidence_items: tuple[EvidenceItem, ...] = ()

    def model_view(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "tool": self.tool,
            "source_id": self.source_id,
            "summary": self.summary,
            "data": self.data,
        }


@dataclass(frozen=True)
class EvidenceDiscoveryResult:
    """Intelligent discovery result plus deterministically derived audit facts."""

    run_status: str
    pack: EvidencePack
    actions: tuple[dict[str, object], ...]
    observations: tuple[ToolObservation, ...]
    input_audit: dict[str, int]
    intelligence_transfer: dict[str, bool]


def _discovery_tool_definitions() -> tuple[AgentToolDefinition, ...]:
    common_properties: dict[str, object] = {
        "source_id": {"type": "string", "minLength": 1},
        "evidence_need": {"type": "string", "minLength": 1},
        "derived_from_observation_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    }
    return (
        AgentToolDefinition(
            name="search_dotnet_metadata",
            description=(
                "Search exact managed metadata in one registered source. Select result "
                "kinds and a small per-kind limit to keep the observation focused."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **common_properties,
                    "queries": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "result_kinds": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "enum": ["methods", "types", "fields"],
                        },
                    },
                    "limit_per_kind": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": [
                    "source_id",
                    "evidence_need",
                    "derived_from_observation_ids",
                    "queries",
                    "result_kinds",
                    "limit_per_kind",
                ],
                "additionalProperties": False,
            },
        ),
        AgentToolDefinition(
            name="inspect_method_il",
            description="Read IL only for a method_id returned by this run's metadata observation.",
            parameters={
                "type": "object",
                "properties": {
                    **common_properties,
                    "method_id": {"type": "string", "minLength": 1},
                },
                "required": [
                    "source_id",
                    "evidence_need",
                    "derived_from_observation_ids",
                    "method_id",
                ],
                "additionalProperties": False,
            },
        ),
    )


def _finish_response_format() -> AgentResponseFormat:
    conclusion = {
        "type": "object",
        "properties": {
            "claim": {"type": "string", "minLength": 1},
            "claim_status": {
                "type": "string",
                "enum": ["observed", "inferred", "unknown"],
            },
            "observation_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "limitations": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
        "required": ["claim", "claim_status", "observation_ids", "limitations"],
        "additionalProperties": False,
    }
    return AgentResponseFormat(
        name="evidence_discovery_finish",
        description="Final grounded evidence decision for the bounded discovery run.",
        schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["finish"]},
                "decision": {
                    "type": "string",
                    "enum": [
                        "sufficient_for_proposal",
                        "needs_more_evidence",
                        "blocked_by_missing_capability",
                        "conflicting_evidence",
                    ],
                },
                "evidence_conclusions": {"type": "array", "items": conclusion},
                "unresolved_questions": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "missing_capabilities": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "required": [
                "action",
                "decision",
                "evidence_conclusions",
                "unresolved_questions",
                "missing_capabilities",
            ],
            "additionalProperties": False,
        },
    )


def _action_from_tool_call(
    name: str,
    raw_arguments: dict[str, object],
) -> dict[str, object]:
    arguments = dict(raw_arguments)
    source_id = arguments.pop("source_id", None)
    evidence_need = arguments.pop("evidence_need", None)
    derived = arguments.pop("derived_from_observation_ids", None)
    if name not in EVIDENCE_DISCOVERY_TOOLS:
        raise ValueError("UNKNOWN_EVIDENCE_TOOL")
    return {
        "action": "use_tool",
        "tool": name,
        "source_id": source_id,
        "arguments": arguments,
        "evidence_need": evidence_need,
        "derived_from_observation_ids": derived,
    }
