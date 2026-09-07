"""Observe tool promises and actual public-CLI outcomes with synthetic HTTP only."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx

from src.mod_agent.local_entry import _restore_patch_agent_context
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_SOURCE_INSPECTION_TOOL_NAME,
    PATCH_UPSTREAM_REQUEST_TOOL_NAME,
)
from tests.unit.test_patch_repair_cli import _message_jsons, _source_hashes
from tests.unit.test_patch_upstream_cli import _case, _run, _UpstreamTransport


def _remove_upstream_configuration(case):
    index = case.argv.index("--patch-upstream-config")
    del case.argv[index:index + 2]


class _EffectsTransport(_UpstreamTransport):
    def __init__(self, root, case, *, read_then_finish=False, repeat_upstream=False):
        super().__init__(root, case)
        self.read_then_finish = read_then_finish
        self.repeat_upstream = repeat_upstream
        self.tool_views = []
        self.effect_views = []
        self.read_returned = False
        self.requested_registered_refs = []

    def _record_wire(self, request, payload, role):
        self.requests.append((request.method, str(request.url)))
        self.chat_requests.append((request.content, payload))
        self.stage_roles.append(role)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"request-{len(self.chat_requests):03d}.json").write_bytes(request.content)

    def _upstream_response(self, request, payload):
        tool = next(item["function"] for item in payload["tools"]
                    if item["function"]["name"] == PATCH_UPSTREAM_REQUEST_TOOL_NAME)
        ref = tool["parameters"]["properties"]["source_refs"]["items"]["enum"][0]
        self.requested_registered_refs.append(ref)
        return self._response(request, {"role": "assistant", "content": "", "tool_calls": [{"function": {
            "name": tool["name"], "arguments": {
                "required_owner": "evidence" if self.case.evidence else "planning",
                "reason": "The source is already registered, but preservation coverage and the semantic edit selection need reassessment.",
                "source_refs": [ref]}}}]})

    def __call__(self, request):
        if request.method != "POST" or request.url.path != "/api/chat":
            return super().__call__(request)
        payload = json.loads(request.content)
        decoded = _message_jsons(payload)
        values = [value for _, value in decoded]
        prompt = next((value for value in values if "required_change_units" in value), None)
        if prompt is not None:
            tools = {item["function"]["name"]: item["function"] for item in payload["tools"]}
            self.tool_views.append(deepcopy(tools))
            state = next(value for value in values if value.get("message_type") == "patch_agent_loop_state")
            self.effect_views.append(deepcopy(state.get("upstream_effects")))
            if self.read_then_finish:
                self._record_wire(request, payload, "patch")
                if not self.read_returned:
                    source = tools[PATCH_SOURCE_INSPECTION_TOOL_NAME]
                    binding = source["parameters"]["properties"]["binding_id"]["enum"][0]
                    self.read_returned = True
                    self.read_bindings.append(binding)
                    return self._response(request, {"role": "assistant", "content": "", "tool_calls": [{"function": {
                        "name": source["name"], "arguments": {"binding_id": binding}}}]})
                observations = [value for role, value in decoded if role == "tool"]
                assert observations and observations[-1]["binding_id"] == self.read_bindings[0]
                assert "KeepExistingFeedback();" in observations[-1]["excerpt"]
                content = json.dumps(self._patch(_restore_patch_agent_context(prompt), passed=True))
                self.generated_texts.append(content)
                return self._response(request, {"role": "assistant", "content": content})
            if not self.upstream_sent or (self.repeat_upstream and self.planning_sent):
                self._record_wire(request, payload, "patch")
                self.upstream_sent = True
                return self._upstream_response(request, payload)
        query = next((value for value in values if value.get("message_type") == "patch_upstream_evidence_queries"), None)
        if query is not None:
            self._record_wire(request, payload, "evidence_query")
            assert query["failure_feedback"]["observed_failure"]
            # All needed source refs already exist; the semantic coverage still
            # must be recomputed, without manufacturing a new search result.
            return self._response(request, {"role": "assistant", "content": json.dumps({"queries": []})})
        findings = next((value for value in values if value.get("message_type") == "product_requirement_findings"), None)
        if findings is not None:
            self._record_wire(request, payload, "evidence_findings")
            old = self.case.inputs.store.read(self.case.request.evidence_pack_ref)["data"]
            assert {item["evidence_id"] for item in findings["source_observations"]} == {item["evidence_id"] for item in old["items"]}
            indexes = payload["format"]["properties"]["findings"]["items"]["properties"]["relation_index"]["enum"]
            rows = [{"relation_index": index, **{key: row[key] for key in (
                "relationship", "evidence_ids", "edit_target_evidence_ids", "unresolved_gaps")}}
                for index, row in enumerate(old["requirement_coverage"]["findings"], 1) if index in indexes]
            return self._response(request, {"role": "assistant", "content": json.dumps({"findings": rows})})
        return super().__call__(request)


def _install(monkeypatch, root, case, **kwargs):
    handler = _EffectsTransport(root, case, **kwargs)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No real network in tool-effects CLI acceptance.")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)
    return handler


def _effects(planning, evidence):
    return {"planning": planning, "evidence": evidence}


def _assert_exposed_semantics(handler):
    descriptions = {
        "record_and_stop": "save request and stop this run; no automatic reassessment",
        "assess_then_stop": "Graph checks and attempts reassessment, then stops at the Plan",
        "assess_and_continue": "Graph checks and may reassess then resume Patch within remaining budget",
        "provider_unavailable_stop": "provider unavailable; save request and stop without reassessment",
    }
    for tools, effects in zip(handler.tool_views, handler.effect_views, strict=True):
        upstream = tools[PATCH_UPSTREAM_REQUEST_TOOL_NAME]
        for owner in ("evidence", "planning"):
            assert f"Current {owner} effect: {descriptions[effects[owner]]}." in upstream["description"]
        assert "known refs may justify reassessment" in upstream["description"]
        assert set(upstream["parameters"]["properties"]) == {"required_owner", "reason", "source_refs"}
        source = tools.get(PATCH_SOURCE_INSPECTION_TOOL_NAME)
        if source is not None:
            assert "Read existing registered content and return it here; no Evidence/Coverage or Plan reassessment." in source["description"]
            assert set(source["parameters"]["properties"]) == {"binding_id"}


def test_record_only_upstream_request_is_saved_and_stops_without_planning(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    _remove_upstream_configuration(case)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, result = _run(case, capsys)
    assert code != 0 and result["reason"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    assert handler.stage_roles == ["patch"]
    assert handler.effect_views == [_effects("record_and_stop", "record_and_stop")]
    assert result["execution_counts"]["planning"] == result["execution_counts"]["apply"] == 0
    journal = json.loads(Path(result["attempt_receipt"]["path"]).read_text())
    assert journal["factory_receipt"]["upstream_decision"]["upstream_request"]["source_refs"] == handler.requested_registered_refs
    _assert_exposed_semantics(handler)


def test_reading_registered_source_can_finish_without_upstream_in_record_only_mode(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    _remove_upstream_configuration(case)
    before = _source_hashes(case.inputs.workspace)
    handler = _install(monkeypatch, tmp_path / "wire", case, read_then_finish=True)
    code, result = _run(case, capsys)
    assert code == 0, result
    assert handler.stage_roles == ["patch", "patch"] and len(handler.read_bindings) == 1
    assert handler.requested_registered_refs == []
    assert handler.effect_views == [_effects("record_and_stop", "record_and_stop")] * 2
    assert result["execution_counts"]["planning"] == 0
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert _source_hashes(case.inputs.workspace) == before
    _assert_exposed_semantics(handler)


def test_automatic_planning_can_continue_and_new_worker_exposes_no_second_cycle(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, result = _run(case, capsys)
    assert code == 0, result
    assert handler.stage_roles == ["patch", "planning", "patch"]
    assert result["execution_counts"]["planning"] == 1
    assert len(handler.tool_views) == 2
    assert handler.effect_views == [_effects("assess_and_continue", "provider_unavailable_stop"),
                                    _effects("record_and_stop", "record_and_stop")]
    _assert_exposed_semantics(handler)


def test_existing_refs_may_legitimately_request_evidence_coverage_reassessment(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch, evidence=True)
    before = _source_hashes(case.inputs.workspace)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, result = _run(case, capsys)
    assert code == 0, result
    assert handler.stage_roles == ["patch", "evidence_query", "evidence_findings", "planning", "patch"]
    assert result["execution_counts"]["model"] == 5
    assert handler.requested_registered_refs
    assert handler.effect_views == [_effects("assess_and_continue", "assess_and_continue"),
                                    _effects("record_and_stop", "record_and_stop")]
    assert _source_hashes(case.inputs.workspace) == before
    _assert_exposed_semantics(handler)


def test_unconfigured_evidence_owner_stops_and_does_not_fall_back_to_planning(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch, evidence=False)
    case.evidence = True  # Synthetic model requests Evidence despite unavailable provider.
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, result = _run(case, capsys)
    assert code != 0 and result["first_failure"]["code"] == "PATCH_UPSTREAM_EVIDENCE_PROVIDER_REQUIRED"
    assert handler.stage_roles == ["patch"] and result["execution_counts"]["planning"] == 0
    assert handler.effect_views == [_effects("assess_and_continue", "provider_unavailable_stop")]
    _assert_exposed_semantics(handler)


def test_after_one_automatic_cycle_a_new_upstream_request_is_recorded_without_second_route(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    handler = _install(monkeypatch, tmp_path / "wire", case, repeat_upstream=True)
    code, result = _run(case, capsys)
    assert code != 0 and result["reason"] == "PATCH_AGENT_UPSTREAM_REQUESTED"
    assert handler.stage_roles == ["patch", "planning", "patch"]
    assert result["execution_counts"]["planning"] == 1 and result["patch_proposal_artifact"] is None
    assert len(handler.requested_registered_refs) == 2
    assert handler.effect_views == [_effects("assess_and_continue", "provider_unavailable_stop"),
                                    _effects("record_and_stop", "record_and_stop")]
    _assert_exposed_semantics(handler)
