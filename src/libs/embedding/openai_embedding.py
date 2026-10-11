"""OpenAI Embedding implementation.

This module provides the OpenAI Embedding implementation that works with
the standard OpenAI Embeddings API.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, List, Optional
from uuid import uuid4

from src.libs.embedding.base_embedding import BaseEmbedding


class OpenAIEmbeddingError(RuntimeError):
    """Raised when OpenAI Embeddings API call fails."""


class OpenAIEmbedding(BaseEmbedding):
    """OpenAI Embedding provider implementation.
    
    This class implements the BaseEmbedding interface for OpenAI's Embeddings API.
    It supports text-embedding-3-small, text-embedding-3-large, and older models
    like text-embedding-ada-002.
    
    Attributes:
        api_key: The API key for authentication.
        model: The model identifier to use.
        dimensions: Optional dimension reduction (only for text-embedding-3-*).
        base_url: The base URL for the API (default: OpenAI's endpoint).
    
    Example:
        >>> from src.core.settings import load_settings
        >>> settings = load_settings('config/settings.yaml')
        >>> embedding = OpenAIEmbedding(settings)
        >>> vectors = embedding.embed(["hello world", "test"])
    """
    
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    def __init__(
        self,
        settings: Any,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the OpenAI Embedding provider.
        
        Args:
            settings: Application settings containing Embedding configuration.
            api_key: Optional API key override (falls back to settings.embedding.api_key or env var).
            base_url: Optional base URL override.
            **kwargs: Additional configuration overrides.
        
        Raises:
            ValueError: If API key is not provided and not found in environment.
        
        Note:
            When azure_endpoint is present in settings, the provider automatically
            constructs the Azure-compatible OpenAI URL and uses api-key auth.
        """
        self.model = settings.embedding.model
        
        # Extract optional dimensions setting
        self.dimensions = getattr(settings.embedding, 'dimensions', None)
        
        # API key: explicit > settings > env var
        self.api_key = (
            api_key
            or getattr(settings.embedding, 'api_key', None)
            or os.environ.get("OPENAI_API_KEY")
        )
        if not self.api_key:
            raise ValueError(
                "OpenAI API key not provided. Set in settings.yaml (embedding.api_key), "
                "OPENAI_API_KEY environment variable, or pass api_key parameter."
            )
        
        # Azure-compatible mode detection
        azure_endpoint = getattr(settings.embedding, 'azure_endpoint', None)
        self.api_version = getattr(settings.embedding, 'api_version', None)
        self._use_azure_auth = False
        
        if base_url:
            self.base_url = base_url
        elif azure_endpoint:
            # Azure-compatible mode: construct deployment-based URL
            deployment = getattr(settings.embedding, 'deployment_name', None) or self.model
            self.base_url = f"{azure_endpoint.rstrip('/')}/openai/deployments/{deployment}"
            self._use_azure_auth = True
            if not self.api_version:
                self.api_version = "2024-02-15-preview"
        else:
            settings_base_url = getattr(settings.embedding, 'base_url', None)
            self.base_url = settings_base_url if settings_base_url else self.DEFAULT_BASE_URL
        
        # Store any additional kwargs for future use
        self._extra_config = kwargs
    
    def embed(
        self,
        texts: List[str],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[List[float]]:
        """Return vectors and, when traced, retain native usage for this call.

        为什么要有它：检索失败仍可能已经消耗Token；缺失usage保持未知，不借用前一题或估算成零。
        """
        started = time.perf_counter()
        observation = {
            "invocation_id": str(uuid4()), "configured_model": self.model,
            "request": None, "response_model": None, "usage": None,
            "sdk_call_invoked": False, "response_received": False,
            "http_attempt_count": None, "status": "started", "error_type": None,
            "usage_scope": "native SDK response; internal HTTP retry usage unavailable",
        }
        try:
            vectors = self._embed_observed(texts, observation, **kwargs)
            observation.update(status="observed", output_count=len(vectors))
            return vectors
        except Exception as error:
            observation.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            observation["elapsed_ms"] = (time.perf_counter() - started) * 1000.0
            if trace is not None:
                trace.record_stage("embedding", observation, elapsed_ms=observation["elapsed_ms"])

    def _embed_observed(self, texts, observation, **kwargs):
        """Generate embeddings for a batch of texts using OpenAI API.
        
        Args:
            texts: List of text strings to embed. Must not be empty.
            trace: Optional TraceContext for observability (reserved for Stage F).
            **kwargs: Override parameters (dimensions, etc.).
        
        Returns:
            List of embedding vectors, where each vector is a list of floats.
            The length of the outer list matches len(texts).
        
        Raises:
            ValueError: If texts list is empty or contains invalid entries.
            OpenAIEmbeddingError: If API call fails.
        """
        # Validate input
        self.validate_texts(texts)
        observation["request"] = {"model": self.model, "input_count": len(texts),
            "input_sha256": hashlib.sha256(json.dumps(texts, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()}
        
        # Import OpenAI client (lazy import to avoid dependency at module level)
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "OpenAI Python package not installed. "
                "Install with: pip install openai"
            ) from e
        
        # Initialize OpenAI client
        client_kwargs = {
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
        # Azure-compatible mode: add api-version query param and api-key header
        if self._use_azure_auth and self.api_version:
            client_kwargs["default_query"] = {"api-version": self.api_version}
            client_kwargs["default_headers"] = {"api-key": self.api_key}
        
        client = OpenAI(**client_kwargs)
        
        # Prepare API call parameters
        api_params = {
            "input": texts,
            "model": self.model,
        }
        
        # Add dimensions if specified (only for text-embedding-3-* models)
        # text-embedding-ada-002 does NOT support the dimensions parameter
        dimensions = kwargs.get("dimensions", self.dimensions)
        if dimensions is not None and self.model.startswith("text-embedding-3"):
            api_params["dimensions"] = dimensions
        
        # Call OpenAI API
        try:
            observation["sdk_call_invoked"] = True
            response = client.embeddings.create(**api_params)
        except Exception as e:
            raise OpenAIEmbeddingError(
                f"OpenAI Embeddings API call failed: {e}"
            ) from e
        observation["response_received"] = True
        returned_model = getattr(response, "model", None)
        observation["response_model"] = returned_model if isinstance(returned_model, str) else None
        usage = getattr(response, "usage", None)
        native_usage = {key: value for key in ("prompt_tokens", "total_tokens")
            if type(value := getattr(usage, key, None)) is int and value >= 0}
        observation["usage"] = native_usage or None
        
        # Extract embeddings from response
        # Response format: response.data is a list of objects with .embedding attribute
        try:
            embeddings = [item.embedding for item in response.data]
        except (AttributeError, KeyError) as e:
            raise OpenAIEmbeddingError(
                f"Failed to parse OpenAI Embeddings API response: {e}"
            ) from e
        
        # Verify output matches input length
        if len(embeddings) != len(texts):
            raise OpenAIEmbeddingError(
                f"Output length mismatch: expected {len(texts)}, got {len(embeddings)}"
            )
        
        return embeddings
    
    def get_dimension(self) -> Optional[int]:
        """Get the embedding dimension for the configured model.
        
        Returns:
            The embedding dimension, or None if not deterministic.
        
        Note:
            For text-embedding-3-* models with custom dimensions, returns
            the configured dimension. For other models, returns their default.
        """
        # If dimensions explicitly configured, return it
        if self.dimensions is not None:
            return self.dimensions
        
        # Model-specific defaults
        model_dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        
        return model_dimensions.get(self.model)
