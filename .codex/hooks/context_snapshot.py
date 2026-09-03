"""Persist and restore a bounded, deterministic Codex task-location snapshot.

This project hook deliberately does not parse Codex transcripts or infer task
completion.  It records only the documented hook inputs, current Git identity,
Git status, and an explicitly materialized task packet.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "codex_context_snapshot_v0"
STATE_DIRECTORY_RELATIVE_PATH = Path(".codex/.runtime/context-snapshots")
TASK_PACKET_RELATIVE_PATH = Path(".codex/task-packet.json")
MAX_HOOK_INPUT_CHARS = 64 * 1024
MAX_SNAPSHOT_CHARS = 64 * 1024
MAX_CONTEXT_TOKENS_ESTIMATE = 1_000
MAX_GIT_STATUS_LINES = 100
MAX_GIT_STATUS_LINE_CHARS = 512
MAX_SESSION_ID_CHARS = 256
MAX_PATH_CHARS = 4_096
MAX_BRANCH_CHARS = 512
MAX_PACKET_LIST_ITEMS = 24
MAX_PACKET_STRING_CHARS = 320

_SCALAR_PACKET_FIELDS = (
    "task_id",
    "goal",
    "base_sha",
    "supported_entry_command",
    "current_node",
    "first_failure_owner",
    "vertical_stage",
)
_LIST_PACKET_FIELDS = (
    "read_first",
    "write_allowlist",
    "protected_paths",
    "verification_commands",
    "done_when",
    "stop_when",
    "out_of_scope",
)
_CONTEXT_PACKET_PRIORITY = (
    "task_id",
    "write_allowlist",
    "protected_paths",
    "stop_when",
    "current_node",
    "first_failure_owner",
    "vertical_stage",
    "done_when",
    "verification_commands",
    "goal",
    "supported_entry_command",
    "read_first",
    "surface_objectives",
    "base_sha",
    "out_of_scope",
)


def _success_output() -> dict[str, Any]:
    return {"continue": True}


def _warning_output(message: str) -> dict[str, Any]:
    return {"continue": True, "systemMessage": message}


def _script_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(
            str(right.resolve())
        )
    except (OSError, RuntimeError):
        return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _run_git(cwd: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=environment,
        text=True,
        timeout=5,
    )


def _resolve_target_root(cwd_value: Any, expected_root: Path) -> tuple[Path, Path] | None:
    if not isinstance(cwd_value, str) or not cwd_value.strip():
        return None
    try:
        cwd = Path(cwd_value).resolve(strict=True)
        expected = expected_root.resolve(strict=True)
    except OSError:
        return None
    if not cwd.is_dir() or not _is_within(cwd, expected):
        return None
    try:
        completed = _run_git(cwd, ("rev-parse", "--show-toplevel"))
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        observed_root = Path(completed.stdout.strip()).resolve(strict=True)
    except OSError:
        return None
    if not _same_path(observed_root, expected):
        return None
    return cwd, expected


def _read_git_state(root: Path) -> dict[str, Any] | None:
    try:
        head_result = _run_git(root, ("rev-parse", "--verify", "HEAD"))
        branch_result = _run_git(
            root, ("symbolic-ref", "--quiet", "--short", "HEAD")
        )
        status_result = _run_git(
            root, ("status", "--short", "--untracked-files=all")
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if head_result.returncode != 0 or status_result.returncode != 0:
        return None
    head = head_result.stdout.strip()
    if len(head) not in {40, 64} or any(
        character not in "0123456789abcdefABCDEF" for character in head
    ):
        return None
    all_status_lines = status_result.stdout.splitlines()
    status_lines = [
        line[:MAX_GIT_STATUS_LINE_CHARS]
        for line in all_status_lines[:MAX_GIT_STATUS_LINES]
    ]
    branch = branch_result.stdout.strip()
    if len(branch) > MAX_BRANCH_CHARS:
        branch = branch[:MAX_BRANCH_CHARS]
    return {
        "root": str(root),
        "head": head,
        "branch": branch if branch_result.returncode == 0 and branch else None,
        "dirty": bool(all_status_lines),
        "status": status_lines,
        "status_count": len(all_status_lines),
        "status_truncated": len(all_status_lines) > len(status_lines),
    }


def _bounded_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\x00", "").strip()
    if not normalized:
        return None
    if len(normalized) > MAX_PACKET_STRING_CHARS:
        return normalized[: MAX_PACKET_STRING_CHARS - 1] + "\u2026"
    return normalized


def _bounded_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value[:MAX_PACKET_LIST_ITEMS]:
        bounded = _bounded_string(item)
        if bounded is not None:
            result.append(bounded)
    return result


def _sanitize_task_packet(raw_packet: Any) -> dict[str, Any] | None:
    if not isinstance(raw_packet, Mapping):
        return None
    packet: dict[str, Any] = {}
    for field in _SCALAR_PACKET_FIELDS:
        value = _bounded_string(raw_packet.get(field))
        if value is not None:
            packet[field] = value
    for field in _LIST_PACKET_FIELDS:
        value = _bounded_string_list(raw_packet.get(field))
        if value is not None:
            packet[field] = value

    surface_objectives = raw_packet.get("surface_objectives")
    if isinstance(surface_objectives, Mapping):
        refs = _bounded_string_list(surface_objectives.get("refs"))
        if refs is not None:
            packet["surface_objectives"] = {"refs": refs}
    return packet or None


def _read_task_packet(root: Path) -> dict[str, Any] | None:
    packet_path = root / TASK_PACKET_RELATIVE_PATH
    try:
        if not packet_path.is_file():
            return None
        resolved_packet = packet_path.resolve(strict=True)
        if not _is_within(resolved_packet, root):
            return None
        raw_text = resolved_packet.read_text(encoding="utf-8")
    except OSError:
        return None
    if len(raw_text) > MAX_SNAPSHOT_CHARS:
        return None
    try:
        raw_packet = json.loads(raw_text)
    except (TypeError, ValueError):
        return None
    return _sanitize_task_packet(raw_packet)


def _state_path(root: Path, session_id: str) -> Path:
    session_digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return root / STATE_DIRECTORY_RELATIVE_PATH / f"{session_digest}.json"


def _state_path_is_ignored(root: Path, state_path: Path) -> bool:
    if not _is_within(state_path, root):
        return False
    relative_path = state_path.relative_to(root).as_posix()
    try:
        completed = _run_git(root, ("check-ignore", "--quiet", "--", relative_path))
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _atomic_write_json(path: Path, payload: Mapping[str, Any], root: Path) -> bool:
    parent = path.parent
    try:
        if not _is_within(parent, root):
            return False
        parent.mkdir(parents=True, exist_ok=True)
        if not _is_within(parent.resolve(strict=True), root):
            return False
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=".context-snapshot-",
            suffix=".tmp",
            text=True,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
    except OSError:
        return False
    return True


def _build_snapshot(
    hook_input: Mapping[str, Any], cwd: Path, root: Path, git_state: Mapping[str, Any]
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session": {
            "session_id": hook_input["session_id"],
            "cwd": str(cwd),
            "trigger": hook_input["trigger"],
        },
        "git": dict(git_state),
    }
    task_packet = _read_task_packet(root)
    if task_packet is not None:
        snapshot["task_packet"] = task_packet
    return snapshot


def _valid_snapshot(
    snapshot: Any, *, root: Path, session_id: str
) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    allowed_top_level = {"schema_version", "session", "git", "task_packet"}
    if set(snapshot) - allowed_top_level:
        return None
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        return None

    session = snapshot.get("session")
    if not isinstance(session, dict) or set(session) != {
        "session_id",
        "cwd",
        "trigger",
    }:
        return None
    if session.get("session_id") != session_id:
        return None
    if len(session_id) > MAX_SESSION_ID_CHARS:
        return None
    if session.get("trigger") not in {"manual", "auto"}:
        return None
    stored_cwd = session.get("cwd")
    if (
        not isinstance(stored_cwd, str)
        or len(stored_cwd) > MAX_PATH_CHARS
        or not Path(stored_cwd).is_absolute()
        or not _is_within(Path(stored_cwd), root)
    ):
        return None

    git_state = snapshot.get("git")
    expected_git_fields = {
        "root",
        "head",
        "branch",
        "dirty",
        "status",
        "status_count",
        "status_truncated",
    }
    if not isinstance(git_state, dict) or set(git_state) != expected_git_fields:
        return None
    git_root = git_state.get("root")
    if (
        not isinstance(git_root, str)
        or len(git_root) > MAX_PATH_CHARS
        or not Path(git_root).is_absolute()
        or not _same_path(Path(git_root), root)
    ):
        return None
    head = git_state.get("head")
    if (
        not isinstance(head, str)
        or len(head) not in {40, 64}
        or any(character not in "0123456789abcdefABCDEF" for character in head)
    ):
        return None
    branch = git_state.get("branch")
    if branch is not None and (
        not isinstance(branch, str) or len(branch) > MAX_BRANCH_CHARS
    ):
        return None
    if not isinstance(git_state.get("dirty"), bool):
        return None
    status = git_state.get("status")
    if (
        not isinstance(status, list)
        or len(status) > MAX_GIT_STATUS_LINES
        or not all(
            isinstance(item, str) and len(item) <= MAX_GIT_STATUS_LINE_CHARS
            for item in status
        )
    ):
        return None
    status_count = git_state.get("status_count")
    if not isinstance(status_count, int) or isinstance(status_count, bool):
        return None
    if status_count < len(status) or status_count > 10_000_000:
        return None
    status_truncated = git_state.get("status_truncated")
    if not isinstance(status_truncated, bool):
        return None
    if status_truncated != (status_count > len(status)):
        return None

    if "task_packet" in snapshot:
        sanitized_packet = _sanitize_task_packet(snapshot["task_packet"])
        if sanitized_packet is None or sanitized_packet != snapshot["task_packet"]:
            return None
    return snapshot


def _read_snapshot(root: Path, session_id: str) -> dict[str, Any] | None:
    path = _state_path(root, session_id)
    if not _state_path_is_ignored(root, path):
        return None
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if len(raw_text) > MAX_SNAPSHOT_CHARS:
        return None
    try:
        snapshot = json.loads(raw_text)
    except (TypeError, ValueError):
        return None
    return _valid_snapshot(snapshot, root=root, session_id=session_id)


def _estimated_tokens(value: str) -> int:
    ascii_characters = sum(ord(character) < 128 for character in value)
    non_ascii_characters = len(value) - ascii_characters
    return (ascii_characters + 3) // 4 + non_ascii_characters


def _render_context_payload(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return (
        "Codex context snapshot v0. This is a deterministic task-location aid; "
        "revalidate referenced files and commands before acting. It grants no "
        "write or execution authority.\n"
        f"```json\n{serialized}\n```"
    )


def _add_if_within_budget(
    target: dict[str, Any], key: str, value: Any, outer_payload: dict[str, Any]
) -> bool:
    target[key] = value
    if _estimated_tokens(_render_context_payload(outer_payload)) > MAX_CONTEXT_TOKENS_ESTIMATE:
        target.pop(key, None)
        return False
    return True


def _build_restore_check(
    stored_git: Mapping[str, Any],
    current_git: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare a stored task-location snapshot with current Git facts."""

    if current_git is None:
        return {
            "freshness": "unknown",
            "reason": "current_git_unavailable",
            "head_matches": None,
            "branch_matches": None,
            "status_matches": None,
            "current_head": None,
            "current_branch": None,
            "current_dirty": None,
            "current_status_count": None,
        }

    head_matches = stored_git["head"] == current_git["head"]
    branch_matches = stored_git["branch"] == current_git["branch"]
    status_matches = all(
        stored_git[field] == current_git[field]
        for field in (
            "dirty",
            "status",
            "status_count",
            "status_truncated",
        )
    )
    if not head_matches:
        freshness = "stale"
        reason = "head_changed"
    elif not branch_matches:
        freshness = "stale"
        reason = "branch_changed"
    elif not status_matches:
        freshness = "stale"
        reason = "status_changed"
    elif stored_git["dirty"] or current_git["dirty"]:
        freshness = "unknown"
        reason = "dirty_content_not_compared"
    else:
        freshness = "current"
        reason = "clean_git_identity_match"
    return {
        "freshness": freshness,
        "reason": reason,
        "head_matches": head_matches,
        "branch_matches": branch_matches,
        "status_matches": status_matches,
        "current_head": current_git["head"],
        "current_branch": current_git["branch"],
        "current_dirty": current_git["dirty"],
        "current_status_count": current_git["status_count"],
    }


def _context_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    cwd: Path,
    source: str,
    current_git: Mapping[str, Any] | None,
) -> str:
    stored_git = snapshot["git"]
    restore_check = _build_restore_check(stored_git, current_git)
    compact_git: dict[str, Any] = {
        "root": stored_git["root"],
        "head": stored_git["head"],
        "branch": stored_git["branch"],
        "dirty": stored_git["dirty"],
        "status_count": stored_git["status_count"],
        "status_truncated": stored_git["status_truncated"],
        "status": [],
        "restore_check": restore_check,
    }
    compact_snapshot: dict[str, Any] = {
        "schema_version": snapshot["schema_version"],
        "restored_for": {
            "session_id": snapshot["session"]["session_id"],
            "cwd": str(cwd),
            "source": source,
        },
        "pre_compact": {
            "cwd": snapshot["session"]["cwd"],
            "trigger": snapshot["session"]["trigger"],
        },
        "git": compact_git,
    }

    truncated_fields: list[str] = []
    task_packet = snapshot.get("task_packet")
    if isinstance(task_packet, Mapping):
        compact_packet: dict[str, Any] = {}
        compact_snapshot["task_packet"] = compact_packet
        for field in _CONTEXT_PACKET_PRIORITY:
            if field not in task_packet:
                continue
            value = task_packet[field]
            if isinstance(value, list):
                accepted_items: list[Any] = []
                compact_packet[field] = accepted_items
                for item in value:
                    accepted_items.append(item)
                    if (
                        _estimated_tokens(_render_context_payload(compact_snapshot))
                        > MAX_CONTEXT_TOKENS_ESTIMATE
                    ):
                        accepted_items.pop()
                        break
                if len(accepted_items) != len(value):
                    truncated_fields.append(field)
                if not accepted_items and value:
                    compact_packet.pop(field, None)
            elif field == "surface_objectives" and isinstance(value, Mapping):
                accepted_refs: list[str] = []
                compact_packet[field] = {"refs": accepted_refs}
                for item in value.get("refs", []):
                    accepted_refs.append(item)
                    if (
                        _estimated_tokens(_render_context_payload(compact_snapshot))
                        > MAX_CONTEXT_TOKENS_ESTIMATE
                    ):
                        accepted_refs.pop()
                        break
                if len(accepted_refs) != len(value.get("refs", [])):
                    truncated_fields.append(field)
                if not accepted_refs and value.get("refs"):
                    compact_packet.pop(field, None)
            else:
                if not _add_if_within_budget(
                    compact_packet, field, value, compact_snapshot
                ):
                    truncated_fields.append(field)
        if truncated_fields:
            compact_snapshot["task_packet_truncated_fields"] = list(
                truncated_fields
            )
        if not compact_packet:
            compact_snapshot.pop("task_packet")

    for status_line in stored_git["status"]:
        compact_git["status"].append(status_line)
        if (
            _estimated_tokens(_render_context_payload(compact_snapshot))
            > MAX_CONTEXT_TOKENS_ESTIMATE
        ):
            compact_git["status"].pop()
            break
    compact_git["included_status_count"] = len(compact_git["status"])
    context = _render_context_payload(compact_snapshot)
    if _estimated_tokens(context) <= MAX_CONTEXT_TOKENS_ESTIMATE:
        return context

    # Long filesystem roots can consume the whole budget. They are already
    # validated against the invoking repository, so omit only their repeated
    # model-facing copies while keeping exact HEAD, branch, and status counts.
    compact_git.pop("root", None)
    compact_snapshot["restored_for"].pop("cwd", None)
    compact_snapshot["pre_compact"].pop("cwd", None)
    while compact_git["status"]:
        context = _render_context_payload(compact_snapshot)
        if _estimated_tokens(context) <= MAX_CONTEXT_TOKENS_ESTIMATE:
            return context
        compact_git["status"].pop()
        compact_git["included_status_count"] = len(compact_git["status"])
    context = _render_context_payload(compact_snapshot)
    if _estimated_tokens(context) <= MAX_CONTEXT_TOKENS_ESTIMATE:
        return context

    minimal_snapshot = {
        "schema_version": snapshot["schema_version"],
        "restored_for": {"source": source},
        "pre_compact": {"trigger": snapshot["session"]["trigger"]},
        "git": {
            "head": stored_git["head"],
            "branch": stored_git["branch"],
            "dirty": stored_git["dirty"],
            "status_count": stored_git["status_count"],
            "restore_check": restore_check,
        },
    }
    if truncated_fields:
        minimal_snapshot["task_packet_truncated_fields"] = list(
            truncated_fields
        )
    if compact_packet:
        minimal_packet = dict(compact_packet)
        minimal_snapshot["task_packet"] = minimal_packet
        while (
            minimal_packet
            and _estimated_tokens(_render_context_payload(minimal_snapshot))
            > MAX_CONTEXT_TOKENS_ESTIMATE
        ):
            minimal_packet.pop(next(reversed(minimal_packet)))
        if not minimal_packet:
            minimal_snapshot.pop("task_packet")
    return _render_context_payload(minimal_snapshot)


def dispatch(
    mode: str, hook_input: Any, *, expected_root: Path | None = None
) -> dict[str, Any]:
    if not isinstance(hook_input, Mapping):
        return _success_output()
    root = expected_root if expected_root is not None else _script_repo_root()
    session_id = hook_input.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return _success_output()
    if len(session_id) > MAX_SESSION_ID_CHARS:
        return _success_output()
    resolved = _resolve_target_root(hook_input.get("cwd"), root)
    if resolved is None:
        return _success_output()
    cwd, root = resolved

    if mode == "pre_compact":
        if hook_input.get("hook_event_name") != "PreCompact":
            return _success_output()
        if hook_input.get("trigger") not in {"manual", "auto"}:
            return _success_output()
        git_state = _read_git_state(root)
        if git_state is None:
            return _success_output()
        state_path = _state_path(root, session_id)
        if not _state_path_is_ignored(root, state_path):
            return _warning_output(
                "Codex context snapshot was not saved because its runtime path "
                "is not ignored by Git."
            )
        snapshot = _build_snapshot(hook_input, cwd, root, git_state)
        if not _atomic_write_json(state_path, snapshot, root):
            return _warning_output(
                "Codex context snapshot could not be saved; compaction will "
                "continue without a new snapshot."
            )
        return _success_output()

    if mode == "session_start":
        if hook_input.get("hook_event_name") != "SessionStart":
            return _success_output()
        source = hook_input.get("source")
        if source not in {"compact", "resume"}:
            return _success_output()
        snapshot = _read_snapshot(root, session_id)
        if snapshot is None:
            return _success_output()
        current_git = _read_git_state(root)
        context = _context_from_snapshot(
            snapshot,
            cwd=cwd,
            source=source,
            current_git=current_git,
        )
        return {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            },
        }

    return _success_output()


def _read_hook_input() -> Any:
    raw_input = sys.stdin.read(MAX_HOOK_INPUT_CHARS + 1)
    if len(raw_input) > MAX_HOOK_INPUT_CHARS:
        return None
    try:
        return json.loads(raw_input)
    except (TypeError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    mode = arguments[0] if len(arguments) == 1 else ""
    result = dispatch(mode, _read_hook_input())
    sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
