"""Read-only compatibility for execute_version receipts; no compiler/model/network runs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.unit.test_patch_execution_index import _retain
from tests.unit.test_patch_langfuse import _case, _prepare


def _file(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _single_process(tmp_path):
    root, journal_path, journal, matrix_ref = _case(tmp_path)
    evaluation = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]
    old = json.loads(Path(matrix_ref["path"]).read_text())
    checks = [{**row, "group": "preservation" if row["passed"] else "change"} for row in old["checks"]]
    source = _file(tmp_path / "process/Subject.cs", b"// independent byte-identity fixture\n")
    program = _file(tmp_path / "process/Program.cs", b"// checker byte-identity fixture\n")
    assembly = _file(tmp_path / "process/CheckApp.dll", b"MZ synthetic compiled-byte fixture")
    arguments = _file(tmp_path / "process/compile.rsp", "\n".join([
        "/nologo", "/target:exe", "/langversion:latest", f'/out:"{assembly["path"]}"',
        '/r:"framework-reference.dll"', f'"{source["path"]}"', f'"{program["path"]}"',
    ]).encode())
    compilation = _retain(tmp_path / "process/compilation.json", {
        "exit_code": 0, "stdout": "", "stderr": "", "sources": [source, program], "arguments_ref": arguments,
    })
    matrix = {"status": "behavior_failed", "checks": checks, "failed_checks": [checks[1]["check"]],
        "preservation_passed": True, "compilation_ref": compilation, "assembly_ref": assembly,
        "exit_code": 1, "stdout": json.dumps(checks), "stderr": "",
        "execution_origin": "actual_csharp_process", "source_ref": source}
    evaluation["verification_ref"] = _retain(Path(matrix_ref["path"]), matrix)
    evaluation["verification_summary"]["executions"] = 1
    _save_case(journal_path, journal, evaluation, matrix)
    return root, journal_path, journal, evaluation, matrix


def _save_case(journal_path, journal, evaluation, matrix):
    evaluation["verification_ref"] = _retain(Path(evaluation["verification_ref"]["path"]), matrix)
    report_path = Path(evaluation["report_ref"]["path"])
    report = json.loads(report_path.read_text())
    report["verification_ref"] = evaluation["verification_ref"]
    report["verification_summary"] = evaluation["verification_summary"]
    evaluation["report_ref"] = _retain(report_path, report)
    _retain(journal_path, journal)


def test_exact_single_process_receipt_derives_count_without_mutating_matrix(tmp_path):
    root, path, _, _, matrix = _single_process(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    batch = _prepare(root, path)
    assert len(batch.scores) == 1 and batch.scores[0]["value"] == 0.5
    assert "executions" not in matrix
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("damage", [
    "origin", "stdout", "exit_code", "failed_names", "preservation", "compile_failed", "compile_hash",
    "missing_assembly", "assembly_hash", "source_hash", "checker_hash", "arguments_hash", "arguments_binding",
    "source_binding", "unknown_shape", "summary_executions", "explicit_zero",
])
def test_single_process_count_requires_the_complete_consistent_receipt(tmp_path, damage):
    root, path, journal, evaluation, matrix = _single_process(tmp_path)
    compilation_path = Path(matrix["compilation_ref"]["path"])
    compilation = json.loads(compilation_path.read_text())
    if damage == "origin":
        matrix["execution_origin"] = "unknown"
    elif damage == "stdout":
        matrix["stdout"] = json.dumps([{**row, "passed": True} for row in matrix["checks"]])
    elif damage == "exit_code":
        matrix["exit_code"] = 0
    elif damage == "failed_names":
        matrix["failed_checks"] = []
    elif damage == "preservation":
        matrix["preservation_passed"] = False
    elif damage == "compile_failed":
        compilation["exit_code"] = 1
        matrix["compilation_ref"] = _retain(compilation_path, compilation)
    elif damage == "compile_hash":
        compilation_path.write_text("{}")
    elif damage == "missing_assembly":
        Path(matrix["assembly_ref"]["path"]).unlink()
    elif damage == "assembly_hash":
        Path(matrix["assembly_ref"]["path"]).write_bytes(b"different assembly")
    elif damage in {"source_hash", "checker_hash"}:
        Path(compilation["sources"][0 if damage == "source_hash" else 1]["path"]).write_bytes(b"different source")
    elif damage == "arguments_hash":
        Path(compilation["arguments_ref"]["path"]).write_bytes(b"different arguments")
    elif damage == "arguments_binding":
        compilation["arguments_ref"] = _file(Path(compilation["arguments_ref"]["path"]), b"/out:unrelated.dll")
        matrix["compilation_ref"] = _retain(compilation_path, compilation)
    elif damage == "source_binding":
        matrix["source_ref"] = compilation["sources"][1]
    elif damage == "unknown_shape":
        matrix["unregistered_receipt_field"] = True
    elif damage == "summary_executions":
        evaluation["verification_summary"]["executions"] = 2
    else:
        matrix["executions"] = 0
    _save_case(path, journal, evaluation, matrix)
    assert _prepare(root, path).scores == ()
