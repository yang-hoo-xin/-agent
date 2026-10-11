import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import dsh_run_request as bridge
from scripts import prepare_reload_trials as owner
from src.mod_agent import platform_execution_snapshot


@pytest.fixture(autouse=True)
def common_platform_check(monkeypatch):
    monkeypatch.setattr(platform_execution_snapshot, "FrozenExecution", lambda *_: SimpleNamespace(
        verify_files=lambda: None, verify_loaded_modules=lambda: None))


def dispatch_inputs(tmp_path):
    base = tmp_path / "b1"
    base.mkdir()
    task_ref = owner.save(tmp_path / "task.json", {"request": "same request"})
    settings = tmp_path / "settings.yaml"
    settings.write_text("{}", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    factory = tmp_path / "factory.py"
    factory.write_text("# fixture", encoding="utf-8")
    template = {"behavior_evaluator": {"factory_ref": owner.ref(factory),
        "kwargs": {"source_root": "unallocated"}}}
    worker_ref = owner.save(base / "worker.json", template)
    profile = {"arguments": ["--target-project", str(source), "--workspace-root", str(base / "w"),
        "--settings", str(settings), "--local-ollama", "--ollama-model", "fixture",
        "--ollama-context-window", "32768", "--ollama-timeout-seconds", "180",
        "--task-model-call-limit", "18", "--model-call-budget-policy", "task_total_only",
        "--patch-worker-config", worker_ref["path"], "--defer-approval", "--confirm-isolated-write", "--allow-build"],
        "worker_path_bindings": [{"path": ["behavior_evaluator", "kwargs", "source_root"], "relative_path": "generated_mods/source"}]}
    profile_ref = owner.save(base / "profile.json", profile)
    allocated = bridge.prepare_new_task(execution_config=profile_ref["path"], description="same request")
    argv = bridge.build_product_argv(execution_config=allocated, description="same request")
    trial = {"root": str(base), "workspace_root": str(base / "w"), "product_snapshot_root": str(base / "p"),
             "profile_ref": profile_ref, "worker_ref": worker_ref, "knowledge_ref": owner.ref(settings)}
    prepared = {"task_ref": task_ref, "platform_root": str(tmp_path), "settings_ref": owner.ref(settings),
                "dependency_ref": owner.ref(settings), "api_config_ref": owner.ref(settings), "platform_snapshot_ref": owner.ref(settings)}
    return trial, prepared, argv


def test_source_snapshot_order_is_not_treated_as_changed_bytes():
    first = [{"path": "Plugin.cs", "sha256": "a", "size": 3}, {"path": "nuget.config", "sha256": "b", "size": 4}]
    assert owner.same_source_snapshot(first, list(reversed(first)))
    assert not owner.same_source_snapshot(first, [first[0], {**first[1], "sha256": "changed"}])


@pytest.mark.parametrize("change", ["description", "budget", "permission", "identity", "worker"])
def test_frozen_transport_rejects_changed_allocated_argv_before_snapshot_or_process(tmp_path, monkeypatch, change):
    trial, prepared, argv = dispatch_inputs(tmp_path)
    monkeypatch.setattr(owner, "prepare_snapshot", lambda **_: pytest.fail("invalid selection reached freeze"))
    if change == "description":
        argv[-1] = "changed"
    elif change == "budget":
        argv[argv.index("--task-model-call-limit") + 1] = "19"
    elif change == "permission":
        argv.insert(-2, "--allow-game-launch")
    elif change == "identity":
        argv[argv.index("--run-id") + 1] = "../../escape"
    else:
        path = Path(argv[argv.index("--patch-worker-config") + 1])
        worker = json.loads(path.read_text())
        worker["behavior_evaluator"]["kwargs"]["source_root"] = "elsewhere"
        path.write_text(json.dumps(worker))
    with pytest.raises(ValueError, match="RELOAD_DISPATCH"):
        owner.frozen_executor(trial=trial, prepared=prepared, runner=lambda *_a, **_k: pytest.fail("process"))(argv)


def test_accepted_transport_binds_exact_argv_and_preserves_stdout(tmp_path, monkeypatch, capsys):
    trial, prepared, argv = dispatch_inputs(tmp_path)
    captured = {}
    def freeze(**kwargs):
        captured.update(kwargs)
        return owner.save(tmp_path / "snapshot.json", {"fake": "test only"})
    monkeypatch.setattr(owner, "prepare_snapshot", freeze)
    def process(command, **kwargs):
        assert command[1:3] == ["-I", "-B"]
        assert "--_child" in command
        return SimpleNamespace(returncode=2, stdout='{"status":"partial"}\n', stderr="fixture error")
    assert owner.frozen_executor(trial=trial, prepared=prepared, runner=process)(argv) == 2
    assert captured["business_argv"] == argv
    assert str(captured["run_root"]).endswith(argv[argv.index("--run-id") + 1])
    assert capsys.readouterr().out == '{"status":"partial"}\n'


def test_common_platform_change_cannot_be_frozen_as_new_valid_trial(tmp_path, monkeypatch):
    trial, prepared, argv = dispatch_inputs(tmp_path)
    def fail():
        raise ValueError("FROZEN_EXECUTION_SOURCE_CHANGED")
    monkeypatch.setattr(platform_execution_snapshot, "FrozenExecution", lambda *_: SimpleNamespace(
        verify_files=fail, verify_loaded_modules=lambda: None))
    monkeypatch.setattr(owner, "prepare_snapshot", lambda **_: pytest.fail("drift must not be copied"))
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        owner.frozen_executor(trial=trial, prepared=prepared)(argv)
