"""Artifact storage primitives for RepoForge."""

from .envelope import ArtifactEnvelope, ArtifactRef
from .freshness import FreshnessView, StaleArtifactError
from .registry import ArtifactContract, ArtifactRegistryError, ArtifactTypeRegistry
from .store import ArtifactStore, ArtifactStoreError, ArtifactWriteResult

__all__ = [
    "ArtifactContract",
    "ArtifactEnvelope",
    "ArtifactRef",
    "ArtifactRegistryError",
    "ArtifactStore",
    "ArtifactStoreError",
    "ArtifactWriteResult",
    "ArtifactTypeRegistry",
    "FreshnessView",
    "StaleArtifactError",
]
