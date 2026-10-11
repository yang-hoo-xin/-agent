"""A recorded third Query finishes through the original Graph without repaying it."""
import json
from pathlib import Path

import httpx
import pytest

from scripts import dsh_run_request as bridge
from src.mod_agent.evidence import reassessment
from src.mod_agent.initial_findings_continuation import (
    execute_initial_findings_continuation,
    prepare_initial_findings_continuation,
    preview_initial_findings_execution,
)
from tests.unit.test_dsh_run_request import _call, _install_execution_boundaries
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401
from tests.unit.test_initial_findings_continuation import _install_source_failure_baseline, _provider_backend


@pytest.mark.parametrize("accepted_gap", [False, True])
@pytest.mark.parametrize("baseline_failure", [False, True])
def test_original_run_reuses_saved_query_and_charges_only_next_live_calls(execution_config, monkeypatch, capsys, accepted_gap, baseline_failure):
    config = json.loads(execution_config.read_text())
    config["arguments"] += ["--run-id", "saved_query_run", "--request-id", "saved_query_request"]
    config["arguments"][config["arguments"].index("--task-model-call-limit") + 1] = "13"
    execution_config.write_text(json.dumps(config))
    limits = {"requirement_projection": 1, "requirement_findings": 3,
              "planning": 1, "initial_patch": 4, "repair": 4}
    (execution_config.parent / "limits.json").write_text(json.dumps(limits))
    _, _, builds = _install_execution_boundaries(execution_config.parent, monkeypatch)
    if baseline_failure:
        _install_source_failure_baseline(monkeypatch, builds)
    transport = httpx.HTTPTransport.handle_request
    query_calls = []
    def initial_transport(client, request):
        if request.method == "POST":
            native = json.loads(request.content)
            payload = json.loads(next(m["content"] for m in native["messages"] if m["role"] == "user"))
            if payload.get("message_type") == "initial_findings_evidence_queries":
                query_calls.append(payload)
                content = {"queries": [{"query": "Load", "metadata_queries": [],
                    "gap_ids": [payload["gap_investigation_targets"][0]["gap_id"]],
                    "requirement_id": payload["requirements"][0]["requirement_id"],
                    "current_fact_needed": "Current lifecycle", "modification_impact": "Binds current source",
                    "authorized_source": "target_source"}]}
                return httpx.Response(200, request=request, json={"model": native["model"],
                    "message": {"role": "assistant", "content": json.dumps(content)}, "done": True,
                    "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
            response = transport(client, request)
            if payload.get("message_type") == "product_requirement_findings":
                body = response.json()
                findings = json.loads(body["message"]["content"])
                for row in findings["findings"]:
                    row.update(relationship="missing", evidence_ids=[], edit_target_evidence_ids=[],
                               unresolved_gaps=["Current input lifecycle not understood."])
                body["message"]["content"] = json.dumps(findings)
                return httpx.Response(200, request=request, json=body)
            return response
        return transport(client, request)
    def old_merge(*_):
        raise ValueError("PATCH_REASSESSMENT_EVIDENCE_ID_CONFLICT")
    with monkeypatch.context() as first:
        from src.mod_agent.evidence.requirement_coverage_provider import StructuredModelRequirementCoverageProvider
        original_init = StructuredModelRequirementCoverageProvider.__init__
        def historical_init(self, complete_json, **kwargs):
            # 为什么要有它：本夹具记录旧无native marker的真实恢复合同，正常新入口另有native控制。
            kwargs["native_findings_contract"] = None
            original_init(self, complete_json, **kwargs)
        first.setattr(StructuredModelRequirementCoverageProvider, "__init__", historical_init)
        first.setattr(httpx.HTTPTransport, "handle_request", initial_transport)
        first.setattr(reassessment, "merge_reobserved_source_item", old_merge)
        code = _call(execution_config, "make Load record deterministic product diagnostics", monkeypatch)
    original = json.loads(capsys.readouterr().out)
    assert code != 0
    assert original["model_call_count"] == 3
    assert len(query_calls) == 1
    assert "PATCH_REASSESSMENT_EVIDENCE_ID_CONFLICT" in json.dumps(original["blockers"])
    root = Path(original["run_root"])
    frozen = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    args = {"run_root": root, "run_id": original["run_id"], "execution_config": execution_config}
    prepared = prepare_initial_findings_continuation(**args)
    if baseline_failure:
        baseline = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))["baseline_build"]
        packet = prepared["continuation_input"]
        assert packet["next_turn"]["payload"]["baseline_compilation_failure"] == baseline["repair_observation"]
        assert packet["retrieved_evidence"]["budget_summary"]["baseline_compilation_failure"] == baseline["repair_observation"]
    assert prepared["budget"]["consumed"] == 3
    assert prepared["continuation_input"]["next_turn"]["role"] == "requirement_findings"
    assert prepared["continuation_input"]["saved_reassessment_query"]["response_ref"]["sha256"]
    assert all(p.read_bytes() == raw for p, raw in frozen.items())
    allocation = execution_config.parent / "saved-query-allocation.json"
    allocation.write_text(json.dumps({"stage_model_call_limits": limits, "max_execution_seconds": 1800,
        "findings_contract_version": "3", "include_downstream_preflight": True,
        "provider_backend": _provider_backend(execution_config.parent)}))
    args["allocation_config"] = allocation
    preview = preview_initial_findings_execution(**args)
    assert preview["blockers"] == []
    assert [x["role"] for x in preview["execution_scope"]["model_call_preflight"]["calls"]] == [
        "requirement_findings", "planning", "initial_patch"]
    assert preview["execution_scope"]["first_provider_request_preflight"]["role"] == "requirement_findings"
    live_roles = []
    def continuation_transport(client, request):
        if request.method == "POST":
            native = json.loads(request.content)
            payload = json.loads(next(m["content"] for m in native["messages"] if m["role"] == "user"))
            role = payload.get("message_type")
            assert role not in {"product_requirement_projection", "initial_findings_evidence_queries"}
            live_roles.append(role)
        return initial_transport(client, request) if accepted_gap else transport(client, request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", continuation_transport)
    completed = execute_initial_findings_continuation(**args,
        decision={"decision": "approve", "reviewer": "offline-fixture", "scope_hash": preview["scope_hash"]})
    if accepted_gap:
        assert completed["status"] == "domain_blocked"
        assert completed["model_call_count"] == 4
        assert live_roles == ["product_requirement_findings"]
        completed_files = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        value = json.loads(allocation.read_text())
        value["resume_mode"] = "accepted_findings_reassessment_revision"
        allocation.write_text(json.dumps(value))
        revision = preview_initial_findings_execution(**args)
        assert revision["blockers"] == []
        assert revision["effective_budget"]["consumed"] == 4
        assert revision["effective_budget"]["maximum"] == 13
        assert revision["execution_scope"]["first_provider_request_preflight"]["role"] == "initial_findings_queries"
        assert [row["role"] for row in revision["execution_scope"]["model_call_preflight"]["calls"]] == [
            "initial_findings_queries", "requirement_findings", "planning", "initial_patch"]
        assert all(p.read_bytes() == raw for p, raw in completed_files.items())
        receipt = revision["continuation_input"]["saved_reassessment_completion"]
        assert receipt["budget_before"]["consumed"] == 3
        assert receipt["budget_after"]["consumed"] == 4
        response_path = Path(receipt["response_ref"]["path"])
        raw_response = response_path.read_bytes()
        response_path.write_bytes(raw_response + b" ")
        try:
            with pytest.raises(ValueError, match="INITIAL_FINDINGS_INPUT_HASH_CHANGED"):
                preview_initial_findings_execution(**args)
        finally:
            response_path.write_bytes(raw_response)
        manifest_path = Path(receipt["manifest_ref"]["path"])
        raw_manifest = manifest_path.read_bytes()
        changed_manifest = json.loads(raw_manifest)
        request_span = next(row for row in changed_manifest["execution_observations"].values()
                            if row["name"] == "model.request")
        request_span["attributes"]["transport_started"] = False
        manifest_path.write_text(json.dumps(changed_manifest), encoding="utf-8")
        try:
            with pytest.raises(ValueError, match="SAVED_REASSESSMENT_COMPLETION_TRACE_INVALID"):
                preview_initial_findings_execution(**args)
        finally:
            manifest_path.write_bytes(raw_manifest)
        assert live_roles == ["product_requirement_findings"]
        live_roles.clear()
        def revision_transport(client, request):
            if request.method == "POST":
                native = json.loads(request.content)
                payload = json.loads(next(m["content"] for m in native["messages"] if m["role"] == "user"))
                role = payload.get("message_type")
                assert role != "product_requirement_projection"
                live_roles.append(role)
                if role == "initial_findings_evidence_queries":
                    response = initial_transport(client, request)
                    body = response.json()
                    content = json.loads(body["message"]["content"])
                    content["queries"][0]["query"] = "Load lifecycle"
                    body["message"]["content"] = json.dumps(content)
                    return httpx.Response(200, request=request, json=body)
            return transport(client, request)
        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", revision_transport)
        completed = execute_initial_findings_continuation(**args,
            decision={"decision": "approve", "reviewer": "offline-fixture", "scope_hash": revision["scope_hash"]})
        assert completed["status"] == "awaiting_approval", completed.get("blockers", completed.get("reason"))
        assert completed["prior_model_call_count"] == 4
        assert live_roles[:2] == ["initial_findings_evidence_queries", "product_requirement_findings"]
        assert completed["model_call_budget"]["by_stage"]["planning"]["consumed"] == 1
        assert completed["model_call_budget"]["by_stage"]["initial_patch"]["consumed"] == 1
        assert len(query_calls) == 2
        immutable_completed = {p: raw for p, raw in completed_files.items()
            if not p.is_relative_to(root / "a") or "r" in p.relative_to(root / "a").parts}
        assert all(p.read_bytes() == raw for p, raw in immutable_completed.items())
    assert completed["status"] == "awaiting_approval", json.dumps(completed, ensure_ascii=True)
    assert completed["prior_model_call_count"] == (4 if accepted_gap else 3)
    assert completed["model_call_count"] == (8 if accepted_gap else 6)
    assert completed["model_call_budget"]["maximum"] == 13
    assert len(live_roles) == (4 if accepted_gap else 3)
    assert len(builds) == 1  # Original simulated baseline only.
    assert completed["actual_write_performed"] is False
    immutable = {p: raw for p, raw in frozen.items()
                 if not p.is_relative_to(root / "a") or "r" in p.relative_to(root / "a").parts}
    assert all(p.read_bytes() == raw for p, raw in immutable.items())
    latest = bridge.inspect_run(execution_config=str(execution_config), run_id=original["run_id"])
    assert latest["result"]["model_call_count"] == (8 if accepted_gap else 6)
