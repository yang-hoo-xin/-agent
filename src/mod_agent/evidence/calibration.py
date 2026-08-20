"""Actual-only entry adapters for the two calibration/development requests.

The adapters deliberately receive no Golden annotation, historical answer,
expected Runtime support, fixed-answer test result, or prior Agent/RAG output.
They register only the natural-language request and the bounded current-source
roots. Requirement Projection, Search Planning, and bounded discovery belong to
the later Agent Evidence Discovery phase and are not reproduced here.
"""

from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)

from .models import EvidencePack, EvidenceRequest
from .retriever import DeterministicEvidenceRetriever
from .discovery_contract import (
    EvidenceDiscoveryModel,
    EvidenceDiscoveryRequest,
    EvidenceDiscoverySource,
    EvidenceDiscoveryToolExecutor,
)
from .discovery_loop import EvidenceDiscoverySpecialist

if TYPE_CHECKING:
    from src.mod_agent.evaluation.hidden_golden import CommittedCalibrationActual

PHASE_1_DIAGNOSTIC_COMPARISON_STATUS = (
    "phase_1_diagnostic_noncomparable_due_to_request_byte_identity_drift"
)


class ActualExecutionIsolationError(ValueError):
    """Raised when an actual-only run cannot bind its declared input roots."""


def run_better_hit_feedback_calibration(
    *,
    r8_root: str | Path,
    request: str,
    model: EvidenceDiscoveryModel | None = None,
    tool_executor: EvidenceDiscoveryToolExecutor | None = None,
    sources: tuple[EvidenceDiscoverySource, ...] = (),
    run_id: str | None = None,
    request_id: str | None = None,
) -> EvidencePack:
    """Run BHF actual retrieval with no answer-bearing technical inputs."""

    source_root = _required_directory(
        Path(r8_root).resolve() / "Assets" / "Scripts" / "Modules-ASM",
        role="r8_modules_source",
    )
    discovery = _phase_2_dependencies(
        model=model,
        tool_executor=tool_executor,
        sources=sources,
    )
    with tempfile.TemporaryDirectory(prefix="rag_er_bhf_") as temp_dir:
        retriever = _build_retriever(
            database_path=Path(temp_dir) / "knowledge.db",
            sources=(
                SourceDefinition(
                    source_id="r8_modules_source",
                    source_type="decompiled_api",
                    root_path=source_root,
                    metadata={"evidence_authority": "supporting"},
                    allowed_extensions=frozenset({".cs"}),
                ),
            ),
        )
        if discovery is not None:
            return _run_phase_2_discovery(
                request=request,
                dependencies=discovery,
                source_retriever=retriever,
                source_ids=("r8_modules_source",),
                run_id=run_id,
                request_id=request_id,
            )
        return retriever.retrieve(
            _actual_only_request(request=request, max_items=30),
        )


def run_wall_crawler_calibration(
    *,
    r8_root: str | Path,
    request: str,
    model: EvidenceDiscoveryModel | None = None,
    tool_executor: EvidenceDiscoveryToolExecutor | None = None,
    sources: tuple[EvidenceDiscoverySource, ...] = (),
    run_id: str | None = None,
    request_id: str | None = None,
) -> EvidencePack:
    """Run WallCrawler actual retrieval with no expected-gap inputs."""

    r8_path = Path(r8_root).resolve()
    modules_root = _required_directory(
        r8_path / "Assets" / "Scripts" / "Modules-ASM",
        role="r8_modules_source",
    )
    datablocks_root = _required_directory(
        r8_path / "Datablocks",
        role="r8_datablocks",
    )
    discovery = _phase_2_dependencies(
        model=model,
        tool_executor=tool_executor,
        sources=sources,
    )
    with tempfile.TemporaryDirectory(prefix="rag_er_wc_") as temp_dir:
        retriever = _build_retriever(
            database_path=Path(temp_dir) / "knowledge.db",
            sources=(
                SourceDefinition(
                    source_id="r8_modules_source",
                    source_type="decompiled_api",
                    root_path=modules_root,
                    metadata={"evidence_authority": "supporting"},
                    allowed_extensions=frozenset({".cs"}),
                ),
                SourceDefinition(
                    source_id="r8_datablocks",
                    source_type="domain_note",
                    root_path=datablocks_root,
                    metadata={"evidence_authority": "supporting"},
                    allowed_extensions=frozenset({".json"}),
                ),
            ),
        )
        if discovery is not None:
            return _run_phase_2_discovery(
                request=request,
                dependencies=discovery,
                source_retriever=retriever,
                source_ids=("r8_modules_source", "r8_datablocks"),
                run_id=run_id,
                request_id=request_id,
            )
        return retriever.retrieve(
            _actual_only_request(request=request, max_items=50),
        )


def commit_better_hit_feedback_calibration_actual(
    *,
    case_root: str | Path,
    r8_root: str | Path,
    store: ArtifactStore,
    feature_spec_ref: ArtifactRef,
    run_id: str,
    request_id: str,
    model: EvidenceDiscoveryModel | None = None,
    tool_executor: EvidenceDiscoveryToolExecutor | None = None,
    sources: tuple[EvidenceDiscoverySource, ...] = (),
) -> "CommittedCalibrationActual":
    """Bind the BHF adapter to the shared committed-actual owner."""

    from src.mod_agent.evaluation.hidden_golden import (
        commit_manifest_bound_calibration_actual,
    )

    def execute(*, r8_root: Path, request: str) -> EvidencePack:
        return run_better_hit_feedback_calibration(
            r8_root=r8_root,
            request=request,
            model=model,
            tool_executor=tool_executor,
            sources=sources,
            run_id=run_id,
            request_id=request_id,
        )

    return commit_manifest_bound_calibration_actual(
        case_root=case_root,
        corpus_root=r8_root,
        store=store,
        feature_spec_ref=feature_spec_ref,
        run_id=run_id,
        request_id=request_id,
        executor=execute,
    )


def commit_wall_crawler_calibration_actual(
    *,
    case_root: str | Path,
    r8_root: str | Path,
    store: ArtifactStore,
    feature_spec_ref: ArtifactRef,
    run_id: str,
    request_id: str,
    model: EvidenceDiscoveryModel | None = None,
    tool_executor: EvidenceDiscoveryToolExecutor | None = None,
    sources: tuple[EvidenceDiscoverySource, ...] = (),
) -> "CommittedCalibrationActual":
    """Bind the WallCrawler adapter to the shared committed-actual owner."""

    from src.mod_agent.evaluation.hidden_golden import (
        commit_manifest_bound_calibration_actual,
    )

    def execute(*, r8_root: Path, request: str) -> EvidencePack:
        return run_wall_crawler_calibration(
            r8_root=r8_root,
            request=request,
            model=model,
            tool_executor=tool_executor,
            sources=sources,
            run_id=run_id,
            request_id=request_id,
        )

    return commit_manifest_bound_calibration_actual(
        case_root=case_root,
        corpus_root=r8_root,
        store=store,
        feature_spec_ref=feature_spec_ref,
        run_id=run_id,
        request_id=request_id,
        executor=execute,
    )


def _actual_only_request(*, request: str, max_items: int) -> EvidenceRequest:
    normalized = request.strip()
    if not normalized:
        raise ActualExecutionIsolationError(
            "Actual execution requires a non-empty natural-language request."
        )
    return EvidenceRequest(
        query=normalized,
        requires_hook_evidence=True,
        max_items=max_items,
        hook_requirement={
            "required": True,
            "reason": "natural_language_gameplay_behavior_requires_discovery",
        },
    )


def _phase_2_dependencies(
    *,
    model: EvidenceDiscoveryModel | None,
    tool_executor: EvidenceDiscoveryToolExecutor | None,
    sources: tuple[EvidenceDiscoverySource, ...],
) -> tuple[
    EvidenceDiscoveryModel,
    EvidenceDiscoveryToolExecutor,
    tuple[EvidenceDiscoverySource, ...],
] | None:
    supplied = (model is not None, tool_executor is not None, bool(sources))
    if not any(supplied):
        return None
    if not all(supplied):
        raise ActualExecutionIsolationError(
            "Phase 2 discovery requires model, tool_executor, and sources together."
        )
    assert model is not None and tool_executor is not None
    return model, tool_executor, sources


def _run_phase_2_discovery(
    *,
    request: str,
    dependencies: tuple[
        EvidenceDiscoveryModel,
        EvidenceDiscoveryToolExecutor,
        tuple[EvidenceDiscoverySource, ...],
    ],
    source_retriever: DeterministicEvidenceRetriever,
    source_ids: tuple[str, ...],
    run_id: str | None,
    request_id: str | None,
) -> EvidencePack:
    normalized = request.strip()
    if not normalized:
        raise ActualExecutionIsolationError(
            "Actual execution requires a non-empty natural-language request."
        )
    model, tool_executor, sources = dependencies
    request_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    bound_run_id = run_id or f"phase-2-discovery-{request_digest[:16]}"
    bound_request_id = request_id or f"actual-request-{request_digest[16:32]}"

    retrieve_source_evidence = _source_evidence_retrieval_callback(
        source_retriever=source_retriever,
        source_ids=source_ids,
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=tool_executor,
        source_evidence_retriever=retrieve_source_evidence,
    ).discover(
        EvidenceDiscoveryRequest(
            run_id=bound_run_id,
            request_id=bound_request_id,
            natural_language_request=normalized,
            sources=sources,
            max_tool_calls=4,
            max_model_steps=5,
            require_actual_planning=True,
        )
    )
    return result.pack


def _source_evidence_retrieval_callback(
    *,
    source_retriever: DeterministicEvidenceRetriever,
    source_ids: tuple[str, ...],
) -> Callable[[tuple[dict[str, str], ...]], EvidencePack]:
    def retrieve_source_evidence(
        source_queries: tuple[dict[str, str], ...],
    ) -> EvidencePack:
        if not source_queries:
            raise ActualExecutionIsolationError(
                "Source evidence retrieval requires a bounded query set."
            )
        return source_retriever.retrieve_query_set(
            queries=source_queries,
            source_ids=source_ids,
            per_query_lane_max_items=3,
            max_items=36,
        )

    return retrieve_source_evidence


# Current assemblies, the R8 assembly, an inspector executable, and
# LocalAssemblyEvidenceToolExecutor are legitimate actual-side physical inputs
# or effect adapters for Phase 2. They may be consumed only after an earlier
# actual discovery step has produced the exact symbol identity to verify. This
# Phase 1 adapter has no discovery step, so it does not accept or invoke those
# inputs; their absence here must not be interpreted as an oracle boundary.
def _required_directory(path: Path, *, role: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ActualExecutionIsolationError(
            f"Actual input role {role} is not a readable directory: {resolved}"
        )
    return resolved


def _build_retriever(
    *,
    database_path: Path,
    sources: tuple[SourceDefinition, ...],
) -> DeterministicEvidenceRetriever:
    database = KnowledgeDatabase(database_path)
    registry = SourceRegistry(database)
    indexer = IncrementalIndexer(database=database, source_registry=registry)
    source_ids: list[str] = []
    for source in sources:
        registry.register(source)
        report = indexer.index_source(source.source_id)
        if report.failed_files:
            raise ValueError(
                f"Source indexing failed for {source.source_id}: {report.failures}"
            )
        source_ids.append(source.source_id)
    indexer.build_retrieval_snapshot(tuple(source_ids))
    return DeterministicEvidenceRetriever(database)


def calibration_summary(pack: EvidencePack) -> str:
    """Return a stable human-readable JSON projection of one actual result."""

    semantics = pack.hook_discovery or {}
    return json.dumps(
        {
            "comparison_status": PHASE_1_DIAGNOSTIC_COMPARISON_STATUS,
            "manifest_bound_comparable": False,
            "query": pack.query,
            "readiness": pack.readiness,
            "can_generate_patch": pack.can_generate_patch,
            "hook_discovery": semantics,
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
