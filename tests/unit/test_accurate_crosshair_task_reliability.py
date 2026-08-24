from __future__ import annotations

from scripts.accurate_crosshair_task_reliability import (
    _config_binding,
    _contains_true_default,
    _path_profile,
    _toggle_branch,
)


def _instruction(
    offset: str,
    opcode: str,
    *,
    operand: object = None,
    resolved: str | None = None,
) -> dict[str, object]:
    return {
        "offset": offset,
        "opcode": opcode,
        "operand": operand,
        "resolved": resolved,
    }


def test_config_binding_discovers_member_without_fixed_property_name() -> None:
    getter = "Example.Settings.get_AnyToggleName"
    setter = "Example.Settings.set_AnyToggleName"
    methods = [
        {
            "symbol": "Example.Settings.Bind",
            "instructions": [
                _instruction("IL_0000", "ldstr", resolved="Accurate Spread Enabled"),
                _instruction("IL_0005", "call", resolved=getter),
                _instruction(
                    "IL_000A",
                    "callvirt",
                    resolved="BepInEx.Configuration.ConfigFile.Bind",
                ),
                _instruction("IL_000F", "callvirt", resolved="TypeSpec.get_Value"),
                _instruction("IL_0014", "call", resolved=setter),
                _instruction("IL_0019", "ret"),
            ],
        },
        {
            "symbol": getter,
            "instructions": [
                _instruction(
                    "IL_0000",
                    "ldsfld",
                    resolved="Example.Settings.toggleBackingField",
                ),
                _instruction("IL_0005", "ret"),
            ],
        },
        {
            "symbol": "Example.Settings..cctor",
            "instructions": [
                _instruction("IL_0000", "ldc.i4.1"),
                _instruction(
                    "IL_0001",
                    "stsfld",
                    resolved="Example.Settings.toggleBackingField",
                ),
                _instruction("IL_0006", "ret"),
            ],
        },
    ]

    binding = _config_binding(methods, "Accurate Spread Enabled")

    assert binding == {
        "key": "Accurate Spread Enabled",
        "bind_method": "Example.Settings.Bind",
        "read_member": getter,
        "write_member": setter,
    }
    assert _contains_true_default(methods, binding) is True


def test_boolean_cfg_separates_false_bypass_from_true_effect() -> None:
    getter = "Example.Settings.get_SpreadToggle"
    sink = "Example.Spread.ApplyAccurateSize"
    rows = [
        _instruction("IL_0000", "call", resolved=getter),
        _instruction("IL_0005", "brtrue.s", operand="IL_0008"),
        _instruction("IL_0007", "ret"),
        _instruction("IL_0008", "call", resolved=sink),
        _instruction("IL_000D", "ret"),
    ]

    branch = _toggle_branch(rows, getter)

    assert branch is not None
    _, false_start, true_start = branch
    assert _path_profile(rows, false_start, {sink}) == {
        "effect_reachable": False,
        "return_reachable": True,
    }
    assert _path_profile(rows, true_start, {sink}) == {
        "effect_reachable": True,
        "return_reachable": True,
    }
