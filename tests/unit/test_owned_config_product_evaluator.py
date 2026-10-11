"""Exercise the owned oracle against the actual run-request workspace layout."""
from __future__ import annotations

import importlib.util
import json
import shutil
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.execution.patch_apply import PatchApplyError, materialize_exact_text_patch
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.planning.models import FeatureSpec, ImplementationPlan
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector

FIXTURE = Path(__file__).parents[1] / "fixtures/patch_eval/owned_config_service"


def _load(filename):
    spec = importlib.util.spec_from_file_location("owned_config_product_test_" + filename, FIXTURE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def product_input(tmp_path):
    legacy = _load("behavior_evaluator.py")
    root = tmp_path / "run"
    shutil.copytree(FIXTURE / "source", root / "generated_mods")
    relative = "generated_mods/OwnedConfigService/JsonConfigStore.cs"
    source = root / relative
    plan = {"binding_registry": {"schema_version": "binding_registry_v1",
        "edit_bindings": [{"binding_id": "edit_binding_001", "canonical_target_path": relative,
            "source_hash": legacy.reference(source)["sha256"],
            "target_span": {"start_line": 1, "end_line": len(source.read_text().splitlines())}}],
        "supporting_bindings": []},
        "proposed_changes": [{"change_id": "change_001", "edit_binding_id": "edit_binding_001"}]}
    plan = ImplementationPlan(feature_id="owned-product", target_files=(relative,),
        target_symbols=("Update",), evidence_refs=(), proposed_changes=tuple(plan["proposed_changes"]),
        side_effect_boundaries=("One comment-only test replacement.",), test_plan=("Existing matrix.",),
        rollback_plan=("Discard this test workspace.",),
        binding_registry=plan["binding_registry"]).to_artifact_payload()
    changes = [{"change_id": "change_001", "edit_binding_id": "edit_binding_001", "patch": {
        "kind": "exact_text_replace", "before_text": "configuration[key] = value.Clone();",
        "after_text": "configuration[key] = value.Clone(); // product-layout probe",
        "expected_occurrences": 1}}]
    response = root / "response.json"
    response.write_text(json.dumps({"changes": changes}), encoding="utf-8")
    materialized = materialize_exact_text_patch(workspace_root=root,
        diff_intent=changes, implementation_plan=plan)
    inspector = PlanBoundSourceInspector(workspace_root=root, implementation_plan=plan,
        policy=PatchAgentLoopPolicy())
    context = {"generated_changes": changes, "generated_changes_sha256": canonical_hash(changes),
        "implementation_plan": plan, "source_snapshot_sha256": inspector.source_snapshot_sha256,
        "model_response": {"path": str(response), "output_sha256": legacy.reference(response)["sha256"]},
        "materialized_code_identity": {"baseline_sha256": materialized.baseline_sha256,
            "code_sha256": materialized.code_sha256, "files": sorted(materialized.files)}}
    return legacy, root, context


def test_legacy_oracle_cannot_resolve_real_product_plan(product_input, tmp_path):
    legacy, root, context = product_input
    oracle = legacy.OwnedConfigOracle(workspace_root=root / "generated_mods",
        output_root=tmp_path / "legacy-results")
    with pytest.raises(PatchApplyError, match="target file is missing"):
        oracle(context)


def _product_oracle(legacy, root, output):
    adapter = _load("product_behavior_evaluator.py")
    return adapter.make_product_behavior_evaluator(workspace_root=root, output_root=output,
        expected_check_ids=legacy.CHECKS,
        oracle_sha256=legacy.reference(FIXTURE / "behavior_evaluator.py")["sha256"])


def _save_plan(root, plan):
    store = ArtifactStore(root / "a")
    feature = FeatureSpec(feature_id="owned-product", user_request="Verify product-layout adapter.",
        target_behavior="Preserve the original behavior matrix.", target_mod="OwnedConfigService",
        risk_level="low", acceptance_criteria=("Identity-preserving relocation.",), non_goals=(),
        evidence_requirements=("Current application source.",), runtime_verification_plan=())
    feature_ref = store.write(feature_id="owned-product", artifact_type="feature_spec",
        payload=feature.to_artifact_payload())
    evidence_ref = store.write(feature_id="owned-product", artifact_type="evidence_pack",
        payload=EvidencePack(query=feature.user_request, readiness="sufficient",
            can_generate_patch=True).to_artifact_payload(), upstream_refs=[feature_ref])
    return store.write(feature_id="owned-product", artifact_type="implementation_plan",
        payload=plan, upstream_refs=[feature_ref, evidence_ref])


def test_product_adapter_executes_unchanged_matrix_and_preserves_product_identity(product_input, tmp_path):
    legacy, root, context = product_input
    factory = FIXTURE / "product_behavior_evaluator.py"
    configuration = {"schema_version": "patch_worker_configuration_v1", "policy": {},
        "enable_recovery_loop": True, "behavior_evaluator": {
            "factory_ref": legacy.reference(factory), "factory_name": "make_product_behavior_evaluator",
            "kwargs": {"workspace_root": str(root), "output_root": str(tmp_path / "product-results"),
                "expected_check_ids": list(legacy.CHECKS),
                "oracle_sha256": legacy.reference(FIXTURE / "behavior_evaluator.py")["sha256"]}}}
    worker = tmp_path / "worker.json"
    worker.write_text(json.dumps(configuration), encoding="utf-8")
    evaluator = PatchWorkerConfiguration.load(worker).behavior_evaluator()
    evaluator.prepare_for_patch_attempt()
    context["verification_identity"] = evaluator.verification_identity()
    plan_ref = _save_plan(root, context["implementation_plan"])
    context["implementation_plan_ref"] = asdict(plan_ref)
    frozen = deepcopy(context)
    report = evaluator(context)
    assert context == frozen
    assert report["status"] == "behavior_failed"
    assert report["materialized_code_identity"] == context["materialized_code_identity"]
    assert report["verification_identity"] == context["verification_identity"]
    assert report["verification_summary"] == {"checks": 15, "failed_checks": 7, "executions": 23}
    matrix = json.loads(Path(report["verification_ref"]["path"]).read_text())
    assert [item["check"] for item in matrix["checks"]] == list(legacy.CHECKS)
    assert all(item["passed"] for item in matrix["checks"] if item["group"] == "preservation")
    assert "product-layout probe" not in (root / context["materialized_code_identity"]["files"][0]).read_text()


@pytest.mark.parametrize("changed, message", [
    ("changes", "GENERATED_CHANGES_MISMATCH"),
    ("snapshot", "SOURCE_SNAPSHOT_MISMATCH"),
    ("code", "MATERIALIZED_CODE_IDENTITY_MISMATCH"),
    ("response", "MODEL_RESPONSE_CHANGED"),
    ("plan", "source_hash does not match|SOURCE_HASH_MISMATCH"),
    ("verifier", "VERIFICATION_IDENTITY_MISMATCH"),
])
def test_product_adapter_rejects_identity_drift_before_compiler(product_input, tmp_path, monkeypatch,
                                                               changed, message):
    legacy, root, context = product_input
    evaluator = _product_oracle(legacy, root, tmp_path / "results")
    monkeypatch.setattr(evaluator._oracle, "_evaluate_files",
        lambda *_: pytest.fail("Compiler must not run after identity drift"))
    if changed == "changes":
        context["generated_changes_sha256"] = "0" * 64
    elif changed == "snapshot":
        context["source_snapshot_sha256"] = "0" * 64
    elif changed == "code":
        context["materialized_code_identity"]["code_sha256"] = "0" * 64
    elif changed == "response":
        Path(context["model_response"]["path"]).write_text("changed")
    elif changed == "plan":
        context["implementation_plan"]["binding_registry"]["edit_bindings"][0]["source_hash"] = "0" * 64
    else:
        context["verification_identity"] = {"validator_sha256": "0" * 64}
    with pytest.raises((ValueError, RuntimeError), match=message):
        evaluator(context)


def test_product_adapter_rejects_changed_bound_plan_artifact(product_input, tmp_path):
    legacy, root, context = product_input
    evaluator = _product_oracle(legacy, root, tmp_path / "results")
    reference = _save_plan(root, context["implementation_plan"])
    context["implementation_plan_ref"] = asdict(reference)
    context["implementation_plan"]["rationale"] = "Not the recorded Plan"
    with pytest.raises(ValueError, match="PLAN_CONTEXT_MISMATCH"):
        evaluator(context)


def test_product_adapter_requires_frozen_oracle_and_original_checks(product_input, tmp_path):
    legacy, root, _ = product_input
    adapter = _load("product_behavior_evaluator.py")
    arguments = {"workspace_root": root, "output_root": tmp_path / "results",
        "expected_check_ids": legacy.CHECKS,
        "oracle_sha256": legacy.reference(FIXTURE / "behavior_evaluator.py")["sha256"]}
    with pytest.raises(ValueError, match="ORACLE_SOURCE_CHANGED"):
        adapter.make_product_behavior_evaluator(**{**arguments, "oracle_sha256": "0" * 64})
    with pytest.raises(ValueError, match="CHECK_SET_CHANGED"):
        adapter.make_product_behavior_evaluator(**{**arguments, "expected_check_ids": legacy.CHECKS[:-1]})


def test_product_adapter_rejects_valid_patch_outside_generated_project(product_input, tmp_path, monkeypatch):
    legacy, root, context = product_input
    evaluator = _product_oracle(legacy, root, tmp_path / "results")
    monkeypatch.setattr(evaluator._oracle, "_evaluate_files",
        lambda *_: pytest.fail("Compiler must not run for a different project"))
    source = root / context["materialized_code_identity"]["files"][0]
    relocated = root / "other-project/JsonConfigStore.cs"
    relocated.parent.mkdir()
    shutil.copyfile(source, relocated)
    plan = context["implementation_plan"]
    plan["binding_registry"]["edit_bindings"][0]["canonical_target_path"] = "other-project/JsonConfigStore.cs"
    materialized = materialize_exact_text_patch(workspace_root=root,
        diff_intent=context["generated_changes"], implementation_plan=plan)
    context["materialized_code_identity"] = {"baseline_sha256": materialized.baseline_sha256,
        "code_sha256": materialized.code_sha256, "files": sorted(materialized.files)}
    context["source_snapshot_sha256"] = PlanBoundSourceInspector(workspace_root=root,
        implementation_plan=plan, policy=PatchAgentLoopPolicy()).source_snapshot_sha256
    with pytest.raises(ValueError, match="PRODUCT_MATERIALIZATION_ESCAPE"):
        evaluator(context)
