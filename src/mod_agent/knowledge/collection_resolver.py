"""Collection resolution for controlled-agent retrieval paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.core.settings import Settings, SettingsError, load_settings


class CollectionResolutionError(ValueError):
    """Raised when a controlled-agent collection cannot be resolved."""


@dataclass(frozen=True)
class CollectionResolution:
    """Resolved collection id and its source."""

    collection_id: str
    source: str


class CollectionResolver:
    """Resolve the collection used by controlled-agent retrieval."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        settings_path: str | Path | None = None,
    ) -> None:
        self._settings = settings
        self._settings_path = settings_path

    def resolve(self, explicit_collection_id: str | None = None) -> CollectionResolution:
        """Return the explicit collection or the configured default collection."""

        if explicit_collection_id is not None:
            collection_id = explicit_collection_id.strip()
            if not collection_id:
                raise CollectionResolutionError(
                    "Explicit collection id cannot be empty."
                )
            return CollectionResolution(collection_id=collection_id, source="explicit")

        settings = self._load_settings()
        collection_id = settings.vector_store.collection_name.strip()
        if not collection_id:
            raise CollectionResolutionError(
                "Missing required field: vector_store.collection_name"
            )
        return CollectionResolution(collection_id=collection_id, source="settings")

    def _load_settings(self) -> Settings:
        if self._settings is not None:
            return self._settings
        try:
            return load_settings(self._settings_path)
        except SettingsError as exc:
            raise CollectionResolutionError(str(exc)) from exc
