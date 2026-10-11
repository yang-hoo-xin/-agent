"""Prepare real repository text through existing sparse indexing and query owners."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

SOURCES = [
    ("src/ingestion/storage/bm25_indexer.py", "BM25Indexer inverted postings IDF"),
    ("src/ingestion/embedding/sparse_encoder.py", "SparseEncoder term_frequencies"),
    ("src/core/query_engine/query_service.py", "QueryService citation_validation"),
    ("src/service_layer/store.py", "RedisJobStore IdempotencyConflict"),
    ("src/service_layer/api.py", "Idempotency-Key Queue capacity reached"),
    ("src/service_layer/backends.py", "RedisQueryCache QUERY_SETTINGS_BINDING_CHANGED"),
]


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def prepare(output, collection="service_load"):
    from src.core.settings import Settings
    from src.core.types import Chunk
    from src.ingestion.embedding.sparse_encoder import SparseEncoder
    from src.ingestion.storage.bm25_indexer import BM25Indexer
    from src.libs.vector_store.vector_store_factory import VectorStoreFactory
    from src.core.query_engine.service_factory import create_query_service

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    storage = output / "data"
    settings_data = {
        "storage_root": str(storage),
        "llm": {"provider": "ollama", "model": "unused-in-sparse-load", "temperature": 0.0, "max_tokens": 256, "base_url": "http://127.0.0.1:1"},
        "embedding": {"provider": "ollama", "model": "unused-in-sparse-load", "dimensions": 1, "base_url": "http://127.0.0.1:1"},
        "vector_store": {"provider": "chroma", "persist_directory": str(storage / "db/chroma"), "collection_name": collection},
        "retrieval": {"dense_enabled": False, "dense_provider": "disabled", "dense_top_k": 10, "sparse_top_k": 10, "fusion_top_k": 10, "rrf_k": 60},
        "rerank": {"enabled": False, "provider": "cross_encoder", "model": "unused", "top_k": 5},
        "evaluation": {"enabled": False, "provider": "ragas", "metrics": []},
        "observability": {"log_level": "WARNING", "trace_enabled": False, "trace_file": str(output / "query-traces.jsonl"), "structured_logging": False},
        "query": {"rewrite_enabled": False, "answer_streaming": False, "cache_enabled": False, "timeout_seconds": 60.0, "queue_timeout_seconds": 60.0},
    }
    settings = Settings.from_dict(settings_data)
    write(output / "settings.yaml", settings_data)  # JSON is a YAML subset.
    chunks, source_refs, queries = [], [], []
    corpus = output / "corpus"
    corpus.mkdir()
    for relative, query in SOURCES:
        raw = (REPO / relative).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8")
        target = corpus / Path(relative).name
        target.write_bytes(raw)
        source_refs.append({"source": relative, "sha256": digest, "bytes": len(raw), "retained": str(target)})
        for offset in range(0, len(text), 3000):
            content = text[offset:offset+3000]
            chunk_id = hashlib.sha256((relative + ":" + str(offset) + ":" + digest).encode()).hexdigest()
            chunks.append(Chunk(id=chunk_id, text=content, metadata={"source_path": relative, "source_sha256": digest,
                "chunk_index": offset // 3000, "collection": collection, "text": content}))
        queries.append({"query": query, "expected_source": relative})
    vector = VectorStoreFactory.create(settings, collection_name=collection)
    # Scope: Chroma's mandatory vector slot only. 为什么要有它：稀疏检索从Chroma按ID取正文，固定占位向量不参与排名，也不冒充模型embedding。
    vector.upsert([{"id": c.id, "vector": [1.0], "metadata": c.metadata} for c in chunks])
    index = BM25Indexer(index_dir=str(storage / "db/bm25" / collection))
    index.build(SparseEncoder().encode(chunks), collection=collection)
    service = create_query_service(settings, collection=collection)
    smoke = []
    for item in queries:
        response = service.query({"query": item["query"], "collection": collection, "top_k": 5,
            "answer": False, "rewrite": False, "rerank": False}).to_dict()
        matched = any(row.get("metadata", {}).get("source_path") == item["expected_source"] for row in response["results"])
        smoke.append({"query": item["query"], "expected_source": item["expected_source"], "matched": matched, "response": response})
    write(output / "queries.json", {"collection": collection, "queries": queries})
    write(output / "smoke.json", smoke)
    ok = all(row["matched"] and row["response"]["status"] == "completed" for row in smoke)
    manifest = {"schema": "service-load-corpus.v1", "status": "ready" if ok else "smoke_failed", "source_refs": source_refs,
        "document_count": len(source_refs), "chunk_count": len(chunks), "source_bytes": sum(r["bytes"] for r in source_refs),
        "collection": collection, "settings_sha256": hashlib.sha256((output / "settings.yaml").read_bytes()).hexdigest(),
        "scope": "Real BM25 ranking and Chroma text lookup on retained repository source; dense, rerank, rewrite and answer disabled; no LLM performance claim",
        "vector_slot": "one-dimensional constant required for Chroma storage only; never queried", "provider_calls": 0}
    write(output / "manifest.json", manifest)
    if not ok:
        raise RuntimeError("Corpus smoke failed; inspect retained smoke.json")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--collection", default="service_load")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output_root, args.collection), ensure_ascii=False))
