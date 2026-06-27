"""Tests for read-only Git audit integration."""

from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.git import GitCommandError, GitRepository

GIT = shutil.which("git")


def _git(repo: Path, *args: str) -> str:
    if GIT is None:
        pytest.skip("git executable is not available on PATH")
    result = subprocess.run(
        (GIT, *args),
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _repo_with_commit(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Controlled Agent")
    _git(repo, "config", "user.email", "agent@example.test")
    source = repo / "plugin.cs"
    source.write_text("public class Plugin {}\n", encoding="utf-8")
    _git(repo, "add", "plugin.cs")
    _git(repo, "commit", "-m", "add plugin skeleton")
    return repo


def _fake_git_command(tmp_path: Path) -> tuple[tuple[str, str], Path]:
    repo = tmp_path / "fake_repo"
    repo.mkdir()
    script = tmp_path / "fake_git.py"
    script.write_text(
        """
from __future__ import annotations

import sys

args = sys.argv[1:]
commit = "a" * 40
if args == ["rev-parse", "--is-inside-work-tree"]:
    print("true")
elif args[:1] == ["show"] and "-s" in args:
    fields = [
        commit,
        "aaaaaaa",
        "add plugin skeleton",
        "2026-06-27T12:00:00+08:00",
        "Controlled Agent",
        "agent@example.test",
    ]
    sys.stdout.write(chr(0).join(fields) + "\\n")
elif args == ["branch", "--show-current"]:
    print("main")
elif args[:1] == ["diff-tree"]:
    print("plugin.cs")
elif args[:1] == ["show"] and "--patch" in args:
    print("diff --git a/plugin.cs b/plugin.cs")
    print("+public class Plugin {}")
else:
    sys.stderr.write("unexpected git args: " + repr(args))
    sys.exit(2)
""",
        encoding="utf-8",
    )
    return (sys.executable, str(script)), repo


def test_non_repo_reports_false_and_blocks_commit_metadata(tmp_path: Path) -> None:
    repository = GitRepository(tmp_path, git_executable=GIT or "git")

    assert repository.is_repo() is False
    with pytest.raises(GitCommandError):
        repository.current_commit()


def test_injected_git_command_builds_record_and_persists_artifact(tmp_path: Path) -> None:
    git_command, repo = _fake_git_command(tmp_path)
    repository = GitRepository(repo, git_executable=git_command)
    store = ArtifactStore(tmp_path / "artifacts")

    record = repository.build_change_record(
        run_id="run_001",
        feature_id="feature_001",
        stage="build",
    )
    ref = repository.write_change_record(
        store,
        run_id="run_001",
        feature_id="feature_001",
        stage="build",
    )

    assert repository.is_repo() is True
    assert record.commit.branch == "main"
    assert record.changed_files == ("plugin.cs",)
    assert record.replay_command == f"git show --patch {record.commit.commit_sha}"
    assert record.rollback_hint == f"git revert {record.commit.commit_sha}"
    envelope = store.read(ref)
    assert envelope["artifact_type"] == "git_change_record"
    assert envelope["producer_stage"] == "git_audit"
    assert envelope["data"]["commit_sha"] == "a" * 40
    assert envelope["data"]["changed_files"] == ["plugin.cs"]


def test_current_commit_returns_stable_metadata(tmp_path: Path) -> None:
    if GIT is None:
        pytest.skip("git executable is not available on PATH")
    repository = GitRepository(_repo_with_commit(tmp_path))

    commit = repository.current_commit()

    assert len(commit.commit_sha) == 40
    assert commit.short_sha
    assert commit.subject == "add plugin skeleton"
    assert commit.author_name == "Controlled Agent"
    assert commit.author_email == "agent@example.test"


def test_changed_files_and_patch_are_read_without_applying_changes(tmp_path: Path) -> None:
    if GIT is None:
        pytest.skip("git executable is not available on PATH")
    repository = GitRepository(_repo_with_commit(tmp_path))

    assert repository.changed_files() == ("plugin.cs",)
    patch = repository.patch_for_commit()
    assert "diff --git" in patch
    assert "+public class Plugin {}" in patch


def test_build_change_record_binds_workflow_artifacts_to_commit(tmp_path: Path) -> None:
    if GIT is None:
        pytest.skip("git executable is not available on PATH")
    repo = _repo_with_commit(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    decision = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload={
            "node_name": "create_implementation_plan",
            "stage": "implementation_plan",
            "message": "stub",
        },
    )
    patch = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload={
            "node_name": "generate_patch_proposal",
            "stage": "patch_proposal",
            "message": "stub",
        },
        upstream_refs=[decision],
    )

    record = GitRepository(repo).build_change_record(
        run_id="run_001",
        feature_id="feature_001",
        stage="dry_run_apply",
        decision_artifact_ref=decision,
        patch_artifact_ref=patch,
    )

    assert record.run_id == "run_001"
    assert record.feature_id == "feature_001"
    assert record.stage == "dry_run_apply"
    assert record.decision_artifact_ref == decision.path
    assert record.patch_artifact_ref == patch.path
    assert record.changed_files == ("plugin.cs",)
    assert record.replay_command == f"git show --patch {record.commit.commit_sha}"
    assert record.rollback_hint == f"git revert {record.commit.commit_sha}"
    assert record.to_artifact_payload()["commit_sha"] == record.commit.commit_sha


def test_write_change_record_persists_artifact_contract(tmp_path: Path) -> None:
    if GIT is None:
        pytest.skip("git executable is not available on PATH")
    repo = _repo_with_commit(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")

    ref = GitRepository(repo).write_change_record(
        store,
        run_id="run_001",
        feature_id="feature_001",
        stage="build",
    )

    envelope = store.read(ref)
    assert envelope["artifact_type"] == "git_change_record"
    assert envelope["producer_stage"] == "git_audit"
    assert envelope["data"]["changed_files"] == ["plugin.cs"]
    assert envelope["data"]["rollback_hint"].startswith("git revert ")
