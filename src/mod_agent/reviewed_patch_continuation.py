"""Review retained exact artifacts and resume human-approved isolated application.

Read/preparation functions grant no approval. Only apply_reviewed_patch accepts
the existing human semantic decision and enters the original Graph/Applier.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.execution.patch_apply import (
    PatchApplyError,
    _build_unified_diff,
    _diff_hash,
    _sha256_json,
    materialize_exact_text_patch,
)
from src.mod_agent.fresh_planning_continuation import (
    PATCH_CONTINUATION_RECEIPT_VERSION,
    _canonical_sha256,
)

_ARTIFACT_FIELDS = {"patch_proposal": "patch_proposal_artifact", "proposal_review": "proposal_review_artifact",
                    "dry_run_result": "dry_run_artifact"}
_REF_FIELDS = ("feature_id", "artifact_type", "path", "artifact_hash")
_INPUT_FIELDS = {"feature_spec": "feature_spec_artifact", "evidence_pack": "evidence_pack_artifact",
                 "implementation_plan": "implementation_plan_artifact"}


def _ref(value, feature_id, kind):
    if (not isinstance(value, dict) or set(value) != set(_REF_FIELDS)
            or any(not isinstance(value[key], str) or not value[key] for key in _REF_FIELDS)):
        raise ValueError("REVIEW_ARTIFACT_REFERENCE_INVALID")
    result = {key: value[key] for key in _REF_FIELDS}
    if result["feature_id"] != feature_id or result["artifact_type"] != kind:
        raise ValueError("REVIEW_ARTIFACT_IDENTITY_MISMATCH")
    return result


def _read_retained_journal(store_root, feature_id, run_id):
    # Same locator as PatchContinuationAttemptJournal and its terminal-cache owner.
    path = Path(store_root).resolve() / "cr" / (hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32] + ".json")
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ValueError("RUN_NOT_UNIQUE_OR_MISSING") from exc
    if (not isinstance(document, dict) or document.get("receipt_version") != PATCH_CONTINUATION_RECEIPT_VERSION
            or document.get("run_id") != run_id or document.get("feature_id") != feature_id):
        raise ValueError("RUN_NOT_UNIQUE_OR_MISSING")
    return document, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _verified_terminal(document, feature_id, run_id):
    terminal = document.get("terminal_result")
    if (not isinstance(terminal, dict) or document.get("terminal_result_sha256") != _canonical_sha256(terminal)
            or terminal.get("run_id") != run_id or terminal.get("feature_id") != feature_id
            or terminal.get("request_id") != document.get("request_id")):
        raise ValueError("TERMINAL_RECORD_UNVERIFIED")
    return terminal


def _terminal_ref(document, terminal, feature_id, kind, field):
    value = terminal.get(field)
    current = (document.get("artifacts") or {}).get(kind)
    if current is not None and (value is None or _ref(current, feature_id, kind) != _ref(value, feature_id, kind)):
        raise ValueError("CURRENT_TERMINAL_ARTIFACT_CONFLICT")
    return None if value is None else _ref(value, feature_id, kind)


def _recorded_behavior_summaries(document):
    evaluations = ((document.get("factory_receipt") or {}).get("patch_agent_loop") or {}).get("behavior_evaluations") or []
    fields = ("status", "failure_owner", "evaluation_index", "report_ref", "generated_changes_sha256",
              "model_response_sha256", "execution_origin", "callback_invoked")
    return [{key: row[key] for key in fields if key in row} for row in evaluations if isinstance(row, dict)]


def _has_upstream(document, ref):
    return any(isinstance(item, dict) and all(item.get(key) == ref[key]
        for key in ("artifact_type", "path", "artifact_hash"))
        for item in document.get("inputs", {}).get("upstream_artifacts", []))


def _source_comparison(workspace, dry_run, proposal, plan):
    files = {}
    for change in dry_run["changes"]:
        relative = change["path"]
        target = (workspace / relative).resolve()
        if Path(relative).is_absolute() or not target.is_relative_to(workspace):
            raise ValueError("REVIEW_SOURCE_PATH_OUTSIDE_CONFIGURED_WORKSPACE")
        if relative in files:
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        expected = change["raw_before_sha256"]
        files[relative] = {"path": relative, "expected_baseline_sha256": expected,
                           "current_sha256": actual, "matches": expected == actual}
    result = {"scope": "changed_files_and_plan_bound_in_memory_materialization_only",
              "files": list(files.values()), "first_difference": next((row for row in files.values() if not row["matches"]), None),
              "source_tree_wide_freshness": "not_checked", "materializer_executed_in_memory": False,
              "approval_or_apply_eligibility": "not_granted_by_this_view"}
    if result["first_difference"] is not None:
        return {**result, "status": "source_changed", "diff_recomputed_matches": None}
    try:
        materialized = materialize_exact_text_patch(workspace_root=workspace,
            diff_intent=proposal["diff_intent"], implementation_plan=plan)
        rendered = _build_unified_diff(root=workspace,
            original_by_target={workspace / path: raw for path, raw in materialized.baseline_files.items()},
            staged={workspace / path: raw for path, raw in materialized.files.items()})
        matches = rendered == dry_run["unified_diff"]
        return {**result, "status": "matches_original_baseline" if matches else "materialized_diff_mismatch",
                "materializer_executed_in_memory": True, "diff_recomputed_matches": matches,
                "baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256}
    except (PatchApplyError, OSError, ValueError):
        return {**result, "status": "source_or_binding_check_failed", "diff_recomputed_matches": None}


def review_run(*, artifact_store_root: str, workspace_root: str, feature_id: str, run_id: str) -> dict:
    for value in (feature_id, run_id):
        if not isinstance(value, str) or not value.strip() or len(value) > 300 or any(c in value for c in "\r\n\0"):
            raise ValueError("REVIEW_ID_INVALID")
    workspace, store_root = Path(workspace_root), Path(artifact_store_root)
    if not workspace.is_absolute() or not workspace.is_dir() or not store_root.is_absolute() or not store_root.is_dir():
        raise ValueError("REVIEW_CONFIGURED_ROOT_UNAVAILABLE")
    workspace = workspace.resolve()
    document, journal_ref = _read_retained_journal(store_root, feature_id, run_id)
    terminal = document.get("terminal_result") or {}
    result = {"entry": "review-run", "read_only": True, "run_id": run_id, "feature_id": feature_id,
              "journal_ref": journal_ref, "artifacts": {}, "unified_diff": None,
              "source_currentness": {"status": "not_checked"},
              "recorded_stage": terminal.get("terminal_stage") if isinstance(terminal, dict) else None,
              "recorded_status": terminal.get("status") if isinstance(terminal, dict) else None,
              "behavior_verification_recorded": _recorded_behavior_summaries(document),
              "query_model_calls": 0, "query_verifier_executions": 0, "product_source_writes_performed": False,
              "artifact_writes_performed": False, "approval_created": False, "apply_allowed": False,
              "product_execution_started": False, "review_is_historical_not_current_apply_approval": True}
    try:
        terminal = _verified_terminal(document, feature_id, run_id)
        for kind, field in _ARTIFACT_FIELDS.items():
            selected = _terminal_ref(document, terminal, feature_id, kind, field)
            if selected is not None:
                result["artifacts"][kind] = selected
        if "patch_proposal" not in result["artifacts"]:
            return {**result, "status": "no_reviewable_diff", "reason": "THIS_RUN_HAS_NO_NEW_PROPOSAL"}
        if len(result["artifacts"]) != 3:
            return {**result, "status": "no_reviewable_diff", "reason": "THIS_RUN_HAS_NO_COMPLETE_REVIEWED_DRY_RUN"}
        store = ArtifactStore(store_root)
        documents = {kind: store.semantic_read_immutable(ArtifactRef(**ref)) for kind, ref in result["artifacts"].items()}
        proposal, review, dry_run = (documents[kind]["data"] for kind in _ARTIFACT_FIELDS)
        if (not _has_upstream(documents["proposal_review"], result["artifacts"]["patch_proposal"])
                or not all(_has_upstream(documents["dry_run_result"], result["artifacts"][kind])
                           for kind in ("patch_proposal", "proposal_review"))):
            raise ValueError("REVIEW_DRY_RUN_LINEAGE_MISMATCH")
        plan_ref = _terminal_ref(document, terminal, feature_id, "implementation_plan", "implementation_plan_artifact")
        if not _has_upstream(documents["patch_proposal"], plan_ref):
            raise ValueError("PROPOSAL_PLAN_LINEAGE_MISMATCH")
        plan = store.semantic_read_immutable(ArtifactRef(**plan_ref))["data"]
        context = dry_run["context_hashes"]
        if any(context.get(key) != _sha256_json(value) for key, value in (
                ("proposal_payload_sha256", proposal), ("proposal_review_payload_sha256", review),
                ("implementation_plan_payload_sha256", plan))):
            raise ValueError("DRY_RUN_CONTEXT_HASH_MISMATCH")
        raw = dry_run["unified_diff"].encode("utf-8")
        if (hashlib.sha256(raw).hexdigest() != dry_run["unified_diff_sha256"] or len(raw) != dry_run["unified_diff_bytes"]
                or dry_run["diff_hash"] != _diff_hash(proposal_id=proposal["proposal_id"],
                    diff_preview=dry_run["diff_preview"], context_hashes=context)):
            raise ValueError("DRY_RUN_DIFF_IDENTITY_MISMATCH")
        result.update(status="reviewable_diff", unified_diff=dry_run["unified_diff"], diff_hash=dry_run["diff_hash"],
            unified_diff_sha256=dry_run["unified_diff_sha256"], diff_stats=dry_run["diff_stats"],
            original_review={key: review.get(key) for key in ("decision", "allowed_next_stage", "findings", "required_changes",
                "human_semantic_review_required", "semantic_assurance")},
            original_dry_run={key: dry_run.get(key) for key in ("execution_mode", "actual_write_performed", "human_semantic_review_completed",
                "human_semantic_review_result", "approved_by_user", "static_checks", "limitations")},
            source_currentness=_source_comparison(workspace, dry_run, proposal, plan),
            stage_limits={"human_semantic_review": "not_performed_by_this_view", "exact_diff_approval": "not_granted_by_this_view",
                "apply_build_runtime": "not_executed_by_this_view", "historical_execution_counts": terminal["execution_counts"]})
        return result
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {**result, "status": "review_unavailable", "unified_diff": None,
                "reason": str(exc) if isinstance(exc, ValueError) and str(exc).isupper() else "EXACT_REVIEW_RECORD_INVALID"}


_COPY_IGNORED = frozenset({"bin", "obj", ".git", ".idea"})


def _copy_source_snapshot(root):
    from src.mod_agent.product_executor import source_snapshot

    for path in root.rglob("*"):
        if any(part in _COPY_IGNORED for part in path.relative_to(root).parts):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("APPLY_COPY_LINK_OUTSIDE_SOURCE")
    return [row for row in source_snapshot(root)
            if not any(part in _COPY_IGNORED for part in Path(row["path"]).parts)]


def _apply_inputs(*, artifact_store_root, workspace_root, feature_id, run_id):
    from src.mod_agent.execution.patch_apply import ExactTextPatchApplier
    from src.mod_agent.fresh_planning_continuation import (
        PATCH_CONTINUATION_CONTRACT_VERSION,
        PatchContinuationInputV1,
        preflight_patch_continuation,
    )

    viewed = review_run(artifact_store_root=artifact_store_root, workspace_root=workspace_root,
                       feature_id=feature_id, run_id=run_id)
    if viewed["status"] != "reviewable_diff":
        raise ValueError("APPLY_EXACT_REVIEW_UNAVAILABLE")
    if viewed["source_currentness"]["status"] != "matches_original_baseline":
        raise ValueError("APPLY_REVIEW_SOURCE_CHANGED")
    document, journal_ref = _read_retained_journal(artifact_store_root, feature_id, run_id)
    terminal = _verified_terminal(document, feature_id, run_id)
    if journal_ref != viewed["journal_ref"]:
        raise ValueError("APPLY_REVIEW_RECORD_CHANGED")
    if (terminal["status"] != "terminal" or terminal["terminal_stage"] != "dry_run_apply"
            or terminal.get("first_failure") is not None or document.get("proposal_admitted") is not True):
        raise ValueError("APPLY_RETAINED_RUN_NOT_READY")
    selected = {kind: ArtifactRef(**_terminal_ref(document, terminal, feature_id, kind, field))
                for kind, field in _INPUT_FIELDS.items()}
    store = ArtifactStore(artifact_store_root)
    request = PatchContinuationInputV1(contract_version=PATCH_CONTINUATION_CONTRACT_VERSION,
        artifact_store_root=artifact_store_root, workspace_root=workspace_root,
        feature_spec_ref=selected["feature_spec"], evidence_pack_ref=selected["evidence_pack"],
        implementation_plan_ref=selected["implementation_plan"])
    admitted = preflight_patch_continuation(request, artifact_store=store)
    refs = {kind: ArtifactRef(**ref) for kind, ref in viewed["artifacts"].items()}
    documents = {kind: store.semantic_read_immutable(ref) for kind, ref in refs.items()}
    if any(document["status"] != "success" for document in documents.values()):
        raise ValueError("APPLY_ARTIFACT_STATUS_NOT_SUCCESS")
    payloads = {kind: document["data"] for kind, document in documents.items()}
    dry = ExactTextPatchApplier().run(workspace_root=workspace_root,
        proposal=payloads["patch_proposal"], implementation_plan=admitted.implementation_plan,
        review=payloads["proposal_review"], allow_write=False)
    if dry["diff_hash"] != viewed["diff_hash"] or dry["unified_diff_sha256"] != viewed["unified_diff_sha256"]:
        raise ValueError("APPLY_CURRENT_DIFF_DIFFERS_FROM_DISPLAYED")
    if dry["human_semantic_review_required"] is not True:
        raise ValueError("APPLY_STRUCTURED_SEMANTIC_REVIEW_REQUIRED")
    return viewed, store, admitted, {**selected, **refs}, payloads, dry


def prepare_reviewed_patch_apply(*, artifact_store_root, workspace_root, feature_id, run_id,
                                isolated_root, operation_id):
    """Prepare a human action using current original contracts, without writes."""
    if (not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 200
            or any(char in operation_id for char in "\r\n\0")):
        raise ValueError("APPLY_OPERATION_ID_INVALID")
    source = Path(workspace_root).resolve()
    destination_root = Path(isolated_root)
    if not destination_root.is_absolute() or not destination_root.is_dir():
        raise ValueError("APPLY_CONFIGURED_ISOLATED_ROOT_UNAVAILABLE")
    destination_root = destination_root.resolve()
    store_root = Path(artifact_store_root).resolve()
    if (destination_root.is_relative_to(source) or source.is_relative_to(destination_root)
            or destination_root.is_relative_to(store_root) or store_root.is_relative_to(destination_root)):
        raise ValueError("APPLY_SOURCE_STORE_DESTINATION_OVERLAP")
    viewed, _store, _admitted, _refs, _payloads, dry = _apply_inputs(
        artifact_store_root=artifact_store_root, workspace_root=str(source), feature_id=feature_id, run_id=run_id)
    destination = destination_root / hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:32]
    if destination.exists():
        raise ValueError("APPLY_OPERATION_DESTINATION_ALREADY_EXISTS")
    snapshot = _copy_source_snapshot(source)
    binding = {"run_id": run_id, "feature_id": feature_id, "operation_id": operation_id,
        "journal_sha256": viewed["journal_ref"]["sha256"], "diff_hash": dry["diff_hash"],
        "unified_diff_sha256": dry["unified_diff_sha256"],
        "source_snapshot_sha256": _sha256_json(snapshot), "workspace_root": str(source),
        "isolated_root": str(destination_root), "isolated_workspace": str(destination),
        "human_semantic_decision_binding": dry["human_semantic_decision_binding"]}
    return {**viewed, "apply_preparation": {"binding": binding,
        "write_target": str(destination), "copy_scope": "configured_workspace_tree",
        "copy_exclusions": sorted(_COPY_IGNORED), "source_file_count": len(snapshot),
        "source_root_provenance": "configured_source_verified_against_retained_baseline",
        "stop_before": "build", "build_runtime_started": False,
        "instruction": "Review this exact diff and isolation target, then explicitly approve or reject with your reviewer identity."}}


def apply_reviewed_patch(*, artifact_store_root, workspace_root, feature_id, run_id,
                         isolated_root, displayed_binding, human_semantic_decision,
                         execution_trace_configuration=None):
    """Trace this approval invocation using the original prospective trace owner."""
    from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration

    if not isinstance(displayed_binding, dict) or not isinstance(displayed_binding.get("operation_id"), str):
        raise ValueError("APPLY_DISPLAY_BINDING_REQUIRED")
    observations = {}
    configuration = execution_trace_configuration or PatchExecutionTraceConfiguration()
    trace = configuration.make_trace(run_id=_apply_run_id(displayed_binding["operation_id"]),
        feature_id=feature_id, artifact_store_root=artifact_store_root,
        recorder=lambda row: observations.update({row["id"]: row}))
    failure = None
    try:
        with trace.activate():
            result = _apply_reviewed_patch_once(artifact_store_root=artifact_store_root,
                workspace_root=workspace_root, feature_id=feature_id, run_id=run_id,
                isolated_root=isolated_root, displayed_binding=displayed_binding,
                human_semantic_decision=human_semantic_decision)
            trace.update(workflow_status=result["status"],
                terminal_stage="isolated_apply" if result["isolated_workspace_created"] else "human_decision")
    except BaseException as error:
        failure = error
        raise
    finally:
        summary = configuration.finish(trace)
        summary.update(trace_id=trace.context.trace_id, session_id=trace.session_id, environment=trace.environment)
        if failure is not None:
            # Preserve measured failure facts without changing or swallowing the
            # original exception, and without writing a rejected action to disk.
            try:
                failure.execution_trace = summary
                failure.execution_observations = observations
            except Exception:
                pass
    result.update(execution_trace=summary, execution_observations=observations)
    if result["isolated_workspace_created"]:
        path = Path(result["isolated_workspace"]) / "reviewed-apply-result.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, sort_keys=True)
    return result


def _apply_run_id(operation_id):
    return "reviewed_apply_" + hashlib.sha256(operation_id.encode()).hexdigest()[:24]


def _apply_reviewed_patch_once(*, artifact_store_root, workspace_root, feature_id, run_id,
                              isolated_root, displayed_binding, human_semantic_decision):
    """Re-admit a displayed action, then use the existing Graph and real Applier.

    This boundary stops before Build; it never updates the source workspace.
    The passed human decision is the existing human_semantic_decision_v1 object.
    """
    from src.mod_agent.execution.patch_apply import (
        ExactTextPatchApplier,
        _validate_human_semantic_decision,
    )
    from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore
    from src.mod_agent.workflow.graph import build_graph
    from src.mod_agent.workflow.state import create_initial_state

    if not isinstance(displayed_binding, dict):
        raise ValueError("APPLY_DISPLAY_BINDING_REQUIRED")
    prepared = prepare_reviewed_patch_apply(artifact_store_root=artifact_store_root,
        workspace_root=workspace_root, feature_id=feature_id, run_id=run_id, isolated_root=isolated_root,
        operation_id=displayed_binding.get("operation_id"))
    current = prepared["apply_preparation"]["binding"]
    if displayed_binding != current:
        raise ValueError("APPLY_DISPLAY_BINDING_STALE")
    decision = _validate_human_semantic_decision(human_semantic_decision,
        expected_binding=current["human_semantic_decision_binding"])
    base_result = {"entry": "apply-patch", "run_id": run_id, "feature_id": feature_id,
        "operation_id": current["operation_id"], "diff_hash": current["diff_hash"],
        "source_workspace_written": False, "model_calls_performed": 0, "builds_performed": 0,
        "runtime_executions_performed": 0, "stopped_before": "build", "human_decision": decision}
    if decision["decision"] == "reject":
        return {**base_result, "status": "rejected", "product_source_writes_performed": False,
                "artifact_writes_performed": False, "isolated_workspace_created": False}
    _, store, admitted, refs, payloads, _ = _apply_inputs(artifact_store_root=artifact_store_root,
        workspace_root=workspace_root, feature_id=feature_id, run_id=run_id)
    source, destination = Path(workspace_root).resolve(), Path(current["isolated_workspace"])
    before = _copy_source_snapshot(source)
    if _sha256_json(before) != current["source_snapshot_sha256"]:
        raise ValueError("APPLY_SOURCE_CHANGED_BEFORE_COPY")
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*sorted(_COPY_IGNORED)))
    if _copy_source_snapshot(destination) != before or _copy_source_snapshot(source) != before:
        raise ValueError("APPLY_ISOLATED_COPY_SOURCE_MISMATCH")
    applier = ExactTextPatchApplier()

    def dry_run_factory(proposal, implementation, review):
        dry = applier.run(workspace_root=destination, proposal=proposal,
            implementation_plan=implementation, review=review, allow_write=False)
        if dry["diff_hash"] != current["diff_hash"] or dry["unified_diff_sha256"] != current["unified_diff_sha256"]:
            raise ValueError("APPLY_ISOLATED_DIFF_CHANGED")
        return dry

    def isolated_apply_factory(proposal, implementation, review):
        if _copy_source_snapshot(source) != before:
            raise ValueError("APPLY_SOURCE_CHANGED_AFTER_APPROVAL")
        return applier.run(workspace_root=destination, proposal=proposal,
            implementation_plan=implementation, review=review, allow_write=True,
            approved_diff_hash=current["diff_hash"], human_semantic_decision=decision)

    state = create_initial_state(run_id=_apply_run_id(current["operation_id"]),
        request_id="reviewed_apply_" + current["operation_id"], user_request=admitted.feature_spec["user_request"],
        confirmed_isolated_write=True)
    state.update(feature_id=feature_id, current_stage="proposal_review",
        review_summary={key: payloads["proposal_review"].get(key) for key in ("decision", "allowed_next_stage")},
        artifacts={kind: ref.path for kind, ref in refs.items()},
        artifact_hashes={kind: ref.artifact_hash for kind, ref in refs.items()})
    graph = build_graph(store, dry_run_factory=dry_run_factory, isolated_apply_factory=isolated_apply_factory,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(), interrupt_before=["build"])
    config = {"configurable": {"thread_id": state["run_id"]}}
    resumed = graph.update_state(config, state, as_node="review_proposal")
    finished = graph.invoke(None, resumed)
    source_unchanged = _copy_source_snapshot(source) == before
    apply_ref = ArtifactRef(feature_id=feature_id, artifact_type="isolated_apply_result",
        path=finished["artifacts"]["isolated_apply_result"],
        artifact_hash=finished["artifact_hashes"]["isolated_apply_result"])
    applied = store.read(apply_ref)["data"]
    complete = applied["actual_write_performed"] is True and not finished["blockers"] and source_unchanged
    result = {**base_result, "status": "applied_in_isolation" if complete else "blocked",
        "source_workspace_written": not source_unchanged, "isolated_workspace": str(destination),
        "isolated_workspace_created": True, "artifact_writes_performed": True,
        "product_source_writes_performed": applied["actual_write_performed"],
        "isolated_apply_result": {"feature_id": apply_ref.feature_id, "artifact_type": apply_ref.artifact_type,
            "path": apply_ref.path, "artifact_hash": apply_ref.artifact_hash},
        "next_nodes": list(graph.get_state(config).next), "blockers": finished["blockers"],
        "trace_events": finished["trace_events"],
        "delivery_scope": "approved_bytes_in_isolated_workspace_not_built_or_runtime_verified"}
    return result
