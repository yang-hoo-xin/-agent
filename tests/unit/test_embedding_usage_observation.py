"""Embedding costs stay bound to the call that actually produced them."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.core.trace.trace_context import TraceContext
from src.libs.embedding.openai_embedding import OpenAIEmbedding, OpenAIEmbeddingError
from src.libs.evaluator.custom_evaluator import CustomEvaluator
from src.observability.evaluation.eval_runner import EvalRunner


def provider(monkeypatch, outcomes):
    settings = SimpleNamespace(embedding=SimpleNamespace(
        model="bge-m3:latest", dimensions=3, base_url="http://127.0.0.1:11434/v1"))
    client = Mock()
    client.embeddings.create.side_effect = outcomes
    monkeypatch.setattr("openai.OpenAI", lambda **_kwargs: client)
    return OpenAIEmbedding(settings, api_key="test-secret"), client


def response(*, usage=True, rows=1):
    return SimpleNamespace(model="bge-m3:latest",
        usage=SimpleNamespace(prompt_tokens=7, total_tokens=7) if usage else None,
        data=[SimpleNamespace(embedding=[.1, .2, .3]) for _ in range(rows)])


def test_embedding_records_native_usage_without_changing_vectors_or_request(monkeypatch):
    embedding, client = provider(monkeypatch, [response()])
    trace = TraceContext()
    assert embedding.embed(["one query"], trace=trace) == [[.1, .2, .3]]
    client.embeddings.create.assert_called_once_with(input=["one query"], model="bge-m3:latest")
    observation = trace.get_stage_data("embedding")
    assert observation["usage"] == {"prompt_tokens": 7, "total_tokens": 7}
    assert observation["sdk_call_invoked"] and observation["response_received"]
    assert observation["http_attempt_count"] is None
    assert "test-secret" not in str(observation)


def test_bad_vector_count_retains_reported_cost_and_missing_usage_stays_unknown(monkeypatch):
    embedding, _ = provider(monkeypatch, [response(rows=0), response(usage=False)])
    failed, successful = TraceContext(), TraceContext()
    with pytest.raises(OpenAIEmbeddingError, match="length mismatch"):
        embedding.embed(["first"], trace=failed)
    embedding.embed(["second"], trace=successful)
    first, second = failed.get_stage_data("embedding"), successful.get_stage_data("embedding")
    assert first["usage"]["prompt_tokens"] == 7 and first["status"] == "failed"
    assert second["usage"] is None and second["status"] == "observed"
    assert first["invocation_id"] != second["invocation_id"]


def test_eval_runner_preserves_each_query_embedding_observation(monkeypatch, tmp_path):
    embedding, _ = provider(monkeypatch, [response(), RuntimeError("transport failed")])

    class Search:
        def search(self, query, top_k, trace=None):
            embedding.embed([query], trace=trace)
            return []

    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"test_cases": [{"query": "first"}, {"query": "second"}]}))
    report = EvalRunner(hybrid_search=Search(), evaluator=CustomEvaluator()).run(path)
    rows = report.to_dict()["query_results"]
    assert rows[0]["embedding_observations"][0]["usage"]["prompt_tokens"] == 7
    failed = rows[1]["embedding_observations"][0]
    assert failed["usage"] is None and failed["status"] == "failed"
    assert failed["sdk_call_invoked"] and not failed["response_received"]
    assert rows[1]["retrieval_measurement"]["status"] == "failed_to_measure"


def test_optional_trace_does_not_break_existing_search_interface(tmp_path):
    calls = []

    class LegacySearch:
        def search(self, query, top_k):
            calls.append(query)
            return []

    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"test_cases": [{"query": "query"}]}))
    row = EvalRunner(hybrid_search=LegacySearch(), evaluator=CustomEvaluator()).run(path).to_dict()["query_results"][0]
    assert calls == ["query"]
    assert row["retrieval_measurement"]["status"] == "observed"
    assert row["embedding_observations"] == []
