"""Deterministic acceptance and diagnosis mapping for the Stagger slice."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


STAGGER_VISUAL_ACCEPTANCE_CRITERION = (
    "With General.Enabled=true, a locally owned player's weapon hit that "
    "actually produces the selected enemy reaction shows one additional "
    "short-lived yellow X at that hit position."
)

_SKIPPED_SIGNAL = "signal=STAGGER_FEEDBACK_SKIPPED"
_VISUAL_NOT_SPAWNED = "visual_spawned=False"
_VISUAL_FAILURE_REASON = "visual_reason=missing_canvas_rect_for_stagger_x"
_RUNTIME_SYMBOL = (
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "TrySpawnStaggerYellowX"
)


def evaluate_stagger_acceptance(
    attempts_by_mode: Mapping[str, Mapping[str, Any]],
    *,
    expected_modes: tuple[str, ...],
    acceptance_criteria: tuple[str, ...],
) -> dict[str, Any]:
    """Keep attempt completion, overall acceptance, and criterion facts separate."""

    criterion_results = {
        criterion: {
            "acceptance_criterion": criterion,
            "outcome": "not_observed",
            "evidence_strength": "none",
            "evidence_refs": [],
        }
        for criterion in acceptance_criteria
    }
    for attempt in attempts_by_mode.values():
        _apply_operator_observations(criterion_results, attempt)
        _apply_supported_acceptance(criterion_results, attempt)

    enabled_attempt = attempts_by_mode.get("general_enabled_true")
    machine_fact = (
        None
        if not isinstance(enabled_attempt, Mapping)
        else _confirmed_visual_machine_fact(enabled_attempt)
    )
    if (
        machine_fact is not None
        and STAGGER_VISUAL_ACCEPTANCE_CRITERION in criterion_results
    ):
        visual_result = criterion_results[STAGGER_VISUAL_ACCEPTANCE_CRITERION]
        visual_result["outcome"] = "false"
        visual_result["evidence_strength"] = "confirmed"
        visual_result["evidence_refs"] = _unique_evidence_refs(
            [
                *visual_result["evidence_refs"],
                *machine_fact["evidence_refs"],
            ]
        )

    modes_complete = all(mode in attempts_by_mode for mode in expected_modes)
    criteria_complete = all(
        result["outcome"] != "not_observed"
        for result in criterion_results.values()
    )
    attempt_completion = (
        "complete" if modes_complete and criteria_complete else "incomplete"
    )
    outcomes = {result["outcome"] for result in criterion_results.values()}
    if "false" in outcomes:
        overall_acceptance = "failed"
    elif attempt_completion == "complete" and outcomes == {"true"}:
        overall_acceptance = "accepted"
    else:
        overall_acceptance = "inconclusive"
    return {
        "schema_version": "stagger_acceptance_evaluation_v1",
        "attempt_completion": attempt_completion,
        "overall_acceptance": overall_acceptance,
        "criteria": list(criterion_results.values()),
        "machine_visual_failure": machine_fact,
    }


def build_stagger_runtime_failure_diagnosis(
    *,
    feature_id: str,
    acceptance_evaluation: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return responsibility anchors for the confirmed Stagger failure point."""

    machine_fact = acceptance_evaluation.get("machine_visual_failure")
    visual_result = _criterion_result(
        acceptance_evaluation,
        STAGGER_VISUAL_ACCEPTANCE_CRITERION,
    )
    if (
        acceptance_evaluation.get("overall_acceptance") != "failed"
        or visual_result is None
        or visual_result.get("outcome") != "false"
        or not isinstance(machine_fact, Mapping)
    ):
        return None
    return {
        "schema_version": "stagger_runtime_failure_diagnosis_v1",
        "status": "diagnosed",
        "feature_id": feature_id,
        "failure_class": "product_behavior",
        "evidence_refs": [
            dict(item)
            for item in visual_result.get("evidence_refs", ())
            if isinstance(item, Mapping)
        ],
        "confirmed_failure_point": {
            "component": "ui_attachment",
            "symbol": _RUNTIME_SYMBOL,
            "dependency": "HUD RectTransform",
            "dependency_expression": "_lastHudParent as RectTransform",
            "mechanism": "dependency_unavailable_early_return",
            "event": "missing_canvas_rect_for_stagger_x",
        },
        "responsibility_anchors": {
            "component": "ui_attachment",
            "symbol": _RUNTIME_SYMBOL,
            "dependency": "HUD RectTransform",
            "dependency_expression": "_lastHudParent as RectTransform",
            "repair_scope": [
                "hud_root_acquisition",
                "canvas_binding",
            ],
            "source_hash": None,
            "source_span": None,
        },
        "root_cause_status": "unresolved",
        "unresolved_root_causes": [
            "hud_parent_never_initialized",
            "hud_parent_initialization_timing",
            "hud_parent_cache_stale",
            "hud_parent_runtime_type_mismatch",
            "hud_node_selection_incorrect",
        ],
        "excluded_repair_scopes": [
            "hit_reaction_hook",
            "audio_pipeline",
        ],
        "limitations": [
            (
                "The current evidence confirms the failure point and early-return "
                "mechanism, but does not distinguish among the recorded unresolved "
                "root causes."
            ),
            (
                "The Runtime evidence does not bind the diagnosed method to a "
                "current source hash and span; Binding resolution must block "
                "unless current evidence supplies both."
            ),
        ],
    }


def _apply_operator_observations(
    criterion_results: dict[str, dict[str, Any]],
    attempt: Mapping[str, Any],
) -> None:
    completion = attempt.get("operator_completion")
    if not isinstance(completion, Mapping):
        return
    consistency = completion.get("semantic_consistency")
    if (
        not isinstance(consistency, Mapping)
        or consistency.get("status") != "consistent"
    ):
        return
    observations = completion.get("observations")
    if not isinstance(observations, list):
        return
    for observation in observations:
        if not isinstance(observation, Mapping):
            continue
        criterion = observation.get("acceptance_criterion")
        if not isinstance(criterion, str) or criterion not in criterion_results:
            continue
        if observation.get("semantic_consistency") != "consistent":
            continue
        outcome = {
            "passed": "true",
            "failed": "false",
            "not_observed": "not_observed",
        }.get(observation.get("status"))
        if outcome is None:
            continue
        result = criterion_results[criterion]
        result["outcome"] = outcome
        result["evidence_strength"] = (
            "direct_observation" if outcome != "not_observed" else "none"
        )
        result["evidence_refs"] = [
            {
                "source": "gtfo_operator_completion",
                "locator": completion.get("request_sha256"),
                "criterion_sha256": observation.get("criterion_sha256"),
            }
        ]


def _apply_supported_acceptance(
    criterion_results: dict[str, dict[str, Any]],
    attempt: Mapping[str, Any],
) -> None:
    for item in attempt.get("evidence_items", ()):
        if not isinstance(item, Mapping):
            continue
        for criterion in item.get("supports_acceptance", ()):
            if criterion not in criterion_results:
                continue
            result = criterion_results[str(criterion)]
            if result["outcome"] == "false":
                continue
            result["outcome"] = "true"
            result["evidence_strength"] = "bound_observation"
            result["evidence_refs"] = _unique_evidence_refs(
                [
                    *result["evidence_refs"],
                    {
                        "source": item.get("source"),
                        "locator": item.get("locator"),
                    },
                ]
            )


def _confirmed_visual_machine_fact(
    enabled_attempt: Mapping[str, Any],
) -> dict[str, Any] | None:
    raw_output = enabled_attempt.get("raw_supplied_output")
    if not isinstance(raw_output, str):
        return None
    trust = enabled_attempt.get("runtime_trust_binding")
    checks = trust.get("checks") if isinstance(trust, Mapping) else None
    required_trust_checks = (
        "feature_id",
        "runtime_process_identity",
        "current_run_logs",
        "plugin_load_marker",
        "deployed_plugin_artifact_hash",
        "runtime_config_identity",
    )
    if (
        not isinstance(checks, Mapping)
        or any(
            not isinstance(checks.get(check_name), Mapping)
            or checks[check_name].get("status") != "passed"
            for check_name in required_trust_checks
        )
    ):
        return None
    log_refs = [
        {
            "source": item.get("source"),
            "locator": item.get("locator"),
        }
        for item in enabled_attempt.get("evidence_items", ())
        if isinstance(item, Mapping)
        and item.get("source") == "gtfo_persistent_log"
        and isinstance(item.get("locator"), str)
        and item.get("locator")
    ]
    if not log_refs:
        return None
    required_tokens = (
        _SKIPPED_SIGNAL,
        _VISUAL_NOT_SPAWNED,
        _VISUAL_FAILURE_REASON,
    )
    line = next(
        (
            raw_line.strip()
            for raw_line in raw_output.splitlines()
            if raw_line.strip()
            and all(token in raw_line for token in required_tokens)
        ),
        None,
    )
    if line is None:
        return None
    return {
        "event": "missing_canvas_rect_for_stagger_x",
        "evidence_strength": "deterministic_current_run_marker",
        "raw_excerpt": line,
        "evidence_refs": log_refs,
    }


def _criterion_result(
    acceptance_evaluation: Mapping[str, Any],
    criterion: str,
) -> Mapping[str, Any] | None:
    matches = [
        item
        for item in acceptance_evaluation.get("criteria", ())
        if isinstance(item, Mapping)
        and item.get("acceptance_criterion") == criterion
    ]
    return matches[0] if len(matches) == 1 else None


def _unique_evidence_refs(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
