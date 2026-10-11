"""Counterexamples for resource-budget numeric admission, without executing work.

为什么要有它：NaN can compare false against both zero and a finite ceiling, so a
resource decision must reject an unmeasurable value before claiming admission.
These inputs do not establish an observed production overrun or permission escape.
"""

import pytest

from src.mod_agent.performance import BudgetLimit, OperationUsage, PerformanceBudgetPolicy


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "positive_infinity", "negative_infinity"])
@pytest.mark.parametrize("field", [
    "api_calls", "item_count", "batch_count", "duration_ms", "concurrency",
    "cache_hits", "cache_misses",
])
def test_resource_usage_rejects_nonfinite_measurements(field, value):
    with pytest.raises(ValueError, match=field):
        OperationUsage(operation="retrieval", **{field: value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "positive_infinity", "negative_infinity"])
@pytest.mark.parametrize("field", [
    "max_api_calls", "max_items", "max_batches", "max_duration_ms", "max_concurrency",
])
def test_resource_limits_reject_nonfinite_ceilings(field, value):
    with pytest.raises(ValueError, match=field):
        BudgetLimit(operation="retrieval", **{field: value})


def test_zero_usage_is_admitted_at_zero_resource_limits():
    policy = PerformanceBudgetPolicy([BudgetLimit(
        operation="retrieval", max_api_calls=0, max_items=0, max_batches=0,
        max_duration_ms=0, max_concurrency=1,
    )])

    decision = policy.check(OperationUsage(operation="retrieval", duration_ms=0.0))

    assert decision.allowed is True
    assert decision.status == "allowed"
    assert decision.exceeded_limits == ()


@pytest.mark.parametrize("duration,allowed", [(0.0, True), (1.25, True), (2.0, True), (2.001, False)])
def test_finite_duration_preserves_fractional_and_exact_boundary_semantics(duration, allowed):
    policy = PerformanceBudgetPolicy([BudgetLimit(operation="retrieval", max_duration_ms=2)])

    decision = policy.check(OperationUsage(operation="retrieval", duration_ms=duration))

    assert decision.allowed is allowed
    assert decision.status == ("allowed" if allowed else "blocked")
    assert decision.exceeded_limits == (() if allowed else (
        {"limit": "max_duration_ms", "allowed": 2, "observed": duration},
    ))


def test_optional_unbounded_limit_uses_none_with_finite_usage():
    policy = PerformanceBudgetPolicy([BudgetLimit(operation="retrieval", max_duration_ms=None)])

    decision = policy.check(OperationUsage(operation="retrieval", duration_ms=1_000_000.5))

    assert decision.allowed is True
    assert decision.budget.max_duration_ms is None
