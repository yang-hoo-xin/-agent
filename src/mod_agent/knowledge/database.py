"""SQLite-backed Knowledge Base for source, artifact, and log evidence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import (
    CHUNK_IDENTITY_FIELDS,
    DOCUMENT_IDENTITY_FIELDS,
    Chunk,
    Document,
    IndexVersion,
    IndexedFile,
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    KnowledgeSourceSnapshot,
    SourceRecord,
    SymbolIndexEntry,
    SymbolRecord,
)


class KnowledgeDatabaseError(RuntimeError):
    """Raised when the Knowledge Base cannot satisfy a contract."""


class KnowledgeDatabase:
    """Small SQLite store for deterministic evidence indexing."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def upsert_source(self, source: SourceRecord) -> None:
        """Register or update a source root."""

        now = self._now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT created_at FROM sources WHERE source_id = ?",
                (source.source_id,),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                INSERT OR REPLACE INTO sources (
                    source_id, source_type, root_path, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_id,
                    source.source_type,
                    source.root_path,
                    json.dumps(source.metadata, sort_keys=True),
                    created_at,
                    now,
                ),
            )

    def list_sources(self) -> list[SourceRecord]:
        """Return registered source roots."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_id, source_type, root_path, metadata_json
                FROM sources
                ORDER BY source_id
                """
            ).fetchall()
        return [
            SourceRecord(
                source_id=row["source_id"],
                source_type=row["source_type"],
                root_path=row["root_path"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def upsert_knowledge_source(self, source: KnowledgeSourceSnapshot) -> None:
        """Persist collection-scoped source metadata for an index build."""

        self._validate_status(source.status, {"building", "stable", "failed", "skipped"})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_sources (
                    source_id, collection_id, source_path, source_type, content_hash,
                    mtime, status, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_id,
                    source.collection_id,
                    source.source_path,
                    source.source_type,
                    source.content_hash,
                    source.mtime,
                    source.status,
                    json.dumps(source.metadata, sort_keys=True),
                ),
            )

    def get_knowledge_source(
        self,
        *,
        collection_id: str,
        source_id: str,
    ) -> KnowledgeSourceSnapshot | None:
        """Return a collection-scoped source row."""

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT source_id, collection_id, source_path, source_type, content_hash,
                       mtime, status, metadata_json
                FROM knowledge_sources
                WHERE collection_id = ? AND source_id = ?
                """,
                (collection_id, source_id),
            ).fetchone()
        return self._source_snapshot_from_row(row) if row else None

    def list_knowledge_sources(
        self,
        *,
        collection_id: str | None = None,
    ) -> list[KnowledgeSourceSnapshot]:
        """Return persisted source snapshots."""

        with self._connect() as conn:
            if collection_id is None:
                rows = conn.execute(
                    """
                    SELECT source_id, collection_id, source_path, source_type, content_hash,
                           mtime, status, metadata_json
                    FROM knowledge_sources
                    ORDER BY collection_id, source_id
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT source_id, collection_id, source_path, source_type, content_hash,
                           mtime, status, metadata_json
                    FROM knowledge_sources
                    WHERE collection_id = ?
                    ORDER BY source_id
                    """,
                    (collection_id,),
                ).fetchall()
        return [self._source_snapshot_from_row(row) for row in rows]

    def upsert_document(self, document: Document) -> KnowledgeDocumentRecord:
        """Persist document metadata and hash contract."""

        self._validate_document_identity(document)
        source_id = self._required_metadata(document.metadata, "source_id")
        raw_text_hash = self._required_metadata(document.metadata, "raw_text_hash")
        canonical_text_hash = self._required_metadata(document.metadata, "canonical_text_hash")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_documents (
                    document_id, source_id, raw_text_hash, canonical_text_hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    source_id,
                    raw_text_hash,
                    canonical_text_hash,
                    json.dumps(document.metadata, sort_keys=True),
                ),
            )
        return KnowledgeDocumentRecord(
            document_id=document.document_id,
            source_id=source_id,
            raw_text_hash=raw_text_hash,
            canonical_text_hash=canonical_text_hash,
            metadata=dict(document.metadata),
        )

    def upsert_documents(
        self,
        documents: list[Document],
    ) -> list[KnowledgeDocumentRecord]:
        """Persist a bounded document snapshot in one transaction."""

        records: list[KnowledgeDocumentRecord] = []
        rows: list[tuple[str, str, str, str, str]] = []
        for document in documents:
            self._validate_document_identity(document)
            source_id = self._required_metadata(document.metadata, "source_id")
            raw_text_hash = self._required_metadata(document.metadata, "raw_text_hash")
            canonical_text_hash = self._required_metadata(
                document.metadata, "canonical_text_hash"
            )
            rows.append(
                (
                    document.document_id,
                    source_id,
                    raw_text_hash,
                    canonical_text_hash,
                    json.dumps(document.metadata, sort_keys=True),
                )
            )
            records.append(
                KnowledgeDocumentRecord(
                    document_id=document.document_id,
                    source_id=source_id,
                    raw_text_hash=raw_text_hash,
                    canonical_text_hash=canonical_text_hash,
                    metadata=dict(document.metadata),
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO knowledge_documents (
                    document_id, source_id, raw_text_hash, canonical_text_hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
        return records

    def get_document(self, document_id: str) -> KnowledgeDocumentRecord | None:
        """Return persisted document metadata by id."""

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT document_id, source_id, raw_text_hash, canonical_text_hash, metadata_json
                FROM knowledge_documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()
        return self._document_record_from_row(row) if row else None

    def upsert_chunk(
        self,
        chunk: Chunk,
        *,
        collection_id: str,
        index_version: str,
    ) -> KnowledgeChunkRecord:
        """Persist one chunk bound to an index version."""

        self._validate_chunk_identity(chunk)
        content_hash = self._required_metadata(chunk.metadata, "content_hash")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO knowledge_chunks (
                    chunk_id, document_id, collection_id, index_version, chunk_text,
                    text_for_retrieval, content_hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    collection_id,
                    index_version,
                    chunk.text,
                    chunk.text_for_retrieval,
                    content_hash,
                    json.dumps(chunk.metadata, sort_keys=True),
                ),
            )
        return KnowledgeChunkRecord(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            collection_id=collection_id,
            index_version=index_version,
            chunk_text=chunk.text,
            text_for_retrieval=chunk.text_for_retrieval,
            content_hash=content_hash,
            metadata=dict(chunk.metadata),
        )

    def upsert_chunks(
        self,
        chunks: list[Chunk],
        *,
        collection_id: str,
        index_version: str,
    ) -> list[KnowledgeChunkRecord]:
        """Persist a bounded chunk snapshot in one transaction."""

        records: list[KnowledgeChunkRecord] = []
        rows: list[tuple[str, str, str, str, str, str, str, str]] = []
        for chunk in chunks:
            self._validate_chunk_identity(chunk)
            content_hash = self._required_metadata(chunk.metadata, "content_hash")
            rows.append(
                (
                    chunk.chunk_id,
                    chunk.document_id,
                    collection_id,
                    index_version,
                    chunk.text,
                    chunk.text_for_retrieval,
                    content_hash,
                    json.dumps(chunk.metadata, sort_keys=True),
                )
            )
            records.append(
                KnowledgeChunkRecord(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    collection_id=collection_id,
                    index_version=index_version,
                    chunk_text=chunk.text,
                    text_for_retrieval=chunk.text_for_retrieval,
                    content_hash=content_hash,
                    metadata=dict(chunk.metadata),
                )
            )
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO knowledge_chunks (
                    chunk_id, document_id, collection_id, index_version, chunk_text,
                    text_for_retrieval, content_hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return records

    def list_chunks(
        self,
        *,
        collection_id: str,
        index_version: str,
    ) -> list[KnowledgeChunkRecord]:
        """Return chunks for a collection index version."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, document_id, collection_id, index_version, chunk_text,
                       text_for_retrieval, content_hash, metadata_json
                FROM knowledge_chunks
                WHERE collection_id = ? AND index_version = ?
                ORDER BY chunk_id
                """,
                (collection_id, index_version),
            ).fetchall()
        return [self._chunk_record_from_row(row) for row in rows]

    def chunks_by_id(
        self,
        *,
        collection_id: str,
        index_version: str,
        chunk_ids: tuple[str, ...],
    ) -> dict[str, KnowledgeChunkRecord]:
        """Return chunks for the given ids in one collection index version."""

        if not chunk_ids:
            return {}
        placeholders = ", ".join("?" for _ in chunk_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT chunk_id, document_id, collection_id, index_version, chunk_text,
                       text_for_retrieval, content_hash, metadata_json
                FROM knowledge_chunks
                WHERE collection_id = ? AND index_version = ?
                  AND chunk_id IN ({placeholders})
                """,
                (collection_id, index_version, *chunk_ids),
            ).fetchall()
        chunks = [self._chunk_record_from_row(row) for row in rows]
        return {chunk.chunk_id: chunk for chunk in chunks}

    def replace_bm25_index(
        self,
        *,
        collection_id: str,
        index_version: str,
        term_doc_freqs: dict[str, int],
        postings: dict[tuple[str, str], int],
    ) -> None:
        """Replace BM25 terms and postings for one index version atomically."""

        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM bm25_terms
                WHERE collection_id = ? AND index_version = ?
                """,
                (collection_id, index_version),
            )
            conn.execute(
                """
                DELETE FROM bm25_postings
                WHERE collection_id = ? AND index_version = ?
                """,
                (collection_id, index_version),
            )
            conn.executemany(
                """
                INSERT INTO bm25_terms (
                    collection_id, index_version, term, doc_freq
                )
                VALUES (?, ?, ?, ?)
                """,
                [
                    (collection_id, index_version, term, doc_freq)
                    for term, doc_freq in sorted(term_doc_freqs.items())
                ],
            )
            conn.executemany(
                """
                INSERT INTO bm25_postings (
                    collection_id, index_version, term, chunk_id, term_freq
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (collection_id, index_version, term, chunk_id, term_freq)
                    for (term, chunk_id), term_freq in sorted(postings.items())
                ],
            )

    def bm25_term_doc_freqs(
        self,
        *,
        collection_id: str,
        index_version: str,
    ) -> dict[str, int]:
        """Return BM25 document frequencies for one index version."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT term, doc_freq
                FROM bm25_terms
                WHERE collection_id = ? AND index_version = ?
                ORDER BY term
                """,
                (collection_id, index_version),
            ).fetchall()
        return {row["term"]: int(row["doc_freq"]) for row in rows}

    def bm25_postings_for_terms(
        self,
        *,
        collection_id: str,
        index_version: str,
        terms: tuple[str, ...],
    ) -> list[dict[str, str | int]]:
        """Return BM25 posting rows for normalized query terms."""

        if not terms:
            return []
        placeholders = ", ".join("?" for _ in terms)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT term, chunk_id, term_freq
                FROM bm25_postings
                WHERE collection_id = ? AND index_version = ?
                  AND term IN ({placeholders})
                ORDER BY term, chunk_id
                """,
                (collection_id, index_version, *terms),
            ).fetchall()
        return [
            {
                "term": row["term"],
                "chunk_id": row["chunk_id"],
                "term_freq": int(row["term_freq"]),
            }
            for row in rows
        ]

    def replace_symbol_index(
        self,
        *,
        collection_id: str,
        index_version: str,
        entries: list[SymbolIndexEntry],
    ) -> None:
        """Replace chunk-bound symbols for one index version atomically."""

        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM symbol_index
                WHERE collection_id = ? AND index_version = ?
                """,
                (collection_id, index_version),
            )
            conn.executemany(
                """
                INSERT INTO symbol_index (
                    collection_id, index_version, symbol, symbol_kind, chunk_id,
                    source_path, start_line, end_line, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entry.collection_id,
                        entry.index_version,
                        entry.symbol,
                        entry.symbol_kind,
                        entry.chunk_id,
                        entry.source_path,
                        entry.start_line,
                        entry.end_line,
                        json.dumps(entry.metadata, sort_keys=True),
                    )
                    for entry in entries
                ],
            )

    def search_symbol_index(
        self,
        *,
        collection_id: str,
        index_version: str,
        symbol: str,
        symbol_kind: str | None = None,
        limit: int = 20,
    ) -> list[SymbolIndexEntry]:
        """Search chunk-bound symbols by exact symbol name."""

        normalized = symbol.strip()
        if not normalized or limit <= 0:
            return []
        with self._connect() as conn:
            if symbol_kind is None:
                rows = conn.execute(
                    """
                    SELECT collection_id, index_version, symbol, symbol_kind, chunk_id,
                           source_path, start_line, end_line, metadata_json
                    FROM symbol_index
                    WHERE collection_id = ? AND index_version = ?
                      AND lower(symbol) = lower(?)
                    ORDER BY source_path, start_line, chunk_id
                    LIMIT ?
                    """,
                    (collection_id, index_version, normalized, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT collection_id, index_version, symbol, symbol_kind, chunk_id,
                           source_path, start_line, end_line, metadata_json
                    FROM symbol_index
                    WHERE collection_id = ? AND index_version = ?
                      AND lower(symbol) = lower(?)
                      AND symbol_kind = ?
                    ORDER BY source_path, start_line, chunk_id
                    LIMIT ?
                    """,
                    (collection_id, index_version, normalized, symbol_kind, limit),
                ).fetchall()
        return [self._symbol_index_entry_from_row(row) for row in rows]

    def start_index_version(
        self,
        *,
        collection_id: str,
        index_version: str,
        source_count: int,
        chunk_count: int,
        source_files: dict[str, dict[str, str]] | None = None,
    ) -> IndexVersion:
        """Create or reset an index version in building state."""

        return self._write_index_version(
            collection_id=collection_id,
            index_version=index_version,
            status="building",
            source_count=source_count,
            chunk_count=chunk_count,
            created_at=self._now(),
            source_files=source_files,
        )

    def set_index_version_status(
        self,
        *,
        collection_id: str,
        index_version: str,
        status: str,
    ) -> IndexVersion:
        """Mark an existing index version stable or failed."""

        self._validate_status(status, {"stable", "failed"})
        existing = self.get_index_version(
            collection_id=collection_id,
            index_version=index_version,
        )
        if existing is None:
            raise KnowledgeDatabaseError(
                f"Unknown index version: {collection_id}/{index_version}"
            )
        return self._write_index_version(
            collection_id=collection_id,
            index_version=index_version,
            status=status,
            source_count=existing.source_count,
            chunk_count=existing.chunk_count,
            created_at=existing.created_at,
        )

    def get_index_version(
        self,
        *,
        collection_id: str,
        index_version: str,
    ) -> IndexVersion | None:
        """Return index version metadata."""

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT collection_id, index_version, status, source_count, chunk_count, created_at
                FROM index_versions
                WHERE collection_id = ? AND index_version = ?
                """,
                (collection_id, index_version),
            ).fetchone()
        return self._index_version_from_row(row) if row else None

    def stable_index_version(self, collection_id: str) -> IndexVersion | None:
        """Select a published stable snapshot that still matches its indexed sources.

        A source scan prepares current rows; it does not publish retrieval data.
        Exact-version history remains readable when a newer scan makes a prior
        snapshot ineligible for current retrieval.
        """

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT collection_id, index_version, status, source_count, chunk_count, created_at, source_files_json
                FROM index_versions
                WHERE collection_id = ? AND status = 'stable'
                ORDER BY created_at DESC, index_version DESC
                """,
                (collection_id,),
            ).fetchall()
            for row in rows:
                if row["source_files_json"] is not None:
                    manifest = json.loads(row["source_files_json"])
                    if not all({item["source_path"]: item["content_hash"] for item in conn.execute(
                        "SELECT source_path, content_hash FROM indexed_files WHERE source_id = ?", (source_id,)
                    ).fetchall()} == expected for source_id, expected in manifest.items()):
                        continue
                else:
                    # This owner's V1 could contain new text with an old file
                    # hash. Never promote it by reconstructing trusted scope
                    # from that metadata. Other snapshot strategies are unchanged.
                    legacy_chunks = conn.execute(
                        "SELECT metadata_json FROM knowledge_chunks WHERE collection_id = ? AND index_version = ?",
                        (collection_id, row["index_version"]),
                    ).fetchall()
                    if any(json.loads(item["metadata_json"]).get("chunk_strategy") == "bounded_source_chunks_v1"
                           for item in legacy_chunks):
                        continue
                return self._index_version_from_row(row)
        return None

    def file_for_path(self, *, source_id: str, source_path: str) -> IndexedFile | None:
        """Return indexed file state for a source path, if present."""

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT file_id, source_id, source_path, relative_path, content_hash, indexed_at
                FROM indexed_files
                WHERE source_id = ? AND source_path = ?
                """,
                (source_id, source_path),
            ).fetchone()
        if row is None:
            return None
        return IndexedFile(**dict(row))

    def list_indexed_files(self, source_id: str | None = None) -> list[IndexedFile]:
        """Return indexed file states, optionally filtered by source."""

        with self._connect() as conn:
            if source_id is None:
                rows = conn.execute(
                    """
                    SELECT file_id, source_id, source_path, relative_path,
                           content_hash, indexed_at
                    FROM indexed_files
                    ORDER BY source_id, relative_path
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT file_id, source_id, source_path, relative_path,
                           content_hash, indexed_at
                    FROM indexed_files
                    WHERE source_id = ?
                    ORDER BY relative_path
                    """,
                    (source_id,),
                ).fetchall()
        return [IndexedFile(**dict(row)) for row in rows]

    def symbols_for_file(
        self,
        *,
        source_id: str,
        source_path: str,
    ) -> list[SymbolRecord]:
        """Return exact symbol records already extracted for one file."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol_id, source_id, source_path, relative_path, name, kind,
                       start_line, end_line, signature, excerpt, content_hash
                FROM symbols
                WHERE source_id = ? AND source_path = ?
                ORDER BY start_line, name
                """,
                (source_id, source_path),
            ).fetchall()
        return [SymbolRecord(**dict(row)) for row in rows]

    def upsert_file(
        self,
        *,
        file_id: str,
        source_id: str,
        source_path: str,
        relative_path: str,
        content_hash: str,
    ) -> IndexedFile:
        """Persist content hash state for one indexed file."""

        indexed_at = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO indexed_files (
                    file_id, source_id, source_path, relative_path, content_hash, indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (file_id, source_id, source_path, relative_path, content_hash, indexed_at),
            )
        return IndexedFile(
            file_id=file_id,
            source_id=source_id,
            source_path=source_path,
            relative_path=relative_path,
            content_hash=content_hash,
            indexed_at=indexed_at,
        )

    def replace_indexed_source_files(
        self,
        *,
        source_id: str,
        files: list[IndexedFile],
        symbols_by_path: dict[str, list[SymbolRecord]],
        observed_source_paths: tuple[str, ...] | None = None,
    ) -> int:
        """Commit changed rows and, after a complete scan, remove absent current rows.

        Historical documents/chunks and stable BM25/symbol snapshots are not
        current-source membership and are never pruned here.
        """
        if any(item.source_id != source_id for item in files) or any(
            symbol.source_id != source_id or symbol.source_path != path
            for path, symbols in symbols_by_path.items() for symbol in symbols
        ):
            raise KnowledgeDatabaseError("Indexed source update crosses its selected source identity.")
        observed = set(observed_source_paths) if observed_source_paths is not None else None
        if observed is not None and (any(item.source_path not in observed for item in files)
                                     or not set(symbols_by_path).issubset(observed)):
            raise KnowledgeDatabaseError("Changed source rows are outside the completed scan.")

        with self._connect() as conn:
            removed = []
            if observed is not None:
                removed = [(source_id, row[0]) for row in conn.execute(
                    "SELECT source_path FROM indexed_files WHERE source_id = ?", (source_id,)
                ).fetchall() if row[0] not in observed]
                obsolete_symbols = [(source_id, row[0]) for row in conn.execute(
                    "SELECT DISTINCT source_path FROM symbols WHERE source_id = ?", (source_id,)
                ).fetchall() if row[0] not in observed]
                conn.executemany("DELETE FROM symbols WHERE source_id = ? AND source_path = ?", obsolete_symbols)
                conn.executemany("DELETE FROM indexed_files WHERE source_id = ? AND source_path = ?", removed)
            conn.executemany(
                """
                INSERT OR REPLACE INTO indexed_files (
                    file_id, source_id, source_path, relative_path, content_hash, indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.file_id,
                        item.source_id,
                        item.source_path,
                        item.relative_path,
                        item.content_hash,
                        item.indexed_at,
                    )
                    for item in files
                ],
            )
            conn.executemany(
                "DELETE FROM symbols WHERE source_id = ? AND source_path = ?",
                [(source_id, source_path) for source_path in symbols_by_path],
            )
            conn.executemany(
                """
                INSERT INTO symbols (
                    symbol_id, source_id, source_path, relative_path, name, kind,
                    start_line, end_line, signature, excerpt, content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        symbol.symbol_id,
                        symbol.source_id,
                        symbol.source_path,
                        symbol.relative_path,
                        symbol.name,
                        symbol.kind,
                        symbol.start_line,
                        symbol.end_line,
                        symbol.signature,
                        symbol.excerpt,
                        symbol.content_hash,
                    )
                    for symbols in symbols_by_path.values()
                    for symbol in symbols
                ],
            )
        return len(removed)

    def replace_symbols_for_file(
        self,
        *,
        source_id: str,
        source_path: str,
        symbols: list[SymbolRecord],
    ) -> None:
        """Replace symbol entries for one file atomically."""

        with self._connect() as conn:
            conn.execute(
                "DELETE FROM symbols WHERE source_id = ? AND source_path = ?",
                (source_id, source_path),
            )
            conn.executemany(
                """
                INSERT INTO symbols (
                    symbol_id, source_id, source_path, relative_path, name, kind,
                    start_line, end_line, signature, excerpt, content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        symbol.symbol_id,
                        symbol.source_id,
                        symbol.source_path,
                        symbol.relative_path,
                        symbol.name,
                        symbol.kind,
                        symbol.start_line,
                        symbol.end_line,
                        symbol.signature,
                        symbol.excerpt,
                        symbol.content_hash,
                    )
                    for symbol in symbols
                ],
            )

    def search_symbols(self, query: str, *, limit: int = 20) -> list[SymbolRecord]:
        """Search symbols by exact or substring match."""

        normalized = query.strip()
        if not normalized:
            return []
        like = f"%{normalized}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol_id, source_id, source_path, relative_path, name, kind,
                       start_line, end_line, signature, excerpt, content_hash
                FROM symbols
                WHERE name = ? OR name LIKE ? OR signature LIKE ? OR relative_path LIKE ?
                ORDER BY
                    CASE WHEN name = ? THEN 0 ELSE 1 END,
                    relative_path,
                    start_line
                LIMIT ?
                """,
                (normalized, like, like, like, normalized, limit),
            ).fetchall()
        return [SymbolRecord(**dict(row)) for row in rows]

    def count_symbols(self) -> int:
        """Return total indexed symbols."""

        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0])

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indexed_files (
                    file_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    UNIQUE(source_id, source_path)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbols (
                    symbol_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    source_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    mtime TEXT,
                    status TEXT NOT NULL CHECK(status IN ('building', 'stable', 'failed', 'skipped')),
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, source_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    raw_text_hash TEXT NOT NULL,
                    canonical_text_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    collection_id TEXT NOT NULL,
                    index_version TEXT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    text_for_retrieval TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (collection_id, index_version, chunk_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_versions (
                    collection_id TEXT NOT NULL,
                    index_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('building', 'stable', 'failed')),
                    source_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    source_files_json TEXT,
                    PRIMARY KEY (collection_id, index_version)
                )
                """
            )
            if "source_files_json" not in {row[1] for row in conn.execute("PRAGMA table_info(index_versions)")}:
                conn.execute("ALTER TABLE index_versions ADD COLUMN source_files_json TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bm25_terms (
                    collection_id TEXT NOT NULL,
                    index_version TEXT NOT NULL,
                    term TEXT NOT NULL,
                    doc_freq INTEGER NOT NULL,
                    PRIMARY KEY (collection_id, index_version, term)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bm25_postings (
                    collection_id TEXT NOT NULL,
                    index_version TEXT NOT NULL,
                    term TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    term_freq INTEGER NOT NULL,
                    PRIMARY KEY (collection_id, index_version, term, chunk_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_index (
                    collection_id TEXT NOT NULL,
                    index_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    symbol_kind TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    start_line INTEGER,
                    end_line INTEGER,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY (
                        collection_id, index_version, symbol, symbol_kind, chunk_id
                    )
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(relative_path)"
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_version
                ON knowledge_chunks(collection_id, index_version)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_index_versions_stable
                ON index_versions(collection_id, status, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bm25_postings_chunk
                ON bm25_postings(collection_id, index_version, chunk_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_symbol_index_symbol
                ON symbol_index(collection_id, index_version, symbol, symbol_kind)
                """
            )

    def _write_index_version(
        self,
        *,
        collection_id: str,
        index_version: str,
        status: str,
        source_count: int,
        chunk_count: int,
        created_at: str,
        source_files: dict[str, dict[str, str]] | None = None,
    ) -> IndexVersion:
        self._validate_status(status, {"building", "stable", "failed"})
        with self._connect() as conn:
            previous = conn.execute(
                "SELECT source_files_json FROM index_versions WHERE collection_id = ? AND index_version = ?",
                (collection_id, index_version),
            ).fetchone()
            source_files_json = (json.dumps(source_files, sort_keys=True) if source_files is not None
                                 else previous[0] if previous is not None else None)
            conn.execute(
                """
                INSERT OR REPLACE INTO index_versions (
                    collection_id, index_version, status, source_count, chunk_count, created_at, source_files_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_id,
                    index_version,
                    status,
                    source_count,
                    chunk_count,
                    created_at,
                    source_files_json,
                ),
            )
        return IndexVersion(
            collection_id=collection_id,
            index_version=index_version,
            status=status,
            source_count=source_count,
            chunk_count=chunk_count,
            created_at=created_at,
        )

    @staticmethod
    def _source_snapshot_from_row(row: sqlite3.Row) -> KnowledgeSourceSnapshot:
        return KnowledgeSourceSnapshot(
            source_id=row["source_id"],
            collection_id=row["collection_id"],
            source_path=row["source_path"],
            source_type=row["source_type"],
            content_hash=row["content_hash"],
            mtime=row["mtime"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _document_record_from_row(row: sqlite3.Row) -> KnowledgeDocumentRecord:
        return KnowledgeDocumentRecord(
            document_id=row["document_id"],
            source_id=row["source_id"],
            raw_text_hash=row["raw_text_hash"],
            canonical_text_hash=row["canonical_text_hash"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _chunk_record_from_row(row: sqlite3.Row) -> KnowledgeChunkRecord:
        return KnowledgeChunkRecord(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            collection_id=row["collection_id"],
            index_version=row["index_version"],
            chunk_text=row["chunk_text"],
            text_for_retrieval=row["text_for_retrieval"],
            content_hash=row["content_hash"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _index_version_from_row(row: sqlite3.Row) -> IndexVersion:
        return IndexVersion(
            collection_id=row["collection_id"],
            index_version=row["index_version"],
            status=row["status"],
            source_count=int(row["source_count"]),
            chunk_count=int(row["chunk_count"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _symbol_index_entry_from_row(row: sqlite3.Row) -> SymbolIndexEntry:
        return SymbolIndexEntry(
            collection_id=row["collection_id"],
            index_version=row["index_version"],
            symbol=row["symbol"],
            symbol_kind=row["symbol_kind"],
            chunk_id=row["chunk_id"],
            source_path=row["source_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def _validate_document_identity(self, document: Document) -> None:
        metadata = document.metadata
        missing = sorted(field for field in DOCUMENT_IDENTITY_FIELDS if field not in metadata)
        if missing:
            raise KnowledgeDatabaseError(
                f"Document {document.document_id!r} missing identity fields: {missing}"
            )
        metadata_document_id = self._required_metadata(metadata, "document_id")
        if metadata_document_id != document.document_id:
            raise KnowledgeDatabaseError(
                "Document metadata document_id must match document.document_id"
            )
        file_hash = self._required_metadata(metadata, "file_hash")
        source_hash = self._required_metadata(metadata, "source_hash")
        content_hash = self._required_metadata(metadata, "content_hash")
        doc_hash = self._required_metadata(metadata, "doc_hash")
        canonical_text_hash = self._required_metadata(metadata, "canonical_text_hash")
        if source_hash != file_hash:
            raise KnowledgeDatabaseError("Document source_hash must equal file_hash")
        if content_hash != file_hash:
            raise KnowledgeDatabaseError("Document content_hash must equal file_hash")
        if doc_hash != canonical_text_hash:
            raise KnowledgeDatabaseError("Document doc_hash must equal canonical_text_hash")

    def _validate_chunk_identity(self, chunk: Chunk) -> None:
        metadata = chunk.metadata
        missing = sorted(field for field in CHUNK_IDENTITY_FIELDS if field not in metadata)
        if missing:
            raise KnowledgeDatabaseError(
                f"Chunk {chunk.chunk_id!r} missing identity fields: {missing}"
            )
        metadata_chunk_id = self._required_metadata(metadata, "chunk_id")
        metadata_document_id = self._required_metadata(metadata, "document_id")
        source_ref = self._required_metadata(metadata, "source_ref")
        file_hash = self._required_metadata(metadata, "file_hash")
        source_hash = self._required_metadata(metadata, "source_hash")
        if metadata_chunk_id != chunk.chunk_id:
            raise KnowledgeDatabaseError(
                "Chunk metadata chunk_id must match chunk.chunk_id"
            )
        if metadata_document_id != chunk.document_id:
            raise KnowledgeDatabaseError(
                "Chunk metadata document_id must match chunk.document_id"
            )
        if source_ref != chunk.document_id:
            raise KnowledgeDatabaseError("Chunk source_ref must equal document_id")
        if source_hash != file_hash:
            raise KnowledgeDatabaseError("Chunk source_hash must equal file_hash")

    @staticmethod
    def _required_metadata(metadata: dict[str, Any], key: str) -> str:
        value = metadata.get(key)
        if value is None:
            raise KnowledgeDatabaseError(f"Missing required metadata field: {key}")
        return str(value)

    @staticmethod
    def _validate_status(status: str, allowed: set[str]) -> None:
        if status not in allowed:
            raise KnowledgeDatabaseError(f"Unsupported status: {status!r}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
