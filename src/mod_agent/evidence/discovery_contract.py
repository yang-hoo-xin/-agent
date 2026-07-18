"""Contracts and model boundaries for bounded intelligent evidence discovery."""

from __future__ import annotations

import hashlib
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
    AgentTurnProviderError,
    AgentTurnRequest,
    AgentTurnResponse,
    BaseLLM,
    Message,
    validate_loopback_http_base_url,
)
from src.mod_agent.knowledge.source_registry import SourceDefinition

from .models import EvidenceItem, EvidencePack

EVIDENCE_DISCOVERY_TOOLS = frozenset(
    {"search_dotnet_metadata", "inspect_method_il"}
)
EVIDENCE_DISCOVERY_RESULT_KINDS = frozenset({"methods", "types", "fields"})
EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION = "evidence_discovery_prompt_v8"
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


@dataclass(frozen=True)
class EvidenceDiscoveryLocalExecution:
    """Auditable on-device model boundary that does not authorize disclosure."""

    endpoint: str
    provider: str
    model: str
    scope: str = "local_loopback_only"

    def validate(self) -> None:
        validate_loopback_http_base_url(self.endpoint)
        if self.scope != "local_loopback_only":
            raise ValueError("EVIDENCE_LOCAL_MODEL_SCOPE_INVALID")
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("EVIDENCE_LOCAL_MODEL_IDENTITY_INVALID")

    def to_audit_record(self) -> dict[str, object]:
        self.validate()
        return {
            "approved": False,
            "reason": "On-device inference through a literal loopback endpoint; no external model disclosure occurred.",
            "execution_kind": "local_agent_turn_adapter",
            "destination": {
                "provider": self.provider,
                "model": self.model,
                "endpoint": validate_loopback_http_base_url(self.endpoint),
            },
            "scope": self.scope,
        }


class EvidenceDiscoveryAgentModel:
    """Map provider-neutral structured turns to the local discovery action contract."""

    def __init__(
        self,
        client: AgentTurnClient,
        *,
        disclosure: EvidenceDiscoveryDisclosure | None = None,
        local_execution: EvidenceDiscoveryLocalExecution | None = None,
    ) -> None:
        if (disclosure is None) == (local_execution is None):
            raise ValueError("EVIDENCE_MODEL_EXECUTION_BOUNDARY_MUST_BE_EXACTLY_ONE")
        boundary = disclosure if disclosure is not None else local_execution
        assert boundary is not None
        boundary.validate()
        self.client = client
        self.execution_boundary = boundary
        self._pending_response: AgentTurnResponse | None = None
        self._usage_records: list[dict[str, object]] = []
        self._provider_turn_records: list[dict[str, object]] = []
        self._model_call_count = 0
        self._accepted_action_count = 0

    @property
    def disclosure_record(self) -> dict[str, object]:
        return self.execution_boundary.to_audit_record()

    @property
    def usage_records(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._usage_records)

    @property
    def provider_turn_records(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._provider_turn_records)

    @property
    def model_call_count(self) -> int:
        return self._model_call_count

    @property
    def accepted_action_count(self) -> int:
        return self._accepted_action_count

    def begin_run(self) -> None:
        self._pending_response = None
        self._usage_records.clear()
        self._provider_turn_records.clear()
        self._model_call_count = 0
        self._accepted_action_count = 0

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

        request = AgentTurnRequest(
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
        self._model_call_count += 1
        try:
            response = self.client.complete_turn(request)
        except AgentTurnProviderError as exc:
            if exc.diagnostic:
                self._provider_turn_records.append(dict(exc.diagnostic))
            raise
        if response.provider_diagnostic is not None:
            self._provider_turn_records.append(dict(response.provider_diagnostic))
        else:
            self._provider_turn_records.append(_fallback_provider_turn_record(response))
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
            self._accepted_action_count += 1
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

    def begin_run(self, *, run_id: str) -> None:
        """Reset run-scoped observation bindings before discovery starts."""
        ...

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

    run_id: str
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
        if (
            not self.run_id.strip()
            or not self.request_id.strip()
            or not self.natural_language_request.strip()
        ):
            raise ValueError("Evidence discovery run id, request id, and goal are required.")
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
            "data": _without_control_only_method_ids(self.data),
        }


def _without_control_only_method_ids(value: object) -> object:
    """Project an observation without exposing internal method identities."""

    if isinstance(value, dict):
        return {
            key: _without_control_only_method_ids(item)
            for key, item in value.items()
            if key != "method_id"
        }
    if isinstance(value, list):
        return [_without_control_only_method_ids(item) for item in value]
    if isinstance(value, tuple):
        return [_without_control_only_method_ids(item) for item in value]
    return value


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
                "Search managed metadata symbols in one registered source using "
                "case-insensitive literal-substring matching. Queries match fully "
                "qualified managed type, method, and field symbols; this is not "
                "behavioral or semantic search. Select result kinds and a small "
                "per-kind limit to keep the observation focused."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **common_properties,
                    "queries": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 12,
                        "description": (
                            "Literal symbol-name substrings, not natural-language "
                            "behavior descriptions. Matching is case-insensitive "
                            "against fully qualified managed type, method, and field "
                            "symbols."
                        ),
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
            description=(
                "Read IL only for a candidate_ref returned by this run's metadata "
                "observation. The control layer resolves it to an internal method identity."
            ),
            parameters={
                "type": "object",
                "properties": {
                    **common_properties,
                    "candidate_ref": {"type": "string", "minLength": 1},
                },
                "required": [
                    "source_id",
                    "evidence_need",
                    "derived_from_observation_ids",
                    "candidate_ref",
                ],
                "additionalProperties": False,
            },
        ),
    )


def evidence_discovery_finish_schema() -> dict[str, object]:
    """Return the exact model-facing schema enforced for a discovery finish."""
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
    return {
        "type": "object",
        "description": (
            "Cross-field: sufficient=>conclusions>0,gaps=0; "
            "needs_more=>gaps>0; blocked=>missing>0."
        ),
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
    }


def evidence_discovery_finish_decision_constraints() -> dict[str, object]:
    """Return the cross-field finish rules shared by prompt and correction."""

    return {
        "sufficient_for_proposal": (
            "conclusions>0; unresolved_questions=0; missing_capabilities=0"
        ),
        "needs_more_evidence": "unresolved_questions+missing_capabilities>0",
        "blocked_by_missing_capability": "missing_capabilities>0",
        "conflicting_evidence": "conflict; proposal_locked",
    }


def _finish_response_format() -> AgentResponseFormat:
    return AgentResponseFormat(
        name="evidence_discovery_finish",
        description="Final grounded evidence decision for the bounded discovery run.",
        schema=evidence_discovery_finish_schema(),
    )


def _fallback_provider_turn_record(
    response: AgentTurnResponse,
) -> dict[str, object]:
    return {
        "api_type": "provider_neutral_agent_turn",
        "streaming": False,
        "provider_request_id": response.request_id,
        "finish_reason": response.stop_reason,
        "tool_calls": [
            {
                "tool_call_id": call.call_id,
                "provider_reported_tool_name": None,
                "adapter_extracted_tool_name": call.name,
                "normalized_tool_name": call.name,
                "normalization_applied": False,
                "arguments_valid_json": True,
                "arguments_is_object": True,
                "arguments_sha256": hashlib.sha256(
                    json.dumps(
                        call.arguments,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
            for call in response.tool_calls
        ],
        "usage": response.usage.to_dict(),
    }


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
