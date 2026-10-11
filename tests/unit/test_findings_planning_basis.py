"""Current planning facts remain separate from unimplemented acceptance behavior."""
from copy import deepcopy

import pytest

from src.mod_agent.evidence import build_requirement_coverage_pack
from src.mod_agent.evidence.requirement_coverage_provider import (
    FINDINGS_PLANNING_BASIS_POLICY,
    StructuredModelRequirementCoverageProvider,
)
from tests.unit.test_requirement_coverage import _materialized_and_retrieved, _positive_findings


@pytest.mark.parametrize("relationship", ["support", "missing"])
def test_planning_guidance_preserves_model_findings_and_real_api_gaps(tmp_path, relationship):
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    response = _positive_findings(materialized, retrieved)
    response["findings"] = response["findings"][:2]
    if relationship == "missing":
        response["findings"][0].update(relationship="missing", edit_target_evidence_ids=[],
            unresolved_gaps=["The callback argument lifetime is unknown; it determines whether the new observer can retain that argument."])
    original = deepcopy(response)
    feedback = {"initial_findings_reassessment": {"findings": [
        {"relationship": "missing", "unresolved_gaps": ["Requested new behavior is absent."]}]},
        "interpretation_is_not_observation": True}
    calls = []
    def complete(role, payload, schema):
        calls.append(role)
        assert payload["findings_planning_basis_policy"] == FINDINGS_PLANNING_BASIS_POLICY
        assert payload["semantic_feedback"] == feedback
        assert [row["excerpt"] for row in payload["source_observations"]] == [item.excerpt for item in retrieved.items]
        rules = " ".join(payload["rules"])
        assert "empty body or scaffold is current implementation evidence" in rules
        assert "SPECIFIC unobserved current fact" in rules
        assert "does not prove external API contracts" in rules
        assert "Never switch to support merely to proceed" in rules
        assert set(schema["properties"]["findings"]["items"]["properties"]) == {
            "relation_index", "relationship", "evidence_ids", "edit_target_evidence_ids", "unresolved_gaps"}
        return response
    findings = StructuredModelRequirementCoverageProvider(complete).findings(
        materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"],
        semantic_feedback=feedback)
    assert calls == ["requirement_findings"] and response == original
    assert findings["findings"][:2] == original["findings"]
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=materialized,
        retrieved_pack=retrieved, findings=findings)
    assert pack.can_generate_patch is (relationship == "support")
    assert "apply_permission" in pack.requirement_coverage["does_not_grant"]


@pytest.mark.parametrize("policy", [None, FINDINGS_PLANNING_BASIS_POLICY])
def test_planning_policy_marker_reconstructs_exact_old_or_new_wire(tmp_path, policy):
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    captured = []
    def complete(role, payload, schema):
        captured.append((deepcopy(payload), deepcopy(schema)))
        response = _positive_findings(materialized, retrieved)
        response["findings"] = response["findings"][:2]
        return response
    StructuredModelRequirementCoverageProvider(complete, findings_planning_basis_policy=policy).findings(
        materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    marker = captured[0][0].get("findings_planning_basis_policy")
    assert marker == policy
    StructuredModelRequirementCoverageProvider(complete, findings_planning_basis_policy=marker).findings(
        materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    assert captured[0] == captured[1]
    assert ("Assess readiness to PLAN" in " ".join(captured[0][0]["rules"])) is (policy is not None)


def test_unknown_planning_policy_cannot_silently_select_new_semantics():
    with pytest.raises(ValueError, match="PLANNING_BASIS_POLICY_INVALID"):
        StructuredModelRequirementCoverageProvider(lambda *_: pytest.fail("model called"),
            findings_planning_basis_policy="unknown")
