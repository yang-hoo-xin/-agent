#!/usr/bin/env python
"""Run the time-boxed local A/B/D retrieval direction pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mod_agent.evaluation import (  # noqa: E402
    AgentQualityCase,
    RgLiveReadProvider,
    RunManifestCollector,
)
from src.mod_agent.git import GitRepository  # noqa: E402
from src.mod_agent.knowledge import (  # noqa: E402
    BM25Indexer,
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.knowledge.models import (  # noqa: E402
    Document,
    chunk_from_document,
    stable_hash,
)

DEFAULT_CASES = PROJECT_ROOT / "evaluation/directional/v2_ret_directional_001_cases_v1.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation/directional/results"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id")
    parser.add_argument("--git-executable")
    parser.add_argument("--rg-executable")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = args.workspace.resolve()
    cases_path = args.cases.resolve()
    raw = _load_object(cases_path)
    _validate_cases(raw, workspace)
    run_id = args.run_id or (
        "v2_ret_directional_001_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    if not run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("run_id may contain only letters, digits, hyphen, and underscore")

    git_repository = GitRepository(workspace, git_executable=args.git_executable)
    collector = RunManifestCollector(workspace, git_repository=git_repository)
    search_roots = tuple(raw["repository_search_roots"])
    before_git = git_repository.working_tree_snapshot()
    before_corpus = collector.canonical_corpus_snapshot(search_roots)

    code_cases = raw["code_cases"]
    community_cases = raw["community_cases"]
    top_k = int(raw["top_k"])
    a_provider = RgLiveReadProvider(
        workspace,
        search_patterns={item["case_id"]: item["a_patterns"] for item in code_cases},
        corpus_snapshot=before_corpus,
        rg_executable=args.rg_executable,
    )

    a_results: list[dict[str, Any]] = []
    a_observations: dict[str, Any] = {}
    for item in code_cases:
        observation = a_provider(_agent_case(item), top_k).retrieval
        a_observations[item["case_id"]] = observation
        a_results.append(_score_a_case(item, observation, top_k))

    with tempfile.TemporaryDirectory(prefix="directional-pilot-") as temp_dir:
        b_results, b_index = _run_b(
            workspace=workspace,
            code_cases=code_cases,
            a_observations=a_observations,
            top_k=top_k,
            temp_root=Path(temp_dir),
        )
        d_results, d_index, d_traces = _run_d(
            workspace=workspace,
            raw=raw,
            community_cases=community_cases,
            corpus_snapshot=before_corpus,
            top_k=top_k,
            rg_executable=args.rg_executable,
            temp_root=Path(temp_dir),
        )

    after_git = git_repository.working_tree_snapshot()
    after_corpus = collector.canonical_corpus_snapshot(search_roots)
    if before_git != after_git or before_corpus != after_corpus:
        raise RuntimeError("workspace inputs changed during the directional pilot")

    community_kind = raw["community_corpus"]["kind"]
    recommendation = _recommend(a_results, b_results, d_results, community_kind)
    payload = {
        "result_schema_version": "retrieval_directional_result_v1",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": raw["dataset_version"],
        "dataset_file_sha256": _file_sha256(cases_path),
        "claim_scope": raw["claim_scope"],
        "top_k": top_k,
        "workspace_binding": {
            "git": before_git.to_dict(),
            "corpus_snapshot_sha256": before_corpus.corpus_snapshot_sha256,
            "corpus_file_count": len(before_corpus.files),
            "inputs_fresh_at_completion": True,
        },
        "arm_a": {
            "scope": "rg_plus_live_read",
            "rg_identity": a_provider.executable_identity.to_dict(),
            "command_traces": [trace.to_dict() for trace in a_provider.command_traces],
            "cases": a_results,
            "summary_by_stratum": _summary_by_stratum(a_results),
        },
        "arm_b": {
            "scope": "arm_a_plus_current_symbol_indexer_and_live_revalidation",
            "claim_boundary": "current regex SymbolIndexer only; not AST, LSP, or call graph",
            "index_build": b_index,
            "cases": b_results,
            "summary_by_stratum": _summary_by_stratum(b_results),
        },
        "arm_d": {
            "scope": "community_bm25_plus_current_source_verification",
            "evidence_grade": community_kind,
            "product_value_claim_allowed": bool(
                raw["community_corpus"].get("authentic_product_value_claim_allowed")
            ),
            "index_build": d_index,
            "verification_command_traces": d_traces,
            "cases": d_results,
            "summary_by_stratum": _summary_by_stratum(d_results),
        },
        "implementation_effort": {
            "arm_a": "reused existing runner/authenticity path",
            "arm_b": "thin local adapter over existing IncrementalIndexer and SymbolIndexer",
            "arm_d": "thin local BM25 fixture adapter; authentic corpus remains unavailable",
        },
        "estimated_maintenance_burden": {
            "arm_a": "low",
            "arm_b": "medium if retained; regex language coverage and refresh need ownership",
            "arm_d": "unknown until authentic corpus acquisition and provenance workflow exist",
        },
        "recommendation": recommendation,
        "limitations": [
            "Local frozen cases on one dirty working tree; no statistical or cross-project claim.",
            "Arm B measures the current regex SymbolIndexer, not AST/LSP/call-graph behavior.",
            "Arm D uses synthetic fixture:// notes because no authentic traceable community corpus exists; its results are plumbing_only.",
            "No H1-H5 verdict, wrong-file modification, final task success, Dense, RRF, rerank, Agentic routing, or production promotion is measured."
        ],
    }
    output = _write_result(payload, args.output_dir.resolve(), run_id)
    print(json.dumps({"result_path": str(output), "result": payload}, ensure_ascii=False, indent=2))
    return 0


def _run_b(
    *,
    workspace: Path,
    code_cases: list[dict[str, Any]],
    a_observations: dict[str, Any],
    top_k: int,
    temp_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    database = KnowledgeDatabase(temp_root / "symbol.db")
    registry = SourceRegistry(database)
    registry.register(
        SourceDefinition(
            source_id="directional_current_source",
            source_type="target_source",
            root_path=workspace / "src",
            allowed_extensions=frozenset({".py", ".cs"}),
        )
    )
    started = time.perf_counter_ns()
    report = IncrementalIndexer(database=database, source_registry=registry).index_source(
        "directional_current_source"
    )
    build_ms = (time.perf_counter_ns() - started) / 1_000_000
    results: list[dict[str, Any]] = []
    for item in code_cases:
        query_started = time.perf_counter_ns()
        symbol_rows: list[dict[str, Any]] = []
        seen_symbols: set[str] = set()
        for symbol_query in item["symbol_queries"]:
            for symbol in database.search_symbols(symbol_query, limit=top_k):
                if symbol.symbol_id in seen_symbols:
                    continue
                _revalidate_symbol(workspace, symbol)
                seen_symbols.add(symbol.symbol_id)
                symbol_rows.append(
                    {
                        "result_type": "symbol",
                        "symbol": symbol.name,
                        "symbol_kind": symbol.kind,
                        "relative_path": "src/" + symbol.relative_path,
                        "line_number": symbol.start_line,
                        "signature": symbol.signature,
                        "content_hash": symbol.content_hash,
                        "live_revalidated": True,
                    }
                )
                if len(symbol_rows) >= top_k:
                    break
            if len(symbol_rows) >= top_k:
                break
        ranked = list(symbol_rows)
        seen_paths = {row["relative_path"] for row in ranked}
        for a_result in a_observations[item["case_id"]].ranked_results:
            if a_result.relative_path in seen_paths:
                continue
            ranked.append(
                {
                    "result_type": "rg_file",
                    "symbol": None,
                    "relative_path": a_result.relative_path,
                    "line_number": a_result.line_number,
                    "matched_text": a_result.matched_text,
                    "content_hash": a_result.file_sha256,
                    "live_revalidated": True,
                }
            )
            seen_paths.add(a_result.relative_path)
            if len(ranked) >= top_k:
                break
        latency_ms = (
            a_observations[item["case_id"]].latency_ms
            + (time.perf_counter_ns() - query_started) / 1_000_000
        )
        results.append(_score_ranked(item, ranked[:top_k], latency_ms))
    return results, {**report.to_artifact_payload(), "duration_ms": build_ms}


def _run_d(
    *,
    workspace: Path,
    raw: dict[str, Any],
    community_cases: list[dict[str, Any]],
    corpus_snapshot: Any,
    top_k: int,
    rg_executable: str | None,
    temp_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    corpus_path = workspace / raw["community_corpus"]["path"]
    community = _load_object(corpus_path)
    database = KnowledgeDatabase(temp_root / "community.db")
    chunks = []
    for note in community["notes"]:
        claim = str(note["claim"])
        file_hash = stable_hash(claim)
        note_id = str(note["note_id"])
        document_id = "doc_" + hashlib.sha256(note_id.encode("utf-8")).hexdigest()[:16]
        document = Document(
            document_id=document_id,
            source_type="manual_note",
            source_path=str(note["source_locator"]),
            raw_text=claim,
            canonical_text=claim,
            text=claim,
            metadata={
                "source_id": "directional_synthetic_community",
                "document_id": document_id,
                "source_path": str(note["source_locator"]),
                "note_id": note_id,
                "raw_text_hash": file_hash,
                "canonical_text_hash": file_hash,
                "doc_hash": file_hash,
                "file_hash": file_hash,
                "source_hash": file_hash,
                "content_hash": file_hash,
                "requires_verification": bool(note["requires_verification"]),
            },
        )
        database.upsert_document(document)
        chunk = chunk_from_document(document)
        chunks.append(
            database.upsert_chunk(
                chunk, collection_id="directional_community", index_version="v1"
            )
        )
    started = time.perf_counter_ns()
    index_report = BM25Indexer(database).index(
        collection_id="directional_community", index_version="v1", chunks=chunks
    )
    build_ms = (time.perf_counter_ns() - started) / 1_000_000
    verifier = RgLiveReadProvider(
        workspace,
        search_patterns={item["case_id"]: item["verifier_patterns"] for item in community_cases},
        corpus_snapshot=corpus_snapshot,
        rg_executable=rg_executable,
    )
    bm25 = BM25Indexer(database)
    results: list[dict[str, Any]] = []
    for item in community_cases:
        started = time.perf_counter_ns()
        hits = bm25.query_text(
            collection_id="directional_community",
            index_version="v1",
            query=item["query"],
            top_k=top_k,
        )
        bm25_ms = (time.perf_counter_ns() - started) / 1_000_000
        observation = verifier(_agent_case_for_community(item), top_k).retrieval
        note_ids = [str(hit.metadata.get("note_id", "")) for hit in hits]
        verifier_files = [result.relative_path for result in observation.ranked_results]
        hint_found = any(note_id in item["expected_note_ids"] for note_id in note_ids)
        verifier_found = any(path in item["expected_verifier_files"] for path in verifier_files)
        results.append(
            {
                "case_id": item["case_id"],
                "stratum": item["stratum"],
                "query": item["query"],
                "ranked_note_ids": note_ids,
                "hint_found_at_5": hint_found,
                "first_correct_result_rank": _first_rank(note_ids, set(item["expected_note_ids"])),
                "mrr": _mrr(note_ids, set(item["expected_note_ids"])),
                "verifier_files": verifier_files,
                "verification_status": item["manual_verdict"] if verifier_found else "unresolved",
                "verification_source_found": verifier_found,
                "bm25_latency_ms": bm25_ms,
                "verification_latency_ms": observation.latency_ms,
                "latency_ms": bm25_ms + observation.latency_ms,
                "evidence_grade": raw["community_corpus"]["kind"],
            }
        )
    return (
        results,
        {
            "chunk_count": index_report.chunk_count,
            "term_count": index_report.term_count,
            "posting_count": index_report.posting_count,
            "duration_ms": build_ms,
            "corpus_file_sha256": _file_sha256(corpus_path),
        },
        [trace.to_dict() for trace in verifier.command_traces],
    )


def _score_a_case(item: dict[str, Any], observation: Any, top_k: int) -> dict[str, Any]:
    ranked = [
        {
            "result_type": "rg_file",
            "symbol": next(
                (symbol for symbol in item["expected_symbols"] if symbol in result.matched_text),
                None,
            ),
            "relative_path": result.relative_path,
            "line_number": result.line_number,
            "matched_text": result.matched_text,
            "content_hash": result.file_sha256,
            "live_revalidated": True,
        }
        for result in observation.ranked_results[:top_k]
    ]
    return _score_ranked(item, ranked, observation.latency_ms)


def _score_ranked(
    item: dict[str, Any], ranked: list[dict[str, Any]], latency_ms: float
) -> dict[str, Any]:
    expected_files = set(item["expected_files"])
    expected_symbols = set(item["expected_symbols"])
    ranked_files = list(dict.fromkeys(row["relative_path"] for row in ranked))
    ranked_symbols = [row.get("symbol") for row in ranked if row.get("symbol")]
    correct_symbols = expected_symbols & set(ranked_symbols)
    rank = _first_rank(ranked_files, expected_files)
    return {
        "case_id": item["case_id"],
        "stratum": item["stratum"],
        "query": item["query"],
        "ranked_results": ranked,
        "correct_file_found_at_5": rank is not None,
        "correct_symbol_found_at_5": (
            bool(correct_symbols) if expected_symbols else None
        ),
        "correct_symbol_count_at_5": len(correct_symbols),
        "expected_symbol_count": len(expected_symbols),
        "first_correct_result_rank": rank,
        "mrr": 1.0 / rank if rank else 0.0,
        "irrelevant_returned_file_count": len(
            [path for path in ranked_files if path not in expected_files]
        ),
        "latency_ms": latency_ms,
    }


def _recommend(
    a_results: list[dict[str, Any]],
    b_results: list[dict[str, Any]],
    d_results: list[dict[str, Any]],
    community_kind: str,
) -> dict[str, Any]:
    a_symbols = {
        item["case_id"]: item for item in a_results if item["stratum"] == "current_symbol_indexer"
    }
    b_symbols = {
        item["case_id"]: item for item in b_results if item["stratum"] == "current_symbol_indexer"
    }
    improved = 0
    extra_irrelevant = 0
    for case_id, b_item in b_symbols.items():
        a_item = a_symbols[case_id]
        if (
            b_item["correct_symbol_count_at_5"] > a_item["correct_symbol_count_at_5"]
            or (b_item["correct_file_found_at_5"] and not a_item["correct_file_found_at_5"])
        ):
            improved += 1
        extra_irrelevant += max(
            0,
            b_item["irrelevant_returned_file_count"]
            - a_item["irrelevant_returned_file_count"],
        )
    if improved >= 2 and extra_irrelevant <= 1:
        choice = "next_deepen_current_symbol_structural_retrieval"
        reason = f"B improved {improved} symbol-stratum cases with {extra_irrelevant} extra irrelevant files."
    elif community_kind == "synthetic_plumbing_only":
        choice = "insufficient_evidence_retain_rg_no_expansion"
        reason = (
            f"B improved only {improved} symbol-stratum cases, and D has no authentic "
            "traceable corpus; retain rg without expanding retrieval infrastructure."
        )
    elif sum(
        bool(item["hint_found_at_5"] and item["verification_source_found"])
        for item in d_results
    ) >= 2:
        choice = "next_build_minimal_authentic_community_bm25"
        reason = "Authentic D produced at least two source-checked useful hints."
    else:
        choice = "retain_rg_plus_live_read"
        reason = (
            f"B improved {improved} symbol-stratum cases and authentic D did not "
            "reach the frozen directional threshold."
        )
    return {
        "choice": choice,
        "reason": reason,
        "community_direction_status": (
            "unknown_no_authentic_traceable_corpus"
            if community_kind == "synthetic_plumbing_only"
            else "measured_locally"
        ),
    }


def _summary_by_stratum(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for stratum in sorted({str(item["stratum"]) for item in results}):
        rows = [item for item in results if item["stratum"] == stratum]
        if "correct_file_found_at_5" in rows[0]:
            summaries[stratum] = {
                "case_count": len(rows),
                "correct_file_found_count": sum(bool(item["correct_file_found_at_5"]) for item in rows),
                "correct_symbol_found_count": sum(item["correct_symbol_count_at_5"] for item in rows),
                "expected_symbol_count": sum(item["expected_symbol_count"] for item in rows),
                "irrelevant_returned_file_count": sum(item["irrelevant_returned_file_count"] for item in rows),
                "mean_mrr": sum(item["mrr"] for item in rows) / len(rows),
                "latency_ms_total": sum(item["latency_ms"] for item in rows),
            }
        else:
            summaries[stratum] = {
                "case_count": len(rows),
                "hint_found_count": sum(bool(item["hint_found_at_5"]) for item in rows),
                "verified_count": sum(item["verification_status"] == "verified" for item in rows),
                "rejected_count": sum(item["verification_status"] == "rejected" for item in rows),
                "unresolved_count": sum(item["verification_status"] == "unresolved" for item in rows),
                "mean_mrr": sum(item["mrr"] for item in rows) / len(rows),
                "latency_ms_total": sum(item["latency_ms"] for item in rows),
            }
    return summaries


def _agent_case(item: dict[str, Any]) -> AgentQualityCase:
    return AgentQualityCase(
        case_id=item["case_id"],
        stratum=item["stratum"],
        query=item["query"],
        expected_relevant_ids=tuple("file:" + path for path in item["expected_files"]),
        expected_hook_ids=tuple(item["expected_symbols"]),
        expected_target_files=(),
        forbidden_files=(),
        expected_readiness="blocked",
        expected_control_action="block",
        task_success_eligible=False,
        expected_task_success=None,
    )


def _agent_case_for_community(item: dict[str, Any]) -> AgentQualityCase:
    return AgentQualityCase(
        case_id=item["case_id"],
        stratum=item["stratum"],
        query=item["query"],
        expected_relevant_ids=tuple(
            "file:" + path for path in item["expected_verifier_files"]
        ),
        expected_hook_ids=(),
        expected_target_files=(),
        forbidden_files=(),
        expected_readiness="blocked",
        expected_control_action="block",
        task_success_eligible=False,
        expected_task_success=None,
    )


def _revalidate_symbol(workspace: Path, symbol: Any) -> None:
    path = Path(symbol.source_path).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise RuntimeError("symbol result escaped workspace") from exc
    content = path.read_text(encoding="utf-8")
    if stable_hash(content) != symbol.content_hash:
        raise RuntimeError(f"symbol result is stale: {path}")
    lines = content.splitlines()
    if symbol.start_line <= 0 or symbol.start_line > len(lines):
        raise RuntimeError(f"symbol line is no longer valid: {path}:{symbol.start_line}")
    if lines[symbol.start_line - 1].strip() != symbol.signature:
        raise RuntimeError(f"symbol signature changed before consumption: {path}")


def _validate_cases(raw: dict[str, Any], workspace: Path) -> None:
    required = {
        "directional_schema_version",
        "dataset_version",
        "claim_scope",
        "top_k",
        "repository_search_roots",
        "code_cases",
        "community_cases",
        "community_corpus",
        "decision_rule",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"directional cases missing fields: {missing}")
    all_cases = [*raw["code_cases"], *raw["community_cases"]]
    if not all_cases or len(all_cases) > 12:
        raise ValueError("directional pilot requires between 1 and 12 cases")
    ids = [item["case_id"] for item in all_cases]
    if len(ids) != len(set(ids)):
        raise ValueError("directional case IDs must be unique")
    smoke = _load_object(PROJECT_ROOT / "evaluation/benchmarks/arm_a_repo_smoke_v3.json")
    smoke_ids = {item["case_id"] for item in smoke["cases"]}
    smoke_queries = {item["query"] for item in smoke["cases"]}
    if set(ids) & smoke_ids or {item["query"] for item in all_cases} & smoke_queries:
        raise ValueError("directional cases reuse formal smoke cases")
    for item in raw["code_cases"]:
        for span in item["ground_truth_spans"]:
            path_text, lines = span.rsplit(":", 1)
            start_text, end_text = lines.split("-", 1)
            path = workspace / path_text
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            if int(start_text) <= 0 or int(end_text) > line_count:
                raise ValueError(f"ground truth span is invalid: {span}")
    corpus_path = workspace / raw["community_corpus"]["path"]
    if not corpus_path.is_file():
        raise ValueError("community corpus file is missing")


def _load_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _first_rank(values: list[str], expected: set[str]) -> int | None:
    return next((rank for rank, value in enumerate(values, 1) if value in expected), None)


def _mrr(values: list[str], expected: set[str]) -> float:
    rank = _first_rank(values, expected)
    return 1.0 / rank if rank else 0.0


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_result(payload: dict[str, Any], output_dir: Path, run_id: str) -> Path:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    digest = hashlib.sha256(encoded).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{run_id}_{digest}.json"
    with path.open("xb") as handle:
        handle.write(encoded)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
