"""Tests for the Phase A LangGraph workflow skeleton."""

from __future__ import annotations

from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.workflow import build_graph, create_initial_state


def _knowledge_with_load_symbol(tmp_path: Path) -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    (root / "Plugin.cs").write_text(
        """
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
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )
    IncrementalIndexer(database=db, source_registry=registry).index_source("target_mod")
    return db


def test_evidence_backed_path_reaches_done(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_domain="gtfo",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "done"
    assert "workflow_summary" in result["artifacts"]
    assert "blocked_report" not in result["artifacts"]
    assert result["blockers"] == []
    assert result["evidence_summary"]["can_generate_patch"] is True
    assert result["review_summary"]["allowed_next_stage"] == "dry_run_apply"


def test_missing_knowledge_routes_to_blocked_after_evidence(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_domain="gtfo",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" not in result["artifacts"]
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["blockers"]


def test_vague_request_routes_to_blocked(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="test",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "request_planning_report" in result["artifacts"]
    assert "blocked_report" in result["artifacts"]
    assert result["blockers"]
    assert result["blockers"][0]["stage"] == "request_planning"


def test_graph_trace_contains_node_started_and_finished(tmp_path: Path) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event_types = {event["event_type"] for event in result["trace_events"]}
    assert "node_started" in event_types
    assert "node_finished" in event_types
    assert any(event["node_name"] == "plan_request" for event in result["trace_events"])
    assert any(event["node_name"] == "done" for event in result["trace_events"])


def test_graph_writes_artifacts_through_store(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(store, knowledge_database=_knowledge_with_load_symbol(tmp_path))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    refs = store.list_feature_artifacts(result["feature_id"])
    artifact_types = {ref.artifact_type for ref in refs}
    assert "feature_spec" in artifact_types
    assert "workflow_summary" in artifact_types
    assert set(result["artifacts"]).issubset(artifact_types)
