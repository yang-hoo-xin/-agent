"""Tests for the controlled code-generation platform CLI."""

from __future__ import annotations

import json

import pytest

from src.mod_agent import __version__
from src.mod_agent.cli import main, plan_request


def test_mod_agent_package_imports() -> None:
    """The new platform package is importable through the repository package root."""

    assert __version__


WALLCRAWLER_REQUEST = (
    "希望让 GTFO 的怪物在配置指定的区域内，能够在原本不支持行走的墙面、"
    "斜面和天花板上移动。区域应能通过面向地图开发者的 JSON 配置；配置需要"
    "与游戏/地图数据库的真实 PersistentID 或准确等价身份建立绑定。"
)


def test_plan_request_returns_no_write_planning_result() -> None:
    """Planning stops before feature_spec without performing writes."""

    result = plan_request(
        WALLCRAWLER_REQUEST,
        target_game="GTFO",
        target_mod="WallCrawler",
    )

    assert result.status == "needs_evidence"
    assert result.command == "plan-request"
    assert result.execution_mode == "planning_only"
    assert result.writes_performed is False
    assert result.stopped_before == "feature_spec"
    assert result.request_planning_report["route"] == "game_hook_investigation"
    assert result.request_planning_report["risk_level"] == "high"
    assert result.request_planning_report["requires_hook_evidence"] is True
    assert result.request_planning_report["requires_runtime_evidence"] is True
    assert result.mod_planning_brief["request_type"]["value"] == "hook-required"
    assert result.mod_planning_brief["decision"] == "needs_evidence"
    assert result.mod_planning_brief["next_action"] == "hook discovery"
    assert result.mod_planning_brief["blockers"][0]["code"] == (
        "HOOK_EVIDENCE_REQUIRED"
    )


def test_cli_plan_request_prints_planning_only_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI emits both planning payloads and no downstream artifacts."""

    exit_code = main(
        [
            "plan-request",
            WALLCRAWLER_REQUEST,
            "--target-game",
            "GTFO",
            "--target-mod",
            "WallCrawler",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "needs_evidence"
    assert payload["command"] == "plan-request"
    assert payload["execution_mode"] == "planning_only"
    assert payload["writes_performed"] is False
    assert payload["stopped_before"] == "feature_spec"
    assert payload["request_planning_report"]["target_mod"] == "WallCrawler"
    assert payload["mod_planning_brief"]["user_intent"]["target_game"] == "GTFO"
    assert "feature_spec" not in payload
    assert "patch_proposal" not in payload


def test_cli_plan_request_preserves_true_config_only_route(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "plan-request",
            "default config EnableLogging false",
            "--target-mod",
            "BetterHitFeedback",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ready_for_feature_spec"
    assert payload["request_planning_report"]["route"] == "quick_patch"
    assert payload["mod_planning_brief"]["request_type"]["value"] == "config-only"
    assert payload["writes_performed"] is False


def test_cli_confirmed_apply_is_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    """Confirmed writes are blocked in Phase A."""

    exit_code = main(["apply-patch", "--confirm"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "BLOCKED"
    assert payload["command"] == "apply-patch"
    assert payload["confirmed"] is True


def test_cli_evidence_request_emits_hard_stop_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_gtfo_r8_evidence_only",
        lambda **_: {
            "status": "needs_more_evidence",
            "command": "evidence-request",
            "execution_mode": "evidence_only",
            "current_stage": "evidence_retrieval",
            "stopped_before": "implementation_plan",
            "forbidden_artifacts_present": [],
        },
    )

    exit_code = main(
        [
            "evidence-request",
            "WallCrawler enemy movement hook",
            "--evidence-root",
            "supplied-r8",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["execution_mode"] == "evidence_only"
    assert payload["current_stage"] == "evidence_retrieval"
    assert payload["stopped_before"] == "implementation_plan"
    assert payload["forbidden_artifacts_present"] == []


def test_cli_intelligent_evidence_request_emits_graph_stop_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_intelligent_evidence_only",
        lambda **_: {
            "status": "completed",
            "command": "intelligent-evidence-request",
            "execution_mode": "intelligent_evidence_only",
            "current_stage": "evidence_retrieval",
            "stopped_before": "implementation_plan",
            "forbidden_artifacts_present": [],
            "source_roots_disclosed_to_model": False,
        },
    )

    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover WallCrawler hook evidence.",
            "--source-registry",
            "machine-local-sources.json",
            "--allow-evidence-disclosure",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["execution_mode"] == "intelligent_evidence_only"
    assert payload["current_stage"] == "evidence_retrieval"
    assert payload["source_roots_disclosed_to_model"] is False


def test_cli_intelligent_evidence_request_blocks_without_disclosure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover WallCrawler hook evidence.",
            "--source-registry",
            "machine-local-sources.json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert "--allow-evidence-disclosure" in payload["reason"]


def test_cli_run_request_blocks_before_target_access_without_source_disclosure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "run-request",
            "change local source",
            "--target-project",
            "missing-target",
            "--confirm-isolated-write",
            "--allow-build",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert "--allow-source-disclosure" in payload["reason"]


def test_cli_does_not_treat_non_real_success_status_as_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_local_request",
        lambda **_: {
            "build_summary": {
                "status": "success",
                "claims_real_build_success": False,
            }
        },
    )

    exit_code = main(
        [
            "run-request",
            "change local source",
            "--target-project",
            "target",
            "--allow-source-disclosure",
            "--confirm-isolated-write",
            "--allow-build",
        ]
    )

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["build_summary"][
        "claims_real_build_success"
    ] is False
