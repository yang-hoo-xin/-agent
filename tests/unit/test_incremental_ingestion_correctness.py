"""Real local Chroma/BM25/SQLite replacement behavior with offline embeddings."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.types import Document
from src.ingestion.pipeline import IngestionPipeline


class CountingEmbedding:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts, trace=None):
        self.calls.append(list(texts))
        return [[float(len(text) % 7), float(index + 1), 1.0]
                for index, text in enumerate(texts)]


def _pipeline_factory(tmp_path, monkeypatch):
    import src.ingestion.pipeline as module

    embeddings: dict[str, CountingEmbedding] = {}

    class Loader:
        def __init__(self, *, extract_images, image_storage_dir, image_id_namespace=None):
            self.namespace = image_id_namespace

        def load(self, path):
            raw = Path(path).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            return Document(id="doc_" + digest[:16], text=raw.decode("utf-8"), metadata={
                "source_path": str(Path(path)), "doc_hash": digest, "title": "Incremental fixture",
                "images": [],
            })

    settings = SimpleNamespace(
        ingestion=SimpleNamespace(splitter="recursive", chunk_size=48, chunk_overlap=0, batch_size=100,
            chunk_refiner={"use_llm": False}, metadata_enricher={"use_llm": False}),
        vector_store=SimpleNamespace(provider="chroma", persist_directory=str(tmp_path / "chroma")),
        embedding=SimpleNamespace(provider="offline"), vision_llm=None,
        storage_root=str(tmp_path),
    )
    monkeypatch.setattr(module, "PdfLoader", Loader)

    def make(collection: str) -> IngestionPipeline:
        embedding = CountingEmbedding()
        embeddings[collection] = embedding
        monkeypatch.setattr(module.EmbeddingFactory, "create", lambda _settings: embedding)
        return IngestionPipeline(settings, collection=collection)

    return make, embeddings


def _stored(pipeline: IngestionPipeline, source: Path) -> dict:
    return pipeline.vector_upserter.vector_store.collection.get(
        where={"source_path": str(source)}, include=["metadatas", "documents"])


def _history_rows(pipeline: IngestionPipeline, source: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(pipeline.integrity_checker.db_path) as connection:
        return connection.execute(
            "SELECT file_hash,status FROM ingestion_history WHERE file_path = ? AND collection = ? "
            "ORDER BY processed_at", (str(source), pipeline.collection)).fetchall()


def test_unchanged_file_second_submission_skips_embedding_and_keeps_entities(tmp_path, monkeypatch):
    make, embeddings = _pipeline_factory(tmp_path, monkeypatch)
    pipeline = make("alpha")
    source = tmp_path / "document.pdf"
    source.write_text("stabletoken " * 20, encoding="utf-8")

    first = pipeline.run(str(source))
    calls_after_first = len(embeddings["alpha"].calls)
    second = pipeline.run(str(source))

    assert first.success and second.success and second.stages["integrity"]["skipped"] is True
    assert first.stages["integrity"]["incremental_action"] == "append_new_source_path"
    assert second.stages["integrity"]["incremental_action"] == "unchanged_skip"
    assert len(embeddings["alpha"].calls) == calls_after_first
    assert set(_stored(pipeline, source)["ids"]) == set(first.vector_ids)
    assert {row["chunk_id"] for row in pipeline.bm25_indexer.query(["stabletoken"], top_k=100)} == set(first.vector_ids)


def test_new_source_path_appends_without_replacing_existing_document(tmp_path, monkeypatch):
    make, _ = _pipeline_factory(tmp_path, monkeypatch)
    pipeline = make("alpha")
    first_source, second_source = tmp_path / "first.pdf", tmp_path / "second.pdf"
    first_source.write_text("firsttoken " * 20, encoding="utf-8")
    second_source.write_text("secondtoken " * 20, encoding="utf-8")

    first = pipeline.run(str(first_source))
    second = pipeline.run(str(second_source))

    assert first.success and second.success
    assert first.stages["integrity"]["incremental_action"] == "append_new_source_path"
    assert second.stages["integrity"]["incremental_action"] == "append_new_source_path"
    assert set(_stored(pipeline, first_source)["ids"]) == set(first.vector_ids)
    assert set(_stored(pipeline, second_source)["ids"]) == set(second.vector_ids)
    assert {row["chunk_id"] for row in pipeline.bm25_indexer.query(["firsttoken"], top_k=100)} == set(first.vector_ids)
    assert {row["chunk_id"] for row in pipeline.bm25_indexer.query(["secondtoken"], top_k=100)} == set(second.vector_ids)


def test_same_source_path_replaces_old_chroma_and_bm25_version(tmp_path, monkeypatch):
    make, _ = _pipeline_factory(tmp_path, monkeypatch)
    pipeline = make("alpha")
    source = tmp_path / "document.pdf"
    source.write_text("oldtoken " * 20, encoding="utf-8")
    first = pipeline.run(str(source))
    old_hash = first.doc_id

    source.write_text("newtoken " * 20, encoding="utf-8")
    second = pipeline.run(str(source))
    stored = _stored(pipeline, source)

    assert second.success and old_hash != second.doc_id
    assert second.stages["integrity"]["incremental_action"] == "replace_source_path"
    assert second.stages["storage"]["stale_vectors_deleted"] == len(set(first.vector_ids) - set(second.vector_ids))
    assert set(stored["ids"]) == set(second.vector_ids)
    assert {row["doc_hash"] for row in stored["metadatas"]} == {second.doc_id}
    assert not pipeline.bm25_indexer.query(["oldtoken"], top_k=100)
    assert {row["chunk_id"] for row in pipeline.bm25_indexer.query(["newtoken"], top_k=100)} == set(second.vector_ids)
    assert not pipeline.integrity_checker.should_skip(old_hash, "alpha")
    assert pipeline.integrity_checker.should_skip(second.doc_id, "alpha")


def test_shorter_replacement_removes_old_tail_chunks_from_both_indexes(tmp_path, monkeypatch):
    make, _ = _pipeline_factory(tmp_path, monkeypatch)
    pipeline = make("alpha")
    source = tmp_path / "document.pdf"
    source.write_text(("sharedtoken " * 20) + ("obsoletetail " * 30), encoding="utf-8")
    first = pipeline.run(str(source))
    assert first.chunk_count > 2

    source.write_text("sharedtoken shortversion", encoding="utf-8")
    second = pipeline.run(str(source))
    stored_ids = set(_stored(pipeline, source)["ids"])

    assert second.success and second.chunk_count < first.chunk_count
    assert stored_ids == set(second.vector_ids)
    assert not (set(first.vector_ids) - set(second.vector_ids)) & stored_ids
    assert not pipeline.bm25_indexer.query(["obsoletetail"], top_k=100)
    assert {row["chunk_id"] for row in pipeline.bm25_indexer.query(["shortversion"], top_k=100)} == set(second.vector_ids)


@pytest.mark.parametrize("failure", ["chroma", "bm25"])
def test_mid_replacement_failure_invalidates_history_and_retry_converges(tmp_path, monkeypatch, failure):
    make, _ = _pipeline_factory(tmp_path, monkeypatch)
    pipeline = make("alpha")
    source = tmp_path / "document.pdf"
    source.write_text("oldtoken " * 30, encoding="utf-8")
    first = pipeline.run(str(source))
    assert first.success
    source.write_text("newtoken " * 30, encoding="utf-8")

    if failure == "chroma":
        collection = pipeline.vector_upserter.vector_store.collection
        original = collection.upsert

        def partial_then_fail(*, ids, embeddings, metadatas, documents):
            original(ids=ids[:1], embeddings=embeddings[:1], metadatas=metadatas[:1], documents=documents[:1])
            raise OSError("injected Chroma replacement failure")

        monkeypatch.setattr(collection, "upsert", partial_then_fail)
    else:
        monkeypatch.setattr(pipeline.bm25_indexer, "replace_documents",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("injected BM25 replacement failure")),
            raising=False)

    failed = pipeline.run(str(source))
    assert not failed.success
    assert all(status != "success" for _, status in _history_rows(pipeline, source))

    monkeypatch.undo()
    # Restore fixture patches removed by undo before creating the retry pipeline.
    make, _ = _pipeline_factory(tmp_path, monkeypatch)
    retry = make("alpha")
    recovered = retry.run(str(source))
    stored = _stored(retry, source)
    assert recovered.success
    assert recovered.stages["integrity"]["incremental_action"] == "replace_source_path"
    assert set(stored["ids"]) == set(recovered.vector_ids)
    assert {row["doc_hash"] for row in stored["metadatas"]} == {recovered.doc_id}
    assert not retry.bm25_indexer.query(["oldtoken"], top_k=100)
    assert {row["chunk_id"] for row in retry.bm25_indexer.query(["newtoken"], top_k=100)} == set(recovered.vector_ids)


def test_same_path_updates_are_isolated_between_collections(tmp_path, monkeypatch):
    make, _ = _pipeline_factory(tmp_path, monkeypatch)
    alpha, beta = make("alpha"), make("beta")
    source = tmp_path / "document.pdf"
    source.write_text("sharedold " * 20, encoding="utf-8")
    alpha_old = alpha.run(str(source))
    beta_old = beta.run(str(source))
    assert alpha_old.success and beta_old.success

    source.write_text("alphaonly " * 20, encoding="utf-8")
    alpha_new = alpha.run(str(source))
    assert alpha_new.success
    assert set(_stored(alpha, source)["ids"]) == set(alpha_new.vector_ids)
    assert set(_stored(beta, source)["ids"]) == set(beta_old.vector_ids)
    assert beta.bm25_indexer.query(["sharedold"], top_k=100)

    source.write_text("betaonly " * 20, encoding="utf-8")
    beta_new = beta.run(str(source))
    assert beta_new.success
    assert set(_stored(alpha, source)["ids"]) == set(alpha_new.vector_ids)
    assert alpha.bm25_indexer.query(["alphaonly"], top_k=100)
    assert set(_stored(beta, source)["ids"]) == set(beta_new.vector_ids)
    assert beta.bm25_indexer.query(["betaonly"], top_k=100)
    assert not beta.bm25_indexer.query(["sharedold"], top_k=100)
