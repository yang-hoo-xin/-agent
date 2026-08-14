"""Tests for Phase C Knowledge Base primitives."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.knowledge import (
    BM25Indexer,
    Chunk,
    IndexedFile,
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceRecord,
    SourceDefinition,
    SourceRegistry,
    chunk_from_document,
)
from src.mod_agent.knowledge.database import KnowledgeDatabaseError


def _write_plugin(root: Path, body: str | None = None) -> Path:
    source = root / "Plugin.cs"
    source.write_text(
        body
        or """
using BepInEx;

public class Plugin
{
    public void Load()
    {
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return source


def test_knowledge_database_creates_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.db"

    KnowledgeDatabase(db_path)

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"sources", "indexed_files", "symbols"}.issubset(tables)


def test_source_registry_persists_source_and_filters_files(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    _write_plugin(root)
    (root / "ignored.bin").write_bytes(b"\x00\x01")
    registry = SourceRegistry(db)

    source = registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )

    assert source.source_id == "target_mod"
    assert registry.list_sources()[0].root_path == str(root.resolve())
    assert [path.name for path in registry.iter_files("target_mod")] == ["Plugin.cs"]


def test_incremental_indexer_extracts_symbols_and_searches_exact_symbol(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    plugin = _write_plugin(root)
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )

    report = IncrementalIndexer(database=db, source_registry=registry).index_source(
        "target_mod"
    )
    results = db.search_symbols("Load")

    assert report.total_files == 1
    assert report.indexed_files == 1
    assert report.skipped_files == 0
    assert report.failed_files == 0
    assert report.symbols_indexed >= 2
    assert results[0].name == "Load"
    assert results[0].source_path == str(plugin.resolve())
    assert results[0].to_evidence_item()["symbol"] == "Load"


def test_incremental_indexer_builds_stable_retrieval_snapshot(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    _write_plugin(root)
    (root / "guide.md").write_text(
        "敌人进入踉跄反应时显示黄色标记。\n",
        encoding="utf-8",
    )
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="current_api",
            source_type="decompiled_api",
            root_path=root,
            metadata={"evidence_authority": "authoritative"},
            allowed_extensions=frozenset({".cs", ".md"}),
        )
    )
    indexer = IncrementalIndexer(database=db, source_registry=registry)
    indexer.index_source("current_api")

    first = indexer.build_retrieval_snapshot("current_api")
    second = indexer.build_retrieval_snapshot("current_api")

    assert first.status == "stable"
    assert second.index_version == first.index_version
    assert db.stable_index_version("knowledge_hub") == second
    assert db.list_chunks(
        collection_id="knowledge_hub",
        index_version=first.index_version,
    )
    assert db.search_symbol_index(
        collection_id="knowledge_hub",
        index_version=first.index_version,
        symbol="Load",
    )
    assert BM25Indexer(db).query(
        collection_id="knowledge_hub",
        index_version=first.index_version,
        tokens=["踉跄"],
        top_k=5,
    )


def test_retrieval_snapshot_deduplicates_overloads_in_one_chunk(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    (root / "Overloads.cs").write_text(
        "public class Overloads {\n"
        "    public void Apply(int value) {}\n"
        "    public void Apply(string value) {}\n"
        "}\n",
        encoding="utf-8",
    )
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="current_api",
            source_type="decompiled_api",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )
    indexer = IncrementalIndexer(database=db, source_registry=registry)
    indexer.index_source("current_api")

    snapshot = indexer.build_retrieval_snapshot("current_api")

    matches = db.search_symbol_index(
        collection_id="knowledge_hub",
        index_version=snapshot.index_version,
        symbol="Apply",
    )
    assert len(matches) == 1


def test_retrieval_snapshot_combines_registered_sources_once(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    registry = SourceRegistry(db)
    for source_id, text in (
        ("api_source", "public class EnemyMovement {}\n"),
        ("data_source", '{"area": 42}\n'),
    ):
        root = tmp_path / source_id
        root.mkdir()
        (root / ("source.cs" if source_id == "api_source" else "data.json")).write_text(
            text,
            encoding="utf-8",
        )
        registry.register(
            SourceDefinition(
                source_id=source_id,
                source_type=("decompiled_api" if source_id == "api_source" else "domain_note"),
                root_path=root,
                metadata={"evidence_authority": "authoritative"},
                allowed_extensions=frozenset({".cs", ".json"}),
            )
        )
    indexer = IncrementalIndexer(database=db, source_registry=registry)
    indexer.index_source("api_source")
    indexer.index_source("data_source")

    snapshot = indexer.build_retrieval_snapshot(("api_source", "data_source"))

    assert snapshot.source_count == 2
    chunks = db.list_chunks(
        collection_id="knowledge_hub",
        index_version=snapshot.index_version,
    )
    assert {chunk.metadata["source_id"] for chunk in chunks} == {
        "api_source",
        "data_source",
    }


def test_document_and_chunk_identity_mapping_is_explicit(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    source = SourceRecord(
        source_id="target_mod",
        source_type="target_source",
        root_path=str(tmp_path),
    )
    indexed_file = IndexedFile(
        file_id="file_001",
        source_id="target_mod",
        source_path=str(tmp_path / "Plugin.cs"),
        relative_path="Plugin.cs",
        content_hash="file_hash_001",
        indexed_at="2026-07-03T00:00:00+00:00",
    )

    document = indexed_file.to_document(source=source, raw_text="raw\r\ntext")
    chunk = chunk_from_document(document, text="chunk text", chunk_index=3)
    document_record = db.upsert_document(document)
    chunk_record = db.upsert_chunk(
        chunk,
        collection_id="knowledge_hub",
        index_version="v1",
    )

    assert document.metadata["file_hash"] == "file_hash_001"
    assert document.metadata["source_hash"] == "file_hash_001"
    assert document.metadata["doc_hash"] == document.metadata["canonical_text_hash"]
    assert document_record.metadata["document_id"] == document.document_id
    assert chunk.metadata["source_ref"] == document.document_id
    assert chunk.metadata["file_hash"] == "file_hash_001"
    assert chunk.metadata["source_hash"] == "file_hash_001"
    assert chunk.metadata["doc_hash"] == document.doc_hash
    assert chunk_record.document_id == document.document_id
    assert chunk_record.metadata["chunk_id"] == chunk.chunk_id


def test_chunk_identity_missing_source_ref_blocks_indexing(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")

    with pytest.raises(KnowledgeDatabaseError, match="missing identity fields"):
        db.upsert_chunk(
            Chunk(
                chunk_id="chunk_001",
                document_id="doc_001",
                text="chunk text",
                text_for_retrieval="chunk text",
                metadata={
                    "chunk_id": "chunk_001",
                    "document_id": "doc_001",
                    "content_hash": "chunk_hash_001",
                    "file_hash": "file_hash_001",
                    "source_hash": "file_hash_001",
                    "doc_hash": "doc_hash_001",
                },
            ),
            collection_id="knowledge_hub",
            index_version="v1",
        )


def test_incremental_indexer_skips_unchanged_files_and_reindexes_changed_file(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    plugin = _write_plugin(root)
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )
    indexer = IncrementalIndexer(database=db, source_registry=registry)

    first = indexer.index_source("target_mod")
    second = indexer.index_source("target_mod")
    plugin.write_text(
        """
public class Plugin
{
    public void Start()
    {
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    third = indexer.index_source("target_mod")

    assert first.indexed_files == 1
    assert second.indexed_files == 0
    assert second.skipped_files == 1
    assert third.indexed_files == 1
    assert [symbol.name for symbol in db.search_symbols("Start")] == ["Start"]
    assert db.search_symbols("Load") == []


def test_indexing_report_can_be_written_as_artifact(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    _write_plugin(root)
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )
    report = IncrementalIndexer(database=db, source_registry=registry).index_source(
        "target_mod"
    )
    store = ArtifactStore(tmp_path / "artifacts")

    ref = store.write(
        feature_id="feature_001",
        artifact_type="knowledge_index_report",
        payload=report.to_artifact_payload(),
    )

    envelope = store.read(ref)
    assert envelope["producer_stage"] == "knowledge_index"
    assert envelope["data"]["source_id"] == "target_mod"
    assert envelope["data"]["symbols_indexed"] >= 2
