"""Run-local GTFO Stagger diagnostics with explicit output isolation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...core.settings import load_settings
from .deployment import temporarily_deploy_verified_plugin
from .gtfo_automation import (
    GTFORealRuntimeAutomationRunner,
    profile_from_settings,
)
from .gtfo_stagger import (
    bind_stagger_attempt_restoration,
    temporarily_deploy_gtfo_config,
)


class StaggerDiagnosticHarnessError(ValueError):
    """Raised when an isolated Stagger diagnostic cannot run safely."""


def run_isolated_stagger_hud_parent_diagnostic(
    *,
    output_root: str | Path,
    run_id: str,
    feature_id: str,
    settings_path: str | Path,
    build_dll_path: str | Path,
    diagnostic_config_path: str | Path,
    dll_destination_path: str | Path,
    config_destination_path: str | Path,
    diagnostic_criterion: str,
    diagnostic_marker: str,
    allow_game_launch: bool,
    allow_game_directory_write: bool,
    runner: GTFORealRuntimeAutomationRunner | None = None,
) -> dict[str, Any]:
    """Execute one diagnostic whose every generated file uses ``output_root``."""

    root = _empty_absolute_output_root(output_root)
    if not run_id or not feature_id:
        raise StaggerDiagnosticHarnessError(
            "run_id and feature_id must be non-empty."
        )
    if not diagnostic_criterion or not diagnostic_marker:
        raise StaggerDiagnosticHarnessError(
            "Diagnostic criterion and marker must be non-empty."
        )
    settings_file = _existing_absolute_file(
        settings_path,
        "settings_path",
    )
    build_dll = _existing_absolute_file(
        build_dll_path,
        "build_dll_path",
    )
    diagnostic_config = _existing_absolute_file(
        diagnostic_config_path,
        "diagnostic_config_path",
    )
    dll_destination = _absolute_path(
        dll_destination_path,
        "dll_destination_path",
    )
    config_destination = _absolute_path(
        config_destination_path,
        "config_destination_path",
    )

    settings = load_settings(settings_file)
    base_profile = profile_from_settings(
        settings,
        acceptance_markers={
            diagnostic_criterion: diagnostic_marker,
        },
    )
    profile = replace(
        base_profile,
        profile_id="gtfo_stagger_hud_parent_diagnostic",
        screenshot_directory=str(root / "runtime_captures"),
        operator_completion_required=False,
    )
    dll_hash = _sha256(build_dll)
    config_hash = _sha256(diagnostic_config)
    dll_existed = dll_destination.is_file()
    dll_hash_before = _sha256(dll_destination) if dll_existed else None
    config_existed = config_destination.is_file()
    config_hash_before = (
        _sha256(config_destination) if config_existed else None
    )
    selected_runner = runner or GTFORealRuntimeAutomationRunner()

    with temporarily_deploy_verified_plugin(
        source_path=build_dll,
        destination_path=dll_destination,
        backup_directory=root / "runtime_deployment_backup",
        expected_source_sha256=dll_hash,
        allow_game_directory_write=allow_game_directory_write,
        expected_destination_existed=dll_existed,
        expected_destination_sha256=dll_hash_before,
    ) as plugin_deployment:
        with temporarily_deploy_gtfo_config(
            mode="general_enabled_true_diagnostic",
            source_path=diagnostic_config,
            expected_source_sha256=config_hash,
            destination_path=config_destination,
            backup_directory=root / "runtime_config_backup",
            allow_game_directory_write=allow_game_directory_write,
            expected_destination_existed=config_existed,
            expected_destination_sha256=config_hash_before,
        ) as config_deployment:
            payload = selected_runner.run(
                feature_id=feature_id,
                profile=profile,
                acceptance_criteria=(diagnostic_criterion,),
                runtime_verification_plan=(
                    "Launch the reviewed GTFO executable.",
                    "Observe only current-run BepInEx log bytes.",
                    "Stop after the bound diagnostic marker.",
                ),
                input_execution_mode="isolated_apply",
                allow_game_launch=allow_game_launch,
                process_diagnostic_directory=(
                    root / "process_diagnostics"
                ),
            )

    bound = bind_stagger_attempt_restoration(
        payload,
        mode="general_enabled_true_diagnostic",
        plugin_deployment=plugin_deployment,
        config_deployment=config_deployment,
    )
    bound["run_id"] = run_id
    bound["diagnostic_scope"] = {
        "observation_only": True,
        "product_acceptance_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
        "diagnostic_marker": diagnostic_marker,
    }
    bound["diagnostic_run_identity"] = {
        "run_id": run_id,
        "output_root": str(root),
    }
    bound["build_dll_sha256"] = dll_hash
    bound["diagnostic_config_sha256"] = config_hash
    bound["diagnostic_run_identity"]["full_log_post_run_copy"] = (
        _capture_full_current_run_log(root, bound)
    )
    current_run_output = bound.get("raw_supplied_output")
    if not isinstance(current_run_output, str):
        raise StaggerDiagnosticHarnessError(
            "The runtime payload must contain string raw_supplied_output."
        )
    current_run_log = root / "LogOutput.current_run.log"
    _write_new_text(current_run_log, current_run_output)
    bound["diagnostic_run_identity"]["current_run_log_path"] = str(
        current_run_log
    )
    bound["diagnostic_run_identity"]["current_run_log_sha256"] = _sha256(
        current_run_log
    )
    _write_new_json(root / "runtime_result.json", bound)
    return bound


def _empty_absolute_output_root(value: str | Path) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raise StaggerDiagnosticHarnessError(
            "output_root must be absolute."
        )
    root = raw.resolve()
    if not root.is_dir():
        raise StaggerDiagnosticHarnessError(
            "output_root must be an existing directory."
        )
    if any(root.iterdir()):
        raise StaggerDiagnosticHarnessError(
            "output_root must be empty before the diagnostic."
        )
    return root


def _existing_absolute_file(value: str | Path, field_name: str) -> Path:
    path = _absolute_path(value, field_name)
    if not path.is_file():
        raise StaggerDiagnosticHarnessError(
            f"{field_name} must identify an existing file."
        )
    return path


def _absolute_path(value: str | Path, field_name: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        raise StaggerDiagnosticHarnessError(
            f"{field_name} must be absolute."
        )
    return raw.resolve()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _capture_full_current_run_log(
    root: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        windows = payload["runtime_trust_binding"]["checks"][
            "current_run_logs"
        ]["source_windows"]
    except (KeyError, TypeError) as exc:
        raise StaggerDiagnosticHarnessError(
            "Runtime trust binding lacks current-run source windows."
        ) from exc
    eligible = [
        window
        for window in windows
        if isinstance(window, dict)
        and window.get("status") == "passed"
        and window.get("mode")
        in {
            "created_or_truncated_after_prelaunch_boundary",
            "replaced_or_truncated_after_prelaunch_boundary",
        }
        and window.get("run_local_start_byte") == 0
        and isinstance(window.get("run_local_size_bytes"), int)
        and isinstance(window.get("run_local_sha256"), str)
        and isinstance(window.get("path"), str)
    ]
    if not eligible:
        raise StaggerDiagnosticHarnessError(
            "No complete current-run log generation is available."
        )
    window = max(
        eligible,
        key=lambda item: (
            int(item.get("generation", 0)),
            int(item["run_local_size_bytes"]),
        ),
    )
    source = _existing_absolute_file(
        window["path"],
        "current_run_log_source_path",
    )
    source_bytes = source.read_bytes()
    observed_size = int(window["run_local_size_bytes"])
    if len(source_bytes) < observed_size:
        raise StaggerDiagnosticHarnessError(
            "The post-run log is shorter than the observed current-run prefix."
        )
    prefix_sha256 = hashlib.sha256(
        source_bytes[:observed_size]
    ).hexdigest()
    if prefix_sha256 != window["run_local_sha256"].lower():
        raise StaggerDiagnosticHarnessError(
            "The post-run log no longer matches the observed current-run prefix."
        )
    destination = root / "LogOutput.post_run_full_copy.log"
    _write_new_bytes(destination, source_bytes)
    return {
        "path": str(destination),
        "sha256": _sha256(destination),
        "size_bytes": len(source_bytes),
        "provenance": "post_run_copy_of_current_run_generation",
        "source_path": str(source),
        "observed_prefix_sha256": prefix_sha256,
        "observed_prefix_size_bytes": observed_size,
        "observed_prefix_verified": True,
    }


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise StaggerDiagnosticHarnessError(
            "The run-local runtime_result.json already exists."
        )
    _write_new_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _write_new_text(path: Path, value: str) -> None:
    _write_new_bytes(path, value.encode("utf-8"))


def _write_new_bytes(path: Path, value: bytes) -> None:
    if path.exists():
        raise StaggerDiagnosticHarnessError(
            f"The run-local output already exists: {path.name}."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".tmp-{uuid4().hex}{path.suffix}")
    temporary.write_bytes(value)
    os.replace(temporary, path)
