"""A read-only upstream Plan view; executable binding contracts remain local."""
from __future__ import annotations

from copy import deepcopy


def project_upstream_model_view(payload: dict) -> dict:
    """Omit equality-proven copies and known control metadata, never new facts.

    为什么要有它：Planning 比较范围与反馈时不需要第二套来源和执行器包装；完整源码、验收和本地 Plan 校验仍保留。
    """
    assessment = payload.get("upstream_assessment")
    if not isinstance(assessment, dict) or not isinstance(assessment.get("current_plan"), dict):
        return payload
    result = deepcopy(payload)
    plan = result["upstream_assessment"]["current_plan"]
    feature = result["feature"]
    observations = result["source_observations"]
    identities = result["source_identity_table"]
    by_id = {}
    for observation in observations:
        evidence_id = observation.get("evidence_id")
        if evidence_id in by_id:
            return payload  # Ambiguous identities cannot justify removing copies.
        index = observation.get("source_identity_ref")
        if type(index) is not int or not 0 <= index < len(identities):
            return payload
        by_id[evidence_id] = {**identities[index], **observation}
    registry = plan.get("binding_registry")
    if isinstance(registry, dict):
        for group, usage in (("edit_bindings", "edit_target_scope"), ("supporting_bindings", "edit_source_evidence")):
            for row in registry.get(group, []):
                source = by_id.get(row.get("evidence_id"))
                if source is None:
                    continue
                for field, source_field in (
                    ("canonical_target_path", "source_path"), ("source_path", "source_path"),
                    ("source_hash", "source_hash"), ("source_type", "source_type"),
                    ("claim_supported", "claim_supported"), ("target_symbol", "symbol"),
                ):
                    if field in row and source_field in source and row[field] == source[source_field]:
                        row.pop(field)
                for field, expected in (("authority", "mod_agent_deterministic"),
                        ("retrieval_method", "rg_live_read"), ("usage", usage)):
                    if row.get(field) == expected:
                        row.pop(field)
                # These absent parser facts are control metadata, not semantic claims.
                for field in ("declared_member_types", "declared_members", "declaring_type",
                        "declaring_type_full_name", "method_kind", "method_name", "parameter_types", "return_type"):
                    if field in row and row[field] is None:
                        row.pop(field)
                if row.get("verified_member_accesses") == []:
                    row.pop("verified_member_accesses")
        for field, expected in (("owner_artifact_type", "implementation_plan"), ("schema_version", "binding_registry_v1")):
            if registry.get(field) == expected:
                registry.pop(field)
    for field, expected in {"node_name": "create_implementation_plan", "stage": "implementation_plan",
            "message": "Implementation plan is evidence-bound.", "blocking": False, "blockers": [], "open_questions": []}.items():
        if plan.get(field) == expected:
            plan.pop(field)
    if plan.get("feature_id") == feature.get("feature_id"):
        plan.pop("feature_id", None)
    if ("test_plan" in plan and "runtime_verification_plan" in feature
            and plan["test_plan"] == feature["runtime_verification_plan"]):
        plan.pop("test_plan", None)
        plan["test_plan_ref"] = "/feature/runtime_verification_plan"
    refs = plan.get("evidence_refs")
    if isinstance(refs, list) and all(ref in by_id for ref in refs):
        paths = list(dict.fromkeys(by_id[ref].get("source_path") for ref in refs))
        if plan.get("evidence_source_paths") == paths:
            plan.pop("evidence_source_paths")
    boundaries, feedback = plan.get("side_effect_boundaries"), result.get("semantic_feedback")
    if isinstance(boundaries, list) and isinstance(feedback, list):
        result["semantic_feedback"] = [value for value in feedback if value not in boundaries]
    result["upstream_context_view"] = (
        "Read-only Plan view. Bindings/evidence_refs join source_observations by evidence_id and source_identity_ref. "
        "Explicit binding fields/span override. Plan boundaries also apply to feedback. test_plan_ref is a same-message JSON pointer."
    )
    return result
