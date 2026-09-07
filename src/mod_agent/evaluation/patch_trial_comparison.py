"""Read-only comparison of explicit trials of one existing fixed Patch task.

This consumes the execution index and retained qualification identities. It does
not execute checks, select a model, qualify profiles, or create a second ledger.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.fresh_planning_continuation import (
    _csharp_source_snapshot,
    _source_tree_snapshot_sha256,
)
from src.mod_agent.model_qualification import (
    _verify_materialized_response,
    canonical_hash,
    read_bound_json,
)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _bytes(ref: Mapping[str, Any]) -> bytes:
    _require(isinstance(ref, Mapping) and set(ref) == {"path", "sha256"}, "exact_file_reference_missing")
    path = Path(ref["path"])
    _require(path.is_absolute() and not str(path).startswith(("\\\\", "//")), "local_absolute_reference_required")
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == ref["sha256"], "referenced_bytes_changed")
    return raw


def _list_ref(ref: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = json.loads(_bytes(ref))
    _require(isinstance(value, list) and all(isinstance(row, dict) for row in value), "retained_list_invalid")
    return value


def _artifact(store: ArtifactStore, ref: Mapping[str, Any], kind: str) -> dict[str, Any]:
    _require(ref.get("artifact_type") == kind, "artifact_kind_mismatch")
    return store.read(ArtifactRef(**ref))


def _task_context(task_ref: Mapping[str, str]) -> dict[str, Any]:
    task = read_bound_json(task_ref)
    request = read_bound_json(task["continuation_input_ref"])
    store = ArtifactStore(request["artifact_store_root"])
    expected = task["expected_check_ids"]
    _require(isinstance(expected, list) and expected and all(isinstance(x, str) and x for x in expected)
             and len(set(expected)) == len(expected), "fixed_check_set_invalid")
    artifacts = {}
    for kind in ("feature_spec", "evidence_pack", "implementation_plan"):
        ref = task[kind + "_ref"]
        _require(ref == request[kind + "_ref"], "task_input_artifact_mismatch")
        artifacts[kind] = _artifact(store, ref, kind)
    baseline = read_bound_json(task["baseline"]["matrix_ref"])
    checks = baseline["checks"]
    _require(len(checks) == len(expected) and {row["check"] for row in checks} == set(expected), "baseline_check_set_incomplete")
    worker = read_bound_json(task["worker_configuration_ref"])
    evaluator = worker["behavior_evaluator"]
    _bytes(evaluator["factory_ref"])
    identity = task["verification_identity"]
    _require(evaluator["factory_ref"]["sha256"] == identity["validator_sha256"], "verifier_definition_mismatch")
    _require(all(isinstance(identity.get(key), str) and len(identity[key]) == 64
                 for key in ("validator_sha256", "inputs_sha256", "environment_sha256")), "verification_identity_incomplete")
    workspace = Path(request["workspace_root"])
    snapshot = _source_tree_snapshot_sha256(_csharp_source_snapshot(workspace))
    return {"task": task, "request": request, "store": store, "artifacts": artifacts,
            "expected": set(expected), "baseline_checks": {row["check"]: row for row in checks},
            "worker": worker, "snapshot": snapshot, "workspace": workspace}


def _evaluation(evaluation: Mapping[str, Any], factory: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    report = read_bound_json(evaluation["report_ref"])
    fields = ("status", "generated_changes_sha256", "source_snapshot_sha256", "observations",
              "verification_identity", "materialized_code_identity", "verification_ref", "verification_summary")
    _require(all(report.get(key) == evaluation.get(key) for key in fields), "report_journal_binding_mismatch")
    _require(evaluation.get("admission") == "accepted", "verification_report_not_admitted")
    _require(report["verification_identity"] == context["task"]["verification_identity"], "verification_identity_mismatch")
    response_hash = evaluation["model_response_sha256"]
    matches = [row for row in factory.get("model_responses", []) if row.get("output_sha256") == response_hash]
    _require(bool(matches), "tested_model_response_missing")
    response_raw = _bytes({"path": matches[-1]["path"], "sha256": response_hash})
    retained = [read_bound_json(turn["response_ref"]) for turn in factory["worker_turns"]]
    _require(any(isinstance(turn.get("content"), str) and turn["content"].encode() == response_raw for turn in retained), "tested_response_not_in_worker_history")
    matrix = read_bound_json(report["verification_ref"])
    commands = _list_ref(matrix["build_commands_ref"])
    _require(bool(commands) and all(type(row.get("exit_code")) is int and type(row.get("process_id")) is int
                                  and row.get("timed_out") is False for row in commands), "compiler_execution_not_verifiable")
    checks = matrix["checks"]
    summary = report["verification_summary"]
    _require(isinstance(checks, list) and summary["checks"] == len(checks)
             and summary["executions"] == matrix["executions"], "verification_counts_mismatch")
    result = {"report_ref": evaluation["report_ref"], "matrix_ref": report["verification_ref"],
              "model_response_sha256": response_hash, "check_count": len(checks),
              "expected_check_count": len(context["expected"]), "checks_passed": None, "checks_failed": None,
              "compilation": "failed" if commands[-1]["exit_code"] != 0 else "passed",
              "behavior": "not_executed", "complete_matrix": False,
              "verification_identity": "matches_frozen_task", "process_executions": matrix["executions"]}
    if matrix.get("status") == "compiler_failed":
        _require(commands[-1]["exit_code"] == matrix["compiler_exit_code"] != 0
                 and not checks and matrix["executions"] == 0, "compiler_failure_record_inconsistent")
        return result
    _require(result["compilation"] == "passed", "behavior_after_failed_compilation")
    _require(report.get("execution_origin") == evaluation.get("execution_origin") == "executed", "matrix_execution_not_recorded")
    _require(len(checks) == len(context["expected"]) and {row["check"] for row in checks} == context["expected"], "matrix_check_set_incomplete")
    for check in checks:
        original = context["baseline_checks"][check["check"]]
        _require(check.get("input") == original.get("input") and check.get("expected") == original.get("expected"), "original_expectation_changed")
        _require(type(check.get("passed")) is bool and check["passed"] == (check["actual"] == check["expected"]), "matrix_verdict_mismatch")
    processes = _list_ref(matrix["process_observations_ref"])
    _require(len(processes) == matrix["executions"] > 0
             and all(type(row.get("process_id")) is int for row in processes), "process_execution_record_incomplete")
    failed = sum(not row["passed"] for row in checks)
    _require(summary["failed_checks"] == failed, "failed_check_total_mismatch")
    _require((report["status"] == matrix["status"] == "passed") == (failed == 0), "matrix_status_mismatch")
    result.update(behavior="passed" if failed == 0 else "failed", checks_passed=len(checks) - failed,
                  checks_failed=failed, complete_matrix=True)
    return result


def _successful_artifacts(journal: Mapping[str, Any], factory: Mapping[str, Any], context: Mapping[str, Any]) -> None:
    terminal = journal["terminal_result"]
    _require(terminal.get("status") == "terminal" and terminal.get("terminal_stage") == "dry_run_apply"
             and journal.get("proposal_admitted") is True, "patch_acceptance_chain_incomplete")
    store = context["store"]
    proposal = _artifact(store, terminal["patch_proposal_artifact"], "patch_proposal")
    review = _artifact(store, terminal["proposal_review_artifact"], "proposal_review")
    dry_run = _artifact(store, terminal["dry_run_artifact"], "dry_run_result")
    _require(proposal["status"] == dry_run["status"] == "success" and review["data"].get("decision") == "approve_dry_run"
             and review["data"].get("allowed_next_stage") == "dry_run_apply", "downstream_review_or_dry_run_not_passed")
    for envelope, refs in ((review, (terminal["patch_proposal_artifact"],)),
                           (dry_run, (terminal["patch_proposal_artifact"], terminal["proposal_review_artifact"]))):
        upstream = envelope.get("inputs", {}).get("upstream_artifacts", [])
        _require(all(any(item.get("path") == ref["path"] and item.get("artifact_hash") == ref["artifact_hash"]
                         for item in upstream) for ref in refs), "downstream_artifact_lineage_mismatch")
    final = factory["patch_agent_loop"]["behavior_evaluations"][-1]
    response = factory["model_response"]
    _require(response["output_sha256"] == final["model_response_sha256"], "final_response_verification_mismatch")
    parsed = read_bound_json({"path": response["path"], "sha256": response["output_sha256"]})
    artifacts = context["artifacts"]
    identity = _verify_materialized_response(feature=artifacts["feature_spec"]["data"],
        evidence=artifacts["evidence_pack"]["data"], plan=artifacts["implementation_plan"]["data"],
        parsed_output=parsed, proposal=proposal["data"], expected_changes_hash=final["generated_changes_sha256"],
        workspace_root=str(context["workspace"]))
    _require(identity == final["materialized_code_identity"], "final_code_identity_mismatch")


def _trial(row: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    result = {"run_id": row["run_id"], "journal_ref": row["journal_ref"], "outcome": "unknown",
              "unknown_reasons": [], "behavior_evaluations": [], "model_qualified": False,
              "index_reference_integrity": row["reference_integrity_counts"],
              "attempt_identity_verification": row["journal_identity_checks"]["attempt_identity"],
              "compilation": "not_executed", "behavior": "not_executed"}
    try:
        journal = read_bound_json(row["journal_ref"])
        factory = journal["factory_receipt"]
        profile = factory["profile"]
        version = factory["qualification_execution_identity"]
        profile_hash = canonical_hash(profile)
        result.update(model=profile["model"], provider=profile["provider"], profile_sha256=profile_hash,
                      worker_implementation_sha256=version["implementation_sha256"], worker_policy_sha256=version["worker_policy_sha256"],
                      worker_identity_scope=version["scope"], model_calls=factory["model_call_count"],
                      source_currentness="unknown", final_stage=journal["terminal_result"]["terminal_stage"])
        _require(row["journal_identity_checks"]["terminal_result_hash"]["status"] == "verified", "terminal_hash_not_verified")
        _require(journal["worker_profile_sha256"] == profile_hash, "profile_hash_mismatch")
        _require(version["implementation_sha256"] == canonical_hash(version["files"]), "worker_manifest_hash_mismatch")
        _require(version["worker_policy_sha256"] == canonical_hash(context["worker"]["policy"]), "worker_policy_mismatch")
        _require(journal["worker_configuration_ref"] == context["task"]["worker_configuration_ref"], "worker_configuration_mismatch")
        _require(journal["generated_against_snapshot_sha256"] == journal["current_snapshot_sha256"] == context["snapshot"], "source_snapshot_changed")
        result["source_currentness"] = "current_source_matches_recorded_snapshot"
        for kind in context["artifacts"]:
            _require(journal["selected_artifacts"][kind] == context["task"][kind + "_ref"], "trial_task_artifact_mismatch")
        turns = factory["worker_turns"]
        _require(len(turns) == factory["model_call_count"] == journal["terminal_result"]["execution_counts"]["model"]
                 and factory.get("replayed_model_turns", 0) == 0, "model_trial_count_or_replay_mismatch")
        for turn in turns:
            response = read_bound_json(turn["response_ref"])
            _require(turn["status"] == "responded" and turn.get("response_origin") == "live_provider_response"
                     and response["model"] == profile["model"], "model_response_identity_or_origin_unverified")
        evaluations = factory["patch_agent_loop"].get("behavior_evaluations", [])
        for evaluation in evaluations:
            result["behavior_evaluations"].append(_evaluation(evaluation, factory, context))
        if result["behavior_evaluations"]:
            last = result["behavior_evaluations"][-1]
            result.update(compilation=last["compilation"], behavior=last["behavior"])
        _require(journal["terminal_result"].get("product_source_writes_performed") is False, "trial_exceeds_no_write_scope")
        if result["behavior"] == "passed":
            _successful_artifacts(journal, factory, context)
            result["outcome"] = "passed"
        elif factory.get("upstream_decision", {}).get("code") == "PATCH_AGENT_UPSTREAM_REQUESTED":
            result["outcome"] = "upstream_requested"
        elif result["compilation"] == "failed":
            result["outcome"] = "compile_failed"
        elif result["behavior"] == "failed":
            result["outcome"] = "behavior_failed"
        elif factory.get("failure", {}).get("diagnostics", {}).get("failure_classification") == "malformed_structured_output":
            result["outcome"] = "format_failed"
        else:
            result["unknown_reasons"].append("no_supported_terminal_outcome")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["unknown_reasons"].append(str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    return result


def compare_patch_trials(*, task_ref: Mapping[str, str], attempt_indexes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Regenerate one task's comparison; every explicitly selected trial stays in the denominator."""
    attempt_locators = [index.get("filters", {}).get("attempt_locator") for index in attempt_indexes]
    _require(all(isinstance(locator, str) and locator for locator in attempt_locators), "explicit_attempt_locator_required")
    _require(bool(attempt_locators) and len(set(attempt_locators)) == len(attempt_locators), "unique_explicit_attempts_required")
    _require(all(index.get("read_only") is True and index.get("model_calls_performed") == 0
                 and index.get("verifier_executions_performed") == 0
                 and index.get("product_source_writes_performed") is False for index in attempt_indexes), "read_only_index_required")
    try:
        context = _task_context(task_ref)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"read_only": True, "authority": "non_authoritative", "persistence": "none",
                "task_ref": dict(task_ref), "task_denominator": None, "trial_denominator": len(attempt_locators),
                "outcomes": {"unknown": len(attempt_locators)}, "verified_passes": 0,
                "observed_trial_completion_fraction": None,
                "trials": [{"journal_locator": locator, "outcome": "unknown", "model_qualified": False,
                            "unknown_reasons": ["fixed_task_unverifiable", type(exc).__name__]}
                           for locator in attempt_locators], "groups": [],
                "model_calls_performed": 0, "verifier_executions_performed": 0,
                "product_source_writes_performed": False, "qualification_published": False, "models_qualified": False}
    trials = []
    seen = set()
    for locator, index in zip(attempt_locators, attempt_indexes, strict=True):
        _require(index["match_count"] <= 1, "ambiguous_attempt")
        if not index["attempts"]:
            trials.append({"journal_locator": locator, "outcome": "unknown", "unknown_reasons": ["journal_missing_or_invalid"], "model_qualified": False})
            continue
        row = index["attempts"][0]
        _require(row["journal_ref"]["path"] not in seen and row["run_id"] not in seen, "duplicate_trial_identity")
        seen.update((row["journal_ref"]["path"], row["run_id"]))
        trials.append(_trial(row, context))
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for trial in trials:
        key = tuple(trial.get(name) for name in ("profile_sha256", "worker_implementation_sha256", "worker_policy_sha256"))
        groups.setdefault(key, []).append(trial)
    counts = Counter(trial["outcome"] for trial in trials)
    return {"read_only": True, "authority": "non_authoritative", "persistence": "none",
            "task_ref": dict(task_ref), "case_id": context["task"]["case_id"], "task_denominator": 1,
            "feature_spec_ref": context["task"]["feature_spec_ref"], "trial_denominator": len(trials),
            "outcomes": dict(counts), "verified_passes": counts["passed"],
            "observed_trial_completion_fraction": counts["passed"] / len(trials), "trials": trials,
            "groups": [{"profile_sha256": key[0], "worker_implementation_sha256": key[1], "worker_policy_sha256": key[2],
                        "model": rows[0].get("model"), "trial_count": len(rows), "outcomes": dict(Counter(row["outcome"] for row in rows))}
                       for key, rows in groups.items()],
            "model_calls_performed": 0, "verifier_executions_performed": 0, "product_source_writes_performed": False,
            "qualification_published": False, "models_qualified": False,
            "limitations": ["One fixed task; repeated trials are not distinct tasks or a model ranking.",
                "Profiles and recorded worker versions differ; this is not a model-only controlled experiment.",
                "Worker manifest is internally checked; its listed source scope does not independently attest every adapter or historical process.",
                "Verification identities match the frozen task; historical environment execution is not rerun.",
                "Complete matrix success is scoped to Patch/Review/Dry-run, not Apply, formal Build, game Runtime or autonomous Planning."]}
