"""Tests for repair planning, retry budget, and review re-entry."""

from __future__ import annotations

from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.build import BuildAdapter, BuildProfile, BuildResult
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.proposal import ProposalReviewer
from src.mod_agent.repair import RepairPatchProposalBuilder, RepairPlanner
from src.mod_agent.workflow import build_graph, create_initial_state
from src.mod_agent.workflow.transitions import (
    route_after_build,
    route_after_repair_plan,
    route_after_runtime_evidence,
)


def test_failed_build_creates_evidence_bound_repair_plan() -> None:
    build_result = _failed_build_result("feature_001").to_artifact_payload()

    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=build_result,
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
    )
    payload = plan.to_artifact_payload()

    assert payload["failure_source"] == "build"
    assert payload["failure_class"] == "missing_reference"
    assert payload["evidence_refs"]
    assert "artifacts/features/feature_001/build_result.json" in payload["evidence_refs"]
    assert payload["minimal_changes"][0]["target_file"] == "Plugin.cs"
    assert payload["retry_count"] == 1
    assert payload["retry_budget"] == 2
    assert payload["retry_exhausted"] is False
    assert payload["allowed_next_stage"] == "generate_patch_proposal"


def test_retry_budget_exhaustion_blocks_repair_loop() -> None:
    build_result = _failed_build_result("feature_001").to_artifact_payload()

    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=build_result,
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=2,
        target_behavior="make Load enable diagnostics",
    )
    payload = plan.to_artifact_payload()

    assert payload["retry_exhausted"] is True
    assert payload["allowed_next_stage"] is None
    assert payload["blockers"][0]["code"] == "RETRY_BUDGET_EXHAUSTED"


def test_repair_proposal_reenters_review_gate() -> None:
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result("feature_001").to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
    ).to_artifact_payload()

    proposal = RepairPatchProposalBuilder().build(plan).to_artifact_payload()
    review = ProposalReviewer().review(
        proposal,
        repair_plan=plan,
        feature_spec={"target_behavior": "make Load enable diagnostics"},
        permission_level="dry_run_write",
    )

    assert proposal["blocked"] is False
    assert review.allowed_next_stage == "dry_run_apply"
    assert review.trace_metrics["num_changes_checked"] == 1


def test_repair_routes_are_explicit() -> None:
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
    )
    state["build_summary"] = {"status": "failed"}
    assert route_after_build(state) == "repair"

    state["build_summary"] = {"status": "success"}
    assert route_after_build(state) == "continue"

    state["runtime_summary"] = {
        "status": "failed",
        "acceptance_status": "failed",
        "acceptance_verified": False,
    }
    assert route_after_runtime_evidence(state) == "repair"

    state["runtime_summary"] = {
        "status": "inconclusive",
        "acceptance_status": "inconclusive",
        "acceptance_verified": False,
    }
    assert route_after_runtime_evidence(state) == "repair"

    state["runtime_summary"] = {
        "status": "verified",
        "acceptance_status": "accepted",
        "acceptance_verified": True,
    }
    assert route_after_runtime_evidence(state) == "continue"

    state["blockers"] = [{"code": "RETRY_BUDGET_EXHAUSTED"}]
    assert route_after_repair_plan(state) == "blocked"


def test_graph_failed_build_enters_repair_and_stops_at_retry_budget(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=_failed_build_result,
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)
    repair_plan = _artifact_data(store, result, "repair_plan")

    assert result["current_stage"] == "blocked"
    assert "repair_plan" in result["artifacts"]
    assert repair_plan["failure_source"] == "build"
    assert repair_plan["retry_exhausted"] is True
    assert result["retry_count"] == 2
    assert any(
        event["node_name"] == "create_repair_plan"
        and event["event_type"] == "node_finished"
        for event in result["trace_events"]
    )
    assert result["blockers"][0]["code"] == "RETRY_BUDGET_EXHAUSTED"


def _failed_build_result(
    feature_id: str,
    input_execution_mode: str | None = None,
) -> BuildResult:
    profile = BuildProfile(
        profile_id="test_profile",
        build_system="dotnet",
        working_directory="generated_mods/TestMod",
        command=("dotnet", "build"),
        timeout_seconds=120,
        expected_artifacts=("bin/Debug/TestMod.dll",),
    )
    result = BuildAdapter().from_supplied_output(
        feature_id=feature_id,
        profile=profile,
        exit_code=1,
        stderr="Plugin.cs(12,7): error CS0246: The type or namespace name 'Foo' could not be found",
    )
    if input_execution_mode is None:
        return result
    return result


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


def _artifact_data(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
) -> dict[str, object]:
    for ref in store.list_feature_artifacts(str(result["feature_id"])):
        if ref.artifact_type == artifact_type:
            return store.read(ref)["data"]
    raise AssertionError(f"Missing artifact: {artifact_type}")
