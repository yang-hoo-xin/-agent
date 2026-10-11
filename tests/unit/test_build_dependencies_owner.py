"""Dependency behavior stays shared while lower-level consumers leave local_entry."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from src.mod_agent import local_entry
from src.mod_agent.build import dependencies
from src.mod_agent.domain import full_project_compilation
from tests.unit.test_full_project_compilation import _checker


def test_old_entry_names_are_exact_dependency_owner_aliases():
    names = ("RunLocalGameFolderBindingV1", "_RunLocalGameFolderSourceIdentity", "_binary_tree_snapshot",
             "_binary_tree_snapshot_sha256", "_windows_extended_length_path", "_directory_copy_path_argument",
             "_copy_validated_directory_tree", "_validate_game_folder_build_binding", "_materialize_game_folder_build_dependency")
    for name in names:
        assert getattr(local_entry, name) is getattr(dependencies, name)
    assert full_project_compilation.RunLocalGameFolderBindingV1 is dependencies.RunLocalGameFolderBindingV1
    assert full_project_compilation._binary_tree_snapshot is dependencies._binary_tree_snapshot


def test_lower_level_dependency_consumers_cold_import_without_local_entry():
    code = "\n".join([
        "import importlib,sys",
        "for name in ('src.mod_agent.build.dependencies', 'src.mod_agent.domain.full_project_compilation', "
        "'src.mod_agent.domain.compilation_feedback', 'src.mod_agent.domain.complete_crosshair_verification', "
        "'src.mod_agent.proposal.dependency_documentation'):",
        "    importlib.import_module(name)",
        "    assert 'src.mod_agent.local_entry' not in sys.modules, name",
    ])
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                            encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr


def test_actual_dependency_owner_drift_invalidates_inflight_compilation(tmp_path, monkeypatch):
    owner_copy = tmp_path / "dependencies-owner.py"
    owner_copy.write_bytes(Path(dependencies.__file__).read_bytes())
    monkeypatch.setattr(dependencies, "__file__", str(owner_copy))
    _, _, checker, calls, _ = _checker(tmp_path / "fixture", monkeypatch)
    initial = checker.verification_identity()
    original = checker._runner

    def changed_owner(profile):
        result = original(profile)
        owner_copy.write_bytes(owner_copy.read_bytes() + b"\n# controlled dependency owner revision\n")
        return result

    checker._runner = changed_owner
    with pytest.raises(ValueError, match="VERIFIER_IDENTITY_CHANGED"):
        checker.verify_baseline()
    assert checker.verification_identity()["validator_sha256"] != initial["validator_sha256"]
    assert len(calls) == 1
