"""Benchmark adapter around normal routing and the frozen Product CLI."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.prepare_reload_trials import ref, save
from src.mod_agent.model_qualification import read_bound_json
from src.mod_agent.platform_execution_snapshot import FrozenExecution, prepare_snapshot


def run(ready_path):
    from scripts.dsh_request_routing import run_natural_request
    from scripts.dsh_run_request import _configuration_arguments
    from src.mod_agent.cli import build_parser
    ready = read_bound_json(ref(ready_path))
    Path(ready["records_root"]).mkdir(parents=True, exist_ok=False)
    frozen = FrozenExecution(ready["platform_snapshot_ref"])
    frozen.verify_files()
    frozen.verify_loaded_modules()
    profile = read_bound_json(ready["profile_ref"])
    original, _ = _configuration_arguments(ready["profile_ref"]["path"])
    request = Path(ready["request_ref"]["path"]).read_text(encoding="utf-8")
    if ref(ready["request_ref"]["path"]) != ready["request_ref"]:
        raise ValueError("BENCHMARK_PLATFORM_REQUEST_CHANGED")
    expected = build_parser().parse_args(["run-request", *original, "--", request])
    from src.mod_agent.local_entry import _read_ollama_model_identity
    def verify_model():
        actual = _read_ollama_model_identity(expected.ollama_base_url, expected.ollama_model)
        if actual.get("digest") != ready["model_digest"]:
            raise ValueError("BENCHMARK_PLATFORM_MODEL_DIGEST_CHANGED")
        return actual
    save(Path(ready["records_root"]) / "model-admission.json", verify_model())

    def execute(argv):
        frozen.verify_files()
        verify_model()
        actual = build_parser().parse_args(argv)
        ignored = {"run_id", "request_id", "patch_worker_config"}
        if {k: v for k, v in vars(actual).items() if k not in ignored} != {
                k: v for k, v in vars(expected).items() if k not in ignored}:
            raise ValueError("BENCHMARK_PLATFORM_DISPATCH_CHANGED")
        root = Path(actual.workspace_root) / actual.run_id
        worker = read_bound_json(ready["worker_ref"])
        for binding in profile["worker_path_bindings"]:
            current = worker
            for key in binding["path"][:-1]:
                current = current[key]
            current[binding["path"][-1]] = str((root / binding["relative_path"]).resolve())
        if json.loads(Path(actual.patch_worker_config).read_bytes()) != worker:
            raise ValueError("BENCHMARK_PLATFORM_WORKER_CHANGED")
        inputs = [ref(actual.patch_worker_config), *ready["bound_inputs"]]
        factory = worker["behavior_evaluator"]["factory_ref"]
        snapshot = prepare_snapshot(source_root=frozen.root, snapshot_root=ready["product_snapshot_root"],
            business_argv=argv, run_root=root, extra_load_refs=[(factory["path"], factory["sha256"])],
            bound_inputs=[(row["path"], row["sha256"]) for row in inputs])
        save(Path(ready["records_root"]) / "dispatch.json", {"argv": argv, "run_root": str(root),
            "snapshot_ref": snapshot, "bound_inputs": inputs, "extra_load_refs": [factory],
            "allocated_worker_ref": ref(actual.patch_worker_config)})
        command = [sys.executable, "-I", "-B", str(Path(ready["product_snapshot_root"]) / "scripts/run_frozen_product.py"),
                   "--_child", snapshot["path"], snapshot["sha256"]]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
        save(Path(ready["records_root"]) / "product-process.json", {"command": command, "exit_code": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr})
        print(completed.stdout, end="")
        return completed.returncode

    result = run_natural_request(execution_config=ready["profile_ref"]["path"], description=request,
        conversation_id="benchmark-" + ready["task_id"], turn_id="initial", product_executor=execute)
    reference = save(Path(ready["records_root"]) / "natural-result.json", result)
    print(json.dumps(reference))
    return 0 if result.get("status") == "awaiting_approval" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ready", required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.ready))
