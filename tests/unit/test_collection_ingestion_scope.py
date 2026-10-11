"""Collection isolation through real local stores and offline provider fixtures."""
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.types import Document
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.document_manager import DocumentManager
from src.ingestion.storage.bm25_indexer import BM25Indexer
from src.libs.loader.file_integrity import SQLiteIntegrityChecker


def _pipelines(tmp_path, monkeypatch):
    import src.ingestion.pipeline as module

    calls = []

    class Loader:
        def __init__(self, *, extract_images, image_storage_dir, image_id_namespace=None):
            self.root = Path(image_storage_dir)
            self.namespace = image_id_namespace

        def load(self, path):
            from src.libs.loader.pdf_loader import PdfLoader

            calls.append(self.namespace)
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            image_id = PdfLoader._generate_image_id(digest, 1, 1, namespace=self.namespace)
            image = self.root / (image_id + ".png")
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"local image bytes")
            text = "Collection document alpha beta. [IMAGE: " + image_id + "]"
            return Document(id="doc_" + digest[:16], text=text, metadata={
                "source_path": path, "doc_hash": digest, "title": "Collection document",
                "images": [{"id": image_id, "path": str(image), "page": 1,
                    "text_offset": text.index("[IMAGE:"), "text_length": len("[IMAGE: " + image_id + "]")}],
            })

    class Embedding:
        def embed(self, texts, trace=None):
            return [[1.0, 0.0, 0.0] for _ in texts]

    settings = SimpleNamespace(
        ingestion=SimpleNamespace(splitter="recursive", chunk_size=1000, chunk_overlap=0, batch_size=4,
            chunk_refiner={"use_llm": False}, metadata_enricher={"use_llm": False}),
        vector_store=SimpleNamespace(provider="chroma", persist_directory=str(tmp_path / "chroma")),
        embedding=SimpleNamespace(provider="offline"), vision_llm=None,
        storage_root=str(tmp_path),
    )
    monkeypatch.setattr(module, "PdfLoader", Loader)
    monkeypatch.setattr(module.EmbeddingFactory, "create", lambda _: Embedding())
    return tuple(IngestionPipeline(settings, collection=name) for name in ("scope-alpha", "scope-beta")), calls


def test_same_file_enters_two_real_collections_then_only_same_collection_skips(tmp_path, monkeypatch):
    (alpha, beta), calls = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    first = alpha.run(str(source))
    second = beta.run(str(source))
    repeated = alpha.run(str(source))
    assert first.success and second.success and repeated.success
    assert second.chunk_count > 0, "A success must not cause B to skip ingestion"
    assert repeated.stages["integrity"]["skipped"] is True
    assert len(calls) == 2
    assert alpha.vector_upserter.vector_store.collection.count() > 0
    assert beta.vector_upserter.vector_store.collection.count() > 0
    assert alpha.bm25_indexer.query(["collection"], top_k=2)
    assert beta.bm25_indexer.query(["collection"], top_k=2)
    alpha_images = alpha.image_storage.list_images(collection="scope-alpha")
    beta_images = beta.image_storage.list_images(collection="scope-beta")
    assert len(alpha_images) == len(beta_images) == 1
    assert alpha_images[0]["image_id"] != beta_images[0]["image_id"]
    assert alpha_images[0]["file_path"] != beta_images[0]["file_path"]
    assert Path(alpha_images[0]["file_path"]).read_bytes() == Path(beta_images[0]["file_path"]).read_bytes()


def test_real_collection_deletion_keeps_other_stores_and_success(tmp_path, monkeypatch):
    (alpha, beta), _ = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success and beta.run(str(source)).success
    digest = alpha.integrity_checker.compute_sha256(str(source))
    images_a = alpha.image_storage.list_images(collection="scope-alpha")
    images_b = beta.image_storage.list_images(collection="scope-beta")
    manager = DocumentManager(alpha.vector_upserter.vector_store, alpha.bm25_indexer,
        alpha.image_storage, alpha.integrity_checker)
    result = manager.delete_document(str(source), "scope-alpha", source_hash=digest)
    assert result.success, result.errors
    assert result.chunks_deleted > 0 and result.bm25_removed and result.images_deleted == 1
    assert not alpha.integrity_checker.should_skip(digest, collection="scope-alpha")
    assert beta.integrity_checker.should_skip(digest, collection="scope-beta")
    assert alpha.vector_upserter.vector_store.collection.count() == 0
    assert beta.vector_upserter.vector_store.collection.count() > 0
    assert json.loads(alpha.bm25_indexer._get_index_path("scope-alpha").read_text(encoding="utf-8"))["index"] == {}
    assert beta.bm25_indexer.query(["collection"], top_k=2)
    assert not Path(images_a[0]["file_path"]).exists()
    assert Path(images_b[0]["file_path"]).read_bytes() == b"local image bytes"


def test_failure_in_second_collection_never_changes_first_success(tmp_path, monkeypatch):
    (alpha, beta), _ = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success
    monkeypatch.setattr(beta.loader, "load", lambda _: (_ for _ in ()).throw(ValueError("failed only in B")))
    assert not beta.run(str(source)).success
    digest = alpha.integrity_checker.compute_sha256(str(source))
    assert alpha.integrity_checker.should_skip(digest, collection="scope-alpha")
    assert not beta.integrity_checker.should_skip(digest, collection="scope-beta")
    assert alpha.run(str(source)).stages["integrity"]["skipped"] is True
    with sqlite3.connect(alpha.integrity_checker.db_path) as connection:
        rows = connection.execute("SELECT collection, status FROM ingestion_history ORDER BY collection").fetchall()
    assert rows == [("scope-alpha", "success"), ("scope-beta", "failed")]


def test_legacy_sqlite_migration_preserves_named_empty_and_unknown_scopes(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE ingestion_history (
            file_hash TEXT PRIMARY KEY, file_path TEXT NOT NULL, status TEXT NOT NULL,
            collection TEXT, error_msg TEXT, processed_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        connection.execute("CREATE INDEX idx_status ON ingestion_history(status)")
        rows = [("named", "/named.pdf", "success", "scope-alpha", None, "old-created", "old-updated"),
                ("unknown", "/unknown.pdf", "success", None, None, "u-created", "u-updated"),
                ("empty", "/empty.pdf", "success", "", None, "e-created", "e-updated")]
        connection.executemany("INSERT INTO ingestion_history VALUES (?,?,?,?,?,?,?)", rows)
    checker = SQLiteIntegrityChecker(str(path))
    assert checker.should_skip("named", "scope-alpha")
    assert not checker.should_skip("named", "scope-beta")
    assert checker.should_skip("unknown", None)
    assert not checker.should_skip("unknown", "") and not checker.should_skip("unknown", "default")
    assert checker.should_skip("empty", "") and not checker.should_skip("empty", None)
    with sqlite3.connect(path) as connection:
        preserved = connection.execute("SELECT * FROM ingestion_history ORDER BY file_hash").fetchall()
    assert preserved == sorted(rows)
    checker.mark_success("named", "/named.pdf", "scope-beta")
    checker.mark_failed("named", "/named.pdf", "B failed", "scope-beta")
    assert checker.should_skip("named", "scope-alpha")
    assert checker.remove_record("named", "scope-beta")
    assert checker.should_skip("named", "scope-alpha")
    assert not checker.remove_record("named")
    reopened = SQLiteIntegrityChecker(str(path))
    assert reopened.should_skip("named", "scope-alpha")
    assert len(reopened.list_processed("scope-alpha")) == 1


def test_same_hash_named_empty_and_unknown_scopes_are_independent(tmp_path):
    checker = SQLiteIntegrityChecker(str(tmp_path / "history.db"))
    for scope in (None, "", "scope-alpha", "scope-beta"):
        checker.mark_success("same", "/same.pdf", scope)
    assert len(checker.list_processed()) == 4
    checker.mark_failed("same", "/same.pdf", "failure", "")
    assert checker.should_skip("same", None) and not checker.should_skip("same", "")
    assert checker.should_skip("same", "scope-alpha")
    checker.remove_record("same", "scope-beta")
    assert checker.should_skip("same", "scope-alpha")


def test_delete_scope_mismatch_or_unknown_ids_performs_no_cleanup(tmp_path, monkeypatch):
    (alpha, beta), _ = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success and beta.run(str(source)).success
    manager = DocumentManager(alpha.vector_upserter.vector_store, alpha.bm25_indexer,
        alpha.image_storage, alpha.integrity_checker)
    result = manager.delete_document(str(source), "scope-beta")
    assert not result.success and "collection" in result.errors[0]
    assert alpha.vector_upserter.vector_store.collection.count() > 0
    assert beta.vector_upserter.vector_store.collection.count() > 0
    unknown = manager.delete_document(str(source), "scope-alpha", source_hash="unknown hash")
    assert not unknown.success and unknown.bm25_removed is False
    assert alpha.bm25_indexer.query(["collection"], top_k=2)


def test_real_pdf_image_namespace_keeps_files_placeholders_and_metadata_together(tmp_path):
    from src.libs.loader.pdf_loader import PdfLoader

    source = Path(__file__).parents[1] / "fixtures" / "sample_documents" / "with_images.pdf"
    assert source.is_file()
    left = PdfLoader(image_storage_dir=tmp_path / "alpha", image_id_namespace="scope-alpha").load(source)
    right = PdfLoader(image_storage_dir=tmp_path / "beta", image_id_namespace="scope-beta").load(source)
    assert left.metadata["images"] and right.metadata["images"]
    for document in (left, right):
        for item in document.metadata["images"]:
            assert Path(item["path"]).is_file()
            assert "[IMAGE: " + item["id"] + "]" in document.text
            assert Path(item["path"]).stem == item["id"]
    assert {item["id"] for item in left.metadata["images"]}.isdisjoint(item["id"] for item in right.metadata["images"])
    assert PdfLoader._generate_image_id("abc123def456", 2, 0) == "abc123de_2_0"
    assert PdfLoader._generate_image_id("abc123def456", 2, 0, namespace="") != PdfLoader._generate_image_id("abc123def456", 2, 0)


def test_bm25_exact_removal_uses_selected_collection_not_loaded_collection(tmp_path):
    indexer = BM25Indexer(index_dir=str(tmp_path))
    rows = [{"chunk_id": value, "term_frequencies": {"word": 1}, "doc_length": 1}
            for value in ("chunk", "chunk-neighbour")]
    indexer.build(rows, collection="alpha")
    indexer.build(rows, collection="beta")
    assert indexer.remove_chunks(["chunk"], collection="alpha")
    alpha = json.loads(indexer._get_index_path("alpha").read_text(encoding="utf-8"))
    beta = json.loads(indexer._get_index_path("beta").read_text(encoding="utf-8"))
    assert [row["chunk_id"] for row in alpha["index"]["word"]["postings"]] == ["chunk-neighbour"]
    assert {row["chunk_id"] for row in beta["index"]["word"]["postings"]} == {"chunk", "chunk-neighbour"}


def test_document_detail_disambiguates_collection_and_dashboard_forwards_it(tmp_path, monkeypatch):
    from src.observability.dashboard.services.data_service import DataService

    (alpha, beta), _ = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success and beta.run(str(source)).success
    digest = alpha.integrity_checker.compute_sha256(str(source))
    manager = DocumentManager(alpha.vector_upserter.vector_store, alpha.bm25_indexer,
        alpha.image_storage, alpha.integrity_checker)
    with pytest.raises(ValueError, match="multiple collections"):
        manager.get_document_detail(digest)
    detail = manager.get_document_detail(digest, collection="scope-beta")
    assert detail.collection == "scope-beta" and detail.chunk_count > 0
    assert detail.image_ids == [row["image_id"] for row in beta.image_storage.list_images(collection="scope-beta")]
    service = DataService()
    service._manager = manager
    service._current_collection = "scope-beta"
    monkeypatch.setattr(service, "_ensure_stores", lambda collection: None)
    assert service.get_document_detail(digest, collection="scope-beta")["collection"] == "scope-beta"


def test_sparse_cleanup_failure_keeps_exact_vector_ids_and_history_for_retry(tmp_path, monkeypatch):
    (alpha, _), _ = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success
    manager = DocumentManager(alpha.vector_upserter.vector_store, alpha.bm25_indexer,
        alpha.image_storage, alpha.integrity_checker)
    original_remove = alpha.bm25_indexer.remove_chunks
    monkeypatch.setattr(alpha.bm25_indexer, "remove_chunks", lambda *args: (_ for _ in ()).throw(OSError("temporary sparse failure")))
    failed = manager.delete_document(str(source), "scope-alpha")
    assert not failed.success and "BM25" in failed.errors[0]
    assert alpha.vector_upserter.vector_store.collection.count() > 0
    assert not alpha.integrity_checker.should_skip(alpha.integrity_checker.compute_sha256(str(source)), "scope-alpha")
    monkeypatch.setattr(alpha.bm25_indexer, "remove_chunks", original_remove)
    assert manager.delete_document(str(source), "scope-alpha").success


def test_image_delete_failure_disables_skip_and_preserves_ids_for_retry(tmp_path, monkeypatch):
    (alpha, beta), _ = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success and beta.run(str(source)).success
    digest = alpha.integrity_checker.compute_sha256(str(source))
    manager = DocumentManager(alpha.vector_upserter.vector_store, alpha.bm25_indexer,
        alpha.image_storage, alpha.integrity_checker)
    original_delete = alpha.image_storage.delete_image
    monkeypatch.setattr(alpha.image_storage, "delete_image", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("temporary image delete failure")))
    result = manager.delete_document(str(source), "scope-alpha")
    assert not result.success and "ImageStorage" in result.errors[0]
    assert not alpha.integrity_checker.should_skip(digest, "scope-alpha")
    assert alpha.vector_upserter.vector_store.collection.count() > 0
    assert beta.integrity_checker.should_skip(digest, "scope-beta")
    monkeypatch.setattr(alpha.image_storage, "delete_image", original_delete)
    assert manager.delete_document(str(source), "scope-alpha").success
    assert beta.vector_upserter.vector_store.collection.count() > 0


def test_ambiguous_final_vector_delete_remains_failed_and_can_reingest(tmp_path, monkeypatch):
    (alpha, beta), calls = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success and beta.run(str(source)).success
    digest = alpha.integrity_checker.compute_sha256(str(source))
    store = alpha.vector_upserter.vector_store
    manager = DocumentManager(store, alpha.bm25_indexer, alpha.image_storage, alpha.integrity_checker)
    original_delete = store.delete_by_metadata

    def deleted_then_failed(where):
        original_delete(where)
        raise OSError("vector outcome acknowledgment lost")

    monkeypatch.setattr(store, "delete_by_metadata", deleted_then_failed)
    result = manager.delete_document(str(source), "scope-alpha")
    assert not result.success and "ChromaDB" in result.errors[0]
    assert store.collection.count() == 0
    assert not alpha.integrity_checker.should_skip(digest, "scope-alpha")
    assert beta.integrity_checker.should_skip(digest, "scope-beta")
    monkeypatch.setattr(store, "delete_by_metadata", original_delete)
    unknown = manager.delete_document(str(source), "scope-alpha")
    assert not unknown.success and "unverified" in unknown.errors[0]
    rebuilt = alpha.run(str(source))
    assert rebuilt.success and rebuilt.chunk_count > 0
    assert len(calls) == 3
    assert alpha.integrity_checker.should_skip(digest, "scope-alpha")
    assert beta.vector_upserter.vector_store.collection.count() > 0


def test_old_shared_picture_file_survives_until_last_collection_reference(tmp_path, monkeypatch):
    (alpha, beta), _ = _pipelines(tmp_path, monkeypatch)
    source = tmp_path / "document.pdf"
    source.write_bytes(b"fixed local document bytes")
    assert alpha.run(str(source)).success and beta.run(str(source)).success
    digest = alpha.integrity_checker.compute_sha256(str(source))
    shared = alpha.image_storage.list_images(collection="scope-alpha")[0]["file_path"]
    alpha.image_storage.register_image(image_id="old-shared-beta-id", file_path=shared,
        collection="scope-beta", doc_hash=digest)
    alpha_manager = DocumentManager(alpha.vector_upserter.vector_store, alpha.bm25_indexer,
        alpha.image_storage, alpha.integrity_checker)
    beta_manager = DocumentManager(beta.vector_upserter.vector_store, beta.bm25_indexer,
        beta.image_storage, beta.integrity_checker)
    assert alpha_manager.delete_document(str(source), "scope-alpha").success
    assert Path(shared).is_file()
    assert beta.image_storage.get_image_path("old-shared-beta-id") == shared
    assert beta_manager.delete_document(str(source), "scope-beta").success
    assert not Path(shared).exists()
