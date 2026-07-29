"""Evidence-bound repair planning and retry-budget contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from src.mod_agent.bindings import BindingResolver
from src.mod_agent.proposal import PatchProposal
from src.mod_agent.proposal.models import (
    build_change_units,
    build_context_pack,
    build_no_op_status,
    build_rollback_hints,
    stable_proposal_id,
)
from src.mod_agent.runtime.evidence import normalize_runtime_failure_ownership

FailureSource = Literal["build", "runtime", "eval", "proposal_review"]


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
    allowed_edit_binding_ids: tuple[str, ...] = ()
    source_proposal: dict[str, Any] | None = None
    display_files: tuple[str, ...] = ()
    failure_findings: tuple[dict[str, Any], ...] = ()
    repair_context: dict[str, Any] | None = None
    resolved_repair_target: dict[str, Any] | None = None

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
            "allowed_edit_binding_ids": list(self.allowed_edit_binding_ids),
            "source_proposal": dict(self.source_proposal or {}),
            "display_files": list(self.display_files),
            "failure_findings": [dict(finding) for finding in self.failure_findings],
            "repair_context": dict(self.repair_context or {}),
            "resolved_repair_target": dict(self.resolved_repair_target or {}),
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
        proposal_context_pack: dict[str, Any] | None = None,
        implementation_plan: dict[str, Any] | None = None,
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
        allowed_binding_ids = _allowed_binding_ids_from_context(proposal_context_pack)
        resolver = BindingResolver.from_implementation_plan(implementation_plan)
        exhausted = retry_count >= self.retry_budget
        minimal_changes = (
            ()
            if exhausted
            else self._minimal_build_changes(
                build_result,
                resolver=resolver,
                allowed_binding_ids=allowed_binding_ids,
            )
        )
        blockers = self._blockers(
            exhausted=exhausted,
            evidence_refs=evidence_refs,
            minimal_changes=minimal_changes,
        )
        next_retry_count = retry_count if exhausted else retry_count + 1
        repair_context = _failure_repair_context(
            failure_source="build",
            failure_class=failure_class,
            exhausted=exhausted,
            evidence_refs=evidence_refs,
            minimal_changes=minimal_changes,
        )
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
            allowed_edit_binding_ids=tuple(sorted(allowed_binding_ids)),
            source_proposal=_source_proposal_from_context(proposal_context_pack),
            display_files=tuple(resolver.display_files_for_edit_ids(tuple(sorted(allowed_binding_ids)))),
            repair_context=repair_context,
        )

    def from_runtime_failure(
        self,
        *,
        runtime_evidence: dict[str, Any],
        runtime_evidence_ref: str,
        retry_count: int,
        target_behavior: str | None = None,
        proposal_context_pack: dict[str, Any] | None = None,
        resolved_repair_target: dict[str, Any] | None = None,
    ) -> RepairPlan:
        """Create a repair plan from failed runtime evidence."""

        feature_id = str(runtime_evidence.get("feature_id") or "unknown_feature")
        ownership = normalize_runtime_failure_ownership(
            runtime_evidence.get("failure_ownership"),
            verification_status=str(
                runtime_evidence.get("verification_status")
                or runtime_evidence.get("acceptance_status")
                or "runtime_unverified"
            ),
        )
        failure_owner = str(ownership["owner"])
        failure_class = str(ownership["failure_class"])
        source_repair_allowed = (
            failure_owner == "product_behavior"
            and ownership["source_repair_allowed"] is True
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
        resolved_target = (
            dict(resolved_repair_target)
            if isinstance(resolved_repair_target, dict)
            else {}
        )
        resolved_binding_id = (
            str(resolved_target["binding_id"])
            if resolved_target.get("status") == "resolved"
            and isinstance(resolved_target.get("binding_id"), str)
            else None
        )
        allowed_binding_ids = (
            {resolved_binding_id} if resolved_binding_id is not None else set()
        )
        exhausted = source_repair_allowed and retry_count >= self.retry_budget
        minimal_changes = (
            ()
            if exhausted or not source_repair_allowed
            else self._minimal_runtime_changes(
                resolved_target,
            )
        )
        blockers = self._runtime_blockers(
            ownership=ownership,
            exhausted=exhausted,
            evidence_refs=evidence_refs,
            minimal_changes=minimal_changes,
            resolved_repair_target=resolved_target,
        )
        source_repair_ready = source_repair_allowed and bool(minimal_changes)
        next_retry_count = (
            retry_count + 1
            if source_repair_ready and not exhausted
            else retry_count
        )
        repair_context = _runtime_failure_repair_context(
            ownership=ownership,
            failure_class=failure_class,
            exhausted=exhausted,
            evidence_refs=evidence_refs,
            minimal_changes=minimal_changes,
            resolved_repair_target=resolved_target,
        )
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
            hypothesis=_runtime_failure_hypothesis(
                ownership,
                resolved_repair_target=resolved_target,
            ),
            minimal_changes=minimal_changes,
            retry_count=next_retry_count,
            retry_budget=self.retry_budget,
            retry_budget_remaining=max(self.retry_budget - retry_count, 0),
            retry_exhausted=exhausted,
            scope_expansion_allowed=False,
            stop_condition=_runtime_failure_stop_condition(ownership),
            forbidden_regressions=(
                "Do not claim gameplay success without acceptance evidence.",
                "Do not broaden runtime behavior without new evidence.",
                "Do not grant source-repair authority to a non-product owner.",
            ),
            requires_new_evidence=(
                failure_owner in {"observation", "unknown"}
                or resolved_target.get("root_cause_status") == "unresolved"
                or resolved_target.get("status") != "resolved"
            ),
            allowed_next_stage=None if exhausted or blockers else "generate_patch_proposal",
            blockers=blockers,
            target_behavior=target_behavior,
            allowed_edit_binding_ids=tuple(sorted(allowed_binding_ids)),
            source_proposal=_source_proposal_from_context(proposal_context_pack),
            display_files=(
                (str(resolved_target["canonical_target_path"]),)
                if isinstance(
                    resolved_target.get("canonical_target_path"),
                    str,
                )
                else ()
            ),
            repair_context=repair_context,
            resolved_repair_target=resolved_target,
        )

    def from_review_failure(
        self,
        *,
        proposal_review: dict[str, Any],
        proposal_review_ref: str,
        retry_count: int,
        target_behavior: str | None = None,
        proposal_context_pack: dict[str, Any] | None = None,
        implementation_plan: dict[str, Any] | None = None,
    ) -> RepairPlan:
        """Create a bounded repair context from proposal_review blockers."""

        feature_id = _feature_id_from_context(
            proposal_context_pack,
            fallback="unknown_feature",
        )
        findings = _blocking_review_findings(proposal_review)
        finding_rule_ids = _unique_strings(
            [finding.get("rule_id") for finding in findings]
        )
        failure_class = (
            "proposal_review:" + ",".join(finding_rule_ids)
            if finding_rule_ids
            else "proposal_review:unknown"
        )
        evidence_refs = _unique_strings(
            [
                proposal_review_ref,
                *(
                    ref
                    for finding in findings
                    for ref in finding.get("evidence_refs", [])
                    if isinstance(finding, dict)
                ),
            ]
        )
        allowed_binding_ids = _allowed_binding_ids_from_context(proposal_context_pack)
        resolver = BindingResolver.from_implementation_plan(implementation_plan)
        exhausted = retry_count >= self.retry_budget
        minimal_changes: tuple[dict[str, Any], ...] = ()
        blockers = self._review_blockers(
            exhausted=exhausted,
            findings=findings,
            evidence_refs=evidence_refs,
        )
        next_retry_count = retry_count if exhausted else retry_count + 1
        display_files = tuple(
            resolver.display_files_for_edit_ids(tuple(sorted(allowed_binding_ids)))
        )
        review_repair_decision = _review_repair_decision(finding_rule_ids)
        repair_context = {
            "review_decision": proposal_review.get("decision"),
            "review_allowed_next_stage": proposal_review.get("allowed_next_stage"),
            "blocking_rule_ids": list(finding_rule_ids),
            "repair_decision": review_repair_decision["repair_decision"],
            "required_actions": review_repair_decision["required_actions"],
            "reason": review_repair_decision["reason"],
            "scope_source": "patch_proposal.context_pack.allowed_edit_binding_ids",
        }
        return RepairPlan(
            repair_id=stable_repair_id(
                feature_id=feature_id,
                failure_source="proposal_review",
                failure_class=failure_class,
                retry_count=next_retry_count,
                evidence_refs=evidence_refs,
            ),
            feature_id=feature_id,
            failure_source="proposal_review",
            failure_class=failure_class,
            evidence_refs=evidence_refs,
            hypothesis=(
                "Proposal review rejected the patch because its context, binding, "
                "or evidence contract is incomplete."
            ),
            minimal_changes=minimal_changes,
            retry_count=next_retry_count,
            retry_budget=self.retry_budget,
            retry_budget_remaining=max(self.retry_budget - retry_count, 0),
            retry_exhausted=exhausted,
            scope_expansion_allowed=False,
            stop_condition=(
                "Stop until proposal planning, context, or evidence binding is "
                "corrected and reviewed again."
            ),
            forbidden_regressions=(
                "Do not bypass proposal_review.",
                "Do not expand repair scope beyond allowed edit bindings.",
                "Do not turn review blockers into successful dry-run/build/runtime artifacts.",
            ),
            requires_new_evidence=bool(
                review_repair_decision["requires_new_evidence"]
            ),
            allowed_next_stage=None,
            blockers=blockers,
            target_behavior=target_behavior,
            allowed_edit_binding_ids=tuple(sorted(allowed_binding_ids)),
            source_proposal=_source_proposal_from_context(proposal_context_pack),
            display_files=display_files,
            failure_findings=tuple(dict(finding) for finding in findings),
            repair_context=repair_context,
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
    def _minimal_build_changes(
        build_result: dict[str, Any],
        *,
        resolver: BindingResolver,
        allowed_binding_ids: set[str],
    ) -> tuple[dict[str, Any], ...]:
        changes = []
        diagnostics = list(build_result.get("diagnostics", []))
        for index, diagnostic in enumerate(diagnostics):
            if not isinstance(diagnostic, dict):
                continue
            target_file = diagnostic.get("file")
            if not target_file:
                continue
            binding_id, error = resolver.resolve_edit_binding_for_path(
                str(target_file),
                allowed_binding_ids=allowed_binding_ids,
            )
            if error is not None or binding_id is None:
                continue
            changes.append(
                {
                    "change_id": f"repair_build_{index}",
                    "edit_binding_id": binding_id,
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
        resolved_repair_target: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        if (
            resolved_repair_target.get("status") != "resolved"
            or not isinstance(
                resolved_repair_target.get("binding_id"),
                str,
            )
        ):
            return ()
        anchors = resolved_repair_target.get("responsibility_anchors")
        if not isinstance(anchors, dict):
            return ()
        repair_scope = anchors.get("repair_scope")
        if (
            not isinstance(repair_scope, list)
            or not repair_scope
            or not all(isinstance(value, str) and value for value in repair_scope)
        ):
            return ()
        return (
            {
                "change_id": "repair_runtime_0",
                "edit_binding_id": resolved_repair_target["binding_id"],
                "intent": (
                    "Investigate the confirmed Runtime failure point within "
                    f"{', '.join(repair_scope)} without selecting a concrete "
                    "source change before root-cause evidence is available."
                ),
                "failure_code": resolved_repair_target.get("failure_class"),
                "failure_message": (
                    "Binding resolution identified the allowed source scope; "
                    "root-cause selection remains separate."
                ),
                "diagnosed_runtime_symbol": anchors.get("symbol"),
                "repair_scope": list(repair_scope),
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

    @staticmethod
    def _runtime_blockers(
        *,
        ownership: dict[str, Any],
        exhausted: bool,
        evidence_refs: tuple[str, ...],
        minimal_changes: tuple[dict[str, Any], ...],
        resolved_repair_target: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        owner = str(ownership["owner"])
        if owner == "product_behavior":
            target_blockers = resolved_repair_target.get("blockers")
            if resolved_repair_target.get("status") != "resolved":
                if isinstance(target_blockers, list) and target_blockers:
                    return tuple(
                        {
                            **dict(blocker),
                            "stage": "repair_plan",
                            "resolution_stage": blocker.get("stage"),
                        }
                        for blocker in target_blockers
                        if isinstance(blocker, dict)
                    )
                return (
                    {
                        "stage": "repair_plan",
                        "code": "RESOLVED_REPAIR_TARGET_REQUIRED",
                        "message": (
                            "Product Runtime repair requires a completed "
                            "ResolvedRepairTarget."
                        ),
                    },
                )
            if resolved_repair_target.get("root_cause_status") == "unresolved":
                return (
                    {
                        "stage": "repair_plan",
                        "code": "RUNTIME_ROOT_CAUSE_UNRESOLVED",
                        "message": (
                            "The failure point is confirmed, but current evidence "
                            "does not select one root cause or concrete source change."
                        ),
                        "unresolved_root_causes": list(
                            resolved_repair_target.get(
                                "unresolved_root_causes",
                                (),
                            )
                        ),
                    },
                )
            return RepairPlanner._blockers(
                exhausted=exhausted,
                evidence_refs=evidence_refs,
                minimal_changes=minimal_changes,
            )
        blocker_codes = {
            "observation": "RUNTIME_OBSERVATION_REPAIR_REQUIRED",
            "environment": "RUNTIME_ENVIRONMENT_REPAIR_REQUIRED",
            "provider": "RUNTIME_PROVIDER_REPAIR_REQUIRED",
            "permission": "RUNTIME_PERMISSION_REQUIRED",
            "unknown": "RUNTIME_FAILURE_OWNER_UNKNOWN",
        }
        return (
            {
                "stage": "repair_plan",
                "code": blocker_codes.get(owner, "RUNTIME_FAILURE_OWNER_UNKNOWN"),
                "message": str(ownership["reason"]),
                "failure_owner": owner,
                "required_action": str(ownership["required_action"]),
                "source_repair_allowed": False,
            },
        )

    @staticmethod
    def _review_blockers(
        *,
        exhausted: bool,
        findings: tuple[dict[str, Any], ...],
        evidence_refs: tuple[str, ...],
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
        if findings:
            blockers.append(
                {
                    "stage": "repair_plan",
                    "code": "REVIEW_REPLAN_REQUIRED",
                    "message": (
                        "Proposal review blockers require context, evidence, or "
                        "planning correction before repair proposal generation."
                    ),
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
                    display_files=tuple(repair_plan.get("display_files") or ()),
                    allowed_edit_binding_ids=tuple(
                        repair_plan.get("allowed_edit_binding_ids") or ()
                    ),
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
            dict.fromkeys(str(path) for path in repair_plan.get("display_files") or [])
        )
        diff_intent = tuple(
            self._repair_change_intent(
                index=index,
                repair_plan=repair_plan,
                change=change,
                evidence_refs=evidence_refs,
            )
            for index, change in enumerate(minimal_changes)
            if isinstance(change, dict) and change.get("edit_binding_id")
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
                    display_files=tuple(repair_plan.get("display_files") or ()),
                    allowed_edit_binding_ids=tuple(
                        repair_plan.get("allowed_edit_binding_ids") or ()
                    ),
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
                display_files=files,
                allowed_edit_binding_ids=tuple(
                    repair_plan.get("allowed_edit_binding_ids") or ()
                ),
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
            "edit_binding_id": change.get("edit_binding_id"),
            "supporting_binding_ids": list(change.get("supporting_binding_ids") or []),
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


def _failure_repair_context(
    *,
    failure_source: Literal["build", "runtime"],
    failure_class: str,
    exhausted: bool,
    evidence_refs: tuple[str, ...],
    minimal_changes: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Classify whether failure evidence supports a bounded repair attempt."""

    scoped_binding_ids = _unique_strings(
        [change.get("edit_binding_id") for change in minimal_changes]
    )
    if exhausted:
        repair_decision = "retry_budget_exhausted"
        required_actions = ["request_human_review_or_new_evidence"]
        reason = "The retry budget is exhausted; no additional repair attempt is allowed."
    elif minimal_changes:
        repair_decision = "scoped_patch_repair"
        required_actions = [
            "generate_evidence_bound_repair_proposal",
            "rerun_proposal_review",
            "rerun_failed_validation_stage",
        ]
        reason = (
            "Failure evidence resolves to edit bindings already allowed by the "
            "source patch proposal."
        )
    elif failure_source == "runtime":
        repair_decision = "runtime_evidence_required"
        required_actions = [
            "collect_target_bound_runtime_evidence",
            "resolve_failure_to_allowed_edit_binding",
        ]
        reason = (
            "Runtime evidence does not resolve to an allowed edit binding, so a "
            "patch repair cannot be proposed safely."
        )
    else:
        repair_decision = "build_scope_resolution_required"
        required_actions = [
            "collect_or_correct_build_diagnostics",
            "resolve_diagnostic_path_to_allowed_edit_binding",
        ]
        reason = (
            "Build diagnostics do not resolve to an allowed edit binding, so a "
            "patch repair cannot be proposed safely."
        )
    return {
        "failure_source": failure_source,
        "failure_class": failure_class,
        "repair_decision": repair_decision,
        "required_actions": required_actions,
        "scoped_edit_binding_ids": list(scoped_binding_ids),
        "failure_evidence_available": bool(evidence_refs),
        "reason": reason,
    }


def _runtime_failure_repair_context(
    *,
    ownership: dict[str, Any],
    failure_class: str,
    exhausted: bool,
    evidence_refs: tuple[str, ...],
    minimal_changes: tuple[dict[str, Any], ...],
    resolved_repair_target: dict[str, Any],
) -> dict[str, Any]:
    """Bind Runtime repair routing to the normalized failure owner."""

    owner = str(ownership["owner"])
    scoped_binding_ids = _unique_strings(
        [change.get("edit_binding_id") for change in minimal_changes]
    )
    if exhausted:
        repair_decision = "retry_budget_exhausted"
        required_actions = ["request_human_review_or_new_evidence"]
        reason = "The product-source repair budget is exhausted."
    elif owner == "product_behavior" and minimal_changes:
        repair_decision = "scoped_patch_repair"
        required_actions = [
            "generate_evidence_bound_repair_proposal",
            "rerun_proposal_review",
            "rerun_failed_validation_stage",
        ]
        reason = (
            "A product-behavior failure resolves to source bindings already "
            "allowed by the source patch proposal."
        )
    elif owner == "product_behavior":
        repair_decision = "runtime_source_binding_required"
        required_actions = [
            "collect_target_bound_runtime_evidence",
            "resolve_failure_to_allowed_edit_binding",
        ]
        reason = (
            "The product-behavior failure does not resolve to an allowed source "
            "edit binding."
        )
    else:
        repair_decision = str(ownership["required_action"])
        required_actions = [str(ownership["required_action"])]
        reason = str(ownership["reason"])
    return {
        "failure_source": "runtime",
        "failure_class": failure_class,
        "failure_owner": owner,
        "source_repair_allowed": bool(ownership["source_repair_allowed"]),
        "repair_decision": repair_decision,
        "required_actions": required_actions,
        "scoped_edit_binding_ids": list(scoped_binding_ids),
        "failure_evidence_available": bool(evidence_refs),
        "reason": reason,
        "resolved_repair_target": dict(resolved_repair_target),
    }


def _runtime_failure_hypothesis(
    ownership: dict[str, Any],
    *,
    resolved_repair_target: dict[str, Any] | None = None,
) -> str:
    owner = str(ownership["owner"])
    target = (
        resolved_repair_target
        if isinstance(resolved_repair_target, dict)
        else {}
    )
    anchors = target.get("responsibility_anchors")
    if (
        owner == "product_behavior"
        and isinstance(anchors, dict)
        and isinstance(anchors.get("symbol"), str)
    ):
        return (
            "Runtime evidence confirms the failure point at "
            f"{anchors['symbol']}; root-cause selection remains "
            f"{target.get('root_cause_status') or 'unresolved'}."
        )
    hypotheses = {
        "product_behavior": (
            "Runtime evidence attributes the acceptance failure to product behavior."
        ),
        "observation": (
            "The Runtime observation path did not establish the required facts."
        ),
        "environment": (
            "The Runtime execution environment failed before acceptance could be "
            "established."
        ),
        "provider": "The selected Runtime provider failed to produce valid evidence.",
        "permission": "Runtime execution lacked current required authorization.",
        "unknown": "Runtime evidence cannot attribute the failure to one repair owner.",
    }
    return hypotheses.get(owner, hypotheses["unknown"])


def _runtime_failure_stop_condition(ownership: dict[str, Any]) -> str:
    owner = str(ownership["owner"])
    if owner == "product_behavior":
        return "Stop if the same product-behavior failure persists after retry budget."
    return (
        "Stop source repair and hand off to the recorded Runtime failure owner; "
        "a new Runtime action requires fresh admission."
    )


def _review_repair_decision(
    finding_rule_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Map proposal-review rules to the next bounded correction action."""

    rule_ids = set(finding_rule_ids)
    evidence_rules = {"binding_registry", "evidence_binding", "hook_target_binding"}
    safety_rules = {
        "domain_profile",
        "forbidden_paths",
        "permission_level",
        "risk_policy",
        "scope_boundary",
    }
    planning_rules = {"target_alignment", "test_plan_presence"}

    if rule_ids & safety_rules:
        return {
            "repair_decision": "human_or_scope_review_required",
            "required_actions": ["return_to_human_or_scope_review"],
            "requires_new_evidence": False,
            "reason": (
                "Safety, permission, domain, or scope findings cannot be repaired "
                "by regenerating a patch proposal."
            ),
        }
    if rule_ids & evidence_rules:
        return {
            "repair_decision": "evidence_retrieval_required",
            "required_actions": [
                "refresh_or_expand_evidence",
                "rebuild_implementation_plan",
                "regenerate_patch_proposal",
                "rerun_proposal_review",
            ],
            "requires_new_evidence": True,
            "reason": (
                "Binding or Hook findings require current evidence and planning "
                "correction before proposal regeneration."
            ),
        }
    if rule_ids & planning_rules:
        return {
            "repair_decision": "planning_revision_required",
            "required_actions": [
                "revise_implementation_plan",
                "regenerate_patch_proposal",
                "rerun_proposal_review",
            ],
            "requires_new_evidence": False,
            "reason": (
                "Target-alignment or test-plan findings require planning revision "
                "before proposal regeneration."
            ),
        }
    if "context_pack" in rule_ids:
        return {
            "repair_decision": "context_rebuild_required",
            "required_actions": [
                "rebuild_proposal_context",
                "regenerate_patch_proposal",
                "rerun_proposal_review",
            ],
            "requires_new_evidence": False,
            "reason": (
                "Proposal context must be rebuilt from existing authoritative "
                "artifacts before proposal regeneration."
            ),
        }
    return {
        "repair_decision": "proposal_revision_required",
        "required_actions": [
            "revise_patch_proposal",
            "rerun_proposal_review",
        ],
        "requires_new_evidence": False,
        "reason": (
            "Proposal-local findings require proposal revision and review re-entry."
        ),
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


def _allowed_binding_ids_from_context(
    proposal_context_pack: dict[str, Any] | None,
) -> set[str]:
    if not isinstance(proposal_context_pack, dict):
        return set()
    ids = proposal_context_pack.get("allowed_edit_binding_ids")
    if isinstance(ids, list):
        return {str(value) for value in ids}
    return set()


def _source_proposal_from_context(
    proposal_context_pack: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(proposal_context_pack, dict):
        return {}
    result: dict[str, Any] = {}
    if proposal_context_pack.get("source_patch_proposal_ref"):
        result["ref"] = proposal_context_pack.get("source_patch_proposal_ref")
    if proposal_context_pack.get("source_patch_proposal_hash"):
        result["hash"] = proposal_context_pack.get("source_patch_proposal_hash")
    return result


def _feature_id_from_context(
    proposal_context_pack: dict[str, Any] | None,
    *,
    fallback: str,
) -> str:
    if not isinstance(proposal_context_pack, dict):
        return fallback
    return str(proposal_context_pack.get("feature_id") or fallback)


def _blocking_review_findings(
    proposal_review: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        dict(finding)
        for finding in proposal_review.get("findings") or []
        if isinstance(finding, dict) and finding.get("level") == "blocking"
    )
