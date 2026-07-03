"""Tests for Phase D deterministic Evidence RAG."""

from __future__ import annotations

from pathlib import Path

from src.core.settings import Settings
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence import (
    DeterministicEvidenceRetriever,
    EvidenceItem,
    EvidenceReadinessClassifier,
    EvidenceRequest,
)
from src.mod_agent.knowledge import (
    BM25Indexer,
    Chunk,
    CollectionResolver,
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRecord,
    SourceRegistry,
)


def _feature_payload() -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "stub",
        "feature_id": "feature_001",
        "user_request": "Load",
        "target_behavior": "Load",
        "non_goals": [],
        "target_mod": None,
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _settings(collection_name: str) -> Settings:
    return Settings.from_dict(
        {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o",
                "temperature": 0.0,
                "max_tokens": 4096,
            },
            "embedding": {
                "provider": "openai",
                "model": "text-embedding-ada-002",
                "dimensions": 1536,
            },
            "vector_store": {
                "provider": "chroma",
                "persist_directory": "./data/db/chroma",
                "collection_name": collection_name,
            },
            "retrieval": {
                "dense_top_k": 20,
                "sparse_top_k": 20,
                "fusion_top_k": 10,
                "rrf_k": 60,
            },
            "rerank": {
                "enabled": False,
                "provider": "none",
                "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "top_k": 5,
            },
            "evaluation": {
                "enabled": False,
                "provider": "custom",
                "metrics": ["hit_rate"],
            },
            "observability": {
                "log_level": "INFO",
                "trace_enabled": True,
                "trace_file": "./logs/traces.jsonl",
                "structured_logging": True,
            },
        }
    )


def _index_chunk_collection(
    db: KnowledgeDatabase,
    *,
    collection_id: str,
    text: str,
) -> None:
    index_version = "v1"
    db.upsert_source(
        SourceRecord(
            source_id="target_mod",
            source_type="target_source",
            root_path=collection_id,
        )
    )
    db.start_index_version(
        collection_id=collection_id,
        index_version=index_version,
        source_count=1,
        chunk_count=1,
    )
    document_id = f"{collection_id}_doc_001"
    chunk_id = f"{collection_id}_chunk_001"
    file_hash = f"{collection_id}_file_hash"
    doc_hash = f"{collection_id}_doc_hash"
    chunk_hash = f"{collection_id}_chunk_hash"
    db.upsert_chunk(
        Chunk(
            chunk_id=chunk_id,
            document_id=document_id,
            text=text,
            text_for_retrieval=text,
            metadata={
                "chunk_id": chunk_id,
                "document_id": document_id,
                "source_ref": document_id,
                "content_hash": chunk_hash,
                "file_hash": file_hash,
                "source_hash": file_hash,
                "doc_hash": doc_hash,
                "source_id": "target_mod",
                "source_type": "target_source",
                "source_path": f"{collection_id}/config.json",
            },
        ),
        collection_id=collection_id,
        index_version=index_version,
    )
    BM25Indexer(db).index(collection_id=collection_id, index_version=index_version)
    db.set_index_version_status(
        collection_id=collection_id,
        index_version=index_version,
        status="stable",
    )


def _index_source(
    tmp_path: Path,
    files: dict[str, str],
    *,
    source_type: str = "target_source",
) -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type=source_type,
            root_path=root,
            allowed_extensions=frozenset({".cs", ".json", ".md"}),
        )
    )
    IncrementalIndexer(database=db, source_registry=registry).index_source("target_mod")
    return db


def test_deterministic_retriever_finds_exact_symbol(tmp_path: Path) -> None:
    db = _index_source(
        tmp_path,
        {
            "Plugin.cs": """
public class Plugin
{
    public void Load()
    {
    }
}
""".strip()
        },
    )

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(query="Load", requires_hook_evidence=True)
    )

    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    assert pack.items[0].symbol == "Load"
    assert pack.items[0].source_type == "target_source"
    assert pack.items[0].retrieval_method == "symbol_exact"


def test_deterministic_retriever_uses_configured_collection_default(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_chunk_collection(
        db,
        collection_id="knowledge_hub",
        text="EnableLogging is configured in this collection.",
    )
    resolver = CollectionResolver(settings=_settings("knowledge_hub"))

    pack = DeterministicEvidenceRetriever(
        db,
        collection_resolver=resolver,
    ).retrieve(
        EvidenceRequest(
            query="EnableLogging",
            execution_path="quick_patch",
            requires_hook_evidence=False,
        )
    )

    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    assert pack.items[0].source_path == "knowledge_hub/config.json"
    assert pack.items[0].chunk_id == "knowledge_hub_chunk_001"
    assert pack.items[0].document_id == "knowledge_hub_doc_001"
    assert pack.items[0].source_ref == "knowledge_hub_doc_001"
    assert pack.items[0].file_hash == "knowledge_hub_file_hash"
    assert pack.items[0].source_hash == "knowledge_hub_file_hash"
    assert pack.items[0].doc_hash == "knowledge_hub_doc_hash"


def test_deterministic_retriever_explicit_collection_overrides_default(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_chunk_collection(
        db,
        collection_id="request_scope",
        text="EnableLogging exists only in the explicit collection.",
    )
    resolver = CollectionResolver(settings=_settings("knowledge_hub"))

    pack = DeterministicEvidenceRetriever(
        db,
        collection_id="request_scope",
        collection_resolver=resolver,
    ).retrieve(
        EvidenceRequest(
            query="EnableLogging",
            execution_path="quick_patch",
            requires_hook_evidence=False,
        )
    )

    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    assert pack.items[0].source_path == "request_scope/config.json"
    assert pack.items[0].chunk_id == "request_scope_chunk_001"


def test_missing_source_returns_insufficient_empty_pack(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(query="MissingHook", requires_hook_evidence=True)
    )

    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.items == ()
    assert pack.blockers[0]["code"] == "INSUFFICIENT_EVIDENCE"


def test_quick_patch_can_use_config_text_evidence_without_hook_evidence(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "config.json": '{ "EnableLogging": false }\n',
        },
    )

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="EnableLogging",
            execution_path="quick_patch",
            requires_hook_evidence=False,
        )
    )

    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    assert pack.items[0].retrieval_method == "text_match"
    assert "EnableLogging" in pack.items[0].excerpt


def test_standard_feature_with_only_text_evidence_is_partial_when_hook_required(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "notes.md": "EnableLogging is a config flag.\n",
        },
    )

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(query="EnableLogging", requires_hook_evidence=True)
    )

    assert pack.readiness == "partial"
    assert pack.can_generate_patch is False
    assert pack.blockers[0]["code"] == "INSUFFICIENT_HOOK_EVIDENCE"


def test_evidence_pack_payload_validates_against_artifact_contract(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "Plugin.cs": "public class Plugin { public void Load() {} }\n",
        },
    )
    pack = DeterministicEvidenceRetriever(db).retrieve(EvidenceRequest(query="Load"))
    store = ArtifactStore(tmp_path / "artifacts")
    feature_ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    ref = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=pack.to_artifact_payload(),
        upstream_refs=[feature_ref],
    )

    envelope = store.read(ref)
    assert envelope["producer_stage"] == "evidence_retrieval"
    assert envelope["data"]["readiness"] == "sufficient"
    assert envelope["data"]["can_generate_patch"] is True
    assert envelope["data"]["authority"] == "mod_agent_deterministic_evidence"
    assert envelope["data"]["authoritative_for_patch"] is True
    assert envelope["data"]["identity_schema_version"] == "identity_v1"
    assert envelope["data"]["identity_field_mapping"]["source_ref"].startswith(
        "Chunk-to-document reference"
    )


def test_legacy_rag_evidence_is_auxiliary_not_authoritative() -> None:
    item = EvidenceItem(
        evidence_id="legacy_001",
        source_type="target_source",
        source_path="mods/BetterHitFeedback/Plugin.cs",
        symbol="Load",
        span={"start_line": 1, "end_line": 1},
        retrieval_method="symbol_exact",
        score=1.0,
        claim_supported="Legacy retrieval result mentions Load.",
        excerpt="public void Load() {}",
        authority="legacy_rag_auxiliary",
    )

    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(query="Load", requires_hook_evidence=True),
        items=[item],
    )

    assert pack.readiness == "partial"
    assert pack.can_generate_patch is False
    assert pack.blockers[0]["code"] == "AUXILIARY_RETRIEVAL_NOT_AUTHORITATIVE"
