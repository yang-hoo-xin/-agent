"""S4 wrapper contract; compiler and probe execution are synthetic in this file."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from src.mod_agent.domain import compiled_probe_evaluator as shared
from src.mod_agent.domain import disabled_warning_evaluator as module
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import read_bound_json


PACKAGE = Path(__file__).resolve().parents[2] / "artifacts/eval_driven_20261004/benchmark10/S4/public/checker-v1"


def observed(case, assembly, dependency, *, broken=True):
    actions = []
    for index, action in enumerate(case["actions"]):
        row = {"index": index, "kind": action["kind"]}
        if action["kind"] == "ticks":
            enabled, available = action["enabled"], action["available"]
            row.update(ticks=action["count"], enabled=enabled, camera_available=available,
                after_fov=action["expected_fov"],
                logs=[{"level": "Warning", "message": "camera unavailable"}] if not available and (enabled or broken) else [],
                camera_writes=[action["expected_fov"]] if enabled and available else [])
        actions.append(row)
    return {"status": "observed", "assembly_sha256": assembly["sha256"],
        "plugin_constructor_executed": True, "plugin_load_calls": 1, "configuration_origin": "BasePlugin_constructor",
        "production_tick_relay_executed": True, "camera_port_substituted": True,
        "tick_relay_registration_count": 1, "log_capture": "real_bepinex_global_listener",
        "plugin_identity": {"guid": "benchmark.gtfo.fovcompanion", "name": "FOV Companion", "version": "0.8.0"},
        "entries": [{"section": "CameraAssist", "key": "Enabled", "default_value": True, "value_type": "System.Boolean"},
                    {"section": "CameraAssist", "key": "FieldOfView", "default_value": 85, "value_type": "System.Single"}],
        "saved_config": "[Other]\nKeep = unchanged\n", "actions": actions,
        "startup_logs": [{"level": "Info", "message": "FOV Companion loaded"}],
        "loaded_dependencies": [dependency]}


def setup(tmp_path, monkeypatch, *, broken=True, damage=None):
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in ("s4_camera_probe.dll", "s4_camera_probe.deps.json", "s4_camera_probe.runtimeconfig.json", "dotnet.exe"):
        (probe / name).write_text("synthetic: " + name)
    cases = tmp_path / "cases.json"
    cases.write_bytes((PACKAGE / "cases.json").read_bytes())
    assessor = tmp_path / "assess.py"
    assessor.write_bytes((PACKAGE / "assess.py").read_bytes())
    config = {"assembly_path": str(probe / "s4_camera_probe.dll"),
        "files": [_ref(path) for path in sorted(probe.iterdir()) if path.name != "dotnet.exe"],
        "dotnet": _ref(probe / "dotnet.exe"), "timeout_seconds": 20}
    source = tmp_path / "source"
    source.mkdir()
    assembly = source / "FovCompanion.dll"
    assembly.write_bytes(b"synthetic not executable")
    response = tmp_path / "response.txt"
    response.write_text("synthetic not model generation")
    response_ref = _ref(response)
    context = {"model_response": {"path": str(response), "output_sha256": response_ref["sha256"]},
        "generated_changes": [{"edit_binding_id": "controller"}], "generated_changes_sha256": "changes",
        "source_snapshot_sha256": "source", "materialized_code_identity": {"code_sha256": "candidate"},
        "implementation_plan_ref": {"path": "synthetic-plan", "artifact_hash": "plan"},
        "implementation_plan": {"binding_registry": {"edit_bindings": [
            {"binding_id": "controller", "canonical_target_path": "FovController.cs"}]}}}
    compiled = {"status": "passed", "execution_origin": "executed", "all_required_files_compiled": True,
        "model_response_ref": response_ref, "materialized_code_identity": context["materialized_code_identity"],
        "implementation_plan_ref": context["implementation_plan_ref"], "built_artifact_ref": _ref(assembly),
        "dependency_binding": None, "dependency_copy": None}
    compiled["report_ref"] = _save(tmp_path / "compiled.json", deepcopy(compiled))
    feedback = {"status": "passed", "validation_results": {"full_compilation": {"changed": compiled}}}
    feedback["report_ref"] = _save(tmp_path / "compilation-feedback.json", deepcopy(feedback))
    compilations, requests = [], []
    class Compilation:
        checker = SimpleNamespace(workspace_root=source, source_root=source)
        def verification_identity(self):
            return {"validator_sha256": "compiler", "inputs_sha256": "inputs", "environment_sha256": "environment"}
        def __call__(self, incoming):
            compilations.append(incoming)
            return deepcopy(feedback)
    evaluator = module.DisabledWarningEvaluator(compilation=Compilation(), output_root=tmp_path / "verification",
        probe_configuration_ref=_save(tmp_path / "probe.json", config), case_configuration_ref=_ref(cases), assessor_ref=_ref(assessor))
    def run(command, **kwargs):
        request = read_bound_json(_ref(command[-1]))
        requests.append(request)
        case = next(case for _, case in evaluator.cases if case["id"] == Path(command[-1]).parent.name)
        assert request["seed_config"] == case["seed_config"] and request["actions"] == case["actions"]
        result = observed(case, request["assembly"], config["files"][0], broken=broken)
        if damage == "timeout":
            raise subprocess.TimeoutExpired(command, 20, output=b"partial", stderr=b"diagnostic")
        if damage == "plugin_exception":
            return SimpleNamespace(returncode=2, stdout=json.dumps({"status": "execution_failed", "execution_phase": "controlled_tick", "message": "candidate exception"}), stderr="")
        if damage == "unbound_dependency":
            result["loaded_dependencies"][0] = {"path": str(tmp_path / "unexpected.dll"), "sha256": "bad"}
        if damage == "duplicate_registration":
            result["tick_relay_registration_count"] = 2
        if damage == "disabled_write":
            for action in result["actions"]:
                if action["kind"] == "ticks" and not action["enabled"]:
                    action["camera_writes"] = [85]
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")
    monkeypatch.setattr(shared.subprocess, "run", run)
    return evaluator, context, requests, compilations


def test_all_69_frozen_assertions_and_original_four_failures_reach_patch_feedback(tmp_path, monkeypatch):
    evaluator, context, requests, _ = setup(tmp_path, monkeypatch)
    report = evaluator(context)
    assert report["status"] == "behavior_failed" and report["failure_owner"] == "patch_implementation"
    assert report["owner_binding_ids"] == ["controller"]
    assert report["verification_summary"] == {"checks": 69, "failed_checks": 4, "executions": 6}
    assert [row["check_id"] for row in report["observations"]] == [
        "disabled_missing.ticks_1.logs", "live_toggle.ticks_4.logs", "live_toggle.ticks_13.logs", "disabled_burst.ticks_1.logs"]
    assert len({request["sandbox_root"] for request in requests}) == 6
    assert report["model_response_sha256"] == context["model_response"]["output_sha256"]
    assert report["generated_changes_sha256"] == context["generated_changes_sha256"]
    assert report["validation_results"]["runtime"] == {"status": "not_executed"}
    for item in report["observations"]:
        assert item["observed"]["logs"] and item["observed"]["enabled"] is False
    assert "def assess" not in json.dumps(report)
    old = Path(report["report_ref"]["path"]).read_bytes()
    second = evaluator(context)
    assert second["failure_state_observations"] == report["failure_state_observations"]
    assert Path(report["report_ref"]["path"]).read_bytes() == old


def test_positive_keeps_all_checks_and_does_not_claim_game_runtime(tmp_path, monkeypatch):
    evaluator, context, _, _ = setup(tmp_path, monkeypatch, broken=False)
    report = evaluator(context)
    assert report["status"] == "passed" and report["failure_owner"] is None
    assert report["verification_summary"] == {"checks": 69, "failed_checks": 0, "executions": 6}
    assert report["validation_results"]["runtime"]["status"] == "not_executed"


@pytest.mark.parametrize("damage,failed", [("duplicate_registration", "execution_binding"), ("disabled_write", "camera_effect")])
def test_preserved_entry_and_disabled_side_effect_are_still_asserted(tmp_path, monkeypatch, damage, failed):
    evaluator, context, _, _ = setup(tmp_path, monkeypatch, broken=False, damage=damage)
    report = evaluator(context)
    assert report["status"] == "behavior_failed"
    assert any(row["check_id"].endswith(failed) for row in report["observations"])


@pytest.mark.parametrize("damage,status", [("timeout", "infrastructure_failed"), ("plugin_exception", "behavior_failed")])
def test_execution_faults_retain_raw_evidence_and_correct_owner(tmp_path, monkeypatch, damage, status):
    evaluator, context, requests, _ = setup(tmp_path, monkeypatch, damage=damage)
    report = evaluator(context)
    assert report["status"] == status and len(requests) == 1
    details = read_bound_json(report["verification_ref"])
    raw = read_bound_json(details["execution_refs"][0])
    assert raw["stdout"]


def test_unbound_loaded_dependency_never_becomes_behavior_success(tmp_path, monkeypatch):
    evaluator, context, _, _ = setup(tmp_path, monkeypatch, damage="unbound_dependency")
    with pytest.raises(ValueError, match="DISABLED_WARNING_LOADED_DEPENDENCY_UNBOUND"):
        evaluator(context)


@pytest.mark.parametrize("name", ["CameraIntegration.cs", "FrameIntegration.cs", "Dependencies.props"])
def test_only_public_business_files_can_change(tmp_path, monkeypatch, name):
    evaluator, context, requests, compilations = setup(tmp_path, monkeypatch)
    context["implementation_plan"]["binding_registry"]["edit_bindings"][0]["canonical_target_path"] = name
    with pytest.raises(ValueError, match="CHANGE_OUTSIDE_PUBLIC_SCOPE"):
        evaluator(context)
    assert not requests and not compilations


@pytest.mark.parametrize("target", ["assessor_ref", "case_configuration_ref"])
def test_frozen_contract_drift_rejected_before_compilation(tmp_path, monkeypatch, target):
    evaluator, context, requests, compilations = setup(tmp_path, monkeypatch)
    Path(getattr(evaluator, target)["path"]).write_text("changed")
    with pytest.raises(ValueError):
        evaluator(context)
    assert not requests and not compilations


@pytest.mark.parametrize("name", ["logs", "camera_writes"])
def test_large_repeated_observations_roundtrip_without_changing_measured_assertions(tmp_path, monkeypatch, name):
    evaluator, _, _, _ = setup(tmp_path, monkeypatch)
    values = ([{"level": "Warning", "message": "Main camera is unavailable.", "source": "FOV Companion"}] * 10000
              if name == "logs" else [85] * 5000 + [95] * 5000)
    original = {"actions": [{name: values}]}
    selected = evaluator.check_observation(original, "ticks_0.logs")
    compact = selected[name]
    assert compact["sequence_encoding"] == "ordered_runs_v1" and compact["total_items"] == 10000
    assert [row["value"] for row in compact["runs"] for _ in range(row["count"])] == values
    assert len(json.dumps(selected)) < 1024
    assert original["actions"][0][name] == values


def test_sequence_compression_preserves_boolean_integer_and_float_types(tmp_path, monkeypatch):
    evaluator, _, _, _ = setup(tmp_path, monkeypatch)
    original = [True] * 100 + [1] * 100 + [1.0] * 100
    compact = evaluator.check_observation({"actions": [{"camera_writes": original}]}, "ticks_0.camera_effect")["camera_writes"]
    restored = [row["value"] for row in compact["runs"] for _ in range(row["count"])]
    assert [type(value) for value in restored] == [type(value) for value in original]
    assert json.dumps(restored) == json.dumps(original)
