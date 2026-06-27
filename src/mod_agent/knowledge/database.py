"""SQLite-backed Knowledge Base for source, artifact, and log evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import IndexedFile, SourceRecord, SymbolRecord


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
                "CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(relative_path)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
