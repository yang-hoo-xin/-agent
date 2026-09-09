"""Offline acceptance of successive bound behavior repairs in one worker budget."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.libs.llm import AgentToolCall
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _patch_request,
    _PatchAgentTurnClient,
    _source_hashes,
)
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Continuous repair tests must not access a network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


class _SequenceClient(_PatchAgentTurnClient):
    def __init__(self, actions):
        super().__init__()
        self.actions = actions
        self.outputs = []
        self.reads = []

    def complete_turn(self, request):
        self.requests.append(request)
        action = self.actions[len(self.requests) - 1]
        builder = _PatchAgentTurnClient()
        builder.requests = [None]  # Reuse only its synthetic complete-output builder.
        response = builder.complete_turn(request)
        if action in ("read", "upstream"):
            name = "inspect_plan_binding_source" if action == "read" else "request_patch_upstream"
            if action == "read":
                tool = next(tool for tool in request.tools if tool.name == name)
                selected = next(binding for binding in tool.parameters["properties"]["binding_id"]["enum"]
                                if binding not in self.reads)
                self.reads.append(selected)
                arguments = {"binding_id": selected}
            else:
                arguments = {"required_owner": "evidence", "reason": "A bound failure needs additional evidence.",
                             "source_refs": ["binding://edit_binding_001"]}
            return replace(response, content=None, stop_reason="tool_calls", tool_calls=(AgentToolCall(
                call_id=f"repair-read-{len(self.requests)}", name=name, arguments=arguments,
            ),), provider_state={"content": None, "tool_calls": [{"function": {
                "name": name, "arguments": arguments,
            }}]})
        content = response.content.replace("RecordRuntimeMarker", action)
        self.outputs.append(content)
        return replace(response, content=content)


def _run(tmp_path, actions, *, budget=5, observation_budget=32768, oracle_options=None, preparation=None):
    inputs, request = preparation if preparation is not None else (None, None)
    inputs = inputs or _inputs(tmp_path)
    request = request or _patch_request(inputs)
    source_before = _source_hashes(inputs.workspace)
    client = _SequenceClient(actions)
    oracle = _BehaviorOracle(tmp_path / "observations", **(oracle_options or {}))
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        max_total_model_turns=budget, max_tool_rounds=6, max_observation_bytes=observation_budget,
        require_source_inspection=False,
        finalize_after_first_observation=False, enable_supporting_reads=True,
        allow_upstream_request=True,
    )
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=budget)
    assert _source_hashes(inputs.workspace) == source_before
    return result, adapter, client, oracle


def test_third_code_repairs_second_failure_with_exact_version_feedback(tmp_path):
    result, adapter, client, oracle = _run(tmp_path,
        ["RecordFirstFailure", "RecordSecondFailure", "RecordRuntimeMarker"], budget=3)
    assert result.status == "terminal", result.to_dict()
    receipt = adapter.patch_attempt_receipt()
    loop = receipt["patch_agent_loop"]
    assert len(client.requests) == receipt["model_call_count"] == 3
    assert [report["status"] for report in oracle.reports] == ["behavior_failed", "behavior_failed", "passed"]
    history = loop["recovery_revisions"]
    assert [row["revision_index"] for row in history] == [1, 2]
    assert loop["behavior_correction"] == history[-1]
    assert sum(row["model_call_count"] for row in history) + loop["model_turns_used"] == 3
    assert len({row["response"]["path"] for row in history}) == 2
    for index, revision in enumerate(history):
        assert revision["previous_response_sha256"] == oracle.contexts[index]["model_response"]["output_sha256"]
        assert revision["validator"]["report_sha256"] == oracle.reports[index]["report_ref"]["sha256"]
        assert revision["validator"]["generated_changes_sha256"] == oracle.contexts[index]["generated_changes_sha256"]
        assert hashlib.sha256(Path(revision["response"]["path"]).read_bytes()).hexdigest() == revision["response"]["output_sha256"]
    final = client.requests[-1]
    assert all(any(m.role == "assistant" and m.content == content for m in final.messages) for content in client.outputs[:2])
    feedback = [m.content["validator_feedback"] for m in final.messages if isinstance(m.content, dict)
                and m.content.get("message_type") == "patch_behavior_correction"]
    assert [row["report_sha256"] for row in feedback] == [row["report_ref"]["sha256"] for row in oracle.reports[:2]]
    for index, row in enumerate(feedback):
        view = row["working_code_view"]
        assert view["code_sha256"] == oracle.contexts[index]["materialized_code_identity"]["code_sha256"]
        assert view["source_role"] == "current_verified_materialization_not_live_baseline"
        assert row["working_code_view_provenance"]["covered_by_verifier_report_ref"] is False
        current = "".join(hunk["text"] for file in view["files"] for hunk in file["hunks"])
        assert ("RecordFirstFailure" if index == 0 else "RecordSecondFailure") in current
        persisted = json.loads(Path(oracle.reports[index]["report_ref"]["path"]).read_text(encoding="utf-8"))
        assert "working_code_view" not in persisted
    assert loop["recovery_observation_bytes"] == sum(row["feedback_budget"]["feedback_utf8_bytes"] for row in history)
    assert all(row["feedback_budget"]["feedback_utf8_bytes"] > len(json.dumps(row["validator"]).encode())
               for row in history), "Count the added Ck and role/content envelope, not only feedback."
    assert len({row["materialized_code_identity"]["code_sha256"] for row in loop["behavior_evaluations"]}) == 3
    assert result.execution_counts["review"] == result.execution_counts["dry_run"] == 1
    assert all(result.execution_counts[key] == 0 for key in ("apply", "build", "runtime"))


def test_two_revision_reads_retain_history_and_accumulate_only_once(tmp_path):
    result, adapter, client, oracle = _run(tmp_path,
        ["RecordFirstFailure", "read", "RecordSecondFailure", "read", "RecordRuntimeMarker"])
    assert result.status == "terminal", result.to_dict()
    receipt = adapter.patch_attempt_receipt()
    loop = receipt["patch_agent_loop"]
    history = loop["recovery_revisions"]
    assert len(client.requests) == receipt["model_call_count"] == 5
    assert [row["model_call_count"] for row in history] == [2, 2]
    assert [row["execution"]["tool_rounds_used"] for row in history] == [1, 1]
    assert adapter._recovery_observation_usage() == (
        2, sum(row["execution"]["total_observation_bytes"] for row in history))
    assert history[1]["source_observation_sha256s"] == [
        row["observation_sha256"] for row in history[0]["execution"]["observation_trace"]]
    final = client.requests[-1]
    exchanges = [*final.historical_tool_exchanges]
    assert sum(len(exchange.tool_results) for exchange in exchanges) + len(final.tool_results) == 2
    assert len(oracle.contexts) == 3
    assert history[1]["feedback_budget"]["prior_feedback_utf8_bytes"] == history[0]["feedback_budget"]["feedback_utf8_bytes"]


def test_behavior_repair_stops_at_shared_model_budget(tmp_path):
    result, adapter, client, oracle = _run(tmp_path,
        ["RecordFirstFailure", "RecordSecondFailure", "RecordRuntimeMarker"], budget=2)
    assert result.status != "terminal"
    assert result.reason == "PATCH_AGENT_CORRECTION_BUDGET_EXHAUSTED"
    assert len(client.requests) == adapter.patch_attempt_receipt()["model_call_count"] == 2
    assert len(oracle.reports) == 2 and oracle.reports[-1]["status"] == "behavior_failed"


def test_feedback_view_exceeding_byte_budget_stops_without_spending_it(tmp_path):
    result, adapter, client, _ = _run(tmp_path, ["RecordFirstFailure"], observation_budget=2048)
    assert result.reason == "PATCH_BEHAVIOR_OBSERVATION_BUDGET_EXHAUSTED"
    loop = adapter.patch_attempt_receipt()["patch_agent_loop"]
    budget = loop["behavior_feedback_budget"]
    assert budget["admitted"] is False and budget["combined_utf8_bytes"] > budget["limit"]
    assert len(client.requests) == 1 and loop["recovery_observation_bytes"] == 0
    assert loop["recovery_revisions"] == []


def test_initial_repair_context_renders_the_exact_failed_materialization(tmp_path):
    from tests.unit.test_patch_repair_continuation import _repair_case

    inputs, request, _ = _repair_case(tmp_path / "parent")
    result, adapter, client, _ = _run(tmp_path, ["RecordRuntimeMarker"], preparation=(inputs, request))
    assert result.status == "terminal", result.to_dict()
    context = next(m.content for m in client.requests[0].messages if isinstance(m.content, dict)
                   and m.content.get("message_type") == "patch_repair_context")
    view = context["validator_feedback"]["working_code_view"]
    assert view["code_sha256"] == adapter._known_failed_code["code_sha256"]
    assert all(file["complete"] for file in view["files"])
    assert adapter.patch_attempt_receipt()["patch_agent_loop"]["recovery_observation_bytes"] > len(
        json.dumps(context["validator_feedback"]).encode())


def test_one_unchanged_revision_can_be_followed_by_a_real_repair(tmp_path):
    result, adapter, client, _ = _run(tmp_path,
        ["RecordFirstFailure", "RecordFirstFailure", "RecordRuntimeMarker"])
    assert result.status == "terminal", result.to_dict()
    assert len(client.requests) == 3
    evaluations = adapter.patch_attempt_receipt()["patch_agent_loop"]["behavior_evaluations"]
    assert evaluations[1]["code_revision"]["same_materialized_code"] is True
    assert evaluations[2]["code_revision"]["same_materialized_code"] is False


def test_repeated_same_code_and_failure_stops_with_unused_budget(tmp_path):
    result, adapter, client, _ = _run(tmp_path, ["RecordFirstFailure"] * 5)
    assert result.status != "terminal" and result.reason == "PATCH_BEHAVIOR_NO_PROGRESS"
    assert len(client.requests) == adapter.patch_attempt_receipt()["model_call_count"] == 3
    stop = adapter.patch_attempt_receipt()["patch_agent_loop"]["behavior_repair_termination"]
    assert stop["remaining_model_turns"] == 2


@pytest.mark.parametrize("actions,options,expected_calls", [
    (["RecordRuntimeMarker"], {}, 1),
    (["RecordFirstFailure"], {"status": "infrastructure_failed", "owner": "environment"}, 1),
    (["RecordFirstFailure", "upstream"], {}, 2),
])
def test_pass_environment_or_upstream_does_not_force_budget_consumption(tmp_path, actions, options, expected_calls):
    result, adapter, client, _ = _run(tmp_path, actions, oracle_options=options)
    assert len(client.requests) == adapter.patch_attempt_receipt()["model_call_count"] == expected_calls
    if actions[0] == "RecordRuntimeMarker":
        assert result.status == "terminal"
    else:
        assert result.status != "terminal"
