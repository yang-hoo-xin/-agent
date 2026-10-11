"""DSH approval adapter for one retained public task; the original Graph executes.

Preview binds the existing checkpoint, exact diff, local build inputs and output
directory. User decisions arrive on stdin. The small delivery receipt records
owner results; it neither grants authority nor substitutes for their Artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from scripts.dsh_run_request import _configuration_arguments, inspect_run, task_execution_config
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.build.adapter import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.build.dependencies import (
    _binary_tree_snapshot,
    _binary_tree_snapshot_sha256,
    _copy_validated_directory_tree,
)
from src.mod_agent.build.nuget import (
    _create_nuget_isolated_build_profile,
    _run_nuget_isolated_build,
)
from src.mod_agent.execution.patch_apply import ExactTextPatchApplier
from src.mod_agent.product_execution import ProductExecutionRequestV1
from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256
from src.mod_agent.reviewed_patch_continuation import (
    _applied_source_snapshot,
    continue_reviewed_patch,
    resume_deferred_approval,
    review_run,
)
from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore
from src.mod_agent.workflow.interrupts import ResumePayload


def _hash(value):
    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _base(run_id, *, read_only=True):
    return {"entry": "dsh-delivery", "run_id": run_id, "read_only": read_only,
            "model_calls_performed": 0, "runtime_executions_performed": 0,
            "product_source_writes_performed": False, "builds_performed": 0,
            "approval_ready": False}


def _paths(config_path, delivery_root, run_id):
    config_path = task_execution_config(execution_config=config_path, run_id=run_id)
    _, options = _configuration_arguments(config_path)
    if (not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id) is None
            or options.get("--run-id") != run_id):
        raise ValueError("DSH_DELIVERY_CONFIGURED_RUN_MISMATCH")
    workspace = Path(options["--workspace-root"]).resolve()
    root = Path(delivery_root)
    if not root.is_absolute():
        raise ValueError("DSH_DELIVERY_ROOT_MUST_BE_ABSOLUTE")
    root = root.resolve()
    source = Path(options["--target-project"]).resolve()
    if any(root.is_relative_to(other) or other.is_relative_to(root)
           for other in (workspace, source)):
        raise ValueError("DSH_DELIVERY_ROOT_OVERLAPS_INPUT")
    for path in (root, *root.parents):
        if path.exists() and (path.is_symlink() or not path.is_dir()
                or getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("DSH_DELIVERY_ROOT_NOT_PLAIN_DIRECTORY")
    receipts = root / ".dsh-delivery"
    if receipts.exists() and (receipts.is_symlink() or not receipts.is_dir()
            or getattr(receipts.lstat(), "st_file_attributes", 0) & 0x400):
        raise ValueError("DSH_DELIVERY_RECEIPT_DIRECTORY_NOT_PLAIN")
    return options, root / run_id, receipts / (run_id + ".json")


def _inputs(config_path, delivery_root, run_id):
    config_path = task_execution_config(execution_config=config_path, run_id=run_id)
    options, destination, receipt_path = _paths(config_path, delivery_root, run_id)
    found = inspect_run(execution_config=config_path, run_id=run_id)
    result, manifest = found["result"], found["manifest"]
    if not result or not manifest or result.get("status") != "awaiting_approval":
        raise ValueError("DSH_DELIVERY_PENDING_PUBLIC_RESULT_REQUIRED")
    run_root = Path(found["run_root"])
    checkpoint_ref = ArtifactRef(**result["workflow_checkpoint"])
    store = ArtifactStore(run_root / "a")
    checkpoint = store.semantic_read_immutable(checkpoint_ref)["data"]
    state = checkpoint["state_snapshot"]
    request = ProductExecutionRequestV1.from_dict(json.loads(
        state["runtime_summary"]["deferred_product_request_json"]))
    if (checkpoint["checkpoint_stage"] != "dry_run_apply" or request.run_id != run_id
            or request.request_id != options.get("--request-id")
            or Path(request.source_root).resolve() != Path(options["--target-project"]).resolve()
            or Path(request.isolated_workspace_root).resolve() != run_root
            or Path(request.artifact_store_root).resolve() != store.root.resolve()
            or result["feature_id"] != checkpoint_ref.feature_id):
        raise ValueError("DSH_DELIVERY_ORIGINAL_IDENTITY_MISMATCH")
    dry = store.semantic_read_immutable(ArtifactRef(feature_id=checkpoint_ref.feature_id,
        artifact_type="dry_run_result", path=state["artifacts"]["dry_run_result"],
        artifact_hash=state["artifact_hashes"]["dry_run_result"]))["data"]
    if (result["diff_hash"] != dry["diff_hash"]
            or result["human_semantic_decision_binding"] != dry["human_semantic_decision_binding"]):
        raise ValueError("DSH_DELIVERY_PUBLIC_DIFF_MISMATCH")
    return {"options": options, "destination": destination, "receipt_path": receipt_path,
            "result": result, "manifest": manifest, "run_root": run_root, "store": store,
            "checkpoint_ref": checkpoint_ref, "checkpoint": checkpoint,
            "request": request, "dry": dry}


def _build_inputs(case):
    manifest, request, root = case["manifest"], case["request"], case["run_root"]
    declared = manifest["nuget_isolated_build_profile"]
    target = Path(request.isolated_target_root).resolve()
    if Path(declared["working_directory"]).resolve() != target or not target.is_relative_to(root):
        raise ValueError("DSH_DELIVERY_BUILD_TARGET_MISMATCH")
    dependency = manifest["build_dependency"]["game_folder"]
    # 为什么要有它：BCL 工程可以没有游戏依赖，但构建声明不能因此隐式加入另一个 GameFolder。
    if dependency is None:
        game = None
        if declared["game_folder_dir"] is not None:
            raise ValueError("DSH_DELIVERY_DEPENDENCY_DECLARATION_MISMATCH")
    else:
        game = Path(dependency["isolated_copy"]).resolve()
        if (not game.is_relative_to(root) or declared["game_folder_dir"] != str(game)
                or dependency["build_uses_isolated_copy"] is not True):
            raise ValueError("DSH_DELIVERY_DEPENDENCY_OUTSIDE_RUN")
        snapshot = _binary_tree_snapshot(game)
        if (len(snapshot) != dependency["copy_file_count"]
                or _binary_tree_snapshot_sha256(snapshot) != dependency["copy_snapshot_sha256"]):
            raise ValueError("DSH_DELIVERY_DEPENDENCY_CHANGED")
    if manifest.get("objective_verification_command") is not None:
        raise ValueError("DSH_DELIVERY_OBJECTIVE_ADAPTER_NOT_CONFIGURED")
    profile = _create_nuget_isolated_build_profile(run_root=root,
        working_directory=target, config_file=Path(declared["config_file"]),
        bepinex_dir=Path(declared["bepinex_dir"]) if declared["bepinex_dir"] else None,
        game_folder_dir=game, timeout_seconds=declared["timeout_seconds"])
    if profile.to_dict() != declared:
        raise ValueError("DSH_DELIVERY_BUILD_PROFILE_CHANGED")
    baseline = manifest["baseline_build"]
    relative = Path(baseline["artifact_path"]).relative_to(
        Path(baseline["build_profile"]["working_directory"]))
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".dll":
        raise ValueError("DSH_DELIVERY_OUTPUT_PATH_INVALID")
    return profile, dependency, relative


def _recorded_review(case, documents):
    review = documents["proposal_review"]
    evidence = {"historical_not_rerun": True,
        "original_review": {key: review.get(key) for key in ("decision", "allowed_next_stage",
            "findings", "required_changes", "human_semantic_review_required", "semantic_assurance")},
        "behavior_verification_recorded": [], "verification_reports": []}
    state = case["checkpoint"]["state_snapshot"]
    for receipt in case["result"].get("patch_execution_receipts", []):
        path = Path(receipt["path"])
        if (not path.resolve().is_relative_to(case["store"].root.resolve())
                or _file_ref(path)["sha256"] != receipt["sha256"]):
            raise ValueError("DSH_DELIVERY_PATCH_RECEIPT_CHANGED")
        journal = json.loads(path.read_text(encoding="utf-8"))
        if journal["parent_product_run_id"] != case["request"].run_id:
            raise ValueError("DSH_DELIVERY_PATCH_PARENT_MISMATCH")
        view = review_run(artifact_store_root=str(case["store"].root), workspace_root=str(case["run_root"]),
            feature_id=case["checkpoint"]["feature_id"], run_id=journal["run_id"])
        if ((view.get("artifacts", {}).get("patch_proposal") or {}).get("artifact_hash")
                != state["artifact_hashes"]["patch_proposal"]):
            continue
        if view["status"] != "reviewable_diff" or view["diff_hash"] != case["dry"]["diff_hash"]:
            raise ValueError("DSH_DELIVERY_PATCH_REVIEW_UNAVAILABLE")
        evidence["patch_journal_ref"] = view["journal_ref"]
        for row in view["behavior_verification_recorded"]:
            reference = row.get("report_ref")
            summary = dict(row)
            if reference:
                if _file_ref(Path(reference["path"])) != reference:
                    raise ValueError("DSH_DELIVERY_VERIFICATION_REPORT_CHANGED")
                report = json.loads(Path(reference["path"]).read_text(encoding="utf-8"))
                evidence["verification_reports"].append(reference)
                summary.update({key: report.get(key) for key in (
                    "verification_summary", "verification_scope", "materialized_code_identity")})
                verification = report.get("verification_ref")
                if verification:
                    if _file_ref(Path(verification["path"])) != verification:
                        raise ValueError("DSH_DELIVERY_VERIFICATION_REPORT_CHANGED")
                    evidence["verification_reports"].append(verification)
            evidence["behavior_verification_recorded"].append(summary)
    if case["result"].get("patch_execution_receipts") and "patch_journal_ref" not in evidence:
        raise ValueError("DSH_DELIVERY_CURRENT_PATCH_REVIEW_NOT_FOUND")
    return evidence


def _preview(case):
    request, store, cp = case["request"], case["store"], case["checkpoint"]
    preflight = WorkflowCheckpointStore(store).preflight_resume(case["checkpoint_ref"],
        resume_id="dsh-delivery-" + request.run_id)
    if not preflight.allowed:
        raise ValueError("DSH_DELIVERY_CHECKPOINT_UNAVAILABLE: " + json.dumps(list(preflight.blockers)))
    if source_snapshot_sha256(source_snapshot(Path(request.source_root))) != request.source_snapshot_sha256:
        raise ValueError("DEFERRED_APPROVAL_ORIGINAL_SOURCE_CHANGED")
    if source_snapshot_sha256(source_snapshot(Path(request.isolated_target_root))) != request.isolated_source_snapshot_sha256:
        raise ValueError("DEFERRED_APPROVAL_ISOLATED_SOURCE_CHANGED")
    state = cp["state_snapshot"]
    documents = {kind: store.semantic_read_immutable(ArtifactRef(feature_id=cp["feature_id"],
        artifact_type=kind, path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind]))["data"]
        for kind in ("patch_proposal", "implementation_plan", "proposal_review")}
    current = ExactTextPatchApplier().run(workspace_root=request.isolated_workspace_root,
        proposal=documents["patch_proposal"], implementation_plan=documents["implementation_plan"],
        review=documents["proposal_review"], allow_write=False)
    if any(current[key] != case["dry"][key] for key in ("diff_hash", "unified_diff_sha256")):
        raise ValueError("DEFERRED_APPROVAL_CURRENT_DIFF_CHANGED")
    profile, dependency, relative = _build_inputs(case)
    if (profile.working_directory / relative).exists():
        raise ValueError("DSH_DELIVERY_PREEXISTING_BUILD_OUTPUT")
    if case["destination"].exists():
        raise ValueError("DSH_DELIVERY_DESTINATION_ALREADY_EXISTS")
    review_evidence = _recorded_review(case, documents)
    binding = {"run_id": request.run_id, "request_id": request.request_id,
        "checkpoint": case["result"]["workflow_checkpoint"],
        "human_semantic_decision_binding": case["dry"]["human_semantic_decision_binding"],
        "source_identity": {"source_root": request.source_root,
            "source_snapshot_sha256": request.source_snapshot_sha256,
            "isolated_target_root": request.isolated_target_root,
            "isolated_source_snapshot_sha256": request.isolated_source_snapshot_sha256},
        "dependency_identity": dependency, "build_profile": profile.to_dict(),
        "review_evidence": review_evidence,
        "expected_artifact": str(profile.working_directory / relative),
        "delivery_path": str(case["destination"]),
        "retention_scope": "complete_project_build_dependencies_build_environment_and_original_artifact_bytes",
        "runtime_authorized": False, "model_calls_authorized": False}
    return {**_base(request.run_id), "status": "awaiting_approval", "approval_ready": True,
        "scope_hash": _hash(binding), "binding": binding, "delivery_path": str(case["destination"]),
        "diff_hash": current["diff_hash"], "unified_diff": current["unified_diff"],
        "build_profile": profile.to_dict(), "source_identity": binding["source_identity"],
        "dependency_identity": dependency, "review_evidence": review_evidence,
        "original_review": review_evidence["original_review"],
        "behavior_verification_recorded": review_evidence["behavior_verification_recorded"]}


def _write_receipt(path, value, *, initial=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if initial:
        # Claim this displayed operation before entering an effect owner. A
        # second process cannot replace an in-flight operation with its own.
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        return
    temporary = path.with_suffix(".writing")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_receipt(case):
    path = case["receipt_path"]
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("DSH_DELIVERY_RECEIPT_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (value["run_id"] != case["request"].run_id or value["checkpoint"] != case["result"]["workflow_checkpoint"]
            or value["delivery_path"] != str(case["destination"])
            or _hash(value["binding"]) != value["scope_hash"]):
        raise ValueError("DSH_DELIVERY_RECEIPT_IDENTITY_MISMATCH")
    outcomes = {}
    for result_name, ref_name in (("apply_result", "isolated_apply_result"), ("build_result", "build_result")):
        result = value.get(result_name) or {}
        if result.get(ref_name):
            outcomes[result_name] = case["store"].semantic_read_immutable(ArtifactRef(**result[ref_name]))["data"]
    if value["status"] == "delivered":
        applied, built = outcomes.get("apply_result") or {}, outcomes.get("build_result") or {}
        if (applied.get("actual_write_performed") is not True
                or applied.get("approved_diff_hash") != case["dry"]["diff_hash"]
                or applied.get("human_semantic_review_completed") is not True
                or built.get("status") != "success" or built.get("real_build_performed") is not True
                or built.get("claims_real_build_success") is not True
                or not built.get("verified_artifacts")
                or built.get("input_execution_mode") != "isolated_apply"):
            raise ValueError("DSH_DELIVERY_SUCCESS_OWNER_EVIDENCE_MISSING")
        reference = value["delivery_ref"]
        if Path(reference["path"]) != case["destination"] / "delivery.json":
            raise ValueError("DSH_DELIVERY_RETAINED_MANIFEST_OUTSIDE_DELIVERY")
        if _file_ref(Path(reference["path"])) != reference:
            raise ValueError("DSH_DELIVERY_RETAINED_MANIFEST_CHANGED")
        retained = json.loads(Path(reference["path"]).read_text(encoding="utf-8"))
        if (retained.get("run_id") != value["run_id"] or retained.get("scope_hash") != value["scope_hash"]
                or retained.get("source_task") != value["checkpoint"]
                or retained.get("apply_result") != value["apply_result"]
                or retained.get("build_result") != value["build_result"]):
            raise ValueError("DSH_DELIVERY_RETAINED_MANIFEST_IDENTITY_MISMATCH")
        observed = [row for row in _binary_tree_snapshot(case["destination"]) if row["path"] != "delivery.json"]
        if observed != retained["files"]:
            raise ValueError("DSH_DELIVERY_RETAINED_BYTES_CHANGED")
        copied = {row["path"]: row["sha256"] for row in observed}
        for artifact in built["verified_artifacts"]:
            relative = Path(artifact["resolved_path"]).relative_to(Path(case["request"].isolated_target_root))
            if copied.get((Path("project") / relative).as_posix()) != artifact["sha256"]:
                raise ValueError("DSH_DELIVERY_BUILD_OUTPUT_NOT_RETAINED")
    return value


def _receipt_view(case, receipt):
    return {**_base(case["request"].run_id), "status": receipt["status"],
            "scope_hash": receipt["scope_hash"], "delivery_path": receipt["delivery_path"],
            "receipt": receipt, "receipt_ref": _file_ref(case["receipt_path"])}


def _effect_view(case, receipt):
    return {**_receipt_view(case, receipt), "read_only": False,
        "product_source_writes_performed": (receipt.get("apply_result") or {}).get(
            "product_source_writes_performed", None if receipt.get("apply_owner_invoked") else False),
        "builds_performed": (receipt.get("build_result") or {}).get(
            "builds_performed", None if receipt.get("build_owner_invoked") else 0)}


def _resume_payload(checkpoint, *, stage, reviewer, decision, scope_hash):
    return ResumePayload(resume_id="dsh-" + stage + "-" + scope_hash.removeprefix("sha256:")[:32],
        run_id=checkpoint["run_id"], request_id=checkpoint["request_id"], feature_id=checkpoint["feature_id"],
        stage=checkpoint["checkpoint_stage"], decision=decision, approved_by=reviewer,
        approved_at=datetime.now(timezone.utc).isoformat(), artifact_refs=tuple(checkpoint["artifact_refs"]),
        diff_hash=checkpoint["resume_binding"]["diff_hash"], notes="Explicit DSH decision for " + scope_hash)


def _build_factory(case, preview):
    def build(destination, feature_id, mode):
        if destination != case["run_root"]:
            raise ValueError("DSH_DELIVERY_BUILD_WORKSPACE_CHANGED")
        profile, dependency, relative = _build_inputs(case)
        if (profile.to_dict() != preview["binding"]["build_profile"]
                or dependency != preview["binding"]["dependency_identity"]):
            raise ValueError("DSH_DELIVERY_BUILD_SCOPE_CHANGED")
        if (profile.working_directory / relative).exists():
            raise ValueError("DSH_DELIVERY_PREEXISTING_BUILD_OUTPUT")
        declared = BuildProfile(profile_id=profile.profile_id, build_system="dotnet",
            working_directory=str(profile.working_directory), command=profile.build_command,
            timeout_seconds=profile.timeout_seconds, expected_artifacts=(relative.as_posix(),))
        log_root = destination / "build_environment" / "dsh_delivery"

        def run(_profile):
            completed = _run_nuget_isolated_build(profile, command_runner=subprocess.run)
            log_root.mkdir(exist_ok=False)
            for suffix, content in (("stdout", completed.stdout), ("stderr", completed.stderr)):
                with (log_root / (suffix + ".log")).open("x", encoding="utf-8") as handle:
                    handle.write(content)
            (log_root / "phases.json").write_text(json.dumps(completed.to_dict(), sort_keys=True), encoding="utf-8")
            return BuildCommandResult(exit_code=completed.exit_code, stdout=completed.stdout,
                stderr=completed.stderr, duration_ms=completed.duration_ms)

        result = BuildAdapter().run_local(feature_id=feature_id, profile=declared,
            command_runner=run, allow_execution=True, input_execution_mode=mode)
        return replace(result, stdout_path=str(log_root / "stdout.log"), stderr_path=str(log_root / "stderr.log"))
    return build


def _copy_verified(source, destination):
    before = _binary_tree_snapshot(source)
    _copy_validated_directory_tree(source=source, destination=destination)
    if _binary_tree_snapshot(source) != before or _binary_tree_snapshot(destination) != before:
        raise ValueError("DSH_DELIVERY_COPY_IDENTITY_MISMATCH")


def _retain(case, receipt):
    destination = case["destination"]
    destination.mkdir(parents=True, exist_ok=False)
    profile, _, _ = _build_inputs(case)
    for source, name in ((profile.working_directory, "project"),
            (case["run_root"] / "build_dependencies", "build_dependencies"),
            (case["run_root"] / "build_environment", "build_environment"),
            (case["store"].root, "original_artifacts")):
        # 为什么要有它：没有声明游戏或 BepInEx 依赖时，留存空缺目录不能成为已完成 Build 的伪失败。
        if (name == "build_dependencies" and not source.exists()
                and profile.game_folder_dir is None and profile.bepinex_dir is None):
            continue
        _copy_verified(source, destination / name)
    for name in ("run_result.json", "run_manifest.json"):
        raw = (case["run_root"] / name).read_bytes()
        (destination / ("original_" + name)).write_bytes(raw)
    verification_root = destination / "verification_reports"
    verification_root.mkdir()
    for reference in receipt["binding"]["review_evidence"]["verification_reports"]:
        path = Path(reference["path"])
        if _file_ref(path) != reference:
            raise ValueError("DSH_DELIVERY_VERIFICATION_REPORT_CHANGED")
        (verification_root / (reference["sha256"] + ".json")).write_bytes(path.read_bytes())
    checkpoint = case["store"].semantic_read_immutable(
        ArtifactRef(**receipt["apply_result"]["workflow_checkpoint"]))["data"]
    approved_source = checkpoint["state_snapshot"]["runtime_summary"]["reviewed_apply"]["applied_source_snapshot"]
    if (_applied_source_snapshot(profile.working_directory) != approved_source
            or _applied_source_snapshot(destination / "project") != approved_source):
        raise ValueError("DSH_DELIVERY_COPIED_SOURCE_DIFFERS_FROM_APPLY")
    built = case["store"].semantic_read_immutable(ArtifactRef(**receipt["build_result"]["build_result"]))["data"]
    for artifact in built["verified_artifacts"]:
        source = Path(artifact["resolved_path"])
        copied = destination / "project" / source.relative_to(profile.working_directory)
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"] for path in (source, copied)):
            raise ValueError("DSH_DELIVERY_COPIED_DLL_DIFFERS_FROM_BUILD")
    retained = {"run_id": receipt["run_id"], "scope_hash": receipt["scope_hash"],
        "source_task": receipt["checkpoint"], "apply_result": receipt["apply_result"],
        "build_result": receipt["build_result"], "build_profile": profile.to_dict(),
        "original_refs_preserved_not_migrated": True,
        "build_reproduction": ("Use project and the retained GameFolder with an explicit GameFolder build property; original profile paths are provenance, not relocated execution authority."
            if profile.game_folder_dir is not None else
            "Use the retained project and declared build profile without adding a GameFolder; original profile paths are provenance, not relocated execution authority."),
        "files": list(_binary_tree_snapshot(destination))}
    path = destination / "delivery.json"
    path.write_text(json.dumps(retained, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return _file_ref(path)


def deliver_run(*, config_path, delivery_root, run_id, action, decision=None):
    case = _inputs(config_path, delivery_root, run_id)
    receipt = _read_receipt(case)
    if action in ("deliver", "reject"):
        expected = "approve" if action == "deliver" else "reject"
        if (not isinstance(decision, dict) or set(decision) != {"decision", "reviewer", "scope_hash"}
                or decision["decision"] != expected or not isinstance(decision["reviewer"], str)
                or not decision["reviewer"].strip() or len(decision["reviewer"]) > 200
                or not isinstance(decision["scope_hash"], str)):
            raise ValueError("DSH_DELIVERY_EXPLICIT_DECISION_REQUIRED")
        if receipt:
            if receipt["scope_hash"] != decision["scope_hash"]:
                raise ValueError("DSH_DELIVERY_DISPLAYED_SCOPE_CHANGED")
            return _receipt_view(case, receipt)
    elif action not in ("preview", "status"):
        raise ValueError("DSH_DELIVERY_ACTION_INVALID")
    if receipt:
        return _receipt_view(case, receipt)
    preview = _preview(case)
    if action in ("preview", "status"):
        return preview
    if decision["scope_hash"] != preview["scope_hash"]:
        raise ValueError("DSH_DELIVERY_DISPLAYED_SCOPE_CHANGED")
    receipt = {"run_id": run_id, "scope_hash": preview["scope_hash"],
        "checkpoint": case["result"]["workflow_checkpoint"], "delivery_path": str(case["destination"]),
        "status": "applying", "decision": decision, "binding": preview["binding"],
        "apply_owner_invoked": True}
    _write_receipt(case["receipt_path"], receipt, initial=True)
    try:
        receipt["apply_owner_invoked"] = True
        applied = resume_deferred_approval(artifact_store_root=str(case["store"].root),
            checkpoint_ref=case["checkpoint_ref"], resume_payload=_resume_payload(case["checkpoint"],
                stage="apply", reviewer=decision["reviewer"], decision=decision["decision"], scope_hash=preview["scope_hash"]),
            human_semantic_decision={**case["dry"]["human_semantic_decision_binding"],
                "decision": decision["decision"], "reviewer_identity": decision["reviewer"]})
        receipt.update(apply_result=applied, status=applied["status"])
        _write_receipt(case["receipt_path"], receipt)
        if applied["status"] != "applied_in_isolation":
            return _effect_view(case, receipt)
        reference = ArtifactRef(**applied["workflow_checkpoint"])
        checkpoint = case["store"].semantic_read_immutable(reference)["data"]
        receipt["status"] = "building"
        receipt["build_owner_invoked"] = True
        _write_receipt(case["receipt_path"], receipt)
        built = continue_reviewed_patch(artifact_store_root=str(case["store"].root),
            checkpoint_ref=reference, resume_payload=_resume_payload(checkpoint, stage="build",
                reviewer=decision["reviewer"], decision="approve", scope_hash=preview["scope_hash"]),
            allow_build=True, build_result_factory=_build_factory(case, preview))
        receipt.update(build_result=built, status=built["status"])
        _write_receipt(case["receipt_path"], receipt)
        if built["status"] == "built":
            receipt["delivery_ref"] = _retain(case, receipt)
            receipt["status"] = "delivered"
            _write_receipt(case["receipt_path"], receipt)
    except Exception as error:
        receipt.update(status="blocked", reason=str(error),
            stopped_after=receipt["status"], execution_outcome="inspect_original_resume_and_effect_artifacts")
        receipt["uncertain_effects"] = {
            "product_source_writes_performed": (receipt.get("apply_result") or {}).get(
                "product_source_writes_performed", None if receipt.get("apply_owner_invoked") else False),
            "builds_performed": (receipt.get("build_result") or {}).get(
                "builds_performed", None if receipt.get("build_owner_invoked") else 0),
            "resume_report": getattr(error, "resume_report", None),
        }
        _write_receipt(case["receipt_path"], receipt)
    return _effect_view(case, receipt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--delivery-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--action", choices=("preview", "deliver", "reject", "status"), required=True)
    parser.add_argument("--decision-stdin", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.decision_stdin != (args.action in ("deliver", "reject")):
            raise ValueError("DSH_DELIVERY_DECISION_CHANNEL_REQUIRED")
        decision = None
        if args.decision_stdin:
            raw = sys.stdin.buffer.read(16385)
            if len(raw) > 16384:
                raise ValueError("DSH_DELIVERY_DECISION_TOO_LARGE")
            decision = json.loads(raw.decode("utf-8"))
        result = deliver_run(config_path=args.config_path, delivery_root=args.delivery_root,
            run_id=args.run_id, action=args.action, decision=decision)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        result = {**_base(args.run_id), "status": "blocked", "reason": str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
