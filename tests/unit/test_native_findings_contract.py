"""Planning knowledge and future implementation status are independent model judgments."""
from copy import deepcopy
import hashlib
import json

import pytest
from jsonschema import Draft7Validator

from src.mod_agent.evidence import build_requirement_coverage_pack
from src.mod_agent.evidence.native_findings_contract import VERSION, materialize, schema
from src.mod_agent.evidence.requirement_coverage_provider import StructuredModelRequirementCoverageProvider
from tests.unit.test_requirement_coverage import _materialized_and_retrieved, _positive_findings
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401


def native_fixture(materialized, retrieved, behavior="not_yet_implemented"):
    prior = _positive_findings(materialized, retrieved)
    return {"findings": [{"relation_index": row["relation_index"], "planning_readiness": "ready",
        "current_evidence_ids": row["evidence_ids"], "current_basis": "Cited current source identifies the existing implementation and edit location.",
        "requested_behavior_status": behavior, "blocking_current_facts": [],
        "edit_target_evidence_ids": row["edit_target_evidence_ids"]} for row in prior["findings"][:2]]}


def invoke(prepared, response, *, corrected=None):
    feature, projection, retrieved = prepared
    calls = []
    def complete(role, payload, response_schema):
        calls.append((role, deepcopy(payload), deepcopy(response_schema)))
        return deepcopy(response if len(calls) == 1 or corrected is None else corrected)
    provider = StructuredModelRequirementCoverageProvider(complete, native_findings_contract=VERSION)
    findings = provider.findings(materialized_projection=projection, retrieved_pack=retrieved,
        request=feature["user_request"])
    pack = build_requirement_coverage_pack(query=feature["user_request"], materialized_projection=projection,
        retrieved_pack=retrieved, findings=findings)
    return findings, pack, provider, calls


@pytest.mark.parametrize("behavior", ["not_yet_implemented", "already_present", "not_assessed", "not_applicable"])
def test_sufficient_current_basis_allows_planning_even_when_requested_behavior_is_absent(tmp_path, behavior):
    feature, projection, retrieved = _materialized_and_retrieved(tmp_path)
    response = native_fixture(projection, retrieved, behavior)
    original = deepcopy(response)
    findings, pack, provider, calls = invoke((feature, projection, retrieved), response)
    assert len(calls) == 1 and response == original
    assert pack.can_generate_patch is True
    assert findings["findings"][:2] == materialize(response)["findings"]
    assert all(row["relationship"] == "support" and row["unresolved_gaps"] == [] for row in findings["findings"][:2])
    record = provider.findings_attempt_audit[0]["native_findings_provenance"]
    assert record["native_response"] == original and record["mapped_findings"] == findings
    assert record["mapping_admitted"] and not record["requested_behavior_status_changes_coverage"]
    assert record["semantic_origin"] == "model_current_planning_readiness_not_host_inferred_support"
    assert "apply_permission" in pack.requirement_coverage["does_not_grant"] and not record["grants_execution_authority"]
    assert calls[0][1]["native_findings_contract"] == VERSION
    assert all("Each item contains only relation_index, relationship" not in rule for rule in calls[0][1]["rules"])


@pytest.mark.parametrize("behavior", ["not_yet_implemented", "already_present"])
def test_unknown_current_api_stays_blocking_regardless_of_future_behavior_status(tmp_path, behavior):
    feature, projection, retrieved = _materialized_and_retrieved(tmp_path)
    response = native_fixture(projection, retrieved, behavior)
    row = response["findings"][0]
    row.update(planning_readiness="needs_current_evidence", edit_target_evidence_ids=[],
        current_basis="The entry source is visible but the required dependency callback contract has not been observed.",
        blocking_current_facts=[{"fact_needed": "Exact dependency callback argument lifetime", "planning_impact": "Determines whether the added observer may retain its argument."}])
    findings, pack, _, calls = invoke((feature, projection, retrieved), response)
    assert len(calls) == 1 and pack.can_generate_patch is False
    assert findings["findings"][0]["relationship"] == "missing"
    assert "argument lifetime" in findings["findings"][0]["unresolved_gaps"][0]
    assert "Determines whether" in findings["findings"][0]["unresolved_gaps"][0]
    assert findings["findings"][0]["evidence_ids"] == row["current_evidence_ids"]


@pytest.mark.parametrize("damage", ["no_citation", "unknown_citation", "ready_with_gap", "missing_without_gap",
    "conflict_without_citation", "duplicate_relation", "unknown_relation", "edit_not_cited", "preservation_edit", "unknown_behavior"])
def test_native_inconsistency_or_illegal_evidence_never_becomes_support(tmp_path, damage):
    feature, projection, retrieved = _materialized_and_retrieved(tmp_path)
    response = native_fixture(projection, retrieved)
    row = response["findings"][0]
    if damage == "no_citation":
        row["current_evidence_ids"] = []
    elif damage == "unknown_citation":
        row["current_evidence_ids"] = ["invented"]
    elif damage == "ready_with_gap":
        row["blocking_current_facts"] = [{"fact_needed": "Unknown current contract", "planning_impact": "Needed to plan"}]
    elif damage == "missing_without_gap":
        row.update(planning_readiness="needs_current_evidence", edit_target_evidence_ids=[])
    elif damage == "conflict_without_citation":
        row.update(planning_readiness="conflicting_current_evidence", current_evidence_ids=[], edit_target_evidence_ids=[],
            blocking_current_facts=[{"fact_needed": "Conflicting contract", "planning_impact": "Cannot choose signature"}])
    elif damage == "duplicate_relation":
        response["findings"][1]["relation_index"] = row["relation_index"]
    elif damage == "unknown_relation":
        row["relation_index"] = 999
    elif damage == "edit_not_cited":
        row["edit_target_evidence_ids"] = response["findings"][1]["current_evidence_ids"]
    elif damage == "preservation_edit":
        response["findings"][1]["edit_target_evidence_ids"] = response["findings"][1]["current_evidence_ids"]
    else:
        row["requested_behavior_status"] = "approved_and_deployed"
    provider = StructuredModelRequirementCoverageProvider(lambda *_: deepcopy(response), native_findings_contract=VERSION)
    with pytest.raises(ValueError):
        provider.findings(materialized_projection=projection, retrieved_pack=retrieved, request=feature["user_request"])
    assert [row["status"] for row in provider.findings_attempt_audit] == ["rejected", "rejected"]
    assert all(not row["native_findings_provenance"]["mapping_admitted"] for row in provider.findings_attempt_audit)


def test_same_bounded_correction_preserves_genuine_gap_instead_of_forcing_ready(tmp_path):
    feature, projection, retrieved = _materialized_and_retrieved(tmp_path)
    bad = native_fixture(projection, retrieved)
    bad["findings"][0]["blocking_current_facts"] = [{"fact_needed": "Current API signature", "planning_impact": "Call arguments cannot be chosen."}]
    corrected = deepcopy(bad)
    corrected["findings"][0].update(planning_readiness="needs_current_evidence", edit_target_evidence_ids=[])
    _, pack, provider, calls = invoke((feature, projection, retrieved), bad, corrected=corrected)
    assert [row[0] for row in calls] == ["requirement_findings", "requirement_findings_correction"]
    assert calls[1][1]["previous_native_findings"] == bad
    assert not pack.can_generate_patch
    assert provider.findings_attempt_audit[-1]["native_findings_provenance"]["native_response"] == corrected


def test_empty_current_evidence_schema_cannot_emit_ready_or_conflict():
    selected = schema(relation_indexes=[1], evidence_ids=[], edit_target_evidence_ids=[])
    assert '"enum": []' not in json.dumps(selected)
    row = {"relation_index": 1, "planning_readiness": "needs_current_evidence", "current_evidence_ids": [],
        "current_basis": "No current source observations were supplied.", "requested_behavior_status": "not_assessed",
        "blocking_current_facts": [{"fact_needed": "Current entry implementation", "planning_impact": "An edit location must be identified."}],
        "edit_target_evidence_ids": []}
    assert Draft7Validator(selected).is_valid({"findings": [row]})
    for readiness in ("ready", "conflicting_current_evidence"):
        assert not Draft7Validator(selected).is_valid({"findings": [{**row, "planning_readiness": readiness}]})


def test_native_preparation_keeps_full_schema_without_transport(tmp_path, monkeypatch):
    import httpx
    from src.libs.llm.ollama_llm import OllamaLLM
    from src.mod_agent.requirement_coverage_model import requirement_coverage_messages
    from tests.unit.test_ollama_llm import MockSettings
    feature, projection, retrieved = _materialized_and_retrieved(tmp_path)
    _, _, _, calls = invoke((feature, projection, retrieved), native_fixture(projection, retrieved))
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("unexpected HTTP"))
    request = {}
    OllamaLLM(MockSettings(), context_window=32768).prepare_structured_chat(requirement_coverage_messages(calls[0][1]),
        response_format=calls[0][2], max_tokens=4096, temperature=0.0, provider_request_recorder=request.update)
    assert request["context_admission"]["admitted"]
    for variant in calls[0][2]["properties"]["findings"]["items"]["oneOf"]:
        assert variant["additionalProperties"] is False and "requested_behavior_status" in variant["required"]


def test_recorded_native_response_and_mapping_hashes_are_independently_checkable(tmp_path):
    feature, projection, retrieved = _materialized_and_retrieved(tmp_path)
    findings, _, provider, _ = invoke((feature, projection, retrieved), native_fixture(projection, retrieved))
    record = provider.findings_attempt_audit[-1]["native_findings_provenance"]
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert record["native_response_sha256"] == digest(record["native_response"])
    assert record["mapped_findings_sha256"] == digest(findings)
    assert materialize(record["native_response"])["findings"] == findings["findings"][:2]


def test_native_historical_preparation_reconstructs_marker_and_keeps_original_budget(execution_config, monkeypatch, capsys):
    import httpx
    from pathlib import Path
    from src.mod_agent.initial_findings_continuation import prepare_initial_findings_continuation
    from tests.unit.test_dsh_run_request import _call, _install_execution_boundaries
    config = json.loads(execution_config.read_text())
    config["arguments"] += ["--run-id", "native_findings", "--request-id", "native_request"]
    execution_config.write_text(json.dumps(config))
    _install_execution_boundaries(execution_config.parent, monkeypatch)
    (execution_config.parent / "limits.json").write_text(json.dumps({"requirement_projection": 1,
        "requirement_findings": 1, "planning": 1, "initial_patch": 4, "repair": 4}))
    original_transport = httpx.HTTPTransport.handle_request
    posts = []
    def transport(client, request):
        response = original_transport(client, request)
        if request.method == "POST":
            posts.append(request)
            body = response.json()
            content = json.loads(body["message"]["content"])
            if "findings" in content:
                assert content["findings"][0]["planning_readiness"] == "ready"
                content["findings"][0]["blocking_current_facts"] = [
                    {"fact_needed": "Current API lifetime", "planning_impact": "Cannot choose retained state safely."}]
                body["message"]["content"] = json.dumps(content)
                return httpx.Response(200, request=request, json=body)
        return response
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    assert _call(execution_config, "make Load record deterministic product diagnostics", monkeypatch) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["model_call_count"] == len(posts) == 2
    root = Path(result["run_root"])
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("historical preparation invoked HTTP"))
    prepared = prepare_initial_findings_continuation(run_root=root, run_id=result["run_id"], execution_config=execution_config)
    packet = prepared["continuation_input"]
    assert packet["native_findings_contract"] == VERSION
    assert packet["next_turn"]["payload"]["native_findings_contract"] == VERSION
    assert packet["next_turn"]["payload"]["previous_native_findings"]["findings"][0]["blocking_current_facts"]
    assert prepared["model_calls_performed"] == 0 and prepared["budget"] == result["model_call_budget"]
    assert all(path.read_bytes() == raw for path, raw in before.items())
