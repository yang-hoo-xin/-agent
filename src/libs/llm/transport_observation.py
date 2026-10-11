"""Optional transport boundary notification; never changes the request or result."""

from contextlib import contextmanager
from contextvars import ContextVar

_observer = ContextVar("agent_transport_observer", default=None)


@contextmanager
def observe_transport(callback, response_callback=None, request_callback=None, *,
                      local_request_body_callback=None):
    token = _observer.set((callback, response_callback, request_callback, local_request_body_callback))
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


def transport_local_request_body(request):
    """Local-sender httpx hook: pass immutable wire bytes only to a local owner.

    Headers and the Request object never enter the callback or ordinary span.
    为什么要有它：实际发送字节不能由再次序列化猜测，记录失败也不能改变业务请求。
    """
    callbacks = _observer.get()
    callback = callbacks[3] if callbacks is not None else None
    if callback is None:
        return
    try:
        raw = request.content
        if isinstance(raw, bytes):
            callback(raw)
    except Exception:
        # Optional local persistence must not block or retry an admitted send.
        pass


def transport_request_prepared(*, request_identity, context_admission):
    """Observe the native owner's serialized request and admission, before send.

    Only measured hashes/counts and the selected estimate mode are projected.
    This callback cannot alter the payload, admit it, or signal a model send.
    """
    callbacks = _observer.get()
    callback = callbacks[2] if callbacks is not None else None
    if callback is None:
        return
    try:
        facts = {"provider_request_constructed": True, "transport_started": False, "response_received": False}
        digest = request_identity.get("provider_body_sha256")
        if isinstance(digest, str) and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            facts["provider_body_sha256"] = digest
        for key in ("provider_body_utf8_bytes", "configured_num_ctx", "num_predict", "conservative_required_context",
                    "estimated_prompt_tokens", "estimated_required_context", "observed_calibration_count"):
            value = context_admission.get(key)
            if type(value) is int and value >= 0:
                facts[key] = value
        for key, output in (("admitted", "provider_request_admitted"),
                            ("exact_prompt_tokens_available_pre_call", "exact_prompt_tokens_available_pre_call")):
            if type(context_admission.get(key)) is bool:
                facts[output] = context_admission[key]
        mode = context_admission.get("mode")
        if mode in {"provider_body_utf8_proxy_plus_output_budget_v1", "same_model_observed_prompt_ratio_upper_bound_v1"}:
            facts["context_admission_mode"] = mode
            facts["context_calibration_used"] = mode == "same_model_observed_prompt_ratio_upper_bound_v1"
        callback(**facts)
    except Exception:
        # Optional observation must not change this already-computed decision.
        pass


def transport_response_received(*, http_status, response_complete):
    callbacks = _observer.get()
    callback = callbacks[1] if callbacks is not None else None
    if callback is not None:
        try:
            callback(response_received=True, http_status=http_status, response_complete=response_complete)
        except Exception:
            pass
