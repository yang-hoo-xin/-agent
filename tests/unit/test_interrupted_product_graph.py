from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, replace

import pytest

from src.mod_agent.product_execution import (
    ProductExecutionContractError, ProductExecutionGraphModeV1, ProductExecutionResultV1,
)
from src.mod_agent.product_executor import ProductApprovalDeferred, execute_product_execution, preflight_product_execution
from src.mod_agent.workflow.graph import _validate_product_graph_start
from src.mod_agent.workflow.state import create_initial_state
from tests.unit.test_product_execution import _request, _successful_compile_adapters


def _selected(tmp_path, monkeypatch):
    request, store = _request(tmp_path)
    adapters = _successful_compile_adapters(request, physical_apply=True)
    def interrupted(*args):
        raise RuntimeError("test stops before Patch output")
    initial = replace(adapters, patch_change_factory=interrupted)
    result = execute_product_execution(preflight_product_execution(request, initial, store), initial, store)
    refs = {row.artifact_role: asdict(row.artifact_ref) for row in result.outputs
            if row.artifact_role in {"feature_spec", "evidence_pack", "implementation_plan"}}
    assert len(refs) == 3
    admitted = {"selected_artifacts": refs, "feature_id": result.feature_id, "request_id": request.request_id,
                "parent_run_id": request.run_id, "user_request": request.user_request,
                "feature_spec": next(store.semantic_read_immutable(row.artifact_ref)["data"]
                                     for row in result.outputs if row.artifact_role == "feature_spec")}
    def save(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    selection = {"source_attempt_ref": save("source_attempt.json", {
        "selected_artifacts": refs, "feature_id": result.feature_id, "request_id": request.request_id,
        "parent_run_id": request.run_id}), "parent_manifest_ref": save("parent_manifest.json", {
        "run_id": request.run_id, "request_id": request.request_id})}
    selection["execution_stop_ref"] = save("stop.json", {**selection,
        "original_execution_stopped": True, "origin": "host_controller"})
    calls = []
    def admission(selected, **kwargs):
        assert selected == selection
        calls.append(kwargs)
        return copy.deepcopy(admitted)
    monkeypatch.setattr("src.mod_agent.interrupted_patch_admission.admit_interrupted_patch", admission)
    def forbidden(*args):
        raise AssertionError("Initial projection, retrieval and planning must not rerun")
    continued = replace(adapters, evidence_pack_factory=forbidden, planning_target_selection_factory=forbidden)
    return request, store, continued, admitted, selection, calls


def test_interrupted_product_graph_reuses_inputs_and_reaches_exact_approval(tmp_path, monkeypatch):
    request, store, adapters, admitted, selection, calls = _selected(tmp_path, monkeypatch)
    before = tuple((store.root).rglob("*"))
    with pytest.raises(ProductApprovalDeferred) as caught:
        execute_product_execution(preflight_product_execution(request, adapters, store), adapters, store,
                                  defer_approval=True, interrupted_patch_selection=selection)
    paused = caught.value
    assert len(calls) == 2
    assert [row.artifact_role for row in paused.outputs[:3]] == ["feature_spec", "evidence_pack", "implementation_plan"]
    assert all(row.origin == "reused_input" and row.reuse_selection == selection for row in paused.outputs[:3])
    assert [row.artifact_role for row in paused.outputs[3:]] == ["patch_proposal", "proposal_review", "dry_run_result"]
    assert [row.sequence for row in paused.outputs] == list(range(6))
    assert set(row.effect_role for row in paused.effect_events) == {"patch_generation", "dry_run"}
    assert store.semantic_read_immutable(paused.dry_run_ref)["data"]["actual_write_performed"] is False
    assert (store.root.parent / "generated_mods/Example/Plugin.cs").read_text() == "sealed class Plugin {}\n"
    assert before


def test_interrupted_product_result_roundtrips_without_invented_store_attempts(tmp_path, monkeypatch):
    request, store, adapters, admitted, selection, calls = _selected(tmp_path, monkeypatch)
    result = execute_product_execution(preflight_product_execution(request, adapters, store), adapters, store,
                                       interrupted_patch_selection=selection)
    assert result.execution_disposition == "succeeded"
    assert result.store_attempts[0].node_name == "generate_patch_proposal"
    assert result.store_attempts[0].sequence == 3
    assert all(row.node_name != "interrupted_patch_admission" for row in result.store_attempts)
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result
    changed = result.to_dict()
    changed["outputs"][0]["reuse_selection"]["source_attempt_ref"]["sha256"] = "b" * 64
    with pytest.raises(ProductExecutionContractError, match="reused inputs"):
        ProductExecutionResultV1.from_dict(changed)

    changed = copy.deepcopy(result.to_dict())
    for output in changed["outputs"][:3]:
        output["reuse_selection"]["source_attempt_ref"]["sha256"] = "c" * 64
    with pytest.raises(ProductExecutionContractError, match="exact original records"):
        ProductExecutionResultV1.from_dict(changed)

    changed = copy.deepcopy(result.to_dict())
    # A self-consistent output/readback mutation still disagrees with the retained journal.
    # 为什么要有它：结果中的origin和自身引用链不能代替原中断记录所绑定的输入身份。
    changed["outputs"][0]["artifact_ref"]["artifact_hash"] = "d" * 64
    readback = next(row["payload"] for row in changed["validation_facts"]["details"] if row["detail_kind"] == "output_readback")
    readback[0]["artifact_hash"] = "d" * 64
    for row in readback[1]["inputs"]["upstream_artifacts"]:
        if row["artifact_type"] == "feature_spec":
            row["artifact_hash"] = "d" * 64
    with pytest.raises(ProductExecutionContractError, match="reused inputs"):
        ProductExecutionResultV1.from_dict(changed)


@pytest.mark.parametrize("field,value", [
    ("retry_count", 1), ("approvals", {"confirmed_write": True, "dry_run": True}),
    ("runtime_summary", {"patch_upstream_return": True}), ("artifact_hashes", {}),
    ("feature_id", "other"), ("current_stage", "repair_plan"),
])
def test_interrupted_graph_start_rejects_injected_state(tmp_path, monkeypatch, field, value):
    request, store, adapters, admitted, selection, calls = _selected(tmp_path, monkeypatch)
    state = create_initial_state(run_id=request.run_id, request_id=request.request_id, user_request=request.user_request,
        target_domain=request.target_domain, target_mod=request.target_mod, confirmed_isolated_write=True)
    state.update(feature_id=admitted["feature_id"], risk_level=admitted["feature_spec"]["risk_level"],
        current_stage="implementation_plan", next_stage="patch_proposal",
        artifacts={key: ref["path"] for key, ref in admitted["selected_artifacts"].items()},
        artifact_hashes={key: ref["artifact_hash"] for key, ref in admitted["selected_artifacts"].items()})
    mode = ProductExecutionGraphModeV1(contract_version="1", request=request, interrupted_patch_selection=selection)
    assert _validate_product_graph_start(state, mode, store) == "continue"
    state[field] = value
    with pytest.raises(ProductExecutionContractError):
        _validate_product_graph_start(state, mode, store)


def test_interrupted_graph_start_rechecks_admission_after_executor_read(tmp_path, monkeypatch):
    request, store, adapters, admitted, selection, calls = _selected(tmp_path, monkeypatch)
    count = 0
    def drifting(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("INTERRUPTED_PATCH_SOURCE_CHANGED")
        return admitted
    monkeypatch.setattr("src.mod_agent.interrupted_patch_admission.admit_interrupted_patch", drifting)
    with pytest.raises(ProductExecutionContractError) as caught:
        execute_product_execution(preflight_product_execution(request, adapters, store), adapters, store,
                                  defer_approval=True, interrupted_patch_selection=selection)
    assert "START admission changed" in str(caught.value)
    assert caught.value.side_effects_may_have_started is False
    assert count == 2


def test_interrupted_selection_forbids_free_state(tmp_path):
    request, store = _request(tmp_path)
    with pytest.raises(ProductExecutionContractError, match="three exact references"):
        ProductExecutionGraphModeV1(contract_version="1", request=request,
                                   interrupted_patch_selection={"state": {"approvals": {"dry_run": True}}})
