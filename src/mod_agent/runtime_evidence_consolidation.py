"""Canonical RuntimeEvidence implementation-evidence consolidation.

The module is a pure semantic owner.  It does not import Graph, checkpoint,
or the concrete ArtifactStore.  Files and immutable Artifacts are exposed
through the neutral read-only semantic context.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.mod_agent.action_identity import (
    canonical_action_json,
    hash_action_identity,
    hash_canonical_value,
)
from src.mod_agent.artifact_semantics import (
    ArtifactSemanticProjection,
    ArtifactSemanticWriteContext,
    RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY,
    RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION,
    SEMANTIC_CONFLICT_HASH_DOMAIN,
)
from src.mod_agent.artifacts.envelope import ArtifactRef
from src.mod_agent.verification_operations import (
    ACTION_IDENTITY_HASH_DOMAIN,
    ENVELOPE_CONTRACT_VERSION,
    EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
    EVIDENCE_CONSOLIDATION_KIND,
    EvidenceConsolidationOperationV1,
    ImplementationEvidenceFileBinding,
    VerificationAttemptPolicy,
    VerificationOperationEnvelope,
    VerificationOperationSpec,
    VerificationProtocolBinding,
    logical_artifact_identity,
    project_verification_operation,
    validate_verification_operation_envelope,
)


DELTA_SCHEMA_VERSION = "verification_only_criterion_evidence_delta_v1"
FEATURE_ADAPTER = "stagger_c4_implementation_evidence_v1"
BINDING_SCHEMA_VERSION = "verification_only_evidence_consolidation_v1"
BUILDER_CONTRACT_VERSION = "stagger_c4_implementation_evidence_builder_v1"
SUCCESSOR_POLICY = "one_child_per_predecessor_for_adapter_v1"
TARGET_SOURCE_LOGICAL_PATH = "Patches/HitFeedbackBehaviorPatch.cs"
_FILE_ROLES = (
    "source_contract_report",
    "source_contract_report_repeat",
    "target_source",
)
_STAGGER_C4_CRITERION = (
    "Each ES_Hitreact.ActivateState invocation with General.Enabled=true, "
    "a reaction type of Micro, Light, or Heavy, and a source that resolves "
    "to a locally owned PlayerAgent produces no more than one additional "
    "yellow X, one feature-attributable short audio cue, and one "
    "STAGGER_FEEDBACK_SHOWN signal within that invocation."
)
_STAGGER_C4_EVIDENCE_IDS = (
    "stagger_fresh_audio_source",
    "stagger_fresh_direct_activate_state_source",
    "stagger_fresh_source_contract_report",
    "stagger_fresh_yellow_x_source",
)
_REQUIRED_REPORT_CHECKS = (
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
_ACTION_SCOPE = {
    "allowed_artifact_types": ["runtime_evidence"],
    "attempt_budget": 1,
    "new_build": False,
    "new_runtime": False,
    "source_write": False,
    "recovery": False,
}


@dataclass(frozen=True)
class RuntimeEvidenceConsolidationAdapter:
    """Frozen bounded product-semantic descriptor."""

    delta_schema_version: str
    feature_adapter: str
    builder_contract_version: str
    successor_policy: str
    acceptance_criterion: str
    evidence_ids: tuple[str, ...]
    file_roles: tuple[str, ...]


_STAGGER_C4_ADAPTER = RuntimeEvidenceConsolidationAdapter(
    delta_schema_version=DELTA_SCHEMA_VERSION,
    feature_adapter=FEATURE_ADAPTER,
    builder_contract_version=BUILDER_CONTRACT_VERSION,
    successor_policy=SUCCESSOR_POLICY,
    acceptance_criterion=_STAGGER_C4_CRITERION,
    evidence_ids=_STAGGER_C4_EVIDENCE_IDS,
    file_roles=_FILE_ROLES,
)
_ADAPTERS = {(DELTA_SCHEMA_VERSION, FEATURE_ADAPTER): _STAGGER_C4_ADAPTER}


def resolve_adapter(delta: Mapping[str, Any]) -> RuntimeEvidenceConsolidationAdapter:
    key = (delta.get("schema_version"), delta.get("feature_adapter"))
    try:
        return _ADAPTERS[key]
    except (KeyError, TypeError) as exc:
        raise ValueError("RuntimeEvidence consolidation adapter is not registered.") from exc


def logical_identity(ref: ArtifactRef) -> dict[str, str]:
    return logical_artifact_identity(ref)


def canonicalize_delta(delta: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize the only registered Criterion delta."""

    adapter = resolve_adapter(delta)
    expected_keys = {
        "schema_version",
        "feature_adapter",
        "criterion_id",
        "acceptance_criterion",
        "before",
        "after",
        "evidence_ids",
        "file_roles",
        "evidence_level",
        "new_build_performed",
        "new_runtime_performed",
        "product_source_modified",
    }
    if set(delta) != expected_keys:
        raise ValueError("Consolidation delta fields do not match the v1 contract.")
    criterion = delta.get("acceptance_criterion")
    if not isinstance(criterion, str) or not criterion:
        raise ValueError("Consolidation acceptance_criterion must be non-empty.")
    criterion_id = "sha256:" + hashlib.sha256(criterion.encode("utf-8")).hexdigest()
    if (
        delta.get("schema_version") != adapter.delta_schema_version
        or delta.get("feature_adapter") != adapter.feature_adapter
        or criterion != adapter.acceptance_criterion
        or delta.get("criterion_id") != criterion_id
        or delta.get("before")
        != {"outcome": "not_observed", "evidence_strength": "none"}
        or delta.get("after")
        != {
            "outcome": "true",
            "evidence_strength": "bound_implementation_evidence",
        }
        or delta.get("evidence_ids") != list(adapter.evidence_ids)
        or delta.get("file_roles") != list(adapter.file_roles)
        or delta.get("evidence_level") != "implementation"
        or delta.get("new_build_performed") is not False
        or delta.get("new_runtime_performed") is not False
        or delta.get("product_source_modified") is not False
    ):
        raise ValueError("Consolidation delta does not match the registered adapter.")
    return json.loads(canonical_action_json(dict(delta)).decode("utf-8"))


def canonicalize_execution_file_bindings(
    bindings: Sequence[ImplementationEvidenceFileBinding],
    *,
    verify_bytes: bool,
) -> tuple[ImplementationEvidenceFileBinding, ...]:
    """Validate exact ephemeral locators without putting them in action identity."""

    by_role: dict[str, ImplementationEvidenceFileBinding] = {}
    for item in bindings:
        if not isinstance(item, ImplementationEvidenceFileBinding):
            raise ValueError("Implementation-evidence file binding type changed.")
        if item.role not in _FILE_ROLES or item.role in by_role:
            raise ValueError("Implementation-evidence file roles are invalid.")
        path = Path(item.absolute_path)
        if not path.is_absolute():
            raise ValueError("Implementation-evidence paths must be absolute.")
        if re.fullmatch(r"[0-9A-Fa-f]{64}", item.content_sha256) is None:
            raise ValueError("Implementation-evidence SHA256 is invalid.")
        logical_target = item.logical_target_path
        if item.role == "target_source":
            if logical_target != TARGET_SOURCE_LOGICAL_PATH:
                raise ValueError("Target source logical path changed.")
        elif logical_target is not None:
            raise ValueError("Report bindings cannot carry logical target paths.")
        canonical = ImplementationEvidenceFileBinding(
            role=item.role,
            absolute_path=str(path.resolve()),
            content_sha256=item.content_sha256.upper(),
            logical_target_path=logical_target,
        )
        if verify_bytes:
            try:
                actual = hashlib.sha256(
                    Path(canonical.absolute_path).read_bytes()
                ).hexdigest().upper()
            except OSError as exc:
                raise ValueError(
                    f"Implementation-evidence file cannot be read: {item.role}."
                ) from exc
            if actual != canonical.content_sha256:
                raise ValueError(
                    f"Implementation-evidence file hash changed: {item.role}."
                )
        by_role[item.role] = canonical
    if tuple(sorted(by_role)) != tuple(sorted(_FILE_ROLES)):
        raise ValueError("Implementation-evidence file bindings are incomplete.")
    return tuple(by_role[role] for role in _FILE_ROLES)


def durable_file_bindings(
    bindings: Sequence[ImplementationEvidenceFileBinding],
) -> list[dict[str, Any]]:
    canonical = canonicalize_execution_file_bindings(bindings, verify_bytes=False)
    return [
        {
            "role": item.role,
            "content_sha256": item.content_sha256,
            **(
                {}
                if item.logical_target_path is None
                else {"logical_target_path": item.logical_target_path}
            ),
        }
        for item in canonical
    ]


def action_projection_for_operation(
    operation: EvidenceConsolidationOperationV1,
) -> dict[str, Any]:
    """Declare the variant portion of the neutral Approval Identity."""

    if operation.output_status != "blocked":
        raise ValueError("Consolidation output status changed.")
    delta = canonicalize_delta(operation.canonical_delta)
    adapter = resolve_adapter(delta)
    files = durable_file_bindings(operation.execution_file_bindings)
    return {
        "feature_spec": logical_identity(operation.feature_spec_ref),
        "build_result": logical_identity(operation.build_result_ref),
        "prior_runtime_evidence": logical_identity(
            operation.prior_runtime_evidence_ref
        ),
        "evidence_pack": logical_identity(operation.evidence_pack_ref),
        "canonical_delta": delta,
        "file_bindings": files,
        "output_status": operation.output_status,
        "feature_adapter": adapter.feature_adapter,
        "builder_contract_version": adapter.builder_contract_version,
        "successor_policy": adapter.successor_policy,
        "action_scope": dict(_ACTION_SCOPE),
    }


def build_derived_payload(
    *,
    envelope: VerificationOperationEnvelope,
    prior_payload: Mapping[str, Any],
    feature_spec: Mapping[str, Any],
    evidence_pack: Mapping[str, Any],
    report: Mapping[str, Any],
    execution_file_bindings: Sequence[ImplementationEvidenceFileBinding],
) -> dict[str, Any]:
    """Deterministically apply the bounded C4 implementation-evidence delta."""

    envelope = validate_verification_operation_envelope(envelope)
    operation = envelope.variant_payload
    delta = canonicalize_delta(operation.canonical_delta)
    adapter = resolve_adapter(delta)
    canonical_files = canonicalize_execution_file_bindings(
        execution_file_bindings,
        verify_bytes=True,
    )
    durable_files = durable_file_bindings(canonical_files)
    criterion = str(delta["acceptance_criterion"])
    criteria = feature_spec.get("acceptance_criteria")
    if not isinstance(criteria, list) or criterion not in criteria:
        raise ValueError("Consolidation Criterion is not in the exact FeatureSpec.")
    _validate_source_contract_report(
        report,
        feature_spec_ref=operation.feature_spec_ref,
        file_bindings=canonical_files,
    )
    _validate_evidence_pack(
        evidence_pack,
        file_bindings=canonical_files,
        evidence_ids=adapter.evidence_ids,
    )

    payload = deepcopy(dict(prior_payload))
    evaluation = payload.get("stagger_acceptance_evaluation")
    result_items = evaluation.get("criteria") if isinstance(evaluation, Mapping) else None
    if not isinstance(result_items, list):
        raise ValueError("Prior RuntimeEvidence lacks Stagger Criterion results.")
    matching = [
        item
        for item in result_items
        if isinstance(item, dict) and item.get("acceptance_criterion") == criterion
    ]
    if len(matching) != 1:
        raise ValueError("Prior RuntimeEvidence does not bind one target Criterion.")
    target = matching[0]
    if {
        "outcome": target.get("outcome"),
        "evidence_strength": target.get("evidence_strength"),
    } != delta["before"]:
        raise ValueError("Prior Criterion state does not match the approved delta.")

    file_by_role = {item["role"]: item for item in durable_files}
    evidence_refs = [
        {
            "source": "artifact_store_evidence_pack",
            **logical_identity(operation.evidence_pack_ref),
            "evidence_ids": list(adapter.evidence_ids),
        },
        {
            "source": "deterministic_source_contract_report",
            **file_by_role["source_contract_report"],
        },
        {
            "source": "reviewed_target_source",
            **file_by_role["target_source"],
        },
    ]
    target.update(delta["after"])
    target["evidence_refs"] = evidence_refs
    report_excerpt = json.dumps(
        {
            "status": report["status"],
            "source_sha256_before": report["source_sha256_before"],
            "source_sha256_after": report["source_sha256_after"],
            "invocation_counts": report["invocation_counts"],
            "loop_count": report["loop_count"],
            "checks": report["checks"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    payload["evidence_items"] = [
        *payload.get("evidence_items", ()),
        {
            "type": "deterministic_source_contract_report",
            "source": "deterministic_source_contract_report",
            "content_sha256": file_by_role["source_contract_report"][
                "content_sha256"
            ],
            "supports_acceptance": [criterion],
            "confidence": 1.0,
            "raw_excerpt": report_excerpt,
        },
    ]
    payload["sources"] = [
        *payload.get("sources", ()),
        {
            "source_type": "deterministic_source_contract_report",
            "file_bindings": durable_files,
            "evidence_pack": logical_identity(operation.evidence_pack_ref),
            "claim": criterion,
            "confidence": 1.0,
        },
    ]
    payload["message"] = (
        "Prior Runtime observations are preserved; the selected Criterion is "
        "additionally bound to deterministic implementation evidence."
    )
    payload["evidence_source"] = (
        "prior_runtime_observation_plus_deterministic_implementation_evidence"
    )
    payload["limitations"] = [
        *payload.get("limitations", ()),
        "No new Build or Runtime was performed by this consolidation.",
        "Only the selected Criterion received implementation-level evidence.",
    ]
    payload["prior_runtime_evidence_ref"] = logical_identity(
        operation.prior_runtime_evidence_ref
    )
    payload["implementation_evidence_binding"] = {
        "schema_version": "stagger_c4_implementation_evidence_binding_v1",
        "criterion_id": delta["criterion_id"],
        "criterion_status": "passed",
        "evidence_level": delta["evidence_level"],
        "feature_spec_ref": logical_identity(operation.feature_spec_ref),
        "evidence_pack_ref": {
            **logical_identity(operation.evidence_pack_ref),
            "evidence_ids": list(adapter.evidence_ids),
        },
        "file_bindings": durable_files,
        "build_result_ref": logical_identity(operation.build_result_ref),
        "prior_runtime_evidence_ref": logical_identity(
            operation.prior_runtime_evidence_ref
        ),
        "new_build_performed": False,
        "new_runtime_performed": False,
        "product_source_modified": False,
    }
    protocol = envelope.protocol_binding
    payload["verification_only_evidence_consolidation"] = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "semantic_binding": {
            "key": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY,
            "version": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION,
        },
        "envelope_contract_version": ENVELOPE_CONTRACT_VERSION,
        "operation_kind": EVIDENCE_CONSOLIDATION_KIND,
        "operation_contract_version": EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        "feature_adapter": adapter.feature_adapter,
        "builder_contract_version": adapter.builder_contract_version,
        "successor_policy": adapter.successor_policy,
        "action_identity": dict(envelope.approval_identity),
        "action_identity_hash": envelope.approval_identity_hash,
        "canonical_delta": delta,
        "canonical_delta_hash": hash_canonical_value(delta),
        "inputs": {
            "build_result": logical_identity(operation.build_result_ref),
            "feature_spec": logical_identity(operation.feature_spec_ref),
            "prior_runtime_evidence": logical_identity(
                operation.prior_runtime_evidence_ref
            ),
            "evidence_pack": logical_identity(operation.evidence_pack_ref),
        },
        "protocol_binding": {
            "checkpoint": logical_identity(protocol.checkpoint_ref),
            "accepted_resume_report": logical_identity(
                protocol.accepted_resume_report_ref
            ),
            "resume_id": protocol.resume_id,
            "approved_by": protocol.approved_by,
        },
        "file_bindings": durable_files,
        "action_scope": dict(_ACTION_SCOPE),
        "new_build_performed": False,
        "new_runtime_performed": False,
        "product_source_modified": False,
    }
    return payload


def project_operation_payload(
    envelope: VerificationOperationEnvelope,
    reader: Any,
) -> dict[str, Any]:
    """Rebuild one operation output from immutable inputs and current bytes."""

    envelope = validate_verification_operation_envelope(envelope)
    operation = envelope.variant_payload
    protocol = envelope.protocol_binding
    checkpoint_ref = protocol.checkpoint_ref
    report_ref = protocol.accepted_resume_report_ref
    checkpoint_envelope = reader.semantic_read_immutable(checkpoint_ref)
    report_envelope = reader.semantic_read_immutable(report_ref)
    prior_envelope = reader.semantic_read_immutable(
        operation.prior_runtime_evidence_ref
    )
    evidence_envelope = reader.semantic_read_immutable(operation.evidence_pack_ref)
    reader.semantic_read_immutable(operation.build_result_ref)
    feature_envelope = reader.semantic_read_immutable(operation.feature_spec_ref)
    _validate_protocol(
        checkpoint_ref=checkpoint_ref,
        checkpoint=checkpoint_envelope["data"],
        report_ref=report_ref,
        report_envelope=report_envelope,
        protocol=protocol,
        feature_ref=operation.feature_spec_ref,
        build_ref=operation.build_result_ref,
        evidence_ref=operation.evidence_pack_ref,
    )
    _validate_artifact_lineage(
        prior_envelope=prior_envelope,
        evidence_envelope=evidence_envelope,
        build_ref=operation.build_result_ref,
        feature_ref=operation.feature_spec_ref,
    )
    _validate_latest_fresh(reader, operation.prior_runtime_evidence_ref)
    _validate_latest_fresh(reader, operation.evidence_pack_ref)
    _validate_no_existing_child(
        reader,
        feature_id=operation.prior_runtime_evidence_ref.feature_id,
        prior_ref=operation.prior_runtime_evidence_ref,
        feature_adapter=FEATURE_ADAPTER,
    )
    canonical_files = canonicalize_execution_file_bindings(
        operation.execution_file_bindings,
        verify_bytes=True,
    )
    report = _load_and_validate_files(
        file_bindings=canonical_files,
        evidence_pack=evidence_envelope["data"],
    )
    return build_derived_payload(
        envelope=envelope,
        prior_payload=prior_envelope["data"],
        feature_spec=feature_envelope["data"],
        evidence_pack=evidence_envelope["data"],
        report=report,
        execution_file_bindings=canonical_files,
    )


def project_semantic_write(
    context: ArtifactSemanticWriteContext,
) -> ArtifactSemanticProjection:
    """Rebuild the approved action and submitted payload from Store context."""

    if (
        context.artifact_type != "runtime_evidence"
        or context.status != "blocked"
        or context.blockers
        or context.trace_refs
        or [ref.artifact_type for ref in context.ordered_upstream_refs]
        != ["build_result", "feature_spec", "runtime_evidence", "evidence_pack"]
        or context.exact_revision_upstream_types
        != frozenset({"runtime_evidence", "evidence_pack"})
        or len(context.protocol_refs) != 2
        or [ref.artifact_type for ref in context.protocol_refs]
        != ["workflow_checkpoint", "resume_report"]
    ):
        raise ValueError("RuntimeEvidence consolidation write boundary changed.")
    binding = _binding(context.submitted_payload)
    validate_persisted_identity(context.submitted_payload)
    upstreams = context.ordered_upstream_refs
    build_ref, feature_ref, prior_ref, evidence_ref = upstreams
    checkpoint_ref, report_ref = context.protocol_refs
    canonical_files = canonicalize_execution_file_bindings(
        context.execution_file_bindings,
        verify_bytes=True,
    )
    operation = EvidenceConsolidationOperationV1(
        feature_spec_ref=feature_ref,
        build_result_ref=build_ref,
        prior_runtime_evidence_ref=prior_ref,
        evidence_pack_ref=evidence_ref,
        canonical_delta=dict(binding.get("canonical_delta") or {}),
        execution_file_bindings=canonical_files,
        output_status="blocked",
    )
    protocol_binding = binding.get("protocol_binding")
    if not isinstance(protocol_binding, Mapping):
        raise ValueError("Consolidation protocol binding is missing.")
    spec = VerificationOperationSpec(
        operation_kind=EVIDENCE_CONSOLIDATION_KIND,
        operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
        attempt_policy=VerificationAttemptPolicy(
            attempt_budget=1,
            retry_allowed=False,
            recovery_allowed=False,
        ),
        protocol_binding=VerificationProtocolBinding(
            checkpoint_ref=checkpoint_ref,
            accepted_resume_report_ref=report_ref,
            resume_id=str(protocol_binding.get("resume_id") or ""),
            approved_by=str(protocol_binding.get("approved_by") or ""),
        ),
        variant_payload=operation,
    )
    envelope = project_verification_operation(spec)
    if (
        binding.get("action_identity") != envelope.approval_identity
        or binding.get("action_identity_hash") != envelope.approval_identity_hash
    ):
        raise ValueError("Consolidation action identity cannot be reconstructed.")
    expected_payload = project_operation_payload(envelope, context.reader)
    if dict(context.submitted_payload) != expected_payload:
        raise ValueError(
            "RuntimeEvidence payload changes exceed the approved consolidation delta."
        )
    conflict_key = {
        "hash_domain": SEMANTIC_CONFLICT_HASH_DOMAIN,
        "feature_id": context.feature_id,
        "semantic_binding_key": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY,
        "semantic_binding_version": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION,
        "feature_adapter": FEATURE_ADAPTER,
        "predecessor_artifact_hash": prior_ref.artifact_hash,
    }
    return ArtifactSemanticProjection(
        semantic_binding_key=RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY,
        semantic_binding_version=RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION,
        expected_payload=expected_payload,
        commit_conflict_key=conflict_key,
    )


def validate_persisted_identity(payload: Mapping[str, Any]) -> str:
    """Recompute the neutral Action Identity hash from one durable payload."""

    binding = _binding(payload)
    identity = binding.get("action_identity")
    identity_hash = binding.get("action_identity_hash")
    if not isinstance(identity, Mapping):
        raise ValueError("RuntimeEvidence consolidation action identity is missing.")
    expected = hash_action_identity(
        identity,
        expected_hash_domain=ACTION_IDENTITY_HASH_DOMAIN,
    )
    if identity_hash != expected:
        raise ValueError("RuntimeEvidence consolidation identity hash is invalid.")
    return expected


def _binding(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    binding = payload.get("verification_only_evidence_consolidation")
    if not isinstance(binding, Mapping):
        raise ValueError("RuntimeEvidence consolidation binding is missing.")
    required = {
        "schema_version",
        "semantic_binding",
        "envelope_contract_version",
        "operation_kind",
        "operation_contract_version",
        "feature_adapter",
        "builder_contract_version",
        "successor_policy",
        "action_identity",
        "action_identity_hash",
        "canonical_delta",
        "canonical_delta_hash",
        "inputs",
        "protocol_binding",
        "file_bindings",
        "action_scope",
        "new_build_performed",
        "new_runtime_performed",
        "product_source_modified",
    }
    if set(binding) != required:
        raise ValueError("RuntimeEvidence consolidation binding fields changed.")
    delta = canonicalize_delta(binding.get("canonical_delta") or {})
    adapter = resolve_adapter(delta)
    if (
        binding.get("schema_version") != BINDING_SCHEMA_VERSION
        or binding.get("semantic_binding")
        != {
            "key": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY,
            "version": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION,
        }
        or binding.get("envelope_contract_version") != ENVELOPE_CONTRACT_VERSION
        or binding.get("operation_kind") != EVIDENCE_CONSOLIDATION_KIND
        or binding.get("operation_contract_version")
        != EVIDENCE_CONSOLIDATION_CONTRACT_VERSION
        or binding.get("feature_adapter") != adapter.feature_adapter
        or binding.get("builder_contract_version")
        != adapter.builder_contract_version
        or binding.get("successor_policy") != adapter.successor_policy
        or binding.get("canonical_delta_hash") != hash_canonical_value(delta)
        or binding.get("action_scope") != _ACTION_SCOPE
        or binding.get("new_build_performed") is not False
        or binding.get("new_runtime_performed") is not False
        or binding.get("product_source_modified") is not False
    ):
        raise ValueError("RuntimeEvidence consolidation binding is inconsistent.")
    return binding


def _validate_protocol(
    *,
    checkpoint_ref: ArtifactRef,
    checkpoint: Mapping[str, Any],
    report_ref: ArtifactRef,
    report_envelope: Mapping[str, Any],
    protocol: VerificationProtocolBinding,
    feature_ref: ArtifactRef,
    build_ref: ArtifactRef,
    evidence_ref: ArtifactRef,
) -> None:
    report = report_envelope.get("data")
    report_upstreams = report_envelope.get("inputs", {}).get("upstream_artifacts", [])
    if not isinstance(report, Mapping):
        raise ValueError("Accepted ResumeReport payload is invalid.")
    snapshot = checkpoint.get("state_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("WorkflowCheckpoint state snapshot is missing.")
    if (
        protocol.checkpoint_ref != checkpoint_ref
        or protocol.accepted_resume_report_ref != report_ref
        or not protocol.resume_id
        or not protocol.approved_by.strip()
        or report.get("checkpoint_id") != checkpoint.get("checkpoint_id")
        or report.get("run_id") != checkpoint.get("run_id")
        or report.get("resume_id") != protocol.resume_id
        or report.get("approved_by") != protocol.approved_by
        or report.get("decision") != "approve"
        or report.get("status") != "accepted"
        or report.get("allowed") is not True
        or (report.get("applied_updates") or {}).get("restored_state") != snapshot
        or not isinstance(report_upstreams, list)
        or len(report_upstreams) != 1
        or not _serialized_ref_matches(report_upstreams[0], checkpoint_ref)
    ):
        raise ValueError("Consolidation protocol identity is invalid.")
    for artifact_type, expected_ref in (
        ("feature_spec", feature_ref),
        ("build_result", build_ref),
        ("evidence_pack", evidence_ref),
    ):
        if _snapshot_ref(snapshot, artifact_type, checkpoint_ref.feature_id) != expected_ref:
            raise ValueError(f"Checkpoint {artifact_type} identity changed.")


def _validate_artifact_lineage(
    *,
    prior_envelope: Mapping[str, Any],
    evidence_envelope: Mapping[str, Any],
    build_ref: ArtifactRef,
    feature_ref: ArtifactRef,
) -> None:
    if (
        prior_envelope.get("status") != "blocked"
        or evidence_envelope.get("status") != "blocked"
        or not _envelope_binds(prior_envelope, build_ref)
        or not _envelope_binds(prior_envelope, feature_ref)
        or not _envelope_binds(evidence_envelope, feature_ref)
    ):
        raise ValueError("Consolidation Artifact lineage is invalid.")


def _validate_latest_fresh(
    reader: Any,
    ref: ArtifactRef,
) -> None:
    latest = [
        item
        for item in reader.list_feature_artifacts(ref.feature_id)
        if item.artifact_type == ref.artifact_type
    ]
    freshness = reader.check_freshness(ref)
    if (
        len(latest) != 1
        or latest[0].artifact_hash != ref.artifact_hash
        or not freshness.is_fresh
    ):
        raise ValueError(f"Consolidation {ref.artifact_type} is not latest and fresh.")


def _validate_no_existing_child(
    reader: Any,
    *,
    feature_id: str,
    prior_ref: ArtifactRef,
    feature_adapter: str,
) -> None:
    if runtime_evidence_consolidation_child_refs(
        reader,
        feature_id=feature_id,
        prior_ref=prior_ref,
        feature_adapter=feature_adapter,
    ):
        raise ValueError("RuntimeEvidence consolidation already started.")


def runtime_evidence_consolidation_child_refs(
    reader: Any,
    *,
    feature_id: str,
    prior_ref: ArtifactRef,
    feature_adapter: str,
) -> tuple[ArtifactRef, ...]:
    """Return exact successors governed by this trusted semantic owner."""

    if feature_id != prior_ref.feature_id:
        raise ValueError("RuntimeEvidence predecessor feature identity changed.")
    if feature_adapter not in {
        adapter.feature_adapter for adapter in _ADAPTERS.values()
    }:
        raise ValueError("RuntimeEvidence consolidation adapter is not registered.")
    expected_semantic_binding = {
        "key": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY,
        "version": RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION,
    }
    children: list[ArtifactRef] = []
    for ref in reader.list_feature_artifact_revisions(
        feature_id,
        "runtime_evidence",
    ):
        if ref.artifact_hash == prior_ref.artifact_hash:
            continue
        envelope = reader.semantic_read_immutable(ref)
        if not _envelope_binds(envelope, prior_ref):
            continue
        payload = envelope.get("data")
        binding = (
            payload.get("verification_only_evidence_consolidation")
            if isinstance(payload, Mapping)
            else None
        )
        if not isinstance(binding, Mapping):
            continue
        if (
            binding.get("semantic_binding") != expected_semantic_binding
            or binding.get("feature_adapter") != feature_adapter
        ):
            continue
        _binding(payload)
        children.append(ref)
    return tuple(children)


def _load_and_validate_files(
    *,
    file_bindings: Sequence[ImplementationEvidenceFileBinding],
    evidence_pack: Mapping[str, Any],
) -> Mapping[str, Any]:
    canonical = canonicalize_execution_file_bindings(file_bindings, verify_bytes=True)
    by_role = {item.role: item for item in canonical}
    evidence_items = {
        item.get("evidence_id"): item
        for item in evidence_pack.get("items", ())
        if isinstance(item, Mapping)
    }
    source_item = evidence_items.get("stagger_fresh_direct_activate_state_source")
    report_item = evidence_items.get("stagger_fresh_source_contract_report")
    if not isinstance(source_item, Mapping) or not isinstance(report_item, Mapping):
        raise ValueError("EvidencePack file provenance is incomplete.")
    target_path = Path(by_role["target_source"].absolute_path).resolve()
    report_path = Path(by_role["source_contract_report"].absolute_path).resolve()
    repeat_path = Path(
        by_role["source_contract_report_repeat"].absolute_path
    ).resolve()
    if (
        Path(str(source_item.get("source_path"))).resolve() != target_path
        or Path(str(report_item.get("source_path"))).resolve() != report_path
        or repeat_path.parent != report_path.parent
        or repeat_path.name != "source_contract_report_repeat.json"
        or by_role["source_contract_report_repeat"].content_sha256
        != by_role["source_contract_report"].content_sha256
        or repeat_path.read_bytes() != report_path.read_bytes()
    ):
        raise ValueError("Implementation-evidence file containment changed.")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Source contract report is not valid UTF-8 JSON.") from exc
    if not isinstance(report, Mapping):
        raise ValueError("Source contract report must be an object.")
    return report


def _validate_source_contract_report(
    report: Mapping[str, Any],
    *,
    feature_spec_ref: ArtifactRef,
    file_bindings: Sequence[ImplementationEvidenceFileBinding],
) -> None:
    by_role = {item.role: item for item in file_bindings}
    source_hash = by_role["target_source"].content_sha256
    checks = report.get("checks")
    if (
        report.get("status") != "passed"
        or report.get("feature_spec_artifact_hash") != feature_spec_ref.artifact_hash
        or str(report.get("source_sha256_before") or "").upper() != source_hash
        or str(report.get("source_sha256_after") or "").upper() != source_hash
        or report.get("target_code_executed") is not False
        or report.get("invocation_counts")
        != {"visual": 1, "audio": 1, "marker": 1, "recursive_postfix": 0}
        or report.get("loop_count") != 0
        or not isinstance(checks, Mapping)
        or any(checks.get(name) is not True for name in _REQUIRED_REPORT_CHECKS)
    ):
        raise ValueError("Source contract report does not prove the C4 delta.")


def _validate_evidence_pack(
    evidence_pack: Mapping[str, Any],
    *,
    file_bindings: Sequence[ImplementationEvidenceFileBinding],
    evidence_ids: Sequence[str],
) -> None:
    by_role = {item.role: item for item in file_bindings}
    source_hash = by_role["target_source"].content_sha256
    report_hash = by_role["source_contract_report"].content_sha256
    items = {
        item.get("evidence_id"): item
        for item in evidence_pack.get("items", ())
        if isinstance(item, Mapping)
    }
    if any(evidence_id not in items for evidence_id in evidence_ids):
        raise ValueError("EvidencePack does not contain every delta evidence ID.")
    for evidence_id in evidence_ids:
        item = items[evidence_id]
        hashes = {
            str(item.get("file_hash") or "").upper(),
            str(item.get("source_hash") or "").upper(),
        } - {""}
        if not hashes or not hashes.issubset({source_hash, report_hash}):
            raise ValueError("EvidencePack item file identity changed.")


def _snapshot_ref(
    snapshot: Mapping[str, Any],
    artifact_type: str,
    feature_id: str,
) -> ArtifactRef:
    artifacts = snapshot.get("artifacts") or {}
    hashes = snapshot.get("artifact_hashes") or {}
    path = artifacts.get(artifact_type)
    artifact_hash = hashes.get(artifact_type)
    if not isinstance(path, str) or not isinstance(artifact_hash, str):
        raise ValueError(f"Checkpoint snapshot is missing {artifact_type}.")
    return ArtifactRef(
        feature_id=feature_id,
        artifact_type=artifact_type,
        path=path,
        artifact_hash=artifact_hash,
    )


def _serialized_ref_matches(value: object, ref: ArtifactRef) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("artifact_type") == ref.artifact_type
        and value.get("path") == ref.path
        and value.get("artifact_hash") == ref.artifact_hash
    )


def _envelope_binds(envelope: Mapping[str, Any], ref: ArtifactRef) -> bool:
    return any(
        _serialized_ref_matches(item, ref)
        for item in envelope.get("inputs", {}).get("upstream_artifacts", ())
    )
