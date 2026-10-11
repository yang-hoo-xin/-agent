"""Configuration order regression from the retained memory transfer run."""
from copy import deepcopy
import itertools

import pytest

from src.mod_agent.domain.logging_transfer_evaluator import assess_logging_transfer
from tests.unit.test_startup_notice_verification import observed


def inputs():
    defaults = {"General.DebugDetails": False, "General.Enabled": True, "General.Message": "Ready"}
    case = {"entries": {"General.DebugDetails": True, "General.Enabled": True, "General.Message": "Hello"},
        "logs": [{"level": "Info", "message": "Hello"}, {"level": "Debug", "message": "Startup message length: 5"}]}
    value = observed(True, "Hello")
    value["entries"].append({"section": "General", "key": "DebugDetails", "value": True,
        "default_value": False, "value_type": "System.Boolean"})
    value["logs"] = deepcopy(case["logs"])
    return value, case, defaults


def assess(value, case, defaults):
    return assess_logging_transfer(value, case=case, defaults=defaults, assembly_sha256="a" * 64)


def test_real_binding_order_and_all_permutations_have_identical_verdict():
    value, case, defaults = inputs()
    assert [row["key"] for row in value["entries"]] == ["Enabled", "Message", "DebugDetails"]
    before = deepcopy(value)
    assert all(assess(value, case, defaults).values())
    for order in itertools.permutations(value["entries"]):
        assert assess({**value, "entries": list(order)}, case, defaults) == assess(value, case, defaults)
    assert value == before


@pytest.mark.parametrize("damage", ["duplicate", "extra", "missing", "wrong_key", "wrong_section", "wrong_value",
    "wrong_default", "wrong_type", "bool_integer", "default_integer", "string_bool", "extra_field", "missing_field", "not_list", "not_row", "invalid_key_type"])
def test_normalization_never_hides_configuration_defects(damage):
    value, case, defaults = inputs()
    if damage == "duplicate": value["entries"][2] = deepcopy(value["entries"][0])
    elif damage == "extra": value["entries"].append({**value["entries"][0], "key": "Extra"})
    elif damage == "missing": value["entries"].pop()
    elif damage == "wrong_key": value["entries"][0]["key"] = "Other"
    elif damage == "wrong_section": value["entries"][0]["section"] = "Other"
    elif damage == "wrong_value": value["entries"][0]["value"] = False
    elif damage == "wrong_default": value["entries"][0]["default_value"] = False
    elif damage == "wrong_type": value["entries"][0]["value_type"] = "System.Int32"
    elif damage == "bool_integer": value["entries"][0]["value"] = 1
    elif damage == "default_integer": value["entries"][0]["default_value"] = 1
    elif damage == "string_bool": value["entries"][0]["value"] = "true"
    elif damage == "extra_field": value["entries"][0]["unapproved"] = True
    elif damage == "missing_field": value["entries"][0].pop("value")
    elif damage == "not_list": value["entries"] = {}
    elif damage == "not_row": value["entries"][0] = "Enabled=true"
    elif damage == "invalid_key_type": value["entries"][0]["key"] = None
    checks = assess(value, case, defaults)
    assert checks["configuration"] is False
    assert checks["logging"] is True and checks["execution_binding"] is True


def test_log_sequence_and_execution_scope_remain_strict():
    value, case, defaults = inputs()
    value["logs"].reverse()
    assert assess(value, case, defaults)["logging"] is False
    value["plugin_instance_constructor_skipped"] = False
    assert assess(value, case, defaults)["execution_binding"] is False
