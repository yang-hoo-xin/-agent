"""Tests for runtime acceptance evidence contracts."""

from __future__ import annotations

import pytest

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.runtime import (
    RuntimeEvidenceError,
    RuntimeEvidenceItem,
    build_runtime_failure_ownership,
    build_manual_runtime_evidence_payload,
    build_real_runtime_evidence_payload,
    build_supplied_runtime_evidence_payload,
    bind_runtime_evidence_context,
)


ACCEPTANCE_CRITERION = "Requested behavior is implemented: make Load enable diagnostics"
SECOND_ACCEPTANCE_CRITERION = "Diagnostic toggle keeps unrelated markers unchanged"
RUNTIME_PLAN_STEP = "acceptance_evidence_observed"
RUN_ID = "run_001"
BUILD_ARTIFACT_HASH = "sha256:build-artifact"
BUILD_ARTIFACT_REF = {
    "feature_id": "feature_001",
    "artifact_type": "build_result",
    "path": "features/feature_001/build_result.json",
    "artifact_hash": BUILD_ARTIFACT_HASH,
}
PLUGIN_MARKER_BINDING = {
    "marker_source": "runtime_probe",
    "markers": [
        {
            "marker": "BETTER_HIT_FEEDBACK_ACCEPTANCE_OK",
            "acceptance_criterion": ACCEPTANCE_CRITERION,
            "observed": True,
        }
    ],
}


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
    assert payload["run_id"] is None
    assert payload["build_artifact_hash"] is None
    assert payload["plugin_marker_binding"] == {}
    assert payload["screenshot_refs"] == []
    assert payload["runtime_trust_binding"] == {
        "status": "not_applicable",
        "checks": {},
        "blockers": [],
    }
    assert payload["failure_ownership"] == {
        "owner": "none",
        "failure_class": "none",
        "source_repair_allowed": False,
        "required_action": "none",
        "reason": "Runtime acceptance is verified.",
    }
    assert payload["non_goal_preservation"]["status"] == "not_checked"


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
    assert payload["failure_ownership"]["owner"] == "unknown"
    assert payload["failure_ownership"]["source_repair_allowed"] is False
    assert (
        payload["failure_ownership"]["required_action"]
        == "collect_failure_evidence"
    )
    assert payload["acceptance_contract"] == {
        "acceptance_criteria": [ACCEPTANCE_CRITERION],
        "runtime_verification_plan": [RUNTIME_PLAN_STEP],
    }


def test_runtime_failure_ownership_is_normalized_fail_closed() -> None:
    payload = build_supplied_runtime_evidence_payload(
        feature_id="feature_001",
        raw_supplied_output="Runtime output did not establish acceptance.",
        verification_status="failed",
        failure_ownership={
            "owner": "unsupported_owner",
            "failure_class": "forged_source_failure",
            "source_repair_allowed": True,
            "required_action": "repair_product_source",
            "reason": "Attempt to grant source authority.",
        },
    )

    assert payload["failure_ownership"] == {
        "owner": "unknown",
        "failure_class": "forged_source_failure",
        "source_repair_allowed": False,
        "required_action": "collect_failure_evidence",
        "reason": "Runtime evidence supplied an unsupported failure owner.",
    }


def test_explicit_product_behavior_failure_preserves_bounded_source_authority() -> None:
    ownership = build_runtime_failure_ownership(
        owner="product_behavior",
        failure_class="acceptance_behavior_failed",
        reason="A bound Runtime behavior emitted an explicit failure.",
    )
    payload = build_real_runtime_evidence_payload(
        feature_id="feature_001",
        input_execution_mode="local",
        evidence_items=(),
        startup_loaded=True,
        gameplay_behavior_verified=False,
        verification_status="failed",
        failure_ownership=ownership,
    )

    assert payload["failure_ownership"] == ownership
    assert payload["failure_ownership"]["source_repair_allowed"] is True


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
        run_id=RUN_ID,
        build_artifact_ref=BUILD_ARTIFACT_REF,
        build_artifact_hash=BUILD_ARTIFACT_HASH,
        plugin_marker_binding=PLUGIN_MARKER_BINDING,
        screenshot_refs=(
            {
                "screenshot_id": "shot_001",
                "artifact_ref": "screenshots/shot_001.png",
                "content_hash": "sha256:screenshot",
            },
        ),
        runtime_trust_binding={
            "status": "trusted",
            "checks": {"runtime_process_identity": {"status": "passed"}},
            "blockers": [],
        },
        non_goals_checked=(
            {
                "non_goal": SECOND_ACCEPTANCE_CRITERION,
                "preserved": True,
            },
        ),
    )

    assert payload["execution_mode"] == "real"
    assert payload["evidence_source"] == "real_runtime_probe"
    assert payload["real_runtime_performed"] is True
    assert payload["claims_real_runtime_success"] is True
    assert payload["acceptance_verified"] is True
    assert payload["run_id"] == RUN_ID
    assert payload["build_artifact_ref"] == BUILD_ARTIFACT_REF
    assert payload["build_artifact_hash"] == BUILD_ARTIFACT_HASH
    assert payload["plugin_marker_binding"] == PLUGIN_MARKER_BINDING
    assert payload["screenshot_refs"] == [
        {
            "screenshot_id": "shot_001",
            "artifact_ref": "screenshots/shot_001.png",
            "content_hash": "sha256:screenshot",
        }
    ]
    assert payload["runtime_trust_binding"] == {
        "status": "trusted",
        "checks": {"runtime_process_identity": {"status": "passed"}},
        "blockers": [],
    }
    assert payload["non_goal_preservation"] == {
        "status": "preserved",
        "checked": [
            {
                "non_goal": SECOND_ACCEPTANCE_CRITERION,
                "preserved": True,
            }
        ],
        "violations": [],
    }


def test_real_runtime_evidence_can_be_built_before_graph_binding() -> None:
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
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
    )

    assert payload["claims_real_runtime_success"] is True
    assert payload["run_id"] is None
    assert payload["build_artifact_hash"] is None
    assert payload["plugin_marker_binding"] == {}
    assert payload["runtime_trust_binding"]["status"] == "not_applicable"


def test_bind_runtime_evidence_context_records_run_and_build_artifact() -> None:
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
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        plugin_marker_binding=PLUGIN_MARKER_BINDING,
    )
    build_ref = ArtifactRef(
        feature_id="feature_001",
        artifact_type="build_result",
        path="features/feature_001/build_result.json",
        artifact_hash=BUILD_ARTIFACT_HASH,
    )

    bound = bind_runtime_evidence_context(
        payload,
        run_id=RUN_ID,
        build_artifact_ref=build_ref,
    )

    assert bound["run_id"] == RUN_ID
    assert bound["build_artifact_ref"] == BUILD_ARTIFACT_REF
    assert bound["build_artifact_hash"] == BUILD_ARTIFACT_HASH


def test_bind_runtime_evidence_context_completes_trust_binding() -> None:
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
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        plugin_marker_binding=PLUGIN_MARKER_BINDING,
        runtime_trust_binding={
            "status": "pending_graph_binding",
            "checks": {
                "feature_id": {"status": "passed"},
                "runtime_process_identity": {"status": "passed"},
                "current_run_logs": {"status": "passed"},
                "plugin_load_marker": {"status": "passed"},
                "acceptance_markers": {"status": "passed"},
                "screenshot_runtime_artifact_linkage": {"status": "passed"},
            },
            "blockers": [],
        },
    )
    build_ref = ArtifactRef(
        feature_id="feature_001",
        artifact_type="build_result",
        path="features/feature_001/build_result.json",
        artifact_hash=BUILD_ARTIFACT_HASH,
    )

    bound = bind_runtime_evidence_context(
        payload,
        run_id=RUN_ID,
        build_artifact_ref=build_ref,
    )

    assert bound["runtime_trust_binding"]["status"] == "trusted"
    assert bound["runtime_trust_binding"]["checks"]["run_id"] == {
        "status": "passed",
        "run_id": RUN_ID,
    }
    assert bound["runtime_trust_binding"]["checks"]["build_artifact_hash"] == {
        "status": "passed",
        "build_artifact_hash": BUILD_ARTIFACT_HASH,
        "build_artifact_ref_hash": BUILD_ARTIFACT_HASH,
    }


def test_bind_runtime_evidence_context_preserves_deployment_requirement() -> None:
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
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        plugin_marker_binding=PLUGIN_MARKER_BINDING,
        runtime_trust_binding={
            "status": "pending_graph_binding",
            "deployment_required": True,
            "checks": {
                "feature_id": {"status": "passed"},
                "runtime_process_identity": {"status": "passed"},
                "current_run_logs": {"status": "passed"},
                "plugin_load_marker": {"status": "passed"},
                "acceptance_markers": {"status": "passed"},
                "screenshot_runtime_artifact_linkage": {"status": "passed"},
                "deployed_plugin_artifact_hash": {"status": "passed"},
                "game_directory_restoration": {"status": "passed"},
            },
            "blockers": [],
        },
    )
    build_ref = ArtifactRef(
        feature_id="feature_001",
        artifact_type="build_result",
        path="features/feature_001/build_result.json",
        artifact_hash=BUILD_ARTIFACT_HASH,
    )

    bound = bind_runtime_evidence_context(
        payload,
        run_id=RUN_ID,
        build_artifact_ref=build_ref,
    )

    assert bound["runtime_trust_binding"]["deployment_required"] is True
    assert bound["runtime_trust_binding"]["status"] == "trusted"


def test_bind_runtime_evidence_context_preserves_operator_completion_requirement() -> None:
    payload = build_real_runtime_evidence_payload(
        feature_id="feature_001",
        input_execution_mode="local",
        evidence_items=(
            RuntimeEvidenceItem(
                item_type="manual_observation",
                source="gtfo_operator_completion",
                locator="sha256:operator-request",
                supports_acceptance=(ACCEPTANCE_CRITERION,),
                confidence=1.0,
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=(ACCEPTANCE_CRITERION,),
        runtime_verification_plan=(RUNTIME_PLAN_STEP,),
        plugin_marker_binding=PLUGIN_MARKER_BINDING,
        runtime_trust_binding={
            "status": "pending_graph_binding",
            "operator_completion_required": True,
            "checks": {
                "feature_id": {"status": "passed"},
                "runtime_process_identity": {"status": "passed"},
                "current_run_logs": {"status": "passed"},
                "plugin_load_marker": {"status": "passed"},
                "acceptance_markers": {"status": "passed"},
                "operator_completion": {"status": "passed"},
                "screenshot_runtime_artifact_linkage": {"status": "passed"},
            },
            "blockers": [],
        },
    )
    build_ref = ArtifactRef(
        feature_id="feature_001",
        artifact_type="build_result",
        path="features/feature_001/build_result.json",
        artifact_hash=BUILD_ARTIFACT_HASH,
    )

    bound = bind_runtime_evidence_context(
        payload,
        run_id=RUN_ID,
        build_artifact_ref=build_ref,
    )

    assert bound["runtime_trust_binding"]["operator_completion_required"] is True
    assert bound["runtime_trust_binding"]["checks"]["operator_completion"] == {
        "status": "passed"
    }
    assert bound["runtime_trust_binding"]["status"] == "trusted"
