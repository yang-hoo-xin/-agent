"""No-network acceptance of a passed Proposal's separate behavior-failure recovery."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationError,
    preflight_patch_continuation,
    run_fresh_patch_continuation,
)
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _local_patch_adapter,
    _patch_request,
    _PatchAgentTurnClient,
    _source_hashes,
)
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle, _sha


def _file_ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _repair_case(tmp_path):
    inputs = _inputs(tmp_path)
    request = _patch_request(inputs)
    adapter, _ = _local_patch_adapter(inputs)
    parent = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace))
    assert parent.status == "terminal"
    proposal = inputs.store.semantic_read_immutable(ArtifactRef(**parent.patch_proposal_artifact))["data"]
    receipt = json.loads(Path(parent.attempt_receipt["path"]).read_text())
    response = receipt["factory_receipt"]["model_response"]
    # The original materializer's compatibility fields are absent from Proposal
    # display metadata. Restore the known synthetic fixture's native projection.
    native = [{
        "change_id": change["change_id"], "change_type": change["change_type"],
        "edit_binding_id": change["edit_binding_id"],
        "supporting_binding_ids": change["supporting_binding_ids"],
        "operation": "exact_text_replace", "rationale": change["rationale"],
        "risk_tags": ["medium"], "expected_validation": change["expected_validation"],
        "rollback_hint": change["rollback_hint"], "patch": change["patch"],
    } for change in proposal["diff_intent"]]
    plan = inputs.store.semantic_read_immutable(request.implementation_plan_ref)["data"]
    inspector = PlanBoundSourceInspector(workspace_root=inputs.workspace,
        implementation_plan=plan, policy=PatchAgentLoopPolicy())
    observed = all("RecordRepairMarker();" in item["patch"]["after_text"] for item in native)
    assert not observed
    report = {
        "status": "behavior_failed", "failure_owner": "patch_implementation",
        "owner_binding_ids": [native[0]["edit_binding_id"]],
        "observations": [{"check_id": "synthetic_repair_marker", "input": {"enabled": True},
            "expected": {"recorded": True}, "observed": {"recorded": observed}}],
        "generated_changes_sha256": _sha(native),
        "source_snapshot_sha256": inspector.source_snapshot_sha256,
    }
    report_path = tmp_path / "post-proposal-behavior.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    recovery = replace(request,
        repair_parent_proposal_ref=ArtifactRef(**parent.patch_proposal_artifact),
        repair_parent_review_ref=ArtifactRef(**parent.proposal_review_artifact),
        repair_failure_report_ref=_file_ref(report_path),
        repair_parent_response_ref={"path": response["path"], "sha256": response["output_sha256"]},
        repair_parent_attempt_ref=_file_ref(Path(parent.attempt_receipt["path"])),
        attempt_id="synthetic-behavior-recovery-1",
    )
    return inputs, recovery, parent


class _RecoveryClient(_PatchAgentTurnClient):
    def complete_turn(self, request):
        response = super().complete_turn(request)
        if response.content:
            return replace(response, content=response.content.replace(
                "RecordRuntimeMarker();", "RecordRuntimeMarker();\\n        RecordRepairMarker();"))
        return response


@pytest.mark.parametrize("owner,status", [("patch_implementation", "behavior_failed"), ("unknown", "needs_evidence")])
def test_passed_proposal_behavior_failure_enters_repair_and_complete_patch(tmp_path, owner, status):
    inputs, request, parent = _repair_case(tmp_path)
    if owner == "unknown":
        path = Path(request.repair_failure_report_ref["path"])
        report = json.loads(path.read_text())
        report.update(status=status, failure_owner=owner, owner_binding_ids=[])
        path.write_text(json.dumps(report))
        request = replace(request, repair_failure_report_ref=_file_ref(path))
    before = _source_hashes(inputs.workspace)
    old_review_bytes = Path(parent.proposal_review_artifact["path"]).read_bytes()
    admitted = preflight_patch_continuation(request)
    assert admitted.repair_context["parent_review_decision"] == "approve_dry_run"
    client = _RecoveryClient()
    oracle = _BehaviorOracle(tmp_path / "verification")
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.status == "terminal", result.to_dict()
    assert len(client.requests) == 2
    assert _source_hashes(inputs.workspace) == before
    assert Path(parent.proposal_review_artifact["path"]).read_bytes() == old_review_bytes
    receipt = json.loads(Path(result.attempt_receipt["path"]).read_text())
    repair = inputs.store.semantic_read_immutable(ArtifactRef(**receipt["artifacts"]["repair_plan"]))
    assert repair["data"]["failure_source"] == "behavior_report"
    assert repair["data"]["semantic_decision"]["decision"] == ("investigation_ready" if owner == "unknown" else "repair_ready")
    proposal = inputs.store.semantic_read_immutable(ArtifactRef(**result.patch_proposal_artifact))
    lineage = proposal["data"]["context_pack"]["repair_lineage"]
    assert lineage["parent_proposal"]["artifact_hash"] == parent.patch_proposal_artifact["artifact_hash"]
    assert lineage["approval_inherited"] is False
    assert {row["edit_binding_id"] for row in proposal["data"]["diff_intent"]} == set(admitted.repair_context["allowed_edit_binding_ids"])
    assert result.patch_proposal_artifact["artifact_hash"] != parent.patch_proposal_artifact["artifact_hash"]
    assert result.execution_counts["apply"] == result.execution_counts["build"] == result.execution_counts["runtime"] == 0
    saved_receipt_bytes = Path(result.attempt_receipt["path"]).read_bytes()
    replay = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert replay.to_dict() == result.to_dict()
    assert len(client.requests) == 2
    assert Path(result.attempt_receipt["path"]).read_bytes() == saved_receipt_bytes
    reset_budget = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=4)
    assert reset_budget.first_failure["code"] == "PATCH_CONTINUATION_ATTEMPT_IDENTITY_CONFLICT"
    assert len(client.requests) == 2
    next_report = json.loads(Path(request.repair_failure_report_ref["path"]).read_text())
    next_report["generated_changes_sha256"] = oracle.contexts[-1]["generated_changes_sha256"]
    next_path = tmp_path / "next-independent-behavior-finding.json"
    next_path.write_text(json.dumps(next_report))
    latest_response = receipt["factory_receipt"]["model_response"]
    next_request = replace(request, attempt_id="next-separately-selected-repair",
        repair_parent_proposal_ref=ArtifactRef(**result.patch_proposal_artifact),
        repair_parent_review_ref=ArtifactRef(**result.proposal_review_artifact),
        repair_parent_attempt_ref=_file_ref(Path(result.attempt_receipt["path"])),
        repair_parent_response_ref={"path": latest_response["path"], "sha256": latest_response["output_sha256"]},
        repair_failure_report_ref=_file_ref(next_path))
    assert preflight_patch_continuation(next_request).repair_context["parent_retry_count"] == 1


def test_interrupted_attempt_does_not_reset_budget_or_resend(tmp_path):
    from src.mod_agent.fresh_planning_continuation import PatchContinuationAttemptJournal
    inputs, request, _ = _repair_case(tmp_path)
    admitted = preflight_patch_continuation(request)
    run_id = "patch_continuation_" + hashlib.sha256(request.attempt_id.encode()).hexdigest()
    journal = PatchContinuationAttemptJournal(artifact_root=inputs.store.root,
        run_id=run_id, request_id="interrupted-request", request=request,
        admitted=admitted, max_model_calls=5)
    journal.record({"phase": "local_patch_worker_turn_requested", "model_call_count": 2})
    before = journal.path.read_bytes()
    calls = []
    result = run_fresh_patch_continuation(request, patch_change_factory=lambda *_args: calls.append(True),
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.first_failure["code"] == "PATCH_CONTINUATION_ATTEMPT_RECOVERY_REQUIRED"
    assert result.execution_counts["model"] == 2
    assert not calls and journal.path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["hash", "native_identity", "raw_response", "baseline"])
def test_repair_identity_mismatch_prevents_model_invocation(tmp_path, mutation):
    inputs, request, _ = _repair_case(tmp_path)
    if mutation == "hash":
        request = replace(request, repair_failure_report_ref={**request.repair_failure_report_ref, "sha256": "0" * 64})
    elif mutation == "native_identity":
        path = Path(request.repair_failure_report_ref["path"])
        report = json.loads(path.read_text())
        report["generated_changes_sha256"] = "0" * 64
        path.write_text(json.dumps(report))
        request = replace(request, repair_failure_report_ref=_file_ref(path))
    elif mutation == "raw_response":
        request = replace(request, repair_parent_response_ref={**request.repair_parent_response_ref, "sha256": "0" * 64})
    else:
        inputs.behavior.write_text(inputs.behavior.read_text() + "\n// drift")
    with pytest.raises(PatchContinuationError):
        preflight_patch_continuation(request)


@pytest.mark.parametrize("owner,binding,code", [
    ("planning", "edit_binding_001", "PATCH_REPAIR_REPLAN_REQUIRED"),
    ("patch_implementation", "outside_existing_plan", "PATCH_REPAIR_REPLAN_REQUIRED"),
    ("evidence", "edit_binding_001", "PATCH_REPAIR_EVIDENCE_REQUIRED"),
    ("validator", "edit_binding_001", "PATCH_REPAIR_VERIFIER_REQUIRED"),
])
def test_repair_upstream_decision_is_persisted_without_generation(tmp_path, owner, binding, code):
    inputs, request, _ = _repair_case(tmp_path)
    path = Path(request.repair_failure_report_ref["path"])
    report = json.loads(path.read_text())
    report.update(failure_owner=owner, owner_binding_ids=[binding])
    path.write_text(json.dumps(report))
    request = replace(request, repair_failure_report_ref=_file_ref(path))
    calls = []
    result = run_fresh_patch_continuation(request, patch_change_factory=lambda *_args: calls.append(True),
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.first_failure["code"] == code, result.to_dict()
    assert not calls
    assert result.patch_proposal_artifact is None
    assert result.proposal_review_artifact is None
    receipt = json.loads(Path(result.attempt_receipt["path"]).read_text())
    assert receipt["repair_semantic_decision"]["decision"] != "repair_ready"
