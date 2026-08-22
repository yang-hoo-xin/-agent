"""Ollama LLM implementation for local model inference.

This module provides the Ollama LLM implementation that works with
locally running Ollama instances. Ollama enables running LLMs like
Llama, Mistral, CodeLlama, etc. on local hardware.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from typing import Any, Dict, List, Optional

from src.libs.llm.base_llm import BaseLLM, ChatResponse, Message


def ollama_provider_body_utf8_policy_projection(
    payload: Mapping[str, Any],
) -> bytes:
    """Return the stable UTF-8 policy projection used for context admission."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_ollama_context_admission(
    *,
    payload: Mapping[str, Any],
    configured_num_ctx: int | None,
    num_predict: int,
) -> dict[str, Any]:
    """Project configured or explicitly unavailable pre-call admission."""

    if (
        isinstance(num_predict, bool)
        or not isinstance(num_predict, int)
        or num_predict <= 0
    ):
        raise ValueError("Ollama context admission budgets must be positive integers.")
    provider_body_utf8_bytes = len(
        ollama_provider_body_utf8_policy_projection(payload)
    )
    if configured_num_ctx is None:
        return {
            "mode": "context_admission_unavailable_not_configured_v1",
            "exact_prompt_tokens_available_pre_call": False,
            "provider_body_utf8_bytes": provider_body_utf8_bytes,
            "configured_num_ctx": None,
            "num_predict": num_predict,
            "conservative_required_context": None,
            "admitted": None,
        }
    if (
        isinstance(configured_num_ctx, bool)
        or not isinstance(configured_num_ctx, int)
        or configured_num_ctx <= 0
    ):
        raise ValueError("Ollama context admission budgets must be positive integers.")
    conservative_required_context = provider_body_utf8_bytes + num_predict
    return {
        "mode": "provider_body_utf8_proxy_plus_output_budget_v1",
        "exact_prompt_tokens_available_pre_call": False,
        "provider_body_utf8_bytes": provider_body_utf8_bytes,
        "configured_num_ctx": configured_num_ctx,
        "num_predict": num_predict,
        "conservative_required_context": conservative_required_context,
        "admitted": conservative_required_context <= configured_num_ctx,
    }


def _context_request_identity_sha256(payload: Mapping[str, Any]) -> str:
    """Bind a structured request while allowing only num_ctx to change."""

    normalized = dict(payload)
    options = dict(normalized.get("options") or {})
    options.pop("num_ctx", None)
    normalized["options"] = options
    return hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class OllamaLLMError(RuntimeError):
    """Raised when Ollama API call fails.
    
    This exception provides clear error messages without exposing
    sensitive configuration details like internal URLs or credentials.
    """

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


class OllamaLLM(BaseLLM):
    """Ollama LLM provider implementation for local inference.
    
    This class implements the BaseLLM interface for Ollama's chat API,
    enabling local LLM inference without cloud dependencies.
    
    Attributes:
        base_url: The base URL for the Ollama server (default: http://localhost:11434).
        model: The model identifier to use (e.g., 'llama3', 'mistral').
        default_temperature: Default temperature for generation.
        default_max_tokens: Default max tokens for generation (num_predict in Ollama).
        context_window: Explicit Ollama num_ctx request value when configured.
        timeout: Request timeout in seconds.
    
    Example:
        >>> from src.core.settings import load_settings
        >>> settings = load_settings('config/settings.yaml')
        >>> llm = OllamaLLM(settings)
        >>> response = llm.chat([Message(role='user', content='Hello')])
    """
    
    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_TIMEOUT = 120.0  # Longer timeout for local inference
    
    def __init__(
        self,
        settings: Any,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        context_window: int | None = None,
        observed_prompt_tokens: int | None = None,
        observed_prompt_identity_sha256: str | None = None,
        observed_prompt_token_source: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Ollama LLM provider.
        
        Args:
            settings: Application settings containing LLM configuration.
            base_url: Optional base URL override (falls back to env var OLLAMA_BASE_URL).
            timeout: Optional timeout override for requests.
            context_window: Optional explicit Ollama num_ctx request value.
            **kwargs: Additional configuration overrides.
        
        Raises:
            ValueError: If required configuration is missing.
        """
        self.model = settings.llm.model
        self.default_temperature = settings.llm.temperature
        self.default_max_tokens = settings.llm.max_tokens
        if (
            context_window is not None
            and (
                isinstance(context_window, bool)
                or not isinstance(context_window, int)
                or context_window <= 0
            )
        ):
            raise ValueError("Ollama context_window must be a positive integer.")
        self.context_window = context_window
        prompt_observation = (
            observed_prompt_tokens,
            observed_prompt_identity_sha256,
            observed_prompt_token_source,
        )
        if any(value is not None for value in prompt_observation):
            if not all(value is not None for value in prompt_observation):
                raise ValueError(
                    "Ollama observed prompt admission requires tokens, "
                    "identity SHA256, and source together."
                )
            if (
                isinstance(observed_prompt_tokens, bool)
                or not isinstance(observed_prompt_tokens, int)
                or observed_prompt_tokens <= 0
            ):
                raise ValueError(
                    "Ollama observed_prompt_tokens must be a positive integer."
                )
            if (
                not isinstance(observed_prompt_identity_sha256, str)
                or len(observed_prompt_identity_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in observed_prompt_identity_sha256
                )
            ):
                raise ValueError(
                    "Ollama observed_prompt_identity_sha256 must be lowercase "
                    "SHA256 hex."
                )
            if (
                not isinstance(observed_prompt_token_source, str)
                or not observed_prompt_token_source.strip()
            ):
                raise ValueError(
                    "Ollama observed_prompt_token_source must be non-empty."
                )
        self.observed_prompt_tokens = observed_prompt_tokens
        self.observed_prompt_identity_sha256 = observed_prompt_identity_sha256
        self.observed_prompt_token_source = observed_prompt_token_source
        
        # Base URL: explicit > env var > default
        self.base_url = (
            base_url 
            or os.environ.get("OLLAMA_BASE_URL") 
            or self.DEFAULT_BASE_URL
        )
        
        # Timeout: explicit > default
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        
        # Store any additional kwargs for future use
        self._extra_config = kwargs
    
    def chat(
        self,
        messages: List[Message],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Generate a chat completion using Ollama API.
        
        Args:
            messages: List of conversation messages.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Override parameters (temperature, max_tokens, etc.).
        
        Returns:
            ChatResponse with generated content and metadata.
        
        Raises:
            ValueError: If messages are invalid.
            OllamaLLMError: If API call fails.
        """
        # Validate input
        self.validate_messages(messages)
        
        # Prepare request parameters
        temperature = kwargs.get("temperature", self.default_temperature)
        max_tokens = kwargs.get("max_tokens", self.default_max_tokens)
        model = kwargs.get("model", self.model)
        response_format = kwargs.get("response_format")
        provider_request_recorder = kwargs.get("provider_request_recorder")
        if response_format is not None and not isinstance(response_format, Mapping):
            raise ValueError("Ollama response_format must be a JSON Schema object.")
        if provider_request_recorder is not None and not callable(provider_request_recorder):
            raise ValueError("Ollama provider_request_recorder must be callable.")
        
        # Convert messages to Ollama API format
        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        
        # Make API call
        try:
            response_data = self._call_api(
                messages=api_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                context_window=self.context_window,
                response_format=(
                    dict(response_format) if response_format is not None else None
                ),
                provider_request_recorder=provider_request_recorder,
            )
            if response_format is not None:
                content, usage = self._admit_chat_response(
                    response_data,
                    expected_model=str(model),
                )
            else:
                if "message" in response_data:
                    content = response_data["message"]["content"]
                elif "response" in response_data:
                    content = response_data["response"]
                else:
                    raise OllamaLLMError(
                        "[Ollama] Unexpected response format: missing "
                        "'message' or 'response' key"
                    )
                usage = self._usage_from_response(response_data)
            
            return ChatResponse(
                content=content,
                model=response_data.get("model", model),
                usage=usage,
                raw_response=response_data,
            )
        except Exception as e:
            if isinstance(e, OllamaLLMError):
                raise
            raise OllamaLLMError(
                f"[Ollama] API call failed: {type(e).__name__}: {e}",
                diagnostics={
                    "failure_boundary": "provider_request_gate",
                    "failure_classification": "durable_provider_request_failure",
                },
            ) from e
    
    def _call_api(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        context_window: int | None = None,
        response_format: Dict[str, Any] | None = None,
        provider_request_recorder: Callable[[dict[str, Any]], None] | None = None,
    ) -> Dict[str, Any]:
        """Make the actual API call to Ollama.
        
        This method is separated to allow easy mocking in tests.
        
        Args:
            messages: Messages in API format.
            model: Model identifier.
            temperature: Generation temperature.
            max_tokens: Maximum tokens to generate (num_predict in Ollama).
            context_window: Explicit Ollama num_ctx request value when configured.
        
        Returns:
            Raw API response as dictionary.
        
        Raises:
            OllamaLLMError: If the API call fails.
        """
        import httpx
        
        url = f"{self.base_url.rstrip('/')}/api/chat"
        headers = {
            "Content-Type": "application/json",
        }
        
        # Ollama uses 'num_predict' instead of 'max_tokens'
        # and 'options' object for model parameters
        options = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        if context_window is not None:
            options["num_ctx"] = context_window
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,  # Disable streaming for synchronous response
            "options": options,
        }
        frozen_request_bytes: bytes | None = None
        if response_format is not None:
            payload["think"] = False
            payload["format"] = response_format
            frozen_request_bytes = ollama_provider_body_utf8_policy_projection(
                payload
            )
            if provider_request_recorder is None:
                raise OllamaLLMError(
                    "[Ollama] Structured patch generation requires a durable "
                    "provider request recorder.",
                    diagnostics={
                        "failure_boundary": "provider_request_gate",
                        "failure_classification": "durable_provider_request_missing",
                    },
                )
            context_admission: dict[str, Any] | None = None
            if context_window is not None:
                if (
                    isinstance(max_tokens, bool)
                    or not isinstance(max_tokens, int)
                    or max_tokens <= 0
                ):
                    raise OllamaLLMError(
                        "[Ollama] Structured request output budget must be a "
                        "positive integer.",
                        diagnostics={
                            "failure_boundary": "provider_request_gate",
                            "failure_classification": (
                                "provider_request_output_budget_invalid"
                            ),
                        },
                    )
                provider_body_utf8_bytes = len(frozen_request_bytes)
                if self.observed_prompt_tokens is None:
                    context_admission = (
                        build_ollama_context_admission(
                            payload=payload,
                            configured_num_ctx=context_window,
                            num_predict=max_tokens,
                        )
                    )
                else:
                    observed_identity = _context_request_identity_sha256(payload)
                    if observed_identity != self.observed_prompt_identity_sha256:
                        raise OllamaLLMError(
                            "[Ollama] Structured request does not match the "
                            "bound prompt-token observation.",
                            diagnostics={
                                "failure_boundary": "provider_request_gate",
                                "failure_classification": (
                                    "provider_request_prompt_identity_mismatch"
                                ),
                                "expected_prompt_identity_sha256": (
                                    self.observed_prompt_identity_sha256
                                ),
                                "observed_prompt_identity_sha256": (
                                    observed_identity
                                ),
                            },
                        )
                    observed_required_context = (
                        self.observed_prompt_tokens + max_tokens
                    )
                    context_admission = {
                        "mode": (
                            "bound_observed_prompt_tokens_plus_output_budget_v1"
                        ),
                        "exact_prompt_tokens_available_pre_call": True,
                        "provider_body_utf8_bytes": provider_body_utf8_bytes,
                        "observed_prompt_tokens": self.observed_prompt_tokens,
                        "prompt_identity_sha256": observed_identity,
                        "prompt_token_source": self.observed_prompt_token_source,
                        "configured_num_ctx": context_window,
                        "num_predict": max_tokens,
                        "observed_required_context": observed_required_context,
                        "admitted": observed_required_context <= context_window,
                    }
                if context_admission["admitted"] is not True:
                    raise OllamaLLMError(
                        "[Ollama] Structured request exceeds the configured "
                        "pre-call context budget.",
                        diagnostics={
                            "failure_boundary": "provider_request_gate",
                            "failure_classification": (
                                "provider_request_context_budget_exceeded"
                            ),
                            "context_admission": context_admission,
                        },
                    )
            provider_request_recorder(
                {
                    "method": "POST",
                    "destination": url,
                    "content_type": "application/json",
                    "body_utf8": frozen_request_bytes.decode("utf-8"),
                    "body_sha256": hashlib.sha256(frozen_request_bytes).hexdigest(),
                    "body_size_bytes": len(frozen_request_bytes),
                    "timeout_seconds": self.timeout,
                    "trust_environment": False,
                    "follow_redirects": False,
                    "context_admission": context_admission,
                }
            )
        
        try:
            with httpx.Client(
                timeout=self.timeout,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                if frozen_request_bytes is None:
                    response = client.post(url, json=payload, headers=headers)
                else:
                    response = client.post(
                        url,
                        content=frozen_request_bytes,
                        headers=headers,
                    )
                
                if response.status_code != 200:
                    error_detail = self._parse_error_response(response)
                    raise OllamaLLMError(
                        f"[Ollama] API error (HTTP {response.status_code}): {error_detail}",
                        diagnostics={
                            "failure_boundary": "provider_response_admission",
                            "failure_classification": "provider_http_error",
                            "http_status": response.status_code,
                        },
                    )
                try:
                    response_data = response.json()
                except (TypeError, ValueError) as exc:
                    raise OllamaLLMError(
                        "[Ollama] Response envelope is not valid JSON.",
                        diagnostics={
                            "failure_boundary": "provider_response_admission",
                            "failure_classification": (
                                "provider_envelope_json_decoding_failure"
                            ),
                            "http_status": response.status_code,
                        },
                    ) from exc
                if not isinstance(response_data, dict):
                    raise OllamaLLMError(
                        "[Ollama] Response envelope root must be an object.",
                        diagnostics={
                            "failure_boundary": "provider_response_admission",
                            "failure_classification": "provider_envelope_shape_failure",
                            "http_status": response.status_code,
                        },
                    )
                return response_data
        except httpx.TimeoutException as e:
            raise OllamaLLMError(
                f"[Ollama] Request timed out after {self.timeout} seconds. "
                "Consider increasing timeout for larger models or longer responses.",
                diagnostics={
                    "failure_boundary": "provider_response_admission",
                    "failure_classification": "provider_timeout",
                },
            ) from e
        except httpx.ConnectError as e:
            raise OllamaLLMError(
                "[Ollama] Connection failed. Ensure Ollama is running locally. "
                "Start it with 'ollama serve' command.",
                diagnostics={
                    "failure_boundary": "provider_response_admission",
                    "failure_classification": "provider_connection_failure",
                },
            ) from e
        except httpx.RequestError as e:
            raise OllamaLLMError(
                f"[Ollama] Request failed: {type(e).__name__}",
                diagnostics={
                    "failure_boundary": "provider_response_admission",
                    "failure_classification": "provider_request_failure",
                },
            ) from e

    def _admit_chat_response(
        self,
        response_data: Dict[str, Any],
        *,
        expected_model: str,
    ) -> tuple[str, dict[str, int] | None]:
        """Apply the bounded non-streaming local response profile."""

        response_model = response_data.get("model")
        done = response_data.get("done")
        done_reason = response_data.get("done_reason")
        message = response_data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        diagnostics = {
            "failure_boundary": "provider_response_admission",
            "response_model": response_model,
            "done": done,
            "done_reason": done_reason,
            "message_content": content if isinstance(content, str) else None,
        }
        if response_model != expected_model:
            raise OllamaLLMError(
                "[Ollama] Response model does not match the admitted exact model.",
                diagnostics={
                    **diagnostics,
                    "failure_classification": "response_model_identity_mismatch",
                },
            )
        if done is not True:
            raise OllamaLLMError(
                "[Ollama] Response is not a complete non-streaming completion.",
                diagnostics={
                    **diagnostics,
                    "failure_classification": "provider_response_incomplete",
                },
            )
        if done_reason != "stop":
            raise OllamaLLMError(
                "[Ollama] Response did not finish with the admitted stop reason.",
                diagnostics={
                    **diagnostics,
                    "failure_classification": "provider_response_stop_reason_rejected",
                },
            )
        if not isinstance(message, dict):
            raise OllamaLLMError(
                "[Ollama] Response message must be an object.",
                diagnostics={
                    **diagnostics,
                    "failure_classification": "provider_message_shape_failure",
                },
            )
        if not isinstance(content, str) or not content.strip():
            raise OllamaLLMError(
                "[Ollama] Response message.content must be non-empty.",
                diagnostics={
                    **diagnostics,
                    "failure_classification": "provider_message_content_empty",
                },
            )
        if message.get("thinking") not in (None, ""):
            raise OllamaLLMError(
                "[Ollama] Thinking content is not admitted for patch generation.",
                diagnostics={
                    **diagnostics,
                    "failure_classification": "provider_thinking_not_admitted",
                },
            )
        if message.get("tool_calls") not in (None, []):
            raise OllamaLLMError(
                "[Ollama] Tool calls are not admitted for patch generation.",
                diagnostics={
                    **diagnostics,
                    "failure_classification": "provider_tool_calls_not_admitted",
                },
            )
        return content, self._usage_from_response(response_data)

    @staticmethod
    def _usage_from_response(
        response_data: Mapping[str, Any],
    ) -> dict[str, int] | None:
        if "eval_count" not in response_data and "prompt_eval_count" not in response_data:
            return None
        prompt_tokens = response_data.get("prompt_eval_count", 0)
        completion_tokens = response_data.get("eval_count", 0)
        if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
            return None
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    
    def _parse_error_response(self, response: Any) -> str:
        """Parse error details from API response.
        
        Args:
            response: The HTTP response object.
        
        Returns:
            Human-readable error message without exposing sensitive details.
        """
        try:
            error_data = response.json()
            if "error" in error_data:
                return str(error_data["error"])
            return response.text[:200] if response.text else "Unknown error"
        except Exception:
            return response.text[:200] if response.text else "Unknown error"
