"""Tests for Phase E deterministic planning."""

from __future__ import annotations

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION
from src.mod_agent.planning import (
    FeatureSpecBuilder,
    ImplementationPlanner,
    ModPlanningBriefBuilder,
    RequestPlanner,
)


def _identity_schema_payload() -> dict[str, object]:
    return {
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "identity_field_mapping": dict(IDENTITY_FIELD_MAPPING),
    }


def _authoritative_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "evidence_id": "ev_001",
        "source_type": "target_source",
        "source_path": "mods/BetterHitFeedback/Plugin.cs",
        "symbol": "Load",
        "authority": "mod_agent_deterministic",
        "chunk_id": "chunk_001",
        "document_id": "doc_001",
        "source_ref": "doc_001",
        "source_hash": "file_hash_001",
        "file_hash": "file_hash_001",
        "doc_hash": "doc_hash_001",
    }
    item.update(overrides)
    return item


def test_request_planner_blocks_ambiguous_request() -> None:
    plan = RequestPlanner().plan("fix it")

    assert plan.blocked is True
    assert plan.route == "blocked_ambiguous"
    assert plan.risk_level == "blocked"
    assert plan.uncertainties[0].uncertainty_id == "ambiguous_user_request"


def test_request_planner_classifies_runtime_feature_as_high_risk() -> None:
    plan = RequestPlanner().plan(
        "make enemies glow when damaged in BetterHitFeedback"
    )

    assert plan.blocked is False
    assert plan.route == "standard_feature"
    assert plan.risk_level == "high"
    assert plan.target_mod == "BetterHitFeedback"
    assert plan.requires_hook_evidence is True
    assert plan.requires_runtime_evidence is True


def test_feature_spec_builder_creates_verifiable_contract() -> None:
    plan = RequestPlanner().plan(
        "default config EnableLogging false",
        target_mod="BetterHitFeedback",
    )

    spec = FeatureSpecBuilder().build(plan)

    assert spec.blocked is False
    assert spec.feature_id == plan.feature_id
    assert spec.target_behavior == plan.user_request
    assert "config or text evidence" in spec.evidence_requirements
    assert spec.acceptance_criteria
    assert spec.non_goals


def test_feature_spec_builder_preserves_blocking_uncertainty() -> None:
    plan = RequestPlanner().plan("test")

    spec = FeatureSpecBuilder().build(plan)

    assert spec.blocked is True
    assert spec.blockers[0]["code"] == "AMBIGUOUS_USER_REQUEST"


def test_mod_planning_brief_classifies_config_only_request() -> None:
    plan = RequestPlanner().plan(
        "default config EnableLogging false",
        target_mod="BetterHitFeedback",
    )

    brief = ModPlanningBriefBuilder().build(plan, target_game="GTFO")
    payload = brief.to_artifact_payload()

    assert payload["decision"] == "ready_for_feature_spec"
    assert payload["request_type"]["value"] == "config-only"
    assert payload["user_intent"]["target_game"] == "GTFO"
    assert payload["user_intent"]["target_mod"] == "BetterHitFeedback"
    assert "config schema or settings reference" in (
        payload["planning_options"][0]["required_evidence"]
    )
    assert payload["next_action"] == "feature_spec"
    assert payload["blocked"] is False


def test_mod_planning_brief_classifies_ui_feedback_request() -> None:
    plan = RequestPlanner().plan(
        "show reload progress in HUD",
        target_mod="BetterHitFeedback",
    )

    payload = ModPlanningBriefBuilder().build(plan).to_artifact_payload()

    assert payload["request_type"]["value"] == "UI feedback"
    assert "game_profile" in payload["knowledge_query_plan"]["source_types"]
    assert "UI or feedback surface evidence" in (
        payload["planning_options"][0]["required_evidence"]
    )
    assert payload["handoff"]["runtime_verification_expectations"] == [
        "compile or static validation",
        "user-visible feedback evidence",
    ]


def test_mod_planning_brief_classifies_hook_required_request() -> None:
    plan = RequestPlanner().plan(
        "hook enemy damage method for BetterHitFeedback"
    )

    payload = ModPlanningBriefBuilder().build(plan).to_artifact_payload()

    assert payload["request_type"]["value"] == "hook-required"
    assert payload["planning_options"][0]["hook_likelihood"] == "high"
    assert "symbol_search" in payload["knowledge_query_plan"]["source_types"]
    assert "target symbol evidence" in payload["planning_options"][0]["required_evidence"]
    assert payload["handoff"]["hook_discovery_guidance"] == (
        "Run hook discovery before implementation planning."
    )


def test_mod_planning_brief_blocks_unclear_request() -> None:
    plan = RequestPlanner().plan("fix it")

    payload = ModPlanningBriefBuilder().build(plan).to_artifact_payload()

    assert payload["decision"] == "needs_clarification"
    assert payload["request_type"]["value"] == "unknown / needs evidence"
    assert payload["selected_plan"]["scope"] == ""
    assert payload["next_action"] == "ask user"
    assert payload["blocked"] is True
    assert payload["blockers"][0]["code"] == "AMBIGUOUS_USER_REQUEST"


def test_implementation_plan_blocks_when_evidence_is_not_sufficient() -> None:
    plan = RequestPlanner().plan("make enemies glow when damaged")
    spec = FeatureSpecBuilder().build(plan)
    evidence_pack = {
        "readiness": "partial",
        "can_generate_patch": False,
        "gaps": ["No safe hook found."],
        "blockers": [{"code": "INSUFFICIENT_HOOK_EVIDENCE"}],
    }

    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack=evidence_pack,
    )

    assert implementation.blocking is True
    assert implementation.open_questions == ("No safe hook found.",)
    assert implementation.proposed_changes == ()


def test_implementation_plan_binds_every_change_to_evidence() -> None:
    plan = RequestPlanner().plan("make Load enable diagnostics")
    spec = FeatureSpecBuilder().build(plan)
    evidence_pack = {
        "readiness": "sufficient",
        "can_generate_patch": True,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": True,
        **_identity_schema_payload(),
        "items": [_authoritative_item()],
    }

    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack=evidence_pack,
    )

    assert implementation.blocking is False
    assert implementation.evidence_source_paths == ("mods/BetterHitFeedback/Plugin.cs",)
    assert implementation.target_files == ("mods/BetterHitFeedback/Plugin.cs",)
    assert implementation.target_symbols == ("Load",)
    assert implementation.evidence_refs == ("ev_001",)
    assert implementation.proposed_changes[0]["evidence_source_path"] == (
        "mods/BetterHitFeedback/Plugin.cs"
    )
    assert implementation.proposed_changes[0]["edit_target_path"] == (
        "mods/BetterHitFeedback/Plugin.cs"
    )
    assert implementation.proposed_changes[0]["evidence_refs"] == ["ev_001"]
    assert implementation.rollback_plan


def test_implementation_plan_blocks_when_evidence_source_is_not_editable() -> None:
    plan = RequestPlanner().plan("make Load enable diagnostics")
    spec = FeatureSpecBuilder().build(plan)
    evidence_pack = {
        "readiness": "sufficient",
        "can_generate_patch": True,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": True,
        **_identity_schema_payload(),
        "items": [
            _authoritative_item(
                evidence_id="ev_api_001",
                source_type="decompiled_api",
                source_path="decompiled/EnemyAgent.cs",
                symbol="Load",
            )
        ],
    }

    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack=evidence_pack,
    )

    assert implementation.blocking is True
    assert implementation.target_files == ()
    assert implementation.proposed_changes == ()
    assert implementation.evidence_refs == ()
    assert implementation.evidence_source_paths == ("decompiled/EnemyAgent.cs",)
    assert implementation.blockers[0]["code"] == "EDIT_TARGET_UNRESOLVED"


def test_planning_payloads_validate_against_artifact_contract(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    plan = RequestPlanner().plan("make Load enable diagnostics")
    brief = ModPlanningBriefBuilder().build(plan, target_game="GTFO")
    spec = FeatureSpecBuilder().build(plan)
    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack={
            "readiness": "sufficient",
            "can_generate_patch": True,
            "authority": "mod_agent_deterministic_evidence",
            "authoritative_for_patch": True,
            **_identity_schema_payload(),
            "items": [_authoritative_item()],
        },
    )

    request_ref = store.write(
        feature_id=plan.feature_id,
        artifact_type="request_planning_report",
        payload=plan.to_artifact_payload(),
    )
    brief_ref = store.write(
        feature_id=plan.feature_id,
        artifact_type="mod_planning_brief",
        payload=brief.to_artifact_payload(),
        upstream_refs=[request_ref],
    )
    feature_ref = store.write(
        feature_id=plan.feature_id,
        artifact_type="feature_spec",
        payload=spec.to_artifact_payload(),
    )
    evidence_ref = store.write(
        feature_id=plan.feature_id,
        artifact_type="evidence_pack",
        payload={
            "node_name": "retrieve_evidence",
            "stage": "evidence_retrieval",
            "message": "Evidence is sufficient.",
            "query": "make Load enable diagnostics",
            "readiness": "sufficient",
            "can_generate_patch": True,
            "authority": "mod_agent_deterministic_evidence",
            "authoritative_for_patch": True,
            **_identity_schema_payload(),
            "items": [_authoritative_item()],
            "gaps": [],
            "excluded": [],
            "blockers": [],
            "retrieval_methods_used": ["symbol_exact"],
            "missing_evidence": [],
            "disabled_modes": {},
            "timing": {},
            "trace_refs": [],
        },
        upstream_refs=[feature_ref],
    )
    implementation_ref = store.write(
        feature_id=plan.feature_id,
        artifact_type="implementation_plan",
        payload=implementation.to_artifact_payload(),
        upstream_refs=[feature_ref, evidence_ref],
    )

    assert store.read(request_ref)["data"]["route"] == plan.route
    assert store.read(brief_ref)["data"]["request_type"]["value"] == "runtime diagnostics"
    assert store.read(feature_ref)["data"]["target_behavior"] == plan.user_request
    assert store.read(implementation_ref)["data"]["evidence_refs"] == ["ev_001"]


def test_implementation_plan_blocks_non_authoritative_evidence_pack() -> None:
    plan = RequestPlanner().plan("make Load enable diagnostics")
    spec = FeatureSpecBuilder().build(plan)
    evidence_pack = {
        "readiness": "sufficient",
        "can_generate_patch": True,
        "authority": "legacy_rag_auxiliary",
        "authoritative_for_patch": False,
        **_identity_schema_payload(),
        "items": [
            {
                "evidence_id": "legacy_001",
                "source_type": "target_source",
                "source_path": "mods/BetterHitFeedback/Plugin.cs",
                "symbol": "Load",
                "authority": "legacy_rag_auxiliary",
            }
        ],
    }

    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack=evidence_pack,
    )

    assert implementation.blocking is True
    assert implementation.proposed_changes == ()
    assert implementation.blockers[0]["code"] == "NON_AUTHORITATIVE_EVIDENCE_PACK"


def test_implementation_plan_blocks_item_with_missing_authority() -> None:
    plan = RequestPlanner().plan("make Load enable diagnostics")
    spec = FeatureSpecBuilder().build(plan)
    item = _authoritative_item()
    item.pop("authority")
    evidence_pack = {
        "readiness": "sufficient",
        "can_generate_patch": True,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": True,
        **_identity_schema_payload(),
        "items": [item],
    }

    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack=evidence_pack,
    )

    assert implementation.blocking is True
    assert implementation.blockers[0]["code"] == "NON_AUTHORITATIVE_EVIDENCE_ITEM"


def test_implementation_plan_blocks_unprovenanced_raw_evidence_pack() -> None:
    plan = RequestPlanner().plan("make Load enable diagnostics")
    spec = FeatureSpecBuilder().build(plan)
    evidence_pack = {
        "readiness": "sufficient",
        "can_generate_patch": True,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": True,
        "items": [_authoritative_item()],
    }

    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack=evidence_pack,
    )

    assert implementation.blocking is True
    assert implementation.blockers[0]["code"] == "UNVERIFIED_EVIDENCE_PROVENANCE"


def test_implementation_plan_ignores_auxiliary_context_items() -> None:
    plan = RequestPlanner().plan("make Load enable diagnostics")
    spec = FeatureSpecBuilder().build(plan)
    evidence_pack = {
        "readiness": "sufficient",
        "can_generate_patch": True,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": True,
        **_identity_schema_payload(),
        "items": [
            _authoritative_item(),
            {
                "evidence_id": "legacy_001",
                "source_type": "target_source",
                "source_path": "legacy/Plugin.cs",
                "symbol": "Load",
                "authority": "legacy_rag_auxiliary",
            },
        ],
    }

    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack=evidence_pack,
    )

    assert implementation.blocking is False
    assert implementation.evidence_refs == ("ev_001",)
    assert implementation.evidence_source_paths == ("mods/BetterHitFeedback/Plugin.cs",)
    assert implementation.target_files == ("mods/BetterHitFeedback/Plugin.cs",)
