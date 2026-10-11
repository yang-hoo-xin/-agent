"""Regressions from the public workflow through the serialized model request."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.libs.llm import ChatResponse
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence import EvidencePack
from src.mod_agent.evidence.requirement_coverage import (
    materialize_requirement_coverage_projection,
    requirement_input_obligation_model_view,
)
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
)
from src.mod_agent.fresh_coverage import strict_feature_spec_payload
from src.mod_agent.planning import FeatureSpecBuilder, ModPlanningBriefBuilder, RequestPlanner
from src.mod_agent.planning.request_planner import requested_scope_text
from src.mod_agent.requirement_coverage_model import request_requirement_coverage_model
from src.mod_agent.workflow import build_graph, create_initial_state


@pytest.mark.parametrize("request_text", [
    "为游戏增加一个手动计时器",
    "增加一个手动计时器，由产品 Agent 判断是否需要方法拦截",
    "Add a manual timer; use a Hook only if needed.",
    "Add a manual timer; investigate whether to use a hook.",
    "Add a manual timer; if necessary use method interception.",
    "为游戏增加一个手动计时器，不要预先指定 Hook",
    "为游戏增加一个手动计时器，保持原生移动正常",
    "不要预选 Hook；增加一个手动计时器，保持原生移动正常",
    "Do not preselect a Hook; add a manual timer and preserve normal movement.",
    "Add a manual timer without changing damage; show elapsed time in HUD.",
    "Add a manual timer; keep the existing Harmony patch unchanged.",
    "Add a manual timer; investigate whether method interception is necessary.",
    "  不要预先指定 Hook。增加手动计时器。保持原生移动正常。\n",
])
def test_constraints_do_not_invent_hook_obligations(request_text):
    request = request_text
    plan = RequestPlanner().plan(request, target_mod="Timer")
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief).to_artifact_payload()
    assert requested_scope_text(request) == request
    assert plan.user_request == spec["user_request"] == spec["target_behavior"] == request
    assert plan.route == "standard_feature"
    assert plan.requires_hook_evidence is False
    assert spec["hook_requirement"] == {
        "required": False, "reason": "implementation_mechanism_unresolved",
    }
    assert plan.requires_runtime_evidence is True
    assert "acceptance_evidence_observed" in spec["runtime_verification_plan"]
    assert "target method" not in spec["evidence_requirements"]
    assert "target symbol evidence" not in spec["evidence_requirements"]
    assert "concrete hook target method identity" not in spec["evidence_requirements"]
    assert spec["request_interpretation"] == plan.request_interpretation
    assert brief["user_intent"]["request_interpretation"] == plan.request_interpretation
    assert brief["planning_options"][0]["hook_likelihood"] == "unknown"


@pytest.mark.parametrize("request_text", [
    "Hook enemy damage method for the timer",
    "请使用方法拦截实现计时器，保持原生移动正常",
    "请使用方法拦截实现计时器并保持原生移动正常",
    "Use method interception and preserve normal movement.",
    "不要改变原生移动；必须拦截游戏方法来实现计时器",
    "Do not change damage; explicitly hook the timer method.",
])
def test_explicit_interception_still_requires_evidence(request_text):
    request = request_text
    plan = RequestPlanner().plan(request)
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    spec = FeatureSpecBuilder().build(plan, planning_brief=brief)
    assert plan.requires_hook_evidence is True
    assert plan.route == "game_hook_investigation"
    assert {"target method", "call timing", "side effect boundary",
            "concrete hook target method identity"} <= set(spec.evidence_requirements)


class _RecordingModel:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def chat(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return ChatResponse(content=json.dumps(self.response), model="scripted-regression")


def _decomposed_response(feature, *, include_hook_evidence=False):
    requirements = [
        {"role": "change", "text": "增加手动计时器", "input_obligation_indexes": [1, 2],
         "query_leads": ["manual timer input and display"]},
        {"role": "preservation", "text": "保持原生移动正常", "input_obligation_indexes": [1, 2],
         "query_leads": ["existing movement behavior boundary"]},
        {"role": "preservation", "text": "不要预先指定 Hook", "input_obligation_indexes": [1, 2],
         "query_leads": ["available timer implementation mechanisms"]},
    ]
    if include_hook_evidence:
        requirements.append({
            "role": "pre_patch_evidence", "text": "调查计时器需要的方法身份、调用时序和副作用边界",
            "input_obligation_indexes": [1, 2], "query_leads": ["timer current API and call timing"],
        })
    dispositions = []
    for obligation in requirement_input_obligation_model_view(feature)[2:]:
        index = obligation["input_obligation_index"]
        if obligation["origin"]["field"] == "evidence_requirements":
            requirements.append({"role": "pre_patch_evidence", "text": obligation["text"],
                                 "input_obligation_indexes": [index], "query_leads": [obligation["text"]]})
        else:
            dispositions.append({"input_obligation_index": index,
                                 "disposition": obligation["allowed_dispositions"][0],
                                 "reason": "Retain the stated boundary or post-change acceptance."})
    return {"requirements": requirements, "input_dispositions": dispositions}


@pytest.mark.parametrize("include_hook_evidence", [False, True])
def test_workflow_to_actual_model_messages_preserves_semantic_roles(tmp_path, include_hook_evidence):
    request = "不要预先指定 Hook；增加一个手动计时器；保持原生移动正常"
    captured = {}

    def collect(_state, feature):
        captured["feature"] = deepcopy(feature)
        model = _RecordingModel(_decomposed_response(feature, include_hook_evidence=include_hook_evidence))

        def complete_json(_stage, payload, schema):
            response, _ = request_requirement_coverage_model(
                llm=model, payload=payload, schema=schema, max_output_tokens=1024,
                capture_provider_request=True,
            )
            return json.loads(response.content)

        projection = StructuredModelRequirementCoverageProvider(complete_json).project(
            feature_data=feature, request=request,
        )
        captured["projection"] = materialize_requirement_coverage_projection(
            feature_data=feature, request=request, projection=projection,
        )
        assert len(model.requests) == 1
        captured["payload"] = json.loads(model.requests[0][0][1].content)
        return EvidencePack.empty(query=request, reason="No source collection in this regression.")

    graph = build_graph(ArtifactStore(tmp_path / "artifacts"), evidence_pack_factory=collect)
    graph.invoke(create_initial_state(run_id="timer", request_id="timer",
                                     user_request=request, target_mod="Timer"))
    feature = captured["feature"]
    payload = captured["payload"]
    assert feature["user_request"] == feature["target_behavior"] == payload["request"] == request
    assert payload["request_interpretation"] == feature["request_interpretation"]
    assert payload["request_interpretation"]["raw_request"] == request
    evidence_text = [row["text"] for row in payload["input_obligations"]
                     if row["origin"]["field"] == "evidence_requirements"]
    assert "target method" not in evidence_text
    assert "concrete hook target method identity" not in evidence_text
    requirements = captured["projection"]["requirements"]
    assert [row["text"] for row in requirements if row["role"] == "change"] == ["增加手动计时器"]
    assert {row["text"] for row in requirements if row["role"] == "preservation"} == {
        "保持原生移动正常", "不要预先指定 Hook",
    }
    if include_hook_evidence:
        assert any(row["text"] == "调查计时器需要的方法身份、调用时序和副作用边界"
                   and row["required_before_patch"] for row in requirements)


def test_corrected_derivation_creates_new_revisions_without_overwriting_history(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    request = "增加一个手动计时器，不要预先指定 Hook，保持原生移动正常"
    plan = RequestPlanner().plan(request)
    historical = replace(plan, route="game_hook_investigation", requires_hook_evidence=True,
                         hook_requirement={"required": True, "reason": "gameplay_method_interception"},
                         request_interpretation={})

    def save(current):
        request_ref = store.write(feature_id=current.feature_id, artifact_type="request_planning_report",
                                  payload=current.to_artifact_payload())
        brief = ModPlanningBriefBuilder().build(current).to_artifact_payload()
        brief_ref = store.write(feature_id=current.feature_id, artifact_type="mod_planning_brief",
                                payload=brief, upstream_refs=[request_ref])
        spec_ref = store.write(feature_id=current.feature_id, artifact_type="feature_spec",
                               payload=FeatureSpecBuilder().build(current, planning_brief=brief).to_artifact_payload(),
                               upstream_refs=[request_ref, brief_ref])
        return request_ref, brief_ref, spec_ref

    old_refs = save(historical)
    old_data = [store.read(ref) for ref in old_refs]
    new_refs = save(plan)
    assert all(old.artifact_hash != new.artifact_hash for old, new in zip(old_refs, new_refs))
    assert [store.read(ref) for ref in old_refs] == old_data
    assert store.read(new_refs[-1])["data"]["user_request"] == request
    assert store.read(new_refs[-1])["data"]["request_interpretation"]["schema_version"] == "request_interpretation_v2"


def test_versioned_feature_spec_roundtrip_and_legacy_projection_wire():
    plan = RequestPlanner().plan("增加手动计时器，保持原生移动正常")
    feature = FeatureSpecBuilder().build(plan).to_artifact_payload()
    assert strict_feature_spec_payload(feature) == feature
    legacy = dict(feature)
    del legacy["request_interpretation"]
    assert strict_feature_spec_payload(legacy) == legacy
    captured = {}

    class CaptureCompleteError(Exception):
        pass

    def complete(_stage, payload, schema):
        captured.update(payload=payload, schema=schema)
        raise CaptureCompleteError()

    with pytest.raises(CaptureCompleteError):
        StructuredModelRequirementCoverageProvider(complete).project(
            feature_data=legacy, request=legacy["user_request"],
        )
    assert set(captured["payload"]) == {"message_type", "request", "input_obligations", "rules"}
    # Frozen rules digest from the original timer run's recorded projection request.
    # 为什么要有它：旧历史续接要求实际提示逐字一致，不能用新提示冒充旧模型输入。
    assert hashlib.sha256(json.dumps(captured["payload"]["rules"], ensure_ascii=False,
                                    sort_keys=True, separators=(",", ":")).encode()).hexdigest() == (
        "26eef65d086cb85c1f2dbef44220ec98120fc850a69863a29e8c5056b020fcf3"
    )
    assert requirement_input_obligation_model_view(legacy)[1]["allowed_roles"] == ["change"]
    assert requirement_input_obligation_model_view(feature)[1]["allowed_roles"] == [
        "change", "preservation", "pre_patch_evidence",
    ]
