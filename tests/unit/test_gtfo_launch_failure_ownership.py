from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.runtime import gtfo_automation as runtime


class Process:
    pid = 741
    stdout = None
    stderr = None

    def __init__(self, cleanup_fails=False):
        self.exitcode = None
        self.events = []
        self.cleanup_fails = cleanup_fails

    def poll(self):
        return self.exitcode

    def terminate(self):
        self.events.append("terminate")
        if self.cleanup_fails:
            raise OSError("cleanup refused")
        self.exitcode = 1

    def wait(self, timeout):
        self.events.append(("wait", timeout))
        return self.exitcode


@pytest.mark.parametrize("phase", ["construct", "start"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_diagnostics_preserves_process_ownership(monkeypatch, tmp_path, phase, cleanup_fails):
    process = Process(cleanup_fails)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: process)
    original = RuntimeError("diagnostics unavailable")

    class Diagnostics:
        def __init__(self, **kwargs):
            if phase == "construct":
                raise original

        def start(self, actual):
            assert actual is process
            raise original

    monkeypatch.setattr(runtime, "_GTFOProcessDiagnosticsCapture", Diagnostics)
    profile = runtime.GTFORealRuntimeProfile("test", "unused.exe", str(tmp_path))
    with pytest.raises(runtime.GTFOProcessLaunchError) as failure:
        runtime._launch_gtfo_process(profile, output_directory=tmp_path)
    error = failure.value
    assert error.original_error is original and error.__cause__ is original
    assert error.process_handle.process is process and error.process_handle.pid == 741
    assert process.events[0] == "terminate"
    if cleanup_fails:
        assert isinstance(error.cleanup_error, OSError) and process.poll() is None
        process.cleanup_fails = False
        runtime._terminate_process(error.process_handle)
        assert process.poll() == 1
    else:
        assert error.cleanup_error is None and process.poll() == 1
    assert ("wait", 15) in process.events


def test_popen_failure_has_no_invented_handle(monkeypatch, tmp_path):
    original = OSError("launch refused")

    def popen(*args, **kwargs):
        raise original

    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    with pytest.raises(OSError) as failure:
        runtime._launch_gtfo_process(
            runtime.GTFORealRuntimeProfile("test", "unused.exe", str(tmp_path)),
            output_directory=tmp_path,
        )
    assert failure.value is original


def test_successful_launch_preserves_existing_handle_contract(monkeypatch, tmp_path):
    process = Process()
    diagnostics = SimpleNamespace(start=lambda p: None)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(runtime, "_GTFOProcessDiagnosticsCapture", lambda **k: diagnostics)
    handle = runtime._launch_gtfo_process(
        runtime.GTFORealRuntimeProfile("test", "unused.exe", str(tmp_path)),
        output_directory=Path(tmp_path),
    )
    assert handle.process is process and handle.diagnostics is diagnostics
    assert not process.events


def test_normal_runner_failure_payload_keeps_started_process_identity(tmp_path):
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"path validation only")
    config = tmp_path / "BepInEx/config/BepInEx.cfg"
    config.parent.mkdir(parents=True)
    config.write_text("[Logging.Disk]\nAppendLog = false\n", encoding="utf-8")
    profile = runtime.GTFORealRuntimeProfile(
        "test", str(executable), str(tmp_path),
        log_paths=("BepInEx/LogOutput.log",), terminate_after_capture=True,
    )
    process = Process()
    handle = runtime.GTFOProcessHandle(741, process)

    def launch(_):
        raise runtime.GTFOProcessLaunchError(handle, RuntimeError("setup failed"), None)

    payload = runtime.GTFORealRuntimeAutomationRunner().run(
        feature_id="test", profile=profile, acceptance_criteria=(),
        runtime_verification_plan=(), input_execution_mode="local", allow_game_launch=True,
        process_launcher=launch,
    )
    assert payload["failure_ownership"]["failure_class"] == "process_launch_failed"
    assert payload["runtime_process"]["pid"] == 741
    assert process.poll() == 1
