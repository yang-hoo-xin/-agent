"""Tests for Phase B artifact contracts and freshness checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.mod_agent.artifacts import (
    ArtifactStore,
    ArtifactStoreError,
    ArtifactTypeRegistry,
    StaleArtifactError,
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
        "evidence_source_paths": [],
        "target_files": [],
        "target_symbols": [],
        "evidence_refs": [],
        "proposed_changes": [],
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
        "evidence_refs": [],
        "scope_boundary": [],
        "risk_assessment": {"risk_level": "blocked"},
        "expected_tests": [],
        "manual_review_notes": [],
        "blocked": True,
        "blockers": [],
    }


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


def _evidence_payload() -> dict[str, object]:
    return {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "stub",
        "query": "Load",
        "readiness": "insufficient",
        "can_generate_patch": False,
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
        "feature_spec",
        "evidence_pack",
        "implementation_plan",
        "patch_proposal",
        "proposal_review",
        "dry_run_result",
        "build_result",
        "runtime_evidence",
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


def test_git_change_record_contract_supports_audit_and_replay() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("git_change_record")

    assert contract.producer_stage == "git_audit"
    assert {"commit_sha", "replay_command", "rollback_hint"}.issubset(
        contract.required_fields
    )
    assert "repair_plan" in contract.consumer_stages
    assert contract.dashboard_projection


def test_runtime_evidence_contract_requires_acceptance_fields() -> None:
    registry = ArtifactTypeRegistry()

    contract = registry.get("runtime_evidence")
    manual_contract = registry.get("manual_evidence")

    required = {
        "feature_id",
        "execution_mode",
        "evidence_source",
        "startup_loaded",
        "gameplay_behavior_verified",
        "evidence_items",
        "verification_status",
        "acceptance_status",
        "raw_supplied_output",
        "sources",
        "non_goals_checked",
        "limitations",
        "claims_real_runtime_success",
    }
    assert required.issubset(contract.required_fields)
    assert required.issubset(manual_contract.required_fields)


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

    assert {"proposal_id", "diff_intent", "evidence_refs", "expected_tests"}.issubset(
        patch.required_fields
    )
    assert {"decision", "findings", "allowed_next_stage", "checked_rules"}.issubset(
        review.required_fields
    )


def test_schema_validation_blocks_missing_required_field(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStoreError, match="missing required fields"):
        store.write(
            feature_id="feature_001",
            artifact_type="feature_spec",
            payload={"node_name": "draft_feature_spec", "stage": "feature_spec"},
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
