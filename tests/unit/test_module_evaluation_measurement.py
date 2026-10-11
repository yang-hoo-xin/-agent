"""Counterexamples protecting module/case/attempt measurement boundaries."""
import json

import pytest

from scripts.run_module_evaluation import aggregate, owner, read_manifest, summarize_events


SPEC = {"nodeid": "tests/unit/test_example.py::test_case", "module_id": "example",
        "scenario_id": "boundary", "assertion": "known outcome", "evidence_kind": "contract"}


def events(status="passed", *, phases=("setup", "call", "teardown")):
    name = SPEC["nodeid"]
    return [{"kind": "collected", "nodeids": [name]}, {"kind": "started", "nodeid": name},
            *[{"kind": "phase", "nodeid": name, "phase": phase,
               "outcome": status if phase == "call" else "passed", "duration_seconds": 0.1}
              for phase in phases]]


def test_missing_and_partial_execution_cannot_be_success():
    missing = summarize_events([], [SPEC])
    assert missing["started_cases"] == 0
    assert missing["missing_selectors"] == [SPEC["nodeid"]]
    partial = summarize_events(events(phases=("setup",)), [SPEC])
    assert partial["status_counts"] == {"incomplete": 1}
    assert partial["call_executions"] == 0


@pytest.mark.parametrize("outcome", ["failed", "skipped"])
def test_nonpass_preserved_in_denominator(outcome):
    result = summarize_events(events(outcome), [SPEC])
    assert result["started_cases"] == result["call_executions"] == 1
    assert result["status_counts"] == {outcome: 1}


def test_teardown_error_does_not_earn_case_pass():
    rows = events()
    rows[-1]["outcome"] = "failed"
    assert summarize_events(rows, [SPEC])["status_counts"] == {"error": 1}


def test_duplicate_execution_and_overlapping_ownership_rejected():
    rows = events()
    rows.append({"kind": "started", "nodeid": SPEC["nodeid"]})
    with pytest.raises(ValueError, match="Duplicate case"):
        summarize_events(rows, [SPEC])
    with pytest.raises(ValueError, match="overlapping"):
        owner(SPEC["nodeid"] + "[one]", [SPEC, {**SPEC, "nodeid": SPEC["nodeid"] + "[one]"}])


def test_repeats_add_attempts_not_unique_cases(tmp_path):
    paths = []
    for number, outcome in enumerate(("failed", "passed")):
        result = summarize_events(events(outcome), [SPEC])
        result.update(elapsed_seconds=1, receipt_sha256=str(number), source_binding_stable=True)
        path = tmp_path / f"run{number}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        paths.append(path)
    result = aggregate(paths)
    assert result["unique_started_cases"] == result["unique_passed_cases"] == 1
    assert result["case_attempts"] == result["batch_invocations"] == 2
    assert result["case_status_counts"] == {"failed": 1, "passed": 1}
    with pytest.raises(ValueError, match="Duplicate run"):
        aggregate([paths[0], paths[0]])


def test_manifest_rejects_duplicate_or_escaped_selection(tmp_path):
    path = tmp_path / "selection.json"
    for nodes in ([SPEC, SPEC], [{**SPEC, "nodeid": "tests/../../secret.py::test_case"}]):
        path.write_text(json.dumps({"nodes": nodes}), encoding="utf-8")
        with pytest.raises(ValueError):
            read_manifest(path)
