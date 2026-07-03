"""Artifact storage primitives for the Controlled Mod Agent platform."""

from .envelope import ArtifactEnvelope, ArtifactRef
from .freshness import FreshnessView, StaleArtifactError
from .registry import ArtifactContract, ArtifactRegistryError, ArtifactTypeRegistry
from .store import ArtifactStore, ArtifactStoreError

__all__ = [
    "ArtifactContract",
    "ArtifactEnvelope",
    "ArtifactRef",
    "ArtifactRegistryError",
    "ArtifactStore",
    "ArtifactStoreError",
    "ArtifactTypeRegistry",
    "FreshnessView",
    "StaleArtifactError",
]
