"""Empty evidence stays empty in native schemas and coverage admission."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft7Validator

from src.libs.llm import ChatResponse
from src.mod_agent.evidence import EvidencePack, build_requirement_coverage_pack
from src.mod_agent.evidence.requirement_coverage import (
    LEGACY_REQUIREMENT_COVERAGE_SCHEMA_VERSION,
    PREVIOUS_REQUIREMENT_COVERAGE_SCHEMA_VERSION,
    REQUIREMENT_COVERAGE_SCHEMA_VERSION,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.evidence.requirement_coverage_provider import (
    EMPTY_EVIDENCE_POLICY,
    FINDINGS_CONTRACT_VERSION,
    LEGACY_FINDINGS_CONTRACT_VERSION,
    PREVIOUS_FINDINGS_CONTRACT_VERSION,
    StructuredModelRequirementCoverageProvider,
    _projection_schema_failure,
    requirement_findings_response_schema,
)
from src.mod_agent.requirement_coverage_model import request_requirement_coverage_model
from tests.unit.test_requirement_coverage import _feature_data, _projection


def _assert_no_empty_enum(value):
    if isinstance(value, dict):
        assert value.get("enum") != [], "Native schema conversion rejects an empty enum."
        for nested in value.values():
            _assert_no_empty_enum(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_empty_enum(nested)


@pytest.mark.parametrize("coverage_version", [
    LEGACY_REQUIREMENT_COVERAGE_SCHEMA_VERSION,
    PREVIOUS_REQUIREMENT_COVERAGE_SCHEMA_VERSION,
    REQUIREMENT_COVERAGE_SCHEMA_VERSION,
])
@pytest.mark.parametrize("contract_version", [
    LEGACY_FINDINGS_CONTRACT_VERSION,
    PREVIOUS_FINDINGS_CONTRACT_VERSION,
    FINDINGS_CONTRACT_VERSION,
])
def test_empty_evidence_domain_accepts_only_empty_id_arrays(coverage_version, contract_version):
    schema = requirement_findings_response_schema(
        relation_indexes=[1], evidence_ids=[], edit_target_evidence_ids=[],
        coverage_schema_version=coverage_version, findings_contract_version=contract_version,
        change_relation_indexes=[1],
    )
    _assert_no_empty_enum(schema)
    Draft7Validator.check_schema(schema)
    row = {"relation_index": 1, "relationship": "missing", "evidence_ids": [],
           "unresolved_gaps": ["Current source evidence is absent."]}
    if coverage_version == REQUIREMENT_COVERAGE_SCHEMA_VERSION:
        row["edit_target_evidence_ids"] = []
    response = {"findings": [row]}
    assert Draft7Validator(schema).is_valid(response)
    assert _projection_schema_failure(response, schema=schema, path="$") is None
    for field in ("evidence_ids", "edit_target_evidence_ids"):
        if field not in row:
            continue
        for invalid_ids in (["invented"], [None], "", None):
            invalid = deepcopy(response)
            invalid["findings"][0][field] = invalid_ids
            assert not Draft7Validator(schema).is_valid(invalid)
            assert _projection_schema_failure(invalid, schema=schema, path="$") is not None


@pytest.mark.parametrize("editable_ids", [[], ["observed-source"]])
def test_nonempty_evidence_keeps_exact_membership_and_empty_edit_domain(editable_ids):
    schema = requirement_findings_response_schema(
        relation_indexes=[1], evidence_ids=["observed-source", "observed-api"],
        edit_target_evidence_ids=editable_ids, findings_contract_version=FINDINGS_CONTRACT_VERSION,
        change_relation_indexes=[1],
    )
    _assert_no_empty_enum(schema)
    properties = schema["properties"]["findings"]["items"]["properties"]
    assert properties["evidence_ids"] == {
        "type": "array", "uniqueItems": True,
        "items": {"type": "string", "enum": ["observed-source", "observed-api"]},
    }
    response = {"findings": [{"relation_index": 1, "relationship": "support",
                             "evidence_ids": ["observed-source"],
                             "edit_target_evidence_ids": editable_ids, "unresolved_gaps": []}]}
    assert Draft7Validator(schema).is_valid(response)
    for field, invalid_ids in (("evidence_ids", ["invented"]),
                               ("evidence_ids", ["observed-source", "observed-source"]),
                               ("edit_target_evidence_ids", ["observed-api"])):
        invalid = deepcopy(response)
        invalid["findings"][0][field] = invalid_ids
        assert not Draft7Validator(schema).is_valid(invalid)
        assert _projection_schema_failure(invalid, schema=schema, path="$") is not None


def test_empty_retrieval_reaches_findings_wire_and_returns_missing_without_patch_authority():
    feature = _feature_data()
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature, request=feature["user_request"], projection=_projection(),
    )
    retrieved = EvidencePack.empty(query=feature["user_request"], reason="No source observations.")
    requests = []

    class RecordingModel:
        def chat(self, messages, **kwargs):
            payload = json.loads(messages[1].content)
            requests.append(payload)
            assert payload["source_observations"] == []
            _assert_no_empty_enum(kwargs["response_format"])
            response = {"findings": [
                {"relation_index": row["relation_index"], "relationship": "missing",
                 "evidence_ids": [], "edit_target_evidence_ids": [],
                 "unresolved_gaps": ["Current source evidence is absent."]}
                for row in payload["relations"]
            ]}
            assert Draft7Validator(kwargs["response_format"]).is_valid(response)
            return ChatResponse(content=json.dumps(response), model="recorded-regression")

    def complete(role, payload, schema):
        assert role == "requirement_findings"
        response, _ = request_requirement_coverage_model(
            llm=RecordingModel(), payload=payload, schema=schema,
            max_output_tokens=1024, capture_provider_request=False,
        )
        return json.loads(response.content)

    findings = StructuredModelRequirementCoverageProvider(complete).findings(
        materialized_projection=materialized, retrieved_pack=retrieved,
        request=feature["user_request"],
    )
    assert len(requests) == 1
    assert all(row["relationship"] == "missing" and row["evidence_ids"] == []
               and row["edit_target_evidence_ids"] == [] for row in findings["findings"])
    pack = build_requirement_coverage_pack(query=feature["user_request"],
                                          materialized_projection=materialized,
                                          retrieved_pack=retrieved, findings=findings)
    assert pack.can_generate_patch is False
    assert pack.requirement_coverage["edit_target_evidence_ids"] == []
    assert pack.items == ()


@pytest.mark.parametrize("relationship", ["support", "conflict"])
def test_empty_domain_policy_excludes_uncitable_relationships(relationship):
    response = {"findings": [{"relation_index": 1, "relationship": relationship,
        "evidence_ids": [], "edit_target_evidence_ids": [], "unresolved_gaps": []}]}
    arguments = dict(relation_indexes=[1], evidence_ids=[], edit_target_evidence_ids=[],
        findings_contract_version=FINDINGS_CONTRACT_VERSION)
    historical = requirement_findings_response_schema(**arguments)
    assert Draft7Validator(historical).is_valid(response)
    current = requirement_findings_response_schema(**arguments, empty_evidence_policy=EMPTY_EVIDENCE_POLICY)
    assert not Draft7Validator(current).is_valid(response)
    assert _projection_schema_failure(response, schema=current, path="$") is not None
    response["findings"][0]["relationship"] = "missing"
    assert not Draft7Validator(current).is_valid(response)
    response["findings"][0]["unresolved_gaps"] = ["Current plugin entry implementation has not been observed."]
    assert Draft7Validator(current).is_valid(response)


def test_empty_support_correction_explains_actual_citation_boundary_without_adding_evidence():
    feature = _feature_data()
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature, request=feature["user_request"], projection=_projection())
    retrieved = EvidencePack.empty(query=feature["user_request"], reason="No matches")
    calls = []
    def complete(role, payload, schema):
        calls.append(role)
        assert payload["empty_evidence_policy"] == EMPTY_EVIDENCE_POLICY
        if role == "requirement_findings_correction":
            diagnostic = payload["rejection_diagnostic"]["empty_evidence_domain"]
            assert diagnostic["available_evidence_ids"] == []
            assert diagnostic["allowed_relationships"] == ["missing"]
            assert diagnostic["minimum_unresolved_gaps"] == 1
            assert all(row["relationship"] == "support" for row in payload["previous_findings"]["findings"])
        return {"findings": [{"relation_index": row["relation_index"],
            "relationship": "support" if len(calls) == 1 else "missing", "evidence_ids": [],
            "edit_target_evidence_ids": [], "unresolved_gaps": [] if len(calls) == 1 else ["Current source is absent."]}
            for row in payload["relations"]]}
    provider = StructuredModelRequirementCoverageProvider(complete)
    findings = provider.findings(materialized_projection=materialized, retrieved_pack=retrieved,
        request=feature["user_request"])
    assert calls == ["requirement_findings", "requirement_findings_correction"]
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=materialized,
        retrieved_pack=retrieved, findings=findings)
    assert not pack.can_generate_patch and not pack.items
    assert provider.findings_attempt_audit[-1]["status"] == "accepted"


def test_metadata_evidence_remains_citeable_under_empty_domain_policy():
    from tests.unit.test_findings_edit_target_domain import _recorded
    value, pack = _recorded()
    assert pack.items and all(item.source_type == "decompiled_api" for item in pack.items)
    calls = []
    model_relations = []
    def complete(role, payload, schema):
        calls.append(role)
        model_relations.extend(row["relation_index"] for row in payload["relations"])
        assert "empty_evidence_policy" not in payload
        properties = schema["properties"]["findings"]["items"]["properties"]
        assert set(properties["relationship"]["enum"]) == {"support", "conflict", "missing"}
        assert properties["evidence_ids"]["items"]["enum"] == [item.evidence_id for item in pack.items]
        assert properties["edit_target_evidence_ids"]["maxItems"] == 0
        return {"findings": [{"relation_index": row["relation_index"], "relationship": "support",
            "evidence_ids": [pack.items[0].evidence_id], "edit_target_evidence_ids": [], "unresolved_gaps": []}
            for row in payload["relations"]]}
    findings = StructuredModelRequirementCoverageProvider(complete).findings(
        materialized_projection=value["materialized_projection"], retrieved_pack=pack, request=value["request"])
    assert calls == ["requirement_findings"]
    assert all(row["relationship"] == "support" for row in findings["findings"]
               if row["relation_index"] in model_relations)


@pytest.mark.parametrize("policy", [None, EMPTY_EVIDENCE_POLICY])
def test_recorded_empty_policy_marker_reconstructs_exact_payload_and_schema(policy):
    feature = _feature_data()
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature, request=feature["user_request"], projection=_projection())
    retrieved = EvidencePack.empty(query=feature["user_request"], reason="No matches")
    captured = []
    def complete(role, payload, schema):
        captured.append((deepcopy(payload), deepcopy(schema)))
        return {"findings": [{"relation_index": row["relation_index"], "relationship": "missing",
            "evidence_ids": [], "edit_target_evidence_ids": [], "unresolved_gaps": ["Current source is absent."]}
            for row in payload["relations"]]}
    StructuredModelRequirementCoverageProvider(complete, empty_evidence_policy=policy).findings(
        materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    historical = captured[0][0]
    assert ("empty_evidence_policy" in historical) is (policy is not None)
    StructuredModelRequirementCoverageProvider(complete,
        empty_evidence_policy=historical.get("empty_evidence_policy")).findings(
        materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    assert captured[0] == captured[1]
