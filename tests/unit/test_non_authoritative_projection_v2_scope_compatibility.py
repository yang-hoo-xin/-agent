from __future__ import annotations

import json
from typing import Any

import pytest

from src.mod_agent.product_execution import (
    ProductBuildCompletionV1,
    ProductExecutionBlockerV1,
    ProductExecutionContractError,
    ProductExecutionFactsV1,
    ProductExecutionResultV1,
    _ProductExecutionResultIdentityV1,
    empty_product_validation_facts,
    project_product_execution_result,
)
from src.non_authoritative_projection.contracts import ProjectionContractError
from src.non_authoritative_projection.contracts_v2 import (
    ArtifactRefV2,
    FactRefV2,
    OwnerFactV2,
    ProjectionViewV2,
)


_SCOPE_VALUES = (
    pytest.param(" leading_scope", True, id="leading-space"),
    pytest.param("trailing_scope ", True, id="trailing-space"),
    pytest.param("\tleading_scope", True, id="leading-tab"),
    pytest.param("trailing_scope\t", True, id="trailing-tab"),
    pytest.param("scope\tvalue", True, id="internal-tab"),
    pytest.param("\nleading_scope", True, id="leading-newline"),
    pytest.param("trailing_scope\n", True, id="trailing-newline"),
    pytest.param("scope\nvalue", True, id="internal-newline"),
    pytest.param("运行_Δ_日本語", True, id="unicode-text"),
    pytest.param("\u3000scope\u00a0", True, id="unicode-whitespace-wrapped"),
    pytest.param("", False, id="empty"),
    pytest.param("   ", False, id="space-only"),
    pytest.param("\t\t", False, id="tab-only"),
    pytest.param("\n\n", False, id="newline-only"),
    pytest.param(
        "\u3000\u00a0\u2003",
        False,
        id="unicode-whitespace-only",
    ),
    pytest.param(True, False, id="bool"),
    pytest.param(b"scope", False, id="bytes"),
    pytest.param(None, False, id="none"),
    pytest.param(1, False, id="integer"),
)


def _owner_result_payload() -> dict[str, Any]:
    result = project_product_execution_result(
        ProductExecutionFactsV1(
            request=_ProductExecutionResultIdentityV1(
                run_id="run_scope_baseline",
                request_id="request_scope_baseline",
                requested_completion_scope="compile_only",
            ),
            feature_id=None,
            terminal_node=None,
            store_attempts=(),
            outputs=(),
            effect_events=(),
            validation_facts=empty_product_validation_facts(),
            blockers=(
                ProductExecutionBlockerV1(
                    contract_version="1",
                    owner="platform",
                    stage="graph_start",
                    code="SCOPE_COMPATIBILITY_FIXTURE",
                    message="Fixture stops before ProductExecution starts.",
                    source_node="graph_start",
                ),
            ),
            variant_result=ProductBuildCompletionV1(
                contract_version="1",
                build_result_ref=None,
                workflow_checkpoint_ref=None,
                build_status="not_reached",
                claims_real_build_success=None,
            ),
            failure_stage="graph_start",
        ),
        validate_request=False,
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result
    return result.to_dict()


def _artifact_ref() -> ArtifactRefV2:
    return ArtifactRefV2(
        feature_id="feature_scope_compatibility",
        artifact_type="evidence_pack",
        path=(
            "C:/store/features/feature_scope_compatibility/r/"
            "evidence_pack/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json"
        ),
        artifact_hash="a" * 64,
    )


def _parse_owner_scope(
    scope_field: str,
    value: object,
) -> ProductExecutionResultV1 | None:
    payload = _owner_result_payload()
    payload[scope_field] = value
    try:
        return ProductExecutionResultV1.from_dict(payload)
    except ProductExecutionContractError:
        return None


def _parse_v2_scope(
    scope_field: str,
    value: object,
) -> FactRefV2 | None:
    payload = FactRefV2(
        owner="product_execution",
        fact_type="product_execution_output_v1",
        run_id="run_scope_baseline",
        request_id="request_scope_baseline",
        owner_sequence=0,
        artifact_ref=_artifact_ref(),
    ).to_dict()
    payload[scope_field] = value
    try:
        return FactRefV2.from_dict(payload)
    except ProjectionContractError:
        return None


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _assert_lossless_canonical_roundtrips(
    scope_field: str,
    value: str,
    owner_result: ProductExecutionResultV1,
    fact_ref: FactRefV2,
) -> None:
    owner_bytes = _canonical_bytes(owner_result.to_dict())
    owner_payload = json.loads(owner_bytes.decode("utf-8"))
    assert owner_payload[scope_field] == value
    owner_roundtrip = ProductExecutionResultV1.from_dict(owner_payload)
    assert getattr(owner_roundtrip, scope_field) == value
    assert _canonical_bytes(owner_roundtrip.to_dict()) == owner_bytes

    fact_bytes = fact_ref.canonical_bytes()
    fact_payload = json.loads(fact_bytes.decode("utf-8"))
    assert fact_payload[scope_field] == value
    fact_roundtrip = FactRefV2.from_dict(fact_payload)
    assert getattr(fact_roundtrip, scope_field) == value
    assert fact_roundtrip.canonical_bytes() == fact_bytes

    owner_fact = OwnerFactV2(
        schema_version="2",
        fact=fact_ref,
        payload_sha256=fact_ref.artifact_ref.artifact_hash,
        payload_schema_version="1.0",
    )
    owner_fact_bytes = _canonical_bytes(owner_fact.to_dict())
    owner_fact_payload = json.loads(owner_fact_bytes.decode("utf-8"))
    assert owner_fact_payload["fact"][scope_field] == value
    owner_fact_roundtrip = OwnerFactV2.from_dict(owner_fact_payload)
    assert getattr(owner_fact_roundtrip.ref, scope_field) == value
    assert _canonical_bytes(owner_fact_roundtrip.to_dict()) == owner_fact_bytes

    view = ProjectionViewV2.rebuild((owner_fact,), ())
    view_bytes = view.canonical_bytes()
    view_payload = json.loads(view_bytes.decode("utf-8"))
    assert view_payload["facts"][0]["fact"][scope_field] == value
    view_roundtrip = ProjectionViewV2.from_dict(view_payload)
    assert getattr(view_roundtrip.facts[0].ref, scope_field) == value
    assert view_roundtrip.canonical_bytes() == view_bytes


@pytest.mark.parametrize("scope_field", ("run_id", "request_id"))
@pytest.mark.parametrize(("value", "expected_acceptance"), _SCOPE_VALUES)
def test_product_execution_scope_acceptance_matches_owner_and_is_lossless(
    scope_field: str,
    value: object,
    expected_acceptance: bool,
) -> None:
    owner_result = _parse_owner_scope(scope_field, value)
    fact_ref = _parse_v2_scope(scope_field, value)

    owner_accepted = owner_result is not None
    v2_accepted = fact_ref is not None
    assert owner_accepted is expected_acceptance
    assert v2_accepted is owner_accepted

    if not owner_accepted:
        return
    assert owner_result is not None
    assert fact_ref is not None
    assert type(value) is str
    assert getattr(owner_result, scope_field) == value
    assert getattr(fact_ref, scope_field) == value
    _assert_lossless_canonical_roundtrips(
        scope_field,
        value,
        owner_result,
        fact_ref,
    )


@pytest.mark.parametrize(
    "value",
    (
        " leading_feature",
        "trailing_feature ",
        "feature\tpart",
        "feature\npart",
        "\u3000feature\u00a0",
    ),
)
def test_product_execution_scope_rule_does_not_relax_artifact_ref_text(
    value: str,
) -> None:
    with pytest.raises(ProjectionContractError, match="exact non-empty string"):
        ArtifactRefV2(
            feature_id=value,
            artifact_type="evidence_pack",
            path="C:/store/features/strict/r/evidence_pack/a.json",
            artifact_hash="a" * 64,
        )
