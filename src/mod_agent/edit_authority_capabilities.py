"""Typed capability authority for Stagger Edit Authority review."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias


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


EDIT_AUTHORITY_CAPABILITIES = (
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

_CAPABILITIES_BY_DISCRIMINATOR = {
    (declaration.schema_version, declaration.projection_kind): declaration
    for declaration in EDIT_AUTHORITY_CAPABILITIES
}
if len(_CAPABILITIES_BY_DISCRIMINATOR) != len(EDIT_AUTHORITY_CAPABILITIES):
    raise RuntimeError("Edit Authority capability discriminator is duplicated.")
_CAPABILITIES_BY_ID = {
    declaration.capability_id: declaration
    for declaration in EDIT_AUTHORITY_CAPABILITIES
}
if len(_CAPABILITIES_BY_ID) != len(EDIT_AUTHORITY_CAPABILITIES):
    raise RuntimeError("Edit Authority capability_id is duplicated.")

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
        return _CAPABILITIES_BY_DISCRIMINATOR[
            (schema_version, projection_kind)
        ]
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


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _approval_identity_hash(identity: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(identity)).hexdigest()


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


def _common_source_scope(proposal: Mapping[str, Any]) -> dict[str, Any]:
    return _select_fields(
        proposal.get("current_source"),
        ("canonical_target_path", "sha256", "target_span"),
        field_name="proposal.current_source",
    )


def _hud_action_scope(
    request_payload: Mapping[str, Any],
    declaration: EditAuthorityCapabilityDeclaration,
) -> dict[str, Any]:
    proposal = _require_mapping(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    scope: dict[str, Any] = {
        "current_source": _select_fields(
            proposal.get("current_source"),
            ("canonical_target_path", "sha256"),
            field_name="proposal.current_source",
        ),
        "diagnostic_contract": _select_fields(
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
        == STAGGER_HUD_PARENT_DIAGNOSTIC_PROPOSAL_SCHEMA
    ):
        scope["supporting_source"] = _select_fields(
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
        api_contract = _require_mapping(
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
                _select_fields(
                    item,
                    ("role", "sha256"),
                    field_name=(
                        "proposal.identity_api_contract.assemblies[]"
                    ),
                )
                for item in assemblies
            ],
            **_select_fields(
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
            _require_mapping(
                request_payload.get("dependency_hashes"),
                field_name="request_payload.dependency_hashes",
            )
        )
    return scope


def _bounded_action_scope(
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    proposal = _require_mapping(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    reviewed = _require_mapping(
        proposal.get("reviewed_no_write_projection"),
        field_name="proposal.reviewed_no_write_projection",
    )
    action_hashes = _select_fields(
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
    plan_template = _require_mapping(
        proposal.get("implementation_plan_template"),
        field_name="proposal.implementation_plan_template",
    )
    actual_plan_hash = "sha256:" + hashlib.sha256(
        _canonical_json(plan_template)
    ).hexdigest()
    if actual_plan_hash != action_hashes["implementation_plan_projection_hash"]:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority bounded ImplementationPlan projection hash "
            "does not match its canonical template."
        )
    return {
        "action_hashes": action_hashes,
        "current_source": _common_source_scope(proposal),
        "target_source_evidence_item": _require_value(
            proposal,
            "target_source_evidence_item",
            field_name="proposal",
        ),
        "historical_identifier_baseline": _select_fields(
            proposal.get("historical_identifier_baseline"),
            ("authority", "downstream_authority"),
            field_name="proposal.historical_identifier_baseline",
        ),
        "materialization_boundary": copy.deepcopy(
            _require_mapping(
                proposal.get("materialization_boundary"),
                field_name="proposal.materialization_boundary",
            )
        ),
        "projected_ids": copy.deepcopy(
            _require_mapping(
                request_payload.get("projected_ids"),
                field_name="request_payload.projected_ids",
            )
        ),
    }


def _build_action_scope(
    request_payload: Mapping[str, Any],
    declaration: EditAuthorityCapabilityDeclaration,
) -> dict[str, Any]:
    proposal = _require_mapping(
        request_payload.get("proposal"),
        field_name="request_payload.proposal",
    )
    if declaration.materializer_kind == "generic":
        return {
            "ownership_review": _select_fields(
                proposal.get("ownership_review"),
                (
                    "stored_runtime_failure_ownership",
                    "replayed_runtime_failure_ownership",
                    "reclassification_approval_required",
                    "runtime_evidence_mutation_allowed",
                ),
                field_name="proposal.ownership_review",
            ),
            "diagnosed_responsibility_anchor": _require_value(
                proposal,
                "diagnosed_responsibility_anchor",
                field_name="proposal",
            ),
            "current_source": _common_source_scope(proposal),
            "technical_scope": _select_fields(
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
                _require_mapping(
                    request_payload.get("projected_ids"),
                    field_name="request_payload.projected_ids",
                )
            ),
        }
    if declaration.materializer_kind == "existing_binding":
        return {
            "binding_scope": _select_fields(
                proposal,
                (
                    "binding_id",
                    "preserved_edit_binding",
                    "preserved_change",
                    "preserved_resolved_repair_target",
                ),
                field_name="proposal",
            ),
            "current_source": _common_source_scope(proposal),
            "ownership_review": _select_fields(
                proposal.get("ownership_review"),
                (
                    "stored_runtime_failure_ownership",
                    "replayed_runtime_failure_ownership",
                    "runtime_evidence_mutation_allowed",
                ),
                field_name="proposal.ownership_review",
            ),
            "decision_boundary": _select_fields(
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
        return _hud_action_scope(request_payload, declaration)
    if declaration.materializer_kind == "bounded_observation":
        return _bounded_action_scope(request_payload)
    raise InvalidEditAuthorityApprovalIdentityError(
        "Edit Authority materializer kind has no identity projection."
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
    declaration = resolve_edit_authority_request_capability(request_payload)
    exact_inputs = sorted(
        (
            {
                "role": binding.role,
                "artifact_type": binding.artifact_type,
                "artifact_hash": _revision_hash(request_payload, binding),
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
        "identity_schema_version": APPROVAL_IDENTITY_SCHEMA_VERSION,
        "hash_domain": APPROVAL_IDENTITY_HASH_DOMAIN,
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
        "action_scope": _build_action_scope(request_payload, declaration),
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
    enriched["approval_identity"] = identity
    return enriched, _approval_identity_hash(identity)


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
    declaration = resolve_edit_authority_request_capability(request_payload)
    identity_mapping = _require_mapping(
        stored_identity,
        field_name="request_payload.approval_identity",
    )
    payload_without_identity = copy.deepcopy(dict(request_payload))
    payload_without_identity.pop("approval_identity", None)
    expected_identity = build_edit_authority_approval_identity(
        request_payload=payload_without_identity,
        feature_id=str(request_artifact_payload.get("feature_id", "")),
        run_id=str(request_artifact_payload.get("run_id", "")),
    )
    if dict(identity_mapping) != expected_identity:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority approval_identity does not match the approved action."
        )
    expected_hash = _approval_identity_hash(expected_identity)
    if request_hash != expected_hash:
        raise InvalidEditAuthorityApprovalIdentityError(
            "Edit Authority Request Approval Identity hash mismatch."
        )
    return declaration, VERSIONED_APPROVAL_IDENTITY_MODE, request_hash


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
            APPROVAL_IDENTITY_SCHEMA_VERSION
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
        declaration = _CAPABILITIES_BY_ID.get(capability_id)
        if declaration is None:
            raise InvalidEditAuthorityApprovalIdentityError(
                "Edit Authority Approval capability_id is not supported."
            )
        if (
            approval_payload.get("approval_identity_schema_version")
            != APPROVAL_IDENTITY_SCHEMA_VERSION
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
