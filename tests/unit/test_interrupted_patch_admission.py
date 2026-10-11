"""Offline native transcripts qualify interrupted-response admission and recovery."""
import json
import shutil
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from src.libs.llm import AgentMessage, AgentResponseFormat, AgentTurnRequest, OllamaChatAgentAdapter
from src.mod_agent.interrupted_patch_admission import admit_interrupted_patch, prepare_retained_generation
from src.mod_agent.errors import LocalEntryError
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter, _patch_agent_context_json
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from src.mod_agent.saved_patch_admission import _hash
from tests.unit.test_fresh_planning_continuation import _inputs, _local_patch_adapter, _patch_request
from tests.unit.test_saved_patch_admission import _ref, _save


@pytest.fixture
def interrupted(tmp_path):
    from src.mod_agent.fresh_planning_continuation import _csharp_source_snapshot, _source_tree_snapshot_sha256, _validate_source_items
    inputs = _inputs(tmp_path)
    request = _patch_request(inputs)
    selected = {kind: asdict(getattr(request, kind + "_ref")) for kind in ("feature_spec", "evidence_pack", "implementation_plan")}
    docs = {kind: inputs.store.read(getattr(request, kind + "_ref"))["data"] for kind in selected}
    state = {"run_id": "original-worker", "request_id": "logical", "feature_id": inputs.feature_ref.feature_id,
        "user_request": inputs.feature_payload["user_request"], "artifacts": {kind: ref["path"] for kind, ref in selected.items()},
        "artifact_hashes": {kind: ref["artifact_hash"] for kind, ref in selected.items()}}
    adapter, _ = _local_patch_adapter(inputs)
    adapter.bind_attempt_recorder(lambda event: None)
    adapter(state, docs["implementation_plan"], docs["evidence_pack"])
    factory = adapter.patch_attempt_receipt()
    response = factory["model_response"]
    content = Path(response["path"]).read_bytes().decode("utf-8")
    _, prepared, _ = prepare_retained_generation(docs["feature_spec"], docs["evidence_pack"], docs["implementation_plan"],
        {"content": content, "model": response["model"]})
    profile = replace(adapter.profile, context_window=32768)
    identity = deepcopy(factory["model_identity"])
    identity["details"]["context_length"] = 32768
    effective = AgentTurnRequest(messages=tuple(AgentMessage(role=m.role, content=m.content) for m in prepared.messages),
        response_format=AgentResponseFormat("patch_generation_v2", "Return patch", dict(prepared.response_schema)))
    wire_path = tmp_path / "wire.json"
    native = {"model": profile.model, "done": True, "done_reason": "stop", "message": {"role": "assistant", "content": content},
        "prompt_eval_count": 3000, "eval_count": 200}
    def sender(url, payload, headers):
        import httpx
        wire_path.write_bytes(httpx.Request("POST", url, json=payload).content)
        return deepcopy(native)
    normalized = OllamaChatAgentAdapter(base_url=profile.base_url, model=profile.model,
        max_output_tokens=profile.output_budget, context_window=profile.context_window,
        request_timeout_seconds=profile.timeout_seconds, request_sender=sender).complete_turn(effective)
    request_path = tmp_path / "effective.json"
    request_path.write_text(_patch_agent_context_json(asdict(effective)), encoding="utf-8")
    native_ref = _save(tmp_path / "native.json", asdict(normalized))
    turn = {"turn_index": 1, "status": "responded", "response_origin": "live_provider_response",
        "request_ref": _ref(request_path), "request_sha256": _hash(asdict(effective)), "response_ref": native_ref,
        "provider_request_ref": _ref(wire_path), "provider_request_sha256": _ref(wire_path)["sha256"]}
    target = inputs.workspace / "generated_mods/SyntheticMod"
    canonical = tmp_path / "canonical/SyntheticMod"
    baseline = inputs.workspace / "baseline_source/SyntheticMod"
    shutil.copytree(target, canonical)
    shutil.copytree(target, baseline)
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text('''from tests.unit.test_patch_behavior_feedback import _BehaviorOracle
def create(root):
    from pathlib import Path
    return _BehaviorOracle(Path(root))
''', encoding="utf-8")
    policy = PatchAgentLoopPolicy(require_source_inspection=False, max_total_model_turns=9, model_call_budget_policy="task_total_only",
        allow_upstream_request=True, max_observation_bytes=32768)
    worker_ref = _save(tmp_path / "worker.json", {"schema_version": "patch_worker_configuration_v1", "policy": asdict(policy),
        "enable_recovery_loop": True, "behavior_evaluator": {"factory_ref": _ref(evaluator), "factory_name": "create",
            "kwargs": {"root": str(tmp_path / "observations")}}})
    factory.update(profile=profile.to_dict(), model_identity=identity, post_response_model_identity=identity,
        status="model_response_persisted", failure=None, model_call_count=1, worker_turns=[turn],
        patch_response_contract={"schema_sha256": prepared.schema_sha256},
        model_call_budget={"maximum_total_model_calls": 9, "minimum_total_model_calls": 1},
        upstream_effects={"evidence": "assess_and_continue", "planning": "assess_and_continue"},
        patch_agent_loop={"policy": asdict(policy), "model_turns_used": 1, "tool_rounds_used": 0,
            "total_observation_bytes": 0, "observation_trace": [], "recovery_revisions": [], "recovery_observation_bytes": 0})
    budget = {"maximum": 12, "consumed": 4, "remaining": 8, "policy": "task_total_only",
        "count_basis": "reserved_provider_invocations_not_transport_proof", "by_stage": {kind: {"consumed": count}
            for kind, count in {"initial_patch": 1, "repair": 0, "requirement_projection": 1, "requirement_findings": 1, "planning": 1}.items()}}
    journal = {"receipt_version": "patch_continuation_attempt_v1", "continuation_selection": "product_graph_current_implementation_plan",
        "parent_run_id": inputs.workspace.name, "run_id": "original-worker", "request_id": "logical", "feature_id": inputs.feature_ref.feature_id,
        "caller": {"workspace_root": str(inputs.workspace)}, "status": "local_patch_post_response_model_admitted",
        "proposal_admitted": False, "artifacts": {}, "factory_receipt": factory, "shared_model_budget": budget,
        "model_role": "initial_patch", "model_call_count": 1, "max_model_calls": 9,
        "worker_configuration_ref": worker_ref, "worker_profile_sha256": _hash(profile.to_dict()), "selected_artifacts": selected,
        "source_validation": _validate_source_items(docs["evidence_pack"], inputs.workspace),
        "generated_against_snapshot_sha256": _source_tree_snapshot_sha256(_csharp_source_snapshot(inputs.workspace)),
        "current_snapshot_sha256": _source_tree_snapshot_sha256(_csharp_source_snapshot(inputs.workspace))}
    manifest = {"run_id": inputs.workspace.name, "request_id": "logical", "request": state["user_request"],
        "isolated_workspace": str(inputs.workspace), "target_source": str(canonical), "actual_write_performed": False,
        "source_snapshot_sha256": source_snapshot_sha256(source_snapshot(canonical)), "local_model_identity": identity,
        "ollama_patch_generation_profile": profile.to_dict(), "nuget_isolated_build_profile": {"working_directory": str(target)},
        "baseline_build": {"build_profile": {"working_directory": str(baseline)}}}
    manifest_ref = _save(inputs.workspace / "run_manifest.json", manifest)
    data = {"inputs": inputs, "state": state, "journal": journal, "manifest": manifest, "profile": profile,
        "selection": {"source_attempt_ref": {}, "parent_manifest_ref": manifest_ref}, "root": tmp_path}
    _rewrite(data)
    return data


def _rewrite(data):
    journal = data["journal"]
    journal["events"] = [{"phase": journal["status"], "model_call_count": journal["model_call_count"],
        "shared_model_budget": deepcopy(journal["shared_model_budget"]), "factory_receipt": deepcopy(journal["factory_receipt"])}]
    data["selection"]["source_attempt_ref"] = _save(data["inputs"].store.root / "cr/interrupted.json", journal)
    stop = {"schema_version": "interrupted-execution-stop.v1", "origin": "host_controller",
        **{key: data["selection"][key] for key in ("source_attempt_ref", "parent_manifest_ref")},
        "original_execution_stopped": True, "source_model_claim": False, "stop_method": "synthetic controlled interruption",
        "execution_handle": "fixture:1", "evidence": "Offline fixture owns and stopped the synthetic worker.",
        "terminal_result": {"exit_code": 1}, "confirmation": {"tool": "fixture", "observed_utc": "2026-10-02T00:00:00Z",
            "scope": "fixture worker", "matching_process_count": 0}}
    data["selection"]["execution_stop_ref"] = _save(data["root"] / "stop.json", stop)


def _admit(data, **kwargs):
    return admit_interrupted_patch(data["selection"], workspace_root=data["inputs"].workspace,
        artifact_store=data["inputs"].store, **kwargs)


def _worker(data, monkeypatch, *, client=None, evaluator=None):
    admitted = _admit(data)
    configuration = PatchWorkerConfiguration.load(admitted["worker_configuration_ref"]["path"])
    verifier = configuration.behavior_evaluator()
    if evaluator is not None:
        verifier._delegate = evaluator
    calls, events = [], []
    def client_factory(profile):
        assert client is not None, "Passing retained code must not construct a model client"
        return client
    worker = LocalOllamaInitialPatchAdapter(profile=data["profile"], artifact_store=data["inputs"].store,
        workspace_root=data["inputs"].workspace, patch_agent_loop_policy=admitted["worker_policy"],
        identity_reader=lambda *a: deepcopy(admitted["factory_receipt"]["model_identity"]),
        agent_turn_client_factory=client_factory, llm_factory=lambda *a: pytest.fail("no new draft"),
        behavior_evaluator=verifier, enable_recovery_loop=True)
    worker.bind_interrupted_attempt(admitted)
    worker.bind_upstream_effects(admitted["factory_receipt"]["upstream_effects"])
    worker.bind_attempt_recorder(events.append)
    worker._shared_model_call_reserver = calls.append
    state = {**data["state"], "run_id": "resumed-worker"}
    return worker, state, admitted, calls, events


def test_pure_admission_checks_native_bytes_and_budget_without_evaluator(interrupted, monkeypatch):
    from src.mod_agent.patch_worker_configuration import _LazyBehaviorEvaluator
    monkeypatch.setattr(_LazyBehaviorEvaluator, "_construct", lambda *a: pytest.fail("pure admission"))
    before = {str(p): p.read_bytes() for p in interrupted["root"].rglob("*") if p.is_file()}
    admitted = _admit(interrupted)
    assert admitted["shared_model_budget"]["consumed"] == 4
    assert admitted["inherited_model_call_count"] == 1
    assert admitted["context_calibration"].observations[0][1] == 3000
    assert before == {str(p): p.read_bytes() for p in interrupted["root"].rglob("*") if p.is_file()}


def test_passing_retained_response_verifies_without_new_generation(interrupted, monkeypatch):
    worker, state, admitted, calls, events = _worker(interrupted, monkeypatch)
    changes = worker(state, admitted["implementation_plan"], admitted["evidence_pack"])
    assert calls == []
    receipt = worker.patch_attempt_receipt()
    assert receipt["model_call_count"] == receipt["inherited_model_call_count"] == 1
    assert receipt["new_reserved_model_calls"] == receipt["new_provider_sends"] == 0
    assert changes[0]["generation"]["response_origin"] == "verified_prior_response"
    assert len(receipt["patch_agent_loop"]["behavior_evaluations"]) == 1
    assert _admit(interrupted)["shared_model_budget"] == admitted["shared_model_budget"]
    with pytest.raises(LocalEntryError, match="ALREADY_CONSUMED"):
        worker(state, admitted["implementation_plan"], admitted["evidence_pack"])


@pytest.mark.parametrize("damage", ["missing_stop", "model_stop", "wrong_parent", "live_process", "response", "later_send", "terminal", "budget", "source"])
def test_interrupted_identity_drift_rejects_before_execution(interrupted, damage):
    journal = interrupted["journal"]
    if damage in {"missing_stop", "model_stop", "wrong_parent", "live_process"}:
        if damage == "missing_stop":
            interrupted["selection"].pop("execution_stop_ref")
        else:
            stop = json.loads(Path(interrupted["selection"]["execution_stop_ref"]["path"]).read_bytes())
            if damage == "model_stop": stop["source_model_claim"] = True
            elif damage == "wrong_parent": stop["parent_manifest_ref"]["sha256"] = "0" * 64
            else: stop["confirmation"]["matching_process_count"] = False
            interrupted["selection"]["execution_stop_ref"] = _save(interrupted["root"] / "changed-stop.json", stop)
    elif damage == "response":
        Path(journal["factory_receipt"]["model_response"]["path"]).write_text("{}")
    elif damage == "source":
        interrupted["inputs"].behavior.write_text("// changed")
    else:
        if damage == "later_send": journal["factory_receipt"]["worker_turns"].append({"status": "requested", "turn_index": 2})
        elif damage == "terminal": journal["terminal_result"] = {"status": "terminal"}
        else: journal["shared_model_budget"]["consumed"] = 0
        _rewrite(interrupted)
    with pytest.raises(ValueError):
        _admit(interrupted)


def test_explicit_verifier_change_preserves_original_policy(interrupted):
    original = interrupted["journal"]["worker_configuration_ref"]
    configuration = json.loads(Path(original["path"]).read_bytes())
    configuration["behavior_evaluator"]["kwargs"]["root"] = str(interrupted["root"] / "changed-observations")
    selected = _save(interrupted["root"] / "changed-worker.json", configuration)
    assert _admit(interrupted, worker_configuration_ref=selected)["original_worker_configuration_ref"] == original
    configuration["policy"]["max_observation_bytes"] *= 2
    selected = _save(interrupted["root"] / "changed-worker.json", configuration)
    with pytest.raises(ValueError, match="CONFIGURATION_CHANGED"):
        _admit(interrupted, worker_configuration_ref=selected)


@pytest.mark.parametrize("next_action", ["revision", "upstream", "context_gate"])
def test_failed_verification_uses_retained_context_and_only_charges_new_calls(interrupted, monkeypatch, next_action):
    from src.libs.llm.agent_turn import AgentTurnProviderError
    from src.libs.llm.transport_observation import transport_started
    from tests.unit.test_patch_behavior_feedback import _BehaviorOracle
    oracle = _BehaviorOracle(interrupted["root"] / "feedback", status="behavior_failed")
    def evaluate(context):
        if oracle.contexts:
            oracle.status = None
        return oracle(context)
    original_response = interrupted["journal"]["factory_receipt"]["model_response"]
    revised = Path(original_response["path"]).read_bytes().decode("utf-8").replace("RecordRuntimeMarker();", "RecordRuntimeMarker(); // corrected")
    observed = []
    def sender(url, payload, headers):
        transport_started()
        observed.append(payload)
        message = {"role": "assistant", "content": revised}
        if next_action == "upstream":
            message = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "request_patch_upstream",
                "arguments": {"required_owner": "planning", "reason": "Another caller requires an edit.",
                    "source_refs": ["binding://edit_binding_001"]}}}]}
        return {"model": interrupted["profile"].model, "done": True, "done_reason": "stop",
            "message": message, "prompt_eval_count": 4000, "eval_count": 50}
    profile = interrupted["profile"]
    client = OllamaChatAgentAdapter(base_url=profile.base_url, model=profile.model,
        context_window=profile.context_window, max_output_tokens=profile.output_budget,
        request_timeout_seconds=profile.timeout_seconds, request_sender=sender)
    if next_action == "context_gate":
        def gate(request):
            raise AgentTurnProviderError("fixture local context gate before transport")
        monkeypatch.setattr(client, "complete_turn", gate)
    worker, state, admitted, calls, events = _worker(interrupted, monkeypatch, client=client, evaluator=evaluate)
    if next_action == "revision":
        changes = worker(state, admitted["implementation_plan"], admitted["evidence_pack"])
        assert changes[0]["generation"]["response_origin"] == "live_provider_response"
        assert changes[0]["generation"]["new_model_calls"] == 1
        assert len(oracle.contexts) == 2
    elif next_action == "upstream":
        with pytest.raises(LocalEntryError, match="PATCH_AGENT_UPSTREAM_REQUESTED"):
            worker(state, admitted["implementation_plan"], admitted["evidence_pack"])
        assert worker.retained_worker_request(complete_upstream=True).tool_results[0].name == "request_patch_upstream"
    else:
        with pytest.raises(Exception, match="context gate|provider|PROVIDER"):
            worker(state, admitted["implementation_plan"], admitted["evidence_pack"])
    receipt = worker.patch_attempt_receipt()
    assert calls == ["patch"]
    assert receipt["model_call_count"] == 2 and receipt["inherited_model_call_count"] == 1
    assert receipt["new_reserved_model_calls"] == 1
    assert receipt["new_provider_sends"] == (0 if next_action == "context_gate" else 1)
    assert receipt["context_calibration_inheritance"]["status"] == "inherited"
    assert receipt["context_calibration_inheritance"]["observed_calibration_count"] == 1
    assert client._prompt_token_calibrations[0] == admitted["context_calibration"].observations[0]
    assert _admit(interrupted)["shared_model_budget"] == admitted["shared_model_budget"]
    assert len(observed) == (0 if next_action == "context_gate" else 1)
