"""Freeze one common ten-task execution revision and prepare the first S2 pair."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import yaml

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_reload_trials import ref, save
from scripts.run_benchmark_arm import codex_argv, source_snapshot
from src.mod_agent.model_qualification import read_bound_json
from src.mod_agent.platform_execution_snapshot import prepare_snapshot


def prepare(protocol_path, bundle_path, worker_template_path, output_root):
    protocol_ref, bundle_ref = ref(protocol_path), ref(bundle_path)
    protocol, bundle = read_bound_json(protocol_ref), read_bound_json(bundle_ref)
    if bundle["task_id"] != protocol["first_task"] or bundle["task_id"] != "S2":
        raise ValueError("BENCHMARK_FIRST_READY_SUBJECT_CHANGED")
    origin = Path(bundle["source_root"])
    if source_snapshot(origin) != {row["path"]: row["sha256"] for row in bundle["source_snapshot"]}:
        raise ValueError("BENCHMARK_INITIAL_SOURCE_CHANGED")
    for reference in [bundle["request_ref"], bundle["public_scope_ref"], bundle["public_checker_manifest_ref"],
                      bundle["public_checker_ref"], bundle["assessor_ref"], bundle["checker_ref"],
                      bundle["case_configuration_ref"], bundle["probe_configuration_ref"], *bundle["materials_refs"]]:
        if ref(reference["path"]) != reference:
            raise ValueError("BENCHMARK_SUBJECT_INPUT_CHANGED")
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    platform = root / "p"
    platform_ref = prepare_snapshot(source_root=repo, snapshot_root=platform, business_argv=["--help"])
    codex = Path(shutil.which("codex")).resolve(strict=True)
    version = subprocess.run([str(codex), "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if version != "codex-cli 0.160.0":
        raise ValueError("BENCHMARK_CODEX_VERSION_CHANGED")
    workspaces = {(task, arm): root / "w" / (task + ("p" if arm == "platform" else "c"))
                  for task in protocol["task_ids"] for arm in ("platform", "codex")}
    for workspace in workspaces.values():
        workspace.mkdir(parents=True)
    (root / "plans").mkdir()
    common = Path(bundle["request_ref"]["path"]).read_text(encoding="utf-8") + "\n\n" + Path(bundle["public_scope_ref"]["path"]).read_text(encoding="utf-8")
    common_ref = save(root / "common-task.json", {"request": common, "request_ref": bundle["request_ref"],
        "public_scope_ref": bundle["public_scope_ref"], "checker_manifest_ref": bundle["public_checker_manifest_ref"]})
    frozen = {"protocol_ref": protocol_ref, "platform_snapshot_ref": platform_ref, "codex_executable_ref": ref(codex),
        "codex_version": version, "task_ids": protocol["task_ids"], "wall_seconds": 600,
        "platform": {"model": "qwen3-coder:30b", "model_digest": protocol["arms"]["platform"]["model_digest"],
            "context_window": 65536, "output_tokens": 4096, "temperature": 0, "product_calls_per_task": 18,
            "initial_route_calls": 1, "source_retrieval": "rg_live", "task_memory": False},
        "codex": {"model": "gpt-5.6-sol", "reasoning_effort": "medium", "ignore_user_config": True,
            "persistent_session": True, "context_override": None, "token_cap": None, "provider_call_cap": None,
            "native_effective_context": "not inferred from bundled catalog; retain native execution evidence or unknown"},
        "clarification_policy": {"maximum_answers": 2, "source": "registered task answers only",
            "model_oracle_answers": False, "platform_route_calls_per_answer": 1,
            "product_budget_reset_on_answer": False, "active_seconds_shared_with_all_turns_and_acceptance": 600,
            "human_wait_seconds": "record separately", "intervention_origin": "record exact evaluator/human response"},
        "later_subject_policy": "Reuse these exact execution bytes/settings; vary only registered subject/source/materials/task oracle. Normal failures remain first results.",
        "scope": "configured-product comparison, not same model/context or causal component ablation"}
    frozen_ref = save(root / "batch-configuration.json", frozen)
    plans = []
    for arm in ("platform", "codex"):
        workspace = workspaces[("S2", arm)]
        source = workspace / "source" / "ExpeditionHud"
        source.parent.mkdir()
        shutil.copytree(origin, source, ignore=shutil.ignore_patterns("bin", "obj", ".git"))
        materials = workspace / "materials"
        shutil.copytree(Path(bundle["materials_root"]), materials)
        shutil.copytree(Path(bundle["public_checker_ref"]["path"]).parent, materials / "checker")
        shutil.copyfile(bundle["public_scope_ref"]["path"], materials / "README.txt")
        checker = [sys._base_executable, "-I", "-S", str(materials / "checker/check.py"), "--source-root", str(source),
                   "--output-root", str(workspace / ".checks/unique-output"), "--max-seconds", "180"]
        prompt = common
        request_path = root / "plans" / (arm + "-request.txt")
        request_path.write_text(common, encoding="utf-8")
        output = root / "results" / ("S2-" + arm)
        input_refs = [protocol_ref, bundle_ref, frozen_ref, platform_ref, common_ref, bundle["checker_ref"]]
        if arm == "codex":
            # 为什么要有它：公开checker使双方都能按相同用例修订；私有宿主输出与其他臂不可作为答案来源。
            invocation = "& " + " ".join("'" + value.replace("'", "''") + "'" for value in checker)
            prompt += ("\n\n工作目录中的 source/ExpeditionHud 是待修工程，materials 是相同版本资料与只读公开验收工具。"
                "你可以按需重复运行下列检查（每次换一个新的输出目录），它与平台自动收到的行为检查使用同一用例和判定。"
                "源码修改仅限公开列出的三个文件；不修改checker/材料/依赖，不读取其他工作区、私有平台或旧答案，不使用网络或启动游戏。"
                "为什么要有它：控制相同任务的修改和数据范围，并让修订依据来自当前源码与可重复检查。\n" + invocation)
            prompt_path = root / "plans/codex-prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            denies = [Path.home() / ".codex", Path.home() / ".aws", Path.home() / ".ssh", repo, platform, root / "results", root / "plans", root / "batch-configuration.json",
                      *[path for key, path in workspaces.items() if key != ("S2", "codex")]]
            command = codex_argv(codex, workspace, output / "last-message.txt", denies)
            input_refs.extend([ref(codex), ref(prompt_path)])
            acceptance = [sys.executable, "-I", "-B", bundle["checker_ref"]["path"], "--platform-root", str(platform),
                "--bundle", bundle_ref["path"], "--bundle-sha256", bundle_ref["sha256"], "--source-root", str(source),
                "--output-root", "{output_root}/host-check", "--max-seconds", "{remaining_seconds}"]
        else:
            settings = yaml.safe_load((platform / "config/settings.yaml").read_text(encoding="utf-8"))
            settings["task_memory"] = {"enabled": False, "store_root": None, "max_context_chars": 3000}
            settings["llm"].update(provider="ollama", model="qwen3-coder:30b", base_url="http://127.0.0.1:11434", max_tokens=4096)
            settings_path = root / "plans/platform-settings.yaml"
            settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8")
            worker = deepcopy(read_bound_json(ref(worker_template_path)))
            factory = ref(platform / "src/mod_agent/domain/hud_size_evaluator.py")
            worker["behavior_evaluator"] = {"factory_name": bundle["factory_name"], "factory_ref": factory, "kwargs": {
                "compilation_kwargs": {"source_root": "allocated-by-existing-bridge", "workspace_root": "allocated-by-existing-bridge",
                    "artifact_store_root": "allocated-by-existing-bridge", "output_root": "allocated-by-existing-bridge",
                    "project_relative_path": "ExpeditionHud.csproj", "expected_artifact": bundle["expected_artifact"],
                    "dependency_binding": read_bound_json(bundle["dependency_binding_ref"]), "nuget_config_ref": ref(source / "nuget.config"), "timeout_seconds": 120},
                "output_root": "allocated-by-existing-bridge", "probe_configuration_ref": bundle["probe_configuration_ref"],
                "case_configuration_ref": bundle["case_configuration_ref"]}}
            worker["policy"]["max_total_model_turns"] = 18
            worker_ref = save(root / "plans/platform-worker.json", worker)
            args = ["--target-project", str(source), "--workspace-root", str(workspace / "runs"), "--settings", str(settings_path),
                "--game-folder-build-binding", bundle["dependency_binding_ref"]["path"], "--local-ollama", "--ollama-model", "qwen3-coder:30b",
                "--ollama-base-url", "http://127.0.0.1:11434", "--ollama-context-window", "65536", "--ollama-max-output-tokens", "4096",
                "--ollama-timeout-seconds", "180", "--task-model-call-limit", "18", "--model-call-budget-policy", "task_total_only",
                "--patch-worker-config", worker_ref["path"], "--source-retrieval", "rg_live", "--confirm-isolated-write", "--allow-build", "--defer-approval"]
            bindings = [{"path": ["behavior_evaluator", "kwargs", "compilation_kwargs", key], "relative_path": value}
                for key, value in (("source_root", "generated_mods/ExpeditionHud"), ("workspace_root", "."), ("artifact_store_root", "a"), ("output_root", "c"))]
            bindings.append({"path": ["behavior_evaluator", "kwargs", "output_root"], "relative_path": "v"})
            profile_ref = save(root / "plans/platform-profile.json", {"arguments": args, "worker_path_bindings": bindings})
            bound = [ref(settings_path), bundle["dependency_binding_ref"], bundle["case_configuration_ref"], bundle["probe_configuration_ref"]]
            ready_ref = save(root / "plans/platform-ready.json", {"task_id": "S2", "platform_snapshot_ref": platform_ref,
                "profile_ref": profile_ref, "worker_ref": worker_ref, "request_ref": ref(request_path), "bundle_ref": bundle_ref,
                "model_digest": frozen["platform"]["model_digest"], "records_root": str(output / "records"),
                "product_snapshot_root": str(output / "product-platform"), "bound_inputs": bound})
            prompt_path = request_path
            command = [sys.executable, "-I", "-B", str(platform / "scripts/benchmark_platform_entry.py"), "--ready", ready_ref["path"]]
            acceptance = [sys.executable, "-I", "-B", str(platform / "scripts/finalize_benchmark_platform.py"), "--ready", ready_ref["path"]]
            input_refs.extend([profile_ref, worker_ref, ready_ref, ref(request_path), *bound])
        plan = {"protocol_ref": protocol_ref, "batch_configuration_ref": frozen_ref, "task_id": "S2", "arm": arm, "attempt": 1,
            "wall_seconds": 600, "workspace": str(workspace), "source_audit_root": str(source), "output_root": str(output),
            "allowed_source_paths": bundle["allowed_edit_paths"], "bundle_ref": bundle_ref, "command": command,
            "prompt_path": str(prompt_path), "public_checker_command": checker, "acceptance_command": acceptance, "input_refs": input_refs}
        plans.append(save(root / "plans" / (arm + "-plan.json"), plan))
    return save(root / "ready.json", {"status": "prepared_not_executed", "protocol_ref": protocol_ref,
        "batch_configuration_ref": frozen_ref, "platform_snapshot_ref": platform_ref, "bundle_ref": bundle_ref, "plans": plans,
        "launch_commands": [[sys.executable, "-I", "-B", str(platform / "scripts/run_benchmark_arm.py"), "--plan", p["path"]] for p in plans],
        "model_calls": 0, "builds": 0, "first_task": "S2", "remaining_tasks": [x for x in protocol["task_ids"] if x != "S2"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("protocol-path", "bundle-path", "worker-template-path", "output-root"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(prepare(**vars(parser.parse_args()))))
