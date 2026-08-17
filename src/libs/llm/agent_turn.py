"""Provider-neutral structured Agent turns and bounded provider adapters."""

from __future__ import annotations

import json
import time
from hashlib import sha256
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AgentMessage:
    """One provider-neutral instruction or context message."""

    role: Literal["system", "user", "assistant"]
    content: object


@dataclass(frozen=True)
class AgentToolDefinition:
    """One callable tool described by an exact JSON Schema."""

    name: str
    description: str
    parameters: dict[str, object]
    strict: bool = True


@dataclass(frozen=True)
class AgentResponseFormat:
    """Structured final-output contract."""

    name: str
    description: str
    schema: dict[str, object]
    strict: bool = True


@dataclass(frozen=True)
class AgentToolResult:
    """A deterministic local result linked to one provider tool call."""

    call_id: str
    name: str
    output: object


@dataclass(frozen=True)
class AgentTurnRequest:
    """One bounded structured turn, independent of provider wire format."""

    messages: tuple[AgentMessage, ...]
    tools: tuple[AgentToolDefinition, ...] = ()
    tool_choice: Literal["auto", "required", "none"] = "auto"
    parallel_tool_calls: bool = False
    response_format: AgentResponseFormat | None = None
    tool_results: tuple[AgentToolResult, ...] = ()
    tool_result_insert_index: int | None = None
    provider_state: object | None = None
    temperature: float = 0.0


@dataclass(frozen=True)
class AgentToolCall:
    """One normalized provider-requested tool call."""

    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class AgentUsage:
    """Normalized token accounting; unavailable values remain zero."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class AgentTurnResponse:
    """Normalized Agent response; raw provider data is diagnostic-only."""

    provider: str
    model: str
    content: str | None
    tool_calls: tuple[AgentToolCall, ...] = ()
    stop_reason: str | None = None
    request_id: str | None = None
    usage: AgentUsage = field(default_factory=AgentUsage)
    provider_state: object | None = None
    provider_diagnostic: dict[str, object] | None = None
    raw_response: object | None = None


class AgentTurnClient(Protocol):
    """Execute one provider-neutral structured Agent turn."""

    provider: str
    model: str

    def complete_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        ...


JsonRequestSender = Callable[[str, dict[str, object], dict[str, str]], dict[str, Any]]


class AgentTurnProviderError(RuntimeError):
    """Raised when a provider rejects or returns an invalid Agent turn."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic = dict(diagnostic or {})


class _HttpJsonSender:
    def __init__(self, *, api_key: str, timeout_seconds: float = 60.0) -> None:
        if not api_key:
            raise ValueError("Agent provider API key is required.")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def __call__(
        self,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        import httpx

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise AgentTurnProviderError(
                f"Agent provider request timed out after {self.timeout_seconds:g} seconds."
            ) from exc
        except httpx.RequestError as exc:
            raise AgentTurnProviderError(
                f"Agent provider connection failed: {type(exc).__name__}: {exc}"
            ) from exc
        if response.status_code != 200:
            try:
                error = response.json()
            except Exception:
                error = response.text
            raise AgentTurnProviderError(
                f"Agent provider HTTP {response.status_code}: {error}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise AgentTurnProviderError("Agent provider response must be an object.")
        return data


def validate_loopback_http_base_url(base_url: str) -> str:
    """Return one normalized literal-loopback HTTP origin or raise."""

    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("LOCAL_AGENT_ENDPOINT_INVALID") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("LOCAL_AGENT_ENDPOINT_MUST_BE_LITERAL_LOOPBACK_HTTP_ORIGIN")
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:{port}"


class _LoopbackHttpJsonSender:
    def __init__(self, *, timeout_seconds: float = 180.0) -> None:
        self.timeout_seconds = timeout_seconds

    def __call__(
        self,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        import httpx

        endpoint = urlsplit(url)
        if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "::1"}:
            raise AgentTurnProviderError("LOCAL_AGENT_REQUEST_LEFT_LOOPBACK")
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise AgentTurnProviderError(
                f"Local Agent request timed out after {self.timeout_seconds:g} seconds."
            ) from exc
        except httpx.RequestError as exc:
            raise AgentTurnProviderError(
                f"Local Agent connection failed: {type(exc).__name__}: {exc}"
            ) from exc
        if response.status_code != 200:
            try:
                error = response.json()
            except Exception:
                error = response.text
            raise AgentTurnProviderError(
                f"Local Agent HTTP {response.status_code}: {error}"
            )
        data = response.json()
        if not isinstance(data, dict):
            raise AgentTurnProviderError("Local Agent response must be an object.")
        return data


class OllamaChatAgentAdapter:
    """Ollama native Chat adapter restricted to a literal loopback origin."""

    provider = "ollama_chat_local"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        max_output_tokens: int,
        context_window: int | None = None,
        seed: int = 0,
        request_timeout_seconds: float = 180.0,
        request_sender: JsonRequestSender | None = None,
    ) -> None:
        if (
            not model.strip()
            or max_output_tokens <= 0
            or (
                context_window is not None
                and (
                    isinstance(context_window, bool)
                    or not isinstance(context_window, int)
                    or context_window <= max_output_tokens
                )
            )
            or isinstance(seed, bool)
            or not isinstance(seed, int)
            or request_timeout_seconds <= 0
        ):
            raise ValueError("Ollama Agent adapter configuration is invalid.")
        self.base_url = validate_loopback_http_base_url(base_url)
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.context_window = context_window
        self.seed = seed
        self.request_timeout_seconds = request_timeout_seconds
        self._send = request_sender or _LoopbackHttpJsonSender(
            timeout_seconds=request_timeout_seconds
        )

    def complete_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        messages = [_chat_message(item) for item in request.messages]
        required_single_tool = (
            request.tool_choice == "required"
            and len(request.tools) == 1
            and request.response_format is None
        )
        if request.tool_results:
            state = request.provider_state
            if not isinstance(state, dict) or not isinstance(state.get("tool_calls"), list):
                raise AgentTurnProviderError("OLLAMA_TOOL_RESULT_STATE_MISSING")
            exchange: list[dict[str, object]] = [
                {
                    "role": "assistant",
                    "content": state.get("content") or "",
                    "tool_calls": state["tool_calls"],
                }
            ]
            for result in request.tool_results:
                exchange.append(
                    {
                        "role": "tool",
                        "tool_name": result.name,
                        "content": _json_text(result.output),
                    }
                )
            insert_at = _insert_index(request.tool_result_insert_index, len(messages))
            messages[insert_at:insert_at] = exchange
        options: dict[str, object] = {
            "temperature": request.temperature,
            "num_predict": self.max_output_tokens,
            "seed": self.seed,
        }
        if self.context_window is not None:
            options["num_ctx"] = self.context_window
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": options,
        }
        if request.tools:
            payload["tools"] = [_chat_tool(tool) for tool in request.tools]
        if request.response_format is not None:
            payload["format"] = request.response_format.schema
        elif required_single_tool:
            payload["format"] = request.tools[0].parameters
        request_started = time.perf_counter()
        data = self._send(
            f"{self.base_url}/api/chat",
            payload,
            {"Content-Type": "application/json"},
        )
        client_elapsed_seconds = time.perf_counter() - request_started
        message = data.get("message")
        if not isinstance(message, dict):
            raise AgentTurnProviderError("OLLAMA_CHAT_RESPONSE_INVALID")
        raw_tool_calls = message.get("tool_calls") or []
        if not isinstance(raw_tool_calls, list):
            raise AgentTurnProviderError("OLLAMA_CHAT_TOOL_CALLS_INVALID")
        if not raw_tool_calls and required_single_tool:
            raw_tool_calls = [
                {
                    "function": {
                        "name": request.tools[0].name,
                        "arguments": _parse_arguments(message.get("content")),
                    }
                }
            ]
        tool_calls = tuple(_parse_ollama_tool_call(item) for item in raw_tool_calls)
        return AgentTurnResponse(
            provider=self.provider,
            model=str(data.get("model") or self.model),
            content=str(message.get("content") or "") or None,
            tool_calls=tool_calls,
            stop_reason=str(data.get("done_reason") or "") or None,
            usage=AgentUsage(
                input_tokens=_int_value(data.get("prompt_eval_count")),
                output_tokens=_int_value(data.get("eval_count")),
            ),
            provider_state={
                "content": message.get("content"),
                "tool_calls": raw_tool_calls,
            },
            provider_diagnostic=_ollama_provider_diagnostic(
                data=data,
                requested_model=self.model,
                max_output_tokens=self.max_output_tokens,
                context_window=self.context_window,
                temperature=request.temperature,
                seed=self.seed,
                client_elapsed_seconds=client_elapsed_seconds,
                tool_calls=tool_calls,
            ),
            raw_response=data,
        )


class QwenChatAgentAdapter:
    """Qwen OpenAI-compatible Chat Completions structured-turn adapter."""

    provider = "qwen_chat"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_completion_tokens: int,
        request_sender: JsonRequestSender | None = None,
    ) -> None:
        if not base_url or not model or max_completion_tokens <= 0:
            raise ValueError("Qwen Agent adapter configuration is invalid.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self._send = request_sender or _HttpJsonSender(api_key=api_key)

    def complete_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        messages = [_chat_message(item) for item in request.messages]
        state = request.provider_state
        if request.tool_results:
            if not isinstance(state, dict) or not isinstance(state.get("tool_calls"), list):
                raise AgentTurnProviderError("QWEN_TOOL_RESULT_STATE_MISSING")
            exchange: list[dict[str, object]] = [
                {
                    "role": "assistant",
                    "content": state.get("content"),
                    "tool_calls": state["tool_calls"],
                }
            ]
            for result in request.tool_results:
                exchange.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "name": result.name,
                        "content": _json_text(result.output),
                    }
                )
            insert_at = _insert_index(request.tool_result_insert_index, len(messages))
            messages[insert_at:insert_at] = exchange
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": request.temperature,
            "max_completion_tokens": self.max_completion_tokens,
            "enable_thinking": False,
            "parallel_tool_calls": request.parallel_tool_calls,
        }
        if request.tools:
            payload["tools"] = [_chat_tool(tool) for tool in request.tools]
            payload["tool_choice"] = request.tool_choice
        elif request.tool_choice == "none":
            payload["tool_choice"] = "none"
        if request.response_format is not None:
            # Qwen's documented JSON mode guarantees an object; deterministic
            # platform validation still enforces the exact local schema.
            payload["response_format"] = {"type": "json_object"}
        data = self._send(
            f"{self.base_url}/chat/completions",
            payload,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentTurnProviderError("QWEN_CHAT_RESPONSE_INVALID") from exc
        usage_data = data.get("usage") or {}
        usage = AgentUsage(
            input_tokens=_int_value(usage_data.get("prompt_tokens")),
            output_tokens=_int_value(usage_data.get("completion_tokens")),
            reasoning_tokens=_int_value(
                (usage_data.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens"
                )
            ),
            cached_input_tokens=_int_value(
                (usage_data.get("prompt_tokens_details") or {}).get("cached_tokens")
            ),
        )
        raw_tool_calls = message.get("tool_calls") or []
        parsed_tool_calls: list[AgentToolCall] = []
        try:
            for item in raw_tool_calls:
                parsed_tool_calls.append(_parse_chat_tool_call(item))
        except AgentTurnProviderError as exc:
            raise AgentTurnProviderError(
                str(exc),
                diagnostic=_qwen_chat_response_diagnostic(
                    data=data,
                    raw_tool_calls=raw_tool_calls,
                    tool_calls=tuple(parsed_tool_calls),
                    usage=usage,
                ),
            ) from exc
        tool_calls = tuple(parsed_tool_calls)
        provider_diagnostic = _qwen_chat_response_diagnostic(
            data=data,
            raw_tool_calls=raw_tool_calls,
            tool_calls=tool_calls,
            usage=usage,
        )
        return AgentTurnResponse(
            provider=self.provider,
            model=str(data.get("model") or self.model),
            content=message.get("content"),
            tool_calls=tool_calls,
            stop_reason=str(choice.get("finish_reason") or "") or None,
            request_id=str(data.get("id") or "") or None,
            usage=usage,
            provider_state={
                "content": message.get("content"),
                "tool_calls": raw_tool_calls,
            },
            provider_diagnostic=provider_diagnostic,
            raw_response=data,
        )


class OpenAIResponsesAgentAdapter:
    """OpenAI Responses API structured-turn adapter."""

    provider = "openai_responses"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str,
        max_output_tokens: int,
        request_sender: JsonRequestSender | None = None,
    ) -> None:
        if not base_url or not model or max_output_tokens <= 0:
            raise ValueError("OpenAI Responses Agent adapter configuration is invalid.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self._send = request_sender or _HttpJsonSender(api_key=api_key)

    def complete_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        input_items: list[dict[str, object]] = [
            {"role": item.role, "content": _json_text(item.content)}
            for item in request.messages
        ]
        if request.tool_results:
            state = request.provider_state
            if not isinstance(state, list):
                raise AgentTurnProviderError("OPENAI_TOOL_RESULT_STATE_MISSING")
            exchange = [dict(item) for item in state if isinstance(item, dict)]
            exchange.extend(
                {
                    "type": "function_call_output",
                    "call_id": result.call_id,
                    "output": _json_text(result.output),
                }
                for result in request.tool_results
            )
            insert_at = _insert_index(request.tool_result_insert_index, len(input_items))
            input_items[insert_at:insert_at] = exchange
        payload: dict[str, object] = {
            "model": self.model,
            "input": input_items,
            "max_output_tokens": self.max_output_tokens,
            "parallel_tool_calls": request.parallel_tool_calls,
        }
        if request.tools:
            payload["tools"] = [_responses_tool(tool) for tool in request.tools]
            payload["tool_choice"] = request.tool_choice
        elif request.tool_choice == "none":
            payload["tool_choice"] = "none"
        if request.response_format is not None:
            fmt = request.response_format
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": fmt.name,
                    "description": fmt.description,
                    "schema": fmt.schema,
                    "strict": fmt.strict,
                }
            }
        data = self._send(
            f"{self.base_url}/responses",
            payload,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        output = data.get("output")
        if not isinstance(output, list):
            raise AgentTurnProviderError("OPENAI_RESPONSES_OUTPUT_INVALID")
        tool_calls: list[AgentToolCall] = []
        text_parts: list[str] = []
        continuation: list[dict[str, object]] = []
        for item in output:
            if not isinstance(item, dict):
                raise AgentTurnProviderError("OPENAI_RESPONSES_ITEM_INVALID")
            item_type = item.get("type")
            if item_type == "function_call":
                tool_calls.append(
                    AgentToolCall(
                        call_id=str(item.get("call_id") or item.get("id") or ""),
                        name=str(item.get("name") or ""),
                        arguments=_parse_arguments(item.get("arguments")),
                    )
                )
                continuation.append(dict(item))
            elif item_type == "reasoning":
                continuation.append(dict(item))
            elif item_type == "message":
                content = item.get("content") or []
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "output_text":
                            text_parts.append(str(part.get("text") or ""))
        usage_data = data.get("usage") or {}
        output_details = usage_data.get("output_tokens_details") or {}
        input_details = usage_data.get("input_tokens_details") or {}
        usage = AgentUsage(
            input_tokens=_int_value(usage_data.get("input_tokens")),
            output_tokens=_int_value(usage_data.get("output_tokens")),
            reasoning_tokens=_int_value(output_details.get("reasoning_tokens")),
            cached_input_tokens=_int_value(input_details.get("cached_tokens")),
        )
        incomplete = data.get("incomplete_details") or {}
        stop_reason = incomplete.get("reason") or data.get("status")
        return AgentTurnResponse(
            provider=self.provider,
            model=str(data.get("model") or self.model),
            content="".join(text_parts) or None,
            tool_calls=tuple(tool_calls),
            stop_reason=str(stop_reason or "") or None,
            request_id=str(data.get("id") or "") or None,
            usage=usage,
            provider_state=continuation,
            raw_response=data,
        )


def _chat_message(message: AgentMessage) -> dict[str, object]:
    return {"role": message.role, "content": _json_text(message.content)}


def _chat_tool(tool: AgentToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _responses_tool(tool: AgentToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
        "strict": tool.strict,
    }


def _qwen_chat_response_diagnostic(
    *,
    data: dict[str, Any],
    raw_tool_calls: object,
    tool_calls: tuple[AgentToolCall, ...],
    usage: AgentUsage,
) -> dict[str, object]:
    raw_items = raw_tool_calls if isinstance(raw_tool_calls, list) else []
    tool_call_diagnostics: list[dict[str, object]] = []
    for index, raw in enumerate(raw_items):
        raw_call = raw if isinstance(raw, dict) else {}
        function = raw_call.get("function")
        raw_function = function if isinstance(function, dict) else {}
        provider_name = str(raw_function.get("name") or "")
        adapter_name = tool_calls[index].name if index < len(tool_calls) else ""
        arguments_audit = _provider_arguments_audit(raw_function.get("arguments"))
        tool_call_diagnostics.append(
            {
                "tool_call_id": str(raw_call.get("id") or ""),
                "provider_reported_tool_name": provider_name,
                "adapter_extracted_tool_name": adapter_name,
                "normalized_tool_name": adapter_name,
                "normalization_applied": False,
                **arguments_audit,
            }
        )
    choice = {}
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        choice = choices[0]
    return {
        "api_type": "openai_compatible_chat_completions",
        "streaming": False,
        "provider_request_id": str(data.get("id") or "") or None,
        "finish_reason": str(choice.get("finish_reason") or "") or None,
        "tool_calls": tool_call_diagnostics,
        "usage": usage.to_dict(),
    }


def _provider_arguments_audit(value: object) -> dict[str, object]:
    valid_json = True
    parsed: object = value
    if isinstance(value, str):
        serialized = value
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            valid_json = False
            parsed = value
    elif not isinstance(value, dict):
        valid_json = False
        try:
            serialized = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            serialized = repr(value)
    else:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    valid_object = valid_json and isinstance(parsed, dict)
    return {
        "arguments_valid_json": valid_json,
        "arguments_is_object": valid_object,
        "arguments_sha256": sha256(serialized.encode("utf-8")).hexdigest(),
    }


def _parse_chat_tool_call(item: object) -> AgentToolCall:
    if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
        raise AgentTurnProviderError("QWEN_CHAT_TOOL_CALL_INVALID")
    function = item["function"]
    call_id = str(item.get("id") or "")
    name = str(function.get("name") or "")
    if not call_id or not name:
        raise AgentTurnProviderError("QWEN_CHAT_TOOL_CALL_IDENTITY_INVALID")
    return AgentToolCall(
        call_id=call_id,
        name=name,
        arguments=_parse_arguments(function.get("arguments")),
    )


def _parse_ollama_tool_call(item: object) -> AgentToolCall:
    if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
        raise AgentTurnProviderError("OLLAMA_CHAT_TOOL_CALL_INVALID")
    function = item["function"]
    name = str(function.get("name") or "")
    arguments = _parse_arguments(function.get("arguments"))
    if not name:
        raise AgentTurnProviderError("OLLAMA_CHAT_TOOL_CALL_IDENTITY_INVALID")
    identity = json.dumps(
        {"name": name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return AgentToolCall(
        call_id="ollama-call-" + sha256(identity).hexdigest()[:16],
        name=name,
        arguments=arguments,
    )


def _ollama_provider_diagnostic(
    *,
    data: dict[str, Any],
    requested_model: str,
    max_output_tokens: int,
    context_window: int | None,
    temperature: float,
    seed: int,
    client_elapsed_seconds: float,
    tool_calls: tuple[AgentToolCall, ...],
) -> dict[str, object]:
    """Retain bounded native timing facts without treating them as evidence."""

    eval_count = _int_value(data.get("eval_count"))
    eval_duration_ns = _int_value(data.get("eval_duration"))
    tokens_per_second = (
        eval_count / (eval_duration_ns / 1_000_000_000)
        if eval_count > 0 and eval_duration_ns > 0
        else None
    )
    return {
        "api_type": "ollama_native_chat",
        "streaming": False,
        "thinking": False,
        "requested_model": requested_model,
        "returned_model": str(data.get("model") or ""),
        "configured_context_window": context_window,
        "configured_temperature": temperature,
        "configured_seed": seed,
        "configured_max_output_tokens": max_output_tokens,
        "client_total_duration_seconds": client_elapsed_seconds,
        "ollama_total_duration_ns": _int_value(data.get("total_duration")),
        "ollama_load_duration_ns": _int_value(data.get("load_duration")),
        "ollama_prompt_eval_duration_ns": _int_value(
            data.get("prompt_eval_duration")
        ),
        "ollama_eval_duration_ns": eval_duration_ns,
        "tokens_per_second": tokens_per_second,
        "first_token_duration_available": False,
        "finish_reason": str(data.get("done_reason") or "") or None,
        "tool_calls": [
            {"tool_call_id": call.call_id, "normalized_tool_name": call.name}
            for call in tool_calls
        ],
        "usage": AgentUsage(
            input_tokens=_int_value(data.get("prompt_eval_count")),
            output_tokens=eval_count,
        ).to_dict(),
    }


def _parse_arguments(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise AgentTurnProviderError("AGENT_TOOL_ARGUMENTS_INVALID")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AgentTurnProviderError("AGENT_TOOL_ARGUMENTS_INVALID_JSON") from exc
    if not isinstance(parsed, dict):
        raise AgentTurnProviderError("AGENT_TOOL_ARGUMENTS_MUST_BE_OBJECT")
    return parsed


def _json_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _int_value(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _insert_index(value: int | None, length: int) -> int:
    if value is None:
        return length
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= length:
        raise AgentTurnProviderError("AGENT_TOOL_RESULT_INSERT_INDEX_INVALID")
    return value
