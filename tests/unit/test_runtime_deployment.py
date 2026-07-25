from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from src.mod_agent.runtime import (
    RuntimePluginDeploymentError,
    bind_plugin_deployment_to_runtime_payload,
    temporarily_deploy_verified_plugin,
)
from src.mod_agent.runtime import deployment as deployment_module


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_temporary_plugin_deployment_removes_new_destination_after_runtime(
    tmp_path: Path,
) -> None:
    source = tmp_path / "build" / "BetterHitFeedback.dll"
    destination = tmp_path / "game" / "BepInEx" / "plugins" / source.name
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"verified final build")

    with temporarily_deploy_verified_plugin(
        source_path=source,
        destination_path=destination,
        backup_directory=tmp_path / "run" / "deployment_backup",
        expected_source_sha256=_sha256(source.read_bytes()),
        allow_game_directory_write=True,
    ) as deployment:
        assert destination.read_bytes() == source.read_bytes()
        assert deployment.destination_sha256_after_copy == _sha256(
            source.read_bytes()
        )

    assert not destination.exists()
    assert deployment.restored is True
    assert deployment.restoration_status == "restored"
    assert deployment.destination_exists_after_restore is False


def test_temporary_plugin_deployment_removes_read_only_deployed_dll(
    tmp_path: Path,
) -> None:
    source = tmp_path / "build" / "BetterHitFeedback.dll"
    destination = tmp_path / "game" / "BepInEx" / "plugins" / source.name
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"read-only verified final build")
    source.chmod(stat.S_IREAD)

    with temporarily_deploy_verified_plugin(
        source_path=source,
        destination_path=destination,
        backup_directory=tmp_path / "run" / "deployment_backup",
        expected_source_sha256=_sha256(source.read_bytes()),
        allow_game_directory_write=True,
    ) as deployment:
        assert destination.is_file()

    assert not destination.exists()
    assert deployment.restoration_status == "restored"


def test_temporary_plugin_deployment_records_restore_failure_without_losing_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "build" / "BetterHitFeedback.dll"
    destination = tmp_path / "game" / "BepInEx" / "plugins" / source.name
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"verified final build")
    original_unlink = deployment_module._unlink_with_retry

    def fail_destination_only(path: Path, **kwargs: object) -> None:
        if path == destination:
            raise PermissionError("simulated destination lock")
        original_unlink(path, **kwargs)

    monkeypatch.setattr(
        deployment_module,
        "_unlink_with_retry",
        fail_destination_only,
    )

    with temporarily_deploy_verified_plugin(
        source_path=source,
        destination_path=destination,
        backup_directory=tmp_path / "run" / "deployment_backup",
        expected_source_sha256=_sha256(source.read_bytes()),
        allow_game_directory_write=True,
    ) as deployment:
        runtime_payload = {"verification_status": "verified"}

    assert runtime_payload["verification_status"] == "verified"
    assert deployment.restored is False
    assert deployment.restoration_status == "failed"
    assert deployment.restoration_error_type == "PermissionError"
    bound = bind_plugin_deployment_to_runtime_payload(
        runtime_payload,
        deployment=deployment,
    )
    assert (
        bound["runtime_trust_binding"]["checks"]["game_directory_restoration"][
            "status"
        ]
        == "blocked"
    )
    destination.chmod(destination.stat().st_mode | stat.S_IWRITE)
    destination.unlink()


def test_temporary_plugin_deployment_restores_preexisting_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "build" / "BetterHitFeedback.dll"
    destination = tmp_path / "game" / "BepInEx" / "plugins" / source.name
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"new verified build")
    destination.write_bytes(b"preexisting installed plugin")
    original_hash = _sha256(destination.read_bytes())

    with temporarily_deploy_verified_plugin(
        source_path=source,
        destination_path=destination,
        backup_directory=tmp_path / "run" / "deployment_backup",
        expected_source_sha256=_sha256(source.read_bytes()),
        allow_game_directory_write=True,
    ) as deployment:
        assert destination.read_bytes() == source.read_bytes()

    assert destination.read_bytes() == b"preexisting installed plugin"
    assert deployment.destination_sha256_before == original_hash
    assert deployment.destination_sha256_after_restore == original_hash
    assert Path(str(deployment.backup_path)).read_bytes() == destination.read_bytes()


def test_temporary_plugin_deployment_blocks_hash_drift_before_write(
    tmp_path: Path,
) -> None:
    source = tmp_path / "build" / "BetterHitFeedback.dll"
    destination = tmp_path / "game" / "BepInEx" / "plugins" / source.name
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"changed build")

    with pytest.raises(RuntimePluginDeploymentError, match="SHA256 changed"):
        with temporarily_deploy_verified_plugin(
            source_path=source,
            destination_path=destination,
            backup_directory=tmp_path / "run" / "deployment_backup",
            expected_source_sha256=_sha256(b"expected build"),
            allow_game_directory_write=True,
        ):
            raise AssertionError("deployment must not start")

    assert not destination.exists()


def test_temporary_plugin_deployment_requires_write_approval(
    tmp_path: Path,
) -> None:
    source = tmp_path / "BetterHitFeedback.dll"
    destination = tmp_path / "plugins" / source.name
    source.write_bytes(b"build")
    destination.parent.mkdir()

    with pytest.raises(RuntimePluginDeploymentError, match="explicit write approval"):
        with temporarily_deploy_verified_plugin(
            source_path=source,
            destination_path=destination,
            backup_directory=tmp_path / "backup",
            expected_source_sha256=_sha256(source.read_bytes()),
            allow_game_directory_write=False,
        ):
            raise AssertionError("deployment must not start")


def test_temporary_plugin_deployment_blocks_destination_drift_after_admission(
    tmp_path: Path,
) -> None:
    source = tmp_path / "build" / "BetterHitFeedback.dll"
    destination = tmp_path / "game" / "BepInEx" / "plugins" / source.name
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"build")
    destination.write_bytes(b"changed after admission")

    with pytest.raises(
        RuntimePluginDeploymentError,
        match="existence changed after admission",
    ):
        with temporarily_deploy_verified_plugin(
            source_path=source,
            destination_path=destination,
            backup_directory=tmp_path / "backup",
            expected_source_sha256=_sha256(source.read_bytes()),
            allow_game_directory_write=True,
            expected_destination_existed=False,
            expected_destination_sha256=None,
        ):
            raise AssertionError("deployment must not start")

    assert destination.read_bytes() == b"changed after admission"


def test_runtime_payload_requires_deployment_hash_and_restoration_checks(
    tmp_path: Path,
) -> None:
    source = tmp_path / "build" / "BetterHitFeedback.dll"
    destination = tmp_path / "game" / "BepInEx" / "plugins" / source.name
    source.parent.mkdir()
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"build")

    with temporarily_deploy_verified_plugin(
        source_path=source,
        destination_path=destination,
        backup_directory=tmp_path / "backup",
        expected_source_sha256=_sha256(source.read_bytes()),
        allow_game_directory_write=True,
    ) as deployment:
        pass

    bound = bind_plugin_deployment_to_runtime_payload(
        {
            "runtime_trust_binding": {
                "status": "pending_graph_binding",
                "checks": {
                    "feature_id": {"status": "passed"},
                    "runtime_process_identity": {"status": "passed"},
                },
                "blockers": [],
            }
        },
        deployment=deployment,
    )

    trust = bound["runtime_trust_binding"]
    assert trust["deployment_required"] is True
    assert trust["status"] == "pending_graph_binding"
    assert trust["checks"]["deployed_plugin_artifact_hash"]["status"] == "passed"
    assert trust["checks"]["game_directory_restoration"]["status"] == "passed"
    assert bound["plugin_deployment_binding"]["restored"] is True
