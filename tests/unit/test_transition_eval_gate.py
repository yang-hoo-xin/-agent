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
    }
