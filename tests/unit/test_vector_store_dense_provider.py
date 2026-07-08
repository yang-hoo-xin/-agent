"""Tests for production dense retrieval provider bridge."""

from __future__ import annotations

from src.mod_agent.evidence.dense import VectorStoreDenseRetrievalProvider
from src.mod_agent.knowledge import ChunkRecord


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3]]


class FakeVectorStore:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    def query(
        self,
        *,
        vector: list[float],
        top_k: int,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append({"vector": vector, "top_k": top_k, "filters": filters})
        return list(self.results)


class FailingVectorStore:
    def query(self, **_: object) -> list[dict[str, object]]:
        raise RuntimeError("vector backend unavailable")


def _chunk(chunk_id: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        text_for_embedding=f"text for {chunk_id}",
        dense_vector=None,
        sparse_terms=None,
        bm25_terms=None,
        metadata={"chunk_id": chunk_id},
        content_hash=f"hash-{chunk_id}",
    )


def test_vector_store_dense_provider_embeds_query_and_filters_to_known_chunks() -> None:
    embedding = FakeEmbeddingClient()
    vector_store = FakeVectorStore(
        [
            {"id": "chunk_b", "score": 0.9},
            {"id": "external_chunk", "score": 1.0},
            {"id": "chunk_a", "score": 0.7},
        ]
    )
    provider = VectorStoreDenseRetrievalProvider(
        embedding_client=embedding,
        vector_store=vector_store,
        filters={"collection_id": "default"},
        overfetch_multiplier=2,
    )

    report = provider.retrieve(
        query="runtime hook evidence",
        chunks=(_chunk("chunk_a"), _chunk("chunk_b")),
        top_k=2,
    )

    assert report.provider == "vector_store"
    assert report.enabled is True
    assert report.api_calls == 1
    assert report.embedded_items == 1
    assert [hit.chunk_id for hit in report.hits] == ["chunk_b", "chunk_a"]
    assert embedding.calls == [["runtime hook evidence"]]
    assert vector_store.calls == [
        {
            "vector": [0.1, 0.2, 0.3],
            "top_k": 4,
            "filters": {"collection_id": "default"},
        }
    ]
    assert "retrieval.dense_finished" in [
        str(event["event"]) for event in report.trace_events
    ]


def test_vector_store_dense_provider_returns_disabled_reason_on_backend_failure() -> None:
    provider = VectorStoreDenseRetrievalProvider(
        embedding_client=FakeEmbeddingClient(),
        vector_store=FailingVectorStore(),
    )

    report = provider.retrieve(
        query="runtime hook evidence",
        chunks=(_chunk("chunk_a"),),
        top_k=1,
    )

    assert report.enabled is True
    assert report.hits == ()
    assert report.disabled_reason == (
        "Dense retrieval provider failed: vector backend unavailable"
    )
    assert "retrieval.dense_failed" in [
        str(event["event"]) for event in report.trace_events
    ]
