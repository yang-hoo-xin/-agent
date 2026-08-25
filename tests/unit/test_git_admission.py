from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from src.mod_agent.git.admission import (
    GitAdmissionError,
    GitExecutableIdentityV1,
    StrictGitAdmission,
    _bounded_stderr,
    controlled_git_environment,
    validate_platform_porcelain_v1_z,
)
from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256


def _git_executable() -> Path:
    value = shutil.which("git")
    assert value is not None
    return Path(value).resolve()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        (str(_git_executable()), "-C", str(root), *args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout.rstrip("\r\n")


def _repository(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    root = tmp_path / "source"
    project = root / "Example"
    project.mkdir(parents=True)
    _git(root.parent, "init", str(root))
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_text("bin/\nobj/\n", encoding="utf-8")
    (project / "Example.csproj").write_text("<Project />\n", encoding="utf-8")
    (project / "Loader.cs").write_text("sealed class Loader {}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    snapshot = source_snapshot(project)
    binding: dict[str, object] = {
        "binding_version": "product_source_revision_binding_v2",
        "complete_snapshot_sha256": source_snapshot_sha256(snapshot),
        "repository_head": _git(root, "rev-parse", "HEAD"),
        "repository_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "project_root": "Example",
        "project_file": "Example/Example.csproj",
        "project_tree": _git(root, "rev-parse", "HEAD:Example"),
        "primary_sources": [
            {
                "path": "Example/Loader.cs",
                "sha256": hashlib.sha256((project / "Loader.cs").read_bytes()).hexdigest(),
            }
        ],
    }
    return root, project, binding


def _admission(root: Path) -> StrictGitAdmission:
    identity = GitExecutableIdentityV1.read(_git_executable())
    return StrictGitAdmission(
        executable_identity=identity,
        source_declared_root=root.as_posix(),
        source_canonical_root=root.resolve().as_posix(),
    )


def test_porcelain_raw_accepts_allowed_wip_without_losing_leading_status() -> None:
    allowed = (
        "docs/ARCHITECTURE_OVERVIEW.md",
        "docs/LOCAL_MODEL_COMPARATIVE_EVALUATION_EXPERIMENT.md",
    )
    raw = (
        b" M docs/ARCHITECTURE_OVERVIEW.md\0"
        b"?? docs/LOCAL_MODEL_COMPARATIVE_EVALUATION_EXPERIMENT.md\0"
    )

    assert validate_platform_porcelain_v1_z(raw, allowed) == (
        {"status": " M", "path": allowed[0]},
        {"status": "??", "path": allowed[1]},
    )


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"M  docs/ARCHITECTURE_OVERVIEW.md\0", "PLATFORM_STAGED_CHANGE"),
        (b"?? docs/UNEXPECTED.md\0", "PLATFORM_DIRTY_PATH_UNEXPECTED"),
        (b"R  docs/new.md\0docs/old.md\0", "PLATFORM_STATUS_PATH_AMBIGUOUS"),
        (b"C  docs/new.md\0docs/old.md\0", "PLATFORM_STATUS_PATH_AMBIGUOUS"),
        (b' M "docs/value.md"\0', "PLATFORM_STATUS_PATH_AMBIGUOUS"),
        (b"?M docs/value.md\0", "PLATFORM_STATUS_UNTRACKED_AMBIGUOUS"),
        (b" M docs/value.md", "PLATFORM_STATUS_NUL_MISSING"),
    ],
)
def test_porcelain_raw_fails_closed(raw: bytes, code: str) -> None:
    with pytest.raises(GitAdmissionError) as raised:
        validate_platform_porcelain_v1_z(raw, ("docs/ARCHITECTURE_OVERVIEW.md",))

    assert raised.value.code == code


def test_strict_source_git_verifies_dynamic_project_root(tmp_path: Path) -> None:
    root, project, binding = _repository(tmp_path)
    snapshot = source_snapshot(project)
    admission = _admission(root)
    assert admission.source_status_raw(root, PurePosixPath("Example")) == b""

    result = admission.verify_source_revision_binding(
        source=project,
        snapshot=snapshot,
        snapshot_sha256=source_snapshot_sha256(snapshot),
        binding=binding,
    )

    assert result["project_root"] == "Example"
    assert result["project_tree"] == binding["project_tree"]
    assert result["repository_head"] == binding["repository_head"]


@pytest.mark.parametrize("value", ["", "relative/source", "*", "../source"])
def test_strict_source_git_rejects_unbound_roots(tmp_path: Path, value: str) -> None:
    root, _, _ = _repository(tmp_path)
    identity = GitExecutableIdentityV1.read(_git_executable())
    admission = StrictGitAdmission(identity, value, value)

    with pytest.raises((GitAdmissionError, OSError)):
        admission.source_text(root, "rev-parse", "HEAD")


def test_source_and_platform_git_argv_and_environment_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _repository(tmp_path)
    admission = _admission(root)
    commands: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    monkeypatch.setattr(StrictGitAdmission, "_executable", lambda self: self.executable_identity.resolved_canonical_path)

    def run(command, **kwargs):
        commands.append((tuple(command), kwargs.get("env")))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)

    assert admission.platform_text(root, "rev-parse", "HEAD") == "ok"
    assert admission.source_text(root, "rev-parse", "HEAD") == "ok"
    platform, source = commands
    assert not any(part.startswith("safe.directory=") for part in platform[0])
    assert source[0][1:8] == (
        "-c",
        "safe.directory=",
        "-c",
        f"safe.directory={root.resolve().as_posix()}",
        "--no-optional-locks",
        "-C",
        root.resolve().as_posix(),
    )
    assert source[1] is not None
    assert "PATH" not in source[1]
    assert "HOME" not in source[1]
    assert "USERPROFILE" not in source[1]


def test_nonzero_git_retains_bounded_redacted_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = _repository(tmp_path)
    admission = _admission(root)
    monkeypatch.setattr(StrictGitAdmission, "_executable", lambda self: self.executable_identity.resolved_canonical_path)

    def run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=128,
            stdout="",
            stderr="fatal token=SECRET_VALUE " + "界" * 300,
        )

    monkeypatch.setattr(subprocess, "run", run)

    with pytest.raises(GitAdmissionError) as raised:
        admission.platform_text(root, "rev-parse", "HEAD")

    diagnostic = raised.value.diagnostics
    assert diagnostic["returncode"] == 128
    stderr = diagnostic["stderr"]
    assert stderr["excerpt_utf8_bytes"] <= 512
    assert stderr["truncated"] is True
    assert "SECRET_VALUE" not in stderr["excerpt"]


def test_controlled_environment_does_not_inherit_git_or_user_paths() -> None:
    environment = controlled_git_environment()

    assert "PATH" not in environment
    assert "HOME" not in environment
    assert "USERPROFILE" not in environment
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"


def test_git_stderr_redacts_absolute_path() -> None:
    diagnostic = _bounded_stderr(b'fatal: cannot access "C:\\Sensitive\\repo"')

    assert "Sensitive" not in diagnostic["excerpt"]
    assert diagnostic["absolute_paths_redacted"] is True
