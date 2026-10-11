"""Paired PUBLIC product-entry wiring with an explicitly injected controlled runtime.

This adapter never installs a model transport or a compiler. The caller must
provide a controlled public CLI invocation and an independent read-only judge.
No sealed material or model execution is admitted by this module.
"""
from __future__ import annotations

import difflib
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from src.mod_agent.evaluation.independent_preparation import digest, worker, write_once
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy


def project_owned_judge_result(record, *, context, verification_identity):
    """Project the existing OwnedSftOracle receipt without exposing checks/answers.

    This is a pure consumer. It neither loads an oracle nor opens report/source
    refs. Only the independently hosted judge may construct the existing oracle.
    """
    for name in ("materialized_code_identity", "generated_changes_sha256", "source_snapshot_sha256"):
        if record[name] != context[name]:
            raise ValueError("Owned judge receipt does not bind the submitted code")
    if (record["verification_identity"] != verification_identity
            or record["model_response_sha256"] != context["model_response"]["output_sha256"]):
        raise ValueError("Owned judge or response identity changed")
    status = record["status"]
    if status not in {"passed", "behavior_failed", "infrastructure_failed"}:
        raise ValueError("Unknown existing OwnedSftOracle status")
    counts = record["verification_summary"]
    if (set(counts) != {"checks", "failed_checks", "executions"}
            or any(type(value) is not int or value < 0 for value in counts.values())
            or counts["failed_checks"] > counts["checks"]):
        raise ValueError("Invalid owned judge counts")
    compilation_failed = any(row["check_id"] == "csharp_compilation" for row in record["observations"])
    executed = record["execution_origin"] == "executed"
    success = None
    compilation, behavior, outcome = "not_demonstrated", "not_evaluated", "execution_error"
    if status == "passed":
        if not (executed and counts["checks"] > 0 and counts["executions"] > 0
                and counts["failed_checks"] == 0 and record["preservation_passed"] is True):
            raise ValueError("Success lacks executed preservation evidence")
        compilation, behavior, outcome, success = "passed", "passed", "success", True
    elif status == "behavior_failed" and compilation_failed:
        compilation, outcome, success = "failed", "compilation_failed", False
    elif status == "behavior_failed":
        if not (executed and counts["checks"] > 0 and counts["failed_checks"] > 0):
            raise ValueError("Behavior failure lacks executed checks")
        compilation, behavior, outcome, success = "passed", "failed", "behavior_failed", False
    return {"compilation": compilation, "behavior": behavior, "outcome": outcome,
        "task_success": success, "verification_summary": dict(counts),
        "preservation_passed": record["preservation_passed"],
        "verification_identity": dict(verification_identity),
        "materialized_code_identity": deepcopy(context["materialized_code_identity"]),
        "model_response_sha256": record["model_response_sha256"],
        "report_sha256": record["report_ref"]["sha256"],
        "detail_visibility": "private observations and report path withheld"}


def product_arguments(*, description, target_project, workspace_root, settings_path,
                      model, context_window, output_tokens, timeout_seconds, total_calls,
                      stage_limits_path, worker_config_path):
    from src.mod_agent.cli import build_parser

    arguments = ["run-request", description, "--target-project", str(target_project),
        "--workspace-root", str(workspace_root), "--settings", str(settings_path),
        "--local-ollama", "--ollama-model", model,
        "--ollama-context-window", str(context_window),
        "--ollama-max-output-tokens", str(output_tokens),
        "--ollama-timeout-seconds", str(timeout_seconds),
        "--task-model-call-limit", str(total_calls),
        "--stage-model-call-limits", str(stage_limits_path),
        "--patch-worker-config", str(worker_config_path),
        "--source-retrieval", "rg_live", "--confirm-isolated-write", "--allow-build", "--defer-approval"]
    parsed = build_parser().parse_args(arguments)
    assert parsed.planning_target_evidence_id == [] and parsed.defer_approval
    return arguments


def run_public_product_pair(*, task_id, description, initial_files, search_patterns,
                            output_root, settings_path, controlled_profile,
                            simple_submission, invoke_controlled_product, final_judge,
                            final_judge_identity):
    """Invoke the real product CLI through a controlled runtime, plus simple rg.

    `invoke_controlled_product(arguments)` returns (exit_code, original JSON).
    `final_judge` receives immutable strings only, with identical field shapes.
    General live transports are deliberately not supplied or constructed here.
    """
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    if not initial_files or not 1 <= controlled_profile["total_calls"] <= 5:
        raise ValueError("Public pair requires source and a common 1..5 call limit")
    source_hash = digest(initial_files)
    for arm in ("simple_rg", "full_product_graph"):
        source = root / arm / "source"
        source.mkdir(parents=True)
        for name, text in initial_files.items():
            path = source / name
            if not path.resolve().is_relative_to(source) or path.is_symlink():
                raise ValueError("Source file is outside public project")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    shared = {"task_id": task_id, "description": description, "input_sha256": source_hash,
              "profile": controlled_profile, "source_access": "all supplied public project files",
              "permissions": "read supplied project; propose only; stop before approval/apply/build",
              "strategy_difference": "direct rg plus shared Patch loop versus original requirement/Evidence/Planning/Graph route",
              "scope": "controlled_public_entry_engineering_only", "model_task_success_rate": None,
              "final_judge_identity": dict(final_judge_identity)}
    write_once(root / "pair-input.json", shared)
    write_once(root / "stage-limits.json", {role: controlled_profile["total_calls"] for role in
        ("requirement_projection", "requirement_findings", "planning", "initial_patch", "repair")})
    policy = asdict(PatchAgentLoopPolicy(max_total_model_turns=controlled_profile["total_calls"],
        max_tool_rounds=6, max_observation_bytes=32768, require_source_inspection=False,
        finalize_after_first_observation=False, enable_supporting_reads=True,
        allow_upstream_request=True, allow_batched_reads=True))
    write_once(root / "worker.json", {"schema_version": "patch_worker_configuration_v1", "policy": policy,
        "enable_recovery_loop": False, "behavior_evaluator": None})
    arguments = product_arguments(description=description, target_project=root / "full_product_graph/source",
        workspace_root=root / "full_product_graph/runs", settings_path=settings_path,
        model=controlled_profile["model"], context_window=controlled_profile["context_window"],
        output_tokens=controlled_profile["output_tokens"], timeout_seconds=controlled_profile["timeout_seconds"],
        total_calls=controlled_profile["total_calls"], stage_limits_path=root / "stage-limits.json",
        worker_config_path=root / "worker.json")
    code, product = invoke_controlled_product(arguments)
    write_once(root / "full_product_graph/product-result.json", product)
    budget = {"max_total_model_turns": controlled_profile["total_calls"], "max_tool_rounds": 6,
              "max_observation_bytes": 32768, "max_response_bytes": 16384}
    simple = worker(workspace=root / "simple_rg/source", task={"task_id": task_id, "request": description,
        "search_patterns": search_patterns, "public_project_materials": initial_files},
        budget=budget, arm="simple_rg", submission=simple_submission, policy_settings=policy,
        controlled_model=controlled_profile["model"])
    write_once(root / "simple_rg/worker-result.json", simple)
    submission = simple["submission"]
    simple_diff = ""
    if submission is not None:
        if not set(submission["files"]) <= set(initial_files):
            raise ValueError("Simple response attempted an unauthorized path")
        for name, after in submission["files"].items():
            simple_diff += "".join(difflib.unified_diff(initial_files[name].splitlines(keepends=True),
                after.splitlines(keepends=True), fromfile="a/" + name, tofile="b/" + name))
    rows = []
    for arm, diff, calls in (("simple_rg", simple_diff, simple["loop"]["model_turns_used"]),
                             ("full_product_graph", product.get("unified_diff", ""), product.get("model_call_count"))):
        before = {str(p.relative_to(root / arm / "source")).replace("\\", "/"): p.read_text(encoding="utf-8")
                  for p in (root / arm / "source").rglob("*") if p.is_file()}
        if before != initial_files:
            raise ValueError("Canonical public project changed")
        judgment_input = {"task_id": task_id, "description": description,
                          "initial_files": deepcopy(initial_files), "unified_diff": str(diff)}
        if arm == "full_product_graph" and (code != 0 or product.get("graph_invoked") is not True
                or product.get("status") != "awaiting_approval"):
            verdict = {"outcome": "execution_error", "task_success": None,
                       "reason": "product_entry_did_not_reach_deferred_review"}
        elif arm == "simple_rg" and submission is None:
            verdict = {"outcome": "budget_exhausted", "task_success": False}
        else:
            verdict = final_judge(deepcopy(judgment_input))
        rows.append({"arm": arm, "input_sha256": source_hash, "final_judge_input_sha256": digest(judgment_input),
                     "controlled_provider_invocations": calls, "native_model_calls": 0, "verdict": verdict,
                     "canonical_source_unchanged": True, "human_technical_interventions": 0,
                     "requirement_clarifications": 0, "approvals": 0})
    result = {**shared, "product_arguments": arguments, "product_exit_code": code,
              "product_graph_invoked": product.get("graph_invoked"), "product_status": product.get("status"),
              "product_budget": product.get("model_call_budget"), "results": rows,
              "verdict_boundary": "Injected public judge; controlled compiler success is not behavioral evidence",
              "simple_loop_budget": budget, "live_comparison_admitted": False}
    write_once(root / "pair-result.json", result)
    return result
