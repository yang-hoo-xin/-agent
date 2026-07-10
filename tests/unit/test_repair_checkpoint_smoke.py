"""Joint smoke tests for repair-loop artifacts and checkpoint resume gates."""

from __future__ import annotations

from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.build import BuildAdapter, BuildProfile
from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION
from src.mod_agent.proposal import ProposalReviewer
from src.mod_agent.repair import RepairPatchProposalBuilder, RepairPlanner
from src.mod_agent.workflow import (
    ResumePayload,
    WorkflowCheckpointStore,
    create_initial_state,
)


def test_repair_review_checkpoint_resume_accepts_review_approval(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    state, refs, payloads = _repair_review_state(store)
    checkpoint_store = WorkflowCheckpointStore(store)

    checkpoint_ref = checkpoint_store.create_checkpoint(
        state,
        interrupt_reason="repair proposal review requires approval",
        resume_allowed_fields=("approvals.review",),
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    payload = ResumePayload(
        resume_id="resume_joint_001",
        run_id="run_joint_001",
        stage="review_proposal",
        decision="approve",
        approved_by="human",
        approved_at="2026-06-30T00:00:00Z",
        artifact_refs=tuple(state["artifacts"].values()),
        diff_hash=checkpoint["resume_binding"]["diff_hash"],
        notes="approve reviewed repair proposal for dry run",
    )

    decision, report_ref = checkpoint_store.resume(checkpoint_ref, payload)
    report = store.read(report_ref)["data"]

    assert payloads["repair_plan"]["failure_source"] == "build"
    assert payloads["repair_plan"]["retry_exhausted"] is False
    assert payloads["patch_proposal"]["blocked"] is False
    assert payloads["patch_proposal"]["evidence_refs"] == payloads["repair_plan"][
        "evidence_refs"
    ]
    assert payloads["proposal_review"]["allowed_next_stage"] == "dry_run_apply"
    assert payloads["proposal_review"]["trace_metrics"]["num_blocking_findings"] == 0
    assert checkpoint["checkpoint_stage"] == "review_proposal"
    assert set(checkpoint["artifact_refs"]) == set(state["artifacts"].values())
    assert checkpoint["resume_binding"]["patch_proposal_ref"] == refs[
        "patch_proposal"
    ].path
    assert checkpoint["resume_binding"]["patch_proposal_hash"] == refs[
        "patch_proposal"
    ].artifact_hash
    assert checkpoint["resume_binding"]["proposal_review_ref"] == refs[
        "proposal_review"
    ].path
    assert checkpoint["resume_binding"]["proposal_review_hash"] == refs[
        "proposal_review"
    ].artifact_hash
    assert checkpoint["resume_binding"]["diff_hash"].startswith("sha256:")
    assert decision.allowed is True
    assert decision.applied_updates["approvals"]["review"] is True
    assert (
        decision.applied_updates["restored_state"]["artifacts"]["patch_proposal"]
        == refs["patch_proposal"].path
    )
    assert (
        decision.applied_updates["restored_state"]["artifact_hashes"]["patch_proposal"]
        == refs["patch_proposal"].artifact_hash
    )
    assert report["allowed"] is True
    assert report["applied_updates"]["restored_state"]["current_stage"] == (
        "review_proposal"
    )
    assert refs["proposal_review"].path in checkpoint["artifact_refs"]
    assert report["checkpoint_id"] == checkpoint["checkpoint_id"]


def test_repair_review_checkpoint_resume_blocks_double_and_stale_resume(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    state, _, payloads = _repair_review_state(store)
    checkpoint_store = WorkflowCheckpointStore(store)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        state,
        interrupt_reason="repair proposal review requires approval",
        resume_allowed_fields=("approvals.review",),
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    payload = ResumePayload(
        resume_id="resume_joint_001",
        run_id="run_joint_001",
        stage="review_proposal",
        decision="approve",
        approved_by="human",
        approved_at="2026-06-30T00:00:00Z",
        artifact_refs=tuple(state["artifacts"].values()),
        diff_hash=checkpoint["resume_binding"]["diff_hash"],
    )

    first_decision, _ = checkpoint_store.resume(checkpoint_ref, payload)
    second_decision, second_ref = checkpoint_store.resume(checkpoint_ref, payload)
    second_report = store.read(second_ref)["data"]

    stale_state, refs, stale_payloads = _repair_review_state(
        ArtifactStore(tmp_path / "stale_artifacts")
    )
    stale_store = ArtifactStore(tmp_path / "stale_artifacts")
    stale_checkpoint_store = WorkflowCheckpointStore(stale_store)
    stale_checkpoint_ref = stale_checkpoint_store.create_checkpoint(
        stale_state,
        interrupt_reason="repair proposal review requires approval",
        resume_allowed_fields=("approvals.review",),
    )
    stale_checkpoint = stale_store.read(stale_checkpoint_ref)["data"]
    changed_proposal = dict(stale_payloads["patch_proposal"])
    changed_proposal["message"] = "Patch proposal changed after checkpoint."
    stale_store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload=changed_proposal,
        upstream_refs=[
            refs["implementation_plan"],
            refs["evidence_pack"],
            refs["repair_plan"],
        ],
    )
    stale_payload = ResumePayload(
        resume_id="resume_stale_001",
        run_id="run_joint_001",
        stage="review_proposal",
        decision="approve",
        approved_by="human",
        approved_at="2026-06-30T00:00:00Z",
        artifact_refs=tuple(stale_state["artifacts"].values()),
        diff_hash=stale_checkpoint["resume_binding"]["diff_hash"],
    )

    stale_decision, stale_ref = stale_checkpoint_store.resume(
        stale_checkpoint_ref,
        stale_payload,
    )
    stale_report = stale_store.read(stale_ref)["data"]

    assert first_decision.allowed is True
    assert second_decision.allowed is False
    assert second_report["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"
    assert stale_decision.allowed is False
    assert stale_report["blockers"][0]["code"] == "STALE_RESUME_REJECTED"
    assert stale_report["stale_reasons"] == ["patch_proposal hash changed"]


def test_repair_review_checkpoint_resume_rejects_changed_diff_hash(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    state, _, _ = _repair_review_state(store)
    checkpoint_store = WorkflowCheckpointStore(store)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        state,
        interrupt_reason="repair proposal review requires approval",
        resume_allowed_fields=("approvals.review",),
    )
    payload = ResumePayload(
        resume_id="resume_diff_hash_mismatch_001",
        run_id="run_joint_001",
        stage="review_proposal",
        decision="approve",
        approved_by="human",
        approved_at="2026-06-30T00:00:00Z",
        artifact_refs=tuple(state["artifacts"].values()),
        diff_hash="sha256:not-the-checkpoint-diff",
    )

    decision, report_ref = checkpoint_store.resume(checkpoint_ref, payload)
    report = store.read(report_ref)["data"]

    assert decision.allowed is False
    assert report["allowed"] is False
    assert report["blockers"][0]["code"] == "RESUME_DIFF_HASH_MISMATCH"


def _repair_review_state(
    store: ArtifactStore,
) -> tuple[
    dict[str, object],
    dict[str, ArtifactRef],
    dict[str, dict[str, object]],
]:
    feature_id = "feature_001"
    feature_payload = _feature_payload()
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=feature_payload,
    )
    evidence_payload = _evidence_payload()
    evidence_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        payload=evidence_payload,
        upstream_refs=[feature_ref],
    )
    implementation_payload = _implementation_payload()
    implementation_ref = store.write(
        feature_id=feature_id,
        artifact_type="implementation_plan",
        payload=implementation_payload,
        upstream_refs=[feature_ref, evidence_ref],
    )
    original_proposal_payload = _patch_payload()
    original_proposal_ref = store.write(
        feature_id=feature_id,
        artifact_type="patch_proposal",
        payload=original_proposal_payload,
        upstream_refs=[implementation_ref, evidence_ref],
    )
    original_review_ref = store.write(
        feature_id=feature_id,
        artifact_type="proposal_review",
        payload=_review_payload(),
        upstream_refs=[original_proposal_ref],
    )
    dry_run_ref = store.write(
        feature_id=feature_id,
        artifact_type="dry_run_result",
        payload=_dry_run_payload(),
        upstream_refs=[original_proposal_ref, original_review_ref],
    )
    build_payload = _failed_build_payload(feature_id)
    build_ref = store.write(
        feature_id=feature_id,
        artifact_type="build_result",
        payload=build_payload,
        status="blocked",
        upstream_refs=[dry_run_ref],
    )
    repair_payload = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=build_payload,
        build_result_ref=build_ref.path,
        retry_count=0,
        target_behavior=str(feature_payload["target_behavior"]),
        proposal_context_pack=original_proposal_payload["context_pack"],
        implementation_plan=implementation_payload,
    ).to_artifact_payload()
    repair_ref = store.write(
        feature_id=feature_id,
        artifact_type="repair_plan",
        payload=repair_payload,
        upstream_refs=[build_ref, original_proposal_ref],
        exact_revision_upstream_types={"patch_proposal"},
    )
    proposal_payload = RepairPatchProposalBuilder().build(
        repair_payload
    ).to_artifact_payload()
    proposal_ref = store.write(
        feature_id=feature_id,
        artifact_type="patch_proposal",
        payload=proposal_payload,
        upstream_refs=[implementation_ref, evidence_ref, repair_ref],
    )
    review_payload = ProposalReviewer().review(
        proposal_payload,
        evidence_pack=evidence_payload,
        repair_plan=repair_payload,
        implementation_plan=implementation_payload,
        feature_spec=feature_payload,
        permission_level="dry_run_write",
    ).to_artifact_payload()
    review_ref = store.write(
        feature_id=feature_id,
        artifact_type="proposal_review",
        payload=review_payload,
        upstream_refs=[proposal_ref],
    )
    refs = {
        "feature_spec": feature_ref,
        "evidence_pack": evidence_ref,
        "implementation_plan": implementation_ref,
        "build_result": build_ref,
        "repair_plan": repair_ref,
        "patch_proposal": proposal_ref,
        "proposal_review": review_ref,
    }
    state = create_initial_state(
        run_id="run_joint_001",
        request_id="req_joint_001",
        user_request="make Load enable diagnostics",
        target_domain="gtfo",
        target_mod="BetterHitFeedback",
    )
    state["feature_id"] = feature_id
    state["current_stage"] = "review_proposal"
    state["execution_path"] = "repair_loop"
    state["risk_level"] = "medium"
    state["artifacts"] = {key: ref.path for key, ref in refs.items()}
    state["artifact_hashes"] = {key: ref.artifact_hash for key, ref in refs.items()}
    state["review_summary"] = {
        "decision": review_payload["decision"],
        "allowed_next_stage": review_payload["allowed_next_stage"],
    }
    state["build_summary"] = {
        "status": build_payload["status"],
        "error_class": build_payload["error_class"],
    }
    state["retry_count"] = int(repair_payload["retry_count"])
    payloads = {
        "feature_spec": feature_payload,
        "evidence_pack": evidence_payload,
        "implementation_plan": implementation_payload,
        "build_result": build_payload,
        "repair_plan": repair_payload,
        "patch_proposal": proposal_payload,
        "proposal_review": review_payload,
    }
    return state, refs, payloads


def _feature_payload() -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "stub",
        "feature_id": "feature_001",
        "user_request": "make Load enable diagnostics",
        "target_behavior": "make Load enable diagnostics",
        "non_goals": [],
        "target_mod": "BetterHitFeedback",
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _evidence_payload() -> dict[str, object]:
    return {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "Evidence pack is sufficient for repair smoke.",
        "query": "make Load enable diagnostics",
        "readiness": "sufficient",
        "can_generate_patch": True,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": True,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "identity_field_mapping": dict(IDENTITY_FIELD_MAPPING),
        "items": [
            {
                "evidence_id": "build_diag:0:CS0246:Plugin.cs:12",
                "source_type": "target_source",
                "source_path": "Plugin.cs",
                "symbol": "Plugin.Load",
                "span": {"start_line": 12, "end_line": 12},
                "source": "Plugin.cs",
                "locator": "Plugin.cs:12",
                "snippet": "error CS0246",
                "metadata": {"kind": "compiler_diagnostic"},
            }
        ],
        "gaps": [],
        "excluded": [],
        "blockers": [],
        "retrieval_methods_used": ["build_diagnostic"],
        "missing_evidence": [],
        "disabled_modes": [],
        "timing": {"total_ms": 0},
        "trace_refs": [],
    }


def _implementation_payload() -> dict[str, object]:
    return {
        "node_name": "create_implementation_plan",
        "stage": "implementation_plan",
        "message": "stub",
        "feature_id": "feature_001",
        "evidence_source_paths": [],
        "target_files": ["Plugin.cs"],
        "target_symbols": ["Plugin.Load"],
        "evidence_refs": ["Plugin.cs:12"],
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "evidence_id": "build_diag:0:CS0246:Plugin.cs:12",
                    "canonical_target_path": "Plugin.cs",
                    "source_type": "target_source",
                    "target_symbol": "Plugin.Load",
                    "target_span": {"start_line": 12, "end_line": 12},
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
        "proposal_id": "proposal_original_001",
        "feature_id": "feature_001",
        "summary": "Original patch proposal before build failure.",
        "files": ["Plugin.cs"],
        "diff_intent": [],
        "change_units": [],
        "context_pack": {
            "feature_id": "feature_001",
            "files": ["Plugin.cs"],
            "evidence_refs": ["Plugin.cs:12"],
            "evidence_source_paths": [],
            "scope_boundary": [],
            "change_unit_ids": [],
            "allowed_edit_binding_ids": ["edit_binding_001"],
        },
        "evidence_refs": ["Plugin.cs:12"],
        "scope_boundary": [],
        "risk_assessment": {"risk_level": "medium"},
        "expected_tests": [],
        "no_op_status": {"is_no_op": True, "reason": "stub has no diff intent"},
        "rollback_hints": [],
        "manual_review_notes": [],
        "blocked": False,
        "blockers": [],
    }


def _review_payload() -> dict[str, object]:
    return {
        "node_name": "review_proposal",
        "stage": "proposal_review",
        "message": "Original patch proposal reviewed before dry run.",
        "decision": "approve",
        "findings": [],
        "required_changes": [],
        "allowed_next_stage": "dry_run_apply",
        "checked_rules": [],
        "trace_metrics": {"num_changes_checked": 1, "num_blocking_findings": 0},
    }


def _dry_run_payload() -> dict[str, object]:
    return {
        "node_name": "dry_run_apply",
        "stage": "dry_run_apply",
        "message": "Dry run completed before failed build.",
    }


def _failed_build_payload(feature_id: str) -> dict[str, object]:
    profile = BuildProfile(
        profile_id="test_profile",
        build_system="dotnet",
        working_directory="generated_mods/TestMod",
        command=("dotnet", "build"),
        timeout_seconds=120,
        expected_artifacts=("bin/Debug/TestMod.dll",),
    )
    return BuildAdapter().from_supplied_output(
        feature_id=feature_id,
        profile=profile,
        exit_code=1,
        stderr=(
            "Plugin.cs(12,7): error CS0246: "
            "The type or namespace name 'Foo' could not be found"
        ),
    ).to_artifact_payload()
