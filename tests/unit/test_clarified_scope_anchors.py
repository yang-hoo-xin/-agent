"""Only two-stage, source-bound task-start units can leave product coverage."""
import hashlib
import json
from copy import deepcopy

import pytest

from src.mod_agent.planning.clarified_request import (
    ANCHORED_VERSION, UNIT_ROLE_PROTOCOL, product_description, projection_context, user_units,
    validate_start_anchors,
)
from src.mod_agent.planning.task_intent import ASSESSMENT_FIELDS, intent_schema
from src.mod_agent.evidence.requirement_coverage import (
    materialize_requirement_coverage_projection, requirement_input_obligation_model_view,
)
from src.mod_agent.evidence.requirement_coverage_provider import StructuredModelRequirementCoverageProvider
from src.mod_agent.planning import FeatureSpecBuilder, ModPlanningBriefBuilder, RequestPlanner
from tests.unit import test_clarification_routing as routing_tests
from tests.unit.test_clarification_routing import call
from tests.unit.test_dsh_request_routing import Model, capture_product, decision
from tests.unit.test_dsh_run_request import execution_config  # noqa: F401

profile = routing_tests.profile
ORIGINAL = "不要续跑开发任务；Mod内取消按钮必须保留任务状态。"
ANSWER = "新建独立工程；名称为演示。"


class AnchorModel(Model):
    def __init__(self, indexes=(0, 2, 3)):
        super().__init__(None)
        self.indexes = indexes

    def chat(self, messages, **kwargs):
        units = json.loads(messages[-1].content)["source_units"]
        self.value = {"assessment": {key: False for key in ASSESSMENT_FIELDS},
            "decision": decision("new_project", name="演示"),
            "unit_roles": {row["unit_id"]: ("project_name" if index == 3 else "action")
                           if index in self.indexes else "keep" for index, row in enumerate(units)}}
        return super().chat(messages, **kwargs)


def dispatch(profile, monkeypatch, indexes=(0, 2, 3)):
    calls = capture_product(monkeypatch)
    first = call(profile, decision("clarify", question="选择新建还是修改？"), ORIGINAL, turn_id="ask")
    model = AnchorModel(indexes)
    result = call(profile, model, ANSWER, turn_id="answer", clarification_for=first["route_id"])
    return calls, result, model


def feature(request):
    plan = RequestPlanner().plan(request, target_mod="Example")
    brief = ModPlanningBriefBuilder().build(plan).to_artifact_payload()
    return FeatureSpecBuilder().build(plan, planning_brief=brief).to_artifact_payload()


def projection(obligations):
    business = [row["input_obligation_index"] for row in obligations if row["origin"]["field"] == "clarified_user_unit"
                and not row["allowed_dispositions"]]
    return {"requirements": [{"role": "change", "text": "Mod内取消按钮必须保留任务状态。",
             "input_obligation_indexes": business, "query_leads": ["cancel state"]}],
        "input_dispositions": [{"input_obligation_index": row["input_obligation_index"],
            "disposition": row["allowed_dispositions"][0], "reason": "Bound task-start context or declared post-change check."}
            for row in obligations if row["allowed_dispositions"]]}


def test_units_reconstruct_original_user_bytes_without_assistant_or_offset_guessing():
    turns = [{"role": "original_user_request", "content": "  保留X.Y值，添加功能；\nNext sentence.  后续。 "},
             {"role": "assistant_clarification_context", "content": "AssistantOnly.cs？"},
             {"role": "user_answer_or_correction", "content": "新建；保持配置。"}]
    units = user_units(turns)
    assert user_units(deepcopy(turns)) == units
    for index in (0, 2):
        rows = [row for row in units if row["turn_index"] == index]
        assert "".join(row["text"] for row in rows) == turns[index]["content"]
        assert rows[0]["start"] == 0 and rows[-1]["end"] == len(turns[index]["content"])
        assert all(left["end"] == right["start"] for left, right in zip(rows, rows[1:]))
        assert all(turns[index]["content"][row["start"]:row["end"]] == row["text"] for row in rows)
    assert all(row["turn_index"] != 1 for row in units)


def test_normal_dispatch_binds_units_and_product_coverage_excludes_only_agreed_context(profile, monkeypatch):
    calls, result, model = dispatch(profile, monkeypatch)
    assert result["routing_protocol"] == UNIT_ROLE_PROTOCOL and len(model.calls) == len(calls) == 1
    request = calls[0][-1]
    context = projection_context(request)
    assert context["schema_version"] == ANCHORED_VERSION
    data = feature(request)
    obligations = requirement_input_obligation_model_view(data)
    unit_inputs = [row for row in obligations if row["origin"]["field"] == "clarified_user_unit"]
    assert [row["text"] for row in unit_inputs] == ["不要续跑开发任务；", "Mod内取消按钮必须保留任务状态。", "新建独立工程；", "名称为演示。"]
    assert [row["allowed_dispositions"] for row in unit_inputs] == [["scope_boundary"], [], ["scope_boundary"], ["scope_boundary"]]
    assert not any(row["origin"]["field"] in {"user_request", "target_behavior"} for row in obligations)
    captured = []
    def complete(role, payload, schema):
        captured.append(payload)
        return projection(obligations)
    projected = StructuredModelRequirementCoverageProvider(complete).project(feature_data=data, request=request)
    materialized = materialize_requirement_coverage_projection(feature_data=data, request=request, projection=projected)
    assert len(materialized["requirements"]) == len(materialized["queries"]) == 1
    assert materialized["requirements"][0]["text"] == "Mod内取消按钮必须保留任务状态。"
    assert materialized["requirements"][0]["required_before_patch"] is True
    assert materialized["request_identity"]["request_sha256"] == hashlib.sha256(request.encode("utf-8")).hexdigest()
    assert len(captured) == 1
    wire = json.dumps(captured[0], ensure_ascii=False)
    assert "routing_binding" not in wire and ".dsh-routing" not in wire
    assert captured[0]["literal_request_sha256"] == hashlib.sha256(request.encode("utf-8")).hexdigest()
    assert "取消按钮必须保留任务状态" in wire


def test_unanchored_mixed_unit_cannot_receive_scope_boundary(profile, monkeypatch):
    calls, _, _ = dispatch(profile, monkeypatch)
    request = calls[0][-1]
    data = feature(request)
    obligations = requirement_input_obligation_model_view(data)
    bad = projection(obligations)
    bad["input_dispositions"].append({"input_obligation_index": 2, "disposition": "scope_boundary", "reason": "Pretend product behavior is context"})
    with pytest.raises(ValueError):
        StructuredModelRequirementCoverageProvider(lambda *_: bad).project(feature_data=data, request=request)
    # A single mixed user clause remains an indivisible product unit when the router leaves it unanchored.
    mixed = [{"role": "original_user_request", "content": "新建包含取消任务按钮的Mod"},
             {"role": "assistant_clarification_context", "content": "确认？"},
             {"role": "user_answer_or_correction", "content": "确认该功能"}]
    assert user_units(mixed)[0]["text"] == mixed[0]["content"]


def test_all_context_attempt_stops_before_product_owner(profile, monkeypatch):
    calls, result, model = dispatch(profile, monkeypatch, indexes=(0, 1, 2, 3))
    assert not calls and len(model.calls) == 1
    assert result["status"] == "routing_failed" and result["reason"] == "CLARIFIED_UNIT_ROLES_ALL_CONTEXT"


@pytest.mark.parametrize("mutation", ["conversation", "turn", "source_text", "selection_hash"])
def test_anchor_binding_rejects_cross_identity_or_changed_record(profile, monkeypatch, mutation):
    calls, _, _ = dispatch(profile, monkeypatch)
    document = json.loads(calls[0][-1])
    if mutation in {"conversation", "turn"}:
        document["routing_binding"][mutation + "_id"] = "another"
    elif mutation == "source_text":
        document["conversation_turns"][0]["content"] += "新增业务要求"
    else:
        document["routing_binding"]["selection_ref"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="CLARIFIED_ROUTING"):
        projection_context(json.dumps(document, ensure_ascii=False))


def test_correction_anchor_requires_later_user_unit():
    turns = [{"role": "original_user_request", "content": "修改旧项目；保留配置。"},
             {"role": "assistant_clarification_context", "content": "新建？"},
             {"role": "user_answer_or_correction", "content": "更正为新建；实现开关。"}]
    units = user_units(turns)
    selected = decision("new_project", name="A")
    anchor = {"unit_id": units[0]["unit_id"], "execution_start_field": "action", "resolved_by_unit_id": units[2]["unit_id"]}
    later = {"unit_id": units[2]["unit_id"], "execution_start_field": "action", "resolved_by_unit_id": ""}
    assert validate_start_anchors([anchor, later], units, selected) == [anchor, later]
    with pytest.raises(ValueError, match="NOT_LATER_USER"):
        validate_start_anchors([{**anchor, "resolved_by_unit_id": units[1]["unit_id"]}], units, selected)
    with pytest.raises(ValueError, match="NOT_BOUND_TO_SAME_FIELD"):
        validate_start_anchors([anchor], units, selected)


def test_context_anchor_does_not_force_projection_to_exempt_potential_business(profile, monkeypatch):
    calls, _, _ = dispatch(profile, monkeypatch)
    request = calls[0][-1]
    data = feature(request)
    obligations = requirement_input_obligation_model_view(data)
    response = projection(obligations)
    response["input_dispositions"] = [row for row in response["input_dispositions"] if row["input_obligation_index"] != 1]
    response["requirements"][0]["input_obligation_indexes"].append(1)
    result = StructuredModelRequirementCoverageProvider(lambda *_: response).project(feature_data=data, request=request)
    assert 1 in result["requirements"][0]["input_obligation_indexes"]


def test_anchor_cannot_point_to_unlisted_assistant_unit_or_empty_selected_field():
    units = user_units([{"role": "original_user_request", "content": "保留配置；新建工程。"}])
    selected = decision("new_project", name="A")
    anchor = {"unit_id": units[1]["unit_id"], "execution_start_field": "action", "resolved_by_unit_id": ""}
    with pytest.raises(ValueError, match="ANCHORS_INVALID"):
        validate_start_anchors([{**anchor, "unit_id": "assistant_unit"}], units, selected)
    with pytest.raises(ValueError, match="EMPTY_FIELD"):
        validate_start_anchors([{**anchor, "execution_start_field": "target_id"}], units, selected)


def test_legacy_wrapper_without_anchors_retains_old_mandatory_coverage():
    turns = [{"role": "original_user_request", "content": "新建；保留配置。"},
             {"role": "assistant_clarification_context", "content": "确认？"},
             {"role": "user_answer_or_correction", "content": "确认。"}]
    request = product_description(turns, decision("new_project", name="A"))
    obligations = requirement_input_obligation_model_view(feature(request))
    assert [row["origin"]["field"] for row in obligations[:2]] == ["user_request", "target_behavior"]
    assert all(row["allowed_dispositions"] == [] for row in obligations[:2])
    assert "execution_start_anchors" not in intent_schema({"projects": []})["properties"]
