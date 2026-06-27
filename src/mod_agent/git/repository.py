"""Read-only Git integration for workflow audit and replay records."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.mod_agent.artifacts import ArtifactRef, ArtifactStore


class GitCommandError(RuntimeError):
    """Raised when a Git command required for audit metadata fails."""

    def __init__(
        self,
        *,
        command: tuple[str, ...],
        cwd: Path,
        returncode: int,
        stderr: str,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.returncode = returncode
        self.stderr = stderr.strip()
        message = (
            f"Git command failed in {cwd}: {' '.join(command)} "
            f"(exit {returncode})"
        )
        if self.stderr:
            message = f"{message}: {self.stderr}"
        super().__init__(message)


@dataclass(frozen=True)
class GitCommitRef:
    """Stable metadata for one Git commit."""

    commit_sha: str
    short_sha: str
    branch: str
    subject: str
    committed_at: str
    author_name: str
    author_email: str

    def to_dict(self) -> dict[str, str]:
        """Return JSON-serializable commit metadata."""

        return {
            "commit_sha": self.commit_sha,
            "short_sha": self.short_sha,
            "branch": self.branch,
            "subject": self.subject,
            "committed_at": self.committed_at,
            "author_name": self.author_name,
            "author_email": self.author_email,
        }


@dataclass(frozen=True)
class GitChangeRecord:
    """Bind a workflow decision and code change to one Git commit."""

    record_id: str
    run_id: str
    feature_id: str
    stage: str
    decision_artifact_ref: str | None
    patch_artifact_ref: str | None
    commit: GitCommitRef
    changed_files: tuple[str, ...]
    replay_command: str
    rollback_hint: str

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the git_change_record artifact contract."""

        return {
            "node_name": "git_change_recorder",
            "stage": self.stage,
            "message": (
                f"Recorded Git commit {self.commit.short_sha} for workflow stage "
                f"{self.stage}."
            ),
            "record_id": self.record_id,
            "run_id": self.run_id,
            "feature_id": self.feature_id,
            "decision_artifact_ref": self.decision_artifact_ref,
            "patch_artifact_ref": self.patch_artifact_ref,
            "commit_sha": self.commit.commit_sha,
            "commit": self.commit.to_dict(),
            "changed_files": list(self.changed_files),
            "replay_command": self.replay_command,
            "rollback_hint": self.rollback_hint,
        }


class GitRepository:
    """Read Git metadata without mutating repository history or files."""

    def __init__(
        self,
        root: str | Path = ".",
        git_executable: str | tuple[str, ...] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.git_command = self._resolve_git_command(git_executable)

    def is_repo(self) -> bool:
        """Return whether root is inside a Git working tree."""

        result = self._run("rev-parse", "--is-inside-work-tree", check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def current_commit(self) -> GitCommitRef:
        """Return metadata for HEAD."""

        return self.commit_metadata("HEAD")

    def commit_metadata(self, ref: str = "HEAD") -> GitCommitRef:
        """Return stable metadata for a commit-ish reference."""

        self._require_repo()
        result = self._run(
            "show",
            "-s",
            "--format=%H%x00%h%x00%s%x00%cI%x00%an%x00%ae",
            ref,
        )
        parts = result.stdout.rstrip("\n").split("\x00")
        if len(parts) != 6:
            raise GitCommandError(
                command=("git", "show", "-s", ref),
                cwd=self.root,
                returncode=1,
                stderr=f"Unexpected git metadata format for {ref!r}",
            )
        branch = self._run("branch", "--show-current", check=False).stdout.strip()
        return GitCommitRef(
            commit_sha=parts[0],
            short_sha=parts[1],
            branch=branch,
            subject=parts[2],
            committed_at=parts[3],
            author_name=parts[4],
            author_email=parts[5],
        )

    def changed_files(self, ref: str = "HEAD") -> tuple[str, ...]:
        """Return files changed by a commit, including root commits."""

        self._require_repo()
        commit = self.commit_metadata(ref)
        result = self._run(
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "--root",
            commit.commit_sha,
        )
        files = tuple(line for line in result.stdout.splitlines() if line)
        return files

    def patch_for_commit(self, ref: str = "HEAD") -> str:
        """Return the patch text for a commit without applying it."""

        self._require_repo()
        commit = self.commit_metadata(ref)
        return self._run(
            "show",
            "--format=",
            "--patch",
            "--find-renames",
            commit.commit_sha,
        ).stdout

    def build_change_record(
        self,
        *,
        run_id: str,
        feature_id: str,
        stage: str,
        decision_artifact_ref: "ArtifactRef | None" = None,
        patch_artifact_ref: "ArtifactRef | None" = None,
        commit_ref: str = "HEAD",
    ) -> GitChangeRecord:
        """Create an auditable binding between workflow artifacts and a commit."""

        commit = self.commit_metadata(commit_ref)
        changed_files = self.changed_files(commit.commit_sha)
        decision_path = self._artifact_path(decision_artifact_ref)
        patch_path = self._artifact_path(patch_artifact_ref)
        replay_command = f"git show --patch {commit.commit_sha}"
        rollback_hint = f"git revert {commit.commit_sha}"
        record_seed = {
            "run_id": run_id,
            "feature_id": feature_id,
            "stage": stage,
            "decision_artifact_ref": decision_path,
            "patch_artifact_ref": patch_path,
            "commit_sha": commit.commit_sha,
            "changed_files": changed_files,
        }
        record_id = hashlib.sha256(
            json.dumps(record_seed, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return GitChangeRecord(
            record_id=record_id,
            run_id=run_id,
            feature_id=feature_id,
            stage=stage,
            decision_artifact_ref=decision_path,
            patch_artifact_ref=patch_path,
            commit=commit,
            changed_files=changed_files,
            replay_command=replay_command,
            rollback_hint=rollback_hint,
        )

    def write_change_record(
        self,
        artifact_store: "ArtifactStore",
        *,
        run_id: str,
        feature_id: str,
        stage: str,
        decision_artifact_ref: "ArtifactRef | None" = None,
        patch_artifact_ref: "ArtifactRef | None" = None,
        commit_ref: str = "HEAD",
    ) -> "ArtifactRef":
        """Persist a git_change_record artifact for dashboard, eval, and replay."""

        record = self.build_change_record(
            run_id=run_id,
            feature_id=feature_id,
            stage=stage,
            decision_artifact_ref=decision_artifact_ref,
            patch_artifact_ref=patch_artifact_ref,
            commit_ref=commit_ref,
        )
        upstream_refs = [
            ref
            for ref in (decision_artifact_ref, patch_artifact_ref)
            if ref is not None
        ]
        return artifact_store.write(
            feature_id=feature_id,
            artifact_type="git_change_record",
            payload=record.to_artifact_payload(),
            upstream_refs=upstream_refs,
        )

    def _require_repo(self) -> None:
        if not self.is_repo():
            raise GitCommandError(
                command=("git", "rev-parse", "--is-inside-work-tree"),
                cwd=self.root,
                returncode=128,
                stderr="Not inside a Git working tree",
            )

    def _run(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = (*self.git_command, *args)
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError:
            result = subprocess.CompletedProcess(
                command,
                127,
                "",
                f"Git executable not found: {self.git_command[0]}",
            )
        if check and result.returncode != 0:
            raise GitCommandError(
                command=command,
                cwd=self.root,
                returncode=result.returncode,
                stderr=result.stderr,
            )
        return result

    @staticmethod
    def _artifact_path(ref: "ArtifactRef | None") -> str | None:
        return None if ref is None else ref.path

    @staticmethod
    def _resolve_git_command(
        git_executable: str | tuple[str, ...] | None,
    ) -> tuple[str, ...]:
        if isinstance(git_executable, tuple):
            return git_executable
        if isinstance(git_executable, str):
            return (git_executable,)
        discovered = shutil.which("git")
        if discovered:
            return (discovered,)
        return ("git",)
