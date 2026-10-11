"""Template owner contracts; no model-quality claim or inferred evidence support."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from src.mod_agent.evidence import (
    EvidencePack,
    RgLiveEvidenceProvider,
    build_requirement_coverage_pack,
    default_feature_requirement_projection,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.planning import FeatureSpecBuilder, ModPlanningBriefBuilder, RequestPlanner
from src.mod_agent.planning.evidence_requirements import (
    CONFIGURATION_EVIDENCE,
    CURRENT_IMPLEMENTATION_EVIDENCE,
)


@pytest.mark.parametrize("task_request", [
    "Add validation for the maxRetries configuration key while preserving JSON persistence.",
    "Change the existing default configuration log level to warning.",
])
def test_generic_investigation_guidance_does_not_become_semantic_obligations(task_request):
    plan = RequestPlanner().plan(task_request, target_mod="ExampleService")
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    standalone = FeatureSpecBuilder().build(plan)
    from_brief = brief["handoff"]["feature_spec_guidance"]["evidence_requirements"]
    combined = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert tuple(from_brief) == combined.evidence_requirements == standalone.evidence_requirements == ()
    guidance = brief["knowledge_query_plan"]["queries"]
    assert guidance.count(CURRENT_IMPLEMENTATION_EVIDENCE) == 1
    assert guidance.count(CONFIGURATION_EVIDENCE) == 1
    assert "implementation source" in CONFIGURATION_EVIDENCE and "referenced definition" in CONFIGURATION_EVIDENCE


@pytest.mark.parametrize("legacy", [False, True])
def test_text_quick_patch_does_not_imply_configuration_schema(legacy):
    plan = RequestPlanner().plan("Change the warning message spelling while preserving its meaning.",
                                 target_mod="ExampleService")
    plan = replace(plan, route="quick_patch", request_interpretation=(
        {} if legacy else plan.request_interpretation))
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert not any("config" in requirement.lower() for requirement in spec.evidence_requirements)


def test_custom_guidance_request_and_acceptance_are_preserved_verbatim():
    raw_request = "  Add configuration validation; preserve unknown fields and do not modify the oracle.  "
    plan = RequestPlanner().plan(raw_request, target_mod="ExampleService")
    original = FeatureSpecBuilder().build(plan)
    custom = ["config schema or settings reference", "current source or docs evidence",
              "An explicitly requested custom schema must be read before any patch."]
    brief = {"handoff": {"feature_spec_guidance": {"evidence_requirements": custom},
                         "runtime_verification_expectations": ["Custom post-change acceptance"]}}
    before = deepcopy(brief)
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert all(value in spec.evidence_requirements for value in custom)
    assert spec.evidence_requirements[-len(custom):] == tuple(custom)
    assert spec.user_request == spec.target_behavior == raw_request
    assert spec.acceptance_criteria == original.acceptance_criteria
    assert spec.non_goals == original.non_goals and brief == before
    assert spec.runtime_verification_plan == (*original.runtime_verification_plan, "Custom post-change acceptance")


def _configuration_projection(*, explicit_requirement=True):
    plan = RequestPlanner().plan("Change configuration validation while preserving existing behavior.",
                                 target_mod="ExampleService")
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    if explicit_requirement:
        brief["handoff"]["feature_spec_guidance"]["evidence_requirements"].append(CONFIGURATION_EVIDENCE)
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    feature = spec.to_artifact_payload()
    raw = default_feature_requirement_projection(feature)
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature, request=spec.user_request, projection=raw)
    return feature, raw, materialized


def test_concrete_templates_do_not_admit_a_patch_without_source():
    feature, _, materialized = _configuration_projection(explicit_requirement=False)
    retrieved = EvidencePack.empty(query=feature["user_request"], reason="No source was observed.")
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=materialized,
                                          retrieved_pack=retrieved, findings={"findings": []})
    assert pack.can_generate_patch is False
    assert pack.requirement_coverage["edit_target_evidence_ids"] == []
    required = [row for row in materialized["input_obligations"] if row["required_before_patch"]]
    assert {row["origin"]["field"] for row in required} == {"user_request", "target_behavior"}
    assert all(row["allowed_dispositions"] == [] for row in required)


def test_referenced_but_unobserved_schema_stays_a_required_gap(tmp_path):
    feature, projection, materialized = _configuration_projection()
    source = tmp_path / "ExampleService/SchemaReader.cs"
    source.parent.mkdir()
    source.write_text('''namespace ExampleService
{
    public class SchemaReader
    {
        public string ReadSchema()
        {
            return System.IO.File.ReadAllText("rules.json");
        }
    }
}
''', encoding="utf-8")
    retrieved = RgLiveEvidenceProvider(tmp_path).collect(query="ReadSchema", search_root="ExampleService")
    assert retrieved.items and not (source.parent / "rules.json").exists()
    schema_requirement = next(row for row in materialized["requirements"] if row["text"] == CONFIGURATION_EVIDENCE)
    schema_id = schema_requirement["requirement_id"]
    findings = {"findings": [{"relation_index": relation_index,
        "relationship": "missing" if schema_id in row["parent_requirement_ids"] else "support",
        "evidence_ids": [retrieved.items[0].evidence_id], "edit_target_evidence_ids": [],
        "unresolved_gaps": ["ReadSchema references rules.json, whose constraints have not been observed."]
            if schema_id in row["parent_requirement_ids"] else []}
        for relation_index, row in enumerate(materialized["relations"], 1)]}
    before = deepcopy(findings)
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=materialized,
                                          retrieved_pack=retrieved, findings=findings)
    assert pack.can_generate_patch is False and findings == before
    assert "required_requirement_missing:" + schema_id in pack.requirement_coverage["sufficiency"]["reasons"]
    index = next(index for index, row in enumerate(materialized["input_obligations"], 1)
                 if row["text"] == CONFIGURATION_EVIDENCE)
    invalid = deepcopy(projection)
    invalid["input_dispositions"].append({"input_obligation_index": index,
        "disposition": "not_applicable", "reason": "The referenced file was not retrieved."})
    with pytest.raises(ValueError, match="DISPOSITION"):
        materialize_requirement_coverage_projection(feature_data=feature,
            request=feature["user_request"], projection=invalid)
