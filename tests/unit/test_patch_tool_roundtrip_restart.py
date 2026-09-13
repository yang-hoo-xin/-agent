"""Saved tool results end at next-request preflight; never return a Patch.

The child entry below is a test driver, not a product CLI or persisted Artifact
contract. All runtime admission and source-reference checks use existing owners.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from src.libs.llm.agent_turn import (
    AgentMessage, AgentResponseFormat, AgentToolDefinition, AgentToolExchange,
    AgentToolResult, AgentTurnProviderError, AgentTurnRequest, OllamaChatAgentAdapter,
    _httpx_json_body_identity,
)
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopPolicy, PlanBoundSourceInspector, estimate_patch_source_reads,
    expand_patch_source_observations, run_patch_agent_loop,
)


def restore_request(value):
    return AgentTurnRequest(**{**value,
        "messages": tuple(AgentMessage(**row) for row in value["messages"]),
        "tools": tuple(AgentToolDefinition(**row) for row in value["tools"]),
        "response_format": AgentResponseFormat(**value["response_format"]) if value["response_format"] else None,
        "tool_results": tuple(AgentToolResult(**row) for row in value["tool_results"]),
        "historical_tool_exchanges": tuple(AgentToolExchange(**{**row,
            "tool_results": tuple(AgentToolResult(**result) for result in row["tool_results"])})
            for row in value["historical_tool_exchanges"]),
    })


class AdmissionRecorder(OllamaChatAgentAdapter):
    """Observe production rendering; delegate admission without seeding state."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.previews, self.requests = [], []

    def _context_admission(self, payload):
        admission = super()._context_admission(payload)
        self.previews.append({"payload": deepcopy(payload), "admission": deepcopy(admission),
            "identity": _httpx_json_body_identity(self.base_url + "/api/chat", payload)})
        return admission

    def complete_turn(self, request):
        self.requests.append(deepcopy(request))
        return super().complete_turn(request)


def capture_next_request(*, inspector, initial_messages, final_format, first_response,
                         model, consumed_observation_bytes=0, upstream_effects=None):
    sender_entries = []

    def sentinel(url, payload, headers):
        sender_entries.append(deepcopy(payload))
        if len(sender_entries) == 1:
            return deepcopy(first_response)
        raise AgentTurnProviderError("OFFLINE_STOP_BEFORE_SECOND_SEND", diagnostic={"offline_pre_send_stop": True})

    client = AdmissionRecorder(base_url="http://127.0.0.1:11434", model=model,
        context_window=49152, max_output_tokens=4096, request_sender=sentinel)
    result = run_patch_agent_loop(client=client, initial_messages=initial_messages,
        final_response_format=final_format, source_inspector=inspector,
        consumed_observation_bytes=consumed_observation_bytes, upstream_effects=upstream_effects)
    assert len(client.requests) == len(client.previews) == len(sender_entries) == 2
    assert result.final_content is None and result.status == "blocked"
    assert result.termination["code"] == "PATCH_AGENT_PROVIDER_TURN_FAILED"
    assert client.previews[1]["admission"]["admitted"] is True
    return client.requests[1], client.previews[1], result


def inspect_wire(request, preview, inspector):
    outputs = [json.loads(row["content"]) for row in preview["payload"]["messages"] if row["role"] == "tool"]
    calls = request.provider_state["tool_calls"]
    assert len(calls) == len(request.tool_results) == len(outputs)
    assert len({row.call_id for row in request.tool_results}) == len(calls)
    for call, result, output in zip(calls, request.tool_results, outputs):
        assert call["function"]["name"] == result.name
        assert call["function"]["arguments"]["binding_id"] == output["binding_id"]
        assert result.output == output
    expanded = expand_patch_source_observations(outputs)
    assert all(row == inspector.inspect(binding_id=row["binding_id"], observation_id=row["observation_id"]).model_view()
        for row in expanded)
    return {"tool_call_count": len(calls), "tool_result_count": len(outputs),
        "binding_order": [row["binding_id"] for row in outputs],
        "parts_positions": [index for index, row in enumerate(outputs) if "excerpt_parts" in row],
        "references_checked_against_visible_wire_and_current_source": True}


def save_bundle(root, *, request, preview, plan, evidence, workspace, policy, model):
    root.mkdir(parents=True, exist_ok=False)
    # Preserve mapping insertion order as well as values for exact re-rendering.
    values = {"request": asdict(request), "preview": preview,
        "source_inputs": {"plan": plan, "evidence": evidence, "workspace": str(workspace), "policy": asdict(policy)},
        "profile": {"base_url": "http://127.0.0.1:11434", "model": model,
            "context_window": 49152, "max_output_tokens": 4096}}
    for name, value in values.items():
        (root / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def child_preflight(bundle):
    sender_entries, socket_attempts = [], []

    def no_socket(*args, **kwargs):
        socket_attempts.append(True)
        raise AssertionError("Restart preflight must never access a socket.")

    socket.socket.connect = no_socket
    socket.socket.connect_ex = no_socket

    def no_sender(*args, **kwargs):
        sender_entries.append(True)
        raise AssertionError("A new adapter must reject before sender entry.")

    request = restore_request(json.loads((bundle / "request.json").read_text(encoding="utf-8")))
    source = json.loads((bundle / "source_inputs.json").read_text(encoding="utf-8"))
    profile = json.loads((bundle / "profile.json").read_text(encoding="utf-8"))
    phase = "source_validation"
    client = None
    outcome = {"pid": os.getpid(), "new_model_responses": 0, "new_patch_created": False,
               "scope": "next_request_preflight_only_not_product_resume_or_model_success"}
    try:
        inspector = PlanBoundSourceInspector(workspace_root=source["workspace"],
            implementation_plan=source["plan"], evidence_pack=source["evidence"], policy=PatchAgentLoopPolicy(**source["policy"]))
        estimate_patch_source_reads(source_inspector=inspector, prior_request=request, binding_ids=())
        outcome["source_references_verified"] = True
        outcome["retained_budget_states"] = [deepcopy(row.content["budget_state"]) for row in request.messages
            if isinstance(row.content, dict) and row.content.get("message_type") == "patch_agent_loop_state"]
        phase = "provider_context_admission"
        client = AdmissionRecorder(**profile, request_sender=no_sender)
        client.complete_turn(request)
        raise AssertionError("No response may be fabricated after a saved tool exchange.")
    except Exception as error:
        outcome.update(phase=phase, error_type=type(error).__name__, error_code=getattr(error, "code", None),
            error_message=str(error), diagnostic=getattr(error, "diagnostic", None))
    outcome.update(sender_entries=len(sender_entries), socket_attempts=len(socket_attempts))
    if client is not None and client.previews:
        preview = client.previews[-1]
        original = json.loads((bundle / "preview.json").read_text(encoding="utf-8"))
        outcome.update(admission=preview["admission"], request_identity=preview["identity"],
            exact_second_wire_identity_preserved=preview["identity"] == original["identity"])
    return outcome


def run_child(bundle):
    completed = subprocess.run([sys.executable, "-B", "-m", __name__, "--child", str(bundle)],
        cwd=Path(__file__).parents[2], env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True, text=True, timeout=40)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.splitlines()[-1])


def synthetic_roundtrip(tmp_path, order):
    workspace = tmp_path / "source"
    workspace.mkdir()
    files = {}
    for name, count in (("Spread.cs", 179), ("Configuration.cs", 80)):
        files[name] = workspace / name
        files[name].write_bytes("".join(f"// 自有 {name} line {number:03d}\r\n" for number in range(1, count + 1)).encode())
    spans = (("Spread.cs", 115, 145), ("Configuration.cs", 50, 78),
             ("Configuration.cs", 35, 48), ("Configuration.cs", 1, 21), ("Spread.cs", 53, 60))
    bindings = [{"binding_id": f"edit_binding_{index:03d}", "canonical_target_path": name,
        "source_hash": hashlib.sha256(files[name].read_bytes()).hexdigest(),
        "target_span": {"start_line": start, "end_line": end}}
        for index, (name, start, end) in enumerate(spans, 1)]
    plan = {"binding_registry": {"edit_bindings": bindings, "supporting_bindings": []},
        "proposed_changes": [{"change_id": str(index), "edit_binding_id": binding["binding_id"]}
            for index, binding in enumerate(bindings)]}
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False,
        allow_batched_reads=True, deduplicate_source_excerpts=True, reuse_covered_source_observations=True,
        max_tool_rounds=6)
    inspector = PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan, policy=policy)
    first = {"model": "offline-restart-fixture", "done": True, "prompt_eval_count": 100,
        "eval_count": 1, "message": {"role": "assistant", "tool_calls": [{"function": {
            "name": "inspect_plan_binding_source", "arguments": {"binding_id": f"edit_binding_{index:03d}"}}}
            for index in order]}}
    from tests.unit.test_patch_agent_loop import _final_format
    request, preview, result = capture_next_request(inspector=inspector,
        initial_messages=(AgentMessage("user", "Synthetic serialization fixture.\n" + "retained-contract-context\n" * 1400),),
        final_format=_final_format(), first_response=first, model=first["model"])
    bundle = tmp_path / "saved"
    save_bundle(bundle, request=request, preview=preview, plan=plan, evidence=None,
        workspace=workspace, policy=policy, model=first["model"])
    return bundle, request, preview, inspector, result


@pytest.mark.parametrize("order", [(1, 2, 3, 4, 5), (1, 5, 2, 3, 4), (5, 1, 2, 3, 4)])
def test_reloaded_second_request_falls_back_to_conservative_admission_before_sender(tmp_path, order):
    bundle, request, preview, inspector, result = synthetic_roundtrip(tmp_path, order)
    wire = inspect_wire(request, preview, inspector)
    assert wire["tool_result_count"] == 5 and wire["parts_positions"] == ([4] if order[1] == 2 else [1])
    assert result.final_content is None
    child = run_child(bundle)
    assert child["pid"] != os.getpid()
    assert child["phase"] == "provider_context_admission" and child["error_type"] == "AgentTurnProviderError"
    assert child["admission"]["mode"] == "provider_body_utf8_proxy_plus_output_budget_v1"
    assert child["admission"]["admitted"] is False
    assert child["admission"]["conservative_required_context"] == child["admission"]["provider_body_utf8_bytes"] + 4096 > 49152
    assert child["exact_second_wire_identity_preserved"] is True
    assert child["sender_entries"] == child["socket_attempts"] == child["new_model_responses"] == 0


@pytest.mark.parametrize("damage", ["missing_anchor", "changed_source"])
def test_reload_rejects_invalid_source_reference_before_provider_admission(tmp_path, damage):
    bundle, _request, _preview, _inspector, _result = synthetic_roundtrip(tmp_path, (1, 5, 2, 3, 4))
    if damage == "missing_anchor":
        value = json.loads((bundle / "request.json").read_text(encoding="utf-8"))
        value["tool_results"].pop(0)
        (bundle / "request.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    else:
        (tmp_path / "source" / "Spread.cs").write_bytes(b"changed source")
    child = run_child(bundle)
    assert child["phase"] == "source_validation" and child["error_type"] == "PatchAgentLoopError"
    assert child["sender_entries"] == child["socket_attempts"] == 0
    assert child["error_code"] in {"PATCH_AGENT_EXCERPT_REFERENCE_INVALID", "PATCH_AGENT_SOURCE_HASH_MISMATCH"}


if __name__ == "__main__":
    assert sys.argv[1] == "--child"
    print(json.dumps(child_preflight(Path(sys.argv[2])), ensure_ascii=False))
