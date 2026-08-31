from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.product_execution import ProductExecutionResultV1
from src.non_authoritative_projection.contracts import ProjectionContractError
from src.non_authoritative_projection.contracts_v2 import (
    EdgeReporterV2,
    ExplicitEdgeV2,
    OwnerFactV2,
    ProjectionViewV2,
)
from src.observability.thin_lineage_projection_v2 import (
    project_product_execution_result_v2,
    project_product_execution_results_v2,
)
from tests.unit.test_non_authoritative_projection_boundary import (
    MOD_AGENT_ROOT,
    PROJECT_ROOT,
    _imported_names,
)
from tests.unit.test_product_execution_projection_v2 import (
    _strict_result_with_reused_patch_revision,
)


_OWNER_LEGAL_SCOPE_VALUES = (
    " leading_scope",
    "trailing_scope ",
    "\tleading_scope",
    "trailing_scope\t",
    "\nleading_scope",
    "trailing_scope\n",
    "\u3000运行_Δ_日本語\u00a0",
)


def _canonical_result_bytes(result: ProductExecutionResultV1) -> bytes:
    return json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def _result_in_scope(
    result: ProductExecutionResultV1,
    *,
    run_id: str,
    request_id: str,
) -> ProductExecutionResultV1:
    serialized = copy.deepcopy(result.to_dict())
    serialized["run_id"] = run_id
    serialized["request_id"] = request_id
    return ProductExecutionResultV1.from_dict(serialized)


def _failed_readback_result(
    result: ProductExecutionResultV1,
) -> ProductExecutionResultV1:
    serialized = copy.deepcopy(result.to_dict())
    validation = serialized["validation_facts"]
    partial_payload = [copy.deepcopy(validation["details"][0]["payload"][0])]
    validation["output_readback_status"] = "failed"
    validation["failure_class"] = "OSError"
    validation["failure_message"] = "readback unavailable"
    validation["details"][0]["payload"] = partial_payload
    serialized["failure_stage"] = "post_execution_validation"
    return ProductExecutionResultV1.from_dict(serialized)


def _facts_by_owner(
    view: ProjectionViewV2,
    owner: str,
) -> tuple[OwnerFactV2, ...]:
    return tuple(fact for fact in view.facts if fact.ref.owner == owner)


def test_post_return_projection_preserves_reused_revision_occurrences_without_store_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _strict_result_with_reused_patch_revision(tmp_path)
    result_before = _canonical_result_bytes(result)
    assert not (tmp_path / "store").exists()

    def forbidden_store_access(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Thin Lineage projection accessed ArtifactStore.")

    for method_name in ("read", "write", "write_with_result"):
        monkeypatch.setattr(ArtifactStore, method_name, forbidden_store_access)

    view = project_product_execution_result_v2(result)

    assert _canonical_result_bytes(result) == result_before
    assert not (tmp_path / "store").exists()
    assert view.diagnostics == ()
    assert len(view.edges) == len(result.outputs)
    product_facts = _facts_by_owner(view, "product_execution")
    revision_facts = _facts_by_owner(view, "artifact_store")
    assert len(product_facts) == len(result.outputs)
    assert len(revision_facts) == len({output.artifact_ref for output in result.outputs})

    patch_outputs = tuple(
        output
        for output in result.outputs
        if output.artifact_role == "patch_proposal"
    )
    assert len(patch_outputs) == 2
    assert patch_outputs[0].sequence != patch_outputs[1].sequence
    assert patch_outputs[0].artifact_ref == patch_outputs[1].artifact_ref
    patch_occurrences = tuple(
        fact
        for fact in product_facts
        if fact.ref.artifact_ref.artifact_type == "patch_proposal"
    )
    patch_revisions = tuple(
        fact
        for fact in revision_facts
        if fact.ref.artifact_ref.artifact_type == "patch_proposal"
    )
    patch_edges = tuple(
        edge
        for edge in view.edges
        if edge.source.artifact_ref.artifact_type == "patch_proposal"
    )

    assert len(patch_occurrences) == 2
    assert len(patch_revisions) == 1
    assert len(patch_edges) == 2
    assert {fact.ref.owner_sequence for fact in patch_occurrences} == {
        patch_outputs[0].sequence,
        patch_outputs[1].sequence,
    }
    assert {fact.ref.artifact_ref for fact in patch_occurrences} == {
        patch_revisions[0].ref.artifact_ref
    }
    assert {edge.target for edge in patch_edges} == {patch_revisions[0].ref}
    assert all(edge.relation == "references" for edge in patch_edges)
    assert all(edge.reporter.fact == edge.source for edge in patch_edges)
    assert all(
        edge.reporter.owner_sequence == edge.source.owner_sequence
        for edge in patch_edges
    )
    assert all(
        edge.reporter.payload_sha256 == edge.source.artifact_ref.artifact_hash
        for edge in patch_edges
    )

    first_output_record_sha256 = hashlib.sha256(
        json.dumps(
            patch_outputs[0].to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert patch_occurrences[0].payload_sha256 == patch_outputs[0].artifact_ref.artifact_hash
    assert patch_occurrences[0].payload_sha256 != first_output_record_sha256


def test_cross_run_projection_and_readback_key_order_have_deterministic_bytes(
    tmp_path: Path,
) -> None:
    first = _strict_result_with_reused_patch_revision(tmp_path)
    second = _result_in_scope(
        first,
        run_id="run_projection_v2_product_002",
        request_id="request_projection_v2_product_002",
    )
    reordered_serialized = copy.deepcopy(first.to_dict())
    readback = reordered_serialized["validation_facts"]["details"][0]["payload"]
    reordered_serialized["validation_facts"]["details"][0]["payload"] = [
        dict(reversed(tuple(envelope.items()))) for envelope in readback
    ]
    reordered_first = ProductExecutionResultV1.from_dict(reordered_serialized)

    forward = project_product_execution_results_v2((first, second))
    reversed_results = project_product_execution_results_v2((second, first))
    reordered = project_product_execution_results_v2((reordered_first, second))

    assert forward == reversed_results == reordered
    assert forward.canonical_bytes() == reversed_results.canonical_bytes()
    assert forward.canonical_bytes() == reordered.canonical_bytes()
    assert forward.canonical_sha256() == reversed_results.canonical_sha256()
    assert ProjectionViewV2.from_dict(
        json.loads(forward.canonical_bytes().decode("utf-8"))
    ) == forward

    first_output = first.outputs[0]
    scoped = tuple(
        fact
        for fact in _facts_by_owner(forward, "product_execution")
        if fact.ref.owner_sequence == first_output.sequence
        and fact.ref.artifact_ref.artifact_hash
        == first_output.artifact_ref.artifact_hash
    )
    assert {(fact.ref.run_id, fact.ref.request_id) for fact in scoped} == {
        (first.run_id, first.request_id),
        (second.run_id, second.request_id),
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_field",
        "unexpected_field",
        "wrong_collection_shape",
        "wrong_blocker_item",
        "wrong_trace_ref_item",
    ),
)
def test_passed_readback_requires_the_exact_envelope_schema(
    tmp_path: Path,
    mutation: str,
) -> None:
    result = _strict_result_with_reused_patch_revision(tmp_path)
    serialized = copy.deepcopy(result.to_dict())
    envelope = serialized["validation_facts"]["details"][0]["payload"][0]
    if mutation == "missing_field":
        envelope.pop("trace_refs")
    elif mutation == "unexpected_field":
        envelope["unexpected"] = None
    elif mutation == "wrong_collection_shape":
        envelope["blockers"] = {}
    elif mutation == "wrong_blocker_item":
        envelope["blockers"] = ["not-an-object"]
    else:
        envelope["trace_refs"] = [123]
    owner_replayable = ProductExecutionResultV1.from_dict(serialized)

    with pytest.raises(ProjectionContractError, match="readback envelope"):
        project_product_execution_result_v2(owner_replayable)


def test_passed_readback_does_not_default_an_unadmitted_payload_schema(
    tmp_path: Path,
) -> None:
    result = _strict_result_with_reused_patch_revision(tmp_path)
    serialized = copy.deepcopy(result.to_dict())
    serialized["validation_facts"]["details"][0]["payload"][0][
        "schema_version"
    ] = "2.0"
    owner_replayable = ProductExecutionResultV1.from_dict(serialized)

    with pytest.raises(ProjectionContractError, match="payload schema version"):
        project_product_execution_result_v2(owner_replayable)


def test_owner_legal_scope_is_strictly_replayed_and_preserved_by_adapter(
    tmp_path: Path,
) -> None:
    baseline = _strict_result_with_reused_patch_revision(tmp_path)

    for scope_field in ("run_id", "request_id"):
        for scope_value in _OWNER_LEGAL_SCOPE_VALUES:
            scope = {
                "run_id": "run_projection_v2_product_001",
                "request_id": "request_projection_v2_product_001",
            }
            scope[scope_field] = scope_value
            result = _result_in_scope(baseline, **scope)
            result_before = _canonical_result_bytes(result)

            replayed_result = ProductExecutionResultV1.from_dict(result.to_dict())
            assert replayed_result == result
            assert getattr(replayed_result, scope_field) == scope_value

            view = project_product_execution_result_v2(result)
            replayed_view = project_product_execution_result_v2(replayed_result)
            expected_scope = (result.run_id, result.request_id)
            product_facts = _facts_by_owner(view, "product_execution")

            assert product_facts
            assert {
                (fact.ref.run_id, fact.ref.request_id) for fact in product_facts
            } == {expected_scope}
            assert all(
                (edge.source.run_id, edge.source.request_id) == expected_scope
                for edge in view.edges
            )
            assert all(
                (
                    edge.reporter.fact.run_id,
                    edge.reporter.fact.request_id,
                )
                == expected_scope
                for edge in view.edges
            )

            canonical_bytes = view.canonical_bytes()
            canonical_payload = json.loads(canonical_bytes.decode("utf-8"))
            serialized_occurrences = tuple(
                fact
                for fact in canonical_payload["facts"]
                if fact["fact"]["owner"] == "product_execution"
            )
            assert serialized_occurrences
            assert all(
                fact["fact"][scope_field] == scope_value
                for fact in serialized_occurrences
            )
            canonical_roundtrip = ProjectionViewV2.from_dict(canonical_payload)
            assert canonical_roundtrip == view == replayed_view
            assert canonical_roundtrip.canonical_bytes() == canonical_bytes
            assert replayed_view.canonical_bytes() == canonical_bytes
            assert _canonical_result_bytes(result) == result_before


def test_failed_readback_keeps_exact_edges_and_reports_only_missing_items(
    tmp_path: Path,
) -> None:
    original = _strict_result_with_reused_patch_revision(tmp_path)
    result = _failed_readback_result(original)
    result_before = _canonical_result_bytes(result)

    view = project_product_execution_result_v2(result)

    assert view.facts == ()
    assert len(view.edges) == len(result.outputs)
    assert len(view.diagnostics) == len(result.outputs) * 3
    assert {item.code for item in view.diagnostics} == {
        "missing_source_fact",
        "missing_target_fact",
        "missing_reporter_fact",
    }
    assert all(edge.relation == "references" for edge in view.edges)
    assert all(edge.reporter.fact == edge.source for edge in view.edges)
    assert all(edge.source.owner == "product_execution" for edge in view.edges)
    assert all(
        edge.source.fact_type == "product_execution_output_v1"
        for edge in view.edges
    )
    assert all(edge.target.owner == "artifact_store" for edge in view.edges)
    assert all(edge.target.fact_type == "artifact_revision_v1" for edge in view.edges)
    assert all(edge.target.run_id is None for edge in view.edges)
    assert all(edge.target.request_id is None for edge in view.edges)
    assert all(edge.target.owner_sequence is None for edge in view.edges)
    for edge in view.edges:
        diagnostics = tuple(
            item
            for item in view.diagnostics
            if item.edge_sha256 == edge.canonical_sha256()
        )
        assert {(item.code, item.primary_fact) for item in diagnostics} == {
            ("missing_source_fact", edge.source),
            ("missing_target_fact", edge.target),
            ("missing_reporter_fact", edge.reporter.fact),
        }
        assert all(item.related_fact is None for item in diagnostics)
        assert all(item.fact_payload_sha256 is None for item in diagnostics)
        assert all(item.reporter_payload_sha256 is None for item in diagnostics)
        assert all(item.fact_owner_sequence is None for item in diagnostics)
        assert all(item.reporter_owner_sequence is None for item in diagnostics)
    assert {
        (
            edge.source.run_id,
            edge.source.request_id,
            edge.source.owner_sequence,
            edge.source.artifact_ref.feature_id,
            edge.source.artifact_ref.artifact_type,
            edge.source.artifact_ref.path,
            edge.source.artifact_ref.artifact_hash,
        )
        for edge in view.edges
    } == {
        (
            result.run_id,
            result.request_id,
            output.sequence,
            output.artifact_ref.feature_id,
            output.artifact_ref.artifact_type,
            output.artifact_ref.path,
            output.artifact_ref.artifact_hash,
        )
        for output in result.outputs
    }
    assert _canonical_result_bytes(result) == result_before


def test_projection_facts_support_explicit_conflict_without_status_or_adjudication(
    tmp_path: Path,
) -> None:
    result = _strict_result_with_reused_patch_revision(tmp_path)
    view = project_product_execution_result_v2(result)
    source = _facts_by_owner(view, "product_execution")[0]
    target = next(
        fact
        for fact in _facts_by_owner(view, "artifact_store")
        if fact.ref.artifact_ref == source.ref.artifact_ref
    )
    sequence = source.ref.owner_sequence
    assert sequence is not None
    conflict_edge = ExplicitEdgeV2(
        schema_version="2",
        relation="conflicts_with",
        source=source.ref,
        target=target.ref,
        reporter=EdgeReporterV2(
            fact=source.ref,
            payload_sha256=source.payload_sha256,
            owner_sequence=sequence,
        ),
    )

    conflicted = ProjectionViewV2.rebuild(
        view.facts,
        (*view.edges, conflict_edge),
    )

    assert {fact.ref for fact in conflicted.facts} == {
        fact.ref for fact in view.facts
    }
    assert [item.code for item in conflicted.diagnostics] == ["explicit_conflict"]
    assert _all_keys(conflicted.to_dict()).isdisjoint(
        {
            "status",
            "platform_status",
            "execution_disposition",
            "failure",
            "failure_stage",
            "blocker",
            "blockers",
            "claim",
            "claims",
            "retry",
            "action",
            "winner",
            "authority",
        }
    )


def test_duplicate_exact_result_is_rejected_instead_of_normalized(
    tmp_path: Path,
) -> None:
    result = _strict_result_with_reused_patch_revision(tmp_path)

    with pytest.raises(ProjectionContractError, match="duplicate complete fact identity"):
        project_product_execution_results_v2((result, result))


def test_mod_agent_has_no_reverse_dependency_on_thin_lineage_projection_v2() -> None:
    target = "src.observability.thin_lineage_projection_v2"
    violations: list[str] = []
    for path in sorted(MOD_AGENT_ROOT.rglob("*.py")):
        imported = _imported_names(path)
        if any(name == target or name.startswith(target + ".") for name in imported):
            violations.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert violations == []
