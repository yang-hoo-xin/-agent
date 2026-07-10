"""Contracts for patch proposal and review gate artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

ReviewDecision = Literal[
    "approve_dry_run",
    "revise_proposal",
    "blocked_insufficient_evidence",
    "blocked_scope_risk",
    "blocked_requires_human",
    "already_satisfied",
]


@dataclass(frozen=True)
class PatchProposal:
    """Reviewable patch intent, not an applied diff."""

    proposal_id: str
    feature_id: str
    summary: str
    files: tuple[str, ...]
    diff_intent: tuple[dict[str, Any], ...]
    change_units: tuple[dict[str, Any], ...]
    context_pack: dict[str, Any]
    evidence_refs: tuple[str, ...]
    scope_boundary: tuple[str, ...]
    risk_assessment: dict[str, Any]
    expected_tests: tuple[str, ...]
    no_op_status: dict[str, Any]
    rollback_hints: tuple[dict[str, Any], ...]
    manual_review_notes: tuple[str, ...] = ()
    blocked: bool = False
    blockers: tuple[dict[str, Any], ...] = ()

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the patch_proposal contract."""

        return {
            "node_name": "generate_patch_proposal",
            "stage": "patch_proposal",
            "message": (
                "Patch proposal is ready for review."
                if not self.blocked
                else "Patch proposal is blocked before review."
            ),
            "proposal_id": self.proposal_id,
            "feature_id": self.feature_id,
            "summary": self.summary,
            "files": list(self.files),
            "diff_intent": list(self.diff_intent),
            "change_units": list(self.change_units),
            "context_pack": self.context_pack,
            "evidence_refs": list(self.evidence_refs),
            "scope_boundary": list(self.scope_boundary),
            "risk_assessment": self.risk_assessment,
            "expected_tests": list(self.expected_tests),
            "no_op_status": self.no_op_status,
            "rollback_hints": list(self.rollback_hints),
            "manual_review_notes": list(self.manual_review_notes),
            "blocked": self.blocked,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ReviewFinding:
    """Structured finding emitted by a review rule."""

    rule_id: str
    level: str
    message: str
    change_id: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable finding."""

        return {
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
            "change_id": self.change_id,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ProposalReview:
    """Composite review gate result."""

    decision: ReviewDecision
    findings: tuple[ReviewFinding, ...]
    required_changes: tuple[str, ...]
    allowed_next_stage: str | None
    checked_rules: tuple[str, ...]
    trace_metrics: dict[str, int]

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the proposal_review contract."""

        return {
            "node_name": "review_proposal",
            "stage": "proposal_review",
            "message": f"Proposal review decision: {self.decision}.",
            "decision": self.decision,
            "findings": [finding.to_dict() for finding in self.findings],
            "required_changes": list(self.required_changes),
            "allowed_next_stage": self.allowed_next_stage,
            "checked_rules": list(self.checked_rules),
            "trace_metrics": self.trace_metrics,
        }


def stable_proposal_id(feature_id: str, evidence_refs: tuple[str, ...]) -> str:
    """Create a stable proposal id for a feature/evidence set."""

    seed = f"{feature_id}:{','.join(evidence_refs)}"
    return "proposal_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def build_change_units(diff_intent: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    """Create explicit change-unit metadata from reviewable diff intent."""

    return tuple(
        {
            "change_unit_id": str(change.get("change_id") or f"change_{index:03d}"),
            "change_type": change.get("change_type"),
            "edit_binding_id": change.get("edit_binding_id"),
            "supporting_binding_ids": list(change.get("supporting_binding_ids") or []),
            "target_file": change.get("display_file"),
            "edit_target_path": change.get("display_file"),
            "target_symbol": None,
            "evidence_refs": list(change.get("evidence_refs") or []),
            "expected_validation": list(change.get("expected_validation") or []),
            "rollback_hint": change.get("rollback_hint"),
        }
        for index, change in enumerate(diff_intent, start=1)
    )


def build_context_pack(
    *,
    feature_id: str,
    files: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    evidence_source_paths: tuple[str, ...],
    scope_boundary: tuple[str, ...],
    change_units: tuple[dict[str, Any], ...],
    source_snippets: tuple[dict[str, Any], ...] = (),
    target_symbol_signatures: tuple[dict[str, Any], ...] = (),
    binding_registry_ref: dict[str, Any] | None = None,
    display_files: tuple[str, ...] = (),
    allowed_edit_binding_ids: tuple[str, ...] = (),
    artifact_hashes: dict[str, str] | None = None,
    implementation_plan_hash: str | None = None,
    git_binding: dict[str, Any] | None = None,
    git_binding_required: bool = False,
    context_budget: dict[str, Any] | None = None,
    omission_blockers: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Create proposal context consumed by review, dashboard, and repair."""

    return {
        "feature_id": feature_id,
        "files": list(files),
        "evidence_refs": list(evidence_refs),
        "evidence_source_paths": list(evidence_source_paths),
        "scope_boundary": list(scope_boundary),
        "change_unit_ids": [
            str(unit.get("change_unit_id"))
            for unit in change_units
            if unit.get("change_unit_id")
        ],
        "source_snippets": [dict(snippet) for snippet in source_snippets],
        "target_symbol_signatures": [
            dict(signature) for signature in target_symbol_signatures
        ],
        "binding_registry_ref": dict(binding_registry_ref or {}),
        "display_files": list(display_files),
        "display_fields_authority": "derived_non_authoritative",
        "allowed_edit_binding_ids": list(allowed_edit_binding_ids),
        "artifact_hashes": dict(artifact_hashes or {}),
        "implementation_plan_hash": implementation_plan_hash,
        "git_binding": dict(git_binding or {}),
        "git_binding_required": git_binding_required,
        "context_budget": dict(context_budget or _empty_context_budget()),
        "omission_blockers": [dict(blocker) for blocker in omission_blockers],
    }


def _empty_context_budget() -> dict[str, Any]:
    return {
        "source_snippet_count": 0,
        "source_snippet_chars": 0,
        "source_snippet_char_limit": 0,
        "omitted_source_snippet_count": 0,
    }


def build_no_op_status(
    *,
    is_no_op: bool,
    reason: str | None,
) -> dict[str, Any]:
    """Create explicit no-op status for proposal gate decisions."""

    return {
        "is_no_op": is_no_op,
        "reason": reason,
    }


def build_rollback_hints(
    diff_intent: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Collect rollback hints per change unit."""

    return tuple(
        {
            "change_unit_id": str(change.get("change_id") or f"change_{index:03d}"),
            "rollback_hint": change.get("rollback_hint"),
        }
        for index, change in enumerate(diff_intent, start=1)
        if change.get("rollback_hint")
    )
