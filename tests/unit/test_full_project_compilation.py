"""Whole-source admission and manifest checks; compiler responses here are fake."""
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.domain.full_project_compilation import FullProjectCompilationChecker, _ref
from src.mod_agent.local_entry import (
    NuGetIsolatedBuildExecution,
    RunLocalGameFolderBindingV1,
    _binary_tree_snapshot,
    _binary_tree_snapshot_sha256,
)
from tests.unit.test_crosshair_current_plan_matrix import _case


def _checker(tmp_path, monkeypatch, *, fail_baseline=False, baseline_failure=None,
             omit_baseline=False, omit_changed=False, changed_failure=None):
    inputs, context, _, _, _ = _case(tmp_path / "case", monkeypatch)
    project = inputs.behavior.parent / "SyntheticMod.csproj"
    project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net7.0</TargetFramework></PropertyGroup></Project>')
    props = inputs.behavior.parent / "GameFolder.props"
    props.write_text("<Project><PropertyGroup><GameFolder>unchanged</GameFolder></PropertyGroup></Project>")
    config = tmp_path / "nuget.config"
    config.write_text("<configuration><packageSources><clear /></packageSources></configuration>")
    dep = tmp_path / "dependencies"
    dep.mkdir()
    (dep / "dependency.dll").write_bytes(b"synthetic dependency, not executed")
    snapshot = _binary_tree_snapshot(dep)
    binding = RunLocalGameFolderBindingV1(source_root=str(dep), snapshot_sha256=_binary_tree_snapshot_sha256(snapshot), file_count=len(snapshot))
    calls = []
    def runner(profile):
        calls.append(profile)
        failure = (baseline_failure or ("compiler" if fail_baseline else None)
                   if len(calls) == 1 else changed_failure)
        failed = failure is not None
        if failure == "timeout":
            raise subprocess.TimeoutExpired(profile.build_command, 1)
        if failure == "process":
            raise FileNotFoundError("toolchain unavailable")
        if failure == "restore":
            return NuGetIsolatedBuildExecution(restore_exit_code=1, build_exit_code=None,
                restore_stdout="restore failed", restore_stderr="", build_stdout="", build_stderr="", duration_ms=1)
        manifest = next(value.split("=", 1)[1] for value in profile.build_command if value.startswith("-p:ControlledCompileInputsFile="))
        files = list(profile.working_directory.rglob("*.cs"))
        if omit_baseline and len(calls) == 1 or omit_changed and len(calls) > 1:
            files = [path for path in files if path.name != "Behavior.cs"]
        Path(manifest).write_text("\n".join(str(path) for path in files), encoding="utf-8")
        if not failed:
            dll = profile.working_directory / "bin/Debug/net7.0/SyntheticMod.dll"
            dll.parent.mkdir(parents=True)
            dll.write_bytes(b"synthetic compiler output")
        diagnostic = {
            "msbuild": "error MSB0001: build tools failed",
            "mixed": "Behavior.cs(1,1): error CS0246: missing type\nerror MSB0001: build tools failed",
            "unbound": "Missing.cs(1,1): error CS0246: missing type",
            "global_compiler": "CSC : error CS0006: Metadata file dependency.dll could not be found",
        }.get(failure, "Behavior.cs(1,1): error CS0246: missing type")
        return NuGetIsolatedBuildExecution(restore_exit_code=0, build_exit_code=1 if failed else 0,
            restore_stdout="restored", restore_stderr="", build_stdout=diagnostic if failed else "built",
            build_stderr="", duration_ms=1)
    checker = FullProjectCompilationChecker(source_root=inputs.workspace,
        project_relative_path=project.relative_to(inputs.workspace).as_posix(), artifact_store_root=inputs.store.root,
        dependency_binding=binding, nuget_config_ref=_ref(config), output_root=tmp_path / "checks",
        expected_artifact="bin/Debug/net7.0/SyntheticMod.dll", build_runner=runner)
    return inputs, context, checker, calls, props


def test_full_source_and_config_copies_compile_without_source_or_dependency_writes(tmp_path, monkeypatch):
    inputs, context, checker, calls, props = _checker(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in inputs.workspace.rglob("*") if path.is_file()}
    result = checker(context)
    assert result["status"] == "passed" and len(calls) == 2
    for phase in (result["baseline"], result["changed"]):
        assert phase["all_required_files_compiled"] is True
        assert len(phase["required_files"]) == 3
        assert any(row["path"].endswith("Configuration.cs") for row in phase["compile_inputs"])
        copied_props = Path(phase["isolated_source_root"]) / props.relative_to(inputs.workspace)
        assert copied_props.read_bytes() == props.read_bytes()
        assert _ref(phase["built_artifact_ref"]["path"]) == phase["built_artifact_ref"]
        assert phase["formal_build_stage_performed"] is False and phase["product_apply_performed"] is False
    assert {path: path.read_bytes() for path in before} == before
    assert result["changed"]["materialized_code_identity"] == context["materialized_code_identity"]


def test_source_error_baseline_allows_exact_candidate_and_keeps_failed_evidence(tmp_path, monkeypatch):
    inputs, context, checker, calls, _ = _checker(tmp_path, monkeypatch, fail_baseline=True)
    before = {path: path.read_bytes() for path in inputs.workspace.rglob("*") if path.is_file()}
    baseline = checker.verify_baseline()
    baseline_bytes = Path(baseline["report_ref"]["path"]).read_bytes()
    result = checker(context)
    assert result["status"] == "passed" and result["failure_owner"] is None
    assert result["changed_compilation_performed"] is True and len(calls) == 2
    assert result["baseline"]["status"] == "compilation_failed"
    assert result["baseline"]["build_result"]["claims_real_build_success"] is False
    assert result["baseline"]["built_artifact_ref"] is None
    assert Path(baseline["report_ref"]["path"]).read_bytes() == baseline_bytes
    assert json.loads(baseline_bytes)["status"] == "compilation_failed"
    assert result["changed"]["materialized_code_identity"] == context["materialized_code_identity"]
    assert result["changed"]["all_required_files_compiled"] is True
    assert result["changed"]["build_result"]["claims_real_build_success"] is True
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("failure", ["restore", "timeout", "process", "msbuild", "mixed", "unbound", "global_compiler"])
def test_baseline_environment_or_unbound_failure_stops_candidate_compilation(tmp_path, monkeypatch, failure):
    _, context, checker, calls, _ = _checker(tmp_path, monkeypatch, baseline_failure=failure)
    result = checker(context)
    assert result["status"] == "environment_failed" and result["failure_owner"] == "environment"
    assert result["changed_compilation_performed"] is False and len(calls) == 1


def test_source_error_without_complete_baseline_inputs_stops_candidate_compilation(tmp_path, monkeypatch):
    _, context, checker, calls, _ = _checker(tmp_path, monkeypatch, fail_baseline=True, omit_baseline=True)
    result = checker(context)
    assert result["status"] != "passed"
    assert result["changed_compilation_performed"] is False and len(calls) == 1
    assert result["baseline"]["all_required_files_compiled"] is False


def test_product_plan_root_is_separate_from_the_compiled_project_tree(tmp_path, monkeypatch):
    inputs, context, original, calls, _ = _checker(tmp_path, monkeypatch)
    project_root = inputs.behavior.parent
    checker = FullProjectCompilationChecker(
        source_root=project_root, workspace_root=inputs.workspace,
        project_relative_path=original.project.name, artifact_store_root=inputs.store.root,
        dependency_binding=original.dependency_binding, nuget_config_ref=original.nuget_config_ref,
        output_root=tmp_path / "product-checks", expected_artifact=original.expected_artifact,
        build_runner=original._runner,
    )
    before = checker.verification_identity()
    journal = inputs.workspace / "a" / "progress.json"
    journal.parent.mkdir(exist_ok=True)
    journal.write_text('{"stage":"patch"}')
    assert checker.verification_identity() == before
    result = checker(context)
    assert result["status"] == "passed" and len(calls) == 2
    assert result["changed"]["materialized_code_identity"] == context["materialized_code_identity"]
    assert all(not path.startswith("a/") for path in result["changed"]["required_files"])


@pytest.mark.parametrize("fail_baseline", [False, True])
def test_success_exit_and_dll_without_changed_file_in_compile_manifest_is_not_pass(tmp_path, monkeypatch, fail_baseline):
    _, context, checker, calls, _ = _checker(tmp_path, monkeypatch,
        fail_baseline=fail_baseline, omit_changed=True)
    result = checker(context)
    assert len(calls) == 2 and result["status"] == "verification_incomplete"
    assert result["failure_owner"] == "validator" and result["changed"]["all_required_files_compiled"] is False


@pytest.mark.parametrize("fail_baseline", [False, True])
@pytest.mark.parametrize("change", ["source", "context", "response", "code_identity"])
def test_current_identity_drift_is_not_compiled_as_model_output(tmp_path, monkeypatch, change, fail_baseline):
    inputs, original, checker, calls, _ = _checker(tmp_path, monkeypatch, fail_baseline=fail_baseline)
    context = deepcopy(original)
    checker.verify_baseline()
    if change == "source":
        inputs.behavior.write_text("changed original")
    elif change == "context":
        context["implementation_plan"]["blocking"] = True
    elif change == "response":
        context["model_response"]["output_sha256"] = "0" * 64
    else:
        context["materialized_code_identity"]["code_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        checker(context)
    assert len(calls) == 1


def test_existing_baseline_is_not_overwritten_or_recompiled_in_same_checker(tmp_path, monkeypatch):
    _, _, checker, calls, _ = _checker(tmp_path, monkeypatch)
    first = checker.verify_baseline()
    first["status"] = "tampered caller copy"
    second = checker.verify_baseline()
    assert second["status"] == "passed" and len(calls) == 1


@pytest.mark.parametrize("fail_baseline", [False, True])
@pytest.mark.parametrize("failure,owner", [("compiler", "patch_implementation"), ("restore", "environment"),
                                         ("timeout", "environment"), ("process", "environment"), ("msbuild", "environment")])
def test_later_environment_failure_does_not_become_a_request_to_edit_business_code(tmp_path, monkeypatch, failure, owner, fail_baseline):
    _, context, checker, calls, _ = _checker(tmp_path, monkeypatch,
        fail_baseline=fail_baseline, changed_failure=failure)
    result = checker(context)
    assert result["baseline"]["status"] == ("compilation_failed" if fail_baseline else "passed")
    assert result["failure_owner"] == owner
    assert result["changed"]["status"] != "passed" and len(calls) == 2
    if failure in ("timeout", "process"):
        assert result["changed"]["build_execution"]["exit_code"] is None


@pytest.mark.parametrize("fail_baseline", [False, True])
def test_existing_bound_baseline_can_be_adopted_without_a_second_baseline_build(tmp_path, monkeypatch, fail_baseline):
    inputs, context, original, calls, _ = _checker(tmp_path, monkeypatch, fail_baseline=fail_baseline)
    baseline = original.verify_baseline()
    historical_version = original.output_root / "version-001"
    historical_version.mkdir()
    marker = historical_version / "retained-report.json"
    marker.write_text("retain previous execution unchanged")
    checker = FullProjectCompilationChecker(source_root=inputs.workspace,
        project_relative_path=original.project_relative_path, artifact_store_root=inputs.store.root,
        dependency_binding=original.dependency_binding, nuget_config_ref=original.nuget_config_ref,
        output_root=original.output_root, expected_artifact=original.expected_artifact, build_runner=original._runner)
    checker.adopt_baseline(baseline["report_ref"])
    result = checker(context)
    assert len(calls) == 2 and result["status"] == "passed"
    assert result["baseline_compilation_performed_in_this_call"] is False
    assert result["changed"]["version_role"] == "version-001"
    assert Path(result["changed"]["isolated_source_root"]).parent != historical_version
    assert Path(result["changed"]["isolated_source_root"]).parent.name.startswith("version-001-")
    assert marker.read_text() == "retain previous execution unchanged"


@pytest.mark.parametrize("tamper", ["failure_claim", "compile_coverage"])
def test_failed_baseline_adoption_rechecks_original_errors_and_actual_inputs(tmp_path, monkeypatch, tamper):
    inputs, _, original, calls, _ = _checker(tmp_path, monkeypatch, fail_baseline=True)
    baseline = original.verify_baseline()
    report = json.loads(Path(baseline["report_ref"]["path"]).read_bytes())
    if tamper == "failure_claim":
        path = Path(report["stdout_ref"]["path"])
        path.write_text("error MSB0001: build tools failed", encoding="utf-8")
        report["stdout_ref"] = _ref(path)
    else:
        path = Path(report["compile_inputs_ref"]["path"])
        path.write_text("\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.endswith("Behavior.cs")), encoding="utf-8")
        report["compile_inputs_ref"] = _ref(path)
        report["compile_inputs"] = [row for row in report["compile_inputs"]
            if not row["path"].endswith("Behavior.cs")]
    forged = original.output_root / "altered-baseline.json"
    forged.write_text(json.dumps(report), encoding="utf-8")
    checker = FullProjectCompilationChecker(source_root=inputs.workspace,
        project_relative_path=original.project_relative_path, artifact_store_root=inputs.store.root,
        dependency_binding=original.dependency_binding, nuget_config_ref=original.nuget_config_ref,
        output_root=original.output_root, expected_artifact=original.expected_artifact, build_runner=original._runner)
    with pytest.raises(ValueError, match="FULL_COMPILE_BASELINE_REUSE_(FAILURE|INPUT)_MISMATCH"):
        checker.adopt_baseline(_ref(forged))
    assert len(calls) == 1 and checker._baseline is None


def test_verifier_identity_change_during_compilation_does_not_publish_a_pass(tmp_path, monkeypatch):
    _, _, checker, calls, _ = _checker(tmp_path, monkeypatch)
    original = checker.verification_identity
    def identity():
        value = original()
        if calls:
            value["validator_sha256"] = "0" * 64
        return value
    monkeypatch.setattr(checker, "verification_identity", identity)
    with pytest.raises(ValueError, match="FULL_COMPILE_VERIFIER_IDENTITY_CHANGED"):
        checker.verify_baseline()
    assert len(calls) == 1 and checker._baseline is None
