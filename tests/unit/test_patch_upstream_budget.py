"""Cross-Plan budgets and interrupted stage accounting through the public CLI."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from src.libs.llm.agent_turn import AgentMessage
from src.mod_agent.local_entry import _patch_agent_context_json
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_SOURCE_INSPECTION_TOOL_NAME,
    PatchAgentLoopPolicy,
    run_patch_agent_loop,
)
from tests.unit.test_patch_agent_loop import (
    _final_format,
    _fixture,
    _response,
    _ScriptedClient,
    _tool_call,
)
from tests.unit.test_patch_repair_cli import _message_jsons, _source_hashes, _write_json
from tests.unit.test_patch_upstream_cli import _case, _install, _run, _UpstreamTransport


class _ConsumedReadTransport(_UpstreamTransport):
    def __init__(self, root, case, *, request_after_replan=False, second_patch_timeout=False):
        super().__init__(root, case, fail_first=not second_patch_timeout)
        self.request_after_replan = request_after_replan
        self.second_patch_timeout = second_patch_timeout
        self.read_requested = False
        self.read_tool = None
        self.replanned_state = None
        self.replanned_tools = None

    def __call__(self, request):
        if request.method != "POST" or request.url.path != "/api/chat":
            return super().__call__(request)
        payload = json.loads(request.content)
        values = [value for _, value in _message_jsons(payload)]
        planning = any("allowed_edit_evidence_ids" in value for value in values)
        feedback = any(value.get("message_type") == "patch_behavior_correction" for value in values)
        inspect_before_upstream = feedback and not self.upstream_sent and not self.read_requested
        second_patch = self.planning_sent and not planning
        if not (inspect_before_upstream or second_patch):
            return super().__call__(request)
        if second_patch:
            self.replanned_state = deepcopy(next(value for value in reversed(values)
                if value.get("message_type") == "patch_agent_loop_state"))
            self.replanned_tools = deepcopy(payload.get("tools", []))
            if not (self.request_after_replan or self.second_patch_timeout):
                return super().__call__(request)
        self.requests.append((request.method, str(request.url)))
        self.chat_requests.append((request.content, payload))
        self.stage_roles.append("patch")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"request-{len(self.chat_requests):03d}.json").write_bytes(request.content)
        if self.second_patch_timeout:
            raise httpx.ReadTimeout("Synthetic second Patch timeout.", request=request)
        if inspect_before_upstream:
            self.read_tool = deepcopy(next(tool["function"] for tool in payload["tools"]
                if tool["function"]["name"] == PATCH_SOURCE_INSPECTION_TOOL_NAME))
            self.read_requested = True
        binding = self.read_tool["parameters"]["properties"]["binding_id"]["enum"][0]
        return self._response(request, {"role": "assistant", "content": "", "tool_calls": [{
            "function": {"name": self.read_tool["name"], "arguments": {"binding_id": binding}},
        }]})


def _install_consumed_transport(monkeypatch, tmp_path, case, **kwargs):
    handler = _ConsumedReadTransport(tmp_path / "wire", case, **kwargs)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))

    def forbid(*_args, **_kwargs):
        raise AssertionError("Offline budget verification must not open a real connection.")

    monkeypatch.setattr("socket.socket.connect", forbid)
    monkeypatch.setattr("socket.socket.connect_ex", forbid)
    return handler


@pytest.mark.parametrize("request_after_replan", [False, True], ids=["direct-generation", "reject-new-read"])
def test_new_plan_keeps_exhausted_reads_and_consumed_observation_bytes(
    tmp_path, monkeypatch, capsys, request_after_replan,
):
    case = _case(tmp_path, monkeypatch)
    case.config["policy"]["max_tool_rounds"] = 1
    _write_json(case.config_path, case.config)
    before = _source_hashes(case.inputs.workspace)
    handler = _install_consumed_transport(monkeypatch, tmp_path, case,
        request_after_replan=request_after_replan)
    code, result = _run(case, capsys)
    assert handler.stage_roles == ["patch", "patch", "patch", "planning", "patch"], result
    journal = json.loads(Path(result["attempt_receipt"]["path"]).read_text())
    first, second = journal["patch_execution_segments"]
    old_loop = first["factory_receipt"]["patch_agent_loop"]
    recovery = old_loop["behavior_correction"]["execution"]
    assert old_loop["tool_rounds_used"] == 0 and recovery["tool_rounds_used"] == 1
    assert len(recovery["observation_trace"]) == 1
    assert recovery["observation_trace"][0]["admitted_to_model"] is True
    new_loop = second["factory_receipt"]["patch_agent_loop"]
    assert new_loop["policy"]["max_tool_rounds"] == 0
    assert new_loop["tool_rounds_used"] == 0
    # Independently count complete newly-added Ck/Fk messages from the wire,
    # including the assistant code and the user envelope, not only Fk's body.
    added_by_type = {}
    for _, payload in handler.chat_requests:
        for position, message in enumerate(payload["messages"]):
            try:
                value = json.loads(message.get("content") or "null")
            except (ValueError, TypeError):
                continue
            if not isinstance(value, dict):
                continue
            kind = value.get("message_type")
            if kind not in {"patch_repair_context", "patch_behavior_correction"} or kind in added_by_type:
                continue
            additions = []
            if "previous_response_ref" not in value:
                previous = payload["messages"][position - 1]
                assert previous["role"] == "assistant"
                additions.append({"role": "assistant", "content": previous["content"]})
            additions.append({"role": message["role"], "content": value})
            added_by_type[kind] = additions
    assert set(added_by_type) == {"patch_repair_context", "patch_behavior_correction"}
    feedback_bytes = sum(len(_patch_agent_context_json(value).encode("utf-8"))
        for value in added_by_type.values())
    assert old_loop["recovery_observation_bytes"] == feedback_bytes
    source_bytes = old_loop["total_observation_bytes"] + recovery["total_observation_bytes"]
    expected_bytes = case.config["policy"]["max_observation_bytes"] - source_bytes - feedback_bytes
    assert new_loop["policy"]["max_observation_bytes"] == expected_bytes
    assert journal["shared_observation_budget"] == {
        "maximum_reads": 1, "consumed_reads": 1, "remaining_reads": 0,
        "maximum_bytes": case.config["policy"]["max_observation_bytes"],
        "source_bytes": source_bytes, "feedback_bytes": feedback_bytes,
        "consumed_bytes": source_bytes + feedback_bytes, "remaining_bytes": expected_bytes,
    }
    assert handler.replanned_state["budget_state"]["total_remaining_tool_rounds"] == 0
    assert not any(tool["function"]["name"] == PATCH_SOURCE_INSPECTION_TOOL_NAME
        for tool in handler.replanned_tools)
    assert result["execution_counts"]["model"] == 5
    assert result["execution_counts"]["planning"] == 1
    assert result["execution_counts"]["patch"] == 2
    if request_after_replan:
        assert code != 0 and result["patch_proposal_artifact"] is None
    else:
        assert code == 0, result
        assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert _source_hashes(case.inputs.workspace) == before


@pytest.mark.parametrize("failure", ["planning", "second_patch"])
def test_interrupted_upstream_run_keeps_previously_executed_stage_counts(
    tmp_path, monkeypatch, capsys, failure,
):
    case = _case(tmp_path, monkeypatch)
    if failure == "planning":
        handler = _install(monkeypatch, tmp_path / "wire", case, planning_timeout=True)
        stages, patch_count, calls = ["patch", "planning"], 1, 2
    else:
        handler = _install_consumed_transport(monkeypatch, tmp_path, case, second_patch_timeout=True)
        stages, patch_count, calls = ["patch", "planning", "patch"], 2, 3
    code, result = _run(case, capsys)
    assert code != 0 and handler.stage_roles == stages, result
    assert result["execution_counts"]["model"] == calls
    assert result["execution_counts"]["planning"] == 1
    assert result["execution_counts"]["patch"] == patch_count
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 0
    assert result["patch_proposal_artifact"] is None
    journal = json.loads(Path(result["attempt_receipt"]["path"]).read_text())
    assert journal["shared_model_budget"]["consumed"] == calls
    assert sum(journal["shared_model_budget"]["by_role"].values()) == calls


@pytest.mark.parametrize("request_read", [False, True], ids=["finish", "no-new-read"])
def test_zero_read_and_observation_allowance_can_finish_without_inspection(tmp_path, request_read):
    policy = PatchAgentLoopPolicy(max_tool_rounds=0, max_observation_bytes=0,
        require_source_inspection=False, finalize_after_first_observation=False)
    _, source, _, inspector = _fixture(tmp_path, policy=policy)
    before = source.read_bytes()
    reply = (_response(turn=1, tool_calls=(_tool_call("edit_binding_001", turn=1),))
        if request_read else _response(turn=1, content='{"changes":[]}'))
    client = _ScriptedClient([reply])
    result = run_patch_agent_loop(client=client,
        initial_messages=(AgentMessage(role="user", content="Synthetic zero-allowance loop check."),),
        final_response_format=_final_format(), source_inspector=inspector, policy=policy)
    assert len(client.requests) == 1 and client.requests[0].tools == ()
    assert result.completed is (not request_read)
    assert result.tool_rounds_used == result.total_observation_bytes == 0
    assert result.observation_trace == ()
    assert source.read_bytes() == before
