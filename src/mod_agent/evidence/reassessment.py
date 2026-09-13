"""Reassess unchanged requirements over old current plus newly retrieved Evidence."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.evidence.identity import feature_spec_payload_sha256
from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.evidence.requirement_coverage import validated_requirement_coverage_view
from src.mod_agent.evidence.requirement_coverage_provider import build_requirement_coverage_pack
from src.mod_agent.fresh_planning_continuation import _validate_source_items


def _successful_source_queries(pack: EvidencePack) -> bool:
    rows = pack.budget_summary.get("per_query_execution")
    return (
        pack.budget_summary.get("all_queries_executed") is True
        and isinstance(rows, list) and bool(rows)
        and all(isinstance(row, dict) and row.get("retrieval_status") in {
            "source_observations_returned", "no_matches", "requested_source_no_matches",
        } for row in rows)
    )


def initial_findings_reassessment_allowed(payload, feature_data) -> bool:
    """Recognize an accepted, complete semantic gap before initial Planning.

    A provider/schema failure may also retain an insufficient EvidencePack. Its
    fallback is not an accepted Findings response and cannot activate this path.
    """
    try:
        old = EvidencePack.from_artifact_payload(payload)
        coverage = validated_requirement_coverage_view(payload)
        audit = old.budget_summary.get("requirement_findings_attempt_audit")
        section = old.requirement_coverage
        return (
            coverage is not None
            and coverage.feature_id == feature_data["feature_id"]
            and coverage.feature_spec_sha256 == feature_spec_payload_sha256(feature_data)
            and old.query == feature_data["user_request"]
            and old.readiness == "insufficient" and old.can_generate_patch is False
            and bool(old.blockers)
            and all(item["code"] == "REQUIREMENT_COVERAGE_INSUFFICIENT" for item in old.blockers)
            and isinstance(audit, list) and bool(audit)
            and audit[-1]["status"] == "accepted" and audit[-1]["error_code"] is None
            and not old.budget_summary.get("semantic_provider_failed_closed")
            and not old.budget_summary.get("semantic_provider_failure_codes")
            and not old.budget_summary.get("semantic_provider_failure_diagnostics")
            and _successful_source_queries(old)
            and "initial_findings_reassessment" not in old.budget_summary
            and len(section["findings"]) == len(section["relations"]) > 0
            and {item["relation_id"] for item in section["findings"]}
                == {item["relation_id"] for item in section["relations"]}
        )
    except (KeyError, TypeError, ValueError):
        return False


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
        self._initial_reassessment_used = False

    def reassess_initial(self, state: dict[str, Any], feature_data: dict[str, Any]) -> EvidencePack:
        """Recheck accepted initial Findings without manufacturing a RepairPlan."""
        if self._initial_reassessment_used or any(kind in state["artifacts"] for kind in (
                "implementation_plan", "patch_proposal", "repair_plan")):
            raise ValueError("INITIAL_FINDINGS_REASSESSMENT_NOT_ADMITTED")
        ref = ArtifactRef(feature_id=state["feature_id"], artifact_type="evidence_pack",
            path=state["artifacts"]["evidence_pack"], artifact_hash=state["artifact_hashes"]["evidence_pack"])
        payload = self.artifact_store.semantic_read_immutable(ref)["data"]
        if not initial_findings_reassessment_allowed(payload, feature_data):
            raise ValueError("INITIAL_FINDINGS_REASSESSMENT_NOT_ADMITTED")
        old = EvidencePack.from_artifact_payload(payload)
        if any(item.source_type == "target_source" for item in old.items):
            _validate_source_items(payload, self.workspace_root)
        feedback = {"initial_findings_reassessment": {
            "prior_evidence_hash": ref.artifact_hash,
            "findings": deepcopy(old.requirement_coverage["findings"]),
            "sufficiency": deepcopy(old.requirement_coverage["sufficiency"]),
        }, "interpretation_is_not_observation": True}
        self._initial_reassessment_used = True
        return self._reassess(state, feature_data, old, feedback, initial_lineage={
            "prior_evidence_ref": asdict(ref),
            "projection_identity": deepcopy(old.requirement_coverage["projection_identity"]),
            "max_cycles": 1, "cycle": 1,
        })

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
        return self._reassess(state, feature_data, old, feedback)

    def _reassess(self, state, feature_data, old, feedback, *, initial_lineage=None):
        materialized = {key: deepcopy(old.requirement_coverage[key]) for key in (
            "schema_version", "feature_spec_identity", "request_identity", "projection_identity",
            "input_obligations", "input_dispositions", "requirements", "relations", "queries")}
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
        if initial_lineage is not None and not queries:
            raise ValueError("INITIAL_FINDINGS_QUERY_REQUIRED")
        added = (self.source_provider.collect_query_set(queries=tuple(queries), search_root=self.search_root,
            max_items=len(queries)) if queries else EvidencePack(query=old.query, readiness="partial", can_generate_patch=False))
        if initial_lineage is not None and queries and not _successful_source_queries(added):
            raise ValueError("INITIAL_FINDINGS_RETRIEVAL_FAILED")
        by_id = {item.evidence_id: item for item in old.items}
        for item in added.items:
            if item.evidence_id in by_id and by_id[item.evidence_id].to_dict() != item.to_dict():
                raise ValueError("PATCH_REASSESSMENT_EVIDENCE_ID_CONFLICT")
            by_id[item.evidence_id] = item
        combined = EvidencePack(query=old.query, readiness="partial", can_generate_patch=False,
            items=tuple(by_id.values()), retrieval_methods_used=tuple(dict.fromkeys((*old.retrieval_methods_used, *added.retrieval_methods_used))),
            timing=dict(added.timing), budget_summary={"reassessment": {
                "old_evidence_hash": state["artifact_hashes"]["evidence_pack"],
                **({"repair_plan_hash": state["artifact_hashes"]["repair_plan"]} if initial_lineage is None else {}),
                "prior_item_count": len(old.items), "new_item_count": len(by_id) - len(old.items),
                "query_count": len(queries), "fresh_execution": False,
                **({"per_query_execution": deepcopy(added.budget_summary.get("per_query_execution", []))}
                   if initial_lineage is not None else {}),
                "old_execution_receipts_reused_as_new": False},
                **({"initial_findings_reassessment": deepcopy(initial_lineage)} if initial_lineage is not None else {})},
            trace_refs=tuple(added.trace_refs))
        if initial_lineage is None or any(item.source_type == "target_source" for item in combined.items):
            _validate_source_items(combined.to_artifact_payload(), self.workspace_root)
        findings = self.semantic_provider.findings(materialized_projection=deepcopy(materialized),
            retrieved_pack=combined, request=old.query, semantic_feedback=feedback)
        audit = deepcopy(list(getattr(self.semantic_provider, "findings_attempt_audit", ())))
        combined = replace(combined, budget_summary={**combined.budget_summary, "reassessment": {
            **combined.budget_summary["reassessment"], "findings_provider_invoked": True,
            "findings_attempt_audit": audit, "model_receipt_available": bool(audit)}})
        return build_requirement_coverage_pack(query=old.query, materialized_projection=materialized,
            retrieved_pack=combined, findings=findings)
