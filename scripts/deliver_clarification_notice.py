"""Deliver a clarified StartupNotice only after its formal DLL passes the same oracle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def _ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return _ref(path)


def prepare_notice(*, ready_path, run_id):
    from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
    from src.mod_agent.evaluation.isolated_delivery_adapter import prepare_delivery
    from src.mod_agent.model_qualification import read_bound_json
    from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
    from src.mod_agent.platform_execution_snapshot import FrozenExecution

    ready = read_bound_json(_ref(ready_path))
    base = Path(ready["base"]).resolve(strict=True)
    if re.fullmatch(r"dsh_[0-9a-f]{32}", run_id) is None:
        raise ValueError("CLARIFICATION_DELIVERY_RUN_ID_INVALID")
    FrozenExecution(ready["source_freeze_ref"]).verify_files()
    template = read_bound_json(ready["worker_ref"])["behavior_evaluator"]
    root = base / "w" / run_id
    initial = read_bound_json(_ref(root / "run_result.json"))
    required = {"workflow_checkpoint", "feature_id", "request_id", "diff_hash", "unified_diff", "artifacts"}
    if (initial.get("status") != "awaiting_approval" or initial.get("run_id") != run_id
            or not required.issubset(initial)):
        raise ValueError("CLARIFICATION_DELIVERY_DEFERRED_PRODUCT_RESULT_REQUIRED")
    store = ArtifactStore(root / "a")
    checkpoint = store.semantic_read_immutable(ArtifactRef(**initial["workflow_checkpoint"]))["data"]
    state = checkpoint["state_snapshot"]
    proposal = store.semantic_read_immutable(ArtifactRef(feature_id=initial["feature_id"], artifact_type="patch_proposal",
        path=state["artifacts"]["patch_proposal"], artifact_hash=state["artifact_hashes"]["patch_proposal"]))["data"]
    selected = {}
    for change in proposal["diff_intent"]:
        generation = change["generation"]
        for evaluation in generation.get("patch_agent_loop", {}).get("behavior_evaluation_refs", []):
            if evaluation.get("status") == "passed" and evaluation.get("model_response_sha256") == generation["model_response_sha256"]:
                reference = evaluation["report_ref"]
                selected[(reference["path"], reference["sha256"])] = reference
    if len(selected) != 1:
        raise ValueError("CLARIFICATION_DELIVERY_CURRENT_REPORT_NOT_UNIQUE")
    report_ref = next(iter(selected.values()))
    report = read_bound_json(report_ref)
    if report.get("verification_summary") != {"checks": 9, "failed_checks": 0, "executions": 3}:
        raise ValueError("CLARIFICATION_DELIVERY_COMPLETE_ORACLE_REQUIRED")
    workers = {}
    for reference in initial.get("patch_execution_receipts", []):
        receipt = read_bound_json({key: reference[key] for key in ("path", "sha256")})
        factory = receipt.get("factory_receipt", {})
        for evaluation in factory.get("patch_agent_loop", {}).get("behavior_evaluations", []):
            if (evaluation.get("report_ref") == report_ref and evaluation.get("admission") == "accepted"
                    and evaluation.get("execution_origin") == "executed"
                    and evaluation.get("model_response_sha256") == report.get("model_response_sha256")):
                configured = factory["behavior_evaluator_configuration"]
                reference = receipt["worker_configuration_ref"]
                if configured["configuration_ref"] != reference:
                    raise ValueError("CLARIFICATION_DELIVERY_EXECUTED_WORKER_CHANGED")
                configuration = PatchWorkerConfiguration.load(reference["path"])
                evaluator = configuration.behavior_evaluator()
                if evaluator is None or configuration.reference != reference or evaluator.configuration_receipt() != configured:
                    raise ValueError("CLARIFICATION_DELIVERY_EXECUTED_WORKER_CHANGED")
                document = read_bound_json(reference)["behavior_evaluator"]
                if (document["factory_ref"] != template["factory_ref"]
                        or document["factory_name"] != "make_startup_notice_evaluator"
                        or document["kwargs"]["probe_configuration_ref"] != template["kwargs"]["probe_configuration_ref"]
                        or document["kwargs"].get("suppress_blank_messages") is not False
                        or evaluator.verification_identity() != report["verification_identity"]):
                    raise ValueError("CLARIFICATION_DELIVERY_ORACLE_CHANGED")
                workers[(reference["path"], reference["sha256"])] = reference
    if len(workers) != 1:
        raise ValueError("CLARIFICATION_DELIVERY_EXECUTED_ORACLE_REQUIRED")
    worker_ref = next(iter(workers.values()))
    context = {"run_root": str(root), "trial": {"delivery": {
        "verification_report_ref": report_ref, "verifier_sha256": report["verification_identity"]["validator_sha256"],
        "policy_id": "user-authorized-clarification-startup-isolated-delivery-v1", "final_acceptance_required": True}}}
    checked = prepare_delivery(context)
    return {"base": base, "root": root, "initial": initial, "context": context, "checked": checked,
            "worker_ref": worker_ref, "report_ref": report_ref, "ready_ref": _ref(ready_path)}


def formal_verifier(prepared):
    from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration

    def verify(assembly_ref):
        # 为什么要有它：Apply 后重新绑定当前源码，正式DLL仍用原已执行配置/探针/场景；回调完成前不能生成 delivered。
        reference = prepared["worker_ref"]
        if _ref(reference["path"]) != reference:
            raise ValueError("CLARIFICATION_DELIVERY_WORKER_CHANGED")
        evaluator = PatchWorkerConfiguration.load(reference["path"]).behavior_evaluator()
        dependency = prepared["checked"]["manifest"]["build_dependency"]["game_folder"]
        result = evaluator.verify_existing_assembly(assembly_ref=assembly_ref, dependency_root=dependency["isolated_copy"],
            expected_dependency_snapshot_sha256=dependency["copy_snapshot_sha256"])
        if result.get("status") == "passed" and (len(result.get("checks", [])) != 9 or len(result.get("execution_refs", [])) != 3):
            raise ValueError("CLARIFICATION_DELIVERY_FORMAL_ORACLE_INCOMPLETE")
        return result
    return verify


def deliver_notice(*, ready_path, run_id):
    from src.mod_agent.evaluation.isolated_delivery_adapter import deliver
    from src.mod_agent.evaluation.product_trial_batch import verify_product_model_proposal
    from src.mod_agent.evaluation.task_measurement import measure_product_task
    from src.mod_agent.evaluation.tool_effects import extract_tool_effects

    prepared = prepare_notice(ready_path=ready_path, run_id=run_id)
    measurement = measure_product_task(allowed_root=prepared["base"], run_root=prepared["root"], run_id=run_id)
    measurement["tool_effects"] = extract_tool_effects(measurement)
    _save(prepared["base"] / "pre-delivery-measurement.json", measurement)
    proof = verify_product_model_proposal(prepared["root"], prepared["initial"], measurement, prepared["report_ref"])
    _save(prepared["base"] / "product-model-proof.json", proof)
    _save(prepared["base"] / "verified-delivery-context.json", {"context": prepared["context"],
        "worker_ref": prepared["worker_ref"], "ready_ref": prepared["ready_ref"], "helper_ref": _ref(__file__)})
    result = deliver(prepared["context"], final_artifact_verifier=formal_verifier(prepared))
    return _save(prepared["base"] / "verified-delivery-result.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    ready = json.loads(Path(args.ready).read_bytes())
    # 为什么要有它：交付复用该试验冻结的产品和验收所有者，不能混入后来主树的validator代码。
    sys.path.insert(0, str(Path(ready["base"]) / "p"))
    if args.prepare_only:
        prepared = prepare_notice(ready_path=args.ready, run_id=args.run_id)
        print(json.dumps({"status": "ready", "candidate_report_ref": prepared["report_ref"],
                          "worker_ref": prepared["worker_ref"], "applies": 0, "builds": 0}))
    else:
        print(json.dumps(deliver_notice(ready_path=args.ready, run_id=args.run_id)))


if __name__ == "__main__":
    main()
