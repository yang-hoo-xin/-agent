"""Prepare, preflight or explicitly select a fixed Patch task for the existing CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mod_agent.evaluation.patch_task_suite import (  # noqa: E402
    preflight_patch_suite,
    prepare_accurate_crosshair_suite,
    reference,
    task_cli_arguments,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-seed", help="Explicit JSON with output_root, p0_arguments_path, p0_matrix_ref and p0_identity_refs.")
    parser.add_argument("--prepare-experiment", help="Explicit existing-suite, task partitions and paired local profiles seed; zero model calls.")
    parser.add_argument("--experiment", help="An already prepared experiment JSON; requires its exact SHA-256 and cell ID.")
    parser.add_argument("--experiment-sha256")
    parser.add_argument("--cell-id")
    parser.add_argument("--suite", help="Existing frozen suite JSON; preflight is the default.")
    parser.add_argument("--select", help="Exact case_id; print its existing CLI arguments.")
    parser.add_argument("--attempt-id", help="Explicit identity required for selection or execution.")
    parser.add_argument("--execute", action="store_true", help="Run the selected case through the existing public CLI; makes real model calls.")
    args = parser.parse_args(argv)
    if args.prepare_experiment or args.experiment:
        from src.observability.evaluation.patch_model_experiment import (
            prepare_patch_model_experiment,
            select_patch_experiment_cell,
        )
        if args.prepare_seed or args.suite or args.select or args.execute or args.attempt_id:
            parser.error("Experiment preparation/selection does not execute or replace an existing task selection.")
        if args.prepare_experiment:
            if args.experiment or args.experiment_sha256 or args.cell_id:
                parser.error("Choose experiment preparation or one frozen cell.")
            result = prepare_patch_model_experiment(**json.loads(Path(args.prepare_experiment).read_text(encoding="utf-8")))
        else:
            if not args.experiment_sha256 or not args.cell_id:
                parser.error("Frozen experiment selection requires --experiment-sha256 and --cell-id.")
            result = select_patch_experiment_cell(experiment_ref={"path": str(Path(args.experiment).resolve()),
                "sha256": args.experiment_sha256}, cell_id=args.cell_id)
    elif args.prepare_seed:
        if args.suite or args.select or args.execute:
            parser.error("Preparation cannot be combined with selection or execution.")
        result = prepare_accurate_crosshair_suite(**json.loads(Path(args.prepare_seed).read_text(encoding="utf-8")))
    elif args.suite:
        if args.select:
            if not args.attempt_id:
                parser.error("Selection requires an explicit attempt identity.")
            selected = task_cli_arguments(suite_ref=reference(args.suite), case_id=args.select, attempt_id=args.attempt_id)
            if args.execute:
                from src.mod_agent.cli import main as product_main
                return product_main(selected)
            result = {"model_calls": 0, "command": "python -m src.mod_agent.cli", "arguments": selected}
        else:
            if args.execute:
                parser.error("Execution requires one selected task; there is no automatic suite retry loop.")
            result = preflight_patch_suite(reference(args.suite))
    else:
        parser.error("Choose --prepare-seed, --suite, --prepare-experiment or --experiment.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("admitted", result.get("preflight", {}).get("admitted", True)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
