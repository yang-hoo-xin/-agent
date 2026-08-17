"""Tests for Phase D deterministic Evidence RAG."""

from __future__ import annotations

from pathlib import Path

from src.core.settings import Settings
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence import (
    DenseRetrievalReport,
    DeterministicEvidenceRetriever,
    EvidenceItem,
    EvidenceReadinessClassifier,
    EvidenceRequest,
    FakeDenseRetrievalProvider,
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
    SymbolIndexer,
)
from src.mod_agent.planning import FeatureSpecBuilder, ImplementationPlanner, RequestPlanner
from src.mod_agent.performance import BudgetLimit, PerformanceBudgetPolicy


class FailingDenseRetrievalProvider:
    provider_name = "vector_store"

    def retrieve(self, *, query, chunks, top_k):
        return DenseRetrievalReport(
            provider=self.provider_name,
            enabled=True,
            disabled_reason="Dense retrieval provider failed: vector backend unavailable",
            trace_events=(
                {
                    "event": "retrieval.dense_failed",
                    "provider": self.provider_name,
                },
            ),
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


def _index_hook_target_collection(db: KnowledgeDatabase, *, collection_id: str) -> None:
    index_version = "v1"
    db.upsert_source(
        SourceRecord(
            source_id="target_mod",
            source_type="target_source",
            root_path="mods/BetterHitFeedback",
        )
    )
    db.upsert_source(
        SourceRecord(
            source_id="decompiled_api",
            source_type="decompiled_api",
            root_path="decompiled",
        )
    )
    chunks = [
        Chunk(
            chunk_id=f"{collection_id}_plugin_load",
            document_id=f"{collection_id}_plugin_doc",
            text="public void Load() { }",
            text_for_retrieval="Load BetterHitFeedback plugin source",
            metadata={
                "chunk_id": f"{collection_id}_plugin_load",
                "document_id": f"{collection_id}_plugin_doc",
                "source_ref": f"{collection_id}_plugin_doc",
                "content_hash": f"{collection_id}_plugin_chunk_hash",
                "file_hash": f"{collection_id}_plugin_file_hash",
                "source_hash": f"{collection_id}_plugin_file_hash",
                "doc_hash": f"{collection_id}_plugin_doc_hash",
                "source_id": "target_mod",
                "source_type": "target_source",
                "source_path": "mods/BetterHitFeedback/Plugin.cs",
                "start_line": 10,
                "end_line": 20,
                "symbols": ["Load"],
                "chunk_type": "method",
            },
        ),
        Chunk(
            chunk_id=f"{collection_id}_crosshair_hook",
            document_id=f"{collection_id}_crosshair_doc",
            text="public void ShowHitIndicator() { }",
            text_for_retrieval=(
                "ShowHitIndicator hook target CrosshairGuiLayer hit indicator"
            ),
            metadata={
                "chunk_id": f"{collection_id}_crosshair_hook",
                "document_id": f"{collection_id}_crosshair_doc",
                "source_ref": f"{collection_id}_crosshair_doc",
                "content_hash": f"{collection_id}_crosshair_chunk_hash",
                "file_hash": f"{collection_id}_crosshair_file_hash",
                "source_hash": f"{collection_id}_crosshair_file_hash",
                "doc_hash": f"{collection_id}_crosshair_doc_hash",
                "source_id": "decompiled_api",
                "source_type": "decompiled_api",
                "source_path": "decompiled/CrosshairGuiLayer.cs",
                "start_line": 100,
                "end_line": 120,
                "symbols": ["ShowHitIndicator"],
                "chunk_type": "method",
                "usage": "hook_target",
                "declaring_type": "CrosshairGuiLayer",
                "method_name": "ShowHitIndicator",
                "parameter_types": [],
                "return_type": "System.Void",
                "method_kind": "instance_method",
            },
        ),
    ]
    db.start_index_version(
        collection_id=collection_id,
        index_version=index_version,
        source_count=2,
        chunk_count=len(chunks),
    )
    for chunk in chunks:
        db.upsert_chunk(
            chunk,
            collection_id=collection_id,
            index_version=index_version,
        )
    SymbolIndexer().index_chunks(
        db,
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
    assert pack.items[0].authority == "mod_agent_deterministic"


def test_deterministic_retriever_uses_shared_chinese_tokenization(tmp_path: Path) -> None:
    db = _index_source(
        tmp_path,
        {
            "behavior.md": "敌人进入踉跄反应时显示黄色标记。",
        },
        source_type="domain_note",
    )

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(query="敌人踉跄时显示黄色标记", requires_hook_evidence=False)
    )

    assert pack.items
    assert any("踉跄" in item.excerpt for item in pack.items)


def test_hook_discovery_uses_explicit_decomposed_search_terms(tmp_path: Path) -> None:
    db = _index_source(
        tmp_path,
        {"ES_Hitreact.cs": "public class ES_Hitreact { }"},
        source_type="decompiled_api",
    )
    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="敌人踉跄时显示黄色标记",
            requires_hook_evidence=False,
            hook_requirement={"search_terms": ["hitreact enemy reaction"]},
        )
    )

    assert any("ES_Hitreact" in item.excerpt for item in pack.items)


def test_lane_local_budget_preserves_symbol_bm25_and_code_text_results(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "ReactionState.cs": (
                "public class ReactionState {\n"
                "    public void EnterReaction() {}\n"
                "    public void ExitReaction() {}\n"
                "}\n"
            ),
        },
        source_type="decompiled_api",
    )
    IncrementalIndexer(
        database=db,
        source_registry=SourceRegistry(db),
    ).build_retrieval_snapshot(("target_mod",))

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="ReactionState",
            requires_hook_evidence=False,
            max_items=6,
        ),
        lane_max_items=2,
    )

    methods = {item.retrieval_method for item in pack.items}
    assert methods == {"symbol_exact", "bm25", "text_match"}
    coverage = pack.budget_summary["deterministic_lane_coverage"]
    assert [row["lane"] for row in coverage] == [
        "symbol_metadata",
        "sparse_bm25",
        "dense",
        "live_text",
    ]
    assert coverage[0]["hit_count"] == 2
    assert coverage[1]["hit_count"] > 0
    assert coverage[3]["hit_count"] > 0


def test_bounded_source_query_set_keeps_queries_and_lanes_independent(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "TerminalLighting.cs": (
                "public class TerminalFlow {\n"
                "    public void FinishAuthentication() {}\n"
                "}\n"
                "public class CorridorLighting {\n"
                "    public void PulseCorridorLights() {}\n"
                "}\n"
            ),
        },
        source_type="decompiled_api",
    )
    IncrementalIndexer(
        database=db,
        source_registry=SourceRegistry(db),
    ).build_retrieval_snapshot(("target_mod",))

    pack = DeterministicEvidenceRetriever(db).retrieve_query_set(
        queries=(
            {
                "query_id": "source_query_authentication",
                "origin": "initial_focus_question",
                "query": "FinishAuthentication",
            },
            {
                "query_id": "source_query_lighting",
                "origin": "initial_focus_query_family",
                "query": "PulseCorridorLights",
            },
        ),
        source_ids=("target_mod",),
        per_query_lane_max_items=1,
        max_items=6,
    )

    execution = pack.budget_summary["source_query_execution"]
    assert {item["query_id"] for item in execution} == {
        "source_query_authentication",
        "source_query_lighting",
    }
    for query_id in (
        "source_query_authentication",
        "source_query_lighting",
    ):
        rows = [item for item in execution if item["query_id"] == query_id]
        assert [item["lane"] for item in rows] == [
            "symbol_metadata",
            "sparse_bm25",
            "live_text",
            "dense",
        ]
        assert any(item["admitted_evidence_refs"] for item in rows)
        assert all(item["result_limit"] == 1 for item in rows)
    assert any(item.symbol == "FinishAuthentication" for item in pack.items)
    assert any(item.symbol == "PulseCorridorLights" for item in pack.items)


def test_bounded_source_query_set_applies_global_budget_fairly_across_queries(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "TerminalLighting.cs": (
                "public class TerminalFlow {\n"
                "    public void FinishAuthentication() {}\n"
                "}\n"
                "public class CorridorLighting {\n"
                "    public void PulseCorridorLights() {}\n"
                "}\n"
            ),
        },
        source_type="decompiled_api",
    )
    IncrementalIndexer(
        database=db,
        source_registry=SourceRegistry(db),
    ).build_retrieval_snapshot(("target_mod",))

    pack = DeterministicEvidenceRetriever(db).retrieve_query_set(
        queries=(
            {
                "query_id": "source_query_authentication",
                "origin": "initial_focus_question",
                "query": "FinishAuthentication",
            },
            {
                "query_id": "source_query_lighting",
                "origin": "initial_focus_query_family",
                "query": "PulseCorridorLights",
            },
        ),
        source_ids=("target_mod",),
        per_query_lane_max_items=1,
        max_items=2,
    )

    symbol_rows = [
        row
        for row in pack.budget_summary["source_query_execution"]
        if row["lane"] == "symbol_metadata"
    ]
    assert [row["admitted_count"] for row in symbol_rows] == [1, 1]
    initial_refs = {
        evidence_ref
        for row in pack.budget_summary["source_query_execution"]
        for evidence_ref in row["admitted_evidence_refs"]
    }
    assert len(initial_refs) == 2
    assert {
        item.symbol for item in pack.items if item.evidence_id in initial_refs
    } == {
        "FinishAuthentication",
        "PulseCorridorLights",
    }


def test_source_query_set_expands_observed_type_and_identifier_components(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "TerminalFlow.cs": (
                "public class TerminalFlow {\n"
                "    public void RunTerminalHandshake(AuthenticationCompletionRelay relay) {}\n"
                "}\n"
            ),
            "AuthenticationCompletionRelay.cs": (
                "public class AuthenticationCompletionRelay {\n"
                "    public void MarkAuthenticationComplete() {}\n"
                "}\n"
            ),
        },
        source_type="decompiled_api",
    )
    IncrementalIndexer(
        database=db,
        source_registry=SourceRegistry(db),
    ).build_retrieval_snapshot(("target_mod",))

    pack = DeterministicEvidenceRetriever(db).retrieve_query_set(
        queries=(
            {
                "query_id": "source_query_terminal_handshake",
                "origin": "initial_focus_query_family",
                "query": "RunTerminalHandshake",
            },
        ),
        source_ids=("target_mod",),
        per_query_lane_max_items=1,
        max_items=3,
    )

    identifiers = pack.budget_summary["observed_identifier_extraction"]
    assert any(
        item["identifier"] == "AuthenticationCompletionRelay"
        and item["extraction_kind"] == "source_excerpt"
        for item in identifiers
    )
    assert {"Authentication", "Completion", "Relay"}.issubset(
        {item["identifier"] for item in identifiers}
    )
    identifier_order = [item["identifier"] for item in identifiers]
    assert identifier_order.index(
        "AuthenticationCompletionRelay"
    ) < identifier_order.index("Authentication")
    expansion = pack.budget_summary["bounded_identifier_reference_expansion"]
    assert expansion["performed"] is True
    expansion_refs = set(expansion["admitted_evidence_refs"])
    assert any(
        item.evidence_id in expansion_refs
        and item.source_path.endswith("AuthenticationCompletionRelay.cs")
        for item in pack.items
    )


def test_symbol_lane_ranks_specific_file_identity_above_directory_only_match(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {
            "TerminalHelpers/Noise.cs": (
                "public class Noise { public void terminal() {} }\n"
            ),
            "TerminalHelpers/Unrelated.cs": (
                "public class Unrelated { public void Refresh() {} }\n"
            ),
            "TerminalAuthenticationFlow.cs": (
                "public class TerminalAuthenticationFlow {\n"
                "    public void FinishAuthentication() {}\n"
                "}\n"
            ),
        },
        source_type="decompiled_api",
    )
    IncrementalIndexer(
        database=db,
        source_registry=SourceRegistry(db),
    ).build_retrieval_snapshot(("target_mod",))

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="terminal completion",
            requires_hook_evidence=True,
            source_ids=("target_mod",),
            max_items=3,
        ),
        lane_max_items=1,
    )

    symbol_items = [
        item for item in pack.items if item.retrieval_method == "symbol_exact"
    ]
    assert len(symbol_items) == 1
    assert symbol_items[0].source_path == "TerminalAuthenticationFlow.cs"
    assert symbol_items[0].symbol == "TerminalAuthenticationFlow"


def test_model_selection_inventory_prioritizes_observed_dotted_method_identity() -> None:
    item = EvidenceItem(
        evidence_id="source_terminal_callback",
        source_type="decompiled_api",
        source_path="TerminalFlow.cs",
        symbol=None,
        span={"start_line": 8, "end_line": 8},
        retrieval_method="text_match",
        score=1.0,
        claim_supported="Source contains an explicit interface method call.",
        excerpt="authenticationEvents.MarkAuthenticationComplete();",
        source_hash="C" * 64,
        authority="mod_agent_deterministic",
        source_authority="supporting",
    )

    inventory = (
        DeterministicEvidenceRetriever.observed_identifier_selection_inventory(
            (item,),
            max_identifiers=1,
        )
    )

    assert inventory == [
        {
            "observed_identifier": (
                "authenticationEvents.MarkAuthenticationComplete"
            ),
            "extraction_kind": "source_excerpt",
            "source_evidence_refs": ["source_terminal_callback"],
            "source_paths": ["TerminalFlow.cs"],
            "source_fact_views": [
                "authenticationEvents.MarkAuthenticationComplete();"
            ],
        }
    ]


def test_retriever_keeps_preverified_lane_independent_from_shared_capacity(
    tmp_path: Path,
) -> None:
    db = _index_source(
        tmp_path,
        {"guide.md": "movement rotation surface normal"},
        source_type="domain_note",
    )
    preverified = EvidenceItem(
        evidence_id="ev_il",
        source_type="decompiled_api",
        source_path="Modules-ASM.dll",
        symbol="ES_PathMove.UpdateRotation",
        span=None,
        retrieval_method="cli_metadata_il_read",
        score=1.0,
        claim_supported="Bound physical IL facts.",
        excerpt="{}",
        source_hash="D" * 64,
        authority="mod_agent_deterministic",
        source_authority="authoritative",
    )

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="surface movement",
            requires_hook_evidence=False,
            max_items=2,
        ),
        preverified_items=(preverified,),
        preverified_lane_coverage=(
            {
                "lane": "metadata_il",
                "status": "searched_with_results",
                "hit_count": 1,
                "scope": {"assembly_sha256": "D" * 64},
                "failure": None,
            },
        ),
    )

    assert pack.items[0].evidence_id == "ev_il"
    assert len(pack.items) == 2


def test_concrete_hook_request_requires_decompiled_api_hook_target() -> None:
    item = EvidenceItem(
        evidence_id="ev_001",
        source_type="target_source",
        source_path="mods/BetterHitFeedback/Plugin.cs",
        symbol="Damage",
        span={"start_line": 10, "end_line": 20},
        retrieval_method="symbol_exact",
        score=1.0,
        claim_supported="Target mod source mentions Damage.",
        excerpt="public void Damage() {}",
        authority="mod_agent_deterministic",
    )

    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="hook enemy damage method for BetterHitFeedback",
            requires_hook_evidence=True,
            hook_requirement={
                "required": True,
                "reason": "gameplay_method_interception",
            },
        ),
        items=[item],
    )

    assert pack.readiness == "partial"
    assert pack.can_generate_patch is False
    assert pack.blockers[0]["code"] == "MISSING_CONCRETE_HOOK_TARGET_EVIDENCE"
    assert pack.missing_evidence[0]["needed_evidence"] == (
        "decompiled API hook target symbol"
    )


def test_hook_request_rejects_unrelated_decompiled_api_method() -> None:
    items = [
        EvidenceItem(
            evidence_id="ev_001",
            source_type="target_source",
            source_path="mods/BetterHitFeedback/Plugin.cs",
            symbol="Load",
            span={"start_line": 10, "end_line": 20},
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported="Target mod source contains Load.",
            excerpt="public void Load() {}",
            authority="mod_agent_deterministic",
        ),
        EvidenceItem(
            evidence_id="ev_api_001",
            source_type="decompiled_api",
            source_path="decompiled/CrosshairGuiLayer.cs",
            symbol="CrosshairGuiLayer.Render",
            span={"start_line": 100, "end_line": 120},
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported="Unrelated rendering method exists.",
            excerpt="public void Render() {}",
            authority="mod_agent_deterministic",
            declaring_type="CrosshairGuiLayer",
            method_name="Render",
            parameter_types=("System.Single",),
            return_type="System.Void",
            method_kind="instance_method",
        ),
    ]

    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="hook enemy damage method for BetterHitFeedback",
            requires_hook_evidence=True,
            hook_requirement={
                "required": True,
                "reason": "gameplay_method_interception",
            },
        ),
        items=items,
    )

    assert pack.readiness == "partial"
    assert pack.blockers[0]["code"] == "MISSING_CONCRETE_HOOK_TARGET_EVIDENCE"


def test_hook_target_overload_requires_parameter_types() -> None:
    items = [
        EvidenceItem(
            evidence_id="ev_001",
            source_type="target_source",
            source_path="mods/BetterHitFeedback/Plugin.cs",
            symbol="Load",
            span={"start_line": 10, "end_line": 20},
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported="Target mod source contains Load.",
            excerpt="public void Load() {}",
            authority="mod_agent_deterministic",
        ),
        EvidenceItem(
            evidence_id="ev_api_001",
            source_type="decompiled_api",
            source_path="decompiled/CrosshairGuiLayer.cs",
            symbol="CrosshairGuiLayer.ShowHitIndicator",
            span={"start_line": 100, "end_line": 120},
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported="ShowHitIndicator is the hook target.",
            excerpt="public void ShowHitIndicator(Vector3 pos) {}",
            authority="mod_agent_deterministic",
            usage="hook_target",
            declaring_type="CrosshairGuiLayer",
            method_name="ShowHitIndicator",
            return_type="System.Void",
            method_kind="instance_method",
        ),
    ]

    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="hook hit indicator method for BetterHitFeedback",
            requires_hook_evidence=True,
            hook_requirement={
                "required": True,
                "reason": "gameplay_method_interception",
            },
        ),
        items=items,
    )

    assert pack.readiness == "partial"
    assert pack.blockers[0]["code"] == "MISSING_CONCRETE_HOOK_TARGET_EVIDENCE"


def test_concrete_hook_request_accepts_decompiled_api_hook_target() -> None:
    items = [
        EvidenceItem(
            evidence_id="ev_001",
            source_type="target_source",
            source_path="mods/BetterHitFeedback/Plugin.cs",
            symbol="Load",
            span={"start_line": 10, "end_line": 20},
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported="Target mod source contains Load.",
            excerpt="public void Load() {}",
            authority="mod_agent_deterministic",
        ),
        EvidenceItem(
            evidence_id="ev_api_001",
            source_type="decompiled_api",
            source_path="decompiled/EnemyAgent.cs",
            symbol="EnemyAgent.Damage",
            span={"start_line": 100, "end_line": 120},
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported="EnemyAgent.Damage is the game hook target.",
            excerpt="public void Damage(float amount) {}",
            authority="mod_agent_deterministic",
            usage="hook_target",
            declaring_type="EnemyAgent",
            method_name="Damage",
            parameter_types=("System.Single",),
            return_type="System.Void",
            method_kind="instance_method",
        ),
    ]

    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="hook enemy damage method for BetterHitFeedback",
            requires_hook_evidence=True,
            hook_requirement={
                "required": True,
                "reason": "gameplay_method_interception",
            },
        ),
        items=items,
    )

    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    assert [item.evidence_id for item in pack.items] == ["ev_001", "ev_api_001"]


def test_retriever_projects_hook_target_method_identity_from_symbol_index(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_hook_target_collection(db, collection_id="knowledge_hub")

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="Load ShowHitIndicator hook target",
            requires_hook_evidence=True,
            hook_requirement={
                "required": True,
                "reason": "gameplay_method_interception",
            },
        )
    )

    hook_item = next(
        item for item in pack.items if item.source_type == "decompiled_api"
    )
    assert pack.readiness == "sufficient"
    assert hook_item.usage == "hook_target"
    assert hook_item.declaring_type == "CrosshairGuiLayer"
    assert hook_item.method_name == "ShowHitIndicator"
    assert hook_item.parameter_types == ()
    assert hook_item.return_type == "System.Void"
    assert hook_item.method_kind == "instance_method"
    assert hook_item.span == {"start_line": 100, "end_line": 120}


def test_retriever_hook_target_identity_flows_into_implementation_plan(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_hook_target_collection(db, collection_id="knowledge_hub")
    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="Load ShowHitIndicator hook target",
            requires_hook_evidence=True,
            hook_requirement={
                "required": True,
                "reason": "gameplay_method_interception",
            },
        )
    )
    request_plan = RequestPlanner().plan(
        "hook ShowHitIndicator method for BetterHitFeedback"
    )
    feature_spec = FeatureSpecBuilder().build(request_plan)

    implementation = ImplementationPlanner().build(
        feature_spec=feature_spec,
        evidence_pack=pack.to_artifact_payload(),
    )

    assert implementation.blocking is False
    hook_binding = implementation.binding_registry["supporting_bindings"][0]
    assert hook_binding["binding_id"] == "hook_target_001"
    assert hook_binding["declaring_type"] == "CrosshairGuiLayer"
    assert hook_binding["method_name"] == "ShowHitIndicator"
    assert hook_binding["parameter_types"] == []
    assert implementation.proposed_changes[0]["hook_target_binding_id"] == (
        "hook_target_001"
    )


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


def test_dense_retrieval_is_disabled_by_default(tmp_path: Path) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_chunk_collection(
        db,
        collection_id="knowledge_hub",
        text="Dense-only evidence lives in this chunk.",
    )

    pack = DeterministicEvidenceRetriever(db).retrieve(
        EvidenceRequest(
            query="DenseOnly",
            execution_path="quick_patch",
            requires_hook_evidence=False,
        )
    )

    assert "dense" not in pack.retrieval_methods_used
    assert pack.disabled_modes["dense"].startswith("Dense retrieval is disabled")
    assert pack.budget_summary["dense_retrieval"]["enabled"] is False


def test_fake_dense_provider_returns_auxiliary_chunk_with_budget_report(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_chunk_collection(
        db,
        collection_id="knowledge_hub",
        text="Dense-only evidence lives in this chunk.",
    )
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="retrieval",
                max_api_calls=0,
                max_items=20,
                cache_enabled=True,
                on_exceed="block",
            )
        ]
    )

    pack = DeterministicEvidenceRetriever(
        db,
        dense_enabled=True,
        dense_provider=FakeDenseRetrievalProvider(
            {"knowledge_hub_chunk_001": 0.91},
            api_calls=0,
            cache_enabled=True,
        ),
        performance_policy=policy,
    ).retrieve(
        EvidenceRequest(
            query="DenseOnly",
            execution_path="quick_patch",
            requires_hook_evidence=False,
        )
    )

    assert pack.readiness == "partial"
    assert pack.can_generate_patch is False
    assert pack.items[0].retrieval_method == "dense"
    assert pack.items[0].chunk_id == "knowledge_hub_chunk_001"
    assert pack.items[0].authority == "legacy_rag_auxiliary"
    assert pack.retrieval_methods_used == ("dense",)
    assert pack.trace_refs == (
        "retrieval.dense_started",
        "retrieval.dense_finished",
    )
    dense_budget = pack.budget_summary["dense_retrieval"]
    assert dense_budget["api_calls"] == 0
    assert dense_budget["embedded_items"] == 1
    assert dense_budget["budget_decision"]["status"] == "allowed"
    assert dense_budget["budget_decision"]["allowed"] is True


def test_dense_provider_budget_block_degrades_to_existing_routes(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_chunk_collection(
        db,
        collection_id="knowledge_hub",
        text="Dense-only evidence lives in this chunk.",
    )
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="retrieval",
                max_api_calls=0,
                cache_enabled=True,
                on_exceed="block",
            )
        ]
    )

    pack = DeterministicEvidenceRetriever(
        db,
        dense_enabled=True,
        dense_provider=FakeDenseRetrievalProvider(
            {"knowledge_hub_chunk_001": 0.91},
            api_calls=1,
            cache_enabled=True,
        ),
        performance_policy=policy,
    ).retrieve(
        EvidenceRequest(
            query="DenseOnly",
            execution_path="quick_patch",
            requires_hook_evidence=False,
        )
    )

    assert pack.items == ()
    assert pack.can_generate_patch is False
    assert "Dense retrieval budget blocked" in pack.disabled_modes["dense"]
    assert pack.budget_summary["dense_retrieval"]["budget_decision"]["status"] == "blocked"


def test_required_dense_failure_blocks_even_when_deterministic_evidence_exists(
    tmp_path: Path,
) -> None:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    _index_chunk_collection(
        db,
        collection_id="knowledge_hub",
        text="DenseOnly deterministic evidence lives in this chunk.",
    )

    pack = DeterministicEvidenceRetriever(
        db,
        dense_enabled=True,
        dense_required=True,
        dense_provider=FailingDenseRetrievalProvider(),
    ).retrieve(
        EvidenceRequest(
            query="DenseOnly",
            execution_path="quick_patch",
            requires_hook_evidence=False,
        )
    )

    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.blockers[-1]["code"] == "DENSE_RETRIEVAL_REQUIRED_FAILED"
    assert pack.disabled_modes["dense"] == (
        "Dense retrieval provider failed: vector backend unavailable"
    )
    assert "retrieval.dense_failed" in pack.trace_refs


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


def test_evidence_item_defaults_to_auxiliary_authority() -> None:
    item = EvidenceItem(
        evidence_id="raw_001",
        source_type="target_source",
        source_path="mods/BetterHitFeedback/Plugin.cs",
        symbol="Load",
        span={"start_line": 1, "end_line": 1},
        retrieval_method="symbol_exact",
        score=1.0,
        claim_supported="Raw evidence mentions Load.",
        excerpt="public void Load() {}",
    )

    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(query="Load", requires_hook_evidence=True),
        items=[item],
    )

    assert item.authority == "legacy_rag_auxiliary"
    assert pack.can_generate_patch is False
    assert pack.blockers[0]["code"] == "AUXILIARY_RETRIEVAL_NOT_AUTHORITATIVE"
