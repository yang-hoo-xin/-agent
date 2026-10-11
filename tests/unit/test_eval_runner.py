"""Unit tests for EvalRunner and golden test set loading."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.core.types import RetrievalResult
from src.libs.evaluator.base_evaluator import BaseEvaluator
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.observability.evaluation.composite_evaluator import CompositeEvaluator
from src.observability.evaluation.eval_runner import (
    EvalReport,
    EvalRunner,
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

    @pytest.mark.parametrize("outcome", [{"faithfulness": 0.0}, RuntimeError("judge offline")])
    def test_report_preserves_exact_consumed_contexts_and_run_metadata(
        self, tmp_path: Path, outcome: Any,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [{"query": "Q", "reference_answer": "reference only"}])
        retrieved = [RetrievalResult(
            chunk_id="c1", text="  Exact context\n第二行。  ", score=0.123456789,
            metadata={"source_path": "public.txt", "section": {"lines": [2, 3]}},
        )]
        generator = MagicMock(return_value="actual answer")
        evaluator = SequenceEvaluator([outcome])
        evaluator.evaluate = MagicMock(wraps=evaluator.evaluate)
        metadata = {"generator": {"model": "fixture-model"}, "index_revision": "fixture-v1"}
        runner = EvalRunner(
            settings={"api_key": "must not be exported"},
            hybrid_search=_search_with(retrieved),
            answer_generator=generator, evaluator=evaluator,
            expected_metrics=["faithfulness"], synthetic_fallback=False,
        )

        report = runner.run(f, run_metadata=metadata)
        payload = report.to_dict()
        row = payload["query_results"][0]
        expected_context = retrieved[0].to_dict()

        assert generator.call_args.args == ("Q", retrieved)
        assert evaluator.evaluate.call_args.kwargs["retrieved_chunks"] is retrieved
        assert row["retrieved_contexts"] == [expected_context]
        assert row["retrieved_contexts"][0]["text"] == generator.call_args.args[1][0].text
        assert row["retrieved_contexts"][0]["text"] == (
            evaluator.evaluate.call_args.kwargs["retrieved_chunks"][0].text
        )
        assert row["reference_answer"] == "reference only"
        assert row["generated_answer"] == "actual answer"
        assert payload["run_metadata"] == metadata
        assert json.loads(json.dumps(payload, allow_nan=False)) == payload
        assert "must not be exported" not in json.dumps(payload)
        if isinstance(outcome, Exception):
            assert row["metrics"] == {}
            assert row["metric_measurements"]["faithfulness"] == "failed_to_measure"
            assert payload["measurement_status"] == "unmeasured"
        else:
            assert row["metrics"] == {"faithfulness": 0.0}
            assert row["metric_measurements"]["faithfulness"] == "observed"
            assert payload["measurement_status"] == "complete"

        # Later caller, retriever, or exported-dictionary mutations cannot rewrite evidence.
        metadata["generator"]["model"] = "changed"
        retrieved[0].text = "changed"
        retrieved[0].metadata["section"]["lines"].append(4)
        payload["run_metadata"]["generator"]["model"] = "changed again"
        row["retrieved_contexts"][0]["metadata"]["section"]["lines"].append(5)
        assert report.run_metadata["generator"]["model"] == "fixture-model"
        assert report.query_results[0].retrieved_contexts == [expected_context]

    @pytest.mark.parametrize("failed_stage", ["retrieval", "answer", "evaluator", None])
    def test_stop_on_failure_preserves_unattempted_cases_and_zero_scores_continue(
        self, tmp_path: Path, failed_stage: str | None,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [
            {"query": "Q1", "reference_answer": "reference one"},
            {"query": "Q2", "reference_answer": "reference two"},
        ])
        chunks = [{"chunk_id": "c1", "text": "context"}]
        failure = TimeoutError("provider timeout")
        search = _search_with(failure if failed_stage == "retrieval" else chunks, chunks)
        generator = MagicMock(side_effect=[
            failure if failed_stage == "answer" else "first answer", "second answer",
        ])
        evaluator = SequenceEvaluator([
            failure if failed_stage == "evaluator" else {"faithfulness": 0.0},
            {"faithfulness": 1.0},
        ])
        runner = EvalRunner(
            hybrid_search=search, answer_generator=generator, evaluator=evaluator,
            expected_metrics=["faithfulness"], synthetic_fallback=False,
        )

        report = runner.run(f, stop_on_failure=True)
        first, second = report.to_dict()["query_results"]

        assert [(row["case_index"], row["query"], row["reference_answer"])
                for row in (first, second)] == [
            (0, "Q1", "reference one"), (1, "Q2", "reference two"),
        ]
        assert report.metric_measurements["faithfulness"]["total"] == 2
        if failed_stage is None:
            assert search.search.call_count == generator.call_count == evaluator.call_count == 2
            assert first["metrics"] == {"faithfulness": 0.0}
            assert second["metrics"] == {"faithfulness": 1.0}
            assert report.metric_measurements["faithfulness"]["observed"] == 2
            assert report.aggregate_metrics == {"faithfulness": 0.5}
        else:
            assert search.search.call_count == 1
            assert generator.call_count == (0 if failed_stage == "retrieval" else 1)
            assert evaluator.call_count == (1 if failed_stage == "evaluator" else 0)
            assert first[f"{failed_stage}_measurement"]["status"] == "failed_to_measure"
            assert second["metrics"] == {}
            assert second["retrieved_contexts"] == []
            assert second["generated_answer"] is None
            for stage in ("retrieval_measurement", "answer_measurement", "evaluator_measurement"):
                assert second[stage]["status"] == "failed_to_measure"
                assert second[stage]["mode"] == "run_stopped"
                assert second[stage]["error_category"] == "PreviousCaseFailed"
                assert "not attempted" in second[stage]["error_message"]
            assert report.metric_measurements["faithfulness"]["failed_to_measure"] == 2
            assert report.metric_measurements["faithfulness"]["observed"] == 0
            assert report.aggregate_metrics == {}

    def test_actual_case_timestamps_leave_unattempted_and_legacy_results_empty(
        self, tmp_path: Path,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [{"query": "Q1"}, {"query": "Q2"}])
        runner = EvalRunner(
            hybrid_search=_search_with([{"chunk_id": "c1", "text": "context"}]),
            answer_generator=lambda query, chunks: "answer",
            evaluator=SequenceEvaluator([TimeoutError("judge timeout")]),
            expected_metrics=["faithfulness"], synthetic_fallback=False,
        )
        before = datetime.now(timezone.utc)

        report = runner.run(f, stop_on_failure=True)

        after = datetime.now(timezone.utc)
        actual, unattempted = report.to_dict()["query_results"]
        started = datetime.fromisoformat(actual["started_at"])
        finished = datetime.fromisoformat(actual["finished_at"])
        assert started.tzinfo == finished.tzinfo == timezone.utc
        assert before <= started <= finished <= after
        assert unattempted["started_at"] is None
        assert unattempted["finished_at"] is None
        legacy = QueryResult("Q", ["c1"], "answer", {"faithfulness": 0.0}, 2.0)
        assert legacy.elapsed_ms == 2.0
        assert legacy.started_at is legacy.finished_at is None

    @pytest.mark.parametrize("metadata", [{"bad": object()}, {"bad": float("nan")}, []])
    def test_invalid_run_metadata_fails_before_retrieval_or_models(
        self, tmp_path: Path, metadata: Any,
    ) -> None:
        f = tmp_path / "g.json"
        _write_golden_json(f, [{"query": "Q"}])
        search = _search_with([])
        generator = MagicMock(return_value="answer")
        evaluator = SequenceEvaluator([{"faithfulness": 1.0}])
        runner = EvalRunner(
            hybrid_search=search, answer_generator=generator, evaluator=evaluator,
        )

        with pytest.raises((TypeError, ValueError)):
            runner.run(f, run_metadata=metadata)

        search.search.assert_not_called()
        generator.assert_not_called()
        assert evaluator.call_count == 0


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


class TestPublicDiagnosticMetadataAndRagOff:
    def test_suite_and_case_provenance_are_preserved_without_becoming_answer_input(
        self, tmp_path: Path,
    ) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        path = tmp_path / "public.json"
        path.write_text(json.dumps({
            "description": "Public smoke set",
            "tier": "tier_0_public_smoke",
            "purpose": "Interface check",
            "source": {"url": "https://example.test/rfc", "sha256": "abc"},
            "authoring_origin": {"type": "codex_synthesized_from_public_source"},
            "human_verified": False,
            "answer_policy": "fixed",
            "citation_policy": "cite retrieved contexts",
            "test_cases": [{
                "query": "Question",
                "reference_answer": "REFERENCE_NOT_FOR_GENERATION",
                "source_sections": ["6"],
                "source_pages": [7],
                "diagnostic_types": ["single_hop"],
                "expected_behavior": "answer",
            }],
        }), encoding="utf-8")
        seen = []
        evaluator = RagasEvaluator(metrics=[
            "faithfulness", "answer_relevancy", "context_precision",
        ])
        evaluator.evaluate = MagicMock(return_value={"answer_relevancy": 0.0})
        runner = EvalRunner(
            hybrid_search=None,
            evaluator=evaluator,
            answer_generator=lambda query, contexts: seen.append((query, contexts)) or "answer",
        )

        report = runner.run(path, comparison_arm="rag_off")
        payload = report.to_dict()

        assert seen == [("Question", [])]
        assert payload["comparison_arm"] == "rag_off"
        assert payload["measurement_status"] == "complete"
        assert payload["test_set_metadata"] == {
            "description": "Public smoke set",
            "tier": "tier_0_public_smoke",
            "purpose": "Interface check",
            "source": {"url": "https://example.test/rfc", "sha256": "abc"},
            "authoring_origin": {"type": "codex_synthesized_from_public_source"},
            "human_verified": False,
            "answer_policy": "fixed",
            "citation_policy": "cite retrieved contexts",
        }
        row = payload["query_results"][0]
        assert row["reference_answer"] == "REFERENCE_NOT_FOR_GENERATION"
        assert row["case_metadata"] == {
            "source_sections": ["6"],
            "source_pages": [7],
            "diagnostic_types": ["single_hop"],
            "expected_behavior": "answer",
        }
        assert row["metric_measurements"] == {
            "faithfulness": "not_applicable",
            "answer_relevancy": "observed",
            "context_precision": "not_applicable",
        }
        assert row["metrics"] == {"answer_relevancy": 0.0}
        assert report.metric_measurements["answer_relevancy"]["scored"] == 1
        assert report.metric_measurements["faithfulness"]["not_applicable"] == 1
        evaluator.evaluate.assert_called_once_with(
            query="Question", retrieved_chunks=[], generated_answer="answer", ground_truth=None,
        )

    @pytest.mark.parametrize("fixture_name, tier, case_count", [
        ("rfc8259_public.json", "tier_0_public_smoke", 3),
        ("rfc8259_diagnostic.json", "tier_1_public_diagnostic", 10),
    ])
    def test_public_sets_have_explicit_nonhuman_origin(
        self, fixture_name: str, tier: str, case_count: int,
    ) -> None:
        path = Path("tests/fixtures/evaluation") / fixture_name
        data = json.loads(path.read_text(encoding="utf-8"))
        cases = load_test_set(path)

        assert data["tier"] == tier
        assert data["authoring_origin"]["type"] == "codex_synthesized_from_public_source"
        assert data["human_verified"] is False
        assert "Human-written" not in data["description"]
        assert len(cases) == case_count
        assert all(case.source_sections and case.source_pages for case in cases)
        assert all(case.diagnostic_types and case.expected_behavior for case in cases)

    def test_human_verified_requires_an_exact_boolean(self, tmp_path: Path) -> None:
        from src.observability.evaluation.eval_runner import load_test_set_metadata

        path = tmp_path / "invalid.json"
        path.write_text(json.dumps({
            "human_verified": "false", "test_cases": [{"query": "Question"}],
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="exact boolean"):
            load_test_set_metadata(path)

    def test_explicit_public_citation_policy_rejects_rag_off_fake_citation(
        self, tmp_path: Path,
    ) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        path = tmp_path / "rag-off.json"
        path.write_text(json.dumps({
            "citation_policy": "RAG-off answers must not invent retrieved citations.",
            "test_cases": [{"query": "Question"}],
        }), encoding="utf-8")
        evaluator = RagasEvaluator(metrics=["answer_relevancy"])
        evaluator.evaluate = MagicMock(return_value={"answer_relevancy": 1.0})
        runner = EvalRunner(
            hybrid_search=None,
            evaluator=evaluator,
            answer_generator=lambda query, contexts: "Unsupported [context:1]",
        )

        report = runner.run(path, comparison_arm="rag_off")
        result = report.query_results[0]

        assert result.generated_answer == "Unsupported [context:1]"
        assert result.answer_measurement.status == "observed"
        assert result.citation_measurement.status == "failed_to_measure"
        assert result.citation_measurement.error_category == "CitationWithoutContext"
        assert result.metric_measurements["answer_relevancy"] == "observed"
        assert report.aggregate_metrics == {"answer_relevancy": 1.0}
        assert report.measurement_status == "partial"
        evaluator.evaluate.assert_called_once_with(
            query="Question",
            retrieved_chunks=[],
            generated_answer="Unsupported [context:1]",
            ground_truth=None,
        )


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
