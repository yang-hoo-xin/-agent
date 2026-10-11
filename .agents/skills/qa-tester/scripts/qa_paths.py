#!/usr/bin/env python3
"""Shared path and backup guards for the project-local QA helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


SOURCE_REPO_ROOT = Path(__file__).resolve().parents[4]
ISOLATION_MARKER = ".qa-isolated-target"
BACKUP_METADATA_VERSION = "qa-backup.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65_536), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata_path(backup: Path) -> Path:
    return backup.with_name(backup.name + ".meta.json")


def resolve_isolated_repo(value: str | Path) -> Path:
    """Return a marked QA checkout and reject the active source repository."""
    target = Path(value).resolve()
    if (
        target == SOURCE_REPO_ROOT
        or target.is_relative_to(SOURCE_REPO_ROOT)
        or SOURCE_REPO_ROOT.is_relative_to(target)
    ):
        raise ValueError("QA target must not overlap the active repository")
    if not target.is_dir():
        raise ValueError(f"QA target repository does not exist: {target}")
    marker = target / ISOLATION_MARKER
    if not marker.is_file():
        raise ValueError(
            f"QA target is missing isolation marker {ISOLATION_MARKER}: {target}"
        )
    return target


def require_contained_path(root: Path, value: Path) -> Path:
    """Resolve one helper path and reject paths outside its QA checkout."""
    resolved_root = root.resolve()
    resolved_value = value.resolve(strict=False)
    if not resolved_value.is_relative_to(resolved_root):
        raise ValueError(f"QA helper path resolves outside target: {value}")
    return resolved_value


def create_backup(source: Path, backup: Path) -> Path:
    """Create one identified backup without replacing an earlier backup."""
    metadata_path = _metadata_path(backup)
    if not source.is_file():
        raise FileNotFoundError(f"source file does not exist: {source}")
    if backup.exists() or metadata_path.exists():
        raise FileExistsError(
            f"existing backup must be restored or removed explicitly: {backup}"
        )
    shutil.copy2(source, backup)
    try:
        payload = {
            "schema_version": BACKUP_METADATA_VERSION,
            "target_path": str(source.resolve()),
            "backup_sha256": _sha256(backup),
            "target_sha256": _sha256(source),
        }
        metadata_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _load_backup_metadata(target: Path, backup: Path) -> tuple[Path, dict[str, str]]:
    """Load metadata bound to one target and backup pair."""
    metadata_path = _metadata_path(backup)
    if not backup.is_file():
        raise FileNotFoundError(f"backup does not exist: {backup}")
    if not metadata_path.is_file():
        raise ValueError(f"backup identity metadata does not exist: {metadata_path}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"backup identity metadata is invalid: {metadata_path}") from exc
    expected_fields = {
        "schema_version",
        "target_path",
        "backup_sha256",
        "target_sha256",
    }
    if not isinstance(metadata, dict) or set(metadata) != expected_fields:
        raise ValueError(f"backup identity metadata has an invalid shape: {metadata_path}")
    if metadata["schema_version"] != BACKUP_METADATA_VERSION:
        raise ValueError(f"backup identity metadata version is unsupported: {metadata_path}")
    if metadata["target_path"] != str(target.resolve()):
        raise ValueError("backup identity metadata belongs to another target")
    if metadata["backup_sha256"] != _sha256(backup):
        raise ValueError("backup content does not match its identity metadata")
    return metadata_path, metadata


def seal_target_state(target: Path, backup: Path) -> None:
    """Record the exact changed target state that a later restore may replace."""
    metadata_path, metadata = _load_backup_metadata(target, backup)
    metadata["target_sha256"] = _sha256(target)
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def restore_backup(target: Path, backup: Path) -> None:
    """Restore an identified backup only over its sealed target state."""
    metadata_path, metadata = _load_backup_metadata(target, backup)
    if metadata["target_sha256"] != _sha256(target):
        raise ValueError("target changed after its restorable state was sealed")
    shutil.copy2(backup, target)
    if _sha256(target) != metadata["backup_sha256"]:
        raise OSError("restored target does not match the identified backup")
    backup.unlink()
    metadata_path.unlink()
