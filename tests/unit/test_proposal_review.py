"""Tests for Phase F patch proposal and review gates."""

from __future__ import annotations

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.proposal import PatchProposalBuilder, ProposalReviewer


def _implementation_payload() -> dict[str, object]:
    return {
        "node_name": "create_implementation_plan",
        "stage": "implementation_plan",
        "message": "Implementation plan is evidence-bound.",
        "feature_id": "feature_001",
        "evidence_source_paths": ["mods/BetterHitFeedback/Plugin.cs"],
        "target_files": ["mods/BetterHitFeedback/Plugin.cs"],
        "target_symbols": ["Load"],
        "evidence_refs": ["ev_001"],
        "proposed_changes": [
            {
                "change_id": "chg_001",
                "change_type": "modify_behavior",
                "evidence_source_path": "mods/BetterHitFeedback/Plugin.cs",
                "edit_target_path": "mods/BetterHitFeedback/Plugin.cs",
                "target_file": "mods/BetterHitFeedback/Plugin.cs",
                "target_symbol": "Load",
                "operation": "minimal_evidence_bound_change",
                "rationale": "make Load enable diagnostics",
                "evidence_refs": ["ev_001"],
                "risk_tags": ["medium"],
                "expected_validation": ["compile"],
                "rollback_hint": "Restore previous behavior.",
            }
        ],
        "side_effect_boundaries": ["Do not refactor unrelated files."],
        "test_plan": ["compile"],
        "rollback_plan": ["Rollback chg_001"],
        "open_questions": [],
        "blocking": False,
        "blockers": [],
    }


def _evidence_pack() -> dict[str, object]:
    return {
        "items": [
            {
                "evidence_id": "ev_001",
                "source_type": "target_source",
                "source_path": "mods/BetterHitFeedback/Plugin.cs",
                "symbol": "Load",
            }
        ]
    }


def _feature_spec() -> dict[str, object]:
    return {
        "target_behavior": "make Load enable diagnostics",
    }


def test_patch_proposal_builder_converts_implementation_plan_to_reviewable_intent() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload())

    assert proposal.blocked is False
    assert proposal.feature_id == "feature_001"
    assert proposal.files == ("mods/BetterHitFeedback/Plugin.cs",)
    assert proposal.evidence_refs == ("ev_001",)
    assert proposal.diff_intent[0]["change_id"] == "chg_001"
    assert proposal.diff_intent[0]["evidence_source_path"] == (
        "mods/BetterHitFeedback/Plugin.cs"
    )
    assert proposal.diff_intent[0]["edit_target_path"] == (
        "mods/BetterHitFeedback/Plugin.cs"
    )
    assert proposal.diff_intent[0]["target_file"] == (
        "mods/BetterHitFeedback/Plugin.cs"
    )
    assert proposal.diff_intent[0]["evidence_refs"] == ["ev_001"]
    assert proposal.change_units[0]["change_unit_id"] == "chg_001"
    assert proposal.change_units[0]["target_file"] == (
        "mods/BetterHitFeedback/Plugin.cs"
    )
    assert proposal.context_pack["feature_id"] == "feature_001"
    assert proposal.context_pack["evidence_source_paths"] == [
        "mods/BetterHitFeedback/Plugin.cs"
    ]
    assert proposal.context_pack["change_unit_ids"] == ["chg_001"]
    assert proposal.no_op_status == {"is_no_op": False, "reason": None}
    assert proposal.rollback_hints == (
        {
            "change_unit_id": "chg_001",
            "rollback_hint": "Restore previous behavior.",
        },
    )
    assert proposal.expected_tests == ("compile",)


def test_patch_proposal_builder_blocks_no_op_plan() -> None:
    payload = _implementation_payload()
    payload["proposed_changes"] = []

    proposal = PatchProposalBuilder().build(payload)

    assert proposal.blocked is True
    assert proposal.blockers[0]["code"] == "NO_OP_PROPOSAL"
    assert proposal.no_op_status["is_no_op"] is True


def test_patch_proposal_builder_blocks_unresolved_edit_target() -> None:
    payload = _implementation_payload()
    payload["target_files"] = []
    payload["proposed_changes"][0].pop("edit_target_path")

    proposal = PatchProposalBuilder().build(payload)

    assert proposal.blocked is True
    assert proposal.blockers[0]["code"] == "EDIT_TARGET_UNRESOLVED"


def test_reviewer_approves_evidence_bound_dry_run_proposal() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload())

    review = ProposalReviewer().review(
        proposal.to_artifact_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        permission_level="dry_run_write",
    )

    assert review.decision == "approve_dry_run"
    assert review.allowed_next_stage == "dry_run_apply"
    assert review.required_changes == ()
    assert review.trace_metrics["num_changes_checked"] == 1


def test_reviewer_blocks_evidence_bound_proposal_without_evidence_pack() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload())

    review = ProposalReviewer().review(
        proposal.to_artifact_payload(),
        feature_spec=_feature_spec(),
        permission_level="dry_run_write",
    )

    assert review.decision == "blocked_insufficient_evidence"
    assert review.allowed_next_stage is None
    assert any(finding.rule_id == "evidence_binding" for finding in review.findings)
    assert review.required_changes == (
        "Change unit evidence refs cannot be validated without an evidence pack or repair plan.",
    )


def test_reviewer_blocks_unbound_change() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload()).to_artifact_payload()
    proposal["diff_intent"][0]["evidence_refs"] = []

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "blocked_insufficient_evidence"
    assert review.allowed_next_stage is None
    assert review.findings[0].rule_id == "evidence_binding"


def test_reviewer_blocks_missing_context_pack() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload()).to_artifact_payload()
    proposal.pop("context_pack")

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "revise_proposal"
    assert review.allowed_next_stage is None
    assert any(finding.rule_id == "context_pack" for finding in review.findings)


def test_reviewer_blocks_change_unit_mismatch() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload()).to_artifact_payload()
    proposal["change_units"][0]["change_unit_id"] = "different_change"

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "revise_proposal"
    assert review.allowed_next_stage is None
    assert any(finding.rule_id == "context_pack" for finding in review.findings)


def test_reviewer_blocks_context_pack_change_unit_id_drift() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload()).to_artifact_payload()
    proposal["context_pack"]["change_unit_ids"] = ["different_change"]

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "revise_proposal"
    assert review.allowed_next_stage is None
    assert any(
        finding.message
        == "Proposal context_pack change_unit_ids do not match proposal change_units."
        for finding in review.findings
    )


def test_reviewer_blocks_forbidden_path() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload()).to_artifact_payload()
    proposal["files"] = [".git/config"]
    proposal["diff_intent"][0]["target_file"] = ".git/config"

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "blocked_scope_risk"
    assert any(finding.rule_id == "forbidden_paths" for finding in review.findings)


def test_reviewer_blocks_wrong_permission_level() -> None:
    proposal = PatchProposalBuilder().build(_implementation_payload()).to_artifact_payload()

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        permission_level="confirmed_write",
    )

    assert review.decision == "blocked_requires_human"
    assert any(finding.rule_id == "permission_level" for finding in review.findings)


def test_proposal_payloads_validate_against_artifact_contract(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    proposal = PatchProposalBuilder().build(_implementation_payload())
    review = ProposalReviewer().review(
        proposal.to_artifact_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    feature_ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload={
            "node_name": "draft_feature_spec",
            "stage": "feature_spec",
            "message": "Feature spec is ready.",
            "feature_id": "feature_001",
            "user_request": "make Load enable diagnostics",
            "target_behavior": "make Load enable diagnostics",
            "non_goals": [],
            "target_mod": "BetterHitFeedback",
            "risk_level": "medium",
            "acceptance_criteria": [],
            "evidence_requirements": [],
            "runtime_verification_plan": [],
            "blocked": False,
            "blockers": [],
        },
    )
    evidence_ref = store.write(
        feature_id="feature_001",
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
            "identity_schema_version": "identity_v1",
            "identity_field_mapping": {
                "document_id": "Stable loaded document id",
                "file_hash": "SHA256 of the loaded source file",
                "source_hash": "Backward-compatible alias for file_hash",
                "doc_hash": "SHA256 of the document canonical_text",
                "chunk_id": "Stable chunk id",
                "source_ref": "Chunk-to-document reference",
                "content_hash": "Context-dependent stored content hash",
            },
            "items": _evidence_pack()["items"],
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
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_ref, evidence_ref],
    )
    proposal_ref = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload=proposal.to_artifact_payload(),
        upstream_refs=[implementation_ref, evidence_ref],
    )
    review_ref = store.write(
        feature_id="feature_001",
        artifact_type="proposal_review",
        payload=review.to_artifact_payload(),
        upstream_refs=[proposal_ref],
    )

    assert store.read(proposal_ref)["data"]["proposal_id"] == proposal.proposal_id
    assert store.read(review_ref)["data"]["decision"] == "approve_dry_run"
