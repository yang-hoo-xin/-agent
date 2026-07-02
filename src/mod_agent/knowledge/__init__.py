"""Knowledge base primitives for evidence-grounded code development."""

from .bm25_indexer import BM25Indexer, normalize_bm25_token, tokenize_bm25
from .collection_resolver import (
    CollectionResolution,
    CollectionResolutionError,
    CollectionResolver,
)
from .database import KnowledgeDatabase
from .indexer import IncrementalIndexer, IndexingReport
from .models import (
    BM25Hit,
    BM25IndexResult,
    Chunk,
    ChunkRecord,
    Document,
    IndexVersion,
    IndexedFile,
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    KnowledgeSourceSnapshot,
    SourceRecord,
    SourceSpan,
    SymbolIndexEntry,
    SymbolIndexResult,
    SymbolRecord,
    chunk_from_document,
    chunk_record_from_chunk,
)
from .source_discovery import DiscoveredSourceFile, SourceDiscovery
from .source_registry import SourceDefinition, SourceRegistry
from .symbol_indexer import SymbolIndexer

__all__ = [
    "BM25Hit",
    "BM25IndexResult",
    "BM25Indexer",
    "CollectionResolution",
    "CollectionResolutionError",
    "CollectionResolver",
    "IncrementalIndexer",
    "Chunk",
    "ChunkRecord",
    "DiscoveredSourceFile",
    "Document",
    "IndexVersion",
    "IndexedFile",
    "IndexingReport",
    "KnowledgeChunkRecord",
    "KnowledgeDatabase",
    "KnowledgeDocumentRecord",
    "KnowledgeSourceSnapshot",
    "SourceDefinition",
    "SourceDiscovery",
    "SourceRecord",
    "SourceSpan",
    "SourceRegistry",
    "SymbolIndexEntry",
    "SymbolIndexResult",
    "SymbolIndexer",
    "SymbolRecord",
    "chunk_from_document",
    "chunk_record_from_chunk",
    "normalize_bm25_token",
    "tokenize_bm25",
]
