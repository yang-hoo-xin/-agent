"""Data contracts for the local Knowledge Base."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IDENTITY_SCHEMA_VERSION = "identity_v1"
IDENTITY_FIELD_MAPPING = {
    "document_id": "Stable loaded document id generated from source_id, relative_path, and file_hash.",
    "file_hash": "SHA256 of the loaded source file bytes decoded as text for V1 loaders.",
    "source_hash": "Backward-compatible V1 alias for file_hash on file-backed sources.",
    "doc_hash": "SHA256 of the document canonical_text.",
    "chunk_id": "Stable chunk id generated from document_id, chunk_index, and chunk content_hash.",
    "source_ref": "Chunk-to-document reference; for V1 chunks this must equal document_id.",
    "content_hash": "Context-dependent stored content hash: file_hash on Document metadata, chunk text hash on Chunk metadata.",
}
DOCUMENT_IDENTITY_FIELDS = frozenset(
    {
        "document_id",
        "file_hash",
        "source_hash",
        "doc_hash",
        "content_hash",
        "raw_text_hash",
        "canonical_text_hash",
    }
)
CHUNK_IDENTITY_FIELDS = frozenset(
    {
        "chunk_id",
        "document_id",
        "source_ref",
        "file_hash",
        "source_hash",
        "doc_hash",
        "content_hash",
    }
)
EVIDENCE_IDENTITY_FIELDS = (
    "chunk_id",
    "document_id",
    "source_ref",
    "source_hash",
    "file_hash",
    "doc_hash",
)


@dataclass(frozen=True)
class SourceRecord:
    """Registered source root that can contribute evidence."""

    source_id: str
    source_type: str
    root_path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceSpan:
    """Location of a document or chunk inside the original source."""

    start_line: int
    end_line: int
    page: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "page": self.page,
        }


@dataclass(frozen=True)
class Document:
    """Loader output that keeps raw, canonical, and retrieval text separate."""

    document_id: str
    source_type: str
    source_path: str
    raw_text: str
    canonical_text: str
    text: str
    metadata: dict[str, Any]

    @property
    def content_hash(self) -> str:
        return str(self.metadata["content_hash"])

    @property
    def file_hash(self) -> str:
        return str(self.metadata["file_hash"])

    @property
    def doc_hash(self) -> str:
        return str(self.metadata["doc_hash"])


@dataclass(frozen=True)
class Chunk:
    """Self-contained retrieval unit derived from a document."""

    chunk_id: str
    document_id: str
    text: str
    text_for_retrieval: str
    metadata: dict[str, Any]
    source_span: SourceSpan | None = None


@dataclass(frozen=True)
class ChunkRecord:
    """Index-facing chunk projection for sparse, dense, and metadata stores."""

    chunk_id: str
    text_for_embedding: str
    dense_vector: list[float] | None
    sparse_terms: dict[str, float] | None
    bm25_terms: dict[str, int] | None
    metadata: dict[str, Any]
    content_hash: str


@dataclass(frozen=True)
class KnowledgeSourceSnapshot:
    """Collection-scoped source state used by index versioning."""

    source_id: str
    collection_id: str
    source_path: str
    source_type: str
    content_hash: str
    mtime: str | None
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeDocumentRecord:
    """Persisted document metadata row."""

    document_id: str
    source_id: str
    raw_text_hash: str
    canonical_text_hash: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeChunkRecord:
    """Persisted chunk row bound to an index version."""

    chunk_id: str
    document_id: str
    collection_id: str
    index_version: str
    chunk_text: str
    text_for_retrieval: str
    content_hash: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IndexVersion:
    """Stable/building/failed index snapshot metadata."""

    collection_id: str
    index_version: str
    status: str
    source_count: int
    chunk_count: int
    created_at: str


@dataclass(frozen=True)
class BM25IndexResult:
    """Result of replacing the BM25 inverted index for one version."""

    collection_id: str
    index_version: str
    chunk_count: int
    term_count: int
    posting_count: int


@dataclass(frozen=True)
class BM25Hit:
    """BM25 lexical hit with explainable term metadata."""

    collection_id: str
    index_version: str
    chunk_id: str
    document_id: str
    score: float
    hit_terms: tuple[str, ...]
    term_frequencies: dict[str, int]
    source_path: str
    span: dict[str, int] | None
    excerpt: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SymbolIndexEntry:
    """Chunk-bound symbol index row."""

    collection_id: str
    index_version: str
    symbol: str
    symbol_kind: str
    chunk_id: str
    source_path: str
    start_line: int | None
    end_line: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SymbolIndexResult:
    """Result of replacing chunk-bound symbol rows for one version."""

    collection_id: str
    index_version: str
    chunk_count: int
    symbol_count: int


@dataclass(frozen=True)
class IndexedFile:
    """Content hash state for one indexed source file."""

    file_id: str
    source_id: str
    source_path: str
    relative_path: str
    content_hash: str
    indexed_at: str

    def to_document(self, *, source: SourceRecord, raw_text: str) -> Document:
        """Build the V1 document contract for this indexed file."""

        canonical_text = canonicalize_text(raw_text)
        metadata = source_metadata_for_file(source=source, indexed_file=self)
        raw_text_hash = stable_hash(raw_text)
        canonical_text_hash = stable_hash(canonical_text)
        document_id = stable_id("doc", source.source_id, self.relative_path, self.content_hash)
        return Document(
            document_id=document_id,
            source_type=source.source_type,
            source_path=self.source_path,
            raw_text=raw_text,
            canonical_text=canonical_text,
            text=canonical_text,
            metadata={
                **metadata,
                "document_id": document_id,
                "raw_text_hash": raw_text_hash,
                "canonical_text_hash": canonical_text_hash,
                "doc_hash": canonical_text_hash,
            },
        )


@dataclass(frozen=True)
class SymbolRecord:
    """Symbol-level evidence index entry."""

    symbol_id: str
    source_id: str
    source_path: str
    relative_path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    excerpt: str
    content_hash: str

    def to_evidence_item(self, *, retrieval_method: str = "symbol") -> dict[str, Any]:
        """Project a symbol into the Evidence Item shape used by Phase D."""

        return {
            "evidence_id": self.symbol_id,
            "source_type": self.source_id,
            "source_path": self.source_path,
            "symbol": self.name,
            "span": {
                "start_line": self.start_line,
                "end_line": self.end_line,
            },
            "retrieval_method": retrieval_method,
            "score": 1.0,
            "claim_supported": f"Symbol {self.name} exists in {self.relative_path}.",
            "excerpt": self.excerpt,
            "risk_notes": [],
        }


def canonicalize_text(raw_text: str) -> str:
    """Normalize newlines without changing evidence content."""

    return raw_text.replace("\r\n", "\n").replace("\r", "\n")


def source_metadata_for_file(
    *,
    source: SourceRecord,
    indexed_file: IndexedFile,
    project_id: str = "default",
) -> dict[str, Any]:
    """Build required source metadata from persisted source and file records."""

    source_path = Path(indexed_file.source_path)
    return {
        "source_id": source.source_id,
        "source_path": indexed_file.source_path,
        "relative_path": indexed_file.relative_path,
        "source_type": source.source_type,
        "content_hash": indexed_file.content_hash,
        "file_hash": indexed_file.content_hash,
        "source_hash": indexed_file.content_hash,
        "loader": loader_name_for_path(source_path),
        "language": language_for_path(source_path),
        "project_id": str(source.metadata.get("project_id", project_id)),
        "target_ecosystem": source.metadata.get("target_ecosystem"),
        "mtime": source.metadata.get("mtime"),
    }


def chunk_from_document(
    document: Document,
    *,
    chunk_index: int = 0,
    text: str | None = None,
    text_for_retrieval: str | None = None,
    source_span: SourceSpan | None = None,
    chunk_type: str | None = None,
    chunk_strategy: str | None = None,
    symbols: tuple[str, ...] = (),
    heading_path: tuple[str, ...] = (),
    risk_tags: tuple[str, ...] = (),
    evidence_kind: str | None = None,
) -> Chunk:
    """Create a chunk with inherited source metadata and stable ids."""

    chunk_text = text if text is not None else document.canonical_text
    retrieval_text = text_for_retrieval if text_for_retrieval is not None else chunk_text
    content_hash = stable_hash(chunk_text)
    chunk_id = stable_id(
        "chunk",
        document.document_id,
        str(chunk_index),
        content_hash,
    )
    span = source_span or SourceSpan(
        start_line=1,
        end_line=max(1, len(chunk_text.splitlines())),
    )
    metadata = {
        **document.metadata,
        "chunk_id": chunk_id,
        "document_id": document.document_id,
        "chunk_index": chunk_index,
        "chunk_type": chunk_type or default_chunk_type(document),
        "chunk_strategy": chunk_strategy or default_chunk_strategy(document),
        "start_line": span.start_line,
        "end_line": span.end_line,
        "page": span.page,
        "heading_path": list(heading_path),
        "symbols": list(symbols),
        "risk_tags": list(risk_tags),
        "evidence_kind": evidence_kind or default_evidence_kind(document),
        "source_hash": document.file_hash,
        "file_hash": document.file_hash,
        "doc_hash": document.doc_hash,
        "source_ref": document.document_id,
        "content_hash": content_hash,
        "metadata_version": "metadata_v1",
        "enrichment_version": "none",
        "image_refs": [],
        "image_captions": {},
    }
    return Chunk(
        chunk_id=chunk_id,
        document_id=document.document_id,
        text=chunk_text,
        text_for_retrieval=retrieval_text,
        metadata=metadata,
        source_span=span,
    )


def chunk_record_from_chunk(chunk: Chunk) -> ChunkRecord:
    """Project a chunk into the index-facing record contract."""

    return ChunkRecord(
        chunk_id=chunk.chunk_id,
        text_for_embedding=chunk.text_for_retrieval,
        dense_vector=None,
        sparse_terms=None,
        bm25_terms=None,
        metadata=dict(chunk.metadata),
        content_hash=str(chunk.metadata["content_hash"]),
    )


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    seed = ":".join(parts)
    return f"{prefix}_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def evidence_identity_from_metadata(metadata: dict[str, Any]) -> dict[str, str | None]:
    """Return the identity fields that evidence items expose for source tracing."""

    return {
        field: str(metadata[field]) if metadata.get(field) is not None else None
        for field in EVIDENCE_IDENTITY_FIELDS
    }


def language_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".cs": "csharp",
        ".py": "python",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".log": "log",
        ".txt": "text",
    }.get(suffix, "text")


def loader_name_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".cs", ".py"}:
        return "CodeLoader"
    if suffix == ".md":
        return "MarkdownLoader"
    if suffix in {".json", ".yaml", ".yml"}:
        return "ArtifactLoader"
    if suffix == ".log":
        return "LogLoader"
    return "TextLoader"


def default_chunk_type(document: Document) -> str:
    language = str(document.metadata.get("language"))
    if language in {"csharp", "python"}:
        return "code_symbol"
    if language == "log":
        return "log_window"
    return "paragraph"


def default_chunk_strategy(document: Document) -> str:
    language = str(document.metadata.get("language"))
    if language in {"csharp", "python"}:
        return "symbol_aware"
    if language == "log":
        return "log_window"
    return "structure_aware"


def default_evidence_kind(document: Document) -> str:
    source_type = str(document.metadata.get("source_type"))
    if source_type in {"target_source", "reference_mod", "decompiled_api"}:
        return "source_code"
    if source_type in {"build_log", "runtime_log"}:
        return "log"
    if source_type == "prior_artifact":
        return "artifact"
    return "text"
