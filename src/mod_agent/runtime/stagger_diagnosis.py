"""Deterministic acceptance and diagnosis mapping for the Stagger slice."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
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
STAGGER_DUPLICATE_RESULT_ACCEPTANCE_CRITERION = (
    "The same accepted hit produces no more than one yellow X, one "
    "feature-attributable cue, and one STAGGER_FEEDBACK_SHOWN signal even "
    "if an implementation-side result event is observed more than once."
)

_CRITERION_STATUSES = {
    "passed",
    "failed",
    "inconclusive",
    "not_evaluated",
}
_IMPACT_STATUSES = {
    "unaffected",
    "needs_regression",
    "invalidated",
    "unknown",
}


def build_stagger_repair_attempt_projection(
    *,
    feature_id: str,
    run_id: str,
    repair_plan: Mapping[str, Any],
    repair_plan_ref: Mapping[str, str],
    root_cause_evidence: Mapping[str, Any],
    root_cause_evidence_ref: Mapping[str, str],
    isolated_apply_result_ref: Mapping[str, str],
    build_result_ref: Mapping[str, str],
    acceptance_criteria: tuple[str, ...],
    marker_criteria: frozenset[str],
    source_hash_before: str,
    source_sha256: str,
    source_snapshot_sha256: str,
    dll_sha256: str,
    diff_hash: str,
) -> dict[str, Any]:
    """Project the current Stagger repair ledger without writing an Artifact."""

    if not feature_id or not run_id:
        raise ValueError("Stagger RepairAttempt requires Feature and Run identities.")
    if not acceptance_criteria or len(set(acceptance_criteria)) != len(
        acceptance_criteria
    ):
        raise ValueError("Stagger RepairAttempt criteria must be non-empty and unique.")
    if not marker_criteria.issubset(set(acceptance_criteria)):
        raise ValueError("Stagger marker criteria are outside the FeatureSpec.")
    if repair_plan.get("feature_id") != feature_id:
        raise ValueError("RepairPlan feature identity does not match.")
    if root_cause_evidence.get("feature_id") != feature_id:
        raise ValueError("RootCauseEvidence feature identity does not match.")
    semantic_decision = repair_plan.get("semantic_decision")
    if not isinstance(semantic_decision, Mapping):
        raise ValueError("RepairPlan semantic decision is missing.")
    hypothesis_id = semantic_decision.get("selected_hypothesis_id")
    if not isinstance(hypothesis_id, str) or not hypothesis_id:
        raise ValueError("RepairPlan selected hypothesis identity is missing.")
    failed_criterion = root_cause_evidence.get("failed_feature_spec_criterion")
    if failed_criterion not in acceptance_criteria:
        raise ValueError(
            "RootCauseEvidence failed criterion is outside the FeatureSpec."
        )
    failure_owner = root_cause_evidence.get("failure_owner")
    if not isinstance(failure_owner, str) or not failure_owner:
        raise ValueError("RootCauseEvidence failure owner is missing.")
    repair_id = repair_plan.get("repair_id")
    if not isinstance(repair_id, str) or not repair_id:
        raise ValueError("RepairPlan repair identity is missing.")
    retry_count = repair_plan.get("retry_count")
    retry_budget = repair_plan.get("retry_budget")
    if (
        isinstance(retry_count, bool)
        or not isinstance(retry_count, int)
        or retry_count < 0
        or isinstance(retry_budget, bool)
        or not isinstance(retry_budget, int)
        or retry_budget < 0
    ):
        raise ValueError("RepairPlan retry accounting is invalid.")
    for name, value in (
        ("source_hash_before", source_hash_before),
        ("source_sha256", source_sha256),
        ("source_snapshot_sha256", source_snapshot_sha256),
        ("dll_sha256", dll_sha256),
    ):
        _require_sha256_hex(name, value)
    _require_prefixed_sha256("diff_hash", diff_hash)
    refs = {
        "repair_plan": _normalized_identity_ref("repair_plan_ref", repair_plan_ref),
        "root_cause_evidence": _normalized_identity_ref(
            "root_cause_evidence_ref",
            root_cause_evidence_ref,
        ),
        "isolated_apply_result": _normalized_identity_ref(
            "isolated_apply_result_ref",
            isolated_apply_result_ref,
        ),
        "build_result": _normalized_identity_ref(
            "build_result_ref",
            build_result_ref,
        ),
    }
    attempt_seed = json.dumps(
        {
            "feature_id": feature_id,
            "run_id": run_id,
            "repair_plan_hash": refs["repair_plan"]["artifact_hash"],
            "isolated_apply_result_hash": refs["isolated_apply_result"][
                "artifact_hash"
            ],
            "build_result_hash": refs["build_result"]["artifact_hash"],
            "source_sha256": source_sha256,
            "dll_sha256": dll_sha256,
            "diff_hash": diff_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    attempt_id = "repair_attempt_" + hashlib.sha256(
        attempt_seed.encode("utf-8")
    ).hexdigest()[:16]
    criterion_results = [
        {
            "schema_version": "criterion_result_v1",
            "criterion_id": _criterion_id(criterion),
            "acceptance_criterion": criterion,
            "criterion_status": "not_evaluated",
            "source_sha256": source_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "dll_sha256": dll_sha256,
            "runtime_attempt_id": None,
            "evidence_refs": [],
            "impact_status": (
                "invalidated"
                if criterion == failed_criterion
                else "needs_regression"
            ),
            "operator_required": criterion not in marker_criteria,
            "prior_result_inherited": False,
        }
        for criterion in acceptance_criteria
    ]
    return {
        "schema_version": "stagger_repair_attempt_projection_v1",
        "repair_attempt": {
            "schema_version": "stagger_repair_attempt_v1",
            "attempt_id": attempt_id,
            "feature_id": feature_id,
            "run_id": run_id,
            "repair_id": repair_id,
            "hypothesis_id": hypothesis_id,
            "source_hash_before": source_hash_before,
            "source_sha256": source_sha256,
            "source_snapshot_sha256": source_snapshot_sha256,
            "dll_sha256": dll_sha256,
            "diff_hash": diff_hash,
            "build_status": "passed",
            "runtime_status": "not_started",
            "criteria": [item["criterion_id"] for item in criterion_results],
            "failure_owner": failure_owner,
            "retry_budget": retry_budget,
            "retry_count": retry_count,
            "human_intervention_count": None,
            "additional_evidence_rounds": None,
            "final_status": None,
            "identity_refs": refs,
            "measurement_limitations": [
                (
                    "human_intervention_count is null because the existing "
                    "immutable lineage does not define which approval and "
                    "operator events count."
                ),
                (
                    "additional_evidence_rounds is null because the existing "
                    "immutable lineage does not define an evidence-round counter."
                ),
                (
                    "final_status remains null until this DLL receives bound "
                    "Runtime results."
                ),
            ],
        },
        "criterion_results": criterion_results,
    }


def bind_stagger_repair_attempt_runtime_results(
    projection: Mapping[str, Any],
    *,
    acceptance_evaluation: Mapping[str, Any],
    attempt_payloads: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Bind current-run criterion outcomes without inheriting an older DLL result."""

    bound = deepcopy(dict(projection))
    raw_results = acceptance_evaluation.get("criteria")
    if not isinstance(raw_results, list):
        raise ValueError("Stagger acceptance evaluation criteria are missing.")
    evaluated = {
        item.get("acceptance_criterion"): item
        for item in raw_results
        if isinstance(item, Mapping)
        and isinstance(item.get("acceptance_criterion"), str)
    }
    repair_attempt = bound.get("repair_attempt")
    criterion_results = bound.get("criterion_results")
    if not isinstance(repair_attempt, dict):
        raise ValueError("Stagger RepairAttempt is missing.")
    if not isinstance(criterion_results, list):
        raise ValueError("Stagger RepairAttempt CriterionResults are missing.")
    if set(evaluated) != {
        item.get("acceptance_criterion")
        for item in criterion_results
        if isinstance(item, Mapping)
    }:
        raise ValueError("Stagger acceptance evaluation criteria changed.")
    attempts_by_criterion: dict[str, Mapping[str, Any]] = {}
    for attempt in attempt_payloads:
        runtime_attempt_id = attempt.get("runtime_attempt_id")
        acceptance_contract = attempt.get("acceptance_contract")
        criteria = (
            acceptance_contract.get("acceptance_criteria")
            if isinstance(acceptance_contract, Mapping)
            else None
        )
        if not isinstance(runtime_attempt_id, str) or not runtime_attempt_id:
            raise ValueError("Started Stagger Runtime attempt identity is missing.")
        if not isinstance(criteria, list):
            raise ValueError("Started Stagger Runtime attempt criteria are missing.")
        for criterion in criteria:
            if not isinstance(criterion, str) or criterion in attempts_by_criterion:
                raise ValueError("Stagger Runtime criterion ownership is invalid.")
            attempts_by_criterion[criterion] = attempt
    statuses: list[str] = []
    for item in criterion_results:
        if not isinstance(item, dict):
            raise ValueError("Stagger CriterionResult is not structured.")
        criterion = item.get("acceptance_criterion")
        result = evaluated.get(criterion)
        if not isinstance(result, Mapping):
            raise ValueError("Stagger CriterionResult evaluation is missing.")
        outcome = result.get("outcome")
        owner_attempt = attempts_by_criterion.get(str(criterion))
        prior_result = result.get("prior_criterion_result")
        if isinstance(prior_result, Mapping) and outcome == "true":
            if owner_attempt is not None:
                raise ValueError(
                    "Inherited Stagger CriterionResult was selected for rerun."
                )
            for key in (
                "criterion_status",
                "runtime_attempt_id",
                "evidence_refs",
                "impact_status",
                "operator_required",
            ):
                item[key] = deepcopy(prior_result.get(key))
            item["prior_result_inherited"] = True
            item["prior_runtime_evidence_ref"] = next(
                (
                    dict(ref)
                    for ref in result.get("evidence_refs", ())
                    if isinstance(ref, Mapping)
                    and ref.get("source") == "prior_runtime_evidence"
                ),
                None,
            )
            statuses.append(str(item["criterion_status"]))
            continue
        if outcome == "true":
            criterion_status = "passed"
        elif outcome == "false":
            criterion_status = "failed"
        elif outcome == "not_observed" and owner_attempt is None:
            criterion_status = "not_evaluated"
        elif outcome == "not_observed":
            criterion_status = "inconclusive"
        else:
            raise ValueError("Stagger acceptance evaluation outcome is invalid.")
        if criterion_status not in _CRITERION_STATUSES:
            raise ValueError("Stagger CriterionResult status is invalid.")
        if item.get("impact_status") not in _IMPACT_STATUSES:
            raise ValueError("Stagger CriterionResult impact status is invalid.")
        item["criterion_status"] = criterion_status
        result_runtime_attempt_id = result.get("runtime_attempt_id")
        item["runtime_attempt_id"] = (
            str(owner_attempt["runtime_attempt_id"])
            if owner_attempt is not None
            else (
                str(result_runtime_attempt_id)
                if isinstance(result_runtime_attempt_id, str)
                else None
            )
        )
        item["evidence_refs"] = [
            dict(ref)
            for ref in result.get("evidence_refs", ())
            if isinstance(ref, Mapping)
        ]
        item["prior_result_inherited"] = False
        statuses.append(criterion_status)
    overall_acceptance = acceptance_evaluation.get("overall_acceptance")
    if statuses and all(status == "passed" for status in statuses):
        runtime_status = "passed"
        expected_acceptance = "accepted"
    elif "failed" in statuses:
        runtime_status = "failed"
        expected_acceptance = "failed"
    else:
        runtime_status = "blocked"
        expected_acceptance = "inconclusive"
    if overall_acceptance != expected_acceptance:
        raise ValueError(
            "Stagger RepairAttempt status does not match aggregate acceptance."
        )
    repair_attempt["runtime_status"] = runtime_status
    repair_attempt["final_status"] = overall_acceptance
    bound["criterion_results"] = criterion_results
    repair_attempt["runtime_attempt_ids"] = sorted(
        {
            str(attempt["runtime_attempt_id"])
            for attempt in attempt_payloads
        }
        | {
            str(item["runtime_attempt_id"])
            for item in criterion_results
            if isinstance(item, Mapping)
            and item.get("prior_result_inherited") is True
            and isinstance(item.get("runtime_attempt_id"), str)
        }
    )
    bound["repair_attempt"] = repair_attempt
    return bound


def inherit_stagger_repair_attempt_prior_results(
    projection: Mapping[str, Any],
    *,
    prior_criterion_results: tuple[Mapping[str, Any], ...],
    prior_runtime_evidence_ref: Mapping[str, Any],
    retry_number: int,
) -> dict[str, Any]:
    """Project same-DLL passed results before a partial observation retry."""

    if isinstance(retry_number, bool) or not isinstance(retry_number, int):
        raise ValueError("Stagger observation retry number is invalid.")
    path = prior_runtime_evidence_ref.get("path")
    artifact_hash = prior_runtime_evidence_ref.get("artifact_hash")
    if not isinstance(path, str) or not path or not isinstance(artifact_hash, str):
        raise ValueError("Prior RuntimeEvidence identity is incomplete.")
    bound = deepcopy(dict(projection))
    repair_attempt = bound.get("repair_attempt")
    criterion_results = bound.get("criterion_results")
    if not isinstance(repair_attempt, dict) or not isinstance(
        criterion_results, list
    ):
        raise ValueError("Stagger RepairAttempt projection is incomplete.")
    by_criterion = {
        item.get("acceptance_criterion"): item
        for item in criterion_results
        if isinstance(item, dict)
        and isinstance(item.get("acceptance_criterion"), str)
    }
    if len(by_criterion) != len(criterion_results):
        raise ValueError("Stagger CriterionResult ownership is invalid.")
    seen: set[str] = set()
    for prior in prior_criterion_results:
        criterion = prior.get("acceptance_criterion")
        current = by_criterion.get(criterion)
        if (
            not isinstance(criterion, str)
            or criterion in seen
            or not isinstance(current, dict)
            or prior.get("criterion_status") != "passed"
            or prior.get("criterion_id") != current.get("criterion_id")
            or prior.get("source_sha256") != current.get("source_sha256")
            or prior.get("source_snapshot_sha256")
            != current.get("source_snapshot_sha256")
            or prior.get("dll_sha256") != current.get("dll_sha256")
        ):
            raise ValueError(
                "Prior Stagger CriterionResult does not match the current DLL."
            )
        if (
            criterion == STAGGER_DUPLICATE_RESULT_ACCEPTANCE_CRITERION
            and not _has_bound_duplicate_result_event_evidence(
                prior.get("evidence_refs")
            )
        ):
            raise ValueError(
                "Duplicate-result Stagger CriterionResult lacks bound "
                "implementation-event evidence."
            )
        seen.add(criterion)
        for key in (
            "criterion_status",
            "runtime_attempt_id",
            "evidence_refs",
            "impact_status",
            "operator_required",
        ):
            current[key] = deepcopy(prior.get(key))
        current["prior_result_inherited"] = True
        current["prior_runtime_evidence_ref"] = {
            "source": "prior_runtime_evidence",
            "locator": path,
            "artifact_hash": artifact_hash,
        }
    repair_attempt["retry_count"] = retry_number
    repair_attempt["runtime_status"] = "not_started"
    repair_attempt["final_status"] = None
    repair_attempt["runtime_attempt_ids"] = sorted(
        {
            str(item["runtime_attempt_id"])
            for item in criterion_results
            if isinstance(item, Mapping)
            and item.get("prior_result_inherited") is True
            and isinstance(item.get("runtime_attempt_id"), str)
        }
    )
    bound["repair_attempt"] = repair_attempt
    bound["criterion_results"] = criterion_results
    return bound


def build_stagger_observation_retry_criterion_binding(
    runtime_evidence: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    """Select unresolved Stagger criteria from one bound prior result."""

    contract = runtime_evidence.get("acceptance_contract")
    criteria = (
        contract.get("acceptance_criteria")
        if isinstance(contract, Mapping)
        else None
    )
    results = runtime_evidence.get("criterion_results")
    attempt = runtime_evidence.get("repair_attempt")
    if (
        not isinstance(criteria, list)
        or not criteria
        or any(not isinstance(item, str) or not item for item in criteria)
        or len(set(criteria)) != len(criteria)
        or not isinstance(results, list)
        or len(results) != len(criteria)
        or not isinstance(attempt, Mapping)
    ):
        raise ValueError(
            "Runtime observation retry CriterionResult lineage is invalid."
        )
    by_criterion: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError(
                "Runtime observation retry CriterionResult is not structured."
            )
        criterion = result.get("acceptance_criterion")
        if not isinstance(criterion, str) or criterion in by_criterion:
            raise ValueError(
                "Runtime observation retry CriterionResult ownership is invalid."
            )
        by_criterion[criterion] = result
    if set(by_criterion) != set(criteria):
        raise ValueError(
            "Runtime observation retry CriterionResults changed from the "
            "acceptance contract."
        )

    snapshot = checkpoint.get("state_snapshot") or {}
    build_ref = (snapshot.get("artifacts") or {}).get("build_result")
    build_hash = (snapshot.get("artifact_hashes") or {}).get("build_result")
    attempt_build_ref = (attempt.get("identity_refs") or {}).get("build_result")
    expected_source = attempt.get("source_sha256")
    expected_snapshot = attempt.get("source_snapshot_sha256")
    expected_dll = attempt.get("dll_sha256")
    if (
        not isinstance(attempt_build_ref, Mapping)
        or attempt_build_ref.get("path") != build_ref
        or attempt_build_ref.get("artifact_hash") != build_hash
        or not all(
            isinstance(value, str) and value
            for value in (expected_source, expected_snapshot, expected_dll)
        )
    ):
        raise ValueError(
            "Runtime observation retry RepairAttempt identity is invalid."
        )

    inherited: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for criterion in criteria:
        result = by_criterion[criterion]
        if (
            result.get("source_sha256") != expected_source
            or result.get("source_snapshot_sha256") != expected_snapshot
            or result.get("dll_sha256") != expected_dll
        ):
            raise ValueError(
                "Runtime observation retry CriterionResult identity changed."
            )
        status = result.get("criterion_status")
        if (
            status == "passed"
            and criterion == STAGGER_DUPLICATE_RESULT_ACCEPTANCE_CRITERION
            and not _has_bound_duplicate_result_event_evidence(
                result.get("evidence_refs")
            )
        ):
            unresolved.append(criterion)
        elif status == "passed":
            inherited.append(dict(result))
        elif status in {"inconclusive", "not_evaluated"}:
            unresolved.append(criterion)
        else:
            raise ValueError(
                "Runtime observation retry cannot inherit a failed or unknown "
                "CriterionResult."
            )
    if not unresolved:
        raise ValueError(
            "Runtime observation retry has no unresolved CriterionResult."
        )
    retry_modes = []
    if any("General.Enabled=false" in item for item in unresolved):
        retry_modes.append("general_enabled_false")
    if any("General.Enabled=false" not in item for item in unresolved):
        retry_modes.append("general_enabled_true")
    return {
        "retry_acceptance_criteria": unresolved,
        "inherited_criterion_results": inherited,
        "retry_modes": retry_modes,
    }


def _criterion_id(criterion: str) -> str:
    return "sha256:" + hashlib.sha256(criterion.encode("utf-8")).hexdigest()


def _normalized_identity_ref(
    name: str,
    value: Mapping[str, str],
) -> dict[str, str]:
    path = value.get("path")
    artifact_hash = value.get("artifact_hash")
    if not isinstance(path, str) or not path:
        raise ValueError(f"{name} path is missing.")
    if not isinstance(artifact_hash, str):
        raise ValueError(f"{name} Artifact hash is missing.")
    _require_sha256_hex(f"{name}.artifact_hash", artifact_hash)
    return {"path": path, "artifact_hash": artifact_hash}


def _require_sha256_hex(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in value)
    ):
        raise ValueError(f"{name} must be one SHA256 hex digest.")


def _require_prefixed_sha256(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(f"{name} must use the sha256: prefix.")
    _require_sha256_hex(name, value.removeprefix("sha256:"))


def evaluate_stagger_acceptance(
    attempts_by_mode: Mapping[str, Mapping[str, Any]],
    *,
    expected_modes: tuple[str, ...],
    acceptance_criteria: tuple[str, ...],
    prior_criterion_results: tuple[Mapping[str, Any], ...] = (),
    prior_runtime_evidence_ref: Mapping[str, Any] | None = None,
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
    if prior_criterion_results:
        if (
            not isinstance(prior_runtime_evidence_ref, Mapping)
            or not isinstance(prior_runtime_evidence_ref.get("path"), str)
            or not isinstance(
                prior_runtime_evidence_ref.get("artifact_hash"), str
            )
        ):
            raise ValueError(
                "Inherited Stagger criteria require one prior RuntimeEvidence ref."
            )
        for prior in prior_criterion_results:
            criterion = prior.get("acceptance_criterion")
            if (
                criterion not in criterion_results
                or prior.get("criterion_status") != "passed"
            ):
                raise ValueError(
                    "Only exact passed Stagger CriterionResults may be inherited."
                )
            result = criterion_results[str(criterion)]
            result["outcome"] = "true"
            result["evidence_strength"] = "inherited_bound_result"
            result["evidence_refs"] = [
                *[
                    dict(item)
                    for item in prior.get("evidence_refs", ())
                    if isinstance(item, Mapping)
                ],
                {
                    "source": "prior_runtime_evidence",
                    "locator": prior_runtime_evidence_ref["path"],
                    "artifact_hash": prior_runtime_evidence_ref[
                        "artifact_hash"
                    ],
                },
            ]
            result["prior_result_inherited"] = True
            result["prior_criterion_result"] = dict(prior)
    for attempt in attempts_by_mode.values():
        _apply_operator_observations(criterion_results, attempt)
        _apply_supported_acceptance(criterion_results, attempt)

    duplicate_result = criterion_results.get(
        STAGGER_DUPLICATE_RESULT_ACCEPTANCE_CRITERION
    )
    if (
        isinstance(duplicate_result, dict)
        and duplicate_result.get("outcome") == "true"
        and not _has_bound_duplicate_result_event_evidence(
            duplicate_result.get("evidence_refs")
        )
    ):
        duplicate_result["outcome"] = "not_observed"
        duplicate_result["evidence_strength"] = (
            "insufficient_duplicate_result_event_evidence"
        )
        duplicate_result.pop("prior_criterion_result", None)
        duplicate_result["prior_result_inherited"] = False

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
        if "prior_criterion_result" in visual_result:
            visual_result.pop("prior_criterion_result")
            visual_result["prior_result_inherited"] = False
            if isinstance(enabled_attempt.get("runtime_attempt_id"), str):
                visual_result["runtime_attempt_id"] = enabled_attempt[
                    "runtime_attempt_id"
                ]
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


def _has_bound_duplicate_result_event_evidence(
    evidence_refs: Any,
) -> bool:
    if not isinstance(evidence_refs, (list, tuple)):
        return False
    return any(
        isinstance(item, Mapping)
        and isinstance(item.get("source"), str)
        and item.get("source")
        not in {"gtfo_operator_completion", "prior_runtime_evidence"}
        for item in evidence_refs
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
