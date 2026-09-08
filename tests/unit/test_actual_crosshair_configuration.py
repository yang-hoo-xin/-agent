"""Configuration judgments stay separate from compiler and game claims."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.domain.accurate_crosshair_configuration import assess_configuration
from src.mod_agent.domain.accurate_crosshair_eval import CONFIG_CASE, CONFIG_CHECKS


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


def _recoil_observations():
    defaults = {"FirstShotType": "Inner", "FirstShotMinDelay": 0.15,
                "PopEnabled": False, "MinSize": 10, "SpeedScalar": 1}
    stored = {"FirstShotType": "Match", "FirstShotMinDelay": 0.25,
              "PopEnabled": True, "MinSize": 20, "SpeedScalar": 0.5}
    names = ("Follow Recoil", "First Shot Display Mode", "First Shot Min Delay",
             "Pop Enabled", "Minimum Size", "Resize Modifier")
    def row(enabled, values):
        entries = [{"section": "General Settings", "key": name, "value": value}
                   for name, value in zip(names, (enabled, *values.values()))]
        return {"keys": [{"section": item["section"], "key": item["key"]} for item in entries],
                "initial_entries": entries, "final_entries": deepcopy(entries),
                "initial": {"FollowsRecoil": enabled, **values, "AccurateSpreadEnabled": None},
                "reload_events": 0}
    return [row(False, defaults), row(True, stored), row(False, stored)]


def test_recoil_task_real_configuration_uses_only_its_own_five_obligations():
    checks, unknown = assess_configuration(_recoil_observations(), case_id=CONFIG_CASE)
    assert tuple(row["check_id"] for row in checks) == CONFIG_CHECKS
    assert all(row["passed"] for row in checks)
    assert unknown is False


@pytest.mark.parametrize("mutation,failed", [
    ("fresh_default", "fresh.recoil_default_false"),
    ("stored_reader", "existing_true.explicit_value_preserved"),
    ("stored_file", "existing_false.explicit_value_preserved"),
    ("stored_other", "existing_true.explicit_value_preserved"),
    ("added_switch", "fresh.exact_configuration_keys"),
    ("integer_bool", "fresh.recoil_default_false"),
])
def test_recoil_configuration_does_not_hide_default_storage_or_preservation_regressions(mutation, failed):
    observed = _recoil_observations()
    if mutation == "fresh_default":
        observed[0]["initial"]["FollowsRecoil"] = True
    elif mutation == "stored_reader":
        observed[1]["initial"]["FollowsRecoil"] = False
    elif mutation == "stored_file":
        observed[2]["initial_entries"][0]["value"] = True
    elif mutation == "stored_other":
        observed[1]["initial"]["MinSize"] = 10
    elif mutation == "added_switch":
        observed[0]["keys"].append({"section": "General Settings", "key": "Accurate Spread Enabled"})
    else:
        observed[0]["initial"]["FollowsRecoil"] = 0
    checks, unknown = assess_configuration(observed, case_id=CONFIG_CASE)
    assert {row["check_id"] for row in checks if not row["passed"]} == {failed}
    assert unknown is False


def test_recoil_missing_reader_is_a_verifier_gap():
    observed = _recoil_observations()
    observed[1]["initial"]["FollowsRecoil"] = None
    _, unknown = assess_configuration(observed, case_id=CONFIG_CASE)
    assert unknown is True


def test_recoil_runner_reuses_compiled_assembly_with_three_task_specific_processes(tmp_path, monkeypatch):
    from src.mod_agent.domain import accurate_crosshair_configuration as module
    from src.mod_agent.domain.accurate_crosshair_eval import _reference, _save

    probe, dotnet, assembly = (tmp_path / name for name in ("probe.dll", "dotnet.exe", "compiled.dll"))
    for path in (probe, dotnet, assembly):
        path.write_bytes(path.name.encode())
    bundle = _save(tmp_path / "probe.json", {"dotnet": _reference(dotnet), "assembly_path": str(probe),
                                           "files": [_reference(probe)]})
    dependency = tmp_path / "dependencies"
    dependency.mkdir()
    (dependency / "dep.dll").write_bytes(b"synthetic dependency; never executed")
    compilation = {"status": "passed", "all_required_files_compiled": True,
                   "built_artifact_ref": _reference(assembly),
                   "materialized_code_identity": {"code_sha256": "a" * 64},
                   "dependency_copy": {"isolated_copy": str(dependency)}}
    compilation["report_ref"] = _save(tmp_path / "compilation.json", compilation)
    observations, calls = _recoil_observations(), []

    def process(command, **kwargs):
        request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        observed = observations[len(calls)]
        calls.append(request)
        assert command[:2] == [str(dotnet), str(probe)]
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({**observed,
            "status": "observed", "configuration_assembly_sha256": compilation["built_artifact_ref"]["sha256"]}))

    monkeypatch.setattr(module.subprocess, "run", process)
    # Keep the synthetic process sandboxes in this test's managed temp root.
    def sandbox(*, prefix):
        path = tmp_path / prefix
        path.mkdir()
        return str(path)
    monkeypatch.setattr(module.tempfile, "mkdtemp", sandbox)
    checker = module.ActualCrosshairConfigurationChecker(probe_configuration_ref=bundle,
        output_root=tmp_path / "observations", case_id=CONFIG_CASE)
    old_checker = module.ActualCrosshairConfigurationChecker(probe_configuration_ref=bundle,
        output_root=tmp_path / "legacy")
    assert checker.verification_identity()["inputs_sha256"] != old_checker.verification_identity()["inputs_sha256"]
    report = checker(compilation)
    assert report["status"] == "passed" and len(calls) == 3
    assert calls[0]["seed_config"] is None
    assert "Follow Recoil = true" in calls[1]["seed_config"]
    assert "Follow Recoil = false" in calls[2]["seed_config"]
    assert all(request["reload_config"] is None for request in calls)
    assert all("Accurate Spread Enabled" not in (request["seed_config"] or "") for request in calls)
    assert all(request["assembly"] == compilation["built_artifact_ref"] for request in calls)
    assert tuple(row["check_id"] for row in report["checks"]) == CONFIG_CHECKS
    assert report["materialized_code_identity"] == compilation["materialized_code_identity"]
    assert report["reader_mapping"] == "AccurateCrosshair.Configuration.FollowsRecoil"
    assert report["runtime_status"] == report["automatic_liveedit_status"] == "not_executed"
    assert report["report_ref"] == _reference(report["report_ref"]["path"])
