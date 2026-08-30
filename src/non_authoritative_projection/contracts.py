"""Pure contracts for rebuilding a non-authoritative owner-fact projection.

The module deliberately contains no product, workflow, Store, UI, or telemetry
dependency.  It carries identities and hashes, never owner payload fields.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal


PROJECTION_SCHEMA_VERSION_V1 = "1"
OWNER_FACT_ADMISSION_VERSION_V1 = "owner_fact_admission_v1"

OwnerSequenceModeV1 = Literal["required", "unavailable"]

# Exact field order: owner, fact_type, payload_schema_version,
# owner_sequence_mode. This is a closed table; callers cannot extend it.
_OWNER_FACT_ADMISSION_V1: tuple[
    tuple[str, str, str, OwnerSequenceModeV1], ...
] = (
    ("artifact_store", "artifact_revision_v1", "1.0", "unavailable"),
    (
        "product_execution",
        "product_execution_output_v1",
        "1.0",
        "required",
    ),
)
OWNER_FACT_ADMISSION_V1 = _OWNER_FACT_ADMISSION_V1

RelationV1 = Literal[
    "references",
    "derived_from",
    "caused_by",
    "conflicts_with",
]

RELATIONS_V1: tuple[RelationV1, ...] = (
    "references",
    "derived_from",
    "caused_by",
    "conflicts_with",
)

RELATION_DIRECTIONS_V1: tuple[tuple[RelationV1, str], ...] = (
    (
        "references",
        "source is the reporter fact explicitly signing source -> target as a reference",
    ),
    (
        "derived_from",
        "source is the reporter fact explicitly signing source as derived from target",
    ),
    (
        "caused_by",
        "source is the reporter fact explicitly signing source as caused by target",
    ),
    (
        "conflicts_with",
        "source is the reporter fact explicitly signing a conflict with target; direction conveys no priority",
    ),
)

DiagnosticCodeV1 = Literal[
    "missing_source_fact",
    "missing_target_fact",
    "missing_reporter_fact",
    "reporter_payload_sha256_mismatch",
    "reporter_owner_sequence_mismatch",
    "explicit_conflict",
]

DIAGNOSTIC_CODES_V1: tuple[DiagnosticCodeV1, ...] = (
    "missing_source_fact",
    "missing_target_fact",
    "missing_reporter_fact",
    "reporter_payload_sha256_mismatch",
    "reporter_owner_sequence_mismatch",
    "explicit_conflict",
)

_ADMITTED_OWNERS = frozenset(
    owner for owner, _fact_type, _schema, _mode in _OWNER_FACT_ADMISSION_V1
)


def _owner_fact_admission(
    owner: str,
    fact_type: str,
) -> tuple[str, OwnerSequenceModeV1] | None:
    for admitted_owner, admitted_type, payload_schema, sequence_mode in (
        _OWNER_FACT_ADMISSION_V1
    ):
        if (owner, fact_type) == (admitted_owner, admitted_type):
            return payload_schema, sequence_mode
    return None


_REPORTER_CAPABLE_OWNERS = frozenset(
    owner
    for owner, _fact_type, _schema, mode in _OWNER_FACT_ADMISSION_V1
    if mode == "required"
)


class ProjectionContractError(ValueError):
    """Raised when the projection contract is malformed or non-canonical."""


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
            "Projection value is not canonical JSON."
        ) from exc


@dataclass(frozen=True, slots=True)
class FactRefV1:
    owner: str
    fact_ref: str

    def __post_init__(self) -> None:
        if self.owner not in _ADMITTED_OWNERS:
            raise ProjectionContractError("FactRefV1 owner is not admitted.")
        _require_text(self.fact_ref, "FactRefV1.fact_ref")

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "fact_ref": self.fact_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FactRefV1":
        _require_exact_fields(value, ("owner", "fact_ref"), "FactRefV1")
        return cls(owner=value["owner"], fact_ref=value["fact_ref"])


@dataclass(frozen=True, slots=True)
class OwnerFactV1:
    schema_version: Literal["1"]
    owner: str
    fact_type: str
    fact_ref: str
    payload_sha256: str
    payload_schema_version: str
    owner_sequence: int | None

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V1:
            raise ProjectionContractError("OwnerFactV1 schema version is unsupported.")
        admission = _owner_fact_admission(self.owner, self.fact_type)
        if admission is None:
            raise ProjectionContractError(
                "OwnerFactV1 owner plus fact_type pair is not admitted."
            )
        expected_payload_schema, owner_sequence_mode = admission
        if self.payload_schema_version != expected_payload_schema:
            raise ProjectionContractError(
                "OwnerFactV1 payload schema version does not match its admission."
            )
        _require_text(self.fact_ref, "OwnerFactV1.fact_ref")
        _require_sha256(self.payload_sha256, "OwnerFactV1.payload_sha256")
        if owner_sequence_mode == "required":
            _require_sequence(self.owner_sequence, "OwnerFactV1.owner_sequence")
        elif self.owner_sequence is not None:
            raise ProjectionContractError(
                "OwnerFactV1 owner sequence must be null for this admission."
            )

    @property
    def ref(self) -> FactRefV1:
        return FactRefV1(owner=self.owner, fact_ref=self.fact_ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "owner": self.owner,
            "fact_type": self.fact_type,
            "fact_ref": self.fact_ref,
            "payload_sha256": self.payload_sha256,
            "payload_schema_version": self.payload_schema_version,
            "owner_sequence": self.owner_sequence,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OwnerFactV1":
        _require_exact_fields(
            value,
            (
                "schema_version",
                "owner",
                "fact_type",
                "fact_ref",
                "payload_sha256",
                "payload_schema_version",
                "owner_sequence",
            ),
            "OwnerFactV1",
        )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class EdgeReporterV1:
    fact: FactRefV1
    payload_sha256: str
    owner_sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.fact, FactRefV1):
            raise ProjectionContractError("EdgeReporterV1.fact must be FactRefV1.")
        _require_sha256(
            self.payload_sha256,
            "EdgeReporterV1.payload_sha256",
        )
        _require_sequence(self.owner_sequence, "EdgeReporterV1.owner_sequence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact": self.fact.to_dict(),
            "payload_sha256": self.payload_sha256,
            "owner_sequence": self.owner_sequence,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EdgeReporterV1":
        _require_exact_fields(
            value,
            ("fact", "payload_sha256", "owner_sequence"),
            "EdgeReporterV1",
        )
        return cls(
            fact=FactRefV1.from_dict(value["fact"]),
            payload_sha256=value["payload_sha256"],
            owner_sequence=value["owner_sequence"],
        )


@dataclass(frozen=True, slots=True)
class ExplicitEdgeV1:
    schema_version: Literal["1"]
    relation: RelationV1
    source: FactRefV1
    target: FactRefV1
    reporter: EdgeReporterV1

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V1:
            raise ProjectionContractError(
                "ExplicitEdgeV1 schema version is unsupported."
            )
        if self.relation not in RELATIONS_V1:
            raise ProjectionContractError("ExplicitEdgeV1 relation is unsupported.")
        if not isinstance(self.source, FactRefV1) or not isinstance(
            self.target, FactRefV1
        ):
            raise ProjectionContractError(
                "ExplicitEdgeV1 endpoints must be FactRefV1."
            )
        if not isinstance(self.reporter, EdgeReporterV1):
            raise ProjectionContractError(
                "ExplicitEdgeV1 reporter must be EdgeReporterV1."
            )
        if self.reporter.fact != self.source:
            raise ProjectionContractError(
                "ExplicitEdgeV1 reporter fact must equal its source endpoint."
            )
        if self.source.owner not in _REPORTER_CAPABLE_OWNERS:
            raise ProjectionContractError(
                "ExplicitEdgeV1 source owner cannot issue a sequence-bound edge."
            )
        if self.relation == "conflicts_with" and self.source == self.target:
            raise ProjectionContractError(
                "ExplicitEdgeV1 conflicts_with endpoints must be distinct."
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
    def from_dict(cls, value: Mapping[str, Any]) -> "ExplicitEdgeV1":
        _require_exact_fields(
            value,
            ("schema_version", "relation", "source", "target", "reporter"),
            "ExplicitEdgeV1",
        )
        return cls(
            schema_version=value["schema_version"],
            relation=value["relation"],
            source=FactRefV1.from_dict(value["source"]),
            target=FactRefV1.from_dict(value["target"]),
            reporter=EdgeReporterV1.from_dict(value["reporter"]),
        )


@dataclass(frozen=True, slots=True)
class ProjectionDiagnosticV1:
    schema_version: Literal["1"]
    code: DiagnosticCodeV1
    edge_sha256: str
    primary_fact: FactRefV1
    related_fact: FactRefV1 | None
    fact_payload_sha256: str | None
    reporter_payload_sha256: str | None
    fact_owner_sequence: int | None
    reporter_owner_sequence: int | None

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V1:
            raise ProjectionContractError(
                "ProjectionDiagnosticV1 schema version is unsupported."
            )
        if self.code not in DIAGNOSTIC_CODES_V1:
            raise ProjectionContractError(
                "ProjectionDiagnosticV1 code is unsupported."
            )
        _require_sha256(
            self.edge_sha256,
            "ProjectionDiagnosticV1.edge_sha256",
        )
        if not isinstance(self.primary_fact, FactRefV1):
            raise ProjectionContractError(
                "ProjectionDiagnosticV1.primary_fact must be FactRefV1."
            )
        if self.related_fact is not None and not isinstance(
            self.related_fact, FactRefV1
        ):
            raise ProjectionContractError(
                "ProjectionDiagnosticV1.related_fact must be FactRefV1 or null."
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
            if self.related_fact is not None or any(item is not None for item in comparisons):
                raise ProjectionContractError(
                    "Missing-fact diagnostic carries unsupported comparison fields."
                )
            return
        if self.code == "explicit_conflict":
            if (
                self.related_fact is None
                or self.related_fact == self.primary_fact
                or any(item is not None for item in comparisons)
            ):
                raise ProjectionContractError(
                    "Explicit-conflict diagnostic shape is invalid."
                )
            return
        if self.related_fact is not None:
            raise ProjectionContractError(
                "Reporter mismatch diagnostic cannot carry related_fact."
            )
        if self.code == "reporter_payload_sha256_mismatch":
            _require_sha256(
                self.fact_payload_sha256,
                "ProjectionDiagnosticV1.fact_payload_sha256",
            )
            _require_sha256(
                self.reporter_payload_sha256,
                "ProjectionDiagnosticV1.reporter_payload_sha256",
            )
            if (
                self.fact_payload_sha256 == self.reporter_payload_sha256
                or self.fact_owner_sequence is not None
                or self.reporter_owner_sequence is not None
            ):
                raise ProjectionContractError(
                    "Reporter payload mismatch diagnostic shape is invalid."
                )
            return
        if self.code == "reporter_owner_sequence_mismatch":
            _require_sequence(
                self.fact_owner_sequence,
                "ProjectionDiagnosticV1.fact_owner_sequence",
            )
            _require_sequence(
                self.reporter_owner_sequence,
                "ProjectionDiagnosticV1.reporter_owner_sequence",
            )
            if (
                self.fact_owner_sequence == self.reporter_owner_sequence
                or self.fact_payload_sha256 is not None
                or self.reporter_payload_sha256 is not None
            ):
                raise ProjectionContractError(
                    "Reporter sequence mismatch diagnostic shape is invalid."
                )
            return
        raise ProjectionContractError("Projection diagnostic code shape is invalid.")

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
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectionDiagnosticV1":
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
            "ProjectionDiagnosticV1",
        )
        related = value["related_fact"]
        return cls(
            schema_version=value["schema_version"],
            code=value["code"],
            edge_sha256=value["edge_sha256"],
            primary_fact=FactRefV1.from_dict(value["primary_fact"]),
            related_fact=(FactRefV1.from_dict(related) if related is not None else None),
            fact_payload_sha256=value["fact_payload_sha256"],
            reporter_payload_sha256=value["reporter_payload_sha256"],
            fact_owner_sequence=value["fact_owner_sequence"],
            reporter_owner_sequence=value["reporter_owner_sequence"],
        )


def _fact_sort_key(fact: OwnerFactV1) -> tuple[str, str]:
    return fact.owner, fact.fact_ref


def _edge_sort_key(edge: ExplicitEdgeV1) -> tuple[Any, ...]:
    return (
        edge.source.owner,
        edge.source.fact_ref,
        edge.relation,
        edge.target.owner,
        edge.target.fact_ref,
        edge.reporter.fact.owner,
        edge.reporter.fact.fact_ref,
        edge.reporter.payload_sha256,
        edge.reporter.owner_sequence,
    )


def _diagnostic_sort_key(diagnostic: ProjectionDiagnosticV1) -> bytes:
    return _canonical_json_bytes(diagnostic.to_dict())


def _validate_fact_collection(facts: tuple[OwnerFactV1, ...]) -> None:
    if any(not isinstance(fact, OwnerFactV1) for fact in facts):
        raise ProjectionContractError("Projection facts must be OwnerFactV1 values.")
    refs = tuple(fact.ref for fact in facts)
    if len(set(refs)) != len(refs):
        raise ProjectionContractError(
            "Projection facts contain a duplicate owner plus fact_ref."
        )


def _validate_edge_collection(edges: tuple[ExplicitEdgeV1, ...]) -> None:
    if any(not isinstance(edge, ExplicitEdgeV1) for edge in edges):
        raise ProjectionContractError(
            "Projection edges must be ExplicitEdgeV1 values."
        )
    identities = tuple(edge.canonical_bytes() for edge in edges)
    if len(set(identities)) != len(identities):
        raise ProjectionContractError("Projection edges contain a duplicate edge.")


def _validate_diagnostic_collection(
    diagnostics: tuple[ProjectionDiagnosticV1, ...],
) -> None:
    if any(
        not isinstance(diagnostic, ProjectionDiagnosticV1)
        for diagnostic in diagnostics
    ):
        raise ProjectionContractError(
            "Projection diagnostics must be ProjectionDiagnosticV1 values."
        )
    identities = tuple(_canonical_json_bytes(item.to_dict()) for item in diagnostics)
    if len(set(identities)) != len(identities):
        raise ProjectionContractError(
            "Projection diagnostics contain a duplicate diagnostic."
        )


def _missing_diagnostic(
    code: DiagnosticCodeV1,
    edge: ExplicitEdgeV1,
    fact: FactRefV1,
) -> ProjectionDiagnosticV1:
    return ProjectionDiagnosticV1(
        schema_version="1",
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
    facts: tuple[OwnerFactV1, ...],
    edges: tuple[ExplicitEdgeV1, ...],
) -> tuple[ProjectionDiagnosticV1, ...]:
    fact_by_ref = {fact.ref: fact for fact in facts}
    diagnostics: list[ProjectionDiagnosticV1] = []
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
                    ProjectionDiagnosticV1(
                        schema_version="1",
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
            if reporter_fact.owner_sequence != edge.reporter.owner_sequence:
                reporter_matches = False
                diagnostics.append(
                    ProjectionDiagnosticV1(
                        schema_version="1",
                        code="reporter_owner_sequence_mismatch",
                        edge_sha256=edge.canonical_sha256(),
                        primary_fact=edge.reporter.fact,
                        related_fact=None,
                        fact_payload_sha256=None,
                        reporter_payload_sha256=None,
                        fact_owner_sequence=reporter_fact.owner_sequence,
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
                ProjectionDiagnosticV1(
                    schema_version="1",
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
class ProjectionViewV1:
    schema_version: Literal["1"]
    facts: tuple[OwnerFactV1, ...]
    edges: tuple[ExplicitEdgeV1, ...]
    diagnostics: tuple[ProjectionDiagnosticV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PROJECTION_SCHEMA_VERSION_V1:
            raise ProjectionContractError(
                "ProjectionViewV1 schema version is unsupported."
            )
        if type(self.facts) is not tuple or type(self.edges) is not tuple:
            raise ProjectionContractError(
                "ProjectionViewV1 facts and edges must be exact tuples."
            )
        if type(self.diagnostics) is not tuple:
            raise ProjectionContractError(
                "ProjectionViewV1 diagnostics must be an exact tuple."
            )
        _validate_fact_collection(self.facts)
        _validate_edge_collection(self.edges)
        _validate_diagnostic_collection(self.diagnostics)
        if self.facts != tuple(sorted(self.facts, key=_fact_sort_key)):
            raise ProjectionContractError(
                "ProjectionViewV1 fact serialization order is non-canonical."
            )
        if self.edges != tuple(sorted(self.edges, key=_edge_sort_key)):
            raise ProjectionContractError(
                "ProjectionViewV1 edge serialization order is non-canonical."
            )
        expected = _derive_diagnostics(self.facts, self.edges)
        if self.diagnostics != expected:
            raise ProjectionContractError(
                "ProjectionViewV1 diagnostics do not exactly match its complete inputs."
            )

    @classmethod
    def rebuild(
        cls,
        facts: Iterable[OwnerFactV1],
        edges: Iterable[ExplicitEdgeV1],
    ) -> "ProjectionViewV1":
        selected_facts = tuple(facts)
        selected_edges = tuple(edges)
        _validate_fact_collection(selected_facts)
        _validate_edge_collection(selected_edges)
        ordered_facts = tuple(sorted(selected_facts, key=_fact_sort_key))
        ordered_edges = tuple(sorted(selected_edges, key=_edge_sort_key))
        return cls(
            schema_version="1",
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
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectionViewV1":
        _require_exact_fields(
            value,
            ("schema_version", "facts", "edges", "diagnostics"),
            "ProjectionViewV1",
        )
        for field in ("facts", "edges", "diagnostics"):
            if type(value[field]) is not list:
                raise ProjectionContractError(
                    f"ProjectionViewV1.{field} must serialize as an array."
                )
        return cls(
            schema_version=value["schema_version"],
            facts=tuple(OwnerFactV1.from_dict(item) for item in value["facts"]),
            edges=tuple(ExplicitEdgeV1.from_dict(item) for item in value["edges"]),
            diagnostics=tuple(
                ProjectionDiagnosticV1.from_dict(item)
                for item in value["diagnostics"]
            ),
        )
