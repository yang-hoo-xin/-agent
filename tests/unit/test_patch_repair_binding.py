"""Deterministic cross-attempt verification binding; all generation inputs are synthetic."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationError,
    _patch_attempt_identity,
    bind_patch_repair_verification,
    preflight_patch_continuation,
)
from tests.unit.test_patch_repair_continuation import _repair_case


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_json(path, value):
    path.write_bytes(_bytes(value))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _binding_case(tmp_path, *, different=True):
    """Build explicit synthetic source/verification records, without invoking the binder."""
    inputs, recovery, parent = _repair_case(tmp_path)
    formal = preflight_patch_continuation(recovery)
    request = replace(recovery, attempt_id="synthetic-bound-repair",
        repair_parent_proposal_ref=None, repair_parent_review_ref=None, repair_parent_response_ref=None,
        repair_parent_attempt_ref=None, repair_failure_report_ref=None)
    parent_journal = json.loads(Path(parent.attempt_receipt["path"]).read_text(encoding="utf-8"))
    response = deepcopy(parent_journal["factory_receipt"]["model_response"])
    raw = json.loads(Path(response["path"]).read_text(encoding="utf-8"))
    if different:
        for change in raw["changes"]:
            change["after_text"] = change["after_text"].replace("RecordRuntimeMarker", "RecordMissingMarker")
    failed_path = tmp_path / "source-current-response.txt"
    failed_path.write_bytes(_bytes(raw))
    failed_ref = {"path": str(failed_path), "sha256": hashlib.sha256(failed_path.read_bytes()).hexdigest()}
    response.update(path=str(failed_path), output_sha256=failed_ref["sha256"], output_utf8_bytes=len(failed_path.read_bytes()))
    changes = deepcopy(formal.repair_context["failed_diff_intent"])
    after_by_binding = {item["edit_binding_id"]: item["after_text"] for item in raw["changes"]}
    for change in changes:
        change["patch"]["after_text"] = after_by_binding[change["edit_binding_id"]]
    current = materialize_exact_text_patch(workspace_root=inputs.workspace, diff_intent=changes,
        implementation_plan=formal.implementation_plan)
    code_identity = {"baseline_sha256": current.baseline_sha256, "code_sha256": current.code_sha256,
                     "files": sorted(current.files)}
    native_hash = hashlib.sha256(_bytes(changes)).hexdigest()
    source = deepcopy(parent_journal)
    source.update(run_id="synthetic-unadmitted-source", status="continuation_failed", proposal_admitted=False,
        artifacts={}, repair_context={key: value for key, value in formal.repair_context.items()
            if key not in {"previous_response", "failure_report", "failed_diff_intent"}})
    source["factory_receipt"]["model_response"] = response
    source_ref = _write_json(tmp_path / "source-attempt.json", source)
    callback = {"evaluation_index": 1, "generated_changes": changes,
        "generated_changes_sha256": native_hash, "model_response": response,
        "source_snapshot_sha256": formal.repair_context["source_snapshot_sha256"],
        "materialized_code_identity": code_identity, "verification_identity": None}
    callback_ref = _write_json(tmp_path / "source-callback.json", callback)
    # Executed Python predicate over these exact materialized inputs, not C#/Runtime.
    observed = all("RecordRepairMarker();" in item["patch"]["after_text"] for item in changes)
    assert observed is False
    check = {"check": "synthetic_required_marker", "passed": observed,
             "expected": True, "actual": observed}
    matrix = {"status": "synthetic_static_check_failed", "executions": 1,
        "source_provenance_verified": True, "checks": [check], "failures": [check], "observations": {}}
    matrix_ref = _write_json(tmp_path / "executed-matrix.json", matrix)
    observations = [{"check_id": check["check"], "input": {"required_marker": "RecordRepairMarker"},
        "expected": True, "observed": observed,
        "observed_state": {"runtime_marker_present": all("RecordRuntimeMarker();" in c["patch"]["after_text"] for c in changes)},
        "result_ref": matrix_ref}]
    report = {"status": "behavior_failed", "failure_owner": "patch_implementation",
        "owner_binding_ids": [changes[0]["edit_binding_id"]], "observations": observations,
        "generated_changes_sha256": native_hash, "source_snapshot_sha256": callback["source_snapshot_sha256"],
        "materialized_code_identity": code_identity, "execution_origin": "executed", "callback_invoked": True,
        "verification_ref": matrix_ref, "verification_summary": {"checks": 1, "executions": 1, "failed_checks": 1}}
    report_ref = _write_json(tmp_path / "executed-feedback.json", report)
    configuration_ref = _write_json(tmp_path / "verification-configuration.json", {
        "purpose": "test-only deterministic Python marker check; no model or Runtime",
        "behavior_evaluator": {"kwargs": {"plan_ref": asdict(request.implementation_plan_ref), "source_root": str(inputs.workspace)}}})
    verification = {"model_calls": 0, "source_unchanged": True, "original_callback_ref": callback_ref,
        "original_model_response": response, "configuration": configuration_ref,
        "behavior_report": {**report, "report_ref": report_ref}}
    verification_ref = _write_json(tmp_path / "verification-only-result.json", verification)
    return {"inputs": inputs, "request": request, "parent": parent, "source_attempt_ref": source_ref,
        "verification_result_ref": verification_ref, "failed_response_ref": failed_ref,
        "current_changes": changes, "source": source, "verification": verification, "observations": observations}


@pytest.mark.parametrize("different", [False, True])
def test_binding_revalidates_current_output_without_promoting_it_to_formal_parent(tmp_path, different):
    case = _binding_case(tmp_path, different=different)
    bound = bind_patch_repair_verification(request=case["request"], source_attempt_ref=case["source_attempt_ref"],
        verification_result_ref=case["verification_result_ref"])
    admitted = preflight_patch_continuation(bound)
    context = admitted.repair_context
    assert context["failed_diff_intent"] == case["current_changes"]
    assert context["failed_response_ref"] == case["failed_response_ref"]
    assert context["previous_response"] == Path(case["failed_response_ref"]["path"]).read_text(encoding="utf-8")
    assert context["parent_response_ref"] != context["failed_response_ref"]
    assert bound.repair_parent_proposal_ref == ArtifactRef(**case["parent"].patch_proposal_artifact)
    report = context["failure_report"]
    assert report["observations"] == case["observations"]
    assert report["code_revision"]["same_materialized_code"] is (not different)
    assert report["code_revision"]["different_code_is_not_proof_of_repair"] is True
    assert report["execution_origin"] == "unknown" and report["callback_invoked"] is False
    assert report["derivation"]["new_model_calls"] == report["derivation"]["new_verifier_executions"] == 0


def test_binding_is_content_addressed_independent_of_consumer_attempt_id(tmp_path):
    case = _binding_case(tmp_path)
    first = bind_patch_repair_verification(request=case["request"], source_attempt_ref=case["source_attempt_ref"],
        verification_result_ref=case["verification_result_ref"])
    before = Path(first.repair_failure_report_ref["path"]).read_bytes()
    second = bind_patch_repair_verification(request=replace(case["request"], attempt_id="another-consumer"),
        source_attempt_ref=case["source_attempt_ref"], verification_result_ref=case["verification_result_ref"])
    assert first.repair_failure_report_ref == second.repair_failure_report_ref
    assert Path(first.repair_failure_report_ref["path"]).read_bytes() == before


def test_already_admitted_source_proposal_can_be_the_direct_formal_parent(tmp_path):
    case = _binding_case(tmp_path, different=False)
    source_ref = {key: case["parent"].attempt_receipt[key] for key in ("path", "sha256")}
    source = json.loads(Path(source_ref["path"]).read_text(encoding="utf-8"))
    response = source["factory_receipt"]["model_response"]
    verification = case["verification"]
    callback_ref = verification["original_callback_ref"]
    callback = json.loads(Path(callback_ref["path"]).read_text(encoding="utf-8"))
    callback["model_response"] = response
    verification["original_callback_ref"] = _write_json(Path(callback_ref["path"]), callback)
    verification["original_model_response"] = response
    verification_ref = _write_json(Path(case["verification_result_ref"]["path"]), verification)
    bound = bind_patch_repair_verification(request=case["request"], source_attempt_ref=source_ref,
        verification_result_ref=verification_ref)
    context = preflight_patch_continuation(bound).repair_context
    assert context["parent_attempt_ref"] == source_ref
    assert context["failed_response_ref"] == context["parent_response_ref"]
    assert context["failure_report"]["code_revision"]["same_materialized_code"] is True


@pytest.mark.parametrize("mutation", ["wrong_source", "wrong_plan", "configuration_plan", "wrong_callback", "not_executed", "matrix", "response_bytes"])
def test_binding_rejects_wrong_source_or_unverified_facts(tmp_path, mutation):
    case = _binding_case(tmp_path)
    source_ref, verification_ref = case["source_attempt_ref"], case["verification_result_ref"]
    if mutation == "wrong_source":
        source_ref = {"path": case["parent"].attempt_receipt["path"], "sha256": case["parent"].attempt_receipt["sha256"]}
    elif mutation == "wrong_plan":
        case["source"]["selected_artifacts"]["implementation_plan"]["artifact_hash"] = "0" * 64
        source_ref = _write_json(Path(source_ref["path"]), case["source"])
    elif mutation == "configuration_plan":
        ref = case["verification"]["configuration"]
        configuration = json.loads(Path(ref["path"]).read_text(encoding="utf-8"))
        configuration["behavior_evaluator"]["kwargs"]["plan_ref"]["artifact_hash"] = "0" * 64
        case["verification"]["configuration"] = _write_json(Path(ref["path"]), configuration)
        verification_ref = _write_json(Path(verification_ref["path"]), case["verification"])
    elif mutation == "wrong_callback":
        callback_ref = case["verification"]["original_callback_ref"]
        callback = json.loads(Path(callback_ref["path"]).read_text())
        callback["generated_changes_sha256"] = "0" * 64
        case["verification"]["original_callback_ref"] = _write_json(Path(callback_ref["path"]), callback)
        verification_ref = _write_json(Path(verification_ref["path"]), case["verification"])
    elif mutation == "not_executed":
        report = case["verification"]["behavior_report"]
        report["execution_origin"] = "unknown"
        report["report_ref"] = _write_json(Path(report["report_ref"]["path"]), {k: v for k, v in report.items() if k != "report_ref"})
        verification_ref = _write_json(Path(verification_ref["path"]), case["verification"])
    elif mutation == "matrix":
        matrix_ref = case["verification"]["behavior_report"]["verification_ref"]
        Path(matrix_ref["path"]).write_bytes(b"{}")
    else:
        Path(case["failed_response_ref"]["path"]).write_bytes(b"{}")
    with pytest.raises(PatchContinuationError):
        bind_patch_repair_verification(request=case["request"], source_attempt_ref=source_ref,
            verification_result_ref=verification_ref)
    assert not list(case["inputs"].store.root.glob("cr/rv-*.json"))


def test_preflight_rechecks_bound_source_files_instead_of_trusting_preparation(tmp_path):
    case = _binding_case(tmp_path)
    bound = bind_patch_repair_verification(request=case["request"], source_attempt_ref=case["source_attempt_ref"],
        verification_result_ref=case["verification_result_ref"])
    Path(case["verification_result_ref"]["path"]).write_bytes(b"{}")
    with pytest.raises(PatchContinuationError, match="PATCH_REPAIR_FILE_HASH_MISMATCH"):
        preflight_patch_continuation(bound)


def test_unbound_attempt_identity_keeps_pre_binding_schema(tmp_path):
    case = _binding_case(tmp_path)
    payload = asdict(case["request"])
    for key in ("worker_configuration_ref", "worker_profile_sha256", "repair_source_attempt_ref", "repair_verification_ref", "qualified_model_routing_ref"):
        payload.pop(key)
    expected = hashlib.sha256(_bytes({"request": payload, "max_model_calls": 5})).hexdigest()
    assert _patch_attempt_identity(case["request"], 5) == expected
