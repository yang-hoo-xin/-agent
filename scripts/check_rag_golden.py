"""CPU retrieval regression against a measured, version-bound small gold set.

Scope: archived-source BM25 only; no model, network, answer faithfulness or Mod
success is measured. 为什么要有它：真实检索回归与模型、产品质量必须分别计量。
Exit 0: no per-case regression; 1: regression/measurement failure; 2: bad input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.tooling.archived_bm25_benchmark import (  # noqa: E402
    run_archived_bm25_benchmark,
)

DATASET = ROOT / "tests/fixtures/evaluation/archived_bm25_benchmark_cases.json"
BASELINE = ROOT / "tests/fixtures/evaluation/archived_bm25_ci_baseline.json"
METRICS = ("micro_recall_at_3", "macro_mrr", "macro_ndcg_at_3")
IDENTITY_FIELDS = ("dataset_id", "dataset_sha256", "corpus_manifest_sha256", "source_revision")
SOURCE_FILES = (
    "src/core/query_engine/tokenization.py",
    "src/ingestion/embedding/sparse_encoder.py",
    "src/ingestion/storage/bm25_indexer.py",
    "tests/tooling/archived_bm25_benchmark.py",
)
SCOPE = "CPU BM25 retrieval regression; exposed curated cases, not independent holdout, LLM faithfulness or product success"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def source_identity(root: Path, revision: str | None = None) -> dict[str, str]:
    """Hash normalized source so Windows checkout line endings remain portable."""
    identities = {}
    for name in SOURCE_FILES:
        if revision is None:
            content = (root / name).read_bytes()
        else:
            content = subprocess.run(
                ["git", "show", f"{revision}:{name}"], cwd=root,
                capture_output=True, check=True,
            ).stdout
        identities[name] = _sha(content.replace(b"\r\n", b"\n"))
    return identities


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{label}: missing or non-numeric")
    if not math.isfinite(value):
        raise ValueError(f"{label}: non-finite")
    return float(value)


def case_values(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Require actual complete case measurements. 为什么要有它：缺测不能算通过。"""
    execution = report["benchmark_execution"]
    if execution["status"] != "completed" or execution["failure_count"] != 0:
        raise ValueError("retrieval execution incomplete")
    cases = report["cases"]
    expected_count = report["dataset"]["case_counts"]["total"]
    if not cases or len(cases) != expected_count or len(cases) != execution["total_case_count"]:
        raise ValueError("case population incomplete")
    result = {}
    for case in cases:
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in result:
            raise ValueError("missing or duplicate case_id")
        if case["retrieval_execution_measurement"]["status"] != "observed":
            raise ValueError(f"{case_id}: retrieval not observed")
        qrels = case["annotations"]["qrels"]["expected_relevant_ids"]
        if not qrels or len(qrels) != len(set(qrels)):
            raise ValueError(f"{case_id}: empty or duplicate qrels")
        values = {}
        for name in METRICS:
            metric = case["metrics"][name]
            if (metric["system_measurement_status"] != "observed"
                    or metric["system_measurement"]["status"] != "observed"):
                raise ValueError(f"{case_id}/{name}: metric not observed")
            value = _number(metric["value"], name)
            numerator = _number(metric["numerator"], name)
            denominator = _number(metric["denominator"], name)
            if denominator <= 0 or numerator < 0 or not 0 <= value <= 1:
                raise ValueError(f"{case_id}/{name}: invalid metric bounds")
            if not math.isclose(value, numerator / denominator, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"{case_id}/{name}: inconsistent metric value")
            if name == "micro_recall_at_3" and denominator != len(qrels):
                raise ValueError(f"{case_id}: changed qrel denominator")
            values[name] = value
        result[case_id] = {"qrels": sorted(qrels), "metrics": values}
    return result


def compare_measurement(report: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Compare each case, not only averages. 为什么要有它：平均值不能掩盖单题退化。"""
    errors = []
    try:
        for field in IDENTITY_FIELDS:
            if report["dataset"][field] != baseline["measurement"]["dataset"][field]:
                errors.append(f"dataset identity mismatch: {field}")
        if report["baseline"]["top_k"] != baseline["measurement"]["baseline"]["top_k"]:
            errors.append("top_k mismatch")
        actual = case_values(report)
        expected = case_values(baseline["measurement"])
        if set(actual) != set(expected):
            errors.append("case identities differ")
        for case_id in sorted(set(actual) & set(expected)):
            if actual[case_id]["qrels"] != expected[case_id]["qrels"]:
                errors.append(f"{case_id}: qrels changed")
            for metric in METRICS:
                before = expected[case_id]["metrics"][metric]
                after = actual[case_id]["metrics"][metric]
                if after + 1e-12 < before:
                    errors.append(f"{case_id}/{metric}: regressed {before} -> {after}")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid measurement: {type(exc).__name__}: {exc}")
    return errors


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_baseline(path: Path, root: Path = ROOT) -> dict[str, Any]:
    baseline = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON: {value}")),
    )
    if baseline["schema"] != "archived_bm25_ci_baseline.v1":
        raise ValueError("unsupported baseline schema")
    case_values(baseline["measurement"])
    expected_sources = source_identity(root, baseline["measured_code_revision"])
    if baseline["retrieval_source_sha256_lf"] != expected_sources:
        raise ValueError("measured baseline algorithm identity mismatch")
    return baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=SCOPE)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args(argv)
    result: dict[str, Any] = {
        "schema": "rag_golden_ci_result.v1", "scope": SCOPE,
        "model_calls": 0, "network_calls": 0, "status": "failed",
        "baseline_path": str(args.baseline), "errors": [],
    }
    exit_code = 2
    try:
        baseline = load_baseline(args.baseline)
        result["baseline_sha256"] = _sha(args.baseline.read_bytes())
        result["baseline_code_revision"] = baseline["measured_code_revision"]
        result["current_retrieval_source_sha256_lf"] = source_identity(ROOT)
        result["baseline_retrieval_source_sha256_lf"] = baseline["retrieval_source_sha256_lf"]
        result["retrieval_sources_changed"] = (
            result["current_retrieval_source_sha256_lf"] != baseline["retrieval_source_sha256_lf"]
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        result["status"] = "configuration_error"
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="rag-golden-") as temporary:
                measurement = run_archived_bm25_benchmark(
                    DATASET, workspace_root=ROOT, index_dir=Path(temporary) / "bm25",
                )
            json.dumps(measurement, allow_nan=False)
            result["measurement"] = measurement
            result["errors"] = compare_measurement(measurement, baseline)
            result["status"] = "passed" if not result["errors"] else "failed"
            exit_code = 0 if not result["errors"] else 1
        except Exception as exc:
            result["errors"].append(f"measurement exception: {type(exc).__name__}: {exc}")
            exit_code = 1
    result["exit_code"] = exit_code
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"Cannot write strict JSON result: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {SCOPE}; result={args.output}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
