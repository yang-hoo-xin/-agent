"""Public same-task continuation of a retained candidate after verifier recovery."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.fresh_planning_continuation import (
    PATCH_CONTINUATION_CONTRACT_VERSION,
    PatchContinuationInputV1,
    run_fresh_patch_continuation,
)
from src.mod_agent.patch_worker_configuration import read_json_object


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _file(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("CANDIDATE_CONTINUATION_OBJECT_REQUIRED")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}, value


def _checked(reference):
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not isinstance(reference["path"], str) or not Path(reference["path"]).is_absolute()):
        raise ValueError("CANDIDATE_CONTINUATION_EXACT_REFERENCE_REQUIRED")
    observed, value = _file(reference["path"])
    if observed != reference:
        raise ValueError("CANDIDATE_CONTINUATION_REFERENCE_CHANGED")
    return value


def _write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _completed_delivery_view(*, execution_config, root, run_id, result_ref):
    from scripts.dsh_run_request import _contained_record_path, _verified_delivered_source

    cached = _checked(result_ref)
    authorization_path = _contained_record_path(root / "delivery" / "authorization.json", root)
    delivery_path = _contained_record_path(root / "delivery" / "result.json", root)
    if not authorization_path.exists():
        if delivery_path.exists():
            raise ValueError("CANDIDATE_CONTINUATION_DELIVERY_ORIGIN_MISSING")
        return cached
    authorization_ref, authorization = _file(authorization_path)
    # 为什么要有它：交付后只读展示须绑定本次候选和实际审批链；来源漂移不能退回待审批而再次Apply。
    if (authorization.get("initial_result_ref") != result_ref
            or authorization.get("initial_manifest_ref") != cached.get("parent_manifest_ref")):
        raise ValueError("CANDIDATE_CONTINUATION_DELIVERY_ORIGIN_CHANGED")
    decision = _checked(authorization.get("decision_ref"))
    if decision.get("checkpoint_ref") != cached.get("workflow_checkpoint"):
        raise ValueError("CANDIDATE_CONTINUATION_DELIVERY_CHECKPOINT_CHANGED")
    verified = _verified_delivered_source(execution_config, run_id, None)
    delivery_ref, _ = _file(delivery_path)
    if delivery_ref not in verified["evidence_refs"] or _file(authorization_path)[0] != authorization_ref:
        raise ValueError("CANDIDATE_CONTINUATION_DELIVERY_CHANGED_DURING_READ")
    return {**cached, "status": "delivered", "current_stage": "build", "read_only": True,
        "delivery_result_ref": delivery_ref, "continuation_result_ref": result_ref,
        "delivery_authorization_ref": authorization_ref, "verified_delivered_source": verified,
        "new_provider_sends": 0, "model_calls_performed": 0}


def _authority(execution_config, root, manifest, original, journal):
    from scripts.dsh_run_request import (
        _configuration_arguments, _verify_followup_configuration,
        _verify_project_configuration, validate_product_profile,
    )
    from src.mod_agent.model_call_budget import validate_budget

    reference, document = _file(execution_config)
    _, parsed = validate_product_profile(execution_config=reference["path"], description=manifest["request"])
    _, options = _configuration_arguments(reference["path"])
    # 为什么要有它：恢复只继承已绑定任务的隔离写入与Build授权，临时配置不能伪装成历史执行请求。
    if "followup_binding" in document:
        bound = _verify_followup_configuration(Path(reference["path"]), options)
    elif "new_project_binding" in document:
        bound = _verify_project_configuration(Path(reference["path"]), options)
    else:
        raise ValueError("CANDIDATE_CONTINUATION_BOUND_AUTHORIZATION_REQUIRED")
    budget = validate_budget(original["model_call_budget"])
    previous_worker = journal["worker_configuration_ref"]
    if (parsed.run_id != manifest["run_id"] or parsed.request_id != manifest["request_id"]
            or bound["request"]["description"] != manifest["request"]
            or Path(parsed.workspace_root).resolve() / parsed.run_id != root
            or Path(parsed.target_project).resolve() != Path(manifest["target_source"]).resolve()
            or not parsed.confirm_isolated_write or not parsed.allow_build or not parsed.defer_approval
            or parsed.task_model_call_limit != budget["maximum"]
            or original["model_call_count"] != budget["consumed"]
            or _file(parsed.patch_worker_config)[0] != previous_worker
            or manifest.get("runtime_admission", {}).get("requested") is not False):
        raise ValueError("CANDIDATE_CONTINUATION_AUTHORIZATION_MISMATCH")
    return reference


def _checkpoint(*, root, manifest, original, fresh, authorization_ref):
    from src.mod_agent.product_execution import ProductExecutionInputBindingV1, ProductExecutionRequestV1
    from src.mod_agent.product_executor import ProductApprovalDeferred, source_snapshot, source_snapshot_sha256
    from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore
    from src.mod_agent.workflow.state import create_initial_state

    store = ArtifactStore(root / "a")
    refs = {kind: ArtifactRef(**fresh[key]) for kind, key in (
        ("feature_spec", "feature_spec_artifact"), ("evidence_pack", "evidence_pack_artifact"),
        ("implementation_plan", "implementation_plan_artifact"), ("patch_proposal", "patch_proposal_artifact"),
        ("proposal_review", "proposal_review_artifact"), ("dry_run_result", "dry_run_artifact"))}
    documents = {kind: store.semantic_read_immutable(ref)["data"] for kind, ref in refs.items()}
    target = Path(manifest["nuget_isolated_build_profile"]["working_directory"]).resolve(strict=True)
    source = Path(manifest["target_source"]).resolve(strict=True)
    if (not target.is_relative_to(root / "generated_mods")
            or source_snapshot(target) != original["initial_isolated_source_snapshot"]
            or source_snapshot_sha256(source_snapshot(source)) != manifest["source_snapshot_sha256"]):
        raise ValueError("CANDIDATE_CONTINUATION_SOURCE_CHANGED")
    classification = original.get("completion_classification") or {}
    if any(type(flag) is not bool for flag in classification.values()):
        raise ValueError("CANDIDATE_CONTINUATION_COMPLETION_CLASSIFICATION_INVALID")
    # 为什么要有它：公开续接仍属于原任务；Graph子执行身份单独保留，后续交付与新需求才能解析原任务。
    request = ProductExecutionRequestV1(contract_version="1", run_id=manifest["run_id"],
        request_id=manifest["request_id"], user_request=manifest["request"], target_domain="gtfo",
        target_mod=source.name, requested_completion_scope="compile_only", repair_budget=2,
        isolated_workspace_root=str(root), isolated_target_root=str(target), source_root=str(source),
        artifact_store_root=str(store.root.resolve()), source_snapshot_sha256=manifest["source_snapshot_sha256"],
        isolated_source_snapshot_sha256=source_snapshot_sha256(original["initial_isolated_source_snapshot"]),
        input_bindings=tuple(ProductExecutionInputBindingV1.create(key,
            (manifest[key] or None) if key == "source_revision_binding" else manifest[key]) for key in
            ("source_revision_binding", "source_disclosure", "model_admission", "runtime_admission")),
        completion_classification=tuple(sorted(classification.items(), key=lambda row: row[0].encode("utf-8"))),
        confirmed_isolated_write=True, allow_build=True)
    state = create_initial_state(run_id=request.run_id, request_id=request.request_id,
        user_request=request.user_request, target_domain=request.target_domain, target_mod=request.target_mod,
        confirmed_isolated_write=True)
    state.update(feature_id=refs["feature_spec"].feature_id, current_stage="dry_run_apply", next_stage="isolated_apply",
        artifacts={kind: ref.path for kind, ref in refs.items()},
        artifact_hashes={kind: ref.artifact_hash for kind, ref in refs.items()},
        risk_level=documents["feature_spec"].get("risk_level"),
        review_summary=deepcopy(documents["proposal_review"]),
        runtime_summary={"deferred_product_request_json": json.dumps(request.to_dict(), ensure_ascii=False, separators=(",", ":")),
            "product_request_origin": "reconstructed-for-continuation", "authorization_configuration_ref": authorization_ref,
            "candidate_reverification_graph_run_id": fresh["run_id"]})
    checkpoint = WorkflowCheckpointStore(store).create_checkpoint(state,
        interrupt_reason="Retained candidate passed current verification; exact diff awaits the existing approval owner.",
        resume_allowed_fields=("approvals.dry_run",))
    result = ProductApprovalDeferred(request=request, checkpoint_ref=checkpoint, dry_run_ref=refs["dry_run_result"],
        dry_run=documents["dry_run_result"], outputs=(), effect_events=()).to_dict()
    result.update(artifacts={kind: ref.path for kind, ref in refs.items()},
        product_request_origin="reconstructed-for-continuation", product_request=request.to_dict(),
        candidate_reverification_graph_run_id=fresh["run_id"])
    return result


def resume_candidate_verification(*, execution_config, run_root, run_id, recovery_config):
    """Reverify once through the existing Graph and save a separate public result.

    为什么要有它：基础设施修复应复用原模型候选，仍沿用原验收、精确diff审批和累计预算。
    """
    root = Path(run_root).resolve(strict=True)
    if root.name != run_id:
        raise ValueError("CANDIDATE_CONTINUATION_RUN_IDENTITY_MISMATCH")
    allocation = (read_json_object(recovery_config) if isinstance(recovery_config, (str, Path))
                  else deepcopy(recovery_config))
    selection = allocation.get("candidate_reverification") if isinstance(allocation, dict) else None
    if (not isinstance(selection, dict) or set(selection) != {"source_attempt_ref", "worker_configuration_ref", "attempt_id"}
            or not isinstance(selection["attempt_id"], str) or not selection["attempt_id"].strip()):
        raise ValueError("CANDIDATE_CONTINUATION_SELECTION_INVALID")
    journal = _checked(selection["source_attempt_ref"])
    _checked(selection["worker_configuration_ref"])
    manifest_ref, manifest = _file(root / "run_manifest.json")
    result_ref, original = _file(root / "run_result.json")
    if (manifest.get("run_id") != run_id or original.get("run_id") != run_id
            or manifest.get("terminal_record") != result_ref):
        raise ValueError("CANDIDATE_CONTINUATION_PARENT_CHANGED")
    authorization_ref = _authority(execution_config, root, manifest, original, journal)
    identity = {"selection": selection, "parent_manifest_ref": manifest_ref,
        "parent_result_ref": result_ref, "authorization_configuration_ref": authorization_ref}
    operation = "cv_" + hashlib.sha256(selection["attempt_id"].encode("utf-8")).hexdigest()[:16]
    segment = root / "continuations" / operation
    segment.parent.mkdir(exist_ok=True)
    if segment.is_symlink() or not segment.resolve().is_relative_to(root):
        raise ValueError("CANDIDATE_CONTINUATION_OUTPUT_OUTSIDE_RUN")
    try:
        segment.mkdir()
    except FileExistsError:
        _, saved = _file(segment / "selection.json")
        if saved != identity:
            raise ValueError("CANDIDATE_CONTINUATION_OPERATION_CONFLICT")
        completion = segment / "completion.json"
        if completion.exists():
            _, saved = _file(completion)
            return _completed_delivery_view(execution_config=execution_config, root=root,
                run_id=run_id, result_ref=saved["result_ref"])
        return {"status": "blocked", "run_id": run_id, "request_id": manifest["request_id"],
            "reason": "CANDIDATE_CONTINUATION_INCOMPLETE_REVIEW_REQUIRED", "new_provider_sends": 0,
            "continuation_root": str(segment)}
    _write(segment / "selection.json", identity)
    selected = journal["selected_artifacts"]
    request = PatchContinuationInputV1(contract_version=PATCH_CONTINUATION_CONTRACT_VERSION,
        artifact_store_root=str(root / "a"), workspace_root=str(root),
        **{kind + "_ref": ArtifactRef(**selected[kind]) for kind in ("feature_spec", "evidence_pack", "implementation_plan")},
        attempt_id=selection["attempt_id"], worker_configuration_ref=selection["worker_configuration_ref"],
        worker_profile_sha256=_hash(journal["factory_receipt"]["profile"]),
        candidate_reverification_selection={"source_attempt_ref": selection["source_attempt_ref"],
            "parent_manifest_ref": manifest_ref, "parent_result_ref": result_ref})
    from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
    fresh = run_fresh_patch_continuation(request, patch_change_factory=None, max_model_calls=0,
        dry_run_factory=make_exact_no_write_dry_run_factory(root)).to_dict()
    _write(segment / "fresh_result.json", fresh)
    public = fresh
    if fresh["status"] == "terminal" and fresh["terminal_stage"] == "dry_run_apply":
        if (fresh["execution_counts"].get("model") != 0 or fresh.get("source_modified_during_run") is not False):
            raise ValueError("CANDIDATE_CONTINUATION_EFFECT_BOUNDARY_CHANGED")
        public = _checkpoint(root=root, manifest=manifest, original=original, fresh=fresh, authorization_ref=authorization_ref)
    public = {**public, "entry": "resume-candidate-verification", "parent_run_id": run_id,
        "request_id": manifest["request_id"], "parent_manifest_ref": manifest_ref, "parent_result_ref": result_ref,
        "generation_origin": "retained_live_response", "new_provider_sends": 0, "model_calls_performed": 0,
        "model_call_count": original["model_call_count"], "model_call_budget": deepcopy(original["model_call_budget"]),
        "patch_execution_receipts": [fresh["attempt_receipt"]] if fresh.get("attempt_receipt") else [],
        "continuation_root": str(segment), "run_root": str(root),
        "fresh_result_ref": _file(segment / "fresh_result.json")[0],
        "continuation_request": asdict(request), "authorization_configuration_ref": authorization_ref,
        "actual_write_performed": False}
    if _file(root / "run_manifest.json")[0] != manifest_ref or _file(root / "run_result.json")[0] != result_ref:
        raise ValueError("CANDIDATE_CONTINUATION_PARENT_CHANGED")
    _write(segment / "run_result.json", public)
    _write(segment / "completion.json", {"result_ref": _file(segment / "run_result.json")[0]})
    return public
