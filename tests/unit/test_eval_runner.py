"""Unit tests for EvalRunner and golden test set loading."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.observability.evaluation.composite_evaluator import CompositeEvaluator
from src.observability.evaluation.eval_runner import (
    EvalRunner,
    EvalReport,
    GoldenTestCase,
    QueryResult,
    load_test_set,
)


# ── Fixtures / Helpers ────────────────────────────────────────────


class StubEvaluator(BaseEvaluator):
    """Evaluator that returns fixed metrics for testing."""

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        return {"hit_rate": 1.0, "mrr": 0.5}


class SequenceEvaluator(BaseEvaluator):
    """Evaluator that returns or raises exact per-call outcomes."""

    def __init__(self, outcomes: List[Any]) -> None:
        self.outcomes = list(outcomes)
        self.call_count = 0

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class DeclaredFakeEvaluator(CustomEvaluator):
    """Fake child exposing metrics through CustomEvaluator's exact interface."""

    def __init__(self, metrics: List[str], outcome: Any) -> None:
        self.metrics = list(metrics)
        self.outcome = outcome
        self.call_count = 0

    def evaluate(
        self,
        query: str,
        retrieved_chunks: List[Any],
        generated_answer: Optional[str] = None,
        ground_truth: Optional[Any] = None,
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        self.call_count += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _search_with(*outcomes: Any) -> MagicMock:
    search = MagicMock()
    search.search.side_effect = list(outcomes)
    return search


def _write_golden_json(path: Path, test_cases: List[Dict]) -> None:
    data = {"test_cases": test_cases}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ── Tests: load_test_set ──────────────────────────────────────────


class TestLoadTestSet:
    def test_load_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "golden.json"
        _write_golden_json(f, [
            {"query": "What is RAG?", "expected_chunk_ids": ["c1"]},
            {"query": "How does BM25 work?"},
        ])

        cases = load_test_set(f)

        assert len(cases) == 2
        assert cases[0].query == "What is RAG?"
        assert cases[0].expected_chunk_ids == ["c1"]
        assert cases[1].expected_chunk_ids == []

    def test_load_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_test_set("nonexistent.json")

    def test_load_invalid_format_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text('{"wrong_key": []}', encoding="utf-8")

        with pytest.raises(ValueError, match="missing 'test_cases'"):
            load_test_set(f)


# ── Tests: TestCase ───────────────────────────────────────────────


class TestGoldenTestCase:
    def test_from_dict_full(self) -> None:
        tc = GoldenTestCase.from_dict({
            "query": "Q",
            "expected_chunk_ids": ["a", "b"],
            "expected_sources": ["doc.pdf"],
            "reference_answer": "Answer",
        })
        assert tc.query == "Q"
        assert tc.expected_chunk_ids == ["a", "b"]
        assert tc.expected_sources == ["doc.pdf"]
        assert tc.reference_answer == "Answer"

    def test_from_dict_minimal(self) -> None:
        tc = GoldenTestCase.from_dict({"query": "Q"})
        assert tc.expected_chunk_ids == []
        assert tc.reference_answer is None


# ── Tests: EvalRunner ─────────────────────────────────────────────


class TestEvalRunner:
    def test_run_without_evaluator_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [{"query": "Q"}])

        runner = EvalRunner(evaluator=None)
        with pytest.raises(ValueError, match="requires an evaluator"):
            runner.run(f)

    def test_run_empty_test_set_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [])

        runner = EvalRunner(evaluator=StubEvaluator())
        with pytest.raises(ValueError, match="empty"):
            runner.run(f)

    def test_run_with_stub_evaluator(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "What is RAG?"},
            {"query": "How does hybrid search work?"},
        ])

        runner = EvalRunner(evaluator=StubEvaluator())
        report = runner.run(f)

        assert isinstance(report, EvalReport)
        assert len(report.query_results) == 2
        assert report.aggregate_metrics["hit_rate"] == 1.0
        assert report.aggregate_metrics["mrr"] == 0.5
        assert report.total_elapsed_ms > 0

    def test_run_with_hybrid_search(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "RAG", "expected_chunk_ids": ["c1"]},
        ])

        mock_search = MagicMock()
        mock_search.search.return_value = [
            MagicMock(chunk_id="c1", text="RAG is...", score=0.9),
        ]

        runner = EvalRunner(
            hybrid_search=mock_search,
            evaluator=StubEvaluator(),
        )
        report = runner.run(f)

        assert len(report.query_results) == 1
        assert report.query_results[0].retrieved_chunk_ids == ["c1"]

    def test_custom_evaluator_metric_declarations_are_preserved(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "RAG", "expected_chunk_ids": ["c1"]},
        ])
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "RAG is..."}]),
            evaluator=CustomEvaluator(metrics=["hit_rate", "mrr"]),
        )

        report = runner.run(f)

        assert report.expected_metrics == ["hit_rate", "mrr"]
        assert report.aggregate_metrics == {"hit_rate": 1.0, "mrr": 1.0}
        assert report.metric_measurements["hit_rate"]["total"] == 1
        assert report.metric_measurements["mrr"]["observed"] == 1

    def test_run_with_answer_generator(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [{"query": "Q"}])

        def gen(query, chunks):
            return f"Generated answer for: {query}"

        runner = EvalRunner(
            evaluator=StubEvaluator(),
            answer_generator=gen,
        )
        report = runner.run(f)

        assert "Generated answer for: Q" == report.query_results[0].generated_answer
        assert report.query_results[0].answer_measurement.status == "observed"

    @pytest.mark.parametrize(
        "invalid_answer",
        [None, "", " \t", b"answer", {"answer": "text"}],
        ids=["none", "empty", "whitespace", "bytes", "dict"],
    )
    def test_invalid_generator_result_is_failed_and_skips_answer_evaluator(
        self,
        tmp_path: Path,
        invalid_answer: Any,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        answer_child = DeclaredFakeEvaluator(
            ["faithfulness"],
            AssertionError("answer evaluator must not run"),
        )
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=answer_child,
            answer_generator=lambda query, chunks: invalid_answer,
        )

        result = runner.run(f).query_results[0]

        assert result.generated_answer is None
        assert result.answer_measurement.status == "failed_to_measure"
        assert result.answer_measurement.mode == "answer_generator"
        assert result.answer_measurement.error_category == "InvalidAnswerValue"
        assert result.metric_measurements["faithfulness"] == "failed_to_measure"
        assert result.evaluator_measurement.status == "not_applicable"
        assert answer_child.call_count == 0

    @pytest.mark.parametrize(
        "invalid_answer",
        [None, "", " \t", b"answer", {"answer": "text"}],
        ids=["none", "empty", "whitespace", "bytes", "dict"],
    )
    def test_invalid_override_is_failed_and_skips_answer_evaluator(
        self,
        tmp_path: Path,
        invalid_answer: Any,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        answer_child = DeclaredFakeEvaluator(
            ["faithfulness"],
            AssertionError("answer evaluator must not run"),
        )
        generator = MagicMock(return_value="valid generated answer")
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=answer_child,
            answer_generator=generator,
            answer_overrides={0: invalid_answer},
        )

        result = runner.run(f).query_results[0]

        assert result.generated_answer is None
        assert result.answer_measurement.status == "failed_to_measure"
        assert result.answer_measurement.mode == "answer_override"
        assert result.answer_measurement.error_category == "InvalidAnswerValue"
        assert result.metric_measurements["faithfulness"] == "failed_to_measure"
        assert result.evaluator_measurement.status == "not_applicable"
        assert answer_child.call_count == 0
        generator.assert_not_called()

    def test_valid_override_is_observed(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        answer_child = DeclaredFakeEvaluator(
            ["faithfulness"],
            {"faithfulness": 0.75},
        )
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=answer_child,
            answer_overrides={0: "controlled answer"},
        )

        result = runner.run(f).query_results[0]

        assert result.generated_answer == "controlled answer"
        assert result.answer_measurement.status == "observed"
        assert result.answer_measurement.mode == "answer_override"
        assert result.metrics == {"faithfulness": 0.75}

    def test_report_to_dict(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [{"query": "Q"}])

        runner = EvalRunner(evaluator=StubEvaluator())
        report = runner.run(f)

        d = report.to_dict()
        assert "aggregate_metrics" in d
        assert "query_results" in d
        assert d["query_count"] == 1
        assert d["evaluator_name"] == "StubEvaluator"

    def test_evaluator_exception_keeps_metric_denominator(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        evaluator = SequenceEvaluator([RuntimeError("judge unavailable")])
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=evaluator,
            answer_generator=lambda query, chunks: "controlled answer",
            expected_metrics=["hit_rate"],
        )

        report = runner.run(f)
        result = report.query_results[0]

        assert result.case_index == 0
        assert result.evaluator_measurement.status == "failed_to_measure"
        assert result.evaluator_measurement.error_category == "RuntimeError"
        assert result.metric_measurements == {"hit_rate": "failed_to_measure"}
        assert report.aggregate_metrics == {}
        assert report.metric_measurements["hit_rate"] == {
            "total": 1,
            "applicable": 1,
            "observed": 0,
            "scored": 0,
            "failed_to_measure": 1,
            "not_applicable": 0,
        }

    def test_empty_metrics_are_measurement_failure(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=SequenceEvaluator([{}]),
            answer_generator=lambda query, chunks: "controlled answer",
            expected_metrics=["hit_rate"],
        )

        result = runner.run(f).query_results[0]

        assert result.evaluator_measurement.status == "failed_to_measure"
        assert result.evaluator_measurement.error_category == "MissingMetrics"
        assert result.metric_measurements["hit_rate"] == "failed_to_measure"

    def test_partial_metrics_keep_each_case_in_denominator(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q1", "expected_chunk_ids": ["c1"]},
            {"query": "Q2", "expected_chunk_ids": ["c2"]},
        ])
        evaluator = SequenceEvaluator([
            {"hit_rate": 1.0, "mrr": 0.5},
            {"hit_rate": 0.0},
        ])
        runner = EvalRunner(
            hybrid_search=_search_with(
                [{"id": "c1", "text": "one"}],
                [{"id": "other", "text": "two"}],
            ),
            evaluator=evaluator,
            answer_generator=lambda query, chunks: "controlled answer",
            expected_metrics=["hit_rate", "mrr"],
        )

        report = runner.run(f)

        assert report.aggregate_metrics == {"hit_rate": 0.5, "mrr": 0.5}
        assert report.metric_measurements["hit_rate"]["observed"] == 2
        assert report.metric_measurements["hit_rate"]["failed_to_measure"] == 0
        assert report.metric_measurements["mrr"] == {
            "total": 2,
            "applicable": 2,
            "observed": 1,
            "scored": 1,
            "failed_to_measure": 1,
            "not_applicable": 0,
        }
        assert report.query_results[1].metric_measurements["mrr"] == "failed_to_measure"

    def test_retrieval_exception_differs_from_observed_empty_result(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "fails", "expected_chunk_ids": ["c1"]},
            {"query": "empty", "expected_chunk_ids": ["c2"]},
        ])
        evaluator = SequenceEvaluator([{"hit_rate": 0.0}])
        runner = EvalRunner(
            hybrid_search=_search_with(TimeoutError("retrieval timed out"), []),
            evaluator=evaluator,
            answer_generator=lambda query, chunks: "controlled answer",
            expected_metrics=["hit_rate"],
        )

        report = runner.run(f)
        failed, empty = report.query_results

        assert failed.case_index == 0
        assert failed.query == "fails"
        assert failed.retrieval_measurement.status == "failed_to_measure"
        assert failed.retrieval_measurement.error_category == "TimeoutError"
        assert failed.metric_measurements["hit_rate"] == "failed_to_measure"
        assert empty.retrieval_measurement.status == "observed"
        assert empty.retrieval_measurement.mode == "empty"
        assert empty.metric_measurements["hit_rate"] == "observed"
        assert empty.metrics["hit_rate"] == 0.0
        assert evaluator.call_count == 1
        assert report.metric_measurements["hit_rate"]["total"] == 2
        assert report.metric_measurements["hit_rate"]["observed"] == 1
        assert report.metric_measurements["hit_rate"]["failed_to_measure"] == 1

    def test_answer_generator_exception_is_not_replaced_by_synthetic_answer(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        evaluator = SequenceEvaluator([{"faithfulness": 1.0}])

        def fail_generation(query: str, chunks: List[Any]) -> str:
            raise ConnectionError("generator offline")

        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=evaluator,
            answer_generator=fail_generation,
            expected_metrics=["faithfulness"],
        )

        report = runner.run(f)
        result = report.query_results[0]

        assert result.generated_answer is None
        assert result.answer_measurement.status == "failed_to_measure"
        assert result.answer_measurement.error_category == "ConnectionError"
        assert result.metric_measurements["faithfulness"] == "failed_to_measure"
        assert result.evaluator_measurement.status == "not_applicable"
        assert evaluator.call_count == 0
        assert "faithfulness" not in report.aggregate_metrics

    def test_no_generator_marks_synthetic_and_excludes_answer_quality(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        evaluator = SequenceEvaluator([{
            "hit_rate": 1.0,
            "faithfulness": 1.0,
        }])
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=evaluator,
            expected_metrics=["hit_rate", "faithfulness"],
        )

        report = runner.run(f)
        result = report.query_results[0]

        assert result.generated_answer == "context"
        assert result.answer_measurement.status == "not_applicable"
        assert result.answer_measurement.mode == "synthetic_fallback"
        assert result.metric_measurements["hit_rate"] == "observed"
        assert result.metric_measurements["faithfulness"] == "not_applicable"
        assert report.aggregate_metrics == {"hit_rate": 1.0}
        assert report.metric_measurements["faithfulness"]["not_applicable"] == 1

    def test_synthetic_answer_filters_composite_child_before_invocation(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        retrieval_child = DeclaredFakeEvaluator(
            ["hit_rate"],
            {"hit_rate": 1.0},
        )
        answer_child = DeclaredFakeEvaluator(
            ["faithfulness"],
            AssertionError("answer child must be filtered before invocation"),
        )
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=CompositeEvaluator(
                evaluators=[retrieval_child, answer_child]
            ),
        )

        result = runner.run(f).query_results[0]

        assert result.answer_measurement.mode == "synthetic_fallback"
        assert retrieval_child.call_count == 1
        assert answer_child.call_count == 0
        assert result.metrics == {"hit_rate": 1.0}
        assert result.metric_measurements == {
            "hit_rate": "observed",
            "faithfulness": "not_applicable",
        }
        assert result.evaluator_measurement.status == "observed"

    def test_composite_runner_merge_and_duplicate_metric_last_wins(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        first = DeclaredFakeEvaluator(
            ["hit_rate", "mrr"],
            {"hit_rate": 0.0, "mrr": 0.5},
        )
        later = DeclaredFakeEvaluator(
            ["hit_rate"],
            {"hit_rate": 1.0},
        )
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=CompositeEvaluator(evaluators=[first, later]),
        )

        result = runner.run(f).query_results[0]

        assert first.call_count == 1
        assert later.call_count == 1
        assert result.metrics == {"hit_rate": 1.0, "mrr": 0.5}
        assert result.evaluator_measurement.status == "observed"

    def test_composite_partial_failure_preserves_child_error(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        success = DeclaredFakeEvaluator(["hit_rate"], {"hit_rate": 1.0})
        failure = DeclaredFakeEvaluator(["mrr"], ValueError("mrr unavailable"))
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=CompositeEvaluator(evaluators=[success, failure]),
        )

        result = runner.run(f).query_results[0]

        assert result.metrics == {"hit_rate": 1.0}
        assert result.metric_measurements["hit_rate"] == "observed"
        assert result.metric_measurements["mrr"] == "failed_to_measure"
        assert result.evaluator_measurement.status == "failed_to_measure"
        assert result.evaluator_measurement.error_category == "ValueError"
        assert result.evaluator_measurement.error_message == (
            "DeclaredFakeEvaluator failed: mrr unavailable"
        )

    def test_composite_all_failed_keeps_runtime_error_semantics(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        first = DeclaredFakeEvaluator(["hit_rate"], RuntimeError("first failed"))
        second = DeclaredFakeEvaluator(["mrr"], ValueError("second failed"))
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=CompositeEvaluator(evaluators=[first, second]),
        )

        result = runner.run(f).query_results[0]

        assert result.metrics == {}
        assert result.metric_measurements == {
            "hit_rate": "failed_to_measure",
            "mrr": "failed_to_measure",
        }
        assert result.evaluator_measurement.status == "failed_to_measure"
        assert result.evaluator_measurement.error_category == "RuntimeError"
        assert result.evaluator_measurement.error_message is not None
        assert result.evaluator_measurement.error_message.startswith(
            "All sub-evaluators failed:\n"
        )
        assert "DeclaredFakeEvaluator failed: first failed" in (
            result.evaluator_measurement.error_message
        )
        assert "DeclaredFakeEvaluator failed: second failed" in (
            result.evaluator_measurement.error_message
        )

    def test_missing_ground_truth_is_not_applicable_not_low_score(
        self,
        tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [{"query": "Q"}])
        evaluator = SequenceEvaluator([{"hit_rate": 0.0}])
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=evaluator,
            expected_metrics=["hit_rate"],
        )

        report = runner.run(f)

        assert evaluator.call_count == 0
        assert report.query_results[0].metric_measurements["hit_rate"] == "not_applicable"
        assert report.aggregate_metrics == {}
        assert report.metric_measurements["hit_rate"] == {
            "total": 1,
            "applicable": 0,
            "observed": 0,
            "scored": 0,
            "failed_to_measure": 0,
            "not_applicable": 1,
        }

    def test_report_measurement_state_json_round_trip(self, tmp_path: Path) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q", "expected_chunk_ids": ["c1"]},
        ])
        runner = EvalRunner(
            hybrid_search=_search_with([{"id": "c1", "text": "context"}]),
            evaluator=SequenceEvaluator([{"hit_rate": 0.25}]),
            answer_generator=lambda query, chunks: "controlled answer",
            expected_metrics=["hit_rate"],
        )

        report_dict = runner.run(f).to_dict()
        round_tripped = json.loads(json.dumps(report_dict))

        assert round_tripped == report_dict
        assert round_tripped["query_results"][0]["case_index"] == 0
        assert round_tripped["query_results"][0]["retrieval_measurement"]["status"] == "observed"
        assert round_tripped["metric_measurements"]["hit_rate"]["scored"] == 1


class TestEvalRunnerAggregation:
    """Test metric aggregation logic."""

    def test_existing_positional_dataclass_fields_remain_compatible(self) -> None:
        result = QueryResult("q", ["c1"], "answer", {"hit_rate": 1.0}, 2.0)
        report = EvalReport([result], {"hit_rate": 1.0}, 3.0, "Stub", "g.json")

        assert result.retrieved_chunk_ids == ["c1"]
        assert result.elapsed_ms == 2.0
        assert report.total_elapsed_ms == 3.0
        assert report.evaluator_name == "Stub"
        assert report.test_set_path == "g.json"

    def test_aggregate_averages_correctly(self) -> None:
        results = [
            QueryResult(query="q1", metrics={"hit_rate": 1.0, "mrr": 1.0}),
            QueryResult(query="q2", metrics={"hit_rate": 0.0, "mrr": 0.5}),
        ]

        avg = EvalRunner._aggregate_metrics(results)

        assert avg["hit_rate"] == pytest.approx(0.5)
        assert avg["mrr"] == pytest.approx(0.75)

    def test_aggregate_empty_returns_empty(self) -> None:
        assert EvalRunner._aggregate_metrics([]) == {}

    def test_aggregate_partial_metrics(self) -> None:
        """When some queries have metrics that others don't."""
        results = [
            QueryResult(query="q1", metrics={"hit_rate": 1.0}),
            QueryResult(query="q2", metrics={"faithfulness": 0.9}),
        ]

        avg = EvalRunner._aggregate_metrics(results)

        # Each metric averaged over only the queries that produced it
        assert avg["hit_rate"] == 1.0
        assert avg["faithfulness"] == 0.9


# ── Tests: Golden test set fixture ────────────────────────────────


class TestGoldenTestSetFixture:
    """Validate the actual golden test set file exists and is valid."""

    def test_golden_set_loads(self) -> None:
        golden_path = Path("tests/fixtures/golden_test_set.json")
        if not golden_path.exists():
            pytest.skip("Golden test set not present")

        cases = load_test_set(golden_path)
        assert len(cases) >= 1
        for tc in cases:
            assert tc.query.strip(), "Query must be non-empty"
