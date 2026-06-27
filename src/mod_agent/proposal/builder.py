"""Build reviewable patch proposals from implementation plans."""

from __future__ import annotations

from typing import Any

from .models import PatchProposal, stable_proposal_id


class PatchProposalBuilder:
    """Convert an implementation plan into patch intent without editing files."""

    def build(self, implementation_plan: dict[str, Any]) -> PatchProposal:
        """Return a patch proposal or a blocked proposal."""

        feature_id = str(implementation_plan.get("feature_id") or "unknown_feature")
        evidence_refs = tuple(implementation_plan.get("evidence_refs") or ())

        if implementation_plan.get("blocking"):
            return self._blocked(
                feature_id=feature_id,
                evidence_refs=evidence_refs,
                blockers=tuple(implementation_plan.get("blockers") or ()),
                note="Implementation plan is blocking.",
            )

        proposed_changes = list(implementation_plan.get("proposed_changes") or [])
        if not proposed_changes:
            return self._blocked(
                feature_id=feature_id,
                evidence_refs=evidence_refs,
                blockers=(
                    {
                        "code": "NO_OP_PROPOSAL",
                        "message": "Implementation plan contains no proposed changes.",
                    },
                ),
                note="No change units were present.",
            )

        files = tuple(dict.fromkeys(implementation_plan.get("target_files") or ()))
        expected_tests = tuple(implementation_plan.get("test_plan") or ())
        diff_intent = tuple(self._change_intent(change) for change in proposed_changes)
        risk_tags = sorted(
            {
                risk
                for change in proposed_changes
                for risk in change.get("risk_tags", [])
                if isinstance(risk, str)
            }
        )

        return PatchProposal(
            proposal_id=stable_proposal_id(feature_id, evidence_refs),
            feature_id=feature_id,
            summary=f"Proposal for {feature_id} with {len(diff_intent)} change unit(s).",
            files=files,
            diff_intent=diff_intent,
            evidence_refs=evidence_refs,
            scope_boundary=tuple(implementation_plan.get("side_effect_boundaries") or ()),
            risk_assessment={
                "risk_tags": risk_tags,
                "risk_level": self._risk_level(risk_tags),
                "requires_manual_review": "high" in risk_tags,
            },
            expected_tests=expected_tests,
            manual_review_notes=tuple(
                "High-risk proposal requires human review before real apply."
                for _ in [0]
                if "high" in risk_tags
            ),
            blocked=False,
        )

    @staticmethod
    def _change_intent(change: dict[str, Any]) -> dict[str, Any]:
        return {
            "change_id": change.get("change_id"),
            "change_type": change.get("change_type"),
            "target_file": change.get("target_file"),
            "target_symbol": change.get("target_symbol"),
            "operation": change.get("operation"),
            "rationale": change.get("rationale"),
            "evidence_refs": list(change.get("evidence_refs") or []),
            "expected_validation": list(change.get("expected_validation") or []),
            "rollback_hint": change.get("rollback_hint"),
        }

    @staticmethod
    def _risk_level(risk_tags: list[str]) -> str:
        if "high" in risk_tags:
            return "high"
        if "medium" in risk_tags:
            return "medium"
        return "low"

    @staticmethod
    def _blocked(
        *,
        feature_id: str,
        evidence_refs: tuple[str, ...],
        blockers: tuple[dict[str, Any], ...],
        note: str,
    ) -> PatchProposal:
        return PatchProposal(
            proposal_id=stable_proposal_id(feature_id, evidence_refs),
            feature_id=feature_id,
            summary="Patch proposal blocked.",
            files=(),
            diff_intent=(),
            evidence_refs=evidence_refs,
            scope_boundary=(),
            risk_assessment={"risk_level": "blocked", "requires_manual_review": True},
            expected_tests=(),
            manual_review_notes=(note,),
            blocked=True,
            blockers=blockers,
        )
