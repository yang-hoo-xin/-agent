"""Exact public receipt contracts only; never construct a sealed oracle."""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.mod_agent.evaluation.independent_product_adapter import project_owned_judge_result


def public_record():
    context = {"materialized_code_identity": {"baseline_sha256": "base", "code_sha256": "code", "files": ["Subject.cs"]},
               "generated_changes_sha256": "changes", "source_snapshot_sha256": "source",
               "model_response": {"output_sha256": "response"}}
    identity = {"validator_sha256": "validator", "inputs_sha256": "inputs", "environment_sha256": "environment",
                "deterministic_reuse_allowed": False}
    record = {**{key: value for key, value in context.items() if key != "model_response"},
        "status": "passed", "model_response_sha256": "response", "verification_identity": identity,
        "observations": [{"check_id": "public_detail", "expected": "DO_NOT_PROJECT", "observed": "DO_NOT_PROJECT"}],
        "verification_summary": {"checks": 3, "failed_checks": 0, "executions": 1},
        "execution_origin": "executed", "preservation_passed": True,
        "report_ref": {"path": "DO_NOT_PROJECT", "sha256": "receipt"}}
    return context, identity, record


@pytest.mark.parametrize("status,compile_failure,outcome,success", [
    ("passed", False, "success", True),
    ("behavior_failed", False, "behavior_failed", False),
    ("behavior_failed", True, "compilation_failed", False),
    ("infrastructure_failed", False, "execution_error", None),
])
def test_existing_judge_statuses_are_separate_without_private_details(status, compile_failure, outcome, success):
    context, identity, record = public_record()
    record["status"] = status
    if status == "behavior_failed" and not compile_failure:
        record["verification_summary"]["failed_checks"] = 1
    if compile_failure or status == "infrastructure_failed":
        record["verification_summary"] = {"checks": 0, "failed_checks": 0, "executions": 0}
        record["execution_origin"] = "incomplete"
        record["preservation_passed"] = None
    if compile_failure:
        record["observations"] = [{"check_id": "csharp_compilation", "observed": "DO_NOT_PROJECT"}]
    result = project_owned_judge_result(record, context=context, verification_identity=identity)
    assert result["outcome"] == outcome and result["task_success"] is success
    assert "DO_NOT_PROJECT" not in repr(result)
    assert "observations" not in result and "report_ref" not in result


@pytest.mark.parametrize("field", ["materialized_code_identity", "generated_changes_sha256", "source_snapshot_sha256",
                                   "model_response_sha256", "verification_identity"])
def test_judge_response_must_bind_original_submission_and_environment(field):
    context, identity, record = public_record()
    record = deepcopy(record)
    record[field] = "drift"
    with pytest.raises(ValueError):
        project_owned_judge_result(record, context=context, verification_identity=identity)


@pytest.mark.parametrize("field,value", [("execution_origin", "incomplete"), ("preservation_passed", None),
    ("verification_summary", {"checks": 0, "failed_checks": 0, "executions": 0})])
def test_receipt_cannot_promote_unexecuted_success(field, value):
    context, identity, record = public_record()
    record[field] = value
    with pytest.raises(ValueError, match="Success lacks"):
        project_owned_judge_result(record, context=context, verification_identity=identity)
