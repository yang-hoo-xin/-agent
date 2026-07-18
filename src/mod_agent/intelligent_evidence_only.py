"""CLI-facing intelligent evidence-only vertical slice."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.core.settings import load_settings
from src.libs.llm import (
    AgentTurnProviderError,
    OllamaChatAgentAdapter,
    QwenChatAgentAdapter,
)

from .artifacts import ArtifactRef, ArtifactStore
from .evidence import (
    EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
    EvidenceDiscoveryAgentModel,
    EvidenceDiscoveryDisclosure,
    EvidenceDiscoveryLocalExecution,
    EvidenceDiscoverySource,
    EvidenceDiscoverySpecialist,
    IntelligentEvidencePackFactory,
    LocalAssemblyEvidenceToolExecutor,
    evidence_discovery_source_from_definition,
)
from .evidence.discovery_contract import EVIDENCE_DISCOVERY_TOOLS
from .knowledge import SourceDefinition
from .domain.wallcrawler_acceptance import evaluate_wallcrawler_evidence
from .planning.models import stable_feature_id
from .workflow import build_graph, create_initial_state

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_INSPECTOR = (
    _PROJECT_ROOT
    / "scripts"
    / "r8_il_inspector"
    / "bin"
    / "Debug"
    / "net7.0"
    / "r8_il_inspector.dll"
)
_REGISTRY_SCHEMA = "evidence_discovery_source_registry_v1"
_SOURCE_FIELDS = frozenset({"source_id", "source_type", "root_path", "metadata"})
_SOURCE_TYPES = frozenset(
    {
        "target_source",
        "reference_mod",
        "decompiled_api",
        "domain_note",
        "prior_artifact",
        "build_log",
        "runtime_log",
        "manual_note",
        "screenshot",
    }
)
_EVIDENCE_ONLY_ARTIFACT_TYPES = (
    "evidence_run_attempt",
    "request_planning_report",
    "mod_planning_brief",
    "feature_spec",
    "evidence_pack",
)


class IntelligentEvidenceEntryError(RuntimeError):
    """Raised when the intelligent evidence-only entry cannot run truthfully."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic or {})


def load_evidence_discovery_sources(
    registry_path: str | Path,
) -> tuple[EvidenceDiscoverySource, ...]:
    """Load strict machine-local source bindings without exposing roots to the model."""

    path = Path(registry_path).resolve()
    if not path.is_file():
        raise IntelligentEvidenceEntryError(f"Source registry is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntelligentEvidenceEntryError("Source registry is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "sources"}:
        raise IntelligentEvidenceEntryError(
            "Source registry must contain exactly schema_version and sources."
        )
    if payload.get("schema_version") != _REGISTRY_SCHEMA:
        raise IntelligentEvidenceEntryError("Source registry schema_version mismatch.")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise IntelligentEvidenceEntryError("Source registry sources must be a non-empty list.")
    sources: list[EvidenceDiscoverySource] = []
    for raw in raw_sources:
        if not isinstance(raw, dict) or set(raw) != _SOURCE_FIELDS:
            raise IntelligentEvidenceEntryError(
                "Each source must contain exactly source_id, source_type, root_path, and metadata."
            )
        if not isinstance(raw["metadata"], dict):
            raise IntelligentEvidenceEntryError("Source metadata must be an object.")
        for field_name in ("source_id", "source_type", "root_path"):
            if not isinstance(raw[field_name], str) or not raw[field_name].strip():
                raise IntelligentEvidenceEntryError(
                    f"Source {field_name} must be a non-empty string."
                )
        if raw["source_type"] not in _SOURCE_TYPES:
            raise IntelligentEvidenceEntryError(
                f"Unsupported source_type: {raw['source_type']!r}"
            )
        sources.append(
            evidence_discovery_source_from_definition(
                SourceDefinition(
                    source_id=raw["source_id"],
                    source_type=raw["source_type"],
                    root_path=raw["root_path"],
                    metadata=dict(raw["metadata"]),
                    allowed_extensions=frozenset({".dll"}),
                )
            )
        )
    if len({source.source_id for source in sources}) != len(sources):
        raise IntelligentEvidenceEntryError("Source registry source_ids must be unique.")
    return tuple(sources)


def run_intelligent_evidence_only(
    *,
    description: str,
    source_registry_path: str | Path,
    artifact_root: str | Path,
    settings_path: str | Path,
    allow_evidence_disclosure: bool,
    target_domain: str = "gtfo",
    target_mod: str = "WallCrawler",
    api_key_env: str = "DASHSCOPE_API_KEY",
    base_url_env: str = "DASHSCOPE_BASE_URL",
    local_ollama: bool = False,
    ollama_base_url: str = "http://127.0.0.1:11434",
    ollama_model: str = "qwen3:4b-instruct",
    ollama_max_output_tokens: int = 4096,
    inspector_path: str | Path = _DEFAULT_INSPECTOR,
) -> dict[str, Any]:
    """Run model-selected read-only tools inside the graph and stop after evidence."""

    request = description.strip()
    if not request:
        raise IntelligentEvidenceEntryError(
            "intelligent-evidence-request requires a non-empty request."
        )
    if local_ollama and allow_evidence_disclosure:
        raise IntelligentEvidenceEntryError(
            "Choose exactly one model boundary: --local-ollama or "
            "--allow-evidence-disclosure."
        )
    if not local_ollama and not allow_evidence_disclosure:
        raise IntelligentEvidenceEntryError(
            "intelligent-evidence-request requires --local-ollama for on-device "
            "inference or --allow-evidence-disclosure for an external model."
        )
    sources = load_evidence_discovery_sources(source_registry_path)
    resolved_artifact_root = _resolve_artifact_root(artifact_root)
    store = ArtifactStore(resolved_artifact_root)
    feature_id = stable_feature_id(request)
    store.preflight_atomic_commit(
        feature_id=feature_id,
        artifact_types=_EVIDENCE_ONLY_ARTIFACT_TYPES,
    )
    run_id = f"intelligent_evidence_{uuid4().hex}"
    request_id = f"request_{uuid4().hex}"
    if local_ollama:
        client = OllamaChatAgentAdapter(
            base_url=ollama_base_url,
            model=ollama_model,
            max_output_tokens=ollama_max_output_tokens,
        )
        model = EvidenceDiscoveryAgentModel(
            client,
            local_execution=EvidenceDiscoveryLocalExecution(
                endpoint=client.base_url,
                provider=client.provider,
                model=client.model,
            ),
        )
    else:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise IntelligentEvidenceEntryError(
                f"Required API key environment variable is missing: {api_key_env}"
            )
        settings = load_settings(settings_path)
        base_url = os.environ.get(base_url_env) or settings.llm.base_url
        if not base_url:
            raise IntelligentEvidenceEntryError(
                f"Required LLM base URL is missing from settings and environment: {base_url_env}"
            )
        model = EvidenceDiscoveryAgentModel(
            QwenChatAgentAdapter(
                api_key=api_key,
                base_url=base_url,
                model=settings.llm.model,
                max_completion_tokens=settings.llm.max_tokens,
            ),
            disclosure=EvidenceDiscoveryDisclosure(
                approved=True,
                approval_id=f"cli:{run_id}",
                destination={
                    "provider": "qwen_chat",
                    "model": settings.llm.model,
                },
                approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
            ),
        )
    executor = LocalAssemblyEvidenceToolExecutor.from_inspector(inspector_path)
    evidence_factory = IntelligentEvidencePackFactory(
        specialist=EvidenceDiscoverySpecialist(
            model=model,
            tool_executor=executor,
        ),
        sources=sources,
    )
    graph = build_graph(
        store,
        evidence_pack_factory=evidence_factory,
        use_default_proposal_git_binding=False,
        stop_after_evidence=True,
    )
    store.write(
        feature_id=feature_id,
        artifact_type="evidence_run_attempt",
        payload=_evidence_run_attempt_payload(
            run_id=run_id,
            request_id=request_id,
            model=model,
            local_ollama=local_ollama,
            run_validity="attempt_started",
            terminal_stage="before_graph",
            accepted_model_actions=0,
            tool_calls_executed=0,
            failure_attribution="unresolved",
            failure={},
        ),
        status="running",
    )
    try:
        result = graph.invoke(
            create_initial_state(
                run_id=run_id,
                request_id=request_id,
                user_request=request,
                target_domain=target_domain,
                target_mod=target_mod,
            )
        )
        forbidden = sorted(
            artifact_type
            for artifact_type in (
                "implementation_plan",
                "patch_proposal",
                "proposal_review",
                "dry_run_result",
                "isolated_apply_result",
                "build_result",
                "runtime_evidence",
            )
            if artifact_type in result["artifacts"]
        )
        if forbidden:
            raise IntelligentEvidenceEntryError(
                "Intelligent evidence-only run crossed its stop boundary."
            )
        if (
            evidence_factory.last_result is None
            or "evidence_pack" not in result["artifacts"]
        ):
            raise IntelligentEvidenceEntryError(
                "Intelligent evidence-only run did not produce an evidence_pack."
            )
        evidence_ref = ArtifactRef(
            feature_id=result["feature_id"] or result["request_id"],
            artifact_type="evidence_pack",
            path=result["artifacts"]["evidence_pack"],
            artifact_hash=result["artifact_hashes"]["evidence_pack"],
        )
        pack = store.read(evidence_ref)["data"]
    except (OSError, RuntimeError, ValueError) as exc:
        error_code = _evidence_run_failure_code(exc)
        failure_attribution = _failure_attribution(model=model, error=error_code)
        failed_ref = store.write(
            feature_id=feature_id,
            artifact_type="evidence_run_attempt",
            payload=_evidence_run_attempt_payload(
                run_id=run_id,
                request_id=request_id,
                model=model,
                local_ollama=local_ollama,
                run_validity="invalid_run",
                terminal_stage=(
                    "tool_call_validation"
                    if error_code == "UNKNOWN_EVIDENCE_TOOL"
                    else "evidence_retrieval"
                ),
                accepted_model_actions=_accepted_model_action_count(
                    evidence_factory=evidence_factory,
                    model=model,
                ),
                tool_calls_executed=_executed_tool_call_count(evidence_factory),
                failure_attribution=failure_attribution,
                failure={
                    "exception_type": type(exc).__name__,
                    "code": error_code,
                },
            ),
            status="failed",
        )
        raise IntelligentEvidenceEntryError(
            error_code,
            diagnostic={
                "category": "evidence_run_failure",
                "stage": "tool_call_validation"
                if error_code == "UNKNOWN_EVIDENCE_TOOL"
                else "evidence_retrieval",
                "code": error_code,
                "run_id": run_id,
                "attempt_artifact": {
                    "path": failed_ref.path,
                    "artifact_hash": failed_ref.artifact_hash,
                },
                "external_model_calls": _external_model_call_count(
                    model=model,
                    local_ollama=local_ollama,
                ),
                "accepted_model_actions": _accepted_model_action_count(
                    evidence_factory=evidence_factory,
                    model=model,
                ),
                "tool_calls_executed": _executed_tool_call_count(evidence_factory),
                "failure_attribution": failure_attribution,
            },
        ) from exc
    completed_attempt_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_run_attempt",
        payload=_evidence_run_attempt_payload(
            run_id=run_id,
            request_id=request_id,
            model=model,
            local_ollama=local_ollama,
            run_validity="valid_run",
            terminal_stage="evidence_retrieval",
            accepted_model_actions=_accepted_model_action_count(
                evidence_factory=evidence_factory,
                model=model,
            ),
            tool_calls_executed=_executed_tool_call_count(evidence_factory),
            failure_attribution="none",
            failure={},
        ),
        status="success",
    )
    output = {
        "status": evidence_factory.last_result.run_status,
        "command": "intelligent-evidence-request",
        "execution_mode": "intelligent_evidence_only",
        "run_id": run_id,
        "feature_id": result["feature_id"],
        "current_stage": result["current_stage"],
        "stopped_before": "implementation_plan",
        "target_source_writes_performed": False,
        "external_model_called": not local_ollama,
        "local_model_called": local_ollama,
        "source_ids": [source.source_id for source in sources],
        "source_roots_disclosed_to_model": False,
        "model_execution": model.disclosure_record,
        "disclosure": model.disclosure_record,
        "artifacts": dict(result["artifacts"]),
        "artifact_hashes": dict(result["artifact_hashes"]),
        "attempt_artifact": {
            "path": completed_attempt_ref.path,
            "artifact_hash": completed_attempt_ref.artifact_hash,
        },
        "forbidden_artifacts_present": forbidden,
        "evidence_pack": pack,
    }
    acceptance = _post_run_acceptance(
        target_domain=target_domain,
        target_mod=target_mod,
        evidence_pack=pack,
        current_stage=str(result["current_stage"]),
        forbidden_artifacts=forbidden,
    )
    if acceptance is not None:
        output["acceptance"] = acceptance
    return output


def _post_run_acceptance(
    *,
    target_domain: str,
    target_mod: str,
    evidence_pack: dict[str, Any],
    current_stage: str,
    forbidden_artifacts: list[str],
) -> dict[str, object] | None:
    """Apply the same WallCrawler evaluator regardless of model provider."""

    if target_domain != "gtfo" or target_mod != "WallCrawler":
        return None
    return evaluate_wallcrawler_evidence(
        evidence_pack=evidence_pack,
        current_stage=current_stage,
        forbidden_artifacts=forbidden_artifacts,
    )


def _resolve_artifact_root(path: str | Path) -> Path:
    value = Path(path)
    resolved = value.resolve() if value.is_absolute() else (_PROJECT_ROOT / value).resolve()
    try:
        resolved.relative_to(_PROJECT_ROOT)
    except ValueError as exc:
        raise IntelligentEvidenceEntryError(
            "artifact_root must stay inside the project root."
        ) from exc
    return resolved


def _evidence_run_attempt_payload(
    *,
    run_id: str,
    request_id: str,
    model: EvidenceDiscoveryAgentModel,
    local_ollama: bool,
    run_validity: str,
    terminal_stage: str,
    accepted_model_actions: int,
    tool_calls_executed: int,
    failure_attribution: str,
    failure: dict[str, object],
) -> dict[str, object]:
    model_calls = int(getattr(model, "model_call_count", 0))
    provider_turns = getattr(model, "provider_turn_records", ())
    return {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": (
            "Durable identity and sanitized provider diagnostics for one bounded "
            "evidence discovery attempt."
        ),
        "run_id": run_id,
        "request_id": request_id,
        "run_validity": run_validity,
        "terminal_stage": terminal_stage,
        "model_execution": model.disclosure_record,
        "model_calls": model_calls,
        "external_model_calls": 0 if local_ollama else model_calls,
        "accepted_model_actions": accepted_model_actions,
        "tool_calls_executed": tool_calls_executed,
        "provider_turns": [dict(item) for item in provider_turns],
        "failure_attribution": failure_attribution,
        "failure": dict(failure),
    }


def _accepted_model_action_count(
    *,
    evidence_factory: IntelligentEvidencePackFactory,
    model: EvidenceDiscoveryAgentModel,
) -> int:
    """Count accepted model tool actions and accepted model finish actions."""

    result = evidence_factory.last_result
    if result is None:
        return int(getattr(model, "accepted_action_count", 0))
    return sum(
        1
        for item in result.pack.model_action_trace
        if item.get("origin") == "model" and item.get("status") == "accepted"
    )


def _executed_tool_call_count(
    evidence_factory: IntelligentEvidencePackFactory,
) -> int:
    result = evidence_factory.last_result
    return len(result.actions) if result is not None else 0


def _external_model_call_count(
    *,
    model: EvidenceDiscoveryAgentModel,
    local_ollama: bool,
) -> int:
    return 0 if local_ollama else int(getattr(model, "model_call_count", 0))


def _failure_attribution(
    *,
    model: EvidenceDiscoveryAgentModel,
    error: str,
) -> str:
    if error != "UNKNOWN_EVIDENCE_TOOL":
        return "unresolved"
    records = getattr(model, "provider_turn_records", ())
    if not records:
        return "unresolved"
    tool_calls = records[-1].get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return "unresolved"
    latest = tool_calls[-1]
    if not isinstance(latest, dict):
        return "unresolved"
    provider_name = str(latest.get("provider_reported_tool_name") or "")
    adapter_name = str(latest.get("adapter_extracted_tool_name") or "")
    if not provider_name:
        return "unresolved"
    if provider_name not in EVIDENCE_DISCOVERY_TOOLS:
        if provider_name.strip() in EVIDENCE_DISCOVERY_TOOLS:
            return "whitespace_normalization_issue"
        return "model_or_provider_emitted_unknown_tool"
    if adapter_name not in EVIDENCE_DISCOVERY_TOOLS:
        return "provider_adapter_extraction_failure"
    return "unresolved"


def _evidence_run_failure_code(exc: BaseException) -> str:
    if str(exc) == "UNKNOWN_EVIDENCE_TOOL":
        return "UNKNOWN_EVIDENCE_TOOL"
    if isinstance(exc, AgentTurnProviderError):
        return "AGENT_TURN_PROVIDER_ERROR"
    if isinstance(exc, OSError):
        return "EVIDENCE_RUN_OS_ERROR"
    if isinstance(exc, ValueError):
        return "EVIDENCE_RUN_VALIDATION_ERROR"
    return "EVIDENCE_RUN_RUNTIME_ERROR"
