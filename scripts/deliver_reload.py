"""Deliver the current verified Reload proposal, then recheck the formal DLL with the same oracle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.prepare_reload_trials import ref, same_source_snapshot, save
from src.mod_agent.evaluation.isolated_delivery_adapter import deliver, prepare_delivery
from src.mod_agent.evaluation.product_trial_batch import verify_product_model_proposal
from src.mod_agent.evaluation.task_measurement import measure_product_task
from src.mod_agent.model_qualification import read_bound_json
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration


def delivery_context(*, ready_ref, trial_id, continuation_result_ref=None):
    prepared = read_bound_json(ready_ref)
    trial = next(row for row in prepared["trials"] if row["trial_id"] == trial_id)
    dispatch = read_bound_json(ref(Path(trial["root"]) / "dispatch.json"))
    task = read_bound_json(prepared["task_ref"])
    for reference in dispatch["bound_inputs"] + dispatch["extra_load_refs"]:
        if ref(reference["path"]) != reference:
            raise ValueError("RELOAD_DELIVERY_INPUT_CHANGED")
    context = {"run_root": dispatch["run_root"], "trial": {
        "snapshot_root": trial["product_snapshot_root"], "bound_inputs": dispatch["bound_inputs"],
        "extra_load_refs": dispatch["extra_load_refs"], "delivery": {
            "policy_id": "startup_reload_user_task_delegation_20261003",
            "verification_selection": "current_proposal", "verifier_selection": "bound_worker_execution",
            "final_acceptance_required": True,
            "output_directory": "delivery"}}}
    if continuation_result_ref is not None:
        context["trial"]["delivery"]["initial_result_ref"] = continuation_result_ref
    checked = prepare_delivery(context)
    if not same_source_snapshot(checked["manifest"]["source_snapshot"], task["source_snapshot"]):
        raise ValueError("RELOAD_DELIVERY_INITIAL_SOURCE_CHANGED")
    report = read_bound_json(checked["verification_report_ref"])
    if report.get("verification_summary") != {"checks": 141, "failed_checks": 0, "executions": 9}:
        raise ValueError("RELOAD_COMPLETE_ORACLE_REQUIRED")
    proposal = json.loads(Path(checked["initial"]["artifacts"]["patch_proposal"]).read_text(encoding="utf-8"))["data"]
    allowed = "generated_mods/StartupNotice/Plugin.cs"
    if set(proposal["files"]) != {allowed}:
        raise ValueError("RELOAD_DELIVERY_SOURCE_SCOPE_CHANGED")
    return prepared, trial, dispatch, context, checked


def deliver_reload(*, ready_ref, trial_id, continuation_result_ref=None):
    prepared, trial, dispatch, context, checked = delivery_context(ready_ref=ready_ref, trial_id=trial_id, continuation_result_ref=continuation_result_ref)
    root = Path(dispatch["run_root"])
    measurement = measure_product_task(allowed_root=Path(prepared["root"]), run_root=root, run_id=root.name,
        continuation_roots=([checked["initial"]["continuation_root"]] if continuation_result_ref else ()))
    save(Path(trial["root"]) / "pre-delivery-measurement.json", measurement)
    proof = verify_product_model_proposal(root, checked["initial"], measurement, checked["verification_report_ref"])
    save(Path(trial["root"]) / "product-model-proof.json", proof)
    formal_results = []
    def verify_formal(assembly_ref):
        configuration = PatchWorkerConfiguration.load(dispatch["allocated_worker_ref"]["path"])
        evaluator = configuration.behavior_evaluator()
        dependency = checked["manifest"]["build_dependency"]["game_folder"]
        formal = evaluator.verify_existing_assembly(assembly_ref=assembly_ref, dependency_root=dependency["isolated_copy"],
            expected_dependency_snapshot_sha256=dependency["copy_snapshot_sha256"])
        formal_results.append(formal)
        if len(formal["checks"]) != 141 or len(formal["execution_refs"]) != 9:
            raise ValueError("RELOAD_FORMAL_ORACLE_INCOMPLETE")
        return formal
    result = deliver(context, final_artifact_verifier=verify_formal)
    if result.get("status") != "delivered":
        return save(Path(trial["root"]) / "delivery-result.json", {"status": "not_delivered", "owner_result": result})
    assembly = ref(checked["target"] / checked["expected_artifact"])
    if assembly not in result["evidence_refs"]:
        raise ValueError("RELOAD_FORMAL_BUILD_ARTIFACT_NOT_BOUND")
    formal = formal_results[0]
    passed = (formal["status"] == "passed" and len(formal["checks"]) == 141
              and len(formal["execution_refs"]) == 9 and all(row["passed"] is True for row in formal["checks"]))
    return save(Path(trial["root"]) / "delivery-result.json", {"status": "delivered" if passed else "formal_acceptance_failed",
        "delivery_complete": passed, "source_origin": "product_model_proposal", "product_model_proof": proof,
        "owner_result_ref": ref(root / "delivery/result.json"), "formal_dll_ref": assembly,
        "formal_acceptance_ref": formal["report_ref"], "case_count": len(formal["execution_refs"]),
        "check_count": len(formal["checks"]), "additional_model_calls": 0,
        "scope": "cold Load and real same-instance ConfigFile.Reload; constructor/Chainloader/watcher/game not executed"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--continuation-result", help="Exact saved same-task continuation result to deliver.")
    args = parser.parse_args()
    continuation_ref = ref(args.continuation_result) if args.continuation_result else None
    if args.prepare_only:
        _, _, _, _, checked = delivery_context(ready_ref=ref(args.ready), trial_id=args.trial_id, continuation_result_ref=continuation_ref)
        print(json.dumps({"status": "ready", "verification_report_ref": checked["verification_report_ref"], "applies": 0, "builds": 0}))
    else:
        print(json.dumps(deliver_reload(ready_ref=ref(args.ready), trial_id=args.trial_id, continuation_result_ref=continuation_ref)))


if __name__ == "__main__":
    main()
