from __future__ import annotations

import importlib.util
import inspect
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QA_SCRIPT_DIR = REPO_ROOT / ".agents" / "skills" / "qa-tester" / "scripts"
SKILL_CREATOR_SCRIPT_DIR = (
    REPO_ROOT / ".agents" / "skills" / "skill-creator" / "scripts"
)


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


@pytest.mark.parametrize(
    "script_name",
    ["qa_bootstrap.py", "qa_config.py", "qa_multistep.py", "qa_validate_notes.py"],
)
def test_qa_helpers_resolve_the_actual_repository_root(script_name: str) -> None:
    module = _load_module(f"qa_{script_name}", QA_SCRIPT_DIR / script_name)
    assert module.REPO_ROOT == REPO_ROOT


def test_qa_target_must_be_an_explicit_marked_isolated_repository(
    tmp_path: Path,
) -> None:
    qa_paths = _load_module("qa_paths", QA_SCRIPT_DIR / "qa_paths.py")
    isolated = tmp_path / "isolated-repo"
    isolated.mkdir()

    with pytest.raises(ValueError, match="marker"):
        qa_paths.resolve_isolated_repo(isolated)
    with pytest.raises(ValueError, match="active repository"):
        qa_paths.resolve_isolated_repo(REPO_ROOT)

    (isolated / qa_paths.ISOLATION_MARKER).write_text("qa\n", encoding="utf-8")
    assert qa_paths.resolve_isolated_repo(isolated) == isolated.resolve()


def test_qa_backup_refuses_an_unidentified_existing_backup(tmp_path: Path) -> None:
    qa_paths = _load_module("qa_paths_backup", QA_SCRIPT_DIR / "qa_paths.py")
    settings = tmp_path / "settings.yaml"
    settings.write_text("value: current\n", encoding="utf-8")
    backup = tmp_path / "settings.yaml.qa-backup"
    backup.write_text("value: unknown\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="existing backup"):
        qa_paths.create_backup(settings, backup)
    assert backup.read_text(encoding="utf-8") == "value: unknown\n"
    with pytest.raises(ValueError, match="metadata"):
        qa_paths.restore_backup(settings, backup)
    assert settings.read_text(encoding="utf-8") == "value: current\n"


def test_qa_note_validator_rejects_zero_rows_and_empty_pass_notes(
    tmp_path: Path,
) -> None:
    validator = _load_module(
        "qa_validate_notes_focus", QA_SCRIPT_DIR / "qa_validate_notes.py"
    )
    progress = tmp_path / "progress.md"
    progress.write_text("# no result rows\n", encoding="utf-8")
    assert validator.validate(progress) is False

    progress.write_text("| ✅ | A-01 | title |   |\n", encoding="utf-8")
    assert validator.validate(progress) is False


@pytest.mark.parametrize(
    ("rows", "accepted"),
    [
        ("| FAIL | Q-01 | Build | Compiler exited 1. |\n", True),
        ("| SKIP | Q-01 | Runtime | Outside the selected scope. |\n", True),
        ("| ✅ | Q-01 | Build | Compiler exited 0. |\n", True),
        ("# no result rows\n", False),
        ("| FAIL | Q-01 | Build | |\n", False),
        ("| SKIP | | Runtime | Outside scope. |\n", False),
        ("| PASS | Q-01 | Build | Exit 0. |\n| FAIL | Q-01 | Build | Exit 1. |\n", False),
    ],
    ids=["all_failed", "all_skipped", "legacy_pass", "empty_table", "empty_note", "empty_id", "duplicate_id"],
)
def test_qa_notes_validate_structure_independently_of_test_outcome(tmp_path: Path, rows: str, accepted: bool) -> None:
    validator = _load_module("qa_note_outcome_independent", QA_SCRIPT_DIR / "qa_validate_notes.py")
    progress = tmp_path / "progress.md"
    progress.write_text(rows, encoding="utf-8")
    assert validator.validate(progress) is accepted


def test_qa_multistep_run_has_no_ignored_behavior_parameters() -> None:
    runner = _load_module("qa_multistep_focus", QA_SCRIPT_DIR / "qa_multistep.py")
    assert list(inspect.signature(runner.run).parameters) == ["args"]


def test_skill_validator_rejects_empty_required_metadata_and_requires_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _load_module(
        "quick_validate_focus", SKILL_CREATOR_SCRIPT_DIR / "quick_validate.py"
    )
    skill_dir = tmp_path / "empty-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: ''\ndescription: ''\n---\n", encoding="utf-8"
    )
    valid, message = validator.validate_skill(skill_dir)
    assert valid is False
    assert "name" in message.lower()

    monkeypatch.setattr(validator, "yaml", None)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: nested-skill\ndescription: >\n  multiline description\nmetadata:\n  owner: qa\n---\n",
        encoding="utf-8",
    )
    valid, message = validator.validate_skill(skill_dir)
    assert valid is False
    assert "PyYAML" in message


def test_skill_packager_excludes_cache_and_temporary_files(tmp_path: Path) -> None:
    packager = _load_module(
        "package_skill_focus", SKILL_CREATOR_SCRIPT_DIR / "package_skill.py"
    )
    skill_dir = tmp_path / "sample-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: sample-skill\ndescription: Sample skill.\n---\n",
        encoding="utf-8",
    )
    cache = skill_dir / "scripts" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "helper.pyc").write_bytes(b"compiled")
    (skill_dir / "notes.tmp").write_text("temporary\n", encoding="utf-8")

    archive = packager.package_skill(skill_dir, tmp_path / "dist")
    assert archive is not None
    with zipfile.ZipFile(archive) as packaged:
        names = set(packaged.namelist())
    assert names == {"sample-skill/SKILL.md"}


def test_qa_bootstrap_clear_is_confined_to_the_marked_target(
    tmp_path: Path,
) -> None:
    bootstrap = _load_module("qa_bootstrap_isolation", QA_SCRIPT_DIR / "qa_bootstrap.py")
    isolated = tmp_path / "isolated-repo"
    chroma = isolated / "data" / "db" / "chroma"
    chroma.mkdir(parents=True)
    (isolated / ".qa-isolated-target").write_text("qa\n", encoding="utf-8")
    (chroma / "index.bin").write_bytes(b"qa")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"keep")

    bootstrap.clear_all(isolated)

    assert list(chroma.iterdir()) == []
    assert outside.read_bytes() == b"keep"


def test_qa_config_never_prints_a_credential_prefix(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _load_module("qa_config_secret", QA_SCRIPT_DIR / "qa_config.py")
    isolated = tmp_path / "isolated-repo"
    config_dir = isolated / "config"
    config_dir.mkdir(parents=True)
    (isolated / ".qa-isolated-target").write_text("qa\n", encoding="utf-8")
    secret = "secret-prefix-that-must-not-appear"
    (config_dir / "settings.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "test_credentials.yaml").write_text(
        f"deepseek:\n  api_key: {secret}\n", encoding="utf-8"
    )
    config.configure_target(isolated)

    config.cmd_check()

    assert secret[:8] not in capsys.readouterr().out


def test_skill_initializer_creates_resources_only_when_requested(
    tmp_path: Path,
) -> None:
    initializer = _load_module(
        "init_skill_focus", SKILL_CREATOR_SCRIPT_DIR / "init_skill.py"
    )

    minimal = initializer.init_skill("minimal-skill", tmp_path)
    assert minimal is not None
    assert {item.name for item in minimal.iterdir()} == {"SKILL.md"}

    examples = initializer.init_skill(
        "example-skill", tmp_path, include_examples=True
    )
    assert examples is not None
    assert {item.name for item in examples.iterdir()} == {
        "SKILL.md",
        "assets",
        "references",
        "scripts",
    }
