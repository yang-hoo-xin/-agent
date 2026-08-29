"""Strict Git identity and read-only admission for sealed product entry."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

GIT_STDERR_MAX_UTF8_BYTES = 512


class GitAdmissionError(RuntimeError):
    """One exact Git admission gate failed without granting product authority."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = dict(diagnostics or {})


@dataclass(frozen=True)
class GitExecutableIdentityV1:
    declared_textual_path: str
    resolved_canonical_path: str
    sha256: str
    size: int
    version: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.declared_textual_path, str)
            or not self.declared_textual_path
            or not isinstance(self.resolved_canonical_path, str)
            or not self.resolved_canonical_path
            or not isinstance(self.sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
            or isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size <= 0
            or not isinstance(self.version, str)
            or not self.version
        ):
            raise ValueError("Git executable identity is invalid.")

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_textual_path": self.declared_textual_path,
            "resolved_canonical_path": self.resolved_canonical_path,
            "sha256": self.sha256,
            "size": self.size,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GitExecutableIdentityV1:
        if set(value) != {
            "declared_textual_path",
            "resolved_canonical_path",
            "sha256",
            "size",
            "version",
        }:
            raise ValueError("Git executable identity shape is invalid.")
        return cls(
            declared_textual_path=value["declared_textual_path"],
            resolved_canonical_path=value["resolved_canonical_path"],
            sha256=value["sha256"],
            size=value["size"],
            version=value["version"],
        )

    @classmethod
    def read(cls, executable: str | Path) -> GitExecutableIdentityV1:
        declared = str(executable)
        selected = Path(executable).resolve(strict=True)
        completed = subprocess.run(
            (str(selected), "--version"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
            env=controlled_git_environment(),
        )
        if completed.returncode != 0:
            raise GitAdmissionError(
                "GIT_EXECUTABLE_VERSION_FAILED",
                "Git executable version query failed.",
                diagnostics={"returncode": completed.returncode},
            )
        return cls(
            declared_textual_path=declared,
            resolved_canonical_path=selected.as_posix(),
            sha256=hashlib.sha256(selected.read_bytes()).hexdigest(),
            size=selected.stat().st_size,
            version=completed.stdout.rstrip("\r\n"),
        )


def controlled_git_environment() -> dict[str, str]:
    """Return the minimal inherited environment for exact read-only Git calls."""

    selected: dict[str, str] = {}
    for key in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT"):
        value = os.environ.get(key)
        if isinstance(value, str) and value:
            selected[key] = value
    selected.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    return selected


def _bounded_stderr(raw: bytes) -> dict[str, object]:
    text = raw.decode("utf-8", errors="replace")
    selected = text.replace("\r", " ").replace("\n", " ")
    selected = re.sub(r"https?://\S+", "[url_redacted]", selected)
    selected = re.sub(
        r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*\S+",
        r"\1=[redacted]",
        selected,
    )
    selected = re.sub(
        r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/][^\"']+",
        "[absolute_path_redacted]",
        selected,
    )
    encoded = selected.encode("utf-8", errors="replace")
    excerpt_bytes = encoded[:GIT_STDERR_MAX_UTF8_BYTES]
    while True:
        try:
            excerpt = excerpt_bytes.decode("utf-8")
            break
        except UnicodeDecodeError:
            excerpt_bytes = excerpt_bytes[:-1]
    return {
        "excerpt": excerpt,
        "source_utf8_bytes": len(raw),
        "excerpt_utf8_bytes": len(excerpt_bytes),
        "max_utf8_bytes": GIT_STDERR_MAX_UTF8_BYTES,
        "truncated": len(encoded) > len(excerpt_bytes),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "absolute_paths_redacted": True,
        "credential_like_values_redacted": True,
    }


def _binding_path(value: object, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GitAdmissionError(
            "SOURCE_BINDING_PATH_INVALID",
            f"Source binding {field} must be a non-empty POSIX path.",
        )
    selected = PurePosixPath(value)
    if selected.is_absolute() or any(part in {"", ".."} for part in selected.parts):
        raise GitAdmissionError(
            "SOURCE_BINDING_PATH_ESCAPE",
            f"Source binding {field} escapes the repository.",
        )
    if value != "." and selected.as_posix() != value:
        raise GitAdmissionError(
            "SOURCE_BINDING_PATH_NOT_NORMALIZED",
            f"Source binding {field} is not normalized.",
        )
    return selected


@dataclass(frozen=True)
class StrictGitAdmission:
    executable_identity: GitExecutableIdentityV1
    source_declared_root: str
    source_canonical_root: str

    def _executable(self) -> str:
        identity = self.executable_identity
        declared = Path(identity.declared_textual_path)
        canonical = Path(identity.resolved_canonical_path)
        if not declared.is_absolute() or not canonical.is_absolute():
            raise GitAdmissionError(
                "GIT_EXECUTABLE_NOT_ABSOLUTE",
                "Git executable identity is not absolute.",
            )
        declared_path = declared.resolve(strict=True)
        canonical_path = canonical.resolve(strict=True)
        if declared_path != canonical_path or not os.path.samefile(
            declared_path, canonical_path
        ):
            raise GitAdmissionError(
                "GIT_EXECUTABLE_PHYSICAL_IDENTITY_DRIFT",
                "Git executable textual and canonical identities drifted.",
            )
        if canonical_path.as_posix() != identity.resolved_canonical_path:
            raise GitAdmissionError(
                "GIT_EXECUTABLE_CANONICAL_SPELLING_DRIFT",
                "Git executable canonical spelling drifted.",
            )
        if hashlib.sha256(canonical_path.read_bytes()).hexdigest() != identity.sha256:
            raise GitAdmissionError(
                "GIT_EXECUTABLE_HASH_DRIFT",
                "Git executable SHA256 drifted.",
            )
        if canonical_path.stat().st_size != identity.size:
            raise GitAdmissionError(
                "GIT_EXECUTABLE_SIZE_DRIFT",
                "Git executable size drifted.",
            )
        completed = subprocess.run(
            (identity.resolved_canonical_path, "--version"),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
            env=controlled_git_environment(),
        )
        if (
            completed.returncode != 0
            or completed.stdout.rstrip("\r\n") != identity.version
        ):
            raise GitAdmissionError(
                "GIT_EXECUTABLE_VERSION_DRIFT",
                "Git executable version drifted.",
                diagnostics={"returncode": completed.returncode},
            )
        return identity.resolved_canonical_path

    def _source_root(self, repository: Path) -> tuple[str, Path]:
        if (
            not isinstance(self.source_declared_root, str)
            or not self.source_declared_root
            or not isinstance(self.source_canonical_root, str)
            or not self.source_canonical_root
        ):
            raise GitAdmissionError(
                "SOURCE_GIT_ROOT_MISSING",
                "Source Git textual or canonical root is missing.",
            )
        if not Path(self.source_declared_root).is_absolute() or not Path(
            self.source_canonical_root
        ).is_absolute():
            raise GitAdmissionError(
                "SOURCE_GIT_ROOT_NOT_ABSOLUTE",
                "Source Git root is not absolute.",
            )
        if any(
            marker in self.source_canonical_root for marker in ("*", "?", "[", "]")
        ):
            raise GitAdmissionError(
                "SOURCE_GIT_SAFE_DIRECTORY_GLOB",
                "Source Git safe.directory contains a glob.",
            )
        if ".." in Path(self.source_declared_root).parts or ".." in Path(
            self.source_canonical_root
        ).parts:
            raise GitAdmissionError(
                "SOURCE_GIT_ROOT_PARENT_TRAVERSAL",
                "Source Git root contains parent traversal.",
            )
        declared = Path(self.source_declared_root).resolve(strict=True)
        canonical = Path(self.source_canonical_root).resolve(strict=True)
        argument = repository.resolve(strict=True)
        if declared != canonical or canonical != argument:
            raise GitAdmissionError(
                "SOURCE_GIT_ROOT_DRIFT",
                "Source Git textual, canonical, and argument roots drifted.",
            )
        if not os.path.samefile(declared, canonical):
            raise GitAdmissionError(
                "SOURCE_GIT_ROOT_NOT_SAMEFILE",
                "Source Git textual and canonical roots are not samefile.",
            )
        if canonical.as_posix() != self.source_canonical_root:
            raise GitAdmissionError(
                "SOURCE_GIT_CANONICAL_SPELLING_DRIFT",
                "Source Git canonical spelling drifted.",
            )
        if not (canonical / ".git").exists():
            raise GitAdmissionError(
                "SOURCE_GIT_MARKER_MISSING",
                "Source Git repository marker is missing.",
            )
        return self.source_canonical_root, canonical

    def _run(
        self,
        command: Sequence[str],
        arguments: Sequence[str],
        *,
        raw: bool,
        controlled_environment: bool,
    ) -> str | bytes:
        try:
            completed = subprocess.run(
                tuple(command),
                capture_output=True,
                text=not raw,
                encoding=None if raw else "utf-8",
                errors=None if raw else "replace",
                check=False,
                timeout=10,
                env=controlled_git_environment() if controlled_environment else None,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitAdmissionError(
                "GIT_COMMAND_UNAVAILABLE",
                "Read-only Git command could not complete.",
                diagnostics={"error_type": type(exc).__name__},
            ) from exc
        stderr = (
            bytes(completed.stderr)
            if raw
            else str(completed.stderr or "").encode("utf-8", errors="replace")
        )
        if completed.returncode != 0:
            raise GitAdmissionError(
                "GIT_COMMAND_FAILED",
                "Read-only Git command returned nonzero.",
                diagnostics={
                    "returncode": completed.returncode,
                    "args": list(arguments),
                    "stderr": _bounded_stderr(stderr),
                },
            )
        if raw:
            return bytes(completed.stdout)
        return str(completed.stdout or "").rstrip("\r\n")

    def _platform_command(self, repository: Path, *arguments: str) -> tuple[str, ...]:
        root = repository.resolve(strict=True)
        return (
            self._executable(),
            "--no-optional-locks",
            "-C",
            str(root),
            *arguments,
        )

    def _source_command(self, repository: Path, *arguments: str) -> tuple[str, ...]:
        canonical_text, _ = self._source_root(repository)
        return (
            self._executable(),
            "-c",
            "safe.directory=",
            "-c",
            f"safe.directory={canonical_text}",
            "--no-optional-locks",
            "-C",
            canonical_text,
            *arguments,
        )

    def platform_text(self, repository: Path, *arguments: str) -> str:
        allowed = {
            ("rev-parse", "HEAD"),
            ("branch", "--show-current"),
        }
        if tuple(arguments) not in allowed:
            raise GitAdmissionError(
                "PLATFORM_GIT_COMMAND_NOT_ALLOWED",
                "Platform Git command is not read-only allowlisted.",
            )
        return str(
            self._run(
                self._platform_command(repository, *arguments),
                arguments,
                raw=False,
                controlled_environment=False,
            )
        )

    def platform_status_raw(self, repository: Path) -> bytes:
        arguments = ("status", "--porcelain=v1", "-z", "--untracked-files=all")
        return bytes(
            self._run(
                self._platform_command(repository, *arguments),
                arguments,
                raw=True,
                controlled_environment=False,
            )
        )

    def verify_platform_code_checkpoint(
        self,
        *,
        repository: Path,
        current_head: str,
        platform_code_checkpoint: str,
        allowed_post_checkpoint_paths: Sequence[str],
    ) -> dict[str, object]:
        """Verify one exact commit and every path touched after it."""

        object_pattern = r"[0-9a-f]{40}|[0-9a-f]{64}"
        if re.fullmatch(object_pattern, current_head) is None:
            raise GitAdmissionError(
                "PLATFORM_CURRENT_HEAD_INVALID",
                "Current platform HEAD is not an exact Git object id.",
            )
        if self.platform_text(repository, "rev-parse", "HEAD") != current_head:
            raise GitAdmissionError(
                "PLATFORM_HEAD_DRIFT",
                "Platform HEAD changed before code-checkpoint verification.",
            )
        if re.fullmatch(object_pattern, platform_code_checkpoint) is None:
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_INVALID",
                "Platform code checkpoint is not an exact Git object id.",
            )
        normalized_allowed: list[str] = []
        for value in allowed_post_checkpoint_paths:
            if not isinstance(value, str) or not value or "\\" in value:
                raise GitAdmissionError(
                    "PLATFORM_CODE_CHECKPOINT_ALLOWED_PATH_INVALID",
                    "An allowed post-checkpoint path is invalid.",
                )
            selected = PurePosixPath(value)
            if (
                not selected.parts
                or selected.is_absolute()
                or any(part in {"", ".", ".."} for part in selected.parts)
                or selected.as_posix() != value
            ):
                raise GitAdmissionError(
                    "PLATFORM_CODE_CHECKPOINT_ALLOWED_PATH_INVALID",
                    "An allowed post-checkpoint path is not normalized.",
                )
            normalized_allowed.append(value)
        if len(normalized_allowed) != len(set(normalized_allowed)):
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_ALLOWED_PATH_DUPLICATE",
                "Allowed post-checkpoint paths contain a duplicate.",
            )

        try:
            resolved = str(
                self._run(
                    self._platform_command(
                        repository,
                        "rev-parse",
                        "--verify",
                        f"{platform_code_checkpoint}^{{commit}}",
                    ),
                    (
                        "rev-parse",
                        "--verify",
                        f"{platform_code_checkpoint}^{{commit}}",
                    ),
                    raw=False,
                    controlled_environment=False,
                )
            )
        except GitAdmissionError as exc:
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_OBJECT_INVALID",
                "Platform code checkpoint does not resolve to an exact commit object.",
                diagnostics={"cause_code": exc.code},
            ) from exc
        if resolved != platform_code_checkpoint:
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_OBJECT_NOT_EXACT_COMMIT",
                "Platform code checkpoint resolves through a different Git object.",
                diagnostics={"resolved_commit": resolved},
            )

        try:
            merge_base = str(
                self._run(
                    self._platform_command(
                        repository,
                        "merge-base",
                        platform_code_checkpoint,
                        current_head,
                    ),
                    ("merge-base", platform_code_checkpoint, current_head),
                    raw=False,
                    controlled_environment=False,
                )
            )
        except GitAdmissionError as exc:
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_NOT_ANCESTOR",
                "Platform code checkpoint is not an ancestor of platform HEAD.",
                diagnostics={"cause_code": exc.code},
            ) from exc
        if merge_base != platform_code_checkpoint:
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_NOT_ANCESTOR",
                "Platform code checkpoint is not an ancestor of platform HEAD.",
                diagnostics={"merge_base": merge_base},
            )

        revision_text = str(
            self._run(
                self._platform_command(
                    repository,
                    "rev-list",
                    "--reverse",
                    f"{platform_code_checkpoint}..{current_head}",
                ),
                (
                    "rev-list",
                    "--reverse",
                    f"{platform_code_checkpoint}..{current_head}",
                ),
                raw=False,
                controlled_environment=False,
            )
        )
        commits = tuple(line for line in revision_text.splitlines() if line)
        if any(re.fullmatch(object_pattern, item) is None for item in commits):
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_REVISION_LIST_INVALID",
                "Post-checkpoint revision list contains an invalid object id.",
            )

        touched: set[str] = set()
        for commit in commits:
            raw_paths = bytes(
                self._run(
                    self._platform_command(
                        repository,
                        "diff-tree",
                        "--root",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        "-m",
                        "-z",
                        commit,
                    ),
                    (
                        "diff-tree",
                        "--root",
                        "--no-commit-id",
                        "--name-only",
                        "-r",
                        "-m",
                        "-z",
                        commit,
                    ),
                    raw=True,
                    controlled_environment=False,
                )
            )
            if raw_paths and not raw_paths.endswith(b"\0"):
                raise GitAdmissionError(
                    "PLATFORM_CODE_CHECKPOINT_PATH_OUTPUT_INVALID",
                    "Post-checkpoint path output is not NUL terminated.",
                )
            for raw_path in raw_paths.split(b"\0"):
                if not raw_path:
                    continue
                try:
                    path_text = raw_path.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise GitAdmissionError(
                        "PLATFORM_CODE_CHECKPOINT_PATH_ENCODING_INVALID",
                        "A post-checkpoint path is not valid UTF-8.",
                    ) from exc
                selected = PurePosixPath(path_text)
                if (
                    not selected.parts
                    or selected.is_absolute()
                    or any(part in {"", ".", ".."} for part in selected.parts)
                    or selected.as_posix() != path_text
                ):
                    raise GitAdmissionError(
                        "PLATFORM_CODE_CHECKPOINT_PATH_INVALID",
                        "A post-checkpoint path is not normalized.",
                    )
                touched.add(path_text)

        unauthorized = sorted(
            touched.difference(normalized_allowed),
            key=lambda item: item.encode("utf-8"),
        )
        if unauthorized:
            raise GitAdmissionError(
                "PLATFORM_CODE_CHECKPOINT_UNAUTHORIZED_PATH",
                "A post-checkpoint commit touched a path outside the typed allowance.",
                diagnostics={"unauthorized_paths": unauthorized},
            )
        return {
            "platform_HEAD": current_head,
            "platform_code_checkpoint": platform_code_checkpoint,
            "exact_commit_object": True,
            "ancestor_of_platform_HEAD": True,
            "allowed_post_checkpoint_paths": list(normalized_allowed),
            "post_checkpoint_commits": list(commits),
            "observed_post_checkpoint_paths": sorted(
                touched,
                key=lambda item: item.encode("utf-8"),
            ),
            "only_allowed_post_checkpoint_paths": True,
        }

    def source_text(self, repository: Path, *arguments: str) -> str:
        project_prefix = "HEAD:"
        allowed = {
            ("rev-parse", "--show-toplevel"),
            ("rev-parse", "HEAD"),
            ("rev-parse", "HEAD^{tree}"),
            ("ls-tree", "-r", "--name-only", "HEAD"),
        }
        selected = tuple(arguments)
        if selected not in allowed and not (
            len(selected) == 2
            and selected[0] == "rev-parse"
            and selected[1].startswith(project_prefix)
            and selected[1] != project_prefix
        ):
            raise GitAdmissionError(
                "SOURCE_GIT_COMMAND_NOT_ALLOWED",
                "Source Git command is not read-only allowlisted.",
            )
        if "config" in selected or "--global" in selected:
            raise GitAdmissionError(
                "SOURCE_GIT_CONFIG_FORBIDDEN",
                "Source Git configuration command is forbidden.",
            )
        return str(
            self._run(
                self._source_command(repository, *arguments),
                arguments,
                raw=False,
                controlled_environment=True,
            )
        )

    def source_status_raw(self, repository: Path, project_root: PurePosixPath) -> bytes:
        arguments = (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            project_root.as_posix(),
        )
        return bytes(
            self._run(
                self._source_command(repository, *arguments),
                arguments,
                raw=True,
                controlled_environment=True,
            )
        )

    def verify_platform(
        self,
        *,
        repository: Path,
        expected_head: str,
        expected_branch: str,
        allowed_dirty_paths: Sequence[str],
    ) -> dict[str, object]:
        if self.platform_text(repository, "rev-parse", "HEAD") != expected_head:
            raise GitAdmissionError(
                "PLATFORM_HEAD_DRIFT",
                "Platform HEAD drifted.",
            )
        if (
            self.platform_text(repository, "branch", "--show-current")
            != expected_branch
        ):
            raise GitAdmissionError(
                "PLATFORM_BRANCH_DRIFT",
                "Platform branch drifted.",
            )
        records = validate_platform_porcelain_v1_z(
            self.platform_status_raw(repository), allowed_dirty_paths
        )
        return {
            "head": expected_head,
            "branch": expected_branch,
            "dirty_records": [dict(item) for item in records],
        }

    def verify_source_revision_binding(
        self,
        *,
        source: Path,
        snapshot: Sequence[Mapping[str, Any]],
        snapshot_sha256: str,
        binding: Mapping[str, Any],
    ) -> dict[str, object]:
        required_fields = {
            "binding_version",
            "complete_snapshot_sha256",
            "repository_head",
            "repository_tree",
            "project_root",
            "project_file",
            "project_tree",
            "primary_sources",
        }
        if set(binding) != required_fields or binding.get("binding_version") != (
            "product_source_revision_binding_v2"
        ):
            raise GitAdmissionError(
                "SOURCE_BINDING_SHAPE_INVALID",
                "Strict Git admission requires product_source_revision_binding_v2.",
            )
        if binding.get("complete_snapshot_sha256") != snapshot_sha256:
            raise GitAdmissionError(
                "SOURCE_SNAPSHOT_BINDING_DRIFT",
                "Canonical source snapshot SHA256 does not match binding.",
            )
        canonical_text, repository = self._source_root(Path(self.source_canonical_root))
        resolved_source = source.resolve(strict=True)
        project_root = _binding_path(binding.get("project_root"), "project_root")
        project_path = (
            repository
            if project_root.as_posix() == "."
            else (repository / Path(*project_root.parts)).resolve(strict=True)
        )
        if project_path != resolved_source or not os.path.samefile(
            project_path, resolved_source
        ):
            raise GitAdmissionError(
                "SOURCE_PROJECT_ROOT_DRIFT",
                "Source binding project_root does not equal selected source.",
            )
        discovered_text = self.source_text(repository, "rev-parse", "--show-toplevel")
        if discovered_text != canonical_text or not os.path.samefile(
            Path(discovered_text).resolve(strict=True), repository
        ):
            raise GitAdmissionError(
                "SOURCE_GIT_TOPLEVEL_DRIFT",
                "Source Git show-toplevel does not equal packet root.",
            )
        head = self.source_text(repository, "rev-parse", "HEAD")
        repository_tree = self.source_text(repository, "rev-parse", "HEAD^{tree}")
        project_tree = (
            repository_tree
            if project_root.as_posix() == "."
            else self.source_text(
                repository, "rev-parse", f"HEAD:{project_root.as_posix()}"
            )
        )
        if head != binding.get("repository_head"):
            raise GitAdmissionError("SOURCE_HEAD_DRIFT", "Source repository HEAD drifted.")
        if repository_tree != binding.get("repository_tree"):
            raise GitAdmissionError(
                "SOURCE_REPOSITORY_TREE_DRIFT",
                "Source repository tree drifted.",
            )
        if project_tree != binding.get("project_tree"):
            raise GitAdmissionError(
                "SOURCE_PROJECT_TREE_DRIFT",
                "Source project tree drifted.",
            )
        if self.source_status_raw(repository, project_root):
            raise GitAdmissionError(
                "SOURCE_PROJECT_DIRTY",
                "Source project subtree is not clean.",
            )
        project_file = _binding_path(binding.get("project_file"), "project_file")
        tracked = set(
            self.source_text(repository, "ls-tree", "-r", "--name-only", "HEAD")
            .splitlines()
        )
        if project_file.as_posix() not in tracked:
            raise GitAdmissionError(
                "SOURCE_PROJECT_FILE_UNTRACKED",
                "Source binding project_file is not tracked at HEAD.",
            )
        snapshot_by_path = {
            str(item.get("path")): item
            for item in snapshot
            if isinstance(item, Mapping) and item.get("path")
        }
        project_file_path = (repository / Path(*project_file.parts)).resolve(strict=True)
        try:
            project_file_relative = project_file_path.relative_to(resolved_source).as_posix()
        except ValueError as exc:
            raise GitAdmissionError(
                "SOURCE_PROJECT_FILE_ESCAPE",
                "Source binding project_file escapes project_root.",
            ) from exc
        if (
            project_file_relative not in snapshot_by_path
            or project_file_path.suffix.casefold() != ".csproj"
        ):
            raise GitAdmissionError(
                "SOURCE_PROJECT_FILE_MISSING",
                "Source binding project_file is absent from snapshot.",
            )
        primary_sources = binding.get("primary_sources")
        if not isinstance(primary_sources, list) or not primary_sources:
            raise GitAdmissionError(
                "SOURCE_PRIMARY_SOURCES_MISSING",
                "Source binding requires primary_sources.",
            )
        seen: set[str] = set()
        for item in primary_sources:
            if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
                raise GitAdmissionError(
                    "SOURCE_PRIMARY_SOURCE_SHAPE_INVALID",
                    "Source binding primary source shape is invalid.",
                )
            selected = _binding_path(item.get("path"), "primary_sources.path")
            selected_text = selected.as_posix()
            if selected_text in seen or selected_text not in tracked:
                raise GitAdmissionError(
                    "SOURCE_PRIMARY_SOURCE_IDENTITY_INVALID",
                    "Source binding primary source identity is invalid.",
                )
            seen.add(selected_text)
            selected_path = (repository / Path(*selected.parts)).resolve(strict=True)
            try:
                relative = selected_path.relative_to(resolved_source).as_posix()
            except ValueError as exc:
                raise GitAdmissionError(
                    "SOURCE_PRIMARY_SOURCE_ESCAPE",
                    "Source binding primary source escapes project_root.",
                ) from exc
            snapshot_entry = snapshot_by_path.get(relative)
            if snapshot_entry is None or snapshot_entry.get("sha256") != item.get(
                "sha256"
            ):
                raise GitAdmissionError(
                    "SOURCE_PRIMARY_SOURCE_HASH_DRIFT",
                    "Source binding primary source SHA256 changed.",
                )
        return {
            "repository_root": canonical_text,
            "repository_head": head,
            "repository_tree": repository_tree,
            "project_root": project_root.as_posix(),
            "project_tree": project_tree,
            "snapshot_sha256": snapshot_sha256,
        }


def validate_platform_porcelain_v1_z(
    raw: bytes, allowed_dirty_paths: Sequence[str]
) -> tuple[dict[str, str], ...]:
    """Parse Git porcelain v1 -z without stripping fixed-width status bytes."""

    if not isinstance(raw, bytes):
        raise GitAdmissionError(
            "PLATFORM_STATUS_NOT_RAW",
            "Platform porcelain status is not raw bytes.",
        )
    if not raw:
        return ()
    if not raw.endswith(b"\0"):
        raise GitAdmissionError(
            "PLATFORM_STATUS_NUL_MISSING",
            "Platform porcelain status lacks terminal NUL.",
        )
    allowed = set(allowed_dirty_paths)
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in raw[:-1].split(b"\0"):
        if len(record) < 4 or record[2:3] != b" ":
            raise GitAdmissionError(
                "PLATFORM_STATUS_RECORD_MALFORMED",
                "Platform porcelain status record is malformed.",
            )
        index_status = chr(record[0])
        worktree_status = chr(record[1])
        try:
            path = record[3:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise GitAdmissionError(
                "PLATFORM_STATUS_PATH_ENCODING_INVALID",
                "Platform porcelain path is not UTF-8.",
            ) from exc
        if (
            not path
            or path.startswith('"')
            or path.endswith('"')
            or "\\" in path
            or index_status in {"R", "C"}
            or worktree_status in {"R", "C"}
        ):
            raise GitAdmissionError(
                "PLATFORM_STATUS_PATH_AMBIGUOUS",
                "Platform rename, copy, quoted, or ambiguous path is forbidden.",
            )
        if path in seen:
            raise GitAdmissionError(
                "PLATFORM_STATUS_PATH_DUPLICATE",
                "Platform porcelain path is duplicated.",
            )
        seen.add(path)
        if index_status == "?" or worktree_status == "?":
            if (index_status, worktree_status) != ("?", "?"):
                raise GitAdmissionError(
                    "PLATFORM_STATUS_UNTRACKED_AMBIGUOUS",
                    "Platform untracked status is ambiguous.",
                )
            kind = "untracked"
        else:
            if index_status != " ":
                raise GitAdmissionError(
                    "PLATFORM_STAGED_CHANGE",
                    "Platform staged change exists.",
                )
            if worktree_status != "M":
                raise GitAdmissionError(
                    "PLATFORM_WORKTREE_STATUS_UNSUPPORTED",
                    "Platform worktree status is unsupported.",
                )
            kind = "modified"
        if path not in allowed:
            raise GitAdmissionError(
                "PLATFORM_DIRTY_PATH_UNEXPECTED",
                f"Unexpected platform {kind} path.",
                diagnostics={"path_sha256": hashlib.sha256(path.encode()).hexdigest()},
            )
        selected.append({"status": index_status + worktree_status, "path": path})
    return tuple(selected)
