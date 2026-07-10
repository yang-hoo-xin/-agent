"""Deterministic request routing for Phase E planning."""

from __future__ import annotations

import re

from .models import RequestPlan, Uncertainty, stable_feature_id

_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_TARGET_MOD_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{3,})\b")


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
        lowered = request.lower()
        quick_patch = any(
            keyword in lowered
            for keyword in ("config", "configuration", "default", "json", "yaml", "logging")
        )
        runtime_terms = ("enemy", "damage", "hook", "harmony", "il2cpp", "runtime", "gameplay")
        requires_runtime = any(keyword in lowered for keyword in runtime_terms)
        requires_hook = requires_runtime and not quick_patch
        hook_requirement = {
            "required": requires_hook,
            "reason": (
                "gameplay_method_interception"
                if requires_hook
                else "not_required"
            ),
        }
        route = "quick_patch" if quick_patch and not requires_hook else "standard_feature"
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
        ignored = {"GTFO", "BepInEx", "Harmony", "IL2CPP", "Unity"}
        for match in _TARGET_MOD_RE.finditer(request):
            candidate = match.group(1)
            if candidate not in ignored:
                return candidate
        return None
