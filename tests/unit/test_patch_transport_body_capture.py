"""Patch turn sidecars bind real local HTTP entity bytes without new model calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentTurnProviderError,
    AgentTurnRequest,
    OllamaChatAgentAdapter,
    QwenChatAgentAdapter,
)
from src.mod_agent import patch_transport_bodies
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalOllamaInitialPatchAdapter,
    LocalOllamaInitialPatchProfileV1,
)
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from src.observability.patch_live_langfuse import build_patch_live_otlp


def _adapter(tmp_path):
    adapter = LocalOllamaInitialPatchAdapter(
        profile=LocalOllamaInitialPatchProfileV1(LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
            "http://127.0.0.1:11434", "native-patch", 4096, 128, 10),
        artifact_store=ArtifactStore(tmp_path / "store"), workspace_root=tmp_path,
        patch_agent_loop_policy=PatchAgentLoopPolicy())
    adapter.bind_attempt_recorder(lambda _event: None)
    return adapter


def _wire(monkeypatch, *, error=None):
    requests = []

    def handle(request):
        requests.append(request.content)
        if error is not None:
            raise error
        return httpx.Response(200, json={"model": "native-patch", "done": True,
            "message": {"content": '{"changes":[]}'}, "prompt_eval_count": 17, "eval_count": 6,
            "choices": [{"message": {"content": '{"changes":[]}'}, "finish_reason": "stop"}]})

    client_type = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr("socket.socket.connect", lambda *_args, **_kwargs: pytest.fail("No network allowed"))
    return requests


def _client():
    return OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="native-patch",
        max_output_tokens=128, context_window=4096)


def _request():
    return AgentTurnRequest(messages=(AgentMessage("user", {"source": "PRIVATE_PATCH_源码\r\n"}),))


def _rows(trace):
    return list({stage["data"]["id"]: stage["data"] for stage in trace.context.stages}.values())


def test_patch_turn_records_actual_wire_with_unchanged_business_refs(tmp_path, monkeypatch):
    requests = _wire(monkeypatch)
    adapter = _adapter(tmp_path)
    recorded = adapter._recording_agent_client(_client(), "patch-body")
    trace = ExecutionTrace("trace", "session", "test")
    trace.context.metadata["local_body_root"] = str(tmp_path / "run")
    with trace.activate():
        response = recorded.complete_turn(_request())
    assert len(requests) == 1 and response.content == '{"changes":[]}'
    turn = adapter.patch_attempt_receipt()["worker_turns"][0]
    assert turn["request_ref_scope"] == "effective_agent_turn_request_not_provider_wire_or_send_proof"
    assert "provider_request_ref" in turn
    raw = Path(turn["provider_request_ref"]["path"]).read_bytes()
    assert raw == requests[0]
    assert turn["provider_request_ref"]["sha256"] == hashlib.sha256(raw).hexdigest()
    row = next(row for row in _rows(trace) if row["kind"] == "generation")
    assert row["attributes"]["local_detail_refs"] == {
        "request": turn["request_ref"], "response": turn["response_ref"],
        "provider_request": turn["provider_request_ref"]}
    for reference in row["attributes"]["local_detail_refs"].values():
        assert hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest() == reference["sha256"]
    assert "PRIVATE_PATCH" not in json.dumps(row)
    assert "PRIVATE_PATCH" not in json.dumps(build_patch_live_otlp(row))


def test_wire_save_failure_does_not_change_response_or_repeat_send(tmp_path, monkeypatch):
    requests = _wire(monkeypatch)
    adapter = _adapter(tmp_path)
    recorded = adapter._recording_agent_client(_client(), "disk-failure")

    def fail(*_args):
        raise OSError("PRIVATE_CAPTURE_DISK_FAILURE")

    monkeypatch.setattr(patch_transport_bodies, "_local_body", fail)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        response = recorded.complete_turn(_request())
    assert len(requests) == adapter.patch_attempt_receipt()["model_call_count"] == 1
    assert response.content == '{"changes":[]}'
    turn = adapter.patch_attempt_receipt()["worker_turns"][0]
    assert turn["provider_request_local_body_status"] == "write_failed"
    assert "provider_request_ref" not in turn
    row = next(row for row in _rows(trace) if row["kind"] == "generation")
    assert row["attributes"]["local_detail_refs"] == {"request": turn["request_ref"], "response": turn["response_ref"]}
    assert row["attributes"]["provider_request_sha256"] == hashlib.sha256(requests[0]).hexdigest()
    assert "PRIVATE_CAPTURE_DISK_FAILURE" not in json.dumps(row)


def test_original_transport_error_is_preserved_with_wire_ref(tmp_path, monkeypatch):
    failure = RuntimeError("original business transport failure")
    requests = _wire(monkeypatch, error=failure)
    adapter = _adapter(tmp_path)
    recorded = adapter._recording_agent_client(_client(), "transport-failure")
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate(), pytest.raises(RuntimeError) as raised:
        recorded.complete_turn(_request())
    assert raised.value is failure and len(requests) == 1
    turn = adapter.patch_attempt_receipt()["worker_turns"][0]
    assert turn["status"] == "failed"
    assert Path(turn["provider_request_ref"]["path"]).read_bytes() == requests[0]


def test_existing_response_sidecar_failure_is_not_swallowed(tmp_path, monkeypatch):
    requests = _wire(monkeypatch)
    adapter = _adapter(tmp_path)
    recorded = adapter._recording_agent_client(_client(), "response-failure")
    original_open = Path.open
    failure = OSError("existing response sidecar failure")

    def open_file(path, *args, **kwargs):
        if path.name.endswith(".response.worker-turn-001.json"):
            raise failure
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate(), pytest.raises(OSError) as raised:
        recorded.complete_turn(_request())
    assert raised.value is failure and len(requests) == 1
    turn = adapter.patch_attempt_receipt()["worker_turns"][0]
    assert "request_ref" in turn and "provider_request_ref" in turn and "response_ref" not in turn


def test_verified_replay_never_manufactures_a_new_wire_body(tmp_path, monkeypatch):
    from tests.unit.test_patch_verified_replay import _case, _client, _prepare, _request

    monkeypatch.setattr("socket.socket.connect", lambda *_args: pytest.fail("Replay must not use network"))
    case = _case(tmp_path)
    _prepare(case)
    sends = []
    client = _client(case, sends)
    case.adapter._install_verified_tool_replay(client)
    recorded = case.adapter._recording_agent_client(client, "verified-replay")
    trace = ExecutionTrace("trace", "session", "test")
    trace.context.metadata["local_body_root"] = str(tmp_path / "new-wire-bodies")
    with trace.activate():
        recorded.complete_turn(_request())
        recorded.complete_turn(_request())
    turns = case.adapter.patch_attempt_receipt()["worker_turns"]
    assert len(turns) == 2 and sends == []
    assert all(turn["response_origin"] == "verified_prior_response" for turn in turns)
    assert all("provider_request_ref" not in turn for turn in turns)
    assert all(turn["provider_request_local_body_status"] == "not_observed" for turn in turns)
    assert not list((tmp_path / "new-wire-bodies").rglob("*.provider_request.json"))
    assert not any(row["kind"] == "generation" for row in _rows(trace))


def test_pre_send_gate_creates_no_wire_file_or_generation(tmp_path, monkeypatch):
    requests = _wire(monkeypatch)
    adapter = _adapter(tmp_path)
    recorded = adapter._recording_agent_client(_client(), "gate")
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate(), pytest.raises(AgentTurnProviderError):
        recorded.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "x" * 20000),)))
    assert requests == []
    assert "provider_request_ref" not in adapter.patch_attempt_receipt()["worker_turns"][0]
    assert not any(row["kind"] == "generation" for row in _rows(trace))


def test_external_client_does_not_gain_local_body_capture(tmp_path, monkeypatch):
    requests = _wire(monkeypatch)
    client = QwenChatAgentAdapter(api_key="PRIVATE_KEY", base_url="https://example.invalid/v1",
        model="native-patch", max_completion_tokens=128)
    adapter = _adapter(tmp_path)
    recorded = adapter._recording_agent_client(client, "external")
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        response = recorded.complete_turn(_request())
    assert response.content == '{"changes":[]}' and len(requests) == 1
    assert "provider_request_ref" not in adapter.patch_attempt_receipt()["worker_turns"][0]
    assert not list(tmp_path.rglob("*.provider_request.json"))
    assert "PRIVATE_KEY" not in json.dumps(_rows(trace))


def test_no_trace_keeps_wire_unknown_and_business_sidecars(tmp_path, monkeypatch):
    requests = _wire(monkeypatch)
    adapter = _adapter(tmp_path)
    adapter._recording_agent_client(_client(), "no-trace").complete_turn(_request())
    turn = adapter.patch_attempt_receipt()["worker_turns"][0]
    assert len(requests) == 1 and "request_ref" in turn and "response_ref" in turn
    assert "provider_request_ref" not in turn and not list(tmp_path.rglob("*.provider_request.json"))


def test_standalone_trace_uses_artifact_root_and_unique_turn_paths(tmp_path, monkeypatch):
    requests = _wire(monkeypatch)
    adapter = _adapter(tmp_path)
    recorded = adapter._recording_agent_client(_client(), "two-turns")
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        recorded.complete_turn(_request())
        recorded.complete_turn(_request())
    turns = adapter.patch_attempt_receipt()["worker_turns"]
    paths = [Path(turn["provider_request_ref"]["path"]) for turn in turns]
    assert len(requests) == len(set(paths)) == 2
    assert all(path.is_relative_to(adapter.artifact_store.root) for path in paths)
    assert [path.read_bytes() for path in paths] == requests
