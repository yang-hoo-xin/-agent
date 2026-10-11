"""DSH preview/confirmation over the existing Build-to-Runtime owner."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.dsh_deliver_run import _inputs, _read_receipt
from src.mod_agent.local_entry import preflight_local_runtime, resume_local_runtime
from src.mod_agent.patch_worker_configuration import read_json_object


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _running_game(executable):
    if os.name != "nt":
        raise ValueError("DSH_RUNTIME_PROCESS_INSPECTION_REQUIRES_WINDOWS")
    process = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode != 0:
        raise ValueError("DSH_RUNTIME_PROCESS_INSPECTION_FAILED")
    return [row[1] for row in csv.reader(io.StringIO(process.stdout))
            if len(row) >= 2 and row[0] == Path(executable).name]


def runtime_run(*, execution_config, delivery_root, runtime_config, run_id, action, decision=None):
    case = _inputs(execution_config, delivery_root, run_id)
    receipt = _read_receipt(case)
    if not receipt or receipt.get("status") != "delivered":
        raise ValueError("DSH_RUNTIME_VERIFIED_DELIVERY_REQUIRED")
    config = read_json_object(runtime_config)
    if set(config) != {"settings_path", "runtime_plugin_destination"}:
        raise ValueError("DSH_RUNTIME_CONFIGURATION_INVALID")
    if any(not isinstance(value, str) or not Path(value).is_absolute() for value in config.values()):
        raise ValueError("DSH_RUNTIME_ABSOLUTE_PATHS_REQUIRED")
    checkpoint = receipt["build_result"]["workflow_checkpoint"]
    arguments = {"run_root": str(case["run_root"]), "artifact_store_root": str(case["store"].root),
                 "feature_id": checkpoint["feature_id"], "checkpoint_path": checkpoint["path"],
                 "checkpoint_hash": checkpoint["artifact_hash"], **config}
    journal = case["run_root"] / "dsh_runtime_result.json"
    if journal.exists():
        previous = read_json_object(journal)
        if previous.get("run_id") != run_id:
            raise ValueError("DSH_RUNTIME_RESULT_IDENTITY_INVALID")
        return {**previous, "read_only": True, "model_calls_performed": 0}
    preflight = preflight_local_runtime(**arguments)
    process_ids = _running_game(preflight["runtime_profile"]["profile"]["game_executable"])
    scope = {"run_id": run_id, "preflight": preflight,
             "settings_sha256": hashlib.sha256(Path(config["settings_path"]).read_bytes()).hexdigest(),
             "runtime_config_sha256": hashlib.sha256(Path(runtime_config).read_bytes()).hexdigest()}
    scope_hash = _hash(scope)
    result = {"entry": "dsh-runtime", "run_id": run_id, "status": "awaiting_runtime_approval",
              "read_only": True, "scope_hash": scope_hash, "preflight": preflight,
              "model_calls_performed": 0, "runtime_success_claimed": False,
              "observation_directory": str(case["run_root"] / "operator_completion")}
    if process_ids:
        return {**result, "status": "blocked", "reason": "DSH_RUNTIME_GAME_ALREADY_RUNNING",
                "running_process_ids": process_ids}
    if preflight.get("status") != "READY_FOR_EXTERNAL_AUTHORIZATION":
        return {**result, "status": "blocked"}
    if action == "preview":
        return result
    if action != "execute":
        raise ValueError("DSH_RUNTIME_ACTION_INVALID")
    if (not isinstance(decision, dict) or set(decision) != {"scope_hash", "reviewer", "decision"}
            or decision["decision"] != "approve" or decision["scope_hash"] != scope_hash
            or not isinstance(decision["reviewer"], str) or not decision["reviewer"].strip()
            or len(decision["reviewer"]) > 200):
        raise ValueError("DSH_RUNTIME_EXACT_APPROVAL_REQUIRED")
    # The original owner controls all deployment, process, restoration and Graph effects.
    # A started/uncertain operation is retained and never retried by the UI bridge.
    result.update(status="running", read_only=False, decision=decision)
    with journal.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    try:
        owner = resume_local_runtime(**arguments, approved_by=decision["reviewer"],
                                     allow_game_launch=True, allow_game_directory_write=True)
        result.update(status="recorded", owner_result=owner)
    except Exception as exc:
        result.update(status="blocked", reason=str(exc), effects="inspect_original_runtime_records")
    temporary = journal.with_suffix(".pending")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(journal)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--execution-config", required=True)
    parser.add_argument("--delivery-root", required=True)
    parser.add_argument("--runtime-config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--action", choices=("preview", "execute"), required=True)
    args = parser.parse_args(argv)
    try:
        decision = None
        if args.action == "execute":
            raw = sys.stdin.buffer.read(16385)
            if len(raw) > 16384:
                raise ValueError("DSH_RUNTIME_DECISION_TOO_LARGE")
            decision = json.loads(raw)
        result = runtime_run(**vars(args), decision=decision)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        result = {"entry": "dsh-runtime", "run_id": args.run_id, "status": "blocked", "reason": str(exc),
                  "model_calls_performed": 0, "runtime_success_claimed": False}
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
