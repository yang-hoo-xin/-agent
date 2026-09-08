"""Real clocks and neutral trace events, without models, sinks or Graph execution."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime

import pytest

from src.core.trace.execution_trace import ExecutionTrace, current_trace, trace_operation


def _latest(trace):
    return {stage["data"]["id"]: stage["data"] for stage in trace.context.stages}


def test_no_active_trace_is_noop_and_business_exception_propagates():
    assert current_trace() is None
    with pytest.raises(ValueError, match="business"):
        with trace_operation("unused") as span:
            assert span.observation_id is None
            span.update(ignored=True)
            raise ValueError("business")


def test_nested_operations_share_trace_context_clock_identity_and_emit_updates():
    events = []
    trace = ExecutionTrace("trace-1", "session-1", "test", recorder=events.append)
    with trace.activate():
        with trace_operation("plan") as first:
            first.update(artifact_hash="exact")
            with trace_operation("binding") as second:
                assert current_trace() is trace
            with trace_operation("explicit", parent_id=first.observation_id):
                pass
    assert current_trace() is None
    latest = _latest(trace)
    root = next(row for row in latest.values() if row["parent_id"] is None)
    assert root["name"] == "patch.execution"
    assert latest[first.observation_id]["parent_id"] == root["id"]
    assert latest[second.observation_id]["parent_id"] == first.observation_id
    assert latest[first.observation_id]["attributes"] == {"artifact_hash": "exact"}
    assert trace.context.trace_type == "execution" and trace.context.finished_at == root["finished_at"]
    for row in latest.values():
        assert row["trace_id"] == "trace-1" and row["session_id"] == "session-1"
        assert row["status"] == "completed" and row["elapsed_ms"] >= 0
        assert datetime.fromisoformat(row["started_at"]).tzinfo is not None
        assert datetime.fromisoformat(row["finished_at"]).tzinfo is not None
    assert len(events) == 9  # Four start/end pairs plus one attribute upsert.


def test_generation_exists_only_after_actual_transport_signal_and_is_idempotent():
    trace = ExecutionTrace("trace", "session", "test")
    with trace.activate():
        with trace.model_call({"provider": "offline"}) as preview:
            preview.update(admission="blocked")
        assert not any(row["kind"] == "generation" for row in _latest(trace).values())
        with trace.model_call({"provider": "offline"}) as call:
            generation = call.transport_started()
            assert call.transport_started() is generation
            call.record_response({"model": "unit", "usage_available": False})
    observations = list(_latest(trace).values())
    generations = [row for row in observations if row["kind"] == "generation"]
    assert len(generations) == 1 and generations[0]["name"] == "patch.generate"
    assert generations[0]["parent_id"] == call.observation_id
    assert generations[0]["attributes"]["response_received"] is True
    assert generations[0]["attributes"]["usage_available"] is False
    assert "usage" not in generations[0]["attributes"]


def test_response_usage_is_preserved_without_model_class_dependency():
    trace = ExecutionTrace("trace", "session", "test")
    with trace.model_call({"provider": "offline"}) as call:
        call.transport_started()
        call.record_response({"usage_available": True}, usage={"input_tokens": 5, "output_tokens": 2})
    rows = _latest(trace)
    assert rows[call.observation_id]["attributes"]["usage"] == {"input_tokens": 5, "output_tokens": 2}
    assert next(row for row in rows.values() if row["kind"] == "generation")["attributes"]["usage"] == {"input_tokens": 5, "output_tokens": 2}


def test_recorder_and_sink_failure_do_not_hide_baseexception_or_leak_its_message():
    events = []
    def broken_recorder(row):
        events.append(row)
        raise RuntimeError("sensitive recorder error")
    class BrokenSink:
        def publish(self, row):
            raise KeyboardInterrupt("sink-only cancellation")
    trace = ExecutionTrace("trace", "session", "test", recorder=broken_recorder, sink=BrokenSink())
    original = SystemExit("sensitive business error")
    with pytest.raises(SystemExit) as raised:
        with trace.activate():
            with trace.model_call() as call:
                call.transport_started()
                raise original
    assert raised.value is original and current_trace() is None
    latest = _latest(trace)
    assert all(row["status"] == "failed" for row in latest.values())
    assert all(row["attributes"]["exception_type"] == "SystemExit" for row in latest.values())
    assert "sensitive business error" not in str(events)
    stats = trace.failure_statistics()
    assert stats["recorder"]["total"] == len(events)
    assert stats["sink"]["by_exception_type"] == {"KeyboardInterrupt": len(events)}


def test_callback_cannot_mutate_stored_observation_or_other_consumer():
    sent = []
    def recorder(row):
        row["name"] = "changed"
    class Sink:
        publish = staticmethod(sent.append)
    trace = ExecutionTrace("trace", "session", "test", recorder=recorder, sink=Sink())
    with trace.activate():
        pass
    assert all(row["name"] == "patch.execution" for row in sent)
    assert all(row["name"] == "patch.execution" for row in _latest(trace).values())


def test_nested_traces_restore_parent_and_copied_context_supports_worker_thread():
    outer = ExecutionTrace("outer", "session", "test")
    inner = ExecutionTrace("inner", "session", "test", root_name="other.execution")
    with outer.activate():
        with trace_operation("parent") as parent:
            with inner.activate():
                with trace_operation("inside"):
                    assert current_trace() is inner
            with outer.activate():
                def child():
                    with trace_operation("thread-child") as span:
                        return span.observation_id
                with ThreadPoolExecutor(max_workers=1) as pool:
                    copied = copy_context()
                    child_id = pool.submit(copied.run, child).result()
            assert _latest(outer)[child_id]["parent_id"] == parent.observation_id
    assert current_trace() is None
    assert all(row["trace_id"] == "outer" for row in _latest(outer).values())
    assert all(row["trace_id"] == "inner" for row in _latest(inner).values())


def test_trace_outcome_attributes_do_not_turn_normal_blocked_return_into_exception():
    trace = ExecutionTrace("trace", "session", "test")
    trace.update(ignored_before_activation=True)
    with trace.activate():
        trace.update(workflow_status="blocked", terminal_stage="planning", proposal_admitted=False)
    root = next(row for row in _latest(trace).values() if row["parent_id"] is None)
    assert root["status"] == "completed"
    assert root["attributes"] == {"workflow_status": "blocked", "terminal_stage": "planning", "proposal_admitted": False}
