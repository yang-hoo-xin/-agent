"""Direct tests for the test-only archived-source BM25 benchmark harness."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from tests.tooling.archived_bm25_benchmark import (
    load_archived_bm25_dataset,
    run_archived_bm25_benchmark,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/evaluation/archived_bm25_benchmark_cases.json"
SOURCE_REVISION = "50b270a65bc602150175389675cfb52a3e2e9baf"
METRICS = {
    "micro_recall_at_3",
    "macro_mrr",
    "macro_ndcg_at_3",
    "nonrelevant_retrieval_rate_at_3",
}


def _run(tmp_path: Path) -> dict[str, Any]:
    return run_archived_bm25_benchmark(
        FIXTURE,
        workspace_root=ROOT,
        index_dir=tmp_path / "bm25",
    )


def _changed_fixture(tmp_path: Path, mutate: Any) -> Path:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutate(raw)
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    return changed


def test_dataset_is_curated_archived_source_smoke_with_reserved_split() -> None:
    dataset = load_archived_bm25_dataset(FIXTURE, workspace_root=ROOT)

    assert dataset.source_revision == SOURCE_REVISION
    assert len(dataset.corpus) == 9
    assert len(dataset.cases) == 8
    assert all(item.lane == "current_source" for item in dataset.corpus)
    assert all(case.required_evidence_lanes == ("current_source",) for case in dataset.cases)
    assert [case.case_id for case in dataset.cases if case.split == "reserved"] == [
        "reserved_wave1_b_scope"
    ]
    assert dataset.development_adjustment_case_ids == ()
    assert dataset.case_governance.case_scope == "curated_current_source_smoke"
    assert dataset.case_governance.source_snapshot_policy == "archived_git_revision"
    assert dataset.case_governance.review_record_status == "not_recorded"


def test_report_reuses_measurement_contract_and_separates_split_metrics(
    tmp_path: Path,
) -> None:
    report = _run(tmp_path)

    assert report["benchmark_contract"] == {
        "kind": "offline_bm25_benchmark_harness",
        "measurement_serialization": (
            "src.observability.evaluation.eval_runner.MeasurementState.to_dict"
        ),
        "durable_eval_truth": False,
        "graph_consumer": False,
        "product_api": False,
        "future_ci_input_only": True,
        "formal_eval_integration": "not_implemented",
    }
    assert "report_schema_version" not in report
    assert "target_measurements" not in report
    assert "high_assurance_rag_report" not in json.dumps(report)
    assert report["dataset"]["case_counts"] == {
        "total": 8,
        "development": 7,
        "reserved": 1,
        "development_adjustment": 0,
    }
    development = report["metric_results_by_split"]["development"]
    reserved = report["metric_results_by_split"]["reserved"]
    assert development["case_count"] == 7
    assert reserved["case_count"] == 1
    assert set(development["metrics"]) == METRICS
    assert set(reserved["metrics"]) == METRICS
    assert development["metrics"]["micro_recall_at_3"]["counts_first"] == {
        "numerator": 8,
        "denominator": 9,
    }
    assert development["metrics"]["micro_recall_at_3"]["value"] == pytest.approx(8 / 9)
    assert development["metrics"]["macro_mrr"]["value"] == pytest.approx(1.0)
    assert development["metrics"]["macro_ndcg_at_3"]["value"] == pytest.approx(
        0.9447353132522084
    )
    assert development["metrics"]["nonrelevant_retrieval_rate_at_3"][
        "counts_first"
    ] == {"numerator": 13, "denominator": 21}
    assert reserved["metrics"]["micro_recall_at_3"]["value"] == pytest.approx(0.5)
    assert reserved["metrics"]["macro_ndcg_at_3"]["value"] == pytest.approx(
        0.6131471927654584
    )
    assert reserved["metrics"]["nonrelevant_retrieval_rate_at_3"][
        "value"
    ] == pytest.approx(2 / 3)
    assert "held_out" not in json.dumps(report)
    assert "error_evidence_rate" not in json.dumps(report)


def test_retrieve_objective_is_not_applicable_and_execution_is_separate(
    tmp_path: Path,
) -> None:
    report = _run(tmp_path)
    objectives = report["objective_measurements"]

    assert report["retrieval_execution_measurements"] == {
        "total": 8,
        "observed": 8,
        "failed_to_measure": 0,
        "not_applicable": 0,
    }
    assert objectives["retrieve"] == {
        "total": 8,
        "observed": 0,
        "failed_to_measure": 0,
        "not_applicable": 8,
    }
    assert objectives["isrel"]["observed"] == 8
    assert objectives["issup"]["not_applicable"] == 8
    assert objectives["isuse"]["not_applicable"] == 8

    for case in report["cases"]:
        assert set(case["retrieval_execution_measurement"]) == {
            "status", "mode", "error_category", "error_message",
        }
        assert case["retrieval_execution_measurement"]["status"] == "observed"
        assert case["objectives"]["retrieve"] == {
            "status": "not_applicable",
            "mode": "no_retrieve_classifier",
            "error_category": None,
            "error_message": None,
        }
        for target in ("retrieve", "isrel", "issup", "isuse"):
            assert set(case["objectives"][target]) == {
                "status", "mode", "error_category", "error_message",
            }
        assert case["annotations"]["qrels"]["presence"] == "present"
        assert case["annotations"]["issup"]["presence"] == "present"
        assert case["annotations"]["isuse"]["presence"] == "present"
        assert all(
            "measurement" not in key
            for annotation in case["annotations"].values()
            for key in annotation
        )
        assert case["bounded_action_contract"] == {
            "oracle_only": True,
            "graph_connected": False,
            "claimed_executed": False,
        }


def test_production_evaluation_has_no_high_assurance_rag_interface() -> None:
    assert not (ROOT / "src/observability/evaluation/high_assurance_rag.py").exists()
    completed = subprocess.run(
        ["git", "grep", "-n", "high_assurance_rag", "--", "src"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert completed.stdout == ""


def test_ragas_remains_not_applicable_and_not_a_ci_gate(tmp_path: Path) -> None:
    applicability = _run(tmp_path)["ragas_applicability"]

    assert applicability["invoked"] is False
    assert applicability["ci_hard_gate"] is False
    assert set(applicability["metrics"]) == {
        "faithfulness", "answer_relevancy", "context_precision",
    }
    assert all(
        item["measurement_status"] == "not_applicable"
        for item in applicability["metrics"].values()
    )


def test_retrieval_failures_preserve_every_metric_position_denominator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_query(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("bounded injected retrieval failure")

    monkeypatch.setattr(
        "tests.tooling.archived_bm25_benchmark.BM25Indexer.query",
        fail_query,
    )
    report = _run(tmp_path)

    assert report["benchmark_execution"]["status"] == "partial"
    assert report["benchmark_execution"]["failure_count"] == 8
    assert report["retrieval_execution_measurements"]["failed_to_measure"] == 8
    assert report["objective_measurements"]["retrieve"]["not_applicable"] == 8
    assert report["objective_measurements"]["retrieve"]["failed_to_measure"] == 0
    for case in report["cases"]:
        assert case["retrieval_execution_measurement"]["status"] == "failed_to_measure"
        assert case["objectives"]["retrieve"]["status"] == "not_applicable"
        assert case["objectives"]["isrel"]["status"] == "failed_to_measure"
        assert case["objectives"]["issup"]["status"] == "not_applicable"
        assert case["objectives"]["isuse"]["status"] == "not_applicable"
        assert case["metrics"]["micro_recall_at_3"]["denominator"] == len(
            case["annotations"]["qrels"]["expected_relevant_ids"]
        )
        assert case["metrics"]["macro_mrr"]["denominator"] == 1
        assert case["metrics"]["macro_ndcg_at_3"]["denominator"] == 1
        assert case["metrics"]["nonrelevant_retrieval_rate_at_3"]["denominator"] == 3
        assert all(
            metric["system_measurement_status"] == "failed_to_measure"
            for metric in case["metrics"].values()
        )
    for split in ("development", "reserved"):
        expected_count = 7 if split == "development" else 1
        for metric in report["metric_results_by_split"][split]["metrics"].values():
            assert metric["measurement_counts"]["total"] == expected_count
            assert metric["measurement_counts"]["failed_to_measure"] == expected_count
            assert all(position["denominator"] > 0 for position in metric["measurement_positions"])


def test_duplicate_retrieved_chunk_ids_fail_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tests.tooling.archived_bm25_benchmark.BM25Indexer.query",
        lambda *_args, **_kwargs: [
            {"chunk_id": "current:eval_runner:measurement_states", "score": 1.0},
            {"chunk_id": "current:eval_runner:measurement_states", "score": 0.5},
        ],
    )

    report = _run(tmp_path)

    assert report["benchmark_execution"]["failure_count"] == 8
    assert all(
        case["retrieval_execution_measurement"]["error_category"] == "ValueError"
        for case in report["cases"]
    )
    assert all(
        "unique" in case["retrieval_execution_measurement"]["error_message"]
        for case in report["cases"]
    )


def test_loader_reads_archived_blobs_without_checkout_file_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _self: (_ for _ in ()).throw(AssertionError("checkout bytes read")),
    )

    dataset = load_archived_bm25_dataset(FIXTURE, workspace_root=ROOT)

    assert dataset.source_revision == SOURCE_REVISION


def test_loader_rejects_archived_source_hash_drift(tmp_path: Path) -> None:
    changed = _changed_fixture(
        tmp_path,
        lambda raw: raw["corpus"][0].__setitem__(
            "source_sha256", "sha256:" + "0" * 64,
        ),
    )

    with pytest.raises(ValueError, match="archived source SHA-256 mismatch"):
        load_archived_bm25_dataset(changed, workspace_root=ROOT)


@pytest.mark.parametrize(
    "lanes",
    [["docs"], ["current_source", "docs"]],
)
def test_loader_requires_exact_current_source_lane(
    tmp_path: Path,
    lanes: list[str],
) -> None:
    changed = _changed_fixture(
        tmp_path,
        lambda raw: raw["cases"][0].__setitem__("required_evidence_lanes", lanes),
    )

    with pytest.raises(ValueError, match="must exactly equal"):
        load_archived_bm25_dataset(changed, workspace_root=ROOT)


def test_loader_freezes_support_id_rules(tmp_path: Path) -> None:
    mutations = [
        lambda raw: raw["cases"][0].__setitem__("support_ids", []),
        lambda raw: raw["cases"][0].__setitem__(
            "support_ids", ["current:eval_runner:metric_registry"],
        ),
        lambda raw: raw["cases"][5].__setitem__(
            "support_ids", ["current:active_contract:wave1_boundaries"],
        ),
    ]
    messages = ["requires non-empty", "subset", "requires empty"]

    for index, (mutation, message) in enumerate(zip(mutations, messages)):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        changed = _changed_fixture(case_dir, mutation)
        with pytest.raises(ValueError, match=message):
            load_archived_bm25_dataset(changed, workspace_root=ROOT)


def test_loader_freezes_qrel_identity_and_reason_coverage(tmp_path: Path) -> None:
    mutations = [
        lambda raw: raw["cases"][0].__setitem__(
            "expected_relevant_ids", ["outside:archived:corpus"],
        ),
        lambda raw: raw["cases"][0]["relevance_reasons"].pop(
            raw["cases"][0]["expected_relevant_ids"][0]
        ),
    ]
    messages = ["outside the frozen corpus", "exactly cover"]

    for index, (mutation, message) in enumerate(zip(mutations, messages)):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        changed = _changed_fixture(case_dir, mutation)
        with pytest.raises(ValueError, match=message):
            load_archived_bm25_dataset(changed, workspace_root=ROOT)
