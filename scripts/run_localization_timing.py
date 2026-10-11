"""Prepare, execute or score the bounded two-failure AI material diagnosis experiment."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mod_agent.evaluation import localization_timing as experiment  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--protocol", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("--prepared", type=Path, required=True)
    execute.add_argument("--output-root", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--prepared", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("--execution", type=Path, required=True)
    score.add_argument("--judgments", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = experiment.prepare(args.protocol, args.output_root)
        elif args.command == "execute":
            result = experiment.execute(args.prepared, args.output_root)
        elif args.command == "verify":
            result = experiment.verify_prepared(args.prepared)
        else:
            result = experiment.summarize(args.execution, args.judgments, args.output)
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
