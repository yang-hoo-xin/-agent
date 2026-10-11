"""Admit and copy an author-published answer-free independent task release."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mod_agent.evaluation.independent_release import prepare_released_pair  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    result = prepare_released_pair(
        inventory_ref={"path": str(Path(args.inventory).resolve()), "sha256": args.inventory_sha256},
        release_ref={"path": str(Path(args.release).resolve()), "sha256": args.release_sha256},
        output_root=args.output_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
