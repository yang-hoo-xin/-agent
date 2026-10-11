"""Thin, zero-model calibration over Arm A retrieval and the existing Patch loop.

Both entry labels are controlled-response wiring, NOT a full-Agent experiment.
The final judge consumes immutable bytes outside the writable attempt directory.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolCall,
    AgentTurnResponse,
    AgentUsage,
)
from src.mod_agent.evaluation.agent_quality import AgentQualityCase, RunManifest
from src.mod_agent.evaluation.arm_a import RgLiveReadProvider, RunManifestCollector
from src.mod_agent.evaluation.independent_calibration_judge import judge
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_SOURCE_INSPECTION_TOOL_NAME,
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    run_patch_agent_loop,
)

ROOT = Path(__file__).resolve().parents[3]
ARMS = ("simple_rg", "shared_patch_worker")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def file_ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return file_ref(path)


def public_inventory(*, protocol_path, metadata_path):
    """Read exactly the two publicly permitted files; never follow sealed refs."""
    protocol_path, metadata_path = Path(protocol_path), Path(metadata_path)
    if protocol_path.name != "protocol.json" or metadata_path.name != "metadata.json":
        raise ValueError("Only protocol.json and metadata.json are allowed")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (protocol["public_files"] != ["protocol.json", "metadata.json"]
            or protocol["baseline_commit"] != metadata["baseline_commit"]
            or protocol["sealed_inventory_sha256"] != metadata["sealed_inventory_sha256"]
            or set(protocol["task_ids"]) != {t["task_id"] for t in metadata["tasks"]}
            or len(protocol["task_ids"]) != len(set(protocol["task_ids"]))
            or len(metadata["tasks"]) != len(protocol["task_ids"])):
        raise ValueError("Public protocol and metadata disagree")
    return {"verified_count": len(metadata["tasks"]), "basis": "public_metadata_only",
        "protocol_ref": file_ref(protocol_path), "metadata_ref": file_ref(metadata_path),
        "baseline_commit": protocol["baseline_commit"], "status": "prepared_not_authorized_for_execution",
        "tasks": [{"task_id": t["task_id"], "root_cause_family": t["family_id"],
                   "split": "final", "model_result": t["model_result"],
                   "historical_preparation_declaration": {k: t[k] for k in
                       ("baseline_compilation_available", "faulty_variant_rejected", "reference_variant_accepted",
                        "baseline_preservation_checks_pass", "original_platform_input_admitted")},
                   "input_sha256": t["baseline_source_sha256"], "requirements_sha256": t["requirements_sha256"],
                   "verifier_source_sha256": t["verifier_source_sha256"],
                   "current_execution_status": "not_verified"} for t in metadata["tasks"]],
        "available_modes": protocol["available_modes"], "selected_primary_mode": "initial_patch",
        "prepared_worker_limits": protocol["prepared_worker_limits"], "model": protocol["model"],
        "entry_reuse": protocol["entry_reuse"], "exposure_policy": protocol["exposure_policy"],
        "toolchain_metadata_sha256": metadata["toolchain_metadata_sha256"],
        "partition_rule": "All three sealed families reserved for final; public calibration alone serves development/validation",
        "execution_gap": ["No answer-free source publication or verifier endpoint in public metadata",
                          "Exact compiler/runtime dependency versions remain sealed; only hash is public",
                          "Current code/profile admission and complete Graph versus simple strategy adapter unverified"],
        "model_calls": 0, "sealed_files_opened": 0}


def validate_config(config):
    if (config["schema_version"] != "independent_public_calibration_v1"
            or config["scope"] != "engineering_calibration_only"
            or config["model"] != "controlled-responses-no-model"):
        raise ValueError("Only public controlled calibration is executable here")
    ids, families = set(), {}
    for task in config["tasks"]:
        task_id, split = task["task_id"], task["split"]
        if not re.fullmatch(r"[a-z0-9_-]+", task_id) or task_id in ids:
            raise ValueError("Duplicate or unsafe task identity")
        ids.add(task_id)
        if split not in {"development", "validation", "final"}:
            raise ValueError("Unknown split")
        if task["exposure"] != "public_engineering_calibration":
            raise ValueError("This runner cannot admit sealed tasks")
        family = task["root_cause_family"]
        if family in families and families[family] != split:
            raise ValueError("Root-cause family crosses partitions")
        families[family] = split
        if task["required_action"] not in {"submit", "stop"}:
            raise ValueError("Invalid public acceptance action")
        for name, source in task["files"].items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*\.py", name) or not isinstance(source, str):
                raise ValueError("Calibration inputs must be flat Python source files")
        checks = task["checks"]
        if len({c["check_id"] for c in checks}) != len(checks):
            raise ValueError("Duplicate check identity")
        for check in checks:
            if check["file"] not in task["files"] or check["kind"] not in {"target", "preservation"}:
                raise ValueError("Invalid check binding")
    if not ids:
        raise ValueError("Empty task inventory")
    budget = config["budget"]
    PatchAgentLoopPolicy(**{k: budget[k] for k in
        ("max_total_model_turns", "max_tool_rounds", "max_observation_bytes")})
    if not 0 < budget["timeout_seconds"] <= 60 or not 0 < budget["max_response_bytes"] <= 65536:
        raise ValueError("Invalid calibration time/response budget")


def environment_identity():
    files = [Path(__file__), ROOT / "src/mod_agent/evaluation/independent_calibration_judge.py",
             ROOT / "src/mod_agent/evaluation/independent_product_adapter.py",
             ROOT / "src/mod_agent/evaluation/arm_a.py", ROOT / "src/mod_agent/evaluation/agent_quality.py",
             ROOT / "src/mod_agent/proposal/patch_agent_loop.py", ROOT / "src/libs/llm/agent_turn.py",
             ROOT / "scripts/run_independent_calibration.py", ROOT / "pyproject.toml"]
    return {"python": sys.version, "python_executable": file_ref(sys.executable),
            "os": platform.platform(), "implementation_refs": [file_ref(p) for p in files],
            "dependencies": sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
                                   if d.metadata["Name"])}


def _submission_format():
    return AgentResponseFormat(name="public_calibration_submission", description="Public source or honest stop",
        schema={"type": "object", "additionalProperties": False, "required": ["action", "files"],
                "properties": {"action": {"enum": ["submit", "no_change", "stop"]},
                               "files": {"type": "object", "additionalProperties": {"type": "string"}}}})


def worker(*, workspace, task, budget, arm, submission, policy_settings=None, controlled_model=None):
    """No arbitrary client/provider loading; controlled responses only."""
    if arm not in ARMS:
        raise ValueError("Unknown arm")
    workspace = Path(workspace).resolve(strict=True)
    corpus = RunManifestCollector(workspace).canonical_corpus_snapshot(["."])
    # AgentQualityCase is a retrieval contract. No judgment labels enter model messages.
    case = AgentQualityCase(task["task_id"], "public_calibration", task["request"], (), (), (), (),
                            "sufficient", "continue", False, None, expected_result_mode="no_relevant")
    provider = RgLiveReadProvider(workspace, search_patterns={case.case_id: task["search_patterns"]},
                                corpus_snapshot=corpus)
    retrieval = provider(case, len(corpus.files))
    policy = PatchAgentLoopPolicy(**policy_settings) if policy_settings else PatchAgentLoopPolicy(max_total_model_turns=budget["max_total_model_turns"],
        max_tool_rounds=budget["max_tool_rounds"], max_observation_bytes=budget["max_observation_bytes"],
        finalize_after_first_observation=False)
    # Every source file is equally available. No correct file, Hook or span is selected.
    bindings = [{"binding_id": f"source_{index}", "canonical_target_path": item.relative_path,
                 "source_hash": item.file_sha256.removeprefix("sha256:"),
                 "target_span": {"start_line": 1,
                                 "end_line": len((workspace / item.relative_path).read_text().splitlines())}}
                for index, item in enumerate(corpus.files)]
    plan = {"binding_registry": {"schema_version": "binding_registry_v1", "edit_bindings": bindings,
                                  "supporting_bindings": []},
            "proposed_changes": [{"change_id": b["binding_id"], "edit_binding_id": b["binding_id"]}
                                 for b in bindings]}
    inspector = PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan, policy=policy)

    class ControlledClient:
        provider, model = "controlled_calibration", controlled_model or "controlled-responses-no-model"

        def __init__(self):
            self.turns = 0

        def complete_turn(self, request):
            self.turns += 1
            if self.turns == 1:
                calls = (AgentToolCall(call_id="public-read", name=PATCH_SOURCE_INSPECTION_TOOL_NAME,
                                      arguments={"binding_id": bindings[0]["binding_id"]}),)
                return AgentTurnResponse(provider=self.provider, model=self.model, content=None,
                    tool_calls=calls, stop_reason="tool_calls", request_id="controlled-read", usage=AgentUsage())
            content = json.dumps(submission)
            if len(content.encode()) > budget["max_response_bytes"]:
                raise ValueError("Controlled response exceeds frozen output budget")
            return AgentTurnResponse(provider=self.provider, model=self.model, content=content,
                tool_calls=(), stop_reason="stop", request_id="controlled-submit", usage=AgentUsage())

    # Strategy is the sole changed field. This proves interface comparability, not
    # the complete product Graph. Both have the same client, tools and limits.
    strategy = ("Use the simplest direct change supported by live source."
                if arm == "simple_rg" else "Inspect evidence and plan a bounded change with preservation checks.")
    messages = (AgentMessage(role="system", content=strategy),
        AgentMessage(role="user", content={"request": task["request"],
            "source_inventory": [{"binding_id": b["binding_id"], "path": b["canonical_target_path"]} for b in bindings],
            "public_project_materials": task.get("public_project_materials", {}),
            "retrieval": [asdict(r) for r in retrieval.retrieval.ranked_results]}))
    result = run_patch_agent_loop(client=ControlledClient(), initial_messages=messages,
        final_response_format=_submission_format(), source_inspector=inspector, policy=policy)
    return {"loop": result.to_dict(), "submission": json.loads(result.final_content) if result.completed else None,
            "rg_identity": provider.executable_identity.to_dict(),
            "rg_traces": [t.to_dict() for t in provider.command_traces],
            "material_access_sha256": digest(messages[1].content),
            "native_model_calls": 0, "native_token_usage": None}


def evaluate_submission(task, submission):
    if not isinstance(submission, dict) or set(submission) != {"action", "files"}:
        return {"outcome": "execution_error", "task_success": None, "reason": "invalid_submission"}
    files, action = submission["files"], submission["action"]
    if (not isinstance(files, dict) or not set(files) <= set(task["files"])
            or any(not isinstance(v, str) for v in files.values())
            or (action in {"stop", "no_change"} and files)):
        return {"outcome": "execution_error", "task_success": None, "reason": "write_scope_violation"}
    submitted = {**task["files"], **files}
    # Merge function definitions solely for this public numeric language. Task
    # checks are still bound to exact files; cross-file substitution cannot pass.
    if action == "stop" or task["required_action"] == "stop":
        result = judge(source="", public_task=task, action=action)
    else:
        results = [judge(source=source, public_task={**task,
            "checks": [c for c in task["checks"] if c["file"] == name]}, action=action)
                   for name, source in submitted.items()]
        unresolved = next((r for r in results if r["task_success"] is None), None)
        failed = next((r for r in results if r["task_success"] is False), None)
        result = dict(unresolved or failed or results[0])
        result["checks"] = [c for r in results for c in r["checks"]]
        result["file_verdicts"] = dict(zip(submitted, results, strict=True))
        if unresolved is None and failed is None:
            result.update(outcome="success", task_success=True)
    return {**result, "submitted_source_sha256": digest(submitted),
            "changed_files": sorted(name for name in files if files[name] != task["files"][name])}


def summarize(rows):
    summary = {}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        first = {}
        for row in selected:
            first.setdefault(row["task_id"], row)
        known = [r for r in first.values() if r["verdict"].get("task_success") is not None]
        successes = sum(r["verdict"].get("task_success") is True for r in first.values())
        summary[arm] = {"distinct_task_count": len(first), "attempt_count": len(selected),
            "repeat_attempt_count": len(selected) - len(first), "first_attempt_successes": successes,
            "resolved_task_count": len(known), "unresolved_task_count": len(first) - len(known),
            "task_success_rate": successes / len(first) if first and len(known) == len(first) else None,
            "resolved_task_success_rate": successes / len(known) if known else None,
            "outcomes": dict(Counter(r["verdict"]["outcome"] for r in selected))}
    return summary


def run_calibration(*, config_path, output_root, repetitions=1):
    config_path, output_root = Path(config_path).resolve(strict=True), Path(output_root).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_config(config)
    if type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise ValueError("Calibration repetitions must be 1..3")
    output_root.mkdir(parents=True, exist_ok=False)
    environment = environment_identity()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    diff = subprocess.run(["git", "diff", "HEAD", "--binary"], cwd=ROOT, capture_output=True, check=True).stdout
    manifest = RunManifest(head, hashlib.sha256(diff).hexdigest(), digest([t["files"] for t in config["tasks"]]),
        digest(config), "controlled_calibration", "1", "fresh")
    frozen = {"manifest": manifest.to_dict(), "config_ref": file_ref(config_path), "config": config,
              "environment": environment, "scope": "engineering_calibration_only", "model_task_success_rate": None,
              "full_product_graph_comparison": "not_connected", "cleanup": "only each attempt scratch directory; source/results retained"}
    write_once(output_root / "preparation.json", frozen)
    rows = []
    for task in config["tasks"]:
        for arm in ARMS:
            for attempt in range(1, repetitions + 1):
                cell = output_root / task["task_id"] / arm / str(attempt)
                workspace = cell / "source"
                workspace.mkdir(parents=True)
                for name, source in task["files"].items():
                    (workspace / name).write_text(source, encoding="utf-8")
                scratch = cell / "scratch"
                scratch.mkdir()
                # Only public task input is sent to the strategy process, no check
                # labels, required action, split, sealed manifest or judge identity.
                request = {"workspace": str(workspace), "task": {k: task[k] for k in
                    ("task_id", "request", "search_patterns")}, "budget": config["budget"],
                    "arm": arm, "submission": task["controlled_submission"]}
                request_ref = write_once(cell / "controlled-input.json", request)
                env = {key: value for key, value in os.environ.items() if key in
                       {"SYSTEMROOT", "SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC"}}
                env.update(TEMP=str(scratch), TMP=str(scratch), HOME=str(scratch),
                           PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTHONUTF8="1")
                started = time.monotonic()
                receipt, execution = None, "completed"
                try:
                    run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/run_independent_calibration.py"),
                        "--worker-input", request_ref["path"]], cwd=workspace, env=env, capture_output=True,
                        text=True, encoding="utf-8", timeout=config["budget"]["timeout_seconds"], check=False)
                    write_once(cell / "process.json", {"exit_code": run.returncode, "stdout": run.stdout, "stderr": run.stderr})
                    if run.returncode:
                        verdict = {"outcome": "execution_error", "task_success": None, "reason": "worker_process_failed"}
                        execution = "failed"
                    else:
                        receipt = json.loads(run.stdout)
                        verdict = (evaluate_submission(task, receipt["submission"]) if receipt["submission"] is not None else
                                   {"outcome": "budget_exhausted", "task_success": False, "reason": receipt["loop"]["termination"]})
                except subprocess.TimeoutExpired:
                    execution = "timeout"
                    verdict = {"outcome": "execution_timeout", "task_success": None}
                except (OSError, ValueError) as exc:
                    execution = "failed"
                    verdict = {"outcome": "execution_error", "task_success": None, "reason": str(exc)}
                elapsed = time.monotonic() - started
                # The worker only reads source. Submitted text is judged as data.
                actual = {p.name: p.read_text(encoding="utf-8") for p in workspace.iterdir() if p.is_file()}
                intact = actual == task["files"] and environment_identity() == environment
                if not intact:
                    verdict = {"outcome": "execution_error", "task_success": None, "reason": "input_or_judge_drift"}
                row = {"task_id": task["task_id"], "root_cause_family": task["root_cause_family"],
                       "split": task["split"], "exposure": task["exposure"], "arm": arm,
                       "attempt": attempt, "budget": config["budget"], "input_sha256": digest(task["files"]),
                       "execution": execution, "duration_seconds": elapsed, "verdict": verdict,
                       "receipt": receipt, "human_technical_interventions": 0,
                       "requirement_clarifications": 0, "approvals": 0,
                       "source_and_judge_intact": intact, "native_model_calls": 0}
                # No recursive deletion: remove only the empty scratch we created.
                try:
                    scratch.rmdir()
                    row["scratch_cleanup"] = "removed_empty_directory"
                except OSError:
                    row["scratch_cleanup"] = "retained_nonempty_for_inspection"
                write_once(cell / "result.json", row)
                rows.append(row)
    comparisons = []
    for task in config["tasks"]:
        for attempt in range(1, repetitions + 1):
            pair = [r for r in rows if r["task_id"] == task["task_id"] and r["attempt"] == attempt]
            comparable = (all(r["receipt"] is not None for r in pair)
                and len({r["input_sha256"] for r in pair}) == 1
                and len({digest(r["budget"]) for r in pair}) == 1
                and len({r["receipt"]["material_access_sha256"] for r in pair}) == 1
                and len({digest(r["receipt"]["rg_identity"]) for r in pair}) == 1)
            comparisons.append({"task_id": task["task_id"], "attempt": attempt,
                                "same_input_tools_material_budget": comparable})
    report = {"scope": "engineering_calibration_only", "independent_unseen_task_count": 0,
              "model_task_success_rate": None, "full_product_graph_comparison": "not_connected",
              "sealed_inventory": config["sealed_inventory"], "summary": summarize(rows), "results": rows,
              "paired_comparisons": comparisons,
              "only_strategy_difference": "system strategy text; same controlled provider and shared Patch loop",
              "native_model_calls": 0, "environment_ref": file_ref(output_root / "preparation.json")}
    write_once(output_root / "results.json", report)
    return report
