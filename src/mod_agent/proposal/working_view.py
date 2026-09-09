"""Read-only views of the exact combined source bytes sent to verification."""
from __future__ import annotations

import difflib
import hashlib
from typing import Any

from src.mod_agent.execution.patch_apply import MaterializedPatchBytes


def build_materialized_patch_view(
    materialized: MaterializedPatchBytes, *, context_radius_lines: int,
) -> dict[str, Any]:
    """Show changed regions in current coordinates; never reinterpret edit authority."""
    if type(context_radius_lines) is not int or context_radius_lines < 1:
        raise ValueError("Current source view requires a positive context radius.")
    files = []
    for path, current in sorted(materialized.files.items()):
        before = materialized.baseline_files[path].decode("utf-8-sig").splitlines(keepends=True)
        after = current.decode("utf-8-sig").splitlines(keepends=True)
        windows: list[tuple[int, int]] = []
        for tag, _, _, start, end in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            left, right = max(0, start - context_radius_lines), min(len(after), end + context_radius_lines)
            if windows and left <= windows[-1][1]:
                windows[-1] = (windows[-1][0], max(windows[-1][1], right))
            else:
                windows.append((left, right))
        diff_lines = list(difflib.unified_diff(
            materialized.baseline_files[path].decode("utf-8-sig").splitlines(),
            current.decode("utf-8-sig").splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
        ))
        files.append({
            "path": path, "raw_bytes_sha256": hashlib.sha256(current).hexdigest(),
            "line_count": len(after), "complete": not after or windows == [(0, len(after))],
            "hunks": [{"start_line": start + 1, "end_line": end, "text": "".join(after[start:end])}
                for start, end in windows if end > start],
            "unified_diff": "\n".join(diff_lines) + ("\n" if diff_lines else ""),
        })
    return {
        "schema_version": "patch_materialized_working_view_v1",
        "baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256,
        "source_role": "current_verified_materialization_not_live_baseline",
        "coordinate_system": "current_file_lines_not_edit_binding_spans",
        "files": files,
    }
