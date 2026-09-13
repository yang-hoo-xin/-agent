"""Actual upstream owner observations without model or game execution."""
import hashlib
import json
from types import MappingProxyType
from dataclasses import replace

import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.mod_agent.evidence import RequirementCoverageEvidenceProvider, RgLiveEvidenceProvider
from src.mod_agent.planning.model_selection import PlanningTargetSelectionError
from src.mod_agent.upstream_trace import material_identities, model_input_materials, payload_sha256, observe_evidence_factory
from tests.unit.test_fresh_planning_continuation import (
    _feature_payload, _inputs, _positive_findings, _projection, _write_sources,
)
from tests.unit.test_model_planning_selection import _Client, _selector


def _rows(trace):
    return list({stage["data"]["id"]: stage["data"] for stage in trace.context.stages}.values())


def test_requirement_owners_record_current_material_production_and_findings(tmp_path):
    _write_sources(tmp_path)
    feature = _feature_payload()
    inputs = []

    def findings(materialized, retrieved):
        inputs.append(retrieved)
        return _positive_findings(materialized, retrieved)

    provider = RequirementCoverageEvidenceProvider(
        RgLiveEvidenceProvider(tmp_path), projection_factory=lambda _: _projection(),
        findings_factory=findings,
    )
    trace = ExecutionTrace("upstream-test", "logical-task", "test")
    with trace.activate():
        result = provider.collect(query=feature["user_request"],
            search_root="generated_mods/SyntheticMod", feature_data=feature)
    rows = _rows(trace)
    assert result.can_generate_patch is True
    projection = next(row for row in rows if row["name"] == "requirements.projection")
    retrieve = next(row for row in rows if row["name"] == "evidence.retrieve")
    coverage = next(row for row in rows if row["name"] == "requirements.coverage")
    tools = [row for row in rows if row["name"] == "evidence.source_query"]
    assert len(tools) == projection["attributes"]["query_count"]
    assert all(row["parent_id"] == retrieve["id"] for row in tools)
    assert retrieve["attributes"]["produced_materials"] == material_identities(inputs[0].items)
    assert coverage["attributes"]["consumed_materials"] == retrieve["attributes"]["produced_materials"]
    assert coverage["attributes"]["output_payload_sha256"] == payload_sha256(result.to_artifact_payload())
    assert coverage["attributes"]["findings_invocation_performed"] is True
    assert coverage["attributes"]["decision"] == "patch_allowed"
    assert coverage["attributes"]["reason_status"] == "reason_unavailable"
    assert coverage["attributes"]["relationship_counts"]["support"] > 0
    assert all(row["trace_id"] == "upstream-test" and row["finished_at"] for row in rows)
    assert not any(row["kind"] == "generation" for row in rows)
    encoded = json.dumps(rows)
    assert "KeepExistingFeedback();" not in encoded
    assert feature["user_request"] not in encoded


@pytest.mark.parametrize(("root", "query", "status", "sent"), [
    ("missing", "ChangeMarker", "source_root_missing", False),
    ("generated_mods/SyntheticMod", "NotInAnySource", "no_matches", True),
])
def test_missing_material_and_query_miss_are_distinct(tmp_path, root, query, status, sent):
    _write_sources(tmp_path)
    trace = ExecutionTrace("retrieval-test", "task", "test")
    with trace.activate():
        result = RgLiveEvidenceProvider(tmp_path).collect(query=query, search_root=root)
    row = next(row for row in _rows(trace) if row["name"] == "evidence.source_query")
    assert not result.items
    assert row["attributes"]["retrieval_status"] == status
    assert row["attributes"]["tool_dispatch_performed"] is sent
    assert row["attributes"]["produced_materials"] == []


def test_planning_links_exact_model_input_to_local_rationale_without_extra_calls(tmp_path):
    inputs = _inputs(tmp_path)
    client = _Client()
    selector = _selector(inputs, client)
    trace = ExecutionTrace("planning-test", "task", "test")
    with trace.activate():
        selected = selector(inputs.feature_payload, inputs.store.read(inputs.evidence_ref)["data"])
    row = next(row for row in _rows(trace) if row["name"] == "planning.decision")
    attrs = row["attributes"]
    payload = client.calls[0].messages[1].content
    assert len(client.calls) == 1
    assert attrs["input_payload_sha256"] == payload_sha256(payload)
    assert attrs["consumed_materials"] == model_input_materials(payload)
    assert attrs["selected_evidence_ids"] == list(selected)
    assert attrs["material_delivery_status"] == "model_input_assembled"
    assert attrs["reason_status"] == "model_rationale_local_only"
    receipt = selector.receipt_path.read_bytes()
    assert attrs["local_detail_refs"]["planning_receipt"] == {
        "path": str(selector.receipt_path), "sha256": hashlib.sha256(receipt).hexdigest(),
    }
    rationale = json.loads(receipt)["selection"]["rationale"]
    assert rationale not in json.dumps(row)
    assert attrs["reason_sha256"] == hashlib.sha256(rationale.encode()).hexdigest()
    assert not any(row["kind"] == "generation" for row in _rows(trace))


def test_failed_planning_records_decision_without_inventing_rationale(tmp_path):
    inputs = _inputs(tmp_path)
    client = _Client(override=lambda result: {**result, "rationale": ""})
    selector = _selector(inputs, client)
    trace = ExecutionTrace("planning-failed", "task", "test")
    with trace.activate(), pytest.raises(PlanningTargetSelectionError):
        selector(inputs.feature_payload, inputs.store.read(inputs.evidence_ref)["data"])
    row = next(row for row in _rows(trace) if row["name"] == "planning.decision")
    assert row["status"] == "failed"
    assert row["attributes"]["reason_status"] == "reason_unavailable"
    assert len(client.calls) == 1


def test_absent_source_hash_is_not_invented_for_findings_payload():
    payload = {"source_observations": [{"evidence_id": "id-1", "source_type": "target_source", "excerpt": "exact\r\n"}]}
    rows = model_input_materials(payload)
    assert rows[0]["source_hash"] is None
    assert rows[0]["excerpt_sha256"] == hashlib.sha256(b"exact\r\n").hexdigest()


def test_source_tool_launch_failure_does_not_claim_completed_dispatch(tmp_path):
    _write_sources(tmp_path)
    trace = ExecutionTrace("missing-tool", "task", "test")
    with trace.activate(), pytest.raises(FileNotFoundError):
        RgLiveEvidenceProvider(tmp_path, rg_executable="missing-rg-executable-test").collect(
            query="ChangeMarker", search_root="generated_mods/SyntheticMod")
    row = next(row for row in _rows(trace) if row["name"] == "evidence.source_query")
    assert row["status"] == "failed"
    assert row["attributes"]["tool_dispatch_attempted"] is True
    assert row["attributes"]["tool_dispatch_performed"] is False


def test_broken_observation_recorder_does_not_change_planning(tmp_path):
    inputs = _inputs(tmp_path)
    client = _Client()
    selector = _selector(inputs, client)

    def broken(_):
        raise OSError("offline recorder unavailable")

    trace = ExecutionTrace("recorder-offline", "task", "test", recorder=broken)
    with trace.activate():
        selected = selector(inputs.feature_payload, inputs.store.read(inputs.evidence_ref)["data"])
    assert selected
    assert len(client.calls) == 1
    assert trace.failure_statistics()["recorder"]["total"] > 0


def test_legacy_projection_extension_that_is_not_json_does_not_break_collection(tmp_path):
    _write_sources(tmp_path)
    feature = _feature_payload()
    projection = MappingProxyType(_projection())
    provider = RequirementCoverageEvidenceProvider(RgLiveEvidenceProvider(tmp_path),
        projection_factory=lambda _: projection, findings_factory=_positive_findings)
    trace = ExecutionTrace("legacy-extension", "task", "test")
    with trace.activate():
        result = provider.collect(query=feature["user_request"],
            search_root="generated_mods/SyntheticMod", feature_data=feature)
    assert result.can_generate_patch is True
    row = next(row for row in _rows(trace) if row["name"] == "requirements.projection")
    assert row["attributes"]["structured_output_sha256"] is None


def test_unrepresentable_material_projection_is_unknown_not_empty():
    assert material_identities([object()]) is None
    assert model_input_materials({"source_observations": [{"source_identity_ref": 9}]}) is None


@pytest.mark.parametrize(("fact_count", "blocked"), [(0, False), (1, False), (0, True)])
def test_final_assembly_records_returned_pack_without_reinvocation(tmp_path, fact_count, blocked):
    _write_sources(tmp_path)
    retrieved = RgLiveEvidenceProvider(tmp_path).collect(
        query="ChangeMarker", search_root="generated_mods/SyntheticMod")
    item = replace(retrieved.items[0], verified_member_accesses=tuple(
        {"test_bound_fact": index} for index in range(fact_count)))
    pack = replace(retrieved, items=(item,), readiness="insufficient" if blocked else "sufficient",
        can_generate_patch=not blocked, budget_summary={"requirement_coverage_model_audits": [{"kept": True}]})
    calls = []

    @observe_evidence_factory
    def factory():
        calls.append(True)
        return pack

    trace = ExecutionTrace("final-pack-test", "task", "test")
    with trace.activate():
        returned = factory()
    assert returned is pack and calls == [True]
    row = next(row for row in _rows(trace) if row["name"] == "evidence.assemble")
    attrs = row["attributes"]
    assert attrs["evidence_payload_sha256"] == attrs["output_payload_sha256"] == payload_sha256(pack.to_artifact_payload())
    assert attrs["produced_member_access_fact_count"] == fact_count
    assert attrs["can_generate_patch"] is (not blocked)
    assert attrs["fact_delivery_status"] == "evidence_pack_assembled_model_delivery_unproven"


def test_assembly_projection_failure_preserves_original_return():
    original = object()
    trace = ExecutionTrace("unprojectable-pack", "task", "test")
    with trace.activate():
        assert observe_evidence_factory(lambda: original)() is original
    row = next(row for row in _rows(trace) if row["name"] == "evidence.assemble")
    assert row["attributes"]["observation_projection_status"] == "unavailable"
