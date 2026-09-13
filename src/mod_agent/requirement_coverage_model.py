"""Shared structured-output adapter for requirement coverage model turns."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from src.libs.llm import ChatResponse, Message


def parse_requirement_coverage_json_object(content: str) -> dict[str, Any]:
    """Strictly parse one coverage response without duplicate or non-finite data."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("REQUIREMENT_COVERAGE_MODEL_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def reject_constant(_value: str) -> Any:
        raise ValueError("REQUIREMENT_COVERAGE_MODEL_NON_FINITE_JSON")

    try:
        value = json.loads(
            content,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("REQUIREMENT_COVERAGE_MODEL_INVALID_JSON") from exc
    _reject_non_finite_numbers(value)
    if not isinstance(value, dict):
        raise ValueError("REQUIREMENT_COVERAGE_MODEL_OUTPUT_NOT_OBJECT")
    return value


def _reject_non_finite_numbers(value: Any) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _reject_non_finite_numbers(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _reject_non_finite_numbers(nested)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("REQUIREMENT_COVERAGE_MODEL_NON_FINITE_JSON")


def request_requirement_coverage_model(
    *,
    llm: Any,
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    max_output_tokens: int,
    capture_provider_request: bool,
    stream_response: bool = False,
    stream_activity_recorder: Callable[[dict[str, Any]], None] | None = None,
    trace_role: str | None = None,
    trace_body_root: Any = None,
) -> tuple[ChatResponse, dict[str, Any]]:
    """Execute one strict admitted coverage turn without interpreting semantics."""

    provider_request: dict[str, Any] = {}

    def record_provider_request(value: dict[str, Any]) -> None:
        provider_request.update(
            {key: item for key, item in value.items() if key != "body_utf8"}
        )

    chat_options: dict[str, Any] = {
        "temperature": 0.0,
        "max_tokens": max_output_tokens,
        "response_format": dict(schema),
        "provider_request_recorder": (
            record_provider_request if capture_provider_request else None
        ),
    }
    if stream_response:
        chat_options["stream_response"] = True
        if stream_activity_recorder is not None:
            chat_options["stream_activity_recorder"] = stream_activity_recorder
    messages = [
            Message(
                role="system",
                content=(
                    "Return one strict JSON object matching the native response "
                    "schema. Do not return reasoning, markdown, stable identities, "
                    "sufficiency, edit authority, or execution authority."
                ),
            ),
            Message(
                role="user",
                content=json.dumps(
                    dict(payload),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        ]
    if trace_role is None:
        response = llm.chat(messages, **chat_options)
    else:
        from src.mod_agent.upstream_model_trace import trace_upstream_model_call
        response = trace_upstream_model_call(
            role=trace_role, provider=type(llm).__name__, model=getattr(llm, "model", None),
            input_payload=payload,
            request_document={"messages": [{"role": m.role, "content": m.content} for m in messages],
                              "response_format": dict(schema), "temperature": 0.0,
                              "max_tokens": max_output_tokens, "stream_response": stream_response},
            body_root=trace_body_root, invoke=lambda: llm.chat(messages, **chat_options))
    if not isinstance(response, ChatResponse):
        raise ValueError("REQUIREMENT_COVERAGE_MODEL_RESPONSE_INVALID")
    return response, provider_request
