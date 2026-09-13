"""Reassess unchanged requirements over old current plus newly retrieved Evidence."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.evidence.requirement_coverage import validated_requirement_coverage_view
from src.mod_agent.evidence.requirement_coverage_provider import build_requirement_coverage_pack
from src.mod_agent.fresh_planning_continuation import _validate_source_items


class RequirementCoverageReassessmentFactory:
    """Existing Evidence node adapter; semantic queries and Findings remain provider-owned."""

    def __init__(self, *, artifact_store, workspace_root, search_root, source_provider,
            semantic_provider, query_selector, max_additional_queries: int = 3):
        if type(max_additional_queries) is not int or not 1 <= max_additional_queries <= 64:
            raise ValueError("A bounded positive query budget is required.")
        self.artifact_store = artifact_store
        self.workspace_root = Path(workspace_root).resolve()
        self.search_root = search_root
        self.source_provider = source_provider
        self.semantic_provider = semantic_provider
        self.query_selector = query_selector
        self.max_additional_queries = max_additional_queries

    def __call__(self, state: dict[str, Any], feature_data: dict[str, Any]) -> EvidencePack:
        def read(kind):
            ref = ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
                path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind])
            return self.artifact_store.semantic_read_immutable(ref)["data"]
        old_payload = read("evidence_pack")
        old = EvidencePack.from_artifact_payload(old_payload)
        coverage = validated_requirement_coverage_view(old_payload)
        if coverage is None or coverage.feature_id != feature_data["feature_id"]:
            raise ValueError("PATCH_REASSESSMENT_COVERAGE_INVALID")
        _validate_source_items(old_payload, self.workspace_root)
        repair = read("repair_plan")
        upstream = repair["repair_context"]["upstream_request"]
        materialized = {key: deepcopy(old.requirement_coverage[key]) for key in (
            "schema_version", "feature_spec_identity", "request_identity", "projection_identity",
            "input_obligations", "input_dispositions", "requirements", "relations", "queries")}
        recommendation = {key: deepcopy(upstream[key]) for key in (
            "required_owner", "reason", "source_refs", "preserved_plan_boundaries")}
        for key in ("source_worker_response_ref", "source_attempt_ref", "failure_report_ref"):
            if key in upstream:
                ref = upstream[key]
                recommendation[key] = {"sha256": ref["sha256"]} if ref is not None else None
        observations = deepcopy(repair["failure_findings"])
        for observation in observations:
            if isinstance(observation.get("result_ref"), dict):
                observation["result_ref"] = {"sha256": observation["result_ref"]["sha256"]}
        feedback = {"recommendation": recommendation, "observed_failure": observations,
            "interpretation_is_not_observation": True}
        selected = self.query_selector(deepcopy(feature_data), deepcopy(materialized), deepcopy(old), deepcopy(feedback))
        requirement_ids = {item["requirement_id"] for item in materialized["requirements"]}
        if not isinstance(selected, (tuple, list)) or len(selected) > self.max_additional_queries:
            raise ValueError("PATCH_REASSESSMENT_QUERY_BUDGET_INVALID")
        queries = []
        for index, item in enumerate(selected, 1):
            if (not isinstance(item, dict) or set(item) != {"query", "requirement_id"}
                    or type(item["query"]) is not str or not item["query"].strip()
                    or item["requirement_id"] not in requirement_ids):
                raise ValueError("PATCH_REASSESSMENT_QUERY_INVALID")
            queries.append({"query_id": f"upstream_query_{index:03d}", **item})
        added = (self.source_provider.collect_query_set(queries=tuple(queries), search_root=self.search_root,
            max_items=len(queries)) if queries else EvidencePack(query=old.query, readiness="partial", can_generate_patch=False))
        by_id = {item.evidence_id: item for item in old.items}
        for item in added.items:
            if item.evidence_id in by_id and by_id[item.evidence_id].to_dict() != item.to_dict():
                raise ValueError("PATCH_REASSESSMENT_EVIDENCE_ID_CONFLICT")
            by_id[item.evidence_id] = item
        combined = EvidencePack(query=old.query, readiness="partial", can_generate_patch=False,
            items=tuple(by_id.values()), retrieval_methods_used=tuple(dict.fromkeys((*old.retrieval_methods_used, *added.retrieval_methods_used))),
            timing=dict(added.timing), budget_summary={"reassessment": {
                "old_evidence_hash": state["artifact_hashes"]["evidence_pack"],
                "repair_plan_hash": state["artifact_hashes"]["repair_plan"],
                "prior_item_count": len(old.items), "new_item_count": len(by_id) - len(old.items),
                "query_count": len(queries), "fresh_execution": False,
                "old_execution_receipts_reused_as_new": False}},
            trace_refs=tuple(added.trace_refs))
        _validate_source_items(combined.to_artifact_payload(), self.workspace_root)
        findings = self.semantic_provider.findings(materialized_projection=deepcopy(materialized),
            retrieved_pack=combined, request=old.query, semantic_feedback=feedback)
        audit = deepcopy(list(getattr(self.semantic_provider, "findings_attempt_audit", ())))
        combined = replace(combined, budget_summary={"reassessment": {
            **combined.budget_summary["reassessment"], "findings_provider_invoked": True,
            "findings_attempt_audit": audit, "model_receipt_available": bool(audit)}})
        return build_requirement_coverage_pack(query=old.query, materialized_projection=materialized,
            retrieved_pack=combined, findings=findings)
