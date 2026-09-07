"""Synthetic Plan changes exercise existing matrix composition, never GTFO execution."""
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.domain.accurate_crosshair_eval import _save
from src.mod_agent.domain.accurate_crosshair_revalidation import CurrentPlanExistingMatrixOracle
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _patch_request,
    _PatchAgentTurnClient,
    _source_hashes,
)
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle


def _case(tmp_path, monkeypatch, *, failed=False, owner_matches=True, compiled=True):
    inputs = _inputs(tmp_path / "task")
    request = _patch_request(inputs)
    old_plan = inputs.store.read(request.implementation_plan_ref)["data"]
    collector = _BehaviorOracle(tmp_path / "captured")
    adapter = _adapter(inputs, _PatchAgentTurnClient(), collector)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy()
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.status == "terminal", result.to_dict()
    context = deepcopy(collector.contexts[0])
    assert context["implementation_plan_ref"] == asdict(request.implementation_plan_ref)
    # Same exact source target, a different admitted Plan and binding ID.
    plan = json.loads(json.dumps(old_plan).replace('"edit_binding_001"', '"edit_binding_new"'))
    plan_ref = inputs.store.write(feature_id=request.feature_spec_ref.feature_id,
        artifact_type="implementation_plan", payload=plan,
        upstream_refs=[inputs.feature_ref, inputs.evidence_ref])
    context["implementation_plan"] = plan
    context["implementation_plan_ref"] = asdict(plan_ref)
    context["generated_changes"] = json.loads(json.dumps(context["generated_changes"]).replace('"edit_binding_001"', '"edit_binding_new"'))
    context["generated_changes_sha256"] = canonical_hash(context["generated_changes"])
    inspector = PlanBoundSourceInspector(workspace_root=inputs.workspace, implementation_plan=plan,
                                        policy=PatchAgentLoopPolicy())
    context["source_snapshot_sha256"] = inspector.source_snapshot_sha256
    raw = json.loads(Path(context["model_response"]["path"]).read_text(encoding="utf-8"))
    raw["changes"][0]["edit_binding_id"] = "edit_binding_new"
    response_ref = _save(tmp_path / "new-model-response.json", raw)
    context["model_response"] = {"path": response_ref["path"], "output_sha256": response_ref["sha256"],
                                 "output_utf8_bytes": Path(response_ref["path"]).stat().st_size}
    materialized = materialize_exact_text_patch(workspace_root=inputs.workspace,
        diff_intent=context["generated_changes"], implementation_plan=plan)
    context["materialized_code_identity"] = {"baseline_sha256": materialized.baseline_sha256,
        "code_sha256": materialized.code_sha256, "files": sorted(materialized.files)}
    baseline_hashes = _source_hashes(inputs.workspace)
    checks = [f"original-check-{i:02}" for i in range(36)]
    executions = []
    original_binding = deepcopy(old_plan["binding_registry"]["edit_bindings"][0])
    if not owner_matches:
        original_binding["target_span"] = {"start_line": 1, "end_line": 1}

    class Legacy:
        source_root = inputs.workspace
        plan_ref = asdict(request.implementation_plan_ref)
        bindings = {"edit_binding_001": original_binding}
        baseline = {"source_sha256": baseline_hashes}
        compiled_paths = tuple(baseline_hashes) if compiled else ()

        def __init__(self, output):
            self.harness = Path(output) / "harness"
            self.harness.mkdir(parents=True, exist_ok=True)

        def _current_sources(self):
            if _source_hashes(inputs.workspace) != baseline_hashes:
                raise ValueError("CANONICAL_SOURCE_CHANGED")
            return {p: (inputs.workspace / p).read_bytes() for p in baseline_hashes}

        def _execute(self, run, report):
            executions.append(run)
            rows = [{"check": name, "expected": True, "actual": not (failed and index == 0),
                     "passed": not (failed and index == 0)} for index, name in enumerate(checks)]
            failures = [row for row in rows if not row["passed"]]
            for name in ("baseline", "product_proposal"):
                _save(run / f"compile_{name}.json", {"exit_code": 0})
            _save(run / "matrix_execution.json", {"exit_code": int(failed)})
            matrix_ref = _save(run / "acceptance_results.json", {"checks": rows, "failures": failures, "executions": 40})
            return {**report, "status": "behavior_failed" if failed else "passed",
                "failure_owner": "patch_implementation" if failed else None,
                "owner_binding_ids": ["edit_binding_001"] if failed else [],
                "verification_ref": matrix_ref,
                "verification_summary": {"checks": 36, "failed_checks": int(failed), "executions": 40}}

    config = _save(tmp_path / "original-worker.json", {"behavior_evaluator": {
        "kwargs": {"output_root": str(tmp_path / "original-matrix")}}})

    def load(path):
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        def evaluator():
            legacy = Legacy(cfg["behavior_evaluator"]["kwargs"]["output_root"])
            return SimpleNamespace(prepare_for_patch_attempt=lambda: None,
                                   _get_delegate=lambda: SimpleNamespace(delegate=legacy))
        return SimpleNamespace(behavior_evaluator=evaluator)

    monkeypatch.setattr("src.mod_agent.patch_worker_configuration.PatchWorkerConfiguration.load", load)
    oracle = CurrentPlanExistingMatrixOracle(artifact_store_root=inputs.store.root,
        configuration_ref=config, identity_refs={key: [config] for key in ("validator", "inputs", "environment")},
        expected_check_ids=checks, output_root=tmp_path / "reports")
    return inputs, context, oracle, executions, checks


def test_new_plan_exact_binding_reaches_original_matrix_with_independent_outputs(tmp_path, monkeypatch):
    inputs, context, oracle, executions, checks = _case(tmp_path, monkeypatch)
    before = _source_hashes(inputs.workspace)
    first = oracle(context)
    assert first["status"] == "passed" and first["execution_origin"] == "executed"
    assert first["implementation_plan_ref"] == context["implementation_plan_ref"]
    matrix = json.loads(Path(first["verification_ref"]["path"]).read_text(encoding="utf-8"))
    assert [row["check"] for row in matrix["checks"]] == checks
    assert matrix["materialized_code_identity"] == context["materialized_code_identity"]
    copied = tmp_path / "next-model-response.json"
    copied.write_bytes(Path(context["model_response"]["path"]).read_bytes())
    second = oracle({**context, "model_response": {**context["model_response"], "path": str(copied)}})
    assert Path(first["report_ref"]["path"]).parent != Path(second["report_ref"]["path"]).parent
    assert len(executions) == 2 and _source_hashes(inputs.workspace) == before


@pytest.mark.parametrize("matches,expected_owner", [(True, "patch_implementation"), (False, "unknown")])
def test_legacy_failure_owner_requires_exact_target_correspondence(tmp_path, monkeypatch, matches, expected_owner):
    _, context, oracle, _, _ = _case(tmp_path, monkeypatch, failed=True, owner_matches=matches)
    report = oracle(context)
    assert report["failure_owner"] == expected_owner
    assert report["owner_binding_ids"] == (["edit_binding_new"] if matches else [])


@pytest.mark.parametrize("drift", ["source", "plan_context", "code"])
def test_changed_input_is_rejected_before_matrix_execution(tmp_path, monkeypatch, drift):
    inputs, context, oracle, executions, _ = _case(tmp_path, monkeypatch)
    if drift == "source":
        inputs.behavior.write_bytes(inputs.behavior.read_bytes() + b"\n// drift")
    elif drift == "plan_context":
        context["implementation_plan"]["side_effect_boundaries"].append("changed context")
    else:
        context["materialized_code_identity"]["code_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        oracle(context)
    assert not executions


def test_uncovered_new_target_does_not_get_a_matrix_pass(tmp_path, monkeypatch):
    _, context, oracle, executions, _ = _case(tmp_path, monkeypatch, compiled=False, owner_matches=False)
    with pytest.raises(ValueError, match="PATCH_EVAL_SOURCE_COVERAGE_INCOMPLETE"):
        oracle(context)
    assert not executions
