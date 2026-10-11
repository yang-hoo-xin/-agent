"""Real original approval/Graph/Applier/BuildAdapter; only compiler process replaced."""

from __future__ import annotations

import io
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from scripts import dsh_deliver_run as bridge
from src.mod_agent import product_executor
from tests.unit import test_product_execution as product_fixture


@pytest.fixture
def retained(tmp_path, monkeypatch, request):
    with_game = getattr(request, "param", True)
    original = product_fixture._request

    def request_with_build_inputs(path):
        request, store = original(path)
        target = Path(request.isolated_target_root)
        (target / "Example.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk" />', encoding="utf-8")
        (target / "nuget.config").write_text('<configuration><packageSources><clear /></packageSources></configuration>', encoding="utf-8")
        return replace(request, run_id="run"), store

    monkeypatch.setattr(product_fixture, "_request", request_with_build_inputs)
    case = product_fixture._formal_coverage_vertical_scenario(tmp_path)
    preflight = product_executor.preflight_product_execution(case.request, case.adapters, case.store)
    with pytest.raises(product_executor.ProductApprovalDeferred) as captured:
        product_executor.execute_product_execution(preflight, case.adapters, case.store, defer_approval=True)
    pending = captured.value.to_dict()
    root = Path(case.request.isolated_workspace_root)
    game = root / "build_dependencies" / "GameFolder" if with_game else None
    if game is not None:
        game.mkdir(parents=True)
        (game / "Reference.dll").write_bytes(b"unit reference bytes")
    target = Path(case.request.isolated_target_root)
    profile = bridge._create_nuget_isolated_build_profile(run_root=root, working_directory=target,
        config_file=target / "nuget.config", bepinex_dir=None, game_folder_dir=game, timeout_seconds=3)
    game_snapshot = bridge._binary_tree_snapshot(game) if game is not None else None
    manifest = {"run_id": case.request.run_id, "nuget_isolated_build_profile": profile.to_dict(),
        "build_dependency": {"game_folder": {"isolated_copy": str(game), "build_uses_isolated_copy": True,
            "copy_file_count": len(game_snapshot), "copy_snapshot_sha256": bridge._binary_tree_snapshot_sha256(game_snapshot)}
            if game is not None else None},
        "baseline_build": {"artifact_path": str(root / "baseline" / "bin" / "Example.dll"),
            "build_profile": {"working_directory": str(root / "baseline")}}, "objective_verification_command": None}
    (root / "run_result.json").write_text(json.dumps(pending), encoding="utf-8")
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    config = tmp_path / "execution.json"
    config.write_text(json.dumps({"arguments": ["--run-id", case.request.run_id,
        "--request-id", case.request.request_id, "--workspace-root", str(root.parent),
        "--target-project", case.request.source_root, "--defer-approval"]}), encoding="utf-8")
    # Delivery is a sibling of the configured workspace, not nested inside it.
    delivery = tmp_path.parent / (tmp_path.name + "-delivered")
    calls = []

    def compiler(command, **kwargs):
        calls.append((tuple(command), kwargs))
        assert kwargs["cwd"] == target
        assert kwargs["env"]["NUGET_PACKAGES"] == str(profile.packages_path)
        assert command[0] == "dotnet" and command[1] in ("restore", "build")
        if command[1] == "build":
            assert case.target.read_bytes() == case.source_after
            output = target / "bin" / "Example.dll"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"unit compiler output from approved source")
        return subprocess.CompletedProcess(command, 0, "test compiler succeeded", "")

    monkeypatch.setattr(bridge.subprocess, "run", compiler)
    arguments = {"config_path": str(config), "delivery_root": str(delivery), "run_id": case.request.run_id}
    return SimpleNamespace(case=case, pending=pending, root=root, game=game, target=target,
        config=config, delivery=delivery, calls=calls, arguments=arguments, profile=profile)


def _approve(retained):
    preview = bridge.deliver_run(**retained.arguments, action="preview")
    return {"decision": "approve", "reviewer": "unit-human", "scope_hash": preview["scope_hash"]}


def test_preview_is_read_only_and_exposes_exact_full_delivery_scope(retained):
    before = retained.case.target.read_bytes()
    result = bridge.deliver_run(**retained.arguments, action="preview")
    assert result["status"] == "awaiting_approval" and result["approval_ready"] is True
    assert result["binding"]["checkpoint"] == retained.pending["workflow_checkpoint"]
    assert result["binding"]["human_semantic_decision_binding"] == retained.pending["human_semantic_decision_binding"]
    assert result["build_profile"] == retained.profile.to_dict()
    assert result["unified_diff"] == retained.pending["unified_diff"]
    assert result["model_calls_performed"] == result["builds_performed"] == 0
    assert retained.case.target.read_bytes() == before and retained.calls == []
    assert not retained.delivery.exists()


def test_same_diff_apply_build_retention_and_restart_do_not_repeat_effects(retained):
    decision = _approve(retained)
    result = bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert result["status"] == "delivered", result
    assert result["product_source_writes_performed"] is True and result["builds_performed"] == 1
    assert result["receipt"]["apply_result"]["isolated_workspace_created"] is False
    assert result["model_calls_performed"] == result["runtime_executions_performed"] == 0
    assert retained.case.canonical.read_bytes() == retained.case.canonical_before
    folder = retained.delivery / retained.case.request.run_id
    assert (folder / "project" / "Behavior.cs").read_bytes() == retained.case.source_after
    assert (folder / "project" / "bin" / "Example.dll").read_bytes() == b"unit compiler output from approved source"
    assert (folder / "build_dependencies" / "GameFolder" / "Reference.dll").read_bytes() == b"unit reference bytes"
    assert (folder / "original_artifacts").is_dir()
    log_root = folder / "build_environment" / "dsh_delivery"
    assert "dotnet restore" in (log_root / "stdout.log").read_text(encoding="utf-8")
    assert json.loads((log_root / "phases.json").read_text(encoding="utf-8"))["build_executed"] is True
    from src.mod_agent.artifacts import ArtifactRef

    built = retained.case.store.semantic_read_immutable(ArtifactRef(**result["receipt"]["build_result"]["build_result"]))["data"]
    assert Path(built["stdout_path"]).read_bytes() == (log_root / "stdout.log").read_bytes()
    assert len(retained.calls) == 2
    # Each invocation reconstructs ArtifactStore/checkpoint owner; no in-memory state is reused.
    for action in ("status", "deliver"):
        again = bridge.deliver_run(**retained.arguments, action=action,
            decision=decision if action == "deliver" else None)
        assert again["status"] == "delivered" and again["read_only"] is True
        assert again["builds_performed"] == 0 and again["product_source_writes_performed"] is False
    assert len(retained.calls) == 2


@pytest.mark.parametrize("retained", [False], indirect=True)
def test_no_game_project_delivers_through_original_approval_graph_without_fake_dependencies(retained):
    preview = bridge.deliver_run(**retained.arguments, action="preview")
    assert preview["dependency_identity"] is None
    assert preview["build_profile"]["game_folder_dir"] is None
    decision = {"decision": "approve", "reviewer": "unit-human", "scope_hash": preview["scope_hash"]}
    result = bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert result["status"] == "delivered", result
    assert result["product_source_writes_performed"] is True and result["builds_performed"] == 1
    folder = retained.delivery / retained.case.request.run_id
    assert (folder / "project" / "Behavior.cs").read_bytes() == retained.case.source_after
    assert (folder / "project" / "bin" / "Example.dll").read_bytes() == b"unit compiler output from approved source"
    assert not (retained.root / "build_dependencies").exists()
    assert not (folder / "build_dependencies").exists()
    assert retained.case.canonical.read_bytes() == retained.case.canonical_before
    assert all(not any("GameFolder=" in arg for arg in command) for command, _ in retained.calls)
    assert len(retained.calls) == 2
    again = bridge.deliver_run(**retained.arguments, action="status")
    assert again["status"] == "delivered" and again["read_only"] is True
    assert len(retained.calls) == 2


@pytest.mark.parametrize("retained", [False], indirect=True)
@pytest.mark.parametrize("damage", ["unexpected_declared_game", "missing_declared_game", "missing_bound_directory"])
def test_no_game_declaration_drift_stops_before_apply_or_build(retained, damage):
    decision = _approve(retained)
    manifest_path = retained.root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = retained.root / "build_dependencies" / "missing"
    if damage == "unexpected_declared_game":
        manifest["nuget_isolated_build_profile"]["game_folder_dir"] = str(missing)
    else:
        manifest["build_dependency"]["game_folder"] = {"isolated_copy": str(missing),
            "build_uses_isolated_copy": True, "copy_file_count": 0, "copy_snapshot_sha256": "0" * 64}
        if damage == "missing_bound_directory":
            manifest["nuget_isolated_build_profile"]["game_folder_dir"] = str(missing)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # 为什么要有它：None 只表达无依赖，不能把声明漂移或丢失的已绑定依赖视为允许交付。
    with pytest.raises((ValueError, FileNotFoundError)):
        bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert retained.case.target.read_bytes() == retained.case.source_before
    assert retained.calls == [] and not retained.delivery.exists()
    assert not retained.case.store.list_feature_artifact_revisions(retained.pending["feature_id"], "resume_report")


@pytest.mark.parametrize("damage", ["missing_decision", "wrong_scope", "source", "isolated", "dependency", "profile"])
def test_bad_approval_or_drift_writes_no_product_and_runs_no_build(retained, damage):
    decision = _approve(retained)
    if damage == "missing_decision":
        decision = None
    elif damage == "wrong_scope":
        decision["scope_hash"] = "sha256:" + "0" * 64
    elif damage == "source":
        retained.case.canonical.write_bytes(b"new source")
    elif damage == "isolated":
        retained.case.target.write_bytes(b"new isolated source")
    elif damage == "dependency":
        (retained.game / "Reference.dll").write_bytes(b"different dependency")
    else:
        path = retained.root / "run_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["nuget_isolated_build_profile"]["build_command"].append("-p:Other=true")
        path.write_text(json.dumps(manifest), encoding="utf-8")
    before = retained.case.target.read_bytes()
    with pytest.raises(ValueError):
        bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert retained.case.target.read_bytes() == before and retained.calls == []
    assert not retained.case.store.list_feature_artifact_revisions(retained.pending["feature_id"], "resume_report")
    assert not retained.delivery.exists()


def test_explicit_rejection_uses_original_owner_and_is_visible_after_reopen(retained):
    decision = {**_approve(retained), "decision": "reject"}
    result = bridge.deliver_run(**retained.arguments, action="reject", decision=decision)
    assert result["status"] == "rejected"
    assert result["receipt"]["apply_result"]["resume_report"] is not None
    assert retained.case.target.read_bytes() == retained.case.source_before
    assert retained.calls == [] and not (retained.delivery / retained.case.request.run_id).exists()
    again = bridge.deliver_run(**retained.arguments, action="status")
    assert again["status"] == "rejected" and again["approval_ready"] is False


def test_failed_build_is_not_delivered_or_repeated(retained, monkeypatch):
    calls = []

    def failed(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "Example.cs(1,1): error CS1002: ; expected")

    monkeypatch.setattr(bridge.subprocess, "run", failed)
    decision = _approve(retained)
    result = bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert result["status"] == "failed", result
    assert result["receipt"]["build_result"]["status"] == "failed"
    assert not (retained.delivery / retained.case.request.run_id).exists()
    again = bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert again["status"] == "failed" and len(calls) == 1


def test_corrupted_delivery_is_not_reported_as_delivered(retained):
    result = bridge.deliver_run(**retained.arguments, action="deliver", decision=_approve(retained))
    assert result["status"] == "delivered", result
    (retained.delivery / retained.case.request.run_id / "project" / "bin" / "Example.dll").write_bytes(b"changed")
    with pytest.raises(ValueError, match="RETAINED_BYTES_CHANGED"):
        bridge.deliver_run(**retained.arguments, action="status")


def test_cli_requires_fixed_run_and_explicit_stdin_channel(retained, monkeypatch, capsys):
    argv = ["--config-path", str(retained.config), "--delivery-root", str(retained.delivery),
            "--run-id", retained.case.request.run_id, "--action", "deliver"]
    assert bridge.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "DSH_DELIVERY_DECISION_CHANNEL_REQUIRED"
    decision = _approve(retained)
    monkeypatch.setattr(bridge.sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(decision).encode())))
    assert bridge.main([*argv, "--decision-stdin"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "delivered"
    with pytest.raises(ValueError, match="CONFIGURED_RUN_MISMATCH"):
        bridge.deliver_run(**{**retained.arguments, "run_id": "different"}, action="status")


def test_concurrent_submissions_claim_receipt_once_before_owner_effects(retained, monkeypatch):
    decision = _approve(retained)
    original = bridge._preview
    barrier = Barrier(2)

    def concurrent_preview(case):
        result = original(case)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(bridge, "_preview", concurrent_preview)

    def call():
        try:
            return bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
        except FileExistsError:
            return {"status": "exclusive_claim_rejected"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(), range(2)))
    assert sorted(result["status"] for result in results) == ["delivered", "exclusive_claim_rejected"]
    assert len(retained.calls) == 2


@pytest.mark.parametrize("owner", ["resume_deferred_approval", "continue_reviewed_patch"])
def test_owner_exception_after_effect_preserves_unknown_instead_of_zero(retained, monkeypatch, owner):
    actual = getattr(bridge, owner)

    def after_effect(**kwargs):
        actual(**kwargs)
        raise RuntimeError("unit interruption after physical effect")

    monkeypatch.setattr(bridge, owner, after_effect)
    decision = _approve(retained)
    result = bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert result["status"] == "blocked"
    assert result["receipt"]["uncertain_effects"] is not None
    if owner == "resume_deferred_approval":
        assert result["product_source_writes_performed"] is None
        assert result["builds_performed"] == 0
    else:
        assert result["product_source_writes_performed"] is True
        assert result["builds_performed"] is None
    calls = len(retained.calls)
    again = bridge.deliver_run(**retained.arguments, action="deliver", decision=decision)
    assert again["status"] == "blocked" and len(retained.calls) == calls


def test_receipt_cannot_invent_success_without_original_apply_and_build(retained):
    preview = bridge.deliver_run(**retained.arguments, action="preview")
    _, _, path = bridge._paths(str(retained.config), str(retained.delivery), retained.case.request.run_id)
    bridge._write_receipt(path, {"run_id": retained.case.request.run_id,
        "checkpoint": retained.pending["workflow_checkpoint"], "delivery_path": preview["delivery_path"],
        "scope_hash": preview["scope_hash"], "binding": preview["binding"], "status": "delivered"}, initial=True)
    with pytest.raises(ValueError, match="SUCCESS_OWNER_EVIDENCE_MISSING"):
        bridge.deliver_run(**retained.arguments, action="status")


@pytest.mark.parametrize("relative,reason", [("Behavior.cs", "COPIED_SOURCE_DIFFERS_FROM_APPLY"),
    ("bin/Example.dll", "COPIED_DLL_DIFFERS_FROM_BUILD")])
def test_copy_cannot_deliver_changed_source_or_dll_as_approved_product(retained, monkeypatch, relative, reason):
    copy = bridge._copy_verified

    def changed_copy(source, destination):
        copy(source, destination)
        if destination.name == "project":
            (destination / relative).write_bytes(b"changed after verified copying")

    monkeypatch.setattr(bridge, "_copy_verified", changed_copy)
    result = bridge.deliver_run(**retained.arguments, action="deliver", decision=_approve(retained))
    assert result["status"] == "blocked" and reason in result["receipt"]["reason"]
    assert "delivery_ref" not in result["receipt"]


@pytest.mark.parametrize("write_fact", [True, None])
def test_blocked_apply_projection_preserves_partial_or_unknown_write_fact(retained, monkeypatch, write_fact):
    """Projection-only owner result; this fixture does not perform partial writes."""
    monkeypatch.setattr(bridge, "resume_deferred_approval", lambda **_: {
        "status": "blocked", "product_source_writes_performed": write_fact,
        "apply_write_details": {"write_completion": "partial" if write_fact else "unknown"}})
    result = bridge.deliver_run(**retained.arguments, action="deliver", decision=_approve(retained))
    assert result["status"] == "blocked" and result["product_source_writes_performed"] is write_fact
    assert result["builds_performed"] == 0 and retained.calls == []
