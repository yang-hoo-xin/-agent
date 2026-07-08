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


class VectorStoreDenseRetrievalProvider:
    """Dense retrieval backed by the configured embedding and vector store."""

    provider_name = "vector_store"

    def __init__(
        self,
        *,
        embedding_client: Any,
        vector_store: Any,
        provider_name: str | None = None,
        filters: dict[str, Any] | None = None,
        overfetch_multiplier: int = 3,
    ) -> None:
        if embedding_client is None:
            raise ValueError("embedding_client is required")
        if vector_store is None:
            raise ValueError("vector_store is required")
        if overfetch_multiplier <= 0:
            raise ValueError("overfetch_multiplier must be positive")
        self.embedding_client = embedding_client
        self.vector_store = vector_store
        if provider_name is not None:
            self.provider_name = provider_name
        self.filters = dict(filters or {})
        self.overfetch_multiplier = overfetch_multiplier

    def retrieve(
        self,
        *,
        query: str,
        chunks: tuple[ChunkRecord, ...],
        top_k: int,
    ) -> DenseRetrievalReport:
        trace_events: list[dict[str, Any]] = [
            {
                "event": "retrieval.dense_started",
                "provider": self.provider_name,
                "chunk_count": len(chunks),
            }
        ]
        if top_k <= 0:
            return DenseRetrievalReport(
                provider=self.provider_name,
                enabled=True,
                hits=(),
                disabled_reason="Dense retrieval top_k must be positive.",
                trace_events=tuple(trace_events),
            )
        if not isinstance(query, str) or not query.strip():
            return DenseRetrievalReport(
                provider=self.provider_name,
                enabled=True,
                hits=(),
                disabled_reason="Dense retrieval query must be a non-empty string.",
                trace_events=tuple(trace_events),
            )

        allowed_chunk_ids = {chunk.chunk_id for chunk in chunks}
        try:
            vectors = self.embedding_client.embed([query])
            query_vector = vectors[0]
            trace_events.append(
                {
                    "event": "retrieval.dense_embedded",
                    "provider": self.provider_name,
                    "embedded_items": 1,
                }
            )
            raw_results = self.vector_store.query(
                vector=query_vector,
                top_k=max(top_k, top_k * self.overfetch_multiplier),
                filters=self.filters or None,
            )
            trace_events.append(
                {
                    "event": "retrieval.dense_vector_queried",
                    "provider": self.provider_name,
                    "raw_hit_count": len(raw_results),
                }
            )
        except Exception as exc:
            trace_events.append(
                {
                    "event": "retrieval.dense_failed",
                    "provider": self.provider_name,
                    "error_type": type(exc).__name__,
                }
            )
            return DenseRetrievalReport(
                provider=self.provider_name,
                enabled=True,
                hits=(),
                api_calls=1,
                embedded_items=1,
                batch_count=1,
                disabled_reason=f"Dense retrieval provider failed: {exc}",
                trace_events=tuple(trace_events),
            )

        hits: list[DenseRetrievalHit] = []
        seen: set[str] = set()
        for raw in raw_results:
            chunk_id = str(raw.get("id", ""))
            if not chunk_id or chunk_id in seen:
                continue
            if allowed_chunk_ids and chunk_id not in allowed_chunk_ids:
                continue
            try:
                score = float(raw.get("score", 0.0))
            except (TypeError, ValueError):
                continue
            hits.append(DenseRetrievalHit(chunk_id=chunk_id, score=score))
            seen.add(chunk_id)
            if len(hits) >= top_k:
                break

        hits = sorted(hits, key=lambda hit: (-hit.score, hit.chunk_id))[:top_k]

        trace_events.append(
            {
                "event": "retrieval.dense_finished",
                "provider": self.provider_name,
                "hit_count": len(hits),
            }
        )
        return DenseRetrievalReport(
            provider=self.provider_name,
            enabled=True,
            hits=tuple(hits),
            api_calls=1,
            embedded_items=1,
            batch_count=1,
            cache_enabled=False,
            trace_events=tuple(trace_events),
        )


def create_vector_store_dense_provider(settings: Any) -> VectorStoreDenseRetrievalProvider:
    """Create the production dense provider from configured factories."""

    from src.libs.embedding.embedding_factory import EmbeddingFactory
    from src.libs.vector_store.vector_store_factory import VectorStoreFactory

    return VectorStoreDenseRetrievalProvider(
        embedding_client=EmbeddingFactory.create(settings),
        vector_store=VectorStoreFactory.create(settings),
    )
