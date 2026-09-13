"""Deterministic source discovery for Knowledge Base ingestion."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DISCOVERY_EXTENSIONS = frozenset(
    {".cs", ".py", ".json", ".yaml", ".yml", ".md", ".txt", ".log", ".png", ".jpg", ".jpeg"}
)
DEFAULT_IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".venv",
        "__pycache__",
        "bin",
        "generated",
        "node_modules",
        "obj",
        "venv",
    }
)
DEFAULT_IGNORED_FILE_PATTERNS = frozenset({"*.pyc", "*.pyo", "*.tmp", ".env"})


class SourceDiscoveryError(ValueError):
    """Raised when source discovery cannot safely scan a root."""


@dataclass(frozen=True)
class DiscoveredSourceFile:
    """One safely discovered file with stable identity and content hash."""

    source_id: str
    source_type: str
    source_path: str
    relative_path: str
    content_hash: str
    size_bytes: int
    mtime: float


class SourceDiscovery:
    """Discover indexable files and classify them by evidence source type."""

    def __init__(
        self,
        *,
        allowed_extensions: frozenset[str] = DEFAULT_DISCOVERY_EXTENSIONS,
        ignored_dir_names: frozenset[str] = DEFAULT_IGNORED_DIR_NAMES,
        ignored_file_patterns: frozenset[str] = DEFAULT_IGNORED_FILE_PATTERNS,
        include_generated_mods: bool = False,
    ) -> None:
        self.allowed_extensions = normalize_extensions(allowed_extensions)
        self.ignored_dir_names = frozenset(ignored_dir_names)
        self.ignored_file_patterns = frozenset(ignored_file_patterns)
        self.include_generated_mods = include_generated_mods

    @classmethod
    def from_config(
        cls,
        settings_path: str | Path,
        *,
        include_generated_mods: bool | None = None,
    ) -> "SourceDiscovery":
        """Build discovery settings from config/settings.yaml."""

        path = Path(settings_path).resolve()
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        knowledge = data.get("knowledge", {})
        safety = data.get("safety", {})
        extensions = knowledge.get("indexable_extensions", DEFAULT_DISCOVERY_EXTENSIONS)
        generated_access = safety.get("generated_mods_access")
        allow_generated = (
            include_generated_mods
            if include_generated_mods is not None
            else generated_access == "allowed"
        )
        return cls(
            allowed_extensions=frozenset(str(extension) for extension in extensions),
            include_generated_mods=bool(allow_generated),
        )

    def discover(self, roots: list[Path]) -> list[DiscoveredSourceFile]:
        """Return stable discovered source file records for the provided roots."""

        records: list[DiscoveredSourceFile] = []
        for root in roots:
            root_path = Path(root).resolve()
            if not root_path.exists():
                raise SourceDiscoveryError(f"Source discovery root does not exist: {root_path}")
            if not root_path.is_dir():
                raise SourceDiscoveryError(f"Source discovery root is not a directory: {root_path}")
            if self._is_blocked_generated_mods_root(root_path):
                continue
            for path in iter_indexable_paths(
                root=root_path,
                allowed_extensions=self.allowed_extensions,
                ignored_dir_names=self.ignored_dir_names,
                ignored_file_patterns=self.ignored_file_patterns,
                include_generated_mods=self.include_generated_mods,
            ):
                relative_path = path.relative_to(root_path).as_posix()
                source_type = classify_source_type(relative_path)
                content_hash = file_content_hash(path)
                stat = path.stat()
                records.append(
                    DiscoveredSourceFile(
                        source_id=stable_source_id(source_type, relative_path),
                        source_type=source_type,
                        source_path=str(path),
                        relative_path=relative_path,
                        content_hash=content_hash,
                        size_bytes=stat.st_size,
                        mtime=stat.st_mtime,
                    )
                )
        return sorted(records, key=lambda record: (record.source_type, record.relative_path))

    def _is_blocked_generated_mods_root(self, root: Path) -> bool:
        return root.name == "generated_mods" and not self.include_generated_mods


def iter_indexable_paths(
    *,
    root: Path,
    allowed_extensions: frozenset[str],
    ignored_dir_names: frozenset[str] = DEFAULT_IGNORED_DIR_NAMES,
    ignored_file_patterns: frozenset[str] = DEFAULT_IGNORED_FILE_PATTERNS,
    include_generated_mods: bool = False,
) -> list[Path]:
    """Walk a root deterministically while pruning ignored directories."""

    root = root.resolve()
    if not root.is_dir():
        raise SourceDiscoveryError(f"Source discovery root is unavailable or not a directory: {root}")
    files: list[Path] = []
    def fail_scan(error: OSError) -> None:
        raise error
    for dirpath, dirnames, filenames in os.walk(root, onerror=fail_scan):
        current = Path(dirpath).resolve()
        if current != root and current.name == "generated_mods" and not include_generated_mods:
            dirnames[:] = []
            continue
        dirnames[:] = [
            dirname
            for dirname in sorted(dirnames)
            if not is_ignored_dir(dirname, ignored_dir_names, include_generated_mods)
        ]
        for filename in sorted(filenames):
            if is_ignored_file(filename, ignored_file_patterns):
                continue
            path = (current / filename).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise SourceDiscoveryError("Discovered path escaped source root") from exc
            # A vanished or unreadable listed file makes the scan incomplete;
            # it must not silently become evidence for deleting indexed rows.
            if path.suffix.lower() in allowed_extensions and stat.S_ISREG(path.stat().st_mode):
                files.append(path)
    return files


def is_ignored_dir(
    dirname: str,
    ignored_dir_names: frozenset[str],
    include_generated_mods: bool,
) -> bool:
    if dirname == "generated_mods":
        return not include_generated_mods
    return dirname in ignored_dir_names


def is_ignored_file(filename: str, ignored_file_patterns: frozenset[str]) -> bool:
    return any(fnmatch.fnmatch(filename, pattern) for pattern in ignored_file_patterns)


def classify_source_type(relative_path: str) -> str:
    """Classify a discovered file using DEV_SPEC source-discovery patterns."""

    normalized = relative_path.replace("\\", "/")
    path = Path(normalized)
    parts = set(path.parts)
    suffix = path.suffix.lower()
    name = path.name
    if "reference_mods" in parts and suffix in {".cs", ".py"}:
        return "reference_mod"
    if "decompiled" in parts and suffix in {".cs", ".py", ".txt"}:
        return "decompiled_api"
    if "generated_mods" in parts and suffix == ".cs":
        return "target_source"
    if suffix in {".cs", ".py"}:
        return "target_source"
    if normalized.startswith("docs/knowledge/") and suffix == ".md":
        return "domain_note"
    if normalized.startswith("docs/features/"):
        if name in {"feature_spec.json", "proposal_review.json"}:
            return "prior_artifact"
        if name == "build_result.json":
            return "build_log"
    if suffix == ".log":
        return "build_log" if "build" in path.stem.lower() else "runtime_log"
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "screenshot"
    if suffix in {".json", ".yaml", ".yml"}:
        return "prior_artifact"
    return "domain_note" if suffix in {".md", ".txt"} else "target_source"


def normalize_extensions(extensions: frozenset[str]) -> frozenset[str]:
    return frozenset(
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in extensions
    )


def file_content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_source_id(source_type: str, relative_path: str) -> str:
    normalized_path = relative_path.replace("\\", "/")
    seed = f"{source_type}:{normalized_path}"
    return "src_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def aggregate_source_hash(files: list[Path], *, root: Path) -> str:
    """Build a stable hash from relative paths and file content hashes."""

    root = root.resolve()
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative_path = path.relative_to(root).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_content_hash(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()
