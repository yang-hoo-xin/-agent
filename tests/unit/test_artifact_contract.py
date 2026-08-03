"""Tests for Phase B artifact contracts and freshness checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.mod_agent.artifacts import (
    ArtifactRegistryError,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactTypeRegistry,
    StaleArtifactError,
)
from src.mod_agent.edit_authority_capabilities import (
    APPROVAL_IDENTITY_SCHEMA_VERSION,
    VERSIONED_APPROVAL_IDENTITY_MODE,
    attach_edit_authority_approval_identity,
)


def _payload(node_name: str, stage: str) -> dict[str, str]:
    return {
        "node_name": node_name,
        "stage": stage,
        "message": "stub",
    }


def _feature_payload() -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "stub",
        "feature_id": "feature_001",
        "user_request": "Load",
        "target_behavior": "Load",
        "non_goals": [],
        "target_mod": None,
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _changed_feature_payload() -> dict[str, object]:
    payload = _feature_payload()
    payload["message"] = "changed"
    payload["target_behavior"] = "changed"
    return payload


def _implementation_payload() -> dict[str, object]:
    return {
        "node_name": "create_implementation_plan",
        "stage": "implementation_plan",
        "message": "stub",
        "feature_id": "feature_001",
        "evidence_source_paths": ["Plugin.cs"],
        "target_files": ["Plugin.cs"],
        "target_symbols": ["Load"],
        "evidence_refs": ["ev_001"],
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "evidence_id": "ev_001",
                    "canonical_target_path": "Plugin.cs",
                    "source_type": "target_source",
                    "target_symbol": "Load",
                    "target_span": {"start_line": 1, "end_line": 10},
                }
            ],
            "supporting_bindings": [],
        },
        "proposed_changes": [
            {
                "change_id": "chg_001",
                "edit_binding_id": "edit_binding_001",
                "supporting_binding_ids": [],
            }
        ],
        "side_effect_boundaries": [],
        "test_plan": [],
        "rollback_plan": [],
        "open_questions": [],
        "blocking": False,
        "blockers": [],
    }


def _patch_payload() -> dict[str, object]:
    return {
        "node_name": "generate_patch_proposal",
        "stage": "patch_proposal",
        "message": "stub",
        "proposal_id": "proposal_001",
        "feature_id": "feature_001",
        "summary": "stub",
        "files": [],
        "diff_intent": [],
        "change_units": [],
        "context_pack": {
            "feature_id": "feature_001",
            "files": [],
            "evidence_refs": [],
            "evidence_source_paths": [],
            "scope_boundary": [],
            "change_unit_ids": [],
        },
        "evidence_refs": [],
        "scope_boundary": [],
        "risk_assessment": {"risk_level": "blocked"},
        "expected_tests": [],
        "no_op_status": {"is_no_op": True, "reason": "stub"},
        "rollback_hints": [],
        "manual_review_notes": [],
        "blocked": True,
        "blockers": [],
    }


def _generic_edit_authority_request_payload() -> dict[str, object]:
    def revision(fill: str) -> dict[str, str]:
        return {
            "feature_id": "feature_001",
            "path": f"{fill}.json",
            "artifact_hash": fill * 64,
        }

    return {
        "schema_version": "stagger_edit_authority_request_v1",
        "proposal": {
            "feature_spec_revision": revision("1"),
            "runtime_evidence_revision": revision("2"),
            "implementation_plan_revision": revision("3"),
            "patch_proposal_revision": revision("4"),
            "ownership_review": {
                "stored_runtime_failure_ownership": {"owner": "observation"},
                "replayed_runtime_failure_ownership": {
                    "owner": "product_behavior"
                },
                "reclassification_approval_required": True,
                "runtime_evidence_mutation_allowed": False,
            },
            "diagnosed_responsibility_anchor": "runtime_result",
            "current_source": {
                "canonical_target_path": "Patches/HitFeedbackBehaviorPatch.cs",
                "sha256": "5" * 64,
                "target_span": {"start_line": 979, "end_line": 984},
            },
            "proposed_target_symbol": "TrySpawnStaggerYellowX",
            "proposed_exact_span": {"start_line": 979, "end_line": 984},
            "proposed_operation": "replace_hud_recttransform_acquisition",
            "existing_binding_gap": "none",
            "current_edit_authority": "edit_binding_004",
            "approval_scope": ["create_exact_binding"],
            "root_cause_status": "confirmed",
            "unresolved_root_causes": [],
        },
        "source_root": "C:/source",
        "projected_ids": {
            "binding_id": "edit_binding_004",
            "change_id": "chg_004",
            "evidence_id": "stagger_repair_001",
        },
    }


def _edit_authority_approval_payload() -> dict[str, object]:
    proposal = {
        "schema_version": "stagger_edit_authority_proposal_v1",
        "feature_id": "feature_001",
    }
    approval_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            proposal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "node_name": "approve_stagger_edit_authority",
        "stage": "edit_authority_approval",
        "message": "Exact authority approved.",
        "status": "approved",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "approval_hash": approval_hash,
        "approved_by": "user",
        "approval_scope": [
            "runtime_failure_ownership_reclassification",
            "new_exact_edit_binding",
        ],
        "approved_proposal": proposal,
        "stored_runtime_failure_ownership": {
            "owner": "observation",
            "source_repair_allowed": False,
        },
        "approved_runtime_failure_ownership": {
            "owner": "product_behavior",
            "source_repair_allowed": True,
        },
        "allowed_edit_binding_ids": ["edit_binding_004"],
        "allowed_evidence_ids": ["stagger_repair_001"],
        "runtime_evidence_mutation_allowed": False,
        "old_patch_proposal_mutation_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }


def test_legacy_edit_authority_approval_envelope_binds_exact_proposal_hash() -> None:
    registry = ArtifactTypeRegistry()
    payload = _edit_authority_approval_payload()
    contract = registry.get("edit_authority_approval")

    def envelope(data: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": contract.schema_version,
            "artifact_type": "edit_authority_approval",
            "feature_id": "feature_001",
            "producer_stage": contract.producer_stage,
            "status": "success",
            "data": data,
        }

    validated = registry.validate_envelope(envelope(payload))

    assert validated.producer_stage == "edit_authority_approval"
    assert "binding_resolution" in validated.consumer_stages

    payload["approval_hash"] = "sha256:" + ("0" * 64)
    with pytest.raises(
        ArtifactRegistryError,
        match="proposal hash mismatch",
    ):
        registry.validate_envelope(envelope(payload))


def test_edit_authority_request_has_no_authority_and_requires_exact_inputs() -> None:
    registry = ArtifactTypeRegistry()
    request_payload, request_hash = attach_edit_authority_approval_identity(
        request_payload=_generic_edit_authority_request_payload(),
        feature_id="feature_001",
        run_id="run_001",
    )
    payload = {
        "node_name": "request_stagger_edit_authority",
        "stage": "edit_authority_request",
        "message": "Awaiting graph approval.",
        "status": "pending_human_approval",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "request_hash": request_hash,
        "request_payload": request_payload,
        "authority_granted": False,
        "registry_mutation_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }

    contract = registry.validate_write(
        artifact_type="edit_authority_request",
        status="success",
        payload=payload,
    )

    assert contract.required_upstream_artifacts == frozenset(
        {
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        }
    )
    assert contract.required_exact_revision_upstream_artifacts == (
        contract.required_upstream_artifacts
    )
    payload["authority_granted"] = True
    with pytest.raises(
        ArtifactRegistryError,
        match="cannot grant execution authority",
    ):
        registry.validate_write(
            artifact_type="edit_authority_request",
            status="success",
            payload=payload,
        )


def test_request_bound_approval_is_permission_only() -> None:
    registry = ArtifactTypeRegistry()
    revision = {
        "feature_id": "feature_001",
        "path": "artifact.json",
        "artifact_hash": "a" * 64,
    }
    payload = {
        "node_name": "approve_stagger_edit_authority",
        "stage": "edit_authority_approval",
        "message": "Exact request approved.",
        "status": "approved",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "authority_source": "edit_authority_request",
        "authority_contract_version": "edit_authority_request_approval_v1",
        "approval_identity_mode": VERSIONED_APPROVAL_IDENTITY_MODE,
        "approval_identity_schema_version": APPROVAL_IDENTITY_SCHEMA_VERSION,
        "capability_id": "stagger_edit_authority_generic",
        "capability_contract_version": "stagger_edit_authority_capability_v1",
        "approval_hash": "sha256:" + ("b" * 64),
        "request_hash": "sha256:" + ("b" * 64),
        "approved_by": "user",
        "approved_at": "2026-07-30T12:00:00+08:00",
        "resume_id": "resume_001",
        "decision": "approve",
        "edit_authority_request_revision": dict(revision),
        "resume_report_revision": dict(revision),
        "allowed_actions": [
            "create_evidence_pack_revision",
            "create_implementation_plan_revision",
            "resolve_exact_edit_binding",
        ],
        "forbidden_actions": [
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ],
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }

    contract = registry.validate_write(
        artifact_type="edit_authority_approval",
        status="success",
        payload=payload,
    )

    assert contract.required_upstream_artifacts == frozenset(
        {"edit_authority_request", "resume_report"}
    )
    assert contract.required_exact_revision_upstream_artifacts == (
        contract.required_upstream_artifacts
    )
    payload["approved_proposal"] = {"must_not_be_here": True}
    with pytest.raises(
        ArtifactRegistryError,
        match="non-authority fields",
    ):
        registry.validate_write(
            artifact_type="edit_authority_approval",
            status="success",
            payload=payload,
        )


def test_existing_binding_reauthorization_contract_adds_no_technical_write() -> None:
    registry = ArtifactTypeRegistry()
    revision = {
        "feature_id": "feature_001",
        "path": "artifact.json",
        "artifact_hash": "a" * 64,
    }
    approval = {
        "node_name": "approve_stagger_edit_authority",
        "stage": "edit_authority_approval",
        "message": "Existing binding reauthorized.",
        "status": "approved",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "authority_source": "edit_authority_request",
        "authority_contract_version": (
            "edit_authority_existing_binding_reauthorization_v1"
        ),
        "approval_identity_mode": VERSIONED_APPROVAL_IDENTITY_MODE,
        "approval_identity_schema_version": APPROVAL_IDENTITY_SCHEMA_VERSION,
        "capability_id": "stagger_existing_binding_reauthorization",
        "capability_contract_version": "stagger_edit_authority_capability_v1",
        "approval_hash": "sha256:" + ("b" * 64),
        "request_hash": "sha256:" + ("b" * 64),
        "approved_by": "user",
        "approved_at": "2026-07-30T12:00:00+08:00",
        "resume_id": "resume_001",
        "decision": "approve",
        "edit_authority_request_revision": dict(revision),
        "resume_report_revision": dict(revision),
        "allowed_actions": [
            "reauthorize_existing_edit_binding",
            "create_binding_resolution_revision",
        ],
        "forbidden_actions": [
            "create_evidence_pack_revision",
            "create_implementation_plan_revision",
            "create_edit_binding",
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ],
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }
    registry.validate_write(
        artifact_type="edit_authority_approval",
        status="success",
        payload=approval,
    )

    plan_revision = dict(revision)
    resolution = {
        "node_name": "resolve_runtime_diagnosis_binding",
        "stage": "binding_resolution",
        "message": "Existing binding remains uniquely resolved.",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "result_type": "resolved_repair_target",
        "runtime_evidence_revision": dict(revision),
        "implementation_plan_revision": plan_revision,
        "patch_proposal_revision": dict(revision),
        "allowed_edit_binding_ids": ["edit_binding_004"],
        "resolved_repair_target": {
            "status": "resolved",
            "feature_id": "feature_001",
            "run_id": "run_001",
            "binding_id": "edit_binding_004",
            "implementation_plan_revision": plan_revision,
        },
        "binding_gap": None,
        "binding_proposal_request": None,
        "blockers": [],
        "authority_source": "edit_authority_approval",
        "authority_contract_version": (
            "edit_authority_existing_binding_reauthorization_v1"
        ),
        "edit_authority_request_revision": dict(revision),
        "edit_authority_approval_revision": dict(revision),
        "evidence_pack_revision": dict(revision),
        "previous_binding_resolution_revision": dict(revision),
        "predecessor_implementation_plan_revision": dict(revision),
        "approved_runtime_failure_ownership": {
            "owner": "product_behavior",
            "source_repair_allowed": True,
        },
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }
    registry.validate_write(
        artifact_type="binding_resolution",
        status="success",
        payload=resolution,
    )

    del resolution["previous_binding_resolution_revision"]
    with pytest.raises(
        ArtifactRegistryError,
        match="previous_binding_resolution_revision",
    ):
        registry.validate_write(
            artifact_type="binding_resolution",
            status="success",
            payload=resolution,
        )


def test_stagger_observation_plan_approval_is_permission_only() -> None:
    registry = ArtifactTypeRegistry()
    revision = {
        "feature_id": "feature_001",
        "path": "artifact.json",
        "artifact_hash": "a" * 64,
    }
    approval = {
        "node_name": "approve_stagger_edit_authority",
        "stage": "edit_authority_approval",
        "message": "Observation-only Plan projection approved.",
        "status": "approved",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "authority_source": "edit_authority_request",
        "authority_contract_version": (
            "edit_authority_stagger_hud_parent_observation_plan_v1"
        ),
        "approval_identity_mode": VERSIONED_APPROVAL_IDENTITY_MODE,
        "approval_identity_schema_version": APPROVAL_IDENTITY_SCHEMA_VERSION,
        "capability_id": "stagger_hud_parent_observation",
        "capability_contract_version": "stagger_edit_authority_capability_v1",
        "approval_hash": "sha256:" + ("b" * 64),
        "request_hash": "sha256:" + ("b" * 64),
        "approved_by": "user",
        "approved_at": "2026-07-30T16:30:00+08:00",
        "resume_id": "resume_001",
        "decision": "approve",
        "edit_authority_request_revision": dict(revision),
        "resume_report_revision": dict(revision),
        "allowed_actions": [
            "create_observation_evidence_pack_revision",
            "create_diagnostic_implementation_plan_revision",
            "create_observation_only_edit_bindings",
        ],
        "forbidden_actions": [
            "create_binding_resolution_revision",
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ],
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }

    registry.validate_write(
        artifact_type="edit_authority_approval",
        status="success",
        payload=approval,
    )

    approval["allowed_actions"].append("modify_source")
    with pytest.raises(
        ArtifactRegistryError,
        match="capability contract",
    ):
        registry.validate_write(
            artifact_type="edit_authority_approval",
            status="success",
            payload=approval,
        )


def _review_payload() -> dict[str, object]:
    return {
        "node_name": "review_proposal",
        "stage": "proposal_review",
        "message": "stub",
        "decision": "revise_proposal",
        "findings": [],
        "required_changes": [],
        "allowed_next_stage": None,
        "checked_rules": [],
        "trace_metrics": {"num_changes_checked": 0, "num_blocking_findings": 0},
    }


def _dry_run_payload() -> dict[str, object]:
    return {
        "node_name": "dry_run_apply",
        "stage": "dry_run_apply",
        "message": "dry run",
    }


def _build_payload() -> dict[str, object]:
    return {
        "node_name": "build",
        "stage": "build",
        "message": "failed build",
        "feature_id": "feature_001",
        "execution_mode": "supplied",
        "status": "failed",
        "command": ["dotnet", "build"],
        "exit_code": 1,
        "stdout_path": None,
        "stderr_path": None,
        "errors": [],
        "warnings": [],
        "duration_ms": 0,
        "error_class": "compile_error",
        "diagnostics": [],
        "repair_handoff": {},
        "expected_artifacts": [],
        "verified_artifacts": [],
        "artifact_verification": {},
        "real_build_performed": False,
        "claims_real_build_success": False,
    }


def _repair_payload() -> dict[str, object]:
    return {
        "node_name": "create_repair_plan",
        "stage": "repair_plan",
        "message": "repair",
        "repair_id": "repair_001",
        "feature_id": "feature_001",
        "failure_source": "build",
        "failure_class": "compile_error",
        "failure_evidence": {"summary": "compiler error"},
        "evidence_refs": [],
        "root_cause_hypotheses": [],
        "hypothesis": "compiler error",
        "recommended_fix_strategy": "repair scoped proposal",
        "minimal_changes": [],
        "retry_count": 1,
        "retry_budget": 2,
        "retry_budget_remaining": 1,
        "retry_exhausted": False,
        "scope_expansion_allowed": False,
        "stop_condition": "stop after repair",
        "forbidden_regressions": [],
        "requires_new_evidence": False,
        "allowed_next_stage": "generate_patch_proposal",
        "blockers": [],
    }


def _evidence_payload() -> dict[str, object]:
    return {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "stub",
        "query": "Load",
        "readiness": "insufficient",
        "can_generate_patch": False,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": False,
        "identity_schema_version": "identity_v1",
        "identity_field_mapping": {
            "document_id": "Stable loaded document id",
            "file_hash": "SHA256 of the loaded source file",
            "source_hash": "Backward-compatible alias for file_hash",
            "doc_hash": "SHA256 of the document canonical_text",
            "chunk_id": "Stable chunk id",
            "source_ref": "Chunk-to-document reference",
            "content_hash": "Context-dependent stored content hash",
        },
        "items": [],
        "gaps": ["stub"],
        "excluded": [],
        "blockers": [],
        "retrieval_methods_used": [],
        "missing_evidence": [],
        "disabled_modes": {},
        "timing": {},
        "trace_refs": [],
    }


def test_every_workflow_artifact_type_is_registered() -> None:
    registry = ArtifactTypeRegistry()

    assert {
        "request_planning_report",
        "mod_planning_brief",
        "feature_spec",
        "evidence_pack",
        "evidence_post_run_validation",
        "implementation_plan",
        "patch_proposal",
        "proposal_review",
        "dry_run_result",
        "build_result",
        "runtime_evidence",
        "binding_resolution",
        "manual_evidence",
        "screenshot_registry",
        "repair_plan",
        "workflow_checkpoint",
        "resume_report",
        "eval_report",
        "workflow_trace",
        "job_status",
        "git_change_record",
        "knowledge_index_report",
    }.issubset(registry.artifact_types())


def test_binding_gap_contract_rejects_authority_grant() -> None:
    registry = ArtifactTypeRegistry()
    payload = {
        "node_name": "resolve_runtime_binding",
        "stage": "binding_resolution",
        "message": "A binding gap was found.",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "result_type": "binding_gap",
        "runtime_evidence_revision": {
            "feature_id": "feature_001",
            "path": "runtime_evidence.json",
            "artifact_hash": "runtime_hash",
        },
        "implementation_plan_revision": {
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        "patch_proposal_revision": {
            "feature_id": "feature_001",
            "path": "patch_proposal.json",
            "artifact_hash": "proposal_hash",
        },
        "allowed_edit_binding_ids": ["edit_binding_002"],
        "resolved_repair_target": None,
        "binding_gap": {
            "gap": True,
            "gap_reasons": ["missing_symbol_binding"],
        },
        "binding_proposal_request": {
            "status": "requested",
            "approval_required": True,
            "registry_mutation_allowed": False,
            "repair_allowed": False,
            "required_plan_lineage": {
                "feature_id": "feature_001",
                "path": "implementation_plan.json",
                "artifact_hash": "plan_hash",
            },
        },
        "blockers": [{"code": "BINDING_GAP"}],
    }

    registry.validate_write(
        artifact_type="binding_resolution",
        status="blocked",
        payload=payload,
    )
    with pytest.raises(
        ArtifactRegistryError,
        match="non-authorizing",
    ):
        registry.validate_write(
            artifact_type="binding_resolution",
            status="blocked",
            payload={
                **payload,
                "binding_proposal_request": {
                    **payload["binding_proposal_request"],
                    "repair_allowed": True,
                },
            },
        )
    with pytest.raises(
        ArtifactRegistryError,
        match="runtime_evidence_revision is not bound",
    ):
        registry.validate_write(
            artifact_type="binding_resolution",
            status="blocked",
            payload={
                **payload,
                "runtime_evidence_revision": {
                    **payload["runtime_evidence_revision"],
                    "feature_id": "other_feature",
                },
            },
        )


def test_evidence_post_run_validation_contract_is_non_routing_and_consistent() -> None:
    registry = ArtifactTypeRegistry()
    payload = {
        "node_name": "post_run_validation",
        "stage": "post_run_validation",
        "message": "lineage validation",
        "run_id": "run_001",
        "request_id": "request_001",
        "lineage_schema_version": "phase1_source_bound_no_write_v1",
        "lineage_checks": {"source_bound": True, "trace_persisted": True},
        "lineage_passed": True,
        "runtime_outcome": {"terminal_stage": "evidence_retrieval"},
        "domain_validation": None,
        "affects_runtime_route": False,
        "limitations": ["One no-write run only."],
    }

    contract = registry.validate_write(
        artifact_type="evidence_post_run_validation",
        status="success",
        payload=payload,
    )

    assert contract.required_upstream_artifacts == frozenset(
        {"evidence_pack", "workflow_trace"}
    )
    with pytest.raises(
        ArtifactRegistryError, match="affects_runtime_route must be false"
    ):
        registry.validate_write(
            artifact_type="evidence_post_run_validation",
            status="success",
            payload={**payload, "affects_runtime_route": True},
        )
    with pytest.raises(
        ArtifactRegistryError, match="must equal all lineage checks"
    ):
        registry.validate_write(
            artifact_type="evidence_post_run_validation",
            status="success",
            payload={**payload, "lineage_passed": False},
        )


def test_git_change_record_contract_supports_audit_and_replay() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("git_change_record")

    assert contract.producer_stage == "git_audit"
    assert {
        "base_revision",
        "commit_sha",
        "diff_hash",
        "commit_diff_hash",
        "working_tree",
        "proposal_binding",
        "dirty_tree_policy",
        "replay_command",
        "rollback_hint",
    }.issubset(contract.required_fields)
    assert "repair_plan" in contract.consumer_stages
    assert contract.dashboard_projection


def test_runtime_evidence_contract_requires_acceptance_fields() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("runtime_evidence")
    manual_contract = registry.get("manual_evidence")

    required = {
        "feature_id",
        "run_id",
        "build_artifact_ref",
        "build_artifact_hash",
        "execution_mode",
        "evidence_source",
        "plugin_marker_binding",
        "screenshot_refs",
        "runtime_trust_binding",
        "startup_loaded",
        "gameplay_behavior_verified",
        "evidence_items",
        "verification_status",
        "acceptance_status",
        "acceptance_verified",
        "acceptance_contract",
        "raw_supplied_output",
        "sources",
        "non_goals_checked",
        "non_goal_preservation",
        "limitations",
        "real_runtime_performed",
        "claims_real_runtime_success",
    }
    assert required.issubset(contract.required_fields)
    assert required.issubset(manual_contract.required_fields)


def test_eval_and_workflow_summary_contracts_separate_completion_from_success() -> None:
    registry = ArtifactTypeRegistry()

    eval_contract = registry.get("eval_report")
    summary_contract = registry.get("workflow_summary")
    shared_required = {
        "execution_mode",
        "workflow_completion_status",
        "requested_behavior_status",
        "v1_acceptance_status",
        "v1_acceptance_blockers",
    }
    eval_required = {
        *shared_required,
        "input_acceptance_status",
        "input_acceptance_verified",
        "acceptance_contract",
        "evaluation_gate",
    }

    assert eval_required.issubset(eval_contract.required_fields)
    assert shared_required.issubset(summary_contract.required_fields)
    assert "claims_real_success" in eval_contract.required_fields
    assert "claims_real_mod_success" in summary_contract.required_fields
    assert "workflow_completion_status" in eval_contract.dashboard_projection
    assert "requested_behavior_status" in summary_contract.dashboard_projection


def test_screenshot_registry_contract_keeps_visual_evidence_separate() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("screenshot_registry")

    assert contract.producer_stage == "runtime_evidence"
    assert {
        "feature_id",
        "screenshot_count",
        "captioned_count",
        "missing_caption_count",
        "screenshots",
        "verification_status",
        "acceptance_status",
        "claims_real_runtime_success",
        "limitations",
    }.issubset(contract.required_fields)
    assert {"evaluate", "repair_plan", "dashboard"}.issubset(contract.consumer_stages)


def test_build_result_contract_requires_structured_build_fields() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("build_result")

    assert {
        "feature_id",
        "execution_mode",
        "status",
        "command",
        "exit_code",
        "stdout_path",
        "stderr_path",
        "errors",
        "warnings",
        "duration_ms",
        "error_class",
        "diagnostics",
        "repair_handoff",
        "expected_artifacts",
        "verified_artifacts",
        "artifact_verification",
        "real_build_performed",
        "claims_real_build_success",
    }.issubset(contract.required_fields)
    assert contract.required_upstream_artifacts == frozenset()
    assert contract.required_one_of_upstream_artifact_groups == (
        frozenset({"dry_run_result", "feature_spec"}),
        frozenset({"dry_run_result", "evidence_pack"}),
    )
    assert "build" in registry.get("feature_spec").consumer_stages
    assert "build" in registry.get("evidence_pack").consumer_stages


def test_repair_plan_contract_requires_retry_and_evidence_fields() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("repair_plan")

    assert {
        "repair_id",
        "feature_id",
        "failure_source",
        "failure_class",
        "failure_evidence",
        "evidence_refs",
        "root_cause_hypotheses",
        "hypothesis",
        "recommended_fix_strategy",
        "minimal_changes",
        "retry_count",
        "retry_budget",
        "retry_budget_remaining",
        "retry_exhausted",
        "scope_expansion_allowed",
        "stop_condition",
        "forbidden_regressions",
        "requires_new_evidence",
        "allowed_next_stage",
        "blockers",
    }.issubset(contract.required_fields)
    assert "generate_patch_proposal" in contract.consumer_stages
    assert contract.required_exact_revision_upstream_artifacts == frozenset(
        {"patch_proposal"}
    )
    assert contract.required_one_of_upstream_artifact_groups == (
        frozenset(
            {
                "build_result",
                "runtime_evidence",
                "proposal_review",
                "root_cause_evidence",
            }
        ),
    )


def test_dashboard_projection_contract_is_present() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("patch_proposal")

    assert contract.dashboard_projection
    assert contract.eval_visibility is True


def test_evidence_pack_contract_requires_readiness_fields() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("evidence_pack")

    assert {
        "query",
        "readiness",
        "can_generate_patch",
            "authority",
            "authoritative_for_patch",
            "identity_schema_version",
            "identity_field_mapping",
            "items",
        "gaps",
        "excluded",
        "blockers",
        "retrieval_methods_used",
        "missing_evidence",
        "disabled_modes",
        "timing",
        "trace_refs",
    }.issubset(contract.required_fields)


def test_patch_and_review_contracts_require_review_gate_fields() -> None:
    registry = ArtifactTypeRegistry()

    patch = registry.get("patch_proposal")
    review = registry.get("proposal_review")

    assert {
        "proposal_id",
        "diff_intent",
        "change_units",
        "context_pack",
        "evidence_refs",
        "expected_tests",
        "no_op_status",
        "rollback_hints",
    }.issubset(patch.required_fields)
    assert {"decision", "findings", "allowed_next_stage", "checked_rules"}.issubset(
        review.required_fields
    )


def test_critic_assessment_contract_binds_score_to_exact_proposal_revision() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("critic_assessment")

    assert {
        "assessor_id",
        "assessor_kind",
        "independence_boundary",
        "subject_artifact_ref",
        "subject_artifact_hash",
        "dimension_scores",
        "total_score",
        "policy_version",
        "applicability",
        "aggregation_method",
        "dimension_weights",
        "verdict",
        "findings",
        "limitations",
    }.issubset(contract.required_fields)
    assert contract.producer_stage == "proposal_review"
    assert contract.required_exact_revision_upstream_artifacts == frozenset(
        {"patch_proposal"}
    )


def test_checkpoint_contract_requires_resume_binding() -> None:
    registry = ArtifactTypeRegistry()

    checkpoint = registry.get("workflow_checkpoint")

    assert {
        "state_snapshot",
        "artifact_refs",
        "artifact_hashes",
        "resume_binding",
        "resume_allowed_fields",
    }.issubset(checkpoint.required_fields)


def test_schema_validation_blocks_missing_required_field(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStoreError, match="missing required fields"):
        store.write(
            feature_id="feature_001",
            artifact_type="feature_spec",
            payload={"node_name": "draft_feature_spec", "stage": "feature_spec"},
        )


def test_non_blocking_implementation_plan_requires_binding_registry(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    payload = _implementation_payload()
    payload.pop("binding_registry")

    with pytest.raises(ArtifactStoreError, match="requires binding_registry"):
        store.write(
            feature_id="feature_001",
            artifact_type="implementation_plan",
            payload=payload,
            upstream_refs=[feature_spec, evidence_pack],
        )


def test_non_blocking_repair_plan_requires_exact_source_proposal_lineage(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    implementation_plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec, evidence_pack],
    )
    patch_proposal = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload=_patch_payload(),
        upstream_refs=[implementation_plan, evidence_pack],
    )
    proposal_review = store.write(
        feature_id="feature_001",
        artifact_type="proposal_review",
        payload=_review_payload(),
        upstream_refs=[patch_proposal],
    )
    dry_run = store.write(
        feature_id="feature_001",
        artifact_type="dry_run_result",
        payload=_dry_run_payload(),
        upstream_refs=[patch_proposal, proposal_review],
    )
    build_result = store.write(
        feature_id="feature_001",
        artifact_type="build_result",
        payload=_build_payload(),
        status="blocked",
        upstream_refs=[dry_run],
    )

    with pytest.raises(ArtifactStoreError, match="missing required exact upstream"):
        store.write(
            feature_id="feature_001",
            artifact_type="repair_plan",
            payload=_repair_payload(),
            upstream_refs=[build_result],
        )
    with pytest.raises(ArtifactStoreError, match="requires exact revision upstream"):
        store.write(
            feature_id="feature_001",
            artifact_type="repair_plan",
            payload=_repair_payload(),
            upstream_refs=[build_result, patch_proposal],
        )


def test_unknown_schema_version_is_rejected_on_read(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    path = Path(ref.path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["schema_version"] = "999.0"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    tampered_ref = type(ref)(
        feature_id=ref.feature_id,
        artifact_type=ref.artifact_type,
        path=ref.path,
        artifact_hash=envelope["artifact_hash"],
    )

    with pytest.raises(ArtifactStoreError, match="Unsupported schema_version"):
        store.read(tampered_ref)


def test_upstream_hash_recorded(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )

    plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec, evidence_pack],
    )

    envelope = store.read(plan)
    upstream_by_type = {
        upstream["artifact_type"]: upstream
        for upstream in envelope["inputs"]["upstream_artifacts"]
    }
    assert upstream_by_type["feature_spec"]["artifact_hash"] == feature_spec.artifact_hash
    assert upstream_by_type["evidence_pack"]["artifact_hash"] == evidence_pack.artifact_hash


def test_stale_detected_after_upstream_change(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec, evidence_pack],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_changed_feature_payload(),
    )

    freshness = store.check_freshness(plan)

    assert freshness.status == "stale"
    assert freshness.stale_reasons == ["feature_spec hash changed"]


def test_stale_artifact_cannot_enter_patch_proposal_generation(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec, evidence_pack],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_changed_feature_payload(),
    )

    with pytest.raises(StaleArtifactError, match="feature_spec hash changed"):
        store.read_for_stage(plan, consumer_stage="generate_patch_proposal")


def test_transitive_stale_detected_after_deep_upstream_change(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec, evidence_pack],
    )
    patch_proposal = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload=_patch_payload(),
        upstream_refs=[plan, evidence_pack],
    )
    proposal_review = store.write(
        feature_id="feature_001",
        artifact_type="proposal_review",
        payload=_review_payload(),
        upstream_refs=[patch_proposal],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_changed_feature_payload(),
    )

    freshness = store.check_freshness(proposal_review)

    assert freshness.status == "stale"
    assert freshness.stale_reasons == ["feature_spec hash changed"]
    with pytest.raises(StaleArtifactError, match="feature_spec hash changed"):
        store.read_for_stage(proposal_review, consumer_stage="dry_run_apply")


def test_dashboard_can_read_stale_reason(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec, evidence_pack],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_changed_feature_payload(),
    )

    view = store.check_freshness(plan)

    assert view.status == "stale"
    assert "feature_spec hash changed" in view.stale_reasons
