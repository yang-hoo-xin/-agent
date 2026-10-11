"""Measure a frozen set of existing local governance scenarios, without model/Build runs.

Each scenario is a semantic family, not an assertion, task, or independent trial.
Why: parameter variations and repeated assertions do not create independent samples.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scenario(number, title, file, tests, expected_cases, metrics, layer, observation):
    return {
        "scenario_id": f"G{number:02d}", "title": title,
        "selectors": [f"tests/unit/{file}.py::{name}" for name in tests],
        "expected_pytest_cases": expected_cases, "applicable_metrics": metrics,
        "execution_layer": layer, "asserted_observation": observation,
    }


APPLY = "production applier; real temporary source bytes; no model or compiler"
REVIEW = "production Graph/ArtifactStore/reviewed continuation; real temporary source and persistence; deterministic model fixture"
BUILD = REVIEW + "; injected compiler writes synthetic DLL bytes, no actual compiler"
SCENARIOS = [
    scenario(1, "Missing/empty/mismatched exact approval hash", "test_patch_apply", [
        "test_apply_rejects_missing_or_mismatched_exact_diff_hash"], 1, ["false_allow"], APPLY,
        "Three approval-hash variations reject; source bytes remain original."),
    scenario(2, "Semantic decision bound to another diff", "test_reviewed_patch_continuation", [
        "test_exact_decision_cannot_be_replaced_or_reused_for_another_diff"], 1, ["false_allow"], REVIEW,
        "Rejects mismatched diff; original source/store unchanged and no isolated copy."),
    scenario(3, "Explicit human rejection", "test_reviewed_patch_continuation", [
        "test_explicit_rejection_keeps_original_artifacts_and_workspace_unmodified"], 1, ["false_allow"], REVIEW,
        "No artifact/source writes or isolated copy after explicit reject."),
    scenario(4, "Source drift since displayed approval", "test_reviewed_patch_continuation", [
        "test_source_drift_invalidates_displayed_approval_before_isolation_copy"], 1, ["false_allow"], REVIEW,
        "Changed original source rejected before isolated copy."),
    scenario(5, "Non-code copy-tree drift", "test_reviewed_patch_continuation", [
        "test_non_code_project_file_change_invalidates_full_copy_binding"], 1, ["false_allow"], REVIEW,
        "Added project settings invalidate displayed binding; no isolated copy."),
    scenario(6, "Forbidden product path", "test_product_execution", [
        "test_product_execution_blocks_coverage_derived_forbidden_path_before_apply"], 1, ["false_allow"],
        "product executor/Graph; real isolated source and ArtifactStore; deterministic proposal provider",
        "BepInEx/core proposal blocked before Dry-run/Apply/Build; original and isolated bytes unchanged."),
    scenario(7, "Change outside bound source span", "test_patch_apply", [
        "test_dry_run_rejects_change_outside_bound_source_span"], 1, ["false_allow"], APPLY,
        "Dry-run rejects out-of-span edit; this case tests admission only, not allow_write=True."),
    scenario(8, "Missing Build authority or adapter", "test_reviewed_patch_continuation", [
        "test_build_continuation_requires_explicit_authorization_and_adapter"], 2, ["false_allow"], REVIEW,
        "Both missing authority and missing adapter reject with whole temporary tree unchanged."),
    scenario(9, "Build input original/isolated source drift", "test_reviewed_patch_continuation", [
        "test_build_continuation_rechecks_full_source_identity_before_effect"], 2, ["false_allow"], REVIEW,
        "Drift in either source tree rejects; forbidden Build callback never invoked; tree unchanged."),
    scenario(10, "Substituted Build resume diff/request identity", "test_reviewed_patch_continuation", [
        "test_build_resume_cannot_substitute_approved_identity"], 2, ["false_allow"], REVIEW,
        "Both identity substitutions reject before Build callback; tree unchanged."),
    scenario(11, "New proposal invalidates old approval", "test_reviewed_patch_continuation", [
        "test_new_proposal_revision_requires_review_and_approval_before_build"], 1, ["false_allow"], REVIEW,
        "New proposal revision returns STALE_RESUME_REJECTED before Build callback."),
    scenario(12, "Invalid Build output and attempted replay", "test_reviewed_patch_continuation", [
        "test_invalid_build_output_cannot_create_runtime_handoff_or_repeat_effect"], 3,
        ["false_allow", "duplicate_side_effect"], BUILD,
        "Supplied output, outside profile and modified input reject after one injected Build; no build-result artifact; replay cannot invoke Build twice."),
    scenario(13, "Deferred approval resumes then duplicate Apply resume", "test_deferred_product_approval", [
        "test_deferred_diff_resumes_same_workspace_and_then_existing_build_checkpoint"], 1,
        ["supported_continuation_success", "duplicate_side_effect"], BUILD,
        "Deferred Apply writes expected isolated bytes in original workspace; duplicate resume blocked; subsequent injected Build succeeds. This is planned continuation, not crash recovery."),
    scenario(14, "Approved Apply checkpoint resumes Build once", "test_reviewed_patch_continuation", [
        "test_approved_apply_checkpoint_continues_original_build_without_reapplying"], 1,
        ["supported_continuation_success", "duplicate_side_effect"], BUILD,
        "Build observes exact applied bytes, cannot recopy/reapply, callback invoked once even after repeated resume; zero additional model calls."),
    scenario(15, "Injected Build interruption refuses replay", "test_reviewed_patch_continuation", [
        "test_interrupted_build_consumes_resume_and_cannot_be_automatically_replayed"], 1,
        ["false_allow", "duplicate_side_effect"], REVIEW + "; callback raises KeyboardInterrupt, no compiler process",
        "Accepted resume is persisted; injected interruption propagates; second attempt is blocked; callback invoked once. Safe stop, not successful recovery."),
    scenario(16, "Filesystem partial/unknown write failures", "test_partial_apply_failure", [
        "test_second_replace_failure_records_confirmed_first_file_without_retry",
        "test_replace_that_changes_first_target_then_raises_remains_unknown",
        "test_target_readback_failure_keeps_returned_replacements_but_not_complete_claim",
        "test_temporary_write_failure_before_first_replace_confirms_no_target_write",
        "test_production_graph_failure_facts_block_build_and_do_not_retry"], 7,
        ["safe_failure_reporting"],
        "production applier real temporary bytes with injected os.replace/read/write errors; Graph propagation uses recording in-memory Store",
        "Before/after-effect failures retain actual partial/unknown facts; no automatic retry or downstream Build. No recovery success or general atomicity claim."),
    scenario(17, "Read recovery of accepted durable resume", "test_workflow_graph", [
        "test_exact_accepted_resume_can_be_read_recovered_before_runtime"], 1,
        ["supported_recovery_success", "duplicate_side_effect"],
        "production WorkflowCheckpointStore and real ArtifactStore reopened in same process; synthetic Build inputs; no runtime effect",
        "New store instance reads identical accepted updates/report and exactly one resume_report exists. Does not inject/kill a real process."),
    scenario(18, "Task-total model reservation exhausted", "test_task_total_budget", [
        "test_task_total_passes_old_stage_zero_and_preserves_both_snapshot_forms"], 1,
        ["false_allow"], "production budget owner; in-memory counters; no provider invocation",
        "After reserving exactly 13 calls, next reservation throws and counters stay unchanged; legacy input snapshot preserved."),
]
SCENARIOS[12]["selectors"].append(
    "tests/unit/test_governance_scenario_measurement.py::"
    "test_deferred_duplicate_resume_has_one_physical_apply_and_one_apply_artifact"
)
SCENARIOS[12]["expected_pytest_cases"] = 2
SCENARIOS[12]["asserted_observation"] += (
    " Supplement observes one allow_write applier invocation and one Apply artifact; replay leaves both source trees unchanged."
)

UNTESTED = [
    {"boundary": "Real process kill/power loss at arbitrary write points", "status": "not_tested"},
    {"boundary": "Automatic completion after partially applied filesystem writes", "status": "not_tested"},
    {"boundary": "Concurrent duplicate requests across processes", "status": "not_tested"},
    {"boundary": "Real compiler, deployment and live game side effects", "status": "not_tested"},
    {"boundary": "OS-level symlink/junction escape and hostile external mutation races", "status": "not_tested"},
]


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def source_snapshot():
    """Bind current Python/schema bytes, including uncommitted and untracked source."""
    paths = [ROOT / "pyproject.toml"]
    for folder in ("src", "scripts", "tests/unit"):
        paths.extend((ROOT / folder).rglob("*.py"))
    paths.extend((ROOT / "schemas").rglob("*.json"))
    return {str(path.relative_to(ROOT)).replace("\\", "/"):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}


def summarize(scenarios, junit_root):
    rows = []
    cases = list(junit_root.iter("testcase"))
    for item in scenarios:
        selected = []
        for selector in item["selectors"]:
            filename, name = selector.split("::")
            classname = filename.removesuffix(".py").replace("/", ".")
            selected.extend(case for case in cases
                            if case.get("classname") == classname
                            and (case.get("name") == name or case.get("name", "").startswith(name + "[")))
        passed = sum(not any(case.find(kind) is not None for kind in ("failure", "error", "skipped"))
                     for case in selected)
        complete = len(selected) == item["expected_pytest_cases"]
        status = "passed" if complete and passed == len(selected) else "unresolved"
        rows.append({**item, "status": status, "observed_pytest_cases": len(selected),
                     "passed_pytest_cases": passed,
                     "testcase_results": [{"classname": case.get("classname"), "name": case.get("name"),
                                           "status": next((kind for kind in ("failure", "error", "skipped")
                                                           if case.find(kind) is not None), "passed")}
                                          for case in selected]})
    metrics = {}
    for metric in sorted({metric for item in scenarios for metric in item["applicable_metrics"]}):
        applicable = [row for row in rows if metric in row["applicable_metrics"]]
        known = [row for row in applicable if row["status"] == "passed"]
        # Unresolved tests are unknown, not evidence of a measured unsafe effect.
        # 为什么要有它：测试框架失败或缺项不能伪造错误放行次数，也不能悄悄缩小适用分母。
        numerator = 0 if metric in {"false_allow", "duplicate_side_effect"} else len(known)
        metrics[metric] = {"observed_numerator": numerator, "observed_denominator": len(known),
                           "applicable_scenarios": len(applicable), "unknown_scenarios": len(applicable) - len(known),
                           "scenario_ids": [row["scenario_id"] for row in applicable],
                           "rate": numerator / len(known) if known else None}
    return {"scenarios": rows, "metrics": metrics,
            "scenario_count": len(rows), "passed_scenario_count": sum(row["status"] == "passed" for row in rows),
            "pytest_case_count": len(cases), "untested": UNTESTED, "untested_boundary_count": len(UNTESTED)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    before = source_snapshot()
    write_json(output / "selection.json", {"schema_version": "governance_selection.v1", "scenarios": SCENARIOS,
                                          "unit": "semantic scenario family, not assertions or independent tasks",
                                          "untested": UNTESTED})
    write_json(output / "source_before.json", before)
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    temporary = Path(tempfile.mkdtemp(prefix="gov-")) / "t"
    command = [sys.executable, "-B", "-m", "pytest", "-q", "--tb=short", "-o", "addopts=",
               "--basetemp", str(temporary), "--junitxml", str(output / "junit.xml")]
    command.extend(selector for item in SCENARIOS for selector in item["selectors"])
    write_json(output / "command.json", {"argv": command, "cwd": str(ROOT), "started_utc": started,
                                        "python": sys.version, "platform": platform.platform(),
                                        "git_head": git.stdout.strip(), "git_head_is_complete_source_identity": False})
    clock = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    elapsed = time.perf_counter() - clock
    (output / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (output / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    after = source_snapshot()
    write_json(output / "source_after.json", after)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    xml = ET.parse(output / "junit.xml").getroot() if (output / "junit.xml").exists() else ET.Element("testsuites")
    summary = summarize(SCENARIOS, xml)
    summary.update(schema_version="governance_measurement.v1", started_utc=started,
                   finished_utc=datetime.now(timezone.utc).isoformat(), pytest_exit_code=result.returncode,
                   elapsed_seconds=elapsed, source_paths_changed_during_run=changed,
                   version_binding_stable=not changed, temporary_test_artifacts=str(temporary),
                   metric_basis="Existing assertions reviewed before selection; passed complete families prove only their explicitly asserted outcome.",
                   independence="Known development regression scenarios, not unseen tasks, random faults, or independent repetitions.",
                   process_crash_recovery_rate=None)
    write_json(output / "summary.json", summary)
    print(json.dumps({"output": str(output), "pytest_exit_code": result.returncode,
                      "scenario_count": summary["scenario_count"], "passed_scenario_count": summary["passed_scenario_count"],
                      "pytest_case_count": summary["pytest_case_count"], "metrics": summary["metrics"],
                      "elapsed_seconds": elapsed, "changed_source_paths": changed}, ensure_ascii=False, indent=2))
    return result.returncode or (0 if summary["passed_scenario_count"] == len(SCENARIOS) and not changed else 1)


if __name__ == "__main__":
    raise SystemExit(main())
