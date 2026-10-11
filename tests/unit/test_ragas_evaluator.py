"""Unit tests for RagasEvaluator.

Tests verify:
- Initialization with valid/invalid metrics
- ImportError handling when ragas is not installed
- Input validation (missing answer, empty query, etc.)
- Metric extraction from settings
- Text extraction from various chunk formats

Note: Actual Ragas evaluation (LLM calls) is mocked to keep unit tests fast
and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest


class TestRagasEvaluatorInit:
    """Tests for RagasEvaluator initialisation."""

    def test_init_default_metrics(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator()
        assert set(evaluator._metric_names) == {
            "answer_relevancy",
            "context_precision",
            "faithfulness",
        }

    def test_init_custom_metrics(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        assert evaluator._metric_names == ["faithfulness"]

    def test_init_unsupported_metric_raises(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        with pytest.raises(ValueError, match="Unsupported ragas metrics"):
            RagasEvaluator(metrics=["hit_rate"])

    def test_init_reads_metrics_from_settings(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        settings = MagicMock()
        settings.evaluation.metrics = ["faithfulness", "answer_relevancy", "hit_rate"]

        evaluator = RagasEvaluator(settings=settings)
        # hit_rate is not a ragas metric, should be filtered out
        assert "hit_rate" not in evaluator._metric_names
        assert "faithfulness" in evaluator._metric_names
        assert "answer_relevancy" in evaluator._metric_names

    def test_init_no_settings_defaults_to_all(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(settings=None, metrics=None)
        assert len(evaluator._metric_names) == 3


class TestRagasImportCheck:
    """Tests for ragas import validation."""

    def test_import_error_when_ragas_missing(self) -> None:
        from src.observability.evaluation.ragas_evaluator import _import_ragas

        with patch.dict("sys.modules", {"ragas": None}):
            with pytest.raises(ImportError, match="ragas"):
                _import_ragas()


class TestRagasEvaluatorValidation:
    """Tests for input validation in evaluate()."""

    def test_empty_query_raises(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        with pytest.raises(ValueError, match="Query cannot be empty"):
            evaluator.evaluate("  ", [{"text": "ctx"}], generated_answer="ans")

    def test_empty_chunks_raises(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        with pytest.raises(ValueError, match="retrieved_chunks cannot be empty"):
            evaluator.evaluate("query", [], generated_answer="ans")

    def test_missing_generated_answer_raises(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        with pytest.raises(ValueError, match="generated_answer"):
            evaluator.evaluate("query", [{"text": "ctx"}], generated_answer=None)

    def test_empty_generated_answer_raises(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        with pytest.raises(ValueError, match="generated_answer"):
            evaluator.evaluate("query", [{"text": "ctx"}], generated_answer="   ")


class TestRagasEvaluatorTextExtraction:
    """Tests for _extract_texts helper."""

    def test_extract_from_dicts(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        result = evaluator._extract_texts([
            {"text": "chunk1"},
            {"content": "chunk2"},
            {"page_content": "chunk3"},
        ])
        assert result == ["chunk1", "chunk2", "chunk3"]

    def test_extract_from_strings(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        result = evaluator._extract_texts(["chunk1", "chunk2"])
        assert result == ["chunk1", "chunk2"]

    def test_extract_from_objects(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])

        class Chunk:
            def __init__(self, text: str) -> None:
                self.text = text

        result = evaluator._extract_texts([Chunk("hello"), Chunk("world")])
        assert result == ["hello", "world"]


class TestRagasEvaluatorEvaluate:
    """Tests for evaluate() with mocked Ragas backend."""

    def _make_mock_ragas_result(self, scores: Dict[str, float]) -> MagicMock:
        """Create a mock ragas evaluation result."""
        import pandas as pd

        df = pd.DataFrame([scores])
        mock_result = MagicMock()
        mock_result.to_pandas.return_value = df
        return mock_result

    def test_evaluate_returns_metrics_dict(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness", "context_precision"])

        expected = {"faithfulness": 0.92, "context_precision": 0.85}
        evaluator._run_ragas = MagicMock(return_value=expected)  # type: ignore[method-assign]

        result = evaluator.evaluate(
            query="What is RAG?",
            retrieved_chunks=["RAG is retrieval augmented generation."],
            generated_answer="RAG stands for Retrieval Augmented Generation.",
        )

        assert result == expected

    def test_evaluate_with_mocked_run_ragas(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness", "answer_relevancy"])

        expected_scores = {"faithfulness": 0.95, "answer_relevancy": 0.88}
        evaluator._run_ragas = MagicMock(return_value=expected_scores)  # type: ignore[method-assign]

        result = evaluator.evaluate(
            query="What is RAG?",
            retrieved_chunks=[{"text": "RAG is Retrieval Augmented Generation"}],
            generated_answer="RAG stands for Retrieval Augmented Generation.",
        )

        assert result == expected_scores
        evaluator._run_ragas.assert_called_once()

    def test_evaluate_runtime_error_on_ragas_failure(self) -> None:
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        evaluator._run_ragas = MagicMock(  # type: ignore[method-assign]
            side_effect=Exception("LLM call failed"),
        )

        with pytest.raises(RuntimeError, match="Ragas evaluation failed"):
            evaluator.evaluate(
                query="test",
                retrieved_chunks=[{"text": "ctx"}],
                generated_answer="answer",
            )

    def test_ground_truth_is_ignored(self) -> None:
        """Ragas should work fine even when ground_truth is provided."""
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness"])
        evaluator._run_ragas = MagicMock(return_value={"faithfulness": 0.9})  # type: ignore[method-assign]

        result = evaluator.evaluate(
            query="test",
            retrieved_chunks=[{"text": "ctx"}],
            generated_answer="answer",
            ground_truth=["chunk_001"],  # should be ignored
        )

        assert "faithfulness" in result


class TestRagasEvaluatorFactory:
    """Tests for factory integration."""

    def test_factory_creates_ragas_evaluator(self) -> None:
        from src.libs.evaluator.evaluator_factory import EvaluatorFactory
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        settings = MagicMock()
        settings.evaluation.enabled = True
        settings.evaluation.provider = "ragas"
        settings.evaluation.metrics = ["faithfulness"]

        evaluator = EvaluatorFactory.create(settings)
        assert isinstance(evaluator, RagasEvaluator)

    def test_factory_lists_ragas(self) -> None:
        from src.libs.evaluator.evaluator_factory import EvaluatorFactory

        providers = EvaluatorFactory.list_providers()
        assert "custom" in providers
        # ragas may be in _PROVIDERS after first create or in _LAZY_PROVIDERS


class TestRagasResultMeasurements:
    """Exercise native result parsing without constructing a model or judge."""

    @staticmethod
    def _evaluator(monkeypatch, *, faithfulness, precision=0.75):
        from ragas.metrics import collections

        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=["faithfulness", "context_precision"])
        llm = SimpleNamespace(client=SimpleNamespace(client=SimpleNamespace(close=AsyncMock())))
        embeddings = SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
        monkeypatch.setattr(evaluator, "_build_wrappers", lambda: (llm, embeddings))
        for name, value in (("Faithfulness", faithfulness),
                            ("ContextPrecisionWithoutReference", precision)):
            metric = MagicMock()
            if isinstance(value, Exception):
                metric.ascore = AsyncMock(side_effect=value)
            else:
                metric.ascore = AsyncMock(return_value=SimpleNamespace(value=value))
            monkeypatch.setattr(collections, name, MagicMock(return_value=metric))
        return evaluator

    @pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf")],
                             ids=["missing", "nan", "positive-infinity", "negative-infinity"])
    def test_invalid_native_result_is_not_a_score(self, monkeypatch, value):
        evaluator = self._evaluator(monkeypatch, faithfulness=value)
        assert evaluator.evaluate("question", ["context"], "actual answer") == {
            "context_precision": 0.75,
        }

    @pytest.mark.parametrize("value", [0.0, 0.5])
    def test_measured_zero_and_finite_native_result_are_preserved(self, monkeypatch, value):
        evaluator = self._evaluator(monkeypatch, faithfulness=value)
        assert evaluator.evaluate("question", ["context"], "actual answer") == {
            "faithfulness": value, "context_precision": 0.75,
        }

    @pytest.mark.parametrize("value", [None, float("nan"), RuntimeError("judge unavailable")],
                             ids=["missing", "nonfinite", "exception"])
    def test_native_failure_and_true_zero_keep_distinct_runner_denominators(
        self, monkeypatch, tmp_path: Path, value,
    ):
        from src.observability.evaluation.eval_runner import EvalRunner

        evaluator = self._evaluator(monkeypatch, faithfulness=0.0, precision=value)
        test_set = tmp_path / "measurement.json"
        test_set.write_text(json.dumps({"test_cases": [{"query": "question"}]}), encoding="utf-8")
        search = SimpleNamespace(search=lambda **kwargs: [{"id": "context-1", "text": "context"}])
        report = EvalRunner(hybrid_search=search, evaluator=evaluator,
                            answer_generator=lambda query, chunks: "actual answer").run(test_set)
        result = report.query_results[0]
        assert result.metric_measurements["context_precision"] == "failed_to_measure"
        assert "context_precision" not in report.aggregate_metrics
        assert report.metric_measurements["context_precision"] == {
            "total": 1, "applicable": 1, "observed": 0, "scored": 0,
            "failed_to_measure": 1, "not_applicable": 0,
        }
        if isinstance(value, Exception):
            assert result.evaluator_measurement.error_category == "RuntimeError"
            assert "judge unavailable" in result.evaluator_measurement.error_message
            assert report.aggregate_metrics == {}
        else:
            assert result.metric_measurements["faithfulness"] == "observed"
            assert report.aggregate_metrics == {"faithfulness": 0.0}
            assert report.metric_measurements["faithfulness"]["scored"] == 1
        # Reports remain strict JSON: missing/nonfinite results are never emitted as values.
        json.dumps(report.to_dict(), allow_nan=False)

    def test_empty_context_measures_only_answer_relevancy(self, monkeypatch):
        from ragas.metrics import collections

        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        evaluator = RagasEvaluator(metrics=[
            "faithfulness", "answer_relevancy", "context_precision",
        ])
        llm = SimpleNamespace(client=SimpleNamespace(client=SimpleNamespace(close=AsyncMock())))
        embeddings = SimpleNamespace(client=SimpleNamespace(close=AsyncMock()))
        monkeypatch.setattr(evaluator, "_build_wrappers", lambda: (llm, embeddings))
        relevancy = MagicMock()
        relevancy.ascore = AsyncMock(return_value=SimpleNamespace(value=0.0))
        monkeypatch.setattr(collections, "AnswerRelevancy", MagicMock(return_value=relevancy))
        faithfulness = MagicMock()
        precision = MagicMock()
        monkeypatch.setattr(collections, "Faithfulness", faithfulness)
        monkeypatch.setattr(collections, "ContextPrecisionWithoutReference", precision)

        assert evaluator.evaluate("question", [], "answer without retrieved evidence") == {
            "answer_relevancy": 0.0,
        }
        relevancy.ascore.assert_awaited_once_with(
            user_input="question", response="answer without retrieved evidence",
        )
        faithfulness.assert_not_called()
        precision.assert_not_called()


class TestRagasProviderTransport:
    """Keep Ragas, Instructor and the SDK real; replace HTTP transport only."""

    @staticmethod
    def _settings(**llm_overrides):
        from src.core.settings import EmbeddingSettings, LLMSettings

        return SimpleNamespace(
            llm=LLMSettings(**{
                "provider": "openai", "model": "judge-model", "api_key": "test-key",
                "base_url": "https://judge.example.test/v1", "temperature": 0.25,
                "max_tokens": 321, **llm_overrides,
            }),
            embedding=EmbeddingSettings(
                provider="openai", model="embedding-model", api_key="test-key",
                base_url="https://embedding.example.test/v1", dimensions=2,
            ),
        )

    @staticmethod
    def _transport(monkeypatch, *, replies=None, status=200):
        import httpx

        monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")
        requests = []
        replies = iter(replies) if replies is not None else None

        async def send(client, request, **kwargs):
            body = json.loads(request.content)
            requests.append((request, body))
            if status != 200:
                return httpx.Response(status, json={"error": {"message": "judge unavailable"}},
                                      request=request)
            if request.url.path.endswith("/embeddings"):
                inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
                payload = {"object": "list", "model": body["model"], "data": [
                    {"object": "embedding", "index": i, "embedding": [0.6, 0.8]}
                    for i in range(len(inputs))
                ], "usage": {"prompt_tokens": 1, "total_tokens": 1}}
            else:
                reply = next(replies) if replies is not None else {"verdict": 1}
                payload = {"id": "test-completion", "object": "chat.completion",
                           "created": 0, "model": body["model"], "choices": [{
                               "index": 0, "finish_reason": "stop", "message": {
                                   "role": "assistant", "content": json.dumps(reply),
                               },
                           }]}
            return httpx.Response(200, json=payload, request=request)

        monkeypatch.setattr(httpx.AsyncClient, "send", send)
        return requests

    @pytest.mark.parametrize("field, expected", [
        ("url", "https://judge.example.test/v1/chat/completions"),
        ("model", "judge-model"), ("temperature", 0.25), ("max_tokens", 321),
    ])
    def test_judge_configuration_reaches_native_request(self, monkeypatch, field, expected):
        from pydantic import BaseModel

        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        class Decision(BaseModel):
            verdict: int

        requests = self._transport(monkeypatch)
        evaluator = RagasEvaluator(settings=self._settings(), metrics=["faithfulness"])
        llm, _ = evaluator._build_wrappers()
        assert llm.generate("Is the supplied answer supported?", Decision).verdict == 1
        assert len(requests) == 1
        request, body = requests[0]
        assert (str(request.url) if field == "url" else body[field]) == expected

    def test_embedding_endpoint_and_model_reach_native_request(self, monkeypatch):
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        requests = self._transport(monkeypatch)
        evaluator = RagasEvaluator(settings=self._settings(), metrics=["answer_relevancy"])
        _, embeddings = evaluator._build_wrappers()
        assert embeddings.embed_text("What time does the library open?") == [0.6, 0.8]
        assert len(requests) == 1
        request, body = requests[0]
        assert str(request.url) == "https://embedding.example.test/v1/embeddings"
        assert body["model"] == "embedding-model"
        assert body["input"] == "What time does the library open?"

    @pytest.mark.parametrize("provider", ["azure", "openai"])
    def test_azure_deployment_is_used_for_judge_and_embedding(self, monkeypatch, provider):
        from dataclasses import replace

        from pydantic import BaseModel

        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        class Decision(BaseModel):
            verdict: int

        settings = self._settings(provider=provider, base_url=None,
                                  azure_endpoint="https://judge.azure.example.test",
                                  deployment_name="judge-deployment", api_version="2024-02-15-preview")
        settings.embedding = replace(
            settings.embedding, provider=provider, base_url=None,
            azure_endpoint="https://embedding.azure.example.test",
            deployment_name="embedding-deployment", api_version="2024-02-15-preview",
        )
        requests = self._transport(monkeypatch)
        llm, embeddings = RagasEvaluator(settings, metrics=["answer_relevancy"])._build_wrappers()
        assert llm.generate("Judge this answer", Decision).verdict == 1
        assert embeddings.embed_text("A question") == [0.6, 0.8]
        assert [body["model"] for _, body in requests] == ["judge-deployment", "embedding-deployment"]
        assert [request.url.path for request, _ in requests] == [
            "/openai/deployments/judge-deployment/chat/completions",
            "/openai/deployments/embedding-deployment/embeddings",
        ]
        assert all(request.url.params["api-version"] == "2024-02-15-preview"
                   for request, _ in requests)

    def test_metrics_without_embeddings_do_not_require_embedding_configuration(self, monkeypatch):
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        settings = self._settings()
        del settings.embedding
        self._transport(monkeypatch)
        _, embeddings = RagasEvaluator(settings, metrics=["faithfulness"])._build_wrappers()
        assert embeddings is None

    @pytest.mark.parametrize("status, replies", [(503, None), (200, [{"invalid": True}])])
    def test_first_request_failure_is_not_retried(self, monkeypatch, status, replies):
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        requests = self._transport(monkeypatch, status=status, replies=replies)
        evaluator = RagasEvaluator(self._settings(), metrics=["faithfulness"])
        build_wrappers = evaluator._build_wrappers
        built = []

        def capture_wrappers():
            wrappers = build_wrappers()
            built.append(wrappers)
            return wrappers

        monkeypatch.setattr(evaluator, "_build_wrappers", capture_wrappers)
        with pytest.raises(RuntimeError, match="Ragas evaluation failed"):
            evaluator.evaluate("What time does the library open?", ["It opens at 9."], "At 9.")
        assert len(requests) == 1
        assert built[0][0].client.client.is_closed()

    def test_all_metrics_use_native_scoring_with_bounded_requests(self, monkeypatch):
        from src.observability.evaluation.ragas_evaluator import RagasEvaluator

        question = "What time does the library open?"
        statement = "The library opens at 9."
        requests = self._transport(monkeypatch, replies=[
            {"statements": [statement]},
            {"statements": [{"statement": statement, "reason": "Explicit in context", "verdict": 1}]},
            *[{"question": question, "noncommittal": 0}] * 3,
            {"reason": "Contains opening hours", "verdict": 1},
            {"reason": "Contains closing hours only", "verdict": 0},
        ])
        evaluator = RagasEvaluator(self._settings(), metrics=[
            "faithfulness", "answer_relevancy", "context_precision",
        ])
        result = evaluator.evaluate(question, [statement, "The library closes at 5."], statement)
        assert result == pytest.approx({
            "faithfulness": 1.0, "answer_relevancy": 1.0, "context_precision": 1.0,
        })
        judge_requests = [body for request, body in requests if request.url.host == "judge.example.test"]
        embedding_requests = [body for request, body in requests
                              if request.url.host == "embedding.example.test"]
        assert len(judge_requests) == 7
        assert len(embedding_requests) == 2
        assert all(body["max_tokens"] == 321 and body["temperature"] == 0.25
                   and body["response_format"] == {"type": "json_object"} for body in judge_requests)
        assert [body["input"] for body in embedding_requests] == [question, [question] * 3]
