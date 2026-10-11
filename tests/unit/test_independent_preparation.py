"""Public calibration only. No sealed task module, payload or reference imports."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from src.mod_agent.evaluation.independent_preparation import (
    ROOT,
    evaluate_submission,
    public_inventory,
    run_calibration,
    summarize,
    validate_config,
    worker,
)


@pytest.fixture
def config():
    return json.loads((ROOT / "config/independent_eval_public.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Public calibration must not connect to a service")
    monkeypatch.setattr("socket.socket.connect", denied)
    monkeypatch.setattr("socket.socket.connect_ex", denied)


@pytest.mark.parametrize("source", [
    "def clamp(value, low, high):\n    return min(high, max(low, value))\n",
    "def clamp(value, low, high):\n    if value < low:\n        return low\n    if value > high:\n        return high\n    return value\n",
])
def test_different_implementations_pass_behavior(config, source):
    result = evaluate_submission(config["tasks"][0], {"action": "submit", "files": {"numbers.py": source}})
    assert result["task_success"] is True
    assert len(result["checks"]) == 5


@pytest.mark.parametrize("source", [
    "def clamp(value, low, high):\n    return value\n",
    "def clamp(value, low, high):\n    return high\n",
    "def clamp(value, low, high):\n    return low\n",
])
def test_known_wrong_programs_rejected(config, source):
    result = evaluate_submission(config["tasks"][0], {"action": "submit", "files": {"numbers.py": source}})
    assert result["task_success"] is False
    assert result["compilation"] == "passed"
    assert result["outcome"] == "behavior_failed"


def test_preservation_is_required_even_when_target_passes(config):
    submission = copy.deepcopy(config["tasks"][0]["controlled_submission"])
    submission["files"]["utility.py"] = "def increment(value):\n    return value\n"
    result = evaluate_submission(config["tasks"][0], submission)
    assert result["task_success"] is False
    assert any(c["kind"] == "preservation" and not c["passed"] for c in result["checks"])


def test_no_change_and_correct_stop_are_legitimate(config):
    assert evaluate_submission(config["tasks"][1], {"action": "no_change", "files": {}})["task_success"] is True
    stopped = evaluate_submission(config["tasks"][2], {"action": "stop", "files": {}})
    assert stopped["outcome"] == "correct_stop" and stopped["task_success"] is True
    wrong = evaluate_submission(config["tasks"][0], {"action": "stop", "files": {}})
    assert wrong["outcome"] == "incorrect_abandonment" and wrong["task_success"] is False
    assert evaluate_submission(config["tasks"][2], {"action": "no_change", "files": {}})["outcome"] == "incorrect_continue"


@pytest.mark.parametrize("source,outcome", [
    ("def magnitude(value) return value", "compilation_failed"),
    ("import os\ndef magnitude(value):\n    return abs(value)\n", "insufficient_observation"),
    ("def magnitude(value):\n    return open('forbidden').read()\n", "insufficient_observation"),
    ("def magnitude(value):\n    return __import__('os').system('echo wrong')\n", "insufficient_observation"),
])
def test_judge_never_executes_submitted_python(config, source, outcome, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = evaluate_submission(config["tasks"][1], {"action": "submit", "files": {"numbers.py": source}})
    assert result["outcome"] == outcome
    assert not list(tmp_path.iterdir())
    assert result["task_success"] is (False if outcome == "compilation_failed" else None)


@pytest.mark.parametrize("submission", [
    {"action": "submit", "files": {"../judge.py": "pass"}},
    {"action": "no_change", "files": {"numbers.py": "pass"}},
    {"action": "stop", "files": {"numbers.py": "pass"}},
    {"action": "submit", "files": {}, "checks": []},
])
def test_submission_cannot_replace_judge_or_scope(config, submission):
    result = evaluate_submission(config["tasks"][0], submission)
    assert result["outcome"] == "execution_error" and result["task_success"] is None


def test_family_and_task_partition_integrity(config):
    validate_config(config)
    config["tasks"][1]["root_cause_family"] = config["tasks"][0]["root_cause_family"]
    with pytest.raises(ValueError, match="family crosses"):
        validate_config(config)


def test_calibration_cannot_be_renamed_unseen(config):
    config["tasks"][0]["exposure"] = "unseen"
    with pytest.raises(ValueError, match="cannot admit sealed"):
        validate_config(config)


def test_task_denominator_and_infrastructure_unknowns_stay_separate():
    rows = [{"task_id": "one", "arm": "simple_rg", "verdict": {"outcome": "behavior_failed", "task_success": False}},
            {"task_id": "one", "arm": "simple_rg", "verdict": {"outcome": "success", "task_success": True}},
            {"task_id": "two", "arm": "simple_rg", "verdict": {"outcome": "execution_error", "task_success": None}}]
    result = summarize(rows)["simple_rg"]
    assert result["distinct_task_count"] == 2 and result["repeat_attempt_count"] == 1
    assert result["first_attempt_successes"] == 0 and result["task_success_rate"] is None
    assert result["resolved_task_success_rate"] == 0 and result["unresolved_task_count"] == 1


def test_public_inventory_does_not_follow_sealed_references(tmp_path, monkeypatch):
    published = json.loads((ROOT / "config/independent_eval_sealed_public.json").read_text())
    protocol = {"public_files": ["protocol.json", "metadata.json"], "baseline_commit": "old",
        "sealed_inventory_sha256": "sealed-hash", "task_ids": ["one"], "available_modes": ["initial_patch"],
        "prepared_worker_limits": {}, "model": {}, "entry_reuse": [], "exposure_policy": {},
        "sealed_material": "DO_NOT_OPEN"}
    task = published["tasks"][0]
    metadata = {"baseline_commit": "old", "sealed_inventory_sha256": "sealed-hash", "toolchain_metadata_sha256": "toolchain",
        "tasks": [{"task_id": "one", "family_id": "family", "model_result": "not_run",
            "baseline_source_sha256": "source", "requirements_sha256": "requirements", "verifier_source_sha256": "verifier",
            **task["historical_preparation_declaration"]}]}
    for name, document in (("protocol.json", protocol), ("metadata.json", metadata)):
        (tmp_path / name).write_text(json.dumps(document))
    opened = []
    original = Path.open

    def record(self, *args, **kwargs):
        opened.append(self.name)
        assert self.name in {"protocol.json", "metadata.json"}
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", record)
    result = public_inventory(protocol_path=tmp_path / "protocol.json", metadata_path=tmp_path / "metadata.json")
    assert result["verified_count"] == 1 and result["sealed_files_opened"] == 0
    assert set(opened) == {"protocol.json", "metadata.json"}


def test_shared_budget_stops_before_second_controlled_response(config, tmp_path):
    task = config["tasks"][0]
    for name, source in task["files"].items():
        (tmp_path / name).write_text(source)
    result = worker(workspace=tmp_path, task=task, budget={**config["budget"], "max_total_model_turns": 1},
                    arm="simple_rg", submission=task["controlled_submission"])
    assert result["submission"] is None
    assert result["loop"]["model_turns_used"] == 1
    assert result["native_model_calls"] == 0


@pytest.mark.parametrize("failure", ["timeout", "nonzero"])
def test_process_failures_never_become_behavior_zero(config, tmp_path, monkeypatch, failure):
    config["tasks"] = config["tasks"][:1]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    original = subprocess.run

    def invoke(command, *args, **kwargs):
        if "--worker-input" in command:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 20)
            return subprocess.CompletedProcess(command, 7, "", "controlled execution failure")
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", invoke)
    result = run_calibration(config_path=path, output_root=tmp_path / "run")
    for summary in result["summary"].values():
        assert summary["task_success_rate"] is None and summary["unresolved_task_count"] == 1
    assert all(r["verdict"]["outcome"].startswith("execution_") for r in result["results"])


def test_paired_entries_repeat_in_isolated_directories(config, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    result = run_calibration(config_path=path, output_root=tmp_path / "run", repetitions=2)
    assert result["model_task_success_rate"] is None
    assert result["independent_unseen_task_count"] == result["native_model_calls"] == 0
    assert all(p["same_input_tools_material_budget"] for p in result["paired_comparisons"])
    for summary in result["summary"].values():
        assert summary["distinct_task_count"] == 3 and summary["attempt_count"] == 6
        assert summary["first_attempt_successes"] == 3
    assert all(r["source_and_judge_intact"] and r["scratch_cleanup"] == "removed_empty_directory" for r in result["results"])
    assert len(list((tmp_path / "run").glob("*/*/*/result.json"))) == 12
    with pytest.raises(FileExistsError):
        run_calibration(config_path=path, output_root=tmp_path / "run")
