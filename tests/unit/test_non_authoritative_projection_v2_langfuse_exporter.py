from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.non_authoritative_projection.contracts_v2 import (
    ArtifactRefV2,
    EdgeReporterV2,
    ExplicitEdgeV2,
    FactRefV2,
    OwnerFactV2,
    ProjectionViewV2,
    RelationV2,
)
from src.observability import (
    non_authoritative_projection_v2_langfuse_exporter as exporter_module,
)
from src.observability.non_authoritative_projection_v2_langfuse_exporter import (
    IDENTITY_TEXT_REDACTION,
    PAYLOAD_SHA256_SEMANTICS,
    TELEMETRY_KIND,
    TELEMETRY_SCHEMA_VERSION,
    LangfuseProjectionViewV2Exporter,
    ProjectionV2TelemetryExportResult,
    ProjectionV2TelemetryFailure,
)


def _artifact(
    suffix: str = "a",
    *,
    path: str | None = None,
) -> ArtifactRefV2:
    return ArtifactRefV2(
        feature_id="feature_projection_export_001",
        artifact_type="evidence_pack",
        path=(
            path
            or "C:/store/features/feature_projection_export_001/r/"
            f"evidence_pack/{suffix}.json"
        ),
        artifact_hash=suffix * 64,
    )


def _product_fact(
    *,
    sequence: int,
    artifact_ref: ArtifactRefV2,
    run_id: str = "run_projection_export_001",
    request_id: str = "request_projection_export_001",
) -> OwnerFactV2:
    return OwnerFactV2(
        schema_version="2",
        fact=FactRefV2(
            owner="product_execution",
            fact_type="product_execution_output_v1",
            run_id=run_id,
            request_id=request_id,
            owner_sequence=sequence,
            artifact_ref=artifact_ref,
        ),
        payload_sha256=artifact_ref.artifact_hash,
        payload_schema_version="1.0",
    )


def _revision_fact(artifact_ref: ArtifactRefV2) -> OwnerFactV2:
    return OwnerFactV2(
        schema_version="2",
        fact=FactRefV2(
            owner="artifact_store",
            fact_type="artifact_revision_v1",
            run_id=None,
            request_id=None,
            owner_sequence=None,
            artifact_ref=artifact_ref,
        ),
        payload_sha256=artifact_ref.artifact_hash,
        payload_schema_version="1.0",
    )


def _edge(
    relation: RelationV2,
    source: OwnerFactV2,
    target: OwnerFactV2,
    *,
    reporter_payload_sha256: str | None = None,
    reporter_owner_sequence: int | None = None,
) -> ExplicitEdgeV2:
    assert source.fact.owner_sequence is not None
    return ExplicitEdgeV2(
        schema_version="2",
        relation=relation,
        source=source.fact,
        target=target.fact,
        reporter=EdgeReporterV2(
            fact=source.fact,
            payload_sha256=(
                source.payload_sha256
                if reporter_payload_sha256 is None
                else reporter_payload_sha256
            ),
            owner_sequence=(
                source.fact.owner_sequence
                if reporter_owner_sequence is None
                else reporter_owner_sequence
            ),
        ),
    )


def _conflict_view(
    *,
    request_id: str = "request_projection_export_001",
) -> ProjectionViewV2:
    artifact_ref = _artifact()
    product = _product_fact(
        sequence=4,
        artifact_ref=artifact_ref,
        request_id=request_id,
    )
    revision = _revision_fact(artifact_ref)
    return ProjectionViewV2.rebuild(
        (revision, product),
        (_edge("conflicts_with", product, revision),),
    )


def _clock(*values: int) -> Callable[[], int]:
    selected = iter(values)

    def read() -> int:
        return next(selected)

    return read


def _redacted(value: str | None) -> str | None:
    if value is None:
        return None
    return "redacted:sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expected_fact_ref(ref: FactRefV2) -> dict[str, Any]:
    return {
        "owner": ref.owner,
        "fact_type": ref.fact_type,
        "run_id": _redacted(ref.run_id),
        "request_id": _redacted(ref.request_id),
        "owner_sequence": ref.owner_sequence,
        "artifact_ref": {
            "feature_id": _redacted(ref.artifact_ref.feature_id),
            "artifact_type": _redacted(ref.artifact_ref.artifact_type),
            "path": _redacted(ref.artifact_ref.path),
            "artifact_hash": ref.artifact_ref.artifact_hash,
        },
    }


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


@dataclass
class _FakeSink:
    endpoint: str = "https://telemetry.example.invalid"
    public_key: str = "public-must-not-export"
    secret_key: str = "secret-must-not-export"
    queue_error: Exception | None = None
    flush_error: Exception | None = None
    payloads: list[bytes] = field(default_factory=list)
    queue_timeouts: list[int] = field(default_factory=list)
    flush_timeouts: list[int] = field(default_factory=list)

    def enqueue(self, payload_json: bytes, *, timeout_millis: int) -> None:
        self.queue_timeouts.append(timeout_millis)
        if self.queue_error is not None:
            raise self.queue_error
        self.payloads.append(payload_json)

    def flush(self, *, timeout_millis: int) -> None:
        self.flush_timeouts.append(timeout_millis)
        if self.flush_error is not None:
            raise self.flush_error


@dataclass
class _InvalidReturnSink:
    queue_result: object | None = None
    flush_result: object | None = None

    def enqueue(self, payload_json: bytes, *, timeout_millis: int) -> object | None:
        del payload_json, timeout_millis
        return self.queue_result

    def flush(self, *, timeout_millis: int) -> object | None:
        del timeout_millis
        return self.flush_result


@dataclass
class _IgnoringTimeoutSink:
    payloads: list[bytes] = field(default_factory=list)
    received_timeouts: list[int] = field(default_factory=list)

    def enqueue(self, payload_json: bytes, *, timeout_millis: int) -> None:
        self.received_timeouts.append(timeout_millis)
        self.payloads.append(payload_json)

    def flush(self, *, timeout_millis: int) -> None:
        self.received_timeouts.append(timeout_millis)


def test_module_has_no_external_client_network_or_control_plane_import() -> None:
    path = Path(exporter_module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    allowed = {
        "__future__",
        "collections.abc",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "re",
        "src.non_authoritative_projection.contracts_v2",
        "time",
        "typing",
    }
    assert imported <= allowed
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imported
        for prefix in (
            "httpx",
            "langfuse",
            "opentelemetry",
            "requests",
            "socket",
            "src.mod_agent",
            "urllib",
        )
    )

    project_root = path.parents[2]
    exporter_name = (
        "src.observability."
        "non_authoritative_projection_v2_langfuse_exporter"
    )
    violations: list[str] = []
    for control_path in sorted((project_root / "src" / "mod_agent").rglob("*.py")):
        current_module = (
            control_path.relative_to(project_root)
            .with_suffix("")
            .as_posix()
            .replace("/", ".")
        )
        control_tree = ast.parse(
            control_path.read_text(encoding="utf-8"),
            filename=str(control_path),
        )
        for node in ast.walk(control_tree):
            names: set[str] = set()
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    base = node.module or ""
                else:
                    package = current_module.split(".")[:-1]
                    parent_hops = node.level - 1
                    anchor = package[: len(package) - parent_hops]
                    if node.module:
                        anchor.extend(node.module.split("."))
                    base = ".".join(anchor)
                if base:
                    names.add(base)
                names.update(
                    f"{base}.{alias.name}" if base else alias.name
                    for alias in node.names
                )
            if any(
                name == exporter_name or name.startswith(exporter_name + ".")
                for name in names
            ):
                violations.append(control_path.relative_to(project_root).as_posix())
    assert violations == []


def test_unconfigured_exporter_does_no_serialization_clock_or_sink_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _conflict_view()

    def forbidden_serializer(_value: Any) -> bytes:
        raise AssertionError("serializer must not run")

    def forbidden_clock() -> int:
        raise AssertionError("clock must not run")

    monkeypatch.setattr(exporter_module, "_canonical_json_bytes", forbidden_serializer)
    result = LangfuseProjectionViewV2Exporter(clock_ns=forbidden_clock).export(view)

    assert result.to_dict() == {
        "outcome": "not_configured",
        "serialization_returned": False,
        "enqueue_returned": False,
        "flush_attempted": False,
        "flush_returned": False,
        "fact_item_count": 0,
        "edge_item_count": 0,
        "diagnostic_item_count": 0,
        "serialized_byte_count": 0,
        "elapsed_milliseconds": 0.0,
        "failures": [],
    }


def test_fake_sink_gets_only_allowlisted_v2_facts_edges_and_diagnostics() -> None:
    secret_request = "api_key=must-not-export-request-secret"
    view = _conflict_view(request_id=secret_request)
    before = view.canonical_bytes()
    sink = _FakeSink()
    exporter = LangfuseProjectionViewV2Exporter(
        sink=sink,
        timeout_millis=321,
        clock_ns=_clock(1_000_000_000, 1_004_000_000),
    )
    exporter_text = repr(exporter)
    assert sink.endpoint not in exporter_text
    assert sink.public_key not in exporter_text
    assert sink.secret_key not in exporter_text

    result = exporter.export(view)

    assert result.outcome == "sink_calls_returned"
    assert result.serialization_returned is True
    assert result.enqueue_returned is True
    assert result.flush_attempted is True
    assert result.flush_returned is True
    assert result.fact_item_count == 2
    assert result.edge_item_count == 1
    assert result.diagnostic_item_count == 1
    assert result.serialized_byte_count == len(sink.payloads[0])
    assert result.elapsed_milliseconds == 4.0
    assert result.failures == ()
    assert sink.queue_timeouts == [321]
    assert sink.flush_timeouts == [321]
    assert view.canonical_bytes() == before

    payload = json.loads(sink.payloads[0].decode("utf-8"))
    assert tuple(payload) == (
        "telemetry_schema_version",
        "telemetry_kind",
        "identity_text_redaction",
        "payload_sha256_semantics",
        "projection_schema_version",
        "facts",
        "edges",
        "diagnostics",
    )
    assert payload["telemetry_schema_version"] == TELEMETRY_SCHEMA_VERSION
    assert payload["telemetry_kind"] == TELEMETRY_KIND
    assert payload["identity_text_redaction"] == IDENTITY_TEXT_REDACTION
    assert payload["payload_sha256_semantics"] == PAYLOAD_SHA256_SEMANTICS
    assert payload["projection_schema_version"] == "2"

    product = next(
        item
        for item in payload["facts"]
        if item["fact"]["owner"] == "product_execution"
    )
    assert tuple(product) == (
        "schema_version",
        "fact",
        "payload_sha256",
        "payload_schema_version",
    )
    assert tuple(product["fact"]) == (
        "owner",
        "fact_type",
        "run_id",
        "request_id",
        "owner_sequence",
        "artifact_ref",
    )
    assert tuple(product["fact"]["artifact_ref"]) == (
        "feature_id",
        "artifact_type",
        "path",
        "artifact_hash",
    )
    assert product["fact"]["run_id"] == _redacted("run_projection_export_001")
    assert product["fact"]["request_id"] == _redacted(secret_request)
    assert product["fact"]["owner_sequence"] == 4
    assert product["fact"]["artifact_ref"] == {
        "feature_id": _redacted(_artifact().feature_id),
        "artifact_type": _redacted(_artifact().artifact_type),
        "path": _redacted(_artifact().path),
        "artifact_hash": _artifact().artifact_hash,
    }
    assert product["payload_sha256"] == _artifact().artifact_hash
    assert (
        product["payload_sha256"]
        == product["fact"]["artifact_ref"]["artifact_hash"]
    )
    assert product["payload_schema_version"] == "1.0"

    exported_edge = payload["edges"][0]
    original_edge = view.edges[0]
    assert tuple(exported_edge) == (
        "schema_version",
        "relation",
        "source",
        "target",
        "reporter",
        "edge_sha256",
    )
    assert exported_edge["schema_version"] == original_edge.schema_version
    assert exported_edge["relation"] == "conflicts_with"
    assert exported_edge["source"] == _expected_fact_ref(original_edge.source)
    assert exported_edge["target"] == _expected_fact_ref(original_edge.target)
    assert tuple(exported_edge["reporter"]) == (
        "fact",
        "payload_sha256",
        "owner_sequence",
    )
    assert exported_edge["reporter"] == {
        "fact": _expected_fact_ref(original_edge.reporter.fact),
        "payload_sha256": original_edge.reporter.payload_sha256,
        "owner_sequence": original_edge.reporter.owner_sequence,
    }
    assert exported_edge["reporter"]["fact"] == exported_edge["source"]
    assert exported_edge["edge_sha256"] == original_edge.canonical_sha256()

    diagnostic = payload["diagnostics"][0]
    assert diagnostic["code"] == "explicit_conflict"
    assert diagnostic["edge_sha256"] == view.diagnostics[0].edge_sha256
    assert diagnostic["edge_sha256"] == exported_edge["edge_sha256"]
    assert (
        diagnostic["primary_fact"]["request_id"]
        == product["fact"]["request_id"]
    )
    assert diagnostic["related_fact"]["owner"] == "artifact_store"

    exported_text = sink.payloads[0].decode("utf-8")
    for forbidden_value in (
        secret_request,
        "run_projection_export_001",
        _artifact().feature_id,
        _artifact().artifact_type,
        _artifact().path,
        sink.endpoint,
        sink.public_key,
        sink.secret_key,
        "owner payload",
        "public void SecretSource()",
    ):
        assert forbidden_value not in exported_text
    assert _all_keys(payload).isdisjoint(
        {
            "apply_authorized",
            "claim",
            "data",
            "failure_chain",
            "first_failure",
            "fresh_actual_status",
            "next_attempt_authorized",
            "owner_payload",
            "projection_integrity",
            "repair_required",
            "source_code",
            "winner",
        }
    )
    assert _all_keys(result.to_dict()).isdisjoint(
        {
            "claim",
            "failure_chain",
            "first_failure",
            "fresh_actual_status",
            "product_status",
            "route",
        }
    )


def test_same_revision_occurrences_remain_distinct_and_payload_is_deterministic() -> None:
    artifact_ref = _artifact()
    first = _product_fact(sequence=4, artifact_ref=artifact_ref)
    second = _product_fact(sequence=5, artifact_ref=artifact_ref)
    revision = _revision_fact(artifact_ref)
    view = ProjectionViewV2.rebuild(
        (second, revision, first),
        (
            _edge("references", first, revision),
            _edge("references", second, revision),
        ),
    )
    sink = _FakeSink()
    exporter = LangfuseProjectionViewV2Exporter(sink=sink)

    first_result = exporter.export(view)
    second_result = exporter.export(view)

    assert first_result.outcome == second_result.outcome == "sink_calls_returned"
    assert first_result.edge_item_count == second_result.edge_item_count == 2
    assert sink.payloads[0] == sink.payloads[1]
    payload = json.loads(sink.payloads[0].decode("utf-8"))
    product_facts = [
        item
        for item in payload["facts"]
        if item["fact"]["owner"] == "product_execution"
    ]
    assert len(product_facts) == 2
    assert {item["fact"]["owner_sequence"] for item in product_facts} == {4, 5}
    assert {
        json.dumps(item["fact"]["artifact_ref"], sort_keys=True)
        for item in product_facts
    } == {
        json.dumps(
            {
                "feature_id": _redacted(revision.fact.artifact_ref.feature_id),
                "artifact_type": _redacted(revision.fact.artifact_ref.artifact_type),
                "path": _redacted(revision.fact.artifact_ref.path),
                "artifact_hash": revision.fact.artifact_ref.artifact_hash,
            },
            sort_keys=True,
        )
    }
    assert all(
        item["payload_sha256"] == artifact_ref.artifact_hash
        for item in product_facts
    )
    assert len(payload["edges"]) == 2
    assert {
        item["source"]["owner_sequence"] for item in payload["edges"]
    } == {4, 5}
    assert {
        item["reporter"]["fact"]["owner_sequence"]
        for item in payload["edges"]
    } == {4, 5}
    assert all(
        item["reporter"]["fact"] == item["source"]
        for item in payload["edges"]
    )
    assert len({item["edge_sha256"] for item in payload["edges"]}) == 2
    assert payload["diagnostics"] == []
    assert sink.queue_timeouts == [5_000, 5_000]
    assert sink.flush_timeouts == [5_000, 5_000]


def test_all_explicit_relations_keep_complete_redacted_edge_identities() -> None:
    source_artifact = _artifact("a")
    target_artifact = _artifact("b")
    source = _product_fact(
        sequence=4,
        artifact_ref=source_artifact,
        run_id="\trun_projection_export_001\n",
        request_id="\u3000request_projection_export_Δ\u00a0",
    )
    target = _product_fact(
        sequence=9,
        artifact_ref=target_artifact,
        run_id="\ntarget_run_projection_export_日本語\t",
        request_id="\u00a0target_request_projection_export_002\u3000",
    )
    relations: tuple[RelationV2, ...] = (
        "references",
        "derived_from",
        "caused_by",
        "conflicts_with",
    )
    view = ProjectionViewV2.rebuild(
        (target, source),
        tuple(_edge(relation, source, target) for relation in relations),
    )
    sink = _FakeSink()

    result = LangfuseProjectionViewV2Exporter(sink=sink).export(view)

    assert result.edge_item_count == 4
    payload = json.loads(sink.payloads[0].decode("utf-8"))
    assert len(payload["edges"]) == 4
    assert {item["relation"] for item in payload["edges"]} == set(relations)
    for exported, original in zip(payload["edges"], view.edges, strict=True):
        assert exported["schema_version"] == original.schema_version
        assert exported["relation"] == original.relation
        assert exported["source"] == _expected_fact_ref(original.source)
        assert exported["target"] == _expected_fact_ref(original.target)
        assert exported["reporter"] == {
            "fact": _expected_fact_ref(original.reporter.fact),
            "payload_sha256": original.reporter.payload_sha256,
            "owner_sequence": original.reporter.owner_sequence,
        }
        assert exported["edge_sha256"] == original.canonical_sha256()

    exported_text = sink.payloads[0].decode("utf-8")
    for redacted_value in (
        source.fact.run_id,
        source.fact.request_id,
        source.fact.artifact_ref.feature_id,
        source.fact.artifact_ref.artifact_type,
        source.fact.artifact_ref.path,
        target.fact.run_id,
        target.fact.request_id,
        target.fact.artifact_ref.feature_id,
        target.fact.artifact_ref.artifact_type,
        target.fact.artifact_ref.path,
    ):
        assert redacted_value is not None
        assert redacted_value not in exported_text
        assert _redacted(redacted_value) in exported_text

    exported_edge_hashes = {item["edge_sha256"] for item in payload["edges"]}
    assert {
        diagnostic["edge_sha256"] for diagnostic in payload["diagnostics"]
    } <= exported_edge_hashes


def test_all_six_existing_item_diagnostics_are_projected_without_new_semantics() -> None:
    artifact_ref = _artifact()
    product = _product_fact(sequence=4, artifact_ref=artifact_ref)
    revision = _revision_fact(artifact_ref)
    references = _edge("references", product, revision)
    views = (
        ProjectionViewV2.rebuild((product,), (references,)),
        ProjectionViewV2.rebuild((revision,), (references,)),
        ProjectionViewV2.rebuild(
            (product, revision),
            (
                _edge(
                    "references",
                    product,
                    revision,
                    reporter_payload_sha256="0" * 64,
                    reporter_owner_sequence=5,
                ),
            ),
        ),
        ProjectionViewV2.rebuild(
            (product, revision),
            (_edge("conflicts_with", product, revision),),
        ),
    )
    observed_codes: set[str] = set()

    for view in views:
        sink = _FakeSink()
        result = LangfuseProjectionViewV2Exporter(sink=sink).export(view)
        assert result.outcome == "sink_calls_returned"
        payload = json.loads(sink.payloads[0].decode("utf-8"))
        assert result.edge_item_count == len(view.edges)
        assert len(payload["edges"]) == len(view.edges)
        exported_edge_hashes = {
            item["edge_sha256"] for item in payload["edges"]
        }
        assert len(payload["diagnostics"]) == len(view.diagnostics)
        for projected, original in zip(
            payload["diagnostics"],
            view.diagnostics,
            strict=True,
        ):
            observed_codes.add(projected["code"])
            assert tuple(projected) == (
                "schema_version",
                "code",
                "edge_sha256",
                "primary_fact",
                "related_fact",
                "fact_payload_sha256",
                "reporter_payload_sha256",
                "fact_owner_sequence",
                "reporter_owner_sequence",
            )
            assert projected["schema_version"] == original.schema_version
            assert projected["code"] == original.code
            assert projected["edge_sha256"] == original.edge_sha256
            assert projected["edge_sha256"] in exported_edge_hashes
            assert projected["fact_payload_sha256"] == original.fact_payload_sha256
            assert (
                projected["reporter_payload_sha256"]
                == original.reporter_payload_sha256
            )
            assert projected["fact_owner_sequence"] == original.fact_owner_sequence
            assert (
                projected["reporter_owner_sequence"]
                == original.reporter_owner_sequence
            )
            assert projected["primary_fact"]["owner"] == original.primary_fact.owner
            assert (
                projected["primary_fact"]["owner_sequence"]
                == original.primary_fact.owner_sequence
            )
            assert projected["primary_fact"]["run_id"] == _redacted(
                original.primary_fact.run_id
            )
            if original.related_fact is None:
                assert projected["related_fact"] is None
            else:
                assert projected["related_fact"]["owner"] == original.related_fact.owner
                assert projected["related_fact"]["run_id"] == _redacted(
                    original.related_fact.run_id
                )
                assert projected["related_fact"]["artifact_ref"]["path"] == _redacted(
                    original.related_fact.artifact_ref.path
                )

    assert observed_codes == {
        "explicit_conflict",
        "missing_reporter_fact",
        "missing_source_fact",
        "missing_target_fact",
        "reporter_owner_sequence_mismatch",
        "reporter_payload_sha256_mismatch",
    }


_SECRET_ERROR_MESSAGE = (
    "https://user:password@example.invalid/api?api_key=must-not-export"
)


@pytest.mark.parametrize(
    (
        "mode",
        "queue_error",
        "flush_error",
        "expected_stage",
        "expected_exception_type",
        "expected_serialization_returned",
        "expected_enqueue_returned",
        "expected_flush_returned",
    ),
    (
        (
            "serialization",
            None,
            None,
            "serialization",
            "TypeError",
            False,
            False,
            True,
        ),
        (
            "sink_unreachable",
            ConnectionError(_SECRET_ERROR_MESSAGE),
            None,
            "queue",
            "ConnectionError",
            True,
            False,
            True,
        ),
        (
            "queue_reported_timeout",
            TimeoutError(_SECRET_ERROR_MESSAGE),
            None,
            "queue",
            "TimeoutError",
            True,
            False,
            True,
        ),
        (
            "queue_failure",
            RuntimeError(_SECRET_ERROR_MESSAGE),
            None,
            "queue",
            "RuntimeError",
            True,
            False,
            True,
        ),
        (
            "flush_reported_timeout",
            None,
            TimeoutError(_SECRET_ERROR_MESSAGE),
            "flush",
            "TimeoutError",
            True,
            True,
            False,
        ),
        (
            "flush_failure",
            None,
            RuntimeError(_SECRET_ERROR_MESSAGE),
            "flush",
            "RuntimeError",
            True,
            True,
            False,
        ),
    ),
)
def test_serialization_and_sink_reported_failures_fail_open(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    queue_error: Exception | None,
    flush_error: Exception | None,
    expected_stage: str,
    expected_exception_type: str,
    expected_serialization_returned: bool,
    expected_enqueue_returned: bool,
    expected_flush_returned: bool,
) -> None:
    view = _conflict_view()
    before = view.canonical_bytes()
    sink = _FakeSink(queue_error=queue_error, flush_error=flush_error)

    def broken_serializer(_value: Any) -> bytes:
        raise TypeError(_SECRET_ERROR_MESSAGE)

    if mode == "serialization":
        monkeypatch.setattr(exporter_module, "_canonical_json_bytes", broken_serializer)
    exporter = LangfuseProjectionViewV2Exporter(
        sink=sink,
        timeout_millis=77,
        clock_ns=_clock(2_000_000_000, 2_003_000_000),
    )

    result = exporter.export(view)

    assert result.outcome == "failed_open"
    assert result.serialization_returned is expected_serialization_returned
    assert result.enqueue_returned is expected_enqueue_returned
    assert result.flush_attempted is True
    assert result.flush_returned is expected_flush_returned
    assert result.elapsed_milliseconds == 3.0
    assert [(item.stage, item.exception_type) for item in result.failures] == [
        (expected_stage, expected_exception_type)
    ]
    assert sink.flush_timeouts == [77]
    assert sink.queue_timeouts == ([] if mode == "serialization" else [77])
    assert view.canonical_bytes() == before
    result_text = json.dumps(result.to_dict(), ensure_ascii=False)
    assert _SECRET_ERROR_MESSAGE not in result_text
    assert _SECRET_ERROR_MESSAGE not in repr(result)


def test_queue_and_flush_failures_are_independently_captured() -> None:
    view = _conflict_view()
    sink = _FakeSink(
        queue_error=RuntimeError("queue " + _SECRET_ERROR_MESSAGE),
        flush_error=TimeoutError("flush " + _SECRET_ERROR_MESSAGE),
    )
    exporter = LangfuseProjectionViewV2Exporter(
        sink=sink,
        timeout_millis=88,
        clock_ns=_clock(3_000_000_000, 3_001_000_000),
    )

    result = exporter.export(view)

    assert result.outcome == "failed_open"
    assert result.serialization_returned is True
    assert result.enqueue_returned is False
    assert result.flush_attempted is True
    assert result.flush_returned is False
    assert [(item.stage, item.exception_type) for item in result.failures] == [
        ("queue", "RuntimeError"),
        ("flush", "TimeoutError"),
    ]
    assert sink.queue_timeouts == [88]
    assert sink.flush_timeouts == [88]
    assert _SECRET_ERROR_MESSAGE not in repr(result)


@pytest.mark.parametrize(
    ("sink", "expected_stage", "expected_enqueue_returned", "expected_flush_returned"),
    (
        (_InvalidReturnSink(queue_result=False), "queue", False, True),
        (_InvalidReturnSink(flush_result=False), "flush", True, False),
    ),
)
def test_sync_sink_methods_must_return_exact_none(
    sink: _InvalidReturnSink,
    expected_stage: str,
    expected_enqueue_returned: bool,
    expected_flush_returned: bool,
) -> None:
    result = LangfuseProjectionViewV2Exporter(
        sink=sink,  # type: ignore[arg-type]
    ).export(_conflict_view())

    assert result.outcome == "failed_open"
    assert result.enqueue_returned is expected_enqueue_returned
    assert result.flush_returned is expected_flush_returned
    assert [(item.stage, item.exception_type) for item in result.failures] == [
        (expected_stage, "TypeError")
    ]


@pytest.mark.parametrize(
    ("clock", "expected_elapsed"),
    (
        (_clock(0, 10**1000), None),
        (_clock(10, 5), 0.0),
        (_clock(True), None),
    ),
)
def test_exporter_timing_cannot_break_fail_open_result(
    clock: Callable[[], int],
    expected_elapsed: float | None,
) -> None:
    sink = _FakeSink()
    result = LangfuseProjectionViewV2Exporter(
        sink=sink,
        clock_ns=clock,
    ).export(_conflict_view())

    assert result.outcome == "sink_calls_returned"
    assert result.elapsed_milliseconds == expected_elapsed
    assert result.failures == ()


def test_ignored_cooperative_timeout_is_not_exporter_cancellation() -> None:
    sink = _IgnoringTimeoutSink()
    result = LangfuseProjectionViewV2Exporter(
        sink=sink,
        timeout_millis=1,
        clock_ns=_clock(0, 5_000_000),
    ).export(_conflict_view())

    assert sink.received_timeouts == [1, 1]
    assert len(sink.payloads) == 1
    assert result.outcome == "sink_calls_returned"
    assert result.elapsed_milliseconds == 5.0
    assert result.failures == ()


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("serialization_returned", 1),
        ("enqueue_returned", 1),
        ("flush_attempted", 1),
        ("flush_returned", 1),
        ("elapsed_milliseconds", float("nan")),
        ("elapsed_milliseconds", float("inf")),
        ("elapsed_milliseconds", 99.0),
        ("edge_item_count", True),
        ("edge_item_count", -1),
        ("serialized_byte_count", 1),
    ),
)
def test_export_result_rejects_non_exact_flags_and_non_finite_timing(
    field_name: str,
    invalid_value: object,
) -> None:
    values: dict[str, Any] = {
        "outcome": "not_configured",
        "serialization_returned": False,
        "enqueue_returned": False,
        "flush_attempted": False,
        "flush_returned": False,
        "fact_item_count": 0,
        "edge_item_count": 0,
        "diagnostic_item_count": 0,
        "serialized_byte_count": 0,
        "elapsed_milliseconds": 0.0,
        "failures": (),
    }
    values[field_name] = invalid_value

    with pytest.raises(ValueError):
        ProjectionV2TelemetryExportResult(**values)


def test_failure_exception_type_requires_an_exact_safe_string() -> None:
    with pytest.raises(ValueError, match="exception type is unsafe"):
        ProjectionV2TelemetryFailure(
            stage="queue",
            exception_type=123,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("timeout_millis", (True, 0, -1))
def test_timeout_configuration_requires_an_exact_positive_integer(
    timeout_millis: object,
) -> None:
    with pytest.raises(ValueError, match="exact positive integer"):
        LangfuseProjectionViewV2Exporter(timeout_millis=timeout_millis)  # type: ignore[arg-type]
