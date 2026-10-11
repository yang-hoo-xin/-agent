"""DSH scope binding; owner calls are controlled doubles, not real deployment."""

import json
from types import SimpleNamespace

import pytest

from scripts import dsh_runtime_run as bridge


@pytest.fixture
def scope(tmp_path, monkeypatch):
    settings = tmp_path / "settings.yaml"
    settings.write_text("runtime: fixture\n")
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"settings_path": str(settings),
                                 "runtime_plugin_destination": str(tmp_path / "installed.dll")}))
    checkpoint = {"feature_id": "feature", "path": str(tmp_path / "checkpoint.json"), "artifact_hash": "a" * 64}
    monkeypatch.setattr(bridge, "_inputs", lambda *_: {"run_root": tmp_path, "store": SimpleNamespace(root=tmp_path / "a")})
    monkeypatch.setattr(bridge, "_read_receipt", lambda _: {"status": "delivered", "build_result": {"workflow_checkpoint": checkpoint}})
    preview = {"status": "READY_FOR_EXTERNAL_AUTHORIZATION", "writes_performed": False,
               "runtime_profile": {"profile": {"game_executable": str(tmp_path / "GTFO.exe")},
                                   "plugin_deployment": {"destination_sha256_at_preflight": "old"}},
               "build_result": {"verified_artifact": {"sha256": "new"}}}
    monkeypatch.setattr(bridge, "preflight_local_runtime", lambda **_: preview)
    monkeypatch.setattr(bridge, "_running_game", lambda _: [])
    calls = []
    def resume(**kwargs):
        calls.append(kwargs)
        return {"status": "inconclusive", "dll_copied": True, "behavior_passed": False}
    monkeypatch.setattr(bridge, "resume_local_runtime", resume)
    return SimpleNamespace(arguments={"execution_config": "selected", "delivery_root": "delivered",
        "runtime_config": str(config), "run_id": "run"}, settings=settings, root=tmp_path, calls=calls, preview=preview)


def test_preview_then_exact_confirmation_calls_original_owner_once(scope):
    shown = bridge.runtime_run(**scope.arguments, action="preview")
    assert shown["read_only"] and scope.calls == []
    decision = {"decision": "approve", "reviewer": "human", "scope_hash": shown["scope_hash"]}
    result = bridge.runtime_run(**scope.arguments, action="execute", decision=decision)
    assert result["status"] == "recorded" and result["runtime_success_claimed"] is False
    assert result["owner_result"]["behavior_passed"] is False
    assert len(scope.calls) == 1 and scope.calls[0]["allow_game_directory_write"] is True
    assert scope.calls[0]["allow_game_launch"] is True
    again = bridge.runtime_run(**scope.arguments, action="execute", decision=decision)
    assert again["read_only"] and len(scope.calls) == 1


@pytest.mark.parametrize("change", ["settings", "installed", "build", "approval"])
def test_changed_displayed_scope_stops_before_owner(scope, change):
    shown = bridge.runtime_run(**scope.arguments, action="preview")
    decision = {"decision": "approve", "reviewer": "human", "scope_hash": shown["scope_hash"]}
    if change == "settings":
        scope.settings.write_text("runtime: changed\n")
    elif change == "installed":
        scope.preview["runtime_profile"]["plugin_deployment"]["destination_sha256_at_preflight"] = "changed"
    elif change == "build":
        scope.preview["build_result"]["verified_artifact"]["sha256"] = "changed"
    else:
        decision["scope_hash"] = "wrong"
    with pytest.raises(ValueError, match="EXACT_APPROVAL_REQUIRED"):
        bridge.runtime_run(**scope.arguments, action="execute", decision=decision)
    assert scope.calls == [] and not (scope.root / "dsh_runtime_result.json").exists()


def test_running_game_does_not_start_deployment(scope, monkeypatch):
    monkeypatch.setattr(bridge, "_running_game", lambda _: ["42"])
    result = bridge.runtime_run(**scope.arguments, action="preview")
    assert result["reason"] == "DSH_RUNTIME_GAME_ALREADY_RUNNING" and scope.calls == []


def test_uncertain_owner_failure_is_not_retried(scope, monkeypatch):
    shown = bridge.runtime_run(**scope.arguments, action="preview")
    decision = {"decision": "approve", "reviewer": "human", "scope_hash": shown["scope_hash"]}
    def failed(**kwargs):
        scope.calls.append(kwargs)
        raise RuntimeError("uncertain effect")
    monkeypatch.setattr(bridge, "resume_local_runtime", failed)
    first = bridge.runtime_run(**scope.arguments, action="execute", decision=decision)
    second = bridge.runtime_run(**scope.arguments, action="execute", decision=decision)
    assert first["status"] == second["status"] == "blocked" and len(scope.calls) == 1
