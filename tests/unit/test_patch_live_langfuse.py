"""New native observations and bounded sink mechanics; no real Cloud or model."""
from __future__ import annotations

import json
import threading
import time
from copy import deepcopy

import httpx
import pytest

from src.observability.patch_langfuse import LangfuseHttpTransport
from src.observability.patch_live_langfuse import (
    OTLP_ENDPOINT,
    PatchLiveLangfuseSink,
    build_patch_live_otlp,
    live_observation_id,
    live_trace_id,
)


def _row(index=1, *, kind="generation", status="completed", attributes=None):
    return {"id": f"{index:016x}", "parent_id": "f" * 16 if index != 0 else None,
        "trace_id": "a" * 32, "session_id": "session-001", "environment": "local-test",
        "name": "patch.model" if kind == "generation" else "patch.run", "kind": kind, "status": status,
        "started_at": "2026-09-08T08:00:00.123456+00:00",
        "finished_at": "2026-09-08T08:00:01.123456+00:00" if status != "running" else None,
        "elapsed_ms": 999.9 if status != "running" else None,
        "attributes": attributes if attributes is not None else {"model": "qwen3.8-max", "provider": "qwen_chat",
            "usage_available": True, "usage": {"input_tokens": 100, "output_tokens": 30,
                "cached_input_tokens": 60, "reasoning_tokens": 10, "total_tokens": 130}}}


def _span(payload):
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def _attributes(payload):
    return {item["key"]: next(iter(item["value"].values())) for item in _span(payload)["attributes"]}


def _transport(monkeypatch, *, response=None, error=None):
    requests = []

    def handle(request):
        assert request.url == "https://langfuse.example" + OTLP_ENDPOINT
        assert request.headers["x-langfuse-ingestion-version"] == "4"
        assert request.method == "POST"
        requests.append(request)
        if error:
            raise error
        return httpx.Response(200, json=response if response is not None else {}, request=request)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("No real Cloud network"))
    monkeypatch.setattr("socket.socket.connect_ex", lambda *a, **k: pytest.fail("No real Cloud network"))
    return LangfuseHttpTransport("https://langfuse.example", "pk-offline", "sk-offline", timeout_seconds=0.1), requests


def test_real_time_tree_session_environment_and_generation_usage_are_native():
    root = _row(0, kind="span")
    root["id"] = "f" * 16
    generation = _row()
    tool = _row(2, kind="tool")
    tool["parent_id"] = generation["id"]
    spans = [build_patch_live_otlp(row) for row in (root, generation, tool)]
    assert _span(spans[1])["parentSpanId"] == _span(spans[0])["spanId"]
    assert _span(spans[2])["parentSpanId"] == _span(spans[1])["spanId"]
    assert "parentSpanId" not in _span(spans[0])
    for payload in spans:
        span, attrs = _span(payload), _attributes(payload)
        assert span["traceId"] == "a" * 32
        assert int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"]) == 1_000_000_000
        assert span["startTimeUnixNano"].endswith("123456000")
        assert attrs["session.id"] == "session-001" and attrs["langfuse.environment"] == "local-test"
        assert attrs["langfuse.trace.tags"] == {"values": [{"stringValue": "live_execution"}, {"stringValue": "metadata_only"}]}
        assert attrs["langfuse.observation.metadata.recorded_elapsed_ms"] == 999.9
        assert "langfuse.observation.cost_details" not in attrs
        assert "langfuse.observation.completion_start_time" not in attrs
    attrs = _attributes(spans[1])
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.observation.model.name"] == "qwen3.8-max"
    usage = json.loads(attrs["langfuse.observation.usage_details"])
    assert usage == {"input": 40, "input_cached_tokens": 60, "output": 20, "output_reasoning_tokens": 10}
    assert sum(usage.values()) == 130
    for payload in (spans[0], spans[2]):
        assert "langfuse.observation.model.name" not in _attributes(payload)
        assert "langfuse.observation.usage_details" not in _attributes(payload)


@pytest.mark.parametrize("attributes", [
    {}, {"usage_available": False, "usage": {"input_tokens": 0, "output_tokens": 0}},
    {"usage_available": True, "usage": {"input_tokens": 10}},
    {"usage_available": True, "usage": {"input_tokens": 10, "output_tokens": 3, "cached_input_tokens": 11}},
    {"usage_available": True, "usage": {"input_tokens": 10, "output_tokens": 3, "reasoning_tokens": 4}},
    {"usage_available": True, "usage": {"input_tokens": False, "output_tokens": 3}},
])
def test_missing_or_invalid_usage_never_becomes_zero_native_counts(attributes):
    attrs = _attributes(build_patch_live_otlp(_row(attributes=attributes)))
    assert "langfuse.observation.usage_details" not in attrs
    assert "langfuse.observation.cost_details" not in attrs


def test_explicit_zero_and_unknown_subtypes_are_not_confused():
    attrs = _attributes(build_patch_live_otlp(_row(attributes={"usage_available": True,
        "usage": {"input_tokens": 0, "output_tokens": 0}})))
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {"input": 0, "output": 0}
    attrs = _attributes(build_patch_live_otlp(_row(attributes={"usage_available": True,
        "usage": {"input_tokens": 10, "output_tokens": 5}})))
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {"input": 10, "output": 5}


@pytest.mark.parametrize("business_status", ["behavior_failed", "needs_evidence", "infrastructure_failed", "identity_failed"])
def test_completed_verifier_negative_result_is_visible_without_becoming_transport_error(business_status):
    row = _row(kind="span", attributes={"verification_status": business_status, "execution_origin": "executed"})
    row["name"] = "patch.verify"
    payload = build_patch_live_otlp(row)
    attrs = _attributes(payload)
    assert attrs["langfuse.observation.level"] == "WARNING"
    assert "verification_status=" + business_status in attrs["langfuse.observation.status_message"]
    assert "not_task_acceptance" in attrs["langfuse.observation.status_message"]
    assert _span(payload)["status"]["code"] == 1


def test_transport_exception_remains_error_even_with_passed_verification_label():
    row = _row(kind="span", status="failed", attributes={"verification_status": "passed", "exception_type": "ReadTimeout"})
    row["name"] = "patch.verify"
    payload = build_patch_live_otlp(row)
    attrs = _attributes(payload)
    assert attrs["langfuse.observation.level"] == "ERROR"
    assert attrs["langfuse.observation.status_message"] == "operation_failed:ReadTimeout"
    assert _span(payload)["status"]["code"] == 2


@pytest.mark.parametrize("workflow_status", ["partial", "blocked", "failed"])
def test_completed_root_with_negative_workflow_state_is_not_default_success(workflow_status):
    payload = build_patch_live_otlp(_row(0, kind="span", attributes={"workflow_status": workflow_status}))
    attrs = _attributes(payload)
    assert attrs["langfuse.observation.level"] == "WARNING"
    assert "workflow_status=" + workflow_status in attrs["langfuse.observation.status_message"]


def test_generic_completed_operation_and_unproven_pass_do_not_claim_task_acceptance():
    plain = _attributes(build_patch_live_otlp(_row(kind="span", attributes={})))
    assert plain["langfuse.observation.status_message"] == "operation_completed;not_task_acceptance"
    row = _row(kind="span", attributes={"verification_status": "passed", "execution_origin": "unknown"})
    row["name"] = "patch.verify"
    attrs = _attributes(build_patch_live_otlp(row))
    assert attrs["langfuse.observation.level"] == "DEFAULT"
    assert "execution_origin=unknown" in attrs["langfuse.observation.status_message"]
    assert "not_task_acceptance" in attrs["langfuse.observation.status_message"]


def test_payload_is_strict_metadata_only_and_filters_free_text_paths_and_secrets():
    row = _row(attributes={"model": "qwen3.8-max", "provider": "qwen_chat", "turn_index": 2,
        "request_sha256": "a"*64, "response_sha256": "b"*64, "byte_count": 42, "reused": False,
        "request_ref": {"path": "C:/SECRET/request.json"}, "input": "SECRET_PROMPT", "output": "SECRET_SOURCE",
        "error": "SECRET_EXCEPTION", "exception_type": "ValueError", "raw_response": {"secret": "SECRET_RESPONSE"},
        "tool_name": "C:/SECRET/tool", "call_id": "SECRET_CALL_ID",
        "artifact_refs": [{"artifact_type": "patch_proposal", "artifact_hash": "c"*64,
            "revision": 2, "path": "C:/SECRET/proposal.json", "description": "SECRET_DESCRIPTION"}],
        "cost_details": {"total": 0}, "prompt_name": "SECRET_MANAGED_PROMPT"})
    row["input"] = "SECRET_TOP_LEVEL"
    row["output"] = "SECRET_TOP_LEVEL_SOURCE"
    payload = build_patch_live_otlp(row)
    text = json.dumps(payload)
    assert "SECRET" not in text and "C:/" not in text
    attrs = _attributes(payload)
    assert attrs["langfuse.observation.metadata.byte_count"] == "42"
    assert json.loads(attrs["langfuse.observation.metadata.artifact_refs"])[0] == {
        "artifact_type": "patch_proposal", "artifact_hash": "c"*64, "revision": 2}
    assert "langfuse.observation.input" not in attrs and "langfuse.observation.output" not in attrs
    assert attrs["langfuse.observation.metadata.exception_type"] == "ValueError"
    row["attributes"]["exception_type"] = "ValueError: SECRET_EXCEPTION_BODY"
    assert "langfuse.observation.metadata.exception_type" not in _attributes(build_patch_live_otlp(row))


def test_workflow_and_tool_consumption_metadata_links_only_explicit_hashes():
    row = _row(attributes={"transport_started": True, "request_bytes": 1200, "workflow_node": "generate_patch_proposal",
        "workflow_status": "failed", "terminal_stage": "generate_patch_proposal", "failure_code": "PATCH_AGENT_PROVIDER_TURN_FAILED",
        "proposal_admitted": False, "verification_status": "behavior_failed", "failure_owner": "patch_implementation",
        "execution_origin": "executed", "callback_invoked": True, "output_sha256": "a"*64,
        "generated_changes_sha256": "b"*64, "baseline_sha256": "sha256:"+"c"*64, "file_count": 1,
        "tool_call_ids": ["source-call-1"], "call_id": "source-call-1",
        "consumed_tool_results": [{"call_id": "source-call-1", "observation_sha256": "d"*64,
            "output": "SECRET_TOOL_SOURCE"}],
        "artifact_refs": {"patch_proposal": {"artifact_type": "patch_proposal", "artifact_hash": "e"*64,
            "path": "C:/SECRET/source.json"}}})
    payload = build_patch_live_otlp(row)
    attrs = _attributes(payload)
    prefix = "langfuse.observation.metadata."
    assert attrs[prefix+"transport_started"] is True and attrs[prefix+"proposal_admitted"] is False
    consumed = json.loads(attrs[prefix+"consumed_tool_results"])
    assert consumed[0]["call_id_sha256"] == attrs[prefix+"call_id_sha256"]
    assert json.loads(attrs[prefix+"tool_call_id_sha256s"]) == [attrs[prefix+"call_id_sha256"]]
    assert consumed[0]["observation_sha256"] == "d"*64
    assert attrs[prefix+"workflow_node"] == "generate_patch_proposal"
    assert attrs[prefix+"baseline_sha256"] == "sha256:"+"c"*64
    assert "SECRET" not in json.dumps(payload)


def test_real_loop_source_attribute_producers_preserve_result_hash_and_consumption_link(tmp_path):
    from src.mod_agent.proposal.patch_agent_loop import (
        _source_result_trace_attributes,
        _source_trace_attributes,
    )
    from tests.unit.test_patch_agent_loop import _fixture, _response, _tool_call

    _, _, _, inspector = _fixture(tmp_path)
    call = _tool_call("edit_binding_001", turn=1)
    response = _response(turn=1, content="SECRET_TOOL_EXPLANATION", tool_calls=(call,))
    observation = inspector.inspect(binding_id="edit_binding_001", observation_id="observed-source-1")
    encoded = observation.model_view()
    tool_attributes = {**_source_trace_attributes(call, response, 1),
        **_source_result_trace_attributes(observation, encoded, True), "read_cost": 1, "reused": False}
    tool = _attributes(build_patch_live_otlp(_row(kind="tool", attributes=tool_attributes)))
    prefix = "langfuse.observation.metadata."
    assert tool[prefix+"encoded_payload_sha256"] == tool_attributes["encoded_payload_sha256"]
    assert tool[prefix+"source_snapshot_sha256"] == observation.source_snapshot_sha256
    assert tool[prefix+"tool_dispatch_performed"] and tool[prefix+"observation_queued"]
    assert tool[prefix+"model_consumption_proven"] is False
    generation = _attributes(build_patch_live_otlp(_row(attributes={"consumed_tool_results": [
        {"call_id": call.call_id, "observation_sha256": tool_attributes["encoded_payload_sha256"]}]})))
    consumed = json.loads(generation[prefix+"consumed_tool_results"])[0]
    assert consumed["call_id_sha256"] == tool[prefix+"call_id_sha256"]
    assert consumed["observation_sha256"] == tool[prefix+"encoded_payload_sha256"]
    assert "SECRET" not in json.dumps(tool)


def test_neutral_execution_trace_exports_one_generation_not_its_model_request_parent(monkeypatch):
    from src.core.trace.execution_trace import ExecutionTrace, trace_operation

    transport, requests = _transport(monkeypatch)
    sink = PatchLiveLangfuseSink(transport)
    trace = ExecutionTrace("neutral-run-1", "session-1", "local-test", sink=sink)
    with trace.activate():
        with trace.model_call({"model": "qwen3.8-max", "provider": "qwen_chat"}) as call:
            call.transport_started()
            call.record_response(usage={"input_tokens": 10, "output_tokens": 4}, usage_available=True)
        with trace_operation("patch.tool", kind="tool", attributes={"tool_call_id": "read-1", "read_cost": 1}):
            pass
    result = sink.shutdown(timeout_millis=1000)
    assert result["invalid_records"] == 0 and result["http_accepted"] == 4
    bodies = [json.loads(r.content) for r in requests]
    assert sum(_attributes(p)["langfuse.observation.type"] == "generation" for p in bodies) == 1
    assert sum("langfuse.observation.usage_details" in _attributes(p) for p in bodies) == 1
    spans = [_span(p) for p in bodies]
    root = next(s for s in spans if "parentSpanId" not in s)
    model_parent = next(s for s in spans if s["name"] == "model.request")
    generation = next(s for s in spans if s["name"] == "patch.generate")
    assert generation["parentSpanId"] == model_parent["spanId"]
    assert model_parent["parentSpanId"] == root["spanId"]


@pytest.mark.parametrize("change", [
    {"started_at": "2026-09-08T08:00:00"}, {"finished_at": None},
    {"finished_at": "2026-09-08T07:00:00+00:00"}, {"status": "running"},
    {"session_id": "C:/SECRET/session"}, {"name": "SECRET free text"}, {"parent_id": "0000000000000001"},
])
def test_invalid_neutral_rows_are_not_given_invented_times_or_parentage(change):
    with pytest.raises(ValueError):
        build_patch_live_otlp({**_row(), **change})


def test_non_otel_neutral_ids_map_consistently_without_raw_identity_disclosure():
    row = _row()
    row.update(trace_id="trace-long-identifier", id="child-long-identifier", parent_id="parent-long-identifier")
    span = _span(build_patch_live_otlp(row))
    assert span["traceId"] == live_trace_id(row["trace_id"])
    assert span["spanId"] == live_observation_id(row["id"])
    assert span["parentSpanId"] == live_observation_id(row["parent_id"])
    assert len(span["traceId"]) == 32 and len(span["spanId"]) == 16
    assert "long-identifier" not in json.dumps(span)


def test_start_not_exported_finish_is_immutable_and_normal_shutdown_closes_worker(monkeypatch):
    transport, requests = _transport(monkeypatch)
    sink = PatchLiveLangfuseSink(transport)
    sink.publish(_row(status="running"))
    row = _row()
    sink.publish(row)
    row["attributes"]["model"] = "mutated-after-publish"
    result = sink.shutdown(timeout_millis=1000)
    assert result["running_not_exported"] == 1 and result["http_accepted"] == 1
    assert result["pending"] == 0 and not result["worker_alive"] and not result["deadline_exhausted"]
    assert result["remote_readback"] == "not_performed"
    assert _attributes(json.loads(requests[0].content))["langfuse.observation.model.name"] == "qwen3.8-max"
    sink.publish(_row(2))
    assert sink.stats()["rejected_after_shutdown"] == 1 and len(requests) == 1


@pytest.mark.parametrize("response,error,field", [
    ({"partialSuccess": {"rejectedSpans": "1"}}, None, "partial_responses"),
    ({"partialSuccess": "not-a-protocol-object"}, None, "send_failures"),
    ({}, httpx.ReadTimeout("SECRET_SINK_EXCEPTION"), "send_failures"),
])
def test_transport_failure_or_partial_acknowledgement_never_retries_or_claims_readback(monkeypatch, response, error, field):
    transport, requests = _transport(monkeypatch, response=response, error=error)
    sink = PatchLiveLangfuseSink(transport)
    sink.publish(_row(status="failed"))
    result = sink.flush(timeout_millis=1000)
    sink.publish(_row(status="failed"))
    closed = sink.shutdown(timeout_millis=1000)
    assert result[field] == 1 and result["http_accepted"] == 0
    assert closed["duplicate_records"] == 1 and len(requests) == 1
    assert "SECRET" not in json.dumps(closed) and closed["remote_readback"] == "not_performed"
    assert _span(json.loads(requests[0].content))["status"]["code"] == 2


def test_nonblocking_queue_and_total_shutdown_deadline_do_not_wait_for_stuck_transport():
    entered, release = threading.Event(), threading.Event()

    class SlowTransport:
        def _request(self, method, path, **kwargs):
            entered.set()
            assert release.wait(3), "Test must release the synthetic blocked transport"
            return {}

    sink = PatchLiveLangfuseSink(SlowTransport(), max_queue_size=1, max_recent_ids=1)
    try:
        sink.publish(_row(1))
        assert entered.wait(1)
        started = time.monotonic()
        sink.publish(_row(2))
        sink.publish(_row(3))
        sink.publish(_row(1))  # Still active even though bounded recent cache evicted it.
        assert time.monotonic() - started < 0.25
        flushed = sink.flush(timeout_millis=20)
        assert flushed["pending"] == 2 and flushed["queue_dropped"] == 1 and flushed["duplicate_records"] == 1
        started = time.monotonic()
        closed = sink.shutdown(timeout_millis=30)
        assert time.monotonic() - started < 0.25
        assert closed["pending"] == 2 and closed["worker_alive"] and closed["deadline_exhausted"]
        sink.publish(_row(4))
        assert sink.stats()["rejected_after_shutdown"] == 1
    finally:
        release.set()
        final = sink.shutdown(timeout_millis=1000)
    assert final["pending"] == 0 and final["post_attempts"] == 2 and not final["worker_alive"]


def test_invalid_conflicting_and_oversized_records_are_counted_without_throwing(monkeypatch):
    transport, _ = _transport(monkeypatch)
    sink = PatchLiveLangfuseSink(transport)
    first = _row()
    sink.publish(first)
    changed = deepcopy(first)
    changed["attributes"]["model"] = "another-model"
    sink.publish(changed)
    sink.publish({"input": "SECRET_BAD_ROW"})
    result = sink.shutdown(timeout_millis=1000)
    assert result["conflicting_updates"] == result["invalid_records"] == 1
    small = PatchLiveLangfuseSink(transport, max_payload_bytes=1024)
    small.publish(_row())
    result = small.shutdown(timeout_millis=1000)
    assert result["invalid_records"] == 1 and result["post_attempts"] == 0
