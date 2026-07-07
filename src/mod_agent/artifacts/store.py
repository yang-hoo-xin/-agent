"""Filesystem-backed artifact store with Phase B artifact contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .envelope import ArtifactEnvelope, ArtifactRef
from .freshness import FreshnessView, StaleArtifactError
from .registry import ArtifactContract, ArtifactRegistryError, ArtifactTypeRegistry

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ARTIFACT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ENVELOPE_HASH_FIELDS = (
    "schema_version",
    "artifact_type",
    "feature_id",
    "producer_stage",
    "status",
    "data",
    "inputs",
    "blockers",
    "trace_refs",
)
_ENVELOPE_FIELDS = frozenset((*_ENVELOPE_HASH_FIELDS, "artifact_hash"))


class ArtifactStoreError(ValueError):
    """Raised when artifact storage validation fails."""


class ArtifactStore:
    """Write and read feature-scoped artifacts through one guarded interface."""

    def __init__(
        self,
        root: str | Path = "artifacts",
        registry: ArtifactTypeRegistry | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.registry = registry or ArtifactTypeRegistry()

    def write(
        self,
        *,
        feature_id: str,
        artifact_type: str,
        payload: Mapping[str, Any],
        status: str = "success",
        blockers: list[dict[str, Any]] | None = None,
        trace_refs: list[str] | None = None,
        upstream_refs: list[ArtifactRef] | None = None,
        allow_stale_upstreams: bool = False,
    ) -> ArtifactRef:
        """Wrap payload in an envelope and write it to disk."""

        self._validate_feature_id(feature_id)
        self._validate_artifact_type(artifact_type)
        data = dict(payload)
        try:
            contract = self.registry.validate_write(
                artifact_type=artifact_type,
                status=status,
                payload=data,
            )
        except ArtifactRegistryError as exc:
            raise ArtifactStoreError(str(exc)) from exc
        upstream_refs = list(upstream_refs or [])
        self._validate_upstream_refs(
            feature_id=feature_id,
            artifact_type=artifact_type,
            contract=contract,
            upstream_refs=upstream_refs,
            allow_stale_upstreams=allow_stale_upstreams,
        )
        inputs = {
            "upstream_artifacts": [
                {
                    "artifact_type": upstream.artifact_type,
                    "path": upstream.path,
                    "artifact_hash": upstream.artifact_hash,
                }
                for upstream in (upstream_refs or [])
            ]
        }
        envelope_content = {
            "schema_version": contract.schema_version,
            "artifact_type": artifact_type,
            "feature_id": feature_id,
            "producer_stage": contract.producer_stage,
            "status": status,
            "data": data,
            "inputs": inputs,
            "blockers": blockers or [],
            "trace_refs": trace_refs or [],
        }
        artifact_hash = self._stable_hash(self._envelope_content_for_hash(envelope_content))
        envelope = ArtifactEnvelope(
            schema_version=contract.schema_version,
            artifact_type=artifact_type,
            feature_id=feature_id,
            producer_stage=contract.producer_stage,
            status=status,
            data=data,
            artifact_hash=artifact_hash,
            inputs=inputs,
            blockers=blockers or [],
            trace_refs=trace_refs or [],
        )

        serialized_envelope = (
            json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        revision_path = self._revision_artifact_path(
            feature_id,
            artifact_type,
            artifact_hash,
        )
        self._write_text_atomic(revision_path, serialized_envelope)
        latest_path = self._artifact_path(feature_id, artifact_type)
        self._write_text_atomic(latest_path, serialized_envelope)
        return ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=str(revision_path),
            artifact_hash=artifact_hash,
        )

    def read(self, ref: ArtifactRef) -> dict[str, Any]:
        """Read an artifact envelope from a guarded artifact reference."""

        path = self._guard_path(Path(ref.path))
        if not path.exists():
            raise ArtifactStoreError(f"Artifact does not exist: {ref.path}")
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("artifact_hash") != ref.artifact_hash:
            raise ArtifactStoreError("Artifact hash mismatch")
        self._validate_envelope_fields(envelope)
        try:
            self.registry.validate_envelope(envelope)
        except ArtifactRegistryError as exc:
            raise ArtifactStoreError(str(exc)) from exc
        content_hash = self._stable_hash(self._envelope_content_for_hash(envelope))
        if content_hash != envelope["artifact_hash"]:
            raise ArtifactStoreError("Artifact content hash mismatch")
        return envelope

    def check_freshness(self, ref: ArtifactRef) -> FreshnessView:
        """Check whether an artifact's upstream hashes still match."""

        return self._check_freshness(ref, recursive=True)

    def check_direct_freshness(self, ref: ArtifactRef) -> FreshnessView:
        """Check only direct upstream hashes for write-time and checkpoint gates."""

        return self._check_freshness(ref, recursive=False)

    def _check_freshness(self, ref: ArtifactRef, *, recursive: bool) -> FreshnessView:
        envelope = self.read(ref)
        stale_reasons: list[str] = []
        seen = {(str(self._guard_path(Path(ref.path))), ref.artifact_hash)}
        self._collect_stale_reasons(envelope, stale_reasons, seen, recursive=recursive)
        if stale_reasons:
            return FreshnessView(status="stale", stale_reasons=stale_reasons)
        return FreshnessView(status="fresh", stale_reasons=[])

    def _collect_stale_reasons(
        self,
        envelope: Mapping[str, Any],
        stale_reasons: list[str],
        seen: set[tuple[str, str]],
        *,
        recursive: bool,
    ) -> None:
        for upstream in envelope.get("inputs", {}).get("upstream_artifacts", []):
            upstream_ref = ArtifactRef(
                feature_id=envelope["feature_id"],
                artifact_type=upstream["artifact_type"],
                path=upstream["path"],
                artifact_hash=upstream["artifact_hash"],
            )
            upstream_path = self._guard_path(Path(upstream_ref.path))
            if not upstream_path.exists():
                self._append_stale_reason(
                    stale_reasons,
                    f"{upstream_ref.artifact_type} missing at {upstream_ref.path}",
                )
                continue

            try:
                upstream_envelope = self.read(upstream_ref)
            except ArtifactStoreError as exc:
                reason = (
                    f"{upstream_ref.artifact_type} hash changed"
                    if str(exc) == "Artifact hash mismatch"
                    else f"{upstream_ref.artifact_type} invalid: {exc}"
                )
                self._append_stale_reason(stale_reasons, reason)
                continue
            try:
                latest_hash = self._latest_artifact_hash(
                    upstream_ref.feature_id,
                    upstream_ref.artifact_type,
                )
            except ArtifactStoreError as exc:
                self._append_stale_reason(
                    stale_reasons,
                    f"{upstream_ref.artifact_type} latest invalid: {exc}",
                )
                continue
            if latest_hash is not None and latest_hash != upstream_ref.artifact_hash:
                self._append_stale_reason(
                    stale_reasons,
                    f"{upstream_ref.artifact_type} hash changed",
                )
                continue

            upstream_key = (str(upstream_path), upstream_ref.artifact_hash)
            if upstream_key in seen:
                continue
            seen.add(upstream_key)
            if recursive:
                self._collect_stale_reasons(
                    upstream_envelope,
                    stale_reasons,
                    seen,
                    recursive=recursive,
                )

    def read_for_stage(self, ref: ArtifactRef, *, consumer_stage: str) -> dict[str, Any]:
        """Read an artifact for a registered consumer, blocking stale inputs."""

        try:
            self.registry.validate_consumer(ref.artifact_type, consumer_stage)
        except ArtifactRegistryError as exc:
            raise ArtifactStoreError(str(exc)) from exc
        freshness = self.check_freshness(ref)
        if not freshness.is_fresh:
            raise StaleArtifactError("; ".join(freshness.stale_reasons))
        return self.read(ref)

    def list_feature_artifacts(self, feature_id: str) -> list[ArtifactRef]:
        """List all artifacts for a feature."""

        self._validate_feature_id(feature_id)
        feature_dir = self._guard_path(self.root / "features" / feature_id)
        if not feature_dir.exists():
            return []

        refs: list[ArtifactRef] = []
        for path in sorted(feature_dir.glob("*.json")):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            refs.append(
                ArtifactRef(
                    feature_id=envelope["feature_id"],
                    artifact_type=envelope["artifact_type"],
                    path=str(path),
                    artifact_hash=envelope["artifact_hash"],
                )
            )
        return refs

    def list_feature_ids(self) -> list[str]:
        """List feature ids with artifact directories."""

        features_dir = self._guard_path(self.root / "features")
        if not features_dir.exists():
            return []
        return sorted(path.name for path in features_dir.iterdir() if path.is_dir())

    def exists(self, ref: ArtifactRef) -> bool:
        """Return whether a guarded artifact reference exists."""

        try:
            return self._guard_path(Path(ref.path)).exists()
        except ArtifactStoreError:
            return False

    def _artifact_path(self, feature_id: str, artifact_type: str) -> Path:
        return self._guard_path(
            self.root / "features" / feature_id / f"{artifact_type}.json"
        )

    def _revision_artifact_path(
        self,
        feature_id: str,
        artifact_type: str,
        artifact_hash: str,
    ) -> Path:
        return self._guard_path(
            self.root
            / "features"
            / feature_id
            / "revisions"
            / artifact_type
            / f"{artifact_hash}.json"
        )

    def _latest_artifact_hash(self, feature_id: str, artifact_type: str) -> str | None:
        latest_path = self._artifact_path(feature_id, artifact_type)
        if not latest_path.exists():
            return None
        envelope = json.loads(latest_path.read_text(encoding="utf-8"))
        artifact_hash = envelope.get("artifact_hash")
        if not isinstance(artifact_hash, str):
            raise ArtifactStoreError("Latest artifact envelope missing artifact_hash")
        latest_ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=str(latest_path),
            artifact_hash=artifact_hash,
        )
        return str(self.read(latest_ref)["artifact_hash"])

    def _write_text_atomic(self, path: Path, content: str) -> None:
        guarded_path = self._guard_path(path)
        guarded_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._guard_path(
            guarded_path.with_name(f".tmp-{uuid4().hex[:12]}.json")
        )
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, guarded_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _validate_upstream_refs(
        self,
        *,
        feature_id: str,
        artifact_type: str,
        contract: ArtifactContract,
        upstream_refs: list[ArtifactRef],
        allow_stale_upstreams: bool,
    ) -> None:
        provided_types = {ref.artifact_type for ref in upstream_refs}
        missing = sorted(contract.required_upstream_artifacts - provided_types)
        if missing:
            raise ArtifactStoreError(
                f"Artifact {artifact_type!r} missing required upstream artifacts: {missing}"
            )

        for upstream in upstream_refs:
            if upstream.feature_id != feature_id:
                raise ArtifactStoreError(
                    f"Upstream artifact feature_id mismatch for {upstream.artifact_type!r}"
                )

            envelope = self.read(upstream)
            if envelope.get("feature_id") != feature_id:
                raise ArtifactStoreError(
                    f"Upstream artifact feature_id mismatch for {upstream.artifact_type!r}"
                )
            if envelope.get("artifact_type") != upstream.artifact_type:
                raise ArtifactStoreError(
                    f"Upstream artifact_type mismatch for {upstream.artifact_type!r}"
                )

            freshness = self.check_direct_freshness(upstream)
            if not freshness.is_fresh and not allow_stale_upstreams:
                raise StaleArtifactError("; ".join(freshness.stale_reasons))

    def _guard_path(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactStoreError("Artifact path cannot escape artifact root") from exc
        return resolved

    @staticmethod
    def _stable_hash(value: Mapping[str, Any]) -> str:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _envelope_content_for_hash(envelope: Mapping[str, Any]) -> dict[str, Any]:
        return {field: envelope[field] for field in _ENVELOPE_HASH_FIELDS}

    @staticmethod
    def _validate_envelope_fields(envelope: Mapping[str, Any]) -> None:
        fields = set(envelope)
        missing = sorted(_ENVELOPE_FIELDS - fields)
        if missing:
            raise ArtifactStoreError(f"Artifact envelope missing fields: {missing}")
        unexpected = sorted(fields - _ENVELOPE_FIELDS)
        if unexpected:
            raise ArtifactStoreError(f"Artifact envelope unexpected fields: {unexpected}")

    @staticmethod
    def _append_stale_reason(stale_reasons: list[str], reason: str) -> None:
        if reason not in stale_reasons:
            stale_reasons.append(reason)

    @staticmethod
    def _validate_feature_id(feature_id: str) -> None:
        if not _SEGMENT_RE.match(feature_id) or ".." in feature_id:
            raise ArtifactStoreError(f"Invalid feature_id: {feature_id!r}")

    @staticmethod
    def _validate_artifact_type(artifact_type: str) -> None:
        if not _ARTIFACT_TYPE_RE.match(artifact_type):
            raise ArtifactStoreError(f"Invalid artifact_type: {artifact_type!r}")
