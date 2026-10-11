"""Admit a terminal Patch preparation failure without replaying earlier stages."""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import re

from src.mod_agent.saved_patch_admission import _hash, _json, _read


def _require(condition, code):
    if not condition:
        raise ValueError("PRETRANSPORT_PATCH_" + code)


def validate_selection(selection):
    _require(isinstance(selection, dict) and set(selection) == {
        "source_attempt_ref", "parent_manifest_ref", "parent_result_ref", "execution_config_ref"}, "SELECTION_INVALID")
    for ref in selection.values():
        _require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}
            and isinstance(ref["path"], str) and Path(ref["path"]).is_absolute()
            and isinstance(ref["sha256"], str) and re.fullmatch("[a-f0-9]{64}", ref["sha256"]), "REFERENCE_INVALID")


def validate_recovery_config(value):
    _require(isinstance(value, dict) and not set(value) - {"selection", "maximum_seconds"}, "RECOVERY_CONFIG_INVALID")
    validate_selection(value.get("selection"))


def admit_pretransport_patch(selection, *, workspace_root, artifact_store, worker_configuration_ref=None):
    """Read exact original facts; no model, evaluator execution, write or approval.

    为什么要有它：已终结的发送前故障可以重用原Plan，但不能借恢复刷新预算或把已有发送当成零成本。
    """
    from src.mod_agent.fresh_planning_continuation import _csharp_source_snapshot, _source_tree_snapshot_sha256
    from src.mod_agent.interrupted_patch_admission import _read_inputs
    from src.mod_agent.model_call_budget import validate_budget
    from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
    from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256

    validate_selection(selection)
    workspace = Path(workspace_root).resolve(strict=True)
    journal, manifest, result = (_json(selection[key]) for key in
        ("source_attempt_ref", "parent_manifest_ref", "parent_result_ref"))
    _json(selection["execution_config_ref"])
    _require(Path(selection["parent_manifest_ref"]["path"]).resolve() == workspace / "run_manifest.json"
        and Path(selection["parent_result_ref"]["path"]).resolve() == workspace / "run_result.json"
        and Path(selection["source_attempt_ref"]["path"]).resolve().is_relative_to(artifact_store.root.resolve())
        and Path(manifest["isolated_workspace"]).resolve() == workspace
        and Path(journal["caller"]["workspace_root"]).resolve() == workspace
        and manifest["run_id"] == result["run_id"] == journal["parent_run_id"]
        and manifest["request_id"] == journal["request_id"], "PARENT_IDENTITY_MISMATCH")
    _require(manifest.get("terminal_record") == selection["parent_result_ref"]
        and result.get("product_execution_result", {}).get("execution_disposition") == "partial"
        and result["product_execution_result"].get("request_id") == journal["request_id"]
        and manifest.get("actual_write_performed") is False and result.get("actual_write_performed") is False
        and journal.get("receipt_version") == "patch_continuation_attempt_v1"
        and journal.get("continuation_selection") == "product_graph_current_implementation_plan"
        and journal.get("status") == "product_execution_finished"
        and journal.get("model_role") == "initial_patch"
        and journal.get("proposal_admitted") is False and journal.get("artifacts") == {}, "PARENT_NOT_PRETRANSPORT_FAILURE")
    blockers = result.get("blockers") or []
    _require(len(blockers) == 1 and blockers[0].get("stage") == "generate_patch_proposal_execution"
        and blockers[0].get("code") == "PRODUCT_NODE_EXECUTION_FAILED"
        and blockers[0].get("source_node") == "generate_patch_proposal", "FAILURE_STAGE_CHANGED")
    factory = journal["factory_receipt"]
    _require(factory.get("status") == "failed" and factory.get("failure")
        and type(factory.get("model_call_count")) is int and type(journal.get("model_call_count")) is int
        and factory.get("model_call_count") == journal.get("model_call_count") == 0
        and factory.get("provider_request") is None and factory.get("model_response") is None
        and factory.get("model_responses") == [] and not factory.get("worker_turns")
        and factory.get("patch_agent_loop", {}).get("status") == "not_started"
        and not factory.get("upstream_decision"), "PROVIDER_OR_WORKER_ALREADY_STARTED")
    receipts = result.get("patch_execution_receipts") or []
    _require(len(receipts) == 1 and {key: receipts[0].get(key) for key in ("path", "sha256")} == selection["source_attempt_ref"]
        and receipts[0].get("model_call_count") == 0 and receipts[0].get("proposal_admitted") is False
        and journal.get("terminal_result_sha256") == _hash(journal.get("terminal_result"))
        and journal["terminal_result"].get("parent_execution_disposition") == "partial"
        and journal["terminal_result"].get("owner_effect_invocations", {}).get("isolated_apply") == 0,
        "TERMINAL_RECEIPT_CHANGED")
    budget = validate_budget(result["model_call_budget"])
    _require(budget == journal["shared_model_budget"] and budget["consumed"] == result["model_call_count"] == manifest["model_call_count"]
        and budget["remaining"] > 0 and budget["by_stage"]["initial_patch"]["consumed"] == 0
        and budget["by_stage"]["repair"]["consumed"] == 0
        and journal["max_model_calls"] == factory["model_call_budget"]["maximum_total_model_calls"] == budget["remaining"], "BUDGET_MISMATCH")
    rows = [row for row in manifest.get("execution_observations", {}).values() if row.get("name") == "model.request"]
    roles = [row.get("attributes", {}).get("model_role") for row in rows]
    _require(len(rows) == budget["consumed"] and all(role in {"requirement_projection", "requirement_findings", "planning"} for role in roles)
        and all(roles.count(role) == budget["by_stage"][role]["consumed"] for role in set(roles)), "MODEL_HISTORY_CHANGED")
    original_ref = journal["worker_configuration_ref"]
    _read(original_ref)
    _require(worker_configuration_ref in (None, original_ref), "WORKER_CONFIGURATION_CHANGED")
    config = PatchWorkerConfiguration.load(original_ref["path"])
    _require(config.reference == original_ref and config.enable_recovery_loop and config.behavior_evaluator() is not None,
        "WORKER_CONFIGURATION_CHANGED")
    policy = replace(config.policy, max_total_model_turns=journal["max_model_calls"], model_call_budget_policy=budget.get("policy", "stage_and_total"))
    # 为什么要有它：原日志的policy是对外投影，缺省字段不表示放宽；逐个核对已记录项并保留完整原配置。
    _require(all(asdict(policy).get(key) == value for key, value in factory["patch_agent_loop"]["policy"].items())
        and journal["worker_profile_sha256"] == _hash(factory["profile"])
        and all(factory["profile"][key] == manifest["ollama_patch_generation_profile"][key]
            for key in ("context_window", "output_budget", "timeout_seconds", "automatic_retry", "automatic_provider_fallback"))
        and manifest["local_model_identity"] == result["local_model_identity"]
        and manifest["local_model_identity"].get("digest"), "MODEL_PROFILE_CHANGED")
    target = Path(manifest["nuget_isolated_build_profile"]["working_directory"]).resolve(strict=True)
    baseline = Path(manifest["baseline_build"]["build_profile"]["working_directory"]).resolve(strict=True)
    _require(target.is_relative_to(workspace / "generated_mods") and baseline.is_relative_to(workspace / "baseline_source"), "SOURCE_SCOPE_INVALID")
    expected = manifest["source_snapshot_sha256"]
    _require(all(source_snapshot_sha256(source_snapshot(path)) == expected for path in
        (Path(manifest["target_source"]), target, baseline)), "SOURCE_CHANGED")
    paths = tuple(sorted((str(path.relative_to(workspace).as_posix()) + "/" + name, digest)
        for path in (baseline, target) for name, digest in _csharp_source_snapshot(path)))
    _require(_source_tree_snapshot_sha256(paths) == journal["generated_against_snapshot_sha256"] == journal["current_snapshot_sha256"], "ORIGINAL_SNAPSHOT_CHANGED")
    feature, evidence, plan = _read_inputs(journal, artifact_store, workspace, original_ref)
    _require(feature["user_request"] == manifest["request"], "REQUEST_CHANGED")
    _require(all(result["artifacts"].get(kind) == ref["path"] for kind, ref in journal["selected_artifacts"].items())
        and not any(kind in result["artifacts"] for kind in ("patch_proposal", "proposal_review", "dry_run_result", "isolated_apply_result")), "SELECTED_ARTIFACTS_CHANGED")
    return {"selection": deepcopy(selection), "selected_artifacts": deepcopy(journal["selected_artifacts"]),
        "feature_id": journal["feature_id"], "request_id": journal["request_id"], "parent_run_id": journal["parent_run_id"],
        "user_request": manifest["request"], "feature_spec": feature, "evidence_pack": evidence, "implementation_plan": plan,
        "shared_model_budget": budget, "factory_receipt": {**deepcopy(factory), "model_identity": deepcopy(manifest["local_model_identity"])},
        "worker_configuration_ref": deepcopy(original_ref), "original_worker_configuration_ref": deepcopy(original_ref),
        "model_calls_performed": 0, "approval_inherited": False}
