"""Focused tests for provider-neutral structured Agent turns."""

from __future__ import annotations

import hashlib
import json

import pytest

from src.libs.llm import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolCall,
    AgentToolDefinition,
    AgentToolResult,
    AgentTurnProviderError,
    AgentTurnRequest,
    OllamaChatAgentAdapter,
    OpenAIResponsesAgentAdapter,
    QwenChatAgentAdapter,
)
from src.libs.llm.agent_turn import AgentToolExchange


def _tool() -> AgentToolDefinition:
    return AgentToolDefinition(
        name="search_dotnet_metadata",
        description="Search exact metadata.",
        parameters={
            "type": "object",
            "properties": {"source_id": {"type": "string"}},
            "required": ["source_id"],
            "additionalProperties": False,
        },
    )


def _format() -> AgentResponseFormat:
    return AgentResponseFormat(
        name="finish",
        description="Finish object.",
        schema={
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["finish"]}},
            "required": ["action"],
            "additionalProperties": False,
        },
    )


def test_qwen_chat_adapter_uses_native_tools_without_thinking_or_parallel_calls() -> None:
    captured: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def send(url, payload, headers):
        captured.append((url, payload, headers))
        return {
            "id": "chatcmpl-qwen-001",
            "model": "qwen3.6-plus",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-qwen-001",
                                "type": "function",
                                "function": {
                                    "name": "search_dotnet_metadata",
                                    "arguments": json.dumps({"source_id": "r8-modules"}),
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        }

    adapter = QwenChatAgentAdapter(
        api_key="not-a-real-key",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3.6-plus",
        max_completion_tokens=4096,
        request_sender=send,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "find methods"}),),
            tools=(_tool(),),
            parallel_tool_calls=False,
        )
    )

    payload = captured[0][1]
    assert captured[0][0].endswith("/chat/completions")
    assert payload["enable_thinking"] is False
    assert payload["parallel_tool_calls"] is False
    assert payload["stream"] is False
    assert payload["max_completion_tokens"] == 4096
    assert "strict" not in payload["tools"][0]["function"]
    assert response.tool_calls == (
        AgentToolCall(
            call_id="call-qwen-001",
            name="search_dotnet_metadata",
            arguments={"source_id": "r8-modules"},
        ),
    )
    assert response.usage.input_tokens == 100
    assert response.usage.output_tokens == 20
    assert response.provider_diagnostic == {
        "api_type": "openai_compatible_chat_completions",
        "streaming": False,
        "provider_request_id": "chatcmpl-qwen-001",
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "tool_call_id": "call-qwen-001",
                "provider_reported_tool_name": "search_dotnet_metadata",
                "adapter_extracted_tool_name": "search_dotnet_metadata",
                "normalized_tool_name": "search_dotnet_metadata",
                "normalization_applied": False,
                "arguments_valid_json": True,
                "arguments_is_object": True,
                "arguments_sha256": hashlib.sha256(
                    json.dumps({"source_id": "r8-modules"}).encode("utf-8")
                ).hexdigest(),
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "reasoning_tokens": 0,
            "cached_input_tokens": 0,
        },
    }


def test_qwen_chat_adapter_preserves_unknown_provider_tool_name() -> None:
    def send(url, payload, headers):
        return {
            "id": "chatcmpl-qwen-unknown",
            "model": "qwen3.6-plus",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-qwen-unknown",
                                "type": "function",
                                "function": {
                                    "name": "search_metadata",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 17, "completion_tokens": 4},
        }

    response = QwenChatAgentAdapter(
        api_key="not-a-real-key",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3.6-plus",
        max_completion_tokens=4096,
        request_sender=send,
    ).complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content="use a tool"),),
            tools=(_tool(),),
        )
    )

    assert response.tool_calls[0].name == "search_metadata"
    diagnostic = response.provider_diagnostic
    assert diagnostic is not None
    assert diagnostic["usage"]["total_tokens"] == 21
    assert diagnostic["tool_calls"][0]["provider_reported_tool_name"] == (
        "search_metadata"
    )
    assert diagnostic["tool_calls"][0]["adapter_extracted_tool_name"] == (
        "search_metadata"
    )


def test_qwen_chat_adapter_preserves_diagnostic_when_arguments_are_invalid() -> None:
    def send(url, payload, headers):
        return {
            "id": "chatcmpl-qwen-invalid-arguments",
            "model": "qwen3.6-plus",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-qwen-invalid-arguments",
                                "type": "function",
                                "function": {
                                    "name": "search_dotnet_metadata",
                                    "arguments": "{",
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 19, "completion_tokens": 2},
        }

    adapter = QwenChatAgentAdapter(
        api_key="not-a-real-key",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3.6-plus",
        max_completion_tokens=4096,
        request_sender=send,
    )
    with pytest.raises(AgentTurnProviderError) as raised:
        adapter.complete_turn(
            AgentTurnRequest(
                messages=(AgentMessage(role="user", content="use a tool"),),
                tools=(_tool(),),
            )
        )

    diagnostic = raised.value.diagnostic
    assert diagnostic["provider_request_id"] == "chatcmpl-qwen-invalid-arguments"
    assert diagnostic["usage"]["total_tokens"] == 21
    tool_call = diagnostic["tool_calls"][0]
    assert tool_call["provider_reported_tool_name"] == "search_dotnet_metadata"
    assert tool_call["adapter_extracted_tool_name"] == ""
    assert tool_call["arguments_valid_json"] is False
    assert tool_call["arguments_is_object"] is False


def test_qwen_chat_adapter_links_local_tool_result_to_exact_call_id() -> None:
    captured: list[dict[str, object]] = []

    def send(url, payload, headers):
        captured.append(payload)
        return {
            "id": "chatcmpl-qwen-002",
            "model": "qwen3.6-plus",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"action":"finish"}'},
                }
            ],
            "usage": {},
        }

    raw_tool_call = {
        "id": "call-qwen-001",
        "type": "function",
        "function": {
            "name": "search_dotnet_metadata",
            "arguments": '{"source_id":"r8-modules"}',
        },
    }
    adapter = QwenChatAgentAdapter(
        api_key="not-a-real-key",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3.6-plus",
        max_completion_tokens=4096,
        request_sender=send,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "finish"}),),
            tools=(),
            tool_choice="none",
            response_format=_format(),
            tool_results=(
                AgentToolResult(
                    call_id="call-qwen-001",
                    name="search_dotnet_metadata",
                    output={"observation_id": "obs-001"},
                ),
            ),
            provider_state={"content": None, "tool_calls": [raw_tool_call]},
        )
    )

    messages = captured[0]["messages"]
    assert messages[-2]["tool_calls"][0]["id"] == "call-qwen-001"
    assert messages[-1]["tool_call_id"] == "call-qwen-001"
    assert captured[0]["response_format"] == {"type": "json_object"}
    assert response.content == '{"action":"finish"}'


def test_ollama_request_identity_matches_actual_httpx_body(monkeypatch) -> None:
    import httpx

    captured = []

    def respond(request):
        captured.append(request.content)
        return httpx.Response(
            200,
            json={"model": "local-code-model", "message": {"content": '{"ok":true}'}},
        )

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs)
    )

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434", model="local-code-model", max_output_tokens=128,
        context_window=4096,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(messages=(AgentMessage(role="user", content={"原文": "保留源码\r\n"}),))
    )
    identity = response.provider_diagnostic["request_identity"]
    assert len(captured) == 1
    assert identity == {
        "provider_body_sha256": hashlib.sha256(captured[0]).hexdigest(),
        "provider_body_utf8_bytes": len(captured[0]),
        "hash_basis": "httpx_json_body_bytes",
    }


@pytest.mark.parametrize("provider", ["ollama", "qwen", "openai"])
def test_provider_preserves_multiple_native_exchanges_at_message_boundaries(provider: str) -> None:
    captured = []

    def send(_url, payload, _headers):
        captured.append(payload)
        if provider == "ollama":
            return {"model": "model", "message": {"content": "done"}}
        if provider == "qwen":
            return {"model": "model", "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}]}
        return {"model": "model", "output": [{"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "done"}]}]}

    if provider == "ollama":
        adapter = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="model", max_output_tokens=64, request_sender=send)
    elif provider == "qwen":
        adapter = QwenChatAgentAdapter(api_key="test", base_url="https://example.invalid/v1", model="model", max_completion_tokens=64, request_sender=send)
    else:
        adapter = OpenAIResponsesAgentAdapter(api_key="test", model="model", max_output_tokens=64, request_sender=send)

    def state(call_id):
        if provider == "openai":
            return [{"type": "function_call", "call_id": call_id, "name": "inspect", "arguments": "{}"}]
        return {"content": "", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "inspect", "arguments": "{}"}}]}

    request = AgentTurnRequest(messages=(AgentMessage(role="user", content="initial"),
        AgentMessage(role="assistant", content="draft"), AgentMessage(role="user", content="failure")),
        historical_tool_exchanges=(AgentToolExchange((AgentToolResult("old", "inspect", {"value": "old-source"}),), state("old"), 1),),
        tool_results=(AgentToolResult("new", "inspect", {"value": "new-source"}),),
        provider_state=state("new"), tool_result_insert_index=3)
    adapter.complete_turn(request)
    messages = captured[0]["input" if provider == "openai" else "messages"]
    assert len(messages) == 7
    assert messages[0]["content"] == "initial"
    assert messages[3]["content"] == "draft"
    assert messages[4]["content"] == "failure"
    assert "old-source" in json.dumps(messages[2])
    assert "new-source" in json.dumps(messages[6])
    assert "old" in json.dumps(messages[1]) and "new" in json.dumps(messages[5])


def test_historical_exchange_invalid_boundary_is_rejected_before_send() -> None:
    adapter = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="model", max_output_tokens=64,
        request_sender=lambda *_: pytest.fail("Invalid tool history must not be sent"))
    request = AgentTurnRequest(messages=(AgentMessage(role="user", content="initial"),),
        historical_tool_exchanges=(AgentToolExchange((AgentToolResult("old", "inspect", {}),), {}, 2),))
    with pytest.raises(AgentTurnProviderError, match="AGENT_TOOL_HISTORY_INVALID"):
        adapter.complete_turn(request)


def test_ollama_request_identity_survives_transport_failure() -> None:
    import httpx

    body = None

    def fail(url, payload, _headers):
        nonlocal body
        body = httpx.Request("POST", url, json=payload).content
        raise AgentTurnProviderError("offline transport failure")

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434", model="local-code-model", max_output_tokens=128,
        context_window=4096, request_sender=fail,
    )
    with pytest.raises(AgentTurnProviderError) as raised:
        adapter.complete_turn(AgentTurnRequest(messages=(AgentMessage(role="user", content="source"),)))
    assert raised.value.diagnostic["request_identity"]["provider_body_sha256"] == hashlib.sha256(body).hexdigest()


def test_ollama_adapter_uses_native_tools_and_local_usage() -> None:
    captured: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def send(url, payload, headers):
        captured.append((url, payload, headers))
        return {
            "model": "qwen3:4b-instruct",
            "done": True,
            "done_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_dotnet_metadata",
                            "arguments": {"source_id": "r8-modules"},
                        }
                    }
                ],
            },
            "prompt_eval_count": 123,
            "eval_count": 17,
            "total_duration": 4_000_000_000,
            "load_duration": 500_000_000,
            "prompt_eval_duration": 1_000_000_000,
            "eval_duration": 2_000_000_000,
        }

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b-instruct",
        max_output_tokens=2048,
        context_window=32768,
        request_sender=send,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "find methods"}),),
            tools=(_tool(),),
        )
    )

    assert len(captured) == 1
    url, payload, headers = captured[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {
        "temperature": 0.0,
        "num_predict": 2048,
        "seed": 0,
        "num_ctx": 32768,
    }
    assert payload["tools"][0]["function"]["name"] == "search_dotnet_metadata"
    assert headers == {"Content-Type": "application/json"}
    assert response.tool_calls[0].call_id.startswith("ollama-call-")
    assert response.tool_calls[0].arguments == {"source_id": "r8-modules"}
    assert response.usage.input_tokens == 123
    assert response.usage.output_tokens == 17
    assert response.provider_diagnostic is not None
    assert response.provider_diagnostic["ollama_total_duration_ns"] == 4_000_000_000
    assert response.provider_diagnostic["ollama_load_duration_ns"] == 500_000_000
    assert response.provider_diagnostic["ollama_prompt_eval_duration_ns"] == 1_000_000_000
    assert response.provider_diagnostic["ollama_eval_duration_ns"] == 2_000_000_000
    assert response.provider_diagnostic["tokens_per_second"] == 8.5
    assert response.provider_diagnostic["first_token_duration_available"] is False
    projected_body_bytes = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert response.provider_diagnostic["context_admission"] == {
        "mode": "provider_body_utf8_proxy_plus_output_budget_v1",
        "exact_prompt_tokens_available_pre_call": False,
        "provider_body_utf8_bytes": projected_body_bytes,
        "configured_num_ctx": 32768,
        "num_predict": 2048,
        "conservative_required_context": projected_body_bytes + 2048,
        "admitted": True,
    }


def test_ollama_adapter_preserves_incomplete_response_for_worker_stop() -> None:
    raw = {"model": "local-code-model", "done": False,
        "message": {"role": "assistant", "content": '{"changes":['}}
    adapter = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434",
        model="local-code-model", max_output_tokens=128, context_window=4096,
        request_sender=lambda *_: raw)
    response = adapter.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "Submit patch"),)))
    assert response.stop_reason == "incomplete"
    assert response.content == raw["message"]["content"]
    assert response.raw_response == raw


def test_qwen_adapter_preserves_refusal_for_worker_stop() -> None:
    raw = {"model": "qwen3.6-plus", "choices": [{"finish_reason": "stop",
        "message": {"content": None, "refusal": "Request declined"}}]}
    adapter = QwenChatAgentAdapter(api_key="test-key",
        base_url="https://dashscope.example/compatible-mode/v1", model="qwen3.6-plus",
        max_completion_tokens=128, request_sender=lambda *_: raw)
    response = adapter.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "Submit patch"),)))
    assert response.stop_reason == "refusal" and response.content is None
    assert response.raw_response == raw


@pytest.mark.parametrize("stop", ["length", "content_filter"])
def test_qwen_stop_precedes_truncated_tool_arguments(stop) -> None:
    raw = {"model": "qwen3.6-plus", "choices": [{"finish_reason": stop,
        "message": {"content": None, "tool_calls": [{"id": "partial-tool", "type": "function",
            "function": {"name": "search_dotnet_metadata", "arguments": '{"source_id":'}}]}}]}
    adapter = QwenChatAgentAdapter(api_key="test-key",
        base_url="https://dashscope.example/compatible-mode/v1", model="qwen3.6-plus",
        max_completion_tokens=128, request_sender=lambda *_: raw)
    response = adapter.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "Inspect"),), tools=(_tool(),)))
    assert response.stop_reason == stop and response.tool_calls == ()
    assert response.raw_response == raw
    assert response.provider_diagnostic["tool_calls"][0]["arguments_valid_json"] is False


@pytest.mark.parametrize("native", [False, True])
def test_ollama_stop_precedes_required_tool_argument_parsing(native) -> None:
    message = {"role": "assistant", "content": '{"source_id":'}
    if native:
        message["tool_calls"] = [{"function": {"name": "search_dotnet_metadata", "arguments": '{"source_id":'}}]
    raw = {"model": "local-code-model", "done": False, "message": message}
    adapter = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434",
        model="local-code-model", max_output_tokens=128, context_window=4096,
        request_sender=lambda *_: raw)
    response = adapter.complete_turn(AgentTurnRequest(messages=(AgentMessage("user", "Inspect"),),
        tools=(_tool(),), tool_choice="required"))
    assert response.stop_reason == "incomplete" and response.tool_calls == ()
    assert response.raw_response == raw


def test_ollama_adapter_blocks_oversized_payload_before_sender() -> None:
    calls: list[dict[str, object]] = []

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b-instruct",
        max_output_tokens=64,
        context_window=128,
        request_sender=lambda _url, payload, _headers: calls.append(payload) or {},
    )

    with pytest.raises(AgentTurnProviderError) as exc_info:
        adapter.complete_turn(
            AgentTurnRequest(
                messages=(AgentMessage(role="user", content="x" * 512),),
            )
        )

    assert calls == []
    assert exc_info.value.diagnostic["failure_boundary"] == "provider_request_gate"
    assert exc_info.value.diagnostic["failure_classification"] == (
        "provider_request_context_budget_exceeded"
    )
    admission = exc_info.value.diagnostic["context_admission"]
    assert admission["configured_num_ctx"] == 128
    assert admission["num_predict"] == 64
    assert admission["admitted"] is False


def test_ollama_adapter_uses_same_model_observed_tokens_for_later_turn() -> None:
    captured: list[dict[str, object]] = []

    def send(_url, payload, _headers):
        captured.append(payload)
        body_bytes = len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        return {
            "model": "qwen3-coder:30b",
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": "done"},
            "prompt_eval_count": max(1, body_bytes // 4),
            "eval_count": 1,
        }

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3-coder:30b",
        max_output_tokens=128,
        context_window=2048,
        request_sender=send,
    )
    adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content="small" * 20),),
        )
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content="large" * 500),),
        )
    )

    assert len(captured) == 2
    admission = response.provider_diagnostic["context_admission"]
    assert admission["mode"] == (
        "same_model_observed_prompt_ratio_upper_bound_v1"
    )
    assert admission["observed_calibration_count"] == 1
    assert admission["safety_multiplier"] == 2.0
    assert admission["conservative_fallback_required_context"] > 2048
    assert admission["estimated_required_context"] <= 2048
    assert admission["admitted"] is True


def test_ollama_adapter_context_admission_counts_unicode_utf8() -> None:
    captured: list[dict[str, object]] = []

    def send(_url, payload, _headers):
        captured.append(payload)
        return {
            "model": "qwen3:4b-instruct",
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": "完成"},
        }

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b-instruct",
        max_output_tokens=64,
        context_window=4096,
        request_sender=send,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content="墙面😀" * 100),),
        )
    )

    expected_bytes = len(
        json.dumps(
            captured[0],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    admission = response.provider_diagnostic["context_admission"]
    assert admission["provider_body_utf8_bytes"] == expected_bytes
    assert admission["conservative_required_context"] == expected_bytes + 64
    assert admission["admitted"] is True


def test_ollama_adapter_admits_final_tools_format_and_tool_replay_payload() -> None:
    captured: list[dict[str, object]] = []

    def send(_url, payload, _headers):
        captured.append(payload)
        return {
            "model": "qwen3:4b-instruct",
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": '{"action":"finish"}'},
        }

    prior_tool_call = {
        "function": {
            "name": "search_dotnet_metadata",
            "arguments": {"source_id": "r8-modules"},
        }
    }
    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b-instruct",
        max_output_tokens=64,
        context_window=4096,
        request_sender=send,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "finish"}),),
            tools=(_tool(),),
            response_format=_format(),
            tool_results=(
                AgentToolResult(
                    call_id="ollama-call-local",
                    name="search_dotnet_metadata",
                    output={"observation_id": "obs-001", "relation_ids": ["r1"]},
                ),
            ),
            provider_state={"content": "", "tool_calls": [prior_tool_call]},
        )
    )

    payload = captured[0]
    assert "tools" in payload
    assert payload["format"] == _format().schema
    assert payload["messages"][-2]["tool_calls"] == [prior_tool_call]
    assert payload["messages"][-1]["tool_name"] == "search_dotnet_metadata"
    expected_bytes = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert response.provider_diagnostic["context_admission"][
        "provider_body_utf8_bytes"
    ] == expected_bytes


def test_ollama_adapter_recovers_required_single_tool_from_structured_content() -> None:
    captured: list[dict[str, object]] = []

    def send(url, payload, headers):
        captured.append(payload)
        return {
            "model": "qwen3:4b-instruct",
            "done": True,
            "done_reason": "stop",
            "message": {
                "role": "assistant",
                "content": '{"source_id":"r8-modules"}',
            },
        }

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b-instruct",
        max_output_tokens=2048,
        request_sender=send,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "select tool"}),),
            tools=(_tool(),),
            tool_choice="required",
        )
    )

    assert captured[0]["tools"][0]["function"]["name"] == "search_dotnet_metadata"
    assert captured[0]["format"] == _tool().parameters
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search_dotnet_metadata"
    assert response.tool_calls[0].arguments == {"source_id": "r8-modules"}
    assert response.provider_state == {
        "content": '{"source_id":"r8-modules"}',
        "tool_calls": [
            {
                "function": {
                    "name": "search_dotnet_metadata",
                    "arguments": {"source_id": "r8-modules"},
                }
            }
        ],
    }
    assert response.provider_diagnostic["context_admission"][
        "provider_body_utf8_bytes"
    ] == len(
        json.dumps(
            captured[0],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def test_ollama_adapter_does_not_force_format_for_auto_tool_choice() -> None:
    captured: list[dict[str, object]] = []

    def send(url, payload, headers):
        captured.append(payload)
        return {
            "model": "qwen3:4b-instruct",
            "done": True,
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_dotnet_metadata",
                            "arguments": {"source_id": "r8-modules"},
                        }
                    }
                ],
            },
        }

    adapter = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b-instruct",
        max_output_tokens=2048,
        request_sender=send,
    )
    response = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "select tool"}),),
            tools=(_tool(),),
            tool_choice="auto",
        )
    )

    assert "format" not in captured[0]
    assert response.provider_diagnostic["context_admission"] == {
        "mode": "context_admission_unavailable_not_configured_v1",
        "exact_prompt_tokens_available_pre_call": False,
        "provider_body_utf8_bytes": len(
            json.dumps(
                captured[0],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
        "configured_num_ctx": None,
        "num_predict": 2048,
        "conservative_required_context": None,
        "admitted": None,
    }


def test_ollama_adapter_replays_native_tool_exchange_and_forces_schema() -> None:
    captured: list[dict[str, object]] = []

    def send(url, payload, headers):
        captured.append(payload)
        return {
            "model": "qwen3:4b-instruct",
            "done": True,
            "message": {"role": "assistant", "content": '{"action":"finish"}'},
        }

    raw_call = {
        "function": {
            "name": "search_dotnet_metadata",
            "arguments": {"source_id": "r8-modules"},
        }
    }
    adapter = OllamaChatAgentAdapter(
        base_url="http://[::1]:11434/",
        model="qwen3:4b-instruct",
        max_output_tokens=2048,
        request_sender=send,
    )
    adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "finish"}),),
            tools=(),
            tool_choice="none",
            response_format=_format(),
            tool_results=(
                AgentToolResult(
                    call_id="ollama-call-local",
                    name="search_dotnet_metadata",
                    output={"observation_id": "obs-001"},
                ),
            ),
            provider_state={"content": "", "tool_calls": [raw_call]},
        )
    )

    assert captured[0]["messages"][-2]["tool_calls"] == [raw_call]
    assert captured[0]["messages"][-1]["tool_name"] == "search_dotnet_metadata"
    assert captured[0]["format"] == _format().schema
    assert "tools" not in captured[0]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:11434",
        "http://192.168.1.10:11434",
        "https://127.0.0.1:11434",
        "http://127.0.0.1:11434/api",
    ],
)
def test_ollama_adapter_rejects_non_literal_loopback_origin(base_url: str) -> None:
    with pytest.raises(ValueError, match="LITERAL_LOOPBACK"):
        OllamaChatAgentAdapter(
            base_url=base_url,
            model="qwen3:4b-instruct",
            max_output_tokens=2048,
            request_sender=lambda *_: {},
        )


def test_openai_responses_adapter_replays_only_bound_reasoning_call_and_output() -> None:
    captured: list[dict[str, object]] = []
    responses = [
        {
            "id": "resp_001",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "output": [
                {"type": "reasoning", "id": "rs_001", "summary": []},
                {
                    "type": "function_call",
                    "id": "fc_001",
                    "call_id": "call_001",
                    "name": "search_dotnet_metadata",
                    "arguments": '{"source_id":"r8-modules"}',
                },
            ],
            "usage": {
                "input_tokens": 80,
                "output_tokens": 12,
                "output_tokens_details": {"reasoning_tokens": 5},
            },
        },
        {
            "id": "resp_002",
            "model": "gpt-5.6-luna",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": '{"action":"finish"}'}
                    ],
                }
            ],
            "usage": {"input_tokens": 90, "output_tokens": 8},
        },
    ]

    def send(url, payload, headers):
        captured.append(payload)
        return responses.pop(0)

    adapter = OpenAIResponsesAgentAdapter(
        api_key="not-a-real-key",
        model="gpt-5.6-luna",
        max_output_tokens=2048,
        request_sender=send,
    )
    first = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "find methods"}),),
            tools=(_tool(),),
        )
    )
    second = adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "finish"}),),
            tools=(),
            tool_choice="none",
            response_format=_format(),
            tool_results=(
                AgentToolResult(
                    call_id="call_001",
                    name="search_dotnet_metadata",
                    output={"observation_id": "obs-001"},
                ),
            ),
            provider_state=first.provider_state,
        )
    )

    assert captured[0]["tools"][0]["strict"] is True
    second_input = captured[1]["input"]
    assert [item["type"] for item in second_input if "type" in item] == [
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert second_input[-1]["call_id"] == "call_001"
    assert captured[1]["text"]["format"]["strict"] is True
    assert first.usage.reasoning_tokens == 5
    assert second.content == '{"action":"finish"}'
