#!/usr/bin/env python
"""Validate a frozen Arm A benchmark design without executing retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mod_agent.evaluation import QualityGatePolicy, load_agent_quality_cases  # noqa: E402

DEFAULT_DATASET = PROJECT_ROOT / "evaluation/benchmarks/arm_a_held_out_v1.json"
DEFAULT_PROTOCOL = PROJECT_ROOT / "evaluation/benchmarks/arm_a_held_out_protocol_v1.json"
DEFAULT_POLICY = PROJECT_ROOT / "evaluation/benchmarks/arm_a_held_out_policy_v1.json"
DEFAULT_COMMUNITY = PROJECT_ROOT / "evaluation/benchmarks/arm_a_held_out_community_v1.json"
SMOKE_DATASET = PROJECT_ROOT / "evaluation/benchmarks/arm_a_repo_smoke_v3.json"
SMOKE_PROTOCOL = PROJECT_ROOT / "evaluation/benchmarks/arm_a_repo_smoke_protocol_v3.json"

EXPECTED_STRATA = {
    "exact_code_lookup",
    "structural_hook_discovery",
    "vague_semantic_intent",
    "community_history_dependent",
}
EXPECTED_MUTATIONS = {
    "mut-edit-method-body",
    "mut-rename-file",
    "mut-rename-symbol",
    "mut-delete-file",
    "mut-branch-worktree-namespace",
    "mut-concurrent-consumption-change",
    "mut-intentional-stale-result",
}


def audit_design(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    protocol_path: Path = DEFAULT_PROTOCOL,
    policy_path: Path = DEFAULT_POLICY,
    community_path: Path = DEFAULT_COMMUNITY,
) -> dict[str, Any]:
    protocol = _load_object(protocol_path)
    policy_raw = _load_object(policy_path)
    community = _load_object(community_path)
    smoke_dataset = _load_object(SMOKE_DATASET)
    smoke_protocol = _load_object(SMOKE_PROTOCOL)
    dataset = load_agent_quality_cases(dataset_path)
    policy = QualityGatePolicy.from_mapping(policy_raw)

    checks: list[dict[str, Any]] = []

    def record(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "pass" if passed else "fail", "detail": detail})

    case_ids = [case.case_id for case in dataset.cases]
    protocol_patterns = protocol.get("search_patterns")
    record(
        "held_out_scope",
        dataset.benchmark_scope == "held_out" and dataset.promotion_eligible,
        f"benchmark_scope={dataset.benchmark_scope}; promotion_eligible={dataset.promotion_eligible}",
    )
    record(
        "protocol_case_coverage",
        isinstance(protocol_patterns, dict) and set(protocol_patterns) == set(case_ids),
        f"dataset_cases={len(case_ids)}; protocol_cases={len(protocol_patterns or {})}",
    )
    counts = Counter(case.stratum for case in dataset.cases)
    record(
        "stratum_population",
        set(counts) == EXPECTED_STRATA and all(counts[name] >= 5 for name in EXPECTED_STRATA),
        json.dumps(dict(sorted(counts.items())), sort_keys=True),
    )
    negative_ids = [case.case_id for case in dataset.cases if case.expected_result_mode == "no_relevant"]
    record(
        "zero_relevant_population",
        bool(negative_ids),
        f"no_relevant_case_ids={negative_ids}",
    )
    multi_ids = [case.case_id for case in dataset.cases if len(case.expected_relevant_ids) > 1]
    record("multi_relevant_population", bool(multi_ids), f"multi_relevant_case_count={len(multi_ids)}")
    forbidden_ids = [case.case_id for case in dataset.cases if case.forbidden_files]
    record("ambiguity_controls", bool(forbidden_ids), f"cases_with_forbidden_files={len(forbidden_ids)}")
    community_ids = [
        case.case_id
        for case in dataset.cases
        if case.community_evidence_required and case.stratum == "community_history_dependent"
    ]
    record(
        "community_authority_boundary",
        len(community_ids) == counts.get("community_history_dependent", 0),
        f"community_bound_cases={len(community_ids)}",
    )

    mutation_ids = {
        item.get("scenario_id")
        for item in protocol.get("mutation_scenarios", [])
        if isinstance(item, dict)
    }
    case_mutations = {item for case in dataset.cases for item in case.mutation_scenario_ids}
    record(
        "mutation_protocol",
        mutation_ids == EXPECTED_MUTATIONS and EXPECTED_MUTATIONS <= case_mutations,
        f"protocol_mutations={sorted(mutation_ids)}; case_bound_mutations={sorted(case_mutations)}",
    )

    smoke_ids = {item["case_id"] for item in smoke_dataset.get("cases", [])}
    smoke_queries = {item["query"] for item in smoke_dataset.get("cases", [])}
    smoke_relevant_sets = {
        tuple(sorted(item["expected_relevant_ids"])) for item in smoke_dataset.get("cases", [])
    }
    held_relevant_sets = {tuple(sorted(case.expected_relevant_ids)) for case in dataset.cases if case.expected_relevant_ids}
    smoke_patterns = {pattern for values in smoke_protocol.get("search_patterns", {}).values() for pattern in values}
    held_patterns = {pattern for values in (protocol_patterns or {}).values() for pattern in values}
    record(
        "smoke_case_exclusion",
        not (set(case_ids) & smoke_ids)
        and not ({case.query for case in dataset.cases} & smoke_queries)
        and not (held_relevant_sets & smoke_relevant_sets)
        and not (held_patterns & smoke_patterns),
        "case IDs, queries, relevant-file sets and exact patterns are disjoint from formal smoke v3/v5 inputs",
    )

    span_errors: list[str] = []
    for case in dataset.cases:
        for span in case.expected_source_spans:
            match = re.fullmatch(r"([^:]+):(\d+)-(\d+)", span)
            if match is None:
                span_errors.append(f"{case.case_id}:{span}:invalid_format")
                continue
            relative, start, end = match.group(1), int(match.group(2)), int(match.group(3))
            source = PROJECT_ROOT / relative
            if not source.is_file():
                span_errors.append(f"{case.case_id}:{span}:missing_file")
                continue
            line_count = len(source.read_text(encoding="utf-8").splitlines())
            if start <= 0 or end < start or end > line_count:
                span_errors.append(f"{case.case_id}:{span}:out_of_range:{line_count}")
    record("source_span_integrity", not span_errors, "; ".join(span_errors) or "all source spans resolve")

    note_ids = {item.get("note_id") for item in community.get("notes", []) if isinstance(item, dict)}
    expected_note_ids = {
        relevant_id
        for case in dataset.cases
        for relevant_id in case.expected_relevant_ids
        if relevant_id.startswith("community_note:")
    }
    record(
        "community_note_integrity",
        note_ids == expected_note_ids and community.get("authority") == "planning_hint_only",
        f"note_count={len(note_ids)}; authority={community.get('authority')}",
    )
    record(
        "policy_contract",
        "no_relevant_result_accuracy" in policy.required_metric_names,
        f"policy_id={policy.policy_id}; required_metrics={list(policy.required_metric_names)}",
    )

    result_hits = []
    runs_dir = PROJECT_ROOT / "data/evaluation/runs"
    if runs_dir.is_dir():
        for path in runs_dir.glob("*.json"):
            if dataset.dataset_version in path.read_text(encoding="utf-8", errors="ignore"):
                result_hits.append(path.relative_to(PROJECT_ROOT).as_posix())
    record("pre_result_freeze", not result_hits, f"matching_result_files={result_hits}")
    record(
        "full_protocol_hash_binding",
        protocol.get("phase") == "frozen_pre_result",
        "runner binds the exact protocol document SHA-256 into evaluation_protocol_sha256",
    )

    failures = [item for item in checks if item["status"] != "pass"]
    return {
        "audit_schema_version": "arm_a_pre_run_audit_v1",
        "audit_scope": "design_only_no_retrieval_execution",
        "dataset_version": dataset.dataset_version,
        "review_status": "ready_for_external_pre_run_review" if not failures else "internal_checks_failed",
        "formal_arm_a_authorized": False,
        "input_hashes": {
            "dataset_file_sha256": _file_sha256(dataset_path),
            "dataset_canonical_sha256": dataset.dataset_sha256,
            "judgment_sha256": dataset.judgment_sha256,
            "protocol_file_sha256": _file_sha256(protocol_path),
            "quality_policy_file_sha256": _file_sha256(policy_path),
            "quality_policy_canonical_sha256": policy.policy_sha256,
            "community_corpus_file_sha256": _file_sha256(community_path),
        },
        "checks": checks,
        "conclusions_allowed": [
            "The held-out dataset and protocol satisfy the recorded internal design checks.",
            "The formal Arm A runner can bind the complete preregistered protocol document hash.",
            "No formal observation for this dataset version existed when the audit ran."
        ],
        "conclusions_forbidden": [
            "Arm A retrieval quality is established.",
            "Any BM25, structural, dense, fusion or Agentic route is better than Arm A.",
            "Any H1-H5 hypothesis passes or fails."
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--quality-policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--community-corpus", type=Path, default=DEFAULT_COMMUNITY)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit_design(
        dataset_path=args.dataset.resolve(),
        protocol_path=args.protocol.resolve(),
        policy_path=args.quality_policy.resolve(),
        community_path=args.community_corpus.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["review_status"] == "ready_for_external_pre_run_review" else 4


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
