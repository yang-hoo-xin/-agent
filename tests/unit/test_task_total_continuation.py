"""The known native-schema refusal resumes Findings once, without repaying Projection."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from scripts import dsh_run_request as bridge
from src.mod_agent import initial_findings_continuation as continuation
from src.mod_agent.evidence import requirement_coverage_provider as provider
from tests.unit.test_request_interpretation_continuation import (
    _at_four,
    _query,
    _ref,
    _select_revision,
    _write,
)
from tests.unit.test_request_interpretation_continuation import (
    execution_config as execution_config,  # noqa: F401
)

ERROR = {"code": 400, "message": "Field 'json_schema': JSON schema conversion failed:\nJSON schema error at #/properties/findings/items/properties/evidence_ids/items: enum must be a non-empty array",
         "type": "invalid_request_error"}


def test_total_budget_reuses_accepted_corrected_findings(execution_config, monkeypatch, capsys):
    args, previous, transport, builds = _at_four(execution_config, monkeypatch, capsys)
    allocation, _ = _select_revision(args, previous)
    roles = []
    original_schema = provider.requirement_findings_response_schema
    def broken_empty_schema(**kwargs):
        schema = original_schema(**kwargs)
        if not kwargs["evidence_ids"]:
            domain = schema["properties"]["findings"]["items"]["properties"]["evidence_ids"]
            domain.pop("maxItems", None)
            domain["items"]["enum"] = []
        return schema
    def refusal_transport(client, request):
        if request.method != "POST":
            return transport(client, request)
        native = json.loads(request.content)
        payload = json.loads(next(m["content"] for m in native["messages"] if m["role"] == "user"))
        role = payload.get("message_type")
        roles.append(role)
        if role == "product_requirement_findings":
            assert payload["source_observations"] == []
            assert native["format"]["properties"]["findings"]["items"]["properties"]["evidence_ids"]["items"]["enum"] == []
            return httpx.Response(400, request=request, json={"error": json.dumps({"error": ERROR})})
        response = transport(client, request)
        if role == "product_requirement_projection":
            body = response.json()
            content = json.loads(body["message"]["content"])
            for row in content["requirements"]:
                row["query_leads"] = ["deliberately unmatched fixture probe"]
            body["message"]["content"] = json.dumps(content)
            return httpx.Response(200, request=request, json=body)
        return response
    call = {"execution_config": str(execution_config), "run_id": args["run_id"],
            "allocation_config": str(args["allocation_config"])}
    with monkeypatch.context() as fault:
        fault.setattr(provider, "requirement_findings_response_schema", broken_empty_schema)
        fault.setattr(httpx.HTTPTransport, "handle_request", refusal_transport)
        failed = bridge.advance_task(**call)
    assert failed["status"] == "partial"
    assert failed["model_call_count"] == 6
    assert roles == ["product_requirement_projection", "product_requirement_findings"]
    root, temp = args["run_root"], execution_config.parent
    parent_path = Path(failed["continuation_root"]) / "run_result.json"
    parent_ref = _ref(parent_path)
    originals = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()
                 and (not p.is_relative_to(root / "a") or "r" in p.relative_to(root / "a").parts)}
    provider_ref = _ref(Path(provider.__file__))
    fix_freeze = _write(temp / "schema-freeze.json", {"files": [{
        "target_path": provider_ref["path"], "before_sha256": provider_ref["sha256"],
        "after_sha256": provider_ref["sha256"], "staged_after_path": provider_ref["path"]}]})
    fix = _write(temp / "schema-fix.json", {"freeze": fix_freeze,
        "before_sha256": provider_ref["sha256"], "after_sha256": provider_ref["sha256"]})
    old_decision = json.loads(Path(allocation["request_interpretation_revision"]["decision_ref"]["path"]).read_text())
    recovery_decision = {**old_decision, "prior_budget": failed["model_call_budget"], "prior_consumed": 6}
    decision_path = temp / "recovery-decision.json"
    selection = allocation["request_interpretation_revision"]
    selection["decision_ref"] = _write(decision_path, recovery_decision)
    selection["findings_schema_recovery"] = {"parent_result_ref": parent_ref,
        "parent_manifest_ref": _ref(Path(failed["continuation_root"]) / "run_manifest.json"),
        "schema_fix_ref": fix, "provider_ref": provider_ref}
    _write(args["allocation_config"], allocation)
    roles.clear()
    blocked = bridge.advance_task(**call)
    assert "PRODUCT_STAGE_MODEL_CALL_BUDGET_EXHAUSTED" in blocked["blockers"]
    assert blocked["effective_budget"]["consumed"] == 6
    assert not (root / "continuations/initial_findings-reassessment-v3.json").exists()
    assert roles == []
    limits = {"requirement_projection": 2, "requirement_findings": 5, "planning": 1, "initial_patch": 2, "repair": 3}
    recovery_decision["selected_stage_model_call_limits"] = limits
    selection["decision_ref"] = _write(decision_path, recovery_decision)
    allocation["stage_model_call_limits"] = limits
    _write(args["allocation_config"], allocation)
    manifest_path = Path(selection["findings_schema_recovery"]["parent_manifest_ref"]["path"])
    manifest_bytes = manifest_path.read_bytes()
    manifest_path.write_bytes(manifest_bytes + b" ")
    try:
        with pytest.raises(ValueError, match="REQUEST_INTERPRETATION_REVISION_REF_CHANGED"):
            bridge.advance_task(**call)
    finally:
        manifest_path.write_bytes(manifest_bytes)
    # Another HTTP 400 is not the verified native-schema failure, even with the same count.
    parent_bytes = parent_path.read_bytes()
    other = json.loads(parent_bytes)
    other["blockers"][0]["message"] = "OllamaLLMError: [Ollama] API error (HTTP 400): " + json.dumps({
        "error": {**ERROR, "message": "Unrelated request failure"}})
    selection["findings_schema_recovery"]["parent_result_ref"] = _write(parent_path, other)
    _write(args["allocation_config"], allocation)
    try:
        with pytest.raises(ValueError, match="FINDINGS_SCHEMA_RECOVERY_FAILURE_UNSUPPORTED"):
            bridge.advance_task(**call)
    finally:
        parent_path.write_bytes(parent_bytes)
        selection["findings_schema_recovery"]["parent_result_ref"] = parent_ref
        _write(args["allocation_config"], allocation)
    preview = continuation.preview_initial_findings_execution(**args)
    assert preview["blockers"] == []
    assert preview["continuation_input"]["next_turn"]["role"] == "requirement_findings"
    assert [x["role"] for x in preview["execution_scope"]["model_call_preflight"]["calls"]] == [
        "requirement_findings", "initial_findings_queries", "requirement_findings", "planning", "initial_patch"]
    def recovery_transport(client, request):
        if request.method != "POST":
            return transport(client, request)
        native = json.loads(request.content)
        payload = json.loads(next(m["content"] for m in native["messages"] if m["role"] == "user"))
        role = payload.get("message_type")
        assert role != "product_requirement_projection"
        roles.append(role)
        if role == "initial_findings_evidence_queries":
            return _query(native, payload, request, text="Load lifecycle")
        if role in {"product_requirement_findings", "product_requirement_findings_correction"} and not payload["source_observations"]:
            domain = native["format"]["properties"]["findings"]["items"]["properties"]["evidence_ids"]
            assert domain["maxItems"] == 0 and "enum" not in domain["items"]
            content = {"findings": [{"relation_index": row["relation_index"], "relationship": "support" if role == "product_requirement_findings" and row["relation_index"] == 1 else "missing",
                "evidence_ids": [], "edit_target_evidence_ids": [], "unresolved_gaps": ["Current source facts are missing."]}
                for row in payload["relations"]]}
            return httpx.Response(200, request=request, json={"model": native["model"],
                "message": {"role": "assistant", "content": json.dumps(content)}, "done": True,
                "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
        return transport(client, request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", recovery_transport)
    result = bridge.advance_task(**call)
    assert result["status"] == "partial"
    assert result["model_call_count"] == 8
    current_root = Path(result["continuation_root"])
    parent = current_root / "run_result.json"
    trace = current_root / "run_manifest.json"
    accepted_files = {p: p.read_bytes() for p in current_root.rglob("*") if p.is_file()}
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision.update(prior_budget=result["model_call_budget"], prior_consumed=8,
        model_call_budget_policy="task_total_only", parent_result_ref=_ref(parent), parent_manifest_ref=_ref(trace))
    decision.pop("selected_stage_model_call_limits", None)
    selection["decision_ref"] = _write(temp / "total-decision.json", decision)
    allocation["model_call_budget_policy"] = "task_total_only"
    allocation.pop("stage_model_call_limits")
    _write(args["allocation_config"], allocation)
    roles.clear()
    original_read = continuation._bound_json
    def typed_drift(reference, selected_root):
        ref, value = original_read(reference, selected_root)
        if Path(reference["path"]).parent.parent == current_root and "format" in value:
            values = value["format"]["properties"]["findings"]["items"]["properties"]["relation_index"]["enum"]
            if values and values[0] == 1:
                values[0] = True
        return ref, value
    with monkeypatch.context() as drift:
        drift.setattr(continuation, "_bound_json", typed_drift)
        with pytest.raises(ValueError, match="ACCEPTED_FINDINGS_PROGRESS_TRACE_INVALID"):
            bridge.advance_task(**call)
    assert roles == []
    result = bridge.advance_task(**call)
    assert result["status"] == "awaiting_approval", result.get("blockers", result.get("reason"))
    assert result["prior_model_call_count"] == 8 and result["model_call_count"] == 12
    assert result["projection_model_calls_performed"] == result["baseline_builds_performed"] == 0
    assert len(builds) == 1 and result["actual_write_performed"] is False
    assert result["model_call_budget"]["policy"] == "task_total_only"
    assert result["model_call_budget"]["by_stage"]["requirement_findings"] == {"consumed": 6}
    assert roles[:2] == ["initial_findings_evidence_queries", "product_requirement_findings"]
    assert len(roles) == 4
    assert all(p.read_bytes() == raw for p, raw in accepted_files.items())
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    previous_calls = deepcopy(roles)
    assert bridge.advance_task(**call)["scope_hash"] == result["scope_hash"]
    assert roles == previous_calls
