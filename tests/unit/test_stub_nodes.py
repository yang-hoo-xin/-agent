"""Tests for Phase A stub workflow nodes."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.workflow import (
    NODE_ARTIFACT_MAP,
    NODE_STAGE_MAP,
    StubNodeRunner,
    create_initial_state,
)


def test_stub_node_writes_artifact_and_updates_state(tmp_path: Path) -> None:
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make enemies glow",
    )
    runner = StubNodeRunner(ArtifactStore(tmp_path / "artifacts"))

    result = runner.run("plan_request", state)

    assert result.state["current_stage"] == "request_planning"
    assert result.state["feature_id"] == "req_001"
    assert "request_planning_report" in result.state["artifacts"]
    assert "request_planning_report" in result.state["artifact_hashes"]
    envelope = runner.artifact_store.read(result.artifact_ref)
    assert envelope["status"] == "stubbed"
    assert envelope["data"]["node_name"] == "plan_request"
    assert "No real retrieval" in envelope["data"]["message"]


def test_stub_node_emits_structured_trace_event(tmp_path: Path) -> None:
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="test",
    )
    runner = StubNodeRunner(ArtifactStore(tmp_path / "artifacts"))

    result = runner.run("retrieve_evidence", state)

    event = result.trace_event.to_dict()
    assert event["event_type"] == "node_finished"
    assert event["status"] == "stubbed"
    assert event["stage"] == "evidence_retrieval"
    assert event["node_name"] == "retrieve_evidence"
    assert event["artifact_refs"] == [result.artifact_ref.path]


def test_all_phase_a_stub_nodes_have_stage_and_artifact_mapping() -> None:
    expected_nodes = {
        "plan_request",
        "draft_feature_spec",
        "retrieve_evidence",
        "create_implementation_plan",
        "generate_patch_proposal",
        "review_proposal",
        "dry_run_apply",
        "build",
        "collect_runtime_evidence",
        "create_repair_plan",
        "evaluate",
        "done",
        "blocked",
    }

    assert set(NODE_STAGE_MAP) == expected_nodes
    assert set(NODE_ARTIFACT_MAP) == expected_nodes


def test_unknown_stub_node_is_rejected(tmp_path: Path) -> None:
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="test",
    )
    runner = StubNodeRunner(ArtifactStore(tmp_path / "artifacts"))

    with pytest.raises(KeyError, match="Unknown stub node"):
        runner.run("real_patch_generator", state)


def test_blocked_stub_adds_structured_blocker(tmp_path: Path) -> None:
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="test",
    )
    runner = StubNodeRunner(ArtifactStore(tmp_path / "artifacts"))

    result = runner.run("blocked", state)

    assert result.state["current_stage"] == "blocked"
    assert result.state["blockers"]
    assert result.state["blockers"][0]["stage"] == "blocked"
