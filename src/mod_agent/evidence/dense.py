"""Dense retrieval provider contracts for controlled evidence retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.mod_agent.knowledge import ChunkRecord


@dataclass(frozen=True)
class DenseRetrievalHit:
    """One dense retrieval hit bound to a persisted chunk id."""

    chunk_id: str
    score: float


@dataclass(frozen=True)
class DenseRetrievalReport:
    """Provider result plus cost/accounting metadata."""

    provider: str
    enabled: bool
    hits: tuple[DenseRetrievalHit, ...] = ()
    api_calls: int = 0
    embedded_items: int = 0
    batch_count: int = 0
    cache_enabled: bool = True
    disabled_reason: str = ""
    trace_events: tuple[dict[str, Any], ...] = ()

    def usage_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "api_calls": self.api_calls,
            "embedded_items": self.embedded_items,
            "batch_count": self.batch_count,
            "cache_enabled": self.cache_enabled,
            "hit_count": len(self.hits),
            "disabled_reason": self.disabled_reason,
        }


class DenseRetrievalProvider(Protocol):
    """Interface for disabled-by-default dense retrieval providers."""

    provider_name: str

    def retrieve(
        self,
        *,
        query: str,
        chunks: tuple[ChunkRecord, ...],
        top_k: int,
    ) -> DenseRetrievalReport:
        """Return dense chunk hits without mutating the knowledge base."""


class DisabledDenseRetrievalProvider:
    """Provider used when dense retrieval is not explicitly enabled."""

    provider_name = "disabled"

    def retrieve(
        self,
        *,
        query: str,
        chunks: tuple[ChunkRecord, ...],
        top_k: int,
    ) -> DenseRetrievalReport:
        return DenseRetrievalReport(
            provider=self.provider_name,
            enabled=False,
            disabled_reason=(
                "Dense retrieval is disabled until an explicit provider and budget "
                "policy are configured."
            ),
        )


class FakeDenseRetrievalProvider:
    """Deterministic dense provider for unit tests and contract verification."""

    provider_name = "fake"

    def __init__(
        self,
        scores_by_chunk_id: dict[str, float],
        *,
        api_calls: int = 0,
        cache_enabled: bool = True,
    ) -> None:
        self.scores_by_chunk_id = dict(scores_by_chunk_id)
        self.api_calls = api_calls
        self.cache_enabled = cache_enabled

    def retrieve(
        self,
        *,
        query: str,
        chunks: tuple[ChunkRecord, ...],
        top_k: int,
    ) -> DenseRetrievalReport:
        hits = sorted(
            (
                DenseRetrievalHit(
                    chunk_id=chunk.chunk_id,
                    score=float(self.scores_by_chunk_id[chunk.chunk_id]),
                )
                for chunk in chunks
                if chunk.chunk_id in self.scores_by_chunk_id
            ),
            key=lambda hit: (-hit.score, hit.chunk_id),
        )[: max(0, top_k)]
        return DenseRetrievalReport(
            provider=self.provider_name,
            enabled=True,
            hits=tuple(hits),
            api_calls=self.api_calls,
            embedded_items=len(chunks),
            batch_count=1 if chunks else 0,
            cache_enabled=self.cache_enabled,
            trace_events=(
                {
                    "event": "retrieval.dense_started",
                    "provider": self.provider_name,
                    "chunk_count": len(chunks),
                },
                {
                    "event": "retrieval.dense_finished",
                    "provider": self.provider_name,
                    "hit_count": len(hits),
                },
            ),
        )
