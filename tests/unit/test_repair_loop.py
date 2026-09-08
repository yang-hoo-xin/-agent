"""Tests for repair planning, retry budget, and review re-entry."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.bindings import (
    BindingResolver,
    resolve_runtime_diagnosis_binding,
)
from src.mod_agent.build import BuildAdapter, BuildProfile, BuildResult
from src.mod_agent.evidence import EvidenceItem, EvidencePack
from src.mod_agent.evidence.models import DETERMINISTIC_EVIDENCE_AUTHORITY
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.proposal import ProposalReviewer
from src.mod_agent.repair import RepairPatchProposalBuilder, RepairPlanner
from src.mod_agent.runtime import build_runtime_failure_ownership
from src.mod_agent.workflow import build_graph, create_initial_state
from src.mod_agent.workflow.transitions import (
    route_after_build,
    route_after_repair_plan,
    route_after_review,
    route_after_runtime_evidence,
)


def _proposal_git_binding() -> dict[str, object]:
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


def _proposal_context_pack(target_file: str = "mods/BetterHitFeedback/Plugin.cs") -> dict[str, object]:
    return {
        "feature_id": "feature_001",
        "files": [target_file],
        "evidence_refs": ["ev_001"],
        "evidence_source_paths": [target_file],
        "scope_boundary": ["Do not refactor unrelated files."],
        "change_unit_ids": ["chg_001"],
        "allowed_edit_binding_ids": ["edit_binding_001"],
    }


_REPAIR_SOURCE_BYTES = (
    "public sealed class Plugin\n{\n"
    + "\n" * 7
    + "    public void Load()\n    {\n"
    + "\n" * 6
    + "    }\n}\n"
).encode("utf-8")
_REPAIR_SOURCE_SHA256 = sha256(_REPAIR_SOURCE_BYTES).hexdigest()


def _implementation_plan_payload(target_file: str = "mods/BetterHitFeedback/Plugin.cs") -> dict[str, object]:
    return {
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "evidence_id": "ev_001",
                    "canonical_target_path": target_file,
                    "source_type": "target_source",
                    "source_hash": _REPAIR_SOURCE_SHA256,
                    "target_symbol": "Load",
                    "target_span": {"start_line": 10, "end_line": 18},
                }
            ],
            "supporting_bindings": [],
        },
    }


def _evidence_pack(target_file: str = "mods/BetterHitFeedback/Plugin.cs") -> dict[str, object]:
    return {
        "items": [
            {
                "evidence_id": "ev_001",
                "source_type": "target_source",
                "source_path": target_file,
                "source_hash": _REPAIR_SOURCE_SHA256,
                "symbol": "Load",
                "span": {"start_line": 10, "end_line": 18},
            }
        ]
    }


def test_failed_build_creates_evidence_bound_repair_plan() -> None:
    build_result = _failed_build_result(
        "feature_001",
        diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
    ).to_artifact_payload()

    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=build_result,
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=_implementation_plan_payload(),
    )
    payload = plan.to_artifact_payload()

    assert payload["failure_source"] == "build"
    assert payload["failure_class"] == "missing_reference"
    assert payload["evidence_refs"]
    assert "artifacts/features/feature_001/build_result.json" in payload["evidence_refs"]
    assert payload["minimal_changes"][0]["edit_binding_id"] == "edit_binding_001"
    assert payload["allowed_edit_binding_ids"] == ["edit_binding_001"]
    assert payload["display_files"] == ["mods/BetterHitFeedback/Plugin.cs"]
    assert payload["retry_count"] == 1
    assert payload["retry_budget"] == 2
    assert payload["retry_exhausted"] is False
    assert payload["allowed_next_stage"] == "generate_patch_proposal"
    assert payload["repair_context"]["repair_decision"] == "scoped_patch_repair"
    assert payload["repair_context"]["scoped_edit_binding_ids"] == [
        "edit_binding_001"
    ]


def test_build_diagnostics_for_one_binding_create_one_repair_change() -> None:
    build_result = _failed_build_result(
        "feature_001",
        diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
    ).to_artifact_payload()
    diagnostic = dict(build_result["diagnostics"][0])
    build_result["diagnostics"] = [
        {
            **diagnostic,
            "line": index + 1,
            "message": f"compiler failure {index}",
        }
        for index in range(14)
    ]

    payload = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=build_result,
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=_implementation_plan_payload(),
    ).to_artifact_payload()

    assert len(payload["minimal_changes"]) == 1
    change = payload["minimal_changes"][0]
    assert change["edit_binding_id"] == "edit_binding_001"
    assert change["failure_evidence_refs"] == [
        (
            "build_diag:"
            f"{index}:CS0246:mods/BetterHitFeedback/Plugin.cs:{index + 1}"
        )
        for index in range(14)
    ]
    assert payload["evidence_refs"] == [
        "artifacts/features/feature_001/build_result.json",
        *change["failure_evidence_refs"],
    ]
    assert payload["allowed_next_stage"] == "generate_patch_proposal"
    assert payload["blockers"] == []


def test_build_diagnostics_for_different_bindings_remain_separate() -> None:
    first_path = "mods/First/Plugin.cs"
    second_path = "mods/Second/Plugin.cs"
    build_result = _failed_build_result(
        "feature_001",
        diagnostic_file=first_path,
    ).to_artifact_payload()
    first = dict(build_result["diagnostics"][0])
    build_result["diagnostics"] = [
        first,
        {
            **first,
            "file": second_path,
            "line": 24,
            "message": "second binding failure",
        },
    ]
    implementation_plan = {
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "canonical_target_path": first_path,
                },
                {
                    "binding_id": "edit_binding_002",
                    "canonical_target_path": second_path,
                },
            ],
            "supporting_bindings": [],
        }
    }
    proposal_context = {
        **_proposal_context_pack(first_path),
        "files": [first_path, second_path],
        "allowed_edit_binding_ids": [
            "edit_binding_001",
            "edit_binding_002",
        ],
    }

    payload = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=build_result,
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        proposal_context_pack=proposal_context,
        implementation_plan=implementation_plan,
    ).to_artifact_payload()

    assert [
        change["edit_binding_id"] for change in payload["minimal_changes"]
    ] == ["edit_binding_001", "edit_binding_002"]
    assert [
        len(change["failure_evidence_refs"])
        for change in payload["minimal_changes"]
    ] == [1, 1]


def _single_load_evidence_pack_factory(source_path: str):
    """Keep legacy repair-route fixtures bound to one exact edit target."""

    def _factory(_state, _feature) -> EvidencePack:
        return EvidencePack(
            query="make Load enable diagnostics",
            readiness="sufficient",
            can_generate_patch=True,
            items=(
                EvidenceItem(
                    evidence_id="evidence_load_symbol_001",
                    source_type="target_source",
                    source_path=source_path,
                    symbol="Load",
                    span={"start_line": 3, "end_line": 3},
                    retrieval_method="symbol_exact",
                    score=1.0,
                    claim_supported="Symbol Load exists in Plugin.cs.",
                    excerpt="public void Load()",
                    source_hash="a" * 64,
                    authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
                ),
            ),
            retrieval_methods_used=("symbol_exact",),
        )

    return _factory


def test_retry_budget_exhaustion_blocks_repair_loop() -> None:
    build_result = _failed_build_result("feature_001").to_artifact_payload()

    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=build_result,
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=2,
        target_behavior="make Load enable diagnostics",
    )
    payload = plan.to_artifact_payload()

    assert payload["retry_exhausted"] is True
    assert payload["allowed_next_stage"] is None
    assert payload["blockers"][0]["code"] == "RETRY_BUDGET_EXHAUSTED"


def test_proposal_review_blockers_create_bounded_repair_context() -> None:
    review_payload = {
        "decision": "revise_proposal",
        "allowed_next_stage": None,
        "findings": [
            {
                "rule_id": "context_pack",
                "level": "blocking",
                "message": "Proposal context_pack is missing Git base revision binding.",
                "change_id": None,
                "evidence_refs": [],
            }
        ],
    }

    plan = RepairPlanner(retry_budget=2).from_review_failure(
        proposal_review=review_payload,
        proposal_review_ref="artifacts/features/feature_001/proposal_review.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=_implementation_plan_payload(),
    )
    payload = plan.to_artifact_payload()

    assert payload["failure_source"] == "proposal_review"
    assert payload["failure_class"] == "proposal_review:context_pack"
    assert payload["evidence_refs"] == [
        "artifacts/features/feature_001/proposal_review.json"
    ]
    assert payload["allowed_edit_binding_ids"] == ["edit_binding_001"]
    assert payload["display_files"] == ["mods/BetterHitFeedback/Plugin.cs"]
    assert payload["minimal_changes"] == []
    assert payload["allowed_next_stage"] is None
    assert payload["requires_new_evidence"] is False
    assert payload["failure_findings"] == review_payload["findings"]
    assert payload["repair_context"] == {
        "review_decision": "revise_proposal",
        "review_allowed_next_stage": None,
        "blocking_rule_ids": ["context_pack"],
        "repair_decision": "context_rebuild_required",
        "required_actions": [
            "rebuild_proposal_context",
            "regenerate_patch_proposal",
            "rerun_proposal_review",
        ],
        "reason": (
            "Proposal context must be rebuilt from existing authoritative "
            "artifacts before proposal regeneration."
        ),
        "scope_source": "patch_proposal.context_pack.allowed_edit_binding_ids",
    }
    assert payload["blockers"][0]["code"] == "REVIEW_REPLAN_REQUIRED"


def test_hook_binding_review_failure_requires_new_evidence() -> None:
    review_payload = {
        "decision": "revise_proposal",
        "allowed_next_stage": None,
        "findings": [
            {
                "rule_id": "hook_target_binding",
                "level": "blocking",
                "message": "Selected Hook target is not present in current evidence.",
                "change_id": "chg_001",
                "evidence_refs": ["ev_001"],
            }
        ],
    }

    payload = RepairPlanner(retry_budget=2).from_review_failure(
        proposal_review=review_payload,
        proposal_review_ref="artifacts/features/feature_001/proposal_review.json",
        retry_count=0,
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=_implementation_plan_payload(),
    ).to_artifact_payload()

    assert payload["requires_new_evidence"] is True
    assert payload["repair_context"]["repair_decision"] == (
        "evidence_retrieval_required"
    )
    assert payload["repair_context"]["required_actions"] == [
        "refresh_or_expand_evidence",
        "rebuild_implementation_plan",
        "regenerate_patch_proposal",
        "rerun_proposal_review",
    ]


def test_ownerless_runtime_failure_fails_closed_without_source_repair() -> None:
    payload = RepairPlanner(retry_budget=2).from_runtime_failure(
        runtime_evidence={
            "feature_id": "feature_001",
            "acceptance_status": "failed",
            "message": "Expected gameplay marker was not observed.",
            "evidence_items": [
                {
                    "source": "runtime_logs/gtfo.log",
                    "locator": "runtime_logs/gtfo.log:120",
                }
            ],
        },
        runtime_evidence_ref="artifacts/features/feature_001/runtime_evidence.json",
        retry_count=0,
        proposal_context_pack=_proposal_context_pack(),
    ).to_artifact_payload()

    assert payload["allowed_next_stage"] is None
    assert payload["minimal_changes"] == []
    assert payload["retry_count"] == 0
    assert payload["blockers"][0]["code"] == "RUNTIME_FAILURE_OWNER_UNKNOWN"
    assert payload["blockers"][0]["source_repair_allowed"] is False
    assert payload["repair_context"]["repair_decision"] == (
        "collect_failure_evidence"
    )
    assert payload["repair_context"]["failure_owner"] == "unknown"
    assert payload["repair_context"]["scoped_edit_binding_ids"] == []


def test_non_product_runtime_owners_cannot_enter_source_repair() -> None:
    blocker_codes = {
        "observation": "RUNTIME_OBSERVATION_REPAIR_REQUIRED",
        "environment": "RUNTIME_ENVIRONMENT_REPAIR_REQUIRED",
        "provider": "RUNTIME_PROVIDER_REPAIR_REQUIRED",
        "permission": "RUNTIME_PERMISSION_REQUIRED",
    }
    for owner, blocker_code in blocker_codes.items():
        payload = RepairPlanner(retry_budget=2).from_runtime_failure(
            runtime_evidence={
                "feature_id": "feature_001",
                "verification_status": "failed",
                "acceptance_status": "failed",
                "message": "Runtime failed.",
                "failure_ownership": build_runtime_failure_ownership(
                    owner=owner,
                    failure_class=f"{owner}_failed",
                    reason=f"{owner} owns this failure.",
                ),
                "evidence_items": [
                    {
                        "source": "mods/BetterHitFeedback/Plugin.cs",
                        "locator": "mods/BetterHitFeedback/Plugin.cs:12",
                    }
                ],
            },
            runtime_evidence_ref=(
                "artifacts/features/feature_001/runtime_evidence.json"
            ),
            retry_count=0,
            proposal_context_pack=_proposal_context_pack(),
        ).to_artifact_payload()

        assert payload["minimal_changes"] == []
        assert payload["retry_count"] == 0
        assert payload["allowed_next_stage"] is None
        assert payload["blockers"][0]["code"] == blocker_code
        assert payload["repair_context"]["failure_owner"] == owner
        assert payload["repair_context"]["source_repair_allowed"] is False


def test_product_behavior_owner_with_bound_source_can_enter_repair_review() -> None:
    payload = RepairPlanner(retry_budget=2).from_runtime_failure(
        runtime_evidence={
            "feature_id": "feature_001",
            "verification_status": "failed",
            "acceptance_status": "failed",
            "message": "Bound product behavior failed at Runtime.",
            "failure_ownership": build_runtime_failure_ownership(
                owner="product_behavior",
                failure_class="acceptance_behavior_failed",
                reason="A bound product behavior emitted an explicit failure.",
            ),
            "evidence_items": [
                {
                    "source": "mods/BetterHitFeedback/Plugin.cs",
                    "locator": "mods/BetterHitFeedback/Plugin.cs:12",
                }
            ],
        },
        runtime_evidence_ref="artifacts/features/feature_001/runtime_evidence.json",
        retry_count=0,
        proposal_context_pack=_proposal_context_pack(),
        resolved_repair_target={
            "schema_version": "resolved_repair_target_v1",
            "status": "resolved",
            "feature_id": "feature_001",
            "run_id": "run_001",
            "implementation_plan_revision": {
                "feature_id": "feature_001",
                "path": "implementation_plan.json",
                "artifact_hash": "plan_hash",
            },
            "diagnosis_schema_version": "runtime_failure_diagnosis_v1",
            "failure_class": "acceptance_behavior_failed",
            "responsibility_anchors": {
                "component": "plugin_load",
                "symbol": "Load",
                "dependency": "ConfigEnabled",
                "repair_scope": ["configuration_gate"],
                "source_hash": "source_hash",
                "source_span": {"start_line": 10, "end_line": 18},
            },
            "evidence_refs": [
                {
                    "source": "runtime_log",
                    "locator": "runtime.log",
                }
            ],
            "binding_id": "edit_binding_001",
            "canonical_target_path": "mods/BetterHitFeedback/Plugin.cs",
            "root_cause_status": "confirmed",
            "unresolved_root_causes": [],
            "blockers": [],
        },
    ).to_artifact_payload()

    assert payload["failure_class"] == "acceptance_behavior_failed"
    assert payload["minimal_changes"][0]["edit_binding_id"] == "edit_binding_001"
    assert payload["retry_count"] == 1
    assert payload["allowed_next_stage"] == "generate_patch_proposal"
    assert payload["blockers"] == []
    assert payload["repair_context"]["failure_owner"] == "product_behavior"
    assert payload["repair_context"]["source_repair_allowed"] is True
    assert payload["repair_context"]["repair_decision"] == "scoped_patch_repair"


def test_current_stagger_diagnosis_blocks_mismatched_symbol_and_span() -> None:
    target_file = "Patches/HitFeedbackBehaviorPatch.cs"
    proposal_context = _proposal_context_pack(target_file)
    proposal_context["allowed_edit_binding_ids"] = ["edit_binding_002"]
    implementation_plan = {
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_002",
                    "evidence_id": "stagger_visual_source",
                    "canonical_target_path": target_file,
                    "source_type": "target_source",
                    "source_hash": (
                        "92EAB8010EED49E8C84094DC6EB5376D"
                        "5F995414C40CF7D2C44FC1955D405E1A"
                    ),
                    "target_symbol": (
                        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                        "AddParallelMarkerPair"
                    ),
                    "target_span": {"start_line": 881, "end_line": 907},
                }
            ],
            "supporting_bindings": [],
        }
    }
    diagnosis = {
        "feature_id": "feature_001",
        "schema_version": "stagger_runtime_failure_diagnosis_v1",
        "status": "diagnosed",
        "failure_class": "product_behavior",
        "evidence_refs": [
            {
                "source": "gtfo_persistent_log",
                "locator": "BepInEx/LogOutput.log",
            }
        ],
        "responsibility_anchors": {
            "component": "ui_attachment",
            "symbol": (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                "TrySpawnStaggerYellowX"
            ),
            "dependency": "HUD RectTransform",
            "repair_scope": [
                "hud_root_acquisition",
                "canvas_binding",
            ],
            "source_hash": None,
            "source_span": None,
        },
        "root_cause_status": "unresolved",
        "unresolved_root_causes": ["hud_parent_runtime_type_mismatch"],
    }
    resolved = BindingResolver.from_implementation_plan(
        implementation_plan
    ).resolve_repair_target(
        diagnosis=diagnosis,
        feature_id="feature_001",
        run_id="run_001",
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        allowed_binding_ids={"edit_binding_002"},
    )
    assert resolved.status == "blocked"
    assert resolved.binding_id is None
    assert [item["code"] for item in resolved.blockers] == [
        "REPAIR_TARGET_SYMBOL_UNRESOLVED",
        "DIAGNOSIS_SOURCE_IDENTITY_INCOMPLETE",
    ]
    payload = RepairPlanner(retry_budget=2).from_runtime_failure(
        runtime_evidence={
            "feature_id": "feature_001",
            "verification_status": "failed",
            "failure_ownership": build_runtime_failure_ownership(
                owner="product_behavior",
                failure_class="product_behavior",
                reason="The Stagger visual requirement is false.",
            ),
            "evidence_items": diagnosis["evidence_refs"],
        },
        runtime_evidence_ref=(
            "artifacts/features/feature_001/runtime_evidence.json"
        ),
        retry_count=0,
        proposal_context_pack=proposal_context,
        resolved_repair_target=resolved.to_dict(),
    ).to_artifact_payload()

    assert payload["minimal_changes"] == []
    assert payload["allowed_next_stage"] is None
    assert payload["allowed_edit_binding_ids"] == []
    assert payload["display_files"] == []
    assert [item["code"] for item in payload["blockers"]] == [
        "REPAIR_TARGET_SYMBOL_UNRESOLVED",
        "DIAGNOSIS_SOURCE_IDENTITY_INCOMPLETE",
    ]


def test_runtime_diagnosis_reports_binding_gap_without_granting_authority() -> None:
    implementation_plan = {
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_002",
                    "evidence_id": "stagger_visual_source",
                    "canonical_target_path": (
                        "Patches/HitFeedbackBehaviorPatch.cs"
                    ),
                    "source_hash": "OLD_SOURCE_HASH",
                    "target_symbol": (
                        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                        "AddParallelMarkerPair"
                    ),
                    "target_span": {"start_line": 881, "end_line": 907},
                }
            ],
            "supporting_bindings": [],
        }
    }
    diagnosis = {
        "schema_version": "stagger_runtime_failure_diagnosis_v1",
        "status": "diagnosed",
        "feature_id": "feature_001",
        "failure_class": "product_behavior",
        "evidence_refs": [
            {
                "source": "gtfo_persistent_log",
                "locator": "BepInEx/LogOutput.log",
            }
        ],
        "responsibility_anchors": {
            "component": "ui_attachment",
            "symbol": (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                "TrySpawnStaggerYellowX"
            ),
            "dependency": "HUD RectTransform",
            "repair_scope": ["canvas_binding"],
            "source_hash": None,
            "source_span": None,
        },
        "root_cause_status": "unresolved",
        "unresolved_root_causes": [
            "hud_parent_runtime_type_mismatch"
        ],
    }
    result = resolve_runtime_diagnosis_binding(
        diagnosis=diagnosis,
        feature_id="feature_001",
        run_id="run_001",
        runtime_evidence_revision={
            "feature_id": "feature_001",
            "path": "runtime_evidence.json",
            "artifact_hash": "runtime_hash",
        },
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        patch_proposal_revision={
            "feature_id": "feature_001",
            "path": "patch_proposal.json",
            "artifact_hash": "proposal_hash",
        },
        implementation_plan=implementation_plan,
        allowed_edit_binding_ids={"edit_binding_002"},
    ).to_artifact_payload()

    assert result["result_type"] == "binding_gap"
    assert result["resolved_repair_target"] is None
    assert result["binding_gap"]["gap"] is True
    assert result["binding_gap"]["gap_reasons"] == [
        "missing_symbol_binding",
        "diagnosis_source_identity_incomplete",
    ]
    assert result["binding_gap"]["existing_allowed_bindings"] == [
        {
            "binding_id": "edit_binding_002",
            "canonical_target_path": (
                "Patches/HitFeedbackBehaviorPatch.cs"
            ),
            "target_symbol": (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                "AddParallelMarkerPair"
            ),
            "target_span": {"start_line": 881, "end_line": 907},
            "source_hash": "OLD_SOURCE_HASH",
            "evidence_id": "stagger_visual_source",
        }
    ]
    request = result["binding_proposal_request"]
    assert request["status"] == "requested"
    assert request["approval_required"] is True
    assert request["registry_mutation_allowed"] is False
    assert request["repair_allowed"] is False
    assert result["blockers"][0]["code"] == "BINDING_GAP"


def test_invalid_diagnosis_lineage_does_not_request_binding_expansion() -> None:
    result = resolve_runtime_diagnosis_binding(
        diagnosis={
            "schema_version": "stagger_runtime_failure_diagnosis_v1",
            "status": "diagnosed",
            "feature_id": "other_feature",
            "failure_class": "product_behavior",
            "evidence_refs": [],
            "responsibility_anchors": {},
        },
        feature_id="feature_001",
        run_id="run_001",
        runtime_evidence_revision={
            "feature_id": "feature_001",
            "path": "runtime_evidence.json",
            "artifact_hash": "runtime_hash",
        },
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        patch_proposal_revision={
            "feature_id": "feature_001",
            "path": "patch_proposal.json",
            "artifact_hash": "proposal_hash",
        },
        implementation_plan={"binding_registry": {"edit_bindings": []}},
        allowed_edit_binding_ids=set(),
    ).to_artifact_payload()

    assert result["result_type"] == "binding_resolution_blocked"
    assert result["binding_gap"] is None
    assert result["binding_proposal_request"] is None
    assert result["blockers"][0]["code"] == (
        "BINDING_RESOLUTION_INPUT_INVALID"
    )


def test_invalid_artifact_lineage_does_not_request_binding_expansion() -> None:
    result = resolve_runtime_diagnosis_binding(
        diagnosis={
            "schema_version": "stagger_runtime_failure_diagnosis_v1",
            "status": "diagnosed",
            "feature_id": "feature_001",
            "failure_class": "product_behavior",
            "evidence_refs": [
                {
                    "source": "gtfo_persistent_log",
                    "locator": "BepInEx/LogOutput.log",
                }
            ],
            "responsibility_anchors": {
                "component": "ui_attachment",
                "symbol": (
                    "BetterHitFeedback.Patches."
                    "HitFeedbackBehaviorPatch.TrySpawnStaggerYellowX"
                ),
                "dependency": "HUD RectTransform",
                "repair_scope": ["canvas_binding"],
                "source_hash": None,
                "source_span": None,
            },
        },
        feature_id="feature_001",
        run_id="run_001",
        runtime_evidence_revision={
            "feature_id": "other_feature",
            "path": "runtime_evidence.json",
            "artifact_hash": "runtime_hash",
        },
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        patch_proposal_revision={
            "feature_id": "feature_001",
            "path": "patch_proposal.json",
            "artifact_hash": "proposal_hash",
        },
        implementation_plan={"binding_registry": {"edit_bindings": []}},
        allowed_edit_binding_ids=set(),
    ).to_artifact_payload()

    assert result["result_type"] == "binding_resolution_blocked"
    assert result["binding_gap"] is None
    assert result["binding_proposal_request"] is None
    assert result["blockers"] == [
        {
            "stage": "binding_resolution",
            "code": "BINDING_RESOLUTION_LINEAGE_INVALID",
            "message": (
                "Runtime binding resolution requires current feature/run "
                "identity and bound RuntimeEvidence, ImplementationPlan, and "
                "PatchProposal revisions."
            ),
            "invalid_revision_types": ["runtime_evidence"],
        }
    ]


def test_resolver_can_resolve_exact_current_symbol_hash_and_span() -> None:
    target_file = "Patches/HitFeedbackBehaviorPatch.cs"
    current_hash = "CURRENT_SOURCE_HASH"
    binding_span = {"start_line": 973, "end_line": 1040}
    failure_span = {"start_line": 979, "end_line": 983}
    implementation_plan = {
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_002",
                    "canonical_target_path": target_file,
                    "source_hash": current_hash,
                    "target_symbol": (
                        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                        "TrySpawnStaggerYellowX"
                    ),
                    "target_span": binding_span,
                }
            ],
            "supporting_bindings": [],
        }
    }
    diagnosis = {
        "schema_version": "stagger_runtime_failure_diagnosis_v1",
        "status": "diagnosed",
        "feature_id": "feature_001",
        "failure_class": "product_behavior",
        "evidence_refs": [
            {
                "source": "gtfo_persistent_log",
                "locator": "BepInEx/LogOutput.log",
            }
        ],
        "responsibility_anchors": {
            "component": "ui_attachment",
            "symbol": (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                "TrySpawnStaggerYellowX"
            ),
            "dependency": "HUD RectTransform",
            "repair_scope": ["canvas_binding"],
            "source_hash": current_hash,
            "source_span": failure_span,
        },
        "root_cause_status": "unresolved",
        "unresolved_root_causes": ["hud_parent_runtime_type_mismatch"],
    }
    resolved = BindingResolver.from_implementation_plan(
        implementation_plan
    ).resolve_repair_target(
        diagnosis=diagnosis,
        feature_id="feature_001",
        run_id="run_001",
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        allowed_binding_ids={"edit_binding_002"},
    )

    assert resolved.status == "resolved"
    assert resolved.binding_id == "edit_binding_002"
    assert resolved.canonical_target_path == target_file
    assert resolved.blockers == ()

    payload = RepairPlanner(retry_budget=2).from_runtime_failure(
        runtime_evidence={
            "feature_id": "feature_001",
            "verification_status": "failed",
            "failure_ownership": build_runtime_failure_ownership(
                owner="product_behavior",
                failure_class="product_behavior",
                reason="The Stagger visual requirement is false.",
            ),
            "evidence_items": diagnosis["evidence_refs"],
        },
        runtime_evidence_ref=(
            "artifacts/features/feature_001/runtime_evidence.json"
        ),
        retry_count=0,
        proposal_context_pack={
            **_proposal_context_pack(target_file),
            "allowed_edit_binding_ids": ["edit_binding_002"],
        },
        resolved_repair_target=resolved.to_dict(),
    ).to_artifact_payload()

    assert payload["minimal_changes"][0]["edit_binding_id"] == "edit_binding_002"
    assert payload["allowed_edit_binding_ids"] == ["edit_binding_002"]
    assert payload["allowed_next_stage"] is None
    assert payload["blockers"][0]["code"] == "RUNTIME_ROOT_CAUSE_UNRESOLVED"
    assert payload["requires_new_evidence"] is True


def test_resolver_blocks_multiple_exact_allowed_bindings() -> None:
    symbol = (
        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
        "TrySpawnStaggerYellowX"
    )
    source_hash = "CURRENT_SOURCE_HASH"
    binding_span = {"start_line": 973, "end_line": 1040}
    failure_span = {"start_line": 979, "end_line": 983}
    resolver = BindingResolver(
        binding_registry={
            "schema_version": "binding_registry_v1",
            "edit_bindings": [
                {
                    "binding_id": binding_id,
                    "canonical_target_path": path,
                    "source_hash": source_hash,
                    "target_symbol": symbol,
                    "target_span": binding_span,
                }
                for binding_id, path in (
                    ("edit_binding_002", "Patches/HitFeedbackBehaviorPatch.cs"),
                    ("edit_binding_004", "Patches/OtherPatch.cs"),
                )
            ],
            "supporting_bindings": [],
        }
    )
    result = resolver.resolve_repair_target(
        diagnosis={
            "schema_version": "stagger_runtime_failure_diagnosis_v1",
            "status": "diagnosed",
            "feature_id": "feature_001",
            "failure_class": "product_behavior",
            "evidence_refs": [
                {
                    "source": "gtfo_persistent_log",
                    "locator": "BepInEx/LogOutput.log",
                }
            ],
            "responsibility_anchors": {
                "component": "ui_attachment",
                "symbol": symbol,
                "dependency": "HUD RectTransform",
                "repair_scope": ["canvas_binding"],
                "source_hash": source_hash,
                "source_span": failure_span,
            },
            "root_cause_status": "unresolved",
            "unresolved_root_causes": ["hud_parent_runtime_type_mismatch"],
        },
        feature_id="feature_001",
        run_id="run_001",
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        allowed_binding_ids={"edit_binding_002", "edit_binding_004"},
    )

    assert result.status == "blocked"
    assert result.binding_id is None
    assert [item["code"] for item in result.blockers] == [
        "REPAIR_TARGET_SYMBOL_AMBIGUOUS"
    ]


def test_resolver_blocks_failure_span_outside_exact_symbol_binding() -> None:
    symbol = (
        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
        "TrySpawnStaggerYellowX"
    )
    source_hash = "CURRENT_SOURCE_HASH"
    result = BindingResolver(
        binding_registry={
            "schema_version": "binding_registry_v1",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_002",
                    "canonical_target_path": (
                        "Patches/HitFeedbackBehaviorPatch.cs"
                    ),
                    "source_hash": source_hash,
                    "target_symbol": symbol,
                    "target_span": {"start_line": 973, "end_line": 1040},
                }
            ],
            "supporting_bindings": [],
        }
    ).resolve_repair_target(
        diagnosis={
            "schema_version": "stagger_runtime_failure_diagnosis_v1",
            "status": "diagnosed",
            "feature_id": "feature_001",
            "failure_class": "product_behavior",
            "evidence_refs": [
                {
                    "source": "gtfo_persistent_log",
                    "locator": "BepInEx/LogOutput.log",
                }
            ],
            "responsibility_anchors": {
                "component": "ui_attachment",
                "symbol": symbol,
                "dependency": "HUD RectTransform",
                "repair_scope": ["canvas_binding"],
                "source_hash": source_hash,
                "source_span": {"start_line": 1041, "end_line": 1044},
            },
            "root_cause_status": "unresolved",
            "unresolved_root_causes": ["hud_parent_runtime_type_mismatch"],
        },
        feature_id="feature_001",
        run_id="run_001",
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        allowed_binding_ids={"edit_binding_002"},
    )

    assert result.status == "blocked"
    assert result.binding_id is None
    assert [item["code"] for item in result.blockers] == [
        "REPAIR_TARGET_SOURCE_OR_SPAN_DRIFT"
    ]


def test_binding_gap_classifies_hash_and_span_drift_separately() -> None:
    symbol = (
        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
        "TrySpawnStaggerYellowX"
    )
    result = resolve_runtime_diagnosis_binding(
        diagnosis={
            "schema_version": "stagger_runtime_failure_diagnosis_v1",
            "status": "diagnosed",
            "feature_id": "feature_001",
            "failure_class": "product_behavior",
            "evidence_refs": [
                {
                    "source": "gtfo_persistent_log",
                    "locator": "BepInEx/LogOutput.log",
                }
            ],
            "responsibility_anchors": {
                "component": "ui_attachment",
                "symbol": symbol,
                "dependency": "HUD RectTransform",
                "repair_scope": ["canvas_binding"],
                "source_hash": "CURRENT_SOURCE_HASH",
                "source_span": {"start_line": 1041, "end_line": 1044},
            },
            "root_cause_status": "unresolved",
            "unresolved_root_causes": [
                "hud_parent_runtime_type_mismatch"
            ],
        },
        feature_id="feature_001",
        run_id="run_001",
        runtime_evidence_revision={
            "feature_id": "feature_001",
            "path": "runtime_evidence.json",
            "artifact_hash": "runtime_hash",
        },
        implementation_plan_revision={
            "feature_id": "feature_001",
            "path": "implementation_plan.json",
            "artifact_hash": "plan_hash",
        },
        patch_proposal_revision={
            "feature_id": "feature_001",
            "path": "patch_proposal.json",
            "artifact_hash": "proposal_hash",
        },
        implementation_plan={
            "binding_registry": {
                "schema_version": "binding_registry_v1",
                "edit_bindings": [
                    {
                        "binding_id": "edit_binding_002",
                        "canonical_target_path": (
                            "Patches/HitFeedbackBehaviorPatch.cs"
                        ),
                        "source_hash": "OLD_SOURCE_HASH",
                        "target_symbol": symbol,
                        "target_span": {
                            "start_line": 973,
                            "end_line": 1040,
                        },
                    }
                ],
                "supporting_bindings": [],
            }
        },
        allowed_edit_binding_ids={"edit_binding_002"},
    ).to_artifact_payload()

    assert result["result_type"] == "binding_gap"
    assert result["binding_gap"]["gap_reasons"] == [
        "source_hash_mismatch",
        "failure_span_outside_edit_scope",
    ]


def test_repair_proposal_reenters_review_gate() -> None:
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result(
            "feature_001",
            diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
        ).to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=_implementation_plan_payload(),
    ).to_artifact_payload()

    proposal = RepairPatchProposalBuilder().build(plan).to_artifact_payload()
    review = ProposalReviewer().review(
        proposal,
        repair_plan=plan,
        implementation_plan=_implementation_plan_payload(),
        evidence_pack=_evidence_pack(),
        feature_spec={"target_behavior": "make Load enable diagnostics"},
        permission_level="dry_run_write",
    )

    assert proposal["blocked"] is False
    assert proposal["diff_intent"][0]["edit_binding_id"] == "edit_binding_001"
    assert review.allowed_next_stage == "dry_run_apply"
    assert review.trace_metrics["num_changes_checked"] == 1


def test_repair_proposal_reuses_non_hook_plan_validation_contract() -> None:
    implementation_plan = _implementation_plan_payload()
    implementation_plan["proposed_changes"] = [
        {
            "change_id": "chg_001",
            "change_type": "repair_helper",
            "edit_binding_id": "edit_binding_001",
            "hook_target_binding_id": None,
            "supporting_binding_ids": [],
            "operation": "replace_helper_expression_only",
            "expected_validation": ["compile", "runtime regression"],
            "rollback_hint": "Restore the helper expression.",
        }
    ]
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result(
            "feature_001",
            diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
        ).to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=implementation_plan,
    ).to_artifact_payload()

    proposal = RepairPatchProposalBuilder().build(
        plan,
        implementation_plan=implementation_plan,
    ).to_artifact_payload()
    review = ProposalReviewer().review(
        proposal,
        repair_plan=plan,
        implementation_plan=implementation_plan,
        evidence_pack=_evidence_pack(),
        feature_spec={
            "target_behavior": "make Load enable diagnostics",
            "hook_requirement": {
                "required": True,
                "reason": "existing product hook remains in scope",
            },
        },
        permission_level="dry_run_write",
    )

    assert proposal["diff_intent"][0]["hook_target_binding_id"] is None
    assert proposal["diff_intent"][0]["operation"] == (
        "replace_helper_expression_only"
    )
    assert proposal["diff_intent"][0]["expected_validation"] == [
        "compile",
        "runtime regression",
    ]
    assert review.allowed_next_stage == "dry_run_apply"
    assert not any(
        finding.rule_id in {"hook_target_binding", "validation_contract"}
        for finding in review.findings
    )


def test_repair_proposal_cannot_bypass_required_hook_binding() -> None:
    implementation_plan = _implementation_plan_payload()
    implementation_plan["binding_registry"]["supporting_bindings"] = [
        {
            "binding_id": "hook_target_001",
            "evidence_id": "ev_hook_001",
            "source_path": "decompiled/EnemyHook.cs",
            "source_type": "decompiled_api",
            "target_symbol": "EnemyHook.Apply",
            "target_span": {"start_line": 20, "end_line": 30},
            "declaring_type": "EnemyHook",
            "method_name": "Apply",
            "parameter_types": [],
            "return_type": "System.Void",
            "method_kind": "instance_method",
            "retrieval_method": "symbol_exact",
            "claim_supported": "EnemyHook.Apply is the selected Hook.",
            "authority": "mod_agent_deterministic",
            "usage": "hook_target",
        }
    ]
    implementation_plan["proposed_changes"] = [
        {
            "change_id": "chg_001",
            "change_type": "repair_hook",
            "edit_binding_id": "edit_binding_001",
            "hook_target_binding_id": "hook_target_001",
            "supporting_binding_ids": ["hook_target_001"],
            "operation": "repair_hook_behavior",
            "expected_validation": ["compile"],
            "rollback_hint": "Restore the Hook behavior.",
        }
    ]
    evidence_pack = _evidence_pack()
    evidence_pack["items"].append(
        {
            "evidence_id": "ev_hook_001",
            "source_type": "decompiled_api",
            "source_path": "decompiled/EnemyHook.cs",
            "symbol": "EnemyHook.Apply",
            "span": {"start_line": 20, "end_line": 30},
            "declaring_type": "EnemyHook",
            "method_name": "Apply",
            "parameter_types": [],
            "return_type": "System.Void",
            "method_kind": "instance_method",
        }
    )
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result(
            "feature_001",
            diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
        ).to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=implementation_plan,
    ).to_artifact_payload()

    proposal = RepairPatchProposalBuilder().build(
        plan,
        implementation_plan=implementation_plan,
    ).to_artifact_payload()
    assert proposal["diff_intent"][0]["hook_target_binding_id"] == (
        "hook_target_001"
    )

    for invalid_hook_id in (None, "hook_target_wrong"):
        invalid = json.loads(json.dumps(proposal))
        invalid["diff_intent"][0]["hook_target_binding_id"] = invalid_hook_id
        review = ProposalReviewer().review(
            invalid,
            repair_plan=plan,
            implementation_plan=implementation_plan,
            evidence_pack=evidence_pack,
            feature_spec={
                "target_behavior": "make Load enable diagnostics",
                "hook_requirement": {
                    "required": True,
                    "reason": "repair changes the selected Hook",
                },
            },
            permission_level="dry_run_write",
        )

        assert review.allowed_next_stage is None
        assert any(
            finding.rule_id == "hook_target_binding"
            for finding in review.findings
        )


def test_repair_proposal_blocks_unplanned_hook_binding() -> None:
    implementation_plan = _implementation_plan_payload()
    implementation_plan["binding_registry"]["supporting_bindings"] = [
        {
            "binding_id": "hook_target_001",
            "evidence_id": "ev_hook_001",
            "source_path": "decompiled/EnemyHook.cs",
            "source_type": "decompiled_api",
            "target_symbol": "EnemyHook.Apply",
            "target_span": {"start_line": 20, "end_line": 30},
            "declaring_type": "EnemyHook",
            "method_name": "Apply",
            "parameter_types": [],
            "return_type": "System.Void",
            "method_kind": "instance_method",
            "retrieval_method": "symbol_exact",
            "claim_supported": "EnemyHook.Apply is available but not selected.",
            "authority": "mod_agent_deterministic",
            "usage": "hook_target",
        }
    ]
    implementation_plan["proposed_changes"] = [
        {
            "change_id": "chg_001",
            "change_type": "repair_helper",
            "edit_binding_id": "edit_binding_001",
            "hook_target_binding_id": None,
            "supporting_binding_ids": [],
            "operation": "replace_helper_expression_only",
            "expected_validation": ["compile"],
            "rollback_hint": "Restore the helper expression.",
        }
    ]
    evidence_pack = _evidence_pack()
    evidence_pack["items"].append(
        {
            "evidence_id": "ev_hook_001",
            "source_type": "decompiled_api",
            "source_path": "decompiled/EnemyHook.cs",
            "symbol": "EnemyHook.Apply",
            "span": {"start_line": 20, "end_line": 30},
            "declaring_type": "EnemyHook",
            "method_name": "Apply",
            "parameter_types": [],
            "return_type": "System.Void",
            "method_kind": "instance_method",
        }
    )
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result(
            "feature_001",
            diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
        ).to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=implementation_plan,
    ).to_artifact_payload()
    proposal = RepairPatchProposalBuilder().build(
        plan,
        implementation_plan=implementation_plan,
    ).to_artifact_payload()
    proposal["diff_intent"][0]["hook_target_binding_id"] = "hook_target_001"

    review = ProposalReviewer().review(
        proposal,
        repair_plan=plan,
        implementation_plan=implementation_plan,
        evidence_pack=evidence_pack,
        feature_spec={
            "target_behavior": "make Load enable diagnostics",
            "hook_requirement": {
                "required": True,
                "reason": "the product contains an existing Hook",
            },
        },
        permission_level="dry_run_write",
    )

    assert review.allowed_next_stage is None
    assert any(
        finding.rule_id == "hook_target_binding"
        and "was not selected" in finding.message
        for finding in review.findings
    )


def test_repair_proposal_blocks_duplicate_plan_changes_for_one_binding() -> None:
    implementation_plan = _implementation_plan_payload()
    implementation_plan["proposed_changes"] = [
        {
            "change_id": "chg_001",
            "edit_binding_id": "edit_binding_001",
            "expected_validation": ["compile"],
        },
        {
            "change_id": "chg_002",
            "edit_binding_id": "edit_binding_001",
            "expected_validation": ["runtime regression"],
        },
    ]
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result(
            "feature_001",
            diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
        ).to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=implementation_plan,
    ).to_artifact_payload()

    proposal = RepairPatchProposalBuilder().build(
        plan,
        implementation_plan=implementation_plan,
    ).to_artifact_payload()

    assert proposal["blocked"] is True
    assert proposal["diff_intent"] == []
    assert proposal["blockers"] == [
        {
            "code": "REPAIR_PLAN_BINDING_AMBIGUOUS",
            "message": (
                "Repair Proposal cannot select among multiple "
                "ImplementationPlan changes for one edit binding."
            ),
            "binding_id": "edit_binding_001",
        }
    ]


def test_repair_proposal_reuses_existing_executable_patch_injection() -> None:
    implementation_plan = _implementation_plan_payload()
    implementation_plan["proposed_changes"] = [
        {
            "change_id": "chg_001",
            "change_type": "repair_helper",
            "edit_binding_id": "edit_binding_001",
            "hook_target_binding_id": None,
            "supporting_binding_ids": [],
            "operation": "replace_helper_expression_only",
            "expected_validation": ["compile"],
            "rollback_hint": "Restore the helper expression.",
            "patch": {
                "kind": "exact_text_replace",
                "before_text": "old helper",
                "after_text": "new helper",
                "expected_occurrences": 1,
            },
        }
    ]
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result(
            "feature_001",
            diagnostic_file="mods/BetterHitFeedback/Plugin.cs",
        ).to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=implementation_plan,
    ).to_artifact_payload()

    proposal = RepairPatchProposalBuilder().build(
        plan,
        implementation_plan=implementation_plan,
    ).to_artifact_payload()

    assert proposal["diff_intent"][0]["patch"] == {
        "kind": "exact_text_replace",
        "before_text": "old helper",
        "after_text": "new helper",
        "expected_occurrences": 1,
    }


def test_repair_plan_blocks_scope_outside_original_proposal_context() -> None:
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result("feature_001").to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack("mods/OtherMod/OtherPlugin.cs"),
        implementation_plan=_implementation_plan_payload("mods/OtherMod/OtherPlugin.cs"),
    ).to_artifact_payload()

    assert plan["allowed_next_stage"] is None
    assert plan["minimal_changes"] == []
    assert plan["blockers"][0]["code"] == "REPAIR_SCOPE_UNRESOLVED"


def test_repair_plan_blocks_short_filename_scope_guess() -> None:
    plan = RepairPlanner(retry_budget=2).from_build_failure(
        build_result=_failed_build_result("feature_001").to_artifact_payload(),
        build_result_ref="artifacts/features/feature_001/build_result.json",
        retry_count=0,
        target_behavior="make Load enable diagnostics",
        proposal_context_pack=_proposal_context_pack(),
        implementation_plan=_implementation_plan_payload(),
    ).to_artifact_payload()

    assert plan["allowed_next_stage"] is None
    assert plan["minimal_changes"] == []
    assert plan["blockers"][0]["code"] == "REPAIR_SCOPE_UNRESOLVED"


def test_repair_routes_are_explicit() -> None:
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
    )
    state["build_summary"] = {"status": "failed"}
    assert route_after_build(state) == "repair"

    state["build_summary"] = {"status": "success"}
    assert route_after_build(state) == "continue"

    state["runtime_summary"] = {
        "status": "failed",
        "acceptance_status": "failed",
        "acceptance_verified": False,
    }
    assert route_after_runtime_evidence(state) == "repair"

    state["runtime_summary"] = {
        "status": "inconclusive",
        "acceptance_status": "inconclusive",
        "acceptance_verified": False,
    }
    assert route_after_runtime_evidence(state) == "repair"

    state["runtime_summary"] = {
        "status": "failed",
        "acceptance_status": "failed",
        "acceptance_verified": False,
        "has_structured_diagnosis": True,
        "failure_ownership": build_runtime_failure_ownership(
            owner="product_behavior",
            failure_class="product_behavior",
            reason="A diagnosed product behavior failed.",
        ),
    }
    assert route_after_runtime_evidence(state) == "binding_resolution"

    for failure_ownership in (
        build_runtime_failure_ownership(
            owner="observation",
            failure_class="observation_incomplete",
            reason="Runtime observation is incomplete.",
        ),
        {
            **build_runtime_failure_ownership(
                owner="product_behavior",
                failure_class="product_behavior",
                reason="A diagnosed product behavior failed.",
            ),
            "source_repair_allowed": False,
        },
        None,
        "malformed",
    ):
        state["runtime_summary"] = {
            "status": "failed",
            "acceptance_status": "failed",
            "acceptance_verified": False,
            "has_structured_diagnosis": True,
            "failure_ownership": failure_ownership,
        }
        assert route_after_runtime_evidence(state) == "repair"

    state["runtime_summary"] = {
        "status": "verified",
        "acceptance_status": "accepted",
        "acceptance_verified": True,
    }
    assert route_after_runtime_evidence(state) == "continue"

    state["blockers"] = [{"code": "RETRY_BUDGET_EXHAUSTED"}]
    assert route_after_repair_plan(state) == "blocked"

    state["blockers"] = []
    state["review_summary"] = {
        "decision": "revise_proposal",
        "allowed_next_stage": None,
    }
    assert route_after_review(state) == "repair"

    state["review_summary"] = {
        "decision": "blocked_scope_risk",
        "allowed_next_stage": None,
    }
    assert route_after_review(state) == "blocked"


def test_graph_repair_reuses_plan_validation_before_second_build_failure(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    diagnostic_file = str(tmp_path / "source" / "Plugin.cs")

    def build_result_factory(
        feature_id: str,
        input_execution_mode: str | None = None,
    ) -> BuildResult:
        return _failed_build_result(
            feature_id,
            input_execution_mode=input_execution_mode,
            diagnostic_file=diagnostic_file,
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        evidence_pack_factory=_single_load_evidence_pack_factory(diagnostic_file),
        build_result_factory=build_result_factory,
        proposal_git_binding_factory=_proposal_git_binding,
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)
    repair_plan = _artifact_data(store, result, "repair_plan")
    repair_envelope = json.loads(
        Path(result["artifacts"]["repair_plan"]).read_text(encoding="utf-8")
    )
    patch_upstreams = [
        upstream
        for upstream in repair_envelope["inputs"]["upstream_artifacts"]
        if upstream["artifact_type"] == "patch_proposal"
    ]

    assert result["current_stage"] == "blocked"
    assert "repair_plan" in result["artifacts"]
    assert repair_plan["failure_source"] == "build"
    assert repair_plan["failure_class"] == "missing_reference"
    assert repair_plan["retry_exhausted"] is True
    assert repair_plan["allowed_next_stage"] is None
    assert repair_plan["blockers"][0]["code"] == "RETRY_BUDGET_EXHAUSTED"
    assert repair_plan["source_proposal"]["ref"] == (
        result["artifacts"]["patch_proposal"]
    )
    assert len(patch_upstreams) == 1
    assert patch_upstreams[0]["require_latest"] is False
    assert patch_upstreams[0]["path"] == repair_plan["source_proposal"]["ref"]
    assert patch_upstreams[0]["artifact_hash"] == repair_plan["source_proposal"]["hash"]
    assert result["retry_count"] == 2
    proposal_reviews = store.list_feature_artifact_revisions(
        str(result["feature_id"]),
        "proposal_review",
    )
    build_results = store.list_feature_artifact_revisions(
        str(result["feature_id"]),
        "build_result",
    )
    assert len(proposal_reviews) == 3
    assert len(build_results) == 3
    finished_nodes = [
        event["node_name"]
        for event in result["trace_events"]
        if event["event_type"] == "node_finished"
    ]
    first_build_index = finished_nodes.index("build")
    second_review_index = finished_nodes.index(
        "review_proposal",
        first_build_index + 1,
    )
    second_build_index = finished_nodes.index("build", first_build_index + 1)
    assert first_build_index < second_review_index < second_build_index
    assert any(
        event["node_name"] == "create_repair_plan"
        and event["event_type"] == "node_finished"
        for event in result["trace_events"]
    )
    assert result["blockers"][-1]["code"] == "RETRY_BUDGET_EXHAUSTED"


def test_graph_records_subsequent_repair_proposal_review_failure_owner(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    diagnostic_file = str(tmp_path / "source" / "Plugin.cs")

    def build_result_factory(
        feature_id: str,
        input_execution_mode: str | None = None,
    ) -> BuildResult:
        return _failed_build_result(
            feature_id,
            input_execution_mode=input_execution_mode,
            diagnostic_file=diagnostic_file,
        )

    def patch_change_factory(
        state: dict[str, object],
        implementation_plan: dict[str, object],
        evidence_pack: dict[str, object],
    ) -> list[dict[str, object]]:
        del evidence_pack
        changes = json.loads(
            json.dumps(implementation_plan["proposed_changes"])
        )
        assert len(changes) == 1
        changes[0]["patch"] = {
            "kind": "exact_text_replace",
            "before_text": "public void Load()",
            "after_text": "public void Load() /* reviewed repair test */",
            "expected_occurrences": 1,
        }
        if state["current_stage"] == "repair_plan":
            changes[0]["expected_validation"] = []
        return changes

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        evidence_pack_factory=_single_load_evidence_pack_factory(diagnostic_file),
        build_result_factory=build_result_factory,
        proposal_git_binding_factory=_proposal_git_binding,
        patch_change_factory=patch_change_factory,
    )
    result = graph.invoke(
        create_initial_state(
            run_id="run_repair_review_failure",
            request_id="req_repair_review_failure",
            user_request="make Load enable diagnostics",
            target_mod="BetterHitFeedback",
        )
    )

    repair_plan = _artifact_data(store, result, "repair_plan")
    build_results = store.list_feature_artifact_revisions(
        str(result["feature_id"]),
        "build_result",
    )
    patch_proposals = store.list_feature_artifact_revisions(
        str(result["feature_id"]),
        "patch_proposal",
    )
    proposal_reviews = store.list_feature_artifact_revisions(
        str(result["feature_id"]),
        "proposal_review",
    )

    assert result["current_stage"] == "blocked"
    assert len(build_results) == 1
    assert len(patch_proposals) == 2
    assert len(proposal_reviews) == 2
    assert repair_plan["failure_source"] == "proposal_review"
    assert repair_plan["failure_class"] == "proposal_review:validation_contract"
    assert repair_plan["source_proposal"]["ref"] == (
        result["artifacts"]["patch_proposal"]
    )
    assert repair_plan["allowed_next_stage"] is None
    assert repair_plan["blockers"][0]["code"] == "REVIEW_REPLAN_REQUIRED"


def test_graph_review_revision_creates_repair_plan_without_success_artifacts(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        proposal_git_binding_factory=lambda: {
            "status": "unavailable",
            "base_revision": None,
            "error": "not inside a Git working tree",
        },
    )
    state = create_initial_state(
        run_id="run_review_repair_context",
        request_id="req_review_repair_context",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    repair_plan = _artifact_data(store, result, "repair_plan")
    review = _artifact_data(store, result, "proposal_review")
    repair_envelope = json.loads(
        Path(result["artifacts"]["repair_plan"]).read_text(encoding="utf-8")
    )
    upstream_types = {
        upstream["artifact_type"]
        for upstream in repair_envelope["inputs"]["upstream_artifacts"]
    }
    patch_upstreams = [
        upstream
        for upstream in repair_envelope["inputs"]["upstream_artifacts"]
        if upstream["artifact_type"] == "patch_proposal"
    ]

    assert review["decision"] == "revise_proposal"
    assert result["current_stage"] == "blocked"
    assert "repair_plan" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]
    assert repair_plan["failure_source"] == "proposal_review"
    assert repair_plan["failure_class"] == "proposal_review:context_pack"
    assert repair_plan["minimal_changes"] == []
    assert repair_plan["allowed_next_stage"] is None
    assert repair_plan["repair_context"]["repair_decision"] == (
        "context_rebuild_required"
    )
    assert repair_plan["source_proposal"]["ref"] == result["artifacts"]["patch_proposal"]
    assert upstream_types == {"patch_proposal", "proposal_review"}
    assert len(patch_upstreams) == 1
    assert patch_upstreams[0]["require_latest"] is False
    assert patch_upstreams[0]["path"] == repair_plan["source_proposal"]["ref"]
    assert patch_upstreams[0]["artifact_hash"] == repair_plan["source_proposal"]["hash"]


def _failed_build_result(
    feature_id: str,
    input_execution_mode: str | None = None,
    diagnostic_file: str = "Plugin.cs",
) -> BuildResult:
    profile = BuildProfile(
        profile_id="test_profile",
        build_system="dotnet",
        working_directory="generated_mods/TestMod",
        command=("dotnet", "build"),
        timeout_seconds=120,
        expected_artifacts=("bin/Debug/TestMod.dll",),
    )
    result = BuildAdapter().from_supplied_output(
        feature_id=feature_id,
        profile=profile,
        exit_code=1,
        stderr=(
            f"{diagnostic_file}(12,7): error CS0246: "
            "The type or namespace name 'Foo' could not be found"
        ),
    )
    if input_execution_mode is None:
        return result
    return result


def _knowledge_with_load_symbol(tmp_path: Path) -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / "source"
    root.mkdir()
    (root / "Plugin.cs").write_text(
        """
public class Plugin
{
    public void Load()
    {
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )
    IncrementalIndexer(database=db, source_registry=registry).index_source("target_mod")
    return db


def _artifact_data(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
) -> dict[str, object]:
    for ref in store.list_feature_artifacts(str(result["feature_id"])):
        if ref.artifact_type == artifact_type:
            return store.read(ref)["data"]
    raise AssertionError(f"Missing artifact: {artifact_type}")
