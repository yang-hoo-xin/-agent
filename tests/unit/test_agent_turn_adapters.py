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
    AgentTurnRequest,
    AgentTurnProviderError,
    OllamaChatAgentAdapter,
    OpenAIResponsesAgentAdapter,
    QwenChatAgentAdapter,
)


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
    adapter.complete_turn(
        AgentTurnRequest(
            messages=(AgentMessage(role="user", content={"goal": "select tool"}),),
            tools=(_tool(),),
            tool_choice="auto",
        )
    )

    assert "format" not in captured[0]


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
