"""Build reviewable patch proposals from implementation plans."""

from __future__ import annotations

from typing import Any

from .models import (
    PatchProposal,
    build_change_units,
    build_context_pack,
    build_no_op_status,
    build_rollback_hints,
    stable_proposal_id,
)


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
        unresolved_changes = [
            change
            for change in proposed_changes
            if not change.get("edit_target_path")
        ]
        if not files or unresolved_changes:
            return self._blocked(
                feature_id=feature_id,
                evidence_refs=evidence_refs,
                blockers=(
                    {
                        "code": "EDIT_TARGET_UNRESOLVED",
                        "message": (
                            "Patch proposal requires implementation_plan edit_target_path "
                            "values resolved before review."
                        ),
                    },
                ),
                note="Implementation plan did not resolve edit targets.",
            )

        expected_tests = tuple(implementation_plan.get("test_plan") or ())
        diff_intent = tuple(self._change_intent(change) for change in proposed_changes)
        change_units = build_change_units(diff_intent)
        scope_boundary = tuple(implementation_plan.get("side_effect_boundaries") or ())
        context_pack = build_context_pack(
            feature_id=feature_id,
            files=files,
            evidence_refs=evidence_refs,
            evidence_source_paths=tuple(
                implementation_plan.get("evidence_source_paths") or ()
            ),
            scope_boundary=scope_boundary,
            change_units=change_units,
        )
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
            change_units=change_units,
            context_pack=context_pack,
            evidence_refs=evidence_refs,
            scope_boundary=scope_boundary,
            risk_assessment={
                "risk_tags": risk_tags,
                "risk_level": self._risk_level(risk_tags),
                "requires_manual_review": "high" in risk_tags,
            },
            expected_tests=expected_tests,
            no_op_status=build_no_op_status(is_no_op=False, reason=None),
            rollback_hints=build_rollback_hints(diff_intent),
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
            "target_file": change.get("edit_target_path"),
            "edit_target_path": change.get("edit_target_path"),
            "evidence_source_path": change.get("evidence_source_path"),
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
        no_op = note == "No change units were present."
        return PatchProposal(
            proposal_id=stable_proposal_id(feature_id, evidence_refs),
            feature_id=feature_id,
            summary="Patch proposal blocked.",
            files=(),
            diff_intent=(),
            change_units=(),
            context_pack=build_context_pack(
                feature_id=feature_id,
                files=(),
                evidence_refs=evidence_refs,
                evidence_source_paths=(),
                scope_boundary=(),
                change_units=(),
            ),
            evidence_refs=evidence_refs,
            scope_boundary=(),
            risk_assessment={"risk_level": "blocked", "requires_manual_review": True},
            expected_tests=(),
            no_op_status=build_no_op_status(is_no_op=no_op, reason=note),
            rollback_hints=(),
            manual_review_notes=(note,),
            blocked=True,
            blockers=blockers,
        )
