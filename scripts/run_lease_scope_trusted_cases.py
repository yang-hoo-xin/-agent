"""Run trusted lease-scope assertions against an external JSON subject worker.

Only each case's operation is sent to the worker. Assertions and expected values
remain in this trusted driver and are omitted from its aggregate result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from src.mod_agent.evaluation.independent_preparation import write_once
from src.mod_agent.model_qualification import read_bound_json


def _select(value, path):
    for key in path:
        if isinstance(key, int) and isinstance(value, list) and 0 <= key < len(value):
            value = value[key]
        elif isinstance(key, str) and isinstance(value, dict) and key in value:
            value = value[key]
        else:
            raise ValueError("LEASE_SCOPE_ASSERTION_PATH_INVALID")
    return value


def run(*, command_ref, cases_ref, output_root):
    command, document = read_bound_json(command_ref), read_bound_json(cases_ref)
    if (set(command) != {"executable_ref", "argv", "cwd", "timeout_seconds", "isolation"}
            or command["isolation"] not in {"none_development_probe_only", "container_restricted"}
            or not isinstance(command["argv"], list)):
        raise ValueError("LEASE_SCOPE_WORKER_COMMAND_INVALID")
    if (document.get("schema_version") != "lease_scope_trusted_cases_v1"
            or set(document) != {"schema_version", "task_id", "eligibility", "cases"}
            or not isinstance(document["cases"], list) or not document["cases"]):
        raise ValueError("LEASE_SCOPE_CASES_INVALID")
    results = []
    for case in document["cases"]:
        if set(case) != {"case_id", "operation", "assertions"}:
            raise ValueError("LEASE_SCOPE_CASE_INVALID")
        request = json.dumps(case["operation"], ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        process = subprocess.run([command["executable_ref"]["path"], *command["argv"]],
            cwd=command["cwd"], input=request, capture_output=True, text=True, encoding="utf-8",
            timeout=command["timeout_seconds"])
        if process.returncode != 0:
            results.append({"case_id": case["case_id"], "status": "infrastructure_failed",
                            "assertion_count": len(case["assertions"]), "failed_assertions": None,
                            "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
                            "response_sha256": None})
            continue
        response = json.loads(process.stdout)
        failures = 0
        for assertion in case["assertions"]:
            if (not isinstance(assertion, dict) or set(assertion) != {"path", "equals"}
                    or _select(response, assertion["path"]) != assertion["equals"]):
                failures += 1
        results.append({"case_id": case["case_id"],
            "status": "passed" if failures == 0 else "behavior_failed",
            "assertion_count": len(case["assertions"]), "failed_assertions": failures,
            "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
            "response_sha256": hashlib.sha256(process.stdout.encode()).hexdigest()})
    summary = {"schema_version": "lease_scope_trusted_case_result_v1",
        "task_id": document["task_id"], "eligibility": document["eligibility"],
        "isolation": command["isolation"], "cases": results,
        "case_count": len(results), "passed": sum(row["status"] == "passed" for row in results),
        "behavior_failed": sum(row["status"] == "behavior_failed" for row in results),
        "infrastructure_failed": sum(row["status"] == "infrastructure_failed" for row in results),
        "worker_received_assertions_or_expected": False, "model_calls": 0}
    return write_once(Path(output_root).resolve() / "trusted-case-result.json", summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--command", required=True)
    parser.add_argument("--command-sha256", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--cases-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    try:
        Path(args.output_root).resolve().mkdir(parents=True, exist_ok=False)
        result = run(command_ref={"path": str(Path(args.command).resolve()), "sha256": args.command_sha256},
                     cases_ref={"path": str(Path(args.cases).resolve()), "sha256": args.cases_sha256},
                     output_root=args.output_root)
    except Exception as exc:
        print(json.dumps({"status": "blocked", "failure_class": type(exc).__name__}))
        return 2
    print(json.dumps({"status": "completed", "result_ref": result, "model_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
