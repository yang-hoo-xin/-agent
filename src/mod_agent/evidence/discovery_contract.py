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

from .models import EvidenceItem, EvidencePack, missing_evidence_from_blockers

EVIDENCE_DISCOVERY_TOOLS = frozenset(
    {"search_dotnet_metadata", "inspect_method_il"}
)
EVIDENCE_DISCOVERY_RESULT_KINDS = frozenset({"methods", "types", "fields"})
EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION = "evidence_discovery_prompt_v9"
AGENT_DISCOVERY_PROMPT_CONTRACT_VERSION = "agent_evidence_discovery_prompt_v7"
AGENT_DISCOVERY_LEGACY_PROMPT_CONTRACT_VERSIONS = frozenset(
    {
        "agent_evidence_discovery_prompt_v2",
        "agent_evidence_discovery_prompt_v3",
        "agent_evidence_discovery_prompt_v4",
        "agent_evidence_discovery_prompt_v5",
        "agent_evidence_discovery_prompt_v6",
    }
)
AGENT_DISCOVERY_ACTUAL_SCHEMA_VERSION = "agent_evidence_discovery_actual_v2"
REQUIREMENT_PROJECTION_SCHEMA_VERSION = "hook_requirement_projection_v2"
SEARCH_PLAN_SCHEMA_VERSION = "hook_discovery_search_plan_v4"
_SEARCH_PLAN_SCHEMA_VERSION_V2 = "hook_discovery_search_plan_v2"
_SEARCH_PLAN_SCHEMA_VERSION_V3 = "hook_discovery_search_plan_v3"
_LEGACY_SEARCH_PLAN_SCHEMA_VERSIONS = frozenset(
    {_SEARCH_PLAN_SCHEMA_VERSION_V2, _SEARCH_PLAN_SCHEMA_VERSION_V3}
)
EVIDENCE_SOURCE_AUTHORITIES = frozenset({"authoritative", "supporting", "lead"})
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
        self._structured_output_records: list[dict[str, object]] = []
        self._model_call_count = 0
        self._accepted_action_count = 0
        self._runtime_stage = "not_started"

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
    def structured_output_records(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._structured_output_records)

    @property
    def model_call_count(self) -> int:
        return self._model_call_count

    @property
    def accepted_action_count(self) -> int:
        return self._accepted_action_count

    @property
    def runtime_stage(self) -> str:
        """Return the current provider/adapter substage without response content."""

        return self._runtime_stage

    def begin_run(self) -> None:
        self._pending_response = None
        self._usage_records.clear()
        self._provider_turn_records.clear()
        self._structured_output_records.clear()
        self._model_call_count = 0
        self._accepted_action_count = 0
        self._runtime_stage = "model_request_construction"

    def complete(self, messages: tuple[dict[str, object], ...]) -> str:
        self._runtime_stage = "model_request_construction"
        agent_messages: list[AgentMessage] = []
        latest_observation: object | None = None
        tool_result_insert_index: int | None = None
        force_finish = False
        force_tool = False
        force_family_selection = False
        force_plan = False
        force_requirement_projection = False
        force_search_plan = False
        force_source_identifier_selection = False
        actual_planning_run = False
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
            if isinstance(content, dict) and content.get("required_next_action") == "use_tool":
                force_tool = True
            if (
                isinstance(content, dict)
                and content.get("message_type") == "tool_action_validation_error"
                and content.get("error_code")
                in {
                    "OPEN_REQUIREMENT_FOLLOWUP_REQUIRED",
                    "QUERY_FAMILY_ALREADY_EXECUTED",
                }
            ):
                force_family_selection = True
            if isinstance(content, dict) and content.get("required_next_action") == "plan":
                force_plan = True
            if (
                isinstance(content, dict)
                and content.get("required_next_action") == "project_requirements"
            ):
                force_requirement_projection = True
            if (
                isinstance(content, dict)
                and content.get("required_next_action") == "plan_search"
            ):
                force_search_plan = True
            if (
                isinstance(content, dict)
                and content.get("required_next_action")
                == "source_identifier_selection"
            ):
                force_source_identifier_selection = True
            if (
                isinstance(content, dict)
                and content.get("message_type") == "frozen_actual_plan"
            ):
                actual_planning_run = True
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
            tools=(
                ()
                if force_finish
                or force_plan
                or force_requirement_projection
                or force_search_plan
                or force_source_identifier_selection
                else _discovery_tool_definitions(
                    require_family_selection=actual_planning_run
                )[:1]
                if force_family_selection
                else _discovery_tool_definitions(
                    require_family_selection=actual_planning_run
                )
            ),
            tool_choice=(
                "none"
                if force_finish
                or force_plan
                or force_requirement_projection
                or force_search_plan
                or force_source_identifier_selection
                else "required"
                if force_tool
                else "auto"
            ),
            parallel_tool_calls=False,
            response_format=(
                _source_identifier_selection_response_format()
                if force_source_identifier_selection
                else _requirement_projection_response_format()
                if force_requirement_projection
                else _search_plan_response_format()
                if force_search_plan
                else _planning_response_format()
                if force_plan
                else _finish_response_format(
                    require_requirement_binding=actual_planning_run
                )
                if force_finish
                else None
            ),
            tool_results=tool_results,
            tool_result_insert_index=tool_result_insert_index,
            provider_state=provider_state,
            temperature=0.0,
        )
        self._model_call_count += 1
        self._runtime_stage = "provider_turn"
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
        self._runtime_stage = "adapter_response_validation"
        if len(response.tool_calls) > 1:
            raise ValueError("EVIDENCE_MODEL_PARALLEL_TOOL_CALLS_FORBIDDEN")
        if response.tool_calls:
            call = response.tool_calls[0]
            self._runtime_stage = "adapter_action_conversion"
            action = _action_from_tool_call(call.name, call.arguments)
            normalized_output = json.dumps(
                action, ensure_ascii=False, separators=(",", ":")
            )
            self._structured_output_records.append(
                {
                    "model_call_index": self._model_call_count,
                    "output_kind": "normalized_tool_action",
                    "structured_output": normalized_output,
                    "structured_output_sha256": hashlib.sha256(
                        normalized_output.encode("utf-8")
                    ).hexdigest(),
                }
            )
            self._accepted_action_count += 1
            self._pending_response = response
            self._runtime_stage = "adapter_action_accepted"
            return normalized_output
        self._pending_response = None
        self._runtime_stage = "adapter_finish_extraction"
        if not response.content or not response.content.strip():
            raise ValueError("EVIDENCE_MODEL_EMPTY_RESPONSE")
        self._structured_output_records.append(
            {
                "model_call_index": self._model_call_count,
                "output_kind": "provider_structured_content",
                "structured_output": response.content,
                "structured_output_sha256": hashlib.sha256(
                    response.content.encode("utf-8")
                ).hexdigest(),
            }
        )
        self._runtime_stage = "adapter_finish_accepted"
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
    source_authority: str
    description: str
    root_path: str | Path
    allowed_tools: tuple[str, ...]
    assembly_relative_paths: tuple[str, ...] = ()
    version_identity: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.source_id or any(value in self.source_id for value in ("/", "\\", "..")):
            raise ValueError("Evidence discovery source_id is invalid.")
        if self.source_authority not in EVIDENCE_SOURCE_AUTHORITIES:
            raise ValueError("Evidence discovery source authority is invalid.")
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
            "source_authority": self.source_authority,
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
    for field_name in (
        "evidence_discovery_kind",
        "evidence_class",
        "description",
        "evidence_authority",
    ):
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
        source_authority=values["evidence_authority"],
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
    require_actual_planning: bool = False

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
        if self.require_actual_planning and self.max_tool_calls > 4:
            raise ValueError("FIRST_HOOK_DISCOVERY_TOOL_BUDGET_EXCEEDS_FOUR")
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

    def identity_view(self) -> dict[str, object]:
        """Return the fact-independent payload used for durable identity binding."""

        return {
            "observation_id": self.observation_id,
            "tool": self.tool,
            "source_id": self.source_id,
            "summary": self.summary,
            "data": _without_control_only_method_ids(self.data),
        }

    def identity_sha256(self) -> str:
        """Hash the observation payload without recursively including fact rows."""

        return hashlib.sha256(
            _canonical_json(self.identity_view()).encode("utf-8")
        ).hexdigest()

    def supported_facts(self) -> list[dict[str, object]]:
        """Project mechanically verifiable facts without semantic interpretation."""

        return _supported_observation_facts(self)

    def model_supported_facts(self) -> list[dict[str, object]]:
        """Expose only observation binding and the exact claim required by the model."""

        return [
            {
                key: fact[key]
                for key in (
                    "fact_id",
                    "observation_id",
                    "canonical_claim",
                )
            }
            for fact in self.supported_facts()
        ]

    def model_view(self) -> dict[str, object]:
        return {
            **self.identity_view(),
            "supported_facts": self.model_supported_facts(),
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


def _supported_observation_facts(
    observation: ToolObservation,
) -> list[dict[str, object]]:
    data = observation.data
    facts: list[dict[str, object]] = []
    if observation.tool == "search_dotnet_metadata":
        matched_counts = data.get("matched_counts")
        matched_query_counts = data.get("matched_query_counts")
        returned_counts = data.get("returned_counts")
        returned_query_counts = data.get("returned_query_counts")
        truncated_by_kind = data.get("truncated_by_kind")
        if all(
            isinstance(value, dict)
            for value in (matched_counts, returned_counts, truncated_by_kind)
        ):
            value = {
                "queries": list(data.get("queries") or []),
                "matched_counts": dict(matched_counts),
                "returned_counts": dict(returned_counts),
                "results_truncated": data.get("results_truncated") is True,
                "truncated_by_kind": dict(truncated_by_kind),
            }
            if isinstance(matched_query_counts, dict) and isinstance(
                returned_query_counts, dict
            ):
                value["matched_query_counts"] = dict(matched_query_counts)
                value["returned_query_counts"] = dict(returned_query_counts)
            canonical_claim = _canonical_claim_for_persisted_fact(
                fact_type="metadata_search_result",
                subject=observation.source_id,
                value=value,
            )
            assert canonical_claim is not None
            facts.append(
                _observation_fact(
                    observation=observation,
                    fact_type="metadata_search_result",
                    subject=observation.source_id,
                    value=value,
                    canonical_claim=canonical_claim,
                )
            )
    elif observation.tool == "inspect_method_il" and data.get("symbol"):
        symbol = str(data["symbol"])
        facts.append(
            _observation_fact(
                observation=observation,
                fact_type="inspected_symbol",
                subject=symbol,
                value={"symbol": symbol},
                canonical_claim=f"Observed inspected symbol: {symbol}.",
            )
        )
        body_value = {
            "metadata_token": str(data.get("metadata_token") or ""),
            "rva": data.get("rva"),
            "has_method_body": data.get("has_method_body") is True,
            "instruction_count": data.get("instruction_count"),
            "instructions_truncated": data.get("instructions_truncated") is True,
        }
        facts.append(
            _observation_fact(
                observation=observation,
                fact_type="method_body_metadata",
                subject=symbol,
                value=body_value,
                canonical_claim=(
                    f"Observed method body metadata for {symbol}: "
                    f"metadata_token={body_value['metadata_token']}; "
                    f"rva={body_value['rva']}; "
                    "has_method_body="
                    f"{str(body_value['has_method_body']).lower()}; "
                    f"instruction_count={body_value['instruction_count']}; "
                    "instructions_truncated="
                    f"{str(body_value['instructions_truncated']).lower()}."
                ),
            )
        )
        instructions = data.get("instructions")
        if isinstance(instructions, list):
            opcodes = [
                str(item.get("opcode"))
                for item in instructions
                if isinstance(item, dict) and item.get("opcode")
            ]
            if opcodes:
                facts.append(
                    _observation_fact(
                        observation=observation,
                        fact_type="instruction_sequence",
                        subject=symbol,
                        value={"opcodes": opcodes},
                        canonical_claim=(
                            f"Observed IL instruction sequence for {symbol}: "
                            f"{', '.join(opcodes)}."
                        ),
                    )
                )
            for instruction in instructions:
                if not isinstance(instruction, dict):
                    continue
                offset = str(instruction.get("offset") or "")
                opcode = str(instruction.get("opcode") or "")
                resolved = str(instruction.get("resolved") or "")
                if opcode in {"ldfld", "ldsfld"} and resolved:
                    facts.append(
                        _observation_fact(
                            observation=observation,
                            fact_type="field_read",
                            subject=symbol,
                            value={
                                "offset": offset,
                                "opcode": opcode,
                                "field": resolved,
                            },
                            canonical_claim=(
                                f"Observed IL field read in {symbol}: "
                                f"offset={offset}; opcode={opcode}; field={resolved}."
                            ),
                        )
                    )
                if opcode in {"call", "callvirt", "newobj"} and resolved:
                    facts.append(
                        _observation_fact(
                            observation=observation,
                            fact_type="call_target",
                            subject=symbol,
                            value={
                                "offset": offset,
                                "opcode": opcode,
                                "target": resolved,
                            },
                            canonical_claim=(
                                f"Observed IL call target in {symbol}: "
                                f"offset={offset}; opcode={opcode}; target={resolved}."
                            ),
                        )
                    )
    return facts


def _observation_fact(
    *,
    observation: ToolObservation,
    fact_type: str,
    subject: str,
    value: dict[str, object],
    canonical_claim: str,
) -> dict[str, object]:
    digest = hashlib.sha256(
        _canonical_json(
            {
                "observation_id": observation.observation_id,
                "observation_sha256": observation.identity_sha256(),
                "source_id": observation.source_id,
                "fact_type": fact_type,
                "subject": subject,
                "value": value,
                "canonical_claim": canonical_claim,
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "fact_id": f"{observation.observation_id}:{fact_type}:{digest}",
        "observation_id": observation.observation_id,
        "observation_sha256": observation.identity_sha256(),
        "source_id": observation.source_id,
        "fact_type": fact_type,
        "subject": subject,
        "value": value,
        "canonical_claim": canonical_claim,
    }


def observation_fact_integrity_valid(
    *,
    fact: object,
    observation_tool: str,
    observation_source_id: str,
    observation_sha256: str,
) -> bool:
    """Validate one persisted fact against its deterministic identity contract."""

    if not isinstance(fact, dict) or set(fact) != {
        "fact_id",
        "observation_id",
        "observation_sha256",
        "source_id",
        "fact_type",
        "subject",
        "value",
        "canonical_claim",
    }:
        return False
    fact_id = fact.get("fact_id")
    observation_id = fact.get("observation_id")
    fact_observation_sha256 = fact.get("observation_sha256")
    source_id = fact.get("source_id")
    fact_type = fact.get("fact_type")
    subject = fact.get("subject")
    value = fact.get("value")
    canonical_claim = fact.get("canonical_claim")
    if not all(
        isinstance(item, str) and bool(item)
        for item in (
            fact_id,
            observation_id,
            fact_observation_sha256,
            source_id,
            fact_type,
            subject,
            canonical_claim,
        )
    ) or not isinstance(value, dict):
        return False
    if (
        source_id != observation_source_id
        or fact_observation_sha256 != observation_sha256
        or len(observation_sha256) != 64
        or any(character not in "0123456789abcdef" for character in observation_sha256)
    ):
        return False
    allowed_fact_types = {
        "search_dotnet_metadata": {"metadata_search_result"},
        "inspect_method_il": {
            "inspected_symbol",
            "method_body_metadata",
            "instruction_sequence",
            "field_read",
            "call_target",
        },
    }
    if fact_type not in allowed_fact_types.get(observation_tool, set()):
        return False
    expected_claim = _canonical_claim_for_persisted_fact(
        fact_type=fact_type,
        subject=subject,
        value=value,
    )
    if canonical_claim != expected_claim:
        return False
    digest = hashlib.sha256(
        _canonical_json(
            {
                "observation_id": observation_id,
                "observation_sha256": fact_observation_sha256,
                "source_id": source_id,
                "fact_type": fact_type,
                "subject": subject,
                "value": value,
                "canonical_claim": canonical_claim,
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return fact_id == f"{observation_id}:{fact_type}:{digest}"


def observed_conclusion_matches_bound_fact(
    *,
    conclusion: object,
    fact: object,
    observation_id: str,
    observation_tool: str,
    observation_source_id: str,
    observation_sha256: str,
) -> bool:
    """Match one observed conclusion to one integrity-valid observation fact."""

    if (
        not isinstance(conclusion, dict)
        or conclusion.get("claim_status") != "observed"
        or not isinstance(fact, dict)
        or fact.get("observation_id") != observation_id
    ):
        return False
    if not observation_fact_integrity_valid(
        fact=fact,
        observation_tool=observation_tool,
        observation_source_id=observation_source_id,
        observation_sha256=observation_sha256,
    ):
        return False
    return (
        conclusion.get("claim") == fact.get("canonical_claim")
        and conclusion.get("observation_ids") == [fact.get("observation_id")]
    )


def _canonical_claim_for_persisted_fact(
    *,
    fact_type: str,
    subject: str,
    value: dict[str, object],
) -> str | None:
    if fact_type == "metadata_search_result":
        legacy_fields = {
            "queries",
            "matched_counts",
            "returned_counts",
            "results_truncated",
            "truncated_by_kind",
        }
        current_fields = legacy_fields | {
            "matched_query_counts",
            "returned_query_counts",
        }
        if frozenset(value) not in {
            frozenset(legacy_fields),
            frozenset(current_fields),
        }:
            return None
        queries = value.get("queries")
        matched_counts = value.get("matched_counts")
        returned_counts = value.get("returned_counts")
        truncated_by_kind = value.get("truncated_by_kind")
        if (
            not isinstance(queries, list)
            or any(not isinstance(item, str) for item in queries)
            or not isinstance(matched_counts, dict)
            or not isinstance(returned_counts, dict)
            or not isinstance(truncated_by_kind, dict)
            or not isinstance(value.get("results_truncated"), bool)
        ):
            return None
        if set(value) == legacy_fields:
            return (
                "Observed metadata search result: "
                f"matched_counts={_canonical_json(matched_counts)}; "
                f"returned_counts={_canonical_json(returned_counts)}; "
                "results_truncated="
                f"{str(value['results_truncated']).lower()}."
            )
        matched_query_counts = value.get("matched_query_counts")
        returned_query_counts = value.get("returned_query_counts")
        if not isinstance(matched_query_counts, dict) or not isinstance(
            returned_query_counts, dict
        ):
            return None
        return (
            "Observed metadata search result: "
            f"matched_counts={_canonical_json(matched_counts)}; "
            f"matched_query_counts={_canonical_json(matched_query_counts)}; "
            f"returned_counts={_canonical_json(returned_counts)}; "
            f"returned_query_counts={_canonical_json(returned_query_counts)}; "
            "results_truncated="
            f"{str(value['results_truncated']).lower()}."
        )
    if fact_type == "inspected_symbol":
        if value != {"symbol": subject}:
            return None
        return f"Observed inspected symbol: {subject}."
    if fact_type == "method_body_metadata":
        if set(value) != {
            "metadata_token",
            "rva",
            "has_method_body",
            "instruction_count",
            "instructions_truncated",
        }:
            return None
        if (
            not isinstance(value.get("metadata_token"), str)
            or not isinstance(value.get("has_method_body"), bool)
            or not isinstance(value.get("instructions_truncated"), bool)
            or not isinstance(value.get("instruction_count"), int)
            or isinstance(value.get("instruction_count"), bool)
            or (
                value.get("rva") is not None
                and (
                    not isinstance(value.get("rva"), int)
                    or isinstance(value.get("rva"), bool)
                )
            )
        ):
            return None
        return (
            f"Observed method body metadata for {subject}: "
            f"metadata_token={value['metadata_token']}; "
            f"rva={value['rva']}; "
            f"has_method_body={str(value['has_method_body']).lower()}; "
            f"instruction_count={value['instruction_count']}; "
            "instructions_truncated="
            f"{str(value['instructions_truncated']).lower()}."
        )
    if fact_type == "instruction_sequence":
        opcodes = value.get("opcodes")
        if (
            set(value) != {"opcodes"}
            or not isinstance(opcodes, list)
            or not opcodes
            or any(not isinstance(item, str) or not item for item in opcodes)
        ):
            return None
        return f"Observed IL instruction sequence for {subject}: {', '.join(opcodes)}."
    if fact_type == "field_read":
        if set(value) != {"offset", "opcode", "field"}:
            return None
        offset = value.get("offset")
        opcode = value.get("opcode")
        field = value.get("field")
        if (
            not isinstance(offset, str)
            or opcode not in {"ldfld", "ldsfld"}
            or not isinstance(field, str)
            or not field
        ):
            return None
        return (
            f"Observed IL field read in {subject}: "
            f"offset={offset}; opcode={opcode}; field={field}."
        )
    if fact_type == "call_target":
        if set(value) != {"offset", "opcode", "target"}:
            return None
        offset = value.get("offset")
        opcode = value.get("opcode")
        target = value.get("target")
        if (
            not isinstance(offset, str)
            or opcode not in {"call", "callvirt", "newobj"}
            or not isinstance(target, str)
            or not target
        ):
            return None
        return (
            f"Observed IL call target in {subject}: "
            f"offset={offset}; opcode={opcode}; target={target}."
        )
    return None


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class EvidenceDiscoveryResult:
    """Intelligent discovery result plus deterministically derived audit facts."""

    run_status: str
    pack: EvidencePack
    actions: tuple[dict[str, object], ...]
    observations: tuple[ToolObservation, ...]
    input_audit: dict[str, int]
    intelligence_transfer: dict[str, bool]
    agent_discovery: dict[str, object] | None = None


def validate_agent_discovery_actual(value: dict[str, object]) -> None:
    """Validate the versioned actual-only requirement and search projection."""

    if set(value) != {
        "schema_version",
        "planning_status",
        "requirement_projection",
        "search_plan",
    }:
        raise ValueError("AGENT_DISCOVERY_ACTUAL_SHAPE_INVALID")
    if value.get("schema_version") != AGENT_DISCOVERY_ACTUAL_SCHEMA_VERSION:
        raise ValueError("AGENT_DISCOVERY_ACTUAL_VERSION_INVALID")
    status = value.get("planning_status")
    if status not in {
        "ready",
        "requirement_projection_insufficient",
        "search_planning_insufficient",
    }:
        raise ValueError("AGENT_DISCOVERY_PLANNING_STATUS_INVALID")
    projection = value.get("requirement_projection")
    if not isinstance(projection, dict):
        raise ValueError("REQUIREMENT_PROJECTION_MUST_BE_OBJECT")
    _validate_requirement_projection(
        projection,
        require_meaningful=status != "requirement_projection_insufficient",
    )
    search_plan = value.get("search_plan")
    if status == "requirement_projection_insufficient":
        if search_plan is not None:
            raise ValueError("REQUIREMENT_PROJECTION_INSUFFICIENT_HAS_SEARCH_PLAN")
        return
    if not isinstance(search_plan, dict):
        raise ValueError("SEARCH_PLAN_MUST_BE_OBJECT")
    _validate_search_plan(search_plan, require_queries=status == "ready")
    if status != "ready":
        return
    requirement_ids = {
        str(item["requirement_id"])
        for item in projection["planning_blocking_questions"]
        if isinstance(item, dict)
    }
    for question in search_plan["engineering_questions"]:
        if any(value not in requirement_ids for value in question["requirement_ids"]):
            raise ValueError("SEARCH_PLAN_ENGINEERING_REQUIREMENT_UNKNOWN")
    referenced_requirement_ids = {
        str(value)
        for question in search_plan["engineering_questions"]
        for value in question["requirement_ids"]
    }
    if referenced_requirement_ids != requirement_ids:
        raise ValueError("SEARCH_PLAN_ENGINEERING_REQUIREMENT_COVERAGE_INVALID")
    question_ids = {
        str(question["question_id"])
        for question in search_plan["engineering_questions"]
    }
    planned_question_ids = {
        str(value)
        for family in search_plan["query_families"]
        for value in family["question_ids"]
    }
    search_plan_version = search_plan.get("schema_version")
    if search_plan_version == SEARCH_PLAN_SCHEMA_VERSION:
        initial_focus_question_id = str(
            search_plan.get("initial_focus_question_id") or ""
        )
        if initial_focus_question_id not in planned_question_ids:
            raise ValueError("SEARCH_PLAN_INITIAL_FOCUS_FAMILY_MISSING")
    elif planned_question_ids != question_ids:
        raise ValueError("SEARCH_PLAN_QUERY_FAMILY_QUESTION_COVERAGE_INVALID")
    if search_plan_version != _SEARCH_PLAN_SCHEMA_VERSION_V2:
        lane_question_ids = {
            str(value)
            for lane in search_plan["planned_lanes"]
            for value in lane["question_ids"]
        }
        if lane_question_ids != question_ids:
            raise ValueError("SEARCH_PLAN_LANE_QUESTION_COVERAGE_INVALID")


def normalize_agent_discovery_planning_actual(
    value: dict[str, object],
) -> dict[str, object]:
    """Classify plan executability from validated actual content, not model opinion."""

    if set(value) != {
        "schema_version",
        "planning_status",
        "requirement_projection",
        "search_plan",
    }:
        raise ValueError("AGENT_DISCOVERY_ACTUAL_SHAPE_INVALID")
    if value.get("schema_version") != AGENT_DISCOVERY_ACTUAL_SCHEMA_VERSION:
        raise ValueError("AGENT_DISCOVERY_ACTUAL_VERSION_INVALID")
    if value.get("planning_status") not in {
        "ready",
        "requirement_projection_insufficient",
        "search_planning_insufficient",
    }:
        raise ValueError("AGENT_DISCOVERY_PLANNING_STATUS_INVALID")
    projection = value.get("requirement_projection")
    if not isinstance(projection, dict):
        raise ValueError("REQUIREMENT_PROJECTION_MUST_BE_OBJECT")
    _validate_requirement_projection(projection, require_meaningful=False)
    projection_is_meaningful = bool(
        _nonempty_string(projection.get("behavior_goal"))
        and projection.get("planning_blocking_questions")
    )
    search_plan = value.get("search_plan")
    if not projection_is_meaningful:
        if search_plan is not None:
            raise ValueError("REQUIREMENT_PROJECTION_INSUFFICIENT_HAS_SEARCH_PLAN")
        normalized_status = "requirement_projection_insufficient"
    else:
        if not isinstance(search_plan, dict):
            raise ValueError("SEARCH_PLAN_MUST_BE_OBJECT")
        _validate_search_plan(search_plan, require_queries=False)
        normalized_status = (
            "ready"
            if search_plan.get("engineering_questions")
            and search_plan.get("query_families")
            and search_plan.get("planned_lanes")
            else "search_planning_insufficient"
        )
    normalized = {
        **value,
        "planning_status": normalized_status,
    }
    validate_agent_discovery_actual(normalized)
    return normalized


def agent_discovery_early_termination_state(
    value: dict[str, object],
) -> dict[str, object]:
    """Project one validated pre-tool planning stop without inventing Hook semantics."""

    validate_agent_discovery_actual(value)
    status = value["planning_status"]
    if status == "requirement_projection_insufficient":
        code = "REQUIREMENT_PROJECTION_INSUFFICIENT"
        message = (
            "The request could not be projected into a meaningful Hook Discovery "
            "engineering problem."
        )
    elif status == "search_planning_insufficient":
        code = "SEARCH_PLANNING_INSUFFICIENT"
        message = (
            "The projected engineering problem did not produce an executable "
            "bounded search plan."
        )
    else:
        raise ValueError("AGENT_DISCOVERY_EARLY_TERMINATION_STATUS_INVALID")
    blockers = (
        {"code": code, "message": message, "needed_evidence": [message]},
    )
    return {
        "run_status": status,
        "readiness": "insufficient",
        "can_generate_patch": False,
        "gaps": (message,),
        "blockers": blockers,
        "missing_evidence": missing_evidence_from_blockers(blockers),
        "message": message,
    }


def evidence_discovery_planning_schema() -> dict[str, object]:
    """Return the provider-neutral first-turn planning response schema."""

    string_array = {
        "type": "array",
        "items": {"type": "string", "minLength": 1},
    }
    nonempty_string_array = {**string_array, "minItems": 1}
    nullable_string = {"type": ["string", "null"], "minLength": 1}
    requirement = {
        "type": "object",
        "properties": {
            "requirement_id": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Stable identity for one engineering requirement that actual "
                    "evidence must answer before implementation planning can begin."
                ),
            },
            "question": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Engineering fact that must be established from authorized actual "
                    "sources. This is not a request-clarification question or an "
                    "expected-answer field."
                ),
            },
        },
        "required": ["requirement_id", "question"],
        "additionalProperties": False,
    }
    engineering_question = {
        "type": "object",
        "properties": {
            "question_id": {
                "type": "string",
                "minLength": 1,
                "description": "Stable identity for this search-planning question.",
            },
            "question": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Searchable engineering question derived from the referenced "
                    "planning requirements."
                ),
            },
            "requirement_ids": {
                **nonempty_string_array,
                "description": (
                    "Only requirement_id values declared in "
                    "planning_blocking_questions."
                ),
            },
        },
        "required": ["question_id", "question", "requirement_ids"],
        "additionalProperties": False,
    }
    projection = {
        "type": "object",
        "properties": {
            "schema_version": {
                "type": "string",
                "const": REQUIREMENT_PROJECTION_SCHEMA_VERSION,
            },
            "behavior_goal": {"type": "string"},
            "trigger": nullable_string,
            "actor": nullable_string,
            "target": nullable_string,
            "hard_constraints": string_array,
            "forbidden_outcomes": string_array,
            "implementation_hints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "role": {"type": "string", "enum": ["investigation_lead"]},
                    },
                    "required": ["text", "role"],
                    "additionalProperties": False,
                },
            },
            "acceptance_signals": string_array,
            "planning_blocking_questions": {
                "type": "array",
                "maxItems": 4,
                "items": requirement,
                "description": (
                    "For planning_status=ready this must be non-empty. Each entry is "
                    "an engineering requirement that authorized actual evidence must "
                    "answer before implementation planning; it is not user ambiguity, "
                    "a Golden fact, or an expected missing-evidence list. For the first "
                    "Hook Discovery slice, include only requirements needed to discover "
                    "one trigger or observation direction."
                ),
            },
            "deferred_planning_or_runtime_questions": {
                **string_array,
                "maxItems": 8,
                "description": (
                    "Downstream implementation and Runtime work that is not required to "
                    "identify the first trigger or observation direction, including "
                    "presentation or feedback effects, event deduplication, boundary "
                    "regression, and final Runtime correctness."
                ),
            },
        },
        "required": [
            "schema_version",
            "behavior_goal",
            "trigger",
            "actor",
            "target",
            "hard_constraints",
            "forbidden_outcomes",
            "implementation_hints",
            "acceptance_signals",
            "planning_blocking_questions",
            "deferred_planning_or_runtime_questions",
        ],
        "additionalProperties": False,
    }
    search_plan = {
        "type": ["object", "null"],
        "properties": {
            "schema_version": {
                "type": "string",
                "const": SEARCH_PLAN_SCHEMA_VERSION,
            },
            "engineering_questions": {
                "type": "array",
                "maxItems": 4,
                "items": engineering_question,
            },
            "initial_focus_question_id": {
                "type": ["string", "null"],
                "minLength": 1,
                "description": (
                    "Exact question_id selected by the model as the first bounded "
                    "Discovery focus. It must reference engineering_questions; the "
                    "first tool action must use a frozen query family bound to it."
                ),
            },
            "source_roles": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "minLength": 1},
                        "role": {"type": "string", "minLength": 1},
                    },
                    "required": ["source_id", "role"],
                    "additionalProperties": False,
                },
            },
            "planned_lanes": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "lane": {"type": "string", "minLength": 1},
                        "tool": {"type": "string"},
                        "source_ids": nonempty_string_array,
                        "question_ids": {
                            **nonempty_string_array,
                            "description": (
                                "Only question_id values declared in "
                                "engineering_questions."
                            ),
                        },
                    },
                    "required": ["lane", "tool", "source_ids", "question_ids"],
                    "additionalProperties": False,
                },
            },
            "query_families": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "family_id": {"type": "string", "minLength": 1},
                        "queries": {
                            **nonempty_string_array,
                            "maxItems": 8,
                            "description": (
                                "Case-insensitive literal substrings matched as an OR "
                                "union against fully qualified managed symbols. Each "
                                "broad term expands the bounded result set. Prefer short "
                                "symbol fragments or established engineering terms; do "
                                "not use space-separated behavioral sentences as primary "
                                "metadata queries."
                            ),
                        },
                        "evidence_need": {"type": "string", "minLength": 1},
                        "source_ids": nonempty_string_array,
                        "tool": {"type": "string"},
                        "question_ids": {
                            **nonempty_string_array,
                            "description": (
                                "Only question_id values declared in "
                                "engineering_questions."
                            ),
                        },
                    },
                    "required": [
                        "family_id",
                        "queries",
                        "evidence_need",
                        "source_ids",
                        "tool",
                        "question_ids",
                    ],
                    "additionalProperties": False,
                },
            },
            "initial_stop_condition": {"type": "string", "minLength": 1},
            "initial_expand_condition": {"type": "string", "minLength": 1},
        },
        "required": [
            "schema_version",
            "engineering_questions",
            "initial_focus_question_id",
            "source_roles",
            "planned_lanes",
            "query_families",
            "initial_stop_condition",
            "initial_expand_condition",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "description": (
            "For planning_status=ready: declare one or more stable planning "
            "requirements, map every requirement through engineering_questions, "
            "and let every query family reference only declared question_id values."
        ),
        "properties": {
            "action": {"type": "string", "enum": ["plan"]},
            "planning_status": {
                "type": "string",
                "enum": [
                    "ready",
                    "requirement_projection_insufficient",
                    "search_planning_insufficient",
                ],
            },
            "requirement_projection": projection,
            "search_plan": search_plan,
        },
        "required": [
            "action",
            "planning_status",
            "requirement_projection",
            "search_plan",
        ],
        "additionalProperties": False,
    }


def _validate_requirement_projection(
    value: dict[str, object], *, require_meaningful: bool
) -> None:
    required = {
        "schema_version",
        "behavior_goal",
        "trigger",
        "actor",
        "target",
        "hard_constraints",
        "forbidden_outcomes",
        "implementation_hints",
        "acceptance_signals",
        "planning_blocking_questions",
        "deferred_planning_or_runtime_questions",
    }
    if set(value) != required:
        raise ValueError("REQUIREMENT_PROJECTION_SHAPE_INVALID")
    if value.get("schema_version") != REQUIREMENT_PROJECTION_SCHEMA_VERSION:
        raise ValueError("REQUIREMENT_PROJECTION_VERSION_INVALID")
    for field_name in ("trigger", "actor", "target"):
        field_value = value.get(field_name)
        if field_value is not None and not _nonempty_string(field_value):
            raise ValueError("REQUIREMENT_PROJECTION_PARTICIPANT_INVALID")
    for field_name in (
        "hard_constraints",
        "forbidden_outcomes",
        "acceptance_signals",
        "deferred_planning_or_runtime_questions",
    ):
        _validate_string_array(value.get(field_name), field_name)
    planning_questions = value.get("planning_blocking_questions")
    if not isinstance(planning_questions, list):
        raise ValueError("PLANNING_BLOCKING_QUESTIONS_INVALID")
    requirement_ids: list[str] = []
    for question in planning_questions:
        if (
            not isinstance(question, dict)
            or set(question) != {"requirement_id", "question"}
            or not _nonempty_string(question.get("requirement_id"))
            or not _nonempty_string(question.get("question"))
        ):
            raise ValueError("PLANNING_BLOCKING_QUESTION_INVALID")
        requirement_ids.append(str(question["requirement_id"]))
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ValueError("PLANNING_REQUIREMENT_ID_DUPLICATE")
    hints = value.get("implementation_hints")
    if not isinstance(hints, list):
        raise ValueError("IMPLEMENTATION_HINTS_INVALID")
    for hint in hints:
        if (
            not isinstance(hint, dict)
            or set(hint) != {"text", "role"}
            or not _nonempty_string(hint.get("text"))
            or hint.get("role") != "investigation_lead"
        ):
            raise ValueError("IMPLEMENTATION_HINT_INVALID")
    if require_meaningful and (
        not _nonempty_string(value.get("behavior_goal"))
        or not value.get("planning_blocking_questions")
    ):
        raise ValueError("REQUIREMENT_PROJECTION_NOT_MEANINGFUL")


def validate_requirement_projection_actual(
    value: dict[str, object], *, require_meaningful: bool
) -> None:
    """Validate one frozen actual Requirement Projection in its existing owner."""

    _validate_requirement_projection(value, require_meaningful=require_meaningful)


def _validate_search_plan(value: dict[str, object], *, require_queries: bool) -> None:
    schema_version = value.get("schema_version")
    if schema_version not in {
        SEARCH_PLAN_SCHEMA_VERSION,
        *_LEGACY_SEARCH_PLAN_SCHEMA_VERSIONS,
    }:
        raise ValueError("SEARCH_PLAN_VERSION_INVALID")
    required = {
        "schema_version",
        "engineering_questions",
        "source_roles",
        "planned_lanes",
        "query_families",
        "initial_stop_condition",
        "initial_expand_condition",
    }
    if schema_version == SEARCH_PLAN_SCHEMA_VERSION:
        required.add("initial_focus_question_id")
    if set(value) != required:
        raise ValueError("SEARCH_PLAN_SHAPE_INVALID")
    engineering_questions = value.get("engineering_questions")
    source_roles = value.get("source_roles")
    lanes = value.get("planned_lanes")
    families = value.get("query_families")
    if not all(
        isinstance(item, list)
        for item in (engineering_questions, source_roles, lanes, families)
    ):
        raise ValueError("SEARCH_PLAN_COLLECTION_INVALID")
    question_ids: list[str] = []
    for item in engineering_questions:
        if (
            not isinstance(item, dict)
            or set(item) != {"question_id", "question", "requirement_ids"}
            or not _nonempty_string(item.get("question_id"))
            or not _nonempty_string(item.get("question"))
        ):
            raise ValueError("SEARCH_PLAN_ENGINEERING_QUESTION_INVALID")
        _validate_string_array(
            item.get("requirement_ids"), "requirement_ids", allow_empty=False
        )
        question_ids.append(str(item["question_id"]))
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("SEARCH_PLAN_QUESTION_ID_DUPLICATE")
    if schema_version == SEARCH_PLAN_SCHEMA_VERSION and require_queries:
        initial_focus_question_id = value.get("initial_focus_question_id")
        if not _nonempty_string(initial_focus_question_id):
            raise ValueError("SEARCH_PLAN_INITIAL_FOCUS_QUESTION_INVALID")
        if initial_focus_question_id not in question_ids:
            raise ValueError("SEARCH_PLAN_INITIAL_FOCUS_QUESTION_UNKNOWN")
    elif schema_version == SEARCH_PLAN_SCHEMA_VERSION:
        initial_focus_question_id = value.get("initial_focus_question_id")
        if initial_focus_question_id is not None and (
            not _nonempty_string(initial_focus_question_id)
            or initial_focus_question_id not in question_ids
        ):
            raise ValueError("SEARCH_PLAN_INITIAL_FOCUS_QUESTION_UNKNOWN")
    for item in source_roles:
        if not isinstance(item, dict) or set(item) != {"source_id", "role"} or not all(
            _nonempty_string(item.get(field)) for field in ("source_id", "role")
        ):
            raise ValueError("SEARCH_PLAN_SOURCE_ROLE_INVALID")
    lane_binding_keys: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
    for item in lanes:
        allowed_lane_fields = {"lane", "tool", "source_ids"}
        if schema_version != _SEARCH_PLAN_SCHEMA_VERSION_V2:
            allowed_lane_fields.add("question_ids")
        if (
            not isinstance(item, dict)
            or set(item) != allowed_lane_fields
            or not _nonempty_string(item.get("lane"))
            or item.get("tool") not in EVIDENCE_DISCOVERY_TOOLS
        ):
            raise ValueError("SEARCH_PLAN_LANE_INVALID")
        _validate_string_array(item.get("source_ids"), "source_ids", allow_empty=False)
        if schema_version != _SEARCH_PLAN_SCHEMA_VERSION_V2:
            _validate_string_array(
                item.get("question_ids"), "question_ids", allow_empty=False
            )
            if any(value not in question_ids for value in item["question_ids"]):
                raise ValueError("SEARCH_PLAN_LANE_QUESTION_UNKNOWN")
            lane_binding_key = (
                str(item["tool"]),
                tuple(str(value) for value in item["source_ids"]),
                tuple(str(value) for value in item["question_ids"]),
            )
            if lane_binding_key in lane_binding_keys:
                raise ValueError("SEARCH_PLAN_LANE_BINDING_AMBIGUOUS")
            lane_binding_keys.add(lane_binding_key)
    family_ids: list[str] = []
    dispatch_keys: set[tuple[str, str, tuple[str, ...], str]] = set()
    for item in families:
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "family_id",
                "queries",
                "evidence_need",
                "source_ids",
                "tool",
                "question_ids",
            }
            or not _nonempty_string(item.get("family_id"))
            or not _nonempty_string(item.get("evidence_need"))
            or item.get("tool") != "search_dotnet_metadata"
        ):
            raise ValueError("SEARCH_PLAN_QUERY_FAMILY_INVALID")
        _validate_string_array(item.get("queries"), "queries", allow_empty=False)
        _validate_string_array(item.get("source_ids"), "source_ids", allow_empty=False)
        _validate_string_array(item.get("question_ids"), "question_ids", allow_empty=False)
        if any(value not in question_ids for value in item["question_ids"]):
            raise ValueError("SEARCH_PLAN_QUERY_FAMILY_QUESTION_UNKNOWN")
        family_id = str(item["family_id"])
        if family_id in family_ids:
            raise ValueError("SEARCH_PLAN_QUERY_FAMILY_ID_DUPLICATE")
        family_ids.append(family_id)
        for dispatch_key in _search_plan_family_dispatch_identities(item):
            if dispatch_key in dispatch_keys:
                raise ValueError("SEARCH_PLAN_QUERY_FAMILY_DISPATCH_AMBIGUOUS")
            dispatch_keys.add(dispatch_key)
    if not all(
        _nonempty_string(value.get(field))
        for field in ("initial_stop_condition", "initial_expand_condition")
    ):
        raise ValueError("SEARCH_PLAN_STOP_EXPAND_INVALID")
    if require_queries and (
        not value.get("engineering_questions") or not families or not lanes
    ):
        raise ValueError("SEARCH_PLAN_NO_VALID_QUERY")


def _search_plan_family_dispatch_identities(
    family: dict[str, object],
) -> frozenset[tuple[str, str, tuple[str, ...], str]]:
    """Return the exact physical dispatch identities used by plan validation."""

    return frozenset(
        (
            str(family["tool"]),
            str(source_id),
            tuple(str(query) for query in family["queries"]),
            str(family["evidence_need"]),
        )
        for source_id in family["source_ids"]
    )


def _validate_string_array(
    value: object, field_name: str, *, allow_empty: bool = True
) -> None:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not _nonempty_string(item) for item in value)
        or len(value) != len(set(value))
    ):
        raise ValueError(f"{field_name.upper()}_INVALID")


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _planning_response_format() -> AgentResponseFormat:
    return AgentResponseFormat(
        name="agent_evidence_discovery_plan",
        description=(
            "Actual-only Hook Discovery requirement projection and bounded search plan."
        ),
        schema=evidence_discovery_planning_schema(),
    )


def evidence_discovery_requirement_projection_schema() -> dict[str, object]:
    """Return the bounded provider view for the first planning subturn."""

    full_schema = evidence_discovery_planning_schema()
    persistent_projection = full_schema["properties"]["requirement_projection"]
    model_projection = {
        "type": "object",
        "properties": {
            key: value
            for key, value in persistent_projection["properties"].items()
            if key != "schema_version"
        },
        "required": [
            key for key in persistent_projection["required"] if key != "schema_version"
        ],
        "additionalProperties": False,
    }
    model_projection["properties"]["planning_blocking_questions"] = {
        "type": "array",
        "maxItems": 4,
        "items": {"type": "string", "minLength": 1},
        "description": (
            "Engineering questions actual evidence must answer before implementation "
            "planning. Deterministic code assigns their identities."
        ),
    }
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "const": "project_requirements"},
            "planning_status": {
                "type": "string",
                "enum": ["ready", "requirement_projection_insufficient"],
            },
            "requirement_projection": model_projection,
        },
        "required": ["action", "planning_status", "requirement_projection"],
        "additionalProperties": False,
    }


def evidence_discovery_search_plan_schema() -> dict[str, object]:
    """Return the nested model-owned view for one frozen Search Plan subturn."""

    string_array = {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string", "minLength": 1},
    }
    model_family = {
        "type": "object",
        "properties": {
            "queries": {**string_array, "maxItems": 8},
            "evidence_need": {"type": "string", "minLength": 1},
        },
        "required": ["queries", "evidence_need"],
        "additionalProperties": False,
    }
    investigation = {
        "type": "object",
        "properties": {
            "engineering_question": {"type": "string", "minLength": 1},
            "initial_focus": {"type": "boolean"},
            "source_ids": string_array,
            "query_families": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": model_family,
            },
        },
        "required": [
            "engineering_question",
            "initial_focus",
            "source_ids",
            "query_families",
        ],
        "additionalProperties": False,
    }
    model_plan = {
        "type": ["object", "null"],
        "properties": {
            "investigations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": investigation,
            },
            "initial_stop_condition": {"type": "string", "minLength": 1},
            "initial_expand_condition": {"type": "string", "minLength": 1},
        },
        "required": [
            "investigations",
            "initial_stop_condition",
            "initial_expand_condition",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "const": "plan_search"},
            "planning_status": {
                "type": "string",
                "enum": ["ready", "search_planning_insufficient"],
            },
            "search_plan": model_plan,
        },
        "required": ["action", "planning_status", "search_plan"],
        "additionalProperties": False,
    }


def _requirement_projection_response_format() -> AgentResponseFormat:
    return AgentResponseFormat(
        name="agent_evidence_requirement_projection",
        description="Actual-only bounded Requirement Projection.",
        schema=evidence_discovery_requirement_projection_schema(),
    )


def _search_plan_response_format() -> AgentResponseFormat:
    return AgentResponseFormat(
        name="agent_evidence_search_plan",
        description="Actual-only bounded Search Plan for one frozen projection.",
        schema=evidence_discovery_search_plan_schema(),
    )


def _source_identifier_selection_response_format() -> AgentResponseFormat:
    return AgentResponseFormat(
        name="agent_evidence_source_identifier_selection",
        description=(
            "Select bounded observed identifiers for an existing frozen "
            "initial-focus family."
        ),
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "const": "select_observed_identifiers",
                },
                "selection_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "required": [
                "action",
                "selection_ids",
            ],
            "additionalProperties": False,
        },
    )


def _discovery_tool_definitions(
    *, require_family_selection: bool = False
) -> tuple[AgentToolDefinition, ...]:
    common_properties: dict[str, object] = {
        "source_id": {"type": "string", "minLength": 1},
        "evidence_need": {"type": "string", "minLength": 1},
        "derived_from_observation_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    }
    metadata_properties: dict[str, object]
    metadata_required: list[str]
    metadata_description: str
    if require_family_selection:
        metadata_properties = {
            "source_id": common_properties["source_id"],
            "family_id": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Exact family_id from frozen_actual_plan. The control layer "
                    "resolves tool, queries, evidence_need, result kinds, and limit."
                ),
            },
        }
        metadata_required = [
            "source_id",
            "family_id",
        ]
        metadata_description = (
            "Select one exact, not-yet-executed family_id from frozen_actual_plan. "
            "The control layer executes that family's queries as a case-insensitive "
            "literal-substring OR union over fully qualified managed symbols. Broad "
            "terms expand the bounded result set. Do not repeat or rewrite the "
            "family's queries, evidence_need, tool, or tuning."
        )
    else:
        metadata_properties = {
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
        }
        metadata_required = [
            "source_id",
            "evidence_need",
            "derived_from_observation_ids",
            "queries",
            "result_kinds",
            "limit_per_kind",
        ]
        metadata_description = (
            "Search managed metadata symbols in one registered source using "
            "case-insensitive literal-substring matching. Queries match fully "
            "qualified managed type, method, and field symbols; this is not "
            "behavioral or semantic search. Select result kinds and a small "
            "per-kind limit to keep the observation focused."
        )
    return (
        AgentToolDefinition(
            name="search_dotnet_metadata",
            description=metadata_description,
            parameters={
                "type": "object",
                "properties": metadata_properties,
                "required": metadata_required,
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


def evidence_discovery_finish_schema(
    *, require_requirement_binding: bool = False
) -> dict[str, object]:
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
            "requirement_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "relationship": {
                "type": "string",
                "enum": ["support", "conflict", "missing"],
            },
        },
        "required": [
            "claim",
            "claim_status",
            "observation_ids",
            "limitations",
            *(
                ["requirement_ids", "relationship"]
                if require_requirement_binding
                else []
            ),
        ],
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


def _finish_response_format(
    *, require_requirement_binding: bool = False
) -> AgentResponseFormat:
    return AgentResponseFormat(
        name="evidence_discovery_finish",
        description="Final grounded evidence decision for the bounded discovery run.",
        schema=evidence_discovery_finish_schema(
            require_requirement_binding=require_requirement_binding
        ),
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
    derived_was_provided = "derived_from_observation_ids" in arguments
    source_id = arguments.pop("source_id", None)
    evidence_need = arguments.pop("evidence_need", None)
    derived = arguments.pop("derived_from_observation_ids", None)
    family_id = arguments.pop("family_id", None)
    if name not in EVIDENCE_DISCOVERY_TOOLS:
        raise ValueError("UNKNOWN_EVIDENCE_TOOL")
    if name == "search_dotnet_metadata" and family_id is not None:
        if arguments or evidence_need is not None or derived_was_provided:
            raise ValueError("QUERY_FAMILY_SELECTION_ARGUMENTS_INVALID")
        return {
            "action": "use_tool",
            "tool": name,
            "source_id": source_id,
            "family_id": family_id,
            "derived_from_observation_ids": [],
        }
    return {
        "action": "use_tool",
        "tool": name,
        "source_id": source_id,
        "arguments": arguments,
        "evidence_need": evidence_need,
        "derived_from_observation_ids": derived,
    }
