"""Focused checks for the S2 oracle's unchanged boundary and behavior contract."""
from copy import deepcopy
import pytest
from src.mod_agent.domain.hud_size_evaluator import assess_hud_size


def example():
    case = {"size_pixels": 96, "show_label": True, "caption": "Vitals", "opacity": 0.8, "unrelated": None}
    value = {"status": "observed", "assembly_sha256": "a" * 64, "plugin_load_calls": 1,
        "plugin_instance_constructor_skipped": False, "injected_base_properties": [], "configuration_origin": "BasePlugin_constructor",
        "rendering_sink_replaced": True, "config_save_called_by_probe": False,
        "hud_calls": [{"size_pixels": 96, "caption": "Vitals", "opacity": 0.8}],
        "plugin_identity": {"guid": "benchmark.gtfo.expeditionhud", "name": "Expedition HUD", "version": "1.2.0"},
        "entries": [{"section": "HUD", "key": k, "value": v, "default_value": d, "value_type": t}
            for k,v,d,t in (("Size", "invalid-original-text", "96", "System.String"),
                ("ShowLabel", True, True, "System.Boolean"), ("Caption", "Vitals", "Vitals", "System.String"),
                ("Opacity", 0.8, 0.8, "System.Single"))]}
    return value,case


def check(value,case):
    return assess_hud_size(value,case=case,assembly_sha256="a"*64)


def test_size_persistence_is_not_an_undeclared_requirement():
    value,case=example()
    assert all(check(value,case).values())
    value["entries"][0]["value"]="96"
    assert all(check(value,case).values())


@pytest.mark.parametrize("damage,key",[("no_render","render_call"),("twice","render_call"),("zero","render_call"),
    ("caption","render_call"),("opacity","render_call"),("duplicate","other_settings"),("bool_as_int","other_settings"),
    ("probe_save","execution_binding"),("other_dll","execution_binding"),("plugin_identity","plugin_identity")])
def test_wrong_behavior_cannot_be_hidden_by_default_fallback(damage,key):
    value,case=example()
    if damage=="no_render":value["hud_calls"]=[]
    elif damage=="twice":value["hud_calls"]*=2
    elif damage=="zero":value["hud_calls"][0]["size_pixels"]=0
    elif damage=="caption":value["hud_calls"][0]["caption"]="changed"
    elif damage=="opacity":value["hud_calls"][0]["opacity"]=0
    elif damage=="duplicate":value["entries"][3]=deepcopy(value["entries"][2])
    elif damage=="bool_as_int":value["entries"][1]["value"]=1
    elif damage=="probe_save":value["config_save_called_by_probe"]=True
    elif damage=="other_dll":value["assembly_sha256"]="b"*64
    elif damage=="plugin_identity":value["plugin_identity"]["guid"]="changed"
    assert check(value,case)[key] is False


def test_valid_size_and_unrelated_configuration_are_preserved():
    value,case=example();case.update(size_pixels=64,unrelated="original")
    value["hud_calls"][0]["size_pixels"]=64
    value["entries"][0]["value"]="64"
    value["saved_config"]="[Unrelated]\nKeep = original\n"
    assert all(check(value,case).values())
    value["saved_config"]="[Unrelated]\nKeep = changed\n"
    assert check(value,case)["unrelated_persistence"] is False
