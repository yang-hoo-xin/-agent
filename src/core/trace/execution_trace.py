"""Prospective execution observations using the existing TraceContext storage.

No execution, model, budget, persistence or network decisions live here. Callers
provide safe metadata and install recorder/sink boundaries. ContextVars propagate
through nested calls and copied contexts; arbitrary threads require explicit bind.
"""
from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from src.core.trace.trace_context import TraceContext

_ACTIVE_TRACE: ContextVar[ExecutionTrace | None] = ContextVar("execution_trace", default=None)
_ACTIVE_PARENT: ContextVar[tuple[ExecutionTrace, str] | None] = ContextVar("execution_trace_parent", default=None)


class _NoopSpan:
    observation_id = None

    def update(self, **attributes: Any):
        return self


class ExecutionSpan:
    """One observation; updates affect attributes, never identity or timestamps."""

    def __init__(self, trace, name, kind, attributes, parent_id, *, root=False):
        self._trace = trace
        self._root = root
        self._started_perf_ns = time.perf_counter_ns()
        self._data = {
            "id": uuid4().hex[:16],
            "parent_id": parent_id,
            "trace_id": trace.context.trace_id,
            "session_id": trace.session_id,
            "environment": deepcopy(trace.environment),
            "name": name,
            "kind": kind,
            "status": "running",
            "started_at": trace.context.started_at if root else datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "elapsed_ms": None,
            "attributes": deepcopy(dict(attributes or {})),
        }
        trace._publish(self._data)

    @property
    def observation_id(self) -> str:
        return self._data["id"]

    def update(self, **attributes: Any):
        with self._trace._lock:
            self._data["attributes"].update(deepcopy(attributes))
            self._trace._publish(self._data)
        return self

    def _finish(self, error: BaseException | None = None):
        with self._trace._lock:
            if self._data["finished_at"] is not None:
                return
            if self._root:
                self._trace.context.finish()
                finished = self._trace.context.finished_at
                elapsed = self._trace.context.elapsed_ms()
            else:
                finished = datetime.now(timezone.utc).isoformat()
                elapsed = (time.perf_counter_ns() - self._started_perf_ns) / 1_000_000
            self._data.update(status="failed" if error is not None else "completed",
                              finished_at=finished, elapsed_ms=elapsed)
            if error is not None:
                self._data["attributes"]["exception_type"] = type(error).__name__
            self._trace._publish(self._data)


class _ModelCall:
    def __init__(self, trace, parent):
        self._trace = trace
        self._parent = parent
        self._generation: ExecutionSpan | None = None

    @property
    def observation_id(self):
        return self._parent.observation_id

    def update(self, **attributes):
        self._parent.update(**attributes)
        if self._generation is not None:
            self._generation.update(**attributes)
        return self

    def transport_started(self):
        """Called at the real transport boundary, never during request preview."""
        if self._generation is None:
            self._parent.update(transport_started=True)
            self._generation = ExecutionSpan(self._trace, "patch.generate", "generation",
                self._parent._data["attributes"], self._parent.observation_id)
        return self._generation

    def record_response(self, response_info=None, usage=None, **attributes):
        values = {**dict(response_info or {}), **attributes, "response_received": True}
        if usage is not None:
            values["usage"] = deepcopy(dict(usage))
        # Missing usage remains absent; the caller supplies usage_available.
        return self.update(**values)

    def _finish(self, error=None):
        if self._generation is not None:
            self._generation._finish(error)


class ExecutionTrace:
    """An in-memory TraceContext with optional fail-open observation consumers."""

    def __init__(self, trace_id, session_id, environment, recorder: Callable | None = None,
                 sink=None, *, root_name="patch.execution"):
        self.context = TraceContext(trace_type="execution", trace_id=trace_id,
            metadata={"session_id": session_id, "environment": deepcopy(environment)})
        self.session_id = session_id
        self.environment = deepcopy(environment)
        self.root_name = root_name
        self.recorder, self.sink = recorder, sink
        self._root: ExecutionSpan | None = None
        self._lock = RLock()
        self._failures: dict[str, Counter] = {"recorder": Counter(), "sink": Counter()}

    def failure_statistics(self):
        with self._lock:
            return {name: {"total": sum(counts.values()), "by_exception_type": dict(counts)}
                    for name, counts in self._failures.items()}

    def update(self, **attributes):
        """Attach product outcome facts without changing the scope lifecycle status."""
        if self._root is not None:
            self._root.update(**attributes)
        return self

    def _publish(self, observation):
        with self._lock:
            snapshot = deepcopy(observation)
            self.context.record_stage(snapshot["name"], snapshot, snapshot["elapsed_ms"])
            for name, consumer in (("recorder", self.recorder), ("sink", self.sink)):
                if consumer is None:
                    continue
                try:
                    callback = consumer if name == "recorder" else consumer.publish
                    callback(deepcopy(snapshot))
                except BaseException as error:
                    self._failures[name][type(error).__name__] += 1

    @contextmanager
    def activate(self):
        if current_trace() is self:
            yield self
            return
        with self._lock:
            owns_root = self._root is None
            if owns_root:
                self._root = ExecutionSpan(self, self.root_name, "span", {}, None, root=True)
            elif self.context.finished_at is not None:
                raise RuntimeError("A finished execution trace cannot be reactivated.")
        trace_token = _ACTIVE_TRACE.set(self)
        parent_token = _ACTIVE_PARENT.set((self, self._root.observation_id))
        error = None
        try:
            yield self
        except BaseException as caught:
            error = caught
            raise
        finally:
            try:
                if owns_root:
                    self._root._finish(error)
            finally:
                _ACTIVE_PARENT.reset(parent_token)
                _ACTIVE_TRACE.reset(trace_token)

    @contextmanager
    def _operation(self, name, kind="span", attributes=None, parent_id=None):
        current_parent = _ACTIVE_PARENT.get()
        if parent_id is None:
            parent_id = current_parent[1] if current_parent and current_parent[0] is self else self._root.observation_id
        span = ExecutionSpan(self, name, kind, attributes, parent_id)
        token = _ACTIVE_PARENT.set((self, span.observation_id))
        error = None
        try:
            yield span
        except BaseException as caught:
            error = caught
            raise
        finally:
            try:
                span._finish(error)
            finally:
                _ACTIVE_PARENT.reset(token)

    @contextmanager
    def model_call(self, attributes: Mapping[str, Any] | None = None):
        if current_trace() is not self:
            with self.activate():
                with self.model_call(attributes) as call:
                    yield call
            return
        with self._operation("model.request", attributes=attributes) as parent:
            call = _ModelCall(self, parent)
            error = None
            try:
                yield call
            except BaseException as caught:
                error = caught
                raise
            finally:
                call._finish(error)


def current_trace() -> ExecutionTrace | None:
    return _ACTIVE_TRACE.get()


@contextmanager
def trace_operation(name, kind="span", attributes=None, parent_id=None):
    trace = current_trace()
    if trace is None:
        yield _NoopSpan()
        return
    with trace._operation(name, kind, attributes, parent_id) as span:
        yield span
