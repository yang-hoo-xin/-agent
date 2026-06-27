"""Tests for Phase C Knowledge Base primitives."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)


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
