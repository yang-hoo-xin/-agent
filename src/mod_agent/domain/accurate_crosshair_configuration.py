"""Actual BepInEx configuration I/O over the compiled crosshair source version.

This checks the existing configuration API, not Unity loading or the automatic
LiveEdit event source. The changed Mod implementation is never supplied here.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from src.core.trace.execution_trace import trace_operation
from src.mod_agent.model_qualification import canonical_hash, read_bound_json

SECTION = "General Settings"
SWITCH_KEY = "Accurate Spread Enabled"
EXISTING_DEFAULTS = {"FollowsRecoil": True, "FirstShotType": "Inner", "FirstShotMinDelay": 0.15,
                     "PopEnabled": False, "MinSize": 10, "SpeedScalar": 1}
CONFIG_KEYS = ("Follow Recoil", "First Shot Display Mode", "First Shot Min Delay",
               "Pop Enabled", "Minimum Size", "Resize Modifier", SWITCH_KEY)
CONFIGURATION_CHECKS = ("fresh.exact_keys", "fresh.spread_default_true", "fresh.original_defaults",
    "false.file_value", "false.reader_value", "false.independent_settings",
    "restart_false.file_value", "restart_false.reader_value",
    "reload_true.file_value", "reload_true.reader_value", "reload_true.event",
    "restart_true.file_value", "restart_true.reader_value")


def _reference(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return _reference(path)


def _config(enabled):
    return ("[General Settings]\n" + SWITCH_KEY + " = " + str(enabled).lower() + "\n"
            "Follow Recoil = false\nFirst Shot Display Mode = Match\nFirst Shot Min Delay = 0.25\n"
            "Pop Enabled = true\nMinimum Size = 20\nResize Modifier = 0.5\n")


def _entry(observed, field):
    values = [row["value"] for row in observed[field]
              if row["section"] == SECTION and row["key"] == SWITCH_KEY]
    return values[0] if len(values) == 1 else None


def assess_configuration(observations):
    """Check task obligations; absent supported reader is unknown, not a repair hint."""
    fresh, off, restart_off, reload_on, restart_on = observations
    rows = []
    def check(name, actual, expected):
        rows.append({"check_id": name, "observed": actual, "expected": expected,
                     "passed": actual == expected and (type(actual) is bool if type(expected) is bool else True)})
    check("fresh.exact_keys", sorted((row["section"], row["key"]) for row in fresh["keys"]),
          sorted((SECTION, key) for key in CONFIG_KEYS))
    check("fresh.spread_default_true", _entry(fresh, "initial_entries"), True)
    check("fresh.original_defaults", {key: fresh["initial"].get(key) for key in EXISTING_DEFAULTS}, EXISTING_DEFAULTS)
    for label, observed, field, expected in (("false", off, "initial", False),
            ("restart_false", restart_off, "initial", False),
            ("reload_true", reload_on, "reloaded", True), ("restart_true", restart_on, "initial", True)):
        check(label + ".file_value", _entry(observed, "final_entries" if field == "reloaded" else "initial_entries"), expected)
        check(label + ".reader_value", observed[field].get("AccurateSpreadEnabled"), expected)
        if label == "false":
            check("false.independent_settings", {key: off["initial"].get(key) for key in EXISTING_DEFAULTS},
                  {"FollowsRecoil": False, "FirstShotType": "Match", "FirstShotMinDelay": 0.25,
                   "PopEnabled": True, "MinSize": 20, "SpeedScalar": 0.5})
        if label == "reload_true":
            check("reload_true.event", observed["reload_events"], 1)
    if tuple(row["check_id"] for row in rows) != CONFIGURATION_CHECKS:
        raise ValueError("CONFIGURATION_CHECK_SET_CHANGED")
    # The fixed matrix also uses this existing observed reader. A different
    # implementation surface requires verifier adaptation, not forced renaming.
    unknown_reader = any(_entry(row, "initial_entries") is not None and
                         row["initial"].get("AccurateSpreadEnabled") is None for row in observations)
    return rows, unknown_reader


class ActualCrosshairConfigurationChecker:
    def __init__(self, *, probe_configuration_ref, output_root, timeout_seconds=20):
        self.probe_configuration_ref = dict(probe_configuration_ref)
        self.configuration = read_bound_json(probe_configuration_ref)
        self.output_root = Path(output_root).resolve()
        self.timeout_seconds = timeout_seconds
        if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 120:
            raise ValueError("CONFIGURATION_TIMEOUT_INVALID")
        self.calls = 0
        self.verification_identity()

    def verification_identity(self):
        configuration = read_bound_json(self.probe_configuration_ref)
        assembly_ref = _reference(configuration["assembly_path"])
        if assembly_ref not in configuration["files"]:
            raise ValueError("CONFIGURATION_PROBE_ASSEMBLY_UNBOUND")
        for ref in configuration["files"]:
            if _reference(ref["path"]) != ref:
                raise ValueError("CONFIGURATION_PROBE_CHANGED")
        if _reference(configuration["dotnet"]["path"]) != configuration["dotnet"]:
            raise ValueError("CONFIGURATION_DOTNET_CHANGED")
        return {"validator_sha256": canonical_hash({"checker": _reference(__file__),
                    "probe": self.probe_configuration_ref, "files": configuration["files"]}),
                "inputs_sha256": canonical_hash({"checks": CONFIGURATION_CHECKS, "section": SECTION,
                    "switch_key": SWITCH_KEY, "existing_defaults": EXISTING_DEFAULTS}),
                "environment_sha256": canonical_hash(configuration["dotnet"]),
                "deterministic_reuse_allowed": False}

    def __call__(self, compilation):
        if compilation.get("status") != "passed" or not compilation.get("all_required_files_compiled"):
            return {"status": "not_executed", "reason": "full_compilation_not_passed", "checks": []}
        saved = read_bound_json(compilation["report_ref"])
        if any(saved.get(key) != compilation.get(key) for key in
               ("built_artifact_ref", "materialized_code_identity", "dependency_copy", "status")):
            raise ValueError("CONFIGURATION_COMPILE_BINDING_CHANGED")
        assembly = compilation["built_artifact_ref"]
        if _reference(assembly["path"]) != assembly:
            raise ValueError("CONFIGURATION_ASSEMBLY_CHANGED")
        identity = self.verification_identity()
        dependencies = [_reference(path) for path in sorted(Path(compilation["dependency_copy"]["isolated_copy"]).rglob("*.dll"))]
        self.calls += 1
        run = self.output_root / ("configuration_" + str(self.calls))
        run.mkdir(parents=True, exist_ok=False)
        fresh = Path(tempfile.mkdtemp(prefix="ac-cfg-fresh-"))
        stored = Path(tempfile.mkdtemp(prefix="ac-cfg-stored-"))
        configurations = (("fresh", fresh, None, None), ("false", stored, _config(False), None),
            ("restart_false", stored, None, None), ("reload_true", stored, None, _config(True)),
            ("restart_true", stored, None, None))
        observations, process_refs = [], []
        status, failure_owner = "passed", None
        failed_execution = []
        with trace_operation("validate.configuration", attributes={"verification_scope": "actual_bepinex_config_io"}) as operation:
            for label, sandbox, seed, reload in configurations:
                request = {"assembly": assembly, "dependencies": dependencies, "sandbox_root": str(sandbox),
                           "seed_config": seed, "reload_config": reload}
                request_ref = _save(run / (label + "-input.json"), request)
                allowed = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "DOTNET_ROOT",
                    "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "APPDATA", "LOCALAPPDATA", "USERPROFILE")
                environment = {key: os.environ[key] for key in allowed if key in os.environ}
                environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
                command = [self.configuration["dotnet"]["path"], self.configuration["assembly_path"], request_ref["path"]]
                with trace_operation("configuration.process", attributes={"process_index": len(process_refs) + 1}) as process_span:
                    try:
                        process = subprocess.run(command, cwd=sandbox, env=environment, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds)
                        raw = {"exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr,
                               "environment_keys": sorted(environment), "request_ref": request_ref}
                        process_span.update(exit_code=process.returncode)
                        process_refs.append(_save(run / (label + "-process.json"), raw))
                        observed = json.loads(process.stdout)
                        if process.returncode != 0 or observed.get("status") != "observed":
                            if observed.get("failure_owner") == "patch_implementation":
                                status, failure_owner = "behavior_failed", "patch_implementation"
                                failed_execution.append({"check_id": label + ".execution", "passed": False,
                                    "expected": "Configuration executes successfully for the valid bound input.",
                                    "observed": observed})
                                break
                            raise ValueError("CONFIGURATION_PROCESS_DID_NOT_OBSERVE")
                        if observed["configuration_assembly_sha256"] != assembly["sha256"]:
                            raise ValueError("CONFIGURATION_PROCESS_ASSEMBLY_MISMATCH")
                        observations.append(observed)
                    except (subprocess.TimeoutExpired, OSError, ValueError) as error:
                        status, failure_owner = "infrastructure_failed", "validator"
                        process_refs.append(_save(run / (label + "-failure.json"), {"error_type": type(error).__name__}))
                        break
            checks, reader_unknown = assess_configuration(observations) if len(observations) == 5 else ([], False)
            checks.extend(failed_execution)
            if reader_unknown:
                status, failure_owner = "needs_evidence", "validator"
            elif any(not row["passed"] for row in checks):
                status, failure_owner = "behavior_failed", "patch_implementation"
            operation.update(verification_status=status, checks_run=len(checks),
                checks_failed=sum(not row["passed"] for row in checks), process_count=len(observations))
        if self.verification_identity() != identity or _reference(assembly["path"]) != assembly:
            raise ValueError("CONFIGURATION_VALIDATION_INPUT_CHANGED")
        if any(_reference(ref["path"]) != ref for ref in dependencies):
            raise ValueError("CONFIGURATION_DEPENDENCIES_CHANGED")
        report = {"status": status, "failure_owner": failure_owner, "checks": checks,
                  "process_refs": process_refs, "observations": observations, "verification_identity": identity,
                  "compilation_report_ref": compilation["report_ref"], "built_artifact_ref": assembly,
                  "materialized_code_identity": compilation["materialized_code_identity"],
                  "reader_mapping": "AccurateCrosshair.Configuration.AccurateSpreadEnabled",
                  "reader_mapping_status": "needs_verifier_adaptation" if reader_unknown else "observed",
                  "runtime_status": "not_executed", "automatic_liveedit_status": "not_executed",
                  "scope": "compiled_configuration_real_bepinex_io_and_reload_consumer_only"}
        return {**report, "report_ref": _save(run / "report.json", report)}
