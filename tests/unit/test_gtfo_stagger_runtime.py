"""Tests for the bounded two-process GTFO stagger Runtime boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.mod_agent.runtime import (
    GTFOProcessHandle,
    GTFORealRuntimeProfile,
    GTFOStaggerAcceptanceProfile,
    build_gtfo_stagger_acceptance_report,
    build_screenshot_metadata,
    make_gtfo_stagger_runtime_evidence_factory,
    temporarily_deploy_gtfo_config,
)


DISABLED_CRITERION = (
    "With General.Enabled=false, a qualifying reaction produces no feature output."
)
VISUAL_CRITERION = (
    "With General.Enabled=true, the additional yellow X is directly observed."
)
MARKER_CRITERION = (
    "STAGGER_FEEDBACK_SHOWN records visual_spawn_succeeded=true and "
    "audio_event_accepted=true without proving visibility or audibility."
)
STARTUP_MARKER = "CHAINLOADER_READY"
ACCEPTANCE_MARKER = (
    "signal=STAGGER_FEEDBACK_SHOWN "
    "visual_spawn_succeeded=true audio_event_accepted=true"
)


def _write_config(path: Path, *, enabled: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[General]\n\n"
        "EnableDiagnosticLogging = false\n"
        f"Enabled = {str(enabled).lower()}\n",
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profiles(
    tmp_path: Path,
) -> tuple[GTFORealRuntimeProfile, GTFOStaggerAcceptanceProfile]:
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"test executable")
    bepinex_config = tmp_path / "BepInEx" / "config" / "BepInEx.cfg"
    bepinex_config.parent.mkdir(parents=True, exist_ok=True)
    bepinex_config.write_text(
        "[Logging.Disk]\nAppendLog = false\n",
        encoding="utf-8",
    )
    plugin_config = (
        tmp_path / "BepInEx" / "config" / "local.betterhitfeedback.cfg"
    )
    disabled_source = tmp_path / "reviewed" / "enabled_false.cfg"
    enabled_source = tmp_path / "reviewed" / "enabled_true.cfg"
    disabled_hash = _write_config(disabled_source, enabled=False)
    enabled_hash = _write_config(enabled_source, enabled=True)
    base_profile = GTFORealRuntimeProfile(
        profile_id="gtfo_real_runtime",
        game_executable=str(executable),
        working_directory=str(tmp_path),
        log_paths=("BepInEx/LogOutput.log",),
        screenshot_directory=str(tmp_path / "screenshots"),
        startup_markers=(STARTUP_MARKER,),
        acceptance_markers={MARKER_CRITERION: ACCEPTANCE_MARKER},
        timeout_seconds=5,
        poll_interval_seconds=0.01,
        terminate_after_capture=True,
        operator_completion_required=True,
        operator_completion_timeout_seconds=30,
    )
    stagger_profile = GTFOStaggerAcceptanceProfile(
        config_path=str(plugin_config),
        disabled_config_path=str(disabled_source),
        disabled_config_sha256=disabled_hash,
        enabled_config_path=str(enabled_source),
        enabled_config_sha256=enabled_hash,
    )
    return base_profile, stagger_profile


def test_stagger_acceptance_report_binds_two_modes_without_writing(
    tmp_path: Path,
) -> None:
    base_profile, stagger_profile = _profiles(tmp_path)
    destination = Path(stagger_profile.config_path)

    report = build_gtfo_stagger_acceptance_report(
        stagger_profile,
        working_directory=base_profile.working_directory,
        acceptance_criteria=(
            DISABLED_CRITERION,
            VISUAL_CRITERION,
            MARKER_CRITERION,
        ),
    )

    assert report["status"] == "ready"
    assert report["writes_performed"] is False
    assert report["process_launched"] is False
    assert destination.exists() is False
    assert [item["mode"] for item in report["attempts"]] == [
        "general_enabled_false",
        "general_enabled_true",
    ]
    assert report["attempts"][0]["acceptance_criteria"] == [
        DISABLED_CRITERION
    ]
    assert report["attempts"][1]["acceptance_criteria"] == [
        VISUAL_CRITERION,
        MARKER_CRITERION,
    ]


def test_stagger_acceptance_report_blocks_changed_reviewed_config(
    tmp_path: Path,
) -> None:
    base_profile, stagger_profile = _profiles(tmp_path)
    Path(stagger_profile.enabled_config_path).write_text(
        "[General]\nEnabled = false\n",
        encoding="utf-8",
    )

    report = build_gtfo_stagger_acceptance_report(
        stagger_profile,
        working_directory=base_profile.working_directory,
        acceptance_criteria=(DISABLED_CRITERION, MARKER_CRITERION),
    )

    assert report["status"] == "blocked"
    assert (
        "Reviewed GTFO config source SHA256 does not match."
        in report["blockers"]
    )
    assert (
        "Reviewed GTFO config must contain exactly one [General] Enabled "
        "value equal to true."
        in report["blockers"]
    )


def test_temporary_gtfo_config_restores_existing_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "game" / "local.betterhitfeedback.cfg"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"original config")
    original_hash = hashlib.sha256(destination.read_bytes()).hexdigest()
    source = tmp_path / "reviewed.cfg"
    source_hash = _write_config(source, enabled=True)

    with temporarily_deploy_gtfo_config(
        mode="general_enabled_true",
        source_path=source,
        expected_source_sha256=source_hash,
        destination_path=destination,
        backup_directory=tmp_path / "backup",
        allow_game_directory_write=True,
        expected_destination_existed=True,
        expected_destination_sha256=original_hash,
    ) as record:
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == source_hash

    assert destination.read_bytes() == b"original config"
    assert record.restored is True
    assert record.restoration_status == "restored"
    assert record.destination_sha256_after_restore == original_hash


def test_stagger_runtime_runs_disabled_then_enabled_and_restores_each_attempt(
    tmp_path: Path,
) -> None:
    base_profile, stagger_profile = _profiles(tmp_path)
    build_dll = tmp_path / "build" / "BetterHitFeedback.dll"
    build_dll.parent.mkdir()
    build_dll.write_bytes(b"verified build dll")
    build_hash = hashlib.sha256(build_dll.read_bytes()).hexdigest()
    plugin_destination = (
        tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    )
    plugin_destination.parent.mkdir(parents=True)
    launched_profiles: list[str] = []
    terminated_pids: list[int] = []
    operator_requests: list[dict[str, object]] = []

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

        def terminate(self) -> None:
            terminated_pids.append(self.pid)

        def wait(self, timeout: int) -> int:
            return 0

    def launcher(profile: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        launched_profiles.append(profile.profile_id)
        pid = 4100 + len(launched_profiles)
        return GTFOProcessHandle(pid=pid, process=Process(pid))

    def collector(profile: GTFORealRuntimeProfile, _):
        marker = (
            ""
            if profile.profile_id.endswith("general_enabled_false")
            else f"\n{ACCEPTANCE_MARKER}"
        )
        from src.mod_agent.runtime import GTFOLogSnapshot

        return GTFOLogSnapshot(
            content=f"{STARTUP_MARKER}{marker}\n",
            sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
        )

    def operator_reader(request):
        payload = request.to_dict()
        operator_requests.append(payload)
        return {
            "schema_version": "gtfo_operator_completion_v1",
            "request_sha256": payload["request_sha256"],
            "feature_id": request.feature_id,
            "status": "completed",
            "observed_by": "local_operator",
            "observations": [
                {
                    "criterion_sha256": item["criterion_sha256"],
                    "status": "passed",
                    "notes": (
                        "Direct observation was completed in this exact "
                        "GTFO process."
                    ),
                }
                for item in payload["acceptance_criteria"]
            ],
        }

    factory = make_gtfo_stagger_runtime_evidence_factory(
        base_profile=base_profile,
        stagger_profile=stagger_profile,
        allow_game_launch=True,
        allow_game_directory_write=True,
        build_artifact_path=build_dll,
        expected_artifact="bin/Debug/BetterHitFeedback.dll",
        plugin_destination_path=plugin_destination,
        backup_directory=tmp_path / "runtime_backup",
        expected_plugin_destination_existed=False,
        expected_plugin_destination_sha256=None,
        expected_config_destination_existed=False,
        expected_config_destination_sha256=None,
        process_launcher=launcher,
        log_collector=collector,
        screenshot_capturer=lambda profile, feature_id: build_screenshot_metadata(
            screenshot_id=f"shot_{profile.profile_id}",
            feature_id=feature_id,
            file_path=str(Path(profile.screenshot_directory) / "shot.png"),
            source="desktop_screenshot",
            content_hash=f"hash_{profile.profile_id}",
        ),
        operator_completion_reader=operator_reader,
    )

    payload = factory(
        "feature_001",
        {
            "execution_mode": "local",
            "claims_real_build_success": True,
            "verified_artifacts": [
                {
                    "path": "bin/Debug/BetterHitFeedback.dll",
                    "sha256": build_hash,
                }
            ],
        },
        {
            "acceptance_criteria": [
                DISABLED_CRITERION,
                VISUAL_CRITERION,
                MARKER_CRITERION,
            ],
            "runtime_verification_plan": ["Run both reviewed GTFO modes."],
        },
    )

    assert payload["verification_status"] == "verified"
    assert payload["acceptance_verified"] is True
    assert payload["claims_real_runtime_success"] is True
    assert launched_profiles == [
        "gtfo_real_runtime:general_enabled_false",
        "gtfo_real_runtime:general_enabled_true",
    ]
    assert terminated_pids == [4101, 4102]
    assert len(payload["stagger_runtime_attempts"]) == 2
    assert len(operator_requests) == 2
    assert operator_requests[0]["runtime_process_pid"] == 4101
    assert operator_requests[1]["runtime_process_pid"] == 4102
    assert operator_requests[0]["request_id"] != operator_requests[1]["request_id"]
    assert plugin_destination.exists() is False
    assert Path(stagger_profile.config_path).exists() is False
    assert payload["runtime_trust_binding"]["status"] == "pending_graph_binding"
    assert all(
        check["status"] == "passed"
        for check in payload["runtime_trust_binding"]["checks"].values()
    )
    assert {
        criterion
        for item in payload["evidence_items"]
        for criterion in item["supports_acceptance"]
    } == {
        DISABLED_CRITERION,
        VISUAL_CRITERION,
        MARKER_CRITERION,
    }
