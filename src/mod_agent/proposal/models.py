"""Contracts for patch proposal and review gate artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

ReviewDecision = Literal[
    "approve_dry_run",
    "revise_proposal",
    "blocked_insufficient_evidence",
    "blocked_scope_risk",
    "blocked_requires_human",
    "already_satisfied",
]

SemanticAssuranceVerdict = Literal[
    "satisfied_within_boundary",
    "violated",
    "unproven",
]
SemanticAssuranceMethod = Literal[
    "formal_proof",
    "static_analysis",
    "unit_test",
    "build",
    "runtime_observation",
    "human_review",
    "not_available",
]

_SEMANTIC_ASSURANCE_SCHEMA_VERSION = "semantic_assurance_v1"
_SEMANTIC_ASSURANCE_FIELDS = {
    "schema_version",
    "verdict",
    "assurance_method",
    "evidence_refs",
    "limitations",
    "assumptions",
    "applicability",
    "invalidation_facts",
}
_SEMANTIC_ASSURANCE_VERDICTS = {
    "satisfied_within_boundary",
    "violated",
    "unproven",
}
_SEMANTIC_ASSURANCE_METHODS = {
    "formal_proof",
    "static_analysis",
    "unit_test",
    "build",
    "runtime_observation",
    "human_review",
    "not_available",
}
_HUMAN_SEMANTIC_REVIEW_NOTE = (
    "Semantic assurance is unproven; human semantic review of the exact dry-run "
    "diff is required before isolated apply."
)


@dataclass(frozen=True)
class SemanticAssuranceV1:
    """Evidence-bound Feature-to-code semantic assurance result."""

    verdict: SemanticAssuranceVerdict
    assurance_method: SemanticAssuranceMethod
    evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]
    assumptions: tuple[str, ...]
    applicability: tuple[str, ...]
    invalidation_facts: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.verdict not in _SEMANTIC_ASSURANCE_VERDICTS:
            raise ValueError("Semantic assurance verdict is unsupported.")
        if self.assurance_method not in _SEMANTIC_ASSURANCE_METHODS:
            raise ValueError("Semantic assurance assurance_method is unsupported.")
        _validate_string_tuple("evidence_refs", self.evidence_refs, allow_empty=True)
        _validate_string_tuple("limitations", self.limitations)
        _validate_string_tuple("assumptions", self.assumptions)
        _validate_string_tuple("applicability", self.applicability)
        _validate_string_tuple("invalidation_facts", self.invalidation_facts)
        if self.assurance_method == "not_available":
            if self.verdict != "unproven":
                raise ValueError(
                    "Semantic assurance not_available method requires unproven verdict."
                )
            if self.evidence_refs:
                raise ValueError(
                    "Semantic assurance not_available method cannot claim evidence_refs."
                )
        if self.verdict in {"satisfied_within_boundary", "violated"}:
            if self.assurance_method == "not_available" or not self.evidence_refs:
                raise ValueError(
                    "Semantic assurance satisfied or violated verdict requires "
                    "an applicable method and evidence_refs."
                )

    @classmethod
    def unproven(cls) -> "SemanticAssuranceV1":
        """Return the honest V0 result when no applicable verifier is bound."""

        return cls(
            verdict="unproven",
            assurance_method="not_available",
            evidence_refs=(),
            limitations=(
                "No applicable semantic verifier result is bound to this proposal.",
            ),
            assumptions=(
                "Human review will evaluate Feature-to-code semantics on the exact "
                "dry-run diff before isolated apply.",
            ),
            applicability=(
                "This result covers only the absence of a bound semantic verifier "
                "for this proposal.",
            ),
            invalidation_facts=(
                "A verifier result or any proposal, source, binding, or exact-diff "
                "identity change invalidates this result.",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the strict versioned JSON projection."""

        return {
            "schema_version": _SEMANTIC_ASSURANCE_SCHEMA_VERSION,
            "verdict": self.verdict,
            "assurance_method": self.assurance_method,
            "evidence_refs": list(self.evidence_refs),
            "limitations": list(self.limitations),
            "assumptions": list(self.assumptions),
            "applicability": list(self.applicability),
            "invalidation_facts": list(self.invalidation_facts),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SemanticAssuranceV1":
        """Strictly reconstruct a serialized semantic assurance result."""

        if not isinstance(value, Mapping) or set(value) != _SEMANTIC_ASSURANCE_FIELDS:
            raise ValueError(
                "Semantic assurance fields must exactly match the V1 contract."
            )
        if value.get("schema_version") != _SEMANTIC_ASSURANCE_SCHEMA_VERSION:
            raise ValueError("Semantic assurance schema_version is unsupported.")
        list_fields = (
            "evidence_refs",
            "limitations",
            "assumptions",
            "applicability",
            "invalidation_facts",
        )
        for name in list_fields:
            if not isinstance(value.get(name), list):
                raise ValueError(f"Semantic assurance {name} must be a JSON list.")
        return cls(
            verdict=value.get("verdict"),
            assurance_method=value.get("assurance_method"),
            evidence_refs=tuple(value["evidence_refs"]),
            limitations=tuple(value["limitations"]),
            assumptions=tuple(value["assumptions"]),
            applicability=tuple(value["applicability"]),
            invalidation_facts=tuple(value["invalidation_facts"]),
        )


def _validate_string_tuple(
    name: str,
    value: tuple[str, ...],
    *,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, tuple) or (not allow_empty and not value):
        raise ValueError(
            f"Semantic assurance {name} must contain non-empty strings."
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(
            f"Semantic assurance {name} must contain non-empty strings."
        )


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
    semantic_assurance: SemanticAssuranceV1 = field(
        default_factory=SemanticAssuranceV1.unproven
    )
    blocked: bool = False
    blockers: tuple[dict[str, Any], ...] = ()

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the patch_proposal contract."""

        manual_review_notes = list(self.manual_review_notes)
        if (
            self.semantic_assurance.verdict == "unproven"
            and _HUMAN_SEMANTIC_REVIEW_NOTE not in manual_review_notes
        ):
            manual_review_notes.append(_HUMAN_SEMANTIC_REVIEW_NOTE)
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
            "manual_review_notes": manual_review_notes,
            "semantic_assurance": self.semantic_assurance.to_dict(),
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
    critic_gate: dict[str, Any]
    semantic_assurance: SemanticAssuranceV1 = field(
        default_factory=SemanticAssuranceV1.unproven
    )
    human_semantic_review_required: bool = True

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
            "critic_gate": self.critic_gate,
            "semantic_assurance": self.semantic_assurance.to_dict(),
            "human_semantic_review_required": self.human_semantic_review_required,
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
            "hook_target_binding_id": change.get("hook_target_binding_id"),
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
