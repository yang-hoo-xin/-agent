"""Tests for Phase A2 workflow state primitives."""

from __future__ import annotations

import pytest

from src.mod_agent.workflow.state import (
    StateOwnershipPolicy,
    create_initial_state,
)


def test_create_initial_state_uses_request_planning_stage() -> None:
    """A new run starts at the request planning stage with empty refs."""

    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make enemies glow",
        target_domain="gtfo",
    )

    assert state["run_id"] == "run_001"
    assert state["request_id"] == "req_001"
    assert state["feature_id"] is None
    assert state["current_stage"] == "request_planning"
    assert state["target_domain"] == "gtfo"
    assert state["artifacts"] == {}
    assert state["artifact_hashes"] == {}
    assert state["blockers"] == []
    assert state["trace_events"] == []
    assert state["retry_count"] == 0


def test_state_ownership_policy_allows_declared_writer() -> None:
    """A field can be written only by declared workflow components."""

    assert StateOwnershipPolicy.can_write("feature_id", "plan_request") is True
    assert (
        StateOwnershipPolicy.can_write("feature_id", "verification_only_admission")
        is True
    )
    assert StateOwnershipPolicy.can_write("feature_id", "retrieve_evidence") is False
    assert (
        StateOwnershipPolicy.can_write(
            "evidence_summary",
            "verification_only_admission",
        )
        is True
    )
    assert (
        StateOwnershipPolicy.can_write(
            "review_summary",
            "verification_only_admission",
        )
        is False
    )
    assert StateOwnershipPolicy.can_write("artifacts", "artifact_producing_node") is True
    assert StateOwnershipPolicy.can_write("approvals", "interrupt_resume_handler") is True
    for terminal_writer in ("evaluate", "done", "blocked"):
        assert (
            StateOwnershipPolicy.can_write("runtime_summary", terminal_writer)
            is True
        )


def test_state_ownership_policy_rejects_unknown_field() -> None:
    """Unknown state fields are not silently accepted."""

    with pytest.raises(KeyError, match="Unknown ModAgentState field"):
        StateOwnershipPolicy.allowed_writers("hidden_business_result")
