"""S5 factory contract; compiler/probe execution is synthetic in these tests."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from src.mod_agent.domain import compiled_probe_evaluator as shared
from src.mod_agent.domain import live_panel_reload_evaluator as module
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import read_bound_json


TASK = Path(__file__).resolve().parents[2] / "artifacts/eval_driven_20261005/benchmark10/S5"
PACKAGE = TASK / "public/checker-v1"


def observed(case, assembly, dependency, *, broken=True):
    original = json.loads((TASK / "host/baseline-result-v2.json").read_bytes())
    selected = [row for row in original["checks"] if row["check_id"].startswith(case["id"] + ".")]
    result = deepcopy(selected[0]["observed"])
    result["actions"] = [deepcopy(next(row["observed"] for row in selected
                         if row["check_id"] == case["id"] + ".action_" + str(index) + ".expected_behavior"))
                         for index in range(len(case["actions"]))]
    result["assembly_sha256"] = assembly["sha256"]
    result["loaded_dependencies"] = [dependency]
    if not broken:
        for action, actual in zip(case["actions"], result["actions"]):
            actual["final"].update(action.get("expected", {}))
    return result


def setup(tmp_path, monkeypatch, *, broken=True, damage=None):
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in ("s5_config_probe.dll", "s5_config_probe.deps.json", "s5_config_probe.runtimeconfig.json", "dotnet.exe"):
        (probe / name).write_text("synthetic " + name)
    cases = tmp_path / "cases.json"
    cases.write_bytes((PACKAGE / "cases.json").read_bytes())
    assessor = tmp_path / "assess.py"
    assessor.write_bytes((PACKAGE / "assess.py").read_bytes())
    config = {"assembly_path": str(probe / "s5_config_probe.dll"),
        "files": [_ref(path) for path in sorted(probe.iterdir()) if path.name != "dotnet.exe"],
        "dotnet": _ref(probe / "dotnet.exe"), "timeout_seconds": 45}
    source = tmp_path / "source"
    source.mkdir()
    assembly = source / "LivePanel.dll"
    assembly.write_bytes(b"synthetic nonexecutable")
    response = tmp_path / "response.txt"
    response.write_text("synthetic non-model response")
    response_ref = _ref(response)
    context = {"model_response": {"path": str(response), "output_sha256": response_ref["sha256"]},
        "generated_changes": [{"edit_binding_id": "controller"}], "generated_changes_sha256": "changes",
        "source_snapshot_sha256": "source", "materialized_code_identity": {"code_sha256": "candidate"},
        "implementation_plan_ref": {"path": "synthetic-plan", "artifact_hash": "plan"},
        "implementation_plan": {"binding_registry": {"edit_bindings": [
            {"binding_id": "controller", "canonical_target_path": "LivePanelController.cs"}]}}}
    compiled = {"status": "passed", "execution_origin": "executed", "all_required_files_compiled": True,
        "model_response_ref": response_ref, "materialized_code_identity": context["materialized_code_identity"],
        "implementation_plan_ref": context["implementation_plan_ref"], "built_artifact_ref": _ref(assembly),
        "dependency_binding": None, "dependency_copy": None}
    compiled["report_ref"] = _save(tmp_path / "compiled.json", deepcopy(compiled))
    feedback = {"status": "passed", "validation_results": {"full_compilation": {"changed": compiled}}}
    feedback["report_ref"] = _save(tmp_path / "compilation-feedback.json", deepcopy(feedback))
    calls, requests = [], []
    class Compilation:
        checker = SimpleNamespace(workspace_root=source, source_root=source)
        def verification_identity(self):
            return {"validator_sha256": "compiler", "inputs_sha256": "inputs", "environment_sha256": "environment"}
        def __call__(self, incoming):
            calls.append(incoming)
            return deepcopy(feedback)
    evaluator = module.LivePanelReloadEvaluator(compilation=Compilation(), output_root=tmp_path / "verification",
        probe_configuration_ref=_save(tmp_path / "probe.json", config), case_configuration_ref=_ref(cases), assessor_ref=_ref(assessor))
    def run(command, **kwargs):
        request = read_bound_json(_ref(command[-1]))
        requests.append(request)
        case = next(case for _, case in evaluator.cases if case["id"] == Path(command[-1]).parent.name)
        assert request["seed_config"] == case["seed_config"] and request["actions"] == case["actions"]
        result = observed(case, request["assembly"], config["files"][0], broken=broken)
        if damage == "timeout":
            raise subprocess.TimeoutExpired(command, 45, output=b"partial", stderr=b"diagnostic")
        if damage in {"production_frame_relay", "external_file_operation"}:
            return SimpleNamespace(returncode=2, stdout=json.dumps({"status": "execution_failed", "execution_phase": damage, "message": "retained exception"}), stderr="")
        if damage == "unbound_dependency":
            result["loaded_dependencies"][0] = {"path": str(tmp_path / "unexpected.dll"), "sha256": "bad"}
        if damage == "assembly_drift":
            assembly.write_bytes(b"changed after loading")
        if damage == "probe_calls_reload":
            result["probe_calls_reload"] = True
        if damage == "background_surface_write":
            result["actions"][0]["calls"] = [{"width": 96, "thread": result["owner_thread"] + 1}]
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")
    monkeypatch.setattr(shared.subprocess, "run", run)
    return evaluator, context, requests, calls


def test_all_51_original_assertions_and_eight_failures_reach_patch_feedback(tmp_path, monkeypatch):
    evaluator, context, requests, _ = setup(tmp_path, monkeypatch)
    report = evaluator(context)
    assert report["status"] == "behavior_failed" and report["failure_owner"] == "patch_implementation"
    assert report["owner_binding_ids"] == ["controller"]
    assert report["verification_summary"] == {"checks": 51, "failed_checks": 8, "executions": 3}
    original = json.loads((TASK / "host/baseline-result-v2.json").read_bytes())
    details = read_bound_json(report["verification_ref"])
    assert [(row["check_id"], row["passed"]) for row in details["checks"]] == [(row["check_id"], row["passed"]) for row in original["checks"]]
    assert len({request["sandbox_root"] for request in requests}) == 3
    assert report["model_response_sha256"] == context["model_response"]["output_sha256"]
    assert report["validation_results"]["runtime"] == {"status": "not_executed"}
    for row in report["observations"]:
        prior = next(item for item in original["checks"] if item["check_id"] == row["check_id"])
        assert row["observed"] == prior["observed"]


def test_synthetic_positive_stays_controlled_scope(tmp_path, monkeypatch):
    evaluator, context, _, _ = setup(tmp_path, monkeypatch, broken=False)
    report = evaluator(context)
    assert report["status"] == "passed" and report["verification_summary"]["checks"] == 51
    assert "not_Unity_Update_GUI_or_game_runtime" in report["verification_scope"]


@pytest.mark.parametrize("damage,status", [("timeout", "infrastructure_failed"), ("external_file_operation", "infrastructure_failed"), ("production_frame_relay", "behavior_failed")])
def test_exception_ownership_and_original_outputs(tmp_path, monkeypatch, damage, status):
    evaluator, context, requests, _ = setup(tmp_path, monkeypatch, damage=damage)
    report = evaluator(context)
    assert report["status"] == status and len(requests) == 1
    raw = read_bound_json(read_bound_json(report["verification_ref"])["execution_refs"][0])
    assert raw["stderr"] == "diagnostic" if damage == "timeout" else "retained exception" in raw["stdout"]


@pytest.mark.parametrize("damage", ["unbound_dependency", "assembly_drift"])
def test_execution_identity_drift_rejected(tmp_path, monkeypatch, damage):
    evaluator, context, _, _ = setup(tmp_path, monkeypatch, damage=damage)
    with pytest.raises(ValueError):
        evaluator(context)


@pytest.mark.parametrize("damage", ["probe_calls_reload", "background_surface_write"])
def test_false_reload_proof_and_offthread_surface_are_not_accepted(tmp_path, monkeypatch, damage):
    evaluator, context, _, _ = setup(tmp_path, monkeypatch, broken=False, damage=damage)
    report = evaluator(context)
    assert report["status"] == "behavior_failed"


@pytest.mark.parametrize("kind", ["cases", "assessor", "probe"])
def test_frozen_contract_drift_fails_before_compilation(tmp_path, monkeypatch, kind):
    evaluator, context, requests, calls = setup(tmp_path, monkeypatch)
    ref = evaluator.case_configuration_ref if kind == "cases" else evaluator.assessor_ref if kind == "assessor" else evaluator.configuration["files"][0]
    Path(ref["path"]).write_text("changed")
    with pytest.raises(ValueError):
        evaluator(context)
    assert not requests and not calls


@pytest.mark.parametrize("path", ["FrameIntegration.cs", "SurfaceIntegration.cs", "Dependencies.props", "../escape.cs"])
def test_public_allowed_paths_reject_boundary_changes_before_compile(tmp_path, monkeypatch, path):
    evaluator, context, requests, calls = setup(tmp_path, monkeypatch)
    context["implementation_plan"]["binding_registry"]["edit_bindings"][0]["canonical_target_path"] = path
    with pytest.raises(ValueError, match="CHANGE_OUTSIDE_PUBLIC_SCOPE"):
        evaluator(context)
    assert not requests and not calls
