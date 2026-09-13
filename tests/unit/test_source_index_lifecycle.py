"""Source membership and physical-byte identity using isolated SQLite fixtures."""
from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.mod_agent.knowledge import IncrementalIndexer, KnowledgeDatabase, SourceDefinition, SourceRegistry, chunk_from_document


@pytest.fixture
def sources(tmp_path):
    database = KnowledgeDatabase(tmp_path / "knowledge.sqlite3")
    registry = SourceRegistry(database)
    paths = {}
    for source_id, name in (("one", "OldOne"), ("two", "OtherTwo")):
        root = tmp_path / source_id
        root.mkdir()
        path = root / "Subject.cs"
        path.write_bytes(f"public class {name} {{ }}\n".encode())
        registry.register(SourceDefinition(source_id=source_id, source_type="target_source", root_path=root,
                                           allowed_extensions=frozenset({".cs"})))
        paths[source_id] = path
    indexer = IncrementalIndexer(database=database, source_registry=registry)
    for source_id in paths:
        indexer.index_source(source_id)
    return database, registry, indexer, paths


def _stable_contents(database, version):
    chunks = database.list_chunks(collection_id=version.collection_id, index_version=version.index_version)
    return (database.get_index_version(collection_id=version.collection_id, index_version=version.index_version),
            chunks, [database.get_document(chunk.document_id) for chunk in chunks],
            database.search_symbol_index(collection_id=version.collection_id, index_version=version.index_version,
                                         symbol="OldOne"))


def test_complete_rescan_removes_deleted_current_file_and_symbols_but_keeps_other_source_and_history(sources):
    database, _, indexer, paths = sources
    old = indexer.build_retrieval_snapshot("one")
    old_contents = _stable_contents(database, old)
    other = database.list_indexed_files("two")
    paths["one"].unlink()
    report = indexer.index_source("one")
    assert report.failed_files == 0 and report.total_files == 0
    assert report.to_artifact_payload()["retrieval_snapshot_published"] is False
    assert database.list_indexed_files("one") == []
    assert database.search_symbols("OldOne") == []
    assert database.list_indexed_files("two") == other
    assert database.search_symbols("OtherTwo")
    assert database.stable_index_version("knowledge_hub") is None
    empty = indexer.build_retrieval_snapshot("one")
    assert empty.index_version != old.index_version and empty.chunk_count == 0 and empty.status == "stable"
    assert _stable_contents(database, old) == old_contents


def test_changed_source_snapshot_requires_reindex_before_touching_stable_data(sources):
    database, _, indexer, paths = sources
    old = indexer.build_retrieval_snapshot("one")
    old_contents = _stable_contents(database, old)
    paths["one"].write_bytes(b"public class NewOne { }\n")
    with pytest.raises(ValueError, match="reindex"):
        indexer.build_retrieval_snapshot("one")
    assert _stable_contents(database, old) == old_contents
    assert database.stable_index_version("knowledge_hub") == old
    indexer.index_source("one")
    new = indexer.build_retrieval_snapshot("one")
    assert new.index_version != old.index_version
    chunks = database.list_chunks(collection_id=new.collection_id, index_version=new.index_version)
    assert all("NewOne" in row.chunk_text and row.metadata["source_hash"] == hashlib.sha256(paths["one"].read_bytes()).hexdigest()
               for row in chunks)
    assert _stable_contents(database, old) == old_contents
    assert database.search_symbols("OldOne") == [] and database.search_symbols("NewOne")


def test_successful_unchanged_snapshot_does_not_republish_or_rewrite_its_stable_version(sources, monkeypatch):
    database, _, indexer, _ = sources
    original = indexer.build_retrieval_snapshot("one")
    before = _stable_contents(database, original)
    monkeypatch.setattr(database, "start_index_version", lambda **kwargs: pytest.fail("Stable version must not be reset to building."))
    assert indexer.build_retrieval_snapshot("one") == original
    assert _stable_contents(database, original) == before


@pytest.mark.parametrize("failure", ["read", "symbols"])
def test_read_and_symbol_failure_does_not_partially_update_or_prune_current_index(sources, monkeypatch, failure):
    database, _, indexer, paths = sources
    extra = paths["one"].with_name("Second.cs")
    extra.write_bytes(b"public class OldSecond { }\n")
    indexer.index_source("one")
    indexed_before = database.list_indexed_files("one")
    symbols_before = {item.source_path: database.symbols_for_file(source_id="one", source_path=item.source_path)
                      for item in indexed_before}
    paths["one"].write_bytes(b"public class ChangedOne { }\n")
    extra.write_bytes(b"public class ChangedSecond { }\n")
    if failure == "symbols":
        original_extract = indexer.symbol_indexer.extract
        def extract(**kwargs):
            if kwargs["source_path"] == paths["one"]:
                raise ValueError("partial parser failure")
            return original_extract(**kwargs)
        monkeypatch.setattr(indexer.symbol_indexer, "extract", extract)
    else:
        from pathlib import Path
        original_read = Path.read_bytes
        def read(path):
            if path == paths["one"]:
                raise PermissionError("file unavailable")
            return original_read(path)
        monkeypatch.setattr(Path, "read_bytes", read)
    report = indexer.index_source("one")
    assert report.failed_files == 1 and report.indexed_files == 0
    assert database.list_indexed_files("one") == indexed_before
    assert {item.source_path: database.symbols_for_file(source_id="one", source_path=item.source_path)
            for item in indexed_before} == symbols_before


def test_partial_directory_scan_error_is_not_an_empty_or_complete_source(sources, monkeypatch):
    import src.mod_agent.knowledge.source_discovery as discovery
    database, _, indexer, paths = sources
    before = database.list_indexed_files()
    error = PermissionError("unreadable subtree")
    def walk(root, *, onerror=None):
        yield str(root), [], []
        if onerror is not None:
            onerror(error)
    monkeypatch.setattr(discovery.os, "walk", walk)
    with pytest.raises(PermissionError) as caught:
        indexer.index_source("one")
    assert caught.value is error and database.list_indexed_files() == before
    assert database.search_symbols("OldOne")


def test_missing_registered_root_cannot_erase_its_last_index(sources):
    database, _, indexer, paths = sources
    before = database.list_indexed_files("one")
    paths["one"].unlink()
    paths["one"].parent.rmdir()
    with pytest.raises((OSError, ValueError)):
        indexer.index_source("one")
    assert database.list_indexed_files("one") == before


def test_added_file_and_changed_filter_require_explicit_index_refresh(sources):
    database, registry, indexer, paths = sources
    extra = paths["one"].with_name("Added.cs")
    extra.write_bytes(b"public class Added { }\n")
    with pytest.raises(ValueError, match="reindex"):
        indexer.build_retrieval_snapshot("one")
    indexer.index_source("one")
    assert len(database.list_indexed_files("one")) == 2
    registry.register(SourceDefinition(source_id="one", source_type="target_source", root_path=extra.parent,
                                       allowed_extensions=frozenset({".txt"})))
    indexer.index_source("one")
    assert database.list_indexed_files("one") == [] and database.search_symbols("Added") == []


def test_complete_scan_removes_orphan_current_symbols_from_same_source_only(sources):
    database, _, indexer, paths = sources
    original = database.symbols_for_file(source_id="one", source_path=str(paths["one"]))[0]
    orphan_path = str(paths["one"].with_name("PreviouslyDeleted.cs"))
    orphan = replace(original, symbol_id="orphan-symbol", source_path=orphan_path,
                     relative_path="PreviouslyDeleted.cs", name="OrphanSymbol")
    database.replace_symbols_for_file(source_id="one", source_path=orphan_path, symbols=[orphan])
    indexer.index_source("one")
    assert database.search_symbols("OrphanSymbol") == []
    assert database.search_symbols("OldOne") and database.search_symbols("OtherTwo")


def test_crlf_hash_is_bound_to_raw_file_bytes_and_snapshot_uses_those_same_bytes(sources):
    database, _, indexer, paths = sources
    raw = b"public class WindowsText\r\n{\r\n}\r\n"
    paths["one"].write_bytes(raw)
    indexer.index_source("one")
    assert database.list_indexed_files("one")[0].content_hash == hashlib.sha256(raw).hexdigest()
    version = indexer.build_retrieval_snapshot("one")
    chunk = database.list_chunks(collection_id=version.collection_id, index_version=version.index_version)[0]
    assert chunk.metadata["file_hash"] == chunk.metadata["source_hash"] == hashlib.sha256(raw).hexdigest()
    document = database.get_document(chunk.document_id)
    assert document.raw_text_hash == hashlib.sha256(raw).hexdigest()


def test_mixed_symbol_revision_cannot_pollute_stable_snapshot(sources):
    database, _, indexer, paths = sources
    old = indexer.build_retrieval_snapshot("one")
    before = _stable_contents(database, old)
    symbols = database.symbols_for_file(source_id="one", source_path=str(paths["one"]))
    database.replace_symbols_for_file(source_id="one", source_path=str(paths["one"]),
        symbols=[replace(symbol, content_hash="0" * 64) for symbol in symbols])
    with pytest.raises(ValueError, match="reindex"):
        indexer.build_retrieval_snapshot("one")
    assert _stable_contents(database, old) == before


def test_old_stable_bad_snapshot_is_preserved_and_new_strategy_builds_correct_version(sources):
    database, registry, indexer, _ = sources
    indexed = database.list_indexed_files("one")[0]
    old_seed = "\n".join(["bounded_source_chunks_v1", "one", f"one:{indexed.relative_path}:{indexed.content_hash}"])
    old_id = "idx_" + hashlib.sha256(old_seed.encode()).hexdigest()[:20]
    wrong = indexed.to_document(source=registry.source_record("one"), raw_text="public class UnindexedChange { }\n")
    old_chunk = chunk_from_document(wrong, chunk_index=0, text=wrong.canonical_text,
                                    chunk_strategy="bounded_source_chunks_v1")
    database.start_index_version(collection_id="knowledge_hub", index_version=old_id, source_count=1, chunk_count=1)
    database.upsert_documents([wrong])
    database.upsert_chunks([old_chunk], collection_id="knowledge_hub", index_version=old_id)
    old = database.set_index_version_status(collection_id="knowledge_hub", index_version=old_id, status="stable")
    before = _stable_contents(database, old)
    assert database.stable_index_version("knowledge_hub") is None
    correct = indexer.build_retrieval_snapshot("one")
    assert correct.index_version != old_id and correct.status == "stable"
    assert all("OldOne" in chunk.chunk_text for chunk in database.list_chunks(
        collection_id=correct.collection_id, index_version=correct.index_version))
    assert _stable_contents(database, old) == before


def test_current_retrieval_drops_deleted_evidence_before_and_after_publication(sources):
    from src.mod_agent.evidence import DeterministicEvidenceRetriever, EvidenceRequest
    database, _, indexer, paths = sources
    old = indexer.build_retrieval_snapshot("one")
    other = indexer.build_retrieval_snapshot("two", collection_id="other_collection")
    retriever = DeterministicEvidenceRetriever(database)
    request = EvidenceRequest(query="OldOne", source_ids=("one",), requires_hook_evidence=False)
    assert retriever.retrieve(request).items
    paths["one"].unlink()
    indexer.index_source("one")
    assert not retriever.retrieve(request).items
    assert database.get_index_version(collection_id=old.collection_id, index_version=old.index_version).status == "stable"
    assert database.list_chunks(collection_id=old.collection_id, index_version=old.index_version)
    assert database.stable_index_version("other_collection") == other
    published = indexer.build_retrieval_snapshot("one")
    assert published.chunk_count == 0 and database.stable_index_version("knowledge_hub") == published
    assert not retriever.retrieve(request).items


def test_failed_scan_does_not_invalidate_published_snapshot(sources, monkeypatch):
    import src.mod_agent.knowledge.source_discovery as discovery
    database, _, indexer, _ = sources
    published = indexer.build_retrieval_snapshot("one")
    def walk(root, *, onerror=None):
        onerror(PermissionError("scan unavailable"))
        yield
    monkeypatch.setattr(discovery.os, "walk", walk)
    with pytest.raises(PermissionError):
        indexer.index_source("one")
    assert database.stable_index_version("knowledge_hub") == published


def test_source_reversion_can_select_preserved_matching_snapshot(sources):
    database, _, indexer, paths = sources
    original_bytes = paths["one"].read_bytes()
    original = indexer.build_retrieval_snapshot("one")
    paths["one"].write_bytes(b"public class Revised { }\n")
    indexer.index_source("one")
    revised = indexer.build_retrieval_snapshot("one")
    assert revised != original
    paths["one"].write_bytes(original_bytes)
    indexer.index_source("one")
    assert indexer.build_retrieval_snapshot("one") == original
    assert database.stable_index_version("knowledge_hub") == original


def test_existing_sqlite_version_rows_gain_optional_provenance_without_rewriting_history(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    original = ("legacy_collection", "legacy_empty", "stable", 1, 0, "2026-01-01T00:00:00+00:00")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE index_versions (collection_id TEXT, index_version TEXT, status TEXT, "
            "source_count INTEGER, chunk_count INTEGER, created_at TEXT, PRIMARY KEY(collection_id,index_version))")
        connection.execute("INSERT INTO index_versions VALUES (?,?,?,?,?,?)", original)
    database = KnowledgeDatabase(path)
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT collection_id,index_version,status,source_count,chunk_count,created_at,source_files_json "
                                 "FROM index_versions").fetchone()
    assert row[:6] == original and row[6] is None
    # No source is invented for an old empty snapshot with no provenance.
    assert database.get_index_version(collection_id=original[0], index_version=original[1]).status == "stable"
