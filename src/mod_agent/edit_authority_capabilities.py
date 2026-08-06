"""Typed capability authority for Stagger Edit Authority review."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from src.mod_agent.action_identity import canonical_action_json, hash_action_identity


PublicOperation: TypeAlias = Literal["preflight", "resume"]
GraphRoute: TypeAlias = Literal["stagger_edit_authority_gate"]
ExecutionMode: TypeAlias = Literal["human_review_then_materialize"]
SideEffectClass: TypeAlias = Literal[
    "artifact_store_write_after_accepted_resume"
]
ArtifactInputMode: TypeAlias = Literal[
    "request_only",
    "request_and_registered_upstreams",
]
MaterializerKind: TypeAlias = Literal[
    "generic",
    "existing_binding",
    "hud_observation",
    "bounded_observation",
]
TerminalStage: TypeAlias = Literal[
    "binding_resolution",
    "implementation_plan",
]
CompatibilityMode: TypeAlias = Literal["preserve_historical_identity"]
EditAuthorityPlatformStatus: TypeAlias = Literal[
    "completed",
    "blocked",
    "partial",
]
EditAuthorityReviewOutcome: TypeAlias = Literal[
    "not_recorded",
    "approved",
    "rejected",
]
EditAuthorityMaterializationStatus: TypeAlias = Literal[
    "not_started",
    "not_applicable",
    "completed",
    "incomplete",
]
EditAuthorityFailureStage: TypeAlias = Literal[
    "graph_interrupt",
    "checkpoint_construction",
    "checkpoint_store",
    "resume_validation",
    "resume_report_store",
    "store_preflight",
    "materialization_validation",
    "edit_authority_approval_store",
    "evidence_pack_store",
    "implementation_plan_store",
    "binding_resolution_store",
    "internal_execution",
]
RequiredFreshness: TypeAlias = Literal[
    "latest_and_fresh",
    "registered_exact_and_fresh",
    "registered_exact",
]

APPROVAL_IDENTITY_SCHEMA_VERSION = "edit_authority_approval_identity_v1"
APPROVAL_IDENTITY_HASH_DOMAIN = "edit_authority_approval_identity"
VERSIONED_APPROVAL_IDENTITY_MODE = "versioned_v1"
LEGACY_APPROVAL_IDENTITY_MODE = "legacy_full_request_payload_v0"


STAGGER_EDIT_AUTHORITY_REQUEST_SCHEMA = "stagger_edit_authority_request_v1"
EXISTING_BINDING_REAUTHORIZATION_REQUEST_SCHEMA = (
    "stagger_existing_binding_reauthorization_request_v1"
)
STAGGER_HUD_PARENT_OBSERVATION_REQUEST_SCHEMA = (
    "stagger_hud_parent_observation_authority_request_v1"
)
STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA = (
    "stagger_hud_parent_diagnostic_execution_authority_request_v2"
)
STAGGER_HUD_PARENT_OBSERVATION_PROPOSAL_SCHEMA = (
    "stagger_hud_parent_observation_authority_v1"
)
STAGGER_HUD_PARENT_DIAGNOSTIC_PROPOSAL_SCHEMA = (
    "stagger_hud_parent_diagnostic_execution_authority_v2"
)
STAGGER_BOUNDED_OBSERVATION_PROJECTION_KIND = (
    "bounded_observation_only_plan_materialization"
)

EDIT_AUTHORITY_REQUEST_APPROVAL_CONTRACT = (
    "edit_authority_request_approval_v1"
)
EXISTING_BINDING_AUTHORITY_CONTRACT = (
    "edit_authority_existing_binding_reauthorization_v1"
)
STAGGER_OBSERVATION_AUTHORITY_CONTRACT_V1 = (
    "edit_authority_stagger_hud_parent_observation_plan_v1"
)
STAGGER_OBSERVATION_AUTHORITY_CONTRACT_V2 = (
    "edit_authority_stagger_hud_parent_diagnostic_plan_v2"
)

_CAPABILITY_CONTRACT_VERSION = "stagger_edit_authority_capability_v1"
_PREFLIGHT_STATUS = "READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION"
_PROTOCOL_WRITE_TYPES = ("workflow_checkpoint", "resume_report")
_GENERIC_ACTIONS = (
    "create_evidence_pack_revision",
    "create_implementation_plan_revision",
    "resolve_exact_edit_binding",
)
_GENERIC_FORBIDDEN_ACTIONS = (
    "invoke_repair_planner",
    "modify_source",
    "build",
    "launch_process",
    "write_game_directory",
)
_EXISTING_BINDING_ACTIONS = (
    "reauthorize_existing_edit_binding",
    "create_binding_resolution_revision",
)
_EXISTING_BINDING_FORBIDDEN_ACTIONS = (
    "create_evidence_pack_revision",
    "create_implementation_plan_revision",
    "create_edit_binding",
    "invoke_repair_planner",
    "modify_source",
    "build",
    "launch_process",
    "write_game_directory",
)
_OBSERVATION_V1_ACTIONS = (
    "create_observation_evidence_pack_revision",
    "create_diagnostic_implementation_plan_revision",
    "create_observation_only_edit_bindings",
)
_OBSERVATION_V2_ACTIONS = (
    "create_observation_evidence_pack_revision",
    "create_diagnostic_only_implementation_plan_revision",
    "create_exact_bounded_observation_bindings",
)
_OBSERVATION_FORBIDDEN_ACTIONS = (
    "create_binding_resolution_revision",
    "invoke_repair_planner",
    "modify_source",
    "build",
    "launch_process",
    "write_game_directory",
)
_RESOLUTION_FIELDS = (
    ("edit_authority_approval", "edit_authority_approval_revision"),
    ("evidence_pack", "evidence_pack_revision"),
    ("implementation_plan", "implementation_plan_revision"),
    ("binding_resolution", "binding_resolution_revision"),
)
_OBSERVATION_FIELDS = _RESOLUTION_FIELDS[:3]


@dataclass(frozen=True)
class ApprovalInputBinding:
    """One role-bound immutable input included in Approval Identity."""

    role: str
    artifact_type: str
    proposal_revision_path: tuple[str, ...]
    required_freshness: RequiredFreshness


def _input(
    role: str,
    artifact_type: str,
    proposal_revision_path: tuple[str, ...],
    required_freshness: RequiredFreshness,
) -> ApprovalInputBinding:
    return ApprovalInputBinding(
        role=role,
        artifact_type=artifact_type,
        proposal_revision_path=proposal_revision_path,
        required_freshness=required_freshness,
    )


_GENERIC_APPROVAL_INPUTS = (
    _input(
        "feature_spec",
        "feature_spec",
        ("feature_spec_revision",),
        "latest_and_fresh",
    ),
    _input(
        "runtime_evidence",
        "runtime_evidence",
        ("runtime_evidence_revision",),
        "latest_and_fresh",
    ),
    _input(
        "implementation_plan",
        "implementation_plan",
        ("implementation_plan_revision",),
        "latest_and_fresh",
    ),
    _input(
        "patch_proposal",
        "patch_proposal",
        ("patch_proposal_revision",),
        "latest_and_fresh",
    ),
)
_EXISTING_BINDING_APPROVAL_INPUTS = (
    _input(
        "feature_spec",
        "feature_spec",
        ("feature_spec_revision",),
        "latest_and_fresh",
    ),
    _input(
        "runtime_evidence",
        "runtime_evidence",
        ("runtime_evidence_revision",),
        "latest_and_fresh",
    ),
    _input(
        "predecessor_implementation_plan",
        "implementation_plan",
        ("predecessor_implementation_plan_revision",),
        "registered_exact_and_fresh",
    ),
    _input(
        "patch_proposal",
        "patch_proposal",
        ("patch_proposal_revision",),
        "latest_and_fresh",
    ),
    _input(
        "current_implementation_plan",
        "implementation_plan",
        ("current_implementation_plan_revision",),
        "latest_and_fresh",
    ),
    _input(
        "existing_binding_resolution",
        "binding_resolution",
        ("existing_binding_resolution_revision",),
        "latest_and_fresh",
    ),
)
_HUD_APPROVAL_INPUTS = (
    _input(
        "feature_spec",
        "feature_spec",
        ("feature_spec_revision",),
        "latest_and_fresh",
    ),
    _input(
        "runtime_evidence",
        "runtime_evidence",
        ("runtime_evidence_revision",),
        "latest_and_fresh",
    ),
    _input(
        "current_implementation_plan",
        "implementation_plan",
        ("current_implementation_plan_revision",),
        "latest_and_fresh",
    ),
    _input(
        "patch_proposal",
        "patch_proposal",
        ("patch_proposal_revision",),
        "latest_and_fresh",
    ),
    _input(
        "existing_binding_resolution",
        "binding_resolution",
        ("existing_binding_resolution_revision",),
        "latest_and_fresh",
    ),
    _input(
        "existing_edit_authority_approval",
        "edit_authority_approval",
        ("existing_edit_authority_approval_revision",),
        "latest_and_fresh",
    ),
    _input(
        "evidence_pack",
        "evidence_pack",
        ("evidence_pack_revision",),
        "latest_and_fresh",
    ),
)
_BOUNDED_APPROVAL_INPUTS = (
    _input(
        "feature_spec",
        "feature_spec",
        ("feature_spec_revision",),
        "latest_and_fresh",
    ),
    _input(
        "runtime_evidence",
        "runtime_evidence",
        ("runtime_evidence_revision",),
        "latest_and_fresh",
    ),
    _input(
        "evidence_pack",
        "evidence_pack",
        ("evidence_pack_revision",),
        "latest_and_fresh",
    ),
    _input(
        "historical_implementation_plan",
        "implementation_plan",
        ("historical_identifier_baseline", "implementation_plan_revision"),
        "registered_exact",
    ),
    _input(
        "historical_patch_proposal",
        "patch_proposal",
        ("historical_identifier_baseline", "patch_proposal_revision"),
        "registered_exact",
    ),
)


class UnsupportedEditAuthorityCapabilityError(ValueError):
    """Raised when an exact schema/projection pair is not registered."""


class InvalidEditAuthorityApprovalIdentityError(ValueError):
    """Raised when a Request does not bind one canonical approval action."""


@dataclass(frozen=True)
class EditAuthorityCapabilityDeclaration:
    """One complete Stagger Edit Authority capability contract."""

    capability_id: str
    capability_contract_version: str
    schema_version: str
    projection_kind: str | None
    proposal_schema_version: str | None
    public_operations: frozenset[PublicOperation]
    graph_route: GraphRoute
    execution_mode: ExecutionMode
    side_effect_class: SideEffectClass
    authority_contract_version: str
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    checkpoint_input_mode: ArtifactInputMode
    latest_admission_mode: ArtifactInputMode
    materializer_kind: MaterializerKind
    materialized_artifact_fields: tuple[tuple[str, str], ...]
    review_write_artifact_types: tuple[str, ...]
    terminal_stage: TerminalStage
    preflight_success_status: str
    public_success_status: str
    materializer_success_status: str
    compatibility_mode: CompatibilityMode
    deprecated: bool
    approval_input_bindings: tuple[ApprovalInputBinding, ...]
    materialization_commit_budget: int
    automatic_retry_budget: int


@dataclass(frozen=True)
class EditAuthorityStoreStepV1:
    """One declaration-ordered Store fact in an Edit Authority attempt."""

    role: str
    store_result: Any

    def __post_init__(self) -> None:
        from src.mod_agent.artifacts.store import ArtifactWriteResult

        if not isinstance(self.store_result, ArtifactWriteResult):
            raise ValueError("Edit Authority store_result must be typed Store truth.")
        if self.role != self.store_result.artifact_type:
            raise ValueError("Edit Authority Store step role/type changed.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "store_result": self.store_result.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EditAuthorityStoreStepV1":
        from src.mod_agent.artifacts.store import ArtifactWriteResult

        if set(value) != {"role", "store_result"}:
            raise ValueError("Edit Authority Store step fields changed.")
        role = value.get("role")
        store_result = value.get("store_result")
        if type(role) is not str or not role or not isinstance(store_result, Mapping):
            raise ValueError("Edit Authority Store step projection is invalid.")
        return cls(
            role=role,
            store_result=ArtifactWriteResult.from_dict(store_result),
        )


@dataclass(frozen=True)
class EditAuthorityReviewResultV1:
    """Authoritative ordered result for one Edit Authority review attempt."""

    result_contract_version: str
    capability_id: str
    capability_contract_version: str
    approval_identity_hash: str
    platform_status: EditAuthorityPlatformStatus
    review_outcome: EditAuthorityReviewOutcome
    materialization_status: EditAuthorityMaterializationStatus
    failure_stage: EditAuthorityFailureStage | None
    store_steps: tuple[EditAuthorityStoreStepV1, ...]
    protocol_outputs: tuple[Any, ...]
    materialization_outputs: tuple[Any, ...]
    platform_blockers: tuple[dict[str, Any], ...]
    review_reasons: tuple[dict[str, Any], ...]
    artifact_store_commit_started: bool
    artifact_store_writes_committed: bool
    recovery_available: bool
    recovery_authorized: bool
    retry_count: int
    source_modified: bool
    build_performed: bool
    process_launched: bool
    product_runtime_performed: bool
    audit_snapshot: dict[str, Any]

    def __post_init__(self) -> None:
        from src.mod_agent.artifacts import ArtifactRef

        if self.result_contract_version != "edit_authority_review_result_v1":
            raise ValueError("Edit Authority result contract version changed.")
        if not self.capability_id or not self.capability_contract_version:
            raise ValueError("Edit Authority result capability identity is incomplete.")
        if not self.approval_identity_hash:
            raise ValueError("Edit Authority result approval identity is incomplete.")
        if self.platform_status not in {"completed", "blocked", "partial"}:
            raise ValueError("Edit Authority platform status is not registered.")
        if self.review_outcome not in {"not_recorded", "approved", "rejected"}:
            raise ValueError("Edit Authority review outcome is not registered.")
        if self.materialization_status not in {
            "not_started",
            "not_applicable",
            "completed",
            "incomplete",
        }:
            raise ValueError("Edit Authority materialization status is not registered.")
        if self.failure_stage not in {
            None,
            "graph_interrupt",
            "checkpoint_construction",
            "checkpoint_store",
            "resume_validation",
            "resume_report_store",
            "store_preflight",
            "materialization_validation",
            "edit_authority_approval_store",
            "evidence_pack_store",
            "implementation_plan_store",
            "binding_resolution_store",
            "internal_execution",
        }:
            raise ValueError("Edit Authority failure stage is not registered.")
        if any(not isinstance(step, EditAuthorityStoreStepV1) for step in self.store_steps):
            raise ValueError("Edit Authority result contains an untyped Store step.")
        if any(not isinstance(ref, ArtifactRef) for ref in (*self.protocol_outputs, *self.materialization_outputs)):
            raise ValueError("Edit Authority result contains an invalid Artifact ref.")
        if self.recovery_authorized or self.retry_count != 0:
            raise ValueError("Edit Authority result cannot authorize recovery or retry.")
        if any(
            (
                self.source_modified,
                self.build_performed,
                self.process_launched,
                self.product_runtime_performed,
            )
        ):
            raise ValueError("Edit Authority result exceeded its side-effect boundary.")

    @staticmethod
    def _ref_dict(ref: Any) -> dict[str, str]:
        return {
            "feature_id": ref.feature_id,
            "artifact_type": ref.artifact_type,
            "path": ref.path,
            "artifact_hash": ref.artifact_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_contract_version": self.result_contract_version,
            "capability_id": self.capability_id,
            "capability_contract_version": self.capability_contract_version,
            "approval_identity_hash": self.approval_identity_hash,
            "platform_status": self.platform_status,
            "review_outcome": self.review_outcome,
            "materialization_status": self.materialization_status,
            "failure_stage": self.failure_stage,
            "store_steps": [step.to_dict() for step in self.store_steps],
            "protocol_outputs": [self._ref_dict(ref) for ref in self.protocol_outputs],
            "materialization_outputs": [
                self._ref_dict(ref) for ref in self.materialization_outputs
            ],
            "platform_blockers": copy.deepcopy(list(self.platform_blockers)),
            "review_reasons": copy.deepcopy(list(self.review_reasons)),
            "artifact_store_commit_started": self.artifact_store_commit_started,
            "artifact_store_writes_committed": self.artifact_store_writes_committed,
            "recovery_available": self.recovery_available,
            "recovery_authorized": self.recovery_authorized,
            "retry_count": self.retry_count,
            "source_modified": self.source_modified,
            "build_performed": self.build_performed,
            "process_launched": self.process_launched,
            "product_runtime_performed": self.product_runtime_performed,
            "audit_snapshot": copy.deepcopy(self.audit_snapshot),
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        capability: EditAuthorityCapabilityDeclaration,
        feature_id: str,
        approval_identity_hash: str,
    ) -> "EditAuthorityReviewResultV1":
        from src.mod_agent.artifacts import ArtifactRef

        expected_fields = {
            "result_contract_version",
            "capability_id",
            "capability_contract_version",
            "approval_identity_hash",
            "platform_status",
            "review_outcome",
            "materialization_status",
            "failure_stage",
            "store_steps",
            "protocol_outputs",
            "materialization_outputs",
            "platform_blockers",
            "review_reasons",
            "artifact_store_commit_started",
            "artifact_store_writes_committed",
            "recovery_available",
            "recovery_authorized",
            "retry_count",
            "source_modified",
            "build_performed",
            "process_launched",
            "product_runtime_performed",
            "audit_snapshot",
        }
        if set(value) != expected_fields:
            raise ValueError("Edit Authority result fields changed.")

        def parse_refs(field: str) -> tuple[ArtifactRef, ...]:
            items = value[field]
            if not isinstance(items, list):
                raise ValueError(f"Edit Authority {field} must be a list.")
            refs: list[ArtifactRef] = []
            for item in items:
                if not isinstance(item, Mapping) or set(item) != {
                    "feature_id",
                    "artifact_type",
                    "path",
                    "artifact_hash",
                }:
                    raise ValueError(f"Edit Authority {field} entry is invalid.")
                values = {
                    key: item[key]
                    for key in (
                        "feature_id",
                        "artifact_type",
                        "path",
                        "artifact_hash",
                    )
                }
                if any(type(item_value) is not str or not item_value for item_value in values.values()):
                    raise ValueError(f"Edit Authority {field} entry is invalid.")
                refs.append(ArtifactRef(**values))
            return tuple(refs)

        store_step_values = value["store_steps"]
        if not isinstance(store_step_values, list):
            raise ValueError("Edit Authority store_steps must be a list.")
        store_steps = tuple(
            EditAuthorityStoreStepV1.from_dict(item)
            for item in store_step_values
            if isinstance(item, Mapping)
        )
        if len(store_steps) != len(store_step_values):
            raise ValueError("Edit Authority store_steps entry is invalid.")
        blockers = value["platform_blockers"]
        reasons = value["review_reasons"]
        audit_snapshot = value["audit_snapshot"]
        if (
            not isinstance(blockers, list)
            or any(not isinstance(item, Mapping) for item in blockers)
            or not isinstance(reasons, list)
            or any(not isinstance(item, Mapping) for item in reasons)
            or not isinstance(audit_snapshot, Mapping)
        ):
            raise ValueError("Edit Authority result detail projection is invalid.")
        for field in (
            "artifact_store_commit_started",
            "artifact_store_writes_committed",
            "recovery_available",
            "recovery_authorized",
            "source_modified",
            "build_performed",
            "process_launched",
            "product_runtime_performed",
        ):
            if type(value[field]) is not bool:
                raise ValueError(f"Edit Authority result {field} must be bool.")
        if type(value["retry_count"]) is not int:
            raise ValueError("Edit Authority result retry_count must be int.")

        result = cls(
            result_contract_version=value["result_contract_version"],
            capability_id=value["capability_id"],
            capability_contract_version=value["capability_contract_version"],
            approval_identity_hash=value["approval_identity_hash"],
            platform_status=value["platform_status"],
            review_outcome=value["review_outcome"],
            materialization_status=value["materialization_status"],
            failure_stage=value["failure_stage"],
            store_steps=store_steps,
            protocol_outputs=parse_refs("protocol_outputs"),
            materialization_outputs=parse_refs("materialization_outputs"),
            platform_blockers=tuple(copy.deepcopy(dict(item)) for item in blockers),
            review_reasons=tuple(copy.deepcopy(dict(item)) for item in reasons),
            artifact_store_commit_started=value["artifact_store_commit_started"],
            artifact_store_writes_committed=value["artifact_store_writes_committed"],
            recovery_available=value["recovery_available"],
            recovery_authorized=value["recovery_authorized"],
            retry_count=value["retry_count"],
            source_modified=value["source_modified"],
            build_performed=value["build_performed"],
            process_launched=value["process_launched"],
            product_runtime_performed=value["product_runtime_performed"],
            audit_snapshot=copy.deepcopy(dict(audit_snapshot)),
        )
        if (
            result.capability_id != capability.capability_id
            or result.capability_contract_version
            != capability.capability_contract_version
            or result.approval_identity_hash != approval_identity_hash
        ):
            raise ValueError("Edit Authority result identity changed.")

        if result.review_outcome == "approved":
            payload_decision = "approve"
            resume_decision_status = "accepted"
            resume_decision_allowed = True
        elif result.review_outcome == "rejected":
            payload_decision = "reject"
            resume_decision_status = "accepted"
            resume_decision_allowed = True
        elif (
            result.failure_stage == "resume_validation"
            and any(step.role == "resume_report" for step in result.store_steps)
        ):
            payload_decision = None
            resume_decision_status = "blocked"
            resume_decision_allowed = False
        else:
            payload_decision = None
            resume_decision_status = None
            resume_decision_allowed = None

        store_failure_stages = set(_EDIT_AUTHORITY_STORE_FAILURE_STAGE_BY_ROLE.values())
        execution_failure_stage = (
            None
            if result.failure_stage in store_failure_stages
            or (
                result.failure_stage == "resume_validation"
                and resume_decision_allowed is False
            )
            else result.failure_stage
        )
        expected = project_edit_authority_review_result(
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=approval_identity_hash,
            store_steps=result.store_steps,
            payload_decision=payload_decision,
            resume_decision_status=resume_decision_status,
            resume_decision_allowed=resume_decision_allowed,
            execution_failure_stage=execution_failure_stage,
            platform_blockers=result.platform_blockers,
            audit_snapshot=result.audit_snapshot,
        )
        if expected.to_dict() != result.to_dict() or result.to_dict() != dict(value):
            raise ValueError("Edit Authority result changed during strict parsing.")
        return result


_EDIT_AUTHORITY_STORE_FAILURE_STAGE_BY_ROLE: dict[str, EditAuthorityFailureStage] = {
    "workflow_checkpoint": "checkpoint_store",
    "resume_report": "resume_report_store",
    "edit_authority_approval": "edit_authority_approval_store",
    "evidence_pack": "evidence_pack_store",
    "implementation_plan": "implementation_plan_store",
    "binding_resolution": "binding_resolution_store",
}


def project_edit_authority_review_result(
    *,
    capability: EditAuthorityCapabilityDeclaration,
    feature_id: str,
    approval_identity_hash: str,
    store_steps: tuple[EditAuthorityStoreStepV1, ...],
    payload_decision: str | None,
    resume_decision_status: str | None,
    resume_decision_allowed: bool | None,
    execution_failure_stage: EditAuthorityFailureStage | None = None,
    platform_blockers: tuple[dict[str, Any], ...] = (),
    audit_snapshot: Mapping[str, Any] | None = None,
) -> EditAuthorityReviewResultV1:
    """Project one complete chain without reading Store or filesystem state."""

    from src.mod_agent.artifacts.store import ArtifactWriteResult

    if not approval_identity_hash:
        raise ValueError("Edit Authority approval identity hash is missing.")
    if payload_decision not in {None, "approve", "reject"}:
        raise ValueError("Edit Authority payload decision is not registered.")
    if resume_decision_status not in {None, "accepted", "blocked"}:
        raise ValueError("Edit Authority ResumeDecision status is not registered.")
    if resume_decision_allowed is not None and type(resume_decision_allowed) is not bool:
        raise ValueError("Edit Authority ResumeDecision allowed fact is invalid.")
    if execution_failure_stage in set(
        _EDIT_AUTHORITY_STORE_FAILURE_STAGE_BY_ROLE.values()
    ):
        raise ValueError(
            "Edit Authority Store failure stage must be derived from a real "
            "noncommitted Store step."
        )
    if (
        (resume_decision_status == "accepted" and resume_decision_allowed is not True)
        or (resume_decision_status == "blocked" and resume_decision_allowed is not False)
        or (resume_decision_status is None and resume_decision_allowed is not None)
    ):
        raise ValueError("Edit Authority ResumeDecision facts disagree.")

    expected_roles = capability.review_write_artifact_types
    actual_roles = tuple(step.role for step in store_steps)
    if actual_roles != expected_roles[: len(actual_roles)]:
        raise ValueError("Edit Authority Store steps are not a declaration prefix.")
    if len(actual_roles) != len(set(actual_roles)):
        raise ValueError("Edit Authority Store steps contain a duplicate role.")
    for step in store_steps:
        if step.store_result.feature_id != feature_id:
            raise ValueError("Edit Authority Store step feature identity changed.")
        if (
            ArtifactWriteResult.from_dict(step.store_result.to_dict())
            != step.store_result
        ):
            raise ValueError("Edit Authority Store step changed during strict parsing.")
    noncommitted = [
        index
        for index, step in enumerate(store_steps)
        if step.store_result.outcome != "committed"
    ]
    if noncommitted and (
        len(noncommitted) != 1 or noncommitted[0] != len(store_steps) - 1
    ):
        raise ValueError("Edit Authority continued after a noncommitted Store step.")

    report_step = next(
        (step for step in store_steps if step.role == "resume_report"),
        None,
    )
    report_committed = bool(
        report_step is not None
        and report_step.store_result.outcome == "committed"
    )
    if report_committed and (
        payload_decision is None
        or resume_decision_status is None
        or resume_decision_allowed is None
    ):
        raise ValueError("Committed ResumeReport lacks exact decision facts.")
    review_outcome: EditAuthorityReviewOutcome = "not_recorded"
    if (
        report_committed
        and resume_decision_status == "accepted"
        and resume_decision_allowed is True
    ):
        if payload_decision == "approve":
            review_outcome = "approved"
        elif payload_decision == "reject":
            review_outcome = "rejected"

    materialization_steps = tuple(
        step
        for step in store_steps
        if step.role not in _PROTOCOL_WRITE_TYPES
    )
    if review_outcome in {"not_recorded", "rejected"} and materialization_steps:
        raise ValueError(
            "Edit Authority materialization continued without an approved review."
        )
    if review_outcome == "rejected" and (
        execution_failure_stage is not None or platform_blockers
    ):
        raise ValueError(
            "Rejected Edit Authority review cannot carry a platform failure."
        )

    materialization_roles = expected_roles[2:]
    committed_roles = {
        step.role
        for step in store_steps
        if step.store_result.outcome == "committed"
    }
    all_materialization_roles_committed = all(
        role in committed_roles for role in materialization_roles
    )
    if (
        review_outcome == "approved"
        and all_materialization_roles_committed
        and not noncommitted
        and execution_failure_stage is not None
    ):
        raise ValueError(
            "Completed Edit Authority writes cannot be downgraded by a later failure."
        )
    if noncommitted:
        if execution_failure_stage is not None:
            raise ValueError(
                "A noncommitted Store step cannot carry a second execution "
                "failure stage."
            )
    else:
        allowed_execution_failure_stages: set[EditAuthorityFailureStage | None]
        if review_outcome == "rejected" or all_materialization_roles_committed:
            allowed_execution_failure_stages = {None}
        elif review_outcome == "not_recorded" and not store_steps:
            allowed_execution_failure_stages = {
                "graph_interrupt",
                "checkpoint_construction",
                "internal_execution",
            }
        elif review_outcome == "not_recorded" and actual_roles == (
            "workflow_checkpoint",
        ):
            allowed_execution_failure_stages = {
                "resume_validation",
                "internal_execution",
            }
        elif (
            review_outcome == "not_recorded"
            and actual_roles == _PROTOCOL_WRITE_TYPES
            and resume_decision_status == "blocked"
            and resume_decision_allowed is False
        ):
            allowed_execution_failure_stages = {None}
        elif review_outcome == "approved" and not materialization_steps:
            allowed_execution_failure_stages = {
                "store_preflight",
                "materialization_validation",
                "internal_execution",
            }
        elif review_outcome == "approved" and materialization_steps:
            allowed_execution_failure_stages = {
                "materialization_validation",
                "internal_execution",
            }
        else:
            allowed_execution_failure_stages = set()

        if execution_failure_stage not in allowed_execution_failure_stages:
            if (
                review_outcome == "approved"
                and not all_materialization_roles_committed
                and execution_failure_stage is None
            ):
                raise ValueError(
                    "Incomplete Edit Authority writes require an exact failure stage."
                )
            raise ValueError(
                "Edit Authority execution failure stage does not match the "
                "actual Store prefix and review phase."
            )

    materialization_status: EditAuthorityMaterializationStatus
    if review_outcome == "not_recorded":
        materialization_status = "not_started"
    elif review_outcome == "rejected":
        materialization_status = "not_applicable"
    else:
        materialization_status = (
            "completed"
            if all_materialization_roles_committed
            and execution_failure_stage is None
            and not noncommitted
            else "incomplete"
        )

    failure_stage = execution_failure_stage
    if noncommitted:
        failure_stage = _EDIT_AUTHORITY_STORE_FAILURE_STAGE_BY_ROLE[
            store_steps[noncommitted[0]].role
        ]
    elif (
        report_committed
        and review_outcome == "not_recorded"
        and resume_decision_allowed is False
    ):
        failure_stage = "resume_validation"

    if failure_stage is None and (
        review_outcome == "rejected"
        or materialization_status == "completed"
    ):
        platform_status: EditAuthorityPlatformStatus = "completed"
    elif (
        failure_stage == "resume_validation"
        and report_committed
        and review_outcome == "not_recorded"
    ):
        platform_status = "blocked"
    elif any(
        step.store_result.outcome == "partial" for step in store_steps
    ):
        platform_status = "partial"
    elif any(
        step.store_result.outcome == "committed" for step in store_steps
    ):
        platform_status = "partial"
    else:
        platform_status = "blocked"

    if platform_status == "completed" and platform_blockers:
        raise ValueError(
            "Completed Edit Authority result cannot carry platform blockers."
        )

    committed_outputs = tuple(
        step.store_result.artifact_ref
        for step in store_steps
        if step.store_result.outcome == "committed"
        and step.store_result.artifact_ref is not None
    )
    protocol_outputs = tuple(
        ref
        for ref in committed_outputs
        if ref.artifact_type in _PROTOCOL_WRITE_TYPES
    )
    materialization_outputs = tuple(
        ref
        for ref in committed_outputs
        if ref.artifact_type not in _PROTOCOL_WRITE_TYPES
    )
    review_reasons: tuple[dict[str, Any], ...] = ()
    if review_outcome == "rejected":
        review_reasons = (
            {
                "stage": "edit_authority_approval",
                "code": "EDIT_AUTHORITY_REJECTED",
                "message": "Human review rejected the exact EditAuthorityRequest.",
            },
        )

    return EditAuthorityReviewResultV1(
        result_contract_version="edit_authority_review_result_v1",
        capability_id=capability.capability_id,
        capability_contract_version=capability.capability_contract_version,
        approval_identity_hash=approval_identity_hash,
        platform_status=platform_status,
        review_outcome=review_outcome,
        materialization_status=materialization_status,
        failure_stage=failure_stage,
        store_steps=store_steps,
        protocol_outputs=protocol_outputs,
        materialization_outputs=materialization_outputs,
        platform_blockers=tuple(copy.deepcopy(platform_blockers)),
        review_reasons=review_reasons,
        artifact_store_commit_started=any(
            step.store_result.commit_started for step in store_steps
        ),
        artifact_store_writes_committed=any(
            step.store_result.outcome == "committed" for step in store_steps
        ),
        recovery_available=any(
            step.store_result.recovery_available for step in store_steps
        ),
        recovery_authorized=False,
        retry_count=0,
        source_modified=False,
        build_performed=False,
        process_launched=False,
        product_runtime_performed=False,
        audit_snapshot=copy.deepcopy(dict(audit_snapshot or {})),
    )


ApprovalIdentityBuilder: TypeAlias = Callable[
    [
        "VersionedEditAuthorityCapabilityRecord",
        Mapping[str, Any],
        str,
        str,
    ],
    dict[str, Any],
]
ApprovalIdentityHasher: TypeAlias = Callable[[Mapping[str, Any]], str]
ActionScopeBuilder: TypeAlias = Callable[
    [Mapping[str, Any], EditAuthorityCapabilityDeclaration],
    dict[str, Any],
]


@dataclass(frozen=True)
class VersionedEditAuthorityCapabilityRecord:
    """Append-only canonical identity semantics for one contract version."""

    declaration: EditAuthorityCapabilityDeclaration
    identity_schema_version: str
    hash_domain: str
    canonical_serialization_id: str
    identity_builder_id: str
    action_projection_id: str
    identity_builder: ApprovalIdentityBuilder
    identity_hasher: ApprovalIdentityHasher
    action_scope_builder: ActionScopeBuilder


@dataclass(frozen=True)
class LegacyV0CapabilitySnapshot:
    """Literal read-only semantics for already-materialized v0 envelopes."""

    capability_id: str
    capability_contract_version: str
    schema_version: str
    projection_kind: str | None
    proposal_schema_version: str | None
    graph_route: str
    execution_mode: str
    side_effect_class: str
    authority_contract_version: str
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    materialization_commit_budget: int
    automatic_retry_budget: int


def _declaration(
    *,
    capability_id: str,
    schema_version: str,
    projection_kind: str | None,
    proposal_schema_version: str | None,
    authority_contract_version: str,
    allowed_actions: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
    input_mode: ArtifactInputMode,
    materializer_kind: MaterializerKind,
    materialized_artifact_fields: tuple[tuple[str, str], ...],
    materializer_write_artifact_types: tuple[str, ...],
    terminal_stage: TerminalStage,
    public_success_status: str,
    materializer_success_status: str,
    approval_input_bindings: tuple[ApprovalInputBinding, ...],
) -> EditAuthorityCapabilityDeclaration:
    return EditAuthorityCapabilityDeclaration(
        capability_id=capability_id,
        capability_contract_version=_CAPABILITY_CONTRACT_VERSION,
        schema_version=schema_version,
        projection_kind=projection_kind,
        proposal_schema_version=proposal_schema_version,
        public_operations=frozenset(("preflight", "resume")),
        graph_route="stagger_edit_authority_gate",
        execution_mode="human_review_then_materialize",
        side_effect_class="artifact_store_write_after_accepted_resume",
        authority_contract_version=authority_contract_version,
        allowed_actions=allowed_actions,
        forbidden_actions=forbidden_actions,
        checkpoint_input_mode=input_mode,
        latest_admission_mode=input_mode,
        materializer_kind=materializer_kind,
        materialized_artifact_fields=materialized_artifact_fields,
        review_write_artifact_types=(
            *_PROTOCOL_WRITE_TYPES,
            *materializer_write_artifact_types,
        ),
        terminal_stage=terminal_stage,
        preflight_success_status=_PREFLIGHT_STATUS,
        public_success_status=public_success_status,
        materializer_success_status=materializer_success_status,
        compatibility_mode="preserve_historical_identity",
        deprecated=False,
        approval_input_bindings=approval_input_bindings,
        materialization_commit_budget=1,
        automatic_retry_budget=0,
    )


_V1_EDIT_AUTHORITY_DECLARATIONS = (
    _declaration(
        capability_id="stagger_edit_authority_generic",
        schema_version=STAGGER_EDIT_AUTHORITY_REQUEST_SCHEMA,
        projection_kind=None,
        proposal_schema_version=None,
        authority_contract_version=EDIT_AUTHORITY_REQUEST_APPROVAL_CONTRACT,
        allowed_actions=_GENERIC_ACTIONS,
        forbidden_actions=_GENERIC_FORBIDDEN_ACTIONS,
        input_mode="request_and_registered_upstreams",
        materializer_kind="generic",
        materialized_artifact_fields=_RESOLUTION_FIELDS,
        materializer_write_artifact_types=(
            "edit_authority_approval",
            "evidence_pack",
            "implementation_plan",
            "binding_resolution",
        ),
        terminal_stage="binding_resolution",
        public_success_status="EXACT_EDIT_AUTHORITY_RESOLVED",
        materializer_success_status="EXACT_EDIT_AUTHORITY_RESOLVED",
        approval_input_bindings=_GENERIC_APPROVAL_INPUTS,
    ),
    _declaration(
        capability_id="stagger_existing_binding_reauthorization",
        schema_version=EXISTING_BINDING_REAUTHORIZATION_REQUEST_SCHEMA,
        projection_kind=None,
        proposal_schema_version=None,
        authority_contract_version=EXISTING_BINDING_AUTHORITY_CONTRACT,
        allowed_actions=_EXISTING_BINDING_ACTIONS,
        forbidden_actions=_EXISTING_BINDING_FORBIDDEN_ACTIONS,
        input_mode="request_only",
        materializer_kind="existing_binding",
        materialized_artifact_fields=_RESOLUTION_FIELDS,
        materializer_write_artifact_types=(
            "edit_authority_approval",
            "binding_resolution",
        ),
        terminal_stage="binding_resolution",
        public_success_status="EXACT_EDIT_AUTHORITY_RESOLVED",
        materializer_success_status="EXISTING_EDIT_AUTHORITY_REAUTHORIZED",
        approval_input_bindings=_EXISTING_BINDING_APPROVAL_INPUTS,
    ),
    _declaration(
        capability_id="stagger_hud_parent_observation",
        schema_version=STAGGER_HUD_PARENT_OBSERVATION_REQUEST_SCHEMA,
        projection_kind=None,
        proposal_schema_version=(
            STAGGER_HUD_PARENT_OBSERVATION_PROPOSAL_SCHEMA
        ),
        authority_contract_version=STAGGER_OBSERVATION_AUTHORITY_CONTRACT_V1,
        allowed_actions=_OBSERVATION_V1_ACTIONS,
        forbidden_actions=_OBSERVATION_FORBIDDEN_ACTIONS,
        input_mode="request_only",
        materializer_kind="hud_observation",
        materialized_artifact_fields=_OBSERVATION_FIELDS,
        materializer_write_artifact_types=(
            "edit_authority_approval",
            "evidence_pack",
            "implementation_plan",
        ),
        terminal_stage="implementation_plan",
        public_success_status=(
            "STAGGER_HUD_PARENT_OBSERVATION_PLAN_AUTHORIZED"
        ),
        materializer_success_status=(
            "STAGGER_HUD_PARENT_OBSERVATION_PLAN_AUTHORIZED"
        ),
        approval_input_bindings=_HUD_APPROVAL_INPUTS,
    ),
    _declaration(
        capability_id="stagger_hud_parent_diagnostic",
        schema_version=STAGGER_HUD_PARENT_DIAGNOSTIC_REQUEST_SCHEMA,
        projection_kind=None,
        proposal_schema_version=(
            STAGGER_HUD_PARENT_DIAGNOSTIC_PROPOSAL_SCHEMA
        ),
        authority_contract_version=STAGGER_OBSERVATION_AUTHORITY_CONTRACT_V2,
        allowed_actions=_OBSERVATION_V2_ACTIONS,
        forbidden_actions=_OBSERVATION_FORBIDDEN_ACTIONS,
        input_mode="request_only",
        materializer_kind="hud_observation",
        materialized_artifact_fields=_OBSERVATION_FIELDS,
        materializer_write_artifact_types=(
            "edit_authority_approval",
            "evidence_pack",
            "implementation_plan",
        ),
        terminal_stage="implementation_plan",
        public_success_status=(
            "STAGGER_HUD_PARENT_DIAGNOSTIC_PLAN_AUTHORIZED"
        ),
        materializer_success_status=(
            "STAGGER_HUD_PARENT_DIAGNOSTIC_PLAN_AUTHORIZED"
        ),
        approval_input_bindings=_HUD_APPROVAL_INPUTS,
    ),
    _declaration(
        capability_id="stagger_bounded_observation",
        schema_version=STAGGER_EDIT_AUTHORITY_REQUEST_SCHEMA,
        projection_kind=STAGGER_BOUNDED_OBSERVATION_PROJECTION_KIND,
        proposal_schema_version=None,
        authority_contract_version=STAGGER_OBSERVATION_AUTHORITY_CONTRACT_V2,
        allowed_actions=_OBSERVATION_V2_ACTIONS,
        forbidden_actions=_OBSERVATION_FORBIDDEN_ACTIONS,
        input_mode="request_only",
        materializer_kind="bounded_observation",
        materialized_artifact_fields=_OBSERVATION_FIELDS,
        materializer_write_artifact_types=(
            "edit_authority_approval",
            "evidence_pack",
            "implementation_plan",
        ),
        terminal_stage="implementation_plan",
        public_success_status=(
            "STAGGER_BOUNDED_OBSERVATION_PLAN_AUTHORIZED"
        ),
        materializer_success_status="BOUNDED_OBSERVATION_PLAN_AUTHORIZED",
        approval_input_bindings=_BOUNDED_APPROVAL_INPUTS,
    ),
)

def _build_frozen_legacy_v0_capability_snapshots(
) -> tuple[LegacyV0CapabilitySnapshot, ...]:
    """Rebuild the literal v0 read contract without consulting v1 declarations."""

    shared_forbidden = (
        "create_binding_resolution_revision",
        "invoke_repair_planner",
        "modify_source",
        "build",
        "launch_process",
        "write_game_directory",
    )
    observation_v2_actions = (
        "create_observation_evidence_pack_revision",
        "create_diagnostic_only_implementation_plan_revision",
        "create_exact_bounded_observation_bindings",
    )
    return (
        LegacyV0CapabilitySnapshot(
            capability_id="stagger_edit_authority_generic",
            capability_contract_version="stagger_edit_authority_capability_v1",
            schema_version="stagger_edit_authority_request_v1",
            projection_kind=None,
            proposal_schema_version=None,
            graph_route="stagger_edit_authority_gate",
            execution_mode="human_review_then_materialize",
            side_effect_class="artifact_store_write_after_accepted_resume",
            authority_contract_version="edit_authority_request_approval_v1",
            allowed_actions=(
                "create_evidence_pack_revision",
                "create_implementation_plan_revision",
                "resolve_exact_edit_binding",
            ),
            forbidden_actions=(
                "invoke_repair_planner",
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
            ),
            materialization_commit_budget=1,
            automatic_retry_budget=0,
        ),
        LegacyV0CapabilitySnapshot(
            capability_id="stagger_existing_binding_reauthorization",
            capability_contract_version="stagger_edit_authority_capability_v1",
            schema_version=(
                "stagger_existing_binding_reauthorization_request_v1"
            ),
            projection_kind=None,
            proposal_schema_version=None,
            graph_route="stagger_edit_authority_gate",
            execution_mode="human_review_then_materialize",
            side_effect_class="artifact_store_write_after_accepted_resume",
            authority_contract_version=(
                "edit_authority_existing_binding_reauthorization_v1"
            ),
            allowed_actions=(
                "reauthorize_existing_edit_binding",
                "create_binding_resolution_revision",
            ),
            forbidden_actions=(
                "create_evidence_pack_revision",
                "create_implementation_plan_revision",
                "create_edit_binding",
                "invoke_repair_planner",
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
            ),
            materialization_commit_budget=1,
            automatic_retry_budget=0,
        ),
        LegacyV0CapabilitySnapshot(
            capability_id="stagger_hud_parent_observation",
            capability_contract_version="stagger_edit_authority_capability_v1",
            schema_version=(
                "stagger_hud_parent_observation_authority_request_v1"
            ),
            projection_kind=None,
            proposal_schema_version=(
                "stagger_hud_parent_observation_authority_v1"
            ),
            graph_route="stagger_edit_authority_gate",
            execution_mode="human_review_then_materialize",
            side_effect_class="artifact_store_write_after_accepted_resume",
            authority_contract_version=(
                "edit_authority_stagger_hud_parent_observation_plan_v1"
            ),
            allowed_actions=(
                "create_observation_evidence_pack_revision",
                "create_diagnostic_implementation_plan_revision",
                "create_observation_only_edit_bindings",
            ),
            forbidden_actions=shared_forbidden,
            materialization_commit_budget=1,
            automatic_retry_budget=0,
        ),
        LegacyV0CapabilitySnapshot(
            capability_id="stagger_hud_parent_diagnostic",
            capability_contract_version="stagger_edit_authority_capability_v1",
            schema_version=(
                "stagger_hud_parent_diagnostic_execution_authority_request_v2"
            ),
            projection_kind=None,
            proposal_schema_version=(
                "stagger_hud_parent_diagnostic_execution_authority_v2"
            ),
            graph_route="stagger_edit_authority_gate",
            execution_mode="human_review_then_materialize",
            side_effect_class="artifact_store_write_after_accepted_resume",
            authority_contract_version=(
                "edit_authority_stagger_hud_parent_diagnostic_plan_v2"
            ),
            allowed_actions=observation_v2_actions,
            forbidden_actions=shared_forbidden,
            materialization_commit_budget=1,
            automatic_retry_budget=0,
        ),
        LegacyV0CapabilitySnapshot(
            capability_id="stagger_bounded_observation",
            capability_contract_version="stagger_edit_authority_capability_v1",
            schema_version="stagger_edit_authority_request_v1",
            projection_kind="bounded_observation_only_plan_materialization",
            proposal_schema_version=None,
            graph_route="stagger_edit_authority_gate",
            execution_mode="human_review_then_materialize",
            side_effect_class="artifact_store_write_after_accepted_resume",
            authority_contract_version=(
                "edit_authority_stagger_hud_parent_diagnostic_plan_v2"
            ),
            allowed_actions=observation_v2_actions,
            forbidden_actions=shared_forbidden,
            materialization_commit_budget=1,
            automatic_retry_budget=0,
        ),
    )


# These literal snapshots are intentionally independent from
# EDIT_AUTHORITY_CAPABILITIES and both current lookup maps.  Future v1
# declaration changes therefore cannot reinterpret immutable legacy envelopes.
_LEGACY_V0_CAPABILITIES = _build_frozen_legacy_v0_capability_snapshots()
_LEGACY_V0_CAPABILITIES_BY_DISCRIMINATOR = {
    (snapshot.schema_version, snapshot.projection_kind): snapshot
    for snapshot in _LEGACY_V0_CAPABILITIES
}


def resolve_edit_authority_capability(
    *,
    schema_version: Any,
    projection_kind: Any,
) -> EditAuthorityCapabilityDeclaration:
    """Resolve one exact discriminator pair without a generic fallback."""

    if not isinstance(schema_version, str):
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority schema_version must be an exact string."
        )
    if projection_kind is not None and not isinstance(projection_kind, str):
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority projection_kind must be an exact string or null."
        )
    try:
        return _CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR[
            (schema_version, projection_kind)
        ].declaration
    except KeyError as exc:
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority schema_version/projection_kind is not supported."
        ) from exc


def resolve_edit_authority_request_capability(
    request_payload: Any,
) -> EditAuthorityCapabilityDeclaration:
    """Resolve the exact capability declared by one Request payload."""

    if not isinstance(request_payload, Mapping):
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority request_payload must be a mapping."
        )
    declaration = resolve_edit_authority_capability(
        schema_version=request_payload.get("schema_version"),
        projection_kind=request_payload.get("projection_kind"),
    )
    expected_proposal_schema = declaration.proposal_schema_version
    if expected_proposal_schema is not None:
        proposal = request_payload.get("proposal")
        if (
            not isinstance(proposal, Mapping)
            or proposal.get("schema_version")
            != expected_proposal_schema
        ):
            raise UnsupportedEditAuthorityCapabilityError(
                "Edit Authority Request capability does not match its "
                "technical proposal schema."
            )
    return declaration


def parse_current_edit_authority_review_result(
    value: Mapping[str, Any],
    *,
    feature_id: str,
    approval_identity_hash: str,
) -> EditAuthorityReviewResultV1:
    """Strictly parse one current result through the declaration owner."""

    capability_id = value.get("capability_id")
    capability_contract_version = value.get("capability_contract_version")
    if type(capability_id) is not str or type(capability_contract_version) is not str:
        raise ValueError("Edit Authority result capability identity is invalid.")
    record = _CURRENT_CAPABILITY_RECORDS_BY_ID.get(capability_id)
    if (
        record is None
        or record.declaration.capability_contract_version
        != capability_contract_version
    ):
        raise ValueError("Edit Authority result capability is not current.")
    return EditAuthorityReviewResultV1.from_dict(
        value,
        capability=record.declaration,
        feature_id=feature_id,
        approval_identity_hash=approval_identity_hash,
    )


def _resolve_legacy_v0_request_capability(
    request_payload: Mapping[str, Any],
) -> LegacyV0CapabilitySnapshot:
    schema_version = request_payload.get("schema_version")
    projection_kind = request_payload.get("projection_kind")
    if not isinstance(schema_version, str):
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority schema_version must be an exact string."
        )
    if projection_kind is not None and not isinstance(projection_kind, str):
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority projection_kind must be an exact string or null."
        )
    try:
        declaration = _LEGACY_V0_CAPABILITIES_BY_DISCRIMINATOR[
            (schema_version, projection_kind)
        ]
    except KeyError as exc:
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority schema_version/projection_kind is not supported."
        ) from exc
    proposal = request_payload.get("proposal")
    if not isinstance(proposal, Mapping):
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority Request proposal must be a mapping."
        )
    if (
        declaration.proposal_schema_version is not None
        and proposal.get("schema_version")
        != declaration.proposal_schema_version
    ):
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority Request capability does not match its technical "
            "proposal schema."
        )
    return declaration


def require_edit_authority_public_operation(
    declaration: EditAuthorityCapabilityDeclaration,
    operation: PublicOperation,
) -> None:
    """Reject a public operation not owned by the declaration."""

    if operation not in declaration.public_operations:
        raise UnsupportedEditAuthorityCapabilityError(
            "Edit Authority capability does not support the requested "
            f"public operation: {operation}."
        )


def _canonical_json_v1(value: Any) -> bytes:
    """Frozen v1 canonical serialization for Approval Identity."""

    return canonical_action_json(value)


def _canonical_json(value: Any) -> bytes:
    """Compatibility alias for the frozen v1 canonical serializer."""

    return _canonical_json_v1(value)


def _approval_identity_hash_v1(
    identity: Mapping[str, Any],
    *,
    _serializer: Callable[[Any], bytes] = _canonical_json_v1,
) -> str:
    """Hash one v1 Approval Identity without consulting current authority."""

    if _serializer is _canonical_json_v1:
        return hash_action_identity(
            identity,
            expected_hash_domain=APPROVAL_IDENTITY_HASH_DOMAIN,
        )
    return "sha256:" + hashlib.sha256(_serializer(identity)).hexdigest()


def _approval_identity_hash(identity: Mapping[str, Any]) -> str:
    """Compatibility alias for the frozen v1 identity hash."""

    return _approval_identity_hash_v1(identity)


def _require_mapping(
    value: Any,
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidEditAuthorityApprovalIdentityError(
            f"Edit Authority {field_name} must be a mapping."
        )
    return value


def _require_value(
    value: Mapping[str, Any],
    key: str,
    *,
    field_name: str,
) -> Any:
    if key not in value:
        raise InvalidEditAuthorityApprovalIdentityError(
            f"Edit Authority {field_name}.{key} is required."
        )
    return copy.deepcopy(value[key])


def _select_fields(
    value: Any,
    fields: tuple[str, ...],
    *,
    field_name: str,
) -> dict[str, Any]:
    source = _require_mapping(value, field_name=field_name)
    return {
        key: _require_value(source, key, field_name=field_name)
        for key in fields
    }


def _value_at_path(
    value: Mapping[str, Any],
    path: tuple[str, ...],
    *,
    field_name: str,
) -> Any:
    current: Any = value
    traversed: list[str] = []
    for key in path:
        traversed.append(key)
        current_mapping = _require_mapping(
            current,
            field_name=f"{field_name}.{'.'.join(traversed[:-1])}".rstrip("."),
        )
        current = _require_value(
            current_mapping,
            key,
            field_name=f"{field_name}.{'.'.join(traversed[:-1])}".rstrip("."),
        )
    return current


def _revision_hash(
    request_payload: Mapping[str, Any],
    binding: ApprovalInputBinding,
) -> str:
    proposal = _require_mapping(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    revision = _value_at_path(
        proposal,
        binding.proposal_revision_path,
        field_name="request_payload.proposal",
    )
    revision_mapping = _require_mapping(
        revision,
        field_name=(
            "request_payload.proposal."
            + ".".join(binding.proposal_revision_path)
        ),
    )
    artifact_hash = revision_mapping.get("artifact_hash")
    if (
        not isinstance(artifact_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", artifact_hash) is None
    ):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority exact input artifact_hash is invalid for role "
            f"{binding.role}."
        )
    return artifact_hash


def _common_source_scope_v1(
    proposal: Mapping[str, Any],
    *,
    _selector: Callable[..., dict[str, Any]] = _select_fields,
) -> dict[str, Any]:
    return _selector(
        proposal.get("current_source"),
        ("canonical_target_path", "sha256", "target_span"),
        field_name="proposal.current_source",
    )


def _hud_action_scope_v1(
    request_payload: Mapping[str, Any],
    declaration: EditAuthorityCapabilityDeclaration,
    *,
    _mapping_reader: Callable[..., Mapping[str, Any]] = _require_mapping,
    _selector: Callable[..., dict[str, Any]] = _select_fields,
    _diagnostic_schema: str = STAGGER_HUD_PARENT_DIAGNOSTIC_PROPOSAL_SCHEMA,
) -> dict[str, Any]:
    proposal = _mapping_reader(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    scope: dict[str, Any] = {
        "current_source": _selector(
            proposal.get("current_source"),
            ("canonical_target_path", "sha256"),
            field_name="proposal.current_source",
        ),
        "diagnostic_contract": _selector(
            proposal,
            (
                "diagnostic_bindings",
                "selected_binding_ids",
                "selected_change_ids",
                "excluded_predecessor_binding_ids",
                "excluded_predecessor_change_ids",
                "diagnostic_plan_projection",
                "why_existing_binding_is_insufficient",
                "root_cause_status",
                "claim_boundary",
                "approval_scope",
            ),
            field_name="proposal",
        ),
    }
    if (
        declaration.proposal_schema_version
        == _diagnostic_schema
    ):
        scope["supporting_source"] = _selector(
            proposal.get("supporting_source"),
            (
                "canonical_target_path",
                "sha256",
                "config_gate",
                "config_section",
                "config_key",
                "default_value",
            ),
            field_name="proposal.supporting_source",
        )
        api_contract = _mapping_reader(
            proposal.get("identity_api_contract"),
            field_name="proposal.identity_api_contract",
        )
        assemblies = api_contract.get("assemblies")
        if not isinstance(assemblies, list) or not assemblies:
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority proposal.identity_api_contract.assemblies "
                "must be a non-empty list."
            )
        scope["identity_api_contract"] = {
            "assemblies": [
                _selector(
                    item,
                    ("role", "sha256"),
                    field_name=(
                        "proposal.identity_api_contract.assemblies[]"
                    ),
                )
                for item in assemblies
            ],
            **_selector(
                api_contract,
                (
                    "crosshair_gui_layer_identity",
                    "unity_object_identity",
                    "compile_boundary",
                ),
                field_name="proposal.identity_api_contract",
            ),
        }
        scope["dependency_hashes"] = copy.deepcopy(
            _mapping_reader(
                request_payload.get("dependency_hashes"),
                field_name="request_payload.dependency_hashes",
            )
        )
    return scope


def _bounded_action_scope_v1(
    request_payload: Mapping[str, Any],
    *,
    _mapping_reader: Callable[..., Mapping[str, Any]] = _require_mapping,
    _selector: Callable[..., dict[str, Any]] = _select_fields,
    _value_reader: Callable[..., Any] = _require_value,
    _source_builder: Callable[[Mapping[str, Any]], dict[str, Any]] = (
        _common_source_scope_v1
    ),
    _serializer: Callable[[Any], bytes] = _canonical_json_v1,
) -> dict[str, Any]:
    proposal = _mapping_reader(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    reviewed = _mapping_reader(
        proposal.get("reviewed_no_write_projection"),
        field_name="proposal.reviewed_no_write_projection",
    )
    action_hashes = _selector(
        reviewed,
        (
            "implementation_plan_projection_hash",
            "patch_proposal_projection_hash",
            "standard_diff_hash",
            "unified_diff_sha256",
            "projected_after_source_sha256",
            "binding_id",
            "change_id",
        ),
        field_name="proposal.reviewed_no_write_projection",
    )
    plan_template = _mapping_reader(
        proposal.get("implementation_plan_template"),
        field_name="proposal.implementation_plan_template",
    )
    actual_plan_hash = "sha256:" + hashlib.sha256(
        _serializer(plan_template)
    ).hexdigest()
    if actual_plan_hash != action_hashes["implementation_plan_projection_hash"]:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority bounded ImplementationPlan projection hash "
            "does not match its canonical template."
        )
    return {
        "action_hashes": action_hashes,
        "current_source": _source_builder(proposal),
        "target_source_evidence_item": _value_reader(
            proposal,
            "target_source_evidence_item",
            field_name="proposal",
        ),
        "historical_identifier_baseline": _selector(
            proposal.get("historical_identifier_baseline"),
            ("authority", "downstream_authority"),
            field_name="proposal.historical_identifier_baseline",
        ),
        "materialization_boundary": copy.deepcopy(
            _mapping_reader(
                proposal.get("materialization_boundary"),
                field_name="proposal.materialization_boundary",
            )
        ),
        "projected_ids": copy.deepcopy(
            _mapping_reader(
                request_payload.get("projected_ids"),
                field_name="request_payload.projected_ids",
            )
        ),
    }


def _build_action_scope_v1(
    request_payload: Mapping[str, Any],
    declaration: EditAuthorityCapabilityDeclaration,
    *,
    _mapping_reader: Callable[..., Mapping[str, Any]] = _require_mapping,
    _selector: Callable[..., dict[str, Any]] = _select_fields,
    _value_reader: Callable[..., Any] = _require_value,
    _source_builder: Callable[[Mapping[str, Any]], dict[str, Any]] = (
        _common_source_scope_v1
    ),
    _hud_builder: Callable[
        [Mapping[str, Any], EditAuthorityCapabilityDeclaration],
        dict[str, Any],
    ] = _hud_action_scope_v1,
    _bounded_builder: Callable[[Mapping[str, Any]], dict[str, Any]] = (
        _bounded_action_scope_v1
    ),
) -> dict[str, Any]:
    proposal = _mapping_reader(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    if declaration.materializer_kind == "generic":
        return {
            "ownership_review": _selector(
                proposal.get("ownership_review"),
                (
                    "stored_runtime_failure_ownership",
                    "replayed_runtime_failure_ownership",
                    "reclassification_approval_required",
                    "runtime_evidence_mutation_allowed",
                ),
                field_name="proposal.ownership_review",
            ),
            "diagnosed_responsibility_anchor": _value_reader(
                proposal,
                "diagnosed_responsibility_anchor",
                field_name="proposal",
            ),
            "current_source": _source_builder(proposal),
            "technical_scope": _selector(
                proposal,
                (
                    "proposed_target_symbol",
                    "proposed_exact_span",
                    "proposed_operation",
                    "existing_binding_gap",
                    "current_edit_authority",
                    "approval_scope",
                    "root_cause_status",
                    "unresolved_root_causes",
                ),
                field_name="proposal",
            ),
            "projected_ids": copy.deepcopy(
                _mapping_reader(
                    request_payload.get("projected_ids"),
                    field_name="request_payload.projected_ids",
                )
            ),
        }
    if declaration.materializer_kind == "existing_binding":
        return {
            "binding_scope": _selector(
                proposal,
                (
                    "binding_id",
                    "preserved_edit_binding",
                    "preserved_change",
                    "preserved_resolved_repair_target",
                ),
                field_name="proposal",
            ),
            "current_source": _source_builder(proposal),
            "ownership_review": _selector(
                proposal.get("ownership_review"),
                (
                    "stored_runtime_failure_ownership",
                    "replayed_runtime_failure_ownership",
                    "runtime_evidence_mutation_allowed",
                ),
                field_name="proposal.ownership_review",
            ),
            "decision_boundary": _selector(
                proposal,
                (
                    "root_cause_status",
                    "unresolved_root_causes",
                    "projection_boundary",
                ),
                field_name="proposal",
            ),
        }
    if declaration.materializer_kind == "hud_observation":
        return _hud_builder(request_payload, declaration)
    if declaration.materializer_kind == "bounded_observation":
        return _bounded_builder(request_payload)
    raise InvalidEditAuthorityApprovalIdentityError(
        "Edit Authority materializer kind has no identity projection."
    )


_V1_CANONICAL_SERIALIZATION_ID = "json_utf8_sort_keys_compact_v1"
_V1_IDENTITY_BUILDER_ID = "edit_authority_approval_identity_builder_v1"
_V1_ACTION_PROJECTION_ID = "stagger_edit_authority_action_scope_v1"


def _build_approval_identity_v1(
    record: VersionedEditAuthorityCapabilityRecord,
    request_payload: Mapping[str, Any],
    feature_id: str,
    run_id: str,
    *,
    _revision_reader: Callable[
        [Mapping[str, Any], ApprovalInputBinding], str
    ] = _revision_hash,
) -> dict[str, Any]:
    """Rebuild one v1 identity solely from its append-only version record."""

    declaration = record.declaration
    exact_inputs = sorted(
        (
            {
                "role": binding.role,
                "artifact_type": binding.artifact_type,
                "artifact_hash": _revision_reader(request_payload, binding),
                "required_freshness": binding.required_freshness,
            }
            for binding in declaration.approval_input_bindings
        ),
        key=lambda item: item["role"],
    )
    feature_spec_input = next(
        item for item in exact_inputs if item["role"] == "feature_spec"
    )
    return {
        "identity_schema_version": record.identity_schema_version,
        "hash_domain": record.hash_domain,
        "capability": {
            "capability_id": declaration.capability_id,
            "capability_contract_version": (
                declaration.capability_contract_version
            ),
            "schema_version": declaration.schema_version,
            "projection_kind": declaration.projection_kind,
            "proposal_schema_version": declaration.proposal_schema_version,
            "authority_contract_version": (
                declaration.authority_contract_version
            ),
        },
        "feature_id": feature_id,
        "run_id": run_id,
        "lineage_root": {
            "feature_id": feature_id,
            "role": "feature_spec",
            "artifact_type": "feature_spec",
            "artifact_hash": feature_spec_input["artifact_hash"],
        },
        "exact_inputs": exact_inputs,
        "action_scope": record.action_scope_builder(
            request_payload,
            declaration,
        ),
        "allowed_actions": list(declaration.allowed_actions),
        "forbidden_actions": list(declaration.forbidden_actions),
        "execution_contract": {
            "graph_route": declaration.graph_route,
            "execution_mode": declaration.execution_mode,
            "side_effect_class": declaration.side_effect_class,
            "checkpoint_input_mode": declaration.checkpoint_input_mode,
            "latest_admission_mode": declaration.latest_admission_mode,
            "materializer_kind": declaration.materializer_kind,
            "materialized_artifact_fields": [
                {
                    "field_name": field_name,
                    "artifact_type": artifact_type,
                }
                for field_name, artifact_type in (
                    declaration.materialized_artifact_fields
                )
            ],
            "review_write_artifact_types": list(
                declaration.review_write_artifact_types
            ),
            "terminal_stage": declaration.terminal_stage,
        },
        "attempt_budget": {
            "materialization_commits": (
                declaration.materialization_commit_budget
            ),
            "automatic_retries": declaration.automatic_retry_budget,
        },
    }


def _versioned_v1_record(
    declaration: EditAuthorityCapabilityDeclaration,
) -> VersionedEditAuthorityCapabilityRecord:
    return VersionedEditAuthorityCapabilityRecord(
        declaration=declaration,
        identity_schema_version=APPROVAL_IDENTITY_SCHEMA_VERSION,
        hash_domain=APPROVAL_IDENTITY_HASH_DOMAIN,
        canonical_serialization_id=_V1_CANONICAL_SERIALIZATION_ID,
        identity_builder_id=_V1_IDENTITY_BUILDER_ID,
        action_projection_id=_V1_ACTION_PROJECTION_ID,
        identity_builder=_build_approval_identity_v1,
        identity_hasher=_approval_identity_hash_v1,
        action_scope_builder=_build_action_scope_v1,
    )


# Append-only historical records own canonical reconstruction semantics.  A
# future current version adds records and advances the two current maps; it does
# not edit or replace the v1 records below.
_VERSIONED_EDIT_AUTHORITY_CAPABILITY_RECORDS = tuple(
    _versioned_v1_record(declaration)
    for declaration in _V1_EDIT_AUTHORITY_DECLARATIONS
)
_VERSIONED_CAPABILITY_RECORDS_BY_KEY = {
    (
        record.identity_schema_version,
        record.declaration.capability_id,
        record.declaration.capability_contract_version,
    ): record
    for record in _VERSIONED_EDIT_AUTHORITY_CAPABILITY_RECORDS
}
if len(_VERSIONED_CAPABILITY_RECORDS_BY_KEY) != len(
    _VERSIONED_EDIT_AUTHORITY_CAPABILITY_RECORDS
):
    raise RuntimeError("Versioned Edit Authority capability key is duplicated.")

_CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR = {
    (
        record.declaration.schema_version,
        record.declaration.projection_kind,
    ): record
    for record in _VERSIONED_EDIT_AUTHORITY_CAPABILITY_RECORDS
}
_CURRENT_CAPABILITY_RECORDS_BY_ID = {
    record.declaration.capability_id: record
    for record in _VERSIONED_EDIT_AUTHORITY_CAPABILITY_RECORDS
}
if len(_CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR) != len(
    _VERSIONED_EDIT_AUTHORITY_CAPABILITY_RECORDS
):
    raise RuntimeError("Edit Authority capability discriminator is duplicated.")
if len(_CURRENT_CAPABILITY_RECORDS_BY_ID) != len(
    _VERSIONED_EDIT_AUTHORITY_CAPABILITY_RECORDS
):
    raise RuntimeError("Edit Authority capability_id is duplicated.")

EDIT_AUTHORITY_CAPABILITIES = tuple(
    record.declaration
    for record in _CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR.values()
)


def _validate_versioned_record(
    record: VersionedEditAuthorityCapabilityRecord,
) -> None:
    if (
        record.identity_builder_id != _V1_IDENTITY_BUILDER_ID
        or record.canonical_serialization_id
        != _V1_CANONICAL_SERIALIZATION_ID
        or record.identity_builder is not _build_approval_identity_v1
        or record.identity_hasher is not _approval_identity_hash_v1
        or not isinstance(record.action_projection_id, str)
        or not record.action_projection_id
        or not callable(record.action_scope_builder)
    ):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority historical identity reconstruction contract is "
            "not supported."
        )


def _resolve_current_request_record(
    request_payload: Mapping[str, Any],
) -> VersionedEditAuthorityCapabilityRecord:
    declaration = resolve_edit_authority_request_capability(request_payload)
    record = _CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR[
        (declaration.schema_version, declaration.projection_kind)
    ]
    if _CURRENT_CAPABILITY_RECORDS_BY_ID.get(declaration.capability_id) is not record:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority current capability indexes are inconsistent."
        )
    return record


def _resolve_historical_versioned_record(
    stored_identity: Mapping[str, Any],
) -> VersionedEditAuthorityCapabilityRecord:
    capability = _require_mapping(
        stored_identity.get("capability"),
        field_name="request_payload.approval_identity.capability",
    )
    key = (
        stored_identity.get("identity_schema_version"),
        capability.get("capability_id"),
        capability.get("capability_contract_version"),
    )
    record = _VERSIONED_CAPABILITY_RECORDS_BY_KEY.get(key)
    if record is None:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority historical capability version is not registered."
        )
    _validate_versioned_record(record)
    return record


def _validate_request_discriminator_for_record(
    request_payload: Mapping[str, Any],
    record: VersionedEditAuthorityCapabilityRecord,
) -> None:
    declaration = record.declaration
    if (
        request_payload.get("schema_version") != declaration.schema_version
        or request_payload.get("projection_kind")
        != declaration.projection_kind
    ):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority Request discriminator does not match its "
            "historical capability version."
        )
    proposal = _require_mapping(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    if (
        declaration.proposal_schema_version is not None
        and proposal.get("schema_version")
        != declaration.proposal_schema_version
    ):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority Request proposal does not match its historical "
            "capability version."
        )


def build_edit_authority_approval_identity(
    *,
    request_payload: Mapping[str, Any],
    feature_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Build the sole versioned identity for one supported approved action."""

    if not isinstance(feature_id, str) or not feature_id:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority feature_id must be non-empty."
        )
    if not isinstance(run_id, str) or not run_id:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority run_id must be non-empty."
        )
    record = _resolve_current_request_record(request_payload)
    _validate_versioned_record(record)
    return record.identity_builder(
        record,
        request_payload,
        feature_id,
        run_id,
    )


def attach_edit_authority_approval_identity(
    *,
    request_payload: Mapping[str, Any],
    feature_id: str,
    run_id: str,
) -> tuple[dict[str, Any], str]:
    """Attach canonical v1 identity and return its Approval hash."""

    if "approval_identity" in request_payload:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority creator cannot replace approval_identity."
        )
    enriched = copy.deepcopy(dict(request_payload))
    identity = build_edit_authority_approval_identity(
        request_payload=enriched,
        feature_id=feature_id,
        run_id=run_id,
    )
    record = _resolve_current_request_record(enriched)
    _validate_versioned_record(record)
    enriched["approval_identity"] = identity
    return enriched, record.identity_hasher(identity)


def validate_edit_authority_request_identity(
    request_artifact_payload: Mapping[str, Any],
    *,
    allow_legacy: bool,
) -> tuple[
    EditAuthorityCapabilityDeclaration | LegacyV0CapabilitySnapshot,
    str,
    str,
]:
    """Validate Request hash and return declaration, mode, and hash."""

    request_payload = _require_mapping(
        request_artifact_payload.get("request_payload"),
        field_name="request_payload",
    )
    request_hash = request_artifact_payload.get("request_hash")
    if (
        not isinstance(request_hash, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", request_hash) is None
    ):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority request_hash is invalid."
        )
    stored_identity = request_payload.get("approval_identity")
    if stored_identity is None:
        if not allow_legacy:
            resolve_edit_authority_request_capability(request_payload)
            raise InvalidEditAuthorityApprovalIdentityError(
                "New Edit Authority Request writes require approval_identity."
            )
        declaration = _resolve_legacy_v0_request_capability(request_payload)
        expected_hash = "sha256:" + hashlib.sha256(
            _canonical_json(request_payload)
        ).hexdigest()
        if request_hash != expected_hash:
            raise InvalidEditAuthorityApprovalIdentityError(
                "Legacy Edit Authority Request hash mismatch."
            )
        return declaration, LEGACY_APPROVAL_IDENTITY_MODE, request_hash
    identity_mapping = _require_mapping(
        stored_identity,
        field_name="request_payload.approval_identity",
    )
    if allow_legacy:
        record = _resolve_historical_versioned_record(identity_mapping)
        _validate_request_discriminator_for_record(request_payload, record)
    else:
        record = _resolve_current_request_record(request_payload)
        _validate_versioned_record(record)
    payload_without_identity = copy.deepcopy(dict(request_payload))
    payload_without_identity.pop("approval_identity", None)
    expected_identity = record.identity_builder(
        record,
        payload_without_identity,
        str(request_artifact_payload.get("feature_id", "")),
        str(request_artifact_payload.get("run_id", "")),
    )
    if dict(identity_mapping) != expected_identity:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority approval_identity does not match the approved action."
        )
    expected_hash = record.identity_hasher(expected_identity)
    if request_hash != expected_hash:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority Request Approval Identity hash mismatch."
        )
    return record.declaration, VERSIONED_APPROVAL_IDENTITY_MODE, request_hash


def edit_authority_identity_sections(
    request_artifact_payload: Mapping[str, Any],
    *,
    allow_legacy: bool,
) -> dict[str, Any]:
    """Return public identity, execution, and audit sections."""

    declaration, identity_mode, request_hash = (
        validate_edit_authority_request_identity(
            request_artifact_payload,
            allow_legacy=allow_legacy,
        )
    )
    request_payload = _require_mapping(
        request_artifact_payload.get("request_payload"),
        field_name="request_payload",
    )
    identity = request_payload.get("approval_identity")
    return {
        "identity_mode": identity_mode,
        "identity_schema_version": (
            identity.get("identity_schema_version")
            if identity_mode == VERSIONED_APPROVAL_IDENTITY_MODE
            else None
        ),
        "request_hash": request_hash,
        "approval_identity": copy.deepcopy(identity),
        "execution_contract_summary": {
            "capability_id": declaration.capability_id,
            "capability_contract_version": (
                declaration.capability_contract_version
            ),
            "authority_contract_version": (
                declaration.authority_contract_version
            ),
            "allowed_actions": list(declaration.allowed_actions),
            "forbidden_actions": list(declaration.forbidden_actions),
            "graph_route": declaration.graph_route,
            "execution_mode": declaration.execution_mode,
            "side_effect_class": declaration.side_effect_class,
            "attempt_budget": {
                "materialization_commits": (
                    declaration.materialization_commit_budget
                ),
                "automatic_retries": declaration.automatic_retry_budget,
            },
        },
    }


def validate_edit_authority_request_upstreams(
    request_artifact_payload: Mapping[str, Any],
    upstreams: list[Mapping[str, Any]],
) -> None:
    """Bind v1 exact input roles to the immutable upstream multiset."""

    _, identity_mode, _ = validate_edit_authority_request_identity(
        request_artifact_payload,
        allow_legacy=False,
    )
    if identity_mode != VERSIONED_APPROVAL_IDENTITY_MODE:
        raise InvalidEditAuthorityApprovalIdentityError(
            "New Edit Authority Request upstream validation requires v1."
        )
    request_payload = _require_mapping(
        request_artifact_payload.get("request_payload"),
        field_name="request_payload",
    )
    identity = _require_mapping(
        request_payload.get("approval_identity"),
        field_name="request_payload.approval_identity",
    )
    exact_inputs = identity.get("exact_inputs")
    if not isinstance(exact_inputs, list):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority approval_identity.exact_inputs must be a list."
        )
    expected = Counter(
        (item["artifact_type"], item["artifact_hash"])
        for item in exact_inputs
        if isinstance(item, Mapping)
    )
    if sum(expected.values()) != len(exact_inputs):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority exact input identity is incomplete."
        )
    actual = Counter(
        (item.get("artifact_type"), item.get("artifact_hash"))
        for item in upstreams
    )
    if actual != expected:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority Request upstream multiset does not match "
            "approval_identity.exact_inputs."
        )


def bind_edit_authority_exact_input_upstreams(
    request_artifact_payload: Mapping[str, Any],
    upstreams: list[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Bind each v1 input role to one immutable upstream occurrence."""

    _, identity_mode, _ = validate_edit_authority_request_identity(
        request_artifact_payload,
        allow_legacy=True,
    )
    if identity_mode == LEGACY_APPROVAL_IDENTITY_MODE:
        return []
    validate_edit_authority_request_upstreams(
        request_artifact_payload,
        upstreams,
    )
    request_payload = _require_mapping(
        request_artifact_payload.get("request_payload"),
        field_name="request_payload",
    )
    identity = _require_mapping(
        request_payload.get("approval_identity"),
        field_name="request_payload.approval_identity",
    )
    exact_inputs = identity.get("exact_inputs")
    if not isinstance(exact_inputs, list):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority approval_identity.exact_inputs must be a list."
        )
    available: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for upstream in upstreams:
        copied = copy.deepcopy(dict(upstream))
        available.setdefault(
            (
                str(copied.get("artifact_type")),
                str(copied.get("artifact_hash")),
            ),
            [],
        ).append(copied)
    bindings: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for requirement in exact_inputs:
        if not isinstance(requirement, Mapping):
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority exact input requirement is invalid."
            )
        copied_requirement = copy.deepcopy(dict(requirement))
        key = (
            str(copied_requirement.get("artifact_type")),
            str(copied_requirement.get("artifact_hash")),
        )
        matches = available.get(key)
        if not matches:
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority exact input has no immutable upstream."
            )
        bindings.append((copied_requirement, matches.pop(0)))
    return bindings


def validate_edit_authority_exact_input_admission(
    request_artifact_payload: Mapping[str, Any],
    input_facts: list[Mapping[str, Any]],
) -> None:
    """Apply the sole role-specific freshness policy to observed facts."""

    request_payload = _require_mapping(
        request_artifact_payload.get("request_payload"),
        field_name="request_payload",
    )
    identity = request_payload.get("approval_identity")
    if identity is None:
        if input_facts:
            raise InvalidEditAuthorityApprovalIdentityError(
                "Legacy Edit Authority Request cannot carry v1 input facts."
            )
        return
    identity_mapping = _require_mapping(
        identity,
        field_name="request_payload.approval_identity",
    )
    exact_inputs = identity_mapping.get("exact_inputs")
    if not isinstance(exact_inputs, list):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority approval_identity.exact_inputs must be a list."
        )
    facts_by_role = {
        str(item.get("role")): item
        for item in input_facts
        if isinstance(item, Mapping)
    }
    if len(facts_by_role) != len(exact_inputs):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority exact input facts are incomplete."
        )
    for requirement in exact_inputs:
        if not isinstance(requirement, Mapping):
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority exact input requirement is invalid."
            )
        role = str(requirement.get("role"))
        fact = facts_by_role.get(role)
        if (
            not isinstance(fact, Mapping)
            or fact.get("artifact_type") != requirement.get("artifact_type")
            or fact.get("artifact_hash") != requirement.get("artifact_hash")
            or fact.get("registered") is not True
        ):
            raise InvalidEditAuthorityApprovalIdentityError(
                f"Edit Authority exact input fact is invalid for role {role}."
            )
        required_freshness = requirement.get("required_freshness")
        if required_freshness == "latest_and_fresh":
            if (
                fact.get("latest_artifact_hash")
                != requirement.get("artifact_hash")
                or fact.get("recursive_fresh") is not True
            ):
                raise InvalidEditAuthorityApprovalIdentityError(
                    f"Edit Authority latest exact input is stale for role {role}."
                )
        elif required_freshness == "registered_exact_and_fresh":
            if fact.get("exact_recursive_fresh") is not True:
                raise InvalidEditAuthorityApprovalIdentityError(
                    "Edit Authority registered exact input is stale for role "
                    f"{role}."
                )
        elif required_freshness != "registered_exact":
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority required_freshness is invalid."
            )


def validate_edit_authority_approval_against_request(
    *,
    approval_payload: Mapping[str, Any],
    request_artifact_payload: Mapping[str, Any],
) -> EditAuthorityCapabilityDeclaration:
    """Validate a direct Approval against its exact Request identity."""

    declaration, identity_mode, request_hash = (
        validate_edit_authority_request_identity(
            request_artifact_payload,
            allow_legacy=False,
        )
    )
    if (
        identity_mode != VERSIONED_APPROVAL_IDENTITY_MODE
        or approval_payload.get("approval_identity_mode")
        != VERSIONED_APPROVAL_IDENTITY_MODE
        or approval_payload.get("approval_identity_schema_version")
        != APPROVAL_IDENTITY_SCHEMA_VERSION
        or approval_payload.get("capability_id") != declaration.capability_id
        or approval_payload.get("capability_contract_version")
        != declaration.capability_contract_version
        or approval_payload.get("request_hash") != request_hash
        or approval_payload.get("approval_hash") != request_hash
        or approval_payload.get("authority_contract_version")
        != declaration.authority_contract_version
        or approval_payload.get("allowed_actions")
        != list(declaration.allowed_actions)
        or approval_payload.get("forbidden_actions")
        != list(declaration.forbidden_actions)
    ):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority Approval does not match its exact Request identity."
        )
    return declaration


def validate_edit_authority_resume_report_against_approval(
    *,
    approval_payload: Mapping[str, Any],
    request_artifact_payload: Mapping[str, Any],
    resume_report_payload: Mapping[str, Any],
) -> EditAuthorityCapabilityDeclaration:
    """Bind one accepted ResumeReport to its exact Request and Approval."""

    declaration = validate_edit_authority_approval_against_request(
        approval_payload=approval_payload,
        request_artifact_payload=request_artifact_payload,
    )
    request_hash = request_artifact_payload.get("request_hash")
    request_run_id = request_artifact_payload.get("run_id")
    if (
        resume_report_payload.get("status") != "accepted"
        or resume_report_payload.get("allowed") is not True
        or resume_report_payload.get("decision") != "approve"
        or resume_report_payload.get("resume_stage")
        != "edit_authority_approval"
        or resume_report_payload.get("authority_request_hash")
        != request_hash
        or resume_report_payload.get("run_id") != request_run_id
        or approval_payload.get("run_id") != request_run_id
        or approval_payload.get("decision") != "approve"
        or resume_report_payload.get("resume_id")
        != approval_payload.get("resume_id")
        or resume_report_payload.get("approved_by")
        != approval_payload.get("approved_by")
        or resume_report_payload.get("approved_at")
        != approval_payload.get("approved_at")
    ):
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority ResumeReport does not match its exact Request "
            "and Approval decision."
        )
    return declaration


def validate_edit_authority_approval_contract(
    approval_payload: Mapping[str, Any],
    *,
    allow_legacy: bool,
) -> EditAuthorityCapabilityDeclaration | LegacyV0CapabilitySnapshot:
    """Delegate Approval capability/action validation to the sole owner."""

    identity_mode = approval_payload.get("approval_identity_mode")
    if identity_mode == VERSIONED_APPROVAL_IDENTITY_MODE:
        capability_id = approval_payload.get("capability_id")
        if allow_legacy:
            record = _VERSIONED_CAPABILITY_RECORDS_BY_KEY.get(
                (
                    approval_payload.get("approval_identity_schema_version"),
                    capability_id,
                    approval_payload.get("capability_contract_version"),
                )
            )
        else:
            record = _CURRENT_CAPABILITY_RECORDS_BY_ID.get(capability_id)
        if record is None:
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority Approval capability version is not supported."
            )
        _validate_versioned_record(record)
        declaration = record.declaration
        if (
            approval_payload.get("approval_identity_schema_version")
            != record.identity_schema_version
            or approval_payload.get("capability_contract_version")
            != declaration.capability_contract_version
            or approval_payload.get("authority_contract_version")
            != declaration.authority_contract_version
            or approval_payload.get("allowed_actions")
            != list(declaration.allowed_actions)
            or approval_payload.get("forbidden_actions")
            != list(declaration.forbidden_actions)
        ):
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority Approval versioned capability contract "
                "does not match its declaration."
            )
        return declaration
    if identity_mode not in {None, LEGACY_APPROVAL_IDENTITY_MODE}:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority Approval identity mode is invalid."
        )
    if not allow_legacy:
        raise InvalidEditAuthorityApprovalIdentityError(
            "New Edit Authority Approval writes require versioned_v1 identity."
        )
    matches = [
        declaration
        for declaration in _LEGACY_V0_CAPABILITIES
        if approval_payload.get("authority_contract_version")
        == declaration.authority_contract_version
        and approval_payload.get("allowed_actions")
        == list(declaration.allowed_actions)
        and approval_payload.get("forbidden_actions")
        == list(declaration.forbidden_actions)
    ]
    if not matches:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Legacy Edit Authority Approval action contract is invalid."
        )
    return matches[0]
