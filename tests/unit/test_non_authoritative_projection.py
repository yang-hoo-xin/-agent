from __future__ import annotations

import copy
import json

import pytest

from src.non_authoritative_projection import (
    DIAGNOSTIC_CODES_V1,
    RELATION_DIRECTIONS_V1,
    RELATIONS_V1,
    EdgeReporterV1,
    ExplicitEdgeV1,
    FactRefV1,
    OwnerFactV1,
    ProjectionContractError,
    ProjectionViewV1,
)


FACT_TYPE_BY_OWNER = {
    "actual_execution": "actual_execution_result",
    "build": "build_result",
    "product_execution": "product_execution_result",
}


def _fact(
    owner: str,
    fact_ref: str,
    *,
    owner_sequence: int,
    hash_character: str,
) -> OwnerFactV1:
    return OwnerFactV1(
        schema_version="1",
        owner=owner,
        fact_type=FACT_TYPE_BY_OWNER[owner],
        fact_ref=fact_ref,
        payload_sha256=hash_character * 64,
        payload_schema_version="owner_payload_v1",
        owner_sequence=owner_sequence,
    )


def _edge(
    relation: str,
    source: OwnerFactV1,
    target: OwnerFactV1,
    reporter: OwnerFactV1,
    *,
    reporter_payload_sha256: str | None = None,
    reporter_owner_sequence: int | None = None,
) -> ExplicitEdgeV1:
    return ExplicitEdgeV1(
        schema_version="1",
        relation=relation,
        source=source.ref,
        target=target.ref,
        reporter=EdgeReporterV1(
            fact=reporter.ref,
            payload_sha256=(
                reporter.payload_sha256
                if reporter_payload_sha256 is None
                else reporter_payload_sha256
            ),
            owner_sequence=(
                reporter.owner_sequence
                if reporter_owner_sequence is None
                else reporter_owner_sequence
            ),
        ),
    )


def _complete_fixture() -> tuple[
    tuple[OwnerFactV1, ...], tuple[ExplicitEdgeV1, ...]
]:
    actual = _fact(
        "actual_execution",
        "actual://run-001/receipt",
        owner_sequence=4,
        hash_character="a",
    )
    product = _fact(
        "product_execution",
        "product://run-001/result",
        owner_sequence=8,
        hash_character="b",
    )
    build = _fact(
        "build",
        "build://run-001/result",
        owner_sequence=2,
        hash_character="c",
    )
    return (
        (actual, product, build),
        (
            _edge("derived_from", product, actual, product),
            _edge("references", product, build, product),
        ),
    )


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def test_contract_strict_roundtrip_and_exact_owner_fact_shape() -> None:
    facts, edges = _complete_fixture()
    view = ProjectionViewV1.rebuild(facts, edges)
    serialized = json.loads(view.canonical_bytes().decode("utf-8"))

    assert ProjectionViewV1.from_dict(serialized) == view
    assert view.canonical_sha256() == ProjectionViewV1.from_dict(
        serialized
    ).canonical_sha256()
    assert tuple(view.facts[0].to_dict()) == (
        "schema_version",
        "owner",
        "fact_type",
        "fact_ref",
        "payload_sha256",
        "payload_schema_version",
        "owner_sequence",
    )
    assert "payload" not in view.facts[0].to_dict()


@pytest.mark.parametrize(
    "mutation",
    (
        "top_level_unknown",
        "fact_unknown",
        "edge_unknown",
        "top_level_field_order",
        "fact_field_order",
    ),
)
def test_from_dict_rejects_unknown_fields_and_noncanonical_field_order(
    mutation: str,
) -> None:
    facts, edges = _complete_fixture()
    serialized = copy.deepcopy(ProjectionViewV1.rebuild(facts, edges).to_dict())
    if mutation == "top_level_unknown":
        serialized["unknown"] = None
    elif mutation == "fact_unknown":
        serialized["facts"][0]["unknown"] = None
    elif mutation == "edge_unknown":
        serialized["edges"][0]["unknown"] = None
    elif mutation == "top_level_field_order":
        serialized = {
            "facts": serialized["facts"],
            "schema_version": serialized["schema_version"],
            "edges": serialized["edges"],
            "diagnostics": serialized["diagnostics"],
        }
    else:
        fact = serialized["facts"][0]
        serialized["facts"][0] = {
            "owner": fact["owner"],
            "schema_version": fact["schema_version"],
            "fact_type": fact["fact_type"],
            "fact_ref": fact["fact_ref"],
            "payload_sha256": fact["payload_sha256"],
            "payload_schema_version": fact["payload_schema_version"],
            "owner_sequence": fact["owner_sequence"],
        }

    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV1.from_dict(serialized)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "2"),
        ("payload_sha256", "A" * 64),
        ("payload_sha256", "sha256:" + "a" * 64),
        ("payload_sha256", "a" * 63),
        ("payload_schema_version", "Owner Payload V1"),
        ("owner", "ProductExecution"),
        ("fact_type", "product execution result"),
        ("owner_sequence", True),
    ),
)
def test_owner_fact_rejects_wrong_version_hash_and_scalar_shape(
    field: str,
    value: object,
) -> None:
    fact = _fact(
        "product_execution",
        "product://run-001/result",
        owner_sequence=1,
        hash_character="a",
    ).to_dict()
    fact[field] = value

    with pytest.raises(ProjectionContractError):
        OwnerFactV1.from_dict(fact)


def test_rebuild_canonical_bytes_ignore_input_collection_order_only() -> None:
    facts, edges = _complete_fixture()
    forward = ProjectionViewV1.rebuild(facts, edges)
    reversed_inputs = ProjectionViewV1.rebuild(
        tuple(reversed(facts)), tuple(reversed(edges))
    )

    assert forward == reversed_inputs
    assert forward.canonical_bytes() == reversed_inputs.canonical_bytes()
    assert forward.canonical_sha256() == reversed_inputs.canonical_sha256()
    assert [fact.owner_sequence for fact in forward.facts] == [4, 2, 8]

    noncanonical = copy.deepcopy(forward.to_dict())
    noncanonical["facts"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV1.from_dict(noncanonical)

    noncanonical_edges = copy.deepcopy(forward.to_dict())
    noncanonical_edges["edges"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV1.from_dict(noncanonical_edges)


def test_relation_enum_and_directions_are_finite_and_exact() -> None:
    assert tuple(relation for relation, _direction in RELATION_DIRECTIONS_V1) == (
        "references",
        "derived_from",
        "caused_by",
        "conflicts_with",
    )
    assert RELATIONS_V1 == tuple(
        relation for relation, _direction in RELATION_DIRECTIONS_V1
    )
    facts, edges = _complete_fixture()
    invalid = edges[0].to_dict()
    invalid["relation"] = "inferred_from_timestamp"

    with pytest.raises(ProjectionContractError, match="relation is unsupported"):
        ExplicitEdgeV1.from_dict(invalid)


def test_different_owner_conflict_is_parallel_and_has_no_adjudication_fields() -> None:
    product = _fact(
        "product_execution",
        "product://run-002/result",
        owner_sequence=11,
        hash_character="d",
    )
    build = _fact(
        "build",
        "build://run-002/result",
        owner_sequence=3,
        hash_character="e",
    )
    reporter = _fact(
        "actual_execution",
        "actual://run-002/receipt",
        owner_sequence=7,
        hash_character="f",
    )
    view = ProjectionViewV1.rebuild(
        (product, build, reporter),
        (_edge("conflicts_with", product, build, reporter),),
    )

    assert {fact.ref for fact in view.facts} == {
        product.ref,
        build.ref,
        reporter.ref,
    }
    assert [item.code for item in view.diagnostics] == ["explicit_conflict"]
    assert view.diagnostics[0].primary_fact == product.ref
    assert view.diagnostics[0].related_fact == build.ref
    assert _all_keys(view.to_dict()).isdisjoint(
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
        }
    )


def test_explicit_edge_endpoints_and_reporter_binding_are_fully_verified() -> None:
    facts, _edges = _complete_fixture()
    actual, product, build = facts
    good = _edge("caused_by", product, build, actual)

    assert ProjectionViewV1.rebuild(facts, (good,)).diagnostics == ()
    assert good.to_dict()["source"] == {
        "owner": "product_execution",
        "fact_ref": "product://run-001/result",
    }
    assert good.to_dict()["target"] == {
        "owner": "build",
        "fact_ref": "build://run-001/result",
    }
    assert good.to_dict()["reporter"] == {
        "fact": {
            "owner": "actual_execution",
            "fact_ref": "actual://run-001/receipt",
        },
        "payload_sha256": actual.payload_sha256,
        "owner_sequence": actual.owner_sequence,
    }

    missing_source = ProjectionViewV1.rebuild((actual, build), (good,))
    missing_target = ProjectionViewV1.rebuild((actual, product), (good,))
    missing_reporter = ProjectionViewV1.rebuild((product, build), (good,))
    mismatch = ProjectionViewV1.rebuild(
        facts,
        (
            _edge(
                "caused_by",
                product,
                build,
                actual,
                reporter_payload_sha256="0" * 64,
                reporter_owner_sequence=actual.owner_sequence + 1,
            ),
        ),
    )

    assert [item.code for item in missing_source.diagnostics] == [
        "missing_source_fact"
    ]
    assert [item.code for item in missing_target.diagnostics] == [
        "missing_target_fact"
    ]
    assert [item.code for item in missing_reporter.diagnostics] == [
        "missing_reporter_fact"
    ]
    assert {item.code for item in mismatch.diagnostics} == {
        "reporter_payload_sha256_mismatch",
        "reporter_owner_sequence_mismatch",
    }
    by_code = {item.code: item for item in mismatch.diagnostics}
    assert by_code["reporter_payload_sha256_mismatch"].fact_payload_sha256 == (
        actual.payload_sha256
    )
    assert by_code[
        "reporter_payload_sha256_mismatch"
    ].reporter_payload_sha256 == "0" * 64
    assert by_code["reporter_owner_sequence_mismatch"].fact_owner_sequence == (
        actual.owner_sequence
    )
    assert by_code[
        "reporter_owner_sequence_mismatch"
    ].reporter_owner_sequence == actual.owner_sequence + 1


def test_diagnostics_are_derived_strict_unique_and_lossless() -> None:
    facts, _edges = _complete_fixture()
    actual, product, build = facts
    edge = _edge(
        "references",
        product,
        build,
        actual,
        reporter_payload_sha256="0" * 64,
        reporter_owner_sequence=actual.owner_sequence + 1,
    )
    view = ProjectionViewV1.rebuild(facts, (edge,))
    serialized = copy.deepcopy(view.to_dict())

    assert len(view.diagnostics) == 2
    assert set(item.code for item in view.diagnostics).issubset(
        DIAGNOSTIC_CODES_V1
    )
    assert ProjectionViewV1.from_dict(serialized) == view

    duplicated = copy.deepcopy(serialized)
    duplicated["diagnostics"].append(copy.deepcopy(duplicated["diagnostics"][0]))
    with pytest.raises(ProjectionContractError, match="duplicate diagnostic"):
        ProjectionViewV1.from_dict(duplicated)

    reordered = copy.deepcopy(serialized)
    reordered["diagnostics"].reverse()
    with pytest.raises(ProjectionContractError, match="complete inputs"):
        ProjectionViewV1.from_dict(reordered)

    altered = copy.deepcopy(serialized)
    altered["diagnostics"][0]["unknown"] = None
    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV1.from_dict(altered)


def test_duplicate_fact_ref_and_duplicate_edge_are_rejected_not_normalized() -> None:
    facts, edges = _complete_fixture()
    view = ProjectionViewV1.rebuild(facts, edges)

    with pytest.raises(ProjectionContractError, match="duplicate owner plus fact_ref"):
        ProjectionViewV1.rebuild((*facts, facts[0]), edges)
    with pytest.raises(ProjectionContractError, match="duplicate edge"):
        ProjectionViewV1.rebuild(facts, (*edges, edges[0]))

    duplicate_ref = OwnerFactV1(
        schema_version="1",
        owner=facts[0].owner,
        fact_type=facts[0].fact_type,
        fact_ref=facts[0].fact_ref,
        payload_sha256="9" * 64,
        payload_schema_version=facts[0].payload_schema_version,
        owner_sequence=facts[0].owner_sequence + 1,
    )
    with pytest.raises(ProjectionContractError, match="duplicate owner plus fact_ref"):
        ProjectionViewV1.rebuild((*facts, duplicate_ref), edges)

    duplicate_serialized_fact = copy.deepcopy(view.to_dict())
    duplicate_serialized_fact["facts"].append(
        copy.deepcopy(duplicate_serialized_fact["facts"][0])
    )
    with pytest.raises(ProjectionContractError, match="duplicate owner plus fact_ref"):
        ProjectionViewV1.from_dict(duplicate_serialized_fact)

    duplicate_serialized_edge = copy.deepcopy(view.to_dict())
    duplicate_serialized_edge["edges"].append(
        copy.deepcopy(duplicate_serialized_edge["edges"][0])
    )
    with pytest.raises(ProjectionContractError, match="duplicate edge"):
        ProjectionViewV1.from_dict(duplicate_serialized_edge)


def test_edge_reporter_rejects_malformed_hash_before_view_diagnostics() -> None:
    facts, edges = _complete_fixture()
    serialized = edges[0].to_dict()
    serialized["reporter"]["payload_sha256"] = "not-a-sha256"

    with pytest.raises(ProjectionContractError, match="64 lowercase"):
        ExplicitEdgeV1.from_dict(serialized)

    view = ProjectionViewV1.rebuild(facts, edges)
    wrong_version = copy.deepcopy(view.to_dict())
    wrong_version["schema_version"] = "2"
    with pytest.raises(ProjectionContractError, match="version is unsupported"):
        ProjectionViewV1.from_dict(wrong_version)
