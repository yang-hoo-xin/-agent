"""Factual Patch input for the host evaluator already prepared for this attempt."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatchVerificationCapability:
    recovery_enabled: bool

    def model_view(self) -> dict[str, Any]:
        return {
            "action": "submit_candidate",
            "mechanism": "normal_final_patch_response",
            "automatic_evaluation": {
                "configured": True,
                "trigger": "after_normal_patch_submission_checks",
                "owner": "configured_host_behavior_evaluator",
                "check_scope": "evaluator_defined",
                "outcome": "not_established_by_this_capability",
            },
            "feedback": {
                "mode": "existing_recovery_loop" if self.recovery_enabled else "single_behavior_correction",
                "budget": "remaining_model_and_observation_budget",
                "eligible_failures_only": True,
            },
            "source_scope_and_delivery_authorization": "unchanged",
        }


def prepared_verification_capability(
    evaluator: Callable[..., Any] | None, *, recovery_enabled: bool,
) -> PatchVerificationCapability | None:
    """Call after the existing evaluator preparation succeeds; never invoke it here.

    为什么要有它：模型需要知道正常候选提交会进入真实验收，配置事实不能代替验收结果或扩展权限。
    """
    return PatchVerificationCapability(recovery_enabled) if callable(evaluator) else None


VERIFICATION_CAPABILITY_GUIDANCE = (
    " Submit a candidate through the normal final Patch response to run the configured evaluator; "
    "eligible failures can return through the existing bounded feedback path, and configuration is not a passed result."
)
