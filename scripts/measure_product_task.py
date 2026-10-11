#!/usr/bin/env python
"""Measure explicitly selected local Product segments without executing the product."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mod_agent.evaluation.task_measurement import measure_product_task  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--allowed-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--continuation-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tool-effects", action="store_true", help="Attach read-only tool-effect evidence with unknown semantic judgments preserved.")
    args = parser.parse_args(argv)
    try:
        result = measure_product_task(allowed_root=args.allowed_root, run_root=args.run_root,
            run_id=args.run_id, continuation_roots=args.continuation_root)
        if args.tool_effects:
            from src.mod_agent.evaluation.tool_effects import extract_tool_effects
            result["tool_effects"] = extract_tool_effects(result)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output is None:
            print(text, end="")
        else:
            if str(args.output).startswith(("\\\\", "//")):
                raise ValueError("Output must be a local file.")
            if args.output.resolve().is_relative_to(args.run_root.resolve()):
                raise ValueError("Measurement output must be outside immutable run history.")
            # Exclusive creation protects earlier evidence and the selected history.
            # 为什么要有它：measurement reports cannot silently replace run records.
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(text)
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
