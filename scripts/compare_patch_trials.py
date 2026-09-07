"""Read one fixed task and explicitly selected journals without rerunning them."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.mod_agent.evaluation.patch_trial_comparison import compare_patch_trials
from src.mod_agent.model_qualification import read_bound_json
from src.observability.patch_execution_index import project_patch_executions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, type=Path)
    parser.add_argument("--attempt", action="append", required=True, help="Exact journal locator within the task ArtifactStore cr directory")
    parser.add_argument("--output", type=Path, help="Optional new report file; existing files are never overwritten")
    args = parser.parse_args(argv)
    task = args.task.resolve(strict=True)
    task_ref = {"path": str(task), "sha256": hashlib.sha256(task.read_bytes()).hexdigest()}
    request = read_bound_json(read_bound_json(task_ref)["continuation_input_ref"])
    indexes = [project_patch_executions(request["artifact_store_root"], attempt_locator=locator) for locator in args.attempt]
    result = compare_patch_trials(task_ref=task_ref, attempt_indexes=indexes)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output is None:
        print(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as stream:
            stream.write(encoded.encode("utf-8"))
        print(json.dumps({"report_path": str(args.output.resolve()), "task_denominator": result["task_denominator"],
                          "trial_denominator": result["trial_denominator"], "outcomes": result["outcomes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
