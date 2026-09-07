"""Bound one explicit semantic return to existing Repair, Evidence and Planning owners."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from src.libs.llm.agent_turn import AgentToolCall
from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationError,
    PatchContinuationInputV1,
    _artifact_ref_dict,
    _canonical_sha256,
    _patch_continuation_state,
    _repair_json,
    _source_tree_snapshot_sha256,
    admit_active_worker_failure,
    preflight_patch_continuation,
)
from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_UPSTREAM_REQUEST_TOOL_NAME,
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    _validate_upstream_request,
)


def validate_patch_upstream_selection(request: PatchContinuationInputV1, selection: Mapping[str, Any], *, artifact_store=None):
    """A recommendation selects an assessment owner, never writable source or approval."""
    if not isinstance(selection, Mapping) or set(selection) != {
        "origin", "required_owner", "reason", "source_refs", "source_attempt_ref"
    } or selection["origin"] not in {"human", "model"}:
        raise PatchContinuationError("PATCH_UPSTREAM_SELECTION_INVALID", "upstream_admission", "Explicit semantic owner selection is required.")
    admitted = preflight_patch_continuation(request, artifact_store=artifact_store)
    if admitted.repair_context is None:
        raise PatchContinuationError("PATCH_UPSTREAM_FAILURE_REQUIRED", "upstream_admission", "This return requires the existing bound post-Proposal failure context.")
    arguments = {key: deepcopy(selection[key]) for key in ("required_owner", "reason", "source_refs")}
    policy = PatchAgentLoopPolicy(enable_supporting_reads=True, allow_upstream_request=True)
    inspector = PlanBoundSourceInspector(workspace_root=request.workspace_root,
        implementation_plan=admitted.implementation_plan, evidence_pack=admitted.evidence_pack, policy=policy)
    code, validated = _validate_upstream_request(
        AgentToolCall(call_id="upstream-admission", name=PATCH_UPSTREAM_REQUEST_TOOL_NAME, arguments=arguments),
        inspector, policy, tool_available=True)
    if validated is None:
        raise PatchContinuationError(code, "upstream_admission", "The owner recommendation has invalid refs or source identity.")
    if selection["origin"] == "model":
        source = _repair_json(selection["source_attempt_ref"])
        expected = {kind: _artifact_ref_dict(ref) for kind, ref in (
            ("feature_spec", request.feature_spec_ref), ("evidence_pack", request.evidence_pack_ref),
            ("implementation_plan", request.implementation_plan_ref))}
        receipt = source.get("factory_receipt") or {}
        terminal = receipt.get("upstream_decision") or {}
        turns = receipt.get("worker_turns") or []
        snapshot = _source_tree_snapshot_sha256(admitted.source_tree_snapshot)
        if (source.get("selected_artifacts") != expected or terminal.get("code") != "PATCH_AGENT_UPSTREAM_REQUESTED"
                or source.get("generated_against_snapshot_sha256") != snapshot
                or source.get("current_snapshot_sha256") != snapshot
                or terminal.get("upstream_request") != validated or not turns):
            raise PatchContinuationError("PATCH_UPSTREAM_ATTEMPT_MISMATCH", "upstream_admission", "The source attempt does not carry this exact model return.")
        admitted, _ = _validate_worker_failure_binding(admitted, receipt, arguments,
            request=request, artifact_store=admitted.artifact_store)
    elif selection["source_attempt_ref"] is not None:
        raise PatchContinuationError("PATCH_UPSTREAM_SELECTION_INVALID", "upstream_admission", "A human selection must not impersonate a model attempt.")
    return admitted, {**deepcopy(dict(selection)), "validated_request": validated,
        "failure_report_ref": deepcopy(admitted.repair_context["failure_report_ref"]),
        "preserved_plan_boundaries": deepcopy(admitted.implementation_plan.get("side_effect_boundaries", []))}


def _validate_worker_failure_binding(admitted, receipt, arguments, *, request, artifact_store):
    context = admitted.repair_context
    recorded = receipt.get("repair_context") or {}
    if (recorded.get("context_sha256") != _canonical_sha256(context)
            or recorded.get("failure_report_sha256") != _canonical_sha256(context["failure_report"])
            or recorded.get("previous_response_sha256") != hashlib.sha256(context["previous_response"].encode()).hexdigest()):
        raise PatchContinuationError("PATCH_UPSTREAM_FAILURE_BINDING_REQUIRED", "upstream_admission",
            "The worker must originate from this exact bound C1/F1 before any newer failure is consumed.")
    turns = receipt.get("worker_turns") or []
    if not turns or turns[-1].get("status") != "responded":
        raise PatchContinuationError("PATCH_UPSTREAM_RESPONSE_MISMATCH", "upstream_admission", "No retained final worker response exists.")
    response = _repair_json(turns[-1].get("response_ref"))
    calls = response.get("tool_calls") or []
    if len(calls) != 1 or calls[0].get("name") != PATCH_UPSTREAM_REQUEST_TOOL_NAME or calls[0].get("arguments") != arguments:
        raise PatchContinuationError("PATCH_UPSTREAM_RESPONSE_MISMATCH", "upstream_admission", "The retained model response does not request this owner and refs.")
    if (receipt.get("patch_agent_loop") or {}).get("behavior_evaluations"):
        admitted = admit_active_worker_failure(request, receipt, artifact_store)
        _validate_current_failure_feedback(admitted.repair_context, receipt)
    return admitted, deepcopy(turns[-1]["response_ref"])


def _validate_current_failure_feedback(context, receipt):
    """An upstream request must consume F2, not merely coexist with its saved result."""
    loop = receipt.get("patch_agent_loop") or {}
    correction = loop.get("behavior_correction") or {}
    execution = correction.get("execution") or {}
    feedback = correction.get("validator") or {}
    observations = deepcopy(context["failure_report"]["observations"])
    for observation in observations:
        if isinstance(observation, dict) and isinstance(observation.get("result_ref"), dict):
            observation["result_ref"] = {"sha256": observation["result_ref"].get("sha256")}
    if (execution.get("termination") != receipt.get("upstream_decision")
            or execution.get("status") != "blocked" or correction.get("status") != "blocked"
            or feedback.get("report_sha256") != context["failure_report_ref"]["sha256"]
            or feedback.get("generated_changes_sha256") != context["generated_changes_sha256"]
            or feedback.get("source_snapshot_sha256") != context["source_snapshot_sha256"]
            or feedback.get("observations") != observations):
        raise PatchContinuationError("PATCH_UPSTREAM_FAILURE_BINDING_REQUIRED", "upstream_admission",
            "The upstream response is not from the revision segment that consumed this current failure.")


def validate_active_worker_upstream(request, receipt, *, artifact_store):
    terminal = receipt.get("upstream_decision") or {}
    arguments = terminal.get("upstream_request") or {}
    if terminal.get("code") != "PATCH_AGENT_UPSTREAM_REQUESTED":
        raise PatchContinuationError("PATCH_UPSTREAM_SELECTION_INVALID", "upstream_admission", "There is no explicit worker upstream request.")
    selection = {"origin": "human", "source_attempt_ref": None,
        **{key: arguments.get(key) for key in ("required_owner", "reason", "source_refs")}}
    admitted, validated = validate_patch_upstream_selection(request, selection, artifact_store=artifact_store)
    if arguments != validated["validated_request"]:
        raise PatchContinuationError("PATCH_UPSTREAM_ATTEMPT_MISMATCH", "upstream_admission", "The live request's source identity differs.")
    admitted, ref = _validate_worker_failure_binding(admitted, receipt,
        {key: selection[key] for key in ("required_owner", "reason", "source_refs")},
        request=request, artifact_store=artifact_store)
    return admitted, {**validated, "origin": "model", "source_worker_response_ref": ref,
        "failure_report_ref": deepcopy(admitted.repair_context["failure_report_ref"]),
        "source_attempt_id": request.attempt_id}


def run_patch_upstream_replanning(*, request: PatchContinuationInputV1, selection: Mapping[str, Any],
        planning_target_selection_factory: ModelPlanningTargetSelector, evidence_pack_factory=None,
        run_id: str | None = None):
    """Run the existing Graph through one upstream assessment, ending at its new Plan."""
    from src.mod_agent.artifacts import ArtifactStore
    from src.mod_agent.workflow import build_graph

    if run_id is not None and (not isinstance(run_id, str) or not run_id or run_id.strip() != run_id):
        raise ValueError("An explicit nonempty invocation identity is required.")
    store = ArtifactStore(request.artifact_store_root)
    admitted, validated = validate_patch_upstream_selection(request, selection, artifact_store=store)
    if not isinstance(planning_target_selection_factory, ModelPlanningTargetSelector):
        raise ValueError("Upstream replanning requires the model-owned target selector; explicit target lists are not a fallback.")
    identity = hashlib.sha256(json.dumps(validated, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    state = _patch_continuation_state(run_id=run_id or f"patch_upstream_{identity[:24]}", request_id=f"patch_upstream_{identity[:24]}",
        request=request, admitted=admitted)
    graph = build_graph(store, use_default_proposal_git_binding=False, patch_continuation_mode=request,
        patch_upstream_request=selection, planning_target_selection_factory=planning_target_selection_factory,
        evidence_pack_factory=evidence_pack_factory)
    return graph.invoke(state)


def prepare_replanned_patch_input(*, prior_request: PatchContinuationInputV1, state: Mapping[str, Any],
        attempt_id: str | None = None) -> PatchContinuationInputV1:
    """Resolve new exact refs; no inherited failed-run context, worker config or execution approval."""
    from src.mod_agent.artifacts import ArtifactRef

    if state.get("current_stage") != "implementation_plan" or state.get("blockers"):
        raise ValueError("A nonblocking replanned result is required before preparing Patch.")
    refs = {kind: ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
        path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind])
        for kind in ("feature_spec", "evidence_pack", "implementation_plan")}
    if refs["feature_spec"] != prior_request.feature_spec_ref:
        raise ValueError("Upstream reassessment must preserve the original FeatureSpec.")
    result = PatchContinuationInputV1(contract_version=prior_request.contract_version,
        artifact_store_root=prior_request.artifact_store_root, workspace_root=prior_request.workspace_root,
        feature_spec_ref=refs["feature_spec"], evidence_pack_ref=refs["evidence_pack"],
        implementation_plan_ref=refs["implementation_plan"], attempt_id=attempt_id)
    preflight_patch_continuation(result)
    return result
