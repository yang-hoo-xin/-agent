"""Compatibility exports and verifier identity for the extracted build owner."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.mod_agent import errors, local_entry, model_qualification, product_executor
from src.mod_agent.build import nuget
from src.mod_agent.domain import full_project_compilation
from tests.unit.test_full_project_compilation import _checker


def test_entry_keeps_exact_nuget_and_error_aliases():
    for name in ("NuGetIsolatedBuildProfile", "NuGetIsolatedBuildExecution",
                 "_create_nuget_isolated_build_profile", "_run_nuget_isolated_build",
                 "_run_nuget_isolated_verification_command", "_require_run_local_build_path",
                 "_join_build_phase_output"):
        assert getattr(local_entry, name) is getattr(nuget, name)
    assert local_entry.LocalEntryError is product_executor.LocalEntryError is errors.LocalEntryError
    assert full_project_compilation._run_nuget_isolated_build is nuget._run_nuget_isolated_build
    assert full_project_compilation._create_nuget_isolated_build_profile is nuget._create_nuget_isolated_build_profile
    assert str(errors.LocalEntryError("same code")) == "same code"


def test_build_owner_cold_import_does_not_load_entry_or_workflow():
    result = subprocess.run([sys.executable, "-B", "-c",
        "import sys; import src.mod_agent.build.nuget; "
        "assert 'src.mod_agent.local_entry' not in sys.modules; "
        "assert 'src.mod_agent.product_executor' not in sys.modules; "
        "assert 'src.mod_agent.workflow.graph' not in sys.modules"],
        capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr


def test_full_compilation_rejects_actual_nuget_owner_drift_during_execution(tmp_path, monkeypatch):
    owner_copy = tmp_path / "nuget-owner.py"
    owner_copy.write_bytes(Path(nuget.__file__).read_bytes())
    monkeypatch.setattr(nuget, "__file__", str(owner_copy))
    _, _, checker, calls, _ = _checker(tmp_path / "fixture", monkeypatch)
    initial = checker.verification_identity()
    runner = checker._runner

    def changed_owner(profile):
        result = runner(profile)
        owner_copy.write_bytes(owner_copy.read_bytes() + b"\n# controlled implementation revision\n")
        return result

    checker._runner = changed_owner
    with pytest.raises(ValueError, match="VERIFIER_IDENTITY_CHANGED"):
        checker.verify_baseline()
    changed = checker.verification_identity()
    assert changed["validator_sha256"] != initial["validator_sha256"]
    assert changed["inputs_sha256"] == initial["inputs_sha256"]
    assert changed["environment_sha256"] == initial["environment_sha256"]
    assert len(calls) == 1


@pytest.mark.parametrize("relative_owner", ["build/nuget.py", "build/dependencies.py"])
def test_worker_fingerprint_changes_when_only_extracted_build_owner_changes(tmp_path, monkeypatch, relative_owner):
    original_root = Path(model_qualification.__file__).parent
    for name in {*model_qualification.worker_implementation_identity()["files"], relative_owner}:
        copied = tmp_path / name
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes((original_root / name).read_bytes())
    monkeypatch.setattr(model_qualification, "__file__", str(tmp_path / "model_qualification.py"))
    before = model_qualification.worker_implementation_identity()
    owner = tmp_path / relative_owner
    owner.write_bytes(owner.read_bytes() + b"\n# controlled build owner revision\n")
    after = model_qualification.worker_implementation_identity()
    assert after["implementation_sha256"] != before["implementation_sha256"]
    assert after["files"]["local_entry.py"] == before["files"]["local_entry.py"]
