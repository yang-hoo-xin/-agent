"""LangGraph StateGraph construction for the controlled development workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.build import BuildResult, build_fake_build_result
from src.mod_agent.domain import (
    DomainAdapterRegistry,
    DomainReviewPolicy,
    GTFO_DOMAIN_NAME,
    GTFOAdapter,
    UnsupportedDomainAdapter,
)
from src.mod_agent.evidence import DeterministicEvidenceRetriever, EvidenceRequest
from src.mod_agent.knowledge import (
    CollectionResolutionError,
    CollectionResolver,
    KnowledgeDatabase,
)
from src.mod_agent.planning import (
    FeatureSpec,
    FeatureSpecBuilder,
    ImplementationPlanner,
    RequestPlan,
    RequestPlanner,
    Uncertainty,
)
from src.mod_agent.proposal import PatchProposalBuilder, ProposalReviewer
from src.mod_agent.repair import RepairPatchProposalBuilder, RepairPlanner
from src.mod_agent.runtime import build_fake_runtime_evidence_payload

from .nodes import StubNodeRunner
from .state import ModAgentState
from .transitions import (
    continue_route,
    route_after_build,
    route_after_evidence,
    route_after_feature_spec,
    route_after_implementation_plan,
    route_after_patch_proposal,
    route_after_plan_request,
    route_after_repair_plan,
    route_after_review,
    route_after_runtime_evidence,
    route_registry,
)

GraphNode = Callable[[ModAgentState], ModAgentState]
BuildResultFactory = Callable[[str, str | None], BuildResult]
RuntimeEvidenceFactory = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]


def build_graph(
    artifact_store: ArtifactStore,
    *,
    knowledge_database: KnowledgeDatabase | None = None,
    collection_id: str | None = None,
    collection_resolver: CollectionResolver | None = None,
    domain_adapter_registry: DomainAdapterRegistry | None = None,
    build_result_factory: BuildResultFactory | None = None,
    runtime_evidence_factory: RuntimeEvidenceFactory | None = None,
    checkpointer: Any | None = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
):
    """Build a compiled LangGraph graph with real planning/review routing.

    Planning, evidence retrieval, implementation planning, patch proposal, and
    review are real controlled nodes. Dry-run remains fake; build and runtime
    evidence can be injected for controlled contract tests.
    """

    stub_runner = StubNodeRunner(artifact_store)
    effective_domain_registry = domain_adapter_registry or _default_domain_adapter_registry()
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
        "retrieve_evidence",
        _make_real_graph_node(
            "retrieve_evidence",
            lambda state: _run_retrieve_evidence(
                state,
                artifact_store,
                knowledge_database,
                collection_id,
                collection_resolver,
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
            lambda state: _run_generate_patch_proposal(state, artifact_store),
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
            ),
        ),
    )

    graph.add_node(
        "dry_run_apply",
        _make_real_graph_node(
            "dry_run_apply",
            lambda state: _run_fake_dry_run_apply(state, artifact_store),
        ),
    )
    graph.add_node(
        "build",
        _make_real_graph_node(
            "build",
            lambda state: _run_build(state, artifact_store, build_result_factory),
        ),
    )
    graph.add_node(
        "collect_runtime_evidence",
        _make_real_graph_node(
            "collect_runtime_evidence",
            lambda state: _run_runtime_evidence(
                state,
                artifact_store,
                runtime_evidence_factory,
            ),
        ),
    )
    graph.add_node(
        "evaluate",
        _make_real_graph_node(
            "evaluate",
            lambda state: _run_fake_evaluate(state, artifact_store),
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
        "done",
        _make_real_graph_node(
            "done",
            lambda state: _run_workflow_summary(state, artifact_store),
        ),
    )
    graph.add_node("blocked", _make_stub_graph_node("blocked", stub_runner))

    graph.add_edge(START, "plan_request")
    registry = route_registry()
    graph.add_conditional_edges(
        "plan_request",
        route_after_plan_request,
        dict(registry["plan_request"]),
    )
    graph.add_conditional_edges(
        "draft_feature_spec",
        route_after_feature_spec,
        dict(registry["draft_feature_spec"]),
    )
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
        dict(registry["review_proposal"]),
    )
    graph.add_conditional_edges(
        "dry_run_apply",
        continue_route,
        dict(registry["dry_run_apply"]),
    )
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
        "create_repair_plan",
        route_after_repair_plan,
        dict(registry["create_repair_plan"]),
    )
    for node_name in [
        "evaluate",
    ]:
        graph.add_conditional_edges(
            node_name,
            continue_route,
            dict(registry[node_name]),
        )
    graph.add_edge("done", END)
    graph.add_edge("blocked", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )


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
    feature_spec = FeatureSpecBuilder().build(plan)
    artifact_ref = artifact_store.write(
        feature_id=feature_spec.feature_id,
        artifact_type="feature_spec",
        payload=feature_spec.to_artifact_payload(),
        status="blocked" if feature_spec.blocked else "success",
        upstream_refs=[_artifact_ref_from_state(state, "request_planning_report")],
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
) -> ModAgentState:
    feature_data = _read_artifact_data(state, artifact_store, "feature_spec")
    if knowledge_database is None:
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
        )
        try:
            pack = DeterministicEvidenceRetriever(
                knowledge_database,
                collection_id=collection_id,
                collection_resolver=collection_resolver,
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
        proposal = PatchProposalBuilder().build(implementation)
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


def _run_review_proposal(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    domain_adapter_registry: DomainAdapterRegistry | None = None,
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    repair_plan = (
        _read_artifact_data(state, artifact_store, "repair_plan")
        if "repair_plan" in state["artifacts"]
        else None
    )
    review = ProposalReviewer().review(
        proposal,
        evidence_pack=evidence_pack,
        repair_plan=repair_plan,
        feature_spec=feature_spec,
        domain_policy=_domain_review_policy_from_state(
            state,
            domain_adapter_registry,
        ),
        permission_level="dry_run_write",
    )
    artifact_ref = artifact_store.write(
        feature_id=proposal["feature_id"],
        artifact_type="proposal_review",
        payload=review.to_artifact_payload(),
        status="success" if review.allowed_next_stage == "dry_run_apply" else "blocked",
        upstream_refs=[_artifact_ref_from_state(state, "patch_proposal")],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "proposal_review"
    next_state["review_summary"] = {
        "decision": review.decision,
        "allowed_next_stage": review.allowed_next_stage,
        "num_findings": len(review.findings),
    }
    _record_artifact(next_state, "proposal_review", artifact_ref)
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


def _default_domain_adapter_registry() -> DomainAdapterRegistry:
    """Return the default domain policy registry for workflow review gates."""

    return DomainAdapterRegistry((GTFOAdapter(), UnsupportedDomainAdapter()))


def _run_fake_dry_run_apply(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    approved = review.get("allowed_next_stage") == "dry_run_apply"
    changed_files = list(proposal.get("files") or [])
    diff_intent = list(proposal.get("diff_intent") or [])
    payload = {
        "node_name": "dry_run_apply",
        "stage": "dry_run_apply",
        "message": (
            "Fake dry-run completed. No source files were written and no patch "
            "was applied."
        ),
        "execution_mode": "fake",
        "actual_write_performed": False,
        "real_patch_applied": False,
        "approved_by_review": approved,
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
            "This is an isolated fake dry-run artifact.",
            "It does not prove a patch applies to the filesystem.",
        ],
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
) -> ModAgentState:
    dry_run = _read_artifact_data(state, artifact_store, "dry_run_result")
    feature_id = state["feature_id"] or state["request_id"]
    result = (
        build_result_factory(feature_id, dry_run.get("execution_mode"))
        if build_result_factory is not None
        else build_fake_build_result(
            feature_id=feature_id,
            input_execution_mode=dry_run.get("execution_mode"),
        )
    )
    payload = result.to_artifact_payload()
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="build_result",
        payload=payload,
        status="failed" if payload["status"] == "failed" else "success",
        upstream_refs=[_artifact_ref_from_state(state, "dry_run_result")],
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
    return next_state


def _run_create_repair_plan(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    planner = RepairPlanner()
    feature_id = state["feature_id"] or state["request_id"]
    if state["build_summary"].get("status") == "failed":
        build_ref = _artifact_ref_from_state(state, "build_result")
        plan = planner.from_build_failure(
            build_result=_read_artifact_data(state, artifact_store, "build_result"),
            build_result_ref=build_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
        )
        upstream_refs = [build_ref]
    else:
        runtime_ref = _artifact_ref_from_state(state, "runtime_evidence")
        plan = planner.from_runtime_failure(
            runtime_evidence=_read_artifact_data(
                state,
                artifact_store,
                "runtime_evidence",
            ),
            runtime_evidence_ref=runtime_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
        )
        upstream_refs = [runtime_ref]
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="repair_plan",
        payload=plan.to_artifact_payload(),
        status="blocked" if plan.blockers else "success",
        upstream_refs=upstream_refs,
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "repair_plan"
    next_state["retry_count"] = plan.retry_count
    _record_artifact(next_state, "repair_plan", artifact_ref)
    if plan.blockers:
        next_state["blockers"].extend(plan.blockers)
    return next_state


def _run_runtime_evidence(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    runtime_evidence_factory: RuntimeEvidenceFactory | None,
) -> ModAgentState:
    build = _read_artifact_data(state, artifact_store, "build_result")
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    feature_id = state["feature_id"] or state["request_id"]
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
    acceptance_verified = bool(payload["acceptance_verified"])
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="runtime_evidence",
        payload=payload,
        status="success" if acceptance_verified else "blocked",
        upstream_refs=[
            _artifact_ref_from_state(state, "build_result"),
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
    }
    _record_artifact(next_state, "runtime_evidence", artifact_ref)
    return next_state


def _run_fake_evaluate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
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
        **v1_boundary,
    }
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="eval_report",
        payload=payload,
        status="success",
        upstream_refs=[
            _artifact_ref_from_state(state, "build_result"),
            _artifact_ref_from_state(state, "runtime_evidence"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "evaluation"
    _record_artifact(next_state, "eval_report", artifact_ref)
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
    if runtime.get("real_runtime_performed") is not True:
        blockers.append(
            {
                "code": "REAL_RUNTIME_EVIDENCE_MISSING",
                "message": "V1 acceptance requires real runtime execution evidence.",
            }
        )
    if runtime.get("acceptance_verified") is not True:
        blockers.append(
            {
                "code": "ACCEPTANCE_NOT_VERIFIED",
                "message": "V1 acceptance requires verified runtime acceptance evidence.",
            }
        )
    return {
        "v1_acceptance_status": "blocked" if blockers else "accepted",
        "v1_acceptance_blockers": blockers,
    }


def _request_plan_from_payload(data: dict[str, Any]) -> RequestPlan:
    return RequestPlan(
        feature_id=data["feature_id"],
        user_request=data["user_request"],
        route=data["route"],
        risk_level=data["risk_level"],
        target_mod=data.get("target_mod"),
        requires_hook_evidence=bool(data["requires_hook_evidence"]),
        requires_runtime_evidence=bool(data["requires_runtime_evidence"]),
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
        blocked=bool(data["blocked"]),
        blockers=tuple(data.get("blockers", [])),
    )


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
    if node_name == "done":
        return "inconclusive"
    if state["blockers"]:
        return "blocked"
    return "success"


def _node_artifact_refs(state: ModAgentState, node_name: str) -> list[str]:
    artifact_by_node = {
        "plan_request": "request_planning_report",
        "draft_feature_spec": "feature_spec",
        "retrieve_evidence": "evidence_pack",
        "create_implementation_plan": "implementation_plan",
        "generate_patch_proposal": "patch_proposal",
        "review_proposal": "proposal_review",
        "dry_run_apply": "dry_run_result",
        "build": "build_result",
        "collect_runtime_evidence": "runtime_evidence",
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
