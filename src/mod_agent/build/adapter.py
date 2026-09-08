"""Controlled build adapter and diagnostic classifier."""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

BuildExecutionMode = Literal["fake", "local", "supplied_output", "real"]
BuildStatus = Literal["success", "failed", "skipped"]
BuildErrorClass = Literal[
    "syntax_error",
    "missing_reference",
    "namespace_error",
    "api_mismatch",
    "il2cpp_access_error",
    "config_binding_error",
    "unsafe_path_error",
    "unknown",
]

_DIAGNOSTIC_RE = re.compile(
    r"(?P<file>[A-Za-z]:\\[^(\r\n]+|[^(:\r\n]+\.(?:cs|fs|vb))"
    r"(?:\((?P<line>\d+),(?P<column>\d+)\))?"
    r"\s*:\s*(?P<severity>error|warning)\s+"
    r"(?P<code>[A-Z]{2}\d{4})\s*:\s*(?P<message>.+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BuildProfile:
    """Build command profile for one target project."""

    profile_id: str
    build_system: str
    working_directory: str
    command: tuple[str, ...]
    timeout_seconds: int
    expected_artifacts: tuple[str, ...] = ()
    log_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable profile data."""

        return {
            "profile_id": self.profile_id,
            "build_system": self.build_system,
            "working_directory": self.working_directory,
            "command": list(self.command),
            "timeout_seconds": self.timeout_seconds,
            "expected_artifacts": list(self.expected_artifacts),
            "log_path": self.log_path,
        }


class BuildProfileRegistry:
    """In-memory build profile registry."""

    def __init__(self, profiles: Iterable[BuildProfile] = ()) -> None:
        self._profiles = {profile.profile_id: profile for profile in profiles}

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> BuildProfileRegistry:
        """Build a registry from the `build.profiles` settings shape."""

        profiles = []
        for item in config.get("build", {}).get("profiles", []):
            profiles.append(
                BuildProfile(
                    profile_id=str(item["profile_id"]),
                    build_system=str(item.get("build_system", "dotnet")),
                    working_directory=str(item["working_directory"]),
                    command=tuple(str(part) for part in item["command"]),
                    timeout_seconds=int(item.get("timeout_seconds", 120)),
                    expected_artifacts=tuple(
                        str(path) for path in item.get("expected_artifacts", [])
                    ),
                    log_path=(
                        None
                        if item.get("log_path") is None
                        else str(item.get("log_path"))
                    ),
                )
            )
        return cls(profiles)

    def get(self, profile_id: str) -> BuildProfile:
        """Return a build profile by id."""

        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise KeyError(f"Unknown build profile: {profile_id}") from exc


@dataclass(frozen=True)
class BuildDiagnostic:
    """One parsed compiler diagnostic."""

    file: str | None
    line: int | None
    column: int | None
    code: str | None
    severity: str
    message: str
    error_class: BuildErrorClass

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable diagnostic data."""

        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "error_class": self.error_class,
        }


@dataclass(frozen=True)
class BuildCommandResult:
    """Result returned by an explicitly supplied command runner."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


def run_build_profile_command(
    profile: BuildProfile,
    *,
    environment: Mapping[str, str],
    command_runner: Callable[..., Any] | None = None,
) -> BuildCommandResult:
    """Execute one explicit profile using the original local process semantics.

    The caller owns authorization, the selected workspace and the environment.
    BuildAdapter remains responsible for classifying and verifying the result.
    """
    if not isinstance(profile, BuildProfile):
        raise TypeError("Build command requires BuildProfile.")
    if not profile.command or not all(isinstance(part, str) and part for part in profile.command):
        raise ValueError("Build command must contain non-empty strings.")
    if not isinstance(environment, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in environment.items()
    ):
        raise ValueError("Build environment must be an explicit string mapping.")
    started = time.perf_counter()
    completed = (subprocess.run if command_runner is None else command_runner)(
        profile.command,
        cwd=profile.working_directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=profile.timeout_seconds,
        check=False,
        env=dict(environment),
    )
    return BuildCommandResult(
        exit_code=int(completed.returncode),
        stdout=str(completed.stdout or ""),
        stderr=str(completed.stderr or ""),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


@dataclass(frozen=True)
class BuildResult:
    """Structured build_result artifact payload."""

    feature_id: str
    execution_mode: BuildExecutionMode
    status: BuildStatus
    command: tuple[str, ...]
    exit_code: int | None
    stdout_path: str | None
    stderr_path: str | None
    error_class: BuildErrorClass
    diagnostics: tuple[BuildDiagnostic, ...]
    warnings: tuple[BuildDiagnostic, ...]
    duration_ms: int
    expected_artifacts: tuple[str, ...]
    verified_artifacts: tuple[dict[str, Any], ...]
    artifact_verification: dict[str, Any]
    repair_handoff: dict[str, Any]
    real_build_performed: bool
    claims_real_build_success: bool
    input_execution_mode: str | None
    message: str
    build_status: str | None = None
    build_profile: dict[str, Any] | None = None

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the build_result artifact contract."""

        return {
            "node_name": "build",
            "stage": "build",
            "message": self.message,
            "feature_id": self.feature_id,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "errors": [
                diagnostic.to_dict()
                for diagnostic in self.diagnostics
                if diagnostic.severity == "error"
            ],
            "warnings": [diagnostic.to_dict() for diagnostic in self.warnings],
            "duration_ms": self.duration_ms,
            "error_class": self.error_class,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "repair_handoff": dict(self.repair_handoff),
            "expected_artifacts": list(self.expected_artifacts),
            "verified_artifacts": list(self.verified_artifacts),
            "artifact_verification": dict(self.artifact_verification),
            "real_build_performed": self.real_build_performed,
            "claims_real_build_success": self.claims_real_build_success,
            "input_execution_mode": self.input_execution_mode,
            "build_status": self.build_status or self.status,
            "build_profile": (
                dict(self.build_profile) if self.build_profile is not None else None
            ),
        }


class BuildErrorClassifier:
    """Classify compiler output into the build error taxonomy."""

    _CODE_CLASS: dict[str, BuildErrorClass] = {
        "CS1001": "syntax_error",
        "CS1002": "syntax_error",
        "CS1513": "syntax_error",
        "CS0246": "missing_reference",
        "CS0234": "namespace_error",
        "CS1061": "api_mismatch",
        "CS1501": "api_mismatch",
        "CS1503": "api_mismatch",
        "CS0122": "il2cpp_access_error",
    }

    def classify(self, output: str) -> tuple[BuildErrorClass, tuple[BuildDiagnostic, ...]]:
        """Return top-level error class and parsed diagnostics."""

        diagnostics = tuple(self._parse_diagnostics(output))
        error_diagnostics = tuple(
            diagnostic for diagnostic in diagnostics if diagnostic.severity == "error"
        )
        if error_diagnostics:
            return error_diagnostics[0].error_class, diagnostics
        lowered = output.lower()
        if "config" in lowered and ("binding" in lowered or "bind" in lowered):
            return "config_binding_error", diagnostics
        if "access denied" in lowered or "unsafe path" in lowered:
            return "unsafe_path_error", diagnostics
        if output.strip():
            return "unknown", diagnostics
        return "unknown", diagnostics

    def _parse_diagnostics(self, output: str) -> Iterable[BuildDiagnostic]:
        for line in output.splitlines():
            match = _DIAGNOSTIC_RE.search(line)
            if match is None:
                continue
            code = match.group("code").upper()
            message = match.group("message").strip()
            yield BuildDiagnostic(
                file=match.group("file").strip(),
                line=_int_or_none(match.group("line")),
                column=_int_or_none(match.group("column")),
                code=code,
                severity=match.group("severity").lower(),
                message=message,
                error_class=self._class_for(code=code, message=message),
            )

    def _class_for(self, *, code: str, message: str) -> BuildErrorClass:
        if code in self._CODE_CLASS:
            return self._CODE_CLASS[code]
        lowered = message.lower()
        if "il2cpp" in lowered or "inaccessible" in lowered:
            return "il2cpp_access_error"
        if "config" in lowered and ("binding" in lowered or "bind" in lowered):
            return "config_binding_error"
        return "unknown"


class BuildAdapter:
    """Build adapter that requires explicit execution opt-in for local commands."""

    def __init__(self, classifier: BuildErrorClassifier | None = None) -> None:
        self.classifier = classifier or BuildErrorClassifier()

    def from_supplied_output(
        self,
        *,
        feature_id: str,
        profile: BuildProfile,
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
        duration_ms: int = 0,
    ) -> BuildResult:
        """Build a structured result from externally supplied compiler output."""

        return self._result_from_command_output(
            feature_id=feature_id,
            profile=profile,
            execution_mode="supplied_output",
            command_result=BuildCommandResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            ),
            real_build_performed=False,
            input_execution_mode=None,
            message="Supplied build output was classified without running a command.",
        )

    def run_local(
        self,
        *,
        feature_id: str,
        profile: BuildProfile,
        command_runner: Callable[[BuildProfile], BuildCommandResult],
        allow_execution: bool = False,
        input_execution_mode: str | None = None,
    ) -> BuildResult:
        """Run a local build only when explicit execution is allowed."""

        if not allow_execution:
            return _skipped_build_result(
                feature_id=feature_id,
                profile=profile,
                execution_mode="local",
                input_execution_mode=input_execution_mode,
                message="Local build execution is blocked without explicit approval.",
            )
        command_result = command_runner(profile)
        return self._result_from_command_output(
            feature_id=feature_id,
            profile=profile,
            execution_mode="local",
            command_result=command_result,
            real_build_performed=True,
            input_execution_mode=input_execution_mode,
            message="Local build command completed and output was classified.",
        )

    def _result_from_command_output(
        self,
        *,
        feature_id: str,
        profile: BuildProfile,
        execution_mode: BuildExecutionMode,
        command_result: BuildCommandResult,
        real_build_performed: bool,
        input_execution_mode: str | None,
        message: str,
    ) -> BuildResult:
        output = "\n".join(part for part in (command_result.stdout, command_result.stderr) if part)
        error_class, diagnostics = self.classifier.classify(output)
        errors = tuple(item for item in diagnostics if item.severity == "error")
        warnings = tuple(item for item in diagnostics if item.severity == "warning")
        process_succeeded = command_result.exit_code == 0
        artifact_verification = _verify_expected_artifacts(
            profile,
            enabled=real_build_performed and process_succeeded,
        )
        artifacts_verified = artifact_verification["status"] == "verified"
        status: BuildStatus = (
            "success"
            if process_succeeded and (not real_build_performed or artifacts_verified)
            else "failed"
        )
        if not process_succeeded:
            build_status = "failed"
        elif artifacts_verified:
            build_status = "success"
        elif not real_build_performed:
            build_status = "success_unverified"
        else:
            build_status = "artifact_verification_failed"
        repair_handoff = {
            "allowed": status == "failed",
            "failure_evidence_refs": [],
            "error_class": error_class if not process_succeeded else None,
        }
        if process_succeeded and not artifacts_verified:
            repair_handoff["failure_evidence_refs"] = ["artifact_verification"]
            repair_handoff["error_class"] = artifact_verification.get("error_class")
        return BuildResult(
            feature_id=feature_id,
            execution_mode=execution_mode,
            status=status,
            command=profile.command,
            exit_code=command_result.exit_code,
            stdout_path=None,
            stderr_path=None,
            error_class=error_class if status == "failed" else "unknown",
            diagnostics=errors,
            warnings=warnings,
            duration_ms=command_result.duration_ms,
            expected_artifacts=profile.expected_artifacts,
            verified_artifacts=tuple(artifact_verification.get("artifacts", ())),
            artifact_verification=artifact_verification,
            repair_handoff=repair_handoff,
            real_build_performed=real_build_performed,
            claims_real_build_success=real_build_performed and status == "success",
            input_execution_mode=input_execution_mode,
            message=message,
            build_status=build_status,
            build_profile=profile.to_dict(),
        )


def build_fake_build_result(
    *,
    feature_id: str,
    input_execution_mode: str | None,
) -> BuildResult:
    """Build a fake build result that never claims real build success."""

    return _skipped_build_result(
        feature_id=feature_id,
        profile=BuildProfile(
            profile_id="fake_controlled_build",
            build_system="none",
            working_directory="",
            command=(),
            timeout_seconds=0,
            expected_artifacts=(),
        ),
        execution_mode="fake",
        input_execution_mode=input_execution_mode,
        message=(
            "Fake build completed. No compiler command was executed and no DLL "
            "or build artifact was produced."
        ),
        build_status="fake_completed",
    )


def _skipped_build_result(
    *,
    feature_id: str,
    profile: BuildProfile,
    execution_mode: BuildExecutionMode,
    input_execution_mode: str | None,
    message: str,
    build_status: str | None = None,
) -> BuildResult:
    return BuildResult(
        feature_id=feature_id,
        execution_mode=execution_mode,
        status="skipped",
        command=profile.command,
        exit_code=0 if execution_mode == "fake" else None,
        stdout_path=None,
        stderr_path=None,
        error_class="unknown",
        diagnostics=(),
        warnings=(),
        duration_ms=0,
        expected_artifacts=profile.expected_artifacts,
        verified_artifacts=(),
        artifact_verification={
            "status": "skipped",
            "artifacts": [],
            "blockers": [],
            "error_class": None,
        },
        repair_handoff={
            "allowed": False,
            "failure_evidence_refs": [],
            "error_class": None,
        },
        real_build_performed=False,
        claims_real_build_success=False,
        input_execution_mode=input_execution_mode,
        message=message,
        build_status=build_status,
        build_profile=profile.to_dict(),
    )


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _verify_expected_artifacts(
    profile: BuildProfile,
    *,
    enabled: bool,
) -> dict[str, Any]:
    """Verify expected build outputs after a real successful command."""

    if not enabled:
        return {
            "status": "skipped",
            "artifacts": [],
            "blockers": [],
            "error_class": None,
        }
    if not profile.expected_artifacts:
        return {
            "status": "missing",
            "artifacts": [],
            "blockers": [
                {
                    "code": "EXPECTED_ARTIFACTS_NOT_DECLARED",
                    "message": "BuildProfile has no expected_artifacts to verify.",
                }
            ],
            "error_class": "unknown",
        }

    base = Path(profile.working_directory).resolve()
    artifacts: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []
    for expected in profile.expected_artifacts:
        relative = Path(expected)
        if relative.is_absolute() or ".." in relative.parts:
            blockers.append(
                {
                    "code": "UNSAFE_EXPECTED_ARTIFACT_PATH",
                    "message": f"Expected artifact path is unsafe: {expected}",
                }
            )
            continue

        resolved = (base / relative).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            blockers.append(
                {
                    "code": "UNSAFE_EXPECTED_ARTIFACT_PATH",
                    "message": f"Expected artifact path escapes build directory: {expected}",
                }
            )
            continue

        if not resolved.exists() or not resolved.is_file():
            blockers.append(
                {
                    "code": "EXPECTED_ARTIFACT_MISSING",
                    "message": f"Expected artifact was not found: {expected}",
                }
            )
            continue

        stat = resolved.stat()
        artifacts.append(
            {
                "path": expected,
                "resolved_path": str(resolved),
                "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )

    if blockers:
        return {
            "status": "failed",
            "artifacts": artifacts,
            "blockers": blockers,
            "error_class": "unsafe_path_error"
            if any(item["code"] == "UNSAFE_EXPECTED_ARTIFACT_PATH" for item in blockers)
            else "unknown",
        }
    return {
        "status": "verified",
        "artifacts": artifacts,
        "blockers": [],
        "error_class": None,
    }
