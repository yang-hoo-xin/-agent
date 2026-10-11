"""Saved-response admission never invokes a model, verifier or Artifact writer."""
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return _ref(path)


def _ref(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _snapshot(path):
    return {str(p): p.read_bytes() for p in path.rglob("*") if p.is_file()}


@pytest.fixture
def case(tmp_path):
    return saved_case(tmp_path)


def saved_case(tmp_path, *, product_layout=False):
    """Independent fixture receipts, with real parser/materializer and no compiler."""
    from src.mod_agent.artifacts import ArtifactRef
    from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
    from src.mod_agent.fresh_planning_continuation import (
        _canonical_sha256,
        _source_tree_snapshot_sha256,
        preflight_patch_continuation,
        run_fresh_patch_continuation,
    )
    from src.mod_agent.local_entry import (
        _binary_tree_snapshot,
        _binary_tree_snapshot_sha256,
        _overlay_generated_patch_changes_on_plan,
        make_exact_no_write_dry_run_factory,
    )
    from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256
    from src.mod_agent.proposal.builder import PatchProposalBuilder
    from src.mod_agent.proposal.patch_agent_loop import (
        PatchAgentLoopPolicy,
        PlanBoundSourceInspector,
    )
    from src.mod_agent.proposal.reviewer import ProposalReviewer
    from tests.unit.test_fresh_planning_continuation import (
        _inputs,
        _local_patch_adapter,
        _patch_request,
    )

    inputs = _inputs(tmp_path)
    request = _patch_request(inputs)
    admitted = preflight_patch_continuation(request)
    if product_layout:
        # Product runs use workspace/a. Create new fixture Artifacts at that
        # layout before the scripted worker produces its retained response.
        # Ordinary Fresh root admission is never relaxed or mocked.
        from src.mod_agent.artifacts import ArtifactStore
        from src.mod_agent.fresh_planning_continuation import PatchContinuationAttemptJournal
        from src.mod_agent.workflow.state import create_initial_state
        store = ArtifactStore(inputs.workspace / "a")
        feature_ref = store.write(feature_id=inputs.feature_ref.feature_id, artifact_type="feature_spec",
                                  payload=admitted.feature_spec, status="success")
        evidence_ref = store.write(feature_id=feature_ref.feature_id, artifact_type="evidence_pack",
            payload=admitted.evidence_pack, status="success", upstream_refs=[feature_ref])
        plan_ref = store.write(feature_id=feature_ref.feature_id, artifact_type="implementation_plan",
            payload=admitted.implementation_plan, status="success", upstream_refs=[feature_ref, evidence_ref])
        request = replace(request, artifact_store_root=str(store.root), feature_spec_ref=feature_ref,
                          evidence_pack_ref=evidence_ref, implementation_plan_ref=plan_ref)
        inputs = replace(inputs, store=store, feature_ref=feature_ref, evidence_ref=evidence_ref)
        admitted = replace(admitted, artifact_store=store)
        journal = PatchContinuationAttemptJournal.for_product_execution(artifact_root=store.root,
            run_id="fixture-worker", request_id="fixture-logical", parent_run_id="fixture-product",
            feature_spec_ref=feature_ref, evidence_pack_ref=evidence_ref, implementation_plan_ref=plan_ref,
            workspace_root=inputs.workspace, max_model_calls=4)
        state = create_initial_state(run_id="fixture-worker", request_id="fixture-logical",
                                     user_request=admitted.feature_spec["user_request"])
        state.update(feature_id=feature_ref.feature_id,
            artifacts={ref.artifact_type: ref.path for ref in (feature_ref, evidence_ref, plan_ref)},
            artifact_hashes={ref.artifact_type: ref.artifact_hash for ref in (feature_ref, evidence_ref, plan_ref)})
        adapter, _ = _local_patch_adapter(inputs)
        adapter.bind_attempt_recorder(journal.record)
        generated_changes = adapter(state, admitted.implementation_plan, admitted.evidence_pack)
        j = json.loads(journal.path.read_text(encoding="utf-8"))
        f = adapter.patch_attempt_receipt()
        j["factory_receipt"] = f
        original = PatchProposalBuilder().build(
            {**admitted.implementation_plan, "proposed_changes": list(generated_changes)},
            evidence_pack=admitted.evidence_pack).to_artifact_payload()
        j["terminal_result"] = {"run_id": state["run_id"], "request_id": state["request_id"],
            "feature_id": state["feature_id"], "status": "terminal", "first_failure": None,
            "execution_counts": {"apply": 0, "build": 0, "runtime": 0},
            "feature_spec_artifact": asdict(feature_ref), "evidence_pack_artifact": asdict(evidence_ref),
            "implementation_plan_artifact": asdict(plan_ref)}
    else:
        adapter, _ = _local_patch_adapter(inputs)  # A scripted test provider, never HTTP.
        completed = run_fresh_patch_continuation(request, patch_change_factory=adapter,
            dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace))
        j = json.loads(Path(completed.attempt_receipt["path"]).read_text(encoding="utf-8"))
        f = j["factory_receipt"]
        original = inputs.store.semantic_read_immutable(ArtifactRef(**completed.patch_proposal_artifact))["data"]
    # Recover native parser output independently from the adapter's final Plan metadata.
    from src.libs.llm import ChatResponse
    from src.mod_agent.local_entry import (
        _external_evidence_items,
        _patch_generation_obligation_projection,
    )
    from src.mod_agent.proposal.code_generator import LLMExactPatchGenerator
    plan = admitted.implementation_plan
    obligations = _patch_generation_obligation_projection(feature_spec=admitted.feature_spec,
        implementation=plan, planned_changes=plan["proposed_changes"])
    generator = LLMExactPatchGenerator(None)
    prepared = generator.prepare_native_contract(user_request=admitted.feature_spec["user_request"],
        evidence_items=_external_evidence_items(admitted.evidence_pack["items"]), binding_registry=plan["binding_registry"],
        constraints=obligations["side_effect_boundaries"], target_behavior=obligations["target_behavior"],
        acceptance_criteria=obligations["acceptance_criteria"], runtime_verification_plan=obligations["runtime_verification_plan"],
        required_change_units=obligations["required_change_units"],
        required_validation_by_binding={r["edit_binding_id"]: r["expected_validation"] for r in obligations["required_change_units"]})
    # The older scripted transport uses a placeholder response_format hash; this
    # fixture records the actual native schema which saved admission requires.
    f["patch_response_contract"]["schema_sha256"] = prepared.schema_sha256
    for change in original["diff_intent"]:
        change["generation"]["patch_response_contract"]["schema_sha256"] = prepared.schema_sha256
    response_ref = {"path": f["model_response"]["path"], "sha256": f["model_response"]["output_sha256"]}
    generated = generator.materialize_prepared_native(prepared,
        ChatResponse(content=Path(response_ref["path"]).read_bytes().decode("utf-8"), model=f["model_response"]["model"]))
    changes = _overlay_generated_patch_changes_on_plan(planned_changes=plan["proposed_changes"], generated_changes=generated.changes)
    materialized = materialize_exact_text_patch(workspace_root=inputs.workspace, diff_intent=changes, implementation_plan=plan)
    code = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256,
            "files": sorted(materialized.files)}
    inspector = PlanBoundSourceInspector(workspace_root=inputs.workspace, implementation_plan=plan, policy=PatchAgentLoopPolicy())
    sources = inputs.workspace / "generated_mods/SyntheticMod"
    dll = tmp_path / "fixture.dll"
    dll.write_bytes(b"synthetic compiled bytes - no compiler executed")
    dependency = tmp_path / "deps"
    dependency.mkdir()
    (dependency / "dep.dll").write_bytes(b"synthetic dependency")
    snap = _binary_tree_snapshot(dependency)
    identity = {"validator_sha256": "1"*64, "inputs_sha256": "2"*64,
                "environment_sha256": "3"*64, "deterministic_reuse_allowed": False}
    source_hashes = {r["path"]: r["sha256"] for r in source_snapshot(sources)}
    compiled = tmp_path / "compiled"
    compiled.mkdir()
    for row in source_snapshot(sources):
        target = compiled / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((sources / row["path"]).read_bytes())
    for path, raw in materialized.files.items():
        rel = (inputs.workspace / path).relative_to(sources).as_posix()
        (compiled / rel).write_bytes(raw)
        source_hashes[rel] = hashlib.sha256(raw).hexdigest()
    placeholder_ref = _save(tmp_path / "fixture-input.json", {"fixture": True})
    compilation = {"status": "passed", "execution_origin": "executed", "model_response_ref": response_ref,
        "implementation_plan_ref": asdict(request.implementation_plan_ref), "materialized_code_identity": code,
        "built_artifact_ref": _ref(dll), "all_required_files_compiled": True, "product_apply_performed": False,
        "formal_build_stage_performed": False, "verification_identity": identity,
        "dependency_binding": {"source_root": str(dependency), "file_count": len(snap),
                               "snapshot_sha256": _binary_tree_snapshot_sha256(snap)},
        "compile_inputs": [{"path": p, "sha256": h} for p, h in source_hashes.items()], "project_root": str(compiled),
        "source_inputs_ref": _save(tmp_path / "source-inputs.json", source_hashes)}
    for field in ("compile_inputs_ref", "measurement_targets_ref", "nuget_config_input_ref", "stdout_ref", "stderr_ref"):
        compilation[field] = placeholder_ref
    compilation_ref = _save(tmp_path / "compilation.json", compilation)
    check = {"check_id": "fixture.marker", "passed": True, "expected": "changed", "observed": "changed"}
    configuration = {"status": "passed", "execution_origin": "executed", "materialized_code_identity": code,
        "built_artifact_ref": _ref(dll), "compilation_report_ref": compilation_ref, "checks": [check],
        "observations": [{"fixture": True}], "process_refs": [placeholder_ref], "verification_identity": identity}
    configuration_ref = _save(tmp_path / "configuration.json", configuration)
    report = {"status": "passed", "execution_origin": "executed", "failure_owner": None,
        "generated_changes_sha256": _canonical_sha256(generated.changes), "source_snapshot_sha256": inspector.source_snapshot_sha256,
        "model_response_sha256": response_ref["sha256"], "materialized_code_identity": code,
        "implementation_plan_ref": asdict(request.implementation_plan_ref), "verification_identity": identity,
        "verification_ref": configuration_ref, "verification_summary": {"checks": 1, "failed_checks": 0, "executions": 1},
        "validation_results": {"full_compilation": {"report_ref": compilation_ref}, "configuration": {"report_ref": configuration_ref}}}
    report_ref = _save(tmp_path / "report.json", report)
    probe_ref = _save(tmp_path / "probe.json", {"dotnet": _ref(dll), "assembly_path": str(dll), "files": [_ref(dll)]})
    kwargs = {"compilation_kwargs": {"source_root": str(sources), "workspace_root": str(inputs.workspace)},
              "configuration_kwargs": {"probe_configuration_ref": probe_ref}}
    worker_ref = _save(tmp_path / "worker.json", {"behavior_evaluator": {"factory_ref": placeholder_ref,
                        "factory_name": "fixture_only", "kwargs": kwargs}})
    f["behavior_evaluator_configuration"] = {"configuration_ref": worker_ref, "factory_ref": placeholder_ref,
        "factory_name": "fixture_only", "kwargs_sha256": _canonical_sha256(kwargs)}
    f["patch_agent_loop"] = {"behavior_evaluations": [{**report, "report_ref": report_ref,
                              "admission": "accepted", "callback_invoked": True}]}
    full_changes = [{**c, "generation": old["generation"]} for c, old in zip(changes, original["diff_intent"])]
    f["generated_changes_sha256"] = _canonical_sha256(full_changes)
    overlay = {**plan, "proposed_changes": full_changes}
    payload = PatchProposalBuilder().build(overlay, evidence_pack=admitted.evidence_pack,
                                          source_snippet_char_limit=1).to_artifact_payload()
    proposal_ref = inputs.store.write(feature_id=request.feature_spec_ref.feature_id, artifact_type="patch_proposal",
        payload=payload, status="success", upstream_refs=[request.implementation_plan_ref, request.evidence_pack_ref])
    review = ProposalReviewer().review(payload, evidence_pack=admitted.evidence_pack,
        implementation_plan=plan, feature_spec=admitted.feature_spec).to_artifact_payload()
    assert {r["rule_id"] for r in review["findings"] if r["level"] == "blocking"} == {"context_pack"}
    review_ref = inputs.store.write(feature_id=request.feature_spec_ref.feature_id, artifact_type="proposal_review",
        payload=review, status="blocked", upstream_refs=[proposal_ref])
    parent_id, logical_id = "fixture-product", "fixture-logical"
    terminal = {**j["terminal_result"], "terminal_stage": "review_proposal", "request_id": logical_id,
        "approval_granted": False, "dry_run_artifact": None, "patch_proposal_artifact": asdict(proposal_ref),
        "proposal_review_artifact": asdict(review_ref)}
    j.update(continuation_selection="product_graph_current_implementation_plan", status="product_execution_finished",
        proposal_admitted=inputs.store.semantic_read_immutable(proposal_ref)["status"] == "success",
        caller={"workspace_root": str(inputs.workspace)}, request_id=logical_id, parent_run_id=parent_id,
        parent_product_run_id=parent_id, model_role="initial_patch", max_model_calls=4,
        artifacts={"patch_proposal": asdict(proposal_ref), "proposal_review": asdict(review_ref)},
        terminal_result=terminal, terminal_result_sha256=_canonical_sha256(terminal),
        current_snapshot_sha256=_source_tree_snapshot_sha256(admitted.source_tree_snapshot),
        source_validation=admitted.source_validation)
    basis = "reserved_provider_invocations_not_transport_proof"
    prior_budget = {"maximum": 14, "consumed": 2, "remaining": 12, "count_basis": basis,
                   "by_stage": {"initial_patch": {"maximum": 4, "consumed": 0, "remaining": 4},
                                "planning": {"maximum": 2, "consumed": 0, "remaining": 2},
                                "repair": {"maximum": 4, "consumed": 0, "remaining": 4},
                                "requirement_findings": {"maximum": 2, "consumed": 1, "remaining": 1},
                                "requirement_projection": {"maximum": 2, "consumed": 1, "remaining": 1}}}
    budget = {"maximum": 12, "consumed": 5, "remaining": 7, "count_basis": basis,
              "by_stage": {"initial_patch": {"maximum": 4, "consumed": 1, "remaining": 3},
                           "planning": {"maximum": 2, "consumed": 2, "remaining": 0},
                           "repair": {"maximum": 4, "consumed": 0, "remaining": 4},
                           "requirement_findings": {"maximum": 1, "consumed": 1, "remaining": 0},
                           "requirement_projection": {"maximum": 1, "consumed": 1, "remaining": 0}}}
    from src.mod_agent.product_execution import (
        ProductBuildCompletionV1,
        ProductExecutionBlockerV1,
        ProductExecutionFactsV1,
        _ProductExecutionResultIdentityV1,
        empty_product_validation_facts,
        project_product_execution_result,
    )
    product = project_product_execution_result(ProductExecutionFactsV1(
        request=_ProductExecutionResultIdentityV1(run_id=parent_id, request_id=logical_id, requested_completion_scope="compile_only"),
        feature_id=j["feature_id"], terminal_node=None, store_attempts=(), outputs=(), effect_events=(),
        validation_facts=empty_product_validation_facts(), blockers=(ProductExecutionBlockerV1(
            contract_version="1", code="FIXTURE_PLATFORM_BLOCK", message="Synthetic fixture only.",
            stage="graph_start", owner="platform", source_node="graph_start"),),
        variant_result=ProductBuildCompletionV1(contract_version="1", build_result_ref=None,
            workflow_checkpoint_ref=None, build_status="not_reached", claims_real_build_success=None),
        failure_stage="graph_start"), validate_request=False).to_dict()
    parent_ref = _save(inputs.workspace / "run_result.json", {"run_id": parent_id, "product_execution_result": product,
        "actual_write_performed": False, "model_call_budget": budget, "model_call_count": 5})
    _save(inputs.workspace / "run_manifest.json", {"run_id": parent_id, "request_id": logical_id,
        "isolated_workspace": str(inputs.workspace), "target_source": str(sources),
        "source_snapshot_sha256": source_snapshot_sha256(source_snapshot(sources)), "terminal_record": parent_ref})
    previous_ref = _save(tmp_path / "prior-result.json", {"run_id": "fixture-prior", "model_call_budget": prior_budget,
        "product_execution_result": {"request_id": logical_id}})
    prior_ref = _save(tmp_path / "prior-summary.json", {"run_id": "fixture-prior", "public_result_ref": previous_ref,
                     "stage_budget": prior_budget})
    logical = {"current_run_id": parent_id, "previous_run_id": "fixture-prior", "logical_request_id": logical_id,
        "previous_summary_ref": prior_ref, "previously_consumed": 2, "original_maximum": 14,
        "this_invocation_maximum": 12, "previous_stage_budget": prior_budget["by_stage"], "count_basis": basis,
        "this_invocation_stage_limits": {k: v["remaining"] for k, v in prior_budget["by_stage"].items()},
        "worker_segment_maximum": 4}
    j.update(shared_model_budget=budget, parent_product_result_identity={"run_id": parent_id,
        "owner": "ProductExecutionResultV1", "hash_basis": "canonical_owner_to_dict", "sha256": _canonical_sha256(product)})
    journal_ref = _save(tmp_path / "saved-attempt.json", j)
    logical_ref = _save(tmp_path / "logical.json", logical)
    request = replace(request, attempt_id="fixture-saved", saved_patch_selection={"source_attempt_ref": journal_ref,
                                                                                "logical_budget_ref": logical_ref})
    return request, admitted, j, logical, full_changes


def test_missing_selection_cannot_admit_saved_code():
    from types import SimpleNamespace

    from src.mod_agent.saved_patch_admission import admit_saved_patch

    with pytest.raises(ValueError, match="SAVED_PATCH_SELECTION_INVALID"):
        admit_saved_patch(SimpleNamespace(saved_patch_selection=None), None)


def test_saved_response_reconstructs_exact_code_without_effects(case, tmp_path, monkeypatch):
    import socket

    from src.mod_agent.artifacts import ArtifactStore
    from src.mod_agent.saved_patch_admission import admit_saved_patch
    request, admitted, journal, _logical, changes = case
    before = _snapshot(tmp_path)
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("No model/network in admission"))
    monkeypatch.setattr(ArtifactStore, "write", lambda *a, **k: pytest.fail("No Artifact writes in admission"))
    result = admit_saved_patch(request, admitted)
    assert result["changes"] == tuple(changes)
    assert result["logical_budget"]["original_maximum"] == 14
    assert result["logical_budget"]["consumed"] == 7
    assert result["logical_budget"]["remaining"] == 7
    assert result["logical_budget"]["new_model_allowance"] == 0
    assert result["logical_budget"]["by_stage"]["planning"] == {"maximum": 2, "consumed": 2, "remaining": 0}
    assert sum(r["consumed"] for r in result["logical_budget"]["by_stage"].values()) == 7
    assert sum(r["remaining"] for r in result["logical_budget"]["by_stage"].values()) == 7
    assert result["inherited_model_budget"] == journal["shared_model_budget"]
    assert result["historical_verification"]["executed"] is False
    assert result["historical_verification"]["new_compilations"] == 0
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("damage", ["response", "source", "terminal", "parent", "budget", "stage_budget", "report", "dependency"])
def test_saved_admission_rejects_identity_drift_even_with_rehashed_selection(case, tmp_path, damage):
    from src.mod_agent.saved_patch_admission import admit_saved_patch
    request, admitted, journal, logical, _ = case
    if damage == "response":
        Path(journal["factory_receipt"]["model_response"]["path"]).write_bytes(b"changed response")
    elif damage == "source":
        path = Path(request.workspace_root) / admitted.source_validation["files"][0]["source_path"]
        path.write_bytes(path.read_bytes() + b"\n// changed")
    elif damage == "terminal":
        journal["terminal_result"]["approval_granted"] = True
        from src.mod_agent.fresh_planning_continuation import _canonical_sha256
        journal["terminal_result_sha256"] = _canonical_sha256(journal["terminal_result"])
    elif damage == "parent":
        journal["parent_product_result_identity"]["sha256"] = "0" * 64
    elif damage == "budget":
        logical["original_maximum"] = 140
    elif damage == "stage_budget":
        logical["this_invocation_stage_limits"]["initial_patch"] = 5
    elif damage == "report":
        Path(journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]["report_ref"]["path"]).write_bytes(b"{}")
    elif damage == "dependency":
        (tmp_path / "deps/dep.dll").write_bytes(b"changed dependency")
    selection = {"source_attempt_ref": _save(Path(request.saved_patch_selection["source_attempt_ref"]["path"]), journal),
                 "logical_budget_ref": _save(Path(request.saved_patch_selection["logical_budget_ref"]["path"]), logical)}
    request = replace(request, saved_patch_selection=selection)
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError):
        admit_saved_patch(request, admitted)
    assert _snapshot(tmp_path) == before


def test_context_review_cannot_hide_other_structured_blockers(case):
    from src.mod_agent.artifacts import ArtifactRef
    from src.mod_agent.fresh_planning_continuation import _canonical_sha256
    from src.mod_agent.saved_patch_admission import admit_saved_patch
    request, admitted, journal, _logical, _ = case
    old = admitted.artifact_store.semantic_read_immutable(ArtifactRef(**journal["artifacts"]["proposal_review"]))
    changed = deepcopy(old["data"])
    changed["findings"].append({"rule_id": "binding_source_locality", "level": "blocking", "message": "fixture",
                                "change_id": None, "evidence_refs": []})
    review_ref = admitted.artifact_store.write(feature_id=request.feature_spec_ref.feature_id,
        artifact_type="proposal_review", status="blocked", payload=changed,
        upstream_refs=[ArtifactRef(**journal["artifacts"]["patch_proposal"])])
    journal["artifacts"]["proposal_review"] = asdict(review_ref)
    journal["terminal_result"]["proposal_review_artifact"] = asdict(review_ref)
    journal["terminal_result_sha256"] = _canonical_sha256(journal["terminal_result"])
    selection = {**request.saved_patch_selection,
        "source_attempt_ref": _save(Path(request.saved_patch_selection["source_attempt_ref"]["path"]), journal)}
    with pytest.raises(ValueError, match="SAVED_PATCH_REVIEW_NOT_CONTEXT_ONLY"):
        admit_saved_patch(replace(request, saved_patch_selection=selection), admitted)


def test_current_reviewer_can_reject_newly_detected_noncontext_rule(case, monkeypatch):
    from types import SimpleNamespace

    from src.mod_agent.proposal.reviewer import ProposalReviewer
    from src.mod_agent.saved_patch_admission import admit_saved_patch
    request, admitted, *_ = case
    observed = []

    def strict_review(self, proposal, **kwargs):
        observed.append(kwargs)
        return SimpleNamespace(to_artifact_payload=lambda: {"decision": "revise_proposal", "findings": [
            {"level": "blocking", "rule_id": "scope_boundary"}]})

    monkeypatch.setattr(ProposalReviewer, "review", strict_review)
    with pytest.raises(ValueError, match="SAVED_PATCH_CURRENT_REVIEW_NOT_CONTEXT_ONLY"):
        admit_saved_patch(request, admitted)
    assert observed[0]["domain_policy"] is not None
    assert observed[0]["require_executable_patch"] is True
