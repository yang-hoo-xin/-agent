"""Native constraints prevent mechanical anchor errors; host clarification remains authoritative."""
import json

import pytest
from jsonschema import Draft7Validator

from src.mod_agent.planning.clarified_request import ANCHOR_PROTOCOL, user_units
from src.mod_agent.planning.task_intent import ASSESSMENT_FIELDS, ANCHOR_SCHEMA_VERSION, intent_schema as _intent_schema
from scripts import dsh_request_routing as routing
from tests.unit import test_clarification_routing as routing_tests
from tests.unit.test_clarification_routing import call
from tests.unit.test_dsh_request_routing import Model, decision
from tests.unit.test_dsh_run_request import execution_config  # noqa: F401

profile = routing_tests.profile
CONTEXT = {"projects": [{"id": "existing"}], "tasks": [{"id": "existing"}]}
TURNS = [{"role": "original_user_request", "content": "保留配置；考虑修改现有工程。"},
         {"role": "assistant_clarification_context", "content": "选择哪个起点？"},
         {"role": "user_answer_or_correction", "content": "新建独立工程；名称为示例；增加开关。"}]


def intent_schema(context, **kwargs):
    return _intent_schema(context, clarification_protocol=ANCHOR_PROTOCOL, **kwargs)


@pytest.fixture(autouse=True)
def retain_v4_route_protocol(monkeypatch):
    original = routing.select_task_intent
    def select(**kwargs):
        return original(**kwargs, clarification_protocol=ANCHOR_PROTOCOL)
    monkeypatch.setattr(routing, "select_task_intent", select)


def admit_native_schema(value, *, schema):
    errors = list(Draft7Validator(schema).iter_errors(value))
    if errors:
        raise ValueError(errors[0].message)


def native(action="new_project", anchors=None):
    selected = decision(action, target="existing" if action in {"modify_project", "resume_task"} else "",
                        name="Example" if action == "new_project" else "",
                        question="选择哪个？" if action == "clarify" else "")
    return {"assessment": {"catalogue_roles": {"existing": "not_referenced"},
                           **{key: False for key in ASSESSMENT_FIELDS}},
            "decision": selected, "execution_start_anchors": anchors or []}


def anchor(unit, field="action", resolver=""):
    return {"unit_id": unit["unit_id"], "execution_start_field": field, "resolved_by_unit_id": resolver}


def test_native_unit_resolvers_allow_only_empty_or_strictly_later_user_turns():
    units = user_units(TURNS)
    schema = intent_schema(CONTEXT, source_units=units)
    for source in units:
        admit_native_schema(native(anchors=[anchor(source)]), schema=schema)
        for resolver in units:
            value = native(anchors=[anchor(source, resolver=resolver["unit_id"])])
            if resolver["turn_index"] > source["turn_index"]:
                admit_native_schema(value, schema=schema)
            else:
                with pytest.raises(ValueError):
                    admit_native_schema(value, schema=schema)


@pytest.mark.parametrize("action,allowed", [("new_project", {"action", "project_name"}),
                                          ("modify_project", {"action", "target_id"}),
                                          ("clarify", set()), ("resume_task", set())])
def test_native_action_branch_limits_anchor_fields_or_requires_empty_array(action, allowed):
    units = user_units(TURNS)
    schema = intent_schema(CONTEXT, source_units=units)
    admit_native_schema(native(action), schema=schema)
    for field in ("action", "target_id", "project_name"):
        value = native(action, [anchor(units[-1], field)])
        if field in allowed:
            admit_native_schema(value, schema=schema)
        else:
            with pytest.raises(ValueError):
                admit_native_schema(value, schema=schema)


class MechanicalAnchorModel(Model):
    def __init__(self, *, override=None, action="new_project"):
        super().__init__(None)
        self.override, self.action = override, action

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1].content)
        assert payload["anchor_response_schema_version"] == ANCHOR_SCHEMA_VERSION
        units = payload["source_units"]
        row = anchor(units[-1], resolver=units[-1]["unit_id"] if self.action == "new_project" else "")
        flags = {key: key == self.override for key in ASSESSMENT_FIELDS}
        self.value = {"assessment": {"catalogue_roles": {"configured_project":
            "current_target" if self.override == "role" else "not_referenced"}, **flags},
            "decision": decision(self.action, name="Example" if self.action == "new_project" else "",
                question="选择哪个？" if self.action == "clarify" else ""),
            "execution_start_anchors": [row]}
        return super().chat(messages, **kwargs)


@pytest.mark.parametrize("override", ["unresolved_start_or_target_choice", "role"])
def test_host_override_preserves_native_anchors_but_never_consumes_them(profile, override):
    first = call(profile, decision("clarify", question="新建还是修改？"), "保留配置；增加开关。")
    model = MechanicalAnchorModel(override=override)
    result = call(profile, model, "新建；名称为Example。", clarification_for=first["route_id"])
    assert result["status"] == "needs_clarification" and not result["product_owner_invoked"]
    provenance = result["intent_provenance"]
    assert provenance["decision_overridden"] is True
    assert provenance["native_execution_start_anchors"] == model.value["execution_start_anchors"]
    assert provenance["execution_start_anchors"] == []
    assert provenance["anchor_admission"] == "not_used_host_clarification"
    assert provenance["anchor_response_schema_version"] == ANCHOR_SCHEMA_VERSION
    assert len(model.calls) == 1


@pytest.mark.parametrize("action,reason", [("new_project", "CLARIFIED_START_CORRECTION_NOT_LATER_USER"),
                                          ("clarify", "TASK_INTENT_START_ANCHORS_WITHOUT_PRODUCT")])
def test_invalid_native_anchors_without_host_override_remain_rejected(profile, action, reason):
    first = call(profile, decision("clarify", question="新建还是修改？"), "保留配置；增加开关。")
    model = MechanicalAnchorModel(action=action)
    result = call(profile, model, "新建；名称为Example。", clarification_for=first["route_id"])
    assert result["status"] == "routing_failed" and result["reason"] == reason
    assert not result["product_owner_invoked"] and len(model.calls) == 1


def test_single_turn_v3_schema_has_no_anchor_branches():
    schema = intent_schema(CONTEXT)
    assert "oneOf" not in schema and set(schema["required"]) == {"assessment", "decision"}
    assert "execution_start_anchors" not in schema["properties"]
