"""Configuration judgments stay separate from compiler and game claims."""
from copy import deepcopy

from src.mod_agent.domain.accurate_crosshair_configuration import assess_configuration


def _observations():
    defaults = {"FollowsRecoil": True, "FirstShotType": "Inner", "FirstShotMinDelay": 0.15,
                "PopEnabled": False, "MinSize": 10, "SpeedScalar": 1}
    stored = {"FollowsRecoil": False, "FirstShotType": "Match", "FirstShotMinDelay": 0.25,
              "PopEnabled": True, "MinSize": 20, "SpeedScalar": 0.5}
    keys = [{"section": "General Settings", "key": key} for key in (
        "Follow Recoil", "First Shot Display Mode", "First Shot Min Delay", "Pop Enabled",
        "Minimum Size", "Resize Modifier", "Accurate Spread Enabled")]
    def row(enabled, values):
        entries = [{"section": "General Settings", "key": "Accurate Spread Enabled", "value": enabled}]
        return {"keys": deepcopy(keys), "initial_entries": deepcopy(entries), "final_entries": deepcopy(entries),
            "initial": {**values, "AccurateSpreadEnabled": enabled}, "reload_events": 0}
    result = [row(True, defaults), row(False, stored), row(False, stored), row(False, stored), row(True, stored)]
    result[3].update(reloaded={**stored, "AccurateSpreadEnabled": True}, reload_events=1,
                     final_entries=[{"section": "General Settings", "key": "Accurate Spread Enabled", "value": True}])
    return result


def test_disk_value_does_not_hide_a_reader_that_ignores_it():
    observed = _observations()
    observed[1]["initial"]["AccurateSpreadEnabled"] = True
    checks, unknown = assess_configuration(observed)
    by_id = {row["check_id"]: row for row in checks}
    assert by_id["false.file_value"]["passed"] is True
    assert by_id["false.reader_value"]["passed"] is False
    assert unknown is False


def test_missing_supported_reader_requires_verifier_adaptation_instead_of_forced_rename():
    observed = _observations()
    for row in observed:
        row["initial"].pop("AccurateSpreadEnabled")
    _, unknown = assess_configuration(observed)
    assert unknown is True


def test_wrong_config_key_is_not_hidden_by_correct_reader_value():
    observed = _observations()
    observed[0]["initial_entries"][0]["key"] = "Accurate Spread Enabled Typo"
    checks, _ = assess_configuration(observed)
    assert next(row for row in checks if row["check_id"] == "fresh.spread_default_true")["passed"] is False


def test_integer_one_does_not_count_as_boolean_configuration_true():
    observed = _observations()
    observed[0]["initial_entries"][0]["value"] = 1
    checks, _ = assess_configuration(observed)
    assert next(row for row in checks if row["check_id"] == "fresh.spread_default_true")["passed"] is False


def test_original_fields_and_reload_event_have_independent_checks():
    observed = _observations()
    observed[1]["initial"]["FirstShotType"] = "None"
    observed[3]["reload_events"] = 0
    checks, unknown = assess_configuration(observed)
    assert {row["check_id"] for row in checks if not row["passed"]} == {"false.independent_settings", "reload_true.event"}
    assert unknown is False
