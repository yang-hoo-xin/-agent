"""Tests for real GTFO runtime automation boundaries."""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
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
from src.mod_agent.runtime import gtfo_automation as gtfo_automation_module


ACCEPTANCE_CRITERION = "Requested behavior is implemented: make Load enable diagnostics"
RUNTIME_PLAN_STEP = "acceptance_evidence_observed"
STARTUP_MARKER = "BEPINEX_CHAINLOADER_READY"
ACCEPTANCE_MARKER = "BETTER_HIT_FEEDBACK_ACCEPTANCE_OK"


def _profile(tmp_path: Path) -> GTFORealRuntimeProfile:
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"fake exe for path validation")
    config_path = tmp_path / "BepInEx" / "config" / "BepInEx.cfg"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "[Logging.Disk]\nAppendLog = false\n",
        encoding="utf-8",
    )
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
    assert report["checks"]["bepinex_log_config"] == {
        "status": "passed",
        "configured_path": "BepInEx/config/BepInEx.cfg",
        "resolved_path": str(tmp_path / "BepInEx" / "config" / "BepInEx.cfg"),
        "exists": True,
        "is_file": True,
        "content_sha256": hashlib.sha256(
            (tmp_path / "BepInEx" / "config" / "BepInEx.cfg").read_bytes()
        ).hexdigest(),
        "section": "Logging.Disk",
        "key": "AppendLog",
        "append_log_value": "false",
        "append_log_enabled": False,
    }
    assert report["planned_evidence_sources"] == {
        "process": True,
        "process_diagnostics": True,
        "persistent_logs": True,
        "bepinex_log_config": True,
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


def test_gtfo_runtime_capability_report_blocks_missing_bepinex_log_config(
    tmp_path: Path,
) -> None:
    profile = _profile(tmp_path)
    (tmp_path / "BepInEx" / "config" / "BepInEx.cfg").unlink()

    report = build_gtfo_runtime_capability_report(
        profile,
        allow_game_launch=True,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
    )

    assert report["status"] == "blocked"
    assert report["would_launch"] is False
    assert report["checks"]["bepinex_log_config"]["status"] == "blocked"
    assert report["checks"]["bepinex_log_config"]["content_sha256"] is None
    assert report["checks"]["bepinex_log_config"]["append_log_value"] is None
    assert report["blockers"] == [
        "BepInEx/config/BepInEx.cfg must contain exactly one "
        "[Logging.Disk] AppendLog boolean value"
    ]


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
    assert payload["failure_ownership"] == {
        "owner": "permission",
        "failure_class": "runtime_launch_not_authorized",
        "source_repair_allowed": False,
        "required_action": "request_runtime_permission",
        "reason": "GTFO launch authority was not admitted for this Runtime attempt.",
    }
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
    assert payload["failure_ownership"]["owner"] == "environment"
    assert payload["failure_ownership"]["source_repair_allowed"] is False
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
    assert payload["runtime_trust_binding"]["checks"]["bepinex_log_config"][
        "append_log_value"
    ] == "false"
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


def test_gtfo_runtime_default_collector_rejects_prelaunch_marker_history(
    tmp_path: Path,
) -> None:
    profile = replace(
        _profile(tmp_path),
        timeout_seconds=0.03,
        poll_interval_seconds=0.01,
    )
    log_path = tmp_path / "BepInEx" / "LogOutput.log"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(
        f"OLD_SENTINEL\n{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n",
        encoding="utf-8",
    )

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=lambda _: GTFOProcessHandle(pid=4242),
        screenshot_capturer=lambda _, __: None,
    )

    assert payload["acceptance_verified"] is False
    assert payload["raw_supplied_output"] == ""
    current_logs = payload["runtime_trust_binding"]["checks"]["current_run_logs"]
    assert current_logs["run_boundary_status"] == "prelaunch_byte_boundary"
    assert current_logs["source_windows"][0]["run_local_size_bytes"] == 0


def test_gtfo_runtime_default_collector_accepts_only_post_launch_appended_markers(
    tmp_path: Path,
) -> None:
    profile = replace(
        _profile(tmp_path),
        timeout_seconds=0.2,
        poll_interval_seconds=0.01,
    )
    log_path = tmp_path / "BepInEx" / "LogOutput.log"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text(
        f"OLD_SENTINEL\n{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n",
        encoding="utf-8",
    )

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"NEW_RUN\n{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n")
        return GTFOProcessHandle(pid=4242)

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_001",
        ),
    )

    assert payload["acceptance_verified"] is True
    assert "NEW_RUN" in payload["raw_supplied_output"]
    assert "OLD_SENTINEL" not in payload["raw_supplied_output"]
    current_logs = payload["runtime_trust_binding"]["checks"]["current_run_logs"]
    assert current_logs["status"] == "passed"
    assert current_logs["run_boundary_status"] == "prelaunch_byte_boundary"
    assert (
        current_logs["source_windows"][0]["mode"]
        == "appended_after_prelaunch_boundary"
    )


def test_gtfo_runtime_log_boundary_allows_one_unused_pending_log_path(
    tmp_path: Path,
) -> None:
    profile = replace(
        _profile(tmp_path),
        log_paths=("BepInEx/LogOutput.log", "BepInEx/logs/LogOutput.log"),
        timeout_seconds=0.2,
        poll_interval_seconds=0.01,
    )
    log_path = tmp_path / "BepInEx" / "LogOutput.log"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text("OLD_SENTINEL\n", encoding="utf-8")

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n")
        return GTFOProcessHandle(pid=4242)

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_001",
        ),
    )

    current_logs = payload["runtime_trust_binding"]["checks"]["current_run_logs"]
    assert payload["acceptance_verified"] is True
    assert current_logs["status"] == "passed"
    assert [window["status"] for window in current_logs["source_windows"]] == [
        "passed",
        "pending",
    ]


def test_gtfo_runtime_log_limit_preserves_newest_marker_tail(
    tmp_path: Path,
) -> None:
    profile = replace(
        _profile(tmp_path),
        timeout_seconds=0.2,
        poll_interval_seconds=0.01,
        output_limit_chars=80,
    )
    log_path = tmp_path / "BepInEx" / "LogOutput.log"
    log_path.parent.mkdir(exist_ok=True)
    log_path.write_text("OLD_SENTINEL\n", encoding="utf-8")

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write("x" * 200)
            stream.write(f"\n{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n")
        return GTFOProcessHandle(pid=4242)

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_001",
        ),
    )

    assert payload["acceptance_verified"] is True
    assert STARTUP_MARKER in payload["raw_supplied_output"]
    assert payload["raw_supplied_output"].rstrip().endswith(ACCEPTANCE_MARKER)
    assert payload["runtime_trust_binding"]["checks"]["current_run_logs"][
        "truncated"
    ] is True


def test_gtfo_runtime_marker_observations_survive_head_tail_split(
    tmp_path: Path,
) -> None:
    profile = replace(
        _profile(tmp_path),
        timeout_seconds=0.2,
        poll_interval_seconds=0.01,
        output_limit_chars=80,
    )
    log_path = tmp_path / "BepInEx" / "LogOutput.log"
    log_path.parent.mkdir(exist_ok=True)
    full_content = f"{STARTUP_MARKER}\n{'x' * 200}\n{ACCEPTANCE_MARKER}\n"

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        log_path.write_text(full_content, encoding="utf-8")
        return GTFOProcessHandle(pid=4242)

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_001",
        ),
    )

    assert STARTUP_MARKER not in payload["raw_supplied_output"]
    assert payload["raw_supplied_output"].rstrip().endswith(ACCEPTANCE_MARKER)
    assert payload["acceptance_verified"] is True
    assert payload["runtime_trust_binding"]["checks"]["plugin_load_marker"][
        "status"
    ] == "passed"
    observations = payload["gtfo_markers"]["marker_observations"]
    assert [item["marker"] for item in observations] == [
        STARTUP_MARKER,
        ACCEPTANCE_MARKER,
    ]
    assert all(item["observed"] is True for item in observations)
    assert observations[0]["run_local_character_offset"] == 0
    assert (
        observations[1]["run_local_character_offset"]
        > observations[0]["run_local_character_offset"]
    )
    assert [item["excerpt"] for item in observations] == [
        STARTUP_MARKER,
        ACCEPTANCE_MARKER,
    ]
    assert all(item["excerpt_truncated"] is False for item in observations)
    assert {
        item["observation_scope"] for item in observations
    } == {"accumulated_run_local_window"}
    assert payload["evidence_items"][0]["raw_excerpt"] == ACCEPTANCE_MARKER


def test_gtfo_runtime_marker_observations_accumulate_across_log_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain_criterion = "chain probe was observed"
    negative_criterion = "negative probe remains absent"
    negative_marker = "h3_observation_negative_probe=absent"
    profile = replace(
        _profile(tmp_path),
        startup_markers=("BepInEx", "Chainloader"),
        acceptance_markers={
            chain_criterion: "chain_probe=true",
            negative_criterion: negative_marker,
        },
        timeout_seconds=0.04,
        poll_interval_seconds=0.01,
    )
    log_path = tmp_path / "BepInEx" / "LogOutput.log"
    log_path.write_text("OLD_SENTINEL\n", encoding="utf-8")

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write("BepInEx\nChainloader\nchain_probe=true\n")
        return GTFOProcessHandle(pid=4242)

    original_sleep = gtfo_automation_module.time.sleep
    rotated = False

    def rotate_after_first_snapshot(delay: float) -> None:
        nonlocal rotated
        if not rotated:
            log_path.write_text(
                "CURRENT_RUN_LATER_GENERATION_WITHOUT_MARKERS\n",
                encoding="utf-8",
            )
            rotated = True
        original_sleep(delay)

    monkeypatch.setattr(
        gtfo_automation_module.time,
        "sleep",
        rotate_after_first_snapshot,
    )

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(chain_criterion, negative_criterion),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_multigeneration",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_multigeneration",
        ),
    )

    assert "Chainloader" not in payload["raw_supplied_output"]
    assert "chain_probe=true" not in payload["raw_supplied_output"]
    assert negative_marker not in payload["raw_supplied_output"]
    observations = {
        item["marker"]: item
        for item in payload["gtfo_markers"]["marker_observations"]
    }
    assert observations["BepInEx"]["observed"] is True
    assert observations["Chainloader"]["observed"] is True
    assert observations["chain_probe=true"]["observed"] is True
    assert observations[negative_marker]["observed"] is False
    assert observations[negative_marker].get("source_window") is None
    assert {
        observations[marker]["source_window"]["generation"]
        for marker in ("BepInEx", "Chainloader", "chain_probe=true")
    } == {1}
    assert payload["startup_loaded"] is True
    assert payload["acceptance_verified"] is False
    assert payload["failure_ownership"]["owner"] == "observation"
    acceptance_check = payload["runtime_trust_binding"]["checks"][
        "acceptance_markers"
    ]
    assert acceptance_check["missing_observations"] == [negative_criterion]
    assert payload["runtime_trust_binding"]["blockers"] == [
        "acceptance_markers trust check did not pass"
    ]
    assert payload["limitations"] == [
        "GTFO runtime logs did not contain every configured acceptance marker."
    ]
    assert payload["gtfo_markers"]["acceptance_markers_observed"] == [
        {
            "acceptance_criterion": chain_criterion,
            "marker": "chain_probe=true",
        }
    ]
    windows = payload["runtime_trust_binding"]["checks"]["current_run_logs"][
        "source_windows"
    ]
    passed = [window for window in windows if window["status"] == "passed"]
    assert [window["generation"] for window in passed] == [1, 2]
    assert [window["mode"] for window in passed] == [
        "appended_after_prelaunch_boundary",
        "replaced_or_truncated_after_prelaunch_boundary",
    ]
    assert [window["prefix_identity_status"] for window in passed] == [
        "matched",
        "replaced_after_launch",
    ]
    assert all(window["observation_count"] >= 1 for window in passed)
    assert all(window["first_observed_at_ns"] > 0 for window in passed)
    assert all(window["last_observed_at_ns"] > 0 for window in passed)


def test_gtfo_runtime_marker_observations_do_not_invent_missing_startup(
    tmp_path: Path,
) -> None:
    profile = replace(
        _profile(tmp_path),
        timeout_seconds=0.05,
        poll_interval_seconds=0.01,
        output_limit_chars=80,
    )
    log_path = tmp_path / "BepInEx" / "LogOutput.log"
    log_path.parent.mkdir(exist_ok=True)
    full_content = f"{'x' * 200}\n{ACCEPTANCE_MARKER}\n"

    def launcher(_: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        log_path.write_text(full_content, encoding="utf-8")
        return GTFOProcessHandle(pid=4242)

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=launcher,
        screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
            screenshot_id="shot_001",
            feature_id=feature_id,
            file_path=str(tmp_path / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash_001",
        ),
    )

    assert payload["startup_loaded"] is False
    assert payload["acceptance_verified"] is False
    startup_check = payload["runtime_trust_binding"]["checks"][
        "plugin_load_marker"
    ]
    assert startup_check["status"] == "blocked"
    assert startup_check["marker_observations"] == [
        {
            "marker": STARTUP_MARKER,
            "observed": False,
            "run_local_character_offset": None,
            "excerpt": None,
            "excerpt_truncated": False,
            "observation_scope": "accumulated_run_local_window",
        }
    ]


def test_gtfo_runtime_records_liveness_before_configured_termination(
    tmp_path: Path,
) -> None:
    profile = replace(_profile(tmp_path), terminate_after_capture=True)

    class Process:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self) -> int | None:
            return 0 if self.terminated else None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: int) -> int:
            return 0

    process = Process()
    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        process_launcher=lambda _: GTFOProcessHandle(pid=4242, process=process),
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

    assert process.terminated is True
    assert payload["runtime_process"]["liveness_observed"] is True
    assert (
        payload["runtime_trust_binding"]["checks"]["runtime_process_identity"][
            "status"
        ]
        == "passed"
    )


def test_gtfo_runtime_process_diagnostics_are_bounded_and_not_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = replace(
        _profile(tmp_path),
        timeout_seconds=0.01,
        output_limit_chars=32,
    )
    captured: dict[str, object] = {}
    stdout_content = (
        b"x" * 80
        + f"\n{STARTUP_MARKER}\n{ACCEPTANCE_MARKER}\n".encode("utf-8")
    )

    class Process:
        pid = 4242

        def __init__(self) -> None:
            self.stdout = io.BytesIO(stdout_content)
            self.stderr = io.BytesIO(b"diagnostic stderr")

        def poll(self) -> None:
            return None

    def fake_popen(command: tuple[str, ...], **kwargs: object) -> Process:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(
        gtfo_automation_module.subprocess,
        "Popen",
        fake_popen,
    )

    payload = GTFORealRuntimeAutomationRunner().run(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_game_launch=True,
        log_collector=lambda _, __: GTFOLogSnapshot(content="", sources=()),
        screenshot_capturer=lambda _, __: None,
        process_diagnostic_directory=(
            tmp_path / "run_001" / "runtime_process_diagnostics"
        ),
    )

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["stdout"] == gtfo_automation_module.subprocess.PIPE
    assert kwargs["stderr"] == gtfo_automation_module.subprocess.PIPE
    diagnostics = payload["process_diagnostics"]
    assert diagnostics["status"] == "captured"
    assert diagnostics["observation_scope"] == "run_local_process_output"
    assert diagnostics["supports_acceptance"] == []
    assert diagnostics["stdout"]["retained_size_bytes"] == 32
    assert diagnostics["stdout"]["total_size_bytes"] > 32
    assert diagnostics["stdout"]["truncated"] is True
    stdout_path = Path(diagnostics["stdout"]["file_path"])
    assert stdout_path.parent == (
        tmp_path / "run_001" / "runtime_process_diagnostics"
    )
    assert stdout_path.read_bytes() == stdout_content[-32:]
    assert payload["startup_loaded"] is False
    assert payload["acceptance_verified"] is False
    assert payload["claims_real_runtime_success"] is False


def test_desktop_screenshot_passes_output_path_through_dedicated_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        output = Path(str(kwargs["env"]["MOD_AGENT_SCREENSHOT_OUTPUT"]))
        output.write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gtfo_automation_module.subprocess, "run", fake_run)

    screenshot = gtfo_automation_module._capture_desktop_screenshot(
        profile,
        "feature_001",
    )

    expected = (tmp_path / "screenshots" / "feature_001_gtfo_runtime.png").resolve()
    assert screenshot is not None
    assert screenshot.file_path == str(tmp_path / "screenshots" / expected.name)
    assert captured["command"][:3] == ("powershell", "-NoProfile", "-Command")
    assert captured["env"]["MOD_AGENT_SCREENSHOT_OUTPUT"] == str(expected)


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
    assert payload["failure_ownership"]["owner"] == "environment"
    assert payload["failure_ownership"]["failure_class"] == "process_launch_failed"
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
    assert payload["failure_ownership"]["owner"] == "observation"
    assert payload["failure_ownership"]["failure_class"] == "log_collection_failed"
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
