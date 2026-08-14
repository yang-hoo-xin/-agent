"""Deterministic symbol extraction for source-like knowledge files."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .database import KnowledgeDatabase
from .models import (
    KnowledgeChunkRecord,
    SymbolIndexEntry,
    SymbolIndexResult,
    SymbolRecord,
)

_CS_TYPE_RE = re.compile(r"\b(class|interface|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
_CS_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected|internal|static|virtual|override|async|sealed|partial|\s)+"
    r"[\w<>\[\],.?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
_PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)")
_PY_FUNCTION_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


class SymbolIndexer:
    """Extract a small deterministic symbol index from text files."""

    def index_chunks(
        self,
        database: KnowledgeDatabase,
        *,
        collection_id: str,
        index_version: str,
        chunks: list[KnowledgeChunkRecord] | None = None,
    ) -> SymbolIndexResult:
        """Replace chunk-bound symbol rows for one index version."""

        indexed_chunks = chunks
        if indexed_chunks is None:
            indexed_chunks = database.list_chunks(
                collection_id=collection_id,
                index_version=index_version,
            )
        entries_by_identity: dict[
            tuple[str, str, str, str, str], SymbolIndexEntry
        ] = {}
        for chunk in indexed_chunks:
            for entry in self._entries_from_chunk(chunk):
                identity = (
                    entry.collection_id,
                    entry.index_version,
                    entry.symbol,
                    entry.symbol_kind,
                    entry.chunk_id,
                )
                entries_by_identity.setdefault(identity, entry)
        entries = list(entries_by_identity.values())
        database.replace_symbol_index(
            collection_id=collection_id,
            index_version=index_version,
            entries=entries,
        )
        return SymbolIndexResult(
            collection_id=collection_id,
            index_version=index_version,
            chunk_count=len(indexed_chunks),
            symbol_count=len(entries),
        )

    def search_chunk_symbols(
        self,
        database: KnowledgeDatabase,
        *,
        collection_id: str,
        index_version: str,
        symbol: str,
        symbol_kind: str | None = None,
        limit: int = 20,
    ) -> list[SymbolIndexEntry]:
        """Search chunk-bound symbols by exact name."""

        return database.search_symbol_index(
            collection_id=collection_id,
            index_version=index_version,
            symbol=symbol,
            symbol_kind=symbol_kind,
            limit=limit,
        )

    def extract(
        self,
        *,
        source_id: str,
        source_path: Path,
        relative_path: str,
        content: str,
        content_hash: str,
    ) -> list[SymbolRecord]:
        """Extract symbol declarations from a supported source file."""

        suffix = source_path.suffix.lower()
        if suffix == ".cs":
            return self._extract_csharp(
                source_id=source_id,
                source_path=source_path,
                relative_path=relative_path,
                content=content,
                content_hash=content_hash,
            )
        if suffix == ".py":
            return self._extract_python(
                source_id=source_id,
                source_path=source_path,
                relative_path=relative_path,
                content=content,
                content_hash=content_hash,
            )
        return []

    @staticmethod
    def _entries_from_chunk(chunk: KnowledgeChunkRecord) -> list[SymbolIndexEntry]:
        raw_symbols = chunk.metadata.get("symbols", [])
        if not isinstance(raw_symbols, list):
            return []
        entries: list[SymbolIndexEntry] = []
        source_path = str(chunk.metadata.get("source_path", ""))
        start_line = chunk.metadata.get("start_line")
        end_line = chunk.metadata.get("end_line")
        symbol_kind = str(chunk.metadata.get("chunk_type", "symbol"))
        for raw_symbol in raw_symbols:
            if not isinstance(raw_symbol, str):
                continue
            symbol = raw_symbol.strip()
            if not symbol:
                continue
            entries.append(
                SymbolIndexEntry(
                    collection_id=chunk.collection_id,
                    index_version=chunk.index_version,
                    symbol=symbol,
                    symbol_kind=symbol_kind,
                    chunk_id=chunk.chunk_id,
                    source_path=source_path,
                    start_line=start_line if isinstance(start_line, int) else None,
                    end_line=end_line if isinstance(end_line, int) else None,
                    metadata={
                        **chunk.metadata,
                        "symbol": symbol,
                        "symbol_kind": symbol_kind,
                    },
                )
            )
        return entries

    def _extract_csharp(
        self,
        *,
        source_id: str,
        source_path: Path,
        relative_path: str,
        content: str,
        content_hash: str,
    ) -> list[SymbolRecord]:
        symbols: list[SymbolRecord] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            type_match = _CS_TYPE_RE.search(line)
            if type_match:
                symbols.append(
                    self._symbol(
                        source_id=source_id,
                        source_path=source_path,
                        relative_path=relative_path,
                        name=type_match.group(2),
                        kind=type_match.group(1),
                        line_number=line_number,
                        signature=line.strip(),
                        content_hash=content_hash,
                    )
                )
            method_match = _CS_METHOD_RE.search(line)
            if method_match and method_match.group(1) not in {"if", "for", "while", "switch"}:
                symbols.append(
                    self._symbol(
                        source_id=source_id,
                        source_path=source_path,
                        relative_path=relative_path,
                        name=method_match.group(1),
                        kind="method",
                        line_number=line_number,
                        signature=line.strip(),
                        content_hash=content_hash,
                    )
                )
        return symbols

    def _extract_python(
        self,
        *,
        source_id: str,
        source_path: Path,
        relative_path: str,
        content: str,
        content_hash: str,
    ) -> list[SymbolRecord]:
        symbols: list[SymbolRecord] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            class_match = _PY_CLASS_RE.search(line)
            if class_match:
                symbols.append(
                    self._symbol(
                        source_id=source_id,
                        source_path=source_path,
                        relative_path=relative_path,
                        name=class_match.group(1),
                        kind="class",
                        line_number=line_number,
                        signature=line.strip(),
                        content_hash=content_hash,
                    )
                )
            function_match = _PY_FUNCTION_RE.search(line)
            if function_match:
                symbols.append(
                    self._symbol(
                        source_id=source_id,
                        source_path=source_path,
                        relative_path=relative_path,
                        name=function_match.group(1),
                        kind="function",
                        line_number=line_number,
                        signature=line.strip(),
                        content_hash=content_hash,
                    )
                )
        return symbols

    @staticmethod
    def _symbol(
        *,
        source_id: str,
        source_path: Path,
        relative_path: str,
        name: str,
        kind: str,
        line_number: int,
        signature: str,
        content_hash: str,
    ) -> SymbolRecord:
        seed = f"{source_id}:{relative_path}:{kind}:{name}:{line_number}:{content_hash}"
        symbol_id = "sym_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return SymbolRecord(
            symbol_id=symbol_id,
            source_id=source_id,
            source_path=str(source_path.resolve()),
            relative_path=relative_path,
            name=name,
            kind=kind,
            start_line=line_number,
            end_line=line_number,
            signature=signature,
            excerpt=signature[:240],
            content_hash=content_hash,
        )
