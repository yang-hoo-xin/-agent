"""Deterministic metrics and status contracts for controlled-agent evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .quality_policy import QualityGatePolicy, evaluate_quality_policy

Readiness = Literal["sufficient", "partial", "blocked"]
ControlAction = Literal["continue", "block"]
EvaluationMode = Literal["calibration", "benchmark"]
ExpectedResultMode = Literal["relevant", "no_relevant"]

EVALUATOR_SCHEMA_VERSION = "controlled_agent_evaluator_v2"
METRIC_SCHEMA_VERSION = "controlled_agent_metrics_v2"

REQUIRED_RETRIEVAL_METRICS = (
    "recall_at_k",
    "precision_at_k",
    "precision_at_returned",
    "mrr_at_k",
)

METRIC_DIRECTIONS: dict[str, bool] = {
    "recall_at_k": True,
    "precision_at_k": True,
    "precision_at_returned": True,
    "mrr_at_k": True,
    "no_relevant_result_accuracy": True,
    "hook_recall_at_k": True,
    "selected_hook_accuracy": True,
    "readiness_accuracy": True,
    "continuation_decision_accuracy": True,
    "task_success_rate": True,
    "expected_task_outcome_match_rate": True,
    "target_file_precision": True,
    "target_file_recall": True,
    "exact_target_set_match_rate": True,
    "unexpected_file_rate": False,
    "forbidden_file_violation_rate": False,
    "no_modification_rate": False,
    "false_continue_rate": False,
    "false_block_rate": False,
}


@dataclass(frozen=True)
class AgentQualityCase:
    case_id: str
    stratum: str
    query: str
    expected_relevant_ids: tuple[str, ...]
    expected_hook_ids: tuple[str, ...]
    expected_target_files: tuple[str, ...]
    forbidden_files: tuple[str, ...]
    expected_readiness: Readiness
    expected_control_action: ControlAction
    task_success_eligible: bool
    expected_task_success: bool | None
    expected_result_mode: ExpectedResultMode = "relevant"
    expected_source_types: tuple[str, ...] = ()
    expected_source_spans: tuple[str, ...] = ()
    community_evidence_required: bool = False
    structural_prerequisites: tuple[str, ...] = ()
    mutation_scenario_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.case_id, "case_id")
        _require_non_empty(self.stratum, "stratum")
        _require_non_empty(self.query, "query")
        if self.expected_result_mode not in {"relevant", "no_relevant"}:
            raise ValueError("invalid expected_result_mode")
        _require_unique_strings(
            self.expected_relevant_ids,
            "expected_relevant_ids",
            required=self.expected_result_mode == "relevant",
        )
        if self.expected_result_mode == "no_relevant" and self.expected_relevant_ids:
            raise ValueError("no_relevant cases require empty expected_relevant_ids")
        _require_unique_strings(self.expected_hook_ids, "expected_hook_ids")
        _require_canonical_paths(self.expected_target_files, "expected_target_files")
        _require_canonical_paths(self.forbidden_files, "forbidden_files")
        if self.expected_readiness not in {"sufficient", "partial", "blocked"}:
            raise ValueError("invalid expected_readiness")
        if self.expected_control_action not in {"continue", "block"}:
            raise ValueError("invalid expected_control_action")
        if type(self.task_success_eligible) is not bool:
            raise ValueError("task_success_eligible must be boolean")
        if self.expected_task_success is not None and type(self.expected_task_success) is not bool:
            raise ValueError("expected_task_success must be boolean or null")
        if self.task_success_eligible and self.expected_task_success is None:
            raise ValueError("task-success eligible cases require expected_task_success")
        if not self.task_success_eligible and self.expected_task_success is not None:
            raise ValueError("task-success ineligible cases require expected_task_success=null")
        _require_unique_strings(self.expected_source_types, "expected_source_types")
        _require_unique_strings(self.expected_source_spans, "expected_source_spans")
        if type(self.community_evidence_required) is not bool:
            raise ValueError("community_evidence_required must be boolean")
        _require_unique_strings(self.structural_prerequisites, "structural_prerequisites")
        _require_unique_strings(self.mutation_scenario_ids, "mutation_scenario_ids")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AgentQualityCase:
        expected = value.get("expected_task_success")
        if expected is not None and not isinstance(expected, bool):
            raise ValueError("expected_task_success must be boolean or null")
        return cls(
            case_id=_required_string(value, "case_id"),
            stratum=_required_string(value, "stratum"),
            query=_required_string(value, "query"),
            expected_relevant_ids=_string_tuple(value.get("expected_relevant_ids")),
            expected_hook_ids=_string_tuple(value.get("expected_hook_ids")),
            expected_target_files=_string_tuple(value.get("expected_target_files")),
            forbidden_files=_string_tuple(value.get("forbidden_files")),
            expected_readiness=_required_string(value, "expected_readiness"),  # type: ignore[arg-type]
            expected_control_action=_required_string(value, "expected_control_action"),  # type: ignore[arg-type]
            task_success_eligible=_required_bool(value, "task_success_eligible"),
            expected_task_success=expected,
            expected_result_mode=value.get("expected_result_mode", "relevant"),  # type: ignore[arg-type]
            expected_source_types=_string_tuple(value.get("expected_source_types")),
            expected_source_spans=_string_tuple(value.get("expected_source_spans")),
            community_evidence_required=value.get("community_evidence_required", False),
            structural_prerequisites=_string_tuple(value.get("structural_prerequisites")),
            mutation_scenario_ids=_string_tuple(value.get("mutation_scenario_ids")),
        )


@dataclass(frozen=True)
class RankedRetrievalResult:
    result_id: str
    relative_path: str
    line_number: int
    matched_text: str
    file_sha256: str
    source: str = "rg_live_read"

    def __post_init__(self) -> None:
        _require_non_empty(self.result_id, "result_id")
        _require_non_empty(self.relative_path, "relative_path")
        if "\\" in self.relative_path or self.relative_path.startswith("/"):
            raise ValueError("relative_path must be canonical workspace-relative POSIX path")
        if self.result_id != f"file:{self.relative_path}":
            raise ValueError("result_id must equal file:<relative_path>")
        if not isinstance(self.line_number, int) or isinstance(self.line_number, bool) or self.line_number <= 0:
            raise ValueError("line_number must be a positive integer")
        _require_non_empty(self.matched_text, "matched_text")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.file_sha256) is None:
            raise ValueError("file_sha256 must be a canonical SHA-256 value")
        _require_non_empty(self.source, "source")
        if self.source != "rg_live_read":
            raise ValueError("ranked retrieval source must be rg_live_read")


@dataclass(frozen=True)
class RetrievalObservation:
    retrieved_ids: tuple[str, ...]
    retrieved_hook_ids: tuple[str, ...] = ()
    ranked_results: tuple[RankedRetrievalResult, ...] = ()
    latency_ms: float = 0.0
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    monetary_cost: float = 0.0

    def __post_init__(self) -> None:
        _require_unique_strings(self.retrieved_ids, "retrieved_ids")
        _require_unique_strings(self.retrieved_hook_ids, "retrieved_hook_ids")
        ranked_ids = tuple(result.result_id for result in self.ranked_results)
        _require_unique_strings(ranked_ids, "ranked_results.result_id")
        if ranked_ids and ranked_ids != self.retrieved_ids:
            raise ValueError("ranked_results result IDs must exactly match retrieved_ids")
        _require_non_negative_finite(self.latency_ms, "latency_ms")
        _require_non_negative_int(self.api_calls, "api_calls")
        _require_non_negative_int(self.input_tokens, "input_tokens")
        _require_non_negative_int(self.output_tokens, "output_tokens")
        _require_non_negative_finite(self.monetary_cost, "monetary_cost")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RetrievalObservation:
        return cls(
            retrieved_ids=_string_tuple(value.get("retrieved_ids")),
            retrieved_hook_ids=_string_tuple(value.get("retrieved_hook_ids")),
            ranked_results=_ranked_results(value.get("ranked_results")),
            latency_ms=_number(value.get("latency_ms", 0.0), "latency_ms"),
            api_calls=_integer(value.get("api_calls", 0), "api_calls"),
            input_tokens=_integer(value.get("input_tokens", 0), "input_tokens"),
            output_tokens=_integer(value.get("output_tokens", 0), "output_tokens"),
            monetary_cost=_number(value.get("monetary_cost", 0.0), "monetary_cost"),
        )


@dataclass(frozen=True)
class AgentDecisionObservation:
    selected_hook_id: str | None
    supporting_hook_ids: tuple[str, ...]
    proposed_files: tuple[str, ...]
    readiness: Readiness
    can_generate_patch: bool
    task_success: bool | None

    def __post_init__(self) -> None:
        if self.selected_hook_id is not None:
            _require_non_empty(self.selected_hook_id, "selected_hook_id")
        _require_unique_strings(self.supporting_hook_ids, "supporting_hook_ids")
        _require_canonical_paths(self.proposed_files, "proposed_files")
        if self.readiness not in {"sufficient", "partial", "blocked"}:
            raise ValueError("invalid readiness")
        if type(self.can_generate_patch) is not bool:
            raise ValueError("can_generate_patch must be boolean")
        if self.task_success is not None and type(self.task_success) is not bool:
            raise ValueError("task_success must be boolean or null")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AgentDecisionObservation:
        task_success = value.get("task_success")
        if task_success is not None and not isinstance(task_success, bool):
            raise ValueError("task_success must be boolean or null")
        return cls(
            selected_hook_id=_optional_string(value.get("selected_hook_id")),
            supporting_hook_ids=_string_tuple(value.get("supporting_hook_ids")),
            proposed_files=_string_tuple(value.get("proposed_files")),
            readiness=_required_string(value, "readiness"),  # type: ignore[arg-type]
            can_generate_patch=_required_bool(value, "can_generate_patch"),
            task_success=task_success,
        )


@dataclass(frozen=True)
class CaseObservation:
    retrieval: RetrievalObservation
    decision: AgentDecisionObservation | None = None


@dataclass(frozen=True)
class RunManifest:
    repository_revision: str
    worktree_diff_sha256: str
    corpus_manifest_sha256: str
    evaluation_protocol_sha256: str
    provider_id: str
    provider_version: str
    evidence_status: str
    percentile_method: str = "nearest_rank"

    def __post_init__(self) -> None:
        for field in (
            "repository_revision",
            "worktree_diff_sha256",
            "corpus_manifest_sha256",
            "evaluation_protocol_sha256",
            "provider_id",
            "provider_version",
        ):
            _require_non_empty(getattr(self, field), field)
        if self.evidence_status not in {"fresh", "unknown", "stale"}:
            raise ValueError("invalid evidence_status")
        if self.percentile_method != "nearest_rank":
            raise ValueError("percentile_method must be nearest_rank")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class AgentQualityReport:
    dataset_schema_version: str
    dataset_version: str
    dataset_kind: EvaluationMode
    dataset_quality_gate_eligible: bool
    dataset_sha256: str
    judgment_sha256: str
    observation_schema_version: str
    observation_envelope_sha256: str
    normalized_observations_sha256: str
    case_ids: tuple[str, ...]
    arm_id: str
    top_k: int
    completeness_status: str
    execution_status: str
    evidence_status: str
    quality_gate_status: str
    gate_eligible: bool
    aggregate_metrics: Mapping[str, float]
    metric_details: Mapping[str, Mapping[str, Any]]
    cost_summary: Mapping[str, float | int | str]
    case_results: tuple[Mapping[str, Any], ...]
    raw_observations: Mapping[str, Mapping[str, Any]]
    missing_case_ids: tuple[str, ...]
    run_manifest: RunManifest
    quality_policy: QualityGatePolicy | None
    benchmark_scope: str = "calibration"
    claim_scope: str = "evaluator_calibration"
    promotion_eligible: bool = False
    evaluator_schema_version: str = EVALUATOR_SCHEMA_VERSION
    metric_schema_version: str = METRIC_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        required_metrics = list(REQUIRED_RETRIEVAL_METRICS)
        return {
            "dataset_schema_version": self.dataset_schema_version,
            "dataset_version": self.dataset_version,
            "dataset_kind": self.dataset_kind,
            "dataset_quality_gate_eligible": self.dataset_quality_gate_eligible,
            "dataset_sha256": self.dataset_sha256,
            "judgment_sha256": self.judgment_sha256,
            "observation_schema_version": self.observation_schema_version,
            "observation_envelope_sha256": self.observation_envelope_sha256,
            "normalized_observations_sha256": self.normalized_observations_sha256,
            "case_ids": list(self.case_ids),
            "arm_id": self.arm_id,
            "top_k": self.top_k,
            "completeness_status": self.completeness_status,
            "execution_status": self.execution_status,
            "evidence_status": self.evidence_status,
            "quality_gate_status": self.quality_gate_status,
            "gate_eligible": self.gate_eligible,
            "evaluator_schema_version": self.evaluator_schema_version,
            "metric_schema_version": self.metric_schema_version,
            "required_metrics": required_metrics,
            "aggregate_metrics": dict(self.aggregate_metrics),
            "metric_details": {key: dict(value) for key, value in self.metric_details.items()},
            "cost_summary": dict(self.cost_summary),
            "case_results": [dict(result) for result in self.case_results],
            "raw_observations": {key: dict(value) for key, value in self.raw_observations.items()},
            "missing_case_ids": list(self.missing_case_ids),
            "run_manifest": self.run_manifest.to_dict(),
            "quality_policy": self.quality_policy.to_dict() if self.quality_policy else None,
            "benchmark_scope": self.benchmark_scope,
            "claim_scope": self.claim_scope,
            "promotion_eligible": self.promotion_eligible,
            "evaluation_context": {
                "evaluation_required": True,
                "evaluation_mode": self.dataset_kind,
                "completeness_status": self.completeness_status,
                "execution_status": self.execution_status,
                "evidence_status": self.evidence_status,
                "quality_gate_status": self.quality_gate_status,
                "gate_eligible": self.gate_eligible,
                "required_metrics": required_metrics,
                "metrics": dict(self.aggregate_metrics),
                "quality_policy": self.quality_policy.to_dict() if self.quality_policy else None,
            },
        }


class AgentQualityEvaluator:
    def evaluate(
        self,
        *,
        dataset_schema_version: str,
        dataset_version: str,
        dataset_kind: EvaluationMode,
        dataset_quality_gate_eligible: bool,
        dataset_sha256: str,
        judgment_sha256: str,
        arm_id: str,
        cases: Sequence[AgentQualityCase],
        observations: Mapping[str, CaseObservation],
        run_manifest: RunManifest,
        observation_schema_version: str = "provider_observation_v1",
        observation_envelope_sha256: str | None = None,
        top_k: int = 10,
        quality_policy: QualityGatePolicy | None = None,
        benchmark_scope: str = "calibration",
        claim_scope: str = "evaluator_calibration",
        promotion_eligible: bool = False,
    ) -> AgentQualityReport:
        _require_non_empty(dataset_schema_version, "dataset_schema_version")
        _require_non_empty(dataset_version, "dataset_version")
        _require_non_empty(dataset_sha256, "dataset_sha256")
        _require_non_empty(judgment_sha256, "judgment_sha256")
        _require_non_empty(arm_id, "arm_id")
        _require_non_empty(observation_schema_version, "observation_schema_version")
        if benchmark_scope not in {"calibration", "smoke", "development", "held_out"}:
            raise ValueError("invalid benchmark_scope")
        _require_non_empty(claim_scope, "claim_scope")
        if not isinstance(promotion_eligible, bool):
            raise ValueError("promotion_eligible must be boolean")
        if benchmark_scope != "held_out" and promotion_eligible:
            raise ValueError("only held_out reports can be promotion eligible")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        if not cases:
            raise ValueError("evaluation cases must not be empty")
        if dataset_kind == "benchmark":
            if quality_policy is None:
                raise ValueError("benchmark runs require quality_policy")
            if not set(REQUIRED_RETRIEVAL_METRICS) <= set(quality_policy.required_metric_names):
                raise ValueError("quality_policy must cover required retrieval metrics")
            if any(float(quality_policy.thresholds[name]) <= 0 for name in REQUIRED_RETRIEVAL_METRICS):
                raise ValueError("required retrieval metric thresholds must be greater than zero")
            if run_manifest.evidence_status != "fresh":
                raise ValueError("benchmark runs require fresh evidence")
            for field in (
                "worktree_diff_sha256",
                "corpus_manifest_sha256",
                "evaluation_protocol_sha256",
            ):
                if not getattr(run_manifest, field).startswith("sha256:"):
                    raise ValueError(f"benchmark run requires hashed {field}")
            if run_manifest.repository_revision in {"unknown", "calibration-unbound"}:
                raise ValueError("benchmark run requires repository_revision")
        _require_unique_strings(tuple(case.case_id for case in cases), "case_ids", required=True)
        extra = set(observations) - {case.case_id for case in cases}
        if extra:
            raise ValueError(f"unexpected observation case_id values: {', '.join(sorted(extra))}")

        results: list[Mapping[str, Any]] = []
        raw: dict[str, Mapping[str, Any]] = {}
        missing: list[str] = []
        for case in cases:
            observation = observations.get(case.case_id)
            if observation is None:
                missing.append(case.case_id)
                continue
            result = _evaluate_case(case, observation, top_k)
            results.append(result)
            raw[case.case_id] = _raw_observation(observation)
        aggregate, details = _aggregate(results)
        completeness = "complete" if not missing else "incomplete"
        execution = "completed"
        gate_eligible = bool(
            dataset_kind == "benchmark"
            and dataset_quality_gate_eligible
            and completeness == "complete"
            and run_manifest.evidence_status == "fresh"
            and quality_policy is not None
        )
        quality_status = (
            evaluate_quality_policy(quality_policy, aggregate, METRIC_DIRECTIONS)
            if gate_eligible and quality_policy is not None
            else "not_evaluated"
        )
        normalized_hash = _sha256(raw)
        return AgentQualityReport(
            dataset_schema_version=dataset_schema_version,
            dataset_version=dataset_version,
            dataset_kind=dataset_kind,
            dataset_quality_gate_eligible=dataset_quality_gate_eligible,
            dataset_sha256=dataset_sha256,
            judgment_sha256=judgment_sha256,
            observation_schema_version=observation_schema_version,
            observation_envelope_sha256=observation_envelope_sha256 or normalized_hash,
            normalized_observations_sha256=normalized_hash,
            case_ids=tuple(case.case_id for case in cases),
            arm_id=arm_id,
            top_k=top_k,
            completeness_status=completeness,
            execution_status=execution,
            evidence_status=run_manifest.evidence_status,
            quality_gate_status=quality_status,
            gate_eligible=gate_eligible,
            aggregate_metrics=aggregate,
            metric_details=details,
            cost_summary=_cost_summary(tuple(item.retrieval for item in observations.values())),
            case_results=tuple(results),
            raw_observations=raw,
            missing_case_ids=tuple(missing),
            run_manifest=run_manifest,
            quality_policy=quality_policy,
            benchmark_scope=benchmark_scope,
            claim_scope=claim_scope,
            promotion_eligible=promotion_eligible,
        )


def _evaluate_case(case: AgentQualityCase, observation: CaseObservation, top_k: int) -> dict[str, Any]:
    retrieved = observation.retrieval.retrieved_ids[:top_k]
    expected = set(case.expected_relevant_ids)
    hits = set(retrieved) & expected
    if case.expected_result_mode == "no_relevant":
        metrics: dict[str, float | None] = {
            "recall_at_k": None,
            "precision_at_k": None,
            "precision_at_returned": None,
            "mrr_at_k": None,
            "no_relevant_result_accuracy": float(not retrieved),
        }
    else:
        metrics = {
            "recall_at_k": len(hits) / len(expected),
            "precision_at_k": len(hits) / top_k,
            "precision_at_returned": len(hits) / len(retrieved) if retrieved else 0.0,
            "mrr_at_k": next(
                (1.0 / rank for rank, item in enumerate(retrieved, 1) if item in expected),
                0.0,
            ),
            "no_relevant_result_accuracy": None,
        }
    expected_hooks = set(case.expected_hook_ids)
    retrieved_hooks = set(observation.retrieval.retrieved_hook_ids[:top_k])
    metrics["hook_recall_at_k"] = (
        len(retrieved_hooks & expected_hooks) / len(expected_hooks) if expected_hooks else None
    )
    decision = observation.decision
    if decision is not None:
        if decision.selected_hook_id and decision.selected_hook_id not in decision.supporting_hook_ids:
            raise ValueError(f"case {case.case_id!r} selected Hook lacks supporting Hook provenance")
        if not set(decision.supporting_hook_ids) <= retrieved_hooks:
            raise ValueError(f"case {case.case_id!r} supporting Hook was not retrieved")
        selected_correct = bool(expected_hooks and decision.selected_hook_id in expected_hooks)
        proposed = set(decision.proposed_files)
        expected_files = set(case.expected_target_files)
        metrics.update(
            {
                "selected_hook_accuracy": float(selected_correct) if expected_hooks else None,
                "readiness_accuracy": float(decision.readiness == case.expected_readiness),
                "continuation_decision_accuracy": float(
                    decision.can_generate_patch == (case.expected_control_action == "continue")
                ),
                "false_continue": (
                    float(decision.can_generate_patch)
                    if case.expected_control_action == "block"
                    else None
                ),
                "false_block": (
                    float(not decision.can_generate_patch)
                    if case.expected_control_action == "continue"
                    else None
                ),
                "target_file_precision": (
                    len(proposed & expected_files) / len(proposed) if proposed else None
                ),
                "target_file_recall": (
                    len(proposed & expected_files) / len(expected_files) if expected_files else None
                ),
                "exact_target_set_match": float(proposed == expected_files) if expected_files else None,
                "unexpected_file": float(bool(proposed - expected_files)) if proposed else None,
                "forbidden_file_violation": (
                    float(bool(proposed & set(case.forbidden_files))) if proposed else None
                ),
                "no_modification": float(not proposed),
                "task_success": (
                    float(decision.task_success)
                    if case.task_success_eligible and decision.task_success is not None
                    else None
                ),
                "expected_task_outcome_match": (
                    float(decision.task_success == case.expected_task_success)
                    if case.expected_task_success is not None and decision.task_success is not None
                    else None
                ),
            }
        )
    return {"case_id": case.case_id, "stratum": case.stratum, "metrics": metrics}


def _aggregate(results: Sequence[Mapping[str, Any]]) -> tuple[dict[str, float], dict[str, Mapping[str, Any]]]:
    mapping = {
        "recall_at_k": "recall_at_k",
        "precision_at_k": "precision_at_k",
        "precision_at_returned": "precision_at_returned",
        "mrr_at_k": "mrr_at_k",
        "no_relevant_result_accuracy": "no_relevant_result_accuracy",
        "hook_recall_at_k": "hook_recall_at_k",
        "selected_hook_accuracy": "selected_hook_accuracy",
        "readiness_accuracy": "readiness_accuracy",
        "continuation_decision_accuracy": "continuation_decision_accuracy",
        "task_success_rate": "task_success",
        "expected_task_outcome_match_rate": "expected_task_outcome_match",
        "target_file_precision": "target_file_precision",
        "target_file_recall": "target_file_recall",
        "exact_target_set_match_rate": "exact_target_set_match",
        "unexpected_file_rate": "unexpected_file",
        "forbidden_file_violation_rate": "forbidden_file_violation",
        "no_modification_rate": "no_modification",
        "false_continue_rate": "false_continue",
        "false_block_rate": "false_block",
    }
    aggregate: dict[str, float] = {}
    details: dict[str, Mapping[str, Any]] = {}
    for name, source in mapping.items():
        applicable = [
            (str(result["case_id"]), float(metrics[source]))
            for result in results
            if isinstance((metrics := result.get("metrics")), Mapping)
            and isinstance(metrics.get(source), (int, float))
        ]
        if applicable:
            values = [value for _, value in applicable]
            aggregate[name] = sum(values) / len(values)
            details[name] = {
                "value": aggregate[name],
                "sum_of_case_scores": sum(values),
                "applicable_case_count": len(values),
                "applicable_case_ids": [case_id for case_id, _ in applicable],
                "higher_is_better": METRIC_DIRECTIONS[name],
            }
    return aggregate, details


def _raw_observation(value: CaseObservation) -> Mapping[str, Any]:
    return {
        "retrieval": {
            **dict(value.retrieval.__dict__),
            "ranked_results": [dict(result.__dict__) for result in value.retrieval.ranked_results],
        },
        "decision": dict(value.decision.__dict__) if value.decision else None,
    }


def _cost_summary(items: Sequence[RetrievalObservation]) -> dict[str, float | int | str]:
    latencies = sorted(item.latency_ms for item in items)
    return {
        "case_count": len(items),
        "latency_ms_total": sum(latencies),
        "latency_ms_mean": sum(latencies) / len(latencies) if latencies else 0.0,
        "latency_ms_p50": _nearest_rank(latencies, 0.50),
        "latency_ms_p95": _nearest_rank(latencies, 0.95),
        "percentile_method": "nearest_rank",
        "api_calls_total": sum(item.api_calls for item in items),
        "input_tokens_total": sum(item.input_tokens for item in items),
        "output_tokens_total": sum(item.output_tokens for item in items),
        "monetary_cost_total": sum(item.monetary_cost for item in items),
    }


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    if not values:
        return 0.0
    return values[math.ceil(len(values) * percentile) - 1]


def _require_non_empty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_unique_strings(values: tuple[str, ...], field: str, required: bool = False) -> None:
    if required and not values:
        raise ValueError(f"{field} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{field} must contain non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{field} must not contain duplicate values")


def _require_canonical_paths(values: tuple[str, ...], field: str) -> None:
    _require_unique_strings(values, field)
    for path in values:
        if "\\" in path or path.startswith("/") or ":" in path.split("/")[0] or any(part in {".", ".."} for part in path.split("/")):
            raise ValueError(f"{field} requires canonical repository-relative POSIX paths")


def _require_non_negative_finite(value: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite non-negative number")


def _require_non_negative_int(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    _require_non_empty(result, field)  # type: ignore[arg-type]
    return result  # type: ignore[return-value]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    _require_non_empty(value, "optional string")
    return value


def _required_bool(value: Mapping[str, Any], field: str) -> bool:
    result = value.get(field)
    if not isinstance(result, bool):
        raise ValueError(f"{field} must be boolean")
    return result


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("string sequence fields must be JSON string arrays")
    return tuple(value)


def _ranked_results(value: Any) -> tuple[RankedRetrievalResult, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("ranked_results must be a JSON array")
    results: list[RankedRetrievalResult] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("ranked_results entries must be JSON objects")
        results.append(
            RankedRetrievalResult(
                result_id=_required_string(item, "result_id"),
                relative_path=_required_string(item, "relative_path"),
                line_number=_integer(item.get("line_number"), "line_number"),
                matched_text=_required_string(item, "matched_text"),
                file_sha256=_required_string(item, "file_sha256"),
                source=_required_string(item, "source"),
            )
        )
    return tuple(results)


def _number(value: Any, field: str) -> float:
    _require_non_negative_finite(value, field)
    return float(value)


def _integer(value: Any, field: str) -> int:
    _require_non_negative_int(value, field)
    return value


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
