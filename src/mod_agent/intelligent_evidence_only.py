"""CLI-facing intelligent evidence-only vertical slice."""

from __future__ import annotations

import json
import hashlib
import os
import traceback
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

_CODE_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _CODE_ROOT
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
_PHASE1_LINEAGE_SCHEMA = "phase1_source_bound_no_write_v1"
_PHASE1_SOURCE_ID = "gtfo-r8-modules-asm"
_PHASE1_SOURCE_TYPE = "decompiled_api"
_PHASE1_ASSEMBLY_RELATIVE_PATH = "Modules-ASM.dll"
_PHASE1_ASSEMBLY_SHA256 = (
    "DD0C57D5C527E78B40FAB798456EDD73413DA0F140995A63FCA3619C36C32698"
)
_PHASE1_MODULE_MVID = "28e7d845-eb8b-48af-a5b2-9b1addb278ae"
_PHASE1_METHOD_SYMBOL = "Player.PlayerCharacterController.Move"
_PHASE1_FORBIDDEN_ARTIFACT_TYPES = (
    "implementation_plan",
    "patch_proposal",
    "proposal_review",
    "dry_run_result",
    "isolated_apply_result",
    "build_result",
    "runtime_evidence",
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
    phase1_lineage: bool = False,
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
    if phase1_lineage and (not local_ollama or allow_evidence_disclosure):
        raise IntelligentEvidenceEntryError(
            "Phase 1 lineage validation requires local Ollama and forbids external fallback."
        )
    sources = load_evidence_discovery_sources(source_registry_path)
    phase1_bindings: dict[str, dict[str, object]] | None = None
    if phase1_lineage:
        sources = tuple(
            source for source in sources if source.source_id == _PHASE1_SOURCE_ID
        )
        if len(sources) != 1:
            raise IntelligentEvidenceEntryError(
                "Phase 1 approved source is not uniquely registered."
            )
        phase1_bindings = {
            "request_binding": _phase1_request_binding(
                request=request,
                target_domain=target_domain,
                target_mod=target_mod,
            ),
            "platform_source_binding": _phase1_platform_source_binding(),
            "target_source_binding": _phase1_target_source_binding(
                registry_path=source_registry_path,
                sources=sources,
            ),
            "authorization_boundary": _phase1_authorization_boundary(),
        }
    resolved_artifact_root = _resolve_artifact_root(artifact_root)
    store = ArtifactStore(resolved_artifact_root)
    feature_id = stable_feature_id(request)
    store.preflight_atomic_commit(
        feature_id=feature_id,
        artifact_types=(
            _EVIDENCE_ONLY_ARTIFACT_TYPES
            + ("workflow_trace", "evidence_post_run_validation")
            if phase1_lineage
            else _EVIDENCE_ONLY_ARTIFACT_TYPES
        ),
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
    started_attempt_ref = store.write(
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
            phase1_bindings=phase1_bindings,
            lineage={"status": "started"} if phase1_lineage else None,
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
            for artifact_type in _PHASE1_FORBIDDEN_ARTIFACT_TYPES
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
        terminal_run_status = str(getattr(exc, "run_status", "") or "")
        failure_attribution = _failure_attribution(model=model, error=error_code)
        failure_diagnostics = _failed_run_diagnostics(
            evidence_factory=evidence_factory,
            error=exc,
        )
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
                    "symbolic_code": failure_diagnostics[
                        "symbolic_failure_code"
                    ],
                },
                failure_diagnostics=failure_diagnostics,
                phase1_bindings=phase1_bindings,
                lineage=(
                    {
                        "status": "failed_before_terminal_validation",
                        "started_attempt": _artifact_identity(started_attempt_ref),
                    }
                    if phase1_lineage
                    else None
                ),
            ),
            status="failed",
            upstream_refs=[started_attempt_ref] if phase1_lineage else None,
            exact_revision_upstream_types=(
                {"evidence_run_attempt"} if phase1_lineage else None
            ),
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
                "failure_diagnostics": failure_diagnostics,
                **(
                    {"run_status": terminal_run_status}
                    if terminal_run_status
                    else {}
                ),
            },
        ) from exc
    acceptance = _post_run_acceptance(
        target_domain=target_domain,
        target_mod=target_mod,
        evidence_pack=pack,
        current_stage=str(result["current_stage"]),
        forbidden_artifacts=forbidden,
    )
    workflow_trace_ref: ArtifactRef | None = None
    validation_ref: ArtifactRef | None = None
    lineage_checks: dict[str, bool] | None = None
    if phase1_lineage:
        assert phase1_bindings is not None
        terminal_platform_binding = _phase1_platform_source_binding()
        terminal_target_binding = _phase1_target_source_binding(
            registry_path=source_registry_path,
            sources=sources,
        )
        workflow_trace_ref = store.write(
            feature_id=feature_id,
            artifact_type="workflow_trace",
            payload={
                "node_name": "persist_workflow_trace",
                "stage": "workflow",
                "message": "Persisted LangGraph trace for one source-bound no-write run.",
                "run_id": run_id,
                "request_id": request_id,
                "feature_id": feature_id,
                "terminal_stage": str(result["current_stage"]),
                "event_count": len(result["trace_events"]),
                "events": [dict(item) for item in result["trace_events"]],
                "artifact_hashes": dict(result["artifact_hashes"]),
            },
            status="success",
            upstream_refs=_result_artifact_refs(result),
        )
        lineage_checks = _phase1_lineage_checks(
            run_id=run_id,
            request_id=request_id,
            result=result,
            evidence_pack=pack,
            forbidden=forbidden,
            model=model,
            initial_platform_binding=phase1_bindings["platform_source_binding"],
            terminal_platform_binding=terminal_platform_binding,
            initial_target_binding=phase1_bindings["target_source_binding"],
            terminal_target_binding=terminal_target_binding,
        )
        validation_ref = store.write(
            feature_id=feature_id,
            artifact_type="evidence_post_run_validation",
            payload={
                "node_name": "post_run_validation",
                "stage": "post_run_validation",
                "message": "Persisted lineage checks without changing runtime routing.",
                "run_id": run_id,
                "request_id": request_id,
                "lineage_schema_version": _PHASE1_LINEAGE_SCHEMA,
                "lineage_checks": lineage_checks,
                "lineage_passed": all(lineage_checks.values()),
                "runtime_outcome": {
                    "terminal_stage": str(result["current_stage"]),
                    "run_status": pack.get("run_status"),
                    "readiness": pack.get("readiness"),
                    "can_generate_patch": pack.get("can_generate_patch"),
                    "forbidden_artifacts_present": forbidden,
                },
                "domain_validation": acceptance,
                "affects_runtime_route": False,
                "limitations": [
                    "This validates one local no-write lineage only.",
                    "It does not prove product capability, patch safety, build, or gameplay runtime behavior.",
                ],
            },
            status="success" if all(lineage_checks.values()) else "blocked",
            blockers=[
                {
                    "code": f"PHASE1_{name.upper()}_FAILED",
                    "message": f"Phase 1 lineage check failed: {name}",
                }
                for name, passed in lineage_checks.items()
                if not passed
            ],
            upstream_refs=[evidence_ref, workflow_trace_ref],
        )
    completed_attempt_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_run_attempt",
        payload=_evidence_run_attempt_payload(
            run_id=run_id,
            request_id=request_id,
            model=model,
            local_ollama=local_ollama,
            run_validity=(
                "valid_run"
                if lineage_checks is None or all(lineage_checks.values())
                else "invalid_run"
            ),
            terminal_stage="evidence_retrieval",
            accepted_model_actions=_accepted_model_action_count(
                evidence_factory=evidence_factory,
                model=model,
            ),
            tool_calls_executed=_executed_tool_call_count(evidence_factory),
            failure_attribution="none",
            failure={},
            phase1_bindings=phase1_bindings,
            lineage=(
                {
                    "status": "terminal",
                    "started_attempt": _artifact_identity(started_attempt_ref),
                    "workflow_trace": _artifact_identity(workflow_trace_ref),
                    "post_run_validation": _artifact_identity(validation_ref),
                    "lineage_passed": all(lineage_checks.values()),
                }
                if phase1_lineage
                and workflow_trace_ref is not None
                and validation_ref is not None
                and lineage_checks is not None
                else None
            ),
        ),
        status=(
            "success"
            if lineage_checks is None or all(lineage_checks.values())
            else "failed"
        ),
        upstream_refs=(
            [started_attempt_ref, evidence_ref, workflow_trace_ref, validation_ref]
            if phase1_lineage
            and workflow_trace_ref is not None
            and validation_ref is not None
            else None
        ),
        exact_revision_upstream_types=(
            {"evidence_run_attempt"} if phase1_lineage else None
        ),
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
    if phase1_lineage:
        output["started_attempt_artifact"] = _artifact_identity(started_attempt_ref)
        output["workflow_trace_artifact"] = _artifact_identity(workflow_trace_ref)
        output["post_run_validation_artifact"] = _artifact_identity(validation_ref)
        output["phase1_lineage_passed"] = bool(
            lineage_checks and all(lineage_checks.values())
        )
    if acceptance is not None:
        output["acceptance"] = acceptance
    if lineage_checks is not None and not all(lineage_checks.values()):
        raise IntelligentEvidenceEntryError(
            "PHASE1_LINEAGE_VALIDATION_FAILED",
            diagnostic={
                "category": "phase1_lineage_validation",
                "code": "PHASE1_LINEAGE_VALIDATION_FAILED",
                "run_id": run_id,
                "attempt_artifact": _artifact_identity(completed_attempt_ref),
                "workflow_trace_artifact": _artifact_identity(workflow_trace_ref),
                "post_run_validation_artifact": _artifact_identity(validation_ref),
                "lineage_checks": lineage_checks,
            },
        )
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
    failure_diagnostics: dict[str, object] | None = None,
    phase1_bindings: dict[str, dict[str, object]] | None = None,
    lineage: dict[str, object] | None = None,
) -> dict[str, object]:
    model_calls = int(getattr(model, "model_call_count", 0))
    provider_turns = getattr(model, "provider_turn_records", ())
    payload: dict[str, object] = {
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
    if failure_diagnostics is not None:
        payload["failure_diagnostics"] = dict(failure_diagnostics)
    if phase1_bindings is not None:
        payload.update(
            {
                "lineage_schema_version": _PHASE1_LINEAGE_SCHEMA,
                "request_binding": dict(phase1_bindings["request_binding"]),
                "platform_source_binding": dict(
                    phase1_bindings["platform_source_binding"]
                ),
                "target_source_binding": dict(
                    phase1_bindings["target_source_binding"]
                ),
                "authorization_boundary": dict(
                    phase1_bindings["authorization_boundary"]
                ),
                "lineage": dict(lineage or {}),
            }
        )
    return payload


def _phase1_request_binding(
    *,
    request: str,
    target_domain: str,
    target_mod: str,
) -> dict[str, object]:
    encoded = request.encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "utf8_bytes": len(encoded),
        "target_domain": target_domain,
        "target_mod": target_mod,
        "execution_mode": "intelligent_evidence_only",
        "stop_after": "evidence_retrieval",
        "request_text_persisted": False,
    }


def _phase1_platform_source_binding() -> dict[str, object]:
    paths = sorted((_PROJECT_ROOT / "src").rglob("*.py"))
    settings_path = _PROJECT_ROOT / "config" / "settings.yaml"
    if settings_path.is_file():
        paths.append(settings_path)
    if not paths:
        raise IntelligentEvidenceEntryError(
            "Phase 1 platform source manifest has no files."
        )
    entries = []
    for path in paths:
        content = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(_PROJECT_ROOT).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return {
        "binding_kind": "file_manifest_sha256",
        "aggregate_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "file_count": len(entries),
        "files": entries,
        "absolute_paths_persisted": False,
    }


def _phase1_target_source_binding(
    *,
    registry_path: str | Path,
    sources: tuple[EvidenceDiscoverySource, ...],
) -> dict[str, object]:
    if len(sources) != 1:
        raise IntelligentEvidenceEntryError(
            "Phase 1 requires exactly one registered source."
        )
    source = sources[0]
    if source.source_id != _PHASE1_SOURCE_ID or source.source_type != _PHASE1_SOURCE_TYPE:
        raise IntelligentEvidenceEntryError(
            "Phase 1 source identity does not match the approved source."
        )
    if tuple(source.assembly_relative_paths) != (_PHASE1_ASSEMBLY_RELATIVE_PATH,):
        raise IntelligentEvidenceEntryError(
            "Phase 1 assembly binding does not match the approved source."
        )
    declared = dict(source.version_identity or {})
    if declared.get("assembly_sha256") != _PHASE1_ASSEMBLY_SHA256:
        raise IntelligentEvidenceEntryError(
            "Phase 1 declared assembly_sha256 does not match the approved source."
        )
    if declared.get("module_mvid") != _PHASE1_MODULE_MVID:
        raise IntelligentEvidenceEntryError(
            "Phase 1 declared module_mvid does not match the approved source."
        )
    assembly_path = Path(source.root_path) / _PHASE1_ASSEMBLY_RELATIVE_PATH
    content = assembly_path.read_bytes()
    observed_hash = hashlib.sha256(content).hexdigest().upper()
    if observed_hash != _PHASE1_ASSEMBLY_SHA256:
        raise IntelligentEvidenceEntryError(
            "Phase 1 live assembly SHA256 does not match the approved source."
        )
    registry_content = Path(registry_path).resolve().read_bytes()
    return {
        "source_id": source.source_id,
        "source_type": source.source_type,
        "registry_schema_version": _REGISTRY_SCHEMA,
        "registry_sha256": hashlib.sha256(registry_content).hexdigest(),
        "assembly_relative_path": _PHASE1_ASSEMBLY_RELATIVE_PATH,
        "assembly_sha256": observed_hash,
        "module_mvid": _PHASE1_MODULE_MVID,
        "source_roots_persisted": False,
    }


def _phase1_authorization_boundary() -> dict[str, object]:
    return {
        "local_ollama": True,
        "external_model_fallback": False,
        "control_artifact_writes": True,
        "target_source_writes": False,
        "proposal": False,
        "apply": False,
        "build": False,
        "game_runtime": False,
    }


def _result_artifact_refs(result: dict[str, Any]) -> list[ArtifactRef]:
    feature_id = str(result["feature_id"] or result["request_id"])
    return [
        ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=path,
            artifact_hash=str(result["artifact_hashes"][artifact_type]),
        )
        for artifact_type, path in result["artifacts"].items()
    ]


def _artifact_identity(ref: ArtifactRef | None) -> dict[str, str] | None:
    if ref is None:
        return None
    return {
        "artifact_type": ref.artifact_type,
        "path": ref.path,
        "artifact_hash": ref.artifact_hash,
    }


def _phase1_lineage_checks(
    *,
    run_id: str,
    request_id: str,
    result: dict[str, Any],
    evidence_pack: dict[str, Any],
    forbidden: list[str],
    model: EvidenceDiscoveryAgentModel,
    initial_platform_binding: dict[str, object],
    terminal_platform_binding: dict[str, object],
    initial_target_binding: dict[str, object],
    terminal_target_binding: dict[str, object],
) -> dict[str, bool]:
    items = evidence_pack.get("items")
    exact_method_inspected = isinstance(items, list) and any(
        isinstance(item, dict)
        and item.get("symbol") == _PHASE1_METHOD_SYMBOL
        and item.get("retrieval_method") == "agent_selected_cli_metadata_il_read"
        for item in items
    )
    trace_events = result.get("trace_events")
    workflow_trace_run_bound = isinstance(trace_events, list) and bool(trace_events) and all(
        isinstance(item, dict)
        and item.get("run_id") == run_id
        and item.get("feature_id") in {request_id, result.get("feature_id")}
        for item in trace_events
    )
    provenance = evidence_pack.get("provenance_validation")
    disclosure = model.disclosure_record
    return {
        "local_model_boundary": (
            disclosure.get("execution_kind") == "local_agent_turn_adapter"
            and disclosure.get("approved") is False
        ),
        "request_bound": (
            result.get("run_id") == run_id
            and result.get("request_id") == request_id
        ),
        "platform_source_unchanged": initial_platform_binding == terminal_platform_binding,
        "target_source_unchanged": initial_target_binding == terminal_target_binding,
        "evidence_pack_run_bound": (
            isinstance(provenance, dict) and provenance.get("run_id") == run_id
        ),
        "workflow_trace_run_bound": workflow_trace_run_bound,
        "expected_terminal_stage": result.get("current_stage") == "evidence_retrieval",
        "exact_method_inspected": exact_method_inspected,
        "forbidden_artifacts_absent": not forbidden,
        "no_target_source_write": initial_target_binding == terminal_target_binding,
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
    if result is not None:
        return len(result.actions)
    diagnostics = evidence_factory.runtime_diagnostics
    return int(diagnostics.get("tool_execution_completed", 0))


def _failed_run_diagnostics(
    *,
    evidence_factory: IntelligentEvidencePackFactory,
    error: BaseException,
) -> dict[str, object]:
    snapshot = evidence_factory.runtime_diagnostics
    failure_stage = str(snapshot.get("failure_stage") or "unresolved")
    if failure_stage in {"none", "not_started"}:
        failure_stage = "evidence_retrieval"
    symbolic_failure_code = str(snapshot.get("symbolic_failure_code") or "")
    if isinstance(error, AgentTurnProviderError):
        symbolic_failure_code = "AGENT_TURN_PROVIDER_ERROR"
    elif symbolic_failure_code in {"", "none"}:
        symbolic_failure_code = _evidence_run_failure_code(error)
    return {
        "schema_version": "evidence_run_failure_diagnostics_v1",
        "provider_tool_calls": int(snapshot.get("provider_tool_calls", 0)),
        "adapter_accepted_actions": int(
            snapshot.get("adapter_accepted_actions", 0)
        ),
        "deterministic_validation_passed": int(
            snapshot.get("deterministic_validation_passed", 0)
        ),
        "dispatch_started": int(snapshot.get("dispatch_started", 0)),
        "tool_execution_completed": int(
            snapshot.get("tool_execution_completed", 0)
        ),
        "observation_created": int(snapshot.get("observation_created", 0)),
        "failure_stage": failure_stage,
        "symbolic_failure_code": symbolic_failure_code,
        "correction_attempted": bool(
            snapshot.get("correction_attempted", False)
        ),
        "correction_unavailable_reason": str(
            snapshot.get("correction_unavailable_reason") or "none"
        ),
        "traceback": _sanitized_traceback(error),
    }


def _sanitized_traceback(error: BaseException) -> dict[str, object]:
    extracted = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
    frames: list[dict[str, object]] = []
    for frame in extracted:
        try:
            relative_path = Path(frame.filename).resolve().relative_to(_CODE_ROOT)
        except (OSError, ValueError):
            continue
        frames.append(
            {
                "path": relative_path.as_posix(),
                "line": frame.lineno,
                "function": frame.name,
            }
        )
    return {
        "available_in_process": error.__traceback__ is not None,
        "recoverable_from_artifact": bool(frames),
        "project_frames": frames,
        "external_frame_count": max(len(extracted) - len(frames), 0),
        "source_lines_persisted": False,
        "locals_persisted": False,
        "exception_message_persisted": False,
    }


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
