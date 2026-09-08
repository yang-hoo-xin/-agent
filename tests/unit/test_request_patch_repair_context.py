"""Repair assembly consumes actual retained bytes; providers/build output are test doubles."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.execution import ExactTextPatchApplier
from src.mod_agent.fresh_planning_continuation import preflight_patch_continuation
from src.mod_agent.local_entry import LocalEntryError, LocalOllamaInitialPatchAdapter
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from src.mod_agent.repair import RepairPlanner
from src.mod_agent.request_patch_execution import (
    RequestPatchExecution, admit_product_repair_context, _validate_applied_source_chain,
)
from src.mod_agent.workflow.graph import _reanchor_applied_product_repair, _run_create_repair_plan
from src.mod_agent.workflow.state import create_initial_state
from tests.unit.test_fresh_planning_continuation import _local_patch_adapter
from tests.unit.test_patch_repair_continuation import _repair_case, _RecoveryClient
from tests.unit.test_product_execution import _human_semantic_approve_from_dry_run


def _state(inputs, request, parent):
    state = create_initial_state(run_id="product_repair_run", request_id="product_repair_request",
        user_request=inputs.feature_payload["user_request"], target_mod=inputs.feature_payload["target_mod"])
    state["feature_id"] = inputs.feature_ref.feature_id
    refs = [request.feature_spec_ref, request.evidence_pack_ref, request.implementation_plan_ref,
            ArtifactRef(**parent.patch_proposal_artifact), ArtifactRef(**parent.proposal_review_artifact),
            ArtifactRef(**parent.dry_run_artifact)]
    state["artifacts"] = {ref.artifact_type: ref.path for ref in refs}
    state["artifact_hashes"] = {ref.artifact_type: ref.artifact_hash for ref in refs}
    return state


def _put(state, ref):
    state["artifacts"][ref.artifact_type] = ref.path
    state["artifact_hashes"][ref.artifact_type] = ref.artifact_hash


def _read(inputs, state, kind):
    return inputs.store.semantic_read_immutable(ArtifactRef(feature_id=state["feature_id"],
        artifact_type=kind, path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind]))["data"]


def _arguments(inputs, state, parent):
    return dict(artifact_store=inputs.store, workspace_root=inputs.workspace, state=state,
        implementation=_read(inputs, state, "implementation_plan"),
        evidence_pack=_read(inputs, state, "evidence_pack"),
        worker_receipts=[json.loads(Path(parent.attempt_receipt["path"]).read_bytes())["factory_receipt"]])


@pytest.fixture
def behavior_repair(tmp_path):
    inputs, request, parent = _repair_case(tmp_path)
    admitted = preflight_patch_continuation(request)
    repair = RepairPlanner().from_behavior_failure(
        repair_context=admitted.repair_context, feature_id=inputs.feature_ref.feature_id,
        target_behavior=inputs.feature_payload["target_behavior"], retry_count=0)
    ref = inputs.store.write(feature_id=inputs.feature_ref.feature_id, artifact_type="repair_plan",
        payload=repair.to_artifact_payload(), status="success",
        upstream_refs=[request.repair_parent_proposal_ref, request.repair_parent_review_ref],
        exact_revision_upstream_types={"patch_proposal"})
    state = _state(inputs, request, parent)
    _put(state, ref)
    state.update(current_stage="repair_plan", retry_count=1)
    return inputs, state, parent


def test_unapplied_repair_preserves_exact_original_response_and_behavior_report(behavior_repair):
    inputs, state, parent = behavior_repair
    before = inputs.behavior.read_bytes()
    context = admit_product_repair_context(**_arguments(inputs, state, parent))
    assert context["base_relationship"] == "full_replacement_against_unchanged_parent_base"
    assert context["failure_report"]["status"] == "behavior_failed"
    assert hashlib.sha256(context["previous_response"].encode()).hexdigest() == context["failed_response_ref"]["sha256"]
    assert context["parent_proposal"] == parent.patch_proposal_artifact
    assert context["approval_inherited"] is False
    assert inputs.behavior.read_bytes() == before


@pytest.mark.parametrize("change", ["response", "report", "missing_receipt"])
def test_unapplied_repair_does_not_invent_missing_or_changed_failure_inputs(behavior_repair, change):
    inputs, state, parent = behavior_repair
    arguments = _arguments(inputs, state, parent)
    if change == "response":
        response_path = Path(arguments["worker_receipts"][0]["model_response"]["path"])
        response_path.write_text('{"changes": []}', encoding="utf-8")
    elif change == "report":
        repair = _read(inputs, state, "repair_plan")
        Path(repair["repair_context"]["failure_report_ref"]["path"]).write_text('{}', encoding="utf-8")
    else:
        arguments["worker_receipts"] = []
        repair = _read(inputs, state, "repair_plan")
        Path(repair["repair_context"]["parent_attempt_ref"]["path"]).write_text('{}', encoding="utf-8")
    with pytest.raises(ValueError):
        admit_product_repair_context(**arguments)


@pytest.fixture
def applied_build_repair(tmp_path):
    inputs, request, parent = _repair_case(tmp_path)
    state = _state(inputs, request, parent)
    proposal = _read(inputs, state, "patch_proposal")
    review = _read(inputs, state, "proposal_review")
    dry_run = _read(inputs, state, "dry_run_result")
    applied = ExactTextPatchApplier().run(
        workspace_root=inputs.workspace, proposal=proposal,
        implementation_plan=_read(inputs, state, "implementation_plan"), review=review,
        allow_write=True, approved_diff_hash=dry_run["diff_hash"],
        human_semantic_decision=_human_semantic_approve_from_dry_run(dry_run))
    apply_ref = inputs.store.write(feature_id=state["feature_id"], artifact_type="isolated_apply_result",
        payload={"node_name": "isolated_apply", "stage": "isolated_apply",
                 "message": "Approved patch was applied inside the isolated workspace.", **applied},
        status="success", upstream_refs=[
            ArtifactRef(**parent.patch_proposal_artifact), ArtifactRef(**parent.proposal_review_artifact),
            ArtifactRef(**parent.dry_run_artifact)])
    _put(state, apply_ref)
    relative = inputs.behavior.relative_to(inputs.workspace).as_posix()
    result = BuildAdapter().run_local(feature_id=state["feature_id"],
        profile=BuildProfile(profile_id="unit-test", build_system="dotnet",
            working_directory=str(inputs.workspace), command=("test-double",), timeout_seconds=1),
        command_runner=lambda _profile: BuildCommandResult(exit_code=1,
            stdout=f"{relative}(6,9): error CS0103: The name 'RecordRuntimeMarker' does not exist in the current context"),
        allow_execution=True, input_execution_mode="isolated_apply")
    build_ref = inputs.store.write(feature_id=state["feature_id"], artifact_type="build_result",
        payload=result.to_artifact_payload(), status="failed",
        upstream_refs=[ArtifactRef(**parent.dry_run_artifact), apply_ref])
    _put(state, build_ref)
    state.update(current_stage="build", build_summary={"status": "failed"})
    state = _run_create_repair_plan(state, inputs.store)
    assert not state["blockers"]
    before_refresh = deepcopy(state)
    state = _reanchor_applied_product_repair(state, inputs.store, workspace_root=inputs.workspace)
    assert not state["blockers"]
    return inputs, state, parent, before_refresh


def test_applied_repair_binds_original_build_to_current_graph_owned_baseline(applied_build_repair):
    inputs, state, parent, old_state = applied_build_repair
    context = admit_product_repair_context(**_arguments(inputs, state, parent))
    assert context["base_relationship"] == "revision_against_verified_applied_parent"
    assert context["failure_report"]["status"] == "build_failed"
    assert context["failure_report_origin"] == "build_result_projection"
    assert context["failure_report"]["observations"][0]["code"] == "CS0103"
    assert context["current_plan_ref"]["artifact_hash"] != old_state["artifact_hashes"]["implementation_plan"]
    assert context["parent_proposal"] == parent.patch_proposal_artifact
    assert context["approval_inherited"] is False


@pytest.mark.parametrize("change", ["source", "old_plan", "unexecuted_build"])
def test_applied_repair_rejects_unbound_live_code_or_unexecuted_build(applied_build_repair, change):
    inputs, state, parent, old_state = applied_build_repair
    if change == "source":
        inputs.behavior.write_text(inputs.behavior.read_text(encoding="utf-8") + "// drift\n", encoding="utf-8")
    elif change == "old_plan":
        state = old_state
    else:
        data = _read(inputs, state, "build_result")
        data["real_build_performed"] = False
        path = Path(state["artifacts"]["build_result"])
        envelope = json.loads(path.read_bytes())
        envelope["data"] = data
        path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError):
        admit_product_repair_context(**_arguments(inputs, state, parent))


@pytest.mark.parametrize("applied", [False, True])
def test_request_assembly_feeds_repair_to_actual_shared_worker(
    request, applied, monkeypatch,
):
    fixture = request.getfixturevalue("applied_build_repair" if applied else "behavior_repair")
    inputs, state, parent = fixture[:3]
    arguments = _arguments(inputs, state, parent)
    adapter, llm = _local_patch_adapter(inputs)
    client = _RecoveryClient()
    monkeypatch.setattr(LocalOllamaInitialPatchAdapter, "_default_llm", staticmethod(lambda _profile: llm))
    monkeypatch.setattr(LocalOllamaInitialPatchAdapter, "_default_agent_turn_client", staticmethod(lambda _profile: client))
    calls = []
    execution = RequestPatchExecution(artifact_store=inputs.store, workspace_root=inputs.workspace,
        profile=adapter.profile, identity_reader=adapter.identity_reader,
        policy=PatchAgentLoopPolicy(max_total_model_turns=3),
        reserve_model_call=calls.append,
        budget_snapshot=lambda: {"remaining": 3 - len(calls),
            "by_stage": {"repair": {"remaining": 3 - len(calls)}}})
    original_response_sha256 = arguments["worker_receipts"][0]["model_response"]["output_sha256"]
    execution.receipts = deepcopy(arguments["worker_receipts"])
    before = inputs.behavior.read_bytes()
    changes = execution(state, arguments["implementation"], arguments["evidence_pack"])
    assert changes and calls == ["repair", "repair"]
    assert all("RecordRepairMarker();" in change["patch"]["after_text"] for change in changes)
    assert inputs.behavior.read_bytes() == before
    assert execution.patch_attempt_receipt()["repair_context"]["previous_response_sha256"] == original_response_sha256
    repair_messages = [message.content for message in client.requests[0].messages
                       if isinstance(message.content, dict)
                       and message.content.get("message_type") == "patch_repair_context"]
    assert len(repair_messages) == 1
    assert repair_messages[0]["revision_semantics"] == (
        "complete_replacement_relative_to_current_applied_base" if applied
        else "complete_replacement_relative_to_B0")


@pytest.fixture
def two_applied_changes(tmp_path):
    source = tmp_path / "Subject.cs"
    source.write_text("public sealed class Subject\n{\n    public int First() => 1;\n    public int Second() => 2;\n}\n", encoding="utf-8")
    baseline_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    bindings = {name: {"binding_id": name, "canonical_target_path": "Subject.cs",
        "source_hash": baseline_hash, "target_span": {"start_line": line, "end_line": line}}
        for name, line in (("first", 3), ("second", 4))}
    plan = {"binding_registry": {"edit_bindings": list(bindings.values())}}
    proposal = {"proposal_id": "unit-two-changes", "diff_intent": [
        {"change_id": "first-change", "edit_binding_id": "first", "patch": {"kind": "exact_text_replace",
            "before_text": "public int First() => 1;", "after_text": "public int First() => 3;", "expected_occurrences": 1}},
        {"change_id": "second-change", "edit_binding_id": "second", "patch": {"kind": "exact_text_replace",
            "before_text": "public int Second() => 2;", "after_text": "public int Second() => 4;", "expected_occurrences": 1}},
    ]}
    review = {"decision": "approve_dry_run", "allowed_next_stage": "dry_run_apply"}
    applier = ExactTextPatchApplier()
    dry = applier.run(workspace_root=tmp_path, proposal=proposal, implementation_plan=plan,
                      review=review, allow_write=False)
    applied = applier.run(workspace_root=tmp_path, proposal=proposal, implementation_plan=plan,
                         review=review, allow_write=True, approved_diff_hash=dry["diff_hash"])
    return source, bindings, applied["changes"]


def test_two_patches_in_one_file_validate_ordered_chain_and_only_final_live_hash(two_applied_changes):
    source, bindings, changes = two_applied_changes
    assert changes[0]["after_sha256"] == changes[1]["before_sha256"]
    assert changes[0]["after_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest()
    assert changes[1]["after_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    _validate_applied_source_chain(source.parent, changes, bindings, set(bindings))


@pytest.mark.parametrize("damage", ["intermediate_hash", "cross_file_path"])
def test_multi_patch_chain_damage_rejects_even_when_final_live_bytes_match(two_applied_changes, damage):
    source, bindings, changes = two_applied_changes
    damaged = deepcopy(changes)
    if damage == "intermediate_hash":
        damaged[1]["before_sha256"] = "0" * 64
    else:
        other = source.with_name("Other.cs")
        other.write_bytes(source.read_bytes())
        damaged[1]["path"] = "Other.cs"
    with pytest.raises(LocalEntryError, match="PRODUCT_PATCH_REPAIR_IDENTITY_INVALID"):
        _validate_applied_source_chain(source.parent, damaged, bindings, set(bindings))
