"""Upstream Cloud projections and explicitly selected local bindings; no network."""
import hashlib
import json

import pytest

from src.observability.patch_langfuse import PatchLangfuseError
from src.observability.patch_langfuse_query import join_local_journal, summarize_execution
from src.observability.patch_live_langfuse import build_patch_live_otlp


TRACE = "a" * 32


def local_row(identity, name, *, kind="span", attributes=None, start=0, end=1):
    return {"id": f"{identity:016x}", "parent_id": None if identity == 0 else "0" * 15 + "f",
        "trace_id": TRACE, "session_id": "logical-task-1", "environment": "local",
        "name": name, "kind": kind, "status": "completed",
        "started_at": f"2026-09-13T01:00:{start:02d}+00:00",
        "finished_at": f"2026-09-13T01:00:{end:02d}+00:00", "elapsed_ms": (end-start) * 1000,
        "attributes": attributes or {}}


def cloud_row(local):
    span = build_patch_live_otlp(local)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    attrs = {item["key"]: next(iter(item["value"].values())) for item in span["attributes"]}
    meta = {}
    for key, value in attrs.items():
        if not key.startswith("langfuse.observation.metadata."):
            continue
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        meta[key.removeprefix("langfuse.observation.metadata.")] = value
    return {"id": span["spanId"], "traceId": TRACE, "parentObservationId": span.get("parentSpanId"),
        "type": local["kind"].upper(), "name": local["name"], "isRootObservation": local["parent_id"] is None,
        "level": attrs["langfuse.observation.level"], "statusMessage": attrs["langfuse.observation.status_message"],
        "startTime": local["started_at"], "endTime": local["finished_at"], "metadata": meta}


def material(*, excerpt="b" * 64, source="c" * 64):
    return {"evidence_id": "SOURCE_IDENTIFIER_PRIVATE", "excerpt_sha256": excerpt,
            "source_hash": source, "source_type": "target_source"}


def test_upstream_projection_exports_fixed_decision_facts_but_never_free_text_or_paths():
    local = local_row(1, "requirements.coverage", attributes={
        "model_role": "requirement_findings", "relationship_counts": {"support": 1, "conflict": 0, "missing": 2,
            "SECRET_EXTRA": 12}, "selected_evidence_ids": ["SOURCE_IDENTIFIER_PRIVATE"], "unresolved_gap_count": 2,
        "decision_summary_origin": "deterministic_structured_result", "decision_summary": "SECRET_MODEL_REASON",
        "reason_status": "model_rationale_local_only", "rationale": "SECRET_MODEL_REASON",
        "consumed_materials": [{**material(), "source_path": "C:/SECRET_SOURCE/subject.cs", "excerpt": "SECRET_BODY"}],
        "local_detail_refs": {"request": {"path": "C:/SECRET_SOURCE/request.json", "sha256": "d" * 64},
                              "response": {"path": "C:/SECRET_SOURCE/response.json", "sha256": "e" * 64}}})
    cloud = cloud_row(local)
    text = json.dumps(cloud)
    assert "SECRET" not in text and "SOURCE_IDENTIFIER_PRIVATE" not in text and "C:/" not in text
    meta = cloud["metadata"]
    assert meta["relationship_counts"] == {"support": 1, "conflict": 0, "missing": 2}
    assert meta["decision_summary_origin"] == "system_fact_from_recorded_structure"
    assert meta["decision_claim_origin"] == "model_claim_requires_validation"
    assert "支持1" in meta["decision_summary"] and "缺证2" in meta["decision_summary"]
    assert meta["local_detail_refs"] == {"request": {"sha256": "d" * 64}, "response": {"sha256": "e" * 64}}


def test_findings_consumption_joins_exact_excerpt_without_inventing_input_source_hash():
    producer = cloud_row(local_row(1, "evidence.retrieve", attributes={"produced_materials": [material()]}))
    request = cloud_row(local_row(2, "model.request", start=2, end=4))
    supplied = material(source=None)
    generation = cloud_row(local_row(3, "requirements.findings", kind="generation", start=2, end=4,
        attributes={"model_role": "requirement_findings", "transport_started": True,
                    "response_received": True, "response_origin": "live_provider_response", "http_status": 200,
                    "input_payload_sha256": "d" * 64, "consumed_materials": [supplied]}))
    result = summarize_execution(TRACE, [producer, request, generation])
    assert result["generation_count"] == result["model_request_observations"] == 1
    link = result["material_consumption_links"][0]
    assert link["binding"] == "matched_excerpt_in_responded_request"
    assert link["delivery_status"] == "provider_response_received"
    assert link["source_observation_ids"] == [producer["id"]]
    assert link["input_source_hash"] is None
    assert result["generations"][0]["usage"] is None
    assert result["generations"][0]["cost"] is None


@pytest.mark.parametrize("changed", [material(excerpt="e" * 64), material(source="d" * 64)])
def test_same_evidence_id_with_changed_bytes_never_counts_as_matching_material(changed):
    result = summarize_execution(TRACE, [
        cloud_row(local_row(1, "evidence.retrieve", attributes={"produced_materials": [material()]})),
        cloud_row(local_row(2, "planning.select", kind="generation", start=2, end=4,
            attributes={"consumed_materials": [changed], "transport_started": True}))])
    assert result["material_consumption_links"][0]["binding"] == "material_origin_unresolved"


def test_assembled_material_is_not_actual_model_consumption_without_transport_proof():
    result = summarize_execution(TRACE, [
        cloud_row(local_row(1, "evidence.retrieve", attributes={"produced_materials": [material()]})),
        cloud_row(local_row(2, "planning.decision", start=1, end=4,
            attributes={"consumed_materials": [material()], "input_payload_sha256": "d" * 64})),
        cloud_row(local_row(3, "planning.select", kind="generation", start=2, end=4,
            attributes={"input_payload_sha256": "d" * 64, "transport_started": False}))])
    assert result["material_consumption_links"][0]["binding"] == "assembled_material_only"


def test_transport_timeout_keeps_input_binding_but_does_not_claim_server_received_material():
    rows = [cloud_row(local_row(1, "evidence.retrieve", attributes={"produced_materials": [material()]})),
        cloud_row(local_row(2, "planning.select", kind="generation", start=2, end=4,
            attributes={"consumed_materials": [material()], "input_payload_sha256": "d" * 64,
                        "transport_started": True, "response_received": False, "exception_type": "ReadTimeout"}))]
    link = summarize_execution(TRACE, rows)["material_consumption_links"][0]
    assert link["binding"] == "matched_excerpt_in_transport_attempt"
    assert link["delivery_status"] == "transport_attempted"


def test_empty_result_missing_records_and_returned_but_omitted_are_distinct_facts():
    empty = cloud_row(local_row(1, "evidence.source_query", attributes={"produced_materials": []}))
    returned = cloud_row(local_row(2, "evidence.retrieve", attributes={"produced_materials": [material()]}))
    omitted = cloud_row(local_row(3, "planning.select", kind="generation", start=2, end=4,
        attributes={"consumed_materials": [], "transport_started": True}))
    unknown = cloud_row(local_row(4, "requirements.findings", kind="generation", start=5, end=6,
        attributes={"model_role": "requirement_findings", "transport_started": True}))
    facts = summarize_execution(TRACE, [empty, returned, omitted, unknown])["evidence_diagnostics"]
    assert {fact["fact"] for fact in facts} == {"recorded_material_result_empty",
        "returned_material_not_in_recorded_input", "input_material_binding_unknown"}
    assert not any("root_cause" in fact for fact in facts)


def test_explicit_retrieval_boundaries_and_route_decision_survive_cloud_mapping():
    rows = [cloud_row(local_row(1, "evidence.source_query", attributes={"retrieval_status": "source_root_missing"})),
        cloud_row(local_row(2, "evidence.source_query", attributes={"retrieval_status": "no_matches", "tool_dispatch_performed": True})),
        cloud_row(local_row(3, "requirements.coverage", attributes={"decision": "patch_blocked",
            "can_generate_patch": False, "readiness": "insufficient"}))]
    result = summarize_execution(TRACE, rows)
    assert {item["fact"] for item in result["evidence_diagnostics"]} == {"source_root_missing", "no_matches"}
    assert all(row["level"] == "WARNING" for row in rows)
    assert any(item["facts"].get("decision") == "patch_blocked" for item in result["upstream_decisions"])
    assert "确定性判断阻止进入Patch" in rows[2]["metadata"]["decision_summary"]


def test_product_scope_sets_consistent_native_trace_name_and_body_failures_are_visible():
    row = local_row(1, "requirements.project", kind="generation", attributes={
        "trace_scope": "product_execution", "local_body_status": "request_write_failed", "decision": "SECRET_BAD_VALUE"})
    payload = build_patch_live_otlp(row)
    attributes = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
    assert {"key": "langfuse.trace.name", "value": {"stringValue": "Product execution"}} in attributes
    assert "SECRET" not in json.dumps(payload)
    assert cloud_row(row)["metadata"]["local_body_status"] == "request_write_failed"


def test_route_selection_is_readable_but_does_not_invent_a_next_node_execution():
    row = cloud_row(local_row(1, "workflow.route", kind="event", attributes={
        "from_node": "collect_evidence", "selected_route": "blocked", "selected_next_node": "__end__",
        "route_selector": "_route_after_evidence", "route_input_sha256": "d" * 64,
        "route_input_summary_scope": "structured_selector_fields", "route_output_summary_status": "unavailable",
        "route_inputs": {"source_path": "PRIVATE_PATH", "rationale": "PRIVATE_REASON"}}))
    result = summarize_execution(TRACE, [row])
    assert result["observed_operations"] == ["workflow.route"]
    decision = result["upstream_decisions"][0]["facts"]
    assert decision["selected_next_node"] == "__end__"
    assert decision["route_selector"] == "_route_after_evidence"
    assert decision["route_output_summary_status"] == "unavailable"
    assert "后续是否执行另查" in decision["decision_summary"]
    assert "PRIVATE" not in json.dumps(result)


def test_source_admission_failure_is_queryable_before_any_graph_or_model_call():
    row = local_row(1, "source.admission", attributes={"execution_phase": "pre_graph",
        "source_directory_exists": False, "project_file_discovered": False,
        "failure_code": "SOURCE_PROJECT_MATERIAL_UNAVAILABLE", "exception_type": "LocalEntryError"})
    row["status"] = "failed"
    result = summarize_execution(TRACE, [cloud_row(row)])
    assert result["generation_count"] == 0
    assert result["observed_operations"] == ["source.admission"]
    assert result["execution_tree"][0]["facts"]["execution_phase"] == "pre_graph"
    assert result["evidence_diagnostics"][0]["fact"] == "source_project_material_unavailable"
    assert result["usage"]["measured_totals"] is None


def test_failure_report_and_terminal_record_join_locally_without_cloud_paths(tmp_path):
    report = tmp_path / "failure.json"
    report.write_text('{"message":"PRIVATE_FAILURE_BODY"}', encoding="utf-8")
    reference = {"path": str(report), "sha256": hashlib.sha256(report.read_bytes()).hexdigest()}
    failure = local_row(1, "preflight.failure", kind="event", attributes={
        "failure_stage": "baseline_build", "exception_type": "LocalEntryError",
        "timing_scope": "failure_decision_record_only", "local_detail_refs": {"failure": reference}})
    root = local_row(0, "product.execution", attributes={"trace_scope": "product_execution",
        "terminal_stage": "baseline_build", "terminal_record_ref": reference})
    cloud = [cloud_row(row) for row in (root, failure)]
    assert "PRIVATE_FAILURE_BODY" not in json.dumps(cloud) and str(tmp_path) not in json.dumps(cloud)
    journal = tmp_path / "run_manifest.json"
    journal.write_text(json.dumps({"execution_observations": {row["id"]: row for row in (root, failure)}}), encoding="utf-8")
    summary = join_local_journal(summarize_execution(TRACE, cloud), journal,
        hashlib.sha256(journal.read_bytes()).hexdigest(), artifact_roots=[tmp_path])
    roles = {detail["role"]: detail["file_binding"] for observation in summary["local_evidence"]["observations"]
             for detail in observation["details"]}
    assert roles == {"failure": "verified_bytes", "terminal_record": "verified_bytes"}
    assert any(row["facts"].get("failure_stage") == "baseline_build" for row in summary["execution_tree"])


def test_enriched_api_facts_and_final_pack_keep_identity_without_claiming_model_delivery():
    enriched = local_row(1, "evidence.member_access_enrich", attributes={
        "input_payload_sha256": "a" * 64, "output_payload_sha256": "b" * 64,
        "input_member_access_count": 1, "output_member_access_count": 2,
        "added_member_access_count": 1, "removed_member_access_count": 0,
        "input_member_access_facts_sha256": "c" * 64, "output_member_access_facts_sha256": "d" * 64,
        "produced_materials": [material()], "fact_delivery_status": "evidence_pack_enriched_model_delivery_unproven",
        "verified_member_accesses": [{"source": "PRIVATE_API_BODY"}]})
    assembled = local_row(2, "evidence.assemble", attributes={
        "evidence_payload_sha256": "e" * 64, "output_payload_sha256": "e" * 64,
        "produced_materials": [material()], "produced_member_access_fact_count": 2,
        "produced_member_access_facts_sha256": "d" * 64,
        "fact_delivery_status": "evidence_pack_assembled_model_delivery_unproven",
        "readiness": "sufficient", "can_generate_patch": True})
    result = summarize_execution(TRACE, [cloud_row(enriched), cloud_row(assembled)])
    facts = {row["name"]: row["facts"] for row in result["execution_tree"]}
    assert facts["evidence.member_access_enrich"]["output_member_access_facts_sha256"] == "d" * 64
    assert facts["evidence.member_access_enrich"]["removed_member_access_count"] == 0
    assert facts["evidence.assemble"]["produced_member_access_fact_count"] == 2
    assert facts["evidence.assemble"]["evidence_payload_sha256"] == "e" * 64
    assert facts["evidence.assemble"]["fact_delivery_status"] == "evidence_pack_assembled_model_delivery_unproven"
    assert "整包API事实是否传给模型尚未证明" in facts["evidence.assemble"]["decision_summary"]
    assert result["material_consumption_links"] == [] and result["generation_count"] == 0
    assert "PRIVATE_API_BODY" not in json.dumps(result)


def bound_journal(tmp_path):
    body = tmp_path / "request.json"
    body.write_text('{"prompt":"PRIVATE_BODY"}', encoding="utf-8")
    digest = hashlib.sha256(body.read_bytes()).hexdigest()
    row = local_row(1, "planning.select", kind="generation", attributes={"model_role": "planning",
        "transport_started": True, "input_payload_sha256": "d" * 64,
        "local_detail_refs": {"request": {"path": str(body), "sha256": digest}}})
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps({"execution_observations": {row["id"]: row}}), encoding="utf-8")
    summary = summarize_execution(TRACE, [cloud_row(row)])
    return body, journal, hashlib.sha256(journal.read_bytes()).hexdigest(), summary


def test_local_join_checks_journal_observation_and_file_bytes_without_returning_body(tmp_path):
    body, journal, digest, summary = bound_journal(tmp_path)
    joined = join_local_journal(summary, journal, digest, artifact_roots=[tmp_path])
    evidence = joined["local_evidence"]["observations"][0]
    assert evidence["binding"] == "verified_journal_and_observation_mapping"
    assert evidence["details"][0]["file_binding"] == "verified_bytes"
    assert evidence["details"][0]["path"] == str(body.resolve())
    assert "PRIVATE_BODY" not in json.dumps(joined)
    assert "local_evidence" not in summary  # The Cloud-only value is not mutated.


def test_local_join_rejects_wrong_journal_and_does_not_follow_mismatching_cloud_row(tmp_path):
    _, journal, digest, summary = bound_journal(tmp_path)
    with pytest.raises(PatchLangfuseError, match="LOCAL_JOURNAL_HASH_MISMATCH"):
        join_local_journal(summary, journal, "f" * 64, artifact_roots=[tmp_path])
    summary["execution_tree"][0]["facts"]["input_payload_sha256"] = "e" * 64
    entry = join_local_journal(summary, journal, digest, artifact_roots=[tmp_path])["local_evidence"]["observations"][0]
    assert entry["binding"] == "local_cloud_observation_mismatch" and entry["details"] == []


def test_local_body_hash_and_explicit_allowed_root_are_independent_checks(tmp_path):
    body, journal, digest, summary = bound_journal(tmp_path)
    without_root = join_local_journal(summary, journal, digest)["local_evidence"]["observations"][0]
    assert without_root["details"][0]["file_binding"] == "not_checked_no_allowed_root"
    other = tmp_path / "other"
    other.mkdir()
    outside = join_local_journal(summary, journal, digest, artifact_roots=[other])["local_evidence"]["observations"][0]
    assert outside["details"][0]["file_binding"] == "outside_explicit_artifact_roots"
    body.write_text("changed", encoding="utf-8")
    modified = join_local_journal(summary, journal, digest, artifact_roots=[tmp_path])["local_evidence"]["observations"][0]
    assert modified["details"][0]["file_binding"] == "file_hash_mismatch"


def test_local_join_accepts_observed_cloud_millisecond_truncation_but_not_different_time(tmp_path):
    _, journal, _, summary = bound_journal(tmp_path)
    document = json.loads(journal.read_text(encoding="utf-8"))
    row = next(iter(document["execution_observations"].values()))
    row["started_at"] = "2026-09-13T01:00:00.000111+00:00"
    row["finished_at"] = "2026-09-13T01:00:01.000111+00:00"
    journal.write_text(json.dumps(document), encoding="utf-8")
    digest = hashlib.sha256(journal.read_bytes()).hexdigest()
    joined = join_local_journal(summary, journal, digest)
    assert joined["local_evidence"]["observations"][0]["binding"] == "verified_journal_and_observation_mapping"
    summary["execution_tree"][0]["start_time"] = "2026-09-13T01:00:00.001Z"
    joined = join_local_journal(summary, journal, digest)
    assert joined["local_evidence"]["observations"][0]["binding"] == "local_cloud_observation_mismatch"
