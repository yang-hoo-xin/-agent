"""Typed authority family for verification-only public operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from src.mod_agent.action_identity import hash_action_identity
from src.mod_agent.artifacts.envelope import ArtifactRef


ENVELOPE_CONTRACT_VERSION = "verification_operation_envelope_v1"
EVIDENCE_CONSOLIDATION_KIND = "runtime_evidence_consolidation"
EVIDENCE_CONSOLIDATION_CONTRACT_VERSION = "runtime_evidence_consolidation_v1"
ACTION_IDENTITY_SCHEMA_VERSION = "verification_operation_action_identity_v1"
ACTION_IDENTITY_HASH_DOMAIN = "mod_agent.verification_operation_action_identity.v1"


@dataclass(frozen=True)
class VerificationAttemptPolicy:
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
class VerificationProtocolBinding:
    checkpoint_ref: ArtifactRef
    accepted_resume_report_ref: ArtifactRef
    resume_id: str
    approved_by: str


@dataclass(frozen=True)
class ImplementationEvidenceFileBinding:
    role: str
    absolute_path: str
    content_sha256: str
    logical_target_path: str | None = None


@dataclass(frozen=True)
class EvidenceConsolidationOperationV1:
    feature_spec_ref: ArtifactRef
    build_result_ref: ArtifactRef
    prior_runtime_evidence_ref: ArtifactRef
    evidence_pack_ref: ArtifactRef
    canonical_delta: Mapping[str, Any]
    execution_file_bindings: tuple[ImplementationEvidenceFileBinding, ...]
    output_status: Literal["blocked"] = "blocked"


@dataclass(frozen=True)
class VerificationOperationSpec:
    operation_kind: str
    operation_contract_version: str
    attempt_policy: VerificationAttemptPolicy
    protocol_binding: VerificationProtocolBinding
    variant_payload: EvidenceConsolidationOperationV1


@dataclass(frozen=True)
class VerificationOperationEnvelope:
    envelope_contract_version: str
    operation_kind: str
    operation_contract_version: str
    approval_identity: Mapping[str, Any]
    approval_identity_hash: str
    attempt_policy: VerificationAttemptPolicy
    protocol_binding: VerificationProtocolBinding
    variant_payload: EvidenceConsolidationOperationV1

    def to_spec(self) -> VerificationOperationSpec:
        return VerificationOperationSpec(
            operation_kind=self.operation_kind,
            operation_contract_version=self.operation_contract_version,
            attempt_policy=self.attempt_policy,
            protocol_binding=self.protocol_binding,
            variant_payload=self.variant_payload,
        )


@dataclass(frozen=True)
class VerificationOperationDeclaration:
    operation_kind: str
    operation_contract_version: str
    variant_type: type
    allowed_attempt_policy: VerificationAttemptPolicy
    side_effect_class: str
    output_artifact_types: tuple[str, ...]
    result_contract: str


_EVIDENCE_CONSOLIDATION_DECLARATION = VerificationOperationDeclaration(
    operation_kind=EVIDENCE_CONSOLIDATION_KIND,
    operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
    variant_type=EvidenceConsolidationOperationV1,
    allowed_attempt_policy=VerificationAttemptPolicy(
        attempt_budget=1,
        retry_allowed=False,
        recovery_allowed=False,
    ),
    side_effect_class="one_runtime_evidence_artifact_write",
    output_artifact_types=("runtime_evidence",),
    result_contract="verification_operation_result_v1",
)
_DECLARATIONS = {
    (
        _EVIDENCE_CONSOLIDATION_DECLARATION.operation_kind,
        _EVIDENCE_CONSOLIDATION_DECLARATION.operation_contract_version,
    ): _EVIDENCE_CONSOLIDATION_DECLARATION,
}


def resolve_verification_operation(
    operation: VerificationOperationSpec | VerificationOperationEnvelope,
) -> VerificationOperationDeclaration:
    """Resolve one exact registered operation without a generic fallback."""

    key = (operation.operation_kind, operation.operation_contract_version)
    declaration = _DECLARATIONS.get(key)
    if declaration is None:
        raise ValueError("Verification operation kind/version is not registered.")
    if type(operation.variant_payload) is not declaration.variant_type:
        raise ValueError("Verification operation variant type changed.")
    if operation.attempt_policy != declaration.allowed_attempt_policy:
        raise ValueError("Verification operation attempt policy changed.")
    return declaration


def logical_artifact_identity(ref: ArtifactRef) -> dict[str, str]:
    return {
        "artifact_type": ref.artifact_type,
        "artifact_hash": ref.artifact_hash,
        "feature_id": ref.feature_id,
    }


def project_verification_operation(
    spec: VerificationOperationSpec,
) -> VerificationOperationEnvelope:
    """Build the only canonical approval projection for one operation spec."""

    declaration = resolve_verification_operation(spec)
    if declaration is not _EVIDENCE_CONSOLIDATION_DECLARATION:
        raise ValueError("Verification operation declaration has no projector.")
    from src.mod_agent.runtime_evidence_consolidation import (
        action_projection_for_operation,
    )

    identity = {
        "identity_schema_version": ACTION_IDENTITY_SCHEMA_VERSION,
        "hash_domain": ACTION_IDENTITY_HASH_DOMAIN,
        "operation_kind": declaration.operation_kind,
        "operation_contract_version": declaration.operation_contract_version,
        "attempt_policy": spec.attempt_policy.to_dict(),
        "protocol_binding": {
            "checkpoint": logical_artifact_identity(
                spec.protocol_binding.checkpoint_ref
            ),
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
    identity_hash = hash_action_identity(
        identity,
        expected_hash_domain=ACTION_IDENTITY_HASH_DOMAIN,
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


def validate_verification_operation_envelope(
    envelope: VerificationOperationEnvelope,
) -> VerificationOperationEnvelope:
    """Reproject an envelope and reject any authority drift."""

    if envelope.envelope_contract_version != ENVELOPE_CONTRACT_VERSION:
        raise ValueError("Verification operation envelope version changed.")
    expected = project_verification_operation(envelope.to_spec())
    if envelope != expected:
        raise ValueError("Verification operation approval identity changed.")
    return expected
