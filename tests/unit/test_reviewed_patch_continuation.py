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
            if "workflow_node" in row["attributes"] and row["name"] != "workflow.route"} == {"dry_run_apply", "isolated_apply"}
    # Resuming after Review selects its outgoing route without re-executing
    # Review. A route observation must not be counted as an executed node.
    assert any(row["name"] == "workflow.route"
               and row["attributes"].get("from_node") == "review_proposal"
               and row["attributes"].get("selected_next_node") == "dry_run_apply"
               for row in observations.values())
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


def test_approved_apply_checkpoint_continues_original_build_without_reapplying(case, tmp_path, monkeypatch):
    """The injected unit compiler checks the applied input, never launches a process."""
    import src.mod_agent.reviewed_patch_continuation as owner
    from src.mod_agent.artifacts import ArtifactRef
    from src.mod_agent.build.adapter import BuildAdapter, BuildCommandResult, BuildProfile
    from src.mod_agent.workflow.interrupts import ResumePayload

    inputs, completed, selected, prepared, before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "synthetic-human"}
    applied = apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)
    checkpoint_ref = ArtifactRef(**applied["workflow_checkpoint"])
    checkpoint = inputs.store.read(checkpoint_ref)["data"]
    resume = ResumePayload(resume_id="synthetic-build-1", run_id=checkpoint["run_id"],
        request_id=checkpoint["request_id"], feature_id=checkpoint["feature_id"],
        stage=checkpoint["checkpoint_stage"], decision="approve", approved_by="synthetic-human",
        approved_at="2026-09-08T00:00:00Z", artifact_refs=tuple(checkpoint["artifact_refs"]),
        diff_hash=applied["diff_hash"])
    calls = []

    def compile_applied(destination, feature_id, mode):
        calls.append((destination, feature_id, mode))
        assert destination == Path(applied["isolated_workspace"])
        dry = inputs.store.read(ArtifactRef(**completed.dry_run_artifact))["data"]
        for change in dry["changes"]:
            assert sha256((destination / change["path"]).read_bytes()).hexdigest() == change["raw_after_sha256"]
        profile = BuildProfile(profile_id="injected-unit-compiler", build_system="unit",
            working_directory=str(destination), command=("injected-unit-compiler",),
            timeout_seconds=1, expected_artifacts=("bin/verified.dll",))

        def command_runner(_profile):
            output = destination / "bin" / "verified.dll"
            output.parent.mkdir()
            output.write_bytes(b"injected unit compiler output")
            return BuildCommandResult(exit_code=0)

        return BuildAdapter().run_local(feature_id=feature_id, profile=profile,
            command_runner=command_runner, allow_execution=True, input_execution_mode=mode)

    monkeypatch.setattr(owner.shutil, "copytree", lambda *a, **k: pytest.fail("Build resume must not repeat Apply."))
    built = owner.continue_reviewed_patch(artifact_store_root=str(inputs.store.root),
        checkpoint_ref=checkpoint_ref, resume_payload=resume, allow_build=True,
        build_result_factory=compile_applied)

    assert built["status"] == "built", built
    assert built["builds_performed"] == 1
    assert built["model_calls_performed"] == built["runtime_executions_performed"] == 0
    assert built["product_source_writes_performed"] is False
    assert len(calls) == 1 and calls[0][2] == "isolated_apply"
    assert _snapshot(inputs.workspace) == before
    build_ref = ArtifactRef(**built["build_result"])
    document = inputs.store.read(build_ref)
    assert any(row["artifact_hash"] == applied["isolated_apply_result"]["artifact_hash"]
        for row in document["inputs"]["upstream_artifacts"])
    runtime_checkpoint = inputs.store.read(ArtifactRef(**built["workflow_checkpoint"]))["data"]
    assert runtime_checkpoint["checkpoint_stage"] == "build"
    assert runtime_checkpoint["resume_binding"]["build_result_hash"] == build_ref.artifact_hash
    repeated = owner.continue_reviewed_patch(artifact_store_root=str(inputs.store.root),
        checkpoint_ref=checkpoint_ref, resume_payload=resume, allow_build=True,
        build_result_factory=compile_applied)
    assert repeated["status"] == "blocked"
    assert len(calls) == 1


def _build_continuation_case(case, tmp_path, monkeypatch):
    from src.mod_agent.artifacts import ArtifactRef
    from src.mod_agent.workflow.interrupts import ResumePayload

    inputs, _completed, selected, prepared, before = _prepare(case, tmp_path, monkeypatch)
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "synthetic-human"}
    applied = apply_reviewed_patch(**selected, displayed_binding=binding, human_semantic_decision=decision)
    checkpoint_ref = ArtifactRef(**applied["workflow_checkpoint"])
    checkpoint = inputs.store.read(checkpoint_ref)["data"]
    payload = ResumePayload(resume_id="synthetic-build-boundary", run_id=checkpoint["run_id"],
        request_id=checkpoint["request_id"], feature_id=checkpoint["feature_id"],
        stage=checkpoint["checkpoint_stage"], decision="approve", approved_by="synthetic-human",
        approved_at="2026-09-08T00:00:00Z", artifact_refs=tuple(checkpoint["artifact_refs"]),
        diff_hash=applied["diff_hash"])
    args = {"artifact_store_root": str(inputs.store.root), "checkpoint_ref": checkpoint_ref,
            "resume_payload": payload, "allow_build": True}
    return inputs, applied, args, before


def _injected_build(destination, feature_id, mode, *, exit_code=0, output_root=None):
    """Use the original BuildAdapter with a unit-only file-writing command runner."""
    from src.mod_agent.build.adapter import BuildAdapter, BuildCommandResult, BuildProfile

    root = destination if output_root is None else output_root
    profile = BuildProfile(profile_id="injected-unit-compiler", build_system="unit",
        working_directory=str(root), command=("injected-unit-compiler",),
        timeout_seconds=1, expected_artifacts=("bin/verified.dll",))

    def command_runner(_profile):
        if exit_code == 0:
            output = root / "bin" / "verified.dll"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"injected unit compiler output")
        return BuildCommandResult(exit_code=exit_code,
            stderr="BoundInput.cs(1,1): error CS1002: ; expected" if exit_code else "")

    return BuildAdapter().run_local(feature_id=feature_id, profile=profile,
        command_runner=command_runner, allow_execution=True, input_execution_mode=mode)


@pytest.mark.parametrize("selection,code", [
    ({"allow_build": False}, "REVIEWED_BUILD_AUTHORIZATION_REQUIRED"),
    ({"build_result_factory": None}, "REVIEWED_BUILD_FACTORY_REQUIRED"),
])
def test_build_continuation_requires_explicit_authorization_and_adapter(case, tmp_path, monkeypatch, selection, code):
    import src.mod_agent.reviewed_patch_continuation as owner

    inputs, _applied, args, _before = _build_continuation_case(case, tmp_path, monkeypatch)
    unchanged = _snapshot(tmp_path)
    with pytest.raises(ValueError, match=code):
        owner.continue_reviewed_patch(**{**args, "build_result_factory": _injected_build, **selection})
    assert _snapshot(tmp_path) == unchanged


@pytest.mark.parametrize("changed,code", [
    ("original", "REVIEWED_BUILD_ORIGINAL_SOURCE_CHANGED"),
    ("isolated", "REVIEWED_BUILD_APPLIED_SOURCE_CHANGED"),
])
def test_build_continuation_rechecks_full_source_identity_before_effect(case, tmp_path, monkeypatch, changed, code):
    import src.mod_agent.reviewed_patch_continuation as owner

    inputs, applied, args, _before = _build_continuation_case(case, tmp_path, monkeypatch)
    root = inputs.workspace if changed == "original" else Path(applied["isolated_workspace"])
    (root / "project-settings.json").write_text('{"changed":true}', encoding="utf-8")
    unchanged = _snapshot(tmp_path)
    with pytest.raises(ValueError, match=code):
        owner.continue_reviewed_patch(**args,
            build_result_factory=lambda *a: pytest.fail("No build after input drift."))
    assert _snapshot(tmp_path) == unchanged


def test_build_rejection_does_not_invoke_build(case, tmp_path, monkeypatch):
    from dataclasses import replace

    import src.mod_agent.reviewed_patch_continuation as owner

    inputs, _applied, args, before = _build_continuation_case(case, tmp_path, monkeypatch)
    args["resume_payload"] = replace(args["resume_payload"], decision="reject")
    result = owner.continue_reviewed_patch(**args,
        build_result_factory=lambda *a: pytest.fail("Rejected Build cannot execute."))
    assert result["status"] == "rejected" and result["builds_performed"] == 0
    assert result["build_result"] is result["workflow_checkpoint"] is None
    assert _snapshot(inputs.workspace) == before


def test_failed_build_is_bound_to_current_apply_and_stops_without_repair(case, tmp_path, monkeypatch):
    import src.mod_agent.reviewed_patch_continuation as owner
    from src.mod_agent.artifacts import ArtifactRef

    inputs, applied, args, before = _build_continuation_case(case, tmp_path, monkeypatch)
    result = owner.continue_reviewed_patch(**args,
        build_result_factory=lambda destination, feature_id, mode: _injected_build(
            destination, feature_id, mode, exit_code=1))
    assert result["status"] == "failed" and result["stopped_before"] == "repair_plan"
    assert result["workflow_checkpoint"] is None
    assert result["builds_performed"] == 1 and result["model_calls_performed"] == 0
    build = inputs.store.read(ArtifactRef(**result["build_result"]))
    assert build["data"]["status"] == "failed"
    assert build["data"]["diagnostics"][0]["code"] == "CS1002"
    assert any(row["artifact_hash"] == applied["isolated_apply_result"]["artifact_hash"]
        for row in build["inputs"]["upstream_artifacts"])
    assert [row["node_name"] for row in result["trace_events"] if row["event_type"] == "node_started"][-1] == "build"
    assert _snapshot(inputs.workspace) == before


@pytest.mark.parametrize("invalid,code", [
    ("supplied", "REVIEWED_BUILD_RESULT_IDENTITY_MISMATCH"),
    ("outside", "REVIEWED_BUILD_PROFILE_OUTSIDE_APPLIED_WORKSPACE"),
    ("modified_input", "REVIEWED_BUILD_INPUT_CHANGED_DURING_BUILD"),
])
def test_invalid_build_output_cannot_create_runtime_handoff_or_repeat_effect(case, tmp_path, monkeypatch, invalid, code):
    from dataclasses import replace

    import src.mod_agent.reviewed_patch_continuation as owner

    inputs, applied, args, _before = _build_continuation_case(case, tmp_path, monkeypatch)
    calls = []

    def invalid_build(destination, feature_id, mode):
        calls.append(destination)
        result = _injected_build(destination, feature_id, mode,
            output_root=tmp_path / "outside" if invalid == "outside" else None)
        if invalid == "supplied":
            return replace(result, execution_mode="supplied_output", real_build_performed=False)
        if invalid == "modified_input":
            relative = inputs.behavior.relative_to(inputs.workspace)
            (destination / relative).write_text("changed after compiler invocation", encoding="utf-8")
        return result

    with pytest.raises(ValueError, match=code) as captured:
        owner.continue_reviewed_patch(**args, build_result_factory=invalid_build)
    assert captured.value.resume_report is not None
    assert not inputs.store.list_feature_artifact_revisions(args["checkpoint_ref"].feature_id, "build_result")
    if invalid == "modified_input":
        with pytest.raises(ValueError, match="REVIEWED_BUILD_APPLIED_SOURCE_CHANGED"):
            owner.continue_reviewed_patch(**args, build_result_factory=invalid_build)
    else:
        repeated = owner.continue_reviewed_patch(**args, build_result_factory=invalid_build)
        assert repeated["status"] == "blocked"
        assert repeated["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"
    assert len(calls) == 1


def test_new_proposal_revision_requires_review_and_approval_before_build(case, tmp_path, monkeypatch):
    import src.mod_agent.reviewed_patch_continuation as owner
    from src.mod_agent.artifacts import ArtifactRef

    inputs, _applied, args, _before = _build_continuation_case(case, tmp_path, monkeypatch)
    state = inputs.store.read(args["checkpoint_ref"])["data"]["state_snapshot"]
    previous = inputs.store.read(ArtifactRef(feature_id=args["checkpoint_ref"].feature_id,
        artifact_type="patch_proposal", path=state["artifacts"]["patch_proposal"],
        artifact_hash=state["artifact_hashes"]["patch_proposal"]))
    payload = dict(previous["data"])
    payload["message"] = "A new proposal revision must obtain its own review and exact approval."
    inputs.store.write(feature_id=args["checkpoint_ref"].feature_id, artifact_type="patch_proposal",
        payload=payload, upstream_refs=[ArtifactRef(feature_id=args["checkpoint_ref"].feature_id,
            artifact_type=row["artifact_type"], path=row["path"], artifact_hash=row["artifact_hash"])
            for row in previous["inputs"]["upstream_artifacts"]])
    result = owner.continue_reviewed_patch(**args,
        build_result_factory=lambda *a: pytest.fail("Old approval cannot Build a new proposal revision."))
    assert result["status"] == "blocked"
    assert result["blockers"][0]["code"] == "STALE_RESUME_REJECTED"


def test_build_checkpoint_is_accepted_by_existing_runtime_handoff_loader(case, tmp_path, monkeypatch):
    import src.mod_agent.reviewed_patch_continuation as owner
    from src.mod_agent.local_entry import _load_runtime_continuation_handoff

    inputs, applied, args, _before = _build_continuation_case(case, tmp_path, monkeypatch)
    built = owner.continue_reviewed_patch(**args, build_result_factory=_injected_build)
    handoff = built["workflow_checkpoint"]
    loaded = _load_runtime_continuation_handoff(run_root=applied["isolated_workspace"],
        artifact_store_root=str(inputs.store.root), feature_id=handoff["feature_id"],
        checkpoint_path=handoff["path"], checkpoint_hash=handoff["artifact_hash"], require_manifest=False)
    assert loaded.checkpoint_ref.artifact_hash == handoff["artifact_hash"]


@pytest.mark.parametrize("field,value,code", [
    ("diff_hash", "sha256:" + "0" * 64, "REVIEWED_BUILD_DIFF_IDENTITY_MISMATCH"),
    ("request_id", "different-request", "REVIEWED_BUILD_RESUME_IDENTITY_MISMATCH"),
])
def test_build_resume_cannot_substitute_approved_identity(case, tmp_path, monkeypatch, field, value, code):
    from dataclasses import replace

    import src.mod_agent.reviewed_patch_continuation as owner

    _inputs, _applied, args, _before = _build_continuation_case(case, tmp_path, monkeypatch)
    args["resume_payload"] = replace(args["resume_payload"], **{field: value})
    unchanged = _snapshot(tmp_path)
    with pytest.raises(ValueError, match=code):
        owner.continue_reviewed_patch(**args,
            build_result_factory=lambda *a: pytest.fail("Mismatched Build identity must not execute."))
    assert _snapshot(tmp_path) == unchanged


def test_interrupted_build_consumes_resume_and_cannot_be_automatically_replayed(case, tmp_path, monkeypatch):
    import src.mod_agent.reviewed_patch_continuation as owner

    _inputs, _applied, args, _before = _build_continuation_case(case, tmp_path, monkeypatch)
    calls = []
    interrupted = KeyboardInterrupt("unit compiler stopped after invocation")

    def interrupt_build(*values):
        calls.append(values)
        raise interrupted

    with pytest.raises(KeyboardInterrupt) as caught:
        owner.continue_reviewed_patch(**args, build_result_factory=interrupt_build)
    assert caught.value is interrupted and interrupted.resume_report is not None
    assert any(row["status"] == "failed" for row in interrupted.execution_observations.values())
    repeated = owner.continue_reviewed_patch(**args, build_result_factory=interrupt_build)
    assert repeated["status"] == "blocked"
    assert repeated["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"
    assert len(calls) == 1
