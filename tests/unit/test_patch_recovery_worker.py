"""Recovery uses the same worker and exposes tested code, facts and constraints."""

import json
from dataclasses import replace

from src.libs.llm import AgentToolCall, OllamaChatAgentAdapter
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


class _InvestigatingClient(_PatchAgentTurnClient):
    def __init__(self):
        super().__init__()
        self.investigated_failure = False

    def complete_turn(self, request):
        response = super().complete_turn(request)
        feedback = next((m.content for m in request.messages if isinstance(m.content, dict)
                         and m.content.get("message_type") == "patch_behavior_correction"), None)
        if feedback and not self.investigated_failure:
            self.investigated_failure = True
            assert request.tools, "Failure correction must retain legal read tools."
            source_tool = next(t for t in request.tools if t.name == "inspect_plan_binding_source")
            selected = source_tool.parameters["properties"]["binding_id"]["enum"][0]
            return replace(response, content=None, tool_calls=(AgentToolCall(
                call_id="inspect-after-failure", name="inspect_plan_binding_source",
                arguments={"binding_id": selected},
            ),), stop_reason="tool_calls", provider_state={"content": "", "tool_calls": [{
                "function": {"name": "inspect_plan_binding_source", "arguments": {"binding_id": selected}},
            }]})
        if response.content and not feedback:
            return replace(response, content=response.content.replace(
                "RecordRuntimeMarker", "RecordMissingMarker"))
        return response


def test_feedback_can_drive_new_inspection_without_losing_tested_draft_or_obligations(tmp_path):
    inputs = _inputs(tmp_path)
    before = _source_hashes(inputs.workspace)
    client = _InvestigatingClient()
    oracle = _BehaviorOracle(tmp_path / "observations")
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        finalize_after_first_observation=False, require_source_inspection=False,
        enable_supporting_reads=True,
    )
    result = run_fresh_patch_continuation(
        _patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5,
    )
    assert result.status == "terminal", result.to_dict()
    assert client.investigated_failure
    assert len(client.requests) == 4
    assert len(oracle.contexts) == 2
    assert oracle.reports[-1]["status"] == "passed"
    assert _source_hashes(inputs.workspace) == before
    final = client.requests[-1]
    feedback = next(m.content for m in final.messages if isinstance(m.content, dict)
                    and m.content.get("message_type") == "patch_behavior_correction")
    assert feedback["revision_semantics"] == "complete_replacement_relative_to_B0"
    draft = next(m.content for m in final.messages if m.role == "assistant")
    tested = json.loads(draft)["changes"]
    assert [c["after_text"] for c in tested] == [
        c["patch"]["after_text"] for c in oracle.contexts[0]["generated_changes"]]
    assert feedback["validator_feedback"]["observations"] == oracle.reports[0]["observations"]
    assert final.messages[0].content == client.requests[0].messages[0].content
    assert final.messages[1].content == client.requests[0].messages[1].content
    captured = []
    def send(_url, payload, _headers):
        captured.append(payload)
        return {"model": client.model, "message": {"content": "{}"}, "done": True}
    serializer = OllamaChatAgentAdapter(model=client.model, base_url="http://127.0.0.1:11434",
                                       max_output_tokens=64, request_sender=send)
    serializer.complete_turn(final)
    payload = captured[0]
    wire_messages = json.dumps(payload["messages"])
    assert "RecordMissingMarker" in wire_messages
    assert "complete_replacement_relative_to_B0" in wire_messages
    receipt = adapter.patch_attempt_receipt()
    correction = receipt["patch_agent_loop"]["behavior_correction"]
    assert correction["model_call_count"] == 2
    assert correction["execution"]["tool_rounds_used"] == 1
    assert receipt["model_call_count"] == 4
