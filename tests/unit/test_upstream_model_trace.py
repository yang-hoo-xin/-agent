"""Real transport adapters with intercepted HTTP; no model or network execution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.libs.llm.base_llm import ChatResponse
from src.libs.llm.ollama_llm import OllamaLLM, OllamaLLMError
from src.libs.llm.openai_llm import OpenAILLM
from src.libs.llm.transport_observation import transport_started
from src.mod_agent.requirement_coverage_model import request_requirement_coverage_model
from src.mod_agent.upstream_model_trace import trace_upstream_model_call
from src.observability.patch_live_langfuse import build_patch_live_otlp


def _settings():
    return SimpleNamespace(llm=SimpleNamespace(model="test-model", temperature=0.0, max_tokens=32))


def _observations(trace):
    return list({s["data"]["id"]: s["data"] for s in trace.context.stages}.values())


def _intercept(monkeypatch, *, error=None, response=None):
    calls = []
    def handle(request):
        calls.append(request)
        if error:
            raise error
        return httpx.Response(200, json=response or {"model": "test-model", "done": True,
            "done_reason": "stop", "message": {"content": '{"findings":[]}'},
            "prompt_eval_count": 17, "eval_count": 3}, request=request)
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("No actual network permitted"))
    return calls


@pytest.mark.parametrize("role,name", [
    ("requirement_projection", "requirements.project"),
    ("requirement_findings", "requirements.findings"),
    ("requirement_findings_correction", "requirements.findings"),
])
def test_upstream_generations_capture_exact_local_bodies_and_safe_cloud_binding(tmp_path, monkeypatch, role, name):
    calls = _intercept(monkeypatch)
    llm = OllamaLLM(_settings(), context_window=32768)
    payload = {"message_type": "owned-example", "source_observations": [
        {"evidence_id": "e1", "source_type": "target_source", "source_hash": "a" * 64, "excerpt": "PRIVATE_SOURCE"}]}
    trace = ExecutionTrace("a" * 32, "session", "test")
    with trace.activate():
        reply, _ = request_requirement_coverage_model(llm=llm, payload=payload,
            schema={"type": "object"}, max_output_tokens=32, capture_provider_request=True,
            trace_role=role, trace_body_root=tmp_path)
    rows = _observations(trace)
    generations = [r for r in rows if r["kind"] == "generation"]
    assert len(calls) == len(generations) == 1
    row = generations[0]
    assert row["name"] == name and row["attributes"]["model_role"] == role
    assert row["attributes"]["usage"] == {"input_tokens": 17, "output_tokens": 3}
    refs = row["attributes"]["local_detail_refs"]
    raw_request = Path(refs["request"]["path"]).read_bytes()
    assert hashlib.sha256(raw_request).hexdigest() == refs["request"]["sha256"] == row["attributes"]["request_sha256"]
    doc = json.loads(raw_request)
    assert doc["messages"] == json.loads(calls[0].content)["messages"]
    assert json.loads(doc["messages"][1]["content"]) == payload
    assert Path(refs["response"]["path"]).read_text(encoding="utf-8") == reply.content
    assert refs["response"]["sha256"] == row["attributes"]["output_sha256"]
    assert row["attributes"]["consumed_materials"][0]["excerpt_sha256"] == hashlib.sha256(b"PRIVATE_SOURCE").hexdigest()
    cloud = json.dumps(build_patch_live_otlp(row))
    assert "PRIVATE_SOURCE" not in cloud and str(tmp_path) not in cloud
    assert row["attributes"]["input_payload_sha256"] in cloud


def test_provider_gate_failure_does_not_manufacture_a_generation(tmp_path, monkeypatch):
    calls = _intercept(monkeypatch)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate(), pytest.raises(OllamaLLMError):
        request_requirement_coverage_model(llm=OllamaLLM(_settings(), context_window=1), payload={"request": "x"},
            schema={"type": "object"}, max_output_tokens=32, capture_provider_request=True,
            trace_role="requirement_projection", trace_body_root=tmp_path)
    assert calls == []
    rows = _observations(trace)
    assert not any(r["kind"] == "generation" for r in rows)
    request = next(r for r in rows if r["name"] == "model.request")
    assert request["status"] == "failed" and request["attributes"]["response_received"] is False
    assert "request" in request["attributes"]["local_detail_refs"]


def test_timeout_is_one_failed_generation_with_no_invented_usage(tmp_path, monkeypatch):
    calls = _intercept(monkeypatch, error=httpx.ReadTimeout("PRIVATE_ERROR"))
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate(), pytest.raises(OllamaLLMError):
        request_requirement_coverage_model(llm=OllamaLLM(_settings(), context_window=32768), payload={"request": "x"},
            schema={"type": "object"}, max_output_tokens=32, capture_provider_request=True,
            trace_role="requirement_findings", trace_body_root=tmp_path)
    row = next(r for r in _observations(trace) if r["kind"] == "generation")
    assert len(calls) == 1 and row["status"] == "failed"
    assert row["attributes"]["usage_available"] is False and "usage" not in row["attributes"]
    assert "PRIVATE_ERROR" not in json.dumps(build_patch_live_otlp(row))


def test_body_writer_failure_cannot_change_result_or_repeat_a_model_call(tmp_path, monkeypatch):
    calls = []
    answer = ChatResponse(content="same-result", model="test-model")
    def invoke():
        calls.append(1)
        transport_started()
        return answer
    def fail(*args):
        raise OSError("PRIVATE_DISK_ERROR")
    monkeypatch.setattr("src.mod_agent.upstream_model_trace._local_body", fail)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        result = trace_upstream_model_call(role="planning", provider="test", model="test-model",
            input_payload={}, request_document={}, body_root=tmp_path, invoke=invoke)
    assert result is answer and calls == [1]
    row = next(r for r in _observations(trace) if r["kind"] == "generation")
    assert row["attributes"]["local_body_status"] == "response_write_failed"
    assert row["attributes"]["usage_available"] is False


def test_partial_provider_usage_is_unknown_not_zero(tmp_path, monkeypatch):
    _intercept(monkeypatch, response={"model": "test-model", "done": True, "done_reason": "stop",
        "message": {"content": "{}"}, "prompt_eval_count": 8})
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        request_requirement_coverage_model(llm=OllamaLLM(_settings(), context_window=32768), payload={},
            schema={"type": "object"}, max_output_tokens=32, capture_provider_request=True,
            trace_role="requirement_findings", trace_body_root=tmp_path)
    row = next(r for r in _observations(trace) if r["kind"] == "generation")
    assert row["attributes"]["usage_available"] is False and "usage" not in row["attributes"]


def test_existing_external_compatible_http_boundary_can_be_traced(tmp_path, monkeypatch):
    calls = _intercept(monkeypatch, response={"model": "test-model", "choices": [{"message": {"content": "{}"}}],
                                           "usage": {"prompt_tokens": 8, "completion_tokens": 2}})
    llm = OpenAILLM(_settings(), api_key="PRIVATE_KEY", base_url="https://example.invalid")
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        request_requirement_coverage_model(llm=llm, payload={}, schema={"type": "object"},
            max_output_tokens=32, capture_provider_request=False,
            trace_role="requirement_projection", trace_body_root=tmp_path)
    row = next(r for r in _observations(trace) if r["kind"] == "generation")
    assert len(calls) == 1 and row["attributes"]["usage"] == {"input_tokens": 8, "output_tokens": 2}
    assert "PRIVATE_KEY" not in json.dumps(row)
