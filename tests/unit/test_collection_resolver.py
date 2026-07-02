"""Tests for controlled-agent collection resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.settings import Settings
from src.mod_agent.knowledge import CollectionResolutionError, CollectionResolver


def _settings(collection_name: str) -> Settings:
    return Settings.from_dict(
        {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": 0.0,
                "max_tokens": 4096,
            },
            "embedding": {
                "provider": "openai",
                "model": "text-embedding-ada-002",
                "dimensions": 1536,
            },
            "vector_store": {
                "provider": "chroma",
                "persist_directory": "./data/db/chroma",
                "collection_name": collection_name,
            },
            "retrieval": {
                "dense_top_k": 20,
                "sparse_top_k": 20,
                "fusion_top_k": 10,
                "rrf_k": 60,
            },
            "rerank": {
                "enabled": False,
                "provider": "none",
                "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "top_k": 5,
            },
            "evaluation": {
                "enabled": False,
                "provider": "custom",
                "metrics": ["hit_rate"],
            },
            "observability": {
                "log_level": "INFO",
                "trace_enabled": True,
                "trace_file": "./logs/traces.jsonl",
                "structured_logging": True,
            },
        }
    )


def test_collection_resolver_uses_configured_vector_store_collection() -> None:
    resolver = CollectionResolver(settings=_settings("knowledge_hub"))

    resolution = resolver.resolve()

    assert resolution.collection_id == "knowledge_hub"
    assert resolution.source == "settings"


def test_collection_resolver_explicit_collection_overrides_configured_default() -> None:
    resolver = CollectionResolver(settings=_settings("knowledge_hub"))

    resolution = resolver.resolve("request_scope")

    assert resolution.collection_id == "request_scope"
    assert resolution.source == "explicit"


def test_collection_resolver_rejects_empty_explicit_collection() -> None:
    resolver = CollectionResolver(settings=_settings("knowledge_hub"))

    with pytest.raises(CollectionResolutionError, match="Explicit collection id"):
        resolver.resolve("  ")


def test_collection_resolver_reports_missing_config(tmp_path: Path) -> None:
    resolver = CollectionResolver(settings_path=tmp_path / "missing.yaml")

    with pytest.raises(CollectionResolutionError, match="Settings file not found"):
        resolver.resolve()
