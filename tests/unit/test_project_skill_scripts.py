from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOUNDED_SCRIPT = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "bounded-task-handoff"
    / "scripts"
    / "build_handoff.py"
)
RELEASE_SCRIPT = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "release-evidence-packager"
    / "scripts"
    / "package_release_evidence.py"
)


def _load_bounded_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "project_bounded_task_handoff", BOUNDED_SCRIPT
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_release_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "project_release_evidence_packager", RELEASE_SCRIPT
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BOUNDED = _load_bounded_module()
RELEASE = _load_release_module()


def _run_git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
    )
    return completed.stdout.strip()


def _handoff_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "handoff-repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "skill-test@example.invalid")
    _run_git(repo, "config", "user.name", "Skill Test")
    (repo / "staged.txt").write_text("base\n", encoding="utf-8")
    (repo / "unstaged.txt").write_text("base\n", encoding="utf-8")
    _run_git(repo, "add", "staged.txt", "unstaged.txt")
    _run_git(repo, "commit", "-m", "base")
    head = _run_git(repo, "rev-parse", "HEAD")

    (repo / "staged.txt").write_text("staged change\n", encoding="utf-8")
    _run_git(repo, "add", "staged.txt")
    (repo / "unstaged.txt").write_text("unstaged change\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    return repo, head


def _handoff_input() -> dict[str, Any]:
    return {
        "schema_version": "bounded-task-handoff.v1",
        "task_id": "TASK-EXACT",
        "goal": "Deliver the explicitly selected behavior.",
        "read_first": ["explicit/read-first.py"],
        "write_allowlist": ["explicit/write-only.py"],
        "protected_paths": ["explicit/protected.md"],
        "verification_commands": [
            "python -m pytest tests/unit/test_exact.py"
        ],
        "done_when": ["The explicit focused check passes."],
        "stop_when": ["The first failure belongs to another owner."],
        "out_of_scope": ["Historical roadmap reconstruction."],
        "supported_entry_command": "python -m product exact-run",
        "current_node": "findings_admission",
        "first_failure_owner": "requirement_findings",
        "vertical_stage": "coverage",
        "surface_objectives": {"refs": ["objective:exact"]},
        "target_commit": None,
    }


def test_bounded_handoff_uses_explicit_scope_and_exact_git_snapshot(
    tmp_path: Path,
) -> None:
    repo, head = _handoff_repo(tmp_path)
    explicit = _handoff_input()

    validated = BOUNDED._validate_input(explicit)
    _, snapshot = BOUNDED._git_snapshot(repo, validated["target_commit"])
    packet = BOUNDED._build_packet(validated, snapshot)

    assert packet["base_sha"] == head
    assert packet["git_snapshot"]["is_clean"] is False
    assert packet["git_snapshot"]["staged_paths"] == ["staged.txt"]
    assert packet["git_snapshot"]["unstaged_paths"] == ["unstaged.txt"]
    assert packet["git_snapshot"]["untracked_paths"] == ["untracked.txt"]
    assert packet["read_first"] == explicit["read_first"]
    assert packet["write_allowlist"] == explicit["write_allowlist"]
    assert packet["protected_paths"] == explicit["protected_paths"]
    assert packet["surface_objectives"] == explicit["surface_objectives"]


def test_bounded_handoff_missing_and_unknown_fields_fail_closed() -> None:
    missing = _handoff_input()
    del missing["goal"]
    with pytest.raises(BOUNDED.InputError, match="missing fields: goal"):
        BOUNDED._validate_input(missing)

    unknown = _handoff_input()
    unknown["goal_alias"] = unknown["goal"]
    with pytest.raises(BOUNDED.InputError, match="unknown fields: goal_alias"):
        BOUNDED._validate_input(unknown)


def test_bounded_handoff_defaults_to_stdout_and_output_writes_only_packet(
    tmp_path: Path,
) -> None:
    repo, head = _handoff_repo(tmp_path)
    input_path = tmp_path / "handoff-input.json"
    input_path.write_text(json.dumps(_handoff_input()), encoding="utf-8")
    command = [
        sys.executable,
        "-B",
        str(BOUNDED_SCRIPT),
        "--input",
        str(input_path),
        "--repo",
        str(repo),
        "--format",
        "json",
    ]

    stdout_only = subprocess.run(
        command,
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
    )
    assert json.loads(stdout_only.stdout)["base_sha"] == head
    assert not (repo / ".codex").exists()

    persisted = subprocess.run(
        [*command, "--output"],
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
    )
    packet_path = repo / ".codex" / "task-packet.json"
    assert packet_path.is_file()
    assert json.loads(packet_path.read_text(encoding="utf-8")) == json.loads(
        persisted.stdout
    )
    assert {item.name for item in packet_path.parent.iterdir()} == {
        "task-packet.json"
    }
    first_packet = packet_path.read_bytes()

    second_input = _handoff_input()
    second_input["task_id"] = "TASK-DIFFERENT"
    second_input_path = tmp_path / "second-handoff-input.json"
    second_input_path.write_text(json.dumps(second_input), encoding="utf-8")
    second_command = [
        sys.executable,
        "-B",
        str(BOUNDED_SCRIPT),
        "--input",
        str(second_input_path),
        "--repo",
        str(repo),
        "--format",
        "json",
    ]
    refused = subprocess.run(
        [*second_command, "--output"],
        capture_output=True,
        check=False,
        encoding="utf-8",
        text=True,
    )
    assert refused.returncode == 2
    assert "--replace-active-packet" in refused.stderr
    assert packet_path.read_bytes() == first_packet
    assert {item.name for item in packet_path.parent.iterdir()} == {
        "task-packet.json"
    }

    replaced = subprocess.run(
        [*second_command, "--output", "--replace-active-packet"],
        capture_output=True,
        check=True,
        encoding="utf-8",
        text=True,
    )
    assert json.loads(replaced.stdout)["task_id"] == "TASK-DIFFERENT"
    assert json.loads(packet_path.read_text(encoding="utf-8"))["task_id"] == (
        "TASK-DIFFERENT"
    )


def test_bounded_handoff_input_and_complete_render_limits_fail_closed(
    tmp_path: Path,
) -> None:
    assert BOUNDED.MAX_TEXT_CHARACTERS == 320
    assert BOUNDED.MAX_LIST_ITEMS == 24
    assert BOUNDED.MAX_ESTIMATED_OUTPUT_TOKENS == 1_500

    long_text = _handoff_input()
    long_text["goal"] = "x" * (BOUNDED.MAX_TEXT_CHARACTERS + 1)
    with pytest.raises(BOUNDED.InputError, match="character limit"):
        BOUNDED._validate_input(long_text)

    long_list = _handoff_input()
    long_list["read_first"] = [
        f"explicit/path-{index}" for index in range(BOUNDED.MAX_LIST_ITEMS + 1)
    ]
    with pytest.raises(BOUNDED.InputError, match="item limit"):
        BOUNDED._validate_input(long_list)

    oversized_input = tmp_path / "oversized-input.json"
    oversized_input.write_bytes(b" " * (BOUNDED.MAX_INPUT_BYTES + 1))
    with pytest.raises(BOUNDED.InputError, match="input byte limit"):
        BOUNDED._load_input(oversized_input)

    validated = BOUNDED._validate_input(_handoff_input())
    snapshot = {
        "repository_root": "repo",
        "head_sha": "a" * 40,
        "branch": "main",
        "is_clean": False,
        "status_short": ["x" * 10_000],
        "staged_paths": [],
        "unstaged_paths": [],
        "untracked_paths": [],
        "target_commit": None,
    }
    packet = BOUNDED._build_packet(validated, snapshot)
    json_output = BOUNDED._json_text(packet)
    markdown_output = BOUNDED._markdown(packet)

    assert BOUNDED._estimated_token_count(json_output) > (
        BOUNDED.MAX_ESTIMATED_OUTPUT_TOKENS
    )
    assert BOUNDED._estimated_token_count(markdown_output) > (
        BOUNDED.MAX_ESTIMATED_OUTPUT_TOKENS
    )
    with pytest.raises(BOUNDED.InputError, match="rendered output limit"):
        BOUNDED._validate_rendered_outputs(json_output, markdown_output)


def _evidence(
    kind: str,
    *,
    evidence_id: str = "EVID-001",
    status: str = "verified",
    commit_sha: str | None = "abc123",
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "status": status,
        "summary": "Exact supplied observation.",
        "source_ref": "receipt:exact",
        "command": "python -m pytest tests/unit/test_exact.py",
        "commit_sha": commit_sha,
        "metrics": [],
    }


def _release_input(
    evidence: list[dict[str, Any]],
    *,
    claims: list[dict[str, Any]] | None = None,
    demo_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "release-evidence-input.v1",
        "release_id": "REL-001",
        "project_name": "Exact Project",
        "release_commit_evidence_id": None,
        "evidence": evidence,
        "claims": [] if claims is None else claims,
        "delivery_lines": [
            {
                "line_id": f"LINE-{index}",
                "label": f"Line {index}",
                "objective_refs": [f"objective:{index}"],
                "evidence_ids": [],
                "unknowns": [f"Unknown {index}"],
                "next_gate": f"Gate {index}",
            }
            for index in range(1, 6)
        ],
        "demo": {
            "duration_minutes": 4,
            "steps": [] if demo_steps is None else demo_steps,
        },
    }


@pytest.mark.parametrize("kind", ["test", "ci", "build", "runtime", "trace"])
def test_non_commit_evidence_retains_explicit_commit_sha(kind: str) -> None:
    validated = RELEASE._validate_evidence([_evidence(kind)])

    assert validated[0]["commit_sha"] == "abc123"


def test_commit_evidence_requires_commit_sha() -> None:
    with pytest.raises(RELEASE.InputError, match="commit_sha is required"):
        RELEASE._validate_evidence([_evidence("commit", commit_sha=None)])


@pytest.mark.parametrize(
    "existing_name",
    ["release_manifest.json", "release_evidence_draft.md"],
)
def test_existing_single_target_without_overwrite_changes_nothing(
    tmp_path: Path,
    existing_name: str,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = output_dir / "release_manifest.json"
    markdown = output_dir / "release_evidence_draft.md"
    existing = output_dir / existing_name
    existing.write_text("old output\n", encoding="utf-8")

    with pytest.raises(RELEASE.InputError, match="output exists"):
        RELEASE._write_output_pair(
            output_dir,
            "new manifest\n",
            "new markdown\n",
            overwrite=False,
        )

    assert existing.read_text(encoding="utf-8") == "old output\n"
    absent = markdown if existing == manifest else manifest
    assert not absent.exists()
    assert {item.name for item in output_dir.iterdir()} == {existing_name}


def test_second_output_commit_failure_restores_both_old_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = output_dir / "release_manifest.json"
    markdown = output_dir / "release_evidence_draft.md"
    manifest.write_text("old manifest\n", encoding="utf-8")
    markdown.write_text("old markdown\n", encoding="utf-8")
    real_replace = RELEASE.os.replace
    failed = False

    def fail_second_install(source: Any, target: Any) -> None:
        nonlocal failed
        source_path = Path(source)
        target_path = Path(target)
        if (
            not failed
            and target_path == markdown
            and source_path.name.startswith(".release_evidence_draft.md-")
        ):
            failed = True
            raise OSError("injected second install failure")
        real_replace(source, target)

    monkeypatch.setattr(RELEASE.os, "replace", fail_second_install)

    with pytest.raises(OSError, match="injected second install failure"):
        RELEASE._write_output_pair(
            output_dir,
            "new manifest\n",
            "new markdown\n",
            overwrite=True,
        )

    assert manifest.read_text(encoding="utf-8") == "old manifest\n"
    assert markdown.read_text(encoding="utf-8") == "old markdown\n"
    assert {item.name for item in output_dir.iterdir()} == {
        "release_evidence_draft.md",
        "release_manifest.json",
    }


def test_unsupported_claim_and_demo_step_remain_not_demonstrated() -> None:
    evidence = [
        _evidence("build", status="blocked", evidence_id="EVID-BUILD")
    ]
    raw = _release_input(
        evidence,
        claims=[
            {
                "claim_id": "CLAIM-BUILD",
                "statement": "Changed-product build passed.",
                "evidence_ids": ["EVID-BUILD"],
                "placements": ["results_table", "resume", "interview"],
            }
        ],
        demo_steps=[
            {
                "title": "Show build",
                "narration": "Present the build as successful.",
                "evidence_ids": ["EVID-BUILD"],
            }
        ],
    )

    manifest = RELEASE._build_manifest(RELEASE._validate(raw), "0" * 64)
    markdown = RELEASE._markdown(manifest)

    assert manifest["claims"][0]["status"] == "not_demonstrated"
    assert manifest["demo"]["steps"][0]["status"] == "not_demonstrated"
    assert "Present the build as successful." not in markdown


@pytest.mark.parametrize(
    ("bound_sha", "expected_status"),
    [("release-sha", "demonstrated"), ("old-sha", "not_demonstrated")],
)
def test_release_projections_require_exact_verified_release_commit_sha(
    bound_sha: str,
    expected_status: str,
) -> None:
    evidence = [
        _evidence(
            "commit",
            evidence_id="EVID-RELEASE",
            commit_sha="release-sha",
        ),
        _evidence("test", evidence_id="EVID-TEST", commit_sha=bound_sha),
    ]
    raw = _release_input(
        evidence,
        claims=[
            {
                "claim_id": "CLAIM-TEST",
                "statement": "Focused tests passed on the release revision.",
                "evidence_ids": ["EVID-TEST"],
                "placements": [
                    "results_table",
                    "demo_script",
                    "resume",
                    "interview",
                ],
            }
        ],
        demo_steps=[
            {
                "title": "Show release tests",
                "narration": "Show tests bound to the release revision.",
                "evidence_ids": ["EVID-TEST"],
            }
        ],
    )
    raw["release_commit_evidence_id"] = "EVID-RELEASE"
    raw["delivery_lines"][0]["evidence_ids"] = ["EVID-TEST"]

    manifest = RELEASE._build_manifest(RELEASE._validate(raw), "f" * 64)
    markdown = RELEASE._markdown(manifest)

    assert manifest["release_commit"]["status"] == "demonstrated"
    assert manifest["evidence_by_kind"]["test"]["status"] == expected_status
    assert manifest["claims"][0]["status"] == expected_status
    assert manifest["delivery_lines"][0]["evidence_status"] == expected_status
    assert manifest["demo"]["steps"][0]["status"] == expected_status
    assert "Source input SHA-256: " + ("f" * 64) in markdown
    assert (
        "Show tests bound to the release revision." in markdown
    ) is (expected_status == "demonstrated")
