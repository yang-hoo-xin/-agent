from __future__ import annotations

import copy
import json

import pytest

import src.non_authoritative_projection.contracts as projection_contracts
from src.mod_agent.artifacts import ArtifactEnvelope, ArtifactRef
from src.mod_agent.product_execution import ProductExecutionOutputV1
from src.non_authoritative_projection import (
    DIAGNOSTIC_CODES_V1,
    OWNER_FACT_ADMISSION_V1,
    OWNER_FACT_ADMISSION_VERSION_V1,
    RELATION_DIRECTIONS_V1,
    RELATIONS_V1,
    EdgeReporterV1,
    ExplicitEdgeV1,
    FactRefV1,
    OwnerFactV1,
    ProjectionContractError,
    ProjectionViewV1,
)


def _owner_contracts(
    suffix: str,
    *,
    sequence: int,
) -> tuple[ProductExecutionOutputV1, ArtifactEnvelope]:
    artifact_ref = ArtifactRef(
        feature_id="feature_projection_001",
        artifact_type="evidence_pack",
        path=f"C:/store/features/feature_projection_001/r/evidence_pack/{suffix}.json",
        artifact_hash=suffix * 64,
    )
    output = ProductExecutionOutputV1(
        contract_version="1",
        sequence=sequence,
        phase="evidence",
        repair_attempt=0,
        node_name="retrieve_evidence",
        artifact_role="evidence_pack",
        artifact_ref=artifact_ref,
    )
    envelope = ArtifactEnvelope(
        schema_version="1.0",
        artifact_type=artifact_ref.artifact_type,
        feature_id=artifact_ref.feature_id,
        producer_stage="evidence_retrieval",
        status="success",
        data={"owner_contract_fixture": suffix},
        artifact_hash=artifact_ref.artifact_hash,
        inputs={"upstream_artifacts": []},
        blockers=[],
        trace_refs=[],
    )
    return output, envelope


def _assert_output_envelope_binding(
    output: ProductExecutionOutputV1,
    envelope: ArtifactEnvelope,
) -> None:
    assert output.contract_version == "1"
    assert envelope.schema_version == "1.0"
    assert output.artifact_ref.artifact_type == envelope.artifact_type
    assert output.artifact_ref.feature_id == envelope.feature_id
    assert output.artifact_ref.artifact_hash == envelope.artifact_hash


def _product_output_fact(
    output: ProductExecutionOutputV1,
    envelope: ArtifactEnvelope,
) -> OwnerFactV1:
    _assert_output_envelope_binding(output, envelope)
    return OwnerFactV1(
        schema_version="1",
        owner="product_execution",
        fact_type="product_execution_output_v1",
        fact_ref=output.artifact_ref.path,
        payload_sha256=output.artifact_ref.artifact_hash,
        payload_schema_version=envelope.schema_version,
        owner_sequence=output.sequence,
    )


def _artifact_revision_fact(
    output: ProductExecutionOutputV1,
    envelope: ArtifactEnvelope,
) -> OwnerFactV1:
    _assert_output_envelope_binding(output, envelope)
    return OwnerFactV1(
        schema_version="1",
        owner="artifact_store",
        fact_type="artifact_revision_v1",
        fact_ref=output.artifact_ref.path,
        payload_sha256=envelope.artifact_hash,
        payload_schema_version=envelope.schema_version,
        owner_sequence=None,
    )


def _facts() -> tuple[OwnerFactV1, OwnerFactV1, OwnerFactV1]:
    first_output, first_envelope = _owner_contracts("a", sequence=4)
    second_output, second_envelope = _owner_contracts("b", sequence=5)
    return (
        _product_output_fact(first_output, first_envelope),
        _product_output_fact(second_output, second_envelope),
        _artifact_revision_fact(second_output, second_envelope),
    )


def _edge(
    relation: str,
    source: OwnerFactV1,
    target: OwnerFactV1,
    *,
    reporter_fact: FactRefV1 | None = None,
    reporter_payload_sha256: str | None = None,
    reporter_owner_sequence: int | None = None,
) -> ExplicitEdgeV1:
    assert source.owner_sequence is not None
    return ExplicitEdgeV1(
        schema_version="1",
        relation=relation,
        source=source.ref,
        target=target.ref,
        reporter=EdgeReporterV1(
            fact=(source.ref if reporter_fact is None else reporter_fact),
            payload_sha256=(
                source.payload_sha256
                if reporter_payload_sha256 is None
                else reporter_payload_sha256
            ),
            owner_sequence=(
                source.owner_sequence
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


def test_owner_fact_admission_is_finite_versioned_and_source_bound() -> None:
    product_output, envelope = _owner_contracts("a", sequence=4)
    product_fact = _product_output_fact(product_output, envelope)
    artifact_fact = _artifact_revision_fact(product_output, envelope)

    assert OWNER_FACT_ADMISSION_VERSION_V1 == "owner_fact_admission_v1"
    assert OWNER_FACT_ADMISSION_V1 == (
        ("artifact_store", "artifact_revision_v1", "1.0", "unavailable"),
        (
            "product_execution",
            "product_execution_output_v1",
            "1.0",
            "required",
        ),
    )
    assert product_fact.fact_ref == product_output.artifact_ref.path
    assert product_fact.payload_sha256 == product_output.artifact_ref.artifact_hash
    assert product_fact.payload_schema_version == envelope.schema_version
    assert product_fact.owner_sequence == product_output.sequence
    assert artifact_fact.fact_ref == product_output.artifact_ref.path
    assert artifact_fact.payload_sha256 == envelope.artifact_hash
    assert artifact_fact.payload_schema_version == envelope.schema_version
    assert artifact_fact.owner_sequence is None
    assert OwnerFactV1.from_dict(product_fact.to_dict()) == product_fact
    assert OwnerFactV1.from_dict(artifact_fact.to_dict()) == artifact_fact


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("owner", "projection"),
        ("owner", "actual_execution"),
        ("fact_type", "final_status"),
        ("fact_type", "product_claim_v1"),
        ("fact_type", "artifact_revision_v1"),
        ("payload_schema_version", "1"),
        ("owner_sequence", None),
    ),
)
def test_arbitrary_owner_unregistered_pair_and_status_claim_wrappers_are_rejected(
    field: str,
    value: object,
) -> None:
    product_fact, _second, _artifact = _facts()
    serialized = product_fact.to_dict()
    serialized[field] = value

    with pytest.raises(ProjectionContractError):
        OwnerFactV1.from_dict(serialized)


def test_public_admission_table_rebinding_cannot_register_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        projection_contracts,
        "OWNER_FACT_ADMISSION_V1",
        (*OWNER_FACT_ADMISSION_V1, ("projection", "final_status", "1", "required")),
    )

    with pytest.raises(ProjectionContractError, match="pair is not admitted"):
        OwnerFactV1(
            schema_version="1",
            owner="projection",
            fact_type="final_status",
            fact_ref="projection://status",
            payload_sha256="a" * 64,
            payload_schema_version="1",
            owner_sequence=0,
        )


@pytest.mark.parametrize("extra_field", ("status", "claim", "final_status"))
def test_owner_fact_cannot_add_business_status_or_claim_fields(
    extra_field: str,
) -> None:
    product_fact, _second, _artifact = _facts()
    serialized = product_fact.to_dict()
    serialized[extra_field] = "caller_reported"

    with pytest.raises(ProjectionContractError, match="fields or field order"):
        OwnerFactV1.from_dict(serialized)


def test_nonreporting_artifact_revision_cannot_invent_owner_sequence() -> None:
    _product, _second, artifact_fact = _facts()
    serialized = artifact_fact.to_dict()
    serialized["owner_sequence"] = 0

    with pytest.raises(ProjectionContractError, match="must be null"):
        OwnerFactV1.from_dict(serialized)


@pytest.mark.parametrize("owner", ("projection", "actual_execution", "build"))
def test_fact_ref_rejects_unadmitted_owner(owner: str) -> None:
    with pytest.raises(ProjectionContractError, match="owner is not admitted"):
        FactRefV1(owner=owner, fact_ref="owner://fact")


def test_contract_strict_roundtrip_and_exact_owner_fact_shape() -> None:
    product_fact, second_fact, artifact_fact = _facts()
    edge = _edge("references", product_fact, second_fact)
    view = ProjectionViewV1.rebuild(
        (artifact_fact, second_fact, product_fact),
        (edge,),
    )
    serialized = json.loads(view.canonical_bytes().decode("utf-8"))

    assert ProjectionViewV1.from_dict(serialized) == view
    assert view.canonical_sha256() == ProjectionViewV1.from_dict(
        serialized
    ).canonical_sha256()
    assert tuple(product_fact.to_dict()) == (
        "schema_version",
        "owner",
        "fact_type",
        "fact_ref",
        "payload_sha256",
        "payload_schema_version",
        "owner_sequence",
    )
    assert "payload" not in product_fact.to_dict()


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
    product_fact, second_fact, artifact_fact = _facts()
    view = ProjectionViewV1.rebuild(
        (product_fact, second_fact, artifact_fact),
        (_edge("references", product_fact, second_fact),),
    )
    serialized = copy.deepcopy(view.to_dict())
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
        ("owner_sequence", True),
    ),
)
def test_owner_fact_rejects_wrong_version_hash_and_scalar_shape(
    field: str,
    value: object,
) -> None:
    product_fact, _second, _artifact = _facts()
    serialized = product_fact.to_dict()
    serialized[field] = value

    with pytest.raises(ProjectionContractError):
        OwnerFactV1.from_dict(serialized)


def test_rebuild_canonical_bytes_ignore_input_collection_order_only() -> None:
    product_fact, second_fact, artifact_fact = _facts()
    edges = (
        _edge("references", product_fact, second_fact),
        _edge("derived_from", product_fact, artifact_fact),
    )
    forward = ProjectionViewV1.rebuild(
        (product_fact, second_fact, artifact_fact), edges
    )
    reversed_inputs = ProjectionViewV1.rebuild(
        (artifact_fact, second_fact, product_fact), tuple(reversed(edges))
    )

    assert forward == reversed_inputs
    assert forward.canonical_bytes() == reversed_inputs.canonical_bytes()
    assert forward.canonical_sha256() == reversed_inputs.canonical_sha256()
    assert [fact.owner_sequence for fact in forward.facts] == [None, 4, 5]

    noncanonical_facts = copy.deepcopy(forward.to_dict())
    noncanonical_facts["facts"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV1.from_dict(noncanonical_facts)

    noncanonical_edges = copy.deepcopy(forward.to_dict())
    noncanonical_edges["edges"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV1.from_dict(noncanonical_edges)


def test_relation_enum_and_reporter_source_directions_are_finite_and_exact() -> None:
    assert RELATION_DIRECTIONS_V1 == (
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
    assert RELATIONS_V1 == tuple(
        relation for relation, _direction in RELATION_DIRECTIONS_V1
    )
    product_fact, second_fact, _artifact_fact = _facts()
    invalid = _edge("references", product_fact, second_fact).to_dict()
    invalid["relation"] = "inferred_from_timestamp"

    with pytest.raises(ProjectionContractError, match="relation is unsupported"):
        ExplicitEdgeV1.from_dict(invalid)


def test_reporter_fact_must_equal_source_and_third_owner_reporting_is_rejected() -> None:
    product_fact, second_fact, artifact_fact = _facts()

    with pytest.raises(ProjectionContractError, match="must equal its source"):
        _edge(
            "references",
            product_fact,
            artifact_fact,
            reporter_fact=second_fact.ref,
        )


def test_nonreporting_artifact_revision_cannot_be_an_edge_source() -> None:
    product_fact, _second_fact, artifact_fact = _facts()
    assert artifact_fact.owner_sequence is None
    with pytest.raises(ProjectionContractError, match="sequence-bound edge"):
        ExplicitEdgeV1(
            schema_version="1",
            relation="references",
            source=artifact_fact.ref,
            target=product_fact.ref,
            reporter=EdgeReporterV1(
                fact=artifact_fact.ref,
                payload_sha256=artifact_fact.payload_sha256,
                owner_sequence=0,
            ),
        )


def test_different_owner_conflict_is_parallel_and_has_no_adjudication_fields() -> None:
    product_fact, _second_fact, artifact_fact = _facts()
    view = ProjectionViewV1.rebuild(
        (product_fact, artifact_fact),
        (_edge("conflicts_with", product_fact, artifact_fact),),
    )

    assert {fact.ref for fact in view.facts} == {
        product_fact.ref,
        artifact_fact.ref,
    }
    assert [item.code for item in view.diagnostics] == ["explicit_conflict"]
    assert view.diagnostics[0].primary_fact == product_fact.ref
    assert view.diagnostics[0].related_fact == artifact_fact.ref
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


def test_explicit_edge_endpoints_and_source_reporter_binding_are_verified() -> None:
    product_fact, second_fact, artifact_fact = _facts()
    good = _edge("caused_by", product_fact, artifact_fact)

    assert ProjectionViewV1.rebuild(
        (product_fact, second_fact, artifact_fact), (good,)
    ).diagnostics == ()
    assert good.to_dict()["source"] == product_fact.ref.to_dict()
    assert good.to_dict()["target"] == artifact_fact.ref.to_dict()
    assert good.to_dict()["reporter"] == {
        "fact": product_fact.ref.to_dict(),
        "payload_sha256": product_fact.payload_sha256,
        "owner_sequence": product_fact.owner_sequence,
    }

    missing_target = ProjectionViewV1.rebuild((product_fact,), (good,))
    missing_source_and_reporter = ProjectionViewV1.rebuild(
        (artifact_fact,), (good,)
    )
    mismatch = ProjectionViewV1.rebuild(
        (product_fact, artifact_fact),
        (
            _edge(
                "caused_by",
                product_fact,
                artifact_fact,
                reporter_payload_sha256="0" * 64,
                reporter_owner_sequence=product_fact.owner_sequence + 1,
            ),
        ),
    )

    assert [item.code for item in missing_target.diagnostics] == [
        "missing_target_fact"
    ]
    assert {item.code for item in missing_source_and_reporter.diagnostics} == {
        "missing_source_fact",
        "missing_reporter_fact",
    }
    assert {item.code for item in mismatch.diagnostics} == {
        "reporter_payload_sha256_mismatch",
        "reporter_owner_sequence_mismatch",
    }


def test_diagnostics_are_derived_strict_unique_and_lossless() -> None:
    product_fact, _second_fact, artifact_fact = _facts()
    edge = _edge(
        "references",
        product_fact,
        artifact_fact,
        reporter_payload_sha256="0" * 64,
        reporter_owner_sequence=product_fact.owner_sequence + 1,
    )
    view = ProjectionViewV1.rebuild((product_fact, artifact_fact), (edge,))
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
    product_fact, second_fact, artifact_fact = _facts()
    edge = _edge("references", product_fact, second_fact)
    facts = (product_fact, second_fact, artifact_fact)
    view = ProjectionViewV1.rebuild(facts, (edge,))

    with pytest.raises(ProjectionContractError, match="duplicate owner plus fact_ref"):
        ProjectionViewV1.rebuild((*facts, product_fact), (edge,))
    with pytest.raises(ProjectionContractError, match="duplicate edge"):
        ProjectionViewV1.rebuild(facts, (edge, edge))

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
    product_fact, second_fact, artifact_fact = _facts()
    edge = _edge("references", product_fact, second_fact)
    serialized = edge.to_dict()
    serialized["reporter"]["payload_sha256"] = "not-a-sha256"

    with pytest.raises(ProjectionContractError, match="64 lowercase"):
        ExplicitEdgeV1.from_dict(serialized)

    view = ProjectionViewV1.rebuild(
        (product_fact, second_fact, artifact_fact), (edge,)
    )
    wrong_version = copy.deepcopy(view.to_dict())
    wrong_version["schema_version"] = "2"
    with pytest.raises(ProjectionContractError, match="version is unsupported"):
        ProjectionViewV1.from_dict(wrong_version)
