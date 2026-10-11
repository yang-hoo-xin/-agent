"""Explicit game-startup exclusions must not invent runtime acceptance work."""
from __future__ import annotations

import pytest

from src.mod_agent.planning import FeatureSpecBuilder, ModPlanningBriefBuilder, RequestPlanner
from src.mod_agent.planning.request_planner import (
    has_runtime_diagnostic_intent,
    requested_scope_text,
)

ACTUAL_REQUEST = (
    "请修改 AccurateCrosshair 的配置默认行为：没有已保存配置时，让 General Settings 下的 Follow Recoil 默认关闭；"
    "已有配置显式 true 或 false 仍照常生效，其余配置默认值和全部配置键保持不变。"
    "本次验收要求完整工程编译及真实 BepInEx 配置读写检查，不要求启动游戏或验证游戏内画面。"
)


def _spec(request):
    plan = RequestPlanner().plan(request, target_mod="AccurateCrosshair")
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert requested_scope_text(request) == request
    assert plan.user_request == spec.user_request == spec.target_behavior == request
    assert plan.request_interpretation["raw_request"] == request
    return plan, spec


def test_exact_no_game_task_does_not_add_startup_acceptance():
    plan, spec = _spec(ACTUAL_REQUEST)
    assert plan.request_interpretation["request_type"] == "config-only"
    assert plan.requires_runtime_evidence is False
    assert plan.risk_level == "low"
    assert "runtime diagnostics" not in plan.request_interpretation["investigation_leads"]
    assert spec.runtime_verification_plan == ("compile or static validation",)


@pytest.mark.parametrize("clause", [
    "不要求启动游戏", "无需启动游戏", "不需要启动游戏", "不要求游戏启动",
    "本次验收不要求启动游戏",
    "no need for game startup", "no need game startup", "do not require game startup",
    "No need for the game startup",
])
def test_narrow_exclusion_preserves_raw_request_and_compile_checks(clause):
    request = "  Change the configuration default. " + clause + ".\n"
    plan, spec = _spec(request)
    assert has_runtime_diagnostic_intent(request) is False
    assert plan.requires_runtime_evidence is False
    assert spec.runtime_verification_plan == ("compile or static validation",)


@pytest.mark.parametrize("request_text", [
    "修改配置并要求启动游戏检查", "修改配置，修复游戏无法启动", "修复游戏无法启动的问题",
    "Change configuration and require game startup checks.",
    "Fix game not starting.", "Fix the configuration error causing game startup failure.",
    "Change configuration and verify reload.", "修改配置，验收要求重启",
    "Change configuration; no need for game startup, but collect runtime diagnostics.",
    "Change configuration; do not require game startup; verify reload.",
    "修改配置，无需启动游戏，但要求运行时诊断。",
    "修改配置，不要求启动游戏但仍需要诊断日志。",
    "修改配置，不要求启动游戏，但是随后要求启动游戏检查。",
    "Change configuration; no need for game startup and require startup logging.",
    "修改配置，不是不需要启动游戏。", "修改配置，是否不需要启动游戏？",
    "Change configuration; do not assume no need for game startup.",
    "Change configuration; is there no need for game startup?",
])
def test_positive_mixed_and_startup_defect_requests_keep_runtime(request_text):
    plan, spec = _spec(request_text)
    assert plan.requires_runtime_evidence is True
    assert "startup_loaded" in spec.runtime_verification_plan
