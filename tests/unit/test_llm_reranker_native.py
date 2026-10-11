"""Native reranking contracts using mocked HTTP, never a real provider."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.core.trace.trace_context import TraceContext
from src.libs.llm.base_llm import Message
from src.libs.llm.ollama_llm import OllamaLLM, OllamaLLMError
from src.libs.reranker.llm_reranker import LLMReranker, LLMRerankError


@pytest.fixture
def native(tmp_path):
    settings = SimpleNamespace(storage_root=str(tmp_path), llm=SimpleNamespace(
        provider="ollama", model="test-model", temperature=0.0, max_tokens=768))
    llm = OllamaLLM(settings, context_window=32768)
    return LLMReranker(settings, llm=llm)


@pytest.fixture
def candidates():
    return [{"id": "a", "text": "First", "metadata": {"source": "original"}},
            {"id": "b", "text": "Second"}]


def envelope(content=None, **updates):
    result = {"model": "test-model", "done": True, "done_reason": "stop",
              "message": {"role": "assistant", "content": content or
                          '[{"passage_id":"a","score":1},{"passage_id":"b","score":3}]'},
              "prompt_eval_count": 91, "eval_count": 37}
    result.update(updates)
    return result


def http_response(raw):
    response = Mock(status_code=200)
    response.json.return_value = raw
    return response


def evidence(native, trace):
    public = next(s["data"] for s in trace.stages if s["stage"] == "rerank_model")
    path = Path(native.settings.storage_root) / "rerank_requests" / (public["evidence_id"] + ".observation.json")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == public["observation_sha256"]
    return public, json.loads(raw)


def test_native_schema_request_is_durable_before_only_send(native, candidates):
    trace = TraceContext()
    def post(_url, **kwargs):
        files = list((Path(native.settings.storage_root) / "rerank_requests").glob("*.request.json"))
        assert len(files) == 1
        frozen = json.loads(files[0].read_bytes())
        assert frozen["body_utf8"].encode() == kwargs["content"]
        body = json.loads(kwargs["content"])
        schema = body["format"]
        assert schema["minItems"] == schema["maxItems"] == 2
        assert schema["items"]["additionalProperties"] is False
        assert schema["items"]["properties"]["passage_id"]["enum"] == ["a", "b"]
        assert schema["items"]["properties"]["score"]["enum"] == [0, 1, 2, 3]
        assert body["options"]["num_predict"] == 768
        assert body["think"] is False
        return http_response(envelope())
    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.side_effect = post
        ranked = native.rerank("Query", candidates, trace)
        assert client.return_value.__enter__.return_value.post.call_count == 1
    assert [x["id"] for x in ranked] == ["b", "a"]
    assert ranked[1]["metadata"] == candidates[0]["metadata"]
    public, private = evidence(native, trace)
    assert public["status"] == "validated"
    assert public["transport_calls"] == 1
    assert public["usage"]["total_tokens"] == 128
    assert private["candidate_ids"] == ["a", "b"]
    assert json.loads(Path(private["response_ref"]["path"]).read_bytes()) == envelope()
    assert "original" not in json.dumps(public)
    assert "path" not in json.dumps(public)


@pytest.mark.parametrize("content", [
    '[{"passage_id":"a","score":1}]',
    '[{"passage_id":"a","score":1},{"passage_id":"a","score":2}]',
    '[{"passage_id":"a","score":1},{"passage_id":"foreign","score":2}]',
    '[{"passage_id":"a","score":true},{"passage_id":"b","score":2}]',
    '[{"passage_id":"a","score":4},{"passage_id":"b","score":2}]',
    '[{"passage_id":"a","score":1.5},{"passage_id":"b","score":2}]',
    '[{"passage_id":"a","score":1,"reasoning":"extra"},{"passage_id":"b","score":2}]',
    '[{"passage_id":"a","score":1,"score":2},{"passage_id":"b","score":2}]',
    '```json\n[{"passage_id":"a","score":1},{"passage_id":"b","score":2}]\n```',
])
def test_invalid_native_scores_never_silently_drop_or_repair(native, candidates, content):
    trace = TraceContext()
    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = http_response(envelope(content))
        with pytest.raises(LLMRerankError):
            native.rerank("Query", candidates, trace)
        assert client.return_value.__enter__.return_value.post.call_count == 1
    public, private = evidence(native, trace)
    assert public["status"] == "failed"
    assert "response_ref" in private


@pytest.mark.parametrize("updates", [{"done_reason": "length"}, {"done": False}, {"model": "wrong"}])
def test_rejected_envelope_preserved_with_actual_usage(native, candidates, updates):
    trace = TraceContext()
    raw = envelope(**updates)
    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = http_response(raw)
        with pytest.raises(LLMRerankError):
            native.rerank("Query", candidates, trace)
        assert client.return_value.__enter__.return_value.post.call_count == 1
    public, private = evidence(native, trace)
    assert public["response_received"] is True
    assert public["done_reason"] == raw["done_reason"]
    assert public["usage"]["completion_tokens"] == 37
    assert json.loads(Path(private["response_ref"]["path"]).read_bytes()) == raw


@pytest.mark.parametrize("kind,expected_sends", [("request", 0), ("response", 1)])
def test_persistence_failure_does_not_claim_evidence_or_retry(native, candidates, kind, expected_sends):
    trace = TraceContext()
    persist = native._persist_evidence
    def fail_selected(evidence_id, selected_kind, value):
        if selected_kind == kind:
            raise OSError("unwritable")
        return persist(evidence_id, selected_kind, value)
    with patch.object(native, "_persist_evidence", side_effect=fail_selected), patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = http_response(envelope())
        with pytest.raises(LLMRerankError):
            native.rerank("Query", candidates, trace)
        assert client.return_value.__enter__.return_value.post.call_count == expected_sends
    public, private = evidence(native, trace)
    assert kind + "_ref" not in private
    assert public["status"] == "failed"
    assert public["transport_calls"] == expected_sends


def test_duplicate_input_ids_fail_before_reservation(native, candidates):
    candidates[1]["id"] = "a"
    trace = TraceContext()
    with patch("httpx.Client") as client, pytest.raises(LLMRerankError, match="unique"):
        native.rerank("Query", candidates, trace)
    client.assert_not_called()
    assert not trace.stages


def test_recorder_receives_copy_before_admission_cannot_repair_envelope(native):
    captured = []
    def record(raw):
        captured.append(dict(raw))
        raw["done_reason"] = "stop"
    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = http_response(envelope(done_reason="length"))
        with pytest.raises(OllamaLLMError, match="stop reason"):
            native.llm.chat([Message("user", "query")], response_format={"type": "array"},
                            provider_request_recorder=lambda _: None, provider_response_recorder=record)
    assert captured[0]["done_reason"] == "length"


def test_missing_response_recorder_preserves_old_chat_default(native):
    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value = http_response(envelope())
        response = native.llm.chat([Message("user", "query")])
    assert response.raw_response == envelope()
    assert not (Path(native.settings.storage_root) / "rerank_requests").exists()
