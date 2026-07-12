"""Strict compatibility tests for retrieval regression reports."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.evaluation import (
    CaseObservation,
    RetrievalObservation,
    RetrievalRegressionRunner,
    RunManifest,
    compare_reports,
    load_agent_quality_cases,
    load_observations,
)

FIXTURE = Path("tests/fixtures/evaluation/agent_quality_cases.json")


def _manifest(provider: str = "fixed") -> RunManifest:
    return RunManifest(
        repository_revision="abc123",
        worktree_diff_sha256="sha256:diff",
        corpus_manifest_sha256="sha256:corpus",
        evaluation_protocol_sha256="sha256:protocol",
        provider_id=provider,
        provider_version="1",
        evidence_status="unknown",
    )


def _report(*, top_k: int = 10, omit_last: bool = False):
    dataset = load_agent_quality_cases(FIXTURE)
    loaded = load_observations(FIXTURE)
    observations = dict(loaded.observations)
    if omit_last:
        observations.pop(dataset.cases[-1].case_id)
    observation_set = replace(loaded, observations=observations)
    return RetrievalRegressionRunner().run_fixed_observations(
        dataset=dataset,
        observation_set=observation_set,
        arm_id="fixture",
        run_manifest=_manifest(),
        top_k=top_k,
    )


def test_retrieval_only_provider_does_not_require_agent_fields() -> None:
    dataset = load_agent_quality_cases(FIXTURE)
    report = RetrievalRegressionRunner().run(
        dataset=dataset,
        arm_id="retrieval_only",
        provider=lambda _case, _k: CaseObservation(
            retrieval=RetrievalObservation(retrieved_ids=())
        ),
        run_manifest=_manifest("rg_live_read"),
    )

    assert "readiness_accuracy" not in report.aggregate_metrics
    assert report.completeness_status == "complete"


def test_provider_must_return_case_observation() -> None:
    dataset = load_agent_quality_cases(FIXTURE)
    with pytest.raises(TypeError, match="CaseObservation"):
        RetrievalRegressionRunner().run(
            dataset=dataset,
            arm_id="invalid_provider",
            provider=lambda _case, _k: RetrievalObservation(retrieved_ids=()),  # type: ignore[arg-type,return-value]
            run_manifest=_manifest("invalid"),
        )


def test_observation_dataset_hash_must_match_cases() -> None:
    dataset = load_agent_quality_cases(FIXTURE)
    loaded = load_observations(FIXTURE)
    with pytest.raises(ValueError, match="dataset_sha256"):
        RetrievalRegressionRunner().run_fixed_observations(
            dataset=dataset,
            observation_set=replace(loaded, dataset_sha256="sha256:different"),
            arm_id="mismatched",
            run_manifest=_manifest(),
        )


def test_comparator_rejects_different_top_k() -> None:
    with pytest.raises(ValueError, match="top_k"):
        compare_reports(_report(top_k=1), _report(top_k=10), metric_names=("recall_at_k",))


def test_comparator_rejects_incomplete_report() -> None:
    with pytest.raises(ValueError, match="complete"):
        compare_reports(_report(), _report(omit_last=True), metric_names=("recall_at_k",))


def test_comparison_records_metric_direction() -> None:
    comparison = compare_reports(
        _report(),
        _report(),
        metric_names=("recall_at_k", "false_continue_rate"),
    )

    assert comparison["comparisons"]["recall_at_k"]["higher_is_better"] is True
    assert comparison["comparisons"]["false_continue_rate"]["higher_is_better"] is False
    assert comparison["comparisons"]["false_continue_rate"]["normalized_improvement"] == 0
    assert comparison["comparison_status"] == "calibration_complete"


def test_benchmark_mode_rejects_calibration_reports() -> None:
    with pytest.raises(ValueError, match="fresh benchmark"):
        compare_reports(
            _report(), _report(), metric_names=("recall_at_k",),
            comparison_mode="benchmark_measurement",
        )


def test_comparator_rejects_different_metric_populations() -> None:
    baseline = _report()
    treatment = _report()
    details = {name: dict(value) for name, value in treatment.metric_details.items()}
    details["recall_at_k"]["applicable_case_ids"] = details["recall_at_k"][
        "applicable_case_ids"
    ][:-1]
    treatment = replace(treatment, metric_details=details)
    with pytest.raises(ValueError, match="applicable_case_ids"):
        compare_reports(baseline, treatment, metric_names=("recall_at_k",))


def test_promotion_comparison_rejects_smoke_scope() -> None:
    report = replace(
        _report(),
        dataset_kind="benchmark",
        evidence_status="fresh",
        quality_gate_status="pass",
        gate_eligible=True,
        benchmark_scope="smoke",
        promotion_eligible=False,
    )
    with pytest.raises(ValueError, match="held-out"):
        compare_reports(
            report,
            report,
            metric_names=("recall_at_k",),
            comparison_mode="promotion",
        )
