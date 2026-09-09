"""Focused review regressions; all worker responses are offline fixtures."""

import json
from copy import deepcopy
from dataclasses import replace

from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _patch_request,
    _PatchAgentTurnClient,
)
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle
from tests.unit.test_patch_recovery_worker import _InvestigatingClient


class _HardInvalidSubmissionClient(_PatchAgentTurnClient):
    def complete_turn(self, request):
        response = super().complete_turn(request)
        if response.content:
            payload = json.loads(response.content)
            payload["changes"][0]["after_text"] = "\ufeff" + payload["changes"][0]["after_text"]
            return replace(response, content=json.dumps(payload))
        return response


def test_hard_submission_rejection_retains_prior_read_and_byte_usage(tmp_path):
    inputs = _inputs(tmp_path)
    client = _HardInvalidSubmissionClient()
    adapter = _adapter(inputs, client, None)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        max_total_model_turns=3, finalize_after_first_observation=False,
    )
    result = run_fresh_patch_continuation(
        _patch_request(inputs), patch_change_factory=adapter, max_model_calls=3,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
    )
    assert result.status != "terminal"
    receipt = adapter.patch_attempt_receipt()
    assert len(client.requests) == receipt["model_call_count"] == 2
    loop = receipt["patch_agent_loop"]
    assert loop.get("tool_rounds_used", 0) == 1
    assert loop.get("total_observation_bytes", 0) > 0
    assert len(loop.get("observation_trace", [])) == 1
    assert loop["submission_trace"][-1]["diagnostics"]["failure_classification"] == "native_after_text_bom_invalid"


class _HardInvalidRecoveryClient(_InvestigatingClient):
    def complete_turn(self, request):
        response = super().complete_turn(request)
        if response.content and self.investigated_failure:
            payload = json.loads(response.content)
            payload["changes"][0]["after_text"] = "\ufeff" + payload["changes"][0]["after_text"]
            return replace(response, content=json.dumps(payload))
        return response


def test_hard_recovery_rejection_retains_both_read_segments(tmp_path):
    inputs = _inputs(tmp_path)
    client = _HardInvalidRecoveryClient()
    oracle = _BehaviorOracle(tmp_path / "observations")
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        max_total_model_turns=5, finalize_after_first_observation=False,
        require_source_inspection=False, enable_supporting_reads=True,
    )
    result = run_fresh_patch_continuation(
        _patch_request(inputs), patch_change_factory=adapter, max_model_calls=5,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
    )
    assert result.status != "terminal"
    receipt = adapter.patch_attempt_receipt()
    assert len(client.requests) == receipt["model_call_count"] == 4
    assert len(oracle.contexts) == 1
    loop = receipt["patch_agent_loop"]
    assert loop["tool_rounds_used"] == 1
    recovery = loop["recovery_revisions"][0]
    assert recovery.get("status") == "blocked"
    assert recovery["model_call_count"] == 2
    execution = recovery["execution"]
    assert execution["tool_rounds_used"] == 1
    assert execution["total_observation_bytes"] > 0
    assert len(execution["observation_trace"]) == 1
    assert execution["submission_trace"][-1]["diagnostics"]["failure_classification"] == "native_after_text_bom_invalid"


def test_model_identity_drift_is_checked_before_format_feedback_retry(tmp_path):
    inputs = _inputs(tmp_path)
    live_identity = {}

    class DriftingClient(_PatchAgentTurnClient):
        def complete_turn(self, request):
            response = super().complete_turn(request)
            if len(self.requests) == 1:
                live_identity["digest"] = "b" * 64
                return replace(response, content="{invalid_json", tool_calls=(), stop_reason="stop")
            return response

    client = DriftingClient()
    adapter = _adapter(inputs, client, None)
    live_identity.update(adapter.identity_reader(None, None))
    adapter.identity_reader = lambda *_: deepcopy(live_identity)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        max_total_model_turns=3, finalize_after_first_observation=False,
        require_source_inspection=False,
    )
    result = run_fresh_patch_continuation(
        _patch_request(inputs), patch_change_factory=adapter, max_model_calls=3,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
    )
    assert result.status != "terminal"
    assert len(client.requests) == 1
    assert result.reason == "OLLAMA_MODEL_DIGEST_DRIFT"


def test_source_drift_after_response_retains_consumed_read_before_hardstop(tmp_path):
    inputs = _inputs(tmp_path)
    source = next(inputs.workspace.rglob("*.cs"))

    class SourceDriftingClient(_PatchAgentTurnClient):
        def complete_turn(self, request):
            response = super().complete_turn(request)
            if response.content:
                source.write_bytes(source.read_bytes() + b"\n// concurrent fixture change\n")
            return response

    client = SourceDriftingClient()
    adapter = _adapter(inputs, client, None)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        max_total_model_turns=3, finalize_after_first_observation=False,
    )
    result = run_fresh_patch_continuation(
        _patch_request(inputs), patch_change_factory=adapter, max_model_calls=3,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
    )
    assert result.status != "terminal"
    receipt = adapter.patch_attempt_receipt()
    assert len(client.requests) == receipt["model_call_count"] == 2
    loop = receipt["patch_agent_loop"]
    assert loop.get("tool_rounds_used", 0) == 1
    assert loop.get("total_observation_bytes", 0) > 0
    assert len(loop.get("observation_trace", [])) == 1
