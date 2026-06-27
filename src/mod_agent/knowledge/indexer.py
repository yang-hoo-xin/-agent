"""Incremental Knowledge Base indexing orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .database import KnowledgeDatabase
from .source_registry import SourceRegistry
from .symbol_indexer import SymbolIndexer


@dataclass(frozen=True)
class IndexingReport:
    """Structured result for one incremental indexing run."""

    source_id: str
    total_files: int
    indexed_files: int
    skipped_files: int
    failed_files: int
    symbols_indexed: int
    failures: tuple[str, ...] = ()

    def to_artifact_payload(self) -> dict[str, object]:
        """Return payload compatible with knowledge_index_report."""

        status_message = (
            f"Indexed {self.indexed_files} files, skipped {self.skipped_files}, "
            f"failed {self.failed_files}; {self.symbols_indexed} symbols available."
        )
        return {
            "node_name": "knowledge_indexer",
            "stage": "knowledge_index",
            "message": status_message,
            "source_id": self.source_id,
            "total_files": self.total_files,
            "indexed_files": self.indexed_files,
            "skipped_files": self.skipped_files,
            "failed_files": self.failed_files,
            "symbols_indexed": self.symbols_indexed,
            "failures": list(self.failures),
        }


class IncrementalIndexer:
    """Index changed files from a registered source root."""

    def __init__(
        self,
        *,
        database: KnowledgeDatabase,
        source_registry: SourceRegistry,
        symbol_indexer: SymbolIndexer | None = None,
    ) -> None:
        self.database = database
        self.source_registry = source_registry
        self.symbol_indexer = symbol_indexer or SymbolIndexer()

    def index_source(self, source_id: str) -> IndexingReport:
        """Index files whose content hash changed since the last run."""

        root = self.source_registry.source_root(source_id)
        files = self.source_registry.iter_files(source_id)
        indexed_files = 0
        skipped_files = 0
        failed_files = 0
        symbols_indexed = 0
        failures: list[str] = []

        for path in files:
            try:
                relative_path = path.relative_to(root).as_posix()
                content = path.read_text(encoding="utf-8")
                content_hash = self._sha256(content)
                existing = self.database.file_for_path(
                    source_id=source_id,
                    source_path=str(path),
                )
                if existing and existing.content_hash == content_hash:
                    skipped_files += 1
                    continue
                file_id = self._file_id(source_id, relative_path)
                self.database.upsert_file(
                    file_id=file_id,
                    source_id=source_id,
                    source_path=str(path),
                    relative_path=relative_path,
                    content_hash=content_hash,
                )
                symbols = self.symbol_indexer.extract(
                    source_id=source_id,
                    source_path=path,
                    relative_path=relative_path,
                    content=content,
                    content_hash=content_hash,
                )
                self.database.replace_symbols_for_file(
                    source_id=source_id,
                    source_path=str(path),
                    symbols=symbols,
                )
                indexed_files += 1
                symbols_indexed += len(symbols)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                failed_files += 1
                failures.append(f"{path}: {exc}")

        return IndexingReport(
            source_id=source_id,
            total_files=len(files),
            indexed_files=indexed_files,
            skipped_files=skipped_files,
            failed_files=failed_files,
            symbols_indexed=symbols_indexed,
            failures=tuple(failures),
        )

    @staticmethod
    def _sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _file_id(source_id: str, relative_path: str) -> str:
        seed = f"{source_id}:{relative_path}"
        return "file_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
