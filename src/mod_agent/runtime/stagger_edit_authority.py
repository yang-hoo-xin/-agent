"""No-write Edit Authority preflight for the current Stagger failure."""

from __future__ import annotations

import copy
import hashlib
import json
import re
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
_EXISTING_STAGGER_REPAIR_BINDING_ID = "edit_binding_004"
_EXISTING_BINDING_REAUTHORIZATION_SCHEMA = (
    "stagger_existing_binding_reauthorization_v1"
)
_EXISTING_BINDING_REQUEST_SCHEMA = (
    "stagger_existing_binding_reauthorization_request_v1"
)
_EXISTING_BINDING_AUTHORITY_CONTRACT = (
    "edit_authority_existing_binding_reauthorization_v1"
)


class StaggerEditAuthorityPreflightError(ValueError):
    """Raised when current evidence cannot produce a reviewed scope."""


class StaggerEditAuthorityApprovalError(
    StaggerEditAuthorityPreflightError
):
    """Raised before or during exact approved authority persistence."""


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
    _require_latest_artifact_refs(store, refs.values())
    freshness = {
        artifact_type: store.check_exact_revision_freshness(ref)
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

    (
        diagnosis,
        stored_ownership,
        replayed_ownership,
    ) = _replay_stagger_visual_failure(
        feature_id=feature_id,
        feature_spec=feature_spec,
        runtime_evidence=runtime_evidence,
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
    proposal_hash = "sha256:" + hashlib.sha256(
        _canonical_json(proposal)
    ).hexdigest()
    return {
        "status": "READY_TO_CREATE_EDIT_AUTHORITY_REQUEST",
        "command": "preflight-stagger-edit-authority",
        "proposal": proposal,
        "proposal_hash": proposal_hash,
        "request_creation_required": True,
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


def create_stagger_edit_authority_request(
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
    """Persist one exact technical request without granting authority."""

    preflight = preflight_stagger_edit_authority(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        run_id=run_id,
        feature_spec_path=feature_spec_path,
        feature_spec_hash=feature_spec_hash,
        runtime_evidence_path=runtime_evidence_path,
        runtime_evidence_hash=runtime_evidence_hash,
        implementation_plan_path=implementation_plan_path,
        implementation_plan_hash=implementation_plan_hash,
        patch_proposal_path=patch_proposal_path,
        patch_proposal_hash=patch_proposal_hash,
        source_root=source_root,
        canonical_target_path=canonical_target_path,
        target_symbol=target_symbol,
        target_start_line=target_start_line,
        target_end_line=target_end_line,
        proposed_operation=proposed_operation,
    )
    store = ArtifactStore(artifact_store_root)
    refs = _authority_refs(
        feature_id=feature_id,
        feature_spec_path=feature_spec_path,
        feature_spec_hash=feature_spec_hash,
        runtime_evidence_path=runtime_evidence_path,
        runtime_evidence_hash=runtime_evidence_hash,
        implementation_plan_path=implementation_plan_path,
        implementation_plan_hash=implementation_plan_hash,
        patch_proposal_path=patch_proposal_path,
        patch_proposal_hash=patch_proposal_hash,
    )
    _require_latest_artifact_refs(store, refs.values())
    plan = _artifact_data(store.read(refs["implementation_plan"]))
    proposal = copy.deepcopy(preflight["proposal"])
    source_identity = _validate_source_identity(
        source_root=source_root,
        canonical_target_path=canonical_target_path,
        target_symbol=target_symbol,
        target_start_line=target_start_line,
        target_end_line=target_end_line,
    )
    if source_identity != proposal["current_source"]:
        raise StaggerEditAuthorityApprovalError(
            "The current source identity changed before request persistence."
        )
    binding_id = _next_sequential_id(
        (
            binding.get("binding_id")
            for binding in (
                plan.get("binding_registry", {}).get("edit_bindings", ())
            )
            if isinstance(binding, dict)
        ),
        prefix="edit_binding_",
    )
    change_id = _next_sequential_id(
        (
            change.get("change_id")
            for change in plan.get("proposed_changes", ())
            if isinstance(change, dict)
        ),
        prefix="chg_",
    )
    request_payload = {
        "schema_version": "stagger_edit_authority_request_v1",
        "proposal": proposal,
        "source_root": str(Path(source_root).resolve()),
        "projected_ids": {
            "binding_id": binding_id,
            "change_id": change_id,
            "evidence_id": _approved_evidence_id(
                approval_hash=preflight["proposal_hash"],
                source_identity=source_identity,
                target_symbol=target_symbol,
            ),
        },
    }
    request_hash = "sha256:" + hashlib.sha256(
        _canonical_json(request_payload)
    ).hexdigest()
    request_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": (
                "Exact technical Edit Authority request awaits LangGraph "
                "human review."
            ),
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": run_id,
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        status="success",
        upstream_refs=[
            refs["feature_spec"],
            refs["runtime_evidence"],
            refs["implementation_plan"],
            refs["patch_proposal"],
        ],
        exact_revision_upstream_types={
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        },
    )
    return {
        "status": "EDIT_AUTHORITY_REQUEST_CREATED",
        "command": "request-stagger-edit-authority",
        "request_hash": request_hash,
        "edit_authority_request_revision": _revision(request_ref),
        "authority_granted": False,
        "registry_mutation_allowed": False,
        "repair_planner_invoked": False,
        "repair_allowed": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
        "writes_performed": True,
        "written_artifact_types": ["edit_authority_request"],
    }


def preflight_stagger_existing_binding_reauthorization(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    run_id: str,
    feature_spec_path: str | Path,
    feature_spec_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    predecessor_implementation_plan_path: str | Path,
    predecessor_implementation_plan_hash: str,
    patch_proposal_path: str | Path,
    patch_proposal_hash: str,
    current_implementation_plan_path: str | Path,
    current_implementation_plan_hash: str,
    existing_binding_resolution_path: str | Path,
    existing_binding_resolution_hash: str,
    source_root: str | Path,
    canonical_target_path: str,
    target_symbol: str,
    target_start_line: int,
    target_end_line: int,
) -> dict[str, Any]:
    """Read-validate the one existing Stagger repair binding without writes."""

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

    store = ArtifactStore(artifact_store_root)
    refs = _existing_binding_reauthorization_refs(
        feature_id=feature_id,
        feature_spec_path=feature_spec_path,
        feature_spec_hash=feature_spec_hash,
        runtime_evidence_path=runtime_evidence_path,
        runtime_evidence_hash=runtime_evidence_hash,
        predecessor_implementation_plan_path=(
            predecessor_implementation_plan_path
        ),
        predecessor_implementation_plan_hash=(
            predecessor_implementation_plan_hash
        ),
        patch_proposal_path=patch_proposal_path,
        patch_proposal_hash=patch_proposal_hash,
        current_implementation_plan_path=current_implementation_plan_path,
        current_implementation_plan_hash=current_implementation_plan_hash,
        existing_binding_resolution_path=existing_binding_resolution_path,
        existing_binding_resolution_hash=existing_binding_resolution_hash,
    )
    envelopes = {
        role: store.read(ref)
        for role, ref in refs.items()
    }
    current_refs = (
        refs["feature_spec"],
        refs["runtime_evidence"],
        refs["patch_proposal"],
        refs["current_implementation_plan"],
        refs["existing_binding_resolution"],
    )
    _require_latest_artifact_refs(store, current_refs)
    _require_registered_exact_revision(
        store,
        refs["predecessor_implementation_plan"],
    )
    stale = {
        role: list(view.stale_reasons)
        for role, view in (
            (
                role,
                store.check_exact_revision_freshness(ref),
            )
            for role, ref in refs.items()
        )
        if not view.is_fresh
    }
    if stale:
        raise StaggerEditAuthorityPreflightError(
            f"Selected Artifact revisions are stale: {stale}"
        )

    feature_spec = _artifact_data(envelopes["feature_spec"])
    runtime_evidence = _artifact_data(envelopes["runtime_evidence"])
    predecessor_plan = _artifact_data(
        envelopes["predecessor_implementation_plan"]
    )
    patch_proposal = _artifact_data(envelopes["patch_proposal"])
    current_plan = _artifact_data(
        envelopes["current_implementation_plan"]
    )
    existing_resolution = _artifact_data(
        envelopes["existing_binding_resolution"]
    )
    _validate_existing_binding_reauthorization_lineage(
        feature_id=feature_id,
        run_id=run_id,
        refs=refs,
        envelopes=envelopes,
        runtime_evidence=runtime_evidence,
        predecessor_plan=predecessor_plan,
        patch_proposal=patch_proposal,
        current_plan=current_plan,
        existing_resolution=existing_resolution,
    )
    (
        diagnosis,
        stored_ownership,
        replayed_ownership,
    ) = _replay_stagger_visual_failure(
        feature_id=feature_id,
        feature_spec=feature_spec,
        runtime_evidence=runtime_evidence,
    )
    source_identity = _validate_source_identity(
        source_root=source_root,
        canonical_target_path=canonical_target_path,
        target_symbol=target_symbol,
        target_start_line=target_start_line,
        target_end_line=target_end_line,
    )
    binding, change = _require_existing_repair_binding(
        current_plan=current_plan,
        source_identity=source_identity,
        target_symbol=target_symbol,
    )
    bound_diagnosis = copy.deepcopy(diagnosis)
    anchors = bound_diagnosis["responsibility_anchors"]
    anchors["canonical_target_path"] = canonical_target_path
    anchors["source_hash"] = source_identity["sha256"]
    anchors["source_span"] = copy.deepcopy(
        source_identity["target_span"]
    )
    replayed_resolution = resolve_runtime_diagnosis_binding(
        diagnosis=bound_diagnosis,
        feature_id=feature_id,
        run_id=run_id,
        runtime_evidence_revision=_revision(refs["runtime_evidence"]),
        implementation_plan_revision=_revision(
            refs["current_implementation_plan"]
        ),
        patch_proposal_revision=_revision(refs["patch_proposal"]),
        implementation_plan=current_plan,
        allowed_edit_binding_ids={
            _EXISTING_STAGGER_REPAIR_BINDING_ID
        },
    ).to_artifact_payload()
    existing_target = existing_resolution.get("resolved_repair_target")
    replayed_target = replayed_resolution.get("resolved_repair_target")
    if (
        replayed_resolution.get("result_type")
        != "resolved_repair_target"
        or not isinstance(replayed_target, dict)
        or replayed_target.get("binding_id")
        != _EXISTING_STAGGER_REPAIR_BINDING_ID
        or replayed_resolution.get("blockers")
        or replayed_target != existing_target
    ):
        raise StaggerEditAuthorityPreflightError(
            "Current facts do not reproduce the exact existing "
            "ResolvedRepairTarget."
        )

    proposal = {
        "schema_version": _EXISTING_BINDING_REAUTHORIZATION_SCHEMA,
        "feature_id": feature_id,
        "run_id": run_id,
        "feature_spec_revision": _revision(refs["feature_spec"]),
        "runtime_evidence_revision": _revision(
            refs["runtime_evidence"]
        ),
        "predecessor_implementation_plan_revision": _revision(
            refs["predecessor_implementation_plan"]
        ),
        "patch_proposal_revision": _revision(refs["patch_proposal"]),
        "current_implementation_plan_revision": _revision(
            refs["current_implementation_plan"]
        ),
        "existing_binding_resolution_revision": _revision(
            refs["existing_binding_resolution"]
        ),
        "binding_id": _EXISTING_STAGGER_REPAIR_BINDING_ID,
        "preserved_edit_binding": copy.deepcopy(binding),
        "preserved_change": copy.deepcopy(change),
        "preserved_resolved_repair_target": copy.deepcopy(
            existing_target
        ),
        "current_source": source_identity,
        "ownership_review": {
            "stored_runtime_failure_ownership": copy.deepcopy(
                stored_ownership
            ),
            "replayed_runtime_failure_ownership": copy.deepcopy(
                replayed_ownership
            ),
            "runtime_evidence_mutation_allowed": False,
        },
        "root_cause_status": diagnosis.get("root_cause_status"),
        "unresolved_root_causes": list(
            diagnosis.get("unresolved_root_causes", ())
        ),
        "projection_boundary": {
            "new_edit_binding_allowed": False,
            "evidence_pack_revision_allowed": False,
            "implementation_plan_revision_allowed": False,
            "binding_resolution_revision_allowed": True,
            "technical_semantics_change_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
    }
    proposal_hash = "sha256:" + hashlib.sha256(
        _canonical_json(proposal)
    ).hexdigest()
    return {
        "status": "READY_TO_CREATE_EXISTING_BINDING_REAUTHORIZATION_REQUEST",
        "command": (
            "preflight-stagger-existing-binding-reauthorization"
        ),
        "proposal": proposal,
        "proposal_hash": proposal_hash,
        "request_creation_required": True,
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


def create_stagger_existing_binding_reauthorization_request(
    **kwargs: Any,
) -> dict[str, Any]:
    """Persist one no-authority request for the existing Stagger binding."""

    preflight = preflight_stagger_existing_binding_reauthorization(
        **kwargs
    )
    feature_id = str(kwargs["feature_id"])
    run_id = str(kwargs["run_id"])
    store = ArtifactStore(kwargs["artifact_store_root"])
    refs = _existing_binding_reauthorization_refs(
        feature_id=feature_id,
        feature_spec_path=kwargs["feature_spec_path"],
        feature_spec_hash=kwargs["feature_spec_hash"],
        runtime_evidence_path=kwargs["runtime_evidence_path"],
        runtime_evidence_hash=kwargs["runtime_evidence_hash"],
        predecessor_implementation_plan_path=kwargs[
            "predecessor_implementation_plan_path"
        ],
        predecessor_implementation_plan_hash=kwargs[
            "predecessor_implementation_plan_hash"
        ],
        patch_proposal_path=kwargs["patch_proposal_path"],
        patch_proposal_hash=kwargs["patch_proposal_hash"],
        current_implementation_plan_path=kwargs[
            "current_implementation_plan_path"
        ],
        current_implementation_plan_hash=kwargs[
            "current_implementation_plan_hash"
        ],
        existing_binding_resolution_path=kwargs[
            "existing_binding_resolution_path"
        ],
        existing_binding_resolution_hash=kwargs[
            "existing_binding_resolution_hash"
        ],
    )
    request_payload = {
        "schema_version": _EXISTING_BINDING_REQUEST_SCHEMA,
        "proposal": copy.deepcopy(preflight["proposal"]),
        "source_root": str(Path(kwargs["source_root"]).resolve()),
    }
    request_hash = "sha256:" + hashlib.sha256(
        _canonical_json(request_payload)
    ).hexdigest()
    request_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        payload={
            "node_name": (
                "request_stagger_existing_binding_reauthorization"
            ),
            "stage": "edit_authority_request",
            "message": (
                "Exact existing-binding reauthorization request awaits "
                "LangGraph human review."
            ),
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": run_id,
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        status="success",
        upstream_refs=[
            refs["feature_spec"],
            refs["runtime_evidence"],
            refs["predecessor_implementation_plan"],
            refs["patch_proposal"],
            refs["current_implementation_plan"],
            refs["existing_binding_resolution"],
        ],
        exact_revision_upstream_types={
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
            "binding_resolution",
        },
    )
    return {
        "status": "EXISTING_BINDING_REAUTHORIZATION_REQUEST_CREATED",
        "command": (
            "request-stagger-existing-binding-reauthorization"
        ),
        "request_hash": request_hash,
        "edit_authority_request_revision": _revision(request_ref),
        "authority_granted": False,
        "registry_mutation_allowed": False,
        "repair_planner_invoked": False,
        "repair_allowed": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
        "writes_performed": True,
        "written_artifact_types": ["edit_authority_request"],
    }


def _apply_approved_stagger_edit_authority(
    *,
    approval_hash: str,
    approved_by: str,
    approved_at: str,
    resume_id: str,
    request_ref: ArtifactRef,
    resume_report_ref: ArtifactRef,
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
    """Materialize one graph-approved request and stop after resolution."""

    preflight = preflight_stagger_edit_authority(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        run_id=run_id,
        feature_spec_path=feature_spec_path,
        feature_spec_hash=feature_spec_hash,
        runtime_evidence_path=runtime_evidence_path,
        runtime_evidence_hash=runtime_evidence_hash,
        implementation_plan_path=implementation_plan_path,
        implementation_plan_hash=implementation_plan_hash,
        patch_proposal_path=patch_proposal_path,
        patch_proposal_hash=patch_proposal_hash,
        source_root=source_root,
        canonical_target_path=canonical_target_path,
        target_symbol=target_symbol,
        target_start_line=target_start_line,
        target_end_line=target_end_line,
        proposed_operation=proposed_operation,
    )
    actor = approved_by.strip()
    approval_time = approved_at.strip()
    if not actor or not approval_time or not resume_id:
        raise StaggerEditAuthorityApprovalError(
            "Graph approval identity must be complete."
        )

    store = ArtifactStore(artifact_store_root)
    request = _artifact_data(store.read(request_ref))
    request_payload = request.get("request_payload")
    if (
        request.get("request_hash") != approval_hash
        or not isinstance(request_payload, dict)
        or request_payload.get("proposal") != preflight["proposal"]
        or "sha256:"
        + hashlib.sha256(_canonical_json(request_payload)).hexdigest()
        != approval_hash
    ):
        raise StaggerEditAuthorityApprovalError(
            "The graph-approved request does not match the fresh proposal."
        )
    refs = _authority_refs(
        feature_id=feature_id,
        feature_spec_path=feature_spec_path,
        feature_spec_hash=feature_spec_hash,
        runtime_evidence_path=runtime_evidence_path,
        runtime_evidence_hash=runtime_evidence_hash,
        implementation_plan_path=implementation_plan_path,
        implementation_plan_hash=implementation_plan_hash,
        patch_proposal_path=patch_proposal_path,
        patch_proposal_hash=patch_proposal_hash,
    )
    envelopes = {
        artifact_type: store.read(ref)
        for artifact_type, ref in refs.items()
    }
    old_plan = _artifact_data(envelopes["implementation_plan"])
    old_evidence_ref = _single_upstream_ref(
        envelopes["implementation_plan"],
        feature_id=feature_id,
        artifact_type="evidence_pack",
    )
    old_evidence_envelope = store.read(old_evidence_ref)
    old_evidence_freshness = store.check_freshness(old_evidence_ref)
    if not old_evidence_freshness.is_fresh:
        raise StaggerEditAuthorityApprovalError(
            "The Implementation Plan EvidencePack is stale: "
            f"{list(old_evidence_freshness.stale_reasons)}"
        )
    old_evidence = _artifact_data(old_evidence_envelope)

    proposal = copy.deepcopy(preflight["proposal"])
    source_identity = _validate_source_identity(
        source_root=source_root,
        canonical_target_path=canonical_target_path,
        target_symbol=target_symbol,
        target_start_line=target_start_line,
        target_end_line=target_end_line,
    )
    if source_identity != proposal["current_source"]:
        raise StaggerEditAuthorityApprovalError(
            "The current source identity changed after approval preflight."
        )
    projected_ids = request_payload.get("projected_ids")
    if not isinstance(projected_ids, dict):
        raise StaggerEditAuthorityApprovalError(
            "The approved request has no exact projected identifiers."
        )
    binding_id = str(projected_ids.get("binding_id") or "")
    change_id = str(projected_ids.get("change_id") or "")
    evidence_id = str(projected_ids.get("evidence_id") or "")
    if not binding_id or not change_id or not evidence_id:
        raise StaggerEditAuthorityApprovalError(
            "The approved request projected identifiers are incomplete."
        )
    approval_payload = _build_approval_payload(
        feature_id=feature_id,
        run_id=run_id,
        approved_by=actor,
        approved_at=approval_time,
        resume_id=resume_id,
        approval_hash=approval_hash,
        request_ref=request_ref,
        resume_report_ref=resume_report_ref,
    )

    store.preflight_atomic_commit(
        feature_id=feature_id,
        artifact_types=(
            "edit_authority_approval",
            "evidence_pack",
            "implementation_plan",
            "binding_resolution",
        ),
    )
    approval_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_approval",
        payload=approval_payload,
        status="success",
        upstream_refs=[
            request_ref,
            resume_report_ref,
        ],
        exact_revision_upstream_types={
            "edit_authority_request",
            "resume_report",
        },
    )

    evidence_payload = _build_evidence_pack_revision(
        old_evidence=old_evidence,
        evidence_id=evidence_id,
        approval_ref=approval_ref,
        runtime_evidence_ref=refs["runtime_evidence"],
        source_identity=source_identity,
        target_symbol=target_symbol,
    )
    evidence_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        payload=evidence_payload,
        status=str(old_evidence_envelope["status"]),
        upstream_refs=[
            refs["feature_spec"],
            refs["runtime_evidence"],
            approval_ref,
            old_evidence_ref,
        ],
        exact_revision_upstream_types={
            "runtime_evidence",
            "edit_authority_approval",
            "evidence_pack",
        },
    )

    plan_payload = _build_implementation_plan_revision(
        old_plan=old_plan,
        binding_id=binding_id,
        change_id=change_id,
        evidence_id=evidence_id,
        evidence_ref=evidence_ref,
        approval_ref=approval_ref,
        proposal=proposal,
        source_identity=source_identity,
    )
    plan_ref = store.write(
        feature_id=feature_id,
        artifact_type="implementation_plan",
        payload=plan_payload,
        status="success",
        upstream_refs=[
            refs["feature_spec"],
            evidence_ref,
            approval_ref,
            refs["implementation_plan"],
        ],
        exact_revision_upstream_types={
            "edit_authority_approval",
            "implementation_plan",
        },
    )

    runtime_evidence = _artifact_data(envelopes["runtime_evidence"])
    diagnosis = _approved_bound_diagnosis(
        feature_id=feature_id,
        runtime_evidence=runtime_evidence,
        proposal=proposal,
    )
    resolution = resolve_runtime_diagnosis_binding(
        diagnosis=diagnosis,
        feature_id=feature_id,
        run_id=run_id,
        runtime_evidence_revision=_revision(refs["runtime_evidence"]),
        implementation_plan_revision=_revision(plan_ref),
        patch_proposal_revision=_revision(refs["patch_proposal"]),
        implementation_plan=plan_payload,
        allowed_edit_binding_ids={binding_id},
    ).to_artifact_payload()
    if (
        resolution.get("result_type") != "resolved_repair_target"
        or not isinstance(resolution.get("resolved_repair_target"), dict)
        or resolution["resolved_repair_target"].get("binding_id")
        != binding_id
        or resolution.get("blockers")
    ):
        raise StaggerEditAuthorityApprovalError(
            "The approved authority did not resolve to exactly one target."
        )
    resolution["authority_source"] = "edit_authority_approval"
    resolution["authority_contract_version"] = (
        "edit_authority_request_approval_v1"
    )
    resolution["edit_authority_approval_revision"] = _revision(
        approval_ref
    )
    resolution["edit_authority_request_revision"] = _revision(
        request_ref
    )
    resolution["evidence_pack_revision"] = _revision(evidence_ref)
    resolution["approved_runtime_failure_ownership"] = copy.deepcopy(
        proposal["ownership_review"][
            "replayed_runtime_failure_ownership"
        ]
    )
    resolution["repair_planner_allowed"] = False
    resolution["source_patch_allowed"] = False
    resolution_ref = store.write(
        feature_id=feature_id,
        artifact_type="binding_resolution",
        payload=resolution,
        status="success",
        upstream_refs=[
            refs["runtime_evidence"],
            plan_ref,
            refs["patch_proposal"],
            request_ref,
            approval_ref,
            evidence_ref,
        ],
        exact_revision_upstream_types={
            "runtime_evidence",
            "patch_proposal",
            "edit_authority_request",
            "edit_authority_approval",
            "evidence_pack",
        },
    )
    return {
        "status": "EXACT_EDIT_AUTHORITY_RESOLVED",
        "command": "langgraph-edit-authority-approval",
        "approval_hash": approval_hash,
        "approved_by": actor,
        "edit_authority_approval_revision": _revision(approval_ref),
        "evidence_pack_revision": _revision(evidence_ref),
        "implementation_plan_revision": _revision(plan_ref),
        "binding_resolution_revision": _revision(resolution_ref),
        "allowed_edit_binding_ids": [binding_id],
        "resolved_repair_target": copy.deepcopy(
            resolution["resolved_repair_target"]
        ),
        "writes_performed": True,
        "artifact_writes_performed": True,
        "written_artifact_types": [
            "edit_authority_approval",
            "evidence_pack",
            "implementation_plan",
            "binding_resolution",
        ],
        "runtime_evidence_modified": False,
        "old_patch_proposal_modified": False,
        "repair_planner_invoked": False,
        "repair_allowed": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }


def materialize_stagger_edit_authority_approval(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    edit_authority_request_path: str | Path,
    edit_authority_request_hash: str,
    resume_report_path: str | Path,
    resume_report_hash: str,
) -> dict[str, Any]:
    """Validate one graph resume and materialize its bounded projections."""

    store = ArtifactStore(artifact_store_root)
    request_ref = _artifact_ref(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        path=edit_authority_request_path,
        artifact_hash=edit_authority_request_hash,
    )
    request_envelope = store.read(request_ref)
    request = _artifact_data(request_envelope)
    if request.get("feature_id") != feature_id:
        raise StaggerEditAuthorityApprovalError(
            "EditAuthorityRequest feature identity is invalid."
        )
    request_payload = request.get("request_payload")
    request_schema = (
        request_payload.get("schema_version")
        if isinstance(request_payload, dict)
        else None
    )
    request_freshness = store.check_freshness(request_ref)
    if not request_freshness.is_fresh:
        raise StaggerEditAuthorityApprovalError(
            "EditAuthorityRequest is stale: "
            f"{list(request_freshness.stale_reasons)}"
        )
    request_upstream_refs = _upstream_refs_from_envelope(
        request_envelope,
        feature_id=feature_id,
    )
    if request_schema == _EXISTING_BINDING_REQUEST_SCHEMA:
        _require_latest_artifact_refs(store, (request_ref,))
    else:
        _require_latest_artifact_refs(
            store,
            (request_ref, *request_upstream_refs),
        )
    report_ref = _artifact_ref(
        feature_id=feature_id,
        artifact_type="resume_report",
        path=resume_report_path,
        artifact_hash=resume_report_hash,
    )
    report_envelope = store.read(report_ref)
    report = _artifact_data(report_envelope)
    checkpoint_ref = _single_upstream_ref(
        report_envelope,
        feature_id=feature_id,
        artifact_type="workflow_checkpoint",
    )
    checkpoint = _artifact_data(store.read(checkpoint_ref))
    state_snapshot = checkpoint.get("state_snapshot")
    snapshot_artifacts = (
        state_snapshot.get("artifacts")
        if isinstance(state_snapshot, dict)
        else None
    )
    snapshot_hashes = (
        state_snapshot.get("artifact_hashes")
        if isinstance(state_snapshot, dict)
        else None
    )
    resume_binding = checkpoint.get("resume_binding")
    if (
        report.get("status") != "accepted"
        or report.get("allowed") is not True
        or report.get("decision") != "approve"
        or report.get("resume_stage") != "edit_authority_approval"
        or report.get("run_id") != request.get("run_id")
        or checkpoint.get("checkpoint_stage")
        != "edit_authority_approval"
        or checkpoint.get("run_id") != request.get("run_id")
        or checkpoint.get("feature_id") != feature_id
        or not isinstance(state_snapshot, dict)
        or not isinstance(snapshot_artifacts, dict)
        or not isinstance(snapshot_hashes, dict)
        or snapshot_artifacts.get("edit_authority_request")
        != request_ref.path
        or snapshot_hashes.get("edit_authority_request")
        != request_ref.artifact_hash
        or not isinstance(resume_binding, dict)
        or resume_binding.get("edit_authority_request_ref")
        != request_ref.path
        or resume_binding.get("edit_authority_request_artifact_hash")
        != request_ref.artifact_hash
        or resume_binding.get("edit_authority_request_hash")
        != request.get("request_hash")
        or report.get("authority_request_hash")
        != request.get("request_hash")
        or not isinstance(report.get("approved_by"), str)
        or not report["approved_by"].strip()
        or not isinstance(report.get("approved_at"), str)
        or not report["approved_at"].strip()
    ):
        raise StaggerEditAuthorityApprovalError(
            "ResumeReport does not bind the exact EditAuthorityRequest."
        )
    proposal = (
        request_payload.get("proposal")
        if isinstance(request_payload, dict)
        else None
    )
    source_root = (
        request_payload.get("source_root")
        if isinstance(request_payload, dict)
        else None
    )
    if not isinstance(proposal, dict) or not isinstance(source_root, str):
        raise StaggerEditAuthorityApprovalError(
            "EditAuthorityRequest technical payload is invalid."
        )
    if (
        request_payload.get("schema_version")
        == _EXISTING_BINDING_REQUEST_SCHEMA
    ):
        return _apply_approved_existing_binding_reauthorization(
            approval_hash=str(request["request_hash"]),
            approved_by=str(report["approved_by"]),
            approved_at=str(report["approved_at"]),
            resume_id=str(report["resume_id"]),
            request_ref=request_ref,
            resume_report_ref=report_ref,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            run_id=str(request["run_id"]),
            request_payload=request_payload,
        )
    if request_payload.get("schema_version") != (
        "stagger_edit_authority_request_v1"
    ):
        raise StaggerEditAuthorityApprovalError(
            "EditAuthorityRequest schema is not supported."
        )
    return _apply_approved_stagger_edit_authority(
        approval_hash=str(request["request_hash"]),
        approved_by=str(report["approved_by"]),
        approved_at=str(report["approved_at"]),
        resume_id=str(report["resume_id"]),
        request_ref=request_ref,
        resume_report_ref=report_ref,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        run_id=str(request["run_id"]),
        feature_spec_path=proposal["feature_spec_revision"]["path"],
        feature_spec_hash=proposal["feature_spec_revision"]["artifact_hash"],
        runtime_evidence_path=proposal["runtime_evidence_revision"]["path"],
        runtime_evidence_hash=proposal["runtime_evidence_revision"][
            "artifact_hash"
        ],
        implementation_plan_path=proposal[
            "implementation_plan_revision"
        ]["path"],
        implementation_plan_hash=proposal[
            "implementation_plan_revision"
        ]["artifact_hash"],
        patch_proposal_path=proposal["patch_proposal_revision"]["path"],
        patch_proposal_hash=proposal["patch_proposal_revision"][
            "artifact_hash"
        ],
        source_root=source_root,
        canonical_target_path=proposal["current_source"][
            "canonical_target_path"
        ],
        target_symbol=proposal["proposed_target_symbol"],
        target_start_line=proposal["proposed_exact_span"]["start_line"],
        target_end_line=proposal["proposed_exact_span"]["end_line"],
        proposed_operation=proposal["proposed_operation"],
    )


def _apply_approved_existing_binding_reauthorization(
    *,
    approval_hash: str,
    approved_by: str,
    approved_at: str,
    resume_id: str,
    request_ref: ArtifactRef,
    resume_report_ref: ArtifactRef,
    artifact_store_root: str | Path,
    feature_id: str,
    run_id: str,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    """Reauthorize one existing binding without changing its technical scope."""

    proposal = request_payload.get("proposal")
    source_root = request_payload.get("source_root")
    if not isinstance(proposal, dict) or not isinstance(source_root, str):
        raise StaggerEditAuthorityApprovalError(
            "Existing-binding reauthorization payload is invalid."
        )
    preflight = preflight_stagger_existing_binding_reauthorization(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        run_id=run_id,
        feature_spec_path=proposal["feature_spec_revision"]["path"],
        feature_spec_hash=proposal[
            "feature_spec_revision"
        ]["artifact_hash"],
        runtime_evidence_path=proposal[
            "runtime_evidence_revision"
        ]["path"],
        runtime_evidence_hash=proposal[
            "runtime_evidence_revision"
        ]["artifact_hash"],
        predecessor_implementation_plan_path=proposal[
            "predecessor_implementation_plan_revision"
        ]["path"],
        predecessor_implementation_plan_hash=proposal[
            "predecessor_implementation_plan_revision"
        ]["artifact_hash"],
        patch_proposal_path=proposal["patch_proposal_revision"]["path"],
        patch_proposal_hash=proposal[
            "patch_proposal_revision"
        ]["artifact_hash"],
        current_implementation_plan_path=proposal[
            "current_implementation_plan_revision"
        ]["path"],
        current_implementation_plan_hash=proposal[
            "current_implementation_plan_revision"
        ]["artifact_hash"],
        existing_binding_resolution_path=proposal[
            "existing_binding_resolution_revision"
        ]["path"],
        existing_binding_resolution_hash=proposal[
            "existing_binding_resolution_revision"
        ]["artifact_hash"],
        source_root=source_root,
        canonical_target_path=proposal["current_source"][
            "canonical_target_path"
        ],
        target_symbol=proposal[
            "preserved_edit_binding"
        ]["target_symbol"],
        target_start_line=proposal["current_source"][
            "target_span"
        ]["start_line"],
        target_end_line=proposal["current_source"][
            "target_span"
        ]["end_line"],
    )
    actor = approved_by.strip()
    approval_time = approved_at.strip()
    if not actor or not approval_time or not resume_id:
        raise StaggerEditAuthorityApprovalError(
            "Graph approval identity must be complete."
        )
    store = ArtifactStore(artifact_store_root)
    request = _artifact_data(store.read(request_ref))
    if (
        request.get("request_hash") != approval_hash
        or preflight["proposal"] != proposal
        or "sha256:"
        + hashlib.sha256(_canonical_json(request_payload)).hexdigest()
        != approval_hash
    ):
        raise StaggerEditAuthorityApprovalError(
            "The graph-approved Request does not match the fresh "
            "existing-binding reauthorization."
        )
    refs = _existing_binding_reauthorization_refs(
        feature_id=feature_id,
        feature_spec_path=proposal["feature_spec_revision"]["path"],
        feature_spec_hash=proposal[
            "feature_spec_revision"
        ]["artifact_hash"],
        runtime_evidence_path=proposal[
            "runtime_evidence_revision"
        ]["path"],
        runtime_evidence_hash=proposal[
            "runtime_evidence_revision"
        ]["artifact_hash"],
        predecessor_implementation_plan_path=proposal[
            "predecessor_implementation_plan_revision"
        ]["path"],
        predecessor_implementation_plan_hash=proposal[
            "predecessor_implementation_plan_revision"
        ]["artifact_hash"],
        patch_proposal_path=proposal["patch_proposal_revision"]["path"],
        patch_proposal_hash=proposal[
            "patch_proposal_revision"
        ]["artifact_hash"],
        current_implementation_plan_path=proposal[
            "current_implementation_plan_revision"
        ]["path"],
        current_implementation_plan_hash=proposal[
            "current_implementation_plan_revision"
        ]["artifact_hash"],
        existing_binding_resolution_path=proposal[
            "existing_binding_resolution_revision"
        ]["path"],
        existing_binding_resolution_hash=proposal[
            "existing_binding_resolution_revision"
        ]["artifact_hash"],
    )
    existing_resolution = _artifact_data(
        store.read(refs["existing_binding_resolution"])
    )
    evidence_revision = existing_resolution.get(
        "evidence_pack_revision"
    )
    if not isinstance(evidence_revision, dict):
        raise StaggerEditAuthorityApprovalError(
            "Existing BindingResolution has no exact EvidencePack revision."
        )
    evidence_ref = _artifact_ref(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        path=evidence_revision["path"],
        artifact_hash=evidence_revision["artifact_hash"],
    )
    evidence_freshness = store.check_exact_revision_freshness(
        evidence_ref
    )
    if not evidence_freshness.is_fresh:
        raise StaggerEditAuthorityApprovalError(
            "Existing EvidencePack revision is stale: "
            f"{list(evidence_freshness.stale_reasons)}"
        )
    approval_payload = _build_approval_payload(
        feature_id=feature_id,
        run_id=run_id,
        approved_by=actor,
        approved_at=approval_time,
        resume_id=resume_id,
        approval_hash=approval_hash,
        request_ref=request_ref,
        resume_report_ref=resume_report_ref,
        authority_contract_version=(
            _EXISTING_BINDING_AUTHORITY_CONTRACT
        ),
    )
    store.preflight_atomic_commit(
        feature_id=feature_id,
        artifact_types=(
            "edit_authority_approval",
            "binding_resolution",
        ),
    )
    approval_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_approval",
        payload=approval_payload,
        status="success",
        upstream_refs=[request_ref, resume_report_ref],
        exact_revision_upstream_types={
            "edit_authority_request",
            "resume_report",
        },
    )
    resolution = copy.deepcopy(existing_resolution)
    resolution["authority_source"] = "edit_authority_approval"
    resolution["authority_contract_version"] = (
        _EXISTING_BINDING_AUTHORITY_CONTRACT
    )
    resolution["edit_authority_request_revision"] = _revision(
        request_ref
    )
    resolution["edit_authority_approval_revision"] = _revision(
        approval_ref
    )
    resolution["previous_binding_resolution_revision"] = _revision(
        refs["existing_binding_resolution"]
    )
    resolution["predecessor_implementation_plan_revision"] = _revision(
        refs["predecessor_implementation_plan"]
    )
    resolution["repair_planner_allowed"] = False
    resolution["source_patch_allowed"] = False
    resolution_ref = store.write(
        feature_id=feature_id,
        artifact_type="binding_resolution",
        payload=resolution,
        status="success",
        upstream_refs=[
            refs["feature_spec"],
            refs["runtime_evidence"],
            refs["predecessor_implementation_plan"],
            refs["patch_proposal"],
            refs["current_implementation_plan"],
            refs["existing_binding_resolution"],
            request_ref,
            approval_ref,
            evidence_ref,
        ],
        exact_revision_upstream_types={
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
            "binding_resolution",
            "edit_authority_request",
            "edit_authority_approval",
            "evidence_pack",
        },
    )
    return {
        "status": "EXISTING_EDIT_AUTHORITY_REAUTHORIZED",
        "command": "langgraph-edit-authority-approval",
        "approval_hash": approval_hash,
        "approved_by": actor,
        "edit_authority_approval_revision": _revision(approval_ref),
        "evidence_pack_revision": _revision(evidence_ref),
        "implementation_plan_revision": _revision(
            refs["current_implementation_plan"]
        ),
        "binding_resolution_revision": _revision(resolution_ref),
        "allowed_edit_binding_ids": [
            _EXISTING_STAGGER_REPAIR_BINDING_ID
        ],
        "resolved_repair_target": copy.deepcopy(
            resolution["resolved_repair_target"]
        ),
        "writes_performed": True,
        "artifact_writes_performed": True,
        "written_artifact_types": [
            "edit_authority_approval",
            "binding_resolution",
        ],
        "evidence_pack_modified": False,
        "implementation_plan_modified": False,
        "new_edit_binding_created": False,
        "repair_planner_invoked": False,
        "repair_allowed": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }


def _authority_refs(
    *,
    feature_id: str,
    feature_spec_path: str | Path,
    feature_spec_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    implementation_plan_path: str | Path,
    implementation_plan_hash: str,
    patch_proposal_path: str | Path,
    patch_proposal_hash: str,
) -> dict[str, ArtifactRef]:
    return {
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


def _existing_binding_reauthorization_refs(
    *,
    feature_id: str,
    feature_spec_path: str | Path,
    feature_spec_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    predecessor_implementation_plan_path: str | Path,
    predecessor_implementation_plan_hash: str,
    patch_proposal_path: str | Path,
    patch_proposal_hash: str,
    current_implementation_plan_path: str | Path,
    current_implementation_plan_hash: str,
    existing_binding_resolution_path: str | Path,
    existing_binding_resolution_hash: str,
) -> dict[str, ArtifactRef]:
    return {
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
        "predecessor_implementation_plan": _artifact_ref(
            feature_id=feature_id,
            artifact_type="implementation_plan",
            path=predecessor_implementation_plan_path,
            artifact_hash=predecessor_implementation_plan_hash,
        ),
        "patch_proposal": _artifact_ref(
            feature_id=feature_id,
            artifact_type="patch_proposal",
            path=patch_proposal_path,
            artifact_hash=patch_proposal_hash,
        ),
        "current_implementation_plan": _artifact_ref(
            feature_id=feature_id,
            artifact_type="implementation_plan",
            path=current_implementation_plan_path,
            artifact_hash=current_implementation_plan_hash,
        ),
        "existing_binding_resolution": _artifact_ref(
            feature_id=feature_id,
            artifact_type="binding_resolution",
            path=existing_binding_resolution_path,
            artifact_hash=existing_binding_resolution_hash,
        ),
    }


def _require_registered_exact_revision(
    store: ArtifactStore,
    ref: ArtifactRef,
) -> None:
    matches = {
        (
            str(Path(revision.path).resolve()),
            revision.artifact_hash,
        )
        for revision in store.list_feature_artifact_revisions(
            ref.feature_id,
            ref.artifact_type,
        )
    }
    if (
        str(Path(ref.path).resolve()),
        ref.artifact_hash,
    ) not in matches:
        raise StaggerEditAuthorityPreflightError(
            f"{ref.artifact_type} is not an exact registered revision."
        )


def _validate_existing_binding_reauthorization_lineage(
    *,
    feature_id: str,
    run_id: str,
    refs: dict[str, ArtifactRef],
    envelopes: dict[str, dict[str, Any]],
    runtime_evidence: dict[str, Any],
    predecessor_plan: dict[str, Any],
    patch_proposal: dict[str, Any],
    current_plan: dict[str, Any],
    existing_resolution: dict[str, Any],
) -> None:
    feature_spec_hash = refs["feature_spec"].artifact_hash
    predecessor_hash = refs[
        "predecessor_implementation_plan"
    ].artifact_hash
    current_plan_hash = refs[
        "current_implementation_plan"
    ].artifact_hash
    patch_proposal_hash = refs["patch_proposal"].artifact_hash
    runtime_evidence_hash = refs["runtime_evidence"].artifact_hash
    if (
        runtime_evidence.get("feature_id") != feature_id
        or runtime_evidence.get("run_id") != run_id
        or not _has_upstream_revision(
            envelopes["runtime_evidence"],
            artifact_type="feature_spec",
            artifact_hash=feature_spec_hash,
        )
    ):
        raise StaggerEditAuthorityPreflightError(
            "RuntimeEvidence identity or FeatureSpec lineage is invalid."
        )
    if (
        predecessor_plan.get("feature_id") != feature_id
        or not _has_upstream_revision(
            envelopes["predecessor_implementation_plan"],
            artifact_type="feature_spec",
            artifact_hash=feature_spec_hash,
        )
    ):
        raise StaggerEditAuthorityPreflightError(
            "The predecessor ImplementationPlan lineage is invalid."
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
        or registry_ref.get("artifact_hash") != predecessor_hash
        or not _has_upstream_revision(
            envelopes["patch_proposal"],
            artifact_type="implementation_plan",
            artifact_hash=predecessor_hash,
        )
    ):
        raise StaggerEditAuthorityPreflightError(
            "PatchProposal does not exactly bind the predecessor "
            "ImplementationPlan."
        )
    if (
        current_plan.get("feature_id") != feature_id
        or not _has_upstream_revision(
            envelopes["current_implementation_plan"],
            artifact_type="feature_spec",
            artifact_hash=feature_spec_hash,
        )
        or not _has_upstream_revision(
            envelopes["current_implementation_plan"],
            artifact_type="implementation_plan",
            artifact_hash=predecessor_hash,
        )
    ):
        raise StaggerEditAuthorityPreflightError(
            "The current ImplementationPlan does not exactly extend the "
            "predecessor Plan."
        )
    if (
        existing_resolution.get("feature_id") != feature_id
        or existing_resolution.get("run_id") != run_id
        or existing_resolution.get("result_type")
        != "resolved_repair_target"
        or existing_resolution.get("authority_source")
        != "edit_authority_approval"
        or existing_resolution.get("repair_planner_allowed") is not False
        or existing_resolution.get("source_patch_allowed") is not False
        or existing_resolution.get(
            "implementation_plan_revision", {}
        ).get("artifact_hash")
        != current_plan_hash
        or existing_resolution.get(
            "patch_proposal_revision", {}
        ).get("artifact_hash")
        != patch_proposal_hash
        or not _has_upstream_revision(
            envelopes["existing_binding_resolution"],
            artifact_type="runtime_evidence",
            artifact_hash=runtime_evidence_hash,
        )
        or not _has_upstream_revision(
            envelopes["existing_binding_resolution"],
            artifact_type="implementation_plan",
            artifact_hash=current_plan_hash,
        )
        or not _has_upstream_revision(
            envelopes["existing_binding_resolution"],
            artifact_type="patch_proposal",
            artifact_hash=patch_proposal_hash,
        )
    ):
        raise StaggerEditAuthorityPreflightError(
            "The existing BindingResolution lineage or stop boundary is "
            "invalid."
        )


def _require_existing_repair_binding(
    *,
    current_plan: dict[str, Any],
    source_identity: dict[str, Any],
    target_symbol: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bindings = current_plan.get("binding_registry", {}).get(
        "edit_bindings"
    )
    changes = current_plan.get("proposed_changes")
    if not isinstance(bindings, list) or not isinstance(changes, list):
        raise StaggerEditAuthorityPreflightError(
            "The current ImplementationPlan Registry is invalid."
        )
    matching_bindings = [
        item
        for item in bindings
        if isinstance(item, dict)
        and item.get("binding_id")
        == _EXISTING_STAGGER_REPAIR_BINDING_ID
    ]
    matching_changes = [
        item
        for item in changes
        if isinstance(item, dict)
        and item.get("edit_binding_id")
        == _EXISTING_STAGGER_REPAIR_BINDING_ID
    ]
    if len(matching_bindings) != 1 or len(matching_changes) != 1:
        raise StaggerEditAuthorityPreflightError(
            "The current Plan does not contain exactly one existing Stagger "
            "repair binding and change."
        )
    binding = matching_bindings[0]
    change = matching_changes[0]
    if (
        binding.get("target_symbol") != target_symbol
        or binding.get("canonical_target_path")
        != source_identity["canonical_target_path"]
        or binding.get("source_hash") != source_identity["sha256"]
        or binding.get("target_span") != source_identity["target_span"]
        or change.get("change_id") != "chg_004"
        or change.get("operation")
        != "replace_hud_recttransform_acquisition_and_null_guard_only"
    ):
        raise StaggerEditAuthorityPreflightError(
            "The existing Stagger repair binding or change no longer matches "
            "the exact current source responsibility."
        )
    return copy.deepcopy(binding), copy.deepcopy(change)


def _has_upstream_revision(
    envelope: dict[str, Any],
    *,
    artifact_type: str,
    artifact_hash: str,
) -> bool:
    inputs = envelope.get("inputs")
    upstreams = (
        inputs.get("upstream_artifacts")
        if isinstance(inputs, dict)
        else ()
    )
    return any(
        isinstance(item, dict)
        and item.get("artifact_type") == artifact_type
        and item.get("artifact_hash") == artifact_hash
        for item in upstreams
    )


def _single_upstream_ref(
    envelope: dict[str, Any],
    *,
    feature_id: str,
    artifact_type: str,
) -> ArtifactRef:
    inputs = envelope.get("inputs")
    upstreams = (
        inputs.get("upstream_artifacts")
        if isinstance(inputs, dict)
        else ()
    )
    matches = [
        item
        for item in upstreams
        if isinstance(item, dict)
        and item.get("artifact_type") == artifact_type
        and isinstance(item.get("path"), str)
        and isinstance(item.get("artifact_hash"), str)
    ]
    if len(matches) != 1:
        raise StaggerEditAuthorityApprovalError(
            f"Expected one exact {artifact_type} upstream."
        )
    item = matches[0]
    return _artifact_ref(
        feature_id=feature_id,
        artifact_type=artifact_type,
        path=str(item["path"]),
        artifact_hash=str(item["artifact_hash"]),
    )


def _upstream_refs_from_envelope(
    envelope: dict[str, Any],
    *,
    feature_id: str,
) -> tuple[ArtifactRef, ...]:
    inputs = envelope.get("inputs")
    upstreams = (
        inputs.get("upstream_artifacts")
        if isinstance(inputs, dict)
        else None
    )
    if not isinstance(upstreams, list):
        raise StaggerEditAuthorityApprovalError(
            "Artifact upstream inputs are invalid."
        )
    refs: list[ArtifactRef] = []
    for upstream in upstreams:
        if (
            not isinstance(upstream, dict)
            or not isinstance(upstream.get("artifact_type"), str)
            or not isinstance(upstream.get("path"), str)
            or not isinstance(upstream.get("artifact_hash"), str)
        ):
            raise StaggerEditAuthorityApprovalError(
                "Artifact upstream identity is invalid."
            )
        refs.append(
            _artifact_ref(
                feature_id=feature_id,
                artifact_type=str(upstream["artifact_type"]),
                path=str(upstream["path"]),
                artifact_hash=str(upstream["artifact_hash"]),
            )
        )
    return tuple(refs)


def _require_latest_artifact_refs(
    store: ArtifactStore,
    refs: Any,
) -> None:
    selected = tuple(refs)
    if not selected:
        raise StaggerEditAuthorityApprovalError(
            "Current authority inputs are empty."
        )
    feature_id = selected[0].feature_id
    latest = {
        ref.artifact_type: ref
        for ref in store.list_feature_artifacts(feature_id)
    }
    for ref in selected:
        latest_ref = latest.get(ref.artifact_type)
        revision_paths = {
            str(Path(revision.path).resolve())
            for revision in store.list_feature_artifact_revisions(
                feature_id,
                ref.artifact_type,
            )
            if revision.artifact_hash == ref.artifact_hash
        }
        if (
            ref.feature_id != feature_id
            or latest_ref is None
            or latest_ref.artifact_hash != ref.artifact_hash
            or str(Path(ref.path).resolve()) not in revision_paths
        ):
            raise StaggerEditAuthorityApprovalError(
                f"{ref.artifact_type} is no longer the current revision."
            )


def _next_sequential_id(values: Any, *, prefix: str) -> str:
    pattern = re.compile(re.escape(prefix) + r"([0-9]{3})")
    numbers: list[int] = []
    for value in values:
        if not isinstance(value, str):
            raise StaggerEditAuthorityApprovalError(
                f"Existing {prefix} identity is invalid."
            )
        match = pattern.fullmatch(value)
        if match is None:
            raise StaggerEditAuthorityApprovalError(
                f"Existing {prefix} identity is invalid."
            )
        numbers.append(int(match.group(1)))
    if not numbers or len(numbers) != len(set(numbers)):
        raise StaggerEditAuthorityApprovalError(
            f"Existing {prefix} identities are incomplete or duplicated."
        )
    next_number = max(numbers) + 1
    if next_number > 999:
        raise StaggerEditAuthorityApprovalError(
            f"No bounded {prefix} identity remains."
        )
    return f"{prefix}{next_number:03d}"


def _approved_evidence_id(
    *,
    approval_hash: str,
    source_identity: dict[str, Any],
    target_symbol: str,
) -> str:
    identity = {
        "approval_hash": approval_hash,
        "canonical_target_path": source_identity["canonical_target_path"],
        "source_hash": source_identity["sha256"],
        "target_span": source_identity["target_span"],
        "target_symbol": target_symbol,
    }
    return (
        "stagger_repair_"
        + hashlib.sha256(_canonical_json(identity)).hexdigest()[:20]
    )


def _build_approval_payload(
    *,
    feature_id: str,
    run_id: str,
    approved_by: str,
    approved_at: str,
    resume_id: str,
    approval_hash: str,
    request_ref: ArtifactRef,
    resume_report_ref: ArtifactRef,
    authority_contract_version: str = (
        "edit_authority_request_approval_v1"
    ),
) -> dict[str, Any]:
    if (
        authority_contract_version
        == _EXISTING_BINDING_AUTHORITY_CONTRACT
    ):
        allowed_actions = [
            "reauthorize_existing_edit_binding",
            "create_binding_resolution_revision",
        ]
        forbidden_actions = [
            "create_evidence_pack_revision",
            "create_implementation_plan_revision",
            "create_edit_binding",
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ]
    else:
        allowed_actions = [
            "create_evidence_pack_revision",
            "create_implementation_plan_revision",
            "resolve_exact_edit_binding",
        ]
        forbidden_actions = [
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ]
    return {
        "node_name": "approve_stagger_edit_authority",
        "stage": "edit_authority_approval",
        "message": (
            "LangGraph human approval permits only the exact request "
            "projection and strict Binding resolution."
        ),
        "status": "approved",
        "feature_id": feature_id,
        "run_id": run_id,
        "authority_source": "edit_authority_request",
        "authority_contract_version": authority_contract_version,
        "approval_hash": approval_hash,
        "request_hash": approval_hash,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "resume_id": resume_id,
        "decision": "approve",
        "edit_authority_request_revision": _revision(request_ref),
        "resume_report_revision": _revision(resume_report_ref),
        "allowed_actions": allowed_actions,
        "forbidden_actions": forbidden_actions,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }


def _build_evidence_pack_revision(
    *,
    old_evidence: dict[str, Any],
    evidence_id: str,
    approval_ref: ArtifactRef,
    runtime_evidence_ref: ArtifactRef,
    source_identity: dict[str, Any],
    target_symbol: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(old_evidence)
    items = payload.get("items")
    if not isinstance(items, list):
        raise StaggerEditAuthorityApprovalError(
            "The current EvidencePack items are invalid."
        )
    if any(
        isinstance(item, dict)
        and (
            item.get("evidence_id") == evidence_id
            or item.get("symbol") == target_symbol
        )
        for item in items
    ):
        raise StaggerEditAuthorityApprovalError(
            "The approved repair evidence already exists or is ambiguous."
        )
    span = source_identity["target_span"]
    source_path = Path(source_identity["resolved_path"])
    lines = source_path.read_text(encoding="utf-8").splitlines()
    excerpt = "\n".join(
        lines[span["start_line"] - 1 : span["end_line"]]
    ) + "\n"
    items.append(
        {
            "authority": "human_exact_edit_authority",
            "chunk_id": None,
            "claim_supported": (
                "The current Build source contains the exact "
                "dependency_unavailable_early_return block and the bound "
                "Runtime facts confirm its missing_canvas_rect_for_stagger_x "
                "outcome; the underlying HUD dependency root cause remains "
                "unresolved."
            ),
            "declared_member_types": None,
            "declared_members": None,
            "declaring_type": None,
            "declaring_type_full_name": None,
            "doc_hash": None,
            "document_id": None,
            "evidence_id": evidence_id,
            "excerpt": excerpt,
            "file_hash": source_identity["sha256"],
            "method_kind": None,
            "method_name": "TrySpawnStaggerYellowX",
            "parameter_types": None,
            "retrieval_method": (
                "approved_runtime_diagnosis_and_current_source_read"
            ),
            "return_type": None,
            "risk_notes": [
                (
                    "This evidence proves the exact failure point and edit "
                    "scope, not which unresolved HUD dependency cause is true."
                )
            ],
            "score": 1.0,
            "source_hash": source_identity["sha256"],
            "source_path": source_identity["canonical_target_path"],
            "source_ref": source_identity["resolved_path"],
            "source_type": "target_source",
            "span": copy.deepcopy(span),
            "symbol": target_symbol,
            "usage": "edit_scope_evidence",
            "verified_member_accesses": [],
            "edit_authority_approval_ref": _revision(approval_ref),
            "runtime_evidence_ref": _revision(runtime_evidence_ref),
        }
    )
    payload["message"] = (
        "The existing sufficient EvidencePack now includes one exact "
        "human-approved Runtime repair edit scope."
    )
    trace_refs = [
        str(item)
        for item in payload.get("trace_refs", ())
        if isinstance(item, str)
    ]
    for ref_path in (approval_ref.path, runtime_evidence_ref.path):
        if ref_path not in trace_refs:
            trace_refs.append(ref_path)
    payload["trace_refs"] = trace_refs
    return payload


def _build_implementation_plan_revision(
    *,
    old_plan: dict[str, Any],
    binding_id: str,
    change_id: str,
    evidence_id: str,
    evidence_ref: ArtifactRef,
    approval_ref: ArtifactRef,
    proposal: dict[str, Any],
    source_identity: dict[str, Any],
) -> dict[str, Any]:
    payload = copy.deepcopy(old_plan)
    registry = payload.get("binding_registry")
    changes = payload.get("proposed_changes")
    if (
        not isinstance(registry, dict)
        or not isinstance(registry.get("edit_bindings"), list)
        or not isinstance(changes, list)
    ):
        raise StaggerEditAuthorityApprovalError(
            "The current Implementation Plan Registry is invalid."
        )
    registry["edit_bindings"].append(
        {
            "authority": "human_exact_edit_authority",
            "binding_id": binding_id,
            "canonical_target_path": source_identity[
                "canonical_target_path"
            ],
            "claim_supported": (
                "The approved Runtime diagnosis binds the exact early-return "
                "dependency block while leaving its root cause unresolved."
            ),
            "declared_member_types": None,
            "declared_members": None,
            "declaring_type": (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch"
            ),
            "declaring_type_full_name": (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch"
            ),
            "evidence_id": evidence_id,
            "method_kind": None,
            "method_name": "TrySpawnStaggerYellowX",
            "parameter_types": None,
            "retrieval_method": (
                "approved_runtime_diagnosis_and_current_source_read"
            ),
            "return_type": None,
            "source_hash": source_identity["sha256"],
            "source_type": "target_source",
            "target_span": copy.deepcopy(
                source_identity["target_span"]
            ),
            "target_symbol": proposal["proposed_target_symbol"],
            "usage": "edit_target_scope",
            "verified_member_accesses": [],
            "edit_authority_approval_ref": _revision(approval_ref),
            "evidence_pack_ref": _revision(evidence_ref),
        }
    )
    changes.append(
        {
            "change_id": change_id,
            "change_type": "repair_hud_recttransform_acquisition",
            "edit_binding_id": binding_id,
            "expected_validation": list(payload.get("test_plan", ())),
            "hook_target_binding_id": None,
            "operation": proposal["proposed_operation"],
            "rationale": (
                "Repair planning may inspect only the approved HUD "
                "RectTransform acquisition and null-guard span. It may not "
                "select among unresolved root causes without further evidence."
            ),
            "risk_tags": [
                "high",
                "runtime_ui_binding",
                "root_cause_unresolved",
            ],
            "rollback_hint": (
                "Restore the exact approved source span before any later "
                "source change."
            ),
            "supporting_binding_ids": [],
        }
    )
    payload["message"] = (
        "Implementation Plan authority is extended by one exact "
        "human-approved Stagger Runtime repair binding."
    )
    for field_name, value in (
        ("evidence_refs", evidence_id),
        ("target_files", source_identity["canonical_target_path"]),
        ("target_symbols", proposal["proposed_target_symbol"]),
    ):
        values = payload.get(field_name)
        if not isinstance(values, list):
            raise StaggerEditAuthorityApprovalError(
                f"Implementation Plan {field_name} is invalid."
            )
        if value not in values:
            values.append(value)
    rollback_plan = payload.get("rollback_plan")
    if not isinstance(rollback_plan, list):
        raise StaggerEditAuthorityApprovalError(
            "Implementation Plan rollback_plan is invalid."
        )
    rollback_plan.append(
        f"Rollback {change_id}: restore the approved exact source span."
    )
    open_questions = payload.get("open_questions")
    if not isinstance(open_questions, list):
        raise StaggerEditAuthorityApprovalError(
            "Implementation Plan open_questions is invalid."
        )
    for root_cause in proposal.get("unresolved_root_causes", ()):
        question = f"Unresolved Runtime root cause: {root_cause}"
        if question not in open_questions:
            open_questions.append(question)
    return payload


def _replay_stagger_visual_failure(
    *,
    feature_id: str,
    feature_spec: dict[str, Any],
    runtime_evidence: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
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
            "RuntimeEvidence acceptance criteria do not exactly match "
            "FeatureSpec."
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
    return (
        diagnosis,
        copy.deepcopy(stored_ownership),
        replayed_ownership,
    )


def _approved_bound_diagnosis(
    *,
    feature_id: str,
    runtime_evidence: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    attempts = runtime_evidence.get("stagger_runtime_attempts")
    acceptance = runtime_evidence.get("acceptance_contract")
    if not isinstance(attempts, list) or not isinstance(acceptance, dict):
        raise StaggerEditAuthorityApprovalError(
            "RuntimeEvidence diagnosis inputs are invalid."
        )
    attempts_by_mode = {
        str(item.get("stagger_attempt_mode")): item
        for item in attempts
        if isinstance(item, dict)
        and isinstance(item.get("stagger_attempt_mode"), str)
    }
    criteria = tuple(
        str(item)
        for item in acceptance.get("acceptance_criteria", ())
        if isinstance(item, str) and item
    )
    evaluation = evaluate_stagger_acceptance(
        attempts_by_mode,
        expected_modes=_EXPECTED_MODES,
        acceptance_criteria=criteria,
    )
    diagnosis = build_stagger_runtime_failure_diagnosis(
        feature_id=feature_id,
        acceptance_evaluation=evaluation,
    )
    if diagnosis is None:
        raise StaggerEditAuthorityApprovalError(
            "The approved Runtime diagnosis no longer reproduces."
        )
    bound = copy.deepcopy(diagnosis)
    approved_anchor = proposal["diagnosed_responsibility_anchor"]
    anchors = bound["responsibility_anchors"]
    anchors["canonical_target_path"] = proposal["current_source"][
        "canonical_target_path"
    ]
    anchors["source_hash"] = approved_anchor["source_hash"]
    anchors["source_span"] = copy.deepcopy(
        approved_anchor["source_span"]
    )
    return bound


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
