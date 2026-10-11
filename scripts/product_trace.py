#!/usr/bin/env python
"""Read one explicit local Product run and optional continuation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.observability.dashboard.services.trace_service import TraceService  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--allowed-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--continuation-root", type=Path)
    parser.add_argument("--include-local-raw", action="store_true")
    parser.add_argument("--context-chain", action="store_true", help="Join recorded inputs, decisions and outcomes; no model judge.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.context_chain and not args.include_local_raw:
        parser.error("--context-chain requires --include-local-raw")
    if args.format == "markdown" and not args.context_chain:
        parser.error("--format markdown requires --context-chain")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        inspect = TraceService(max_string_chars=262_144).inspect_product_run
        if args.context_chain:
            from src.mod_agent.evaluation.context_chain import inspect_context_chain
            inspect = inspect_context_chain
        result = inspect(
            allowed_root=args.allowed_root,
            run_root=args.run_root,
            run_id=args.run_id,
            continuation_root=args.continuation_root,
            include_local_raw=args.include_local_raw,
        )
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.format == "markdown":
            from src.mod_agent.evaluation.context_chain import render_context_chain
            text = render_context_chain(result)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if args.context_chain:
                with args.output.open("x", encoding="utf-8") as handle:
                    handle.write(text)
            else:
                args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
