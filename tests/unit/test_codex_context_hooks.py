from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = REPO_ROOT / ".codex" / "hooks" / "context_snapshot.py"
HOOKS_CONFIG_PATH = REPO_ROOT / ".codex" / "hooks.json"


def _load_hook_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "codex_context_snapshot_hook", HOOK_PATH
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


HOOK = _load_hook_module()


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
    )


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "codex-hook-test@example.invalid")
    _git(repo, "config", "user.name", "Codex Hook Test")
    (repo / ".gitignore").write_text(
        ".codex/.runtime/\n.codex/task-packet.json\n",
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("original\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "tracked.txt")
    _git(repo, "commit", "-m", "seed")
    return repo


def _pre_compact_input(repo: Path, *, session_id: str = "session-001") -> dict[str, Any]:
    return {
        "session_id": session_id,
        "transcript_path": str(repo / "must-not-be-read.jsonl"),
        "cwd": str(repo),
        "hook_event_name": "PreCompact",
        "turn_id": "turn-001",
        "trigger": "auto",
    }


def _session_start_input(
    repo: Path, *, session_id: str = "session-001", source: str = "compact"
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "transcript_path": str(repo / "must-not-be-read.jsonl"),
        "cwd": str(repo),
        "hook_event_name": "SessionStart",
        "source": source,
    }


def _snapshot_path(repo: Path, session_id: str = "session-001") -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return repo / ".codex" / ".runtime" / "context-snapshots" / f"{digest}.json"


def _write_snapshot(repo: Path, session_id: str = "session-001") -> dict[str, Any]:
    result = HOOK.dispatch(
        "pre_compact",
        _pre_compact_input(repo, session_id=session_id),
        expected_root=repo,
    )
    assert result == {"continue": True}
    path = _snapshot_path(repo, session_id)
    assert path.is_file()
    return json.loads(path.read_text(encoding="utf-8"))


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = set(value)
        for child in value.values():
            result.update(_all_keys(child))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in value:
            result.update(_all_keys(child))
        return result
    return set()


def test_pre_compact_records_clean_and_dirty_git_state(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    clean_snapshot = _write_snapshot(repo)
    assert clean_snapshot["git"]["dirty"] is False
    assert clean_snapshot["git"]["status"] == []

    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    dirty_snapshot = _write_snapshot(repo)
    assert dirty_snapshot["git"]["dirty"] is True
    assert dirty_snapshot["git"]["status"] == [" M tracked.txt"]
    assert dirty_snapshot["git"]["status_count"] == 1


def test_snapshot_is_deterministic_and_does_not_read_transcript(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    first = _write_snapshot(repo)
    first_bytes = _snapshot_path(repo).read_bytes()
    second = _write_snapshot(repo)

    assert first == second
    assert _snapshot_path(repo).read_bytes() == first_bytes
    assert "transcript_path" not in json.dumps(first)


def test_explicit_task_packet_is_whitelisted_with_point_line_surface_refs(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    packet_path = repo / ".codex" / "task-packet.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(
        json.dumps(
            {
                "task_id": "HOOK-V0",
                "goal": "Restore bounded context",
                "current_node": "implement_context_hook",
                "first_failure_owner": "context_snapshot_dispatcher",
                "vertical_stage": "focused_verification",
                "surface_objectives": {"refs": ["ACTIVE_PRODUCT_CONTRACT#1.1"]},
                "write_allowlist": [".codex/hooks/**"],
                "done_when": ["Focused tests pass"],
                "stop_when": ["The task exceeds the write allowlist"],
                "readiness": "must-not-propagate",
                "artifact": {"must": "not-propagate"},
            }
        ),
        encoding="utf-8",
    )

    snapshot = _write_snapshot(repo)
    packet = snapshot["task_packet"]

    assert packet["current_node"] == "implement_context_hook"
    assert packet["first_failure_owner"] == "context_snapshot_dispatcher"
    assert packet["vertical_stage"] == "focused_verification"
    assert packet["surface_objectives"] == {
        "refs": ["ACTIVE_PRODUCT_CONTRACT#1.1"]
    }
    assert packet["done_when"] == ["Focused tests pass"]
    assert packet["stop_when"] == ["The task exceeds the write allowlist"]
    assert "readiness" not in _all_keys(snapshot)
    assert "artifact" not in _all_keys(snapshot)


def test_session_start_returns_bounded_official_additional_context(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    _write_snapshot(repo)

    result = HOOK.dispatch(
        "session_start", _session_start_input(repo), expected_root=repo
    )

    assert result["continue"] is True
    specific = result["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    context = specific["additionalContext"]
    assert "codex_context_snapshot_v0" in context
    assert '"source": "compact"' in context
    assert HOOK._estimated_tokens(context) <= HOOK.MAX_CONTEXT_TOKENS_ESTIMATE
    json.dumps(result)


def test_context_budget_keeps_write_protection_and_stop_fields(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    packet_path = repo / ".codex" / "task-packet.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(
        json.dumps(
            {
                "task_id": "BOUNDED-CONTEXT",
                "write_allowlist": ["src/exact_owner.py"],
                "protected_paths": ["docs/user-wip.md"],
                "stop_when": ["The verified owner changes."],
                "goal": "界" * 320,
                "read_first": [f"界{index}" * 160 for index in range(24)],
                "verification_commands": [
                    f"python -m pytest tests/unit/test_{index}.py"
                    for index in range(24)
                ],
                "surface_objectives": {
                    "refs": [f"objective:{index}" for index in range(24)]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_snapshot(repo)

    result = HOOK.dispatch(
        "session_start", _session_start_input(repo), expected_root=repo
    )
    context = result["hookSpecificOutput"]["additionalContext"]
    serialized = context.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    restored = json.loads(serialized)

    assert restored["task_packet"]["write_allowlist"] == [
        "src/exact_owner.py"
    ]
    assert restored["task_packet"]["protected_paths"] == [
        "docs/user-wip.md"
    ]
    assert restored["task_packet"]["stop_when"] == [
        "The verified owner changes."
    ]
    assert restored["task_packet_truncated_fields"]
    assert HOOK._estimated_tokens(context) <= HOOK.MAX_CONTEXT_TOKENS_ESTIMATE


@pytest.mark.parametrize("source", ["compact", "resume"])
def test_session_start_accepts_only_bound_snapshot_for_same_session(
    tmp_path: Path, source: str
) -> None:
    repo = _make_repo(tmp_path)
    _write_snapshot(repo, session_id="bound-session")

    matching = HOOK.dispatch(
        "session_start",
        _session_start_input(repo, session_id="bound-session", source=source),
        expected_root=repo,
    )
    other_session = HOOK.dispatch(
        "session_start",
        _session_start_input(repo, session_id="other-session", source=source),
        expected_root=repo,
    )

    assert "hookSpecificOutput" in matching
    assert other_session == {"continue": True}


def test_pre_compact_keeps_independent_snapshots_for_multiple_sessions(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)

    first = _write_snapshot(repo, session_id="session-first")
    (repo / "tracked.txt").write_text("second session state\n", encoding="utf-8")
    second = _write_snapshot(repo, session_id="session-second")

    first_path = _snapshot_path(repo, "session-first")
    second_path = _snapshot_path(repo, "session-second")
    assert first_path != second_path
    assert json.loads(first_path.read_text(encoding="utf-8")) == first
    assert json.loads(second_path.read_text(encoding="utf-8")) == second
    assert first["git"]["dirty"] is False
    assert second["git"]["dirty"] is True


def test_corrupt_snapshot_is_ignored_without_overwrite(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    path = _snapshot_path(repo)
    path.parent.mkdir(parents=True)
    corrupt = b"{not-json\n"
    path.write_bytes(corrupt)

    result = HOOK.dispatch(
        "session_start", _session_start_input(repo), expected_root=repo
    )

    assert result == {"continue": True}
    assert path.read_bytes() == corrupt


def test_no_git_repo_and_non_target_repo_are_no_write(tmp_path: Path) -> None:
    no_git = tmp_path / "no-git"
    no_git.mkdir()
    assert HOOK.dispatch(
        "pre_compact", _pre_compact_input(no_git), expected_root=no_git
    ) == {"continue": True}
    assert not (no_git / ".codex").exists()

    expected_repo = _make_repo(tmp_path, "expected")
    other_repo = _make_repo(tmp_path, "other")
    assert HOOK.dispatch(
        "pre_compact", _pre_compact_input(other_repo), expected_root=expected_repo
    ) == {"continue": True}
    assert not _snapshot_path(expected_repo).exists()
    assert not _snapshot_path(other_repo).exists()


def test_traversal_like_session_id_cannot_change_state_path(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    outside = tmp_path / "escaped.json"

    _write_snapshot(repo, session_id="../../escaped.json")

    assert _snapshot_path(repo, "../../escaped.json").is_file()
    assert not outside.exists()


def test_pre_compact_writes_only_ignored_runtime_snapshot(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    tracked_before = (repo / "tracked.txt").read_bytes()
    files_before = {
        path.relative_to(repo).as_posix()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }

    _write_snapshot(repo)

    files_after = {
        path.relative_to(repo).as_posix()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    snapshot_relative = _snapshot_path(repo).relative_to(repo).as_posix()
    assert files_after - files_before == {snapshot_relative}
    assert (repo / "tracked.txt").read_bytes() == tracked_before
    assert _git(repo, "status", "--short").stdout == ""


def test_cli_main_reads_stdin_and_emits_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make_repo(tmp_path)
    hook_input = _pre_compact_input(repo)
    monkeypatch.setattr(HOOK, "_script_repo_root", lambda: repo)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))

    assert HOOK.main(["pre_compact"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"continue": True}
    assert _snapshot_path(repo).is_file()


def test_pre_compact_reports_snapshot_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(HOOK, "_atomic_write_json", lambda *_args: False)

    result = HOOK.dispatch(
        "pre_compact", _pre_compact_input(repo), expected_root=repo
    )

    assert result == {
        "continue": True,
        "systemMessage": (
            "Codex context snapshot could not be saved; compaction will "
            "continue without a new snapshot."
        ),
    }
    assert not _snapshot_path(repo).exists()


def test_hooks_json_has_only_synchronous_v0_events_and_stable_root_commands() -> None:
    configuration = json.loads(HOOKS_CONFIG_PATH.read_text(encoding="utf-8"))
    hooks = configuration["hooks"]

    assert set(hooks) == {"PreCompact", "SessionStart"}
    assert hooks["PreCompact"][0]["matcher"] == "^(manual|auto)$"
    assert hooks["SessionStart"][0]["matcher"] == "^(compact|resume)$"

    for event_groups in hooks.values():
        handler = event_groups[0]["hooks"][0]
        assert handler["type"] == "command"
        assert "async" not in handler
        assert "git rev-parse --show-toplevel" in handler["command"]
        assert "git rev-parse --show-toplevel" in handler["commandWindows"]
        assert handler["timeout"] == 10

    session_handler = hooks["SessionStart"][0]["hooks"][0]
    assert session_handler["additionalContextLimit"] == 1200
    assert "additionalContextLimit" not in hooks["PreCompact"][0]["hooks"][0]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows hook command")
def test_windows_hook_command_executes_from_repository_subdirectory(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    hook_dir = repo / ".codex" / "hooks"
    hook_dir.mkdir(parents=True)
    shutil.copy2(HOOK_PATH, hook_dir / "context_snapshot.py")
    subdirectory = repo / "nested"
    subdirectory.mkdir()
    configuration = json.loads(HOOKS_CONFIG_PATH.read_text(encoding="utf-8"))
    command = configuration["hooks"]["PreCompact"][0]["hooks"][0][
        "commandWindows"
    ]

    completed = subprocess.run(
        command,
        cwd=subdirectory,
        input=json.dumps(_pre_compact_input(repo)),
        capture_output=True,
        check=False,
        encoding="utf-8",
        shell=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"continue": True}
    assert _snapshot_path(repo).is_file()
