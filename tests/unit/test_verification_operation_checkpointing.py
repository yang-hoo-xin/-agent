"""Focused tests for typed verification checkpoint admission."""

from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import replace
from unittest.mock import Mock

import pytest

import src.mod_agent.workflow.checkpointing as checkpointing_module
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.verification_operations import (
    EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
    EVIDENCE_CONSOLIDATION_KIND,
    ENVELOPE_CONTRACT_VERSION,
    RUNTIME_EVIDENCE_ONLY_COMPLETION,
    RUNTIME_EXECUTION_CONTRACT_VERSION,
    RUNTIME_EXECUTION_KIND,
    RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
    RUNTIME_TERMINALIZATION_KIND,
    RUNTIME_WORKFLOW_COMPLETION,
    VERIFICATION_BUILD_CONTRACT_VERSION,
    VERIFICATION_BUILD_KIND,
    AcceptedResumeRecoveryAttemptV1,
    BuildInvocationProtocolBindingV1,
    EvidenceConsolidationOperationV1,
    InitialAttemptV1,
    NewRuntimeResumeProtocolBindingV1,
    ObservationRetryAttemptV1,
    RuntimeExecutionOperationV1,
    RuntimeTerminalizationOperationV1,
    VerificationAttemptPolicy,
    VerificationBuildOperationV1,
    VerificationCheckpointIdentityV1,
    VerificationOperationEnvelope,
    VerificationOperationSpec,
    VerificationProtocolBinding,
    project_verification_operation,
    resolve_verification_operation,
)
from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore
from src.mod_agent.workflow.interrupts import ResumeDecision


FEATURE_ID = "feature-checkpoint-dispatch"
RESUME_ID = "resume-001"


class _ReadStore:
    def __init__(self, payloads: dict[ArtifactRef, dict[str, object]] | None = None):
        self.payloads = payloads or {}

    def read(self, ref: ArtifactRef) -> dict[str, object]:
        return {"data": self.payloads[ref]}


def _ref(artifact_type: str, name: str) -> ArtifactRef:
    return ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type=artifact_type,
        path=f"artifacts/{FEATURE_ID}/{artifact_type}/{name}.json",
        artifact_hash=f"sha256-{name}",
    )


def _decision() -> ResumeDecision:
    return ResumeDecision(
        status="accepted",
        allowed=True,
        reason="focused test admission",
        applied_updates={},
    )


def _checkpoint_identity() -> VerificationCheckpointIdentityV1:
    return VerificationCheckpointIdentityV1(
        checkpoint_id="checkpoint-001",
        run_id="run-001",
        request_id="request-001",
    )


def _build_envelope() -> VerificationOperationEnvelope:
    return project_verification_operation(
        VerificationOperationSpec(
            operation_kind=VERIFICATION_BUILD_KIND,
            operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=BuildInvocationProtocolBindingV1(
                run_id="run-001",
                request_id="request-001",
            ),
            variant_payload=VerificationBuildOperationV1(
                feature_spec_ref=_ref("feature_spec", "feature-spec"),
                evidence_pack_ref=_ref("evidence_pack", "evidence-pack"),
                user_request="Build the approved feature.",
                target_domain="gtfo",
                target_mod="CheckpointDispatch",
            ),
        )
    )


def _runtime_envelope(
    *,
    completion_scope: str,
    attempt_policy: InitialAttemptV1
    | ObservationRetryAttemptV1
    | AcceptedResumeRecoveryAttemptV1,
    protocol_binding: NewRuntimeResumeProtocolBindingV1
    | VerificationProtocolBinding,
) -> VerificationOperationEnvelope:
    return project_verification_operation(
        VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=attempt_policy,
            protocol_binding=protocol_binding,
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope=completion_scope,
                runtime_action_scope={
                    "allow_game_launch": False,
                    "allow_game_directory_write": False,
                },
            ),
        ),
        checkpoint_identity=_checkpoint_identity(),
    )


def _accepted_protocol(
    checkpoint_ref: ArtifactRef,
    report_ref: ArtifactRef,
) -> VerificationProtocolBinding:
    return VerificationProtocolBinding(
        checkpoint_ref=checkpoint_ref,
        accepted_resume_report_ref=report_ref,
        resume_id=RESUME_ID,
        approved_by="original-operator",
    )


def test_build_admission_validates_the_envelope_and_has_no_checkpoint_result() -> None:
    store = WorkflowCheckpointStore(_ReadStore())

    assert store.preflight_verification_operation(_build_envelope()) is None


@pytest.mark.parametrize(
    "completion_scope",
    (RUNTIME_EVIDENCE_ONLY_COMPLETION, RUNTIME_WORKFLOW_COMPLETION),
)
def test_initial_runtime_shapes_delegate_to_initial_resume_facts(
    monkeypatch: pytest.MonkeyPatch,
    completion_scope: str,
) -> None:
    checkpoint_ref = _ref("workflow_checkpoint", "checkpoint")
    envelope = _runtime_envelope(
        completion_scope=completion_scope,
        attempt_policy=InitialAttemptV1(),
        protocol_binding=NewRuntimeResumeProtocolBindingV1(
            checkpoint_ref=checkpoint_ref,
            resume_id=RESUME_ID,
            approved_by="current-operator",
        ),
    )
    expected = _decision()
    store = WorkflowCheckpointStore(_ReadStore())
    factual = Mock(return_value=expected)
    monkeypatch.setattr(store, "_preflight_resume_facts", factual)

    assert store.preflight_verification_operation(envelope) is expected
    factual.assert_called_once_with(checkpoint_ref, resume_id=RESUME_ID)


def _retry_fixture() -> tuple[
    VerificationOperationEnvelope,
    ArtifactRef,
    ArtifactRef,
    ArtifactRef,
    ArtifactRef,
]:
    checkpoint_ref = _ref("workflow_checkpoint", "checkpoint")
    report_ref = _ref("resume_report", "accepted-report")
    runtime_ref = _ref("runtime_evidence", "prior-runtime")
    repair_ref = _ref("repair_plan", "repair-plan")
    envelope = _runtime_envelope(
        completion_scope=RUNTIME_WORKFLOW_COMPLETION,
        attempt_policy=ObservationRetryAttemptV1(
            prior_runtime_evidence_ref=runtime_ref,
            repair_plan_ref=repair_ref,
            retry_number=1,
            retry_budget=2,
            retry_budget_remaining=0,
            current_attempt_approved_by="current-operator",
        ),
        protocol_binding=_accepted_protocol(checkpoint_ref, report_ref),
    )
    return envelope, checkpoint_ref, report_ref, runtime_ref, repair_ref


def test_observation_retry_admits_exact_protocol_and_attempt_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, checkpoint_ref, report_ref, runtime_ref, repair_ref = _retry_fixture()
    expected = (
        _decision(),
        report_ref,
        runtime_ref,
        repair_ref,
        {
            "retry_number": 1,
            "retry_budget": 2,
            "retry_budget_remaining_before_attempt": 1,
        },
    )
    store = WorkflowCheckpointStore(
        _ReadStore({report_ref: {"approved_by": "original-operator"}})
    )
    factual = Mock(return_value=expected)
    monkeypatch.setattr(
        store,
        "_preflight_runtime_observation_retry_facts",
        factual,
    )

    assert store.preflight_verification_operation(envelope) is expected
    factual.assert_called_once_with(checkpoint_ref, resume_id=RESUME_ID)


@pytest.mark.parametrize(
    "mismatch",
    (
        "resume_report_ref",
        "original_approved_by",
        "prior_runtime_ref",
        "repair_plan_ref",
        "retry_number",
        "retry_budget",
        "retry_budget_remaining",
    ),
)
def test_observation_retry_rejects_every_persisted_binding_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    envelope, _checkpoint_ref, report_ref, runtime_ref, repair_ref = _retry_fixture()
    admitted_report_ref = report_ref
    admitted_runtime_ref = runtime_ref
    admitted_repair_ref = repair_ref
    retry_binding = {
        "retry_number": 1,
        "retry_budget": 2,
        "retry_budget_remaining_before_attempt": 1,
    }
    report_approved_by = "original-operator"
    if mismatch == "resume_report_ref":
        admitted_report_ref = _ref("resume_report", "other-report")
    elif mismatch == "original_approved_by":
        report_approved_by = "different-operator"
    elif mismatch == "prior_runtime_ref":
        admitted_runtime_ref = _ref("runtime_evidence", "other-runtime")
    elif mismatch == "repair_plan_ref":
        admitted_repair_ref = _ref("repair_plan", "other-repair")
    elif mismatch == "retry_number":
        retry_binding["retry_number"] = 2
    elif mismatch == "retry_budget":
        retry_binding["retry_budget"] = 3
    elif mismatch == "retry_budget_remaining":
        retry_binding["retry_budget_remaining_before_attempt"] = 2
    payloads = {
        admitted_report_ref: {"approved_by": report_approved_by},
    }
    store = WorkflowCheckpointStore(_ReadStore(payloads))
    monkeypatch.setattr(
        store,
        "_preflight_runtime_observation_retry_facts",
        Mock(
            return_value=(
                _decision(),
                admitted_report_ref,
                admitted_runtime_ref,
                admitted_repair_ref,
                retry_binding,
            )
        ),
    )

    with pytest.raises(
        ValueError,
        match="Observation retry protocol or attempt does not match current facts",
    ):
        store.preflight_verification_operation(envelope)


def _recovery_envelope() -> tuple[
    VerificationOperationEnvelope,
    ArtifactRef,
    ArtifactRef,
]:
    checkpoint_ref = _ref("workflow_checkpoint", "checkpoint")
    report_ref = _ref("resume_report", "accepted-report")
    envelope = _runtime_envelope(
        completion_scope=RUNTIME_WORKFLOW_COMPLETION,
        attempt_policy=AcceptedResumeRecoveryAttemptV1(
            accepted_resume_report_ref=report_ref,
            recovery_of_resume_id=RESUME_ID,
            current_attempt_approved_by="current-operator",
        ),
        protocol_binding=_accepted_protocol(checkpoint_ref, report_ref),
    )
    return envelope, checkpoint_ref, report_ref


def test_accepted_resume_recovery_admits_exact_report_and_original_approver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, checkpoint_ref, report_ref = _recovery_envelope()
    expected = (_decision(), report_ref)
    store = WorkflowCheckpointStore(
        _ReadStore({report_ref: {"approved_by": "original-operator"}})
    )
    factual = Mock(return_value=expected)
    monkeypatch.setattr(
        store,
        "_preflight_accepted_resume_recovery_facts",
        factual,
    )

    assert store.preflight_verification_operation(envelope) is expected
    factual.assert_called_once_with(checkpoint_ref, resume_id=RESUME_ID)


@pytest.mark.parametrize("mismatch", ("resume_report_ref", "approved_by"))
def test_accepted_resume_recovery_rejects_persisted_binding_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    envelope, _checkpoint_ref, report_ref = _recovery_envelope()
    admitted_report_ref = report_ref
    approved_by = "original-operator"
    if mismatch == "resume_report_ref":
        admitted_report_ref = _ref("resume_report", "other-report")
    else:
        approved_by = "different-operator"
    store = WorkflowCheckpointStore(
        _ReadStore({admitted_report_ref: {"approved_by": approved_by}})
    )
    monkeypatch.setattr(
        store,
        "_preflight_accepted_resume_recovery_facts",
        Mock(return_value=(_decision(), admitted_report_ref)),
    )

    with pytest.raises(
        ValueError,
        match="Accepted-resume recovery protocol does not match current facts",
    ):
        store.preflight_verification_operation(envelope)


def test_runtime_terminalization_delegates_exact_typed_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_ref = _ref("workflow_checkpoint", "checkpoint")
    report_ref = _ref("resume_report", "accepted-report")
    runtime_ref = _ref("runtime_evidence", "runtime")
    protocol = _accepted_protocol(checkpoint_ref, report_ref)
    envelope = project_verification_operation(
        VerificationOperationSpec(
            operation_kind=RUNTIME_TERMINALIZATION_KIND,
            operation_contract_version=RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=protocol,
            variant_payload=RuntimeTerminalizationOperationV1(
                runtime_evidence_ref=runtime_ref,
            ),
        ),
        checkpoint_identity=_checkpoint_identity(),
    )
    expected = (_decision(), {"verification_status": "accepted"}, ())
    store = WorkflowCheckpointStore(_ReadStore())
    factual = Mock(return_value=expected)
    monkeypatch.setattr(
        store,
        "_preflight_runtime_terminal_continuation_facts",
        factual,
    )

    assert store.preflight_verification_operation(envelope) is expected
    factual.assert_called_once_with(
        checkpoint_ref,
        resume_report_ref=report_ref,
        runtime_evidence_ref=runtime_ref,
        resume_id=RESUME_ID,
        approved_by="original-operator",
    )


def test_runtime_evidence_consolidation_delegates_exact_typed_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_ref = _ref("workflow_checkpoint", "checkpoint")
    report_ref = _ref("resume_report", "accepted-report")
    runtime_ref = _ref("runtime_evidence", "prior-runtime")
    spec = VerificationOperationSpec(
        operation_kind=EVIDENCE_CONSOLIDATION_KIND,
        operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        attempt_policy=VerificationAttemptPolicy(
            attempt_budget=1,
            retry_allowed=False,
            recovery_allowed=False,
        ),
        protocol_binding=_accepted_protocol(checkpoint_ref, report_ref),
        variant_payload=EvidenceConsolidationOperationV1(
            feature_spec_ref=_ref("feature_spec", "feature-spec"),
            build_result_ref=_ref("build_result", "build-result"),
            prior_runtime_evidence_ref=runtime_ref,
            evidence_pack_ref=_ref("evidence_pack", "evidence-pack"),
            canonical_delta={},
            execution_file_bindings=(),
        ),
    )
    envelope = VerificationOperationEnvelope(
        envelope_contract_version=ENVELOPE_CONTRACT_VERSION,
        operation_kind=spec.operation_kind,
        operation_contract_version=spec.operation_contract_version,
        approval_identity={},
        approval_identity_hash="dispatcher-only-test-identity",
        attempt_policy=spec.attempt_policy,
        protocol_binding=spec.protocol_binding,
        variant_payload=spec.variant_payload,
    )
    assert (
        resolve_verification_operation(envelope).shape_id
        == "runtime_evidence_consolidation_initial"
    )
    monkeypatch.setattr(
        checkpointing_module,
        "validate_verification_operation_envelope",
        lambda value: value,
    )
    expected = (_decision(), {"verification_status": "inconclusive"}, ())
    store = WorkflowCheckpointStore(_ReadStore())
    factual = Mock(return_value=expected)
    monkeypatch.setattr(
        store,
        "_preflight_runtime_evidence_consolidation_facts",
        factual,
    )

    assert store.preflight_verification_operation(envelope) is expected
    factual.assert_called_once_with(
        checkpoint_ref,
        resume_report_ref=report_ref,
        prior_runtime_evidence_ref=runtime_ref,
        resume_id=RESUME_ID,
        approved_by="original-operator",
    )


def test_dispatcher_rejects_a_supplied_declaration_from_another_shape() -> None:
    checkpoint_ref = _ref("workflow_checkpoint", "checkpoint")
    runtime_envelope = _runtime_envelope(
        completion_scope=RUNTIME_WORKFLOW_COMPLETION,
        attempt_policy=InitialAttemptV1(),
        protocol_binding=NewRuntimeResumeProtocolBindingV1(
            checkpoint_ref=checkpoint_ref,
            resume_id=RESUME_ID,
            approved_by="current-operator",
        ),
    )
    store = WorkflowCheckpointStore(_ReadStore())

    with pytest.raises(
        ValueError,
        match="declaration changed before checkpoint admission",
    ):
        store.preflight_verification_operation(
            _build_envelope(),
            declaration=resolve_verification_operation(runtime_envelope),
        )


def test_legacy_preflight_names_remain_thin_factual_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_ref = _ref("workflow_checkpoint", "checkpoint")
    report_ref = _ref("resume_report", "accepted-report")
    runtime_ref = _ref("runtime_evidence", "runtime")
    store = WorkflowCheckpointStore(_ReadStore())
    results = [object() for _ in range(5)]
    method_names = (
        "_preflight_resume_facts",
        "_preflight_accepted_resume_recovery_facts",
        "_preflight_runtime_observation_retry_facts",
        "_preflight_runtime_terminal_continuation_facts",
        "_preflight_runtime_evidence_consolidation_facts",
    )
    factual = []
    for method_name, result in zip(method_names, results, strict=True):
        handler = Mock(return_value=result)
        factual.append(handler)
        monkeypatch.setattr(store, method_name, handler)

    assert store.preflight_resume(checkpoint_ref, resume_id=RESUME_ID) is results[0]
    assert (
        store.preflight_accepted_resume_recovery(
            checkpoint_ref,
            resume_id=RESUME_ID,
        )
        is results[1]
    )
    assert (
        store.preflight_runtime_observation_retry(
            checkpoint_ref,
            resume_id=RESUME_ID,
        )
        is results[2]
    )
    assert (
        store.preflight_runtime_terminal_continuation(
            checkpoint_ref,
            resume_report_ref=report_ref,
            runtime_evidence_ref=runtime_ref,
            resume_id=RESUME_ID,
            approved_by="original-operator",
        )
        is results[3]
    )
    assert (
        store.preflight_runtime_evidence_consolidation(
            checkpoint_ref,
            resume_report_ref=report_ref,
            prior_runtime_evidence_ref=runtime_ref,
            resume_id=RESUME_ID,
            approved_by="original-operator",
        )
        is results[4]
    )

    factual[0].assert_called_once_with(checkpoint_ref, resume_id=RESUME_ID)
    factual[1].assert_called_once_with(checkpoint_ref, resume_id=RESUME_ID)
    factual[2].assert_called_once_with(checkpoint_ref, resume_id=RESUME_ID)
    factual[3].assert_called_once_with(
        checkpoint_ref,
        resume_report_ref=report_ref,
        runtime_evidence_ref=runtime_ref,
        resume_id=RESUME_ID,
        approved_by="original-operator",
    )
    factual[4].assert_called_once_with(
        checkpoint_ref,
        resume_report_ref=report_ref,
        prior_runtime_evidence_ref=runtime_ref,
        resume_id=RESUME_ID,
        approved_by="original-operator",
    )


def test_typed_dispatcher_does_not_consume_public_legacy_boolean_names() -> None:
    tree = ast.parse(
        textwrap.dedent(
            inspect.getsource(WorkflowCheckpointStore.preflight_verification_operation)
        )
    )
    consumed_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }

    assert consumed_names.isdisjoint(
        {
            "runtime_evidence_only",
            "runtime_terminalization_only",
            "recover_accepted_resume",
            "retry_runtime_observation",
        }
    )
