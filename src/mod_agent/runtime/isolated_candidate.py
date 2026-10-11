"""One trusted isolated-game candidate deployment with retained runtime evidence."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .deployment import temporarily_deploy_verified_plugin
from .gtfo_automation import (
    GTFOProcessHandle,
    GTFOProcessLaunchError,
    GTFORealRuntimeAutomationRunner,
    GTFORealRuntimeProfile,
    _capture_log_baselines,
    _collect_persistent_logs,
    _launch_gtfo_process,
    _read_run_local_runtime_logs,
    _terminate_process,
)


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _save(path: Path, value: Any) -> dict[str, str]:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    return _ref(path)


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("ISOLATED_RUNTIME_PATH_ESCAPE")
    return resolved


def _verify(reference: Mapping[str, Any], root: Path | None = None) -> Path:
    path = Path(str(reference["path"])).resolve()
    if root is not None:
        path = _inside(root, path)
    if _ref(path)["sha256"] != reference["sha256"]:
        raise ValueError("ISOLATED_RUNTIME_FILE_DRIFT: " + str(path))
    return path


def _existing_gtfo_processes() -> list[int]:
    if os.name != "nt":
        raise RuntimeError("GTFO_PROCESS_PROBE_REQUIRES_WINDOWS")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "@(Get-Process -Name GTFO -ErrorAction SilentlyContinue) | ForEach-Object { $_.Id }"],
        capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError("GTFO_PROCESS_PROBE_FAILED")
    return [int(line) for line in result.stdout.splitlines() if line.strip()]


def run_isolated_runtime_candidate(
    *, config: Mapping[str, Any], candidate_ref: Mapping[str, str],
    output_directory: str | Path,
    runner: Any = None,
    process_probe: Callable[[], list[int]] | None = None,
    process_launcher: Callable[[GTFORealRuntimeProfile], GTFOProcessHandle] | None = None,
) -> dict[str, Any]:
    """Collect a full observation window; config is an exact caller-authorized clone binding.

    The caller owns authorization and behavior assertions. ``collected`` only means
    fresh evidence was retained and deployment/process cleanup succeeded.
    """
    out = Path(output_directory).resolve()
    out.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schema_version": "isolated_runtime_candidate_v1", "status": "blocked",
        "candidate_ref": dict(candidate_ref), "current_run_logs": [],
        "process": {"pid": None, "exited": False},
        "protected_files_unchanged": False, "error": None,
        "authorization_origin": config.get("authorization_origin"),
        "protected_file_refs": list(config.get("protected_file_refs", [])),
    }
    result["deployment_ref"] = _save(out / "deployment-admission.json", {
        "status": "not_started", "candidate_ref": dict(candidate_ref),
        "expected_prior_plugin_ref": config.get("expected_prior_plugin_ref"),
    })
    deployment = None
    handle = None
    lock_fd = None
    lock_path = None
    retain_lock = False
    baselines = ()
    protected = []
    prior = None
    target = None
    failures: list[str] = []
    probe = process_probe or _existing_gtfo_processes
    try:
        if not isinstance(config.get("authorization_origin"), str) or not config["authorization_origin"].strip():
            raise ValueError("ISOLATED_RUNTIME_AUTHORIZATION_ORIGIN_REQUIRED")
        timeout = config["timeout_seconds"]
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 120:
            raise ValueError("ISOLATED_RUNTIME_TIMEOUT_OUT_OF_RANGE")
        root = Path(str(config["game_root"])).resolve(strict=True)
        relative = Path(str(config["plugin_relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("ISOLATED_RUNTIME_PATH_ESCAPE")
        target = _inside(root, root / relative)
        if target.suffix.lower() != ".dll":
            raise ValueError("ISOLATED_RUNTIME_PLUGIN_MUST_BE_DLL")
        executable = _verify(config["game_executable_ref"], root)
        if executable != root / "GTFO.exe":
            raise ValueError("ISOLATED_RUNTIME_EXECUTABLE_BINDING_INVALID")
        prior = config["expected_prior_plugin_ref"]
        if _verify(prior, root) != target:
            raise ValueError("ISOLATED_RUNTIME_PRIOR_PLUGIN_BINDING_INVALID")
        source = _verify(candidate_ref)
        if source == target:
            raise ValueError("ISOLATED_RUNTIME_CANDIDATE_IS_DESTINATION")
        protected = [dict(item) for item in config["protected_file_refs"]]
        if not protected:
            raise ValueError("ISOLATED_RUNTIME_PROTECTED_REFS_REQUIRED")
        for item in protected:
            if _verify(item, root) == target:
                raise ValueError("ISOLATED_RUNTIME_PROTECTED_PLUGIN_OVERLAP")
        log_paths = []
        for value in config.get("log_relative_paths", ["BepInEx/LogOutput.log"]):
            relative_log = Path(str(value))
            if relative_log.is_absolute() or ".." in relative_log.parts:
                raise ValueError("ISOLATED_RUNTIME_PATH_ESCAPE")
            log_path = _inside(root, root / relative_log)
            if log_path in {target, executable, *[Path(item["path"]).resolve() for item in protected]}:
                raise ValueError("ISOLATED_RUNTIME_LOG_FILE_OVERLAP")
            log_paths.append(str(log_path))
        if not log_paths:
            raise ValueError("ISOLATED_RUNTIME_LOG_PATHS_REQUIRED")
        lock_path = root / ".candidate-runtime.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(lock_fd, str(os.getpid()).encode("ascii"))
        if probe():
            raise RuntimeError("EXISTING_GTFO_PROCESS")
        # A second identity check happens under the clone lock, before mutation.
        _verify(prior, root)
        _verify(config["game_executable_ref"], root)
        for item in protected:
            _verify(item, root)
        profile = GTFORealRuntimeProfile(
            profile_id="isolated-candidate-observation", game_executable=str(executable),
            working_directory=str(root), launch_args=("-logFile", str(out / "Player.log")),
            log_paths=tuple([*log_paths, str(out / "Player.log")]),
            screenshot_directory=str(out / "screenshots"), timeout_seconds=timeout,
            startup_markers=(), acceptance_markers={}, terminate_after_capture=False,
            operator_completion_required=False,
        )
        baselines = _capture_log_baselines(profile)
        result["log_baseline_ref"] = _save(out / "log-baselines.json", [vars(item) for item in baselines])

        def launch(active_profile: GTFORealRuntimeProfile) -> GTFOProcessHandle:
            nonlocal handle, retain_lock
            if probe():
                raise RuntimeError("EXISTING_GTFO_PROCESS")
            _verify(config["game_executable_ref"], root)
            if _ref(target)["sha256"] != candidate_ref["sha256"]:
                raise ValueError("ISOLATED_RUNTIME_DEPLOYED_FILE_DRIFT")
            try:
                handle = (process_launcher(active_profile) if process_launcher else
                          _launch_gtfo_process(active_profile, output_directory=out / "diagnostics"))
            except GTFOProcessLaunchError as exc:
                handle = exc.process_handle
                result["process"]["pid"] = handle.pid
                retain_lock = True
                raise
            result["process"]["pid"] = handle.pid
            retain_lock = True
            os.lseek(lock_fd, 0, os.SEEK_SET)
            os.ftruncate(lock_fd, 0)
            os.write(lock_fd, json.dumps({"owner_pid": os.getpid(), "game_pid": handle.pid,
                "status": "owned_process_active", "evidence_directory": str(out)}).encode("utf-8"))
            if handle.process is None or not callable(getattr(handle.process, "poll", None)) or handle.process.poll() is not None:
                raise RuntimeError("ISOLATED_RUNTIME_PROCESS_NOT_LIVE")
            result["process"]["observed_live"] = True
            return handle

        def retain_windows(windows: Any, prefix: str) -> list[dict[str, Any]]:
            retained = []
            latest = {window["path"]: window for window in windows}
            for index, window in enumerate(latest.values()):
                if window["status"] != "passed":
                    continue
                raw = Path(window["path"]).read_bytes()[window["run_local_start_byte"]:window["run_local_end_byte"]]
                if hashlib.sha256(raw).hexdigest() != window["run_local_sha256"]:
                    raise RuntimeError("ISOLATED_RUNTIME_LOG_CHANGED_DURING_CAPTURE")
                path = out / f"{prefix}-{index}.log"
                path.write_bytes(raw)
                retained.append({"source_path": window["path"], "ref": _ref(path), "source_window": dict(window)})
            return retained

        def collect(active_profile: GTFORealRuntimeProfile, criteria: tuple[str, ...]):
            snapshot = _collect_persistent_logs(active_profile, criteria, baselines=baselines)
            result["current_run_logs"] = retain_windows(snapshot.source_windows, "current-run")
            result["log_windows_ref"] = _save(out / "log-windows.json", list(snapshot.source_windows))
            return snapshot

        with temporarily_deploy_verified_plugin(
            source_path=source, destination_path=target, backup_directory=out / "backup",
            expected_source_sha256=candidate_ref["sha256"], allow_game_directory_write=True,
            expected_destination_existed=True, expected_destination_sha256=prior["sha256"],
            # 为什么要有它：仅对本次部署，进程仍活着或存活状态不可读时保留 DLL 和备份，不能靠释放上下文绕过恢复边界。
            restore_guard=lambda: handle is None or handle.process.poll() is not None,
        ) as deployment:
            result["deployment_ref"] = _save(out / "deployment.json", deployment.to_dict())
            try:
                payload = (runner or GTFORealRuntimeAutomationRunner()).run(
                    feature_id="isolated-candidate-observation", profile=profile,
                    acceptance_criteria=(), runtime_verification_plan=("Collect a complete fresh log window",),
                    input_execution_mode="no_input_readonly_observation", allow_game_launch=True,
                    process_launcher=launch, log_collector=collect, screenshot_capturer=lambda *_: None,
                    process_diagnostic_directory=out / "diagnostics",
                )
                result["runner_ref"] = _save(out / "runner-result.json", payload)
                if payload.get("failure"):
                    raise RuntimeError("ISOLATED_RUNTIME_RUNNER_FAILED: " + str(payload["failure"]))
            finally:
                if handle is not None and handle.process is not None:
                    cleanup_errors = []
                    if handle.process.poll() is None:
                        try:
                            _terminate_process(handle)
                        except Exception as exc:
                            cleanup_errors.append(f"{type(exc).__name__}: {exc}")
                    if handle.process.poll() is None:
                        try:
                            handle.process.kill()
                            handle.process.wait(timeout=5)
                        except Exception as exc:
                            cleanup_errors.append(f"{type(exc).__name__}: {exc}")
                    result["process"]["exited"] = handle.process.poll() is not None
                    retain_lock = not result["process"]["exited"]
                    result["process"]["cleanup_errors"] = cleanup_errors
                    if not result["process"]["exited"]:
                        retain_lock = True
                        os.lseek(lock_fd, 0, os.SEEK_SET)
                        os.ftruncate(lock_fd, 0)
                        os.write(lock_fd, json.dumps({"owner_pid": os.getpid(), "game_pid": handle.pid,
                            "status": "owned_process_still_alive", "evidence_directory": str(out)}).encode("utf-8"))
                        raise RuntimeError("ISOLATED_RUNTIME_PROCESS_NOT_EXITED_LOCK_RETAINED")
        if handle is None:
            raise RuntimeError("ISOLATED_RUNTIME_NO_PROCESS_LAUNCHED")
    except Exception as exc:
        failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            if baselines:
                _, _, windows, _ = _read_run_local_runtime_logs(baselines)
                if any(window["status"] == "blocked" for window in windows):
                    failures.append("ISOLATED_RUNTIME_LOG_BOUNDARY_BLOCKED")
                result["post_stop_current_run_logs"] = retain_windows(windows, "post-stop")
                result["post_stop_log_windows_ref"] = _save(out / "post-stop-log-windows.json", list(windows))
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        try:
            restored = bool(deployment is not None and deployment.restored and target is not None and _ref(target)["sha256"] == prior["sha256"])
            result["restoration_ref"] = _save(out / "restoration.json", {
                "restored": restored, "deployment": deployment.to_dict() if deployment else None,
                "process": result["process"],
            })
            if deployment is not None and not restored:
                failures.append("ISOLATED_RUNTIME_RESTORATION_FAILED")
            if "game_executable_ref" in config:
                _verify(config["game_executable_ref"])
            result["protected_files_unchanged"] = bool(protected) and all(_verify(item) for item in protected)
            if not failures and restored and result["process"]["exited"] and any(item["source_window"]["run_local_size_bytes"] > 0 for item in result["current_run_logs"]):
                result["status"] = "collected"
        except Exception as exc:
            failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                    if not retain_lock:
                        lock_path.unlink()
                    else:
                        result["retained_lock_ref"] = _ref(lock_path)
                except OSError as exc:
                    failures.append(f"ISOLATED_RUNTIME_LOCK_RELEASE_FAILED: {exc}")
        result["error"] = "; ".join(failures) or None
        if failures:
            result["status"] = "blocked"
        _save(out / "result.json", result)
    return result
