"""Rule-based patch proposal review gate."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .models import ProposalReview, ReviewFinding

CHECKED_RULES = (
    "schema_validity",
    "evidence_binding",
    "scope_boundary",
    "target_alignment",
    "risk_policy",
    "forbidden_paths",
    "permission_level",
    "test_plan_presence",
    "no_op_detection",
)


class ProposalReviewer:
    """Evaluate a patch proposal before dry-run apply is allowed."""

    def review(
        self,
        proposal: dict[str, Any],
        *,
        evidence_pack: dict[str, Any] | None = None,
        feature_spec: dict[str, Any] | None = None,
        permission_level: str = "dry_run_write",
    ) -> ProposalReview:
        """Return a composite review decision."""

        findings: list[ReviewFinding] = []
        diff_intent = list(proposal.get("diff_intent") or [])
        evidence_ids = self._evidence_ids(evidence_pack)
        proposal_evidence_refs = set(proposal.get("evidence_refs") or [])
        allowed_files = set(proposal.get("files") or [])

        if proposal.get("blocked"):
            findings.append(
                ReviewFinding(
                    rule_id="schema_validity",
                    level="blocking",
                    message="Proposal is already marked blocked.",
                )
            )

        if not diff_intent:
            findings.append(
                ReviewFinding(
                    rule_id="no_op_detection",
                    level="blocking",
                    message="Proposal has no change intent and would be a no-op.",
                )
            )

        if permission_level != "dry_run_write":
            findings.append(
                ReviewFinding(
                    rule_id="permission_level",
                    level="blocking",
                    message="Only dry_run_write proposals may advance to dry-run apply.",
                )
            )

        if not proposal.get("expected_tests"):
            findings.append(
                ReviewFinding(
                    rule_id="test_plan_presence",
                    level="blocking",
                    message="Proposal must declare expected tests or validation steps.",
                )
            )

        if feature_spec and not self._target_aligned(proposal, feature_spec):
            findings.append(
                ReviewFinding(
                    rule_id="target_alignment",
                    level="blocking",
                    message="Proposal summary/rationale does not align with target behavior.",
                )
            )

        if proposal.get("risk_assessment", {}).get("requires_manual_review"):
            findings.append(
                ReviewFinding(
                    rule_id="risk_policy",
                    level="warning",
                    message="Proposal declares manual review requirement before real apply.",
                )
            )

        for change in diff_intent:
            change_id = change.get("change_id")
            refs = tuple(change.get("evidence_refs") or ())
            target_file = change.get("target_file")
            if not refs:
                findings.append(
                    ReviewFinding(
                        rule_id="evidence_binding",
                        level="blocking",
                        message="Change unit has no evidence refs.",
                        change_id=change_id,
                    )
                )
            elif evidence_ids and not set(refs).issubset(evidence_ids):
                findings.append(
                    ReviewFinding(
                        rule_id="evidence_binding",
                        level="blocking",
                        message="Change unit references evidence not present in evidence pack.",
                        change_id=change_id,
                        evidence_refs=refs,
                    )
                )
            elif not set(refs).issubset(proposal_evidence_refs):
                findings.append(
                    ReviewFinding(
                        rule_id="evidence_binding",
                        level="blocking",
                        message="Change unit evidence refs are not declared at proposal level.",
                        change_id=change_id,
                        evidence_refs=refs,
                    )
                )

            if target_file not in allowed_files:
                findings.append(
                    ReviewFinding(
                        rule_id="scope_boundary",
                        level="blocking",
                        message="Change unit target file is outside proposal file list.",
                        change_id=change_id,
                    )
                )

            if target_file and self._is_forbidden_path(str(target_file)):
                findings.append(
                    ReviewFinding(
                        rule_id="forbidden_paths",
                        level="blocking",
                        message="Change unit targets a forbidden or unsafe path.",
                        change_id=change_id,
                    )
                )

        blocking = [finding for finding in findings if finding.level == "blocking"]
        if blocking:
            decision = self._blocked_decision(blocking)
            return ProposalReview(
                decision=decision,
                findings=tuple(findings),
                required_changes=tuple(finding.message for finding in blocking),
                allowed_next_stage=None,
                checked_rules=CHECKED_RULES,
                trace_metrics={
                    "num_changes_checked": len(diff_intent),
                    "num_blocking_findings": len(blocking),
                },
            )

        return ProposalReview(
            decision="approve_dry_run",
            findings=tuple(findings),
            required_changes=(),
            allowed_next_stage="dry_run_apply",
            checked_rules=CHECKED_RULES,
            trace_metrics={
                "num_changes_checked": len(diff_intent),
                "num_blocking_findings": 0,
            },
        )

    @staticmethod
    def _evidence_ids(evidence_pack: dict[str, Any] | None) -> set[str]:
        if evidence_pack is None:
            return set()
        return {
            item["evidence_id"]
            for item in evidence_pack.get("items", [])
            if item.get("evidence_id")
        }

    @staticmethod
    def _target_aligned(proposal: dict[str, Any], feature_spec: dict[str, Any]) -> bool:
        target = str(feature_spec.get("target_behavior") or "").lower()
        if not target:
            return True
        haystack = " ".join(
            [
                str(proposal.get("summary") or ""),
                " ".join(str(change.get("rationale") or "") for change in proposal.get("diff_intent", [])),
            ]
        ).lower()
        return any(token in haystack for token in target.split() if len(token) > 3)

    @staticmethod
    def _is_forbidden_path(path: str) -> bool:
        normalized = path.replace("\\", "/")
        posix = PurePosixPath(normalized)
        parts = set(posix.parts)
        if ".." in parts:
            return True
        forbidden_parts = {".git", ".env", "secrets"}
        return bool(parts & forbidden_parts)

    @staticmethod
    def _blocked_decision(blocking: list[ReviewFinding]) -> str:
        rule_ids = {finding.rule_id for finding in blocking}
        if "evidence_binding" in rule_ids:
            return "blocked_insufficient_evidence"
        if "scope_boundary" in rule_ids or "forbidden_paths" in rule_ids:
            return "blocked_scope_risk"
        if "permission_level" in rule_ids or "risk_policy" in rule_ids:
            return "blocked_requires_human"
        return "revise_proposal"
