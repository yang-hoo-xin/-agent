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
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

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

PHASE_1_DIAGNOSTIC_COMPARISON_STATUS = (
    "phase_1_diagnostic_noncomparable_due_to_request_byte_identity_drift"
)


class ActualExecutionIsolationError(ValueError):
    """Raised when an actual-only run cannot bind its declared input roots."""


class HiddenGoldenCalibrationError(ValueError):
    """Raised when calibration actual isolation or identity binding is invalid."""


@dataclass(frozen=True)
class HiddenGoldenActualInput:
    """Manifest-bound input that is safe to expose to actual discovery."""

    case_identity: str
    request_text: str
    request_sha256: str
    declared_corpus_snapshot_sha256: str
    observed_corpus_snapshot_sha256: str | None
    source_allowlist: tuple[str, ...]
    excluded_source_classes: tuple[str, ...]


@dataclass(frozen=True)
class CommittedCalibrationActual:
    """Strictly rehydrated actual identity ready for expected-side evaluation."""

    store: ArtifactStore
    actual_ref: ArtifactRef
    actual_input: HiddenGoldenActualInput
    feature_spec_ref: ArtifactRef
    run_id: str
    request_id: str
    evidence_pack: EvidencePack


def load_hidden_golden_actual_input(
    case_root: str | Path,
    *,
    corpus_root: str | Path | None = None,
    corpus_snapshot_resolver: Callable[[Path, tuple[str, ...]], str] | None = None,
) -> HiddenGoldenActualInput:
    """Load only manifest/request facts; never open the annotation."""

    root = Path(case_root)
    manifest = _load_actual_object(root / "corpus_manifest.json")
    case_identity = _required_actual_string(manifest, "case_identity")
    request_spec = _required_actual_object(manifest, "request")
    request_ref = _required_actual_string(request_spec, "ref")
    request_ref_path = PurePosixPath(request_ref)
    if (
        request_ref_path.name != "request.txt"
        or request_ref_path.parent.name != root.name
    ):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_REF_INVALID")
    request_bytes = _canonical_actual_request_bytes((root / "request.txt").read_bytes())
    request_sha256 = _actual_sha256(request_bytes)
    if request_sha256 != _required_actual_string(request_spec, "sha256"):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_HASH_MISMATCH")
    try:
        request_text = request_bytes.decode("utf-8").rstrip("\n")
    except UnicodeDecodeError as exc:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_NOT_UTF8") from exc
    if not request_text.strip():
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_EMPTY")

    scope = _required_actual_object(manifest, "actual_retrieval_scope")
    if scope.get("mode") != "allowlist_only":
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_SOURCE_SCOPE_NOT_ALLOWLIST")
    source_allowlist = _actual_string_tuple(scope, "search_root_allowlist")
    excluded = _actual_string_tuple(scope, "excluded_source_classes")
    if "technical_annotation" not in excluded or "prior_agent_or_rag_outputs" not in excluded:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_EXPECTED_EXCLUSION_MISSING")
    snapshot = _required_actual_object(manifest, "canonical_corpus_snapshot")
    snapshot_allowlist = _actual_string_tuple(snapshot, "search_root_allowlist")
    if snapshot_allowlist != source_allowlist:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_CORPUS_ALLOWLIST_MISMATCH")

    declared_snapshot = _required_actual_string(snapshot, "corpus_snapshot_sha256")
    observed_snapshot: str | None = None
    if corpus_root is not None:
        if corpus_snapshot_resolver is None:
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_CORPUS_SNAPSHOT_RESOLVER_REQUIRED"
            )
        observed_snapshot = corpus_snapshot_resolver(
            Path(corpus_root).resolve(),
            source_allowlist,
        )
        if not isinstance(observed_snapshot, str) or not observed_snapshot:
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_CORPUS_SNAPSHOT_OBSERVATION_INVALID"
            )
        if observed_snapshot != declared_snapshot:
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_CORPUS_SNAPSHOT_MISMATCH"
            )

    return HiddenGoldenActualInput(
        case_identity=case_identity,
        request_text=request_text,
        request_sha256=request_sha256,
        declared_corpus_snapshot_sha256=declared_snapshot,
        observed_corpus_snapshot_sha256=observed_snapshot,
        source_allowlist=source_allowlist,
        excluded_source_classes=excluded,
    )


def commit_manifest_bound_calibration_actual(
    *,
    case_root: str | Path,
    corpus_root: str | Path,
    store: ArtifactStore,
    feature_spec_ref: ArtifactRef,
    run_id: str,
    request_id: str,
    corpus_snapshot_resolver: Callable[[Path, tuple[str, ...]], str],
    executor: Callable[..., EvidencePack],
) -> CommittedCalibrationActual:
    """Execute and commit one manifest-bound actual without expected-side inputs."""

    actual_input = load_hidden_golden_actual_input(
        case_root,
        corpus_root=corpus_root,
        corpus_snapshot_resolver=corpus_snapshot_resolver,
    )
    if (
        actual_input.observed_corpus_snapshot_sha256 is None
        or actual_input.observed_corpus_snapshot_sha256
        != actual_input.declared_corpus_snapshot_sha256
    ):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_CORPUS_SNAPSHOT_NOT_BOUND"
        )
    if not isinstance(run_id, str) or not run_id.strip():
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_RUN_ID_INVALID")
    if not isinstance(request_id, str) or not request_id.strip():
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_ID_INVALID")
    if not callable(executor):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_EXECUTOR_INVALID")
    if feature_spec_ref.artifact_type != "feature_spec":
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_FEATURE_SPEC_REF_TYPE_INVALID"
        )
    if not feature_spec_ref.feature_id:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_FEATURE_SPEC_IDENTITY_INVALID"
        )

    pack = executor(
        r8_root=Path(corpus_root).resolve(),
        request=actual_input.request_text,
        run_id=run_id,
        request_id=request_id,
    )
    if not isinstance(pack, EvidencePack):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_EXECUTOR_RESULT_INVALID"
        )
    if pack.query != actual_input.request_text:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_REQUEST_MISMATCH"
        )
    if pack.provenance_validation.get("run_id") != run_id:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_RUN_ID_MISMATCH"
        )
    if pack.provenance_validation.get("request_id") != request_id:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_REQUEST_ID_MISMATCH"
        )

    manifest_binding = {
        "case_identity": actual_input.case_identity,
        "request_sha256": actual_input.request_sha256,
        "declared_corpus_snapshot_sha256": (
            actual_input.declared_corpus_snapshot_sha256
        ),
        "observed_corpus_snapshot_sha256": (
            actual_input.observed_corpus_snapshot_sha256
        ),
        "source_allowlist": list(actual_input.source_allowlist),
    }
    existing_manifest_binding = pack.provenance_validation.get(
        "manifest_bound_actual"
    )
    if (
        existing_manifest_binding is not None
        and existing_manifest_binding != manifest_binding
    ):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_MANIFEST_BINDING_MISMATCH"
        )
    pack = replace(
        pack,
        provenance_validation={
            **pack.provenance_validation,
            "manifest_bound_actual": manifest_binding,
        },
    )
    payload = pack.to_artifact_payload()
    if not EvidencePack.requires_strict_semantic_rehydrate(payload):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_NOT_SEMANTIC"
        )
    try:
        EvidencePack.from_artifact_payload(payload)
    except ValueError as exc:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_REHYDRATE_FAILED"
        ) from exc
    _validate_committed_actual_model_identity(pack.model_identity)

    # The executor has finished before any FeatureSpec payload becomes visible.
    feature_envelope = store.read(feature_spec_ref)
    feature_payload = feature_envelope.get("data")
    if (
        not isinstance(feature_payload, dict)
        or feature_payload.get("user_request") != actual_input.request_text
        or feature_payload.get("target_behavior") != actual_input.request_text
    ):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_FEATURE_REQUEST_MISMATCH"
        )

    actual_ref = store.write(
        feature_id=feature_spec_ref.feature_id,
        artifact_type="evidence_pack",
        payload=payload,
        status="success" if pack.can_generate_patch else "blocked",
        upstream_refs=[feature_spec_ref],
    )
    envelope = store.read(actual_ref)
    committed_payload = envelope.get("data")
    if not isinstance(committed_payload, dict):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_COMMITTED_ACTUAL_PAYLOAD_INVALID"
        )
    if not EvidencePack.requires_strict_semantic_rehydrate(committed_payload):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_COMMITTED_ACTUAL_NOT_SEMANTIC"
        )
    try:
        committed_pack = EvidencePack.from_artifact_payload(committed_payload)
    except ValueError as exc:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_COMMITTED_ACTUAL_REHYDRATE_FAILED"
        ) from exc
    if committed_pack.query != actual_input.request_text:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_COMMITTED_ACTUAL_REQUEST_MISMATCH"
        )

    return CommittedCalibrationActual(
        store=store,
        actual_ref=actual_ref,
        actual_input=actual_input,
        feature_spec_ref=feature_spec_ref,
        run_id=run_id,
        request_id=request_id,
        evidence_pack=committed_pack,
    )


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
    corpus_snapshot_resolver: Callable[[Path, tuple[str, ...]], str],
    model: EvidenceDiscoveryModel | None = None,
    tool_executor: EvidenceDiscoveryToolExecutor | None = None,
    sources: tuple[EvidenceDiscoverySource, ...] = (),
) -> "CommittedCalibrationActual":
    """Bind the BHF adapter to the shared committed-actual owner."""

    def execute(
        *,
        r8_root: Path,
        request: str,
        run_id: str,
        request_id: str,
    ) -> EvidencePack:
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
        corpus_snapshot_resolver=corpus_snapshot_resolver,
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
    corpus_snapshot_resolver: Callable[[Path, tuple[str, ...]], str],
    model: EvidenceDiscoveryModel | None = None,
    tool_executor: EvidenceDiscoveryToolExecutor | None = None,
    sources: tuple[EvidenceDiscoverySource, ...] = (),
) -> "CommittedCalibrationActual":
    """Bind the WallCrawler adapter to the shared committed-actual owner."""

    def execute(
        *,
        r8_root: Path,
        request: str,
        run_id: str,
        request_id: str,
    ) -> EvidencePack:
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
        corpus_snapshot_resolver=corpus_snapshot_resolver,
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


def _validate_committed_actual_model_identity(
    identity: Mapping[str, Any],
) -> None:
    execution_kind = identity.get("execution_kind")
    if execution_kind == "local_agent_turn_adapter":
        required = ("provider", "model", "endpoint")
    elif execution_kind == "external_agent_turn_adapter":
        required = ("provider", "model", "approval_id")
    elif execution_kind == "injected_local_or_test":
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_TEST_MODEL_IDENTITY_FORBIDDEN"
        )
    else:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_MODEL_EXECUTION_KIND_INVALID"
        )
    if any(
        not isinstance(identity.get(field), str) or not identity.get(field)
        for field in required
    ):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_MODEL_IDENTITY_INCOMPLETE"
        )


def _canonical_actual_request_bytes(raw: bytes) -> bytes:
    canonical = raw.replace(b"\r\n", b"\n")
    if b"\r" in canonical:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_REQUEST_LINE_ENDING_INVALID"
        )
    return canonical


def _load_actual_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JSON_READ_FAILED") from exc
    if not isinstance(value, dict):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JSON_OBJECT_REQUIRED")
    return value


def _required_actual_object(
    value: Mapping[str, Any],
    field: str,
) -> dict[str, Any]:
    result = value.get(field)
    if not isinstance(result, dict):
        raise HiddenGoldenCalibrationError(f"HIDDEN_GOLDEN_{field.upper()}_INVALID")
    return result


def _required_actual_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise HiddenGoldenCalibrationError(f"HIDDEN_GOLDEN_{field.upper()}_INVALID")
    return result


def _actual_string_tuple(value: Mapping[str, Any], field: str) -> tuple[str, ...]:
    result = value.get(field)
    if not isinstance(result, list) or not all(
        isinstance(item, str) and item for item in result
    ):
        raise HiddenGoldenCalibrationError(f"HIDDEN_GOLDEN_{field.upper()}_INVALID")
    return tuple(result)


def _actual_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


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
