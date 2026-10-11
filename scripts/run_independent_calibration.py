"""Run public independent-evaluation engineering preparation; no model transport."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mod_agent.evaluation.independent_preparation import (  # noqa: E402
    evaluate_submission,
    public_inventory,
    run_calibration,
    validate_config,
    worker,
    write_once,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "config/independent_eval_public.json"))
    parser.add_argument("--output-root")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--worker-input", help=argparse.SUPPRESS)
    parser.add_argument("--judge-task")
    parser.add_argument("--submission", help="Public calibration submission JSON; never a Python entrypoint")
    parser.add_argument("--inventory-protocol")
    parser.add_argument("--inventory-metadata")
    parser.add_argument("--inventory-output")
    args = parser.parse_args(argv)
    if args.inventory_protocol:
        if not args.inventory_metadata or not args.inventory_output:
            parser.error("Public inventory requires protocol, metadata and output")
        result = public_inventory(protocol_path=args.inventory_protocol, metadata_path=args.inventory_metadata)
        write_once(args.inventory_output, result)
    elif args.worker_input:
        result = worker(**json.loads(Path(args.worker_input).read_text(encoding="utf-8")))
    elif args.judge_task:
        if not args.submission or args.output_root:
            parser.error("--judge-task requires only --submission and optional --config")
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        validate_config(config)
        matches = [t for t in config["tasks"] if t["task_id"] == args.judge_task]
        if len(matches) != 1:
            parser.error("Unknown task identity")
        result = evaluate_submission(matches[0], json.loads(Path(args.submission).read_text(encoding="utf-8")))
    else:
        if not args.output_root or args.submission:
            parser.error("--output-root is required for a new calibration run")
        report = run_calibration(config_path=args.config, output_root=args.output_root, repetitions=args.repetitions)
        result = {k: v for k, v in report.items() if k != "results"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result.get("task_success") is not False and all(
        row["unresolved_task_count"] == 0 and row["first_attempt_successes"] == row["distinct_task_count"]
        for row in result.get("summary", {}).values())) else 2


if __name__ == "__main__":
    raise SystemExit(main())
