"""Tests for Phase E deterministic planning."""

from __future__ import annotations

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.planning import (
    FeatureSpecBuilder,
    ImplementationPlanner,
    RequestPlanner,
)


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
        "items": [
            {
                "evidence_id": "ev_001",
                "source_type": "target_source",
                "source_path": "mods/BetterHitFeedback/Plugin.cs",
                "symbol": "Load",
            }
        ],
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
        "items": [
            {
                "evidence_id": "ev_api_001",
                "source_type": "decompiled_api",
                "source_path": "decompiled/EnemyAgent.cs",
                "symbol": "Load",
            }
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
    spec = FeatureSpecBuilder().build(plan)
    implementation = ImplementationPlanner().build(
        feature_spec=spec,
        evidence_pack={
            "readiness": "sufficient",
            "can_generate_patch": True,
            "items": [
                {
                    "evidence_id": "ev_001",
                    "source_type": "target_source",
                    "source_path": "mods/BetterHitFeedback/Plugin.cs",
                    "symbol": "Load",
                }
            ],
        },
    )

    request_ref = store.write(
        feature_id=plan.feature_id,
        artifact_type="request_planning_report",
        payload=plan.to_artifact_payload(),
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
            "items": [
                {
                    "evidence_id": "ev_001",
                    "source_type": "target_source",
                    "source_path": "mods/BetterHitFeedback/Plugin.cs",
                    "symbol": "Load",
                }
            ],
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
    assert store.read(feature_ref)["data"]["target_behavior"] == plan.user_request
    assert store.read(implementation_ref)["data"]["evidence_refs"] == ["ev_001"]
