"""Actual httpx serialization at the local Planning boundary; no network/model."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentResponseFormat,
    AgentTurnRequest,
    OllamaChatAgentAdapter,
    _HttpJsonSender,
    _LoopbackHttpJsonSender,
)
from src.libs.llm.base_llm import ChatResponse
from src.libs.llm.transport_observation import observe_transport
from src.mod_agent import upstream_model_trace
from src.mod_agent.upstream_model_trace import trace_upstream_model_call
from src.observability.patch_live_langfuse import build_patch_live_otlp


def _wire(monkeypatch, *, error=None, alternate_serialization=False, headers_seen=None):
    received = []

    def handle(request):
        received.append(request.content)
        if headers_seen is not None:
            headers_seen.append(dict(request.headers))
        if error is not None:
            raise error
        return httpx.Response(200, json={"model": "local-model", "done": True,
            "message": {"content": '{"ok":true}'}, "prompt_eval_count": 19, "eval_count": 5})

    client_type = httpx.Client

    class WireClient(client_type):
        def post(self, *args, **kwargs):
            if alternate_serialization:
                kwargs["content"] = json.dumps(kwargs.pop("json"), ensure_ascii=True, indent=2).encode()
            return super().post(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: WireClient(
        transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr("socket.socket.connect", lambda *_args, **_kwargs: pytest.fail("No network allowed"))
    return received


def _request():
    return AgentTurnRequest(messages=(AgentMessage("system", "Select targets."),
        AgentMessage("user", {"source_observations": [{"evidence_id": "e1",
            "source_type": "target_source", "source_hash": "a" * 64,
            "excerpt": "PRIVATE_SOURCE_原文\r\n\tvalue = 1;"}]})),
        response_format=AgentResponseFormat("selection", "A selection", {"type": "object"}),
        tool_choice="none")


def _invoke(root):
    adapter = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="local-model",
        max_output_tokens=128, context_window=4096)
    request = _request()
    return trace_upstream_model_call(role="planning", provider=adapter.provider, model=adapter.model,
        input_payload=request.messages[1].content, request_document=asdict(request), body_root=root,
        invoke=lambda: adapter.complete_turn(request))


def _generation(trace):
    rows = {stage["data"]["id"]: stage["data"] for stage in trace.context.stages}
    return next(row for row in rows.values() if row["kind"] == "generation")


def test_planning_captures_actual_httpx_body_locally_not_in_spans(tmp_path, monkeypatch):
    received = _wire(monkeypatch)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        response = _invoke(tmp_path)
    assert len(received) == 1 and response.content == '{"ok":true}'
    row = _generation(trace)
    attrs = row["attributes"]
    assert "provider_request" in attrs["local_detail_refs"]
    reference = attrs["local_detail_refs"]["provider_request"]
    captured = Path(reference["path"]).read_bytes()
    assert captured == received[0]
    digest = hashlib.sha256(received[0]).hexdigest()
    assert reference["sha256"] == attrs["provider_request_sha256"] == digest
    assert attrs["provider_request_bytes"] == len(received[0])
    assert response.provider_diagnostic["request_identity"]["provider_body_sha256"] == digest
    assert "PRIVATE_SOURCE" not in json.dumps(row)
    assert "PRIVATE_SOURCE" not in json.dumps(build_patch_live_otlp(row))


def test_capture_uses_wire_bytes_even_when_client_serialization_differs(tmp_path, monkeypatch):
    received = _wire(monkeypatch, alternate_serialization=True)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        response = _invoke(tmp_path)
    attrs = _generation(trace)["attributes"]
    reference = attrs["local_detail_refs"]["provider_request"]
    assert len(received) == 1
    assert Path(reference["path"]).read_bytes() == received[0]
    actual_hash = hashlib.sha256(received[0]).hexdigest()
    assert actual_hash == reference["sha256"] == attrs["provider_request_sha256"]
    assert actual_hash != response.provider_diagnostic["request_identity"]["provider_body_sha256"]


def _fail_provider_body(monkeypatch):
    original = upstream_model_trace._local_body

    def fail(root, observation_id, role, raw):
        if role == "provider_request.json":
            raise OSError("PRIVATE_DISK_ERROR")
        return original(root, observation_id, role, raw)

    monkeypatch.setattr(upstream_model_trace, "_local_body", fail)


def test_provider_body_persistence_failure_keeps_one_original_response(tmp_path, monkeypatch):
    received = _wire(monkeypatch)
    _fail_provider_body(monkeypatch)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        response = _invoke(tmp_path)
    row = _generation(trace)
    attrs = row["attributes"]
    assert len(received) == 1 and response.content == '{"ok":true}'
    assert attrs["provider_request_local_body_status"] == "write_failed"
    assert "provider_request" not in attrs["local_detail_refs"]
    assert attrs["provider_request_sha256"] == hashlib.sha256(received[0]).hexdigest()
    assert "PRIVATE_DISK_ERROR" not in json.dumps(row)
    assert "PRIVATE_DISK_ERROR" not in json.dumps(build_patch_live_otlp(row))


@pytest.mark.parametrize("write_failure", [False, True])
def test_original_transport_exception_is_preserved_without_retry(tmp_path, monkeypatch, write_failure):
    original_error = RuntimeError("original transport failure")
    received = _wire(monkeypatch, error=original_error)
    if write_failure:
        _fail_provider_body(monkeypatch)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate(), pytest.raises(RuntimeError) as raised:
        _invoke(tmp_path)
    assert raised.value is original_error and len(received) == 1
    row = _generation(trace)
    assert row["status"] == "failed"
    assert row["attributes"]["usage_available"] is False


@pytest.mark.parametrize("active_trace_without_upstream_owner", [False, True])
def test_no_body_observer_does_not_write_body_files(tmp_path, monkeypatch, active_trace_without_upstream_owner):
    received = _wire(monkeypatch)
    if active_trace_without_upstream_owner:
        adapter = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="local-model",
            max_output_tokens=128, context_window=4096)
        with ExecutionTrace("trace", "session", "test").activate():
            adapter.complete_turn(_request())
    else:
        _invoke(tmp_path)
    assert len(received) == 1
    assert not list(tmp_path.rglob("*.provider_request.json"))
    assert not (tmp_path / "model_trace_bodies").exists()


@pytest.mark.parametrize("external", [False, True])
def test_only_loopback_sender_captures_body_and_never_headers(tmp_path, monkeypatch, external):
    headers_seen = []
    received = _wire(monkeypatch, headers_seen=headers_seen)
    sender = _HttpJsonSender(api_key="PRIVATE_KEY") if external else _LoopbackHttpJsonSender()
    url = "https://example.invalid/v1/chat/completions" if external else "http://127.0.0.1:11434/api/chat"
    trace = ExecutionTrace("trace", "session", "test")

    def invoke():
        value = sender(url, {"messages": [{"role": "user", "content": "body-only"}]},
            {"Content-Type": "application/json", "Authorization": "Bearer PRIVATE_KEY", "X-Private": "PRIVATE_HEADER"})
        return ChatResponse(content=value["message"]["content"], model="local-model")

    with trace.activate():
        trace_upstream_model_call(role="planning", provider="test", model="local-model",
            input_payload={}, request_document={}, body_root=tmp_path, invoke=invoke)
    row = _generation(trace)
    assert len(received) == 1 and headers_seen[0]["authorization"] == "Bearer PRIVATE_KEY"
    refs = row["attributes"]["local_detail_refs"]
    assert ("provider_request" in refs) is not external
    if not external:
        assert Path(refs["provider_request"]["path"]).read_bytes() == received[0]
    for private in ("PRIVATE_KEY", "PRIVATE_HEADER"):
        assert private not in json.dumps(row)
        assert private not in json.dumps(build_patch_live_otlp(row))
        assert all(private.encode() not in path.read_bytes() for path in tmp_path.rglob("*.*") if path.is_file())


def test_local_body_context_is_restored_and_callback_failure_is_observation_only(monkeypatch):
    received = _wire(monkeypatch)
    bodies, safe_updates = [], []
    sender = _LoopbackHttpJsonSender()

    def call():
        return sender("http://127.0.0.1:11434/api/chat", {"source": "immutable bytes"}, {})

    def mutate_body(raw):
        raw[0] = 0

    with observe_transport(lambda: None, lambda **values: safe_updates.append(values),
                           local_request_body_callback=bodies.append):
        call()
        with observe_transport(lambda: None, local_request_body_callback=mutate_body):
            assert call()["message"]["content"] == '{"ok":true}'
        call()
    call()
    assert len(received) == 4 and bodies == [received[0], received[2]]
    assert len(safe_updates) == 2 and all("source" not in str(value) for value in safe_updates)
