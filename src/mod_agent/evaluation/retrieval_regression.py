"""Versioned dataset loading, observation execution, and strict report comparison."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .agent_quality import (
    METRIC_DIRECTIONS,
    AgentDecisionObservation,
    AgentQualityCase,
    AgentQualityEvaluator,
    AgentQualityReport,
    CaseObservation,
    EvaluationMode,
    RetrievalObservation,
    RunManifest,
)
from .quality_policy import QualityGatePolicy

ObservationProvider = Callable[[AgentQualityCase, int], CaseObservation]


@dataclass(frozen=True)
class VersionedAgentQualityCases:
    dataset_schema_version: str
    dataset_version: str
    dataset_kind: EvaluationMode
    quality_gate_eligible: bool
    dataset_sha256: str
    judgment_sha256: str
    cases: tuple[AgentQualityCase, ...]
    benchmark_scope: str = "calibration"
    claim_scope: str = "evaluator_calibration"
    promotion_eligible: bool = False


@dataclass(frozen=True)
class VersionedObservations:
    observation_schema_version: str
    dataset_version: str
    dataset_sha256: str
    observation_envelope_sha256: str
    observations: Mapping[str, CaseObservation]


def load_agent_quality_cases(path: str | Path) -> VersionedAgentQualityCases:
    source = Path(path)
    data = _load_object(source, "evaluation case")
    schema = _required_string(data, "dataset_schema_version")
    version = _required_string(data, "dataset_version")
    kind = _required_string(data, "dataset_kind")
    if kind not in {"calibration", "benchmark"}:
        raise ValueError("dataset_kind must be calibration or benchmark")
    eligible = data.get("quality_gate_eligible")
    if not isinstance(eligible, bool):
        raise ValueError("quality_gate_eligible must be boolean")
    if kind == "calibration" and eligible:
        raise ValueError("calibration datasets cannot be quality-gate eligible")
    default_scope = "calibration" if kind == "calibration" else "development"
    default_claim_scope = (
        "evaluator_calibration" if kind == "calibration" else "benchmark_measurement_only"
    )
    benchmark_scope = data.get("benchmark_scope", default_scope)
    claim_scope = data.get("claim_scope", default_claim_scope)
    promotion_eligible = data.get("promotion_eligible", False)
    if benchmark_scope not in {"calibration", "smoke", "development", "held_out"}:
        raise ValueError("invalid benchmark_scope")
    if not isinstance(claim_scope, str) or not claim_scope.strip():
        raise ValueError("claim_scope must be a non-empty string")
    if not isinstance(promotion_eligible, bool):
        raise ValueError("promotion_eligible must be boolean")
    if benchmark_scope != "held_out" and promotion_eligible:
        raise ValueError("only held_out datasets can be promotion eligible")
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("evaluation case file requires a non-empty cases list")
    cases = tuple(AgentQualityCase.from_mapping(item) for item in raw_cases if isinstance(item, Mapping))
    if len(cases) != len(raw_cases):
        raise ValueError("every evaluation case must be a JSON object")
    ids = tuple(case.case_id for case in cases)
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case_id values must be unique")
    canonical_dataset = {
        key: value
        for key, value in data.items()
        if key not in {"observations", "observation_schema_version", "dataset_sha256"}
    }
    return VersionedAgentQualityCases(
        dataset_schema_version=schema,
        dataset_version=version,
        dataset_kind=kind,  # type: ignore[arg-type]
        quality_gate_eligible=eligible,
        dataset_sha256=_sha256(canonical_dataset),
        judgment_sha256=_sha256(raw_cases),
        cases=cases,
        benchmark_scope=benchmark_scope,
        claim_scope=claim_scope,
        promotion_eligible=promotion_eligible,
    )


def load_observations(path: str | Path) -> VersionedObservations:
    data = _load_object(Path(path), "observation")
    schema = _required_string(data, "observation_schema_version")
    dataset_version = _required_string(data, "dataset_version")
    dataset_sha256 = _required_string(data, "dataset_sha256")
    raw = data.get("observations")
    if not isinstance(raw, list) or not raw:
        raise ValueError("observation file requires a non-empty observations list")
    observations: dict[str, CaseObservation] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("every observation must be a JSON object")
        case_id = _required_string(item, "case_id")
        if case_id in observations:
            raise ValueError(f"duplicate observation case_id: {case_id}")
        retrieval = item.get("retrieval")
        decision = item.get("decision")
        if not isinstance(retrieval, Mapping):
            raise ValueError(f"observation {case_id!r} requires retrieval object")
        if decision is not None and not isinstance(decision, Mapping):
            raise ValueError(f"observation {case_id!r} decision must be object or null")
        observations[case_id] = CaseObservation(
            retrieval=RetrievalObservation.from_mapping(retrieval),
            decision=(AgentDecisionObservation.from_mapping(decision) if decision else None),
        )
    return VersionedObservations(
        observation_schema_version=schema,
        dataset_version=dataset_version,
        dataset_sha256=dataset_sha256,
        observation_envelope_sha256=_sha256(raw),
        observations=observations,
    )


class RetrievalRegressionRunner:
    def __init__(self, evaluator: AgentQualityEvaluator | None = None) -> None:
        self.evaluator = evaluator or AgentQualityEvaluator()

    def run(
        self,
        *,
        dataset: VersionedAgentQualityCases,
        arm_id: str,
        provider: ObservationProvider,
        run_manifest: RunManifest,
        top_k: int = 10,
        quality_policy: QualityGatePolicy | None = None,
    ) -> AgentQualityReport:
        observations: dict[str, CaseObservation] = {}
        for case in dataset.cases:
            observed = provider(case, top_k)
            if not isinstance(observed, CaseObservation):
                raise TypeError("observation provider must return CaseObservation")
            observations[case.case_id] = observed
        return self._evaluate(
            dataset,
            arm_id,
            observations,
            run_manifest,
            top_k,
            quality_policy,
            observation_schema_version="provider_observation_v1",
            observation_envelope_sha256=None,
        )

    def run_fixed_observations(
        self,
        *,
        dataset: VersionedAgentQualityCases,
        observation_set: VersionedObservations,
        arm_id: str,
        run_manifest: RunManifest,
        top_k: int = 10,
        quality_policy: QualityGatePolicy | None = None,
    ) -> AgentQualityReport:
        if observation_set.dataset_version != dataset.dataset_version:
            raise ValueError("observation dataset_version does not match cases")
        if observation_set.dataset_sha256 != dataset.dataset_sha256:
            raise ValueError("observation dataset_sha256 does not match cases")
        return self._evaluate(
            dataset,
            arm_id,
            observation_set.observations,
            run_manifest,
            top_k,
            quality_policy,
            observation_schema_version=observation_set.observation_schema_version,
            observation_envelope_sha256=observation_set.observation_envelope_sha256,
        )

    def _evaluate(
        self,
        dataset: VersionedAgentQualityCases,
        arm_id: str,
        observations: Mapping[str, CaseObservation],
        manifest: RunManifest,
        top_k: int,
        quality_policy: QualityGatePolicy | None,
        *,
        observation_schema_version: str,
        observation_envelope_sha256: str | None,
    ) -> AgentQualityReport:
        return self.evaluator.evaluate(
            dataset_schema_version=dataset.dataset_schema_version,
            dataset_version=dataset.dataset_version,
            dataset_kind=dataset.dataset_kind,
            dataset_quality_gate_eligible=dataset.quality_gate_eligible,
            dataset_sha256=dataset.dataset_sha256,
            judgment_sha256=dataset.judgment_sha256,
            arm_id=arm_id,
            cases=dataset.cases,
            observations=observations,
            run_manifest=manifest,
            observation_schema_version=observation_schema_version,
            observation_envelope_sha256=observation_envelope_sha256,
            top_k=top_k,
            quality_policy=quality_policy,
            benchmark_scope=dataset.benchmark_scope,
            claim_scope=dataset.claim_scope,
            promotion_eligible=dataset.promotion_eligible,
        )


def compare_reports(
    baseline: AgentQualityReport,
    treatment: AgentQualityReport,
    *,
    metric_names: Sequence[str],
    comparison_mode: Literal["calibration", "benchmark_measurement", "promotion"] = "calibration",
) -> dict[str, Any]:
    if comparison_mode not in {"calibration", "benchmark_measurement", "promotion"}:
        raise ValueError("invalid comparison_mode")
    compatibility = {
        "dataset_schema_version": (baseline.dataset_schema_version, treatment.dataset_schema_version),
        "dataset_version": (baseline.dataset_version, treatment.dataset_version),
        "dataset_kind": (baseline.dataset_kind, treatment.dataset_kind),
        "dataset_sha256": (baseline.dataset_sha256, treatment.dataset_sha256),
        "judgment_sha256": (baseline.judgment_sha256, treatment.judgment_sha256),
        "case_ids": (baseline.case_ids, treatment.case_ids),
        "evaluator_schema_version": (baseline.evaluator_schema_version, treatment.evaluator_schema_version),
        "metric_schema_version": (baseline.metric_schema_version, treatment.metric_schema_version),
        "observation_schema_version": (baseline.observation_schema_version, treatment.observation_schema_version),
        "top_k": (baseline.top_k, treatment.top_k),
        "repository_revision": (baseline.run_manifest.repository_revision, treatment.run_manifest.repository_revision),
        "worktree_diff_sha256": (baseline.run_manifest.worktree_diff_sha256, treatment.run_manifest.worktree_diff_sha256),
        "corpus_manifest_sha256": (baseline.run_manifest.corpus_manifest_sha256, treatment.run_manifest.corpus_manifest_sha256),
        "evaluation_protocol_sha256": (baseline.run_manifest.evaluation_protocol_sha256, treatment.run_manifest.evaluation_protocol_sha256),
        "percentile_method": (baseline.run_manifest.percentile_method, treatment.run_manifest.percentile_method),
    }
    mismatches = [name for name, values in compatibility.items() if values[0] != values[1]]
    if mismatches:
        raise ValueError(f"reports are not comparable: {', '.join(mismatches)}")
    for report in (baseline, treatment):
        if report.completeness_status != "complete" or report.execution_status != "completed":
            raise ValueError("reports must be complete and successfully executed")
    if comparison_mode != "calibration":
        for report in (baseline, treatment):
            if report.dataset_kind != "benchmark" or report.evidence_status != "fresh":
                raise ValueError("benchmark comparison requires fresh benchmark reports")
    if comparison_mode == "promotion":
        for report in (baseline, treatment):
            if report.quality_gate_status != "pass" or not report.gate_eligible:
                raise ValueError("promotion comparison requires passing gate-eligible reports")
            if not report.promotion_eligible or report.benchmark_scope != "held_out":
                raise ValueError("promotion comparison requires held-out promotion-eligible reports")
        if baseline.quality_policy is None or treatment.quality_policy is None:
            raise ValueError("promotion comparison requires quality policies")
        if baseline.quality_policy.policy_sha256 != treatment.quality_policy.policy_sha256:
            raise ValueError("promotion comparison requires identical quality policies")
    comparisons: dict[str, Any] = {}
    for metric in metric_names:
        base = baseline.aggregate_metrics.get(metric)
        treated = treatment.aggregate_metrics.get(metric)
        if base is None or treated is None:
            raise ValueError(f"required comparison metric is missing: {metric}")
        base_ids = tuple(baseline.metric_details.get(metric, {}).get("applicable_case_ids", ()))
        treated_ids = tuple(treatment.metric_details.get(metric, {}).get("applicable_case_ids", ()))
        if base_ids != treated_ids:
            raise ValueError(f"metric applicable_case_ids mismatch: {metric}")
        delta = treated - base
        higher = METRIC_DIRECTIONS.get(metric, True)
        comparisons[metric] = {
            "baseline": base,
            "treatment": treated,
            "absolute_delta": delta,
            "percentage_point_delta": delta * 100.0,
            "relative_change": None if base == 0 else delta / abs(base),
            "higher_is_better": higher,
            "normalized_improvement": delta if higher else -delta,
        }
    cost_comparisons: dict[str, Any] = {}
    for metric in (
        "latency_ms_mean",
        "latency_ms_p50",
        "latency_ms_p95",
        "api_calls_total",
        "input_tokens_total",
        "output_tokens_total",
        "monetary_cost_total",
    ):
        base = baseline.cost_summary.get(metric)
        treated = treatment.cost_summary.get(metric)
        if not isinstance(base, (int, float)) or not isinstance(treated, (int, float)):
            continue
        delta = float(treated) - float(base)
        cost_comparisons[metric] = {
            "baseline": base,
            "treatment": treated,
            "absolute_delta": delta,
            "relative_change": None if base == 0 else delta / abs(float(base)),
            "higher_is_better": False,
            "normalized_improvement": -delta,
        }
    return {
        "dataset_version": baseline.dataset_version,
        "baseline_arm_id": baseline.arm_id,
        "treatment_arm_id": treatment.arm_id,
        "comparisons": comparisons,
        "cost_comparisons": cost_comparisons,
        "comparison_mode": comparison_mode,
        "comparison_status": (
            "calibration_complete" if comparison_mode == "calibration" else "complete"
        ),
    }


def _load_object(path: Path, label: str) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} file not found: {path}")
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-standard JSON numeric constant: {token}")
        ),
    )
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} file must contain a JSON object")
    return value


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return result
