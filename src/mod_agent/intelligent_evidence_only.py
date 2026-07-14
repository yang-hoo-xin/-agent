"""CLI-facing intelligent evidence-only vertical slice."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.core.settings import load_settings
from src.libs.llm import QwenChatAgentAdapter

from .artifacts import ArtifactRef, ArtifactStore
from .evidence import (
    EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
    EvidenceDiscoveryAgentModel,
    EvidenceDiscoveryDisclosure,
    EvidenceDiscoverySource,
    EvidenceDiscoverySpecialist,
    IntelligentEvidencePackFactory,
    LocalAssemblyEvidenceToolExecutor,
    evidence_discovery_source_from_definition,
)
from .knowledge import SourceDefinition
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


class IntelligentEvidenceEntryError(RuntimeError):
    """Raised when the intelligent evidence-only entry cannot run truthfully."""


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
    inspector_path: str | Path = _DEFAULT_INSPECTOR,
) -> dict[str, Any]:
    """Run model-selected read-only tools inside the graph and stop after evidence."""

    request = description.strip()
    if not request:
        raise IntelligentEvidenceEntryError(
            "intelligent-evidence-request requires a non-empty request."
        )
    if not allow_evidence_disclosure:
        raise IntelligentEvidenceEntryError(
            "intelligent-evidence-request requires --allow-evidence-disclosure before "
            "sending the request, source views, or metadata/IL observations to the model."
        )
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
    sources = load_evidence_discovery_sources(source_registry_path)
    resolved_artifact_root = _resolve_artifact_root(artifact_root)
    run_id = f"intelligent_evidence_{uuid4().hex}"
    request_id = f"request_{uuid4().hex}"
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
    store = ArtifactStore(resolved_artifact_root)
    graph = build_graph(
        store,
        evidence_pack_factory=evidence_factory,
        use_default_proposal_git_binding=False,
        stop_after_evidence=True,
    )
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
            "Intelligent evidence-only run crossed its stop boundary: "
            + ", ".join(forbidden)
        )
    if evidence_factory.last_result is None or "evidence_pack" not in result["artifacts"]:
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
    return {
        "status": evidence_factory.last_result.run_status,
        "command": "intelligent-evidence-request",
        "execution_mode": "intelligent_evidence_only",
        "run_id": run_id,
        "feature_id": result["feature_id"],
        "current_stage": result["current_stage"],
        "stopped_before": "implementation_plan",
        "target_source_writes_performed": False,
        "external_model_called": True,
        "source_ids": [source.source_id for source in sources],
        "source_roots_disclosed_to_model": False,
        "disclosure": model.disclosure_record,
        "artifacts": dict(result["artifacts"]),
        "artifact_hashes": dict(result["artifact_hashes"]),
        "forbidden_artifacts_present": forbidden,
        "evidence_pack": pack,
    }


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
