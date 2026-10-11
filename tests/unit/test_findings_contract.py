"""Model contract and correction feedback preserve evidence without inventing support."""

from copy import deepcopy

import pytest

from src.libs.llm.ollama_llm import _schema_constraint_loss
from src.mod_agent.evidence import (
    StructuredModelRequirementCoverageProvider,
    build_requirement_coverage_pack,
)
from src.mod_agent.evidence.requirement_coverage_provider import _projection_schema_failure
from src.mod_agent.evidence.requirement_coverage_provider import (
    FINDINGS_CONTRACT_VERSION,
    PREVIOUS_FINDINGS_CONTRACT_VERSION,
    requirement_findings_response_schema,
)
from tests.unit.test_requirement_coverage import _materialized_and_retrieved, _positive_findings


@pytest.mark.parametrize("damage", ["gaps", "missing", "non_change", "subset", "unknown", "duplicate"])
def test_rejected_fields_relations_and_actual_rule_reach_correction(tmp_path, damage):
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    invalid = _positive_findings(materialized, retrieved)
    invalid["findings"] = invalid["findings"][:2]
    row = invalid["findings"][0]
    if damage == "gaps":
        row["unresolved_gaps"] = ["Current input API is not known."]
    elif damage == "missing":
        row["relationship"] = "missing"
        row["unresolved_gaps"] = ["Current input API is not known."]
    elif damage == "non_change":
        row = invalid["findings"][1]
        row["edit_target_evidence_ids"] = row["evidence_ids"][:]
    elif damage == "subset":
        row["edit_target_evidence_ids"] = invalid["findings"][1]["evidence_ids"][:]
    elif damage == "unknown":
        row["edit_target_evidence_ids"] = ["not-a-retrieved-id"]
    else:
        row["edit_target_evidence_ids"] *= 2
    before = deepcopy(invalid)
    calls = []
    def complete(role, payload, schema):
        calls.append((role, deepcopy(payload), schema))
        if role == "requirement_findings":
            return invalid
        assert payload["previous_findings"] == before
        assert payload["rejection_diagnostic"]["rejected_fields_source"] == "previous_findings"
        assert payload["relations"] == calls[0][1]["relations"]
        assert payload["rejection_diagnostic"]["diagnostic"]
        if damage in {"gaps", "missing", "non_change", "subset"}:
            diagnostic = payload["rejection_diagnostic"]["validator_rejection"]["diagnostic"]
            assert diagnostic["violated_rules"]
            assert diagnostic["edit_target_evidence_ids"] == row["edit_target_evidence_ids"]
            assert diagnostic["unresolved_gaps"] == row["unresolved_gaps"]
        # A genuine unresolved gap stays unresolved; the caller, not the adapter,
        # returns this independent structured response.
        revised = deepcopy(before)
        for finding in revised["findings"]:
            finding.update(relationship="missing", edit_target_evidence_ids=[],
                           unresolved_gaps=["Current API remains unverified."])
        return revised
    provider = StructuredModelRequirementCoverageProvider(complete)
    findings = provider.findings(materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    assert invalid == before
    assert [call[0] for call in calls] == ["requirement_findings", "requirement_findings_correction"]
    assert calls[0][1]["findings_contract_version"] == FINDINGS_CONTRACT_VERSION
    if damage in {"unknown", "duplicate"}:
        assert _projection_schema_failure(before, schema=calls[0][2], path="$") is not None
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=materialized,
                                          retrieved_pack=retrieved, findings=findings)
    assert pack.can_generate_patch is False
    assert pack.requirement_coverage["edit_target_evidence_ids"] == []
    assert findings["findings"][0]["evidence_ids"] == before["findings"][0]["evidence_ids"]


@pytest.mark.parametrize("relationship", ["missing", "support"])
def test_partial_current_evidence_is_preserved_without_edit_authority(tmp_path, relationship):
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    response = _positive_findings(materialized, retrieved)
    response["findings"] = response["findings"][:2]
    response["findings"][0].update(relationship=relationship, edit_target_evidence_ids=[],
                                 unresolved_gaps=["Current input API unknown."])
    def complete(role, payload, schema):
        assert role == "requirement_findings"
        assert _projection_schema_failure(response, schema=schema, path="$") is None
        assert any("new behavior not existing" in rule for rule in payload["rules"])
        return response
    findings = StructuredModelRequirementCoverageProvider(complete).findings(
        materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    assert findings["findings"][:2] == response["findings"]
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=materialized,
                                          retrieved_pack=retrieved, findings=findings)
    assert pack.can_generate_patch is False
    assert pack.requirement_coverage["edit_target_evidence_ids"] == []


def test_new_requested_behavior_does_not_need_to_exist_before_planning(tmp_path):
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    response = _positive_findings(materialized, retrieved)
    response["findings"] = response["findings"][:2]
    def complete(role, payload, schema):
        assert role == "requirement_findings"
        assert _projection_schema_failure(response, schema=schema, path="$") is None
        # The model sees current implementation evidence and separate post-change
        # acceptance; no expected new source or implementation is supplied.
        assert all(any(parent["required_before_patch"] for parent in relation["parent_requirements"])
                   for relation in payload["relations"])
        return response
    findings = StructuredModelRequirementCoverageProvider(complete).findings(
        materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=materialized,
                                          retrieved_pack=retrieved, findings=findings)
    assert pack.can_generate_patch is True
    assert findings["findings"][-1]["relationship"] == "missing"
    assert findings["findings"][-1]["unresolved_gaps"] == []


def test_current_findings_wire_schema_keeps_common_fields_without_mixed_oneof(tmp_path):
    _, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    relation_indexes = [1, 2]
    evidence_ids = [item.evidence_id for item in retrieved.items]
    editable_ids = evidence_ids[:1]
    current = requirement_findings_response_schema(
        relation_indexes=relation_indexes, evidence_ids=evidence_ids,
        edit_target_evidence_ids=editable_ids,
        findings_contract_version=FINDINGS_CONTRACT_VERSION,
        change_relation_indexes=[1])
    item = current["properties"]["findings"]["items"]
    assert FINDINGS_CONTRACT_VERSION == "3"
    assert set(item) == {"type", "properties", "required", "additionalProperties"}
    assert item["required"] == ["relation_index", "relationship", "evidence_ids",
                                "edit_target_evidence_ids", "unresolved_gaps"]
    assert item["properties"]["evidence_ids"]["items"]["enum"] == evidence_ids
    assert item["properties"]["edit_target_evidence_ids"]["items"]["enum"] == editable_ids
    previous = requirement_findings_response_schema(
        relation_indexes=relation_indexes, evidence_ids=evidence_ids,
        edit_target_evidence_ids=editable_ids,
        findings_contract_version=PREVIOUS_FINDINGS_CONTRACT_VERSION,
        change_relation_indexes=[1])
    old_item = previous["properties"]["findings"]["items"]
    assert "oneOf" in old_item and "properties" in old_item and "required" in old_item
    assert _schema_constraint_loss(previous) == {
        "json_path": "$.properties.findings.items",
        "combinator": "oneOf",
        "ignored_sibling_keywords": ["additionalProperties", "properties", "required", "type"],
    }
    assert _schema_constraint_loss(current) is None
