"""Deterministic transition evaluation gates."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .agent_quality import METRIC_DIRECTIONS, REQUIRED_RETRIEVAL_METRICS
from .quality_policy import QualityGatePolicy, evaluate_quality_policy


def build_transition_eval_gate_report(
    *,
    review: Mapping[str, Any],
    dry_run: Mapping[str, Any],
    build: Mapping[str, Any],
    runtime: Mapping[str, Any],
    v1_boundary: Mapping[str, Any],
    claims_real_success: bool,
    evaluation_context: Mapping[str, Any] | None = None,
    evaluation_required: bool = False,
    continuation_mode: str = "mutation",
    verification_only_lineage_verified: bool = False,
) -> dict[str, Any]:
    """Build the TRANSITION-001 eval gate report."""

    if continuation_mode not in {"mutation", "verification_only"}:
        raise ValueError(f"Unsupported continuation_mode: {continuation_mode}")
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
        _build_claim_boundary_case(build=build),
        _runtime_claim_boundary_case(runtime=runtime),
        _insufficient_baseline_case(context),
        _stale_evidence_case(context),
        _missing_required_metric_case(context),
    ]
    if continuation_mode == "verification_only":
        cases.insert(
            2,
            _verification_only_continuation_case(
                build=build,
                lineage_verified=verification_only_lineage_verified,
            ),
        )
    else:
        cases[2:2] = [
            _false_continue_case(review=review, dry_run=dry_run, build=build),
            _review_correctness_case(review=review),
            _dry_run_safety_case(review=review, dry_run=dry_run),
        ]
    required = evaluation_required or context.get("evaluation_required") is True
    if required:
        cases.extend(_required_evaluation_contract_cases(evaluation_context))
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
        "continuation_mode": continuation_mode,
        "status": "failed" if blockers else "passed",
        "summary": {
            "total": len(cases),
            "passed": sum(1 for case in cases if case["status"] == "passed"),
            "failed": len(blockers),
        },
        "cases": cases,
        "blockers": blockers,
    }


def _verification_only_continuation_case(
    *,
    build: Mapping[str, Any],
    lineage_verified: bool,
) -> dict[str, str]:
    if build.get("input_execution_mode") != "verification_only":
        return _failed(
            "verification_only_build_identity",
            "verification_only_continuation",
            "BuildResult does not preserve verification_only input identity.",
        )
    if not lineage_verified:
        return _failed(
            "verification_only_lineage",
            "verification_only_continuation",
            "Verification-only FeatureSpec/EvidencePack lineage is not fresh and exact.",
        )
    return _passed(
        "verification_only_continuation",
        "verification_only_continuation",
        "Verification-only continuation is bound to fresh FeatureSpec and EvidencePack inputs.",
    )


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
    missing_binding = _missing_runtime_success_binding(runtime)
    if missing_binding:
        return _failed(
            "runtime_claim_boundary_binding",
            "claim_boundary",
            "Runtime claims real success without required binding fields: "
            + ", ".join(missing_binding)
            + ".",
        )
    non_goal_failure = _non_goal_preservation_failure(runtime)
    if non_goal_failure:
        return _failed(
            "runtime_claim_boundary_non_goal_preservation",
            "claim_boundary",
            non_goal_failure,
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


def _required_evaluation_contract_cases(
    context: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    if context is None:
        return [
            _failed(
                "required_evaluation_context",
                "evaluation_contract",
                "Evaluation is required but evaluation_context is missing.",
            )
        ]
    cases: list[dict[str, str]] = []
    required_values = {
        "evaluation_mode": "benchmark",
        "completeness_status": "complete",
        "execution_status": "completed",
        "evidence_status": "fresh",
        "quality_gate_status": "pass",
        "gate_eligible": True,
    }
    for field, expected in required_values.items():
        actual = context.get(field)
        if actual != expected:
            cases.append(
                _failed(
                    f"required_{field}",
                    "evaluation_contract",
                    f"Required evaluation expects {field}={expected!r}; got {actual!r}.",
                )
            )
        else:
            cases.append(
                _passed(
                    f"required_{field}",
                    "evaluation_contract",
                    f"Required evaluation field {field} is valid.",
                )
            )
    required_metrics = _string_tuple(context.get("required_metrics"))
    metrics = context.get("metrics")
    invalid_metrics: list[str] = []
    if not required_metrics:
        invalid_metrics.append("required_metrics")
    if not isinstance(metrics, Mapping):
        invalid_metrics.append("metrics")
    else:
        for metric in required_metrics:
            value = metrics.get(metric)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.0 <= float(value) <= 1.0
            ):
                invalid_metrics.append(metric)
    if invalid_metrics:
        cases.append(
            _failed(
                "required_metric_values",
                "evaluation_contract",
                "Required evaluation has missing or invalid metric values: "
                + ", ".join(invalid_metrics)
                + ".",
            )
        )
    else:
        cases.append(
            _passed(
                "required_metric_values",
                "evaluation_contract",
                "Required evaluation metric values are finite and within [0, 1].",
            )
        )
    policy_value = context.get("quality_policy")
    try:
        if not isinstance(policy_value, Mapping):
            raise ValueError("quality_policy is missing")
        policy = QualityGatePolicy.from_mapping(policy_value)
        if not set(REQUIRED_RETRIEVAL_METRICS) <= set(policy.required_metric_names):
            raise ValueError("quality_policy does not cover required retrieval metrics")
        if any(float(policy.thresholds[name]) <= 0 for name in REQUIRED_RETRIEVAL_METRICS):
            raise ValueError("required retrieval metric thresholds must be greater than zero")
        if not isinstance(metrics, Mapping):
            raise ValueError("metrics is missing")
        recomputed = evaluate_quality_policy(policy, metrics, METRIC_DIRECTIONS)
        if recomputed != "pass":
            raise ValueError("quality policy recomputation did not pass")
        if context.get("quality_gate_status") != recomputed:
            raise ValueError("reported quality_gate_status does not match recomputation")
    except ValueError as exc:
        cases.append(
            _failed(
                "required_quality_policy",
                "evaluation_contract",
                f"Required evaluation quality policy is invalid: {exc}.",
            )
        )
    else:
        cases.append(
            _passed(
                "required_quality_policy",
                "evaluation_contract",
                "Quality policy is versioned and independently recomputes to pass.",
            )
        )
    return cases


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


def _missing_runtime_success_binding(runtime: Mapping[str, Any]) -> tuple[str, ...]:
    missing: list[str] = []
    if not runtime.get("run_id"):
        missing.append("run_id")
    build_artifact_ref = runtime.get("build_artifact_ref")
    if not _valid_build_artifact_ref(build_artifact_ref):
        missing.append("build_artifact_ref")
    build_artifact_hash = runtime.get("build_artifact_hash")
    if not build_artifact_hash:
        missing.append("build_artifact_hash")
    elif (
        isinstance(build_artifact_ref, Mapping)
        and build_artifact_ref.get("artifact_hash") != build_artifact_hash
    ):
        missing.append("build_artifact_hash")
    runtime_trust_binding = runtime.get("runtime_trust_binding")
    operator_completion_required = bool(
        isinstance(runtime_trust_binding, Mapping)
        and runtime_trust_binding.get("operator_completion_required") is True
    )
    if not _has_observed_acceptance_plugin_markers(
        runtime.get("plugin_marker_binding"),
        _acceptance_criteria(runtime),
        allow_non_marker_acceptance=operator_completion_required,
    ):
        missing.append("plugin_marker_binding")
    if _requires_runtime_trust_binding(runtime) and not _has_trusted_runtime_binding(
        runtime.get("runtime_trust_binding")
    ):
        missing.append("runtime_trust_binding")
    return tuple(missing)


def _valid_build_artifact_ref(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return all(
        isinstance(value.get(field), str) and bool(value.get(field))
        for field in ("feature_id", "artifact_type", "path", "artifact_hash")
    )


def _acceptance_criteria(runtime: Mapping[str, Any]) -> tuple[str, ...]:
    contract = runtime.get("acceptance_contract")
    if not isinstance(contract, Mapping):
        return ()
    return _string_tuple(contract.get("acceptance_criteria"))


def _has_observed_acceptance_plugin_markers(
    value: Any,
    acceptance_criteria: tuple[str, ...],
    *,
    allow_non_marker_acceptance: bool = False,
) -> bool:
    observed_acceptance = _observed_acceptance_marker_criteria(value)
    if allow_non_marker_acceptance:
        configured_acceptance = _configured_acceptance_marker_criteria(value)
        return bool(configured_acceptance) and configured_acceptance.issubset(
            observed_acceptance
        )
    if acceptance_criteria:
        return set(acceptance_criteria).issubset(observed_acceptance)
    return bool(observed_acceptance)


def _configured_acceptance_marker_criteria(value: Any) -> set[str]:
    if not isinstance(value, Mapping):
        return set()
    configured: set[str] = set()
    markers = value.get("markers") or value.get("acceptance_markers") or ()
    if not isinstance(markers, (list, tuple)):
        return configured
    for marker in markers:
        if not isinstance(marker, Mapping):
            continue
        acceptance_criterion = marker.get("acceptance_criterion")
        if isinstance(acceptance_criterion, str) and acceptance_criterion:
            configured.add(acceptance_criterion)
    return configured


def _observed_acceptance_marker_criteria(value: Any) -> set[str]:
    if not isinstance(value, Mapping):
        return set()
    observed: set[str] = set()
    _add_observed_acceptance_marker(observed, value)
    markers = value.get("markers") or value.get("acceptance_markers") or ()
    if not isinstance(markers, (list, tuple)):
        return observed
    for marker in markers:
        if isinstance(marker, Mapping):
            _add_observed_acceptance_marker(observed, marker)
    return observed


def _add_observed_acceptance_marker(
    observed: set[str],
    marker: Mapping[str, Any],
) -> None:
    acceptance_criterion = marker.get("acceptance_criterion")
    if marker.get("observed") is True and isinstance(acceptance_criterion, str):
        observed.add(acceptance_criterion)


def _non_goal_preservation_failure(runtime: Mapping[str, Any]) -> str | None:
    preservation = runtime.get("non_goal_preservation")
    if not isinstance(preservation, Mapping):
        return "Runtime claims real success without non_goal_preservation."
    status = preservation.get("status")
    violations = preservation.get("violations")
    if status == "violated":
        return "Runtime claims real success with non-goal preservation violations."
    if isinstance(violations, (list, tuple)) and violations:
        return "Runtime claims real success with non-goal preservation violations."
    checked = preservation.get("checked")
    if isinstance(checked, (list, tuple)) and checked and status != "preserved":
        return "Runtime claims real success without preserved non-goal status."
    non_goals_checked = runtime.get("non_goals_checked")
    if isinstance(non_goals_checked, (list, tuple)) and non_goals_checked and status != "preserved":
        return "Runtime claims real success without preserved non-goal status."
    return None


def _requires_runtime_trust_binding(runtime: Mapping[str, Any]) -> bool:
    return runtime.get("evidence_source") == "gtfo_real_runtime_automation"


def _has_trusted_runtime_binding(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("status") != "trusted":
        return False
    checks = value.get("checks")
    if not isinstance(checks, Mapping):
        return False
    required_checks = {
        "run_id",
        "feature_id",
        "build_artifact_hash",
        "runtime_process_identity",
        "current_run_logs",
        "plugin_load_marker",
        "acceptance_markers",
        "screenshot_runtime_artifact_linkage",
    }
    if value.get("deployment_required") is True:
        required_checks.update(
            {
                "deployed_plugin_artifact_hash",
                "game_directory_restoration",
            }
        )
    if value.get("operator_completion_required") is True:
        required_checks.add("operator_completion")
    return all(
        isinstance(checks.get(check_name), Mapping)
        and checks[check_name].get("status") == "passed"
        for check_name in required_checks
    )
