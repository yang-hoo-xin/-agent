"""Compile and observe the existing observer in an isolated, freshly launched game.

为什么要有它：编译成功不能证明查找到了真实面板；失败观测须回到同一 Patch 修订协议。
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re
from uuid import uuid4

from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator
from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import canonical_hash, read_bound_json


SCOPE = "real_game_single_panel_observation_with_preserved_logging_scaffold_not_complete_readonly_multiobject_or_keyboard_acceptance"
UNCOVERED = ["complete_read_only_semantics", "multiple_object_unknown_behavior", "physical_keyboard_edges"]
PREFIX = "S1_OBSERVER_V2 "


def _same_path(left, right):
    return str(left).replace("\\", "/").rstrip("/").casefold() == str(right).replace("\\", "/").rstrip("/").casefold()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def source_scaffold_observation(original, candidate):
    """Conservative source support gate, not a proof of all read-only behavior."""
    original, candidate = (value.replace("\r\n", "\n") for value in (original, candidate))
    start = "                nextDiscovery=elapsed+0.5;\n"
    end = "            }\n            if(behaviour==null) panelStatus=discoveryStatus;"
    if original.count(start) != 1 or candidate.count(start) != 1 or original.count(end) != 1 or candidate.count(end) != 1:
        return {"status": "review_required", "reason": "observation_scaffold_boundaries_changed"}
    before, original_rest = original.split(start)
    _, after = original_rest.split(end)
    new_before, new_rest = candidate.split(start)
    lookup, new_after = new_rest.split(end)
    if before != new_before or after != new_after:
        return {"status": "review_required", "reason": "observation_code_outside_lookup_changed"}
    # 为什么要有它：同一进程中的模型代码也能输出伪成功；保留原日志路径并将可疑副作用交给审核，不能仅凭成功字符串验收。
    suspicious = (r"\b(?:Emit|LogInfo|LogWarning|WriteLine|Step|Bind|SetValue|Invoke)\s*\(",
        r"\b(?:Visible|Readout|Alpha|panelStatus|readoutStatus|visible|readout|alpha|frames|elapsed|frame)\s*(?:=(?!=)|\+=|\+\+)",
        r"S1_OBSERVER|\b(?:File|Process|StreamWriter|Console)\s*\.", r"\b(?:unsafe|DllImport)\b")
    if any(re.search(pattern, lookup) for pattern in suspicious):
        return {"status": "review_required", "reason": "lookup_requires_side_effect_or_logging_review"}
    return {"status": "supported", "reason": "original_observation_scaffold_preserved",
            "scope": "static_scaffold_preservation_only", "complete_read_only_semantics_proven": False}


def parse_observer_log(raw):
    rows, errors = [], 0
    for line in raw.decode("utf-8-sig", errors="replace").splitlines():
        if PREFIX not in line:
            continue
        try:
            row = json.loads(line.split(PREFIX, 1)[1])
            if not isinstance(row, dict):
                raise ValueError("object required")
            rows.append(row)
        except (ValueError, TypeError):
            errors += 1
    return rows, errors


def assess_observer_rows(rows, expected):
    """Assess field values, not text markers; caller supplies process/log identity."""
    loaded = [row for row in rows if row.get("kind") == "loaded"]
    started = [row for row in rows if row.get("kind") == "started"]
    frames = [row for row in rows if row.get("kind") == "frame"]
    numeric = all(type(row.get("frame")) is int and type(row.get("observed_frame_sequence")) is int
                  and _number(row.get("elapsed")) for row in frames)
    increasing = numeric and all(b["frame"] > a["frame"] and b["observed_frame_sequence"] > a["observed_frame_sequence"]
                                and b["elapsed"] > a["elapsed"] for a, b in zip(frames, frames[1:]))
    sampled = [row for row in frames if row.get("readout_sample") is True]
    duration = frames[-1]["elapsed"] - frames[0]["elapsed"] if frames and numeric else 0
    enough = bool(increasing and len(sampled) >= expected["min_samples"] and duration >= expected["min_elapsed_seconds"])
    # 为什么要有它：启动期未知不应掩盖稳定期失败；固定稳定期后的实际记录必须逐条满足声明。
    stable = [row for row in frames if _number(row.get("elapsed")) and row["elapsed"] >= expected["min_elapsed_seconds"]]
    stable_samples = [row for row in stable if row.get("readout_sample") is True]
    panel_ok = bool(stable) and all(row.get("panel_found") is True and row.get("panel_status") == "observed"
                                     and type(row.get("visible")) is bool for row in stable)
    readout_ok = bool(stable_samples) and all(row.get("readout_status") == "observed" and isinstance(row.get("readout"), str)
                                            and row["readout"].strip() for row in stable_samples)
    changing = readout_ok and len({row["readout"] for row in stable_samples}) > 1
    alpha_ok = bool(stable_samples) and all(_number(row.get("alpha")) and abs(row["alpha"] - expected["alpha"]) <= 1e-6
                                          for row in stable_samples)
    checks = {"plugin_loaded": len(loaded) == 1 and loaded[0].get("schema") == expected["schema"]
              and loaded[0].get("observer_version") == expected["observer_version"],
              "actual_lateupdate": len(started) == 1 and enough,
              "bound_panel_observed": panel_ok, "readout_changes": bool(changing), "alpha_preserved": alpha_ok}
    observation = {"sample_count": len(sampled), "stable_sample_count": len(stable_samples), "elapsed_span_seconds": duration,
        "frame_sequence_increasing": bool(increasing), "panel_statuses": sorted({str(row.get("panel_status")) for row in stable}),
        "known_panel_samples": sum(row.get("panel_found") is True for row in stable_samples),
        "nonempty_readout": bool(readout_ok), "readout_changed": bool(changing), "alpha_matches": alpha_ok,
        "uncovered": UNCOVERED}
    return checks, observation


class ObserverRuntimeEvaluator(CompiledProbeEvaluator):
    error_prefix = "OBSERVER_RUNTIME"
    scope = SCOPE

    def __init__(self, *, compilation, output_root, runtime_configuration_ref):
        self.compilation = compilation
        self.output_root = Path(output_root).resolve()
        self.probe_configuration_ref = deepcopy(runtime_configuration_ref)
        self.configuration = read_bound_json(runtime_configuration_ref)
        if self.configuration.get("schema") != "observer-runtime-evaluator.v1":
            raise self.error("CONFIGURATION_SCHEMA")
        self.protocol_parameters = deepcopy(self.configuration["expected"])
        expected = self.protocol_parameters
        if (not _number(expected.get("min_elapsed_seconds")) or expected["min_elapsed_seconds"] < 2
                or type(expected.get("min_samples")) is not int or expected["min_samples"] < 10
                or not _number(expected.get("alpha")) or not isinstance(expected.get("schema"), str)
                or not isinstance(expected.get("observer_version"), str)):
            raise self.error("EXPECTATION_INVALID")
        if self.configuration.get("source_filename") != "Observer.cs":
            raise self.error("SOURCE_FILENAME")
        self._candidate_source_ref = None
        self._candidate_compilation_ref = None
        self._runtime_executed = False
        self.verification_identity()

    def verification_identity(self):
        from src.mod_agent.runtime import isolated_candidate
        if read_bound_json(self.probe_configuration_ref) != self.configuration:
            raise self.error("CONFIGURATION_CHANGED")
        original = self.configuration["original_source_ref"]
        if _ref(original["path"]) != original:
            raise self.error("ORIGINAL_SOURCE_CHANGED")
        config = self.configuration["owner_config"]
        references = [config["game_executable_ref"], config["expected_prior_plugin_ref"], *config["protected_file_refs"]]
        if any(_ref(ref["path"]) != ref for ref in references):
            raise self.error("RUNTIME_INPUT_CHANGED")
        child = self.compilation.verification_identity()
        return {"validator_sha256": canonical_hash({"owner": _ref(__file__), "shared": _ref(__import__(CompiledProbeEvaluator.__module__, fromlist=["__file__"]).__file__),
                "runtime_owner": _ref(isolated_candidate.__file__), "compilation": child, "configuration": self.probe_configuration_ref}),
            "inputs_sha256": canonical_hash({"compilation": child["inputs_sha256"], "original": original, "expected": self.protocol_parameters}),
            "environment_sha256": canonical_hash({"compilation": child["environment_sha256"], "runtime_files": references}),
            "deterministic_reuse_allowed": False}

    def candidate_source_refs(self, compiled):
        root = Path(compiled["isolated_source_root"]).resolve(strict=True)
        candidates = [path for path in root.rglob(self.configuration["source_filename"]) if not {"obj", "bin"}.intersection(path.relative_to(root).parts)]
        if len(candidates) != 1:
            raise self.error("CANDIDATE_SOURCE_AMBIGUOUS")
        self._candidate_source_ref = _ref(candidates[0])
        self._candidate_compilation_ref = compiled.get("report_ref")
        relative = candidates[0].relative_to(root).as_posix()
        inputs = read_bound_json(compiled["source_inputs_ref"])
        if (inputs.get(relative) != self._candidate_source_ref["sha256"]
                or {"path": relative, "sha256": self._candidate_source_ref["sha256"]} not in compiled["compile_inputs"]):
            raise self.error("CANDIDATE_SOURCE_NOT_COMPILED")
        return [self._candidate_source_ref]

    def runtime_validation_result(self, status, detail_ref):
        return {"status": "executed" if self._runtime_executed else "not_executed", "outcome": status,
                "report_ref": detail_ref, "scope": self.scope, "uncovered": UNCOVERED}

    def stable_observation(self, observed):
        # 为什么要有它：新进程的采样数和耗时不构成修复进展，同一真实故障应保持稳定比较。
        return {key: deepcopy(observed[key]) for key in ("reason", "panel_statuses", "nonempty_readout", "readout_changed", "alpha_matches", "uncovered") if key in observed}

    def _execute_probe_cases(self, assembly, dependencies, assembly_files):
        from src.mod_agent.runtime.isolated_candidate import run_isolated_runtime_candidate
        run = self.output_root / uuid4().hex[:12]
        run.mkdir(parents=True, exist_ok=False)
        self._runtime_executed = False
        source_ref = self._candidate_source_ref
        if source_ref is None or _ref(source_ref["path"]) != source_ref:
            raise self.error("CANDIDATE_SOURCE_REQUIRED")
        original = self.configuration["original_source_ref"]
        scaffold = source_scaffold_observation(Path(original["path"]).read_bytes().decode("utf-8-sig"),
                                               Path(source_ref["path"]).read_bytes().decode("utf-8-sig"))
        scope_ref = _save(run / "source-scope.json", {"original_source_ref": original, "candidate_source_ref": source_ref,
                         "compilation_report_ref": self._candidate_compilation_ref, **scaffold})
        if scaffold["status"] != "supported":
            checks = [{"check_id": "observer.source_review", "passed": False, "expected": "Preserved observation scaffold or an independent source review.",
                       "observed": scaffold, "execution_ref": scope_ref}]
            return run, checks, [scope_ref], "infrastructure_failed", "validator"
        result = run_isolated_runtime_candidate(config=deepcopy(self.configuration["owner_config"]), candidate_ref=assembly,
                                                output_directory=run / "runtime")
        result_ref = _save(run / "execution.json", result)
        self._runtime_executed = bool((result.get("process") or {}).get("pid"))
        checks, status, owner = self.assess_runtime_result(result, assembly, result_ref)
        return run, checks, [scope_ref, result_ref], status, owner

    def assess_runtime_result(self, result, assembly, execution_ref):
        def blocked(reason):
            return [{"check_id": "observer.runtime_environment", "passed": False, "expected": "Bound candidate, current-process raw logs, completed cleanup and unchanged protected files.",
                     "observed": {"reason": reason}, "execution_ref": execution_ref}], "infrastructure_failed", "validator"
        config = self.configuration["owner_config"]
        if (result.get("status") != "collected" or result.get("candidate_ref") != assembly
                or result.get("protected_files_unchanged") is not True or not (result.get("process") or {}).get("pid")
                or (result.get("process") or {}).get("exited") is not True):
            return blocked("runtime_owner_did_not_collect_bound_clean_execution")
        rows, malformed, texts = [], 0, []
        try:
            runner = read_bound_json(result["runner_ref"])
            deployment = read_bound_json(result["deployment_ref"])
            restoration = read_bound_json(result["restoration_ref"])
            windows_ref = result["log_windows_ref"]
            if _ref(windows_ref["path"]) != windows_ref:
                return blocked("runtime_log_window_manifest_changed")
            final_windows = json.loads(Path(windows_ref["path"]).read_bytes())
            if not isinstance(final_windows, list):
                return blocked("runtime_log_window_manifest_invalid")
            if (not _same_path(deployment.get("source_path"), assembly["path"])
                    or deployment.get("source_sha256") != assembly["sha256"]
                    or deployment.get("destination_sha256_after_copy") != assembly["sha256"]
                    or not _same_path(deployment.get("destination_path"), config["expected_prior_plugin_ref"]["path"])
                    or deployment.get("destination_sha256_before") != config["expected_prior_plugin_ref"]["sha256"]):
                return blocked("candidate_deployment_unbound")
            if restoration.get("restored") is not True or restoration.get("process") != result["process"]:
                return blocked("runtime_restoration_unconfirmed")
            trust = runner["runtime_trust_binding"]["checks"]
            process = trust["runtime_process_identity"]
            logs = trust["current_run_logs"]
            if (process.get("status") != "passed" or process.get("pid") != result["process"]["pid"]
                    or process.get("launched") is not True or process.get("liveness_observed") is not True
                    or logs.get("status") != "passed" or logs.get("collected_after_process_start") is not True
                    or logs.get("process_pid") != process["pid"]):
                return blocked("current_process_or_log_boundary_not_bound")
            for entry in result["current_run_logs"]:
                reference, window = entry["ref"], entry["source_window"]
                earlier = next((row for row in logs["source_windows"] if _same_path(row.get("path"), entry["source_path"])), {})
                boundary_fields = ("baseline_size_bytes", "baseline_content_sha256", "baseline_captured_at_ns", "run_local_start_byte")
                if (_ref(reference["path"]) != reference or window.get("status") != "passed"
                        or window.get("run_local_sha256") != reference["sha256"]
                        or window not in final_windows or window not in logs["source_windows"] or not earlier
                        or any(window.get(key) != earlier.get(key) for key in boundary_fields)):
                    return blocked("current_log_bytes_or_window_not_bound")
                if not _same_path(entry["source_path"], Path(config["game_root"]) / "BepInEx" / "LogOutput.log"):
                    continue
                raw = Path(reference["path"]).read_bytes()
                parsed, errors = parse_observer_log(raw)
                rows.extend(parsed)
                malformed += errors
                texts.append(raw.decode("utf-8-sig", errors="replace"))
        except (OSError, KeyError, TypeError, ValueError):
            return blocked("runtime_evidence_unreadable_or_unbound")
        if malformed:
            return blocked("malformed_observer_records")
        verdicts, observation = assess_observer_rows(rows, self.protocol_parameters)
        loaded = next((row for row in rows if row.get("kind") == "loaded"), {})
        hud_refs = [ref for ref in config["protected_file_refs"] if Path(ref["path"]).name == "FramePulse.dll"]
        if (len(hud_refs) != 1 or not _same_path(loaded.get("subject_path"), hud_refs[0]["path"])
                or not _same_path(loaded.get("executable"), config["game_executable_ref"]["path"])
                or not any("Frame Pulse loaded" in text and "Loading [S1 Runtime Observer " in text for text in texts)):
            return blocked("subject_or_plugin_load_not_bound")
        if not verdicts["plugin_loaded"] or not verdicts["actual_lateupdate"]:
            return blocked("insufficient_loaded_plugin_or_increasing_runtime_samples")
        checks = [{"check_id": "observer." + name, "passed": passed, "expected": deepcopy(self.protocol_parameters),
                   "observed": observation, "execution_ref": execution_ref} for name, passed in verdicts.items()]
        if all(verdicts.values()):
            return checks, "passed", None
        return checks, "behavior_failed", "patch_implementation"

    def verify_existing_assembly(self, *, candidate_source_ref, compilation_report_ref, **kwargs):
        # 为什么要有它：分别核对源码与 DLL 哈希不能证明二者来自同一次编译；正式重验也须同一编译回执。
        compiled = read_bound_json(compilation_report_ref)
        if (compiled.get("built_artifact_ref") != kwargs["assembly_ref"] or compiled.get("status") != "passed"
                or compiled.get("all_required_files_compiled") is not True or compiled.get("execution_origin") != "executed"):
            raise self.error("EXISTING_ASSEMBLY_COMPILE_BINDING")
        if self.candidate_source_refs(compiled) != [candidate_source_ref]:
            raise self.error("EXISTING_SOURCE_COMPILE_BINDING")
        self._candidate_compilation_ref = deepcopy(compilation_report_ref)
        self._candidate_source_ref = deepcopy(candidate_source_ref)
        if (_ref(candidate_source_ref["path"]) != candidate_source_ref
                or read_bound_json(compilation_report_ref) != compiled):
            raise self.error("CANDIDATE_SOURCE_CHANGED")
        result = super().verify_existing_assembly(**kwargs)
        if (_ref(candidate_source_ref["path"]) != candidate_source_ref
                or read_bound_json(compilation_report_ref) != compiled):
            raise self.error("CANDIDATE_SOURCE_CHANGED")
        return result


def make_observer_runtime_evaluator(*, compilation_kwargs, output_root, runtime_configuration_ref):
    scope = uuid4().hex[:8]
    parameters = deepcopy(compilation_kwargs)
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters,
        output_root=str(Path(output_root) / scope / "compile"))
    return ObserverRuntimeEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "runtime",
                                    runtime_configuration_ref=runtime_configuration_ref)
