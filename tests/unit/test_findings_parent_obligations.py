"""Lossless Findings input from nlcfg_001's merged evidence requirement.

The fixture contains only the recorded input requirement and its four linked
FeatureSpec obligations. It contains no model Findings, patches or oracle answer.
Source: FeatureSpec 5be7c5c84cdee532aeb595c6587a9e3f3d586bd508c026ed8645237fef698274;
EvidencePack 215fd63cab7fabad89f0be068eda65cfab365e43a1cedf7920643b3143532d73.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
    _requirement_findings_model_relations,
)


@pytest.fixture
def actual_merged_parent():
    obligations = [
        {"input_obligation_id": "obligation_fe71c66f721de47796d2", "origin": {"field": "evidence_requirements", "index": 1},
         "text": "target source or API evidence", "mandatory": True, "allowed_roles": ["pre_patch_evidence"],
         "allowed_dispositions": [], "required_before_patch": True},
        {"input_obligation_id": "obligation_27321e05e54c770b6ea8", "origin": {"field": "evidence_requirements", "index": 2},
         "text": "config or text evidence", "mandatory": True, "allowed_roles": ["pre_patch_evidence"],
         "allowed_dispositions": [], "required_before_patch": True},
        {"input_obligation_id": "obligation_6c363999ae2febc597f5", "origin": {"field": "evidence_requirements", "index": 3},
         "text": "current source or docs evidence", "mandatory": True, "allowed_roles": ["pre_patch_evidence"],
         "allowed_dispositions": [], "required_before_patch": True},
        {"input_obligation_id": "obligation_8268ddbf7ada63f85038", "origin": {"field": "evidence_requirements", "index": 4},
         "text": "config schema or settings reference", "mandatory": True, "allowed_roles": ["pre_patch_evidence"],
         "allowed_dispositions": [], "required_before_patch": True},
    ]
    return {
        "schema_version": "evidence_requirement_coverage_v3",
        "feature_spec_identity": {"feature_id": "feature_cda1ea827cc3",
            "feature_spec_sha256": "2081955b7c5ab4f89512c5fba4e16588b5a21aa9956d9b50aa5d965fb282dcea"},
        "input_obligations": obligations,
        "requirements": [{"requirement_id": "requirement_898d3acd4bd97558b51f", "role": "pre_patch_evidence",
            "text": "target source or API evidence", "required_before_patch": True,
            "input_obligation_ids": [row["input_obligation_id"] for row in obligations],
            "query_leads": [row["text"] for row in obligations]}],
        "relations": [{"relation_id": "relation_295ecf825f1ec888",
            "parent_requirement_ids": ["requirement_898d3acd4bd97558b51f"],
            "meaning": "Evidence disposition for requirement 2.", "provenance": {"relation_index": 2}}],
    }


def test_actual_merged_parent_preserves_all_four_linked_obligations(actual_merged_parent):
    before = deepcopy(actual_merged_parent)
    views, indexes, all_indexes, deferred = _requirement_findings_model_relations(actual_merged_parent)
    parent = views[0]["parent_requirements"][0]
    assert parent["input_obligations"] == actual_merged_parent["input_obligations"]
    assert parent["text"] == "target source or API evidence"
    assert [row["origin"]["index"] for row in parent["input_obligations"]] == [1, 2, 3, 4]
    assert indexes == all_indexes == [2] and deferred == {}
    assert actual_merged_parent == before


def test_parent_view_is_detached_and_preserves_exact_link_order(actual_merged_parent):
    parent = actual_merged_parent["requirements"][0]
    parent["input_obligation_ids"].reverse()
    before = deepcopy(actual_merged_parent)
    views, *_ = _requirement_findings_model_relations(actual_merged_parent)
    visible = views[0]["parent_requirements"][0]["input_obligations"]
    assert [row["input_obligation_id"] for row in visible] == parent["input_obligation_ids"]
    visible[0]["origin"]["index"] = 999
    visible[0]["allowed_roles"].append("change")
    assert actual_merged_parent == before


def test_parent_view_does_not_add_unlinked_obligations(actual_merged_parent):
    parent = actual_merged_parent["requirements"][0]
    parent["input_obligation_ids"] = parent["input_obligation_ids"][:2]
    views, *_ = _requirement_findings_model_relations(actual_merged_parent)
    assert views[0]["parent_requirements"][0]["input_obligations"] == actual_merged_parent["input_obligations"][:2]


@pytest.mark.parametrize("mutation", ["unknown_id", "case_changed_id", "duplicate_link", "duplicate_obligation", "conflicting_obligation"])
def test_invalid_obligation_links_stop_before_model_completion(actual_merged_parent, mutation):
    parent = actual_merged_parent["requirements"][0]
    if mutation == "unknown_id":
        parent["input_obligation_ids"][0] = "unknown_obligation"
    elif mutation == "case_changed_id":
        parent["input_obligation_ids"][0] = parent["input_obligation_ids"][0].upper()
    elif mutation == "duplicate_link":
        parent["input_obligation_ids"].append(parent["input_obligation_ids"][0])
    elif mutation == "duplicate_obligation":
        actual_merged_parent["input_obligations"].append(deepcopy(actual_merged_parent["input_obligations"][0]))
    else:
        actual_merged_parent["input_obligations"][0]["text"] = "A conflicting text under the original immutable identity."

    def no_model(*args):
        pytest.fail("Invalid obligation identity cannot reach the semantic provider.")

    provider = StructuredModelRequirementCoverageProvider(no_model)
    with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_INPUT_OBLIGATION_INVALID"):
        provider.findings(materialized_projection=actual_merged_parent,
            retrieved_pack=EvidencePack(query="Current configuration evidence", readiness="insufficient", can_generate_patch=False),
            request="Current configuration evidence")


def test_extra_input_context_does_not_turn_missing_into_support(tmp_path):
    """A scripted missing decision remains a failure, even with current source."""
    from src.mod_agent.evidence import (
        build_requirement_coverage_pack,
        materialize_requirement_coverage_projection,
    )
    from tests.unit.test_fresh_planning_continuation import _inputs, _projection

    inputs = _inputs(tmp_path)
    retrieved = EvidencePack.from_artifact_payload(inputs.store.read(inputs.evidence_ref)["data"])
    materialized = materialize_requirement_coverage_projection(feature_data=inputs.feature_payload,
        request=inputs.feature_payload["user_request"], projection=_projection())
    answers = []

    def missing(_role, payload, _schema):
        assert all(parent["input_obligations"] for relation in payload["relations"] for parent in relation["parent_requirements"])
        answer = {"findings": [{"relation_index": relation["relation_index"], "relationship": "missing",
            "evidence_ids": [retrieved.items[0].evidence_id], "edit_target_evidence_ids": [],
            "unresolved_gaps": ["The required current semantic evidence remains unresolved."]}
            for relation in payload["relations"]]}
        answers.append(deepcopy(answer))
        return answer

    provider = StructuredModelRequirementCoverageProvider(missing)
    findings = provider.findings(materialized_projection=materialized, retrieved_pack=retrieved,
        request=inputs.feature_payload["user_request"])
    for row in answers[0]["findings"]:
        assert next(value for value in findings["findings"] if value["relation_index"] == row["relation_index"]) == row
    result = build_requirement_coverage_pack(query=inputs.feature_payload["user_request"],
        materialized_projection=materialized, retrieved_pack=retrieved, findings=findings)
    assert result.can_generate_patch is False
    assert all(row["relationship"] == "missing" for row in result.requirement_coverage["findings"])
    assert any("required_requirement_missing:" in item["message"] for item in result.blockers)
