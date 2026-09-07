"""Registered API provenance survives the production model wire serializer."""

from __future__ import annotations

import json

import httpx
import pytest

from src.libs.llm.agent_turn import AgentMessage, OllamaChatAgentAdapter
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopError,
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    run_patch_agent_loop,
)
from tests.unit.test_patch_agent_loop import _final_format, _fixture


def _inspector(tmp_path, metadata):
    workspace, _, plan, baseline = _fixture(tmp_path)
    item = {
        "evidence_id": "api-source", "source_type": "decompiled_api",
        "source_path": "Dependency.dll", "source_hash": "A1" * 32,
        "span": None, "symbol": "Dependency.Read",
        "excerpt": "Registered method metadata and saved wrapper body; not runtime proof.",
        **metadata,
    }
    plan["binding_registry"]["supporting_bindings"] = [{
        "binding_id": "api-read", "evidence_id": item["evidence_id"],
        "source_type": item["source_type"], "source_path": item["source_path"],
        "target_span": None, "target_symbol": item["symbol"],
    }]
    inspector = PlanBoundSourceInspector(
        workspace_root=workspace, implementation_plan=plan,
        evidence_pack={"items": [item]}, policy=PatchAgentLoopPolicy(enable_supporting_reads=True),
    )
    return inspector, baseline, item


@pytest.mark.parametrize("authority,origin", [
    ("authoritative", "source://current-interop/Dependency.dll"),
    ("reference", "source://prior-release/Dependency.dll"),
])
def test_api_origin_reaches_exact_http_body_without_becoming_write_authority(
    tmp_path, monkeypatch, authority, origin,
):
    notes = ["Saved metadata was not live-revalidated.", "Wrapper IL does not prove game behavior."]
    inspector, baseline, item = _inspector(tmp_path, {
        "source_authority": authority, "source_ref": origin, "risk_notes": notes,
    })
    # The inspector owns an immutable admitted copy, including provenance.
    item["source_ref"] = "source://caller-mutation/other.dll"
    notes.append("caller mutation")
    bodies = []

    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            message = {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "inspect_plan_binding_source", "arguments": {"binding_id": "api-read"}},
            }]}
        else:
            message = {"role": "assistant", "content": '{"changes":[]}'}
        return httpx.Response(200, json={"model": "test-wire", "message": message,
                                       "done": True, "done_reason": "stop"})

    client_type = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: client_type(transport=httpx.MockTransport(respond), **kw))
    client = OllamaChatAgentAdapter(base_url="http://127.0.0.1:11434", model="test-wire", max_output_tokens=1024)
    result = run_patch_agent_loop(
        client=client, initial_messages=(AgentMessage(role="user", content="Inspect the registered dependency."),),
        final_response_format=_final_format(), source_inspector=inspector,
    )
    assert result.completed and len(bodies) == 2
    observation = json.loads(next(m["content"] for m in bodies[1]["messages"] if m["role"] == "tool"))
    assert observation["source_authority"] == authority
    assert observation["evidence_source_ref"] == origin
    assert observation["risk_notes"] == notes[:2]
    assert observation["source_identity_status"] == "registered_not_live_revalidated"
    assert observation["source_ref"] == "binding://api-read"
    assert observation["source_hash"] == item["source_hash"]
    assert observation["excerpt"] == item["excerpt"]
    assert inspector.available_binding_ids == baseline.available_binding_ids
    assert "api-read" not in inspector.available_binding_ids


def test_legacy_api_without_optional_provenance_remains_readable_as_unknown(tmp_path):
    inspector, _, _ = _inspector(tmp_path, {})
    view = inspector.inspect(binding_id="api-read", observation_id="old-api").model_view()
    assert view["source_authority"] == "unknown"
    assert view["evidence_source_ref"] == "unknown"
    assert view["risk_notes"] is None


def test_observation_view_cannot_mutate_admitted_risk_notes(tmp_path):
    inspector, _, _ = _inspector(tmp_path, {"risk_notes": ["Not runtime proof."]})
    observation = inspector.inspect(binding_id="api-read", observation_id="api")
    view = observation.model_view()
    view["risk_notes"].append("consumer mutation")
    assert observation.model_view()["risk_notes"] == ["Not runtime proof."]


@pytest.mark.parametrize("metadata", [{"source_authority": True}, {"source_ref": []},
                                    {"risk_notes": "not a list"}, {"risk_notes": [7]}])
def test_invalid_provenance_does_not_silently_turn_into_an_authority_claim(tmp_path, metadata):
    with pytest.raises(PatchAgentLoopError, match="PATCH_AGENT_REGISTERED_API_EVIDENCE_INVALID"):
        _inspector(tmp_path, metadata)
