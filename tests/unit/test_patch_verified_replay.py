"""Portable, no-network qualification of an exact paid tool-selection prefix."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.libs.llm import AgentMessage, AgentToolDefinition, AgentTurnRequest, OllamaChatAgentAdapter
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.fresh_planning_continuation import (
    _csharp_source_snapshot,
    _source_tree_snapshot_sha256,
)
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalEntryError,
    LocalOllamaInitialPatchAdapter,
    LocalOllamaInitialPatchProfileV1,
)
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy


def _ref(path: Path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _json_file(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return _ref(path)


def _request():
    return AgentTurnRequest(
        messages=(AgentMessage(role="user", content="Read the registered source before deciding."),),
        tools=(AgentToolDefinition(name="inspect_plan_binding_source", description="Read exact registered source.",
            parameters={"type": "object", "properties": {"binding_id": {"type": "string"}},
                "required": ["binding_id"], "additionalProperties": False}),),
        tool_choice="auto", temperature=0.0,
    )


def _case(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "Sample.cs"
    source.write_text("class Sample { static int Read() => 1; }\n", encoding="utf-8")
    store = ArtifactStore(tmp_path / "store")
    policy = PatchAgentLoopPolicy(max_total_model_turns=4)
    profile = LocalOllamaInitialPatchProfileV1(
        profile_version=LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        base_url="http://127.0.0.1:11434", model="qwen3:4b-instruct",
        context_window=8192, output_budget=1024, timeout_seconds=30.0,
    )
    identity = {"name": profile.model, "model": profile.model, "digest": "a" * 64,
        "modified_at": "2026-09-04T00:00:00Z", "size": 1,
        "details": {"context_length": 8192}, "capabilities": ["completion", "tools"],
        "base_url": profile.base_url}
    state = {"artifact_hashes": {name: str(index) * 64 for index, name in enumerate(
        ("feature_spec", "evidence_pack", "implementation_plan"), start=1)}}
    raw = {"model": profile.model, "done": True, "done_reason": "stop",
        "prompt_eval_count": 20, "eval_count": 5,
        "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "inspect_plan_binding_source", "arguments": {"binding_id": "edit_binding_001"}}}]}}
    request_refs, response_refs, payloads, responses = [], [], [], []
    original = tmp_path / "retained"

    def capture(url, payload, headers):
        del headers
        payloads.append(deepcopy(payload))
        path = original / f"wire-{len(payloads)}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(httpx.Request("POST", url, json=payload).content)
        request_refs.append(_ref(path))
        return deepcopy(raw)

    old_client = OllamaChatAgentAdapter(base_url=profile.base_url, model=profile.model,
        max_output_tokens=profile.output_budget, context_window=profile.context_window,
        request_sender=capture)
    for index in range(2):
        response = old_client.complete_turn(_request())
        responses.append(asdict(response))
        response_refs.append(_json_file(original / f"response-{index}.json", asdict(response)))
    document = {
        "proposal_admitted": False,
        "generated_against_snapshot_sha256": _source_tree_snapshot_sha256(_csharp_source_snapshot(workspace)),
        "selected_artifacts": {key: {"artifact_hash": value} for key, value in state["artifact_hashes"].items()},
        "factory_receipt": {"profile": profile.to_dict(), "model_identity": identity,
            "patch_agent_loop": {"policy": asdict(policy), "tool_rounds_used": 0},
            "model_call_count": 2,
            "worker_turns": [{"status": "responded", "response_origin": "live_provider_response", "response_ref": ref}
                for ref in response_refs]},
    }
    attempt_path = original / "attempt.json"
    attempt_ref = _json_file(attempt_path, document)
    adapter = LocalOllamaInitialPatchAdapter(profile=profile, artifact_store=store,
        workspace_root=workspace, patch_agent_loop_policy=policy, enable_recovery_loop=True,
        replay_attempt_ref=attempt_ref, replay_request_refs=tuple(request_refs))
    adapter.bind_attempt_recorder(lambda _event: None)
    return SimpleNamespace(adapter=adapter, identity=identity, state=state, source=source,
        document=document, attempt_path=attempt_path, request_refs=request_refs,
        response_refs=response_refs, responses=responses, payloads=payloads, raw=raw,
        store=store, profile=profile)


def _rewrite_attempt(case):
    case.adapter._replay_attempt_ref = _json_file(case.attempt_path, case.document)


def _prepare(case):
    case.adapter._prepare_verified_tool_replay(case.state, case.identity)


def _client(case, sends):
    def send(url, payload, headers):
        sends.append((url, deepcopy(payload), headers))
        return deepcopy(case.raw)
    return OllamaChatAgentAdapter(base_url=case.profile.base_url, model=case.profile.model,
        max_output_tokens=case.profile.output_budget, context_window=case.profile.context_window,
        request_sender=send)


@pytest.mark.parametrize("mutation", ["attempt_hash", "response_hash", "wire_hash", "source", "profile", "digest", "upstream", "tool_executed", "budget", "missing_turn"])
def test_verified_prefix_rejects_changed_identity_before_network(tmp_path, mutation):
    case = _case(tmp_path)
    if mutation == "attempt_hash":
        case.adapter._replay_attempt_ref["sha256"] = "0" * 64
    elif mutation == "response_hash":
        case.document["factory_receipt"]["worker_turns"][0]["response_ref"]["sha256"] = "0" * 64
        _rewrite_attempt(case)
    elif mutation == "wire_hash":
        case.adapter._replay_request_refs[0]["sha256"] = "0" * 64
    elif mutation == "source":
        case.source.write_text("class Sample { static int Read() => 2; }\n")
    elif mutation == "profile":
        case.document["factory_receipt"]["profile"]["output_budget"] += 1
        _rewrite_attempt(case)
    elif mutation == "digest":
        case.identity = {**case.identity, "digest": "b" * 64}
    elif mutation == "upstream":
        case.state["artifact_hashes"]["implementation_plan"] = "0" * 64
    elif mutation == "tool_executed":
        case.document["factory_receipt"]["patch_agent_loop"]["tool_rounds_used"] = 1
        _rewrite_attempt(case)
    elif mutation == "budget":
        case.document["factory_receipt"]["model_call_count"] = 4
        _rewrite_attempt(case)
    else:
        case.document["factory_receipt"]["worker_turns"].pop()
        _rewrite_attempt(case)
    with pytest.raises(LocalEntryError):
        _prepare(case)
    assert case.adapter._replay_prefix == []


@pytest.mark.parametrize("mutation", ["content", "tool_name", "raw_content", "raw_tool_name", "raw_arguments"])
def test_prefix_must_be_only_the_original_source_tool_selection(tmp_path, mutation):
    case = _case(tmp_path)
    retained = deepcopy(case.responses[0])
    if mutation == "content":
        retained["content"] = '{"changes":[{"after_text":"unadmitted generated code"}]}'
    elif mutation == "tool_name":
        retained["tool_calls"][0]["name"] = "write_file"
    elif mutation == "raw_content":
        retained["raw_response"]["message"]["content"] = '{"changes":[]}'
    elif mutation == "raw_tool_name":
        retained["raw_response"]["message"]["tool_calls"][0]["function"]["name"] = "write_file"
    else:
        retained["raw_response"]["message"]["tool_calls"][0]["function"]["arguments"] = {"binding_id": "different_binding"}
    new_ref = _json_file(Path(case.response_refs[0]["path"]), retained)
    case.document["factory_receipt"]["worker_turns"][0]["response_ref"] = new_ref
    _rewrite_attempt(case)
    with pytest.raises(LocalEntryError):
        _prepare(case)


@pytest.mark.parametrize("mutation", ["text", "temperature", "json_type", "model", "tool_schema", "output_budget"])
def test_every_changed_request_value_is_rejected_without_sending(tmp_path, mutation):
    case = _case(tmp_path)
    _prepare(case)
    sends = []
    client = _client(case, sends)
    case.adapter._install_verified_tool_replay(client)
    payload = deepcopy(case.payloads[0])
    if mutation == "text":
        payload["messages"][0]["content"] += " "
    elif mutation == "temperature":
        payload["options"]["temperature"] = 0.5
    elif mutation == "json_type":
        payload["options"]["temperature"] = False  # False == 0.0 in Python, distinct provider JSON.
    elif mutation == "model":
        payload["model"] = "another-model"
    elif mutation == "tool_schema":
        payload["tools"][0]["function"]["description"] += " changed"
    else:
        payload["options"]["num_predict"] += 1
    with pytest.raises(LocalEntryError, match="PATCH_REPLAY_REQUEST_CHANGED"):
        client._send(case.profile.base_url + "/api/chat", payload, {})
    assert sends == [] and case.adapter._replayed_turn_count == 0


def test_json_key_order_change_keeps_all_values_and_uses_original_response(tmp_path):
    case = _case(tmp_path)
    _prepare(case)
    sends = []
    client = _client(case, sends)
    case.adapter._install_verified_tool_replay(client)
    payload = dict(reversed(list(case.payloads[0].items())))
    payload["options"] = dict(reversed(list(payload["options"].items())))
    result = client._send(case.profile.base_url + "/api/chat", payload, {})
    assert result == case.raw and sends == []
    match = case.adapter.patch_attempt_receipt()["replay_request_matches"][0]
    assert match["exact_wire_bytes_match"] is False
    assert match["all_json_values_and_text_exact"] is True


def test_replay_retains_original_file_and_consumes_shared_budget(tmp_path):
    case = _case(tmp_path)
    original_bytes = {ref["path"]: Path(ref["path"]).read_bytes()
        for ref in (*case.response_refs, *case.request_refs, _ref(case.attempt_path))}
    _prepare(case)
    sends = []
    client = _client(case, sends)
    case.adapter._install_verified_tool_replay(client)
    recorded = case.adapter._recording_agent_client(client, "synthetic_verified_replay")
    for _ in range(2):
        response = recorded.complete_turn(_request())
        assert response.tool_calls and response.content is None
    receipt = case.adapter.patch_attempt_receipt()
    assert sends == []
    assert receipt["model_call_count"] == 2
    assert receipt["verified_replay"]["maximum_new_model_calls"] == 2
    assert receipt["replayed_model_turns"] == 2 and receipt["live_response_count"] == 0
    assert [turn["response_ref"] for turn in receipt["worker_turns"]] == case.response_refs
    assert all(turn["response_origin"] == "verified_prior_response" for turn in receipt["worker_turns"])
    assert not list(case.store.root.rglob("*.json"))
    for path, original in original_bytes.items():
        assert Path(path).read_bytes() == original
    for _ in range(2):
        recorded.complete_turn(replace(_request(), messages=(AgentMessage(role="user", content="Read another allowed source."),)))
    assert len(sends) == 2
    assert case.adapter.patch_attempt_receipt()["model_call_count"] == 4
    with pytest.raises(LocalEntryError, match="PATCH_AGENT_CORRECTION_BUDGET_EXHAUSTED"):
        recorded.complete_turn(_request())
    assert len(sends) == 2
