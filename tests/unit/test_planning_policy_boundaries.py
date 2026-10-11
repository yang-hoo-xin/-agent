"""Platform policy belongs in execution boundaries, not duplicated evidence gates."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.mod_agent.evidence.requirement_coverage import requirement_input_obligation_model_view
from src.mod_agent.local_entry import _patch_generation_obligation_projection
from src.mod_agent.planning import (
    FeatureSpecBuilder,
    ImplementationPlanner,
    ModPlanningBriefBuilder,
    RequestPlanner,
)
from src.mod_agent.planning.evidence_requirements import CURRENT_IMPLEMENTATION_EVIDENCE
from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
from src.mod_agent.workflow.graph import _feature_spec_from_payload
from tests.unit.test_fresh_planning_continuation import _inputs
from tests.unit.test_model_planning_selection import _Client

POLICIES = (
    "Do not perform unrelated refactors.",
    "Do not modify files outside evidence-supported scope.",
    "Do not claim runtime success without runtime evidence.",
)


def _owned_request():
    source = Path(__file__).parents[1] / "fixtures/patch_eval/owned_config_service/behavior_evaluator.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    assignment = next(node for node in module.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "REQUEST" for target in node.targets))
    return ast.literal_eval(assignment.value)


def test_real_owned_request_has_five_fewer_automatic_evidence_and_policy_obligations():
    original = _owned_request()
    plan = RequestPlanner().plan(original, target_mod="OwnedConfigService")
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    obligations = requirement_input_obligation_model_view(spec.to_artifact_payload())
    generated = [row for row in obligations if row["origin"]["field"] in {"evidence_requirements", "non_goals"}]
    assert generated == [], generated
    assert len(obligations) == 10  # The prior automatic contract had 15, including these five templates.
    by_index = {row["input_obligation_index"]: row for row in obligations}
    assert all(by_index[index]["required_before_patch_policy"] is False for index in (5, 6, 7))
    assert all(row["text"] not in POLICIES for row in obligations)
    assert spec.user_request == spec.target_behavior == original
    # Runtime profiles use this exact criterion text as the marker association key.
    # 为什么要有它：这里的重复具有验收身份含义，压短文案会断开原有证据关联。
    assert spec.acceptance_criteria[0] == f"Requested behavior is implemented: {original}"


def test_all_fixed_policies_reach_successful_plan_and_original_patch_projection(tmp_path):
    inputs = _inputs(tmp_path)
    feature = _feature_spec_from_payload(inputs.feature_payload)
    implementation = ImplementationPlanner().build(feature_spec=feature,
        evidence_pack=inputs.store.read(inputs.evidence_ref)["data"], formal_requirement_coverage_required=True,
        planning_target_evidence_ids=inputs.request.planning_target_evidence_ids)
    assert not implementation.blocking
    assert all(policy in implementation.side_effect_boundaries for policy in POLICIES)
    assert all(value in implementation.side_effect_boundaries for value in feature.non_goals)
    context = _patch_generation_obligation_projection(feature_spec=inputs.feature_payload,
        implementation=implementation.to_artifact_payload(), planned_changes=implementation.proposed_changes)
    assert all(context["side_effect_boundaries"].count(policy) == 1 for policy in POLICIES)


def test_true_user_non_goals_are_preserved_even_when_text_matches_platform_policy():
    plan = RequestPlanner().plan("Change a configuration default while preserving saved settings.")
    custom = ("Do not modify the oracle.", POLICIES[0])
    brief = ModPlanningBriefBuilder().build(plan, non_goals=custom).to_artifact_payload()
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert spec.non_goals == custom


def test_custom_api_and_source_requirements_are_not_filtered_by_template_text():
    plan = RequestPlanner().plan("Change configuration defaults while preserving existing settings.")
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    custom = [CURRENT_IMPLEMENTATION_EVIDENCE, "Read the explicitly required custom API contract."]
    brief["handoff"]["feature_spec_guidance"]["evidence_requirements"] = custom
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert spec.evidence_requirements == tuple(custom)
    obligations = requirement_input_obligation_model_view(spec.to_artifact_payload())
    evidence_inputs = [row for row in obligations if row["origin"]["field"] == "evidence_requirements"]
    assert [row["text"] for row in evidence_inputs] == custom
    assert all(row["required_before_patch_policy"] and not row["allowed_dispositions"] for row in evidence_inputs)


def test_explicit_hook_request_keeps_its_concrete_pre_patch_obligations():
    plan = RequestPlanner().plan("Hook Update in ExampleService and preserve its existing callers.")
    assert plan.requires_hook_evidence
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert {"target method", "call timing", "side effect boundary",
            "concrete hook target method identity"}.issubset(spec.evidence_requirements)
    assert CURRENT_IMPLEMENTATION_EVIDENCE not in spec.evidence_requirements


@pytest.mark.parametrize("damage", ["outside", "drift"])
def test_removing_template_gates_keeps_real_source_scope_and_version_checks(tmp_path, damage):
    inputs = _inputs(tmp_path)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    if damage == "outside":
        item = next(row for row in evidence["items"] if row["source_ref"] == str(inputs.behavior))
        outside = inputs.workspace.parent / "Outside.cs"
        outside.write_bytes(inputs.behavior.read_bytes())
        item.update(source_path="../Outside.cs", source_ref=str(outside))
    else:
        inputs.behavior.write_text(inputs.behavior.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
    client = _Client()
    selector = ModelPlanningTargetSelector(client=client, workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / "policy-boundary-selection.json")
    with pytest.raises(ValueError):
        selector(inputs.feature_payload, evidence)
    assert client.calls == []
