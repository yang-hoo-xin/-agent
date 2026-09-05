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

FailureSource = Literal["build", "runtime", "eval", "proposal_review", "behavior_report"]
RepairSemanticDecisionKind = Literal[
    "repair_ready",
    "evidence_insufficient",
    "binding_insufficient",
]


@dataclass(frozen=True)
class RepairSemanticDecision:
    """A semantic-only decision that grants no workflow authority."""

    decision: RepairSemanticDecisionKind
    reason: str
    selected_hypothesis_id: str | None
    required_next_action: str
    blockers: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the deterministic semantic decision payload."""

        return {
            "schema_version": "repair_semantic_decision_v1",
            "decision": self.decision,
            "decision_scope": "semantic_only",
            "authority_granted": False,
            "artifact_materialization_allowed": False,
            "source_patch_allowed": False,
            "build_allowed": False,
            "runtime_allowed": False,
            "reason": self.reason,
            "selected_hypothesis_id": self.selected_hypothesis_id,
            "required_next_action": self.required_next_action,
            "blockers": [dict(blocker) for blocker in self.blockers],
        }


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
    semantic_decision: dict[str, Any] | None = None

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
            "semantic_decision": dict(self.semantic_decision or {}),
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

    def from_behavior_failure(
        self, *, repair_context: dict[str, Any], feature_id: str,
        target_behavior: str, retry_count: int,
    ) -> RepairPlan:
        """Route admitted observations; a passed Review remains passed history."""
        report = repair_context["failure_report"]
        allowed = tuple(repair_context["allowed_edit_binding_ids"])
        owner_ids = tuple(report["owner_binding_ids"])
        owner = report.get("failure_owner")
        exhausted = retry_count >= self.retry_budget
        if exhausted:
            decision, action, code = "retry_budget_exhausted", "human_review", "PATCH_REPAIR_RETRY_EXHAUSTED"
        elif owner == "planning" or (owner == "patch_implementation" and not set(owner_ids).issubset(allowed)):
            decision, action, code = "binding_insufficient", "planning", "PATCH_REPAIR_REPLAN_REQUIRED"
        elif owner == "evidence":
            decision, action, code = "evidence_insufficient", "evidence", "PATCH_REPAIR_EVIDENCE_REQUIRED"
        elif owner in {"validator", "environment"} or report.get("status") == "infrastructure_failed":
            decision, action, code = "verification_unavailable", "validator", "PATCH_REPAIR_VERIFIER_REQUIRED"
        elif report.get("status") == "identity_failed":
            decision, action, code = "source_identity_invalid", "evidence", "PATCH_REPAIR_SOURCE_IDENTITY_REQUIRED"
        elif owner in {"unknown", None} and report.get("status") in {"needs_evidence", "behavior_failed"}:
            decision, action, code = "investigation_ready", "generate_patch_proposal", None
        elif owner == "patch_implementation" and owner_ids and report.get("status") == "behavior_failed":
            decision, action, code = "repair_ready", "generate_patch_proposal", None
        else:
            decision, action, code = "evidence_insufficient", "evidence", "PATCH_REPAIR_OWNER_UNRESOLVED"
        refs = (repair_context["failure_report_ref"]["path"],)
        reason = (
            "The failure owner is unresolved. Investigate within the existing read scope and shared budget; this working hypothesis grants no new edit authority."
            if decision == "investigation_ready" else
            "The bound behavior observations identify an implementation failure within the existing Plan."
            if code is None else "The behavior observation requires its named upstream owner before another Patch."
        )
        blockers = () if code is None else ({
            "stage": "repair_plan", "code": code, "message": reason,
            "required_next_owner": action, "failure_evidence_refs": list(refs),
        },)
        # The parent has not been Applied: this is a whole-Patch replacement,
        # including previously correct changes, never an owner-only delta.
        minimal_changes = tuple({
            "edit_binding_id": binding_id,
            "intent": "Regenerate the complete approved-scope proposal against the unchanged base; preserve all FeatureSpec obligations.",
        } for binding_id in allowed) if code is None else ()
        next_count = retry_count if exhausted else retry_count + 1
        return RepairPlan(
            repair_id=stable_repair_id(feature_id=feature_id, failure_source="behavior_report",
                failure_class="observed_behavior_failure", retry_count=next_count, evidence_refs=refs),
            feature_id=feature_id, failure_source="behavior_report", failure_class="observed_behavior_failure",
            evidence_refs=refs, hypothesis=reason, minimal_changes=minimal_changes,
            retry_count=next_count, retry_budget=self.retry_budget,
            retry_budget_remaining=max(self.retry_budget - next_count, 0), retry_exhausted=exhausted,
            scope_expansion_allowed=False, stop_condition="Stop after this bounded replacement or request the recorded upstream owner; never inherit approval.",
            forbidden_regressions=("Preserve the original FeatureSpec and behavior matrix.", "Do not modify outside existing edit bindings.", "Do not reuse the parent approval or claim Build/Runtime success."),
            requires_new_evidence=decision == "evidence_insufficient", allowed_next_stage=action if code is None else None,
            blockers=blockers, target_behavior=target_behavior, allowed_edit_binding_ids=allowed,
            source_proposal=dict(repair_context["parent_proposal"]),
            failure_findings=tuple(dict(item) for item in report["observations"]),
            repair_context={key: value for key, value in repair_context.items() if key != "previous_response"},
            semantic_decision={"decision": decision, "required_next_owner": action, "authority_granted": False, "reason": reason},
        )

    @staticmethod
    def assess_stagger_semantic_decision(
        *,
        root_cause_evidence: dict[str, Any],
        repair_hypothesis_set: dict[str, Any],
        binding_resolution: dict[str, Any],
    ) -> RepairSemanticDecision:
        """Select one Stagger semantic route without granting outer authority."""

        if (
            root_cause_evidence.get("direct_failure_mechanism")
            != "confirmed"
            or root_cause_evidence.get("failure_owner")
            != "product_behavior"
        ):
            return RepairSemanticDecision(
                decision="evidence_insufficient",
                reason=(
                    "The direct product failure mechanism is not confirmed "
                    "by the supplied RootCauseEvidence."
                ),
                selected_hypothesis_id=None,
                required_next_action=(
                    "Collect bounded evidence for the direct failure mechanism."
                ),
                blockers=(
                    {
                        "stage": "repair_plan",
                        "code": "STAGGER_DIRECT_MECHANISM_EVIDENCE_REQUIRED",
                        "message": (
                            "Repair semantics require a confirmed product "
                            "failure mechanism."
                        ),
                    },
                ),
            )
        hypotheses = repair_hypothesis_set.get("hypotheses")
        hypothesis_items = hypotheses if isinstance(hypotheses, list) else []
        supported = [
            item
            for item in hypothesis_items
            if isinstance(item, dict)
            and item.get("status") == "supported"
        ]
        if len(supported) != 1:
            return RepairSemanticDecision(
                decision="evidence_insufficient",
                reason=(
                    "The current evidence does not support exactly one "
                    "RectTransform acquisition hypothesis."
                ),
                selected_hypothesis_id=None,
                required_next_action=(
                    "Perform the bounded read-only observation named by the "
                    "unresolved hypotheses."
                ),
                blockers=(
                    {
                        "stage": "repair_plan",
                        "code": "STAGGER_RECT_TRANSFORM_SOURCE_UNRESOLVED",
                        "message": (
                            "The failed downcast is confirmed, but the correct "
                            "RectTransform acquisition path is unresolved."
                        ),
                    },
                ),
            )
        selected = supported[0]
        resolved_target = binding_resolution.get("resolved_repair_target")
        allowed_ids = binding_resolution.get("allowed_edit_binding_ids")
        if (
            binding_resolution.get("result_type")
            != "resolved_repair_target"
            or not isinstance(resolved_target, dict)
            or resolved_target.get("status") != "resolved"
            or not isinstance(allowed_ids, list)
            or allowed_ids != [resolved_target.get("binding_id")]
        ):
            return RepairSemanticDecision(
                decision="binding_insufficient",
                reason=(
                    "The selected semantic repair does not have one exact "
                    "resolved Edit Binding."
                ),
                selected_hypothesis_id=str(
                    selected.get("hypothesis_id") or ""
                )
                or None,
                required_next_action=(
                    "Create a no-write exact Binding request and obtain "
                    "separate human approval."
                ),
                blockers=(
                    {
                        "stage": "repair_plan",
                        "code": "STAGGER_EXACT_BINDING_REQUIRED",
                        "message": (
                            "Repair planning cannot expand or infer the "
                            "writable source scope."
                        ),
                    },
                ),
            )
        binding_status = selected.get("binding_status")
        responsibility_anchors = resolved_target.get(
            "responsibility_anchors"
        )
        target_symbol = (
            responsibility_anchors.get("symbol")
            if isinstance(responsibility_anchors, dict)
            else None
        )
        proposed_location = selected.get("proposed_edit_location")
        if (
            binding_status != "covered_by_current_binding"
            or proposed_location != target_symbol
        ):
            return RepairSemanticDecision(
                decision="binding_insufficient",
                reason=(
                    "The supported semantic repair lies outside the current "
                    "exact Edit Binding."
                ),
                selected_hypothesis_id=str(
                    selected.get("hypothesis_id") or ""
                )
                or None,
                required_next_action=(
                    "Create a no-write exact Binding request for the supported "
                    "source location."
                ),
                blockers=(
                    {
                        "stage": "repair_plan",
                        "code": "STAGGER_BINDING_SCOPE_INSUFFICIENT",
                        "message": (
                            "The current Binding cannot be widened by "
                            "RepairPlanner."
                        ),
                    },
                ),
            )
        if not isinstance(selected.get("proposed_operation"), str) or not selected[
            "proposed_operation"
        ]:
            return RepairSemanticDecision(
                decision="evidence_insufficient",
                reason=(
                    "The supported hypothesis lacks one evidence-bound "
                    "operation."
                ),
                selected_hypothesis_id=str(
                    selected.get("hypothesis_id") or ""
                )
                or None,
                required_next_action=(
                    "Record the exact operation supported by the observation."
                ),
                blockers=(
                    {
                        "stage": "repair_plan",
                        "code": "STAGGER_OPERATION_EVIDENCE_REQUIRED",
                        "message": (
                            "RepairPlanner cannot infer an operation from a "
                            "source location alone."
                        ),
                    },
                ),
            )
        return RepairSemanticDecision(
            decision="repair_ready",
            reason=(
                "One supported hypothesis is fully covered by the current "
                "exact Edit Binding."
            ),
            selected_hypothesis_id=str(selected["hypothesis_id"]),
            required_next_action=(
                "Create an intent-only RepairPlan and Proposal; source writes "
                "remain separately gated."
            ),
            blockers=(),
        )

    def from_stagger_semantic_failure(
        self,
        *,
        root_cause_evidence: dict[str, Any],
        root_cause_evidence_ref: str,
        repair_hypothesis_set: dict[str, Any],
        repair_hypothesis_set_ref: str,
        binding_resolution: dict[str, Any],
        binding_resolution_ref: str,
        retry_count: int,
        target_behavior: str | None = None,
    ) -> RepairPlan:
        """Create an intent-only Stagger RepairPlan from formal planning inputs."""

        feature_id = str(root_cause_evidence.get("feature_id") or "")
        if (
            not feature_id
            or repair_hypothesis_set.get("feature_id") != feature_id
            or binding_resolution.get("feature_id") != feature_id
        ):
            raise ValueError(
                "Stagger planning inputs do not share one feature identity."
            )
        decision = self.assess_stagger_semantic_decision(
            root_cause_evidence=root_cause_evidence,
            repair_hypothesis_set=repair_hypothesis_set,
            binding_resolution=binding_resolution,
        )
        decision_payload = decision.to_dict()
        selected = next(
            (
                item
                for item in repair_hypothesis_set.get("hypotheses", ())
                if isinstance(item, dict)
                and item.get("hypothesis_id")
                == decision.selected_hypothesis_id
            ),
            None,
        )
        resolved_target = dict(
            binding_resolution.get("resolved_repair_target") or {}
        )
        minimal_changes: tuple[dict[str, Any], ...] = ()
        allowed_ids: tuple[str, ...] = ()
        display_files: tuple[str, ...] = ()
        if decision.decision == "repair_ready" and isinstance(selected, dict):
            binding_id = str(resolved_target["binding_id"])
            minimal_changes = (
                {
                    "change_id": "repair_stagger_semantic_001",
                    "edit_binding_id": binding_id,
                    "intent": str(selected["proposed_operation"]),
                    "hypothesis_id": str(selected["hypothesis_id"]),
                },
            )
            allowed_ids = (binding_id,)
            display_files = (
                str(resolved_target["canonical_target_path"]),
            )
        evidence_refs = _unique_strings(
            [
                root_cause_evidence_ref,
                repair_hypothesis_set_ref,
                binding_resolution_ref,
                *(
                    item.get("path")
                    for item in root_cause_evidence.get(
                        "evidence_items",
                        (),
                    )
                    if isinstance(item, dict)
                ),
            ]
        )
        blockers = decision.blockers
        hypothesis = (
            str(selected["statement"])
            if isinstance(selected, dict)
            else (
                "The current evidence confirms the failed RectTransform "
                "downcast but does not select the correct acquisition path."
            )
        )
        return RepairPlan(
            repair_id=stable_repair_id(
                feature_id=feature_id,
                failure_source="runtime",
                failure_class="stagger_yellow_x_visual",
                retry_count=retry_count,
                evidence_refs=evidence_refs,
            ),
            feature_id=feature_id,
            failure_source="runtime",
            failure_class="stagger_yellow_x_visual",
            evidence_refs=evidence_refs,
            hypothesis=hypothesis,
            minimal_changes=minimal_changes,
            retry_count=retry_count,
            retry_budget=self.retry_budget,
            retry_budget_remaining=max(
                self.retry_budget - retry_count,
                0,
            ),
            retry_exhausted=False,
            scope_expansion_allowed=False,
            stop_condition=(
                "Stop before Proposal generation unless semantic_decision is "
                "repair_ready and one exact Edit Binding covers the operation."
            ),
            forbidden_regressions=(
                "Do not alter historical RuntimeEvidence.",
                "Do not treat post-run copies as formal RuntimeEvidence.",
                "Do not widen edit_binding_004.",
                "Do not claim yellow-X or audio acceptance from this plan.",
            ),
            requires_new_evidence=(
                decision.decision == "evidence_insufficient"
            ),
            allowed_next_stage=(
                "generate_patch_proposal"
                if decision.decision == "repair_ready"
                else None
            ),
            blockers=blockers,
            target_behavior=target_behavior,
            allowed_edit_binding_ids=allowed_ids,
            display_files=display_files,
            repair_context={
                "semantic_decision": decision_payload,
                "root_cause_evidence_ref": root_cause_evidence_ref,
                "repair_hypothesis_set_ref": repair_hypothesis_set_ref,
                "binding_resolution_ref": binding_resolution_ref,
            },
            resolved_repair_target=resolved_target,
            semantic_decision=decision_payload,
        )

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
        refs: list[str] = []
        for index, diagnostic in enumerate(build_result.get("diagnostics", [])):
            if not isinstance(diagnostic, dict):
                continue
            refs.append(RepairPlanner._diagnostic_ref(index, diagnostic))
        return tuple(refs)

    @staticmethod
    def _diagnostic_ref(index: int, diagnostic: dict[str, Any]) -> str:
        code = diagnostic.get("code") or "unknown"
        file_name = diagnostic.get("file") or "unknown_file"
        line = diagnostic.get("line") or "unknown_line"
        return f"build_diag:{index}:{code}:{file_name}:{line}"

    @staticmethod
    def _minimal_build_changes(
        build_result: dict[str, Any],
        *,
        resolver: BindingResolver,
        allowed_binding_ids: set[str],
    ) -> tuple[dict[str, Any], ...]:
        grouped: dict[str, dict[str, Any]] = {}
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
            group = grouped.setdefault(
                binding_id,
                {
                    "first_index": index,
                    "first_diagnostic": diagnostic,
                    "failure_evidence_refs": [],
                },
            )
            group["failure_evidence_refs"].append(
                RepairPlanner._diagnostic_ref(index, diagnostic)
            )
        return tuple(
            {
                "change_id": f"repair_build_{group['first_index']}",
                "edit_binding_id": binding_id,
                "intent": (
                    "Repair the compiler diagnostics for this exact edit binding "
                    "using the referenced failure evidence."
                ),
                "failure_code": group["first_diagnostic"].get("code"),
                "failure_message": group["first_diagnostic"].get("message"),
                "failure_evidence_refs": list(group["failure_evidence_refs"]),
            }
            for binding_id, group in grouped.items()
        )

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

    def build(
        self,
        repair_plan: dict[str, Any],
        *,
        implementation_plan: dict[str, Any] | None = None,
    ) -> PatchProposal:
        """Return a reviewable repair patch proposal without editing files."""

        feature_id = str(repair_plan.get("feature_id") or "unknown_feature")
        evidence_refs = tuple(str(ref) for ref in repair_plan.get("evidence_refs", []))
        minimal_changes = list(repair_plan.get("minimal_changes") or [])
        (
            planned_changes_by_binding,
            ambiguous_planned_bindings,
        ) = self._planned_changes_by_binding(implementation_plan)
        selected_ambiguous_bindings = sorted(
            {
                str(change.get("edit_binding_id") or "")
                for change in minimal_changes
                if isinstance(change, dict)
                and str(change.get("edit_binding_id") or "")
                in ambiguous_planned_bindings
            }
        )
        blockers = tuple(repair_plan.get("blockers") or ()) + tuple(
            {
                "code": "REPAIR_PLAN_BINDING_AMBIGUOUS",
                "message": (
                    "Repair Proposal cannot select among multiple "
                    "ImplementationPlan changes for one edit binding."
                ),
                "binding_id": binding_id,
            }
            for binding_id in selected_ambiguous_bindings
        )
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

        files = tuple(
            dict.fromkeys(str(path) for path in repair_plan.get("display_files") or [])
        )
        diff_intent = tuple(
            self._repair_change_intent(
                index=index,
                repair_plan=repair_plan,
                change=change,
                evidence_refs=evidence_refs,
                planned_change=planned_changes_by_binding.get(
                    str(change.get("edit_binding_id") or "")
                ),
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
        planned_change: dict[str, Any] | None,
    ) -> dict[str, Any]:
        planned = planned_change if isinstance(planned_change, dict) else {}
        intent = {
            "change_id": change.get("change_id") or f"repair_change_{index}",
            "change_type": "repair",
            "edit_binding_id": change.get("edit_binding_id"),
            "hook_target_binding_id": planned.get("hook_target_binding_id"),
            "supporting_binding_ids": list(
                change.get("supporting_binding_ids")
                or planned.get("supporting_binding_ids")
                or []
            ),
            "operation": (
                change.get("operation")
                or planned.get("operation")
                or "modify"
            ),
            "rationale": (
                f"{repair_plan.get('hypothesis')} "
                f"Intent: {change.get('intent')}"
            ),
            "evidence_refs": list(evidence_refs),
            "expected_validation": list(
                planned.get("expected_validation")
                or (
                    "repair_plan reviewed",
                    "dry-run apply remains isolated",
                    "build/runtime failure evidence is rechecked",
                )
            ),
            "rollback_hint": (
                planned.get("rollback_hint")
                or "Use git change metadata and artifact refs for rollback."
            ),
        }
        if isinstance(planned.get("patch"), dict):
            intent["patch"] = dict(planned["patch"])
        return intent

    @staticmethod
    def _planned_changes_by_binding(
        implementation_plan: dict[str, Any] | None,
    ) -> tuple[dict[str, dict[str, Any]], frozenset[str]]:
        if not isinstance(implementation_plan, dict):
            return {}, frozenset()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for change in implementation_plan.get("proposed_changes") or []:
            if not isinstance(change, dict) or not change.get("edit_binding_id"):
                continue
            grouped.setdefault(str(change["edit_binding_id"]), []).append(change)
        return (
            {
                binding_id: changes[0]
                for binding_id, changes in grouped.items()
                if len(changes) == 1
            },
            frozenset(
                binding_id
                for binding_id, changes in grouped.items()
                if len(changes) > 1
            ),
        )


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
