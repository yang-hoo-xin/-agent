"""Incremental Knowledge Base indexing orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .bm25_indexer import BM25Indexer
from .database import KnowledgeDatabase
from .models import IndexVersion, IndexedFile, SourceSpan, chunk_from_document
from .source_registry import SourceRegistry
from .symbol_indexer import SymbolIndexer

RETRIEVAL_SNAPSHOT_VERSION = "bounded_source_chunks_v1"


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
        indexed_at = datetime.now(timezone.utc).isoformat()
        existing_by_path = {
            item.source_path: item for item in self.database.list_indexed_files(source_id)
        }
        changed_files: list[IndexedFile] = []
        symbols_by_path = {}

        for path in files:
            try:
                relative_path = path.relative_to(root).as_posix()
                content = path.read_text(encoding="utf-8")
                content_hash = self._sha256(content)
                existing = existing_by_path.get(str(path))
                if existing and existing.content_hash == content_hash:
                    skipped_files += 1
                    continue
                file_id = self._file_id(source_id, relative_path)
                changed_files.append(IndexedFile(
                    file_id=file_id,
                    source_id=source_id,
                    source_path=str(path),
                    relative_path=relative_path,
                    content_hash=content_hash,
                    indexed_at=indexed_at,
                ))
                symbols = self.symbol_indexer.extract(
                    source_id=source_id,
                    source_path=path,
                    relative_path=relative_path,
                    content=content,
                    content_hash=content_hash,
                )
                symbols_by_path[str(path)] = symbols
                indexed_files += 1
                symbols_indexed += len(symbols)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                failed_files += 1
                failures.append(f"{path}: {exc}")

        self.database.replace_indexed_source_files(
            source_id=source_id,
            files=changed_files,
            symbols_by_path=symbols_by_path,
        )

        return IndexingReport(
            source_id=source_id,
            total_files=len(files),
            indexed_files=indexed_files,
            skipped_files=skipped_files,
            failed_files=failed_files,
            symbols_indexed=symbols_indexed,
            failures=tuple(failures),
        )

    def build_retrieval_snapshot(
        self,
        source_ids: str | tuple[str, ...],
        *,
        collection_id: str = "knowledge_hub",
    ) -> IndexVersion:
        """Build a stable BM25/symbol snapshot from the indexed source bytes."""

        requested_source_ids = (
            (source_ids,) if isinstance(source_ids, str) else tuple(source_ids)
        )
        if not requested_source_ids or len(set(requested_source_ids)) != len(
            requested_source_ids
        ):
            raise ValueError("Retrieval snapshot requires unique source ids.")
        sources = {
            source_id: self.source_registry.source_record(source_id)
            for source_id in requested_source_ids
        }
        files_by_source = {
            source_id: self.database.list_indexed_files(source_id)
            for source_id in requested_source_ids
        }
        missing = [
            source_id for source_id, files in files_by_source.items() if not files
        ]
        if missing:
            raise ValueError(f"Sources have no indexed files: {', '.join(missing)}")
        version_seed = "\n".join(
            [
                RETRIEVAL_SNAPSHOT_VERSION,
                *requested_source_ids,
                *(
                    f"{source_id}:{item.relative_path}:{item.content_hash}"
                    for source_id in requested_source_ids
                    for item in files_by_source[source_id]
                ),
            ]
        )
        index_version = "idx_" + hashlib.sha256(
            version_seed.encode("utf-8")
        ).hexdigest()[:20]
        documents = []
        chunks = []
        for source_id in requested_source_ids:
            source = sources[source_id]
            for indexed_file in files_by_source[source_id]:
                path = Path(indexed_file.source_path)
                raw_text = path.read_text(encoding="utf-8")
                document = indexed_file.to_document(source=source, raw_text=raw_text)
                documents.append(document)
                for chunk_index, (text, span) in enumerate(
                    self._bounded_chunks(path=path, text=document.canonical_text)
                ):
                    chunks.append(
                        chunk_from_document(
                            document,
                            chunk_index=chunk_index,
                            text=text,
                            text_for_retrieval=text,
                            source_span=span,
                            chunk_type=("code_window" if path.suffix.lower() in {".cs", ".py"} else "text_window"),
                            chunk_strategy=RETRIEVAL_SNAPSHOT_VERSION,
                            symbols=tuple(
                                symbol.name
                                for symbol in self.database.symbols_for_file(
                                    source_id=source_id,
                                    source_path=indexed_file.source_path,
                                )
                                if span.start_line <= symbol.start_line <= span.end_line
                            ),
                        )
                    )
        self.database.start_index_version(
            collection_id=collection_id,
            index_version=index_version,
            source_count=len(requested_source_ids),
            chunk_count=len(chunks),
        )
        self.database.upsert_documents(documents)
        records = self.database.upsert_chunks(
            chunks,
            collection_id=collection_id,
            index_version=index_version,
        )
        BM25Indexer(self.database).index(
            collection_id=collection_id,
            index_version=index_version,
            chunks=records,
        )
        self.symbol_indexer.index_chunks(
            self.database,
            collection_id=collection_id,
            index_version=index_version,
            chunks=records,
        )
        return self.database.set_index_version_status(
            collection_id=collection_id,
            index_version=index_version,
            status="stable",
        )

    @staticmethod
    def _bounded_chunks(
        *,
        path: Path,
        text: str,
    ) -> list[tuple[str, SourceSpan]]:
        lines = text.splitlines()
        if not lines:
            return [("", SourceSpan(start_line=1, end_line=1))]
        if path.suffix.lower() in {".cs", ".py"}:
            window_lines = 80
            overlap_lines = 10
        else:
            window_lines = 120
            overlap_lines = 10
        chunks: list[tuple[str, SourceSpan]] = []
        start = 0
        while start < len(lines):
            end = min(len(lines), start + window_lines)
            chunks.append(
                (
                    "\n".join(lines[start:end]),
                    SourceSpan(start_line=start + 1, end_line=end),
                )
            )
            if end == len(lines):
                break
            start = end - overlap_lines
        return chunks

    @staticmethod
    def _sha256(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _file_id(source_id: str, relative_path: str) -> str:
        seed = f"{source_id}:{relative_path}"
        return "file_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
