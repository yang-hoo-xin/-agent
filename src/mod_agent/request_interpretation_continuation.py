"""Consume one approved corrected derivation in the existing task continuation."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
)
from src.mod_agent.planning import FeatureSpecBuilder, ModPlanningBriefBuilder, RequestPlanner
from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256


class _ProjectionPreparedError(RuntimeError):
    pass


def _checked_ref(reference):
    from src.mod_agent.initial_findings_continuation import _file
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ValueError("REQUEST_INTERPRETATION_REVISION_REF_INVALID")
    observed, value = _file(reference["path"])
    if observed != reference:
        raise ValueError("REQUEST_INTERPRETATION_REVISION_REF_CHANGED")
    return observed, value


def read_revision_selection(*, allocation, run_root, execution_config):
    """Validate selection, retained business authorization and frozen semantic owners."""
    from src.mod_agent.initial_findings_continuation import _budget, _digest, _file

    root = Path(run_root).resolve(strict=True)
    config_ref, configuration = _file(execution_config)
    _, manifest = _file(root / "run_manifest.json")
    selection = allocation.get("request_interpretation_revision")
    required = {"store_root", "derivation_ref", "decision_ref", "frozen_files_ref"}
    if (not isinstance(selection, dict) or not required.issubset(selection)
            or set(selection) - required - {"findings_schema_recovery"}
            or allocation.get("resume_mode") != "accepted_findings_reassessment_revision"
            or allocation.get("initial_reassessment_max_cycles", 1) != 1):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_SELECTION_INVALID")
    derivation_ref, derivation = _checked_ref(selection["derivation_ref"])
    decision_ref, decision = _checked_ref(selection["decision_ref"])
    frozen_ref, frozen = _checked_ref(selection["frozen_files_ref"])
    if frozen.get("shared_production_files_frozen") is not True or not frozen.get("files"):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_CODE_NOT_FROZEN")
    from src.mod_agent.findings_schema_recovery import schema_fix_binding
    schema_fix = schema_fix_binding(selection)
    for reference in frozen["files"]:
        path = Path(reference["path"]).resolve(strict=True)
        observed_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        fixed_provider = (schema_fix is not None and str(path) == schema_fix["path"]
            and reference["sha256"] == schema_fix["before_sha256"] and observed_hash == schema_fix["after_sha256"])
        if observed_hash != reference["sha256"] and not fixed_provider:
            raise ValueError("REQUEST_INTERPRETATION_REVISION_CODE_CHANGED")
    prior = _budget(decision["prior_budget"])
    from src.mod_agent.model_call_budget import STAGE_AND_TOTAL, TASK_TOTAL_ONLY
    policy = allocation.get("model_call_budget_policy", STAGE_AND_TOTAL)
    limits = allocation.get("stage_model_call_limits")
    valid_limits = (decision.get("model_call_budget_policy") == TASK_TOTAL_ONLY if policy == TASK_TOTAL_ONLY else
        isinstance(limits, dict) and decision.get("selected_stage_model_call_limits") == limits
        and set(limits) == set(prior["by_stage"])
        and all(type(value) is int and value >= max(1, prior["by_stage"][key]["consumed"])
                for key, value in limits.items()) and sum(limits.values()) == prior["maximum"])
    if (decision.get("run_id") != manifest["run_id"]
            or decision.get("task_maximum") != prior["maximum"]
            or decision.get("prior_consumed") != prior["consumed"]
            or policy not in {STAGE_AND_TOTAL, TASK_TOTAL_ONLY} or not valid_limits
            or any(decision.get(key) is not False for key in (
                "refund_performed", "history_moved_between_stages", "user_request_changed",
                "model_changed", "new_external_or_runtime_effects_authorized"))):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_DECISION_INVALID")
    authorization_ref, authorization = _file(decision["original_authorization_ref"])
    scope_ref, approval = _file(authorization["scope_file"])
    scope = approval["scope"]
    identity = manifest["local_model_identity"]
    if (authorization.get("approved") is not True
            or authorization.get("scope_sha256") != _digest(scope)
            or approval.get("scope_sha256") != authorization["scope_sha256"]
            or scope.get("run_id") != manifest["run_id"]
            or scope.get("request_id") != manifest["request_id"]
            or scope.get("task_model_call_limit") != prior["maximum"]
            or config_ref not in scope.get("bindings", [])
            or Path(scope["run_root"]).resolve() != root
            or Path(scope["target_project"]).resolve() != Path(manifest["target_source"]).resolve()
            or scope.get("source_snapshot_sha256") != manifest["source_snapshot_sha256"]
            or scope["model"].get("name") != identity["model"]
            or scope["model"].get("digest") != identity["digest"]
            or scope["model"].get("base_url") != identity["base_url"]
            or authorization.get("model_digest") != identity["digest"]
            or allocation["max_execution_seconds"] * 1000 > scope["dsh_command_timeout_ms"]):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_AUTHORIZATION_CHANGED")
    from src.mod_agent.cli import build_parser
    parsed = build_parser().parse_args(["run-request", *configuration["arguments"], "--", manifest["request"]])
    for path in (parsed.settings, parsed.stage_model_call_limits, parsed.patch_worker_config):
        if path is not None:
            selected_path = Path(path).resolve(strict=True)
            reference = {"path": str(selected_path), "sha256": hashlib.sha256(selected_path.read_bytes()).hexdigest()}
            if reference not in scope["bindings"]:
                raise ValueError("REQUEST_INTERPRETATION_REVISION_AUTHORIZATION_CHANGED")
    if (scope["model"].get("context_window") != parsed.ollama_context_window
            or scope["model"].get("max_output_tokens") != parsed.ollama_max_output_tokens
            or scope["model"].get("request_timeout_seconds") != parsed.ollama_timeout_seconds):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_AUTHORIZATION_CHANGED")
    source = Path(manifest["target_source"])
    for current in (source, root / "generated_mods" / source.name):
        if source_snapshot_sha256(source_snapshot(current)) != manifest["source_snapshot_sha256"]:
            raise ValueError("INITIAL_FINDINGS_SOURCE_CHANGED")
    if (derivation.get("schema_version") != "request_interpretation_revision_v2"
            or derivation.get("historical_run_id") != manifest["run_id"]
            or derivation.get("unchanged_user_request") is not True
            or derivation.get("model_calls_performed") != 0
            or derivation.get("product_run_started") is not False):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_DERIVATION_INVALID")
    roles = ("request_planning_report", "mod_planning_brief", "feature_spec")
    if set(derivation["historical_sources"]) != set(roles) or set(derivation["corrected_artifacts"]) != set(roles):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_DERIVATION_INVALID")
    historical = {}
    for role in roles:
        _, envelope = _checked_ref(derivation["historical_sources"][role])
        reference = ArtifactRef(feature_id=envelope["feature_id"], artifact_type=role,
            path=derivation["historical_sources"][role]["path"], artifact_hash=envelope["artifact_hash"])
        historical[role] = ArtifactStore(root / "a").semantic_read_immutable(reference)["data"]
    store = ArtifactStore(selection["store_root"])
    corrected, corrected_refs = {}, {}
    for role in roles:
        record = derivation["corrected_artifacts"][role]
        reference = ArtifactRef(feature_id=historical[role]["feature_id"], artifact_type=role, **record)
        corrected[role] = store.semantic_read_immutable(reference)["data"]
        corrected_refs[role] = {"feature_id": reference.feature_id, "artifact_type": role,
            "path": reference.path, "artifact_hash": reference.artifact_hash}
    feature = corrected["feature_spec"]
    if (feature["user_request"] != manifest["request"]
            or historical["feature_spec"]["user_request"] != manifest["request"]
            or feature["target_mod"] != source.name
            or feature.get("request_interpretation", {}).get("schema_version") != "request_interpretation_v2"
            or historical["feature_spec"].get("request_interpretation", {}).get("schema_version") == "request_interpretation_v2"):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_REQUEST_CHANGED")
    plan = RequestPlanner().plan(manifest["request"], target_mod=source.name)
    brief = ModPlanningBriefBuilder().build(plan, target_game="gtfo").to_artifact_payload()
    current = {"request_planning_report": plan.to_artifact_payload(), "mod_planning_brief": brief,
               "feature_spec": FeatureSpecBuilder().build(plan, planning_brief=brief).to_artifact_payload()}
    if current != corrected:
        raise ValueError("REQUEST_INTERPRETATION_REVISION_DERIVATION_CHANGED")
    progress_parent = None
    if "parent_result_ref" in decision or "parent_manifest_ref" in decision:
        result_ref, _ = _checked_ref(decision["parent_result_ref"])
        manifest_ref, _ = _checked_ref(decision["parent_manifest_ref"])
        progress_parent = {"result_ref": result_ref, "manifest_ref": manifest_ref}
    return {"selection_sha256": _digest(selection), "selection": deepcopy(selection),
        "progress_parent": progress_parent,
        "derivation_ref": derivation_ref, "decision_ref": decision_ref, "frozen_files_ref": frozen_ref,
        "authorization_ref": authorization_ref, "authorization_scope_ref": scope_ref,
        "historical_sources": deepcopy(derivation["historical_sources"]),
        "selected_artifact_refs": corrected_refs, "feature_data": feature,
        "prior_budget": prior, "historical_data": historical}


def prepare_accepted_findings_progress(*, run_root, run_id, execution_config, allocation):
    """Reuse an accepted current pack at the existing initial reassessment boundary."""
    from src.mod_agent import initial_findings_continuation as continuation
    from src.mod_agent.evidence import EvidencePack, build_requirement_coverage_pack
    from src.mod_agent.evidence import requirement_coverage_provider as provider
    from src.mod_agent.evidence.reassessment import initial_findings_reassessment_allowed

    root = Path(run_root).resolve(strict=True)
    selected = read_revision_selection(allocation=allocation, run_root=root, execution_config=execution_config)
    refs = selected["progress_parent"]
    parent_ref, parent = _checked_ref(refs["result_ref"])
    manifest_ref, manifest = _checked_ref(refs["manifest_ref"])
    latest = continuation.read_initial_findings_execution(root)
    if (latest is None or latest.get("result_ref") != parent_ref
            or Path(manifest_ref["path"]).parent != Path(parent_ref["path"]).parent
            or parent.get("run_id") != run_id or manifest.get("run_id") != run_id
            or parent.get("model_call_budget") != selected["prior_budget"]
            or manifest.get("model_call_budget") != selected["prior_budget"]
            or parent.get("request_interpretation_revision", {}).get("selected_artifact_refs") != selected["selected_artifact_refs"]):
        raise ValueError("ACCEPTED_FINDINGS_PROGRESS_PARENT_CHANGED")
    outputs = {row["artifact_role"]: row["artifact_ref"] for row in parent["product_execution_result"]["outputs"]}
    evidence_ref = outputs["evidence_pack"]
    if evidence_ref["path"] != parent["artifacts"]["evidence_pack"]:
        raise ValueError("ACCEPTED_FINDINGS_PROGRESS_EVIDENCE_CHANGED")
    store = ArtifactStore(root / "a")
    evidence = store.semantic_read_immutable(ArtifactRef(**evidence_ref))["data"]
    feature = store.semantic_read_immutable(ArtifactRef(**outputs["feature_spec"]))["data"]
    if feature != selected["feature_data"] or not initial_findings_reassessment_allowed(evidence, feature):
        raise ValueError("INITIAL_FINDINGS_ACCEPTED_REASSESSMENT_NOT_ADMITTED")
    audit = evidence["budget_summary"]["requirement_findings_attempt_audit"]
    coverages = [row["attributes"] for row in manifest["execution_observations"].values()
                 if row["name"] == "requirements.coverage"]
    calls = sorted((row for row in manifest["execution_observations"].values() if row["name"] == "model.request"),
                   key=lambda row: row["started_at"])
    if (len(coverages) != 1 or coverages[0].get("requirement_findings_attempt_audit") != audit
            or len(calls) != parent["current_invocation_model_call_count"]
            or not calls or any(row["attributes"].get("model_role") not in {
                "requirement_findings", "requirement_findings_correction"} for row in calls)
            or any(row["attributes"].get("http_status") != 200
                   or row["attributes"].get("response_complete") is not True for row in calls)):
        raise ValueError("ACCEPTED_FINDINGS_PROGRESS_TRACE_INVALID")
    body_refs = []
    response = None
    schema = None
    for row in calls:
        values = {}
        for kind, reference in row["attributes"]["local_detail_refs"].items():
            observed, values[kind] = continuation._bound_json(reference, Path(parent_ref["path"]).parent)
            body_refs.append(observed)
        if continuation._digest(values["request"]["response_format"]) != continuation._digest(values["provider_request"]["format"]):
            raise ValueError("ACCEPTED_FINDINGS_PROGRESS_TRACE_INVALID")
        response, schema = values["response"], values["request"]["response_format"]
    pack = EvidencePack.from_artifact_payload(evidence)
    materialized = {key: deepcopy(pack.requirement_coverage[key]) for key in (
        "schema_version", "feature_spec_identity", "request_identity", "projection_identity",
        "input_obligations", "input_dispositions", "requirements", "relations", "queries")}
    _, indexes, all_indexes, deferred = provider._requirement_findings_model_relations(materialized)
    findings = provider._materialize_requirement_findings_response(response, schema=schema,
        relation_indexes=indexes, coverage_schema_version=materialized["schema_version"])
    findings = provider._merge_deferred_requirement_findings(findings,
        all_relation_indexes=all_indexes, deferred_findings=deferred)
    reconstructed = build_requirement_coverage_pack(query=feature["user_request"],
        materialized_projection=materialized, retrieved_pack=pack, findings=findings)
    if reconstructed.requirement_coverage != pack.requirement_coverage:
        raise ValueError("ACCEPTED_FINDINGS_PROGRESS_RESPONSE_CHANGED")
    base = continuation.prepare_initial_findings_continuation(run_root=root, run_id=run_id,
        execution_config=execution_config, correction_contract_version=allocation.get("findings_contract_version"))
    prepared = continuation._prepare_accepted_findings_reassessment(base, run_root=root, run_id=run_id,
        resume_mode="accepted_findings_reassessment", parent_override={**parent, "result_ref": parent_ref},
        feature_ref_override=outputs["feature_spec"])
    packet = prepared["continuation_input"]
    for key in ("saved_reassessment_query", "admitted_projection", "retrieved_evidence", "materialized_projection"):
        packet.pop(key, None)
    selected.pop("historical_data")
    selected.update(parent_result_ref=parent_ref, historical_feature_ref=packet["feature_spec_ref"])
    proof = {"parent_result_ref": parent_ref, "parent_manifest_ref": manifest_ref,
             "evidence_pack_ref": evidence_ref, "findings_body_refs": body_refs}
    selected["accepted_findings_progress"] = proof
    packet.update(request_interpretation_revision=selected, accepted_findings_progress=proof,
                  feature_spec_ref=outputs["feature_spec"])
    packet["parent_refs"].extend([manifest_ref, *body_refs])
    prepared["continuation_input_sha256"] = continuation._input_digest(packet)
    return prepared


def prepare_interpretation_revision(prepared, *, run_root, execution_config, allocation):
    """Prepare a new Projection contract; never reinterpret an old model response."""
    from src.mod_agent import initial_findings_continuation as continuation
    from src.mod_agent.saved_reassessment import verify_completed_saved_findings

    if not prepared["continuation_input"].get("saved_reassessment_query"):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_PARENT_UNSUPPORTED")
    root = Path(run_root).resolve(strict=True)
    if any((root / "continuations").glob("initial_findings-reassessment*.json")):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_ALREADY_CLAIMED")
    selected = read_revision_selection(allocation=allocation, run_root=root, execution_config=execution_config)
    parent = continuation.read_initial_findings_execution(root, claim_name="initial_findings-v3.json")
    if (parent is None or parent.get("status") != "domain_blocked"
            or parent.get("model_call_budget") != selected["prior_budget"]
            or parent.get("actual_write_performed") is not False
            or parent.get("canonical_source_unchanged") is not True or parent.get("patch_execution_receipts")):
        raise ValueError("REQUEST_INTERPRETATION_REVISION_PARENT_UNSUPPORTED")
    references = {row["artifact_role"]: row["artifact_ref"] for row in parent["product_execution_result"]["outputs"]}
    old_store = ArtifactStore(root / "a")
    for role, old in selected.pop("historical_data").items():
        if old_store.semantic_read_immutable(ArtifactRef(**references[role]))["data"] != old:
            raise ValueError("REQUEST_INTERPRETATION_REVISION_PARENT_CHANGED")
    pack = old_store.semantic_read_immutable(ArtifactRef(**references["evidence_pack"]))["data"]
    _, completion = verify_completed_saved_findings(prepared=prepared, parent=parent, evidence=pack, root=root)
    contract = {}
    def capture(role, payload, schema):
        contract.update(role=role, payload=deepcopy(payload), schema=deepcopy(schema))
        raise _ProjectionPreparedError()
    try:
        StructuredModelRequirementCoverageProvider(capture).project(
            feature_data=selected["feature_data"], request=selected["feature_data"]["user_request"])
    except _ProjectionPreparedError:
        pass
    if contract.get("role") != "requirement_projection":
        raise ValueError("REQUEST_INTERPRETATION_REVISION_PROJECTION_NOT_PREPARED")
    packet = deepcopy(prepared["continuation_input"])
    packet.pop("saved_reassessment_query")
    packet.pop("admitted_projection")
    packet.pop("materialized_projection")
    packet.pop("retrieved_evidence")
    selected.update(parent_result_ref=deepcopy(parent["result_ref"]),
        historical_feature_ref=deepcopy(packet["feature_spec_ref"]), completion_receipt=completion)
    packet.update(request_interpretation_revision=selected, budget=deepcopy(parent["model_call_budget"]),
        budget_stage="requirement_projection", resume_mode="accepted_findings_reassessment_revision",
        execution_parent_result_ref=deepcopy(parent["result_ref"]),
        next_turn={"role": "requirement_projection", "query_model_contract": contract})
    packet["parent_refs"].append(deepcopy(parent["result_ref"]))
    packet["implementation_refs"].append({"path": str(Path(__file__).resolve()),
        "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    return {**prepared, "budget": packet["budget"], "budget_stage": "requirement_projection",
        "blockers": [], "continuation_input": packet,
        "continuation_input_sha256": continuation._input_digest(packet)}


def advance_authorized_revision(*, run_root, run_id, execution_config, allocation_config):
    """One backend operation consumes retained authorization and the original durable claim."""
    from src.mod_agent import initial_findings_continuation as continuation

    allocation_ref, allocation = continuation._file(allocation_config)
    selected = read_revision_selection(allocation=allocation, run_root=run_root, execution_config=execution_config)
    existing = continuation.read_initial_findings_execution(run_root)
    if existing is not None and existing.get("request_interpretation_revision"):
        recorded = existing["request_interpretation_revision"]
        if (recorded.get("selection_sha256") == selected["selection_sha256"]
                and recorded.get("allocation_ref") == allocation_ref):
            return existing
        recovery = selected["selection"].get("findings_schema_recovery")
        progress = selected.get("progress_parent")
        expected_parent = progress["result_ref"] if progress else recovery["parent_result_ref"] if recovery else None
        if existing.get("result_ref") != expected_parent:
            raise ValueError("REQUEST_INTERPRETATION_REVISION_ALREADY_CLAIMED")
    preview = continuation.preview_initial_findings_execution(run_root=run_root, run_id=run_id,
        execution_config=execution_config, allocation_config=allocation_config)
    if "continuation_input" not in preview:
        recorded = preview.get("request_interpretation_revision", {})
        if (recorded.get("selection_sha256") != selected["selection_sha256"]
                or recorded.get("allocation_ref") != allocation_ref):
            raise ValueError("REQUEST_INTERPRETATION_REVISION_ALREADY_CLAIMED")
        return preview
    if preview["blockers"]:
        return preview
    decision = {"decision": "approve", "reviewer": "retained_business_authorization",
                "scope_hash": preview["scope_hash"]}
    return continuation.execute_initial_findings_continuation(run_root=run_root, run_id=run_id,
        execution_config=execution_config, allocation_config=allocation_config, decision=decision)
