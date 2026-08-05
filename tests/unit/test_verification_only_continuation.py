from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import shutil
from pathlib import Path
from threading import Barrier, Event, Thread, local
from types import SimpleNamespace
from typing import Any

import pytest
import src.mod_agent.artifacts.store as artifact_store_module
import src.mod_agent.local_entry as local_entry_module
import src.mod_agent.workflow.graph as workflow_graph_module

from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactWriteResult,
)
from src.mod_agent.build import (
    BuildAdapter,
    BuildCommandResult,
    BuildProfile,
    BuildResult,
    build_fake_build_result,
)
from src.mod_agent.workflow import (
    ResumeDecision,
    ResumePayload,
    ResumeValidator,
    VerificationOnlyContinuationInput,
    WorkflowCheckpointStore,
    build_graph,
    create_initial_state,
    preflight_verification_only_continuation,
    resumed_state_from_decision,
)
from src.mod_agent.verification_operations import (
    RUNTIME_EXECUTION_CONTRACT_VERSION,
    RUNTIME_EXECUTION_KIND,
    RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
    RUNTIME_TERMINALIZATION_KIND,
    VERIFICATION_BUILD_CONTRACT_VERSION,
    VERIFICATION_BUILD_KIND,
    BuildInvocationProtocolBindingV1,
    EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
    EVIDENCE_CONSOLIDATION_KIND,
    EvidenceConsolidationOperationV1,
    EvidenceConsolidationResultV1,
    ImplementationEvidenceFileBinding,
    InitialAttemptV1,
    NewRuntimeResumeProtocolBindingV1,
    RuntimeExecutionOperationV1,
    RuntimeTerminalizationOperationV1,
    VerificationAttemptPolicy,
    VerificationBuildOperationV1,
    VerificationCheckpointIdentityV1,
    VerificationOperationPreflightResultV1,
    VerificationOperationResultV1,
    VerificationOperationSpec,
    VerificationProtocolBinding,
    project_verification_operation,
)
from src.mod_agent.workflow.verification_only import (
    verification_only_lineage_payload,
)
from src.mod_agent.runtime import (
    RuntimeEvidenceItem,
    build_fake_runtime_evidence_payload,
    build_real_runtime_evidence_payload,
)
from src.mod_agent.runtime_evidence_consolidation import (
    runtime_evidence_consolidation_child_refs,
)
from src.mod_agent.workflow.graph import _run_workflow_summary
from src.mod_agent.local_entry import (
    LocalEntryError,
    execute_verification_only_build_continuation,
    preflight_local_runtime,
    preflight_verification_only_build_continuation,
    resume_local_runtime,
)


FEATURE_ID = "feature_verification_only_001"
USER_REQUEST = "Verify the existing implementation without changing source."
TARGET_MOD = "BetterHitFeedback"
HANDOFF_CODE = "VERIFICATION_ONLY_FRESH_LINEAGE_HANDOFF_UNSUPPORTED"
RUNTIME_ADMISSION = {
    "status": "admitted",
    "authorization_scope": "this_resume_only",
    "requested_side_effects": ["runtime_execution"],
    "authorized_side_effects": ["runtime_execution"],
    "provider": "injected_test",
}


def _build_verification_operation(
    continuation: VerificationOnlyContinuationInput,
):
    return project_verification_operation(
        VerificationOperationSpec(
            operation_kind=VERIFICATION_BUILD_KIND,
            operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=BuildInvocationProtocolBindingV1(
                run_id="verification_only_run_001",
                request_id="verification_only_request_001",
            ),
            variant_payload=VerificationBuildOperationV1(
                feature_spec_ref=continuation.feature_spec_ref,
                evidence_pack_ref=continuation.evidence_pack_ref,
                user_request=USER_REQUEST,
                target_domain="gtfo",
                target_mod=TARGET_MOD,
            ),
        )
    )


def _runtime_workflow_operation(
    *,
    checkpoint_ref: ArtifactRef,
    checkpoint: dict[str, object],
):
    return project_verification_operation(
        VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=NewRuntimeResumeProtocolBindingV1(
                checkpoint_ref=checkpoint_ref,
                resume_id="verification_only_resume_001",
                approved_by="human",
            ),
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope="runtime_workflow",
                runtime_action_scope=RUNTIME_ADMISSION,
            ),
        ),
        checkpoint_identity=VerificationCheckpointIdentityV1(
            checkpoint_id=str(checkpoint["checkpoint_id"]),
            run_id=str(checkpoint["run_id"]),
            request_id=str(checkpoint["request_id"]),
        ),
    )


def test_preflight_is_deterministic_and_performs_no_write(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    before = _store_snapshot(store.root)

    first = _preflight(store, continuation)
    second = _preflight(store, continuation)

    assert first == second
    assert first["status"] == "ready_for_build_authorization"
    assert first["source_lineage"]["all_files_verified"] is True
    assert first["writes_performed"] is False
    assert first["artifact_writes_performed"] is False
    assert first["build_invoked"] is False
    assert _store_snapshot(store.root) == before


def test_public_build_preflight_never_probes_store_or_invokes_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    before = _store_snapshot(store.root)
    calls = {"probe": 0}

    def forbidden_probe(*_args, **_kwargs) -> None:
        calls["probe"] += 1
        raise AssertionError("No-write public preflight must not probe Store writes.")

    monkeypatch.setattr(ArtifactStore, "preflight_atomic_commit", forbidden_probe)
    first = preflight_verification_only_build_continuation(
        **_public_build_arguments(store, continuation)
    )
    second = preflight_verification_only_build_continuation(
        **_public_build_arguments(store, continuation)
    )

    assert first == second
    assert first["status"] == "ready_for_build_authorization"
    assert first["build_invoked"] is False
    assert calls["probe"] == 0
    assert _store_snapshot(store.root) == before


def test_public_build_orders_graph_admission_probe_factory_and_returns_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    original_probe = ArtifactStore.preflight_atomic_commit
    events: list[str] = []

    def recording_probe(selected: ArtifactStore, **kwargs) -> None:
        events.append("store_preflight")
        original_probe(selected, **kwargs)

    base_factory = _real_build_factory(tmp_path)

    def factory(feature_id: str, input_execution_mode: str | None) -> BuildResult:
        events.append("caller_factory")
        return base_factory(feature_id, input_execution_mode)

    monkeypatch.setattr(ArtifactStore, "preflight_atomic_commit", recording_probe)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=factory,
        allow_build_execution=True,
    )

    assert events == ["store_preflight", "caller_factory"]
    assert result["status"] == "completed"
    assert result["failure_stage"] is None
    assert result["handoff_ready"] is True
    assert result["build_execution"]["factory_invocation_count"] == 1
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"]["resume_preflight"]["allowed"] is True

    checkpoint_ref = ArtifactRef(**result["workflow_checkpoint"]["artifact_ref"])
    checkpoint = store.read(checkpoint_ref)["data"]
    checkpoint_build_summary = checkpoint["state_snapshot"]["build_summary"]
    assert "build_result_store_result" not in checkpoint_build_summary
    assert "workflow_checkpoint_store_result" not in checkpoint_build_summary


def test_public_build_probe_failure_stops_before_caller_and_store_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    calls = {"factory": 0}

    def failed_probe(*_args, **_kwargs) -> None:
        raise ArtifactStoreError("probe failed")

    def factory(_feature_id: str, _mode: str | None) -> BuildResult:
        calls["factory"] += 1
        raise AssertionError("Caller factory must not run after probe failure.")

    monkeypatch.setattr(ArtifactStore, "preflight_atomic_commit", failed_probe)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=factory,
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "store_preflight"
    assert result["build_execution"]["factory_invocation_count"] == 0
    assert result["build_execution"]["side_effects_may_have_started"] is False
    assert result["build_result"] is None
    assert result["workflow_checkpoint"] is None
    assert calls["factory"] == 0
    assert store.list_feature_artifact_revisions(FEATURE_ID, "build_result") == []


def test_public_build_authorization_and_admission_fail_before_store_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    calls = {"probe": 0, "factory": 0}

    def forbidden_probe(*_args, **_kwargs) -> None:
        calls["probe"] += 1
        raise AssertionError("Blocked execution must not probe Store writes.")

    def forbidden_factory(_feature_id: str, _mode: str | None) -> BuildResult:
        calls["factory"] += 1
        raise AssertionError("Blocked execution must not invoke the factory.")

    monkeypatch.setattr(ArtifactStore, "preflight_atomic_commit", forbidden_probe)
    unauthorized = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=forbidden_factory,
        allow_build_execution=False,
    )
    assert unauthorized["status"] == "blocked"
    assert unauthorized["failure_stage"] == "authorization"

    source_root = Path(
        store.read(continuation.feature_spec_ref)["data"]["source_lineage"]["root"]
    )
    (source_root / "Plugin.cs").write_text("drifted", encoding="utf-8")
    inadmissible = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=forbidden_factory,
        allow_build_execution=True,
    )
    assert inadmissible["status"] == "blocked"
    assert inadmissible["failure_stage"] == "admission"
    assert calls == {"probe": 0, "factory": 0}


def test_public_build_graph_admission_drift_stops_without_blocked_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    before = _store_snapshot(store.root)
    original_preflight = workflow_graph_module.preflight_verification_only_continuation

    def blocked_graph_preflight(*args, **kwargs):
        report = original_preflight(*args, **kwargs)
        return {
            **report,
            "status": "blocked",
            "blockers": [
                {
                    "code": "VERIFICATION_INPUT_DRIFT",
                    "message": "Input identity changed before Graph admission.",
                }
            ],
        }

    monkeypatch.setattr(
        workflow_graph_module,
        "preflight_verification_only_continuation",
        blocked_graph_preflight,
    )
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "admission"
    assert result["build_execution"]["factory_invocation_count"] == 0
    assert result["build_result"] is None
    assert result["workflow_checkpoint"] is None
    assert _store_snapshot(store.root) == before


def test_public_build_factory_exception_reports_possible_side_effects_without_receipt(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)

    def failed_factory(_feature_id: str, _mode: str | None) -> BuildResult:
        raise OSError("runner failed")

    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=failed_factory,
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "build_execution"
    assert result["build_execution"]["factory_invocation_count"] == 1
    assert result["build_execution"]["side_effects_may_have_started"] is True
    assert result["build_result"] is None
    assert result["workflow_checkpoint"] is None


def test_public_build_post_build_drift_blocks_before_store_receipt(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    base_factory = _real_build_factory(tmp_path)
    source_root = Path(
        store.read(continuation.feature_spec_ref)["data"]["source_lineage"]["root"]
    )

    def drifting_factory(
        feature_id: str,
        input_execution_mode: str | None,
    ) -> BuildResult:
        result = base_factory(feature_id, input_execution_mode)
        (source_root / "Plugin.cs").write_text("drifted", encoding="utf-8")
        return result

    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=drifting_factory,
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "post_build_validation"
    assert result["build_execution"]["factory_invocation_count"] == 1
    assert result["build_result"] is None
    assert result["workflow_checkpoint"] is None


def test_public_build_post_build_preflight_exception_is_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    before = _store_snapshot(store.root)
    original_preflight = workflow_graph_module.preflight_verification_only_continuation
    graph_preflight_calls = 0

    def selected_graph_preflight(*args, **kwargs):
        nonlocal graph_preflight_calls
        graph_preflight_calls += 1
        if graph_preflight_calls == 3:
            raise OSError("post-Build source read failed")
        return original_preflight(*args, **kwargs)

    monkeypatch.setattr(
        workflow_graph_module,
        "preflight_verification_only_continuation",
        selected_graph_preflight,
    )
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert graph_preflight_calls == 3
    assert result["status"] == "blocked"
    assert result["failure_stage"] == "post_build_validation"
    assert result["build_execution"]["factory_invocation_count"] == 1
    assert result["build_execution"]["side_effects_may_have_started"] is True
    assert result["build_result"] is None
    assert result["workflow_checkpoint"] is None
    assert _store_snapshot(store.root) == before


@pytest.mark.parametrize(
    ("store_outcome", "expected_status"),
    (("blocked_before_commit", "blocked"), ("partial", "partial")),
)
def test_public_build_preserves_build_result_store_outcome_without_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_outcome: str,
    expected_status: str,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    original_write = ArtifactStore.write_with_result

    def selected_write(selected: ArtifactStore, **kwargs) -> ArtifactWriteResult:
        if kwargs["artifact_type"] == "build_result":
            return _store_failure_result(
                selected,
                artifact_type="build_result",
                outcome=store_outcome,
            )
        return original_write(selected, **kwargs)

    monkeypatch.setattr(ArtifactStore, "write_with_result", selected_write)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == expected_status
    assert result["failure_stage"] == "build_result_store"
    assert result["build_result"]["artifact_ref"] is None
    assert result["build_result"]["store_result"]["outcome"] == store_outcome
    assert result["workflow_checkpoint"] is None
    assert result["handoff_ready"] is False
    assert result["automatic_retry_count"] == 0
    assert result["recovery_performed"] is False


def test_public_build_exposes_real_filesystem_partial_without_driver_reinterpretation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    original_write = ArtifactStore._write_text_atomic

    def fail_build_latest(
        selected: ArtifactStore,
        path: Path,
        content: str,
        *,
        capture_replace_error: bool = False,
    ) -> None:
        if path == selected._artifact_path(FEATURE_ID, "build_result"):
            raise OSError("injected latest alias failure")
        original_write(
            selected,
            path,
            content,
            capture_replace_error=capture_replace_error,
        )

    monkeypatch.setattr(ArtifactStore, "_write_text_atomic", fail_build_latest)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    store_result = result["build_result"]["store_result"]
    assert result["status"] == "partial"
    assert result["failure_stage"] == "build_result_store"
    assert store_result["outcome"] == "partial"
    assert store_result["commit_started"] is True
    assert store_result["revision_state"] == "valid"
    assert store_result["pending_marker_state"] == "present"
    assert store_result["recovery_available"] is True
    assert Path(store_result["revision_path"]).is_file()
    assert Path(store_result["pending_marker_path"]).is_file()
    assert result["workflow_checkpoint"] is None


@pytest.mark.parametrize(
    ("store_outcome", "expected_status"),
    (("blocked_before_commit", "blocked"), ("partial", "partial")),
)
def test_public_build_preserves_checkpoint_store_outcome_after_build_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store_outcome: str,
    expected_status: str,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    original_write = ArtifactStore.write_with_result

    def selected_write(selected: ArtifactStore, **kwargs) -> ArtifactWriteResult:
        if kwargs["artifact_type"] == "workflow_checkpoint":
            return _store_failure_result(
                selected,
                artifact_type="workflow_checkpoint",
                outcome=store_outcome,
            )
        return original_write(selected, **kwargs)

    monkeypatch.setattr(ArtifactStore, "write_with_result", selected_write)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == expected_status
    assert result["failure_stage"] == "checkpoint_store"
    assert result["build_result"]["artifact_ref"] is not None
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"]["artifact_ref"] is None
    assert result["workflow_checkpoint"]["store_result"]["outcome"] == store_outcome
    assert result["handoff_ready"] is False


def test_public_build_keeps_committed_failed_domain_result_separate_from_store(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_failed_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == "completed"
    assert result["failure_stage"] is None
    assert result["build_execution"]["domain_status"] == "failed"
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"] is None
    assert result["handoff_ready"] is False


def test_public_build_success_without_real_success_claim_is_not_handoff_ready(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    base_factory = _real_build_factory(tmp_path)

    def unclaimed_factory(
        feature_id: str,
        input_execution_mode: str | None,
    ) -> BuildResult:
        return dataclasses.replace(
            base_factory(feature_id, input_execution_mode),
            claims_real_build_success=False,
        )

    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=unclaimed_factory,
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "handoff_eligibility"
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"] is None


def test_public_build_checkpoint_prewrite_failure_preserves_build_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)

    def failed_checkpoint(*_args, **_kwargs) -> ArtifactWriteResult:
        raise ArtifactStoreError("checkpoint prewrite failed")

    monkeypatch.setattr(
        WorkflowCheckpointStore,
        "create_checkpoint_with_result",
        failed_checkpoint,
    )
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "checkpoint_prewrite"
    assert result["build_result"]["artifact_ref"] is not None
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"] is None


def test_public_build_normalizes_non_store_checkpoint_prewrite_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)

    def invalid_checkpoint_payload(*_args, **_kwargs):
        raise ValueError("checkpoint payload invalid")

    monkeypatch.setattr(
        WorkflowCheckpointStore,
        "_checkpoint_write_arguments",
        invalid_checkpoint_payload,
    )
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "checkpoint_prewrite"
    assert result["build_result"]["artifact_ref"] is not None
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"] is None


def test_public_build_committed_checkpoint_with_blocked_resume_is_not_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)

    def blocked_resume(*_args, **_kwargs):
        return SimpleNamespace(
            status="blocked",
            allowed=False,
            reason="checkpoint is not resumable",
            blockers=({"code": "BLOCKED", "message": "blocked"},),
        )

    monkeypatch.setattr(WorkflowCheckpointStore, "preflight_resume", blocked_resume)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "checkpoint_resume_preflight"
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"]["resume_preflight"]["allowed"] is False
    assert result["handoff_ready"] is False


def test_public_build_resume_preflight_exception_preserves_committed_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)

    def failed_resume_preflight(*_args, **_kwargs):
        raise OSError("checkpoint read failed")

    monkeypatch.setattr(
        WorkflowCheckpointStore,
        "preflight_resume",
        failed_resume_preflight,
    )
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "checkpoint_resume_preflight"
    assert result["build_result"]["artifact_ref"] is not None
    assert result["build_result"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"]["artifact_ref"] is not None
    assert result["workflow_checkpoint"]["store_result"]["outcome"] == "committed"
    assert result["workflow_checkpoint"]["resume_preflight"] is None
    assert result["handoff_ready"] is False
    assert result["automatic_retry_count"] == 0
    assert result["recovery_performed"] is False
    assert {
        blocker["code"] for blocker in result["blockers"]
    } >= {"VERIFICATION_CHECKPOINT_RESUME_PREFLIGHT_FAILED"}


def test_preflight_blocks_stale_feature_lineage(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    prior = store.read(continuation.feature_spec_ref)
    newer_payload = copy.deepcopy(prior["data"])
    newer_payload["message"] = "A newer FeatureSpec revision."
    store.write(
        feature_id=FEATURE_ID,
        artifact_type="feature_spec",
        payload=newer_payload,
        status="success",
    )

    report = _preflight(store, continuation)

    assert report["status"] == "blocked"
    assert {item["code"] for item in report["blockers"]} >= {
        "VERIFICATION_ARTIFACT_INVALID",
        "VERIFICATION_INPUT_NOT_LATEST",
    }


def test_preflight_blocks_changed_source_bytes(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    feature = store.read(continuation.feature_spec_ref)["data"]
    source_root = Path(feature["source_lineage"]["root"])
    (source_root / "Plugin.cs").write_text("changed", encoding="utf-8")

    report = _preflight(store, continuation)

    assert report["status"] == "blocked"
    assert "VERIFICATION_SOURCE_HASH_MISMATCH" in {
        item["code"] for item in report["blockers"]
    }


def test_preflight_blocks_non_latest_evidence_pack(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    envelope = store.read(continuation.evidence_pack_ref)
    payload = copy.deepcopy(envelope["data"])
    payload["message"] = "Newer reviewed verification evidence."
    store.write(
        feature_id=FEATURE_ID,
        artifact_type="evidence_pack",
        payload=payload,
        status="blocked",
        blockers=list(payload["blockers"]),
        trace_refs=list(payload["trace_refs"]),
        upstream_refs=[continuation.feature_spec_ref],
    )

    report = _preflight(store, continuation)

    assert report["status"] == "blocked"
    assert "VERIFICATION_INPUT_NOT_LATEST" in {
        item["code"] for item in report["blockers"]
    }


def test_preflight_blocks_unreviewed_evidence_disposition(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    envelope = store.read(continuation.evidence_pack_ref)
    payload = copy.deepcopy(envelope["data"])
    payload["blockers"] = [
        {"code": "UNRELATED_BLOCKER", "message": "Different reason."}
    ]
    replacement = store.write(
        feature_id=FEATURE_ID,
        artifact_type="evidence_pack",
        payload=payload,
        status="blocked",
        blockers=list(payload["blockers"]),
        trace_refs=list(payload["trace_refs"]),
        upstream_refs=[continuation.feature_spec_ref],
    )

    report = _preflight(
        store,
        VerificationOnlyContinuationInput(
            feature_spec_ref=continuation.feature_spec_ref,
            evidence_pack_ref=replacement,
        ),
    )

    assert report["status"] == "blocked"
    assert "VERIFICATION_HANDOFF_DISPOSITION_INVALID" in {
        item["code"] for item in report["blockers"]
    }


def test_build_contract_requires_complete_verification_upstreams(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    payload = build_fake_build_result(
        feature_id=FEATURE_ID,
        input_execution_mode="verification_only",
    ).to_artifact_payload()

    with pytest.raises(
        ArtifactStoreError,
        match="requires only one exact FeatureSpec and one exact EvidencePack",
    ):
        store.write(
            feature_id=FEATURE_ID,
            artifact_type="build_result",
            payload=payload,
            status="success",
            upstream_refs=[continuation.feature_spec_ref],
        )


def test_build_contract_rejects_mixed_lineage_in_both_directions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    monkeypatch.setattr(
        store,
        "_validate_immutable_upstream_ref",
        lambda *, feature_id, upstream: None,
    )
    fake_dry_run = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="dry_run_result",
        path=str(tmp_path / "not-read.json"),
        artifact_hash="0" * 64,
    )
    before = len(store.list_feature_artifact_revisions(FEATURE_ID, "build_result"))
    verification_payload = build_fake_build_result(
        feature_id=FEATURE_ID,
        input_execution_mode="verification_only",
    ).to_artifact_payload()
    verification_payload["verification_only_lineage"] = (
        verification_only_lineage_payload(_preflight(store, continuation))
    )

    with pytest.raises(ArtifactStoreError, match="requires only one exact"):
        store.write(
            feature_id=FEATURE_ID,
            artifact_type="build_result",
            payload=verification_payload,
            status="success",
            upstream_refs=[
                continuation.feature_spec_ref,
                continuation.evidence_pack_ref,
                fake_dry_run,
            ],
        )

    mutation_payload = build_fake_build_result(
        feature_id=FEATURE_ID,
        input_execution_mode="fake",
    ).to_artifact_payload()
    with pytest.raises(ArtifactStoreError, match="requires dry_run_result"):
        store.write(
            feature_id=FEATURE_ID,
            artifact_type="build_result",
            payload=mutation_payload,
            status="success",
            upstream_refs=[
                continuation.feature_spec_ref,
                continuation.evidence_pack_ref,
            ],
        )

    assert len(store.list_feature_artifact_revisions(FEATURE_ID, "build_result")) == before


def test_graph_builds_from_exact_verification_lineage_and_stops(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    graph = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        verification_operation=_build_verification_operation(continuation),
    )

    result = graph.invoke(_initial_state())

    assert result["current_stage"] == "build"
    assert result["build_summary"]["input_execution_mode"] == "verification_only"
    assert "implementation_plan" not in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    assert "proposal_review" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    build_ref = _state_ref(result, "build_result")
    build_envelope = store.read(build_ref)
    assert {
        item["artifact_type"]
        for item in build_envelope["inputs"]["upstream_artifacts"]
    } == {"feature_spec", "evidence_pack"}
    assert build_envelope["data"]["input_execution_mode"] == "verification_only"
    checkpoint_ref = _state_ref(result, "workflow_checkpoint")
    decision = WorkflowCheckpointStore(store).preflight_resume(checkpoint_ref)
    assert decision.allowed is True


def test_graph_blocks_build_result_identity_drift_without_artifact_write(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    calls = {"count": 0}

    def wrong_factory(feature_id: str, input_execution_mode: str | None) -> BuildResult:
        calls["count"] += 1
        valid = _real_build_factory(tmp_path)(feature_id, input_execution_mode)
        return BuildResult(
            **{
                **valid.__dict__,
                "input_execution_mode": "mutation",
            }
        )

    graph = build_graph(
        store,
        build_result_factory=wrong_factory,
        verification_operation=_build_verification_operation(continuation),
    )

    result = graph.invoke(_initial_state())

    assert calls["count"] == 1
    assert result["build_summary"]["status"] == "blocked"
    assert "build_result" not in result["artifacts"]
    assert "workflow_checkpoint" not in result["artifacts"]
    assert store.list_feature_artifact_revisions(FEATURE_ID, "build_result") == []


def test_graph_blocks_source_drift_during_build_before_artifact_write(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    source_root = Path(
        store.read(continuation.feature_spec_ref)["data"]["source_lineage"]["root"]
    )
    valid_factory = _real_build_factory(tmp_path)

    def drifting_factory(
        feature_id: str,
        input_execution_mode: str | None,
    ) -> BuildResult:
        result = valid_factory(feature_id, input_execution_mode)
        (source_root / "Plugin.cs").write_text("drifted", encoding="utf-8")
        return result

    result = build_graph(
        store,
        build_result_factory=drifting_factory,
        verification_operation=_build_verification_operation(continuation),
    ).invoke(_initial_state())

    assert result["build_summary"]["status"] == "blocked"
    assert {item["code"] for item in result["blockers"]} >= {
        "VERIFICATION_BUILD_INPUT_DRIFT"
    }
    assert "build_result" not in result["artifacts"]
    assert "workflow_checkpoint" not in result["artifacts"]
    assert store.list_feature_artifact_revisions(FEATURE_ID, "build_result") == []


def test_graph_blocks_build_that_did_not_consume_admitted_source(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    unrelated_root = tmp_path / "unrelated_build"
    output = unrelated_root / "bin" / "BetterHitFeedback.dll"

    def unbound_factory(
        feature_id: str,
        input_execution_mode: str | None,
    ) -> BuildResult:
        def runner(_: BuildProfile) -> BuildCommandResult:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"unbound build")
            return BuildCommandResult(exit_code=0, stdout="Build succeeded")

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="unbound_verification_test",
                build_system="dotnet",
                working_directory=str(unrelated_root),
                command=("dotnet", "build"),
                timeout_seconds=120,
                expected_artifacts=("bin/BetterHitFeedback.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    result = build_graph(
        store,
        build_result_factory=unbound_factory,
        verification_operation=_build_verification_operation(continuation),
    ).invoke(_initial_state())

    assert result["build_summary"]["status"] == "blocked"
    assert "VERIFICATION_BUILD_SOURCE_FILE_MISSING" in {
        item["code"] for item in result["blockers"]
    }
    assert "build_result" not in result["artifacts"]
    assert store.list_feature_artifact_revisions(FEATURE_ID, "build_result") == []


def test_fresh_process_runtime_reuses_verification_build_without_mutation_chain(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    build_graph_instance = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        verification_operation=_build_verification_operation(continuation),
    )
    build_state = build_graph_instance.invoke(_initial_state())
    checkpoint_ref = _state_ref(build_state, "workflow_checkpoint")
    checkpoint = store.read(checkpoint_ref)["data"]
    checkpoint_store = WorkflowCheckpointStore(store)
    decision, resume_ref = checkpoint_store.resume(
        checkpoint_ref,
        _resume_payload(checkpoint),
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_ref,
    )

    runtime_graph = build_graph(
        store,
        runtime_evidence_factory=_runtime_payload,
        verification_operation=_runtime_workflow_operation(
            checkpoint_ref=checkpoint_ref,
            checkpoint=checkpoint,
        ),
    )
    result = runtime_graph.invoke(resumed_state)

    assert result["current_stage"] == "done"
    assert "repair_plan" not in result["artifacts"]
    assert "implementation_plan" not in result["artifacts"]
    evaluation = store.read(_state_ref(result, "eval_report"))["data"]
    assert evaluation["evaluation_gate"]["continuation_mode"] == "verification_only"
    assert {
        item["case_id"] for item in evaluation["evaluation_gate"]["cases"]
    } >= {"verification_only_continuation"}
    assert {
        item["case_id"] for item in evaluation["evaluation_gate"]["cases"]
    }.isdisjoint({"review_correctness", "dry_run_safety"})


def test_inconclusive_verification_runtime_stops_without_repair_planner(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    build_state = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        verification_operation=_build_verification_operation(continuation),
    ).invoke(_initial_state())
    checkpoint_ref = _state_ref(build_state, "workflow_checkpoint")
    checkpoint = store.read(checkpoint_ref)["data"]
    decision, resume_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        _resume_payload(checkpoint),
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_ref,
    )

    result = build_graph(
        store,
        runtime_evidence_factory=_unverified_runtime_payload,
        verification_operation=_runtime_workflow_operation(
            checkpoint_ref=checkpoint_ref,
            checkpoint=checkpoint,
        ),
    ).invoke(resumed_state)

    assert result["current_stage"] == "blocked"
    assert "runtime_evidence" in result["artifacts"]
    assert "repair_plan" not in result["artifacts"]
    assert "eval_report" not in result["artifacts"]
    assert "blocked_report" in result["artifacts"]


def test_eval_lineage_failure_never_claims_real_success(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    build_state = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        verification_operation=_build_verification_operation(continuation),
    ).invoke(_initial_state())
    checkpoint_ref = _state_ref(build_state, "workflow_checkpoint")
    checkpoint = store.read(checkpoint_ref)["data"]
    decision, resume_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        _resume_payload(checkpoint),
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_ref,
    )
    resumed_state["artifacts"]["dry_run_result"] = "not-used.json"
    resumed_state["artifact_hashes"]["dry_run_result"] = "0" * 64

    result = build_graph(
        store,
        runtime_evidence_factory=_verified_runtime_payload,
        verification_operation=_runtime_workflow_operation(
            checkpoint_ref=checkpoint_ref,
            checkpoint=checkpoint,
        ),
    ).invoke(resumed_state)

    evaluation = store.read(_state_ref(result, "eval_report"))["data"]
    assert result["current_stage"] == "blocked"
    assert evaluation["evaluation_gate"]["status"] == "failed"
    assert evaluation["verdict"] == "blocked"
    assert evaluation["claims_real_success"] is False
    assert evaluation["workflow_completion_status"] == "evaluation_blocked"
    assert evaluation["requested_behavior_status"] == "not_verified"
    assert evaluation["v1_acceptance_status"] == "accepted"

    summary_state = _run_workflow_summary(result, store)
    summary = store.read(_state_ref(summary_state, "workflow_summary"))["data"]
    assert summary["final_status"] == "blocked"
    assert summary["claims_real_mod_success"] is False
    assert summary["next_required_evidence"]


def test_verification_only_configuration_keeps_build_runtime_authority_separate(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    operation = _build_verification_operation(continuation)

    with pytest.raises(ValueError, match="come from its declaration"):
        build_graph(
            store,
            build_result_factory=_real_build_factory(tmp_path),
            verification_operation=operation,
            stop_after_build=True,
        )

    with pytest.raises(ValueError, match="come from its declaration"):
        build_graph(
            store,
            build_result_factory=_real_build_factory(tmp_path),
            verification_operation=operation,
            interrupt_after=["collect_runtime_evidence"],
        )


def test_public_build_handoff_enters_manifest_free_runtime_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    calls = {"probe": 0, "factory": 0}

    def forbidden_probe(*_args, **_kwargs) -> None:
        calls["probe"] += 1
        raise AssertionError("Runtime preflight must not probe Store writes.")

    monkeypatch.setattr(ArtifactStore, "preflight_atomic_commit", forbidden_probe)
    arguments = _runtime_preflight_arguments(
        store,
        build_result,
        runtime_root=runtime_root,
    )
    first = preflight_local_runtime(**arguments)
    second = preflight_local_runtime(**arguments)

    assert first == second
    assert first["status"] == "READY_FOR_RUNTIME_EXECUTION"
    assert first["runtime_execution_identity"] == second[
        "runtime_execution_identity"
    ]
    assert first["runtime_execution_identity_hash"] == second[
        "runtime_execution_identity_hash"
    ]
    structured = first["verification_operation_preflight_result"]
    assert structured["preflight_status"] == "ready"
    assert structured["identity_resolution_status"] == "identity_resolved"
    assert structured["envelope"] is not None
    assert (
        structured["approval_identity_hash"]
        == first["runtime_execution_identity_hash"]
    )
    assert first["manifest_required"] is False
    assert first["writes_performed"] is False
    assert calls == {"probe": 0, "factory": 0}
    assert not (runtime_root / "run_manifest.json").exists()


def test_runtime_execution_identity_excludes_run_root_and_binds_action(
    tmp_path: Path,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    first_root = tmp_path / "runtime-a"
    second_root = tmp_path / "runtime-b"
    first_root.mkdir()
    second_root.mkdir()
    first = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=first_root,
        )
    )
    same_action = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=second_root,
        )
    )
    changed_approver = preflight_local_runtime(
        **{
            **_runtime_preflight_arguments(
                store,
                build_result,
                runtime_root=second_root,
            ),
            "approved_by": "different-human",
        }
    )
    changed_admission = preflight_local_runtime(
        **{
            **_runtime_preflight_arguments(
                store,
                build_result,
                runtime_root=second_root,
            ),
            "injected_runtime_admission": {
                **RUNTIME_ADMISSION,
                "provider": "different-provider",
            },
        }
    )

    assert first["runtime_execution_identity_hash"] == same_action[
        "runtime_execution_identity_hash"
    ]
    assert first["runtime_execution_identity_hash"] != changed_approver[
        "runtime_execution_identity_hash"
    ]
    assert first["runtime_execution_identity_hash"] != changed_admission[
        "runtime_execution_identity_hash"
    ]
    with pytest.raises(LocalEntryError, match="non-JSON"):
        preflight_local_runtime(
            **{
                **_runtime_preflight_arguments(
                    store,
                    build_result,
                    runtime_root=second_root,
                ),
                "injected_runtime_admission": {
                    **RUNTIME_ADMISSION,
                    "invalid": object(),
                },
            }
        )


@pytest.mark.parametrize("expected_hash", (None, "sha256:not-valid", "sha256:" + "0" * 64))
def test_runtime_execute_identity_gate_blocks_before_resume_or_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expected_hash: str | None,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    before_resume_count = len(
        store.list_feature_artifact_revisions(FEATURE_ID, "resume_report")
    )
    calls = {"probe": 0, "factory": 0}

    def forbidden_probe(*_args, **_kwargs) -> None:
        calls["probe"] += 1
        raise AssertionError("Identity rejection must precede Store probe.")

    def forbidden_factory(*_args, **_kwargs):
        calls["factory"] += 1
        raise AssertionError("Identity rejection must precede Runtime execution.")

    monkeypatch.setattr(ArtifactStore, "preflight_atomic_commit", forbidden_probe)
    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=expected_hash,
            runtime_factory=forbidden_factory,
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "authorization"
    assert result["runtime_preflight"] is not None
    assert result["runtime_execution_identity"] is not None
    assert result["runtime_execution_identity_hash"].startswith("sha256:")
    assert result["resume_report"] is None
    assert result["runtime_evidence"] is None
    assert calls == {"probe": 0, "factory": 0}
    assert len(
        store.list_feature_artifact_revisions(FEATURE_ID, "resume_report")
    ) == before_resume_count


def test_runtime_only_preflight_projects_consumed_checkpoint_as_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    checkpoint_projection = build_result["workflow_checkpoint"]
    assert isinstance(checkpoint_projection, dict)
    checkpoint_ref_value = checkpoint_projection["artifact_ref"]
    assert isinstance(checkpoint_ref_value, dict)
    checkpoint_ref = ArtifactRef(**checkpoint_ref_value)
    checkpoint = store.read(checkpoint_ref)["data"]
    payload = _resume_payload(checkpoint)
    decision, _ = WorkflowCheckpointStore(store).resume(checkpoint_ref, payload)
    assert decision.allowed is True
    original_validate = ResumeValidator.validate
    validator_calls = 0

    def recording_validate(selected, *args, **kwargs):
        nonlocal validator_calls
        validator_calls += 1
        return original_validate(selected, *args, **kwargs)

    monkeypatch.setattr(ResumeValidator, "validate", recording_validate)

    result = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )

    assert result["status"] == "BLOCKED"
    assert result["resume_decision"]["allowed"] is False
    assert result["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"
    assert result["checkpoint"]["consumption_status"] == "consumed"
    assert validator_calls == 1
    assert result["writes_performed"] is False


def test_runtime_execute_rechecks_handoff_before_resume_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    arguments = _runtime_preflight_arguments(
        store,
        build_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)
    original_loader = local_entry_module._load_runtime_continuation_handoff
    loader_calls = 0

    def drifting_loader(*args, **kwargs):
        nonlocal loader_calls
        loader_calls += 1
        handoff = original_loader(*args, **kwargs)
        if loader_calls == 2:
            return dataclasses.replace(
                handoff,
                resume_readiness=ResumeDecision(
                    status="blocked",
                    allowed=False,
                    reason="checkpoint changed before ResumeReport",
                    applied_updates={},
                    blockers=(
                        {
                            "code": "DOUBLE_RESUME_REJECTED",
                            "message": "checkpoint was consumed concurrently",
                        },
                    ),
                ),
            )
        return handoff

    monkeypatch.setattr(
        local_entry_module,
        "_load_runtime_continuation_handoff",
        drifting_loader,
    )
    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=_runtime_payload,
        )
    )

    assert loader_calls == 2
    assert result["status"] == "blocked"
    assert result["failure_stage"] == "admission"
    assert result["resume_report"] is None
    assert result["runtime_execution"]["factory_invocation_count"] == 0
    assert store.list_feature_artifact_revisions(FEATURE_ID, "resume_report") == []


def test_runtime_evidence_only_missing_factory_is_structured_admission_failure(
    tmp_path: Path,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    before = _store_snapshot(store.root)

    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=None,
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "admission"
    assert result["runtime_execution"]["factory_invocation_count"] == 0
    assert result["resume_report"] is None
    assert result["runtime_evidence"] is None
    assert result["blockers"][0]["code"] == "RUNTIME_EVIDENCE_FACTORY_REQUIRED"
    assert _store_snapshot(store.root) == before


def test_runtime_evidence_only_normalizes_resume_write_exception_before_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    before = _store_snapshot(store.root)

    def failing_resume(*_args, **_kwargs):
        raise ArtifactStoreError("resume admission changed")

    monkeypatch.setattr(
        WorkflowCheckpointStore,
        "resume_with_result",
        failing_resume,
    )
    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=_runtime_payload,
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "resume_admission"
    assert result["runtime_execution"]["factory_invocation_count"] == 0
    assert result["resume_report"] is None
    assert result["runtime_evidence"] is None
    assert result["blockers"][0]["code"] == "RUNTIME_RESUME_ADMISSION_FAILED"
    assert _store_snapshot(store.root) == before


def test_runtime_evidence_only_preserves_committed_report_on_state_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    before_reports = store.list_feature_artifact_revisions(
        FEATURE_ID,
        "resume_report",
    )

    def failing_state(*_args, **_kwargs):
        raise ValueError("resumed state cannot be reconstructed")

    monkeypatch.setattr(
        local_entry_module,
        "resumed_state_from_decision",
        failing_state,
    )
    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=_runtime_payload,
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "resume_admission"
    assert result["runtime_execution"]["factory_invocation_count"] == 0
    assert result["resume_report"]["artifact_ref"] is not None
    assert result["resume_report"]["store_result"]["outcome"] == "committed"
    assert result["runtime_evidence"] is None
    assert result["blockers"][0]["code"] == (
        "RUNTIME_RESUMED_STATE_RECONSTRUCTION_FAILED"
    )
    after_reports = store.list_feature_artifact_revisions(
        FEATURE_ID,
        "resume_report",
    )
    assert len(after_reports) == len(before_reports) + 1


def test_runtime_evidence_only_public_path_orders_effect_and_interrupts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    original_write = ArtifactStore.write_with_result
    original_probe = ArtifactStore.preflight_atomic_commit
    original_graph_admission = (
        workflow_graph_module._route_runtime_continuation_entry
    )
    events: list[str] = []

    def recording_write(selected: ArtifactStore, **kwargs) -> ArtifactWriteResult:
        result = original_write(selected, **kwargs)
        if kwargs["artifact_type"] == "resume_report":
            events.append("resume_report_committed")
        return result

    def recording_probe(selected: ArtifactStore, **kwargs) -> None:
        events.append("store_preflight")
        original_probe(selected, **kwargs)

    def recording_graph_admission(*args, **kwargs):
        events.append("graph_admission")
        return original_graph_admission(*args, **kwargs)

    def runtime_factory(feature_id, build, feature_spec):
        events.append("caller_factory")
        return _runtime_payload(feature_id, build, feature_spec)

    monkeypatch.setattr(ArtifactStore, "write_with_result", recording_write)
    monkeypatch.setattr(ArtifactStore, "preflight_atomic_commit", recording_probe)
    monkeypatch.setattr(
        workflow_graph_module,
        "_route_runtime_continuation_entry",
        recording_graph_admission,
    )
    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=runtime_factory,
        )
    )

    assert events == [
        "resume_report_committed",
        "graph_admission",
        "store_preflight",
        "caller_factory",
    ]
    assert result["status"] == "completed"
    assert result["failure_stage"] is None
    assert result["runtime_execution"]["factory_invocation_count"] == 1
    assert result["resume_report"]["store_result"]["outcome"] == "committed"
    assert result["runtime_evidence"]["store_result"]["outcome"] == "committed"
    assert result["runtime_evidence_ready"] is True
    assert not (runtime_root / "run_manifest.json").exists()
    assert not (runtime_root / "runtime_resume_result.json").exists()
    for artifact_type in ("blocked_report", "eval_report", "workflow_summary"):
        assert store.list_feature_artifact_revisions(FEATURE_ID, artifact_type) == []
    runtime_ref = ArtifactRef(**result["runtime_evidence"]["artifact_ref"])
    runtime_payload = store.read(runtime_ref)["data"]
    assert "runtime_evidence_store_result" not in runtime_payload


@pytest.mark.parametrize(
    ("artifact_type", "outcome", "expected_status", "expected_stage"),
    (
        ("resume_report", "blocked_before_commit", "blocked", "resume_report_store"),
        ("resume_report", "partial", "partial", "resume_report_store"),
        ("runtime_evidence", "blocked_before_commit", "blocked", "runtime_evidence_store"),
        ("runtime_evidence", "partial", "partial", "runtime_evidence_store"),
    ),
)
def test_runtime_evidence_only_preserves_store_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_type: str,
    outcome: str,
    expected_status: str,
    expected_stage: str,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    original_write = ArtifactStore.write_with_result

    def selected_write(selected: ArtifactStore, **kwargs) -> ArtifactWriteResult:
        if kwargs["artifact_type"] == artifact_type:
            return _store_failure_result(
                selected,
                artifact_type=artifact_type,
                outcome=outcome,
            )
        return original_write(selected, **kwargs)

    monkeypatch.setattr(ArtifactStore, "write_with_result", selected_write)
    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=_runtime_payload,
        )
    )

    assert result["status"] == expected_status
    assert result["failure_stage"] == expected_stage
    if artifact_type == "resume_report":
        assert result["runtime_execution"]["factory_invocation_count"] == 0
        assert result["runtime_evidence"] is None
    else:
        assert result["runtime_execution"]["factory_invocation_count"] == 1
        assert result["runtime_evidence"]["artifact_ref"] is None
        assert result["runtime_evidence"]["store_result"]["outcome"] == outcome


def test_resume_with_result_consumes_checkpoint_only_after_committed_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    checkpoint_projection = build_result["workflow_checkpoint"]
    assert isinstance(checkpoint_projection, dict)
    checkpoint_ref_value = checkpoint_projection["artifact_ref"]
    assert isinstance(checkpoint_ref_value, dict)
    checkpoint_ref = ArtifactRef(**checkpoint_ref_value)
    checkpoint = store.read(checkpoint_ref)["data"]
    checkpoint_store = WorkflowCheckpointStore(store)
    payload = _resume_payload(checkpoint)
    original_write = store.write_with_result

    monkeypatch.setattr(
        store,
        "write_with_result",
        lambda **_kwargs: _store_failure_result(
            store,
            artifact_type="resume_report",
            outcome="blocked_before_commit",
        ),
    )
    first_decision, first_result = checkpoint_store.resume_with_result(
        checkpoint_ref,
        payload,
    )
    assert first_decision.allowed is True
    assert first_result.outcome == "blocked_before_commit"
    assert checkpoint_store.preflight_resume(
        checkpoint_ref,
        resume_id=payload.resume_id,
    ).allowed is True

    monkeypatch.setattr(store, "write_with_result", original_write)
    second_decision, second_result = checkpoint_store.resume_with_result(
        checkpoint_ref,
        payload,
    )
    assert second_decision.allowed is True
    assert second_result.outcome == "committed"
    assert second_result.artifact_ref is not None
    assert checkpoint_store.preflight_resume(
        checkpoint_ref,
        resume_id=payload.resume_id,
    ).allowed is False


@pytest.mark.parametrize(
    ("failure_kind", "expected_stage", "expected_count"),
    (
        ("probe", "store_preflight", 0),
        ("factory", "runtime_execution", 1),
        ("factory_named_store_preflight", "runtime_execution", 1),
        ("factory_named_post_validation", "runtime_execution", 1),
        ("payload", "post_runtime_validation", 1),
    ),
)
def test_runtime_evidence_only_normalizes_effect_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_stage: str,
    expected_count: int,
) -> None:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    if failure_kind == "probe":
        monkeypatch.setattr(
            ArtifactStore,
            "preflight_atomic_commit",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ArtifactStoreError("probe failed")
            ),
        )

    def runtime_factory(feature_id, build, feature_spec):
        if failure_kind == "factory":
            raise OSError("runtime failed")
        if failure_kind == "factory_named_store_preflight":
            error_type = type(
                "_RuntimeEvidenceStorePreflightError",
                (RuntimeError,),
                {},
            )
            raise error_type("caller must not select store_preflight")
        if failure_kind == "factory_named_post_validation":
            error_type = type(
                "_RuntimeEvidencePostValidationError",
                (RuntimeError,),
                {},
            )
            raise error_type("caller must not select post_runtime_validation")
        payload = _runtime_payload(feature_id, build, feature_spec)
        if failure_kind == "payload":
            payload["run_id"] = "wrong-run"
        return payload

    result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=runtime_factory,
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == expected_stage
    assert result["runtime_execution"]["factory_invocation_count"] == expected_count
    assert result["runtime_evidence"] is None


def test_runtime_terminal_preflight_is_deterministic_and_zero_write(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    before = _store_snapshot(store.root)

    first = preflight_local_runtime(
        **_runtime_terminal_preflight_arguments(
            store,
            build_result,
            runtime_result,
            runtime_root=runtime_root,
        )
    )
    second = preflight_local_runtime(
        **_runtime_terminal_preflight_arguments(
            store,
            build_result,
            runtime_result,
            runtime_root=runtime_root,
        )
    )

    assert first == second
    assert first["status"] == "READY_FOR_RUNTIME_TERMINALIZATION"
    assert first["writes_performed"] is False
    assert first["graph_invoked"] is False
    assert first["runtime_factory_invoked"] is False
    assert first["existing_terminal_artifacts"] == []
    assert first["runtime_terminal_execution_identity_hash"].startswith(
        "sha256:"
    )
    structured = first["verification_operation_preflight_result"]
    assert structured["preflight_status"] == "ready"
    assert structured["identity_resolution_status"] == "identity_resolved"
    assert structured["envelope"] is not None
    assert (
        structured["approval_identity_hash"]
        == first["runtime_terminal_execution_identity_hash"]
    )
    assert _store_snapshot(store.root) == before


def test_runtime_terminal_uses_durable_build_identity_after_output_cleanup(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    build_ref_value = build_result["build_result"]["artifact_ref"]
    assert isinstance(build_ref_value, dict)
    build = store.read(ArtifactRef(**build_ref_value))["data"]
    verified_artifacts = build["verified_artifacts"]
    assert isinstance(verified_artifacts, list)
    assert len(verified_artifacts) == 1
    output_path = Path(verified_artifacts[0]["resolved_path"])
    output_path.unlink()

    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)
    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert preflight["status"] == "READY_FOR_RUNTIME_TERMINALIZATION"
    assert result["status"] == "completed"
    assert result["terminal_route"] == "blocked"


def test_runtime_terminal_unverified_evidence_commits_exact_blocked_report(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)
    before_reports = len(
        store.list_feature_artifact_revisions(FEATURE_ID, "resume_report")
    )
    before_runtime = len(
        store.list_feature_artifact_revisions(FEATURE_ID, "runtime_evidence")
    )

    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert result["status"] == "completed"
    assert result["failure_stage"] is None
    assert result["terminal_route"] == "blocked"
    assert result["terminal_ready"] is True
    assert result["domain_result"]["final_status"] == "blocked"
    assert result["blocked_report"]["store_result"]["outcome"] == "committed"
    assert result["eval_report"] is None
    assert result["workflow_summary"] is None
    assert result["runtime_factory_invocation_count"] == 0
    assert len(
        store.list_feature_artifact_revisions(FEATURE_ID, "resume_report")
    ) == before_reports
    assert len(
        store.list_feature_artifact_revisions(FEATURE_ID, "runtime_evidence")
    ) == before_runtime
    blocked_ref = ArtifactRef(**result["blocked_report"]["artifact_ref"])
    runtime_ref = ArtifactRef(**runtime_result["runtime_evidence"]["artifact_ref"])
    blocked_envelope = store.read(blocked_ref)
    blocked_upstreams = blocked_envelope["inputs"]["upstream_artifacts"]
    assert blocked_envelope["trace_refs"] == []
    assert blocked_upstreams == [
        {
            "artifact_type": "runtime_evidence",
            "artifact_hash": runtime_ref.artifact_hash,
            "path": runtime_ref.path,
            "require_latest": True,
        }
    ]

    replay = preflight_local_runtime(**arguments)
    assert replay["status"] == "BLOCKED"
    assert replay["existing_terminal_artifacts"] == [
        {
            "artifact_type": "blocked_report",
            "artifact_hash": blocked_ref.artifact_hash,
            "feature_id": FEATURE_ID,
        }
    ]


def test_runtime_terminal_verified_evidence_commits_eval_and_summary(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(
            tmp_path,
            runtime_factory=_verified_runtime_payload,
        )
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)

    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert result["status"] == "completed"
    assert result["failure_stage"] is None
    assert result["terminal_route"] == "done", result["blockers"]
    assert result["terminal_ready"] is True
    assert result["domain_result"]["final_status"] == "accepted"
    assert result["domain_result"]["claims_real_mod_success"] is True
    assert result["eval_report"]["store_result"]["outcome"] == "committed"
    assert result["workflow_summary"]["store_result"]["outcome"] == "committed"
    assert result["blocked_report"] is None
    summary_ref = ArtifactRef(**result["workflow_summary"]["artifact_ref"])
    summary = store.read(summary_ref)["data"]
    assert "runtime_evidence_store_result" not in summary["runtime_summary"]
    assert "eval_report_store_result" not in summary["runtime_summary"]
    assert "workflow_summary_store_result" not in summary["runtime_summary"]

    replay = preflight_local_runtime(**arguments)
    assert replay["status"] == "BLOCKED"
    assert {
        item["artifact_type"] for item in replay["existing_terminal_artifacts"]
    } == {"eval_report", "workflow_summary"}


def test_runtime_terminal_eval_gate_commits_eval_then_exact_blocked_report(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(
            tmp_path,
            runtime_factory=_verified_runtime_payload_without_marker,
        )
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)

    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert result["status"] == "completed"
    assert result["terminal_route"] == "blocked"
    assert result["domain_result"]["final_status"] == "blocked"
    assert result["eval_report"]["store_result"]["outcome"] == "committed"
    assert result["blocked_report"]["store_result"]["outcome"] == "committed"
    assert result["workflow_summary"] is None
    machine_result = result["verification_operation_result"]
    outputs = {item["role"]: item["artifact_ref"] for item in machine_result["outputs"]}
    receipts = {
        item["role"]: item["artifact_write_result"]
        for item in machine_result["store_receipts"]
    }
    assert set(outputs) == {"eval_report", "blocked_report"}
    assert set(receipts) == set(outputs)
    assert all(receipts[role]["outcome"] == "committed" for role in outputs)
    assert all(
        receipts[role]["artifact_ref"] == outputs[role] for role in outputs
    )
    eval_ref = ArtifactRef(**result["eval_report"]["artifact_ref"])
    blocked_ref = ArtifactRef(**result["blocked_report"]["artifact_ref"])
    assert store.read(blocked_ref)["inputs"]["upstream_artifacts"] == [
        {
            "artifact_type": "eval_report",
            "artifact_hash": eval_ref.artifact_hash,
            "path": eval_ref.path,
            "require_latest": True,
        }
    ]

    replay = preflight_local_runtime(**arguments)
    assert replay["status"] == "BLOCKED"
    assert {
        item["artifact_type"] for item in replay["existing_terminal_artifacts"]
    } == {"blocked_report", "eval_report"}


def test_runtime_terminal_identity_excludes_run_root_and_binds_approver(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, first_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    second_root = tmp_path / "terminal-presentation-root"
    second_root.mkdir()
    first_arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=first_root,
    )
    second_arguments = {
        **first_arguments,
        "run_root": second_root,
    }
    first = preflight_local_runtime(**first_arguments)
    second = preflight_local_runtime(**second_arguments)
    changed_approver = preflight_local_runtime(
        **{
            **second_arguments,
            "approved_by": "other-human",
        }
    )

    assert first["runtime_terminal_execution_identity_hash"] == second[
        "runtime_terminal_execution_identity_hash"
    ]
    assert first["runtime_terminal_execution_identity_hash"] != changed_approver[
        "runtime_terminal_execution_identity_hash"
    ]
    assert changed_approver["status"] == "BLOCKED"

    handoff = local_entry_module._load_runtime_terminal_handoff(
        **{
            key: value
            for key, value in first_arguments.items()
            if key != "runtime_terminalization_only"
        }
    )
    identity, identity_hash = (
        local_entry_module._verification_only_runtime_terminal_identity(
            handoff=handoff,
            resume_id="verification_only_runtime_resume_001",
            approved_by="human",
        )
    )
    assert identity["terminal_result_scope"] == {
        "allowed_artifact_types": [
            "blocked_report",
            "eval_report",
            "workflow_summary",
        ],
        "automatic_retry_count": 0,
        "recovery_allowed": False,
    }
    for field in (
        "checkpoint_ref",
        "resume_report_ref",
        "runtime_evidence_ref",
    ):
        ref = getattr(handoff.build_handoff, field, None)
        if ref is None:
            ref = getattr(handoff, field)
        changed_ref = dataclasses.replace(ref, artifact_hash="f" * 64)
        if field == "checkpoint_ref":
            changed_handoff = dataclasses.replace(
                handoff,
                build_handoff=dataclasses.replace(
                    handoff.build_handoff,
                    checkpoint_ref=changed_ref,
                ),
            )
        else:
            changed_handoff = dataclasses.replace(
                handoff,
                **{field: changed_ref},
            )
        _, changed_hash = (
            local_entry_module._verification_only_runtime_terminal_identity(
                handoff=changed_handoff,
                resume_id="verification_only_runtime_resume_001",
                approved_by="human",
            )
        )
        assert changed_hash != identity_hash


def test_runtime_terminal_identity_gate_precedes_graph_and_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    before = _store_snapshot(store.root)

    def forbidden_graph(*_args, **_kwargs):
        raise AssertionError("Identity rejection must precede Graph construction.")

    monkeypatch.setattr(local_entry_module, "build_graph", forbidden_graph)
    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash="sha256:" + "0" * 64,
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "authorization"
    assert result["blocked_report"] is None
    assert result["eval_report"] is None
    assert result["workflow_summary"] is None
    assert _store_snapshot(store.root) == before


def test_runtime_terminal_rejects_runtime_side_effect_scope_before_write(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)
    before = _store_snapshot(store.root)
    execute_arguments = _runtime_terminal_execute_arguments(
        arguments,
        expected_hash=preflight["runtime_terminal_execution_identity_hash"],
    )
    execute_arguments["allow_game_launch"] = True

    result = resume_local_runtime(**execute_arguments)

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "authorization"
    assert result["blockers"][0]["code"] == (
        "RUNTIME_TERMINAL_SIDE_EFFECT_SCOPE_INVALID"
    )
    assert _store_snapshot(store.root) == before


def test_runtime_terminal_preflight_rejects_plugin_destination_without_write(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    arguments["runtime_plugin_destination"] = runtime_root / "plugin.dll"
    before = _store_snapshot(store.root)

    with pytest.raises(LocalEntryError, match="Store-only continuation"):
        preflight_local_runtime(**arguments)
    assert _store_snapshot(store.root) == before


@pytest.mark.parametrize(
    "drift_kind",
    (
        "runtime_hash",
        "runtime_alias_path",
        "resume_report_hash",
        "resume_report_alias_path",
        "checkpoint_alias_path",
    ),
)
def test_runtime_terminal_exact_revision_drift_is_zero_write(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    if drift_kind == "runtime_hash":
        arguments["runtime_evidence_hash"] = "0" * 64
    elif drift_kind == "runtime_alias_path":
        latest_runtime = next(
            ref
            for ref in store.list_feature_artifacts(FEATURE_ID)
            if ref.artifact_type == "runtime_evidence"
        )
        arguments["runtime_evidence_path"] = latest_runtime.path
    elif drift_kind == "resume_report_hash":
        arguments["accepted_resume_report_hash"] = "0" * 64
    elif drift_kind == "resume_report_alias_path":
        latest_report = next(
            ref
            for ref in store.list_feature_artifacts(FEATURE_ID)
            if ref.artifact_type == "resume_report"
        )
        arguments["accepted_resume_report_path"] = latest_report.path
    else:
        latest_checkpoint = next(
            ref
            for ref in store.list_feature_artifacts(FEATURE_ID)
            if ref.artifact_type == "workflow_checkpoint"
        )
        arguments["checkpoint_path"] = latest_checkpoint.path
    before = _store_snapshot(store.root)

    result = preflight_local_runtime(**arguments)
    structured = result["verification_operation_preflight_result"]
    assert structured["preflight_status"] == "blocked"
    assert structured["failure_stage"] == "admission"
    assert any(
        "exact immutable revision" in blocker["message"]
        for blocker in structured["blockers"]
    )
    assert _store_snapshot(store.root) == before


def test_runtime_terminal_stale_feature_lineage_is_blocked_without_write(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    feature_ref = next(
        ref
        for ref in store.list_feature_artifact_revisions(FEATURE_ID, "feature_spec")
    )
    changed_feature = copy.deepcopy(store.read(feature_ref)["data"])
    changed_feature["message"] = "FeatureSpec advanced after RuntimeEvidence."
    store.write(
        feature_id=FEATURE_ID,
        artifact_type="feature_spec",
        payload=changed_feature,
        status="success",
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    before = _store_snapshot(store.root)

    result = preflight_local_runtime(**arguments)

    assert result["status"] == "BLOCKED"
    blocker_codes = {item["code"] for item in result["blockers"]}
    assert "RUNTIME_TERMINAL_CHECKPOINT_STALE" in blocker_codes
    assert "RUNTIME_TERMINAL_EVIDENCE_STALE" in blocker_codes
    assert _store_snapshot(store.root) == before


@pytest.mark.parametrize(
    ("artifact_type", "runtime_mode", "expected_prior"),
    (
        ("blocked_report", "unverified", ()),
        ("blocked_report", "verified_without_marker", ("eval_report",)),
        ("eval_report", "verified", ()),
        ("workflow_summary", "verified", ("eval_report",)),
    ),
)
@pytest.mark.parametrize("outcome", ("blocked_before_commit", "partial"))
def test_runtime_terminal_preserves_each_store_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_type: str,
    runtime_mode: str,
    expected_prior: tuple[str, ...],
    outcome: str,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(
            tmp_path,
            runtime_factory={
                "unverified": _unverified_runtime_payload,
                "verified": _verified_runtime_payload,
                "verified_without_marker": (
                    _verified_runtime_payload_without_marker
                ),
            }[runtime_mode],
        )
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)
    original_write = ArtifactStore.write_with_result

    def selected_write(selected: ArtifactStore, **kwargs) -> ArtifactWriteResult:
        if kwargs["artifact_type"] == artifact_type:
            return _store_failure_result(
                selected,
                artifact_type=artifact_type,
                outcome=outcome,
            )
        return original_write(selected, **kwargs)

    monkeypatch.setattr(ArtifactStore, "write_with_result", selected_write)
    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert result["status"] == (
        "partial" if outcome == "partial" else "blocked"
    )
    assert result["failure_stage"] == f"{artifact_type}_store"
    selected_projection = result[artifact_type]
    assert selected_projection["artifact_ref"] is None
    assert selected_projection["store_result"]["outcome"] == outcome
    for prior_type in expected_prior:
        assert result[prior_type]["artifact_ref"] is not None
        assert result[prior_type]["store_result"]["outcome"] == "committed"


def test_runtime_terminal_graph_admission_drift_is_zero_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)
    before = _store_snapshot(store.root)

    monkeypatch.setattr(
        workflow_graph_module,
        "_route_runtime_terminal_continuation_entry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("terminal Graph state drift")
        ),
    )
    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == "graph_terminal_admission"
    assert _store_snapshot(store.root) == before


def test_runtime_terminal_direct_graph_wrong_state_is_zero_write(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    handoff = local_entry_module._load_runtime_terminal_handoff(
        **{
            key: value
            for key, value in arguments.items()
            if key not in {"runtime_terminalization_only"}
        }
    )
    state = resumed_state_from_decision(
        handoff.decision,
        checkpoint_ref=handoff.build_handoff.checkpoint_ref,
        resume_report_ref=handoff.resume_report_ref,
    )
    state["artifacts"]["runtime_evidence"] = handoff.runtime_evidence_ref.path
    state["artifact_hashes"]["runtime_evidence"] = (
        handoff.runtime_evidence_ref.artifact_hash
    )
    state["runtime_summary"] = workflow_graph_module._runtime_summary_from_payload(
        handoff.runtime_evidence
    )
    state["current_stage"] = "build"
    before = _store_snapshot(store.root)
    graph = build_graph(
        store,
        verification_operation=project_verification_operation(
            VerificationOperationSpec(
                operation_kind=RUNTIME_TERMINALIZATION_KIND,
                operation_contract_version=RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
                attempt_policy=InitialAttemptV1(),
                protocol_binding=VerificationProtocolBinding(
                    checkpoint_ref=handoff.build_handoff.checkpoint_ref,
                    accepted_resume_report_ref=handoff.resume_report_ref,
                    resume_id="verification_only_runtime_resume_001",
                    approved_by="human",
                ),
                variant_payload=RuntimeTerminalizationOperationV1(
                    runtime_evidence_ref=handoff.runtime_evidence_ref,
                ),
            ),
            checkpoint_identity=VerificationCheckpointIdentityV1(
                checkpoint_id=str(
                    handoff.build_handoff.checkpoint["checkpoint_id"]
                ),
                run_id=str(handoff.build_handoff.checkpoint["run_id"]),
                request_id=str(handoff.build_handoff.checkpoint["request_id"]),
            ),
        ),
        use_default_proposal_git_binding=False,
    )

    with pytest.raises(ValueError, match="RuntimeEvidence boundary"):
        graph.invoke(state)
    assert _store_snapshot(store.root) == before


def test_runtime_terminal_never_calls_store_probe_or_runtime_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)

    monkeypatch.setattr(
        ArtifactStore,
        "preflight_atomic_commit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Terminalization must not run a Store probe.")
        ),
    )
    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert result["status"] == "completed"
    assert result["runtime_factory_invocation_count"] == 0
    assert not (runtime_root / "run_manifest.json").exists()
    assert not (runtime_root / "runtime_resume_result.json").exists()


@pytest.mark.parametrize(
    ("failure_node", "runtime_mode", "expected_stage", "prior_type"),
    (
        ("evaluate", "verified", "eval_report_execution", None),
        (
            "workflow_summary",
            "verified",
            "workflow_summary_execution",
            "eval_report",
        ),
        ("blocked", "unverified", "blocked_report_execution", None),
        (
            "blocked",
            "verified_without_marker",
            "blocked_report_execution",
            "eval_report",
        ),
    ),
)
def test_runtime_terminal_normalizes_each_payload_execution_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_node: str,
    runtime_mode: str,
    expected_stage: str,
    prior_type: str | None,
) -> None:
    store, build_result, runtime_result, runtime_root = (
        _public_runtime_evidence_handoff(
            tmp_path,
            runtime_factory={
                "unverified": _unverified_runtime_payload,
                "verified": _verified_runtime_payload,
                "verified_without_marker": (
                    _verified_runtime_payload_without_marker
                ),
            }[runtime_mode],
        )
    )
    arguments = _runtime_terminal_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
    )
    preflight = preflight_local_runtime(**arguments)

    if failure_node == "evaluate":
        monkeypatch.setattr(
            workflow_graph_module,
            "build_transition_eval_gate_report",
            lambda **_kwargs: (_ for _ in ()).throw(
                ValueError("eval payload failed")
            ),
        )
    elif failure_node == "workflow_summary":
        monkeypatch.setattr(
            workflow_graph_module,
            "_run_workflow_summary",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("summary payload failed")
            ),
        )
    else:
        monkeypatch.setattr(
            workflow_graph_module.StubNodeRunner,
            "_payload_for",
            staticmethod(
                lambda **_kwargs: (_ for _ in ()).throw(
                    ValueError("blocked payload failed")
                )
            ),
        )

    result = resume_local_runtime(
        **_runtime_terminal_execute_arguments(
            arguments,
            expected_hash=preflight[
                "runtime_terminal_execution_identity_hash"
            ],
        )
    )

    assert result["status"] == "blocked"
    assert result["failure_stage"] == expected_stage
    assert result["terminal_ready"] is False
    if prior_type is not None:
        assert result[prior_type]["artifact_ref"] is not None
        assert result[prior_type]["store_result"]["outcome"] == "committed"


def _public_build_handoff(tmp_path: Path) -> tuple[ArtifactStore, dict[str, object]]:
    store, continuation = _verification_inputs(tmp_path)
    result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )
    assert result["status"] == "completed"
    assert result["handoff_ready"] is True
    return store, result


def _public_runtime_evidence_handoff(
    tmp_path: Path,
    *,
    runtime_factory=None,
) -> tuple[ArtifactStore, dict[str, object], dict[str, Any], Path]:
    store, build_result = _public_build_handoff(tmp_path)
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    runtime_result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=runtime_factory or _unverified_runtime_payload,
        )
    )
    if runtime_result["status"] != "completed":
        raise AssertionError(runtime_result["blockers"])
    assert runtime_result["runtime_evidence_ready"] is True
    return store, build_result, runtime_result, runtime_root


def test_runtime_evidence_consolidation_public_path_commits_one_child(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    first = preflight_local_runtime(**arguments)
    second = preflight_local_runtime(**arguments)
    assert isinstance(first, VerificationOperationPreflightResultV1)
    assert isinstance(second, VerificationOperationPreflightResultV1)
    assert first == second
    assert first.preflight_status == "ready"
    assert first.approval_identity_hash is not None
    before_counts = _artifact_counts(store)

    result = resume_local_runtime(
        **_runtime_consolidation_execute_arguments(
            arguments,
            expected_hash=first.approval_identity_hash,
        )
    )

    assert isinstance(result, VerificationOperationResultV1)
    assert isinstance(result.variant_result, EvidenceConsolidationResultV1)
    assert result.platform_status == "completed"
    assert result.failure_stage is None
    assert result.execution_disposition == "succeeded"
    assert len(result.store_receipts) == 1
    assert result.store_receipts[0].role == "runtime_evidence"
    assert result.store_receipts[0].artifact_write_result.outcome == "committed"
    child_ref = result.variant_result.runtime_evidence_ref
    assert child_ref is not None
    envelope = store.read(child_ref)
    assert envelope["status"] == "blocked"
    assert [item["artifact_type"] for item in envelope["inputs"]["upstream_artifacts"]] == [
        "build_result",
        "feature_spec",
        "runtime_evidence",
        "evidence_pack",
    ]
    assert [item["require_latest"] for item in envelope["inputs"]["upstream_artifacts"]] == [
        True,
        True,
        False,
        False,
    ]
    criteria = envelope["data"]["stagger_acceptance_evaluation"]["criteria"]
    assert criteria[0]["outcome"] == "true"
    assert criteria[0]["evidence_strength"] == "bound_implementation_evidence"
    assert envelope["data"]["acceptance_verified"] is False
    assert envelope["data"]["claims_real_runtime_success"] is False
    after_counts = _artifact_counts(store)
    assert after_counts["runtime_evidence"] == before_counts["runtime_evidence"] + 1
    for artifact_type in set(after_counts) - {"runtime_evidence"}:
        assert after_counts[artifact_type] == before_counts[artifact_type]
    assert store.check_freshness(child_ref).is_fresh


def test_runtime_evidence_consolidation_identity_excludes_run_root_and_binds_delta(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    first = preflight_local_runtime(**arguments)
    alternate_root = tmp_path / "presentation-only-root"
    alternate_root.mkdir()
    second = preflight_local_runtime(**{**arguments, "run_root": alternate_root})
    assert isinstance(first, VerificationOperationPreflightResultV1)
    assert isinstance(second, VerificationOperationPreflightResultV1)
    assert first.approval_identity_hash == second.approval_identity_hash

    changed_delta = copy.deepcopy(action["delta"])
    changed_delta["evidence_ids"] = [*changed_delta["evidence_ids"], "extra"]
    original_operation = arguments["verification_operation"]
    changed_operation = dataclasses.replace(
        original_operation,
        variant_payload=dataclasses.replace(
            original_operation.variant_payload,
            canonical_delta=changed_delta,
        ),
    )
    changed = preflight_local_runtime(
        **{**arguments, "verification_operation": changed_operation}
    )
    assert isinstance(changed, VerificationOperationPreflightResultV1)
    assert changed.preflight_status == "blocked"
    assert changed.failure_stage == "admission"


def test_typed_consolidation_identity_excludes_physical_file_locators(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    operation = arguments["verification_operation"]
    relocated = tuple(
        dataclasses.replace(
            binding,
            absolute_path=str(tmp_path / "relocated" / Path(binding.absolute_path).name),
        )
        for binding in operation.variant_payload.execution_file_bindings
    )
    relocated_operation = dataclasses.replace(
        operation,
        variant_payload=dataclasses.replace(
            operation.variant_payload,
            execution_file_bindings=relocated,
        ),
    )
    changed_content = list(relocated)
    changed_content[0] = dataclasses.replace(
        changed_content[0],
        content_sha256="0" * 64,
    )
    changed_content_operation = dataclasses.replace(
        relocated_operation,
        variant_payload=dataclasses.replace(
            relocated_operation.variant_payload,
            execution_file_bindings=tuple(changed_content),
        ),
    )

    assert (
        project_verification_operation(operation).approval_identity_hash
        == project_verification_operation(relocated_operation).approval_identity_hash
    )
    assert (
        project_verification_operation(operation).approval_identity_hash
        != project_verification_operation(
            changed_content_operation
        ).approval_identity_hash
    )


@pytest.mark.parametrize(
    "drift",
    ("unknown_contract", "legacy_scope"),
)
def test_typed_consolidation_authority_drift_is_zero_write(
    tmp_path: Path,
    drift: str,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    if drift == "unknown_contract":
        arguments["verification_operation"] = dataclasses.replace(
            arguments["verification_operation"],
            operation_contract_version="runtime_evidence_consolidation_v2",
        )
    else:
        arguments["runtime_evidence_only"] = True
    before = _store_snapshot(store.root)
    result = preflight_local_runtime(**arguments)
    assert isinstance(result, VerificationOperationPreflightResultV1)
    assert result.preflight_status == "blocked"
    assert result.failure_stage == "authorization"
    assert _store_snapshot(store.root) == before


@pytest.mark.parametrize(
    "tamper",
    (
        "claims",
        "non_target_criterion",
        "canonical_delta_hash",
        "file_binding",
        "action_scope",
        "binding_version",
        "feature_adapter",
    ),
)
def test_runtime_evidence_consolidation_direct_store_rejects_semantic_tamper(
    tmp_path: Path,
    tamper: str,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    tampered = copy.deepcopy(handoff.derived_payload)
    binding = tampered["verification_only_evidence_consolidation"]
    if tamper == "claims":
        tampered["acceptance_verified"] = True
        tampered["claims_real_runtime_success"] = True
    elif tamper == "non_target_criterion":
        tampered["stagger_acceptance_evaluation"]["criteria"][1][
            "outcome"
        ] = "true"
    elif tamper == "canonical_delta_hash":
        binding["canonical_delta_hash"] = "sha256:" + "0" * 64
    elif tamper == "file_binding":
        binding["file_bindings"][0]["content_sha256"] = "0" * 64
    elif tamper == "action_scope":
        binding["action_scope"]["new_runtime_performed"] = True
    elif tamper == "binding_version":
        binding["semantic_binding"]["version"] = "2"
    else:
        binding["feature_adapter"] = "unknown_adapter_v1"
    before = _store_snapshot(store.root)
    result = store.write_with_result(
        feature_id=FEATURE_ID,
        artifact_type="runtime_evidence",
        payload=tampered,
        status="blocked",
        upstream_refs=[
            handoff.build_handoff.build_ref,
            handoff.build_handoff.feature_spec_ref,
            handoff.prior_runtime_evidence_ref,
            handoff.evidence_pack_ref,
        ],
        exact_revision_upstream_types={"runtime_evidence", "evidence_pack"},
        semantic_intent=handoff.semantic_intent,
    )
    assert result.outcome == "blocked_before_commit"
    assert result.commit_started is False
    assert result.artifact_ref is None
    assert _store_snapshot(store.root) == before


@pytest.mark.parametrize("outcome", ("blocked_before_commit", "partial"))
def test_runtime_evidence_consolidation_preserves_c5_store_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    preflight = preflight_local_runtime(**arguments)
    assert isinstance(preflight, VerificationOperationPreflightResultV1)
    assert preflight.approval_identity_hash is not None
    monkeypatch.setattr(
        ArtifactStore,
        "write_with_result",
        lambda selected, **kwargs: _store_failure_result(
            selected,
            artifact_type=kwargs["artifact_type"],
            outcome=outcome,
        ),
    )
    result = resume_local_runtime(
        **_runtime_consolidation_execute_arguments(
            arguments,
            expected_hash=preflight.approval_identity_hash,
        )
    )
    assert isinstance(result, VerificationOperationResultV1)
    assert isinstance(result.variant_result, EvidenceConsolidationResultV1)
    assert result.platform_status == (
        "partial" if outcome == "partial" else "blocked"
    )
    assert result.failure_stage == "runtime_evidence_store"
    assert result.variant_result.runtime_evidence_ref is None
    assert len(result.store_receipts) == 1
    assert result.store_receipts[0].artifact_write_result.outcome == outcome


def test_runtime_evidence_consolidation_replay_and_file_drift_fail_closed(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    preflight = preflight_local_runtime(**arguments)
    assert isinstance(preflight, VerificationOperationPreflightResultV1)
    assert preflight.approval_identity_hash is not None
    first = resume_local_runtime(
        **_runtime_consolidation_execute_arguments(
            arguments,
            expected_hash=preflight.approval_identity_hash,
        )
    )
    assert isinstance(first, VerificationOperationResultV1)
    assert first.platform_status == "completed"
    before = _store_snapshot(store.root)
    replay = preflight_local_runtime(**arguments)
    assert isinstance(replay, VerificationOperationPreflightResultV1)
    assert replay.preflight_status == "blocked"
    assert replay.blockers
    assert _store_snapshot(store.root) == before

    other_tmp = tmp_path / "drift"
    other_tmp.mkdir()
    store2, build2, runtime2, root2, action2 = (
        _c4_public_runtime_evidence_handoff(other_tmp)
    )
    arguments2 = _runtime_consolidation_preflight_arguments(
        store2,
        build2,
        runtime2,
        runtime_root=root2,
        action=action2,
    )
    Path(action2["bindings"][0].absolute_path).write_text(
        "drift", encoding="utf-8"
    )
    before2 = _store_snapshot(store2.root)
    drifted = preflight_local_runtime(**arguments2)
    assert isinstance(drifted, VerificationOperationPreflightResultV1)
    assert drifted.preflight_status == "blocked"
    assert drifted.failure_stage == "admission"
    assert _store_snapshot(store2.root) == before2


def test_runtime_evidence_consolidation_successor_owner_filters_exact_adapter(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    prior_ref = handoff.prior_runtime_evidence_ref
    foreign_payload = copy.deepcopy(store.read(prior_ref)["data"])
    foreign_payload["message"] = "Independent RuntimeEvidence child."
    foreign_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="runtime_evidence",
        payload=foreign_payload,
        status="blocked",
        upstream_refs=[
            handoff.build_handoff.build_ref,
            handoff.build_handoff.feature_spec_ref,
            prior_ref,
        ],
        exact_revision_upstream_types={"runtime_evidence"},
    )
    assert foreign_ref != prior_ref
    assert runtime_evidence_consolidation_child_refs(
        store,
        feature_id=FEATURE_ID,
        prior_ref=prior_ref,
        feature_adapter="stagger_c4_implementation_evidence_v1",
    ) == ()
    decision, _, checkpoint_child_refs = WorkflowCheckpointStore(
        store
    ).preflight_runtime_evidence_consolidation(
        handoff.build_handoff.checkpoint_ref,
        resume_report_ref=handoff.resume_report_ref,
        prior_runtime_evidence_ref=prior_ref,
        resume_id=handoff.operation.protocol_binding.resume_id,
        approved_by=handoff.operation.protocol_binding.approved_by,
    )
    assert checkpoint_child_refs == ()
    blocker_codes = {str(item.get("code")) for item in decision.blockers}
    assert "RUNTIME_CONSOLIDATION_ALREADY_STARTED" not in blocker_codes
    assert "RUNTIME_CONSOLIDATION_EVIDENCE_NOT_LATEST" in blocker_codes


def test_runtime_evidence_consolidation_direct_graph_wrong_state_is_zero_write(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    state = resumed_state_from_decision(
        handoff.decision,
        checkpoint_ref=handoff.build_handoff.checkpoint_ref,
        resume_report_ref=handoff.resume_report_ref,
    )
    state["artifacts"]["runtime_evidence"] = handoff.prior_runtime_evidence_ref.path
    state["artifact_hashes"]["runtime_evidence"] = (
        handoff.prior_runtime_evidence_ref.artifact_hash
    )
    state["artifacts"]["evidence_pack"] = handoff.evidence_pack_ref.path
    state["artifact_hashes"]["evidence_pack"] = (
        handoff.evidence_pack_ref.artifact_hash
    )
    state["current_stage"] = "build"
    before = _store_snapshot(store.root)
    graph = build_graph(
        store,
        verification_operation=handoff.operation,
        use_default_proposal_git_binding=False,
    )
    with pytest.raises(ValueError, match="RuntimeEvidence boundary"):
        graph.invoke(state)
    assert _store_snapshot(store.root) == before


def test_runtime_evidence_consolidation_expected_identity_drift_is_zero_write(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    before = _store_snapshot(store.root)
    result = resume_local_runtime(
        **_runtime_consolidation_execute_arguments(
            arguments,
            expected_hash="sha256:" + "0" * 64,
        )
    )
    assert isinstance(result, VerificationOperationResultV1)
    assert result.platform_status == "blocked"
    assert result.failure_stage == "authorization"
    assert result.outputs == ()
    assert result.store_receipts == ()
    assert _store_snapshot(store.root) == before


def test_runtime_evidence_consolidation_uses_durable_build_identity_after_cleanup(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    build_ref = ArtifactRef(**build_result["build_result"]["artifact_ref"])
    build_payload = store.read(build_ref)["data"]
    Path(build_payload["verified_artifacts"][0]["resolved_path"]).unlink()
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    preflight = preflight_local_runtime(**arguments)
    assert isinstance(preflight, VerificationOperationPreflightResultV1)
    assert preflight.approval_identity_hash is not None
    result = resume_local_runtime(
        **_runtime_consolidation_execute_arguments(
            arguments,
            expected_hash=preflight.approval_identity_hash,
        )
    )
    assert isinstance(result, VerificationOperationResultV1)
    assert result.platform_status == "completed"
    assert result.execution_disposition == "succeeded"


def test_runtime_evidence_consolidation_direct_store_cannot_bypass_lineage(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    before = _store_snapshot(store.root)
    result = store.write_with_result(
        feature_id=FEATURE_ID,
        artifact_type="runtime_evidence",
        payload=dict(handoff.derived_payload),
        status="blocked",
        upstream_refs=[
            handoff.build_handoff.build_ref,
            handoff.build_handoff.feature_spec_ref,
            handoff.prior_runtime_evidence_ref,
            handoff.evidence_pack_ref,
        ],
        exact_revision_upstream_types={"runtime_evidence", "evidence_pack"},
    )
    assert result.outcome == "blocked_before_commit"
    assert result.commit_started is False
    assert result.artifact_ref is None
    assert _store_snapshot(store.root) == before


def test_runtime_evidence_consolidation_compat_write_fails_before_pending(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    tampered = copy.deepcopy(handoff.derived_payload)
    tampered["claims_real_runtime_success"] = True
    write_arguments = _runtime_consolidation_store_arguments(handoff)
    write_arguments["payload"] = tampered
    before = _store_snapshot(store.root)

    with pytest.raises(ArtifactStoreError):
        store.write(**write_arguments)

    assert _store_snapshot(store.root) == before


def test_semantic_reservation_validation_failure_keeps_c5_attempt_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    original = artifact_store_module.project_artifact_write_intent
    invocation_count = 0

    def fail_second_projection(**kwargs):
        nonlocal invocation_count
        invocation_count += 1
        if invocation_count == 2:
            raise ValueError("semantic TOCTOU drift")
        return original(**kwargs)

    monkeypatch.setattr(
        artifact_store_module,
        "project_artifact_write_intent",
        fail_second_projection,
    )
    before = _store_snapshot(store.root)
    result = store.write_with_result(
        **_runtime_consolidation_store_arguments(handoff)
    )

    assert result.outcome == "partial"
    assert result.commit_started is True
    assert result.failure_stage == "commit_verification"
    assert result.pending_marker_state == "absent"
    assert result.revision_state == "absent"
    assert result.recovery_available is False
    assert result.recovery_authorized is False
    assert _store_snapshot(store.root) == before


def test_semantic_reservation_loser_and_recovery_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    original_projector = artifact_store_module.project_artifact_write_intent
    invocation_count = 0

    def fail_second_projection(**kwargs):
        nonlocal invocation_count
        invocation_count += 1
        if invocation_count == 2:
            raise ValueError("semantic TOCTOU drift")
        return original_projector(**kwargs)

    monkeypatch.setattr(
        artifact_store_module,
        "project_artifact_write_intent",
        fail_second_projection,
    )
    original_cleanup = store._unlink_exact_semantic_pending_marker
    monkeypatch.setattr(
        store,
        "_unlink_exact_semantic_pending_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("reservation cleanup failed")
        ),
    )
    winner = store.write_with_result(
        **_runtime_consolidation_store_arguments(handoff)
    )
    assert winner.outcome == "partial"
    assert winner.commit_started is True
    assert winner.failure_stage == "pending_marker_cleanup"
    assert winner.pending_marker_state == "present"
    assert winner.recovery_available is False

    monkeypatch.setattr(
        artifact_store_module,
        "project_artifact_write_intent",
        original_projector,
    )
    monkeypatch.setattr(
        store,
        "_unlink_exact_semantic_pending_marker",
        original_cleanup,
    )
    loser = store.write_with_result(
        **_runtime_consolidation_store_arguments(handoff)
    )
    assert loser.outcome == "partial"
    assert loser.commit_started is False
    assert loser.failure_stage == "admission_validation"
    assert loser.pending_marker_state == "present"
    assert loser.recovery_available is False
    recovery = store.recover_pending_writes()
    assert recovery == [
        {
            "feature_id": FEATURE_ID,
            "artifact_type": "runtime_evidence",
            "artifact_hash": handoff.semantic_intent.expected_artifact_hash,
            "status": "blocked",
            "reason": "semantic_recovery_not_authorized",
        }
    ]
    assert Path(str(winner.pending_marker_path)).exists()


def test_semantic_reservation_binding_tamper_is_admission_failure(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    intent = handoff.semantic_intent
    pending_path = store._semantic_pending_write_path(
        FEATURE_ID,
        "runtime_evidence",
        intent.commit_conflict_key_hash,
    )
    revision_path = store._revision_artifact_path(
        FEATURE_ID,
        "runtime_evidence",
        intent.expected_artifact_hash,
    )
    latest_path = store._artifact_path(FEATURE_ID, "runtime_evidence")
    marker = json.loads(
        store._serialize_semantic_pending_write(
            feature_id=FEATURE_ID,
            artifact_type="runtime_evidence",
            artifact_hash=intent.expected_artifact_hash,
            revision_path=revision_path,
            latest_path=latest_path,
            semantic_intent=intent,
        )
    )
    marker["semantic_binding_version"] = "tampered"
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.write_text(
        json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = _store_snapshot(store.root)

    result = store.write_with_result(
        **_runtime_consolidation_store_arguments(handoff)
    )

    assert result.outcome == "blocked_before_commit"
    assert result.commit_started is False
    assert result.failure_stage == "admission_validation"
    assert result.pending_marker_state == "invalid"
    assert not revision_path.exists()
    assert _store_snapshot(store.root) == before


def test_semantic_reservation_racing_full_key_collision_is_admission_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    intent = handoff.semantic_intent
    revision_path = store._revision_artifact_path(
        FEATURE_ID,
        "runtime_evidence",
        intent.expected_artifact_hash,
    )
    latest_path = store._artifact_path(FEATURE_ID, "runtime_evidence")
    marker = json.loads(
        store._serialize_semantic_pending_write(
            feature_id=FEATURE_ID,
            artifact_type="runtime_evidence",
            artifact_hash=intent.expected_artifact_hash,
            revision_path=revision_path,
            latest_path=latest_path,
            semantic_intent=intent,
        )
    )
    collision_key = dict(intent.commit_conflict_key)
    collision_key["predecessor_artifact_hash"] = "0" * 64
    marker["commit_conflict_key"] = collision_key
    marker["commit_conflict_key_hash"] = artifact_store_module.hash_action_identity(
        collision_key,
        expected_hash_domain=(
            artifact_store_module.SEMANTIC_CONFLICT_HASH_DOMAIN
        ),
    )
    collision_bytes = (
        json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    def install_competing_marker(path: Path, _content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(collision_bytes, encoding="utf-8")
        raise FileExistsError(str(path))

    monkeypatch.setattr(
        store,
        "_write_text_exclusive_atomic",
        install_competing_marker,
    )
    result = store.write_with_result(
        **_runtime_consolidation_store_arguments(handoff)
    )

    assert result.outcome == "blocked_before_commit"
    assert result.commit_started is False
    assert result.failure_stage == "admission_validation"
    assert result.revision_state == "absent"
    assert Path(str(result.pending_marker_path)).read_text(encoding="utf-8") == (
        collision_bytes
    )


def test_semantic_reservation_full_write_chain_has_one_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    first_handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(arguments)
    )
    first_spec = arguments["verification_operation"]
    first_protocol = first_spec.protocol_binding
    first_report = copy.deepcopy(
        store.read(first_protocol.accepted_resume_report_ref)["data"]
    )
    first_report["resume_id"] = "verification_only_runtime_resume_002"
    first_report["approved_by"] = "second-human"
    first_report["approved_at"] = "2026-08-04T00:00:00Z"
    second_report_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="resume_report",
        payload=first_report,
        status="success",
        upstream_refs=[first_protocol.checkpoint_ref],
        exact_revision_upstream_types={"workflow_checkpoint"},
    )
    second_spec = dataclasses.replace(
        first_spec,
        protocol_binding=VerificationProtocolBinding(
            checkpoint_ref=first_protocol.checkpoint_ref,
            accepted_resume_report_ref=second_report_ref,
            resume_id="verification_only_runtime_resume_002",
            approved_by="second-human",
        ),
    )
    second_arguments = {
        **arguments,
        "resume_id": "verification_only_runtime_resume_002",
        "approved_by": "second-human",
        "verification_operation": second_spec,
    }
    second_handoff = local_entry_module._load_runtime_evidence_consolidation_handoff(
        **_runtime_consolidation_loader_arguments(second_arguments)
    )
    assert (
        first_handoff.operation.approval_identity_hash
        != second_handoff.operation.approval_identity_hash
    )
    assert (
        first_handoff.semantic_intent.commit_conflict_key_hash
        == second_handoff.semantic_intent.commit_conflict_key_hash
    )
    assert (
        first_handoff.semantic_intent.expected_artifact_hash
        != second_handoff.semantic_intent.expected_artifact_hash
    )

    admission_barrier = Barrier(2)
    loser_validated = Event()
    thread_state = local()
    original_projector = artifact_store_module.project_artifact_write_intent
    original_install = ArtifactStore._write_text_exclusive_atomic
    original_validate = ArtifactStore._validate_semantic_pending_locator

    def synchronized_projector(**kwargs):
        result = original_projector(**kwargs)
        invocation = getattr(thread_state, "projection_invocation", 0) + 1
        thread_state.projection_invocation = invocation
        if invocation == 1:
            admission_barrier.wait(timeout=10)
        return result

    def coordinated_install(selected, path, content):
        try:
            original_install(selected, path, content)
        except FileExistsError:
            thread_state.lost_reservation = True
            raise
        if not loser_validated.wait(timeout=10):
            raise AssertionError("Competing reservation was not validated.")

    def recording_validate(selected, path, **kwargs):
        result = original_validate(selected, path, **kwargs)
        if getattr(thread_state, "lost_reservation", False):
            loser_validated.set()
        return result

    monkeypatch.setattr(
        artifact_store_module,
        "project_artifact_write_intent",
        synchronized_projector,
    )
    monkeypatch.setattr(
        ArtifactStore,
        "_write_text_exclusive_atomic",
        coordinated_install,
    )
    monkeypatch.setattr(
        ArtifactStore,
        "_validate_semantic_pending_locator",
        recording_validate,
    )
    stores = (ArtifactStore(store.root), ArtifactStore(store.root))
    handoffs = (first_handoff, second_handoff)
    results: list[ArtifactWriteResult] = []
    errors: list[BaseException] = []
    baseline_runtime_revisions = len(
        store.list_feature_artifact_revisions(FEATURE_ID, "runtime_evidence")
    )

    def write(selected: ArtifactStore, handoff: Any) -> None:
        try:
            results.append(
                selected.write_with_result(
                    **_runtime_consolidation_store_arguments(handoff)
                )
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        Thread(target=write, args=(selected, handoff))
        for selected, handoff in zip(stores, handoffs)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert sorted(result.outcome for result in results) == ["committed", "partial"]
    committed = next(result for result in results if result.outcome == "committed")
    loser = next(result for result in results if result.outcome == "partial")
    assert committed.commit_started is True
    assert committed.artifact_ref is not None
    assert loser.commit_started is False
    assert loser.failure_stage == "admission_validation"
    children = runtime_evidence_consolidation_child_refs(
        store,
        feature_id=FEATURE_ID,
        prior_ref=first_handoff.prior_runtime_evidence_ref,
        feature_adapter="stagger_c4_implementation_evidence_v1",
    )
    assert children == (committed.artifact_ref,)
    assert len(
        store.list_feature_artifact_revisions(FEATURE_ID, "runtime_evidence")
    ) == baseline_runtime_revisions + 1
    pending_root = store.root / "features" / FEATURE_ID / "p"
    assert list(pending_root.rglob("*.json")) == []


def test_runtime_evidence_consolidation_committed_receipt_is_terminal_truth(
    tmp_path: Path,
) -> None:
    store, build_result, runtime_result, runtime_root, action = (
        _c4_public_runtime_evidence_handoff(tmp_path)
    )
    arguments = _runtime_consolidation_preflight_arguments(
        store,
        build_result,
        runtime_result,
        runtime_root=runtime_root,
        action=action,
    )
    preflight = preflight_local_runtime(**arguments)
    assert isinstance(preflight, VerificationOperationPreflightResultV1)
    assert preflight.approval_identity_hash is not None
    result = resume_local_runtime(
        **_runtime_consolidation_execute_arguments(
            arguments,
            expected_hash=preflight.approval_identity_hash,
        )
    )
    assert isinstance(result, VerificationOperationResultV1)
    assert isinstance(result.variant_result, EvidenceConsolidationResultV1)
    assert result.platform_status == "completed"
    assert result.failure_stage is None
    assert result.variant_result.runtime_evidence_ref is not None
    assert len(result.store_receipts) == 1
    assert result.store_receipts[0].artifact_write_result.outcome == "committed"


def _runtime_terminal_preflight_arguments(
    store: ArtifactStore,
    build_result: dict[str, object],
    runtime_result: dict[str, Any],
    *,
    runtime_root: Path,
) -> dict[str, object]:
    checkpoint = build_result["workflow_checkpoint"]
    assert isinstance(checkpoint, dict)
    checkpoint_ref = checkpoint["artifact_ref"]
    assert isinstance(checkpoint_ref, dict)
    report_ref = runtime_result["resume_report"]["artifact_ref"]
    runtime_ref = runtime_result["runtime_evidence"]["artifact_ref"]
    return {
        "run_root": runtime_root,
        "artifact_store_root": store.root,
        "feature_id": FEATURE_ID,
        "checkpoint_path": checkpoint_ref["path"],
        "checkpoint_hash": checkpoint_ref["artifact_hash"],
        "resume_id": "verification_only_runtime_resume_001",
        "approved_by": "human",
        "runtime_terminalization_only": True,
        "accepted_resume_report_path": report_ref["path"],
        "accepted_resume_report_hash": report_ref["artifact_hash"],
        "runtime_evidence_path": runtime_ref["path"],
        "runtime_evidence_hash": runtime_ref["artifact_hash"],
    }


def _runtime_terminal_execute_arguments(
    preflight_arguments: dict[str, object],
    *,
    expected_hash: str,
) -> dict[str, object]:
    return {
        **preflight_arguments,
        "settings_path": Path(str(preflight_arguments["run_root"]))
        / "unused-runtime.yaml",
        "allow_game_launch": False,
        "runtime_plugin_destination": None,
        "allow_game_directory_write": False,
        "expected_runtime_terminal_identity_hash": expected_hash,
    }


def _runtime_preflight_arguments(
    store: ArtifactStore,
    build_result: dict[str, object],
    *,
    runtime_root: Path,
) -> dict[str, object]:
    checkpoint = build_result["workflow_checkpoint"]
    assert isinstance(checkpoint, dict)
    checkpoint_ref = checkpoint["artifact_ref"]
    assert isinstance(checkpoint_ref, dict)
    return {
        "run_root": runtime_root,
        "artifact_store_root": store.root,
        "feature_id": FEATURE_ID,
        "checkpoint_path": checkpoint_ref["path"],
        "checkpoint_hash": checkpoint_ref["artifact_hash"],
        "resume_id": "verification_only_runtime_resume_001",
        "approved_by": "human",
        "injected_runtime_admission": dict(RUNTIME_ADMISSION),
        "runtime_evidence_only": True,
    }


def _runtime_execute_arguments(
    store: ArtifactStore,
    build_result: dict[str, object],
    *,
    runtime_root: Path,
    expected_hash: str | None,
    runtime_factory,
) -> dict[str, object]:
    return {
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        ),
        "settings_path": runtime_root / "unused-runtime.yaml",
        "allow_game_launch": False,
        "runtime_plugin_destination": None,
        "allow_game_directory_write": False,
        "runtime_evidence_factory": runtime_factory,
        "expected_runtime_execution_identity_hash": expected_hash,
    }


def _runtime_payload(feature_id, build, feature_spec):
    return build_fake_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=build.get("input_execution_mode"),
        acceptance_criteria=tuple(feature_spec.get("acceptance_criteria") or ()),
        runtime_verification_plan=tuple(
            feature_spec.get("runtime_verification_plan") or ()
        ),
    )


def _unverified_runtime_payload(feature_id, build, feature_spec):
    return build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=build.get("input_execution_mode"),
        evidence_items=(),
        startup_loaded=False,
        gameplay_behavior_verified=False,
        verification_status="inconclusive",
        limitations=("No product observation was supplied.",),
        acceptance_criteria=tuple(feature_spec.get("acceptance_criteria") or ()),
        runtime_verification_plan=tuple(
            feature_spec.get("runtime_verification_plan") or ()
        ),
    )


def _verified_runtime_payload(feature_id, build, feature_spec):
    acceptance_criteria = tuple(feature_spec.get("acceptance_criteria") or ())
    return build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=build.get("input_execution_mode"),
        evidence_items=(
            RuntimeEvidenceItem(
                item_type="runtime_acceptance",
                source="bounded_test_runtime",
                locator="current-run",
                supports_acceptance=acceptance_criteria,
                confidence=1.0,
                raw_excerpt="Exact acceptance behavior was observed.",
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=acceptance_criteria,
        runtime_verification_plan=tuple(
            feature_spec.get("runtime_verification_plan") or ()
        ),
        plugin_marker_binding={
            "marker_source": "bounded_test_runtime",
            "markers": [
                {
                    "acceptance_criterion": criterion,
                    "marker": f"MARKER_{index}",
                    "observed": True,
                }
                for index, criterion in enumerate(
                    acceptance_criteria,
                    start=1,
                )
            ],
        },
    )


def _verified_runtime_payload_without_marker(feature_id, build, feature_spec):
    acceptance_criteria = tuple(feature_spec.get("acceptance_criteria") or ())
    return build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=build.get("input_execution_mode"),
        evidence_items=(
            RuntimeEvidenceItem(
                item_type="runtime_acceptance",
                source="bounded_test_runtime",
                locator="current-run",
                supports_acceptance=acceptance_criteria,
                confidence=1.0,
                raw_excerpt="Acceptance behavior was observed without marker binding.",
            ),
        ),
        startup_loaded=True,
        gameplay_behavior_verified=True,
        verification_status="verified",
        acceptance_criteria=acceptance_criteria,
        runtime_verification_plan=tuple(
            feature_spec.get("runtime_verification_plan") or ()
        ),
    )


def _verification_inputs(
    tmp_path: Path,
) -> tuple[ArtifactStore, VerificationOnlyContinuationInput]:
    store = ArtifactStore(tmp_path / "artifacts")
    source_root = tmp_path / "source"
    source_root.mkdir()
    files = {
        "Plugin.cs": "plugin source",
        "Patches/HitFeedbackBehaviorPatch.cs": "patch source",
    }
    for relative_path, content in files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    source_hashes = {
        relative_path: _sha256(source_root / relative_path)
        for relative_path in files
    }
    feature_payload = {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "Fresh verification FeatureSpec.",
        "feature_id": FEATURE_ID,
        "user_request": USER_REQUEST,
        "target_behavior": "Verify existing behavior.",
        "non_goals": ["No source change."],
        "target_mod": TARGET_MOD,
        "risk_level": "high",
        "acceptance_criteria": ["Existing behavior remains correct."],
        "evidence_requirements": ["Current source identity."],
        "runtime_verification_plan": ["Run after a fresh Build."],
        "blocked": False,
        "blockers": [],
        "source_lineage": {
            "root": str(source_root.resolve()),
            "read_only": True,
            "files": source_hashes,
        },
    }
    feature_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="feature_spec",
        payload=feature_payload,
        status="success",
    )
    evidence_blockers = [
        {
            "code": HANDOFF_CODE,
            "message": "Existing source requires fresh Build verification, not a patch.",
        }
    ]
    trace_refs = [
        f"feature_spec:{feature_ref.artifact_hash}",
        f"source:sha256:{source_hashes['Plugin.cs'].lower()}",
    ]
    evidence_payload = {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "Fresh source evidence is ready for verification only.",
        "query": USER_REQUEST,
        "readiness": "partial",
        "can_generate_patch": False,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": False,
        "identity_schema_version": "1.0",
        "identity_field_mapping": {},
        "items": [],
        "gaps": ["Fresh Build is missing."],
        "excluded": [],
        "blockers": evidence_blockers,
        "retrieval_methods_used": ["source_inspection"],
        "missing_evidence": ["Fresh BuildResult"],
        "disabled_modes": {},
        "timing": {},
        "trace_refs": trace_refs,
    }
    evidence_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="evidence_pack",
        payload=evidence_payload,
        status="blocked",
        blockers=evidence_blockers,
        trace_refs=trace_refs,
        upstream_refs=[feature_ref],
    )
    return store, VerificationOnlyContinuationInput(
        feature_spec_ref=feature_ref,
        evidence_pack_ref=evidence_ref,
    )


def _real_build_factory(tmp_path: Path):
    build_root = tmp_path / "build"
    source_root = tmp_path / "source"
    output = build_root / "bin" / "BetterHitFeedback.dll"

    def factory(feature_id: str, input_execution_mode: str | None) -> BuildResult:
        def runner(_: BuildProfile) -> BuildCommandResult:
            shutil.copytree(source_root, build_root, dirs_exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"verification-only build")
            return BuildCommandResult(exit_code=0, stdout="Build succeeded")

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="verification_only_test",
                build_system="dotnet",
                working_directory=str(build_root),
                command=("dotnet", "build"),
                timeout_seconds=120,
                expected_artifacts=("bin/BetterHitFeedback.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    return factory


def _failed_build_factory(tmp_path: Path):
    build_root = tmp_path / "failed-build"
    source_root = tmp_path / "source"

    def factory(feature_id: str, input_execution_mode: str | None) -> BuildResult:
        def runner(_: BuildProfile) -> BuildCommandResult:
            shutil.copytree(source_root, build_root, dirs_exist_ok=True)
            return BuildCommandResult(exit_code=1, stderr="Build failed")

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="verification_only_failed_test",
                build_system="dotnet",
                working_directory=str(build_root),
                command=("dotnet", "build"),
                timeout_seconds=120,
                expected_artifacts=("bin/BetterHitFeedback.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    return factory


def _public_build_arguments(
    store: ArtifactStore,
    continuation: VerificationOnlyContinuationInput,
) -> dict[str, object]:
    return {
        "artifact_store_root": store.root,
        "feature_id": FEATURE_ID,
        "feature_spec_path": continuation.feature_spec_ref.path,
        "feature_spec_hash": continuation.feature_spec_ref.artifact_hash,
        "evidence_pack_path": continuation.evidence_pack_ref.path,
        "evidence_pack_hash": continuation.evidence_pack_ref.artifact_hash,
        "run_id": "verification_only_run_001",
        "request_id": "verification_only_request_001",
        "user_request": USER_REQUEST,
        "target_domain": "gtfo",
        "target_mod": TARGET_MOD,
    }


def _store_failure_result(
    store: ArtifactStore,
    *,
    artifact_type: str,
    outcome: str,
) -> ArtifactWriteResult:
    partial = outcome == "partial"
    feature_root = store.root / "features" / FEATURE_ID
    return ArtifactWriteResult(
        outcome=outcome,  # type: ignore[arg-type]
        feature_id=FEATURE_ID,
        artifact_type=artifact_type,
        artifact_hash="f" * 64,
        artifact_ref=None,
        revision_path=str(feature_root / "r" / artifact_type / ("f" * 32 + ".json")),
        latest_alias_path=str(feature_root / f"{artifact_type}.json"),
        pending_marker_path=str(
            feature_root / "p" / artifact_type / ("f" * 32 + ".json")
        ),
        commit_started=partial,
        revision_state="valid" if partial else "absent",
        latest_alias_state="absent",
        pending_marker_state="present" if partial else "absent",
        failure_stage=(
            "latest_alias_write" if partial else "admission_validation"
        ),
        failure_class="ArtifactStoreError",
        failure_message="injected Store outcome",
        recovery_available=partial,
        recovery_authorized=False,
    )


def _initial_state():
    return create_initial_state(
        run_id="verification_only_run_001",
        request_id="verification_only_request_001",
        user_request=USER_REQUEST,
        target_domain="gtfo",
        target_mod=TARGET_MOD,
    )


def _preflight(
    store: ArtifactStore,
    continuation: VerificationOnlyContinuationInput,
) -> dict[str, object]:
    return preflight_verification_only_continuation(
        store,
        continuation,
        run_id="verification_only_run_001",
        request_id="verification_only_request_001",
        user_request=USER_REQUEST,
        target_mod=TARGET_MOD,
    )


def _state_ref(state: dict[str, object], artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        feature_id=str(state["feature_id"]),
        artifact_type=artifact_type,
        path=str(state["artifacts"][artifact_type]),  # type: ignore[index]
        artifact_hash=str(state["artifact_hashes"][artifact_type]),  # type: ignore[index]
    )


def _resume_payload(checkpoint: dict[str, object]) -> ResumePayload:
    return ResumePayload(
        resume_id="verification_only_resume_001",
        run_id=str(checkpoint["run_id"]),
        request_id=str(checkpoint["request_id"]),
        feature_id=str(checkpoint["feature_id"]),
        stage="build",
        decision="approve",
        approved_by="human",
        approved_at="2026-08-02T00:00:00Z",
        artifact_refs=tuple(checkpoint["artifact_refs"]),  # type: ignore[arg-type]
        runtime_admission={
            "status": "admitted",
            "authorization_scope": "this_resume_only",
            "requested_side_effects": ["runtime_execution"],
            "authorized_side_effects": ["runtime_execution"],
            "provider": "injected_test",
        },
    )


C4_CRITERION = (
    "Each ES_Hitreact.ActivateState invocation with General.Enabled=true, "
    "a reaction type of Micro, Light, or Heavy, and a source that resolves "
    "to a locally owned PlayerAgent produces no more than one additional "
    "yellow X, one feature-attributable short audio cue, and one "
    "STAGGER_FEEDBACK_SHOWN signal within that invocation."
)
C4_EVIDENCE_IDS = (
    "stagger_fresh_audio_source",
    "stagger_fresh_direct_activate_state_source",
    "stagger_fresh_source_contract_report",
    "stagger_fresh_yellow_x_source",
)
UNCHANGED_CRITERION = "A separate Runtime criterion remains not observed."


def _c4_public_runtime_evidence_handoff(
    tmp_path: Path,
) -> tuple[ArtifactStore, dict[str, object], dict[str, Any], Path, dict[str, Any]]:
    store, continuation, action = _c4_verification_inputs(tmp_path)
    build_result = execute_verification_only_build_continuation(
        **_public_build_arguments(store, continuation),
        build_result_factory=_real_build_factory(tmp_path),
        allow_build_execution=True,
    )
    assert build_result["status"] == "completed"
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    preflight = preflight_local_runtime(
        **_runtime_preflight_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
        )
    )
    runtime_result = resume_local_runtime(
        **_runtime_execute_arguments(
            store,
            build_result,
            runtime_root=runtime_root,
            expected_hash=preflight["runtime_execution_identity_hash"],
            runtime_factory=_c4_unverified_runtime_payload,
        )
    )
    assert runtime_result["status"] == "completed"
    return store, build_result, runtime_result, runtime_root, action


def _c4_verification_inputs(
    tmp_path: Path,
) -> tuple[ArtifactStore, VerificationOnlyContinuationInput, dict[str, Any]]:
    store = ArtifactStore(tmp_path / "artifacts")
    source_root = tmp_path / "source"
    source_root.mkdir()
    files = {
        "Plugin.cs": "plugin source",
        "Patches/HitFeedbackBehaviorPatch.cs": "patch source",
    }
    for relative_path, content in files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    source_hashes = {
        relative_path: _sha256(source_root / relative_path)
        for relative_path in files
    }
    feature_payload = {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "Fresh C4 verification FeatureSpec.",
        "feature_id": FEATURE_ID,
        "user_request": USER_REQUEST,
        "target_behavior": "Verify existing C4 behavior.",
        "non_goals": ["No source change."],
        "target_mod": TARGET_MOD,
        "risk_level": "high",
        "acceptance_criteria": [C4_CRITERION, UNCHANGED_CRITERION],
        "evidence_requirements": ["Current deterministic source contract."],
        "runtime_verification_plan": ["Bind implementation evidence."],
        "blocked": False,
        "blockers": [],
        "source_lineage": {
            "root": str(source_root.resolve()),
            "read_only": True,
            "files": source_hashes,
        },
    }
    feature_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="feature_spec",
        payload=feature_payload,
        status="success",
    )
    evidence_root = tmp_path / "implementation-evidence"
    evidence_root.mkdir()
    source_path = source_root / "Patches/HitFeedbackBehaviorPatch.cs"
    source_hash = _sha256(source_path)
    report = {
        "status": "passed",
        "feature_spec_artifact_hash": feature_ref.artifact_hash,
        "source_sha256_before": source_hash,
        "source_sha256_after": source_hash,
        "target_code_executed": False,
        "invocation_counts": {
            "visual": 1,
            "audio": 1,
            "marker": 1,
            "recursive_postfix": 0,
        },
        "loop_count": 0,
        "checks": {
            name: True
            for name in (
                "one_visual_call",
                "one_audio_call",
                "one_marker_emission",
                "no_loop_in_postfix",
                "outputs_not_nested_in_loop",
                "no_recursive_postfix_call",
                "enabled_guard_precedes_outputs",
                "reaction_guard_precedes_outputs",
                "source_guard_precedes_outputs",
                "marker_guard_precedes_marker",
                "visual_precedes_audio",
                "audio_precedes_marker_guard",
                "source_unchanged_during_inspection",
            )
        },
    }
    report_path = evidence_root / "source_contract_report.json"
    repeat_path = evidence_root / "source_contract_report_repeat.json"
    report_bytes = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    report_path.write_text(report_bytes, encoding="utf-8")
    repeat_path.write_text(report_bytes, encoding="utf-8")
    report_hash = _sha256(report_path)
    evidence_blockers = [
        {
            "code": HANDOFF_CODE,
            "message": "Existing source requires fresh verification, not a patch.",
        }
    ]
    evidence_items = [
        {
            "evidence_id": "stagger_fresh_source_contract_report",
            "file_hash": report_hash,
            "source_hash": report_hash,
            "source_path": str(report_path.resolve()),
        },
        *[
            {
                "evidence_id": evidence_id,
                "file_hash": source_hash,
                "source_hash": source_hash,
                "source_path": str(source_path.resolve()),
            }
            for evidence_id in C4_EVIDENCE_IDS
            if evidence_id != "stagger_fresh_source_contract_report"
        ],
    ]
    evidence_payload = {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "Fresh C4 evidence is ready for verification only.",
        "query": USER_REQUEST,
        "readiness": "partial",
        "can_generate_patch": False,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": False,
        "identity_schema_version": "1.0",
        "identity_field_mapping": {},
        "items": evidence_items,
        "gaps": ["C4 RuntimeEvidence binding is missing."],
        "excluded": [],
        "blockers": evidence_blockers,
        "retrieval_methods_used": ["source_inspection"],
        "missing_evidence": ["Bound implementation evidence"],
        "disabled_modes": {},
        "timing": {},
        "trace_refs": [f"feature_spec:{feature_ref.artifact_hash}"],
    }
    evidence_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="evidence_pack",
        payload=evidence_payload,
        status="blocked",
        blockers=evidence_blockers,
        trace_refs=evidence_payload["trace_refs"],
        upstream_refs=[feature_ref],
    )
    criterion_id = "sha256:" + hashlib.sha256(
        C4_CRITERION.encode("utf-8")
    ).hexdigest()
    action = {
        "delta": {
            "schema_version": "verification_only_criterion_evidence_delta_v1",
            "feature_adapter": "stagger_c4_implementation_evidence_v1",
            "criterion_id": criterion_id,
            "acceptance_criterion": C4_CRITERION,
            "before": {"outcome": "not_observed", "evidence_strength": "none"},
            "after": {
                "outcome": "true",
                "evidence_strength": "bound_implementation_evidence",
            },
            "evidence_ids": list(C4_EVIDENCE_IDS),
            "file_roles": [
                "source_contract_report",
                "source_contract_report_repeat",
                "target_source",
            ],
            "evidence_level": "implementation",
            "new_build_performed": False,
            "new_runtime_performed": False,
            "product_source_modified": False,
        },
        "bindings": (
            ImplementationEvidenceFileBinding(
                role="source_contract_report",
                absolute_path=str(report_path.resolve()),
                content_sha256=report_hash,
            ),
            ImplementationEvidenceFileBinding(
                role="source_contract_report_repeat",
                absolute_path=str(repeat_path.resolve()),
                content_sha256=report_hash,
            ),
            ImplementationEvidenceFileBinding(
                role="target_source",
                absolute_path=str(source_path.resolve()),
                content_sha256=source_hash,
                logical_target_path="Patches/HitFeedbackBehaviorPatch.cs",
            ),
        ),
        "evidence_ref": evidence_ref,
        "feature_ref": feature_ref,
    }
    return (
        store,
        VerificationOnlyContinuationInput(
            feature_spec_ref=feature_ref,
            evidence_pack_ref=evidence_ref,
        ),
        action,
    )


def _c4_unverified_runtime_payload(feature_id, build, feature_spec):
    payload = build_real_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=build.get("input_execution_mode"),
        evidence_items=(),
        startup_loaded=False,
        gameplay_behavior_verified=False,
        verification_status="inconclusive",
        limitations=("C4 implementation evidence is not yet bound.",),
        acceptance_criteria=(C4_CRITERION, UNCHANGED_CRITERION),
        runtime_verification_plan=tuple(
            feature_spec.get("runtime_verification_plan") or ()
        ),
    )
    payload["stagger_acceptance_evaluation"] = {
        "criteria": [
            {
                "acceptance_criterion": C4_CRITERION,
                "outcome": "not_observed",
                "evidence_strength": "none",
                "evidence_refs": [],
            },
            {
                "acceptance_criterion": UNCHANGED_CRITERION,
                "outcome": "not_observed",
                "evidence_strength": "none",
                "evidence_refs": [],
            },
        ],
        "attempt_completion": "incomplete",
        "overall_acceptance": "inconclusive",
    }
    return payload


def _runtime_consolidation_preflight_arguments(
    store: ArtifactStore,
    build_result: dict[str, object],
    runtime_result: dict[str, Any],
    *,
    runtime_root: Path,
    action: dict[str, Any],
) -> dict[str, Any]:
    checkpoint_ref = build_result["workflow_checkpoint"]["artifact_ref"]
    report_ref = runtime_result["resume_report"]["artifact_ref"]
    runtime_ref = runtime_result["runtime_evidence"]["artifact_ref"]
    evidence_ref = action["evidence_ref"]
    feature_ref = action["feature_ref"]
    build_ref = ArtifactRef(**build_result["build_result"]["artifact_ref"])
    operation = VerificationOperationSpec(
        operation_kind=EVIDENCE_CONSOLIDATION_KIND,
        operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        attempt_policy=VerificationAttemptPolicy(
            attempt_budget=1,
            retry_allowed=False,
            recovery_allowed=False,
        ),
        protocol_binding=VerificationProtocolBinding(
            checkpoint_ref=ArtifactRef(**checkpoint_ref),
            accepted_resume_report_ref=ArtifactRef(**report_ref),
            resume_id="verification_only_runtime_resume_001",
            approved_by="human",
        ),
        variant_payload=EvidenceConsolidationOperationV1(
            feature_spec_ref=feature_ref,
            build_result_ref=build_ref,
            prior_runtime_evidence_ref=ArtifactRef(**runtime_ref),
            evidence_pack_ref=evidence_ref,
            canonical_delta=action["delta"],
            execution_file_bindings=action["bindings"],
        ),
    )
    return {
        "run_root": runtime_root,
        "artifact_store_root": store.root,
        "verification_operation": operation,
    }


def _runtime_consolidation_execute_arguments(
    preflight_arguments: dict[str, Any],
    *,
    expected_hash: str,
) -> dict[str, Any]:
    return {
        **{
            **preflight_arguments,
            "verification_operation": project_verification_operation(
                preflight_arguments["verification_operation"]
            ),
        },
        "allow_game_launch": False,
        "runtime_plugin_destination": None,
        "allow_game_directory_write": False,
        "expected_approval_identity_hash": expected_hash,
    }


def _runtime_consolidation_loader_arguments(
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    operation = project_verification_operation(
        arguments["verification_operation"]
    )
    protocol = operation.protocol_binding
    return {
        "run_root": arguments["run_root"],
        "artifact_store_root": arguments["artifact_store_root"],
        "feature_id": protocol.checkpoint_ref.feature_id,
        "checkpoint_path": protocol.checkpoint_ref.path,
        "checkpoint_hash": protocol.checkpoint_ref.artifact_hash,
        "operation": operation,
    }


def _runtime_consolidation_store_arguments(
    handoff: Any,
) -> dict[str, Any]:
    return {
        "feature_id": FEATURE_ID,
        "artifact_type": "runtime_evidence",
        "payload": dict(handoff.derived_payload),
        "status": "blocked",
        "upstream_refs": [
            handoff.build_handoff.build_ref,
            handoff.build_handoff.feature_spec_ref,
            handoff.prior_runtime_evidence_ref,
            handoff.evidence_pack_ref,
        ],
        "exact_revision_upstream_types": {
            "runtime_evidence",
            "evidence_pack",
        },
        "semantic_intent": handoff.semantic_intent,
    }


def _artifact_counts(store: ArtifactStore) -> dict[str, int]:
    return {
        artifact_type: len(
            store.list_feature_artifact_revisions(FEATURE_ID, artifact_type)
        )
        for artifact_type in store.registry.artifact_types()
    }


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _store_snapshot(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)
