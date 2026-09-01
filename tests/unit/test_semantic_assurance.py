"""Focused tests for the Semantic Assurance V0 human gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.mod_agent.execution import (
    ExactDiffApprovalRejectedError,
    ExactTextPatchApplier,
    PatchApplyError,
)
from src.mod_agent.proposal import PatchProposalBuilder, ProposalReviewer
from src.mod_agent.proposal.models import SemanticAssuranceV1


_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
_FROZEN_4B_RESPONSE = _FIXTURE_ROOT / "wrong_4b_patch_response.json"
_FOUR_SITE_SOURCE = _FIXTURE_ROOT / "actual15_four_site_source"


def _artifact_hashes() -> dict[str, str]:
    return {
        "feature_spec": "sha256:feature",
        "evidence_pack": "sha256:evidence",
        "implementation_plan": "sha256:implementation",
    }


def _wrong_4b_inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    frozen = json.loads(_FROZEN_4B_RESPONSE.read_text(encoding="utf-8"))
    assert frozen["source_sha256"] == (
        "cb75b0db0f136a9030ec72ba5d2f066f10c30c8e75f46667a2c65a3b19a5a93c"
    )

    sites = (
        ("Configuration.cs", "Configuration", 12, 17),
        ("Configuration.cs", "OnFileChanged", 35, 48),
        ("Configuration.cs", "BindAll", 50, 78),
        ("SpreadPatches.cs", "OverrideCrosshairSize", 115, 145),
    )
    evidence_items: list[dict[str, object]] = []
    edit_bindings: list[dict[str, object]] = []
    proposed_changes: list[dict[str, object]] = []
    for index, (change, site) in enumerate(zip(frozen["changes"], sites), start=1):
        filename, symbol, start_line, end_line = site
        source_path = _FOUR_SITE_SOURCE / filename
        source_bytes = source_path.read_bytes()
        source_text = source_bytes.decode("utf-8-sig")
        before_text = "".join(source_text.splitlines(keepends=True)[start_line - 1 : end_line])
        evidence_id = f"frozen_4b_evidence_{index:03d}"
        source_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
        evidence_items.append(
            {
                "evidence_id": evidence_id,
                "source_type": "target_source",
                "source_path": filename,
                "symbol": symbol,
                "span": {"start_line": start_line, "end_line": end_line},
                "retrieval_method": "symbol_exact",
                "excerpt": before_text,
                "chunk_id": f"chunk_{index:03d}",
                "document_id": f"document_{index:03d}",
                "source_ref": f"source_{index:03d}",
                "source_hash": source_hash,
                "file_hash": source_hash,
                "doc_hash": source_hash,
            }
        )
        edit_bindings.append(
            {
                "binding_id": change["edit_binding_id"],
                "evidence_id": evidence_id,
                "canonical_target_path": filename,
                "source_type": "target_source",
                "target_symbol": symbol,
                "target_span": {"start_line": start_line, "end_line": end_line},
                "declaring_type": "FixtureType",
                "method_name": symbol,
                "parameter_types": [],
                "return_type": "void",
                "method_kind": "method",
                "retrieval_method": "symbol_exact",
                "claim_supported": "The exact frozen source site is present.",
                "authority": "mod_agent_deterministic",
                "usage": "edit_target_scope",
            }
        )
        proposed_changes.append(
            {
                "change_id": change["change_id"],
                "change_type": "modify_behavior",
                "edit_binding_id": change["edit_binding_id"],
                "supporting_binding_ids": [],
                "operation": "exact_text_replace",
                "rationale": change["rationale"],
                "risk_tags": ["medium"],
                "expected_validation": ["Observe RuntimeMarker."],
                "rollback_hint": change["rollback_hint"],
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": before_text,
                    "after_text": change["after_text"],
                    "expected_occurrences": 1,
                },
            }
        )

    evidence_pack = {"items": evidence_items}
    implementation_plan = {
        "feature_id": "ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001",
        "evidence_source_paths": ["Configuration.cs", "SpreadPatches.cs"],
        "target_files": ["Configuration.cs", "SpreadPatches.cs"],
        "target_symbols": [site[1] for site in sites],
        "evidence_refs": [item["evidence_id"] for item in evidence_items],
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": edit_bindings,
            "supporting_bindings": [],
        },
        "proposed_changes": proposed_changes,
        "side_effect_boundaries": ["Preserve behavior outside the four bound sites."],
        "test_plan": ["Observe RuntimeMarker."],
        "rollback_plan": ["Restore every exact frozen source excerpt."],
        "open_questions": [],
        "blocking": False,
        "blockers": [],
    }
    feature_spec = {
        "target_behavior": "Add an independent accurate spread setting behavior.",
        "hook_requirement": {"required": False, "reason": "not_required"},
    }
    proposal = PatchProposalBuilder().build(
        implementation_plan,
        evidence_pack=evidence_pack,
        artifact_hashes=_artifact_hashes(),
        source_snippet_char_limit=20000,
    ).to_artifact_payload()
    return proposal, implementation_plan, evidence_pack, feature_spec


def _generic_inputs(
    assurance: SemanticAssuranceV1,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    evidence_pack = {
        "items": [
            {
                "evidence_id": "evidence_001",
                "source_type": "target_source",
                "source_path": "module.py",
                "symbol": "transform",
                "span": {"start_line": 1, "end_line": 1},
                "retrieval_method": "symbol_exact",
                "excerpt": "value = 'before'\n",
                "chunk_id": "chunk_001",
                "document_id": "document_001",
                "source_ref": "source_001",
                "source_hash": "sha256:source",
                "file_hash": "sha256:source",
                "doc_hash": "sha256:source",
            }
        ]
    }
    plan = {
        "feature_id": "generic_feature",
        "evidence_source_paths": ["module.py"],
        "target_files": ["module.py"],
        "target_symbols": ["transform"],
        "evidence_refs": ["evidence_001"],
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "evidence_id": "evidence_001",
                    "canonical_target_path": "module.py",
                    "source_type": "target_source",
                    "target_symbol": "transform",
                    "target_span": {"start_line": 1, "end_line": 1},
                    "declaring_type": "Module",
                    "method_name": "transform",
                    "parameter_types": [],
                    "return_type": "str",
                    "method_kind": "function",
                    "retrieval_method": "symbol_exact",
                    "claim_supported": "The exact source line is present.",
                    "authority": "mod_agent_deterministic",
                    "usage": "edit_target_scope",
                }
            ],
            "supporting_bindings": [],
        },
        "proposed_changes": [
            {
                "change_id": "change_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "supporting_binding_ids": [],
                "operation": "exact_text_replace",
                "rationale": "Transform the generic value.",
                "risk_tags": [],
                "expected_validation": ["Run the bound unit test."],
                "rollback_hint": "Restore the original line.",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "value = 'before'",
                    "after_text": "value = 'after'",
                    "expected_occurrences": 1,
                },
            }
        ],
        "side_effect_boundaries": ["Do not change other files."],
        "test_plan": ["Run the bound unit test."],
        "rollback_plan": ["Restore the original line."],
        "open_questions": [],
        "blocking": False,
        "blockers": [],
    }
    proposal_model = PatchProposalBuilder().build(
        plan,
        evidence_pack=evidence_pack,
        artifact_hashes=_artifact_hashes(),
    )
    proposal = {
        **proposal_model.to_artifact_payload(),
        "semantic_assurance": assurance.to_dict(),
    }
    feature_spec = {
        "target_behavior": "Transform the generic value.",
        "hook_requirement": {"required": False, "reason": "not_required"},
    }
    return proposal, plan, evidence_pack, feature_spec


def _review(
    proposal: dict[str, object],
    plan: dict[str, object],
    evidence_pack: dict[str, object],
    feature_spec: dict[str, object],
):
    return ProposalReviewer().review(
        proposal,
        implementation_plan=plan,
        evidence_pack=evidence_pack,
        feature_spec=feature_spec,
        artifact_hashes=_artifact_hashes(),
        permission_level="dry_run_write",
        require_executable_patch=True,
    )


def _human_decision(
    dry_run: dict[str, object],
    *,
    decision: str = "approve",
    reviewer_identity: str = "human:test-reviewer",
    **overrides: object,
) -> dict[str, object]:
    binding = dry_run["human_semantic_decision_binding"]
    assert isinstance(binding, dict)
    return {
        **binding,
        "decision": decision,
        "reviewer_identity": reviewer_identity,
        **overrides,
    }


def test_frozen_wrong_4b_patch_is_unproven_and_requires_human_semantic_review() -> None:
    proposal, plan, evidence_pack, feature_spec = _wrong_4b_inputs()

    review = _review(proposal, plan, evidence_pack, feature_spec)

    assert len(proposal["diff_intent"]) == 4
    assert any(
        "human semantic review" in note
        for note in proposal["manual_review_notes"]
    )
    assert review.decision == "approve_dry_run"
    assert review.allowed_next_stage == "dry_run_apply"
    assert review.semantic_assurance.verdict == "unproven"
    assert review.semantic_assurance.assurance_method == "not_available"
    assert review.human_semantic_review_required is True
    assert any(
        finding.rule_id == "semantic_assurance"
        and finding.level == "warning"
        for finding in review.findings
    )
    assert "semantic_assurance" in review.checked_rules
    assert review.semantic_assurance.verdict != "satisfied_within_boundary"


@pytest.mark.parametrize("reported_verdict", ["satisfied_within_boundary", "violated"])
def test_proposal_cannot_self_report_semantic_verdict(
    reported_verdict: str,
) -> None:
    reported = SemanticAssuranceV1(
        verdict=reported_verdict,
        assurance_method="unit_test",
        evidence_refs=("artifact://fake/not-registered",),
        limitations=("The claimed test boundary is not independently registered.",),
        assumptions=("The Proposal claims its own verifier result.",),
        applicability=("The Proposal claims this applies to its replacement.",),
        invalidation_facts=("Any replacement change invalidates the claim.",),
    )
    proposal, plan, evidence_pack, feature_spec = _generic_inputs(reported)

    review = _review(proposal, plan, evidence_pack, feature_spec)

    assert review.semantic_assurance.verdict == "unproven"
    assert review.semantic_assurance.assurance_method == "not_available"
    assert review.allowed_next_stage is None
    assert review.decision == "revise_proposal"
    assert any(
        finding.rule_id == "semantic_assurance_untrusted_proposal_claim"
        and finding.level == "blocking"
        for finding in review.findings
    )


def test_missing_semantic_assurance_defaults_to_unproven() -> None:
    proposal, plan, evidence_pack, feature_spec = _generic_inputs(
        SemanticAssuranceV1.unproven()
    )
    proposal.pop("semantic_assurance")

    review = _review(proposal, plan, evidence_pack, feature_spec)

    assert review.semantic_assurance == SemanticAssuranceV1.unproven()
    assert review.allowed_next_stage == "dry_run_apply"
    assert review.human_semantic_review_required is True


def test_semantic_assurance_strict_round_trip_and_unknown_field_rejection() -> None:
    assurance = SemanticAssuranceV1.unproven()
    payload = assurance.to_dict()

    assert SemanticAssuranceV1.from_dict(payload) == assurance
    assert payload["schema_version"] == "semantic_assurance_v1"
    with pytest.raises(ValueError, match="fields"):
        SemanticAssuranceV1.from_dict({**payload, "unexpected": True})
    with pytest.raises(ValueError, match="non-empty strings"):
        SemanticAssuranceV1.from_dict({**payload, "limitations": [""]})
    with pytest.raises(ValueError, match="evidence_refs"):
        SemanticAssuranceV1(
            verdict="violated",
            assurance_method="static_analysis",
            evidence_refs=(),
            limitations=("The analyzer covers one rule set.",),
            assumptions=("The analyzed input is exact.",),
            applicability=("The analyzer applies to the proposal.",),
            invalidation_facts=("A proposal change invalidates the result.",),
        )


def test_unproven_dry_run_is_zero_write_and_apply_without_exact_approval_blocks(
    tmp_path: Path,
) -> None:
    proposal, plan, evidence_pack, feature_spec = _generic_inputs(
        SemanticAssuranceV1.unproven()
    )
    review = _review(proposal, plan, evidence_pack, feature_spec).to_artifact_payload()
    source = tmp_path / "module.py"
    source.write_text("value = 'before'\n", encoding="utf-8")
    applier = ExactTextPatchApplier()

    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
        review=review,
        allow_write=False,
    )

    assert dry_run["semantic_assurance"]["verdict"] == "unproven"
    assert dry_run["human_semantic_review_required"] is True
    assert dry_run["human_semantic_review_completed"] is False
    assert dry_run["human_semantic_decision_binding"] == {
        "schema_version": "human_semantic_decision_v1",
        "feature_id": proposal["feature_id"],
        "feature_spec_artifact_hash": "sha256:feature",
        "proposal_id": proposal["proposal_id"],
        "proposal_payload_sha256": dry_run["context_hashes"][
            "proposal_payload_sha256"
        ],
        "proposal_review_payload_sha256": dry_run["context_hashes"][
            "proposal_review_payload_sha256"
        ],
        "semantic_assurance_payload_sha256": dry_run["context_hashes"][
            "semantic_assurance_payload_sha256"
        ],
        "diff_hash": dry_run["diff_hash"],
    }
    assert dry_run["actual_write_performed"] is False
    with pytest.raises(PatchApplyError, match="human semantic decision"):
        applier.run(
            workspace_root=tmp_path,
            proposal=proposal,
            implementation_plan=plan,
            review=review,
            allow_write=True,
            approved_diff_hash=str(dry_run["diff_hash"]),
        )
    assert source.read_text(encoding="utf-8") == "value = 'before'\n"


def test_hash_only_exact_diff_approval_cannot_write_unproven_proposal(
    tmp_path: Path,
) -> None:
    proposal, plan, evidence_pack, feature_spec = _generic_inputs(
        SemanticAssuranceV1.unproven()
    )
    review = _review(proposal, plan, evidence_pack, feature_spec).to_artifact_payload()
    source = tmp_path / "module.py"
    source.write_text("value = 'before'\n", encoding="utf-8")
    applier = ExactTextPatchApplier()
    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
        review=review,
        allow_write=False,
    )

    with pytest.raises(PatchApplyError, match="human semantic decision"):
        applier.run(
            workspace_root=tmp_path,
            proposal=proposal,
            implementation_plan=plan,
            review=review,
            allow_write=True,
            approved_diff_hash=str(dry_run["diff_hash"]),
        )

    assert source.read_text(encoding="utf-8") == "value = 'before'\n"


def test_structured_human_reject_is_bound_and_zero_write(tmp_path: Path) -> None:
    proposal, plan, evidence_pack, feature_spec = _generic_inputs(
        SemanticAssuranceV1.unproven()
    )
    review = _review(proposal, plan, evidence_pack, feature_spec).to_artifact_payload()
    source = tmp_path / "module.py"
    source.write_text("value = 'before'\n", encoding="utf-8")
    applier = ExactTextPatchApplier()
    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
        review=review,
        allow_write=False,
    )

    with pytest.raises(ExactDiffApprovalRejectedError, match="rejected"):
        applier.run(
            workspace_root=tmp_path,
            proposal=proposal,
            implementation_plan=plan,
            review=review,
            allow_write=True,
            approved_diff_hash=str(dry_run["diff_hash"]),
            human_semantic_decision=_human_decision(
                dry_run,
                decision="reject",
            ),
        )

    assert source.read_text(encoding="utf-8") == "value = 'before'\n"


def test_structured_human_approve_writes_only_bound_bytes_and_preserves_machine_verdict(
    tmp_path: Path,
) -> None:
    proposal, plan, evidence_pack, feature_spec = _generic_inputs(
        SemanticAssuranceV1.unproven()
    )
    review = _review(proposal, plan, evidence_pack, feature_spec).to_artifact_payload()
    source = tmp_path / "module.py"
    source.write_text("value = 'before'\n", encoding="utf-8")
    applier = ExactTextPatchApplier()
    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
        review=review,
        allow_write=False,
    )
    decision = _human_decision(dry_run)

    applied = applier.run(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
        review=review,
        allow_write=True,
        approved_diff_hash=str(dry_run["diff_hash"]),
        human_semantic_decision=decision,
    )

    assert applied["actual_write_performed"] is True
    assert applied["human_semantic_review_completed"] is True
    assert applied["human_semantic_review_result"] == "approved"
    assert applied["human_semantic_decision"] == decision
    assert applied["semantic_assurance"]["verdict"] == "unproven"
    assert applied["semantic_assurance"]["assurance_method"] == "not_available"
    assert source.read_text(encoding="utf-8") == "value = 'after'\n"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "human_semantic_decision_v0"),
        ("feature_id", "other_feature"),
        ("feature_spec_artifact_hash", "sha256:other-feature"),
        ("proposal_id", "proposal_other"),
        ("proposal_payload_sha256", "sha256:other-proposal"),
        ("proposal_review_payload_sha256", "sha256:other-review"),
        ("semantic_assurance_payload_sha256", "sha256:other-assurance"),
        ("diff_hash", "sha256:other-diff"),
        ("decision", "maybe"),
        ("reviewer_identity", ""),
    ],
)
def test_structured_human_decision_drift_is_zero_write(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    proposal, plan, evidence_pack, feature_spec = _generic_inputs(
        SemanticAssuranceV1.unproven()
    )
    review = _review(proposal, plan, evidence_pack, feature_spec).to_artifact_payload()
    source = tmp_path / "module.py"
    source.write_text("value = 'before'\n", encoding="utf-8")
    applier = ExactTextPatchApplier()
    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
        review=review,
        allow_write=False,
    )
    decision = _human_decision(dry_run)
    decision[field] = value

    with pytest.raises(PatchApplyError):
        applier.run(
            workspace_root=tmp_path,
            proposal=proposal,
            implementation_plan=plan,
            review=review,
            allow_write=True,
            approved_diff_hash=str(dry_run["diff_hash"]),
            human_semantic_decision=decision,
        )

    assert source.read_text(encoding="utf-8") == "value = 'before'\n"
