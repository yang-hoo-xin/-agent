"""No-external-dependency compilation and executable candidate file binding."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.domain import compiled_probe_evaluator as common
from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.domain.spread_api_evaluator import SpreadApiEvaluator
from src.mod_agent.model_qualification import read_bound_json
from tests.unit.test_full_project_compilation import _checker
from tests.unit.test_spread_api_evaluator import contract, observed


def _without_dependencies(tmp_path, monkeypatch):
    _, context, original, calls, _ = _checker(tmp_path, monkeypatch)
    feedback = make_compilation_feedback(compilation_kwargs={
        "source_root": original.source_root,
        "project_relative_path": original.project_relative_path,
        "artifact_store_root": original.store.root,
        "dependency_binding": None,
        "nuget_config_ref": original.nuget_config_ref,
        "output_root": original.output_root,
        "expected_artifact": original.expected_artifact,
        "build_runner": original._runner,
    }, output_root=tmp_path / "feedback")
    return context, feedback, calls


def test_no_dependency_baseline_and_candidate_and_adoption(tmp_path, monkeypatch):
    context, feedback, calls = _without_dependencies(tmp_path, monkeypatch)
    checker = feedback.checker
    game_identity = {"snapshot_sha256": "unused"}
    def forbidden(*args, **kwargs):
        raise AssertionError("A BCL-only compilation must not use a game dependency operation")
    monkeypatch.setattr("src.mod_agent.domain.full_project_compilation._validate_game_folder_build_binding", forbidden)
    monkeypatch.setattr("src.mod_agent.domain.full_project_compilation._materialize_game_folder_build_dependency", forbidden)
    result = checker(context)
    assert result["status"] == "passed" and len(calls) == 2
    for phase in (result["baseline"], result["changed"]):
        assert phase["dependency_binding"] is None and phase["dependency_copy"] is None
        assert "no_external_dependency" in phase["verification_identity"]["environment_identity_scope"]
        assert phase["build_profile"]["game_folder_dir"] is None
    assert all(not any("GameFolder=" in part for part in call.build_command) for call in calls)
    baseline = result["baseline"]
    checker._baseline = None
    assert checker.adopt_baseline(baseline["report_ref"])["status"] == "passed"
    assert len(calls) == 2
    # 为什么要有它：无游戏依赖的历史报告不能在恢复时接入另一棵复制树。
    checker._baseline = None
    forged = {key: value for key, value in baseline.items() if key != "report_ref"}
    forged["dependency_copy"] = game_identity
    with pytest.raises(ValueError, match="DEPENDENCY_COPY_UNEXPECTED"):
        checker.adopt_baseline(_save(tmp_path / "forged.json", forged))


@pytest.mark.parametrize("damage", [None, "sidecar_changed", "unbound_runtime"])
@pytest.mark.parametrize("phase", ["candidate", "formal"])
def test_cli_sidecars_and_runtime_are_bound_without_game_dependencies(tmp_path, monkeypatch, damage, phase):
    context, feedback, calls = _without_dependencies(tmp_path, monkeypatch)
    original_runner = feedback.checker._runner
    def runner(profile):
        result = original_runner(profile)
        assembly = profile.working_directory / feedback.checker.expected_artifact
        for suffix in (".deps.json", ".runtimeconfig.json"):
            assembly.with_suffix(suffix).write_text("{}", encoding="utf-8")
        return result
    feedback.checker._runner = runner
    class ExecutableProtocol(SpreadApiEvaluator):
        def assembly_file_refs(self, assembly):
            path = Path(assembly["path"])
            return [assembly, _ref(path.with_suffix(".deps.json")), _ref(path.with_suffix(".runtimeconfig.json"))]
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in ("spread_api_probe.dll", "spread_api_probe.deps.json", "spread_api_probe.runtimeconfig.json", "System.Runtime.dll", "dotnet.exe"):
        (probe / name).write_bytes(b"synthetic " + name.encode())
    config = _save(tmp_path / "probe.json", {"assembly_path": str(probe / "spread_api_probe.dll"),
        "files": [_ref(path) for path in probe.iterdir()], "dotnet": _ref(probe / "dotnet.exe")})
    evaluator = ExecutableProtocol(compilation=feedback, output_root=tmp_path / "behavior",
        probe_configuration_ref=config, case_configuration_ref=_save(tmp_path / "cases.json", contract()))
    requests = []
    def run(command, **kwargs):
        request = read_bound_json(_ref(command[-1]))
        requests.append(request)
        assert request["dependencies"] == [] and len(request["assembly_files"]) == 3
        case = next(row for row in evaluator.cases if row[0] == Path(command[-1]).parent.name)
        output = observed(case)
        output["assembly_sha256"] = request["assembly"]["sha256"]
        runtime = _ref(probe / "System.Runtime.dll")
        if damage == "unbound_runtime":
            runtime["sha256"] = "0" * 64
        output["loaded_dependencies"] = [{**runtime, "name": "System.Runtime"}]
        if damage == "sidecar_changed":
            Path(request["assembly_files"][1]["path"]).write_text('{"changed":true}', encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=json.dumps(output), stderr="")
    monkeypatch.setattr(common.subprocess, "run", run)
    if phase == "formal":
        compiled = feedback(context)["validation_results"]["full_compilation"]["changed"]
        def invoke():
            return evaluator.verify_existing_assembly(assembly_ref=compiled["built_artifact_ref"])
    else:
        def invoke():
            return evaluator(context)
    if damage:
        expected = "VALIDATION_INPUT_CHANGED" if damage == "sidecar_changed" else "LOADED_DEPENDENCY_UNBOUND"
        with pytest.raises(ValueError, match=expected):
            invoke()
    else:
        report = invoke()
        assert report["status"] == "passed" and len(calls) == 2 and len(requests) == 9
        if phase == "candidate":
            details = read_bound_json(report["verification_ref"])
            assert details["assembly_files"] == requests[0]["assembly_files"]
        else:
            assert report["compilation_performed"] is False


@pytest.mark.parametrize("declared_dependency,hash_value", [(object(), None), (None, "unexpected")])
def test_formal_no_dependency_cannot_omit_declared_binding(tmp_path, monkeypatch, declared_dependency, hash_value):
    evaluator = common.CompiledProbeEvaluator.__new__(common.CompiledProbeEvaluator)
    evaluator.compilation = SimpleNamespace(checker=SimpleNamespace(dependency_binding=declared_dependency))
    monkeypatch.setattr(evaluator, "verification_identity", lambda: {})
    assembly = tmp_path / "bound.dll"
    assembly.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="FORMAL_DEPENDENCY_REQUIRED"):
        evaluator.verify_existing_assembly(assembly_ref=_ref(assembly), expected_dependency_snapshot_sha256=hash_value)
