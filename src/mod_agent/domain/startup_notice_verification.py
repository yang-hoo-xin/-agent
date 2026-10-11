"""Assess retained real cold-Load observations for the startup-notice development task."""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import canonical_hash, read_bound_json

CASES = (("fresh", True, "Ready", None),
         ("stored_true_custom", True, "Explicit custom message", "[General]\nEnabled = true\nMessage = Explicit custom message\n"),
         ("stored_false_custom", False, "Disabled custom message", "[General]\nEnabled = false\nMessage = Disabled custom message\n"))


def assess_observation(observed, *, enabled, message, assembly_sha256, suppress_blank_messages=False):
    """Compare actual values and all captured logs, never a saved 'checks_passed' flag."""
    entries = observed.get("entries", [])
    expected = [{"section": "General", "key": "Enabled", "value": enabled,
                 "default_value": True, "value_type": "System.Boolean"},
                {"section": "General", "key": "Message", "value": message,
                 "default_value": "Ready", "value_type": "System.String"}]
    logs = [{"level": row.get("level"), "message": row.get("message")} for row in observed.get("logs", [])]
    return {
        "execution_binding": observed.get("status") == "observed" and observed.get("plugin_load_calls") == 1
            and observed.get("plugin_instance_constructor_skipped") is True
            and observed.get("injected_base_properties") == ["Config", "Log"]
            and observed.get("assembly_sha256") == assembly_sha256
            and observed.get("log_capture") == "real_bepinex_global_listener_including_injected_base_log_source",
        "configuration": json.dumps(entries, sort_keys=True) == json.dumps(expected, sort_keys=True),
        "logging": logs == ([{"level": "Info", "message": message}]
            if enabled and (not suppress_blank_messages or bool(message.strip())) else []),
    }


def verify_retained_startup_notice(*, postcheck_ref, worker_report_ref, output_root):
    """Bind exact executed probes and compiler output to the existing delegation contract.

    为什么要有它：离线汇总不能凭布尔结论授权Apply，必须回读实际进程输出、程序集、输入和模型源码身份。
    """
    bundle = read_bound_json(postcheck_ref)
    compile_ref = bundle["compiler_report_ref"]
    compiled = read_bound_json(compile_ref)
    worker = read_bound_json(worker_report_ref)
    if (worker["status"] != "passed" or worker["execution_origin"] != "executed"
            or worker["validation_results"]["full_compilation"]["changed"]["report_ref"] != compile_ref
            or worker["materialized_code_identity"] != compiled["materialized_code_identity"]):
        raise ValueError("STARTUP_NOTICE_WORKER_COMPILE_BINDING_CHANGED")
    assembly = compiled["built_artifact_ref"]
    if (compiled["status"] != "passed" or compiled["execution_origin"] != "executed"
            or compiled["all_required_files_compiled"] is not True
            or not re.fullmatch(r"version-\d{3,}", compiled["version_role"])
            or not compiled["changed_files"] or _ref(compiled["model_response_ref"]["path"]) != compiled["model_response_ref"]
            or _ref(assembly["path"]) != assembly
            or bundle["assembly_ref"] != assembly or bundle["materialized_code_identity"] != compiled["materialized_code_identity"]):
        raise ValueError("STARTUP_NOTICE_COMPILED_CANDIDATE_REQUIRED")
    for reference in bundle["probe_refs"]:
        if _ref(reference["path"]) != reference:
            raise ValueError("STARTUP_NOTICE_PROBE_CHANGED")
    probe = [ref for ref in bundle["probe_refs"] if Path(ref["path"]).name == "bepinex_plugin_probe.dll"]
    if len(probe) != 1 or [row["case"] for row in bundle["cases"]] != [row[0] for row in CASES]:
        raise ValueError("STARTUP_NOTICE_PROBE_OR_CASES_INVALID")
    checks, evidence_refs = [], [postcheck_ref, compile_ref, worker_report_ref, *bundle["probe_refs"]]
    for row, (name, enabled, message, seed) in zip(bundle["cases"], CASES):
        request = read_bound_json(row["request_ref"])
        observed = read_bound_json(row["stdout_ref"])
        execution_ref = _ref(Path(row["request_ref"]["path"]).parent / "execution.json")
        execution = read_bound_json(execution_ref)
        if (execution != row or row["exit_code"] != 0 or row["command"][1:] != [probe[0]["path"], row["request_ref"]["path"]]
                or request["assembly"] != assembly or request.get("seed_config") != seed
                or _ref(row["stderr_ref"]["path"]) != row["stderr_ref"]):
            raise ValueError("STARTUP_NOTICE_EXECUTION_BINDING_CHANGED")
        for reference in request["dependencies"]:
            if _ref(reference["path"]) != reference:
                raise ValueError("STARTUP_NOTICE_DEPENDENCY_CHANGED")
        for loaded in observed["loaded_dependencies"]:
            if _ref(loaded["path"])["sha256"] != loaded["sha256"]:
                raise ValueError("STARTUP_NOTICE_LOADED_DEPENDENCY_CHANGED")
        verdicts = assess_observation(observed, enabled=enabled, message=message, assembly_sha256=assembly["sha256"])
        checks.extend({"check_id": name + "." + key, "passed": passed,
            "expected": {"enabled": enabled, "message": message}, "observed_ref": row["stdout_ref"]}
            for key, passed in verdicts.items())
        evidence_refs.extend([row["request_ref"], row["stdout_ref"], row["stderr_ref"], execution_ref])
    passed = all(row["passed"] for row in checks)
    details = {"status": "passed" if passed else "behavior_failed", "execution_origin": "executed",
        "materialized_code_identity": compiled["materialized_code_identity"], "built_artifact_ref": assembly,
        "compilation_report_ref": compile_ref, "checks": checks, "evidence_refs": evidence_refs,
        "scope": "cold_Load_with_injected_BasePlugin_config_and_logging; constructor_and_game_not_executed; probe_saves_config"}
    output = Path(output_root)
    detail_ref = _save(output / "checks.json", details)
    report = {"status": details["status"], "failure_owner": None if passed else "patch_implementation",
        "execution_origin": "executed", "observations": [] if passed else [row for row in checks if not row["passed"]],
        "materialized_code_identity": compiled["materialized_code_identity"],
        "model_response_sha256": compiled["model_response_ref"]["sha256"],
        "generated_changes_sha256": worker["generated_changes_sha256"],
        "source_snapshot_sha256": worker["source_snapshot_sha256"],
        "implementation_plan_ref": compiled["implementation_plan_ref"],
        "verification_ref": detail_ref, "verification_summary": {"checks": len(checks),
            "failed_checks": sum(not row["passed"] for row in checks), "executions": len(CASES)},
        "verification_identity": {"validator_sha256": canonical_hash({"assessor": _ref(__file__), "probe": bundle["probe_refs"]}),
            "inputs_sha256": canonical_hash({"cases": CASES, "postcheck": postcheck_ref}),
            "environment_sha256": compiled["verification_identity"]["environment_sha256"]},
        "validation_results": {"full_compilation": {"status": "passed", "all_required_files_compiled": True,
            "report_ref": compile_ref}, "runtime": {"status": "not_executed"}},
        "verification_scope": details["scope"], "verifier_origin": "developer_configured_postcheck_not_original_patch_worker"}
    return {**report, "report_ref": _save(output / "report.json", report)}
