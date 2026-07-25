"""Tests for repair planning, retry budget, and review re-entry."""

from __future__ import annotations

import json
from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.build import BuildAdapter, BuildProfile, BuildResult
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
        implementation_plan=_implementation_plan_payload(),
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
            implementation_plan=_implementation_plan_payload(),
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
        implementation_plan=_implementation_plan_payload(),
    ).to_artifact_payload()

    assert payload["failure_class"] == "acceptance_behavior_failed"
    assert payload["minimal_changes"][0]["edit_binding_id"] == "edit_binding_001"
    assert payload["retry_count"] == 1
    assert payload["allowed_next_stage"] == "generate_patch_proposal"
    assert payload["blockers"] == []
    assert payload["repair_context"]["failure_owner"] == "product_behavior"
    assert payload["repair_context"]["source_repair_allowed"] is True
    assert payload["repair_context"]["repair_decision"] == "scoped_patch_repair"


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


def test_graph_repair_uses_current_proposal_review_failure_owner(tmp_path: Path) -> None:
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
    assert repair_plan["failure_source"] == "proposal_review"
    assert repair_plan["failure_class"] == "proposal_review:validation_contract"
    assert repair_plan["retry_exhausted"] is False
    assert repair_plan["allowed_next_stage"] is None
    assert repair_plan["blockers"][0]["code"] == "REVIEW_REPLAN_REQUIRED"
    assert repair_plan["source_proposal"]["ref"] == (
        result["artifacts"]["patch_proposal"]
    )
    assert len(patch_upstreams) == 1
    assert patch_upstreams[0]["require_latest"] is False
    assert patch_upstreams[0]["path"] == repair_plan["source_proposal"]["ref"]
    assert patch_upstreams[0]["artifact_hash"] == repair_plan["source_proposal"]["hash"]
    assert result["retry_count"] == 2
    assert any(
        event["node_name"] == "create_repair_plan"
        and event["event_type"] == "node_finished"
        for event in result["trace_events"]
    )
    assert result["blockers"][-1]["code"] == "REVIEW_REPLAN_REQUIRED"


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
