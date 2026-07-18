"""Hidden post-run gates for the local WallCrawler model acceptance."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def evaluate_wallcrawler_local_evidence(
    *,
    evidence_pack: dict[str, Any],
    current_stage: str,
    forbidden_artifacts: list[str],
) -> dict[str, object]:
    """Evaluate capability, convergence, and task semantics after inference."""

    trace = evidence_pack.get("model_action_trace")
    tools = evidence_pack.get("tool_trace_summary")
    conclusions = evidence_pack.get("evidence_conclusions")
    budget = evidence_pack.get("budget_summary")
    provenance = evidence_pack.get("provenance_validation")
    input_audit = evidence_pack.get("input_audit")
    if not all(
        isinstance(value, expected)
        for value, expected in (
            (trace, list),
            (tools, list),
            (conclusions, list),
            (budget, dict),
            (provenance, dict),
            (input_audit, dict),
        )
    ):
        raise ValueError("WALLCRAWLER_ACCEPTANCE_PACK_SHAPE_INVALID")

    accepted_actions = [
        item.get("action")
        for item in trace
        if isinstance(item, dict)
        and item.get("status") == "accepted"
        and isinstance(item.get("action"), dict)
    ]
    tool_actions = [
        action for action in accepted_actions if action.get("action") == "use_tool"
    ]
    finish_actions = [
        action for action in accepted_actions if action.get("action") == "finish"
    ]
    finish = finish_actions[-1] if finish_actions else {}
    tool_names = [str(action.get("tool") or "") for action in tool_actions]
    inspection_observation_ids = {
        str(item.get("observation_id"))
        for item in tools
        if isinstance(item, dict)
        and item.get("tool") == "inspect_method_il"
        and item.get("observation_id")
    }
    grounded_il_conclusions = [
        item
        for item in conclusions
        if isinstance(item, dict)
        and item.get("claim_status") in {"observed", "inferred"}
        and isinstance(item.get("observation_ids"), list)
        and inspection_observation_ids.intersection(item["observation_ids"])
    ]
    signatures = [
        sha256(
            json.dumps(
                {
                    "tool": action.get("tool"),
                    "source_id": action.get("source_id"),
                    "arguments": action.get("arguments"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        for action in tool_actions
    ]
    correction_count = sum(
        1
        for item in trace
        if isinstance(item, dict) and item.get("status") != "accepted"
    )
    inspection_index = next(
        (index for index, name in enumerate(tool_names) if name == "inspect_method_il"),
        None,
    )
    broad_searches_after_il = (
        sum(
            1
            for name in tool_names[inspection_index + 1 :]
            if name == "search_dotnet_metadata"
        )
        if inspection_index is not None
        else 0
    )
    expected_input_audit_fields = {
        "manual_symbol_count",
        "manual_tool_sequence_count",
        "precomputed_report_count",
        "operator_intervention_count",
    }
    input_is_clean = set(input_audit) == expected_input_audit_fields and all(
        isinstance(value, int) and not isinstance(value, bool) and value == 0
        for value in input_audit.values()
    )
    capability_checks = {
        "completed": evidence_pack.get("run_status") == "completed",
        "within_model_budget": _bounded_int(budget.get("model_steps_used"), 1, 8),
        "within_tool_budget": _bounded_int(budget.get("tool_calls_used"), 1, 6),
        "metadata_then_il": _contains_ordered_pair(
            tool_names, "search_dotnet_metadata", "inspect_method_il"
        ),
        "prior_observation_method_binding": (
            provenance.get("all_method_inspections_derived_from_observations") is True
        ),
        "grounded_il_conclusion": bool(grounded_il_conclusions),
        "input_pollution_absent": input_is_clean,
        "no_identical_tool_repeat": len(signatures) == len(set(signatures)),
        "evidence_only_stop": current_stage == "evidence_retrieval"
        and not forbidden_artifacts,
    }
    convergence_checks = {
        "three_model_turns": budget.get("model_steps_used") == 3,
        "two_tool_calls": budget.get("tool_calls_used") == 2,
        "exact_tool_sequence": tool_names
        == ["search_dotnet_metadata", "inspect_method_il"],
        "zero_corrections": correction_count == 0,
        "zero_broad_searches_after_il": broad_searches_after_il == 0,
        "no_identical_tool_repeat": len(signatures) == len(set(signatures)),
    }

    il_items = [
        item
        for item in evidence_pack.get("items", [])
        if isinstance(item, dict)
        and item.get("retrieval_method") == "agent_selected_cli_metadata_il_read"
        and isinstance(item.get("symbol"), str)
        and item.get("symbol")
    ]
    grounded_claim_text = "\n".join(
        str(item.get("claim") or "") for item in grounded_il_conclusions
    )
    unresolved_text = "\n".join(
        str(value)
        for value in (
            list(evidence_pack.get("unresolved_questions") or [])
            + [
                limitation
                for item in conclusions
                if isinstance(item, dict)
                for limitation in (item.get("limitations") or [])
            ]
        )
    ).casefold()
    semantic_checks = {
        "grounded_claim_names_inspected_symbol": any(
            str(item["symbol"]) in grounded_claim_text for item in il_items
        ),
        "persistent_identity_binding_left_unresolved": any(
            term in unresolved_text
            for term in ("persistentid", "identity", "身份", "数据库绑定")
        ),
        "proposal_not_unlocked": finish.get("decision") == "needs_more_evidence"
        and evidence_pack.get("can_generate_patch") is False,
    }
    return {
        "evaluator_visibility": "post_run_hidden_from_model",
        "capability_gate": {
            "passed": all(capability_checks.values()),
            "checks": capability_checks,
        },
        "convergence_gate": {
            "passed": all(convergence_checks.values()),
            "checks": convergence_checks,
            "correction_count": correction_count,
            "broad_searches_after_il": broad_searches_after_il,
        },
        "semantic_gate": {
            "passed": all(semantic_checks.values()),
            "checks": semantic_checks,
        },
    }


def _bounded_int(value: object, lower: int, upper: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and lower <= value <= upper
    )


def _contains_ordered_pair(values: list[str], first: str, second: str) -> bool:
    try:
        first_index = values.index(first)
        second_index = values.index(second, first_index + 1)
    except ValueError:
        return False
    return first_index < second_index
