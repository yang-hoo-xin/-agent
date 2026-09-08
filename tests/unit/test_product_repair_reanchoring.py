"""Graph-owned C1 identities from actual temporary Apply and compiler test doubles."""

import hashlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.workflow import graph
from tests.unit.test_request_patch_repair_context import (  # noqa: F401
    _arguments,
    _read,
    applied_build_repair,
)

# Re-export the shared fixture for pytest's fixture discovery.
__all__ = ["applied_build_repair"]


def test_graph_reanchors_applied_repair_without_replanning_or_widening(applied_build_repair):
    inputs, _, parent, state = applied_build_repair
    old_plan = _read(inputs, state, "implementation_plan")
    old_evidence = _read(inputs, state, "evidence_pack")
    before = inputs.behavior.read_bytes()
    original_state = deepcopy(state)
    current = graph._reanchor_applied_product_repair(state, inputs.store, workspace_root=inputs.workspace)
    assert current["current_stage"] == "repair_plan" and not current["blockers"]
    assert current["retry_count"] == state["retry_count"]
    assert current["artifact_hashes"]["implementation_plan"] != state["artifact_hashes"]["implementation_plan"]
    plan = _read(inputs, current, "implementation_plan")
    evidence = _read(inputs, current, "evidence_pack")
    old_binding = old_plan["binding_registry"]["edit_bindings"][0]
    new_binding = plan["binding_registry"]["edit_bindings"][0]
    assert new_binding["binding_id"] == old_binding["binding_id"]
    assert new_binding["canonical_target_path"] == old_binding["canonical_target_path"]
    assert new_binding["source_hash"] == hashlib.sha256(before).hexdigest()
    assert new_binding["target_span"]["start_line"] == old_binding["target_span"]["start_line"]
    assert new_binding["target_span"]["end_line"] == old_binding["target_span"]["end_line"] + 1
    assert plan["proposed_changes"] == old_plan["proposed_changes"]
    assert evidence["requirement_coverage"] == old_evidence["requirement_coverage"]
    assert evidence["provenance_validation"]["repair_source_reanchoring"]["findings_reexecuted"] is False
    assert current["approvals"] == state["approvals"]
    assert inputs.behavior.read_bytes() == before and state == original_state
    for kind in ("patch_proposal", "proposal_review", "isolated_apply_result", "build_result", "repair_plan"):
        assert current["artifacts"][kind] == state["artifacts"][kind]
    from src.mod_agent.request_patch_execution import admit_product_repair_context
    admitted = admit_product_repair_context(**_arguments(inputs, current, parent))
    assert admitted["base_relationship"] == "revision_against_verified_applied_parent"
    assert admitted["approval_inherited"] is False


def _envelope(inputs, state, kind):
    return inputs.store.semantic_read_immutable(ArtifactRef(feature_id=state["feature_id"],
        artifact_type=kind, path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind]))


def _revision_count(inputs):
    return len(list(inputs.store.root.glob("features/*/r/*/*.json")))


def test_reanchored_revisions_keep_direct_contract_upstreams_and_repair_trace(applied_build_repair, monkeypatch):
    inputs, _, _, state = applied_build_repair
    old_plan = _read(inputs, state, "implementation_plan")
    monkeypatch.setattr(graph.ImplementationPlanner, "build", lambda *_args, **_kwargs: pytest.fail("Must not rerun Planning"))
    current = graph._reanchor_applied_product_repair(state, inputs.store, workspace_root=inputs.workspace)
    evidence, plan = (_envelope(inputs, current, kind) for kind in ("evidence_pack", "implementation_plan"))
    assert {row["artifact_type"] for row in evidence["inputs"]["upstream_artifacts"]} == {"feature_spec"}
    assert {row["artifact_type"] for row in plan["inputs"]["upstream_artifacts"]} == {"feature_spec", "evidence_pack"}
    assert next(row for row in plan["inputs"]["upstream_artifacts"] if row["artifact_type"] == "evidence_pack")["artifact_hash"] == current["artifact_hashes"]["evidence_pack"]
    assert f"{state['artifacts']['repair_plan']}#sha256={state['artifact_hashes']['repair_plan']}" in evidence["data"]["trace_refs"]
    for field in ("target_files", "target_symbols", "proposed_changes", "side_effect_boundaries", "test_plan", "rollback_plan"):
        assert plan["data"][field] == old_plan[field]
    refreshed = evidence["data"]["provenance_validation"]["repair_source_reanchoring"]
    assert refreshed["planning_model_reexecuted"] is refreshed["approval_inherited"] is False
    for item in evidence["data"]["items"]:
        if item["source_type"] == "target_source":
            raw = (inputs.workspace / item["source_path"]).read_bytes()
            span = item["span"]
            assert item["excerpt"] == b"".join(raw.splitlines(keepends=True)[span["start_line"] - 1:span["end_line"]]).decode("utf-8")


@pytest.mark.parametrize("target", ["applied_file", "supporting_file"])
def test_drift_rejects_before_any_new_evidence_or_plan_commit(applied_build_repair, target):
    inputs, _, _, state = applied_build_repair
    path = inputs.behavior
    if target == "supporting_file":
        evidence = _read(inputs, state, "evidence_pack")
        item = next(item for item in evidence["items"] if item["source_type"] == "target_source"
                    and inputs.workspace / item["source_path"] != inputs.behavior)
        path = inputs.workspace / item["source_path"]
    path.write_bytes(path.read_bytes() + b"\n// unrelated source drift\n")
    count = _revision_count(inputs)
    with pytest.raises(ValueError):
        graph._reanchor_applied_product_repair(state, inputs.store, workspace_root=inputs.workspace)
    assert _revision_count(inputs) == count


def _replace_revision(inputs, state, kind, mutate, *, replace_upstream=None):
    envelope = _envelope(inputs, state, kind)
    data = deepcopy(envelope["data"])
    mutate(data)
    refs = [ArtifactRef(feature_id=state["feature_id"], artifact_type=row["artifact_type"],
        path=row["path"], artifact_hash=row["artifact_hash"]) for row in envelope["inputs"]["upstream_artifacts"]]
    if replace_upstream is not None:
        refs = [replace_upstream if ref.artifact_type == replace_upstream.artifact_type else ref for ref in refs]
    ref = inputs.store.write(feature_id=state["feature_id"], artifact_type=kind, payload=data,
        status=envelope["status"], upstream_refs=refs,
        exact_revision_upstream_types={row.artifact_type for row in refs})
    state["artifacts"][kind], state["artifact_hashes"][kind] = ref.path, ref.artifact_hash
    return ref


@pytest.mark.parametrize("missing", ["approval", "receipts"])
def test_unapproved_or_unobserved_apply_is_not_source_reanchoring_authority(applied_build_repair, missing):
    inputs, _, _, state = applied_build_repair
    state = deepcopy(state)
    update = (lambda value: value.update(approved_by_user=False)) if missing == "approval" else (lambda value: value.pop("changes"))
    apply_ref = _replace_revision(inputs, state, "isolated_apply_result", update)
    build_ref = _replace_revision(inputs, state, "build_result", lambda _value: None, replace_upstream=apply_ref)
    _replace_revision(inputs, state, "repair_plan", lambda _value: None, replace_upstream=build_ref)
    count = _revision_count(inputs)
    with pytest.raises(ValueError, match="exact approved written bytes" if missing == "approval" else "real before/after receipts"):
        graph._reanchor_applied_product_repair(state, inputs.store, workspace_root=inputs.workspace)
    assert _revision_count(inputs) == count


def test_current_plan_cannot_expand_repair_allowed_bindings(applied_build_repair):
    inputs, _, _, state = applied_build_repair
    state = deepcopy(state)
    _replace_revision(inputs, state, "repair_plan", lambda value: value.update(allowed_edit_binding_ids=[]))
    count = _revision_count(inputs)
    with pytest.raises(ValueError, match="admitted binding IDs"):
        graph._reanchor_applied_product_repair(state, inputs.store, workspace_root=inputs.workspace)
    assert _revision_count(inputs) == count


@pytest.mark.parametrize("drift", [False, True])
def test_product_graph_repair_owner_publishes_current_refs_or_durable_blocker(applied_build_repair, drift):
    inputs, _, _, state = applied_build_repair
    build_state = deepcopy(state)
    build_state.update(current_stage="build", retry_count=0)
    if drift:
        inputs.behavior.write_bytes(inputs.behavior.read_bytes() + b"\n// unapproved edit\n")
    mode = SimpleNamespace(request=SimpleNamespace(isolated_workspace_root=str(inputs.workspace)))
    current = graph._run_create_repair_plan(build_state, inputs.store, product_execution_mode=mode)
    assert current["current_stage"] == "repair_plan" and current["retry_count"] == 1
    repair = _envelope(inputs, current, "repair_plan")
    if drift:
        assert current["blockers"][-1]["code"] == "PRODUCT_REPAIR_SOURCE_REANCHORING_REQUIRED"
        from src.mod_agent.workflow.nodes import StubNodeRunner
        from src.mod_agent.workflow.transitions import route_after_repair_plan
        assert route_after_repair_plan(current) == "blocked"
        assert repair["status"] == "success"  # Retained semantic decision, never an inherited approval.
        blocked = StubNodeRunner(inputs.store).run("blocked", current)
        assert blocked.artifact_ref.artifact_type == "blocked_report"
        saved = inputs.store.read(blocked.artifact_ref)["data"]
        assert saved["blockers"][-1]["code"] == "PRODUCT_REPAIR_SOURCE_REANCHORING_REQUIRED"
        assert current["artifacts"]["implementation_plan"] == state["artifacts"]["implementation_plan"]
    else:
        assert not current["blockers"] and repair["status"] == "success"
        assert current["artifacts"]["implementation_plan"] != state["artifacts"]["implementation_plan"]
    assert Path(state["artifacts"]["build_result"]).is_file()


def _physical_product(tmp_path, *, omit_receipts=False):
    from src.mod_agent.product_execution import ProductExecutionRequestV1
    from tests.unit.test_product_execution import (
        _request,
        _successful_compile_adapters,
        execute_product_execution,
        preflight_product_execution,
        source_snapshot,
        source_snapshot_sha256,
    )

    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_bytes(b"public void Load() {}\n")
    value = request.to_dict()
    value["isolated_source_snapshot_sha256"] = source_snapshot_sha256(source_snapshot(Path(request.isolated_target_root)))
    request = ProductExecutionRequestV1.from_dict(value)
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 0], physical_apply=True)
    if omit_receipts:
        original = adapters.isolated_apply_factory
        def without_receipt(*args):
            observed = original(*args)
            observed.pop("changes")
            return observed
        adapters = replace(adapters, isolated_apply_factory=without_receipt)
    return execute_product_execution(preflight_product_execution(request, adapters, store), adapters, store)


def test_physical_store_scope_does_not_allow_real_repeated_planning_nodes(tmp_path):
    from src.mod_agent.product_execution import (
        ProductExecutionContractError,
        ProductExecutionResultV1,
    )

    result = _physical_product(tmp_path)
    assert result.execution_disposition == "succeeded"
    value = result.to_dict()
    for field in ("store_attempts", "outputs"):
        item = next(row for row in value[field] if row["node_name"] == "create_repair_plan"
                    and row["artifact_role"] == "evidence_pack")
        item.update(node_name="retrieve_evidence", phase="evidence")
    with pytest.raises(ProductExecutionContractError, match="Planning/evidence nodes cannot repeat"):
        ProductExecutionResultV1.from_dict(value)


def test_unobserved_apply_stops_at_existing_blocked_report_in_public_product(tmp_path):
    from src.mod_agent.product_execution import ProductExecutionResultV1

    result = _physical_product(tmp_path, omit_receipts=True)
    assert result.execution_disposition == "domain_blocked"
    assert result.platform_status == "completed"
    assert result.outputs[-1].artifact_role == "blocked_report"
    assert result.blockers[-1].code == "PRODUCT_REPAIR_SOURCE_REANCHORING_REQUIRED"
    assert not any(row.node_name == "create_repair_plan" and row.artifact_role in {"evidence_pack", "implementation_plan"}
                   for row in result.store_attempts)
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


def test_repair_writer_scope_rejects_old_findings_as_new_semantic_execution_before_store(applied_build_repair):
    from src.mod_agent.product_execution import ProductExecutionContractError
    from src.mod_agent.product_executor import _ProductStoreRecorder

    inputs, _, _, state = applied_build_repair
    recorder = _ProductStoreRecorder(inputs.store)
    envelope = _envelope(inputs, state, "repair_plan")
    refs = [ArtifactRef(feature_id=state["feature_id"], artifact_type=row["artifact_type"],
        path=row["path"], artifact_hash=row["artifact_hash"]) for row in envelope["inputs"]["upstream_artifacts"]]
    repair_ref = recorder.write(feature_id=state["feature_id"], artifact_type="repair_plan",
        payload=envelope["data"], status="success", upstream_refs=refs,
        exact_revision_upstream_types={ref.artifact_type for ref in refs})
    count = _revision_count(inputs)
    with pytest.raises(ProductExecutionContractError, match="new semantic model decision"):
        with recorder.repair_source_revision_scope(repair_ref):
            recorder.write(feature_id=state["feature_id"], artifact_type="evidence_pack",
                payload=_read(inputs, state, "evidence_pack"), status="success", upstream_refs=[inputs.feature_ref],
                trace_refs=[f"{repair_ref.path}#sha256={repair_ref.artifact_hash}"])
    assert _revision_count(inputs) == count
    assert recorder._repair_source_scope is None


def test_reanchoring_store_failure_is_not_reclassified_as_missing_source(applied_build_repair, monkeypatch):
    from src.mod_agent.artifacts import ArtifactStoreError

    inputs, _, _, state = applied_build_repair
    build_state = deepcopy(state)
    build_state.update(current_stage="build", retry_count=0)
    def failed_store(*_args, **_kwargs):
        raise ArtifactStoreError("explicit Store failure")
    monkeypatch.setattr(graph, "_reanchor_applied_product_repair", failed_store)
    mode = SimpleNamespace(request=SimpleNamespace(isolated_workspace_root=str(inputs.workspace)))
    with pytest.raises(ArtifactStoreError, match="explicit Store failure"):
        graph._run_create_repair_plan(build_state, inputs.store, product_execution_mode=mode)
