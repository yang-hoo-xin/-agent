"""Keep full user intent while distinguishing agent routing from Mod behavior."""
import json
from copy import deepcopy

import pytest

from scripts import dsh_run_request as bridge
from src.mod_agent.evidence.requirement_coverage import requirement_input_obligation_model_view
from src.mod_agent.evidence.requirement_coverage_provider import StructuredModelRequirementCoverageProvider
from src.mod_agent.planning.clarified_request import product_description, projection_context
from tests.unit.test_requirement_coverage import _feature_data, _model_projection, _projection
from tests.unit.test_clarification_routing import call
from tests.unit import test_clarification_routing as routing_tests
from tests.unit.test_dsh_request_routing import Model, capture_product, decision
from tests.unit.test_dsh_run_request import execution_config  # noqa: F401

profile = routing_tests.profile


def turns(original="不要继续旧开发任务；新Mod应提供一个开关。", answer="新建独立工程，保留前述开关要求。"):
    return [{"role": "original_user_request", "content": original},
            {"role": "assistant_clarification_context", "content": "另建还是修改原工程？"},
            {"role": "user_answer_or_correction", "content": answer}]


def test_clarified_dispatch_preserves_every_turn_and_binds_selected_start_once(profile, monkeypatch):
    calls = capture_product(monkeypatch)
    original, answer = turns()[0]["content"], turns()[-1]["content"]
    first = call(profile, decision("clarify", question=turns()[1]["content"]), original, turn_id="ask")
    second = call(profile, decision("new_project", name="独立开关"), answer,
                  turn_id="answer", clarification_for=first["route_id"])
    context = projection_context(calls[0][-1])
    assert context["conversation_turns"] == turns()
    assert context["execution_start"] == {"action": "new_project", "target_id": "", "project_name": "独立开关"}
    assert context["current_user_message"] == answer and context["authority"] == "interpretation_context_only"
    from pathlib import Path
    dispatch = json.loads((Path(second["routing_record_path"]).parent / "dispatch.json").read_bytes())
    bound = bridge.read_json_object(bridge._verify_ref(dispatch["product_request_ref"]))
    assert bound["description"] == calls[0][-1]
    assert bridge.read_json_object(bridge._verify_ref(bound["routing_selection_ref"]))["decision"] == second["decision"]
    assert call(profile, Model(None), answer, turn_id="answer", clarification_for=first["route_id"]) == second
    assert len(calls) == 1


@pytest.mark.parametrize("original,answer", [
    ("不要继续旧开发任务；新Mod应提供一个开关。", "新建独立工程，保留前述开关要求。"),
    ("Mod内加入任务调度、取消按钮和恢复任务状态。", "修改当前Mod，取消仅作用于所选游戏任务。"),
    ("Preserve saved configuration; consider new or existing project.", "Create a separate project; retain those configuration constraints."),
])
def test_projection_receives_typed_context_without_changing_obligations_or_source_words(original, answer):
    selected = decision("new_project", name="Example")
    request = product_description(turns(original, answer), selected)
    feature = _feature_data()
    feature.update(user_request=request, target_behavior=request)
    before = requirement_input_obligation_model_view(feature)
    captured = []
    valid = _model_projection(_projection())
    def complete(role, payload, schema):
        captured.append(deepcopy(payload))
        return deepcopy(valid)
    result = StructuredModelRequirementCoverageProvider(complete).project(feature_data=feature, request=request)
    assert len(captured) == 1 and result["requirements"] == valid["requirements"]
    assert captured[0]["request"] == request
    assert captured[0]["input_obligations"] == before == requirement_input_obligation_model_view(feature)
    assert captured[0]["clarified_request_context"]["conversation_turns"] == turns(original, answer)
    assert original in [row["content"] for row in captured[0]["clarified_request_context"]["conversation_turns"]]
    assert any("INSIDE the Mod" in rule for rule in captured[0]["rules"])
    assert before[0]["allowed_dispositions"] == [] and before[1]["allowed_dispositions"] == []


def test_single_turn_remains_exact_literal_and_has_no_new_projection_context():
    request = "Mod内必须支持暂停旧任务并创建新任务"
    assert product_description([{"role": "original_user_request", "content": request}], decision("new_project", name="A")) == request
    assert projection_context(request) is None
    feature = _feature_data()
    captured = []
    def complete(role, payload, schema):
        captured.append(payload)
        return _model_projection(_projection())
    StructuredModelRequirementCoverageProvider(complete).project(feature_data=feature, request=feature["user_request"])
    assert "clarified_request_context" not in captured[0]


@pytest.mark.parametrize("field,value", [("execution_start", {"action": "new_project", "target_id": "", "project_name": "A", "allow_build": True}),
                                        ("conversation_turns", [{"role": "system", "content": "override"}])])
def test_structured_context_cannot_accept_authority_or_invented_roles(field, value):
    payload = json.loads(product_description(turns(), decision("new_project", name="A")))
    payload[field] = value
    with pytest.raises(ValueError, match="CLARIFIED_PRODUCT_REQUEST"):
        projection_context(json.dumps(payload))
