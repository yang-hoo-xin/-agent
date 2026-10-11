"""Exact delegated platform delivery; the formal DLL is checked before delivered."""
import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_reload_trials import ref, save
from src.mod_agent.domain.full_project_compilation import _source_snapshot
from src.mod_agent.evaluation.isolated_delivery_adapter import deliver, prepare_delivery
from src.mod_agent.model_qualification import read_bound_json
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration


def finalize(ready_path):
    ready = read_bound_json(ref(ready_path))
    dispatch = read_bound_json(ref(Path(ready["records_root"]) / "dispatch.json"))
    bundle = read_bound_json(ready["bundle_ref"])
    context = {"run_root": dispatch["run_root"], "trial": {"snapshot_root": ready["product_snapshot_root"],
        "bound_inputs": dispatch["bound_inputs"], "extra_load_refs": dispatch["extra_load_refs"], "delivery": {
            "policy_id": ready.get("delivery_policy_id", "benchmark10_user_delegation_v1"), "verification_selection": "current_proposal",
            "verifier_selection": "bound_worker_execution", "final_acceptance_required": True}}}
    prepared = prepare_delivery(context)
    report = read_bound_json(prepared["verification_report_ref"])
    if report.get("verification_summary") != {"checks": bundle["expected_check_count"], "failed_checks": 0, "executions": bundle["cases"]}:
        raise ValueError("BENCHMARK_COMPLETE_SHARED_ORACLE_REQUIRED")
    baseline = {row["path"]: row["sha256"] for row in prepared["manifest"]["source_snapshot"]}
    expected = {row["path"]: row["sha256"] for row in bundle["source_snapshot"]}
    if baseline != expected:
        raise ValueError("BENCHMARK_DELIVERY_BASELINE_CHANGED")
    delivered_diff = {}

    def verify(assembly):
        after = {row["path"]: row["sha256"] for row in _source_snapshot(prepared["target"])}
        changed = [path for path in baseline.keys() | after.keys() if baseline.get(path) != after.get(path)]
        if set(after) != set(baseline) or any(path not in bundle["allowed_edit_paths"] for path in changed):
            raise ValueError("BENCHMARK_DELIVERED_SOURCE_SCOPE_CHANGED")
        delivered_diff.update(before=baseline, after=after, changed_paths=sorted(changed),
            generated_source_root=str(prepared["target"]), input_source_unchanged=(
                {row["path"]: row["sha256"] for row in _source_snapshot(Path(prepared["manifest"]["target_source"]))} == baseline))
        configuration = PatchWorkerConfiguration.load(dispatch["allocated_worker_ref"]["path"])
        dependency = prepared["manifest"]["build_dependency"]["game_folder"]
        return configuration.behavior_evaluator().verify_existing_assembly(assembly_ref=assembly,
            dependency_root=dependency["isolated_copy"] if dependency is not None else None,
            expected_dependency_snapshot_sha256=dependency["copy_snapshot_sha256"] if dependency is not None else None)

    result = deliver(context, final_artifact_verifier=verify)
    result["delivered_source_diff"] = delivered_diff
    result["input_source_unchanged"] = delivered_diff.get("input_source_unchanged")
    return save(Path(ready["records_root"]) / "delivery-result.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready", required=True)
    args = parser.parse_args()
    reference = finalize(args.ready)
    print(json.dumps(reference))
    raise SystemExit(0 if read_bound_json(reference).get("delivery_complete") is True else 2)
