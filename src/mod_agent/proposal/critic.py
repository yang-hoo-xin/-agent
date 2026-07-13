"""ProposalCritic local/injected assessment boundary for patch proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

CriticVerdict = Literal["pass", "revise", "block", "unresolved"]
CriticFindingLevel = Literal["info", "warning", "blocking"]

CRITIC_DIMENSIONS = (
    "evidence_grounding",
    "scope_discipline",
    "verification_quality",
    "reversibility",
)
CRITIC_PASS_THRESHOLD = 80
CRITIC_POLICY_VERSION = "proposal_critic_local_injected_v1"
CRITIC_APPLICABILITY = "patch_proposal_review_only"
CRITIC_AGGREGATION = "equal_weight_rounded_mean"


@dataclass(frozen=True)
class CriticFinding:
    """One structured issue raised by ProposalCritic."""

    dimension: str
    level: CriticFindingLevel
    message: str
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable finding."""

        return {
            "dimension": self.dimension,
            "level": self.level,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class CriticAssessment:
    """Structured, read-only assessment consumed by deterministic review."""

    assessor_id: str
    assessor_kind: Literal["rule_based", "model", "test", "unresolved"]
    subject_artifact_ref: str
    subject_artifact_hash: str
    dimension_scores: dict[str, int]
    total_score: int
    verdict: CriticVerdict
    findings: tuple[CriticFinding, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        expected = set(CRITIC_DIMENSIONS)
        actual = set(self.dimension_scores)
        if actual != expected:
            raise ValueError(
                "Critic dimension_scores must use exactly: "
                + ", ".join(CRITIC_DIMENSIONS)
            )
        values = [*self.dimension_scores.values(), self.total_score]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("Critic scores must be integers.")
        if any(value < 0 or value > 100 for value in values):
            raise ValueError("Critic scores must be between 0 and 100.")
        expected_total = round(sum(self.dimension_scores.values()) / len(CRITIC_DIMENSIONS))
        if self.total_score != expected_total:
            raise ValueError("Critic total_score must equal the rounded dimension average.")
        if not self.assessor_id.strip():
            raise ValueError("Critic assessor_id must not be empty.")
        if not self.subject_artifact_ref or not self.subject_artifact_hash:
            raise ValueError("Critic subject artifact ref and hash are required.")

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the critic_assessment contract."""

        return {
            "node_name": "review_proposal",
            "stage": "proposal_review",
            "message": f"ProposalCritic assessment verdict: {self.verdict}.",
            "assessor_id": self.assessor_id,
            "assessor_kind": self.assessor_kind,
            "independence_boundary": "read_only_no_route_authority",
            "subject_type": "patch_proposal",
            "subject_artifact_ref": self.subject_artifact_ref,
            "subject_artifact_hash": self.subject_artifact_hash,
            "score_scale": {"minimum": 0, "maximum": 100},
            "dimension_scores": dict(self.dimension_scores),
            "total_score": self.total_score,
            "policy_threshold": CRITIC_PASS_THRESHOLD,
            "policy_version": CRITIC_POLICY_VERSION,
            "applicability": CRITIC_APPLICABILITY,
            "aggregation_method": CRITIC_AGGREGATION,
            "dimension_weights": {dimension: 25 for dimension in CRITIC_DIMENSIONS},
            "verdict": self.verdict,
            "findings": [finding.to_dict() for finding in self.findings],
            "limitations": list(self.limitations),
        }


class ProposalCritic(Protocol):
    """Read-only specialist boundary; implementations receive no route or write tools."""

    def assess(
        self,
        proposal: dict[str, Any],
        *,
        subject_artifact_ref: str,
        subject_artifact_hash: str,
    ) -> CriticAssessment:
        """Score one proposal and bind the result to its exact artifact revision."""


class RuleBasedProposalCritic:
    """Local deterministic Critic used without external source disclosure."""

    assessor_id = "local_rule_based_proposal_critic_v1"

    def assess(
        self,
        proposal: dict[str, Any],
        *,
        subject_artifact_ref: str,
        subject_artifact_hash: str,
    ) -> CriticAssessment:
        """Score evidence, scope, verification, and reversibility."""

        findings: list[CriticFinding] = []
        changes = [item for item in proposal.get("diff_intent") or [] if isinstance(item, dict)]
        files = {str(path) for path in proposal.get("files") or [] if path}
        context_pack = (
            proposal.get("context_pack")
            if isinstance(proposal.get("context_pack"), dict)
            else {}
        )
        allowed_edit_binding_ids = {
            str(binding_id)
            for binding_id in context_pack.get("allowed_edit_binding_ids") or []
            if binding_id
        }
        evidence_refs = {
            str(ref) for ref in proposal.get("evidence_refs") or [] if ref
        }

        grounded_changes = [
            change
            for change in changes
            if change.get("edit_binding_id") or change.get("evidence_refs")
        ]
        evidence_score = _coverage_score(len(grounded_changes), len(changes))
        if not evidence_refs or evidence_score < 100:
            findings.append(
                CriticFinding(
                    dimension="evidence_grounding",
                    level="blocking",
                    message="Not every proposed change is grounded by declared evidence or an edit binding.",
                    evidence_refs=tuple(sorted(evidence_refs)),
                )
            )

        scoped_changes = [
            change
            for change in changes
            if (
                change.get("edit_binding_id")
                and str(change["edit_binding_id"]) in allowed_edit_binding_ids
            )
            or (_display_target(change) is not None and _display_target(change) in files)
        ]
        scope_score = _coverage_score(len(scoped_changes), len(changes))
        if not files or scope_score < 100:
            findings.append(
                CriticFinding(
                    dimension="scope_discipline",
                    level="blocking",
                    message="Not every proposed change resolves to the proposal file scope.",
                )
            )

        expected_tests = [item for item in proposal.get("expected_tests") or [] if item]
        verification_score = 100 if expected_tests else 0
        if verification_score < 100:
            findings.append(
                CriticFinding(
                    dimension="verification_quality",
                    level="warning",
                    message="The proposal does not declare a verification step.",
                )
            )

        rollback_change_ids = {
            str(item.get("change_unit_id"))
            for item in proposal.get("rollback_hints") or []
            if isinstance(item, dict) and item.get("change_unit_id") and item.get("rollback_hint")
        }
        change_ids = {
            str(change.get("change_id") or f"change_{index:03d}")
            for index, change in enumerate(changes, start=1)
        }
        reversibility_score = _coverage_score(
            len(change_ids & rollback_change_ids),
            len(change_ids),
        )
        if reversibility_score < 100:
            findings.append(
                CriticFinding(
                    dimension="reversibility",
                    level="warning",
                    message="Rollback guidance does not cover every proposed change.",
                )
            )

        dimension_scores = {
            "evidence_grounding": evidence_score,
            "scope_discipline": scope_score,
            "verification_quality": verification_score,
            "reversibility": reversibility_score,
        }
        total_score = round(sum(dimension_scores.values()) / len(CRITIC_DIMENSIONS))
        if any(finding.level == "blocking" for finding in findings):
            verdict: CriticVerdict = "block"
        elif total_score < CRITIC_PASS_THRESHOLD:
            verdict = "revise"
        else:
            verdict = "pass"
        return CriticAssessment(
            assessor_id=self.assessor_id,
            assessor_kind="rule_based",
            subject_artifact_ref=subject_artifact_ref,
            subject_artifact_hash=subject_artifact_hash,
            dimension_scores=dimension_scores,
            total_score=total_score,
            verdict=verdict,
            findings=tuple(findings),
            limitations=(
                "Local structural scoring does not prove semantic correctness or runtime behavior.",
            ),
        )


def _coverage_score(covered: int, total: int) -> int:
    if total <= 0:
        return 0
    return round((covered / total) * 100)


def _display_target(change: dict[str, Any]) -> str | None:
    value = change.get("display_file") or change.get("target_file")
    return str(value) if value else None
