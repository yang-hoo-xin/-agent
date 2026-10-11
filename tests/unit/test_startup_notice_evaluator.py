"""Integrated acceptance plumbing; compiler/probe processes are synthetic here."""
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.domain import startup_notice_evaluator as module
from src.mod_agent.domain.compilation_feedback import CompilationFeedback
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import read_bound_json
from tests.unit.test_full_project_compilation import _checker
from tests.unit.test_startup_notice_verification import observed


def setup(tmp_path, monkeypatch, *, suppress=True, damage=None, **checker_kwargs):
    inputs, context, checker, builds, _ = _checker(tmp_path, monkeypatch, **checker_kwargs)
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in ("bepinex_plugin_probe.dll", "bepinex_plugin_probe.deps.json", "bepinex_plugin_probe.runtimeconfig.json", "dotnet.exe"):
        (probe / name).write_text("synthetic " + name)
    config = {"assembly_path": str(probe / "bepinex_plugin_probe.dll"),
        "files": [_ref(path) for path in sorted(probe.iterdir()) if path.name != "dotnet.exe"], "dotnet": _ref(probe / "dotnet.exe")}
    runtime = tmp_path / "runtime" / "netstandard.dll"
    runtime.parent.mkdir()
    runtime.write_bytes(b"synthetic framework runtime")
    if damage in {"bound_runtime", "changed_runtime"}:
        config["files"].append(_ref(runtime))
    config_ref = _save(tmp_path / "probe.json", config)
    compilation = CompilationFeedback(checker, tmp_path / "compile-feedback")
    evaluator = module.StartupNoticeEvaluator(compilation=compilation, output_root=tmp_path / "behavior",
        probe_configuration_ref=config_ref, suppress_blank_messages=suppress)
    calls = []

    def run(command, **kwargs):
        request = read_bound_json(_ref(command[-1]))
        calls.append(request)
        name = Path(command[-1]).parent.name
        case = next(row for row in evaluator.cases if row[0] == name)
        value = observed(case[1], case[2])
        value["assembly_sha256"] = request["assembly"]["sha256"]
        value["loaded_dependencies"] = [{**ref, "name": Path(ref["path"]).stem} for ref in request["dependencies"]]
        if damage in {"bound_runtime", "unbound_runtime", "changed_runtime"}:
            value["loaded_dependencies"].append({**_ref(runtime), "name": "netstandard"})
            if damage == "changed_runtime":
                runtime.write_bytes(b"changed after loading")
        if suppress and not case[2].strip():
            value["logs"] = []
        if damage == "missing":
            value["logs"] = []
        elif damage == "double":
            value["logs"] *= 2
        elif damage == "blank_log" and not case[2]:
            value["logs"] = [{"level": "Info", "message": ""}]
        elif damage == "defaults":
            value["entries"][1]["default_value"] = "different"
        elif damage == "candidate_drift":
            Path(request["assembly"]["path"]).write_bytes(b"drift")
        elif damage == "dependency_drift":
            Path(request["dependencies"][0]["path"]).write_bytes(b"drift")
        elif damage == "observed_assembly":
            value["assembly_sha256"] = "bad"
        elif damage == "observed_dependency":
            value["loaded_dependencies"][0]["sha256"] = "bad"
        elif damage == "plugin_exception":
            return SimpleNamespace(returncode=2, stdout=json.dumps({"status": "execution_failed", "execution_phase": "plugin_load",
                "error_type": "System.Exception", "message": "actual plugin failure"}), stderr="retained stderr")
        elif damage == "timeout":
            raise subprocess.TimeoutExpired(command, 20, output=b"partial stdout", stderr=b"partial stderr")
        elif damage == "malformed":
            return SimpleNamespace(returncode=0, stdout="not json", stderr="retained stderr")
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    return evaluator, context, calls, builds, inputs, config


@pytest.mark.parametrize("suppress,count", [(False, 3), (True, 5)])
def test_full_candidate_checks_and_delegation_contract(tmp_path, monkeypatch, suppress, count):
    evaluator, context, calls, builds, _, _ = setup(tmp_path, monkeypatch, suppress=suppress)
    report = evaluator(context)
    details = read_bound_json(report["verification_ref"])
    assert report["status"] == "passed" and report["failure_owner"] is None
    assert len(calls) == count and len(builds) == 2
    assert report["verification_summary"] == {"checks": count * 3, "failed_checks": 0, "executions": count}
    assert report["model_response_sha256"] == context["model_response"]["output_sha256"]
    assert details["compilation_report_ref"] == report["validation_results"]["full_compilation"]["report_ref"]
    assert all(row["passed"] for row in details["checks"])
    assert report["validation_results"]["runtime"]["status"] == "not_executed"
    assert len({row["sandbox_root"] for row in calls}) == count
    from src.mod_agent.execution.task_delegation import _verification
    _verification(report["report_ref"], [row["check_id"] for row in details["checks"]],
        request=SimpleNamespace(isolated_workspace_root=str(tmp_path)), plan_ref=context["implementation_plan_ref"],
        code_identity=context["materialized_code_identity"],
        proposal={"diff_intent": [{"generation": {"model_response_sha256": report["model_response_sha256"]}}]})


def test_logging_feedback_preserves_failure_facts_and_raw_execution(tmp_path, monkeypatch):
    evaluator, context, _, _, _, _ = setup(tmp_path, monkeypatch, suppress=False, damage="missing")
    report = evaluator(context)
    assert report["verification_summary"] == {"checks": 9, "failed_checks": 2, "executions": 3}
    for observation in report["observations"]:
        raw = json.loads(read_bound_json(observation["input"]["execution_ref"])["stdout"])
        selected = observation["observed"]
        assert observation["check_id"].endswith(".logging")
        assert selected["logs"] == raw["logs"] == []
        assert selected["entries"] == raw["entries"]
        assert selected["plugin_load_calls"] == 1
        assert selected["plugin_instance_constructor_skipped"] is True
        assert selected["injected_base_properties"] == raw["injected_base_properties"]
        assert selected["assembly_sha256"] == raw["assembly_sha256"]
        assert selected["log_capture"] == raw["log_capture"]
        assert observation["expected"]["logs"]
        assert "loaded_dependencies" not in selected and raw["loaded_dependencies"]
        case = next(case for case in evaluator.cases if case[0] == observation["check_id"].split(".")[0])
        assert observation["expected"] == evaluator.expected(case)
        assert evaluator.assess(raw, case, raw["assembly_sha256"])["logging"] is False


@pytest.mark.parametrize("damage", ["missing", "double", "blank_log", "defaults"])
def test_behavior_failure_has_actual_observation_and_stable_projection(tmp_path, monkeypatch, damage):
    evaluator, context, _, _, _, _ = setup(tmp_path, monkeypatch, damage=damage)
    first = evaluator(context)
    original = Path(first["report_ref"]["path"]).read_bytes()
    second = evaluator(context)
    assert first["status"] == second["status"] == "behavior_failed"
    assert first["owner_binding_ids"] == [row["edit_binding_id"] for row in context["generated_changes"]]
    assert first["observations"] and first["observations"][0]["observed"]["entries"]
    assert first["failure_state_observations"] == second["failure_state_observations"]
    assert first["report_ref"] != second["report_ref"]
    assert Path(first["report_ref"]["path"]).read_bytes() == original


@pytest.mark.parametrize("damage", ["candidate_drift", "dependency_drift", "observed_assembly", "observed_dependency"])
def test_changed_execution_bindings_rejected(tmp_path, monkeypatch, damage):
    evaluator, context, _, _, _, _ = setup(tmp_path, monkeypatch, damage=damage)
    with pytest.raises(ValueError, match="STARTUP_NOTICE_"):
        evaluator(context)


@pytest.mark.parametrize("damage", ["bound_runtime", "unbound_runtime", "changed_runtime"])
def test_framework_runtime_requires_explicit_bound_file_and_actual_hash(tmp_path, monkeypatch, damage):
    evaluator, context, _, _, _, _ = setup(tmp_path, monkeypatch, damage=damage)
    if damage == "bound_runtime":
        assert evaluator(context)["status"] == "passed"
    else:
        with pytest.raises(ValueError, match="STARTUP_NOTICE_LOADED_DEPENDENCY_UNBOUND"):
            evaluator(context)


@pytest.mark.parametrize("target", ["dotnet", "probe", "config"])
def test_probe_identity_drift_before_compilation(tmp_path, monkeypatch, target):
    evaluator, context, calls, builds, _, config = setup(tmp_path, monkeypatch)
    path = config["dotnet"]["path"] if target == "dotnet" else config["files"][0]["path"] if target == "probe" else evaluator.probe_configuration_ref["path"]
    Path(path).write_text("changed")
    with pytest.raises(ValueError):
        evaluator(context)
    assert not calls and not builds


@pytest.mark.parametrize("damage,status", [("plugin_exception", "behavior_failed"), ("timeout", "infrastructure_failed"), ("malformed", "infrastructure_failed")])
def test_execution_failure_preserves_output(tmp_path, monkeypatch, damage, status):
    evaluator, context, calls, _, _, _ = setup(tmp_path, monkeypatch, damage=damage)
    report = evaluator(context)
    assert report["status"] == status and len(calls) == 1
    details = read_bound_json(report["verification_ref"])
    raw = read_bound_json(details["execution_refs"][0])
    assert raw["stderr"]
    if damage == "plugin_exception":
        assert report["observations"][0]["observed"]["message"] == "actual plugin failure"
    elif damage == "timeout":
        assert raw["stdout"] == "partial stdout" and raw["error_type"] == "TimeoutExpired"


@pytest.mark.parametrize("failure,status", [("compiler", "behavior_failed"), ("restore", "infrastructure_failed")])
def test_compilation_failure_bypasses_probe_and_retains_feedback(tmp_path, monkeypatch, failure, status):
    evaluator, context, calls, _, _, _ = setup(tmp_path, monkeypatch, changed_failure=failure)
    report = evaluator(context)
    original = read_bound_json(report["compilation_feedback_ref"])
    assert report["status"] == status and not calls
    assert report["observations"] == original["observations"]
    if failure == "compiler":
        assert report["failure_state_observations"] == original["failure_state_observations"]
        assert report["observations"][0]["observed"]["diagnostics"][0]["code"] == "CS0246"


def test_cs1061_dependency_documentation_is_preserved(tmp_path, monkeypatch):
    evaluator, context, calls, _, _, _ = setup(tmp_path, monkeypatch)
    checker = evaluator.compilation.checker
    original = checker._runner

    def runner(profile):
        from dataclasses import replace
        execution = original(profile)
        return replace(execution, build_exit_code=1,
            build_stdout="Behavior.cs(1,1): error CS1061: Missing member")

    checker._runner = runner
    documentation = {"members": [{"name": "ManualLogSource.LogInfo", "summary": "actual dependency documentation"}]}
    from src.mod_agent.proposal import dependency_documentation
    monkeypatch.setattr(dependency_documentation, "prepare_dependency_documentation",
        lambda **kwargs: SimpleNamespace(validate=lambda: None, model_view=lambda: deepcopy(documentation)))
    report = evaluator(context)
    assert report["status"] == "behavior_failed" and not calls
    assert report["observations"][0]["observed"]["dependency_documentation"] == documentation
    assert report["failure_state_observations"][0]["observed"]["dependency_documentation"] == documentation
