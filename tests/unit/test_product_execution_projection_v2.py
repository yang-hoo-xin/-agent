from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.mod_agent.artifacts import (
    ArtifactEnvelope,
    ArtifactRef,
    ArtifactStore,
    ArtifactWriteResult,
)
from src.mod_agent.product_execution import (
    ProductBuildCompletionV1,
    ProductExecutionBlockerV1,
    ProductExecutionFactsV1,
    ProductExecutionOutputV1,
    ProductExecutionResultV1,
    ProductExecutionValidationDetailV1,
    ProductExecutionValidationFactsV1,
    _ProductExecutionResultIdentityV1,
    project_product_execution_result,
)
from src.mod_agent.product_executor import _ProductStoreRecorder
from src.non_authoritative_projection.contracts_v2 import (
    ArtifactRefV2,
    EdgeReporterV2,
    ExplicitEdgeV2,
    FactRefV2,
    OwnerFactV2,
    ProjectionViewV2,
)


FEATURE_ID = "feature_projection_v2_product_001"


def _artifact_ref(role: str) -> ArtifactRef:
    artifact_hash = hashlib.sha256(role.encode("utf-8")).hexdigest()
    return ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type=role,
        path=(
            f"C:/store/features/{FEATURE_ID}/r/{role}/"
            f"{artifact_hash[:32]}.json"
        ),
        artifact_hash=artifact_hash,
    )


def _committed_result(
    ref: ArtifactRef,
    *,
    commit_started: bool,
) -> ArtifactWriteResult:
    return ArtifactWriteResult.from_dict(
        {
            "outcome": "committed",
            "feature_id": ref.feature_id,
            "artifact_type": ref.artifact_type,
            "artifact_hash": ref.artifact_hash,
            "artifact_ref": {
                "feature_id": ref.feature_id,
                "artifact_type": ref.artifact_type,
                "path": ref.path,
                "artifact_hash": ref.artifact_hash,
            },
            "revision_path": ref.path,
            "latest_alias_path": (
                f"C:/store/features/{FEATURE_ID}/{ref.artifact_type}.json"
            ),
            "pending_marker_path": (
                f"C:/store/features/{FEATURE_ID}/p/{ref.artifact_hash}.json"
            ),
            "commit_started": commit_started,
            "revision_state": "valid",
            "latest_alias_state": "matches_identity",
            "pending_marker_state": "absent",
            "failure_stage": None,
            "failure_class": None,
            "failure_message": None,
            "recovery_available": False,
            "recovery_authorized": False,
        }
    )


def _readback_envelope(output: ProductExecutionOutputV1) -> dict[str, object]:
    data: dict[str, object] = {}
    if output.artifact_role == "repair_plan":
        data = {
            "retry_count": 1,
            "retry_budget": 2,
            "retry_budget_remaining": 2,
            "retry_exhausted": False,
            "allowed_next_stage": "generate_patch_proposal",
            "blockers": [],
        }
    return ArtifactEnvelope(
        schema_version="1.0",
        artifact_type=output.artifact_ref.artifact_type,
        feature_id=output.artifact_ref.feature_id,
        producer_stage=output.node_name,
        status="success",
        data=data,
        artifact_hash=output.artifact_ref.artifact_hash,
        inputs={"upstream_artifacts": []},
        blockers=[],
        trace_refs=[],
    ).to_dict()


def _strict_result_with_reused_patch_revision(
    tmp_path: Path,
) -> ProductExecutionResultV1:
    recorder = _ProductStoreRecorder(ArtifactStore(tmp_path / "store"))
    roles = (
        "request_planning_report",
        "mod_planning_brief",
        "feature_spec",
        "evidence_pack",
        "implementation_plan",
        "patch_proposal",
        "critic_assessment",
        "proposal_review",
        "repair_plan",
        "patch_proposal",
    )
    shared_patch_ref = _artifact_ref("patch_proposal")
    patch_occurrence = 0
    for role in roles:
        if role == "patch_proposal":
            patch_occurrence += 1
            ref = shared_patch_ref
            commit_started = patch_occurrence == 1
        else:
            ref = _artifact_ref(role)
            commit_started = True
        recorder._record(
            _committed_result(ref, commit_started=commit_started),
            payload={"retry_count": 1} if role == "repair_plan" else {},
        )

    outputs = tuple(recorder.outputs)
    readback = [_readback_envelope(output) for output in outputs]
    validation = ProductExecutionValidationFactsV1(
        contract_version="1",
        output_readback_status="passed",
        canonical_source_status="not_applicable",
        compiled_artifact_status="not_applicable",
        source_change_status="not_applicable",
        completion_classification_status="not_applicable",
        failure_class=None,
        failure_message=None,
        details=(
            ProductExecutionValidationDetailV1(
                contract_version="1",
                detail_kind="output_readback",
                payload=readback,
            ),
            ProductExecutionValidationDetailV1(
                contract_version="1",
                detail_kind="canonical_source",
                payload=None,
            ),
            ProductExecutionValidationDetailV1(
                contract_version="1",
                detail_kind="compiled_artifact",
                payload=None,
            ),
            ProductExecutionValidationDetailV1(
                contract_version="1",
                detail_kind="source_change",
                payload=None,
            ),
            ProductExecutionValidationDetailV1(
                contract_version="1",
                detail_kind="completion_classification",
                payload=None,
            ),
        ),
    )
    result = project_product_execution_result(
        ProductExecutionFactsV1(
            request=_ProductExecutionResultIdentityV1(
                run_id="run_projection_v2_product_001",
                request_id="request_projection_v2_product_001",
                requested_completion_scope="compile_only",
            ),
            feature_id=FEATURE_ID,
            terminal_node=None,
            store_attempts=tuple(recorder.attempts),
            outputs=outputs,
            effect_events=(),
            validation_facts=validation,
            blockers=(
                ProductExecutionBlockerV1(
                    contract_version="1",
                    owner="platform",
                    stage="review_proposal_execution",
                    code="PRODUCT_PROJECTION_FIXTURE_STOP",
                    message="Fixture stops after the second committed Patch output.",
                    source_node="review_proposal",
                ),
            ),
            variant_result=ProductBuildCompletionV1(
                contract_version="1",
                build_result_ref=None,
                workflow_checkpoint_ref=None,
                build_status="not_reached",
                claims_real_build_success=None,
            ),
            failure_stage="review_proposal_execution",
        ),
        validate_request=False,
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result
    return result


def _projection_artifact_ref(ref: ArtifactRef) -> ArtifactRefV2:
    return ArtifactRefV2(
        feature_id=ref.feature_id,
        artifact_type=ref.artifact_type,
        path=ref.path,
        artifact_hash=ref.artifact_hash,
    )


def _output_fact(
    result: ProductExecutionResultV1,
    output: ProductExecutionOutputV1,
    envelope: dict[str, object],
) -> OwnerFactV2:
    assert output in result.outputs
    assert envelope["feature_id"] == output.artifact_ref.feature_id
    assert envelope["artifact_type"] == output.artifact_ref.artifact_type
    assert envelope["artifact_hash"] == output.artifact_ref.artifact_hash
    artifact_ref = _projection_artifact_ref(output.artifact_ref)
    return OwnerFactV2(
        schema_version="2",
        fact=FactRefV2(
            owner="product_execution",
            fact_type="product_execution_output_v1",
            run_id=result.run_id,
            request_id=result.request_id,
            owner_sequence=output.sequence,
            artifact_ref=artifact_ref,
        ),
        payload_sha256=output.artifact_ref.artifact_hash,
        payload_schema_version=str(envelope["schema_version"]),
    )


def _revision_fact(
    output: ProductExecutionOutputV1,
    envelope: dict[str, object],
) -> OwnerFactV2:
    assert envelope["artifact_hash"] == output.artifact_ref.artifact_hash
    artifact_ref = _projection_artifact_ref(output.artifact_ref)
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
        payload_sha256=output.artifact_ref.artifact_hash,
        payload_schema_version=str(envelope["schema_version"]),
    )


def _references(source: OwnerFactV2, target: OwnerFactV2) -> ExplicitEdgeV2:
    sequence = source.ref.owner_sequence
    assert sequence is not None
    return ExplicitEdgeV2(
        schema_version="2",
        relation="references",
        source=source.ref,
        target=target.ref,
        reporter=EdgeReporterV2(
            fact=source.ref,
            payload_sha256=source.payload_sha256,
            owner_sequence=sequence,
        ),
    )


def test_strict_product_result_reused_revision_projects_two_lossless_occurrences(
    tmp_path: Path,
) -> None:
    result = _strict_result_with_reused_patch_revision(tmp_path)
    result_before = json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    patch_outputs = tuple(
        output
        for output in result.outputs
        if output.artifact_role == "patch_proposal"
    )
    assert len(patch_outputs) == 2
    assert patch_outputs[0].sequence != patch_outputs[1].sequence
    assert patch_outputs[0].artifact_ref == patch_outputs[1].artifact_ref

    readback = result.validation_facts.details[0].payload
    assert isinstance(readback, list)
    envelope_by_sequence = {
        output.sequence: envelope
        for output, envelope in zip(result.outputs, readback, strict=True)
    }
    first = _output_fact(
        result,
        patch_outputs[0],
        envelope_by_sequence[patch_outputs[0].sequence],
    )
    second = _output_fact(
        result,
        patch_outputs[1],
        envelope_by_sequence[patch_outputs[1].sequence],
    )
    revision = _revision_fact(
        patch_outputs[0],
        envelope_by_sequence[patch_outputs[0].sequence],
    )
    first_envelope = envelope_by_sequence[patch_outputs[0].sequence]
    output_projection = patch_outputs[0].to_dict()
    occurrence_record_sha256 = hashlib.sha256(
        json.dumps(
            output_projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert "owner" not in output_projection
    assert "fact_type" not in output_projection
    assert "owner" not in patch_outputs[0].artifact_ref.__dict__
    assert "fact_type" not in patch_outputs[0].artifact_ref.__dict__
    assert "owner" not in first_envelope
    assert "fact_type" not in first_envelope
    assert first.ref.owner == "product_execution"
    assert first.ref.fact_type == "product_execution_output_v1"
    assert first.ref.run_id == result.run_id
    assert first.ref.request_id == result.request_id
    assert first.ref.owner_sequence == patch_outputs[0].sequence
    assert first.ref.artifact_ref.to_dict() == {
        "feature_id": patch_outputs[0].artifact_ref.feature_id,
        "artifact_type": patch_outputs[0].artifact_ref.artifact_type,
        "path": patch_outputs[0].artifact_ref.path,
        "artifact_hash": patch_outputs[0].artifact_ref.artifact_hash,
    }
    assert first.payload_schema_version == first_envelope["schema_version"]
    assert first.payload_sha256 == patch_outputs[0].artifact_ref.artifact_hash
    assert first.payload_sha256 != occurrence_record_sha256
    edges = (_references(first, revision), _references(second, revision))

    view = ProjectionViewV2.rebuild(
        (revision, second, first),
        tuple(reversed(edges)),
    )

    assert view.diagnostics == ()
    assert len(view.facts) == 3
    assert len(view.edges) == 2
    assert first.ref != second.ref
    assert first.ref.run_id == second.ref.run_id == result.run_id
    assert first.ref.request_id == second.ref.request_id == result.request_id
    assert first.ref.artifact_ref == second.ref.artifact_ref == revision.ref.artifact_ref
    assert {edge.source.owner_sequence for edge in view.edges} == {
        patch_outputs[0].sequence,
        patch_outputs[1].sequence,
    }
    assert {edge.target for edge in view.edges} == {revision.ref}
    assert all(edge.reporter.fact == edge.source for edge in view.edges)
    assert all(
        edge.reporter.payload_sha256 == edge.source.artifact_ref.artifact_hash
        for edge in view.edges
    )
    assert json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") == result_before
