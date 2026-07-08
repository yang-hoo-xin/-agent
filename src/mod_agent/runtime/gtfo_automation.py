"""GTFO real runtime automation with explicit launch approval."""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evidence import RuntimeEvidenceItem, build_real_runtime_evidence_payload
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


@dataclass(frozen=True)
class GTFOLogSnapshot:
    """Collected persistent runtime log content."""

    content: str
    sources: tuple[str, ...]
    truncated: bool = False


ProcessLauncher = Callable[[GTFORealRuntimeProfile], GTFOProcessHandle]
LogCollector = Callable[[GTFORealRuntimeProfile, tuple[str, ...]], GTFOLogSnapshot]
ScreenshotCapturer = Callable[[GTFORealRuntimeProfile, str], ScreenshotMetadata | None]


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
        checks["acceptance_markers"]["status"] = "blocked"
        checks["acceptance_markers"]["missing_acceptance_criteria"] = list(
            missing_acceptance_criteria
        )
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
            "persistent_logs": bool(profile.log_paths),
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
            )
        try:
            _validate_real_profile(profile)

            launcher = process_launcher or _launch_gtfo_process
            collector = log_collector or _collect_persistent_logs
            capturer = screenshot_capturer or _capture_desktop_screenshot

            process_handle = launcher(profile)
            log_snapshot = collector(profile, acceptance_criteria)
            screenshot = capturer(profile, feature_id)
        except Exception as exc:
            return _payload_from_runtime_failure(
                feature_id=feature_id,
                profile=profile,
                failure=exc,
                process_handle=locals().get("process_handle"),
                acceptance_criteria=acceptance_criteria,
                runtime_verification_plan=runtime_verification_plan,
                input_execution_mode=input_execution_mode,
                capability_report=capability_report,
            )
        finally:
            if "process_handle" in locals() and profile.terminate_after_capture:
                _terminate_process(process_handle)

        return _payload_from_runtime_observations(
            feature_id=feature_id,
            profile=profile,
            process_handle=process_handle,
            log_snapshot=log_snapshot,
            screenshot=screenshot,
            acceptance_criteria=acceptance_criteria,
            runtime_verification_plan=runtime_verification_plan,
            input_execution_mode=input_execution_mode,
            capability_report=capability_report,
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
    return GTFORealRuntimeProfile(
        profile_id="gtfo_real_runtime",
        game_executable=gtfo.game_executable,
        working_directory=gtfo.working_directory,
        launch_args=tuple(gtfo.launch_args),
        log_paths=tuple(gtfo.log_paths),
        screenshot_directory=gtfo.screenshot_directory,
        screenshot_timeout_seconds=gtfo.screenshot_timeout_seconds,
        startup_markers=tuple(gtfo.startup_markers),
        acceptance_markers=dict(acceptance_markers or {}),
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
        )

    return runtime_evidence_factory


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


def _launch_gtfo_process(profile: GTFORealRuntimeProfile) -> GTFOProcessHandle:
    command = (profile.game_executable, *profile.launch_args)
    process = subprocess.Popen(
        command,
        cwd=profile.working_directory,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=False,
    )
    return GTFOProcessHandle(pid=int(process.pid), process=process)


def _collect_persistent_logs(
    profile: GTFORealRuntimeProfile,
    acceptance_criteria: tuple[str, ...],
) -> GTFOLogSnapshot:
    started = time.monotonic()
    latest_content = ""
    latest_sources: tuple[str, ...] = ()
    wanted_markers = tuple(
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
    while time.monotonic() - started <= profile.timeout_seconds:
        latest_content, latest_sources = _read_runtime_logs(profile)
        if wanted_markers and all(marker in latest_content for marker in wanted_markers):
            break
        time.sleep(profile.poll_interval_seconds)
    content, truncated = _limit_text(latest_content, profile.output_limit_chars)
    return GTFOLogSnapshot(content=content, sources=latest_sources, truncated=truncated)


def _read_runtime_logs(profile: GTFORealRuntimeProfile) -> tuple[str, tuple[str, ...]]:
    working_directory = Path(profile.working_directory)
    parts: list[str] = []
    sources: list[str] = []
    for configured_path in profile.log_paths:
        path = Path(configured_path)
        if not path.is_absolute():
            path = working_directory / path
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        parts.append(text)
        sources.append(str(path))
    return ("\n".join(parts), tuple(sources))


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
        "$bitmap.Save($args[0],[System.Drawing.Imaging.ImageFormat]::Png); "
        "$graphics.Dispose(); $bitmap.Dispose();"
    )
    completed = subprocess.run(
        ("powershell", "-NoProfile", "-Command", script, str(output_path)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=profile.screenshot_timeout_seconds,
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
    log_snapshot: GTFOLogSnapshot,
    screenshot: ScreenshotMetadata | None,
    acceptance_criteria: tuple[str, ...],
    runtime_verification_plan: tuple[str, ...],
    input_execution_mode: str | None,
    capability_report: Mapping[str, Any],
) -> dict[str, Any]:
    startup_loaded = _startup_loaded(
        log_snapshot.content,
        startup_markers=profile.startup_markers,
    )
    supported_criteria = _supported_criteria(
        log_snapshot.content,
        acceptance_criteria=acceptance_criteria,
        acceptance_markers=profile.acceptance_markers,
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
            raw_excerpt=_first_marker_line(
                log_snapshot.content,
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
    payload["runtime_process"] = {
        "profile_id": profile.profile_id,
        "pid": process_handle.pid,
        "launched": True,
        "liveness_observed": _process_liveness_observed(process_handle),
    }
    payload["gtfo_markers"] = {
        "startup_markers": list(profile.startup_markers),
        "startup_loaded": startup_loaded,
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
    payload["screenshot"] = screenshot.to_dict() if screenshot is not None else None
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
) -> dict[str, Any]:
    failure_type = type(failure).__name__
    failure_message = str(failure)
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
    payload["failure"] = {
        "type": failure_type,
        "message": failure_message,
    }
    payload["gtfo_capability_report"] = dict(capability_report)
    return payload


def _startup_loaded(output: str, *, startup_markers: tuple[str, ...]) -> bool:
    if not startup_markers:
        return bool(output.strip())
    return all(marker in output for marker in startup_markers)


def _supported_criteria(
    output: str,
    *,
    acceptance_criteria: tuple[str, ...],
    acceptance_markers: Mapping[str, str],
) -> set[str]:
    return {
        criterion
        for criterion in acceptance_criteria
        if acceptance_markers.get(criterion)
        and acceptance_markers[criterion] in output
    }


def _first_marker_line(output: str, markers: tuple[str, ...]) -> str | None:
    for line in output.splitlines():
        if any(marker in line for marker in markers):
            return line
    return None


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


def _limit_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


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


def _process_liveness_observed(process_handle: GTFOProcessHandle) -> bool:
    process = process_handle.process
    if process is None:
        return process_handle.pid > 0
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return process_handle.pid > 0
    return poll() is None
