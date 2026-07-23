"""Minimal local product entry that assembles the existing controlled graph."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from src.core.settings import load_settings
from src.libs.llm import LLMFactory, OllamaLLM, validate_loopback_http_base_url
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.evidence import RgLiveEvidenceProvider
from src.mod_agent.evidence.dotnet_metadata import (
    DotNetMetadataEnrichmentError,
    RunLocalMemberAccessResolver,
    enrich_source_evidence_with_member_accesses,
)
from src.mod_agent.execution import ExactDiffApprovalRejectedError, ExactTextPatchApplier
from src.mod_agent.planning.request_planner import requested_scope_text
from src.mod_agent.proposal import LLMExactPatchGenerator
from src.mod_agent.workflow import build_graph, create_initial_state


class LocalEntryError(RuntimeError):
    """Raised when the local real-slice entry cannot start truthfully."""


SOURCE_DISCLOSURE_DATA_CLASSES = (
    "natural_language_request",
    "retrieved_local_source_excerpts",
    "run_local_api_member_metadata_facts",
    "binding_registry",
    "side_effect_boundaries",
)
LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES = 262_144
LOCAL_DIAGNOSTIC_CONTENT_FILENAME = "patch_generation_failure_message_content.txt"
EXACT_DIFF_REJECTION_TOKEN = "REJECTED_BY_USER"
OllamaModelIdentityReader = Callable[[str, str], dict[str, Any]]
OllamaServerVersionReader = Callable[[str], str]


@dataclass(frozen=True)
class NuGetIsolatedBuildProfile:
    """Run-local NuGet restore and build inputs for one delivery workspace."""

    profile_id: str
    run_root: Path
    working_directory: Path
    config_file: Path
    packages_path: Path
    http_cache_path: Path
    scratch_path: Path
    plugins_cache_path: Path
    appdata_path: Path
    user_config_file: Path
    additional_user_config_path: Path
    bepinex_dir: Path
    timeout_seconds: int
    restore_command: tuple[str, ...]
    build_command: tuple[str, ...]

    @property
    def environment(self) -> dict[str, str]:
        return {
            "NUGET_PACKAGES": str(self.packages_path),
            "NUGET_HTTP_CACHE_PATH": str(self.http_cache_path),
            "NUGET_SCRATCH": str(self.scratch_path),
            "NUGET_PLUGINS_CACHE_PATH": str(self.plugins_cache_path),
            "APPDATA": str(self.appdata_path),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scope": "run_local_nuget_config_and_writable_cache_isolation",
            "fully_hermetic_build_claimed": False,
            "working_directory": str(self.working_directory),
            "config_file": str(self.config_file),
            "packages_path": str(self.packages_path),
            "http_cache_path": str(self.http_cache_path),
            "scratch_path": str(self.scratch_path),
            "plugins_cache_path": str(self.plugins_cache_path),
            "appdata_path": str(self.appdata_path),
            "user_config_file": str(self.user_config_file),
            "additional_user_config_path": str(
                self.additional_user_config_path
            ),
            "user_config_source_sha256": hashlib.sha256(
                self.config_file.read_bytes()
            ).hexdigest(),
            "bepinex_dir": str(self.bepinex_dir),
            "timeout_seconds": self.timeout_seconds,
            "restore_command": list(self.restore_command),
            "build_command": list(self.build_command),
            "environment": self.environment,
        }


@dataclass(frozen=True)
class NuGetIsolatedBuildExecution:
    """Observed restore/build subprocess outcome for the bounded profile."""

    restore_exit_code: int
    build_exit_code: int | None
    restore_stdout: str
    restore_stderr: str
    build_stdout: str
    build_stderr: str
    duration_ms: int

    @property
    def exit_code(self) -> int:
        return (
            self.restore_exit_code
            if self.restore_exit_code != 0
            else int(self.build_exit_code or 0)
        )

    @property
    def stdout(self) -> str:
        return _join_build_phase_output(
            ("dotnet restore", self.restore_stdout),
            ("dotnet build --no-restore", self.build_stdout),
        )

    @property
    def stderr(self) -> str:
        return _join_build_phase_output(
            ("dotnet restore", self.restore_stderr),
            ("dotnet build --no-restore", self.build_stderr),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "restore_exit_code": self.restore_exit_code,
            "build_exit_code": self.build_exit_code,
            "build_executed": self.build_exit_code is not None,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class CompiledArtifactInspectionProfile:
    """Tracked inspector source and expected plugin identity for one local run."""

    project_path: Path
    method_symbol: str
    expected_guid: str
    expected_name: str
    expected_version: str
    timeout_seconds: int = 120

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_path": str(self.project_path.resolve()),
            "method_symbol": self.method_symbol,
            "expected_guid": self.expected_guid,
            "expected_name": self.expected_name,
            "expected_version": self.expected_version,
            "timeout_seconds": self.timeout_seconds,
        }


def _create_nuget_isolated_build_profile(
    *,
    run_root: Path,
    working_directory: Path,
    config_file: Path,
    bepinex_dir: Path,
    timeout_seconds: int,
) -> NuGetIsolatedBuildProfile:
    root = run_root.resolve()
    working = working_directory.resolve()
    config = config_file.resolve()
    bepinex = bepinex_dir.resolve()
    for label, path in (
        ("working_directory", working),
        ("config_file", config),
        ("bepinex_dir", bepinex),
    ):
        _require_run_local_build_path(root=root, path=path, label=label)
    if not working.is_dir():
        raise LocalEntryError("NuGet-isolated build working directory is missing.")
    if not config.is_file():
        raise LocalEntryError("NuGet-isolated build config file is missing.")
    if not bepinex.is_dir():
        raise LocalEntryError("NuGet-isolated build BepInEx directory is missing.")
    if timeout_seconds <= 0:
        raise LocalEntryError("NuGet-isolated build timeout must be positive.")

    nuget_root = root / "build_environment" / "nuget"
    packages = nuget_root / "packages"
    http_cache = nuget_root / "http-cache"
    scratch = nuget_root / "scratch"
    plugins_cache = nuget_root / "plugins-cache"
    appdata = root / "build_environment" / "appdata"
    user_config = appdata / "NuGet" / "NuGet.Config"
    additional_user_config = appdata / "NuGet" / "config"
    bepinex_property = f"-p:BepInExDir={bepinex}"
    return NuGetIsolatedBuildProfile(
        profile_id="v2_codegen_real_local_dotnet_nuget_isolated",
        run_root=root,
        working_directory=working,
        config_file=config,
        packages_path=packages,
        http_cache_path=http_cache,
        scratch_path=scratch,
        plugins_cache_path=plugins_cache,
        appdata_path=appdata,
        user_config_file=user_config,
        additional_user_config_path=additional_user_config,
        bepinex_dir=bepinex,
        timeout_seconds=timeout_seconds,
        restore_command=(
            "dotnet",
            "restore",
            "--configfile",
            str(config),
            "--packages",
            str(packages),
            bepinex_property,
        ),
        build_command=(
            "dotnet",
            "build",
            "--no-restore",
            bepinex_property,
        ),
    )


def _run_nuget_isolated_build(
    profile: NuGetIsolatedBuildProfile,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
) -> NuGetIsolatedBuildExecution:
    for path in (
        profile.packages_path,
        profile.http_cache_path,
        profile.scratch_path,
        profile.plugins_cache_path,
        profile.additional_user_config_path,
    ):
        path.mkdir(parents=True, exist_ok=True)
    source_config = profile.config_file.read_bytes()
    if profile.user_config_file.exists():
        if profile.user_config_file.read_bytes() != source_config:
            raise LocalEntryError(
                "Run-local NuGet user config does not match the bound config file."
            )
    else:
        profile.user_config_file.write_bytes(source_config)
    environment = os.environ.copy()
    environment.update(profile.environment)
    common = {
        "cwd": profile.working_directory,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": profile.timeout_seconds,
        "check": False,
        "env": environment,
    }
    started = time.perf_counter()
    restore = command_runner(profile.restore_command, **common)
    if restore.returncode != 0:
        return NuGetIsolatedBuildExecution(
            restore_exit_code=int(restore.returncode),
            build_exit_code=None,
            restore_stdout=str(restore.stdout or ""),
            restore_stderr=str(restore.stderr or ""),
            build_stdout="",
            build_stderr="",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    build = command_runner(profile.build_command, **common)
    return NuGetIsolatedBuildExecution(
        restore_exit_code=int(restore.returncode),
        build_exit_code=int(build.returncode),
        restore_stdout=str(restore.stdout or ""),
        restore_stderr=str(restore.stderr or ""),
        build_stdout=str(build.stdout or ""),
        build_stderr=str(build.stderr or ""),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _require_run_local_build_path(*, root: Path, path: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise LocalEntryError(
            f"NuGet-isolated build {label} must remain inside the run workspace."
        ) from exc


def _join_build_phase_output(*phases: tuple[str, str]) -> str:
    selected = [f"[{label}]\n{output}" for label, output in phases if output]
    return "\n".join(selected)


def _remove_generated_build_directory(
    directory: Path,
    *,
    tree_remover: Callable[..., Any] = shutil.rmtree,
) -> dict[str, Any]:
    """Remove one generated build directory while tolerating vanished entries."""

    selected = directory.resolve()
    ignored_missing_paths: list[str] = []
    cleanup_attempt_count = 0
    directory_not_empty_retry_count = 0

    def handle_error(
        _operation: Callable[..., Any],
        failed_path: str,
        error_info: tuple[type[BaseException], BaseException, Any],
    ) -> None:
        error = error_info[1]
        if isinstance(error, FileNotFoundError):
            ignored_missing_paths.append(str(failed_path))
            return
        raise error

    while selected.exists():
        cleanup_attempt_count += 1
        try:
            tree_remover(selected, onerror=handle_error)
        except OSError as error:
            if (
                getattr(error, "winerror", None) == 145
                and directory_not_empty_retry_count == 0
            ):
                directory_not_empty_retry_count = 1
                continue
            raise
        break
    if selected.exists():
        raise LocalEntryError("Generated build directory remains after cleanup.")
    return {
        "path": str(selected),
        "removed": True,
        "ignored_missing_paths": ignored_missing_paths,
        "cleanup_attempt_count": cleanup_attempt_count,
        "directory_not_empty_retry_count": directory_not_empty_retry_count,
    }


def _build_run_local_il_inspector(
    profile: CompiledArtifactInspectionProfile,
    *,
    run_root: Path,
    command_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Build the tracked inspector source inside one run-local tool workspace."""

    root = run_root.resolve()
    project = profile.project_path.resolve()
    if not project.is_file() or project.suffix.lower() != ".csproj":
        raise LocalEntryError("Configured IL inspector project is missing.")
    if profile.timeout_seconds <= 0:
        raise LocalEntryError("IL inspector build timeout must be positive.")

    tool_root = root / "verification_tools" / "r8_il_inspector"
    source_root = tool_root / "source"
    output_root = tool_root / "output"
    environment_root = tool_root / "build_environment"
    nuget_root = environment_root / "nuget"
    packages = nuget_root / "packages"
    http_cache = nuget_root / "http-cache"
    scratch = nuget_root / "scratch"
    plugins_cache = nuget_root / "plugins-cache"
    appdata = environment_root / "appdata"
    additional_user_config = appdata / "NuGet" / "config"
    user_config = appdata / "NuGet" / "NuGet.Config"
    config = tool_root / "nuget.config"
    restore_stdout = tool_root / "restore.stdout.log"
    restore_stderr = tool_root / "restore.stderr.log"
    build_stdout = tool_root / "build.stdout.log"
    build_stderr = tool_root / "build.stderr.log"
    record_path = tool_root / "verification_tool_build.json"

    for path in (
        tool_root,
        packages,
        http_cache,
        scratch,
        plugins_cache,
        additional_user_config,
        output_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        project.parent,
        source_root,
        ignore=shutil.ignore_patterns("bin", "obj", ".git", ".idea"),
    )
    copied_project = source_root / project.name
    if not copied_project.is_file():
        raise LocalEntryError("Run-local IL inspector project copy is missing.")
    config_bytes = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<configuration><packageSources><clear /></packageSources></configuration>\n"
    )
    config.write_bytes(config_bytes)
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_bytes(config_bytes)

    environment = os.environ.copy()
    isolated_environment = {
        "NUGET_PACKAGES": str(packages),
        "NUGET_HTTP_CACHE_PATH": str(http_cache),
        "NUGET_SCRATCH": str(scratch),
        "NUGET_PLUGINS_CACHE_PATH": str(plugins_cache),
        "APPDATA": str(appdata),
    }
    environment.update(isolated_environment)
    restore_command = (
        "dotnet",
        "restore",
        str(copied_project),
        "--configfile",
        str(config),
        "--packages",
        str(packages),
    )
    build_command = (
        "dotnet",
        "build",
        str(copied_project),
        "--no-restore",
        "--output",
        str(output_root),
    )
    common = {
        "cwd": source_root,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": profile.timeout_seconds,
        "check": False,
        "env": environment,
    }
    started = time.perf_counter()
    restore = command_runner(restore_command, **common)
    restore_stdout.write_text(str(restore.stdout or ""), encoding="utf-8")
    restore_stderr.write_text(str(restore.stderr or ""), encoding="utf-8")
    build = None
    if restore.returncode == 0:
        build = command_runner(build_command, **common)
        build_stdout.write_text(str(build.stdout or ""), encoding="utf-8")
        build_stderr.write_text(str(build.stderr or ""), encoding="utf-8")
    else:
        build_stdout.write_text("", encoding="utf-8")
        build_stderr.write_text("", encoding="utf-8")

    inspector = output_root / f"{copied_project.stem}.dll"
    source_snapshot = _source_snapshot(source_root)
    record = {
        "profile_id": "run_local_r8_il_inspector_dotnet_nuget_isolated",
        "fully_hermetic_build_claimed": False,
        "source_project": str(project),
        "source_project_sha256": hashlib.sha256(project.read_bytes()).hexdigest(),
        "source_snapshot_sha256": _source_snapshot_sha256(source_snapshot),
        "copied_project": str(copied_project),
        "restore_command": list(restore_command),
        "build_command": list(build_command),
        "environment": isolated_environment,
        "timeout_seconds": profile.timeout_seconds,
        "restore_exit_code": int(restore.returncode),
        "build_exit_code": int(build.returncode) if build is not None else None,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "restore_stdout_path": str(restore_stdout),
        "restore_stderr_path": str(restore_stderr),
        "build_stdout_path": str(build_stdout),
        "build_stderr_path": str(build_stderr),
        "inspector_path": str(inspector),
        "inspector_exists": inspector.is_file(),
        "inspector_sha256": (
            hashlib.sha256(inspector.read_bytes()).hexdigest()
            if inspector.is_file()
            else None
        ),
    }
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if restore.returncode != 0:
        raise LocalEntryError(
            f"Run-local IL inspector restore failed with exit code {restore.returncode}."
        )
    if build is None or build.returncode != 0:
        exit_code = None if build is None else build.returncode
        raise LocalEntryError(
            f"Run-local IL inspector build failed with exit code {exit_code}."
        )
    if not inspector.is_file():
        raise LocalEntryError("Run-local IL inspector build produced no inspector DLL.")
    return record


def _persist_pre_graph_failure(
    *,
    run_root: Path,
    run_id: str,
    request_id: str,
    failure_stage: str,
    error: BaseException,
    source_revision_binding: Mapping[str, str] | None,
    model_admission: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> None:
    failure = {
        "run_id": run_id,
        "request_id": request_id,
        "current_stage": "failed_before_graph",
        "failure_stage": failure_stage,
        "error_type": type(error).__name__,
        "error": str(error),
        "model_call_count": 0,
        "graph_invoked": False,
        "patch_payload_parser_entered": False,
        "actual_write_performed": False,
        "source_revision_binding": dict(source_revision_binding or {}),
        "model_admission": dict(model_admission),
        "run_root": str(run_root),
    }
    if extra:
        failure.update(dict(extra))
    try:
        failure_path = run_root / "run_failure.json"
        failure_bytes = (
            json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        failure_path.write_bytes(failure_bytes)
        manifest_path = run_root / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("run_id") != run_id
            or manifest.get("request_id") != request_id
        ):
            return
        manifest.update(
            {
                "status": "failed",
                "terminal_failure_stage": failure_stage,
                "terminal_record": {
                    "path": str(failure_path),
                    "sha256": hashlib.sha256(failure_bytes).hexdigest(),
                },
                "model_call_count": 0,
                "graph_invoked": False,
                "patch_payload_parser_entered": False,
                "actual_write_performed": False,
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def _run_pre_graph_step(
    *,
    failure_stage: str,
    action: Callable[[], Any],
    run_root: Path,
    run_id: str,
    request_id: str,
    source_revision_binding: Mapping[str, str] | None,
    model_admission: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> Any:
    try:
        return action()
    except Exception as exc:
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage=failure_stage,
            error=exc,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra=extra,
        )
        raise


def _persist_graph_terminal_result(
    *,
    run_root: Path,
    run_id: str,
    request_id: str,
    summary: Mapping[str, Any],
    model_call_count: int,
    patch_payload_parser_entered: bool,
    actual_write_performed: bool,
) -> None:
    manifest_path = run_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id or manifest.get("request_id") != request_id:
        raise LocalEntryError("Run manifest identity changed before terminal projection.")
    result_path = run_root / "run_result.json"
    result_bytes = (
        json.dumps(dict(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    result_path.write_bytes(result_bytes)
    terminal_stage = str(summary.get("current_stage") or "unknown")
    manifest.update(
        {
            "status": terminal_stage,
            "terminal_stage": terminal_stage,
            "terminal_record": {
                "path": str(result_path),
                "sha256": hashlib.sha256(result_bytes).hexdigest(),
            },
            "model_call_count": model_call_count,
            "graph_invoked": True,
            "patch_payload_parser_entered": patch_payload_parser_entered,
            "actual_write_performed": actual_write_performed,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _persist_graph_terminal_failure(
    *,
    run_root: Path,
    run_id: str,
    request_id: str,
    error: BaseException,
    model_call_count: int,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = getattr(error, "diagnostics", None)
    diagnostic_record = dict(diagnostics) if isinstance(diagnostics, Mapping) else {}
    patch_payload_parser_entered = (
        diagnostic_record.get("failure_boundary")
        == "deterministic_patch_validation"
    )
    failure = {
        "run_id": run_id,
        "request_id": request_id,
        "current_stage": "failed_after_graph_invocation",
        "failure_stage": diagnostic_record.get("failure_boundary")
        or "graph_invocation",
        "error_type": type(error).__name__,
        "error": str(error),
        "model_call_count": model_call_count,
        "graph_invoked": True,
        "patch_payload_parser_entered": patch_payload_parser_entered,
        "actual_write_performed": False,
        "run_root": str(run_root),
    }
    if extra:
        failure.update(dict(extra))
    manifest_path = run_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id or manifest.get("request_id") != request_id:
        raise LocalEntryError("Run manifest identity changed before failure projection.")
    failure_path = run_root / "run_failure.json"
    failure_bytes = (
        json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    failure_path.write_bytes(failure_bytes)
    manifest.update(
        {
            "status": "failed",
            "terminal_failure_stage": failure["failure_stage"],
            "terminal_record": {
                "path": str(failure_path),
                "sha256": hashlib.sha256(failure_bytes).hexdigest(),
            },
            "model_call_count": model_call_count,
            "graph_invoked": True,
            "patch_payload_parser_entered": patch_payload_parser_entered,
            "actual_write_performed": False,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return failure


def _read_exact_diff_approval(
    reader: Callable[[dict[str, Any]], str],
    dry_run: Mapping[str, Any],
) -> str:
    approval = reader(dict(dry_run)).strip()
    if approval == EXACT_DIFF_REJECTION_TOKEN:
        raise ExactDiffApprovalRejectedError("User rejected the displayed exact diff.")
    return approval


def _verify_final_compiled_artifact_if_built(
    *,
    graph_result: Mapping[str, Any],
    target_copy: Path,
    expected_artifact: Path,
    verifier: Callable[[Path, str], dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if graph_result.get("build_summary", {}).get("claims_real_build_success") is not True:
        return None
    if verifier is None:
        return None
    final_artifact = target_copy / expected_artifact
    if not final_artifact.is_file():
        raise LocalEntryError("Final compiled artifact is missing after the graph build.")
    return verifier(final_artifact, "final")


def run_local_request(
    *,
    description: str,
    target_project: str | Path,
    workspace_base: str | Path,
    settings_path: str | Path,
    api_key_env: str = "DASHSCOPE_API_KEY",
    base_url_env: str = "DASHSCOPE_BASE_URL",
    confirm_isolated_write: bool,
    allow_build: bool,
    allow_source_disclosure: bool,
    diff_approval_reader: Callable[[dict[str, Any]], str] | None = None,
    source_disclosure_approval_id: str | None = None,
    source_revision_binding: Mapping[str, str] | None = None,
    compiled_artifact_verifier: Callable[[Path, str], dict[str, Any]] | None = None,
    compiled_artifact_inspection_profile: (
        CompiledArtifactInspectionProfile | None
    ) = None,
    source_change_verifier: (
        Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]] | None
    ) = None,
    completion_classification: Mapping[str, bool] | None = None,
    local_ollama: bool = False,
    ollama_base_url: str = "http://127.0.0.1:11434",
    ollama_model: str | None = None,
    ollama_max_output_tokens: int = 4096,
    ollama_model_identity_reader: OllamaModelIdentityReader | None = None,
    ollama_server_version_reader: OllamaServerVersionReader | None = None,
) -> dict[str, Any]:
    """Run one request through the existing graph against an isolated target copy."""

    if not description.strip():
        raise LocalEntryError("run-request requires a non-empty natural-language request.")
    if local_ollama and allow_source_disclosure:
        raise LocalEntryError(
            "Choose exactly one model boundary: --local-ollama or "
            "--allow-source-disclosure."
        )
    if not local_ollama and not allow_source_disclosure:
        raise LocalEntryError(
            "run-request requires --allow-source-disclosure before reading local "
            "target source or calling the configured external LLM."
        )
    if not confirm_isolated_write:
        raise LocalEntryError("run-request requires --confirm-isolated-write.")
    if not allow_build:
        raise LocalEntryError("run-request requires --allow-build for the real build step.")
    if diff_approval_reader is None:
        raise LocalEntryError("run-request requires an exact diff approval reader.")
    if (
        compiled_artifact_verifier is not None
        and compiled_artifact_inspection_profile is not None
    ):
        raise LocalEntryError(
            "Choose either an injected compiled artifact verifier or a run-local "
            "inspection profile."
        )
    settings = load_settings(settings_path)
    local_model_identity: dict[str, Any] | None = None
    local_ollama_server_version: str | None = None
    identity_reader = ollama_model_identity_reader or _read_ollama_model_identity
    server_version_reader = (
        ollama_server_version_reader or _read_ollama_server_version
    )
    api_key: str | None = None
    if local_ollama:
        if not isinstance(ollama_model, str) or not ollama_model.strip():
            raise LocalEntryError(
                "run-request --local-ollama requires an exact --ollama-model "
                "read from /api/tags."
            )
        if ollama_max_output_tokens <= 0:
            raise LocalEntryError("--ollama-max-output-tokens must be positive.")
        try:
            llm_base_url = validate_loopback_http_base_url(ollama_base_url)
        except ValueError as exc:
            raise LocalEntryError(str(exc)) from exc
        local_model_identity = identity_reader(llm_base_url, ollama_model)
        _validate_ollama_model_identity(
            local_model_identity,
            expected_base_url=llm_base_url,
            expected_model=ollama_model,
        )
        local_ollama_server_version = server_version_reader(llm_base_url)
        settings = replace(
            settings,
            llm=replace(
                settings.llm,
                provider="ollama",
                model=ollama_model,
                max_tokens=ollama_max_output_tokens,
                api_key=None,
                base_url=llm_base_url,
            ),
        )
        try:
            llm = LLMFactory.create(settings, base_url=llm_base_url)
        except Exception as exc:
            raise LocalEntryError(
                f"Local Ollama initialization failed: {type(exc).__name__}."
            ) from exc
        if not isinstance(llm, OllamaLLM):
            raise LocalEntryError("Local model selection did not create OllamaLLM.")
        source_disclosure = _local_no_external_disclosure_record()
        model_admission = _local_model_admission_record(
            model_identity=local_model_identity,
            provider_adapter=f"{type(llm).__module__}.{type(llm).__qualname__}",
        )
    else:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LocalEntryError(
                f"Required API key environment variable is missing: {api_key_env}"
            )
        llm_base_url = os.environ.get(base_url_env) or settings.llm.base_url
        if not llm_base_url:
            raise LocalEntryError(
                "Required LLM base URL is missing from settings and environment: "
                f"{base_url_env}"
            )
        _sanitized_endpoint_url(llm_base_url)
        llm = LLMFactory.create(
            settings,
            api_key=api_key,
            base_url=llm_base_url,
        )
    started_at = datetime.now(timezone.utc).isoformat()
    if not local_ollama:
        source_disclosure = _source_disclosure_record(
            provider=settings.llm.provider,
            model=settings.llm.model,
            base_url=llm_base_url,
            approved_at=started_at,
            approval_id=source_disclosure_approval_id,
            provider_adapter=f"{type(llm).__module__}.{type(llm).__qualname__}",
            destination_url=(
                f"{str(getattr(llm, 'base_url')).rstrip('/')}/chat/completions"
                if getattr(llm, "base_url", None)
                else None
            ),
        )
        model_admission = _external_model_admission_record(source_disclosure)

    source = Path(target_project).resolve()
    if not source.is_dir() or not any(source.glob("*.csproj")):
        raise LocalEntryError("Target project must be an existing directory with a .csproj file.")
    initial_source_snapshot = _source_snapshot(source)
    initial_source_snapshot_sha256 = _source_snapshot_sha256(initial_source_snapshot)
    _verify_source_revision_binding(
        source=source,
        snapshot=initial_source_snapshot,
        snapshot_sha256=initial_source_snapshot_sha256,
        binding=source_revision_binding,
    )
    base = Path(workspace_base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex[:8]
    request_id = f"request_{run_id}"
    run_root = (base / run_id).resolve()
    run_root.mkdir(parents=True)
    initial_manifest = {
        "run_id": run_id,
        "request_id": request_id,
        "status": "admitted",
        "started_at": started_at,
        "request": description,
        "target_source": str(source),
        "target_source_provenance": "externally_produced_read_only_input",
        "isolated_workspace": str(run_root),
        "source_snapshot": initial_source_snapshot,
        "source_snapshot_sha256": initial_source_snapshot_sha256,
        "source_revision_binding": dict(source_revision_binding or {}),
        "model": settings.llm.model,
        "model_admission": model_admission,
        "local_model_identity": local_model_identity,
        "ollama_server_version": local_ollama_server_version,
        "source_disclosure": source_disclosure,
        "compiled_artifact_inspection_profile": (
            compiled_artifact_inspection_profile.to_dict()
            if compiled_artifact_inspection_profile is not None
            else None
        ),
        "model_call_count": 0,
        "graph_invoked": False,
        "patch_payload_parser_entered": False,
        "actual_write_performed": False,
    }
    (run_root / "run_manifest.json").write_text(
        json.dumps(initial_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    target_copy = run_root / "generated_mods" / source.name
    baseline_copy = run_root / "baseline_source" / source.name
    target_copy.parent.mkdir(parents=True)
    baseline_copy.parent.mkdir(parents=True)
    _run_pre_graph_step(
        failure_stage="workspace_preparation",
        action=lambda: tuple(
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns("bin", "obj", ".git", ".idea"),
            )
            for destination in (target_copy, baseline_copy)
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    source_projects = tuple(source.glob("*.csproj"))
    if len(source_projects) != 1:
        error = LocalEntryError(
            "Target project must contain exactly one top-level .csproj file."
        )
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage="workspace_preparation",
            error=error,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
        )
        raise error
    source_project = source_projects[0]
    assembly_name = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _project_text_property(
            source_project,
            property_name="AssemblyName",
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    source_bepinex_dir = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _resolve_project_path_property(
            source_project,
            property_name="BepInExDir",
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    if not source_bepinex_dir.is_dir():
        error = LocalEntryError(f"Resolved BepInExDir is missing: {source_bepinex_dir}")
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage="baseline_profile",
            error=error,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
        )
        raise error
    isolated_bepinex_dir = run_root / "build_dependencies" / "BepInEx"
    isolated_bepinex_dir.parent.mkdir(parents=True)
    _run_pre_graph_step(
        failure_stage="build_dependency_preparation",
        action=lambda: shutil.copytree(source_bepinex_dir, isolated_bepinex_dir),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    nuget_build_profile = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _create_nuget_isolated_build_profile(
            run_root=run_root,
            working_directory=target_copy,
            config_file=target_copy / "nuget.config",
            bepinex_dir=isolated_bepinex_dir,
            timeout_seconds=120,
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    baseline_build_profile = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _create_nuget_isolated_build_profile(
            run_root=run_root,
            working_directory=baseline_copy,
            config_file=baseline_copy / "nuget.config",
            bepinex_dir=isolated_bepinex_dir,
            timeout_seconds=120,
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    verification_tool_build = None
    inspector_path: Path | None = None
    active_compiled_artifact_verifier = compiled_artifact_verifier
    if compiled_artifact_inspection_profile is not None:
        verification_tool_build = _run_pre_graph_step(
            failure_stage="verification_tool_build",
            action=lambda: _build_run_local_il_inspector(
                compiled_artifact_inspection_profile,
                run_root=run_root,
            ),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
        )
        inspector_path = Path(str(verification_tool_build["inspector_path"]))

        def verify_compiled_artifact(artifact: Path, stage: str) -> dict[str, Any]:
            return {
                **_verify_bepin_plugin_identity(
                    artifact,
                    inspector_path=inspector_path,
                    method_symbol=compiled_artifact_inspection_profile.method_symbol,
                    expected_guid=compiled_artifact_inspection_profile.expected_guid,
                    expected_name=compiled_artifact_inspection_profile.expected_name,
                    expected_version=compiled_artifact_inspection_profile.expected_version,
                ),
                "verification_stage": stage,
                "verification_tool_sha256": verification_tool_build[
                    "inspector_sha256"
                ],
            }

        active_compiled_artifact_verifier = verify_compiled_artifact
    baseline_stdout = run_root / "baseline_build.stdout.log"
    baseline_stderr = run_root / "baseline_build.stderr.log"
    baseline = _run_pre_graph_step(
        failure_stage="baseline_build",
        action=lambda: _run_nuget_isolated_build(baseline_build_profile),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
        extra={"verification_tool_build": verification_tool_build},
    )
    baseline_stdout.write_text(baseline.stdout, encoding="utf-8")
    baseline_stderr.write_text(baseline.stderr, encoding="utf-8")
    expected_artifact = f"bin/Debug/{assembly_name}.dll"
    baseline_artifact = baseline_copy / expected_artifact
    baseline_stat = baseline_artifact.stat() if baseline_artifact.is_file() else None
    baseline_result = {
        **baseline.to_dict(),
        "artifact_exists": baseline_artifact.is_file(),
        "artifact_sha256": (
            hashlib.sha256(baseline_artifact.read_bytes()).hexdigest()
            if baseline_artifact.is_file()
            else None
        ),
        "artifact_path": str(baseline_artifact),
        "artifact_size_bytes": baseline_stat.st_size if baseline_stat is not None else None,
        "artifact_mtime_utc": (
            datetime.fromtimestamp(baseline_stat.st_mtime, tz=timezone.utc).isoformat()
            if baseline_stat is not None
            else None
        ),
        "stdout_path": str(baseline_stdout),
        "stderr_path": str(baseline_stderr),
        "build_profile": baseline_build_profile.to_dict(),
    }
    if baseline.exit_code != 0 or not baseline_result["artifact_exists"]:
        failure_stage = (
            "baseline_restore"
            if baseline.restore_exit_code != 0
            else "baseline_build"
            if baseline.build_exit_code not in (None, 0)
            else "baseline_artifact_missing"
        )
        error = LocalEntryError(
            "Unmodified isolated baseline build failed; code generation was not started."
        )
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage=failure_stage,
            error=error,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra={
                "baseline_build": baseline_result,
                "verification_tool_build": verification_tool_build,
            },
        )
        raise error
    if baseline_artifact.is_file() and active_compiled_artifact_verifier is not None:
        baseline_result["compiled_artifact_verification"] = _run_pre_graph_step(
            failure_stage="baseline_artifact_verification",
            action=lambda: active_compiled_artifact_verifier(
                baseline_artifact,
                "baseline",
            ),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra={
                "baseline_build": baseline_result,
                "verification_tool_build": verification_tool_build,
            },
        )
    generator = LLMExactPatchGenerator(llm)
    applier = ExactTextPatchApplier()
    evidence_provider = RgLiveEvidenceProvider(run_root)
    member_access_resolver = (
        RunLocalMemberAccessResolver(
            inspector_path,
            dependency_root=isolated_bepinex_dir,
        )
        if inspector_path is not None
        else None
    )
    artifact_store = ArtifactStore(run_root / "a")
    build_stdout = run_root / "build.stdout.log"
    build_stderr = run_root / "build.stderr.log"
    pending_dry_run: dict[str, Any] | None = None
    external_model_input_audit: dict[str, Any] | None = None
    local_model_input_audit: dict[str, Any] | None = None
    model_call_count = 0

    def evidence_factory(state: dict[str, Any], _: dict[str, Any]):
        evidence_pack = evidence_provider.collect(
            query=requested_scope_text(state["user_request"]),
            search_root=f"generated_mods/{source.name}",
        )
        if member_access_resolver is None:
            return evidence_pack
        try:
            return enrich_source_evidence_with_member_accesses(
                evidence_pack,
                consumer_assembly=baseline_artifact,
                resolver=member_access_resolver,
            )
        except DotNetMetadataEnrichmentError as exc:
            blocker = {
                "code": "DOTNET_MEMBER_ACCESS_UNRESOLVED",
                "message": str(exc),
                "needed_evidence": [
                    "source-bound compiled receiver identity",
                    "AssemblyRef-bound run-local dependency",
                    "public readable direct Boolean property",
                ],
            }
            return replace(
                evidence_pack,
                readiness="insufficient",
                can_generate_patch=False,
                blockers=(*evidence_pack.blockers, blocker),
                missing_evidence=(
                    *evidence_pack.missing_evidence,
                    {
                        "needed_evidence": "verified .NET member access",
                        "blocker_code": blocker["code"],
                        "reason": blocker["message"],
                    },
                ),
                message=(
                    "Source evidence was found, but run-local .NET member "
                    f"semantics could not be bound: {exc}"
                ),
            )

    def patch_change_factory(
        state: dict[str, Any],
        implementation: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        nonlocal external_model_input_audit, local_model_input_audit, model_call_count
        if local_ollama:
            if local_model_identity is None or ollama_model is None:
                raise LocalEntryError("Local Ollama model identity is missing.")
            current_identity = identity_reader(llm_base_url, ollama_model)
            _validate_ollama_model_identity(
                current_identity,
                expected_base_url=llm_base_url,
                expected_model=ollama_model,
            )
            _assert_ollama_model_identity_stable(
                expected=local_model_identity,
                observed=current_identity,
            )
        else:
            _verify_source_disclosure(
                source_disclosure,
                requested_data_classes=SOURCE_DISCLOSURE_DATA_CLASSES,
            )
        external_evidence = _external_evidence_items(
            list(evidence_pack.get("items") or [])
        )
        model_input = {
            "request": state["user_request"],
            "evidence": external_evidence,
            "binding_registry": dict(implementation.get("binding_registry") or {}),
            "side_effect_boundaries": [
                str(item) for item in implementation.get("side_effect_boundaries") or []
            ],
        }
        _assert_no_absolute_local_paths(model_input)
        model_input_audit = {
            "approval_id": source_disclosure.get("approval_id"),
            "provider_adapter": model_admission.get("provider_adapter"),
            "destination": model_admission.get("destination"),
            "approved_data_classes": source_disclosure.get("approved_data_classes"),
            "payload_sha256": _sha256_json(model_input),
            "absolute_local_paths_present": False,
            "api_key_in_payload": False,
            "automatic_provider_fallback": False,
            "automatic_external_retry": False,
            "execution_locality": model_admission.get("execution_locality"),
            "external_disclosure_occurred": not local_ollama,
        }
        if not local_ollama:
            (run_root / "external_model_input_audit.json").write_text(
                json.dumps(
                    model_input_audit,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            external_model_input_audit = model_input_audit
        def record_local_provider_request(provider_request: dict[str, Any]) -> None:
            nonlocal local_model_input_audit, model_call_count
            if not local_ollama:
                raise LocalEntryError(
                    "Local provider request recorder cannot be used externally."
                )
            if local_model_input_audit is not None or model_call_count != 0:
                raise LocalEntryError("LOCAL_PATCH_GENERATION_CALL_ALREADY_RECORDED")
            if local_ollama_server_version is None or local_model_identity is None:
                raise LocalEntryError("Local Ollama environment binding is missing.")
            attempt = {
                **model_input_audit,
                "status": "ready_for_provider_invocation",
                "run_id": run_id,
                "request_id": state["request_id"],
                "model_call_count": 0,
                "remaining_call_budget": 1,
                "output_budget": ollama_max_output_tokens,
                "ollama_server_version": local_ollama_server_version,
                "model_identity": dict(local_model_identity),
                "source_revision_binding": dict(source_revision_binding or {}),
                "source_snapshot_sha256": initial_source_snapshot_sha256,
                "generation_input_binding": {
                    "request_sha256": hashlib.sha256(
                        str(model_input["request"]).encode("utf-8")
                    ).hexdigest(),
                    "evidence_pack_ref": state["artifacts"].get("evidence_pack"),
                    "evidence_pack_hash": state["artifact_hashes"].get(
                        "evidence_pack"
                    ),
                    "implementation_plan_ref": state["artifacts"].get(
                        "implementation_plan"
                    ),
                    "implementation_plan_hash": state["artifact_hashes"].get(
                        "implementation_plan"
                    ),
                    "editable_paths": [
                        str(item) for item in implementation.get("target_files") or []
                    ],
                    "change_scope": [
                        str(item)
                        for item in implementation.get("side_effect_boundaries") or []
                    ],
                },
                "provider_request": dict(provider_request),
                "provider_request_profile": {
                    "stream": False,
                    "think": False,
                    "tools_sent": False,
                    "native_json_schema_requested": True,
                    "timeout_seconds": provider_request.get("timeout_seconds"),
                    "trust_environment": provider_request.get("trust_environment"),
                    "follow_redirects": provider_request.get("follow_redirects"),
                    "automatic_provider_fallback": False,
                    "automatic_retry": False,
                    "model_switching": False,
                },
            }
            (run_root / "local_model_input_audit.json").write_text(
                json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            local_model_input_audit = attempt
            model_call_count = 1

        def enforce_post_response_model_binding(_: Any) -> None:
            if local_model_identity is None or ollama_model is None:
                raise LocalEntryError("Local Ollama model identity is missing.")
            observed_identity = identity_reader(llm_base_url, ollama_model)
            _validate_ollama_model_identity(
                observed_identity,
                expected_base_url=llm_base_url,
                expected_model=ollama_model,
            )
            _assert_ollama_model_identity_stable(
                expected=local_model_identity,
                observed=observed_identity,
            )

        required_validation_by_binding = {
            str(item["edit_binding_id"]): [
                str(value) for value in item.get("expected_validation") or []
            ]
            for item in implementation.get("proposed_changes") or []
            if isinstance(item, dict) and item.get("edit_binding_id")
        }
        generated = generator.generate(
            user_request=str(model_input["request"]),
            evidence_items=list(model_input["evidence"]),
            binding_registry=dict(model_input["binding_registry"]),
            constraints=list(model_input["side_effect_boundaries"]),
            required_validation_by_binding=required_validation_by_binding,
            require_native_schema=local_ollama,
            provider_request_recorder=(
                record_local_provider_request if local_ollama else None
            ),
            post_response_admission=(
                enforce_post_response_model_binding if local_ollama else None
            ),
        )
        if local_ollama and generated.model != ollama_model:
            raise LocalEntryError("OLLAMA_RESPONSE_MODEL_IDENTITY_MISMATCH")
        planned_by_binding = {
            str(item.get("edit_binding_id")): item
            for item in implementation.get("proposed_changes") or []
            if isinstance(item, dict) and item.get("edit_binding_id")
        }
        changes: list[dict[str, Any]] = []
        for generated_change in generated.changes:
            binding_id = str(generated_change["edit_binding_id"])
            planned = planned_by_binding.get(binding_id)
            if planned is None:
                raise LocalEntryError("Generated patch is outside implementation-plan bindings.")
            changes.append(
                {
                    **planned,
                    "rationale": generated_change["rationale"],
                    "expected_validation": generated_change["expected_validation"],
                    "rollback_hint": generated_change["rollback_hint"],
                    "patch": generated_change["patch"],
                    "generation": {
                        "provider": settings.llm.provider,
                        "model": generated.model,
                        "model_digest": (
                            local_model_identity.get("digest")
                            if local_model_identity is not None
                            else None
                        ),
                        "usage": generated.usage,
                        "api_key_env": None if local_ollama else api_key_env,
                    },
                }
            )
        return tuple(changes)

    def dry_run_factory(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal pending_dry_run
        pending_dry_run = applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=implementation,
            review=review,
            allow_write=False,
        )
        return pending_dry_run

    def isolated_apply_factory(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        if pending_dry_run is None:
            raise LocalEntryError("Exact diff approval requested before dry-run completed.")
        approved_diff_hash = _read_exact_diff_approval(
            diff_approval_reader,
            pending_dry_run,
        )
        return applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=implementation,
            review=review,
            allow_write=True,
            approved_diff_hash=approved_diff_hash,
        )

    def build_result_factory(feature_id: str, input_execution_mode: str | None):
        profile = BuildProfile(
            profile_id=nuget_build_profile.profile_id,
            build_system="dotnet",
            working_directory=str(target_copy),
            command=nuget_build_profile.build_command,
            timeout_seconds=nuget_build_profile.timeout_seconds,
            expected_artifacts=(expected_artifact,),
        )

        def command_runner(selected: BuildProfile) -> BuildCommandResult:
            if selected.command != nuget_build_profile.build_command:
                raise LocalEntryError("Final build command does not match the bound profile.")
            completed = _run_nuget_isolated_build(nuget_build_profile)
            build_stdout.write_text(completed.stdout, encoding="utf-8")
            build_stderr.write_text(completed.stderr, encoding="utf-8")
            return BuildCommandResult(
                exit_code=completed.exit_code,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=completed.duration_ms,
            )

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=profile,
            command_runner=command_runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    manifest = {
        "run_id": run_id,
        "request_id": request_id,
        "status": "baseline_verified",
        "started_at": started_at,
        "request": description,
        "target_source": str(source),
        "target_source_provenance": "externally_produced_read_only_input",
        "isolated_workspace": str(run_root),
        "source_snapshot": initial_source_snapshot,
        "source_snapshot_sha256": initial_source_snapshot_sha256,
        "source_revision_binding": dict(source_revision_binding or {}),
        "model": settings.llm.model,
        "model_admission": model_admission,
        "local_model_identity": local_model_identity,
        "ollama_server_version": local_ollama_server_version,
        "ollama_patch_generation_profile": (
            {
                "stream": False,
                "think": False,
                "tools_sent": False,
                "native_json_schema_required": True,
                "output_budget": ollama_max_output_tokens,
                "timeout_seconds": getattr(llm, "timeout", None),
                "trust_environment": False,
                "follow_redirects": False,
                "automatic_provider_fallback": False,
                "automatic_retry": False,
                "model_switching": False,
                "diagnostic_content_max_utf8_bytes": (
                    LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES
                ),
            }
            if local_ollama
            else None
        ),
        "base_url": _sanitized_endpoint_url(llm_base_url),
        "base_url_env": None if local_ollama else base_url_env,
        "base_url_env_present": (
            False if local_ollama else bool(os.environ.get(base_url_env))
        ),
        "api_key_env": None if local_ollama else api_key_env,
        "api_key_required": not local_ollama,
        "api_key_read": not local_ollama,
        "api_key_present": False if local_ollama else True,
        "api_key_value_persisted": False,
        "source_disclosure": source_disclosure,
        "assembly_name": assembly_name,
        "build_dependency": {
            "source": str(source_bepinex_dir),
            "isolated_copy": str(isolated_bepinex_dir),
            "build_uses_isolated_copy": True,
        },
        "nuget_isolated_build_profile": nuget_build_profile.to_dict(),
        "compiled_artifact_inspection_profile": (
            compiled_artifact_inspection_profile.to_dict()
            if compiled_artifact_inspection_profile is not None
            else None
        ),
        "verification_tool_build": verification_tool_build,
        "baseline_build": baseline_result,
        "model_call_count": 0,
        "graph_invoked": False,
        "patch_payload_parser_entered": False,
        "actual_write_performed": False,
        "limits": [
            "No claim that the external BetterHitFeedback project was generated by this platform.",
            "No real GTFO launch or gameplay validation is performed.",
            "The dotnet process executes user-authorized project build logic and is not an OS sandbox.",
        ],
    }
    (run_root / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _run_pre_graph_step(
        failure_stage="pre_graph_generated_directory_cleanup",
        action=lambda: tuple(
            _remove_generated_build_directory(generated_directory)
            for generated_directory in (target_copy / "bin", target_copy / "obj")
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
        extra={
            "baseline_build": baseline_result,
            "verification_tool_build": verification_tool_build,
        },
    )

    graph = build_graph(
        artifact_store,
        evidence_pack_factory=evidence_factory,
        patch_change_factory=patch_change_factory,
        dry_run_factory=dry_run_factory,
        isolated_apply_factory=isolated_apply_factory,
        build_result_factory=build_result_factory,
        use_default_proposal_git_binding=False,
        stop_after_build=True,
    )
    state = create_initial_state(
        run_id=run_id,
        request_id=request_id,
        user_request=description,
        target_domain="gtfo",
        target_mod=source.name,
        confirmed_isolated_write=True,
    )
    with _working_directory(run_root):
        try:
            result = graph.invoke(state)
        except Exception as exc:
            provider_failure = _persist_local_failure_diagnostics(
                run_root=run_root,
                error=exc,
                enabled=local_ollama,
            )
            _persist_graph_terminal_failure(
                run_root=run_root,
                run_id=run_id,
                request_id=request_id,
                error=exc,
                model_call_count=model_call_count,
                extra=(
                    {"provider_failure": provider_failure}
                    if provider_failure is not None
                    else None
                ),
            )
            raise LocalEntryError(f"Controlled graph failed: {type(exc).__name__}: {exc}") from exc

    final_build_succeeded = (
        result.get("build_summary", {}).get("claims_real_build_success") is True
    )
    final_artifact_verification = _verify_final_compiled_artifact_if_built(
        graph_result=result,
        target_copy=target_copy,
        expected_artifact=expected_artifact,
        verifier=active_compiled_artifact_verifier,
    )
    final_canonical_snapshot = _source_snapshot(source)
    canonical_source_unchanged = (
        final_canonical_snapshot == initial_source_snapshot
        and _source_snapshot_sha256(final_canonical_snapshot)
        == initial_source_snapshot_sha256
    )
    if not canonical_source_unchanged:
        raise LocalEntryError("Canonical source changed during the isolated run.")
    final_isolated_snapshot = _source_snapshot(target_copy)
    source_change_verification = None
    if final_build_succeeded and source_change_verifier is not None:
        source_change_verification = source_change_verifier(
            initial_source_snapshot,
            final_isolated_snapshot,
        )
    actual_write_performed = final_isolated_snapshot != initial_source_snapshot
    patch_payload_parser_entered = "patch_proposal" in (result.get("artifacts") or {})
    selected_classification = dict(completion_classification or {})
    if selected_classification:
        if result.get("build_summary", {}).get("claims_real_build_success") is not True:
            raise LocalEntryError("Completion classification requires a real successful build.")
        if active_compiled_artifact_verifier is None or source_change_verifier is None:
            raise LocalEntryError(
                "Completion classification requires compiled artifact and source change verification."
            )

    summary = {
        "run_id": run_id,
        "current_stage": result["current_stage"],
        "feature_id": result.get("feature_id"),
        "blockers": result.get("blockers") or [],
        "artifacts": result.get("artifacts") or {},
        "build_summary": result.get("build_summary") or {},
        "run_root": str(run_root),
        "build_stdout": str(build_stdout) if build_stdout.exists() else None,
        "build_stderr": str(build_stderr) if build_stderr.exists() else None,
        "source_revision_binding": dict(source_revision_binding or {}),
        "external_model_input_audit": external_model_input_audit,
        "local_model_input_audit": local_model_input_audit,
        "model_call_count": model_call_count,
        "graph_invoked": True,
        "patch_payload_parser_entered": patch_payload_parser_entered,
        "actual_write_performed": actual_write_performed,
        "model_admission": model_admission,
        "local_model_identity": local_model_identity,
        "verification_tool_build": verification_tool_build,
        "baseline_artifact_verification": baseline_result.get(
            "compiled_artifact_verification"
        ),
        "final_artifact_verification": final_artifact_verification,
        "canonical_source_unchanged": canonical_source_unchanged,
        "initial_isolated_source_snapshot": initial_source_snapshot,
        "final_isolated_source_snapshot": final_isolated_snapshot,
        "source_change_verification": source_change_verification,
        "completion_classification": selected_classification,
    }
    _persist_graph_terminal_result(
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        summary=summary,
        model_call_count=model_call_count,
        patch_payload_parser_entered=patch_payload_parser_entered,
        actual_write_performed=actual_write_performed,
    )
    return summary


def _source_snapshot(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and "bin" not in path.parts and "obj" not in path.parts
    ]


def _source_snapshot_sha256(snapshot: list[dict[str, Any]]) -> str:
    return _sha256_json(snapshot)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_source_revision_binding(
    *,
    source: Path,
    snapshot: list[dict[str, Any]],
    snapshot_sha256: str,
    binding: Mapping[str, str] | None,
) -> None:
    if binding is None:
        return
    expected_snapshot = binding.get("complete_snapshot_sha256")
    if expected_snapshot != snapshot_sha256:
        raise LocalEntryError("Canonical source complete snapshot SHA256 does not match binding.")
    plugin_entry = next(
        (item for item in snapshot if item.get("path") == "Plugin.cs"),
        None,
    )
    if plugin_entry is None:
        raise LocalEntryError("Canonical source binding requires Plugin.cs.")
    if binding.get("plugin_cs_sha256") != plugin_entry.get("sha256"):
        raise LocalEntryError("Canonical source Plugin.cs SHA256 does not match binding.")
    if not binding.get("repository_head") or not binding.get("subtree_tree"):
        raise LocalEntryError("Canonical source binding requires repository_head and subtree_tree.")


def _external_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in items:
        selected = dict(item)
        source_path = selected.get("source_path")
        source_type = selected.get("source_type")
        if isinstance(source_path, str) and isinstance(source_type, str):
            selected["source_ref"] = f"source://{source_type}/{source_path}"
        else:
            selected.pop("source_ref", None)
        sanitized.append(selected)
    return sanitized


def _assert_no_absolute_local_paths(value: Any) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _assert_no_absolute_local_paths(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _assert_no_absolute_local_paths(nested)
        return
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        return
    if Path(value).is_absolute() or (
        len(value) >= 3
        and value[0].isalpha()
        and value[1] == ":"
        and value[2] in {"/", "\\"}
    ):
        raise LocalEntryError("External model payload contains an absolute local path.")


def _verify_exact_snapshot_change(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    relative_path: str,
    before_sha256: str,
    after_sha256: str,
) -> dict[str, Any]:
    before_by_path = {str(item["path"]): item for item in before}
    after_by_path = {str(item["path"]): item for item in after}
    changed_paths = sorted(
        path
        for path in set(before_by_path) | set(after_by_path)
        if before_by_path.get(path) != after_by_path.get(path)
    )
    if changed_paths != [relative_path]:
        raise LocalEntryError("Isolated source changes do not match the approved file scope.")
    selected_before = before_by_path[relative_path]
    selected_after = after_by_path[relative_path]
    if selected_before.get("sha256") != before_sha256:
        raise LocalEntryError("Isolated source before SHA256 does not match approval binding.")
    if selected_after.get("sha256") != after_sha256:
        raise LocalEntryError("Isolated source after SHA256 does not match approved exact change.")
    return {
        "status": "passed",
        "changed_paths": changed_paths,
        "relative_path": relative_path,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
    }


def _verify_bepin_plugin_identity(
    artifact_path: str | Path,
    *,
    inspector_path: str | Path,
    method_symbol: str,
    expected_guid: str,
    expected_name: str,
    expected_version: str,
) -> dict[str, Any]:
    artifact = Path(artifact_path).resolve()
    inspector = Path(inspector_path).resolve()
    if not artifact.is_file():
        raise LocalEntryError("Compiled artifact is missing for metadata inspection.")
    if not inspector.is_file():
        raise LocalEntryError("Configured IL inspector is missing.")
    completed = subprocess.run(
        ("dotnet", str(inspector), str(artifact), method_symbol),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise LocalEntryError(
            f"Compiled artifact inspection failed with exit code {completed.returncode}."
        )
    try:
        inspection = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LocalEntryError("Compiled artifact inspector returned invalid JSON.") from exc
    methods = inspection.get("methods") if isinstance(inspection, dict) else None
    matching_methods = [
        item
        for item in methods or []
        if isinstance(item, dict) and item.get("symbol") == method_symbol
    ]
    if len(matching_methods) != 1:
        raise LocalEntryError("Compiled artifact inspector did not resolve one exact method.")
    plugin_attributes = [
        item
        for item in matching_methods[0].get("declaring_type_custom_attributes") or []
        if isinstance(item, dict)
        and item.get("constructor") == "BepInEx.BepInPlugin..ctor"
    ]
    if len(plugin_attributes) != 1:
        raise LocalEntryError("Compiled artifact does not contain one BepInPlugin identity.")
    observed_identity = plugin_attributes[0].get("printable_ascii_runs")
    expected_identity = [expected_guid, expected_name, expected_version]
    if observed_identity != expected_identity:
        raise LocalEntryError("Compiled BepInPlugin identity does not match expected values.")
    stat = artifact.stat()
    return {
        "status": "passed",
        "artifact_path": str(artifact),
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "artifact_size_bytes": stat.st_size,
        "artifact_mtime_utc": datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        "inspector_path": str(inspector),
        "inspector_sha256": hashlib.sha256(inspector.read_bytes()).hexdigest(),
        "inspector_schema_version": inspection.get("schema_version"),
        "method_symbol": method_symbol,
        "bepin_plugin": {
            "guid": expected_guid,
            "name": expected_name,
            "version": expected_version,
        },
        "target_code_executed": inspection.get("target_code_executed"),
    }


def _source_disclosure_record(
    *,
    provider: str,
    model: str,
    base_url: str | None,
    approved_at: str,
    approval_id: str | None = None,
    provider_adapter: str | None = None,
    destination_url: str | None = None,
) -> dict[str, Any]:
    return {
        "approved": True,
        "approved_at": approved_at,
        "approval_id": approval_id,
        "approval_actor_type": "local_cli_invoker",
        "consent_mechanism": "--allow-source-disclosure",
        "provider_adapter": provider_adapter,
        "destination": {
            "provider": provider,
            "model": model,
            "base_url": _sanitized_endpoint_url(base_url),
            "request_url": _sanitized_endpoint_url(destination_url),
        },
        "approved_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "requested_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "scope": "this_run_only",
    }


def _local_no_external_disclosure_record() -> dict[str, Any]:
    return {
        "occurred": False,
        "approved": False,
        "approved_at": None,
        "approval_id": None,
        "approval_actor_type": None,
        "consent_mechanism": None,
        "provider_adapter": None,
        "destination": None,
        "approved_data_classes": [],
        "requested_data_classes": [],
        "scope": "this_run_only",
        "reason": "local_model_execution",
    }


def _local_model_admission_record(
    *,
    model_identity: Mapping[str, Any],
    provider_adapter: str,
) -> dict[str, Any]:
    base_url = str(model_identity["base_url"])
    return {
        "provider": "ollama",
        "model": str(model_identity["name"]),
        "model_digest": str(model_identity["digest"]),
        "provider_adapter": provider_adapter,
        "execution_locality": "local",
        "base_url": base_url,
        "destination": f"{base_url}/api/chat",
        "external_disclosure_occurred": False,
        "api_key_required": False,
        "api_key_read": False,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "machine_local",
    }


def _persist_local_failure_diagnostics(
    *,
    run_root: Path,
    error: BaseException,
    enabled: bool,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    diagnostics: dict[str, Any] = {}
    diagnostic_content: str | None = None
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        current_diagnostics = getattr(current, "diagnostics", None)
        if isinstance(current_diagnostics, Mapping):
            diagnostics.update(current_diagnostics)
            embedded_content = current_diagnostics.get("message_content")
            if diagnostic_content is None and isinstance(embedded_content, str):
                diagnostic_content = embedded_content
        current_content = getattr(current, "diagnostic_content", None)
        if diagnostic_content is None and isinstance(current_content, str):
            diagnostic_content = current_content
        current = current.__cause__ or current.__context__
    diagnostics.pop("message_content", None)
    diagnostics["failure_attribution"] = "unknown"
    if diagnostic_content is None:
        diagnostics["diagnostic_content"] = {
            "present": False,
            "retained": False,
            "max_utf8_bytes": LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES,
        }
        return diagnostics

    content_bytes = diagnostic_content.encode("utf-8")
    retention = {
        "present": True,
        "utf8_bytes": len(content_bytes),
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
        "max_utf8_bytes": LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES,
        "retained": False,
        "path": None,
    }
    if len(content_bytes) <= LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES:
        destination = run_root / LOCAL_DIAGNOSTIC_CONTENT_FILENAME
        try:
            destination.write_bytes(content_bytes)
        except OSError as exc:
            retention["retention_error"] = type(exc).__name__
            diagnostics["diagnostic_sufficiency"] = "insufficient"
        else:
            retention["retained"] = True
            retention["path"] = str(destination)
    else:
        diagnostics["diagnostic_sufficiency"] = "reduced"
        retention["not_retained_reason"] = "policy_limit_exceeded"
    diagnostics["diagnostic_content"] = retention
    return diagnostics


def _external_model_admission_record(
    source_disclosure: Mapping[str, Any],
) -> dict[str, Any]:
    destination = source_disclosure.get("destination")
    destination_data = destination if isinstance(destination, dict) else {}
    return {
        "provider": destination_data.get("provider"),
        "model": destination_data.get("model"),
        "model_digest": None,
        "provider_adapter": source_disclosure.get("provider_adapter"),
        "execution_locality": "external",
        "base_url": destination_data.get("base_url"),
        "destination": destination_data.get("request_url"),
        "external_disclosure_occurred": True,
        "api_key_required": True,
        "api_key_read": True,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "external_provider",
    }


def _read_ollama_model_identity(base_url: str, model: str) -> dict[str, Any]:
    normalized_base_url = validate_loopback_http_base_url(base_url)
    try:
        import httpx

        with httpx.Client(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{normalized_base_url}/api/tags")
        if response.status_code != 200:
            raise LocalEntryError(
                f"OLLAMA_MODEL_CATALOG_HTTP_{response.status_code}"
            )
        payload = response.json()
    except LocalEntryError:
        raise
    except Exception as exc:
        raise LocalEntryError(
            f"OLLAMA_MODEL_CATALOG_UNAVAILABLE:{type(exc).__name__}"
        ) from exc
    return _select_ollama_model_identity(
        payload,
        base_url=normalized_base_url,
        expected_model=model,
    )


def _read_ollama_server_version(base_url: str) -> str:
    normalized_base_url = validate_loopback_http_base_url(base_url)
    try:
        import httpx

        with httpx.Client(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{normalized_base_url}/api/version")
        if response.status_code != 200:
            raise LocalEntryError(
                f"OLLAMA_SERVER_VERSION_HTTP_{response.status_code}"
            )
        payload = response.json()
    except LocalEntryError:
        raise
    except Exception as exc:
        raise LocalEntryError(
            f"OLLAMA_SERVER_VERSION_UNAVAILABLE:{type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise LocalEntryError("OLLAMA_SERVER_VERSION_SHAPE_INVALID")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise LocalEntryError("OLLAMA_SERVER_VERSION_MISSING")
    return version


def _select_ollama_model_identity(
    payload: Any,
    *,
    base_url: str,
    expected_model: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise LocalEntryError("OLLAMA_MODEL_CATALOG_SHAPE_INVALID")
    models = payload["models"]
    if not models:
        raise LocalEntryError("OLLAMA_MODEL_LIST_EMPTY")
    matches = [
        item
        for item in models
        if isinstance(item, dict) and item.get("name") == expected_model
    ]
    if len(matches) != 1:
        raise LocalEntryError("OLLAMA_MODEL_NOT_EXACTLY_PRESENT")
    selected = matches[0]
    identity = {
        "name": selected.get("name"),
        "model": selected.get("model"),
        "digest": selected.get("digest"),
        "modified_at": selected.get("modified_at"),
        "size": selected.get("size"),
        "details": selected.get("details"),
        "capabilities": selected.get("capabilities"),
        "base_url": base_url,
    }
    _validate_ollama_model_identity(
        identity,
        expected_base_url=base_url,
        expected_model=expected_model,
    )
    return identity


def _validate_ollama_model_identity(
    identity: Mapping[str, Any],
    *,
    expected_base_url: str,
    expected_model: str,
) -> None:
    if identity.get("name") != expected_model:
        raise LocalEntryError("OLLAMA_MODEL_NAME_MISMATCH")
    if identity.get("model") != expected_model:
        raise LocalEntryError("OLLAMA_MODEL_IDENTITY_MISMATCH")
    if identity.get("base_url") != expected_base_url:
        raise LocalEntryError("OLLAMA_MODEL_BASE_URL_MISMATCH")
    digest = identity.get("digest")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise LocalEntryError("OLLAMA_MODEL_DIGEST_INVALID")
    if not isinstance(identity.get("details"), dict):
        raise LocalEntryError("OLLAMA_MODEL_DETAILS_INVALID")
    capabilities = identity.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise LocalEntryError("OLLAMA_MODEL_CAPABILITIES_INVALID")


def _assert_ollama_model_identity_stable(
    *,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> None:
    if expected.get("name") != observed.get("name"):
        raise LocalEntryError("OLLAMA_MODEL_NAME_DRIFT")
    if expected.get("digest") != observed.get("digest"):
        raise LocalEntryError("OLLAMA_MODEL_DIGEST_DRIFT")


def _verify_source_disclosure(
    record: dict[str, Any],
    *,
    requested_data_classes: tuple[str, ...],
) -> None:
    if record.get("approved") is not True:
        raise LocalEntryError("Source disclosure is not explicitly approved.")
    approved = record.get("approved_data_classes")
    if not isinstance(approved, list):
        raise LocalEntryError("Source disclosure approved_data_classes is missing.")
    unapproved = sorted(set(requested_data_classes) - {str(item) for item in approved})
    if unapproved:
        raise LocalEntryError(
            "Source disclosure does not approve requested data classes: "
            + ", ".join(unapproved)
        )


def _resolve_project_path_property(project_file: Path, *, property_name: str) -> Path:
    value = Path(
        _project_text_property(project_file, property_name=property_name).replace(
            "\\", os.sep
        )
    )
    return value.resolve() if value.is_absolute() else (project_file.parent / value).resolve()


def _project_text_property(project_file: Path, *, property_name: str) -> str:
    root = ET.parse(project_file).getroot()
    values = [
        item.text.strip()
        for item in root.iter(property_name)
        if isinstance(item.text, str) and item.text.strip()
    ]
    if not values:
        raise LocalEntryError(f"Project file does not define {property_name}.")
    if len(values) != 1:
        raise LocalEntryError(
            f"Project file must define exactly one non-empty {property_name}."
        )
    return values[0]


def _sanitized_endpoint_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    parsed = urlsplit(base_url)
    if not parsed.scheme or parsed.hostname is None:
        raise LocalEntryError("Configured LLM base_url is not a valid absolute URL.")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    try:
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    except ValueError as exc:
        raise LocalEntryError("Configured LLM base_url has an invalid port.") from exc
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)
