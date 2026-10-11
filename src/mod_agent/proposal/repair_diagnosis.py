"""Pure construction of a read-only diagnosis turn for an observed failed candidate."""
from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from src.libs.llm.agent_turn import AgentMessage, AgentTurnRequest


_DIAGNOSIS_INSTRUCTIONS = (
    "Diagnose the current checked candidate against the original task and all supplied observations. "
    "Return a concise diagnosis, not a Patch, replacement code, or tool calls. Original Patch-output "
    "instructions and schemas are context for the later revision, not this turn's output contract. "
    "为什么要有它：本次调用只分析已发生的失败，不生成或执行修改。\n"
    "The previous_response is the current checked candidate; working_code_view in validator_feedback "
    "describes that candidate. Source excerpts in task_contract and Plan-bound source tool observations "
    "are historical baseline B0, not the current candidate. Preserve every original requirement, "
    "constraint, acceptance criterion, and behavior that must remain unchanged. "
    "为什么要有它：区分受测版本和原始基线，避免把旧实现当作当前失败代码。\n"
    "Explain observations using the supplied candidate and evidence; identify uncertainty or missing "
    "information without inventing facts. Your analysis is an unverified hypothesis, not new evidence, "
    "an acceptance decision, or permission to change source, tests, scope, or approvals. "
    "为什么要有它：模型诊断不能代替实际验证，也不能授予新的修改权限。"
)

# These are machine-generated history, replaced by the explicitly supplied current feedback.
# 为什么要有它：当前诊断不需要重复旧候选的错误与猜测，但未知用户上下文必须保留。
_HISTORICAL_CONTROL_MESSAGES = (
    "patch_behavior_correction", "patch_repair_context", "patch_submission_feedback",
    "patch_agent_loop_state", "patch_same_plan_assessment", "patch_replanned_context",
    "patch_failure_diagnosis",
)


def _object(value: object) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def build_repair_diagnosis_request(
    request: AgentTurnRequest, *, previous_response: str, feedback: Mapping[str, Any],
) -> AgentTurnRequest:
    """Preserve supplied facts as data, without invoking or retaining executable tools."""
    contracts = []
    for index, message in enumerate(request.messages):
        value = _object(message.content) if message.role == "user" else None
        if (value is not None and isinstance(value.get("request"), str)
                and isinstance(value.get("edit_binding_contexts"), dict)
                and isinstance(value.get("required_output_schema"), dict)):
            contracts.append((index, value))

    payload: dict[str, Any] = {
        "message_type": "patch_repair_diagnosis",
        "previous_response": previous_response,
        "validator_feedback": deepcopy(dict(feedback)),
    }
    if len(contracts) == 1:
        contract_index, contract = contracts[0]
        payload["task_contract"] = contract
        payload["original_context"] = [
            asdict(message) for index, message in enumerate(request.messages)
            if index != contract_index and (message.role == "system" or (
                message.role == "user" and (_object(message.content) or {}).get("message_type")
                not in _HISTORICAL_CONTROL_MESSAGES))
        ]
    else:
        # Do not infer missing contract fields or choose between ambiguous contracts.
        # 为什么要有它：非标准调用也须保留真实输入，不能靠猜测补出需求或源码身份。
        payload["context_representation"] = "unrecognized_or_ambiguous_original_context"
        payload["original_context"] = [asdict(message) for message in request.messages]

    # Carry observed tool data, not provider state or executable native exchanges.
    # 为什么要有它：无工具诊断仍需要已读材料，但不能重放调用或冒充新的读取。
    payload["observed_tool_results"] = [
        asdict(result) for exchange in request.historical_tool_exchanges for result in exchange.tool_results
    ] + [asdict(result) for result in request.tool_results]
    return AgentTurnRequest(
        messages=(AgentMessage("system", _DIAGNOSIS_INSTRUCTIONS), AgentMessage("user", payload)),
        tools=(), tool_choice="none", parallel_tool_calls=False, response_format=None,
        temperature=request.temperature,
    )
