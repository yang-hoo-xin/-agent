"""Route labels and transition registry for the controlled workflow."""

from __future__ import annotations

from collections.abc import Mapping

from .state import ModAgentState

RouteRegistry = Mapping[str, Mapping[str, str]]


def is_vague_request(user_request: str) -> bool:
    """Return whether a request is too vague for safe planning."""

    normalized = " ".join(user_request.strip().lower().split())
    return normalized in {"", "test", "do it", "make it better", "something", "whatever"}


def route_after_plan_request(state: ModAgentState) -> str:
    """Route from plan_request based on structured planning blockers."""

    if state["blockers"] or state["execution_path"] == "blocked_ambiguous":
        return "blocked"
    return "continue"


def route_after_feature_spec(state: ModAgentState) -> str:
    """Stop when feature specification is blocked."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_planning_brief(state: ModAgentState) -> str:
    """Stop when planning brief handoff is blocked."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_evidence(state: ModAgentState) -> str:
    """Stop when evidence is not sufficient for patch generation."""

    if not state["evidence_summary"].get("can_generate_patch", False):
        return "blocked"
    return "continue"


def route_after_implementation_plan(state: ModAgentState) -> str:
    """Stop when implementation planning is blocking."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_patch_proposal(state: ModAgentState) -> str:
    """Stop when proposal generation is blocking."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_review(state: ModAgentState) -> str:
    """Allow dry-run after approval or route revision findings to repair."""

    if state["review_summary"].get("allowed_next_stage") == "dry_run_apply":
        return "continue"
    if state["review_summary"].get("decision") == "revise_proposal":
        return "repair"
    return "blocked"


def route_after_human_review_gate(state: ModAgentState) -> str:
    """Stop only when the human review gate records validation blockers."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_dry_run(state: ModAgentState) -> str:
    """Stop when dry-run is blocked by missing or rejected approval."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_isolated_apply(state: ModAgentState) -> str:
    """Stop when the approved isolated write failed or was not performed."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_build(state: ModAgentState) -> str:
    """Route failed builds to repair planning."""

    if state["build_summary"].get("status") == "failed":
        return "repair"
    return "continue"


def route_after_runtime_evidence(state: ModAgentState) -> str:
    """Route unverified acceptance to repair planning."""

    if state["runtime_summary"].get("acceptance_verified") is True:
        return "continue"
    if state["runtime_summary"].get("has_structured_diagnosis") is True:
        return "binding_resolution"
    return "repair"


def route_after_binding_resolution(state: ModAgentState) -> str:
    """Continue only after edit authority resolves to one binding."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_after_evaluate(state: ModAgentState) -> str:
    """Stop when evaluation gate blockers are present."""

    if any(_is_eval_gate_blocker(blocker) for blocker in state["blockers"]):
        return "blocked"
    return "continue"


def route_after_repair_plan(state: ModAgentState) -> str:
    """Route repair plans back through proposal review or block exhausted loops."""

    if state["blockers"]:
        return "blocked"
    return "continue"


def route_registry() -> RouteRegistry:
    """Return the route matrix used by graph construction and audits."""

    return {
        "plan_request": {
            "blocked": "blocked",
            "continue": "planning_brief",
        },
        "planning_brief": {
            "blocked": "blocked",
            "continue": "draft_feature_spec",
        },
        "draft_feature_spec": {
            "blocked": "blocked",
            "continue": "retrieve_evidence",
        },
        "retrieve_evidence": {
            "blocked": "blocked",
            "continue": "create_implementation_plan",
        },
        "create_implementation_plan": {
            "blocked": "blocked",
            "continue": "generate_patch_proposal",
        },
        "generate_patch_proposal": {
            "blocked": "blocked",
            "continue": "review_proposal",
        },
        "review_proposal": {
            "blocked": "blocked",
            "continue": "dry_run_apply",
            "repair": "create_repair_plan",
        },
        "human_review_gate": {
            "blocked": "blocked",
            "continue": "dry_run_apply",
        },
        "dry_run_apply": {
            "blocked": "blocked",
            "continue": "build",
        },
        "isolated_apply": {
            "blocked": "blocked",
            "continue": "build",
        },
        "build": {
            "continue": "collect_runtime_evidence",
            "repair": "create_repair_plan",
        },
        "collect_runtime_evidence": {
            "continue": "evaluate",
            "binding_resolution": "resolve_runtime_binding",
            "repair": "create_repair_plan",
        },
        "resolve_runtime_binding": {
            "blocked": "blocked",
            "continue": "create_repair_plan",
        },
        "create_repair_plan": {
            "blocked": "blocked",
            "continue": "generate_patch_proposal",
        },
        "evaluate": {
            "blocked": "blocked",
            "continue": "done",
        },
    }


def continue_route(_: ModAgentState) -> str:
    """Route label for unconditional Phase A transitions."""

    return "continue"


def _is_eval_gate_blocker(blocker: object) -> bool:
    if not isinstance(blocker, Mapping):
        return False
    code = blocker.get("code")
    return blocker.get("stage") == "evaluation" and isinstance(code, str) and code.startswith(
        "EVAL_GATE_"
    )
