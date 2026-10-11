"""Freeze two existing TaskMemory settings/stores; no model or task execution."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mod_agent.evaluation.memory_comparison import (  # noqa: E402
    prepare_memory_pair,
    verify_memory_pair,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--settings")
    parser.add_argument("--memory-root")
    parser.add_argument("--invariants", help="Public identity-only JSON; never hidden task contents")
    parser.add_argument("--output-root")
    parser.add_argument("--verify")
    parser.add_argument("--sha256")
    args = parser.parse_args(argv)
    if args.verify:
        if not args.sha256 or any((args.settings, args.memory_root, args.invariants, args.output_root)):
            parser.error("Verification requires only --verify and its frozen --sha256")
        result = verify_memory_pair({"path": str(Path(args.verify).resolve()), "sha256": args.sha256})
    else:
        if args.sha256 or not all((args.settings, args.memory_root, args.invariants, args.output_root)):
            parser.error("Preparation requires settings, memory-root, invariants and a new output-root")
        result = prepare_memory_pair(settings_path=args.settings, memory_root=args.memory_root,
            invariants=json.loads(Path(args.invariants).read_text(encoding="utf-8")), output_root=args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
