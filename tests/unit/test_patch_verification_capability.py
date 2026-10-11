"""Actual native Patch input describes only the evaluator the host assembled."""
from __future__ import annotations

import json

import pytest

from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _patch_request,
    _PatchAgentTurnClient,
    _source_hashes,
)
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorClient, _BehaviorOracle


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Capability wiring tests must not invoke a model or network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


class _PreparedOracle(_BehaviorOracle):
    def __init__(self, root, *, unavailable=False):
        super().__init__(root)
        self.prepared = False
        self.unavailable = unavailable

    def prepare_for_patch_attempt(self):
        if self.unavailable:
            raise RuntimeError("Controlled evaluator preparation failure")
        self.prepared = True


def _run(inputs, client, evaluator, *, recovery=False):
    request = _patch_request(inputs)
    adapter = _adapter(inputs, client, evaluator)
    adapter.enable_recovery_loop = recovery
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
        max_model_calls=adapter.patch_agent_loop_policy.max_total_model_turns)
    return result


@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("recovery", [False, True])
def test_loaded_evaluator_capability_reaches_actual_native_input(tmp_path, available, recovery):
    inputs = _inputs(tmp_path)
    original = _source_hashes(inputs.workspace)
    client = _PatchAgentTurnClient()
    evaluator = _PreparedOracle(tmp_path / "checks") if available else None
    complete = client.complete_turn

    def observed(request):
        assert evaluator is None or evaluator.prepared
        return complete(request)

    client.complete_turn = observed
    result = _run(inputs, client, evaluator, recovery=recovery)
    assert result.status == "terminal"
    payload = json.loads(client.requests[0].messages[1].content)
    assert ("candidate_verification" in payload) is available
    assert all(tool.name != "submit_candidate" for request in client.requests for tool in request.tools)
    assert payload["acceptance_criteria"] == inputs.feature_payload["acceptance_criteria"]
    assert _source_hashes(inputs.workspace) == original
    if evaluator is not None:
        capability = payload["candidate_verification"]
        assert capability["action"] == "submit_candidate"
        assert capability["mechanism"] == "normal_final_patch_response"
        assert capability["automatic_evaluation"]["configured"] is True
        assert capability["automatic_evaluation"]["trigger"] == "after_normal_patch_submission_checks"
        assert capability["automatic_evaluation"]["outcome"] == "not_established_by_this_capability"
        assert capability["feedback"]["mode"] == (
            "existing_recovery_loop" if recovery else "single_behavior_correction")
        assert capability["feedback"]["budget"] == "remaining_model_and_observation_budget"
        assert len(evaluator.contexts) == 1 and evaluator.reports[0]["status"] == "passed"
        assert not any(key in json.dumps(capability) for key in ("factory_ref", "check_ids", "expected_values"))


def test_failed_evaluator_preparation_cannot_advertise_or_call_model(tmp_path):
    inputs = _inputs(tmp_path)
    client = _PatchAgentTurnClient()
    evaluator = _PreparedOracle(tmp_path / "checks", unavailable=True)
    result = _run(inputs, client, evaluator)
    assert result.status != "terminal" and not client.requests and not evaluator.contexts
    assert result.patch_proposal_artifact is None


def test_submission_uses_existing_bounded_feedback_and_preserves_capability(tmp_path):
    inputs = _inputs(tmp_path)
    client = _BehaviorClient()
    evaluator = _PreparedOracle(tmp_path / "checks")
    result = _run(inputs, client, evaluator)
    assert result.status == "terminal"
    assert len(client.requests) == 3 and len(evaluator.contexts) == 2
    assert [report["status"] for report in evaluator.reports] == ["behavior_failed", "passed"]
    first = json.loads(client.requests[0].messages[1].content)["candidate_verification"]
    assert json.loads(client.requests[-1].messages[1].content)["candidate_verification"] == first
    assert client.requests[-1].messages[-1].content["message_type"] == "patch_behavior_correction"
