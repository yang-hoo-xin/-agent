"""Prepare paired local-model trials over an existing immutable Patch task suite.

This is an experiment-input consumer, not a trainer, scorer, qualification
resolver or execution engine. One selected cell returns original public CLI
arguments. Prepared cells remain unrun; historical trials are never relabelled.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from src.mod_agent.evaluation import patch_task_suite
from src.mod_agent.evaluation.patch_task_suite import (
    _checked_profile,
    _checked_suite,
    reference,
    save_once,
    select_patch_task,
    task_cli_arguments,
)
from src.mod_agent.model_admission import (
    validate_ollama_context_window,
    validate_ollama_model_identity,
)
from src.mod_agent.model_qualification import (
    canonical_hash,
    read_bound_json,
    worker_implementation_identity,
)
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.observability.patch_execution_index import project_patch_executions

EXPERIMENT_SCHEMA = "patch_model_experiment_preparation_v1"
_SPLITS = ("training", "validation", "holdout")


def _preparation_identity():
    here = Path(__file__).resolve()
    return [reference(path) for path in (here, Path(patch_task_suite.__file__),
        here.parents[3] / "scripts/prepare_patch_eval_suite.py")]


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _partitions(suite, partitions):
    _require(isinstance(partitions, dict) and set(partitions) == set(_SPLITS), "EXPERIMENT_SPLITS_REQUIRED")
    _require(all(isinstance(value, list) and value and all(isinstance(item, str) for item in value)
                 for value in partitions.values()), "EXPERIMENT_SPLIT_EMPTY_OR_INVALID")
    selected = [case for split in _SPLITS for case in partitions[split]]
    expected = {case["case_id"] for case in suite["cases"]}
    _require(len(selected) == len(set(selected)) and set(selected) == expected,
             "EXPERIMENT_TASK_PARTITIONS_NOT_DISJOINT_AND_COMPLETE")
    return {case: split for split in _SPLITS for case in partitions[split]}


def _profiles(suite, rows):
    _require(isinstance(rows, list) and 2 <= len(rows) <= 5, "EXPERIMENT_TWO_TO_FIVE_PROFILES_REQUIRED")
    result = []
    common = {key: value for key, value in suite["execution_profile"].items() if key != "model"}
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"profile_id", "profile", "model_identity_ref"},
                 "EXPERIMENT_PROFILE_FIELDS_INVALID")
        _require(isinstance(row["profile_id"], str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", row["profile_id"]),
                 "EXPERIMENT_PROFILE_ID_INVALID")
        profile = _checked_profile(row["profile"])
        _require({key: value for key, value in profile.items() if key != "model"} == common,
                 "EXPERIMENT_NON_MODEL_PROFILE_AXIS_CHANGED")
        identity = read_bound_json(row["model_identity_ref"])
        validate_ollama_model_identity(identity, expected_base_url=profile["base_url"], expected_model=profile["model"])
        validate_ollama_context_window(identity, requested_context_window=profile["context_window"])
        _require({"completion", "tools"} <= set(identity["capabilities"]), "EXPERIMENT_MODEL_CAPABILITY_UNDECLARED")
        result.append({**row, "profile_sha256": canonical_hash(profile), "model_digest": identity["digest"],
            "inventory_identity_scope": "retained_catalogue_not_current_live_availability_or_qualification"})
    _require(len({row["profile_id"] for row in result}) == len(result)
             and len({(row["profile"]["model"], row["model_digest"]) for row in result}) == len(result),
             "EXPERIMENT_DUPLICATE_MODEL_PROFILE")
    return result


def _case_snapshot(suite_ref, case, profile):
    request = select_patch_task(suite_ref=suite_ref, case_id=case["case_id"],
        attempt_id="experiment-preflight-" + case["case_id"], execution_profile=profile)
    configuration = PatchWorkerConfiguration.load(request.worker_configuration_ref["path"])
    config = read_bound_json(request.worker_configuration_ref)
    return {"case_id": case["case_id"], "feature_spec_ref": asdict(request.feature_spec_ref),
        "evidence_pack_ref": asdict(request.evidence_pack_ref), "implementation_plan_ref": asdict(request.implementation_plan_ref),
        "continuation_input_ref": case["execution"]["continuation_input_ref"],
        "worker_configuration_ref": request.worker_configuration_ref, "worker_policy": asdict(configuration.policy),
        "verifier_factory_ref": config["behavior_evaluator"]["factory_ref"],
        "verification_identity": case["verification_identity"], "expected_check_ids": case["expected_check_ids"],
        "workspace_root": request.workspace_root, "artifact_store_root": request.artifact_store_root,
        "role": case["execution"]["role"], "planning_target_selection": case["execution"].get("planning_target_selection")}


def _cells(suite_ref, experiment_id, tasks, selected_profiles):
    cells = []
    for task in tasks:
        for selected in selected_profiles:
            cell_id = canonical_hash({"experiment_id": experiment_id, "case_id": task["case_id"],
                                      "profile_id": selected["profile_id"]})[:24]
            attempt_id = "experiment-" + experiment_id + "-" + cell_id
            arguments = task_cli_arguments(suite_ref=suite_ref, case_id=task["case_id"],
                attempt_id=attempt_id, execution_profile=selected["profile"])
            cells.append({"cell_id": cell_id, "case_id": task["case_id"], "split": task["split"],
                "profile_id": selected["profile_id"], "attempt_id": attempt_id,
                "shared_input_sha256": task["shared_input_sha256"], "profile_sha256": selected["profile_sha256"],
                "model_digest": selected["model_digest"], "arguments": arguments,
                "trial_status_at_preparation": "not_run", "protocol": "not_run", "action_quality": "not_evaluated",
                "compilation": "not_run", "behavior": "not_run", "performance": "not_measured"})
    return cells


def prepare_patch_model_experiment(*, suite_ref, experiment_id, partitions, profiles, output_root):
    _require(isinstance(experiment_id, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", experiment_id),
             "EXPERIMENT_ID_INVALID")
    suite = _checked_suite(suite_ref)
    split_by_case = _partitions(suite, partitions)
    selected_profiles = _profiles(suite, profiles)
    tasks, exposure = [], []
    for case in suite["cases"]:
        snapshot = _case_snapshot(suite_ref, case, selected_profiles[0]["profile"])
        index = project_patch_executions(case["artifact_store_root"], feature_id=case["feature_spec_ref"]["feature_id"])
        previous = [row["journal_ref"] for row in index["attempts"]
            if (type(row["budget_and_counts_recorded"].get("model_call_count")) is int
                and row["budget_and_counts_recorded"]["model_call_count"] > 0) or row.get("worker_turns")]
        observed = bool(previous or case.get("prior_failure_observation_ref"))
        _require(not (split_by_case[case["case_id"]] == "holdout" and observed),
                 "EXPERIMENT_EXPOSED_TASK_CANNOT_BE_HOLDOUT")
        tasks.append({**snapshot, "split": split_by_case[case["case_id"]],
                      "shared_input_sha256": canonical_hash(snapshot)})
        exposure.append({"case_id": case["case_id"], "prior_model_attempts_in_configured_store": previous,
            "prior_failure_observation_ref": case.get("prior_failure_observation_ref"),
            "known_exposed": observed, "independence_scope": "task_identity_only_shared_repository_source_exposure_not_proven"})
    policy_hashes = {canonical_hash(task["worker_policy"]) for task in tasks}
    _require(len(policy_hashes) == 1, "EXPERIMENT_TASK_WORKER_BUDGETS_DIFFER")
    cells = _cells(suite_ref, experiment_id, tasks, selected_profiles)
    prepared = {"schema_version": EXPERIMENT_SCHEMA, "experiment_id": experiment_id,
        "suite_ref": suite_ref, "partitions": partitions, "profiles": selected_profiles,
        "tasks": tasks, "cells": cells, "exposure_at_preparation": exposure,
        "worker_execution_identity": worker_implementation_identity(),
        "preparation_implementation_refs": _preparation_identity(),
        "version_basis": "current_working_tree_exact_file_bytes_no_commit_or_release_claim",
        "comparison_axis": "model_identity_only_all_other_profile_fields_and_each_task_input_fixed",
        "distinct_task_denominator": len(tasks), "planned_trial_denominator": len(cells),
        "split_task_denominators": dict(Counter(task["split"] for task in tasks)),
        "metric_boundaries": {"protocol": "full_submission_schema_outcomes_not_code_behavior",
            "action_quality": "requires_task_semantic_assessment_not_tool_count_or_frontend_understanding",
            "code_delivery": "compilation_behavior_and_original_review_chain_are_separate",
            "end_to_end": "all_planned_trials_retained_protocol_tool_timeout_failures_are_not_dropped",
            "performance": "measured_duration_usage_resource_facts_only_no_invented_cost_or_TTFT"},
        "observed_trials_at_preparation": 0, "observed_task_success_rate": None,
        "training_performed": False, "training_gain": None, "models_qualified": False,
        "holdout_independence": "partition_declared_task_exposure_checked_source_and_training_lineage_not_proven",
        "execution_permission": "not_granted_by_preparation", "model_calls": 0, "network_calls": 0,
        "limitations": ["Three to five existing tasks do not establish a broad model ranking.",
            "Training partition names tasks available for future development; no training or scorer-induced gain occurred.",
            "No hardware isolation, current live catalogue or hidden-source independence is asserted.",
            "Initial Patch task results do not qualify Repair, frontend requirement understanding, Apply or Runtime."]}
    root = Path(output_root).resolve()
    _require(not root.exists(), "EXPERIMENT_OUTPUT_ALREADY_EXISTS")
    root.mkdir(parents=True)
    frozen_ref = save_once(root / "experiment.json", prepared)
    return {"status": "prepared_not_executed", "experiment_ref": frozen_ref,
        "distinct_task_denominator": len(tasks), "planned_trial_denominator": len(cells),
        "observed_trials": 0, "model_calls": 0, "network_calls": 0, "models_qualified": False}


def select_patch_experiment_cell(*, experiment_ref, cell_id):
    frozen = read_bound_json(experiment_ref)
    _require(frozen.get("schema_version") == EXPERIMENT_SCHEMA, "EXPERIMENT_SCHEMA_INVALID")
    _require(worker_implementation_identity() == frozen["worker_execution_identity"], "EXPERIMENT_WORKER_IMPLEMENTATION_DRIFT")
    _require(_preparation_identity() == frozen["preparation_implementation_refs"], "EXPERIMENT_PREPARATION_IMPLEMENTATION_DRIFT")
    suite = _checked_suite(frozen["suite_ref"])
    split_by_case = _partitions(suite, frozen["partitions"])
    profiles = _profiles(suite, [{key: row[key] for key in ("profile_id", "profile", "model_identity_ref")}
                               for row in frozen["profiles"]])
    _require(profiles == frozen["profiles"], "EXPERIMENT_PROFILE_IDENTITY_DRIFT")
    tasks = []
    for case in suite["cases"]:
        snapshot = _case_snapshot(frozen["suite_ref"], case, profiles[0]["profile"])
        tasks.append({**snapshot, "split": split_by_case[case["case_id"]], "shared_input_sha256": canonical_hash(snapshot)})
    _require(tasks == frozen["tasks"], "EXPERIMENT_TASK_INPUT_OR_DENOMINATOR_DRIFT")
    _require(_cells(frozen["suite_ref"], frozen["experiment_id"], tasks, profiles) == frozen["cells"],
             "EXPERIMENT_PAIRED_MATRIX_DRIFT")
    _require(frozen["distinct_task_denominator"] == len(tasks)
             and frozen["planned_trial_denominator"] == len(tasks)*len(profiles)
             and frozen["split_task_denominators"] == dict(Counter(task["split"] for task in tasks)),
             "EXPERIMENT_PAIRED_DENOMINATOR_DRIFT")
    selected = [row for row in frozen["cells"] if row["cell_id"] == cell_id]
    _require(len(selected) == 1, "EXPERIMENT_CELL_NOT_FOUND")
    cell = selected[0]
    profile = next(row["profile"] for row in profiles if row["profile_id"] == cell["profile_id"])
    case = next(row for row in suite["cases"] if row["case_id"] == cell["case_id"])
    snapshot = _case_snapshot(frozen["suite_ref"], case, profile)
    _require(canonical_hash(snapshot) == cell["shared_input_sha256"], "EXPERIMENT_TASK_INPUT_OR_DENOMINATOR_DRIFT")
    arguments = task_cli_arguments(suite_ref=frozen["suite_ref"], case_id=cell["case_id"],
        attempt_id=cell["attempt_id"], execution_profile=profile)
    _require(arguments == cell["arguments"], "EXPERIMENT_PUBLIC_ARGUMENTS_DRIFT")
    return {"status": "prepared_cell_admitted", "experiment_ref": dict(experiment_ref), "cell_id": cell_id,
        "case_id": cell["case_id"], "split": cell["split"], "model_digest": cell["model_digest"],
        "command": "python -m src.mod_agent.cli", "arguments": arguments,
        "live_model_identity_verified": False, "model_calls": 0, "network_calls": 0,
        "training_performed": False, "model_qualified": False}
