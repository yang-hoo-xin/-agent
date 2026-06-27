"""Phase A smoke tests for the Controlled Mod Agent CLI."""

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
