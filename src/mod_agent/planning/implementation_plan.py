"""Implementation planning from feature specs and evidence packs."""

from __future__ import annotations

from typing import Any

from .models import FeatureSpec, ImplementationPlan


class ImplementationPlanner:
    """Create an evidence-bound implementation plan without producing a patch."""

    def build(
        self,
        *,
        feature_spec: FeatureSpec,
        evidence_pack: dict[str, Any],
    ) -> ImplementationPlan:
        """Return an implementation plan or a blocking result."""

        if feature_spec.blocked:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=feature_spec.blockers,
                open_questions=("Feature spec is blocked.",),
            )

        if evidence_pack.get("readiness") != "sufficient" or not evidence_pack.get(
            "can_generate_patch"
        ):
            blockers = tuple(evidence_pack.get("blockers") or ())
            open_questions = tuple(
                str(gap) for gap in evidence_pack.get("gaps", ["Evidence is not sufficient."])
            )
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=blockers,
                open_questions=open_questions,
            )

        items = list(evidence_pack.get("items") or [])
        evidence_refs = tuple(
            item["evidence_id"] for item in items if item.get("evidence_id")
        )
        target_files = tuple(
            dict.fromkeys(item["source_path"] for item in items if item.get("source_path"))
        )
        target_symbols = tuple(
            dict.fromkeys(item["symbol"] for item in items if item.get("symbol"))
        )
        if not evidence_refs or not target_files:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "MISSING_EVIDENCE_BINDING",
                        "message": "Sufficient readiness was claimed without evidence refs or target files.",
                    },
                ),
                open_questions=("Evidence pack lacks concrete target files or evidence ids.",),
            )

        proposed_changes = tuple(
            {
                "change_id": f"chg_{index:03d}",
                "change_type": "modify_behavior",
                "target_file": item.get("source_path"),
                "target_symbol": item.get("symbol"),
                "operation": "minimal_evidence_bound_change",
                "rationale": feature_spec.target_behavior,
                "evidence_refs": [item["evidence_id"]],
                "risk_tags": [feature_spec.risk_level],
                "expected_validation": list(feature_spec.runtime_verification_plan),
                "rollback_hint": "Revert this change unit or restore previous behavior.",
            }
            for index, item in enumerate(items, start=1)
            if item.get("evidence_id") and item.get("source_path")
        )

        return ImplementationPlan(
            feature_id=feature_spec.feature_id,
            target_files=target_files,
            target_symbols=target_symbols,
            evidence_refs=evidence_refs,
            proposed_changes=proposed_changes,
            side_effect_boundaries=feature_spec.non_goals,
            test_plan=feature_spec.runtime_verification_plan,
            rollback_plan=tuple(
                f"Rollback {change['change_id']}: {change['rollback_hint']}"
                for change in proposed_changes
            ),
            open_questions=(),
            blocking=False,
        )

    @staticmethod
    def _blocked(
        *,
        feature_id: str,
        blockers: tuple[dict[str, Any], ...],
        open_questions: tuple[str, ...],
    ) -> ImplementationPlan:
        return ImplementationPlan(
            feature_id=feature_id,
            target_files=(),
            target_symbols=(),
            evidence_refs=(),
            proposed_changes=(),
            side_effect_boundaries=(),
            test_plan=(),
            rollback_plan=(),
            open_questions=open_questions,
            blocking=True,
            blockers=blockers,
        )
