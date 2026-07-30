"""LangGraph StateGraph construction for the controlled development workflow."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.bindings import resolve_runtime_diagnosis_binding
from src.mod_agent.build import BuildResult, build_fake_build_result
from src.mod_agent.domain import (
    GTFO_DOMAIN_NAME,
    DomainAdapterRegistry,
    DomainReviewPolicy,
    GTFOAdapter,
    UnsupportedDomainAdapter,
)
from src.mod_agent.evaluation import build_transition_eval_gate_report
from src.mod_agent.evidence import (
    DenseRetrievalProvider,
    DeterministicEvidenceRetriever,
    EvidencePack,
    EvidenceRequest,
)
from src.mod_agent.execution import ExactDiffApprovalRejectedError
from src.mod_agent.git import GitCommandError, GitRepository
from src.mod_agent.knowledge import (
    CollectionResolutionError,
    CollectionResolver,
    KnowledgeDatabase,
)
from src.mod_agent.planning import (
    FeatureSpec,
    FeatureSpecBuilder,
    ImplementationPlanner,
    ModPlanningBriefBuilder,
    RequestPlan,
    RequestPlanner,
    Uncertainty,
)
from src.mod_agent.proposal import (
    CRITIC_DIMENSIONS,
    CriticAssessment,
    CriticFinding,
    PatchProposalBuilder,
    ProposalCritic,
    ProposalReviewer,
)
from src.mod_agent.repair import RepairPatchProposalBuilder, RepairPlanner
from src.mod_agent.runtime import (
    build_fake_runtime_evidence_payload,
    make_gtfo_runtime_evidence_factory_from_settings,
)
from src.mod_agent.runtime.evidence import bind_runtime_evidence_context
from src.mod_agent.runtime.stagger_edit_authority import (
    materialize_stagger_edit_authority_approval,
)

from .checkpointing import WorkflowCheckpointStore
from .interrupts import InterruptRequest, ResumePayload
from .nodes import StubNodeRunner
from .state import ModAgentState
from .transitions import (
    route_after_build,
    route_after_binding_resolution,
    route_after_dry_run,
    route_after_evaluate,
    route_after_evidence,
    route_after_feature_spec,
    route_after_human_review_gate,
    route_after_implementation_plan,
    route_after_isolated_apply,
    route_after_patch_proposal,
    route_after_plan_request,
    route_after_planning_brief,
    route_after_repair_plan,
    route_after_review,
    route_after_runtime_evidence,
    route_registry,
)

GraphNode = Callable[[ModAgentState], ModAgentState]
BuildResultFactory = Callable[[str, str | None], BuildResult]
RuntimeEvidenceFactory = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
EvaluationContextFactory = Callable[[ModAgentState], dict[str, Any]]
ProposalGitBindingFactory = Callable[[], dict[str, Any]]
EvidencePackFactory = Callable[[ModAgentState, dict[str, Any]], EvidencePack]
PatchChangeFactory = Callable[
    [ModAgentState, dict[str, Any], dict[str, Any]], tuple[dict[str, Any], ...]
]
PatchExecutionFactory = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]
]
CriticRequirement = Literal["not_required", "required"]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_EXISTING_BINDING_REAUTHORIZATION_REQUEST_SCHEMA = (
    "stagger_existing_binding_reauthorization_request_v1"
)
_STAGGER_HUD_PARENT_OBSERVATION_REQUEST_SCHEMA = (
    "stagger_hud_parent_observation_authority_request_v1"
)
_STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA = (
    "stagger_hud_parent_diagnostic_execution_authority_request_v2"
)


def build_graph(
    artifact_store: ArtifactStore,
    *,
    settings: Any | None = None,
    knowledge_database: KnowledgeDatabase | None = None,
    collection_id: str | None = None,
    collection_resolver: CollectionResolver | None = None,
    dense_provider: DenseRetrievalProvider | None = None,
    dense_enabled: bool = False,
    dense_required: bool = False,
    dense_top_k: int | None = None,
    domain_adapter_registry: DomainAdapterRegistry | None = None,
    domain_review_policy: DomainReviewPolicy | None = None,
    build_result_factory: BuildResultFactory | None = None,
    runtime_evidence_factory: RuntimeEvidenceFactory | None = None,
    allow_game_launch: bool = False,
    proposal_git_binding_factory: ProposalGitBindingFactory | None = None,
    use_default_proposal_git_binding: bool = True,
    evidence_pack_factory: EvidencePackFactory | None = None,
    patch_change_factory: PatchChangeFactory | None = None,
    proposal_source_snippet_char_limit: int = 6000,
    proposal_critic: ProposalCritic | None = None,
    critic_requirement: CriticRequirement = "not_required",
    dry_run_factory: PatchExecutionFactory | None = None,
    isolated_apply_factory: PatchExecutionFactory | None = None,
    stop_after_evidence: bool = False,
    stop_after_build: bool = False,
    persist_build_runtime_handoff: bool = False,
    runtime_continuation_checkpoint_id: str | None = None,
    edit_authority_request_ref: ArtifactRef | None = None,
    evaluation_context_factory: EvaluationContextFactory | None = None,
    require_external_evaluation: bool = False,
    require_review_approval_for_dry_run: bool = False,
    enable_dynamic_review_interrupt: bool = False,
    checkpointer: Any | None = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
):
    """Build a compiled LangGraph graph with real planning/review routing.

    Planning, evidence retrieval, implementation planning, patch proposal, and
    review are real controlled nodes. Dry-run remains fake; build and runtime
    evidence can be injected for controlled contract tests.
    """

    if (
        enable_dynamic_review_interrupt
        or edit_authority_request_ref is not None
    ) and checkpointer is None:
        raise ValueError(
            "Human approval interrupts require a LangGraph checkpointer."
        )
    if (
        runtime_continuation_checkpoint_id is not None
        and edit_authority_request_ref is not None
    ):
        raise ValueError(
            "Runtime continuation and Edit Authority approval cannot share "
            "one graph entry."
        )
    if persist_build_runtime_handoff and not stop_after_build:
        raise ValueError(
            "Build-to-Runtime handoff persistence requires stop_after_build=True."
        )
    if require_external_evaluation and evaluation_context_factory is None:
        raise ValueError("require_external_evaluation requires evaluation_context_factory")
    if (
        isinstance(proposal_source_snippet_char_limit, bool)
        or not isinstance(proposal_source_snippet_char_limit, int)
        or proposal_source_snippet_char_limit <= 0
    ):
        raise ValueError("proposal_source_snippet_char_limit must be a positive integer.")
    if critic_requirement not in {"not_required", "required"}:
        raise ValueError(
            "critic_requirement must be exactly 'not_required' or 'required'."
        )
    if critic_requirement == "not_required" and proposal_critic is not None:
        raise ValueError(
            "proposal_critic requires critic_requirement='required'; "
            "implicit triggering is not supported."
        )
    if domain_review_policy is not None and domain_adapter_registry is not None:
        raise ValueError(
            "domain_review_policy and domain_adapter_registry cannot both "
            "be supplied."
        )

    stub_runner = StubNodeRunner(artifact_store)
    effective_domain_registry = domain_adapter_registry or _default_domain_adapter_registry()
    effective_runtime_evidence_factory = (
        runtime_evidence_factory
        or _runtime_evidence_factory_from_settings(
            settings,
            allow_game_launch=allow_game_launch,
        )
    )
    effective_proposal_git_binding_factory = proposal_git_binding_factory
    if effective_proposal_git_binding_factory is None and use_default_proposal_git_binding:
        effective_proposal_git_binding_factory = _default_proposal_git_binding_factory
    graph = StateGraph(ModAgentState)

    graph.add_node(
        "plan_request",
        _make_real_graph_node(
            "plan_request",
            lambda state: _run_plan_request(state, artifact_store),
        ),
    )
    graph.add_node(
        "draft_feature_spec",
        _make_real_graph_node(
            "draft_feature_spec",
            lambda state: _run_draft_feature_spec(state, artifact_store),
        ),
    )
    graph.add_node(
        "planning_brief",
        _make_real_graph_node(
            "planning_brief",
            lambda state: _run_planning_brief(state, artifact_store),
        ),
    )
    graph.add_node(
        "retrieve_evidence",
        _make_real_graph_node(
            "retrieve_evidence",
            lambda state: _run_retrieve_evidence(
                state,
                artifact_store,
                knowledge_database,
                collection_id,
                collection_resolver,
                dense_provider,
                dense_enabled,
                dense_required,
                dense_top_k,
                evidence_pack_factory,
            ),
        ),
    )
    graph.add_node(
        "create_implementation_plan",
        _make_real_graph_node(
            "create_implementation_plan",
            lambda state: _run_create_implementation_plan(state, artifact_store),
        ),
    )
    graph.add_node(
        "generate_patch_proposal",
        _make_real_graph_node(
            "generate_patch_proposal",
            lambda state: _run_generate_patch_proposal(
                state,
                artifact_store,
                proposal_git_binding_factory=effective_proposal_git_binding_factory,
                patch_change_factory=patch_change_factory,
                source_snippet_char_limit=proposal_source_snippet_char_limit,
            ),
        ),
    )
    graph.add_node(
        "review_proposal",
        _make_real_graph_node(
            "review_proposal",
            lambda state: _run_review_proposal(
                state,
                artifact_store,
                domain_adapter_registry=effective_domain_registry,
                domain_review_policy=domain_review_policy,
                require_executable_patch=patch_change_factory is not None,
                proposal_critic=proposal_critic,
                critic_requirement=critic_requirement,
            ),
        ),
    )
    if enable_dynamic_review_interrupt:
        graph.add_node(
            "human_review_gate",
            _make_real_graph_node(
                "human_review_gate",
                lambda state: _run_dynamic_human_review_gate(state, artifact_store),
            ),
        )
    if edit_authority_request_ref is not None:
        graph.add_node(
            "stagger_edit_authority_gate",
            _make_real_graph_node(
                "stagger_edit_authority_gate",
                lambda state: _run_stagger_edit_authority_gate(
                    state,
                    artifact_store,
                    edit_authority_request_ref,
                ),
            ),
        )

    graph.add_node(
        "dry_run_apply",
        _make_real_graph_node(
            "dry_run_apply",
            lambda state: _run_dry_run_apply(
                state,
                artifact_store,
                require_review_approval=require_review_approval_for_dry_run,
                dry_run_factory=dry_run_factory,
            ),
        ),
    )
    if isolated_apply_factory is not None:
        graph.add_node(
            "isolated_apply",
            _make_real_graph_node(
                "isolated_apply",
                lambda state: _run_isolated_apply(
                    state,
                    artifact_store,
                    isolated_apply_factory=isolated_apply_factory,
                ),
            ),
        )
    graph.add_node(
        "build",
        _make_real_graph_node(
            "build",
            lambda state: _run_build(
                state,
                artifact_store,
                build_result_factory,
                persist_build_runtime_handoff=persist_build_runtime_handoff,
            ),
        ),
    )
    graph.add_node(
        "collect_runtime_evidence",
        _make_real_graph_node(
            "collect_runtime_evidence",
            lambda state: _run_runtime_evidence(
                state,
                artifact_store,
                effective_runtime_evidence_factory,
            ),
        ),
    )
    graph.add_node(
        "evaluate",
        _make_real_graph_node(
            "evaluate",
            lambda state: _run_fake_evaluate(
                state,
                artifact_store,
                evaluation_context_factory,
                require_external_evaluation,
            ),
        ),
    )
    graph.add_node(
        "create_repair_plan",
        _make_real_graph_node(
            "create_repair_plan",
            lambda state: _run_create_repair_plan(state, artifact_store),
        ),
    )
    graph.add_node(
        "resolve_runtime_binding",
        _make_real_graph_node(
            "resolve_runtime_binding",
            lambda state: _run_resolve_runtime_binding(
                state,
                artifact_store,
            ),
        ),
    )
    graph.add_node(
        "done",
        _make_real_graph_node(
            "done",
            lambda state: _run_workflow_summary(state, artifact_store),
        ),
    )
    graph.add_node("blocked", _make_stub_graph_node("blocked", stub_runner))

    if edit_authority_request_ref is not None:
        graph.add_edge(START, "stagger_edit_authority_gate")
    elif runtime_continuation_checkpoint_id is None:
        graph.add_edge(START, "plan_request")
    else:
        graph.add_conditional_edges(
            START,
            lambda state: _route_runtime_continuation_entry(
                state,
                artifact_store,
                checkpoint_id=runtime_continuation_checkpoint_id,
            ),
            {
                "continue": "collect_runtime_evidence",
            },
        )
    registry = route_registry()
    graph.add_conditional_edges(
        "plan_request",
        route_after_plan_request,
        dict(registry["plan_request"]),
    )
    graph.add_conditional_edges(
        "planning_brief",
        route_after_planning_brief,
        dict(registry["planning_brief"]),
    )
    graph.add_conditional_edges(
        "draft_feature_spec",
        route_after_feature_spec,
        dict(registry["draft_feature_spec"]),
    )
    if stop_after_evidence:
        graph.add_conditional_edges(
            "retrieve_evidence",
            route_after_evidence,
            {"continue": END, "blocked": END},
        )
    else:
        graph.add_conditional_edges(
            "retrieve_evidence",
            route_after_evidence,
            dict(registry["retrieve_evidence"]),
        )
    graph.add_conditional_edges(
        "create_implementation_plan",
        route_after_implementation_plan,
        dict(registry["create_implementation_plan"]),
    )
    graph.add_conditional_edges(
        "generate_patch_proposal",
        route_after_patch_proposal,
        dict(registry["generate_patch_proposal"]),
    )
    graph.add_conditional_edges(
        "review_proposal",
        route_after_review,
        _review_route_map(
            registry["review_proposal"],
            enable_dynamic_review_interrupt=enable_dynamic_review_interrupt,
        ),
    )
    if enable_dynamic_review_interrupt:
        graph.add_conditional_edges(
            "human_review_gate",
            route_after_human_review_gate,
            dict(registry["human_review_gate"]),
        )
    if edit_authority_request_ref is not None:
        graph.add_edge("stagger_edit_authority_gate", END)
    dry_run_routes = dict(registry["dry_run_apply"])
    if isolated_apply_factory is not None:
        dry_run_routes["continue"] = "isolated_apply"
    graph.add_conditional_edges(
        "dry_run_apply",
        route_after_dry_run,
        dry_run_routes,
    )
    if isolated_apply_factory is not None:
        graph.add_conditional_edges(
            "isolated_apply",
            route_after_isolated_apply,
            dict(registry["isolated_apply"]),
        )
    if stop_after_build:
        graph.add_conditional_edges(
            "build",
            route_after_build,
            {"continue": END, "repair": END},
        )
    else:
        graph.add_conditional_edges(
            "build",
            route_after_build,
            dict(registry["build"]),
        )
    graph.add_conditional_edges(
        "collect_runtime_evidence",
        route_after_runtime_evidence,
        dict(registry["collect_runtime_evidence"]),
    )
    graph.add_conditional_edges(
        "resolve_runtime_binding",
        route_after_binding_resolution,
        dict(registry["resolve_runtime_binding"]),
    )
    graph.add_conditional_edges(
        "create_repair_plan",
        route_after_repair_plan,
        dict(registry["create_repair_plan"]),
    )
    for node_name in [
        "evaluate",
    ]:
        graph.add_conditional_edges(
            node_name,
            route_after_evaluate,
            dict(registry[node_name]),
        )
    graph.add_edge("done", END)
    graph.add_edge("blocked", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )


def _review_route_map(
    route_map: dict[str, str] | Any,
    *,
    enable_dynamic_review_interrupt: bool,
) -> dict[str, str]:
    mapped = dict(route_map)
    if enable_dynamic_review_interrupt:
        mapped["continue"] = "human_review_gate"
    return mapped


def _make_real_graph_node(node_name: str, run: GraphNode) -> GraphNode:
    def _node(state: ModAgentState) -> ModAgentState:
        started = _trace_event(
            state=state,
            node_name=node_name,
            event_type="node_started",
            status="started",
            artifact_refs=[],
            summary=f"{node_name} started.",
        )
        state_with_start = _copy_state_with_trace(state, started)
        result = run(state_with_start)
        finished = _trace_event(
            state=result,
            node_name=node_name,
            event_type="node_finished",
            status=_node_status(result, node_name),
            artifact_refs=_node_artifact_refs(result, node_name),
            summary=f"{node_name} completed.",
            details=_node_trace_details(result, node_name),
        )
        return _copy_state_with_trace(result, finished)

    return _node


def _make_stub_graph_node(node_name: str, runner: StubNodeRunner) -> GraphNode:
    def _node(state: ModAgentState) -> ModAgentState:
        started = _trace_event(
            state=state,
            node_name=node_name,
            event_type="node_started",
            status="started",
            artifact_refs=[],
            summary=f"{node_name} started.",
        )
        state_with_start = _copy_state_with_trace(state, started)
        result = runner.run(node_name, state_with_start)
        finished_state = _copy_state_with_trace(
            result.state,
            result.trace_event.to_dict(),
        )
        return finished_state

    return _node


def _run_plan_request(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    plan = RequestPlanner().plan(
        state["user_request"],
        target_mod=state["target_mod"],
    )
    artifact_ref = artifact_store.write(
        feature_id=plan.feature_id,
        artifact_type="request_planning_report",
        payload=plan.to_artifact_payload(),
        status="blocked" if plan.blocked else "success",
    )
    next_state = _copy_state(state)
    next_state["feature_id"] = plan.feature_id
    next_state["target_mod"] = plan.target_mod
    next_state["execution_path"] = plan.route
    next_state["risk_level"] = plan.risk_level
    next_state["current_stage"] = "request_planning"
    _record_artifact(next_state, "request_planning_report", artifact_ref)
    next_state["warnings"].extend(
        uncertainty.to_dict()
        for uncertainty in plan.uncertainties
        if uncertainty.severity != "blocking"
    )
    if plan.blocked:
        next_state["blockers"].extend(
            {
                "stage": "request_planning",
                "code": uncertainty.uncertainty_id.upper(),
                "message": uncertainty.question,
            }
            for uncertainty in plan.uncertainties
            if uncertainty.severity == "blocking"
        )
    return next_state


def _run_draft_feature_spec(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    plan_data = _read_artifact_data(state, artifact_store, "request_planning_report")
    plan = _request_plan_from_payload(plan_data)
    planning_brief = _read_artifact_data(state, artifact_store, "mod_planning_brief")
    feature_spec = FeatureSpecBuilder().build(
        plan,
        planning_brief=planning_brief,
    )
    artifact_ref = artifact_store.write(
        feature_id=feature_spec.feature_id,
        artifact_type="feature_spec",
        payload=feature_spec.to_artifact_payload(),
        status="blocked" if feature_spec.blocked else "success",
        upstream_refs=[
            _artifact_ref_from_state(state, "request_planning_report"),
            _artifact_ref_from_state(state, "mod_planning_brief"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "feature_spec"
    _record_artifact(next_state, "feature_spec", artifact_ref)
    if feature_spec.blocked:
        next_state["blockers"].extend(feature_spec.blockers)
    return next_state


def _run_retrieve_evidence(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    knowledge_database: KnowledgeDatabase | None,
    collection_id: str | None,
    collection_resolver: CollectionResolver | None,
    dense_provider: DenseRetrievalProvider | None,
    dense_enabled: bool,
    dense_required: bool,
    dense_top_k: int | None,
    evidence_pack_factory: EvidencePackFactory | None,
) -> ModAgentState:
    feature_data = _read_artifact_data(state, artifact_store, "feature_spec")
    if evidence_pack_factory is not None:
        pack = evidence_pack_factory(state, feature_data)
    elif knowledge_database is None:
        from src.mod_agent.evidence import EvidencePack

        pack = EvidencePack.empty(
            query=str(feature_data.get("target_behavior") or state["user_request"]),
            reason="Knowledge database is not configured for this graph run.",
        )
    else:
        request = EvidenceRequest(
            query=str(feature_data.get("target_behavior") or state["user_request"]),
            execution_path=state["execution_path"] or "standard_feature",
            requires_hook_evidence=(
                "target method" in feature_data.get("evidence_requirements", [])
            ),
            hook_requirement=_hook_requirement_from_payload(feature_data),
        )
        try:
            pack = DeterministicEvidenceRetriever(
                knowledge_database,
                collection_id=collection_id,
                collection_resolver=collection_resolver,
                dense_provider=dense_provider,
                dense_enabled=dense_enabled,
                dense_required=dense_required,
                dense_top_k=dense_top_k,
            ).retrieve(request)
        except CollectionResolutionError as exc:
            from src.mod_agent.evidence import EvidencePack

            pack = EvidencePack.empty(
                query=request.query,
                reason=f"Collection resolution failed: {exc}",
            )
    artifact_ref = artifact_store.write(
        feature_id=state["feature_id"] or state["request_id"],
        artifact_type="evidence_pack",
        payload=pack.to_artifact_payload(),
        status="success" if pack.can_generate_patch else "blocked",
        upstream_refs=[_artifact_ref_from_state(state, "feature_spec")],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "evidence_retrieval"
    next_state["evidence_summary"] = {
        "readiness": pack.readiness,
        "can_generate_patch": pack.can_generate_patch,
        "num_items": len(pack.items),
        "gaps": list(pack.gaps),
        "retrieval_methods_used": list(pack.retrieval_methods_used),
        "missing_evidence": list(pack.missing_evidence),
        "disabled_modes": dict(pack.disabled_modes),
        "timing": dict(pack.timing),
    }
    _record_artifact(next_state, "evidence_pack", artifact_ref)
    if not pack.can_generate_patch:
        next_state["blockers"].extend(pack.blockers)
    return next_state


def _run_create_implementation_plan(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    feature_spec = _feature_spec_from_payload(
        _read_artifact_data(state, artifact_store, "feature_spec")
    )
    evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
    implementation = ImplementationPlanner().build(
        feature_spec=feature_spec,
        evidence_pack=evidence_pack,
    )
    artifact_ref = artifact_store.write(
        feature_id=implementation.feature_id,
        artifact_type="implementation_plan",
        payload=implementation.to_artifact_payload(),
        status="blocked" if implementation.blocking else "success",
        upstream_refs=[
            _artifact_ref_from_state(state, "feature_spec"),
            _artifact_ref_from_state(state, "evidence_pack"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "implementation_plan"
    _record_artifact(next_state, "implementation_plan", artifact_ref)
    if implementation.blocking:
        next_state["blockers"].extend(implementation.blockers)
    return next_state


def _run_generate_patch_proposal(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    proposal_git_binding_factory: ProposalGitBindingFactory | None = None,
    patch_change_factory: PatchChangeFactory | None = None,
    source_snippet_char_limit: int = 6000,
) -> ModAgentState:
    if state["current_stage"] == "repair_plan" and "repair_plan" in state["artifacts"]:
        repair_plan = _read_artifact_data(state, artifact_store, "repair_plan")
        proposal = RepairPatchProposalBuilder().build(repair_plan)
        upstream_refs = [
            _artifact_ref_from_state(state, "implementation_plan"),
            _artifact_ref_from_state(state, "repair_plan"),
            _artifact_ref_from_state(state, "evidence_pack"),
        ]
    else:
        implementation = _read_artifact_data(state, artifact_store, "implementation_plan")
        evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
        if patch_change_factory is not None:
            implementation = {
                **implementation,
                "proposed_changes": list(
                    patch_change_factory(state, implementation, evidence_pack)
                ),
            }
        proposal = PatchProposalBuilder().build(
            implementation,
            evidence_pack=evidence_pack,
            artifact_hashes=dict(state["artifact_hashes"]),
            git_binding=(
                proposal_git_binding_factory()
                if proposal_git_binding_factory is not None
                else None
            ),
            require_git_binding=proposal_git_binding_factory is not None,
            source_snippet_char_limit=source_snippet_char_limit,
        )
        upstream_refs = [
            _artifact_ref_from_state(state, "implementation_plan"),
            _artifact_ref_from_state(state, "evidence_pack"),
        ]
    artifact_ref = artifact_store.write(
        feature_id=proposal.feature_id,
        artifact_type="patch_proposal",
        payload=proposal.to_artifact_payload(),
        status="blocked" if proposal.blocked else "success",
        upstream_refs=upstream_refs,
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "patch_proposal"
    _record_artifact(next_state, "patch_proposal", artifact_ref)
    if proposal.blocked:
        next_state["blockers"].extend(proposal.blockers)
    return next_state


def _default_proposal_git_binding_factory() -> dict[str, Any]:
    try:
        snapshot = _project_git_repository().working_tree_snapshot()
    except GitCommandError as exc:
        return {
            "status": "unavailable",
            "base_revision": None,
            "error": str(exc),
        }
    return {
        "status": "available",
        "base_revision": snapshot.base_revision,
        "branch": snapshot.branch,
        "is_dirty": snapshot.is_dirty,
        "diff_hash": snapshot.diff_hash,
        "dirty_tree_policy": snapshot.dirty_tree_policy,
    }


def _project_git_repository() -> GitRepository:
    base_repository = GitRepository(_PROJECT_ROOT)
    git_dir = _PROJECT_ROOT / ".git"
    return GitRepository(
        _PROJECT_ROOT,
        git_executable=(
            *base_repository.git_command,
            "--git-dir",
            str(git_dir),
            "--work-tree",
            str(_PROJECT_ROOT),
        ),
    )


def _run_review_proposal(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    domain_adapter_registry: DomainAdapterRegistry | None = None,
    domain_review_policy: DomainReviewPolicy | None = None,
    require_executable_patch: bool = False,
    proposal_critic: ProposalCritic | None = None,
    critic_requirement: CriticRequirement = "not_required",
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    implementation_plan = _read_artifact_data(
        state,
        artifact_store,
        "implementation_plan",
    )
    evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    repair_plan = (
        _read_artifact_data(state, artifact_store, "repair_plan")
        if "repair_plan" in state["artifacts"]
        else None
    )
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    critic_payload: dict[str, Any] | None = None
    critic_ref: ArtifactRef | None = None
    if critic_requirement == "required" and proposal_critic is not None:
        try:
            critic_assessment = proposal_critic.assess(
                proposal,
                subject_artifact_ref=proposal_ref.path,
                subject_artifact_hash=proposal_ref.artifact_hash,
            )
        except Exception as exc:  # fail closed at the external Critic boundary
            critic_assessment = CriticAssessment(
                assessor_id=type(proposal_critic).__name__ or "unidentified_critic",
                assessor_kind="unresolved",
                subject_artifact_ref=proposal_ref.path,
                subject_artifact_hash=proposal_ref.artifact_hash,
                dimension_scores={dimension: 0 for dimension in CRITIC_DIMENSIONS},
                total_score=0,
                verdict="unresolved",
                findings=(
                    CriticFinding(
                        dimension="evidence_grounding",
                        level="blocking",
                        message=f"Critic execution failed with {type(exc).__name__}.",
                    ),
                ),
                limitations=("The Critic result was not available for this review.",),
            )
        critic_payload = critic_assessment.to_artifact_payload()
        critic_ref = artifact_store.write(
            feature_id=proposal["feature_id"],
            artifact_type="critic_assessment",
            payload=critic_payload,
            status="success" if critic_assessment.verdict == "pass" else "blocked",
            upstream_refs=[
                _artifact_ref_from_state(state, "feature_spec"),
                _artifact_ref_from_state(state, "evidence_pack"),
                _artifact_ref_from_state(state, "implementation_plan"),
                proposal_ref,
            ],
            exact_revision_upstream_types={"patch_proposal"},
        )

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=evidence_pack,
        repair_plan=repair_plan,
        implementation_plan=implementation_plan,
        feature_spec=feature_spec,
        artifact_hashes=dict(state["artifact_hashes"]),
        critic_assessment=critic_payload,
        require_critic_assessment=critic_requirement == "required",
        domain_policy=(
            domain_review_policy
            if domain_review_policy is not None
            else _domain_review_policy_from_state(
                state,
                domain_adapter_registry,
            )
        ),
        permission_level="dry_run_write",
        require_executable_patch=require_executable_patch,
    )
    artifact_ref = artifact_store.write(
        feature_id=proposal["feature_id"],
        artifact_type="proposal_review",
        payload=review.to_artifact_payload(),
        status="success" if review.allowed_next_stage == "dry_run_apply" else "blocked",
        upstream_refs=[proposal_ref, *([critic_ref] if critic_ref is not None else [])],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "proposal_review"
    next_state["review_summary"] = {
        "decision": review.decision,
        "allowed_next_stage": review.allowed_next_stage,
        "num_findings": len(review.findings),
        "critic_gate": dict(review.critic_gate),
    }
    _record_artifact(next_state, "proposal_review", artifact_ref)
    if critic_ref is not None:
        _record_artifact(next_state, "critic_assessment", critic_ref)
    if review.allowed_next_stage != "dry_run_apply":
        next_state["blockers"].extend(
            {
                "stage": "proposal_review",
                "code": finding.rule_id.upper(),
                "message": finding.message,
            }
            for finding in review.findings
            if finding.level == "blocking"
        )
    return next_state


def _domain_review_policy_from_state(
    state: ModAgentState,
    domain_adapter_registry: DomainAdapterRegistry | None,
) -> DomainReviewPolicy | None:
    """Resolve the review policy for a workflow run."""

    registry = domain_adapter_registry or _default_domain_adapter_registry()
    target_domain = state.get("target_domain")
    if not target_domain:
        return None

    adapter_name = target_domain
    if target_domain == "gtfo" and GTFO_DOMAIN_NAME in registry.names():
        adapter_name = GTFO_DOMAIN_NAME

    try:
        adapter = registry.get(adapter_name)
    except KeyError:
        adapter = UnsupportedDomainAdapter()

    return adapter.identify_project(".").review_policy()


def _run_dynamic_human_review_gate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    if review.get("allowed_next_stage") != "dry_run_apply":
        return _copy_state(state)
    if state["approvals"].get("review") is True:
        return _copy_state(state)

    request = _dynamic_review_interrupt_request(state, artifact_store)
    resume_value = interrupt(request.to_dict())

    checkpoint_store = WorkflowCheckpointStore(artifact_store)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        state,
        interrupt_reason=request.reason,
        resume_allowed_fields=("approvals.review",),
    )
    checkpoint = artifact_store.read(checkpoint_ref)["data"]
    payload = _resume_payload_from_dynamic_value(
        resume_value,
        state=state,
        checkpoint=checkpoint,
    )
    decision, resume_report_ref = checkpoint_store.resume(checkpoint_ref, payload)

    next_state = _copy_state(state)
    _record_artifact(next_state, "workflow_checkpoint", checkpoint_ref)
    _record_artifact(next_state, "resume_report", resume_report_ref)
    approvals = decision.applied_updates.get("approvals")
    if isinstance(approvals, dict):
        next_state["approvals"] = {
            **dict(next_state["approvals"]),
            **approvals,
        }
    if not decision.allowed:
        next_state["blockers"].extend(decision.blockers)
    return next_state


def _run_stagger_edit_authority_gate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    request_ref: ArtifactRef,
) -> ModAgentState:
    """Approve one exact request in-graph, then project bounded records."""

    feature_id = state["feature_id"] or state["request_id"]
    if request_ref.feature_id != feature_id:
        raise ValueError(
            "EditAuthorityRequest feature does not match graph state."
        )
    request_envelope = artifact_store.read_for_stage(
        request_ref,
        consumer_stage="edit_authority_approval",
    )
    request = request_envelope["data"]
    if (
        request.get("feature_id") != feature_id
        or request.get("run_id") != state["run_id"]
        or request.get("authority_granted") is not False
    ):
        raise ValueError(
            "EditAuthorityRequest identity or no-authority boundary is invalid."
        )

    gate_state = _copy_state(state)
    gate_state["current_stage"] = "edit_authority_approval"
    _record_artifact(gate_state, "edit_authority_request", request_ref)
    request_payload = request.get("request_payload")
    request_schema = (
        request_payload.get("schema_version")
        if isinstance(request_payload, dict)
        else None
    )
    if request_schema not in {
        _EXISTING_BINDING_REAUTHORIZATION_REQUEST_SCHEMA,
        _STAGGER_HUD_PARENT_OBSERVATION_REQUEST_SCHEMA,
        _STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA,
    }:
        for upstream in request_envelope.get("inputs", {}).get(
            "upstream_artifacts",
            (),
        ):
            if (
                isinstance(upstream, dict)
                and isinstance(upstream.get("artifact_type"), str)
                and isinstance(upstream.get("path"), str)
                and isinstance(
                    upstream.get("artifact_hash"),
                    str,
                )
            ):
                _record_artifact(
                    gate_state,
                    str(upstream["artifact_type"]),
                    ArtifactRef(
                        feature_id=feature_id,
                        artifact_type=str(
                            upstream["artifact_type"]
                        ),
                        path=str(upstream["path"]),
                        artifact_hash=str(
                            upstream["artifact_hash"]
                        ),
                    ),
                )
    if (
        request_schema
        == _EXISTING_BINDING_REAUTHORIZATION_REQUEST_SCHEMA
    ):
        allowed_actions = [
            "reauthorize_existing_edit_binding",
            "create_binding_resolution_revision",
        ]
        forbidden_actions = [
            "create_evidence_pack_revision",
            "create_implementation_plan_revision",
            "create_edit_binding",
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ]
    elif request_schema in {
        _STAGGER_HUD_PARENT_OBSERVATION_REQUEST_SCHEMA,
        _STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA,
    }:
        allowed_actions = (
            [
                "create_observation_evidence_pack_revision",
                "create_diagnostic_only_implementation_plan_revision",
                "create_exact_bounded_observation_bindings",
            ]
            if request_schema
            == _STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA
            else [
                "create_observation_evidence_pack_revision",
                "create_diagnostic_implementation_plan_revision",
                "create_observation_only_edit_bindings",
            ]
        )
        forbidden_actions = [
            "create_binding_resolution_revision",
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ]
    else:
        allowed_actions = [
            "create_evidence_pack_revision",
            "create_implementation_plan_revision",
            "resolve_exact_edit_binding",
        ]
        forbidden_actions = [
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ]
    interrupt_request = InterruptRequest(
        interrupt_id=f"interrupt_{uuid4().hex}",
        run_id=state["run_id"],
        feature_id=feature_id,
        stage="edit_authority_approval",
        reason=(
            "exact EditAuthorityRequest requires human approval before "
            "Registry projection"
        ),
        payload={
            "node_name": "stagger_edit_authority_gate",
            "stage": "edit_authority_approval",
            "required_decision": ["approve", "reject"],
            "edit_authority_request_revision": {
                "feature_id": request_ref.feature_id,
                "path": request_ref.path,
                "artifact_hash": request_ref.artifact_hash,
            },
            "request_hash": request["request_hash"],
            "allowed_actions": allowed_actions,
            "forbidden_actions": forbidden_actions,
        },
        resume_allowed_fields=("approvals.edit_authority",),
        artifact_refs=tuple(gate_state["artifacts"].values()),
    )
    resume_value = interrupt(interrupt_request.to_dict())

    checkpoint_store = WorkflowCheckpointStore(artifact_store)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        gate_state,
        interrupt_reason=interrupt_request.reason,
        resume_allowed_fields=("approvals.edit_authority",),
    )
    checkpoint = artifact_store.read(checkpoint_ref)["data"]
    payload = _resume_payload_from_dynamic_value(
        resume_value,
        state=gate_state,
        checkpoint=checkpoint,
    )
    decision, report_ref = checkpoint_store.resume(
        checkpoint_ref,
        payload,
    )
    next_state = _copy_state(gate_state)
    _record_artifact(next_state, "workflow_checkpoint", checkpoint_ref)
    _record_artifact(next_state, "resume_report", report_ref)
    if not decision.allowed or payload.decision != "approve":
        next_state["current_stage"] = "blocked"
        next_state["blockers"].extend(
            decision.blockers
            or (
                {
                    "stage": "edit_authority_approval",
                    "code": "EDIT_AUTHORITY_REJECTED",
                    "message": (
                        "Human review did not approve the exact "
                        "EditAuthorityRequest."
                    ),
                },
            )
        )
        return next_state

    try:
        materialized = materialize_stagger_edit_authority_approval(
            artifact_store_root=artifact_store.root,
            feature_id=feature_id,
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            resume_report_path=report_ref.path,
            resume_report_hash=report_ref.artifact_hash,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        next_state["current_stage"] = "blocked"
        next_state["blockers"].append(
            {
                "stage": "edit_authority_approval",
                "code": "EDIT_AUTHORITY_APPROVED_NOT_MATERIALIZED",
                "message": str(exc),
            }
        )
        return next_state

    materialized_fields = [
        ("edit_authority_approval", "edit_authority_approval_revision"),
        ("evidence_pack", "evidence_pack_revision"),
        ("implementation_plan", "implementation_plan_revision"),
    ]
    if request_schema not in {
        _STAGGER_HUD_PARENT_OBSERVATION_REQUEST_SCHEMA,
        _STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA,
    }:
        materialized_fields.append(
            ("binding_resolution", "binding_resolution_revision")
        )
    for artifact_type, field_name in materialized_fields:
        revision = materialized[field_name]
        _record_artifact(
            next_state,
            artifact_type,
            ArtifactRef(
                feature_id=feature_id,
                artifact_type=artifact_type,
                path=str(revision["path"]),
                artifact_hash=str(revision["artifact_hash"]),
            ),
        )
    next_state["current_stage"] = (
        "implementation_plan"
        if request_schema
        in {
            _STAGGER_HUD_PARENT_OBSERVATION_REQUEST_SCHEMA,
            _STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA,
        }
        else "binding_resolution"
    )
    next_state["approvals"] = {
        **dict(next_state["approvals"]),
        "edit_authority": True,
    }
    return next_state


def _dynamic_review_interrupt_request(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> InterruptRequest:
    feature_id = state["feature_id"] or state["request_id"]
    return InterruptRequest(
        interrupt_id=f"interrupt_{uuid4().hex}",
        run_id=state["run_id"],
        feature_id=feature_id,
        stage="proposal_review",
        reason="proposal review requires human approval before dry run",
        payload={
            "node_name": "human_review_gate",
            "stage": "proposal_review",
            "required_decision": ["approve", "reject"],
            "resume_binding": _dynamic_review_resume_binding(state, artifact_store),
            "artifact_hashes": dict(state["artifact_hashes"]),
        },
        resume_allowed_fields=("approvals.review",),
        artifact_refs=tuple(state["artifacts"].values()),
    )


def _dynamic_review_resume_binding(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> dict[str, Any]:
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    review_ref = _artifact_ref_from_state(state, "proposal_review")
    proposal_payload = artifact_store.read(proposal_ref)["data"]
    serialized = json.dumps(
        proposal_payload.get("diff_intent") or [],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "patch_proposal_ref": proposal_ref.path,
        "patch_proposal_hash": proposal_ref.artifact_hash,
        "proposal_review_ref": review_ref.path,
        "proposal_review_hash": review_ref.artifact_hash,
        "diff_hash": "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }


def _resume_payload_from_dynamic_value(
    resume_value: Any,
    *,
    state: ModAgentState,
    checkpoint: dict[str, Any],
) -> ResumePayload:
    value = resume_value if isinstance(resume_value, dict) else {}
    return ResumePayload(
        resume_id=str(value.get("resume_id") or f"resume_{uuid4().hex}"),
        run_id=str(value.get("run_id") or state["run_id"]),
        stage=str(value.get("stage") or checkpoint.get("checkpoint_stage") or state["current_stage"]),
        decision=str(value.get("decision") or "reject"),
        approved_by=str(value.get("approved_by") or ""),
        approved_at=str(value.get("approved_at") or ""),
        artifact_refs=tuple(value.get("artifact_refs") or ()),
        diff_hash=value.get("diff_hash"),
        notes=str(value.get("notes") or ""),
        authority_request_hash=value.get("authority_request_hash"),
    )


def _default_domain_adapter_registry() -> DomainAdapterRegistry:
    """Return the default domain policy registry for workflow review gates."""

    return DomainAdapterRegistry((GTFOAdapter(), UnsupportedDomainAdapter()))


def _runtime_evidence_factory_from_settings(
    settings: Any | None,
    *,
    allow_game_launch: bool,
) -> RuntimeEvidenceFactory | None:
    if settings is None:
        return None
    runtime = getattr(settings, "runtime", None)
    gtfo = getattr(runtime, "gtfo", None)
    if gtfo is not None and getattr(gtfo, "enabled", False):
        return make_gtfo_runtime_evidence_factory_from_settings(
            settings,
            allow_game_launch=allow_game_launch,
        )
    return None


def _run_dry_run_apply(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    require_review_approval: bool = False,
    dry_run_factory: PatchExecutionFactory | None = None,
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    approved_by_review = review.get("allowed_next_stage") == "dry_run_apply"
    approved_by_human = state["approvals"].get("review") is True
    approved = approved_by_review and (
        not require_review_approval or approved_by_human
    )
    changed_files = list(proposal.get("files") or [])
    diff_intent = list(proposal.get("diff_intent") or [])
    generated_payload = (
        dry_run_factory(
            proposal,
            _read_artifact_data(state, artifact_store, "implementation_plan"),
            review,
        )
        if dry_run_factory is not None and approved
        else None
    )
    payload = {
        "node_name": "dry_run_apply",
        "stage": "dry_run_apply",
        "message": (
            "Executable patch dry-run validated without writing source files."
            if generated_payload is not None
            else "Fake dry-run completed. No source files were written and no patch was applied."
        ),
        "execution_mode": "dry_run" if generated_payload is not None else "fake",
        "actual_write_performed": False,
        "real_patch_applied": False,
        "approved_by_review": approved_by_review,
        "human_approval_required": require_review_approval,
        "approved_by_human": approved_by_human,
        "proposal_id": proposal.get("proposal_id"),
        "review_decision": review.get("decision"),
        "would_write": bool(diff_intent),
        "changed_files": changed_files,
        "diff_stats": {
            "files": len(changed_files),
            "change_units": len(diff_intent),
            "insertions": 0,
            "deletions": 0,
        },
        "limitations": [
            "Dry-run validation does not prove the isolated write or build succeeds."
            if generated_payload is not None
            else "This is an isolated fake dry-run artifact."
        ],
        **dict(generated_payload or {}),
    }
    status = "success" if approved else "blocked"
    artifact_ref = artifact_store.write(
        feature_id=proposal["feature_id"],
        artifact_type="dry_run_result",
        payload=payload,
        status=status,
        upstream_refs=[
            _artifact_ref_from_state(state, "patch_proposal"),
            _artifact_ref_from_state(state, "proposal_review"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "dry_run_apply"
    _record_artifact(next_state, "dry_run_result", artifact_ref)
    if not approved:
        next_state["blockers"].append(
            {
                "stage": "dry_run_apply",
                "code": "REVIEW_NOT_APPROVED",
                "message": "Dry-run cannot proceed without review approval.",
            }
        )
    return next_state


def _run_build(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    build_result_factory: BuildResultFactory | None,
    *,
    persist_build_runtime_handoff: bool = False,
) -> ModAgentState:
    dry_run = _read_artifact_data(state, artifact_store, "dry_run_result")
    feature_id = state["feature_id"] or state["request_id"]
    apply_result = (
        _read_artifact_data(state, artifact_store, "isolated_apply_result")
        if "isolated_apply_result" in state["artifacts"]
        else None
    )
    input_execution_mode = (
        apply_result.get("execution_mode")
        if apply_result is not None
        else dry_run.get("execution_mode")
    )
    result = (
        build_result_factory(feature_id, input_execution_mode)
        if build_result_factory is not None
        else build_fake_build_result(
            feature_id=feature_id,
            input_execution_mode=input_execution_mode,
        )
    )
    payload = result.to_artifact_payload()
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="build_result",
        payload=payload,
        status="failed" if payload["status"] == "failed" else "success",
        upstream_refs=[
            _artifact_ref_from_state(state, "dry_run_result"),
            *(
                [_artifact_ref_from_state(state, "isolated_apply_result")]
                if "isolated_apply_result" in state["artifacts"]
                else []
            ),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "build"
    next_state["build_summary"] = {
        "status": payload["status"],
        "build_status": payload["build_status"],
        "execution_mode": payload["execution_mode"],
        "real_build_performed": payload["real_build_performed"],
        "error_class": payload["error_class"],
        "repair_handoff": payload["repair_handoff"],
        "claims_real_build_success": payload["claims_real_build_success"],
    }
    _record_artifact(next_state, "build_result", artifact_ref)
    if (
        persist_build_runtime_handoff
        and payload["status"] == "success"
        and payload["claims_real_build_success"] is True
    ):
        next_state["next_stage"] = "runtime_evidence"
        checkpoint_ref = WorkflowCheckpointStore(artifact_store).create_checkpoint(
            next_state,
            interrupt_reason=(
                "Successful Build is ready for fresh-process Runtime continuation."
            ),
            resume_allowed_fields=(),
        )
        _record_artifact(next_state, "workflow_checkpoint", checkpoint_ref)
    return next_state


def _route_runtime_continuation_entry(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    checkpoint_id: str,
) -> str:
    """Admit only a validated Build checkpoint into the existing Runtime node."""

    if state.get("current_stage") != "build":
        raise ValueError("Runtime continuation state must restore the Build boundary.")
    if state.get("next_stage") != "runtime_evidence":
        raise ValueError("Runtime continuation state has an unexpected next_stage.")
    if state.get("blockers"):
        raise ValueError("Runtime continuation state contains unresolved blockers.")
    for artifact_type in (
        "workflow_checkpoint",
        "resume_report",
        "feature_spec",
        "build_result",
    ):
        if artifact_type not in state.get("artifacts", {}):
            raise ValueError(
                f"Runtime continuation state is missing {artifact_type}."
            )
        if artifact_type not in state.get("artifact_hashes", {}):
            raise ValueError(
                f"Runtime continuation state is missing {artifact_type} hash."
            )
    checkpoint_ref = _artifact_ref_from_state(state, "workflow_checkpoint")
    report_ref = _artifact_ref_from_state(state, "resume_report")
    checkpoint = artifact_store.read_for_stage(
        checkpoint_ref,
        consumer_stage="resume",
    )["data"]
    report = artifact_store.read(report_ref)["data"]
    if (
        checkpoint.get("checkpoint_id") != checkpoint_id
        or checkpoint.get("checkpoint_stage") != "build"
        or checkpoint.get("run_id") != state.get("run_id")
        or checkpoint.get("request_id") != state.get("request_id")
        or checkpoint.get("feature_id") != state.get("feature_id")
        or report.get("checkpoint_id") != checkpoint_id
        or report.get("run_id") != state.get("run_id")
        or report.get("resume_stage") != "build"
        or report.get("decision") != "approve"
        or report.get("allowed") is not True
    ):
        raise ValueError(
            "Runtime continuation checkpoint and resume report are not bound "
            "to the restored state."
        )
    return "continue"


def _run_create_repair_plan(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    proposal_context_pack = _read_artifact_data(
        state,
        artifact_store,
        "patch_proposal",
    ).get("context_pack")
    proposal_context_for_repair = (
        {
            **proposal_context_pack,
            "source_patch_proposal_ref": proposal_ref.path,
            "source_patch_proposal_hash": proposal_ref.artifact_hash,
        }
        if isinstance(proposal_context_pack, dict)
        else None
    )
    planner = RepairPlanner()
    feature_id = state["feature_id"] or state["request_id"]
    failed_stage = state["current_stage"]
    if failed_stage == "build" and state["build_summary"].get("status") == "failed":
        build_ref = _artifact_ref_from_state(state, "build_result")
        plan = planner.from_build_failure(
            build_result=_read_artifact_data(state, artifact_store, "build_result"),
            build_result_ref=build_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
            proposal_context_pack=proposal_context_for_repair,
            implementation_plan=_read_artifact_data(
                state,
                artifact_store,
                "implementation_plan",
            ),
        )
        upstream_refs = [build_ref, proposal_ref]
    elif failed_stage in {"runtime_evidence", "binding_resolution"}:
        runtime_ref = _artifact_ref_from_state(state, "runtime_evidence")
        runtime_evidence = _read_artifact_data(
            state,
            artifact_store,
            "runtime_evidence",
        )
        binding_resolution = (
            _read_artifact_data(
                state,
                artifact_store,
                "binding_resolution",
            )
            if "binding_resolution" in state["artifacts"]
            else None
        )
        resolved_repair_target = (
            dict(binding_resolution["resolved_repair_target"])
            if isinstance(binding_resolution, dict)
            and binding_resolution.get("result_type")
            == "resolved_repair_target"
            and isinstance(
                binding_resolution.get("resolved_repair_target"),
                dict,
            )
            else {}
        )
        plan = planner.from_runtime_failure(
            runtime_evidence=runtime_evidence,
            runtime_evidence_ref=runtime_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
            proposal_context_pack=proposal_context_for_repair,
            resolved_repair_target=resolved_repair_target,
        )
        upstream_refs = [runtime_ref, proposal_ref]
        if binding_resolution is not None:
            upstream_refs.append(
                _artifact_ref_from_state(state, "binding_resolution")
            )
    elif failed_stage == "proposal_review":
        review_ref = _artifact_ref_from_state(state, "proposal_review")
        plan = planner.from_review_failure(
            proposal_review=_read_artifact_data(
                state,
                artifact_store,
                "proposal_review",
            ),
            proposal_review_ref=review_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
            proposal_context_pack=proposal_context_for_repair,
            implementation_plan=_read_artifact_data(
                state,
                artifact_store,
                "implementation_plan",
            ),
        )
        upstream_refs = [review_ref, proposal_ref]
    else:
        raise ValueError(
            f"Unsupported repair-plan source stage: {failed_stage}"
        )
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="repair_plan",
        payload=plan.to_artifact_payload(),
        status="blocked" if plan.blockers else "success",
        upstream_refs=upstream_refs,
        exact_revision_upstream_types={"patch_proposal"},
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "repair_plan"
    next_state["retry_count"] = plan.retry_count
    _record_artifact(next_state, "repair_plan", artifact_ref)
    if plan.blockers:
        next_state["blockers"].extend(plan.blockers)
    return next_state


def _run_resolve_runtime_binding(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    feature_id = state["feature_id"] or state["request_id"]
    runtime_ref = _artifact_ref_from_state(state, "runtime_evidence")
    runtime_evidence = _read_artifact_data(
        state,
        artifact_store,
        "runtime_evidence",
    )
    implementation_plan_ref = _artifact_ref_from_state(
        state,
        "implementation_plan",
    )
    implementation_plan = _read_artifact_data(
        state,
        artifact_store,
        "implementation_plan",
    )
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    proposal = _read_artifact_data(
        state,
        artifact_store,
        "patch_proposal",
    )
    context_pack = proposal.get("context_pack")
    allowed_binding_ids = {
        str(value)
        for value in (
            context_pack.get("allowed_edit_binding_ids", ())
            if isinstance(context_pack, dict)
            else ()
        )
        if isinstance(value, str)
    }
    result = resolve_runtime_diagnosis_binding(
        diagnosis=runtime_evidence.get("runtime_failure_diagnosis"),
        feature_id=feature_id,
        run_id=state["run_id"],
        runtime_evidence_revision={
            "feature_id": runtime_ref.feature_id,
            "path": runtime_ref.path,
            "artifact_hash": runtime_ref.artifact_hash,
        },
        implementation_plan_revision={
            "feature_id": implementation_plan_ref.feature_id,
            "path": implementation_plan_ref.path,
            "artifact_hash": implementation_plan_ref.artifact_hash,
        },
        patch_proposal_revision={
            "feature_id": proposal_ref.feature_id,
            "path": proposal_ref.path,
            "artifact_hash": proposal_ref.artifact_hash,
        },
        implementation_plan=implementation_plan,
        allowed_edit_binding_ids=allowed_binding_ids,
    )
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="binding_resolution",
        payload=result.to_artifact_payload(),
        status="blocked" if result.blocked else "success",
        upstream_refs=[
            runtime_ref,
            implementation_plan_ref,
            proposal_ref,
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "binding_resolution"
    _record_artifact(next_state, "binding_resolution", artifact_ref)
    next_state["blockers"].extend(result.blockers)
    return next_state


def _run_runtime_evidence(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    runtime_evidence_factory: RuntimeEvidenceFactory | None,
) -> ModAgentState:
    build = _read_artifact_data(state, artifact_store, "build_result")
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    feature_id = state["feature_id"] or state["request_id"]
    build_artifact_ref = _artifact_ref_from_state(state, "build_result")
    payload = (
        runtime_evidence_factory(feature_id, build, feature_spec)
        if runtime_evidence_factory is not None
        else build_fake_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=build.get("execution_mode"),
            acceptance_criteria=tuple(feature_spec.get("acceptance_criteria") or ()),
            runtime_verification_plan=tuple(
                feature_spec.get("runtime_verification_plan") or ()
            ),
        )
    )
    payload = bind_runtime_evidence_context(
        payload,
        run_id=state["run_id"],
        build_artifact_ref=build_artifact_ref,
    )
    acceptance_verified = bool(payload["acceptance_verified"])
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="runtime_evidence",
        payload=payload,
        status="success" if acceptance_verified else "blocked",
        upstream_refs=[
            build_artifact_ref,
            _artifact_ref_from_state(state, "feature_spec"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "runtime_evidence"
    next_state["runtime_summary"] = {
        "status": payload["verification_status"],
        "execution_mode": payload["execution_mode"],
        "real_runtime_performed": payload["real_runtime_performed"],
        "startup_loaded": payload["startup_loaded"],
        "gameplay_behavior_verified": payload["gameplay_behavior_verified"],
        "acceptance_status": payload["acceptance_status"],
        "acceptance_verified": acceptance_verified,
        "acceptance_contract": payload["acceptance_contract"],
        "claims_real_runtime_success": payload["claims_real_runtime_success"],
        "run_id": payload["run_id"],
        "build_artifact_hash": payload["build_artifact_hash"],
        "plugin_marker_binding": payload["plugin_marker_binding"],
        "screenshot_refs": payload["screenshot_refs"],
        "runtime_trust_binding": payload["runtime_trust_binding"],
        "failure_ownership": payload["failure_ownership"],
        "has_structured_diagnosis": isinstance(
            payload.get("runtime_failure_diagnosis"),
            dict,
        ),
        "plugin_deployment_binding": payload.get("plugin_deployment_binding"),
        "non_goal_preservation": payload["non_goal_preservation"],
    }
    _record_artifact(next_state, "runtime_evidence", artifact_ref)
    return next_state


def _run_fake_evaluate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    evaluation_context_factory: EvaluationContextFactory | None = None,
    require_external_evaluation: bool = False,
) -> ModAgentState:
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    dry_run = _read_artifact_data(state, artifact_store, "dry_run_result")
    build = _read_artifact_data(state, artifact_store, "build_result")
    runtime = _read_artifact_data(state, artifact_store, "runtime_evidence")
    feature_id = state["feature_id"] or state["request_id"]
    acceptance_verified = bool(runtime.get("acceptance_verified"))
    v1_boundary = _v1_acceptance_boundary(build=build, runtime=runtime)
    v1_accepted = v1_boundary["v1_acceptance_status"] == "accepted"
    execution_mode = "real" if v1_accepted else "fake"
    workflow_completion_status = (
        "real_runtime_acceptance_completed"
        if v1_accepted
        else "fake_execution_completed"
    )
    evaluation_gate = build_transition_eval_gate_report(
        review=review,
        dry_run=dry_run,
        build=build,
        runtime=runtime,
        v1_boundary=v1_boundary,
        claims_real_success=v1_accepted,
        evaluation_context=(
            evaluation_context_factory(state)
            if evaluation_context_factory is not None
            else None
        ),
        evaluation_required=require_external_evaluation,
    )
    payload = {
        "node_name": "evaluate",
        "stage": "evaluation",
        "message": (
            "Evaluation completed with real build and runtime acceptance evidence."
            if v1_accepted
            else (
                "Evaluation completed for a fake/local workflow path. Result remains "
                "inconclusive for real build and runtime success."
            )
        ),
        "execution_mode": execution_mode,
        "workflow_completion_status": workflow_completion_status,
        "requested_behavior_status": "verified" if acceptance_verified else "not_verified",
        "verdict": "accepted" if v1_accepted else "inconclusive",
        "claims_real_success": v1_accepted,
        "checks": [
            {
                "check": "review_gate_approved",
                "status": "passed",
            },
            {
                "check": "real_build",
                "status": "passed"
                if build.get("claims_real_build_success")
                else "not_run",
            },
            {
                "check": "real_runtime",
                "status": "passed"
                if runtime.get("claims_real_runtime_success")
                else "not_run",
            },
        ],
        "input_runtime_status": runtime.get("verification_status"),
        "input_acceptance_status": runtime.get("acceptance_status"),
        "input_acceptance_verified": acceptance_verified,
        "acceptance_contract": runtime.get("acceptance_contract"),
        "evaluation_gate": evaluation_gate,
        **v1_boundary,
    }
    gate_failed = evaluation_gate.get("status") == "failed"
    gate_blockers = list(evaluation_gate.get("blockers") or [])
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="eval_report",
        payload=payload,
        status="blocked" if gate_failed else "success",
        blockers=gate_blockers,
        upstream_refs=[
            _artifact_ref_from_state(state, "build_result"),
            _artifact_ref_from_state(state, "runtime_evidence"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "evaluation"
    _record_artifact(next_state, "eval_report", artifact_ref)
    if gate_failed:
        next_state["blockers"].extend(
            {
                "stage": "evaluation",
                "code": blocker.get("code", "EVAL_GATE_FAILED"),
                "message": blocker.get("message", "Evaluation gate failed."),
            }
            for blocker in gate_blockers
            if isinstance(blocker, dict)
        )
    return next_state


def _run_isolated_apply(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    isolated_apply_factory: PatchExecutionFactory,
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    approved_by_user = state["approvals"].get("confirmed_write") is True
    next_state = _copy_state(state)
    status = "success"
    if not approved_by_user:
        payload = {
            "execution_mode": "blocked",
            "actual_write_performed": False,
            "real_patch_applied": False,
            "approved_by_review": review.get("allowed_next_stage") == "dry_run_apply",
            "changed_files": [],
        }
        status = "blocked"
        next_state["blockers"].append(
            {
                "stage": "isolated_apply",
                "code": "ISOLATED_WRITE_NOT_APPROVED",
                "message": "Isolated patch application requires explicit user approval.",
            }
        )
    else:
        try:
            payload = isolated_apply_factory(
                proposal,
                _read_artifact_data(state, artifact_store, "implementation_plan"),
                review,
            )
        except ExactDiffApprovalRejectedError as exc:
            payload = {
                "execution_mode": "rejected",
                "actual_write_performed": False,
                "real_patch_applied": False,
                "approved_by_review": review.get("allowed_next_stage")
                == "dry_run_apply",
                "changed_files": [],
                "rejection": str(exc),
            }
            status = "blocked"
            next_state["blockers"].append(
                {
                    "stage": "isolated_apply",
                    "code": "EXACT_DIFF_REJECTED",
                    "message": str(exc),
                }
            )
        except Exception as exc:
            payload = {
                "execution_mode": "isolated_apply",
                "actual_write_performed": False,
                "real_patch_applied": False,
                "approved_by_review": review.get("allowed_next_stage") == "dry_run_apply",
                "changed_files": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            status = "failed"
            next_state["blockers"].append(
                {
                    "stage": "isolated_apply",
                    "code": "ISOLATED_APPLY_FAILED",
                    "message": payload["error"],
                }
            )
    exact_diff_approved = bool(
        payload.get("approved_diff_hash")
        and payload.get("approved_diff_hash") == payload.get("diff_hash")
    )
    complete_payload = {
        "node_name": "isolated_apply",
        "stage": "isolated_apply",
        "message": (
            "Approved patch was applied inside the isolated workspace."
            if status == "success"
            else "Isolated patch application did not complete."
        ),
        **payload,
        "write_scope_preapproved": approved_by_user,
        "approved_by_user": bool(
            payload.get("approved_by_user", approved_by_user if status == "success" else False)
        ),
        "exact_diff_approved": exact_diff_approved,
    }
    artifact_ref = artifact_store.write(
        feature_id=proposal["feature_id"],
        artifact_type="isolated_apply_result",
        payload=complete_payload,
        status=status,
        upstream_refs=[
            _artifact_ref_from_state(state, "patch_proposal"),
            _artifact_ref_from_state(state, "proposal_review"),
            _artifact_ref_from_state(state, "dry_run_result"),
        ],
    )
    next_state["current_stage"] = "isolated_apply"
    _record_artifact(next_state, "isolated_apply_result", artifact_ref)
    return next_state


def _run_workflow_summary(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    eval_report = _read_artifact_data(state, artifact_store, "eval_report")
    feature_id = state["feature_id"] or state["request_id"]
    accepted = eval_report.get("v1_acceptance_status") == "accepted"
    payload = {
        "node_name": "done",
        "stage": "done",
        "message": (
            "Workflow reached done with real build and runtime acceptance evidence."
            if accepted
            else (
                "Workflow reached the end of the controlled fake execution loop. "
                "No real file write, real build, or real runtime success is claimed."
            )
        ),
        "execution_mode": eval_report.get("execution_mode"),
        "workflow_completion_status": eval_report.get("workflow_completion_status"),
        "requested_behavior_status": eval_report.get("requested_behavior_status"),
        "final_status": "accepted" if accepted else "inconclusive",
        "claims_real_mod_success": bool(eval_report.get("claims_real_success")),
        "claims_real_build_success": bool(
            state["build_summary"].get("claims_real_build_success")
        ),
        "claims_real_runtime_success": bool(
            state["runtime_summary"].get("claims_real_runtime_success")
        ),
        "artifact_refs": dict(state["artifacts"]),
        "build_summary": dict(state["build_summary"]),
        "runtime_summary": dict(state["runtime_summary"]),
        "eval_verdict": eval_report.get("verdict"),
        "v1_acceptance_status": eval_report.get("v1_acceptance_status"),
        "v1_acceptance_blockers": list(eval_report.get("v1_acceptance_blockers") or []),
        "next_required_evidence": [
            "real dry-run/apply result",
            "real build output",
            "real runtime or manual verification evidence",
        ],
    }
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="workflow_summary",
        payload=payload,
        status="success",
        upstream_refs=[_artifact_ref_from_state(state, "eval_report")],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "done"
    _record_artifact(next_state, "workflow_summary", artifact_ref)
    return next_state


def _run_planning_brief(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    plan_data = _read_artifact_data(state, artifact_store, "request_planning_report")
    plan = _request_plan_from_payload(plan_data)
    planning_brief = ModPlanningBriefBuilder().build(
        plan,
        target_game=state["target_domain"],
    )
    artifact_ref = artifact_store.write(
        feature_id=planning_brief.feature_id,
        artifact_type="mod_planning_brief",
        payload=planning_brief.to_artifact_payload(),
        status="blocked" if planning_brief.blocked else "success",
        upstream_refs=[_artifact_ref_from_state(state, "request_planning_report")],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "planning_brief"
    _record_artifact(next_state, "mod_planning_brief", artifact_ref)
    if planning_brief.blocked:
        next_state["blockers"].extend(planning_brief.blockers)
    return next_state


def _v1_acceptance_boundary(
    *,
    build: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    if build.get("claims_real_build_success") is not True:
        blockers.append(
            {
                "code": "REAL_BUILD_EVIDENCE_MISSING",
                "message": "V1 acceptance requires real build success evidence.",
            }
        )
    if runtime.get("execution_mode") != "real":
        blockers.append(
            {
                "code": "REAL_RUNTIME_MODE_REQUIRED",
                "message": "V1 acceptance requires runtime evidence from real execution mode.",
            }
        )
    if runtime.get("real_runtime_performed") is not True:
        blockers.append(
            {
                "code": "REAL_RUNTIME_EVIDENCE_MISSING",
                "message": "V1 acceptance requires real runtime execution evidence.",
            }
        )
    if runtime.get("claims_real_runtime_success") is not True:
        blockers.append(
            {
                "code": "REAL_RUNTIME_SUCCESS_NOT_CLAIMED",
                "message": "V1 acceptance requires an explicit real runtime success claim.",
            }
        )
    if runtime.get("acceptance_verified") is not True:
        blockers.append(
            {
                "code": "ACCEPTANCE_NOT_VERIFIED",
                "message": "V1 acceptance requires verified runtime acceptance evidence.",
            }
        )
    if (
        runtime.get("evidence_source") == "gtfo_real_runtime_automation"
        and _runtime_trust_binding_status(runtime) != "trusted"
    ):
        blockers.append(
            {
                "code": "GTFO_RUNTIME_TRUST_BINDING_MISSING",
                "message": (
                    "V1 acceptance for GTFO automation requires trusted current-run "
                    "log, process, marker, build, and screenshot binding."
                ),
            }
        )
    return {
        "v1_acceptance_status": "blocked" if blockers else "accepted",
        "v1_acceptance_blockers": blockers,
    }


def _runtime_trust_binding_status(runtime: dict[str, Any]) -> str | None:
    binding = runtime.get("runtime_trust_binding")
    if not isinstance(binding, dict):
        return None
    return binding.get("status")


def _request_plan_from_payload(data: dict[str, Any]) -> RequestPlan:
    return RequestPlan(
        feature_id=data["feature_id"],
        user_request=data["user_request"],
        route=data["route"],
        risk_level=data["risk_level"],
        target_mod=data.get("target_mod"),
        requires_hook_evidence=bool(data["requires_hook_evidence"]),
        requires_runtime_evidence=bool(data["requires_runtime_evidence"]),
        hook_requirement=_hook_requirement_from_payload(data),
        uncertainties=tuple(
            Uncertainty(
                uncertainty_id=item["uncertainty_id"],
                severity=item["severity"],
                question=item["question"],
                allowed_resolution=tuple(item.get("allowed_resolution", ())),
                default_action=item.get("default_action", "block"),
            )
            for item in data.get("uncertainties", [])
        ),
        blocked=bool(data["blocked"]),
    )


def _feature_spec_from_payload(data: dict[str, Any]) -> FeatureSpec:
    return FeatureSpec(
        feature_id=data["feature_id"],
        user_request=data["user_request"],
        target_behavior=data["target_behavior"],
        non_goals=tuple(data["non_goals"]),
        target_mod=data.get("target_mod"),
        risk_level=data["risk_level"],
        acceptance_criteria=tuple(data["acceptance_criteria"]),
        evidence_requirements=tuple(data["evidence_requirements"]),
        runtime_verification_plan=tuple(data["runtime_verification_plan"]),
        hook_requirement=_hook_requirement_from_payload(data),
        blocked=bool(data["blocked"]),
        blockers=tuple(data.get("blockers", [])),
    )


def _hook_requirement_from_payload(data: dict[str, Any]) -> dict[str, Any]:
    hook_requirement = data.get("hook_requirement")
    if isinstance(hook_requirement, dict):
        return {
            "required": hook_requirement.get("required") is True,
            "reason": str(hook_requirement.get("reason") or "not_required"),
        }
    return {"required": False, "reason": "not_required"}


def _read_artifact_data(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    artifact_type: str,
) -> dict[str, Any]:
    ref = _artifact_ref_from_state(state, artifact_type)
    envelope = artifact_store.read(ref)
    return envelope["data"]


def _artifact_ref_from_state(state: ModAgentState, artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        feature_id=state["feature_id"] or state["request_id"],
        artifact_type=artifact_type,
        path=state["artifacts"][artifact_type],
        artifact_hash=state["artifact_hashes"][artifact_type],
    )


def _record_artifact(
    state: ModAgentState,
    artifact_type: str,
    artifact_ref: ArtifactRef,
) -> None:
    state["artifacts"][artifact_type] = artifact_ref.path
    state["artifact_hashes"][artifact_type] = artifact_ref.artifact_hash


def _node_status(state: ModAgentState, node_name: str) -> str:
    if node_name == "retrieve_evidence":
        return "success" if state["evidence_summary"].get("can_generate_patch") else "blocked"
    if node_name == "review_proposal":
        return (
            "success"
            if state["review_summary"].get("allowed_next_stage") == "dry_run_apply"
            else "blocked"
        )
    if node_name == "build" and state["build_summary"]:
        return str(state["build_summary"].get("status", "success"))
    if node_name == "collect_runtime_evidence" and state["runtime_summary"]:
        return str(state["runtime_summary"].get("status", "success"))
    if node_name == "create_repair_plan":
        return "blocked" if state["blockers"] else "success"
    if node_name == "resolve_runtime_binding":
        return "blocked" if state["blockers"] else "success"
    if node_name == "done":
        return "inconclusive"
    if state["blockers"]:
        return "blocked"
    return "success"


def _node_artifact_refs(state: ModAgentState, node_name: str) -> list[str]:
    artifact_by_node = {
        "plan_request": "request_planning_report",
        "planning_brief": "mod_planning_brief",
        "draft_feature_spec": "feature_spec",
        "retrieve_evidence": "evidence_pack",
        "create_implementation_plan": "implementation_plan",
        "generate_patch_proposal": "patch_proposal",
        "review_proposal": "proposal_review",
        "human_review_gate": "resume_report",
        "dry_run_apply": "dry_run_result",
        "build": "build_result",
        "collect_runtime_evidence": "runtime_evidence",
        "resolve_runtime_binding": "binding_resolution",
        "create_repair_plan": "repair_plan",
        "evaluate": "eval_report",
        "done": "workflow_summary",
    }
    artifact_type = artifact_by_node.get(node_name)
    if artifact_type is None or artifact_type not in state["artifacts"]:
        return []
    return [state["artifacts"][artifact_type]]


def _node_trace_details(state: ModAgentState, node_name: str) -> dict[str, Any]:
    if node_name == "retrieve_evidence" and state["evidence_summary"]:
        missing_evidence = list(state["evidence_summary"].get("missing_evidence") or [])
        return {
            "readiness": state["evidence_summary"].get("readiness"),
            "can_generate_patch": state["evidence_summary"].get("can_generate_patch"),
            "retrieval_methods_used": list(
                state["evidence_summary"].get("retrieval_methods_used") or []
            ),
            "missing_evidence_count": len(missing_evidence),
            "disabled_modes": dict(state["evidence_summary"].get("disabled_modes") or {}),
            "timing": dict(state["evidence_summary"].get("timing") or {}),
        }
    if node_name == "create_repair_plan" and "repair_plan" in state["artifacts"]:
        return {
            "retry_count": state["retry_count"],
            "blocked": bool(state["blockers"]),
        }
    if (
        node_name == "resolve_runtime_binding"
        and "binding_resolution" in state["artifacts"]
    ):
        return {
            "result_type": (
                "binding_gap" if state["blockers"] else "resolved_repair_target"
            ),
            "blocked": bool(state["blockers"]),
        }
    return {}


def _trace_event(
    *,
    state: ModAgentState,
    node_name: str,
    event_type: str,
    status: str,
    artifact_refs: list[str],
    summary: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "event_id": f"evt_{uuid4().hex}",
        "run_id": state["run_id"],
        "feature_id": state.get("feature_id") or state["request_id"],
        "node_name": node_name,
        "stage": state["current_stage"],
        "event_type": event_type,
        "status": status,
        "artifact_refs": artifact_refs,
        "summary": summary,
    }
    if details:
        event["details"] = details
    return event


def _copy_state_with_trace(
    state: ModAgentState,
    trace_event: dict[str, Any],
) -> ModAgentState:
    next_state = _copy_state(state)
    next_state["trace_events"].append(trace_event)
    return next_state


def _copy_state(state: ModAgentState) -> ModAgentState:
    return ModAgentState(
        run_id=state["run_id"],
        request_id=state["request_id"],
        feature_id=state["feature_id"],
        user_request=state["user_request"],
        target_domain=state["target_domain"],
        target_mod=state["target_mod"],
        execution_path=state["execution_path"],
        risk_level=state["risk_level"],
        current_stage=state["current_stage"],
        next_stage=state["next_stage"],
        artifacts=dict(state["artifacts"]),
        artifact_hashes=dict(state["artifact_hashes"]),
        approvals=dict(state["approvals"]),
        blockers=list(state["blockers"]),
        warnings=list(state["warnings"]),
        evidence_summary=dict(state["evidence_summary"]),
        review_summary=dict(state["review_summary"]),
        build_summary=dict(state["build_summary"]),
        runtime_summary=dict(state["runtime_summary"]),
        trace_events=list(state["trace_events"]),
        retry_count=state["retry_count"],
    )
