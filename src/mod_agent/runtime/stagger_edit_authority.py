"""No-write Edit Authority preflight for the current Stagger failure."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from ..artifacts import ArtifactRef, ArtifactStore
from ..bindings.runtime_resolution import resolve_runtime_diagnosis_binding
from .evidence import build_runtime_failure_ownership
from .stagger_diagnosis import (
    build_stagger_runtime_failure_diagnosis,
    evaluate_stagger_acceptance,
)


_STAGGER_RUNTIME_SYMBOL = (
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "TrySpawnStaggerYellowX"
)
_STAGGER_METHOD_DECLARATION = (
    "private static bool TrySpawnStaggerYellowX("
    "Vector3 worldPos, out string reason)"
)
_EXPECTED_MODES = (
    "general_enabled_false",
    "general_enabled_true",
)
_DEPENDENCY_BLOCK_TOKENS = (
    "RectTransform? canvasRect = _lastHudParent as RectTransform;",
    "if (canvasRect == null)",
    'reason = "missing_canvas_rect_for_stagger_x";',
    "return false;",
)


class StaggerEditAuthorityPreflightError(ValueError):
    """Raised when current evidence cannot produce a reviewed scope."""


def preflight_stagger_edit_authority(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    run_id: str,
    feature_spec_path: str | Path,
    feature_spec_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    implementation_plan_path: str | Path,
    implementation_plan_hash: str,
    patch_proposal_path: str | Path,
    patch_proposal_hash: str,
    source_root: str | Path,
    canonical_target_path: str,
    target_symbol: str,
    target_start_line: int,
    target_end_line: int,
    proposed_operation: str,
) -> dict[str, Any]:
    """Re-evaluate immutable evidence and emit an exact no-write proposal."""

    if not feature_id or not run_id:
        raise StaggerEditAuthorityPreflightError(
            "feature_id and run_id must be non-empty."
        )
    if target_symbol != _STAGGER_RUNTIME_SYMBOL:
        raise StaggerEditAuthorityPreflightError(
            "The requested symbol is not the diagnosed Stagger responsibility."
        )
    if (
        not isinstance(target_start_line, int)
        or not isinstance(target_end_line, int)
        or target_start_line <= 0
        or target_end_line < target_start_line
    ):
        raise StaggerEditAuthorityPreflightError(
            "The proposed target span is invalid."
        )
    operation = proposed_operation.strip()
    if not operation:
        raise StaggerEditAuthorityPreflightError(
            "The proposed operation must be non-empty."
        )

    store = ArtifactStore(artifact_store_root)
    refs = {
        "feature_spec": _artifact_ref(
            feature_id=feature_id,
            artifact_type="feature_spec",
            path=feature_spec_path,
            artifact_hash=feature_spec_hash,
        ),
        "runtime_evidence": _artifact_ref(
            feature_id=feature_id,
            artifact_type="runtime_evidence",
            path=runtime_evidence_path,
            artifact_hash=runtime_evidence_hash,
        ),
        "implementation_plan": _artifact_ref(
            feature_id=feature_id,
            artifact_type="implementation_plan",
            path=implementation_plan_path,
            artifact_hash=implementation_plan_hash,
        ),
        "patch_proposal": _artifact_ref(
            feature_id=feature_id,
            artifact_type="patch_proposal",
            path=patch_proposal_path,
            artifact_hash=patch_proposal_hash,
        ),
    }
    envelopes = {
        artifact_type: store.read(ref)
        for artifact_type, ref in refs.items()
    }
    freshness = {
        artifact_type: store.check_freshness(ref)
        for artifact_type, ref in refs.items()
    }
    stale = {
        artifact_type: list(view.stale_reasons)
        for artifact_type, view in freshness.items()
        if not view.is_fresh
    }
    if stale:
        raise StaggerEditAuthorityPreflightError(
            f"Current Artifact revisions are stale: {stale}"
        )

    feature_spec = _artifact_data(envelopes["feature_spec"])
    runtime_evidence = _artifact_data(envelopes["runtime_evidence"])
    implementation_plan = _artifact_data(
        envelopes["implementation_plan"]
    )
    patch_proposal = _artifact_data(envelopes["patch_proposal"])
    _validate_artifact_lineage(
        feature_id=feature_id,
        run_id=run_id,
        feature_spec_ref=refs["feature_spec"],
        runtime_evidence=runtime_evidence,
        runtime_evidence_envelope=envelopes["runtime_evidence"],
        implementation_plan_ref=refs["implementation_plan"],
        implementation_plan_envelope=envelopes["implementation_plan"],
        patch_proposal=patch_proposal,
        patch_proposal_envelope=envelopes["patch_proposal"],
    )

    acceptance_criteria = tuple(
        str(item)
        for item in feature_spec.get("acceptance_criteria", ())
        if isinstance(item, str) and item
    )
    runtime_acceptance = tuple(
        str(item)
        for item in (
            runtime_evidence.get("acceptance_contract", {})
            .get("acceptance_criteria", ())
        )
        if isinstance(item, str) and item
    )
    if not acceptance_criteria or runtime_acceptance != acceptance_criteria:
        raise StaggerEditAuthorityPreflightError(
            "RuntimeEvidence acceptance criteria do not exactly match FeatureSpec."
        )

    attempts = runtime_evidence.get("stagger_runtime_attempts")
    if not isinstance(attempts, list):
        raise StaggerEditAuthorityPreflightError(
            "RuntimeEvidence has no Stagger attempt payloads."
        )
    attempts_by_mode = {
        str(item.get("stagger_attempt_mode")): item
        for item in attempts
        if isinstance(item, dict)
        and isinstance(item.get("stagger_attempt_mode"), str)
    }
    if any(mode not in attempts_by_mode for mode in _EXPECTED_MODES):
        raise StaggerEditAuthorityPreflightError(
            "RuntimeEvidence does not contain both exact Stagger modes."
        )
    semantic_status = runtime_evidence.get(
        "operator_semantic_consistency", {}
    )
    if (
        not isinstance(semantic_status, dict)
        or semantic_status.get("status") != "consistent"
    ):
        raise StaggerEditAuthorityPreflightError(
            "Operator observations are not semantically consistent."
        )

    acceptance_evaluation = evaluate_stagger_acceptance(
        attempts_by_mode,
        expected_modes=_EXPECTED_MODES,
        acceptance_criteria=acceptance_criteria,
    )
    diagnosis = build_stagger_runtime_failure_diagnosis(
        feature_id=feature_id,
        acceptance_evaluation=acceptance_evaluation,
    )
    if diagnosis is None:
        raise StaggerEditAuthorityPreflightError(
            "Current RuntimeEvidence does not deterministically diagnose the "
            "Stagger visual failure."
        )
    stored_ownership = runtime_evidence.get("failure_ownership")
    if (
        not isinstance(stored_ownership, dict)
        or stored_ownership.get("owner") != "observation"
        or stored_ownership.get("source_repair_allowed") is not False
    ):
        raise StaggerEditAuthorityPreflightError(
            "The selected RuntimeEvidence does not have the exact stored "
            "observation-owned no-source-repair boundary."
        )
    replayed_ownership = build_runtime_failure_ownership(
        owner="product_behavior",
        failure_class="stagger_visual_output_failed",
        reason=(
            "Deterministic replay of the immutable current-run attempts binds "
            "the exact yellow-X criterion to both the trusted "
            "missing_canvas_rect_for_stagger_x marker and a consistent direct "
            "operator failed observation."
        ),
    )

    source_identity = _validate_source_identity(
        source_root=source_root,
        canonical_target_path=canonical_target_path,
        target_symbol=target_symbol,
        target_start_line=target_start_line,
        target_end_line=target_end_line,
    )
    bound_diagnosis = copy.deepcopy(diagnosis)
    anchors = bound_diagnosis["responsibility_anchors"]
    anchors["canonical_target_path"] = canonical_target_path
    anchors["source_hash"] = source_identity["sha256"]
    anchors["source_span"] = {
        "start_line": target_start_line,
        "end_line": target_end_line,
    }

    context_pack = patch_proposal.get("context_pack")
    allowed_ids = {
        str(item)
        for item in (
            context_pack.get("allowed_edit_binding_ids", ())
            if isinstance(context_pack, dict)
            else ()
        )
        if isinstance(item, str)
    }
    existing_resolution = resolve_runtime_diagnosis_binding(
        diagnosis=bound_diagnosis,
        feature_id=feature_id,
        run_id=run_id,
        runtime_evidence_revision=_revision(refs["runtime_evidence"]),
        implementation_plan_revision=_revision(
            refs["implementation_plan"]
        ),
        patch_proposal_revision=_revision(refs["patch_proposal"]),
        implementation_plan=implementation_plan,
        allowed_edit_binding_ids=allowed_ids,
    ).to_artifact_payload()
    if existing_resolution["result_type"] != "binding_gap":
        raise StaggerEditAuthorityPreflightError(
            "The current Registry did not produce the required Binding Gap."
        )

    proposal = {
        "schema_version": "stagger_edit_authority_proposal_v1",
        "feature_id": feature_id,
        "run_id": run_id,
        "feature_spec_revision": _revision(refs["feature_spec"]),
        "runtime_evidence_revision": _revision(
            refs["runtime_evidence"]
        ),
        "implementation_plan_revision": _revision(
            refs["implementation_plan"]
        ),
        "patch_proposal_revision": _revision(refs["patch_proposal"]),
        "ownership_review": {
            "stored_runtime_failure_ownership": dict(stored_ownership),
            "replayed_runtime_failure_ownership": replayed_ownership,
            "reclassification_approval_required": True,
            "runtime_evidence_mutation_allowed": False,
            "boundary": (
                "The immutable RuntimeEvidence keeps its original observation "
                "owner. Any later authority record must bind this exact replay "
                "and human approval without rewriting that Artifact."
            ),
        },
        "diagnosed_responsibility_anchor": {
            "component": anchors.get("component"),
            "symbol": anchors.get("symbol"),
            "dependency": anchors.get("dependency"),
            "dependency_expression": anchors.get(
                "dependency_expression"
            ),
            "source_hash": anchors.get("source_hash"),
            "source_span": dict(anchors["source_span"]),
        },
        "current_source": source_identity,
        "proposed_target_symbol": target_symbol,
        "proposed_exact_span": {
            "start_line": target_start_line,
            "end_line": target_end_line,
        },
        "proposed_operation": operation,
        "existing_binding_gap": {
            "gap_reasons": list(
                existing_resolution["binding_gap"]["gap_reasons"]
            ),
            "existing_allowed_bindings": list(
                existing_resolution["binding_gap"][
                    "existing_allowed_bindings"
                ]
            ),
        },
        "current_edit_authority": {
            "allowed_binding_source": (
                "patch_proposal.context_pack.allowed_edit_binding_ids"
            ),
            "allowed_edit_binding_ids": sorted(allowed_ids),
            "old_patch_proposal_mutation_allowed": False,
            "reviewed_new_authority_record_required": True,
        },
        "approval_scope": [
            "runtime_failure_ownership_reclassification",
            "new_exact_edit_binding",
        ],
        "root_cause_status": diagnosis.get("root_cause_status"),
        "unresolved_root_causes": list(
            diagnosis.get("unresolved_root_causes", ())
        ),
    }
    approval_hash = "sha256:" + hashlib.sha256(
        _canonical_json(proposal)
    ).hexdigest()
    return {
        "status": "AWAITING_EXACT_EDIT_AUTHORITY_APPROVAL",
        "command": "preflight-stagger-edit-authority",
        "proposal": proposal,
        "approval_hash": approval_hash,
        "approval_required": True,
        "registry_mutation_allowed": False,
        "repair_allowed": False,
        "writes_performed": False,
        "artifact_writes_performed": False,
        "repair_planner_invoked": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }


def _artifact_ref(
    *,
    feature_id: str,
    artifact_type: str,
    path: str | Path,
    artifact_hash: str,
) -> ArtifactRef:
    return ArtifactRef(
        feature_id=feature_id,
        artifact_type=artifact_type,
        path=str(Path(path).resolve()),
        artifact_hash=artifact_hash,
    )


def _artifact_data(envelope: dict[str, Any]) -> dict[str, Any]:
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise StaggerEditAuthorityPreflightError(
            "Artifact data must be an object."
        )
    return data


def _validate_artifact_lineage(
    *,
    feature_id: str,
    run_id: str,
    feature_spec_ref: ArtifactRef,
    runtime_evidence: dict[str, Any],
    runtime_evidence_envelope: dict[str, Any],
    implementation_plan_ref: ArtifactRef,
    implementation_plan_envelope: dict[str, Any],
    patch_proposal: dict[str, Any],
    patch_proposal_envelope: dict[str, Any],
) -> None:
    if (
        runtime_evidence.get("feature_id") != feature_id
        or runtime_evidence.get("run_id") != run_id
    ):
        raise StaggerEditAuthorityPreflightError(
            "RuntimeEvidence feature/run identity does not match."
        )
    runtime_upstreams = _upstream_hashes(runtime_evidence_envelope)
    if runtime_upstreams.get("feature_spec") != feature_spec_ref.artifact_hash:
        raise StaggerEditAuthorityPreflightError(
            "RuntimeEvidence is not bound to the selected FeatureSpec."
        )
    if (
        _upstream_hashes(implementation_plan_envelope).get("feature_spec")
        != feature_spec_ref.artifact_hash
    ):
        raise StaggerEditAuthorityPreflightError(
            "ImplementationPlan is not bound to the selected FeatureSpec."
        )
    context_pack = patch_proposal.get("context_pack")
    registry_ref = (
        context_pack.get("binding_registry_ref")
        if isinstance(context_pack, dict)
        else None
    )
    if (
        patch_proposal.get("feature_id") != feature_id
        or not isinstance(registry_ref, dict)
        or registry_ref.get("artifact_type") != "implementation_plan"
        or registry_ref.get("artifact_hash")
        != implementation_plan_ref.artifact_hash
        or _upstream_hashes(patch_proposal_envelope).get(
            "implementation_plan"
        )
        != implementation_plan_ref.artifact_hash
    ):
        raise StaggerEditAuthorityPreflightError(
            "PatchProposal is not bound to the selected Implementation Plan."
        )


def _upstream_hashes(envelope: dict[str, Any]) -> dict[str, str]:
    inputs = envelope.get("inputs")
    upstreams = (
        inputs.get("upstream_artifacts")
        if isinstance(inputs, dict)
        else None
    )
    if not isinstance(upstreams, list):
        return {}
    return {
        str(item["artifact_type"]): str(item["artifact_hash"])
        for item in upstreams
        if isinstance(item, dict)
        and isinstance(item.get("artifact_type"), str)
        and isinstance(item.get("artifact_hash"), str)
    }


def _validate_source_identity(
    *,
    source_root: str | Path,
    canonical_target_path: str,
    target_symbol: str,
    target_start_line: int,
    target_end_line: int,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise StaggerEditAuthorityPreflightError(
            "The explicit source root does not exist."
        )
    canonical = PurePosixPath(canonical_target_path)
    if canonical.is_absolute() or ".." in canonical.parts:
        raise StaggerEditAuthorityPreflightError(
            "The canonical target path is unsafe."
        )
    source_path = (root / Path(*canonical.parts)).resolve()
    try:
        relative = source_path.relative_to(root)
    except ValueError as exc:
        raise StaggerEditAuthorityPreflightError(
            "The target source is outside the explicit source root."
        ) from exc
    if relative.as_posix() != canonical_target_path:
        raise StaggerEditAuthorityPreflightError(
            "The resolved target path does not match the canonical path."
        )
    if not source_path.is_file():
        raise StaggerEditAuthorityPreflightError(
            "The exact target source file does not exist."
        )

    content = source_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if target_end_line > len(lines):
        raise StaggerEditAuthorityPreflightError(
            "The proposed target span exceeds the current source."
        )
    declarations = [
        index
        for index, line in enumerate(lines, start=1)
        if line.strip() == _STAGGER_METHOD_DECLARATION
    ]
    if target_symbol != _STAGGER_RUNTIME_SYMBOL or len(declarations) != 1:
        raise StaggerEditAuthorityPreflightError(
            "The exact Stagger method declaration is not unique."
        )
    target_lines = lines[target_start_line - 1 : target_end_line]
    target_text = "\n".join(target_lines)
    if any(token not in target_text for token in _DEPENDENCY_BLOCK_TOKENS):
        raise StaggerEditAuthorityPreflightError(
            "The exact target span does not contain the diagnosed dependency block."
        )
    return {
        "canonical_target_path": canonical_target_path,
        "resolved_path": str(source_path),
        "sha256": hashlib.sha256(source_path.read_bytes())
        .hexdigest()
        .upper(),
        "line_count": len(lines),
        "method_declaration_line": declarations[0],
        "target_span": {
            "start_line": target_start_line,
            "end_line": target_end_line,
        },
    }


def _revision(ref: ArtifactRef) -> dict[str, str]:
    return {
        "feature_id": ref.feature_id,
        "path": ref.path,
        "artifact_hash": ref.artifact_hash,
    }


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
