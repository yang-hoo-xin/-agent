"""Typed Fresh Artifact continuation into the existing Planning graph node."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactRegistryError,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactWriteResult,
    StaleArtifactError,
)
from src.mod_agent.bindings import BindingResolver
from src.mod_agent.evidence import EvidencePack
from src.mod_agent.evidence.identity import feature_spec_payload_sha256
from src.mod_agent.fresh_coverage import (
    FRESH_COVERAGE_MODEL_CALL_BUDGET,
    strict_feature_spec_payload,
)

PLANNING_CONTINUATION_CONTRACT_VERSION = "fresh_planning_continuation_v1"
PLANNING_CONTINUATION_RESULT_TYPE = "planning_continuation_result_v1"
PLANNING_CONSUMER_STAGE = "create_implementation_plan"
PATCH_CONTINUATION_CONTRACT_VERSION = "fresh_patch_continuation_v1"
PATCH_CONTINUATION_RESULT_TYPE = "patch_continuation_result_v1"
PATCH_CONTINUATION_RECEIPT_VERSION = "patch_continuation_attempt_v1"
PATCH_CONSUMER_STAGE = "generate_patch_proposal"


class PlanningContinuationError(ValueError):
    """Reject an invalid continuation before a later product stage can run."""

    def __init__(self, code: str, stage: str, reason: str) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.reason = reason


class PlanningContinuationArtifactWriteError(RuntimeError):
    """Carry an exact non-committed Store result out of the Planning node."""

    def __init__(self, write_result: ArtifactWriteResult) -> None:
        super().__init__("Planning continuation Artifact write did not commit.")
        self.write_result = write_result


class PatchContinuationError(ValueError):
    """Reject an invalid exact Plan continuation before unsafe progress."""

    def __init__(self, code: str, stage: str, reason: str) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True)
class PlanningContinuationInputV1:
    """Complete identity required to continue two Fresh revisions."""

    contract_version: Literal["fresh_planning_continuation_v1"]
    artifact_store_root: str
    workspace_root: str
    feature_spec_ref: ArtifactRef
    evidence_pack_ref: ArtifactRef
    planning_target_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.contract_version != PLANNING_CONTINUATION_CONTRACT_VERSION:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_VERSION_INVALID",
                "request",
                "Planning continuation contract version is invalid.",
            )
        for value, name in (
            (self.artifact_store_root, "artifact_store_root"),
            (self.workspace_root, "workspace_root"),
        ):
            if type(value) is not str or not value.strip():
                raise PlanningContinuationError(
                    "PLANNING_CONTINUATION_PATH_INVALID",
                    "request",
                    f"Planning continuation {name} must be non-empty text.",
                )
        _validate_artifact_ref(
            self.feature_spec_ref,
            field_name="feature_spec_ref",
            expected_type="feature_spec",
        )
        _validate_artifact_ref(
            self.evidence_pack_ref,
            field_name="evidence_pack_ref",
            expected_type="evidence_pack",
        )
        if self.feature_spec_ref.feature_id != self.evidence_pack_ref.feature_id:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_FEATURE_MISMATCH",
                "request",
                "Fresh FeatureSpec and EvidencePack refs have different feature_id values.",
            )


@dataclass(frozen=True)
class PatchContinuationInputV1:
    """Exact immutable Artifact selection for one Patch-to-Dry-run continuation."""

    contract_version: Literal["fresh_patch_continuation_v1"]
    artifact_store_root: str
    workspace_root: str
    feature_spec_ref: ArtifactRef
    evidence_pack_ref: ArtifactRef
    implementation_plan_ref: ArtifactRef

    def __post_init__(self) -> None:
        if self.contract_version != PATCH_CONTINUATION_CONTRACT_VERSION:
            raise PatchContinuationError(
                "PATCH_CONTINUATION_VERSION_INVALID",
                "request",
                "Patch continuation contract version is invalid.",
            )
        for value, name in (
            (self.artifact_store_root, "artifact_store_root"),
            (self.workspace_root, "workspace_root"),
        ):
            if type(value) is not str or not value.strip():
                raise PatchContinuationError(
                    "PATCH_CONTINUATION_PATH_INVALID",
                    "request",
                    f"Patch continuation {name} must be non-empty text.",
                )
        for ref, field_name, artifact_type in (
            (self.feature_spec_ref, "feature_spec_ref", "feature_spec"),
            (self.evidence_pack_ref, "evidence_pack_ref", "evidence_pack"),
            (
                self.implementation_plan_ref,
                "implementation_plan_ref",
                "implementation_plan",
            ),
        ):
            try:
                _validate_artifact_ref(
                    ref,
                    field_name=field_name,
                    expected_type=artifact_type,
                )
            except PlanningContinuationError as exc:
                raise PatchContinuationError(
                    "PATCH_CONTINUATION_REF_INVALID",
                    "request",
                    exc.reason,
                ) from exc
        feature_ids = {
            self.feature_spec_ref.feature_id,
            self.evidence_pack_ref.feature_id,
            self.implementation_plan_ref.feature_id,
        }
        if len(feature_ids) != 1:
            raise PatchContinuationError(
                "PATCH_CONTINUATION_FEATURE_MISMATCH",
                "request",
                "Selected FeatureSpec, EvidencePack, and Plan feature_id values differ.",
            )


@dataclass(frozen=True)
class PlanningContinuationResultV1:
    """Stable public result for one bounded Fresh-to-Planning continuation."""

    status: Literal["terminal", "blocked", "partial"]
    terminal_stage: str
    first_failure: dict[str, str] | None
    run_id: str
    request_id: str
    feature_id: str | None
    feature_spec_artifact: dict[str, str] | None
    evidence_pack_artifact: dict[str, str] | None
    implementation_plan_artifact: dict[str, str] | None
    plan_blocking: bool | None
    artifact_write: dict[str, Any] | None
    source_validation: dict[str, Any]
    planning_execution_count: int
    source_modified_during_run: bool | None
    duration_seconds: float
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_type": PLANNING_CONTINUATION_RESULT_TYPE,
            "status": self.status,
            "command": "continue-fresh-planning",
            "terminal_stage": self.terminal_stage,
            "first_failure": (None if self.first_failure is None else dict(self.first_failure)),
            "run_id": self.run_id,
            "request_id": self.request_id,
            "feature_id": self.feature_id,
            "feature_spec_artifact": (
                None if self.feature_spec_artifact is None else dict(self.feature_spec_artifact)
            ),
            "evidence_pack_artifact": (
                None if self.evidence_pack_artifact is None else dict(self.evidence_pack_artifact)
            ),
            "implementation_plan_artifact": (
                None
                if self.implementation_plan_artifact is None
                else dict(self.implementation_plan_artifact)
            ),
            "plan_blocking": self.plan_blocking,
            "artifact_write": (None if self.artifact_write is None else dict(self.artifact_write)),
            "source_validation": dict(self.source_validation),
            "stopped_before": "patch_proposal",
            "execution_counts": {
                "fresh_coverage": 0,
                "model": 0,
                "planning": self.planning_execution_count,
                "patch": 0,
                "apply": 0,
                "build": 0,
                "runtime": 0,
            },
            "product_source_writes_performed": False,
            "source_modified_during_run": self.source_modified_during_run,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PatchContinuationResultV1:
    """Public result for exact Plan through deterministic no-write Dry-run."""

    status: Literal["terminal", "blocked", "partial"]
    terminal_stage: str
    first_failure: dict[str, str] | None
    run_id: str
    request_id: str
    feature_id: str | None
    feature_spec_artifact: dict[str, str] | None
    evidence_pack_artifact: dict[str, str] | None
    implementation_plan_artifact: dict[str, str] | None
    patch_proposal_artifact: dict[str, str] | None
    proposal_review_artifact: dict[str, str] | None
    dry_run_artifact: dict[str, str] | None
    source_validation: dict[str, Any]
    execution_counts: dict[str, int]
    attempt_receipt: dict[str, Any] | None
    source_modified_during_run: bool | None
    duration_seconds: float
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_type": PATCH_CONTINUATION_RESULT_TYPE,
            "status": self.status,
            "command": "continue-fresh-patch",
            "terminal_stage": self.terminal_stage,
            "first_failure": (
                None if self.first_failure is None else dict(self.first_failure)
            ),
            "run_id": self.run_id,
            "request_id": self.request_id,
            "feature_id": self.feature_id,
            "feature_spec_artifact": self.feature_spec_artifact,
            "evidence_pack_artifact": self.evidence_pack_artifact,
            "implementation_plan_artifact": self.implementation_plan_artifact,
            "patch_proposal_artifact": self.patch_proposal_artifact,
            "proposal_review_artifact": self.proposal_review_artifact,
            "dry_run_artifact": self.dry_run_artifact,
            "source_validation": dict(self.source_validation),
            "stopped_before": "exact_diff_approval",
            "execution_counts": dict(self.execution_counts),
            "attempt_receipt": (
                None if self.attempt_receipt is None else dict(self.attempt_receipt)
            ),
            "product_source_writes_performed": False,
            "source_modified_during_run": self.source_modified_during_run,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class _AdmittedPlanningInputs:
    artifact_store: ArtifactStore
    feature_spec: dict[str, Any]
    evidence_pack: dict[str, Any]
    source_validation: dict[str, Any]
    source_tree_snapshot: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _AdmittedPatchInputs:
    artifact_store: ArtifactStore
    feature_spec: dict[str, Any]
    evidence_pack: dict[str, Any]
    implementation_plan: dict[str, Any]
    source_validation: dict[str, Any]
    source_tree_snapshot: tuple[tuple[str, str], ...]
    latest_observations: dict[str, dict[str, Any]]


PatchContinuationFactory = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]],
    tuple[dict[str, Any], ...],
]
PatchContinuationDryRunFactory = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]],
    dict[str, Any],
]


def _validate_artifact_ref(
    ref: Any,
    *,
    field_name: str,
    expected_type: str,
) -> None:
    if not isinstance(ref, ArtifactRef):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_REF_INVALID",
            "request",
            f"Planning continuation {field_name} must be ArtifactRef.",
        )
    if (
        type(ref.feature_id) is not str
        or not ref.feature_id
        or ref.artifact_type != expected_type
        or type(ref.path) is not str
        or not ref.path
        or not Path(ref.path).is_absolute()
        or not _is_sha256(ref.artifact_hash)
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_REF_INVALID",
            "request",
            f"Planning continuation {field_name} identity is invalid.",
        )


def _is_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))
    except (OSError, RuntimeError):
        return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _artifact_ref_dict(ref: ArtifactRef) -> dict[str, str]:
    return {
        "feature_id": ref.feature_id,
        "artifact_type": ref.artifact_type,
        "path": ref.path,
        "artifact_hash": ref.artifact_hash,
    }


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _artifact_write_projection(
    value: ArtifactWriteResult | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = value.to_dict() if isinstance(value, ArtifactWriteResult) else dict(value)
    fields = (
        "outcome",
        "artifact_hash",
        "revision_path",
        "latest_alias_path",
        "commit_started",
        "revision_state",
        "latest_alias_state",
        "pending_marker_state",
        "failure_stage",
        "failure_class",
        "recovery_available",
    )
    return {field: raw.get(field) for field in fields}


def _resolve_roots(request: PlanningContinuationInputV1) -> tuple[Path, Path]:
    try:
        artifact_root = Path(request.artifact_store_root).resolve(strict=True)
        workspace_root = Path(request.workspace_root).resolve(strict=True)
    except OSError as exc:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_ROOT_INVALID",
            "artifact_admission",
            "Planning continuation roots must already exist.",
        ) from exc
    if not artifact_root.is_dir() or not workspace_root.is_dir():
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_ROOT_INVALID",
            "artifact_admission",
            "Planning continuation roots must be directories.",
        )
    if (
        _same_path(artifact_root, workspace_root)
        or _is_within(artifact_root, workspace_root)
        or _is_within(workspace_root, artifact_root)
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_ROOTS_OVERLAP",
            "artifact_admission",
            "ArtifactStore and product workspace roots must not overlap.",
        )
    return artifact_root, workspace_root


def _latest_artifact_ref(
    store: ArtifactStore,
    *,
    feature_id: str,
    artifact_type: str,
) -> ArtifactRef | None:
    latest = [
        ref
        for ref in store.list_feature_artifacts(feature_id)
        if ref.artifact_type == artifact_type
    ]
    if not latest:
        return None
    if len(latest) != 1:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_LATEST_ALIAS_INVALID",
            "artifact_admission",
            "ArtifactStore has multiple latest aliases for one Artifact type.",
        )
    store.read(latest[0])
    return latest[0]


def _read_exact_revision(
    store: ArtifactStore,
    ref: ArtifactRef,
) -> dict[str, Any]:
    try:
        revisions = store.list_feature_artifact_revisions(
            ref.feature_id,
            ref.artifact_type,
        )
        if ref not in revisions:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_EXACT_REVISION_REQUIRED",
                "artifact_admission",
                "Planning continuation requires an immutable Artifact revision ref.",
            )
        latest_ref = _latest_artifact_ref(
            store,
            feature_id=ref.feature_id,
            artifact_type=ref.artifact_type,
        )
        if latest_ref is None or latest_ref.artifact_hash != ref.artifact_hash:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_ARTIFACT_STALE",
                "artifact_admission",
                "Planning continuation requires the current latest Artifact revision.",
            )
        envelope = store.read_for_stage(
            ref,
            consumer_stage=PLANNING_CONSUMER_STAGE,
        )
        exact_freshness = store.check_exact_revision_freshness(ref)
    except PlanningContinuationError:
        raise
    except (
        ArtifactStoreError,
        StaleArtifactError,
        OSError,
        ValueError,
    ) as exc:
        code = (
            "PLANNING_CONTINUATION_ARTIFACT_STALE"
            if "stale" in type(exc).__name__.lower()
            else "PLANNING_CONTINUATION_ARTIFACT_INVALID"
        )
        raise PlanningContinuationError(
            code,
            "artifact_admission",
            "Planning continuation Artifact admission failed.",
        ) from exc
    if not exact_freshness.is_fresh:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_ARTIFACT_STALE",
            "artifact_admission",
            "Planning continuation exact revision is stale.",
        )
    return envelope


def _validate_upstream(
    evidence_envelope: Mapping[str, Any],
    feature_spec_ref: ArtifactRef,
) -> None:
    upstreams = evidence_envelope.get("inputs", {}).get("upstream_artifacts")
    if not isinstance(upstreams, list) or len(upstreams) != 1:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_UPSTREAM_INVALID",
            "artifact_admission",
            "Fresh EvidencePack must have exactly one FeatureSpec upstream.",
        )
    upstream = upstreams[0]
    if not isinstance(upstream, Mapping) or (
        upstream.get("artifact_type") != "feature_spec"
        or upstream.get("path") != feature_spec_ref.path
        or upstream.get("artifact_hash") != feature_spec_ref.artifact_hash
        or upstream.get("require_latest") is not True
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_UPSTREAM_MISMATCH",
            "artifact_admission",
            "Fresh EvidencePack is not bound to the selected FeatureSpec revision.",
        )


def _source_hash(item: Mapping[str, Any]) -> str:
    source_hash = item.get("source_hash")
    file_hash = item.get("file_hash")
    if source_hash not in (None, "") and not _is_sha256(source_hash):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_SOURCE_HASH_INVALID",
            "source_validation",
            "Target-source evidence has an invalid source_hash.",
        )
    if file_hash not in (None, "") and not _is_sha256(file_hash):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_SOURCE_HASH_INVALID",
            "source_validation",
            "Target-source evidence has an invalid file_hash.",
        )
    if source_hash and file_hash and source_hash != file_hash:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_SOURCE_HASH_CONFLICT",
            "source_validation",
            "Target-source evidence hash aliases disagree.",
        )
    selected = source_hash or file_hash
    if not isinstance(selected, str):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_SOURCE_HASH_MISSING",
            "source_validation",
            "Target-source evidence has no physical source hash.",
        )
    return selected


def _validate_source_items(
    evidence_pack: Mapping[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    raw_items = evidence_pack.get("items")
    if not isinstance(raw_items, list):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_EVIDENCE_ITEMS_INVALID",
            "source_validation",
            "Fresh EvidencePack items must be an array.",
        )
    target_items = [
        item
        for item in raw_items
        if isinstance(item, Mapping) and item.get("source_type") == "target_source"
    ]
    if not target_items:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_TARGET_SOURCE_MISSING",
            "source_validation",
            "Planning continuation found no target-source evidence.",
        )

    files: dict[str, dict[str, Any]] = {}
    for item in target_items:
        source_path = item.get("source_path")
        source_ref = item.get("source_ref")
        if type(source_path) is not str or not source_path.strip():
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_PATH_INVALID",
                "source_validation",
                "Target-source evidence source_path is invalid.",
            )
        pure_path = PurePosixPath(source_path)
        if pure_path.is_absolute() or Path(source_path).is_absolute() or ".." in pure_path.parts:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_PATH_INVALID",
                "source_validation",
                "Target-source evidence source_path escapes the workspace.",
            )
        expected_path = (workspace_root / Path(*pure_path.parts)).resolve()
        if not _is_within(expected_path, workspace_root) or not expected_path.is_file():
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_MISSING",
                "source_validation",
                "A target-source evidence file is unavailable.",
            )
        if (
            type(source_ref) is not str
            or not Path(source_ref).is_absolute()
            or not _same_path(Path(source_ref), expected_path)
        ):
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_REF_MISMATCH",
                "source_validation",
                "Target-source evidence source_ref does not match source_path.",
            )
        try:
            source_bytes = expected_path.read_bytes()
            line_count = len(source_bytes.decode("utf-8").splitlines())
        except (OSError, UnicodeDecodeError) as exc:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_READ_FAILED",
                "source_validation",
                "A target-source evidence file could not be read as UTF-8.",
            ) from exc
        expected_hash = _source_hash(item)
        observed_hash = hashlib.sha256(source_bytes).hexdigest()
        if observed_hash != expected_hash:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_HASH_MISMATCH",
                "source_validation",
                "A target-source evidence file has changed.",
            )
        span = item.get("span")
        if not isinstance(span, Mapping):
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_SPAN_INVALID",
                "source_validation",
                "Target-source evidence span is invalid.",
            )
        start_line = span.get("start_line")
        end_line = span.get("end_line")
        if (
            type(start_line) is not int
            or type(end_line) is not int
            or start_line < 1
            or end_line < start_line
            or end_line > line_count
        ):
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_SPAN_INVALID",
                "source_validation",
                "Target-source evidence span is outside the current source file.",
            )
        existing = files.setdefault(
            pure_path.as_posix(),
            {
                "source_path": pure_path.as_posix(),
                "sha256": observed_hash,
                "item_count": 0,
            },
        )
        if existing["sha256"] != observed_hash:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_SOURCE_HASH_CONFLICT",
                "source_validation",
                "One source path has conflicting evidence hashes.",
            )
        existing["item_count"] += 1

    file_rows = [files[path] for path in sorted(files)]
    return {
        "status": "passed",
        "checked_item_count": len(target_items),
        "checked_file_count": len(file_rows),
        "files": file_rows,
        "snapshot_sha256": _canonical_sha256(file_rows),
    }


def _csharp_source_snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    try:
        return tuple(
            (
                path.relative_to(root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in sorted(root.rglob("*.cs"), key=lambda item: item.as_posix())
            if path.is_file()
        )
    except OSError as exc:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_SOURCE_SNAPSHOT_FAILED",
            "source_validation",
            "Current C# source snapshot could not be read.",
        ) from exc


def _validate_fresh_origin(evidence_pack: Mapping[str, Any]) -> None:
    budget_summary = evidence_pack.get("budget_summary")
    execution = (
        budget_summary.get("fresh_coverage_model_execution")
        if isinstance(budget_summary, Mapping)
        else None
    )
    if not isinstance(execution, Mapping):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_FRESH_ORIGIN_MISSING",
            "artifact_admission",
            "EvidencePack has no Fresh Coverage model execution receipt.",
        )
    roles = execution.get("roles")
    attempts = execution.get("attempts")
    call_count = execution.get("call_count")
    budget = execution.get("budget")
    admission = execution.get("admission")
    if (
        not isinstance(roles, list)
        or not roles
        or not all(type(role) is str and role for role in roles)
        or "requirement_projection" not in roles
        or "requirement_findings" not in roles
        or type(call_count) is not int
        or call_count != len(roles)
        or not isinstance(attempts, list)
        or len(attempts) != call_count
        or not isinstance(budget, Mapping)
        or budget.get("automatic_provider_fallback") is not False
        or budget.get("automatic_retry") is not False
        or not isinstance(admission, Mapping)
        or admission.get("provider") != "ollama"
        or admission.get("execution_locality") != "local"
        or admission.get("external_disclosure_occurred") is not False
        or budget_summary.get("all_queries_executed") is not True
        or not {
            "rg_live_query_set",
            "rg_live_read",
        }.issubset(set(evidence_pack.get("retrieval_methods_used") or []))
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_FRESH_ORIGIN_INVALID",
            "artifact_admission",
            "EvidencePack Fresh Coverage execution receipt is invalid.",
        )
    for index, (role, attempt) in enumerate(zip(roles, attempts, strict=True), start=1):
        if (
            not isinstance(attempt, Mapping)
            or attempt.get("attempt_index") != index
            or attempt.get("role") != role
            or attempt.get("status") not in {"accepted", "rejected"}
            or not _is_sha256(attempt.get("payload_canonical_sha256"))
            or not _is_sha256(attempt.get("schema_canonical_sha256"))
            or not _is_sha256(attempt.get("output_canonical_sha256"))
        ):
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_FRESH_ORIGIN_INVALID",
                "artifact_admission",
                "EvidencePack Fresh Coverage attempt receipt is invalid.",
            )

    valid_role_sequences = {
        (
            "requirement_projection",
            "requirement_findings",
        ),
        (
            "requirement_projection",
            "requirement_projection_correction",
            "requirement_findings",
        ),
        (
            "requirement_projection",
            "requirement_findings",
            "requirement_findings_correction",
        ),
        tuple(FRESH_COVERAGE_MODEL_CALL_BUDGET),
    }
    role_sequence = tuple(roles)
    role_call_counts = execution.get("role_call_counts")
    expected_role_call_counts = {
        role: role_sequence.count(role) for role in FRESH_COVERAGE_MODEL_CALL_BUDGET
    }
    if (
        role_sequence not in valid_role_sequences
        or role_call_counts != expected_role_call_counts
        or execution.get("correction_count")
        != sum(role.endswith("_correction") for role in role_sequence)
        or budget.get("maximum_total_calls") != sum(FRESH_COVERAGE_MODEL_CALL_BUDGET.values())
        or budget.get("maximum_calls_by_role") != FRESH_COVERAGE_MODEL_CALL_BUDGET
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_FRESH_ORIGIN_INVALID",
            "artifact_admission",
            "EvidencePack Fresh Coverage role sequence is invalid.",
        )

    attempt_by_role = {str(attempt["role"]): attempt for attempt in attempts}
    for base_role, correction_role in (
        ("requirement_projection", "requirement_projection_correction"),
        ("requirement_findings", "requirement_findings_correction"),
    ):
        base_attempt = attempt_by_role[base_role]
        correction_attempt = attempt_by_role.get(correction_role)
        if correction_attempt is None:
            valid_stage = (
                base_attempt.get("status") == "accepted" and base_attempt.get("error_code") is None
            )
        else:
            valid_stage = (
                base_attempt.get("status") == "rejected"
                and type(base_attempt.get("error_code")) is str
                and bool(base_attempt["error_code"])
                and correction_attempt.get("status") == "accepted"
                and correction_attempt.get("error_code") is None
            )
        if not valid_stage:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_FRESH_ORIGIN_INVALID",
                "artifact_admission",
                "EvidencePack Fresh Coverage stage has no accepted final output.",
            )


def preflight_planning_continuation(
    request: PlanningContinuationInputV1,
    *,
    artifact_store: ArtifactStore | None = None,
) -> _AdmittedPlanningInputs:
    artifact_root, workspace_root = _resolve_roots(request)
    if artifact_store is not None and not _same_path(
        artifact_store.root,
        artifact_root,
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_STORE_BINDING_MISMATCH",
            "artifact_admission",
            "Graph ArtifactStore does not match the continuation input root.",
        )
    store = artifact_store or ArtifactStore(artifact_root)
    feature_envelope = _read_exact_revision(store, request.feature_spec_ref)
    evidence_envelope = _read_exact_revision(store, request.evidence_pack_ref)
    if feature_envelope.get("status") != "success" or evidence_envelope.get("status") != "success":
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_ARTIFACT_STATUS_INVALID",
            "artifact_admission",
            "Planning continuation requires successful Fresh input Artifacts.",
        )
    _validate_upstream(evidence_envelope, request.feature_spec_ref)
    try:
        feature_spec = strict_feature_spec_payload(feature_envelope["data"])
        pack = EvidencePack.from_artifact_payload(evidence_envelope["data"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_PAYLOAD_INVALID",
            "artifact_admission",
            "Fresh input payload failed strict semantic round-trip.",
        ) from exc
    evidence_pack = pack.to_artifact_payload()
    _validate_fresh_origin(evidence_pack)
    if (
        feature_spec["feature_id"] != request.feature_spec_ref.feature_id
        or evidence_pack["query"] != feature_spec["user_request"]
        or evidence_pack["readiness"] != "sufficient"
        or evidence_pack["can_generate_patch"] is not True
        or evidence_pack["authoritative_for_patch"] is not True
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_SEMANTIC_ADMISSION_FAILED",
            "artifact_admission",
            "Fresh inputs are not eligible for formal implementation planning.",
        )
    requirement_coverage = evidence_pack.get("requirement_coverage")
    expected_feature_identity = {
        "feature_id": feature_spec["feature_id"],
        "feature_spec_sha256": feature_spec_payload_sha256(feature_spec),
    }
    if (
        not isinstance(requirement_coverage, Mapping)
        or requirement_coverage.get("feature_spec_identity") != expected_feature_identity
    ):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_COVERAGE_IDENTITY_MISMATCH",
            "artifact_admission",
            "Requirement coverage is not bound to the selected FeatureSpec payload.",
        )
    source_validation = _validate_source_items(evidence_pack, workspace_root)
    return _AdmittedPlanningInputs(
        artifact_store=store,
        feature_spec=feature_spec,
        evidence_pack=evidence_pack,
        source_validation=source_validation,
        source_tree_snapshot=_csharp_source_snapshot(workspace_root),
    )


def _read_selected_exact_revision(
    store: ArtifactStore,
    ref: ArtifactRef,
    *,
    consumer_stage: str | None,
) -> dict[str, Any]:
    """Read a selected immutable revision without promoting latest to authority."""

    try:
        revisions = store.list_feature_artifact_revisions(
            ref.feature_id,
            ref.artifact_type,
        )
        if ref not in revisions:
            raise PatchContinuationError(
                "PATCH_CONTINUATION_EXACT_REVISION_REQUIRED",
                "artifact_admission",
                "Patch continuation requires immutable Artifact revision refs.",
            )
        if consumer_stage is not None:
            store.registry.validate_consumer(ref.artifact_type, consumer_stage)
        envelope = dict(store.semantic_read_immutable(ref))
        freshness = store.check_exact_revision_freshness(ref)
    except PatchContinuationError:
        raise
    except (ArtifactRegistryError, ArtifactStoreError, OSError, ValueError) as exc:
        raise PatchContinuationError(
            "PATCH_CONTINUATION_ARTIFACT_INVALID",
            "artifact_admission",
            "Selected exact Artifact revision failed immutable admission.",
        ) from exc
    if not freshness.is_fresh:
        raise PatchContinuationError(
            "PATCH_CONTINUATION_ANCESTRY_STALE",
            "artifact_admission",
            "Selected exact Artifact ancestry is missing or content-invalid.",
        )
    return envelope


def _latest_observation(
    store: ArtifactStore,
    selected_ref: ArtifactRef,
) -> dict[str, Any]:
    """Observe the latest alias without granting it continuation authority."""

    try:
        latest_ref = _latest_artifact_ref(
            store,
            feature_id=selected_ref.feature_id,
            artifact_type=selected_ref.artifact_type,
        )
    except (ArtifactStoreError, PatchContinuationError, PlanningContinuationError) as exc:
        return {
            "status": "unavailable",
            "selected_is_latest": None,
            "failure_class": type(exc).__name__,
        }
    if latest_ref is None:
        return {
            "status": "absent",
            "selected_is_latest": False,
            "artifact_hash": None,
            "path": None,
        }
    return {
        "status": "observed",
        "selected_is_latest": latest_ref.artifact_hash == selected_ref.artifact_hash,
        "artifact_hash": latest_ref.artifact_hash,
        "path": latest_ref.path,
    }


def _validate_exact_upstream_set(
    envelope: Mapping[str, Any],
    expected_refs: tuple[ArtifactRef, ...],
) -> None:
    upstreams = envelope.get("inputs", {}).get("upstream_artifacts")
    if not isinstance(upstreams, list) or len(upstreams) != len(expected_refs):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_UPSTREAM_INVALID",
            "artifact_admission",
            "Selected Artifact has an unexpected direct upstream set.",
        )
    observed: dict[str, Mapping[str, Any]] = {}
    for upstream in upstreams:
        if not isinstance(upstream, Mapping):
            raise PatchContinuationError(
                "PATCH_CONTINUATION_UPSTREAM_INVALID",
                "artifact_admission",
                "Selected Artifact direct upstream identity is invalid.",
            )
        artifact_type = upstream.get("artifact_type")
        if type(artifact_type) is not str or artifact_type in observed:
            raise PatchContinuationError(
                "PATCH_CONTINUATION_UPSTREAM_INVALID",
                "artifact_admission",
                "Selected Artifact direct upstream types are invalid.",
            )
        observed[artifact_type] = upstream
    for expected in expected_refs:
        upstream = observed.get(expected.artifact_type)
        if upstream is None or (
            upstream.get("path") != expected.path
            or upstream.get("artifact_hash") != expected.artifact_hash
        ):
            raise PatchContinuationError(
                "PATCH_CONTINUATION_UPSTREAM_MISMATCH",
                "artifact_admission",
                "Selected Artifact ancestry does not match the explicit refs.",
            )


def _validate_selected_plan(
    implementation_plan: Mapping[str, Any],
    evidence_pack: dict[str, Any],
    *,
    feature_id: str,
) -> None:
    if (
        implementation_plan.get("feature_id") != feature_id
        or implementation_plan.get("blocking") is not False
    ):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_PLAN_NOT_ADMITTED",
            "artifact_admission",
            "Selected ImplementationPlan is blocking or has the wrong feature_id.",
        )
    registry = implementation_plan.get("binding_registry")
    proposed_changes = implementation_plan.get("proposed_changes")
    if not isinstance(registry, dict) or not isinstance(proposed_changes, list):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_PLAN_PAYLOAD_INVALID",
            "artifact_admission",
            "Selected ImplementationPlan has no valid binding/change representation.",
        )
    resolver = BindingResolver.from_implementation_plan(
        dict(implementation_plan),
        evidence_pack=evidence_pack,
    )
    binding_validation = resolver.validate_registry_against_evidence()
    if not binding_validation.allowed:
        raise PatchContinuationError(
            "PATCH_CONTINUATION_BINDING_INVALID",
            "binding_admission",
            "Selected ImplementationPlan bindings drifted from EvidencePack.",
        )
    edit_binding_ids = tuple(resolver.edit_bindings)
    if not edit_binding_ids or len(edit_binding_ids) != len(set(edit_binding_ids)):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_BINDING_INVALID",
            "binding_admission",
            "Selected ImplementationPlan edit bindings are empty or duplicated.",
        )
    selected_change_ids: list[str] = []
    selected_binding_ids: list[str] = []
    for change in proposed_changes:
        if not isinstance(change, Mapping):
            raise PatchContinuationError(
                "PATCH_CONTINUATION_PLAN_CHANGE_INVALID",
                "binding_admission",
                "Selected ImplementationPlan change is not an object.",
            )
        change_id = change.get("change_id")
        binding_id = change.get("edit_binding_id")
        if type(change_id) is not str or not change_id or type(binding_id) is not str:
            raise PatchContinuationError(
                "PATCH_CONTINUATION_PLAN_CHANGE_INVALID",
                "binding_admission",
                "Selected ImplementationPlan change identity is incomplete.",
            )
        selected_change_ids.append(change_id)
        selected_binding_ids.append(binding_id)
    if (
        len(selected_change_ids) != len(set(selected_change_ids))
        or len(selected_binding_ids) != len(set(selected_binding_ids))
        or set(selected_binding_ids) != set(edit_binding_ids)
    ):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_PLAN_SELECTION_INVALID",
            "binding_admission",
            "The exact Plan selection must cover every and only its edit bindings once.",
        )


def preflight_patch_continuation(
    request: PatchContinuationInputV1,
    *,
    artifact_store: ArtifactStore | None = None,
) -> _AdmittedPatchInputs:
    """Admit exact selected refs, ancestry, bindings, and current source bytes."""

    try:
        artifact_root, workspace_root = _resolve_roots(request)  # type: ignore[arg-type]
    except PlanningContinuationError as exc:
        raise PatchContinuationError(
            exc.code.replace("PLANNING_", "PATCH_", 1),
            exc.stage,
            exc.reason,
        ) from exc
    if artifact_store is not None and not _same_path(
        artifact_store.root,
        artifact_root,
    ):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_STORE_BINDING_MISMATCH",
            "artifact_admission",
            "Graph ArtifactStore does not match the continuation input root.",
        )
    store = artifact_store or ArtifactStore(artifact_root)
    feature_envelope = _read_selected_exact_revision(
        store,
        request.feature_spec_ref,
        consumer_stage=None,
    )
    evidence_envelope = _read_selected_exact_revision(
        store,
        request.evidence_pack_ref,
        consumer_stage=PATCH_CONSUMER_STAGE,
    )
    plan_envelope = _read_selected_exact_revision(
        store,
        request.implementation_plan_ref,
        consumer_stage=PATCH_CONSUMER_STAGE,
    )
    if any(
        envelope.get("status") != "success"
        for envelope in (feature_envelope, evidence_envelope, plan_envelope)
    ):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_ARTIFACT_STATUS_INVALID",
            "artifact_admission",
            "Patch continuation requires successful selected Artifacts.",
        )
    _validate_exact_upstream_set(evidence_envelope, (request.feature_spec_ref,))
    _validate_exact_upstream_set(
        plan_envelope,
        (request.feature_spec_ref, request.evidence_pack_ref),
    )
    try:
        feature_spec = strict_feature_spec_payload(feature_envelope["data"])
        evidence_pack = EvidencePack.from_artifact_payload(
            evidence_envelope["data"]
        ).to_artifact_payload()
        implementation_plan = dict(plan_envelope["data"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PatchContinuationError(
            "PATCH_CONTINUATION_PAYLOAD_INVALID",
            "artifact_admission",
            "Selected Artifact payload failed strict semantic admission.",
        ) from exc
    if (
        feature_spec["feature_id"] != request.feature_spec_ref.feature_id
        or evidence_pack["query"] != feature_spec["user_request"]
    ):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_SEMANTIC_IDENTITY_MISMATCH",
            "artifact_admission",
            "Selected FeatureSpec and EvidencePack semantic identities differ.",
        )
    _validate_selected_plan(
        implementation_plan,
        evidence_pack,
        feature_id=request.feature_spec_ref.feature_id,
    )
    try:
        source_validation = _validate_source_items(evidence_pack, workspace_root)
    except PlanningContinuationError as exc:
        raise PatchContinuationError(
            exc.code.replace("PLANNING_", "PATCH_", 1),
            exc.stage,
            exc.reason,
        ) from exc
    selected_refs = (
        request.feature_spec_ref,
        request.evidence_pack_ref,
        request.implementation_plan_ref,
    )
    return _AdmittedPatchInputs(
        artifact_store=store,
        feature_spec=feature_spec,
        evidence_pack=evidence_pack,
        implementation_plan=implementation_plan,
        source_validation=source_validation,
        source_tree_snapshot=_csharp_source_snapshot(workspace_root),
        latest_observations={
            ref.artifact_type: _latest_observation(store, ref)
            for ref in selected_refs
        },
    )


def _source_tree_snapshot_sha256(
    snapshot: tuple[tuple[str, str], ...],
) -> str:
    return _canonical_sha256(
        [{"path": path, "sha256": sha256} for path, sha256 in snapshot]
    )


class PatchContinuationAttemptJournal:
    """Atomic non-Artifact receipt for one external Patch attempt and its gates."""

    def __init__(
        self,
        *,
        artifact_root: Path,
        run_id: str,
        request_id: str,
        request: PatchContinuationInputV1,
        admitted: _AdmittedPatchInputs,
    ) -> None:
        self.path = (
            artifact_root
            / "continuation_receipts"
            / run_id
            / "patch_attempt.json"
        )
        self._document: dict[str, Any] = {
            "receipt_version": PATCH_CONTINUATION_RECEIPT_VERSION,
            "status": "admitted",
            "run_id": run_id,
            "request_id": request_id,
            "feature_id": request.feature_spec_ref.feature_id,
            "continuation_selection": "explicit_exact_implementation_plan_ref",
            "semantic_authority_claimed": False,
            "selected_artifacts": {
                "feature_spec": _artifact_ref_dict(request.feature_spec_ref),
                "evidence_pack": _artifact_ref_dict(request.evidence_pack_ref),
                "implementation_plan": _artifact_ref_dict(
                    request.implementation_plan_ref
                ),
            },
            "latest_observations": admitted.latest_observations,
            "generated_against_snapshot_sha256": _source_tree_snapshot_sha256(
                admitted.source_tree_snapshot
            ),
            "current_snapshot_sha256": _source_tree_snapshot_sha256(
                admitted.source_tree_snapshot
            ),
            "model_call_count": 0,
            "proposal_admitted": False,
            "artifacts": {},
            "events": [],
        }
        self._write()

    def record(self, event: Mapping[str, Any]) -> None:
        phase = event.get("phase")
        if type(phase) is not str or not phase:
            raise PatchContinuationError(
                "PATCH_CONTINUATION_RECEIPT_EVENT_INVALID",
                "patch_attempt_receipt",
                "Patch attempt receipt event requires a non-empty phase.",
            )
        normalized = json.loads(
            json.dumps(
                dict(event),
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        )
        normalized["event_index"] = len(self._document["events"]) + 1
        self._document["events"].append(normalized)
        for key, value in normalized.items():
            if key not in {"phase", "event_index"}:
                self._document[key] = value
        self._document["status"] = phase
        self._write()

    def projection(self) -> dict[str, Any]:
        payload = self.path.read_bytes()
        return {
            "receipt_version": PATCH_CONTINUATION_RECEIPT_VERSION,
            "path": str(self.path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "status": self._document["status"],
            "event_count": len(self._document["events"]),
            "model_call_count": self._document.get("model_call_count", 0),
            "proposal_admitted": self._document.get("proposal_admitted", False),
            "generated_against_snapshot_sha256": self._document.get(
                "generated_against_snapshot_sha256"
            ),
            "current_snapshot_sha256": self._document.get(
                "current_snapshot_sha256"
            ),
        }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        payload = (
            json.dumps(
                self._document,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise PatchContinuationError(
                "PATCH_CONTINUATION_RECEIPT_WRITE_FAILED",
                "patch_attempt_receipt",
                "Patch attempt receipt could not be persisted atomically.",
            ) from exc


def blocked_planning_continuation_result(
    *,
    code: str,
    stage: str,
    duration_seconds: float,
    reason: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    feature_id: str | None = None,
    feature_spec_ref: ArtifactRef | None = None,
    evidence_pack_ref: ArtifactRef | None = None,
    implementation_plan_ref: ArtifactRef | None = None,
    plan_blocking: bool | None = None,
    artifact_write: ArtifactWriteResult | Mapping[str, Any] | None = None,
    planning_execution_count: int = 0,
    source_validation: Mapping[str, Any] | None = None,
    source_modified_during_run: bool | None = None,
    status: Literal["blocked", "partial"] = "blocked",
) -> PlanningContinuationResultV1:
    return PlanningContinuationResultV1(
        status=status,
        terminal_stage=stage,
        first_failure={"code": code, "stage": stage},
        run_id=run_id or f"planning_continuation_{uuid4().hex}",
        request_id=request_id or f"planning_request_{uuid4().hex}",
        feature_id=feature_id,
        feature_spec_artifact=(
            None if feature_spec_ref is None else _artifact_ref_dict(feature_spec_ref)
        ),
        evidence_pack_artifact=(
            None if evidence_pack_ref is None else _artifact_ref_dict(evidence_pack_ref)
        ),
        implementation_plan_artifact=(
            None if implementation_plan_ref is None else _artifact_ref_dict(implementation_plan_ref)
        ),
        plan_blocking=plan_blocking,
        artifact_write=_artifact_write_projection(artifact_write),
        source_validation=dict(
            source_validation
            or {
                "status": "not_completed",
                "checked_item_count": 0,
                "checked_file_count": 0,
            }
        ),
        planning_execution_count=planning_execution_count,
        source_modified_during_run=source_modified_during_run,
        duration_seconds=duration_seconds,
        reason=reason or code,
    )


def _plan_ref_from_state(
    state: Mapping[str, Any],
    feature_id: str,
) -> ArtifactRef:
    artifacts = state.get("artifacts")
    artifact_hashes = state.get("artifact_hashes")
    if not isinstance(artifacts, Mapping) or not isinstance(artifact_hashes, Mapping):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_PLAN_REF_MISSING",
            "implementation_plan",
            "Planning graph returned no Artifact reference maps.",
        )
    path = artifacts.get("implementation_plan")
    artifact_hash = artifact_hashes.get("implementation_plan")
    if type(path) is not str or not path or not _is_sha256(artifact_hash):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_PLAN_REF_MISSING",
            "implementation_plan",
            "Planning graph did not persist an exact ImplementationPlan ref.",
        )
    return ArtifactRef(
        feature_id=feature_id,
        artifact_type="implementation_plan",
        path=path,
        artifact_hash=artifact_hash,
    )


def _plan_ref_from_write_result(
    store: ArtifactStore,
    write_result: ArtifactWriteResult,
) -> ArtifactRef | None:
    if write_result.artifact_ref is not None:
        return write_result.artifact_ref
    if (
        write_result.revision_state != "valid"
        or not _is_sha256(write_result.artifact_hash)
        or type(write_result.revision_path) is not str
        or not write_result.revision_path
    ):
        return None
    ref = ArtifactRef(
        feature_id=write_result.feature_id,
        artifact_type=write_result.artifact_type,
        path=write_result.revision_path,
        artifact_hash=write_result.artifact_hash,
    )
    try:
        store.read(ref)
    except ArtifactStoreError:
        return None
    return ref


def _planning_trace_count(state: Mapping[str, Any]) -> int:
    trace_events = state.get("trace_events")
    if not isinstance(trace_events, list):
        return 0
    return sum(
        1
        for event in trace_events
        if isinstance(event, Mapping)
        and event.get("node_name") == "create_implementation_plan"
        and event.get("event_type") == "node_started"
    )


def _write_result_from_state(state: Mapping[str, Any]) -> ArtifactWriteResult:
    runtime_summary = state.get("runtime_summary")
    raw_result = (
        runtime_summary.get("planning_artifact_write_result")
        if isinstance(runtime_summary, Mapping)
        else None
    )
    if not isinstance(raw_result, Mapping):
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_WRITE_RESULT_MISSING",
            "implementation_plan",
            "Planning graph returned no exact Artifact write result.",
        )
    try:
        return ArtifactWriteResult.from_dict(raw_result)
    except ArtifactStoreError as exc:
        raise PlanningContinuationError(
            "PLANNING_CONTINUATION_WRITE_RESULT_INVALID",
            "implementation_plan",
            "Planning graph Artifact write result is invalid.",
        ) from exc


def _plan_blocking_from_ref(
    store: ArtifactStore,
    ref: ArtifactRef | None,
) -> bool | None:
    if ref is None:
        return None
    try:
        envelope = store.read(ref)
    except ArtifactStoreError:
        return None
    data = envelope.get("data")
    if not isinstance(data, Mapping) or type(data.get("blocking")) is not bool:
        return None
    return data["blocking"]


def _first_plan_failure(state: Mapping[str, Any]) -> dict[str, str] | None:
    blockers = state.get("blockers")
    if not isinstance(blockers, list):
        return {
            "code": "PLANNING_CONTINUATION_BLOCKERS_INVALID",
            "stage": "implementation_plan",
        }
    for blocker in blockers:
        if not isinstance(blocker, Mapping):
            continue
        code = blocker.get("code")
        if isinstance(code, str) and code:
            return {"code": code, "stage": "implementation_plan"}
    if blockers:
        return {
            "code": "IMPLEMENTATION_PLAN_BLOCKED",
            "stage": "implementation_plan",
        }
    return None


def _continuation_state(
    *,
    run_id: str,
    request_id: str,
    request: PlanningContinuationInputV1,
    admitted: _AdmittedPlanningInputs,
):
    from src.mod_agent.workflow.state import create_initial_state

    feature_spec = admitted.feature_spec
    evidence_pack = admitted.evidence_pack
    state = create_initial_state(
        run_id=run_id,
        request_id=request_id,
        user_request=feature_spec["user_request"],
        target_mod=feature_spec["target_mod"],
    )
    state["feature_id"] = request.feature_spec_ref.feature_id
    state["risk_level"] = feature_spec["risk_level"]
    state["current_stage"] = "evidence_retrieval"
    state["next_stage"] = "implementation_plan"
    state["artifacts"] = {
        "feature_spec": request.feature_spec_ref.path,
        "evidence_pack": request.evidence_pack_ref.path,
    }
    state["artifact_hashes"] = {
        "feature_spec": request.feature_spec_ref.artifact_hash,
        "evidence_pack": request.evidence_pack_ref.artifact_hash,
    }
    state["evidence_summary"] = {
        "readiness": evidence_pack["readiness"],
        "can_generate_patch": evidence_pack["can_generate_patch"],
        "num_items": len(evidence_pack["items"]),
        "gaps": list(evidence_pack["gaps"]),
        "retrieval_methods_used": list(evidence_pack["retrieval_methods_used"]),
        "missing_evidence": list(evidence_pack["missing_evidence"]),
        "disabled_modes": dict(evidence_pack["disabled_modes"]),
        "timing": dict(evidence_pack["timing"]),
    }
    return state


def _source_tree_changed_since(
    request: PlanningContinuationInputV1,
    before: tuple[tuple[str, str], ...],
) -> bool | None:
    try:
        _, workspace_root = _resolve_roots(request)
        return _csharp_source_snapshot(workspace_root) != before
    except PlanningContinuationError:
        return None


def run_fresh_planning_continuation(
    request: PlanningContinuationInputV1,
) -> PlanningContinuationResultV1:
    """Run exact Fresh inputs through Planning once and stop before Patch."""

    started = time.perf_counter()
    run_id = f"planning_continuation_{uuid4().hex}"
    request_id = f"planning_request_{uuid4().hex}"
    feature_id = request.feature_spec_ref.feature_id
    try:
        admitted = preflight_planning_continuation(request)
    except PlanningContinuationError as exc:
        return blocked_planning_continuation_result(
            code=exc.code,
            stage=exc.stage,
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
        )

    from src.mod_agent.workflow.graph import build_graph

    state = _continuation_state(
        run_id=run_id,
        request_id=request_id,
        request=request,
        admitted=admitted,
    )
    try:
        graph = build_graph(
            admitted.artifact_store,
            planning_continuation_mode=request,
            use_default_proposal_git_binding=False,
        )
    except (PlanningContinuationError, RuntimeError, ValueError) as exc:
        code = getattr(exc, "code", "PLANNING_CONTINUATION_GRAPH_INVALID")
        return blocked_planning_continuation_result(
            code=code if isinstance(code, str) and code else "PLANNING_CONTINUATION_GRAPH_INVALID",
            stage=getattr(exc, "stage", "planning_admission"),
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            source_validation={
                "status": "passed_before_planning",
                "before": admitted.source_validation,
            },
        )

    try:
        graph_result = graph.invoke(state)
    except (ArtifactStoreError, PlanningContinuationError, RuntimeError, ValueError) as exc:
        node_started = getattr(exc, "_mod_agent_graph_node", None) == "create_implementation_plan"
        write_result = (
            exc.write_result if isinstance(exc, PlanningContinuationArtifactWriteError) else None
        )
        plan_ref = (
            _plan_ref_from_write_result(admitted.artifact_store, write_result)
            if write_result is not None
            else None
        )
        if write_result is not None:
            code = (
                "PLANNING_CONTINUATION_PLAN_STORE_PARTIAL"
                if write_result.outcome == "partial"
                else "PLANNING_CONTINUATION_PLAN_STORE_BLOCKED"
            )
            stage = "implementation_plan_store"
        else:
            code = getattr(
                exc,
                "code",
                "PLANNING_CONTINUATION_EXECUTION_FAILED",
            )
            if not isinstance(code, str) or not code:
                code = "PLANNING_CONTINUATION_EXECUTION_FAILED"
            stage = getattr(exc, "stage", "implementation_plan")
        is_partial = write_result is not None and (
            write_result.outcome == "partial" or write_result.commit_started or plan_ref is not None
        )
        return blocked_planning_continuation_result(
            code=code,
            stage=stage,
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=plan_ref,
            plan_blocking=_plan_blocking_from_ref(
                admitted.artifact_store,
                plan_ref,
            ),
            artifact_write=write_result,
            planning_execution_count=1 if node_started else 0,
            source_validation={
                "status": (
                    "failed_during_planning"
                    if _source_tree_changed_since(
                        request,
                        admitted.source_tree_snapshot,
                    )
                    else "passed_before_planning"
                ),
                "before": admitted.source_validation,
            },
            source_modified_during_run=_source_tree_changed_since(
                request,
                admitted.source_tree_snapshot,
            ),
            status="partial" if is_partial else "blocked",
        )

    planning_execution_count = _planning_trace_count(graph_result)
    plan_ref: ArtifactRef | None = None
    write_result: ArtifactWriteResult | None = None
    try:
        write_result = _write_result_from_state(graph_result)
        plan_ref = _plan_ref_from_state(graph_result, feature_id)
        if write_result.artifact_ref != plan_ref:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_PLAN_REF_MISMATCH",
                "implementation_plan",
                "Planning state and Artifact write result refs disagree.",
            )
        if planning_execution_count != 1:
            raise PlanningContinuationError(
                "PLANNING_CONTINUATION_EXECUTION_COUNT_INVALID",
                "implementation_plan",
                "Planning graph did not record exactly one Planning start.",
            )
        plan_envelope = admitted.artifact_store.read(plan_ref)
    except (ArtifactStoreError, PlanningContinuationError) as exc:
        code = getattr(
            exc,
            "code",
            "PLANNING_CONTINUATION_PLAN_READBACK_FAILED",
        )
        return blocked_planning_continuation_result(
            code=code
            if isinstance(code, str) and code
            else "PLANNING_CONTINUATION_PLAN_READBACK_FAILED",
            stage=getattr(exc, "stage", "implementation_plan"),
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=plan_ref,
            plan_blocking=_plan_blocking_from_ref(
                admitted.artifact_store,
                plan_ref,
            ),
            artifact_write=write_result,
            planning_execution_count=planning_execution_count,
            source_validation={
                "status": "passed_before_planning",
                "before": admitted.source_validation,
            },
            source_modified_during_run=_source_tree_changed_since(
                request,
                admitted.source_tree_snapshot,
            ),
            status="partial" if plan_ref is not None else "blocked",
        )

    plan_data = plan_envelope["data"]
    if not isinstance(plan_data, Mapping) or type(plan_data.get("blocking")) is not bool:
        return blocked_planning_continuation_result(
            code="PLANNING_CONTINUATION_PLAN_PAYLOAD_INVALID",
            stage="implementation_plan",
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=plan_ref,
            artifact_write=write_result,
            planning_execution_count=planning_execution_count,
            source_validation={
                "status": "passed_before_planning",
                "before": admitted.source_validation,
            },
        )

    try:
        after = preflight_planning_continuation(request)
    except PlanningContinuationError as exc:
        source_modified: bool | None = None
        try:
            _, workspace_root = _resolve_roots(request)
            source_modified = (
                _csharp_source_snapshot(workspace_root) != admitted.source_tree_snapshot
            )
        except PlanningContinuationError:
            pass
        return blocked_planning_continuation_result(
            code=exc.code,
            stage=exc.stage,
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=plan_ref,
            plan_blocking=bool(plan_data["blocking"]),
            artifact_write=write_result,
            planning_execution_count=planning_execution_count,
            source_validation={
                "status": "failed_after_planning",
                "before": admitted.source_validation,
            },
            source_modified_during_run=source_modified,
            status="partial",
        )

    source_modified = after.source_tree_snapshot != admitted.source_tree_snapshot
    if source_modified:
        return blocked_planning_continuation_result(
            code="PLANNING_CONTINUATION_SOURCE_CHANGED",
            stage="source_validation",
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=plan_ref,
            plan_blocking=bool(plan_data["blocking"]),
            artifact_write=write_result,
            planning_execution_count=planning_execution_count,
            source_validation={
                "status": "failed_after_planning",
                "before": admitted.source_validation,
                "after": after.source_validation,
            },
            source_modified_during_run=True,
            status="partial",
        )

    plan_blocking = plan_data["blocking"]
    first_failure = _first_plan_failure(graph_result)
    status: Literal["terminal", "blocked"] = "blocked" if plan_blocking else "terminal"
    return PlanningContinuationResultV1(
        status=status,
        terminal_stage="implementation_plan",
        first_failure=first_failure,
        run_id=run_id,
        request_id=request_id,
        feature_id=feature_id,
        feature_spec_artifact=_artifact_ref_dict(request.feature_spec_ref),
        evidence_pack_artifact=_artifact_ref_dict(request.evidence_pack_ref),
        implementation_plan_artifact=_artifact_ref_dict(plan_ref),
        plan_blocking=plan_blocking,
        artifact_write=_artifact_write_projection(write_result),
        source_validation={
            "status": "passed",
            "before": admitted.source_validation,
            "after_snapshot_sha256": after.source_validation["snapshot_sha256"],
            "source_tree_unchanged": True,
        },
        planning_execution_count=planning_execution_count,
        source_modified_during_run=False,
        duration_seconds=time.perf_counter() - started,
        reason=(None if first_failure is None else first_failure["code"]),
    )


def blocked_patch_continuation_result(
    *,
    code: str,
    stage: str,
    duration_seconds: float,
    reason: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    feature_id: str | None = None,
    feature_spec_ref: ArtifactRef | None = None,
    evidence_pack_ref: ArtifactRef | None = None,
    implementation_plan_ref: ArtifactRef | None = None,
    patch_proposal_ref: ArtifactRef | None = None,
    proposal_review_ref: ArtifactRef | None = None,
    dry_run_ref: ArtifactRef | None = None,
    source_validation: Mapping[str, Any] | None = None,
    execution_counts: Mapping[str, int] | None = None,
    attempt_receipt: Mapping[str, Any] | None = None,
    source_modified_during_run: bool | None = None,
    status: Literal["blocked", "partial"] = "blocked",
) -> PatchContinuationResultV1:
    counts = {
        "fresh_coverage": 0,
        "model": 0,
        "planning": 0,
        "patch": 0,
        "review": 0,
        "dry_run": 0,
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }
    counts.update(dict(execution_counts or {}))
    return PatchContinuationResultV1(
        status=status,
        terminal_stage=stage,
        first_failure={"code": code, "stage": stage},
        run_id=run_id or f"patch_continuation_{uuid4().hex}",
        request_id=request_id or f"patch_request_{uuid4().hex}",
        feature_id=feature_id,
        feature_spec_artifact=(
            None if feature_spec_ref is None else _artifact_ref_dict(feature_spec_ref)
        ),
        evidence_pack_artifact=(
            None if evidence_pack_ref is None else _artifact_ref_dict(evidence_pack_ref)
        ),
        implementation_plan_artifact=(
            None
            if implementation_plan_ref is None
            else _artifact_ref_dict(implementation_plan_ref)
        ),
        patch_proposal_artifact=(
            None if patch_proposal_ref is None else _artifact_ref_dict(patch_proposal_ref)
        ),
        proposal_review_artifact=(
            None if proposal_review_ref is None else _artifact_ref_dict(proposal_review_ref)
        ),
        dry_run_artifact=(
            None if dry_run_ref is None else _artifact_ref_dict(dry_run_ref)
        ),
        source_validation=dict(
            source_validation
            or {
                "status": "not_completed",
                "checked_item_count": 0,
                "checked_file_count": 0,
            }
        ),
        execution_counts=counts,
        attempt_receipt=(
            None if attempt_receipt is None else dict(attempt_receipt)
        ),
        source_modified_during_run=source_modified_during_run,
        duration_seconds=duration_seconds,
        reason=reason or code,
    )


def _patch_continuation_state(
    *,
    run_id: str,
    request_id: str,
    request: PatchContinuationInputV1,
    admitted: _AdmittedPatchInputs,
):
    from src.mod_agent.workflow.state import create_initial_state

    state = create_initial_state(
        run_id=run_id,
        request_id=request_id,
        user_request=admitted.feature_spec["user_request"],
        target_mod=admitted.feature_spec["target_mod"],
    )
    state["feature_id"] = request.feature_spec_ref.feature_id
    state["risk_level"] = admitted.feature_spec["risk_level"]
    state["current_stage"] = "implementation_plan"
    state["next_stage"] = "patch_proposal"
    state["artifacts"] = {
        "feature_spec": request.feature_spec_ref.path,
        "evidence_pack": request.evidence_pack_ref.path,
        "implementation_plan": request.implementation_plan_ref.path,
    }
    state["artifact_hashes"] = {
        "feature_spec": request.feature_spec_ref.artifact_hash,
        "evidence_pack": request.evidence_pack_ref.artifact_hash,
        "implementation_plan": request.implementation_plan_ref.artifact_hash,
    }
    return state


def _bind_patch_attempt_recorder(
    factory: PatchContinuationFactory,
    recorder: Callable[[Mapping[str, Any]], None],
) -> None:
    binder = getattr(factory, "bind_attempt_recorder", None)
    if binder is None:
        return
    if not callable(binder):
        raise PatchContinuationError(
            "PATCH_CONTINUATION_FACTORY_RECORDER_INVALID",
            "patch_attempt_receipt",
            "Patch factory recorder binder must be callable.",
        )
    binder(recorder)


def _ref_from_patch_state(
    state: Mapping[str, Any],
    artifact_type: str,
    *,
    feature_id: str,
) -> ArtifactRef | None:
    artifacts = state.get("artifacts")
    hashes = state.get("artifact_hashes")
    if not isinstance(artifacts, Mapping) or not isinstance(hashes, Mapping):
        return None
    path = artifacts.get(artifact_type)
    artifact_hash = hashes.get(artifact_type)
    if type(path) is not str or not path or not _is_sha256(artifact_hash):
        return None
    return ArtifactRef(
        feature_id=feature_id,
        artifact_type=artifact_type,
        path=path,
        artifact_hash=artifact_hash,
    )


def _node_execution_count(state: Mapping[str, Any], node_name: str) -> int:
    trace_events = state.get("trace_events")
    if not isinstance(trace_events, list):
        return 0
    return sum(
        1
        for event in trace_events
        if isinstance(event, Mapping)
        and event.get("node_name") == node_name
        and event.get("event_type") == "node_started"
    )


def _patch_execution_counts(
    state: Mapping[str, Any],
    *,
    model_call_count: int,
) -> dict[str, int]:
    return {
        "fresh_coverage": 0,
        "model": model_call_count,
        "planning": 0,
        "patch": _node_execution_count(state, "generate_patch_proposal"),
        "review": _node_execution_count(state, "review_proposal"),
        "dry_run": _node_execution_count(state, "dry_run_apply"),
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }


def _failed_patch_execution_counts(
    failed_node: str | None,
    *,
    model_call_count: int,
) -> dict[str, int]:
    ordered = (
        "generate_patch_proposal",
        "review_proposal",
        "dry_run_apply",
    )
    reached = ordered.index(failed_node) + 1 if failed_node in ordered else 0
    return {
        "fresh_coverage": 0,
        "model": model_call_count,
        "planning": 0,
        "patch": int(reached >= 1),
        "review": int(reached >= 2),
        "dry_run": int(reached >= 3),
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }


def _patch_first_failure(state: Mapping[str, Any]) -> dict[str, str] | None:
    blockers = state.get("blockers")
    if not isinstance(blockers, list):
        return {
            "code": "PATCH_CONTINUATION_BLOCKERS_INVALID",
            "stage": str(state.get("current_stage") or "workflow"),
        }
    for blocker in blockers:
        if not isinstance(blocker, Mapping):
            continue
        code = blocker.get("code")
        if type(code) is str and code:
            return {
                "code": code,
                "stage": str(blocker.get("stage") or state.get("current_stage") or "workflow"),
            }
    return None


def _proposal_source_snippet_char_limit(admitted: _AdmittedPatchInputs) -> int:
    evidence_by_id = {
        str(item["evidence_id"]): item
        for item in admitted.evidence_pack.get("items") or []
        if isinstance(item, Mapping) and item.get("evidence_id")
    }
    return max(
        1,
        sum(
            len(excerpt)
            for evidence_id in admitted.implementation_plan.get("evidence_refs") or []
            if isinstance(
                excerpt := evidence_by_id.get(str(evidence_id), {}).get("excerpt"),
                str,
            )
        ),
    )


def run_fresh_patch_continuation(
    request: PatchContinuationInputV1,
    *,
    patch_change_factory: PatchContinuationFactory,
    dry_run_factory: PatchContinuationDryRunFactory,
) -> PatchContinuationResultV1:
    """Run an exact Plan through Patch, Review, and no-write Dry-run once."""

    started = time.perf_counter()
    run_id = f"patch_continuation_{uuid4().hex}"
    request_id = f"patch_request_{uuid4().hex}"
    feature_id = request.feature_spec_ref.feature_id
    try:
        admitted = preflight_patch_continuation(request)
    except PatchContinuationError as exc:
        return blocked_patch_continuation_result(
            code=exc.code,
            stage=exc.stage,
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=request.implementation_plan_ref,
        )

    journal = PatchContinuationAttemptJournal(
        artifact_root=admitted.artifact_store.root,
        run_id=run_id,
        request_id=request_id,
        request=request,
        admitted=admitted,
    )
    try:
        _bind_patch_attempt_recorder(patch_change_factory, journal.record)
    except PatchContinuationError as exc:
        return blocked_patch_continuation_result(
            code=exc.code,
            stage=exc.stage,
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=request.implementation_plan_ref,
            source_validation={"status": "passed_before_patch", "before": admitted.source_validation},
            attempt_receipt=journal.projection(),
            source_modified_during_run=False,
        )

    from src.mod_agent.workflow.graph import build_graph

    state = _patch_continuation_state(
        run_id=run_id,
        request_id=request_id,
        request=request,
        admitted=admitted,
    )
    try:
        graph = build_graph(
            admitted.artifact_store,
            patch_change_factory=patch_change_factory,
            dry_run_factory=dry_run_factory,
            use_default_proposal_git_binding=False,
            proposal_source_snippet_char_limit=_proposal_source_snippet_char_limit(
                admitted
            ),
            patch_continuation_mode=request,
            patch_continuation_attempt_recorder=journal.record,
        )
        graph_result = graph.invoke(state)
    except Exception as exc:
        failed_node = getattr(exc, "_mod_agent_graph_node", None)
        failure_stage = str(
            getattr(exc, "stage", None) or failed_node or "workflow"
        )
        current_snapshot = _source_tree_snapshot_sha256(
            _csharp_source_snapshot(Path(request.workspace_root).resolve())
        )
        failure_code = str(getattr(exc, "code", type(exc).__name__))
        journal.record(
            {
                "phase": "continuation_failed",
                "current_snapshot_sha256": current_snapshot,
                "failure": {
                    "code": failure_code,
                    "failure_class": type(exc).__name__,
                    "stage": failure_stage,
                },
                "proposal_admitted": False,
            }
        )
        receipt = journal.projection()
        source_modified = (
            current_snapshot
            != _source_tree_snapshot_sha256(admitted.source_tree_snapshot)
        )
        counts = _failed_patch_execution_counts(
            failed_node if isinstance(failed_node, str) else None,
            model_call_count=int(receipt.get("model_call_count") or 0),
        )
        return blocked_patch_continuation_result(
            code=failure_code,
            stage=failure_stage,
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=request.implementation_plan_ref,
            source_validation={
                "status": "failed_during_continuation",
                "before": admitted.source_validation,
                "current_snapshot_sha256": current_snapshot,
            },
            execution_counts=counts,
            attempt_receipt=receipt,
            source_modified_during_run=source_modified,
            status="partial" if counts["model"] else "blocked",
        )

    patch_ref = _ref_from_patch_state(
        graph_result,
        "patch_proposal",
        feature_id=feature_id,
    )
    review_ref = _ref_from_patch_state(
        graph_result,
        "proposal_review",
        feature_id=feature_id,
    )
    dry_run_ref = _ref_from_patch_state(
        graph_result,
        "dry_run_result",
        feature_id=feature_id,
    )
    artifacts = {
        artifact_type: _artifact_ref_dict(ref)
        for artifact_type, ref in (
            ("patch_proposal", patch_ref),
            ("proposal_review", review_ref),
            ("dry_run_result", dry_run_ref),
        )
        if ref is not None
    }
    journal.record(
        {
            "phase": "workflow_artifacts_persisted",
            "artifacts": artifacts,
            "proposal_admitted": patch_ref is not None and not graph_result.get("blockers"),
        }
    )
    try:
        after = preflight_patch_continuation(
            request,
            artifact_store=admitted.artifact_store,
        )
    except PatchContinuationError as exc:
        current_snapshot = _source_tree_snapshot_sha256(
            _csharp_source_snapshot(Path(request.workspace_root).resolve())
        )
        journal.record(
            {
                "phase": "post_workflow_admission_rejected",
                "current_snapshot_sha256": current_snapshot,
                "failure": {
                    "code": exc.code,
                    "failure_class": type(exc).__name__,
                    "stage": exc.stage,
                },
                "proposal_admitted": False,
            }
        )
        counts = _patch_execution_counts(
            graph_result,
            model_call_count=int(journal.projection().get("model_call_count") or 0),
        )
        return blocked_patch_continuation_result(
            code=exc.code,
            stage=exc.stage,
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=request.implementation_plan_ref,
            patch_proposal_ref=patch_ref,
            proposal_review_ref=review_ref,
            dry_run_ref=dry_run_ref,
            source_validation={"status": "failed_after_workflow", "before": admitted.source_validation},
            execution_counts=counts,
            attempt_receipt=journal.projection(),
            source_modified_during_run=None,
            status="partial",
        )
    source_modified = after.source_tree_snapshot != admitted.source_tree_snapshot
    if source_modified:
        code = "PATCH_CONTINUATION_SOURCE_CHANGED_DURING_WORKFLOW"
        journal.record(
            {
                "phase": "post_workflow_source_rejected",
                "current_snapshot_sha256": _source_tree_snapshot_sha256(
                    after.source_tree_snapshot
                ),
                "failure": {
                    "code": code,
                    "failure_class": "PatchContinuationError",
                    "stage": "source_validation",
                },
                "proposal_admitted": False,
            }
        )
        return blocked_patch_continuation_result(
            code=code,
            stage="source_validation",
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=request.implementation_plan_ref,
            patch_proposal_ref=patch_ref,
            proposal_review_ref=review_ref,
            dry_run_ref=dry_run_ref,
            source_validation={
                "status": "failed_after_workflow",
                "before": admitted.source_validation,
                "after": after.source_validation,
            },
            execution_counts=_patch_execution_counts(
                graph_result,
                model_call_count=int(journal.projection().get("model_call_count") or 0),
            ),
            attempt_receipt=journal.projection(),
            source_modified_during_run=True,
            status="partial",
        )

    first_failure = _patch_first_failure(graph_result)
    pre_terminal_receipt = journal.projection()
    counts = _patch_execution_counts(
        graph_result,
        model_call_count=int(pre_terminal_receipt.get("model_call_count") or 0),
    )
    expected_counts = {
        "fresh_coverage": 0,
        "model": 1,
        "planning": 0,
        "patch": 1,
        "review": 1,
        "dry_run": 1,
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }
    complete = (
        first_failure is None
        and patch_ref is not None
        and review_ref is not None
        and dry_run_ref is not None
        and graph_result.get("current_stage") == "dry_run_apply"
        and counts == expected_counts
    )
    terminal_phase = (
        "stopped_before_exact_diff_approval"
        if complete
        else "continuation_blocked"
    )
    journal.record(
        {
            "phase": terminal_phase,
            "current_snapshot_sha256": _source_tree_snapshot_sha256(
                after.source_tree_snapshot
            ),
            "proposal_admitted": complete,
            "source_tree_unchanged": True,
        }
    )
    receipt = journal.projection()
    if not complete:
        failure = first_failure or {
            "code": "PATCH_CONTINUATION_INCOMPLETE",
            "stage": str(graph_result.get("current_stage") or "workflow"),
        }
        return blocked_patch_continuation_result(
            code=failure["code"],
            stage=failure["stage"],
            duration_seconds=time.perf_counter() - started,
            run_id=run_id,
            request_id=request_id,
            feature_id=feature_id,
            feature_spec_ref=request.feature_spec_ref,
            evidence_pack_ref=request.evidence_pack_ref,
            implementation_plan_ref=request.implementation_plan_ref,
            patch_proposal_ref=patch_ref,
            proposal_review_ref=review_ref,
            dry_run_ref=dry_run_ref,
            source_validation={
                "status": "passed",
                "before": admitted.source_validation,
                "after_snapshot_sha256": after.source_validation["snapshot_sha256"],
                "source_tree_unchanged": True,
            },
            execution_counts=counts,
            attempt_receipt=receipt,
            source_modified_during_run=False,
            status="partial" if counts["model"] else "blocked",
        )
    return PatchContinuationResultV1(
        status="terminal",
        terminal_stage="dry_run_apply",
        first_failure=None,
        run_id=run_id,
        request_id=request_id,
        feature_id=feature_id,
        feature_spec_artifact=_artifact_ref_dict(request.feature_spec_ref),
        evidence_pack_artifact=_artifact_ref_dict(request.evidence_pack_ref),
        implementation_plan_artifact=_artifact_ref_dict(
            request.implementation_plan_ref
        ),
        patch_proposal_artifact=_artifact_ref_dict(patch_ref),
        proposal_review_artifact=_artifact_ref_dict(review_ref),
        dry_run_artifact=_artifact_ref_dict(dry_run_ref),
        source_validation={
            "status": "passed",
            "before": admitted.source_validation,
            "after_snapshot_sha256": after.source_validation["snapshot_sha256"],
            "source_tree_unchanged": True,
        },
        execution_counts=counts,
        attempt_receipt=receipt,
        source_modified_during_run=False,
        duration_seconds=time.perf_counter() - started,
    )
