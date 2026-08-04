"""Stub business nodes for the Phase A workflow skeleton."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore, ArtifactWriteResult
from src.mod_agent.build import build_fake_build_result
from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION
from src.mod_agent.runtime import build_fake_runtime_evidence_payload

from .state import ModAgentState, StageName

NodeName = str

NODE_STAGE_MAP: Mapping[NodeName, StageName] = {
    "plan_request": "request_planning",
    "draft_feature_spec": "feature_spec",
    "retrieve_evidence": "evidence_retrieval",
    "create_implementation_plan": "implementation_plan",
    "generate_patch_proposal": "patch_proposal",
    "review_proposal": "proposal_review",
    "dry_run_apply": "dry_run_apply",
    "build": "build",
    "collect_runtime_evidence": "runtime_evidence",
    "create_repair_plan": "repair_plan",
    "evaluate": "evaluation",
    "done": "done",
    "blocked": "blocked",
}

NODE_ARTIFACT_MAP: Mapping[NodeName, str] = {
    "plan_request": "request_planning_report",
    "draft_feature_spec": "feature_spec",
    "retrieve_evidence": "evidence_pack",
    "create_implementation_plan": "implementation_plan",
    "generate_patch_proposal": "patch_proposal",
    "review_proposal": "proposal_review",
    "dry_run_apply": "dry_run_result",
    "build": "build_result",
    "collect_runtime_evidence": "runtime_evidence",
    "create_repair_plan": "repair_plan",
    "evaluate": "eval_report",
    "done": "workflow_summary",
    "blocked": "blocked_report",
}


@dataclass(frozen=True)
class TraceEvent:
    """Structured trace event emitted by a stub node."""

    event_id: str
    run_id: str
    feature_id: str
    node_name: str
    stage: StageName
    event_type: str
    status: str
    artifact_refs: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable trace event."""

        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "feature_id": self.feature_id,
            "node_name": self.node_name,
            "stage": self.stage,
            "event_type": self.event_type,
            "status": self.status,
            "artifact_refs": self.artifact_refs,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class StubNodeResult:
    """Result produced by a stub node execution."""

    state: ModAgentState
    artifact_ref: ArtifactRef | None
    trace_event: TraceEvent
    artifact_write_result: ArtifactWriteResult | None = None


class StubNodeRunner:
    """Run Phase A business nodes as safe, artifact-backed stubs."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def run(
        self,
        node_name: NodeName,
        state: ModAgentState,
        *,
        use_store_result: bool = False,
        additional_upstream_refs: tuple[ArtifactRef, ...] = (),
    ) -> StubNodeResult:
        """Execute a stub node and return updated state plus trace."""

        if node_name not in NODE_STAGE_MAP:
            raise KeyError(f"Unknown stub node: {node_name}")

        stage = NODE_STAGE_MAP[node_name]
        artifact_type = NODE_ARTIFACT_MAP[node_name]
        feature_id = state.get("feature_id") or state["request_id"]
        event_id = f"evt_{uuid4().hex}"
        try:
            payload = self._payload_for(
                artifact_type=artifact_type,
                node_name=node_name,
                stage=stage,
                user_request=state["user_request"],
                state=state,
            )
            upstream_refs = self._upstream_refs_for(
                artifact_type,
                feature_id,
                state,
            )
            for ref in additional_upstream_refs:
                if ref not in upstream_refs:
                    upstream_refs.append(ref)
        except Exception as exc:
            if not use_store_result:
                raise
            next_state = self._copy_state(state)
            next_state["current_stage"] = stage
            next_state["runtime_summary"].update(
                {
                    "platform_failure_stage": "blocked_report_execution",
                    "blocked_report_store_result": None,
                    "blocked_report_ready": False,
                    "terminal_route": "blocked",
                    "terminal_ready": False,
                    "terminal_final_status": None,
                    "terminal_claims_real_mod_success": False,
                }
            )
            next_state["blockers"].append(
                {
                    "stage": "blocked",
                    "code": "BLOCKED_REPORT_EXECUTION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
            return StubNodeResult(
                state=next_state,
                artifact_ref=None,
                trace_event=TraceEvent(
                    event_id=event_id,
                    run_id=state["run_id"],
                    feature_id=feature_id,
                    node_name=node_name,
                    stage=stage,
                    event_type="node_finished",
                    status="blocked",
                    artifact_refs=[],
                    summary="Workflow terminal blocker report construction failed.",
                ),
            )
        write_result = None
        if use_store_result:
            write_result = self.artifact_store.write_with_result(
                feature_id=feature_id,
                artifact_type=artifact_type,
                payload=payload,
                status="blocked" if node_name == "blocked" else "stubbed",
                trace_refs=[],
                upstream_refs=upstream_refs,
            )
            artifact_ref = write_result.artifact_ref
        else:
            artifact_ref = self.artifact_store.write(
                feature_id=feature_id,
                artifact_type=artifact_type,
                payload=payload,
                status="blocked" if node_name == "blocked" else "stubbed",
                trace_refs=[event_id],
                upstream_refs=upstream_refs,
            )
        next_state = self._copy_state(state)
        next_state["feature_id"] = feature_id
        next_state["current_stage"] = stage
        if artifact_ref is not None:
            next_state["artifacts"][artifact_type] = artifact_ref.path
            next_state["artifact_hashes"][artifact_type] = artifact_ref.artifact_hash
        if write_result is not None:
            next_state["runtime_summary"].update(
                {
                    "blocked_report_store_result": write_result.to_dict(),
                    "blocked_report_ready": (
                        write_result.outcome == "committed"
                        and artifact_ref is not None
                    ),
                    "platform_failure_stage": (
                        None
                        if write_result.outcome == "committed"
                        else "blocked_report_store"
                    ),
                    "terminal_route": "blocked",
                    "terminal_ready": (
                        write_result.outcome == "committed"
                        and artifact_ref is not None
                    ),
                    "terminal_final_status": (
                        "blocked"
                        if write_result.outcome == "committed"
                        and artifact_ref is not None
                        else None
                    ),
                    "terminal_claims_real_mod_success": False,
                }
            )

        if node_name == "blocked" and not next_state["blockers"]:
            next_state["blockers"].append(
                {
                    "stage": stage,
                    "reason": "Phase A blocked stub node reached.",
                }
            )

        trace_event = TraceEvent(
            event_id=event_id,
            run_id=state["run_id"],
            feature_id=feature_id,
            node_name=node_name,
            stage=stage,
            event_type="node_finished",
            status="blocked" if node_name == "blocked" else "stubbed",
            artifact_refs=[] if artifact_ref is None else [artifact_ref.path],
            summary=(
                "Workflow terminal blocker report persisted."
                if node_name == "blocked"
                else f"{node_name} completed as a Phase A stub."
            ),
        )
        return StubNodeResult(
            state=next_state,
            artifact_ref=artifact_ref,
            trace_event=trace_event,
            artifact_write_result=write_result,
        )

    def _upstream_refs_for(
        self,
        artifact_type: str,
        feature_id: str,
        state: ModAgentState,
    ) -> list[ArtifactRef]:
        contract = self.artifact_store.registry.get(artifact_type)
        refs: list[ArtifactRef] = []
        for upstream_type in sorted(contract.required_upstream_artifacts):
            path = state["artifacts"].get(upstream_type)
            artifact_hash = state["artifact_hashes"].get(upstream_type)
            if path and artifact_hash:
                refs.append(
                    ArtifactRef(
                        feature_id=feature_id,
                        artifact_type=upstream_type,
                        path=path,
                        artifact_hash=artifact_hash,
                    )
                )
        return refs

    @staticmethod
    def _payload_for(
        *,
        artifact_type: str,
        node_name: str,
        stage: StageName,
        user_request: str,
        state: ModAgentState,
    ) -> dict[str, Any]:
        if artifact_type == "blocked_report":
            return {
                "node_name": node_name,
                "stage": stage,
                "message": "Workflow stopped at the blocked terminal stage.",
                "blockers": list(state["blockers"]),
                "upstream_artifacts": {
                    artifact_name: {
                        "path": artifact_path,
                        "artifact_hash": state["artifact_hashes"].get(artifact_name),
                    }
                    for artifact_name, artifact_path in sorted(
                        state["artifacts"].items()
                    )
                },
            }
        payload: dict[str, Any] = {
            "node_name": node_name,
            "stage": stage,
            "message": (
                "Phase A stub node. No real retrieval, patch generation, build, "
                "runtime action, or source write was performed."
            ),
        }
        if artifact_type == "request_planning_report":
            payload.update(
                {
                    "feature_id": "stubbed_feature",
                    "user_request": user_request,
                    "route": "standard_feature",
                    "risk_level": "medium",
                    "target_mod": None,
                    "requires_hook_evidence": True,
                    "requires_runtime_evidence": False,
                    "uncertainties": [],
                    "blocked": False,
                }
            )
        if artifact_type == "feature_spec":
            payload.update(
                {
                    "feature_id": "stubbed_feature",
                    "user_request": user_request,
                    "target_behavior": user_request,
                    "non_goals": ["Phase A stub does not define real non-goals."],
                    "target_mod": None,
                    "risk_level": "medium",
                    "acceptance_criteria": ["Phase A stub has no real acceptance criteria."],
                    "evidence_requirements": ["Phase A stub requires future evidence."],
                    "runtime_verification_plan": [],
                    "blocked": False,
                    "blockers": [],
                }
            )
        if artifact_type == "evidence_pack":
            blocker = {
                "code": "STUBBED_EVIDENCE_RETRIEVAL",
                "message": "Evidence retrieval is stubbed in this workflow node.",
                "needed_evidence": ["knowledge index", "symbol evidence"],
            }
            payload.update(
                {
                    "query": user_request,
                    "readiness": "insufficient",
                    "can_generate_patch": False,
                    "authority": "mod_agent_deterministic_evidence",
                    "authoritative_for_patch": False,
                    "identity_schema_version": IDENTITY_SCHEMA_VERSION,
                    "identity_field_mapping": dict(IDENTITY_FIELD_MAPPING),
                    "items": [],
                    "gaps": ["Phase A stub did not run evidence retrieval."],
                    "excluded": [],
                    "blockers": [blocker],
                    "retrieval_methods_used": [],
                    "missing_evidence": [
                        {
                            "needed_evidence": needed,
                            "blocker_code": blocker["code"],
                            "reason": blocker["message"],
                        }
                        for needed in blocker["needed_evidence"]
                    ],
                    "disabled_modes": {
                        "deterministic": "Stub node did not run deterministic retrieval.",
                        "bm25": "Stub node did not run BM25 retrieval.",
                        "dense": "Stub node did not run dense retrieval.",
                        "fusion": "Stub node did not run fusion.",
                        "rerank": "Stub node did not run rerank.",
                        "neural_sparse": "Neural sparse retrieval is outside the V1 retrieval path.",
                    },
                    "timing": {
                        "query_processing_ms": 0.0,
                        "symbol_ms": 0.0,
                        "text_ms": 0.0,
                        "bm25_ms": 0.0,
                        "dense_ms": 0.0,
                        "fusion_ms": 0.0,
                        "rerank_ms": 0.0,
                        "readiness_ms": 0.0,
                        "total_ms": 0.0,
                        "final_count": 0.0,
                        "excluded_count": 0.0,
                    },
                    "trace_refs": [],
                }
            )
        if artifact_type == "implementation_plan":
            payload.update(
                {
                    "feature_id": "stubbed_feature",
                    "evidence_source_paths": [],
                    "target_files": [],
                    "target_symbols": [],
                    "evidence_refs": [],
                    "proposed_changes": [],
                    "side_effect_boundaries": [],
                    "test_plan": [],
                    "rollback_plan": [],
                    "open_questions": ["Phase A stub did not create a real implementation plan."],
                    "blocking": True,
                    "blockers": [
                        {
                            "code": "STUBBED_IMPLEMENTATION_PLAN",
                            "message": "Implementation planning is stubbed in this workflow node.",
                        }
                    ],
                }
            )
        if artifact_type == "patch_proposal":
            payload.update(
                {
                    "proposal_id": "stubbed_proposal",
                    "feature_id": "stubbed_feature",
                    "summary": "Phase A stub proposal.",
                    "files": [],
                    "diff_intent": [],
                    "change_units": [],
                    "context_pack": {
                        "feature_id": "stubbed_feature",
                        "files": [],
                        "evidence_refs": [],
                        "evidence_source_paths": [],
                        "scope_boundary": [],
                        "change_unit_ids": [],
                    },
                    "evidence_refs": [],
                    "scope_boundary": [],
                    "risk_assessment": {
                        "risk_level": "blocked",
                        "requires_manual_review": True,
                    },
                    "expected_tests": [],
                    "no_op_status": {
                        "is_no_op": True,
                        "reason": "Phase A stub did not generate patch intent.",
                    },
                    "rollback_hints": [],
                    "manual_review_notes": ["Phase A stub did not generate patch intent."],
                    "blocked": True,
                    "blockers": [
                        {
                            "code": "STUBBED_PATCH_PROPOSAL",
                            "message": "Patch proposal generation is stubbed.",
                        }
                    ],
                }
            )
        if artifact_type == "proposal_review":
            payload.update(
                {
                    "decision": "revise_proposal",
                    "findings": [
                        {
                            "rule_id": "stubbed_review",
                            "level": "blocking",
                            "message": "Proposal review is stubbed.",
                            "change_id": None,
                            "evidence_refs": [],
                        }
                    ],
                    "required_changes": ["Run real proposal review before dry-run apply."],
                    "allowed_next_stage": None,
                    "checked_rules": ["stubbed_review"],
                    "trace_metrics": {
                        "num_changes_checked": 0,
                        "num_blocking_findings": 1,
                    },
                }
            )
        if artifact_type == "build_result":
            payload.update(
                build_fake_build_result(
                    feature_id="stubbed_feature",
                    input_execution_mode=None,
                ).to_artifact_payload()
            )
        if artifact_type == "runtime_evidence":
            payload.update(
                build_fake_runtime_evidence_payload(
                    feature_id="stubbed_feature",
                    input_execution_mode=None,
                    acceptance_criteria=("Phase A stub has no real acceptance criteria.",),
                    runtime_verification_plan=(),
                )
            )
        if artifact_type == "repair_plan":
            payload.update(
                {
                    "repair_id": "stubbed_repair",
                    "feature_id": "stubbed_feature",
                    "failure_source": "build",
                    "failure_class": "unknown",
                    "failure_evidence": ["stubbed_failure_evidence"],
                    "evidence_refs": ["stubbed_failure_evidence"],
                    "root_cause_hypotheses": [
                        "Stub repair plan has no real failure evidence."
                    ],
                    "hypothesis": "Stub repair plan has no real failure evidence.",
                    "recommended_fix_strategy": "Run real repair planning before retry.",
                    "minimal_changes": [],
                    "retry_count": 0,
                    "retry_budget": 0,
                    "retry_budget_remaining": 0,
                    "retry_exhausted": True,
                    "scope_expansion_allowed": False,
                    "stop_condition": "Phase A stub cannot retry.",
                    "forbidden_regressions": [],
                    "requires_new_evidence": True,
                    "allowed_next_stage": None,
                    "blockers": [
                        {
                            "code": "STUBBED_REPAIR_PLAN",
                            "message": "Repair planning is stubbed.",
                        }
                    ],
                }
            )
        return payload

    @staticmethod
    def _copy_state(state: ModAgentState) -> ModAgentState:
        return ModAgentState(
            run_id=state["run_id"],
            request_id=state["request_id"],
            feature_id=state["feature_id"],
            user_request=state["user_request"],
            target_domain=state["target_domain"],
            target_mod=state["target_mod"],
            execution_path=state["execution_path"],
            risk_level=state["risk_level"],
            current_stage=state["current_stage"],
            next_stage=state["next_stage"],
            artifacts=dict(state["artifacts"]),
            artifact_hashes=dict(state["artifact_hashes"]),
            approvals=dict(state["approvals"]),
            blockers=list(state["blockers"]),
            warnings=list(state["warnings"]),
            evidence_summary=dict(state["evidence_summary"]),
            review_summary=dict(state["review_summary"]),
            build_summary=dict(state["build_summary"]),
            runtime_summary=dict(state["runtime_summary"]),
            trace_events=list(state["trace_events"]),
            retry_count=state["retry_count"],
        )
