"""Product trace lifecycle with actual clocks/recorders and offline business fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.core.trace.execution_trace import ExecutionTrace, current_trace, trace_operation
from src.mod_agent.patch_execution_trace import (
    PatchExecutionTraceConfiguration, product_execution_trace, product_trace_identity,
)


def _manifest(tmp_path, run_id="run-1", request_id="request-1"):
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps({"run_id": run_id, "request_id": request_id, "status": "prepared"}))
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _scope(tmp_path, **kwargs):
    return product_execution_trace(run_root=tmp_path, run_id="run-1", request_id="request-1",
                                   artifact_store_root=tmp_path / "store", **kwargs)


def test_named_generation_requires_real_transport_and_default_is_unchanged():
    trace = ExecutionTrace("trace", "session", "test")
    with trace.model_call(generation_name="requirements.project") as call:
        call.update(admission="blocked")
    assert not any(s["data"]["kind"] == "generation" for s in trace.context.stages)
    trace = ExecutionTrace("trace-2", "session", "test")
    with trace.activate():
        with trace.model_call(generation_name="requirements.findings") as call:
            call.transport_started()
        with trace.model_call() as patch:
            patch.transport_started()
    rows = {s["data"]["id"]: s["data"] for s in trace.context.stages}.values()
    assert {r["name"] for r in rows if r["kind"] == "generation"} == {
        "requirements.findings", "patch.generate"}


@pytest.mark.parametrize("terminal", ["done", "blocked", "awaiting_approval"])
def test_product_scope_persists_upstream_and_terminal_without_inventing_patch(tmp_path, terminal):
    manifest = _manifest(tmp_path)
    with _scope(tmp_path) as trace:
        with trace_operation("requirements.coverage") as span:
            span.update(relationship="missing", decision_reason="Required source evidence was absent.")
        # Exercise the same owner persistence routine used on normal/early returns.
        from src.mod_agent.local_entry import _persist_graph_terminal_result
        summary = {"current_stage": terminal, "execution_trace": product_trace_identity(trace, tmp_path)}
        _persist_graph_terminal_result(run_root=tmp_path, run_id="run-1", request_id="request-1",
            summary=summary, model_call_count=0, patch_payload_parser_entered=False,
            actual_write_performed=False)
    document = _read(manifest)
    rows = list(document["execution_observations"].values())
    root = next(r for r in rows if r["parent_id"] is None)
    assert root["name"] == "product.execution"
    assert root["attributes"]["workflow_status"] == terminal
    assert root["attributes"]["terminal_stage"] == terminal
    assert root["attributes"]["terminal_record_ref"] == document["terminal_record"]
    assert not any(r["kind"] == "generation" or r["name"].startswith("patch.") for r in rows)
    assert all(r["finished_at"] and r["elapsed_ms"] >= 0 for r in rows)
    assert all(r["attributes"]["trace_scope"] == "product_execution" for r in rows)
    assert document["execution_trace"]["mode"] == "local_only"
    assert current_trace() is None
    result_path = Path(document["terminal_record"]["path"])
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == document["terminal_record"]["sha256"]
    assert _read(result_path)["execution_trace"]["trace_id"] == trace.context.trace_id


def test_product_exception_keeps_original_failure_and_partial_observations(tmp_path):
    manifest = _manifest(tmp_path)
    error = RuntimeError("original business failure")
    with pytest.raises(RuntimeError) as raised:
        with _scope(tmp_path):
            with trace_operation("planning.decision"):
                from src.mod_agent.local_entry import _persist_graph_terminal_failure
                _persist_graph_terminal_failure(run_root=tmp_path, run_id="run-1", request_id="request-1",
                    error=error, model_call_count=0)
                raise error
    assert raised.value is error
    document = _read(manifest)
    root = next(r for r in document["execution_observations"].values() if r["parent_id"] is None)
    assert root["status"] == "failed" and root["attributes"]["exception_type"] == "RuntimeError"
    assert root["attributes"]["terminal_record_ref"] == document["terminal_record"]
    assert _read(Path(document["terminal_record"]["path"]))["error"] == str(error)
    assert current_trace() is None


def test_scoped_worker_recorder_does_not_receive_upstream_or_later_siblings():
    upstream, worker = [], []
    trace = ExecutionTrace("trace", "session", "test", recorder=upstream.append)
    with trace.activate():
        with trace.model_call(generation_name="requirements.findings") as call:
            call.transport_started()
        with trace.record_scope(worker.append):
            with trace_operation("patch.worker"):
                with trace.model_call() as call:
                    call.transport_started()
        with trace_operation("review"):
            pass
    assert {r["name"] for r in worker} == {"patch.worker", "model.request", "patch.generate"}
    assert {r["name"] for r in upstream} > {r["name"] for r in worker}
    assert all(r["trace_id"] == "trace" for r in upstream + worker)


def test_observation_write_and_export_failure_cannot_damage_original_manifest(tmp_path, monkeypatch):
    manifest = _manifest(tmp_path)
    before = manifest.read_bytes()
    original_write = Path.write_text
    def failing_write(path, *args, **kwargs):
        if path.name == ".run_manifest.trace.tmp":
            raise OSError("disk failure")
        return original_write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", failing_write)
    class FailedSink:
        def publish(self, row):
            raise RuntimeError("unavailable")
        def shutdown(self, **kwargs):
            raise RuntimeError("unavailable")
    with _scope(tmp_path, configuration=PatchExecutionTraceConfiguration(sink=FailedSink())) as trace:
        with trace_operation("requirements.projection"):
            outcome = "business result preserved"
    assert outcome == "business result preserved" and manifest.read_bytes() == before
    assert trace.failure_statistics()["recorder"]["total"] > 0
    assert trace.failure_statistics()["sink"]["total"] > 0
    assert current_trace() is None


def test_same_logical_request_across_runs_shares_session_but_not_trace(tmp_path):
    config = PatchExecutionTraceConfiguration()
    args = dict(feature_id=None, artifact_store_root=tmp_path, recorder=None, request_id="request-1")
    first = config.make_trace(run_id="first", **args)
    second = config.make_trace(run_id="second", **args)
    assert first.session_id == second.session_id and first.context.trace_id != second.context.trace_id
    assert first.session_id.startswith("request-")


def test_physical_product_retry_is_unique_while_legacy_patch_id_remains_unchanged(tmp_path):
    config = PatchExecutionTraceConfiguration()
    args = dict(run_id="reused-run", request_id="logical-request", feature_id=None,
                artifact_store_root=tmp_path, recorder=None, root_name="product.execution")
    first = config.make_trace(**args)
    retry = config.make_trace(**args)
    other_store = config.make_trace(**{**args, "artifact_store_root": tmp_path / "other"})
    other_request = config.make_trace(**{**args, "request_id": "different-request"})
    assert len({row.context.trace_id for row in (first, retry, other_store, other_request)}) == 4
    assert first.session_id == retry.session_id
    assert len({first.session_id, other_store.session_id, other_request.session_id}) == 3
    assert first.context.metadata["execution_identity"] == {
        "artifact_store_root": str(tmp_path.resolve()), "run_id": "reused-run", "request_id": "logical-request"}
    legacy = config.make_trace(run_id="old-run", feature_id="old-feature", artifact_store_root=tmp_path, recorder=None)
    assert legacy.context.trace_id == hashlib.sha256(b"live:old-run").hexdigest()[:32]


@pytest.mark.parametrize("mismatch", [None, "request_id", "run_id", "artifact_store_root"])
def test_nested_request_worker_reuses_only_matching_product_trace_and_shutdown_occurs_once(tmp_path, mismatch):
    from src.mod_agent.request_patch_execution import RequestPatchExecution
    from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
    from tests.unit.test_fresh_planning_continuation import _inputs, _local_patch_adapter, _patch_request

    inputs = _inputs(tmp_path / "fixture")
    adapter, _ = _local_patch_adapter(inputs)
    request = _patch_request(inputs)
    refs = (inputs.feature_ref, inputs.evidence_ref, request.implementation_plan_ref)
    state = {"run_id": "run-1", "request_id": "request-1", "feature_id": inputs.feature_ref.feature_id,
             "retry_count": 0, "current_stage": "implementation_plan",
             "artifacts": {r.artifact_type: r.path for r in refs},
             "artifact_hashes": {r.artifact_type: r.artifact_hash for r in refs}}
    class Sink:
        shutdown_count = 0
        def publish(self, row):
            pass
        def shutdown(self, **kwargs):
            self.shutdown_count += 1
            return {"status": "complete"}
    sink = Sink()
    class Worker:
        _recovery_observation_bytes = 0
        def __init__(self, **kwargs):
            pass
        def bind_attempt_recorder(self, recorder):
            self.recorder = recorder
        def bind_upstream_effects(self, effects):
            pass
        def patch_attempt_receipt(self):
            return {}
        def __call__(self, *args):
            with trace_operation("patch.worker"):
                with current_trace().model_call() as call:
                    call.transport_started()
            return []
    config = PatchExecutionTraceConfiguration(sink=sink)
    execution = RequestPatchExecution(artifact_store=inputs.store, workspace_root=inputs.workspace,
        profile=adapter.profile, identity_reader=adapter.identity_reader, policy=PatchAgentLoopPolicy(),
        reserve_model_call=lambda role: None,
        budget_snapshot=lambda: {"remaining": 5, "by_stage": {"initial_patch": {"remaining": 5}}},
        adapter_factory=Worker, trace_configuration=config)
    _manifest(tmp_path)
    parent_identity = {"run_id": "run-1", "request_id": "request-1", "artifact_store_root": inputs.store.root}
    if mismatch is not None:
        parent_identity[mismatch] = tmp_path / "another-store" if mismatch == "artifact_store_root" else "another-task"
    _manifest(tmp_path, parent_identity["run_id"], parent_identity["request_id"])
    with product_execution_trace(run_root=tmp_path, configuration=config, **parent_identity) as trace:
        with trace.model_call(generation_name="planning.select") as call:
            call.transport_started()
        execution(state, inputs.store.read(request.implementation_plan_ref)["data"], inputs.store.read(inputs.evidence_ref)["data"])
        assert current_trace() is trace and trace.context.finished_at is None
        assert sink.shutdown_count == 0
        with trace_operation("review"):
            pass
    assert sink.shutdown_count == 1
    journal = _read(execution.journals[0].path)
    assert (journal["execution_trace"]["trace_id"] == trace.context.trace_id) == (mismatch is None)
    assert journal["execution_trace"]["logical_request_id"] == "request-1"
    rows = list(journal["execution_observations"].values())
    assert [r["name"] for r in rows if r["kind"] == "generation"] == ["patch.generate"]
    assert not any(r["name"] in {"planning.select", "review", "product.execution"} for r in rows)
    parent_rows = list(_read(tmp_path / "run_manifest.json")["execution_observations"].values())
    parent_generations = [r["name"] for r in parent_rows if r["kind"] == "generation"]
    assert parent_generations == (["planning.select", "patch.generate"] if mismatch is None else ["planning.select"])


def test_deferred_approval_and_build_keep_logical_session_and_distinct_invocation_traces(tmp_path):
    from dataclasses import replace
    from src.mod_agent.artifacts import ArtifactRef
    from src.mod_agent.reviewed_patch_continuation import resume_deferred_approval, continue_reviewed_patch
    from tests.unit.test_deferred_product_approval import _pending_case
    from tests.unit.test_reviewed_patch_continuation import _injected_build

    case, pending, payload, human = _pending_case(tmp_path)
    configuration = PatchExecutionTraceConfiguration()
    parent = configuration.make_trace(run_id=case.request.run_id, feature_id=pending.checkpoint_ref.feature_id,
        request_id=case.request.request_id, artifact_store_root=case.store.root, recorder=None)
    applied = resume_deferred_approval(artifact_store_root=str(case.store.root),
        checkpoint_ref=pending.checkpoint_ref, resume_payload=payload, human_semantic_decision=human)
    checkpoint_ref = ArtifactRef(**applied["workflow_checkpoint"])
    checkpoint = case.store.read(checkpoint_ref)["data"]
    build_payload = replace(payload, resume_id="separate-build-invocation", stage="isolated_apply",
                            artifact_refs=tuple(checkpoint["artifact_refs"]))
    built = continue_reviewed_patch(artifact_store_root=str(case.store.root), checkpoint_ref=checkpoint_ref,
        resume_payload=build_payload, allow_build=True, build_result_factory=_injected_build)
    assert applied["status"] == "applied_in_isolation" and built["status"] == "built"
    assert applied["execution_trace"]["session_id"] == built["execution_trace"]["session_id"] == parent.session_id
    assert len({parent.context.trace_id, applied["execution_trace"]["trace_id"], built["execution_trace"]["trace_id"]}) == 3
    assert applied["run_id"] == built["run_id"] == case.request.run_id
    assert built["execution_trace"]["logical_request_id"] == case.request.request_id


def test_reviewed_saved_output_reuses_only_exact_bound_logical_request(tmp_path, monkeypatch):
    from tests.unit.test_dsh_review_run import case as original_case
    from tests.unit.test_reviewed_patch_continuation import _build_continuation_case, _injected_build
    from src.mod_agent.reviewed_patch_continuation import continue_reviewed_patch, _retained_trace_request_id

    case = original_case.__wrapped__(tmp_path / "fixture")
    inputs, completed, _ = case
    path = Path(completed.attempt_receipt["path"])
    document = _read(path)
    logical_id = document["request_id"]
    document["execution_trace"]["logical_request_id"] = logical_id
    path.write_text(json.dumps(document), encoding="utf-8")
    args = (str(inputs.store.root), inputs.feature_ref.feature_id, document["run_id"])
    assert _retained_trace_request_id(*args, hashlib.sha256(path.read_bytes()).hexdigest()) == logical_id
    assert _retained_trace_request_id(*args, "0" * 64) is None
    _, applied, build_args, _ = _build_continuation_case(case, tmp_path, monkeypatch)
    built = continue_reviewed_patch(**build_args, build_result_factory=_injected_build)
    expected = PatchExecutionTraceConfiguration().make_trace(run_id="other-process",
        feature_id=inputs.feature_ref.feature_id, request_id=logical_id,
        artifact_store_root=inputs.store.root, recorder=None)
    assert applied["execution_trace"]["session_id"] == built["execution_trace"]["session_id"] == expected.session_id
    assert applied["execution_trace"]["trace_id"] != built["execution_trace"]["trace_id"]
