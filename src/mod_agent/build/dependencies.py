"""Bound dependency trees, deterministic snapshots and validated directory copies.

为什么要有它：依赖校验和复制由build owner独立提供，底层verifier无需反向加载产品入口。
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import shutil
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.mod_agent.build.nuget import _require_run_local_build_path
from src.mod_agent.errors import LocalEntryError


@dataclass(frozen=True)
class RunLocalGameFolderBindingV1:
    """Exact read-only GameFolder dependency identity for one local run."""

    source_root: str
    snapshot_sha256: str
    file_count: int
    property_name: Literal["GameFolder"] = "GameFolder"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_root, str)
            or not self.source_root
            or not isinstance(self.snapshot_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256) is None
            or isinstance(self.file_count, bool)
            or not isinstance(self.file_count, int)
            or self.file_count <= 0
            or self.property_name != "GameFolder"
        ):
            raise ValueError("Run-local GameFolder binding is invalid.")

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_version": "run_local_game_folder_binding_v1",
            "source_root": self.source_root,
            "snapshot_sha256": self.snapshot_sha256,
            "file_count": self.file_count,
            "property_name": self.property_name,
        }



@dataclass(frozen=True)
class _RunLocalGameFolderSourceIdentity:
    source_root: Path
    snapshot: tuple[dict[str, object], ...]
    snapshot_sha256: str
    file_count: int



def _binary_tree_snapshot(root: Path) -> tuple[dict[str, object], ...]:
    selected_root = root.resolve(strict=True)
    walk_root = _directory_copy_path_argument(
        selected_root,
        windows=os.name == "nt",
    )
    records: list[dict[str, object]] = []

    def fail_walk(error: OSError) -> None:
        raise LocalEntryError(
            "GameFolder dependency snapshot traversal failed."
        ) from error

    def require_plain_entry(
        path_text: str | os.PathLike[str],
        *,
        directory: bool,
    ) -> os.stat_result:
        try:
            entry_stat = os.lstat(path_text)
        except OSError as exc:
            raise LocalEntryError(
                "GameFolder dependency snapshot entry could not be inspected."
            ) from exc
        reparse_mask = getattr(
            stat_module,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400,
        )
        if stat_module.S_ISLNK(entry_stat.st_mode) or bool(
            getattr(entry_stat, "st_file_attributes", 0) & reparse_mask
        ):
            raise LocalEntryError(
                "GameFolder dependency snapshot rejects symlink or reparse entries."
            )
        expected = (
            stat_module.S_ISDIR(entry_stat.st_mode)
            if directory
            else stat_module.S_ISREG(entry_stat.st_mode)
        )
        if not expected:
            raise LocalEntryError(
                "GameFolder dependency snapshot rejects non-regular entries."
            )
        return entry_stat

    for current_root, directory_names, file_names in os.walk(
        walk_root,
        topdown=True,
        onerror=fail_walk,
        followlinks=False,
    ):
        directory_names.sort(key=lambda name: name.encode("utf-8"))
        file_names.sort(key=lambda name: name.encode("utf-8"))
        for directory_name in directory_names:
            require_plain_entry(
                os.path.join(current_root, directory_name),
                directory=True,
            )
        for file_name in file_names:
            file_path = os.path.join(current_root, file_name)
            entry_stat = require_plain_entry(file_path, directory=False)
            relative_path = Path(os.path.relpath(file_path, walk_root)).as_posix()
            if relative_path in ("", ".") or relative_path.startswith("../"):
                raise LocalEntryError(
                    "GameFolder dependency snapshot relative path escaped its root."
                )
            digest = hashlib.sha256()
            try:
                with open(file_path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as exc:
                raise LocalEntryError(
                    "GameFolder dependency snapshot file could not be read."
                ) from exc
            records.append(
                {
                    "path": relative_path,
                    "sha256": digest.hexdigest(),
                    "size": entry_stat.st_size,
                }
            )
    return tuple(
        sorted(records, key=lambda item: str(item["path"]).encode("utf-8"))
    )



def _binary_tree_snapshot_sha256(snapshot: tuple[dict[str, object], ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            list(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()



def _windows_extended_length_path(path_text: str) -> str:
    """Project one validated absolute Windows path into Win32 long-path form."""

    normalized = ntpath.normpath(path_text)
    if normalized.startswith("\\\\?\\"):
        return normalized
    if normalized.startswith("\\\\.\\") or not ntpath.isabs(normalized):
        raise LocalEntryError(
            "Extended-length copy paths must be absolute filesystem paths."
        )
    if normalized.startswith("\\\\"):
        return "\\\\?\\UNC\\" + normalized[2:]
    drive, tail = ntpath.splitdrive(normalized)
    if re.fullmatch(r"[A-Za-z]:", drive) is None or not tail.startswith("\\"):
        raise LocalEntryError(
            "Extended-length copy paths must use an absolute drive or UNC root."
        )
    return "\\\\?\\" + normalized



def _directory_copy_path_argument(
    path: Path,
    *,
    windows: bool,
) -> Path | str:
    if not windows:
        return path
    return _windows_extended_length_path(str(path))



def _copy_validated_directory_tree(*, source: Path, destination: Path) -> None:
    """Copy roots whose identity and containment were already validated."""

    windows = os.name == "nt"
    shutil.copytree(
        _directory_copy_path_argument(source, windows=windows),
        _directory_copy_path_argument(destination, windows=windows),
        copy_function=shutil.copy2,
    )



def _validate_game_folder_build_binding(
    binding: RunLocalGameFolderBindingV1,
    *,
    canonical_source_root: Path,
) -> _RunLocalGameFolderSourceIdentity:
    source = Path(binding.source_root)
    if not source.is_absolute():
        raise LocalEntryError("GameFolder dependency source_root must be absolute.")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise LocalEntryError("GameFolder dependency source_root is missing.")
    canonical = canonical_source_root.resolve(strict=True)
    try:
        source.relative_to(canonical)
    except ValueError:
        pass
    else:
        raise LocalEntryError(
            "GameFolder dependency source cannot be inside canonical product source."
        )
    try:
        canonical.relative_to(source)
    except ValueError:
        pass
    else:
        raise LocalEntryError(
            "GameFolder dependency source cannot contain canonical product source."
        )
    snapshot = _binary_tree_snapshot(source)
    observed_hash = _binary_tree_snapshot_sha256(snapshot)
    if len(snapshot) != binding.file_count:
        raise LocalEntryError("GameFolder dependency file count drifted.")
    if observed_hash != binding.snapshot_sha256:
        raise LocalEntryError("GameFolder dependency snapshot SHA256 drifted.")
    return _RunLocalGameFolderSourceIdentity(
        source_root=source,
        snapshot=snapshot,
        snapshot_sha256=observed_hash,
        file_count=len(snapshot),
    )



def _materialize_game_folder_build_dependency(
    identity: _RunLocalGameFolderSourceIdentity,
    *,
    run_root: Path,
) -> dict[str, object]:
    root = run_root.resolve(strict=True)
    destination = root / "build_dependencies" / "GameFolder"
    _require_run_local_build_path(
        root=root,
        path=destination,
        label="game_folder_dir",
    )
    if destination.exists():
        raise LocalEntryError("Run-local GameFolder dependency destination already exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_validated_directory_tree(
        source=identity.source_root,
        destination=destination,
    )
    copied_snapshot = _binary_tree_snapshot(destination)
    copied_hash = _binary_tree_snapshot_sha256(copied_snapshot)
    source_after_copy = _binary_tree_snapshot(identity.source_root)
    if source_after_copy != identity.snapshot:
        raise LocalEntryError("GameFolder dependency source changed during copy.")
    if copied_snapshot != identity.snapshot or copied_hash != identity.snapshot_sha256:
        raise LocalEntryError("Run-local GameFolder dependency copy identity drifted.")
    return {
        "binding_version": "run_local_game_folder_binding_v1",
        "property_name": "GameFolder",
        "source_root": str(identity.source_root),
        "source_snapshot_sha256": identity.snapshot_sha256,
        "source_file_count": identity.file_count,
        "isolated_copy": str(destination),
        "copy_snapshot_sha256": copied_hash,
        "copy_file_count": len(copied_snapshot),
        "build_uses_isolated_copy": True,
    }

