"""Bound delegation uses the real Apply/Graph owners and a controlled unit compiler."""
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from src.mod_agent import product_executor
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.execution.patch_apply import ExactTextPatchApplier, materialize_exact_text_patch
from src.mod_agent.execution.task_delegation import (
    ORIGIN,
    _scope,
    delegation_result_fields,
    has_verified_apply_authorization,
    prepare_task_delegation,
    validate_task_delegation,
)
from src.mod_agent.reviewed_patch_continuation import (
    continue_reviewed_patch,
    resume_deferred_approval,
)
from src.mod_agent.workflow.interrupts import ResumePayload
from tests.unit.test_product_execution import _formal_coverage_vertical_scenario
from tests.unit.test_reviewed_patch_continuation import _injected_build

CHECKS = ["fresh.default", "other.defaults", "all.keys", "saved.true", "saved.false"]
RESPONSE_HASH = hashlib.sha256(b"controlled unit response, not a model invocation").hexdigest()


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


def _pending(tmp_path):
    case = _formal_coverage_vertical_scenario(tmp_path)
    original_factory = case.adapters.patch_change_factory

    def controlled_patch(*args, **kwargs):
        changes = deepcopy(original_factory(*args, **kwargs))
        for change in changes:
            change["generation"] = {"model_response_sha256": RESPONSE_HASH,
                                    "origin": "controlled_unit_fixture"}
        return changes

    adapters = replace(case.adapters, patch_change_factory=controlled_patch)
    admitted = product_executor.preflight_product_execution(case.request, adapters, case.store)
    with pytest.raises(product_executor.ProductApprovalDeferred) as captured:
        product_executor.execute_product_execution(admitted, adapters, case.store, defer_approval=True)
    pending = captured.value
    checkpoint = case.store.read(pending.checkpoint_ref)["data"]
    state = checkpoint["state_snapshot"]
    refs = {kind: ArtifactRef(feature_id=pending.checkpoint_ref.feature_id, artifact_type=kind,
        path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind])
        for kind in ("patch_proposal", "proposal_review", "implementation_plan", "dry_run_result")}
    documents = {k: case.store.read(v)["data"] for k, v in refs.items()}
    materialized = materialize_exact_text_patch(workspace_root=case.request.isolated_workspace_root,
        diff_intent=documents["patch_proposal"]["diff_intent"], implementation_plan=documents["implementation_plan"])
    code = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256,
            "files": sorted(materialized.files)}
    output = Path(case.request.isolated_workspace_root) / "controlled-checks"
    output.mkdir()
    binary = output / "controlled.dll"
    binary.write_bytes(b"controlled unit binary, not an actual compiler product")
    binary_ref = {"path": str(binary.resolve()), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    compile_ref = _save(output / "compile.json", {"status": "passed", "execution_origin": "executed",
        "materialized_code_identity": code, "all_required_files_compiled": True,
        "built_artifact_ref": binary_ref,
        "scope": "controlled unit fixture, no compiler was launched"})
    detail_ref = _save(output / "checks.json", {"status": "passed", "execution_origin": "executed",
        "materialized_code_identity": code, "checks": [{"check_id": name, "passed": True} for name in CHECKS],
        "built_artifact_ref": binary_ref, "compilation_report_ref": compile_ref,
        "scope": "controlled unit witness"})
    report = {"status": "passed", "execution_origin": "executed", "failure_owner": None,
        "observations": [], "materialized_code_identity": code,
        "implementation_plan_ref": asdict(refs["implementation_plan"]), "model_response_sha256": RESPONSE_HASH,
        "verification_summary": {"checks": 5, "failed_checks": 0, "executions": 3},
        "verification_ref": detail_ref, "validation_results": {"full_compilation": {
            "status": "passed", "all_required_files_compiled": True, "report_ref": compile_ref}},
        "scope": "controlled unit acceptance witness; not real task success"}
    verification_ref = _save(output / "report.json", report)
    return case, pending, checkpoint, documents, report, verification_ref


def _decision(case, pending, verification_ref):
    return prepare_task_delegation(artifact_store_root=str(case.store.root), checkpoint_ref=pending.checkpoint_ref,
        verification_report_ref=verification_ref, required_check_ids=CHECKS,
        disposable_run_root=case.request.isolated_workspace_root, policy_id="explicit-unit-task-delegation")


def _resume(case, pending, checkpoint, reference):
    return ResumePayload(resume_id="delegated-apply", run_id=case.request.run_id,
        request_id=case.request.request_id, feature_id=pending.checkpoint_ref.feature_id,
        stage="dry_run_apply", decision="approve", approved_by=ORIGIN + ":" + reference["sha256"],
        approved_at="2026-09-26T00:00:00Z", artifact_refs=tuple(checkpoint["artifact_refs"]),
        diff_hash=pending.to_dict()["diff_hash"], authority_request_hash=reference["sha256"])


def _apply(case, pending, payload, reference):
    return resume_deferred_approval(artifact_store_root=str(case.store.root), checkpoint_ref=pending.checkpoint_ref,
                                    resume_payload=payload, task_delegation_ref=reference)


def test_delegation_applies_and_builds_once_without_claiming_human_review(tmp_path):
    case, pending, checkpoint, _, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    assert case.target.read_bytes() == case.source_before
    payload = _resume(case, pending, checkpoint, reference)
    result = _apply(case, pending, payload, reference)
    assert result["status"] == "applied_in_isolation", result
    assert case.target.read_bytes() == case.source_after
    assert case.canonical.read_bytes() == case.canonical_before
    applied = case.store.read(ArtifactRef(**result["isolated_apply_result"]))["data"]
    assert applied["approved_by_user"] is False
    assert applied["human_semantic_review_completed"] is False
    assert applied["human_semantic_review_required"] is False
    assert applied["human_semantic_decision"] is None
    assert applied["semantic_assurance"]["verdict"] == "unproven"
    assert applied["authorization_origin"] == ORIGIN and applied["task_delegation_ref"] == reference
    assert has_verified_apply_authorization(applied, run_id=case.request.run_id)
    report = case.store.read(ArtifactRef(**result["resume_report"]))["data"]
    assert report["authority_request_hash"] == reference["sha256"]
    assert report["approved_by"] == ORIGIN + ":" + reference["sha256"]
    assert report["authorization_origin"] == ORIGIN and report["task_delegation_ref"] == reference
    repeated = _apply(case, pending, payload, reference)
    assert repeated["status"] == "blocked"
    checkpoint_ref = ArtifactRef(**result["workflow_checkpoint"])
    build_checkpoint = case.store.read(checkpoint_ref)["data"]
    build_payload = replace(payload, resume_id="delegated-build", stage="isolated_apply",
                            artifact_refs=tuple(build_checkpoint["artifact_refs"]))
    kwargs = {"artifact_store_root": str(case.store.root), "checkpoint_ref": checkpoint_ref,
              "resume_payload": build_payload, "allow_build": True, "build_result_factory": _injected_build}
    built = continue_reviewed_patch(**kwargs)
    assert built["status"] == "built" and built["builds_performed"] == 1
    assert built["runtime_executions_performed"] == 0
    assert continue_reviewed_patch(**kwargs)["status"] == "blocked"
    assert case.canonical.read_bytes() == case.canonical_before


@pytest.mark.parametrize("change", ["cross_run", "diff", "original", "isolated", "actor", "runtime_resume"])
def test_changed_resume_or_source_is_rejected_before_consumption_or_write(tmp_path, change):
    case, pending, checkpoint, _, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    payload = _resume(case, pending, checkpoint, reference)
    if change == "cross_run":
        payload = replace(payload, run_id="another-run")
    elif change == "diff":
        payload = replace(payload, diff_hash="sha256:" + "f" * 64)
    elif change == "original":
        case.canonical.write_bytes(b"changed original")
    elif change == "isolated":
        case.target.write_bytes(case.source_before + b"\n// changed")
    elif change == "actor":
        payload = replace(payload, approved_by="pretend-human")
    else:
        payload = replace(payload, runtime_admission={"allow_game_launch": True})
    target_before = case.target.read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        _apply(case, pending, payload, reference)
    assert case.target.read_bytes() == target_before
    assert not case.store.list_feature_artifact_revisions(pending.checkpoint_ref.feature_id, "resume_report")
    assert not case.store.list_feature_artifact_revisions(pending.checkpoint_ref.feature_id, "isolated_apply_result")


@pytest.mark.parametrize("change", ["failed", "incomplete", "code", "model", "check_count", "check_details"])
def test_unpassed_or_unbound_acceptance_cannot_create_delegation(tmp_path, change):
    case, pending, _, _, report, reference = _pending(tmp_path)
    if change == "failed":
        report["status"] = "behavior_failed"
    elif change == "incomplete":
        report["execution_origin"] = "incomplete"
    elif change == "code":
        report["materialized_code_identity"]["code_sha256"] = "f" * 64
    elif change == "model":
        report["model_response_sha256"] = "f" * 64
    elif change == "check_count":
        report["verification_summary"]["checks"] = 4
    else:
        details = json.loads(Path(report["verification_ref"]["path"]).read_text())
        details["checks"][0]["passed"] = False
        report["verification_ref"] = _save(Path(report["verification_ref"]["path"]), details)
    reference = _save(Path(reference["path"]), report)
    with pytest.raises(ValueError, match="TASK_DELEGATION_"):
        _decision(case, pending, reference)
    assert not (case.store.root / "task_delegations").exists()
    assert case.target.read_bytes() == case.source_before


@pytest.mark.parametrize("change", ["runtime", "overlap", "target_outside"])
def test_policy_scope_excludes_runtime_and_nonisolated_roots(tmp_path, change):
    case, _, _, _, _, _ = _pending(tmp_path)
    request = case.request
    if change == "runtime":
        request = replace(request, requested_completion_scope="runtime_workflow")
    elif change == "overlap":
        request = replace(request, source_root=request.isolated_target_root)
    else:
        request = replace(request, isolated_target_root=request.source_root)
    with pytest.raises(ValueError, match="TASK_DELEGATION_"):
        _scope(request)


def test_delegation_ref_is_rejected_for_another_workspace_and_unknown_origin(tmp_path):
    case, pending, _, documents, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    with pytest.raises(ValueError, match="WORKSPACE_MISMATCH"):
        validate_task_delegation(reference, workspace_root=tmp_path)
    dry = documents["dry_run_result"]
    with pytest.raises(ValueError, match="WORKSPACE_MISMATCH"):
        validate_task_delegation(reference, workspace_root=tmp_path, diff_hash=dry["diff_hash"])
    with pytest.raises(ValueError, match="APPLY_PROVENANCE_INVALID"):
        has_verified_apply_authorization({"authorization_origin": "model_generated", "approved_by_user": True})
    assert case.target.read_bytes() == case.source_before


def test_delegation_cannot_be_combined_with_a_fabricated_human_decision(tmp_path):
    case, pending, checkpoint, _, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    payload = _resume(case, pending, checkpoint, reference)
    with pytest.raises(ValueError, match="AUTHORIZATION_SOURCE_AMBIGUOUS"):
        resume_deferred_approval(artifact_store_root=str(case.store.root), checkpoint_ref=pending.checkpoint_ref,
            resume_payload=payload, task_delegation_ref=reference, human_semantic_decision={"decision": "approve"})
    assert case.target.read_bytes() == case.source_before


def test_decision_alone_cannot_bypass_checkpoint_consumption(tmp_path):
    case, pending, _, documents, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    with pytest.raises(ValueError, match="RESUME_RECEIPT_REQUIRED"):
        ExactTextPatchApplier().run(workspace_root=case.request.isolated_workspace_root,
            proposal=documents["patch_proposal"], implementation_plan=documents["implementation_plan"],
            review=documents["proposal_review"], allow_write=True,
            approved_diff_hash=documents["dry_run_result"]["diff_hash"], task_delegation_ref=reference)
    assert case.target.read_bytes() == case.source_before


def test_model_fields_cannot_supply_host_authorization(tmp_path):
    case, pending, _, documents, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    proposal = deepcopy(documents["patch_proposal"])
    proposal.update(authorization_origin=ORIGIN, task_delegation_ref=reference)
    applier = ExactTextPatchApplier()
    kwargs = {"workspace_root": case.request.isolated_workspace_root, "proposal": proposal,
              "implementation_plan": documents["implementation_plan"], "review": documents["proposal_review"]}
    dry = applier.run(**kwargs, allow_write=False)
    with pytest.raises(RuntimeError, match="structured human semantic decision"):
        applier.run(**kwargs, allow_write=True, approved_diff_hash=dry["diff_hash"])
    assert case.target.read_bytes() == case.source_before


def test_historical_apply_remains_readable_but_missing_live_inputs_prevent_build(tmp_path):
    case, pending, checkpoint, _, report, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    payload = _resume(case, pending, checkpoint, reference)
    applied = _apply(case, pending, payload, reference)
    applied_ref = ArtifactRef(**applied["isolated_apply_result"])
    compile_ref = report["validation_results"]["full_compilation"]["report_ref"]
    compiled = json.loads(Path(compile_ref["path"]).read_text())
    Path(compiled["built_artifact_ref"]["path"]).unlink()
    case.canonical.unlink()
    Path(case.request.source_root).rmdir()
    historical = case.store.semantic_read_immutable(applied_ref)["data"]
    assert historical["authorization_origin"] == ORIGIN
    assert historical["approved_by_user"] is False
    checkpoint_ref = ArtifactRef(**applied["workflow_checkpoint"])
    build_checkpoint = case.store.read(checkpoint_ref)["data"]
    build_payload = replace(payload, resume_id="build-missing-inputs", stage="isolated_apply",
                            artifact_refs=tuple(build_checkpoint["artifact_refs"]))
    with pytest.raises((ValueError, OSError, RuntimeError)):
        continue_reviewed_patch(artifact_store_root=str(case.store.root), checkpoint_ref=checkpoint_ref,
            resume_payload=build_payload, allow_build=True,
            build_result_factory=lambda *args: pytest.fail("Missing evidence cannot execute Build"))


def test_build_cannot_add_unapproved_source_files(tmp_path):
    case, pending, checkpoint, _, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    payload = _resume(case, pending, checkpoint, reference)
    applied = _apply(case, pending, payload, reference)
    checkpoint_ref = ArtifactRef(**applied["workflow_checkpoint"])
    build_checkpoint = case.store.read(checkpoint_ref)["data"]
    build_payload = replace(payload, resume_id="build-added-source", stage="isolated_apply",
                            artifact_refs=tuple(build_checkpoint["artifact_refs"]))

    def changed_build(destination, feature_id, mode):
        result = _injected_build(destination, feature_id, mode)
        (Path(case.request.isolated_target_root) / "Unexpected.cs").write_text("class Unexpected {}")
        return result

    with pytest.raises(ValueError, match="REVIEWED_BUILD_INPUT_CHANGED_DURING_BUILD"):
        continue_reviewed_patch(artifact_store_root=str(case.store.root), checkpoint_ref=checkpoint_ref,
            resume_payload=build_payload, allow_build=True, build_result_factory=changed_build)


def test_two_host_resumes_cannot_both_commit_acceptance(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore

    case, pending, checkpoint, _, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    payload = _resume(case, pending, checkpoint, reference)
    first = WorkflowCheckpointStore(case.store)
    second = WorkflowCheckpointStore(case.store)
    prepared, release = Event(), Event()
    original = first._resume_write_arguments

    def paused(*args):
        result = original(*args)
        prepared.set()
        assert release.wait(timeout=5)
        return result

    first._resume_write_arguments = paused
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first.resume, pending.checkpoint_ref, payload)
        assert prepared.wait(timeout=5)
        two = pool.submit(second.resume, pending.checkpoint_ref, replace(payload, resume_id="competing-resume"))
        release.set()
        results = [one.result(timeout=10), two.result(timeout=10)]
    assert sum(decision.allowed for decision, _ in results) == 1
    reports = [case.store.read(ref)["data"] for _, ref in results]
    assert sum(row["allowed"] for row in reports) == 1
    assert case.target.read_bytes() == case.source_before


def test_apply_authorization_requires_concrete_diff_and_context_bindings(tmp_path):
    from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore

    case, pending, checkpoint, documents, _, verification_ref = _pending(tmp_path)
    reference = _decision(case, pending, verification_ref)
    payload = _resume(case, pending, checkpoint, reference)
    decision, receipt = WorkflowCheckpointStore(case.store).resume(pending.checkpoint_ref, payload)
    assert decision.allowed
    dry = documents["dry_run_result"]
    result = {**delegation_result_fields(reference, asdict(receipt)),
              "diff_hash": dry["diff_hash"], "approved_diff_hash": dry["diff_hash"],
              "context_hashes": dry["context_hashes"]}
    assert has_verified_apply_authorization(result)
    invalid = [{**result, "diff_hash": None, "approved_diff_hash": None, "context_hashes": None},
               {**result, "diff_hash": "", "approved_diff_hash": ""},
               {**result, "context_hashes": {}},
               {**result, "context_hashes": {"other.cs": "0" * 64}}]
    invalid.extend({key: value for key, value in result.items() if key != missing}
                   for missing in ("diff_hash", "approved_diff_hash", "context_hashes"))
    for candidate in invalid:
        with pytest.raises(ValueError, match="TASK_DELEGATION_"):
            has_verified_apply_authorization(candidate)
    assert case.target.read_bytes() == case.source_before
