"""A product task pauses after its real dry-run and resumes the same workspace."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent import product_executor
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.reviewed_patch_continuation import (
    continue_reviewed_patch,
    resume_deferred_approval,
)
from src.mod_agent.workflow.interrupts import ResumePayload
from tests.unit.test_product_execution import _formal_coverage_vertical_scenario
from tests.unit.test_reviewed_patch_continuation import _injected_build


def test_product_can_persist_pending_diff_without_rejection_apply_or_build(tmp_path):
    case = _formal_coverage_vertical_scenario(tmp_path)
    preflight = product_executor.preflight_product_execution(case.request, case.adapters, case.store)
    with pytest.raises(product_executor.ProductApprovalDeferred) as captured:
        product_executor.execute_product_execution(preflight, case.adapters, case.store, defer_approval=True)
    assert type(captured.value).__name__ == "ProductApprovalDeferred"
    pending = captured.value
    assert pending.to_dict()["status"] == "awaiting_approval"
    assert case.trace["apply_calls"] == case.trace["build_calls"] == 0
    assert case.target.read_bytes() == case.source_before
    assert case.canonical.read_bytes() == case.canonical_before
    checkpoint = case.store.read(pending.checkpoint_ref)["data"]
    assert checkpoint["checkpoint_stage"] == "dry_run_apply"
    assert "isolated_apply_result" not in checkpoint["state_snapshot"]["artifacts"]
    assert "build_result" not in checkpoint["state_snapshot"]["artifacts"]
    assert not any(row.effect_role == "isolated_apply" for row in pending.effect_events)
    assert not case.store.list_feature_artifact_revisions(pending.checkpoint_ref.feature_id, "resume_report")


def _pending_case(tmp_path):
    case = _formal_coverage_vertical_scenario(tmp_path)
    preflight = product_executor.preflight_product_execution(case.request, case.adapters, case.store)
    with pytest.raises(product_executor.ProductApprovalDeferred) as captured:
        product_executor.execute_product_execution(preflight, case.adapters, case.store, defer_approval=True)
    pending = captured.value
    checkpoint = case.store.read(pending.checkpoint_ref)["data"]
    payload = ResumePayload(resume_id="unit-deferred-approve", run_id=case.request.run_id,
        request_id=case.request.request_id, feature_id=pending.checkpoint_ref.feature_id,
        stage="dry_run_apply", decision="approve", approved_by="unit-human", approved_at="2026-09-08T00:00:00Z",
        artifact_refs=tuple(checkpoint["artifact_refs"]), diff_hash=pending.to_dict()["diff_hash"])
    human = {**pending.to_dict()["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "unit-human"}
    return case, pending, payload, human


def test_deferred_diff_resumes_same_workspace_and_then_existing_build_checkpoint(tmp_path, monkeypatch):
    import src.mod_agent.reviewed_patch_continuation as owner

    case, pending, payload, human = _pending_case(tmp_path)
    monkeypatch.setattr(owner.shutil, "copytree", lambda *a, **k: pytest.fail("A paused product keeps its existing workspace."))
    result = resume_deferred_approval(artifact_store_root=str(case.store.root), checkpoint_ref=pending.checkpoint_ref,
        resume_payload=payload, human_semantic_decision=human)
    assert result["status"] == "applied_in_isolation", result
    assert result["run_id"] == case.request.run_id
    assert result["isolated_workspace"] == case.request.isolated_workspace_root
    assert result["isolated_workspace_created"] is False
    assert case.target.read_bytes() == case.source_after
    assert case.canonical.read_bytes() == case.canonical_before
    assert result["builds_performed"] == 0 and result["next_nodes"] == ["build"]
    repeated = resume_deferred_approval(artifact_store_root=str(case.store.root), checkpoint_ref=pending.checkpoint_ref,
        resume_payload=payload, human_semantic_decision=human)
    assert repeated["status"] == "blocked" and repeated["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"
    build_checkpoint_ref = ArtifactRef(**result["workflow_checkpoint"])
    checkpoint = case.store.read(build_checkpoint_ref)["data"]
    build_payload = replace(payload, resume_id="unit-deferred-build", stage="isolated_apply",
        artifact_refs=tuple(checkpoint["artifact_refs"]))
    built = continue_reviewed_patch(artifact_store_root=str(case.store.root), checkpoint_ref=build_checkpoint_ref,
        resume_payload=build_payload, allow_build=True, build_result_factory=_injected_build)
    assert built["status"] == "built"
    assert built["run_id"] == case.request.run_id
    assert Path(built["isolated_workspace"]) == Path(case.request.isolated_workspace_root)


@pytest.mark.parametrize("change,reason", [
    ("source", "DEFERRED_APPROVAL_ORIGINAL_SOURCE_CHANGED"),
    ("isolated", "DEFERRED_APPROVAL_ISOLATED_SOURCE_CHANGED"),
    ("diff", "diff_hash does not match"),
])
def test_pending_approval_rechecks_sources_and_exact_human_diff(tmp_path, change, reason):
    case, pending, payload, human = _pending_case(tmp_path)
    if change == "source":
        case.canonical.write_bytes(b"source changed")
    elif change == "isolated":
        case.target.write_bytes(b"isolated source changed")
    else:
        human["diff_hash"] = "sha256:" + "0" * 64
    with pytest.raises((ValueError, RuntimeError), match=reason):
        resume_deferred_approval(artifact_store_root=str(case.store.root), checkpoint_ref=pending.checkpoint_ref,
            resume_payload=payload, human_semantic_decision=human)
    assert not case.store.list_feature_artifact_revisions(pending.checkpoint_ref.feature_id, "isolated_apply_result")
    assert not case.store.list_feature_artifact_revisions(pending.checkpoint_ref.feature_id, "resume_report")


def test_public_resume_approval_command_consumes_original_checkpoint_in_place(tmp_path, capsys):
    import json

    from src.mod_agent import cli

    case, pending, payload, human = _pending_case(tmp_path)
    resume_path = tmp_path / "human-resume.json"
    decision_path = tmp_path / "semantic-decision.json"
    resume_path.write_text(json.dumps(payload.to_dict()), encoding="utf-8")
    decision_path.write_text(json.dumps(human), encoding="utf-8")
    reference = pending.checkpoint_ref
    code = cli.main(["apply-patch", "--resume-approval", "--artifact-store-root", str(case.store.root),
        "--feature-id", reference.feature_id, "--checkpoint-path", reference.path,
        "--checkpoint-hash", reference.artifact_hash, "--resume-payload", str(resume_path),
        "--human-semantic-decision", str(decision_path)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["status"] == "applied_in_isolation", result
    assert result["run_id"] == case.request.run_id
    assert result["isolated_workspace_created"] is False and result["builds_performed"] == 0
    assert case.target.read_bytes() == case.source_after


def test_run_request_defer_flag_reports_intentional_pause_without_reading_stdin(tmp_path, monkeypatch, capsys):
    import json

    from src.mod_agent import cli

    case = _formal_coverage_vertical_scenario(tmp_path)

    def local_boundary(**kwargs):
        assert kwargs["defer_approval"] is True
        preflight = product_executor.preflight_product_execution(case.request, case.adapters, case.store)
        try:
            return product_executor.execute_product_execution(preflight, case.adapters, case.store,
                defer_approval=kwargs["defer_approval"])
        except product_executor.ProductApprovalDeferred as pending:
            return pending.to_dict()

    class UnreadStdin:
        def read(self, *args):
            pytest.fail("Deferred approval must not consume absent user input.")

    monkeypatch.setattr(cli, "run_local_request", local_boundary)
    monkeypatch.setattr(cli.sys, "stdin", UnreadStdin())
    assert cli.main(["run-request", "A request to be approved later", "--target-project", str(tmp_path),
        "--defer-approval"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "awaiting_approval"
    assert case.trace["apply_calls"] == case.trace["build_calls"] == 0


def test_explicit_rejection_is_preserved_and_writes_no_product_bytes(tmp_path):
    case, pending, payload, human = _pending_case(tmp_path)
    payload = replace(payload, decision="reject")
    human["decision"] = "reject"
    result = resume_deferred_approval(artifact_store_root=str(case.store.root), checkpoint_ref=pending.checkpoint_ref,
        resume_payload=payload, human_semantic_decision=human)
    assert result["status"] == "rejected"
    assert result["product_source_writes_performed"] is False
    assert case.target.read_bytes() == case.source_before
    assert not case.store.list_feature_artifact_revisions(pending.checkpoint_ref.feature_id, "isolated_apply_result")
