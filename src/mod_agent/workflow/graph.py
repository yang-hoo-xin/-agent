"""LangGraph StateGraph construction for the controlled development workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.evidence import DeterministicEvidenceRetriever, EvidenceRequest
from src.mod_agent.knowledge import KnowledgeDatabase
from src.mod_agent.planning import (
    FeatureSpec,
    FeatureSpecBuilder,
    ImplementationPlanner,
    RequestPlan,
    RequestPlanner,
    Uncertainty,
)
from src.mod_agent.proposal import PatchProposalBuilder, ProposalReviewer

from .nodes import StubNodeRunner
from .state import ModAgentState
from .transitions import (
    continue_route,
    route_after_evidence,
    route_after_feature_spec,
    route_after_implementation_plan,
    route_after_patch_proposal,
    route_after_plan_request,
    route_after_review,
    route_registry,
)

GraphNode = Callable[[ModAgentState], ModAgentState]


def build_graph(
    artifact_store: ArtifactStore,
    *,
    knowledge_database: KnowledgeDatabase | None = None,
):
    """Build a compiled LangGraph graph with real planning/review routing.

    Planning, evidence retrieval, implementation planning, patch proposal, and
    review are real controlled nodes. Later execution stages remain stubbed
    until dry-run/build/runtime modules are implemented.
    """

    stub_runner = StubNodeRunner(artifact_store)
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
            lambda state: _run_review_proposal(state, artifact_store),
        ),
    )

    for node_name in {
        "dry_run_apply",
        "build",
        "collect_runtime_evidence",
        "evaluate",
        "done",
        "blocked",
    }:
        graph.add_node(node_name, _make_stub_graph_node(node_name, stub_runner))

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
    for node_name in [
        "dry_run_apply",
        "build",
        "collect_runtime_evidence",
        "evaluate",
    ]:
        graph.add_conditional_edges(
            node_name,
            continue_route,
            dict(registry[node_name]),
        )
    graph.add_edge("done", END)
    graph.add_edge("blocked", END)
    return graph.compile()


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
        pack = DeterministicEvidenceRetriever(knowledge_database).retrieve(request)
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
    implementation = _read_artifact_data(state, artifact_store, "implementation_plan")
    proposal = PatchProposalBuilder().build(implementation)
    artifact_ref = artifact_store.write(
        feature_id=proposal.feature_id,
        artifact_type="patch_proposal",
        payload=proposal.to_artifact_payload(),
        status="blocked" if proposal.blocked else "success",
        upstream_refs=[
            _artifact_ref_from_state(state, "implementation_plan"),
            _artifact_ref_from_state(state, "evidence_pack"),
        ],
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
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    review = ProposalReviewer().review(
        proposal,
        evidence_pack=evidence_pack,
        feature_spec=feature_spec,
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
    }
    artifact_type = artifact_by_node.get(node_name)
    if artifact_type is None or artifact_type not in state["artifacts"]:
        return []
    return [state["artifacts"][artifact_type]]


def _trace_event(
    *,
    state: ModAgentState,
    node_name: str,
    event_type: str,
    status: str,
    artifact_refs: list[str],
    summary: str,
) -> dict[str, Any]:
    return {
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
