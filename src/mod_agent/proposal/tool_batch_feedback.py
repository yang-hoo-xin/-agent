"""Reject a whole non-read batch before any tool or upstream dispatch."""
from __future__ import annotations

from dataclasses import dataclass

from src.libs.llm.agent_turn import AgentToolCall, AgentToolResult


@dataclass(frozen=True)
class ToolBatchRejection:
    code: str
    reason: str
    results: tuple[AgentToolResult, ...] = ()


def reject_nonread_batch(
    calls: tuple[AgentToolCall, ...], *, source_tool_name: str,
    upstream_tool_name: str, executed_call_ids: set[str],
) -> ToolBatchRejection | None:
    """Build per-call feedback only when unique IDs can safely correlate it.

    为什么要有它：模型一次返回多个互斥请求是可纠正的协议选择；整批先拒绝才能保证反馈前没有部分读取或路由副作用。
    """
    if len(calls) < 2 or all(call.name == source_tool_name for call in calls):
        return None
    call_ids: set[str] = set()
    for call in calls:
        if type(call.call_id) is not str or not call.call_id:
            return ToolBatchRejection("PATCH_AGENT_TOOL_CALL_ID_INVALID", "A provider tool call id is missing.")
        if call.call_id in call_ids or call.call_id in executed_call_ids:
            return ToolBatchRejection("PATCH_AGENT_TOOL_CALL_ID_REUSED", "Tool results cannot be correlated to reused call IDs.")
        call_ids.add(call.call_id)
    if any(call.name not in {source_tool_name, upstream_tool_name} for call in calls):
        code, reason = "PATCH_AGENT_UNKNOWN_TOOL", "The batch contains an unregistered Patch tool."
    elif all(call.name == upstream_tool_name for call in calls):
        code, reason = "PATCH_AGENT_MULTIPLE_UPSTREAM_REQUESTS", "Only one upstream owner can be requested in a turn."
    else:
        code, reason = "PATCH_AGENT_MIXED_TOOL_BATCH_FORBIDDEN", "Source reads and upstream requests cannot share one batch."
    results = tuple(AgentToolResult(call_id=call.call_id, name=call.name, output={
        "status": "not_executed", "error_code": code, "reason": reason,
        "batch_rejected": True, "tool_execution_performed": False,
        "upstream_request_registered": False,
        "required_action": "Use only currently available tools: request one upstream owner in a separate turn, "
                           "or submit source reads without an upstream request, or finish from existing context.",
    }) for call in calls)
    return ToolBatchRejection(code, reason, results)
