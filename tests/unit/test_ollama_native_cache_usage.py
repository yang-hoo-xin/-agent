"""Native cache accounting through actual adapters and tracing; intercepted HTTP only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentTurnRequest,
    OllamaChatAgentAdapter,
    OpenAIResponsesAgentAdapter,
    QwenChatAgentAdapter,
)
from src.libs.llm.base_llm import ChatResponse, Message
from src.libs.llm.ollama_llm import OllamaLLM
from src.libs.llm.transport_observation import transport_started
from src.mod_agent.evidence.discovery_loop import _usage_totals
from src.mod_agent.upstream_model_trace import trace_upstream_model_call


# Only token counters copied from the retained hot S2 worker-turn-004 response,
# SHA e2e21933017201f69139a67c5829259e8a0b5f5e971b1589e01565f024d2bf90.
# That original normalized cache is 0 but native cache is 6833. No body is copied.
def envelope(cache=6833):
    data = {"model":"test-model", "done":True, "done_reason":"stop",
            "message":{"role":"assistant", "content":"{}"},
            "prompt_eval_count":9709, "eval_count":427}
    if cache != "absent":
        data["prompt_eval_cached_count"] = cache
    return data


@pytest.mark.parametrize("cache,expected", [(6833,6833),(0,0),("absent",None),
    (None,None),(-1,None),(True,None),("6833",None),(1.5,None)])
def test_agent_and_diagnostic_preserve_measured_cache(cache, expected):
    adapter = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="test-model",
        max_output_tokens=512, request_sender=lambda *_:envelope(cache))
    response = adapter.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "x"),)))
    assert response.usage.cached_input_tokens == expected
    assert response.usage.total_tokens == 10136
    for usage in (response.usage.to_dict(), response.provider_diagnostic["usage"],
                  response.provider_diagnostic["measured_usage"]):
        assert usage["input_tokens"] == 9709 and usage["output_tokens"] == 427
        if expected is None:
            assert "cached_input_tokens" not in usage
        else:
            assert usage["cached_input_tokens"] == expected


@pytest.mark.parametrize("mode", ["plain", "structured", "stream"])
@pytest.mark.parametrize("cache,expected", [(6833,6833),(0,0),("absent",None),(False,None),(-5,None)])
def test_planning_adapter_and_generation_trace_retain_cache(monkeypatch, tmp_path, mode, cache, expected):
    data = envelope(cache)
    def handle(request):
        if mode == "stream":
            return httpx.Response(200, content=(json.dumps(data)+"\n").encode(), request=request)
        return httpx.Response(200, json=data, request=request)
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request:transport.handle_request(request))
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw:pytest.fail("network forbidden"))
    settings = SimpleNamespace(llm=SimpleNamespace(model="test-model", temperature=0, max_tokens=512))
    llm = OllamaLLM(settings)
    kwargs = {} if mode == "plain" else {"response_format":{"type":"object"}}
    if mode == "stream":
        kwargs["stream_response"] = True
    trace = ExecutionTrace("a"*32, "session", "cache-test")
    with trace.activate():
        response = trace_upstream_model_call(role="planning", provider="ollama", model="test-model",
            input_payload={"goal":"x"}, request_document={}, body_root=tmp_path,
            invoke_with_provider_request=lambda recorder:llm.chat(
                [Message("user", "x")], provider_request_recorder=recorder, **kwargs))
    assert response.usage["prompt_tokens"] == 9709
    assert response.usage["total_tokens"] == 10136
    generations = {row["data"]["id"]:row["data"] for row in trace.context.stages if row["data"]["kind"] == "generation"}
    assert len(generations) == 1
    usage = next(iter(generations.values()))["attributes"]["usage"]
    attributes = next(iter(generations.values()))["attributes"]
    native_ref = attributes["local_detail_refs"]["provider_response"]
    retained = Path(native_ref["path"]).read_bytes()
    assert hashlib.sha256(retained).hexdigest() == native_ref["sha256"] == attributes["provider_response_sha256"]
    assert json.loads(retained) == response.raw_response
    assert attributes["provider_response_capture_boundary"] == "adapter_raw_response_json_not_wire_bytes"
    assert usage["input_tokens"] == 9709 and usage["output_tokens"] == 427
    for observed in (response.usage, usage):
        assert observed.get("cached_input_tokens") == expected
        if expected is None:
            assert "cached_input_tokens" not in observed


def test_discovery_cache_aggregate_is_unknown_when_any_turn_is_unknown():
    known = {"input_tokens":9709,"output_tokens":427,"total_tokens":10136,"cached_input_tokens":6833}
    unknown = {"input_tokens":100,"output_tokens":1,"total_tokens":101}
    total = _usage_totals((known, unknown))
    assert total["cached_input_tokens"] is None
    assert total["total_tokens"] == 10237
    assert _usage_totals((known, {**unknown,"cached_input_tokens":0}))["cached_input_tokens"] == 6833


@pytest.mark.parametrize("provider", ["qwen", "responses"])
@pytest.mark.parametrize("details,expected", [({},None),(None,None),([],None),("bad",None),
    ({"cached_tokens":False},None),({"cached_tokens":-1},None),({"cached_tokens":"2"},None),
    ({"cached_tokens":0},0),({"cached_tokens":8},8)])
def test_non_ollama_optional_native_cache(provider, details, expected):
    if provider == "qwen":
        data = {"model":"test-model","choices":[{"finish_reason":"stop","message":{"content":"{}"}}],
                "usage":{"prompt_tokens":12,"completion_tokens":3,"prompt_tokens_details":details}}
        adapter = QwenChatAgentAdapter(api_key="test-only",base_url="https://example.invalid/v1",
            model="test-model",max_completion_tokens=100,request_sender=lambda *_:data)
    else:
        data = {"model":"test-model","id":"test-response","status":"completed",
                "output":[{"type":"message","content":[{"type":"output_text","text":"{}"}]}],
                "usage":{"input_tokens":12,"output_tokens":3,"input_tokens_details":details}}
        adapter = OpenAIResponsesAgentAdapter(api_key="test-only",model="test-model",
            max_output_tokens=100,request_sender=lambda *_:data)
    response = adapter.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "x"),)))
    assert response.usage.cached_input_tokens == expected
    assert response.usage.total_tokens == 15
    assert response.usage.to_dict().get("cached_input_tokens") == expected
    if expected is None:
        assert "cached_input_tokens" not in response.usage.to_dict()


@pytest.mark.parametrize("records,steps", [((),1),((),None),
    (({"input_tokens":2,"output_tokens":3,"cached_input_tokens":0,"total_tokens":5},),2)])
def test_discovery_missing_turns_cannot_be_zero_or_partial_cost(records, steps):
    assert all(value is None for value in _usage_totals(records, expected_model_steps=steps).values())
    assert all(value == 0 for value in _usage_totals((), expected_model_steps=0).values())


@pytest.mark.parametrize("mode,expected_status", [("write_failure","write_failed"),
    ("unserializable","not_serializable"),("absent","not_available")])
def test_native_body_capture_failure_does_not_change_response_or_retry(tmp_path, monkeypatch, mode, expected_status):
    from src.mod_agent import upstream_model_trace as trace_module
    native = object() if mode == "unserializable" else None if mode == "absent" else envelope()
    response = ChatResponse(content="{}", model="test-model",raw_response=native,
        usage={"prompt_tokens":9709,"completion_tokens":427})
    original = trace_module._local_body
    def capture(root, observation, role, raw):
        if mode == "write_failure" and role == "provider_response.json":
            raise OSError("controlled local write failure")
        return original(root, observation, role, raw)
    monkeypatch.setattr(trace_module,"_local_body",capture)
    calls = []
    def invoke():
        calls.append(1)
        transport_started()
        return response
    trace = ExecutionTrace("b"*32,"session","capture-failure")
    with trace.activate():
        result = trace_upstream_model_call(role="planning",provider="test",model="test-model",
            input_payload={},request_document={},body_root=tmp_path,invoke=invoke)
    assert result is response and calls == [1]
    row = next(row["data"] for row in reversed(trace.context.stages) if row["data"]["kind"] == "generation")
    assert row["attributes"]["provider_response_local_body_status"] == expected_status
    assert "provider_response" not in row["attributes"]["local_detail_refs"]
    assert row["attributes"]["usage"]["input_tokens"] == 9709
