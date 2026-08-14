from __future__ import annotations

import src.mod_agent.evidence as evidence_module
import pytest

from src.mod_agent.evidence import (
    EvidenceItem,
    EvidencePack,
    EvidenceReadinessClassifier,
    EvidenceRequest,
    HookDiscoverySemanticsError,
    ToolObservation,
    build_agent_discovery_semantics,
    build_hook_discovery_semantics,
)


def _item(
    evidence_id: str,
    *,
    symbol: str,
    source_authority: str = "authoritative",
    authority: str = "mod_agent_deterministic",
    source_hash: str | None = "A" * 64,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type="decompiled_api",
        source_path="interop/Modules-ASM.dll",
        symbol=symbol,
        span={"start_line": 1, "end_line": 1},
        retrieval_method="current_interop_metadata_il_read",
        score=1.0,
        claim_supported=f"Bound physical facts for {symbol}.",
        excerpt="{}",
        source_hash=source_hash,
        usage="hook_target",
        declaring_type=symbol.rsplit(".", 1)[0],
        method_name=symbol.rsplit(".", 1)[1],
        parameter_types=(),
        return_type="System.Void",
        method_kind="instance_method",
        authority=authority,
        source_authority=source_authority,
    )


def _requirement(*, required_lanes: list[str]) -> dict[str, object]:
    return {
        "required": True,
        "reason": "gameplay_method_interception",
        "request_type": "hook_discovery",
        "required_lanes": required_lanes,
        "evidence_requirements": [
            {
                "requirement_id": "bound_activate_state",
                "description": "Bind the exact current method identity.",
                "relationship": "support",
                "planning_blocking": True,
                "match": {"symbols": ["ES_Hitreact.ActivateState"]},
            }
        ],
        "limitations": ["Final Runtime correctness remains unverified."],
    }


def _coverage(lane: str, status: str, hit_count: int) -> dict[str, object]:
    return {
        "lane": lane,
        "status": status,
        "hit_count": hit_count,
        "scope": {"source_ids": ["current_interop"]},
        "failure": None,
    }


def test_hook_discovery_persists_three_layer_continue_semantics() -> None:
    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="Observe a bound reaction method.",
            hook_requirement=_requirement(required_lanes=["metadata_il"]),
        ),
        items=[_item("ev_hitreact", symbol="ES_Hitreact.ActivateState")],
        lane_coverage=(_coverage("metadata_il", "searched_with_results", 1),),
    )

    semantics = pack.hook_discovery
    assert semantics is not None
    assert semantics["schema_version"] == "hook_discovery_evidence_v2"
    assert semantics["source_admission"]["admitted_evidence_ids"] == [
        "ev_hitreact"
    ]
    assert semantics["hook_identities"] == [
        {
            "evidence_id": "ev_hitreact",
            "source_path": "interop/Modules-ASM.dll",
            "source_content_hash": "A" * 64,
            "declaring_type": "ES_Hitreact",
            "method_name": "ActivateState",
            "parameter_types": [],
            "return_type": "System.Void",
            "method_kind": "instance_method",
        }
    ]
    assert semantics["evidence_relationships"] == [
        {
            "requirement_id": "bound_activate_state",
            "description": "Bind the exact current method identity.",
            "relationship": "support",
            "evidence_ids": ["ev_hitreact"],
            "decisive_evidence_ids": ["ev_hitreact"],
            "planning_blocking": True,
        }
    ]
    assert semantics["sufficiency"] == {
        "retrieval": {"status": "sufficient", "reasons": []},
        "engineering": {"status": "sufficient", "reasons": []},
        "planning": {"status": "sufficient", "reasons": []},
    }
    assert semantics["planning_action"] == "continue"
    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    payload = pack.to_artifact_payload()
    assert payload["hook_discovery"] == semantics
    assert "agent_discovery" not in payload
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload


def test_hook_discovery_blocks_missing_planning_fact_without_promoting_hits() -> None:
    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="Find a surface-relative movement integration.",
            hook_requirement=_requirement(required_lanes=["metadata_il", "runtime"]),
        ),
        items=[_item("ev_other", symbol="ES_PathMove.UpdateRotation")],
        lane_coverage=(
            _coverage("metadata_il", "searched_with_results", 1),
            _coverage("runtime", "not_searched", 0),
        ),
    )

    semantics = pack.hook_discovery
    assert semantics is not None
    assert semantics["sufficiency"]["retrieval"] == {
        "status": "insufficient",
        "reasons": ["required_lane_incomplete:runtime"],
    }
    assert semantics["evidence_relationships"][0]["relationship"] == "missing"
    assert semantics["sufficiency"]["planning"]["status"] == "insufficient"
    assert semantics["planning_action"] == "block"
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False


def test_hook_discovery_rejects_unbound_or_auxiliary_evidence() -> None:
    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="Observe a bound reaction method.",
            hook_requirement=_requirement(required_lanes=["metadata_il"]),
        ),
        items=[
            _item(
                "ev_unbound",
                symbol="ES_Hitreact.ActivateState",
                authority="legacy_rag_auxiliary",
                source_hash=None,
            )
        ],
        lane_coverage=(_coverage("metadata_il", "searched_with_results", 1),),
    )

    semantics = pack.hook_discovery
    assert semantics is not None
    assert semantics["source_admission"]["admitted_evidence_ids"] == []
    assert semantics["source_admission"]["rejected"] == [
        {
            "evidence_id": "ev_unbound",
            "reason": (
                "non_deterministic_evidence_authority,content_identity_not_bound"
            ),
        }
    ]
    assert semantics["planning_action"] == "block"


def test_legacy_evidence_item_payload_bytes_do_not_gain_new_null_field() -> None:
    payload = _item(
        "ev_legacy",
        symbol="ES_Hitreact.ActivateState",
    ).to_dict()
    payload.pop("source_authority")
    legacy_item = EvidenceItem(
        evidence_id=payload["evidence_id"],
        source_type=payload["source_type"],
        source_path=payload["source_path"],
        symbol=payload["symbol"],
        span=payload["span"],
        retrieval_method=payload["retrieval_method"],
        score=payload["score"],
        claim_supported=payload["claim_supported"],
        excerpt=payload["excerpt"],
    )
    assert "source_authority" not in legacy_item.to_dict()


def test_hook_discovery_rejects_unknown_match_fields() -> None:
    requirement = _requirement(required_lanes=["metadata_il"])
    requirement["evidence_requirements"][0]["match"] = {"unknown": ["value"]}
    with pytest.raises(HookDiscoverySemanticsError, match="Unsupported evidence match"):
        EvidenceReadinessClassifier().classify(
            request=EvidenceRequest(query="query", hook_requirement=requirement),
            items=[_item("ev", symbol="ES_Hitreact.ActivateState")],
            lane_coverage=(_coverage("metadata_il", "searched_with_results", 1),),
        )


def test_bound_il_report_has_no_public_authority_projection_helper() -> None:
    assert not hasattr(evidence_module, "evidence_items_from_bound_il_report")


def test_reviewed_empty_evidence_binding_stays_missing() -> None:
    requirement = _requirement(required_lanes=["metadata_il"])
    requirement["evidence_requirements"][0]["match"] = {"evidence_ids": []}
    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(query="query", hook_requirement=requirement),
        items=[_item("ev", symbol="ES_Hitreact.ActivateState")],
        lane_coverage=(_coverage("metadata_il", "searched_with_results", 1),),
    )

    assert pack.hook_discovery is not None
    assert pack.hook_discovery["evidence_relationships"][0]["relationship"] == "missing"
    assert pack.hook_discovery["planning_action"] == "block"


@pytest.mark.parametrize("source_authority", ["supporting", "lead"])
def test_non_authoritative_source_cannot_close_planning_requirement(
    source_authority: str,
) -> None:
    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="Observe a bound reaction method.",
            hook_requirement=_requirement(required_lanes=["metadata_il"]),
        ),
        items=[
            _item(
                "ev_non_decisive",
                symbol="ES_Hitreact.ActivateState",
                source_authority=source_authority,
            )
        ],
        lane_coverage=(_coverage("metadata_il", "searched_with_results", 1),),
    )

    semantics = pack.hook_discovery
    assert semantics is not None
    assert semantics["source_admission"]["admitted_evidence_ids"] == [
        "ev_non_decisive"
    ]
    assert semantics["evidence_relationships"][0]["relationship"] == "missing"
    assert semantics["evidence_relationships"][0]["decisive_evidence_ids"] == []
    assert semantics["hook_identities"] == []
    assert semantics["planning_action"] == "block"
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False


def test_invalid_source_authority_is_rejected_without_rank_promotion() -> None:
    item = _item("ev_invalid", symbol="ES_Hitreact.ActivateState")
    object.__setattr__(item, "source_authority", "invalid")
    object.__setattr__(item, "score", 999.0)

    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query="Observe a bound reaction method.",
            hook_requirement=_requirement(required_lanes=["metadata_il"]),
        ),
        items=[item],
        lane_coverage=(_coverage("metadata_il", "searched_with_results", 1),),
    )

    semantics = pack.hook_discovery
    assert semantics is not None
    assert semantics["source_admission"]["admitted_evidence_ids"] == []
    assert semantics["source_admission"]["rejected"] == [{
        "evidence_id": "ev_invalid",
        "reason": "source_authority_not_declared",
    }]
    assert semantics["planning_action"] == "block"


def test_authoritative_conflict_is_contradictory_and_blocks_top_level() -> None:
    requirement = _requirement(required_lanes=["metadata_il"])
    requirement["evidence_requirements"][0]["relationship"] = "conflict"
    pack = EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(query="query", hook_requirement=requirement),
        items=[_item("ev_conflict", symbol="ES_Hitreact.ActivateState")],
        lane_coverage=(_coverage("metadata_il", "searched_with_results", 1),),
    )

    semantics = pack.hook_discovery
    assert semantics is not None
    assert semantics["evidence_relationships"][0]["relationship"] == "conflict"
    assert semantics["sufficiency"]["engineering"]["status"] == "contradictory"
    assert semantics["sufficiency"]["planning"]["status"] == "contradictory"
    assert semantics["planning_action"] == "block"
    assert pack.readiness == "contradictory"
    assert pack.can_generate_patch is False


def test_legacy_and_agent_normalization_delegate_to_same_semantic_core() -> None:
    item = _item("ev_shared", symbol="ES_Hitreact.ActivateState")
    legacy_requirement = _requirement(
        required_lanes=["managed_metadata_discovery", "exact_il_verification"]
    )
    normalized_legacy = build_hook_discovery_semantics(
        hook_requirement=legacy_requirement,
        items=(item,),
        lane_coverage=(
            _coverage("managed_metadata_discovery", "searched_with_results", 1),
            _coverage("exact_il_verification", "searched_with_results", 1),
        ),
    )
    metadata_observation = ToolObservation(
        observation_id="obs-001",
        tool="search_dotnet_metadata",
        source_id="current_interop",
        summary="One method identity was observed.",
        data={"methods": [{"candidate_ref": "ref-1"}]},
    )
    il_observation = ToolObservation(
        observation_id="obs-002",
        tool="inspect_method_il",
        source_id="current_interop",
        summary="Exact IL was observed.",
        data={"symbol": "ES_Hitreact.ActivateState"},
        evidence_items=(item,),
    )
    normalized_agent = build_agent_discovery_semantics(
        agent_discovery={
            "requirement_projection": {
                "planning_blocking_questions": [{
                    "requirement_id": "bound_activate_state",
                    "question": "Bind the exact current method identity.",
                }],
            },
            "search_plan": {
                "engineering_questions": [{
                    "question_id": "question-bind-method",
                    "question": "Bind the exact current method identity.",
                    "requirement_ids": ["bound_activate_state"],
                }],
                "query_families": [{
                    "family_id": "family-activate-state",
                    "queries": ["ActivateState"],
                    "evidence_need": "Bind the exact current method identity.",
                    "source_ids": ["current_interop"],
                    "tool": "search_dotnet_metadata",
                    "question_ids": ["question-bind-method"],
                }],
                "planned_lanes": [
                    {
                        "lane": "managed_metadata_discovery",
                        "tool": "search_dotnet_metadata",
                        "source_ids": ["current_interop"],
                    },
                    {
                        "lane": "exact_il_verification",
                        "tool": "inspect_method_il",
                        "source_ids": ["current_interop"],
                    },
                ],
            },
        },
        items=(item,),
        actions=(
            {
                "tool": "search_dotnet_metadata",
                "source_id": "current_interop",
                "arguments": {"queries": ["ActivateState"]},
                "evidence_need": "Bind the exact current method identity.",
                "derived_from_observation_ids": [],
            },
            {
                "tool": "inspect_method_il",
                "source_id": "current_interop",
                "arguments": {"candidate_ref": "ref-1"},
                "evidence_need": "Verify exact IL.",
                "derived_from_observation_ids": ["obs-001"],
            },
        ),
        observations=(metadata_observation, il_observation),
        finish={
            "decision": "sufficient_for_proposal",
            "evidence_conclusions": [{
                "claim": "The observed method supports the planning requirement.",
                "claim_status": "inferred",
                "observation_ids": ["obs-002"],
                "limitations": ["Final Runtime behavior remains unverified."],
                "requirement_ids": ["bound_activate_state"],
                "relationship": "support",
            }],
            "unresolved_questions": [],
            "missing_capabilities": [],
        },
    )

    for field in (
        "source_admission",
        "hook_identities",
        "sufficiency",
        "planning_action",
    ):
        assert normalized_legacy[field] == normalized_agent[field]


def _agent_semantic_input() -> tuple[
    dict[str, object],
    EvidenceItem,
    tuple[dict[str, object], ...],
    tuple[ToolObservation, ...],
]:
    item = _item("ev_ordered", symbol="ES_Hitreact.ActivateState")
    agent_discovery = {
        "requirement_projection": {
            "planning_blocking_questions": [{
                "requirement_id": "req-primary",
                "question": "Bind the exact current method identity.",
            }],
        },
        "search_plan": {
            "engineering_questions": [{
                "question_id": "question-primary",
                "question": "Bind the exact current method identity.",
                "requirement_ids": ["req-primary"],
            }],
            "query_families": [{
                "family_id": "family-primary",
                "queries": ["ActivateState"],
                "evidence_need": "Bind the exact current method identity.",
                "source_ids": ["current-interop"],
                "tool": "search_dotnet_metadata",
                "question_ids": ["question-primary"],
            }],
            "planned_lanes": [
                {
                    "lane": "managed_metadata_discovery",
                    "tool": "search_dotnet_metadata",
                    "source_ids": ["current-interop"],
                },
                {
                    "lane": "exact_il_verification",
                    "tool": "inspect_method_il",
                    "source_ids": ["current-interop"],
                },
            ],
        },
    }
    actions = (
        {
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": {"queries": ["ActivateState"]},
            "evidence_need": "Bind the exact current method identity.",
            "derived_from_observation_ids": [],
        },
        {
            "tool": "inspect_method_il",
            "source_id": "current-interop",
            "arguments": {"candidate_ref": "ref-1"},
            "evidence_need": "Verify exact IL.",
            "derived_from_observation_ids": ["obs-001"],
        },
    )
    observations = (
        ToolObservation(
            observation_id="obs-001",
            tool="search_dotnet_metadata",
            source_id="current-interop",
            summary="One method identity was observed.",
            data={"methods": [{"candidate_ref": "ref-1"}]},
        ),
        ToolObservation(
            observation_id="obs-002",
            tool="inspect_method_il",
            source_id="current-interop",
            summary="Exact IL was observed.",
            data={"symbol": "ES_Hitreact.ActivateState"},
            evidence_items=(item,),
        ),
    )
    return agent_discovery, item, actions, observations


def _agent_semantics_for_conclusions(
    conclusions: list[dict[str, object]],
) -> dict[str, object]:
    agent_discovery, item, actions, observations = _agent_semantic_input()
    return build_agent_discovery_semantics(
        agent_discovery=agent_discovery,
        items=(item,),
        actions=actions,
        observations=observations,
        finish={
            "decision": (
                "conflicting_evidence"
                if any(value["relationship"] == "conflict" for value in conclusions)
                else "sufficient_for_proposal"
            ),
            "evidence_conclusions": conclusions,
            "unresolved_questions": [],
            "missing_capabilities": [],
        },
    )


def test_agent_relationship_support_aggregation_is_order_independent() -> None:
    no_decisive_evidence = {
        "observation_ids": ["obs-001"],
        "limitations": ["Metadata discovery alone is not decisive."],
        "requirement_ids": ["req-primary"],
        "relationship": "support",
    }
    decisive_evidence = {
        "observation_ids": ["obs-002"],
        "limitations": [],
        "requirement_ids": ["req-primary"],
        "relationship": "support",
    }

    forward = _agent_semantics_for_conclusions(
        [no_decisive_evidence, decisive_evidence]
    )
    reverse = _agent_semantics_for_conclusions(
        [decisive_evidence, no_decisive_evidence]
    )

    assert forward == reverse
    assert forward["evidence_relationships"][0]["relationship"] == "support"
    assert forward["evidence_relationships"][0]["decisive_evidence_ids"] == [
        "ev_ordered"
    ]
    assert forward["planning_action"] == "continue"


def test_agent_relationship_conflict_precedes_support_independent_of_order() -> None:
    support = {
        "observation_ids": ["obs-002"],
        "limitations": [],
        "requirement_ids": ["req-primary"],
        "relationship": "support",
    }
    conflict = {
        "observation_ids": ["obs-002"],
        "limitations": ["The same physical evidence contradicts the requirement."],
        "requirement_ids": ["req-primary"],
        "relationship": "conflict",
    }

    support_first = _agent_semantics_for_conclusions([support, conflict])
    conflict_first = _agent_semantics_for_conclusions([conflict, support])

    assert support_first == conflict_first
    assert support_first["evidence_relationships"][0]["relationship"] == "conflict"
    assert support_first["sufficiency"]["engineering"]["status"] == "contradictory"
    assert support_first["sufficiency"]["planning"]["status"] == "contradictory"
    assert support_first["planning_action"] == "block"


def test_agent_semantics_rejects_ambiguous_observation_family_binding() -> None:
    agent_discovery, item, actions, observations = _agent_semantic_input()
    search_plan = agent_discovery["search_plan"]
    assert isinstance(search_plan, dict)
    search_plan["engineering_questions"].append({
        "question_id": "question-secondary",
        "question": "Bind another requirement.",
        "requirement_ids": ["req-secondary"],
    })
    search_plan["query_families"].append({
        "family_id": "family-secondary",
        "queries": ["ActivateState"],
        "evidence_need": "Bind the exact current method identity.",
        "source_ids": ["current-interop"],
        "tool": "search_dotnet_metadata",
        "question_ids": ["question-secondary"],
    })

    with pytest.raises(
        HookDiscoverySemanticsError,
        match="exactly one frozen query family",
    ):
        build_agent_discovery_semantics(
            agent_discovery=agent_discovery,
            items=(item,),
            actions=actions,
            observations=observations,
            finish={
                "decision": "sufficient_for_proposal",
                "evidence_conclusions": [{
                    "observation_ids": ["obs-002"],
                    "limitations": [],
                    "requirement_ids": ["req-primary"],
                    "relationship": "support",
                }],
                "unresolved_questions": [],
                "missing_capabilities": [],
            },
        )
