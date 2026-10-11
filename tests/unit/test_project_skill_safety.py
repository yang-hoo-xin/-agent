from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
QA_SCRIPT_DIR = REPO_ROOT / ".agents" / "skills" / "qa-tester" / "scripts"


def _load_module(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.path.insert(0, str(path.parent))
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_bootstrap_rejects_a_data_path_that_resolves_outside_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = _load_module("qa_bootstrap_escape", QA_SCRIPT_DIR / "qa_bootstrap.py")
    isolated = tmp_path / "isolated-repo"
    isolated.mkdir()
    (isolated / ".qa-isolated-target").write_text("qa\n", encoding="utf-8")
    outside_data = tmp_path / "outside-data"
    chroma = outside_data / "db" / "chroma"
    chroma.mkdir(parents=True)
    sentinel = chroma / "keep.bin"
    sentinel.write_bytes(b"keep")
    monkeypatch.setattr(
        bootstrap,
        "_target_paths",
        lambda target: (
            target / "scripts",
            target / "tests" / "fixtures" / "sample_documents",
            outside_data,
            target / "logs" / "traces.jsonl",
        ),
    )

    with pytest.raises(ValueError, match="outside"):
        bootstrap.clear_all(isolated)
    assert sentinel.read_bytes() == b"keep"


def test_contained_path_rejects_parent_traversal(tmp_path: Path) -> None:
    qa_paths = _load_module("qa_paths_containment", QA_SCRIPT_DIR / "qa_paths.py")
    target = tmp_path / "target"
    target.mkdir()

    with pytest.raises(ValueError, match="outside"):
        qa_paths.require_contained_path(target, target / ".." / "outside.yaml")


def test_isolated_target_must_not_overlap_active_repository(
    tmp_path: Path,
) -> None:
    qa_paths = _load_module("qa_paths_overlap", QA_SCRIPT_DIR / "qa_paths.py")
    nested = REPO_ROOT / ".qa-nested-test-target"

    with pytest.raises(ValueError, match="overlap"):
        qa_paths.resolve_isolated_repo(nested)

    ancestor = REPO_ROOT.parents[0]
    with pytest.raises(ValueError, match="overlap"):
        qa_paths.resolve_isolated_repo(ancestor)


def test_baseline_reports_failure_when_fixtures_or_commands_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bootstrap = _load_module("qa_bootstrap_failure", QA_SCRIPT_DIR / "qa_bootstrap.py")
    isolated = tmp_path / "isolated-repo"
    (isolated / "config").mkdir(parents=True)
    (isolated / ".qa-isolated-target").write_text("qa\n", encoding="utf-8")
    (isolated / "config" / "settings.yaml").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        bootstrap,
        "run_cmd",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=[], returncode=1),
    )

    assert bootstrap.setup_baseline(isolated) is False
    output = capsys.readouterr().out
    assert "Baseline setup failed" in output
    assert "System is now in Baseline state" not in output


def test_restore_rejects_unsealed_target_drift(tmp_path: Path) -> None:
    qa_paths = _load_module("qa_paths_target_drift", QA_SCRIPT_DIR / "qa_paths.py")
    settings = tmp_path / "settings.yaml"
    backup = tmp_path / "settings.yaml.qa-backup"
    settings.write_text("value: original\n", encoding="utf-8")
    qa_paths.create_backup(settings, backup)
    settings.write_text("value: unexpected\n", encoding="utf-8")

    with pytest.raises(ValueError, match="target changed"):
        qa_paths.restore_backup(settings, backup)

    qa_paths.seal_target_state(settings, backup)
    qa_paths.restore_backup(settings, backup)
    assert settings.read_text(encoding="utf-8") == "value: original\n"


def test_multistep_owned_config_write_restores_its_backup(tmp_path: Path) -> None:
    runner = _load_module("qa_multistep_restore", QA_SCRIPT_DIR / "qa_multistep.py")
    isolated = tmp_path / "isolated-repo"
    config_dir = isolated / "config"
    config_dir.mkdir(parents=True)
    (isolated / ".qa-isolated-target").write_text("qa\n", encoding="utf-8")
    settings = config_dir / "settings.yaml"
    settings.write_text("value: original\n", encoding="utf-8")
    runner.configure_target(isolated)

    runner.backup_config()
    runner.write_config_text("value: owned-change\n")
    runner.restore_config()

    assert settings.read_text(encoding="utf-8") == "value: original\n"
