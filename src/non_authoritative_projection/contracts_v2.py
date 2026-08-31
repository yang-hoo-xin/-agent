"""Occurrence-aware contracts for a non-authoritative owner projection.

The module keeps ProductExecution occurrences distinct from the ArtifactStore
revisions they reference.  It has no product, workflow, Store, UI, telemetry,
or execution dependency and carries no owner payload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from src.non_authoritative_projection.contracts import ProjectionContractError


PROJECTION_SCHEMA_VERSION_V2 = "2"
OWNER_FACT_ADMISSION_VERSION_V2 = "owner_fact_admission_v2"

OwnerScopeModeV2 = Literal["product_execution_result", "unavailable"]
OwnerSequenceModeV2 = Literal["required", "unavailable"]

# Exact field order: owner, fact_type, payload_schema_version, scope_mode,
# owner_sequence_mode.  This is closed admission; callers cannot extend it.
_OWNER_FACT_ADMISSION_V2: tuple[
    tuple[str, str, str, OwnerScopeModeV2, OwnerSequenceModeV2], ...
] = (
    (
        "artifact_store",
        "artifact_revision_v1",
        "1.0",
        "unavailable",
        "unavailable",
    ),
    (
        "product_execution",
        "product_execution_output_v1",
        "1.0",
        "product_execution_result",
        "required",
    ),
)
OWNER_FACT_ADMISSION_V2 = _OWNER_FACT_ADMISSION_V2

RelationV2 = Literal[
    "references",
    "derived_from",
    "caused_by",
    "conflicts_with",
]

RELATIONS_V2: tuple[RelationV2, ...] = (
    "references",
    "derived_from",
    "caused_by",
    "conflicts_with",
)

RELATION_DIRECTIONS_V2: tuple[tuple[RelationV2, str], ...] = (
    (
        "references",
        "source is the reporter occurrence explicitly signing source -> target as a reference",
    ),
    (
        "derived_from",
        "source is the reporter occurrence explicitly signing source as derived from target",
    ),
    (
        "caused_by",
        "source is the reporter occurrence explicitly signing source as caused by target",
    ),
    (
        "conflicts_with",
        "source is the reporter occurrence explicitly signing a conflict with target; direction conveys no priority",
    ),
)

DiagnosticCodeV2 = Literal[
    "missing_source_fact",
    "missing_target_fact",
    "missing_reporter_fact",
    "reporter_payload_sha256_mismatch",
    "reporter_owner_sequence_mismatch",
    "explicit_conflict",
]

DIAGNOSTIC_CODES_V2: tuple[DiagnosticCodeV2, ...] = (
    "missing_source_fact",
    "missing_target_fact",
    "missing_reporter_fact",
    "reporter_payload_sha256_mismatch",
    "reporter_owner_sequence_mismatch",
    "explicit_conflict",
)


def _owner_fact_admission(
    owner: str,
    fact_type: str,
) -> tuple[str, OwnerScopeModeV2, OwnerSequenceModeV2] | None:
    for (
        admitted_owner,
        admitted_type,
        payload_schema,
        scope_mode,
        sequence_mode,
    ) in _OWNER_FACT_ADMISSION_V2:
        if (owner, fact_type) == (admitted_owner, admitted_type):
            return payload_schema, scope_mode, sequence_mode
    return None


def _require_exact_fields(
    value: Mapping[str, Any], fields: tuple[str, ...], name: str
) -> None:
    if not isinstance(value, Mapping) or tuple(value) != fields:
        raise ProjectionContractError(f"{name} fields or field order changed.")


def _require_text(value: Any, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ProjectionContractError(f"{name} must be an exact non-empty string.")
    return value


def _require_sha256(value: Any, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ProjectionContractError(
            f"{name} must be exactly 64 lowercase hexadecimal characters."
        )
    return value


def _require_sequence(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ProjectionContractError(f"{name} must be an exact integer >= 0.")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProjectionContractError(
            "Projection V2 value is not canonical JSON."
        ) from exc


@dataclass(frozen=True, slots=True)
class ArtifactRefV2:
    """Exact structured copy of an owner-issued ArtifactRef identity."""

    feature_id: str
    artifact_type: str
    path: str
    artifact_hash: str

    def __post_init__(self) -> None:
        _require_text(self.feature_id, "ArtifactRefV2.feature_id")
        _require_text(self.artifact_type, "ArtifactRefV2.artifact_type")
        _require_text(self.path, "ArtifactRefV2.path")
        _require_sha256(self.artifact_hash, "ArtifactRefV2.artifact_hash")

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "artifact_type": self.artifact_type,
            "path": self.path,
            "artifact_hash": self.artifact_hash,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArtifactRefV2":
        _require_exact_fields(
            value,
            ("feature_id", "artifact_type", "path", "artifact_hash"),
            "ArtifactRefV2",
        )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class FactRefV2:
    """Complete endpoint identity for one owner fact or owner occurrence."""

    owner: str
    fact_type: str
    run_id: str | None
    request_id: str | None
    owner_sequence: int | None
    artifact_ref: ArtifactRefV2

    def __post_init__(self) -> None:
        admission = _owner_fact_admission(self.owner, self.fact_type)
        if admission is None:
            raise ProjectionContractError(
                "FactRefV2 owner plus fact_type pair is not admitted."
            )
        if not isinstance(self.artifact_ref, ArtifactRefV2):
            raise ProjectionContractError(
                "FactRefV2.artifact_ref must be ArtifactRefV2."
            )
        _payload_schema, scope_mode, sequence_mode = admission
        if scope_mode == "product_execution_result":
            _require_text(self.run_id, "FactRefV2.run_id")
            _require_text(self.request_id, "FactRefV2.request_id")
        elif self.run_id is not None or self.request_id is not None:
            raise ProjectionContractError(
                "FactRefV2 run and request scope must be null for this admission."
            )
        if sequence_mode == "required":
            _require_sequence(self.owner_sequence, "FactRefV2.owner_sequence")
        elif self.owner_sequence is not None:
            raise ProjectionContractError(
                "FactRefV2 owner sequence must be null for this admission."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "fact_type": self.fact_type,
            "run_id": self.run_id,
            "request_id": self.request_id,
            "owner_sequence": self.owner_sequence,
            "artifact_ref": self.artifact_ref.to_dict(),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactRefV2":
        _require_exact_fields(
            value,
            (
                "owner",
                "fact_type",
                "run_id",
                "request_id",
                "owner_sequence",
                "artifact_ref",
            ),
            "FactRefV2",
        )
        return cls(
            owner=value["owner"],
            fact_type=value["fact_type"],
            run_id=value["run_id"],
            request_id=value["request_id"],
            owner_sequence=value["owner_sequence"],
            artifact_ref=ArtifactRefV2.from_dict(value["artifact_ref"]),
        )


@dataclass(frozen=True, slots=True)
class OwnerFactV2:
    schema_version: Literal["2"]
    fact: FactRefV2
    payload_sha256: str
    payload_schema_version: str

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V2:
            raise ProjectionContractError("OwnerFactV2 schema version is unsupported.")
        if not isinstance(self.fact, FactRefV2):
            raise ProjectionContractError("OwnerFactV2.fact must be FactRefV2.")
        admission = _owner_fact_admission(self.fact.owner, self.fact.fact_type)
        if admission is None:
            raise ProjectionContractError(
                "OwnerFactV2 owner plus fact_type pair is not admitted."
            )
        expected_payload_schema, _scope_mode, _sequence_mode = admission
        if self.payload_schema_version != expected_payload_schema:
            raise ProjectionContractError(
                "OwnerFactV2 payload schema version does not match its admission."
            )
        _require_sha256(self.payload_sha256, "OwnerFactV2.payload_sha256")
        if self.payload_sha256 != self.fact.artifact_ref.artifact_hash:
            raise ProjectionContractError(
                "OwnerFactV2 payload hash must equal its exact ArtifactRef hash."
            )

    @property
    def ref(self) -> FactRefV2:
        return self.fact

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fact": self.fact.to_dict(),
            "payload_sha256": self.payload_sha256,
            "payload_schema_version": self.payload_schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OwnerFactV2":
        _require_exact_fields(
            value,
            (
                "schema_version",
                "fact",
                "payload_sha256",
                "payload_schema_version",
            ),
            "OwnerFactV2",
        )
        return cls(
            schema_version=value["schema_version"],
            fact=FactRefV2.from_dict(value["fact"]),
            payload_sha256=value["payload_sha256"],
            payload_schema_version=value["payload_schema_version"],
        )


@dataclass(frozen=True, slots=True)
class EdgeReporterV2:
    fact: FactRefV2
    payload_sha256: str
    owner_sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.fact, FactRefV2):
            raise ProjectionContractError("EdgeReporterV2.fact must be FactRefV2.")
        admission = _owner_fact_admission(self.fact.owner, self.fact.fact_type)
        if (
            admission is None
            or admission[2] != "required"
            or self.fact.owner_sequence is None
        ):
            raise ProjectionContractError(
                "EdgeReporterV2 fact cannot report without an owner sequence."
            )
        _require_sha256(self.payload_sha256, "EdgeReporterV2.payload_sha256")
        _require_sequence(self.owner_sequence, "EdgeReporterV2.owner_sequence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact": self.fact.to_dict(),
            "payload_sha256": self.payload_sha256,
            "owner_sequence": self.owner_sequence,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EdgeReporterV2":
        _require_exact_fields(
            value,
            ("fact", "payload_sha256", "owner_sequence"),
            "EdgeReporterV2",
        )
        return cls(
            fact=FactRefV2.from_dict(value["fact"]),
            payload_sha256=value["payload_sha256"],
            owner_sequence=value["owner_sequence"],
        )


@dataclass(frozen=True, slots=True)
class ExplicitEdgeV2:
    schema_version: Literal["2"]
    relation: RelationV2
    source: FactRefV2
    target: FactRefV2
    reporter: EdgeReporterV2

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V2:
            raise ProjectionContractError(
                "ExplicitEdgeV2 schema version is unsupported."
            )
        if self.relation not in RELATIONS_V2:
            raise ProjectionContractError("ExplicitEdgeV2 relation is unsupported.")
        if not isinstance(self.source, FactRefV2) or not isinstance(
            self.target, FactRefV2
        ):
            raise ProjectionContractError(
                "ExplicitEdgeV2 endpoints must be FactRefV2."
            )
        if not isinstance(self.reporter, EdgeReporterV2):
            raise ProjectionContractError(
                "ExplicitEdgeV2 reporter must be EdgeReporterV2."
            )
        if self.reporter.fact != self.source:
            raise ProjectionContractError(
                "ExplicitEdgeV2 reporter fact must equal its source endpoint."
            )
        admission = _owner_fact_admission(
            self.source.owner,
            self.source.fact_type,
        )
        if admission is None or admission[2] != "required":
            raise ProjectionContractError(
                "ExplicitEdgeV2 source fact cannot issue a sequence-bound edge."
            )
        if self.relation == "conflicts_with" and self.source == self.target:
            raise ProjectionContractError(
                "ExplicitEdgeV2 conflicts_with endpoints must be distinct."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "relation": self.relation,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "reporter": self.reporter.to_dict(),
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def canonical_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExplicitEdgeV2":
        _require_exact_fields(
            value,
            ("schema_version", "relation", "source", "target", "reporter"),
            "ExplicitEdgeV2",
        )
        return cls(
            schema_version=value["schema_version"],
            relation=value["relation"],
            source=FactRefV2.from_dict(value["source"]),
            target=FactRefV2.from_dict(value["target"]),
            reporter=EdgeReporterV2.from_dict(value["reporter"]),
        )


@dataclass(frozen=True, slots=True)
class ProjectionDiagnosticV2:
    schema_version: Literal["2"]
    code: DiagnosticCodeV2
    edge_sha256: str
    primary_fact: FactRefV2
    related_fact: FactRefV2 | None
    fact_payload_sha256: str | None
    reporter_payload_sha256: str | None
    fact_owner_sequence: int | None
    reporter_owner_sequence: int | None

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V2:
            raise ProjectionContractError(
                "ProjectionDiagnosticV2 schema version is unsupported."
            )
        if self.code not in DIAGNOSTIC_CODES_V2:
            raise ProjectionContractError(
                "ProjectionDiagnosticV2 code is unsupported."
            )
        _require_sha256(self.edge_sha256, "ProjectionDiagnosticV2.edge_sha256")
        if not isinstance(self.primary_fact, FactRefV2):
            raise ProjectionContractError(
                "ProjectionDiagnosticV2.primary_fact must be FactRefV2."
            )
        if self.related_fact is not None and not isinstance(
            self.related_fact, FactRefV2
        ):
            raise ProjectionContractError(
                "ProjectionDiagnosticV2.related_fact must be FactRefV2 or null."
            )
        self._validate_code_shape()

    def _validate_code_shape(self) -> None:
        missing_codes = {
            "missing_source_fact",
            "missing_target_fact",
            "missing_reporter_fact",
        }
        comparisons = (
            self.fact_payload_sha256,
            self.reporter_payload_sha256,
            self.fact_owner_sequence,
            self.reporter_owner_sequence,
        )
        if self.code in missing_codes:
            if self.related_fact is not None or any(
                item is not None for item in comparisons
            ):
                raise ProjectionContractError(
                    "Missing-fact V2 diagnostic carries unsupported comparison fields."
                )
            return
        if self.code == "explicit_conflict":
            if (
                self.related_fact is None
                or self.related_fact == self.primary_fact
                or any(item is not None for item in comparisons)
            ):
                raise ProjectionContractError(
                    "Explicit-conflict V2 diagnostic shape is invalid."
                )
            return
        if self.related_fact is not None:
            raise ProjectionContractError(
                "Reporter mismatch V2 diagnostic cannot carry related_fact."
            )
        if self.code == "reporter_payload_sha256_mismatch":
            _require_sha256(
                self.fact_payload_sha256,
                "ProjectionDiagnosticV2.fact_payload_sha256",
            )
            _require_sha256(
                self.reporter_payload_sha256,
                "ProjectionDiagnosticV2.reporter_payload_sha256",
            )
            if (
                self.fact_payload_sha256 == self.reporter_payload_sha256
                or self.fact_owner_sequence is not None
                or self.reporter_owner_sequence is not None
            ):
                raise ProjectionContractError(
                    "Reporter payload V2 mismatch diagnostic shape is invalid."
                )
            return
        if self.code == "reporter_owner_sequence_mismatch":
            _require_sequence(
                self.fact_owner_sequence,
                "ProjectionDiagnosticV2.fact_owner_sequence",
            )
            _require_sequence(
                self.reporter_owner_sequence,
                "ProjectionDiagnosticV2.reporter_owner_sequence",
            )
            if (
                self.fact_owner_sequence == self.reporter_owner_sequence
                or self.fact_payload_sha256 is not None
                or self.reporter_payload_sha256 is not None
            ):
                raise ProjectionContractError(
                    "Reporter sequence V2 mismatch diagnostic shape is invalid."
                )
            return
        raise ProjectionContractError("Projection V2 diagnostic code shape is invalid.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "code": self.code,
            "edge_sha256": self.edge_sha256,
            "primary_fact": self.primary_fact.to_dict(),
            "related_fact": (
                self.related_fact.to_dict() if self.related_fact is not None else None
            ),
            "fact_payload_sha256": self.fact_payload_sha256,
            "reporter_payload_sha256": self.reporter_payload_sha256,
            "fact_owner_sequence": self.fact_owner_sequence,
            "reporter_owner_sequence": self.reporter_owner_sequence,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectionDiagnosticV2":
        _require_exact_fields(
            value,
            (
                "schema_version",
                "code",
                "edge_sha256",
                "primary_fact",
                "related_fact",
                "fact_payload_sha256",
                "reporter_payload_sha256",
                "fact_owner_sequence",
                "reporter_owner_sequence",
            ),
            "ProjectionDiagnosticV2",
        )
        related = value["related_fact"]
        return cls(
            schema_version=value["schema_version"],
            code=value["code"],
            edge_sha256=value["edge_sha256"],
            primary_fact=FactRefV2.from_dict(value["primary_fact"]),
            related_fact=(
                FactRefV2.from_dict(related) if related is not None else None
            ),
            fact_payload_sha256=value["fact_payload_sha256"],
            reporter_payload_sha256=value["reporter_payload_sha256"],
            fact_owner_sequence=value["fact_owner_sequence"],
            reporter_owner_sequence=value["reporter_owner_sequence"],
        )


def _occurrence_slot(ref: FactRefV2) -> tuple[str, str, str, str, int] | None:
    admission = _owner_fact_admission(ref.owner, ref.fact_type)
    if admission is None or admission[1] != "product_execution_result":
        return None
    if (
        ref.run_id is None
        or ref.request_id is None
        or ref.owner_sequence is None
    ):
        raise ProjectionContractError(
            "ProductExecution V2 occurrence lacks its validated scope or sequence."
        )
    return (
        ref.owner,
        ref.fact_type,
        ref.run_id,
        ref.request_id,
        ref.owner_sequence,
    )


def _validate_occurrence_bindings(refs: Iterable[FactRefV2]) -> None:
    artifact_by_slot: dict[
        tuple[str, str, str, str, int], ArtifactRefV2
    ] = {}
    for ref in refs:
        slot = _occurrence_slot(ref)
        if slot is None:
            continue
        existing = artifact_by_slot.setdefault(slot, ref.artifact_ref)
        if existing != ref.artifact_ref:
            raise ProjectionContractError(
                "One ProductExecution V2 scope plus owner sequence maps to multiple Artifact identities."
            )


def _fact_sort_key(fact: OwnerFactV2) -> bytes:
    return fact.ref.canonical_bytes()


def _edge_sort_key(edge: ExplicitEdgeV2) -> bytes:
    return edge.canonical_bytes()


def _diagnostic_sort_key(diagnostic: ProjectionDiagnosticV2) -> bytes:
    return _canonical_json_bytes(diagnostic.to_dict())


def _validate_fact_collection(facts: tuple[OwnerFactV2, ...]) -> None:
    if any(not isinstance(fact, OwnerFactV2) for fact in facts):
        raise ProjectionContractError("Projection V2 facts must be OwnerFactV2 values.")
    refs = tuple(fact.ref for fact in facts)
    if len(set(refs)) != len(refs):
        raise ProjectionContractError(
            "Projection V2 facts contain a duplicate complete fact identity."
        )
    _validate_occurrence_bindings(refs)


def _validate_edge_collection(edges: tuple[ExplicitEdgeV2, ...]) -> None:
    if any(not isinstance(edge, ExplicitEdgeV2) for edge in edges):
        raise ProjectionContractError(
            "Projection V2 edges must be ExplicitEdgeV2 values."
        )
    identities = tuple(edge.canonical_bytes() for edge in edges)
    if len(set(identities)) != len(identities):
        raise ProjectionContractError("Projection V2 edges contain a duplicate edge.")
    _validate_occurrence_bindings(
        ref
        for edge in edges
        for ref in (edge.source, edge.target, edge.reporter.fact)
    )


def _validate_view_occurrence_bindings(
    facts: tuple[OwnerFactV2, ...],
    edges: tuple[ExplicitEdgeV2, ...],
) -> None:
    _validate_occurrence_bindings(
        (
            *(fact.ref for fact in facts),
            *(
                ref
                for edge in edges
                for ref in (edge.source, edge.target, edge.reporter.fact)
            ),
        )
    )


def _validate_diagnostic_collection(
    diagnostics: tuple[ProjectionDiagnosticV2, ...],
) -> None:
    if any(
        not isinstance(diagnostic, ProjectionDiagnosticV2)
        for diagnostic in diagnostics
    ):
        raise ProjectionContractError(
            "Projection V2 diagnostics must be ProjectionDiagnosticV2 values."
        )
    identities = tuple(_canonical_json_bytes(item.to_dict()) for item in diagnostics)
    if len(set(identities)) != len(identities):
        raise ProjectionContractError(
            "Projection V2 diagnostics contain a duplicate diagnostic."
        )


def _missing_diagnostic(
    code: DiagnosticCodeV2,
    edge: ExplicitEdgeV2,
    fact: FactRefV2,
) -> ProjectionDiagnosticV2:
    return ProjectionDiagnosticV2(
        schema_version="2",
        code=code,
        edge_sha256=edge.canonical_sha256(),
        primary_fact=fact,
        related_fact=None,
        fact_payload_sha256=None,
        reporter_payload_sha256=None,
        fact_owner_sequence=None,
        reporter_owner_sequence=None,
    )


def _derive_diagnostics(
    facts: tuple[OwnerFactV2, ...],
    edges: tuple[ExplicitEdgeV2, ...],
) -> tuple[ProjectionDiagnosticV2, ...]:
    fact_by_ref = {fact.ref: fact for fact in facts}
    diagnostics: list[ProjectionDiagnosticV2] = []
    for edge in edges:
        source_exists = edge.source in fact_by_ref
        target_exists = edge.target in fact_by_ref
        if not source_exists:
            diagnostics.append(
                _missing_diagnostic("missing_source_fact", edge, edge.source)
            )
        if not target_exists:
            diagnostics.append(
                _missing_diagnostic("missing_target_fact", edge, edge.target)
            )

        reporter_fact = fact_by_ref.get(edge.reporter.fact)
        reporter_matches = reporter_fact is not None
        if reporter_fact is None:
            diagnostics.append(
                _missing_diagnostic(
                    "missing_reporter_fact",
                    edge,
                    edge.reporter.fact,
                )
            )
        else:
            if reporter_fact.payload_sha256 != edge.reporter.payload_sha256:
                reporter_matches = False
                diagnostics.append(
                    ProjectionDiagnosticV2(
                        schema_version="2",
                        code="reporter_payload_sha256_mismatch",
                        edge_sha256=edge.canonical_sha256(),
                        primary_fact=edge.reporter.fact,
                        related_fact=None,
                        fact_payload_sha256=reporter_fact.payload_sha256,
                        reporter_payload_sha256=edge.reporter.payload_sha256,
                        fact_owner_sequence=None,
                        reporter_owner_sequence=None,
                    )
                )
            if reporter_fact.ref.owner_sequence != edge.reporter.owner_sequence:
                reporter_matches = False
                diagnostics.append(
                    ProjectionDiagnosticV2(
                        schema_version="2",
                        code="reporter_owner_sequence_mismatch",
                        edge_sha256=edge.canonical_sha256(),
                        primary_fact=edge.reporter.fact,
                        related_fact=None,
                        fact_payload_sha256=None,
                        reporter_payload_sha256=None,
                        fact_owner_sequence=reporter_fact.ref.owner_sequence,
                        reporter_owner_sequence=edge.reporter.owner_sequence,
                    )
                )

        if (
            edge.relation == "conflicts_with"
            and source_exists
            and target_exists
            and reporter_matches
        ):
            diagnostics.append(
                ProjectionDiagnosticV2(
                    schema_version="2",
                    code="explicit_conflict",
                    edge_sha256=edge.canonical_sha256(),
                    primary_fact=edge.source,
                    related_fact=edge.target,
                    fact_payload_sha256=None,
                    reporter_payload_sha256=None,
                    fact_owner_sequence=None,
                    reporter_owner_sequence=None,
                )
            )
    return tuple(sorted(diagnostics, key=_diagnostic_sort_key))


@dataclass(frozen=True, slots=True)
class ProjectionViewV2:
    schema_version: Literal["2"]
    facts: tuple[OwnerFactV2, ...]
    edges: tuple[ExplicitEdgeV2, ...]
    diagnostics: tuple[ProjectionDiagnosticV2, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V2:
            raise ProjectionContractError(
                "ProjectionViewV2 schema version is unsupported."
            )
        if type(self.facts) is not tuple or type(self.edges) is not tuple:
            raise ProjectionContractError(
                "ProjectionViewV2 facts and edges must be exact tuples."
            )
        if type(self.diagnostics) is not tuple:
            raise ProjectionContractError(
                "ProjectionViewV2 diagnostics must be an exact tuple."
            )
        _validate_fact_collection(self.facts)
        _validate_edge_collection(self.edges)
        _validate_view_occurrence_bindings(self.facts, self.edges)
        _validate_diagnostic_collection(self.diagnostics)
        if self.facts != tuple(sorted(self.facts, key=_fact_sort_key)):
            raise ProjectionContractError(
                "ProjectionViewV2 fact serialization order is non-canonical."
            )
        if self.edges != tuple(sorted(self.edges, key=_edge_sort_key)):
            raise ProjectionContractError(
                "ProjectionViewV2 edge serialization order is non-canonical."
            )
        expected = _derive_diagnostics(self.facts, self.edges)
        if self.diagnostics != expected:
            raise ProjectionContractError(
                "ProjectionViewV2 diagnostics do not exactly match its complete inputs."
            )

    @classmethod
    def rebuild(
        cls,
        facts: Iterable[OwnerFactV2],
        edges: Iterable[ExplicitEdgeV2],
    ) -> "ProjectionViewV2":
        selected_facts = tuple(facts)
        selected_edges = tuple(edges)
        _validate_fact_collection(selected_facts)
        _validate_edge_collection(selected_edges)
        _validate_view_occurrence_bindings(selected_facts, selected_edges)
        ordered_facts = tuple(sorted(selected_facts, key=_fact_sort_key))
        ordered_edges = tuple(sorted(selected_edges, key=_edge_sort_key))
        return cls(
            schema_version="2",
            facts=ordered_facts,
            edges=ordered_edges,
            diagnostics=_derive_diagnostics(ordered_facts, ordered_edges),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "facts": [fact.to_dict() for fact in self.facts],
            "edges": [edge.to_dict() for edge in self.edges],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    def canonical_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectionViewV2":
        _require_exact_fields(
            value,
            ("schema_version", "facts", "edges", "diagnostics"),
            "ProjectionViewV2",
        )
        for field in ("facts", "edges", "diagnostics"):
            if type(value[field]) is not list:
                raise ProjectionContractError(
                    f"ProjectionViewV2.{field} must serialize as an array."
                )
        return cls(
            schema_version=value["schema_version"],
            facts=tuple(OwnerFactV2.from_dict(item) for item in value["facts"]),
            edges=tuple(ExplicitEdgeV2.from_dict(item) for item in value["edges"]),
            diagnostics=tuple(
                ProjectionDiagnosticV2.from_dict(item)
                for item in value["diagnostics"]
            ),
        )
