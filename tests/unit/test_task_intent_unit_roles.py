"""Fixed-map clarification scope avoids array/resolver mechanics without weakening product coverage."""
import json

import pytest
from jsonschema import Draft7Validator

from src.mod_agent.planning.clarified_request import (
    UNIT_ROLE_PROTOCOL, user_units, validate_unit_roles, validate_start_anchors,
)
from src.mod_agent.planning.task_intent import ASSESSMENT_FIELDS, UNIT_ROLE_SCHEMA_VERSION, intent_schema
from tests.unit import test_clarification_routing as routing_tests
from tests.unit.test_clarification_routing import call
from tests.unit.test_dsh_request_routing import Model, decision
from tests.unit.test_dsh_run_request import execution_config  # noqa: F401

profile = routing_tests.profile
TURNS = [{"role": "original_user_request", "content": "保留配置；取消Mod内选中的任务。"},
         {"role": "assistant_clarification_context", "content": "工程起点？"},
         {"role": "user_answer_or_correction", "content": "新建独立工程。"}]
CONTEXT = {"projects": [{"id": "p"}], "tasks": [{"id": "p"}]}


def native(action, roles):
    return {"assessment": {"catalogue_roles": {"p": "current_target" if action in {"modify_project", "resume_task"} else "not_referenced"},
                           **{key: False for key in ASSESSMENT_FIELDS}},
        "decision": decision(action, target="p" if action in {"modify_project", "resume_task"} else "",
            name="A" if action == "new_project" else "", question="哪个？" if action == "clarify" else ""),
        "unit_roles": roles}


@pytest.mark.parametrize("action,allowed", [("new_project", {"keep", "action", "project_name"}),
    ("modify_project", {"keep", "action", "target_id"}), ("clarify", {"keep"}), ("resume_task", {"keep"})])
def test_native_fixed_map_has_all_ids_once_and_action_specific_values(action, allowed):
    units = user_units(TURNS)
    schema = intent_schema(CONTEXT, source_units=units)
    validator = Draft7Validator(schema)
    roles = {row["unit_id"]: "keep" for row in units}
    assert not list(validator.iter_errors(native(action, roles)))
    key = units[-1]["unit_id"]
    for role in ("keep", "action", "target_id", "project_name", "invented"):
        assert bool(list(validator.iter_errors(native(action, {**roles, key: role})))) == (role not in allowed)
    for malformed in ({}, {**roles, "extra": "keep"}, {k: v for k, v in roles.items() if k != key}):
        assert list(validator.iter_errors(native(action, malformed)))
    assert "resolved_by_unit_id" not in json.dumps(schema)
    assert "execution_start_anchors" not in json.dumps(schema)


def test_host_normalization_is_unit_ordered_and_makes_no_correction_edge_claim():
    units = user_units(TURNS)
    roles = {row["unit_id"]: "keep" for row in reversed(units)}
    roles[units[-1]["unit_id"]] = "action"
    normalized = validate_unit_roles(roles, units, decision("new_project", name="A"))
    assert normalized == [{"unit_id": units[-1]["unit_id"], "execution_start_field": "action", "resolved_by_unit_id": ""}]
    assert roles[units[1]["unit_id"]] == "keep"


@pytest.mark.parametrize("kind", ["missing", "extra", "invalid_role", "all_context", "empty_field"])
def test_host_rejects_role_map_identity_action_and_all_context_bypasses(kind):
    units = user_units(TURNS)
    roles = {row["unit_id"]: "keep" for row in units}
    selected = decision("new_project", name="A")
    if kind == "missing": roles.pop(units[0]["unit_id"])
    elif kind == "extra": roles["extra"] = "keep"
    elif kind == "invalid_role": roles[units[-1]["unit_id"]] = "target_id"
    elif kind == "all_context": roles = {key: "action" for key in roles}
    else:
        selected["project_name"] = ""
        roles[units[-1]["unit_id"]] = "project_name"
    with pytest.raises(ValueError, match="CLARIFIED_UNIT_ROLES"):
        validate_unit_roles(roles, units, selected)


class OverrideRoleModel(Model):
    def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1].content)
        assert payload["anchor_response_schema_version"] == UNIT_ROLE_SCHEMA_VERSION
        self.value = {"assessment": {"catalogue_roles": {"configured_project": "not_referenced"},
            **{key: key == "unresolved_start_or_target_choice" for key in ASSESSMENT_FIELDS}},
            "decision": decision("new_project", name="A"),
            "unit_roles": {row["unit_id"]: "action" for row in payload["source_units"]}}
        return super().chat(messages, **kwargs)


def test_host_clarification_retains_raw_roles_but_exposes_no_eligible_units(profile):
    first = call(profile, decision("clarify", question="选择起点？"), TURNS[0]["content"])
    model = OverrideRoleModel(None)
    result = call(profile, model, TURNS[-1]["content"], clarification_for=first["route_id"])
    assert result["status"] == "needs_clarification" and not result["product_owner_invoked"]
    provenance = result["intent_provenance"]
    assert provenance["protocol"] == UNIT_ROLE_PROTOCOL
    assert provenance["native_unit_roles"] == model.value["unit_roles"]
    assert provenance["execution_start_anchors"] == [] and provenance["anchor_admission"] == "not_used_host_clarification"
    assert provenance["anchor_origin"] == "host_normalized_unit_roles_without_correction_edges"
    assert len(model.calls) == 1


def test_old_v4_self_and_missing_same_field_links_still_fail():
    units = user_units(TURNS)
    selected = decision("new_project", name="A")
    source, later = units[0], units[-1]
    row = {"unit_id": source["unit_id"], "execution_start_field": "action", "resolved_by_unit_id": source["unit_id"]}
    with pytest.raises(ValueError, match="NOT_LATER_USER"):
        validate_start_anchors([row], units, selected)
    with pytest.raises(ValueError, match="NOT_BOUND_TO_SAME_FIELD"):
        validate_start_anchors([{**row, "resolved_by_unit_id": later["unit_id"]}], units, selected)
