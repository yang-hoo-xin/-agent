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
    CHUNK_IDENTITY_FIELDS,
    DOCUMENT_IDENTITY_FIELDS,
    EVIDENCE_IDENTITY_FIELDS,
    IDENTITY_FIELD_MAPPING,
    IDENTITY_SCHEMA_VERSION,
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
    evidence_identity_from_metadata,
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
    "CHUNK_IDENTITY_FIELDS",
    "DOCUMENT_IDENTITY_FIELDS",
    "EVIDENCE_IDENTITY_FIELDS",
    "IDENTITY_FIELD_MAPPING",
    "IDENTITY_SCHEMA_VERSION",
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
    "evidence_identity_from_metadata",
    "normalize_bm25_token",
    "tokenize_bm25",
]
