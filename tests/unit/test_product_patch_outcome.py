"""Product owner outcomes project to real journals; no model/compiler is run."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.fresh_planning_continuation import PatchContinuationAttemptJournal, _canonical_sha256
from src.mod_agent.product_executor import (
    ProductApprovalDeferred, execute_product_execution, preflight_product_execution,
)
from src.mod_agent.request_patch_execution import RequestPatchExecution
from src.mod_agent.reviewed_patch_continuation import review_run, _verified_terminal
from src.observability.patch_execution_index import project_patch_executions
from tests.unit.test_dsh_review_run import _snapshot
from tests.unit.test_product_execution import _formal_coverage_vertical_scenario


def _case(tmp_path):
    case = _formal_coverage_vertical_scenario(tmp_path)
    execution = RequestPatchExecution.__new__(RequestPatchExecution)
    execution.store = case.store
    execution.journals = []
    execution._repair_attempts = []
    execution.budget_snapshot = lambda: {"remaining": 0}
    original = case.adapters.patch_change_factory

    def worker(state, implementation, evidence):
        changes = original(state, implementation, evidence)
        # This explicit deterministic provider fixture preserves response/code
        # identity, but supplies no native transport observations or model claims.
        raw = json.dumps(changes, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        refs = {kind: ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
            path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind])
            for kind in ("feature_spec", "evidence_pack", "implementation_plan")}
        journal = PatchContinuationAttemptJournal.for_product_execution(
            artifact_root=case.store.root, workspace_root=case.request.isolated_workspace_root,
            run_id=state["run_id"] + "_patch_1", parent_run_id=state["run_id"],
            request_id=state["request_id"], max_model_calls=1,
            feature_spec_ref=refs["feature_spec"], evidence_pack_ref=refs["evidence_pack"],
            implementation_plan_ref=refs["implementation_plan"])
        response_path = tmp_path / "deterministic-provider-response.json"
        response_path.write_bytes(raw)
        journal.record({"phase": "local_patch_generation_completed", "factory_receipt": {
            "model_response": {"model": "deterministic-unit-fixture", "path": str(response_path),
                "output_sha256": digest, "output_utf8_bytes": len(raw), "retained": True},
            "model_call_count": 0}})
        execution.journals.append(journal)
        execution._repair_attempts.append(state["retry_count"])
        return tuple({**change, "generation": {"model_response_sha256": digest}} for change in changes)

    case.adapters = replace(case.adapters, patch_change_factory=worker)
    return case, execution


def _read_view(case, execution):
    document = json.loads(execution.journals[0].path.read_bytes())
    config = dict(artifact_store_root=str(case.store.root), workspace_root=case.request.isolated_workspace_root,
                  run_id=document["run_id"], feature_id=document["feature_id"])
    return document, config


def test_real_product_result_produces_segment_terminal_readable_by_existing_review(tmp_path, monkeypatch):
    case, execution = _case(tmp_path)

    def no_apply(*_args):
        raise ValueError("Unit fixture stops before source Apply.")

    case.adapters = replace(case.adapters, isolated_apply_factory=no_apply)
    preflight = preflight_product_execution(case.request, case.adapters, case.store)
    result = execute_product_execution(preflight, case.adapters, case.store)
    assert result.execution_disposition == "domain_blocked"
    execution.complete_product(result)
    document, config = _read_view(case, execution)
    terminal = _verified_terminal(document, config["feature_id"], config["run_id"])
    assert terminal["run_id"] != result.run_id
    assert terminal["status"] == "blocked"
    assert terminal["parent_product_run_id"] == result.run_id
    assert terminal["parent_product_result_identity"]["sha256"] == _canonical_sha256(result.to_dict())
    assert terminal["parent_product_result_identity"]["store_artifact"] is False
    assert "store_attempts" not in terminal and "outputs" not in terminal and "variant_result" not in terminal
    assert terminal["execution_counts"]["model"] is None
    assert terminal["execution_counts"]["apply"] is None  # Factory started; physical execution is unmeasured here.
    assert terminal["execution_counts"]["build"] == terminal["execution_counts"]["runtime"] == 0
    before = _snapshot(tmp_path)
    monkeypatch.setattr(ArtifactStore, "write", lambda *_args, **_kwargs: pytest.fail("Readback must not write Artifacts."))
    viewed = review_run(**config)
    assert viewed["status"] == "reviewable_diff", viewed
    assert viewed["apply_allowed"] is False and viewed["approval_created"] is False
    queried = project_patch_executions(case.store.root, run_id=config["run_id"])
    assert queried["match_count"] == 1
    assert queried["attempts"][0]["journal_identity_checks"]["terminal_result_hash"]["status"] == "verified"
    assert _snapshot(tmp_path) == before
    assert case.trace["build_calls"] == 0


def test_deferred_owner_keeps_exact_checkpoint_diff_and_zero_downstream_effects(tmp_path):
    case, execution = _case(tmp_path)
    preflight = preflight_product_execution(case.request, case.adapters, case.store)
    with pytest.raises(ProductApprovalDeferred) as caught:
        execute_product_execution(preflight, case.adapters, case.store, defer_approval=True)
    pending = caught.value
    execution.complete_deferred(pending)
    document, config = _read_view(case, execution)
    terminal = _verified_terminal(document, config["feature_id"], config["run_id"])
    assert document["status"] == terminal["status"] == "awaiting_approval"
    assert terminal["terminal_stage"] == "dry_run_apply" and terminal["stopped_before"] == "isolated_apply"
    assert terminal["workflow_checkpoint"]["artifact_hash"] == pending.checkpoint_ref.artifact_hash
    assert terminal["diff_hash"] == pending.to_dict()["diff_hash"]
    assert terminal["unified_diff_sha256"] == pending.to_dict()["unified_diff_sha256"]
    assert "unified_diff" not in terminal
    assert terminal["parent_product_result_identity"]["sha256"] == _canonical_sha256(pending.to_dict())
    assert all(terminal["execution_counts"][name] == 0 for name in ("apply", "build", "runtime"))
    assert terminal["approval_recorded"] is False
    before = _snapshot(tmp_path)
    viewed = review_run(**config)
    assert viewed["status"] == "reviewable_diff", viewed
    assert viewed["recorded_status"] == "awaiting_approval" and viewed["apply_allowed"] is False
    assert viewed["diff_hash"] == pending.to_dict()["diff_hash"]
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("mismatch", ["response", "repair_attempt"])
def test_segment_without_its_own_proposal_cannot_borrow_another_output(tmp_path, mismatch):
    case, execution = _case(tmp_path)
    preflight = preflight_product_execution(case.request, case.adapters, case.store)
    with pytest.raises(ProductApprovalDeferred) as caught:
        execute_product_execution(preflight, case.adapters, case.store, defer_approval=True)
    journal = execution.journals[0]
    if mismatch == "response":
        journal.record({"phase": "local_patch_generation_failed", "factory_receipt": {
            "model_response": {"output_sha256": "0" * 64}}})
    else:
        execution._repair_attempts[0] = 1
    execution.complete_deferred(caught.value)
    document, config = _read_view(case, execution)
    assert document["proposal_admitted"] is False
    assert document["terminal_result"]["patch_proposal_artifact"] is None
    assert document["terminal_result"]["proposal_review_artifact"] is None
    assert document["terminal_result"]["dry_run_artifact"] is None
    viewed = review_run(**config)
    assert viewed["status"] == "no_reviewable_diff" and viewed["reason"] == "THIS_RUN_HAS_NO_NEW_PROPOSAL"


def test_parent_identity_drift_rejects_before_terminal_write(tmp_path):
    case, execution = _case(tmp_path)
    preflight = preflight_product_execution(case.request, case.adapters, case.store)
    with pytest.raises(ProductApprovalDeferred) as caught:
        execute_product_execution(preflight, case.adapters, case.store, defer_approval=True)
    pending = caught.value
    pending.request = replace(pending.request, run_id="different_parent_run")
    before = execution.journals[0].path.read_bytes()
    with pytest.raises(ValueError, match="PRODUCT_PATCH_OUTCOME_PARENT_IDENTITY_MISMATCH"):
        execution.complete_deferred(pending)
    assert execution.journals[0].path.read_bytes() == before


def test_two_worker_segments_keep_proposal_review_and_dry_run_on_the_emitting_segment(tmp_path):
    case, execution = _case(tmp_path)
    preflight = preflight_product_execution(case.request, case.adapters, case.store)
    with pytest.raises(ProductApprovalDeferred) as caught:
        execute_product_execution(preflight, case.adapters, case.store, defer_approval=True)
    first = json.loads(execution.journals[0].path.read_bytes())
    selected = {kind: ArtifactRef(**ref) for kind, ref in first["selected_artifacts"].items()}
    second = PatchContinuationAttemptJournal.for_product_execution(
        artifact_root=case.store.root, workspace_root=case.request.isolated_workspace_root,
        run_id=case.request.run_id + "_patch_2", parent_run_id=case.request.run_id,
        request_id=case.request.request_id, max_model_calls=1,
        feature_spec_ref=selected["feature_spec"], evidence_pack_ref=selected["evidence_pack"],
        implementation_plan_ref=selected["implementation_plan"])
    second.record({"phase": "local_patch_generation_failed", "failure": {
        "code": "UNIT_WORKER_RESPONSE_REJECTED", "stage": "generate_patch_proposal"},
        "factory_receipt": {"model_response": {"output_sha256": "f" * 64}}})
    execution.journals.append(second)
    execution._repair_attempts.append(0)  # Even a shared retry ordinal cannot confer ownership.
    execution.complete_deferred(caught.value)
    first_document, config = _read_view(case, execution)
    first_view = review_run(**config)
    second_view = review_run(**dict(config, run_id=case.request.run_id + "_patch_2"))
    assert first_view["status"] == "reviewable_diff"
    assert set(first_view["artifacts"]) == {"patch_proposal", "proposal_review", "dry_run_result"}
    assert first_document["terminal_result"]["dry_run_artifact"]["artifact_hash"] == caught.value.dry_run_ref.artifact_hash
    second_document = json.loads(second.path.read_bytes())
    assert second_document["proposal_admitted"] is False
    assert all(second_document["terminal_result"][field] is None for field in (
        "patch_proposal_artifact", "proposal_review_artifact", "dry_run_artifact"))
    assert second_view["status"] == "no_reviewable_diff" and second_view["artifacts"] == {}
