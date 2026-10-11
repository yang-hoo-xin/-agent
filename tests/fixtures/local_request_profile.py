"""Explicit inputs shared by normal-entry tests using controlled model responses."""


def request_budget() -> dict[str, int | str]:
    """Return fresh task-wide budget inputs for tests of other entry contracts.

    为什么要有它：预算应在调用处显式提供，让其他入口验收到达被测行为，
    同时保留缺预算和非法预算用例对真实生产校验的覆盖。
    """
    return {
        "task_model_call_limit": 12,
        "model_call_budget_policy": "task_total_only",
    }


def request_budget_args() -> list[str]:
    """Return the same explicit test budget through the public CLI interface."""
    budget = request_budget()
    return [
        "--task-model-call-limit", str(budget["task_model_call_limit"]),
        "--model-call-budget-policy", str(budget["model_call_budget_policy"]),
    ]
