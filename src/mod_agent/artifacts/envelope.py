"""Artifact envelope and reference types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactRef:
    """Stable pointer to a feature-scoped artifact."""

    feature_id: str
    artifact_type: str
    path: str
    artifact_hash: str


@dataclass(frozen=True)
class ArtifactEnvelope:
    """Auditable wrapper around an artifact payload."""

    schema_version: str
    artifact_type: str
    feature_id: str
    producer_stage: str
    status: str
    data: dict[str, Any]
    artifact_hash: str
    inputs: dict[str, Any]
    blockers: list[dict[str, Any]]
    trace_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "feature_id": self.feature_id,
            "producer_stage": self.producer_stage,
            "status": self.status,
            "data": self.data,
            "artifact_hash": self.artifact_hash,
            "inputs": self.inputs,
            "blockers": self.blockers,
            "trace_refs": self.trace_refs,
        }
