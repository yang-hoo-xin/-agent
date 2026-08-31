"""Pure post-return Thin Lineage projection for ProductExecution V1 results.

The adapter copies only the owner-issued scope, output sequence, ArtifactRef,
and matching output-readback schema needed by Projection V2.  It never reads or
writes ArtifactStore and does not observe ProductExecution while it is running.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.product_execution import (
    ProductExecutionContractError,
    ProductExecutionOutputV1,
    ProductExecutionResultV1,
)
from src.non_authoritative_projection.contracts import ProjectionContractError
from src.non_authoritative_projection.contracts_v2 import (
    PROJECTION_SCHEMA_VERSION_V2,
    ArtifactRefV2,
    EdgeReporterV2,
    ExplicitEdgeV2,
    FactRefV2,
    OwnerFactV2,
    ProjectionViewV2,
)


_READBACK_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "feature_id",
        "producer_stage",
        "status",
        "data",
        "artifact_hash",
        "inputs",
        "blockers",
        "trace_refs",
    }
)
_READBACK_TEXT_FIELDS = (
    "artifact_type",
    "feature_id",
    "producer_stage",
    "status",
    "artifact_hash",
)


def _strictly_replay(result: ProductExecutionResultV1) -> None:
    if not isinstance(result, ProductExecutionResultV1):
        raise ProjectionContractError(
            "Thin Lineage V2 input must be ProductExecutionResultV1."
        )
    try:
        replayed = ProductExecutionResultV1.from_dict(result.to_dict())
    except ProductExecutionContractError as exc:
        raise ProjectionContractError(
            "Thin Lineage V2 requires a strictly replayable ProductExecutionResultV1."
        ) from exc
    if replayed != result:
        raise ProjectionContractError(
            "Thin Lineage V2 input changed during ProductExecution strict replay."
        )


def _readback_payload(
    result: ProductExecutionResultV1,
) -> tuple[Mapping[str, Any], ...] | None:
    details = tuple(
        detail
        for detail in result.validation_facts.details
        if detail.detail_kind == "output_readback"
    )
    if len(details) != 1:
        raise ProjectionContractError(
            "Thin Lineage V2 requires one exact output_readback detail."
        )
    status = result.validation_facts.output_readback_status
    payload = details[0].payload
    if status == "passed":
        if type(payload) is not list or len(payload) != len(result.outputs):
            raise ProjectionContractError(
                "Thin Lineage V2 output readback does not match output count."
            )
        if any(type(item) is not dict for item in payload):
            raise ProjectionContractError(
                "Thin Lineage V2 output readback items must be exact objects."
            )
        return tuple(payload)
    if status == "failed":
        return None
    if status == "not_applicable":
        if payload is not None:
            raise ProjectionContractError(
                "Thin Lineage V2 unavailable output readback must be null."
            )
        return None
    raise ProjectionContractError(
        "Thin Lineage V2 output readback status is unsupported."
    )


def _readback_schema_version(
    envelope: Mapping[str, Any],
    output: ProductExecutionOutputV1,
) -> str:
    if set(envelope) != _READBACK_ENVELOPE_FIELDS:
        raise ProjectionContractError(
            "Thin Lineage V2 output readback envelope fields changed."
        )
    schema_version = envelope["schema_version"]
    if type(schema_version) is not str or any(
        type(envelope[field]) is not str for field in _READBACK_TEXT_FIELDS
    ):
        raise ProjectionContractError(
            "Thin Lineage V2 output readback envelope text fields changed shape."
        )
    data = envelope["data"]
    inputs = envelope["inputs"]
    blockers = envelope["blockers"]
    trace_refs = envelope["trace_refs"]
    if (
        type(data) is not dict
        or type(inputs) is not dict
        or type(blockers) is not list
        or any(type(item) is not dict for item in blockers)
        or type(trace_refs) is not list
        or any(type(item) is not str for item in trace_refs)
    ):
        raise ProjectionContractError(
            "Thin Lineage V2 output readback envelope collection fields changed shape."
        )
    artifact_ref = output.artifact_ref
    if (
        envelope["feature_id"] != artifact_ref.feature_id
        or envelope["artifact_type"] != artifact_ref.artifact_type
        or envelope["artifact_hash"] != artifact_ref.artifact_hash
    ):
        raise ProjectionContractError(
            "Thin Lineage V2 output readback changed its exact Artifact identity."
        )
    return schema_version


def _artifact_ref(ref: ArtifactRef) -> ArtifactRefV2:
    return ArtifactRefV2(
        feature_id=ref.feature_id,
        artifact_type=ref.artifact_type,
        path=ref.path,
        artifact_hash=ref.artifact_hash,
    )


def _occurrence_ref(
    result: ProductExecutionResultV1,
    output: ProductExecutionOutputV1,
    artifact_ref: ArtifactRefV2,
) -> FactRefV2:
    return FactRefV2(
        owner="product_execution",
        fact_type="product_execution_output_v1",
        run_id=result.run_id,
        request_id=result.request_id,
        owner_sequence=output.sequence,
        artifact_ref=artifact_ref,
    )


def _revision_ref(artifact_ref: ArtifactRefV2) -> FactRefV2:
    return FactRefV2(
        owner="artifact_store",
        fact_type="artifact_revision_v1",
        run_id=None,
        request_id=None,
        owner_sequence=None,
        artifact_ref=artifact_ref,
    )


def _references_edge(
    source: FactRefV2,
    target: FactRefV2,
    output: ProductExecutionOutputV1,
) -> ExplicitEdgeV2:
    return ExplicitEdgeV2(
        schema_version=PROJECTION_SCHEMA_VERSION_V2,
        relation="references",
        source=source,
        target=target,
        reporter=EdgeReporterV2(
            fact=source,
            payload_sha256=output.artifact_ref.artifact_hash,
            owner_sequence=output.sequence,
        ),
    )


def project_product_execution_results_v2(
    results: Iterable[ProductExecutionResultV1],
) -> ProjectionViewV2:
    """Project completed ProductExecution results into one read-only V2 view.

    A passed readback admits one occurrence fact and one shared revision fact
    for each output.  A failed readback supplies no schema and therefore admits
    no facts; its exact output references remain as edges so the V2 contract
    reports item-level missing-source, missing-target, and missing-reporter
    diagnostics without inventing a schema or changing the owner result.
    """

    selected_results = tuple(results)
    occurrence_facts: list[OwnerFactV2] = []
    revision_facts: dict[ArtifactRefV2, OwnerFactV2] = {}
    edges: list[ExplicitEdgeV2] = []

    for result in selected_results:
        _strictly_replay(result)
        readback = _readback_payload(result)
        output_readbacks: Iterable[
            tuple[ProductExecutionOutputV1, Mapping[str, Any] | None]
        ]
        if readback is None:
            output_readbacks = ((output, None) for output in result.outputs)
        else:
            output_readbacks = zip(result.outputs, readback, strict=True)
        for output, envelope in output_readbacks:
            artifact_ref = _artifact_ref(output.artifact_ref)
            occurrence_ref = _occurrence_ref(result, output, artifact_ref)
            revision_ref = _revision_ref(artifact_ref)
            edges.append(_references_edge(occurrence_ref, revision_ref, output))

            if envelope is None:
                continue
            payload_schema_version = _readback_schema_version(envelope, output)
            occurrence_facts.append(
                OwnerFactV2(
                    schema_version=PROJECTION_SCHEMA_VERSION_V2,
                    fact=occurrence_ref,
                    payload_sha256=artifact_ref.artifact_hash,
                    payload_schema_version=payload_schema_version,
                )
            )
            revision_fact = OwnerFactV2(
                schema_version=PROJECTION_SCHEMA_VERSION_V2,
                fact=revision_ref,
                payload_sha256=artifact_ref.artifact_hash,
                payload_schema_version=payload_schema_version,
            )
            previous = revision_facts.setdefault(artifact_ref, revision_fact)
            if previous != revision_fact:
                raise ProjectionContractError(
                    "Thin Lineage V2 received conflicting facts for one Artifact revision."
                )

    return ProjectionViewV2.rebuild(
        (*occurrence_facts, *revision_facts.values()),
        edges,
    )


def project_product_execution_result_v2(
    result: ProductExecutionResultV1,
) -> ProjectionViewV2:
    """Project one completed ProductExecution result through the plural path."""

    return project_product_execution_results_v2((result,))
