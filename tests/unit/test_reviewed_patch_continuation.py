"""A human-approved retained diff uses the original Graph and isolated applier."""
import json
import socket
from hashlib import sha256
from pathlib import Path

import pytest

from src.mod_agent.reviewed_patch_continuation import (
    apply_reviewed_patch,
    prepare_reviewed_patch_apply,
)
from tests.unit.test_dsh_review_run import _snapshot
from tests.unit.test_dsh_review_run import case as retained_case


@pytest.fixture(name="case")
def prepared_case(tmp_path):
    return retained_case.__wrapped__(tmp_path)


def _prepare(case, tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *args: pytest.fail("No network or model in approved continuation."))
    inputs, completed, config = case
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    selected = {**config, "isolated_root": str(isolated.resolve())}
    before = _snapshot(inputs.workspace)
    prepared = prepare_reviewed_patch_apply(**selected, operation_id="synthetic-explicit-approval")
    assert _snapshot(inputs.workspace) == before
    assert list(isolated.iterdir()) == []
    return inputs, completed, selected, prepared, before


def test_reviewed_diff_explicit_approval_reaches_original_graph_apply_and_stops_before_build(case, tmp_path, monkeypatch):
    inputs, completed, selected, prepared, before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "synthetic-human"}

    result = apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)

    assert result["status"] == "applied_in_isolation", result
    assert result["model_calls_performed"] == result["builds_performed"] == result["runtime_executions_performed"] == 0
    assert result["next_nodes"] == ["build"]
    assert [row["node_name"] for row in result["trace_events"] if row["event_type"] == "node_started"] == [
        "dry_run_apply", "isolated_apply"]
    assert result["source_workspace_written"] is False and _snapshot(inputs.workspace) == before
    assert result["product_source_writes_performed"] is True
    parent = json.loads(Path(completed.attempt_receipt["path"]).read_text(encoding="utf-8"))
    summary = result["execution_trace"]
    assert summary["mode"] == "local_only" and summary["cloud_readback"] == "not_performed"
    assert summary["session_id"] == parent["execution_trace"]["session_id"]
    assert summary["trace_id"] != parent["execution_trace"]["trace_id"]
    observations = result["execution_observations"]
    roots = [row for row in observations.values() if row["parent_id"] is None]
    assert len(roots) == 1 and roots[0]["attributes"]["workflow_status"] == "applied_in_isolation"
    assert not any(row["kind"] == "generation" for row in observations.values())
    assert {row["attributes"]["workflow_node"] for row in observations.values()
            if "workflow_node" in row["attributes"]} == {"dry_run_apply", "isolated_apply"}
    for row in observations.values():
        assert row["trace_id"] == summary["trace_id"] and row["status"] == "completed"
        assert row["started_at"] and row["finished_at"] and row["elapsed_ms"] >= 0
        if row["parent_id"] is not None:
            assert row["parent_id"] in observations
    retained = json.loads((Path(result["isolated_workspace"]) / "reviewed-apply-result.json").read_text(encoding="utf-8"))
    assert retained == result
    applied = json.loads(Path(result["isolated_apply_result"]["path"]).read_text(encoding="utf-8"))["data"]
    assert applied["human_semantic_decision"] == decision
    assert applied["approved_diff_hash"] == prepared["diff_hash"]
    dry = json.loads(Path(completed.dry_run_artifact["path"]).read_text(encoding="utf-8"))["data"]
    for change in dry["changes"]:
        assert sha256((Path(result["isolated_workspace"]) / change["path"]).read_bytes()).hexdigest() == change["raw_after_sha256"]


def test_explicit_rejection_keeps_original_artifacts_and_workspace_unmodified(case, tmp_path, monkeypatch):
    inputs, _completed, selected, prepared, before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "reject", "reviewer_identity": "synthetic-human"}
    store_before = _snapshot(inputs.store.root)

    result = apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)

    assert result["status"] == "rejected" and result["product_source_writes_performed"] is False
    assert result["artifact_writes_performed"] is False
    assert _snapshot(inputs.workspace) == before and _snapshot(inputs.store.root) == store_before
    assert not Path(binding["isolated_workspace"]).exists()


def test_source_drift_invalidates_displayed_approval_before_isolation_copy(case, tmp_path, monkeypatch):
    inputs, _completed, selected, prepared, _before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "synthetic-human"}
    inputs.behavior.write_bytes(inputs.behavior.read_bytes() + b"\n// human changed source\n")
    changed = _snapshot(inputs.workspace)

    with pytest.raises(ValueError, match="APPLY_REVIEW_SOURCE_CHANGED"):
        apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)

    assert _snapshot(inputs.workspace) == changed
    assert not Path(binding["isolated_workspace"]).exists()


def test_non_code_project_file_change_invalidates_full_copy_binding(case, tmp_path, monkeypatch):
    inputs, _completed, selected, prepared, _before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "synthetic-human"}
    (inputs.workspace / "project-settings.json").write_text('{"changed":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="APPLY_DISPLAY_BINDING_STALE"):
        apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)

    assert not Path(binding["isolated_workspace"]).exists()


def test_exact_decision_cannot_be_replaced_or_reused_for_another_diff(case, tmp_path, monkeypatch):
    inputs, _completed, selected, prepared, before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve",
                "reviewer_identity": "synthetic-human", "diff_hash": "0" * 64}
    store_before = _snapshot(inputs.store.root)

    with pytest.raises(RuntimeError, match="diff_hash does not match"):
        apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)

    assert _snapshot(inputs.workspace) == before and _snapshot(inputs.store.root) == store_before
    assert not Path(binding["isolated_workspace"]).exists()


def test_interruption_closes_prospective_trace_and_propagates_without_creating_output(case, tmp_path, monkeypatch):
    import src.mod_agent.reviewed_patch_continuation as owner

    inputs, _completed, selected, prepared, before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "synthetic-human"}
    interruption = KeyboardInterrupt("offline interruption before physical copy")

    def interrupt_copy(*args, **kwargs):
        raise interruption

    monkeypatch.setattr(owner.shutil, "copytree", interrupt_copy)
    with pytest.raises(KeyboardInterrupt) as captured:
        apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)

    assert captured.value is interruption
    assert interruption.execution_trace["mode"] == "local_only"
    rows = list(interruption.execution_observations.values())
    assert len(rows) == 1 and rows[0]["parent_id"] is None
    assert rows[0]["status"] == "failed" and rows[0]["finished_at"] is not None
    assert rows[0]["attributes"]["exception_type"] == "KeyboardInterrupt"
    assert _snapshot(inputs.workspace) == before
    assert not Path(binding["isolated_workspace"]).exists()


def test_review_and_apply_do_not_consume_non_authoritative_execution_query(case, tmp_path, monkeypatch):
    import src.observability.patch_execution_index as read_query

    def forbidden_query(*args, **kwargs):
        raise AssertionError("A read-only query cannot decide approval or execution inputs.")

    monkeypatch.setattr(read_query, "project_patch_executions", forbidden_query)
    inputs, completed, selected, prepared, before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    assert binding["journal_sha256"] == sha256(Path(completed.attempt_receipt["path"]).read_bytes()).hexdigest()
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "synthetic-human"}

    result = apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)

    assert result["status"] == "applied_in_isolation"
    assert _snapshot(inputs.workspace) == before
