"""Contract parity tests for the Edit Authority capability declarations."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

import src.mod_agent.edit_authority_capabilities as capabilities_module
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.artifacts.store import ArtifactWriteResult
from src.mod_agent.edit_authority_capabilities import (
    EDIT_AUTHORITY_CAPABILITIES,
    EditAuthorityReviewResultV1,
    EditAuthorityStoreStepV1,
    UnsupportedEditAuthorityCapabilityError,
    attach_edit_authority_approval_identity,
    edit_authority_identity_sections,
    require_edit_authority_public_operation,
    project_edit_authority_review_result,
    resolve_edit_authority_capability,
    resolve_edit_authority_request_capability,
    validate_edit_authority_approval_contract,
    validate_edit_authority_request_identity,
)


_PROTOCOL_WRITES = ("workflow_checkpoint", "resume_report")


def _store_step(
    role: str,
    *,
    outcome: str = "committed",
) -> EditAuthorityStoreStepV1:
    feature_id = "feature_review_result"
    if outcome == "committed":
        artifact_hash = role.ljust(64, "0")[:64]
        ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type=role,
            path=f"C:/store/{role}/{artifact_hash[:32]}.json",
            artifact_hash=artifact_hash,
        )
        result = ArtifactWriteResult.from_dict(
            {
                "outcome": "committed",
                "feature_id": feature_id,
                "artifact_type": role,
                "artifact_hash": artifact_hash,
                "artifact_ref": {
                    "feature_id": ref.feature_id,
                    "artifact_type": ref.artifact_type,
                    "path": ref.path,
                    "artifact_hash": ref.artifact_hash,
                },
                "revision_path": ref.path,
                "latest_alias_path": f"C:/store/{role}.json",
                "pending_marker_path": f"C:/store/pending/{artifact_hash}.json",
                "commit_started": True,
                "revision_state": "valid",
                "latest_alias_state": "matches_identity",
                "pending_marker_state": "absent",
                "failure_stage": None,
                "failure_class": None,
                "failure_message": None,
                "recovery_available": False,
                "recovery_authorized": False,
            }
        )
    elif outcome == "blocked_before_commit":
        result = ArtifactWriteResult.from_dict(
            {
                "outcome": "blocked_before_commit",
                "feature_id": feature_id,
                "artifact_type": role,
                "artifact_hash": None,
                "artifact_ref": None,
                "revision_path": None,
                "latest_alias_path": None,
                "pending_marker_path": None,
                "commit_started": False,
                "revision_state": "unavailable",
                "latest_alias_state": "unavailable",
                "pending_marker_state": "unavailable",
                "failure_stage": "admission_validation",
                "failure_class": "ArtifactStoreError",
                "failure_message": "injected Store admission failure",
                "recovery_available": False,
                "recovery_authorized": False,
            }
        )
    elif outcome == "partial":
        artifact_hash = role.ljust(64, "f")[:64]
        result = ArtifactWriteResult.from_dict(
            {
                "outcome": "partial",
                "feature_id": feature_id,
                "artifact_type": role,
                "artifact_hash": artifact_hash,
                "artifact_ref": None,
                "revision_path": f"C:/store/{role}/{artifact_hash[:32]}.json",
                "latest_alias_path": f"C:/store/{role}.json",
                "pending_marker_path": (
                    f"C:/store/pending/{artifact_hash}.json"
                ),
                "commit_started": True,
                "revision_state": "valid",
                "latest_alias_state": "absent",
                "pending_marker_state": "present",
                "failure_stage": "latest_alias_write",
                "failure_class": "ArtifactStoreError",
                "failure_message": "injected partial Store commit",
                "recovery_available": True,
                "recovery_authorized": False,
            }
        )
    else:
        raise ValueError(f"Unsupported test outcome: {outcome}")
    return EditAuthorityStoreStepV1(role=role, store_result=result)


def _replace_current_record(
    monkeypatch: pytest.MonkeyPatch,
    record: capabilities_module.VersionedEditAuthorityCapabilityRecord,
) -> None:
    declaration = record.declaration
    monkeypatch.setitem(
        capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR,
        (declaration.schema_version, declaration.projection_kind),
        record,
    )
    monkeypatch.setitem(
        capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID,
        declaration.capability_id,
        record,
    )


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
    current_record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR[
        discriminator
    ]
    changed_declaration = replace(
        current_record.declaration,
        **declaration_change,
    )
    _replace_current_record(
        monkeypatch,
        replace(current_record, declaration=changed_declaration),
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
    current_record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR[
        discriminator
    ]
    declaration = current_record.declaration
    inputs = list(declaration.approval_input_bindings)
    inputs[0] = replace(inputs[0], required_freshness="registered_exact")
    _replace_current_record(
        monkeypatch,
        replace(
            current_record,
            declaration=replace(
                declaration,
                approval_input_bindings=tuple(inputs),
            ),
        ),
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
    current_record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR[
        discriminator
    ]
    current = current_record.declaration
    _replace_current_record(
        monkeypatch,
        replace(
            current_record,
            declaration=replace(
                current,
                allowed_actions=("future_v1_action",),
            ),
        ),
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


def test_historical_v1_identity_survives_current_version_and_projection_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _generic_identity_request_payload()
    old_enriched, old_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    old_artifact = {
        "feature_id": "feature_identity",
        "run_id": "run_identity",
        "request_hash": old_hash,
        "request_payload": old_enriched,
    }
    old_identity = copy.deepcopy(old_enriched["approval_identity"])
    old_record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID[
        "stagger_edit_authority_generic"
    ]
    old_declaration = old_record.declaration
    old_approval = {
        "approval_identity_mode": "versioned_v1",
        "approval_identity_schema_version": (
            old_record.identity_schema_version
        ),
        "capability_id": old_declaration.capability_id,
        "capability_contract_version": (
            old_declaration.capability_contract_version
        ),
        "authority_contract_version": (
            old_declaration.authority_contract_version
        ),
        "allowed_actions": list(old_declaration.allowed_actions),
        "forbidden_actions": list(old_declaration.forbidden_actions),
    }

    def v2_action_scope(
        _request_payload: object,
        declaration: object,
    ) -> dict[str, object]:
        return {
            "identity_contract_revision": "v2",
            "capability_id": declaration.capability_id,
        }

    v2_declaration = replace(
        old_declaration,
        capability_contract_version="stagger_edit_authority_capability_v2",
    )
    v2_record = replace(
        old_record,
        declaration=v2_declaration,
        action_projection_id="stagger_edit_authority_action_scope_v2",
        action_scope_builder=v2_action_scope,
    )
    monkeypatch.setitem(
        capabilities_module._VERSIONED_CAPABILITY_RECORDS_BY_KEY,
        (
            v2_record.identity_schema_version,
            v2_declaration.capability_id,
            v2_declaration.capability_contract_version,
        ),
        v2_record,
    )
    _replace_current_record(monkeypatch, v2_record)
    monkeypatch.setattr(
        capabilities_module,
        "_build_action_scope_v1",
        lambda _payload, _declaration: {"future_current_helper": True},
    )
    monkeypatch.setattr(
        capabilities_module,
        "APPROVAL_IDENTITY_SCHEMA_VERSION",
        "edit_authority_approval_identity_future",
    )

    historical, mode, validated_hash = validate_edit_authority_request_identity(
        old_artifact,
        allow_legacy=True,
    )
    assert historical is old_declaration
    assert mode == "versioned_v1"
    assert validated_hash == old_hash
    assert old_enriched["approval_identity"] == old_identity
    assert validate_edit_authority_approval_contract(
        old_approval,
        allow_legacy=True,
    ) is old_declaration
    assert edit_authority_identity_sections(
        old_artifact,
        allow_legacy=True,
    )["identity_schema_version"] == "edit_authority_approval_identity_v1"

    with pytest.raises(
        capabilities_module.InvalidEditAuthorityApprovalIdentityError,
        match="does not match the approved action",
    ):
        validate_edit_authority_request_identity(
            old_artifact,
            allow_legacy=False,
        )
    with pytest.raises(
        capabilities_module.InvalidEditAuthorityApprovalIdentityError,
        match="does not match its declaration",
    ):
        validate_edit_authority_approval_contract(
            old_approval,
            allow_legacy=False,
        )

    new_enriched, new_hash = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    assert new_hash != old_hash
    assert new_enriched["approval_identity"]["capability"][
        "capability_contract_version"
    ] == "stagger_edit_authority_capability_v2"
    assert new_enriched["approval_identity"]["action_scope"] == {
        "identity_contract_revision": "v2",
        "capability_id": "stagger_edit_authority_generic",
    }
    new_artifact = {
        "feature_id": "feature_identity",
        "run_id": "run_identity",
        "request_hash": new_hash,
        "request_payload": new_enriched,
    }
    assert validate_edit_authority_request_identity(
        new_artifact,
        allow_legacy=False,
    )[0] is v2_declaration


def test_historical_v1_unknown_reconstruction_builder_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _generic_identity_request_payload()
    enriched, _ = attach_edit_authority_approval_identity(
        request_payload=payload,
        feature_id="feature_identity",
        run_id="run_identity",
    )
    identity = copy.deepcopy(enriched["approval_identity"])
    identity["capability"][
        "capability_contract_version"
    ] = "stagger_edit_authority_capability_unknown_builder"
    enriched["approval_identity"] = identity
    artifact = {
        "feature_id": "feature_identity",
        "run_id": "run_identity",
        "request_hash": capabilities_module._approval_identity_hash(identity),
        "request_payload": enriched,
    }
    old_record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID[
        "stagger_edit_authority_generic"
    ]
    unknown_declaration = replace(
        old_record.declaration,
        capability_contract_version=(
            "stagger_edit_authority_capability_unknown_builder"
        ),
    )
    unknown_record = replace(
        old_record,
        declaration=unknown_declaration,
        identity_builder_id="unknown_identity_builder",
    )
    monkeypatch.setitem(
        capabilities_module._VERSIONED_CAPABILITY_RECORDS_BY_KEY,
        (
            unknown_record.identity_schema_version,
            unknown_declaration.capability_id,
            unknown_declaration.capability_contract_version,
        ),
        unknown_record,
    )

    with pytest.raises(
        capabilities_module.InvalidEditAuthorityApprovalIdentityError,
        match="reconstruction contract is not supported",
    ):
        validate_edit_authority_request_identity(artifact, allow_legacy=True)


def test_current_capability_indexes_cannot_mix_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID[
        "stagger_edit_authority_generic"
    ]
    mixed_record = replace(
        old_record,
        declaration=replace(
            old_record.declaration,
            capability_contract_version="stagger_edit_authority_capability_v2",
        ),
    )
    monkeypatch.setitem(
        capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID,
        old_record.declaration.capability_id,
        mixed_record,
    )

    with pytest.raises(
        capabilities_module.InvalidEditAuthorityApprovalIdentityError,
        match="current capability indexes are inconsistent",
    ):
        attach_edit_authority_approval_identity(
            request_payload=_generic_identity_request_payload(),
            feature_id="feature_identity",
            run_id="run_identity",
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
    record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID[
        declaration.capability_id
    ]
    _replace_current_record(
        monkeypatch,
        replace(
            record,
            action_projection_id="test_vector_projection",
            action_scope_builder=(
                lambda _payload, resolved: {"vector": resolved.capability_id}
            ),
        ),
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


@pytest.mark.parametrize("capability", EDIT_AUTHORITY_CAPABILITIES)
def test_edit_authority_review_result_projects_each_declaration_order(
    capability,
) -> None:
    steps = tuple(
        _store_step(role)
        for role in capability.review_write_artifact_types
    )
    result = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash="sha256:" + ("a" * 64),
        store_steps=steps,
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
    )

    assert tuple(step.role for step in result.store_steps) == (
        capability.review_write_artifact_types
    )
    assert result.platform_status == "completed"
    assert result.review_outcome == "approved"
    assert result.materialization_status == "completed"
    assert result.failure_stage is None
    assert tuple(ref.artifact_type for ref in result.protocol_outputs) == (
        _PROTOCOL_WRITES
    )
    assert tuple(
        ref.artifact_type for ref in result.materialization_outputs
    ) == capability.review_write_artifact_types[2:]
    assert EditAuthorityReviewResultV1.from_dict(
        result.to_dict(),
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash="sha256:" + ("a" * 64),
    ) == result


def test_committed_structured_blocked_resume_is_not_partial_or_rejection() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    result = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash="sha256:" + ("b" * 64),
        store_steps=tuple(_store_step(role) for role in _PROTOCOL_WRITES),
        payload_decision="approve",
        resume_decision_status="blocked",
        resume_decision_allowed=False,
    )

    assert result.platform_status == "blocked"
    assert result.review_outcome == "not_recorded"
    assert result.materialization_status == "not_started"
    assert result.failure_stage == "resume_validation"
    assert len(result.protocol_outputs) == 2
    assert result.materialization_outputs == ()


@pytest.mark.parametrize(
    "failure_stage",
    ("store_preflight", "materialization_validation"),
)
def test_approved_pre_materialization_failure_preserves_protocol_prefix(
    failure_stage: str,
) -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    result = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash="sha256:" + ("c" * 64),
        store_steps=tuple(_store_step(role) for role in _PROTOCOL_WRITES),
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
        execution_failure_stage=failure_stage,
    )

    assert result.platform_status == "partial"
    assert result.review_outcome == "approved"
    assert result.materialization_status == "incomplete"
    assert result.failure_stage == failure_stage
    assert tuple(ref.artifact_type for ref in result.protocol_outputs) == (
        _PROTOCOL_WRITES
    )
    assert result.materialization_outputs == ()


@pytest.mark.parametrize("capability", EDIT_AUTHORITY_CAPABILITIES)
def test_edit_authority_result_stops_at_first_noncommitted_store_role(
    capability,
) -> None:
    roles = capability.review_write_artifact_types
    steps = tuple(_store_step(role) for role in roles[:2]) + (
        _store_step(roles[2], outcome="blocked_before_commit"),
    )
    result = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash="sha256:" + ("d" * 64),
        store_steps=steps,
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
    )

    assert result.platform_status == "partial"
    assert result.review_outcome == "approved"
    assert result.materialization_status == "incomplete"
    assert result.failure_stage == "edit_authority_approval_store"
    assert tuple(ref.artifact_type for ref in result.protocol_outputs) == (
        _PROTOCOL_WRITES
    )
    assert result.materialization_outputs == ()


_STORE_FAILURE_STAGE_BY_ROLE = {
    "workflow_checkpoint": "checkpoint_store",
    "resume_report": "resume_report_store",
    "edit_authority_approval": "edit_authority_approval_store",
    "evidence_pack": "evidence_pack_store",
    "implementation_plan": "implementation_plan_store",
    "binding_resolution": "binding_resolution_store",
}


@pytest.mark.parametrize("capability", EDIT_AUTHORITY_CAPABILITIES)
@pytest.mark.parametrize("outcome", ("blocked_before_commit", "partial"))
def test_every_edit_authority_store_position_stops_with_exact_receipt(
    capability,
    outcome: str,
) -> None:
    roles = capability.review_write_artifact_types
    for failed_index, failed_role in enumerate(roles):
        steps = tuple(_store_step(role) for role in roles[:failed_index]) + (
            _store_step(failed_role, outcome=outcome),
        )
        has_committed_report = failed_index > roles.index("resume_report")
        result = project_edit_authority_review_result(
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("e" * 64),
            store_steps=steps,
            payload_decision="approve" if has_committed_report else None,
            resume_decision_status=(
                "accepted" if has_committed_report else None
            ),
            resume_decision_allowed=(True if has_committed_report else None),
        )

        assert result.store_steps[-1].role == failed_role
        assert result.store_steps[-1].store_result.outcome == outcome
        assert result.failure_stage == _STORE_FAILURE_STAGE_BY_ROLE[failed_role]
        assert result.platform_status == (
            "blocked"
            if failed_index == 0 and outcome == "blocked_before_commit"
            else "partial"
        )
        assert result.review_outcome == (
            "approved" if has_committed_report else "not_recorded"
        )
        assert tuple(ref.artifact_type for ref in result.protocol_outputs) == (
            tuple(
                role
                for role in roles[:failed_index]
                if role in _PROTOCOL_WRITES
            )
        )
        assert tuple(
            ref.artifact_type for ref in result.materialization_outputs
        ) == tuple(
            role
            for role in roles[:failed_index]
            if role not in _PROTOCOL_WRITES
        )


@pytest.mark.parametrize(
    "steps",
    (
        (
            _store_step("workflow_checkpoint"),
            _store_step("edit_authority_approval"),
        ),
        (
            _store_step("workflow_checkpoint"),
            _store_step("resume_report"),
            _store_step("resume_report"),
        ),
        (
            _store_step("workflow_checkpoint", outcome="partial"),
            _store_step("resume_report"),
        ),
    ),
)
def test_edit_authority_projector_rejects_skip_duplicate_and_post_failure_steps(
    steps: tuple[EditAuthorityStoreStepV1, ...],
) -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    with pytest.raises(ValueError):
        project_edit_authority_review_result(
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("f" * 64),
            store_steps=steps,
            payload_decision=None,
            resume_decision_status=None,
            resume_decision_allowed=None,
        )


def test_edit_authority_projector_rejects_role_type_and_feature_drift() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    checkpoint_step = _store_step("workflow_checkpoint")
    with pytest.raises(ValueError, match="role/type changed"):
        EditAuthorityStoreStepV1(
            role="resume_report",
            store_result=checkpoint_step.store_result,
        )
    drifted_step = EditAuthorityStoreStepV1(
        role="workflow_checkpoint",
        store_result=replace(
            checkpoint_step.store_result,
            feature_id="different_feature",
        ),
    )
    with pytest.raises(ValueError, match="feature identity changed"):
        project_edit_authority_review_result(
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("1" * 64),
            store_steps=(drifted_step,),
            payload_decision=None,
            resume_decision_status=None,
            resume_decision_allowed=None,
        )


def test_edit_authority_audit_snapshot_does_not_change_machine_outcome() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    common = {
        "capability": capability,
        "feature_id": "feature_review_result",
        "approval_identity_hash": "sha256:" + ("2" * 64),
        "store_steps": tuple(
            _store_step(role)
            for role in capability.review_write_artifact_types
        ),
        "payload_decision": "approve",
        "resume_decision_status": "accepted",
        "resume_decision_allowed": True,
    }
    first = project_edit_authority_review_result(
        **common,
        audit_snapshot={"revision_total": 1, "presentation": "first"},
    )
    second = project_edit_authority_review_result(
        **common,
        audit_snapshot={"revision_total": 99, "presentation": "second"},
    )

    assert (
        first.platform_status,
        first.review_outcome,
        first.materialization_status,
        first.failure_stage,
        first.store_steps,
        first.protocol_outputs,
        first.materialization_outputs,
    ) == (
        second.platform_status,
        second.review_outcome,
        second.materialization_status,
        second.failure_stage,
        second.store_steps,
        second.protocol_outputs,
        second.materialization_outputs,
    )
    assert first.audit_snapshot != second.audit_snapshot


def test_edit_authority_projector_rejects_inapplicable_or_unexplained_steps() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    all_steps = tuple(
        _store_step(role) for role in capability.review_write_artifact_types
    )
    protocol_steps = all_steps[:2]
    approval_prefix = all_steps[:3]
    common = {
        "capability": capability,
        "feature_id": "feature_review_result",
        "approval_identity_hash": "sha256:" + ("3" * 64),
    }

    with pytest.raises(ValueError, match="without an approved review"):
        project_edit_authority_review_result(
            **common,
            store_steps=all_steps,
            payload_decision="reject",
            resume_decision_status="accepted",
            resume_decision_allowed=True,
        )
    with pytest.raises(ValueError, match="without an approved review"):
        project_edit_authority_review_result(
            **common,
            store_steps=all_steps,
            payload_decision="approve",
            resume_decision_status="blocked",
            resume_decision_allowed=False,
        )
    with pytest.raises(ValueError, match="cannot be downgraded"):
        project_edit_authority_review_result(
            **common,
            store_steps=all_steps,
            payload_decision="approve",
            resume_decision_status="accepted",
            resume_decision_allowed=True,
            execution_failure_stage="internal_execution",
        )
    with pytest.raises(ValueError, match="require an exact failure stage"):
        project_edit_authority_review_result(
            **common,
            store_steps=approval_prefix,
            payload_decision="approve",
            resume_decision_status="accepted",
            resume_decision_allowed=True,
        )
    with pytest.raises(ValueError, match="cannot carry a platform failure"):
        project_edit_authority_review_result(
            **common,
            store_steps=protocol_steps,
            payload_decision="reject",
            resume_decision_status="accepted",
            resume_decision_allowed=True,
            platform_blockers=(
                {
                    "stage": "edit_authority_approval",
                    "code": "INVALID_REJECTION_BLOCKER",
                    "message": "rejection is not a platform failure",
                },
            ),
        )


def test_edit_authority_strict_parser_rejects_rejection_with_materialization() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    rejected = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash="sha256:" + ("4" * 64),
        store_steps=tuple(_store_step(role) for role in _PROTOCOL_WRITES),
        payload_decision="reject",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
    ).to_dict()
    materialization_step = _store_step("edit_authority_approval")
    rejected["store_steps"].append(materialization_step.to_dict())
    rejected["materialization_outputs"].append(
        EditAuthorityReviewResultV1._ref_dict(
            materialization_step.store_result.artifact_ref
        )
    )

    with pytest.raises(ValueError, match="without an approved review"):
        EditAuthorityReviewResultV1.from_dict(
            rejected,
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("4" * 64),
        )


@pytest.mark.parametrize(
    "store_failure_stage",
    (
        "checkpoint_store",
        "resume_report_store",
        "edit_authority_approval_store",
        "evidence_pack_store",
        "implementation_plan_store",
        "binding_resolution_store",
    ),
)
def test_edit_authority_projector_rejects_caller_supplied_store_failure_stage(
    store_failure_stage: str,
) -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )

    with pytest.raises(ValueError, match="must be derived from a real"):
        project_edit_authority_review_result(
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("5" * 64),
            store_steps=tuple(
                _store_step(role)
                for role in capability.review_write_artifact_types[:3]
            ),
            payload_decision="approve",
            resume_decision_status="accepted",
            resume_decision_allowed=True,
            execution_failure_stage=store_failure_stage,
        )


def test_edit_authority_strict_parser_rejects_fabricated_store_failure_stage() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    approval_identity_hash = "sha256:" + ("6" * 64)
    partial = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash=approval_identity_hash,
        store_steps=tuple(
            _store_step(role)
            for role in capability.review_write_artifact_types[:3]
        ),
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
        execution_failure_stage="materialization_validation",
    ).to_dict()
    partial["failure_stage"] = "evidence_pack_store"

    with pytest.raises(ValueError, match="require an exact failure stage"):
        EditAuthorityReviewResultV1.from_dict(
            partial,
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash=approval_identity_hash,
        )


@pytest.mark.parametrize(
    (
        "prefix_length",
        "payload_decision",
        "resume_decision_status",
        "resume_decision_allowed",
        "failure_stage",
    ),
    (
        (0, None, None, None, None),
        (0, None, None, None, "resume_validation"),
        (1, None, None, None, "graph_interrupt"),
        (1, None, None, None, "store_preflight"),
        (2, "approve", "accepted", True, "checkpoint_construction"),
        (2, "approve", "accepted", True, "resume_validation"),
        (3, "approve", "accepted", True, "checkpoint_construction"),
        (3, "approve", "accepted", True, "store_preflight"),
    ),
)
def test_edit_authority_projector_rejects_failure_stage_outside_actual_phase(
    prefix_length: int,
    payload_decision: str | None,
    resume_decision_status: str | None,
    resume_decision_allowed: bool | None,
    failure_stage: str | None,
) -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )

    with pytest.raises(ValueError, match="actual Store prefix|exact failure stage"):
        project_edit_authority_review_result(
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("7" * 64),
            store_steps=tuple(
                _store_step(role)
                for role in capability.review_write_artifact_types[:prefix_length]
            ),
            payload_decision=payload_decision,
            resume_decision_status=resume_decision_status,
            resume_decision_allowed=resume_decision_allowed,
            execution_failure_stage=failure_stage,
        )


def test_edit_authority_projector_rejects_two_failure_facts() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )

    with pytest.raises(ValueError, match="cannot carry a second"):
        project_edit_authority_review_result(
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("8" * 64),
            store_steps=(
                _store_step("workflow_checkpoint", outcome="blocked_before_commit"),
            ),
            payload_decision=None,
            resume_decision_status=None,
            resume_decision_allowed=None,
            execution_failure_stage="internal_execution",
        )


def test_edit_authority_strict_parser_rejects_failure_stage_phase_mismatch() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    approval_identity_hash = "sha256:" + ("9" * 64)
    partial = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash=approval_identity_hash,
        store_steps=tuple(
            _store_step(role)
            for role in capability.review_write_artifact_types[:3]
        ),
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
        execution_failure_stage="materialization_validation",
    ).to_dict()
    partial["failure_stage"] = "store_preflight"

    with pytest.raises(ValueError, match="actual Store prefix"):
        EditAuthorityReviewResultV1.from_dict(
            partial,
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash=approval_identity_hash,
        )


def test_edit_authority_projector_rejects_completed_with_platform_blockers() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )

    with pytest.raises(ValueError, match="cannot carry platform blockers"):
        project_edit_authority_review_result(
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash="sha256:" + ("a" * 64),
            store_steps=tuple(
                _store_step(role)
                for role in capability.review_write_artifact_types
            ),
            payload_decision="approve",
            resume_decision_status="accepted",
            resume_decision_allowed=True,
            platform_blockers=(
                {
                    "stage": "presentation",
                    "code": "INVALID_POST_COMPLETION_BLOCKER",
                    "message": "Presentation is not a platform blocker.",
                },
            ),
        )


def test_edit_authority_strict_parser_rejects_completed_with_platform_blockers() -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    approval_identity_hash = "sha256:" + ("b" * 64)
    completed = project_edit_authority_review_result(
        capability=capability,
        feature_id="feature_review_result",
        approval_identity_hash=approval_identity_hash,
        store_steps=tuple(
            _store_step(role)
            for role in capability.review_write_artifact_types
        ),
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
    ).to_dict()
    completed["platform_blockers"] = [
        {
            "stage": "presentation",
            "code": "INVALID_POST_COMPLETION_BLOCKER",
            "message": "Presentation is not a platform blocker.",
        }
    ]

    with pytest.raises(ValueError, match="cannot carry platform blockers"):
        EditAuthorityReviewResultV1.from_dict(
            completed,
            capability=capability,
            feature_id="feature_review_result",
            approval_identity_hash=approval_identity_hash,
        )
