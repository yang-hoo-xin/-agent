"""Prospective tool timings observe existing execution, without changing policy."""
import hashlib
import json

from src.core.trace.execution_trace import ExecutionTrace
from src.libs.llm.agent_turn import AgentMessage, AgentToolCall
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, run_patch_agent_loop
from tests.unit.test_patch_agent_loop import (
    _final_format,
    _fixture,
    _response,
    _run,
    _ScriptedClient,
    _tool_call,
)
from tests.unit.test_patch_source_coverage_reuse import _coverage_inspector


def _observations(trace, name):
    latest = {row["data"]["id"]: row["data"] for row in trace.context.stages}
    return [row for row in latest.values() if row["name"] == name]


class _FirstFinishedSink:
    def __init__(self):
        self.finished = {}

    def publish(self, observation):
        if observation["finished_at"] is not None:
            self.finished.setdefault(observation["id"], observation)


def test_actual_read_and_submission_have_live_timing_and_returned_payload_identity(tmp_path):
    _, _, _, inspector = _fixture(tmp_path)
    client = _ScriptedClient([_response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),)),
                              _response(turn=2, content='{"changes":[]}')])
    sink = _FirstFinishedSink()
    trace = ExecutionTrace("trace", "session", "offline", sink=sink)
    with trace.activate():
        result = _run(client, inspector)
    assert result.completed and result.tool_rounds_used == 1
    reads = _observations(trace, "source.inspect")
    assert len(reads) == 1 and reads[0]["status"] == "completed"
    attrs = reads[0]["attributes"]
    returned = client.requests[1].tool_results[0].output
    encoded = json.dumps(returned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert attrs["encoded_payload_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert attrs["encoded_payload_bytes"] == len(encoded) and attrs["read_cost"] == 1
    assert attrs["tool_call_id"] == "call-001" and attrs["turn_index"] == 1
    assert attrs["observation_queued"] is True and attrs["model_consumption_proven"] is False
    assert sink.finished[reads[0]["id"]]["attributes"] == attrs
    assert "line 040" not in json.dumps(trace.context.to_dict())
    submission = _observations(trace, "patch.submission")[0]
    assert submission["attributes"]["submission_admitted"] is True
    assert submission["attributes"]["behavior_validation_performed"] is False
    assert reads[0]["finished_at"] and reads[0]["elapsed_ms"] >= 0


def test_budget_rejection_records_preparation_and_admission_but_no_source_dispatch(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    client = _ScriptedClient([_response(turn=1, tool_calls=(
        _tool_call("edit_binding_001", turn=1), _tool_call("edit_binding_002", turn=2))),
        _response(turn=2, content='{"changes":[]}')])
    trace = ExecutionTrace("trace", "session", "offline")
    with trace.activate():
        result = run_patch_agent_loop(client=client, initial_messages=(AgentMessage("user", "Test"),),
            final_response_format=_final_format(), source_inspector=inspector, reserve_tool_reads=5)
    assert result.completed and result.tool_rounds_used == 0
    assert not _observations(trace, "source.inspect")
    prepared = _observations(trace, "source.prepare")
    assert len(prepared) == 1 and prepared[0]["attributes"]["preparation_only"] is True
    assert prepared[0]["attributes"]["tool_dispatch_performed"] is False
    decisions = _observations(trace, "tool.admission")
    assert len(decisions) == 2
    assert all(row["attributes"]["admission_result"] == "rejected_not_executed" for row in decisions)
    assert all(row["attributes"]["dispatch_started"] is False for row in decisions)


def test_visible_source_reuse_has_zero_read_cost_and_separate_tool_call_identity(tmp_path):
    inspector = _coverage_inspector(tmp_path)
    client = _ScriptedClient([
        _response(turn=1, tool_calls=(_tool_call("edit_binding_002", turn=1),)),
        _response(turn=2, tool_calls=(_tool_call("edit_binding_003", turn=2),)),
        _response(turn=3, content='{"changes":[]}')])
    sink = _FirstFinishedSink()
    trace = ExecutionTrace("trace", "session", "offline", sink=sink)
    with trace.activate():
        result = _run(client, inspector)
    reads = _observations(trace, "source.inspect")
    assert len(reads) == 2 and result.tool_rounds_used == 1
    assert [row["attributes"]["read_cost"] for row in reads] == [1, 0]
    assert [row["attributes"]["reused"] for row in reads] == [False, True]
    assert {row["attributes"]["tool_call_id"] for row in reads} == {"call-001", "call-002"}
    assert all(row["attributes"]["prepared_before_dispatch"] is True for row in reads)
    assert all(sink.finished[row["id"]]["attributes"] == row["attributes"] for row in reads)


def test_upstream_trace_marks_registration_without_claiming_upstream_execution(tmp_path):
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(
        require_source_inspection=False, allow_upstream_request=True))
    client = _ScriptedClient([_response(turn=1, tool_calls=(AgentToolCall(call_id="upstream-1",
        name="request_patch_upstream", arguments={"required_owner": "planning", "reason": "Need a reviewed scope change.",
        "source_refs": ["binding://edit_binding_001"]}),))])
    trace = ExecutionTrace("trace", "session", "offline")
    with trace.activate():
        result = _run(client, inspector)
    assert result.termination["code"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    request = _observations(trace, "patch.upstream_request")[0]
    assert request["attributes"]["request_registered"] is True
    assert request["attributes"]["upstream_execution_performed"] is False
    assert not _observations(trace, "source.inspect")


def test_format_failure_and_correction_keep_shared_budget_and_original_response(tmp_path):
    _, _, _, inspector = _fixture(tmp_path, policy=PatchAgentLoopPolicy(require_source_inspection=False,
        finalize_after_first_observation=False))
    raw = 'Explanation before JSON. {"changes":[]}'
    client = _ScriptedClient([_response(turn=1, content=raw), _response(turn=2, content='{"changes":[]}')])
    trace = ExecutionTrace("trace", "session", "offline")
    with trace.activate():
        result = _run(client, inspector)
    assert result.completed and result.model_turns_used == len(client.requests) == 2
    submissions = _observations(trace, "patch.submission")
    assert [row["status"] for row in submissions] == ["failed", "completed"]
    assert submissions[0]["attributes"]["exception_type"] == "PatchGenerationError"
    assert submissions[0]["attributes"]["response_content_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in json.dumps(trace.context.to_dict())
    assert any(message.role == "assistant" and message.content == raw for message in client.requests[1].messages)
