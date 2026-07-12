"""Audit-counterexample tests for controlled-agent evaluation metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.mod_agent.evaluation import (
    AgentQualityCase,
    AgentQualityEvaluator,
    CaseObservation,
    QualityGatePolicy,
    RetrievalObservation,
    RunManifest,
    build_transition_eval_gate_report,
    load_agent_quality_cases,
    load_observations,
)

FIXTURE = Path("tests/fixtures/evaluation/agent_quality_cases.json")


def _policy(threshold: float = 0.5) -> QualityGatePolicy:
    names = ("recall_at_k", "precision_at_k", "precision_at_returned", "mrr_at_k")
    return QualityGatePolicy(
        policy_schema_version="quality_gate_policy_v1",
        policy_id="retrieval_quality_v1",
        required_metric_names=names,
        thresholds={name: threshold for name in names},
    )


def _manifest() -> RunManifest:
    return RunManifest(
        repository_revision="calibration-unbound",
        worktree_diff_sha256="calibration-unbound",
        corpus_manifest_sha256="calibration-unbound",
        evaluation_protocol_sha256="calibration-v2",
        provider_id="fixed_calibration_observations",
        provider_version="1",
        evidence_status="unknown",
    )


def _report():
    dataset = load_agent_quality_cases(FIXTURE)
    observation_set = load_observations(FIXTURE)
    return AgentQualityEvaluator().evaluate(
        dataset_schema_version=dataset.dataset_schema_version,
        dataset_version=dataset.dataset_version,
        dataset_kind=dataset.dataset_kind,
        dataset_quality_gate_eligible=dataset.quality_gate_eligible,
        dataset_sha256=dataset.dataset_sha256,
        judgment_sha256=dataset.judgment_sha256,
        arm_id="fixture_calibration",
        cases=dataset.cases,
        observations=observation_set.observations,
        run_manifest=_manifest(),
        top_k=10,
    )


def test_calibration_is_complete_but_not_gate_eligible() -> None:
    report = _report()
    context = report.to_dict()["evaluation_context"]

    assert report.completeness_status == "complete"
    assert report.execution_status == "completed"
    assert report.evidence_status == "unknown"
    assert report.quality_gate_status == "not_evaluated"
    assert report.gate_eligible is False
    assert context["evaluation_mode"] == "calibration"

    gate = build_transition_eval_gate_report(
        review={"decision": "approve_dry_run", "allowed_next_stage": "dry_run_apply"},
        dry_run={
            "actual_write_performed": False,
            "real_patch_applied": False,
            "approved_by_review": True,
            "review_decision": "approve_dry_run",
        },
        build={"claims_real_build_success": False},
        runtime={"claims_real_runtime_success": False},
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_context=context,
        evaluation_required=True,
    )
    assert gate["status"] == "failed"


def test_precision_at_k_uses_cutoff_and_reports_returned_precision() -> None:
    case = AgentQualityCase(
        case_id="short_results",
        stratum="exact_code_lookup",
        query="q",
        expected_relevant_ids=("R1", "R2"),
        expected_hook_ids=(),
        expected_target_files=(),
        forbidden_files=(),
        expected_readiness="blocked",
        expected_control_action="block",
        task_success_eligible=False,
        expected_task_success=None,
    )
    report = AgentQualityEvaluator().evaluate(
        dataset_schema_version="1",
        dataset_version="test",
        dataset_kind="calibration",
        dataset_quality_gate_eligible=False,
        dataset_sha256="sha256:test",
        judgment_sha256="sha256:judgment",
        arm_id="short",
        cases=(case,),
        observations={
            case.case_id: CaseObservation(
                retrieval=RetrievalObservation(retrieved_ids=("R1",))
            )
        },
        run_manifest=_manifest(),
        top_k=10,
    )

    assert report.aggregate_metrics["recall_at_k"] == pytest.approx(0.5)
    assert report.aggregate_metrics["precision_at_k"] == pytest.approx(0.1)
    assert report.aggregate_metrics["precision_at_returned"] == pytest.approx(1.0)


def test_no_relevant_case_scores_empty_result_without_polluting_positive_metrics() -> None:
    case = AgentQualityCase(
        case_id="known_absence",
        stratum="exact_code_lookup",
        query="Locate an intentionally absent implementation.",
        expected_relevant_ids=(),
        expected_hook_ids=(),
        expected_target_files=(),
        forbidden_files=(),
        expected_readiness="blocked",
        expected_control_action="block",
        task_success_eligible=False,
        expected_task_success=None,
        expected_result_mode="no_relevant",
    )
    report = AgentQualityEvaluator().evaluate(
        dataset_schema_version="1",
        dataset_version="negative-test",
        dataset_kind="calibration",
        dataset_quality_gate_eligible=False,
        dataset_sha256="sha256:negative-test",
        judgment_sha256="sha256:negative-judgment",
        arm_id="negative",
        cases=(case,),
        observations={case.case_id: CaseObservation(retrieval=RetrievalObservation(retrieved_ids=()))},
        run_manifest=_manifest(),
        top_k=10,
    )

    assert report.aggregate_metrics["no_relevant_result_accuracy"] == 1.0
    assert "recall_at_k" not in report.aggregate_metrics


def test_no_relevant_case_rejects_non_empty_ground_truth() -> None:
    with pytest.raises(ValueError, match="empty expected_relevant_ids"):
        AgentQualityCase(
            case_id="invalid_absence",
            stratum="exact_code_lookup",
            query="Invalid negative case.",
            expected_relevant_ids=("file:present.py",),
            expected_hook_ids=(),
            expected_target_files=(),
            forbidden_files=(),
            expected_readiness="blocked",
            expected_control_action="block",
            task_success_eligible=False,
            expected_task_success=None,
            expected_result_mode="no_relevant",
        )


def test_duplicate_ranked_and_ground_truth_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        RetrievalObservation(retrieved_ids=("R1", "R1"))
    with pytest.raises(ValueError, match="duplicate"):
        AgentQualityCase(
            case_id="duplicate_ground_truth",
            stratum="exact",
            query="q",
            expected_relevant_ids=("R1", "R1"),
            expected_hook_ids=(),
            expected_target_files=(),
            forbidden_files=(),
            expected_readiness="blocked",
            expected_control_action="block",
            task_success_eligible=False,
            expected_task_success=None,
        )


def test_calibration_metrics_use_conditional_denominators() -> None:
    report = _report()

    assert report.aggregate_metrics["readiness_accuracy"] == pytest.approx(0.75)
    assert report.aggregate_metrics["false_continue_rate"] == pytest.approx(0.5)
    assert report.metric_details["false_continue_rate"]["applicable_case_count"] == 2
    assert report.aggregate_metrics["task_success_rate"] == pytest.approx(1.0)
    assert report.metric_details["task_success_rate"]["applicable_case_count"] == 2


def test_live_observation_rejects_nan_and_invalid_top_k() -> None:
    with pytest.raises(ValueError, match="finite"):
        RetrievalObservation(retrieved_ids=(), latency_ms=float("nan"))
    dataset = load_agent_quality_cases(FIXTURE)
    observations = load_observations(FIXTURE)
    with pytest.raises(ValueError, match="positive integer"):
        AgentQualityEvaluator().evaluate(
            dataset_schema_version=dataset.dataset_schema_version,
            dataset_version=dataset.dataset_version,
            dataset_kind=dataset.dataset_kind,
            dataset_quality_gate_eligible=dataset.quality_gate_eligible,
            dataset_sha256=dataset.dataset_sha256,
            judgment_sha256=dataset.judgment_sha256,
            arm_id="bad_k",
            cases=dataset.cases,
            observations=observations.observations,
            run_manifest=_manifest(),
            top_k=True,
        )


def test_complete_zero_quality_benchmark_fails_quality_gate() -> None:
    dataset = load_agent_quality_cases(FIXTURE)
    observations = {
        case.case_id: CaseObservation(
            retrieval=RetrievalObservation(retrieved_ids=())
        )
        for case in dataset.cases
    }
    report = AgentQualityEvaluator().evaluate(
        dataset_schema_version=dataset.dataset_schema_version,
        dataset_version="zero_quality_benchmark",
        dataset_kind="benchmark",
        dataset_quality_gate_eligible=True,
        dataset_sha256=dataset.dataset_sha256,
        judgment_sha256=dataset.judgment_sha256,
        arm_id="zero_quality",
        cases=dataset.cases,
        observations=observations,
        run_manifest=RunManifest(
            repository_revision="abc123",
            worktree_diff_sha256="sha256:diff",
            corpus_manifest_sha256="sha256:corpus",
            evaluation_protocol_sha256="sha256:protocol",
            provider_id="zero_provider",
            provider_version="1",
            evidence_status="fresh",
        ),
        quality_policy=_policy(),
    )

    assert report.completeness_status == "complete"
    assert report.gate_eligible is True
    assert report.quality_gate_status == "fail"
    gate = build_transition_eval_gate_report(
        review={"decision": "approve_dry_run", "allowed_next_stage": "dry_run_apply"},
        dry_run={
            "actual_write_performed": False,
            "real_patch_applied": False,
            "approved_by_review": True,
            "review_decision": "approve_dry_run",
        },
        build={"claims_real_build_success": False},
        runtime={"claims_real_runtime_success": False},
        v1_boundary={"v1_acceptance_status": "blocked"},
        claims_real_success=False,
        evaluation_context=report.to_dict()["evaluation_context"],
        evaluation_required=True,
    )
    assert gate["status"] == "failed"


def test_benchmark_rejects_partial_zero_or_nan_policy() -> None:
    with pytest.raises(ValueError, match="exactly cover"):
        QualityGatePolicy(
            policy_schema_version="v1",
            policy_id="partial",
            required_metric_names=("recall_at_k", "precision_at_k"),
            thresholds={"recall_at_k": 0.5},
        )
    with pytest.raises(ValueError, match="finite"):
        QualityGatePolicy(
            policy_schema_version="v1",
            policy_id="nan",
            required_metric_names=("recall_at_k",),
            thresholds={"recall_at_k": float("nan")},
        )
