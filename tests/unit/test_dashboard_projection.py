"""Tests for controlled-agent dashboard projections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore, ArtifactStoreError
from src.mod_agent.dashboard import DashboardProjectionBuilder


def test_empty_feature_projection_reports_missing_artifacts(tmp_path: Path) -> None:
    projection = DashboardProjectionBuilder(
        ArtifactStore(tmp_path / "artifacts")
    ).build_feature_projection("feature_001")

    assert projection["status"] == "empty"
    assert projection["artifacts"] == []
    assert "patch_proposal" in projection["missing_artifacts"]
    assert projection["build"]["status"] == "empty"
    assert "raw_artifacts" not in projection


def test_projection_exposes_summaries_without_raw_artifact_body(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    _write_full_chain(store)

    projection = DashboardProjectionBuilder(store).build_feature_projection("feature_001")
    rendered = str(projection)

    assert projection["status"] == "available"
    assert projection["proposal"]["proposal_id"] == "proposal_001"
    assert projection["proposal"]["change_count"] == 1
    assert projection["proposal"]["review_decision"] == "approved"
    assert projection["evidence"]["readiness"] == "ready"
    assert projection["evidence"]["can_generate_patch"] is True
    assert projection["evidence"]["projection_status"] == "available"
    assert projection["evidence"]["authority"] == "mod_agent_deterministic_evidence"
    assert projection["evidence"]["authoritative_for_patch"] is True
    assert projection["build"]["execution_mode"] == "fake"
    assert projection["build"]["claims_real_build_success"] is False
    assert projection["runtime"]["acceptance_status"] == "inconclusive"
    assert projection["runtime"]["claims_real_runtime_success"] is False
    assert projection["repair"]["failure_source"] == "build"
    assert projection["evaluation"]["requested_behavior_status"] == "not_verified"
    assert "raw_supplied_output" not in rendered
    assert "SECRET_RUNTIME_OUTPUT" not in rendered
    assert "diff_intent" not in rendered
    assert "C:\\secret\\Project\\Plugin.cs" not in rendered
    assert "[redacted_path:Plugin.cs]" in rendered


def test_projection_reports_stale_artifact_status(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_spec_payload(message="original"),
    )
    store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_pack_payload(),
        upstream_refs=[feature],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_spec_payload(message="changed"),
    )

    projection = DashboardProjectionBuilder(store).build_feature_projection("feature_001")
    evidence = [
        item
        for item in projection["artifacts"]
        if item["artifact_type"] == "evidence_pack"
    ][0]

    assert evidence["freshness"]["status"] == "stale"
    assert evidence["freshness"]["stale_reasons"] == ["feature_spec hash changed"]


def test_projection_blocks_unknown_artifact_without_raw_body(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    feature_dir = root / "features" / "feature_001"
    feature_dir.mkdir(parents=True)
    (feature_dir / "unknown_report.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact_type": "unknown_report",
                "feature_id": "feature_001",
                "producer_stage": "unknown",
                "status": "success",
                "data": {
                    "message": "unknown raw body",
                    "secret": "SECRET_VALUE",
                },
                "artifact_hash": "hash_001",
                "inputs": {"upstream_artifacts": []},
                "blockers": [],
                "trace_refs": [],
            }
        ),
        encoding="utf-8",
    )

    projection = DashboardProjectionBuilder(
        ArtifactStore(root)
    ).build_feature_projection("feature_001")
    rendered = str(projection)

    assert projection["artifacts"][0]["artifact_type"] == "unknown_report"
    assert projection["artifacts"][0]["artifact_status"] == "success"
    assert projection["artifacts"][0]["projection_status"] == "blocked"
    assert projection["artifacts"][0]["dashboard_projection"] == {}
    assert "SECRET_VALUE" not in rendered


def test_dashboard_artifact_root_allows_absolute_root_but_blocks_relative_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.observability.dashboard.pages.mod_agent_dashboard import (
        _artifact_store_from_input,
    )

    monkeypatch.chdir(tmp_path)

    store = _artifact_store_from_input("artifacts")
    assert store.root == (tmp_path / "artifacts").resolve()

    external_store = _artifact_store_from_input(str(tmp_path.parent / "outside_artifacts"))
    assert external_store.root == (tmp_path.parent / "outside_artifacts").resolve()

    with pytest.raises(ArtifactStoreError, match="cannot escape"):
        _artifact_store_from_input("..")


def test_dashboard_page_module_imports() -> None:
    from src.observability.dashboard.pages import mod_agent_dashboard

    assert callable(mod_agent_dashboard.render)


def _write_full_chain(store: ArtifactStore) -> None:
    feature = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_spec_payload(),
    )
    evidence = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_pack_payload(),
        upstream_refs=[feature],
    )
    plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_plan_payload(),
        upstream_refs=[feature, evidence],
    )
    proposal = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload=_patch_proposal_payload(),
        upstream_refs=[plan, evidence],
    )
    review = store.write(
        feature_id="feature_001",
        artifact_type="proposal_review",
        payload=_proposal_review_payload(),
        upstream_refs=[proposal],
    )
    dry_run = store.write(
        feature_id="feature_001",
        artifact_type="dry_run_result",
        payload={
            "node_name": "dry_run_apply",
            "stage": "dry_run_apply",
            "message": "Fake dry-run completed.",
        },
        upstream_refs=[proposal, review],
    )
    build = store.write(
        feature_id="feature_001",
        artifact_type="build_result",
        payload=_build_result_payload(),
        status="skipped",
        upstream_refs=[dry_run],
    )
    runtime = store.write(
        feature_id="feature_001",
        artifact_type="runtime_evidence",
        payload=_runtime_evidence_payload(),
        status="skipped",
        upstream_refs=[build],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="repair_plan",
        payload=_repair_plan_payload(),
    )
    store.write(
        feature_id="feature_001",
        artifact_type="eval_report",
        payload=_eval_report_payload(),
        upstream_refs=[build, runtime],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="workflow_summary",
        payload=_workflow_summary_payload(),
    )


def _feature_spec_payload(*, message: str = "Feature spec ready.") -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": message,
        "feature_id": "feature_001",
        "user_request": "Change Load text",
        "target_behavior": "Change Load text",
        "non_goals": [],
        "target_mod": None,
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _evidence_pack_payload() -> dict[str, object]:
    return {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "Evidence ready.",
        "query": "Load",
        "readiness": "ready",
        "can_generate_patch": True,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": True,
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
        "gaps": [],
        "excluded": [],
        "blockers": [],
        "retrieval_methods_used": ["symbol_exact"],
        "missing_evidence": [],
        "disabled_modes": {},
        "timing": {},
        "trace_refs": [],
    }


def _implementation_plan_payload() -> dict[str, object]:
    return {
        "node_name": "create_implementation_plan",
        "stage": "implementation_plan",
        "message": "Implementation plan ready.",
        "feature_id": "feature_001",
        "evidence_source_paths": [],
        "target_files": ["C:\\secret\\Project\\Plugin.cs"],
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


def _patch_proposal_payload() -> dict[str, object]:
    return {
        "node_name": "generate_patch_proposal",
        "stage": "patch_proposal",
        "message": "Patch proposal ready.",
        "proposal_id": "proposal_001",
        "feature_id": "feature_001",
        "summary": "Update text safely.",
        "files": ["C:\\secret\\Project\\Plugin.cs"],
        "diff_intent": [{"file": "C:\\secret\\Project\\Plugin.cs", "secret": "do not show"}],
        "evidence_refs": ["evidence_001"],
        "scope_boundary": [],
        "risk_assessment": {"risk_level": "medium"},
        "expected_tests": [],
        "manual_review_notes": [],
        "blocked": False,
        "blockers": [],
    }


def _proposal_review_payload() -> dict[str, object]:
    return {
        "node_name": "review_proposal",
        "stage": "proposal_review",
        "message": "Proposal approved for dry-run.",
        "decision": "approved",
        "findings": [],
        "required_changes": [],
        "allowed_next_stage": "dry_run_apply",
        "checked_rules": [],
        "trace_metrics": {"num_changes_checked": 1, "num_blocking_findings": 0},
    }


def _build_result_payload() -> dict[str, object]:
    return {
        "node_name": "build",
        "stage": "build",
        "message": "Fake build completed.",
        "feature_id": "feature_001",
        "execution_mode": "fake",
        "status": "skipped",
        "command": [],
        "exit_code": 0,
        "stdout_path": "C:\\secret\\build\\stdout.log",
        "stderr_path": "C:\\secret\\build\\stderr.log",
        "errors": [],
        "warnings": [],
        "duration_ms": 0,
        "error_class": "unknown",
        "diagnostics": [],
        "repair_handoff": {
            "allowed": False,
            "failure_evidence_refs": [],
            "error_class": None,
        },
        "expected_artifacts": [],
        "verified_artifacts": [],
        "artifact_verification": {
            "status": "skipped",
            "artifacts": [],
            "blockers": [],
            "error_class": None,
        },
        "real_build_performed": False,
        "claims_real_build_success": False,
        "input_execution_mode": "fake",
        "build_status": "fake_completed",
    }


def _runtime_evidence_payload() -> dict[str, object]:
    return {
        "node_name": "collect_runtime_evidence",
        "stage": "runtime_evidence",
        "message": "Fake runtime evidence collected.",
        "feature_id": "feature_001",
        "execution_mode": "fake",
        "evidence_source": "fake",
        "startup_loaded": False,
        "gameplay_behavior_verified": False,
        "evidence_items": [],
        "verification_status": "inconclusive",
        "acceptance_status": "inconclusive",
        "acceptance_verified": False,
        "acceptance_contract": {
            "acceptance_criteria": ["Requested behavior is implemented."],
            "runtime_verification_plan": ["manual"],
        },
        "raw_supplied_output": "SECRET_RUNTIME_OUTPUT",
        "sources": ["C:\\secret\\runtime.log"],
        "non_goals_checked": [],
        "limitations": ["fake runtime"],
        "claims_real_runtime_success": False,
    }


def _repair_plan_payload() -> dict[str, object]:
    return {
        "node_name": "create_repair_plan",
        "stage": "repair_plan",
        "message": "Repair plan ready.",
        "repair_id": "repair_001",
        "feature_id": "feature_001",
        "failure_source": "build",
        "failure_class": "unknown",
        "failure_evidence": {},
        "evidence_refs": ["build_result"],
        "root_cause_hypotheses": [],
        "hypothesis": "fake build did not run.",
        "recommended_fix_strategy": "collect real build output",
        "minimal_changes": [],
        "retry_count": 1,
        "retry_budget": 3,
        "retry_budget_remaining": 2,
        "retry_exhausted": False,
        "scope_expansion_allowed": False,
        "stop_condition": "real evidence required",
        "forbidden_regressions": [],
        "requires_new_evidence": True,
        "allowed_next_stage": "generate_patch_proposal",
        "blockers": [],
    }


def _eval_report_payload() -> dict[str, object]:
    return {
        "node_name": "evaluate",
        "stage": "evaluation",
        "message": "Evaluation remains inconclusive.",
        "execution_mode": "fake",
        "workflow_completion_status": "fake_execution_completed",
        "requested_behavior_status": "not_verified",
        "verdict": "inconclusive",
        "claims_real_success": False,
        "checks": [],
        "input_runtime_status": "inconclusive",
        "input_acceptance_status": "inconclusive",
        "input_acceptance_verified": False,
        "acceptance_contract": {
            "acceptance_criteria": ["Requested behavior is implemented."],
            "runtime_verification_plan": ["manual"],
        },
    }


def _workflow_summary_payload() -> dict[str, object]:
    return {
        "node_name": "done",
        "stage": "done",
        "message": "Workflow completed without real success claims.",
        "execution_mode": "fake",
        "workflow_completion_status": "fake_execution_completed",
        "requested_behavior_status": "not_verified",
        "final_status": "inconclusive",
        "claims_real_mod_success": False,
        "claims_real_build_success": False,
        "claims_real_runtime_success": False,
    }
