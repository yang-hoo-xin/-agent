"""Tests for Phase D deterministic Evidence RAG."""

from __future__ import annotations

from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence import (
    DeterministicEvidenceRetriever,
    EvidenceItem,
    EvidenceReadinessClassifier,
    EvidenceRequest,
)
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
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
