"""Phase A smoke tests for the Evidence-Grounded Controlled Code Generation Agent Platform CLI."""

from __future__ import annotations

import json

import pytest

from src.mod_agent import __version__
from src.mod_agent.cli import main, plan_request


def test_mod_agent_package_imports() -> None:
    """The new platform package is importable through the repository package root."""

    assert __version__


def test_plan_request_returns_stubbed_result() -> None:
    """Phase A request planning is explicitly stubbed."""

    result = plan_request("make enemies glow")

    assert result.status == "stubbed"
    assert result.command == "plan-request"
    assert result.request == "make enemies glow"


def test_cli_plan_request_prints_stubbed_json(capsys: pytest.CaptureFixture[str]) -> None:
    """The minimal CLI prints a structured placeholder response."""

    exit_code = main(["plan-request", "test"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "stubbed"
    assert payload["command"] == "plan-request"
    assert payload["request"] == "test"


def test_cli_confirmed_apply_is_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    """Confirmed writes are blocked in Phase A."""

    exit_code = main(["apply-patch", "--confirm"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "BLOCKED"
    assert payload["command"] == "apply-patch"
    assert payload["confirmed"] is True


def test_cli_run_request_blocks_before_target_access_without_source_disclosure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "run-request",
            "change local source",
            "--target-project",
            "missing-target",
            "--confirm-isolated-write",
            "--allow-build",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert "--allow-source-disclosure" in payload["reason"]


def test_cli_does_not_treat_non_real_success_status_as_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_local_request",
        lambda **_: {
            "build_summary": {
                "status": "success",
                "claims_real_build_success": False,
            }
        },
    )

    exit_code = main(
        [
            "run-request",
            "change local source",
            "--target-project",
            "target",
            "--allow-source-disclosure",
            "--confirm-isolated-write",
            "--allow-build",
        ]
    )

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["build_summary"][
        "claims_real_build_success"
    ] is False
