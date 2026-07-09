"""Tests for real GTFO runtime automation boundaries."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.runtime import (
    GTFOLogSnapshot,
    GTFOProcessHandle,
    GTFORealRuntimeAutomationRunner,
    GTFORealRuntimeProfile,
    GTFORuntimeAutomationError,
    build_gtfo_runtime_capability_report,
    build_screenshot_metadata,
    make_gtfo_runtime_evidence_factory,
    make_gtfo_runtime_evidence_factory_from_settings,
    profile_from_settings,
)


ACCEPTANCE_CRITERION = "Requested behavior is implemented: make Load enable diagnostics"
RUNTIME_PLAN_STEP = "acceptance_evidence_observed"
STARTUP_MARKER = "BEPINEX_CHAINLOADER_READY"
ACCEPTANCE_MARKER = "BETTER_HIT_FEEDBACK_ACCEPTANCE_OK"


def _profile(tmp_path: Path) -> GTFORealRuntimeProfile:
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"fake exe for path validation")
    return GTFORealRuntimeProfile(
        profile_id="gtfo_real_runtime",
        game_executable=str(executable),
        working_directory=str(tmp_path),
        log_paths=("BepInEx/LogOutput.log",),
        screenshot_directory=str(tmp_path / "screenshots"),
        startup_markers=(STARTUP_MARKER,),
        acceptance_markers={ACCEPTANCE_CRITERION: ACCEPTANCE_MARKER},
        timeout_seconds=5,
        poll_interval_seconds=0.01,
    )


def test_gtfo_runtime_capability_report_checks_profile_without_launch(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)

    report = build_gtfo_runtime_capability_report(
        profile,
        allow_game_launch=False,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
    )

    assert report["status"] == "blocked"
    assert report["would_launch"] is False
    assert report["blockers"] == ["GTFO game launch requires explicit approval"]
    assert report["checks"]["explicit_launch_approval"] == {
        "status": "blocked",
        "required": True,
        "allow_game_launch": False,
    }
    assert report["checks"]["game_executable"]["status"] == "passed"
    assert report["checks"]["game_executable"]["exists"] is True
    assert report["checks"]["working_directory"]["status"] == "passed"
    assert report["checks"]["working_directory"]["is_dir"] is True
    assert report["checks"]["log_paths"]["resolved_paths"] == [
        {
            "configured_path": "BepInEx/LogOutput.log",
            "resolved_path": str(tmp_path / "BepInEx" / "LogOutput.log"),
            "exists": False,
            "is_file": False,
        }
    ]
    assert report["checks"]["acceptance_markers"]["status"] == "passed"
    assert report["planned_evidence_sources"] == {
        "process": True,
        "persistent_logs": True,
        "desktop_screenshot": True,
        "plugin_markers": True,
    }


def test_gtfo_runtime_capability_report_is_ready_with_launch_approval(
    tmp_path: Path,
) -> None:
    report = build_gtfo_runtime_capability_report(
        _profile(tmp_path),
        allow_game_launch=True,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
    )

    assert report["status"] == "ready"
    assert report["would_launch"] is True
    assert report["blockers"] == []


def test_gtfo_runtime_requires_explicit_launch_approval(tmp_path: Path) -> None:
    launcher_called = False
    collector_called = False
    capturer_called = False

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        nonlocal launcher_called
        launcher_called = True
        return GTFOProcessHandle(pid=4242)

    def collector(
        _: GTFORealRuntimeProfile,
        __: tuple[str, ...],
    ) -> GTFOLogSnapshot:
        nonlocal collector_called
        collector_called = True
        return GTFOLogSnapshot(content="", sources=())

    def capturer(
        _: GTFORealRuntimeProfile,
        __: str,
    ):
        nonlocal capturer_called
        capturer_called = True
        return None

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=_profile(tmp_path),
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=False,
        process_launcher=launcher,
        log_collector=collector,
        screenshot_capturer=capturer,
    )

    assert launcher_called is False
    assert collector_called is False
    assert capturer_called is False
    assert payload["verification_status"] == "failed"
    assert payload["acceptance_verified"] is False
    assert payload["claims_real_runtime_success"] is False
    assert payload["real_runtime_performed"] is False
    assert payload["runtime_process"]["launched"] is False
    assert payload["failure"]["type"] == "GTFORuntimeAutomationError"
    assert "GTFO game launch requires explicit approval" in payload["failure"]["message"]
    assert payload["gtfo_capability_report"]["status"] == "blocked"
    assert payload["gtfo_capability_report"]["checks"]["explicit_launch_approval"] == {
        "status": "blocked",
        "required": True,
        "allow_game_launch": False,
    }


def test_gtfo_runtime_rejects_missing_executable(tmp_path: Path) -> None:
    profile = GTFORealRuntimeProfile(
        profile_id="gtfo_real_runtime",
        game_executable=str(tmp_path / "missing-GTFO.exe"),
        working_directory=str(tmp_path),
        log_paths=("BepInEx/LogOutput.log",),
    )

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
    )

    assert payload["verification_status"] == "failed"
    assert payload["acceptance_verified"] is False
    assert payload["claims_real_runtime_success"] is False
    assert payload["runtime_process"] == {
        "profile_id": "gtfo_real_runtime",
        "pid": None,
        "launched": False,
        "liveness_observed": False,
    }
    assert payload["failure"]["type"] == "GTFORuntimeAutomationError"
    assert "GTFO executable does not exist" in payload["failure"]["message"]
    assert payload["gtfo_capability_report"]["status"] == "blocked"
    assert payload["gtfo_capability_report"]["would_launch"] is False
    assert (
        payload["gtfo_capability_report"]["checks"]["game_executable"]["status"]
        == "blocked"
    )


def test_gtfo_runtime_logs_and_screenshot_can_verify_acceptance(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        return GTFOProcessHandle(pid=4242)

    def collector(
        _: GTFORealRuntimeProfile,
        __: tuple[str, ...],
    ) -> GTFOLogSnapshot:
        return GTFOLogSnapshot(
            content=f"{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n",
            sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
        )

    def capturer(
        _: GTFORealRuntimeProfile,
        feature_id: str,
    ):
        screenshot_path = tmp_path / "screenshots" / "feature_001_gtfo_runtime.png"
        screenshot_path.parent.mkdir()
        screenshot_path.write_bytes(b"png")
        return build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(screenshot_path),
            source="desktop_screenshot",
            content_hash="hash_001",
        )

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
        log_collector=collector,
        screenshot_capturer=capturer,
    )

    assert payload["execution_mode"] == "real"
    assert payload["evidence_source"] == "gtfo_real_runtime_automation"
    assert payload["real_runtime_performed"] is True
    assert payload["startup_loaded"] is True
    assert payload["gameplay_behavior_verified"] is True
    assert payload["acceptance_verified"] is True
    assert payload["claims_real_runtime_success"] is True
    assert payload["runtime_process"] == {
        "profile_id": "gtfo_real_runtime",
        "pid": 4242,
        "launched": True,
        "liveness_observed": True,
    }
    assert payload["gtfo_markers"]["startup_loaded"] is True
    assert payload["gtfo_markers"]["acceptance_markers_observed"] == [
        {
            "acceptance_criterion": ACCEPTANCE_CRITERION,
            "marker": ACCEPTANCE_MARKER,
        }
    ]
    assert payload["screenshot"]["source"] == "desktop_screenshot"
    assert payload["screenshot_refs"] == [payload["screenshot"]]
    assert payload["evidence_items"][0]["source"] == "gtfo_persistent_log"
    assert payload["evidence_items"][0]["supports_acceptance"] == [ACCEPTANCE_CRITERION]
    assert payload["gtfo_capability_report"]["status"] == "ready"
    assert payload["gtfo_capability_report"]["would_launch"] is True
    assert payload["plugin_marker_binding"] == {
        "marker_source": "gtfo_persistent_log",
        "markers": [
            {
                "acceptance_criterion": ACCEPTANCE_CRITERION,
                "marker": ACCEPTANCE_MARKER,
                "observed": True,
            }
        ],
    }
    assert payload["runtime_trust_binding"]["status"] == "pending_graph_binding"
    assert payload["runtime_trust_binding"]["checks"]["runtime_process_identity"] == {
        "status": "passed",
        "profile_id": "gtfo_real_runtime",
        "pid": 4242,
        "launched": True,
        "liveness_observed": True,
    }
    assert (
        payload["runtime_trust_binding"]["checks"]["current_run_logs"]["status"]
        == "passed"
    )
    assert (
        payload["runtime_trust_binding"]["checks"]["screenshot_runtime_artifact_linkage"][
            "status"
        ]
        == "passed"
    )


def test_gtfo_runtime_missing_acceptance_marker_is_inconclusive(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=lambda _: GTFOProcessHandle(pid=4242),
        log_collector=lambda _, __: GTFOLogSnapshot(
            content=f"{STARTUP_MARKER}\n",
            sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
        ),
        screenshot_capturer=lambda _, __: None,
    )

    assert payload["execution_mode"] == "real"
    assert payload["real_runtime_performed"] is True
    assert payload["startup_loaded"] is True
    assert payload["gameplay_behavior_verified"] is False
    assert payload["acceptance_verified"] is False
    assert payload["claims_real_runtime_success"] is False
    assert "GTFO runtime logs did not contain every configured acceptance marker." in payload[
        "limitations"
    ]
    assert "GTFO runtime screenshot was not captured." in payload["limitations"]
    assert payload["runtime_trust_binding"]["status"] == "blocked"
    assert (
        payload["runtime_trust_binding"]["checks"]["acceptance_markers"]["status"]
        == "blocked"
    )
    assert (
        payload["runtime_trust_binding"]["checks"]["screenshot_runtime_artifact_linkage"][
            "status"
        ]
        == "blocked"
    )


def test_gtfo_runtime_missing_acceptance_marker_blocks_before_launch(
    tmp_path: Path,
) -> None:
    profile = GTFORealRuntimeProfile(
        profile_id="gtfo_real_runtime",
        game_executable=_profile(tmp_path).game_executable,
        working_directory=str(tmp_path),
        log_paths=("BepInEx/LogOutput.log",),
        screenshot_directory=str(tmp_path / "screenshots"),
        startup_markers=(STARTUP_MARKER,),
        acceptance_markers={},
    )
    launcher_called = False

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        nonlocal launcher_called
        launcher_called = True
        return GTFOProcessHandle(pid=4242)

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
    )

    assert launcher_called is False
    assert payload["verification_status"] == "failed"
    assert payload["claims_real_runtime_success"] is False
    assert payload["runtime_process"]["launched"] is False
    assert payload["failure"]["type"] == "GTFORuntimeAutomationError"
    assert payload["gtfo_capability_report"]["status"] == "blocked"
    assert payload["gtfo_capability_report"]["checks"]["acceptance_markers"] == {
        "status": "blocked",
        "configured_markers": {},
        "acceptance_criteria": [ACCEPTANCE_CRITERION],
        "missing_acceptance_criteria": [ACCEPTANCE_CRITERION],
    }


def test_gtfo_runtime_launcher_exception_becomes_failed_payload(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        raise OSError("process launch denied")

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
    )

    assert payload["verification_status"] == "failed"
    assert payload["runtime_status"] == "failed"
    assert payload["real_runtime_performed"] is False
    assert payload["runtime_process"]["launched"] is False
    assert payload["failure"] == {
        "type": "OSError",
        "message": "process launch denied",
    }
    assert payload["gtfo_markers"]["acceptance_markers_observed"] == []
    assert payload["runtime_trust_binding"]["status"] == "blocked"


def test_gtfo_runtime_collector_failure_preserves_launched_process(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    def collector(
        _: GTFORealRuntimeProfile,
        __: tuple[str, ...],
    ) -> GTFOLogSnapshot:
        raise PermissionError("log access denied")

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=lambda _: GTFOProcessHandle(pid=4242),
        log_collector=collector,
    )

    assert payload["verification_status"] == "failed"
    assert payload["real_runtime_performed"] is True
    assert payload["runtime_process"] == {
        "profile_id": "gtfo_real_runtime",
        "pid": 4242,
        "launched": True,
        "liveness_observed": True,
    }
    assert payload["failure"] == {
        "type": "PermissionError",
        "message": "log access denied",
    }
    assert payload["runtime_trust_binding"]["status"] == "blocked"


def test_gtfo_runtime_factory_is_graph_compatible(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    factory = make_gtfo_runtime_evidence_factory(
        profile=profile,
        allow_game_launch=True,
        process_launcher=lambda _: GTFOProcessHandle(pid=4242),
        log_collector=lambda _, __: GTFOLogSnapshot(
            content=f"{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n",
            sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
        ),
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_001",
        ),
    )

    payload = factory(
        "feature_001",
        {"execution_mode": "local"},
        {
            "acceptance_criteria": [ACCEPTANCE_CRITERION],
            "runtime_verification_plan": [RUNTIME_PLAN_STEP],
        },
    )

    assert payload["acceptance_verified"] is True


def test_gtfo_runtime_factory_from_settings_uses_configured_markers(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    settings = SimpleNamespace(
        runtime=SimpleNamespace(
            gtfo=SimpleNamespace(
                enabled=True,
                game_executable=profile.game_executable,
                working_directory=profile.working_directory,
                launch_args=[],
                log_paths=list(profile.log_paths),
                screenshot_directory=profile.screenshot_directory,
                screenshot_timeout_seconds=profile.screenshot_timeout_seconds,
                startup_markers=list(profile.startup_markers),
                acceptance_markers={ACCEPTANCE_CRITERION: ACCEPTANCE_MARKER},
                timeout_seconds=profile.timeout_seconds,
                poll_interval_seconds=profile.poll_interval_seconds,
                output_limit_chars=profile.output_limit_chars,
                terminate_after_capture=profile.terminate_after_capture,
            )
        )
    )

    runtime_profile = profile_from_settings(settings)
    factory = make_gtfo_runtime_evidence_factory_from_settings(
        settings,
        allow_game_launch=True,
        process_launcher=lambda _: GTFOProcessHandle(pid=4242),
        log_collector=lambda _, __: GTFOLogSnapshot(
            content=f"{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n",
            sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
        ),
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_001",
        ),
    )

    payload = factory(
        "feature_001",
        {"execution_mode": "local"},
        {
            "acceptance_criteria": [ACCEPTANCE_CRITERION],
            "runtime_verification_plan": [RUNTIME_PLAN_STEP],
        },
    )

    assert runtime_profile.acceptance_markers == {
        ACCEPTANCE_CRITERION: ACCEPTANCE_MARKER
    }
    assert payload["acceptance_verified"] is True
    assert payload["plugin_marker_binding"] == {
        "marker_source": "gtfo_persistent_log",
        "markers": [
            {
                "acceptance_criterion": ACCEPTANCE_CRITERION,
                "marker": ACCEPTANCE_MARKER,
                "observed": True,
            }
        ],
    }
    assert payload["runtime_trust_binding"]["status"] == "pending_graph_binding"
