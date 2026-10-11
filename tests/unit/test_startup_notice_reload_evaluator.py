"""Frozen reload oracle checks; generated process data here is explicitly synthetic."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.domain import compiled_probe_evaluator as shared
from src.mod_agent.domain.startup_notice_reload_evaluator import StartupNoticeReloadEvaluator, _entries
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import read_bound_json
from tests.unit.test_startup_notice_evaluator import setup as original_setup
from tests.unit.test_startup_notice_verification import observed

CASES = Path(__file__).parents[1] / "fixtures/evaluation/startup_notice_reload_cases.json"


def evaluator_and_case(name):
    evaluator = StartupNoticeReloadEvaluator.__new__(StartupNoticeReloadEvaluator)
    evaluator.contract = json.loads(CASES.read_bytes())
    return evaluator, next(case for case in evaluator.case_definitions() if case[0] == name)


def observation(evaluator, case, *, no_handler=False):
    data = case[1]
    result = observed(data["initial"]["enabled"], data["initial"]["message"])
    if not data["initial"]["message"].strip():
        result["logs"] = []
    result.update(plugin_identity=deepcopy(evaluator.contract["plugin_identity"]),
        reload_protocol="bepinex-config-reload-probe.v1", config_reload_calls=len(data["reload_actions"]),
        config_reloaded_events=len(data["reload_actions"]), target_api_methods_instrumented=False,
        file_watcher_started_by_probe=False, reload_observations=[])
    before = deepcopy(result["entries"])
    logs = deepcopy(result["logs"])
    for index, action in enumerate(data["reload_actions"], 1):
        delta = [] if no_handler else deepcopy(action["expected"]["logs"])
        entries = _entries(action["expected"])
        result["reload_observations"].append({"id": action["id"], "config_text": action["config_text"],
            "written_config_sha256": hashlib.sha256(action["config_text"].encode()).hexdigest(),
            "reload_call_index": index, "before_entries": before, "entries": entries,
            "logs_before": len(logs), "logs_after": len(logs) + len(delta), "logs": delta,
            "config_reloaded_events": 1})
        before = deepcopy(entries)
        logs += delta
    result.update(final_entries=before, final_logs=logs)
    return result


def recount_logs(value):
    logs = deepcopy(value["logs"])
    for row in value["reload_observations"]:
        row["logs_before"] = len(logs)
        logs += row["logs"]
        row["logs_after"] = len(logs)
    value["final_logs"] = logs


def test_frozen_contract_has_five_legacy_cases_and_explicit_silent_roundtrips():
    evaluator, _ = evaluator_and_case("fresh")
    cases = evaluator.case_definitions()
    assert len(cases) == 9 and sum(len(c[1]["reload_actions"]) for c in cases) == 26
    assert [c[0] for c in cases[:5]] == ["fresh", "stored_true_custom", "stored_false_custom", "stored_empty", "stored_whitespace"]
    checks = []
    for case in cases:
        verdicts = evaluator.assess(observation(evaluator, case), case, "a" * 64)
        assert all(verdicts.values())
        checks.extend(verdicts.values())
    assert len(checks) == 141


def test_existing_load_only_behavior_fails_reload_logging_without_fabricated_configuration_failure():
    evaluator, case = evaluator_and_case("silent_state_roundtrips")
    verdicts = evaluator.assess(observation(evaluator, case, no_handler=True), case, "a" * 64)
    assert [key for key, passed in verdicts.items() if not passed] == [
        "enable_same_text.logging", "restore_same_text.logging"]


@pytest.mark.parametrize("damage", ["double", "intermediate", "disabled", "wrong_level", "case_folded", "boolean_as_integer"])
def test_behavior_counterexamples_are_rejected(damage):
    evaluator, case = evaluator_and_case("both_keys_one_completion")
    value = observation(evaluator, case)
    row = value["reload_observations"][0]
    if damage == "double":
        row["logs"] *= 2
    elif damage == "intermediate":
        row["logs"].insert(0, {"level": "Info", "message": "Old"})
    elif damage == "disabled":
        value["reload_observations"][1]["logs"] = [{"level": "Info", "message": "Quiet"}]
    elif damage == "wrong_level":
        row["logs"][0]["level"] = "Warning"
    elif damage == "case_folded":
        row["logs"][0]["message"] = "new"
    else:
        row["entries"][0]["value"] = 1
    recount_logs(value)
    assert not all(evaluator.assess(value, case, "a" * 64).values())


@pytest.mark.parametrize("damage", ["action_text", "written_hash", "before_state", "missing_action", "event_missing", "guid", "instrumented", "constructor", "assembly"])
def test_bound_actions_identity_and_probe_scope_cannot_be_replaced(damage):
    evaluator, case = evaluator_and_case("state_transitions")
    value = observation(evaluator, case)
    row = value["reload_observations"][0]
    if damage == "action_text":
        row["config_text"] += "# changed"
    elif damage == "written_hash":
        row["written_config_sha256"] = "b" * 64
    elif damage == "before_state":
        row["before_entries"] = []
    elif damage == "missing_action":
        value["reload_observations"].pop()
    elif damage == "event_missing":
        row["config_reloaded_events"] = 0
    elif damage == "guid":
        value["plugin_identity"]["guid"] = "changed"
    elif damage == "instrumented":
        value["target_api_methods_instrumented"] = True
    elif damage == "constructor":
        value["plugin_instance_constructor_skipped"] = False
    else:
        value["assembly_sha256"] = "b" * 64
    assert not all(evaluator.assess(value, case, "a" * 64).values())


def test_shared_compilation_reports_remain_delegation_compatible(tmp_path, monkeypatch):
    old, context, _, builds, _, _ = original_setup(tmp_path, monkeypatch)
    case_ref = _save(tmp_path / "cases.json", json.loads(CASES.read_bytes()))
    evaluator = StartupNoticeReloadEvaluator(compilation=old.compilation, output_root=tmp_path / "reload",
        probe_configuration_ref=old.probe_configuration_ref, case_configuration_ref=case_ref)
    calls = []
    def run(command, **kwargs):
        request = read_bound_json(_ref(command[-1]))
        case = next(c for c in evaluator.cases if c[0] == Path(command[-1]).parent.name)
        value = observation(evaluator, case)
        value["assembly_sha256"] = request["assembly"]["sha256"]
        value["loaded_dependencies"] = [{**ref, "name": Path(ref["path"]).stem} for ref in request["dependencies"]]
        calls.append(request)
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")
    monkeypatch.setattr(shared.subprocess, "run", run)
    report = evaluator(context)
    assert report["status"] == "passed" and len(calls) == 9 and len(builds) == 2
    assert report["verification_summary"] == {"checks": 141, "failed_checks": 0, "executions": 9}
    details = read_bound_json(report["verification_ref"])
    from src.mod_agent.execution.task_delegation import _verification
    _verification(report["report_ref"], [row["check_id"] for row in details["checks"]],
        request=SimpleNamespace(isolated_workspace_root=str(tmp_path)), plan_ref=context["implementation_plan_ref"],
        code_identity=context["materialized_code_identity"],
        proposal={"diff_intent": [{"generation": {"model_response_sha256": report["model_response_sha256"]}}]})
    compiled = read_bound_json(report["validation_results"]["full_compilation"]["report_ref"])
    formal = evaluator.verify_existing_assembly(assembly_ref=compiled["built_artifact_ref"],
        dependency_root=compiled["dependency_copy"]["isolated_copy"],
        expected_dependency_snapshot_sha256=compiled["dependency_binding"]["snapshot_sha256"])
    assert formal["status"] == "passed" and len(formal["checks"]) == 141
    assert len(formal["execution_refs"]) == 9 and len(calls) == 18 and len(builds) == 2
    assert formal["compilation_performed"] is False
    before = len(calls)
    with pytest.raises(ValueError, match="ASSEMBLY_CHANGED"):
        evaluator.verify_existing_assembly(assembly_ref={**compiled["built_artifact_ref"], "sha256": "0" * 64},
            dependency_root=compiled["dependency_copy"]["isolated_copy"],
            expected_dependency_snapshot_sha256=compiled["dependency_binding"]["snapshot_sha256"])
    assert len(calls) == before


def test_logging_failure_context_contains_actual_states_without_changing_acceptance():
    evaluator, case = evaluator_and_case("comparison_and_unrelated_settings")
    value = observation(evaluator, case)
    first = value["reload_observations"][0]
    first["logs"] = [{"level": "Info", "message": "Alpha"}]
    recount_logs(value)
    checks = evaluator.assess(value, case, "a" * 64)
    assert [key for key, passed in checks.items() if not passed] == ["same.logging"]
    original = deepcopy(value)
    context = evaluator.check_observation(value, "same.logging")
    assert context["initial_effective_state"] == {"General.Enabled": True, "General.Message": "Alpha"}
    assert context["before_effective_state"] == context["initial_effective_state"]
    assert context["after_effective_state"] == context["before_effective_state"]
    assert context["reload_call_index"] == 1 and context["config_reloaded_events"] == 1
    assert context["plugin_instance_constructor_skipped"] is True
    assert value == original
    changed_process = {**value, "process_id": "another execution"}
    later = evaluator.check_observation(changed_process, "same.logging")
    assert context == later
    assert evaluator.stable_observation(context) == evaluator.stable_observation(later)
    assert "same.logging" in checks and len(checks) == len(evaluator.expected(case))



def test_failed_report_sends_only_failed_checks_with_hash_bound_actual_context(tmp_path, monkeypatch):
    old, context, _, _, _, _ = original_setup(tmp_path, monkeypatch)
    evaluator = StartupNoticeReloadEvaluator(compilation=old.compilation, output_root=tmp_path / "reload-failure",
        probe_configuration_ref=old.probe_configuration_ref,
        case_configuration_ref=_save(tmp_path / "cases.json", json.loads(CASES.read_bytes())))
    def run(command, **kwargs):
        request = read_bound_json(_ref(command[-1]))
        case = next(c for c in evaluator.cases if c[0] == Path(command[-1]).parent.name)
        value = observation(evaluator, case)
        value["assembly_sha256"] = request["assembly"]["sha256"]
        value["loaded_dependencies"] = [{**ref, "name": Path(ref["path"]).stem} for ref in request["dependencies"]]
        if case[0] == "comparison_and_unrelated_settings":
            value["reload_observations"][0]["logs"] = [{"level": "Info", "message": "Alpha"}]
            recount_logs(value)
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")
    monkeypatch.setattr(shared.subprocess, "run", run)
    report = evaluator(context)
    assert report["verification_summary"] == {"checks": 141, "failed_checks": 1, "executions": 9}
    assert len(report["observations"]) == 1
    failed = report["observations"][0]
    assert failed["check_id"] == "comparison_and_unrelated_settings.same.logging" and failed["expected"] == []
    process = read_bound_json(failed["input"]["execution_ref"])
    raw = json.loads(process["stdout"])
    assert failed["observed"] == evaluator.check_observation(raw, "same.logging")
    assert failed["observed"]["initial_effective_state"]["General.Message"] == "Alpha"
    assert failed["observed"]["plugin_instance_constructor_skipped"] is True
    assert len(read_bound_json(report["verification_ref"])["checks"]) == 141
