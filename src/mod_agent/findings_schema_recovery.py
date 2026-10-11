"""Resume the observed empty-Evidence native-schema refusal after a verified Projection."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.evidence.optimization_policy import run_optimization_policy
from src.mod_agent.evidence import RgLiveEvidenceProvider, model_view, requirement_coverage_provider
from src.mod_agent.evidence.requirement_coverage import materialize_requirement_coverage_projection
from src.mod_agent.evidence.source_view import run_small_file_max_bytes
from src.mod_agent.requirement_coverage_model import requirement_coverage_messages_match


class _FindingsPreparedError(RuntimeError):
    pass


def schema_fix_binding(selection):
    """Bind the reviewed delta and the receiver's exact bytes, retaining the older freeze."""
    from src.mod_agent.request_interpretation_continuation import _checked_ref

    recovery = selection.get("findings_schema_recovery")
    if recovery is None:
        return None
    if not isinstance(recovery, dict) or set(recovery) != {
            "parent_result_ref", "parent_manifest_ref", "schema_fix_ref", "provider_ref"}:
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_SELECTION_INVALID")
    _, fix = _checked_ref(recovery["schema_fix_ref"])
    _, frozen = _checked_ref(fix["freeze"])
    provider = Path(requirement_coverage_provider.__file__).resolve(strict=True)
    reference = recovery["provider_ref"]
    if (set(reference) != {"path", "sha256"} or reference["path"] != str(provider)
            or hashlib.sha256(provider.read_bytes()).hexdigest() != reference["sha256"]):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_PROVIDER_CHANGED")
    rows = [row for row in frozen["files"] if Path(row["target_path"]).resolve() == provider]
    if len(rows) != 1 or rows[0]["before_sha256"] != fix["before_sha256"]:
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_FIX_INVALID")
    staged = Path(rows[0]["staged_after_path"]).read_bytes()
    if (hashlib.sha256(staged).hexdigest() != rows[0]["after_sha256"]
            or rows[0]["after_sha256"] != fix["after_sha256"]
            or staged.replace(b"\r\n", b"\n") != provider.read_bytes().replace(b"\r\n", b"\n")):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_FIX_INVALID")
    # The receiver's raw hash is authority; LF equality proves only the declared integration delta.
    # 为什么要有它：接收工具可能改变换行，但不能把暂存文件哈希冒充运行文件身份。
    return {"path": str(provider), "before_sha256": fix["before_sha256"],
            "after_sha256": reference["sha256"]}


def prepare_findings_schema_recovery(*, run_root, run_id, execution_config, allocation):
    """Prepare one new Findings request; no successful stage is dispatched again."""
    from src.mod_agent import initial_findings_continuation as continuation
    from src.mod_agent import local_entry, requirement_coverage_model
    from src.mod_agent.cli import build_parser
    from src.mod_agent.evidence import reassessment, requirement_coverage
    from src.mod_agent.request_interpretation_continuation import (
        _checked_ref,
        read_revision_selection,
    )
    from src.mod_agent.workflow import graph

    root = Path(run_root).resolve(strict=True)
    selected = read_revision_selection(allocation=allocation, run_root=root, execution_config=execution_config)
    selected.pop("historical_data")
    recovery = selected["selection"]["findings_schema_recovery"]
    parent_ref, parent = _checked_ref(recovery["parent_result_ref"])
    latest = continuation.read_initial_findings_execution(root)
    if latest is None or latest.get("result_ref") != parent_ref:
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_PARENT_CHANGED")
    old_revision = parent.get("request_interpretation_revision", {})
    if (old_revision.get("findings_schema_recovery") is not None
            or parent.get("status") != "partial" or parent.get("run_id") != run_id
            or parent.get("model_call_budget") != selected["prior_budget"]
            or parent.get("model_call_count") != selected["prior_budget"]["consumed"]
            or parent.get("current_invocation_model_call_count") != 2
            or parent.get("projection_model_calls_performed") != 1
            or parent.get("baseline_builds_performed") != 0
            or parent.get("actual_write_performed") is not False
            or parent.get("canonical_source_unchanged") is not True or parent.get("patch_execution_receipts")
            or old_revision.get("selected_artifact_refs") != selected["selected_artifact_refs"]
            or old_revision.get("derivation_ref") != selected["derivation_ref"]
            or old_revision.get("authorization_ref") != selected["authorization_ref"]):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_PARENT_UNSUPPORTED")
    failures = parent.get("blockers", [])
    prefix = "OllamaLLMError: [Ollama] API error (HTTP 400): "
    if (len(failures) != 1 or failures[0].get("code") != "PRODUCT_NODE_EXECUTION_FAILED"
            or failures[0].get("stage") != "retrieve_evidence_execution"
            or not failures[0].get("message", "").startswith(prefix)):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_FAILURE_UNSUPPORTED")
    error = json.loads(failures[0]["message"][len(prefix):])["error"]
    if (error.get("code") != 400 or error.get("type") != "invalid_request_error"
            or "#/properties/findings/items/properties/evidence_ids/items: enum must be a non-empty array" not in error.get("message", "")):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_FAILURE_UNSUPPORTED")
    manifest_ref, original = continuation._file(root / "run_manifest.json")
    segment = Path(parent_ref["path"]).parent
    trace_ref, trace = _checked_ref(recovery["parent_manifest_ref"])
    if Path(trace_ref["path"]).resolve() != segment / "run_manifest.json":
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_TRACE_INVALID")
    _, preceding = continuation._bound_json(trace["parent_result_ref"], root)
    expected = deepcopy(parent["model_call_budget"])
    expected["consumed"] -= 2
    for role in ("requirement_projection", "requirement_findings"):
        expected["by_stage"][role]["consumed"] -= 1
    if (trace.get("run_id") != run_id or trace.get("request_id") != original["request_id"]
            or parent.get("request_id") != original["request_id"]
            or trace.get("model_call_budget") != parent["model_call_budget"]
            or parent.get("prior_model_call_count") != preceding["model_call_budget"]["consumed"]
            or expected["consumed"] != preceding["model_call_budget"]["consumed"]
            or any(row["consumed"] != preceding["model_call_budget"]["by_stage"][key]["consumed"]
                   for key, row in expected["by_stage"].items())):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_BUDGET_CHANGED")
    rows = sorted((row for row in trace["execution_observations"].values() if row["name"] == "model.request"),
                  key=lambda row: row["started_at"])
    if [row["attributes"].get("model_role") for row in rows] != ["requirement_projection", "requirement_findings"]:
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_TRACE_INVALID")
    references = [manifest_ref, parent_ref, trace_ref]
    bodies = []
    for row, status in zip(rows, (200, 400)):
        attributes = row["attributes"]
        if (attributes.get("http_status") != status or attributes.get("transport_started") is not True
                or attributes.get("response_received") is not True or attributes.get("response_complete") is not True
                or attributes.get("model") != original["local_model_identity"]["model"]
                or row.get("trace_id") != trace["execution_trace"]["trace_id"]
                or row.get("status") != ("completed" if status == 200 else "failed")):
            raise ValueError("FINDINGS_SCHEMA_RECOVERY_TRACE_INVALID")
        values = {}
        for key, ref in attributes["local_detail_refs"].items():
            observed, values[key] = continuation._bound_json(ref, segment)
            if attributes.get(f"{key}_sha256") != observed["sha256"]:
                raise ValueError("FINDINGS_SCHEMA_RECOVERY_TRACE_INVALID")
            references.append(observed)
        if (set(values) != ({"request", "provider_request", "response"} if status == 200 else {"request", "provider_request"})
                or values["provider_request"]["messages"] != values["request"]["messages"]
                or values["provider_request"]["format"] != values["request"]["response_format"]
                or values["provider_request"]["model"] != original["model"]):
            raise ValueError("FINDINGS_SCHEMA_RECOVERY_TRACE_INVALID")
        bodies.append(values)
    projection_wire, findings_wire = bodies
    invalid_schema = findings_wire["request"]["response_format"]
    expected_schema = deepcopy(invalid_schema)
    domain = expected_schema["properties"]["findings"]["items"]["properties"]["evidence_ids"]
    if domain["items"].get("enum") != [] or "maxItems" in domain:
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_FAILURE_UNSUPPORTED")
    del domain["items"]["enum"]
    domain["maxItems"] = 0
    feature_ref = ArtifactRef(**old_revision["graph_artifact_refs"]["feature_spec"])
    feature = ArtifactStore(root / "a").semantic_read_immutable(feature_ref)["data"]
    if feature != selected["feature_data"]:
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_FEATURE_CHANGED")
    def replay(role, payload, schema):
        if (role != "requirement_projection" or schema != projection_wire["request"]["response_format"]
                or not requirement_coverage_messages_match(payload, projection_wire["request"]["messages"])):
            raise ValueError("FINDINGS_SCHEMA_RECOVERY_PROJECTION_CHANGED")
        return deepcopy(projection_wire["response"])
    semantic = requirement_coverage_provider.StructuredModelRequirementCoverageProvider(replay, compress_findings_input=run_optimization_policy(root)["compress_findings_input"])
    projection = semantic.project(feature_data=feature, request=feature["user_request"])
    materialized = materialize_requirement_coverage_projection(feature_data=feature,
        request=feature["user_request"], projection=projection)
    observations = list(trace["execution_observations"].values())
    projections = [row["attributes"] for row in observations if row["name"] == "requirements.projection"]
    retrievals = [row["attributes"] for row in observations if row["name"] == "evidence.retrieve"]
    if (len(projections) != 1 or len(retrievals) != 1 or projections[0].get("projection_fallback_used") is not False
            or projections[0]["materialized_projection_sha256"] != continuation._digest(materialized)
            or retrievals[0]["materialized_projection_sha256"] != continuation._digest(materialized)):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_PROJECTION_CHANGED")
    retrieved = RgLiveEvidenceProvider(root, small_file_max_bytes=run_small_file_max_bytes(root),
                reuse_query_observations=run_optimization_policy(root)["reuse_query_observations"]).collect_query_set(
        queries=tuple(dict(q) for q in materialized["queries"]),
        source_identity_query=feature["user_request"],
        search_root=f"generated_mods/{feature['target_mod']}", max_items=max(1, len(materialized["queries"])))
    if (retrieved.items or retrievals[0]["evidence_item_count"] != 0
            or retrieved.budget_summary["per_query_execution"] != retrievals[0]["query_execution"]):
        raise ValueError("FINDINGS_SCHEMA_RECOVERY_RETRIEVAL_CHANGED")
    contract = {}
    def capture(role, payload, schema):
        if (role != "requirement_findings" or schema != expected_schema
                or not requirement_coverage_messages_match(payload, findings_wire["request"]["messages"])):
            raise RuntimeError("FINDINGS_SCHEMA_RECOVERY_REPAIR_NOT_MATCHED")
        contract.update(role=role, payload=deepcopy(payload), schema=deepcopy(schema))
        raise _FindingsPreparedError()
    try:
        historical_findings_payload = json.loads(next(row["content"] for row in findings_wire["request"]["messages"]
                                                     if row["role"] == "user"))
        # 为什么要有它：这里只修原empty-enum故障，不能同时悄悄替换当时的零证据语义协议。
        requirement_coverage_provider.StructuredModelRequirementCoverageProvider(capture, compress_findings_input=run_optimization_policy(root)["compress_findings_input"],
            empty_evidence_policy=historical_findings_payload.get("empty_evidence_policy"),
            findings_planning_basis_policy=historical_findings_payload.get("findings_planning_basis_policy"),
            native_findings_contract=historical_findings_payload.get("native_findings_contract")).findings(
            materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    except _FindingsPreparedError:
        pass
    config_ref, configuration = continuation._file(execution_config)
    parsed = build_parser().parse_args(["run-request", *configuration["arguments"], "--", original["request"]])
    configuration_refs = [config_ref]
    for path in (parsed.settings, parsed.stage_model_call_limits, parsed.patch_worker_config, parsed.game_folder_build_binding):
        if path:
            p = Path(path).resolve(strict=True)
            configuration_refs.append({"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    proof = {**deepcopy(recovery), "manifest_ref": trace_ref, "projection_refs": deepcopy(rows[0]["attributes"]["local_detail_refs"]),
        "failed_findings_refs": deepcopy(rows[1]["attributes"]["local_detail_refs"]),
        "materialized_projection_sha256": continuation._digest(materialized), "http_400_consumption_retained": True}
    selected.update(parent_result_ref=parent_ref, historical_feature_ref=old_revision["historical_feature_ref"],
                    findings_schema_recovery=proof)
    packet = {"run_id": run_id, "request_id": original["request_id"], "feature_spec_ref": old_revision["graph_artifact_refs"]["feature_spec"],
        "parent_refs": references, "configuration_refs": configuration_refs, "execution_parent_result_ref": parent_ref,
        "source_snapshot_sha256": original["source_snapshot_sha256"], "model_identity": original["local_model_identity"],
        "budget": deepcopy(parent["model_call_budget"]), "budget_stage": "requirement_findings",
        "source_retrieval_mode": original["source_retrieval_mode"], "python_runtime_identity": continuation._python_runtime_identity(),
        "evidence_optimization": run_optimization_policy(root),
        "model_limits": {"timeout_seconds": original["ollama_patch_generation_profile"]["timeout_seconds"],
                         "context_window": parsed.ollama_context_window, "output_tokens": parsed.ollama_max_output_tokens},
        "next_turn": {"role": "requirement_findings", "query_model_contract": contract},
        "request_interpretation_revision": selected, "findings_schema_recovery": proof,
        "resume_mode": "accepted_findings_reassessment_revision", "materialized_projection": materialized,
        "retrieved_evidence": retrieved.to_artifact_payload(),
        "prior_execution_timing": {"started_at": trace.get("started_at"), "elapsed_ms": None, "new_time_window_granted": False},
        "correction_contract": {"historical_version": "3", "selected_version": "3", "historical_turn": findings_wire["request"],
            "historical_turn_sha256": continuation._digest(findings_wire["request"]),
            "selected_turn_sha256": continuation._digest(contract), "revision_requires_new_approval": False}}
    packet["implementation_refs"] = [{"path": str(Path(p).resolve()), "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
        for p in (__file__, continuation.__file__, local_entry.__file__, requirement_coverage_provider.__file__,
                  requirement_coverage.__file__, requirement_coverage_model.__file__, model_view.__file__, reassessment.__file__, graph.__file__)]
    return {"entry": "initial-findings-continuation", "run_id": run_id, "read_only": True,
        "status": "prepared_awaiting_authorization", "model_calls_performed": 0, "graph_invoked": False,
        "product_source_writes_performed": False, "budget": packet["budget"], "budget_stage": "requirement_findings",
        "blockers": [], "cause_chain": {"terminal_blockers": deepcopy(failures), "history_rewritten": False,
            "findings_schema_recovery": proof}, "continuation_input": packet,
        "continuation_input_sha256": continuation._input_digest(packet)}
