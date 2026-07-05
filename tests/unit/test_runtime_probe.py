"""Tests for local runtime probe launching and log collection."""

from __future__ import annotations

import sys

import pytest

from src.mod_agent.runtime import (
    RuntimeProbeError,
    RuntimeProbeProfile,
    RuntimeProbeRunner,
)


ACCEPTANCE_CRITERION = "Requested behavior is implemented: make Load enable diagnostics"
SECOND_ACCEPTANCE_CRITERION = "Diagnostic toggle keeps unrelated markers unchanged"
RUNTIME_PLAN_STEP = "acceptance_evidence_observed"
STARTUP_MARKER = "MOD_AGENT_STARTUP_OK"
ACCEPTANCE_MARKER = "MOD_AGENT_ACCEPTANCE_OK"
SECOND_ACCEPTANCE_MARKER = "MOD_AGENT_SECOND_ACCEPTANCE_OK"


def test_runtime_probe_subprocess_verifies_acceptance_contract(tmp_path) -> None:
    profile = RuntimeProbeProfile(
        profile_id="local_probe",
        working_directory=str(tmp_path),
        command=(
            sys.executable,
            "-c",
            (
                "print('MOD_AGENT_STARTUP_OK'); "
                "print('MOD_AGENT_ACCEPTANCE_OK'); "
                "print('MOD_AGENT_SECOND_ACCEPTANCE_OK')"
            ),
        ),
        timeout_seconds=10,
        startup_markers=(STARTUP_MARKER,),
        acceptance_markers={
            ACCEPTANCE_CRITERION: ACCEPTANCE_MARKER,
            SECOND_ACCEPTANCE_CRITERION: SECOND_ACCEPTANCE_MARKER,
        },
    )

    payload = RuntimeProbeRunner().run_local(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION, SECOND_ACCEPTANCE_CRITERION),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_execution=True,
    )

    assert payload["execution_mode"] == "real"
    assert payload["evidence_source"] == "real_runtime_probe"
    assert payload["real_runtime_performed"] is True
    assert payload["startup_loaded"] is True
    assert payload["gameplay_behavior_verified"] is True
    assert payload["verification_status"] == "verified"
    assert payload["acceptance_verified"] is True
    assert payload["claims_real_runtime_success"] is True
    assert {
        criterion
        for item in payload["evidence_items"]
        for criterion in item["supports_acceptance"]
    } == {ACCEPTANCE_CRITERION, SECOND_ACCEPTANCE_CRITERION}


def test_runtime_probe_missing_marker_is_inconclusive(tmp_path) -> None:
    profile = RuntimeProbeProfile(
        profile_id="local_probe",
        working_directory=str(tmp_path),
        command=(sys.executable, "-c", "print('MOD_AGENT_STARTUP_OK')"),
        timeout_seconds=10,
        startup_markers=(STARTUP_MARKER,),
        acceptance_markers={ACCEPTANCE_CRITERION: ACCEPTANCE_MARKER},
    )

    payload = RuntimeProbeRunner().run_local(
        feature_id="feature_001",
        profile=profile,
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        input_execution_mode="local",
        allow_execution=True,
    )

    assert payload["execution_mode"] == "real"
    assert payload["real_runtime_performed"] is True
    assert payload["startup_loaded"] is True
    assert payload["gameplay_behavior_verified"] is False
    assert payload["verification_status"] == "inconclusive"
    assert payload["acceptance_verified"] is False
    assert payload["claims_real_runtime_success"] is False
    assert payload["evidence_items"] == []
    assert "Runtime probe output did not contain every configured acceptance marker." in payload[
        "limitations"
    ]


def test_runtime_probe_requires_explicit_execution_approval(tmp_path) -> None:
    profile = RuntimeProbeProfile(
        profile_id="local_probe",
        working_directory=str(tmp_path),
        command=(sys.executable, "-c", "print('MOD_AGENT_STARTUP_OK')"),
        timeout_seconds=10,
    )

    with pytest.raises(RuntimeProbeError, match="explicit approval"):
        RuntimeProbeRunner().run_local(
            feature_id="feature_001",
            profile=profile,
            acceptance_criteria=(ACCEPTANCE_CRITERION,),
            runtime_verification_plan=(RUNTIME_PLAN_STEP,),
            input_execution_mode="local",
            allow_execution=False,
        )
