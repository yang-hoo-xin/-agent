"""One owned application baseline, compiled and observed in separate processes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationInputV1,
    preflight_patch_continuation,
)
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration


@pytest.fixture(scope="module")
def task_module():
    path = Path(__file__).parents[1] / "fixtures/patch_eval/owned_config_service/behavior_evaluator.py"
    spec = importlib.util.spec_from_file_location("owned_config_oracle_tests", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module._dotnet_identity()
    except ValueError as exc:
        pytest.skip(str(exc))
    return module


@pytest.fixture(scope="module")
def prepared(task_module, tmp_path_factory):
    root = tmp_path_factory.mktemp("owned-config") / "task"
    observations = {}
    trace = ExecutionTrace("b" * 32, "owned-config-baseline", "offline-acceptance",
        recorder=lambda row: observations.__setitem__(row["id"], row))
    with trace.activate():
        result = task_module.prepare_owned_config_task(output_root=root)
    result["test_execution_observations"] = list(observations.values())
    return root, result


def test_baseline_really_fails_requested_change_and_preserves_all_existing_paths(task_module, prepared):
    root, result = prepared
    assert result["ready_for_model_screen"] is True
    baseline = result["baseline"]
    assert baseline["observed_failures"] == list(task_module.CHANGE_CHECKS)
    assert baseline["all_preservation_checks_passed"] is True
    matrix = json.loads(Path(baseline["matrix_ref"]["path"]).read_text())
    assert len(matrix["checks"]) == 15 and matrix["executions"] == 23
    assert sum(row["passed"] for row in matrix["checks"]) == 8
    commands = json.loads(Path(matrix["build_commands_ref"]["path"]).read_text())
    assert len(commands) == 1 and commands[0]["exit_code"] == 0
    assert "csc.dll" in commands[0]["argv"][1]
    assert Path(matrix["application_ref"]["path"]).is_file()
    observed = json.loads(Path(matrix["process_observations_ref"]["path"]).read_text())
    assert len(observed) == 23 and all(row["process_id"] for row in observed)
    assert all("DASHSCOPE_API_KEY" not in row["environment_keys"] and "OPENAI_API_KEY" not in row["environment_keys"] for row in observed)
    assert not list((root / "store/cr").glob("*.json"))


def test_prepared_case_consumes_existing_preflight_and_worker_configuration_only(prepared):
    root, result = prepared
    value = json.loads(Path(result["continuation_input_ref"]["path"]).read_text())
    for key in ("feature_spec_ref", "evidence_pack_ref", "implementation_plan_ref"):
        value[key] = ArtifactRef(**value[key])
    admitted = preflight_patch_continuation(PatchContinuationInputV1(**value))
    assert admitted.feature_spec["target_mod"] == "OwnedConfigService"
    assert len(admitted.implementation_plan["binding_registry"]["edit_bindings"]) == 1
    assert admitted.implementation_plan["target_symbols"] == ["Update"]
    configuration = PatchWorkerConfiguration.load(root / "worker.json")
    assert configuration.policy.max_total_model_turns == 5 and configuration.policy.max_tool_rounds == 6
    disclosure = json.loads((root / "source-disclosure-preview.json").read_text())
    assert disclosure["approved"] is False and len(disclosure["source_files"]) == 3
    assert result["model_calls"] == 0 and result["distinct_task_count"] == 1


def test_unexecuted_checks_do_not_count_as_preservation_pass(task_module, prepared, tmp_path, monkeypatch):
    root, _ = prepared
    oracle = task_module.OwnedConfigOracle(workspace_root=root / "source", output_root=tmp_path / "not-executed")
    monkeypatch.setattr(oracle, "_evaluate_files", lambda *_: {"status": "infrastructure_failed", "checks": [], "executions": 0})
    result = oracle.verify_baseline()
    assert result["all_preservation_checks_passed"] is False and result["expected_failure_signature_observed"] is False


def test_actual_compiler_diagnostic_is_distinct_from_unavailable_infrastructure(task_module, prepared, tmp_path):
    root, _ = prepared
    oracle = task_module.OwnedConfigOracle(workspace_root=root / "source", output_root=tmp_path / "compiler")
    report = oracle._evaluate_files(tmp_path / "compiler-error", {"OwnedConfigService/JsonConfigStore.cs": b"this is deliberately invalid C sharp;"})
    assert report["status"] == "compiler_failed" and report["checks"] == []
    assert "error CS" in report["compiler_diagnostic"]


def test_actual_compiler_preserves_non_ascii_diagnostic(task_module, tmp_path):
    workspace = task_module.HERE / "source"
    oracle = task_module.OwnedConfigOracle(workspace_root=workspace, output_root=tmp_path / "compiler")
    relative = "OwnedConfigService/JsonConfigStore.cs"
    source = (workspace / relative).read_text(encoding="utf-8")
    original = "configuration[key] = value.Clone();"
    assert source.count(original) == 1
    invalid = source.replace(original, "configuration[key] = 缺失的配置值;").encode("utf-8")

    report = oracle._evaluate_files(tmp_path / "unicode-compiler-error", {relative: invalid})

    assert report["status"] == "compiler_failed" and report["checks"] == []
    assert "error CS0103" in report["compiler_diagnostic"]
    assert "缺失的配置值" in report["compiler_diagnostic"]
    assert "\ufffd" not in report["compiler_diagnostic"]
    commands = json.loads(Path(report["build_commands_ref"]["path"]).read_text(encoding="utf-8"))
    actual_output = commands[0]["stdout"] + commands[0]["stderr"]
    assert "缺失的配置值" in actual_output
    assert "\ufffd" not in actual_output


def test_real_compiler_and_process_observations_use_measured_timing(prepared):
    _, result = prepared
    rows = result["test_execution_observations"]
    compiles = [row for row in rows if row["name"] == "patch.compile"]
    matrices = [row for row in rows if row["name"] == "behavior.matrix"]
    processes = [row for row in rows if row["name"] == "behavior.process"]
    assert len(compiles) == len(matrices) == 1 and len(processes) == 23
    assert compiles[0]["attributes"]["exit_code"] == 0
    assert matrices[0]["attributes"]["checks_run"] == 15
    assert matrices[0]["attributes"]["checks_failed"] == 7
    assert all(row["parent_id"] == matrices[0]["id"] for row in processes)
    assert all(row["finished_at"] and row["elapsed_ms"] > 0 for row in [*compiles, *processes])
    assert not any(row["kind"] == "generation" for row in rows)
    assert all("stdout" not in row["attributes"] and "argv" not in row["attributes"] for row in rows)
