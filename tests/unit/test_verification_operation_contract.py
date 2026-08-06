from __future__ import annotations

from dataclasses import replace

import pytest

from src.mod_agent.artifacts.envelope import ArtifactRef
from src.mod_agent.artifacts.store import ArtifactStoreError, ArtifactWriteResult
from src.mod_agent.verification_operations import (
    ACTION_IDENTITY_HASH_DOMAIN,
    ACTION_IDENTITY_SCHEMA_VERSION,
    BUILD_EFFECT_CONTRACT,
    BUILD_HANDOFF_COMPLETION,
    EVIDENCE_CONSOLIDATION_COMPLETION,
    EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
    EVIDENCE_CONSOLIDATION_KIND,
    LEGACY_RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
    LEGACY_RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
    LEGACY_RUNTIME_TERMINAL_IDENTITY_HASH_DOMAIN,
    LEGACY_RUNTIME_TERMINAL_IDENTITY_SCHEMA_VERSION,
    PREFLIGHT_RESULT_CONTRACT_VERSION,
    RESULT_CONTRACT_VERSION,
    RUNTIME_EVIDENCE_ONLY_COMPLETION,
    RUNTIME_EXECUTION_CONTRACT_VERSION,
    RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
    RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
    RUNTIME_EXECUTION_KIND,
    RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
    RUNTIME_TERMINALIZATION_KIND,
    RUNTIME_WORKFLOW_COMPLETION,
    TERMINAL_COMPLETION,
    VERIFICATION_BUILD_CONTRACT_VERSION,
    VERIFICATION_BUILD_IDENTITY_HASH_DOMAIN,
    VERIFICATION_BUILD_IDENTITY_SCHEMA_VERSION,
    VERIFICATION_BUILD_KIND,
    AcceptedResumeRecoveryAttemptV1,
    BuildInvocationProtocolBindingV1,
    BuildVerificationResultV1,
    EvidenceConsolidationOperationV1,
    EvidenceConsolidationResultV1,
    ImplementationEvidenceFileBinding,
    InitialAttemptV1,
    NewRuntimeResumeProtocolBindingV1,
    ObservationRetryAttemptV1,
    RuntimeExecutionOperationV1,
    RuntimeExecutionResultV1,
    RuntimeTerminalizationOperationV1,
    RuntimeTerminalizationResultV1,
    VerificationAttemptPolicy,
    VerificationAttemptResultV1,
    VerificationBuildOperationV1,
    VerificationCheckpointIdentityV1,
    VerificationOperationBlockerV1,
    VerificationOperationOutputV1,
    VerificationOperationPreflightResultV1,
    VerificationOperationRejectedResultV1,
    VerificationOperationResultV1,
    VerificationOperationSpec,
    VerificationOperationStoreReceiptV1,
    VerificationProtocolBinding,
    _ordered_store_attempt_roles,
    project_attempt_result,
    project_verification_operation,
    project_verification_operation_result,
    resolve_verification_operation,
    validate_verification_operation_envelope,
    verification_operation_declarations,
)


def _ref(artifact_type: str, fill: str, *, path_root: str = "C:/store") -> ArtifactRef:
    return ArtifactRef(
        feature_id="feature_contract",
        artifact_type=artifact_type,
        path=f"{path_root}/{artifact_type}/{fill}.json",
        artifact_hash=fill * 64,
    )


CHECKPOINT_IDENTITY = VerificationCheckpointIdentityV1(
    checkpoint_id="checkpoint_contract",
    run_id="run_contract",
    request_id="request_contract",
)

RUNTIME_SCOPE = {
    "allow_game_directory_write": True,
    "allow_game_launch": True,
    "plugin_destination_action_target": "BepInEx/plugins/BetterHitFeedback.dll",
    "runtime_effect_contract": (
        "one_caller_runtime_factory_invocation_after_graph_admission"
    ),
}


def _new_runtime_protocol(*, path_root: str = "C:/store") -> NewRuntimeResumeProtocolBindingV1:
    return NewRuntimeResumeProtocolBindingV1(
        checkpoint_ref=_ref("workflow_checkpoint", "c", path_root=path_root),
        resume_id="resume_contract",
        approved_by="operator_contract",
    )


def _accepted_runtime_protocol() -> VerificationProtocolBinding:
    return VerificationProtocolBinding(
        checkpoint_ref=_ref("workflow_checkpoint", "c"),
        accepted_resume_report_ref=_ref("resume_report", "f"),
        resume_id="resume_contract",
        approved_by="original_operator",
    )


def _build_spec(
    *, feature_fill: str = "a", path_root: str = "C:/store"
) -> VerificationOperationSpec:
    return VerificationOperationSpec(
        operation_kind=VERIFICATION_BUILD_KIND,
        operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
        attempt_policy=InitialAttemptV1(),
        protocol_binding=BuildInvocationProtocolBindingV1(
            run_id="run_contract",
            request_id="request_contract",
        ),
        variant_payload=VerificationBuildOperationV1(
            feature_spec_ref=_ref("feature_spec", feature_fill, path_root=path_root),
            evidence_pack_ref=_ref("evidence_pack", "b", path_root=path_root),
            user_request="Verify existing implementation",
            target_domain="gtfo",
            target_mod="BetterHitFeedback",
        ),
    )


def _initial_runtime_spec(completion_scope: str) -> VerificationOperationSpec:
    return VerificationOperationSpec(
        operation_kind=RUNTIME_EXECUTION_KIND,
        operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
        attempt_policy=InitialAttemptV1(),
        protocol_binding=_new_runtime_protocol(),
        variant_payload=RuntimeExecutionOperationV1(
            completion_scope=completion_scope,
            runtime_action_scope=RUNTIME_SCOPE,
        ),
    )


def _retry_runtime_spec() -> VerificationOperationSpec:
    return VerificationOperationSpec(
        operation_kind=RUNTIME_EXECUTION_KIND,
        operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
        attempt_policy=ObservationRetryAttemptV1(
            prior_runtime_evidence_ref=_ref("runtime_evidence", "d"),
            repair_plan_ref=_ref("repair_plan", "e"),
            retry_number=2,
            retry_budget=3,
            retry_budget_remaining=1,
            current_attempt_approved_by="retry_operator",
        ),
        protocol_binding=_accepted_runtime_protocol(),
        variant_payload=RuntimeExecutionOperationV1(
            completion_scope=RUNTIME_WORKFLOW_COMPLETION,
            runtime_action_scope=RUNTIME_SCOPE,
        ),
    )


def _recovery_runtime_spec() -> VerificationOperationSpec:
    return VerificationOperationSpec(
        operation_kind=RUNTIME_EXECUTION_KIND,
        operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
        attempt_policy=AcceptedResumeRecoveryAttemptV1(
            accepted_resume_report_ref=_ref("resume_report", "f"),
            recovery_of_resume_id="resume_contract",
            current_attempt_approved_by="recovery_operator",
        ),
        protocol_binding=_accepted_runtime_protocol(),
        variant_payload=RuntimeExecutionOperationV1(
            completion_scope=RUNTIME_WORKFLOW_COMPLETION,
            runtime_action_scope=RUNTIME_SCOPE,
        ),
    )


def _terminal_spec() -> VerificationOperationSpec:
    return VerificationOperationSpec(
        operation_kind=RUNTIME_TERMINALIZATION_KIND,
        operation_contract_version=RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
        attempt_policy=InitialAttemptV1(),
        protocol_binding=_accepted_runtime_protocol(),
        variant_payload=RuntimeTerminalizationOperationV1(
            runtime_evidence_ref=_ref("runtime_evidence", "d"),
        ),
    )


def _logical(artifact_type: str, fill: str) -> dict[str, str]:
    return {
        "artifact_hash": fill * 64,
        "artifact_type": artifact_type,
        "feature_id": "feature_contract",
    }


def _checkpoint_logical() -> dict[str, str]:
    return {
        **_logical("workflow_checkpoint", "c"),
        "checkpoint_id": "checkpoint_contract",
        "request_id": "request_contract",
        "run_id": "run_contract",
    }


EXPECTED_BUILD_IDENTITY = {
    "attempt_policy": {
        "attempt_number": 1,
        "recovery_allowed": False,
        "retry_allowed": False,
    },
    "exact_inputs": {
        "evidence_pack": _logical("evidence_pack", "b"),
        "feature_spec": _logical("feature_spec", "a"),
    },
    "execution_contract": {
        "completion_scope": "build_handoff",
        "output_artifact_types": ["build_result", "workflow_checkpoint"],
        "result_contract": "verification_operation_result_v1",
        "side_effect_class": BUILD_EFFECT_CONTRACT,
    },
    "hash_domain": "mod_agent.verification_build_action_identity.v1",
    "operation_contract_version": "verification_build_v1",
    "operation_kind": "verification_build",
    "protocol_binding": {
        "request_id": "request_contract",
        "run_id": "run_contract",
    },
    "schema_version": "verification_build_action_identity_v1",
    "variant_action": {
        "build_effect_contract": BUILD_EFFECT_CONTRACT,
        "target_domain": "gtfo",
        "target_mod": "BetterHitFeedback",
        "user_request": "Verify existing implementation",
    },
}

EXPECTED_INITIAL_WORKFLOW_IDENTITY = {
    "attempt_policy": {
        "attempt_number": 1,
        "recovery_allowed": False,
        "retry_allowed": False,
    },
    "checkpoint": _checkpoint_logical(),
    "completion_scope": "runtime_workflow",
    "execution_contract": {
        "completion_scope": "runtime_workflow",
        "output_artifact_types": [
            "resume_report",
            "runtime_evidence",
            "blocked_report",
            "eval_report",
            "workflow_summary",
        ],
        "result_contract": "verification_operation_result_v1",
        "side_effect_class": (
            "one_caller_runtime_factory_invocation_after_graph_admission"
        ),
    },
    "hash_domain": "mod_agent.runtime_execution_action_identity.v1",
    "operation_contract_version": "runtime_execution_v1",
    "operation_kind": "runtime_execution",
    "protocol_binding": {
        "approved_by": "operator_contract",
        "resume_id": "resume_contract",
    },
    "runtime_action_scope": RUNTIME_SCOPE,
    "schema_version": "runtime_execution_action_identity_v1",
}

EXPECTED_RETRY_IDENTITY = {
    **EXPECTED_INITIAL_WORKFLOW_IDENTITY,
    "attempt_policy": {
        "current_attempt_approved_by": "retry_operator",
        "prior_runtime_evidence": _logical("runtime_evidence", "d"),
        "repair_plan": _logical("repair_plan", "e"),
        "retry_budget": 3,
        "retry_budget_remaining": 1,
        "retry_number": 2,
    },
    "protocol_binding": {
        "accepted_resume_report": _logical("resume_report", "f"),
        "original_report_approved_by": "original_operator",
        "resume_id": "resume_contract",
    },
    "execution_contract": {
        "completion_scope": "runtime_workflow",
        "output_artifact_types": [
            "runtime_evidence",
            "blocked_report",
            "eval_report",
            "workflow_summary",
        ],
        "result_contract": "verification_operation_result_v1",
        "side_effect_class": (
            "one_caller_runtime_factory_invocation_after_graph_admission"
        ),
    },
}

EXPECTED_RECOVERY_IDENTITY = {
    **EXPECTED_INITIAL_WORKFLOW_IDENTITY,
    "attempt_policy": {
        "accepted_resume_report": _logical("resume_report", "f"),
        "automatic_retry_count": 0,
        "current_attempt_approved_by": "recovery_operator",
        "recovery_of_resume_id": "resume_contract",
    },
    "protocol_binding": {
        "accepted_resume_report": _logical("resume_report", "f"),
        "original_report_approved_by": "original_operator",
        "resume_id": "resume_contract",
    },
    "execution_contract": {
        "completion_scope": "runtime_workflow",
        "output_artifact_types": [
            "runtime_evidence",
            "blocked_report",
            "eval_report",
            "workflow_summary",
        ],
        "result_contract": "verification_operation_result_v1",
        "side_effect_class": (
            "one_caller_runtime_factory_invocation_after_graph_admission"
        ),
    },
}


def test_declaration_table_has_four_kinds_and_seven_exact_shapes() -> None:
    declarations = verification_operation_declarations()

    assert len(declarations) == 7
    assert {item.operation_kind for item in declarations} == {
        VERIFICATION_BUILD_KIND,
        RUNTIME_EXECUTION_KIND,
        RUNTIME_TERMINALIZATION_KIND,
        EVIDENCE_CONSOLIDATION_KIND,
    }
    assert [item.shape_id for item in declarations] == [
        "verification_build_initial",
        "runtime_execution_initial_evidence_only",
        "runtime_execution_initial_workflow",
        "runtime_execution_observation_retry",
        "runtime_execution_accepted_resume_recovery",
        "runtime_terminalization_initial",
        "runtime_evidence_consolidation_initial",
    ]
    assert [item.completion_scope for item in declarations] == [
        BUILD_HANDOFF_COMPLETION,
        RUNTIME_EVIDENCE_ONLY_COMPLETION,
        RUNTIME_WORKFLOW_COMPLETION,
        RUNTIME_WORKFLOW_COMPLETION,
        RUNTIME_WORKFLOW_COMPLETION,
        TERMINAL_COMPLETION,
        EVIDENCE_CONSOLIDATION_COMPLETION,
    ]
    assert [item.graph_handler for item in declarations] == [
        "verification_build",
        "runtime_execution",
        "runtime_execution",
        "runtime_execution",
        "runtime_execution",
        "runtime_terminalization",
        "runtime_evidence_consolidation",
    ]
    assert declarations[0].failure_stages == (
        "authorization",
        "admission",
        "store_preflight",
        "build_execution",
        "post_build_validation",
        "build_result_store",
        "handoff_eligibility",
        "checkpoint_prewrite",
        "checkpoint_store",
        "checkpoint_resume_preflight",
    )
    assert declarations[2].failure_stages[-4:] == (
        "blocked_report_execution",
        "blocked_report_store",
        "workflow_summary_execution",
        "workflow_summary_store",
    )
    assert declarations[5].failure_stages[5:7] == (
        "blocked_report_execution",
        "blocked_report_store",
    )


def test_declarations_own_exact_store_attempt_chains() -> None:
    declarations = verification_operation_declarations()

    assert [item.store_attempt_chains for item in declarations] == [
        (
            ("build_result",),
            ("build_result", "workflow_checkpoint"),
        ),
        (("resume_report", "runtime_evidence"),),
        (
            ("resume_report", "runtime_evidence", "blocked_report"),
            (
                "resume_report",
                "runtime_evidence",
                "eval_report",
                "blocked_report",
            ),
            (
                "resume_report",
                "runtime_evidence",
                "eval_report",
                "workflow_summary",
            ),
        ),
        (
            ("runtime_evidence", "blocked_report"),
            ("runtime_evidence", "eval_report", "blocked_report"),
            ("runtime_evidence", "eval_report", "workflow_summary"),
        ),
        (
            ("runtime_evidence", "blocked_report"),
            ("runtime_evidence", "eval_report", "blocked_report"),
            ("runtime_evidence", "eval_report", "workflow_summary"),
        ),
        (
            ("blocked_report",),
            ("eval_report", "blocked_report"),
            ("eval_report", "workflow_summary"),
        ),
        (("runtime_evidence",),),
    ]
    with pytest.raises(ValueError, match="chains are required"):
        replace(declarations[0], store_attempt_chains=())
    with pytest.raises(ValueError, match="chain is empty"):
        replace(declarations[0], store_attempt_chains=((),))
    with pytest.raises(ValueError, match="repeats a role"):
        replace(
            declarations[0],
            store_attempt_chains=(("build_result", "build_result"),),
        )
    with pytest.raises(ValueError, match="unknown role"):
        replace(declarations[0], store_attempt_chains=(("resume_report",),))


def test_ordered_store_attempt_roles_accepts_shared_prefix_once() -> None:
    declaration = verification_operation_declarations()[5]

    assert _ordered_store_attempt_roles(declaration, ("eval_report",)) == (
        "eval_report",
    )


def test_ordered_store_attempt_roles_rejects_impossible_role_set() -> None:
    declaration = verification_operation_declarations()[5]

    with pytest.raises(ValueError, match="declared Store attempt prefix"):
        _ordered_store_attempt_roles(declaration, ("workflow_summary",))


def test_ordered_store_attempt_roles_rejects_distinct_projected_orders() -> None:
    declaration = replace(
        verification_operation_declarations()[5],
        store_attempt_chains=(
            ("eval_report", "blocked_report"),
            ("blocked_report", "eval_report"),
        ),
    )

    with pytest.raises(ValueError, match="output order is ambiguous"):
        _ordered_store_attempt_roles(
            declaration,
            ("eval_report", "blocked_report"),
        )


@pytest.mark.parametrize(
    ("spec", "expected_identity", "expected_hash"),
    [
        (
            _build_spec(),
            EXPECTED_BUILD_IDENTITY,
            "sha256:33b405c73a5443acb5e57ae9a518fb00b0fc44665ce912e1a29320cfa60f6159",
        ),
        (
            _initial_runtime_spec(RUNTIME_WORKFLOW_COMPLETION),
            EXPECTED_INITIAL_WORKFLOW_IDENTITY,
            "sha256:d4cf3f06dfa9fd963a99f8050c6638c0800bd002890a30e27abf695675e13e92",
        ),
        (
            _retry_runtime_spec(),
            EXPECTED_RETRY_IDENTITY,
            "sha256:b58ecb56b49868d3ba312e9dc77702c2e0090810408dbf94612b6b5ffac909f1",
        ),
        (
            _recovery_runtime_spec(),
            EXPECTED_RECOVERY_IDENTITY,
            "sha256:34b2bca816e19aa57713a6340dd7f24315da4f5123b207abee0e940302a3baa2",
        ),
    ],
)
def test_new_identity_golden_vectors_are_literal(
    spec: VerificationOperationSpec,
    expected_identity: dict[str, object],
    expected_hash: str,
) -> None:
    checkpoint_identity = (
        None
        if spec.operation_kind == VERIFICATION_BUILD_KIND
        else CHECKPOINT_IDENTITY
    )

    envelope = project_verification_operation(
        spec,
        checkpoint_identity=checkpoint_identity,
    )

    assert envelope.approval_identity == expected_identity
    assert envelope.approval_identity_hash == expected_hash
    assert validate_verification_operation_envelope(envelope) == envelope


def test_c6_2_identity_projection_remains_byte_compatible() -> None:
    envelope = project_verification_operation(
        _initial_runtime_spec(RUNTIME_EVIDENCE_ONLY_COMPLETION),
        checkpoint_identity=CHECKPOINT_IDENTITY,
    )

    assert envelope.approval_identity == {
        "approved_by": "operator_contract",
        "checkpoint": _checkpoint_logical(),
        "hash_domain": LEGACY_RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
        "resume_id": "resume_contract",
        "runtime_admission": RUNTIME_SCOPE,
        "schema_version": LEGACY_RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
    }
    assert envelope.approval_identity_hash == (
        "sha256:499cea6371574d9e5c347f8c5ac40f8ba8fa3174111056eea97cd47fab25dc55"
    )


def test_c6_3_identity_projection_remains_byte_compatible() -> None:
    envelope = project_verification_operation(
        _terminal_spec(),
        checkpoint_identity=CHECKPOINT_IDENTITY,
    )

    assert envelope.approval_identity == {
        "approved_by": "original_operator",
        "checkpoint": _checkpoint_logical(),
        "hash_domain": LEGACY_RUNTIME_TERMINAL_IDENTITY_HASH_DOMAIN,
        "resume_id": "resume_contract",
        "resume_report": _logical("resume_report", "f"),
        "runtime_evidence": _logical("runtime_evidence", "d"),
        "schema_version": LEGACY_RUNTIME_TERMINAL_IDENTITY_SCHEMA_VERSION,
        "terminal_result_scope": {
            "allowed_artifact_types": [
                "blocked_report",
                "eval_report",
                "workflow_summary",
            ],
            "automatic_retry_count": 0,
            "recovery_allowed": False,
        },
    }
    assert envelope.approval_identity_hash == (
        "sha256:2b2d8c68dac32147e85c5d689593a7fc298cd8c362d006747575daa791f26cb9"
    )


def test_c6_4_identity_projection_preserves_existing_envelope_bytes(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.mod_agent.runtime_evidence_consolidation.action_projection_for_operation",
        lambda operation: {"fixture": "c6.4"},
    )
    spec = VerificationOperationSpec(
        operation_kind=EVIDENCE_CONSOLIDATION_KIND,
        operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        attempt_policy=VerificationAttemptPolicy(1, False, False),
        protocol_binding=_accepted_runtime_protocol(),
        variant_payload=EvidenceConsolidationOperationV1(
            feature_spec_ref=_ref("feature_spec", "a"),
            build_result_ref=_ref("build_result", "7"),
            prior_runtime_evidence_ref=_ref("runtime_evidence", "d"),
            evidence_pack_ref=_ref("evidence_pack", "b"),
            canonical_delta={},
            execution_file_bindings=(),
        ),
    )

    envelope = project_verification_operation(spec)

    assert envelope.approval_identity == {
        "attempt_policy": {
            "attempt_budget": 1,
            "recovery_allowed": False,
            "retry_allowed": False,
        },
        "execution_contract": {
            "output_artifact_types": ["runtime_evidence"],
            "result_contract": RESULT_CONTRACT_VERSION,
            "side_effect_class": "one_runtime_evidence_artifact_write",
        },
        "hash_domain": ACTION_IDENTITY_HASH_DOMAIN,
        "identity_schema_version": ACTION_IDENTITY_SCHEMA_VERSION,
        "operation_contract_version": EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        "operation_kind": EVIDENCE_CONSOLIDATION_KIND,
        "protocol_binding": {
            "accepted_resume_report": _logical("resume_report", "f"),
            "approved_by": "original_operator",
            "checkpoint": _logical("workflow_checkpoint", "c"),
            "resume_id": "resume_contract",
        },
        "variant_action": {"fixture": "c6.4"},
    }
    assert envelope.approval_identity_hash == (
        "sha256:382b2b8b9ac7ec4d74dc1d0d169ce1ec0dc04bb11148b9597707a3adf153f0f9"
    )


def test_identity_excludes_physical_locator_but_binds_logical_hash() -> None:
    first = project_verification_operation(_build_spec(path_root="C:/first"))
    moved = project_verification_operation(_build_spec(path_root="D:/moved"))
    changed = project_verification_operation(_build_spec(feature_fill="9"))

    assert first.approval_identity_hash == moved.approval_identity_hash
    assert first.approval_identity == moved.approval_identity
    assert changed.approval_identity_hash != first.approval_identity_hash


def test_unregistered_shape_and_checkpoint_context_fail_closed() -> None:
    wrong = replace(
        _initial_runtime_spec(RUNTIME_EVIDENCE_ONLY_COMPLETION),
        attempt_policy=ObservationRetryAttemptV1(
            prior_runtime_evidence_ref=_ref("runtime_evidence", "d"),
            repair_plan_ref=_ref("repair_plan", "e"),
            retry_number=1,
            retry_budget=2,
            retry_budget_remaining=1,
            current_attempt_approved_by="retry_operator",
        ),
    )

    with pytest.raises(ValueError, match="shape is not registered"):
        resolve_verification_operation(wrong)
    with pytest.raises(ValueError, match="checkpoint identity context"):
        project_verification_operation(
            _initial_runtime_spec(RUNTIME_EVIDENCE_ONLY_COMPLETION)
        )
    with pytest.raises(ValueError, match="checkpoint identity context"):
        project_verification_operation(
            _build_spec(), checkpoint_identity=CHECKPOINT_IDENTITY
        )


def test_preflight_result_identity_resolution_shapes() -> None:
    blocker = VerificationOperationBlockerV1(
        stage="authorization",
        code="unknown_operation",
        message="Operation declaration was not resolved.",
    )
    unresolved = VerificationOperationPreflightResultV1(
        result_contract_version=PREFLIGHT_RESULT_CONTRACT_VERSION,
        preflight_status="blocked",
        identity_resolution_status="unresolved",
        operation_kind=None,
        operation_contract_version=None,
        envelope=None,
        approval_identity_hash=None,
        failure_stage="authorization",
        blockers=(blocker,),
        audit_snapshot={"store_file_count": 12},
    )
    envelope = project_verification_operation(_build_spec())
    ready = VerificationOperationPreflightResultV1(
        result_contract_version=PREFLIGHT_RESULT_CONTRACT_VERSION,
        preflight_status="ready",
        identity_resolution_status="identity_resolved",
        operation_kind=VERIFICATION_BUILD_KIND,
        operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
        envelope=envelope,
        approval_identity_hash=envelope.approval_identity_hash,
        failure_stage=None,
        blockers=(),
        audit_snapshot={"stdout": "presentation only"},
    )

    assert unresolved.identity_resolution_status == "unresolved"
    assert ready.envelope == envelope
    with pytest.raises(ValueError, match="leaked untrusted identity"):
        replace(unresolved, operation_kind=VERIFICATION_BUILD_KIND)


def _committed_write_result(ref: ArtifactRef) -> ArtifactWriteResult:
    return ArtifactWriteResult(
        outcome="committed",
        feature_id=ref.feature_id,
        artifact_type=ref.artifact_type,
        artifact_hash=ref.artifact_hash,
        artifact_ref=ref,
        revision_path=ref.path,
        latest_alias_path=f"C:/store/{ref.artifact_type}.json",
        pending_marker_path=None,
        commit_started=True,
        revision_state="valid",
        latest_alias_state="matches_identity",
        pending_marker_state="absent",
        failure_stage=None,
        failure_class=None,
        failure_message=None,
        recovery_available=False,
    )


def _failed_write_result(
    artifact_type: str,
    *,
    outcome: str = "blocked_before_commit",
) -> ArtifactWriteResult:
    partial = outcome == "partial"
    return ArtifactWriteResult(
        outcome=outcome,  # type: ignore[arg-type]
        feature_id="feature_contract",
        artifact_type=artifact_type,
        artifact_hash="9" * 64,
        artifact_ref=None,
        revision_path=f"C:/store/{artifact_type}/{'9' * 32}.json",
        latest_alias_path=f"C:/store/{artifact_type}.json",
        pending_marker_path=f"C:/store/p/{artifact_type}/{'9' * 32}.json",
        commit_started=partial,
        revision_state="valid" if partial else "absent",
        latest_alias_state="absent",
        pending_marker_state="present" if partial else "absent",
        failure_stage="latest_alias_write" if partial else "admission_validation",
        failure_class="ArtifactStoreError",
        failure_message="injected Store failure",
        recovery_available=partial,
        recovery_authorized=False,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("commit_started", 1, "must be bool"),
        ("outcome", "success", "outcome is not registered"),
        ("revision_state", "present", "revision_state is not registered"),
    ],
)
def test_store_owned_write_result_parser_rejects_legacy_coercion(
    field: str,
    value: object,
    message: str,
) -> None:
    projection = _committed_write_result(_ref("build_result", "8")).to_dict()
    projection[field] = value

    with pytest.raises(ArtifactStoreError, match=message):
        ArtifactWriteResult.from_dict(projection)


def test_store_owned_write_result_parser_rejects_missing_or_extra_fields() -> None:
    projection = _committed_write_result(_ref("build_result", "8")).to_dict()
    missing = dict(projection)
    missing.pop("recovery_authorized")
    extra = {**projection, "legacy_success": True}

    with pytest.raises(ArtifactStoreError, match="fields changed"):
        ArtifactWriteResult.from_dict(missing)
    with pytest.raises(ArtifactStoreError, match="fields changed"):
        ArtifactWriteResult.from_dict(extra)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"recovery_available": True},
            "Committed ArtifactWriteResult has inconsistent Store facts",
        ),
        (
            {"recovery_authorized": True},
            "Committed ArtifactWriteResult has inconsistent Store facts",
        ),
        (
            {
                "outcome": "blocked_before_commit",
                "commit_started": True,
                "failure_stage": "admission_validation",
                "failure_class": "ArtifactStoreError",
                "failure_message": "blocked",
            },
            "Non-committed ArtifactWriteResult has inconsistent Store facts",
        ),
        (
            {
                "outcome": "blocked_before_commit",
                "artifact_ref": None,
                "commit_started": True,
                "failure_stage": "admission_validation",
                "failure_class": "ArtifactStoreError",
                "failure_message": "blocked",
            },
            "Blocked-before-commit ArtifactWriteResult entered commit or recovery",
        ),
        (
            {
                "outcome": "partial",
                "artifact_ref": None,
                "failure_stage": None,
                "failure_class": "ArtifactStoreError",
                "failure_message": "partial",
            },
            "Non-committed ArtifactWriteResult has inconsistent Store facts",
        ),
        (
            {
                "outcome": "partial",
                "artifact_ref": None,
                "failure_stage": "latest_alias_write",
                "failure_class": "ArtifactStoreError",
                "failure_message": "partial",
                "recovery_available": True,
                "pending_marker_state": "absent",
            },
            "Recoverable ArtifactWriteResult lacks partial pending revision facts",
        ),
    ],
)
def test_store_owned_write_result_parser_rejects_impossible_terminal_facts(
    changes: dict[str, object],
    message: str,
) -> None:
    projection = _committed_write_result(_ref("build_result", "8")).to_dict()
    projection.update(changes)

    with pytest.raises(ArtifactStoreError, match=message):
        ArtifactWriteResult.from_dict(projection)


@pytest.mark.parametrize("outcome", ["blocked_before_commit", "partial"])
def test_store_owned_write_result_parser_accepts_registered_failure_facts(
    outcome: str,
) -> None:
    result = _failed_write_result("runtime_evidence", outcome=outcome)

    assert ArtifactWriteResult.from_dict(result.to_dict()) == result


def _completed_result(
    *,
    envelope,
    variant,
    role_refs: tuple[tuple[str, ArtifactRef], ...],
):
    return project_verification_operation_result(
        envelope=envelope,
        platform_status="completed",
        failure_stage=None,
        side_effects_may_have_started=True,
        store_receipts=tuple(
            VerificationOperationStoreReceiptV1(
                role=role,
                artifact_write_result=_committed_write_result(ref),
            )
            for role, ref in role_refs
        ),
        blockers=(),
        variant_result=variant,
        audit_snapshot={},
    )


def test_completed_c6_2_requires_runtime_outputs_and_committed_receipts() -> None:
    envelope = project_verification_operation(
        _initial_runtime_spec(RUNTIME_EVIDENCE_ONLY_COMPLETION),
        checkpoint_identity=CHECKPOINT_IDENTITY,
    )
    empty_variant = RuntimeExecutionResultV1(
        completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
        domain_runtime_status="accepted",
        resume_report_ref=None,
        runtime_evidence_ref=None,
        terminal_refs=(),
        operator_input_required=False,
    )
    with pytest.raises(ValueError, match="exact committed output chain"):
        _completed_result(envelope=envelope, variant=empty_variant, role_refs=())

    resume_ref = _ref("resume_report", "6")
    runtime_ref = _ref("runtime_evidence", "7")
    complete_variant = replace(
        empty_variant,
        resume_report_ref=resume_ref,
        runtime_evidence_ref=runtime_ref,
    )
    with pytest.raises(ValueError, match="matching committed Store receipt"):
        _completed_result(
            envelope=envelope,
            variant=complete_variant,
            role_refs=(("resume_report", resume_ref),),
        )

    blocked_runtime_receipt = VerificationOperationStoreReceiptV1(
        role="runtime_evidence",
        artifact_write_result=_failed_write_result("runtime_evidence"),
    )
    with pytest.raises(ValueError, match="matching committed Store receipt"):
        project_verification_operation_result(
            envelope=envelope,
            platform_status="completed",
            failure_stage=None,
            side_effects_may_have_started=True,
            store_receipts=(
                VerificationOperationStoreReceiptV1(
                    role="resume_report",
                    artifact_write_result=_committed_write_result(resume_ref),
                ),
                blocked_runtime_receipt,
            ),
            blockers=(),
            variant_result=complete_variant,
            audit_snapshot={},
        )


def test_completed_c6_2_rejects_reversed_committed_receipts() -> None:
    envelope = project_verification_operation(
        _initial_runtime_spec(RUNTIME_EVIDENCE_ONLY_COMPLETION),
        checkpoint_identity=CHECKPOINT_IDENTITY,
    )
    resume_ref = _ref("resume_report", "6")
    runtime_ref = _ref("runtime_evidence", "7")
    variant = RuntimeExecutionResultV1(
        completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
        domain_runtime_status="accepted",
        resume_report_ref=resume_ref,
        runtime_evidence_ref=runtime_ref,
        terminal_refs=(),
        operator_input_required=False,
    )

    with pytest.raises(ValueError, match="receipt order disagrees"):
        _completed_result(
            envelope=envelope,
            variant=variant,
            role_refs=(
                ("runtime_evidence", runtime_ref),
                ("resume_report", resume_ref),
            ),
        )


def test_terminal_eval_then_blocked_receipts_are_ordered() -> None:
    envelope = project_verification_operation(
        _terminal_spec(), checkpoint_identity=CHECKPOINT_IDENTITY
    )
    runtime_ref = _ref("runtime_evidence", "7")
    eval_ref = _ref("eval_report", "8")
    blocked_ref = _ref("blocked_report", "9")
    variant = RuntimeTerminalizationResultV1(
        domain_acceptance_status="blocked",
        runtime_evidence_ref=runtime_ref,
        eval_report_ref=eval_ref,
        blocked_report_ref=blocked_ref,
        workflow_summary_ref=None,
    )

    result = _completed_result(
        envelope=envelope,
        variant=variant,
        role_refs=(("eval_report", eval_ref), ("blocked_report", blocked_ref)),
    )
    assert tuple(item.role for item in result.outputs) == (
        "eval_report",
        "blocked_report",
    )
    assert tuple(item.role for item in result.store_receipts) == (
        "eval_report",
        "blocked_report",
    )
    with pytest.raises(ValueError, match="receipt order disagrees"):
        _completed_result(
            envelope=envelope,
            variant=variant,
            role_refs=(
                ("blocked_report", blocked_ref),
                ("eval_report", eval_ref),
            ),
        )


def test_noncommitted_store_receipt_must_be_last_and_next_in_chain() -> None:
    envelope = project_verification_operation(
        _initial_runtime_spec(RUNTIME_EVIDENCE_ONLY_COMPLETION),
        checkpoint_identity=CHECKPOINT_IDENTITY,
    )
    resume_ref = _ref("resume_report", "6")
    runtime_failure = VerificationOperationStoreReceiptV1(
        role="runtime_evidence",
        artifact_write_result=_failed_write_result(
            "runtime_evidence", outcome="partial"
        ),
    )
    variant = RuntimeExecutionResultV1(
        completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
        domain_runtime_status="unknown",
        resume_report_ref=resume_ref,
        runtime_evidence_ref=None,
        terminal_refs=(),
        operator_input_required=False,
    )
    committed_resume = VerificationOperationStoreReceiptV1(
        role="resume_report",
        artifact_write_result=_committed_write_result(resume_ref),
    )
    blocker = VerificationOperationBlockerV1(
        stage="runtime_evidence_store",
        code="runtime_evidence_store_failed",
        message="RuntimeEvidence Store write did not commit.",
    )

    accepted = project_verification_operation_result(
        envelope=envelope,
        platform_status="partial",
        failure_stage="runtime_evidence_store",
        side_effects_may_have_started=True,
        store_receipts=(committed_resume, runtime_failure),
        blockers=(blocker,),
        variant_result=variant,
        audit_snapshot={},
    )
    assert tuple(item.role for item in accepted.outputs) == ("resume_report",)
    with pytest.raises(ValueError, match="only one final non-committed"):
        project_verification_operation_result(
            envelope=envelope,
            platform_status="partial",
            failure_stage="runtime_evidence_store",
            side_effects_may_have_started=True,
            store_receipts=(runtime_failure, committed_resume),
            blockers=(blocker,),
            variant_result=variant,
            audit_snapshot={},
        )

    serialized_failure = ArtifactWriteResult.from_dict(
        runtime_failure.artifact_write_result.to_dict()
    )
    serialized_resume = ArtifactWriteResult.from_dict(
        committed_resume.artifact_write_result.to_dict()
    )
    with pytest.raises(ValueError, match="only one final non-committed"):
        project_verification_operation_result(
            envelope=envelope,
            platform_status="partial",
            failure_stage="runtime_evidence_store",
            side_effects_may_have_started=True,
            store_receipts=(
                VerificationOperationStoreReceiptV1(
                    role="runtime_evidence",
                    artifact_write_result=serialized_failure,
                ),
                VerificationOperationStoreReceiptV1(
                    role="resume_report",
                    artifact_write_result=serialized_resume,
                ),
            ),
            blockers=(blocker,),
            variant_result=variant,
            audit_snapshot={},
        )


def test_completed_result_shapes_require_their_exact_committed_chains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_ref = _ref("build_result", "1")
    resume_ref = _ref("resume_report", "2")
    runtime_ref = _ref("runtime_evidence", "3")
    blocked_ref = _ref("blocked_report", "4")

    monkeypatch.setattr(
        "src.mod_agent.runtime_evidence_consolidation.action_projection_for_operation",
        lambda operation: {"fixture": "completed-chain"},
    )
    consolidation_spec = VerificationOperationSpec(
        operation_kind=EVIDENCE_CONSOLIDATION_KIND,
        operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        attempt_policy=VerificationAttemptPolicy(1, False, False),
        protocol_binding=_accepted_runtime_protocol(),
        variant_payload=EvidenceConsolidationOperationV1(
            feature_spec_ref=_ref("feature_spec", "a"),
            build_result_ref=_ref("build_result", "b"),
            prior_runtime_evidence_ref=_ref("runtime_evidence", "c"),
            evidence_pack_ref=_ref("evidence_pack", "d"),
            canonical_delta={},
            execution_file_bindings=(),
        ),
    )
    runtime_workflow_variant = RuntimeExecutionResultV1(
        completion_scope=RUNTIME_WORKFLOW_COMPLETION,
        domain_runtime_status="blocked",
        resume_report_ref=resume_ref,
        runtime_evidence_ref=runtime_ref,
        terminal_refs=(blocked_ref,),
        operator_input_required=False,
    )
    retry_variant = replace(runtime_workflow_variant, resume_report_ref=None)
    terminal_variant = RuntimeTerminalizationResultV1(
        domain_acceptance_status="blocked",
        runtime_evidence_ref=_ref("runtime_evidence", "d"),
        eval_report_ref=None,
        blocked_report_ref=blocked_ref,
        workflow_summary_ref=None,
    )
    consolidation_ref = _ref("runtime_evidence", "5")
    cases = (
        (
            project_verification_operation(_build_spec()),
            BuildVerificationResultV1(
                domain_build_status="failed",
                claims_real_build_success=False,
                build_result_ref=build_ref,
                workflow_checkpoint_ref=None,
                handoff_ready=False,
            ),
            (("build_result", build_ref),),
        ),
        (
            project_verification_operation(
                _initial_runtime_spec(RUNTIME_EVIDENCE_ONLY_COMPLETION),
                checkpoint_identity=CHECKPOINT_IDENTITY,
            ),
            RuntimeExecutionResultV1(
                completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
                domain_runtime_status="accepted",
                resume_report_ref=resume_ref,
                runtime_evidence_ref=runtime_ref,
                terminal_refs=(),
                operator_input_required=False,
            ),
            (("resume_report", resume_ref), ("runtime_evidence", runtime_ref)),
        ),
        (
            project_verification_operation(
                _initial_runtime_spec(RUNTIME_WORKFLOW_COMPLETION),
                checkpoint_identity=CHECKPOINT_IDENTITY,
            ),
            runtime_workflow_variant,
            (
                ("resume_report", resume_ref),
                ("runtime_evidence", runtime_ref),
                ("blocked_report", blocked_ref),
            ),
        ),
        (
            project_verification_operation(
                _retry_runtime_spec(), checkpoint_identity=CHECKPOINT_IDENTITY
            ),
            retry_variant,
            (("runtime_evidence", runtime_ref), ("blocked_report", blocked_ref)),
        ),
        (
            project_verification_operation(
                _recovery_runtime_spec(), checkpoint_identity=CHECKPOINT_IDENTITY
            ),
            retry_variant,
            (("runtime_evidence", runtime_ref), ("blocked_report", blocked_ref)),
        ),
        (
            project_verification_operation(
                _terminal_spec(), checkpoint_identity=CHECKPOINT_IDENTITY
            ),
            terminal_variant,
            (("blocked_report", blocked_ref),),
        ),
        (
            project_verification_operation(consolidation_spec),
            EvidenceConsolidationResultV1(
                prior_runtime_evidence_ref=_ref("runtime_evidence", "c"),
                runtime_evidence_ref=consolidation_ref,
                derived_payload_hash="sha256:" + "6" * 64,
                semantic_binding_key="runtime_evidence_consolidation",
                semantic_binding_version="v1",
            ),
            (("runtime_evidence", consolidation_ref),),
        ),
    )

    for envelope, variant, role_refs in cases:
        result = _completed_result(
            envelope=envelope,
            variant=variant,
            role_refs=role_refs,
        )
        assert result.execution_disposition in {"succeeded", "domain_blocked"}


def test_build_domain_failure_is_completed_domain_blocked_golden_result() -> None:
    build_ref = _ref("build_result", "8")
    receipt = VerificationOperationStoreReceiptV1(
        role="build_result",
        artifact_write_result=_committed_write_result(build_ref),
    )
    result = VerificationOperationResultV1(
        result_contract_version=RESULT_CONTRACT_VERSION,
        operation_kind=VERIFICATION_BUILD_KIND,
        operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
        approval_identity_hash=(
            "sha256:33b405c73a5443acb5e57ae9a518fb00b0fc44665ce912e1a29320cfa60f6159"
        ),
        identity_resolution_status="identity_resolved",
        platform_status="completed",
        execution_disposition="domain_blocked",
        failure_stage=None,
        side_effects_may_have_started=True,
        attempt_result=project_attempt_result(InitialAttemptV1()),
        outputs=(VerificationOperationOutputV1("build_result", build_ref),),
        store_receipts=(receipt,),
        blockers=(),
        variant_result=BuildVerificationResultV1(
            domain_build_status="failed",
            claims_real_build_success=False,
            build_result_ref=build_ref,
            workflow_checkpoint_ref=None,
            handoff_ready=False,
        ),
        audit_snapshot={"elapsed_ms": 42},
    )

    assert result.platform_status == "completed"
    assert result.execution_disposition == "domain_blocked"
    assert result.failure_stage is None
    assert result.variant_result.handoff_ready is False
    with pytest.raises(ValueError, match="disposition changed"):
        replace(result, execution_disposition="succeeded")
    with pytest.raises(ValueError, match="not handoff-ready"):
        replace(
            result,
            execution_disposition="succeeded",
            variant_result=replace(
                result.variant_result,
                domain_build_status="succeeded",
            ),
        )


def test_rejected_and_identity_resolved_results_cannot_cross_boundaries() -> None:
    blocker = VerificationOperationBlockerV1(
        stage="authorization",
        code="unknown_operation",
        message="Operation declaration was not resolved.",
    )
    unresolved = VerificationOperationResultV1(
        result_contract_version=RESULT_CONTRACT_VERSION,
        operation_kind=None,
        operation_contract_version=None,
        approval_identity_hash=None,
        identity_resolution_status="unresolved",
        platform_status="blocked",
        execution_disposition="platform_blocked",
        failure_stage="authorization",
        side_effects_may_have_started=False,
        attempt_result=None,
        outputs=(),
        store_receipts=(),
        blockers=(blocker,),
        variant_result=VerificationOperationRejectedResultV1(),
        audit_snapshot={},
    )

    assert unresolved.to_dict()["variant_result"] == {"result_variant": "rejected"}
    with pytest.raises(ValueError, match="cannot report effects"):
        replace(unresolved, side_effects_may_have_started=True)
    with pytest.raises(ValueError, match="incomplete"):
        replace(
            unresolved,
            operation_kind=VERIFICATION_BUILD_KIND,
            operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
            approval_identity_hash="sha256:" + "1" * 64,
            identity_resolution_status="identity_resolved",
            attempt_result=project_attempt_result(InitialAttemptV1()),
        )


def test_result_failure_stage_and_output_roles_are_declaration_owned() -> None:
    build_ref = _ref("build_result", "8")
    base = VerificationOperationResultV1(
        result_contract_version=RESULT_CONTRACT_VERSION,
        operation_kind=VERIFICATION_BUILD_KIND,
        operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
        approval_identity_hash="sha256:" + "1" * 64,
        identity_resolution_status="identity_resolved",
        platform_status="blocked",
        execution_disposition="platform_blocked",
        failure_stage="build_execution",
        side_effects_may_have_started=True,
        attempt_result=project_attempt_result(InitialAttemptV1()),
        outputs=(),
        store_receipts=(),
        blockers=(
            VerificationOperationBlockerV1(
                stage="build_execution",
                code="factory_failed",
                message="Build effect failed.",
            ),
        ),
        variant_result=BuildVerificationResultV1(
            domain_build_status="unknown",
            claims_real_build_success=False,
            build_result_ref=None,
            workflow_checkpoint_ref=None,
            handoff_ready=False,
        ),
        audit_snapshot={},
    )

    assert base.failure_stage == "build_execution"
    with pytest.raises(ValueError, match="not declared"):
        replace(base, failure_stage="blocked_report_execution")
    with pytest.raises(ValueError, match="outputs disagree"):
        replace(
            base,
            outputs=(VerificationOperationOutputV1("build_result", build_ref),),
        )


def test_attempt_result_projection_is_unique_for_each_attempt_type() -> None:
    assert project_attempt_result(InitialAttemptV1()) == VerificationAttemptResultV1(
        attempt_kind="initial",
        attempt_number=1,
        automatic_retry_count=0,
        retry_budget_remaining=None,
        current_attempt_is_retry=False,
        current_attempt_is_recovery=False,
        recovery_available=False,
    )
    assert project_attempt_result(_retry_runtime_spec().attempt_policy).to_dict() == {
        "attempt_kind": "observation_retry",
        "attempt_number": 2,
        "automatic_retry_count": 0,
        "retry_budget_remaining": 1,
        "current_attempt_is_retry": True,
        "current_attempt_is_recovery": False,
        "recovery_available": False,
    }
    assert project_attempt_result(_recovery_runtime_spec().attempt_policy).to_dict() == {
        "attempt_kind": "accepted_resume_recovery",
        "attempt_number": 1,
        "automatic_retry_count": 0,
        "retry_budget_remaining": None,
        "current_attempt_is_retry": False,
        "current_attempt_is_recovery": True,
        "recovery_available": False,
    }


def test_exact_type_constructors_reject_invalid_contract_values() -> None:
    with pytest.raises(ValueError, match="fixed"):
        InitialAttemptV1(attempt_number=2)
    with pytest.raises(ValueError, match="outside the approved budget"):
        ObservationRetryAttemptV1(
            prior_runtime_evidence_ref=_ref("runtime_evidence", "d"),
            repair_plan_ref=_ref("repair_plan", "e"),
            retry_number=1,
            retry_budget=2,
            retry_budget_remaining=2,
            current_attempt_approved_by="operator",
        )
    with pytest.raises(ValueError, match="non-JSON"):
        RuntimeExecutionOperationV1(
            completion_scope=RUNTIME_WORKFLOW_COMPLETION,
            runtime_action_scope={"invalid": object()},
        )
    with pytest.raises(ValueError, match="different feature_id"):
        VerificationBuildOperationV1(
            feature_spec_ref=_ref("feature_spec", "a"),
            evidence_pack_ref=replace(
                _ref("evidence_pack", "b"), feature_id="another_feature"
            ),
            user_request="Verify",
            target_domain="gtfo",
            target_mod=None,
        )


def test_exact_constants_match_approved_contract() -> None:
    assert VERIFICATION_BUILD_IDENTITY_SCHEMA_VERSION == (
        "verification_build_action_identity_v1"
    )
    assert VERIFICATION_BUILD_IDENTITY_HASH_DOMAIN == (
        "mod_agent.verification_build_action_identity.v1"
    )
    assert RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION == (
        "runtime_execution_action_identity_v1"
    )
    assert RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN == (
        "mod_agent.runtime_execution_action_identity.v1"
    )


def test_c6_4_support_type_remains_constructible() -> None:
    binding = ImplementationEvidenceFileBinding(
        role="source_contract_report",
        absolute_path="C:/reports/source_contract_report.json",
        content_sha256="a" * 64,
        logical_target_path="reports/source_contract_report.json",
    )

    assert binding.absolute_path == "C:/reports/source_contract_report.json"
