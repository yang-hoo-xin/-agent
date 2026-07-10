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
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "evidence_id": "ev_001",
                    "canonical_target_path": "mods/BetterHitFeedback/Plugin.cs",
                    "source_type": "target_source",
                    "target_symbol": "Load",
                    "target_span": {"start_line": 10, "end_line": 18},
                    "retrieval_method": "symbol_exact",
                    "claim_supported": "Symbol Load exists.",
                    "authority": "mod_agent_deterministic",
                    "usage": "edit_target_scope",
                }
            ],
            "supporting_bindings": [],
        },
        "proposed_changes": [
            {
                "change_id": "chg_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "supporting_binding_ids": [],
                "operation": "minimal_evidence_bound_change",
                "rationale": "make Load enable diagnostics",
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
                "span": {"start_line": 10, "end_line": 18},
                "retrieval_method": "symbol_exact",
                "excerpt": "public void Load() { /* existing behavior */ }",
                "chunk_id": "chunk_001",
                "document_id": "doc_001",
                "source_ref": "source_001",
                "source_hash": "sha256:source",
                "file_hash": "sha256:file",
                "doc_hash": "sha256:doc",
            }
        ]
    }


def _artifact_hashes() -> dict[str, str]:
    return {
        "feature_spec": "sha256:feature",
        "evidence_pack": "sha256:evidence",
        "implementation_plan": "sha256:implementation",
    }


def _git_binding() -> dict[str, object]:
    return {
        "status": "available",
        "base_revision": "a" * 40,
        "branch": "codex/test",
        "is_dirty": False,
        "diff_hash": "sha256:gitdiff",
        "dirty_tree_policy": {
            "status": "clean",
            "blocks_proposal_binding": False,
            "blockers": [],
        },
    }


def _proposal_payload() -> dict[str, object]:
    return PatchProposalBuilder().build(
        _implementation_payload(),
        evidence_pack=_evidence_pack(),
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    ).to_artifact_payload()


def _feature_spec() -> dict[str, object]:
    return {
        "target_behavior": "make Load enable diagnostics",
        "hook_requirement": {"required": False, "reason": "not_required"},
    }


def _hook_feature_spec() -> dict[str, object]:
    return {
        "target_behavior": "hook enemy damage method for BetterHitFeedback",
        "hook_requirement": {
            "required": True,
            "reason": "gameplay_method_interception",
        },
    }


def _hook_target_binding() -> dict[str, object]:
    return {
        "binding_id": "hook_target_001",
        "evidence_id": "ev_api_001",
        "source_path": "decompiled/CrosshairGuiLayer.cs",
        "source_type": "decompiled_api",
        "target_symbol": "CrosshairGuiLayer.ShowHitIndicator",
        "target_span": {"start_line": 100, "end_line": 120},
        "declaring_type": "CrosshairGuiLayer",
        "method_name": "ShowHitIndicator",
        "parameter_types": [
            "UnityEngine.Vector3",
            "System.Boolean",
            "System.Boolean",
            "System.Boolean",
        ],
        "return_type": "System.Void",
        "method_kind": "instance_method",
        "retrieval_method": "symbol_exact",
        "claim_supported": "ShowHitIndicator is the hook target.",
        "authority": "mod_agent_deterministic",
        "usage": "hook_target",
    }


def _hook_target_evidence_item() -> dict[str, object]:
    return {
        "evidence_id": "ev_api_001",
        "source_type": "decompiled_api",
        "source_path": "decompiled/CrosshairGuiLayer.cs",
        "symbol": "CrosshairGuiLayer.ShowHitIndicator",
        "span": {"start_line": 100, "end_line": 120},
        "declaring_type": "CrosshairGuiLayer",
        "method_name": "ShowHitIndicator",
        "parameter_types": [
            "UnityEngine.Vector3",
            "System.Boolean",
            "System.Boolean",
            "System.Boolean",
        ],
        "return_type": "System.Void",
        "method_kind": "instance_method",
        "retrieval_method": "symbol_exact",
        "excerpt": "public void ShowHitIndicator(Vector3 pos, bool a, bool b, bool c) { }",
        "chunk_id": "chunk_api_001",
        "document_id": "doc_api_001",
        "source_ref": "source_api_001",
        "source_hash": "sha256:source_api",
        "file_hash": "sha256:file_api",
        "doc_hash": "sha256:doc_api",
        "usage": "hook_target",
    }


def test_patch_proposal_builder_converts_implementation_plan_to_reviewable_intent() -> None:
    proposal = PatchProposalBuilder().build(
        _implementation_payload(),
        evidence_pack=_evidence_pack(),
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    )

    assert proposal.blocked is False
    assert proposal.feature_id == "feature_001"
    assert proposal.files == ("mods/BetterHitFeedback/Plugin.cs",)
    assert proposal.evidence_refs == ("ev_001",)
    assert proposal.diff_intent[0]["change_id"] == "chg_001"
    assert proposal.diff_intent[0]["edit_binding_id"] == "edit_binding_001"
    assert "target_file" not in proposal.diff_intent[0]
    assert "target_symbol" not in proposal.diff_intent[0]
    assert "source_span" not in proposal.diff_intent[0]
    assert proposal.change_units[0]["change_unit_id"] == "chg_001"
    assert proposal.change_units[0]["edit_binding_id"] == "edit_binding_001"
    assert proposal.context_pack["feature_id"] == "feature_001"
    assert proposal.context_pack["evidence_source_paths"] == [
        "mods/BetterHitFeedback/Plugin.cs"
    ]
    assert proposal.context_pack["change_unit_ids"] == ["chg_001"]
    assert proposal.context_pack["source_snippets"][0]["evidence_id"] == "ev_001"
    assert proposal.context_pack["source_snippets"][0]["span"] == {
        "start_line": 10,
        "end_line": 18,
    }
    assert proposal.context_pack["target_symbol_signatures"][0]["symbol"] == "Load"
    assert proposal.context_pack["binding_registry_ref"] == {
        "artifact_type": "implementation_plan",
        "artifact_hash": "sha256:implementation",
        "schema_version": "binding_registry_v1",
    }
    assert proposal.context_pack["display_fields_authority"] == (
        "derived_non_authoritative"
    )
    assert proposal.context_pack["display_files"] == [
        "mods/BetterHitFeedback/Plugin.cs"
    ]
    assert proposal.context_pack["allowed_edit_binding_ids"] == ["edit_binding_001"]
    assert proposal.context_pack["artifact_hashes"]["evidence_pack"] == (
        "sha256:evidence"
    )
    assert proposal.context_pack["implementation_plan_hash"] == (
        "sha256:implementation"
    )
    assert proposal.context_pack["git_binding"]["base_revision"] == "a" * 40
    assert proposal.context_pack["context_budget"]["source_snippet_count"] == 1
    assert proposal.context_pack["omission_blockers"] == []
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
    payload["proposed_changes"][0].pop("edit_binding_id")

    proposal = PatchProposalBuilder().build(payload)

    assert proposal.blocked is True
    assert proposal.blockers[0]["code"] == "EDIT_TARGET_UNRESOLVED"


def test_patch_proposal_builder_derives_files_from_binding_registry() -> None:
    payload = _implementation_payload()
    payload["target_files"] = ["wrong/Displayed.cs"]

    proposal = PatchProposalBuilder().build(payload)

    assert proposal.blocked is False
    assert proposal.files == ("mods/BetterHitFeedback/Plugin.cs",)
    assert proposal.context_pack["display_files"] == [
        "mods/BetterHitFeedback/Plugin.cs"
    ]


def test_reviewer_approves_evidence_bound_dry_run_proposal() -> None:
    review = ProposalReviewer().review(
        _proposal_payload(),
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
        permission_level="dry_run_write",
    )

    assert review.decision == "approve_dry_run"
    assert review.allowed_next_stage == "dry_run_apply"
    assert review.required_changes == ()
    assert review.trace_metrics["num_changes_checked"] == 1


def test_reviewer_blocks_evidence_bound_proposal_without_evidence_pack() -> None:
    review = ProposalReviewer().review(
        _proposal_payload(),
        implementation_plan=_implementation_payload(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
        permission_level="dry_run_write",
    )

    assert review.decision == "revise_proposal"
    assert review.allowed_next_stage is None
    assert any(finding.rule_id == "binding_registry" for finding in review.findings)
    assert (
        "Edit binding evidence_id is not present in evidence_pack."
        in review.required_changes
    )


def test_reviewer_blocks_unbound_change() -> None:
    proposal = _proposal_payload()
    proposal["diff_intent"][0].pop("edit_binding_id")

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "blocked_insufficient_evidence"
    assert review.allowed_next_stage is None
    assert any(finding.rule_id == "binding_registry" for finding in review.findings)


def test_reviewer_blocks_binding_registry_source_span_drift() -> None:
    proposal = _proposal_payload()
    implementation_plan = _implementation_payload()
    implementation_plan["binding_registry"]["edit_bindings"][0]["target_span"] = None

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=implementation_plan,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert review.decision == "revise_proposal"
    assert any(
        finding.message
        == "Edit binding span does not match evidence_pack."
        for finding in review.findings
    )


def test_reviewer_blocks_proposal_copying_authoritative_binding_fields() -> None:
    proposal = _proposal_payload()
    proposal["diff_intent"][0]["target_symbol"] = "DifferentSymbol"

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert review.decision == "revise_proposal"
    assert any(
        finding.message
        == "Proposal changes must reference binding IDs instead of copying path, symbol, or span fields."
        for finding in review.findings
    )


def test_reviewer_allows_mixed_evidence_without_edit_binding_for_every_ref() -> None:
    payload = _implementation_payload()
    payload["evidence_source_paths"].append("decompiled/EnemyAgent.cs")
    payload["evidence_refs"].append("ev_api_001")
    payload["binding_registry"]["supporting_bindings"].append(
        {
            "binding_id": "support_binding_ev_api_001",
            "evidence_id": "ev_api_001",
            "source_path": "decompiled/EnemyAgent.cs",
            "source_type": "decompiled_api",
            "target_symbol": "EnemyAgent.Damage",
            "target_span": {"start_line": 100, "end_line": 120},
            "retrieval_method": "symbol_exact",
            "claim_supported": "EnemyAgent.Damage is the game hook target.",
            "authority": "mod_agent_deterministic",
            "usage": "hook_target_or_supporting_evidence",
        }
    )
    payload["proposed_changes"][0]["supporting_binding_ids"].append(
        "support_binding_ev_api_001"
    )
    evidence_pack = _evidence_pack()
    evidence_pack["items"].append(
        {
            "evidence_id": "ev_api_001",
            "source_type": "decompiled_api",
            "source_path": "decompiled/EnemyAgent.cs",
            "symbol": "EnemyAgent.Damage",
            "span": {"start_line": 100, "end_line": 120},
            "retrieval_method": "symbol_exact",
            "excerpt": "public void Damage(float amount) { }",
            "chunk_id": "chunk_api_001",
            "document_id": "doc_api_001",
            "source_ref": "source_api_001",
            "source_hash": "sha256:source_api",
            "file_hash": "sha256:file_api",
            "doc_hash": "sha256:doc_api",
        }
    )
    proposal = PatchProposalBuilder().build(
        payload,
        evidence_pack=evidence_pack,
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    ).to_artifact_payload()

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=payload,
        evidence_pack=evidence_pack,
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert proposal["evidence_refs"] == ["ev_001", "ev_api_001"]
    assert proposal["diff_intent"][0]["supporting_binding_ids"] == [
        "support_binding_ev_api_001"
    ]
    assert review.allowed_next_stage == "dry_run_apply"


def test_reviewer_blocks_hook_change_without_hook_target_binding() -> None:
    payload = _implementation_payload()
    payload["evidence_source_paths"].append("decompiled/CrosshairGuiLayer.cs")
    payload["evidence_refs"].append("ev_api_001")
    payload["binding_registry"]["supporting_bindings"].append(_hook_target_binding())
    evidence_pack = _evidence_pack()
    evidence_pack["items"].append(_hook_target_evidence_item())
    proposal = PatchProposalBuilder().build(
        payload,
        evidence_pack=evidence_pack,
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    ).to_artifact_payload()

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=payload,
        evidence_pack=evidence_pack,
        feature_spec=_hook_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert review.allowed_next_stage is None
    assert any(
        finding.rule_id == "hook_target_binding"
        and finding.change_id == "chg_001"
        for finding in review.findings
    )


def test_reviewer_approves_selected_hook_target_binding() -> None:
    payload = _implementation_payload()
    payload["evidence_source_paths"].append("decompiled/CrosshairGuiLayer.cs")
    payload["evidence_refs"].append("ev_api_001")
    payload["binding_registry"]["supporting_bindings"].append(_hook_target_binding())
    payload["proposed_changes"][0]["hook_target_binding_id"] = "hook_target_001"
    payload["proposed_changes"][0]["rationale"] = (
        "hook enemy damage method for BetterHitFeedback"
    )
    evidence_pack = _evidence_pack()
    evidence_pack["items"].append(_hook_target_evidence_item())
    proposal = PatchProposalBuilder().build(
        payload,
        evidence_pack=evidence_pack,
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    ).to_artifact_payload()

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=payload,
        evidence_pack=evidence_pack,
        feature_spec=_hook_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert proposal["diff_intent"][0]["hook_target_binding_id"] == "hook_target_001"
    assert review.allowed_next_stage == "dry_run_apply"


def test_reviewer_blocks_hook_target_not_selected_by_plan() -> None:
    payload = _implementation_payload()
    payload["evidence_source_paths"].append("decompiled/CrosshairGuiLayer.cs")
    payload["evidence_refs"].append("ev_api_001")
    payload["binding_registry"]["supporting_bindings"].append(_hook_target_binding())
    payload["proposed_changes"][0]["rationale"] = (
        "hook enemy damage method for BetterHitFeedback"
    )
    evidence_pack = _evidence_pack()
    evidence_pack["items"].append(_hook_target_evidence_item())
    proposal = PatchProposalBuilder().build(
        payload,
        evidence_pack=evidence_pack,
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    ).to_artifact_payload()
    proposal["diff_intent"][0]["hook_target_binding_id"] = "hook_target_001"

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=payload,
        evidence_pack=evidence_pack,
        feature_spec=_hook_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert review.allowed_next_stage is None
    assert any(
        finding.rule_id == "hook_target_binding"
        and "was not selected" in finding.message
        for finding in review.findings
    )


def test_reviewer_blocks_forged_supporting_binding() -> None:
    payload = _implementation_payload()
    payload["binding_registry"]["supporting_bindings"].append(
        {
            "binding_id": "support_binding_forged",
            "evidence_id": "missing",
            "source_path": "forged.cs",
            "source_type": "decompiled_api",
            "target_symbol": "Forged",
            "target_span": {"start_line": 1, "end_line": 2},
            "usage": "hook_target_or_supporting_evidence",
        }
    )
    payload["proposed_changes"][0]["supporting_binding_ids"].append(
        "support_binding_forged"
    )
    proposal = PatchProposalBuilder().build(
        payload,
        evidence_pack=_evidence_pack(),
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    ).to_artifact_payload()

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=payload,
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert review.allowed_next_stage is None
    assert any(
        finding.rule_id == "binding_registry"
        and "Supporting binding evidence_id is not present" in finding.message
        for finding in review.findings
    )


def test_reviewer_blocks_missing_context_pack() -> None:
    proposal = _proposal_payload()
    proposal.pop("context_pack")

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "revise_proposal"
    assert review.allowed_next_stage is None
    assert any(finding.rule_id == "context_pack" for finding in review.findings)


def test_reviewer_blocks_change_unit_mismatch() -> None:
    proposal = _proposal_payload()
    proposal["change_units"][0]["change_unit_id"] = "different_change"

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "revise_proposal"
    assert review.allowed_next_stage is None
    assert any(finding.rule_id == "context_pack" for finding in review.findings)


def test_reviewer_blocks_context_pack_change_unit_id_drift() -> None:
    proposal = _proposal_payload()
    proposal["context_pack"]["change_unit_ids"] = ["different_change"]

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
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


def test_reviewer_blocks_missing_deep_context_bindings() -> None:
    proposal = _proposal_payload()
    proposal["context_pack"]["source_snippets"] = []
    proposal["context_pack"]["artifact_hashes"].pop("implementation_plan")
    proposal["context_pack"]["implementation_plan_hash"] = None
    proposal["context_pack"]["git_binding"] = {}

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    messages = {finding.message for finding in review.findings}
    assert review.decision == "revise_proposal"
    assert (
        "Proposal context_pack source_snippets do not cover proposal evidence refs."
        in messages
    )
    assert (
        "Proposal context_pack is missing required upstream artifact hash: implementation_plan."
        in messages
    )
    assert "Proposal context_pack implementation_plan_hash is not bound." in messages
    assert "Proposal context_pack is missing Git base revision binding." in messages


def test_reviewer_blocks_artifact_hash_drift() -> None:
    proposal = _proposal_payload()
    proposal["context_pack"]["artifact_hashes"]["evidence_pack"] = "sha256:stale"

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
    )

    assert review.decision == "revise_proposal"
    assert any(
        finding.message
        == "Proposal context_pack upstream artifact hash drifted: evidence_pack."
        for finding in review.findings
    )


def test_reviewer_blocks_forbidden_path() -> None:
    proposal = _proposal_payload()
    proposal["files"] = [".git/config"]
    proposal["diff_intent"][0]["target_file"] = ".git/config"

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
    )

    assert review.decision == "blocked_scope_risk"
    assert any(finding.rule_id == "forbidden_paths" for finding in review.findings)


def test_reviewer_blocks_wrong_permission_level() -> None:
    proposal = _proposal_payload()

    review = ProposalReviewer().review(
        proposal,
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
        permission_level="confirmed_write",
    )

    assert review.decision == "blocked_requires_human"
    assert any(finding.rule_id == "permission_level" for finding in review.findings)


def test_proposal_payloads_validate_against_artifact_contract(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    proposal = PatchProposalBuilder().build(
        _implementation_payload(),
        evidence_pack=_evidence_pack(),
        artifact_hashes=_artifact_hashes(),
        git_binding=_git_binding(),
        require_git_binding=True,
    )
    review = ProposalReviewer().review(
        proposal.to_artifact_payload(),
        implementation_plan=_implementation_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec=_feature_spec(),
        artifact_hashes=_artifact_hashes(),
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
