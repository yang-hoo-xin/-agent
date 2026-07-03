"""Freshness checks for artifact dependency hashes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FreshnessView:
    """Freshness status for an artifact read."""

    status: str
    stale_reasons: list[str]

    @property
    def is_fresh(self) -> bool:
        """Return whether the artifact is fresh."""

        return self.status == "fresh"


class StaleArtifactError(ValueError):
    """Raised when a stale artifact is used by a strict consumer."""

