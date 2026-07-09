"""Interrupt and resume payload contracts for controlled workflow pauses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .state import StageName


@dataclass(frozen=True)
class InterruptRequest:
    """Structured request for a human-controlled workflow interrupt."""

    interrupt_id: str
    run_id: str
    feature_id: str
    stage: StageName
    reason: str
    payload: dict[str, Any]
    resume_allowed_fields: tuple[str, ...]
    artifact_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable interrupt request."""

        return {
            "interrupt_id": self.interrupt_id,
            "run_id": self.run_id,
            "feature_id": self.feature_id,
            "stage": self.stage,
            "reason": self.reason,
            "payload": self.payload,
            "resume_allowed_fields": list(self.resume_allowed_fields),
            "artifact_refs": list(self.artifact_refs),
        }


@dataclass(frozen=True)
class ResumePayload:
    """Human resume payload matching the DEV_SPEC resume contract."""

    resume_id: str
    run_id: str
    stage: str
    decision: str
    approved_by: str
    approved_at: str
    artifact_refs: tuple[str, ...]
    diff_hash: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable resume payload."""

        return {
            "resume_id": self.resume_id,
            "run_id": self.run_id,
            "stage": self.stage,
            "decision": self.decision,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "artifact_refs": list(self.artifact_refs),
            "diff_hash": self.diff_hash,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ResumeDecision:
    """Validation result for a resume attempt."""

    status: str
    allowed: bool
    reason: str
    applied_updates: dict[str, Any]
    blockers: tuple[dict[str, Any], ...] = ()
    stale_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable resume decision."""

        return {
            "status": self.status,
            "allowed": self.allowed,
            "reason": self.reason,
            "applied_updates": self.applied_updates,
            "blockers": list(self.blockers),
            "stale_reasons": list(self.stale_reasons),
        }


class ResumeValidator:
    """Validate resume payloads against checkpoint and interrupt policy."""

    RESUME_ALLOWED_FIELDS: dict[str, tuple[str, ...]] = {
        "plan_request": ("user_request", "target_mod"),
        "proposal_review": ("approvals.review",),
        "review_proposal": ("approvals.review",),
        "dry_run_apply": ("approvals.dry_run",),
        "confirmed_apply": ("approvals.confirmed_write",),
        "collect_runtime_evidence": ("runtime_evidence.manual",),
    }

    ALLOWED_DECISIONS = frozenset({"approve", "reject", "correct", "provide_evidence"})

    def validate(
        self,
        payload: ResumePayload,
        *,
        checkpoint: dict[str, Any],
    ) -> ResumeDecision:
        """Validate a resume payload against one checkpoint artifact."""

        blockers: list[dict[str, Any]] = []
        if payload.run_id != checkpoint.get("run_id"):
            blockers.append(
                {
                    "code": "RESUME_RUN_MISMATCH",
                    "message": "Resume payload run_id does not match checkpoint.",
                }
            )
        if payload.stage != checkpoint.get("checkpoint_stage"):
            blockers.append(
                {
                    "code": "RESUME_STAGE_MISMATCH",
                    "message": "Resume payload stage does not match checkpoint.",
                }
            )
        if payload.decision not in self.ALLOWED_DECISIONS:
            blockers.append(
                {
                    "code": "RESUME_DECISION_UNSUPPORTED",
                    "message": "Resume decision is not supported.",
                }
            )
        if payload.decision == "approve" and not payload.approved_by:
            blockers.append(
                {
                    "code": "RESUME_APPROVER_MISSING",
                    "message": "Approved resume payload must include approved_by.",
                }
            )
        missing_refs = sorted(
            set(checkpoint.get("artifact_refs", [])) - set(payload.artifact_refs)
        )
        if missing_refs:
            blockers.append(
                {
                    "code": "RESUME_ARTIFACT_REFS_MISSING",
                    "message": "Resume payload omits checkpoint artifact refs.",
                    "artifact_refs": missing_refs,
                }
            )
        expected_diff_hash = (checkpoint.get("resume_binding") or {}).get("diff_hash")
        if expected_diff_hash and payload.diff_hash != expected_diff_hash:
            blockers.append(
                {
                    "code": "RESUME_DIFF_HASH_MISMATCH",
                    "message": "Resume payload diff_hash does not match checkpoint.",
                    "expected_diff_hash": expected_diff_hash,
                    "provided_diff_hash": payload.diff_hash,
                }
            )
        if blockers:
            return ResumeDecision(
                status="blocked",
                allowed=False,
                reason="Resume payload failed validation.",
                applied_updates={},
                blockers=tuple(blockers),
            )
        return ResumeDecision(
            status="accepted",
            allowed=True,
            reason="Resume payload accepted.",
            applied_updates=self._updates_for(payload, checkpoint=checkpoint),
        )

    def _updates_for(
        self,
        payload: ResumePayload,
        *,
        checkpoint: dict[str, Any],
    ) -> dict[str, Any]:
        allowed_fields = self.RESUME_ALLOWED_FIELDS.get(payload.stage, ())
        restored_state = dict(checkpoint.get("state_snapshot", {}))
        if payload.decision == "approve" and payload.stage in {
            "proposal_review",
            "review_proposal",
        }:
            return {
                "approvals": {"review": True},
                "allowed_fields": list(allowed_fields),
                "restored_state": restored_state,
            }
        if payload.decision == "approve" and payload.stage == "dry_run_apply":
            return {
                "approvals": {"dry_run": True},
                "allowed_fields": list(allowed_fields),
                "restored_state": restored_state,
            }
        return {
            "allowed_fields": list(allowed_fields),
            "decision": payload.decision,
            "restored_state": restored_state,
        }
