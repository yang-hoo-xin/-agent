"""Contract parity tests for the Edit Authority capability declarations."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

import src.mod_agent.edit_authority_capabilities as capabilities_module
from src.mod_agent.edit_authority_capabilities import (
    EDIT_AUTHORITY_CAPABILITIES,
    UnsupportedEditAuthorityCapabilityError,
    attach_edit_authority_approval_identity,
    require_edit_authority_public_operation,
    resolve_edit_authority_capability,
    resolve_edit_authority_request_capability,
    validate_edit_authority_request_identity,
)


_PROTOCOL_WRITES = ("workflow_checkpoint", "resume_report")


def _generic_identity_request_payload() -> dict[str, object]:
    def revision(fill: str) -> dict[str, str]:
        return {
            "feature_id": "feature_identity",
            "path": f"{fill}.json",
            "artifact_hash": fill * 64,
        }

    return {
        "schema_version": "stagger_edit_authority_request_v1",
        "proposal": {
            "feature_spec_revision": revision("1"),
            "runtime_evidence_revision": revision("2"),
            "implementation_plan_revision": revision("3"),
            "patch_proposal_revision": revision("4"),
            "ownership_review": {
                "stored_runtime_failure_ownership": {"owner": "observation"},
                "replayed_runtime_failure_ownership": {
                    "owner": "product_behavior"
                },
                "reclassification_approval_required": True,
                "runtime_evidence_mutation_allowed": False,
            },
            "diagnosed_responsibility_anchor": "runtime_result",
            "current_source": {
                "canonical_target_path": "Patches/HitFeedbackBehaviorPatch.cs",
                "sha256": "5" * 64,
                "target_span": {"start_line": 979, "end_line": 984},
            },
            "proposed_target_symbol": "TrySpawnStaggerYellowX",
            "proposed_exact_span": {"start_line": 979, "end_line": 984},
            "proposed_operation": "replace_hud_recttransform_acquisition",
            "existing_binding_gap": "none",
            "current_edit_authority": "edit_binding_004",
            "approval_scope": ["create_exact_binding"],
            "root_cause_status": "confirmed",
            "unresolved_root_causes": [],
        },
        "source_root": "C:/source",
        "projected_ids": {
            "binding_id": "edit_binding_004",
            "change_id": "chg_004",
            "evidence_id": "stagger_repair_001",
        },
    }


def test_v1_identity_excludes_audit_and_presentation_fields() -> None:
    payload = _generic_identity_request_payload()
    enriched, request_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    changed = copy.deepcopy(payload)
    changed["audit_snapshot"] = {
        "shared_store_file_count": 999,
        "shared_store_bytes": 123456,
        "stdout_line_endings": "CRLF",
        "display_path": "C:/presentation-only.json",
    }
    changed_proposal = changed["proposal"]
    assert isinstance(changed_proposal, dict)
    changed_proposal["feature_spec_revision"]["path"] = "D:/other-locator.json"
    changed["source_root"] = "D:/other-run-local-root"
    changed_enriched, changed_hash = attach_edit_authority_approval_identity(
        request_payload=changed,
        feature_id="feature_identity",
        run_id="run_identity",
    )

    exact_inputs = enriched["approval_identity"]["exact_inputs"]
    exact_roles = [item["role"] for item in exact_inputs]
    assert exact_roles == sorted(exact_roles)
    assert changed_hash == request_hash
    assert changed_enriched["approval_identity"] == enriched["approval_identity"]


@pytest.mark.parametrize(
    "mutation",
    ("exact_input", "source", "action"),
)
def test_v1_identity_changes_for_action_identity_mutations(mutation: str) -> None:
    payload = _generic_identity_request_payload()
    _, request_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    changed = copy.deepcopy(payload)
    proposal = changed["proposal"]
    assert isinstance(proposal, dict)
    if mutation == "exact_input":
        proposal["runtime_evidence_revision"]["artifact_hash"] = "a" * 64
    elif mutation == "source":
        proposal["current_source"]["sha256"] = "b" * 64
    else:
        proposal["proposed_operation"] = "different_exact_operation"

    _, changed_hash = attach_edit_authority_approval_identity(
        request_payload=changed,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    assert changed_hash != request_hash


@pytest.mark.parametrize(
    "declaration_change",
    (
        {"allowed_actions": ("different_action",)},
        {"side_effect_class": "artifact_store_write_after_accepted_resume_v2"},
        {"capability_contract_version": "stagger_edit_authority_capability_v2"},
        {"materialization_commit_budget": 2},
    ),
)
def test_v1_identity_changes_with_public_capability_contract(
    monkeypatch: pytest.MonkeyPatch,
    declaration_change: dict[str, object],
) -> None:
    payload = _generic_identity_request_payload()
    _, request_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    discriminator = ("stagger_edit_authority_request_v1", None)
    changed_declaration = replace(
        capabilities_module._CAPABILITIES_BY_DISCRIMINATOR[discriminator],
        **declaration_change,
    )
    monkeypatch.setitem(
        capabilities_module._CAPABILITIES_BY_DISCRIMINATOR,
        discriminator,
        changed_declaration,
    )

    _, changed_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    assert changed_hash != request_hash


def test_v1_identity_changes_with_required_freshness_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _generic_identity_request_payload()
    _, request_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    discriminator = ("stagger_edit_authority_request_v1", None)
    declaration = capabilities_module._CAPABILITIES_BY_DISCRIMINATOR[
        discriminator
    ]
    inputs = list(declaration.approval_input_bindings)
    inputs[0] = replace(inputs[0], required_freshness="registered_exact")
    monkeypatch.setitem(
        capabilities_module._CAPABILITIES_BY_DISCRIMINATOR,
        discriminator,
        replace(declaration, approval_input_bindings=tuple(inputs)),
    )

    _, changed_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    assert changed_hash != request_hash


def test_legacy_v0_read_uses_frozen_capability_not_current_v1_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_payload = {
        "schema_version": "stagger_edit_authority_request_v1",
        "proposal": {},
    }
    request_hash = "sha256:" + capabilities_module.hashlib.sha256(
        capabilities_module._canonical_json(request_payload)
    ).hexdigest()
    artifact_payload = {
        "feature_id": "feature_legacy",
        "run_id": "run_legacy",
        "request_hash": request_hash,
        "request_payload": request_payload,
    }
    discriminator = ("stagger_edit_authority_request_v1", None)
    current = capabilities_module._CAPABILITIES_BY_DISCRIMINATOR[
        discriminator
    ]
    monkeypatch.setitem(
        capabilities_module._CAPABILITIES_BY_DISCRIMINATOR,
        discriminator,
        replace(current, allowed_actions=("future_v1_action",)),
    )

    declaration, identity_mode, validated_hash = (
        validate_edit_authority_request_identity(
            artifact_payload,
            allow_legacy=True,
        )
    )

    assert identity_mode == "legacy_full_request_payload_v0"
    assert validated_hash == request_hash
    assert declaration.allowed_actions == (
        "create_evidence_pack_revision",
        "create_implementation_plan_revision",
        "resolve_exact_edit_binding",
    )
    assert declaration is not current
    rebuilt = (
        capabilities_module._build_frozen_legacy_v0_capability_snapshots()
    )
    rebuilt_generic = next(
        item
        for item in rebuilt
        if item.schema_version == "stagger_edit_authority_request_v1"
        and item.projection_kind is None
    )
    assert rebuilt_generic.allowed_actions == declaration.allowed_actions
    assert rebuilt_generic.allowed_actions != (
        "future_v1_action",
    )


@pytest.mark.parametrize(
    ("capability_id", "expected_roles", "expected_hash"),
    (
        (
            "stagger_edit_authority_generic",
            (
                "feature_spec",
                "implementation_plan",
                "patch_proposal",
                "runtime_evidence",
            ),
            "sha256:d7612566f3d9cc0992c63abc10f3741da196dc8da4009ae1ae96ac9c7c4ddb5e",
        ),
        (
            "stagger_existing_binding_reauthorization",
            (
                "current_implementation_plan",
                "existing_binding_resolution",
                "feature_spec",
                "patch_proposal",
                "predecessor_implementation_plan",
                "runtime_evidence",
            ),
            "sha256:8b5618d06b11742ee74efd8b1908a72da694f5d7f38486f1658451dd7dabc6c8",
        ),
        (
            "stagger_hud_parent_observation",
            (
                "current_implementation_plan",
                "evidence_pack",
                "existing_binding_resolution",
                "existing_edit_authority_approval",
                "feature_spec",
                "patch_proposal",
                "runtime_evidence",
            ),
            "sha256:d5101c50d9f4fcb68671fbcfd8ccfb475a3b1992d0786aa399f75ccceacd8d4a",
        ),
        (
            "stagger_hud_parent_diagnostic",
            (
                "current_implementation_plan",
                "evidence_pack",
                "existing_binding_resolution",
                "existing_edit_authority_approval",
                "feature_spec",
                "patch_proposal",
                "runtime_evidence",
            ),
            "sha256:c7a816597d135d0d24249f0f6e3c4edd2507a84826d9efe428ec1447b0103d55",
        ),
        (
            "stagger_bounded_observation",
            (
                "evidence_pack",
                "feature_spec",
                "historical_implementation_plan",
                "historical_patch_proposal",
                "runtime_evidence",
            ),
            "sha256:dda193038e4782552b3101d3b602457174eca6a616e157bfb3590afc19d7f3f2",
        ),
    ),
)
def test_all_five_identity_vectors_lock_role_sorted_exact_inputs(
    monkeypatch: pytest.MonkeyPatch,
    capability_id: str,
    expected_roles: tuple[str, ...],
    expected_hash: str,
) -> None:
    declaration = next(
        item
        for item in EDIT_AUTHORITY_CAPABILITIES
        if item.capability_id == capability_id
    )
    proposal: dict[str, object] = {}
    if declaration.proposal_schema_version is not None:
        proposal["schema_version"] = declaration.proposal_schema_version
    for binding in declaration.approval_input_bindings:
        current = proposal
        for key in binding.proposal_revision_path[:-1]:
            child = current.setdefault(key, {})
            assert isinstance(child, dict)
            current = child
        current[binding.proposal_revision_path[-1]] = {
            "feature_id": "feature_vector",
            "path": f"{binding.role}.json",
            "artifact_hash": capabilities_module.hashlib.sha256(
                binding.role.encode("utf-8")
            ).hexdigest(),
        }
    request_payload: dict[str, object] = {
        "schema_version": declaration.schema_version,
        "proposal": proposal,
    }
    if declaration.projection_kind is not None:
        request_payload["projection_kind"] = declaration.projection_kind
    monkeypatch.setattr(
        capabilities_module,
        "_build_action_scope",
        lambda _payload, resolved: {"vector": resolved.capability_id},
    )

    enriched, request_hash = attach_edit_authority_approval_identity(
        request_payload=request_payload,
        feature_id="feature_vector",
        run_id="run_vector",
    )

    roles = tuple(
        item["role"]
        for item in enriched["approval_identity"]["exact_inputs"]
    )
    assert roles == expected_roles
    assert request_hash == expected_hash


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
