"""Pure Hook Discovery evidence semantics for RAG/ER."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from .models import DETERMINISTIC_EVIDENCE_AUTHORITY, EvidenceItem

if TYPE_CHECKING:
    from .models import EvidencePack

HOOK_DISCOVERY_REQUEST_TYPE = "hook_discovery"
HOOK_DISCOVERY_SCHEMA_VERSION = "hook_discovery_evidence_v2"

_LANE_STATUSES = frozenset(
    {
        "searched_with_results",
        "searched_and_absent",
        "insufficient_coverage",
        "not_searched",
        "failed",
    }
)
_SOURCE_AUTHORITIES = frozenset({"authoritative", "supporting", "lead"})
_RELATIONSHIPS = frozenset({"support", "conflict", "missing"})


class HookDiscoverySemanticsError(ValueError):
    """Raised when a Hook Discovery request or evidence projection is invalid."""


def build_hook_discovery_semantics(
    *,
    hook_requirement: Mapping[str, Any],
    items: Iterable[EvidenceItem],
    lane_coverage: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the single persisted Hook Discovery semantic projection."""

    _require_exact_value(
        hook_requirement,
        "request_type",
        HOOK_DISCOVERY_REQUEST_TYPE,
    )
    required_lanes = _string_list(hook_requirement, "required_lanes", allow_empty=False)
    requirements = _object_list(
        hook_requirement,
        "evidence_requirements",
        allow_empty=False,
    )
    limitations = _string_list(hook_requirement, "limitations", allow_empty=True)

    evidence_items = tuple(items)
    normalized_relationships: list[dict[str, Any]] = []
    for requirement in requirements:
        requirement_id = _required_string(requirement, "requirement_id")
        description = _required_string(requirement, "description")
        relationship = _required_string(requirement, "relationship")
        if relationship not in _RELATIONSHIPS:
            raise HookDiscoverySemanticsError(
                f"Unsupported evidence relationship for {requirement_id}: {relationship}"
            )
        planning_blocking = requirement.get("planning_blocking")
        if not isinstance(planning_blocking, bool):
            raise HookDiscoverySemanticsError(
                f"planning_blocking must be boolean for {requirement_id}."
            )
        match = requirement.get("match")
        if not isinstance(match, Mapping):
            raise HookDiscoverySemanticsError(
                f"match must be an object for {requirement_id}."
            )
        matched = [item for item in evidence_items if _matches(item, match)]
        normalized_relationships.append(
            {
                "requirement_id": requirement_id,
                "description": description,
                "relationship": relationship,
                "evidence_ids": sorted(item.evidence_id for item in matched),
                "planning_blocking": planning_blocking,
                "absent_relationship": (
                    "missing" if relationship == "support" else "searched_and_absent"
                ),
            }
        )
    return _build_hook_discovery_semantics_core(
        items=evidence_items,
        coverage=_normalize_lane_coverage(lane_coverage),
        required_lanes=required_lanes,
        relationships=normalized_relationships,
        limitations=limitations,
        forced_planning_reasons=[],
    )


def build_agent_discovery_semantics(
    *,
    agent_discovery: Mapping[str, Any],
    items: Iterable[EvidenceItem],
    actions: Iterable[Mapping[str, Any]],
    observations: Iterable[Any],
    finish: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize actual loop evidence through the existing semantic owner."""

    projection = agent_discovery.get("requirement_projection")
    search_plan = agent_discovery.get("search_plan")
    if not isinstance(projection, Mapping) or not isinstance(search_plan, Mapping):
        raise HookDiscoverySemanticsError(
            "Agent discovery requires frozen requirement and search projections."
        )
    evidence_items = tuple(items)
    action_rows = [dict(item) for item in actions]
    observation_rows = list(observations)
    coverage = _agent_lane_coverage(
        search_plan=search_plan,
        actions=action_rows,
        observations=observation_rows,
    )
    observation_evidence = {
        str(observation.observation_id): sorted(
            item.evidence_id for item in observation.evidence_items
        )
        for observation in observation_rows
    }
    binding_by_observation = _agent_observation_requirement_bindings(
        search_plan=search_plan,
        actions=action_rows,
        observations=observation_rows,
    )
    conclusions = [
        item for item in finish.get("evidence_conclusions", [])
        if isinstance(item, Mapping)
    ]
    relationships: list[dict[str, Any]] = []
    blockers = projection.get("planning_blocking_questions")
    if not isinstance(blockers, list):
        raise HookDiscoverySemanticsError(
            "Requirement projection planning_blocking_questions must be an array."
        )
    for blocker in blockers:
        if not isinstance(blocker, Mapping):
            raise HookDiscoverySemanticsError("Planning blocker must be an object.")
        requirement_id = _required_string(blocker, "requirement_id")
        relevant = [
            value for value in conclusions
            if requirement_id in value.get("requirement_ids", [])
        ]
        selected_relationship = next(
            (
                relationship
                for relationship in ("conflict", "support", "missing")
                if any(
                    value.get("relationship") == relationship for value in relevant
                )
            ),
            "support",
        )
        selected = [
            value
            for value in relevant
            if value.get("relationship") == selected_relationship
        ]
        observation_ids = sorted(
            {
                str(observation_id)
                for value in selected
                for observation_id in value.get("observation_ids", [])
            }
        )
        bound_observation_ids = [
            value for value in observation_ids
            if requirement_id in binding_by_observation.get(value, {}).get(
                "requirement_ids", []
            )
        ]
        evidence_ids = sorted(
            {
                evidence_id
                for observation_id in bound_observation_ids
                for evidence_id in observation_evidence.get(observation_id, [])
            }
        )
        trace = _relationship_trace(
            requirement_id=requirement_id,
            observation_ids=bound_observation_ids,
            binding_by_observation=binding_by_observation,
        )
        relationships.append(
            {
                "requirement_id": requirement_id,
                "description": _required_string(blocker, "question"),
                "relationship": (
                    selected_relationship
                ),
                "evidence_ids": evidence_ids,
                "observation_ids": bound_observation_ids,
                "planning_blocking": True,
                "limitations": (
                    sorted(
                        {
                            str(limitation)
                            for value in selected
                            for limitation in value.get("limitations", [])
                        }
                    )
                ),
                "query_family_ids": trace["query_family_ids"],
                "engineering_question_ids": trace["engineering_question_ids"],
                "action_indexes": trace["action_indexes"],
                "absent_relationship": "missing",
            }
        )
    open_questions = [
        str(value)
        for value in (
            list(finish.get("unresolved_questions", []))
            + list(finish.get("missing_capabilities", []))
        )
    ]
    return _build_hook_discovery_semantics_core(
        items=evidence_items,
        coverage=coverage,
        required_lanes=[str(value["lane"]) for value in coverage],
        relationships=relationships,
        limitations=list(dict.fromkeys(open_questions)),
        forced_planning_reasons=open_questions,
    )


def _build_hook_discovery_semantics_core(
    *,
    items: tuple[EvidenceItem, ...],
    coverage: list[dict[str, Any]],
    required_lanes: list[str],
    relationships: list[dict[str, Any]],
    limitations: list[str],
    forced_planning_reasons: list[str],
) -> dict[str, Any]:
    """Own source admission, relationships, sufficiency, and planning action."""

    admitted, rejected = _admit_items(items)
    admitted_by_id = {item.evidence_id: item for item in admitted}
    coverage_by_lane = {entry["lane"]: entry for entry in coverage}
    missing_lanes = [lane for lane in required_lanes if lane not in coverage_by_lane]
    failed_lanes = [
        lane
        for lane in required_lanes
        if lane in coverage_by_lane
        and coverage_by_lane[lane]["status"]
        not in {"searched_with_results", "searched_and_absent"}
    ]

    normalized_relationships: list[dict[str, Any]] = []
    planning_blockers: list[str] = []
    conflict_ids: list[str] = []
    authoritative_support_ids: set[str] = set()
    for relationship in relationships:
        requirement_id = _required_string(relationship, "requirement_id")
        requested_relationship = _required_string(relationship, "relationship")
        if requested_relationship not in _RELATIONSHIPS:
            raise HookDiscoverySemanticsError(
                f"Unsupported evidence relationship for {requirement_id}: "
                f"{requested_relationship}"
            )
        raw_evidence_ids = relationship.get("evidence_ids")
        if not isinstance(raw_evidence_ids, list):
            raise HookDiscoverySemanticsError("evidence_ids must be an array.")
        evidence_ids = sorted(
            value
            for value in {str(item) for item in raw_evidence_ids}
            if value in admitted_by_id
        )
        decisive_ids = [
            value
            for value in evidence_ids
            if admitted_by_id[value].source_authority == "authoritative"
        ]
        absent_relationship = str(
            relationship.get("absent_relationship")
            or ("missing" if requested_relationship == "support" else "searched_and_absent")
        )
        result = requested_relationship if decisive_ids else absent_relationship
        planning_blocking = relationship.get("planning_blocking")
        if not isinstance(planning_blocking, bool):
            raise HookDiscoverySemanticsError(
                f"planning_blocking must be boolean for {requirement_id}."
            )
        if result == "support":
            authoritative_support_ids.update(decisive_ids)
        if planning_blocking and result != "support":
            planning_blockers.append(requirement_id)
        if planning_blocking and result == "conflict":
            conflict_ids.append(requirement_id)
        normalized = {
            key: value
            for key, value in relationship.items()
            if key not in {"absent_relationship", "relationship", "evidence_ids"}
        }
        normalized.update(
            {
                "relationship": result,
                "evidence_ids": evidence_ids,
                "decisive_evidence_ids": decisive_ids,
            }
        )
        normalized_relationships.append(normalized)

    normalized_hooks = [
        _hook_identity_from_item(item)
        for item in admitted
        if item.evidence_id in authoritative_support_ids
        and _has_complete_hook_identity(item)
    ]
    retrieval_reasons = [
        *(f"required_lane_not_reported:{lane}" for lane in missing_lanes),
        *(f"required_lane_incomplete:{lane}" for lane in failed_lanes),
    ]
    retrieval_status = "sufficient" if not retrieval_reasons else "insufficient"
    engineering_reasons = [
        f"planning_requirement_missing_or_conflicted:{value}"
        for value in planning_blockers
    ]
    engineering_reasons.extend(forced_planning_reasons)
    if not admitted:
        engineering_reasons.append("no_admitted_evidence")
    if not normalized_hooks:
        engineering_reasons.append("no_authoritative_relevant_complete_hook_identity")
    engineering_status = (
        "contradictory"
        if conflict_ids
        else "sufficient"
        if not engineering_reasons
        else "insufficient"
    )
    planning_reasons = [*retrieval_reasons, *engineering_reasons]
    planning_status = (
        "contradictory"
        if conflict_ids
        else "sufficient"
        if not planning_reasons
        else "insufficient"
    )
    return {
        "schema_version": HOOK_DISCOVERY_SCHEMA_VERSION,
        "request_type": HOOK_DISCOVERY_REQUEST_TYPE,
        "source_admission": {
            "admitted_evidence_ids": sorted(admitted_by_id),
            "rejected": rejected,
        },
        "lane_coverage": coverage,
        "hook_identities": normalized_hooks,
        "evidence_relationships": normalized_relationships,
        "sufficiency": {
            "retrieval": {"status": retrieval_status, "reasons": retrieval_reasons},
            "engineering": {
                "status": engineering_status,
                "reasons": engineering_reasons,
            },
            "planning": {"status": planning_status, "reasons": planning_reasons},
        },
        "planning_action": "continue" if planning_status == "sufficient" else "block",
        "limitations": limitations,
        "does_not_grant": [
            "human_approval",
            "apply_permission",
            "build_permission",
            "runtime_acceptance",
            "final_correctness",
        ],
    }


def evidence_pack_state_from_hook_discovery(
    *,
    semantics: Mapping[str, Any],
    items: Iterable[EvidenceItem],
    excluded: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Project one Hook Discovery semantic result to EvidencePack top-level state."""

    validate_hook_discovery_semantics(semantics)
    admitted_ids = set(semantics["source_admission"]["admitted_evidence_ids"])
    admitted_items = tuple(item for item in items if item.evidence_id in admitted_ids)
    planning = semantics["sufficiency"]["planning"]
    planning_status = str(planning["status"])
    reasons = tuple(str(value) for value in planning["reasons"])
    blockers = tuple(
        {
            "code": "HOOK_DISCOVERY_PLANNING_BLOCKED",
            "message": reason,
            "needed_evidence": [reason],
        }
        for reason in reasons
    )
    rejected = tuple(
        {"stage": "source_admission", **dict(value)}
        for value in semantics["source_admission"]["rejected"]
    )
    return {
        "readiness": planning_status,
        "can_generate_patch": semantics["planning_action"] == "continue",
        "items": admitted_items,
        "excluded": tuple(dict(value) for value in excluded) + rejected,
        "gaps": reasons,
        "blockers": blockers,
        "message": (
            "Hook Discovery evidence supports implementation planning; it grants no "
            "Approval, Apply, Build, Runtime, or final-correctness authority."
            if semantics["planning_action"] == "continue"
            else "Hook Discovery evidence does not support implementation planning."
        ),
    }


def _agent_observation_requirement_bindings(
    *,
    search_plan: Mapping[str, Any],
    actions: list[dict[str, Any]],
    observations: list[Any],
) -> dict[str, dict[str, Any]]:
    questions = search_plan.get("engineering_questions")
    families = search_plan.get("query_families")
    if not isinstance(questions, list) or not isinstance(families, list):
        raise HookDiscoverySemanticsError("Search plan relationship collections are invalid.")
    question_requirements = {
        str(item["question_id"]): [str(value) for value in item["requirement_ids"]]
        for item in questions
        if isinstance(item, Mapping)
    }
    bindings: dict[str, dict[str, Any]] = {}
    for index, (action, observation) in enumerate(zip(actions, observations), 1):
        family_rows: list[Mapping[str, Any]] = []
        if action.get("tool") == "search_dotnet_metadata":
            arguments = action.get("arguments")
            if isinstance(arguments, Mapping):
                family_rows = _families_for_resolved_action(
                    action=action,
                    families=families,
                )
            if len(family_rows) != 1:
                raise HookDiscoverySemanticsError(
                    "Metadata observation must bind exactly one frozen query family."
                )
        derived = action.get("derived_from_observation_ids")
        inherited = [
            bindings[value]
            for value in derived
            if isinstance(derived, list) and value in bindings
        ]
        question_ids = sorted(
            {
                str(value)
                for family in family_rows
                for value in family.get("question_ids", [])
            }
            | {
                str(value)
                for binding in inherited
                for value in binding["engineering_question_ids"]
            }
        )
        requirement_ids = sorted(
            {
                value
                for question_id in question_ids
                for value in question_requirements.get(question_id, [])
            }
        )
        bindings[str(observation.observation_id)] = {
            "requirement_ids": requirement_ids,
            "engineering_question_ids": question_ids,
            "query_family_ids": sorted(
                {str(family["family_id"]) for family in family_rows}
                | {
                    str(value)
                    for binding in inherited
                    for value in binding["query_family_ids"]
                }
            ),
            "action_indexes": sorted(
                {index}
                | {
                    int(value)
                    for binding in inherited
                    for value in binding["action_indexes"]
                }
            ),
        }
    return bindings


def _families_for_resolved_action(
    *,
    action: Mapping[str, Any],
    families: list[Any],
) -> list[Mapping[str, Any]]:
    arguments = action.get("arguments")
    if not isinstance(arguments, Mapping):
        return []
    query_family_id = action.get("query_family_id")
    return [
        family
        for family in families
        if isinstance(family, Mapping)
        and (
            query_family_id is None
            or family.get("family_id") == query_family_id
        )
        and family.get("queries") == arguments.get("queries")
        and family.get("tool") == action.get("tool")
        and family.get("evidence_need") == action.get("evidence_need")
        and action.get("source_id") in family.get("source_ids", [])
    ]


def _expected_family_selection_derivation(
    *,
    selected_family: Mapping[str, Any],
    families: list[Any],
    accepted_actions: list[Mapping[str, Any]],
    observation_rows: list[Mapping[str, Any]],
) -> list[str]:
    """Recompute the one deterministic observation binding for a family selection."""

    if not accepted_actions:
        return []
    completed_observations = observation_rows[: len(accepted_actions)]
    if len(completed_observations) != len(accepted_actions):
        raise HookDiscoverySemanticsError(
            "Family selection does not follow completed observations."
        )
    consumed_observation_ids = {
        str(observation_id)
        for action in accepted_actions
        for observation_id in action.get("derived_from_observation_ids", [])
        if isinstance(observation_id, str)
    }
    pending = [
        (index, observation)
        for index, observation in enumerate(completed_observations)
        if observation.get("observation_id") not in consumed_observation_ids
    ]
    if len(pending) != 1 or pending[0][0] != len(completed_observations) - 1:
        raise HookDiscoverySemanticsError(
            "Family selection observation binding is not uniquely provable."
        )
    origin_index, observation = pending[0]
    observation_id = observation.get("observation_id")
    if not isinstance(observation_id, str) or not observation_id:
        raise HookDiscoverySemanticsError(
            "Family selection observation binding is invalid."
        )
    origin_action = accepted_actions[origin_index]
    if origin_action.get("tool") == "inspect_method_il":
        return [observation_id]
    if origin_action.get("tool") != "search_dotnet_metadata":
        raise HookDiscoverySemanticsError(
            "Family selection observation origin is unsupported."
        )
    origin_family_id = origin_action.get("query_family_id")
    origin_family = next(
        (
            family
            for family in families
            if isinstance(family, Mapping)
            and family.get("family_id") == origin_family_id
        ),
        None,
    )
    selected_question_ids = selected_family.get("question_ids")
    origin_question_ids = (
        origin_family.get("question_ids")
        if isinstance(origin_family, Mapping)
        else None
    )
    if (
        not isinstance(selected_question_ids, list)
        or not selected_question_ids
        or not isinstance(origin_question_ids, list)
        or set(selected_question_ids) != set(origin_question_ids)
    ):
        raise HookDiscoverySemanticsError(
            "Family selection observation does not bind the same engineering question."
        )
    return [observation_id]


def _relationship_trace(
    *,
    requirement_id: str,
    observation_ids: list[str],
    binding_by_observation: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[Any]]:
    bindings = [binding_by_observation[value] for value in observation_ids]
    return {
        "query_family_ids": sorted(
            {
                str(value)
                for binding in bindings
                for value in binding["query_family_ids"]
            }
        ),
        "engineering_question_ids": sorted(
            {
                str(value)
                for binding in bindings
                for value in binding["engineering_question_ids"]
            }
        ),
        "action_indexes": sorted({
            int(value)
            for binding in bindings
            if requirement_id in binding["requirement_ids"]
            for value in binding["action_indexes"]
        }),
    }


def _agent_lane_coverage(
    *,
    search_plan: Mapping[str, Any],
    actions: list[dict[str, Any]],
    observations: list[Any],
) -> list[dict[str, Any]]:
    planned_lanes = search_plan.get("planned_lanes")
    if not isinstance(planned_lanes, list):
        raise HookDiscoverySemanticsError("Search plan planned_lanes must be an array.")
    binding_by_observation = _agent_observation_requirement_bindings(
        search_plan=search_plan,
        actions=actions,
        observations=observations,
    )
    families = search_plan.get("query_families")
    if not isinstance(families, list):
        raise HookDiscoverySemanticsError("Search plan query_families must be an array.")
    legacy_lane_keys = [
        (raw_lane.get("tool"), tuple(raw_lane.get("source_ids", [])))
        for raw_lane in planned_lanes
        if isinstance(raw_lane, Mapping)
    ]
    coverage: list[dict[str, Any]] = []
    for raw_lane in planned_lanes:
        if not isinstance(raw_lane, Mapping):
            raise HookDiscoverySemanticsError("Search plan lane must be an object.")
        lane = _required_string(raw_lane, "lane")
        tool = _required_string(raw_lane, "tool")
        source_ids = raw_lane.get("source_ids")
        if not isinstance(source_ids, list):
            raise HookDiscoverySemanticsError("Search plan source_ids must be an array.")
        question_ids = raw_lane.get("question_ids")
        if question_ids is None:
            lane_key = (tool, tuple(source_ids))
            if legacy_lane_keys.count(lane_key) != 1:
                raise HookDiscoverySemanticsError(
                    "Legacy lanes with the same tool and sources are ambiguous."
                )
            matching_indexes = [
                index
                for index, action in enumerate(actions)
                if action.get("tool") == tool
                and action.get("source_id") in source_ids
            ]
        else:
            if not isinstance(question_ids, list) or not all(
                isinstance(value, str) and value for value in question_ids
            ):
                raise HookDiscoverySemanticsError(
                    "Search plan lane question_ids must be a string array."
                )
            lane_questions = set(question_ids)
            matching_indexes = []
            for index, (action, observation) in enumerate(zip(actions, observations)):
                if (
                    action.get("tool") != tool
                    or action.get("source_id") not in source_ids
                ):
                    continue
                if tool == "search_dotnet_metadata":
                    direct_families = _families_for_resolved_action(
                        action=action,
                        families=families,
                    )
                    if len(direct_families) != 1:
                        raise HookDiscoverySemanticsError(
                            "Metadata lane must bind exactly one frozen query family."
                        )
                    action_questions = set(direct_families[0]["question_ids"])
                else:
                    action_questions = set(
                        binding_by_observation[str(observation.observation_id)][
                            "engineering_question_ids"
                        ]
                    )
                if lane_questions.intersection(action_questions):
                    matching_indexes.append(index)
        matching_observations = [observations[index] for index in matching_indexes]
        matching_actions = [actions[index] for index in matching_indexes]
        actual_source_ids = (
            list(source_ids)
            if question_ids is None
            else [
                source_id
                for source_id in source_ids
                if any(
                    action.get("source_id") == source_id
                    for action in matching_actions
                )
            ]
        )
        hit_count = sum(
            len(observation.evidence_items)
            if tool == "inspect_method_il"
            else sum(
                len(observation.data.get(kind, []))
                for kind in ("methods", "types", "fields")
                if isinstance(observation.data.get(kind), list)
            )
            for observation in matching_observations
        )
        status = (
            "searched_with_results"
            if hit_count > 0
            else "searched_and_absent"
            if matching_observations
            and all(_bounded_metadata_absence(observation) for observation in matching_observations)
            else "insufficient_coverage"
            if matching_observations
            else "not_searched"
        )
        coverage.append(
            {
                "lane": lane,
                "status": status,
                "hit_count": hit_count,
                "scope": {
                    "tool": tool,
                    "source_ids": actual_source_ids,
                    "action_count": len(matching_actions),
                },
                "failure": None,
            }
        )
    return coverage


def _bounded_metadata_absence(observation: Any) -> bool:
    """Recognize a complete bounded zero-hit search without inferring from emptiness."""

    if observation.tool != "search_dotnet_metadata":
        return False
    data = observation.data
    discovered = data.get("assemblies_discovered")
    searched = data.get("managed_assemblies_searched")
    unreadable = data.get("unreadable_or_non_managed_assemblies")
    returned = data.get("returned_counts")
    matched = data.get("matched_counts")
    return bool(
        isinstance(discovered, int)
        and discovered > 0
        and searched == discovered
        and unreadable == 0
        and data.get("results_truncated") is False
        and isinstance(returned, Mapping)
        and isinstance(matched, Mapping)
        and all(returned.get(kind) == 0 for kind in ("methods", "types", "fields"))
        and all(matched.get(kind) == 0 for kind in ("methods", "types", "fields"))
    )


def validate_hook_discovery_semantics(value: Mapping[str, Any]) -> None:
    """Validate a persisted Hook Discovery segment without recomputing it."""

    if set(value) != {
        "schema_version",
        "request_type",
        "source_admission",
        "lane_coverage",
        "hook_identities",
        "evidence_relationships",
        "sufficiency",
        "planning_action",
        "limitations",
        "does_not_grant",
    }:
        raise HookDiscoverySemanticsError("Hook Discovery shape is invalid.")
    _require_exact_value(value, "schema_version", HOOK_DISCOVERY_SCHEMA_VERSION)
    _require_exact_value(value, "request_type", HOOK_DISCOVERY_REQUEST_TYPE)
    source_admission = value.get("source_admission")
    if not isinstance(source_admission, Mapping) or set(source_admission) != {
        "admitted_evidence_ids",
        "rejected",
    }:
        raise HookDiscoverySemanticsError("source_admission must be an object.")
    admitted_ids = source_admission.get("admitted_evidence_ids")
    rejected = source_admission.get("rejected")
    if not isinstance(admitted_ids, list) or not all(
        isinstance(item, str) and item for item in admitted_ids
    ):
        raise HookDiscoverySemanticsError(
            "admitted_evidence_ids must be a string array."
        )
    if len(admitted_ids) != len(set(admitted_ids)):
        raise HookDiscoverySemanticsError("admitted_evidence_ids must be unique.")
    if not isinstance(rejected, list) or not all(
        isinstance(item, Mapping)
        and set(item) == {"evidence_id", "reason"}
        and isinstance(item.get("evidence_id"), str)
        and bool(item.get("evidence_id"))
        and isinstance(item.get("reason"), str)
        and bool(item.get("reason"))
        for item in rejected
    ):
        raise HookDiscoverySemanticsError("rejected must be an object array.")
    rejected_ids = [str(item["evidence_id"]) for item in rejected]
    if len(rejected_ids) != len(set(rejected_ids)) or set(rejected_ids) & set(admitted_ids):
        raise HookDiscoverySemanticsError("source_admission evidence ids are invalid.")
    _normalize_lane_coverage(_object_list(value, "lane_coverage", allow_empty=True))
    hooks = _object_list(value, "hook_identities", allow_empty=True)
    for hook in hooks:
        if _normalize_persisted_hook_identity(hook) != dict(hook):
            raise HookDiscoverySemanticsError("Hook identity shape is invalid.")
    relationships = _object_list(value, "evidence_relationships", allow_empty=False)
    requirement_ids: list[str] = []
    for relationship in relationships:
        requirement_id = _required_string(relationship, "requirement_id")
        requirement_ids.append(requirement_id)
        _required_string(relationship, "description")
        relation = _required_string(relationship, "relationship")
        if relation not in {"support", "conflict", "missing", "searched_and_absent"}:
            raise HookDiscoverySemanticsError(
                f"Unsupported persisted relationship: {relation}"
            )
        evidence_ids = relationship.get("evidence_ids")
        if not isinstance(evidence_ids, list) or not all(
            isinstance(item, str) and item for item in evidence_ids
        ):
            raise HookDiscoverySemanticsError("evidence_ids must be a string array.")
        if not isinstance(relationship.get("planning_blocking"), bool):
            raise HookDiscoverySemanticsError("planning_blocking must be boolean.")
        decisive_ids = relationship.get("decisive_evidence_ids")
        if not isinstance(decisive_ids, list) or not all(
            isinstance(item, str) and item for item in decisive_ids
        ):
            raise HookDiscoverySemanticsError(
                "decisive_evidence_ids must be a string array."
            )
        legacy_shape = {
            "requirement_id",
            "description",
            "relationship",
            "evidence_ids",
            "planning_blocking",
            "decisive_evidence_ids",
        }
        agent_shape = legacy_shape | {
            "observation_ids",
            "limitations",
            "query_family_ids",
            "engineering_question_ids",
            "action_indexes",
        }
        relationship_shape = frozenset(relationship)
        if relationship_shape not in {
            frozenset(legacy_shape),
            frozenset(agent_shape),
        }:
            raise HookDiscoverySemanticsError(
                f"Evidence relationship shape is invalid for {requirement_id}."
            )
        if relationship_shape == frozenset(agent_shape):
            for key in (
                "observation_ids",
                "limitations",
                "query_family_ids",
                "engineering_question_ids",
            ):
                _string_list(relationship, key, allow_empty=True)
            action_indexes = relationship.get("action_indexes")
            if not isinstance(action_indexes, list) or not all(
                isinstance(item, int) and not isinstance(item, bool) and item > 0
                for item in action_indexes
            ):
                raise HookDiscoverySemanticsError(
                    "action_indexes must be an array of positive integers."
                )
    if len(requirement_ids) != len(set(requirement_ids)):
        raise HookDiscoverySemanticsError("requirement_id values must be unique.")
    sufficiency = value.get("sufficiency")
    if not isinstance(sufficiency, Mapping) or set(sufficiency) != {
        "retrieval",
        "engineering",
        "planning",
    }:
        raise HookDiscoverySemanticsError("sufficiency must be an object.")
    for layer in ("retrieval", "engineering", "planning"):
        result = sufficiency.get(layer)
        if not isinstance(result, Mapping) or set(result) != {"status", "reasons"}:
            raise HookDiscoverySemanticsError(f"sufficiency.{layer} must be an object.")
        status = _required_string(result, "status")
        if status not in {"sufficient", "insufficient", "contradictory"}:
            raise HookDiscoverySemanticsError(
                f"Unsupported sufficiency status for {layer}: {status}"
            )
        _string_list(result, "reasons", allow_empty=True)
    action = _required_string(value, "planning_action")
    if action not in {"continue", "block"}:
        raise HookDiscoverySemanticsError(f"Unsupported planning_action: {action}")
    planning_status = sufficiency["planning"]["status"]
    if (action == "continue") != (planning_status == "sufficient"):
        raise HookDiscoverySemanticsError(
            "planning_action must match planning sufficiency."
        )
    _string_list(value, "limitations", allow_empty=True)
    does_not_grant = _string_list(value, "does_not_grant", allow_empty=False)
    if does_not_grant != [
        "human_approval",
        "apply_permission",
        "build_permission",
        "runtime_acceptance",
        "final_correctness",
    ]:
        raise HookDiscoverySemanticsError("does_not_grant boundary is invalid.")


def validate_hook_discovery_evidence_pack(pack: "EvidencePack") -> None:
    """Validate strict cross-section and top-level Hook Discovery persistence."""

    semantics = pack.hook_discovery
    if not isinstance(semantics, Mapping):
        raise HookDiscoverySemanticsError("hook_discovery must be present.")
    validate_hook_discovery_semantics(semantics)
    item_by_id = {item.evidence_id: item for item in pack.items}
    admitted, rejected = _admit_items(tuple(pack.items))
    if rejected or len(admitted) != len(pack.items):
        raise HookDiscoverySemanticsError(
            "Persisted Hook Discovery items must all pass source admission."
        )
    admitted_ids = semantics["source_admission"]["admitted_evidence_ids"]
    if admitted_ids != sorted(item_by_id):
        raise HookDiscoverySemanticsError(
            "source_admission must exactly match persisted EvidenceItems."
        )

    authoritative_support_ids = {
        evidence_id
        for relationship in semantics["evidence_relationships"]
        if relationship["relationship"] == "support"
        for evidence_id in relationship["decisive_evidence_ids"]
    }
    expected_hooks = [
        _hook_identity_from_item(item)
        for item in pack.items
        if item.evidence_id in authoritative_support_ids
        and _has_complete_hook_identity(item)
    ]
    persisted_hooks = semantics["hook_identities"]
    hook_ids = [str(value["evidence_id"]) for value in persisted_hooks]
    if len(hook_ids) != len(set(hook_ids)):
        raise HookDiscoverySemanticsError("Hook identity evidence ids must be unique.")
    if persisted_hooks != expected_hooks:
        raise HookDiscoverySemanticsError(
            "Hook identities must exactly match decisive authoritative EvidenceItems."
        )

    all_evidence_ids = set(item_by_id)
    for relationship in semantics["evidence_relationships"]:
        evidence_ids = relationship["evidence_ids"]
        decisive_ids = relationship["decisive_evidence_ids"]
        if len(evidence_ids) != len(set(evidence_ids)) or not set(
            evidence_ids
        ).issubset(all_evidence_ids):
            raise HookDiscoverySemanticsError(
                "Relationship evidence refs must resolve uniquely."
            )
        if len(decisive_ids) != len(set(decisive_ids)) or not set(
            decisive_ids
        ).issubset(evidence_ids):
            raise HookDiscoverySemanticsError(
                "Relationship decisive evidence refs must resolve uniquely."
            )
        expected_decisive = [
            evidence_id
            for evidence_id in evidence_ids
            if item_by_id[evidence_id].source_authority == "authoritative"
        ]
        if decisive_ids != expected_decisive:
            raise HookDiscoverySemanticsError(
                "Only authoritative evidence may be decisive."
            )
        relation = relationship["relationship"]
        if relation in {"support", "conflict"} and not decisive_ids:
            raise HookDiscoverySemanticsError(
                "Support or conflict requires authoritative decisive evidence."
            )
        if relation in {"missing", "searched_and_absent"} and decisive_ids:
            raise HookDiscoverySemanticsError(
                "Missing relationships cannot carry decisive evidence."
            )

    source_rejections = [
        {"stage": "source_admission", **dict(value)}
        for value in semantics["source_admission"]["rejected"]
    ]
    persisted_source_rejections = [
        dict(value)
        for value in pack.excluded
        if value.get("stage") == "source_admission"
    ]
    if persisted_source_rejections != source_rejections:
        raise HookDiscoverySemanticsError(
            "Source-admission exclusions do not match Hook Discovery semantics."
        )
    other_exclusions = [
        value for value in pack.excluded if value.get("stage") != "source_admission"
    ]
    projected = evidence_pack_state_from_hook_discovery(
        semantics=semantics,
        items=pack.items,
        excluded=other_exclusions,
    )
    if pack.readiness != projected["readiness"]:
        raise HookDiscoverySemanticsError("EvidencePack readiness projection drifted.")
    if pack.can_generate_patch != projected["can_generate_patch"]:
        raise HookDiscoverySemanticsError(
            "EvidencePack can_generate_patch projection drifted."
        )
    if pack.items != projected["items"]:
        raise HookDiscoverySemanticsError("EvidencePack admitted item projection drifted.")
    if pack.excluded != projected["excluded"]:
        raise HookDiscoverySemanticsError("EvidencePack exclusion projection drifted.")
    if pack.gaps != projected["gaps"] or pack.blockers != projected["blockers"]:
        raise HookDiscoverySemanticsError("EvidencePack blocker projection drifted.")

    from .models import missing_evidence_from_blockers

    if pack.missing_evidence != missing_evidence_from_blockers(pack.blockers):
        raise HookDiscoverySemanticsError(
            "EvidencePack missing_evidence projection drifted."
        )
    if pack.can_generate_patch != (
        semantics["planning_action"] == "continue"
    ):
        raise HookDiscoverySemanticsError("Planning action projection drifted.")

    _validate_persisted_sufficiency(pack)

    if pack.agent_discovery is not None:
        _validate_agent_trace_refs(pack)
    else:
        agent_relationship_fields = {
            "observation_ids",
            "limitations",
            "query_family_ids",
            "engineering_question_ids",
            "action_indexes",
        }
        if any(
            agent_relationship_fields.intersection(relationship)
            for relationship in semantics["evidence_relationships"]
        ) or any(
            (
                pack.tool_trace_summary,
                pack.model_action_trace,
                pack.observation_trace,
                pack.observation_fact_catalog,
            )
        ):
            raise HookDiscoverySemanticsError(
                "Agent-shaped Hook relationships or traces require agent_discovery."
            )


def _validate_persisted_sufficiency(pack: "EvidencePack") -> None:
    semantics = pack.hook_discovery
    assert isinstance(semantics, Mapping)
    relationships = semantics["evidence_relationships"]
    coverage = semantics["lane_coverage"]
    retrieval_reasons = [
        f"required_lane_incomplete:{value['lane']}"
        for value in coverage
        if value["status"] not in {"searched_with_results", "searched_and_absent"}
    ]
    persisted_retrieval = semantics["sufficiency"]["retrieval"]
    if pack.agent_discovery is not None:
        if persisted_retrieval["reasons"] != retrieval_reasons:
            raise HookDiscoverySemanticsError("Retrieval sufficiency reasons drifted.")
    else:
        missing_lane_reasons = [
            value
            for value in persisted_retrieval["reasons"]
            if value.startswith("required_lane_not_reported:")
        ]
        if persisted_retrieval["reasons"] != [
            *missing_lane_reasons,
            *retrieval_reasons,
        ]:
            raise HookDiscoverySemanticsError("Retrieval sufficiency reasons drifted.")
    expected_retrieval_status = (
        "sufficient" if not persisted_retrieval["reasons"] else "insufficient"
    )
    if persisted_retrieval["status"] != expected_retrieval_status:
        raise HookDiscoverySemanticsError("Retrieval sufficiency status drifted.")

    planning_blockers = [
        str(value["requirement_id"])
        for value in relationships
        if value["planning_blocking"] and value["relationship"] != "support"
    ]
    conflict_ids = [
        str(value["requirement_id"])
        for value in relationships
        if value["planning_blocking"] and value["relationship"] == "conflict"
    ]
    engineering_reasons = [
        f"planning_requirement_missing_or_conflicted:{value}"
        for value in planning_blockers
    ]
    if pack.agent_discovery is not None:
        engineering_reasons.extend(
            [*pack.unresolved_questions, *pack.missing_capabilities]
        )
    if not pack.items:
        engineering_reasons.append("no_admitted_evidence")
    if not semantics["hook_identities"]:
        engineering_reasons.append(
            "no_authoritative_relevant_complete_hook_identity"
        )
    persisted_engineering = semantics["sufficiency"]["engineering"]
    expected_engineering_status = (
        "contradictory"
        if conflict_ids
        else "sufficient"
        if not engineering_reasons
        else "insufficient"
    )
    if persisted_engineering != {
        "status": expected_engineering_status,
        "reasons": engineering_reasons,
    }:
        raise HookDiscoverySemanticsError("Engineering sufficiency projection drifted.")
    expected_planning_status = (
        "contradictory"
        if conflict_ids
        else "sufficient"
        if not persisted_retrieval["reasons"] and not engineering_reasons
        else "insufficient"
    )
    if semantics["sufficiency"]["planning"] != {
        "status": expected_planning_status,
        "reasons": [*persisted_retrieval["reasons"], *engineering_reasons],
    }:
        raise HookDiscoverySemanticsError("Planning sufficiency projection drifted.")


def _validate_resolved_finish_fact_handles(
    *,
    action: Mapping[str, Any],
    resolved_action: object,
    observation_fact_catalog: tuple[dict[str, Any], ...],
) -> None:
    finish_fields = {
        "action",
        "decision",
        "evidence_conclusions",
        "unresolved_questions",
        "missing_capabilities",
    }
    if (
        set(action) != finish_fields
        or action.get("action") != "finish"
        or not isinstance(resolved_action, Mapping)
        or set(resolved_action) != finish_fields
        or resolved_action.get("action") != "finish"
        or any(
            action.get(field) != resolved_action.get(field)
            for field in finish_fields - {"evidence_conclusions"}
        )
    ):
        raise HookDiscoverySemanticsError(
            "Resolved finish fact-handle topology is invalid."
        )
    raw_conclusions = action.get("evidence_conclusions")
    resolved_conclusions = resolved_action.get("evidence_conclusions")
    if (
        not isinstance(raw_conclusions, list)
        or not isinstance(resolved_conclusions, list)
        or len(raw_conclusions) != len(resolved_conclusions)
    ):
        raise HookDiscoverySemanticsError(
            "Resolved finish fact-handle conclusions are invalid."
        )
    facts_by_id = {
        str(fact.get("fact_id")): fact
        for fact in observation_fact_catalog
        if isinstance(fact, Mapping) and isinstance(fact.get("fact_id"), str)
    }
    expanded = False
    for raw, resolved in zip(raw_conclusions, resolved_conclusions):
        if not isinstance(raw, Mapping) or not isinstance(resolved, Mapping):
            raise HookDiscoverySemanticsError(
                "Resolved finish fact-handle conclusion is invalid."
            )
        if raw == resolved:
            continue
        fact = facts_by_id.get(str(raw.get("claim") or ""))
        if (
            raw.get("claim_status") != "observed"
            or fact is None
            or raw.get("observation_ids") != [fact.get("observation_id")]
            or set(raw) != set(resolved)
            or any(
                raw.get(field) != resolved.get(field)
                for field in set(raw) - {"claim"}
            )
            or resolved.get("claim") != fact.get("canonical_claim")
        ):
            raise HookDiscoverySemanticsError(
                "Resolved finish fact handle does not bind one frozen observation fact."
            )
        expanded = True
    if not expanded:
        raise HookDiscoverySemanticsError(
            "Resolved finish action did not expand a frozen fact handle."
        )


def _validate_agent_trace_refs(pack: "EvidencePack") -> None:
    agent = pack.agent_discovery
    if not isinstance(agent, Mapping) or agent.get("planning_status") != "ready":
        raise HookDiscoverySemanticsError(
            "Persisted Agent Hook Discovery semantics require a ready frozen plan."
        )
    search_plan = agent.get("search_plan")
    projection = agent.get("requirement_projection")
    if not isinstance(search_plan, Mapping) or not isinstance(projection, Mapping):
        raise HookDiscoverySemanticsError("Agent discovery plan is invalid.")
    observation_rows = list(pack.observation_trace)
    summary_rows = list(pack.tool_trace_summary)
    observation_ids = [str(value.get("observation_id")) for value in observation_rows]
    if len(observation_ids) != len(set(observation_ids)) or pack.trace_refs != tuple(
        observation_ids
    ):
        raise HookDiscoverySemanticsError("Observation trace refs are invalid.")
    if len(summary_rows) != len(observation_rows):
        raise HookDiscoverySemanticsError("Observation summaries are incomplete.")
    for trace, summary in zip(observation_rows, summary_rows):
        if set(trace) != {
            "observation_id",
            "tool",
            "source_id",
            "observation_sha256",
            "model_payload_bytes",
        }:
            raise HookDiscoverySemanticsError("Observation trace shape is invalid.")
        if set(summary) != {"observation_id", "tool", "source_id", "summary"}:
            raise HookDiscoverySemanticsError("Tool trace summary shape is invalid.")
        if any(
            trace.get(key) != summary.get(key)
            for key in ("observation_id", "tool", "source_id")
        ):
            raise HookDiscoverySemanticsError("Observation trace identity drifted.")
        observation_sha256 = trace.get("observation_sha256")
        if (
            not isinstance(observation_sha256, str)
            or len(observation_sha256) != 64
            or any(value not in "0123456789abcdef" for value in observation_sha256)
        ):
            raise HookDiscoverySemanticsError("Observation hash is invalid.")
        if not isinstance(trace.get("model_payload_bytes"), int) or isinstance(
            trace.get("model_payload_bytes"), bool
        ) or trace["model_payload_bytes"] < 0:
            raise HookDiscoverySemanticsError("Observation byte count is invalid.")

    requirement_ids = {
        str(value["requirement_id"])
        for value in projection["planning_blocking_questions"]
    }
    question_ids = {
        str(value["question_id"])
        for value in search_plan["engineering_questions"]
    }
    family_ids = {
        str(value["family_id"]) for value in search_plan["query_families"]
    }
    families = list(search_plan["query_families"])
    accepted_actions: list[Mapping[str, Any]] = []
    for attempt in pack.model_action_trace:
        allowed_attempt_fields = {
            "model_step",
            "origin",
            "status",
            "action",
            "action_sha256",
        }
        if attempt.get("status") == "rejected":
            allowed_attempt_fields.add("validation_error")
        has_resolved_action = "resolved_action" in attempt
        if has_resolved_action:
            allowed_attempt_fields.update(
                {"resolved_action", "resolved_action_sha256"}
            )
        if set(attempt) != allowed_attempt_fields:
            raise HookDiscoverySemanticsError("Model action trace shape is invalid.")
        if (
            not isinstance(attempt.get("model_step"), int)
            or isinstance(attempt.get("model_step"), bool)
            or attempt["model_step"] < 0
            or not isinstance(attempt.get("origin"), str)
            or not attempt["origin"]
            or attempt.get("status") not in {"accepted", "rejected"}
        ):
            raise HookDiscoverySemanticsError("Model action trace identity is invalid.")
        action = attempt.get("action")
        if not isinstance(action, Mapping):
            raise HookDiscoverySemanticsError("Model action trace action is invalid.")
        action_sha256 = hashlib.sha256(
            json.dumps(
                action,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if attempt.get("action_sha256") != action_sha256:
            raise HookDiscoverySemanticsError("Model action trace hash is invalid.")
        resolved_action = attempt.get("resolved_action")
        if has_resolved_action:
            if not isinstance(resolved_action, Mapping):
                raise HookDiscoverySemanticsError(
                    "Resolved model action trace is invalid."
                )
            resolved_sha256 = hashlib.sha256(
                json.dumps(
                    resolved_action,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if attempt.get("resolved_action_sha256") != resolved_sha256:
                raise HookDiscoverySemanticsError(
                    "Resolved model action trace hash is invalid."
                )
        raw_family_id = action.get("family_id")
        if raw_family_id is not None:
            resolved_arguments = (
                resolved_action.get("arguments")
                if isinstance(resolved_action, Mapping)
                else None
            )
            selected_families = [
                family
                for family in families
                if isinstance(family, Mapping)
                and family.get("family_id") == raw_family_id
            ]
            matched_families = (
                _families_for_resolved_action(
                    action=resolved_action,
                    families=families,
                )
                if isinstance(resolved_action, Mapping)
                else []
            )
            if (
                set(action)
                != {
                    "action",
                    "tool",
                    "source_id",
                    "family_id",
                    "derived_from_observation_ids",
                }
                or action.get("action") != "use_tool"
                or action.get("tool") != "search_dotnet_metadata"
                or not isinstance(raw_family_id, str)
                or not raw_family_id
                or action.get("derived_from_observation_ids") != []
                or not isinstance(resolved_action, Mapping)
                or set(resolved_action)
                != {
                    "action",
                    "tool",
                    "source_id",
                    "arguments",
                    "evidence_need",
                    "derived_from_observation_ids",
                    "query_family_id",
                }
                or resolved_action.get("action") != action.get("action")
                or resolved_action.get("tool") != action.get("tool")
                or resolved_action.get("source_id") != action.get("source_id")
                or resolved_action.get("query_family_id") != raw_family_id
                or not isinstance(resolved_arguments, Mapping)
                or set(resolved_arguments)
                != {"queries", "result_kinds", "limit_per_kind"}
                or resolved_arguments.get("result_kinds") != ["methods"]
                or resolved_arguments.get("limit_per_kind") != 10
                or len(selected_families) != 1
                or len(matched_families) != 1
                or matched_families[0].get("family_id") != raw_family_id
            ):
                raise HookDiscoverySemanticsError(
                    "Model family selection and resolved action topology differ."
                )
            expected_derived = _expected_family_selection_derivation(
                selected_family=selected_families[0],
                families=families,
                accepted_actions=accepted_actions,
                observation_rows=observation_rows,
            )
            if resolved_action.get("derived_from_observation_ids") != expected_derived:
                raise HookDiscoverySemanticsError(
                    "Resolved family selection observation binding is invalid."
                )
        elif has_resolved_action:
            _validate_resolved_finish_fact_handles(
                action=action,
                resolved_action=resolved_action,
                observation_fact_catalog=pack.observation_fact_catalog,
            )
        if attempt.get("status") == "accepted" and action.get("action") == "use_tool":
            accepted_actions.append(
                resolved_action if isinstance(resolved_action, Mapping) else action
            )
    if len(accepted_actions) != len(observation_rows):
        raise HookDiscoverySemanticsError("Accepted tool action trace is incomplete.")

    questions = {
        str(value["question_id"]): {
            str(requirement_id) for requirement_id in value["requirement_ids"]
        }
        for value in search_plan["engineering_questions"]
    }
    trace_binding: dict[str, dict[str, set[Any]]] = {}
    for index, (action, observation) in enumerate(
        zip(accepted_actions, observation_rows), 1
    ):
        initial_focus_question_id = search_plan.get("initial_focus_question_id")
        if (
            index == 1
            and initial_focus_question_id is not None
            and action.get("tool") != "search_dotnet_metadata"
        ):
            raise HookDiscoverySemanticsError(
                "First Agent Discovery action must be metadata for the frozen focus."
            )
        if action.get("tool") != observation.get("tool") or action.get(
            "source_id"
        ) != observation.get("source_id"):
            raise HookDiscoverySemanticsError("Action/observation identity drifted.")
        matched_families: list[Mapping[str, Any]] = []
        if action.get("tool") == "search_dotnet_metadata":
            arguments = action.get("arguments")
            if not isinstance(arguments, Mapping):
                raise HookDiscoverySemanticsError("Metadata action arguments are invalid.")
            matched_families = _families_for_resolved_action(
                action=action,
                families=families,
            )
            if len(matched_families) != 1:
                raise HookDiscoverySemanticsError(
                    "Metadata trace must bind exactly one frozen query family."
                )
            if index == 1 and initial_focus_question_id is not None and (
                initial_focus_question_id
                not in matched_families[0].get("question_ids", [])
            ):
                raise HookDiscoverySemanticsError(
                    "First metadata trace must bind the frozen initial focus."
                )
        derived = action.get("derived_from_observation_ids")
        if not isinstance(derived, list) or any(
            value not in trace_binding for value in derived
        ):
            raise HookDiscoverySemanticsError("Action derivation trace is invalid.")
        direct_question_binding = {
            str(question_id)
            for family in matched_families
            for question_id in family["question_ids"]
        }
        question_binding = set(direct_question_binding)
        family_binding = {
            str(family["family_id"]) for family in matched_families
        }
        requirement_binding = {
            requirement_id
            for question_id in question_binding
            for requirement_id in questions[question_id]
        }
        action_binding: set[Any] = {index}
        for parent_id in derived:
            parent = trace_binding[parent_id]
            question_binding.update(parent["question_ids"])
            family_binding.update(parent["family_ids"])
            requirement_binding.update(parent["requirement_ids"])
            action_binding.update(parent["action_indexes"])
        trace_binding[str(observation["observation_id"])] = {
            "question_ids": question_binding,
            "direct_question_ids": direct_question_binding,
            "family_ids": family_binding,
            "requirement_ids": requirement_binding,
            "action_indexes": action_binding,
        }
    planned_lanes = search_plan["planned_lanes"]
    coverage = pack.hook_discovery["lane_coverage"]
    if len(coverage) != len(planned_lanes):
        raise HookDiscoverySemanticsError("Lane coverage count drifted.")
    for lane, persisted in zip(planned_lanes, coverage):
        if lane.get("question_ids") is None:
            continue
        lane_questions = set(lane["question_ids"])
        matching_action_indexes = [
            index
            for index, (action, observation) in enumerate(
                zip(accepted_actions, observation_rows), 1
            )
            if action.get("tool") == lane.get("tool")
            and action.get("source_id") in lane.get("source_ids", [])
            and lane_questions.intersection(
                trace_binding[str(observation["observation_id"])][
                    "direct_question_ids"
                    if action.get("tool") == "search_dotnet_metadata"
                    else "question_ids"
                ]
            )
        ]
        actual_source_ids = [
            source_id
            for source_id in lane.get("source_ids", [])
            if any(
                accepted_actions[index - 1].get("source_id") == source_id
                for index in matching_action_indexes
            )
        ]
        if persisted["lane"] != lane.get("lane") or persisted["scope"] != {
            "tool": lane.get("tool"),
            "source_ids": actual_source_ids,
            "action_count": len(matching_action_indexes),
        }:
            raise HookDiscoverySemanticsError("Lane coverage binding drifted.")
        if not matching_action_indexes and (
            persisted["status"] != "not_searched" or persisted["hit_count"] != 0
        ):
            raise HookDiscoverySemanticsError(
                "Unexecuted lane must remain not_searched."
            )
    for relationship in pack.hook_discovery["evidence_relationships"]:
        if relationship["requirement_id"] not in requirement_ids:
            raise HookDiscoverySemanticsError("Relationship requirement ref is invalid.")
        relationship_observations = relationship["observation_ids"]
        if not set(relationship_observations).issubset(observation_ids):
            raise HookDiscoverySemanticsError("Relationship observation ref is invalid.")
        if not set(relationship["query_family_ids"]).issubset(family_ids):
            raise HookDiscoverySemanticsError("Relationship query-family ref is invalid.")
        if not set(relationship["engineering_question_ids"]).issubset(question_ids):
            raise HookDiscoverySemanticsError(
                "Relationship engineering-question ref is invalid."
            )
        if any(index > len(accepted_actions) for index in relationship["action_indexes"]):
            raise HookDiscoverySemanticsError("Relationship action ref is invalid.")
        bound_rows = [trace_binding[value] for value in relationship_observations]
        if any(
            relationship["requirement_id"] not in row["requirement_ids"]
            for row in bound_rows
        ):
            raise HookDiscoverySemanticsError(
                "Relationship observation is not bound to its planning requirement."
            )
        expected_question_ids = sorted(
            {
                str(value)
                for row in bound_rows
                for value in row["question_ids"]
                if relationship["requirement_id"] in questions[str(value)]
            }
        )
        expected_family_ids = sorted(
            {
                str(value)
                for row in bound_rows
                for value in row["family_ids"]
            }
        )
        expected_action_indexes = sorted(
            {
                int(value)
                for row in bound_rows
                for value in row["action_indexes"]
            }
        )
        if relationship["engineering_question_ids"] != expected_question_ids:
            raise HookDiscoverySemanticsError(
                "Relationship engineering-question binding drifted."
            )
        if relationship["query_family_ids"] != expected_family_ids:
            raise HookDiscoverySemanticsError("Relationship query-family binding drifted.")
        if relationship["action_indexes"] != expected_action_indexes:
            raise HookDiscoverySemanticsError("Relationship action binding drifted.")

    observation_by_id = {
        str(value["observation_id"]): value for value in observation_rows
    }
    from .discovery_contract import observation_fact_integrity_valid

    for fact in pack.observation_fact_catalog:
        observation_id = fact.get("observation_id")
        observation = observation_by_id.get(str(observation_id))
        if observation is None or not observation_fact_integrity_valid(
            fact=fact,
            observation_tool=str(observation["tool"]),
            observation_source_id=str(observation["source_id"]),
            observation_sha256=str(observation["observation_sha256"]),
        ):
            raise HookDiscoverySemanticsError("Observation fact ref is invalid.")
    for rows in (pack.evidence_conclusions, pack.verified_findings):
        for value in rows:
            refs = value.get("observation_ids", [])
            if not isinstance(refs, list) or not set(refs).issubset(observation_ids):
                raise HookDiscoverySemanticsError(
                    "Evidence conclusion observation ref is invalid."
                )


def _admit_items(
    items: tuple[EvidenceItem, ...],
) -> tuple[list[EvidenceItem], list[dict[str, str]]]:
    admitted: list[EvidenceItem] = []
    rejected: list[dict[str, str]] = []
    for item in items:
        reasons: list[str] = []
        if item.authority != DETERMINISTIC_EVIDENCE_AUTHORITY:
            reasons.append("non_deterministic_evidence_authority")
        if item.source_authority not in _SOURCE_AUTHORITIES:
            reasons.append("source_authority_not_declared")
        if not any((item.source_hash, item.file_hash, item.doc_hash)):
            reasons.append("content_identity_not_bound")
        if reasons:
            rejected.append(
                {
                    "evidence_id": item.evidence_id,
                    "reason": ",".join(reasons),
                }
            )
        else:
            admitted.append(item)
    return admitted, rejected


def _matches(item: EvidenceItem, match: Mapping[str, Any]) -> bool:
    allowed_keys = {
        "evidence_ids",
        "source_types",
        "source_paths",
        "source_authorities",
        "retrieval_methods",
        "symbols",
        "usage",
    }
    unknown = sorted(set(match) - allowed_keys)
    if unknown:
        raise HookDiscoverySemanticsError(
            f"Unsupported evidence match fields: {', '.join(unknown)}"
        )
    checks = {
        "evidence_ids": item.evidence_id,
        "source_types": item.source_type,
        "source_paths": item.source_path,
        "source_authorities": item.source_authority,
        "retrieval_methods": item.retrieval_method,
        "symbols": item.symbol,
    }
    for key, actual in checks.items():
        if key in match:
            values = match[key]
            allow_empty = key == "evidence_ids"
            if not isinstance(values, list) or (not values and not allow_empty) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise HookDiscoverySemanticsError(
                    f"{key} must be a non-empty string array."
                )
            if actual not in values:
                return False
    if "usage" in match:
        usage = match["usage"]
        if not isinstance(usage, str) or not usage:
            raise HookDiscoverySemanticsError("usage must be a non-empty string.")
        if item.usage != usage:
            return False
    return True


def _normalize_lane_coverage(
    values: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if set(value) != {"lane", "status", "hit_count", "scope", "failure"}:
            raise HookDiscoverySemanticsError("Lane coverage shape is invalid.")
        lane = _required_string(value, "lane")
        if lane in seen:
            raise HookDiscoverySemanticsError(f"Duplicate lane coverage: {lane}")
        seen.add(lane)
        status = _required_string(value, "status")
        if status not in _LANE_STATUSES:
            raise HookDiscoverySemanticsError(
                f"Unsupported lane status for {lane}: {status}"
            )
        hit_count = value.get("hit_count")
        if not isinstance(hit_count, int) or isinstance(hit_count, bool) or hit_count < 0:
            raise HookDiscoverySemanticsError(
                f"hit_count must be a non-negative integer for {lane}."
            )
        scope = value.get("scope")
        if not isinstance(scope, Mapping):
            raise HookDiscoverySemanticsError(f"scope must be an object for {lane}.")
        if set(scope) == {"source_ids"}:
            source_ids = scope.get("source_ids")
            if not isinstance(source_ids, list) or not all(
                isinstance(item, str) and item for item in source_ids
            ):
                raise HookDiscoverySemanticsError(
                    f"scope.source_ids must be a string array for {lane}."
                )
        elif set(scope) == {"tool", "source_ids", "action_count"}:
            _required_string(scope, "tool")
            source_ids = scope.get("source_ids")
            action_count = scope.get("action_count")
            if not isinstance(source_ids, list) or not all(
                isinstance(item, str) and item for item in source_ids
            ):
                raise HookDiscoverySemanticsError(
                    f"scope.source_ids must be a string array for {lane}."
                )
            if (
                not isinstance(action_count, int)
                or isinstance(action_count, bool)
                or action_count < 0
            ):
                raise HookDiscoverySemanticsError(
                    f"scope.action_count must be non-negative for {lane}."
                )
        else:
            raise HookDiscoverySemanticsError(f"scope shape is invalid for {lane}.")
        failure = value.get("failure")
        if failure is not None and (not isinstance(failure, str) or not failure):
            raise HookDiscoverySemanticsError(
                f"failure must be null or a non-empty string for {lane}."
            )
        normalized.append(
            {
                "lane": lane,
                "status": status,
                "hit_count": hit_count,
                "scope": dict(scope),
                "failure": failure,
            }
        )
    return normalized


def _has_complete_hook_identity(item: EvidenceItem) -> bool:
    typed_identity = bool(
        item.parameter_types is not None and item.return_type and item.method_kind
    )
    metadata_identity = bool(
        item.module_mvid and item.metadata_token and item.signature_blob
    )
    return bool(
        item.declaring_type
        and item.method_name
        and (typed_identity or metadata_identity)
    )


def _hook_identity_from_item(item: EvidenceItem) -> dict[str, Any]:
    source_content_hash = item.source_hash or item.file_hash or item.doc_hash
    identity = {
        "evidence_id": item.evidence_id,
        "source_path": item.source_path,
        "source_content_hash": source_content_hash,
        "declaring_type": item.declaring_type,
        "method_name": item.method_name,
    }
    if item.module_mvid is not None:
        identity["module_mvid"] = item.module_mvid
    if item.metadata_token is not None:
        identity["metadata_token"] = item.metadata_token
    if item.signature_blob is not None:
        identity["signature_blob"] = item.signature_blob
    if item.parameter_types is not None:
        identity["parameter_types"] = list(item.parameter_types)
    if item.return_type is not None:
        identity["return_type"] = item.return_type
    if item.method_kind is not None:
        identity["method_kind"] = item.method_kind
    return identity


def _normalize_persisted_hook_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    evidence_id = _required_string(value, "evidence_id")
    normalized = {
        "evidence_id": evidence_id,
        "source_path": _required_string(value, "source_path"),
        "source_content_hash": _required_string(value, "source_content_hash"),
        "declaring_type": _required_string(value, "declaring_type"),
        "method_name": _required_string(value, "method_name"),
    }
    metadata_fields = ("module_mvid", "metadata_token", "signature_blob")
    typed_fields = ("parameter_types", "return_type", "method_kind")
    has_metadata_identity = all(value.get(key) is not None for key in metadata_fields)
    has_typed_identity = all(value.get(key) is not None for key in typed_fields)
    if not has_metadata_identity and not has_typed_identity:
        raise HookDiscoverySemanticsError(
            f"Hook identity {evidence_id} lacks both metadata and typed identity."
        )
    if has_metadata_identity:
        for key in metadata_fields:
            normalized[key] = _required_string(value, key)
    if has_typed_identity:
        parameter_types = value.get("parameter_types")
        if not isinstance(parameter_types, list) or not all(
            isinstance(item, str) and item for item in parameter_types
        ):
            raise HookDiscoverySemanticsError(
                f"parameter_types must be a string array for {evidence_id}."
            )
        normalized["parameter_types"] = list(parameter_types)
        normalized["return_type"] = _required_string(value, "return_type")
        normalized["method_kind"] = _required_string(value, "method_kind")
    return normalized


def _require_exact_value(
    value: Mapping[str, Any],
    key: str,
    expected: str,
) -> None:
    actual = value.get(key)
    if actual != expected:
        raise HookDiscoverySemanticsError(
            f"{key} must be exactly {expected!r}; received {actual!r}."
        )


def _required_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise HookDiscoverySemanticsError(f"{key} must be a non-empty string.")
    return result


def _string_list(
    value: Mapping[str, Any],
    key: str,
    *,
    allow_empty: bool,
) -> list[str]:
    result = value.get(key)
    if not isinstance(result, list) or not all(
        isinstance(item, str) and item for item in result
    ):
        raise HookDiscoverySemanticsError(f"{key} must be a string array.")
    if not allow_empty and not result:
        raise HookDiscoverySemanticsError(f"{key} must not be empty.")
    return list(result)


def _object_list(
    value: Mapping[str, Any],
    key: str,
    *,
    allow_empty: bool,
) -> list[Mapping[str, Any]]:
    result = value.get(key)
    if not isinstance(result, list) or not all(isinstance(item, Mapping) for item in result):
        raise HookDiscoverySemanticsError(f"{key} must be an object array.")
    if not allow_empty and not result:
        raise HookDiscoverySemanticsError(f"{key} must not be empty.")
    return list(result)
