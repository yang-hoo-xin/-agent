"""Public candidate recovery preserves parent evidence, budget and approval boundary."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import dsh_run_request as bridge
from src.mod_agent import candidate_verification_continuation as public
from src.mod_agent.candidate_verification_continuation import _authority as verify_authority
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from tests.unit import test_saved_candidate_reverification as cases
from tests.unit.test_saved_patch_admission import _ref, _save, saved_case


@pytest.fixture
def public_case(tmp_path, monkeypatch):
    monkeypatch.setattr(cases, "saved_case", lambda path: saved_case(path, product_layout=True))
    request, admitted, journal = cases.case.__wrapped__(tmp_path)
    root = Path(request.workspace_root)
    original = json.loads((root / "run_result.json").read_bytes())
    original["run_id"] = root.name
    product = original["product_execution_result"]
    product["run_id"] = root.name
    journal.update(parent_run_id=root.name, parent_product_run_id=root.name)
    journal["parent_product_result_identity"].update(run_id=root.name, sha256=public._hash(product))
    source_ref = _save(tmp_path / "candidate.json", journal)
    original["patch_execution_receipts"] = [source_ref]
    original_ref = _save(root / "run_result.json", original)
    manifest = json.loads((root / "run_manifest.json").read_bytes())
    manifest.update(run_id=root.name, terminal_record=original_ref, request=admitted.feature_spec["user_request"],
        source_revision_binding={}, source_disclosure={}, model_admission={}, runtime_admission={"requested": False})
    _save(root / "run_manifest.json", manifest)
    config_ref = _save(tmp_path / "execution.json", {"arguments": []})
    monkeypatch.setattr(public, "_authority", lambda *args: config_ref)
    allocation = {"candidate_reverification": {"source_attempt_ref": source_ref,
        "worker_configuration_ref": request.worker_configuration_ref, "attempt_id": "public-once"}}
    return {"execution_config": config_ref["path"], "run_root": str(root), "run_id": root.name,
        "recovery_config": allocation}, original, manifest


def test_public_recovery_real_graph_checkpoint_repeated_read(public_case, tmp_path, monkeypatch):
    from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
    from src.mod_agent.product_execution import ProductExecutionRequestV1
    from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore
    args, original, manifest = public_case
    root = Path(args["run_root"])
    before = {name: (root / name).read_bytes() for name in ("run_result.json", "run_manifest.json")}
    monkeypatch.setattr(LocalOllamaInitialPatchAdapter, "__call__", lambda *a: pytest.fail("no new model"))
    result = public.resume_candidate_verification(**args)
    assert result["status"] == "awaiting_approval", result
    assert result["model_call_budget"] == original["model_call_budget"]
    assert result["model_call_count"] == original["model_call_count"]
    assert result["new_provider_sends"] == 0 and result["actual_write_performed"] is False
    assert result["request_id"] == manifest["request_id"] and result["run_id"] == args["run_id"]
    assert result["candidate_reverification_graph_run_id"] != args["run_id"]
    assert (tmp_path / "calls.txt").read_text() == "1"
    checkpoint_ref = ArtifactRef(**result["workflow_checkpoint"])
    store = ArtifactStore(root / "a")
    checkpoint = store.semantic_read_immutable(checkpoint_ref)["data"]
    state = checkpoint["state_snapshot"]
    request = ProductExecutionRequestV1.from_dict(json.loads(state["runtime_summary"]["deferred_product_request_json"]))
    assert request.run_id == result["run_id"] and request.request_id == result["request_id"]
    assert state["runtime_summary"]["product_request_origin"] == "reconstructed-for-continuation"
    assert state["runtime_summary"]["candidate_reverification_graph_run_id"] == result["candidate_reverification_graph_run_id"]
    assert state["approvals"] == {"confirmed_write": True}
    assert checkpoint["resume_binding"]["diff_hash"] == result["diff_hash"]
    assert WorkflowCheckpointStore(store).preflight_resume(checkpoint_ref, resume_id="test-resume").allowed
    assert public.resume_candidate_verification(**args) == result
    assert (tmp_path / "calls.txt").read_text() == "1"
    assert before == {name: (root / name).read_bytes() for name in before}


def test_parent_terminal_drift_rejects_before_evaluator(public_case, tmp_path):
    args, _, manifest = public_case
    manifest["terminal_record"]["sha256"] = "0" * 64
    _save(Path(args["run_root"]) / "run_manifest.json", manifest)
    with pytest.raises(ValueError, match="PARENT_CHANGED"):
        public.resume_candidate_verification(**args)
    assert not (tmp_path / "calls.txt").exists()


def test_incomplete_operation_is_not_executed_again(public_case, tmp_path, monkeypatch):
    args, _, _ = public_case
    def interrupted(*a, **kw):
        raise RuntimeError("interrupted")
    monkeypatch.setattr(public, "run_fresh_patch_continuation", interrupted)
    with pytest.raises(RuntimeError, match="interrupted"):
        public.resume_candidate_verification(**args)
    second = public.resume_candidate_verification(**args)
    assert second["reason"] == "CANDIDATE_CONTINUATION_INCOMPLETE_REVIEW_REQUIRED"
    assert not (tmp_path / "calls.txt").exists()


def test_operation_cannot_change_verifier(public_case, tmp_path):
    args, _, _ = public_case
    public.resume_candidate_verification(**args)
    selection = args["recovery_config"]["candidate_reverification"]
    changed = json.loads(Path(selection["worker_configuration_ref"]["path"]).read_bytes())
    changed["behavior_evaluator"]["kwargs"]["status"] = "infrastructure_failed"
    selection["worker_configuration_ref"] = _save(tmp_path / "second-worker.json", changed)
    with pytest.raises(ValueError, match="OPERATION_CONFLICT"):
        public.resume_candidate_verification(**args)
    assert (tmp_path / "calls.txt").read_text() == "1"


def test_advance_dispatches_candidate_configuration(tmp_path, monkeypatch):
    config = tmp_path / "execution.json"
    allocation = tmp_path / "allocation.json"
    _save(allocation, {"candidate_reverification": {"attempt_id": "selected"}})
    monkeypatch.setattr(bridge, "task_execution_config", lambda **kw: str(config))
    monkeypatch.setattr(bridge, "inspect_run", lambda **kw: {"status": "recorded", "manifest": {},
        "result": {"status": "blocked"}, "run_root": str(tmp_path / "run")})
    observed = []
    monkeypatch.setattr(public, "resume_candidate_verification", lambda **kw: observed.append(kw) or {"status": "selected"})
    result = bridge.advance_task(execution_config=str(config), run_id="run", allocation_config=str(allocation))
    assert result == {"status": "selected"}
    assert observed[0]["recovery_config"] == json.loads(allocation.read_bytes())


def test_unbound_authority_does_not_reconstruct_request(tmp_path, monkeypatch):
    config = tmp_path / "execution.json"
    _save(config, {"arguments": []})
    monkeypatch.setattr(bridge, "validate_product_profile", lambda **kw: ([], SimpleNamespace()))
    monkeypatch.setattr(bridge, "_configuration_arguments", lambda *a: ([], {}))
    with pytest.raises(ValueError, match="BOUND_AUTHORIZATION_REQUIRED"):
        public._authority(str(config), tmp_path, {"request": "requirement"}, {}, {})


@pytest.mark.parametrize("damage", [None, "confirm_isolated_write", "allow_build", "defer_approval", "task_model_call_limit", "request_id"])
def test_reconstruction_requires_original_authorized_scope(public_case, tmp_path, monkeypatch, damage):
    args, original, manifest = public_case
    root = Path(args["run_root"])
    config = tmp_path / "authority.json"
    _save(config, {"arguments": [], "followup_binding": {}})
    worker = _save(tmp_path / "original-worker.json", {})
    parsed = SimpleNamespace(run_id=root.name, request_id=manifest["request_id"], workspace_root=str(root.parent),
        target_project=manifest["target_source"], confirm_isolated_write=True, allow_build=True, defer_approval=True,
        task_model_call_limit=original["model_call_budget"]["maximum"], patch_worker_config=worker["path"])
    if damage:
        setattr(parsed, damage, False if damage in {"confirm_isolated_write", "allow_build", "defer_approval"} else "different")
    monkeypatch.setattr(bridge, "validate_product_profile", lambda **kw: ([], parsed))
    monkeypatch.setattr(bridge, "_configuration_arguments", lambda *a: ([], {}))
    monkeypatch.setattr(bridge, "_verify_followup_configuration", lambda *a: {"request": {"description": manifest["request"]}})
    if damage:
        with pytest.raises(ValueError, match="AUTHORIZATION_MISMATCH"):
            verify_authority(config, root, manifest, original, {"worker_configuration_ref": worker})
    else:
        assert verify_authority(config, root, manifest, original, {"worker_configuration_ref": worker}) == _ref(config)


def _delivered_view_fixture(args, monkeypatch):
    cached = public.resume_candidate_verification(**args)
    root = Path(args["run_root"])
    result_path = Path(cached["continuation_root"]) / "run_result.json"
    result_ref = _ref(result_path)
    delivery_ref = _save(root / "delivery/result.json", {"status": "delivered", "delivery_complete": True})
    decision_ref = _save(root / "decision.json", {"checkpoint_ref": cached["workflow_checkpoint"]})
    authorization = {"initial_result_ref": result_ref, "initial_manifest_ref": cached["parent_manifest_ref"],
        "decision_ref": decision_ref}
    _save(root / "delivery/authorization.json", authorization)
    observed = []
    def verified(*arguments):
        observed.append(arguments)
        return {"evidence_refs": [delivery_ref], "run_id": args["run_id"]}
    monkeypatch.setattr(bridge, "_verified_delivered_source", verified)
    return cached, result_path, delivery_ref, authorization, observed


def test_reentry_projects_verified_delivery_without_changing_saved_result(public_case, tmp_path, monkeypatch):
    args, original, _ = public_case
    cached, path, delivery_ref, _, calls = _delivered_view_fixture(args, monkeypatch)
    before = path.read_bytes()
    result = public.resume_candidate_verification(**args)
    assert result["status"] == "delivered" and result["current_stage"] == "build" and result["read_only"] is True
    assert result["delivery_result_ref"] == delivery_ref and result["continuation_result_ref"] == _ref(path)
    assert result["model_call_budget"] == original["model_call_budget"] and result["new_provider_sends"] == 0
    assert calls == [(args["execution_config"], args["run_id"], None)]
    assert cached["status"] == "awaiting_approval" and path.read_bytes() == before
    assert (tmp_path / "calls.txt").read_text() == "1"


@pytest.mark.parametrize("damage", ["origin", "checkpoint", "source", "missing_authorization"])
def test_delivered_reentry_rejects_origin_or_source_drift(public_case, tmp_path, monkeypatch, damage):
    args, _, _ = public_case
    _, _, _, authorization, calls = _delivered_view_fixture(args, monkeypatch)
    root = Path(args["run_root"])
    if damage == "origin":
        authorization["initial_result_ref"]["sha256"] = "0" * 64
        _save(root / "delivery/authorization.json", authorization)
    elif damage == "checkpoint":
        authorization["decision_ref"] = _save(root / "changed-decision.json", {"checkpoint_ref": {}})
        _save(root / "delivery/authorization.json", authorization)
    elif damage == "missing_authorization":
        (root / "delivery/authorization.json").unlink()
    else:
        def changed(*args):
            raise ValueError("DSH_FOLLOWUP_APPLIED_SOURCE_CHANGED")
        monkeypatch.setattr(bridge, "_verified_delivered_source", changed)
    with pytest.raises(ValueError, match="DELIVERY_|APPLIED_SOURCE_CHANGED"):
        public.resume_candidate_verification(**args)
    assert calls == []
    assert (tmp_path / "calls.txt").read_text() == "1"
