"""Focused tests for the standard document RAG product entry point."""

from __future__ import annotations

from typing import Any

import pytest

from src.core.query_engine.hybrid_search import (
    HybridSearch,
    HybridSearchConfig,
    HybridSearchResult,
)
from src.core.query_engine.query_processor import QueryProcessor
from src.core.query_engine.sparse_retriever import SparseRetriever
from src.core.response.response_builder import ResponseBuilder
from src.core.types import ProcessedQuery, RetrievalResult
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.mcp_server.tools.query_knowledge_hub import (
    QueryKnowledgeHubConfig,
    QueryKnowledgeHubTool,
)


class FakeHybridSearch:
    def __init__(self, details: HybridSearchResult) -> None:
        self.details = details
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> HybridSearchResult:
        self.calls.append(kwargs)
        return self.details


def _result(source_path: str = "docs/guide.md") -> RetrievalResult:
    return RetrievalResult(
        chunk_id="guide_0001",
        score=1.0,
        text="The indexed guide contains a source-supported statement.",
        metadata={"source_path": source_path, "doc_type": "markdown"},
    )


def _details(
    *,
    results: list[RetrievalResult],
    sparse_results: list[RetrievalResult] | None,
    dense_results: list[RetrievalResult] | None = None,
    sparse_error: str | None = None,
    dense_error: str | None = None,
    filters: dict[str, Any] | None = None,
) -> HybridSearchResult:
    return HybridSearchResult(
        results=results,
        sparse_results=sparse_results,
        dense_results=dense_results,
        sparse_error=sparse_error,
        dense_error=dense_error,
        processed_query=ProcessedQuery(
            original_query="query",
            keywords=["query"],
            filters=filters or {},
        ),
    )


def _tool(
    details: HybridSearchResult,
    *,
    config: QueryKnowledgeHubConfig | None = None,
) -> QueryKnowledgeHubTool:
    tool = QueryKnowledgeHubTool(
        config=config,
        hybrid_search=FakeHybridSearch(details),
        response_builder=ResponseBuilder(enable_multimodal=False),
    )
    tool._ensure_initialized = lambda collection: None  # type: ignore[method-assign]
    return tool


@pytest.mark.asyncio
async def test_default_sparse_result_has_citation_and_complete_required_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    tool = _tool(_details(results=[result], sparse_results=[result]))
    monkeypatch.setattr(
        "src.mcp_server.tools.query_knowledge_hub.TraceCollector.collect",
        lambda self, trace: None,
    )

    response = await tool.execute("source-supported query", collection="docs")

    assert QueryKnowledgeHubConfig().enable_dense is False
    assert QueryKnowledgeHubConfig().enable_rerank is False
    assert response.metadata["retrieval_status"] == "source_supported_results"
    assert response.metadata["answer_allowance"] == "source_supported_results"
    assert response.metadata["required_coverage_complete"] is True
    assert response.metadata["searched_lanes"] == ["sparse_bm25"]
    assert response.metadata["unsearched_lanes"] == {"dense": "disabled_by_default"}
    assert response.metadata["retrieval_configuration"] == {
        "baseline": "sparse_bm25",
        "dense_enabled": False,
        "rerank_enabled": False,
    }
    assert response.citations[0].source == "docs/guide.md"


@pytest.mark.asyncio
async def test_completed_sparse_search_without_results_reports_evidence_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool(_details(results=[], sparse_results=[]))
    monkeypatch.setattr(
        "src.mcp_server.tools.query_knowledge_hub.TraceCollector.collect",
        lambda self, trace: None,
    )

    response = await tool.execute("unanswered question", collection="docs")

    assert response.metadata["retrieval_status"] == "evidence_insufficient"
    assert response.metadata["answer_allowance"] == "evidence_insufficient_response"
    assert response.metadata["required_coverage_complete"] is True
    assert response.metadata.get("error") is None
    assert response.is_empty is True
    assert response.content.startswith("## 证据不足")


@pytest.mark.asyncio
async def test_required_sparse_failure_is_not_reported_as_evidence_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dense_result = _result()
    tool = _tool(
        _details(
            results=[dense_result],
            sparse_results=None,
            dense_results=[dense_result],
            sparse_error="Sparse retrieval error: index unavailable",
        ),
        config=QueryKnowledgeHubConfig(enable_dense=True),
    )
    monkeypatch.setattr(
        "src.mcp_server.tools.query_knowledge_hub.TraceCollector.collect",
        lambda self, trace: None,
    )

    response = await tool.execute("query", collection="docs")

    assert response.metadata["retrieval_status"] == "retrieval_failed"
    assert response.metadata["answer_allowance"] == "none"
    assert response.metadata["required_coverage_complete"] is False
    assert "sparse_bm25" in response.metadata["failed_lanes"]
    assert "error" in response.metadata
    assert response.citations == []
    assert response.content.startswith("## 检索失败")


@pytest.mark.asyncio
async def test_optional_dense_failure_returns_bounded_sparse_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sparse_result = _result()
    tool = _tool(
        _details(
            results=[sparse_result],
            sparse_results=[sparse_result],
            dense_results=None,
            dense_error="Dense retrieval error: provider unavailable",
        ),
        config=QueryKnowledgeHubConfig(enable_dense=True),
    )
    monkeypatch.setattr(
        "src.mcp_server.tools.query_knowledge_hub.TraceCollector.collect",
        lambda self, trace: None,
    )

    response = await tool.execute("query", collection="docs")

    assert response.metadata["retrieval_status"] == "bounded_partial"
    assert response.metadata["answer_allowance"] == "bounded_partial_results"
    assert response.metadata["required_coverage_complete"] is True
    assert response.metadata["failed_lanes"] == {
        "dense": "Dense retrieval error: provider unavailable"
    }
    assert response.citations[0].source == "docs/guide.md"
    assert response.content.startswith("## 有界部分结果")


def test_source_path_filter_is_exact_identity_match() -> None:
    search = HybridSearch()

    assert search._matches_filters(
        {"source_path": "docs/guide.md"},
        {"source_path": "docs/guide.md"},
    )
    assert not search._matches_filters(
        {"source_path": "archive/docs/guide.md"},
        {"source_path": "docs/guide.md"},
    )


def test_perform_search_preserves_processed_filter_identity() -> None:
    result = _result()
    details = _details(
        results=[result],
        sparse_results=[result],
        filters={"source_path": "docs/guide.md", "doc_type": "markdown"},
    )
    tool = _tool(details)

    outcome = tool._perform_search(
        "source:docs/guide.md type:markdown query",
        5,
        collection="docs",
    )

    assert outcome.applied_filters == {
        "source_path": "docs/guide.md",
        "doc_type": "markdown",
        "collection": "docs",
    }
    assert tool._hybrid_search.calls[0]["filters"] == {"collection": "docs"}  # type: ignore[union-attr]
    assert tool._hybrid_search.calls[0]["return_details"] is True  # type: ignore[union-attr]


class InMemoryRecordStore:
    def __init__(self, records: dict[str, dict[str, Any]]) -> None:
        self.records = records

    def get_by_ids(self, ids: list[str], trace: Any = None) -> list[dict[str, Any]]:
        return [self.records[chunk_id] for chunk_id in ids if chunk_id in self.records]


@pytest.mark.asyncio
async def test_real_bm25_roundtrip_reaches_product_citation(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indexer = BM25Indexer(index_dir=str(tmp_path))
    indexer.build(
        [
            {
                "chunk_id": "guide_0001",
                "term_frequencies": {"calibration": 2, "evidence": 1},
                "doc_length": 3,
            },
            {
                "chunk_id": "other_0001",
                "term_frequencies": {"unrelated": 2, "material": 1},
                "doc_length": 3,
            },
        ],
        collection="docs",
    )
    record_store = InMemoryRecordStore(
        {
            "guide_0001": {
                "id": "guide_0001",
                "text": "Calibration evidence must stay source bound.",
                "metadata": {
                    "source_path": "docs/guide.md",
                    "doc_type": "markdown",
                    "doc_hash": "sha256:guide",
                    "source_ref": "doc_guide",
                },
            },
            "other_0001": {
                "id": "other_0001",
                "text": "Unrelated material.",
                "metadata": {
                    "source_path": "docs/other.md",
                    "doc_type": "markdown",
                },
            },
        }
    )
    sparse = SparseRetriever(
        bm25_indexer=indexer,
        vector_store=record_store,  # type: ignore[arg-type]
        default_collection="docs",
        fail_on_unavailable_index=True,
    )
    search = HybridSearch(
        query_processor=QueryProcessor(),
        sparse_retriever=sparse,
        config=HybridSearchConfig(
            enable_dense=False,
            enable_sparse=True,
            parallel_retrieval=False,
        ),
    )
    tool = QueryKnowledgeHubTool(
        hybrid_search=search,
        response_builder=ResponseBuilder(enable_multimodal=False),
    )
    tool._ensure_initialized = lambda collection: None  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.mcp_server.tools.query_knowledge_hub.TraceCollector.collect",
        lambda self, trace: None,
    )

    response = await tool.execute(
        "source:docs/guide.md calibration evidence",
        collection="docs",
    )

    assert response.metadata["retrieval_status"] == "source_supported_results"
    assert response.metadata["required_coverage_complete"] is True
    assert response.metadata["applied_filters"] == {
        "source_path": "docs/guide.md",
        "collection": "docs",
    }
    assert [citation.source for citation in response.citations] == ["docs/guide.md"]
    assert response.citations[0].chunk_id == "guide_0001"
    assert response.citations[0].metadata["doc_hash"] == "sha256:guide"
    assert response.citations[0].metadata["source_ref"] == "doc_guide"
    assert response.citations[0].metadata["collection"] == "docs"


@pytest.mark.asyncio
async def test_inline_collection_selects_physical_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result()
    details = _details(
        results=[result],
        sparse_results=[result],
        filters={"collection": "manuals"},
    )
    tool = _tool(details)
    initialized: list[str] = []
    tool._ensure_initialized = initialized.append  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.mcp_server.tools.query_knowledge_hub.TraceCollector.collect",
        lambda self, trace: None,
    )

    response = await tool.execute("collection:manuals calibration evidence")

    assert initialized == ["manuals"]
    assert response.metadata["collection"] == "manuals"
    assert tool._hybrid_search.calls[0]["filters"] == {"collection": "manuals"}  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_initialization_failure_exposes_platform_failure_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _tool(_details(results=[], sparse_results=[]))

    def fail_initialization(collection: str) -> None:
        raise RuntimeError("vector store unavailable")

    tool._ensure_initialized = fail_initialization  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.mcp_server.tools.query_knowledge_hub.TraceCollector.collect",
        lambda self, trace: None,
    )

    response = await tool.execute("query", collection="docs")

    assert response.metadata["retrieval_status"] == "retrieval_failed"
    assert response.metadata["answer_allowance"] == "none"
    assert response.metadata["required_coverage_complete"] is False
    assert response.metadata["unsearched_lanes"] == {"sparse_bm25": "platform_failure"}
    assert response.metadata["failed_lanes"] == {
        "initialization_or_retrieval": "vector store unavailable"
    }
