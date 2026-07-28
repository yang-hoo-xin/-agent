"""GTFO real runtime automation with explicit launch approval."""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence import (
    RuntimeEvidenceItem,
    build_real_runtime_evidence_payload,
    build_runtime_failure_ownership,
)
from .screenshots import ScreenshotMetadata, build_screenshot_metadata


class GTFORuntimeAutomationError(ValueError):
    """Raised when real GTFO runtime automation cannot run safely."""


@dataclass(frozen=True)
class GTFORealRuntimeProfile:
    """Configuration required to launch GTFO and collect runtime evidence."""

    profile_id: str
    game_executable: str
    working_directory: str
    launch_args: tuple[str, ...] = ()
    log_paths: tuple[str, ...] = ()
    screenshot_directory: str = "./artifacts/runtime/screenshots"
    screenshot_timeout_seconds: int = 15
    startup_markers: tuple[str, ...] = ()
    acceptance_markers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: int = 120
    poll_interval_seconds: float = 1.0
    output_limit_chars: int = 20_000
    terminate_after_capture: bool = False

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise GTFORuntimeAutomationError("profile_id is required")
        if self.timeout_seconds <= 0:
            raise GTFORuntimeAutomationError("timeout_seconds must be positive")
        if self.poll_interval_seconds <= 0:
            raise GTFORuntimeAutomationError("poll_interval_seconds must be positive")
        if self.output_limit_chars <= 0:
            raise GTFORuntimeAutomationError("output_limit_chars must be positive")
        if self.screenshot_timeout_seconds <= 0:
            raise GTFORuntimeAutomationError("screenshot_timeout_seconds must be positive")


@dataclass(frozen=True)
class GTFOProcessHandle:
    """Launched process handle used by the automation runner."""

    pid: int
    process: Any = None
    diagnostics: Any = None


@dataclass(frozen=True)
class GTFOLogSnapshot:
    """Collected persistent runtime log content."""

    content: str
    sources: tuple[str, ...]
    truncated: bool = False
    run_boundary_status: str = "collector_asserted_current_run"
    source_windows: tuple[Mapping[str, Any], ...] = ()
    marker_observations: tuple[Mapping[str, Any], ...] | None = None


@dataclass(frozen=True)
class _GTFOLogFileBaseline:
    """Pre-launch byte identity for one configured persistent log."""

    path: str
    existed: bool
    size_bytes: int
    content_sha256: str | None
    mtime_ns: int | None
    captured_at_ns: int


class _BoundedProcessOutput:
    """Thread-safe newest-byte buffer for one launched process stream."""

    def __init__(self, *, limit_bytes: int) -> None:
        self._limit_bytes = limit_bytes
        self._content = bytearray()
        self._total_size_bytes = 0
        self._lock = threading.Lock()

    def append(self, content: bytes) -> None:
        if not content:
            return
        with self._lock:
            self._total_size_bytes += len(content)
            self._content.extend(content)
            if len(self._content) > self._limit_bytes:
                del self._content[: len(self._content) - self._limit_bytes]

    def snapshot(self) -> tuple[bytes, int, bool]:
        with self._lock:
            retained = bytes(self._content)
            total_size = self._total_size_bytes
        return retained, total_size, total_size > len(retained)


class _GTFOProcessDiagnosticsCapture:
    """Drain stdout/stderr without feeding either stream into acceptance."""

    def __init__(
        self,
        *,
        output_directory: Path,
        feature_id: str,
        output_limit_chars: int,
    ) -> None:
        self._output_directory = output_directory
        self._feature_id = feature_id
        self._capture_id = str(time.time_ns())
        self._stdout = _BoundedProcessOutput(limit_bytes=output_limit_chars)
        self._stderr = _BoundedProcessOutput(limit_bytes=output_limit_chars)
        self._threads: list[threading.Thread] = []

    def start(self, process: Any) -> None:
        for name, stream, output in (
            ("stdout", getattr(process, "stdout", None), self._stdout),
            ("stderr", getattr(process, "stderr", None), self._stderr),
        ):
            if stream is None:
                continue
            thread = threading.Thread(
                target=self._drain,
                args=(stream, output),
                name=f"gtfo-{name}-diagnostic-drain",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    @staticmethod
    def _drain(stream: Any, output: _BoundedProcessOutput) -> None:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            output.append(bytes(chunk))

    def snapshot(self) -> dict[str, Any]:
        for thread in self._threads:
            thread.join(timeout=0.2)
        self._output_directory.mkdir(parents=True, exist_ok=True)
        return {
            "status": "captured",
            "observation_scope": "run_local_process_output",
            "supports_acceptance": [],
            "stdout": self._stream_snapshot("stdout", self._stdout),
            "stderr": self._stream_snapshot("stderr", self._stderr),
        }

    def _stream_snapshot(
        self,
        stream_name: str,
        output: _BoundedProcessOutput,
    ) -> dict[str, Any]:
        retained, total_size, truncated = output.snapshot()
        path = (
            self._output_directory
            / f"{self._feature_id}_{self._capture_id}.{stream_name}.log"
        )
        path.write_bytes(retained)
        return {
            "file_path": str(path),
            "content_sha256": hashlib.sha256(retained).hexdigest(),
            "retained_size_bytes": len(retained),
            "total_size_bytes": total_size,
            "truncated": truncated,
        }


ProcessLauncher = Callable[[GTFORealRuntimeProfile], GTFOProcessHandle]
LogCollector = Callable[[GTFORealRuntimeProfile, tuple[str, ...]], GTFOLogSnapshot]
ScreenshotCapturer = Callable[[GTFORealRuntimeProfile, str], ScreenshotMetadata | None]


def _bepinex_log_config_binding(
    working_directory: Path | None,
) -> dict[str, Any]:
    configured_path = "BepInEx/config/BepInEx.cfg"
    resolved_path = (
        None
        if working_directory is None
        else working_directory / Path(configured_path)
    )
    binding: dict[str, Any] = {
        "status": "blocked",
        "configured_path": configured_path,
        "resolved_path": None if resolved_path is None else str(resolved_path),
        "exists": False,
        "is_file": False,
        "content_sha256": None,
        "section": "Logging.Disk",
        "key": "AppendLog",
        "append_log_value": None,
        "append_log_enabled": None,
    }
    if resolved_path is None or not resolved_path.is_file():
        return binding
    binding["exists"] = True
    binding["is_file"] = True
    try:
        content = resolved_path.read_bytes()
    except OSError as exc:
        binding["read_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return binding
    binding["content_sha256"] = hashlib.sha256(content).hexdigest()
    section: str | None = None
    values: list[str] = []
    for raw_line in content.decode("utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "Logging.Disk" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "AppendLog":
            values.append(value.split("#", 1)[0].strip())
    if len(values) != 1 or values[0].lower() not in {"true", "false"}:
        return binding
    binding["status"] = "passed"
    binding["append_log_value"] = values[0]
    binding["append_log_enabled"] = values[0].lower() == "true"
    return binding


def build_gtfo_runtime_capability_report(
    profile: GTFORealRuntimeProfile,
    *,
    allow_game_launch: bool,
    acceptance_criteria: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Inspect GTFO runtime automation readiness without launching the game."""

    blockers: list[str] = []
    warnings: list[str] = []
    working_directory = Path(profile.working_directory) if profile.working_directory else None
    executable = Path(profile.game_executable) if profile.game_executable else None

    checks: dict[str, Any] = {
        "explicit_launch_approval": {
            "status": "passed" if allow_game_launch else "blocked",
            "required": True,
            "allow_game_launch": allow_game_launch,
        },
        "game_executable": {
            "status": "passed",
            "configured_path": profile.game_executable,
            "exists": False,
            "is_file": False,
        },
        "working_directory": {
            "status": "passed",
            "configured_path": profile.working_directory,
            "exists": False,
            "is_dir": False,
        },
        "log_paths": {
            "status": "passed",
            "configured_paths": list(profile.log_paths),
            "resolved_paths": [],
        },
        "bepinex_log_config": _bepinex_log_config_binding(working_directory),
        "screenshot_directory": {
            "status": "passed",
            "configured_path": profile.screenshot_directory,
        },
        "startup_markers": {
            "status": "passed",
            "configured_markers": list(profile.startup_markers),
        },
        "acceptance_markers": {
            "status": "passed",
            "configured_markers": dict(profile.acceptance_markers),
            "acceptance_criteria": list(acceptance_criteria),
            "missing_acceptance_criteria": [],
        },
    }

    if not allow_game_launch:
        blockers.append("GTFO game launch requires explicit approval")

    if executable is None:
        checks["game_executable"]["status"] = "blocked"
        blockers.append("runtime.gtfo.game_executable is required")
    else:
        checks["game_executable"]["exists"] = executable.exists()
        checks["game_executable"]["is_file"] = executable.is_file()
        if not executable.exists() or not executable.is_file():
            checks["game_executable"]["status"] = "blocked"
            blockers.append(f"GTFO executable does not exist: {profile.game_executable}")

    if working_directory is None:
        checks["working_directory"]["status"] = "blocked"
        blockers.append("runtime.gtfo.working_directory is required")
    else:
        checks["working_directory"]["exists"] = working_directory.exists()
        checks["working_directory"]["is_dir"] = working_directory.is_dir()
        if not working_directory.exists() or not working_directory.is_dir():
            checks["working_directory"]["status"] = "blocked"
            blockers.append(
                f"GTFO working directory does not exist: {profile.working_directory}"
            )

    if not profile.log_paths:
        checks["log_paths"]["status"] = "blocked"
        blockers.append("runtime.gtfo.log_paths must not be empty")
    else:
        resolved_paths: list[dict[str, Any]] = []
        for configured_path in profile.log_paths:
            path = Path(configured_path)
            if not path.is_absolute() and working_directory is not None:
                path = working_directory / path
            resolved_paths.append(
                {
                    "configured_path": configured_path,
                    "resolved_path": str(path),
                    "exists": path.exists(),
                    "is_file": path.is_file(),
                }
            )
        checks["log_paths"]["resolved_paths"] = resolved_paths

    if checks["bepinex_log_config"]["status"] != "passed":
        blockers.append(
            "BepInEx/config/BepInEx.cfg must contain exactly one "
            "[Logging.Disk] AppendLog boolean value"
        )

    if not profile.screenshot_directory:
        checks["screenshot_directory"]["status"] = "blocked"
        blockers.append("runtime.gtfo.screenshot_directory is required")

    if not profile.startup_markers:
        checks["startup_markers"]["status"] = "warning"
        warnings.append("runtime.gtfo.startup_markers is empty")

    missing_acceptance_criteria = [
        criterion
        for criterion in acceptance_criteria
        if criterion not in profile.acceptance_markers
    ]
    if missing_acceptance_criteria:
        checks["acceptance_markers"]["missing_acceptance_criteria"] = list(
            missing_acceptance_criteria
        )
        configured_acceptance_criteria = [
            criterion
            for criterion in acceptance_criteria
            if criterion in profile.acceptance_markers
        ]
        if configured_acceptance_criteria:
            checks["acceptance_markers"]["status"] = "warning"
            warnings.append(
                "GTFO Runtime acceptance criteria without configured markers require "
                "separate observation and cannot be verified by plugin markers"
            )
        else:
            checks["acceptance_markers"]["status"] = "blocked"
            blockers.append(
                "GTFO runtime profile has no acceptance marker for every criterion"
            )

    status = "ready" if not blockers else "blocked"
    return {
        "profile_id": profile.profile_id,
        "status": status,
        "would_launch": status == "ready" and allow_game_launch,
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "planned_evidence_sources": {
            "process": bool(profile.game_executable and profile.working_directory),
            "process_diagnostics": bool(profile.screenshot_directory),
            "persistent_logs": bool(profile.log_paths),
            "bepinex_log_config": True,
            "desktop_screenshot": bool(profile.screenshot_directory),
            "plugin_markers": bool(profile.acceptance_markers),
        },
    }


class GTFORealRuntimeAutomationRunner:
    """Launch GTFO, poll runtime logs, capture a screenshot, and build evidence."""

    def run(
        self,
        *,
        feature_id: str,
        profile: GTFORealRuntimeProfile,
        acceptance_criteria: tuple[str, ...],
        runtime_verification_plan: tuple[str, ...],
        input_execution_mode: str | None,
        allow_game_launch: bool = False,
        process_launcher: ProcessLauncher | None = None,
        log_collector: LogCollector | None = None,
        screenshot_capturer: ScreenshotCapturer | None = None,
        process_diagnostic_directory: str | Path | None = None,
    ) -> dict[str, Any]:
        """Run real GTFO automation only after explicit approval."""

        capability_report = build_gtfo_runtime_capability_report(
            profile,
            allow_game_launch=allow_game_launch,
            acceptance_criteria=acceptance_criteria,
        )
        if capability_report["status"] == "blocked":
            return _payload_from_runtime_failure(
                feature_id=feature_id,
                profile=profile,
                failure=GTFORuntimeAutomationError(
                    "GTFO runtime capability report blocked: "
                    + "; ".join(capability_report["blockers"])
                ),
                process_handle=None,
                acceptance_criteria=acceptance_criteria,
                runtime_verification_plan=runtime_verification_plan,
                input_execution_mode=input_execution_mode,
                capability_report=capability_report,
                failure_stage="capability_admission",
                process_diagnostics=_unavailable_process_diagnostics(),
            )
        failure_stage = "profile_validation"
        failure: Exception | None = None
        process_handle: GTFOProcessHandle | None = None
        process_diagnostics = _unavailable_process_diagnostics()
        try:
            _validate_real_profile(profile)

            launcher = process_launcher or (
                lambda active_profile: _launch_gtfo_process(
                    active_profile,
                    feature_id=feature_id,
                    output_directory=(
                        Path(process_diagnostic_directory)
                        if process_diagnostic_directory is not None
                        else Path(active_profile.screenshot_directory)
                    ),
                )
            )
            capturer = screenshot_capturer or _capture_desktop_screenshot
            log_baselines = _capture_log_baselines(profile)
            collector = log_collector or (
                lambda active_profile, criteria: _collect_persistent_logs(
                    active_profile,
                    criteria,
                    baselines=log_baselines,
                )
            )

            failure_stage = "process_launch"
            process_handle = launcher(profile)
            process_liveness_observed = _process_liveness_observed(process_handle)
            failure_stage = "log_collection"
            log_snapshot = collector(profile, acceptance_criteria)
            failure_stage = "screenshot_capture"
            screenshot = capturer(profile, feature_id)
        except Exception as exc:
            failure = exc
        finally:
            if process_handle is not None and profile.terminate_after_capture:
                _terminate_process(process_handle)
            process_diagnostics = _snapshot_process_diagnostics(process_handle)

        if failure is not None:
            return _payload_from_runtime_failure(
                feature_id=feature_id,
                profile=profile,
                failure=failure,
                process_handle=process_handle,
                acceptance_criteria=acceptance_criteria,
                runtime_verification_plan=runtime_verification_plan,
                input_execution_mode=input_execution_mode,
                capability_report=capability_report,
                failure_stage=failure_stage,
                process_diagnostics=process_diagnostics,
            )

        return _payload_from_runtime_observations(
            feature_id=feature_id,
            profile=profile,
            process_handle=process_handle,
            process_liveness_observed=process_liveness_observed,
            log_snapshot=log_snapshot,
            screenshot=screenshot,
            acceptance_criteria=acceptance_criteria,
            runtime_verification_plan=runtime_verification_plan,
            input_execution_mode=input_execution_mode,
            capability_report=capability_report,
            process_diagnostics=process_diagnostics,
        )


def profile_from_settings(
    settings: Any,
    *,
    acceptance_markers: Mapping[str, str] | None = None,
) -> GTFORealRuntimeProfile:
    """Build a GTFO runtime profile from ``Settings.runtime.gtfo``."""

    runtime = getattr(settings, "runtime", None)
    gtfo = getattr(runtime, "gtfo", None)
    if gtfo is None or not getattr(gtfo, "enabled", False):
        raise GTFORuntimeAutomationError("runtime.gtfo.enabled is false or missing")
    configured_acceptance_markers = getattr(gtfo, "acceptance_markers", {})
    effective_acceptance_markers = (
        configured_acceptance_markers
        if acceptance_markers is None
        else acceptance_markers
    )
    return GTFORealRuntimeProfile(
        profile_id="gtfo_real_runtime",
        game_executable=gtfo.game_executable,
        working_directory=gtfo.working_directory,
        launch_args=tuple(gtfo.launch_args),
        log_paths=tuple(gtfo.log_paths),
        screenshot_directory=gtfo.screenshot_directory,
        screenshot_timeout_seconds=gtfo.screenshot_timeout_seconds,
        startup_markers=tuple(gtfo.startup_markers),
        acceptance_markers=dict(effective_acceptance_markers),
        timeout_seconds=gtfo.timeout_seconds,
        poll_interval_seconds=gtfo.poll_interval_seconds,
        output_limit_chars=gtfo.output_limit_chars,
        terminate_after_capture=gtfo.terminate_after_capture,
    )


def make_gtfo_runtime_evidence_factory(
    *,
    profile: GTFORealRuntimeProfile,
    allow_game_launch: bool,
    process_launcher: ProcessLauncher | None = None,
    log_collector: LogCollector | None = None,
    screenshot_capturer: ScreenshotCapturer | None = None,
    process_diagnostic_directory: str | Path | None = None,
) -> Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Build a graph-compatible runtime evidence factory for real GTFO runs."""

    runner = GTFORealRuntimeAutomationRunner()

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, Any],
        feature_spec: dict[str, Any],
    ) -> dict[str, Any]:
        return runner.run(
            feature_id=feature_id,
            profile=profile,
            acceptance_criteria=tuple(
                str(item) for item in feature_spec.get("acceptance_criteria", ())
            ),
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec.get("runtime_verification_plan", ())
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
            process_diagnostic_directory=process_diagnostic_directory,
        )

    return runtime_evidence_factory


def make_gtfo_runtime_evidence_factory_from_settings(
    settings: Any,
    *,
    allow_game_launch: bool,
    acceptance_markers: Mapping[str, str] | None = None,
    process_launcher: ProcessLauncher | None = None,
    log_collector: LogCollector | None = None,
    screenshot_capturer: ScreenshotCapturer | None = None,
    process_diagnostic_directory: str | Path | None = None,
) -> Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Build a graph-compatible GTFO runtime evidence factory from settings."""

    return make_gtfo_runtime_evidence_factory(
        profile=profile_from_settings(
            settings,
            acceptance_markers=acceptance_markers,
        ),
        allow_game_launch=allow_game_launch,
        process_launcher=process_launcher,
        log_collector=log_collector,
        screenshot_capturer=screenshot_capturer,
        process_diagnostic_directory=process_diagnostic_directory,
    )


def _validate_real_profile(profile: GTFORealRuntimeProfile) -> None:
    executable = Path(profile.game_executable)
    working_directory = Path(profile.working_directory)
    if not profile.game_executable:
        raise GTFORuntimeAutomationError("runtime.gtfo.game_executable is required")
    if not executable.exists() or not executable.is_file():
        raise GTFORuntimeAutomationError(
            f"GTFO executable does not exist: {profile.game_executable}"
        )
    if not profile.working_directory:
        raise GTFORuntimeAutomationError("runtime.gtfo.working_directory is required")
    if not working_directory.exists() or not working_directory.is_dir():
        raise GTFORuntimeAutomationError(
            f"GTFO working directory does not exist: {profile.working_directory}"
        )
    if not profile.log_paths:
        raise GTFORuntimeAutomationError("runtime.gtfo.log_paths must not be empty")


def _launch_gtfo_process(
    profile: GTFORealRuntimeProfile,
    *,
    feature_id: str,
    output_directory: Path,
) -> GTFOProcessHandle:
    command = (profile.game_executable, *profile.launch_args)
    process = subprocess.Popen(
        command,
        cwd=profile.working_directory,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    diagnostics = _GTFOProcessDiagnosticsCapture(
        output_directory=output_directory,
        feature_id=feature_id,
        output_limit_chars=profile.output_limit_chars,
    )
    diagnostics.start(process)
    return GTFOProcessHandle(
        pid=int(process.pid),
        process=process,
        diagnostics=diagnostics,
    )


def _unavailable_process_diagnostics() -> dict[str, Any]:
    return {
        "status": "not_available",
        "observation_scope": "run_local_process_output",
        "supports_acceptance": [],
        "stdout": None,
        "stderr": None,
    }


def _snapshot_process_diagnostics(
    process_handle: GTFOProcessHandle | None,
) -> dict[str, Any]:
    if process_handle is None or process_handle.diagnostics is None:
        return _unavailable_process_diagnostics()
    snapshot = getattr(process_handle.diagnostics, "snapshot", None)
    if not callable(snapshot):
        return _unavailable_process_diagnostics()
    try:
        return dict(snapshot())
    except Exception as exc:
        return {
            "status": "failed",
            "observation_scope": "run_local_process_output",
            "supports_acceptance": [],
            "stdout": None,
            "stderr": None,
            "failure": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


def _collect_persistent_logs(
    profile: GTFORealRuntimeProfile,
    acceptance_criteria: tuple[str, ...],
    *,
    baselines: tuple[_GTFOLogFileBaseline, ...] | None = None,
) -> GTFOLogSnapshot:
    active_baselines = baselines or _capture_log_baselines(profile)
    started = time.monotonic()
    latest_content = ""
    latest_windows: tuple[Mapping[str, Any], ...] = ()
    observed_sources: list[str] = []
    generation_state: dict[str, dict[str, Any]] = {}
    lifecycle_windows: dict[tuple[str, int], dict[str, Any]] = {}
    accumulated_observations: dict[str, Mapping[str, Any]] = {}
    wanted_markers = tuple(
        dict.fromkeys(
            marker
            for marker in (
                *profile.startup_markers,
                *(
                    profile.acceptance_markers[criterion]
                    for criterion in acceptance_criteria
                    if criterion in profile.acceptance_markers
                ),
            )
            if marker
        )
    )
    while time.monotonic() - started <= profile.timeout_seconds:
        (
            latest_content,
            _latest_sources,
            current_windows,
            current_window_content,
        ) = _read_run_local_runtime_logs(active_baselines)
        enriched_windows: list[Mapping[str, Any]] = []
        for window in current_windows:
            if window.get("status") != "passed":
                enriched_windows.append(window)
                continue
            path = str(window["path"])
            run_local_content = current_window_content[path]
            previous = generation_state.get(path)
            same_generation = (
                previous is not None
                and previous["mode"] == window["mode"]
                and run_local_content.startswith(previous["run_local_content"])
            )
            generation = (
                int(previous["generation"])
                if same_generation
                else (0 if previous is None else int(previous["generation"])) + 1
            )
            enriched = {
                **dict(window),
                "generation": generation,
            }
            generation_state[path] = {
                "generation": generation,
                "mode": window["mode"],
                "run_local_content": run_local_content,
            }
            lifecycle_key = (path, generation)
            lifecycle = lifecycle_windows.get(lifecycle_key)
            if lifecycle is None:
                lifecycle = {
                    **enriched,
                    "first_observed_at_ns": window["observed_at_ns"],
                    "last_observed_at_ns": window["observed_at_ns"],
                    "observation_count": 1,
                    "first_current_size_bytes": window["current_size_bytes"],
                    "first_run_local_size_bytes": window["run_local_size_bytes"],
                    "first_run_local_sha256": window["run_local_sha256"],
                }
                lifecycle_windows[lifecycle_key] = lifecycle
            else:
                lifecycle.update(enriched)
                lifecycle["last_observed_at_ns"] = window["observed_at_ns"]
                lifecycle["observation_count"] = int(
                    lifecycle["observation_count"]
                ) + 1
            enriched_windows.append(enriched)
            if path not in observed_sources:
                observed_sources.append(path)
            for observation in _observe_markers(
                run_local_content,
                wanted_markers,
                observation_scope="accumulated_run_local_window",
            ):
                marker = str(observation["marker"])
                if (
                    observation.get("observed") is True
                    and marker not in accumulated_observations
                ):
                    accumulated_observations[marker] = {
                        **dict(observation),
                        "source_window": dict(enriched),
                    }
        latest_windows = tuple(enriched_windows)
        if wanted_markers and all(
            marker in accumulated_observations for marker in wanted_markers
        ):
            break
        time.sleep(profile.poll_interval_seconds)
    content, truncated = _limit_text(latest_content, profile.output_limit_chars)
    blocked_windows = tuple(
        window for window in latest_windows if window.get("status") == "blocked"
    )
    boundary_passed = bool(lifecycle_windows) and not blocked_windows
    final_windows = (
        *lifecycle_windows.values(),
        *(
            window
            for window in latest_windows
            if window.get("status") != "passed"
        ),
    )
    marker_observations = tuple(
        accumulated_observations.get(marker)
        or _observe_markers(
            "",
            (marker,),
            observation_scope="accumulated_run_local_window",
        )[0]
        for marker in (
            wanted_markers
        )
    )
    return GTFOLogSnapshot(
        content=content,
        sources=tuple(observed_sources),
        truncated=truncated,
        run_boundary_status=(
            "prelaunch_byte_boundary" if boundary_passed else "blocked"
        ),
        source_windows=tuple(final_windows),
        marker_observations=marker_observations,
    )


def _capture_log_baselines(
    profile: GTFORealRuntimeProfile,
) -> tuple[_GTFOLogFileBaseline, ...]:
    working_directory = Path(profile.working_directory)
    captured_at_ns = time.time_ns()
    baselines: list[_GTFOLogFileBaseline] = []
    for configured_path in profile.log_paths:
        path = Path(configured_path)
        if not path.is_absolute():
            path = working_directory / path
        if path.is_file():
            content = path.read_bytes()
            stat_result = path.stat()
            baselines.append(
                _GTFOLogFileBaseline(
                    path=str(path),
                    existed=True,
                    size_bytes=len(content),
                    content_sha256=hashlib.sha256(content).hexdigest(),
                    mtime_ns=stat_result.st_mtime_ns,
                    captured_at_ns=captured_at_ns,
                )
            )
        else:
            baselines.append(
                _GTFOLogFileBaseline(
                    path=str(path),
                    existed=False,
                    size_bytes=0,
                    content_sha256=None,
                    mtime_ns=None,
                    captured_at_ns=captured_at_ns,
                )
            )
    return tuple(baselines)


def _read_run_local_runtime_logs(
    baselines: tuple[_GTFOLogFileBaseline, ...],
) -> tuple[
    str,
    tuple[str, ...],
    tuple[Mapping[str, Any], ...],
    Mapping[str, str],
]:
    parts: list[str] = []
    sources: list[str] = []
    windows: list[Mapping[str, Any]] = []
    window_content: dict[str, str] = {}
    for baseline in baselines:
        observed_at_ns = time.time_ns()
        path = Path(baseline.path)
        if not path.is_file():
            windows.append(
                {
                    "path": baseline.path,
                    "status": "pending",
                    "mode": "not_created_after_launch",
                    "baseline_size_bytes": baseline.size_bytes,
                    "current_size_bytes": None,
                    "observed_at_ns": observed_at_ns,
                    "baseline_content_sha256": baseline.content_sha256,
                    "observed_prefix_sha256": None,
                    "prefix_identity_status": "not_observed",
                }
            )
            continue
        content = path.read_bytes()
        stat_result = path.stat()
        current_size = len(content)
        run_bytes: bytes | None = None
        mode: str
        observed_prefix_sha256: str | None = None
        prefix_identity_status: str
        run_local_start_byte: int | None = None
        if baseline.existed and current_size >= baseline.size_bytes:
            prefix = content[: baseline.size_bytes]
            observed_prefix_sha256 = hashlib.sha256(prefix).hexdigest()
            if observed_prefix_sha256 == baseline.content_sha256:
                run_bytes = content[baseline.size_bytes :]
                mode = "appended_after_prelaunch_boundary"
                prefix_identity_status = "matched"
                run_local_start_byte = baseline.size_bytes
            elif stat_result.st_mtime_ns >= baseline.captured_at_ns:
                run_bytes = content
                mode = "replaced_or_truncated_after_prelaunch_boundary"
                prefix_identity_status = "replaced_after_launch"
                run_local_start_byte = 0
            else:
                mode = "prefix_identity_mismatch"
                prefix_identity_status = "mismatched"
        elif stat_result.st_mtime_ns >= baseline.captured_at_ns:
            run_bytes = content
            mode = "created_or_truncated_after_prelaunch_boundary"
            observed_prefix_sha256 = (
                hashlib.sha256(content).hexdigest() if content else None
            )
            prefix_identity_status = (
                "replaced_after_launch" if baseline.existed else "not_applicable"
            )
            run_local_start_byte = 0
        else:
            mode = "no_verified_post_launch_window"
            prefix_identity_status = "not_verified"
        if run_bytes is None:
            windows.append(
                {
                    "path": baseline.path,
                    "status": "blocked",
                    "mode": mode,
                    "baseline_size_bytes": baseline.size_bytes,
                    "current_size_bytes": current_size,
                    "observed_at_ns": observed_at_ns,
                    "current_mtime_ns": stat_result.st_mtime_ns,
                    "baseline_captured_at_ns": baseline.captured_at_ns,
                    "baseline_content_sha256": baseline.content_sha256,
                    "observed_prefix_sha256": observed_prefix_sha256,
                    "prefix_identity_status": prefix_identity_status,
                }
            )
            continue
        decoded = run_bytes.decode("utf-8", errors="replace")
        parts.append(decoded)
        sources.append(baseline.path)
        window_content[baseline.path] = decoded
        windows.append(
            {
                "path": baseline.path,
                "status": "passed",
                "mode": mode,
                "baseline_size_bytes": baseline.size_bytes,
                "current_size_bytes": current_size,
                "run_local_size_bytes": len(run_bytes),
                "run_local_sha256": hashlib.sha256(run_bytes).hexdigest(),
                "run_local_start_byte": run_local_start_byte,
                "run_local_end_byte": (
                    None
                    if run_local_start_byte is None
                    else run_local_start_byte + len(run_bytes)
                ),
                "observed_at_ns": observed_at_ns,
                "current_mtime_ns": stat_result.st_mtime_ns,
                "baseline_captured_at_ns": baseline.captured_at_ns,
                "baseline_content_sha256": baseline.content_sha256,
                "observed_prefix_sha256": observed_prefix_sha256,
                "prefix_identity_status": prefix_identity_status,
            }
        )
    return (
        "\n".join(parts),
        tuple(sources),
        tuple(windows),
        window_content,
    )


def _capture_desktop_screenshot(
    profile: GTFORealRuntimeProfile,
    feature_id: str,
) -> ScreenshotMetadata | None:
    output_dir = Path(profile.screenshot_directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{feature_id}_gtfo_runtime.png"
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$bounds=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bitmap=New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height; "
        "$graphics=[System.Drawing.Graphics]::FromImage($bitmap); "
        "$graphics.CopyFromScreen($bounds.Location,[System.Drawing.Point]::Empty,$bounds.Size); "
        "$bitmap.Save($env:MOD_AGENT_SCREENSHOT_OUTPUT,[System.Drawing.Imaging.ImageFormat]::Png); "
        "$graphics.Dispose(); $bitmap.Dispose();"
    )
    completed = subprocess.run(
        ("powershell", "-NoProfile", "-Command", script),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=profile.screenshot_timeout_seconds,
        env={
            **os.environ,
            "MOD_AGENT_SCREENSHOT_OUTPUT": str(output_path.resolve()),
        },
    )
    if completed.returncode != 0 or not output_path.exists():
        return None
    content_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return build_screenshot_metadata(
        screenshot_id=f"gtfo_{feature_id}",
        feature_id=feature_id,
        file_path=str(output_path),
        source="desktop_screenshot",
        captured_at=datetime.now(timezone.utc).isoformat(),
        content_hash=content_hash,
        metadata={"profile_id": profile.profile_id},
    )


def _payload_from_runtime_observations(
    *,
    feature_id: str,
    profile: GTFORealRuntimeProfile,
    process_handle: GTFOProcessHandle,
    process_liveness_observed: bool,
    log_snapshot: GTFOLogSnapshot,
    screenshot: ScreenshotMetadata | None,
    acceptance_criteria: tuple[str, ...],
    runtime_verification_plan: tuple[str, ...],
    input_execution_mode: str | None,
    capability_report: Mapping[str, Any],
    process_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    marker_observations = (
        tuple(dict(item) for item in log_snapshot.marker_observations)
        if log_snapshot.marker_observations is not None
        else _observe_markers(
            log_snapshot.content,
            (
                *profile.startup_markers,
                *(
                    profile.acceptance_markers[criterion]
                    for criterion in acceptance_criteria
                    if criterion in profile.acceptance_markers
                ),
            ),
            observation_scope="collector_snapshot_content",
        )
    )
    startup_loaded = _startup_loaded(
        log_snapshot.content,
        startup_markers=profile.startup_markers,
        marker_observations=marker_observations,
    )
    supported_criteria = _supported_criteria(
        log_snapshot.content,
        acceptance_criteria=acceptance_criteria,
        acceptance_markers=profile.acceptance_markers,
        marker_observations=marker_observations,
    )
    missing_marker_config = [
        criterion
        for criterion in acceptance_criteria
        if criterion not in profile.acceptance_markers
    ]
    missing_observations = [
        criterion
        for criterion in acceptance_criteria
        if criterion not in supported_criteria
    ]
    gameplay_behavior_verified = (
        startup_loaded
        and bool(acceptance_criteria)
        and not missing_marker_config
        and not missing_observations
    )
    verification_status = "verified" if gameplay_behavior_verified else "inconclusive"
    evidence_items = [
        RuntimeEvidenceItem(
            item_type="runtime_log",
            source="gtfo_persistent_log",
            locator=source,
            supports_acceptance=tuple(
                criterion
                for criterion in acceptance_criteria
                if criterion in supported_criteria
            ),
            confidence=1.0,
            raw_excerpt=_first_observed_marker_excerpt(
                marker_observations,
                tuple(
                    profile.acceptance_markers[criterion]
                    for criterion in supported_criteria
                ),
            ),
        )
        for source in log_snapshot.sources
    ]
    limitations = _limitations(
        process_handle=process_handle,
        log_snapshot=log_snapshot,
        screenshot=screenshot,
        missing_marker_config=missing_marker_config,
        missing_observations=missing_observations,
    )
    plugin_marker_binding = _plugin_marker_binding(
        acceptance_criteria=acceptance_criteria,
        acceptance_markers=profile.acceptance_markers,
        supported_criteria=supported_criteria,
    )
    screenshot_ref = screenshot.to_dict() if screenshot is not None else None
    runtime_process = {
        "profile_id": profile.profile_id,
        "pid": process_handle.pid,
        "launched": True,
        "liveness_observed": process_liveness_observed,
    }
    runtime_trust_binding = _runtime_trust_binding(
        feature_id=feature_id,
        profile=profile,
        process_handle=process_handle,
        runtime_process=runtime_process,
        log_snapshot=log_snapshot,
        screenshot=screenshot,
        startup_loaded=startup_loaded,
        missing_marker_config=missing_marker_config,
        missing_observations=missing_observations,
        plugin_marker_binding=plugin_marker_binding,
        marker_observations=marker_observations,
        bepinex_log_config=capability_report["checks"]["bepinex_log_config"],
    )
    payload = build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=input_execution_mode,
        evidence_items=tuple(evidence_items),
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
        verification_status=verification_status,
        raw_runtime_output=log_snapshot.content,
        non_goals_checked=(),
        limitations=limitations,
        acceptance_criteria=acceptance_criteria,
        runtime_verification_plan=runtime_verification_plan,
        plugin_marker_binding=plugin_marker_binding,
        screenshot_refs=(screenshot_ref,) if screenshot_ref is not None else (),
        runtime_trust_binding=runtime_trust_binding,
        failure_ownership=(
            None
            if verification_status == "verified"
            else build_runtime_failure_ownership(
                owner="observation",
                failure_class="runtime_observation_incomplete",
                reason=(
                    "GTFO Runtime observations did not establish every required "
                    "startup, acceptance, and trust fact."
                ),
            )
        ),
    )
    payload["evidence_source"] = "gtfo_real_runtime_automation"
    payload["sources"] = [
        *payload["sources"],
        *(
            [
                {
                    "source_type": "screenshot",
                    "claim": "Screenshot captured during GTFO runtime automation.",
                    "confidence": 0.0,
                    "attachments": [screenshot.file_path],
                }
            ]
            if screenshot is not None
            else []
        ),
    ]
    payload["runtime_process"] = runtime_process
    payload["gtfo_markers"] = {
        "startup_markers": list(profile.startup_markers),
        "startup_loaded": startup_loaded,
        "marker_observations": [dict(item) for item in marker_observations],
        "acceptance_markers_configured": [
            {
                "acceptance_criterion": criterion,
                "marker": profile.acceptance_markers[criterion],
            }
            for criterion in acceptance_criteria
            if criterion in profile.acceptance_markers
        ],
        "acceptance_markers_observed": [
            {
                "acceptance_criterion": criterion,
                "marker": profile.acceptance_markers[criterion],
            }
            for criterion in sorted(supported_criteria)
        ],
    }
    payload["screenshot"] = screenshot_ref
    payload["process_diagnostics"] = dict(process_diagnostics)
    payload["gtfo_capability_report"] = dict(capability_report)
    return payload


def _payload_from_runtime_failure(
    *,
    feature_id: str,
    profile: GTFORealRuntimeProfile,
    failure: Exception,
    process_handle: GTFOProcessHandle | None,
    acceptance_criteria: tuple[str, ...],
    runtime_verification_plan: tuple[str, ...],
    input_execution_mode: str | None,
    capability_report: Mapping[str, Any],
    failure_stage: str,
    process_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    failure_type = type(failure).__name__
    failure_message = str(failure)
    failure_ownership = _gtfo_failure_ownership(
        failure_stage=failure_stage,
        capability_report=capability_report,
    )
    payload = build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=input_execution_mode,
        evidence_items=(),
        startup_loaded=False,
        gameplay_behavior_verified=False,
        verification_status="failed",
        raw_runtime_output=None,
        non_goals_checked=(),
        limitations=(
            f"GTFO runtime automation failed before acceptance evidence: {failure_type}: {failure_message}",
        ),
        acceptance_criteria=acceptance_criteria,
        runtime_verification_plan=runtime_verification_plan,
        failure_ownership=failure_ownership,
    )
    payload["real_runtime_performed"] = process_handle is not None
    payload["evidence_source"] = "gtfo_real_runtime_automation"
    payload["message"] = "GTFO runtime automation failed and was recorded as runtime evidence."
    payload["runtime_process"] = {
        "profile_id": profile.profile_id,
        "pid": process_handle.pid if process_handle is not None else None,
        "launched": process_handle is not None,
        "liveness_observed": (
            _process_liveness_observed(process_handle)
            if process_handle is not None
            else False
        ),
    }
    payload["gtfo_markers"] = {
        "startup_markers": list(profile.startup_markers),
        "startup_loaded": False,
        "acceptance_markers_configured": [
            {
                "acceptance_criterion": criterion,
                "marker": profile.acceptance_markers[criterion],
            }
            for criterion in acceptance_criteria
            if criterion in profile.acceptance_markers
        ],
        "acceptance_markers_observed": [],
    }
    payload["screenshot"] = None
    payload["process_diagnostics"] = dict(process_diagnostics)
    payload["runtime_trust_binding"] = {
        "profile_id": profile.profile_id,
        "evidence_source": "gtfo_real_runtime_automation",
        "status": "blocked",
        "checks": {
            "runtime_process_identity": {
                "status": "blocked",
                "profile_id": profile.profile_id,
                "pid": process_handle.pid if process_handle is not None else None,
                "launched": process_handle is not None,
                "liveness_observed": (
                    _process_liveness_observed(process_handle)
                    if process_handle is not None
                    else False
                ),
            },
            "current_run_logs": {
                "status": "blocked",
                "sources": [],
                "collected_after_process_start": process_handle is not None,
            },
            "plugin_load_marker": {
                "status": "blocked",
                "startup_markers": list(profile.startup_markers),
                "startup_loaded": False,
            },
            "acceptance_markers": {
                "status": "blocked",
                "marker_source": "gtfo_persistent_log",
                "markers": [],
            },
            "screenshot_runtime_artifact_linkage": {
                "status": "blocked",
                "screenshot_ref": None,
            },
        },
        "blockers": [
            "GTFO runtime automation failed before current-run trust binding completed."
        ],
    }
    payload["failure"] = {
        "type": failure_type,
        "message": failure_message,
    }
    payload["gtfo_capability_report"] = dict(capability_report)
    return payload


def _gtfo_failure_ownership(
    *,
    failure_stage: str,
    capability_report: Mapping[str, Any],
) -> dict[str, Any]:
    checks = capability_report.get("checks")
    explicit_launch_check = (
        checks.get("explicit_launch_approval")
        if isinstance(checks, Mapping)
        else None
    )
    if (
        failure_stage == "capability_admission"
        and isinstance(explicit_launch_check, Mapping)
        and explicit_launch_check.get("status") == "blocked"
    ):
        return build_runtime_failure_ownership(
            owner="permission",
            failure_class="runtime_launch_not_authorized",
            reason="GTFO launch authority was not admitted for this Runtime attempt.",
        )
    if failure_stage in {
        "capability_admission",
        "profile_validation",
        "process_launch",
    }:
        return build_runtime_failure_ownership(
            owner="environment",
            failure_class=f"{failure_stage}_failed",
            reason=(
                "The GTFO execution environment failed before Runtime "
                "observation could complete."
            ),
        )
    if failure_stage in {"log_collection", "screenshot_capture"}:
        return build_runtime_failure_ownership(
            owner="observation",
            failure_class=f"{failure_stage}_failed",
            reason="The GTFO Runtime observation path failed after process admission.",
        )
    return build_runtime_failure_ownership(
        owner="provider",
        failure_class="gtfo_runtime_provider_failed",
        reason="The GTFO Runtime provider failed outside a classified stage.",
    )


def _startup_loaded(
    output: str,
    *,
    startup_markers: tuple[str, ...],
    marker_observations: tuple[Mapping[str, Any], ...] | None = None,
) -> bool:
    if not startup_markers:
        return bool(output.strip())
    if marker_observations is not None:
        return all(
            _marker_was_observed(marker_observations, marker)
            for marker in startup_markers
        )
    return all(marker in output for marker in startup_markers)


def _supported_criteria(
    output: str,
    *,
    acceptance_criteria: tuple[str, ...],
    acceptance_markers: Mapping[str, str],
    marker_observations: tuple[Mapping[str, Any], ...] | None = None,
) -> set[str]:
    return {
        criterion
        for criterion in acceptance_criteria
        if acceptance_markers.get(criterion)
        and (
            _marker_was_observed(
                marker_observations,
                acceptance_markers[criterion],
            )
            if marker_observations is not None
            else acceptance_markers[criterion] in output
        )
    }


def _first_observed_marker_excerpt(
    marker_observations: tuple[Mapping[str, Any], ...],
    markers: tuple[str, ...],
) -> str | None:
    for marker in markers:
        for observation in marker_observations:
            if (
                observation.get("marker") == marker
                and observation.get("observed") is True
                and isinstance(observation.get("excerpt"), str)
                and observation["excerpt"]
            ):
                return str(observation["excerpt"])
    return None


def _observe_markers(
    output: str,
    markers: tuple[str, ...],
    *,
    observation_scope: str,
) -> tuple[Mapping[str, Any], ...]:
    observations: list[Mapping[str, Any]] = []
    for marker in dict.fromkeys(item for item in markers if item):
        offset = output.find(marker)
        excerpt, excerpt_truncated = _marker_excerpt(
            output,
            marker=marker,
            offset=offset,
        )
        observations.append(
            {
                "marker": marker,
                "observed": offset >= 0,
                "run_local_character_offset": offset if offset >= 0 else None,
                "excerpt": excerpt,
                "excerpt_truncated": excerpt_truncated,
                "observation_scope": observation_scope,
            }
        )
    return tuple(observations)


def _marker_was_observed(
    marker_observations: tuple[Mapping[str, Any], ...],
    marker: str,
) -> bool:
    return any(
        observation.get("marker") == marker
        and observation.get("observed") is True
        for observation in marker_observations
    )


def _marker_excerpt(
    output: str,
    *,
    marker: str,
    offset: int,
    max_chars: int = 1_000,
) -> tuple[str | None, bool]:
    if offset < 0:
        return None, False
    line_start = output.rfind("\n", 0, offset) + 1
    line_end = output.find("\n", offset)
    if line_end < 0:
        line_end = len(output)
    line = output[line_start:line_end].rstrip("\r")
    if len(line) <= max_chars:
        return line, False
    marker_offset = offset - line_start
    excerpt_start = max(0, marker_offset - (max_chars // 4))
    excerpt_start = min(excerpt_start, len(line) - max_chars)
    return line[excerpt_start : excerpt_start + max_chars], True


def _plugin_marker_binding(
    *,
    acceptance_criteria: tuple[str, ...],
    acceptance_markers: Mapping[str, str],
    supported_criteria: set[str],
) -> dict[str, Any]:
    return {
        "marker_source": "gtfo_persistent_log",
        "markers": [
            {
                "acceptance_criterion": criterion,
                "marker": acceptance_markers[criterion],
                "observed": criterion in supported_criteria,
            }
            for criterion in acceptance_criteria
            if criterion in acceptance_markers
        ],
    }


def _runtime_trust_binding(
    *,
    feature_id: str,
    profile: GTFORealRuntimeProfile,
    process_handle: GTFOProcessHandle,
    runtime_process: Mapping[str, Any],
    log_snapshot: GTFOLogSnapshot,
    screenshot: ScreenshotMetadata | None,
    startup_loaded: bool,
    missing_marker_config: list[str],
    missing_observations: list[str],
    plugin_marker_binding: Mapping[str, Any],
    marker_observations: tuple[Mapping[str, Any], ...],
    bepinex_log_config: Mapping[str, Any],
) -> dict[str, Any]:
    screenshot_ref = screenshot.to_dict() if screenshot is not None else None
    screenshot_feature_id = (
        screenshot_ref.get("feature_id") if isinstance(screenshot_ref, Mapping) else None
    )
    checks: dict[str, Any] = {
        "feature_id": {
            "status": (
                "passed"
                if feature_id
                and (
                    screenshot_feature_id is None
                    or screenshot_feature_id == feature_id
                )
                else "blocked"
            ),
            "feature_id": feature_id,
            "screenshot_feature_id": screenshot_feature_id,
        },
        "runtime_process_identity": {
            "status": (
                "passed"
                if runtime_process.get("launched") is True
                and runtime_process.get("liveness_observed") is True
                and isinstance(runtime_process.get("pid"), int)
                and runtime_process.get("pid") > 0
                else "blocked"
            ),
            **dict(runtime_process),
        },
        "current_run_logs": {
            "status": (
                "passed"
                if process_handle.pid > 0
                and bool(log_snapshot.sources)
                and log_snapshot.run_boundary_status
                in {"prelaunch_byte_boundary", "collector_asserted_current_run"}
                else "blocked"
            ),
            "marker_source": "gtfo_persistent_log",
            "sources": list(log_snapshot.sources),
            "collected_after_process_start": True,
            "process_pid": process_handle.pid,
            "truncated": log_snapshot.truncated,
            "run_boundary_status": log_snapshot.run_boundary_status,
            "source_windows": [dict(item) for item in log_snapshot.source_windows],
        },
        "bepinex_log_config": dict(bepinex_log_config),
        "plugin_load_marker": {
            "status": "passed" if startup_loaded else "blocked",
            "startup_markers": list(profile.startup_markers),
            "startup_loaded": startup_loaded,
            "marker_observations": [
                dict(item)
                for item in marker_observations
                if item.get("marker") in profile.startup_markers
            ],
        },
        "acceptance_markers": {
            "status": (
                "passed"
                if not missing_marker_config and not missing_observations
                else "blocked"
            ),
            "marker_source": "gtfo_persistent_log",
            "missing_marker_config": list(missing_marker_config),
            "missing_observations": list(missing_observations),
            "markers": list(plugin_marker_binding.get("markers") or []),
            "marker_observations": [
                dict(item)
                for item in marker_observations
                if item.get("marker") in profile.acceptance_markers.values()
            ],
        },
        "screenshot_runtime_artifact_linkage": {
            "status": (
                "passed"
                if screenshot_ref is not None
                and screenshot_ref.get("feature_id") == feature_id
                and bool(screenshot_ref.get("file_path"))
                and bool(screenshot_ref.get("content_hash"))
                else "blocked"
            ),
            "screenshot_ref": screenshot_ref,
            "feature_id": feature_id,
        },
    }
    blockers = [
        f"{name} trust check did not pass"
        for name, check in checks.items()
        if check.get("status") != "passed"
    ]
    return {
        "profile_id": profile.profile_id,
        "evidence_source": "gtfo_real_runtime_automation",
        "status": "pending_graph_binding" if not blockers else "blocked",
        "checks": checks,
        "blockers": blockers,
    }


def _limit_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[-limit:], True


def _limitations(
    *,
    process_handle: GTFOProcessHandle,
    log_snapshot: GTFOLogSnapshot,
    screenshot: ScreenshotMetadata | None,
    missing_marker_config: list[str],
    missing_observations: list[str],
) -> tuple[str, ...]:
    limitations: list[str] = []
    if process_handle.pid <= 0:
        limitations.append("GTFO process id was not captured.")
    if not log_snapshot.sources:
        limitations.append("No configured GTFO runtime log file was available.")
    if log_snapshot.run_boundary_status == "blocked":
        limitations.append(
            "Configured GTFO logs did not establish a post-launch byte boundary."
        )
    if log_snapshot.truncated:
        limitations.append("GTFO runtime log output was truncated before artifact storage.")
    if missing_marker_config:
        limitations.append(
            "GTFO runtime profile has no acceptance marker for every criterion."
        )
    if missing_observations:
        limitations.append(
            "GTFO runtime logs did not contain every configured acceptance marker."
        )
    if screenshot is None:
        limitations.append("GTFO runtime screenshot was not captured.")
    return tuple(limitations)


def _terminate_process(process_handle: GTFOProcessHandle) -> None:
    process = process_handle.process
    if process is None:
        return
    terminate = getattr(process, "terminate", None)
    if callable(terminate):
        terminate()
    wait = getattr(process, "wait", None)
    if not callable(wait):
        return
    try:
        wait(timeout=15)
    except subprocess.TimeoutExpired:
        kill = getattr(process, "kill", None)
        if callable(kill):
            kill()
        wait(timeout=15)


def _process_liveness_observed(process_handle: GTFOProcessHandle) -> bool:
    process = process_handle.process
    if process is None:
        return process_handle.pid > 0
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return process_handle.pid > 0
    return poll() is None
