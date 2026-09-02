#!/usr/bin/env python3
"""Build a strict, Git-backed handoff packet without changing the repository by default."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

INPUT_VERSION = "bounded-task-handoff.v1"
OUTPUT_VERSION = "bounded-task-handoff-output.v1"
MAX_INPUT_BYTES = 32_768
MAX_TEXT_CHARACTERS = 320
MAX_LIST_ITEMS = 24
MAX_ESTIMATED_OUTPUT_TOKENS = 1_500
TOP_LEVEL_FIELDS = {
    "schema_version",
    "task_id",
    "goal",
    "read_first",
    "write_allowlist",
    "protected_paths",
    "verification_commands",
    "done_when",
    "stop_when",
    "out_of_scope",
    "supported_entry_command",
    "current_node",
    "first_failure_owner",
    "vertical_stage",
    "surface_objectives",
    "target_commit",
}


class InputError(ValueError):
    pass


class GitError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise InputError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise InputError(f"unsupported JSON constant: {value}")


def _load_input(path: Path) -> dict[str, Any]:
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read input: {exc}") from exc
    if len(raw_bytes) > MAX_INPUT_BYTES:
        raise InputError(
            f"input byte limit exceeded: {len(raw_bytes)} > {MAX_INPUT_BYTES}"
        )
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("input must be UTF-8") from exc
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, InputError) as exc:
        raise InputError(f"invalid JSON input: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError("input root must be an object")
    return value


def _require_exact_fields(
    value: dict[str, Any], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(unknown)}")
        raise InputError(f"{location}: {'; '.join(parts)}")


def _text(value: Any, location: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise InputError(f"{location} must be a string")
    if not value or value != value.strip():
        raise InputError(f"{location} must be non-empty without outer whitespace")
    if "\n" in value or "\r" in value:
        raise InputError(f"{location} must be one line")
    if len(value) > MAX_TEXT_CHARACTERS:
        raise InputError(
            f"{location} character limit exceeded: "
            f"{len(value)} > {MAX_TEXT_CHARACTERS}"
        )
    return value


def _text_list(
    value: Any, location: str, *, minimum: int = 0
) -> list[str]:
    if not isinstance(value, list):
        raise InputError(f"{location} must be an array")
    if len(value) > MAX_LIST_ITEMS:
        raise InputError(
            f"{location} item limit exceeded: {len(value)} > {MAX_LIST_ITEMS}"
        )
    result = []
    for index, item in enumerate(value):
        checked = _text(item, f"{location}[{index}]")
        assert isinstance(checked, str)
        result.append(checked)
    if len(result) < minimum:
        raise InputError(f"{location} must contain at least {minimum} item(s)")
    if len(set(result)) != len(result):
        raise InputError(f"{location} must not contain duplicate values")
    return result


def _validate_input(value: dict[str, Any]) -> dict[str, Any]:
    _require_exact_fields(value, TOP_LEVEL_FIELDS, "root")
    if value["schema_version"] != INPUT_VERSION:
        raise InputError(f"schema_version must equal {INPUT_VERSION}")

    surface = value["surface_objectives"]
    if not isinstance(surface, dict):
        raise InputError("surface_objectives must be an object")
    _require_exact_fields(surface, {"refs"}, "surface_objectives")

    checked = {
        "task_id": _text(value["task_id"], "task_id"),
        "goal": _text(value["goal"], "goal"),
        "read_first": _text_list(value["read_first"], "read_first", minimum=1),
        "write_allowlist": _text_list(
            value["write_allowlist"], "write_allowlist", minimum=1
        ),
        "protected_paths": _text_list(
            value["protected_paths"], "protected_paths", minimum=1
        ),
        "verification_commands": _text_list(
            value["verification_commands"], "verification_commands", minimum=1
        ),
        "done_when": _text_list(value["done_when"], "done_when", minimum=1),
        "stop_when": _text_list(value["stop_when"], "stop_when", minimum=1),
        "out_of_scope": _text_list(
            value["out_of_scope"], "out_of_scope", minimum=1
        ),
        "supported_entry_command": _text(
            value["supported_entry_command"], "supported_entry_command"
        ),
        "current_node": _text(value["current_node"], "current_node"),
        "first_failure_owner": _text(
            value["first_failure_owner"], "first_failure_owner", nullable=True
        ),
        "vertical_stage": _text(value["vertical_stage"], "vertical_stage"),
        "surface_objectives": {
            "refs": _text_list(
                surface["refs"], "surface_objectives.refs", minimum=1
            )
        },
        "target_commit": _text(
            value["target_commit"], "target_commit", nullable=True
        ),
    }
    overlap = sorted(
        set(checked["write_allowlist"]) & set(checked["protected_paths"])
    )
    if overlap:
        raise InputError(
            "write_allowlist and protected_paths overlap exactly: "
            + ", ".join(overlap)
        )
    return checked


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(
            f"git {' '.join(arguments)} failed with "
            f"exit {completed.returncode}: {detail}"
        )
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitError(f"git {' '.join(arguments)} returned non-UTF-8 output") from exc


def _nul_values(value: str) -> list[str]:
    return sorted(item for item in value.split("\0") if item)


def _git_snapshot(repo: Path, target_commit: str | None) -> tuple[Path, dict[str, Any]]:
    root = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    head = _git(root, "rev-parse", "--verify", "HEAD").strip()
    branch_text = _git(root, "branch", "--show-current").strip()
    status_text = _git(
        root, "status", "--short", "--untracked-files=all"
    ).rstrip("\r\n")
    staged = _nul_values(
        _git(root, "diff", "--cached", "--name-only", "-z", "--")
    )
    unstaged = _nul_values(_git(root, "diff", "--name-only", "-z", "--"))
    untracked = _nul_values(
        _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    )

    target: dict[str, Any] | None = None
    if target_commit is not None:
        target_sha = _git(
            root, "rev-parse", "--verify", f"{target_commit}^{{commit}}"
        ).strip()
        target_parents = [
            item
            for item in _git(root, "show", "-s", "--format=%P", target_sha).split()
            if item
        ]
        head_parents = [
            item
            for item in _git(root, "show", "-s", "--format=%P", head).split()
            if item
        ]
        target = {
            "requested": target_commit,
            "resolved_sha": target_sha,
            "parent_shas": target_parents,
            "is_head": target_sha == head,
            "head_is_direct_parent": head in target_parents,
            "target_is_direct_parent_of_head": target_sha in head_parents,
        }

    snapshot = {
        "repository_root": str(root),
        "head_sha": head,
        "branch": branch_text or None,
        "is_clean": not bool(status_text),
        "status_short": status_text.splitlines() if status_text else [],
        "staged_paths": staged,
        "unstaged_paths": unstaged,
        "untracked_paths": untracked,
        "target_commit": target,
    }
    return root, snapshot


def _build_packet(inputs: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": OUTPUT_VERSION,
        "task_id": inputs["task_id"],
        "goal": inputs["goal"],
        "base_sha": snapshot["head_sha"],
        "current_node": inputs["current_node"],
        "first_failure_owner": inputs["first_failure_owner"],
        "vertical_stage": inputs["vertical_stage"],
        "surface_objectives": inputs["surface_objectives"],
        "supported_entry_command": inputs["supported_entry_command"],
        "read_first": inputs["read_first"],
        "write_allowlist": inputs["write_allowlist"],
        "protected_paths": inputs["protected_paths"],
        "verification_commands": inputs["verification_commands"],
        "done_when": inputs["done_when"],
        "stop_when": inputs["stop_when"],
        "out_of_scope": inputs["out_of_scope"],
        "git_snapshot": snapshot,
    }


def _json_text(packet: dict[str, Any]) -> str:
    return json.dumps(packet, ensure_ascii=False, indent=2) + "\n"


def _estimated_token_count(value: str) -> int:
    count = 0
    ascii_word_length = 0

    def flush_ascii_word() -> None:
        nonlocal ascii_word_length, count
        if ascii_word_length:
            count += (ascii_word_length + 3) // 4
            ascii_word_length = 0

    for character in value:
        if character.isascii() and (
            character.isalnum() or character in "_-"
        ):
            ascii_word_length += 1
            continue
        flush_ascii_word()
        if character in "\r\n":
            count += 1
        elif not character.isspace():
            count += 1
    flush_ascii_word()
    return count


def _validate_rendered_outputs(
    json_output: str, markdown_output: str
) -> None:
    counts = {
        "json": _estimated_token_count(json_output),
        "markdown": _estimated_token_count(markdown_output),
    }
    exceeded = [
        f"{name}={count}"
        for name, count in counts.items()
        if count > MAX_ESTIMATED_OUTPUT_TOKENS
    ]
    if exceeded:
        raise InputError(
            "rendered output limit exceeded: "
            + ", ".join(exceeded)
            + f"; limit={MAX_ESTIMATED_OUTPUT_TOKENS} estimated tokens"
        )


def _markdown_list(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def _markdown(packet: dict[str, Any]) -> str:
    snapshot = packet["git_snapshot"]
    target = snapshot["target_commit"]
    target_text = "null" if target is None else json.dumps(target, ensure_ascii=False)
    owner = (
        "null"
        if packet["first_failure_owner"] is None
        else packet["first_failure_owner"]
    )
    sections = [
        "# Bounded Task Handoff",
        "",
        f"- task_id: {packet['task_id']}",
        f"- goal: {packet['goal']}",
        f"- base_sha: {packet['base_sha']}",
        f"- current_node: {packet['current_node']}",
        f"- first_failure_owner: {owner}",
        f"- vertical_stage: {packet['vertical_stage']}",
        f"- supported_entry_command: {packet['supported_entry_command']}",
        f"- surface_objectives.refs: {json.dumps(packet['surface_objectives']['refs'], ensure_ascii=False)}",
        "",
        "## Git Snapshot",
        "",
        f"- repository_root: {snapshot['repository_root']}",
        f"- branch: {snapshot['branch'] if snapshot['branch'] is not None else 'null'}",
        f"- is_clean: {str(snapshot['is_clean']).lower()}",
        f"- status_short: {json.dumps(snapshot['status_short'], ensure_ascii=False)}",
        f"- staged_paths: {json.dumps(snapshot['staged_paths'], ensure_ascii=False)}",
        f"- unstaged_paths: {json.dumps(snapshot['unstaged_paths'], ensure_ascii=False)}",
        f"- untracked_paths: {json.dumps(snapshot['untracked_paths'], ensure_ascii=False)}",
        f"- target_commit: {target_text}",
    ]
    for heading, key in (
        ("Read First", "read_first"),
        ("Write Allowlist", "write_allowlist"),
        ("Protected Paths", "protected_paths"),
        ("Verification Commands", "verification_commands"),
        ("Done When", "done_when"),
        ("Stop When", "stop_when"),
        ("Out of Scope", "out_of_scope"),
    ):
        sections.extend(["", f"## {heading}", "", _markdown_list(packet[key])])
    return "\n".join(sections) + "\n"


def _atomic_runtime_write(
    root: Path, content: str, *, replace_active_packet: bool
) -> None:
    packet_dir_path = root / ".codex"
    packet_dir_path.mkdir(parents=True, exist_ok=True)
    packet_dir = packet_dir_path.resolve()
    try:
        packet_dir.relative_to(root)
    except ValueError as exc:
        raise InputError(
            "resolved .codex directory is outside the Git root"
        ) from exc
    target = packet_dir / "task-packet.json"
    target_exists = os.path.lexists(target)
    if target_exists and not replace_active_packet:
        raise InputError(
            "active implementation packet already exists; "
            "pass --replace-active-packet with --output to replace it"
        )
    if target_exists and not target.is_file():
        raise InputError("active implementation packet path is not a file")
    handle, temporary_name = tempfile.mkstemp(
        prefix=".task-packet-", suffix=".tmp", dir=packet_dir
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if replace_active_packet:
            os.replace(temporary, target)
        else:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise InputError(
                    "active implementation packet appeared during write; "
                    "replacement was refused"
                ) from exc
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one bounded task handoff from explicit input and Git facts."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--repo", default=Path("."), type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument(
        "--output",
        action="store_true",
        help="Atomically write the JSON packet to <git-root>/.codex/task-packet.json.",
    )
    parser.add_argument(
        "--replace-active-packet",
        action="store_true",
        help="With --output, replace the checkout's existing active packet.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    try:
        if arguments.replace_active_packet and not arguments.output:
            raise InputError("--replace-active-packet requires --output")
        inputs = _validate_input(_load_input(arguments.input))
        root, snapshot = _git_snapshot(
            arguments.repo.resolve(), inputs["target_commit"]
        )
        packet = _build_packet(inputs, snapshot)
        json_output = _json_text(packet)
        markdown_output = _markdown(packet)
        _validate_rendered_outputs(json_output, markdown_output)
        if arguments.output:
            _atomic_runtime_write(
                root,
                json_output,
                replace_active_packet=arguments.replace_active_packet,
            )
        output = json_output if arguments.format == "json" else markdown_output
        sys.stdout.write(output)
        return 0
    except (InputError, GitError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
