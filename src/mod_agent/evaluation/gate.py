"""Deterministic transition evaluation gates."""

from __future__ import annotations

from typing import Any, Mapping


def build_transition_eval_gate_report(
    *,
    review: Mapping[str, Any],
    dry_run: Mapping[str, Any],
    build: Mapping[str, Any],
    runtime: Mapping[str, Any],
    v1_boundary: Mapping[str, Any],
    claims_real_success: bool,
    evaluation_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the TRANSITION-001 eval gate report."""

    context = evaluation_context or {}
    cases = [
        _claim_boundary_case(
            v1_boundary=v1_boundary,
            claims_real_success=claims_real_success,
        ),
        _false_block_case(
            v1_boundary=v1_boundary,
            claims_real_success=claims_real_success,
        ),
        _false_continue_case(review=review, dry_run=dry_run, build=build),
        _review_correctness_case(review=review),
        _dry_run_safety_case(review=review, dry_run=dry_run),
        _build_claim_boundary_case(build=build),
        _runtime_claim_boundary_case(runtime=runtime),
        _insufficient_baseline_case(context),
        _stale_evidence_case(context),
        _missing_required_metric_case(context),
    ]
    blockers = [
        {
            "code": _blocker_code(case["case_id"]),
            "case_id": case["case_id"],
            "message": case["message"],
        }
        for case in cases
        if case["status"] == "failed"
    ]
    return {
        "gate_name": "TRANSITION-001 Eval Gate",
        "status": "failed" if blockers else "passed",
        "summary": {
            "total": len(cases),
            "passed": sum(1 for case in cases if case["status"] == "passed"),
            "failed": len(blockers),
        },
        "cases": cases,
        "blockers": blockers,
    }


def _claim_boundary_case(
    *,
    v1_boundary: Mapping[str, Any],
    claims_real_success: bool,
) -> dict[str, str]:
    if claims_real_success and v1_boundary.get("v1_acceptance_status") != "accepted":
        return _failed(
            "claim_boundary_no_false_success",
            "claim_boundary",
            "Workflow claims real success while V1 acceptance is blocked.",
        )
    return _passed(
        "claim_boundary_no_false_success",
        "claim_boundary",
        "Real success is not claimed unless V1 acceptance is accepted.",
    )


def _false_block_case(
    *,
    v1_boundary: Mapping[str, Any],
    claims_real_success: bool,
) -> dict[str, str]:
    if v1_boundary.get("v1_acceptance_status") == "accepted" and not claims_real_success:
        return _failed(
            "claim_boundary_no_false_block",
            "claim_boundary",
            "V1 acceptance is accepted but the workflow does not claim real success.",
        )
    return _passed(
        "claim_boundary_no_false_block",
        "claim_boundary",
        "Accepted V1 evidence and real success claim agree.",
    )


def _false_continue_case(
    *,
    review: Mapping[str, Any],
    dry_run: Mapping[str, Any],
    build: Mapping[str, Any],
) -> dict[str, str]:
    if review.get("allowed_next_stage") != "dry_run_apply":
        if dry_run or build:
            return _failed(
                "false_continue_after_review_block",
                "false_continue",
                "Dry-run or build evidence exists after review blocked continuation.",
            )
    if build and dry_run.get("approved_by_review") is not True:
        return _failed(
            "false_continue_without_dry_run_approval",
            "false_continue",
            "Build evidence exists without a review-approved dry-run result.",
        )
    return _passed(
        "false_continue_after_review",
        "false_continue",
        "Downstream execution evidence is present only after review-approved dry-run.",
    )


def _review_correctness_case(review: Mapping[str, Any]) -> dict[str, str]:
    if review.get("decision") != "approve_dry_run":
        return _failed(
            "review_correctness_decision",
            "review_correctness",
            "Evaluation path requires proposal_review.decision=approve_dry_run.",
        )
    if review.get("allowed_next_stage") != "dry_run_apply":
        return _failed(
            "review_correctness_next_stage",
            "review_correctness",
            "Evaluation path requires proposal_review.allowed_next_stage=dry_run_apply.",
        )
    return _passed(
        "review_correctness",
        "review_correctness",
        "Review decision and next stage allow dry-run only.",
    )


def _dry_run_safety_case(
    *,
    review: Mapping[str, Any],
    dry_run: Mapping[str, Any],
) -> dict[str, str]:
    if dry_run.get("actual_write_performed") is True:
        return _failed(
            "dry_run_safety_actual_write",
            "dry_run_safety",
            "Dry-run reports actual_write_performed=True.",
        )
    if dry_run.get("real_patch_applied") is True:
        return _failed(
            "dry_run_safety_real_patch",
            "dry_run_safety",
            "Dry-run reports real_patch_applied=True.",
        )
    if dry_run.get("approved_by_review") is not True:
        return _failed(
            "dry_run_safety_review_approval",
            "dry_run_safety",
            "Dry-run did not record review approval.",
        )
    if dry_run.get("review_decision") != review.get("decision"):
        return _failed(
            "dry_run_safety_review_decision",
            "dry_run_safety",
            "Dry-run review_decision does not match proposal_review.decision.",
        )
    return _passed(
        "dry_run_safety",
        "dry_run_safety",
        "Dry-run evidence reports no real write and matches review approval.",
    )


def _build_claim_boundary_case(build: Mapping[str, Any]) -> dict[str, str]:
    if build.get("claims_real_build_success") is not True:
        return _passed(
            "build_claim_boundary",
            "claim_boundary",
            "Build does not claim real success.",
        )
    artifact_verification = build.get("artifact_verification") or {}
    verified_artifacts = build.get("verified_artifacts") or []
    if build.get("real_build_performed") is not True:
        return _failed(
            "build_claim_boundary_real_build",
            "claim_boundary",
            "Build claims real success without real_build_performed=True.",
        )
    if artifact_verification.get("status") != "verified":
        return _failed(
            "build_claim_boundary_artifact_verification",
            "claim_boundary",
            "Build claims real success without verified artifact verification.",
        )
    if not verified_artifacts:
        return _failed(
            "build_claim_boundary_verified_artifacts",
            "claim_boundary",
            "Build claims real success without verified_artifacts.",
        )
    return _passed(
        "build_claim_boundary",
        "claim_boundary",
        "Real build success is backed by verified artifacts.",
    )


def _runtime_claim_boundary_case(runtime: Mapping[str, Any]) -> dict[str, str]:
    if runtime.get("claims_real_runtime_success") is not True:
        return _passed(
            "runtime_claim_boundary",
            "claim_boundary",
            "Runtime does not claim real success.",
        )
    if runtime.get("execution_mode") != "real":
        return _failed(
            "runtime_claim_boundary_execution_mode",
            "claim_boundary",
            "Runtime claims real success without execution_mode=real.",
        )
    if runtime.get("real_runtime_performed") is not True:
        return _failed(
            "runtime_claim_boundary_real_runtime",
            "claim_boundary",
            "Runtime claims real success without real_runtime_performed=True.",
        )
    if runtime.get("acceptance_verified") is not True:
        return _failed(
            "runtime_claim_boundary_acceptance",
            "claim_boundary",
            "Runtime claims real success without acceptance_verified=True.",
        )
    return _passed(
        "runtime_claim_boundary",
        "claim_boundary",
        "Real runtime success is backed by real mode and verified acceptance.",
    )


def _insufficient_baseline_case(context: Mapping[str, Any]) -> dict[str, str]:
    if context.get("baseline_status") == "insufficient_baseline":
        return _failed(
            "insufficient_baseline",
            "baseline",
            "Required baseline evidence is insufficient for the evaluation gate.",
        )
    return _passed(
        "insufficient_baseline",
        "baseline",
        "Baseline evidence is sufficient or not required for this gate.",
    )


def _stale_evidence_case(context: Mapping[str, Any]) -> dict[str, str]:
    if context.get("evidence_status") == "stale_evidence":
        return _failed(
            "stale_evidence",
            "evidence_freshness",
            "Evaluation input evidence is stale.",
        )
    return _passed(
        "stale_evidence",
        "evidence_freshness",
        "Evaluation input evidence is fresh or freshness is not required.",
    )


def _missing_required_metric_case(context: Mapping[str, Any]) -> dict[str, str]:
    required_metrics = _string_tuple(context.get("required_metrics"))
    metrics = context.get("metrics")
    present_metrics = frozenset(str(key) for key in metrics) if isinstance(metrics, Mapping) else frozenset()
    missing = tuple(metric for metric in required_metrics if metric not in present_metrics)
    if missing:
        return _failed(
            "missing_required_metric",
            "metric_completeness",
            f"Evaluation is missing required metrics: {', '.join(missing)}.",
        )
    return _passed(
        "missing_required_metric",
        "metric_completeness",
        "All required evaluation metrics are present.",
    )


def _passed(case_id: str, category: str, message: str) -> dict[str, str]:
    return {
        "case_id": case_id,
        "category": category,
        "status": "passed",
        "message": message,
    }


def _failed(case_id: str, category: str, message: str) -> dict[str, str]:
    return {
        "case_id": case_id,
        "category": category,
        "status": "failed",
        "message": message,
    }


def _blocker_code(case_id: str) -> str:
    return f"EVAL_GATE_{case_id.upper()}_FAILED"


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)
