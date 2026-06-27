"""Tests for the Phase A permission model."""

from __future__ import annotations

import pytest

from src.mod_agent.tools.permissions import PermissionModel


def test_read_only_is_allowed() -> None:
    decision = PermissionModel().decide("read_only")

    assert decision.allowed is True
    assert decision.level == "read_only"
    assert decision.reason
    assert decision.required_approval is None


def test_report_only_is_allowed() -> None:
    decision = PermissionModel().decide("report_only")

    assert decision.allowed is True
    assert decision.level == "report_only"
    assert decision.reason


def test_dry_run_write_requires_explicit_phase() -> None:
    decision = PermissionModel().decide("dry_run_write")

    assert decision.allowed is False
    assert decision.level == "dry_run_write"
    assert decision.required_approval == "explicit_phase"


def test_dry_run_write_allowed_with_explicit_phase() -> None:
    decision = PermissionModel().decide("dry_run_write", explicit_phase="A4")

    assert decision.allowed is True
    assert decision.level == "dry_run_write"


def test_confirmed_write_is_blocked_by_default() -> None:
    decision = PermissionModel().decide("confirmed_write")

    assert decision.allowed is False
    assert decision.level == "confirmed_write"
    assert decision.required_approval == "human_approval"
    assert "blocked by default" in decision.reason


def test_external_side_effect_is_blocked_by_default() -> None:
    decision = PermissionModel().decide("external_side_effect")

    assert decision.allowed is False
    assert decision.level == "external_side_effect"
    assert decision.required_approval == "human_approval"


def test_unknown_permission_level_raises() -> None:
    with pytest.raises(ValueError, match="Unknown permission level"):
        PermissionModel().decide("dangerous")  # type: ignore[arg-type]
