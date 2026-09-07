"""Read one run's exact Proposal/Review/Dry-run for a human DSH command.

The view grants no approval. Source materialization is in memory and never
invokes a model, validator, Graph, artifact write or product Apply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.execution.patch_apply import (
    PatchApplyError,
    _build_unified_diff,
    _diff_hash,
    _sha256_json,
    materialize_exact_text_patch,
)
from src.observability.patch_execution_index import project_patch_executions

_ARTIFACT_FIELDS = {"patch_proposal": "patch_proposal_artifact", "proposal_review": "proposal_review_artifact",
                    "dry_run_result": "dry_run_artifact"}
_REF_FIELDS = ("feature_id", "artifact_type", "path", "artifact_hash")


def _ref(value, feature_id, kind):
    if not isinstance(value, dict) or value.get("integrity") != "verified_artifact":
        raise ValueError("REVIEW_ARTIFACT_REFERENCE_INVALID")
    result = {key: value[key] for key in _REF_FIELDS}
    if result["feature_id"] != feature_id or result["artifact_type"] != kind:
        raise ValueError("REVIEW_ARTIFACT_IDENTITY_MISMATCH")
    return result


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
    projection = project_patch_executions(store_root, feature_id=feature_id, run_id=run_id)
    if projection["match_count"] != 1:
        raise ValueError("RUN_NOT_UNIQUE_OR_MISSING")
    row = projection["attempts"][0]
    result = {"entry": "review-run", "read_only": True, "run_id": run_id, "feature_id": feature_id,
              "journal_ref": row["journal_ref"], "artifacts": {}, "unified_diff": None,
              "source_currentness": {"status": "not_checked"},
              "recorded_stage": row["terminal"].get("terminal_stage"), "recorded_status": row["terminal"].get("status"),
              "behavior_verification_recorded": row["behavior_evaluations"],
              "query_model_calls": 0, "query_verifier_executions": 0, "product_source_writes_performed": False,
              "artifact_writes_performed": False, "approval_created": False, "apply_allowed": False,
              "product_execution_started": False, "review_is_historical_not_current_apply_approval": True}
    if row["journal_identity_checks"]["terminal_result_hash"]["status"] != "verified":
        return {**result, "status": "review_unavailable", "reason": "TERMINAL_RECORD_UNVERIFIED"}
    try:
        for kind, field in _ARTIFACT_FIELDS.items():
            current = row["current_artifacts"].get(kind, {}).get("ref")
            terminal = row["terminal_artifacts"][field]["ref"]
            if current is not None and terminal is not None:
                if _ref(current, feature_id, kind) != _ref(terminal, feature_id, kind):
                    raise ValueError("CURRENT_TERMINAL_ARTIFACT_CONFLICT")
            if current is not None or terminal is not None:
                result["artifacts"][kind] = _ref(current if current is not None else terminal, feature_id, kind)
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
        plan_ref = _ref(row["selected_upstreams"]["implementation_plan"], feature_id, "implementation_plan")
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
                "apply_build_runtime": "not_executed_by_this_view", "historical_execution_counts": row["budget_and_counts_recorded"]})
        return result
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {**result, "status": "review_unavailable", "unified_diff": None,
                "reason": str(exc) if isinstance(exc, ValueError) and str(exc).isupper() else "EXACT_REVIEW_RECORD_INVALID"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact-store-root", "workspace-root", "feature-id", "run-id"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    result = review_run(artifact_store_root=args.artifact_store_root, workspace_root=args.workspace_root,
                        feature_id=args.feature_id, run_id=args.run_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
