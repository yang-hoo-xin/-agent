"""Fail-open telemetry export for ``ProjectionViewV2``.

This module is deliberately limited to an injected, synchronous transport.
The repository does not declare a Langfuse or OpenTelemetry dependency, so no
external client is imported, loaded, configured, or guessed here.  A caller
that has separately established an exact SDK adapter may inject it through the
small sink protocol below.

The exported JSON contains only a redacted copy of the V2 fact identities,
allowlisted explicit edges, their hash/schema/owner-local-sequence fields, and
the View's existing item-level diagnostics.  It does not export owner payloads,
source text, credentials, or claims.  In every ``payload_sha256`` field, the
value means the referenced Artifact payload hash; it is not a hash of the
occurrence record or of this telemetry batch.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from src.non_authoritative_projection.contracts_v2 import (
    ArtifactRefV2,
    EdgeReporterV2,
    ExplicitEdgeV2,
    FactRefV2,
    OwnerFactV2,
    ProjectionDiagnosticV2,
    ProjectionViewV2,
)


TELEMETRY_SCHEMA_VERSION = "1"
TELEMETRY_KIND = "non_authoritative_projection_v2_identity_diagnostics"
PAYLOAD_SHA256_SEMANTICS = "referenced_artifact_payload_sha256"
IDENTITY_TEXT_REDACTION = "all_free_text_identity_to_sha256_utf8"

ExporterOutcome = Literal[
    "not_configured",
    "sink_calls_returned",
    "failed_open",
]
ExporterFailureStage = Literal["serialization", "queue", "flush"]
MonotonicClock = Callable[[], int]


_SAFE_EXCEPTION_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")


class ProjectionV2TelemetrySink(Protocol):
    """Transport supplied by the caller; it receives immutable JSON bytes.

    ``timeout_millis`` is a cooperative deadline argument for the injected
    adapter, which must return or raise within that deadline.  If the adapter
    ignores it, the synchronous call can outlive the value.  This exporter does
    not provide thread- or process-level cancellation and makes no deadline-
    enforcement claim.  A sink-reported ``TimeoutError`` is captured fail-open.
    """

    def enqueue(self, payload_json: bytes, *, timeout_millis: int) -> None: ...

    def flush(self, *, timeout_millis: int) -> None: ...


@dataclass(frozen=True, slots=True)
class ProjectionV2TelemetryFailure:
    """One exporter-local failure without endpoint, credential, or traceback."""

    stage: ExporterFailureStage
    exception_type: str

    def __post_init__(self) -> None:
        if self.stage not in ("serialization", "queue", "flush"):
            raise ValueError("Projection V2 telemetry failure stage is unsupported.")
        if type(self.exception_type) is not str or not _SAFE_EXCEPTION_TYPE.fullmatch(
            self.exception_type
        ):
            raise ValueError("Projection V2 telemetry exception type is unsafe.")

    def to_dict(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "exception_type": self.exception_type,
        }


@dataclass(frozen=True, slots=True)
class ProjectionV2TelemetryExportResult:
    """Exporter mechanics only; it is never a product or delivery result.

    ``sink_calls_returned`` means only that local serialization plus the
    injected sink's queue and flush methods returned without an exception.  It
    does not establish that Langfuse or another remote system received a batch.
    """

    outcome: ExporterOutcome
    serialization_returned: bool
    enqueue_returned: bool
    flush_attempted: bool
    flush_returned: bool
    fact_item_count: int
    edge_item_count: int
    diagnostic_item_count: int
    serialized_byte_count: int
    elapsed_milliseconds: float | None
    failures: tuple[ProjectionV2TelemetryFailure, ...]

    def __post_init__(self) -> None:
        if self.outcome not in (
            "not_configured",
            "sink_calls_returned",
            "failed_open",
        ):
            raise ValueError("Projection V2 telemetry exporter outcome is unsupported.")
        for name, value in (
            ("serialization_returned", self.serialization_returned),
            ("enqueue_returned", self.enqueue_returned),
            ("flush_attempted", self.flush_attempted),
            ("flush_returned", self.flush_returned),
        ):
            if type(value) is not bool:
                raise ValueError(f"Projection V2 telemetry {name} must be exact bool.")
        for name, value in (
            ("fact_item_count", self.fact_item_count),
            ("edge_item_count", self.edge_item_count),
            ("diagnostic_item_count", self.diagnostic_item_count),
            ("serialized_byte_count", self.serialized_byte_count),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"Projection V2 telemetry {name} must be >= 0.")
        if self.elapsed_milliseconds is not None and (
            type(self.elapsed_milliseconds) is not float
            or not math.isfinite(self.elapsed_milliseconds)
            or self.elapsed_milliseconds < 0
        ):
            raise ValueError(
                "Projection V2 telemetry elapsed_milliseconds must be non-negative."
            )
        if type(self.failures) is not tuple or any(
            not isinstance(item, ProjectionV2TelemetryFailure)
            for item in self.failures
        ):
            raise ValueError("Projection V2 telemetry failures must be an exact tuple.")
        if self.flush_returned and not self.flush_attempted:
            raise ValueError("Projection V2 telemetry cannot flush without an attempt.")
        if self.enqueue_returned and not self.serialization_returned:
            raise ValueError("Projection V2 telemetry cannot enqueue unserialized bytes.")
        if self.serialization_returned != (self.serialized_byte_count > 0):
            raise ValueError(
                "Projection V2 telemetry serialization and byte count disagree."
            )
        if self.outcome == "not_configured" and (
            self.serialization_returned
            or self.enqueue_returned
            or self.flush_attempted
            or self.flush_returned
            or self.fact_item_count
            or self.edge_item_count
            or self.diagnostic_item_count
            or self.serialized_byte_count
            or self.failures
            or self.elapsed_milliseconds != 0.0
        ):
            raise ValueError("Unconfigured Projection V2 telemetry did work.")
        if self.outcome == "sink_calls_returned" and (
            not self.serialization_returned
            or not self.enqueue_returned
            or not self.flush_attempted
            or not self.flush_returned
            or self.failures
        ):
            raise ValueError(
                "Returned Projection V2 telemetry sink-call result is inconsistent."
            )
        if self.outcome == "failed_open" and not self.failures:
            raise ValueError("Failed-open Projection V2 telemetry needs a failure.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "serialization_returned": self.serialization_returned,
            "enqueue_returned": self.enqueue_returned,
            "flush_attempted": self.flush_attempted,
            "flush_returned": self.flush_returned,
            "fact_item_count": self.fact_item_count,
            "edge_item_count": self.edge_item_count,
            "diagnostic_item_count": self.diagnostic_item_count,
            "serialized_byte_count": self.serialized_byte_count,
            "elapsed_milliseconds": self.elapsed_milliseconds,
            "failures": [item.to_dict() for item in self.failures],
        }


def _redact_identity_text(value: str | None) -> str | None:
    if value is None:
        return None
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"redacted:sha256:{digest}"


def _artifact_ref_payload(ref: ArtifactRefV2) -> dict[str, Any]:
    return {
        "feature_id": _redact_identity_text(ref.feature_id),
        "artifact_type": _redact_identity_text(ref.artifact_type),
        "path": _redact_identity_text(ref.path),
        "artifact_hash": ref.artifact_hash,
    }


def _fact_ref_payload(ref: FactRefV2) -> dict[str, Any]:
    return {
        "owner": ref.owner,
        "fact_type": ref.fact_type,
        "run_id": _redact_identity_text(ref.run_id),
        "request_id": _redact_identity_text(ref.request_id),
        "owner_sequence": ref.owner_sequence,
        "artifact_ref": _artifact_ref_payload(ref.artifact_ref),
    }


def _owner_fact_payload(fact: OwnerFactV2) -> dict[str, Any]:
    return {
        "schema_version": fact.schema_version,
        "fact": _fact_ref_payload(fact.fact),
        "payload_sha256": fact.payload_sha256,
        "payload_schema_version": fact.payload_schema_version,
    }


def _edge_reporter_payload(reporter: EdgeReporterV2) -> dict[str, Any]:
    return {
        "fact": _fact_ref_payload(reporter.fact),
        "payload_sha256": reporter.payload_sha256,
        "owner_sequence": reporter.owner_sequence,
    }


def _explicit_edge_payload(edge: ExplicitEdgeV2) -> dict[str, Any]:
    return {
        "schema_version": edge.schema_version,
        "relation": edge.relation,
        "source": _fact_ref_payload(edge.source),
        "target": _fact_ref_payload(edge.target),
        "reporter": _edge_reporter_payload(edge.reporter),
        "edge_sha256": edge.canonical_sha256(),
    }


def _diagnostic_payload(diagnostic: ProjectionDiagnosticV2) -> dict[str, Any]:
    return {
        "schema_version": diagnostic.schema_version,
        "code": diagnostic.code,
        "edge_sha256": diagnostic.edge_sha256,
        "primary_fact": _fact_ref_payload(diagnostic.primary_fact),
        "related_fact": (
            _fact_ref_payload(diagnostic.related_fact)
            if diagnostic.related_fact is not None
            else None
        ),
        "fact_payload_sha256": diagnostic.fact_payload_sha256,
        "reporter_payload_sha256": diagnostic.reporter_payload_sha256,
        "fact_owner_sequence": diagnostic.fact_owner_sequence,
        "reporter_owner_sequence": diagnostic.reporter_owner_sequence,
    }


def _telemetry_payload(view: ProjectionViewV2) -> dict[str, Any]:
    """Build a fresh allowlisted mapping; never expose the View to the sink."""

    return {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "telemetry_kind": TELEMETRY_KIND,
        "identity_text_redaction": IDENTITY_TEXT_REDACTION,
        "payload_sha256_semantics": PAYLOAD_SHA256_SEMANTICS,
        "projection_schema_version": view.schema_version,
        "facts": [_owner_fact_payload(item) for item in view.facts],
        "edges": [_explicit_edge_payload(item) for item in view.edges],
        "diagnostics": [
            _diagnostic_payload(item) for item in view.diagnostics
        ],
    }


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _failure(
    stage: ExporterFailureStage,
    exc: Exception,
) -> ProjectionV2TelemetryFailure:
    exception_type = type(exc).__name__
    if not _SAFE_EXCEPTION_TYPE.fullmatch(exception_type):
        exception_type = "Exception"
    return ProjectionV2TelemetryFailure(
        stage=stage,
        exception_type=exception_type,
    )


def _read_clock(clock: MonotonicClock) -> int | None:
    try:
        value = clock()
    except Exception:
        return None
    return value if type(value) is int and value >= 0 else None


def _elapsed_milliseconds(
    clock: MonotonicClock,
    started_ns: int | None,
) -> float | None:
    if started_ns is None:
        return None
    ended_ns = _read_clock(clock)
    if ended_ns is None:
        return None
    try:
        elapsed = max(0, ended_ns - started_ns) / 1_000_000
    except ArithmeticError:
        return None
    return elapsed if math.isfinite(elapsed) else None


@dataclass(frozen=True, slots=True)
class LangfuseProjectionViewV2Exporter:
    """One-shot V2 exporter backed only by an explicitly injected sink."""

    sink: ProjectionV2TelemetrySink | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    timeout_millis: int = 5_000
    clock_ns: MonotonicClock = field(
        default=time.monotonic_ns,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.timeout_millis) is not int or self.timeout_millis <= 0:
            raise ValueError(
                "Projection V2 telemetry timeout_millis must be an exact positive integer."
            )
        if not callable(self.clock_ns):
            raise TypeError("Projection V2 telemetry clock_ns must be callable.")

    def export(self, view: ProjectionViewV2) -> ProjectionV2TelemetryExportResult:
        if self.sink is None:
            return ProjectionV2TelemetryExportResult(
                outcome="not_configured",
                serialization_returned=False,
                enqueue_returned=False,
                flush_attempted=False,
                flush_returned=False,
                fact_item_count=0,
                edge_item_count=0,
                diagnostic_item_count=0,
                serialized_byte_count=0,
                elapsed_milliseconds=0.0,
                failures=(),
            )

        started_ns = _read_clock(self.clock_ns)
        failures: list[ProjectionV2TelemetryFailure] = []
        serialization_returned = False
        enqueue_returned = False
        flush_attempted = False
        flush_returned = False
        fact_item_count = 0
        edge_item_count = 0
        diagnostic_item_count = 0
        payload_json: bytes | None = None

        try:
            if type(view) is not ProjectionViewV2:
                raise TypeError("Exporter input must be an exact ProjectionViewV2.")
            fact_item_count = len(view.facts)
            edge_item_count = len(view.edges)
            diagnostic_item_count = len(view.diagnostics)
            payload_json = _canonical_json_bytes(_telemetry_payload(view))
            if type(payload_json) is not bytes or not payload_json:
                raise TypeError("Projection V2 telemetry serializer must return bytes.")
            serialization_returned = True
        except Exception as exc:
            payload_json = None
            failures.append(_failure("serialization", exc))

        if payload_json is not None:
            try:
                queue_result = self.sink.enqueue(
                    payload_json,
                    timeout_millis=self.timeout_millis,
                )
                if queue_result is not None:
                    raise TypeError(
                        "Projection V2 telemetry sink enqueue must return None."
                    )
                enqueue_returned = True
            except Exception as exc:
                failures.append(_failure("queue", exc))

        # Flush is intentionally independent.  A sink may have accepted part of
        # a queue operation before raising, or may hold earlier batches.
        flush_attempted = True
        try:
            flush_result = self.sink.flush(timeout_millis=self.timeout_millis)
            if flush_result is not None:
                raise TypeError(
                    "Projection V2 telemetry sink flush must return None."
                )
            flush_returned = True
        except Exception as exc:
            failures.append(_failure("flush", exc))

        outcome: ExporterOutcome = (
            "failed_open" if failures else "sink_calls_returned"
        )
        return ProjectionV2TelemetryExportResult(
            outcome=outcome,
            serialization_returned=serialization_returned,
            enqueue_returned=enqueue_returned,
            flush_attempted=flush_attempted,
            flush_returned=flush_returned,
            fact_item_count=fact_item_count,
            edge_item_count=edge_item_count,
            diagnostic_item_count=diagnostic_item_count,
            serialized_byte_count=len(payload_json) if payload_json is not None else 0,
            elapsed_milliseconds=_elapsed_milliseconds(
                self.clock_ns,
                started_ns,
            ),
            failures=tuple(failures),
        )


__all__ = [
    "IDENTITY_TEXT_REDACTION",
    "PAYLOAD_SHA256_SEMANTICS",
    "TELEMETRY_KIND",
    "TELEMETRY_SCHEMA_VERSION",
    "LangfuseProjectionViewV2Exporter",
    "ProjectionV2TelemetryExportResult",
    "ProjectionV2TelemetryFailure",
    "ProjectionV2TelemetrySink",
]
