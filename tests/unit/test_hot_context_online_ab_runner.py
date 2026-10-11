import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_hot_context_online_ab as hot


@pytest.fixture
def case(tmp_path):
    runner = tmp_path / "snapshot/scripts/run_context_online_ab.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# frozen fake runner, never executed")
    snapshot = hot.save(
        tmp_path / "snapshot.json",
        {
            "snapshot_root": str(runner.parent.parent),
            "files": {"scripts/run_context_online_ab.py": {"sha256": hot.ref(runner)["sha256"]}},
        },
    )
    trial = {
        "trial_id": "s2b1",
        "output_root": str(tmp_path / "results/s2b1"),
        "runtime_required": False,
    }
    trial_ref = hot.save(tmp_path / "trial.json", trial)
    protocol = {
        "trials": [{"trial_id": "s2b1", "trial_ref": trial_ref}],
        "wall_seconds": 900,
        "platform_snapshot_ref": snapshot,
        "startup_condition": {"expected_service_version": "0.35.1"},
        "common_configuration": {
            "model": "qwen3-coder:30b",
            "digest": "fixed",
            "context_window": 65536,
            "temperature": 0,
        },
    }
    reference = hot.save(tmp_path / "protocol.json", protocol)
    calls, commands = [], []

    def api(endpoint, payload, timeout):
        calls.append((endpoint, payload, timeout))
        values = {
            "/api/version": {"version": "0.35.1"},
            "/api/tags": {"models": [{"name": "qwen3-coder:30b", "digest": "fixed"}]},
            "/api/generate": {
                "model": "qwen3-coder:30b",
                "done": True,
                "response": "A",
                "prompt_eval_count": 9,
                "eval_count": 1,
                "load_duration": 42,
                "eval_duration": 20,
            },
            "/api/ps": {
                "models": [
                    {
                        "name": "qwen3-coder:30b",
                        "digest": "fixed",
                        "context_length": 65536,
                        "size_vram": 1000,
                    }
                ]
            },
        }
        return json.dumps(values[endpoint]).encode()

    def launch(command, output):
        commands.append(command)
        (output / "task.stdout.bin").write_bytes(b"stdout")
        (output / "task.stderr.bin").write_bytes(b"")
        return SimpleNamespace(wait=lambda: 2)

    return SimpleNamespace(
        tmp=tmp_path,
        protocol=protocol,
        reference=reference,
        trial=trial,
        calls=calls,
        commands=commands,
        api=api,
        launch=launch,
    )


def invoke(case, api=None, **kwargs):
    return hot.run(
        case.reference,
        "s2b1",
        api=api or case.api,
        launcher=case.launch,
        preflight_runner=lambda *args: 0,
        **kwargs,
    )


def test_hot_start_uses_task_free_fixed_warmup_and_frozen_runner(case):
    result = invoke(case)
    startup = hot.read(result["startup_ref"])
    assert result["agent_started"] and result["returncode"] == 2 and result["success"] is False
    assert startup["condition_classification"] == "hot_verified"
    assert [c[0] for c in case.calls].count("/api/generate") == 1
    payload = next(c[1] for c in case.calls if c[0] == "/api/generate")
    assert payload == {
        "model": "qwen3-coder:30b",
        "prompt": hot.WARMUP_PROMPT,
        "stream": False,
        "keep_alive": -1,
        "options": {"num_ctx": 65536, "temperature": 0, "num_predict": 1},
    }
    assert all(0 < call[2] <= 180 for call in case.calls)
    assert case.commands[0][5] == str(case.tmp / "snapshot/scripts/run_context_online_ab.py")
    assert "--allow-runtime" not in case.commands[0]
    warmup = hot.read(startup["warmup_ref"])
    assert (warmup["input_tokens"], warmup["output_tokens"], warmup["cached_input_tokens"]) == (
        9,
        1,
        None,
    )
    assert warmup["load_ns"] == 42 and len(startup["residency_refs"]) == 2
    assert not Path(case.trial["output_root"]).exists()


@pytest.mark.parametrize(
    "mode", ["version", "digest", "gpu", "context", "missing_context", "warmup_error", "api_error"]
)
def test_bad_or_unknown_warmup_never_starts_task_and_retains_result(case, mode):
    def api(endpoint, payload, timeout):
        if mode == "api_error" and endpoint == "/api/generate":
            raise TimeoutError("injected")
        value = json.loads(case.api(endpoint, payload, timeout))
        if mode == "version" and endpoint == "/api/version":
            value["version"] = "other"
        if mode == "digest" and endpoint == "/api/tags":
            value["models"][0]["digest"] = "other"
        if endpoint == "/api/ps":
            if mode == "gpu":
                value["models"][0]["size_vram"] = 0
            if mode == "context":
                value["models"][0]["context_length"] = 4096
            if mode == "missing_context":
                del value["models"][0]["context_length"]
        if mode == "warmup_error" and endpoint == "/api/generate":
            value["done"] = False
        return json.dumps(value).encode()

    result = invoke(case, api)
    assert result["agent_started"] is False and result["success"] is None
    assert case.commands == []
    startup = hot.read(result["startup_ref"])
    assert startup["condition_classification"] in {"unknown", "deviation"}
    assert (Path(result["startup_ref"]["path"]).parent / "result.json").is_file()


def test_runtime_flag_defaults_to_refusal_before_any_http_or_preflight(case):
    case.trial["runtime_required"] = True
    Path(case.protocol["trials"][0]["trial_ref"]["path"]).write_text(json.dumps(case.trial))
    case.protocol["trials"][0]["trial_ref"] = hot.ref(
        case.protocol["trials"][0]["trial_ref"]["path"]
    )
    Path(case.reference["path"]).write_text(json.dumps(case.protocol))
    case.reference = hot.ref(case.reference["path"])
    with pytest.raises(ValueError, match="RUNTIME_NOT_STARTED"):
        invoke(case)
    assert not case.calls and not case.commands


def test_post_task_residency_deviation_is_not_hidden(case):
    count = 0

    def api(endpoint, payload, timeout):
        nonlocal count
        value = json.loads(case.api(endpoint, payload, timeout))
        if endpoint == "/api/ps":
            count += 1
            if count == 2:
                value["models"] = []
        return json.dumps(value).encode()

    result = invoke(case, api)
    assert result["agent_started"] is True
    assert result["condition_classification"] == "deviation"
    assert sum(call[0] == "/api/generate" for call in case.calls) == 1


def test_rejects_second_execution_and_frozen_source_drift(case):
    invoke(case)
    with pytest.raises(FileExistsError):
        invoke(case)
    assert len(case.commands) == 1


def test_no_redirects_or_other_endpoints():
    with pytest.raises(ValueError, match="REDIRECT"):
        hot.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://remote.invalid")
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        hot.request_api("https://remote.invalid", None, 1)


def test_metric_consumer_reads_native_warmup_and_bound_residency(case):
    from scripts.summarize_context_online_ab import inspect_startup

    result = invoke(case)
    measured = inspect_startup({"startup_ref": result["startup_ref"]})
    assert measured["condition_classification"] == "hot_verified"
    assert measured["warmup"]["input_tokens"] == 9
    assert measured["warmup"]["output_tokens"] == 1
    assert measured["warmup"]["cache_tokens"] is None


def test_monitor_is_read_only_and_reports_transient_failure(case, monkeypatch):
    import time

    monkeypatch.setattr(hot, "POLL_SECONDS", 0.01)
    ps_calls = 0

    def api(endpoint, payload, timeout):
        nonlocal ps_calls
        if endpoint == "/api/ps":
            ps_calls += 1
            if ps_calls == 2:
                raise TimeoutError("transient unavailable")
        return case.api(endpoint, payload, timeout)

    def launch(command, output):
        case.commands.append(command)
        return SimpleNamespace(wait=lambda: (time.sleep(0.05), 0)[1])

    result = hot.run(
        case.reference, "s2b1", api=api, launcher=launch, preflight_runner=lambda *a: 0
    )
    assert result["agent_started"] and result["success"]
    assert result["condition_classification"] == "unknown"
    assert ps_calls >= 3
    assert sum(call[0] == "/api/generate" for call in case.calls) == 1


def test_expired_warmup_cannot_start_task(case, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(hot.time, "monotonic", lambda: now[0])

    def api(endpoint, payload, timeout):
        raw = case.api(endpoint, payload, timeout)
        if endpoint == "/api/generate":
            now[0] += 181
        return raw

    result = invoke(case, api)
    assert not result["agent_started"] and result["success"] is None
    startup = hot.read(result["startup_ref"])
    assert "WARMUP_BUDGET_EXHAUSTED" in startup["error"]
    assert hot.read(startup["warmup_ref"])["input_tokens"] == 9
    assert not case.commands


@pytest.mark.parametrize("phase", ["before_task", "after_task"])
def test_additional_resident_model_is_deviation(case, phase):
    seen = 0

    def api(endpoint, payload, timeout):
        nonlocal seen
        value = json.loads(case.api(endpoint, payload, timeout))
        if endpoint == "/api/ps":
            seen += 1
            if phase == "before_task" or seen > 1:
                value["models"].append(
                    {
                        "name": "other-model",
                        "digest": "other",
                        "context_length": 4096,
                        "size_vram": 100,
                    }
                )
        return json.dumps(value).encode()

    result = invoke(case, api)
    assert result["condition_classification"] == "deviation"
    assert result["agent_started"] is (phase == "after_task")
    assert sum(call[0] == "/api/generate" for call in case.calls) == 1
    startup = hot.read(result["startup_ref"])
    assert any(
        hot.read(reference)["reason"] == "ADDITIONAL_MODEL_RESIDENT"
        for reference in startup["residency_refs"]
    )
