"""CPU golden retrieval checks. 为什么要有它：真实检索、缺测和退化都要有可观察结果。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts import check_rag_golden as gate


def _report() -> dict:
    return deepcopy(gate.load_baseline(gate.BASELINE)["measurement"])


def test_normal_cli_executes_real_retrieval_and_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    assert gate.main(["--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["measurement"]["benchmark_execution"]["total_case_count"] == 8
    assert all(row["retrieval"]["retrieved"] for row in result["measurement"]["cases"])
    assert result["model_calls"] == result["network_calls"] == 0


def test_real_retrieval_degradation_fails_without_rewriting_gold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ingestion.storage.bm25_indexer import BM25Indexer

    baseline_bytes = gate.BASELINE.read_bytes()
    monkeypatch.setattr(BM25Indexer, "query", lambda *args, **kwargs: [])
    output = tmp_path / "regression.json"
    assert gate.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert any("regressed" in error for error in report["errors"])
    assert gate.BASELINE.read_bytes() == baseline_bytes


@pytest.mark.parametrize("failure", ["missing_case", "missing_metric", "nan", "unobserved", "dataset", "qrels"])
def test_missing_or_changed_measurements_cannot_pass(failure: str) -> None:
    baseline = gate.load_baseline(gate.BASELINE)
    report = deepcopy(baseline["measurement"])
    case = report["cases"][0]
    if failure == "missing_case":
        report["cases"].pop()
    elif failure == "missing_metric":
        del case["metrics"]["macro_mrr"]
    elif failure == "nan":
        case["metrics"]["macro_ndcg_at_3"]["value"] = float("nan")
    elif failure == "unobserved":
        case["retrieval_execution_measurement"]["status"] = "not_applicable"
    elif failure == "dataset":
        report["dataset"]["corpus_manifest_sha256"] = "sha256:wrong"
    else:
        case["annotations"]["qrels"]["expected_relevant_ids"] = ["invented:qrel"]
    assert gate.compare_measurement(report, baseline)


def test_one_case_regression_is_not_hidden_by_aggregate() -> None:
    baseline = gate.load_baseline(gate.BASELINE)
    report = deepcopy(baseline["measurement"])
    for name in gate.METRICS:
        metric = report["cases"][0]["metrics"][name]
        metric["value"] = metric["numerator"] = 0
    assert any("regressed" in error for error in gate.compare_measurement(report, baseline))


def test_tampered_baseline_algorithm_identity_is_configuration_error(tmp_path: Path) -> None:
    baseline = gate.load_baseline(gate.BASELINE)
    baseline["retrieval_source_sha256_lf"][gate.SOURCE_FILES[0]] = "sha256:wrong"
    changed = tmp_path / "baseline.json"
    changed.write_text(json.dumps(baseline), encoding="utf-8")
    output = tmp_path / "result.json"
    assert gate.main(["--baseline", str(changed), "--output", str(output)]) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "configuration_error"


def test_unexpected_retrieval_exception_emits_failed_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("synthetic index failure")

    monkeypatch.setattr(gate, "run_archived_bm25_benchmark", broken)
    output = tmp_path / "failure.json"
    assert gate.main(["--output", str(output)]) == 1
    assert "synthetic index failure" in json.loads(output.read_text(encoding="utf-8"))["errors"][0]


def test_nonfinite_runtime_report_still_emits_failure_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report()
    report['cases'][0]['metrics']['macro_mrr']['value'] = float('nan')
    monkeypatch.setattr(gate, 'run_archived_bm25_benchmark', lambda *args, **kwargs: report)
    output = tmp_path / 'nonfinite.json'
    assert gate.main(['--output', str(output)]) == 1
    saved = json.loads(output.read_text(encoding='utf-8'))
    assert saved['status'] == 'failed'
    assert saved['errors']