"""Evidence-bound repair planning and retry-budget contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from src.mod_agent.proposal import PatchProposal
from src.mod_agent.proposal.models import (
    build_change_units,
    build_context_pack,
    build_no_op_status,
    build_rollback_hints,
    stable_proposal_id,
)

FailureSource = Literal["build", "runtime", "eval"]


@dataclass(frozen=True)
class RepairPlan:
    """Structured repair plan created from real failure evidence."""

    repair_id: str
    feature_id: str
    failure_source: FailureSource
    failure_class: str
    evidence_refs: tuple[str, ...]
    hypothesis: str
    minimal_changes: tuple[dict[str, Any], ...]
    retry_count: int
    retry_budget: int
    retry_budget_remaining: int
    retry_exhausted: bool
    scope_expansion_allowed: bool
    stop_condition: str
    forbidden_regressions: tuple[str, ...]
    requires_new_evidence: bool
    allowed_next_stage: str | None
    blockers: tuple[dict[str, Any], ...] = ()
    target_behavior: str | None = None

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the repair_plan artifact contract."""

        return {
            "node_name": "create_repair_plan",
            "stage": "repair_plan",
            "message": (
                "Repair plan created from failure evidence."
                if not self.retry_exhausted
                else "Repair retry budget exhausted; repair is blocked."
            ),
            "repair_id": self.repair_id,
            "feature_id": self.feature_id,
            "failure_source": self.failure_source,
            "failure_class": self.failure_class,
            "failure_evidence": list(self.evidence_refs),
            "evidence_refs": list(self.evidence_refs),
            "root_cause_hypotheses": [self.hypothesis],
            "hypothesis": self.hypothesis,
            "recommended_fix_strategy": self._recommended_fix_strategy(),
            "minimal_changes": list(self.minimal_changes),
            "retry_count": self.retry_count,
            "retry_budget": self.retry_budget,
            "retry_budget_remaining": self.retry_budget_remaining,
            "retry_exhausted": self.retry_exhausted,
            "scope_expansion_allowed": self.scope_expansion_allowed,
            "stop_condition": self.stop_condition,
            "forbidden_regressions": list(self.forbidden_regressions),
            "requires_new_evidence": self.requires_new_evidence,
            "allowed_next_stage": self.allowed_next_stage,
            "blockers": list(self.blockers),
            "target_behavior": self.target_behavior,
        }

    def _recommended_fix_strategy(self) -> str:
        if self.retry_exhausted:
            return "Stop automated repair and request new evidence or human review."
        if self.minimal_changes:
            return "Generate an intent-only repair proposal scoped to the failure evidence."
        return "Request more evidence before proposing repair changes."


class RepairPlanner:
    """Create repair plans from build or runtime failure artifacts."""

    def __init__(self, retry_budget: int = 2) -> None:
        if retry_budget < 0:
            raise ValueError("retry_budget must be non-negative")
        self.retry_budget = retry_budget

    def from_build_failure(
        self,
        *,
        build_result: dict[str, Any],
        build_result_ref: str,
        retry_count: int,
        target_behavior: str | None = None,
    ) -> RepairPlan:
        """Create a repair plan from a failed build_result artifact."""

        feature_id = str(build_result.get("feature_id") or "unknown_feature")
        failure_class = str(build_result.get("error_class") or "unknown")
        evidence_refs = _unique_strings(
            [
                build_result_ref,
                *build_result.get("repair_handoff", {}).get("failure_evidence_refs", []),
                *self._diagnostic_refs(build_result),
            ]
        )
        exhausted = retry_count >= self.retry_budget
        minimal_changes = () if exhausted else self._minimal_build_changes(build_result)
        blockers = self._blockers(
            exhausted=exhausted,
            evidence_refs=evidence_refs,
            minimal_changes=minimal_changes,
        )
        next_retry_count = retry_count if exhausted else retry_count + 1
        return RepairPlan(
            repair_id=stable_repair_id(
                feature_id=feature_id,
                failure_source="build",
                failure_class=failure_class,
                retry_count=next_retry_count,
                evidence_refs=evidence_refs,
            ),
            feature_id=feature_id,
            failure_source="build",
            failure_class=failure_class,
            evidence_refs=evidence_refs,
            hypothesis=_hypothesis_for_build_error(failure_class),
            minimal_changes=minimal_changes,
            retry_count=next_retry_count,
            retry_budget=self.retry_budget,
            retry_budget_remaining=max(self.retry_budget - retry_count, 0),
            retry_exhausted=exhausted,
            scope_expansion_allowed=False,
            stop_condition="Stop if the same failure class persists after retry budget.",
            forbidden_regressions=(
                "Do not change unrelated behavior.",
                "Do not expand patch scope without new evidence.",
            ),
            requires_new_evidence=failure_class == "unknown",
            allowed_next_stage=None if exhausted or blockers else "generate_patch_proposal",
            blockers=blockers,
            target_behavior=target_behavior,
        )

    def from_runtime_failure(
        self,
        *,
        runtime_evidence: dict[str, Any],
        runtime_evidence_ref: str,
        retry_count: int,
        target_behavior: str | None = None,
    ) -> RepairPlan:
        """Create a repair plan from failed runtime evidence."""

        feature_id = str(runtime_evidence.get("feature_id") or "unknown_feature")
        failure_class = str(
            runtime_evidence.get("acceptance_status")
            or runtime_evidence.get("verification_status")
            or "runtime_unverified"
        )
        evidence_refs = _unique_strings(
            [
                runtime_evidence_ref,
                *(
                    item.get("locator")
                    for item in runtime_evidence.get("evidence_items", [])
                    if isinstance(item, dict)
                ),
            ]
        )
        exhausted = retry_count >= self.retry_budget
        minimal_changes = () if exhausted else self._minimal_runtime_changes(runtime_evidence)
        blockers = self._blockers(
            exhausted=exhausted,
            evidence_refs=evidence_refs,
            minimal_changes=minimal_changes,
        )
        next_retry_count = retry_count if exhausted else retry_count + 1
        return RepairPlan(
            repair_id=stable_repair_id(
                feature_id=feature_id,
                failure_source="runtime",
                failure_class=failure_class,
                retry_count=next_retry_count,
                evidence_refs=evidence_refs,
            ),
            feature_id=feature_id,
            failure_source="runtime",
            failure_class=failure_class,
            evidence_refs=evidence_refs,
            hypothesis="Runtime evidence did not prove the requested acceptance criteria.",
            minimal_changes=minimal_changes,
            retry_count=next_retry_count,
            retry_budget=self.retry_budget,
            retry_budget_remaining=max(self.retry_budget - retry_count, 0),
            retry_exhausted=exhausted,
            scope_expansion_allowed=False,
            stop_condition="Stop if runtime acceptance remains unverified after retry budget.",
            forbidden_regressions=(
                "Do not claim gameplay success without acceptance evidence.",
                "Do not broaden runtime behavior without new evidence.",
            ),
            requires_new_evidence=True,
            allowed_next_stage=None if exhausted or blockers else "generate_patch_proposal",
            blockers=blockers,
            target_behavior=target_behavior,
        )

    @staticmethod
    def _diagnostic_refs(build_result: dict[str, Any]) -> tuple[str, ...]:
        refs = []
        for index, diagnostic in enumerate(build_result.get("diagnostics", [])):
            if not isinstance(diagnostic, dict):
                continue
            code = diagnostic.get("code") or "unknown"
            file_name = diagnostic.get("file") or "unknown_file"
            line = diagnostic.get("line") or "unknown_line"
            refs.append(f"build_diag:{index}:{code}:{file_name}:{line}")
        return tuple(refs)

    @staticmethod
    def _minimal_build_changes(build_result: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        changes = []
        diagnostics = list(build_result.get("diagnostics", []))
        for index, diagnostic in enumerate(diagnostics):
            if not isinstance(diagnostic, dict):
                continue
            target_file = diagnostic.get("file")
            if not target_file:
                continue
            changes.append(
                {
                    "change_id": f"repair_build_{index}",
                    "target_file": target_file,
                    "intent": (
                        "Repair the compiler diagnostic using the referenced "
                        "failure evidence."
                    ),
                    "failure_code": diagnostic.get("code"),
                    "failure_message": diagnostic.get("message"),
                }
            )
        return tuple(changes)

    @staticmethod
    def _minimal_runtime_changes(
        runtime_evidence: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        source = next(
            (
                str(item.get("source"))
                for item in runtime_evidence.get("evidence_items", [])
                if isinstance(item, dict) and item.get("source")
            ),
            "runtime_evidence",
        )
        return (
            {
                "change_id": "repair_runtime_0",
                "target_file": source,
                "intent": "Adjust implementation so runtime evidence can satisfy acceptance.",
                "failure_code": runtime_evidence.get("acceptance_status"),
                "failure_message": runtime_evidence.get("message"),
            },
        )

    @staticmethod
    def _blockers(
        *,
        exhausted: bool,
        evidence_refs: tuple[str, ...],
        minimal_changes: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        blockers: list[dict[str, Any]] = []
        if exhausted:
            blockers.append(
                {
                    "stage": "repair_plan",
                    "code": "RETRY_BUDGET_EXHAUSTED",
                    "message": "Repair retry budget is exhausted.",
                }
            )
        if not evidence_refs:
            blockers.append(
                {
                    "stage": "repair_plan",
                    "code": "MISSING_FAILURE_EVIDENCE",
                    "message": "Repair plan cannot proceed without failure evidence.",
                }
            )
        if not minimal_changes and not exhausted:
            blockers.append(
                {
                    "stage": "repair_plan",
                    "code": "REPAIR_SCOPE_UNRESOLVED",
                    "message": "Failure evidence does not identify a safe repair scope.",
                }
            )
        return tuple(blockers)


class RepairPatchProposalBuilder:
    """Convert a repair_plan into an intent-only patch proposal."""

    def build(self, repair_plan: dict[str, Any]) -> PatchProposal:
        """Return a reviewable repair patch proposal without editing files."""

        feature_id = str(repair_plan.get("feature_id") or "unknown_feature")
        evidence_refs = tuple(str(ref) for ref in repair_plan.get("evidence_refs", []))
        blockers = tuple(repair_plan.get("blockers") or ())
        if repair_plan.get("retry_exhausted") or blockers:
            return PatchProposal(
                proposal_id=stable_proposal_id(feature_id, evidence_refs),
                feature_id=feature_id,
                summary="Repair proposal blocked.",
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
                no_op_status=build_no_op_status(
                    is_no_op=True,
                    reason="Repair plan is blocked before proposal review.",
                ),
                rollback_hints=(),
                manual_review_notes=("Repair plan is blocked before proposal review.",),
                blocked=True,
                blockers=blockers,
            )

        minimal_changes = list(repair_plan.get("minimal_changes") or [])
        files = tuple(
            dict.fromkeys(
                str(change["target_file"])
                for change in minimal_changes
                if isinstance(change, dict) and change.get("target_file")
            )
        )
        diff_intent = tuple(
            self._repair_change_intent(
                index=index,
                repair_plan=repair_plan,
                change=change,
                evidence_refs=evidence_refs,
            )
            for index, change in enumerate(minimal_changes)
            if isinstance(change, dict) and change.get("target_file")
        )
        if not files or not diff_intent:
            return PatchProposal(
                proposal_id=stable_proposal_id(feature_id, evidence_refs),
                feature_id=feature_id,
                summary="Repair proposal blocked.",
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
                no_op_status=build_no_op_status(
                    is_no_op=True,
                    reason="Repair plan has no scoped change intent.",
                ),
                rollback_hints=(),
                manual_review_notes=("Repair plan has no scoped change intent.",),
                blocked=True,
                blockers=(
                    {
                        "code": "REPAIR_SCOPE_UNRESOLVED",
                        "message": "Repair plan did not produce scoped file changes.",
                    },
                ),
            )

        target_behavior = str(repair_plan.get("target_behavior") or feature_id)
        change_units = build_change_units(diff_intent)
        scope_boundary = tuple(repair_plan.get("forbidden_regressions") or ())
        return PatchProposal(
            proposal_id=stable_proposal_id(feature_id, evidence_refs),
            feature_id=feature_id,
            summary=(
                f"Repair proposal for {target_behavior} after "
                f"{repair_plan.get('failure_source')} failure."
            ),
            files=files,
            diff_intent=diff_intent,
            change_units=change_units,
            context_pack=build_context_pack(
                feature_id=feature_id,
                files=files,
                evidence_refs=evidence_refs,
                evidence_source_paths=files,
                scope_boundary=scope_boundary,
                change_units=change_units,
            ),
            evidence_refs=evidence_refs,
            scope_boundary=scope_boundary,
            risk_assessment={
                "risk_level": "medium",
                "requires_manual_review": True,
                "repair_id": repair_plan.get("repair_id"),
                "scope_expansion_allowed": bool(
                    repair_plan.get("scope_expansion_allowed", False)
                ),
            },
            expected_tests=(
                "re-run dry_run_apply",
                "re-run build",
                "preserve original acceptance criteria",
            ),
            no_op_status=build_no_op_status(is_no_op=False, reason=None),
            rollback_hints=build_rollback_hints(diff_intent),
            manual_review_notes=(
                "Repair proposal must pass review before dry-run apply.",
                str(repair_plan.get("stop_condition") or ""),
            ),
            blocked=False,
        )

    @staticmethod
    def _repair_change_intent(
        *,
        index: int,
        repair_plan: dict[str, Any],
        change: dict[str, Any],
        evidence_refs: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "change_id": change.get("change_id") or f"repair_change_{index}",
            "change_type": "repair",
            "target_file": change.get("target_file"),
            "target_symbol": change.get("target_symbol"),
            "operation": "modify",
            "rationale": (
                f"{repair_plan.get('hypothesis')} "
                f"Intent: {change.get('intent')}"
            ),
            "evidence_refs": list(evidence_refs),
            "expected_validation": [
                "repair_plan reviewed",
                "dry-run apply remains isolated",
                "build/runtime failure evidence is rechecked",
            ],
            "rollback_hint": "Use git change metadata and artifact refs for rollback.",
        }


def stable_repair_id(
    *,
    feature_id: str,
    failure_source: str,
    failure_class: str,
    retry_count: int,
    evidence_refs: tuple[str, ...],
) -> str:
    """Create a stable repair id for a failure evidence set."""

    seed = "|".join(
        [
            feature_id,
            failure_source,
            failure_class,
            str(retry_count),
            ",".join(evidence_refs),
        ]
    )
    return "repair_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _hypothesis_for_build_error(failure_class: str) -> str:
    return {
        "syntax_error": "Generated code does not satisfy the compiler syntax contract.",
        "missing_reference": "A referenced type or assembly is unavailable in the build profile.",
        "namespace_error": "The referenced namespace differs from indexed source evidence.",
        "api_mismatch": "The referenced API shape differs from available code evidence.",
        "il2cpp_access_error": "The patch touches an IL2CPP member that is not safely accessible.",
        "config_binding_error": "Configuration binding does not match the current config contract.",
        "unsafe_path_error": "Build output indicates an unsafe path or access violation.",
        "unknown": "Build failed but the current classifier cannot identify a precise root cause.",
    }.get(failure_class, "Failure evidence requires a scoped repair hypothesis.")


def _unique_strings(values: list[Any]) -> tuple[str, ...]:
    result = []
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)
