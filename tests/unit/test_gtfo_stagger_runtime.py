"""Tests for the bounded two-process GTFO stagger Runtime boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.mod_agent.runtime import (
    GTFOProcessHandle,
    GTFORealRuntimeProfile,
    GTFOStaggerAcceptanceProfile,
    build_gtfo_stagger_acceptance_report,
    build_screenshot_metadata,
    make_gtfo_stagger_runtime_evidence_factory,
    temporarily_deploy_gtfo_config,
)
from src.mod_agent.runtime import gtfo_stagger as gtfo_stagger_module
from src.mod_agent.runtime.stagger_diagnosis import (
    bind_stagger_repair_attempt_runtime_results,
    build_stagger_observation_retry_criterion_binding,
    build_stagger_repair_attempt_projection,
    evaluate_stagger_acceptance,
    inherit_stagger_repair_attempt_prior_results,
)


DISABLED_CRITERION = (
    "With General.Enabled=false, a qualifying reaction produces no feature output."
)
VISUAL_CRITERION = (
    "With General.Enabled=true, a locally owned player's weapon hit that "
    "actually produces the selected enemy reaction shows one additional "
    "short-lived yellow X at that hit position."
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


def _repair_attempt_projection(
    *,
    acceptance_criteria: tuple[str, ...] = (
        DISABLED_CRITERION,
        VISUAL_CRITERION,
        MARKER_CRITERION,
    ),
) -> dict[str, object]:
    failed_criterion = VISUAL_CRITERION
    return build_stagger_repair_attempt_projection(
        feature_id="feature_001",
        run_id="run_001",
        repair_plan={
            "feature_id": "feature_001",
            "repair_id": "repair_001",
            "retry_count": 0,
            "retry_budget": 2,
            "semantic_decision": {"selected_hypothesis_id": "H1"},
        },
        repair_plan_ref={"path": "repair-plan.json", "artifact_hash": "1" * 64},
        root_cause_evidence={
            "feature_id": "feature_001",
            "failure_owner": "product_behavior",
            "failed_feature_spec_criterion": failed_criterion,
        },
        root_cause_evidence_ref={
            "path": "root-cause.json",
            "artifact_hash": "2" * 64,
        },
        isolated_apply_result_ref={
            "path": "apply.json",
            "artifact_hash": "3" * 64,
        },
        build_result_ref={"path": "build.json", "artifact_hash": "4" * 64},
        acceptance_criteria=acceptance_criteria,
        marker_criteria=frozenset({MARKER_CRITERION}),
        source_hash_before="5" * 64,
        source_sha256="6" * 64,
        source_snapshot_sha256="7" * 64,
        dll_sha256="8" * 64,
        diff_hash="sha256:" + "9" * 64,
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


def test_stagger_acceptance_report_selects_only_unresolved_enabled_criterion(
    tmp_path: Path,
) -> None:
    base_profile, stagger_profile = _profiles(tmp_path)

    report = build_gtfo_stagger_acceptance_report(
        stagger_profile,
        working_directory=base_profile.working_directory,
        acceptance_criteria=(
            DISABLED_CRITERION,
            VISUAL_CRITERION,
            MARKER_CRITERION,
        ),
        selected_acceptance_criteria=(VISUAL_CRITERION,),
    )

    assert report["status"] == "ready"
    assert report["selected_acceptance_criteria"] == [VISUAL_CRITERION]
    assert report["attempts"] == [
        {
            "mode": "general_enabled_true",
            "acceptance_criteria": [VISUAL_CRITERION],
            "requires_operator_completion": True,
            "requires_product_marker": True,
        }
    ]
    assert report["writes_performed"] is False
    assert report["process_launched"] is False


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
        assert (tmp_path / "backup" / "original.bin").is_file()

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
                    "criterion_satisfied": True,
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
        repair_attempt_projection=_repair_attempt_projection(),
        runtime_attempt_namespace="repair_attempt_test:run_001:initial",
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
    assert payload["repair_attempt"]["runtime_status"] == "passed"
    assert payload["repair_attempt"]["final_status"] == "accepted"
    assert {
        item["runtime_attempt_id"]
        for item in payload["criterion_results"]
    } == {
        "repair_attempt_test:run_001:initial:general_enabled_false",
        "repair_attempt_test:run_001:initial:general_enabled_true",
    }
    assert len(operator_requests) == 2
    assert operator_requests[0]["runtime_process_pid"] == 4101
    assert operator_requests[1]["runtime_process_pid"] == 4102
    assert operator_requests[0]["request_id"] != operator_requests[1]["request_id"]
    assert "intentionally disables BetterHitFeedback" in str(
        operator_requests[0]["acceptance_criteria"][0]["operator_guidance"]
    )
    assert operator_requests[0]["acceptance_criteria"][0][
        "criterion_satisfied_required"
    ] is True
    assert plugin_destination.exists() is False
    assert Path(stagger_profile.config_path).exists() is False
    assert payload["runtime_trust_binding"]["status"] == "pending_graph_binding"
    assert payload["operator_semantic_consistency"] == {
        "status": "consistent",
        "correction_required": False,
        "conflict_modes": [],
    }
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


def test_stagger_runtime_isolates_full_post_run_logs_and_bounded_projection(
    tmp_path: Path,
) -> None:
    base_profile, stagger_profile = _profiles(tmp_path)
    base_profile = gtfo_stagger_module.replace(
        base_profile,
        output_limit_chars=20_000,
    )
    build_dll = tmp_path / "build" / "BetterHitFeedback.dll"
    build_dll.parent.mkdir()
    build_dll.write_bytes(b"verified build dll")
    build_hash = hashlib.sha256(build_dll.read_bytes()).hexdigest()
    plugin_destination = (
        tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    )
    plugin_destination.parent.mkdir(parents=True)
    output_root = tmp_path / "run_004"
    output_root.mkdir()
    persistent_log = tmp_path / "BepInEx" / "LogOutput.log"

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self):
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: int) -> int:
            return 0

    launches = 0

    def launcher(profile: GTFORealRuntimeProfile) -> GTFOProcessHandle:
        nonlocal launches
        launches += 1
        return GTFOProcessHandle(
            pid=5200 + launches,
            process=Process(5200 + launches),
        )

    def collector(profile: GTFORealRuntimeProfile, _):
        marker = (
            ""
            if profile.profile_id.endswith("general_enabled_false")
            else f"\n{ACCEPTANCE_MARKER}"
        )
        content = f"{STARTUP_MARKER}\n" + ("x" * 24_000) + marker + "\n"
        content_bytes = content.encode("utf-8")
        persistent_log.write_bytes(content_bytes)
        from src.mod_agent.runtime import GTFOLogSnapshot

        return GTFOLogSnapshot(
            content=content,
            sources=(str(persistent_log),),
            source_windows=(
                {
                    "status": "passed",
                    "mode": (
                        "created_or_truncated_after_prelaunch_boundary"
                        if launches == 1
                        else "replaced_or_truncated_after_prelaunch_boundary"
                    ),
                    "generation": launches,
                    "path": str(persistent_log),
                    "run_local_start_byte": 0,
                    "run_local_size_bytes": len(content_bytes),
                    "run_local_sha256": hashlib.sha256(
                        content_bytes
                    ).hexdigest(),
                },
            ),
        )

    def operator_reader(request):
        payload = request.to_dict()
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
                    "criterion_satisfied": True,
                    "notes": "Direct observation completed.",
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
        backup_directory=output_root / "runtime_backup",
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
        attempt_output_root=output_root,
        run_id="run_004",
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

    assert payload["run_id"] == "run_004"
    assert payload["run_local_output_root"] == str(output_root.resolve())
    assert (output_root / "runtime_result.json").is_file()
    for mode, identity in payload["run_local_log_identities"].items():
        bounded = identity["bounded_projection"]
        full = identity["post_run_full_copy"]
        assert bounded["character_count"] == 20_000
        assert bounded["configured_character_limit"] == 20_000
        assert full["size_bytes"] > bounded["size_bytes"]
        assert full["observed_prefix_verified"] is True
        full_bytes = Path(full["path"]).read_bytes()
        assert hashlib.sha256(full_bytes).hexdigest() == full["sha256"]
        if mode == "general_enabled_false":
            assert ACCEPTANCE_MARKER.encode("utf-8") not in full_bytes
        else:
            assert ACCEPTANCE_MARKER.encode("utf-8") in full_bytes
    assert plugin_destination.exists() is False
    assert Path(stagger_profile.config_path).exists() is False


def test_stagger_runtime_full_log_mismatch_restores_plugin_and_config(
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
    output_root = tmp_path / "run_004"
    output_root.mkdir()
    persistent_log = tmp_path / "BepInEx" / "LogOutput.log"
    persistent_log.write_bytes(b"current run")

    class Process:
        pid = 5301

        def poll(self):
            return None

        def terminate(self) -> None:
            return None

        def wait(self, timeout: int) -> int:
            return 0

    def collector(profile: GTFORealRuntimeProfile, _):
        from src.mod_agent.runtime import GTFOLogSnapshot

        return GTFOLogSnapshot(
            content=f"{STARTUP_MARKER}\n",
            sources=(str(persistent_log),),
            source_windows=(
                {
                    "status": "passed",
                    "mode": "created_or_truncated_after_prelaunch_boundary",
                    "generation": 1,
                    "path": str(persistent_log),
                    "run_local_start_byte": 0,
                    "run_local_size_bytes": len(persistent_log.read_bytes()),
                    "run_local_sha256": "0" * 64,
                },
            ),
        )

    factory = make_gtfo_stagger_runtime_evidence_factory(
        base_profile=base_profile,
        stagger_profile=stagger_profile,
        allow_game_launch=True,
        allow_game_directory_write=True,
        build_artifact_path=build_dll,
        expected_artifact="bin/Debug/BetterHitFeedback.dll",
        plugin_destination_path=plugin_destination,
        backup_directory=output_root / "runtime_backup",
        expected_plugin_destination_existed=False,
        expected_plugin_destination_sha256=None,
        expected_config_destination_existed=False,
        expected_config_destination_sha256=None,
        process_launcher=lambda _: GTFOProcessHandle(pid=5301, process=Process()),
        log_collector=collector,
        screenshot_capturer=lambda profile, feature_id: build_screenshot_metadata(
            screenshot_id="shot",
            feature_id=feature_id,
            file_path=str(Path(profile.screenshot_directory) / "shot.png"),
            source="desktop_screenshot",
            content_hash="hash",
        ),
        operator_completion_reader=lambda request: {
            "schema_version": "gtfo_operator_completion_v1",
            "request_sha256": request.to_dict()["request_sha256"],
            "feature_id": request.feature_id,
            "status": "completed",
            "observed_by": "local_operator",
            "observations": [
                {
                    "criterion_sha256": item["criterion_sha256"],
                    "status": "passed",
                    "criterion_satisfied": True,
                    "notes": "Direct observation completed.",
                }
                for item in request.to_dict()["acceptance_criteria"]
            ],
        },
        attempt_output_root=output_root,
        run_id="run_004",
    )

    try:
        factory(
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
                ],
                "runtime_verification_plan": [
                    "Run both reviewed GTFO modes."
                ],
            },
        )
    except gtfo_stagger_module.GTFOStaggerRuntimeError as exc:
        assert "observed current-run prefix" in str(exc)
    else:
        raise AssertionError("Expected full-log prefix mismatch.")

    assert plugin_destination.exists() is False
    assert Path(stagger_profile.config_path).exists() is False


def test_stagger_operator_semantic_conflict_is_separate_observation_failure() -> None:
    payload = gtfo_stagger_module._aggregate_stagger_attempts(
        feature_id="feature_001",
        input_execution_mode="local",
        acceptance_criteria=(DISABLED_CRITERION, VISUAL_CRITERION),
        runtime_verification_plan=("Run both reviewed GTFO modes.",),
        attempt_payloads=[
            {
                "stagger_attempt_mode": "general_enabled_false",
                "acceptance_verified": False,
                "evidence_items": [],
                "screenshot_refs": [],
                "runtime_process": {"pid": 4101},
                "runtime_trust_binding": {"checks": {}},
                "operator_completion": {
                    "semantic_consistency": {
                        "status": "conflict",
                        "correction_required": True,
                    }
                },
            }
        ],
        expected_modes=(
            "general_enabled_false",
            "general_enabled_true",
        ),
    )

    assert payload["verification_status"] == "inconclusive"
    assert payload["acceptance_verified"] is False
    assert payload["failure_ownership"]["failure_class"] == (
        "operator_status_semantic_conflict"
    )
    assert payload["failure_ownership"]["source_repair_allowed"] is False
    assert payload["operator_semantic_consistency"] == {
        "status": "conflict",
        "correction_required": True,
        "conflict_modes": ["general_enabled_false"],
    }


def test_stagger_visual_false_is_diagnosed_before_full_acceptance_completes() -> None:
    visual_hash = hashlib.sha256(VISUAL_CRITERION.encode("utf-8")).hexdigest()
    marker_hash = hashlib.sha256(MARKER_CRITERION.encode("utf-8")).hexdigest()
    payload = gtfo_stagger_module._aggregate_stagger_attempts(
        feature_id="feature_001",
        input_execution_mode="local",
        acceptance_criteria=(VISUAL_CRITERION, MARKER_CRITERION),
        runtime_verification_plan=("Run the enabled GTFO mode.",),
        attempt_payloads=[
            {
                "stagger_attempt_mode": "general_enabled_true",
                "acceptance_verified": False,
                "raw_supplied_output": (
                    "[GTFO_MOD_AGENT] signal=STAGGER_FEEDBACK_SKIPPED "
                    "visual_spawned=False "
                    "visual_reason=missing_canvas_rect_for_stagger_x"
                ),
                "evidence_items": [
                    {
                        "type": "runtime_log",
                        "source": "gtfo_persistent_log",
                        "locator": "BepInEx/LogOutput.log",
                        "supports_acceptance": [],
                        "confidence": 1.0,
                        "raw_excerpt": None,
                    }
                ],
                "screenshot_refs": [],
                "runtime_process": {"pid": 4102},
                "runtime_trust_binding": {
                    "checks": {
                        "feature_id": {"status": "passed"},
                        "runtime_process_identity": {"status": "passed"},
                        "current_run_logs": {
                            "status": "passed",
                            "sources": ["BepInEx/LogOutput.log"],
                        },
                        "plugin_load_marker": {"status": "passed"},
                        "deployed_plugin_artifact_hash": {
                            "status": "passed"
                        },
                        "runtime_config_identity": {"status": "passed"},
                    }
                },
                "operator_completion": {
                    "request_sha256": "a" * 64,
                    "semantic_consistency": {
                        "status": "consistent",
                        "correction_required": False,
                    },
                    "observations": [
                        {
                            "acceptance_criterion": VISUAL_CRITERION,
                            "criterion_sha256": visual_hash,
                            "status": "failed",
                            "criterion_satisfied": False,
                            "semantic_consistency": "consistent",
                            "notes": "No additional yellow X was observed.",
                        },
                        {
                            "acceptance_criterion": MARKER_CRITERION,
                            "criterion_sha256": marker_hash,
                            "status": "not_observed",
                            "criterion_satisfied": None,
                            "semantic_consistency": "consistent",
                            "notes": "Audibility remains unresolved.",
                        },
                    ],
                },
            }
        ],
        expected_modes=("general_enabled_true",),
    )

    diagnosis = payload["runtime_failure_diagnosis"]
    assert payload["verification_status"] == "failed"
    assert payload["acceptance_verified"] is False
    assert payload["failure_ownership"]["owner"] == "product_behavior"
    assert payload["failure_ownership"]["failure_class"] == (
        "product_behavior"
    )
    assert payload["failure_ownership"]["source_repair_allowed"] is True
    assert payload["stagger_acceptance_evaluation"][
        "attempt_completion"
    ] == "incomplete"
    assert payload["stagger_acceptance_evaluation"][
        "overall_acceptance"
    ] == "failed"
    assert payload["stagger_acceptance_evaluation"]["criteria"] == [
        {
            "acceptance_criterion": VISUAL_CRITERION,
            "outcome": "false",
            "evidence_strength": "confirmed",
            "evidence_refs": [
                {
                    "source": "gtfo_operator_completion",
                    "locator": "a" * 64,
                    "criterion_sha256": visual_hash,
                },
                {
                    "source": "gtfo_persistent_log",
                    "locator": "BepInEx/LogOutput.log",
                },
            ],
        },
        {
            "acceptance_criterion": MARKER_CRITERION,
            "outcome": "not_observed",
            "evidence_strength": "none",
            "evidence_refs": [
                {
                    "source": "gtfo_operator_completion",
                    "locator": "a" * 64,
                    "criterion_sha256": marker_hash,
                }
            ],
        },
    ]
    assert diagnosis["schema_version"] == (
        "stagger_runtime_failure_diagnosis_v1"
    )
    assert diagnosis["failure_class"] == "product_behavior"
    assert diagnosis["confirmed_failure_point"] == {
        "component": "ui_attachment",
        "symbol": (
            "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
            "TrySpawnStaggerYellowX"
        ),
        "dependency": "HUD RectTransform",
        "dependency_expression": "_lastHudParent as RectTransform",
        "mechanism": "dependency_unavailable_early_return",
        "event": "missing_canvas_rect_for_stagger_x",
    }
    assert diagnosis["responsibility_anchors"]["source_hash"] is None
    assert diagnosis["responsibility_anchors"]["source_span"] is None
    assert diagnosis["root_cause_status"] == "unresolved"
    assert diagnosis["unresolved_root_causes"] == [
        "hud_parent_never_initialized",
        "hud_parent_initialization_timing",
        "hud_parent_cache_stale",
        "hud_parent_runtime_type_mismatch",
        "hud_node_selection_incorrect",
    ]
    assert diagnosis["excluded_repair_scopes"] == [
        "hit_reaction_hook",
        "audio_pipeline",
    ]


def test_stagger_machine_diagnosis_does_not_require_manual_observation() -> None:
    base_attempt = {
        "stagger_attempt_mode": "general_enabled_true",
        "acceptance_verified": False,
        "evidence_items": [
            {
                "type": "runtime_log",
                "source": "gtfo_persistent_log",
                "locator": "BepInEx/LogOutput.log",
                "supports_acceptance": [],
                "confidence": 1.0,
                "raw_excerpt": None,
            }
        ],
        "screenshot_refs": [],
        "runtime_process": {"pid": 4102},
        "runtime_trust_binding": {
            "checks": {
                "feature_id": {"status": "passed"},
                "runtime_process_identity": {"status": "passed"},
                "current_run_logs": {
                    "status": "passed",
                    "sources": ["BepInEx/LogOutput.log"],
                },
                "plugin_load_marker": {"status": "passed"},
                "deployed_plugin_artifact_hash": {"status": "passed"},
                "runtime_config_identity": {"status": "passed"},
            }
        },
    }
    machine_only = {
        **base_attempt,
        "raw_supplied_output": (
            "signal=STAGGER_FEEDBACK_SKIPPED visual_spawned=False "
            "visual_reason=missing_canvas_rect_for_stagger_x"
        ),
    }
    manual_only = {
        **base_attempt,
        "operator_completion": {
            "request_sha256": "b" * 64,
            "semantic_consistency": {"status": "consistent"},
            "observations": [
                {
                    "acceptance_criterion": VISUAL_CRITERION,
                    "criterion_sha256": hashlib.sha256(
                        VISUAL_CRITERION.encode("utf-8")
                    ).hexdigest(),
                    "status": "failed",
                    "criterion_satisfied": False,
                    "semantic_consistency": "consistent",
                    "notes": "No additional yellow X was observed.",
                }
            ],
        },
    }

    machine_payload = gtfo_stagger_module._aggregate_stagger_attempts(
        feature_id="feature_001",
        input_execution_mode="local",
        acceptance_criteria=(VISUAL_CRITERION,),
        runtime_verification_plan=("Run the enabled GTFO mode.",),
        attempt_payloads=[machine_only],
        expected_modes=("general_enabled_true",),
    )
    assert machine_payload["runtime_failure_diagnosis"]["status"] == "diagnosed"
    assert machine_payload["failure_ownership"]["owner"] == "product_behavior"

    unbound_machine = {
        **machine_only,
        "runtime_trust_binding": {
            "checks": {
                **base_attempt["runtime_trust_binding"]["checks"],
                "deployed_plugin_artifact_hash": {"status": "blocked"},
            }
        },
    }
    unbound_payload = gtfo_stagger_module._aggregate_stagger_attempts(
        feature_id="feature_001",
        input_execution_mode="local",
        acceptance_criteria=(VISUAL_CRITERION,),
        runtime_verification_plan=("Run the enabled GTFO mode.",),
        attempt_payloads=[unbound_machine],
        expected_modes=("general_enabled_true",),
    )
    assert "runtime_failure_diagnosis" not in unbound_payload
    assert unbound_payload["stagger_acceptance_evaluation"][
        "overall_acceptance"
    ] == "inconclusive"
    assert unbound_payload["failure_ownership"]["owner"] == "observation"

    manual_payload = gtfo_stagger_module._aggregate_stagger_attempts(
        feature_id="feature_001",
        input_execution_mode="local",
        acceptance_criteria=(VISUAL_CRITERION,),
        runtime_verification_plan=("Run the enabled GTFO mode.",),
        attempt_payloads=[manual_only],
        expected_modes=("general_enabled_true",),
    )
    assert "runtime_failure_diagnosis" not in manual_payload
    assert manual_payload["stagger_acceptance_evaluation"][
        "overall_acceptance"
    ] == "failed"
    assert manual_payload["failure_ownership"]["owner"] == "product_behavior"
    assert manual_payload["failure_ownership"]["failure_class"] == (
        "product_behavior"
    )


def test_stagger_repair_attempt_projection_does_not_inherit_old_dll_results() -> None:
    projection = _repair_attempt_projection()
    repair_attempt = projection["repair_attempt"]

    assert repair_attempt["build_status"] == "passed"
    assert repair_attempt["runtime_status"] == "not_started"
    assert repair_attempt["final_status"] is None
    assert repair_attempt["human_intervention_count"] is None
    assert repair_attempt["additional_evidence_rounds"] is None
    results = projection["criterion_results"]
    assert isinstance(results, list)
    assert len(results) == 3
    assert {item["criterion_status"] for item in results} == {"not_evaluated"}
    assert {item["dll_sha256"] for item in results} == {"8" * 64}
    assert all(item["prior_result_inherited"] is False for item in results)
    assert next(
        item for item in results if item["acceptance_criterion"] == VISUAL_CRITERION
    )["impact_status"] == "invalidated"
    assert next(
        item for item in results if item["acceptance_criterion"] == MARKER_CRITERION
    )["operator_required"] is False


def test_stagger_repair_attempt_preserves_partial_criterion_results() -> None:
    projection = _repair_attempt_projection()
    disabled_attempt = {
        "runtime_attempt_id": "runtime_disabled_001",
        "acceptance_contract": {
            "acceptance_criteria": [DISABLED_CRITERION],
        },
    }
    enabled_attempt = {
        "runtime_attempt_id": "runtime_enabled_001",
        "acceptance_contract": {
            "acceptance_criteria": [VISUAL_CRITERION],
        },
    }
    bound = bind_stagger_repair_attempt_runtime_results(
        projection,
        acceptance_evaluation={
            "overall_acceptance": "failed",
            "criteria": [
                {
                    "acceptance_criterion": DISABLED_CRITERION,
                    "outcome": "true",
                    "evidence_refs": [
                        {"source": "gtfo_operator_completion", "locator": "a" * 64}
                    ],
                },
                {
                    "acceptance_criterion": VISUAL_CRITERION,
                    "outcome": "false",
                    "evidence_refs": [
                        {"source": "gtfo_operator_completion", "locator": "b" * 64}
                    ],
                },
                {
                    "acceptance_criterion": MARKER_CRITERION,
                    "outcome": "not_observed",
                    "evidence_refs": [],
                },
            ]
        },
        attempt_payloads=(disabled_attempt, enabled_attempt),
    )

    results = {
        item["acceptance_criterion"]: item
        for item in bound["criterion_results"]
    }
    assert results[DISABLED_CRITERION]["criterion_status"] == "passed"
    assert results[DISABLED_CRITERION]["runtime_attempt_id"] == (
        "runtime_disabled_001"
    )
    assert results[VISUAL_CRITERION]["criterion_status"] == "failed"
    assert results[VISUAL_CRITERION]["runtime_attempt_id"] == "runtime_enabled_001"
    assert results[MARKER_CRITERION]["criterion_status"] == "not_evaluated"
    assert results[MARKER_CRITERION]["runtime_attempt_id"] is None
    assert bound["repair_attempt"]["runtime_status"] == "failed"
    assert bound["repair_attempt"]["final_status"] == "failed"


def test_stagger_observation_retry_inherits_passed_results_for_same_dll() -> None:
    projection = _repair_attempt_projection()
    prior_results = []
    for item in projection["criterion_results"]:
        if item["acceptance_criterion"] == VISUAL_CRITERION:
            continue
        prior = dict(item)
        prior["criterion_status"] = "passed"
        prior["runtime_attempt_id"] = "runtime_initial_001"
        prior["evidence_refs"] = [
            {"source": "gtfo_operator_completion", "locator": "a" * 64}
        ]
        prior_results.append(prior)
    enabled_attempt = {
        "runtime_attempt_id": "runtime_retry_001",
        "acceptance_contract": {"acceptance_criteria": [VISUAL_CRITERION]},
        "operator_completion": {
            "request_sha256": "b" * 64,
            "semantic_consistency": {"status": "consistent"},
            "observations": [
                {
                    "acceptance_criterion": VISUAL_CRITERION,
                    "criterion_sha256": "c" * 64,
                    "semantic_consistency": "consistent",
                    "status": "passed",
                }
            ],
        },
        "evidence_items": [],
    }
    prior_ref = {
        "path": "runtime-evidence.json",
        "artifact_hash": "d" * 64,
    }

    evaluation = evaluate_stagger_acceptance(
        {"general_enabled_true": enabled_attempt},
        expected_modes=("general_enabled_true",),
        acceptance_criteria=(
            DISABLED_CRITERION,
            VISUAL_CRITERION,
            MARKER_CRITERION,
        ),
        prior_criterion_results=tuple(prior_results),
        prior_runtime_evidence_ref=prior_ref,
    )
    bound = bind_stagger_repair_attempt_runtime_results(
        projection,
        acceptance_evaluation=evaluation,
        attempt_payloads=(enabled_attempt,),
    )

    assert evaluation["overall_acceptance"] == "accepted"
    results = {
        item["acceptance_criterion"]: item
        for item in bound["criterion_results"]
    }
    assert results[VISUAL_CRITERION]["prior_result_inherited"] is False
    assert results[VISUAL_CRITERION]["runtime_attempt_id"] == "runtime_retry_001"
    assert results[DISABLED_CRITERION]["prior_result_inherited"] is True
    assert results[DISABLED_CRITERION]["runtime_attempt_id"] == (
        "runtime_initial_001"
    )
    assert results[DISABLED_CRITERION]["prior_runtime_evidence_ref"] == {
        "source": "prior_runtime_evidence",
        "locator": "runtime-evidence.json",
        "artifact_hash": "d" * 64,
    }
    assert results[MARKER_CRITERION]["prior_result_inherited"] is True
    assert bound["repair_attempt"]["runtime_status"] == "passed"
    assert bound["repair_attempt"]["final_status"] == "accepted"
    assert bound["repair_attempt"]["runtime_attempt_ids"] == [
        "runtime_initial_001",
        "runtime_retry_001",
    ]


def test_stagger_observation_retry_preflight_projects_inherited_results() -> None:
    projection = _repair_attempt_projection()
    prior = dict(projection["criterion_results"][0])
    prior["criterion_status"] = "passed"
    prior["runtime_attempt_id"] = "runtime_initial_001"
    prior["evidence_refs"] = [
        {"source": "gtfo_operator_completion", "locator": "a" * 64}
    ]

    inherited = inherit_stagger_repair_attempt_prior_results(
        projection,
        prior_criterion_results=(prior,),
        prior_runtime_evidence_ref={
            "path": "runtime-evidence.json",
            "artifact_hash": "b" * 64,
        },
        retry_number=1,
    )

    results = inherited["criterion_results"]
    assert results[0]["criterion_status"] == "passed"
    assert results[0]["prior_result_inherited"] is True
    assert results[1]["criterion_status"] == "not_evaluated"
    assert inherited["repair_attempt"]["retry_count"] == 1
    assert inherited["repair_attempt"]["runtime_status"] == "not_started"
    assert inherited["repair_attempt"]["final_status"] is None
    assert inherited["repair_attempt"]["runtime_attempt_ids"] == [
        "runtime_initial_001"
    ]


def test_stagger_observation_retry_selects_only_unresolved_bound_criteria() -> None:
    checkpoint = {
        "state_snapshot": {
            "artifacts": {"build_result": "build-result.json"},
            "artifact_hashes": {"build_result": "a" * 64},
        }
    }
    base_result = {
        "schema_version": "criterion_result_v1",
        "source_sha256": "b" * 64,
        "source_snapshot_sha256": "c" * 64,
        "dll_sha256": "d" * 64,
        "impact_status": "needs_regression",
        "operator_required": True,
        "prior_result_inherited": False,
        "evidence_refs": [],
    }
    runtime = {
        "acceptance_contract": {
            "acceptance_criteria": [DISABLED_CRITERION, VISUAL_CRITERION]
        },
        "repair_attempt": {
            "source_sha256": "b" * 64,
            "source_snapshot_sha256": "c" * 64,
            "dll_sha256": "d" * 64,
            "identity_refs": {
                "build_result": {
                    "path": "build-result.json",
                    "artifact_hash": "a" * 64,
                }
            },
        },
        "criterion_results": [
            {
                **base_result,
                "acceptance_criterion": DISABLED_CRITERION,
                "criterion_status": "passed",
                "runtime_attempt_id": "runtime_initial_disabled",
            },
            {
                **base_result,
                "acceptance_criterion": VISUAL_CRITERION,
                "criterion_status": "inconclusive",
                "runtime_attempt_id": "runtime_initial_enabled",
            },
        ],
    }

    binding = build_stagger_observation_retry_criterion_binding(
        runtime,
        checkpoint,
    )

    assert binding["retry_acceptance_criteria"] == [VISUAL_CRITERION]
    assert binding["retry_modes"] == ["general_enabled_true"]
    assert binding["inherited_criterion_results"] == [
        runtime["criterion_results"][0]
    ]

    runtime["criterion_results"][0]["dll_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="CriterionResult identity changed"):
        build_stagger_observation_retry_criterion_binding(
            runtime,
            checkpoint,
        )
