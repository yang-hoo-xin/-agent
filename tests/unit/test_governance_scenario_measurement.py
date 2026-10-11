"""Checks for measurement omissions and a direct replay effect observation."""
import xml.etree.ElementTree as ET

from scripts.run_governance_scenarios import summarize


def _selection(*, expected=1):
    return [{"scenario_id": "fixture", "selectors": ["tests/unit/example.py::test_gate"],
             "expected_pytest_cases": expected, "applicable_metrics": ["false_allow"]}]


def test_measurement_missing_case_remains_unknown():
    result = summarize(_selection(), ET.fromstring("<testsuites/>"))
    metric = result["metrics"]["false_allow"]
    assert metric["applicable_scenarios"] == metric["unknown_scenarios"] == 1
    assert metric["observed_denominator"] == 0 and metric["rate"] is None


def test_measurement_failed_or_skipped_variation_does_not_earn_a_family_pass():
    for outcome in ("failure", "error", "skipped"):
        xml = ET.fromstring(
            '<testsuite><testcase classname="tests.unit.example" name="test_gate[one]"/>'
            '<testcase classname="tests.unit.example" name="test_gate[two]">'
            f"<{outcome}/></testcase></testsuite>"
        )
        result = summarize(_selection(expected=2), xml)
        assert result["passed_scenario_count"] == 0
        assert result["metrics"]["false_allow"]["unknown_scenarios"] == 1
        assert result["metrics"]["false_allow"]["rate"] is None
        assert result["scenarios"][0]["testcase_results"][1]["status"] == outcome


def test_measurement_changed_parameter_count_cannot_silently_change_denominator():
    xml = ET.fromstring(
        '<testsuite><testcase classname="tests.unit.example" name="test_gate[one]"/>'
        '<testcase classname="tests.unit.example" name="test_gate[two]"/></testsuite>'
    )
    incomplete = summarize(_selection(), xml)
    assert incomplete["metrics"]["false_allow"]["observed_denominator"] == 0
    complete = summarize(_selection(expected=2), xml)
    assert complete["metrics"]["false_allow"]["observed_denominator"] == 1
    assert complete["passed_scenario_count"] == 1


def test_deferred_duplicate_resume_has_one_physical_apply_and_one_apply_artifact(tmp_path, monkeypatch):
    from src.mod_agent.execution import ExactTextPatchApplier
    from src.mod_agent.reviewed_patch_continuation import resume_deferred_approval
    from tests.unit.test_deferred_product_approval import _pending_case

    case, pending, payload, human = _pending_case(tmp_path)
    original = ExactTextPatchApplier.run
    write_attempts = []

    def observe_apply(self, *args, **kwargs):
        if kwargs.get("allow_write"):
            write_attempts.append(kwargs["workspace_root"])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ExactTextPatchApplier, "run", observe_apply)
    options = {"artifact_store_root": str(case.store.root), "checkpoint_ref": pending.checkpoint_ref,
               "resume_payload": payload, "human_semantic_decision": human}
    first = resume_deferred_approval(**options)
    assert first["status"] == "applied_in_isolation"
    assert len(write_attempts) == 1
    assert case.target.read_bytes() == case.source_after
    before_replay = case.target.read_bytes()
    repeated = resume_deferred_approval(**options)
    assert repeated["status"] == "blocked"
    assert repeated["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"
    assert len(write_attempts) == 1
    assert case.target.read_bytes() == before_replay
    assert case.canonical.read_bytes() == case.canonical_before
    assert len(case.store.list_feature_artifact_revisions(
        pending.checkpoint_ref.feature_id, "isolated_apply_result")) == 1
