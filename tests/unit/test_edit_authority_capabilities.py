"""Contract parity tests for the Edit Authority capability declarations."""

from __future__ import annotations

import pytest

from src.mod_agent.edit_authority_capabilities import (
    EDIT_AUTHORITY_CAPABILITIES,
    UnsupportedEditAuthorityCapabilityError,
    require_edit_authority_public_operation,
    resolve_edit_authority_capability,
    resolve_edit_authority_request_capability,
)


_PROTOCOL_WRITES = ("workflow_checkpoint", "resume_report")


@pytest.mark.parametrize(
    (
        "schema_version",
        "projection_kind",
        "capability_id",
        "proposal_schema_version",
        "authority_contract_version",
        "allowed_actions",
        "forbidden_actions",
        "checkpoint_input_mode",
        "materializer_kind",
        "materialized_types",
        "review_write_types",
        "terminal_stage",
        "public_status",
        "materializer_status",
    ),
    (
        (
            "stagger_edit_authority_request_v1",
            None,
            "stagger_edit_authority_generic",
            None,
            "edit_authority_request_approval_v1",
            (
                "create_evidence_pack_revision",
                "create_implementation_plan_revision",
                "resolve_exact_edit_binding",
            ),
            (
                "invoke_repair_planner",
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
            ),
            "request_and_registered_upstreams",
            "generic",
            (
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
                "binding_resolution",
            ),
            (
                *_PROTOCOL_WRITES,
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
                "binding_resolution",
            ),
            "binding_resolution",
            "EXACT_EDIT_AUTHORITY_RESOLVED",
            "EXACT_EDIT_AUTHORITY_RESOLVED",
        ),
        (
            "stagger_existing_binding_reauthorization_request_v1",
            None,
            "stagger_existing_binding_reauthorization",
            None,
            "edit_authority_existing_binding_reauthorization_v1",
            (
                "reauthorize_existing_edit_binding",
                "create_binding_resolution_revision",
            ),
            (
                "create_evidence_pack_revision",
                "create_implementation_plan_revision",
                "create_edit_binding",
                "invoke_repair_planner",
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
            ),
            "request_only",
            "existing_binding",
            (
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
                "binding_resolution",
            ),
            (
                *_PROTOCOL_WRITES,
                "edit_authority_approval",
                "binding_resolution",
            ),
            "binding_resolution",
            "EXACT_EDIT_AUTHORITY_RESOLVED",
            "EXISTING_EDIT_AUTHORITY_REAUTHORIZED",
        ),
        (
            "stagger_hud_parent_observation_authority_request_v1",
            None,
            "stagger_hud_parent_observation",
            "stagger_hud_parent_observation_authority_v1",
            "edit_authority_stagger_hud_parent_observation_plan_v1",
            (
                "create_observation_evidence_pack_revision",
                "create_diagnostic_implementation_plan_revision",
                "create_observation_only_edit_bindings",
            ),
            (
                "create_binding_resolution_revision",
                "invoke_repair_planner",
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
            ),
            "request_only",
            "hud_observation",
            (
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
            ),
            (
                *_PROTOCOL_WRITES,
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
            ),
            "implementation_plan",
            "STAGGER_HUD_PARENT_OBSERVATION_PLAN_AUTHORIZED",
            "STAGGER_HUD_PARENT_OBSERVATION_PLAN_AUTHORIZED",
        ),
        (
            "stagger_hud_parent_diagnostic_execution_authority_request_v2",
            None,
            "stagger_hud_parent_diagnostic",
            "stagger_hud_parent_diagnostic_execution_authority_v2",
            "edit_authority_stagger_hud_parent_diagnostic_plan_v2",
            (
                "create_observation_evidence_pack_revision",
                "create_diagnostic_only_implementation_plan_revision",
                "create_exact_bounded_observation_bindings",
            ),
            (
                "create_binding_resolution_revision",
                "invoke_repair_planner",
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
            ),
            "request_only",
            "hud_observation",
            (
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
            ),
            (
                *_PROTOCOL_WRITES,
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
            ),
            "implementation_plan",
            "STAGGER_HUD_PARENT_DIAGNOSTIC_PLAN_AUTHORIZED",
            "STAGGER_HUD_PARENT_DIAGNOSTIC_PLAN_AUTHORIZED",
        ),
        (
            "stagger_edit_authority_request_v1",
            "bounded_observation_only_plan_materialization",
            "stagger_bounded_observation",
            None,
            "edit_authority_stagger_hud_parent_diagnostic_plan_v2",
            (
                "create_observation_evidence_pack_revision",
                "create_diagnostic_only_implementation_plan_revision",
                "create_exact_bounded_observation_bindings",
            ),
            (
                "create_binding_resolution_revision",
                "invoke_repair_planner",
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
            ),
            "request_only",
            "bounded_observation",
            (
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
            ),
            (
                *_PROTOCOL_WRITES,
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
            ),
            "implementation_plan",
            "STAGGER_BOUNDED_OBSERVATION_PLAN_AUTHORIZED",
            "BOUNDED_OBSERVATION_PLAN_AUTHORIZED",
        ),
    ),
)
def test_exact_discriminators_have_one_complete_public_contract(
    schema_version: str,
    projection_kind: str | None,
    capability_id: str,
    proposal_schema_version: str | None,
    authority_contract_version: str,
    allowed_actions: tuple[str, ...],
    forbidden_actions: tuple[str, ...],
    checkpoint_input_mode: str,
    materializer_kind: str,
    materialized_types: tuple[str, ...],
    review_write_types: tuple[str, ...],
    terminal_stage: str,
    public_status: str,
    materializer_status: str,
) -> None:
    declaration = resolve_edit_authority_capability(
        schema_version=schema_version,
        projection_kind=projection_kind,
    )

    assert declaration.capability_id == capability_id
    assert declaration.proposal_schema_version == proposal_schema_version
    assert declaration.capability_contract_version == (
        "stagger_edit_authority_capability_v1"
    )
    assert declaration.public_operations == frozenset(
        {"preflight", "resume"}
    )
    assert declaration.graph_route == "stagger_edit_authority_gate"
    assert declaration.execution_mode == "human_review_then_materialize"
    assert declaration.side_effect_class == (
        "artifact_store_write_after_accepted_resume"
    )
    assert declaration.authority_contract_version == (
        authority_contract_version
    )
    assert declaration.allowed_actions == allowed_actions
    assert declaration.forbidden_actions == forbidden_actions
    assert declaration.checkpoint_input_mode == checkpoint_input_mode
    assert declaration.latest_admission_mode == checkpoint_input_mode
    assert declaration.materializer_kind == materializer_kind
    assert tuple(
        artifact_type
        for artifact_type, _ in declaration.materialized_artifact_fields
    ) == materialized_types
    assert declaration.review_write_artifact_types == review_write_types
    assert declaration.terminal_stage == terminal_stage
    assert declaration.preflight_success_status == (
        "READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION"
    )
    assert declaration.public_success_status == public_status
    assert declaration.materializer_success_status == materializer_status
    assert declaration.compatibility_mode == "preserve_historical_identity"
    assert declaration.deprecated is False


def test_capability_table_has_only_the_five_approved_discriminators() -> None:
    assert len(EDIT_AUTHORITY_CAPABILITIES) == 5
    assert len(
        {
            (item.schema_version, item.projection_kind)
            for item in EDIT_AUTHORITY_CAPABILITIES
        }
    ) == 5


@pytest.mark.parametrize(
    ("schema_version", "projection_kind"),
    (
        (
            "wrong_edit_authority_request_schema",
            "bounded_observation_only_plan_materialization",
        ),
        ("stagger_edit_authority_request_v1", "unknown_projection_kind"),
        ("stagger_edit_authority_request_v1", 1),
        (None, None),
    ),
)
def test_unknown_discriminator_combinations_have_no_generic_fallback(
    schema_version: object,
    projection_kind: object,
) -> None:
    with pytest.raises(UnsupportedEditAuthorityCapabilityError):
        resolve_edit_authority_capability(
            schema_version=schema_version,
            projection_kind=projection_kind,
        )


def test_request_resolver_requires_an_exact_mapping() -> None:
    with pytest.raises(UnsupportedEditAuthorityCapabilityError):
        resolve_edit_authority_request_capability(None)


@pytest.mark.parametrize(
    ("request_schema", "proposal_schema"),
    (
        (
            "stagger_hud_parent_observation_authority_request_v1",
            "stagger_hud_parent_diagnostic_execution_authority_v2",
        ),
        (
            "stagger_hud_parent_diagnostic_execution_authority_request_v2",
            "stagger_hud_parent_observation_authority_v1",
        ),
    ),
)
def test_hud_request_capability_requires_its_exact_proposal_schema(
    request_schema: str,
    proposal_schema: str,
) -> None:
    with pytest.raises(
        UnsupportedEditAuthorityCapabilityError,
        match="does not match its technical proposal schema",
    ):
        resolve_edit_authority_request_capability(
            {
                "schema_version": request_schema,
                "proposal": {"schema_version": proposal_schema},
            }
        )


def test_public_operation_is_enforced_by_the_capability_owner() -> None:
    declaration = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    require_edit_authority_public_operation(declaration, "preflight")
    require_edit_authority_public_operation(declaration, "resume")
