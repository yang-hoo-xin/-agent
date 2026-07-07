"""Artifact-backed checkpoint and resume helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
        "review_proposal",
        "dry_run_apply",
        "collect_runtime_evidence",
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
        }


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

        checkpoint_envelope = self.artifact_store.read(checkpoint_ref)
        checkpoint = checkpoint_envelope["data"]
        freshness = self.artifact_store.check_direct_freshness(checkpoint_ref)
        if not freshness.is_fresh:
            decision = ResumeDecision(
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
        elif (
            payload.resume_id in self._seen_resume_ids
            or checkpoint["checkpoint_id"] in self._consumed_checkpoint_ids
        ):
            decision = ResumeDecision(
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
        else:
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
        )
        report_ref = self.artifact_store.write(
            feature_id=checkpoint_ref.feature_id,
            artifact_type="resume_report",
            payload=report.to_artifact_payload(),
            status="success" if decision.allowed else "blocked",
            upstream_refs=[checkpoint_ref],
            allow_stale_upstreams=not decision.allowed and bool(decision.stale_reasons),
        )
        return decision, report_ref

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
            "current_stage": state["current_stage"],
            "next_stage": state["next_stage"],
            "execution_path": state["execution_path"],
            "risk_level": state["risk_level"],
            "target_domain": state["target_domain"],
            "target_mod": state["target_mod"],
            "retry_count": state["retry_count"],
            "artifacts": dict(state["artifacts"]),
            "artifact_hashes": dict(state["artifact_hashes"]),
        }

    def _resume_binding_from_state(self, state: ModAgentState) -> dict[str, Any]:
        binding: dict[str, Any] = {
            "patch_proposal_ref": None,
            "patch_proposal_hash": None,
            "proposal_review_ref": None,
            "proposal_review_hash": None,
            "diff_hash": None,
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
        return binding

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
