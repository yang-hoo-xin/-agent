"""Real unchanged source plus doubles; these are not GTFO or model trials."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.mod_agent.domain.accurate_crosshair_eval import (
    API_CASE,
    API_CHECKS,
    CONFIG_CASE,
    CONFIG_CHECKS,
    AccurateCrosshairTaskOracle,
    BoundExistingMatrixOracle,
    CurrentPlanTaskOracle,
)
from src.mod_agent.evaluation.patch_task_suite import reference, save_once

SOURCE = Path(__file__).parents[1] / "fixtures/patch_eval/accurate_crosshair"


@pytest.mark.parametrize("case_id,checks,failed", [(CONFIG_CASE, CONFIG_CHECKS, 1), (API_CASE, API_CHECKS, 12)])
def test_original_source_exposes_the_new_requirement_without_hiding_preservation(tmp_path, case_id, checks, failed):
    if not Path("C:/Program Files/dotnet/sdk/7.0.401/Roslyn/bincore/csc.dll").is_file():
        pytest.skip("The fixed local .NET 7 task environment is unavailable.")
    workspace = tmp_path / "source"
    shutil.copytree(SOURCE, workspace)
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in workspace.rglob("*.cs")}
    oracle = AccurateCrosshairTaskOracle(case_id=case_id, workspace_root=workspace,
        implementation_plan={}, output_root=tmp_path / "results")
    result = oracle.verify_baseline()
    assert tuple(row["check"] for row in result["checks"]) == checks
    assert len(result["failures"]) == failed
    assert result["model_calls"] == 0 and result["input_kind"] == "unchanged_baseline"
    assert any(row["passed"] for row in result["checks"])
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in workspace.rglob("*.cs")}
    first = next(workspace.rglob("*.cs"))
    first.write_bytes(first.read_bytes() + b"\n// changed source identity\n")
    # Change an actually used source, rather than an unrelated file in the copy.
    used = workspace / oracle.sources[0]
    used.write_bytes(used.read_bytes() + b"\n// source drift\n")
    with pytest.raises(ValueError, match="PATCH_EVAL_BASELINE_CHANGED"):
        oracle.verification_identity()


def test_existing_matrix_wrapper_preserves_originals_and_binds_current_code(tmp_path, monkeypatch):
    from types import SimpleNamespace

    code = {"baseline_sha256": "a" * 64, "code_sha256": "b" * 64, "files": ["Behavior.cs"]}
    matrix_ref = save_once(tmp_path / "original-matrix.json", {
        "checks": [{"check": "preserve", "passed": True}], "failures": [], "executions": 1})
    report_ref = save_once(tmp_path / "original-report.json", {
        "status": "passed", "execution_origin": "executed", "materialized_code_identity": code,
        "verification_ref": matrix_ref})
    config = save_once(tmp_path / "config.json", {"behavior_evaluator": {
        "kwargs": {"output_root": str(tmp_path / "original-validator")}}})
    monkeypatch.setattr("src.mod_agent.patch_worker_configuration.PatchWorkerConfiguration.load",
        lambda _: SimpleNamespace(behavior_evaluator=lambda: lambda context: {"report_ref": report_ref}))
    old_matrix = Path(matrix_ref["path"]).read_bytes()
    old_report = Path(report_ref["path"]).read_bytes()
    oracle = BoundExistingMatrixOracle(configuration_ref=config,
        identity_refs={kind: [config] for kind in ("validator", "inputs", "environment")},
        expected_check_ids=["preserve"], output_root=tmp_path / "wrapped")
    context = {"materialized_code_identity": code,
               "model_response": {"output_sha256": "c" * 64, "path": str(tmp_path / "response-one.txt")}}
    result = oracle(context)
    assert result["source_report_ref"] == report_ref
    assert result["verification_identity"] == oracle.verification_identity()
    assert json.loads(Path(result["verification_ref"]["path"]).read_text())["materialized_code_identity"] == code
    assert Path(matrix_ref["path"]).read_bytes() == old_matrix
    assert Path(report_ref["path"]).read_bytes() == old_report
    second = oracle({**context, "model_response": {**context["model_response"], "path": str(tmp_path / "response-two.txt")}})
    assert Path(result["report_ref"]["path"]).parent != Path(second["report_ref"]["path"]).parent
    with pytest.raises(ValueError, match="PATCH_EVAL_CODE_IDENTITY_MISMATCH"):
        oracle({**context, "materialized_code_identity": {**code, "code_sha256": "d" * 64}})
    assert reference(result["report_ref"]["path"]) == result["report_ref"]


def _current_task_oracle(tmp_path, monkeypatch):
    from src.mod_agent.domain import accurate_crosshair_eval as module
    from tests.unit.test_crosshair_current_plan_matrix import _case
    from tests.unit.test_fresh_planning_continuation import _source_hashes

    inputs, context, _, _, _ = _case(tmp_path, monkeypatch)
    # This exercises Plan/byte binding using a synthetic Mod and no compiler.
    monkeypatch.setattr(module, "CONFIG_SOURCES", tuple(_source_hashes(inputs.workspace)))
    monkeypatch.setattr(module, "_dotnet_identity", lambda: {"test_environment": "no_compiler"})
    oracle = CurrentPlanTaskOracle(case_id=CONFIG_CASE, artifact_store_root=inputs.store.root,
        workspace_root=inputs.workspace, output_root=tmp_path / "current-task",
        expected_check_ids=CONFIG_CHECKS)
    calls = []
    def observe(sources):
        calls.append(sources)
        return {"checks": [{"check": name, "passed": True} for name in CONFIG_CHECKS],
                "failures": [], "executions": 3}
    monkeypatch.setattr(oracle, "_run_sources", observe)
    return inputs, context, oracle, calls


def test_task_oracle_consumes_current_plan_without_fixed_target_reference(tmp_path, monkeypatch):
    from tests.unit.test_fresh_planning_continuation import _source_hashes

    inputs, context, oracle, calls = _current_task_oracle(tmp_path, monkeypatch)
    before = _source_hashes(inputs.workspace)
    report = oracle(context)
    assert report["status"] == "passed"
    assert report["implementation_plan_ref"] == context["implementation_plan_ref"]
    assert report["verification_summary"] == {"checks": 5, "failed_checks": 0, "executions": 3}
    assert report["materialized_code_identity"] == context["materialized_code_identity"]
    assert len(calls) == 1 and oracle.plan == {}
    changed_path = context["implementation_plan"]["binding_registry"]["edit_bindings"][0]["canonical_target_path"]
    assert calls[0][changed_path] != (inputs.workspace / changed_path).read_bytes()
    assert _source_hashes(inputs.workspace) == before
    assert reference(report["report_ref"]["path"]) == report["report_ref"]


def test_task_oracle_preserves_product_plan_paths_with_an_explicit_source_prefix(tmp_path, monkeypatch):
    from src.mod_agent.domain import accurate_crosshair_eval as module
    from tests.unit.test_crosshair_current_plan_matrix import _case
    from tests.unit.test_fresh_planning_continuation import _source_hashes

    inputs, context, _, _, _ = _case(tmp_path, monkeypatch)
    prefix = inputs.behavior.parent.relative_to(inputs.workspace)
    sources = tuple(_source_hashes(inputs.workspace))
    monkeypatch.setattr(module, "CONFIG_SOURCES", tuple(Path(name).relative_to(prefix).as_posix() for name in sources))
    monkeypatch.setattr(module, "_dotnet_identity", lambda: {"test_environment": "no_compiler"})
    oracle = CurrentPlanTaskOracle(case_id=CONFIG_CASE, artifact_store_root=inputs.store.root,
        workspace_root=inputs.workspace, source_prefix=prefix.as_posix(), output_root=tmp_path / "current-task",
        expected_check_ids=CONFIG_CHECKS)
    seen = []

    def observe(values):
        seen.append(values)
        return {"checks": [{"check": name, "passed": True} for name in CONFIG_CHECKS],
                "failures": [], "executions": 3}

    monkeypatch.setattr(oracle, "_run_sources", observe)
    report = oracle(context)
    assert set(seen[0]) == set(sources)
    assert report["materialized_code_identity"] == context["materialized_code_identity"]
    assert report["status"] == "passed"


@pytest.mark.parametrize("drift", ["plan", "source", "change_hash", "response", "returned_text", "code"])
def test_current_task_oracle_rejects_identity_drift_before_behavior(tmp_path, monkeypatch, drift):
    from src.mod_agent.model_qualification import canonical_hash

    _, context, oracle, calls = _current_task_oracle(tmp_path, monkeypatch)
    if drift == "plan":
        context["implementation_plan"]["blocking"] = True
    elif drift == "source":
        context["source_snapshot_sha256"] = "f" * 64
    elif drift == "change_hash":
        context["generated_changes_sha256"] = "f" * 64
    elif drift == "response":
        context["model_response"]["output_sha256"] = "f" * 64
    elif drift == "returned_text":
        context["generated_changes"][0]["patch"]["after_text"] += "\n// not returned by model"
        context["generated_changes_sha256"] = canonical_hash(context["generated_changes"])
    else:
        context["materialized_code_identity"]["code_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        oracle(context)
    assert not calls
