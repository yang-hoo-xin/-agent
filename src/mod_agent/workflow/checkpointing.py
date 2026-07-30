"""Artifact-backed checkpoint and resume helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore, ArtifactStoreError

from .interrupts import ResumeDecision, ResumePayload, ResumeValidator
from .state import ModAgentState


@dataclass(frozen=True)
class CheckpointPolicy:
    """Local checkpoint policy for human-controlled workflow boundaries."""

    interrupt_stages: tuple[str, ...] = (
        "proposal_review",
        "review_proposal",
        "dry_run_apply",
        "build",
        "collect_runtime_evidence",
        "edit_authority_approval",
    )
    backend: str = "langgraph_memory"

    def should_checkpoint(self, stage: str) -> bool:
        """Return whether the stage is a checkpoint boundary."""

        return stage in self.interrupt_stages

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable policy details."""

        return {
            "interrupt_stages": list(self.interrupt_stages),
            "backend": self.backend,
        }


@dataclass(frozen=True)
class WorkflowCheckpoint:
    """Structured checkpoint payload."""

    checkpoint_id: str
    run_id: str
    feature_id: str
    request_id: str
    stage: str
    status: str
    state_snapshot: dict[str, Any]
    artifact_refs: tuple[str, ...]
    artifact_hashes: dict[str, str]
    resume_binding: dict[str, Any]
    resume_allowed_fields: tuple[str, ...]
    interrupt_reason: str
    policy: CheckpointPolicy

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the workflow_checkpoint contract."""

        return {
            "node_name": "workflow_checkpoint",
            "stage": "checkpoint",
            "message": "Workflow checkpoint recorded for controlled resume.",
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "feature_id": self.feature_id,
            "request_id": self.request_id,
            "checkpoint_stage": self.stage,
            "status": self.status,
            "state_snapshot": self.state_snapshot,
            "artifact_refs": list(self.artifact_refs),
            "artifact_hashes": self.artifact_hashes,
            "resume_binding": self.resume_binding,
            "resume_allowed_fields": list(self.resume_allowed_fields),
            "interrupt_reason": self.interrupt_reason,
            "checkpoint_policy": self.policy.to_dict(),
        }


@dataclass(frozen=True)
class ResumeReport:
    """Structured resume report payload."""

    resume_id: str
    checkpoint_id: str
    run_id: str
    stage: str
    decision: str
    status: str
    allowed: bool
    reason: str
    applied_updates: dict[str, Any]
    stale_reasons: tuple[str, ...]
    blockers: tuple[dict[str, Any], ...]
    approved_by: str = ""
    approved_at: str = ""
    authority_request_hash: str | None = None

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the resume_report contract."""

        return {
            "node_name": "workflow_resume",
            "stage": "resume",
            "message": f"Workflow resume {self.status}.",
            "resume_id": self.resume_id,
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id,
            "resume_stage": self.stage,
            "decision": self.decision,
            "status": self.status,
            "allowed": self.allowed,
            "reason": self.reason,
            "applied_updates": self.applied_updates,
            "stale_reasons": list(self.stale_reasons),
            "blockers": list(self.blockers),
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "authority_request_hash": self.authority_request_hash,
        }


def resumed_state_from_decision(
    decision: ResumeDecision,
    *,
    checkpoint_ref: ArtifactRef | None = None,
    resume_report_ref: ArtifactRef | None = None,
) -> ModAgentState:
    """Build a graph-resumable state from an accepted resume decision."""

    if not decision.allowed:
        raise ValueError("Cannot build graph state from a blocked resume decision.")
    restored_state = decision.applied_updates.get("restored_state")
    if not isinstance(restored_state, dict):
        raise ValueError("Accepted resume decision does not contain restored_state.")
    state = ModAgentState(**restored_state)
    if decision.applied_updates.get("clear_checkpointed_approvals") is True:
        state["approvals"] = {}
    approvals = decision.applied_updates.get("approvals")
    if isinstance(approvals, dict):
        state["approvals"] = {
            **dict(state["approvals"]),
            **approvals,
        }
    if checkpoint_ref is not None:
        state["artifacts"] = {
            **dict(state["artifacts"]),
            "workflow_checkpoint": checkpoint_ref.path,
        }
        state["artifact_hashes"] = {
            **dict(state["artifact_hashes"]),
            "workflow_checkpoint": checkpoint_ref.artifact_hash,
        }
    if resume_report_ref is not None:
        state["artifacts"] = {
            **dict(state["artifacts"]),
            "resume_report": resume_report_ref.path,
        }
        state["artifact_hashes"] = {
            **dict(state["artifact_hashes"]),
            "resume_report": resume_report_ref.artifact_hash,
        }
    return state


class WorkflowCheckpointStore:
    """Write checkpoints and validate resume attempts through ArtifactStore."""

    def __init__(
        self,
        artifact_store: ArtifactStore,
        *,
        policy: CheckpointPolicy | None = None,
        resume_validator: ResumeValidator | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.policy = policy or CheckpointPolicy()
        self.resume_validator = resume_validator or ResumeValidator()
        self._consumed_checkpoint_ids: set[str] = set()
        self._seen_resume_ids: set[str] = set()

    def create_checkpoint(
        self,
        state: ModAgentState,
        *,
        interrupt_reason: str,
        resume_allowed_fields: tuple[str, ...],
    ) -> ArtifactRef:
        """Persist a workflow_checkpoint artifact from current state."""

        feature_id = state["feature_id"] or state["request_id"]
        artifact_refs = tuple(state["artifacts"].values())
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=f"checkpoint_{uuid4().hex}",
            run_id=state["run_id"],
            feature_id=feature_id,
            request_id=state["request_id"],
            stage=state["current_stage"],
            status="interrupted",
            state_snapshot=self._state_snapshot(state),
            artifact_refs=artifact_refs,
            artifact_hashes=dict(state["artifact_hashes"]),
            resume_binding=self._resume_binding_from_state(state),
            resume_allowed_fields=resume_allowed_fields,
            interrupt_reason=interrupt_reason,
            policy=self.policy,
        )
        return self.artifact_store.write(
            feature_id=feature_id,
            artifact_type="workflow_checkpoint",
            payload=checkpoint.to_artifact_payload(),
            status="success",
            upstream_refs=self._artifact_refs_from_state(state),
        )

    def resume(
        self,
        checkpoint_ref: ArtifactRef,
        payload: ResumePayload,
    ) -> tuple[ResumeDecision, ArtifactRef]:
        """Validate a resume payload and write a resume_report artifact."""

        checkpoint = self.artifact_store.read(checkpoint_ref)["data"]
        decision = self.preflight_resume(
            checkpoint_ref,
            resume_id=payload.resume_id,
        )
        if decision.allowed:
            decision = self.resume_validator.validate(payload, checkpoint=checkpoint)

        if decision.allowed:
            self._seen_resume_ids.add(payload.resume_id)
            self._consumed_checkpoint_ids.add(checkpoint["checkpoint_id"])

        report = ResumeReport(
            resume_id=payload.resume_id,
            checkpoint_id=str(checkpoint["checkpoint_id"]),
            run_id=payload.run_id,
            stage=payload.stage,
            decision=payload.decision,
            status=decision.status,
            allowed=decision.allowed,
            reason=decision.reason,
            applied_updates=decision.applied_updates,
            stale_reasons=tuple(decision.stale_reasons),
            blockers=tuple(decision.blockers),
            approved_by=payload.approved_by,
            approved_at=payload.approved_at,
            authority_request_hash=payload.authority_request_hash,
        )
        report_ref = self.artifact_store.write(
            feature_id=checkpoint_ref.feature_id,
            artifact_type="resume_report",
            payload=report.to_artifact_payload(),
            status="success" if decision.allowed else "blocked",
            upstream_refs=[checkpoint_ref],
            allow_stale_upstreams=not decision.allowed and bool(decision.stale_reasons),
            exact_revision_upstream_types={"workflow_checkpoint"},
        )
        return decision, report_ref

    def preflight_resume(
        self,
        checkpoint_ref: ArtifactRef,
        *,
        resume_id: str | None = None,
    ) -> ResumeDecision:
        """Validate checkpoint integrity and consumption without writing or consuming."""

        checkpoint_envelope = self.artifact_store.read(checkpoint_ref)
        checkpoint = checkpoint_envelope["data"]
        lineage_blockers = self._checkpoint_lineage_blockers(
            checkpoint_ref,
            checkpoint_envelope,
        )
        freshness = (
            self.artifact_store.check_freshness(checkpoint_ref)
            if checkpoint.get("checkpoint_stage") == "build"
            else self.artifact_store.check_direct_freshness(checkpoint_ref)
        )
        consumed, seen_resume_id = self._durable_consumption_state(
            checkpoint_ref.feature_id,
            checkpoint_id=str(checkpoint.get("checkpoint_id") or ""),
            resume_id=resume_id or "",
        )
        if lineage_blockers:
            return ResumeDecision(
                status="blocked",
                allowed=False,
                reason="Resume blocked because checkpoint lineage is invalid.",
                applied_updates={},
                blockers=tuple(lineage_blockers),
            )
        if not freshness.is_fresh:
            return ResumeDecision(
                status="blocked",
                allowed=False,
                reason="Resume blocked because checkpoint inputs are stale.",
                applied_updates={},
                blockers=(
                    {
                        "code": "STALE_RESUME_REJECTED",
                        "message": "Checkpoint upstream artifacts changed.",
                    },
                ),
                stale_reasons=tuple(freshness.stale_reasons),
            )
        if (
            (resume_id is not None and resume_id in self._seen_resume_ids)
            or checkpoint["checkpoint_id"] in self._consumed_checkpoint_ids
            or seen_resume_id
            or consumed
        ):
            return ResumeDecision(
                status="blocked",
                allowed=False,
                reason="Resume blocked because checkpoint or resume_id was already used.",
                applied_updates={},
                blockers=(
                    {
                        "code": "DOUBLE_RESUME_REJECTED",
                        "message": "Checkpoint resume is idempotent and was already consumed.",
                    },
                ),
            )
        return ResumeDecision(
            status="ready",
            allowed=True,
            reason="Checkpoint is ready for a separately authorized resume.",
            applied_updates={},
        )

    def preflight_accepted_resume_recovery(
        self,
        checkpoint_ref: ArtifactRef,
        *,
        resume_id: str,
    ) -> tuple[ResumeDecision, ArtifactRef]:
        """Read-validate one exact accepted pre-Runtime resume without writing."""

        if not resume_id:
            raise ValueError(
                "Accepted resume recovery requires the exact prior resume_id."
            )
        checkpoint_envelope = self.artifact_store.read(checkpoint_ref)
        checkpoint = checkpoint_envelope["data"]
        blockers = self._checkpoint_lineage_blockers(
            checkpoint_ref,
            checkpoint_envelope,
        )
        freshness = (
            self.artifact_store.check_freshness(checkpoint_ref)
            if checkpoint.get("checkpoint_stage") == "build"
            else self.artifact_store.check_direct_freshness(checkpoint_ref)
        )
        if not freshness.is_fresh:
            blockers.append(
                {
                    "code": "STALE_RESUME_RECOVERY_REJECTED",
                    "message": "Checkpoint inputs changed after the accepted resume.",
                }
            )

        accepted_reports: list[tuple[ArtifactRef, dict[str, Any], dict[str, Any]]] = []
        for report_ref in self.artifact_store.list_feature_artifact_revisions(
            checkpoint_ref.feature_id,
            "resume_report",
        ):
            envelope = self.artifact_store.read(report_ref)
            report = envelope["data"]
            if (
                report.get("checkpoint_id") == checkpoint.get("checkpoint_id")
                and report.get("allowed") is True
            ):
                accepted_reports.append((report_ref, envelope, report))
        if len(accepted_reports) != 1:
            raise ValueError(
                "Accepted resume recovery requires exactly one accepted "
                "ResumeReport for the checkpoint."
            )
        report_ref, report_envelope, report = accepted_reports[0]
        if report.get("resume_id") != resume_id:
            raise ValueError(
                "Accepted resume recovery resume_id does not match ResumeReport."
            )
        upstream = report_envelope.get("inputs", {}).get("upstream_artifacts", [])
        if (
            len(upstream) != 1
            or upstream[0].get("artifact_type") != "workflow_checkpoint"
            or upstream[0].get("path") != checkpoint_ref.path
            or upstream[0].get("artifact_hash") != checkpoint_ref.artifact_hash
        ):
            blockers.append(
                {
                    "code": "RESUME_RECOVERY_REPORT_BINDING_MISMATCH",
                    "message": (
                        "Accepted ResumeReport is not bound to the exact checkpoint."
                    ),
                }
            )
        restored_state = report.get("applied_updates", {}).get("restored_state")
        if (
            report.get("status") != "accepted"
            or report.get("run_id") != checkpoint.get("run_id")
            or report.get("resume_stage") != checkpoint.get("checkpoint_stage")
            or not isinstance(report.get("applied_updates"), dict)
            or not isinstance(restored_state, dict)
            or restored_state != checkpoint.get("state_snapshot")
        ):
            blockers.append(
                {
                    "code": "RESUME_RECOVERY_REPORT_INVALID",
                    "message": (
                        "Accepted ResumeReport cannot reconstruct the exact "
                        "pre-Runtime graph state."
                    ),
                }
            )
        for artifact_type in ("runtime_evidence", "eval_report", "workflow_summary"):
            for ref in self.artifact_store.list_feature_artifact_revisions(
                checkpoint_ref.feature_id,
                artifact_type,
            ):
                artifact = self.artifact_store.read(ref)["data"]
                if artifact.get("run_id") == checkpoint.get("run_id"):
                    blockers.append(
                        {
                            "code": "RESUME_RECOVERY_DOWNSTREAM_STATE_PRESENT",
                            "message": (
                                f"{artifact_type} already exists for this handoff run."
                            ),
                        }
                    )
                    break
        if blockers:
            raise ValueError(
                "Accepted resume recovery was blocked: "
                + ", ".join(str(item.get("code")) for item in blockers)
            )
        return (
            ResumeDecision(
                status="accepted",
                allowed=True,
                reason="Exact accepted ResumeReport is ready for bounded recovery.",
                applied_updates=dict(report["applied_updates"]),
            ),
            report_ref,
        )

    def preflight_runtime_observation_retry(
        self,
        checkpoint_ref: ArtifactRef,
        *,
        resume_id: str,
    ) -> tuple[
        ResumeDecision,
        ArtifactRef,
        ArtifactRef,
        ArtifactRef,
        dict[str, Any],
    ]:
        """Read-validate one bounded observation retry without writing."""

        if not resume_id:
            raise ValueError(
                "Runtime observation retry requires the exact prior resume_id."
            )
        checkpoint_envelope = self.artifact_store.read(checkpoint_ref)
        checkpoint = checkpoint_envelope["data"]
        blockers = self._checkpoint_lineage_blockers(
            checkpoint_ref,
            checkpoint_envelope,
            allow_prior_runtime_state=True,
        )
        freshness = (
            self.artifact_store.check_freshness(checkpoint_ref)
            if checkpoint.get("checkpoint_stage") == "build"
            else self.artifact_store.check_direct_freshness(checkpoint_ref)
        )
        if not freshness.is_fresh:
            blockers.append(
                {
                    "code": "OBSERVATION_RETRY_STALE_CHECKPOINT",
                    "message": (
                        "Checkpoint inputs changed after the prior Runtime "
                        "observation."
                    ),
                }
            )

        accepted_reports: list[tuple[ArtifactRef, dict[str, Any], dict[str, Any]]] = []
        for report_ref in self.artifact_store.list_feature_artifact_revisions(
            checkpoint_ref.feature_id,
            "resume_report",
        ):
            envelope = self.artifact_store.read(report_ref)
            report = envelope["data"]
            if (
                report.get("checkpoint_id") == checkpoint.get("checkpoint_id")
                and report.get("allowed") is True
            ):
                accepted_reports.append((report_ref, envelope, report))
        if len(accepted_reports) != 1:
            raise ValueError(
                "Runtime observation retry requires exactly one accepted "
                "ResumeReport for the checkpoint."
            )
        report_ref, report_envelope, report = accepted_reports[0]
        if report.get("resume_id") != resume_id:
            raise ValueError(
                "Runtime observation retry resume_id does not match ResumeReport."
            )
        report_upstream = report_envelope.get("inputs", {}).get(
            "upstream_artifacts",
            [],
        )
        restored_state = report.get("applied_updates", {}).get("restored_state")
        if (
            len(report_upstream) != 1
            or report_upstream[0].get("artifact_type") != "workflow_checkpoint"
            or report_upstream[0].get("path") != checkpoint_ref.path
            or report_upstream[0].get("artifact_hash")
            != checkpoint_ref.artifact_hash
            or report.get("status") != "accepted"
            or report.get("run_id") != checkpoint.get("run_id")
            or report.get("resume_stage") != checkpoint.get("checkpoint_stage")
            or not isinstance(report.get("applied_updates"), dict)
            or not isinstance(restored_state, dict)
            or restored_state != checkpoint.get("state_snapshot")
        ):
            blockers.append(
                {
                    "code": "OBSERVATION_RETRY_RESUME_BINDING_INVALID",
                    "message": (
                        "Accepted ResumeReport does not reconstruct the exact "
                        "pre-Runtime state."
                    ),
                }
            )

        runtime_revisions: list[tuple[ArtifactRef, dict[str, Any]]] = []
        for runtime_ref in self.artifact_store.list_feature_artifact_revisions(
            checkpoint_ref.feature_id,
            "runtime_evidence",
        ):
            runtime = self.artifact_store.read(runtime_ref)["data"]
            if runtime.get("run_id") == checkpoint.get("run_id"):
                runtime_revisions.append((runtime_ref, runtime))
        latest_runtime_ref = self._latest_revision_ref(
            checkpoint_ref.feature_id,
            "runtime_evidence",
        )
        if latest_runtime_ref is None:
            raise ValueError(
                "Runtime observation retry requires prior RuntimeEvidence."
            )
        latest_runtime = self.artifact_store.read(latest_runtime_ref)["data"]
        runtime_owner = latest_runtime.get("failure_ownership")
        checkpoint_snapshot = checkpoint.get("state_snapshot") or {}
        checkpoint_artifacts = checkpoint_snapshot.get("artifacts") or {}
        checkpoint_hashes = checkpoint_snapshot.get("artifact_hashes") or {}
        build_ref = latest_runtime.get("build_artifact_ref") or {}
        if (
            latest_runtime.get("run_id") != checkpoint.get("run_id")
            or latest_runtime.get("verification_status") != "inconclusive"
            or latest_runtime.get("acceptance_verified") is not False
            or latest_runtime.get("claims_real_runtime_success") is not False
            or not isinstance(runtime_owner, dict)
            or runtime_owner.get("owner") != "observation"
            or runtime_owner.get("required_action") != "repair_runtime_observation"
            or runtime_owner.get("source_repair_allowed") is not False
            or not isinstance(build_ref, dict)
            or build_ref.get("path") != checkpoint_artifacts.get("build_result")
            or build_ref.get("artifact_hash")
            != checkpoint_hashes.get("build_result")
            or latest_runtime.get("build_artifact_hash")
            != checkpoint_hashes.get("build_result")
        ):
            blockers.append(
                {
                    "code": "OBSERVATION_RETRY_RUNTIME_EVIDENCE_INELIGIBLE",
                    "message": (
                        "Latest RuntimeEvidence is not an inconclusive, "
                        "observation-owned result bound to this Build."
                    ),
                }
            )

        latest_repair_ref = self._latest_revision_ref(
            checkpoint_ref.feature_id,
            "repair_plan",
        )
        if latest_repair_ref is None:
            raise ValueError(
                "Runtime observation retry requires a prior RepairPlan."
            )
        latest_repair_envelope = self.artifact_store.read(latest_repair_ref)
        latest_repair = latest_repair_envelope["data"]
        repair_context = latest_repair.get("repair_context")
        repair_upstreams = latest_repair_envelope.get("inputs", {}).get(
            "upstream_artifacts",
            [],
        )
        bound_runtime_upstreams = [
            item
            for item in repair_upstreams
            if isinstance(item, dict)
            and item.get("artifact_type") == "runtime_evidence"
        ]
        retry_budget = latest_repair.get("retry_budget")
        retry_budget_remaining = latest_repair.get("retry_budget_remaining")
        retry_number = len(runtime_revisions)
        if (
            latest_repair.get("failure_source") != "runtime"
            or latest_repair.get("requires_new_evidence") is not True
            or latest_repair.get("allowed_next_stage") is not None
            or latest_repair.get("retry_exhausted") is not False
            or not isinstance(repair_context, dict)
            or repair_context.get("failure_owner") != "observation"
            or repair_context.get("repair_decision")
            != "repair_runtime_observation"
            or repair_context.get("source_repair_allowed") is not False
            or bound_runtime_upstreams
            != [
                {
                    "artifact_type": "runtime_evidence",
                    "path": latest_runtime_ref.path,
                    "artifact_hash": latest_runtime_ref.artifact_hash,
                    "require_latest": True,
                }
            ]
            or isinstance(retry_budget, bool)
            or not isinstance(retry_budget, int)
            or retry_budget < 1
            or isinstance(retry_budget_remaining, bool)
            or not isinstance(retry_budget_remaining, int)
            or retry_budget_remaining < 1
        ):
            blockers.append(
                {
                    "code": "OBSERVATION_RETRY_REPAIR_PLAN_INELIGIBLE",
                    "message": (
                        "Latest RepairPlan does not authorize new observation "
                        "evidence without source repair."
                    ),
                }
            )
        if isinstance(retry_budget, int) and retry_number > retry_budget:
            blockers.append(
                {
                    "code": "OBSERVATION_RETRY_BUDGET_EXHAUSTED",
                    "message": "Runtime observation retry budget is exhausted.",
                }
            )
        effective_retry_budget_remaining = (
            min(
                retry_budget_remaining,
                retry_budget - retry_number + 1,
            )
            if isinstance(retry_budget, int)
            and isinstance(retry_budget_remaining, int)
            else 0
        )

        for artifact_type in ("eval_report", "workflow_summary"):
            for artifact_ref in self.artifact_store.list_feature_artifact_revisions(
                checkpoint_ref.feature_id,
                artifact_type,
            ):
                artifact = self.artifact_store.read(artifact_ref)["data"]
                if artifact.get("run_id") == checkpoint.get("run_id"):
                    blockers.append(
                        {
                            "code": "OBSERVATION_RETRY_TERMINAL_STATE_PRESENT",
                            "message": (
                                f"{artifact_type} already exists for this "
                                "Runtime handoff."
                            ),
                        }
                    )
                    break

        if blockers:
            raise ValueError(
                "Runtime observation retry was blocked: "
                + ", ".join(str(item.get("code")) for item in blockers)
            )
        decision = ResumeDecision(
            status="accepted",
            allowed=True,
            reason=(
                "Observation-owned Runtime result is ready for one bounded "
                "evidence retry."
            ),
            applied_updates=dict(report["applied_updates"]),
        )
        retry_binding = {
            "retry_number": retry_number,
            "retry_budget": retry_budget,
            "retry_budget_remaining_before_attempt": (
                effective_retry_budget_remaining
            ),
            "prior_runtime_evidence_ref": latest_runtime_ref.path,
            "prior_runtime_evidence_hash": latest_runtime_ref.artifact_hash,
            "prior_repair_plan_ref": latest_repair_ref.path,
            "prior_repair_plan_hash": latest_repair_ref.artifact_hash,
            "resume_report_ref": report_ref.path,
            "resume_report_hash": report_ref.artifact_hash,
            "new_checkpoint_would_be_created": False,
            "new_resume_report_would_be_created": False,
        }
        return (
            decision,
            report_ref,
            latest_runtime_ref,
            latest_repair_ref,
            retry_binding,
        )

    @staticmethod
    def langgraph_memory_checkpointer() -> MemorySaver:
        """Return the available local LangGraph memory checkpointer."""

        return MemorySaver()

    @staticmethod
    def _state_snapshot(state: ModAgentState) -> dict[str, Any]:
        return {
            "run_id": state["run_id"],
            "request_id": state["request_id"],
            "feature_id": state["feature_id"],
            "user_request": state["user_request"],
            "target_domain": state["target_domain"],
            "target_mod": state["target_mod"],
            "execution_path": state["execution_path"],
            "risk_level": state["risk_level"],
            "current_stage": state["current_stage"],
            "next_stage": state["next_stage"],
            "artifacts": dict(state["artifacts"]),
            "artifact_hashes": dict(state["artifact_hashes"]),
            "approvals": dict(state["approvals"]),
            "blockers": list(state["blockers"]),
            "warnings": list(state["warnings"]),
            "evidence_summary": dict(state["evidence_summary"]),
            "review_summary": dict(state["review_summary"]),
            "build_summary": dict(state["build_summary"]),
            "runtime_summary": dict(state["runtime_summary"]),
            "trace_events": list(state["trace_events"]),
            "retry_count": state["retry_count"],
        }

    def _resume_binding_from_state(self, state: ModAgentState) -> dict[str, Any]:
        binding: dict[str, Any] = {
            "patch_proposal_ref": None,
            "patch_proposal_hash": None,
            "proposal_review_ref": None,
            "proposal_review_hash": None,
            "diff_hash": None,
            "feature_spec_ref": None,
            "feature_spec_hash": None,
            "build_result_ref": None,
            "build_result_hash": None,
            "next_graph_node": None,
            "edit_authority_request_ref": None,
            "edit_authority_request_artifact_hash": None,
            "edit_authority_request_hash": None,
        }
        if "patch_proposal" in state["artifacts"]:
            proposal_ref = self._artifact_ref_from_state(state, "patch_proposal")
            proposal_payload = self.artifact_store.read(proposal_ref)["data"]
            binding["patch_proposal_ref"] = proposal_ref.path
            binding["patch_proposal_hash"] = proposal_ref.artifact_hash
            binding["diff_hash"] = self._diff_hash_from_patch_proposal(
                proposal_payload,
            )
        if "proposal_review" in state["artifacts"]:
            review_ref = self._artifact_ref_from_state(state, "proposal_review")
            binding["proposal_review_ref"] = review_ref.path
            binding["proposal_review_hash"] = review_ref.artifact_hash
        if "feature_spec" in state["artifacts"]:
            feature_ref = self._artifact_ref_from_state(state, "feature_spec")
            binding["feature_spec_ref"] = feature_ref.path
            binding["feature_spec_hash"] = feature_ref.artifact_hash
        if "build_result" in state["artifacts"]:
            build_ref = self._artifact_ref_from_state(state, "build_result")
            binding["build_result_ref"] = build_ref.path
            binding["build_result_hash"] = build_ref.artifact_hash
        if "edit_authority_request" in state["artifacts"]:
            request_ref = self._artifact_ref_from_state(
                state,
                "edit_authority_request",
            )
            request_payload = self.artifact_store.read(request_ref)["data"]
            binding["edit_authority_request_ref"] = request_ref.path
            binding["edit_authority_request_artifact_hash"] = (
                request_ref.artifact_hash
            )
            binding["edit_authority_request_hash"] = request_payload.get(
                "request_hash"
            )
        if state["current_stage"] == "build":
            binding["next_graph_node"] = "collect_runtime_evidence"
        return binding

    def _durable_consumption_state(
        self,
        feature_id: str,
        *,
        checkpoint_id: str,
        resume_id: str,
    ) -> tuple[bool, bool]:
        consumed = False
        seen_resume_id = False
        for ref in self.artifact_store.list_feature_artifact_revisions(
            feature_id,
            "resume_report",
        ):
            report = self.artifact_store.read(ref)["data"]
            if report.get("allowed") is not True:
                continue
            consumed = consumed or report.get("checkpoint_id") == checkpoint_id
            seen_resume_id = seen_resume_id or report.get("resume_id") == resume_id
        return consumed, seen_resume_id

    def _latest_revision_ref(
        self,
        feature_id: str,
        artifact_type: str,
    ) -> ArtifactRef | None:
        """Resolve the latest pointer back to its immutable revision."""

        latest_refs = [
            ref
            for ref in self.artifact_store.list_feature_artifacts(feature_id)
            if ref.artifact_type == artifact_type
        ]
        if not latest_refs:
            return None
        if len(latest_refs) != 1:
            raise ArtifactStoreError(
                f"Multiple latest pointers found for {artifact_type}."
            )
        matching_revisions = [
            ref
            for ref in self.artifact_store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
            if ref.artifact_hash == latest_refs[0].artifact_hash
        ]
        if len(matching_revisions) != 1:
            raise ArtifactStoreError(
                f"Latest {artifact_type} pointer does not resolve uniquely."
            )
        return matching_revisions[0]

    def _checkpoint_lineage_blockers(
        self,
        checkpoint_ref: ArtifactRef,
        checkpoint_envelope: dict[str, Any],
        *,
        allow_prior_runtime_state: bool = False,
    ) -> list[dict[str, Any]]:
        checkpoint = checkpoint_envelope["data"]
        snapshot = checkpoint.get("state_snapshot")
        artifact_hashes = checkpoint.get("artifact_hashes")
        artifact_refs = checkpoint.get("artifact_refs")
        upstream = checkpoint_envelope.get("inputs", {}).get("upstream_artifacts", [])
        blockers: list[dict[str, Any]] = []
        if (
            not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("artifacts"), dict)
            or not isinstance(snapshot.get("artifact_hashes"), dict)
            or not isinstance(artifact_hashes, dict)
            or not isinstance(artifact_refs, list)
        ):
            return [
                {
                    "code": "CHECKPOINT_LINEAGE_INVALID",
                    "message": "Checkpoint state and Artifact bindings are incomplete.",
                }
            ]
        upstream_by_type = {
            item.get("artifact_type"): item
            for item in upstream
            if isinstance(item, dict) and isinstance(item.get("artifact_type"), str)
        }
        snapshot_artifacts = snapshot["artifacts"]
        snapshot_hashes = snapshot["artifact_hashes"]
        if (
            checkpoint.get("run_id") != snapshot.get("run_id")
            or checkpoint.get("request_id") != snapshot.get("request_id")
            or checkpoint.get("feature_id") != snapshot.get("feature_id")
            or checkpoint_ref.feature_id != checkpoint.get("feature_id")
            or checkpoint.get("checkpoint_stage") != snapshot.get("current_stage")
            or set(artifact_refs) != set(snapshot_artifacts.values())
            or artifact_hashes != snapshot_hashes
            or set(upstream_by_type) != set(snapshot_artifacts)
        ):
            blockers.append(
                {
                    "code": "CHECKPOINT_LINEAGE_MISMATCH",
                    "message": "Checkpoint identity, state, or Artifact bindings disagree.",
                }
            )
            return blockers
        for artifact_type, path in snapshot_artifacts.items():
            item = upstream_by_type.get(artifact_type)
            if (
                item is None
                or item.get("path") != path
                or item.get("artifact_hash") != snapshot_hashes.get(artifact_type)
            ):
                blockers.append(
                    {
                        "code": "CHECKPOINT_ARTIFACT_BINDING_MISMATCH",
                        "message": (
                            f"Checkpoint Artifact binding disagrees for {artifact_type}."
                        ),
                    }
                )
        if checkpoint.get("checkpoint_stage") == "build":
            blockers.extend(
                self._build_handoff_blockers(
                    checkpoint,
                    allow_prior_runtime_state=allow_prior_runtime_state,
                )
            )
        return blockers

    def _build_handoff_blockers(
        self,
        checkpoint: dict[str, Any],
        *,
        allow_prior_runtime_state: bool = False,
    ) -> list[dict[str, Any]]:
        snapshot = checkpoint["state_snapshot"]
        required = {"feature_spec", "build_result"}
        missing = sorted(required - set(snapshot["artifacts"]))
        if missing:
            return [
                {
                    "code": "BUILD_HANDOFF_ARTIFACT_MISSING",
                    "message": f"Build handoff is missing required Artifacts: {missing}",
                }
            ]
        binding = checkpoint.get("resume_binding") or {}
        if (
            binding.get("feature_spec_ref") != snapshot["artifacts"]["feature_spec"]
            or binding.get("feature_spec_hash")
            != snapshot["artifact_hashes"]["feature_spec"]
            or binding.get("build_result_ref") != snapshot["artifacts"]["build_result"]
            or binding.get("build_result_hash")
            != snapshot["artifact_hashes"]["build_result"]
            or binding.get("next_graph_node") != "collect_runtime_evidence"
        ):
            return [
                {
                    "code": "BUILD_HANDOFF_BINDING_MISMATCH",
                    "message": "Build handoff does not bind the expected Runtime graph entry.",
                }
            ]
        build_ref = ArtifactRef(
            feature_id=checkpoint["feature_id"],
            artifact_type="build_result",
            path=snapshot["artifacts"]["build_result"],
            artifact_hash=snapshot["artifact_hashes"]["build_result"],
        )
        build = self.artifact_store.read(build_ref)["data"]
        if (
            build.get("status") != "success"
            or build.get("claims_real_build_success") is not True
        ):
            return [
                {
                    "code": "BUILD_HANDOFF_NOT_SUCCESSFUL",
                    "message": "Runtime continuation requires a successful real Build.",
                }
            ]
        verified_artifacts = build.get("verified_artifacts")
        if (
            not isinstance(verified_artifacts, list)
            or not verified_artifacts
            or (build.get("artifact_verification") or {}).get("status") != "verified"
        ):
            return [
                {
                    "code": "BUILD_OUTPUT_VERIFICATION_MISSING",
                    "message": (
                        "Runtime continuation requires at least one verified "
                        "physical Build output."
                    ),
                }
            ]
        blockers: list[dict[str, Any]] = []
        if not allow_prior_runtime_state:
            for runtime_ref in self.artifact_store.list_feature_artifact_revisions(
                checkpoint["feature_id"],
                "runtime_evidence",
            ):
                runtime = self.artifact_store.read(runtime_ref)["data"]
                if runtime.get("run_id") == checkpoint.get("run_id"):
                    blockers.append(
                        {
                            "code": "PRIOR_RUNTIME_STATE_PRESENT",
                            "message": (
                                "Runtime evidence already exists for this "
                                "handoff run; automatic repetition is blocked."
                            ),
                        }
                    )
                    return blockers
        for artifact in verified_artifacts:
            if not isinstance(artifact, dict):
                blockers.append(
                    {
                        "code": "BUILD_OUTPUT_BINDING_INVALID",
                        "message": "Build output binding is not structured.",
                    }
                )
                continue
            resolved_path = artifact.get("resolved_path")
            expected_hash = artifact.get("sha256")
            if not isinstance(resolved_path, str) or not isinstance(expected_hash, str):
                blockers.append(
                    {
                        "code": "BUILD_OUTPUT_BINDING_INVALID",
                        "message": "Build output path or SHA256 is missing.",
                    }
                )
                continue
            path = Path(resolved_path)
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
            ):
                blockers.append(
                    {
                        "code": "BUILD_OUTPUT_BYTES_CHANGED",
                        "message": f"Verified Build output changed: {resolved_path}",
                    }
                )
        return blockers

    @staticmethod
    def _diff_hash_from_patch_proposal(proposal_payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            proposal_payload["diff_intent"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _artifact_refs_from_state(state: ModAgentState) -> list[ArtifactRef]:
        refs = []
        for artifact_type, path in state["artifacts"].items():
            artifact_hash = state["artifact_hashes"].get(artifact_type)
            if artifact_hash is None:
                raise ArtifactStoreError(
                    f"Missing artifact hash for state artifact: {artifact_type}"
                )
            refs.append(
                ArtifactRef(
                    feature_id=state["feature_id"] or state["request_id"],
                    artifact_type=artifact_type,
                    path=path,
                    artifact_hash=artifact_hash,
                )
            )
        return refs

    @staticmethod
    def _artifact_ref_from_state(
        state: ModAgentState,
        artifact_type: str,
    ) -> ArtifactRef:
        artifact_hash = state["artifact_hashes"].get(artifact_type)
        if artifact_hash is None:
            raise ArtifactStoreError(
                f"Missing artifact hash for state artifact: {artifact_type}"
            )
        return ArtifactRef(
            feature_id=state["feature_id"] or state["request_id"],
            artifact_type=artifact_type,
            path=state["artifacts"][artifact_type],
            artifact_hash=artifact_hash,
        )
