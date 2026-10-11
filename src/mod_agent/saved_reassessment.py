"""Finish an interrupted source-reassessment merge using its recorded Query response."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.build.baseline_repair import validated_baseline_repair_observation
from src.mod_agent.evidence.optimization_policy import run_optimization_policy
from src.mod_agent.evidence import EvidencePack, RgLiveEvidenceProvider, model_view
from src.mod_agent.evidence.reassessment import (
    RequirementCoverageReassessmentFactory,
    initial_findings_reassessment_allowed,
)
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
    admit_requirement_projection_response,
)
from src.mod_agent.evidence.source_view import run_small_file_max_bytes


class _FindingsPreparedError(Exception):
    pass


def restored_source_observations(packet):
    """Rehydrate the bound intermediate source pool, not a semantic Evidence Artifact."""
    from src.mod_agent.evidence.models import _evidence_item_from_artifact_payload

    raw = packet["retrieved_evidence"]
    return EvidencePack(query=raw["query"], readiness="partial", can_generate_patch=False,
        items=tuple(_evidence_item_from_artifact_payload(row) for row in raw["items"]),
        retrieval_methods_used=tuple(raw["retrieval_methods_used"]), timing=raw["timing"],
        budget_summary=deepcopy(raw["budget_summary"]), trace_refs=tuple(raw["trace_refs"]))


def prepare_saved_query_finish(*, root, manifest, result, result_ref, references,
                              configuration_refs, configuration_blockers, budget, bodies,
                              feature_ref, feature, parsed, contract_version):
    """Verify all three completed turns and capture the next Findings without a model."""
    from src.mod_agent import initial_findings_continuation as continuation
    from src.mod_agent import local_entry, requirement_coverage_model
    from src.mod_agent.evidence import requirement_coverage_provider as provider
    from src.mod_agent.evidence.requirement_coverage import (
        materialize_requirement_coverage_projection,
    )

    baseline_observation = validated_baseline_repair_observation(manifest, root)
    if (contract_version not in (None, provider.FINDINGS_CONTRACT_VERSION)
            or not any(row.get("message") == "ValueError: PATCH_REASSESSMENT_EVIDENCE_ID_CONFLICT"
                       for row in result["blockers"])):
        raise ValueError("SAVED_REASSESSMENT_FAILURE_NOT_SELECTED")
    store = ArtifactStore(root / "a")
    evidence_refs = [row["artifact_ref"] for row in result["product_execution_result"]["outputs"]
                     if row["artifact_role"] == "evidence_pack"
                     and row["artifact_ref"]["path"] == result["artifacts"]["evidence_pack"]]
    if len(evidence_refs) != 1:
        raise ValueError("SAVED_REASSESSMENT_EVIDENCE_NOT_UNIQUE")
    ref = ArtifactRef(**evidence_refs[0])
    original = store.semantic_read_immutable(ref)["data"]
    if not initial_findings_reassessment_allowed(original, feature):
        raise ValueError("SAVED_REASSESSMENT_PARENT_NOT_ADMITTED")
    old = EvidencePack.from_artifact_payload(original)
    projection_request, projection_response = bodies[0]
    def replay_projection(role, payload, schema):
        payload = continuation._with_baseline_compilation_observation(payload, baseline_observation)
        if (role != "requirement_projection" or not requirement_coverage_model.requirement_coverage_messages_match(
                payload, projection_request["messages"])
                or projection_request["response_format"] != schema):
            raise ValueError("SAVED_REASSESSMENT_PROJECTION_CHANGED")
        return deepcopy(projection_response)
    projection = StructuredModelRequirementCoverageProvider(replay_projection, compress_findings_input=run_optimization_policy(root)["compress_findings_input"]).project(
        feature_data=feature, request=feature["user_request"])
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature, request=feature["user_request"], projection=projection)
    if any(old.requirement_coverage[k] != v for k, v in materialized.items()):
        raise ValueError("SAVED_REASSESSMENT_PROJECTION_CHANGED")
    def replay_findings(role, payload, schema):
        payload = continuation._with_baseline_compilation_observation(payload, baseline_observation)
        if (role != "requirement_findings" or not requirement_coverage_model.requirement_coverage_messages_match(
                payload, bodies[1][0]["messages"]) or schema != bodies[1][0]["response_format"]):
            raise ValueError("SAVED_REASSESSMENT_FINDINGS_CHANGED")
        return deepcopy(bodies[1][1])
    historical_findings_payload = json.loads(next(row["content"] for row in bodies[1][0]["messages"]
                                                 if row["role"] == "user"))
    # 为什么要有它：历史Findings按原policy重建，新补查可以用新协议但不能篡改原判断输入。
    original_semantic = StructuredModelRequirementCoverageProvider(replay_findings, compress_findings_input=run_optimization_policy(root)["compress_findings_input"],
        empty_evidence_policy=historical_findings_payload.get("empty_evidence_policy"),
        findings_planning_basis_policy=historical_findings_payload.get("findings_planning_basis_policy"),
        native_findings_contract=historical_findings_payload.get("native_findings_contract"))
    original_semantic.findings(materialized_projection=materialized, retrieved_pack=old,
                              request=feature["user_request"])
    feedback = {"initial_findings_reassessment": {
        "prior_evidence_hash": ref.artifact_hash,
        "findings": deepcopy(old.requirement_coverage["findings"]),
        "sufficiency": deepcopy(old.requirement_coverage["sufficiency"]),
    }, "interpretation_is_not_observation": True}
    search_root = (Path("generated_mods") / Path(manifest["target_source"]).name).as_posix()
    query_request, query_response = bodies[2]
    query_payload = json.loads(next(row["content"] for row in query_request["messages"]
                                   if row["role"] == "user"))
    contract = local_entry._build_request_upstream_query_contract(
        feature=feature, projection=materialized, old=old, feedback=feedback,
        upstream_search_root=search_root,
        contract_version=query_payload.get("query_contract_version", "requirement_queries_v1"),
        # 为什么要有它：历史能力描述只用于原wire重建，实际执行仍由当前已核验的augmentation绑定决定。
        tool_capabilities=query_payload.get("tool_capabilities"))
    contract["payload"] = continuation._with_baseline_compilation_observation(
        contract["payload"], baseline_observation)
    if (not requirement_coverage_model.requirement_coverage_messages_match(contract["payload"], query_request["messages"])
            or contract["schema"] != query_request["response_format"]):
        raise ValueError("SAVED_REASSESSMENT_QUERY_INPUT_CHANGED")
    admit_requirement_projection_response(query_response, schema=query_request["response_format"])
    captured = {}
    def capture(role, payload, schema):
        payload = continuation._with_baseline_compilation_observation(payload, baseline_observation)
        captured.update(role=role, payload=deepcopy(payload), schema=deepcopy(schema))
        raise _FindingsPreparedError()
    class CaptureProvider:
        def findings(self, **kwargs):
            captured["retrieved_evidence"] = kwargs["retrieved_pack"]
            return StructuredModelRequirementCoverageProvider(capture, compress_findings_input=run_optimization_policy(root)["compress_findings_input"],
                native_findings_contract=historical_findings_payload.get("native_findings_contract")).findings(**kwargs)
    state = {"artifact_hashes": {"evidence_pack": ref.artifact_hash}}
    factory = RequirementCoverageReassessmentFactory(artifact_store=store, workspace_root=root,
        search_root=search_root, source_provider=RgLiveEvidenceProvider(root,
            small_file_max_bytes=run_small_file_max_bytes(root),
            reuse_query_observations=run_optimization_policy(root)["reuse_query_observations"]),
        semantic_provider=CaptureProvider(), query_selector=lambda *_: deepcopy(query_response["queries"]))
    lineage = {"prior_evidence_ref": evidence_refs[0],
               "projection_identity": materialized["projection_identity"], "max_cycles": 1, "cycle": 1}
    try:
        factory._reassess(state, feature, old, feedback, initial_lineage=lineage)
    except _FindingsPreparedError:
        pass
    if captured.get("role") != "requirement_findings":
        raise ValueError("SAVED_REASSESSMENT_FINDINGS_NOT_PREPARED")
    combined = continuation._with_baseline_compilation_evidence(
        captured.pop("retrieved_evidence"), baseline_observation)
    combined = replace(combined, budget_summary={**combined.budget_summary,
        "saved_query_replay": {"response_ref": references[-1], "model_calls_performed": 0,
                               "original_consumed": budget["consumed"], "stage": "initial_findings_queries"}})
    turn = {**captured, "model_request": {**deepcopy(bodies[1][0]),
        "messages": [{"role": m.role, "content": m.content}
                     for m in requirement_coverage_model.requirement_coverage_messages(captured["payload"])],
        "response_format": captured["schema"]}}
    packet = {"run_id": manifest["run_id"], "request_id": manifest["request_id"],
        "feature_spec_ref": feature_ref, "parent_refs": references, "configuration_refs": configuration_refs,
        "execution_parent_result_ref": result_ref, "source_snapshot_sha256": manifest["source_snapshot_sha256"],
        "model_identity": manifest["local_model_identity"], "budget": budget,
        "budget_stage": "requirement_findings", "next_turn": turn,
        "saved_reassessment_query": {"request_sha256": continuation._digest(query_request),
            "response_ref": references[-1], "evidence_pack_ref": evidence_refs[0]},
        "source_retrieval_mode": manifest["source_retrieval_mode"],
        "evidence_optimization": run_optimization_policy(root),
        "python_runtime_identity": continuation._python_runtime_identity(),
        "model_limits": {"timeout_seconds": manifest["ollama_patch_generation_profile"]["timeout_seconds"],
            "context_window": parsed.ollama_context_window, "output_tokens": parsed.ollama_max_output_tokens},
        "admitted_projection": projection, "materialized_projection": materialized,
        "retrieved_evidence": combined.to_artifact_payload(),
        "prior_execution_timing": {"started_at": manifest.get("started_at"), "elapsed_ms": None,
                                   "new_time_window_granted": False},
        "correction_contract": {"historical_version": provider.FINDINGS_CONTRACT_VERSION,
            "selected_version": provider.FINDINGS_CONTRACT_VERSION,
            "historical_turn_sha256": continuation._digest(query_request),
            "selected_turn_sha256": continuation._digest(turn), "historical_turn": query_request,
            "revision_requires_new_approval": False}}
    from src.mod_agent import product_executor, request_patch_execution
    if historical_findings_payload.get("native_findings_contract") is not None:
        packet["native_findings_contract"] = historical_findings_payload["native_findings_contract"]
    from src.mod_agent.evidence import native_findings_contract, reassessment
    from src.mod_agent.workflow import graph
    packet["implementation_refs"] = [{"path": str(Path(p).resolve()), "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
        for p in (__file__, continuation.__file__, local_entry.__file__, reassessment.__file__,
                  provider.__file__, requirement_coverage_model.__file__, model_view.__file__, native_findings_contract.__file__, product_executor.__file__,
                  request_patch_execution.__file__, graph.__file__)]
    return {"entry": "initial-findings-continuation", "run_id": manifest["run_id"], "read_only": True,
        "status": "prepared_awaiting_authorization", "model_calls_performed": 0,
        "product_source_writes_performed": False, "graph_invoked": False,
        "budget": budget, "budget_stage": "requirement_findings", "blockers": configuration_blockers,
        "model_invocation_authorized": False, "current_live_model_identity_checked": False,
        "cause_chain": {"terminal_blockers": result["blockers"], "history_rewritten": False,
                        "saved_query_replay": packet["saved_reassessment_query"]},
        "continuation_input": packet, "continuation_input_sha256": continuation._input_digest(packet)}


def with_completed_findings_receipt(evidence, receipt):
    """Project the verified completion into revision input, preserving its stored Artifact."""
    projected = deepcopy(evidence)
    projected["budget_summary"]["reassessment"].update(
        findings_provider_invoked=True, findings_attempt_audit=[{
            "status": "accepted", "error_code": None,
            "origin": "saved_reassessment_completion", "completion_receipt": deepcopy(receipt)}],
        model_receipt_available=True)
    return projected


def verify_completed_saved_findings(*, prepared, parent, evidence, root):
    """Bind one completed post-merge Findings to its original request, Trace and budget."""
    from src.mod_agent import initial_findings_continuation as continuation
    from src.mod_agent.evidence import build_requirement_coverage_pack
    from src.mod_agent.evidence import requirement_coverage_provider as provider

    packet = prepared["continuation_input"]
    saved = packet["saved_reassessment_query"]
    segment = Path(parent["result_ref"]["path"]).parent
    manifest_ref, manifest = continuation._file(segment / "run_manifest.json")
    original_budget = packet["budget"]
    expected_budget = deepcopy(original_budget)
    for row in (expected_budget, expected_budget["by_stage"]["requirement_findings"]):
        row["consumed"] += 1
        if "remaining" in row:
            row["remaining"] -= 1
    if (parent.get("status") != "domain_blocked"
            or parent.get("request_id") != packet["request_id"]
            or parent.get("prior_model_call_count") != original_budget["consumed"]
            or parent.get("current_invocation_model_call_count") != 1
            or parent.get("model_call_budget") != expected_budget
            or parent.get("baseline_builds_performed") != 0
            or parent.get("projection_model_calls_performed") != 0
            or parent.get("cause_chain", {}).get("saved_query_replay") != saved
            or manifest.get("run_id") != packet["run_id"]
            or manifest.get("request_id") != packet["request_id"]
            or manifest.get("parent_result_ref") != packet["execution_parent_result_ref"]
            or manifest.get("model_call_budget") != expected_budget
            or manifest.get("model_call_count") != expected_budget["consumed"]
            or manifest.get("current_invocation_model_call_count") != 1):
        raise ValueError("SAVED_REASSESSMENT_COMPLETION_IDENTITY_INVALID")
    rows = [row for row in manifest["execution_observations"].values() if row["name"] == "model.request"]
    if len(rows) != 1:
        raise ValueError("SAVED_REASSESSMENT_COMPLETION_TRACE_INVALID")
    row = rows[0]
    attributes = row["attributes"]
    trace = manifest.get("execution_trace", {})
    if (row.get("status") != "completed" or row.get("trace_id") != trace.get("trace_id")
            or row.get("session_id") != trace.get("session_id")
            or trace.get("logical_request_id") != packet["request_id"]
            or parent.get("execution_trace", {}).get("trace_id") != row.get("trace_id")
            or attributes.get("model_role") != "requirement_findings"
            or attributes.get("model") != packet["model_identity"]["model"]
            or attributes.get("transport_started") is not True
            or attributes.get("response_complete") is not True
            or attributes.get("response_received") is not True
            or attributes.get("http_status") != 200):
        raise ValueError("SAVED_REASSESSMENT_COMPLETION_TRACE_INVALID")
    refs = attributes["local_detail_refs"]
    request_ref, request = continuation._bound_json(refs["request"], segment)
    response_ref, response = continuation._bound_json(refs["response"], segment)
    provider_ref, provider_request = continuation._bound_json(refs["provider_request"], segment)
    if (request != packet["next_turn"]["model_request"]
            or attributes.get("request_sha256") != request_ref["sha256"]
            or attributes.get("response_sha256") != response_ref["sha256"]
            or attributes.get("output_sha256") != response_ref["sha256"]
            or attributes.get("provider_request_sha256") != provider_ref["sha256"]
            or provider_request.get("model") != packet["model_identity"]["model"]
            or provider_request.get("messages") != request["messages"]
            or provider_request.get("format") != request["response_format"]
            or provider_request.get("stream") is not False
            or provider_request.get("options", {}).get("num_predict") != request["max_tokens"]
            or attributes.get("input_payload_sha256") != continuation._digest(
                json.loads(next(m["content"] for m in request["messages"] if m["role"] == "user")))):
        raise ValueError("SAVED_REASSESSMENT_COMPLETION_REQUEST_CHANGED")
    materialized = packet["materialized_projection"]
    _, indexes, all_indexes, deferred = provider._requirement_findings_model_relations(materialized)
    findings = provider._materialize_requirement_findings_response(response,
        schema=packet["next_turn"]["schema"], relation_indexes=indexes,
        coverage_schema_version=materialized["schema_version"])
    findings = provider._merge_deferred_requirement_findings(
        findings, all_relation_indexes=all_indexes, deferred_findings=deferred)
    expected = build_requirement_coverage_pack(query=evidence["query"], materialized_projection=materialized,
        retrieved_pack=restored_source_observations(packet), findings=findings).to_artifact_payload()
    observed = deepcopy(evidence)
    audit = observed["budget_summary"].pop("requirement_findings_attempt_audit", None)
    expected["budget_summary"].pop("requirement_findings_attempt_audit", None)
    if (not isinstance(audit, list) or len(audit) != 1
            or audit[0].get("status") != "accepted" or audit[0].get("error_code") is not None
            or continuation._input_digest({"retrieved_evidence": expected})
                != continuation._input_digest({"retrieved_evidence": observed})):
        raise ValueError("SAVED_REASSESSMENT_COMPLETION_EVIDENCE_CHANGED")
    receipt = {"parent_result_ref": deepcopy(parent["result_ref"]), "manifest_ref": manifest_ref,
        "request_ref": request_ref, "provider_request_ref": provider_ref, "response_ref": response_ref,
        "trace_id": row["trace_id"], "observation_id": row["id"],
        "budget_before": deepcopy(original_budget), "budget_after": deepcopy(expected_budget),
        "model_calls_performed": 0}
    return with_completed_findings_receipt(evidence, receipt), receipt
