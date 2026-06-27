"""Permission model for controlled tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PermissionLevel = Literal[
    "read_only",
    "report_only",
    "dry_run_write",
    "confirmed_write",
    "external_side_effect",
]


@dataclass(frozen=True)
class PermissionDecision:
    """Structured permission decision for a requested tool action."""

    allowed: bool
    level: PermissionLevel
    reason: str
    required_approval: str | None = None


class PermissionModel:
    """Phase A permission model with dangerous actions blocked by default."""

    _ALWAYS_ALLOWED: frozenset[PermissionLevel] = frozenset(
        {"read_only", "report_only"}
    )
    _BLOCKED_BY_DEFAULT: frozenset[PermissionLevel] = frozenset(
        {"confirmed_write", "external_side_effect"}
    )

    def decide(
        self,
        level: PermissionLevel,
        *,
        explicit_phase: str | None = None,
        human_approved: bool = False,
    ) -> PermissionDecision:
        """Return a permission decision without performing any side effects."""

        if level in self._ALWAYS_ALLOWED:
            return PermissionDecision(
                allowed=True,
                level=level,
                reason=f"{level} actions are allowed by default in Phase A.",
            )

        if level == "dry_run_write":
            if explicit_phase:
                return PermissionDecision(
                    allowed=True,
                    level=level,
                    reason="dry_run_write is allowed only when an explicit phase is set.",
                )
            return PermissionDecision(
                allowed=False,
                level=level,
                reason="dry_run_write requires an explicit phase.",
                required_approval="explicit_phase",
            )

        if level in self._BLOCKED_BY_DEFAULT:
            approval = "human_approval" if human_approved else "human_approval"
            return PermissionDecision(
                allowed=False,
                level=level,
                reason=f"{level} is blocked by default in Phase A.",
                required_approval=approval,
            )

        raise ValueError(f"Unknown permission level: {level}")
