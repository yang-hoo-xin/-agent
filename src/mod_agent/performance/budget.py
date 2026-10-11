"""Config-driven performance budget checks for controlled-agent operations."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.core.settings import PerformanceOperationSettings, PerformanceSettings


def _require_finite(value, field_name):
    # 为什么要有它：NaN 可绕过范围比较；只检查浮点有限性以保留合法的大整数和 None。
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


@dataclass(frozen=True)
class BudgetLimit:
    """Limits for one controlled-agent operation."""

    operation: str
    max_api_calls: int | None = None
    max_items: int | None = None
    max_batches: int | None = None
    max_duration_ms: int | None = None
    max_concurrency: int | None = None
    cache_enabled: bool | None = None
    on_exceed: str = "block"

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must be non-empty")
        if self.on_exceed not in {"block", "degrade"}:
            raise ValueError("on_exceed must be 'block' or 'degrade'")
        for field_name in (
            "max_api_calls",
            "max_items",
            "max_batches",
            "max_duration_ms",
        ):
            value = getattr(self, field_name)
            _require_finite(value, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        _require_finite(self.max_concurrency, "max_concurrency")
        if self.max_concurrency is not None and self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero")

    @classmethod
    def from_settings(
        cls,
        operation: str,
        settings: PerformanceOperationSettings,
    ) -> "BudgetLimit":
        return cls(
            operation=operation,
            max_api_calls=settings.max_api_calls,
            max_items=settings.max_items,
            max_batches=settings.max_batches,
            max_duration_ms=settings.max_duration_ms,
            max_concurrency=settings.max_concurrency,
            cache_enabled=settings.cache_enabled,
            on_exceed=settings.on_exceed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "max_api_calls": self.max_api_calls,
            "max_items": self.max_items,
            "max_batches": self.max_batches,
            "max_duration_ms": self.max_duration_ms,
            "max_concurrency": self.max_concurrency,
            "cache_enabled": self.cache_enabled,
            "on_exceed": self.on_exceed,
        }


@dataclass(frozen=True)
class OperationUsage:
    """Observed usage for a controlled-agent operation."""

    operation: str
    api_calls: int = 0
    item_count: int = 0
    batch_count: int = 0
    duration_ms: float = 0.0
    concurrency: int = 1
    cache_hits: int = 0
    cache_misses: int = 0
    cache_enabled: bool | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must be non-empty")
        for field_name in (
            "api_calls",
            "item_count",
            "batch_count",
            "duration_ms",
            "cache_hits",
            "cache_misses",
        ):
            value = getattr(self, field_name)
            _require_finite(value, field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        _require_finite(self.concurrency, "concurrency")
        if self.concurrency <= 0:
            raise ValueError("concurrency must be greater than zero")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "api_calls": self.api_calls,
            "item_count": self.item_count,
            "batch_count": self.batch_count,
            "duration_ms": self.duration_ms,
            "concurrency": self.concurrency,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_enabled": self.cache_enabled,
        }


@dataclass(frozen=True)
class BudgetDecision:
    """Result of checking observed usage against one budget."""

    operation: str
    status: str
    allowed: bool
    exceeded_limits: tuple[dict[str, Any], ...]
    budget: BudgetLimit
    usage: OperationUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "allowed": self.allowed,
            "exceeded_limits": list(self.exceeded_limits),
            "budget": self.budget.to_dict(),
            "usage": self.usage.to_dict(),
            "timing_summary": {
                "duration_ms": self.usage.duration_ms,
                "max_duration_ms": self.budget.max_duration_ms,
            },
            "trace_events": self.trace_events(),
        }

    def trace_events(self) -> list[dict[str, Any]]:
        checked = {
            "event": "perf.budget_checked",
            "operation": self.operation,
            "status": self.status,
            "allowed": self.allowed,
        }
        if not self.exceeded_limits:
            return [checked]
        return [
            checked,
            {
                "event": "perf.limit_exceeded",
                "operation": self.operation,
                "limits": list(self.exceeded_limits),
            },
        ]

    def artifact_status(self) -> str:
        if self.status in {"blocked", "degraded"}:
            return "blocked"
        return "success"


class PerformanceBudgetPolicy:
    """Budget policy keyed by controlled-agent operation name."""

    def __init__(self, budgets: Iterable[BudgetLimit]) -> None:
        self._budgets = {budget.operation: budget for budget in budgets}

    @classmethod
    def from_settings(
        cls,
        settings: PerformanceSettings | Mapping[str, Any],
    ) -> "PerformanceBudgetPolicy":
        if isinstance(settings, PerformanceSettings):
            budgets = [
                BudgetLimit.from_settings(operation, operation_settings)
                for operation, operation_settings in settings.operations.items()
            ]
            return cls(budgets)

        operations = settings.get("operations", settings)
        if not isinstance(operations, Mapping):
            raise ValueError("performance settings must contain an operations mapping")

        budgets: list[BudgetLimit] = []
        for operation, raw_budget in operations.items():
            if not isinstance(operation, str):
                raise ValueError("operation must be a string")
            if not isinstance(raw_budget, Mapping):
                raise ValueError(f"budget for {operation!r} must be a mapping")
            budgets.append(
                BudgetLimit(
                    operation=operation,
                    max_api_calls=raw_budget.get("max_api_calls"),
                    max_items=raw_budget.get("max_items"),
                    max_batches=raw_budget.get("max_batches"),
                    max_duration_ms=raw_budget.get("max_duration_ms"),
                    max_concurrency=raw_budget.get("max_concurrency"),
                    cache_enabled=raw_budget.get("cache_enabled"),
                    on_exceed=str(raw_budget.get("on_exceed", "block")),
                )
            )
        return cls(budgets)

    def check(self, usage: OperationUsage) -> BudgetDecision:
        budget = self._budgets.get(usage.operation)
        if budget is None:
            budget = BudgetLimit(operation=usage.operation)
            return BudgetDecision(
                operation=usage.operation,
                status="blocked",
                allowed=False,
                exceeded_limits=(
                    {
                        "limit": "configured_operation",
                        "allowed": "registered",
                        "observed": "missing",
                    },
                ),
                budget=budget,
                usage=usage,
            )

        exceeded = tuple(self._exceeded_limits(budget, usage))
        if not exceeded:
            return BudgetDecision(
                operation=usage.operation,
                status="allowed",
                allowed=True,
                exceeded_limits=(),
                budget=budget,
                usage=usage,
            )

        status = "degraded" if budget.on_exceed == "degrade" else "blocked"
        return BudgetDecision(
            operation=usage.operation,
            status=status,
            allowed=status == "degraded",
            exceeded_limits=exceeded,
            budget=budget,
            usage=usage,
        )

    def to_job_status_payload(
        self,
        *,
        job_id: str,
        decision: BudgetDecision,
        created_at: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        artifact_refs: Iterable[str] = (),
        trace_refs: Iterable[str] = (),
    ) -> dict[str, Any]:
        return {
            "node_name": "performance_budget",
            "stage": "performance_budget",
            "message": f"Performance budget check for {decision.operation}: {decision.status}",
            "job_id": job_id,
            "job_type": f"{decision.operation}_budget_check",
            "status": decision.status,
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "artifact_refs": list(artifact_refs),
            "trace_refs": list(trace_refs),
            "error": self._error_message(decision),
            "budget_summary": decision.to_dict(),
        }

    @staticmethod
    def _error_message(decision: BudgetDecision) -> str | None:
        if not decision.exceeded_limits:
            return None
        limits = ", ".join(
            str(limit["limit"]) for limit in decision.exceeded_limits
        )
        if decision.status == "degraded":
            return f"Performance budget degraded; exceeded limits: {limits}"
        return f"Performance budget blocked; exceeded limits: {limits}"

    @staticmethod
    def _exceeded_limits(
        budget: BudgetLimit,
        usage: OperationUsage,
    ) -> list[dict[str, Any]]:
        checks = (
            ("max_api_calls", budget.max_api_calls, usage.api_calls),
            ("max_items", budget.max_items, usage.item_count),
            ("max_batches", budget.max_batches, usage.batch_count),
            ("max_duration_ms", budget.max_duration_ms, usage.duration_ms),
            ("max_concurrency", budget.max_concurrency, usage.concurrency),
        )
        exceeded: list[dict[str, Any]] = []
        for limit_name, limit_value, observed_value in checks:
            if limit_value is not None and observed_value > limit_value:
                exceeded.append(
                    {
                        "limit": limit_name,
                        "allowed": limit_value,
                        "observed": observed_value,
                    }
                )
        if (
            budget.cache_enabled is not None
            and usage.cache_enabled != budget.cache_enabled
        ):
            exceeded.append(
                {
                    "limit": "cache_enabled",
                    "allowed": budget.cache_enabled,
                    "observed": usage.cache_enabled,
                }
            )
        return exceeded
