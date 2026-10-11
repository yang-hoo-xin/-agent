"""Shared budget representation; reservation and execution remain with their existing owners."""
from copy import deepcopy

STAGE_AND_TOTAL = "stage_and_total"
TASK_TOTAL_ONLY = "task_total_only"


def total_only(budget):
    return budget.get("policy", STAGE_AND_TOTAL) == TASK_TOTAL_ONLY


def validate_budget(value):
    budget = deepcopy(value)
    if (not isinstance(budget, dict) or not isinstance(budget.get("by_stage"), dict)
            or budget.get("policy", STAGE_AND_TOTAL) not in {STAGE_AND_TOTAL, TASK_TOTAL_ONLY}
            or budget.get("count_basis") != "reserved_provider_invocations_not_transport_proof"):
        raise ValueError("PRODUCT_MODEL_CALL_BUDGET_INVALID")
    limited = [budget] if total_only(budget) else [budget, *budget["by_stage"].values()]
    for row in limited:
        if (not isinstance(row, dict)
                or any(type(row.get(key)) is not int or row[key] < 0 for key in ("maximum", "consumed", "remaining"))
                or row["remaining"] != row["maximum"] - row["consumed"]):
            raise ValueError("PRODUCT_MODEL_CALL_BUDGET_INVALID")
    if (any(not isinstance(row, dict) or type(row.get("consumed")) is not int or row["consumed"] < 0
            for row in budget["by_stage"].values())
            or sum(row["consumed"] for row in budget["by_stage"].values()) != budget["consumed"]):
        raise ValueError("PRODUCT_MODEL_CALL_BUDGET_INVALID")
    return budget


def as_task_total_only(value):
    budget = validate_budget(value)
    budget["policy"] = TASK_TOTAL_ONLY
    # Stage counters have no fictional capacity; old bounded snapshots stay untouched.
    # 为什么要有它：取消阶段硬配额不能靠放大阶段数字，且历史已耗必须原样继承。
    budget["by_stage"] = {role: {"consumed": row["consumed"]} for role, row in budget["by_stage"].items()}
    return budget


def call_allowance(budget, role, local_limit=None):
    """Bound a worker by task capacity; legacy callers retain their original limits."""
    if role not in budget["by_stage"]:
        return 0
    if total_only(budget):
        return budget["remaining"]
    available = min(budget["remaining"], budget["by_stage"][role]["remaining"])
    return available if local_limit is None else min(available, local_limit)
