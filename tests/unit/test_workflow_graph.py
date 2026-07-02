"""Tests for the Phase A LangGraph workflow skeleton."""

from __future__ import annotations

from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.knowledge import (
    CollectionResolver,
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.workflow import build_graph, create_initial_state


def _knowledge_with_load_symbol(tmp_path: Path, *, root_name: str = "source") -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / root_name
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
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "done"
    assert "workflow_summary" in result["artifacts"]
    assert "blocked_report" not in result["artifacts"]
    assert result["blockers"] == []
    assert result["evidence_summary"]["can_generate_patch"] is True
    assert result["evidence_summary"]["retrieval_methods_used"] == ["symbol_exact"]
    assert result["evidence_summary"]["missing_evidence"] == []
    assert result["evidence_summary"]["timing"]["final_count"] == 1.0
    assert result["review_summary"]["allowed_next_stage"] == "dry_run_apply"
    assert result["build_summary"]["execution_mode"] == "fake"
    assert result["build_summary"]["claims_real_build_success"] is False
    assert result["runtime_summary"]["status"] == "inconclusive"
    assert result["runtime_summary"]["claims_real_runtime_success"] is False


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
    assert "patch_proposal" not in result["artifacts"]
    assert "proposal_review" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["evidence_summary"]["missing_evidence"]
    assert result["evidence_summary"]["timing"]["final_count"] == 0.0
    assert result["blockers"]


def test_collection_resolution_failure_routes_to_blocked_after_evidence(
    tmp_path: Path,
) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        collection_resolver=CollectionResolver(settings_path=tmp_path / "missing.yaml"),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["evidence_summary"]["can_generate_patch"] is False
    assert "Collection resolution failed" in result["evidence_summary"]["gaps"][0]
    assert result["blockers"][0]["code"] == "INSUFFICIENT_EVIDENCE"


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


def test_retrieve_evidence_trace_exposes_pack_summary(tmp_path: Path) -> None:
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

    event = _finished_event(result, "retrieve_evidence")
    assert event["status"] == "success"
    assert event["artifact_refs"] == [result["artifacts"]["evidence_pack"]]
    assert event["details"]["readiness"] == "sufficient"
    assert event["details"]["can_generate_patch"] is True
    assert event["details"]["retrieval_methods_used"] == ["symbol_exact"]
    assert event["details"]["missing_evidence_count"] == 0
    assert event["details"]["disabled_modes"]["bm25"]
    assert event["details"]["timing"]["final_count"] == 1.0


def test_retrieve_evidence_trace_records_blocked_summary(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event = _finished_event(result, "retrieve_evidence")
    assert event["status"] == "blocked"
    assert event["details"]["readiness"] == "insufficient"
    assert event["details"]["can_generate_patch"] is False
    assert event["details"]["missing_evidence_count"] > 0
    assert event["details"]["timing"]["final_count"] == 0.0


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


def test_approved_path_writes_explicit_fake_execution_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(store, knowledge_database=_knowledge_with_load_symbol(tmp_path))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    dry_run = _artifact_data(store, result, "dry_run_result")
    build = _artifact_data(store, result, "build_result")
    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")
    summary = _artifact_data(store, result, "workflow_summary")

    assert dry_run["execution_mode"] == "fake"
    assert dry_run["actual_write_performed"] is False
    assert dry_run["real_patch_applied"] is False
    assert build["execution_mode"] == "fake"
    assert build["status"] == "skipped"
    assert build["real_build_performed"] is False
    assert build["build_status"] == "fake_completed"
    assert build["claims_real_build_success"] is False
    assert build["repair_handoff"]["allowed"] is False
    assert runtime["execution_mode"] == "fake"
    assert runtime["runtime_status"] == "inconclusive"
    assert runtime["verification_status"] == "inconclusive"
    assert runtime["acceptance_status"] == "inconclusive"
    assert runtime["startup_loaded"] is False
    assert runtime["gameplay_behavior_verified"] is False
    assert runtime["real_runtime_performed"] is False
    assert runtime["raw_supplied_output"] is None
    assert runtime["claims_real_runtime_success"] is False
    assert evaluation["workflow_completion_status"] == "fake_execution_completed"
    assert evaluation["requested_behavior_status"] == "not_verified"
    assert evaluation["verdict"] == "inconclusive"
    assert evaluation["claims_real_success"] is False
    assert evaluation["input_acceptance_status"] == "inconclusive"
    assert summary["workflow_completion_status"] == "fake_execution_completed"
    assert summary["requested_behavior_status"] == "not_verified"
    assert summary["final_status"] == "inconclusive"
    assert summary["claims_real_mod_success"] is False
    assert summary["claims_real_build_success"] is False
    assert summary["claims_real_runtime_success"] is False


def test_review_block_does_not_create_fake_success_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path, root_name="secrets"),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["review_summary"]["allowed_next_stage"] is None
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]


def test_default_graph_uses_domain_policy_for_unsupported_domain(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_domain_policy",
        request_id="req_domain_policy",
        user_request="make Load change runtime behavior",
        target_domain="unsupported",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert result["review_summary"]["allowed_next_stage"] is None
    assert any(blocker["code"] == "DOMAIN_PROFILE" for blocker in result["blockers"])
    review = _artifact_data(store, result, "proposal_review")
    assert review["decision"] == "blocked_requires_human"
    assert any(finding["rule_id"] == "domain_profile" for finding in review["findings"])


def _artifact_data(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
) -> dict[str, object]:
    for ref in store.list_feature_artifacts(str(result["feature_id"])):
        if ref.artifact_type == artifact_type:
            return store.read(ref)["data"]
    raise AssertionError(f"Missing artifact: {artifact_type}")


def _finished_event(result: dict[str, object], node_name: str) -> dict[str, object]:
    for event in result["trace_events"]:
        if event["node_name"] == node_name and event["event_type"] == "node_finished":
            return event
    raise AssertionError(f"Missing finished event: {node_name}")
