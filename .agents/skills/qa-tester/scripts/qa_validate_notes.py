#!/usr/bin/env python3
"""Validate the structure of explicitly supplied QA progress rows.

This helper checks row structure only. It never treats prose as proof that a
test command ran.

Usage:
    python .agents/skills/qa-tester/scripts/qa_validate_notes.py <progress.md>

Exit code:
    0 — All notes pass validation
    1 — One or more structural checks failed
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RESULT_ROW = re.compile(
    r"\|\s*(✅|❌|⏭️?|PASS|FAIL|SKIP)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|$",
    re.IGNORECASE,
)


def validate(progress_file: str | Path) -> bool:
    progress_path = Path(progress_file)
    if not progress_path.is_file():
        print(f"FAIL: progress file not found: {progress_path}")
        return False
    content = progress_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    issues = []
    total_results = 0
    identifiers = set()

    for lineno, line in enumerate(lines, 1):
        # 为什么要有它：校验结果行结构，不把至少一次通过当作报告有效性的条件。
        m = RESULT_ROW.match(line.strip())
        if not m:
            continue

        test_id = m.group(2).strip()
        title = m.group(3).strip()
        note = m.group(4).strip()
        total_results += 1
        if not test_id:
            issues.append(("<empty>", lineno, "Result row test ID is empty", note[:80]))
        if test_id in identifiers:
            issues.append((test_id, lineno, "Duplicate result test ID", note[:80]))
        identifiers.add(test_id)
        if not title:
            issues.append((test_id, lineno, "Result row title is empty", note[:80]))
        if not note:
            issues.append((test_id, lineno, "Result row note is empty", ""))

    if total_results == 0:
        issues.append(("<none>", 0, "No result rows found", ""))

    # Print report
    print("QA Note Validation Report")
    print(f"   Total result entries: {total_results}")
    print(f"   Flagged entries:    {len(issues)}")
    print()

    if issues:
        print("STRUCTURAL ISSUES:")
        print("-" * 70)
        for test_id, lineno, reason, note_preview in issues:
            print(f"  [{test_id}] Line {lineno}")
            print(f"    Reason: {reason}")
            print(f"    Note:   {note_preview}...")
            print()
        print(f"FAIL: {len(issues)} structural issue(s) found.")
    else:
        print("PASS: Result rows are structurally complete.")
        print("NOTE: Structural checks cannot prove that any test command ran.")

    return len(issues) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate QA progress row structure")
    parser.add_argument("progress_file", type=Path)
    arguments = parser.parse_args()
    ok = validate(arguments.progress_file)
    sys.exit(0 if ok else 1)
