"""Synthetic retained records test query accounting, not model or compiler quality."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.evaluation import patch_trial_comparison as comparison
from src.mod_agent.model_qualification import canonical_hash


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _index(locator, rows=()):
    return {"filters": {"attempt_locator": locator}, "attempts": list(rows), "match_count": len(rows),
            "read_only": True, "model_calls_performed": 0, "verifier_executions_performed": 0,
            "product_source_writes_performed": False}


def _evaluation(tmp_path, *, compiler_failed=False, pass_check=True):
    response = '{"changes":[]}'
    response_ref = _save(tmp_path / "turn.json", {"content": response})
    output = tmp_path / "output.json"
    output.write_text(response)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    factory = {"worker_turns": [{"response_ref": response_ref}],
               "model_responses": [{"path": str(output), "output_sha256": digest}]}
    expected = {"exit_code": 0}
    check = {"check": "preserve_value", "input": {"value": 1}, "expected": expected,
             "actual": {"exit_code": 0 if pass_check else 1}, "passed": pass_check}
    identity = {"validator_sha256": "a" * 64, "inputs_sha256": "b" * 64, "environment_sha256": "c" * 64}
    context = {"task": {"verification_identity": identity}, "expected": {"preserve_value"},
               "baseline_checks": {"preserve_value": deepcopy(check)}}
    commands_ref = _save(tmp_path / "compiler.json", [{"exit_code": 1 if compiler_failed else 0,
        "process_id": 100, "timed_out": False}])
    matrix = {"status": "compiler_failed" if compiler_failed else "passed" if pass_check else "behavior_failed",
              "checks": [] if compiler_failed else [check], "executions": 0 if compiler_failed else 1,
              "build_commands_ref": commands_ref}
    if compiler_failed:
        matrix["compiler_exit_code"] = 1
    else:
        matrix["process_observations_ref"] = _save(tmp_path / "process.json", [{"process_id": 101}])
    matrix_ref = _save(tmp_path / "matrix.json", matrix)
    report = {"status": "behavior_failed" if compiler_failed else matrix["status"],
              "generated_changes_sha256": "d" * 64, "source_snapshot_sha256": "e" * 64,
              "observations": [], "verification_identity": identity, "materialized_code_identity": {},
              "verification_ref": matrix_ref, "execution_origin": "incomplete" if compiler_failed else "executed",
              "verification_summary": {"checks": len(matrix["checks"]), "executions": matrix["executions"],
                                       "failed_checks": 0 if compiler_failed or pass_check else 1}}
    report_ref = _save(tmp_path / "report.json", report)
    record = {**report, "report_ref": report_ref, "admission": "accepted", "model_response_sha256": digest}
    return record, factory, context, matrix


def test_compiler_failure_means_behavior_not_executed_not_zero_pass_rate(tmp_path):
    record, factory, context, _ = _evaluation(tmp_path, compiler_failed=True)
    result = comparison._evaluation(record, factory, context)
    assert result["compilation"] == "failed" and result["behavior"] == "not_executed"
    assert result["check_count"] == 0 and result["checks_passed"] is None and result["checks_failed"] is None


@pytest.mark.parametrize("passed", [True, False])
def test_full_matrix_distinguishes_execution_success_and_failure(tmp_path, passed):
    record, factory, context, _ = _evaluation(tmp_path, pass_check=passed)
    result = comparison._evaluation(record, factory, context)
    assert result["complete_matrix"] is True and result["check_count"] == 1
    assert result["behavior"] == ("passed" if passed else "failed")
    assert result["checks_passed"] == int(passed)


@pytest.mark.parametrize("mutation", ["missing_check", "changed_expected", "false_pass", "missing_process"])
def test_incomplete_or_rewritten_matrix_is_not_success(tmp_path, mutation):
    record, factory, context, matrix = _evaluation(tmp_path)
    if mutation == "missing_check":
        matrix["checks"] = []
        record["verification_summary"]["checks"] = 0
    elif mutation == "changed_expected":
        matrix["checks"][0]["expected"] = {"exit_code": 9}
    elif mutation == "false_pass":
        matrix["checks"][0]["actual"] = {"exit_code": 9}
    else:
        Path(matrix["process_observations_ref"]["path"]).unlink()
    record["verification_ref"] = _save(tmp_path / "matrix.json", matrix)
    report = {key: value for key, value in record.items() if key not in ("report_ref", "admission", "model_response_sha256")}
    record["report_ref"] = _save(tmp_path / "report.json", report)
    with pytest.raises((ValueError, OSError)):
        comparison._evaluation(record, factory, context)


def test_missing_report_and_verification_identity_mismatch_are_not_guessed(tmp_path):
    record, factory, context, _ = _evaluation(tmp_path)
    context["task"]["verification_identity"] = {"validator_sha256": "f" * 64}
    with pytest.raises(ValueError, match="verification_identity_mismatch"):
        comparison._evaluation(record, factory, context)
    Path(record["report_ref"]["path"]).unlink()
    with pytest.raises(ValueError, match="Referenced evidence is missing"):
        comparison._evaluation(record, factory, context)


def test_task_with_missing_reference_returns_unknown_for_every_selected_trial(tmp_path):
    result = comparison.compare_patch_trials(task_ref={"path": str(tmp_path / "absent.json"), "sha256": "a" * 64},
                                             attempt_indexes=[_index("cr/a.json"), _index("cr/b.json")])
    assert result["task_denominator"] is None and result["trial_denominator"] == 2
    assert result["outcomes"] == {"unknown": 2} and result["verified_passes"] == 0
    assert result["observed_trial_completion_fraction"] is None


def test_task_and_trial_denominators_are_separate_and_worker_versions_do_not_merge(tmp_path, monkeypatch):
    context = {"request": {"artifact_store_root": str(tmp_path)},
               "task": {"case_id": "one-task", "feature_spec_ref": {"artifact_hash": "a" * 64}}}
    monkeypatch.setattr(comparison, "_task_context", lambda _: context)
    results = ["compile_failed", "upstream_requested", "format_failed", "passed"]
    def trial(row, _):
        index = int(row["run_id"])
        return {"outcome": results[index], "model": "one-model", "profile_sha256": "p",
                "worker_implementation_sha256": "old" if index < 3 else "new", "worker_policy_sha256": "q"}
    monkeypatch.setattr(comparison, "_trial", trial)
    indexes = [_index(str(index), [{"run_id": str(index), "journal_ref": {"path": str(tmp_path / str(index))}}]) for index in range(4)]
    result = comparison.compare_patch_trials(task_ref={}, attempt_indexes=indexes)
    assert result["task_denominator"] == 1 and result["trial_denominator"] == 4
    assert result["verified_passes"] == 1 and result["observed_trial_completion_fraction"] == 0.25
    assert [row["trial_count"] for row in result["groups"]] == [3, 1]
    assert result["models_qualified"] is result["qualification_published"] is False
    assert result["model_calls_performed"] == result["verifier_executions_performed"] == 0


def test_duplicate_trial_selectors_are_rejected_before_indexing():
    with pytest.raises(ValueError, match="unique_explicit_attempts_required"):
        comparison.compare_patch_trials(task_ref={}, attempt_indexes=[_index("same"), _index("same")])


def test_changed_source_is_unknown_not_a_failed_model_trial(tmp_path):
    policy = {"max_total_model_turns": 5}
    profile = {"model": "test", "provider": "test"}
    journal = {"factory_receipt": {"profile": profile, "model_call_count": 1,
        "qualification_execution_identity": {"implementation_sha256": canonical_hash({}), "files": {},
            "worker_policy_sha256": canonical_hash(policy), "scope": "test"}},
        "worker_profile_sha256": canonical_hash(profile), "worker_configuration_ref": {"path": "existing"},
        "generated_against_snapshot_sha256": "old", "current_snapshot_sha256": "old",
        "terminal_result": {"terminal_stage": "generate_patch_proposal"}}
    row = {"run_id": "one", "journal_ref": _save(tmp_path / "journal.json", journal),
           "reference_integrity_counts": {}, "journal_identity_checks": {
               "attempt_identity": {"status": "unverifiable"}, "terminal_result_hash": {"status": "verified"}}}
    context = {"worker": {"policy": policy}, "task": {"worker_configuration_ref": {"path": "existing"}},
               "snapshot": "changed"}
    result = comparison._trial(row, context)
    assert result["outcome"] == "unknown" and result["source_currentness"] == "unknown"
    assert "source_snapshot_changed" in result["unknown_reasons"]


def test_report_cli_refuses_to_overwrite_existing_history(tmp_path, monkeypatch):
    from scripts import compare_patch_trials as command

    task = tmp_path / "task.json"
    task.write_text("{}")
    existing = tmp_path / "existing-report.json"
    existing.write_text("retain historical bytes")
    reads = iter([{"continuation_input_ref": {}}, {"artifact_store_root": str(tmp_path)}])
    monkeypatch.setattr(command, "read_bound_json", lambda _: next(reads))
    monkeypatch.setattr(command, "project_patch_executions", lambda *args, **kwargs: _index("cr/one.json"))
    monkeypatch.setattr(command, "compare_patch_trials", lambda **kwargs: {"task_denominator": 1,
        "trial_denominator": 1, "outcomes": {"unknown": 1}})
    with pytest.raises(FileExistsError):
        command.main(["--task", str(task), "--attempt", "cr/one.json", "--output", str(existing)])
    assert existing.read_text() == "retain historical bytes"
