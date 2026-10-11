import hashlib
import json
from pathlib import Path

import pytest

from src.mod_agent.runtime.gtfo_automation import GTFOProcessHandle
from src.mod_agent.runtime.isolated_candidate import run_isolated_runtime_candidate


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def case(tmp_path):
    game = tmp_path / "clone"
    game.mkdir()
    plugin = game / "BepInEx/plugins/Observer.dll"
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b"prior")
    hud = game / "BepInEx/plugins/Hud.dll"
    hud.write_bytes(b"hud")
    executable = game / "GTFO.exe"
    executable.write_bytes(b"exe")
    log = game / "BepInEx/LogOutput.log"
    log.write_bytes(b"old-success\n")
    candidate = tmp_path / "candidate.dll"
    candidate.write_bytes(b"new")
    config = dict(game_root=str(game), plugin_relative_path="BepInEx/plugins/Observer.dll",
                  expected_prior_plugin_ref=ref(plugin), protected_file_refs=[ref(hud)],
                  game_executable_ref=ref(executable), timeout_seconds=30,
                  authorization_origin="user explicitly authorized isolated clone runtime")
    return config, ref(candidate), tmp_path / "out", plugin, log


@pytest.fixture(autouse=True)
def quick_owner_collection(monkeypatch):
    from dataclasses import replace

    from src.mod_agent.runtime import isolated_candidate as owner
    collect = owner._collect_persistent_logs
    monkeypatch.setattr(owner, "_collect_persistent_logs", lambda profile, criteria, **kwargs:
        collect(replace(profile, timeout_seconds=0.002, poll_interval_seconds=0.001), criteria, **kwargs))


class Process:
    def __init__(self):
        self.exitcode = None
        self.terminated = 0

    def poll(self):
        return self.exitcode

    def terminate(self):
        self.terminated += 1
        self.exitcode = 0

    def wait(self, timeout):
        return self.exitcode


class Runner:
    def __init__(self, log, *, failure=None, returned_failure=False):
        self.log = log
        self.failure = failure
        self.returned_failure = returned_failure
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        profile = kwargs["profile"]
        assert profile.timeout_seconds == 30
        assert profile.startup_markers == ()
        assert profile.acceptance_markers == {}
        assert kwargs["acceptance_criteria"] == ()
        assert kwargs["screenshot_capturer"](None, None) is None
        handle = kwargs["process_launcher"](profile)
        with self.log.open("ab") as stream:
            stream.write(b"new-runtime\n")
        kwargs["log_collector"](profile, ())
        if self.failure:
            raise self.failure
        return {"runtime_process": {"pid": handle.pid}, **({"failure": {"message": "collection failed"}} if self.returned_failure else {})}


def run(case, **kwargs):
    config, candidate, out, plugin, log = case
    process = Process()
    runner = kwargs.pop("runner", Runner(log))
    result = run_isolated_runtime_candidate(
        config=config, candidate_ref=candidate, output_directory=out,
        runner=runner, process_probe=kwargs.pop("process_probe", lambda: []),
        process_launcher=lambda _: GTFOProcessHandle(123, process), **kwargs,
    )
    return result, process, runner


def test_fresh_logs_and_exact_hashes_are_retained_and_original_restored(case):
    result, process, runner = run(case)
    assert result["status"] == "collected"
    assert process.terminated == 1
    assert result["process"] == {"pid": 123, "exited": True, "observed_live": True, "cleanup_errors": []}
    assert case[3].read_bytes() == b"prior"
    assert case[4].read_bytes() == b"old-success\nnew-runtime\n"
    assert len(result["current_run_logs"]) == 1
    item = result["current_run_logs"][0]
    assert Path(item["ref"]["path"]).read_bytes() == b"new-runtime\n"
    assert item["ref"] == ref(Path(item["ref"]["path"]))
    assert item["source_window"]["run_local_start_byte"] == len(b"old-success\n")
    assert json.loads(Path(result["restoration_ref"]["path"]).read_bytes())["restored"] is True
    assert not (Path(case[0]["game_root"]) / ".candidate-runtime.lock").exists()


@pytest.mark.parametrize("returned", [False, True])
def test_runner_failure_still_stops_owned_process_and_restores(case, returned):
    runner = Runner(case[4], failure=None if returned else RuntimeError("broken"), returned_failure=returned)
    result, process, _ = run(case, runner=runner)
    assert result["status"] == "blocked"
    assert case[3].read_bytes() == b"prior"
    assert process.terminated == 1
    assert result["error"]
    assert result["current_run_logs"]
    assert json.loads(Path(result["restoration_ref"]["path"]).read_bytes())["restored"] is True


@pytest.mark.parametrize("which", ["prior", "protected", "exe", "candidate"])
def test_drift_rejected_before_launch(case, which):
    reference = {"prior": case[0]["expected_prior_plugin_ref"], "protected": case[0]["protected_file_refs"][0],
                 "exe": case[0]["game_executable_ref"], "candidate": case[1]}[which]
    Path(reference["path"]).write_bytes(b"drift")
    result, _, runner = run(case)
    assert result["status"] == "blocked"
    assert "FILE_DRIFT" in result["error"]
    assert runner.calls == 0


@pytest.mark.parametrize("escape", ["../escape.dll", "BepInEx/../../../escape.dll"])
def test_path_escape_rejected(case, escape):
    case[0]["plugin_relative_path"] = escape
    result, _, runner = run(case)
    assert result["status"] == "blocked"
    assert "PATH_ESCAPE" in result["error"]
    assert runner.calls == 0


def test_existing_process_rejected_without_touching_it(case):
    result, process, runner = run(case, process_probe=lambda: [999])
    assert result["status"] == "blocked"
    assert "EXISTING_GTFO_PROCESS" in result["error"]
    assert runner.calls == 0 and process.terminated == 0
    assert case[3].read_bytes() == b"prior"


def test_concurrent_lock_is_not_removed(case):
    lock = Path(case[0]["game_root"]) / ".candidate-runtime.lock"
    lock.write_text("someone else")
    result, _, runner = run(case)
    assert result["status"] == "blocked"
    assert runner.calls == 0
    assert lock.read_text() == "someone else"


def test_process_appearing_before_launch_restores_without_killing_other(case):
    states = iter([[], [999]])
    result, process, runner = run(case, process_probe=lambda: next(states))
    assert result["status"] == "blocked"
    assert case[3].read_bytes() == b"prior"
    assert process.terminated == 0


def test_protected_file_changed_during_run_blocks(case):
    runner = Runner(case[4])
    original = runner.run
    def changed(**kwargs):
        result = original(**kwargs)
        Path(case[0]["protected_file_refs"][0]["path"]).write_bytes(b"changed")
        return result
    runner.run = changed
    result, _, _ = run(case, runner=runner)
    assert result["status"] == "blocked"
    assert not result["protected_files_unchanged"]
    assert case[3].read_bytes() == b"prior"


def test_real_runner_interface_collects_full_window_without_game(case, monkeypatch):
    from dataclasses import replace

    from src.mod_agent.runtime import gtfo_automation as automation
    game = Path(case[0]["game_root"])
    cfg = game / "BepInEx/config/BepInEx.cfg"
    cfg.parent.mkdir()
    cfg.write_text("[Logging.Disk]\nAppendLog = true\n")
    original_collect = automation._collect_persistent_logs
    def quick_collect(profile, criteria, **kwargs):
        assert profile.timeout_seconds == 30
        assert not profile.startup_markers and not profile.acceptance_markers
        return original_collect(replace(profile, timeout_seconds=0.002, poll_interval_seconds=0.001), criteria, **kwargs)
    from src.mod_agent.runtime import isolated_candidate as owner

    monkeypatch.setattr(owner, "_collect_persistent_logs", quick_collect)
    process = Process()
    def launch(_):
        with case[4].open("ab") as stream:
            stream.write(b"actual-runner-new-log\n")
        return GTFOProcessHandle(234, process)
    result = run_isolated_runtime_candidate(config=case[0], candidate_ref=case[1],
        output_directory=case[2], process_probe=lambda: [], process_launcher=launch)
    assert result["status"] == "collected", result
    payload = json.loads(Path(result["runner_ref"]["path"]).read_bytes())
    assert payload["runtime_process"]["pid"] == 234
    assert payload["runtime_trust_binding"]["checks"]["current_run_logs"]["status"] == "passed"
    assert Path(result["current_run_logs"][0]["ref"]["path"]).read_bytes() == b"actual-runner-new-log\n"
    assert process.terminated == 1


def test_logs_emitted_on_termination_are_separate_from_runner_observation(case):
    class LateProcess(Process):
        def terminate(self):
            with case[4].open("ab") as stream:
                stream.write(b"late-only\n")
            super().terminate()
    process = LateProcess()
    result = run_isolated_runtime_candidate(config=case[0], candidate_ref=case[1],
        output_directory=case[2], process_probe=lambda: [], runner=Runner(case[4]),
        process_launcher=lambda _: GTFOProcessHandle(345, process))
    observed = Path(result["current_run_logs"][0]["ref"]["path"]).read_bytes()
    after_stop = Path(result["post_stop_current_run_logs"][0]["ref"]["path"]).read_bytes()
    assert observed == b"new-runtime\n"
    assert after_stop == b"new-runtime\nlate-only\n"



@pytest.mark.parametrize("kill_fails", [False, True])
def test_terminate_exception_fallback_and_live_process_retains_lock(case, kill_fails):
    class DifficultProcess(Process):
        def terminate(self):
            raise OSError("terminate refused")
        def kill(self):
            if kill_fails:
                raise OSError("kill refused")
            self.exitcode = 1
    process = DifficultProcess()
    result = run_isolated_runtime_candidate(config=case[0], candidate_ref=case[1],
        output_directory=case[2], process_probe=lambda: [], runner=Runner(case[4]),
        process_launcher=lambda _: GTFOProcessHandle(567, process))
    assert result["process"]["cleanup_errors"]
    lock = Path(case[0]["game_root"]) / ".candidate-runtime.lock"
    if kill_fails:
        assert case[3].read_bytes() == Path(case[1]["path"]).read_bytes()
        assert result["status"] == "blocked"
        assert result["process"]["exited"] is False
        assert json.loads(lock.read_bytes())["game_pid"] == 567
        assert result["retained_lock_ref"] == ref(lock)
    else:
        assert case[3].read_bytes() == b"prior"
        assert result["status"] == "collected"
        assert result["process"]["exited"] is True
        assert not lock.exists()


@pytest.mark.parametrize("survives", [False, True])
def test_launch_setup_failure_keeps_handle_and_defers_restore_while_alive(case, survives):
    from src.mod_agent.runtime.gtfo_automation import GTFOProcessLaunchError

    class SetupProcess(Process):
        def terminate(self):
            if survives:
                raise OSError("terminate refused")
            super().terminate()

        def kill(self):
            if survives:
                raise OSError("kill refused")
            self.exitcode = 1

    process = SetupProcess()
    handle = GTFOProcessHandle(742, process)

    def launch(_):
        raise GTFOProcessLaunchError(handle, RuntimeError("diagnostics setup failed"), OSError("initial cleanup failed"))

    result = run_isolated_runtime_candidate(
        config=case[0], candidate_ref=case[1], output_directory=case[2],
        process_probe=lambda: [], runner=Runner(case[4]), process_launcher=launch,
    )
    assert result["status"] == "blocked"
    assert result["process"]["pid"] == 742
    assert result["process"]["exited"] is not survives
    lock = Path(case[0]["game_root"]) / ".candidate-runtime.lock"
    if survives:
        assert case[3].read_bytes() == b"new"
        assert json.loads(lock.read_bytes())["game_pid"] == 742
    else:
        assert case[3].read_bytes() == b"prior"
        assert not lock.exists()
