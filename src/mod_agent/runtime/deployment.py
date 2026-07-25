"""Run-scoped physical plugin deployment with verified restoration."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from uuid import uuid4


class RuntimePluginDeploymentError(RuntimeError):
    """Raised when a run-scoped plugin deployment cannot remain truthful."""


@dataclass
class RuntimePluginDeploymentRecord:
    """Mutable audit record completed when the deployment context restores."""

    source_path: str
    destination_path: str
    expected_source_sha256: str
    source_sha256: str
    destination_existed_before: bool
    destination_sha256_before: str | None
    backup_path: str | None
    deployed_at: str
    destination_sha256_after_copy: str
    copied: bool = True
    restored: bool = False
    restoration_status: str = "pending"
    restored_at: str | None = None
    destination_exists_after_restore: bool | None = None
    destination_sha256_after_restore: str | None = None
    restoration_error_type: str | None = None
    restoration_error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the complete deployment/restoration audit shape."""

        return {
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "expected_source_sha256": self.expected_source_sha256,
            "source_sha256": self.source_sha256,
            "destination_existed_before": self.destination_existed_before,
            "destination_sha256_before": self.destination_sha256_before,
            "backup_path": self.backup_path,
            "deployed_at": self.deployed_at,
            "destination_sha256_after_copy": self.destination_sha256_after_copy,
            "copied": self.copied,
            "restored": self.restored,
            "restoration_status": self.restoration_status,
            "restored_at": self.restored_at,
            "destination_exists_after_restore": self.destination_exists_after_restore,
            "destination_sha256_after_restore": self.destination_sha256_after_restore,
            "restoration_error_type": self.restoration_error_type,
            "restoration_error_message": self.restoration_error_message,
        }


@contextmanager
def temporarily_deploy_verified_plugin(
    *,
    source_path: str | Path,
    destination_path: str | Path,
    backup_directory: str | Path,
    expected_source_sha256: str,
    allow_game_directory_write: bool,
) -> Iterator[RuntimePluginDeploymentRecord]:
    """Deploy verified bytes for one Runtime call and restore in ``finally``."""

    if not allow_game_directory_write:
        raise RuntimePluginDeploymentError(
            "Game-directory plugin deployment requires explicit write approval."
        )
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    backup_root = Path(backup_directory).resolve()
    if not source.is_file():
        raise RuntimePluginDeploymentError(
            f"Verified build artifact is missing: {source}"
        )
    if not destination.is_absolute() or destination.suffix.lower() != ".dll":
        raise RuntimePluginDeploymentError(
            "Runtime plugin destination must be an absolute .dll path."
        )
    if not destination.parent.is_dir():
        raise RuntimePluginDeploymentError(
            f"Runtime plugin destination directory is missing: {destination.parent}"
        )
    expected_hash = _normalized_sha256(expected_source_sha256)
    source_hash = _sha256_file(source)
    if source_hash != expected_hash:
        raise RuntimePluginDeploymentError(
            "Verified build artifact SHA256 changed before deployment."
        )

    backup_root.mkdir(parents=True, exist_ok=True)
    destination_existed = destination.is_file()
    destination_hash_before = (
        _sha256_file(destination) if destination_existed else None
    )
    backup_path = (
        backup_root / f"{destination.name}.before"
        if destination_existed
        else None
    )
    if backup_path is not None:
        shutil.copy2(destination, backup_path)
        if _sha256_file(backup_path) != destination_hash_before:
            raise RuntimePluginDeploymentError(
                "Runtime plugin backup SHA256 does not match the existing destination."
            )

    deployment_temp = destination.parent / (
        f".{destination.name}.{uuid4().hex}.deploying"
    )
    restore_temp = destination.parent / (
        f".{destination.name}.{uuid4().hex}.restoring"
    )
    record: RuntimePluginDeploymentRecord | None = None
    try:
        shutil.copy2(source, deployment_temp)
        if _sha256_file(deployment_temp) != source_hash:
            raise RuntimePluginDeploymentError(
                "Temporary deployed plugin SHA256 does not match the build artifact."
            )
        os.replace(deployment_temp, destination)
        deployed_hash = _sha256_file(destination)
        if deployed_hash != source_hash:
            raise RuntimePluginDeploymentError(
                "Deployed plugin SHA256 does not match the build artifact."
            )
        record = RuntimePluginDeploymentRecord(
            source_path=str(source),
            destination_path=str(destination),
            expected_source_sha256=expected_hash,
            source_sha256=source_hash,
            destination_existed_before=destination_existed,
            destination_sha256_before=destination_hash_before,
            backup_path=str(backup_path) if backup_path is not None else None,
            deployed_at=_utc_now(),
            destination_sha256_after_copy=deployed_hash,
        )
        yield record
    finally:
        try:
            _unlink_with_retry(deployment_temp)
            try:
                if destination_existed:
                    if backup_path is None or not backup_path.is_file():
                        raise RuntimePluginDeploymentError(
                            "Runtime plugin backup is missing during restoration."
                        )
                    shutil.copy2(backup_path, restore_temp)
                    if _sha256_file(restore_temp) != destination_hash_before:
                        raise RuntimePluginDeploymentError(
                            "Runtime plugin restore bytes do not match the original SHA256."
                        )
                    _replace_with_retry(restore_temp, destination)
                else:
                    _unlink_with_retry(destination)
                destination_exists_after = destination.is_file()
                destination_hash_after = (
                    _sha256_file(destination) if destination_exists_after else None
                )
                restored = (
                    destination_exists_after == destination_existed
                    and destination_hash_after == destination_hash_before
                )
                if not restored:
                    raise RuntimePluginDeploymentError(
                        "Runtime plugin destination did not return to its pre-run state."
                    )
                if record is not None:
                    record.restored = True
                    record.restoration_status = "restored"
                    record.restored_at = _utc_now()
                    record.destination_exists_after_restore = destination_exists_after
                    record.destination_sha256_after_restore = destination_hash_after
            except Exception as exc:
                if record is None:
                    raise
                record.restored = False
                record.restoration_status = "failed"
                record.restored_at = _utc_now()
                record.destination_exists_after_restore = destination.is_file()
                record.destination_sha256_after_restore = (
                    _sha256_file(destination) if destination.is_file() else None
                )
                record.restoration_error_type = type(exc).__name__
                record.restoration_error_message = str(exc)
        finally:
            try:
                _unlink_with_retry(restore_temp)
            except OSError as exc:
                if record is None:
                    raise
                if record.restoration_error_type is None:
                    record.restored = False
                    record.restoration_status = "failed"
                    record.restored_at = _utc_now()
                    record.restoration_error_type = type(exc).__name__
                    record.restoration_error_message = str(exc)


def bind_plugin_deployment_to_runtime_payload(
    payload: Mapping[str, Any],
    *,
    deployment: RuntimePluginDeploymentRecord,
) -> dict[str, Any]:
    """Require verified deployment and restoration in GTFO Runtime trust."""

    bound = dict(payload)
    deployment_record = deployment.to_dict()
    deployed_hash_passed = bool(
        deployment.copied
        and deployment.source_sha256 == deployment.expected_source_sha256
        and deployment.destination_sha256_after_copy == deployment.source_sha256
    )
    restoration_passed = bool(
        deployment.restored and deployment.restoration_status == "restored"
    )
    trust = dict(bound.get("runtime_trust_binding") or {})
    checks = dict(trust.get("checks") or {})
    checks["deployed_plugin_artifact_hash"] = {
        "status": "passed" if deployed_hash_passed else "blocked",
        "source_path": deployment.source_path,
        "destination_path": deployment.destination_path,
        "expected_source_sha256": deployment.expected_source_sha256,
        "source_sha256": deployment.source_sha256,
        "destination_sha256_after_copy": deployment.destination_sha256_after_copy,
    }
    checks["game_directory_restoration"] = {
        "status": "passed" if restoration_passed else "blocked",
        "destination_existed_before": deployment.destination_existed_before,
        "destination_sha256_before": deployment.destination_sha256_before,
        "destination_exists_after_restore": (
            deployment.destination_exists_after_restore
        ),
        "destination_sha256_after_restore": (
            deployment.destination_sha256_after_restore
        ),
        "restoration_status": deployment.restoration_status,
        "error_type": deployment.restoration_error_type,
        "error_message": deployment.restoration_error_message,
    }
    blockers = [
        f"{name} trust check did not pass"
        for name, check in checks.items()
        if not isinstance(check, Mapping) or check.get("status") != "passed"
    ]
    trust.update(
        {
            "deployment_required": True,
            "checks": checks,
            "blockers": blockers,
            "status": "pending_graph_binding" if not blockers else "blocked",
        }
    )
    bound["plugin_deployment_binding"] = deployment_record
    bound["runtime_trust_binding"] = trust
    return bound


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unlink_with_retry(
    path: Path,
    *,
    attempts: int = 20,
    delay_seconds: float = 0.25,
) -> None:
    """Remove one exact path after clearing read-only state and bounded lock retries."""

    for attempt in range(attempts):
        if not path.exists():
            return
        try:
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
            path.unlink()
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(delay_seconds)


def _replace_with_retry(
    source: Path,
    destination: Path,
    *,
    attempts: int = 20,
    delay_seconds: float = 0.25,
) -> None:
    """Replace one exact destination after bounded Windows lock retries."""

    for attempt in range(attempts):
        try:
            if destination.exists():
                destination.chmod(destination.stat().st_mode | stat.S_IWRITE)
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(delay_seconds)


def _normalized_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise RuntimePluginDeploymentError(
            "Expected build artifact SHA256 must contain exactly 64 hex characters."
        )
    return normalized


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
