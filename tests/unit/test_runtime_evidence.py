"""Tests for runtime acceptance evidence contracts."""

from __future__ import annotations

import pytest

from src.mod_agent.runtime import (
    RuntimeEvidenceError,
    RuntimeEvidenceItem,
    build_manual_runtime_evidence_payload,
    build_real_runtime_evidence_payload,
    build_supplied_runtime_evidence_payload,
)


ACCEPTANCE_CRITERION = "Requested behavior is implemented: make Load enable diagnostics"
SECOND_ACCEPTANCE_CRITERION = "Diagnostic toggle keeps unrelated markers unchanged"
RUNTIME_PLAN_STEP = "acceptance_evidence_observed"


def test_manual_runtime_evidence_verifies_matching_acceptance_contract() -> None:
    payload = build_manual_runtime_evidence_payload(
        feature_id="feature_001",
        evidence_items=(
            RuntimeEvidenceItem(
                item_type="manual_note",
                source="tester",
                locator="manual://run-001",
                supports_acceptance=(ACCEPTANCE_CRITERION,),
                confidence=1.0,
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
    )

    assert payload["execution_mode"] == "manual"
    assert payload["acceptance_verified"] is True
    assert payload["acceptance_status"] == "accepted"
    assert payload["claims_real_runtime_success"] is True
    assert payload["real_runtime_performed"] is False
    assert payload["acceptance_contract"] == {
        "acceptance_criteria": [ACCEPTANCE_CRITERION],
        "runtime_verification_plan": [RUNTIME_PLAN_STEP],
    }


def test_supplied_runtime_evidence_rejects_unmatched_acceptance_contract() -> None:
    with pytest.raises(RuntimeEvidenceError, match="every acceptance criterion"):
        build_supplied_runtime_evidence_payload(
            feature_id="feature_001",
            raw_supplied_output="Game loaded and unrelated behavior was observed.",
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="log_excerpt",
                    source="supplied_log",
                    locator="logs/run.log:12",
                    supports_acceptance=("Unrelated behavior was observed.",),
                    confidence=1.0,
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            acceptance_criteria=(ACCEPTANCE_CRITERION,),
            runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        )


def test_manual_runtime_evidence_rejects_partial_acceptance_contract() -> None:
    with pytest.raises(RuntimeEvidenceError, match="every acceptance criterion"):
        build_manual_runtime_evidence_payload(
            feature_id="feature_001",
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="manual_note",
                    source="tester",
                    locator="manual://run-001",
                    supports_acceptance=(ACCEPTANCE_CRITERION,),
                    confidence=1.0,
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            acceptance_criteria=(
                ACCEPTANCE_CRITERION,
                SECOND_ACCEPTANCE_CRITERION,
            ),
            runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        )


def test_supplied_runtime_evidence_keeps_contract_when_unverified() -> None:
    payload = build_supplied_runtime_evidence_payload(
        feature_id="feature_001",
        raw_supplied_output="Startup log did not show target behavior.",
        evidence_items=(),
        startup_loaded=True,
        gameplay_behavior_verified=False,
        verification_status="inconclusive",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
    )

    assert payload["execution_mode"] == "supplied_output"
    assert payload["acceptance_verified"] is False
    assert payload["acceptance_status"] == "inconclusive"
    assert payload["claims_real_runtime_success"] is False
    assert payload["acceptance_contract"] == {
        "acceptance_criteria": [ACCEPTANCE_CRITERION],
        "runtime_verification_plan": [RUNTIME_PLAN_STEP],
    }


def test_real_runtime_evidence_can_verify_full_acceptance_contract() -> None:
    payload = build_real_runtime_evidence_payload(
        feature_id="feature_001",
        input_execution_mode="local",
        evidence_items=(
            RuntimeEvidenceItem(
                item_type="runtime_log",
                source="runtime_probe",
                locator="runtime://probe-001",
                supports_acceptance=(ACCEPTANCE_CRITERION,),
                confidence=1.0,
                raw_excerpt="Runtime probe observed the diagnostic behavior.",
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        raw_runtime_output="Runtime probe observed the diagnostic behavior.",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
    )

    assert payload["execution_mode"] == "real"
    assert payload["evidence_source"] == "real_runtime_probe"
    assert payload["real_runtime_performed"] is True
    assert payload["claims_real_runtime_success"] is True
    assert payload["acceptance_verified"] is True
