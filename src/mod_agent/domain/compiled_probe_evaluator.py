"""Shared full-compilation/probe execution and evidence binding for configured tasks.

为什么要有它：新增行为协议复用同一编译、进程和回执链，不能各自复制另一套执行器。
"""
from __future__ import annotations

import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from src.core.trace.execution_trace import trace_operation
from src.mod_agent.build.dependencies import _binary_tree_snapshot, _binary_tree_snapshot_sha256
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import canonical_hash, read_bound_json


def project_config_logging_observation(observed, key):
    """Keep effective config, complete logs and scope; raw execution stays source-bound."""
    if key in {"configuration", "logging"}:
        # 为什么要有它：配置/日志修订需要实际值与执行边界；加载文件、目录和进程回执留在原execution_ref，避免同一执行元数据反复耗尽观察预算。
        return {name: deepcopy(observed.get(name)) for name in (
            "status", "entries", "logs", "plugin_load_calls", "plugin_instance_constructor_skipped",
            "injected_base_properties", "assembly_sha256", "log_capture", "scope")}
    return deepcopy(observed)


class CompiledProbeEvaluator:
    error_prefix = "COMPILED_PROBE"

    def error(self, code):
        return ValueError(self.error_prefix + "_" + code)

    def check_observation(self, observed, key):
        return observed

    def check_expectation(self, expected, key):
        return expected

    def runtime_validation_result(self, status, detail_ref):
        """Managed probes do not imply a launched game runtime."""
        return {"status": "not_executed"}

    def candidate_source_refs(self, compiled):
        """Optional source inputs for protocols that assess their observation code.

        为什么要有它：候选日志的解释依赖实际编译源码时，源码必须与 DLL 一同绑定和复查。
        """
        return []

    def assembly_file_refs(self, assembly):
        """Return candidate files read by this protocol's execution host.

        为什么要有它：库探针默认只加载 DLL；可执行 CLI 协议还需绑定实际运行时清单。
        """
        return [assembly]

    def __init__(self, *, compilation, output_root, probe_configuration_ref):
        self.compilation = compilation
        self.output_root = Path(output_root).resolve()
        self.probe_configuration_ref = deepcopy(probe_configuration_ref)
        self.configuration = read_bound_json(probe_configuration_ref)
        self.cases = self.case_definitions()
        self.timeout_seconds = self.configuration.get("timeout_seconds", 20)
        if type(self.timeout_seconds) not in (int, float) or not 0 < self.timeout_seconds <= 120:
            raise self.error("TIMEOUT_INVALID")
        self.verification_identity()

    def verification_identity(self):
        config = read_bound_json(self.probe_configuration_ref)
        if config != self.configuration:
            raise self.error("CONFIGURATION_CHANGED")
        probe = Path(config["assembly_path"])
        if probe.name != self.probe_filename:
            raise self.error("PROBE_REQUIRED")
        # 为什么要有它：dotnet 会读取旁边的运行时配置与依赖清单，仅绑定 DLL 不能固定实际验收程序。
        for path in (probe, probe.with_suffix(".deps.json"), probe.with_suffix(".runtimeconfig.json")):
            if _ref(path) not in config["files"]:
                raise self.error("PROBE_FILE_UNBOUND")
        for reference in [*config["files"], config["dotnet"]]:
            if _ref(reference["path"]) != reference:
                raise self.error("PROBE_OR_DOTNET_CHANGED")
        child = self.compilation.verification_identity()
        return {"validator_sha256": canonical_hash({"owner": _ref(__file__),
                    "protocol": [_ref(path) for path in self.protocol_sources], "compilation": child,
                    "probe": self.probe_configuration_ref, "files": config["files"]}),
                "inputs_sha256": canonical_hash({"compilation": child["inputs_sha256"], "cases": self.cases,
                    "protocol_parameters": self.protocol_parameters, "timeout_seconds": self.timeout_seconds}),
                "environment_sha256": canonical_hash({"compilation": child["environment_sha256"], "dotnet": config["dotnet"]}),
                "deterministic_reuse_allowed": False}

    def __call__(self, context):
        self.verification_identity()
        feedback = self.compilation(context)
        # 为什么要有它：复用现有编译反馈可保留 CS1061 的依赖说明、真实失败和稳定比较投影，不另建修复循环。
        identity = self.verification_identity()
        if feedback["status"] != "passed":
            report = {**feedback, "verification_identity": identity, "verification_scope": self.scope}
            report.pop("report_ref", None)
            report["compilation_feedback_ref"] = feedback["report_ref"]
            return {**report, "report_ref": _save(self.output_root / uuid4().hex / "report.json", report)}
        full = feedback["validation_results"]["full_compilation"]
        compiled = full["changed"]
        saved = read_bound_json(compiled["report_ref"])
        if saved != {key: value for key, value in compiled.items() if key != "report_ref"}:
            raise self.error("COMPILE_BINDING_CHANGED")
        response_ref = {"path": context["model_response"]["path"], "sha256": context["model_response"]["output_sha256"]}
        if (compiled.get("status") != "passed" or compiled.get("execution_origin") != "executed"
                or compiled.get("all_required_files_compiled") is not True
                or compiled.get("materialized_code_identity") != context["materialized_code_identity"]
                or compiled.get("implementation_plan_ref") != context["implementation_plan_ref"]
                or compiled.get("model_response_ref") != response_ref or _ref(response_ref["path"]) != response_ref):
            raise self.error("CANDIDATE_BINDING_CHANGED")
        assembly = compiled["built_artifact_ref"]
        if _ref(assembly["path"]) != assembly:
            raise self.error("ASSEMBLY_CHANGED")
        assembly_files = self.assembly_file_refs(assembly)
        if (not isinstance(assembly_files, list) or assembly not in assembly_files
                or any(_ref(ref["path"]) != ref for ref in assembly_files)):
            raise self.error("ASSEMBLY_FILES_CHANGED")
        # 为什么要有它：BCL 工程不应附加虚构游戏依赖，但实际加载的运行时仍须由配置逐文件绑定。
        if compiled["dependency_binding"] is None:
            if compiled["dependency_copy"] is not None:
                raise self.error("COMPILED_DEPENDENCY_COPY_UNEXPECTED")
            dependencies = []
        else:
            dependency_root = Path(compiled["dependency_copy"]["isolated_copy"])
            if _binary_tree_snapshot_sha256(_binary_tree_snapshot(dependency_root)) != compiled["dependency_binding"]["snapshot_sha256"]:
                raise self.error("COMPILED_DEPENDENCY_TREE_CHANGED")
            dependencies = [_ref(path) for path in sorted(dependency_root.rglob("*.dll"))]
        source_refs = self.candidate_source_refs(compiled)
        if not isinstance(source_refs, list) or any(_ref(ref["path"]) != ref for ref in source_refs):
            raise self.error("CANDIDATE_SOURCE_CHANGED")
        run, checks, executions, status, owner = self._execute_probe_cases(assembly, dependencies, assembly_files)
        if self.verification_identity() != identity or any(_ref(ref["path"]) != ref for ref in [*assembly_files, response_ref, *dependencies, *source_refs]):
            raise self.error("VALIDATION_INPUT_CHANGED")
        details = {"status": status, "execution_origin": "executed", "checks": checks, "execution_refs": executions,
            "probe_configuration_ref": self.probe_configuration_ref, "materialized_code_identity": compiled["materialized_code_identity"],
            "compilation_report_ref": compiled["report_ref"], "built_artifact_ref": assembly,
            "assembly_files": assembly_files, "candidate_source_refs": source_refs, "scope": self.scope}
        detail_ref = _save(run / "checks.json", details)
        observations = [{"check_id": row["check_id"], "input": {"execution_ref": row["execution_ref"]},
            "expected": row["expected"], "observed": row["observed"]} for row in checks if not row["passed"]]
        report = {"status": status, "failure_owner": owner,
            "owner_binding_ids": [row["edit_binding_id"] for row in context["generated_changes"]] if owner == "patch_implementation" else [],
            "observations": observations, "execution_origin": "executed", "verification_ref": detail_ref,
            "verification_summary": {"checks": len(checks), "failed_checks": len(observations), "executions": len(executions)},
            "verification_identity": identity, "verification_scope": self.scope,
            "materialized_code_identity": context["materialized_code_identity"],
            "implementation_plan_ref": context["implementation_plan_ref"], "model_response_sha256": response_ref["sha256"],
            "generated_changes_sha256": context["generated_changes_sha256"], "source_snapshot_sha256": context["source_snapshot_sha256"],
            "compilation_feedback_ref": feedback["report_ref"],
            "validation_results": {"full_compilation": {"status": "passed", "all_required_files_compiled": True,
                "report_ref": compiled["report_ref"]}, "runtime": self.runtime_validation_result(status, detail_ref)}}
        if owner == "patch_implementation":
            # 为什么要有它：目录、进程号与执行回执不同不代表修复取得进展；原始失败仍在 observations 和执行记录中。
            report["failure_state_observations"] = [{"check_id": row["check_id"], "expected": row["expected"],
                "observed": self.stable_observation(row["observed"])}
                for row in observations]
        return {**report, "report_ref": _save(run / "report.json", report)}



    def _execute_probe_cases(self, assembly, dependencies, assembly_files):
        run = self.output_root / uuid4().hex
        run.mkdir(parents=True, exist_ok=False)
        checks, executions = [], []
        status, owner = "passed", None
        allowed = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "DOTNET_ROOT",
            "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "APPDATA", "LOCALAPPDATA", "USERPROFILE")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
        with trace_operation(self.trace_name, attributes={"verification_scope": self.scope}) as operation:
            for case in self.cases:
                name = case[0]
                case_root = run / name
                sandbox = case_root / "sandbox"
                sandbox.mkdir(parents=True, exist_ok=False)
                request_ref = _save(case_root / "request.json", {"assembly": assembly, "assembly_files": assembly_files, "dependencies": dependencies,
                    "sandbox_root": str(sandbox), **self.request_fields(case)})
                command = [self.configuration["dotnet"]["path"], self.configuration["assembly_path"], request_ref["path"]]
                raw = {"case": name, "command": command, "request_ref": request_ref, "environment_keys": sorted(environment)}
                try:
                    process = subprocess.run(command, cwd=sandbox, env=environment, capture_output=True,
                        text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds)
                    raw.update(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr)
                except (subprocess.TimeoutExpired, OSError) as error:
                    def decode(value):
                        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
                    raw.update(exit_code=None, error_type=type(error).__name__, message=str(error),
                        stdout=decode(getattr(error, "stdout", None)), stderr=decode(getattr(error, "stderr", None)))
                execution_ref = _save(case_root / "execution.json", raw)
                executions.append(execution_ref)
                try:
                    observed = json.loads(raw["stdout"])
                    if not isinstance(observed, dict):
                        raise self.error("OBJECT_OBSERVATION_REQUIRED")
                except ValueError:
                    observed = {"status": "invalid_probe_output", "execution_ref": execution_ref}
                expected = self.expected(case)
                if raw["exit_code"] != 0 or observed.get("status") != "observed":
                    patch_failure = observed.get("execution_phase") in self.patch_failure_phases
                    status, owner = ("behavior_failed", "patch_implementation") if patch_failure else ("infrastructure_failed", "validator")
                    checks.append({"check_id": name + ".execution", "passed": False, "expected": expected,
                        "observed": observed, "execution_ref": execution_ref})
                    break
                # 为什么要有它：成功日志必须来自同一候选 DLL 和已绑定依赖，探针回执本身不能免除身份复查。
                if observed.get("assembly_sha256") != assembly["sha256"]:
                    raise self.error("OBSERVED_ASSEMBLY_CHANGED")
                loaded = observed.get("loaded_dependencies", [])
                allowed_loaded = dependencies + self.configuration["files"]
                if not loaded or any({"path": row["path"], "sha256": row["sha256"]} not in allowed_loaded
                        or _ref(row["path"])["sha256"] != row["sha256"] for row in loaded):
                    raise self.error("LOADED_DEPENDENCY_UNBOUND")
                verdicts = self.assess(observed, case, assembly["sha256"])
                checks.extend({"check_id": name + "." + key, "passed": passed,
                    "expected": self.check_expectation(expected, key),
                    "observed": self.check_observation(observed, key), "execution_ref": execution_ref}
                    for key, passed in verdicts.items())
            if status == "passed" and any(not row["passed"] for row in checks):
                status, owner = "behavior_failed", "patch_implementation"
            operation.update(verification_status=status, checks_run=len(checks), process_count=len(executions))
        return run, checks, executions, status, owner

    def verify_existing_assembly(self, *, assembly_ref, dependency_root=None, expected_dependency_snapshot_sha256=None):
        """Run this same bound protocol on a separately recorded formal Build artifact.

        为什么要有它：正式DLL须执行相同场景，不复用候选通过标记，也不触发第二次编译。
        """
        identity = self.verification_identity()
        if _ref(assembly_ref["path"]) != assembly_ref:
            raise self.error("ASSEMBLY_CHANGED")
        # 为什么要有它：无外部依赖工程的正式交付也须执行原探针，不能伪造游戏目录或跳过声明过的依赖。
        if dependency_root is None:
            if (expected_dependency_snapshot_sha256 is not None
                    or self.compilation.checker.dependency_binding is not None):
                raise self.error("FORMAL_DEPENDENCY_REQUIRED")
            root, dependencies = None, []
        else:
            if expected_dependency_snapshot_sha256 is None:
                raise self.error("FORMAL_DEPENDENCY_REQUIRED")
            root = Path(dependency_root).resolve(strict=True)
            if _binary_tree_snapshot_sha256(_binary_tree_snapshot(root)) != expected_dependency_snapshot_sha256:
                raise self.error("COMPILED_DEPENDENCY_TREE_CHANGED")
            dependencies = [_ref(path) for path in sorted(root.rglob("*.dll"))]
        assembly_files = self.assembly_file_refs(assembly_ref)
        if any(_ref(ref["path"]) != ref for ref in assembly_files):
            raise self.error("ASSEMBLY_FILES_CHANGED")
        run, checks, executions, status, owner = self._execute_probe_cases(assembly_ref, dependencies, assembly_files)
        if (self.verification_identity() != identity
                or any(_ref(ref["path"]) != ref for ref in [*assembly_files, *dependencies])
                or (root is not None and _binary_tree_snapshot_sha256(_binary_tree_snapshot(root)) != expected_dependency_snapshot_sha256)):
            raise self.error("VALIDATION_INPUT_CHANGED")
        result = {"status": status, "failure_owner": owner, "assembly_ref": assembly_ref,
                  "checks": checks, "execution_refs": executions, "verification_identity": identity,
                  "probe_configuration_ref": self.probe_configuration_ref,
                  "protocol_parameters": self.protocol_parameters, "scope": self.scope,
                  "compilation_performed": False, "model_calls": 0}
        return {**result, "report_ref": _save(run / "formal-dll-result.json", result)}
