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
