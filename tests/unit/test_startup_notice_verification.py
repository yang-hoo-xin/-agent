"""Cold startup task acceptance rejects missing behavior and extra logging."""
from copy import deepcopy

import pytest

from src.mod_agent.domain.startup_notice_verification import assess_observation


def observed(enabled=True, message="Ready"):
    return {"status": "observed", "plugin_load_calls": 1, "plugin_instance_constructor_skipped": True,
        "injected_base_properties": ["Config", "Log"], "assembly_sha256": "a" * 64,
        "log_capture": "real_bepinex_global_listener_including_injected_base_log_source",
        "entries": [{"section": "General", "key": "Enabled", "value": enabled, "default_value": True, "value_type": "System.Boolean"},
                    {"section": "General", "key": "Message", "value": message, "default_value": "Ready", "value_type": "System.String"}],
        "logs": [{"level": "Info", "message": message, "source": "real log"}] if enabled else []}


@pytest.mark.parametrize("enabled,message", [(True, "Ready"), (True, "Custom"), (False, "Disabled")])
def test_startup_contract(enabled, message):
    assert all(assess_observation(observed(enabled, message), enabled=enabled, message=message, assembly_sha256="a"*64).values())


@pytest.mark.parametrize("damage", ["neutral", "double", "disabled_log", "boolean_integer", "assembly"])
def test_realistic_counterexamples(damage):
    enabled = damage != "disabled_log"
    value = deepcopy(observed(enabled))
    if damage == "neutral":
        value.update(entries=[], logs=[])
    elif damage == "double":
        value["logs"] *= 2
    elif damage == "disabled_log":
        value["logs"] = [{"level": "Info", "message": "Ready"}]
    elif damage == "boolean_integer":
        value["entries"][0]["value"] = 1
    else:
        value["assembly_sha256"] = "b" * 64
    assert not all(assess_observation(value, enabled=enabled, message="Ready", assembly_sha256="a"*64).values())
