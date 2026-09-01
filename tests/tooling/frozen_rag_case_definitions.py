"""Strict loader for the B1 pre-execution RAG case definition checkpoint.

This module validates fixture structure and archived Git identities only. It
does not build an index, execute retrieval, calculate a metric value, or call a
model. The corpus and case fields intentionally reuse the archived BM25
test-only representation; the additional governance fields distinguish formal
pre-execution held-out cases from that fixture's non-held-out ``reserved``
split.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Any

from tests.tooling.archived_bm25_benchmark import (
    ArchivedBm25Case,
    FrozenEvidence,
    _canonical_sha256,
    _load_cases,
    _load_corpus,
    _reject_duplicate_keys,
    _required_string,
    _string_tuple,
    _verify_git_revision,
)


METRIC_DEFINITIONS = {
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
}

_DATASET_FIELDS = {
    "dataset_schema_version",
    "dataset_id",
    "source_revision",
    "top_k",
    "development_adjustment_case_ids",
    "case_governance",
    "metric_definitions",
    "corpus",
    "cases",
}
_CORPUS_FIELDS = {
    "evidence_id",
    "lane",
    "relative_path",
    "source_sha256",
    "start_line",
    "end_line",
}
_CASE_FIELDS = {
    "case_id",
    "split",
    "category",
    "requirement",
    "query",
    "required_evidence_lanes",
    "expected_relevant_ids",
    "relevance_reasons",
    "support_status",
    "support_ids",
    "support_rationale",
    "use_decision",
    "use_rationale",
    "insufficient_evidence_action",
}
_GOVERNANCE_FIELDS = {
    "case_scope",
    "source_snapshot_policy",
    "collection_boundary",
    "annotation_boundary",
    "review_record_status",
    "prior_benchmark_adjustment_status",
    "first_execution_status",
    "held_out_case_ids",
    "development_case_ids",
    "held_out_access_boundary",
    "held_out_blinding",
    "metric_applicability",
    "ragas_applicability",
    "claim_boundary",
    "b2_entry_condition",
}
_CASE_SPLITS = {"development", "held_out"}


@dataclass(frozen=True)
class FrozenRagCaseGovernance:
    case_scope: str
    source_snapshot_policy: str
    collection_boundary: str
    annotation_boundary: str
    review_record_status: str
    prior_benchmark_adjustment_status: str
    first_execution_status: str
    held_out_case_ids: tuple[str, ...]
    development_case_ids: tuple[str, ...]
    held_out_access_boundary: str
    held_out_blinding: str
    metric_applicability: str
    ragas_applicability: str
    claim_boundary: str
    b2_entry_condition: str


@dataclass(frozen=True)
class FrozenRagCaseDataset:
    dataset_schema_version: str
    dataset_id: str
    source_revision: str
    top_k: int
    development_adjustment_case_ids: tuple[str, ...]
    case_governance: FrozenRagCaseGovernance
    metric_definitions: Mapping[str, str]
    corpus: tuple[FrozenEvidence, ...]
    cases: tuple[ArchivedBm25Case, ...]
    dataset_sha256: str
    corpus_manifest_sha256: str


def load_frozen_rag_case_definitions(
    path: str | Path,
    *,
    workspace_root: str | Path,
) -> FrozenRagCaseDataset:
    """Load B1 definitions without executing any retrieval path."""

    raw = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-standard JSON numeric constant: {token}")
        ),
    )
    if not isinstance(raw, Mapping):
        raise ValueError("frozen RAG case definition dataset must be a JSON object")
    _require_exact_fields(raw, _DATASET_FIELDS, "dataset")

    schema_version = _required_string(raw, "dataset_schema_version")
    if schema_version != "frozen_rag_case_definitions_v1":
        raise ValueError("dataset_schema_version must be frozen_rag_case_definitions_v1")
    dataset_id = _required_string(raw, "dataset_id")
    source_revision = _required_string(raw, "source_revision")
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("source_revision must be a lowercase 40-character Git SHA")
    top_k = raw.get("top_k")
    if top_k != 3 or isinstance(top_k, bool):
        raise ValueError("top_k must equal 3 for the frozen @3 metric definitions")

    root = Path(workspace_root).resolve()
    _verify_git_revision(root, source_revision)

    raw_corpus = raw.get("corpus")
    if not isinstance(raw_corpus, list):
        raise ValueError("corpus must be an array")
    for entry in raw_corpus:
        if not isinstance(entry, Mapping):
            raise ValueError("each corpus entry must be an object")
        _require_exact_fields(entry, _CORPUS_FIELDS, "corpus entry")
    corpus = _load_corpus(raw_corpus, root, source_revision)
    evidence_ids = {item.evidence_id for item in corpus}

    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 5:
        raise ValueError("this B1 checkpoint must contain exactly five cases")
    original_splits: list[str] = []
    archived_shape_cases: list[dict[str, Any]] = []
    for entry in raw_cases:
        if not isinstance(entry, Mapping):
            raise ValueError("each case must be an object")
        _require_exact_fields(entry, _CASE_FIELDS, "case")
        split = _required_string(entry, "split")
        if split not in _CASE_SPLITS:
            raise ValueError("case split must be development or held_out")
        original_splits.append(split)
        archived_shape_cases.append({
            **entry,
            "split": "reserved" if split == "held_out" else split,
        })

    # Reuse the archived fixture's exact qrel and annotation validation. Its
    # reserved label is used only for validation and is restored to held_out in
    # the returned immutable definitions; the archived dataset is not changed.
    archived_cases = _load_cases(archived_shape_cases, evidence_ids)
    cases = tuple(
        replace(case, split=split)
        for case, split in zip(archived_cases, original_splits, strict=True)
    )

    adjustment_ids = _string_tuple(raw.get("development_adjustment_case_ids"))
    if adjustment_ids:
        raise ValueError(
            "development_adjustment_case_ids must be empty before first execution"
        )

    metric_definitions = raw.get("metric_definitions")
    if metric_definitions != METRIC_DEFINITIONS:
        raise ValueError("metric_definitions must exactly match the archived @3 contract")

    governance = _load_governance(raw.get("case_governance"), cases)
    return FrozenRagCaseDataset(
        dataset_schema_version=schema_version,
        dataset_id=dataset_id,
        source_revision=source_revision,
        top_k=top_k,
        development_adjustment_case_ids=adjustment_ids,
        case_governance=governance,
        metric_definitions=dict(metric_definitions),
        corpus=corpus,
        cases=cases,
        dataset_sha256=_canonical_sha256(raw),
        corpus_manifest_sha256=_canonical_sha256(raw_corpus),
    )


def _load_governance(
    value: Any,
    cases: tuple[ArchivedBm25Case, ...],
) -> FrozenRagCaseGovernance:
    if not isinstance(value, Mapping):
        raise ValueError("case_governance must be an object")
    _require_exact_fields(value, _GOVERNANCE_FIELDS, "case_governance")
    governance = FrozenRagCaseGovernance(
        case_scope=_required_string(value, "case_scope"),
        source_snapshot_policy=_required_string(value, "source_snapshot_policy"),
        collection_boundary=_required_string(value, "collection_boundary"),
        annotation_boundary=_required_string(value, "annotation_boundary"),
        review_record_status=_required_string(value, "review_record_status"),
        prior_benchmark_adjustment_status=_required_string(
            value, "prior_benchmark_adjustment_status"
        ),
        first_execution_status=_required_string(value, "first_execution_status"),
        held_out_case_ids=_string_tuple(value.get("held_out_case_ids")),
        development_case_ids=_string_tuple(value.get("development_case_ids")),
        held_out_access_boundary=_required_string(value, "held_out_access_boundary"),
        held_out_blinding=_required_string(value, "held_out_blinding"),
        metric_applicability=_required_string(value, "metric_applicability"),
        ragas_applicability=_required_string(value, "ragas_applicability"),
        claim_boundary=_required_string(value, "claim_boundary"),
        b2_entry_condition=_required_string(value, "b2_entry_condition"),
    )
    exact_values = {
        "case_scope": "frozen_pre_execution_rag_evaluation",
        "source_snapshot_policy": "archived_git_revision",
        "review_record_status": "b1_internal_definition_checkpoint_only",
        "prior_benchmark_adjustment_status": "not_participated",
        "first_execution_status": "not_executed",
        "held_out_blinding": "not_blind_labels_committed_before_first_execution",
        "ragas_applicability": (
            "not_applicable_retrieval_only_no_generated_answer_or_llm_judge"
        ),
    }
    for field, expected in exact_values.items():
        if getattr(governance, field) != expected:
            raise ValueError(f"case_governance.{field} must equal {expected}")

    case_ids = {case.case_id for case in cases}
    held_out_ids = {case.case_id for case in cases if case.split == "held_out"}
    development_ids = {
        case.case_id for case in cases if case.split == "development"
    }
    if len(held_out_ids) < 2:
        raise ValueError("at least two cases must be frozen as held_out")
    if set(governance.held_out_case_ids) != held_out_ids:
        raise ValueError("held_out_case_ids must exactly match held_out case splits")
    if set(governance.development_case_ids) != development_ids:
        raise ValueError(
            "development_case_ids must exactly match development case splits"
        )
    if held_out_ids | development_ids != case_ids:
        raise ValueError("governance case IDs must cover every frozen case")
    return governance


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ValueError(
            f"{label} fields must match exactly; missing={missing}; extra={extra}"
        )
