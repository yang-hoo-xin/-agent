"""Bounded two-process GTFO Runtime acceptance for stagger feedback."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .deployment import (
    RuntimePluginDeploymentRecord,
    bind_plugin_deployment_to_runtime_payload,
    temporarily_deploy_verified_plugin,
)
from .evidence import (
    RuntimeEvidenceItem,
    build_real_runtime_evidence_payload,
    build_runtime_failure_ownership,
)
from .gtfo_automation import (
    GTFOLogSnapshot,
    GTFOProcessHandle,
    GTFORealRuntimeAutomationRunner,
    GTFORealRuntimeProfile,
    OperatorCompletionReader,
    ScreenshotCapturer,
)


class GTFOStaggerRuntimeError(RuntimeError):
    """Raised when the selected stagger Runtime boundary is not safe."""


@dataclass(frozen=True)
class GTFOStaggerAcceptanceProfile:
    """Exact config inputs for the selected two-process Runtime acceptance."""

    config_path: str
    disabled_config_path: str
    disabled_config_sha256: str
    enabled_config_path: str
    enabled_config_sha256: str


@dataclass
class GTFOConfigDeploymentRecord:
    """Audit record for one temporary BetterHitFeedback config deployment."""

    mode: str
    source_path: str
    source_sha256: str
    destination_path: str
    destination_existed_before: bool
    destination_sha256_before: str | None
    destination_sha256_after_copy: str
    deployed_at: str
    restored: bool = False
    restoration_status: str = "pending"
    restored_at: str | None = None
    destination_exists_after_restore: bool | None = None
    destination_sha256_after_restore: str | None = None
    restoration_error_type: str | None = None
    restoration_error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "destination_path": self.destination_path,
            "destination_existed_before": self.destination_existed_before,
            "destination_sha256_before": self.destination_sha256_before,
            "destination_sha256_after_copy": self.destination_sha256_after_copy,
            "deployed_at": self.deployed_at,
            "restored": self.restored,
            "restoration_status": self.restoration_status,
            "restored_at": self.restored_at,
            "destination_exists_after_restore": self.destination_exists_after_restore,
            "destination_sha256_after_restore": self.destination_sha256_after_restore,
            "restoration_error_type": self.restoration_error_type,
            "restoration_error_message": self.restoration_error_message,
        }


def stagger_profile_from_settings(settings: Any) -> GTFOStaggerAcceptanceProfile | None:
    """Project the optional reviewed stagger section without reading other providers."""

    runtime = getattr(settings, "runtime", None)
    gtfo = getattr(runtime, "gtfo", None)
    value = getattr(gtfo, "stagger_acceptance", None)
    if value is None or getattr(value, "enabled", False) is not True:
        return None
    return GTFOStaggerAcceptanceProfile(
        config_path=str(getattr(value, "config_path", "")),
        disabled_config_path=str(getattr(value, "disabled_config_path", "")),
        disabled_config_sha256=str(
            getattr(value, "disabled_config_sha256", "")
        ),
        enabled_config_path=str(getattr(value, "enabled_config_path", "")),
        enabled_config_sha256=str(getattr(value, "enabled_config_sha256", "")),
    )


def build_gtfo_stagger_acceptance_report(
    profile: GTFOStaggerAcceptanceProfile,
    *,
    working_directory: str | Path,
    acceptance_criteria: tuple[str, ...],
) -> dict[str, Any]:
    """Validate exact two-mode config and criterion ownership without writing."""

    blockers: list[str] = []
    working_root = Path(working_directory).resolve()
    destination = _absolute_path(profile.config_path)
    if destination is None:
        blockers.append("runtime.gtfo.stagger_acceptance.config_path must be absolute")
    elif destination.suffix.lower() != ".cfg":
        blockers.append(
            "runtime.gtfo.stagger_acceptance.config_path must identify one .cfg file"
        )
    elif not _is_within(destination, working_root):
        blockers.append(
            "runtime.gtfo.stagger_acceptance.config_path must remain inside "
            "runtime.gtfo.working_directory"
        )
    elif not destination.parent.is_dir():
        blockers.append(
            "runtime.gtfo.stagger_acceptance.config_path parent does not exist"
        )

    disabled_source = _config_source_record(
        profile.disabled_config_path,
        profile.disabled_config_sha256,
        expected_enabled=False,
    )
    enabled_source = _config_source_record(
        profile.enabled_config_path,
        profile.enabled_config_sha256,
        expected_enabled=True,
    )
    blockers.extend(disabled_source["blockers"])
    blockers.extend(enabled_source["blockers"])

    disabled_criteria = [
        criterion
        for criterion in acceptance_criteria
        if "General.Enabled=false" in criterion
    ]
    if len(disabled_criteria) != 1:
        blockers.append(
            "Stagger Runtime requires exactly one General.Enabled=false "
            "acceptance criterion"
        )
    enabled_criteria = [
        criterion
        for criterion in acceptance_criteria
        if criterion not in disabled_criteria
    ]
    if not enabled_criteria:
        blockers.append(
            "Stagger Runtime requires at least one General.Enabled=true "
            "acceptance criterion"
        )

    return {
        "schema_version": "gtfo_stagger_acceptance_report_v1",
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "writes_performed": False,
        "process_launched": False,
        "config": {
            "destination_path": (
                profile.config_path if destination is None else str(destination)
            ),
            "destination_existed": bool(
                destination is not None and destination.is_file()
            ),
            "destination_sha256": (
                _sha256_file(destination)
                if destination is not None and destination.is_file()
                else None
            ),
            "disabled": disabled_source,
            "enabled": enabled_source,
            "restore_after_each_attempt": True,
        },
        "attempts": [
            {
                "mode": "general_enabled_false",
                "acceptance_criteria": disabled_criteria,
                "requires_operator_completion": True,
                "requires_product_marker": False,
            },
            {
                "mode": "general_enabled_true",
                "acceptance_criteria": enabled_criteria,
                "requires_operator_completion": True,
                "requires_product_marker": True,
            },
        ],
    }


@contextmanager
def temporarily_deploy_gtfo_config(
    *,
    mode: str,
    source_path: str | Path,
    expected_source_sha256: str,
    destination_path: str | Path,
    backup_directory: str | Path,
    allow_game_directory_write: bool,
    expected_destination_existed: bool | None = None,
    expected_destination_sha256: str | None = None,
) -> Iterator[GTFOConfigDeploymentRecord]:
    """Deploy one reviewed config and restore its exact pre-attempt state."""

    if not allow_game_directory_write:
        raise GTFOStaggerRuntimeError(
            "GTFO config deployment requires explicit game-directory write approval."
        )
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    backup_root = Path(backup_directory).resolve()
    if not source.is_file():
        raise GTFOStaggerRuntimeError(f"Reviewed GTFO config is missing: {source}")
    expected_hash = _normalized_sha256(expected_source_sha256)
    source_hash = _sha256_file(source)
    if source_hash != expected_hash:
        raise GTFOStaggerRuntimeError(
            "Reviewed GTFO config SHA256 changed before deployment."
        )
    if not destination.is_absolute() or destination.suffix.lower() != ".cfg":
        raise GTFOStaggerRuntimeError(
            "GTFO config destination must be an absolute .cfg path."
        )
    if not destination.parent.is_dir():
        raise GTFOStaggerRuntimeError(
            f"GTFO config destination directory is missing: {destination.parent}"
        )

    destination_existed = destination.is_file()
    destination_hash_before = (
        _sha256_file(destination) if destination_existed else None
    )
    if (
        expected_destination_existed is not None
        and destination_existed != expected_destination_existed
    ):
        raise GTFOStaggerRuntimeError(
            "GTFO config destination existence changed after admission."
        )
    if (
        expected_destination_existed is not None
        and destination_hash_before != expected_destination_sha256
    ):
        raise GTFOStaggerRuntimeError(
            "GTFO config destination SHA256 changed after admission."
        )

    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = (
        backup_root / "original.bin"
        if destination_existed
        else None
    )
    deploying_path = destination.parent / (
        f".{destination.name}.{uuid4().hex}.deploying"
    )
    restoring_path = destination.parent / (
        f".{destination.name}.{uuid4().hex}.restoring"
    )
    record: GTFOConfigDeploymentRecord | None = None
    if backup_path is not None:
        shutil.copy2(destination, backup_path)
        if _sha256_file(backup_path) != destination_hash_before:
            raise GTFOStaggerRuntimeError(
                "GTFO config backup SHA256 does not match its destination."
            )
    try:
        shutil.copy2(source, deploying_path)
        if _sha256_file(deploying_path) != source_hash:
            raise GTFOStaggerRuntimeError(
                "Temporary GTFO config SHA256 does not match its reviewed source."
            )
        _replace_with_retry(deploying_path, destination)
        deployed_hash = _sha256_file(destination)
        if deployed_hash != source_hash:
            raise GTFOStaggerRuntimeError(
                "Deployed GTFO config SHA256 does not match its reviewed source."
            )
        record = GTFOConfigDeploymentRecord(
            mode=mode,
            source_path=str(source),
            source_sha256=source_hash,
            destination_path=str(destination),
            destination_existed_before=destination_existed,
            destination_sha256_before=destination_hash_before,
            destination_sha256_after_copy=deployed_hash,
            deployed_at=_utc_now(),
        )
        yield record
    finally:
        _remove_with_retry(deploying_path)
        try:
            if destination_existed:
                if backup_path is None or not backup_path.is_file():
                    raise GTFOStaggerRuntimeError(
                        "GTFO config backup is missing during restoration."
                    )
                shutil.copy2(backup_path, restoring_path)
                if _sha256_file(restoring_path) != destination_hash_before:
                    raise GTFOStaggerRuntimeError(
                        "GTFO config restore bytes do not match the original SHA256."
                    )
                _replace_with_retry(restoring_path, destination)
            else:
                _remove_with_retry(destination)
            destination_exists_after = destination.is_file()
            destination_hash_after = (
                _sha256_file(destination) if destination_exists_after else None
            )
            restored = (
                destination_exists_after == destination_existed
                and destination_hash_after == destination_hash_before
            )
            if not restored:
                raise GTFOStaggerRuntimeError(
                    "GTFO config did not return to its pre-attempt state."
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
            _remove_with_retry(restoring_path)


def bind_stagger_attempt_restoration(
    payload: Mapping[str, Any],
    *,
    mode: str,
    plugin_deployment: RuntimePluginDeploymentRecord,
    config_deployment: GTFOConfigDeploymentRecord,
) -> dict[str, Any]:
    """Bind per-attempt plugin and config restoration to Runtime trust."""

    bound = bind_plugin_deployment_to_runtime_payload(
        payload,
        deployment=plugin_deployment,
    )
    trust = dict(bound.get("runtime_trust_binding") or {})
    checks = dict(trust.get("checks") or {})
    checks["runtime_config_identity"] = {
        "status": (
            "passed"
            if (
                config_deployment.source_sha256
                == config_deployment.destination_sha256_after_copy
            )
            else "blocked"
        ),
        "mode": mode,
        "source_path": config_deployment.source_path,
        "source_sha256": config_deployment.source_sha256,
        "destination_path": config_deployment.destination_path,
        "destination_sha256_after_copy": (
            config_deployment.destination_sha256_after_copy
        ),
    }
    checks["runtime_config_restoration"] = {
        "status": (
            "passed"
            if config_deployment.restored
            and config_deployment.restoration_status == "restored"
            else "blocked"
        ),
        "mode": mode,
        "restoration_status": config_deployment.restoration_status,
        "destination_existed_before": (
            config_deployment.destination_existed_before
        ),
        "destination_sha256_before": config_deployment.destination_sha256_before,
        "destination_exists_after_restore": (
            config_deployment.destination_exists_after_restore
        ),
        "destination_sha256_after_restore": (
            config_deployment.destination_sha256_after_restore
        ),
    }
    trust["checks"] = checks
    trust["blockers"] = [
        f"{name} trust check did not pass"
        for name, check in checks.items()
        if not isinstance(check, Mapping) or check.get("status") != "passed"
    ]
    trust["status"] = (
        "pending_graph_binding" if not trust["blockers"] else "blocked"
    )
    bound["runtime_trust_binding"] = trust
    bound["stagger_attempt_mode"] = mode
    bound["stagger_config_deployment_binding"] = config_deployment.to_dict()
    bound["plugin_deployment_binding"] = plugin_deployment.to_dict()
    return bound


def make_gtfo_stagger_runtime_evidence_factory(
    *,
    base_profile: GTFORealRuntimeProfile,
    stagger_profile: GTFOStaggerAcceptanceProfile,
    allow_game_launch: bool,
    allow_game_directory_write: bool,
    build_artifact_path: str | Path,
    expected_artifact: str,
    plugin_destination_path: str | Path,
    backup_directory: str | Path,
    expected_plugin_destination_existed: bool | None = None,
    expected_plugin_destination_sha256: str | None = None,
    expected_config_destination_existed: bool | None = None,
    expected_config_destination_sha256: str | None = None,
    process_launcher: Callable[[GTFORealRuntimeProfile], GTFOProcessHandle]
    | None = None,
    log_collector: Callable[
        [GTFORealRuntimeProfile, tuple[str, ...]],
        GTFOLogSnapshot,
    ]
    | None = None,
    screenshot_capturer: ScreenshotCapturer | None = None,
    operator_completion_reader: OperatorCompletionReader | None = None,
) -> Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Build the selected two-process graph Runtime factory."""

    runner = GTFORealRuntimeAutomationRunner()
    build_path = Path(build_artifact_path)
    plugin_destination = Path(plugin_destination_path)
    backup_root = Path(backup_directory)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, Any],
        feature_spec: dict[str, Any],
    ) -> dict[str, Any]:
        acceptance_criteria = tuple(
            str(item) for item in feature_spec.get("acceptance_criteria", ())
        )
        report = build_gtfo_stagger_acceptance_report(
            stagger_profile,
            working_directory=base_profile.working_directory,
            acceptance_criteria=acceptance_criteria,
        )
        if report["status"] != "ready":
            raise GTFOStaggerRuntimeError(
                "GTFO stagger Runtime preflight blocked: "
                + "; ".join(str(item) for item in report["blockers"])
            )
        expected_plugin_sha256 = _verified_build_sha256(
            build,
            expected_artifact=expected_artifact,
        )
        attempt_payloads: list[dict[str, Any]] = []
        for attempt in report["attempts"]:
            mode = str(attempt["mode"])
            mode_criteria = tuple(
                str(item) for item in attempt["acceptance_criteria"]
            )
            if mode == "general_enabled_false":
                config_source_path = stagger_profile.disabled_config_path
                config_source_sha256 = stagger_profile.disabled_config_sha256
                mode_markers: Mapping[str, str] = {}
            elif mode == "general_enabled_true":
                config_source_path = stagger_profile.enabled_config_path
                config_source_sha256 = stagger_profile.enabled_config_sha256
                mode_markers = {
                    criterion: marker
                    for criterion, marker in base_profile.acceptance_markers.items()
                    if criterion in mode_criteria
                }
            else:
                raise GTFOStaggerRuntimeError(
                    f"Unsupported GTFO stagger Runtime mode: {mode}"
                )
            mode_profile = replace(
                base_profile,
                profile_id=f"{base_profile.profile_id}:{mode}",
                acceptance_markers=mode_markers,
                screenshot_directory=str(
                    Path(base_profile.screenshot_directory) / mode
                ),
                operator_completion_required=True,
                terminate_after_capture=True,
            )
            with temporarily_deploy_verified_plugin(
                source_path=build_path,
                destination_path=plugin_destination,
                backup_directory=backup_root / mode / "plugin",
                expected_source_sha256=expected_plugin_sha256,
                allow_game_directory_write=allow_game_directory_write,
                expected_destination_existed=(
                    expected_plugin_destination_existed
                ),
                expected_destination_sha256=expected_plugin_destination_sha256,
            ) as plugin_deployment:
                with temporarily_deploy_gtfo_config(
                    mode=mode,
                    source_path=config_source_path,
                    expected_source_sha256=config_source_sha256,
                    destination_path=stagger_profile.config_path,
                    backup_directory=backup_root / mode / "config",
                    allow_game_directory_write=allow_game_directory_write,
                    expected_destination_existed=(
                        expected_config_destination_existed
                    ),
                    expected_destination_sha256=(
                        expected_config_destination_sha256
                    ),
                ) as config_deployment:
                    payload = runner.run(
                        feature_id=feature_id,
                        profile=mode_profile,
                        acceptance_criteria=mode_criteria,
                        runtime_verification_plan=tuple(
                            str(item)
                            for item in feature_spec.get(
                                "runtime_verification_plan",
                                (),
                            )
                        ),
                        input_execution_mode=(
                            None
                            if build.get("execution_mode") is None
                            else str(build.get("execution_mode"))
                        ),
                        allow_game_launch=allow_game_launch,
                        process_launcher=process_launcher,
                        log_collector=log_collector,
                        screenshot_capturer=screenshot_capturer,
                        operator_completion_reader=operator_completion_reader,
                        process_diagnostic_directory=(
                            backup_root.parent
                            / "runtime_process_diagnostics"
                            / mode
                        ),
                    )
            bound_attempt = bind_stagger_attempt_restoration(
                payload,
                mode=mode,
                plugin_deployment=plugin_deployment,
                config_deployment=config_deployment,
            )
            attempt_payloads.append(bound_attempt)
            if bound_attempt.get("acceptance_verified") is not True:
                break
        return _aggregate_stagger_attempts(
            feature_id=feature_id,
            input_execution_mode=(
                None
                if build.get("execution_mode") is None
                else str(build.get("execution_mode"))
            ),
            acceptance_criteria=acceptance_criteria,
            runtime_verification_plan=tuple(
                str(item)
                for item in feature_spec.get("runtime_verification_plan", ())
            ),
            attempt_payloads=attempt_payloads,
            expected_modes=tuple(
                str(item["mode"]) for item in report["attempts"]
            ),
        )

    return runtime_evidence_factory


def _aggregate_stagger_attempts(
    *,
    feature_id: str,
    input_execution_mode: str | None,
    acceptance_criteria: tuple[str, ...],
    runtime_verification_plan: tuple[str, ...],
    attempt_payloads: list[dict[str, Any]],
    expected_modes: tuple[str, ...],
) -> dict[str, Any]:
    attempts_by_mode = {
        str(payload.get("stagger_attempt_mode")): payload
        for payload in attempt_payloads
    }
    complete = all(
        mode in attempts_by_mode
        and attempts_by_mode[mode].get("acceptance_verified") is True
        for mode in expected_modes
    )
    evidence_items = tuple(
        RuntimeEvidenceItem(
            item_type=str(item["type"]),
            source=str(item["source"]),
            locator=str(item["locator"]),
            supports_acceptance=tuple(
                str(value) for value in item.get("supports_acceptance", ())
            ),
            confidence=float(item.get("confidence", 0.0)),
            raw_excerpt=(
                None
                if item.get("raw_excerpt") is None
                else str(item.get("raw_excerpt"))
            ),
        )
        for payload in attempt_payloads
        for item in payload.get("evidence_items", ())
        if isinstance(item, Mapping)
    )
    enabled_payload = attempts_by_mode.get("general_enabled_true", {})
    plugin_marker_binding = dict(
        enabled_payload.get("plugin_marker_binding") or {}
    )
    screenshot_refs = tuple(
        dict(item)
        for payload in attempt_payloads
        for item in payload.get("screenshot_refs", ())
        if isinstance(item, Mapping)
    )
    check_names = (
        "feature_id",
        "runtime_process_identity",
        "current_run_logs",
        "bepinex_log_config",
        "plugin_load_marker",
        "acceptance_markers",
        "operator_completion",
        "screenshot_runtime_artifact_linkage",
        "deployed_plugin_artifact_hash",
        "game_directory_restoration",
        "runtime_config_identity",
        "runtime_config_restoration",
    )
    checks = {
        name: _aggregate_attempt_check(
            name,
            attempts_by_mode=attempts_by_mode,
            expected_modes=expected_modes,
        )
        for name in check_names
    }
    blockers = [
        f"{name} trust check did not pass"
        for name, check in checks.items()
        if check["status"] != "passed"
    ]
    runtime_trust_binding = {
        "profile_id": "gtfo_stagger_two_process_runtime",
        "evidence_source": "gtfo_real_runtime_automation",
        "deployment_required": True,
        "operator_completion_required": True,
        "status": "pending_graph_binding" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
    }
    verification_status = "verified" if complete else "inconclusive"
    payload = build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=input_execution_mode,
        evidence_items=evidence_items,
        startup_loaded=complete,
        gameplay_behavior_verified=complete,
        verification_status=verification_status,
        raw_runtime_output=None,
        limitations=(
            ()
            if complete
            else (
                "The two-process GTFO stagger Runtime did not verify every "
                "required attempt.",
            )
        ),
        acceptance_criteria=acceptance_criteria,
        runtime_verification_plan=runtime_verification_plan,
        plugin_marker_binding=plugin_marker_binding,
        screenshot_refs=screenshot_refs,
        runtime_trust_binding=runtime_trust_binding,
        failure_ownership=(
            None
            if complete
            else build_runtime_failure_ownership(
                owner="observation",
                failure_class="stagger_runtime_attempt_incomplete",
                reason=(
                    "One required GTFO stagger Runtime attempt did not produce "
                    "complete bound observations."
                ),
            )
        ),
    )
    payload["evidence_source"] = "gtfo_real_runtime_automation"
    payload["stagger_runtime_schema_version"] = (
        "gtfo_stagger_two_process_runtime_v1"
    )
    payload["stagger_runtime_attempts"] = attempt_payloads
    payload["runtime_processes"] = [
        dict(item.get("runtime_process") or {})
        for item in attempt_payloads
    ]
    return payload


def _aggregate_attempt_check(
    check_name: str,
    *,
    attempts_by_mode: Mapping[str, Mapping[str, Any]],
    expected_modes: tuple[str, ...],
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    passed = True
    for mode in expected_modes:
        payload = attempts_by_mode.get(mode)
        trust = (
            payload.get("runtime_trust_binding")
            if isinstance(payload, Mapping)
            else None
        )
        checks = trust.get("checks") if isinstance(trust, Mapping) else None
        check = checks.get(check_name) if isinstance(checks, Mapping) else None
        status = (
            str(check.get("status"))
            if isinstance(check, Mapping)
            else "missing"
        )
        attempts.append({"mode": mode, "status": status})
        if status != "passed":
            passed = False
    return {
        "status": "passed" if passed else "blocked",
        "attempts": attempts,
    }


def _verified_build_sha256(
    build: Mapping[str, Any],
    *,
    expected_artifact: str,
) -> str:
    if build.get("claims_real_build_success") is not True:
        raise GTFOStaggerRuntimeError(
            "Stagger Runtime requires a successful real Build."
        )
    matches = [
        item
        for item in build.get("verified_artifacts") or ()
        if isinstance(item, Mapping) and item.get("path") == expected_artifact
    ]
    if len(matches) != 1:
        raise GTFOStaggerRuntimeError(
            "Stagger Runtime requires exactly one verified expected artifact."
        )
    value = matches[0].get("sha256")
    if not isinstance(value, str) or not value:
        raise GTFOStaggerRuntimeError(
            "Stagger Runtime verified artifact is missing its physical SHA256."
        )
    return value


def _config_source_record(
    configured_path: str,
    configured_sha256: str,
    *,
    expected_enabled: bool,
) -> dict[str, Any]:
    path = _absolute_path(configured_path)
    blockers: list[str] = []
    exists = bool(path is not None and path.is_file())
    actual_sha256 = _sha256_file(path) if exists and path is not None else None
    expected_sha256 = None
    try:
        expected_sha256 = _normalized_sha256(configured_sha256)
    except GTFOStaggerRuntimeError as exc:
        blockers.append(str(exc))
    if path is None:
        blockers.append("Reviewed GTFO config source path must be absolute.")
    elif not exists:
        blockers.append(f"Reviewed GTFO config source is missing: {path}")
    if (
        expected_sha256 is not None
        and actual_sha256 is not None
        and expected_sha256 != actual_sha256
    ):
        blockers.append("Reviewed GTFO config source SHA256 does not match.")
    enabled_value = (
        _general_enabled_value(path)
        if path is not None and path.is_file()
        else None
    )
    if enabled_value is not expected_enabled:
        blockers.append(
            "Reviewed GTFO config must contain exactly one [General] Enabled "
            f"value equal to {str(expected_enabled).lower()}."
        )
    return {
        "configured_path": configured_path,
        "resolved_path": None if path is None else str(path),
        "exists": exists,
        "configured_sha256": configured_sha256,
        "actual_sha256": actual_sha256,
        "general_enabled": enabled_value,
        "status": "passed" if not blockers else "blocked",
        "blockers": blockers,
    }


def _general_enabled_value(path: Path) -> bool | None:
    section: str | None = None
    values: list[str] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "General" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "Enabled":
            values.append(value.split("#", 1)[0].strip())
    if len(values) != 1 or values[0].lower() not in {"true", "false"}:
        return None
    return values[0].lower() == "true"


def _absolute_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        return None
    return path.resolve()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalized_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized.removeprefix("sha256:")
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise GTFOStaggerRuntimeError(
            "Reviewed GTFO config SHA256 must contain exactly 64 hex characters."
        )
    return normalized


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _remove_with_retry(
    path: Path,
    *,
    attempts: int = 20,
    delay_seconds: float = 0.25,
) -> None:
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
    for attempt in range(attempts):
        try:
            if destination.exists():
                destination.chmod(
                    destination.stat().st_mode | stat.S_IWRITE
                )
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(delay_seconds)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
