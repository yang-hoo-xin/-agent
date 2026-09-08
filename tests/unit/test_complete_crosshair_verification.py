"""Synthetic phase results validate public-worker feedback, not real Mod behavior."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.domain.complete_crosshair_verification import CompleteCrosshairVerification
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_fresh_planning_continuation import _inputs, _patch_request, _source_hashes
from tests.unit.test_patch_behavior_feedback import _adapter
from tests.unit.test_patch_recovery_worker import _InvestigatingClient


class _Identity:
    revision = 1

    def verification_identity(self):
        return {"validator_sha256": canonical_hash(type(self).__name__), "inputs_sha256": canonical_hash("fixed inputs"),
                "environment_sha256": canonical_hash(self.revision), "deterministic_reuse_allowed": False}


class _Compilation(_Identity):
    def __init__(self, root, mode="passed"):
        self.root, self.mode, self.contexts = root, mode, []

    def __call__(self, context):
        self.contexts.append(deepcopy(context))
        failed = self.mode == "compiler_once" and len(self.contexts) == 1
        environment = self.mode in ("restore", "timeout")
        status = "compilation_failed" if failed else "environment_failed" if environment else "passed"
        owner = "patch_implementation" if failed else "environment" if environment else None
        path = self.root / str(len(self.contexts))
        path.mkdir(parents=True)
        stdout = path / "stdout.txt"
        stdout.write_text("Behavior.cs(3,5): error CS0103: Unknown symbol." if failed else
                          "restore unavailable" if environment else "synthetic compile passed", encoding="utf-8")
        dll = path / "synthetic.dll"
        dll.write_bytes(b"test input, not executable")
        record = {"status": status, "all_required_files_compiled": not failed and not environment,
                  "built_artifact_ref": _ref(dll), "stdout_ref": _ref(stdout),
                  "materialized_code_identity": context["materialized_code_identity"]}
        record["report_ref"] = _save(path / "compile.json", record)
        return {"status": status, "failure_owner": owner, "changed": record,
                "baseline_compilation_performed_in_this_call": False}


class _Configuration(_Identity):
    def __init__(self, root, mode="passed"):
        self.root, self.mode, self.calls = root, mode, []

    def __call__(self, compilation):
        self.calls.append(deepcopy(compilation))
        failed = self.mode == "wrong_key_once" and len(self.calls) == 1
        row = {"check_id": "fresh.exact_keys", "expected": ["Accurate Spread Enabled"],
               "observed": ["Wrong switch"] if failed else ["Accurate Spread Enabled"], "passed": not failed}
        report = {"status": "behavior_failed" if failed else "passed", "failure_owner": "patch_implementation" if failed else None,
                  "checks": [row], "built_artifact_ref": compilation["built_artifact_ref"],
                  "runtime_status": "not_executed", "automatic_liveedit_status": "not_executed"}
        report["report_ref"] = _save(self.root / str(len(self.calls)) / "config.json", report)
        return report


class _Matrix(_Identity):
    def __init__(self, root, mode="passed", drift=None):
        self.root, self.mode, self.drift = root, mode, drift
        self.contexts, self.report_refs = [], []

    def __call__(self, context):
        self.contexts.append(deepcopy(context))
        incomplete = self.mode == "incomplete"
        checks = [] if incomplete else [{"check": f"original_{index:02}", "passed": True} for index in range(36)]
        matrix = {"checks": checks, "failures": [], "executions": 0 if incomplete else 40}
        path = self.root / str(len(self.contexts))
        matrix_ref = _save(path / "original-matrix.json", matrix)
        report = {"status": "infrastructure_failed" if incomplete else "passed", "failure_owner": "environment" if incomplete else None,
                  "owner_binding_ids": [], "observations": [], "verification_ref": matrix_ref,
                  "execution_origin": "incomplete" if incomplete else "executed",
                  "verification_summary": {"checks": len(checks), "failed_checks": 0, "executions": matrix["executions"]}}
        report_ref = _save(path / "original-report.json", report)
        self.report_refs.append(report_ref)
        if self.drift is not None:
            self.drift()
        return {**report, "report_ref": report_ref}


def _combined(tmp_path, *, compile_mode="passed", config_mode="passed", matrix_mode="passed"):
    compilation = _Compilation(tmp_path / "compile", compile_mode)
    configuration = _Configuration(tmp_path / "configuration", config_mode)
    matrix = _Matrix(tmp_path / "matrix", matrix_mode)
    wrapper = CompleteCrosshairVerification(compilation=compilation, configuration=configuration,
                                            matrix=matrix, output_root=tmp_path / "combined")
    return wrapper, compilation, configuration, matrix


def _context():
    return {"generated_changes": [{"edit_binding_id": "edit_binding_001"}], "generated_changes_sha256": "a" * 64,
            "source_snapshot_sha256": "b" * 64, "model_response": {"output_sha256": "c" * 64},
            "materialized_code_identity": {"code_sha256": "d" * 64}, "implementation_plan_ref": {"artifact_hash": "e" * 64}}


@pytest.mark.parametrize("phase", ["compilation", "configuration"])
def test_failing_phase_is_bound_to_current_code_and_prevents_later_checks(tmp_path, phase):
    wrapper, compilation, configuration, matrix = _combined(tmp_path,
        compile_mode="compiler_once" if phase == "compilation" else "passed",
        config_mode="wrong_key_once" if phase == "configuration" else "passed")
    context = _context()
    report = wrapper(context)
    assert report["status"] == "behavior_failed" and report["failure_owner"] == "patch_implementation"
    assert report["model_response_sha256"] == context["model_response"]["output_sha256"]
    assert report["materialized_code_identity"] == context["materialized_code_identity"]
    assert report["owner_binding_ids"] == ["edit_binding_001"]
    assert len(compilation.contexts) == 1 and len(configuration.calls) == int(phase == "configuration")
    assert not matrix.contexts and report["verification_summary"] == {"checks": 0, "failed_checks": 0, "executions": 0}
    assert report["execution_origin"] == "incomplete"
    assert report["validation_results"]["behavior_matrix"]["status"] == "not_executed"


def test_all_prerequisites_pass_then_original_36_matrix_remains_separate_and_unchanged(tmp_path):
    wrapper, compilation, configuration, matrix = _combined(tmp_path)
    report = wrapper(_context())
    assert report["status"] == "passed"
    assert len(compilation.contexts) == len(configuration.calls) == len(matrix.contexts) == 1
    assert report["verification_summary"] == {"checks": 36, "failed_checks": 0, "executions": 40}
    assert report["validation_results"]["configuration"]["checks_run"] == 1
    assert report["validation_results"]["runtime"]["status"] == "not_executed"
    assert report["validation_results"]["automatic_liveedit"]["status"] == "not_executed"
    for original in matrix.report_refs:
        assert _ref(original["path"]) == original
        saved = json.loads(Path(original["path"]).read_text(encoding="utf-8"))
        assert "validation_results" not in saved


def test_incomplete_original_matrix_is_not_promoted_to_executed(tmp_path):
    wrapper, _, _, _ = _combined(tmp_path, matrix_mode="incomplete")
    report = wrapper(_context())
    assert report["status"] == "infrastructure_failed" and report["failure_owner"] == "environment"
    assert report["execution_origin"] == "incomplete"


def test_component_identity_drift_stops_without_rewriting_original_reports(tmp_path):
    wrapper, _, configuration, matrix = _combined(tmp_path)
    matrix.drift = lambda: setattr(configuration, "revision", 2)
    with pytest.raises(ValueError, match="COMPLETE_VERIFICATION_IDENTITY_CHANGED"):
        wrapper(_context())
    assert matrix.report_refs and _ref(matrix.report_refs[0]["path"]) == matrix.report_refs[0]
    assert not list((tmp_path / "combined").rglob("report.json"))


@pytest.mark.parametrize("phase", ["compilation", "configuration"])
def test_public_worker_consumes_phase_failure_then_revises_through_same_loop(tmp_path, phase):
    inputs = _inputs(tmp_path / "task")
    before = _source_hashes(inputs.workspace)
    client = _InvestigatingClient()
    wrapper, compilation, configuration, matrix = _combined(tmp_path / "checks",
        compile_mode="compiler_once" if phase == "compilation" else "passed",
        config_mode="wrong_key_once" if phase == "configuration" else "passed")
    adapter = _adapter(inputs, client, wrapper)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(require_source_inspection=False,
        finalize_after_first_observation=False, enable_supporting_reads=True, max_total_model_turns=5)
    result = run_fresh_patch_continuation(_patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.status == "terminal", result.to_dict()
    assert client.investigated_failure and len(client.requests) == 4
    assert len(compilation.contexts) == 2 and len(matrix.contexts) == 1
    assert len(configuration.calls) == (1 if phase == "compilation" else 2)
    assert _source_hashes(inputs.workspace) == before
    feedback = next(message.content["validator_feedback"] for message in client.requests[-1].messages
        if isinstance(message.content, dict) and message.content.get("message_type") == "patch_behavior_correction")
    first = compilation.contexts[0]
    assert feedback["generated_changes_sha256"] == first["generated_changes_sha256"]
    assert feedback["failure_owner"] == "patch_implementation"
    assert any(message.role == "assistant" and isinstance(message.content, str)
        and hashlib.sha256(message.content.encode()).hexdigest() == first["model_response"]["output_sha256"]
        for message in client.requests[-1].messages)
    observation = feedback["observations"][0]
    if phase == "compilation":
        assert "CS0103" in observation["observed"]["stdout"]
    else:
        assert observation["check_id"] == "configuration.fresh.exact_keys"
        assert observation["observed"] == ["Wrong switch"]
    assert result.execution_counts["apply"] == result.execution_counts["build"] == result.execution_counts["runtime"] == 0


@pytest.mark.parametrize("failure", ["restore", "timeout"])
def test_public_worker_does_not_repair_business_code_for_environment_failure(tmp_path, failure):
    inputs = _inputs(tmp_path / "task")
    wrapper, compilation, configuration, matrix = _combined(tmp_path / "checks", compile_mode=failure)
    client = _InvestigatingClient()
    adapter = _adapter(inputs, client, wrapper)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(require_source_inspection=False,
        finalize_after_first_observation=False, enable_supporting_reads=True, max_total_model_turns=5)
    result = run_fresh_patch_continuation(_patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.status != "terminal" and result.patch_proposal_artifact is None
    assert len(client.requests) == 2 and len(compilation.contexts) == 1
    assert not configuration.calls and not matrix.contexts and not client.investigated_failure
    assert all(not any(isinstance(message.content, dict) and message.content.get("message_type") == "patch_behavior_correction"
                       for message in request.messages) for request in client.requests)
