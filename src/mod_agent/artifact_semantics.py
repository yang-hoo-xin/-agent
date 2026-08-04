"""Trusted semantic admission for ArtifactStore writes.

This module owns the neutral write context, ephemeral intent, and fixed
binding resolver.  Product semantics remain in the selected pure handler;
ArtifactStore remains the only commit-protocol owner.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from src.mod_agent.action_identity import hash_action_identity, hash_canonical_value
from src.mod_agent.artifacts.envelope import ArtifactRef
from src.mod_agent.verification_operations import ImplementationEvidenceFileBinding


ARTIFACT_WRITE_INTENT_SCHEMA_VERSION = "artifact_write_intent_v1"
SEMANTIC_CONFLICT_HASH_DOMAIN = "mod_agent.artifact_semantic_commit_conflict.v1"
RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY = "runtime_evidence_consolidation"
RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION = "1"


class ArtifactSemanticStore(Protocol):
    """Read-only Store surface used while projecting semantic admission."""

    def semantic_read_immutable(self, ref: ArtifactRef) -> Mapping[str, Any]: ...

    def list_feature_artifact_revisions(
        self,
        feature_id: str,
        artifact_type: str,
    ) -> list[ArtifactRef]: ...

    def list_feature_artifacts(self, feature_id: str) -> list[ArtifactRef]: ...

    def check_freshness(self, ref: ArtifactRef) -> Any: ...

    def project_artifact_hash(
        self,
        *,
        feature_id: str,
        artifact_type: str,
        payload: Mapping[str, Any],
        status: str,
        blockers: Sequence[Mapping[str, Any]],
        trace_refs: Sequence[str],
        upstream_refs: Sequence[ArtifactRef],
        exact_revision_upstream_types: set[str],
    ) -> str: ...


@dataclass(frozen=True)
class ArtifactSemanticWriteContext:
    """Read-only inputs supplied by ArtifactStore to one trusted handler."""

    artifact_type: str
    feature_id: str
    status: str
    submitted_payload: Mapping[str, Any]
    ordered_upstream_refs: tuple[ArtifactRef, ...]
    exact_revision_upstream_types: frozenset[str]
    blockers: tuple[Mapping[str, Any], ...]
    trace_refs: tuple[str, ...]
    protocol_refs: tuple[ArtifactRef, ...]
    execution_file_bindings: tuple[ImplementationEvidenceFileBinding, ...]
    reader: ArtifactSemanticStore


@dataclass(frozen=True)
class ArtifactSemanticProjection:
    """Pure handler result consumed by the neutral intent projector."""

    semantic_binding_key: str
    semantic_binding_version: str
    expected_payload: Mapping[str, Any]
    commit_conflict_key: Mapping[str, Any]


@dataclass(frozen=True)
class ArtifactWriteIntent:
    """Ephemeral exact write intent reprojected by ArtifactStore."""

    schema_version: str
    artifact_type: str
    feature_id: str
    status: str
    semantic_binding_key: str
    semantic_binding_version: str
    ordered_upstream_refs: tuple[ArtifactRef, ...]
    exact_revision_upstream_types: frozenset[str]
    blockers: tuple[Mapping[str, Any], ...]
    trace_refs: tuple[str, ...]
    protocol_refs: tuple[ArtifactRef, ...]
    execution_file_bindings: tuple[ImplementationEvidenceFileBinding, ...]
    commit_conflict_key: Mapping[str, Any]
    commit_conflict_key_hash: str
    expected_payload_hash: str
    expected_artifact_hash: str
    allowed_artifact_type: str


_TRUSTED_HANDLERS = {
    (
        "runtime_evidence",
        RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_KEY,
        RUNTIME_EVIDENCE_CONSOLIDATION_BINDING_VERSION,
    ): (
        "src.mod_agent.runtime_evidence_consolidation",
        "project_semantic_write",
    ),
}


def semantic_binding_from_payload(
    artifact_type: str,
    payload: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Return a registered semantic binding discriminator, if present."""

    if artifact_type != "runtime_evidence":
        return None
    binding = payload.get("verification_only_evidence_consolidation")
    if binding is None:
        return None
    if not isinstance(binding, Mapping):
        raise ValueError("Artifact semantic binding must be an object.")
    semantic_binding = binding.get("semantic_binding")
    if not isinstance(semantic_binding, Mapping) or set(semantic_binding) != {
        "key",
        "version",
    }:
        raise ValueError("Artifact semantic binding discriminator is invalid.")
    key = semantic_binding.get("key")
    version = semantic_binding.get("version")
    if not isinstance(key, str) or not isinstance(version, str):
        raise ValueError("Artifact semantic binding discriminator is invalid.")
    discriminator = (artifact_type, key, version)
    if discriminator not in _TRUSTED_HANDLERS:
        raise ValueError("Artifact semantic binding is not registered.")
    return key, version


def require_registered_semantic_binding(
    artifact_type: str,
    payload: Mapping[str, Any],
) -> tuple[str, str] | None:
    """Registry-facing structural check without interpreting business claims."""

    return semantic_binding_from_payload(artifact_type, payload)


def project_artifact_write_intent(
    *,
    reader: ArtifactSemanticStore,
    feature_id: str,
    artifact_type: str,
    payload: Mapping[str, Any],
    status: str,
    upstream_refs: Sequence[ArtifactRef],
    exact_revision_upstream_types: set[str],
    blockers: Sequence[Mapping[str, Any]] = (),
    trace_refs: Sequence[str] = (),
    protocol_refs: Sequence[ArtifactRef],
    execution_file_bindings: Sequence[ImplementationEvidenceFileBinding],
) -> ArtifactWriteIntent:
    """Project one trusted semantic intent without performing a Store write."""

    binding = semantic_binding_from_payload(artifact_type, payload)
    if binding is None:
        raise ValueError("Artifact payload has no registered semantic binding.")
    context = ArtifactSemanticWriteContext(
        artifact_type=artifact_type,
        feature_id=feature_id,
        status=status,
        submitted_payload=payload,
        ordered_upstream_refs=tuple(upstream_refs),
        exact_revision_upstream_types=frozenset(exact_revision_upstream_types),
        blockers=tuple(dict(item) for item in blockers),
        trace_refs=tuple(trace_refs),
        protocol_refs=tuple(protocol_refs),
        execution_file_bindings=tuple(execution_file_bindings),
        reader=reader,
    )
    projection = validate_artifact_semantic_write(context)
    if dict(payload) != dict(projection.expected_payload):
        raise ValueError("Submitted payload differs from the trusted semantic projection.")
    conflict_key = dict(projection.commit_conflict_key)
    conflict_key_hash = hash_action_identity(
        conflict_key,
        expected_hash_domain=SEMANTIC_CONFLICT_HASH_DOMAIN,
    )
    expected_payload_hash = hash_canonical_value(payload)
    expected_artifact_hash = reader.project_artifact_hash(
        feature_id=feature_id,
        artifact_type=artifact_type,
        payload=payload,
        status=status,
        blockers=tuple(blockers),
        trace_refs=tuple(trace_refs),
        upstream_refs=tuple(upstream_refs),
        exact_revision_upstream_types=set(exact_revision_upstream_types),
    )
    return ArtifactWriteIntent(
        schema_version=ARTIFACT_WRITE_INTENT_SCHEMA_VERSION,
        artifact_type=artifact_type,
        feature_id=feature_id,
        status=status,
        semantic_binding_key=projection.semantic_binding_key,
        semantic_binding_version=projection.semantic_binding_version,
        ordered_upstream_refs=tuple(upstream_refs),
        exact_revision_upstream_types=frozenset(exact_revision_upstream_types),
        blockers=tuple(dict(item) for item in blockers),
        trace_refs=tuple(trace_refs),
        protocol_refs=tuple(protocol_refs),
        execution_file_bindings=tuple(execution_file_bindings),
        commit_conflict_key=conflict_key,
        commit_conflict_key_hash=conflict_key_hash,
        expected_payload_hash=expected_payload_hash,
        expected_artifact_hash=expected_artifact_hash,
        allowed_artifact_type=artifact_type,
    )


def validate_artifact_semantic_write(
    context: ArtifactSemanticWriteContext,
) -> ArtifactSemanticProjection:
    """Resolve and invoke the platform-fixed handler for one semantic binding."""

    binding = semantic_binding_from_payload(
        context.artifact_type,
        context.submitted_payload,
    )
    if binding is None:
        raise ValueError("Artifact semantic write has no registered binding.")
    module_name, symbol_name = _TRUSTED_HANDLERS[
        (context.artifact_type, binding[0], binding[1])
    ]
    handler = getattr(importlib.import_module(module_name), symbol_name)
    projection = handler(context)
    if not isinstance(projection, ArtifactSemanticProjection):
        raise ValueError("Artifact semantic handler returned an invalid projection.")
    if (
        projection.semantic_binding_key != binding[0]
        or projection.semantic_binding_version != binding[1]
    ):
        raise ValueError("Artifact semantic handler binding changed.")
    return projection
