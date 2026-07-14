"""Deterministic request routing for Phase E planning."""

from __future__ import annotations

import re

from .models import RequestPlan, Uncertainty, stable_feature_id

_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_TARGET_MOD_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{3,})\b")

_CONFIG_REQUEST_TERMS = (
    "config",
    "configuration",
    "default",
    "json",
    "yaml",
    "toml",
    "ini",
    "setting",
    "settings",
    "logging",
    "配置",
)
_RUNTIME_BEHAVIOR_TERMS = (
    "enemy",
    "enemies",
    "damage",
    "hook",
    "harmony",
    "il2cpp",
    "gameplay",
    "movement",
    "move",
    "walk",
    "walking",
    "wall",
    "walls",
    "slope",
    "slopes",
    "ceiling",
    "ceilings",
    "敌人",
    "怪物",
    "移动",
    "行走",
    "墙面",
    "斜面",
    "天花板",
    "寻路",
    "旋转",
    "表面",
    "游戏行为",
    "钩子",
)
_RUNTIME_DIAGNOSTIC_TERMS = (
    "diagnostic",
    "diagnostics",
    "trace",
    "runtime probe",
    "startup",
    "runtime",
    "诊断",
    "跟踪",
    "启动",
    "运行时",
)


def requested_scope_text(user_request: str) -> str:
    """Return the requested behavior before explicit non-goal clauses."""

    return re.split(
        r"\b(?:without|do not|don't|must not)\b",
        user_request.lower(),
        maxsplit=1,
    )[0].strip()


def has_config_intent(user_request: str) -> bool:
    """Return whether the request explicitly includes configuration work."""

    lowered = user_request.lower()
    return any(_contains_term(lowered, term) for term in _CONFIG_REQUEST_TERMS)


def has_runtime_behavior_intent(user_request: str) -> bool:
    """Return whether the requested scope explicitly changes runtime behavior."""

    requested_scope = requested_scope_text(user_request)
    return any(
        _contains_term(requested_scope, term) for term in _RUNTIME_BEHAVIOR_TERMS
    )


def has_runtime_diagnostic_intent(user_request: str) -> bool:
    """Return whether the requested scope explicitly requires runtime observation."""

    requested_scope = requested_scope_text(user_request)
    return any(
        _contains_term(requested_scope, term) for term in _RUNTIME_DIAGNOSTIC_TERMS
    )


def _contains_term(text: str, term: str) -> bool:
    if term.isascii():
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


class RequestPlanner:
    """Turn natural language into a route decision without writing code."""

    def plan(
        self,
        user_request: str,
        *,
        target_mod: str | None = None,
    ) -> RequestPlan:
        """Return a structured request plan."""

        request = user_request.strip()
        feature_id = stable_feature_id(request)
        terms = _TERM_RE.findall(request)
        uncertainties: list[Uncertainty] = []

        if self._is_ambiguous(request, terms):
            uncertainties.append(
                Uncertainty(
                    uncertainty_id="ambiguous_user_request",
                    severity="blocking",
                    question="What exact behavior or code outcome should be changed?",
                )
            )
            return RequestPlan(
                feature_id=feature_id,
                user_request=request,
                route="blocked_ambiguous",
                risk_level="blocked",
                target_mod=target_mod,
                requires_hook_evidence=True,
                requires_runtime_evidence=False,
                hook_requirement={
                    "required": False,
                    "reason": "blocked_ambiguous_request",
                },
                uncertainties=tuple(uncertainties),
                blocked=True,
            )

        resolved_target_mod = target_mod or self._extract_target_mod(request)
        quick_patch = has_config_intent(request)
        requires_hook = has_runtime_behavior_intent(request)
        requires_runtime = requires_hook or has_runtime_diagnostic_intent(request)
        hook_requirement = {
            "required": requires_hook,
            "reason": (
                "gameplay_method_interception"
                if requires_hook
                else "not_required"
            ),
        }
        route = (
            "game_hook_investigation"
            if requires_hook
            else ("quick_patch" if quick_patch else "standard_feature")
        )
        risk_level = "high" if requires_runtime else ("low" if quick_patch else "medium")

        if resolved_target_mod is None:
            uncertainties.append(
                Uncertainty(
                    uncertainty_id="target_mod_unresolved",
                    severity="warning",
                    question="Which target mod or plugin project should receive the change?",
                    default_action="continue_with_evidence",
                )
            )

        return RequestPlan(
            feature_id=feature_id,
            user_request=request,
            route=route,
            risk_level=risk_level,
            target_mod=resolved_target_mod,
            requires_hook_evidence=requires_hook,
            requires_runtime_evidence=requires_runtime,
            hook_requirement=hook_requirement,
            uncertainties=tuple(uncertainties),
            blocked=False,
        )

    @staticmethod
    def _is_ambiguous(request: str, terms: list[str]) -> bool:
        lowered = request.lower()
        if len(request) < 8 or len(terms) < 2:
            return True
        ambiguous_phrases = ("fix it", "that issue", "那个问题", "修一下", "test")
        return any(phrase == lowered or phrase in lowered for phrase in ambiguous_phrases)

    @staticmethod
    def _extract_target_mod(request: str) -> str | None:
        ignored = {
            "GTFO",
            "BepInEx",
            "Harmony",
            "IL2CPP",
            "Unity",
            "JSON",
            "PersistentID",
        }
        for match in _TARGET_MOD_RE.finditer(request):
            candidate = match.group(1)
            if candidate not in ignored:
                return candidate
        return None
