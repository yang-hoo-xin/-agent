"""Source registration and guarded file discovery for Knowledge Base indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .database import KnowledgeDatabase
from .models import SourceRecord
from .source_discovery import (
    DEFAULT_IGNORED_DIR_NAMES,
    DEFAULT_IGNORED_FILE_PATTERNS,
    aggregate_source_hash,
    iter_indexable_paths,
    normalize_extensions,
)

DEFAULT_EXTENSIONS = frozenset({".cs", ".py", ".json", ".yaml", ".yml", ".md", ".txt", ".log"})


class SourceRegistryError(ValueError):
    """Raised when a source root cannot be registered or scanned safely."""


@dataclass(frozen=True)
class SourceDefinition:
    """Input contract for a registered knowledge source."""

    source_id: str
    source_type: str
    root_path: str | Path
    metadata: dict[str, Any] = field(default_factory=dict)
    allowed_extensions: frozenset[str] = DEFAULT_EXTENSIONS
    ignored_dir_names: frozenset[str] = DEFAULT_IGNORED_DIR_NAMES
    ignored_file_patterns: frozenset[str] = DEFAULT_IGNORED_FILE_PATTERNS
    include_generated_mods: bool = False


class SourceRegistry:
    """Register source roots and discover indexable files."""

    def __init__(self, database: KnowledgeDatabase) -> None:
        self.database = database
        self._definitions: dict[str, SourceDefinition] = {}

    def register(self, definition: SourceDefinition) -> SourceRecord:
        """Validate and persist a source definition."""

        self._validate_source_id(definition.source_id)
        self._validate_source_type(definition.source_type)
        root = Path(definition.root_path).resolve()
        if not root.exists():
            raise SourceRegistryError(f"Source root does not exist: {root}")
        if not root.is_dir():
            raise SourceRegistryError(f"Source root is not a directory: {root}")
        normalized_extensions = normalize_extensions(definition.allowed_extensions)
        stored = SourceDefinition(
            source_id=definition.source_id,
            source_type=definition.source_type,
            root_path=root,
            metadata=dict(definition.metadata),
            allowed_extensions=normalized_extensions,
            ignored_dir_names=frozenset(definition.ignored_dir_names),
            ignored_file_patterns=frozenset(definition.ignored_file_patterns),
            include_generated_mods=definition.include_generated_mods,
        )
        self._definitions[definition.source_id] = stored
        record = SourceRecord(
            source_id=definition.source_id,
            source_type=definition.source_type,
            root_path=str(root),
            metadata={
                **definition.metadata,
                "allowed_extensions": sorted(normalized_extensions),
                "ignored_dir_names": sorted(definition.ignored_dir_names),
                "ignored_file_patterns": sorted(definition.ignored_file_patterns),
                "include_generated_mods": definition.include_generated_mods,
            },
        )
        self.database.upsert_source(record)
        return record

    def list_sources(self) -> list[SourceRecord]:
        """Return all persisted source records."""

        return self.database.list_sources()

    def iter_files(self, source_id: str) -> list[Path]:
        """Return indexable files for a registered source."""

        definition = self._definition_for(source_id)
        root = Path(definition.root_path).resolve()
        return iter_indexable_paths(
            root=root,
            allowed_extensions=definition.allowed_extensions,
            ignored_dir_names=definition.ignored_dir_names,
            ignored_file_patterns=definition.ignored_file_patterns,
            include_generated_mods=definition.include_generated_mods,
        )

    def source_content_hash(self, source_id: str) -> str:
        """Return a stable aggregate hash for currently discovered files."""

        root = self.source_root(source_id)
        return aggregate_source_hash(self.iter_files(source_id), root=root)

    def source_root(self, source_id: str) -> Path:
        """Return the resolved root path for a registered source."""

        return Path(self._definition_for(source_id).root_path).resolve()

    def source_record(self, source_id: str) -> SourceRecord:
        """Return a persisted source record by id."""

        for source in self.database.list_sources():
            if source.source_id == source_id:
                return source
        raise SourceRegistryError(f"Unknown source_id: {source_id}")

    def _definition_for(self, source_id: str) -> SourceDefinition:
        if source_id in self._definitions:
            return self._definitions[source_id]
        for record in self.database.list_sources():
            if record.source_id == source_id:
                extensions = frozenset(record.metadata.get("allowed_extensions", DEFAULT_EXTENSIONS))
                ignored_dir_names = frozenset(
                    record.metadata.get("ignored_dir_names", DEFAULT_IGNORED_DIR_NAMES)
                )
                ignored_file_patterns = frozenset(
                    record.metadata.get("ignored_file_patterns", DEFAULT_IGNORED_FILE_PATTERNS)
                )
                definition = SourceDefinition(
                    source_id=record.source_id,
                    source_type=record.source_type,
                    root_path=record.root_path,
                    metadata=record.metadata,
                    allowed_extensions=normalize_extensions(extensions),
                    ignored_dir_names=ignored_dir_names,
                    ignored_file_patterns=ignored_file_patterns,
                    include_generated_mods=bool(record.metadata.get("include_generated_mods", False)),
                )
                self._definitions[source_id] = definition
                return definition
        raise SourceRegistryError(f"Unknown source_id: {source_id}")

    @staticmethod
    def _validate_source_id(source_id: str) -> None:
        if not source_id or any(char in source_id for char in ("\\", "/", "..")):
            raise SourceRegistryError(f"Invalid source_id: {source_id!r}")

    @staticmethod
    def _validate_source_type(source_type: str) -> None:
        allowed = {
            "target_source",
            "reference_mod",
            "decompiled_api",
            "domain_note",
            "prior_artifact",
            "build_log",
            "runtime_log",
            "manual_note",
            "screenshot",
        }
        if source_type not in allowed:
            raise SourceRegistryError(f"Unsupported source_type: {source_type!r}")
