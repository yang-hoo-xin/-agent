#!/usr/bin/env python
"""Validate and summarize a benchmark outcome ledger without running Product work."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mod_agent.evaluation.benchmark_outcome_ledger import (  # noqa: E402
    aggregate_outcome_ledger,
    verify_evidence_references,
)


def _local_path(value: Path, *, label: str) -> Path:
    if str(value).startswith(("\\\\", "//")):
        raise ValueError(f"{label} must be a local path.")
    return value.resolve()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        ledger_path = _local_path(args.ledger, label="Ledger")
        ledger_raw = ledger_path.read_bytes()
        ledger = json.loads(ledger_raw)

        # The normal entry verifies source bytes before reporting any metric.
        # 为什么要有它：引用形状正确不代表原件仍是当时的内容，汇总不能在证据漂移后继续发布旧结论。
        evidence = verify_evidence_references(ledger)
        report = {
            "schema": "benchmark-outcome-report.v1",
            "read_only": True,
            "inspection_model_calls": 0,
            "ledger_ref": {
                "path": str(ledger_path),
                "sha256": hashlib.sha256(ledger_raw).hexdigest(),
            },
            "evidence_verification": evidence,
            "summary": aggregate_outcome_ledger(ledger),
        }
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output is None:
            print(text, end="")
        else:
            output = _local_path(args.output, label="Output")
            if output == ledger_path:
                raise ValueError("Output cannot replace the selected ledger.")
            output.parent.mkdir(parents=True, exist_ok=True)
            # Preserve every previously generated snapshot.
            # 为什么要有它：新汇总不能覆盖旧结论，否则无法复查指标何时因新增运行而变化。
            with output.open("x", encoding="utf-8") as handle:
                handle.write(text)
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "blocked", "reason": f"{type(error).__name__}: {error}"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
