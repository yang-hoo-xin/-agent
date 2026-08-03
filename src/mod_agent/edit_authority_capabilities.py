"""Typed capability authority for Stagger Edit Authority review."""

from __future__ import annotations

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


class UnsupportedEditAuthorityCapabilityError(ValueError):
    """Raised when an exact schema/projection pair is not registered."""


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
    ),
)

_CAPABILITIES_BY_DISCRIMINATOR = {
    (declaration.schema_version, declaration.projection_kind): declaration
    for declaration in EDIT_AUTHORITY_CAPABILITIES
}
if len(_CAPABILITIES_BY_DISCRIMINATOR) != len(EDIT_AUTHORITY_CAPABILITIES):
    raise RuntimeError("Edit Authority capability discriminator is duplicated.")


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
