"""Feature spec drafting from request plans."""

from __future__ import annotations

from typing import Any

from .models import FeatureSpec, RequestPlan


class FeatureSpecBuilder:
    """Convert route decisions into verifiable feature specs."""

    def build(
        self,
        plan: RequestPlan,
        *,
        planning_brief: dict[str, Any] | None = None,
    ) -> FeatureSpec:
        """Return a feature spec that can gate evidence retrieval."""

        blocking_uncertainties = [
            uncertainty
            for uncertainty in plan.uncertainties
            if uncertainty.severity == "blocking"
        ]
        if plan.blocked or blocking_uncertainties:
            return FeatureSpec(
                feature_id=plan.feature_id,
                user_request=plan.user_request,
                target_behavior="",
                non_goals=self._brief_non_goals(planning_brief),
                target_mod=plan.target_mod,
                risk_level=plan.risk_level,
                acceptance_criteria=(),
                evidence_requirements=tuple(self._brief_evidence_requirements(planning_brief)),
                runtime_verification_plan=(),
                hook_requirement=dict(plan.hook_requirement),
                request_interpretation=dict(plan.request_interpretation),
                blocked=True,
                blockers=tuple(
                    {
                        "code": uncertainty.uncertainty_id.upper(),
                        "message": uncertainty.question,
                    }
                    for uncertainty in blocking_uncertainties
                ),
            )

        evidence_requirements: list[str] = []
        if plan.requires_hook_evidence:
            evidence_requirements.extend(["target method", "call timing", "side effect boundary"])
        if plan.hook_requirement.get("required") is True:
            evidence_requirements.append("concrete hook target method identity")
        evidence_requirements = self._merge_unique(
            evidence_requirements,
            self._brief_evidence_requirements(planning_brief),
        )

        runtime_verification = ["compile or static validation"]
        if plan.requires_runtime_evidence:
            runtime_verification.extend(
                [
                    "startup_loaded",
                    "target_path_executed",
                    "acceptance_evidence_observed",
                    "non_goals_preserved",
                ]
            )
        runtime_verification = self._merge_unique(
            runtime_verification,
            self._brief_runtime_expectations(planning_brief),
        )

        return FeatureSpec(
            feature_id=plan.feature_id,
            user_request=plan.user_request,
            target_behavior=plan.user_request,
            non_goals=self._brief_non_goals(planning_brief),
            target_mod=plan.target_mod,
            risk_level=plan.risk_level,
            acceptance_criteria=(
                f"Requested behavior is implemented: {plan.user_request}",
                "Every proposed change is bound to evidence.",
                "Validation output is reported with real command or artifact evidence.",
            ),
            evidence_requirements=tuple(evidence_requirements),
            runtime_verification_plan=tuple(runtime_verification),
            hook_requirement=dict(plan.hook_requirement),
            request_interpretation=dict(plan.request_interpretation),
            blocked=False,
        )

    @staticmethod
    def _brief_non_goals(planning_brief: dict[str, Any] | None) -> tuple[str, ...]:
        selected = planning_brief.get("selected_plan") if isinstance(planning_brief, dict) else None
        values = selected.get("non_goals") if isinstance(selected, dict) else None
        # 为什么要有它：明确提供的用户限制必须保留，不能按文本与平台政策相似就从语义输入中删除。
        return tuple(str(item) for item in values) if isinstance(values, (list, tuple)) else ()

    @staticmethod
    def _brief_evidence_requirements(
        planning_brief: dict[str, Any] | None,
    ) -> list[str]:
        handoff = planning_brief.get("handoff") if isinstance(planning_brief, dict) else {}
        if not isinstance(handoff, dict):
            return []
        guidance = handoff.get("feature_spec_guidance")
        if not isinstance(guidance, dict):
            return []
        values = guidance.get("evidence_requirements")
        if not isinstance(values, (list, tuple)):
            return []
        return [str(item) for item in values]

    @staticmethod
    def _brief_runtime_expectations(
        planning_brief: dict[str, Any] | None,
    ) -> list[str]:
        handoff = planning_brief.get("handoff") if isinstance(planning_brief, dict) else {}
        if not isinstance(handoff, dict):
            return []
        values = handoff.get("runtime_verification_expectations")
        if not isinstance(values, (list, tuple)):
            return []
        return [str(item) for item in values]

    @staticmethod
    def _merge_unique(primary: list[str], secondary: list[str]) -> tuple[str, ...]:
        merged: list[str] = []
        for item in [*primary, *secondary]:
            if item and item not in merged:
                merged.append(item)
        return tuple(merged)
