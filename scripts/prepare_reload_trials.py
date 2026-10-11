"""Prepare/freeze/run the predeclared Reload comparison through normal DSH and frozen Product owners."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from src.mod_agent.domain.full_project_compilation import _source_snapshot
from src.mod_agent.model_qualification import read_bound_json
from src.mod_agent.platform_execution_snapshot import prepare_snapshot


def ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
    return ref(path)


def same_source_snapshot(left, right):
    return sorted(left, key=lambda row: row["path"]) == sorted(right, key=lambda row: row["path"])


def prepare_trials(*, output_root, protocol_path, task_path, probe_path, api_config_path, worker_template_path):
    root = Path(output_root).resolve()
    protocol, task, worker = [json.loads(Path(path).read_text(encoding="utf-8")) for path in (protocol_path, task_path, worker_template_path)]
    batch = protocol["mod_batch"]
    if (batch["order"] != ["baseline-1", "combination-1", "combination-2", "baseline-2"]
            or task["cases_ref"] != batch["same_oracle_ref"] or task["source_snapshot"] != batch["same_initial_source"]):
        raise ValueError("RELOAD_COMPARISON_INPUT_MISMATCH")
    read_bound_json(task["cases_ref"])
    read_bound_json(task["prior_delivery_ref"])
    source = Path(task["source_root"])
    if not same_source_snapshot(_source_snapshot(source), task["source_snapshot"]):
        raise ValueError("RELOAD_INITIAL_SOURCE_CHANGED")
    root.mkdir(parents=True, exist_ok=False)
    copied = root / "input" / "StartupNotice"
    copied.mkdir(parents=True)
    for row in task["source_snapshot"]:
        target = copied / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / row["path"]).read_bytes())
    if not same_source_snapshot(_source_snapshot(copied), task["source_snapshot"]):
        raise ValueError("RELOAD_COPIED_SOURCE_CHANGED")
    (root / "request.txt").write_text(task["request"], encoding="utf-8")
    dependencies = worker["behavior_evaluator"]["kwargs"]["compilation_kwargs"]["dependency_binding"]
    dependency_ref = save(root / "dependency.json", dependencies)
    settings = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))
    settings["task_memory"] = {"enabled": False, "store_root": None, "max_context_chars": 3000}
    settings["llm"].update(provider="ollama", model="qwen3-coder:30b", base_url="http://127.0.0.1:11434",
                            max_tokens=batch["coder_max_output"])
    with (root / "settings.yaml").open("x", encoding="utf-8") as stream:
        yaml.safe_dump(settings, stream, allow_unicode=True, sort_keys=False)
    trials = []
    for name, short in zip(batch["order"], ("b1", "c1", "c2", "b2")):
        base = root / short
        base.mkdir()
        trials.append({"trial_id": name, "arm": "baseline" if name.startswith("baseline") else "combination",
                       "root": str(base), "workspace_root": str(base / "w"), "product_snapshot_root": str(base / "p")})
    return save(root / "prepared.json", {"status": "prepared_awaiting_final_source_and_knowledge_bindings", "root": str(root),
        "protocol_ref": ref(protocol_path), "task_ref": ref(task_path), "probe_ref": ref(probe_path),
        "api_config_ref": ref(api_config_path), "worker_template_ref": ref(worker_template_path),
        "dependency_ref": dependency_ref, "settings_ref": ref(root / "settings.yaml"),
        "source_root": str(copied), "request_ref": ref(root / "request.txt"), "trials": trials,
        "model_calls": 0, "builds": 0, "applies": 0})


def finalize_trials(*, prepared_ref, platform_root, knowledge_configs):
    from src.mod_agent.knowledge_evidence_config import KnowledgeEvidenceConfiguration
    prepared = read_bound_json(prepared_ref)
    root, platform = Path(prepared["root"]), Path(platform_root).resolve(strict=True)
    from src.mod_agent.platform_execution_snapshot import FrozenExecution
    FrozenExecution(ref(platform / "execution_snapshot.json")).verify_files()
    task, protocol = read_bound_json(prepared["task_ref"]), read_bound_json(prepared["protocol_ref"])
    worker_template = read_bound_json(prepared["worker_template_ref"])
    for arm in ("baseline", "combination"):
        config = KnowledgeEvidenceConfiguration.load(knowledge_configs[arm])
        if Path(config.value["server_root"]).resolve() != platform:
            raise ValueError("RELOAD_KNOWLEDGE_SERVER_SOURCE_MISMATCH")
        if config.value["max_queries"] != protocol["mod_batch"]["document_query_budget_separate"]:
            raise ValueError("RELOAD_DOCUMENT_QUERY_BUDGET_CHANGED")
    rows = []
    for trial in prepared["trials"]:
        base = Path(trial["root"])
        worker = deepcopy(worker_template)
        selected = worker["behavior_evaluator"]
        selected["factory_name"] = "make_startup_notice_reload_evaluator"
        selected["factory_ref"] = ref(platform / "src/mod_agent/domain/startup_notice_reload_evaluator.py")
        selected["kwargs"].pop("suppress_blank_messages", None)
        selected["kwargs"].update(probe_configuration_ref=prepared["probe_ref"], case_configuration_ref=task["cases_ref"])
        compilation = selected["kwargs"]["compilation_kwargs"]
        compilation.update(project_relative_path="Mod.csproj",
            expected_artifact=Path(task["delivered_baseline_dll"]["path"]).relative_to(Path(task["source_root"])).as_posix(),
            source_root="allocated-by-existing-bridge", workspace_root="allocated-by-existing-bridge",
            artifact_store_root="allocated-by-existing-bridge", output_root="allocated-by-existing-bridge")
        worker["policy"]["max_total_model_turns"] = protocol["mod_batch"]["product_generation_call_budget_per_trial"]
        worker_ref = save(base / "worker.json", worker)
        arguments = ["--target-project", prepared["source_root"], "--workspace-root", trial["workspace_root"],
            "--settings", prepared["settings_ref"]["path"], "--game-folder-build-binding", prepared["dependency_ref"]["path"],
            "--local-ollama", "--ollama-model", "qwen3-coder:30b", "--ollama-base-url", "http://127.0.0.1:11434",
            "--ollama-context-window", str(protocol["mod_batch"]["coder_context"]),
            "--ollama-max-output-tokens", str(protocol["mod_batch"]["coder_max_output"]),
            "--ollama-timeout-seconds", str(protocol["mod_batch"]["coder_timeout_seconds"]),
            "--task-model-call-limit", str(protocol["mod_batch"]["product_generation_call_budget_per_trial"]),
            "--model-call-budget-policy", "task_total_only", "--patch-worker-config", worker_ref["path"],
            "--source-retrieval", "rg_live", "--dependency-api-config", prepared["api_config_ref"]["path"],
            "--knowledge-evidence-config", str(Path(knowledge_configs[trial["arm"]]).resolve()),
            "--confirm-isolated-write", "--allow-build", "--defer-approval"]
        bindings = [{"path": ["behavior_evaluator", "kwargs", "compilation_kwargs", name], "relative_path": relative}
            for name, relative in (("source_root", "generated_mods/StartupNotice"), ("workspace_root", "."),
                                   ("artifact_store_root", "a"), ("output_root", "c"))]
        bindings.append({"path": ["behavior_evaluator", "kwargs", "output_root"], "relative_path": "v"})
        profile_ref = save(base / "profile.json", {"arguments": arguments, "worker_path_bindings": bindings})
        rows.append({**trial, "profile_ref": profile_ref, "worker_ref": worker_ref,
                     "knowledge_ref": ref(knowledge_configs[trial["arm"]])})
    return save(root / "ready.json", {**prepared, "status": "ready_not_executed", "prepared_ref": prepared_ref,
        "platform_root": str(platform), "platform_snapshot_ref": ref(platform / "execution_snapshot.json"), "trials": rows})


def prepare_knowledge_configs(*, prepared_ref, platform_root, corpus_path, baseline_settings, combination_settings):
    from src.mod_agent.build.dependencies import _binary_tree_snapshot, _binary_tree_snapshot_sha256
    from src.mod_agent.knowledge_evidence_config import KnowledgeEvidenceConfiguration
    prepared = read_bound_json(prepared_ref)
    corpus_ref = ref(corpus_path)
    corpus = read_bound_json(corpus_ref)
    dependency = read_bound_json(prepared["dependency_ref"])
    tree = _binary_tree_snapshot(Path(dependency["source_root"]))
    if _binary_tree_snapshot_sha256(tree) != dependency["snapshot_sha256"]:
        raise ValueError("RELOAD_KNOWLEDGE_DEPENDENCY_CHANGED")
    dependencies = {}
    for member in corpus["xml_member_lineage"]:
        selected = member["source"]["paired_dll_ref"]
        if ref(selected["path"])["sha256"] != selected["sha256"]:
            raise ValueError("RELOAD_KNOWLEDGE_PAIRED_DLL_CHANGED")
        matched = [row for row in tree if Path(row["path"]).name == Path(selected["path"]).name and row["sha256"] == selected["sha256"]]
        if len(matched) != 1:
            raise ValueError("RELOAD_KNOWLEDGE_PAIRED_DLL_NOT_UNIQUE")
        dependencies[matched[0]["path"]] = {"relative_path": matched[0]["path"], "source_ref": selected}
    sources = [{"source_ref": material, "lineage_ref": corpus_ref} for material in corpus["materials"]
               if Path(material["path"]).suffix.lower() in {".txt", ".cs"}]
    platform = Path(platform_root).resolve(strict=True)
    result = {}
    for arm, path in (("baseline", baseline_settings), ("combination", combination_settings)):
        settings = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        document = {"schema_version": "knowledge_evidence_config_v1", "python_ref": ref(sys.executable),
            "server_root": str(platform), "server_entry_ref": ref(platform / "src/mcp_server/server.py"),
            "server_settings_ref": ref(path), "collection": "startup_reload",
            "processing_fingerprint": settings["query"]["expected_processing_fingerprint"],
            "sources": sources, "dependency_refs": list(dependencies.values()), "top_k": 5, "max_queries": 4,
            "max_llm_calls_per_query": 2, "rewrite": arm == "combination", "rerank": arm == "combination", "timeout_seconds": 600}
        output = Path(prepared["root"]) / ("knowledge-" + arm + ".json")
        save(output, document)
        KnowledgeEvidenceConfiguration.load(output).boundary()
        result[arm] = str(output)
    return result


def frozen_executor(*, trial, prepared, runner=subprocess.run):
    from scripts.dsh_run_request import _configuration_arguments
    original_argv, expected = _configuration_arguments(trial["profile_ref"]["path"])
    profile = read_bound_json(trial["profile_ref"])
    root = Path(trial["root"])
    def execute(argv):
        from src.mod_agent.platform_execution_snapshot import FrozenExecution
        common = FrozenExecution(prepared["platform_snapshot_ref"])
        common.verify_files()
        common.verify_loaded_modules()
        from src.mod_agent.cli import build_parser
        selected = build_parser().parse_args(argv)
        task = read_bound_json(prepared["task_ref"])
        expected_parsed = build_parser().parse_args(["run-request", *original_argv, "--", task["request"]])
        if selected.command != "run-request" or selected.description != task["request"]:
            raise ValueError("RELOAD_DISPATCH_REQUEST_CHANGED")
        ignored = {"run_id", "request_id", "patch_worker_config"}
        if {k: v for k, v in vars(selected).items() if k not in ignored} != {k: v for k, v in vars(expected_parsed).items() if k not in ignored}:
            raise ValueError("RELOAD_DISPATCH_ARGUMENT_CHANGED")
        if (not selected.run_id or re.fullmatch(r"dsh_[0-9a-f]{32}", selected.run_id) is None
                or selected.request_id != "request_" + selected.run_id[4:]):
            raise ValueError("RELOAD_DISPATCH_IDENTITY_INVALID")
        run_root = (Path(trial["workspace_root"]) / selected.run_id).resolve()
        worker = Path(selected.patch_worker_config).resolve(strict=True)
        if worker.parent != (Path(trial["workspace_root"]) / ".dsh-inputs" / selected.run_id).resolve():
            raise ValueError("RELOAD_DISPATCH_WORKER_OUTSIDE_ALLOCATION")
        document = json.loads(worker.read_text(encoding="utf-8"))
        expected_worker = read_bound_json(trial["worker_ref"])
        for binding in profile["worker_path_bindings"]:
            current = expected_worker
            for name in binding["path"][:-1]:
                current = current[name]
            current[binding["path"][-1]] = str((run_root / binding["relative_path"]).resolve())
        if document != expected_worker:
            raise ValueError("RELOAD_DISPATCH_WORKER_CHANGED")
        factory = document["behavior_evaluator"]["factory_ref"]
        inputs = [ref(worker), prepared["settings_ref"], prepared["dependency_ref"], prepared["api_config_ref"], trial["knowledge_ref"]]
        snapshot = prepare_snapshot(source_root=prepared["platform_root"], snapshot_root=trial["product_snapshot_root"],
            business_argv=argv, run_root=run_root, extra_load_refs=[(factory["path"], factory["sha256"])],
            bound_inputs=[(row["path"], row["sha256"]) for row in inputs])
        save(root / "dispatch.json", {"argv": argv, "run_root": str(run_root), "snapshot_ref": snapshot,
            "bound_inputs": inputs, "extra_load_refs": [factory], "allocated_worker_ref": ref(worker)})
        command = [sys.executable, "-I", "-B", str(Path(trial["product_snapshot_root"]) / "scripts/run_frozen_product.py"),
                   "--_child", snapshot["path"], snapshot["sha256"]]
        result = runner(command, capture_output=True, text=True, encoding="utf-8", check=False)
        save(root / "product-process.json", {"command": command, "exit_code": result.returncode,
                                             "stdout": result.stdout, "stderr": result.stderr})
        print(result.stdout, end="")
        return result.returncode
    return execute


def run_trial(*, ready_ref, trial_id):
    from scripts.dsh_request_routing import run_natural_request
    prepared = read_bound_json(ready_ref)
    if Path(__file__).resolve().parents[1] != Path(prepared["platform_root"]).resolve():
        raise ValueError("RELOAD_ROUTING_MUST_RUN_FROM_SELECTED_FROZEN_PLATFORM")
    from src.mod_agent.platform_execution_snapshot import FrozenExecution
    common = FrozenExecution(prepared["platform_snapshot_ref"])
    common.verify_files()
    common.verify_loaded_modules()
    trial = next(row for row in prepared["trials"] if row["trial_id"] == trial_id)
    output = Path(trial["root"]) / "natural-result.json"
    if output.is_file():
        return ref(output)
    for previous in prepared["trials"][:prepared["trials"].index(trial)]:
        if not (Path(previous["root"]) / "natural-result.json").is_file():
            raise ValueError("RELOAD_PREDECLARED_TRIAL_ORDER_REQUIRED")
    for reference in (prepared["platform_snapshot_ref"], trial["profile_ref"], trial["knowledge_ref"], prepared["request_ref"]):
        if ref(reference["path"]) != reference:
            raise ValueError("RELOAD_PREPARED_INPUT_CHANGED")
    from src.mod_agent.local_entry import _read_ollama_model_identity
    expected = read_bound_json(prepared["protocol_ref"])["models"]["qwen3-coder:30b"]
    identity = _read_ollama_model_identity("http://127.0.0.1:11434", "qwen3-coder:30b")
    if identity.get("digest") != expected["digest"]:
        raise ValueError("RELOAD_PREDECLARED_MODEL_CHANGED")
    save(Path(trial["root"]) / "model-admission.json", identity)
    result = run_natural_request(execution_config=trial["profile_ref"]["path"],
        description=Path(prepared["request_ref"]["path"]).read_text(encoding="utf-8"),
        conversation_id="reload-" + trial_id, turn_id="initial",
        product_executor=frozen_executor(trial=trial, prepared=prepared))
    return save(output, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    prepare = sub.add_parser("prepare")
    for name in ("output-root", "protocol-path", "task-path", "probe-path", "api-config-path", "worker-template-path"):
        prepare.add_argument("--" + name, required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--prepared", required=True)
    finalize.add_argument("--platform-root", required=True)
    finalize.add_argument("--baseline-knowledge", required=True)
    finalize.add_argument("--combination-knowledge", required=True)
    run = sub.add_parser("run")
    run.add_argument("--ready", required=True)
    run.add_argument("--trial-id", required=True)
    knowledge = sub.add_parser("knowledge")
    for name in ("prepared", "platform-root", "corpus-path", "baseline-settings", "combination-settings"):
        knowledge.add_argument("--" + name, required=True)
    args = vars(parser.parse_args())
    mode = args.pop("mode")
    if mode == "prepare":
        result = prepare_trials(**args)
    elif mode == "finalize":
        result = finalize_trials(prepared_ref=ref(args["prepared"]), platform_root=args["platform_root"],
            knowledge_configs={"baseline": args["baseline_knowledge"], "combination": args["combination_knowledge"]})
    elif mode == "knowledge":
        result = prepare_knowledge_configs(prepared_ref=ref(args.pop("prepared")), **args)
    else:
        result = run_trial(ready_ref=ref(args["ready"]), trial_id=args["trial_id"])
    print(json.dumps(result))


if __name__ == "__main__":
    main()
