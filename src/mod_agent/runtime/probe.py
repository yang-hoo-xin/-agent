"""Runtime probe launcher and log collector."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .evidence import RuntimeEvidenceItem, RuntimeEvidenceError, build_real_runtime_evidence_payload


class RuntimeProbeError(RuntimeEvidenceError):
    """Raised when a runtime probe cannot be launched safely."""


@dataclass(frozen=True)
class RuntimeProbeProfile:
    """Local runtime probe command and verification markers."""

    profile_id: str
    working_directory: str
    command: tuple[str, ...]
    timeout_seconds: int
    startup_markers: tuple[str, ...] = ()
    acceptance_markers: Mapping[str, str] = field(default_factory=dict)
    output_limit_chars: int = 20_000

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise RuntimeProbeError("profile_id is required")
        if not self.command:
            raise RuntimeProbeError("command is required")
        if self.timeout_seconds <= 0:
            raise RuntimeProbeError("timeout_seconds must be positive")
        if self.output_limit_chars <= 0:
            raise RuntimeProbeError("output_limit_chars must be positive")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable profile metadata without executing anything."""

        return {
            "profile_id": self.profile_id,
            "working_directory": self.working_directory,
            "command": list(self.command),
            "timeout_seconds": self.timeout_seconds,
            "startup_markers": list(self.startup_markers),
            "acceptance_markers": dict(self.acceptance_markers),
            "output_limit_chars": self.output_limit_chars,
        }


@dataclass(frozen=True)
class RuntimeProbeCommandResult:
    """Raw local runtime probe process result."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False


RuntimeProbeCommandRunner = Callable[[RuntimeProbeProfile], RuntimeProbeCommandResult]


class RuntimeProbeRunner:
    """Launch an explicitly approved local runtime probe and collect log evidence."""

    def run_local(
        self,
        *,
        feature_id: str,
        profile: RuntimeProbeProfile,
        acceptance_criteria: tuple[str, ...],
        runtime_verification_plan: tuple[str, ...],
        input_execution_mode: str | None,
        allow_execution: bool = False,
        command_runner: RuntimeProbeCommandRunner | None = None,
    ) -> dict[str, Any]:
        """Run a local runtime probe and return a runtime_evidence payload."""

        if not allow_execution:
            raise RuntimeProbeError(
                "Local runtime probe execution requires explicit approval"
            )
        runner = command_runner or _run_subprocess
        command_result = runner(profile)
        return _payload_from_command_result(
            feature_id=feature_id,
            profile=profile,
            command_result=command_result,
            acceptance_criteria=acceptance_criteria,
            runtime_verification_plan=runtime_verification_plan,
            input_execution_mode=input_execution_mode,
        )


def make_runtime_probe_evidence_factory(
    *,
    profile: RuntimeProbeProfile,
    allow_execution: bool,
    command_runner: RuntimeProbeCommandRunner | None = None,
) -> Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Build a graph-compatible runtime_evidence_factory for local probes."""

    runner = RuntimeProbeRunner()

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, Any],
        feature_spec: dict[str, Any],
    ) -> dict[str, Any]:
        return runner.run_local(
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
            allow_execution=allow_execution,
            command_runner=command_runner,
        )

    return runtime_evidence_factory


def _payload_from_command_result(
    *,
    feature_id: str,
    profile: RuntimeProbeProfile,
    command_result: RuntimeProbeCommandResult,
    acceptance_criteria: tuple[str, ...],
    runtime_verification_plan: tuple[str, ...],
    input_execution_mode: str | None,
) -> dict[str, Any]:
    output = _combine_output(command_result)
    raw_runtime_output, output_truncated = _limit_output(
        output,
        limit=profile.output_limit_chars,
    )
    startup_loaded = _startup_loaded(
        output=output,
        startup_markers=profile.startup_markers,
        exit_code=command_result.exit_code,
    )
    supported_criteria = _supported_criteria(
        output=output,
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
        command_result.exit_code == 0
        and startup_loaded
        and bool(acceptance_criteria)
        and not missing_marker_config
        and not missing_observations
    )
    verification_status = _verification_status(
        command_result=command_result,
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
    )
    evidence_items = tuple(
        RuntimeEvidenceItem(
            item_type="runtime_log",
            source="runtime_probe",
            locator=f"runtime://{profile.profile_id}#stdout",
            supports_acceptance=(criterion,),
            confidence=1.0,
            raw_excerpt=_line_for_marker(output, profile.acceptance_markers[criterion]),
        )
        for criterion in acceptance_criteria
        if criterion in supported_criteria
    )
    limitations = _limitations(
        command_result=command_result,
        missing_marker_config=missing_marker_config,
        missing_observations=missing_observations,
        output_truncated=output_truncated,
    )
    return build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=input_execution_mode,
        evidence_items=evidence_items,
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
        verification_status=verification_status,
        raw_runtime_output=raw_runtime_output,
        non_goals_checked=(),
        limitations=limitations,
        acceptance_criteria=acceptance_criteria,
        runtime_verification_plan=runtime_verification_plan,
        plugin_marker_binding={
            "marker_source": "runtime_probe",
            "markers": [
                {
                    "acceptance_criterion": criterion,
                    "marker": profile.acceptance_markers[criterion],
                    "observed": criterion in supported_criteria,
                }
                for criterion in acceptance_criteria
                if criterion in profile.acceptance_markers
            ],
        },
    )


def _run_subprocess(profile: RuntimeProbeProfile) -> RuntimeProbeCommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            profile.command,
            cwd=_working_directory(profile.working_directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=profile.timeout_seconds,
            check=False,
        )
        return RuntimeProbeCommandResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=_duration_ms(started),
        )
    except subprocess.TimeoutExpired as exc:
        return RuntimeProbeCommandResult(
            exit_code=124,
            stdout=_to_text(exc.stdout),
            stderr=_to_text(exc.stderr),
            duration_ms=_duration_ms(started),
            timed_out=True,
        )
    except OSError as exc:
        return RuntimeProbeCommandResult(
            exit_code=127,
            stdout="",
            stderr=str(exc),
            duration_ms=_duration_ms(started),
        )


def _working_directory(path: str) -> str | None:
    if not path:
        return None
    return str(Path(path))


def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _to_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _combine_output(command_result: RuntimeProbeCommandResult) -> str:
    return "\n".join(
        part for part in (command_result.stdout, command_result.stderr) if part
    )


def _limit_output(output: str, *, limit: int) -> tuple[str, bool]:
    if len(output) <= limit:
        return output, False
    return output[:limit], True


def _startup_loaded(
    *,
    output: str,
    startup_markers: tuple[str, ...],
    exit_code: int,
) -> bool:
    if startup_markers:
        return all(marker in output for marker in startup_markers)
    return exit_code == 0


def _supported_criteria(
    *,
    output: str,
    acceptance_criteria: tuple[str, ...],
    acceptance_markers: Mapping[str, str],
) -> set[str]:
    return {
        criterion
        for criterion in acceptance_criteria
        if acceptance_markers.get(criterion)
        and str(acceptance_markers[criterion]) in output
    }


def _verification_status(
    *,
    command_result: RuntimeProbeCommandResult,
    startup_loaded: bool,
    gameplay_behavior_verified: bool,
) -> str:
    if command_result.exit_code != 0 or command_result.timed_out:
        return "failed"
    if startup_loaded and gameplay_behavior_verified:
        return "verified"
    return "inconclusive"


def _line_for_marker(output: str, marker: str) -> str | None:
    for line in output.splitlines():
        if marker in line:
            return line
    return None


def _limitations(
    *,
    command_result: RuntimeProbeCommandResult,
    missing_marker_config: list[str],
    missing_observations: list[str],
    output_truncated: bool,
) -> tuple[str, ...]:
    limitations: list[str] = []
    if command_result.timed_out:
        limitations.append("Runtime probe timed out before verification completed.")
    if command_result.exit_code != 0:
        limitations.append(
            f"Runtime probe exited with nonzero code {command_result.exit_code}."
        )
    if missing_marker_config:
        limitations.append(
            "Runtime probe profile has no acceptance marker for every criterion."
        )
    if missing_observations:
        limitations.append(
            "Runtime probe output did not contain every configured acceptance marker."
        )
    if output_truncated:
        limitations.append("Runtime probe output was truncated before artifact storage.")
    return tuple(limitations)
