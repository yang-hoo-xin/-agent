from __future__ import annotations

import ast
import inspect
import json
import textwrap
from argparse import Namespace
from collections.abc import Callable
from typing import Any

import pytest

from src.mod_agent import cli
from src.mod_agent.local_entry import LocalEntryError


def _preflight_args() -> Namespace:
    return Namespace(
        run_root="run-root",
        artifact_store_root="shared-store",
        feature_id="feature_001",
        checkpoint_path="checkpoint.json",
        checkpoint_hash="a" * 64,
        resume_id="resume_001",
        recover_accepted_resume=False,
        retry_runtime_observation=True,
        runtime_output_root="runtime-output",
        settings="runtime.yaml",
        runtime_plugin_destination="plugin.dll",
    )


def _resume_args() -> Namespace:
    return Namespace(
        **vars(_preflight_args()),
        approved_by="human",
        allow_game_launch=True,
        allow_game_directory_write=True,
    )


def _public_result(disposition: object) -> dict[str, Any]:
    return {
        "verification_operation_result": {
            "execution_disposition": disposition,
        },
        # Deliberately conflict with the public disposition. These legacy fields
        # remain printable but must not influence the process exit.
        "current_stage": "blocked",
        "runtime_summary": {"claims_real_runtime_success": False},
        "audit_snapshot": {
            "store_file_count": 999,
            "pending": ["display-only"],
            "locator": "display-only",
        },
    }


@pytest.mark.parametrize(
    ("disposition", "expected_exit"),
    [
        ("succeeded", 0),
        ("domain_blocked", 1),
        ("operator_input_required", 1),
        ("platform_blocked", 2),
        ("partial", 2),
        ("unknown", 2),
        (None, 2),
    ],
)
def test_runtime_execute_cli_adapter_uses_only_public_execution_disposition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    disposition: object,
    expected_exit: int,
) -> None:
    result = _public_result(disposition)
    monkeypatch.setattr(cli, "resume_local_runtime", lambda **_: result)

    exit_code = cli._run_resume_runtime_command(_resume_args())

    assert exit_code == expected_exit
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize(
    ("result", "expected_exit"),
    [
        ({"status": "READY_FOR_RUNTIME_PROFILE"}, 0),
        ({"status": "READY_FOR_EXTERNAL_AUTHORIZATION"}, 0),
        ({"status": "BLOCKED"}, 2),
        ({}, 2),
        ({"verification_operation_preflight_result": {"preflight_status": "ready"}}, 2),
        ({"verification_operation_preflight_result": {}}, 2),
        ({"verification_operation_preflight_result": None}, 2),
    ],
)
def test_legacy_runtime_preflight_cli_accepts_only_advisory_result_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: dict[str, Any],
    expected_exit: int,
) -> None:
    monkeypatch.setattr(cli, "preflight_local_runtime", lambda **_: result)

    assert cli._run_preflight_runtime_command(_preflight_args()) == expected_exit
    assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize(
    ("result", "expected_exit"),
    [
        (
            {"verification_operation_preflight_result": {"preflight_status": "ready"}},
            0,
        ),
        (
            {"verification_operation_preflight_result": {"preflight_status": "blocked"}},
            2,
        ),
        ({"verification_operation_preflight_result": {}}, 2),
        ({"status": "READY_FOR_RUNTIME_PROFILE"}, 2),
        ({}, 2),
    ],
)
def test_execution_grade_preflight_exit_requires_structured_result(
    result: object,
    expected_exit: int,
) -> None:
    assert cli._verification_preflight_exit_code(result) == expected_exit


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"verification_operation_result": None},
        {"verification_operation_result": {}},
        {"verification_operation_result": {"execution_disposition": 0}},
    ],
)
def test_runtime_cli_adapter_fails_closed_without_exact_structured_result(
    result: object,
) -> None:
    assert cli._verification_operation_exit_code(result) == 2


def test_preflight_runtime_adapter_prepares_legacy_parameters_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "preflight_local_runtime",
        lambda **kwargs: captured.append(kwargs)
        or {"status": "READY_FOR_RUNTIME_PROFILE"},
    )

    assert cli._run_preflight_runtime_command(_preflight_args()) == 0
    json.loads(capsys.readouterr().out)
    assert captured == [
        {
            "run_root": "run-root",
            "artifact_store_root": "shared-store",
            "feature_id": "feature_001",
            "checkpoint_path": "checkpoint.json",
            "checkpoint_hash": "a" * 64,
            "resume_id": "resume_001",
            "recover_accepted_resume": False,
            "retry_runtime_observation": True,
            "runtime_output_root": "runtime-output",
            "settings_path": "runtime.yaml",
            "runtime_plugin_destination": "plugin.dll",
        }
    ]


def test_resume_runtime_adapter_prepares_legacy_parameters_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "resume_local_runtime",
        lambda **kwargs: captured.append(kwargs) or _public_result("succeeded"),
    )

    assert cli._run_resume_runtime_command(_resume_args()) == 0
    json.loads(capsys.readouterr().out)
    assert captured == [
        {
            "run_root": "run-root",
            "artifact_store_root": "shared-store",
            "feature_id": "feature_001",
            "checkpoint_path": "checkpoint.json",
            "checkpoint_hash": "a" * 64,
            "resume_id": "resume_001",
            "recover_accepted_resume": False,
            "retry_runtime_observation": True,
            "runtime_output_root": "runtime-output",
            "approved_by": "human",
            "settings_path": "runtime.yaml",
            "allow_game_launch": True,
            "runtime_plugin_destination": "plugin.dll",
            "allow_game_directory_write": True,
        }
    ]


@pytest.mark.parametrize(
    ("helper_name", "public_name", "args_factory", "command"),
    [
        (
            "_run_preflight_runtime_command",
            "preflight_local_runtime",
            _preflight_args,
            "preflight-runtime",
        ),
        (
            "_run_resume_runtime_command",
            "resume_local_runtime",
            _resume_args,
            "resume-runtime",
        ),
    ],
)
def test_runtime_cli_adapter_presents_public_errors_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    helper_name: str,
    public_name: str,
    args_factory: Callable[[], Namespace],
    command: str,
) -> None:
    invocation_count = 0

    def fail(**_: object) -> dict[str, Any]:
        nonlocal invocation_count
        invocation_count += 1
        raise LocalEntryError("blocked by public operation")

    monkeypatch.setattr(cli, public_name, fail)

    assert getattr(cli, helper_name)(args_factory()) == 2
    payload = json.loads(capsys.readouterr().out)
    assert invocation_count == 1
    assert payload["command"] == command
    assert payload["status"] == "BLOCKED"


def _helper_syntax(helper: Callable[..., int]) -> ast.AST:
    return ast.parse(textwrap.dedent(inspect.getsource(helper)))


def test_only_registered_runtime_cli_helpers_are_scanned_for_adapter_authority(
) -> None:
    migrated_helpers = (
        cli._run_preflight_runtime_command,
        cli._run_resume_runtime_command,
    )
    assert tuple(helper.__name__ for helper in migrated_helpers) == (
        "_run_preflight_runtime_command",
        "_run_resume_runtime_command",
    )

    forbidden_symbols = {
        "ArtifactStore",
        "WorkflowCheckpointStore",
        "build_graph",
        "hash_action_identity",
        "list_feature_artifact_revisions",
        "project_verification_operation",
        "write",
        "write_with_result",
    }
    forbidden_verdict_inputs = {
        "claims_real_build_success",
        "claims_real_runtime_success",
        "current_stage",
        "runtime_summary",
    }
    for helper in migrated_helpers:
        tree = _helper_syntax(helper)
        referenced = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        string_literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert referenced.isdisjoint(forbidden_symbols)
        assert string_literals.isdisjoint(forbidden_verdict_inputs)
        assert not any(
            isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree)
        )


def test_main_only_dispatches_runtime_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        cli,
        "_run_preflight_runtime_command",
        lambda _: calls.append("preflight") or 7,
    )
    monkeypatch.setattr(
        cli,
        "_run_resume_runtime_command",
        lambda _: calls.append("resume") or 8,
    )

    assert (
        cli.main(
            [
                "preflight-runtime",
                "--run-root",
                "run-root",
                "--feature-id",
                "feature_001",
                "--checkpoint-path",
                "checkpoint.json",
                "--checkpoint-hash",
                "a" * 64,
            ]
        )
        == 7
    )
    assert (
        cli.main(
            [
                "resume-runtime",
                "--run-root",
                "run-root",
                "--feature-id",
                "feature_001",
                "--checkpoint-path",
                "checkpoint.json",
                "--checkpoint-hash",
                "a" * 64,
                "--approved-by",
                "human",
                "--runtime-plugin-destination",
                "plugin.dll",
            ]
        )
        == 8
    )
    assert calls == ["preflight", "resume"]
