"""Optional transport boundary notification; never changes the request or result."""

from contextlib import contextmanager
from contextvars import ContextVar

_observer = ContextVar("agent_transport_observer", default=None)


@contextmanager
def observe_transport(callback, response_callback=None):
    token = _observer.set((callback, response_callback))
    try:
        yield
    finally:
        _observer.reset(token)


def transport_started():
    callbacks = _observer.get()
    callback = callbacks[0] if callbacks is not None else None
    if callback is not None:
        try:
            callback()
        except Exception:
            # Instrumentation cannot block a send already admitted by its owner.
            pass


def transport_response_received(*, http_status, response_complete):
    callbacks = _observer.get()
    callback = callbacks[1] if callbacks is not None else None
    if callback is not None:
        try:
            callback(response_received=True, http_status=http_status, response_complete=response_complete)
        except Exception:
            pass
