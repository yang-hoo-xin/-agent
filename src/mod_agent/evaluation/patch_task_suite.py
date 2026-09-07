"""Freeze and select fixed Patch tasks using the existing qualification contract.

This module prepares inputs and reuses the existing continuation preflight. It
does not qualify models, manufacture trials, approve patches, or run providers.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.domain.accurate_crosshair_eval import (
    API_CASE,
    API_CHECKS,
    CONFIG_CASE,
    CONFIG_CHECKS,
    AccurateCrosshairTaskOracle,
)
from src.mod_agent.evidence.requirement_coverage import (
    default_feature_requirement_projection,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.evidence.requirement_coverage_provider import build_requirement_coverage_pack
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
from src.mod_agent.fresh_planning_continuation import (
    PATCH_CONTINUATION_CONTRACT_VERSION,
    PatchContinuationInputV1,
    preflight_patch_continuation,
)
from src.mod_agent.model_qualification import (
    SUITE_SCHEMA,
    canonical_hash,
    read_bound_json,
    worker_implementation_identity,
)
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.planning.implementation_plan import ImplementationPlanner
from src.mod_agent.planning.models import FeatureSpec, stable_feature_id

TASKS = (
    {"case_id": CONFIG_CASE, "category": "configuration",
     "request": "独立Eval任务：AccurateCrosshair在没有已保存配置时，让General Settings下Follow Recoil默认关闭；已有配置显式true或false仍照常生效，其他五项配置默认值和所有配置键保持不变。",
     "criteria": ("A fresh configuration defaults Follow Recoil to false.",
                  "Existing explicit true and false values retain their meaning.",
                  "All other defaults and the complete original configuration key set are unchanged."),
     "queries": ("BindAll", "FollowsRecoil", "OnFileChanged"), "target_symbol": "BindAll",
     "target_path": "AccurateCrosshair/Configuration.cs", "checks": CONFIG_CHECKS},
    {"case_id": API_CASE, "category": "public_api_behavior",
     "request": "独立Eval任务：AccurateCrosshair的公开SpreadAPI.SetModifier拒绝负数、NaN、正负Infinity，抛出ArgumentOutOfRangeException，并保留之前已登记的modifier及通知次数。零和有限非负值仍有效；乘积、同key替换、移除，以及值未变时不发更新通知的现有语义保持不变。",
     "criteria": ("Negative and non-finite input throws ArgumentOutOfRangeException before changing observable state.",
                  "Rejecting an input preserves the previous modifier and does not notify a size update.",
                  "Finite non-negative values including zero preserve product, replacement, removal and unchanged-value notification behavior."),
     "queries": ("SetModifier", "RemoveModifier", "UpdateModifier"), "target_symbol": "SetModifier",
     "target_path": "AccurateCrosshair/API/SpreadAPI.cs", "checks": API_CHECKS},
)


def reference(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())
    return reference(path)


def _request_from_document(value):
    value = deepcopy(value)
    for key in ("feature_spec_ref", "evidence_pack_ref", "implementation_plan_ref",
                "repair_parent_proposal_ref", "repair_parent_review_ref"):
        if value.get(key) is not None:
            value[key] = ArtifactRef(**value[key])
    return PatchContinuationInputV1(**value)


def _checked_suite(suite_ref):
    suite = read_bound_json(suite_ref)
    if suite.get("schema_version") != SUITE_SCHEMA or not isinstance(suite.get("cases"), list):
        raise ValueError("PATCH_EVAL_SUITE_INVALID")
    cases = suite["cases"]
    if (not 3 <= len(cases) <= 5 or len({case["case_id"] for case in cases}) != len(cases)
            or len({case["feature_spec_ref"]["feature_id"] for case in cases}) != len(cases)
            or len({case["feature_spec_ref"]["artifact_hash"] for case in cases}) != len(cases)):
        raise ValueError("PATCH_EVAL_DISTINCT_TASK_DENOMINATOR_INVALID")
    from src.mod_agent.local_entry import LocalOllamaInitialPatchProfileV1
    profile = suite["execution_profile"]
    parsed = LocalOllamaInitialPatchProfileV1(**{key: profile[key] for key in (
        "profile_version", "base_url", "model", "context_window", "output_budget", "timeout_seconds")})
    if parsed.to_dict() != profile:
        raise ValueError("PATCH_EVAL_PROFILE_INVALID")
    return suite


def select_patch_task(*, suite_ref, case_id, attempt_id):
    suite = _checked_suite(suite_ref)
    matches = [case for case in suite["cases"] if case["case_id"] == case_id]
    if len(matches) != 1:
        raise ValueError("PATCH_EVAL_CASE_NOT_FOUND")
    case = matches[0]
    request = _request_from_document(read_bound_json(case["execution"]["continuation_input_ref"]))
    request = replace(request, attempt_id=attempt_id)
    if request.worker_profile_sha256 != canonical_hash(suite["execution_profile"]):
        raise ValueError("PATCH_EVAL_MODEL_PROFILE_MISMATCH")
    if (asdict(request.feature_spec_ref) != case["feature_spec_ref"]
            or request.artifact_store_root != case["artifact_store_root"]
            or request.workspace_root != case["workspace_root"]):
        raise ValueError("PATCH_EVAL_TASK_INPUT_MISMATCH")
    admitted = preflight_patch_continuation(request)
    if admitted.feature_spec["target_mod"] != suite["scope"]["target_mod"]:
        raise ValueError("PATCH_EVAL_TARGET_SCOPE_MISMATCH")
    role = "repair" if admitted.repair_context is not None else "initial_patch"
    if role != case["execution"]["role"]:
        raise ValueError("PATCH_EVAL_ROLE_MISMATCH")
    config_ref = case["execution"]["worker_configuration_ref"]
    if request.worker_configuration_ref != config_ref:
        raise ValueError("PATCH_EVAL_WORKER_CONFIGURATION_MISMATCH")
    config_document = read_bound_json(config_ref)
    configured_checks = config_document["behavior_evaluator"]["kwargs"].get("expected_check_ids")
    if configured_checks != case["expected_check_ids"]:
        raise ValueError("PATCH_EVAL_CHECK_SET_MISMATCH")
    configuration = PatchWorkerConfiguration.load(config_ref["path"])
    evaluator = configuration.behavior_evaluator()
    if evaluator is None or evaluator.verification_identity() != case["verification_identity"]:
        raise ValueError("PATCH_EVAL_VERIFIER_IDENTITY_MISMATCH")
    return request


def preflight_patch_suite(suite_ref):
    suite = _checked_suite(suite_ref)
    results = []
    for case in suite["cases"]:
        try:
            request = select_patch_task(suite_ref=suite_ref, case_id=case["case_id"],
                attempt_id="eval-preflight-" + case["case_id"])
            status, reason = "admitted", None
            role = "repair" if request.repair_parent_proposal_ref else "initial_patch"
        except (ValueError, OSError) as exc:
            status, reason, role = "blocked", str(exc), case["execution"]["role"]
        results.append({"case_id": case["case_id"], "feature_id": case["feature_spec_ref"]["feature_id"],
            "role": role, "input_preflight": status, "reason": reason,
            "expected_check_count": len(case["expected_check_ids"]), "model_trial": "not_run_by_preflight"})
    return {"suite_ref": suite_ref, "distinct_task_count": len(results), "cases": results,
            "model_calls": 0, "task_success_rate": None, "models_qualified": False,
            "admitted": all(row["input_preflight"] == "admitted" for row in results)}


def task_cli_arguments(*, suite_ref, case_id, attempt_id):
    request = select_patch_task(suite_ref=suite_ref, case_id=case_id, attempt_id=attempt_id)
    suite = _checked_suite(suite_ref)
    profile = suite["execution_profile"]
    arguments = ["continue-fresh-patch", "--artifact-root", request.artifact_store_root,
        "--workspace-root", request.workspace_root, "--feature-id", request.feature_spec_ref.feature_id]
    for name, flag in (("feature_spec_ref", "feature-spec"), ("evidence_pack_ref", "evidence-pack"),
                       ("implementation_plan_ref", "implementation-plan")):
        ref = getattr(request, name)
        arguments.extend(["--" + flag + "-path", ref.path, "--" + flag + "-hash", ref.artifact_hash])
    if request.repair_parent_proposal_ref is not None:
        raise ValueError("PATCH_EVAL_EXPLICIT_REPAIR_SELECTION_NOT_PREPARED")
    arguments.extend(["--patch-worker-config", request.worker_configuration_ref["path"],
        "--ollama-base-url", profile["base_url"],
        "--ollama-model", profile["model"], "--ollama-context-window", str(profile["context_window"]),
        "--ollama-output-budget", str(profile["output_budget"]), "--ollama-timeout-seconds", str(profile["timeout_seconds"]),
        "--attempt-id", attempt_id])
    return arguments


def prepare_source_task(*, definition, source_root, output_root, policy, profile):
    root = Path(output_root).resolve()
    workspace = root / "source"
    shutil.copytree(source_root, workspace)
    store = ArtifactStore(root / "store")
    feature = FeatureSpec(feature_id=stable_feature_id(definition["request"]), user_request=definition["request"],
        target_behavior=definition["request"], target_mod="AccurateCrosshair", risk_level="low",
        acceptance_criteria=definition["criteria"], evidence_requirements=("Current exact source implementing the selected public behavior.",),
        non_goals=("Do not change unrelated behavior, tests or their applicability.",
                   "This independent Eval task does not change the user's production Mod request."),
        runtime_verification_plan=("Run the task-specific local C# behavior matrix; this is not GTFO Runtime.",))
    feature_ref = store.write(feature_id=feature.feature_id, artifact_type="feature_spec", payload=feature.to_artifact_payload())
    projection = default_feature_requirement_projection(feature.to_artifact_payload())
    for row in projection["requirements"]:
        row["query_leads"] = list(definition["queries"])
    materialized = materialize_requirement_coverage_projection(feature_data=feature.to_artifact_payload(),
        request=feature.user_request, projection=projection)
    retrieved = RgLiveEvidenceProvider(workspace).collect_query_set(queries=tuple(materialized["queries"]),
        search_root="AccurateCrosshair", max_items=max(32, len(materialized["queries"])))
    targets = [item.evidence_id for item in retrieved.items
               if item.source_path == definition["target_path"] and item.symbol == definition["target_symbol"]]
    if len(targets) != 1:
        raise ValueError("PATCH_EVAL_EXACT_SOURCE_TARGET_AMBIGUOUS")
    findings = {"findings": []}
    for index, row in enumerate(materialized["requirements"], 1):
        deferred = row["role"] == "post_change_acceptance"
        findings["findings"].append({"relation_index": index, "relationship": "missing" if deferred else "support",
            "evidence_ids": [] if deferred else [item.evidence_id for item in retrieved.items],
            "edit_target_evidence_ids": targets if row["role"] == "change" else [],
            "unresolved_gaps": ["Execute the independent task oracle after model-generated code."] if deferred else []})
    pack = build_requirement_coverage_pack(query=feature.user_request, materialized_projection=materialized,
        retrieved_pack=retrieved, findings=findings)
    evidence = pack.to_artifact_payload()
    evidence["budget_summary"]["eval_input_authorship"] = {"semantic_owner": "explicit_operator_authored_task_fixture",
        "model_calls": 0, "not_fresh_model_execution": True}
    if not pack.can_generate_patch:
        raise ValueError("PATCH_EVAL_SOURCE_COVERAGE_INCOMPLETE: " + repr(pack.blockers))
    evidence_ref = store.write(feature_id=feature.feature_id, artifact_type="evidence_pack", payload=evidence,
        upstream_refs=[feature_ref])
    plan = ImplementationPlanner().build(feature_spec=feature, evidence_pack=evidence,
        formal_requirement_coverage_required=True, planning_target_evidence_ids=tuple(targets))
    if plan.blocking:
        raise ValueError("PATCH_EVAL_PLAN_BLOCKED: " + repr(plan.blockers))
    plan_payload = plan.to_artifact_payload()
    plan_ref = store.write(feature_id=feature.feature_id, artifact_type="implementation_plan", payload=plan_payload,
        upstream_refs=[feature_ref, evidence_ref])
    from src.mod_agent.domain import accurate_crosshair_eval
    config = {"schema_version": "patch_worker_configuration_v1", "policy": asdict(policy), "enable_recovery_loop": True,
        "behavior_evaluator": {"factory_ref": reference(accurate_crosshair_eval.__file__), "factory_name": "make_behavior_evaluator",
            "kwargs": {"case_id": definition["case_id"], "artifact_store_root": str(store.root), "workspace_root": str(workspace),
                       "plan_ref": asdict(plan_ref), "output_root": str(root / "evaluations"),
                       "expected_check_ids": list(definition["checks"])}}}
    config_ref = save_once(root / "worker.json", config)
    oracle = AccurateCrosshairTaskOracle(case_id=definition["case_id"], workspace_root=workspace,
        implementation_plan=plan_payload, output_root=root / "evaluations")
    baseline = oracle.verify_baseline()
    baseline_ref = save_once(root / "baseline-verification.json", baseline)
    request = PatchContinuationInputV1(contract_version=PATCH_CONTINUATION_CONTRACT_VERSION,
        artifact_store_root=str(store.root), workspace_root=str(workspace), feature_spec_ref=feature_ref,
        evidence_pack_ref=evidence_ref, implementation_plan_ref=plan_ref, worker_configuration_ref=config_ref,
        worker_profile_sha256=canonical_hash(profile))
    preflight_patch_continuation(request)
    request_ref = save_once(root / "continuation-input.json", asdict(request))
    save_once(root / "input-authorship.json", {"origin": "new_independent_eval_task_definition",
        "planning_target_selection": "explicit_operator_assisted", "source_root": str(Path(source_root).resolve()),
        "source_hashes": {str(path.relative_to(workspace)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(workspace.rglob("*.cs"))}, "model_calls": 0, "model_trial": "not_run"})
    return {"case_id": definition["case_id"], "category": definition["category"], "artifact_store_root": str(store.root),
        "workspace_root": str(workspace), "feature_spec_ref": asdict(feature_ref), "expected_check_ids": list(definition["checks"]),
        "verification_identity": oracle.verification_identity(), "baseline_verification_ref": baseline_ref,
        "evaluation_layer": "real_source_with_dependency_doubles_not_game_runtime",
        "execution": {"continuation_input_ref": request_ref, "worker_configuration_ref": config_ref, "role": "initial_patch",
                      "task_trial_status_at_freeze": "not_run", "planning_target_selection": "explicit_operator_assisted"}}


def prepare_accurate_crosshair_suite(*, output_root, p0_arguments_path, p0_matrix_ref, p0_identity_refs):
    """Freeze two independent tasks plus the existing P0, with no model execution."""
    from src.mod_agent.cli import build_parser
    from src.mod_agent.domain import accurate_crosshair_eval
    from src.mod_agent.local_entry import (
        LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        LocalOllamaInitialPatchProfileV1,
    )

    arguments = json.loads(Path(p0_arguments_path).read_text(encoding="utf-8"))
    parsed = build_parser().parse_args(arguments)
    if not arguments or arguments[0] != "continue-fresh-patch":
        raise ValueError("PATCH_EVAL_P0_ENTRY_INVALID")
    profile = LocalOllamaInitialPatchProfileV1(profile_version=LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        base_url=parsed.ollama_base_url or "http://127.0.0.1:11434", model=parsed.ollama_model,
        context_window=parsed.ollama_context_window, output_budget=parsed.ollama_output_budget,
        timeout_seconds=parsed.ollama_timeout_seconds).to_dict()
    original_configuration = PatchWorkerConfiguration.load(parsed.patch_worker_config)
    root = Path(output_root).resolve()
    if root.exists():
        raise ValueError("PATCH_EVAL_OUTPUT_ALREADY_EXISTS")
    root.mkdir(parents=True)
    cases = [prepare_source_task(definition=definition, source_root=parsed.workspace_root,
        output_root=root / f"c{index}", policy=original_configuration.policy, profile=profile)
        for index, definition in enumerate(TASKS, 1)]
    p0_root = root / "c3"
    delegate = deepcopy(read_bound_json(original_configuration.reference))
    previous_output = Path(delegate["behavior_evaluator"]["kwargs"]["output_root"])
    delegate["behavior_evaluator"]["kwargs"]["output_root"] = str(previous_output.parent / ("eval-" + canonical_hash(str(root))[:10]))
    delegate_ref = save_once(p0_root / "original-worker.json", delegate)
    matrix = read_bound_json(p0_matrix_ref)
    check_ids = [row["check"] for row in matrix["checks"]]
    if len(check_ids) != 36 or len(set(check_ids)) != 36:
        raise ValueError("PATCH_EVAL_P0_ORIGINAL_MATRIX_REQUIRED")
    config = {"schema_version": "patch_worker_configuration_v1", "policy": asdict(original_configuration.policy),
        "enable_recovery_loop": True, "behavior_evaluator": {
            "factory_ref": reference(accurate_crosshair_eval.__file__), "factory_name": "make_existing_matrix_evaluator",
            "kwargs": {"configuration_ref": delegate_ref, "identity_refs": p0_identity_refs,
                       "expected_check_ids": check_ids, "output_root": str(p0_root / "evaluations")}}}
    config_ref = save_once(p0_root / "worker.json", config)
    refs = {kind: ArtifactRef(feature_id=parsed.feature_id, artifact_type=kind,
        path=getattr(parsed, kind + "_path"), artifact_hash=getattr(parsed, kind + "_hash"))
        for kind in ("feature_spec", "evidence_pack", "implementation_plan")}
    request = PatchContinuationInputV1(contract_version=PATCH_CONTINUATION_CONTRACT_VERSION,
        artifact_store_root=str(Path(parsed.artifact_root).resolve()), workspace_root=str(Path(parsed.workspace_root).resolve()),
        feature_spec_ref=refs["feature_spec"], evidence_pack_ref=refs["evidence_pack"], implementation_plan_ref=refs["implementation_plan"],
        worker_configuration_ref=config_ref, worker_profile_sha256=canonical_hash(profile))
    preflight_patch_continuation(request)
    request_ref = save_once(p0_root / "continuation-input.json", asdict(request))
    oracle = PatchWorkerConfiguration.load(config_ref["path"]).behavior_evaluator()
    cases.append({"case_id": "accurate-crosshair-spread-toggle", "category": "multi_file_preservation",
        "artifact_store_root": request.artifact_store_root, "workspace_root": request.workspace_root,
        "feature_spec_ref": asdict(request.feature_spec_ref), "expected_check_ids": check_ids,
        "verification_identity": oracle.verification_identity(), "prior_failure_observation_ref": p0_matrix_ref,
        "evaluation_layer": "real_source_with_engine_doubles_not_game_runtime",
        "execution": {"continuation_input_ref": request_ref, "worker_configuration_ref": config_ref, "role": "initial_patch",
            "task_trial_status_at_freeze": "not_run", "planning_target_selection": "existing_explicit_operator_assisted_plan",
            "repair_role_is_separate_not_an_extra_task": True}})
    suite = {"schema_version": SUITE_SCHEMA, "scope": {"target_mod": "AccurateCrosshair"}, "cases": cases,
        "execution_profile": profile, "worker_execution_identity_at_freeze": worker_implementation_identity(),
        "model_calls_at_freeze": 0, "distinct_task_count": 3, "models_qualified": False,
        "acceptance_scope": "initial_patch_fixed_source_behavior_then_original_Proposal_Review_Dry_run",
        "qualification_scope_excludes": ["autonomous_planning", "autonomous_evidence", "all_repair_roles", "DSH_service", "GTFO_Runtime"],
        "validation_layers": {"synthetic_contract_tests": "separate_engineering_tests",
            "real_source_dependency_doubles": "per_task_oracles", "real_model_tasks": "not_run",
            "service_and_GTFO_acceptance": "not_run"}}
    suite_ref = save_once(root / "suite.json", suite)
    preflight = preflight_patch_suite(suite_ref)
    save_once(root / "preflight.json", preflight)
    for case in cases:
        save_once(root / (case["case_id"] + ".arguments.json"),
            task_cli_arguments(suite_ref=suite_ref, case_id=case["case_id"], attempt_id="eval-v1-" + case["case_id"]))
    return {"suite_ref": suite_ref, "preflight": preflight}
