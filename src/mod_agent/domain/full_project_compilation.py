"""Isolated whole-project compilation of B0 and exact model-produced bytes.

This is an opt-in pre-approval verifier, not product Apply or the formal Build
workflow stage. Source/configuration files remain unchanged; the existing local
build owner controls restore/build/cache and dependency-copy execution.
"""
from __future__ import annotations

import codecs
import hashlib
import json
import shutil
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path, PurePosixPath
from uuid import uuid4
from xml.etree import ElementTree

from src.core.trace.execution_trace import trace_operation
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.build import baseline_repair
from src.mod_agent.build import dependencies as dependency_build
from src.mod_agent.build import nuget as nuget_build
from src.mod_agent.build.adapter import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.build.baseline_repair import classify_source_compilation_failure
from src.mod_agent.build.dependencies import (
    RunLocalGameFolderBindingV1,
    _binary_tree_snapshot,
    _binary_tree_snapshot_sha256,
    _materialize_game_folder_build_dependency,
    _validate_game_folder_build_binding,
)
from src.mod_agent.build.nuget import (
    _create_nuget_isolated_build_profile,
    _run_nuget_isolated_build,
)
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.model_qualification import canonical_hash, read_bound_json

_COPY_IGNORES = ("bin", "obj", ".git", ".idea")


def _ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    return _ref(path)


def _source_snapshot(root):
    return tuple(row for row in _binary_tree_snapshot(root)
                 if not any(part in _COPY_IGNORES for part in PurePosixPath(row["path"]).parts))


def _within(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("FULL_COMPILE_RELATIVE_PATH_REQUIRED")
    resolved = (root / relative).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def _capture_targets():
    project = ElementTree.Element("Project")
    target = ElementTree.SubElement(project, "Target", Name="RecordControlledCompileInputs", BeforeTargets="CoreCompile")
    ElementTree.SubElement(target, "WriteLinesToFile", File="$(ControlledCompileInputsFile)",
        Lines="@(Compile->'%(FullPath)')", Overwrite="true", Encoding="UTF-8")
    return ElementTree.tostring(project, encoding="utf-8", xml_declaration=True)


def _compile_input_rows(path, isolated_source):
    rows = []
    if path.is_file():
        for value in path.read_text(encoding="utf-8-sig").splitlines():
            source = Path(value).resolve(strict=True)
            relative = source.relative_to(isolated_source).as_posix()
            rows.append({"path": relative, "sha256": _ref(source)["sha256"]})
    return rows


def _source_compilation_errors(*, execution, output, isolated_source, project_root, source_inputs):
    expected = {}
    for relative, digest in source_inputs.items():
        path = _within(isolated_source, relative)
        if path.suffix == ".cs" and path.is_relative_to(project_root):
            expected[path.relative_to(project_root).as_posix()] = digest
    return classify_source_compilation_failure(execution=execution, output=output,
        project_root=project_root, expected_sources=expected)


class FullProjectCompilationChecker:
    """One fresh baseline followed by separately isolated exact source versions."""

    def __init__(self, *, source_root, project_relative_path, artifact_store_root,
                 dependency_binding: RunLocalGameFolderBindingV1 | None, nuget_config_ref,
                 output_root, expected_artifact, timeout_seconds=120, build_runner=None,
                 workspace_root=None):
        self.source_root = Path(source_root).resolve(strict=True)
        self.workspace_root = (Path(workspace_root).resolve(strict=True)
                               if workspace_root is not None else self.source_root)
        self._source_prefix = self.source_root.relative_to(self.workspace_root).as_posix()
        self.project_relative_path = project_relative_path
        self.project = _within(self.source_root, project_relative_path)
        if not self.project.is_file() or self.project.suffix != ".csproj":
            raise ValueError("FULL_COMPILE_PROJECT_REQUIRED")
        self.store = ArtifactStore(artifact_store_root)
        self.dependency_binding = dependency_binding
        self.nuget_config_ref = dict(nuget_config_ref)
        if _ref(nuget_config_ref["path"]) != self.nuget_config_ref:
            raise ValueError("FULL_COMPILE_NUGET_CONFIG_CHANGED")
        self.output_root = Path(output_root).resolve()
        try:
            self.output_root.relative_to(self.source_root)
        except ValueError:
            pass
        else:
            raise ValueError("FULL_COMPILE_OUTPUT_MUST_BE_SEPARATE")
        self.expected_artifact = expected_artifact
        _within(self.output_root, expected_artifact)
        self.timeout_seconds = timeout_seconds
        self._runner = build_runner or _run_nuget_isolated_build
        self._source_identity = _source_snapshot(self.source_root)
        self._baseline = None
        self._dependency = None
        self._calls = 0

    def adopt_baseline(self, report_ref):
        """Reuse a bound fresh baseline without rewriting its original execution record."""
        if self._baseline is not None:
            raise ValueError("FULL_COMPILE_BASELINE_ALREADY_SELECTED")
        report = read_bound_json(report_ref)
        current = self.verification_identity()
        if (report.get("version_role") != "baseline" or report.get("status") not in {"passed", "compilation_failed"}
                or report.get("all_required_files_compiled") is not True
                or any(report["verification_identity"].get(key) != current[key]
                       for key in ("inputs_sha256", "environment_sha256"))
                or Path(report["isolated_source_root"]).parent.parent != self.output_root):
            raise ValueError("FULL_COMPILE_BASELINE_REUSE_IDENTITY_MISMATCH")
        names = ("source_inputs_ref", "compile_inputs_ref", "stdout_ref", "stderr_ref")
        for name in (*names, *(("built_artifact_ref",) if report["status"] == "passed" else ())):
            if _ref(report[name]["path"]) != report[name]:
                raise ValueError("FULL_COMPILE_BASELINE_REUSE_FILE_CHANGED")
        if report.get("dependency_binding") != (self.dependency_binding.to_dict() if self.dependency_binding else None):
            raise ValueError("FULL_COMPILE_BASELINE_DEPENDENCY_BINDING_MISMATCH")
        self._dependency = deepcopy(report["dependency_copy"])
        self._targets_path = self.output_root / "record-compile-inputs.targets"
        if self._targets_path.read_bytes() != _capture_targets():
            raise ValueError("FULL_COMPILE_BASELINE_TARGETS_CHANGED")
        if _source_snapshot(Path(report["isolated_source_root"])) != self._source_identity:
            raise ValueError("FULL_COMPILE_BASELINE_COPY_CHANGED")
        isolated_source = Path(report["isolated_source_root"])
        copied = {row["path"]: row["sha256"] for row in self._source_identity}
        required = {path: digest for path, digest in copied.items() if path.endswith(".cs")}
        rows = _compile_input_rows(Path(report["compile_inputs_ref"]["path"]), isolated_source)
        actual = {row["path"]: row["sha256"] for row in rows}
        project_root = _within(isolated_source, self.project_relative_path).parent
        if (read_bound_json(report["source_inputs_ref"]) != copied
                or report["project_root"] != str(project_root)
                or rows != report["compile_inputs"]
                or not rows or any(actual.get(path) != digest for path, digest in required.items())):
            raise ValueError("FULL_COMPILE_BASELINE_REUSE_INPUT_MISMATCH")
        if report["status"] == "compilation_failed":
            diagnostics = _source_compilation_errors(execution=report["build_execution"],
                output="\n".join(Path(report[name]["path"]).read_text(encoding="utf-8")
                    for name in ("stdout_ref", "stderr_ref")),
                isolated_source=isolated_source, project_root=project_root, source_inputs=copied)
            build = report.get("build_result") or {}
            if (not diagnostics or list(diagnostics) != report.get("source_compilation_errors")
                    or build.get("status") != "failed" or build.get("real_build_performed") is not True
                    or build.get("claims_real_build_success") is not False
                    or report.get("built_artifact_ref") is not None):
                raise ValueError("FULL_COMPILE_BASELINE_REUSE_FAILURE_MISMATCH")
        if _ref(self.output_root / "nuget.config")["sha256"] != self.nuget_config_ref["sha256"]:
            raise ValueError("FULL_COMPILE_BASELINE_CONFIG_CHANGED")
        self._validate_dependency_copy()
        self._baseline = {**report, "report_ref": dict(report_ref)}
        return deepcopy(self._baseline)

    def verification_identity(self):
        if _source_snapshot(self.source_root) != self._source_identity:
            raise ValueError("FULL_COMPILE_SOURCE_CHANGED")
        if _ref(self.nuget_config_ref["path"]) != self.nuget_config_ref:
            raise ValueError("FULL_COMPILE_NUGET_CONFIG_CHANGED")
        coordinate = ({"plan_source_prefix": self._source_prefix}
                      if self.workspace_root != self.source_root else {})
        return {"validator_sha256": canonical_hash({"checker": _ref(__file__),
                    "build_adapter": _ref(Path(__file__).parents[1] / "build/adapter.py"),
                    "baseline_failure_classifier": _ref(baseline_repair.__file__),
                    "build_execution_owner": _ref(nuget_build.__file__),
                    "dependency_copy_owner": _ref(dependency_build.__file__)}),
                "inputs_sha256": canonical_hash({"sources": self._source_identity,
                    "project": self.project_relative_path, "expected_artifact": self.expected_artifact,
                    "nuget_config": self.nuget_config_ref, **coordinate}),
                "environment_sha256": canonical_hash(self.dependency_binding.to_dict() if self.dependency_binding else None),
                "environment_identity_scope": ("exact_game_dependency_tree_and_declared_build_profile_not_entire_host"
                    if self.dependency_binding else "no_external_dependency_binding_declared_build_profile_not_entire_host"),
                "deterministic_reuse_allowed": False}

    def _prepare(self):
        # 为什么要有它：仅使用 BCL 的工程没有游戏依赖，不能伪造游戏目录来满足编译接口。
        identity = (_validate_game_folder_build_binding(self.dependency_binding, canonical_source_root=self.source_root)
                    if self.dependency_binding is not None else None)
        self.output_root.mkdir(parents=True, exist_ok=False)
        self._dependency = (_materialize_game_folder_build_dependency(identity, run_root=self.output_root)
                            if identity is not None else None)
        config = self.output_root / "nuget.config"
        with config.open("xb") as stream:
            stream.write(Path(self.nuget_config_ref["path"]).read_bytes())
        # Existing MSBuild hook, used only to record the actual @(Compile) set.
        self._targets_path = self.output_root / "record-compile-inputs.targets"
        with self._targets_path.open("xb") as stream:
            stream.write(_capture_targets())

    def _validate_dependency_copy(self):
        # 为什么要有它：无依赖声明和复制回执必须一致，避免恢复旧基线时偷偷继承另一棵依赖树。
        if self.dependency_binding is None:
            if self._dependency is not None:
                raise ValueError("FULL_COMPILE_DEPENDENCY_COPY_UNEXPECTED")
        elif (self._dependency is None or
                _binary_tree_snapshot_sha256(_binary_tree_snapshot(Path(self._dependency["isolated_copy"])))
                != self.dependency_binding.snapshot_sha256):
            raise ValueError("FULL_COMPILE_DEPENDENCY_COPY_CHANGED")

    def _compile(self, *, label, files, code_identity, plan_ref=None, response_ref=None):
        identity = self.verification_identity()
        if self._targets_path.read_bytes() != _capture_targets():
            raise ValueError("FULL_COMPILE_TARGETS_CHANGED")
        # A new worker may adopt the same immutable baseline. Physical folders
        # are independent; a directory listing never supplies execution state.
        phase_root = self.output_root / (label if label == "baseline" else f"{label}-{uuid4().hex[:12]}")
        phase_root.mkdir(parents=True, exist_ok=False)
        isolated_source = phase_root / "source"
        shutil.copytree(self.source_root, isolated_source, ignore=shutil.ignore_patterns(*_COPY_IGNORES))
        for relative, content in files.items():
            destination = _within(isolated_source, relative)
            if not destination.is_file() or destination.suffix != ".cs":
                raise ValueError("FULL_COMPILE_BOUND_CSHARP_FILE_REQUIRED")
            destination.write_bytes(content)
        expected = {row["path"]: row["sha256"] for row in self._source_identity}
        expected.update({path: hashlib.sha256(content).hexdigest() for path, content in files.items()})
        copied = {row["path"]: row["sha256"] for row in _source_snapshot(isolated_source)}
        if copied != expected:
            raise ValueError("FULL_COMPILE_SOURCE_COPY_MISMATCH")
        copied_ref = _save(phase_root / "source-inputs.json", copied)
        project = _within(isolated_source, self.project_relative_path)
        compile_inputs = phase_root / "compile-inputs.txt"
        profile = _create_nuget_isolated_build_profile(run_root=self.output_root,
            working_directory=project.parent, config_file=self.output_root / "nuget.config", bepinex_dir=None,
            timeout_seconds=self.timeout_seconds,
            game_folder_dir=Path(self._dependency["isolated_copy"]) if self._dependency is not None else None)
        extra = (f"-p:CustomBeforeMicrosoftCommonTargets={self._targets_path}",
                 f"-p:ControlledCompileInputsFile={compile_inputs}")
        profile = replace(profile, build_command=(*profile.build_command, *extra))
        build_profile = BuildProfile(profile_id=profile.profile_id, build_system="dotnet",
            working_directory=str(project.parent), command=profile.build_command,
            timeout_seconds=profile.timeout_seconds, expected_artifacts=(self.expected_artifact,))
        observed = {}
        interrupted = None
        def run(selected):
            if selected.command != profile.build_command:
                raise ValueError("FULL_COMPILE_PROFILE_CHANGED")
            execution = self._runner(profile)
            observed["execution"] = execution.to_dict()
            (phase_root / "stdout.txt").write_text(execution.stdout, encoding="utf-8")
            (phase_root / "stderr.txt").write_text(execution.stderr, encoding="utf-8")
            return BuildCommandResult(exit_code=execution.exit_code, stdout=execution.stdout,
                stderr=execution.stderr, duration_ms=execution.duration_ms)
        with trace_operation("validate.full_project_compilation", attributes={"version_role": label,
                "source_inputs_sha256": copied_ref["sha256"], "verification_scope": "isolated_compile_not_formal_build"}) as span:
            try:
                build = BuildAdapter().run_local(feature_id=plan_ref["feature_id"] if plan_ref else "baseline",
                    profile=build_profile, command_runner=run, allow_execution=True,
                    input_execution_mode="preapproval_isolated_compilation")
            except (OSError, subprocess.SubprocessError) as exc:
                build = None
                interrupted = {"exception_type": type(exc).__name__, "timeout_seconds": self.timeout_seconds,
                    "command": list(exc.cmd) if isinstance(getattr(exc, "cmd", None), (list, tuple)) else None}
                observed["execution"] = {"exit_code": None, "restore_exit_code": None,
                    "build_exit_code": None, "build_executed": None, "completed": False,
                    "exception": interrupted}
                for field in ("stdout", "stderr"):
                    value = getattr(exc, field, None) or b""
                    (phase_root / f"{field}.txt").write_bytes(value if isinstance(value, bytes) else value.encode("utf-8"))
            rows = _compile_input_rows(compile_inputs, isolated_source)
            actual_inputs = {row["path"]: row["sha256"] for row in rows}
            required = {path: digest for path, digest in copied.items() if path.endswith(".cs")}
            covered = bool(rows) and all(actual_inputs.get(path) == digest for path, digest in required.items())
            execution = observed["execution"]
            compiler_errors = (_source_compilation_errors(execution=execution,
                output="\n".join((phase_root / f"{field}.txt").read_text(encoding="utf-8", errors="replace")
                    for field in ("stdout", "stderr")),
                isolated_source=isolated_source, project_root=project.parent, source_inputs=copied)
                if build is not None else ())
            if interrupted is not None or execution["restore_exit_code"] != 0:
                status, owner = "environment_failed", "environment"
            elif build.claims_real_build_success and covered:
                status, owner = "passed", None
            elif execution["build_exit_code"] != 0:
                status = "compilation_failed" if compiler_errors else "environment_failed"
                owner = "patch_implementation" if compiler_errors else "environment"
            else:
                status, owner = "verification_incomplete", "validator"
            span.update(verification_status=status, compiled_input_count=len(rows), all_required_files_compiled=covered)
        if self.verification_identity() != identity:
            raise ValueError("FULL_COMPILE_VERIFIER_IDENTITY_CHANGED")
        if {row["path"]: row["sha256"] for row in _source_snapshot(isolated_source)} != expected:
            raise ValueError("FULL_COMPILE_ISOLATED_INPUT_CHANGED")
        self._validate_dependency_copy()
        record = {"status": status, "version_role": label, "execution_origin": "executed",
            "failure_owner": owner,
            "verification_scope": "full_project_compilation_not_behavior_or_formal_build_or_runtime",
            "verification_identity": identity, "source_inputs_ref": copied_ref,
            "isolated_source_root": str(isolated_source), "project_root": str(project.parent),
            "dependency_binding": self.dependency_binding.to_dict() if self.dependency_binding else None,
            "dependency_copy": self._dependency,
            "nuget_config_input_ref": self.nuget_config_ref, "measurement_targets_ref": _ref(self._targets_path),
            "build_profile": profile.to_dict(), "build_result": build.to_artifact_payload() if build is not None else None,
            "build_execution": observed["execution"], "compile_inputs": rows,
            "source_compilation_errors": list(compiler_errors),
            "compile_inputs_ref": _ref(compile_inputs) if compile_inputs.is_file() else None,
            "all_required_files_compiled": covered, "required_files": sorted(required), "changed_files": sorted(files),
            "materialized_code_identity": code_identity, "implementation_plan_ref": plan_ref,
            "model_response_ref": response_ref, "original_source_unchanged": True,
            "built_artifact_ref": _ref(project.parent / self.expected_artifact) if build is not None and build.claims_real_build_success else None,
            "stdout_ref": _ref(phase_root / "stdout.txt"), "stderr_ref": _ref(phase_root / "stderr.txt"),
            "product_apply_performed": False, "formal_build_stage_performed": False, "model_calls": 0}
        return {**record, "report_ref": _save(phase_root / "report.json", record)}

    def verify_baseline(self):
        self.verification_identity()
        if self._baseline is None:
            self._prepare()
            self._baseline = self._compile(label="baseline", files={}, code_identity=None)
        elif _ref(self._baseline["report_ref"]["path"]) != self._baseline["report_ref"]:
            raise ValueError("FULL_COMPILE_BASELINE_REPORT_CHANGED")
        return deepcopy(self._baseline)

    def __call__(self, context):
        baseline_preexisting = self._baseline is not None
        baseline = self.verify_baseline()
        # 为什么要有它：已定位的原源码错误是候选要修复的事实；允许编译候选不把失败baseline伪装成成功，也不绕过完整输入验证。
        source_failure = (baseline["status"] == "compilation_failed"
            and baseline["all_required_files_compiled"] is True
            and bool(baseline.get("source_compilation_errors")))
        if baseline["status"] != "passed" and not source_failure:
            return {"status": "environment_failed", "failure_owner": "environment",
                    "baseline": baseline, "changed_compilation_performed": False}
        ref = ArtifactRef(**context["implementation_plan_ref"])
        if ref.artifact_type != "implementation_plan":
            raise ValueError("FULL_COMPILE_PLAN_REFERENCE_REQUIRED")
        envelope = self.store.read(ref)
        plan = envelope["data"]
        if envelope["status"] != "success" or plan != context["implementation_plan"] or plan.get("blocking"):
            raise ValueError("FULL_COMPILE_PLAN_MISMATCH")
        changes = context["generated_changes"]
        if canonical_hash(changes) != context["generated_changes_sha256"]:
            raise ValueError("FULL_COMPILE_CHANGE_HASH_MISMATCH")
        response = context["model_response"]
        raw = Path(response["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != response["output_sha256"] or len(raw) != response["output_utf8_bytes"]:
            raise ValueError("FULL_COMPILE_RESPONSE_MISMATCH")
        submitted = json.loads(raw)["changes"]
        by_id = {row["edit_binding_id"]: row for row in submitted}
        if (len(by_id) != len(submitted) or len(changes) != len(submitted)
                or set(by_id) != {row["edit_binding_id"] for row in changes}):
            raise ValueError("FULL_COMPILE_RESPONSE_CHANGE_SET_MISMATCH")
        materialized = materialize_exact_text_patch(workspace_root=self.workspace_root, diff_intent=changes, implementation_plan=plan)
        identity = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256,
                    "files": sorted(materialized.files)}
        if identity != context["materialized_code_identity"]:
            raise ValueError("FULL_COMPILE_CODE_IDENTITY_MISMATCH")
        bindings = {row["binding_id"]: row for row in plan["binding_registry"]["edit_bindings"]}
        for row in changes:
            original = materialized.baseline_files[bindings[row["edit_binding_id"]]["canonical_target_path"]]
            after = row["patch"]["after_text"]
            raw_change = by_id[row["edit_binding_id"]]
            returned = raw_change["after_text"]
            # 为什么要有它：相同after可写在错误位置；raw局部前像必须与canonical补丁相同，省略则仍代表完整绑定。
            if "before_text" in raw_change:
                if (raw_change["before_text"] != row["patch"]["before_text"] or returned != after):
                    raise ValueError("FULL_COMPILE_MODEL_SELECTION_CHANGED")
            else:
                span = bindings[row["edit_binding_id"]]["target_span"]
                expected_before = b"".join(original.splitlines(keepends=True)[span["start_line"]-1:span["end_line"]]).decode("utf-8")
                if row["patch"]["before_text"] != expected_before:
                    raise ValueError("FULL_COMPILE_MODEL_SELECTION_CHANGED")
            if after != returned and not (
                original.startswith(codecs.BOM_UTF8) and after == "\ufeff" + returned
                or not original.startswith(codecs.BOM_UTF8) and returned == "\ufeff" + after
            ):
                raise ValueError("FULL_COMPILE_MODEL_CODE_CHANGED")
        self._calls += 1
        # Canonical Plan paths stay relative to the product workspace. Compile
        # only the explicitly selected project tree, not its changing journals.
        project_files = {}
        for relative, content in materialized.files.items():
            path = _within(self.workspace_root, relative)
            try:
                project_relative = path.relative_to(self.source_root).as_posix()
            except ValueError as exc:
                raise ValueError("FULL_COMPILE_CHANGE_OUTSIDE_SELECTED_PROJECT") from exc
            project_files[project_relative] = content
        changed = self._compile(label=f"version-{self._calls:03d}", files=project_files,
            code_identity=identity, plan_ref=context["implementation_plan_ref"],
            response_ref={"path": response["path"], "sha256": response["output_sha256"]})
        return {"status": changed["status"], "failure_owner": changed["failure_owner"],
                "baseline": baseline, "changed": changed, "changed_compilation_performed": True,
                "baseline_compilation_performed_in_this_call": not baseline_preexisting}
