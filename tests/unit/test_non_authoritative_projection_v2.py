from __future__ import annotations

import copy
import json

import pytest

from src.non_authoritative_projection.contracts import (
    EdgeReporterV1,
    ExplicitEdgeV1,
    FactRefV1,
    OwnerFactV1,
    ProjectionContractError,
    ProjectionViewV1,
)
from src.non_authoritative_projection.contracts_v2 import (
    DIAGNOSTIC_CODES_V2,
    OWNER_FACT_ADMISSION_V2,
    OWNER_FACT_ADMISSION_VERSION_V2,
    RELATION_DIRECTIONS_V2,
    RELATIONS_V2,
    ArtifactRefV2,
    EdgeReporterV2,
    ExplicitEdgeV2,
    FactRefV2,
    OwnerFactV2,
    ProjectionDiagnosticV2,
    ProjectionViewV2,
)


def _artifact(suffix: str) -> ArtifactRefV2:
    return ArtifactRefV2(
        feature_id="feature_projection_v2_001",
        artifact_type="evidence_pack",
        path=(
            "C:/store/features/feature_projection_v2_001/r/"
            f"evidence_pack/{suffix}.json"
        ),
        artifact_hash=suffix * 64,
    )


def _product_fact(
    *,
    run_id: str = "run_projection_v2_001",
    request_id: str = "request_projection_v2_001",
    sequence: int,
    artifact_ref: ArtifactRefV2,
) -> OwnerFactV2:
    fact = FactRefV2(
        owner="product_execution",
        fact_type="product_execution_output_v1",
        run_id=run_id,
        request_id=request_id,
        owner_sequence=sequence,
        artifact_ref=artifact_ref,
    )
    return OwnerFactV2(
        schema_version="2",
        fact=fact,
        payload_sha256=artifact_ref.artifact_hash,
        payload_schema_version="1.0",
    )


def _artifact_fact(artifact_ref: ArtifactRefV2) -> OwnerFactV2:
    fact = FactRefV2(
        owner="artifact_store",
        fact_type="artifact_revision_v1",
        run_id=None,
        request_id=None,
        owner_sequence=None,
        artifact_ref=artifact_ref,
    )
    return OwnerFactV2(
        schema_version="2",
        fact=fact,
        payload_sha256=artifact_ref.artifact_hash,
        payload_schema_version="1.0",
    )


def _edge(
    relation: str,
    source: OwnerFactV2,
    target: OwnerFactV2,
    *,
    reporter_fact: FactRefV2 | None = None,
    reporter_payload_sha256: str | None = None,
    reporter_owner_sequence: int | None = None,
) -> ExplicitEdgeV2:
    sequence = source.ref.owner_sequence
    assert sequence is not None
    return ExplicitEdgeV2(
        schema_version="2",
        relation=relation,
        source=source.ref,
        target=target.ref,
        reporter=EdgeReporterV2(
            fact=source.ref if reporter_fact is None else reporter_fact,
            payload_sha256=(
                source.payload_sha256
                if reporter_payload_sha256 is None
                else reporter_payload_sha256
            ),
            owner_sequence=(
                sequence
                if reporter_owner_sequence is None
                else reporter_owner_sequence
            ),
        ),
    )


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def test_v2_admission_and_exact_structured_identity_shape_are_frozen() -> None:
    artifact_ref = _artifact("a")
    product = _product_fact(sequence=4, artifact_ref=artifact_ref)
    revision = _artifact_fact(artifact_ref)
    conflict_edge = _edge("conflicts_with", product, revision)
    conflict_view = ProjectionViewV2.rebuild(
        (product, revision),
        (conflict_edge,),
    )
    diagnostic = conflict_view.diagnostics[0]

    assert OWNER_FACT_ADMISSION_VERSION_V2 == "owner_fact_admission_v2"
    assert OWNER_FACT_ADMISSION_V2 == (
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
    assert tuple(artifact_ref.to_dict()) == (
        "feature_id",
        "artifact_type",
        "path",
        "artifact_hash",
    )
    assert tuple(product.ref.to_dict()) == (
        "owner",
        "fact_type",
        "run_id",
        "request_id",
        "owner_sequence",
        "artifact_ref",
    )
    assert tuple(product.to_dict()) == (
        "schema_version",
        "fact",
        "payload_sha256",
        "payload_schema_version",
    )
    assert tuple(conflict_edge.reporter.to_dict()) == (
        "fact",
        "payload_sha256",
        "owner_sequence",
    )
    assert tuple(conflict_edge.to_dict()) == (
        "schema_version",
        "relation",
        "source",
        "target",
        "reporter",
    )
    assert tuple(diagnostic.to_dict()) == (
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
    assert tuple(conflict_view.to_dict()) == (
        "schema_version",
        "facts",
        "edges",
        "diagnostics",
    )
    assert ProjectionDiagnosticV2.from_dict(diagnostic.to_dict()) == diagnostic
    assert product.ref.run_id == "run_projection_v2_001"
    assert product.ref.request_id == "request_projection_v2_001"
    assert product.ref.owner_sequence == 4
    assert revision.ref.run_id is None
    assert revision.ref.request_id is None
    assert revision.ref.owner_sequence is None
    assert product.ref.artifact_ref == revision.ref.artifact_ref


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("owner", "projection"),
        ("fact_type", "product_status_v1"),
    ),
)
def test_v2_fact_ref_rejects_unregistered_owner_or_fact_type(
    field: str,
    value: object,
) -> None:
    serialized = _product_fact(
        sequence=4,
        artifact_ref=_artifact("a"),
    ).ref.to_dict()
    serialized[field] = value

    with pytest.raises(ProjectionContractError, match="pair is not admitted"):
        FactRefV2.from_dict(serialized)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "run_not_owned_by_artifact_store"),
        ("request_id", "request_not_owned_by_artifact_store"),
        ("owner_sequence", 0),
    ),
)
def test_artifact_revision_rejects_invented_scope_and_sequence(
    field: str,
    value: object,
) -> None:
    serialized = _artifact_fact(_artifact("a")).ref.to_dict()
    serialized[field] = value

    with pytest.raises(ProjectionContractError, match="must be null"):
        FactRefV2.from_dict(serialized)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", None),
        ("request_id", None),
        ("owner_sequence", None),
        ("owner_sequence", True),
    ),
)
def test_product_occurrence_rejects_missing_scope_sequence_and_bool_sequence(
    field: str,
    value: object,
) -> None:
    serialized = _product_fact(
        sequence=4,
        artifact_ref=_artifact("a"),
    ).ref.to_dict()
    serialized[field] = value

    with pytest.raises(ProjectionContractError):
        FactRefV2.from_dict(serialized)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("payload_schema_version", "1", "schema version"),
        ("payload_sha256", "b" * 64, "must equal its exact ArtifactRef hash"),
    ),
)
def test_owner_fact_rejects_wrong_payload_schema_and_artifact_hash_drift(
    field: str,
    value: object,
    message: str,
) -> None:
    serialized = _product_fact(
        sequence=4,
        artifact_ref=_artifact("a"),
    ).to_dict()
    serialized[field] = value

    with pytest.raises(ProjectionContractError, match=message):
        OwnerFactV2.from_dict(serialized)


def test_same_revision_different_occurrences_coexist_and_each_references_revision() -> None:
    artifact_ref = _artifact("a")
    first = _product_fact(sequence=4, artifact_ref=artifact_ref)
    second = _product_fact(sequence=5, artifact_ref=artifact_ref)
    revision = _artifact_fact(artifact_ref)
    edges = (
        _edge("references", first, revision),
        _edge("references", second, revision),
    )

    view = ProjectionViewV2.rebuild((second, revision, first), tuple(reversed(edges)))

    assert len(view.facts) == 3
    assert len(view.edges) == 2
    assert view.diagnostics == ()
    assert first.ref != second.ref
    assert first.ref.artifact_ref == second.ref.artifact_ref == revision.ref.artifact_ref
    assert {edge.source.owner_sequence for edge in view.edges} == {4, 5}
    assert {edge.target for edge in view.edges} == {revision.ref}
    assert all(edge.reporter.fact == edge.source for edge in view.edges)


def test_multi_result_scope_prevents_cross_run_collision_and_rebuild_is_stable() -> None:
    artifact_ref = _artifact("a")
    first_run = _product_fact(
        run_id="run_projection_v2_001",
        request_id="request_projection_v2_001",
        sequence=4,
        artifact_ref=artifact_ref,
    )
    second_run = _product_fact(
        run_id="run_projection_v2_002",
        request_id="request_projection_v2_002",
        sequence=4,
        artifact_ref=artifact_ref,
    )
    revision = _artifact_fact(artifact_ref)
    edges = (
        _edge("references", first_run, revision),
        _edge("references", second_run, revision),
    )

    forward = ProjectionViewV2.rebuild(
        (first_run, second_run, revision),
        edges,
    )
    reversed_inputs = ProjectionViewV2.rebuild(
        (revision, second_run, first_run),
        tuple(reversed(edges)),
    )

    assert forward == reversed_inputs
    assert forward.canonical_bytes() == reversed_inputs.canonical_bytes()
    assert forward.canonical_sha256() == reversed_inputs.canonical_sha256()
    assert ProjectionViewV2.from_dict(
        json.loads(forward.canonical_bytes().decode("utf-8"))
    ) == forward
    assert {fact.ref.run_id for fact in forward.facts} == {
        None,
        "run_projection_v2_001",
        "run_projection_v2_002",
    }


def test_duplicate_occurrence_and_scope_sequence_artifact_drift_fail_closed() -> None:
    first_artifact = _artifact("a")
    second_artifact = _artifact("b")
    first = _product_fact(sequence=4, artifact_ref=first_artifact)
    drifted = _product_fact(sequence=4, artifact_ref=second_artifact)

    with pytest.raises(ProjectionContractError, match="duplicate complete fact identity"):
        ProjectionViewV2.rebuild((first, first), ())

    with pytest.raises(ProjectionContractError, match="maps to multiple Artifact identities"):
        ProjectionViewV2.rebuild((first, drifted), ())

    first_revision = _artifact_fact(first_artifact)
    drift_edge = _edge("references", drifted, first_revision)
    with pytest.raises(ProjectionContractError, match="maps to multiple Artifact identities"):
        ProjectionViewV2.rebuild((first, first_revision), (drift_edge,))


def test_reporter_is_full_source_identity_and_artifact_revision_cannot_report() -> None:
    artifact_ref = _artifact("a")
    first = _product_fact(sequence=4, artifact_ref=artifact_ref)
    second = _product_fact(sequence=5, artifact_ref=artifact_ref)
    revision = _artifact_fact(artifact_ref)

    with pytest.raises(ProjectionContractError, match="must equal its source"):
        _edge("references", first, revision, reporter_fact=second.ref)

    serialized_reporter = {
        "fact": revision.ref.to_dict(),
        "payload_sha256": revision.payload_sha256,
        "owner_sequence": 0,
    }
    with pytest.raises(ProjectionContractError, match="cannot report without"):
        EdgeReporterV2(
            fact=revision.ref,
            payload_sha256=revision.payload_sha256,
            owner_sequence=0,
        )
    with pytest.raises(ProjectionContractError, match="cannot report without"):
        EdgeReporterV2.from_dict(serialized_reporter)


def test_product_reporter_wrong_sequence_remains_an_item_level_diagnostic() -> None:
    artifact_ref = _artifact("a")
    product = _product_fact(sequence=4, artifact_ref=artifact_ref)
    revision = _artifact_fact(artifact_ref)
    with pytest.raises(ProjectionContractError, match="exact integer"):
        EdgeReporterV2(
            fact=product.ref,
            payload_sha256=product.payload_sha256,
            owner_sequence=True,
        )
    edge = _edge(
        "references",
        product,
        revision,
        reporter_owner_sequence=5,
    )

    view = ProjectionViewV2.rebuild((product, revision), (edge,))
    payload_mismatch = ProjectionViewV2.rebuild(
        (product, revision),
        (
            _edge(
                "references",
                product,
                revision,
                reporter_payload_sha256="0" * 64,
            ),
        ),
    )

    assert [item.code for item in view.diagnostics] == [
        "reporter_owner_sequence_mismatch"
    ]
    diagnostic = view.diagnostics[0]
    assert diagnostic.fact_owner_sequence == 4
    assert diagnostic.reporter_owner_sequence == 5
    assert diagnostic.fact_payload_sha256 is None
    assert diagnostic.reporter_payload_sha256 is None
    assert [item.code for item in payload_mismatch.diagnostics] == [
        "reporter_payload_sha256_mismatch"
    ]


def test_missing_mismatch_and_conflict_remain_item_level_without_adjudication() -> None:
    artifact_ref = _artifact("a")
    product = _product_fact(sequence=4, artifact_ref=artifact_ref)
    revision = _artifact_fact(artifact_ref)
    references_edge = _edge("references", product, revision)
    mismatch_edge = _edge(
        "references",
        product,
        revision,
        reporter_payload_sha256="0" * 64,
        reporter_owner_sequence=5,
    )

    mismatch = ProjectionViewV2.rebuild((product, revision), (mismatch_edge,))
    missing = ProjectionViewV2.rebuild(
        (product,),
        (references_edge,),
    )
    missing_source_and_reporter = ProjectionViewV2.rebuild(
        (revision,),
        (references_edge,),
    )
    conflict_edge = _edge("conflicts_with", product, revision)
    conflict = ProjectionViewV2.rebuild(
        (product, revision),
        (conflict_edge,),
    )
    mismatched_conflict = ProjectionViewV2.rebuild(
        (product, revision),
        (
            _edge(
                "conflicts_with",
                product,
                revision,
                reporter_owner_sequence=5,
            ),
        ),
    )

    assert {item.code for item in mismatch.diagnostics} == {
        "reporter_payload_sha256_mismatch",
        "reporter_owner_sequence_mismatch",
    }
    assert [item.code for item in missing.diagnostics] == ["missing_target_fact"]
    assert {item.code for item in missing_source_and_reporter.diagnostics} == {
        "missing_source_fact",
        "missing_reporter_fact",
    }
    assert len(missing_source_and_reporter.diagnostics) == 2
    assert [item.code for item in conflict.diagnostics] == ["explicit_conflict"]
    conflict_diagnostic = conflict.diagnostics[0]
    assert conflict_diagnostic.primary_fact == conflict_edge.source
    assert conflict_diagnostic.related_fact == conflict_edge.target
    assert conflict_diagnostic.edge_sha256 == conflict_edge.canonical_sha256()
    assert [item.code for item in mismatched_conflict.diagnostics] == [
        "reporter_owner_sequence_mismatch"
    ]
    assert set(item.code for item in mismatch.diagnostics).issubset(
        DIAGNOSTIC_CODES_V2
    )
    assert {fact.ref for fact in conflict.facts} == {product.ref, revision.ref}
    assert _all_keys(conflict.to_dict()).isdisjoint(
        {
            "ready",
            "allowed",
            "first_failure",
            "failure_chain",
            "claim_impact",
            "fresh_actual_status",
            "should_pause",
            "should_retry",
            "repair_required",
            "next_attempt_authorized",
            "resume_authorized",
            "apply_authorized",
            "projection_integrity",
            "winner",
            "final_status",
            "status",
            "authority",
            "retry",
            "pause",
            "resume",
            "apply",
            "repair",
            "recovery",
        }
    )


def test_v2_strict_shape_order_and_duplicate_collections_are_rejected() -> None:
    artifact_ref = _artifact("a")
    first = _product_fact(sequence=4, artifact_ref=artifact_ref)
    second = _product_fact(sequence=5, artifact_ref=artifact_ref)
    revision = _artifact_fact(artifact_ref)
    edges = (
        _edge("references", first, revision),
        _edge("references", second, revision),
    )
    view = ProjectionViewV2.rebuild((first, second, revision), edges)

    top_level_unknown = copy.deepcopy(view.to_dict())
    top_level_unknown["unknown"] = None
    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV2.from_dict(top_level_unknown)

    unknown = copy.deepcopy(view.to_dict())
    unknown["facts"][0]["fact"]["artifact_ref"]["unknown"] = None
    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV2.from_dict(unknown)

    reordered_fields = copy.deepcopy(view.to_dict())
    fact = reordered_fields["facts"][0]["fact"]
    reordered_fields["facts"][0]["fact"] = {
        "fact_type": fact["fact_type"],
        "owner": fact["owner"],
        "run_id": fact["run_id"],
        "request_id": fact["request_id"],
        "owner_sequence": fact["owner_sequence"],
        "artifact_ref": fact["artifact_ref"],
    }
    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV2.from_dict(reordered_fields)

    reordered_facts = copy.deepcopy(view.to_dict())
    reordered_facts["facts"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV2.from_dict(reordered_facts)

    reordered_edges = copy.deepcopy(view.to_dict())
    reordered_edges["edges"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV2.from_dict(reordered_edges)

    duplicate_fact = copy.deepcopy(view.to_dict())
    duplicate_fact["facts"].append(copy.deepcopy(duplicate_fact["facts"][0]))
    with pytest.raises(ProjectionContractError, match="duplicate complete fact identity"):
        ProjectionViewV2.from_dict(duplicate_fact)

    duplicate_edge = copy.deepcopy(view.to_dict())
    duplicate_edge["edges"].append(copy.deepcopy(duplicate_edge["edges"][0]))
    with pytest.raises(ProjectionContractError, match="duplicate edge"):
        ProjectionViewV2.from_dict(duplicate_edge)

    conflict = ProjectionViewV2.rebuild(
        (first, revision),
        (_edge("conflicts_with", first, revision),),
    )
    duplicate_diagnostic = copy.deepcopy(conflict.to_dict())
    duplicate_diagnostic["diagnostics"].append(
        copy.deepcopy(duplicate_diagnostic["diagnostics"][0])
    )
    with pytest.raises(ProjectionContractError, match="duplicate diagnostic"):
        ProjectionViewV2.from_dict(duplicate_diagnostic)

    mismatch = ProjectionViewV2.rebuild(
        (first, revision),
        (
            _edge(
                "references",
                first,
                revision,
                reporter_payload_sha256="0" * 64,
                reporter_owner_sequence=5,
            ),
        ),
    )
    reordered_diagnostics = copy.deepcopy(mismatch.to_dict())
    reordered_diagnostics["diagnostics"].reverse()
    with pytest.raises(ProjectionContractError, match="complete inputs"):
        ProjectionViewV2.from_dict(reordered_diagnostics)


def test_relation_directions_are_finite_and_v1_does_not_auto_upgrade() -> None:
    assert RELATION_DIRECTIONS_V2 == (
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
    assert RELATIONS_V2 == tuple(
        relation for relation, _direction in RELATION_DIRECTIONS_V2
    )

    path = "C:/store/features/feature_projection_001/r/evidence_pack/a.json"
    product_v1 = OwnerFactV1(
        schema_version="1",
        owner="product_execution",
        fact_type="product_execution_output_v1",
        fact_ref=path,
        payload_sha256="a" * 64,
        payload_schema_version="1.0",
        owner_sequence=4,
    )
    revision_v1 = OwnerFactV1(
        schema_version="1",
        owner="artifact_store",
        fact_type="artifact_revision_v1",
        fact_ref=path,
        payload_sha256="a" * 64,
        payload_schema_version="1.0",
        owner_sequence=None,
    )
    edge_v1 = ExplicitEdgeV1(
        schema_version="1",
        relation="references",
        source=FactRefV1(owner="product_execution", fact_ref=path),
        target=FactRefV1(owner="artifact_store", fact_ref=path),
        reporter=EdgeReporterV1(
            fact=FactRefV1(owner="product_execution", fact_ref=path),
            payload_sha256="a" * 64,
            owner_sequence=4,
        ),
    )
    view_v1 = ProjectionViewV1.rebuild(
        (product_v1, revision_v1),
        (edge_v1,),
    )
    bytes_v1 = view_v1.canonical_bytes()
    hash_v1 = view_v1.canonical_sha256()

    view_v2 = ProjectionViewV2.rebuild(
        (
            _product_fact(sequence=4, artifact_ref=_artifact("a")),
            _artifact_fact(_artifact("a")),
        ),
        (),
    )

    assert ProjectionViewV1.from_dict(view_v1.to_dict()) == view_v1
    assert view_v1.canonical_bytes() == bytes_v1
    assert view_v1.canonical_sha256() == hash_v1
    with pytest.raises(ProjectionContractError):
        ProjectionViewV2.from_dict(copy.deepcopy(view_v1.to_dict()))
    with pytest.raises(ProjectionContractError):
        ProjectionViewV1.from_dict(copy.deepcopy(view_v2.to_dict()))
