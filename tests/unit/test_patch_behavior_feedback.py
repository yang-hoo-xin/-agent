"""Synthetic no-network qualification of one bounded behavioral correction."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.libs.llm import AgentToolCall, OllamaChatAgentAdapter
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalOllamaInitialPatchAdapter,
    LocalOllamaInitialPatchProfileV1,
    make_exact_no_write_dry_run_factory,
)
from src.mod_agent.proposal import LLMExactPatchGenerator, PatchGenerationError
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _NativePatchLLM,
    _patch_request,
    _PatchAgentTurnClient,
    _source_hashes,
)


def _sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class _BehaviorClient(_PatchAgentTurnClient):
    """A scripted synthetic model, never a replacement implementation for the Mod."""

    def __init__(self, *, fixes=True, invalid=None):
        super().__init__()
        self.fixes = fixes
        self.invalid = invalid

    def complete_turn(self, request):
        response = super().complete_turn(request)
        if response.content is None:
            return response
        last = request.messages[-1].content
        behavior_turn = isinstance(last, dict) and last.get("message_type") == (
            "patch_behavior_correction"
        )
        if not behavior_turn or not self.fixes:
            response = replace(
                response,
                content=response.content.replace("RecordRuntimeMarker", "RecordMissingMarker"),
            )
        if behavior_turn and self.invalid == "tool":
            return replace(
                response,
                tool_calls=(AgentToolCall(call_id="forbidden", name="write", arguments={}),),
            )
        if behavior_turn and self.invalid == "empty":
            return replace(response, content="")
        if behavior_turn and self.invalid == "model":
            return replace(response, model="unadmitted-model")
        return response


class _BehaviorOracle:
    """Observe the generated synthetic marker; do not send an implementation back."""

    def __init__(self, root, *, status=None, owner=None, binding=None, mutate=None):
        self.root = root
        self.status = status
        self.owner = owner
        self.binding = binding
        self.mutate = mutate
        self.contexts = []
        self.reports = []

    def __call__(self, context):
        self.contexts.append(deepcopy(context))
        changes = context["generated_changes"]
        assert context["generated_changes_sha256"] == _sha(changes)
        assert hashlib.sha256(Path(context["model_response"]["path"]).read_bytes()).hexdigest() == (
            context["model_response"]["output_sha256"]
        )
        observed = all("RecordRuntimeMarker();" in change["patch"]["after_text"] for change in changes)
        status = self.status or ("passed" if observed else "behavior_failed")
        owner = self.owner or (None if status == "passed" else "patch_implementation")
        report = {
            "status": status,
            "failure_owner": owner,
            "owner_binding_ids": [] if status == "passed" else [
                self.binding or changes[0]["edit_binding_id"]
            ],
            "observations": [{
                "case_id": "synthetic_marker_present",
                "input": {"enabled": True},
                "expected": {"marker_recorded": True},
                "observed": {"marker_recorded": observed},
                "passed": observed,
            }],
            "generated_changes_sha256": context["generated_changes_sha256"],
            "source_snapshot_sha256": context["source_snapshot_sha256"],
        }
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"observation-{len(self.contexts)}.json"
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True).encode()
        path.write_bytes(payload)
        report["report_ref"] = {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}
        self.reports.append(deepcopy(report))
        if self.mutate is not None:
            self.mutate()
        return report


def _adapter(inputs, client, evaluator):
    identity = {
        "name": client.model, "model": client.model, "digest": "a" * 64,
        "modified_at": "2026-09-04T00:00:00Z", "size": 1,
        "details": {"context_length": 8192}, "capabilities": ["completion", "tools"],
        "base_url": "http://127.0.0.1:11434",
    }
    return LocalOllamaInitialPatchAdapter(
        profile=LocalOllamaInitialPatchProfileV1(
            profile_version=LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
            base_url="http://127.0.0.1:11434", model=client.model,
            context_window=8192, output_budget=1024, timeout_seconds=30.0,
        ),
        artifact_store=inputs.store,
        workspace_root=inputs.workspace,
        patch_agent_loop_policy=PatchAgentLoopPolicy(),
        identity_reader=lambda *_args: deepcopy(identity),
        llm_factory=lambda _profile: _NativePatchLLM(),
        agent_turn_client_factory=lambda _profile: client,
        behavior_evaluator=evaluator,
    )


def _run(inputs, client, evaluator):
    request = _patch_request(inputs)
    adapter = _adapter(inputs, client, evaluator)
    result = run_fresh_patch_continuation(
        request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
        max_model_calls=adapter.patch_agent_loop_policy.max_total_model_turns,
    )
    receipt = json.loads(Path(result.attempt_receipt["path"]).read_text(encoding="utf-8"))
    return result, receipt["factory_receipt"]


def _assert_stopped_before_proposal(result):
    assert result.status != "terminal"
    assert result.patch_proposal_artifact is None
    assert result.proposal_review_artifact is None
    assert result.dry_run_artifact is None


def test_behavior_failure_is_corrected_once_and_revalidated_before_proposal(tmp_path):
    inputs = _inputs(tmp_path)
    source_before = _source_hashes(inputs.workspace)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(tmp_path / "observations")
    result, factory = _run(inputs, client, oracle)

    assert result.status == "terminal"
    assert len(client.requests) == factory["model_call_count"] == 3
    assert len(oracle.contexts) == 2
    assert oracle.reports[0]["status"] == "behavior_failed"
    assert oracle.reports[1]["status"] == "passed"
    assert oracle.contexts[0]["generated_changes_sha256"] != oracle.contexts[1]["generated_changes_sha256"]
    assert _source_hashes(inputs.workspace) == source_before
    correction_request = client.requests[-1]
    assert correction_request.tools == ()
    assert correction_request.tool_choice == "none"
    feedback = correction_request.messages[-1].content["validator_feedback"]
    assert feedback["report_sha256"] == oracle.reports[0]["report_ref"]["sha256"]
    assert feedback["observations"] == oracle.reports[0]["observations"]
    assert "RecordRuntimeMarker" not in json.dumps(feedback)
    loop = factory["patch_agent_loop"]
    assert len(loop["behavior_evaluations"]) == 2
    assert loop["behavior_correction"]["attempt_count"] == 1
    assert loop["behavior_correction"]["status"] == "completed"
    assert len(factory["model_responses"]) == 2
    proposal = inputs.store.read(ArtifactRef(**result.patch_proposal_artifact))["data"]
    generation = proposal["diff_intent"][0]["generation"]
    assert generation["model_response_sha256"] == factory["model_response"]["output_sha256"]
    encoded_refs = json.dumps(generation["patch_agent_loop"], sort_keys=True)
    assert oracle.reports[0]["report_ref"]["sha256"] in encoded_refs
    assert oracle.reports[1]["report_ref"]["sha256"] in encoded_refs
    assert factory["model_response"]["output_sha256"] in encoded_refs


def test_behavior_correction_keeps_the_observed_source_and_assistant_draft(tmp_path):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    result, factory = _run(inputs, client, _BehaviorOracle(tmp_path / "observations"))
    assert result.status == "terminal"
    draft_request, correction_request = client.requests[1:3]
    assert correction_request.tool_results == draft_request.tool_results
    assert correction_request.provider_state == draft_request.provider_state
    assert correction_request.tool_result_insert_index == draft_request.tool_result_insert_index
    assert correction_request.messages[:len(draft_request.messages)] == draft_request.messages
    assert correction_request.messages[-2].role == "assistant"
    assert hashlib.sha256(correction_request.messages[-2].content.encode()).hexdigest() == (
        factory["model_responses"][0]["output_sha256"]
    )
    assert "previous_response" not in correction_request.messages[-1].content
    assert correction_request.tools == ()
    payloads = []

    def record_wire(_url, payload, _headers):
        payloads.append(payload)
        return {"model": client.model, "message": {"content": "{}"}, "done": True}

    OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434", model=client.model,
        max_output_tokens=1024, request_sender=record_wire,
    ).complete_turn(correction_request)
    messages = payloads[0]["messages"]
    assert [message["role"] for message in messages] == [
        "system", "user", "assistant", "tool", "user", "assistant", "user",
    ]
    assert json.loads(messages[3]["content"]) == draft_request.tool_results[0].output
    assert messages[-2]["content"] == correction_request.messages[-2].content
    original_excerpt = correction_request.tool_results[0].output["excerpt"]
    draft_request.tool_results[0].output["excerpt"] = "mutated after return"
    assert correction_request.tool_results[0].output["excerpt"] == original_excerpt


def test_behavior_failure_after_one_correction_preserves_both_responses_and_stops(tmp_path):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient(fixes=False)
    oracle = _BehaviorOracle(tmp_path / "observations")
    result, factory = _run(inputs, client, oracle)

    _assert_stopped_before_proposal(result)
    assert len(client.requests) == factory["model_call_count"] == 3
    assert len(oracle.contexts) == 2
    assert all(report["status"] == "behavior_failed" for report in oracle.reports)
    assert len(factory["model_responses"]) == 2


@pytest.mark.parametrize(("status", "owner", "binding"), [
    ("infrastructure_failed", "environment", None),
    ("identity_failed", "unknown", None),
    ("needs_evidence", "evidence", None),
    ("behavior_failed", "planning", None),
    ("behavior_failed", "validator", None),
    ("behavior_failed", "unknown", None),
    ("behavior_failed", "patch_implementation", "outside_plan"),
])
def test_non_patch_failure_or_unknown_binding_does_not_authorize_correction(tmp_path, status, owner, binding):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(tmp_path / "observations", status=status, owner=owner, binding=binding)
    result, factory = _run(inputs, client, oracle)

    _assert_stopped_before_proposal(result)
    assert len(client.requests) == factory["model_call_count"] == 2
    assert len(oracle.contexts) == 1
    assert factory["model_responses"][0]["retained"] is True


def test_source_drift_during_behavior_evaluation_stops_before_correction(tmp_path):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(
        tmp_path / "observations",
        mutate=lambda: inputs.behavior.write_text("// drift\n", encoding="utf-8"),
    )
    result, factory = _run(inputs, client, oracle)

    _assert_stopped_before_proposal(result)
    assert len(client.requests) == factory["model_call_count"] == 2
    assert len(oracle.contexts) == 1


def test_source_drift_after_materialization_stops_before_evaluator(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(tmp_path / "observations")
    materialize = LLMExactPatchGenerator.materialize_prepared_native

    def drift_after_materialization(self, prepared, response, **kwargs):
        generated = materialize(self, prepared, response, **kwargs)
        inputs.behavior.write_text("// changed after materialization\n", encoding="utf-8")
        return generated

    monkeypatch.setattr(LLMExactPatchGenerator, "materialize_prepared_native", drift_after_materialization)
    result, factory = _run(inputs, client, oracle)
    _assert_stopped_before_proposal(result)
    assert len(client.requests) == factory["model_call_count"] == 2
    assert oracle.contexts == []


@pytest.mark.parametrize("corruption", ["generated_changes_sha256", "source_snapshot_sha256", "report_bytes",
                                       "failure_state_observations"])
def test_behavior_report_must_match_generated_bytes_source_and_persisted_observation(tmp_path, corruption):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(tmp_path / "observations")

    def corrupted_report(context):
        report = oracle(context)
        if corruption == "report_bytes":
            Path(report["report_ref"]["path"]).write_text("changed report", encoding="utf-8")
        elif corruption == "failure_state_observations":
            report[corruption] = []
        else:
            report[corruption] = "f" * 64
        return report

    result, factory = _run(inputs, client, corrupted_report)
    _assert_stopped_before_proposal(result)
    assert len(client.requests) == factory["model_call_count"] == 2
    assert len(oracle.contexts) == 1


def test_evaluator_failure_keeps_initial_response_and_does_not_call_model_again(tmp_path):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()

    def unavailable(_context):
        raise OSError("Synthetic compiler unavailable")

    result, factory = _run(inputs, client, unavailable)
    _assert_stopped_before_proposal(result)
    assert len(client.requests) == factory["model_call_count"] == 2
    assert factory["model_responses"][0]["retained"] is True


def test_valid_report_hash_does_not_authorize_different_returned_content(tmp_path):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(tmp_path / "observations")

    def false_pass(context):
        report = oracle(context)
        # Same valid file/hash and source identities, but a different claimed result.
        return {**report, "status": "passed", "failure_owner": None, "observations": []}

    result, factory = _run(inputs, client, false_pass)
    _assert_stopped_before_proposal(result)
    assert factory["model_call_count"] == len(client.requests) == 2
    assert factory["patch_agent_loop"]["behavior_evaluations"][0]["admission"] == "rejected"


@pytest.mark.parametrize("invalid", ["tool", "empty", "model"])
def test_invalid_behavior_correction_is_retained_before_rejection(tmp_path, invalid):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient(invalid=invalid)
    oracle = _BehaviorOracle(tmp_path / "observations")
    result, factory = _run(inputs, client, oracle)

    _assert_stopped_before_proposal(result)
    assert len(client.requests) == factory["model_call_count"] == 3
    assert len(oracle.contexts) == 1
    assert len(factory["model_responses"]) == 2
    retained = factory["model_responses"][-1]
    assert retained["retained"] is True
    assert Path(retained["path"]).exists()


def test_header_and_behavior_corrections_share_one_total_call_budget(tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(tmp_path / "observations")
    materialize = LLMExactPatchGenerator.materialize_prepared_native
    calls = 0

    def reject_header_once(self, prepared, response, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PatchGenerationError("Synthetic header preservation failure", diagnostics={
                "failure_classification": "csharp_file_header_usings_removed",
                "binding_id": "edit_binding_001", "removed_using_count": 1,
            })
        return materialize(self, prepared, response, **kwargs)

    monkeypatch.setattr(LLMExactPatchGenerator, "materialize_prepared_native", reject_header_once)
    result, factory = _run(inputs, client, oracle)
    assert result.status == "terminal"
    assert len(client.requests) == factory["model_call_count"] == 4
    assert len(factory["model_responses"]) == 3
    assert factory["patch_agent_loop"]["validator_correction"]["attempt_count"] == 1
    assert factory["patch_agent_loop"]["behavior_correction"]["attempt_count"] == 1


def test_behavior_correction_cannot_send_after_total_budget_is_consumed(tmp_path, monkeypatch):
    from src.mod_agent import local_entry

    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    oracle = _BehaviorOracle(tmp_path / "observations")
    run_loop = local_entry.run_patch_agent_loop

    def exhausted_loop(**kwargs):
        result = run_loop(**kwargs)
        # Isolate the post-loop boundary with an already spent five-turn receipt.
        usage = tuple({**result.usage_by_turn[-1], "turn_index": index} for index in range(1, 6))
        return replace(result, model_turns_used=5, usage_by_turn=usage)

    monkeypatch.setattr(local_entry, "run_patch_agent_loop", exhausted_loop)
    result, factory = _run(inputs, client, oracle)
    _assert_stopped_before_proposal(result)
    assert len(client.requests) == 2
    assert factory["model_call_count"] == 5
    assert len(oracle.contexts) == 1
