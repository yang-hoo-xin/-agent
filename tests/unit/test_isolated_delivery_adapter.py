"""Delivery preparation preserves original records and reuses public contracts."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.evaluation.isolated_delivery_adapter import deliver, prepare_delivery
from src.mod_agent.local_entry import _create_nuget_isolated_build_profile


@pytest.mark.parametrize("outcome", ["passed", "failed", "exception"])
def test_formal_acceptance_precedes_canonical_delivered_receipt(tmp_path, monkeypatch, outcome):
    from scripts.dsh_run_request import _verified_delivered_source
    from src.mod_agent.artifacts import ArtifactRef
    from src.mod_agent.evaluation import isolated_delivery_adapter as owner
    root = tmp_path / "run"
    root.mkdir()
    target = root / "target"
    target.mkdir()
    (target / "Plugin.dll").write_bytes(b"formal built fixture")
    cp = ArtifactRef(feature_id="f", artifact_type="workflow_checkpoint", path=str(root / "a/cp.json"), artifact_hash="a" * 64)
    initial = {"run_id": "run", "request_id": "request", "feature_id": "f", "diff_hash": "b" * 64, "unified_diff": "fixture diff"}
    prepared = {"run_root": root, "initial": initial, "store": SimpleNamespace(root=root / "a",
        semantic_read_immutable=lambda *_: {"data": {"artifact_refs": []}}), "checkpoint": cp,
        "config": {"policy_id": "fixture-policy", "final_acceptance_required": True},
        "verification_report_ref": _save(root / "verification.json", {"status": "passed"}),
        "required_check_ids": ["same-case"], "initial_ref": _save(root / "run_result.json", initial),
        "manifest_ref": _save(root / "run_manifest.json", {}), "verifier_identity_binding": None,
        "profile": None, "target": target, "expected_artifact": "Plugin.dll"}
    monkeypatch.setattr(owner, "prepare_delivery", lambda _: prepared)
    monkeypatch.setattr(owner, "prepare_task_delegation", lambda **_: {"path": "fixture", "sha256": "c" * 64})
    monkeypatch.setattr(owner, "resume_deferred_approval", lambda **_: {"status": "applied_in_isolation",
        "workflow_checkpoint": {"feature_id": cp.feature_id, "artifact_type": cp.artifact_type, "path": cp.path, "artifact_hash": cp.artifact_hash}})
    monkeypatch.setattr(owner, "continue_reviewed_patch", lambda **_: {"status": "built"})
    def check(assembly_ref):
        assert not (root / "delivery/result.json").exists()
        assert (root / "delivery/apply.json").exists() and (root / "delivery/build.json").exists()
        if outcome == "exception":
            raise RuntimeError("formal probe failed")
        return {"status": outcome, "assembly_ref": assembly_ref, "checks": [{"check_id": "same-case", "passed": outcome == "passed"}]}
    result = owner.deliver({"run_root": str(root)}, final_artifact_verifier=check)
    canonical = json.loads((root / "delivery/result.json").read_text())
    assert canonical == result
    assert canonical["delivery_complete"] is (outcome == "passed")
    if outcome != "passed":
        config = _save(tmp_path / "execution.json", {"arguments": ["--workspace-root", str(tmp_path), "--run-id", "run"]})
        with pytest.raises(ValueError, match="DELIVERED_SOURCE_REQUIRED"):
            _verified_delivered_source(config["path"], "run", None)


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _setup(tmp_path, monkeypatch):
    root = tmp_path / "run_generic"
    target = root / "generated_mods/ArbitraryTask"
    target.mkdir(parents=True)
    config = target / "nuget.config"
    config.write_text("<configuration />")
    profile = _create_nuget_isolated_build_profile(run_root=root, working_directory=target,
        config_file=config, bepinex_dir=None, timeout_seconds=23)
    baseline = root / "baseline_source/ArbitraryTask"
    artifact = baseline / "bin/custom/AnotherName.dll"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"original baseline DLL")
    detail = _save(root / "checks/details.json", {"checks": [{"check_id": "opaque-7", "passed": True}]})
    report = _save(root / "checks/report.json", {"status": "passed", "execution_origin": "executed",
        "verification_identity": {"validator_sha256": "a" * 64}, "verification_ref": detail})
    cp = {"feature_id": "f", "artifact_type": "workflow_checkpoint", "path": str(root / "a/checkpoint.json"), "artifact_hash": "c" * 64}
    initial = {"run_id": root.name, "status": "awaiting_approval", "current_stage": "awaiting_approval",
        "feature_id": "f", "workflow_checkpoint": cp}
    manifest = {"nuget_isolated_build_profile": profile.to_dict(), "baseline_build": {
        "restore_exit_code": 0, "build_exit_code": 0,
        "artifact_path": str(artifact), "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "build_profile": {"working_directory": str(baseline)}}}
    _save(root / "run_result.json", initial)
    _save(root / "run_manifest.json", manifest)
    proposal = {"diff_intent": [{"generation": {"model_response_sha256": "m" * 64, "patch_agent_loop": {
        "behavior_evaluation_refs": [{"status": "passed", "model_response_sha256": "m" * 64, "report_ref": report}]}}}]}
    def read(_store, reference):
        return {"data": {"state_snapshot": {"artifacts": {"patch_proposal": str(root / "a/proposal.json")},
            "artifact_hashes": {"patch_proposal": "p" * 64}}}} if reference.artifact_type == "workflow_checkpoint" else {"data": proposal}
    monkeypatch.setattr("src.mod_agent.artifacts.ArtifactStore.semantic_read_immutable", read)
    monkeypatch.setattr("src.mod_agent.evaluation.isolated_delivery_adapter.prepare_task_delegation", lambda **_: pytest.fail("prepare cannot authorize"))
    context = {"run_root": str(root), "trial": {"delivery": {"verification_selection": "current_proposal",
        "verifier_sha256": "a" * 64, "policy_id": "caller-selected-policy"}}}
    return context, root, manifest, proposal, report


def test_prepare_derives_arbitrary_formal_dll_and_opaque_checks_without_changing_records(tmp_path, monkeypatch):
    context, root, _, _, _ = _setup(tmp_path, monkeypatch)
    before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = prepare_delivery(context)
    assert result["expected_artifact"] == "bin/custom/AnotherName.dll"
    assert result["required_check_ids"] == ["opaque-7"]
    assert result["model_calls_performed"] == result["apply_calls_performed"] == result["build_calls_performed"] == 0
    assert not (root / "delivery").exists()
    assert all(path_bytes == Path(path).read_bytes() for path, path_bytes in before.items())


@pytest.mark.parametrize("damage", [None, "parent", "budget", "request"])
def test_explicit_continuation_result_retains_parent_and_budget(tmp_path, monkeypatch, damage):
    context, root, manifest, _, _ = _setup(tmp_path, monkeypatch)
    parent = json.loads((root / "run_result.json").read_bytes())
    parent.update(model_call_count=7, model_call_budget={"maximum": 12, "consumed": 7, "remaining": 5,
        "by_stage": {"initial_patch": {"consumed": 7}}, "policy": "task_total_only",
        "count_basis": "reserved_provider_invocations_not_transport_proof"})
    parent_ref = _save(root / "run_result.json", parent)
    manifest["request_id"] = "original_request"
    manifest_ref = _save(root / "run_manifest.json", manifest)
    initial = {**parent, "run_id": "continuation-child", "request_id": "original_request",
        "parent_run_id": root.name, "parent_result_ref": parent_ref, "parent_manifest_ref": manifest_ref,
        "generation_origin": "retained_live_response", "new_provider_sends": 0}
    if damage == "parent":
        initial["parent_result_ref"] = manifest_ref
    elif damage == "budget":
        initial["model_call_budget"] = {**parent["model_call_budget"], "consumed": 0, "remaining": 12}
    elif damage == "request":
        initial["request_id"] = "other"
    context["trial"]["delivery"]["initial_result_ref"] = _save(root / "continuations/retry/result.json", initial)
    if damage:
        with pytest.raises(ValueError, match="CONTINUATION_PARENT_BINDING_REQUIRED"):
            prepare_delivery(context)
    else:
        result = prepare_delivery(context)
        assert result["initial"]["run_id"] == "continuation-child"
        assert result["model_calls_performed"] == result["apply_calls_performed"] == 0
        assert json.loads((root / "run_result.json").read_bytes()) == parent


def test_prepare_delivery_of_repaired_source_does_not_require_a_baseline_dll(tmp_path, monkeypatch):
    from src.mod_agent.build.baseline_repair import (
        baseline_failure_model_view,
        classify_source_compilation_failure,
    )
    from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256
    context, root, manifest, _, _ = _setup(tmp_path, monkeypatch)
    baseline = manifest["baseline_build"]
    Path(baseline["artifact_path"]).unlink()
    original = tmp_path / "original/ArbitraryTask"
    original.mkdir(parents=True)
    target = root / "generated_mods/ArbitraryTask"
    compiled_source = Path(baseline["build_profile"]["working_directory"])
    for folder in (original, target, compiled_source):
        (folder / "Plugin.cs").write_text("class Plugin { MissingType field; }", encoding="utf-8")
        (folder / "nuget.config").write_bytes((target / "nuget.config").read_bytes())
    snapshot = source_snapshot(original)
    output = f"{compiled_source / 'Plugin.cs'}(1,16): error CS0246: MissingType was not found"
    baseline.update(restore_exit_code=0, build_exit_code=1, artifact_exists=False, artifact_sha256=None)
    for stream, content in (("stdout", output), ("stderr", "")):
        log = root / f"baseline_build.{stream}.log"
        log.write_text(content, encoding="utf-8")
        baseline[stream + "_path"] = str(log)
        baseline[stream + "_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
    diagnostics = classify_source_compilation_failure(execution=baseline, output=output,
        project_root=compiled_source, expected_sources={row["path"]: row["sha256"] for row in snapshot})
    baseline["source_compilation_diagnostics"] = list(diagnostics)
    baseline["repair_observation"] = baseline_failure_model_view(diagnostics,
        source_prefix="generated_mods/ArbitraryTask", source_snapshot_sha256=source_snapshot_sha256(snapshot))
    manifest.update(target_source=str(original), source_snapshot=snapshot,
                    source_snapshot_sha256=source_snapshot_sha256(snapshot))
    _save(root / "run_manifest.json", manifest)
    result = prepare_delivery(context)
    assert result["expected_artifact"] == "bin/custom/AnotherName.dll"
    assert result["apply_calls_performed"] == result["build_calls_performed"] == 0
    assert result["required_check_ids"] == ["opaque-7"]


@pytest.mark.parametrize("kind", ["objective", "runtime", "inspection", "profile", "verifier", "dll", "failed-stale-dll"])
def test_prepare_refuses_missing_acceptance_or_changed_inputs(tmp_path, monkeypatch, kind):
    context, root, manifest, _, _ = _setup(tmp_path, monkeypatch)
    if kind == "objective":
        manifest["objective_verification_command"] = ["additional-check"]
    elif kind == "runtime":
        manifest["runtime_admission"] = {"requested": True}
    elif kind == "inspection":
        manifest["compiled_artifact_inspection_profile"] = {"required": True}
    elif kind == "profile":
        manifest["nuget_isolated_build_profile"]["build_command"].append("-p:Unrecorded=true")
    elif kind == "verifier":
        context["trial"]["delivery"]["verifier_sha256"] = "b" * 64
    elif kind == "failed-stale-dll":
        manifest["baseline_build"]["build_exit_code"] = 1
    else:
        manifest["baseline_build"]["artifact_sha256"] = "b" * 64
    _save(root / "run_manifest.json", manifest)
    result = deliver(context)
    assert result["status"] == "unknown" and result["delivery_complete"] is False
    assert not (root / "delivery").exists()


def test_report_selection_requires_unique_current_model_result_not_a_pass_glob(tmp_path, monkeypatch):
    context, root, _, proposal, report = _setup(tmp_path, monkeypatch)
    other = _save(root / "checks/other.json", json.loads(Path(report["path"]).read_text()))
    refs = proposal["diff_intent"][0]["generation"]["patch_agent_loop"]["behavior_evaluation_refs"]
    refs.append({**deepcopy(refs[0]), "report_ref": other})
    with pytest.raises(ValueError, match="NOT_UNIQUE"):
        prepare_delivery(context)
    context["trial"]["delivery"]["verification_report_ref"] = report
    assert prepare_delivery(context)["verification_report_ref"] == report


@pytest.mark.parametrize("damage", [None, "caller_factory", "unverified_execution", "worker_identity", "report_identity"])
def test_bound_verifier_identity_comes_from_executed_worker_not_report_claim(tmp_path, monkeypatch, damage):
    context, root, manifest, proposal, report_ref = _setup(tmp_path, monkeypatch)
    factory = _save(tmp_path / "factory.py", {"controlled": "factory source"})
    worker_value = {"behavior_evaluator": {"factory_ref": factory, "factory_name": "make", "kwargs": {"option": 1}}}
    worker_ref = _save(tmp_path / "worker.json", worker_value)
    snapshot_root = tmp_path / "snapshot"
    retained = "external/worker.json"
    _save(snapshot_root / retained, worker_value)
    snapshot_ref = _save(snapshot_root / "execution_snapshot.json", {
        "business_argv": ["run-request", "task", "--patch-worker-config", worker_ref["path"]],
        "external_refs": [{"role": "bound_input", **worker_ref, "retained_path": retained}]})
    check_ref = _save(snapshot_root / "check.json", {"status": "verified", "run_id": root.name,
        "execution_version_ref": snapshot_ref, "external_bindings": [{"role": "extra_python_load", **factory,
            "execution_observed": True}]})
    manifest.update(execution_version_ref=snapshot_ref, execution_version_check_ref=check_ref)
    identity = {"validator_sha256": "d" * 64, "inputs_sha256": "e" * 64}
    report = json.loads(Path(report_ref["path"]).read_text())
    report.update(verification_identity=identity, model_response_sha256="m" * 64)
    report_ref = _save(Path(report_ref["path"]), report)
    proposal["diff_intent"][0]["generation"]["patch_agent_loop"]["behavior_evaluation_refs"][0]["report_ref"] = report_ref
    receipt = {"factory_receipt": {"behavior_evaluator_configuration": {"configuration_ref": worker_ref,
        "factory_ref": factory, "factory_name": "make", "kwargs_sha256": hashlib.sha256(b'{"option":1}').hexdigest()},
        "patch_agent_loop": {"behavior_evaluations": [{"report_ref": report_ref, "admission": "accepted",
            "execution_origin": "executed", "model_response_sha256": "m" * 64, "verification_identity": identity}]}}}
    if damage == "worker_identity":
        receipt["factory_receipt"]["behavior_evaluator_configuration"]["kwargs_sha256"] = "0" * 64
    if damage == "report_identity":
        receipt["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]["verification_identity"] = {"validator_sha256": "0" * 64}
    initial = json.loads((root / "run_result.json").read_text())
    initial["patch_execution_receipts"] = [_save(root / "a/cr/worker.json", receipt)]
    _save(root / "run_result.json", initial)
    if damage == "unverified_execution":
        value = json.loads(Path(check_ref["path"]).read_text())
        value["status"] = "unknown"
        manifest["execution_version_check_ref"] = _save(Path(check_ref["path"]), value)
    _save(root / "run_manifest.json", manifest)
    context["trial"].update(snapshot_root=str(snapshot_root), bound_inputs=[worker_ref],
        extra_load_refs=[] if damage == "caller_factory" else [factory])
    context["trial"]["delivery"].pop("verifier_sha256")
    context["trial"]["delivery"]["verifier_selection"] = "bound_worker_execution"
    if damage:
        with pytest.raises(ValueError):
            prepare_delivery(context)
    else:
        prepared = prepare_delivery(context)
        assert prepared["verifier_identity_binding"]["validator_sha256"] == "d" * 64
        assert prepared["verifier_identity_binding"]["factory_ref"] == factory


def _compilation_report_fixture(tmp_path):
    from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
    root = tmp_path / "compiled_run"
    target = root / "generated_mods/M"
    target.mkdir(parents=True)
    before = b"class P { int V=1; }\n"
    (target / "P.cs").write_bytes(before)
    changed_bytes = before.replace(b"V=1", b"V=2")
    plan_ref = {"feature_id": "f", "artifact_type": "implementation_plan", "path": str(root / "a/plan.json"), "artifact_hash": "a" * 64}
    plan = {"binding_registry": {"edit_bindings": [{"binding_id": "b0", "canonical_target_path": "generated_mods/M/P.cs",
        "source_hash": hashlib.sha256(before).hexdigest(), "source_type": "target_source", "evidence_id": "e0",
        "target_span": {"start_line": 1, "end_line": 1}, "target_symbol": None}], "supporting_bindings": []}}
    _save(root / "a/plan.json", plan)
    raw_ref = _save(root / "a/model.json", {"changes": [{"edit_binding_id": "b0", "before_text": "V=1", "after_text": "V=2"}]})
    change = {"change_id": "c1", "edit_binding_id": "b0", "patch": {"kind": "exact_text_replace", "before_text": "V=1", "after_text": "V=2", "expected_occurrences": 1},
        "generation": {"model_response_sha256": raw_ref["sha256"], "patch_agent_loop": {"behavior_evaluation_refs": []}}}
    materialized = materialize_exact_text_patch(workspace_root=root, diff_intent=[change], implementation_plan=plan)
    identity = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256, "files": sorted(materialized.files)}
    compiled = root / "c/version/source"
    compiled.mkdir(parents=True)
    (compiled / "P.cs").write_bytes(changed_bytes)
    dll = compiled / "P.dll"
    dll.write_bytes(b"test compiler artifact")
    from src.mod_agent.evaluation.isolated_delivery_adapter import _ref
    inputs = {"P.cs": hashlib.sha256(changed_bytes).hexdigest()}
    changed = {"status": "passed", "execution_origin": "executed", "all_required_files_compiled": True,
        "build_execution": {"build_executed": True, "restore_exit_code": 0, "build_exit_code": 0, "exit_code": 0},
        "build_result": {"real_build_performed": True, "claims_real_build_success": True, "exit_code": 0},
        "product_apply_performed": False, "verification_scope": "full_project_compilation_not_behavior_or_formal_build_or_runtime",
        "model_response_ref": raw_ref, "implementation_plan_ref": plan_ref, "materialized_code_identity": identity,
        "isolated_source_root": str(compiled), "source_inputs_ref": _save(root / "c/inputs.json", inputs),
        "compile_inputs_ref": _save(root / "c/compile-inputs.json", inputs), "required_files": ["P.cs"],
        "compile_inputs": [{"path": "P.cs", "sha256": inputs["P.cs"]}], "built_artifact_ref": _ref(dll),
        "stdout_ref": _save(root / "c/stdout.json", {"exit_code": 0}), "stderr_ref": _save(root / "c/stderr.json", {})}
    changed["report_ref"] = _save(root / "c/report.json", changed)
    report = {"status": "passed", "execution_origin": "executed", "verification_scope": "compilation_only_gameplay_not_verified",
        "generated_changes_sha256": "1" * 64, "source_snapshot_sha256": "2" * 64,
        "materialized_code_identity": identity, "validation_results": {"full_compilation": {"status": "passed", "changed_compilation_performed": True, "changed": changed}, "runtime": {"status": "not_executed"}}}
    verification = _save(root / "v/report.json", report)
    change["generation"]["patch_agent_loop"]["behavior_evaluation_refs"] = [{"report_ref": verification, "status": "passed",
        "model_response_sha256": raw_ref["sha256"], "generated_changes_sha256": "1" * 64}]
    return root, report, {"diff_intent": [change]}, verification, SimpleNamespace(semantic_read_immutable=lambda _: {"data": plan}), {"nuget_isolated_build_profile": {"working_directory": str(target)}}


@pytest.mark.parametrize("damage", [None, "raw_model", "compiled_source", "live_source", "dll", "unexecuted", "missing_compile_input", "wrong_generated_changes", "wrong_code_identity", "nested_report"])
def test_compilation_feedback_requires_actual_current_code_and_execution(tmp_path, damage):
    from src.mod_agent.evaluation.isolated_delivery_adapter import _compilation_feedback_binding
    root, report, proposal, verification, store, manifest = _compilation_report_fixture(tmp_path)
    changed = report["validation_results"]["full_compilation"]["changed"]
    if damage == "raw_model":
        Path(changed["model_response_ref"]["path"]).write_bytes(b"different model response")
    elif damage == "compiled_source":
        (Path(changed["isolated_source_root"]) / "P.cs").write_bytes(b"not the materialized code")
    elif damage == "live_source":
        (Path(manifest["nuget_isolated_build_profile"]["working_directory"]) / "P.cs").write_bytes(b"source drift")
    elif damage == "dll":
        Path(changed["built_artifact_ref"]["path"]).write_bytes(b"stale artifact")
    elif damage == "unexecuted":
        changed["build_execution"]["build_executed"] = False
    elif damage == "missing_compile_input":
        changed["compile_inputs"] = []
    elif damage == "wrong_generated_changes":
        report["generated_changes_sha256"] = "9" * 64
    elif damage == "wrong_code_identity":
        report["materialized_code_identity"] = {**report["materialized_code_identity"], "code_sha256": "sha256:" + "0" * 64}
    elif damage == "nested_report":
        changed["status"] = "changed nested claim"
    if damage in {"unexecuted", "missing_compile_input"}:
        changed["report_ref"] = _save(Path(changed["report_ref"]["path"]), {k: v for k, v in changed.items() if k != "report_ref"})
    if damage:
        with pytest.raises(ValueError):
            _compilation_feedback_binding(root, report, proposal, verification, store, manifest)
    else:
        result = _compilation_feedback_binding(root, report, proposal, verification, store, manifest)
        assert result["verification_scope"] == "compilation_only_gameplay_not_verified"
        assert result["generated_changes_sha256"] == "1" * 64
        assert "checks" not in report and "model_response_sha256" not in report
        assert report["validation_results"]["runtime"]["status"] == "not_executed"


def test_required_final_acceptance_without_callback_cannot_apply(tmp_path, monkeypatch):
    from src.mod_agent.evaluation import isolated_delivery_adapter as owner
    monkeypatch.setattr(owner, "prepare_delivery", lambda _: {"run_root": tmp_path, "initial": {}, "store": None,
        "config": {"final_acceptance_required": True}})
    with pytest.raises(ValueError, match="FINAL_ACCEPTANCE_CALLBACK_REQUIRED"):
        owner.deliver({})
    assert not (tmp_path / "delivery").exists()
