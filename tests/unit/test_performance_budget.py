"""Tests for controlled-agent performance budget contracts."""

from __future__ import annotations

import json

from src.core.settings import (
    PerformanceOperationSettings,
    PerformanceSettings,
)
from src.mod_agent.artifacts.store import ArtifactStore
from src.mod_agent.artifacts.registry import ArtifactTypeRegistry
from src.mod_agent.performance import (
    BudgetLimit,
    OperationUsage,
    PerformanceBudgetPolicy,
)


def test_budget_check_allows_usage_within_limits() -> None:
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="retrieval",
                max_api_calls=0,
                max_items=20,
                max_duration_ms=5000,
                cache_enabled=True,
                on_exceed="block",
            )
        ]
    )

    decision = policy.check(
        OperationUsage(
            operation="retrieval",
            api_calls=0,
            item_count=8,
            duration_ms=120.5,
            cache_enabled=True,
        )
    )

    assert decision.status == "allowed"
    assert decision.allowed is True
    assert decision.exceeded_limits == ()
    assert decision.to_dict()["trace_events"] == [
        {
            "event": "perf.budget_checked",
            "operation": "retrieval",
            "status": "allowed",
            "allowed": True,
        }
    ]


def test_budget_check_blocks_over_budget_operation() -> None:
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="tool_call",
                max_api_calls=0,
                max_duration_ms=1000,
                on_exceed="block",
            )
        ]
    )

    decision = policy.check(
        OperationUsage(
            operation="tool_call",
            api_calls=1,
            duration_ms=1500,
        )
    )

    assert decision.status == "blocked"
    assert decision.allowed is False
    assert decision.artifact_status() == "blocked"
    assert decision.exceeded_limits == (
        {"limit": "max_api_calls", "allowed": 0, "observed": 1},
        {"limit": "max_duration_ms", "allowed": 1000, "observed": 1500},
    )
    assert decision.to_dict()["trace_events"][1]["event"] == "perf.limit_exceeded"


def test_budget_check_degrades_when_policy_allows_degradation() -> None:
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="captions",
                max_api_calls=0,
                max_items=5,
                on_exceed="degrade",
            )
        ]
    )

    decision = policy.check(
        OperationUsage(
            operation="captions",
            api_calls=0,
            item_count=8,
        )
    )

    assert decision.status == "degraded"
    assert decision.allowed is True
    assert decision.artifact_status() == "blocked"
    assert decision.exceeded_limits == (
        {"limit": "max_items", "allowed": 5, "observed": 8},
    )


def test_unconfigured_operation_is_blocked_by_default() -> None:
    policy = PerformanceBudgetPolicy([])

    decision = policy.check(OperationUsage(operation="unregistered_operation"))

    assert decision.status == "blocked"
    assert decision.allowed is False
    assert decision.exceeded_limits == (
        {
            "limit": "configured_operation",
            "allowed": "registered",
            "observed": "missing",
        },
    )


def test_cache_policy_is_enforced_when_configured() -> None:
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="indexing",
                cache_enabled=True,
                on_exceed="block",
            )
        ]
    )

    missing_report = policy.check(OperationUsage(operation="indexing"))
    disabled_cache = policy.check(
        OperationUsage(operation="indexing", cache_enabled=False)
    )
    enabled_cache = policy.check(
        OperationUsage(operation="indexing", cache_enabled=True)
    )

    assert missing_report.status == "blocked"
    assert missing_report.exceeded_limits == (
        {"limit": "cache_enabled", "allowed": True, "observed": None},
    )
    assert disabled_cache.status == "blocked"
    assert disabled_cache.exceeded_limits == (
        {"limit": "cache_enabled", "allowed": True, "observed": False},
    )
    assert enabled_cache.status == "allowed"


def test_concurrency_limits_must_be_positive() -> None:
    for value in (0, -1):
        try:
            BudgetLimit(operation="retrieval", max_concurrency=value)
        except ValueError as exc:
            assert str(exc) == "max_concurrency must be greater than zero"
        else:
            raise AssertionError("max_concurrency must reject non-positive values")

    try:
        OperationUsage(operation="retrieval", concurrency=0)
    except ValueError as exc:
        assert str(exc) == "concurrency must be greater than zero"
    else:
        raise AssertionError("concurrency must reject zero")


def test_policy_loads_from_performance_settings() -> None:
    settings = PerformanceSettings(
        operations={
            "eval": PerformanceOperationSettings(
                max_api_calls=0,
                max_batches=5,
                max_duration_ms=30000,
                max_concurrency=1,
                cache_enabled=False,
                on_exceed="block",
            )
        }
    )

    decision = PerformanceBudgetPolicy.from_settings(settings).check(
        OperationUsage(
            operation="eval",
            api_calls=0,
            batch_count=5,
            duration_ms=30000,
            concurrency=1,
            cache_enabled=False,
        )
    )

    assert decision.status == "allowed"
    assert decision.budget.cache_enabled is False


def test_budget_decision_serializes_as_job_status_artifact(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="retrieval",
                max_items=3,
                on_exceed="block",
            )
        ]
    )
    decision = policy.check(
        OperationUsage(
            operation="retrieval",
            item_count=4,
        )
    )
    payload = policy.to_job_status_payload(
        job_id="job_perf_001",
        decision=decision,
        created_at="2026-07-04T00:00:00Z",
        started_at="2026-07-04T00:00:00Z",
        finished_at="2026-07-04T00:00:01Z",
        trace_refs=("trace_perf_001",),
    )

    ref = store.write(
        feature_id="feature_001",
        artifact_type="job_status",
        payload=payload,
        status=decision.artifact_status(),
        trace_refs=["trace_perf_001"],
    )
    envelope = store.read(ref)

    json.dumps(envelope["data"], sort_keys=True)
    assert envelope["status"] == "blocked"
    assert envelope["data"]["job_type"] == "retrieval_budget_check"
    assert envelope["data"]["error"] == (
        "Performance budget blocked; exceeded limits: max_items"
    )
    assert envelope["data"]["budget_summary"]["status"] == "blocked"
    assert envelope["data"]["budget_summary"]["timing_summary"]["duration_ms"] == 0.0


def test_degraded_job_status_payload_records_specific_budget_error() -> None:
    policy = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="captions",
                max_items=1,
                on_exceed="degrade",
            )
        ]
    )
    decision = policy.check(OperationUsage(operation="captions", item_count=2))
    payload = policy.to_job_status_payload(
        job_id="job_perf_002",
        decision=decision,
    )

    assert decision.status == "degraded"
    assert decision.artifact_status() == "blocked"
    assert payload["status"] == "degraded"
    assert payload["error"] == "Performance budget degraded; exceeded limits: max_items"


def test_job_status_dashboard_projection_includes_budget_summary() -> None:
    contract = ArtifactTypeRegistry().get("job_status")

    assert "budget_summary" in contract.dashboard_projection
