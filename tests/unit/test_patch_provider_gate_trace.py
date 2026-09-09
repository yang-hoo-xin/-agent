"""Provider admission diagnostics reach the first finished metadata-only span."""
from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentTurnProviderError,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentUsage,
    OllamaChatAgentAdapter,
)
from src.libs.llm.transport_observation import transport_started
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalOllamaInitialPatchAdapter,
    LocalOllamaInitialPatchProfileV1,
)
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from src.observability.patch_langfuse_query import summarize_execution
from src.observability.patch_live_langfuse import build_patch_live_otlp

MODE = "provider_body_utf8_proxy_plus_output_budget_v1"
LABELS = {"failure_boundary": "provider_request_gate",
          "failure_classification": "provider_request_context_budget_exceeded"}
MEASUREMENTS = {"provider_body_utf8_bytes": 13710, "configured_num_ctx": 16384,
                "num_predict": 4096, "conservative_required_context": 17806}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Gate trace tests must not access models or Cloud.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


class _FirstFinishedSink:
    def __init__(self):
        self.finished = {}

    def publish(self, row):
        if row["finished_at"] is not None:
            self.finished.setdefault(row["id"], deepcopy(row))


def _adapter(tmp_path, model):
    adapter = LocalOllamaInitialPatchAdapter(
        profile=LocalOllamaInitialPatchProfileV1(LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
            "http://127.0.0.1:11434", model, 16384, 4096, 1),
        artifact_store=ArtifactStore(tmp_path / "store"), workspace_root=tmp_path,
        patch_agent_loop_policy=PatchAgentLoopPolicy())
    adapter.bind_attempt_recorder(lambda _row: None)
    return adapter


def _cloud_row(row):
    payload = build_patch_live_otlp(row)
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    attrs = {}
    for item in span["attributes"]:
        value = item["value"]
        attrs[item["key"]] = int(value["intValue"]) if "intValue" in value else next(iter(value.values()))
    prefix = "langfuse.observation.metadata."
    cloud = {"id": span["spanId"], "traceId": span["traceId"], "name": row["name"],
        "type": {"span": "SPAN", "generation": "GENERATION"}[row["kind"]],
        "parentObservationId": span.get("parentSpanId"), "isRootObservation": row["parent_id"] is None,
        "startTime": row["started_at"], "endTime": row["finished_at"],
        "level": attrs["langfuse.observation.level"],
        "metadata": {key[len(prefix):]: value for key, value in attrs.items() if key.startswith(prefix)}}
    if "langfuse.observation.usage_details" in attrs:
        cloud["usageDetails"] = json.loads(attrs["langfuse.observation.usage_details"])
    return cloud, payload


@pytest.mark.parametrize("end_time", ["2026-09-09T08:00:00.456Z", None])
def test_query_preserves_readback_timestamps_without_replacement(end_time):
    start_time = "2026-09-09T08:00:00.123Z"
    row = {"id": "request", "traceId": "a" * 32, "name": "model.request", "type": "SPAN",
           "startTime": start_time, "endTime": end_time, "metadata": {}}
    observed = summarize_execution("a" * 32, [row])["execution_tree"][0]
    assert observed["start_time"] == start_time and observed["end_time"] == end_time
    assert observed["duration_ms"] == (333.0 if end_time else None)


def test_real_pre_send_gate_exports_exact_quantities_before_span_finishes(tmp_path):
    sends = []
    model = "offline-gate-fixture"
    empty_body = {"model": model, "messages": [{"role": "user", "content": ""}], "stream": False,
        "think": False, "options": {"temperature": 0.0, "num_predict": 4096, "seed": 0, "num_ctx": 16384}}
    overhead = len(httpx.Request("POST", "http://127.0.0.1:11434/api/chat", json=empty_body).content)
    request = AgentTurnRequest(messages=(AgentMessage("user", "x" * (13710 - overhead)),))
    client = OllamaChatAgentAdapter(model=model, base_url="http://127.0.0.1:11434", max_output_tokens=4096,
        context_window=16384, request_sender=lambda *args: sends.append(args))
    adapter = _adapter(tmp_path, model)
    recorded = adapter._recording_agent_client(client, "gate-fixture")
    sink = _FirstFinishedSink()
    trace = ExecutionTrace("a" * 32, "gate-fixture", "offline", sink=sink)
    with trace.activate(), pytest.raises(AgentTurnProviderError) as raised:
        recorded.complete_turn(request)
    assert sends == [] and adapter.patch_attempt_receipt()["model_call_count"] == 1
    assert raised.value.diagnostic["context_admission"]["provider_body_utf8_bytes"] == 13710
    rows = list(sink.finished.values())
    assert not any(row["kind"] == "generation" for row in rows)
    request_row = next(row for row in rows if row["name"] == "model.request")
    assert request_row["status"] == "failed"
    for key, value in {**LABELS, "context_admission_mode": MODE, **MEASUREMENTS}.items():
        assert request_row["attributes"][key] == value
    cloud, payload = _cloud_row(request_row)
    result = summarize_execution(trace.context.trace_id, [cloud])
    assert result["generation_count"] == 0 and result["model_request_observations"] == 1
    item = result["execution_tree"][0]
    assert item["start_time"] == request_row["started_at"] and item["end_time"] == request_row["finished_at"]
    for key, value in {**LABELS, "context_admission_mode": MODE, **MEASUREMENTS}.items():
        assert item["facts"][key] == value
    assert "langfuse.observation.usage_details" not in json.dumps(payload)


@pytest.mark.parametrize("context", [None, {},
    {"mode": MODE, "provider_body_utf8_bytes": "PRIVATE_BODY", "configured_num_ctx": True,
     "num_predict": -1, "conservative_required_context": float("inf"), "path": "C:/PRIVATE_PATH"},
    {"mode": "PRIVATE_MODE", **MEASUREMENTS},
])
def test_missing_or_sensitive_diagnostic_values_are_not_invented_or_exported(tmp_path, context):
    diagnostic = {**LABELS, "context_admission": context, "body": "PRIVATE_BODY", "path": "C:/PRIVATE_PATH"}
    error = AgentTurnProviderError("PRIVATE_ERROR_TEXT", diagnostic=diagnostic)
    before = deepcopy(error.diagnostic)
    def fail(_request):
        raise error
    adapter = _adapter(tmp_path, "offline-sensitive-fixture")
    recorded = adapter._recording_agent_client(SimpleNamespace(provider="offline", model=adapter.profile.model,
        complete_turn=fail), "sensitive-fixture")
    sink = _FirstFinishedSink()
    trace = ExecutionTrace("b" * 32, "sensitive-fixture", "offline", sink=sink)
    with trace.activate(), pytest.raises(AgentTurnProviderError) as raised:
        recorded.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "offline"),)))
    assert raised.value is error and error.diagnostic == before
    row = next(row for row in sink.finished.values() if row["name"] == "model.request")
    assert all(key not in row["attributes"] for key in MEASUREMENTS)
    cloud, payload = _cloud_row(row)
    exported = json.dumps([trace.context.to_dict(), payload, summarize_execution(trace.context.trace_id, [cloud])])
    assert all(secret not in exported for secret in ("PRIVATE_BODY", "PRIVATE_PATH", "PRIVATE_MODE", "PRIVATE_ERROR_TEXT"))
    assert not any(item["kind"] == "generation" for item in sink.finished.values())


@pytest.mark.parametrize("measured", [False, True])
def test_success_keeps_transport_generation_and_original_usage_contract(tmp_path, measured):
    usage = {"input_tokens": 11, "output_tokens": 4}
    response = AgentTurnResponse(provider="offline", model="offline-success", content="{}",
        usage=AgentUsage(**usage), provider_diagnostic={"measured_usage": usage} if measured else {})
    def complete(_request):
        transport_started()  # Explicit fixture notification of the existing transport boundary.
        return response
    adapter = _adapter(tmp_path, response.model)
    recorded = adapter._recording_agent_client(SimpleNamespace(provider=response.provider, model=response.model,
        complete_turn=complete), "success-fixture")
    sink = _FirstFinishedSink()
    trace = ExecutionTrace("c" * 32, "success-fixture", "offline", sink=sink)
    with trace.activate():
        assert recorded.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "offline"),))) is response
    rows = list(sink.finished.values())
    assert len([row for row in rows if row["kind"] == "generation"]) == 1
    assert all(not set({**LABELS, **MEASUREMENTS, "context_admission_mode": MODE}).intersection(row["attributes"])
               for row in rows)
    generation = next(row for row in rows if row["kind"] == "generation")
    cloud, _ = _cloud_row(generation)
    result = summarize_execution(trace.context.trace_id, [cloud])
    assert result["generation_count"] == 1
    assert result["generations"][0]["usage"] == ({**usage, "total_tokens": 15} if measured else None)
