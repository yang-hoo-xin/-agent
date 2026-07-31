"""Exact Stagger RepairPlanner authority and materialization boundary."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from ..artifacts import ArtifactRef, ArtifactStore
from ..repair import RepairPlanner
from .stagger_hierarchy_observation import (
    merge_stagger_hierarchy_observation,
)
from .stagger_root_cause import preflight_stagger_run_002_root_cause


_REQUEST_SCHEMA = "stagger_repair_planning_authority_request_v1"
_ROOT_CAUSE_SCHEMA = "stagger_root_cause_evidence_v1"
_HYPOTHESIS_SET_SCHEMA = "stagger_repair_hypothesis_set_v1"
_ALLOWED_ACTIONS = [
    "materialize_root_cause_evidence",
    "materialize_repair_hypothesis_set",
    "invoke_repair_planner_for_semantic_decision",
    "materialize_repair_plan",
]
_FORBIDDEN_ACTIONS = [
    "modify_source",
    "build",
    "launch_process",
    "write_game_directory",
    "claim_product_acceptance",
    "claim_audio_audibility",
]


class StaggerPlannerAdmissionError(ValueError):
    """Raised when exact planning identity or authority does not match."""


def preproject_stagger_planning_authority(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    binding_resolution_hash: str,
    run_dir: str | Path,
    planning_run_id: str,
    hierarchy_run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return one deterministic no-write RepairPlanner authority request."""

    if not planning_run_id:
        raise StaggerPlannerAdmissionError(
            "planning_run_id must be non-empty."
        )
    preprojection = preflight_stagger_run_002_root_cause(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        binding_resolution_hash=binding_resolution_hash,
        run_dir=run_dir,
    )
    if hierarchy_run_dir is not None:
        preprojection = merge_stagger_hierarchy_observation(
            base_preprojection=preprojection,
            hierarchy_run_dir=hierarchy_run_dir,
        )
    if preprojection["semantic_assessment"]["status"] not in {
        "ready_for_non_authoritative_direct_mechanism_only",
        "ready_for_non_authoritative_repair_selection",
    }:
        raise StaggerPlannerAdmissionError(
            "The direct mechanism assessment is not ready."
        )
    binding_freshness = preprojection["freshness"][
        "binding_resolution"
    ]
    if (
        binding_freshness["exact_revision_status"] != "fresh"
        or binding_freshness["latest_match"] is not True
        or preprojection["materialization_admission"]["blockers"]
        != ["planning_authority_not_materialized"]
    ):
        raise StaggerPlannerAdmissionError(
            "The exact current Binding or planning admission boundary drifted."
        )
    root_core = _root_cause_evidence_core(
        preprojection,
        planning_run_id=planning_run_id,
    )
    hypothesis_core = _repair_hypothesis_set_core(
        preprojection,
        planning_run_id=planning_run_id,
    )
    request_payload = {
        "schema_version": _REQUEST_SCHEMA,
        "feature_id": feature_id,
        "planning_run_id": planning_run_id,
        "preprojection_hash": preprojection["projection_hash"],
        "formal_lineage": copy.deepcopy(
            preprojection["formal_lineage"]
        ),
        "root_cause_evidence_core": root_core,
        "repair_hypothesis_set_core": hypothesis_core,
        "requested_actions": list(_ALLOWED_ACTIONS),
        "forbidden_actions": list(_FORBIDDEN_ACTIONS),
        "authority_boundary": {
            "artifact_materialization_allowed_before_approval": False,
            "repair_planner_allowed_before_approval": False,
            "source_patch_allowed": False,
            "build_allowed": False,
            "runtime_allowed": False,
        },
    }
    request_hash = _stable_hash(request_payload)
    request_artifact_payload = {
        "node_name": "request_stagger_repair_planning_authority",
        "stage": "repair_planning_authority_request",
        "message": (
            "Exact Stagger RepairPlanner materialization request awaits "
            "LangGraph human approval."
        ),
        "status": "pending_human_approval",
        "feature_id": feature_id,
        "run_id": planning_run_id,
        "request_hash": request_hash,
        "request_payload": request_payload,
        "authority_granted": False,
        "artifact_materialization_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
        "build_allowed": False,
        "runtime_allowed": False,
    }
    return {
        "status": "READY_TO_CREATE_REPAIR_PLANNING_AUTHORITY_REQUEST",
        "command": "preproject-stagger-repair-planning-authority",
        "preprojection": preprojection,
        "request_hash": request_hash,
        "request_payload": request_payload,
        "request_artifact_payload": request_artifact_payload,
        "authority_granted": False,
        "artifact_materialization_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
        "build_allowed": False,
        "runtime_allowed": False,
        "writes_performed": False,
        "artifact_writes_performed": False,
        "repair_planner_invoked": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }


def create_stagger_planning_authority_request(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    binding_resolution_hash: str,
    run_dir: str | Path,
    planning_run_id: str,
    expected_request_hash: str,
    hierarchy_run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist the exact human-confirmed no-authority request."""

    projection = preproject_stagger_planning_authority(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        binding_resolution_hash=binding_resolution_hash,
        run_dir=run_dir,
        planning_run_id=planning_run_id,
        hierarchy_run_dir=hierarchy_run_dir,
    )
    if projection["request_hash"] != expected_request_hash:
        raise StaggerPlannerAdmissionError(
            "The approved Request hash does not match the live projection."
        )
    store = ArtifactStore(artifact_store_root)
    binding_ref = _revision_ref(
        feature_id,
        "binding_resolution",
        projection["request_payload"]["formal_lineage"][
            "binding_resolution"
        ],
    )
    request_ref = store.write(
        feature_id=feature_id,
        artifact_type="repair_planning_request",
        payload=projection["request_artifact_payload"],
        status="success",
        upstream_refs=[binding_ref],
        exact_revision_upstream_types={"binding_resolution"},
    )
    return {
        "status": "REPAIR_PLANNING_AUTHORITY_REQUEST_CREATED",
        "request_hash": expected_request_hash,
        "repair_planning_authority_request_revision": _revision(
            request_ref
        ),
        "authority_granted": False,
        "artifact_materialization_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
        "build_allowed": False,
        "runtime_allowed": False,
        "writes_performed": True,
        "written_artifact_types": [
            "repair_planning_request",
        ],
    }


def materialize_stagger_planning_approval(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    repair_planning_authority_request_path: str | Path,
    repair_planning_authority_request_hash: str,
    resume_report_path: str | Path,
    resume_report_hash: str,
) -> dict[str, Any]:
    """Materialize approved planning inputs, invoke Planner, and persist its plan."""

    store = ArtifactStore(artifact_store_root)
    request_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="repair_planning_request",
        path=str(Path(repair_planning_authority_request_path).resolve()),
        artifact_hash=repair_planning_authority_request_hash,
    )
    resume_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="resume_report",
        path=str(Path(resume_report_path).resolve()),
        artifact_hash=resume_report_hash,
    )
    request = store.read_for_stage(
        request_ref,
        consumer_stage="repair_planning_approval",
    )["data"]
    resume = store.read_for_stage(
        resume_ref,
        consumer_stage="repair_planning_approval",
    )["data"]
    _validate_approval_inputs(
        store=store,
        request_ref=request_ref,
        request=request,
        resume=resume,
    )
    request_payload = request["request_payload"]
    planning_run_id = str(request["run_id"])
    lineage_refs = _validate_live_request_inputs(
        store=store,
        feature_id=feature_id,
        request_payload=request_payload,
    )
    approval_payload = {
        "node_name": "approve_stagger_repair_planning_authority",
        "stage": "repair_planning_approval",
        "message": (
            "Human approval authorizes only the exact Stagger planning "
            "materialization and semantic RepairPlanner call."
        ),
        "status": "approved",
        "feature_id": feature_id,
        "run_id": planning_run_id,
        "request_hash": request["request_hash"],
        "approval_hash": request["request_hash"],
        "approved_by": resume["approved_by"],
        "approved_at": resume["approved_at"],
        "repair_planning_authority_request_revision": _revision(
            request_ref
        ),
        "resume_report_revision": _revision(resume_ref),
        "allowed_actions": list(_ALLOWED_ACTIONS),
        "forbidden_actions": list(_FORBIDDEN_ACTIONS),
        "artifact_materialization_allowed": True,
        "repair_planner_allowed": True,
        "source_patch_allowed": False,
        "build_allowed": False,
        "runtime_allowed": False,
    }
    binding_ref = lineage_refs["binding_resolution"]
    binding = store.read(binding_ref)["data"]
    projected_approval_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="repair_planning_approval",
        path=str(
            store.root
            / ".preflight"
            / "repair_planning_approval.json"
        ),
        artifact_hash="0" * 64,
    )
    projected_root_payload = {
        **copy.deepcopy(request_payload["root_cause_evidence_core"]),
        "repair_planning_authority_request_revision": _revision(
            request_ref
        ),
        "repair_planning_authority_approval_revision": _revision(
            projected_approval_ref
        ),
        "binding_resolution_revision": _revision(binding_ref),
    }
    projected_root_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="root_cause_evidence",
        path=str(
            store.root / ".preflight" / "root_cause_evidence.json"
        ),
        artifact_hash="1" * 64,
    )
    projected_hypothesis_payload = {
        **copy.deepcopy(
            request_payload["repair_hypothesis_set_core"]
        ),
        "repair_planning_authority_approval_revision": _revision(
            projected_approval_ref
        ),
        "root_cause_evidence_revision": _revision(
            projected_root_ref
        ),
        "binding_resolution_revision": _revision(binding_ref),
    }
    projected_hypothesis_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="repair_hypothesis_set",
        path=str(
            store.root / ".preflight" / "repair_hypothesis_set.json"
        ),
        artifact_hash="2" * 64,
    )
    projected_plan = RepairPlanner().from_stagger_semantic_failure(
        root_cause_evidence=projected_root_payload,
        root_cause_evidence_ref=projected_root_ref.path,
        repair_hypothesis_set=projected_hypothesis_payload,
        repair_hypothesis_set_ref=projected_hypothesis_ref.path,
        binding_resolution=binding,
        binding_resolution_ref=binding_ref.path,
        retry_count=0,
        target_behavior=projected_root_payload[
            "failed_feature_spec_criterion"
        ],
    )
    store.registry.validate_write(
        artifact_type="repair_planning_approval",
        status="success",
        payload=approval_payload,
    )
    store.registry.validate_write(
        artifact_type="root_cause_evidence",
        status="success",
        payload=projected_root_payload,
    )
    store.registry.validate_write(
        artifact_type="repair_hypothesis_set",
        status="success",
        payload=projected_hypothesis_payload,
    )
    store.registry.validate_write(
        artifact_type="repair_plan",
        status=(
            "blocked"
            if projected_plan.blockers
            else "success"
        ),
        payload=projected_plan.to_artifact_payload(),
    )
    approval_ref = store.write(
        feature_id=feature_id,
        artifact_type="repair_planning_approval",
        payload=approval_payload,
        status="success",
        upstream_refs=[request_ref, resume_ref],
        exact_revision_upstream_types={
            "repair_planning_request",
            "resume_report",
        },
    )
    root_payload = {
        **copy.deepcopy(request_payload["root_cause_evidence_core"]),
        "repair_planning_authority_request_revision": _revision(
            request_ref
        ),
        "repair_planning_authority_approval_revision": _revision(
            approval_ref
        ),
        "binding_resolution_revision": _revision(binding_ref),
    }
    root_ref = store.write(
        feature_id=feature_id,
        artifact_type="root_cause_evidence",
        payload=root_payload,
        status="success",
        upstream_refs=[
            request_ref,
            approval_ref,
            binding_ref,
        ],
        exact_revision_upstream_types={
            "repair_planning_request",
            "repair_planning_approval",
            "binding_resolution",
        },
    )
    hypothesis_payload = {
        **copy.deepcopy(
            request_payload["repair_hypothesis_set_core"]
        ),
        "repair_planning_authority_approval_revision": _revision(
            approval_ref
        ),
        "root_cause_evidence_revision": _revision(root_ref),
        "binding_resolution_revision": _revision(binding_ref),
    }
    hypothesis_ref = store.write(
        feature_id=feature_id,
        artifact_type="repair_hypothesis_set",
        payload=hypothesis_payload,
        status="success",
        upstream_refs=[
            approval_ref,
            root_ref,
            binding_ref,
        ],
        exact_revision_upstream_types={
            "repair_planning_approval",
            "root_cause_evidence",
            "binding_resolution",
        },
    )
    planner = RepairPlanner()
    plan = planner.from_stagger_semantic_failure(
        root_cause_evidence=root_payload,
        root_cause_evidence_ref=root_ref.path,
        repair_hypothesis_set=hypothesis_payload,
        repair_hypothesis_set_ref=hypothesis_ref.path,
        binding_resolution=binding,
        binding_resolution_ref=binding_ref.path,
        retry_count=0,
        target_behavior=(
            root_payload["failed_feature_spec_criterion"]
        ),
    )
    patch_ref = lineage_refs["patch_proposal"]
    runtime_ref = lineage_refs["runtime_evidence"]
    plan_payload = plan.to_artifact_payload()
    if (
        plan.semantic_decision
        != projected_plan.semantic_decision
    ):
        raise StaggerPlannerAdmissionError(
            "RepairPlanner semantic decision drifted after materialization."
        )
    plan_ref = store.write(
        feature_id=feature_id,
        artifact_type="repair_plan",
        payload=plan_payload,
        status="blocked" if plan.blockers else "success",
        upstream_refs=[
            root_ref,
            hypothesis_ref,
            binding_ref,
            patch_ref,
            runtime_ref,
            approval_ref,
        ],
        exact_revision_upstream_types={
            "root_cause_evidence",
            "repair_hypothesis_set",
            "binding_resolution",
            "patch_proposal",
            "runtime_evidence",
            "repair_planning_approval",
        },
    )
    return {
        "status": (
            "REPAIR_PLAN_BLOCKED"
            if plan.blockers
            else "REPAIR_PLAN_CREATED"
        ),
        "semantic_decision": plan_payload["semantic_decision"],
        "repair_planning_authority_approval_revision": _revision(
            approval_ref
        ),
        "root_cause_evidence_revision": _revision(root_ref),
        "repair_hypothesis_set_revision": _revision(hypothesis_ref),
        "repair_plan_revision": _revision(plan_ref),
        "source_patch_allowed": False,
        "build_allowed": False,
        "runtime_allowed": False,
        "repair_planner_invoked": True,
        "writes_performed": True,
        "written_artifact_types": [
            "repair_planning_approval",
            "root_cause_evidence",
            "repair_hypothesis_set",
            "repair_plan",
        ],
    }


def _root_cause_evidence_core(
    preprojection: dict[str, Any],
    *,
    planning_run_id: str,
) -> dict[str, Any]:
    semantic = preprojection["semantic_assessment"]
    root_projection = preprojection["root_cause_evidence_projection"]
    return {
        "node_name": "create_stagger_root_cause_evidence",
        "stage": "root_cause_evidence",
        "message": (
            "The run-local Stagger direct failure mechanism is preserved "
            "with explicit provenance limitations."
        ),
        "schema_version": _ROOT_CAUSE_SCHEMA,
        "feature_id": preprojection["feature_id"],
        "planning_run_id": planning_run_id,
        "failed_feature_spec_criterion": preprojection["acceptance"][
            "failed_feature_spec_criterion"
        ],
        "failure_owner": semantic["failure_owner"],
        "direct_failure_mechanism": semantic[
            "direct_failure_mechanism"
        ],
        "confirmed_mechanism": copy.deepcopy(
            semantic["confirmed_mechanism"]
        ),
        "excluded_for_observed_event": list(
            semantic["excluded_for_observed_event"]
        ),
        "unresolved": list(semantic["unresolved"]),
        "repair_selection": {
            "authoritative": False,
            "selected_rect_transform_acquisition_path": semantic.get(
                "selected_rect_transform_acquisition_path"
            ),
            "binding_scope_assessment": semantic.get(
                "binding_scope_assessment"
            ),
        },
        "product_acceptance": "not_evaluated",
        "audio_audibility": "not_evaluated",
        "yellow_x_repaired": False,
        "formal_runtime_evidence": False,
        "evidence_items": copy.deepcopy(
            root_projection["evidence_items"]
        ),
        "evidence_gaps": copy.deepcopy(
            root_projection["evidence_gaps"]
        ),
        "immutable_limitations": list(
            root_projection["immutable_limitations"]
        ),
        "formal_lineage": copy.deepcopy(
            preprojection["formal_lineage"]
        ),
        "product_identity": copy.deepcopy(
            preprojection["product_identity"]
        ),
        "diagnostic_identity": copy.deepcopy(
            preprojection["diagnostic_identity"]
        ),
        "hierarchy_observation_identity": copy.deepcopy(
            preprojection.get("hierarchy_observation_identity")
        ),
        "runtime_result_identity": copy.deepcopy(
            preprojection["runtime_result_identity"]
        ),
        "binding_identity": copy.deepcopy(
            preprojection["binding_identity"]
        ),
        "preprojection_hash": preprojection["projection_hash"],
        "source_patch_allowed": False,
    }


def _repair_hypothesis_set_core(
    preprojection: dict[str, Any],
    *,
    planning_run_id: str,
) -> dict[str, Any]:
    selection_status = preprojection[
        "repair_hypothesis_set_projection"
    ].get("selection_status", "unresolved")
    return {
        "node_name": "create_stagger_repair_hypothesis_set",
        "stage": "repair_hypothesis_set",
        "message": (
            "Bounded Stagger hierarchy evidence supports exactly one "
            "RectTransform repair hypothesis."
            if selection_status == "selected"
            else (
                "Stagger RectTransform repair hypotheses remain unselected "
                "until bounded evidence supports exactly one."
            )
        ),
        "schema_version": _HYPOTHESIS_SET_SCHEMA,
        "feature_id": preprojection["feature_id"],
        "planning_run_id": planning_run_id,
        "selection_status": selection_status,
        "hypotheses": copy.deepcopy(
            preprojection["repair_hypothesis_set_projection"][
                "hypotheses"
            ]
        ),
        "preprojection_hash": preprojection["projection_hash"],
        "source_patch_allowed": False,
    }


def _validate_approval_inputs(
    *,
    store: ArtifactStore,
    request_ref: ArtifactRef,
    request: dict[str, Any],
    resume: dict[str, Any],
) -> None:
    freshness = store.check_direct_freshness(request_ref)
    if not freshness.is_fresh:
        raise StaggerPlannerAdmissionError(
            "The Repair planning Request is not the current revision."
        )
    if (
        request.get("status") != "pending_human_approval"
        or request.get("authority_granted") is not False
        or request.get("artifact_materialization_allowed") is not False
        or request.get("repair_planner_allowed") is not False
        or request.get("source_patch_allowed") is not False
        or request.get("build_allowed") is not False
        or request.get("runtime_allowed") is not False
        or request.get("request_payload", {}).get("schema_version")
        != _REQUEST_SCHEMA
    ):
        raise StaggerPlannerAdmissionError(
            "The stored Repair planning Request boundary is invalid."
        )
    if (
        resume.get("resume_stage") != "repair_planning_approval"
        or resume.get("decision") != "approve"
        or resume.get("allowed") is not True
        or resume.get("authority_request_hash")
        != request.get("request_hash")
        or not isinstance(resume.get("approved_by"), str)
        or not resume["approved_by"]
        or not isinstance(resume.get("approved_at"), str)
        or not resume["approved_at"]
    ):
        raise StaggerPlannerAdmissionError(
            "ResumeReport does not contain exact human planning approval."
        )


def _validate_live_request_inputs(
    *,
    store: ArtifactStore,
    feature_id: str,
    request_payload: dict[str, Any],
) -> dict[str, ArtifactRef]:
    formal_lineage = request_payload.get("formal_lineage")
    if not isinstance(formal_lineage, dict):
        raise StaggerPlannerAdmissionError(
            "Repair planning Request formal lineage is missing."
        )
    expected_types = {
        "feature_spec",
        "build_result",
        "implementation_plan",
        "patch_proposal",
        "binding_resolution",
        "runtime_evidence",
    }
    if set(formal_lineage) != expected_types:
        raise StaggerPlannerAdmissionError(
            "Repair planning Request formal lineage roles drifted."
        )
    refs = {
        artifact_type: _revision_ref(
            feature_id,
            artifact_type,
            formal_lineage[artifact_type],
        )
        for artifact_type in sorted(expected_types)
    }
    for ref in refs.values():
        store.read(ref)
        freshness = store.check_exact_revision_freshness(ref)
        if not freshness.is_fresh:
            raise StaggerPlannerAdmissionError(
                f"{ref.artifact_type} exact revision drifted."
            )
    binding_ref = refs["binding_resolution"]
    _validate_current_binding_revision(
        store=store,
        feature_id=feature_id,
        binding_ref=binding_ref,
    )
    root = request_payload.get("root_cause_evidence_core")
    if not isinstance(root, dict):
        raise StaggerPlannerAdmissionError(
            "RootCauseEvidence core is missing."
        )
    file_bindings = [
        *(
            (str(item.get("path")), str(item.get("sha256")))
            for item in root.get("evidence_items", ())
            if isinstance(item, dict)
        ),
        *(
            (
                str(identity.get(path_field)),
                str(identity.get(hash_field)),
            )
            for identity, path_field, hash_field in (
                (
                    root.get("product_identity", {}),
                    "source_path",
                    "source_sha256",
                ),
                (
                    root.get("product_identity", {}),
                    "build_dll_path",
                    "build_dll_sha256",
                ),
                (
                    root.get("diagnostic_identity", {}),
                    "source_path",
                    "source_sha256",
                ),
                (
                    root.get("diagnostic_identity", {}),
                    "build_dll_path",
                    "build_dll_sha256",
                ),
                (
                    root.get("diagnostic_identity", {}),
                    "config_path",
                    "config_sha256",
                ),
                (
                    root.get("runtime_result_identity", {}),
                    "path",
                    "sha256",
                ),
            )
        ),
    ]
    for raw_path, expected_hash in file_bindings:
        path = Path(raw_path)
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest().upper()
            != expected_hash.upper()
        ):
            raise StaggerPlannerAdmissionError(
                f"Bound planning input drifted: {raw_path}"
            )
    return refs


def _validate_current_binding_revision(
    *,
    store: ArtifactStore,
    feature_id: str,
    binding_ref: ArtifactRef,
) -> None:
    current = {
        ref.artifact_type: ref
        for ref in store.list_feature_artifacts(feature_id)
    }.get("binding_resolution")
    if (
        current is None
        or current.artifact_hash != binding_ref.artifact_hash
    ):
        raise StaggerPlannerAdmissionError(
            "BindingResolution is no longer the current revision."
        )


def _revision_ref(
    feature_id: str,
    artifact_type: str,
    revision: dict[str, Any],
) -> ArtifactRef:
    if (
        revision.get("artifact_type") != artifact_type
        or revision.get("path") is None
        or revision.get("artifact_hash") is None
    ):
        raise StaggerPlannerAdmissionError(
            f"{artifact_type} revision identity is invalid."
        )
    return ArtifactRef(
        feature_id=feature_id,
        artifact_type=artifact_type,
        path=str(revision["path"]),
        artifact_hash=str(revision["artifact_hash"]),
    )


def _revision(ref: ArtifactRef) -> dict[str, str]:
    return {
        "feature_id": ref.feature_id,
        "artifact_type": ref.artifact_type,
        "path": ref.path,
        "artifact_hash": ref.artifact_hash,
    }


def _stable_hash(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
