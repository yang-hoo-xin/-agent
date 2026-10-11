from dataclasses import replace

import pytest

from src.core.query_engine.dense_retriever import DenseRetriever
from src.core.settings import load_settings
from src.libs.vector_store.chroma_store import ChromaStore
from tests.unit.test_dense_retriever import FakeEmbedding
from tests.unit.test_query_service import make_service, request


def test_real_chroma_container_scope_does_not_require_collection_metadata(tmp_path):
    settings = load_settings("config/settings.yaml")
    settings = replace(settings, storage_root=str(tmp_path), vector_store=replace(settings.vector_store,
        persist_directory=str(tmp_path / "chroma"), collection_name="bound_docs"))
    store = ChromaStore(settings)
    embedding = FakeEmbedding(dimension=3)
    store.upsert([{"id": "api", "vector": [0., 1/3, 2/3], "metadata": {"text": "ConfigFile.Reload", "source_path": "api.xml"}}])
    retriever = DenseRetriever(settings, embedding_client=embedding, vector_store=store)
    filters = {"collection": "bound_docs", "source_path": "api.xml"}
    rows = retriever.retrieve("reload", filters=filters)
    assert len(rows) == 1 and rows[0].chunk_id == "api"
    assert rows[0].metadata["collection"] == "bound_docs" and filters["collection"] == "bound_docs"
    calls = embedding.call_count
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        retriever.retrieve("reload", filters={"collection": "other_docs"})
    assert embedding.call_count == calls


def test_full_cache_rejects_changed_implementation(tmp_path, monkeypatch):
    import src.core.query_engine.query_service as module
    version = {"source": "v1"}
    monkeypatch.setattr(module, "query_implementation_identity", lambda: dict(version))
    service, model, _, calls, _ = make_service(tmp_path)
    first = service.query(request(request_id="first")).to_dict()
    assert first["status"] == "completed"
    count = len(calls)
    assert service.query(request(request_id="repeat")).to_dict()["cache"]["result"] == "hit"
    version["source"] = "v2"
    assert service.query(request(request_id="updated")).to_dict()["cache"]["result"] == "miss"
    assert len(calls) > count
