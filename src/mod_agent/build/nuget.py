"""Run-local NuGet environment, restore/build sequence and verification commands.

为什么要有它：构建环境和进程顺序归单一build owner，入口保留兼容别名，不再承载这段实现。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.mod_agent.build.adapter import BuildCommandResult, BuildProfile
from src.mod_agent.errors import LocalEntryError


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
    bepinex_dir: Path | None
    game_folder_dir: Path | None
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
            "bepinex_dir": (
                str(self.bepinex_dir) if self.bepinex_dir is not None else None
            ),
            "game_folder_dir": (
                str(self.game_folder_dir)
                if self.game_folder_dir is not None
                else None
            ),
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



def _create_nuget_isolated_build_profile(
    *,
    run_root: Path,
    working_directory: Path,
    config_file: Path,
    bepinex_dir: Path | None,
    timeout_seconds: int,
    game_folder_dir: Path | None = None,
) -> NuGetIsolatedBuildProfile:
    root = run_root.resolve()
    working = working_directory.resolve()
    config = config_file.resolve()
    bepinex = bepinex_dir.resolve() if bepinex_dir is not None else None
    game_folder = (
        game_folder_dir.resolve() if game_folder_dir is not None else None
    )
    for label, path in (
        ("working_directory", working),
        ("config_file", config),
    ):
        _require_run_local_build_path(root=root, path=path, label=label)
    if bepinex is not None:
        _require_run_local_build_path(
            root=root,
            path=bepinex,
            label="bepinex_dir",
        )
    if game_folder is not None:
        _require_run_local_build_path(
            root=root,
            path=game_folder,
            label="game_folder_dir",
        )
    if not working.is_dir():
        raise LocalEntryError("NuGet-isolated build working directory is missing.")
    if not config.is_file():
        raise LocalEntryError("NuGet-isolated build config file is missing.")
    if bepinex is not None and not bepinex.is_dir():
        raise LocalEntryError("NuGet-isolated build BepInEx directory is missing.")
    if game_folder is not None and not game_folder.is_dir():
        raise LocalEntryError("NuGet-isolated build GameFolder directory is missing.")
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
    bepinex_arguments = (
        (f"-p:BepInExDir={bepinex}",) if bepinex is not None else ()
    )
    game_folder_arguments = (
        (f"-p:GameFolder={game_folder}",) if game_folder is not None else ()
    )
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
        game_folder_dir=game_folder,
        timeout_seconds=timeout_seconds,
        restore_command=(
            "dotnet",
            "restore",
            "--configfile",
            str(config),
            "--packages",
            str(packages),
            *bepinex_arguments,
            *game_folder_arguments,
        ),
        build_command=(
            "dotnet",
            "build",
            "--no-restore",
            *bepinex_arguments,
            *game_folder_arguments,
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



def _run_nuget_isolated_verification_command(
    profile: NuGetIsolatedBuildProfile,
    command: tuple[str, ...],
    *,
    command_runner: Callable[..., Any] = subprocess.run,
) -> BuildCommandResult:
    if not command or not all(
        isinstance(part, str) and part for part in command
    ):
        raise LocalEntryError(
            "Run-local objective verification command must contain non-empty strings."
        )
    environment = os.environ.copy()
    environment.update(profile.environment)
    from src.mod_agent.build.adapter import run_build_profile_command

    return run_build_profile_command(
        BuildProfile(profile_id=profile.profile_id, build_system="dotnet",
                     working_directory=profile.working_directory, command=command,
                     timeout_seconds=profile.timeout_seconds),
        environment=environment, command_runner=command_runner,
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

