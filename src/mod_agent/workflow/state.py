"""Runtime control state for the Evidence-Grounded Controlled Code Generation Agent Platform workflow."""

from __future__ import annotations

from typing import Any, Literal, Mapping, TypedDict

StageName = Literal[
    "request_planning",
    "planning_brief",
    "feature_spec",
    "evidence_retrieval",
    "implementation_plan",
    "patch_proposal",
    "proposal_review",
    "dry_run_apply",
    "isolated_apply",
    "build",
    "runtime_evidence",
    "edit_authority_request",
    "edit_authority_approval",
    "repair_planning_authority_request",
    "repair_planning_approval",
    "root_cause_evidence",
    "repair_hypothesis_set",
    "binding_resolution",
    "repair_plan",
    "evaluation",
    "done",
    "blocked",
]

ExecutionPath = Literal[
    "config_only",
    "no_hook_needed",
    "quick_patch",
    "standard_feature",
    "game_hook_investigation",
    "runtime_investigation",
    "repair_loop",
    "blocked_ambiguous",
]

RiskLevel = Literal["low", "medium", "high", "blocked"]

ArtifactRefMap = dict[str, str]


class ModAgentState(TypedDict):
    """LangGraph runtime control state.

    Durable evidence and business outputs live in artifacts. This state stores
    routing fields, artifact refs, summaries, blockers, and approval metadata.
    """

    run_id: str
    request_id: str
    feature_id: str | None
    user_request: str
    target_domain: str | None
    target_mod: str | None
    execution_path: ExecutionPath | None
    risk_level: RiskLevel | None
    current_stage: StageName
    next_stage: StageName | None
    artifacts: ArtifactRefMap
    artifact_hashes: ArtifactRefMap
    approvals: dict[str, bool]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    evidence_summary: dict[str, Any]
    review_summary: dict[str, Any]
    build_summary: dict[str, Any]
    runtime_summary: dict[str, Any]
    trace_events: list[dict[str, Any]]
    retry_count: int


class StateOwnershipPolicy:
    """Declare which workflow component may write each state field."""

    _WRITERS: Mapping[str, frozenset[str]] = {
        "run_id": frozenset({"state_initializer"}),
        "request_id": frozenset({"state_initializer"}),
        "feature_id": frozenset({"plan_request", "verification_only_admission"}),
        "user_request": frozenset({"state_initializer", "human_correction"}),
        "target_domain": frozenset({"state_initializer", "plan_request", "domain_adapter"}),
        "target_mod": frozenset({"state_initializer", "plan_request"}),
        "execution_path": frozenset({"plan_request"}),
        "risk_level": frozenset({"plan_request", "domain_adapter"}),
        "current_stage": frozenset({"workflow_node", "transition_router"}),
        "next_stage": frozenset({"transition_router"}),
        "artifacts": frozenset({"artifact_producing_node"}),
        "artifact_hashes": frozenset({"artifact_store"}),
        "approvals": frozenset({"state_initializer", "interrupt_resume_handler"}),
        "blockers": frozenset({"workflow_node", "transition_router", "review_proposal"}),
        "warnings": frozenset({"workflow_node", "review_proposal"}),
        "evidence_summary": frozenset(
            {"retrieve_evidence", "verification_only_admission"}
        ),
        "review_summary": frozenset({"review_proposal"}),
        "build_summary": frozenset({"build"}),
        "runtime_summary": frozenset({"collect_runtime_evidence"}),
        "trace_events": frozenset({"workflow_node", "transition_router"}),
        "retry_count": frozenset({"create_repair_plan", "transition_router"}),
    }

    @classmethod
    def allowed_writers(cls, field_name: str) -> frozenset[str]:
        """Return the declared writers for a state field."""

        try:
            return cls._WRITERS[field_name]
        except KeyError as exc:
            raise KeyError(f"Unknown ModAgentState field: {field_name}") from exc

    @classmethod
    def can_write(cls, field_name: str, writer: str) -> bool:
        """Return whether a workflow component may write a field."""

        return writer in cls.allowed_writers(field_name)


def create_initial_state(
    *,
    run_id: str,
    request_id: str,
    user_request: str,
    target_domain: str | None = None,
    target_mod: str | None = None,
    confirmed_isolated_write: bool = False,
) -> ModAgentState:
    """Create the minimal initial state for a workflow run."""

    return ModAgentState(
        run_id=run_id,
        request_id=request_id,
        feature_id=None,
        user_request=user_request,
        target_domain=target_domain,
        target_mod=target_mod,
        execution_path=None,
        risk_level=None,
        current_stage="request_planning",
        next_stage=None,
        artifacts={},
        artifact_hashes={},
        approvals={"confirmed_write": True} if confirmed_isolated_write else {},
        blockers=[],
        warnings=[],
        evidence_summary={},
        review_summary={},
        build_summary={},
        runtime_summary={},
        trace_events=[],
        retry_count=0,
    )
