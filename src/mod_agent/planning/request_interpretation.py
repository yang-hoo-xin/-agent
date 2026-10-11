"""Shared provisional interpretation; model projection owns semantic decomposition."""

from __future__ import annotations

import re
from typing import Any

from .request_planner import (
    has_config_intent,
    has_runtime_behavior_intent,
    has_runtime_diagnostic_intent,
    has_runtime_reload_intent,
)

REQUEST_INTERPRETATION_VERSION = "request_interpretation_v2"

# Only explicit interception directives establish a pre-model obligation.
# 为什么要有它：提及技术名词、保持行为和实现过程约束不能替用户选择实现机制。
_INTERCEPTION_DIRECTIVE = re.compile(
    r"^(?:(?:please|explicitly|must)\s+)*(?:hook|intercept)\s+\w+"
    r"|^(?:(?:please|explicitly|must)\s+)*(?:use|require)\s+(?:a\s+)?(?:harmony\s+)?(?:hook|method interception)\b"
    r"|^(?:请)?(?:明确)?(?:要求|必须|需要|使用|采用|通过|用)(?:明确)?(?:方法拦截|拦截(?:游戏)?方法|Hook|Harmony)"
    r"|^拦截(?:游戏)?方法",
    re.IGNORECASE,
)
_NON_DIRECTIVE = re.compile(
    r"\b(?:no|not|never|without|avoid|don't|if|whether|optional|may|might|could)\b"
    r"|不要|不得|禁止|无需|不需要|不使用|不预|避免|是否|如果|可选|可能|判断|调查",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY = re.compile(
    r"[。！？!?;；,，\n]|\.(?:\s|$)|\b(?:but|then|and)\b|但是|然后|并且|并",
    re.IGNORECASE,
)
_UI_TERMS = re.compile(r"\b(?:ui|hud|overlay|feedback|message|indicator|icon|color|colour)\b", re.I)
_GAME_STARTUP_EXCLUSION = re.compile(
    r"^\s*(?:(?:本次|这次)(?:验收|验证|任务)\s*)?(?:不要求|无需|不需要)\s*"
    r"(?:启动\s*(?:游戏|GTFO)|(?:游戏|GTFO)\s*启动)"
    r"|^\s*(?:please\s+)?(?:no\s+need(?:\s+for|\s+to)?|do\s+not\s+require)\s+"
    r"(?:(?:the\s+)?game\s+startup|startup\s+(?:of|for)\s+(?:the\s+)?game"
    r"|(?:start(?:ing)?|launch(?:ing)?)\s+(?:the\s+)?game)\b",
    re.IGNORECASE,
)


def runtime_diagnostic_clauses(request: str) -> tuple[str, ...]:
    """Exclude only explicit game-startup directives from diagnostic term scanning.

    为什么要有它：明确免除本次启动验收不能反向生成启动义务；其它诊断、重载和无法启动的问题仍保留，原请求不裁剪。
    """
    return tuple(_GAME_STARTUP_EXCLUSION.sub(" ", clause)
                 for clause in _CLAUSE_BOUNDARY.split(request))


def interpret_request(request: str) -> dict[str, Any]:
    """Keep raw input and distinguish positive directives from unresolved means.

    Clause matching is a bounded fast path, not a semantic classifier. Unmatched
    wording remains unresolved for the existing RequirementProjection model turn.
    """
    explicit_interception = any(
        _INTERCEPTION_DIRECTIVE.search(clause.strip())
        and not _NON_DIRECTIVE.search(clause)
        for clause in _CLAUSE_BOUNDARY.split(request)
    )
    runtime_lead = has_runtime_behavior_intent(request)
    config_lead = has_config_intent(request)
    diagnostics = has_runtime_diagnostic_intent(request)
    ui_lead = bool(_UI_TERMS.search(request))
    request_type = (
        "hook-required" if explicit_interception else
        "config-only" if config_lead and not runtime_lead else
        "runtime diagnostics" if diagnostics else
        "UI feedback" if ui_lead else
        "gameplay behavior"
    )
    return {
        "schema_version": REQUEST_INTERPRETATION_VERSION,
        "raw_request": request,
        "semantic_status": "pending_requirement_projection",
        "request_type": request_type,
        "hook_requirement": {
            "required": bool(explicit_interception),
            "reason": (
                "explicit_user_method_interception" if explicit_interception
                else "implementation_mechanism_unresolved"
            ),
        },
        "requires_runtime_evidence": (
            request_type != "config-only" or diagnostics or has_runtime_reload_intent(request)
        ),
        "investigation_leads": [
            name for name, present in (
                ("runtime behavior", runtime_lead),
                ("configuration", config_lead),
                ("runtime diagnostics", diagnostics),
                ("UI feedback", ui_lead),
            ) if present
        ],
    }
