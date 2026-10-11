"""Bound compiler candidates retain blocked Findings through existing continuations."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from src.mod_agent.build.baseline_repair import baseline_failure_model_view
from src.mod_agent.evidence import EvidencePack, build_requirement_coverage_pack, materialize_requirement_coverage_projection
from src.mod_agent.evidence.compilation_candidate import KEY, attach_compilation_candidate, compilation_candidate_scope
from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationAttemptJournal, PatchContinuationError, PlanningContinuationError,
    preflight_patch_continuation, preflight_planning_continuation,
)
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from tests.unit.test_fresh_planning_continuation import _inputs, _patch_request, _positive_findings, _projection
from tests.unit.test_patch_worker_configuration import _write_configuration


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("No live provider in candidate admission tests"))


def _candidate_inputs(tmp_path, *, status="blocked", evaluator=True):
    inputs = _inputs(tmp_path)
    configuration_path, _, _ = _write_configuration(tmp_path,
        "def make_evaluator():\n    return lambda context: {}\n" if evaluator else None)
    configuration = PatchWorkerConfiguration.load(configuration_path)
    old = EvidencePack.from_artifact_payload(inputs.store.read(inputs.evidence_ref)["data"])
    materialized = materialize_requirement_coverage_projection(feature_data=inputs.feature_payload,
        request=inputs.feature_payload["user_request"], projection=_projection())
    findings = _positive_findings(materialized, old)
    findings["findings"][0].update(relationship="missing", edit_target_evidence_ids=[],
        unresolved_gaps=["Investigate the compiler-observed missing identifier before judging the candidate."])
    pack = build_requirement_coverage_pack(query=old.query, materialized_projection=materialized,
        retrieved_pack=old, findings=findings)
    item = next(row for row in pack.items if row.evidence_id == inputs.request.planning_target_evidence_ids[0])
    diagnostic = {"file": "Behavior.cs", "line": item.span["start_line"], "column": 1,
        "severity": "error", "code": "CS0103", "message": "Missing identifier in current source.",
        "source_sha256": item.source_hash}
    observation = baseline_failure_model_view([diagnostic], source_prefix="generated_mods/SyntheticMod",
        source_snapshot_sha256=hashlib.sha256(inputs.behavior.read_bytes()).hexdigest())
    pack = replace(pack, budget_summary={"baseline_compilation_failure": observation})
    pack = attach_compilation_candidate(pack, feature_spec=inputs.feature_payload,
        worker_configuration_ref=configuration.reference)
    assert pack.can_generate_patch is False
    if evaluator:
        assert compilation_candidate_scope(pack.to_artifact_payload())
    return _rewrite_evidence(inputs, pack.to_artifact_payload(), status=status), configuration


def _rewrite_evidence(inputs, payload, *, status="blocked", feature_ref=None):
    feature_ref = feature_ref or inputs.feature_ref
    ref = inputs.store.write(feature_id=feature_ref.feature_id, artifact_type="evidence_pack",
        payload=payload, status=status, upstream_refs=[feature_ref])
    return replace(inputs, evidence_ref=ref, feature_ref=feature_ref,
        request=replace(inputs.request, evidence_pack_ref=ref, feature_spec_ref=feature_ref))


def _candidate_patch_request(inputs, configuration):
    request = _patch_request(inputs)
    return replace(request, worker_configuration_ref=configuration.reference, worker_profile_sha256="1" * 64)


def _journal(request):
    return PatchContinuationAttemptJournal.for_product_execution(
        artifact_root=request.artifact_store_root, run_id="candidate-patch", request_id="candidate-request",
        parent_run_id="candidate-product", feature_spec_ref=request.feature_spec_ref,
        evidence_pack_ref=request.evidence_pack_ref, implementation_plan_ref=request.implementation_plan_ref,
        workspace_root=request.workspace_root, max_model_calls=5,
        worker_configuration_ref=request.worker_configuration_ref, worker_profile_sha256=request.worker_profile_sha256)


def test_candidate_continues_planning_patch_and_product_journal_without_rewriting_findings(tmp_path):
    inputs, configuration = _candidate_inputs(tmp_path)
    original = inputs.store.read(inputs.evidence_ref)
    admitted = preflight_planning_continuation(inputs.request)
    assert admitted.evidence_pack == original["data"]
    assert original["status"] == "blocked" and original["data"]["can_generate_patch"] is False
    request = _candidate_patch_request(inputs, configuration)
    patch = preflight_patch_continuation(request)
    assert patch.evidence_pack == original["data"]
    assert set(row["evidence_id"] for row in patch.implementation_plan["binding_registry"]["edit_bindings"]).issubset(
        compilation_candidate_scope(patch.evidence_pack)["evidence_ids"])
    journal = _journal(request)
    assert journal.path.is_file()
    assert inputs.store.read(inputs.evidence_ref) == original
    assert json.loads(journal.path.read_bytes())["max_model_calls"] == 5


@pytest.mark.parametrize("status", ["failed", "stubbed", "skipped"])
def test_candidate_does_not_admit_other_artifact_statuses(tmp_path, status):
    inputs, _ = _candidate_inputs(tmp_path, status=status)
    with pytest.raises(PlanningContinuationError, match="ARTIFACT_STATUS_INVALID"):
        preflight_planning_continuation(inputs.request)


@pytest.mark.parametrize("damage", ["unbound", "scope_ids", "feature", "source", "worker_bytes", "factory_bytes", "no_evaluator"])
def test_candidate_planning_rechecks_scope_source_and_configured_evaluator(tmp_path, damage):
    inputs, configuration = _candidate_inputs(tmp_path, evaluator=damage != "no_evaluator")
    payload = deepcopy(inputs.store.read(inputs.evidence_ref)["data"])
    if damage == "unbound":
        payload["budget_summary"].pop(KEY)
    elif damage == "scope_ids":
        payload["budget_summary"][KEY]["evidence_ids"] = ["invented"]
    elif damage == "feature":
        payload["budget_summary"][KEY]["feature_spec_sha256"] = "0" * 64
    elif damage == "source":
        inputs.behavior.write_text("changed", encoding="utf-8")
    elif damage == "worker_bytes":
        from pathlib import Path
        path = Path(configuration.reference["path"])
        path.write_bytes(path.read_bytes() + b" ")
    elif damage == "factory_bytes":
        (tmp_path / "trusted_factory.py").write_text("changed", encoding="utf-8")
    if damage in {"unbound", "scope_ids", "feature"}:
        inputs = _rewrite_evidence(inputs, payload)
    with pytest.raises(PlanningContinuationError):
        preflight_planning_continuation(inputs.request)


@pytest.mark.parametrize("entry", ["patch", "journal"])
def test_candidate_worker_cannot_be_replaced_or_omitted(tmp_path, entry):
    inputs, configuration = _candidate_inputs(tmp_path)
    request = _candidate_patch_request(inputs, configuration)
    dispatch = preflight_patch_continuation if entry == "patch" else _journal
    with pytest.raises(PatchContinuationError):
        dispatch(replace(request, worker_configuration_ref=None, worker_profile_sha256=None))
    other = tmp_path / "other-worker.json"
    from pathlib import Path
    other.write_bytes(Path(configuration.reference["path"]).read_bytes())
    with pytest.raises(PatchContinuationError):
        dispatch(replace(request, worker_configuration_ref=PatchWorkerConfiguration.load(other).reference))


@pytest.mark.parametrize("entry", ["patch", "journal"])
def test_candidate_cannot_select_another_evidence_revision_than_the_plan(tmp_path, entry):
    inputs, configuration = _candidate_inputs(tmp_path)
    request = _candidate_patch_request(inputs, configuration)
    payload = deepcopy(inputs.store.read(inputs.evidence_ref)["data"])
    payload["budget_summary"]["unrelated_note"] = "a different revision"
    other = _rewrite_evidence(inputs, payload)
    dispatch = preflight_patch_continuation if entry == "patch" else _journal
    with pytest.raises(PatchContinuationError, match="UPSTREAM"):
        dispatch(replace(request, evidence_pack_ref=other.evidence_ref))


@pytest.mark.parametrize("entry", ["patch", "journal"])
@pytest.mark.parametrize("kind,status", [
    ("evidence_pack", "failed"),
    ("evidence_pack", "stubbed"),
    ("feature_spec", "blocked"),
    ("implementation_plan", "blocked"),
])
def test_candidate_exception_only_accepts_blocked_evidence(tmp_path, entry, kind, status):
    inputs, configuration = _candidate_inputs(tmp_path)
    request = _candidate_patch_request(inputs, configuration)
    original = inputs.store.read(getattr(request, kind + "_ref"))
    upstream = {
        "feature_spec": [],
        "evidence_pack": [request.feature_spec_ref],
        "implementation_plan": [request.feature_spec_ref, request.evidence_pack_ref],
    }[kind]
    rejected = inputs.store.write(feature_id=request.feature_spec_ref.feature_id,
        artifact_type=kind, payload=original["data"], status=status, upstream_refs=upstream)
    dispatch = preflight_patch_continuation if entry == "patch" else _journal
    with pytest.raises(PatchContinuationError, match="ARTIFACT_STATUS_INVALID"):
        dispatch(replace(request, **{kind + "_ref": rejected}))
    assert not (inputs.store.root / "cr").exists()


@pytest.mark.parametrize("entry", ["patch", "journal"])
def test_candidate_source_drift_is_rejected_before_worker_receipt(tmp_path, entry):
    inputs, configuration = _candidate_inputs(tmp_path)
    request = _candidate_patch_request(inputs, configuration)
    inputs.behavior.write_text(inputs.behavior.read_text(encoding="utf-8") + "// source changed\n",
        encoding="utf-8")
    dispatch = preflight_patch_continuation if entry == "patch" else _journal
    with pytest.raises(PatchContinuationError, match="SOURCE_HASH_MISMATCH"):
        dispatch(request)
    assert not (inputs.store.root / "cr").exists()


@pytest.mark.parametrize("entry", ["patch", "journal"])
def test_candidate_plan_cannot_expand_to_other_retrieved_source(tmp_path, entry):
    inputs, configuration = _candidate_inputs(tmp_path)
    request = _candidate_patch_request(inputs, configuration)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    scope = compilation_candidate_scope(evidence)
    outside = next(item for item in evidence["items"]
        if item["source_type"] == "target_source" and item["evidence_id"] not in scope["evidence_ids"])
    plan = deepcopy(inputs.store.read(request.implementation_plan_ref)["data"])
    binding = plan["binding_registry"]["edit_bindings"][0]
    binding.update(evidence_id=outside["evidence_id"], canonical_target_path=outside["source_path"],
        source_hash=outside["source_hash"], target_symbol=outside["symbol"], target_span=outside["span"])
    expanded = inputs.store.write(feature_id=request.feature_spec_ref.feature_id,
        artifact_type="implementation_plan", payload=plan, status="success",
        upstream_refs=[request.feature_spec_ref, request.evidence_pack_ref])
    dispatch = preflight_patch_continuation if entry == "patch" else _journal
    with pytest.raises(PatchContinuationError, match="BINDING_INVALID"):
        dispatch(replace(request, implementation_plan_ref=expanded))
    assert not (inputs.store.root / "cr").exists()


def test_product_request_worker_reaches_original_journal_with_remaining_budget(tmp_path):
    from src.mod_agent.local_entry import LOCAL_OLLAMA_PATCH_PROFILE_VERSION, LocalOllamaInitialPatchProfileV1
    from src.mod_agent.request_patch_execution import RequestPatchExecution
    from src.mod_agent.workflow import create_initial_state

    inputs, configuration = _candidate_inputs(tmp_path)
    request = _candidate_patch_request(inputs, configuration)
    state = create_initial_state(run_id="candidate-product", request_id="candidate-request",
        user_request=inputs.feature_payload["user_request"], target_mod=inputs.feature_payload["target_mod"])
    state["feature_id"] = request.feature_spec_ref.feature_id
    for ref in (request.feature_spec_ref, request.evidence_pack_ref, request.implementation_plan_ref):
        state["artifacts"][ref.artifact_type] = ref.path
        state["artifact_hashes"][ref.artifact_type] = ref.artifact_hash
    state["current_stage"] = "implementation_plan"
    evidence = inputs.store.read(inputs.evidence_ref)
    plan = inputs.store.read(request.implementation_plan_ref)["data"]
    source_before = inputs.behavior.read_bytes()
    worker_arguments = []

    class WorkerConstructionObserved(Exception):
        pass

    def observe_worker(**kwargs):
        worker_arguments.append(kwargs)
        raise WorkerConstructionObserved

    profile = LocalOllamaInitialPatchProfileV1(profile_version=LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        base_url="http://127.0.0.1:11434", model="qwen3:4b-instruct", context_window=8192,
        output_budget=1024, timeout_seconds=30.0)
    execution = RequestPatchExecution(artifact_store=inputs.store, workspace_root=inputs.workspace,
        profile=profile, identity_reader=lambda *_: pytest.fail("No provider identity call during journal admission"),
        policy=configuration.policy, reserve_model_call=lambda *_: pytest.fail("No model call during journal admission"),
        budget_snapshot=lambda: {"remaining": 2, "by_stage": {"initial_patch": {"remaining": 2}}},
        behavior_evaluator=configuration.behavior_evaluator(), worker_configuration_ref=configuration.reference,
        adapter_factory=observe_worker)
    with pytest.raises(WorkerConstructionObserved):
        execution(state, plan, evidence["data"])
    assert len(execution.journals) == len(worker_arguments) == 1
    document = json.loads(execution.journals[0].path.read_bytes())
    assert document["continuation_selection"] == "product_graph_current_implementation_plan"
    assert document["worker_configuration_ref"] == configuration.reference
    assert document["max_model_calls"] == worker_arguments[0]["patch_agent_loop_policy"].max_total_model_turns == 2
    assert document["model_call_count"] == 0
    assert inputs.behavior.read_bytes() == source_before
    assert inputs.store.read(inputs.evidence_ref) == evidence
