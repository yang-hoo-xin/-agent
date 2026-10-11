"""Existing Ollama NDJSON transport feeds the public owner and normal CLI."""
import json
from unittest.mock import patch

import pytest

from src.libs.llm import Message, OllamaLLM, OllamaLLMError
from tests.unit.test_ollama_llm import MockSettings, make_ollama_stream_response
from tests.unit.test_query_service import Model, make_service, request


def test_ollama_content_callback_receives_only_actual_content_and_whitespace():
    provider = OllamaLLM(MockSettings())
    response = make_ollama_stream_response([
        {"model": "llama3", "message": {"content": " ", "thinking": "PRIVATE"}, "done": False},
        {"model": "llama3", "message": {"content": "actual answer", "thinking": "PRIVATE2"}, "done": False},
        {"model": "llama3", "message": {"content": ""}, "done": True, "done_reason": "stop"},
    ])
    deltas = []
    with patch("httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        client.stream.return_value.__enter__.return_value = response
        result = provider.chat([Message("user", "question")], stream_response=True, stream_content_recorder=deltas.append)
    assert deltas == [" ", "actual answer", ""] and result.content == " actual answer"
    assert "PRIVATE" not in json.dumps(deltas)


def test_content_consumer_failure_closes_existing_stream_and_is_not_fail_open():
    provider = OllamaLLM(MockSettings())
    response = make_ollama_stream_response([
        {"model": "llama3", "message": {"content": "partial"}, "done": False},
        {"model": "llama3", "message": {"content": "final"}, "done": True},
    ])
    with patch("httpx.Client") as factory:
        client = factory.return_value.__enter__.return_value
        stream = client.stream.return_value
        stream.__enter__.return_value = response
        with pytest.raises(OllamaLLMError):
            provider.chat([Message("user", "question")], stream_response=True,
                          stream_content_recorder=lambda _: (_ for _ in ()).throw(RuntimeError("consumer cancelled")))
        assert stream.__exit__.call_count == 1
        assert factory.return_value.__exit__.call_count == 1


def test_content_callback_requires_explicit_stream_transport():
    with pytest.raises(ValueError, match="stream_content_recorder"):
        OllamaLLM(MockSettings()).chat([Message("user", "question")], stream_content_recorder=lambda _: None)


@pytest.mark.parametrize("mode", ["incomplete", "truncated"])
def test_ollama_nonstream_partial_completion_cannot_be_cached(tmp_path, mode):
    class Partial(Model):
        def chat(self, *args, **kwargs):
            result = super().chat(*args, **kwargs)
            result.raw_response.update(done=mode != "incomplete", done_reason="length" if mode == "truncated" else None)
            return result
    service, _, _, _, _ = make_service(tmp_path, model=Partial())
    result = service.query(request(stream=False)).to_dict()
    assert result["status"] == "failed" and result["error"]["code"] == "QUERY_PROVIDER_INCOMPLETE"
    assert not list((tmp_path / "cache").glob("*.json"))


def test_normal_cli_stream_is_jsonl_with_progress_distinct_from_content(tmp_path, monkeypatch, capsys):
    from scripts import query
    service, model, backend, _, _ = make_service(tmp_path)
    monkeypatch.setattr(query, "load_settings", lambda *_: service.settings)
    monkeypatch.setattr(query, "create_query_service", lambda *_: service)
    code = query.main(["--query", "lookup", "--collection", "docs", "--top-k", "1", "--stream"])
    out = capsys.readouterr()
    events = [json.loads(line) for line in out.out.splitlines()]
    assert code == 0 and events[-1]["kind"] == "final"
    assert events[-1]["response"]["status"] == "completed"
    assert sum(event["kind"] == "model_content" for event in events) == 3
    assert len(model.calls) == len(backend.calls) == 1


def test_normal_cli_retrieval_only_uses_same_reranker_without_model(tmp_path, monkeypatch, capsys):
    from scripts import query
    service, model, backend, _, _ = make_service(tmp_path)
    monkeypatch.setattr(query, "load_settings", lambda *_: service.settings)
    monkeypatch.setattr(query, "create_query_service", lambda *_: service)
    assert query.main(["--query", "lookup", "--collection", "docs", "--top-k", "1", "--retrieval-only", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["results"][0]["chunk_id"] == "b" and result["answer"] is None
    assert len(backend.calls) == 1 and not model.calls
