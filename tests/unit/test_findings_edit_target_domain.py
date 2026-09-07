"""Schema/source identity alignment for the retained API-only Findings failure."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.evidence.models import EvidencePack, _evidence_item_from_artifact_payload
from src.mod_agent.evidence.requirement_coverage import resolve_requirement_coverage
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
    _projection_schema_failure,
    requirement_findings_response_schema,
)
from tests.unit.test_api_semantic_consumption import _api_item
from tests.unit.test_requirement_coverage import _materialized_and_retrieved

FIXTURE = Path(__file__).parents[1] / "fixtures/evaluation/findings_api_only_actual_001.json"


def _recorded():
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # The Actual supplied source observations, not an already-admitted semantic pack.
    pack = EvidencePack(query=value["request"], readiness="partial", can_generate_patch=False,
        items=tuple(_evidence_item_from_artifact_payload(item) for item in value["retrieved_pack"]["items"]))
    return value, pack


def test_saved_api_only_response_fits_old_schema_but_not_current_edit_identity():
    value, pack = _recorded()
    assert _projection_schema_failure(value["saved_response"], schema=value["saved_response_schema"], path="$") is None
    with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_EDIT_TARGET_IDENTITY_INVALID"):
        resolve_requirement_coverage(query=value["request"], materialized_projection=value["materialized_projection"],
            items=pack.items, findings=value["saved_response"])


def test_api_only_production_schema_keeps_references_and_allows_missing_without_edit_hints():
    value, pack = _recorded()
    requests = []
    def complete(_role, payload, schema):
        requests.append(deepcopy(schema))
        properties = schema["properties"]["findings"]["items"]["properties"]
        assert properties["evidence_ids"]["items"]["enum"] == [item.evidence_id for item in pack.items]
        assert properties["edit_target_evidence_ids"]["maxItems"] == 0
        assert _projection_schema_failure(value["saved_response"], schema=schema, path="$") is not None
        return {"findings": [{"relation_index": index, "relationship": "missing", "evidence_ids": [],
            "edit_target_evidence_ids": [], "unresolved_gaps": ["No target-source modification location is supplied."]}
            for index in properties["relation_index"]["enum"]]}
    provider = StructuredModelRequirementCoverageProvider(complete)
    findings = provider.findings(materialized_projection=value["materialized_projection"], retrieved_pack=pack, request=value["request"])
    assert len(requests) == 1
    assert all(not row["edit_target_evidence_ids"] for row in findings["findings"])
    _, _, allowed, _, _ = resolve_requirement_coverage(query=value["request"],
        materialized_projection=value["materialized_projection"], items=pack.items, findings=findings)
    assert allowed is False


def test_mixed_source_schema_preserves_full_global_target_pool_for_multiple_relations(tmp_path):
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    api = _api_item()
    combined = replace(retrieved, items=(*retrieved.items, api))
    captured = []
    def complete(_role, payload, schema):
        properties = schema["properties"]["findings"]["items"]["properties"]
        captured.append(properties)
        expected = [item.evidence_id for item in retrieved.items]
        assert properties["edit_target_evidence_ids"]["items"]["enum"] == expected
        assert properties["evidence_ids"]["items"]["enum"] == [*expected, api.evidence_id]
        assert len(payload["relations"]) > 1
        return {"findings": [{"relation_index": index, "relationship": "missing", "evidence_ids": [],
            "edit_target_evidence_ids": [], "unresolved_gaps": ["Offline schema test does not supply semantic findings."]}
            for index in properties["relation_index"]["enum"]]}
    StructuredModelRequirementCoverageProvider(complete).findings(materialized_projection=materialized,
        retrieved_pack=combined, request=feature["user_request"])
    assert len(captured) == 1


def test_direct_schema_call_compatibility_and_explicit_domain_validation():
    legacy = requirement_findings_response_schema(relation_indexes=[1], evidence_ids=["source", "api"])
    assert legacy["properties"]["findings"]["items"]["properties"]["edit_target_evidence_ids"]["items"]["enum"] == ["source", "api"]
    with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_EDIT_TARGET_SCHEMA_INVALID"):
        requirement_findings_response_schema(relation_indexes=[1], evidence_ids=["source"], edit_target_evidence_ids=["outside"])
