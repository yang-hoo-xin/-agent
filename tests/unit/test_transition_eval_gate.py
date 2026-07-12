from __future__ import annotations

from src.mod_agent.evaluation import build_transition_eval_gate_report
from src.mod_agent.workflow.transitions import route_after_evaluate


def test_transition_eval_gate_passes_controlled_fake_path() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "passed"
    assert report["summary"]["failed"] == 0


def test_required_evaluation_fails_closed_without_context() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_required=True,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "required_evaluation_context") == "failed"


def test_required_evaluation_rejects_calibration_and_invalid_metrics() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_required=True,
        evaluation_context={
            "evaluation_mode": "calibration",
            "completeness_status": "complete",
            "execution_status": "completed",
            "evidence_status": "unknown",
            "quality_gate_status": "not_evaluated",
            "gate_eligible": False,
            "required_metrics": ["recall_at_k"],
            "metrics": {"recall_at_k": None},
        },
    )

    assert report["status"] == "failed"
    assert _case_status(report, "required_evaluation_mode") == "failed"
    assert _case_status(report, "required_metric_values") == "failed"


def test_required_evaluation_accepts_explicit_valid_benchmark_context() -> None:
    required = ["recall_at_k", "precision_at_k", "precision_at_returned", "mrr_at_k"]
    policy = {
        "policy_schema_version": "quality_gate_policy_v1",
        "policy_id": "retrieval_quality_v1",
        "required_metric_names": required,
        "thresholds": {name: 0.5 for name in required},
    }
    from src.mod_agent.evaluation import QualityGatePolicy

    policy = QualityGatePolicy.from_mapping(policy).to_dict()
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_required=True,
        evaluation_context={
            "evaluation_mode": "benchmark",
            "completeness_status": "complete",
            "execution_status": "completed",
            "evidence_status": "fresh",
            "quality_gate_status": "pass",
            "gate_eligible": True,
            "required_metrics": required,
            "metrics": {name: 0.8 for name in required},
            "quality_policy": policy,
        },
    )

    assert report["status"] == "passed"


def test_required_evaluation_recomputes_policy_instead_of_trusting_pass() -> None:
    required = ["recall_at_k", "precision_at_k", "precision_at_returned", "mrr_at_k"]
    from src.mod_agent.evaluation import QualityGatePolicy

    policy = QualityGatePolicy(
        policy_schema_version="quality_gate_policy_v1",
        policy_id="retrieval_quality_v1",
        required_metric_names=tuple(required),
        thresholds={name: 0.8 for name in required},
    ).to_dict()
    report = build_transition_eval_gate_report(
        review=_review(), dry_run=_dry_run(), build=_fake_build(), runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"}, claims_real_success=False,
        evaluation_required=True,
        evaluation_context={
            "evaluation_mode": "benchmark", "completeness_status": "complete",
            "execution_status": "completed", "evidence_status": "fresh",
            "quality_gate_status": "pass", "gate_eligible": True,
            "required_metrics": required, "metrics": {name: 0.2 for name in required},
            "quality_policy": policy,
        },
    )
    assert _case_status(report, "required_quality_policy") == "failed"


def test_transition_eval_gate_detects_false_success_claim() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=True,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "claim_boundary_no_false_success") == "failed"


def test_transition_eval_gate_detects_false_block() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_verified_build(),
        runtime=_real_runtime(),
        v1_boundary={"v1_acceptance_status": "accepted"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "claim_boundary_no_false_block") == "failed"


def test_transition_eval_gate_detects_false_continue_after_review_block() -> None:
    review = {"decision": "blocked_requires_human", "allowed_next_stage": "blocked"}

    report = build_transition_eval_gate_report(
        review=review,
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "false_continue_after_review_block") == "failed"


def test_transition_eval_gate_detects_unsafe_dry_run() -> None:
    dry_run = {
        **_dry_run(),
        "actual_write_performed": True,
    }

    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=dry_run,
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "dry_run_safety_actual_write") == "failed"


def test_transition_eval_gate_detects_build_claim_without_verified_artifact() -> None:
    build = {
        **_fake_build(),
        "claims_real_build_success": True,
        "real_build_performed": True,
        "artifact_verification": {"status": "failed"},
        "verified_artifacts": [],
    }

    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=build,
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert (
        _case_status(report, "build_claim_boundary_artifact_verification")
        == "failed"
    )


def test_transition_eval_gate_detects_runtime_claim_without_real_mode() -> None:
    runtime = {
        **_fake_runtime(),
        "claims_real_runtime_success": True,
        "execution_mode": "manual",
        "real_runtime_performed": False,
        "acceptance_verified": True,
    }

    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=runtime,
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "runtime_claim_boundary_execution_mode") == "failed"


def test_transition_eval_gate_detects_runtime_claim_without_binding() -> None:
    runtime = {
        **_real_runtime(),
        "run_id": "run_001",
        "build_artifact_ref": None,
        "build_artifact_hash": None,
        "plugin_marker_binding": {},
    }

    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=runtime,
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "runtime_claim_boundary_binding") == "failed"


def test_transition_eval_gate_requires_acceptance_marker_binding() -> None:
    runtime = {
        **_real_runtime(),
        "plugin_marker_binding": {
            "markers": [
                {
                    "marker": "BETTER_HIT_FEEDBACK_STARTUP_OK",
                    "observed": True,
                }
            ]
        },
    }

    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=runtime,
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "runtime_claim_boundary_binding") == "failed"


def test_transition_eval_gate_requires_gtfo_runtime_trust_binding() -> None:
    runtime = {
        **_real_runtime(),
        "evidence_source": "gtfo_real_runtime_automation",
        "runtime_trust_binding": {
            "status": "blocked",
            "checks": {
                "screenshot_runtime_artifact_linkage": {"status": "blocked"},
            },
            "blockers": [
                "screenshot_runtime_artifact_linkage trust check did not pass"
            ],
        },
    }

    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=runtime,
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert _case_status(report, "runtime_claim_boundary_binding") == "failed"


def test_transition_eval_gate_detects_unpreserved_non_goals() -> None:
    runtime = {
        **_real_runtime(),
        "non_goal_preservation": {
            "status": "violated",
            "checked": [{"non_goal": "Do not alter recoil.", "preserved": False}],
            "violations": [{"non_goal": "Do not alter recoil.", "preserved": False}],
        },
    }

    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=runtime,
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
    )

    assert report["status"] == "failed"
    assert (
        _case_status(report, "runtime_claim_boundary_non_goal_preservation")
        == "failed"
    )


def test_transition_eval_gate_detects_insufficient_baseline() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_context={"baseline_status": "insufficient_baseline"},
    )

    assert report["status"] == "failed"
    assert _case_status(report, "insufficient_baseline") == "failed"


def test_transition_eval_gate_detects_stale_evidence() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_context={"evidence_status": "stale_evidence"},
    )

    assert report["status"] == "failed"
    assert _case_status(report, "stale_evidence") == "failed"


def test_transition_eval_gate_detects_missing_required_metric() -> None:
    report = build_transition_eval_gate_report(
        review=_review(),
        dry_run=_dry_run(),
        build=_fake_build(),
        runtime=_fake_runtime(),
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_context={
            "required_metrics": ["hit_rate", "mrr"],
            "metrics": {"hit_rate": 1.0},
        },
    )

    assert report["status"] == "failed"
    assert _case_status(report, "missing_required_metric") == "failed"


def test_route_after_evaluate_only_blocks_eval_gate_blockers() -> None:
    assert (
        route_after_evaluate(
            {
                "blockers": [
                    {
                        "stage": "historical",
                        "code": "OLD_BLOCKER",
                        "message": "Historical blocker kept for audit.",
                    }
                ]
            }
        )
        == "continue"
    )
    assert (
        route_after_evaluate(
            {
                "blockers": [
                    {
                        "stage": "evaluation",
                        "code": "EVAL_GATE_INSUFFICIENT_BASELINE_FAILED",
                        "message": "Baseline is insufficient.",
                    }
                ]
            }
        )
        == "blocked"
    )


def _case_status(report: dict[str, object], case_id: str) -> str:
    for case in report["cases"]:
        if case["case_id"] == case_id:
            return str(case["status"])
    raise AssertionError(f"missing eval gate case: {case_id}")


def _review() -> dict[str, object]:
    return {
        "decision": "approve_dry_run",
        "allowed_next_stage": "dry_run_apply",
    }


def _dry_run() -> dict[str, object]:
    return {
        "execution_mode": "fake",
        "actual_write_performed": False,
        "real_patch_applied": False,
        "approved_by_review": True,
        "review_decision": "approve_dry_run",
    }


def _fake_build() -> dict[str, object]:
    return {
        "execution_mode": "fake",
        "status": "skipped",
        "real_build_performed": False,
        "claims_real_build_success": False,
        "artifact_verification": {"status": "not_run"},
        "verified_artifacts": [],
    }


def _verified_build() -> dict[str, object]:
    return {
        "execution_mode": "local",
        "status": "success",
        "real_build_performed": True,
        "claims_real_build_success": True,
        "artifact_verification": {"status": "verified"},
        "verified_artifacts": [{"path": "bin/Debug/BetterHitFeedback.dll"}],
    }


def _fake_runtime() -> dict[str, object]:
    return {
        "execution_mode": "fake",
        "real_runtime_performed": False,
        "acceptance_verified": True,
        "claims_real_runtime_success": False,
    }


def _real_runtime() -> dict[str, object]:
    return {
        "execution_mode": "real",
        "real_runtime_performed": True,
        "acceptance_verified": True,
        "claims_real_runtime_success": True,
        "run_id": "run_001",
        "build_artifact_ref": {
            "feature_id": "feature_001",
            "artifact_type": "build_result",
            "path": "features/feature_001/build_result.json",
            "artifact_hash": "sha256:build-artifact",
        },
        "build_artifact_hash": "sha256:build-artifact",
        "acceptance_contract": {
            "acceptance_criteria": ["Requested behavior is implemented."],
            "runtime_verification_plan": ["manual"],
        },
        "plugin_marker_binding": {
            "markers": [
                {
                    "marker": "BETTER_HIT_FEEDBACK_ACCEPTANCE_OK",
                    "acceptance_criterion": "Requested behavior is implemented.",
                    "observed": True,
                }
            ]
        },
        "runtime_trust_binding": {
            "status": "not_applicable",
            "checks": {},
            "blockers": [],
        },
        "non_goal_preservation": {
            "status": "not_checked",
            "checked": [],
            "violations": [],
        },
    }
