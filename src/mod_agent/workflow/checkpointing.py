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

    def _checkpoint_lineage_blockers(
        self,
        checkpoint_ref: ArtifactRef,
        checkpoint_envelope: dict[str, Any],
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
            blockers.extend(self._build_handoff_blockers(checkpoint))
        return blockers

    def _build_handoff_blockers(
        self,
        checkpoint: dict[str, Any],
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
                            "Runtime evidence already exists for this handoff run; "
                            "automatic repetition is blocked."
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
