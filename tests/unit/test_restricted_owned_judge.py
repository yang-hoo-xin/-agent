"""Host judgment boundaries with controlled process receipts; no Docker/model calls."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evaluation import restricted_csharp as runtime
from src.mod_agent.evaluation import restricted_owned_judge as judge
from src.mod_agent.evidence import RgLiveEvidenceProvider
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.planning import FeatureSpec, ImplementationPlan, ImplementationPlanner
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector

PRIVATE_VALUE = "host-private-expectation-not-for-candidate"
SOURCE = b"public sealed class ExportPipeline\n{\n    public int Apply()\n    {\n        return 0;\n    }\n}\n"


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    return runtime._save(path, value)


def _read(reference):
    return json.loads(Path(reference["path"]).read_text(encoding="utf-8"))


def _fixture(tmp_path, *, source_bytes=SOURCE, replacement=None, cases=None):
    workspace = tmp_path / "public"
    source = workspace / "generated_mods/Lease/Subject.cs"
    source.parent.mkdir(parents=True)
    source.write_bytes(source_bytes)
    store = ArtifactStore(workspace / "artifacts")
    evidence = RgLiveEvidenceProvider(workspace).collect(query="Apply", search_root="generated_mods").to_artifact_payload()
    binding = ImplementationPlanner._edit_binding(index=1, item=evidence["items"][0])
    before = evidence["items"][0]["excerpt"]
    change = {"change_id": "developer_control", "change_type": "modify", "edit_binding_id": binding["binding_id"],
        "operation": "controlled fixture", "rationale": "unit test, no model",
        "evidence_refs": [binding["evidence_id"]], "expected_validation": ["declared checks"],
        "rollback_hint": "temporary fixture only", "patch": {"kind": "exact_text_replace",
            "before_text": before, "after_text": replacement(before) if replacement else before.replace("return 0;", "return 1;"),
            "expected_occurrences": 1, "match_mode": "bound_span_exact"}}
    feature = FeatureSpec(feature_id="unit_feature", user_request="controlled unit task", target_behavior="unit behavior",
        target_mod="Lease", risk_level="low", acceptance_criteria=("checks",), non_goals=(),
        evidence_requirements=("current source",), runtime_verification_plan=("observations",))
    feature_ref = store.write(feature_id=feature.feature_id, artifact_type="feature_spec", payload=feature.to_artifact_payload())
    evidence_ref = store.write(feature_id=feature.feature_id, artifact_type="evidence_pack", payload=evidence, upstream_refs=[feature_ref])
    plan = ImplementationPlan(feature_id=feature.feature_id, target_files=(binding["canonical_target_path"],),
        target_symbols=(binding["target_symbol"],), evidence_refs=(binding["evidence_id"],),
        evidence_source_paths=(binding["canonical_target_path"],), proposed_changes=(change,),
        side_effect_boundaries=("temporary source only",), test_plan=("checks",), rollback_plan=("discard fixture",),
        binding_registry={"schema_version": "binding_registry_v1", "edit_bindings": [binding], "supporting_bindings": []}).to_artifact_payload()
    plan_ref = store.write(feature_id=feature.feature_id, artifact_type="implementation_plan", payload=plan, upstream_refs=[feature_ref, evidence_ref])
    submitted = _save(workspace / "response.json", {"changes": [{"edit_binding_id": binding["binding_id"], "after_text": change["patch"]["after_text"]}]})
    inspector = PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan, policy=PatchAgentLoopPolicy())
    materialized = materialize_exact_text_patch(workspace_root=workspace, implementation_plan=plan, diff_intent=[change])
    context = {"implementation_plan_ref": asdict(plan_ref), "implementation_plan": plan,
        "generated_changes": [change], "generated_changes_sha256": canonical_hash([change]),
        "source_snapshot_sha256": inspector.source_snapshot_sha256,
        "materialized_code_identity": {"baseline_sha256": materialized.baseline_sha256,
            "code_sha256": materialized.code_sha256, "files": sorted(materialized.files)},
        "model_response": {"path": submitted["path"], "output_sha256": submitted["sha256"],
                           "output_utf8_bytes": Path(submitted["path"]).stat().st_size}}
    case_ref = _save(tmp_path / "private/cases.json", cases or {"schema_version": "lease_scope_trusted_cases_v1",
        "task_id": judge.TASK_ID, "eligibility": "development_only_not_held_out_after_adapter_design",
        "cases": [{"case_id": "host-only-label", "operation": {"Records": ["public-input"]},
            "assertions": [{"path": ["active"], "equals": 0}, {"path": ["events", 0], "equals": PRIVATE_VALUE}]}]})
    kwargs = {"workspace_root": str(workspace), "artifact_store_root": str(store.root),
        "source_files": {source.relative_to(workspace).as_posix(): hashlib.sha256(source_bytes).hexdigest()},
        "cases_ref": case_ref, "output_root": str(workspace / "reports"), "private_output_root": str(tmp_path / "private/executions")}
    return kwargs, context, source


def _controlled_runtime(monkeypatch, *, observation=None, mode="normal"):
    calls = {"sources": [], "operations": []}

    def execution():
        return {"image": runtime.IMAGE, "inspect_policy_verified": True, "container_id": "c" * 64,
            "implementation_ref": runtime._ref(Path(runtime.__file__)), "completed": True,
            "container_state": {"Running": False, "ExitCode": 0}, "exit_code": 0, "stdout": "", "stderr": ""}

    def compile_source(*, sources, output_root):
        calls["sources"].append(deepcopy(sources))
        if mode == "compile_host_error":
            raise OSError("Docker unavailable before a candidate process was created")
        root = Path(output_root)
        root.mkdir(parents=True)
        record = execution()
        succeeded = mode != "compile_failure"
        if not succeeded:
            record.update(exit_code=1, stdout="/inputs/Subject.cs: error CS1002")
        execution_ref = _save(root / "execution.json", record)
        (root / "Subject.dll").write_bytes(b"controlled unit binary; no compiler")
        binary = runtime._ref(root / "Subject.dll")
        receipt = _save(root / "compilation.json", {"image": runtime.IMAGE, "succeeded": succeeded,
            "source_manifest": {**{name: runtime._hash(value) for name, value in sources.items()},
                "sources.rsp": runtime._hash("\n".join("/inputs/" + name for name in sorted(sources)).encode())},
            "execution_ref": execution_ref})
        return runtime.CSharpCompilation(str(root), succeeded, binary if succeeded else None, None, receipt)

    def run_source(*, compilation, operation, output_root):
        calls["operations"].append(deepcopy(operation))
        result = execution()
        result.update(stdout=json.dumps(observation if observation is not None else {"active": 0, "events": [PRIVATE_VALUE]}),
            stdin_sha256=canonical_hash(operation), compilation_receipt_ref=compilation.receipt_ref,
            host_judge_material_mounted=False)
        if mode == "missing_inspect":
            result["inspect_policy_verified"] = False
        elif mode == "wrong_operation":
            result["stdin_sha256"] = "0" * 64
        elif mode == "invalid_json":
            result["stdout"] = '{"active":0,"active":1}'
        elif mode == "timeout":
            result.update(completed=False, exit_code=None, timed_out=True)
        elif mode == "transport_incomplete":
            result.update(completed=False, exit_code=None, timed_out=False, output_limit_exceeded=False)
        elif mode == "host_error":
            raise OSError("private host path and expected values must not escape")
        result["receipt_ref"] = _save(Path(output_root) / "run.json", result)
        return result

    monkeypatch.setattr(runtime, "compile_csharp", compile_source)
    monkeypatch.setattr(runtime, "run_csharp", run_source)
    return calls


def test_normal_worker_factory_materializes_and_keeps_assertions_host_private(tmp_path, monkeypatch):
    kwargs, context, source = _fixture(tmp_path)
    calls = _controlled_runtime(monkeypatch)
    config_ref = _save(Path(kwargs["workspace_root"]) / "worker.json", {"schema_version": "patch_worker_configuration_v1",
        "policy": asdict(PatchAgentLoopPolicy()), "enable_recovery_loop": True,
        "behavior_evaluator": {"factory_ref": runtime._ref(Path(judge.__file__)),
            "factory_name": "make_lease_scope_evaluator", "kwargs": kwargs}})
    evaluator = PatchWorkerConfiguration.load(config_ref["path"]).behavior_evaluator()
    evaluator.prepare_for_patch_attempt()
    context["verification_identity"] = evaluator.verification_identity()
    report = evaluator(context)
    assert report["status"] == "passed" and report["verification_summary"] == {"checks": 2, "failed_checks": 0, "executions": 1}
    assert source.read_bytes() == SOURCE
    assert set(calls["sources"][0]) == {*kwargs["source_files"], judge.WORKER_NAME}
    assert b"return 1;" in calls["sources"][0][next(iter(kwargs["source_files"]))]
    assert all(PRIVATE_VALUE.encode() not in value for value in calls["sources"][0].values())
    assert calls["operations"] == [{"Records": ["public-input"]}]
    public = json.dumps(report) + json.dumps(_read(report["verification_ref"]))
    assert PRIVATE_VALUE not in public and "host-only-label" not in public and "private/executions" not in public
    assert "assertions" not in json.dumps(report["observations"])
    assert _read(report["verification_ref"])["checks"] == [{"check_id": "lease_scope.00000", "passed": True}, {"check_id": "lease_scope.00001", "passed": True}]
    compilation = _read(report["compilation_report_ref"])
    assert compilation["all_required_files_compiled"] and compilation["materialized_code_identity"] == context["materialized_code_identity"]
    assert judge.aggregate_result(report, context=context)["task_success"] is True


@pytest.mark.parametrize("mode,status,outcome", [
    ("compile_failure", "behavior_failed", "compilation_failed"),
    ("invalid_json", "behavior_failed", "behavior_failed"),
    ("timeout", "behavior_failed", "behavior_failed"),
    ("missing_inspect", "infrastructure_failed", "execution_error"),
    ("wrong_operation", "infrastructure_failed", "execution_error"),
    ("host_error", "infrastructure_failed", "execution_error"),
    ("transport_incomplete", "infrastructure_failed", "execution_error"),
])
def test_invalid_execution_or_observation_cannot_become_success(tmp_path, monkeypatch, mode, status, outcome):
    kwargs, context, _ = _fixture(tmp_path)
    calls = _controlled_runtime(monkeypatch, mode=mode)
    report = judge.make_lease_scope_evaluator(**kwargs)(context)
    assert report["status"] == status
    assert judge.aggregate_result(report, context=context)["outcome"] == outcome
    if mode == "compile_failure":
        assert calls["operations"] == []
    assert "private host path" not in json.dumps(report)


def test_host_comparison_is_type_strict_and_missing_observation_is_a_failure(tmp_path, monkeypatch):
    kwargs, context, _ = _fixture(tmp_path)
    _controlled_runtime(monkeypatch, observation={"active": False})
    report = judge.make_lease_scope_evaluator(**kwargs)(context)
    assert report["status"] == "behavior_failed" and report["verification_summary"]["failed_checks"] == 2


@pytest.mark.parametrize("change", ["source", "cases", "code_identity", "response_after", "plan"])
def test_changed_inputs_are_rejected_before_compilation(tmp_path, monkeypatch, change):
    kwargs, context, source = _fixture(tmp_path)
    calls = _controlled_runtime(monkeypatch)
    evaluator = judge.make_lease_scope_evaluator(**kwargs)
    if change == "source":
        source.write_bytes(SOURCE + b"// drift")
    elif change == "cases":
        Path(kwargs["cases_ref"]["path"]).write_text('{}', encoding="utf-8")
    elif change == "code_identity":
        context["materialized_code_identity"]["code_sha256"] = "0" * 64
    elif change == "response_after":
        path = Path(context["model_response"]["path"])
        value = json.loads(path.read_text())
        value["changes"][0]["after_text"] = "other source"
        path.write_text(json.dumps(value), encoding="utf-8")
        context["model_response"].update(output_sha256=runtime._ref(path)["sha256"], output_utf8_bytes=path.stat().st_size)
    else:
        context["implementation_plan"]["test_plan"] = ["replacement"]
    with pytest.raises(ValueError):
        evaluator(context)
    assert calls["sources"] == []


def test_private_material_must_be_outside_model_workspace(tmp_path):
    kwargs, _, _ = _fixture(tmp_path)
    kwargs["private_output_root"] = str(Path(kwargs["workspace_root"]) / "secret")
    with pytest.raises(ValueError, match="PRIVATE_SCOPE_REQUIRED"):
        judge.make_lease_scope_evaluator(**kwargs)


def test_assertions_cannot_be_embedded_in_runtime_operation(tmp_path):
    kwargs, _, _ = _fixture(tmp_path)
    document = _read(kwargs["cases_ref"])
    document["cases"][0]["operation"]["expected"] = PRIVATE_VALUE
    kwargs["cases_ref"] = _save(tmp_path / "private/other-cases.json", document)
    with pytest.raises(ValueError, match="OPERATION_FIELDS_INVALID"):
        judge.make_lease_scope_evaluator(**kwargs)


def test_public_binary_must_be_the_verified_compiler_output(tmp_path, monkeypatch):
    kwargs, context, _ = _fixture(tmp_path)
    _controlled_runtime(monkeypatch)
    original_write = Path.write_bytes

    def corrupt_public_copy(path, value):
        if path.name == "Subject.dll" and path.parent.parent == Path(kwargs["output_root"]):
            value = b"different bytes, not the verified compilation"
        return original_write(path, value)

    monkeypatch.setattr(Path, "write_bytes", corrupt_public_copy)
    report = judge.make_lease_scope_evaluator(**kwargs)(context)
    assert report["status"] == "infrastructure_failed"
    assert judge.aggregate_result(report, context=context)["task_success"] is None


def test_unstarted_compiler_is_not_reported_as_executed_checks(tmp_path, monkeypatch):
    kwargs, context, _ = _fixture(tmp_path)
    _controlled_runtime(monkeypatch, mode="compile_host_error")
    report = judge.make_lease_scope_evaluator(**kwargs)(context)
    assert report["execution_origin"] == "incomplete"
    assert _read(report["verification_ref"])["execution_origin"] == "incomplete"
    assert judge.aggregate_result(report, context=context)["outcome"] == "execution_error"


SYNTHETIC_DRIVER = b'''using System;
using System.Linq;
using System.Text.Json;
public static class Program {
    public static void Main() {
        using var operation = JsonDocument.Parse(Console.In.ReadToEnd());
        var sum = operation.RootElement.GetProperty("Numbers").EnumerateArray().Sum(x => x.GetInt32());
        Console.Write(JsonSerializer.Serialize(new { sum = sum + new ExportPipeline().Apply() }));
    }
}
'''


def _generic_fixture(tmp_path, *, lease_data=False, operation=None, assertions=None):
    kwargs, context, source = _fixture(tmp_path)
    document = _read(kwargs.pop("cases_ref"))
    document["schema_version"] = judge.CASE_BUNDLE_SCHEMA
    task_id = judge.TASK_ID if lease_data else "synthetic-sum-calibration-only"
    document["task_id"] = task_id
    if not lease_data:
        document["eligibility"] = "synthetic_calibration_not_independent_task"
        document["cases"] = [{"case_id": "synthetic-private-case", "operation": {"Numbers": [2, 3]} if operation is None else operation,
            "assertions": assertions if assertions is not None else [{"path": ["sum"], "equals": 6}]}]
    cases_ref = _save(tmp_path / "private/generic-cases.json", document)
    worker = Path(kwargs["workspace_root"]) / "public-driver.cs"
    worker.write_bytes(judge.public_worker.WORKER_SOURCE.encode() if lease_data else SYNTHETIC_DRIVER)
    kwargs.update(case_bundle_ref=cases_ref, public_worker_source_ref=runtime._ref(worker), task_id=task_id)
    return kwargs, context, source


@pytest.mark.parametrize("lease_data", [True, False], ids=["existing_lease_data", "synthetic_second_driver"])
def test_generic_factory_uses_explicit_driver_and_task_bundle(tmp_path, monkeypatch, lease_data):
    kwargs, context, source = _generic_fixture(tmp_path, lease_data=lease_data)
    calls = _controlled_runtime(monkeypatch, observation=None if lease_data else {"sum": 6})
    config = _save(Path(kwargs["workspace_root"]) / "generic-worker.json", {"schema_version": "patch_worker_configuration_v1",
        "policy": asdict(PatchAgentLoopPolicy()), "enable_recovery_loop": True,
        "behavior_evaluator": {"factory_ref": runtime._ref(Path(judge.__file__)),
            "factory_name": "make_restricted_csharp_evaluator", "kwargs": kwargs}})
    evaluator = PatchWorkerConfiguration.load(config["path"]).behavior_evaluator()
    evaluator.prepare_for_patch_attempt()
    report = evaluator(context)
    assert report["status"] == "passed" and source.read_bytes() == SOURCE
    assert calls["sources"][0]["__public_observation_worker__.cs"] == Path(kwargs["public_worker_source_ref"]["path"]).read_bytes()
    assert report["verification_scope"] == "restricted_csharp_behavior_not_product_delivery"
    assert _read(report["verification_ref"])["checks"][0] == {"check_id": "restricted_csharp.00000", "passed": True}
    assert calls["operations"] == ([{"Records": ["public-input"]}] if lease_data else [{"Numbers": [2, 3]}])
    assert "assertions" not in json.dumps(calls["operations"])
    assert judge.aggregate_result(report, context=context)["task_success"] is True


def test_generic_json_operation_and_root_assertion_are_not_lease_shaped(tmp_path, monkeypatch):
    kwargs, context, _ = _generic_fixture(tmp_path, operation=[1, False, None],
        assertions=[{"path": [], "equals": [1, False, None]}])
    calls = _controlled_runtime(monkeypatch, observation=[1, False, None])
    report = judge.make_restricted_csharp_evaluator(**kwargs)(context)
    assert report["status"] == "passed" and calls["operations"] == [[1, False, None]]


@pytest.mark.parametrize("damage", ["worker_bytes", "task_identity", "assertion_path", "bundle_bytes"])
def test_generic_bound_inputs_reject_drift_before_compile(tmp_path, monkeypatch, damage):
    kwargs, context, _ = _generic_fixture(tmp_path)
    calls = _controlled_runtime(monkeypatch)
    if damage == "task_identity":
        kwargs["task_id"] = "another-task"
    elif damage == "assertion_path":
        document = _read(kwargs["case_bundle_ref"])
        document["cases"][0]["assertions"][0]["path"] = [True]
        kwargs["case_bundle_ref"] = _save(tmp_path / "private/bad-path.json", document)
    if damage in {"task_identity", "assertion_path"}:
        with pytest.raises(ValueError):
            judge.make_restricted_csharp_evaluator(**kwargs)
    else:
        evaluator = judge.make_restricted_csharp_evaluator(**kwargs)
        reference = kwargs["public_worker_source_ref" if damage == "worker_bytes" else "case_bundle_ref"]
        Path(reference["path"]).write_bytes(b"changed after admission")
        with pytest.raises(ValueError, match="REFERENCED_BYTES_CHANGED"):
            evaluator(context)
    assert calls["sources"] == []


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("CODEX_LEASE_DOCKER_TEST") != "1", reason="Explicit fixed-image Docker control selection is required.")
@pytest.mark.parametrize("variant,expected", [("unchanged", "behavior_failed"), ("developer_repair", "passed"),
    ("invalid", "behavior_failed"), ("generic_developer_repair", "passed")])
def test_real_public_lease_controls(tmp_path, variant, expected):
    """Only the already exposed lease source and public development-case literal."""
    published = Path("C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/repair_actual_7faf_001/independent_eval/published-answer-free-v3/public/tasks/private_eval_20260909_lease_scope_001/source/OwnedTraining/Subject.cs")
    source_bytes = published.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == "1586ff556a7b54b8bf61d17df66c35a9b0cc801b46866bd6d2772a53e7a7d797"
    syntax = ast.parse(Path(judge.public_worker.__file__).read_text(encoding="utf-8"))
    prepare = next(node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name == "prepare")
    cases_node = next(node.value for node in prepare.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "development_cases" for target in node.targets))
    cases = ast.literal_eval(cases_node)
    if variant == "generic_developer_repair":
        cases["schema_version"] = judge.CASE_BUNDLE_SCHEMA
    root = Path(os.environ.get("CODEX_LEASE_CONTROL_ROOT", str(tmp_path))) / variant
    assert not root.exists()

    def replacement(before):
        if variant == "unchanged":
            return before.replace("var completed = 0;", "var completed = 0; // unchanged development control")
        if variant == "invalid":
            return before.replace("var completed = 0;", "var completed = ;")
        return '''    public int Apply(LeaseContext context, string[] records, Action<string> emit)
    {
        using (var reader = context.Open("reader"))
        using (var writer = context.Open("writer"))
        {
            var completed = 0;
            foreach (var record in records)
            {
                using (var frame = context.Open("frame:" + record))
                {
                    emit(record);
                    completed++;
                }
            }
            return completed;
        }
    }
'''

    kwargs, context, source = _fixture(root, source_bytes=source_bytes, replacement=replacement, cases=cases)
    if variant == "generic_developer_repair":
        driver = Path(kwargs["workspace_root"]) / "public-driver.cs"
        driver.write_bytes(judge.public_worker.WORKER_SOURCE.encode())
        kwargs.update(case_bundle_ref=kwargs.pop("cases_ref"), public_worker_source_ref=runtime._ref(driver), task_id=judge.TASK_ID)
        evaluator = judge.make_restricted_csharp_evaluator(**kwargs)
    else:
        evaluator = judge.make_lease_scope_evaluator(**kwargs)
    context["verification_identity"] = evaluator.verification_identity()
    report = evaluator(context)
    _save(root / "control-result.json", {"variant": variant, "origin": "developer_control_no_model",
        "factory": "make_restricted_csharp_evaluator" if variant == "generic_developer_repair" else "make_lease_scope_evaluator",
        "original_public_source_ref": runtime._ref(published), "report_ref": report["report_ref"],
        "status": report["status"], "aggregate": judge.aggregate_result(report, context=context),
        "model_calls": 0, "independent_task_success_claimed": False})
    assert report["status"] == expected, report
    assert source.read_bytes() == source_bytes
    if variant == "invalid":
        assert report["compilation"] == "failed" and report["verification_summary"]["executions"] == 0
    else:
        assert report["compilation"] == "passed" and report["verification_summary"]["executions"] == 4
