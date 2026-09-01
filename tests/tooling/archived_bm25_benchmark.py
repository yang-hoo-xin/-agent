"""Test-only BM25 benchmark harness over an archived Git snapshot.

This tooling reuses EvalRunner's public ``MeasurementState`` serialization only.
Its dictionaries are test and future-CI inputs, not a report schema, durable Eval
truth, Graph input, or product API. It executes BM25 retrieval, applies fixture
qrels for IsREL, and retains IsSUP/IsUSE fixture annotations without evaluating
them. It never generates an answer, grants authority, selects a Graph route, or
invokes RAGAS/LLM judges.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.query_engine.tokenization import tokenize_retrieval_text
from src.core.types import Chunk
from src.ingestion.embedding.sparse_encoder import SparseEncoder
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.observability.evaluation.eval_runner import (
    FAILED_TO_MEASURE,
    MeasurementState,
    NOT_APPLICABLE,
    OBSERVED,
)

_SUPPORT_STATUSES = {"support", "partial", "conflict", "missing"}
_USE_DECISIONS = {"answer", "continue_plan", "clarify", "refuse"}
_BOUNDED_ACTIONS = {
    "additional_lookup", "block", "clarify", "bounded_partial", "refuse",
}
_SPLITS = {"development", "reserved"}
_METRICS = (
    "micro_recall_at_3",
    "macro_mrr",
    "macro_ndcg_at_3",
    "nonrelevant_retrieval_rate_at_3",
)
_RAGAS_METRICS = ("faithfulness", "answer_relevancy", "context_precision")


@dataclass(frozen=True)
class FrozenEvidence:
    evidence_id: str
    lane: str
    relative_path: str
    source_sha256: str
    start_line: int
    end_line: int
    text: str

    @property
    def source_ref(self) -> str:
        return f"{self.relative_path}#L{self.start_line}-L{self.end_line}"


@dataclass(frozen=True)
class ArchivedBm25Case:
    case_id: str
    split: str
    category: str
    requirement: str
    query: str
    required_evidence_lanes: tuple[str, ...]
    expected_relevant_ids: tuple[str, ...]
    relevance_reasons: Mapping[str, str]
    support_status: str
    support_ids: tuple[str, ...]
    support_rationale: str
    use_decision: str
    use_rationale: str
    insufficient_evidence_action: str


@dataclass(frozen=True)
class CaseGovernance:
    case_scope: str
    source_snapshot_policy: str
    collection_boundary: str
    annotation_boundary: str
    review_record_status: str


@dataclass(frozen=True)
class ArchivedBm25Dataset:
    dataset_schema_version: str
    dataset_id: str
    source_revision: str
    top_k: int
    development_adjustment_case_ids: tuple[str, ...]
    case_governance: CaseGovernance
    corpus: tuple[FrozenEvidence, ...]
    cases: tuple[ArchivedBm25Case, ...]
    dataset_sha256: str
    corpus_manifest_sha256: str


def load_archived_bm25_dataset(
    path: str | Path, *, workspace_root: str | Path,
) -> ArchivedBm25Dataset:
    """Load strict labels and verify every span from its archived Git blob."""

    raw = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-standard JSON numeric constant: {token}")
        ),
    )
    if not isinstance(raw, Mapping):
        raise ValueError("archived BM25 dataset must be a JSON object")
    schema_version = _required_string(raw, "dataset_schema_version")
    dataset_id = _required_string(raw, "dataset_id")
    source_revision = _required_string(raw, "source_revision")
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("source_revision must be a lowercase 40-character Git SHA")
    top_k = raw.get("top_k")
    if top_k != 3 or isinstance(top_k, bool):
        raise ValueError("top_k must equal 3 for the named @3 metrics")

    root = Path(workspace_root).resolve()
    _verify_git_revision(root, source_revision)
    corpus = _load_corpus(raw.get("corpus"), root, source_revision)
    evidence_ids = {item.evidence_id for item in corpus}
    cases = _load_cases(raw.get("cases"), evidence_ids)
    adjustment_ids = _string_tuple(raw.get("development_adjustment_case_ids"))
    case_ids = {case.case_id for case in cases}
    if set(adjustment_ids) - case_ids:
        raise ValueError("development_adjustment_case_ids contains unknown case IDs")
    reserved_ids = {case.case_id for case in cases if case.split == "reserved"}
    development_ids = {case.case_id for case in cases if case.split == "development"}
    if not reserved_ids:
        raise ValueError("at least one reserved case is required")
    if not set(adjustment_ids) <= development_ids:
        raise ValueError("only development cases may participate in adjustment")
    governance = _load_case_governance(raw.get("case_governance"))
    return ArchivedBm25Dataset(
        dataset_schema_version=schema_version,
        dataset_id=dataset_id,
        source_revision=source_revision,
        top_k=top_k,
        development_adjustment_case_ids=adjustment_ids,
        case_governance=governance,
        corpus=corpus,
        cases=cases,
        dataset_sha256=_canonical_sha256(raw),
        corpus_manifest_sha256=_canonical_sha256(raw.get("corpus")),
    )


def run_archived_bm25_benchmark(
    dataset_path: str | Path,
    *,
    workspace_root: str | Path,
    index_dir: str | Path,
) -> dict[str, Any]:
    """Run the archived existing-BM25 benchmark and return test-only output."""

    dataset = load_archived_bm25_dataset(
        dataset_path, workspace_root=workspace_root,
    )
    chunks = [
        Chunk(
            id=item.evidence_id,
            text=item.text,
            metadata={"source_path": item.relative_path},
        )
        for item in dataset.corpus
    ]
    indexer = BM25Indexer(index_dir=str(index_dir))
    indexer.build(
        SparseEncoder().encode(chunks), collection=dataset.dataset_id,
    )
    corpus_by_id = {item.evidence_id: item for item in dataset.corpus}
    case_results = [
        _run_case(case, dataset.top_k, indexer, corpus_by_id)
        for case in dataset.cases
    ]
    failed_cases = [
        result["case_id"] for result in case_results
        if result["retrieval_execution_measurement"]["status"] == FAILED_TO_MEASURE
    ]
    missed_cases = [
        result for result in case_results
        if result["metrics"]["micro_recall_at_3"].get("value") != 1.0
    ]
    metric_results_by_split = {
        split: _split_metric_results(split, case_results)
        for split in ("development", "reserved")
    }
    return {
        "benchmark_contract": {
            "kind": "offline_bm25_benchmark_harness",
            "measurement_serialization": (
                "src.observability.evaluation.eval_runner.MeasurementState.to_dict"
            ),
            "durable_eval_truth": False,
            "graph_consumer": False,
            "product_api": False,
            "future_ci_input_only": True,
            "formal_eval_integration": "not_implemented",
        },
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "dataset_schema_version": dataset.dataset_schema_version,
            "dataset_sha256": dataset.dataset_sha256,
            "source_revision": dataset.source_revision,
            "corpus_manifest_sha256": dataset.corpus_manifest_sha256,
            "case_counts": {
                "total": len(dataset.cases),
                "development": sum(c.split == "development" for c in dataset.cases),
                "reserved": sum(c.split == "reserved" for c in dataset.cases),
                "development_adjustment": len(
                    dataset.development_adjustment_case_ids
                ),
            },
            "reserved_case_ids": [
                case.case_id for case in dataset.cases if case.split == "reserved"
            ],
            "development_adjustment_case_ids": list(
                dataset.development_adjustment_case_ids
            ),
            "case_governance": dict(dataset.case_governance.__dict__),
        },
        "baseline": {
            "retriever": "BM25Indexer",
            "encoder": "SparseEncoder",
            "retrieval_lanes": ["current_source"],
            "top_k": dataset.top_k,
            "dense": NOT_APPLICABLE,
            "rrf": NOT_APPLICABLE,
            "reranker": NOT_APPLICABLE,
            "network_calls": 0,
            "model_calls": 0,
            "source_snapshot_policy": "archived_git_revision",
        },
        "corpus": [
            {
                "evidence_id": item.evidence_id,
                "lane": item.lane,
                "source_ref": item.source_ref,
                "source_sha256": item.source_sha256,
                "source_revision": dataset.source_revision,
            }
            for item in dataset.corpus
        ],
        "cases": case_results,
        "metric_results_by_split": metric_results_by_split,
        "all_case_metric_results": _split_metric_results("all", case_results),
        "metric_definitions": {
            "micro_recall_at_3": (
                "Sum of qrel hits in the first 3 results divided by the sum of "
                "qrel counts across observed cases."
            ),
            "macro_mrr": "Mean per-case reciprocal rank across observed cases.",
            "macro_ndcg_at_3": "Mean per-case binary nDCG@3 across observed cases.",
            "nonrelevant_retrieval_rate_at_3": (
                "Non-qrel retrieved results divided by all returned results in the "
                "first 3 positions across observed cases."
            ),
        },
        "retrieval_execution_measurements": _status_counts(
            result["retrieval_execution_measurement"]["status"]
            for result in case_results
        ),
        "objective_measurements": {
            target: _status_counts(
                result["objectives"][target]["status"] for result in case_results
            )
            for target in ("retrieve", "isrel", "issup", "isuse")
        },
        "benchmark_execution": {
            "status": "completed" if not failed_cases else "partial",
            "failed_case_ids": failed_cases,
            "failure_count": len(failed_cases),
            "total_case_count": len(dataset.cases),
        },
        "bounded_action_annotations": [
            {
                "case_id": result["case_id"],
                "action": result["annotations"]["isuse"][
                    "insufficient_evidence_action"
                ],
                "objective_measurement_status": NOT_APPLICABLE,
                "graph_connected": False,
                "claimed_executed": False,
            }
            for result in missed_cases
        ],
        "ragas_applicability": {
            "invoked": False,
            "ci_hard_gate": False,
            "metrics": {
                metric: {
                    "measurement_status": NOT_APPLICABLE,
                    "reason": (
                        "This retrieval-only offline slice has no generated answer and "
                        "does not invoke an LLM judge."
                    ),
                }
                for metric in _RAGAS_METRICS
            },
        },
        "claim_boundary": {
            "observed": (
                "Archived Git-blob identity validation, existing BM25 execution, "
                "fixture-qrel IsREL application, and local retrieval metric counts."
            ),
            "not_established": (
                "Independent or untuned evaluation, formal held-out performance, "
                "human review, claim support, answer usefulness, stable success "
                "rates, RAGAS scores, write authority, Graph routing, Apply, Build, "
                "or Runtime success."
            ),
            "reserved_status": (
                "Reserved means excluded from development adjustment in this same-"
                "revision curated smoke fixture; it is not a formal held-out set."
            ),
            "small_sample_reporting": "Report counts and denominators before ratios.",
        },
    }


def _run_case(
    case: ArchivedBm25Case,
    top_k: int,
    indexer: BM25Indexer,
    corpus_by_id: Mapping[str, FrozenEvidence],
) -> dict[str, Any]:
    retrieve_objective = MeasurementState(
        status=NOT_APPLICABLE,
        mode="no_retrieve_classifier",
    )
    try:
        query_terms = tokenize_retrieval_text(
            case.query, lowercase=True, min_token_length=2,
        )
        hits = indexer.query(query_terms, top_k=top_k)
        retrieved_ids = [str(hit["chunk_id"]) for hit in hits]
        _require_unique(retrieved_ids, "retrieved chunk IDs")
        unknown_ids = set(retrieved_ids) - set(corpus_by_id)
        if unknown_ids:
            raise ValueError("retrieval returned IDs outside the archived corpus")
        scores = {str(hit["chunk_id"]): float(hit["score"]) for hit in hits}
        retrieval_execution = MeasurementState(
            status=OBSERVED,
            mode="empty" if not retrieved_ids else "bm25_results",
        )
        isrel_objective = MeasurementState(
            status=OBSERVED,
            mode="fixture_qrels_applied",
        )
    except Exception as exc:  # retain the denominator position
        retrieved_ids = []
        scores = {}
        retrieval_execution = MeasurementState.from_exception(
            exc,
            mode="bm25_retrieval",
        )
        isrel_objective = MeasurementState.from_exception(
            exc,
            mode="fixture_qrels_apply",
        )

    expected = set(case.expected_relevant_ids)
    metrics = _case_metrics(
        retrieved_ids,
        case.expected_relevant_ids,
        top_k,
        retrieval_execution.status,
    )
    issup_objective = MeasurementState(
        status=NOT_APPLICABLE,
        mode="no_claim_evaluator",
    )
    isuse_objective = MeasurementState(
        status=NOT_APPLICABLE,
        mode="no_answer_evaluator",
    )
    return {
        "case_id": case.case_id,
        "split": case.split,
        "category": case.category,
        "requirement": case.requirement,
        "query": case.query,
        "retrieval_execution_measurement": retrieval_execution.to_dict(),
        "objectives": {
            "retrieve": retrieve_objective.to_dict(),
            "isrel": isrel_objective.to_dict(),
            "issup": issup_objective.to_dict(),
            "isuse": isuse_objective.to_dict(),
        },
        "retrieval": {
            "required_evidence_lanes": list(case.required_evidence_lanes),
            "lane_results": {
                "current_source": {
                    "execution_measurement": retrieval_execution.to_dict(),
                    "skipped": False,
                    "retrieved_count": len(retrieved_ids),
                }
            },
            "retrieved": [
                {
                    "evidence_id": evidence_id,
                    "score": scores[evidence_id],
                    "source_ref": corpus_by_id[evidence_id].source_ref,
                    "source_sha256": corpus_by_id[evidence_id].source_sha256,
                }
                for evidence_id in retrieved_ids
            ],
        },
        "annotations": {
            "qrels": {
                "presence": "present",
                "expected_relevant_ids": list(case.expected_relevant_ids),
                "relevance_reasons": dict(case.relevance_reasons),
            },
            "issup": {
                "presence": "present",
                "support_status": case.support_status,
                "support_ids": list(case.support_ids),
                "support_rationale": case.support_rationale,
            },
            "isuse": {
                "presence": "present",
                "use_decision": case.use_decision,
                "use_rationale": case.use_rationale,
                "insufficient_evidence_action": case.insufficient_evidence_action,
            },
        },
        "isrel_judgments": [
            {
                "evidence_id": evidence_id,
                "relevant": evidence_id in expected,
                "reason": case.relevance_reasons.get(
                    evidence_id,
                    "Not listed in the fixture expected_relevant_ids qrels.",
                ),
                "grants_edit_authority": False,
            }
            for evidence_id in retrieved_ids
        ],
        "bounded_action_contract": {
            "oracle_only": True,
            "graph_connected": False,
            "claimed_executed": False,
        },
        "metrics": metrics,
    }


def _case_metrics(
    retrieved_ids: Sequence[str],
    expected_ids: Sequence[str],
    top_k: int,
    retrieval_status: str,
) -> dict[str, dict[str, Any]]:
    expected = set(expected_ids)
    ideal_count = min(len(expected), top_k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    if retrieval_status != OBSERVED:
        failed = MeasurementState(
            status=FAILED_TO_MEASURE,
            mode="bm25_retrieval_prerequisite",
        )
        return {
            "micro_recall_at_3": {
                "system_measurement": failed.to_dict(),
                "system_measurement_status": failed.status,
                "numerator": None,
                "denominator": len(expected),
                "value": None,
            },
            "macro_mrr": {
                "system_measurement": failed.to_dict(),
                "system_measurement_status": failed.status,
                "numerator": None,
                "denominator": 1,
                "value": None,
            },
            "macro_ndcg_at_3": {
                "system_measurement": failed.to_dict(),
                "system_measurement_status": failed.status,
                "numerator": None,
                "denominator": 1,
                "value": None,
                "score_counts": {"numerator": None, "denominator": idcg},
            },
            "nonrelevant_retrieval_rate_at_3": {
                "system_measurement": failed.to_dict(),
                "system_measurement_status": failed.status,
                "numerator": None,
                "denominator": top_k,
                "value": None,
            },
        }
    ranked = list(retrieved_ids[:top_k])
    relevant_flags = [evidence_id in expected for evidence_id in ranked]
    relevant_count = sum(relevant_flags)
    first_rank = next((i for i, flag in enumerate(relevant_flags, 1) if flag), None)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, flag in enumerate(relevant_flags, 1) if flag
    )
    errors = len(ranked) - relevant_count
    reciprocal_rank = 0.0 if first_rank is None else 1.0 / first_rank
    observed = MeasurementState(status=OBSERVED, mode="bm25_qrels_metric")
    return {
        "micro_recall_at_3": {
            "system_measurement": observed.to_dict(),
            "system_measurement_status": observed.status,
            "numerator": relevant_count,
            "denominator": len(expected),
            "value": relevant_count / len(expected),
        },
        "macro_mrr": {
            "system_measurement": observed.to_dict(),
            "system_measurement_status": observed.status,
            "numerator": reciprocal_rank,
            "denominator": 1,
            "value": reciprocal_rank,
        },
        "macro_ndcg_at_3": {
            "system_measurement": observed.to_dict(),
            "system_measurement_status": observed.status,
            "numerator": dcg / idcg,
            "denominator": 1,
            "value": dcg / idcg,
            "score_counts": {"numerator": dcg, "denominator": idcg},
        },
        "nonrelevant_retrieval_rate_at_3": {
            "system_measurement": observed.to_dict(),
            "system_measurement_status": observed.status,
            "numerator": errors,
            "denominator": len(ranked),
            "value": None if not ranked else errors / len(ranked),
        },
    }


def _aggregate_metric(metric: str, results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    positions = [result["metrics"][metric] for result in results]
    observed = [
        item for item in positions if item["system_measurement_status"] == OBSERVED
    ]
    failed = sum(
        item["system_measurement_status"] == FAILED_TO_MEASURE for item in positions
    )
    not_applicable = sum(
        item["system_measurement_status"] == NOT_APPLICABLE for item in positions
    )
    if metric in {"micro_recall_at_3", "nonrelevant_retrieval_rate_at_3"}:
        numerator = sum(item["numerator"] for item in observed)
        denominator = sum(item["denominator"] for item in observed)
        value = None if denominator == 0 else numerator / denominator
    else:
        values = [item["value"] for item in observed if item.get("value") is not None]
        numerator = sum(values)
        denominator = len(values)
        value = None if denominator == 0 else numerator / denominator
    return {
        "counts_first": {"numerator": numerator, "denominator": denominator},
        "value": value,
        "measurement_counts": {
            "total": len(positions),
            "applicable": len(observed) + failed,
            "observed": len(observed),
            "failed_to_measure": failed,
            "not_applicable": not_applicable,
        },
        "measurement_positions": [
            {
                "case_id": str(result["case_id"]),
                "system_measurement_status": position["system_measurement_status"],
                "numerator": position["numerator"],
                "denominator": position["denominator"],
            }
            for result, position in zip(results, positions)
        ],
    }


def _status_counts(status_values: Any) -> dict[str, int]:
    statuses = list(status_values)
    return {
        "total": len(statuses),
        "observed": statuses.count(OBSERVED),
        "failed_to_measure": statuses.count(FAILED_TO_MEASURE),
        "not_applicable": statuses.count(NOT_APPLICABLE),
    }


def _split_metric_results(
    split: str,
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selected = list(results) if split == "all" else [
        result for result in results if result["split"] == split
    ]
    return {
        "split": split,
        "case_count": len(selected),
        "case_ids": [str(result["case_id"]) for result in selected],
        "metrics": {
            metric: _aggregate_metric(metric, selected) for metric in _METRICS
        },
    }


def _load_corpus(value: Any, root: Path, source_revision: str) -> tuple[FrozenEvidence, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("corpus must be a non-empty array")
    result: list[FrozenEvidence] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("each corpus entry must be an object")
        evidence_id = _required_string(raw, "evidence_id")
        lane = _required_string(raw, "lane")
        if lane != "current_source":
            raise ValueError("the baseline corpus only permits lane=current_source")
        relative_path = _canonical_relative_path(raw, "relative_path")
        source_sha256 = _required_string(raw, "source_sha256")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", source_sha256) is None:
            raise ValueError("source_sha256 must be a canonical SHA-256 value")
        start_line = _positive_int(raw, "start_line")
        end_line = _positive_int(raw, "end_line")
        if end_line < start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        frozen_bytes = _git_show(root, source_revision, relative_path)
        actual_sha256 = "sha256:" + hashlib.sha256(frozen_bytes).hexdigest()
        if actual_sha256 != source_sha256:
            raise ValueError(f"archived source SHA-256 mismatch: {relative_path}")
        lines = frozen_bytes.decode("utf-8-sig").splitlines()
        if end_line > len(lines):
            raise ValueError(f"corpus span exceeds archived source: {relative_path}")
        result.append(FrozenEvidence(
            evidence_id=evidence_id,
            lane=lane,
            relative_path=relative_path,
            source_sha256=source_sha256,
            start_line=start_line,
            end_line=end_line,
            text="\n".join(lines[start_line - 1:end_line]),
        ))
    _require_unique((item.evidence_id for item in result), "corpus.evidence_id")
    return tuple(result)


def _load_cases(value: Any, evidence_ids: set[str]) -> tuple[ArchivedBm25Case, ...]:
    if not isinstance(value, list) or not 5 <= len(value) <= 10:
        raise ValueError("cases must contain between 5 and 10 entries")
    result: list[ArchivedBm25Case] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("each case must be an object")
        split = _required_string(raw, "split")
        if split not in _SPLITS:
            raise ValueError("case split must be development or reserved")
        lanes = _string_tuple(raw.get("required_evidence_lanes"))
        if lanes != ("current_source",):
            raise ValueError(
                'required_evidence_lanes must exactly equal ["current_source"]'
            )
        expected_ids = _string_tuple(raw.get("expected_relevant_ids"))
        if not expected_ids:
            raise ValueError("expected_relevant_ids must not be empty")
        support_ids = _string_tuple(raw.get("support_ids"))
        if set(expected_ids) - evidence_ids:
            raise ValueError("case references evidence outside the frozen corpus")
        if not set(support_ids) <= set(expected_ids):
            raise ValueError("support_ids must be a subset of expected_relevant_ids")
        relevance = raw.get("relevance_reasons")
        if not isinstance(relevance, Mapping) or set(relevance) != set(expected_ids):
            raise ValueError("relevance_reasons must exactly cover expected_relevant_ids")
        support_status = _required_string(raw, "support_status")
        if support_status not in _SUPPORT_STATUSES:
            raise ValueError("invalid support_status")
        if support_status == "support" and not support_ids:
            raise ValueError("support status requires non-empty support_ids")
        if support_status == "partial" and (
            not support_ids or set(support_ids) == set(expected_ids)
        ):
            raise ValueError(
                "partial status requires a non-empty proper subset of expected IDs"
            )
        if support_status == "conflict" and not support_ids:
            raise ValueError("conflict status requires non-empty support_ids")
        if support_status == "missing" and support_ids:
            raise ValueError("missing status requires empty support_ids")
        use_decision = _required_string(raw, "use_decision")
        if use_decision not in _USE_DECISIONS:
            raise ValueError("invalid use_decision")
        bounded_action = _required_string(raw, "insufficient_evidence_action")
        if bounded_action not in _BOUNDED_ACTIONS:
            raise ValueError("invalid insufficient_evidence_action")
        result.append(ArchivedBm25Case(
            case_id=_required_string(raw, "case_id"),
            split=split,
            category=_required_string(raw, "category"),
            requirement=_required_string(raw, "requirement"),
            query=_required_string(raw, "query"),
            required_evidence_lanes=lanes,
            expected_relevant_ids=expected_ids,
            relevance_reasons={
                str(key): _exact_non_empty_string(reason, "relevance reason")
                for key, reason in relevance.items()
            },
            support_status=support_status,
            support_ids=support_ids,
            support_rationale=_required_string(raw, "support_rationale"),
            use_decision=use_decision,
            use_rationale=_required_string(raw, "use_rationale"),
            insufficient_evidence_action=bounded_action,
        ))
    _require_unique((case.case_id for case in result), "cases.case_id")
    return tuple(result)


def _load_case_governance(value: Any) -> CaseGovernance:
    if not isinstance(value, Mapping):
        raise ValueError("case_governance must be an object")
    governance = CaseGovernance(
        case_scope=_required_string(value, "case_scope"),
        source_snapshot_policy=_required_string(value, "source_snapshot_policy"),
        collection_boundary=_required_string(value, "collection_boundary"),
        annotation_boundary=_required_string(value, "annotation_boundary"),
        review_record_status=_required_string(value, "review_record_status"),
    )
    if governance.case_scope != "curated_current_source_smoke":
        raise ValueError("case_scope must be curated_current_source_smoke")
    if governance.source_snapshot_policy != "archived_git_revision":
        raise ValueError("source_snapshot_policy must be archived_git_revision")
    if governance.review_record_status != "not_recorded":
        raise ValueError("review_record_status must be not_recorded")
    return governance


def _verify_git_revision(root: Path, revision: str) -> None:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=root, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise ValueError("source_revision is not a readable Git commit")


def _git_show(root: Path, revision: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{relative_path}"],
        cwd=root, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise ValueError(f"source path is absent from source_revision: {relative_path}")
    return completed.stdout


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _required_string(value: Mapping[str, Any], field: str) -> str:
    return _exact_non_empty_string(value.get(field), field)


def _exact_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _positive_int(value: Mapping[str, Any], field: str) -> int:
    result = value.get(field)
    if not isinstance(result, int) or isinstance(result, bool) or result <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return result


def _canonical_relative_path(value: Mapping[str, Any], field: str) -> str:
    result = _required_string(value, field)
    path = Path(result)
    if "\\" in result or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a canonical workspace-relative POSIX path")
    return result


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("expected a string array")
    result = tuple(_exact_non_empty_string(item, "array item") for item in value)
    _require_unique(result, "string array")
    return result


def _require_unique(values: Sequence[str] | Any, field: str) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise ValueError(f"{field} must contain unique values")


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
# End of test-only benchmark harness.
