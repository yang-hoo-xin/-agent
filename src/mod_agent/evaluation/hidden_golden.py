"""Expected-side comparison for the two Hook Discovery calibration fixtures.

This module is deliberately not a discovery runner.  It consumes a manifest-bound
actual identity only after Evidence-side execution, Store commit, and strict semantic
rehydration, then reads the frozen technical annotation for comparison.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.evidence.calibration import (
    HiddenGoldenActualInput,
    HiddenGoldenCalibrationError,
)
from src.mod_agent.evidence.discovery_loop import (
    discovery_plan_budget_feasibility,
)
from src.mod_agent.evidence.models import EvidencePack

HIDDEN_GOLDEN_CALIBRATION_EVAL_VERSION = "hidden_golden_calibration_eval_v3"
STRUCTURED_RELATION_RUBRIC_VERSION = "hidden_golden_relation_rubric_v1"
_TECHNICAL_REVIEW_AUTHORITY = (
    "independently_model_reviewed_technical_calibration_annotation"
)
_JUDGMENT_FIELDS = (
    "required_evidence",
    "forbidden_evidence",
    "acceptable_hook_full_identities",
    "forbidden_hook_full_identities",
    "required_missing_evidence",
    "expected_sufficiency",
    "expected_control_action",
)
_JUDGMENT_FIELDS_WITH_RELATIONS = (
    *_JUDGMENT_FIELDS,
    "structured_relation_rubric",
)
_RELATIONSHIP_VALUES = {"support", "conflict", "missing"}
_FULL_IDENTITY_FIELDS = (
    "assembly_sha256",
    "module_mvid",
    "declaring_type",
    "method_name",
    "metadata_token",
    "signature_blob",
)


def evaluate_committed_hidden_golden(
    *,
    store: ArtifactStore,
    actual_ref: ArtifactRef,
    actual_input: HiddenGoldenActualInput,
    annotation_path: str | Path,
) -> dict[str, Any]:
    """Compare one committed actual pack after strict rehydration.

    Reading the annotation occurs after Store read, Registry validation, strict
    semantic rehydration, and request binding.  The returned comparison grants no
    Data Readiness, product quality, promotion, or execution verdict.
    """

    if actual_ref.artifact_type != "evidence_pack":
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_REF_TYPE_INVALID")
    if actual_input.observed_corpus_snapshot_sha256 is None:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_CORPUS_SNAPSHOT_NOT_OBSERVED"
        )
    envelope = store.read(actual_ref)
    payload = envelope.get("data")
    if not isinstance(payload, dict):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_PAYLOAD_INVALID")
    if not EvidencePack.requires_strict_semantic_rehydrate(payload):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_NOT_SEMANTIC")
    try:
        pack = EvidencePack.from_artifact_payload(payload)
    except ValueError as exc:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_REHYDRATE_FAILED") from exc
    if pack.query != actual_input.request_text:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_REQUEST_MISMATCH")
    _validate_actual_manifest_binding(pack, actual_input)
    actual_payload_sha256 = _canonical_sha256(payload)

    # Expected truth becomes visible only after actual is immutable and rebound.
    annotation = _load_object(Path(annotation_path))
    expected = _validated_expected(annotation, actual_input.case_identity)
    actual_sufficiency, actual_action = _actual_decision(pack)
    actual_identities = _actual_hook_identities(pack)
    acceptable_identities = _expected_identities(
        expected, "acceptable_hook_full_identities", "acceptance_scope"
    )
    forbidden_identities = _expected_identities(
        expected, "forbidden_hook_full_identities", "forbidden_scope"
    )
    actual_keys = {_identity_key(value) for value in actual_identities}
    acceptable_keys = {_identity_key(value) for value in acceptable_identities}
    forbidden_hits = sorted(actual_keys & {_identity_key(value) for value in forbidden_identities})
    comparison = {
        "sufficiency_matches": actual_sufficiency
        == expected["expected_sufficiency"],
        "control_action_matches": actual_action
        == expected["expected_control_action"],
        "acceptable_hook_identity_set_matches": actual_keys == acceptable_keys,
        "forbidden_hook_identity_hits": [list(value) for value in forbidden_hits],
    }
    reliability = _calibration_reliability_gate(
        pack=pack,
        expected=expected,
        generic_comparison=comparison,
    )

    return {
        "protocol_version": HIDDEN_GOLDEN_CALIBRATION_EVAL_VERSION,
        "protocol_role": "expected_truth_isolation_after_committed_actual",
        "case_identity": actual_input.case_identity,
        "calibration_scope": "calibration_development",
        "blind_or_held_out_claim": False,
        "promotion_claim": False,
        "actual": {
            "artifact_hash": actual_ref.artifact_hash,
            "payload_sha256": actual_payload_sha256,
            "request_sha256": actual_input.request_sha256,
            "corpus_snapshot_sha256": actual_input.observed_corpus_snapshot_sha256,
            "sufficiency": actual_sufficiency,
            "control_action": actual_action,
            "hook_full_identities": actual_identities,
        },
        "expected": {
            "frozen_judgment_hash": annotation["frozen_judgment_hash"],
            "technical_review_authority": annotation["technical_review_authority"],
            "sufficiency": expected["expected_sufficiency"],
            "control_action": expected["expected_control_action"],
            "acceptable_hook_full_identities": acceptable_identities,
            "forbidden_hook_full_identities": forbidden_identities,
        },
        "comparison": comparison,
        "reliability": reliability,
        "unscored_expected_fields": [
            "required_evidence",
            "forbidden_evidence",
            "required_missing_evidence",
        ],
        "limitations": [
            "Narrative evidence requirements are not scored without registered actual relationship identities.",
            "This comparison does not re-run discovery or derive expected judgment from physical evidence.",
        ],
        "does_not_grant": [
            "golden_completion_verdict",
            "data_readiness_verdict",
            "product_quality_verdict",
            "promotion",
            "patch_apply_build_or_runtime_authority",
        ],
    }


def _calibration_reliability_gate(
    *,
    pack: EvidencePack,
    expected: Mapping[str, Any],
    generic_comparison: Mapping[str, Any],
) -> dict[str, Any]:
    """Separate actual evaluability from the generic expected comparison."""

    reason_codes: list[str] = []
    agent_discovery = pack.agent_discovery
    search_plan = (
        agent_discovery.get("search_plan")
        if isinstance(agent_discovery, dict)
        else None
    )
    planned_lanes = (
        search_plan.get("planned_lanes")
        if isinstance(search_plan, dict)
        else None
    )
    if not isinstance(planned_lanes, list):
        planned_lanes = []
        reason_codes.append("ACTUAL_SEARCH_PLAN_MISSING")

    hook_discovery = pack.hook_discovery
    lane_coverage = (
        hook_discovery.get("lane_coverage")
        if isinstance(hook_discovery, dict)
        else None
    )
    if not isinstance(lane_coverage, list):
        lane_coverage = []
        reason_codes.append("ACTUAL_LANE_COVERAGE_MISSING")
    disposition_by_lane = {
        str(row.get("lane")): str(row.get("status"))
        for row in lane_coverage
        if isinstance(row, dict) and row.get("lane")
    }
    disposed_statuses = {"searched_with_results", "searched_and_absent"}
    planned_lane_ids = [
        str(row.get("lane"))
        for row in planned_lanes
        if isinstance(row, dict) and row.get("lane")
    ]
    undisposed_lanes = [
        lane
        for lane in planned_lane_ids
        if disposition_by_lane.get(lane) not in disposed_statuses
    ]
    if undisposed_lanes:
        reason_codes.append("PLANNED_LANE_UNDISPOSED")
    if any(
        str(value).startswith("required_lane_incomplete:")
        for value in (
            *pack.gaps,
            *(item.get("message", "") for item in pack.blockers),
        )
    ):
        reason_codes.append("REQUIRED_LANE_INCOMPLETE")

    projection = (
        agent_discovery.get("requirement_projection")
        if isinstance(agent_discovery, dict)
        else None
    )
    raw_requirements = (
        projection.get("planning_blocking_questions")
        if isinstance(projection, dict)
        else None
    )
    requirement_ids = {
        str(row.get("requirement_id"))
        for row in raw_requirements or []
        if isinstance(row, dict) and row.get("requirement_id")
    }
    covered_requirement_ids: set[str] = set()
    actual_relationships_by_relation: dict[str, set[str]] = {}
    actual_observation_refs_by_binding: dict[tuple[str, str], set[str]] = {}
    for conclusion in pack.evidence_conclusions:
        relationship = conclusion.get("relationship")
        refs = conclusion.get("requirement_ids")
        relation_refs = conclusion.get("relation_ids")
        observation_refs = conclusion.get("observation_ids")
        if relationship not in _RELATIONSHIP_VALUES:
            continue
        if isinstance(refs, list):
            for value in refs:
                if not isinstance(value, str) or not value:
                    continue
                covered_requirement_ids.add(value)
        if isinstance(relation_refs, list):
            for relation_id in relation_refs:
                if not isinstance(relation_id, str) or not relation_id:
                    continue
                actual_relationships_by_relation.setdefault(
                    relation_id, set()
                ).add(str(relationship))
                actual_observation_refs_by_binding.setdefault(
                    (relation_id, str(relationship)), set()
                ).update(
                    str(item)
                    for item in observation_refs or []
                    if isinstance(item, str) and item
                )
    uncovered_requirement_ids = sorted(
        requirement_ids - covered_requirement_ids
    )
    if uncovered_requirement_ids:
        reason_codes.append("REQUIREMENT_RELATION_UNCOVERED")

    plan_budget: dict[str, object] | None = None
    if isinstance(agent_discovery, dict) and planned_lanes:
        plan_budget = discovery_plan_budget_feasibility(
            agent_discovery=agent_discovery,
            max_tool_calls=int(pack.budget_summary.get("max_tool_calls", 0)),
            max_model_steps=int(pack.budget_summary.get("max_model_steps", 0)),
        )
        if not plan_budget["feasible"]:
            reason_codes.append("DISCOVERY_PLAN_BUDGET_INFEASIBLE")
    if pack.run_status == "budget_exhausted":
        reason_codes.append("ACTUAL_RUN_BUDGET_EXHAUSTED")

    relation_score = _score_structured_relations(
        expected=expected,
        projection=projection,
        actual_relationships_by_relation=actual_relationships_by_relation,
        actual_observation_refs_by_binding=actual_observation_refs_by_binding,
    )
    if relation_score["status"] != "scored":
        reason_codes.append(str(relation_score["reason_code"]))

    blocking_reason_codes = list(dict.fromkeys(reason_codes))
    agent_behavior_evaluable = not blocking_reason_codes
    acceptable = expected.get("acceptable_hook_full_identities")
    has_acceptable_identity_direction = isinstance(acceptable, list) and bool(
        acceptable
    )
    if (
        not has_acceptable_identity_direction
        and plan_budget is not None
        and not plan_budget["feasible"]
    ):
        validity = "invalid_for_agent_evaluation_for_current_protocol"
    else:
        validity = "valid_with_limitations"

    generic_matches = bool(
        generic_comparison.get("sufficiency_matches") is True
        and generic_comparison.get("control_action_matches") is True
        and generic_comparison.get("acceptable_hook_identity_set_matches") is True
        and generic_comparison.get("forbidden_hook_identity_hits") == []
    )
    negative_shape = bool(
        expected.get("expected_sufficiency") == "insufficient"
        and expected.get("expected_control_action") == "block"
        and acceptable == []
    )
    unscored_expected_fields = [
        field
        for field in (
            "required_evidence",
            "forbidden_evidence",
            "required_missing_evidence",
        )
        if isinstance(expected.get(field), list) and expected.get(field)
    ]
    failure_reason_codes: list[str] = []
    forbidden_identity_hits = generic_comparison.get("forbidden_hook_identity_hits")
    if isinstance(forbidden_identity_hits, list) and forbidden_identity_hits:
        failure_reason_codes.append("FORBIDDEN_IDENTITY_HIT")
    if relation_score.get("forbidden_hits"):
        failure_reason_codes.append("FORBIDDEN_RELATION_HIT")
    if relation_score.get("status") == "scored" and not relation_score.get(
        "matches"
    ):
        failure_reason_codes.append("STRUCTURED_RELATION_MISMATCH")
    if not generic_matches:
        failure_reason_codes.append("GENERIC_COMPARISON_MISMATCH")

    if not agent_behavior_evaluable:
        capability_verdict = "inconclusive"
    elif failure_reason_codes:
        capability_verdict = "fail"
    else:
        capability_verdict = "pass"
    negative_capability_pass = bool(
        capability_verdict == "pass" and negative_shape
    )
    return {
        "protocol_version": "calibration_reliability_gate_v2",
        "case_validity": validity,
        "agent_behavior_evaluable": agent_behavior_evaluable,
        "agent_behavior_outcome": capability_verdict,
        "capability_verdict": capability_verdict,
        "negative_capability_pass": negative_capability_pass,
        "reason_codes": blocking_reason_codes,
        "failure_reason_codes": failure_reason_codes,
        "identity_and_isolation_hard_gates": {
            "artifact_type": "passed",
            "strict_semantic_rehydrate": "passed",
            "request_binding": "passed",
            "manifest_binding": "passed",
            "expected_hash_and_isolation": "passed",
        },
        "coverage": {
            "planned_lane_count": len(planned_lane_ids),
            "disposed_lane_count": len(planned_lane_ids) - len(undisposed_lanes),
            "undisposed_lanes": undisposed_lanes,
            "coverage_complete": not undisposed_lanes and bool(planned_lane_ids),
        },
        "budget_feasibility": plan_budget,
        "actual_relation_coverage": {
            "required_requirement_ids": sorted(requirement_ids),
            "covered_requirement_ids": sorted(covered_requirement_ids),
            "uncovered_requirement_ids": uncovered_requirement_ids,
            "complete": not uncovered_requirement_ids and bool(requirement_ids),
        },
        "expected_relation_scoreability": {
            "structured_mapping_available": relation_score["status"] == "scored",
            "status": relation_score["status"],
            "unscored_fields": unscored_expected_fields,
            "text_matching_used": False,
        },
        "structured_relation_score": relation_score,
        "generic_comparison_retained": True,
        "generic_comparison_matches": generic_matches,
    }


def _score_structured_relations(
    *,
    expected: Mapping[str, Any],
    projection: object,
    actual_relationships_by_relation: Mapping[str, set[str]],
    actual_observation_refs_by_binding: Mapping[tuple[str, str], set[str]],
) -> dict[str, Any]:
    rubric = expected.get("structured_relation_rubric")
    if rubric is None:
        return {
            "status": "unscored",
            "reason_code": "EXPECTED_STRUCTURED_RELATION_MAPPING_MISSING",
            "matches": False,
            "required_relation_results": [],
            "forbidden_hits": [],
            "unexpected_actual_relations": [],
            "missing_relation_mappings": [],
        }
    if not isinstance(rubric, dict):
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_RELATION_RUBRIC_SHAPE_INVALID"
        )
    relation_contract = (
        projection.get("relation_contract")
        if isinstance(projection, dict)
        else None
    )
    relation_definitions = (
        relation_contract.get("relations")
        if isinstance(relation_contract, dict)
        else None
    )
    if not isinstance(relation_definitions, list) or not relation_definitions:
        return {
            "status": "unscored",
            "reason_code": "ACTUAL_RELATION_IDENTITY_CONTRACT_MISSING",
            "matches": False,
            "required_relation_results": [],
            "forbidden_hits": [],
            "unexpected_actual_relations": [],
            "missing_relation_mappings": [],
        }
    relation_by_id = {
        str(row["relation_id"]): row
        for row in relation_definitions
        if isinstance(row, dict) and row.get("relation_id")
    }
    required_rows = rubric["required_relations"]
    forbidden_rows = rubric["forbidden_relations"]
    required_expected_relation_ids = {
        str(row["relation_id"])
        for row in required_rows
        if isinstance(row, dict)
    }
    all_expected_relation_ids = {
        str(row["relation_id"])
        for row in (*required_rows, *forbidden_rows)
        if isinstance(row, dict)
    }
    unknown_relation_ids = sorted(
        all_expected_relation_ids - set(relation_by_id)
    )
    if unknown_relation_ids:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_RELATION_IDENTITY_MISMATCH"
        )
    missing_relation_mappings = sorted(
        set(relation_by_id) - required_expected_relation_ids
    )
    if missing_relation_mappings:
        return {
            "status": "unscored",
            "reason_code": "EXPECTED_STRUCTURED_RELATION_MAPPING_INCOMPLETE",
            "matches": False,
            "required_relation_results": [],
            "forbidden_hits": [],
            "unexpected_actual_relations": [],
            "missing_relation_mappings": missing_relation_mappings,
        }

    expected_bindings = {
        (str(row["relation_id"]), str(row["relationship"]))
        for row in required_rows
        if isinstance(row, dict)
    }
    actual_bindings = {
        (relation_id, relationship)
        for relation_id, relationships in actual_relationships_by_relation.items()
        if relation_id in relation_by_id
        for relationship in relationships
    }
    required_relation_results = [
        {
            "relation_id": str(row["relation_id"]),
            "parent_requirement_ids": list(
                relation_by_id[str(row["relation_id"])][
                    "parent_requirement_ids"
                ]
            ),
            "expected_relationship": str(row["relationship"]),
            "actual_observation_refs": sorted(
                actual_observation_refs_by_binding.get(
                    (
                        str(row["relation_id"]),
                        str(row["relationship"]),
                    ),
                    set(),
                )
            ),
            "grounding_required": True,
            "matched": bool(
                str(row["relationship"])
                in actual_relationships_by_relation.get(
                    str(row["relation_id"]), set()
                )
                and actual_observation_refs_by_binding.get(
                    (
                        str(row["relation_id"]),
                        str(row["relationship"]),
                    )
                )
            ),
        }
        for row in required_rows
        if isinstance(row, dict)
    ]
    forbidden_hits = [
        {
            "relation_id": str(row["relation_id"]),
            "relationship": str(row["relationship"]),
            "actual_observation_refs": sorted(
                actual_observation_refs_by_binding.get(
                    (
                        str(row["relation_id"]),
                        str(row["relationship"]),
                    ),
                    set(),
                )
            ),
        }
        for row in forbidden_rows
        if isinstance(row, dict)
        and str(row["relationship"])
        in actual_relationships_by_relation.get(
            str(row["relation_id"]), set()
        )
    ]
    unexpected_actual_relations = [
        {
            "relation_id": relation_id,
            "relationship": relationship,
            "actual_observation_refs": sorted(
                actual_observation_refs_by_binding.get(
                    (relation_id, relationship), set()
                )
            ),
        }
        for relation_id, relationship in sorted(
            actual_bindings - expected_bindings
        )
    ]
    matches = bool(
        all(row["matched"] for row in required_relation_results)
        and not forbidden_hits
        and not unexpected_actual_relations
    )
    return {
        "status": "scored",
        "reason_code": None,
        "matches": matches,
        "required_relation_results": required_relation_results,
        "forbidden_hits": forbidden_hits,
        "unexpected_actual_relations": unexpected_actual_relations,
        "missing_relation_mappings": [],
    }


def _aggregate_calibration_verdicts(
    reports: list[Mapping[str, Any]],
) -> dict[str, Any]:
    counts = {"pass": 0, "fail": 0, "inconclusive": 0}
    inconclusive_reason_counts: dict[str, int] = {}
    for report in reports:
        reliability = report.get("reliability", report)
        if not isinstance(reliability, Mapping):
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_RELIABILITY_REPORT_INVALID"
            )
        verdict = reliability.get("capability_verdict")
        if verdict not in counts:
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_CAPABILITY_VERDICT_INVALID"
            )
        counts[str(verdict)] += 1
        if verdict == "inconclusive":
            reasons = reliability.get("reason_codes")
            normalized_reasons = (
                sorted({str(value) for value in reasons if isinstance(value, str)})
                if isinstance(reasons, list) and reasons
                else ["UNSPECIFIED_INCONCLUSIVE"]
            )
            for reason in normalized_reasons:
                inconclusive_reason_counts[reason] = (
                    inconclusive_reason_counts.get(reason, 0) + 1
                )
    scored_count = counts["pass"] + counts["fail"]
    total_count = len(reports)
    return {
        "total_count": total_count,
        "pass_count": counts["pass"],
        "fail_count": counts["fail"],
        "inconclusive_count": counts["inconclusive"],
        "inconclusive_reason_counts": inconclusive_reason_counts,
        "scored_count": scored_count,
        "evaluable_rate": (
            scored_count / total_count if total_count else None
        ),
        "all_run_pass_rate": (
            counts["pass"] / total_count if total_count else None
        ),
        "conditional_scored_success_rate": (
            counts["pass"] / scored_count if scored_count else None
        ),
        "zero_total_rate_policy": "null",
        "inconclusive_excluded_from_success_rate": True,
        "promotion_rate_policy": (
            "consume evaluable_rate and all_run_pass_rate; never use "
            "conditional_scored_success_rate alone"
        ),
    }


def _validate_actual_manifest_binding(
    pack: EvidencePack,
    actual_input: HiddenGoldenActualInput,
) -> None:
    expected = {
        "case_identity": actual_input.case_identity,
        "request_sha256": actual_input.request_sha256,
        "declared_corpus_snapshot_sha256": (
            actual_input.declared_corpus_snapshot_sha256
        ),
        "observed_corpus_snapshot_sha256": (
            actual_input.observed_corpus_snapshot_sha256
        ),
        "source_allowlist": list(actual_input.source_allowlist),
    }
    if pack.provenance_validation.get("manifest_bound_actual") != expected:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_ACTUAL_MANIFEST_BINDING_MISMATCH"
        )


def _validated_expected(
    annotation: Mapping[str, Any], case_identity: str
) -> dict[str, Any]:
    if annotation.get("case_identity") != case_identity:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_CASE_IDENTITY_MISMATCH")
    if annotation.get("technical_review_authority") != _TECHNICAL_REVIEW_AUTHORITY:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REVIEW_AUTHORITY_INVALID")
    if annotation.get("current_rag_actual_output_accessed") is not False:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_EXPECTED_ISOLATION_INVALID")
    if (
        annotation.get("judgment_hash_protocol")
        != "sha256_of_canonical_json_over_judgment_payload_only"
    ):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_HASH_PROTOCOL_INVALID")
    expected = annotation.get("judgment_payload")
    if not isinstance(expected, dict) or tuple(expected) not in {
        _JUDGMENT_FIELDS,
        _JUDGMENT_FIELDS_WITH_RELATIONS,
    }:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JUDGMENT_SHAPE_INVALID")
    calculated = _canonical_sha256(expected)
    if annotation.get("proposed_judgment_hash") != calculated:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_PROPOSED_HASH_MISMATCH")
    if annotation.get("frozen_judgment_hash") != calculated:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_FROZEN_HASH_MISMATCH")
    if expected.get("expected_sufficiency") not in {
        "sufficient",
        "insufficient",
        "contradictory",
    }:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_SUFFICIENCY_INVALID")
    if expected.get("expected_control_action") not in {"continue", "block"}:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTION_INVALID")
    rubric = expected.get("structured_relation_rubric")
    if rubric is not None:
        _validate_structured_relation_rubric(rubric)
    return expected


def _validate_structured_relation_rubric(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "required_relations",
        "forbidden_relations",
    }:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_RELATION_RUBRIC_SHAPE_INVALID"
        )
    if value.get("schema_version") != STRUCTURED_RELATION_RUBRIC_VERSION:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_RELATION_RUBRIC_VERSION_INVALID"
        )
    relation_bindings: set[tuple[str, str]] = set()
    for field in ("required_relations", "forbidden_relations"):
        rows = value.get(field)
        if not isinstance(rows, list):
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_RELATION_RUBRIC_LIST_INVALID"
            )
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "relation_id",
                "relationship",
            }:
                raise HiddenGoldenCalibrationError(
                    "HIDDEN_GOLDEN_RELATION_RUBRIC_ROW_INVALID"
                )
            relation_id = row.get("relation_id")
            relationship = row.get("relationship")
            if (
                not isinstance(relation_id, str)
                or not relation_id.strip()
                or relationship not in _RELATIONSHIP_VALUES
            ):
                raise HiddenGoldenCalibrationError(
                    "HIDDEN_GOLDEN_RELATION_RUBRIC_IDENTITY_INVALID"
                )
            binding = (relation_id, str(relationship))
            if binding in relation_bindings:
                raise HiddenGoldenCalibrationError(
                    "HIDDEN_GOLDEN_RELATION_RUBRIC_DUPLICATE"
                )
            relation_bindings.add(binding)


def _actual_decision(pack: EvidencePack) -> tuple[str, str]:
    if pack.hook_discovery is not None:
        sufficiency = pack.hook_discovery["sufficiency"]["planning"]["status"]
        action = pack.hook_discovery["planning_action"]
        return str(sufficiency), str(action)
    if pack.agent_discovery is not None:
        return pack.readiness, "continue" if pack.can_generate_patch else "block"
    raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_SEMANTICS_MISSING")


def _actual_hook_identities(pack: EvidencePack) -> list[dict[str, str]]:
    if pack.hook_discovery is None:
        return []
    result: list[dict[str, str]] = []
    for value in pack.hook_discovery["hook_identities"]:
        if not all(
            isinstance(value.get(field), str) and value.get(field)
            for field in (
                "source_content_hash",
                "module_mvid",
                "declaring_type",
                "method_name",
                "metadata_token",
                "signature_blob",
            )
        ):
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_ACTUAL_FULL_IDENTITY_MISSING"
            )
        result.append(
            {
                "assembly_sha256": str(value["source_content_hash"]),
                "module_mvid": str(value["module_mvid"]),
                "declaring_type": str(value["declaring_type"]),
                "method_name": str(value["method_name"]),
                "metadata_token": str(value["metadata_token"]),
                "signature_blob": str(value["signature_blob"]),
            }
        )
    return sorted(result, key=_identity_key)


def _expected_identities(
    expected: Mapping[str, Any], field: str, scope_field: str
) -> list[dict[str, str]]:
    values = expected.get(field)
    if not isinstance(values, list):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_IDENTITY_LIST_INVALID")
    result: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {*_FULL_IDENTITY_FIELDS, scope_field}:
            raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_FULL_IDENTITY_INVALID")
        identity: dict[str, str] = {}
        for key in _FULL_IDENTITY_FIELDS:
            raw = value.get(key)
            if not isinstance(raw, str) or not raw:
                raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_FULL_IDENTITY_INVALID")
            identity[key] = raw
        result.append(identity)
    return sorted(result, key=_identity_key)


def _identity_key(value: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(value[field] for field in _FULL_IDENTITY_FIELDS)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JSON_READ_FAILED") from exc
    if not isinstance(value, dict):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JSON_OBJECT_REQUIRED")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()
