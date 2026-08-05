"""Typed authority family for verification-only public operations."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from src.mod_agent.action_identity import canonical_action_json, hash_action_identity


@dataclass(frozen=True)
class ImplementationEvidenceFileBinding:
    """File evidence binding defined before ArtifactStore's semantic import cycle."""

    role: str
    absolute_path: str
    content_sha256: str
    logical_target_path: str | None = None


from src.mod_agent.artifacts.envelope import ArtifactRef

if TYPE_CHECKING:
    from src.mod_agent.artifacts.store import ArtifactWriteResult


ENVELOPE_CONTRACT_VERSION = "verification_operation_envelope_v1"

VERIFICATION_BUILD_KIND = "verification_build"
RUNTIME_EXECUTION_KIND = "runtime_execution"
RUNTIME_TERMINALIZATION_KIND = "runtime_terminalization"
EVIDENCE_CONSOLIDATION_KIND = "runtime_evidence_consolidation"

VERIFICATION_BUILD_CONTRACT_VERSION = "verification_build_v1"
RUNTIME_EXECUTION_CONTRACT_VERSION = "runtime_execution_v1"
RUNTIME_TERMINALIZATION_CONTRACT_VERSION = "runtime_terminalization_v1"
EVIDENCE_CONSOLIDATION_CONTRACT_VERSION = "runtime_evidence_consolidation_v1"

ACTION_IDENTITY_SCHEMA_VERSION = "verification_operation_action_identity_v1"
ACTION_IDENTITY_HASH_DOMAIN = "mod_agent.verification_operation_action_identity.v1"
VERIFICATION_BUILD_IDENTITY_SCHEMA_VERSION = "verification_build_action_identity_v1"
VERIFICATION_BUILD_IDENTITY_HASH_DOMAIN = (
    "mod_agent.verification_build_action_identity.v1"
)
RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION = "runtime_execution_action_identity_v1"
RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN = (
    "mod_agent.runtime_execution_action_identity.v1"
)
LEGACY_RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION = (
    "verification_only_runtime_execution_identity_v1"
)
LEGACY_RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN = (
    "mod_agent.verification_only_runtime_execution_identity.v1"
)
LEGACY_RUNTIME_TERMINAL_IDENTITY_SCHEMA_VERSION = (
    "verification_only_runtime_terminal_identity_v1"
)
LEGACY_RUNTIME_TERMINAL_IDENTITY_HASH_DOMAIN = (
    "mod_agent.verification_only_runtime_terminal_identity.v1"
)

PREFLIGHT_RESULT_CONTRACT_VERSION = "verification_operation_preflight_result_v1"
RESULT_CONTRACT_VERSION = "verification_operation_result_v1"

BUILD_HANDOFF_COMPLETION = "build_handoff"
RUNTIME_EVIDENCE_ONLY_COMPLETION = "runtime_evidence_only"
RUNTIME_WORKFLOW_COMPLETION = "runtime_workflow"
TERMINAL_COMPLETION = "terminal"
EVIDENCE_CONSOLIDATION_COMPLETION = "runtime_evidence_consolidation"

BUILD_EFFECT_CONTRACT = (
    "one_caller_build_factory_invocation_after_graph_admission"
)


def _require_non_empty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty.")


def _validate_ref(ref: ArtifactRef, field: str, artifact_type: str | None = None) -> None:
    if not isinstance(ref, ArtifactRef):
        raise ValueError(f"{field} must be an ArtifactRef.")
    for name in ("feature_id", "artifact_type", "path", "artifact_hash"):
        _require_non_empty(getattr(ref, name), f"{field}.{name}")
    if artifact_type is not None and ref.artifact_type != artifact_type:
        raise ValueError(f"{field} must reference {artifact_type}.")


def _validate_json(value: Any, field: str) -> None:
    def visit(item: Any) -> None:
        if item is None or isinstance(item, (bool, str)):
            return
        if isinstance(item, int) and not isinstance(item, bool):
            return
        if isinstance(item, float):
            if math.isfinite(item):
                return
            raise ValueError(f"{field} contains a non-finite float.")
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError(f"{field} contains a non-string object key.")
            for child in item.values():
                visit(child)
            return
        raise ValueError(f"{field} contains a non-JSON value.")

    visit(value)
    canonical_action_json(value)


def _canonical_mapping(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping.")
    projected = dict(value)
    _validate_json(projected, field)
    return json.loads(canonical_action_json(projected).decode("utf-8"))


@dataclass(frozen=True)
class VerificationAttemptPolicy:
    """Frozen C6.4 attempt object retained byte-for-byte."""

    attempt_budget: int
    retry_allowed: bool
    recovery_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_budget": self.attempt_budget,
            "retry_allowed": self.retry_allowed,
            "recovery_allowed": self.recovery_allowed,
        }


@dataclass(frozen=True)
class InitialAttemptV1:
    attempt_number: Literal[1] = 1
    retry_allowed: Literal[False] = False
    recovery_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if (
            self.attempt_number != 1
            or self.retry_allowed is not False
            or self.recovery_allowed is not False
        ):
            raise ValueError("InitialAttemptV1 fields are fixed.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "retry_allowed": self.retry_allowed,
            "recovery_allowed": self.recovery_allowed,
        }


@dataclass(frozen=True)
class ObservationRetryAttemptV1:
    prior_runtime_evidence_ref: ArtifactRef
    repair_plan_ref: ArtifactRef
    retry_number: int
    retry_budget: int
    retry_budget_remaining: int
    current_attempt_approved_by: str

    def __post_init__(self) -> None:
        _validate_ref(
            self.prior_runtime_evidence_ref,
            "prior_runtime_evidence_ref",
            "runtime_evidence",
        )
        _validate_ref(self.repair_plan_ref, "repair_plan_ref", "repair_plan")
        if type(self.retry_number) is not int or self.retry_number < 1:
            raise ValueError("retry_number must be at least 1.")
        if type(self.retry_budget) is not int or self.retry_budget < 1:
            raise ValueError("retry_budget must be at least 1.")
        if (
            type(self.retry_budget_remaining) is not int
            or self.retry_budget_remaining < 0
            or self.retry_budget_remaining >= self.retry_budget
        ):
            raise ValueError("retry_budget_remaining is outside the approved budget.")
        _require_non_empty(
            self.current_attempt_approved_by,
            "current_attempt_approved_by",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prior_runtime_evidence": logical_artifact_identity(
                self.prior_runtime_evidence_ref
            ),
            "repair_plan": logical_artifact_identity(self.repair_plan_ref),
            "retry_number": self.retry_number,
            "retry_budget": self.retry_budget,
            "retry_budget_remaining": self.retry_budget_remaining,
            "current_attempt_approved_by": self.current_attempt_approved_by,
        }


@dataclass(frozen=True)
class AcceptedResumeRecoveryAttemptV1:
    accepted_resume_report_ref: ArtifactRef
    recovery_of_resume_id: str
    current_attempt_approved_by: str
    automatic_retry_count: Literal[0] = 0

    def __post_init__(self) -> None:
        _validate_ref(
            self.accepted_resume_report_ref,
            "accepted_resume_report_ref",
            "resume_report",
        )
        _require_non_empty(self.recovery_of_resume_id, "recovery_of_resume_id")
        _require_non_empty(
            self.current_attempt_approved_by,
            "current_attempt_approved_by",
        )
        if self.automatic_retry_count != 0:
            raise ValueError("automatic_retry_count must remain 0.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_resume_report": logical_artifact_identity(
                self.accepted_resume_report_ref
            ),
            "recovery_of_resume_id": self.recovery_of_resume_id,
            "current_attempt_approved_by": self.current_attempt_approved_by,
            "automatic_retry_count": self.automatic_retry_count,
        }


@dataclass(frozen=True)
class BuildInvocationProtocolBindingV1:
    run_id: str
    request_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.run_id, "run_id")
        _require_non_empty(self.request_id, "request_id")


@dataclass(frozen=True)
class NewRuntimeResumeProtocolBindingV1:
    checkpoint_ref: ArtifactRef
    resume_id: str
    approved_by: str

    def __post_init__(self) -> None:
        _validate_ref(self.checkpoint_ref, "checkpoint_ref", "workflow_checkpoint")
        _require_non_empty(self.resume_id, "resume_id")
        _require_non_empty(self.approved_by, "approved_by")


@dataclass(frozen=True)
class VerificationProtocolBinding:
    """Frozen accepted-resume protocol retained for C6.4 compatibility."""

    checkpoint_ref: ArtifactRef
    accepted_resume_report_ref: ArtifactRef
    resume_id: str
    approved_by: str

@dataclass(frozen=True)
class VerificationCheckpointIdentityV1:
    """Non-persisted facts required by checkpoint-bound identity projectors."""

    checkpoint_id: str
    run_id: str
    request_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.checkpoint_id, "checkpoint_id")
        _require_non_empty(self.run_id, "run_id")
        _require_non_empty(self.request_id, "request_id")


@dataclass(frozen=True)
class VerificationBuildOperationV1:
    feature_spec_ref: ArtifactRef
    evidence_pack_ref: ArtifactRef
    user_request: str
    target_domain: str
    target_mod: str | None
    completion_scope: Literal["build_handoff"] = BUILD_HANDOFF_COMPLETION
    build_effect_contract: Literal[
        "one_caller_build_factory_invocation_after_graph_admission"
    ] = BUILD_EFFECT_CONTRACT

    def __post_init__(self) -> None:
        _validate_ref(self.feature_spec_ref, "feature_spec_ref", "feature_spec")
        _validate_ref(self.evidence_pack_ref, "evidence_pack_ref", "evidence_pack")
        if self.feature_spec_ref.feature_id != self.evidence_pack_ref.feature_id:
            raise ValueError("Build exact inputs have different feature_id values.")
        _require_non_empty(self.user_request, "user_request")
        _require_non_empty(self.target_domain, "target_domain")
        if self.target_mod is not None:
            _require_non_empty(self.target_mod, "target_mod")
        if self.completion_scope != BUILD_HANDOFF_COMPLETION:
            raise ValueError("Build completion scope changed.")
        if self.build_effect_contract != BUILD_EFFECT_CONTRACT:
            raise ValueError("Build effect contract changed.")


@dataclass(frozen=True)
class RuntimeExecutionOperationV1:
    completion_scope: Literal["runtime_evidence_only", "runtime_workflow"]
    runtime_action_scope: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.completion_scope not in {
            RUNTIME_EVIDENCE_ONLY_COMPLETION,
            RUNTIME_WORKFLOW_COMPLETION,
        }:
            raise ValueError("Runtime completion scope is not registered.")
        _canonical_mapping(self.runtime_action_scope, "runtime_action_scope")


@dataclass(frozen=True)
class RuntimeTerminalizationOperationV1:
    runtime_evidence_ref: ArtifactRef
    terminal_result_scope: Mapping[str, Any] = field(
        default_factory=lambda: {
            "allowed_artifact_types": [
                "blocked_report",
                "eval_report",
                "workflow_summary",
            ],
            "automatic_retry_count": 0,
            "recovery_allowed": False,
        }
    )

    def __post_init__(self) -> None:
        _validate_ref(
            self.runtime_evidence_ref,
            "runtime_evidence_ref",
            "runtime_evidence",
        )
        if _canonical_mapping(
            self.terminal_result_scope,
            "terminal_result_scope",
        ) != {
            "allowed_artifact_types": [
                "blocked_report",
                "eval_report",
                "workflow_summary",
            ],
            "automatic_retry_count": 0,
            "recovery_allowed": False,
        }:
            raise ValueError("Terminal result scope changed.")


@dataclass(frozen=True)
class EvidenceConsolidationOperationV1:
    feature_spec_ref: ArtifactRef
    build_result_ref: ArtifactRef
    prior_runtime_evidence_ref: ArtifactRef
    evidence_pack_ref: ArtifactRef
    canonical_delta: Mapping[str, Any]
    execution_file_bindings: tuple[ImplementationEvidenceFileBinding, ...]
    output_status: Literal["blocked"] = "blocked"


VerificationAttempt = (
    VerificationAttemptPolicy
    | InitialAttemptV1
    | ObservationRetryAttemptV1
    | AcceptedResumeRecoveryAttemptV1
)
VerificationProtocol = (
    VerificationProtocolBinding
    | BuildInvocationProtocolBindingV1
    | NewRuntimeResumeProtocolBindingV1
)
VerificationVariant = (
    EvidenceConsolidationOperationV1
    | VerificationBuildOperationV1
    | RuntimeExecutionOperationV1
    | RuntimeTerminalizationOperationV1
)


@dataclass(frozen=True)
class VerificationOperationSpec:
    operation_kind: str
    operation_contract_version: str
    attempt_policy: VerificationAttempt
    protocol_binding: VerificationProtocol
    variant_payload: VerificationVariant


@dataclass(frozen=True)
class VerificationOperationEnvelope:
    envelope_contract_version: str
    operation_kind: str
    operation_contract_version: str
    approval_identity: Mapping[str, Any]
    approval_identity_hash: str
    attempt_policy: VerificationAttempt
    protocol_binding: VerificationProtocol
    variant_payload: VerificationVariant

    def to_spec(self) -> VerificationOperationSpec:
        return VerificationOperationSpec(
            operation_kind=self.operation_kind,
            operation_contract_version=self.operation_contract_version,
            attempt_policy=self.attempt_policy,
            protocol_binding=self.protocol_binding,
            variant_payload=self.variant_payload,
        )


@dataclass(frozen=True)
class VerificationOperationBlockerV1:
    stage: str
    code: str
    message: str

    def __post_init__(self) -> None:
        _require_non_empty(self.stage, "blocker.stage")
        _require_non_empty(self.code, "blocker.code")
        _require_non_empty(self.message, "blocker.message")

    def to_dict(self) -> dict[str, str]:
        return {"stage": self.stage, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class VerificationAttemptResultV1:
    attempt_kind: Literal["initial", "observation_retry", "accepted_resume_recovery"]
    attempt_number: int
    automatic_retry_count: int
    retry_budget_remaining: int | None
    current_attempt_is_retry: bool
    current_attempt_is_recovery: bool
    recovery_available: bool

    def __post_init__(self) -> None:
        if self.attempt_kind not in {
            "initial",
            "observation_retry",
            "accepted_resume_recovery",
        }:
            raise ValueError("attempt_kind is not registered.")
        if type(self.attempt_number) is not int or self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1.")
        if type(self.automatic_retry_count) is not int or self.automatic_retry_count < 0:
            raise ValueError("automatic_retry_count must be non-negative.")
        if self.retry_budget_remaining is not None and (
            type(self.retry_budget_remaining) is not int
            or self.retry_budget_remaining < 0
        ):
            raise ValueError("retry_budget_remaining must be non-negative or null.")
        if type(self.current_attempt_is_retry) is not bool or type(
            self.current_attempt_is_recovery
        ) is not bool:
            raise ValueError("Attempt kind flags must be bool values.")
        if type(self.recovery_available) is not bool:
            raise ValueError("recovery_available must be bool.")
        expected_retry = self.attempt_kind == "observation_retry"
        expected_recovery = self.attempt_kind == "accepted_resume_recovery"
        if (
            self.current_attempt_is_retry != expected_retry
            or self.current_attempt_is_recovery != expected_recovery
            or self.automatic_retry_count != 0
            or (expected_retry and self.retry_budget_remaining is None)
            or (not expected_retry and self.retry_budget_remaining is not None)
            or (self.attempt_kind == "initial" and self.attempt_number != 1)
        ):
            raise ValueError("Attempt result does not match its attempt kind.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_kind": self.attempt_kind,
            "attempt_number": self.attempt_number,
            "automatic_retry_count": self.automatic_retry_count,
            "retry_budget_remaining": self.retry_budget_remaining,
            "current_attempt_is_retry": self.current_attempt_is_retry,
            "current_attempt_is_recovery": self.current_attempt_is_recovery,
            "recovery_available": self.recovery_available,
        }


@dataclass(frozen=True)
class VerificationOperationOutputV1:
    role: str
    artifact_ref: ArtifactRef

    def __post_init__(self) -> None:
        _require_non_empty(self.role, "output.role")
        _validate_ref(self.artifact_ref, "output.artifact_ref")

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "artifact_ref": artifact_ref_to_dict(self.artifact_ref)}


@dataclass(frozen=True)
class VerificationOperationStoreReceiptV1:
    role: str
    artifact_write_result: "ArtifactWriteResult"

    def __post_init__(self) -> None:
        _require_non_empty(self.role, "store_receipt.role")
        from src.mod_agent.artifacts.store import ArtifactWriteResult

        if not isinstance(self.artifact_write_result, ArtifactWriteResult):
            raise ValueError("artifact_write_result must be an ArtifactWriteResult.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "artifact_write_result": self.artifact_write_result.to_dict(),
        }


@dataclass(frozen=True)
class VerificationOperationRejectedResultV1:
    result_variant: Literal["rejected"] = "rejected"

    def __post_init__(self) -> None:
        if self.result_variant != "rejected":
            raise ValueError("Rejected result variant changed.")

    def to_dict(self) -> dict[str, str]:
        return {"result_variant": self.result_variant}


@dataclass(frozen=True)
class BuildVerificationResultV1:
    domain_build_status: Literal["succeeded", "failed", "unknown"]
    claims_real_build_success: bool
    build_result_ref: ArtifactRef | None
    workflow_checkpoint_ref: ArtifactRef | None
    handoff_ready: bool

    def __post_init__(self) -> None:
        if self.domain_build_status not in {"succeeded", "failed", "unknown"}:
            raise ValueError("domain_build_status is not registered.")
        if type(self.claims_real_build_success) is not bool:
            raise ValueError("claims_real_build_success must be bool.")
        if self.build_result_ref is not None:
            _validate_ref(self.build_result_ref, "build_result_ref", "build_result")
        if self.workflow_checkpoint_ref is not None:
            _validate_ref(
                self.workflow_checkpoint_ref,
                "workflow_checkpoint_ref",
                "workflow_checkpoint",
            )
        if (
            self.build_result_ref is not None
            and self.workflow_checkpoint_ref is not None
            and self.build_result_ref.feature_id
            != self.workflow_checkpoint_ref.feature_id
        ):
            raise ValueError("Build result refs have different feature_id values.")
        if type(self.handoff_ready) is not bool:
            raise ValueError("handoff_ready must be bool.")
        if self.claims_real_build_success and self.build_result_ref is None:
            raise ValueError("Real Build success requires a BuildResult ref.")
        if self.handoff_ready and (
            self.build_result_ref is None or self.workflow_checkpoint_ref is None
        ):
            raise ValueError("Build handoff requires BuildResult and checkpoint refs.")


@dataclass(frozen=True)
class RuntimeExecutionResultV1:
    completion_scope: Literal["runtime_evidence_only", "runtime_workflow"]
    domain_runtime_status: Literal["accepted", "blocked", "inconclusive", "unknown"]
    resume_report_ref: ArtifactRef | None
    runtime_evidence_ref: ArtifactRef | None
    terminal_refs: tuple[ArtifactRef, ...]
    operator_input_required: bool

    def __post_init__(self) -> None:
        if self.completion_scope not in {
            RUNTIME_EVIDENCE_ONLY_COMPLETION,
            RUNTIME_WORKFLOW_COMPLETION,
        }:
            raise ValueError("Runtime result completion scope is not registered.")
        if self.domain_runtime_status not in {
            "accepted",
            "blocked",
            "inconclusive",
            "unknown",
        }:
            raise ValueError("domain_runtime_status is not registered.")
        if self.resume_report_ref is not None:
            _validate_ref(self.resume_report_ref, "resume_report_ref", "resume_report")
        if self.runtime_evidence_ref is not None:
            _validate_ref(
                self.runtime_evidence_ref,
                "runtime_evidence_ref",
                "runtime_evidence",
            )
        terminal_types = {
            "blocked_report",
            "eval_report",
            "workflow_summary",
        }
        for index, ref in enumerate(self.terminal_refs):
            _validate_ref(ref, f"terminal_refs[{index}]")
            if ref.artifact_type not in terminal_types:
                raise ValueError("Runtime terminal ref type is not registered.")
        if len({ref.artifact_type for ref in self.terminal_refs}) != len(
            self.terminal_refs
        ):
            raise ValueError("Runtime terminal ref types must be unique.")
        if (
            self.completion_scope == RUNTIME_EVIDENCE_ONLY_COMPLETION
            and self.terminal_refs
        ):
            raise ValueError("Evidence-only Runtime result cannot contain terminal refs.")
        if type(self.operator_input_required) is not bool:
            raise ValueError("operator_input_required must be bool.")


@dataclass(frozen=True)
class RuntimeTerminalizationResultV1:
    domain_acceptance_status: Literal["accepted", "blocked", "inconclusive", "unknown"]
    runtime_evidence_ref: ArtifactRef
    eval_report_ref: ArtifactRef | None
    blocked_report_ref: ArtifactRef | None
    workflow_summary_ref: ArtifactRef | None

    def __post_init__(self) -> None:
        if self.domain_acceptance_status not in {
            "accepted",
            "blocked",
            "inconclusive",
            "unknown",
        }:
            raise ValueError("domain_acceptance_status is not registered.")
        _validate_ref(
            self.runtime_evidence_ref,
            "runtime_evidence_ref",
            "runtime_evidence",
        )
        for field_name, ref, artifact_type in (
            ("eval_report_ref", self.eval_report_ref, "eval_report"),
            ("blocked_report_ref", self.blocked_report_ref, "blocked_report"),
            ("workflow_summary_ref", self.workflow_summary_ref, "workflow_summary"),
        ):
            if ref is not None:
                _validate_ref(ref, field_name, artifact_type)


@dataclass(frozen=True)
class EvidenceConsolidationResultV1:
    prior_runtime_evidence_ref: ArtifactRef
    runtime_evidence_ref: ArtifactRef | None
    derived_payload_hash: str
    semantic_binding_key: str
    semantic_binding_version: str

    def __post_init__(self) -> None:
        _validate_ref(
            self.prior_runtime_evidence_ref,
            "prior_runtime_evidence_ref",
            "runtime_evidence",
        )
        if self.runtime_evidence_ref is not None:
            _validate_ref(
                self.runtime_evidence_ref,
                "runtime_evidence_ref",
                "runtime_evidence",
            )
        for field_name, value in (
            ("derived_payload_hash", self.derived_payload_hash),
            ("semantic_binding_key", self.semantic_binding_key),
            ("semantic_binding_version", self.semantic_binding_version),
        ):
            _require_non_empty(value, field_name)


VerificationResultVariant = (
    VerificationOperationRejectedResultV1
    | BuildVerificationResultV1
    | RuntimeExecutionResultV1
    | RuntimeTerminalizationResultV1
    | EvidenceConsolidationResultV1
)


@dataclass(frozen=True)
class VerificationOperationPreflightResultV1:
    result_contract_version: Literal[
        "verification_operation_preflight_result_v1"
    ]
    preflight_status: Literal["ready", "blocked"]
    identity_resolution_status: Literal[
        "unresolved", "declaration_resolved", "identity_resolved"
    ]
    operation_kind: str | None
    operation_contract_version: str | None
    envelope: VerificationOperationEnvelope | None
    approval_identity_hash: str | None
    failure_stage: Literal["authorization", "admission"] | None
    blockers: tuple[VerificationOperationBlockerV1, ...]
    audit_snapshot: dict[str, Any]

    def __post_init__(self) -> None:
        _validate_preflight_result(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_contract_version": self.result_contract_version,
            "preflight_status": self.preflight_status,
            "identity_resolution_status": self.identity_resolution_status,
            "operation_kind": self.operation_kind,
            "operation_contract_version": self.operation_contract_version,
            "envelope": (
                None
                if self.envelope is None
                else verification_operation_envelope_to_dict(self.envelope)
            ),
            "approval_identity_hash": self.approval_identity_hash,
            "failure_stage": self.failure_stage,
            "blockers": [item.to_dict() for item in self.blockers],
            "audit_snapshot": dict(self.audit_snapshot),
        }


@dataclass(frozen=True)
class VerificationOperationResultV1:
    result_contract_version: Literal["verification_operation_result_v1"]
    operation_kind: str | None
    operation_contract_version: str | None
    approval_identity_hash: str | None
    identity_resolution_status: Literal[
        "unresolved",
        "declaration_resolved",
        "approved_identity_only",
        "identity_resolved",
    ]
    platform_status: Literal["completed", "blocked", "partial"]
    execution_disposition: Literal[
        "succeeded",
        "domain_blocked",
        "platform_blocked",
        "partial",
        "operator_input_required",
    ]
    failure_stage: str | None
    side_effects_may_have_started: bool
    attempt_result: VerificationAttemptResultV1 | None
    outputs: tuple[VerificationOperationOutputV1, ...]
    store_receipts: tuple[VerificationOperationStoreReceiptV1, ...]
    blockers: tuple[VerificationOperationBlockerV1, ...]
    variant_result: VerificationResultVariant
    audit_snapshot: dict[str, Any]

    def __post_init__(self) -> None:
        _validate_operation_result(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_contract_version": self.result_contract_version,
            "operation_kind": self.operation_kind,
            "operation_contract_version": self.operation_contract_version,
            "approval_identity_hash": self.approval_identity_hash,
            "identity_resolution_status": self.identity_resolution_status,
            "platform_status": self.platform_status,
            "execution_disposition": self.execution_disposition,
            "failure_stage": self.failure_stage,
            "side_effects_may_have_started": self.side_effects_may_have_started,
            "attempt_result": (
                None if self.attempt_result is None else self.attempt_result.to_dict()
            ),
            "outputs": [item.to_dict() for item in self.outputs],
            "store_receipts": [item.to_dict() for item in self.store_receipts],
            "blockers": [item.to_dict() for item in self.blockers],
            "variant_result": _result_variant_to_dict(self.variant_result),
            "audit_snapshot": dict(self.audit_snapshot),
        }


IdentityProjector = Callable[
    [
        VerificationOperationSpec,
        "VerificationOperationDeclaration",
        VerificationCheckpointIdentityV1 | None,
    ],
    dict[str, Any],
]
ResultProjector = Callable[[str, VerificationResultVariant], str]


@dataclass(frozen=True)
class VerificationOperationDeclaration:
    shape_id: str
    operation_kind: str
    operation_contract_version: str
    variant_type: type
    attempt_type: type
    protocol_type: type
    completion_scope: str
    identity_schema_version: str
    identity_hash_domain: str
    identity_projector: IdentityProjector
    graph_handler: str
    side_effect_class: str
    output_artifact_roles: tuple[tuple[str, str], ...]
    result_variant_type: type
    result_contract: str
    result_projector: ResultProjector
    failure_stages: tuple[str, ...]
    compatibility_mode: str
    deprecated: bool
    requires_checkpoint_identity: bool

    @property
    def output_artifact_types(self) -> tuple[str, ...]:
        return tuple(artifact_type for _role, artifact_type in self.output_artifact_roles)


_BUILD_FAILURE_STAGES = (
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
_RUNTIME_EVIDENCE_ONLY_FAILURE_STAGES = (
    "authorization",
    "admission",
    "resume_admission",
    "resume_report_store",
    "graph_admission",
    "store_preflight",
    "runtime_execution",
    "post_runtime_validation",
    "runtime_evidence_store",
)
_RUNTIME_WORKFLOW_FAILURE_STAGES = _RUNTIME_EVIDENCE_ONLY_FAILURE_STAGES + (
    "graph_terminal_admission",
    "eval_report_execution",
    "eval_report_store",
    "blocked_report_execution",
    "blocked_report_store",
    "workflow_summary_execution",
    "workflow_summary_store",
)
_TERMINAL_FAILURE_STAGES = (
    "authorization",
    "terminal_admission",
    "graph_terminal_admission",
    "eval_report_execution",
    "eval_report_store",
    "blocked_report_execution",
    "blocked_report_store",
    "workflow_summary_execution",
    "workflow_summary_store",
)
_CONSOLIDATION_FAILURE_STAGES = (
    "authorization",
    "consolidation_admission",
    "graph_consolidation_admission",
    "runtime_evidence_store",
)


def logical_artifact_identity(ref: ArtifactRef) -> dict[str, str]:
    return {
        "artifact_type": ref.artifact_type,
        "artifact_hash": ref.artifact_hash,
        "feature_id": ref.feature_id,
    }


def artifact_ref_to_dict(ref: ArtifactRef) -> dict[str, str]:
    return {**logical_artifact_identity(ref), "path": ref.path}


def _attempt_to_dict(attempt: VerificationAttempt) -> dict[str, Any]:
    return attempt.to_dict()


def _protocol_to_dict(protocol: VerificationProtocol) -> dict[str, Any]:
    if isinstance(protocol, BuildInvocationProtocolBindingV1):
        return {"run_id": protocol.run_id, "request_id": protocol.request_id}
    if isinstance(protocol, NewRuntimeResumeProtocolBindingV1):
        return {
            "checkpoint_ref": artifact_ref_to_dict(protocol.checkpoint_ref),
            "resume_id": protocol.resume_id,
            "approved_by": protocol.approved_by,
        }
    return {
        "checkpoint_ref": artifact_ref_to_dict(protocol.checkpoint_ref),
        "accepted_resume_report_ref": artifact_ref_to_dict(
            protocol.accepted_resume_report_ref
        ),
        "resume_id": protocol.resume_id,
        "approved_by": protocol.approved_by,
    }


def _variant_to_dict(variant: VerificationVariant) -> dict[str, Any]:
    if isinstance(variant, VerificationBuildOperationV1):
        return {
            "feature_spec_ref": artifact_ref_to_dict(variant.feature_spec_ref),
            "evidence_pack_ref": artifact_ref_to_dict(variant.evidence_pack_ref),
            "user_request": variant.user_request,
            "target_domain": variant.target_domain,
            "target_mod": variant.target_mod,
            "completion_scope": variant.completion_scope,
            "build_effect_contract": variant.build_effect_contract,
        }
    if isinstance(variant, RuntimeExecutionOperationV1):
        return {
            "completion_scope": variant.completion_scope,
            "runtime_action_scope": _canonical_mapping(
                variant.runtime_action_scope,
                "runtime_action_scope",
            ),
        }
    if isinstance(variant, RuntimeTerminalizationOperationV1):
        return {
            "runtime_evidence_ref": artifact_ref_to_dict(
                variant.runtime_evidence_ref
            ),
            "terminal_result_scope": _canonical_mapping(
                variant.terminal_result_scope,
                "terminal_result_scope",
            ),
        }
    return {
        "feature_spec_ref": artifact_ref_to_dict(variant.feature_spec_ref),
        "build_result_ref": artifact_ref_to_dict(variant.build_result_ref),
        "prior_runtime_evidence_ref": artifact_ref_to_dict(
            variant.prior_runtime_evidence_ref
        ),
        "evidence_pack_ref": artifact_ref_to_dict(variant.evidence_pack_ref),
        "canonical_delta": _canonical_mapping(
            variant.canonical_delta,
            "canonical_delta",
        ),
        "execution_file_bindings": [
            {
                "role": binding.role,
                "absolute_path": binding.absolute_path,
                "content_sha256": binding.content_sha256,
                "logical_target_path": binding.logical_target_path,
            }
            for binding in variant.execution_file_bindings
        ],
        "output_status": variant.output_status,
    }


def verification_operation_envelope_to_dict(
    envelope: VerificationOperationEnvelope,
) -> dict[str, Any]:
    """Return the exact JSON-safe operation envelope projection."""

    return {
        "envelope_contract_version": envelope.envelope_contract_version,
        "operation_kind": envelope.operation_kind,
        "operation_contract_version": envelope.operation_contract_version,
        "approval_identity": _canonical_mapping(
            envelope.approval_identity,
            "approval_identity",
        ),
        "approval_identity_hash": envelope.approval_identity_hash,
        "attempt_policy": _attempt_to_dict(envelope.attempt_policy),
        "protocol_binding": _protocol_to_dict(envelope.protocol_binding),
        "variant_payload": _variant_to_dict(envelope.variant_payload),
    }


def _checkpoint_projection(
    ref: ArtifactRef,
    checkpoint_identity: VerificationCheckpointIdentityV1 | None,
) -> dict[str, str]:
    if checkpoint_identity is None:
        raise ValueError("Checkpoint-bound identity projection requires current facts.")
    return {
        **logical_artifact_identity(ref),
        "checkpoint_id": checkpoint_identity.checkpoint_id,
        "run_id": checkpoint_identity.run_id,
        "request_id": checkpoint_identity.request_id,
    }


def _execution_contract(declaration: VerificationOperationDeclaration) -> dict[str, Any]:
    return {
        "completion_scope": declaration.completion_scope,
        "side_effect_class": declaration.side_effect_class,
        "output_artifact_types": list(declaration.output_artifact_types),
        "result_contract": declaration.result_contract,
    }


def _project_build_identity(
    spec: VerificationOperationSpec,
    declaration: VerificationOperationDeclaration,
    checkpoint_identity: VerificationCheckpointIdentityV1 | None,
) -> dict[str, Any]:
    if checkpoint_identity is not None:
        raise ValueError("Build identity does not accept checkpoint facts.")
    operation = spec.variant_payload
    protocol = spec.protocol_binding
    return _canonical_identity(
        {
            "schema_version": declaration.identity_schema_version,
            "hash_domain": declaration.identity_hash_domain,
            "operation_kind": declaration.operation_kind,
            "operation_contract_version": declaration.operation_contract_version,
            "protocol_binding": {
                "run_id": protocol.run_id,
                "request_id": protocol.request_id,
            },
            "exact_inputs": {
                "feature_spec": logical_artifact_identity(operation.feature_spec_ref),
                "evidence_pack": logical_artifact_identity(operation.evidence_pack_ref),
            },
            "attempt_policy": spec.attempt_policy.to_dict(),
            "variant_action": {
                "user_request": operation.user_request,
                "target_domain": operation.target_domain,
                "target_mod": operation.target_mod,
                "build_effect_contract": operation.build_effect_contract,
            },
            "execution_contract": _execution_contract(declaration),
        }
    )


def _project_runtime_identity(
    spec: VerificationOperationSpec,
    declaration: VerificationOperationDeclaration,
    checkpoint_identity: VerificationCheckpointIdentityV1 | None,
) -> dict[str, Any]:
    operation = spec.variant_payload
    protocol = spec.protocol_binding
    _validate_ref(protocol.checkpoint_ref, "checkpoint_ref", "workflow_checkpoint")
    _require_non_empty(protocol.resume_id, "resume_id")
    _require_non_empty(protocol.approved_by, "approved_by")
    checkpoint = _checkpoint_projection(protocol.checkpoint_ref, checkpoint_identity)
    runtime_scope = _canonical_mapping(
        operation.runtime_action_scope,
        "runtime_action_scope",
    )
    if declaration.shape_id == "runtime_execution_initial_evidence_only":
        return _canonical_identity(
            {
                "schema_version": LEGACY_RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
                "hash_domain": LEGACY_RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
                "checkpoint": checkpoint,
                "resume_id": protocol.resume_id,
                "approved_by": protocol.approved_by,
                "runtime_admission": runtime_scope,
            }
        )
    protocol_projection: dict[str, Any] = {
        "resume_id": protocol.resume_id,
        "approved_by": protocol.approved_by,
    }
    if isinstance(protocol, VerificationProtocolBinding):
        _validate_ref(
            protocol.accepted_resume_report_ref,
            "accepted_resume_report_ref",
            "resume_report",
        )
        protocol_projection = {
            "accepted_resume_report": logical_artifact_identity(
                protocol.accepted_resume_report_ref
            ),
            "original_report_approved_by": protocol.approved_by,
            "resume_id": protocol.resume_id,
        }
    return _canonical_identity(
        {
            "schema_version": declaration.identity_schema_version,
            "hash_domain": declaration.identity_hash_domain,
            "operation_kind": declaration.operation_kind,
            "operation_contract_version": declaration.operation_contract_version,
            "checkpoint": checkpoint,
            "attempt_policy": spec.attempt_policy.to_dict(),
            "protocol_binding": protocol_projection,
            "runtime_action_scope": runtime_scope,
            "completion_scope": operation.completion_scope,
            "execution_contract": _execution_contract(declaration),
        }
    )


def _project_terminal_identity(
    spec: VerificationOperationSpec,
    declaration: VerificationOperationDeclaration,
    checkpoint_identity: VerificationCheckpointIdentityV1 | None,
) -> dict[str, Any]:
    operation = spec.variant_payload
    protocol = spec.protocol_binding
    _validate_ref(protocol.checkpoint_ref, "checkpoint_ref", "workflow_checkpoint")
    _validate_ref(
        protocol.accepted_resume_report_ref,
        "accepted_resume_report_ref",
        "resume_report",
    )
    _require_non_empty(protocol.resume_id, "resume_id")
    _require_non_empty(protocol.approved_by, "approved_by")
    return _canonical_identity(
        {
            "schema_version": LEGACY_RUNTIME_TERMINAL_IDENTITY_SCHEMA_VERSION,
            "hash_domain": LEGACY_RUNTIME_TERMINAL_IDENTITY_HASH_DOMAIN,
            "checkpoint": _checkpoint_projection(
                protocol.checkpoint_ref,
                checkpoint_identity,
            ),
            "resume_report": logical_artifact_identity(
                protocol.accepted_resume_report_ref
            ),
            "runtime_evidence": logical_artifact_identity(
                operation.runtime_evidence_ref
            ),
            "resume_id": protocol.resume_id,
            "approved_by": protocol.approved_by,
            "terminal_result_scope": _canonical_mapping(
                operation.terminal_result_scope,
                "terminal_result_scope",
            ),
        }
    )


def _project_consolidation_identity(
    spec: VerificationOperationSpec,
    declaration: VerificationOperationDeclaration,
    checkpoint_identity: VerificationCheckpointIdentityV1 | None,
) -> dict[str, Any]:
    if checkpoint_identity is not None:
        raise ValueError("Consolidation identity does not accept checkpoint facts.")
    from src.mod_agent.runtime_evidence_consolidation import (
        action_projection_for_operation,
    )

    return {
        "identity_schema_version": ACTION_IDENTITY_SCHEMA_VERSION,
        "hash_domain": ACTION_IDENTITY_HASH_DOMAIN,
        "operation_kind": declaration.operation_kind,
        "operation_contract_version": declaration.operation_contract_version,
        "attempt_policy": spec.attempt_policy.to_dict(),
        "protocol_binding": {
            "checkpoint": logical_artifact_identity(spec.protocol_binding.checkpoint_ref),
            "accepted_resume_report": logical_artifact_identity(
                spec.protocol_binding.accepted_resume_report_ref
            ),
            "resume_id": spec.protocol_binding.resume_id,
            "approved_by": spec.protocol_binding.approved_by,
        },
        "variant_action": action_projection_for_operation(spec.variant_payload),
        "execution_contract": {
            "side_effect_class": declaration.side_effect_class,
            "output_artifact_types": list(declaration.output_artifact_types),
            "result_contract": declaration.result_contract,
        },
    }


def _canonical_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(canonical_action_json(dict(identity)).decode("utf-8"))


def _generic_result_disposition(
    platform_status: str,
    variant: VerificationResultVariant,
) -> str:
    if platform_status == "partial":
        return "partial"
    if isinstance(variant, RuntimeExecutionResultV1) and variant.operator_input_required:
        return "operator_input_required"
    if platform_status == "blocked":
        return "platform_blocked"
    raise ValueError("Completed operation requires a variant result projector.")


def _build_result_disposition(
    platform_status: str,
    variant: VerificationResultVariant,
) -> str:
    if platform_status != "completed":
        return _generic_result_disposition(platform_status, variant)
    if not isinstance(variant, BuildVerificationResultV1):
        raise ValueError("Build declaration requires BuildVerificationResultV1.")
    if variant.domain_build_status == "succeeded":
        if not variant.claims_real_build_success or not variant.handoff_ready:
            raise ValueError("Successful Build result is not handoff-ready.")
        return "succeeded"
    if variant.claims_real_build_success or variant.handoff_ready:
        raise ValueError("Blocked Build domain result claims a successful handoff.")
    return "domain_blocked"


def _runtime_result_disposition(
    platform_status: str,
    variant: VerificationResultVariant,
) -> str:
    if platform_status != "completed":
        return _generic_result_disposition(platform_status, variant)
    if not isinstance(variant, RuntimeExecutionResultV1):
        raise ValueError("Runtime declaration requires RuntimeExecutionResultV1.")
    if variant.operator_input_required:
        return "operator_input_required"
    if variant.completion_scope == RUNTIME_EVIDENCE_ONLY_COMPLETION:
        return "succeeded"
    return "succeeded" if variant.domain_runtime_status == "accepted" else "domain_blocked"


def _store_action_result_disposition(
    platform_status: str,
    variant: VerificationResultVariant,
) -> str:
    if platform_status != "completed":
        return _generic_result_disposition(platform_status, variant)
    return "succeeded"


_DECLARATIONS: tuple[VerificationOperationDeclaration, ...] = (
    VerificationOperationDeclaration(
        shape_id="verification_build_initial",
        operation_kind=VERIFICATION_BUILD_KIND,
        operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
        variant_type=VerificationBuildOperationV1,
        attempt_type=InitialAttemptV1,
        protocol_type=BuildInvocationProtocolBindingV1,
        completion_scope=BUILD_HANDOFF_COMPLETION,
        identity_schema_version=VERIFICATION_BUILD_IDENTITY_SCHEMA_VERSION,
        identity_hash_domain=VERIFICATION_BUILD_IDENTITY_HASH_DOMAIN,
        identity_projector=_project_build_identity,
        graph_handler="verification_build",
        side_effect_class=BUILD_EFFECT_CONTRACT,
        output_artifact_roles=(
            ("build_result", "build_result"),
            ("workflow_checkpoint", "workflow_checkpoint"),
        ),
        result_variant_type=BuildVerificationResultV1,
        result_contract=RESULT_CONTRACT_VERSION,
        result_projector=_build_result_disposition,
        failure_stages=_BUILD_FAILURE_STAGES,
        compatibility_mode="typed_current_with_legacy_public_v0_adapter",
        deprecated=False,
        requires_checkpoint_identity=False,
    ),
    VerificationOperationDeclaration(
        shape_id="runtime_execution_initial_evidence_only",
        operation_kind=RUNTIME_EXECUTION_KIND,
        operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
        variant_type=RuntimeExecutionOperationV1,
        attempt_type=InitialAttemptV1,
        protocol_type=NewRuntimeResumeProtocolBindingV1,
        completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
        identity_schema_version=LEGACY_RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
        identity_hash_domain=LEGACY_RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
        identity_projector=_project_runtime_identity,
        graph_handler="runtime_execution",
        side_effect_class="one_caller_runtime_factory_invocation_after_graph_admission",
        output_artifact_roles=(
            ("resume_report", "resume_report"),
            ("runtime_evidence", "runtime_evidence"),
        ),
        result_variant_type=RuntimeExecutionResultV1,
        result_contract=RESULT_CONTRACT_VERSION,
        result_projector=_runtime_result_disposition,
        failure_stages=_RUNTIME_EVIDENCE_ONLY_FAILURE_STAGES,
        compatibility_mode="typed_current_with_legacy_bound_identity_adapter",
        deprecated=False,
        requires_checkpoint_identity=True,
    ),
    VerificationOperationDeclaration(
        shape_id="runtime_execution_initial_workflow",
        operation_kind=RUNTIME_EXECUTION_KIND,
        operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
        variant_type=RuntimeExecutionOperationV1,
        attempt_type=InitialAttemptV1,
        protocol_type=NewRuntimeResumeProtocolBindingV1,
        completion_scope=RUNTIME_WORKFLOW_COMPLETION,
        identity_schema_version=RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
        identity_hash_domain=RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
        identity_projector=_project_runtime_identity,
        graph_handler="runtime_execution",
        side_effect_class="one_caller_runtime_factory_invocation_after_graph_admission",
        output_artifact_roles=(
            ("resume_report", "resume_report"),
            ("runtime_evidence", "runtime_evidence"),
            ("blocked_report", "blocked_report"),
            ("eval_report", "eval_report"),
            ("workflow_summary", "workflow_summary"),
        ),
        result_variant_type=RuntimeExecutionResultV1,
        result_contract=RESULT_CONTRACT_VERSION,
        result_projector=_runtime_result_disposition,
        failure_stages=_RUNTIME_WORKFLOW_FAILURE_STAGES,
        compatibility_mode="typed_current_with_legacy_public_v0_adapter",
        deprecated=False,
        requires_checkpoint_identity=True,
    ),
    VerificationOperationDeclaration(
        shape_id="runtime_execution_observation_retry",
        operation_kind=RUNTIME_EXECUTION_KIND,
        operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
        variant_type=RuntimeExecutionOperationV1,
        attempt_type=ObservationRetryAttemptV1,
        protocol_type=VerificationProtocolBinding,
        completion_scope=RUNTIME_WORKFLOW_COMPLETION,
        identity_schema_version=RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
        identity_hash_domain=RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
        identity_projector=_project_runtime_identity,
        graph_handler="runtime_execution",
        side_effect_class="one_caller_runtime_factory_invocation_after_graph_admission",
        output_artifact_roles=(
            ("runtime_evidence", "runtime_evidence"),
            ("blocked_report", "blocked_report"),
            ("eval_report", "eval_report"),
            ("workflow_summary", "workflow_summary"),
        ),
        result_variant_type=RuntimeExecutionResultV1,
        result_contract=RESULT_CONTRACT_VERSION,
        result_projector=_runtime_result_disposition,
        failure_stages=_RUNTIME_WORKFLOW_FAILURE_STAGES,
        compatibility_mode="typed_current_with_legacy_public_v0_adapter",
        deprecated=False,
        requires_checkpoint_identity=True,
    ),
    VerificationOperationDeclaration(
        shape_id="runtime_execution_accepted_resume_recovery",
        operation_kind=RUNTIME_EXECUTION_KIND,
        operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
        variant_type=RuntimeExecutionOperationV1,
        attempt_type=AcceptedResumeRecoveryAttemptV1,
        protocol_type=VerificationProtocolBinding,
        completion_scope=RUNTIME_WORKFLOW_COMPLETION,
        identity_schema_version=RUNTIME_EXECUTION_IDENTITY_SCHEMA_VERSION,
        identity_hash_domain=RUNTIME_EXECUTION_IDENTITY_HASH_DOMAIN,
        identity_projector=_project_runtime_identity,
        graph_handler="runtime_execution",
        side_effect_class="one_caller_runtime_factory_invocation_after_graph_admission",
        output_artifact_roles=(
            ("runtime_evidence", "runtime_evidence"),
            ("blocked_report", "blocked_report"),
            ("eval_report", "eval_report"),
            ("workflow_summary", "workflow_summary"),
        ),
        result_variant_type=RuntimeExecutionResultV1,
        result_contract=RESULT_CONTRACT_VERSION,
        result_projector=_runtime_result_disposition,
        failure_stages=_RUNTIME_WORKFLOW_FAILURE_STAGES,
        compatibility_mode="typed_current_with_legacy_public_v0_adapter",
        deprecated=False,
        requires_checkpoint_identity=True,
    ),
    VerificationOperationDeclaration(
        shape_id="runtime_terminalization_initial",
        operation_kind=RUNTIME_TERMINALIZATION_KIND,
        operation_contract_version=RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
        variant_type=RuntimeTerminalizationOperationV1,
        attempt_type=InitialAttemptV1,
        protocol_type=VerificationProtocolBinding,
        completion_scope=TERMINAL_COMPLETION,
        identity_schema_version=LEGACY_RUNTIME_TERMINAL_IDENTITY_SCHEMA_VERSION,
        identity_hash_domain=LEGACY_RUNTIME_TERMINAL_IDENTITY_HASH_DOMAIN,
        identity_projector=_project_terminal_identity,
        graph_handler="runtime_terminalization",
        side_effect_class="store_only_terminal_artifact_writes",
        output_artifact_roles=(
            ("blocked_report", "blocked_report"),
            ("eval_report", "eval_report"),
            ("workflow_summary", "workflow_summary"),
        ),
        result_variant_type=RuntimeTerminalizationResultV1,
        result_contract=RESULT_CONTRACT_VERSION,
        result_projector=_store_action_result_disposition,
        failure_stages=_TERMINAL_FAILURE_STAGES,
        compatibility_mode="typed_current_with_legacy_bound_identity_adapter",
        deprecated=False,
        requires_checkpoint_identity=True,
    ),
    VerificationOperationDeclaration(
        shape_id="runtime_evidence_consolidation_initial",
        operation_kind=EVIDENCE_CONSOLIDATION_KIND,
        operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        variant_type=EvidenceConsolidationOperationV1,
        attempt_type=VerificationAttemptPolicy,
        protocol_type=VerificationProtocolBinding,
        completion_scope=EVIDENCE_CONSOLIDATION_COMPLETION,
        identity_schema_version=ACTION_IDENTITY_SCHEMA_VERSION,
        identity_hash_domain=ACTION_IDENTITY_HASH_DOMAIN,
        identity_projector=_project_consolidation_identity,
        graph_handler="runtime_evidence_consolidation",
        side_effect_class="one_runtime_evidence_artifact_write",
        output_artifact_roles=(("runtime_evidence", "runtime_evidence"),),
        result_variant_type=EvidenceConsolidationResultV1,
        result_contract=RESULT_CONTRACT_VERSION,
        result_projector=_store_action_result_disposition,
        failure_stages=_CONSOLIDATION_FAILURE_STAGES,
        compatibility_mode="typed_current",
        deprecated=False,
        requires_checkpoint_identity=False,
    ),
)


def verification_operation_declarations() -> tuple[VerificationOperationDeclaration, ...]:
    """Return the frozen seven-shape declaration table."""

    return _DECLARATIONS


def _operation_completion(
    operation: VerificationOperationSpec | VerificationOperationEnvelope,
) -> str:
    variant = operation.variant_payload
    if isinstance(variant, RuntimeExecutionOperationV1):
        return variant.completion_scope
    if isinstance(variant, VerificationBuildOperationV1):
        return variant.completion_scope
    if isinstance(variant, RuntimeTerminalizationOperationV1):
        return TERMINAL_COMPLETION
    if isinstance(variant, EvidenceConsolidationOperationV1):
        return EVIDENCE_CONSOLIDATION_COMPLETION
    raise ValueError("Verification operation variant type is not registered.")


def resolve_verification_operation(
    operation: VerificationOperationSpec | VerificationOperationEnvelope,
) -> VerificationOperationDeclaration:
    """Resolve one exact registered operation shape without a generic fallback."""

    completion = _operation_completion(operation)
    matches = [
        declaration
        for declaration in _DECLARATIONS
        if declaration.operation_kind == operation.operation_kind
        and declaration.operation_contract_version == operation.operation_contract_version
        and type(operation.variant_payload) is declaration.variant_type
        and type(operation.attempt_policy) is declaration.attempt_type
        and type(operation.protocol_binding) is declaration.protocol_type
        and declaration.completion_scope == completion
    ]
    if len(matches) != 1:
        raise ValueError("Verification operation shape is not registered.")
    declaration = matches[0]
    if declaration.shape_id == "runtime_evidence_consolidation_initial" and (
        operation.attempt_policy
        != VerificationAttemptPolicy(
            attempt_budget=1,
            retry_allowed=False,
            recovery_allowed=False,
        )
    ):
        raise ValueError("Verification operation attempt policy changed.")
    if isinstance(operation.attempt_policy, ObservationRetryAttemptV1):
        if not isinstance(operation.protocol_binding, VerificationProtocolBinding):
            raise ValueError("Observation retry protocol changed.")
    if isinstance(operation.attempt_policy, AcceptedResumeRecoveryAttemptV1):
        if (
            operation.attempt_policy.accepted_resume_report_ref
            != operation.protocol_binding.accepted_resume_report_ref
            or operation.attempt_policy.recovery_of_resume_id
            != operation.protocol_binding.resume_id
        ):
            raise ValueError("Accepted-resume recovery binding changed.")
    return declaration


def project_verification_operation(
    spec: VerificationOperationSpec,
    *,
    checkpoint_identity: VerificationCheckpointIdentityV1 | None = None,
) -> VerificationOperationEnvelope:
    """Build the only canonical approval projection for one operation spec."""

    declaration = resolve_verification_operation(spec)
    if declaration.requires_checkpoint_identity != (checkpoint_identity is not None):
        raise ValueError("Verification operation checkpoint identity context changed.")
    identity = declaration.identity_projector(spec, declaration, checkpoint_identity)
    identity_hash = hash_action_identity(
        identity,
        expected_hash_domain=declaration.identity_hash_domain,
    )
    return VerificationOperationEnvelope(
        envelope_contract_version=ENVELOPE_CONTRACT_VERSION,
        operation_kind=spec.operation_kind,
        operation_contract_version=spec.operation_contract_version,
        approval_identity=identity,
        approval_identity_hash=identity_hash,
        attempt_policy=spec.attempt_policy,
        protocol_binding=spec.protocol_binding,
        variant_payload=spec.variant_payload,
    )


def _checkpoint_identity_from_envelope(
    envelope: VerificationOperationEnvelope,
    declaration: VerificationOperationDeclaration,
) -> VerificationCheckpointIdentityV1 | None:
    if not declaration.requires_checkpoint_identity:
        return None
    checkpoint = envelope.approval_identity.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise ValueError("Verification operation identity lacks checkpoint facts.")
    try:
        return VerificationCheckpointIdentityV1(
            checkpoint_id=checkpoint["checkpoint_id"],
            run_id=checkpoint["run_id"],
            request_id=checkpoint["request_id"],
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("Verification operation checkpoint identity is invalid.") from exc


def validate_verification_operation_envelope(
    envelope: VerificationOperationEnvelope,
) -> VerificationOperationEnvelope:
    """Reproject an envelope and reject any approval-identity drift."""

    if not isinstance(envelope, VerificationOperationEnvelope):
        raise ValueError("Verification operation envelope type changed.")
    if envelope.envelope_contract_version != ENVELOPE_CONTRACT_VERSION:
        raise ValueError("Verification operation envelope version changed.")
    declaration = resolve_verification_operation(envelope)
    expected = project_verification_operation(
        envelope.to_spec(),
        checkpoint_identity=_checkpoint_identity_from_envelope(
            envelope,
            declaration,
        ),
    )
    if envelope != expected:
        raise ValueError("Verification operation approval identity changed.")
    return expected


def project_attempt_result(
    attempt: VerificationAttempt,
    *,
    recovery_available: bool = False,
) -> VerificationAttemptResultV1:
    if isinstance(attempt, ObservationRetryAttemptV1):
        return VerificationAttemptResultV1(
            attempt_kind="observation_retry",
            attempt_number=attempt.retry_number,
            automatic_retry_count=0,
            retry_budget_remaining=attempt.retry_budget_remaining,
            current_attempt_is_retry=True,
            current_attempt_is_recovery=False,
            recovery_available=recovery_available,
        )
    if isinstance(attempt, AcceptedResumeRecoveryAttemptV1):
        return VerificationAttemptResultV1(
            attempt_kind="accepted_resume_recovery",
            attempt_number=1,
            automatic_retry_count=0,
            retry_budget_remaining=None,
            current_attempt_is_retry=False,
            current_attempt_is_recovery=True,
            recovery_available=recovery_available,
        )
    if isinstance(attempt, (InitialAttemptV1, VerificationAttemptPolicy)):
        return VerificationAttemptResultV1(
            attempt_kind="initial",
            attempt_number=1,
            automatic_retry_count=0,
            retry_budget_remaining=None,
            current_attempt_is_retry=False,
            current_attempt_is_recovery=False,
            recovery_available=recovery_available,
        )
    raise ValueError("Verification attempt type is not registered.")


def project_verification_operation_result(
    *,
    envelope: VerificationOperationEnvelope,
    platform_status: Literal["completed", "blocked", "partial"],
    failure_stage: str | None,
    side_effects_may_have_started: bool,
    store_receipts: tuple[VerificationOperationStoreReceiptV1, ...],
    blockers: tuple[VerificationOperationBlockerV1, ...],
    variant_result: VerificationResultVariant,
    audit_snapshot: Mapping[str, Any],
    recovery_available: bool = False,
) -> VerificationOperationResultV1:
    """Project the sole authoritative machine result for a resolved operation."""

    validate_verification_operation_envelope(envelope)
    declaration = resolve_verification_operation(envelope)
    if type(variant_result) is not declaration.result_variant_type:
        raise ValueError("Verification result variant does not match its declaration.")
    attempt_result = project_attempt_result(
        envelope.attempt_policy,
        recovery_available=recovery_available,
    )
    execution_disposition = declaration.result_projector(
        platform_status,
        variant_result,
    )
    outputs = _project_variant_output_refs(
        variant_result,
        attempt_result,
        declaration,
    )
    return VerificationOperationResultV1(
        result_contract_version=RESULT_CONTRACT_VERSION,
        operation_kind=envelope.operation_kind,
        operation_contract_version=envelope.operation_contract_version,
        approval_identity_hash=envelope.approval_identity_hash,
        identity_resolution_status="identity_resolved",
        platform_status=platform_status,
        execution_disposition=execution_disposition,
        failure_stage=failure_stage,
        side_effects_may_have_started=side_effects_may_have_started,
        attempt_result=attempt_result,
        outputs=outputs,
        store_receipts=store_receipts,
        blockers=blockers,
        variant_result=variant_result,
        audit_snapshot=dict(audit_snapshot),
    )


def project_rejected_verification_operation_result(
    *,
    operation_kind: str | None,
    operation_contract_version: str | None,
    approval_identity_hash: str | None,
    identity_resolution_status: Literal[
        "unresolved", "declaration_resolved", "approved_identity_only"
    ],
    failure_stage: Literal["authorization", "admission"],
    blockers: tuple[VerificationOperationBlockerV1, ...],
    audit_snapshot: Mapping[str, Any] | None = None,
) -> VerificationOperationResultV1:
    """Project an early structured rejection without inventing operation facts."""

    return VerificationOperationResultV1(
        result_contract_version=RESULT_CONTRACT_VERSION,
        operation_kind=operation_kind,
        operation_contract_version=operation_contract_version,
        approval_identity_hash=approval_identity_hash,
        identity_resolution_status=identity_resolution_status,
        platform_status="blocked",
        execution_disposition="platform_blocked",
        failure_stage=failure_stage,
        side_effects_may_have_started=False,
        attempt_result=None,
        outputs=(),
        store_receipts=(),
        blockers=blockers,
        variant_result=VerificationOperationRejectedResultV1(),
        audit_snapshot=dict(audit_snapshot or {}),
    )


def _validate_preflight_result(result: VerificationOperationPreflightResultV1) -> None:
    if result.result_contract_version != PREFLIGHT_RESULT_CONTRACT_VERSION:
        raise ValueError("Preflight result contract version changed.")
    if result.preflight_status not in {"ready", "blocked"}:
        raise ValueError("Preflight status is not registered.")
    if not isinstance(result.blockers, tuple) or any(
        not isinstance(item, VerificationOperationBlockerV1)
        for item in result.blockers
    ):
        raise ValueError("Preflight blockers must use the registered type.")
    _validate_json(result.audit_snapshot, "audit_snapshot")
    if result.preflight_status == "ready":
        if (
            result.identity_resolution_status != "identity_resolved"
            or result.operation_kind is None
            or result.operation_contract_version is None
            or result.envelope is None
            or result.approval_identity_hash is None
            or result.failure_stage is not None
            or result.blockers
        ):
            raise ValueError("Ready preflight result is incomplete.")
        envelope = validate_verification_operation_envelope(result.envelope)
        if (
            result.operation_kind != envelope.operation_kind
            or result.operation_contract_version != envelope.operation_contract_version
            or result.approval_identity_hash != envelope.approval_identity_hash
        ):
            raise ValueError("Ready preflight identity fields disagree.")
        return
    if result.preflight_status != "blocked" or not result.blockers:
        raise ValueError("Blocked preflight requires blockers.")
    if result.failure_stage not in {"authorization", "admission"}:
        raise ValueError("Blocked preflight failure stage is invalid.")
    if result.identity_resolution_status == "unresolved":
        if any(
            value is not None
            for value in (
                result.operation_kind,
                result.operation_contract_version,
                result.envelope,
                result.approval_identity_hash,
            )
        ) or result.failure_stage != "authorization":
            raise ValueError("Unresolved preflight leaked untrusted identity.")
    elif result.identity_resolution_status == "declaration_resolved":
        if (
            result.operation_kind is None
            or result.operation_contract_version is None
            or result.envelope is not None
            or result.approval_identity_hash is not None
            or result.failure_stage != "admission"
        ):
            raise ValueError("Declaration-resolved preflight shape is invalid.")
    elif result.identity_resolution_status == "identity_resolved":
        if (
            result.operation_kind is None
            or result.operation_contract_version is None
            or result.envelope is None
            or result.approval_identity_hash is None
            or result.failure_stage != "admission"
        ):
            raise ValueError("Identity-resolved preflight shape is invalid.")
        envelope = validate_verification_operation_envelope(result.envelope)
        if result.approval_identity_hash != envelope.approval_identity_hash:
            raise ValueError("Preflight approval identity hash changed.")
    else:
        raise ValueError("Preflight identity resolution status is invalid.")


def _result_declaration(result: VerificationOperationResultV1) -> VerificationOperationDeclaration:
    attempt_kind = result.attempt_result.attempt_kind if result.attempt_result else None
    matches = [
        item
        for item in _DECLARATIONS
        if item.operation_kind == result.operation_kind
        and item.operation_contract_version == result.operation_contract_version
        and type(result.variant_result) is item.result_variant_type
        and (
            (
                attempt_kind == "initial"
                and item.attempt_type
                in {InitialAttemptV1, VerificationAttemptPolicy}
            )
            or (
                attempt_kind == "observation_retry"
                and item.attempt_type is ObservationRetryAttemptV1
            )
            or (
                attempt_kind == "accepted_resume_recovery"
                and item.attempt_type is AcceptedResumeRecoveryAttemptV1
            )
        )
        and (
            not isinstance(result.variant_result, RuntimeExecutionResultV1)
            or item.completion_scope == result.variant_result.completion_scope
        )
    ]
    if len(matches) != 1:
        raise ValueError("Verification result shape is not registered.")
    return matches[0]


def _project_variant_output_refs(
    variant: VerificationResultVariant,
    attempt_result: VerificationAttemptResultV1,
    declaration: VerificationOperationDeclaration,
) -> tuple[VerificationOperationOutputV1, ...]:
    refs: dict[str, ArtifactRef | None] = {}
    if isinstance(variant, BuildVerificationResultV1):
        refs = {
            "build_result": variant.build_result_ref,
            "workflow_checkpoint": variant.workflow_checkpoint_ref,
        }
    elif isinstance(variant, RuntimeExecutionResultV1):
        refs = {
            "resume_report": (
                variant.resume_report_ref
                if attempt_result.attempt_kind == "initial"
                else None
            ),
            "runtime_evidence": variant.runtime_evidence_ref,
            **{ref.artifact_type: ref for ref in variant.terminal_refs},
        }
    elif isinstance(variant, RuntimeTerminalizationResultV1):
        refs = {
            "eval_report": variant.eval_report_ref,
            "blocked_report": variant.blocked_report_ref,
            "workflow_summary": variant.workflow_summary_ref,
        }
    elif isinstance(variant, EvidenceConsolidationResultV1):
        refs = {"runtime_evidence": variant.runtime_evidence_ref}
    return tuple(
        VerificationOperationOutputV1(role=role, artifact_ref=refs[role])
        for role, _artifact_type in declaration.output_artifact_roles
        if refs.get(role) is not None
    )


def _variant_output_refs(
    result: VerificationOperationResultV1,
    declaration: VerificationOperationDeclaration,
) -> tuple[VerificationOperationOutputV1, ...]:
    if result.attempt_result is None:
        return ()
    return _project_variant_output_refs(
        result.variant_result,
        result.attempt_result,
        declaration,
    )


def _completed_terminal_output_roles(
    *,
    blocked_report_ref: ArtifactRef | None,
    eval_report_ref: ArtifactRef | None,
    workflow_summary_ref: ArtifactRef | None,
) -> tuple[str, ...]:
    if blocked_report_ref is not None:
        if workflow_summary_ref is not None:
            raise ValueError("Completed terminal result has conflicting output chains.")
        return (
            ("eval_report", "blocked_report")
            if eval_report_ref is not None
            else ("blocked_report",)
        )
    if eval_report_ref is None or workflow_summary_ref is None:
        raise ValueError("Completed terminal result lacks its exact output chain.")
    return ("eval_report", "workflow_summary")


def _required_completed_output_roles(
    result: VerificationOperationResultV1,
) -> tuple[str, ...]:
    variant = result.variant_result
    attempt = result.attempt_result
    if isinstance(variant, BuildVerificationResultV1):
        roles = ["build_result"]
        if variant.handoff_ready:
            roles.append("workflow_checkpoint")
        return tuple(roles)
    if isinstance(variant, RuntimeExecutionResultV1):
        roles = []
        if attempt is not None and attempt.attempt_kind == "initial":
            roles.append("resume_report")
        roles.append("runtime_evidence")
        if variant.completion_scope == RUNTIME_WORKFLOW_COMPLETION:
            refs = {ref.artifact_type: ref for ref in variant.terminal_refs}
            roles.extend(
                _completed_terminal_output_roles(
                    blocked_report_ref=refs.get("blocked_report"),
                    eval_report_ref=refs.get("eval_report"),
                    workflow_summary_ref=refs.get("workflow_summary"),
                )
            )
        return tuple(roles)
    if isinstance(variant, RuntimeTerminalizationResultV1):
        return _completed_terminal_output_roles(
            blocked_report_ref=variant.blocked_report_ref,
            eval_report_ref=variant.eval_report_ref,
            workflow_summary_ref=variant.workflow_summary_ref,
        )
    if isinstance(variant, EvidenceConsolidationResultV1):
        return ("runtime_evidence",)
    raise ValueError("Completed verification result variant is not registered.")


def _validate_operation_result(result: VerificationOperationResultV1) -> None:
    if result.result_contract_version != RESULT_CONTRACT_VERSION:
        raise ValueError("Verification result contract version changed.")
    if result.platform_status not in {"completed", "blocked", "partial"}:
        raise ValueError("Verification result platform status is not registered.")
    if result.execution_disposition not in {
        "succeeded",
        "domain_blocked",
        "platform_blocked",
        "partial",
        "operator_input_required",
    }:
        raise ValueError("Verification result execution disposition is not registered.")
    if type(result.side_effects_may_have_started) is not bool:
        raise ValueError("side_effects_may_have_started must be bool.")
    if not isinstance(result.outputs, tuple) or any(
        not isinstance(item, VerificationOperationOutputV1) for item in result.outputs
    ):
        raise ValueError("Verification result outputs must use the registered type.")
    if not isinstance(result.store_receipts, tuple) or any(
        not isinstance(item, VerificationOperationStoreReceiptV1)
        for item in result.store_receipts
    ):
        raise ValueError("Verification result receipts must use the registered type.")
    if not isinstance(result.blockers, tuple) or any(
        not isinstance(item, VerificationOperationBlockerV1)
        for item in result.blockers
    ):
        raise ValueError("Verification result blockers must use the registered type.")
    _validate_json(result.audit_snapshot, "audit_snapshot")
    if result.platform_status == "blocked" and not result.blockers:
        raise ValueError("Blocked verification result requires blockers.")
    if result.identity_resolution_status in {
        "unresolved",
        "declaration_resolved",
        "approved_identity_only",
    }:
        if not isinstance(result.variant_result, VerificationOperationRejectedResultV1):
            raise ValueError("Unresolved identity requires the rejected result variant.")
        if result.outputs or result.store_receipts or result.side_effects_may_have_started:
            raise ValueError("Rejected result cannot report effects or Store outputs.")
        if result.attempt_result is not None:
            raise ValueError("Rejected result cannot claim a resolved attempt.")
        if (
            result.platform_status != "blocked"
            or result.execution_disposition != "platform_blocked"
        ):
            raise ValueError("Rejected result must be platform-blocked.")
        if result.identity_resolution_status == "unresolved":
            if any(
                value is not None
                for value in (
                    result.operation_kind,
                    result.operation_contract_version,
                    result.approval_identity_hash,
                )
            ) or result.failure_stage != "authorization":
                raise ValueError("Unresolved result leaked untrusted identity.")
        elif result.identity_resolution_status == "declaration_resolved":
            if (
                result.operation_kind is None
                or result.operation_contract_version is None
                or result.approval_identity_hash is not None
                or result.failure_stage not in {"authorization", "admission"}
            ):
                raise ValueError("Declaration-resolved result shape is invalid.")
        else:
            if (
                result.operation_kind is None
                or result.operation_contract_version is None
                or result.approval_identity_hash is None
                or result.failure_stage != "admission"
            ):
                raise ValueError("Approved-identity-only result shape is invalid.")
        return
    if result.identity_resolution_status != "identity_resolved":
        raise ValueError("Verification result identity resolution status is invalid.")
    if (
        result.operation_kind is None
        or result.operation_contract_version is None
        or result.approval_identity_hash is None
        or result.attempt_result is None
        or isinstance(result.variant_result, VerificationOperationRejectedResultV1)
    ):
        raise ValueError("Identity-resolved result is incomplete.")
    _require_non_empty(result.approval_identity_hash, "approval_identity_hash")
    declaration = _result_declaration(result)
    if (
        isinstance(result.variant_result, RuntimeExecutionResultV1)
        and result.attempt_result.attempt_kind != "initial"
        and result.variant_result.resume_report_ref is not None
    ):
        raise ValueError("Retry/recovery result cannot claim a new ResumeReport.")
    if result.failure_stage is not None and result.failure_stage not in declaration.failure_stages:
        raise ValueError("Verification result failure stage is not declared.")
    if result.platform_status == "completed" and result.failure_stage is not None:
        raise ValueError("Completed verification result cannot have a failure stage.")
    if result.platform_status in {"blocked", "partial"} and result.failure_stage is None:
        raise ValueError("Non-completed verification result requires a failure stage.")
    expected_disposition = declaration.result_projector(
        result.platform_status,
        result.variant_result,
    )
    if result.execution_disposition != expected_disposition:
        raise ValueError("Verification result disposition changed.")
    expected_outputs = _variant_output_refs(result, declaration)
    if result.outputs != expected_outputs:
        raise ValueError("Verification result outputs disagree with its variant.")
    allowed_roles = tuple(role for role, _artifact_type in declaration.output_artifact_roles)
    allowed_types = dict(declaration.output_artifact_roles)
    receipt_roles = tuple(item.role for item in result.store_receipts)
    if len(set(receipt_roles)) != len(receipt_roles) or any(
        role not in allowed_roles for role in receipt_roles
    ):
        raise ValueError("Verification result Store receipt roles changed.")
    output_by_role = {item.role: item.artifact_ref for item in result.outputs}
    receipt_by_role = {item.role: item for item in result.store_receipts}
    for receipt in result.store_receipts:
        from src.mod_agent.artifacts.store import ArtifactStoreError, ArtifactWriteResult

        try:
            parsed_write_result = ArtifactWriteResult.from_dict(
                receipt.artifact_write_result.to_dict()
            )
        except ArtifactStoreError as exc:
            raise ValueError("Verification Store receipt is not a valid C5 result.") from exc
        if parsed_write_result != receipt.artifact_write_result:
            raise ValueError("Verification Store receipt changed during strict parsing.")
        if receipt.artifact_write_result.artifact_type != allowed_types[receipt.role]:
            raise ValueError("Verification Store receipt Artifact type changed.")
        receipt_ref = receipt.artifact_write_result.artifact_ref
        output_ref = output_by_role.get(receipt.role)
        if receipt.artifact_write_result.outcome == "committed":
            if receipt_ref is None or output_ref != receipt_ref:
                raise ValueError(
                    "Committed Verification Store receipt disagrees with outputs."
                )
        elif output_ref is not None:
            raise ValueError("Verification Store receipt ref disagrees with outputs.")
    for role, output_ref in output_by_role.items():
        receipt = receipt_by_role.get(role)
        if (
            receipt is None
            or receipt.artifact_write_result.outcome != "committed"
            or receipt.artifact_write_result.artifact_ref != output_ref
        ):
            raise ValueError(
                "Verification output lacks its matching committed Store receipt."
            )
    if result.platform_status == "completed":
        required_roles = _required_completed_output_roles(result)
        if set(output_by_role) != set(required_roles):
            raise ValueError(
                "Completed verification result lacks its exact committed output chain."
            )
        if any(
            receipt.artifact_write_result.outcome != "committed"
            for receipt in result.store_receipts
        ):
            raise ValueError(
                "Completed verification result contains a non-committed Store receipt."
            )


def _result_variant_to_dict(variant: VerificationResultVariant) -> dict[str, Any]:
    if isinstance(variant, VerificationOperationRejectedResultV1):
        return variant.to_dict()
    if isinstance(variant, BuildVerificationResultV1):
        return {
            "domain_build_status": variant.domain_build_status,
            "claims_real_build_success": variant.claims_real_build_success,
            "build_result_ref": (
                None
                if variant.build_result_ref is None
                else artifact_ref_to_dict(variant.build_result_ref)
            ),
            "workflow_checkpoint_ref": (
                None
                if variant.workflow_checkpoint_ref is None
                else artifact_ref_to_dict(variant.workflow_checkpoint_ref)
            ),
            "handoff_ready": variant.handoff_ready,
        }
    if isinstance(variant, RuntimeExecutionResultV1):
        return {
            "completion_scope": variant.completion_scope,
            "domain_runtime_status": variant.domain_runtime_status,
            "resume_report_ref": (
                None
                if variant.resume_report_ref is None
                else artifact_ref_to_dict(variant.resume_report_ref)
            ),
            "runtime_evidence_ref": (
                None
                if variant.runtime_evidence_ref is None
                else artifact_ref_to_dict(variant.runtime_evidence_ref)
            ),
            "terminal_refs": [artifact_ref_to_dict(ref) for ref in variant.terminal_refs],
            "operator_input_required": variant.operator_input_required,
        }
    if isinstance(variant, RuntimeTerminalizationResultV1):
        return {
            "domain_acceptance_status": variant.domain_acceptance_status,
            "runtime_evidence_ref": artifact_ref_to_dict(variant.runtime_evidence_ref),
            "eval_report_ref": (
                None
                if variant.eval_report_ref is None
                else artifact_ref_to_dict(variant.eval_report_ref)
            ),
            "blocked_report_ref": (
                None
                if variant.blocked_report_ref is None
                else artifact_ref_to_dict(variant.blocked_report_ref)
            ),
            "workflow_summary_ref": (
                None
                if variant.workflow_summary_ref is None
                else artifact_ref_to_dict(variant.workflow_summary_ref)
            ),
        }
    return {
        "prior_runtime_evidence_ref": artifact_ref_to_dict(variant.prior_runtime_evidence_ref),
        "runtime_evidence_ref": (
            None
            if variant.runtime_evidence_ref is None
            else artifact_ref_to_dict(variant.runtime_evidence_ref)
        ),
        "derived_payload_hash": variant.derived_payload_hash,
        "semantic_binding_key": variant.semantic_binding_key,
        "semantic_binding_version": variant.semantic_binding_version,
    }
