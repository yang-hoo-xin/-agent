"""Tests for the Phase A LangGraph workflow skeleton."""

from __future__ import annotations

import copy
import inspect
import json
import hashlib
import sys
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.mod_agent.edit_authority_capabilities as capabilities_module
import src.mod_agent.cli as cli_module
import src.mod_agent.local_entry as local_entry_module
from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    StaleArtifactError,
)
from src.mod_agent.artifacts.store import ArtifactWriteResult
from src.mod_agent.artifacts.registry import (
    ArtifactContract,
    ArtifactTypeRegistry,
)
from src.mod_agent.bindings import resolve_runtime_diagnosis_binding
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.domain import DomainAdapterRegistry, build_gtfo_profile
from src.mod_agent.evidence import (
    EvidencePack,
    FakeDenseRetrievalProvider,
    RgLiveEvidenceProvider,
)
from src.mod_agent.execution import ExactDiffApprovalRejectedError
from src.mod_agent.edit_authority_capabilities import (
    EditAuthorityReviewResultV1,
    EditAuthorityStoreStepV1,
    attach_edit_authority_approval_identity,
    project_edit_authority_review_result,
    resolve_edit_authority_capability,
)
from src.mod_agent.knowledge import (
    IDENTITY_FIELD_MAPPING,
    IDENTITY_SCHEMA_VERSION,
    BM25Indexer,
    Chunk,
    CollectionResolver,
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRecord,
    SourceRegistry,
)
from src.mod_agent.local_entry import (
    EditAuthorityPresentationError,
    LocalEntryError,
    VerificationOperationExecutionError,
    VerificationOperationPresentationError,
    preflight_local_runtime,
    preflight_stagger_edit_authority_review,
    resume_stagger_edit_authority_review,
    resume_local_runtime,
)
from src.mod_agent.proposal import RuleBasedProposalCritic
from src.mod_agent.repair import RepairPlanner
from src.mod_agent.runtime import (
    GTFOLogSnapshot,
    GTFOProcessHandle,
    RuntimeEvidenceItem,
    RuntimeProbeProfile,
    build_fake_runtime_evidence_payload,
    build_manual_runtime_evidence_payload,
    build_real_runtime_evidence_payload,
    build_screenshot_metadata,
    make_gtfo_runtime_evidence_factory_from_settings,
    make_runtime_probe_evidence_factory,
)
from src.mod_agent.runtime.stagger_edit_authority import (
    StaggerEditAuthorityApprovalError,
    StaggerEditAuthorityMaterializationError,
    materialize_stagger_edit_authority_approval,
)
from src.mod_agent.verification_operations import (
    RUNTIME_EXECUTION_CONTRACT_VERSION,
    RUNTIME_EXECUTION_KIND,
    RUNTIME_WORKFLOW_COMPLETION,
    InitialAttemptV1,
    NewRuntimeResumeProtocolBindingV1,
    RuntimeExecutionOperationV1,
    VerificationCheckpointIdentityV1,
    VerificationOperationSpec,
    project_verification_operation,
)
from src.mod_agent.workflow import (
    ResumeDecision,
    ResumePayload,
    ResumeValidator,
    WorkflowCheckpointStore,
    build_graph,
    create_initial_state,
    resumed_state_from_decision,
)
from src.mod_agent.workflow.graph import (
    _PROJECT_ROOT,
    _default_proposal_git_binding_factory,
    _run_isolated_apply,
)


def _committed_edit_authority_steps(
    *,
    feature_id: str,
    root: Path,
    artifact_types: tuple[str, ...],
) -> tuple[EditAuthorityStoreStepV1, ...]:
    steps: list[EditAuthorityStoreStepV1] = []
    for artifact_type in artifact_types:
        artifact_hash = artifact_type.ljust(64, "0")[:64]
        ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=str(root / f"{artifact_type}.json"),
            artifact_hash=artifact_hash,
        )
        steps.append(
            EditAuthorityStoreStepV1(
                role=artifact_type,
                store_result=ArtifactWriteResult(
                    outcome="committed",
                    feature_id=feature_id,
                    artifact_type=artifact_type,
                    artifact_hash=artifact_hash,
                    artifact_ref=ref,
                    revision_path=ref.path,
                    latest_alias_path=str(root / f"latest-{artifact_type}.json"),
                    pending_marker_path=str(
                        root / "pending" / f"{artifact_hash}.json"
                    ),
                    commit_started=True,
                    revision_state="valid",
                    latest_alias_state="matches_identity",
                    pending_marker_state="absent",
                    failure_stage=None,
                    failure_class=None,
                    failure_message=None,
                    recovery_available=False,
                    recovery_authorized=False,
                ),
            )
        )
    return tuple(steps)


def _noncommitted_artifact_write_result(
    *,
    feature_id: str,
    artifact_type: str,
    outcome: str,
) -> ArtifactWriteResult:
    partial = outcome == "partial"
    artifact_hash = artifact_type.ljust(64, "f")[:64] if partial else None
    return ArtifactWriteResult.from_dict(
        {
            "outcome": outcome,
            "feature_id": feature_id,
            "artifact_type": artifact_type,
            "artifact_hash": artifact_hash,
            "artifact_ref": None,
            "revision_path": (
                f"C:/store/{artifact_type}/{artifact_hash[:32]}.json"
                if partial and artifact_hash is not None
                else None
            ),
            "latest_alias_path": (
                f"C:/store/{artifact_type}.json" if partial else None
            ),
            "pending_marker_path": (
                f"C:/store/pending/{artifact_hash}.json"
                if partial and artifact_hash is not None
                else None
            ),
            "commit_started": partial,
            "revision_state": "valid" if partial else "unavailable",
            "latest_alias_state": "absent" if partial else "unavailable",
            "pending_marker_state": "present" if partial else "unavailable",
            "failure_stage": (
                "latest_alias_write" if partial else "admission_validation"
            ),
            "failure_class": "ArtifactStoreError",
            "failure_message": "injected protocol Store failure",
            "recovery_available": partial,
            "recovery_authorized": False,
        }
    )


def test_external_evaluation_requirement_requires_factory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="evaluation_context_factory"):
        build_graph(
            ArtifactStore(tmp_path / "artifacts"),
            require_external_evaluation=True,
        )


@pytest.mark.parametrize(
    "scenario",
    (
        "success",
        "materialization_validation",
        "store_preflight",
        "evidence_payload_validation",
        "resume_validation",
        "resume_exception",
        "reject",
        "checkpoint_store_blocked",
        "checkpoint_store_partial",
        "resume_report_store_blocked",
        "resume_report_store_partial",
    ),
)
def test_stagger_edit_authority_approval_runs_only_through_graph_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    from langgraph.types import Command

    default_registry = ArtifactTypeRegistry()
    simple_contracts = [
        ArtifactContract(
            artifact_type=artifact_type,
            schema_version="1.0",
            required_fields=frozenset({"node_name", "stage", "message"}),
            producer_stage=artifact_type,
            consumer_stages=frozenset({"edit_authority_request"}),
            allowed_statuses=frozenset({"success"}),
        )
        for artifact_type in (
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        )
    ]
    registry = ArtifactTypeRegistry(
        contracts=[
            *simple_contracts,
            default_registry.get("edit_authority_request"),
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    upstream_refs: dict[str, ArtifactRef] = {}
    for artifact_type in (
        "feature_spec",
        "runtime_evidence",
        "implementation_plan",
        "patch_proposal",
    ):
        upstream_payload: dict[str, object] = {
            "node_name": artifact_type,
            "stage": artifact_type,
            "message": artifact_type,
        }
        if artifact_type == "implementation_plan":
            upstream_payload["blocking"] = True
        if artifact_type == "patch_proposal":
            upstream_payload["diff_intent"] = []
        upstream_refs[artifact_type] = store.write(
            feature_id="feature_edit_authority",
            artifact_type=artifact_type,
            payload=upstream_payload,
        )
    request_payload, request_hash = _generic_versioned_request_payload(
        feature_id="feature_edit_authority",
        run_id="run_edit_authority",
        source_root=tmp_path,
        upstream_refs=upstream_refs,
    )
    request_ref = store.write(
        feature_id="feature_edit_authority",
        artifact_type="edit_authority_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Awaiting graph approval.",
            "status": "pending_human_approval",
            "feature_id": "feature_edit_authority",
            "run_id": "run_edit_authority",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        upstream_refs=list(upstream_refs.values()),
        exact_revision_upstream_types=set(upstream_refs),
    )
    captured: dict[str, object] = {}

    def materialize(**kwargs):
        captured.update(kwargs)
        if scenario == "materialization_validation":
            raise RuntimeError("projection stopped after approval")
        if scenario == "store_preflight":
            raise StaggerEditAuthorityMaterializationError(
                "Store probe stopped before EditAuthorityApproval",
                failure_stage="store_preflight",
            )
        if scenario == "evidence_payload_validation":
            approval_step = _committed_edit_authority_steps(
                feature_id="feature_edit_authority",
                root=tmp_path,
                artifact_types=("edit_authority_approval",),
            )
            raise StaggerEditAuthorityMaterializationError(
                "EvidencePack payload validation failed",
                failure_stage="materialization_validation",
                store_steps=approval_step,
            )
        store_steps = _committed_edit_authority_steps(
            feature_id="feature_edit_authority",
            root=tmp_path,
            artifact_types=(
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
                "binding_resolution",
            ),
        )
        return {
            "status": "EXACT_EDIT_AUTHORITY_RESOLVED",
            "store_steps": store_steps,
            **{
                field_name: {
                    "feature_id": "feature_edit_authority",
                    "path": str(tmp_path / f"{artifact_type}.json"),
                    "artifact_hash": artifact_type.ljust(64, "0")[:64],
                }
                for artifact_type, field_name in (
                    (
                        "edit_authority_approval",
                        "edit_authority_approval_revision",
                    ),
                    ("evidence_pack", "evidence_pack_revision"),
                    (
                        "implementation_plan",
                        "implementation_plan_revision",
                    ),
                    ("binding_resolution", "binding_resolution_revision"),
                )
            },
        }

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "materialize_stagger_edit_authority_approval",
        materialize,
    )
    if scenario in {"checkpoint_store_blocked", "checkpoint_store_partial"}:
        monkeypatch.setattr(
            WorkflowCheckpointStore,
            "create_checkpoint_with_result",
            lambda _self, *_args, **_kwargs: _noncommitted_artifact_write_result(
                feature_id="feature_edit_authority",
                artifact_type="workflow_checkpoint",
                outcome=(
                    "partial"
                    if scenario == "checkpoint_store_partial"
                    else "blocked_before_commit"
                ),
            ),
        )
    elif scenario in {
        "resume_report_store_blocked",
        "resume_report_store_partial",
    }:
        monkeypatch.setattr(
            WorkflowCheckpointStore,
            "resume_with_result",
            lambda _self, *_args, **_kwargs: (
                ResumeDecision(
                    status="accepted",
                    allowed=True,
                    reason="Resume payload accepted.",
                    applied_updates={"approvals.edit_authority": True},
                ),
                _noncommitted_artifact_write_result(
                    feature_id="feature_edit_authority",
                    artifact_type="resume_report",
                    outcome=(
                        "partial"
                        if scenario == "resume_report_store_partial"
                        else "blocked_before_commit"
                    ),
                ),
            ),
        )
    elif scenario == "resume_exception":
        def fail_resume(*_args, **_kwargs):
            raise ValueError("injected resume payload construction failure")

        monkeypatch.setattr(
            WorkflowCheckpointStore,
            "resume_with_result",
            fail_resume,
        )
    graph = build_graph(
        store,
        edit_authority_request_ref=request_ref,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
    )
    config = {
        "configurable": {
            "thread_id": (
                "stagger_edit_authority_graph_failed"
                if scenario != "success"
                else "stagger_edit_authority_graph_001"
            )
        }
    }
    state = create_initial_state(
        run_id="run_edit_authority",
        request_id="feature_edit_authority",
        user_request="Approve one exact Stagger edit scope.",
    )
    state["feature_id"] = "feature_edit_authority"

    interrupted = graph.invoke(state, config)

    assert "__interrupt__" in interrupted
    request = interrupted["__interrupt__"][0].value
    assert request["stage"] == "edit_authority_approval"
    assert request["payload"]["request_hash"] == request_hash
    assert store.list_feature_artifact_revisions(
        "feature_edit_authority",
        "edit_authority_approval",
    ) == []

    result = graph.invoke(
        Command(
            resume={
                "resume_id": "resume_edit_authority_001",
                "run_id": "run_edit_authority",
                "stage": "edit_authority_approval",
                "decision": "reject" if scenario == "reject" else "approve",
                "approved_by": (
                    "" if scenario == "resume_validation" else "user"
                ),
                "approved_at": "2026-07-30T12:00:00+08:00",
                "artifact_refs": request["artifact_refs"],
                "authority_request_hash": request_hash,
            }
        ),
        config,
    )

    if scenario in {"checkpoint_store_blocked", "checkpoint_store_partial"}:
        assert "workflow_checkpoint" not in result["artifacts"]
        assert "resume_report" not in result["artifacts"]
        assert captured == {}
        machine_result = result["edit_authority_review_result"]
        assert machine_result["platform_status"] == (
            "partial" if scenario == "checkpoint_store_partial" else "blocked"
        )
        assert machine_result["failure_stage"] == "checkpoint_store"
        assert machine_result["store_steps"][0]["store_result"]["outcome"] == (
            "partial"
            if scenario == "checkpoint_store_partial"
            else "blocked_before_commit"
        )
    elif scenario in {
        "resume_report_store_blocked",
        "resume_report_store_partial",
    }:
        assert "workflow_checkpoint" in result["artifacts"]
        assert "resume_report" not in result["artifacts"]
        assert captured == {}
        machine_result = result["edit_authority_review_result"]
        assert machine_result["platform_status"] == "partial"
        assert machine_result["failure_stage"] == "resume_report_store"
        assert machine_result["store_steps"][-1]["store_result"]["outcome"] == (
            "partial"
            if scenario == "resume_report_store_partial"
            else "blocked_before_commit"
        )
    elif scenario == "resume_exception":
        assert "workflow_checkpoint" in result["artifacts"]
        assert "resume_report" not in result["artifacts"]
        assert captured == {}
        machine_result = result["edit_authority_review_result"]
        assert machine_result["platform_status"] == "partial"
        assert machine_result["review_outcome"] == "not_recorded"
        assert machine_result["failure_stage"] == "resume_validation"
        assert len(machine_result["store_steps"]) == 1
    elif scenario == "resume_validation":
        assert "resume_report" in result["artifacts"]
        assert captured == {}
        machine_result = result["edit_authority_review_result"]
        assert machine_result["platform_status"] == "blocked"
        assert machine_result["review_outcome"] == "not_recorded"
        assert machine_result["materialization_status"] == "not_started"
        assert machine_result["failure_stage"] == "resume_validation"
        assert len(machine_result["protocol_outputs"]) == 2
        assert machine_result["materialization_outputs"] == []
    elif scenario == "reject":
        assert "resume_report" in result["artifacts"]
        assert captured == {}
        machine_result = result["edit_authority_review_result"]
        assert machine_result["platform_status"] == "completed"
        assert machine_result["review_outcome"] == "rejected"
        assert machine_result["materialization_status"] == "not_applicable"
        assert machine_result["failure_stage"] is None
        assert len(machine_result["protocol_outputs"]) == 2
        assert machine_result["materialization_outputs"] == []
    else:
        assert "resume_report" in result["artifacts"]
        assert captured["edit_authority_request_path"] == request_ref.path
        assert captured["edit_authority_request_hash"] == (
            request_ref.artifact_hash
        )
    if scenario in {
        "materialization_validation",
        "evidence_payload_validation",
        "store_preflight",
    }:
        assert result["current_stage"] == "blocked"
        assert "binding_resolution" not in result["artifacts"]
        assert result["approvals"].get("edit_authority") is not True
        expected_code = (
            "EDIT_AUTHORITY_MATERIALIZATION_VALIDATION_FAILED"
            if scenario == "materialization_validation"
            else "EDIT_AUTHORITY_MATERIALIZATION_FAILED"
        )
        assert any(blocker["code"] == expected_code for blocker in result["blockers"])
        assert result["edit_authority_review_result"]["platform_status"] == (
            "partial"
        )
        assert result["edit_authority_review_result"]["failure_stage"] == (
            "materialization_validation"
            if scenario == "evidence_payload_validation"
            else scenario
        )
        assert result["edit_authority_review_result"]["review_outcome"] == (
            "approved"
        )
        assert result["edit_authority_review_result"]["materialization_status"] == (
            "incomplete"
        )
        assert len(result["edit_authority_review_result"]["protocol_outputs"]) == 2
        assert result["edit_authority_review_result"]["materialization_outputs"] == (
            []
            if scenario != "evidence_payload_validation"
            else [
                result["edit_authority_review_result"]["store_steps"][2][
                    "store_result"
                ]["artifact_ref"]
            ]
        )
    elif scenario == "success":
        assert result["current_stage"] == "binding_resolution"
        assert result["approvals"]["edit_authority"] is True
        assert "binding_resolution" in result["artifacts"]
    checkpoint_path = result["artifacts"].get("workflow_checkpoint")
    if checkpoint_path is not None:
        checkpoint_ref = ArtifactRef(
            feature_id="feature_edit_authority",
            artifact_type="workflow_checkpoint",
            path=checkpoint_path,
            artifact_hash=result["artifact_hashes"]["workflow_checkpoint"],
        )
        checkpoint = store.read(checkpoint_ref)["data"]
        assert "edit_authority_review_result" not in checkpoint["state_snapshot"]


def test_existing_binding_reauthorization_exposes_narrow_graph_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get("edit_authority_request"),
        required_upstream_artifacts=frozenset(),
        required_exact_revision_upstream_artifacts=frozenset(),
    )
    registry = ArtifactTypeRegistry(
        contracts=[
            request_contract,
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    request_payload = {
        "schema_version": (
            "stagger_existing_binding_reauthorization_request_v1"
        ),
        "proposal": {},
        "source_root": str(tmp_path),
    }
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_ref = _write_historical_edit_authority_request(
        store,
        feature_id="feature_existing_binding",
        payload={
            "node_name": (
                "request_stagger_existing_binding_reauthorization"
            ),
            "stage": "edit_authority_request",
            "message": "Awaiting graph approval.",
            "status": "pending_human_approval",
            "feature_id": "feature_existing_binding",
            "run_id": "run_existing_binding",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
    )
    declaration = resolve_edit_authority_capability(
        schema_version=(
            "stagger_existing_binding_reauthorization_request_v1"
        ),
        projection_kind=None,
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "_validate_graph_edit_authority_exact_inputs",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "validate_edit_authority_request_identity",
        lambda _request, allow_legacy: (
            declaration,
            "versioned_v1",
            request_hash,
        ),
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph.edit_authority_identity_sections",
        lambda _request, allow_legacy: {
            "identity_mode": "versioned_v1",
            "identity_schema_version": "edit_authority_approval_identity_v1",
            "request_hash": request_hash,
            "approval_identity": {"test_scope": "graph_action_projection"},
            "execution_contract_summary": {
                "allowed_actions": list(declaration.allowed_actions),
                "forbidden_actions": list(declaration.forbidden_actions),
            },
        },
    )
    graph = build_graph(
        store,
        edit_authority_request_ref=request_ref,
        checkpointer=(
            WorkflowCheckpointStore.langgraph_memory_checkpointer()
        ),
    )
    state = create_initial_state(
        run_id="run_existing_binding",
        request_id="feature_existing_binding",
        user_request="Review one existing Stagger edit binding.",
    )
    state["feature_id"] = "feature_existing_binding"

    interrupted = graph.invoke(
        state,
        {
            "configurable": {
                "thread_id": "existing_binding_reauthorization_001"
            }
        },
    )

    request = interrupted["__interrupt__"][0].value
    assert request["payload"]["allowed_actions"] == [
        "reauthorize_existing_edit_binding",
        "create_binding_resolution_revision",
    ]
    assert request["payload"]["forbidden_actions"] == [
        "create_evidence_pack_revision",
        "create_implementation_plan_revision",
        "create_edit_binding",
        "invoke_repair_planner",
        "modify_source",
        "build",
        "launch_process",
        "write_game_directory",
    ]
    assert store.list_feature_artifact_revisions(
        "feature_existing_binding",
        "edit_authority_approval",
    ) == []


@pytest.mark.parametrize(
    ("request_schema", "projection_kind"),
    [
        (
            "stagger_hud_parent_diagnostic_execution_authority_request_v2",
            None,
        ),
        (
            "stagger_edit_authority_request_v1",
            "bounded_observation_only_plan_materialization",
        ),
    ],
)


def _write_historical_edit_authority_request(
    store: ArtifactStore,
    *,
    feature_id: str,
    payload: dict[str, object],
    upstream_refs: list[ArtifactRef] | None = None,
    exact_revision_upstream_types: set[str] | None = None,
) -> ArtifactRef:
    """Seed a frozen v0 Request without reopening the new-write contract."""

    original_validate_write = store.registry.validate_write
    original_validate_envelope = store.registry.validate_envelope

    def validate_historical_write(
        *,
        artifact_type: str,
        status: str,
        payload: dict[str, object],
    ) -> ArtifactContract:
        if artifact_type == "edit_authority_request":
            return store.registry.get(artifact_type)
        return original_validate_write(
            artifact_type=artifact_type,
            status=status,
            payload=payload,
        )

    def validate_historical_envelope(
        envelope: dict[str, object],
    ) -> ArtifactContract:
        if envelope.get("artifact_type") == "edit_authority_request":
            return store.registry.get("edit_authority_request")
        return original_validate_envelope(envelope)

    with patch.object(
        store.registry,
        "validate_write",
        side_effect=validate_historical_write,
    ), patch.object(
        store.registry,
        "validate_envelope",
        side_effect=validate_historical_envelope,
    ), patch.object(
        store,
        "_validate_edit_authority_request_identity_upstreams",
        return_value=None,
    ):
        return store.write(
            feature_id=feature_id,
            artifact_type="edit_authority_request",
            payload=payload,
            upstream_refs=upstream_refs,
            exact_revision_upstream_types=exact_revision_upstream_types,
        )


def _generic_versioned_request_payload(
    *,
    feature_id: str,
    run_id: str,
    source_root: Path,
    upstream_refs: dict[str, ArtifactRef],
) -> tuple[dict[str, object], str]:
    def revision(artifact_type: str) -> dict[str, str]:
        ref = upstream_refs[artifact_type]
        return {
            "feature_id": feature_id,
            "path": ref.path,
            "artifact_hash": ref.artifact_hash,
        }

    return attach_edit_authority_approval_identity(
        request_payload={
            "schema_version": "stagger_edit_authority_request_v1",
            "proposal": {
                "feature_spec_revision": revision("feature_spec"),
                "runtime_evidence_revision": revision("runtime_evidence"),
                "implementation_plan_revision": revision("implementation_plan"),
                "patch_proposal_revision": revision("patch_proposal"),
                "ownership_review": {
                    "stored_runtime_failure_ownership": {
                        "owner": "observation"
                    },
                    "replayed_runtime_failure_ownership": {
                        "owner": "product_behavior"
                    },
                    "reclassification_approval_required": True,
                    "runtime_evidence_mutation_allowed": False,
                },
                "diagnosed_responsibility_anchor": "runtime_result",
                "current_source": {
                    "canonical_target_path": (
                        "Patches/HitFeedbackBehaviorPatch.cs"
                    ),
                    "sha256": "5" * 64,
                    "target_span": {"start_line": 979, "end_line": 984},
                },
                "proposed_target_symbol": "TrySpawnStaggerYellowX",
                "proposed_exact_span": {
                    "start_line": 979,
                    "end_line": 984,
                },
                "proposed_operation": (
                    "replace_hud_recttransform_acquisition"
                ),
                "existing_binding_gap": "none",
                "current_edit_authority": "edit_binding_004",
                "approval_scope": ["create_exact_binding"],
                "root_cause_status": "confirmed",
                "unresolved_root_causes": [],
            },
            "source_root": str(source_root),
            "projected_ids": {
                "binding_id": "edit_binding_004",
                "change_id": "chg_004",
                "evidence_id": "stagger_repair_001",
            },
        },
        feature_id=feature_id,
        run_id=run_id,
    )
@pytest.mark.parametrize(
    ("request_schema", "projection_kind"),
    (
        (
            "stagger_hud_parent_diagnostic_execution_authority_request_v2",
            None,
        ),
        (
            "stagger_edit_authority_request_v1",
            "bounded_observation_only_plan_materialization",
        ),
    ),
)
def test_stagger_diagnostic_authority_graph_stops_at_diagnostic_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_schema: str,
    projection_kind: str | None,
) -> None:
    from langgraph.types import Command

    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get("edit_authority_request"),
        required_upstream_artifacts=frozenset(),
        required_exact_revision_upstream_artifacts=frozenset(),
    )
    registry = ArtifactTypeRegistry(
        contracts=[
            request_contract,
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    monkeypatch.setattr(
        store,
        "_validate_upstream_refs",
        lambda **_kwargs: None,
    )
    request_payload = {
        "schema_version": request_schema,
        "proposal": (
            {
                "schema_version": (
                    "stagger_hud_parent_diagnostic_execution_authority_v2"
                )
            }
            if request_schema
            == "stagger_hud_parent_diagnostic_execution_authority_request_v2"
            else {}
        ),
        "source_root": str(tmp_path),
    }
    if projection_kind is not None:
        request_payload["projection_kind"] = projection_kind
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_ref = _write_historical_edit_authority_request(
        store,
        feature_id="feature_observation_authority",
        payload={
            "node_name": (
                "request_stagger_hud_parent_observation_authority"
            ),
            "stage": "edit_authority_request",
            "message": "Awaiting graph approval.",
            "status": "pending_human_approval",
            "feature_id": "feature_observation_authority",
            "run_id": "run_observation_authority",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
    )
    declaration = resolve_edit_authority_capability(
        schema_version=request_schema,
        projection_kind=projection_kind,
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "_validate_graph_edit_authority_exact_inputs",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "validate_edit_authority_request_identity",
        lambda _request, allow_legacy: (
            declaration,
            "versioned_v1",
            request_hash,
        ),
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph.edit_authority_identity_sections",
        lambda _request, allow_legacy: {
            "identity_mode": "versioned_v1",
            "identity_schema_version": "edit_authority_approval_identity_v1",
            "request_hash": request_hash,
            "approval_identity": {"test_scope": "graph_terminal_projection"},
            "execution_contract_summary": {
                "allowed_actions": list(declaration.allowed_actions),
                "forbidden_actions": list(declaration.forbidden_actions),
            },
        },
    )
    if projection_kind == "bounded_observation_only_plan_materialization":
        original_read_for_stage = store.read_for_stage

        def read_for_stage_with_registered_request_upstreams(
            ref: ArtifactRef,
            *,
            consumer_stage: str,
        ) -> dict[str, Any]:
            envelope = original_read_for_stage(
                ref,
                consumer_stage=consumer_stage,
            )
            if ref.artifact_type != "edit_authority_request":
                return envelope
            expanded = copy.deepcopy(envelope)
            expanded["inputs"]["upstream_artifacts"] = [
                {
                    "feature_id": "feature_observation_authority",
                    "artifact_type": "implementation_plan",
                    "path": str(tmp_path / "historical_plan.json"),
                    "artifact_hash": "f" * 64,
                    "require_latest": False,
                }
            ]
            return expanded

        monkeypatch.setattr(
            store,
            "read_for_stage",
            read_for_stage_with_registered_request_upstreams,
        )

    materializer_output_types: list[str] = []

    def materialize(**_kwargs):
        materializer_output_types.extend(
            [
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
            ]
        )
        store_steps = _committed_edit_authority_steps(
            feature_id="feature_observation_authority",
            root=tmp_path,
            artifact_types=tuple(materializer_output_types),
        )
        return {
            "status": (
                "BOUNDED_OBSERVATION_PLAN_AUTHORIZED"
                if projection_kind
                == "bounded_observation_only_plan_materialization"
                else "STAGGER_HUD_PARENT_DIAGNOSTIC_PLAN_AUTHORIZED"
            ),
            "store_steps": store_steps,
            **{
                field_name: {
                    "feature_id": "feature_observation_authority",
                    "path": str(tmp_path / f"{artifact_type}.json"),
                    "artifact_hash": artifact_type.ljust(64, "0")[:64],
                }
                for artifact_type, field_name in (
                    (
                        "edit_authority_approval",
                        "edit_authority_approval_revision",
                    ),
                    ("evidence_pack", "evidence_pack_revision"),
                    (
                        "implementation_plan",
                        "implementation_plan_revision",
                    ),
                )
            },
        }

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "materialize_stagger_edit_authority_approval",
        materialize,
    )
    graph = build_graph(
        store,
        edit_authority_request_ref=request_ref,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
    )
    config = {
        "configurable": {
            "thread_id": "stagger_observation_authority_001"
        }
    }
    state = create_initial_state(
        run_id="run_observation_authority",
        request_id="feature_observation_authority",
        user_request="Approve exact observation-only Stagger bindings.",
    )
    state["feature_id"] = "feature_observation_authority"
    interrupted = graph.invoke(state, config)
    interrupt_value = interrupted["__interrupt__"][0].value
    assert interrupt_value["artifact_refs"] == [request_ref.path]
    assert interrupt_value["payload"]["allowed_actions"] == [
        "create_observation_evidence_pack_revision",
        "create_diagnostic_only_implementation_plan_revision",
        "create_exact_bounded_observation_bindings",
    ]
    assert interrupt_value["payload"]["forbidden_actions"] == [
        "create_binding_resolution_revision",
        "invoke_repair_planner",
        "modify_source",
        "build",
        "launch_process",
        "write_game_directory",
    ]
    result = graph.invoke(
        Command(
            resume={
                "resume_id": "resume_observation_authority_001",
                "run_id": "run_observation_authority",
                "stage": "edit_authority_approval",
                "decision": "approve",
                "approved_by": "user",
                "approved_at": "2026-07-30T16:30:00+08:00",
                "artifact_refs": interrupt_value["artifact_refs"],
                "authority_request_hash": request_hash,
            }
        ),
        config,
    )
    assert result["current_stage"] == "implementation_plan"
    assert result["approvals"]["edit_authority"] is True
    assert "implementation_plan" in result["artifacts"]
    assert "binding_resolution" not in result["artifacts"]
    assert "repair_plan" not in result["artifacts"]
    assert materializer_output_types == [
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
    ]
    assert len(
        store.list_feature_artifact_revisions(
            "feature_observation_authority",
            "edit_authority_request",
        )
    ) == 1
    assert len(
        store.list_feature_artifact_revisions(
            "feature_observation_authority",
            "workflow_checkpoint",
        )
    ) == 1
    assert len(
        store.list_feature_artifact_revisions(
            "feature_observation_authority",
            "resume_report",
        )
    ) == 1
    assert {
        "edit_authority_request",
        "workflow_checkpoint",
        "resume_report",
        *materializer_output_types,
    } == {
        "edit_authority_request",
        "workflow_checkpoint",
        "resume_report",
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
    }


@pytest.mark.parametrize(
    ("case_id", "schema_version", "projection_kind"),
    (
        (
            "wrong_schema_known_projection",
            "wrong_edit_authority_request_schema",
            "bounded_observation_only_plan_materialization",
        ),
        (
            "known_schema_unknown_projection",
            "stagger_edit_authority_request_v1",
            "unknown_projection_kind",
        ),
        (
            "known_schema_wrong_known_projection",
            "stagger_hud_parent_observation_authority_request_v1",
            "bounded_observation_only_plan_materialization",
        ),
    ),
)
def test_unsupported_discriminators_fail_at_all_three_layers_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    schema_version: str,
    projection_kind: str,
) -> None:
    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get("edit_authority_request"),
        required_upstream_artifacts=frozenset(),
        required_exact_revision_upstream_artifacts=frozenset(),
    )
    registry = ArtifactTypeRegistry(
        contracts=[
            request_contract,
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    monkeypatch.setattr(
        store,
        "_validate_upstream_refs",
        lambda **_kwargs: None,
    )
    request_payload = {
        "schema_version": schema_version,
        "projection_kind": projection_kind,
        "proposal": {},
        "source_root": str(tmp_path),
    }
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_artifact_payload = {
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Wrong schema must not gain bounded actions.",
            "status": "pending_human_approval",
            "feature_id": f"feature_{case_id}",
            "run_id": f"run_{case_id}",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
    }
    with pytest.raises(
        ArtifactStoreError,
        match="schema_version/projection_kind is not supported",
    ):
        store.write(
            feature_id=f"feature_{case_id}",
            artifact_type="edit_authority_request",
            payload=request_artifact_payload,
        )
    assert store.list_feature_artifact_revisions(
        f"feature_{case_id}",
        "edit_authority_request",
    ) == []
    request_ref = _write_historical_edit_authority_request(
        store,
        feature_id=f"feature_{case_id}",
        payload=request_artifact_payload,
    )
    graph = build_graph(
        store,
        edit_authority_request_ref=request_ref,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
    )
    state = create_initial_state(
        run_id=f"run_{case_id}",
        request_id=f"feature_{case_id}",
        user_request="Unsupported discriminator must fail closed.",
    )
    state["feature_id"] = f"feature_{case_id}"

    guarded_types = (
        "workflow_checkpoint",
        "resume_report",
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
        "binding_resolution",
    )
    before_counts = {
        artifact_type: len(
            store.list_feature_artifact_revisions(
                f"feature_{case_id}",
                artifact_type,
            )
        )
        for artifact_type in guarded_types
    }
    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )
    with pytest.raises(
        LocalEntryError,
        match="schema_version/projection_kind is not supported",
    ):
        preflight_stagger_edit_authority_review(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=f"feature_{case_id}",
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            authority_request_hash=request_hash,
        )
    with pytest.raises(
        ValueError,
        match="schema_version/projection_kind is not supported",
    ):
        graph.invoke(
            state,
            {"configurable": {"thread_id": case_id}},
        )
    with pytest.raises(
        (ArtifactStoreError, StaggerEditAuthorityApprovalError),
        match="schema_version/projection_kind is not supported",
    ):
        materialize_stagger_edit_authority_approval(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=f"feature_{case_id}",
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            resume_report_path=str(tmp_path / "missing-resume-report.json"),
            resume_report_hash="0" * 64,
        )
    assert {
        artifact_type: len(
            store.list_feature_artifact_revisions(
                f"feature_{case_id}",
                artifact_type,
            )
        )
        for artifact_type in guarded_types
    } == before_counts


@pytest.mark.parametrize("operation", ("preflight", "resume"))
def test_public_entry_cannot_bypass_declared_operation_applicability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get("edit_authority_request"),
        required_upstream_artifacts=frozenset(),
        required_exact_revision_upstream_artifacts=frozenset(),
    )
    registry = ArtifactTypeRegistry(
        contracts=[
            request_contract,
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    feature_id = f"feature_public_operation_{operation}"
    request_payload = {
        "schema_version": "stagger_edit_authority_request_v1",
        "proposal": {},
        "source_root": str(tmp_path),
    }
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_ref = _write_historical_edit_authority_request(
        store,
        feature_id=feature_id,
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Public operation applicability test.",
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": f"run_public_operation_{operation}",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
    )
    declaration = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    retained_operation = "resume" if operation == "preflight" else "preflight"
    restricted = replace(
        declaration,
        public_operations=frozenset({retained_operation}),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry.validate_edit_authority_request_identity",
        lambda _request, allow_legacy: (
            restricted,
            "versioned_v1",
            request_hash,
        ),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry.edit_authority_identity_sections",
        lambda _request, allow_legacy: {
            "identity_mode": "versioned_v1",
            "identity_schema_version": "edit_authority_approval_identity_v1",
            "request_hash": request_hash,
            "approval_identity": {"test_scope": "public_operation"},
            "execution_contract_summary": {
                "allowed_actions": list(restricted.allowed_actions),
                "forbidden_actions": list(restricted.forbidden_actions),
            },
        },
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry."
        "_validate_edit_authority_public_exact_inputs",
        lambda **_kwargs: None,
    )
    interrupt_called = False

    def reject_interrupt(**_kwargs):
        nonlocal interrupt_called
        interrupt_called = True
        raise AssertionError("Graph interrupt must not run.")

    monkeypatch.setattr(
        "src.mod_agent.local_entry._invoke_stagger_edit_authority_interrupt",
        reject_interrupt,
    )
    guarded_types = (
        "workflow_checkpoint",
        "resume_report",
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
        "binding_resolution",
    )
    before_counts = {
        artifact_type: len(
            store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in guarded_types
    }

    with pytest.raises(
        LocalEntryError,
        match="does not support the requested public operation",
    ):
        if operation == "preflight":
            preflight_stagger_edit_authority_review(
                artifact_store_root=tmp_path / "artifacts",
                feature_id=feature_id,
                edit_authority_request_path=request_ref.path,
                edit_authority_request_hash=request_ref.artifact_hash,
                authority_request_hash=request_hash,
            )
        else:
            resume_stagger_edit_authority_review(
                artifact_store_root=tmp_path / "artifacts",
                feature_id=feature_id,
                edit_authority_request_path=request_ref.path,
                edit_authority_request_hash=request_ref.artifact_hash,
                authority_request_hash=request_hash,
                resume_id=f"resume_public_operation_{operation}",
                decision="approve",
                approved_by="user",
                approved_at="2026-08-03T12:00:00+08:00",
            )
    assert interrupt_called is False
    assert {
        artifact_type: len(
            store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in guarded_types
    } == before_counts


@pytest.mark.parametrize(
    ("case_id", "request_schema", "proposal_schema"),
    (
        (
            "hud_v1_request_with_v2_proposal",
            "stagger_hud_parent_observation_authority_request_v1",
            "stagger_hud_parent_diagnostic_execution_authority_v2",
        ),
        (
            "hud_v2_request_with_v1_proposal",
            "stagger_hud_parent_diagnostic_execution_authority_request_v2",
            "stagger_hud_parent_observation_authority_v1",
        ),
    ),
)
def test_hud_request_proposal_schema_mismatch_fails_at_all_layers_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    request_schema: str,
    proposal_schema: str,
) -> None:
    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get("edit_authority_request"),
        required_upstream_artifacts=frozenset(),
        required_exact_revision_upstream_artifacts=frozenset(),
    )
    registry = ArtifactTypeRegistry(
        contracts=[
            request_contract,
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    monkeypatch.setattr(
        store,
        "_validate_upstream_refs",
        lambda **_kwargs: None,
    )
    feature_id = f"feature_{case_id}"
    request_payload = {
        "schema_version": request_schema,
        "proposal": {"schema_version": proposal_schema},
        "source_root": str(tmp_path),
    }
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_artifact_payload = {
            "node_name": "request_stagger_hud_authority",
            "stage": "edit_authority_request",
            "message": "HUD Request and proposal schemas must match.",
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": f"run_{case_id}",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
    }
    with pytest.raises(
        ArtifactStoreError,
        match="does not match its technical proposal schema",
    ):
        store.write(
            feature_id=feature_id,
            artifact_type="edit_authority_request",
            payload=request_artifact_payload,
        )
    assert store.list_feature_artifact_revisions(
        feature_id,
        "edit_authority_request",
    ) == []
    request_ref = _write_historical_edit_authority_request(
        store,
        feature_id=feature_id,
        payload=request_artifact_payload,
    )
    graph = build_graph(
        store,
        edit_authority_request_ref=request_ref,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
    )
    state = create_initial_state(
        run_id=f"run_{case_id}",
        request_id=feature_id,
        user_request="HUD Request/Proposal mismatch must fail closed.",
    )
    state["feature_id"] = feature_id
    guarded_types = (
        "workflow_checkpoint",
        "resume_report",
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
        "binding_resolution",
    )
    before_counts = {
        artifact_type: len(
            store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in guarded_types
    }
    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )

    with pytest.raises(
        LocalEntryError,
        match="does not match its technical proposal schema",
    ):
        preflight_stagger_edit_authority_review(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=feature_id,
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            authority_request_hash=request_hash,
        )
    with pytest.raises(
        ValueError,
        match="does not match its technical proposal schema",
    ):
        graph.invoke(
            state,
            {"configurable": {"thread_id": case_id}},
        )
    with pytest.raises(
        (ArtifactStoreError, StaggerEditAuthorityApprovalError),
        match="does not match its technical proposal schema",
    ):
        materialize_stagger_edit_authority_approval(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=feature_id,
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            resume_report_path=str(tmp_path / "missing-resume-report.json"),
            resume_report_hash="0" * 64,
        )
    assert {
        artifact_type: len(
            store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in guarded_types
    } == before_counts


def test_legacy_existing_binding_request_is_read_only_at_public_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature_id = "feature_existing_binding_exact"
    run_id = "run_existing_binding_exact"
    statuses = frozenset({"success"})
    simple_contracts = [
        ArtifactContract(
            artifact_type=artifact_type,
            schema_version="1.0",
            required_fields=frozenset(
                {"node_name", "stage", "message"}
            ),
            producer_stage=artifact_type,
            consumer_stages=frozenset(
                {"edit_authority_request"}
            ),
            allowed_statuses=statuses,
        )
        for artifact_type in (
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        )
    ]
    default_registry = ArtifactTypeRegistry()
    registry = ArtifactTypeRegistry(
        contracts=[
            *simple_contracts,
            default_registry.get("edit_authority_request"),
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)

    def write_simple(
        artifact_type: str,
        label: str,
        *,
        upstream_refs: list[ArtifactRef] | None = None,
    ) -> ArtifactRef:
        payload = {
            "node_name": label,
            "stage": artifact_type,
            "message": label,
        }
        if artifact_type == "implementation_plan":
            payload["blocking"] = True
        return store.write(
            feature_id=feature_id,
            artifact_type=artifact_type,
            payload=payload,
            upstream_refs=upstream_refs,
        )

    feature_ref = write_simple("feature_spec", "feature")
    predecessor_plan_ref = write_simple(
        "implementation_plan",
        "predecessor-plan",
    )
    runtime_ref = write_simple(
        "runtime_evidence",
        "runtime",
        upstream_refs=[predecessor_plan_ref],
    )
    proposal_ref = write_simple(
        "patch_proposal",
        "proposal",
        upstream_refs=[predecessor_plan_ref],
    )
    current_plan_ref = write_simple(
        "implementation_plan",
        "current-plan",
    )
    assert store.check_freshness(runtime_ref).is_fresh is False
    assert store.check_freshness(proposal_ref).is_fresh is False

    request_payload = {
        "schema_version": (
            "stagger_existing_binding_reauthorization_request_v1"
        ),
        "proposal": {},
        "source_root": str(tmp_path),
    }
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_ref = _write_historical_edit_authority_request(
        store,
        feature_id=feature_id,
        payload={
            "node_name": (
                "request_stagger_existing_binding_reauthorization"
            ),
            "stage": "edit_authority_request",
            "message": "Awaiting graph approval.",
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": run_id,
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        upstream_refs=[
            feature_ref,
            runtime_ref,
            predecessor_plan_ref,
            proposal_ref,
            current_plan_ref,
        ],
        exact_revision_upstream_types={
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        },
    )
    assert store.check_freshness(request_ref).is_fresh is True
    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )

    before_counts = {
        artifact_type: len(
            store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in (
            "workflow_checkpoint",
            "resume_report",
            "edit_authority_approval",
            "binding_resolution",
        )
    }
    with pytest.raises(
        LocalEntryError,
        match="require approval_identity",
    ):
        preflight_stagger_edit_authority_review(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=feature_id,
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            authority_request_hash=request_hash,
        )
    assert {
        artifact_type: len(
            store.list_feature_artifact_revisions(feature_id, artifact_type)
        )
        for artifact_type in before_counts
    } == before_counts

def test_legacy_generic_request_cannot_enter_public_or_graph_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get("edit_authority_request"),
        required_upstream_artifacts=frozenset(),
        required_exact_revision_upstream_artifacts=frozenset(),
    )
    feature_contract = ArtifactContract(
        artifact_type="feature_spec",
        schema_version="1.0",
        required_fields=frozenset({"node_name", "stage", "message"}),
        producer_stage="feature_spec",
        consumer_stages=frozenset({"edit_authority_request"}),
        allowed_statuses=frozenset({"success"}),
    )
    registry = ArtifactTypeRegistry(
        contracts=[
            feature_contract,
            request_contract,
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    feature_ref = store.write(
        feature_id="feature_original_request",
        artifact_type="feature_spec",
        payload={
            "node_name": "feature",
            "stage": "feature_spec",
            "message": "feature",
        },
    )
    request_payload = {
        "schema_version": "stagger_edit_authority_request_v1",
        "proposal": {},
        "source_root": str(tmp_path),
        "projected_ids": {
            "binding_id": "edit_binding_004",
            "change_id": "chg_004",
            "evidence_id": "stagger_repair_001",
        },
    }
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_ref = _write_historical_edit_authority_request(
        store,
        feature_id="feature_original_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Awaiting graph approval.",
            "status": "pending_human_approval",
            "feature_id": "feature_original_request",
            "run_id": "run_original_request",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        upstream_refs=[feature_ref],
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )
    with pytest.raises(
        LocalEntryError,
        match="require approval_identity",
    ):
        preflight_stagger_edit_authority_review(
            artifact_store_root=tmp_path / "artifacts",
            feature_id="feature_original_request",
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            authority_request_hash=request_hash,
        )
    graph = build_graph(
        store,
        edit_authority_request_ref=request_ref,
        checkpointer=(
            WorkflowCheckpointStore.langgraph_memory_checkpointer()
        ),
    )
    state = create_initial_state(
        run_id="run_original_request",
        request_id="feature_original_request",
        user_request="Review the original authority request.",
    )
    state["feature_id"] = "feature_original_request"

    with pytest.raises(ValueError, match="require approval_identity"):
        graph.invoke(
            state,
            {
                "configurable": {
                    "thread_id": "original_authority_request_001"
                }
            },
        )
    assert store.list_feature_artifact_revisions(
        "feature_original_request",
        "workflow_checkpoint",
    ) == []
    assert store.list_feature_artifact_revisions(
        "feature_original_request",
        "resume_report",
    ) == []


def test_historical_v1_request_cannot_enter_current_public_graph_or_materializer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_registry = ArtifactTypeRegistry()
    simple_contracts = [
        ArtifactContract(
            artifact_type=artifact_type,
            schema_version="1.0",
            required_fields=frozenset({"node_name", "stage", "message"}),
            producer_stage=artifact_type,
            consumer_stages=frozenset({"edit_authority_request"}),
            allowed_statuses=frozenset({"success"}),
        )
        for artifact_type in (
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        )
    ]
    registry = ArtifactTypeRegistry(
        contracts=[
            *simple_contracts,
            default_registry.get("edit_authority_request"),
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    feature_id = "feature_historical_v1_execution"
    run_id = "run_historical_v1_execution"
    upstream_refs: dict[str, ArtifactRef] = {}
    for artifact_type in (
        "feature_spec",
        "runtime_evidence",
        "implementation_plan",
        "patch_proposal",
    ):
        payload: dict[str, object] = {
            "node_name": artifact_type,
            "stage": artifact_type,
            "message": artifact_type,
        }
        if artifact_type == "implementation_plan":
            payload["blocking"] = True
        if artifact_type == "patch_proposal":
            payload["diff_intent"] = []
        upstream_refs[artifact_type] = store.write(
            feature_id=feature_id,
            artifact_type=artifact_type,
            payload=payload,
        )
    request_payload, request_hash = _generic_versioned_request_payload(
        feature_id=feature_id,
        run_id=run_id,
        source_root=tmp_path,
        upstream_refs=upstream_refs,
    )
    request_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Historical v1 Request.",
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": run_id,
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        upstream_refs=list(upstream_refs.values()),
        exact_revision_upstream_types=set(upstream_refs),
    )
    old_record = capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID[
        "stagger_edit_authority_generic"
    ]
    v2_declaration = replace(
        old_record.declaration,
        capability_contract_version="stagger_edit_authority_capability_v2",
    )
    v2_record = replace(
        old_record,
        declaration=v2_declaration,
        action_projection_id="stagger_edit_authority_action_scope_v2",
        action_scope_builder=lambda _payload, _declaration: {
            "identity_contract_revision": "v2"
        },
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
    monkeypatch.setitem(
        capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR,
        (v2_declaration.schema_version, v2_declaration.projection_kind),
        v2_record,
    )
    monkeypatch.setitem(
        capabilities_module._CURRENT_CAPABILITY_RECORDS_BY_ID,
        v2_declaration.capability_id,
        v2_record,
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )
    before_counts = {
        artifact_type: len(
            store.list_feature_artifact_revisions(feature_id, artifact_type)
        )
        for artifact_type in (
            "workflow_checkpoint",
            "resume_report",
            "edit_authority_approval",
            "evidence_pack",
            "implementation_plan",
            "binding_resolution",
        )
    }

    with pytest.raises(LocalEntryError, match="does not match the approved action"):
        preflight_stagger_edit_authority_review(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=feature_id,
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            authority_request_hash=request_hash,
        )

    graph = build_graph(
        store,
        edit_authority_request_ref=request_ref,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
    )
    state = create_initial_state(
        run_id=run_id,
        request_id=feature_id,
        user_request="Reject historical v1 current execution.",
    )
    state["feature_id"] = feature_id
    with pytest.raises(ValueError, match="does not match the approved action"):
        graph.invoke(
            state,
            {"configurable": {"thread_id": "historical_v1_execution"}},
        )

    monkeypatch.setattr(
        "src.mod_agent.runtime.stagger_edit_authority.ArtifactStore",
        lambda _root: store,
    )
    with pytest.raises(
        StaggerEditAuthorityApprovalError,
        match="does not match the approved action",
    ):
        materialize_stagger_edit_authority_approval(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=feature_id,
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            resume_report_path=tmp_path / "not-read.json",
            resume_report_hash="0" * 64,
        )

    assert {
        artifact_type: len(
            store.list_feature_artifact_revisions(feature_id, artifact_type)
        )
        for artifact_type in before_counts
    } == before_counts

    v2_request_payload, v2_request_hash = _generic_versioned_request_payload(
        feature_id=feature_id,
        run_id="run_current_v2_execution",
        source_root=tmp_path,
        upstream_refs=upstream_refs,
    )
    v2_request_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Current v2 Request.",
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": "run_current_v2_execution",
            "request_hash": v2_request_hash,
            "request_payload": v2_request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        upstream_refs=list(upstream_refs.values()),
        exact_revision_upstream_types=set(upstream_refs),
    )
    current_preflight = preflight_stagger_edit_authority_review(
        artifact_store_root=tmp_path / "artifacts",
        feature_id=feature_id,
        edit_authority_request_path=v2_request_ref.path,
        edit_authority_request_hash=v2_request_ref.artifact_hash,
        authority_request_hash=v2_request_hash,
    )
    assert current_preflight["status"] == (
        "READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION"
    )
    assert current_preflight["execution_contract_summary"][
        "capability_contract_version"
    ] == "stagger_edit_authority_capability_v2"


def test_edit_authority_resume_blocks_wrong_request_hash() -> None:
    checkpoint = {
        "run_id": "run_edit_authority",
        "checkpoint_stage": "edit_authority_approval",
        "artifact_refs": ["request.json"],
        "state_snapshot": {},
        "resume_binding": {
            "edit_authority_request_hash": "sha256:" + ("a" * 64),
        },
    }
    payload = ResumePayload(
        resume_id="resume_edit_authority_wrong_hash",
        run_id="run_edit_authority",
        stage="edit_authority_approval",
        decision="approve",
        approved_by="user",
        approved_at="2026-07-30T12:00:00+08:00",
        artifact_refs=("request.json",),
        authority_request_hash="sha256:" + ("b" * 64),
    )

    decision = ResumeValidator().validate(payload, checkpoint=checkpoint)

    assert decision.allowed is False
    assert any(
        blocker["code"] == "EDIT_AUTHORITY_REQUEST_HASH_MISMATCH"
        for blocker in decision.blockers
    )


def test_stagger_edit_authority_local_entry_carries_decision_through_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_registry = ArtifactTypeRegistry()
    simple_contracts = [
        ArtifactContract(
            artifact_type=artifact_type,
            schema_version="1.0",
            required_fields=frozenset({"node_name", "stage", "message"}),
            producer_stage=artifact_type,
            consumer_stages=frozenset({"edit_authority_request"}),
            allowed_statuses=frozenset({"success"}),
        )
        for artifact_type in (
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        )
    ]
    registry = ArtifactTypeRegistry(
        contracts=[
            *simple_contracts,
            default_registry.get("edit_authority_request"),
            default_registry.get("workflow_checkpoint"),
            default_registry.get("resume_report"),
            default_registry.get("workflow_trace"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    feature_id = "feature_edit_authority_entry"
    run_id = "run_edit_authority_entry"
    upstream_refs: dict[str, ArtifactRef] = {}
    for artifact_type in (
        "feature_spec",
        "runtime_evidence",
        "implementation_plan",
        "patch_proposal",
    ):
        payload: dict[str, object] = {
            "node_name": artifact_type,
            "stage": artifact_type,
            "message": artifact_type,
        }
        if artifact_type == "implementation_plan":
            payload["blocking"] = True
        if artifact_type == "patch_proposal":
            payload["diff_intent"] = []
        upstream_refs[artifact_type] = store.write(
            feature_id=feature_id,
            artifact_type=artifact_type,
            payload=payload,
        )
    request_payload, request_hash = _generic_versioned_request_payload(
        feature_id=feature_id,
        run_id=run_id,
        source_root=tmp_path,
        upstream_refs=upstream_refs,
    )
    request_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Awaiting graph approval.",
            "status": "pending_human_approval",
            "feature_id": feature_id,
            "run_id": run_id,
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        upstream_refs=list(upstream_refs.values()),
        exact_revision_upstream_types=set(upstream_refs),
    )

    def materialize(**_kwargs):
        store_steps = _committed_edit_authority_steps(
            feature_id="feature_edit_authority_entry",
            root=tmp_path,
            artifact_types=(
                "edit_authority_approval",
                "evidence_pack",
                "implementation_plan",
                "binding_resolution",
            ),
        )
        revisions = {
            field_name: {
                "feature_id": "feature_edit_authority_entry",
                "path": str(tmp_path / f"{artifact_type}.json"),
                "artifact_hash": artifact_type.ljust(64, "0")[:64],
            }
            for artifact_type, field_name in (
                (
                    "edit_authority_approval",
                    "edit_authority_approval_revision",
                ),
                ("evidence_pack", "evidence_pack_revision"),
                (
                    "implementation_plan",
                    "implementation_plan_revision",
                ),
                ("binding_resolution", "binding_resolution_revision"),
            )
        }
        return {
            "status": "EXACT_EDIT_AUTHORITY_RESOLVED",
            "store_steps": store_steps,
            **revisions,
        }

    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "materialize_stagger_edit_authority_approval",
        materialize,
    )
    preflight = preflight_stagger_edit_authority_review(
        artifact_store_root=tmp_path / "artifacts",
        feature_id=feature_id,
        edit_authority_request_path=request_ref.path,
        edit_authority_request_hash=request_ref.artifact_hash,
        authority_request_hash=request_hash,
    )
    assert preflight["approval_identity_mode"] == "versioned_v1"
    assert preflight["approval_identity"] == request_payload["approval_identity"]
    assert preflight["execution_contract_summary"]["capability_id"] == (
        "stagger_edit_authority_generic"
    )
    assert preflight["audit_snapshot"]["writes_performed"] is False

    result = resume_stagger_edit_authority_review(
        artifact_store_root=tmp_path / "artifacts",
        feature_id=feature_id,
        edit_authority_request_path=request_ref.path,
        edit_authority_request_hash=request_ref.artifact_hash,
        authority_request_hash=request_hash,
        resume_id="resume_edit_authority_entry_001",
        decision="approve",
        approved_by="user",
        approved_at="2026-07-30T12:00:00+08:00",
    )

    assert result["status"] == "EXACT_EDIT_AUTHORITY_RESOLVED"
    assert result["current_stage"] == "binding_resolution"
    assert "resume_report" in result["artifacts"]
    assert "binding_resolution" in result["artifacts"]
    assert "repair_plan" not in result["artifacts"]
    assert result["repair_planner_invoked"] is False
    assert result["audit_snapshot"]["writes_performed"] is True
    assert result["audit_snapshot"]["artifact_writes_performed"] is True
    assert result["audit_snapshot"]["artifact_revision_counts_before"] != (
        result["audit_snapshot"]["artifact_revision_counts_after"]
    )


def test_edit_authority_presentation_failure_preserves_completed_machine_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    feature_id = "feature_edit_authority_presentation"
    request_hash = "sha256:" + ("a" * 64)
    machine_result = project_edit_authority_review_result(
        capability=capability,
        feature_id=feature_id,
        approval_identity_hash=request_hash,
        store_steps=_committed_edit_authority_steps(
            feature_id=feature_id,
            root=tmp_path,
            artifact_types=capability.review_write_artifact_types,
        ),
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
    )

    class AuditFailingStore:
        calls = 0

        def list_feature_artifact_revisions(
            self,
            _feature_id: str,
            _artifact_type: str,
        ) -> list[ArtifactRef]:
            self.calls += 1
            if self.calls > len(capability.review_write_artifact_types):
                raise OSError("audit snapshot unavailable")
            return []

    store = AuditFailingStore()
    admission = local_entry_module._EditAuthorityReviewAdmission(
        store=store,
        request_ref=ArtifactRef(
            feature_id=feature_id,
            artifact_type="edit_authority_request",
            path=str(tmp_path / "request.json"),
            artifact_hash="b" * 64,
        ),
        request={},
        request_envelope={},
        run_id="run_edit_authority_presentation",
        capability=capability,
        identity_sections={},
    )

    class CompletedGraph:
        def invoke(self, *_args, **_kwargs):
            return {
                "edit_authority_review_result": machine_result.to_dict(),
                "artifacts": {},
                "artifact_hashes": {},
                "blockers": [],
                "current_stage": "binding_resolution",
            }

    monkeypatch.setattr(
        local_entry_module,
        "_admit_stagger_edit_authority_review",
        lambda **_kwargs: admission,
    )
    monkeypatch.setattr(
        local_entry_module,
        "_invoke_stagger_edit_authority_interrupt",
        lambda **_kwargs: (CompletedGraph(), ["request.json"], {}, {}),
    )

    with pytest.raises(EditAuthorityPresentationError) as caught:
        resume_stagger_edit_authority_review(
            artifact_store_root=tmp_path / "artifacts",
            feature_id=feature_id,
            edit_authority_request_path=tmp_path / "request.json",
            edit_authority_request_hash="b" * 64,
            authority_request_hash=request_hash,
            resume_id="resume_edit_authority_presentation",
            decision="approve",
            approved_by="user",
            approved_at="2026-08-06T13:00:00+08:00",
        )

    assert isinstance(
        caught.value.edit_authority_review_result,
        EditAuthorityReviewResultV1,
    )
    assert caught.value.edit_authority_review_result == machine_result
    assert caught.value.presentation_error == {
        "error_class": "OSError",
        "error_message": "audit snapshot unavailable",
    }
    assert machine_result.platform_status == "completed"


def test_explicit_domain_policy_rejects_simultaneous_registry(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match=(
            "domain_review_policy and domain_adapter_registry cannot both "
            "be supplied"
        ),
    ):
        build_graph(
            ArtifactStore(tmp_path / "artifacts"),
            domain_review_policy=build_gtfo_profile(tmp_path).review_policy(),
            domain_adapter_registry=DomainAdapterRegistry(),
        )


def test_build_handoff_requires_graph_to_stop_before_runtime(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="stop_after_build=True"):
        build_graph(
            ArtifactStore(tmp_path / "artifacts"),
            persist_build_runtime_handoff=True,
        )


def test_proposal_critic_cannot_be_implicitly_triggered(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="critic_requirement='required'"):
        build_graph(
            ArtifactStore(tmp_path / "artifacts"),
            proposal_critic=RuleBasedProposalCritic(),
        )


def test_proposal_critic_requirement_rejects_unknown_value(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be exactly"):
        build_graph(
            ArtifactStore(tmp_path / "artifacts"),
            critic_requirement="automatic",  # type: ignore[arg-type]
        )


def test_proposal_source_snippet_char_limit_must_be_positive(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="proposal_source_snippet_char_limit must be a positive integer",
    ):
        build_graph(
            ArtifactStore(tmp_path / "artifacts"),
            proposal_source_snippet_char_limit=0,
        )


def _knowledge_with_load_symbol(
    tmp_path: Path,
    *,
    root_name: str = "source",
) -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / root_name
    root.mkdir()
    (root / "Plugin.cs").write_text(
        """
public class Plugin
{
    public void Load()
    {
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )
    IncrementalIndexer(database=db, source_registry=registry).index_source("target_mod")
    return db


@pytest.fixture(autouse=True)
def _default_proposal_git_repository(monkeypatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    class FakeGitRepository:
        def __init__(
            self,
            root: str | Path,
            git_executable: str | tuple[str, ...] | None = None,
        ) -> None:
            self.git_command = ("git",)
            calls.append(
                {
                    "root": Path(root),
                    "git_executable": git_executable,
                }
            )

        def working_tree_snapshot(self) -> SimpleNamespace:
            return SimpleNamespace(
                base_revision="b" * 40,
                branch="codex/default-binding",
                is_dirty=False,
                diff_hash="sha256:defaultgit",
                dirty_tree_policy={
                    "status": "clean",
                    "blocks_proposal_binding": False,
                    "blockers": [],
                },
            )

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph.GitRepository",
        FakeGitRepository,
    )
    return calls


def _plugin_marker_binding(criteria: tuple[str, ...]) -> dict[str, object]:
    return {
        "marker_source": "runtime_probe",
        "markers": [
            {
                "acceptance_criterion": criterion,
                "marker": f"MARKER_{index}",
                "observed": True,
            }
            for index, criterion in enumerate(criteria, start=1)
        ],
    }


def _knowledge_with_dense_chunk(tmp_path: Path) -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    collection_id = "knowledge_hub"
    index_version = "v1"
    document_id = "knowledge_hub_doc_001"
    chunk_id = "knowledge_hub_chunk_001"
    db.upsert_source(
        SourceRecord(
            source_id="target_mod",
            source_type="target_source",
            root_path=collection_id,
        )
    )
    db.start_index_version(
        collection_id=collection_id,
        index_version=index_version,
        source_count=1,
        chunk_count=1,
    )
    db.upsert_chunk(
        Chunk(
            chunk_id=chunk_id,
            document_id=document_id,
            text="Dense-only runtime hook evidence lives in this chunk.",
            text_for_retrieval="Dense-only runtime hook evidence lives in this chunk.",
            metadata={
                "chunk_id": chunk_id,
                "document_id": document_id,
                "source_ref": document_id,
                "content_hash": "knowledge_hub_chunk_hash",
                "file_hash": "knowledge_hub_file_hash",
                "source_hash": "knowledge_hub_file_hash",
                "doc_hash": "knowledge_hub_doc_hash",
                "source_id": "target_mod",
                "source_type": "target_source",
                "source_path": "knowledge_hub/runtime.json",
            },
        ),
        collection_id=collection_id,
        index_version=index_version,
    )
    BM25Indexer(db).index(collection_id=collection_id, index_version=index_version)
    db.set_index_version_status(
        collection_id=collection_id,
        index_version=index_version,
        status="stable",
    )
    return db


def _real_build_result_factory(tmp_path: Path):
    build_root = tmp_path / "build"
    expected_artifact = build_root / "bin" / "Debug" / "BetterHitFeedback.dll"

    def build_result_factory(feature_id: str, input_execution_mode: str | None):
        def runner(_: BuildProfile) -> BuildCommandResult:
            expected_artifact.parent.mkdir(parents=True, exist_ok=True)
            expected_artifact.write_bytes(b"verified runtime build")
            return BuildCommandResult(exit_code=0, stdout="Build succeeded", duration_ms=8)

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="test_dotnet",
                build_system="dotnet",
                working_directory=str(build_root),
                command=("dotnet", "build"),
                timeout_seconds=120,
                expected_artifacts=("bin/Debug/BetterHitFeedback.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    return build_result_factory


def _revision_count(tmp_path: Path, feature_id: str, artifact_type: str) -> int:
    revision_dir = (
        tmp_path
        / "artifacts"
        / "features"
        / feature_id
        / "r"
        / artifact_type
    )
    return len(list(revision_dir.glob("*.json"))) if revision_dir.exists() else 0


def _build_runtime_resume_payload(
    *,
    checkpoint: dict[str, object],
    resume_id: str,
) -> ResumePayload:
    return ResumePayload(
        resume_id=resume_id,
        run_id=str(checkpoint["run_id"]),
        request_id=str(checkpoint["request_id"]),
        feature_id=str(checkpoint["feature_id"]),
        stage="build",
        decision="approve",
        approved_by="human",
        approved_at="2026-07-25T00:00:00Z",
        artifact_refs=tuple(checkpoint["artifact_refs"]),  # type: ignore[arg-type]
        runtime_admission={
            "status": "admitted",
            "authorization_scope": "this_resume_only",
            "requested_side_effects": ["runtime_execution"],
            "authorized_side_effects": ["runtime_execution"],
            "provider": "injected_test",
        },
    )


def _successful_build_handoff(
    tmp_path: Path,
    *,
    artifact_directory: str = "artifacts",
) -> tuple[ArtifactStore, dict[str, object], object]:
    store = ArtifactStore(tmp_path / artifact_directory)
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=_real_build_result_factory(tmp_path),
        stop_after_build=True,
        persist_build_runtime_handoff=True,
    )
    state = create_initial_state(
        run_id="run_build_runtime_handoff_001",
        request_id="req_build_runtime_handoff_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )
    result = graph.invoke(state)
    checkpoint_ref = ArtifactRef(
        feature_id=str(result["feature_id"]),
        artifact_type="workflow_checkpoint",
        path=result["artifacts"]["workflow_checkpoint"],
        artifact_hash=result["artifact_hashes"]["workflow_checkpoint"],
    )
    return store, result, checkpoint_ref


def _state_artifact_ref(
    result: dict[str, object],
    artifact_type: str,
) -> ArtifactRef:
    return ArtifactRef(
        feature_id=str(result["feature_id"]),
        artifact_type=artifact_type,
        path=str(result["artifacts"][artifact_type]),  # type: ignore[index]
        artifact_hash=str(result["artifact_hashes"][artifact_type]),  # type: ignore[index]
    )


def _runtime_workflow_graph_operation(
    store: ArtifactStore,
    *,
    checkpoint_ref: ArtifactRef,
    resume_report_ref: ArtifactRef,
):
    checkpoint = store.read(checkpoint_ref)["data"]
    report = store.read(resume_report_ref)["data"]
    runtime_admission = report["applied_updates"]["runtime_admission"]
    return project_verification_operation(
        VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=NewRuntimeResumeProtocolBindingV1(
                checkpoint_ref=checkpoint_ref,
                resume_id=str(report["resume_id"]),
                approved_by=str(report["approved_by"]),
            ),
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope=RUNTIME_WORKFLOW_COMPLETION,
                runtime_action_scope=runtime_admission,
            ),
        ),
        checkpoint_identity=VerificationCheckpointIdentityV1(
            checkpoint_id=str(checkpoint["checkpoint_id"]),
            run_id=str(checkpoint["run_id"]),
            request_id=str(checkpoint["request_id"]),
        ),
    )


def _fake_runtime_factory(
    feature_id: str,
    build: dict[str, object],
    feature_spec: dict[str, object],
) -> dict[str, object]:
    return build_fake_runtime_evidence_payload(
        feature_id=feature_id,
        input_execution_mode=str(build.get("execution_mode")),
        acceptance_criteria=tuple(feature_spec.get("acceptance_criteria") or ()),
        runtime_verification_plan=tuple(
            feature_spec.get("runtime_verification_plan") or ()
        ),
    )


def _clone_as_latest_revision(
    store: ArtifactStore,
    ref: ArtifactRef,
    *,
    message_suffix: str,
    replace_upstream: dict[str, ArtifactRef] | None = None,
    payload_updates: dict[str, object] | None = None,
    transitive_exact_types: set[str] | None = None,
) -> ArtifactRef:
    envelope = store.read(ref)
    payload = copy.deepcopy(envelope["data"])
    payload["message"] = f"{payload.get('message', '')} {message_suffix}".strip()
    payload.update(payload_updates or {})
    replacement = replace_upstream or {}
    upstream_refs: list[ArtifactRef] = []
    exact_types: set[str] = set()
    for item in envelope["inputs"]["upstream_artifacts"]:
        upstream = replacement.get(
            item["artifact_type"],
            ArtifactRef(
                feature_id=ref.feature_id,
                artifact_type=item["artifact_type"],
                path=item["path"],
                artifact_hash=item["artifact_hash"],
            ),
        )
        upstream_refs.append(upstream)
        if item.get("require_latest") is False:
            exact_types.add(upstream.artifact_type)
    exact_types.update(transitive_exact_types or set())
    return store.write(
        feature_id=ref.feature_id,
        artifact_type=ref.artifact_type,
        payload=payload,
        status=envelope["status"],
        blockers=list(envelope.get("blockers", [])),
        trace_refs=list(envelope.get("trace_refs", [])),
        upstream_refs=upstream_refs,
        exact_revision_upstream_types=exact_types,
    )


def _feature_spec_revision_graph_fixture(tmp_path: Path) -> dict[str, object]:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_id = "feature_revision_gate"
    request_ref = store.write(
        feature_id=feature_id,
        artifact_type="request_planning_report",
        payload={
            "node_name": "plan_request",
            "stage": "request_planning",
            "message": "Request classified.",
            "feature_id": feature_id,
            "user_request": "Revise the Stagger M1 FeatureSpec.",
            "route": "game_hook_investigation",
            "risk_level": "high",
            "requires_hook_evidence": True,
            "requires_runtime_evidence": True,
            "uncertainties": [],
            "blocked": False,
        },
    )
    predecessor_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload={
            "node_name": "draft_feature_spec",
            "stage": "feature_spec",
            "message": "Original FeatureSpec.",
            "feature_id": feature_id,
            "user_request": "Original request.",
            "target_behavior": "Original behavior.",
            "non_goals": [],
            "target_mod": "BetterHitFeedback",
            "risk_level": "high",
            "acceptance_criteria": ["Original criterion."],
            "evidence_requirements": ["Original evidence."],
            "runtime_verification_plan": ["Original runtime plan."],
            "hook_requirement": {"required": True, "reason": "Original Hook."},
            "blocked": False,
            "blockers": [],
        },
        upstream_refs=[request_ref],
    )
    payload = {
        "acceptance_criteria": [
            "C1",
            "C2",
            "C3",
            "C4",
            "C5",
            "C6",
            "C7",
            "C8",
        ],
        "admission_boundary": {
            "next_stage": None,
            "source_write_authorized": False,
        },
        "automation_claim": "not_proven",
        "blocked": False,
        "blockers": [],
        "evidence_requirements": [
            "Bind the direct ES_Hitreact.ActivateState Hook.",
            "C4 requires deterministic implementation evidence.",
            "C6 and C7 require explicit negative inputs.",
        ],
        "feature_id": feature_id,
        "hook_requirement": {
            "required": True,
            "reason": "Use the direct ES_Hitreact.ActivateState result Hook.",
        },
        "message": "FeatureSpec revision; downstream execution is not authorized.",
        "node_name": "draft_feature_spec",
        "non_goals": [
            "Cross-invocation physical-hit duplicate suppression is deferred."
        ],
        "operator_guided_technical_hypotheses": {
            "authority": "advisory_pending_current_evidence",
            "essential_rejection_action": "block_before_implementation_plan",
            "essential_unresolved_action": "block_and_return_for_operator_review",
            "evidence_may_reject": True,
            "hypotheses": [
                {
                    "essential": True,
                    "id": "direct_activate_state_hook",
                    "statement": "ActivateState is the direct Hook.",
                    "invalidation_condition": "The Hook inputs are unavailable.",
                }
            ],
        },
        "revision_reason": "Use per-invocation M1 semantics.",
        "risk_level": "high",
        "runtime_verification_plan": [
            "Re-review five historical facts.",
            "Evaluate C4, C6, and C7 independently.",
        ],
        "source_lineage": {
            "root": "reviewed-source",
            "read_only": True,
            "files": {"Plugin.cs": "a" * 64},
        },
        "specification_mode": "operator_guided",
        "stage": "feature_spec",
        "success_marker_contract": {
            "signal": "STAGGER_FEEDBACK_SHOWN",
        },
        "supersedes_artifact_hash": predecessor_ref.artifact_hash,
        "target_behavior": "One output group per qualifying ActivateState invocation.",
        "target_mod": "BetterHitFeedback",
        "user_request": "Original request remains preserved.",
    }
    projection = {
        "schema_version": "1.0",
        "artifact_type": "feature_spec",
        "feature_id": feature_id,
        "producer_stage": "feature_spec",
        "status": "success",
        "payload": payload,
        "inputs": {
            "upstream_artifacts": [
                {
                    "artifact_type": "request_planning_report",
                    "path": request_ref.path,
                    "artifact_hash": request_ref.artifact_hash,
                    "require_latest": True,
                }
            ]
        },
        "blockers": [],
        "trace_refs": ["feature-spec-revision-test"],
    }
    state = create_initial_state(
        run_id="run_feature_spec_revision",
        request_id="request_feature_spec_revision",
        user_request="Revise the Stagger M1 FeatureSpec.",
        target_mod="BetterHitFeedback",
    )
    state["feature_id"] = feature_id
    state["artifacts"] = {"request_planning_report": request_ref.path}
    state["artifact_hashes"] = {
        "request_planning_report": request_ref.artifact_hash
    }
    state["approvals"] = {"feature_spec_revision": True}
    return {
        "store": store,
        "feature_id": feature_id,
        "request_ref": request_ref,
        "predecessor_ref": predecessor_ref,
        "projection": projection,
        "state": state,
    }


def _canonical_projection_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _invoke_feature_spec_revision_graph(
    fixture: dict[str, object],
    *,
    projection: dict[str, object] | None = None,
    approved_payload_hash: str | None = None,
    approved_projection_hash: str | None = None,
    thread_id: str = "feature_spec_revision_gate",
) -> dict[str, object]:
    effective_projection = projection or copy.deepcopy(fixture["projection"])
    payload = effective_projection["payload"]
    assert isinstance(payload, dict)
    graph = build_graph(
        fixture["store"],
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
        interrupt_after=["draft_feature_spec"],
        feature_spec_revision_projection=effective_projection,
        approved_feature_spec_revision_payload_hash=(
            approved_payload_hash or _canonical_projection_hash(payload)
        ),
        approved_feature_spec_revision_projection_hash=(
            approved_projection_hash
            or _canonical_projection_hash(effective_projection)
        ),
    )
    config = {"configurable": {"thread_id": thread_id}}
    seeded = graph.update_state(
        config,
        copy.deepcopy(fixture["state"]),
        as_node="planning_brief",
    )
    result = graph.invoke(None, seeded)
    assert isinstance(result, dict)
    result["_next"] = graph.get_state(config).next
    return result


def test_feature_spec_revision_gate_materializes_once_and_stops(
    tmp_path: Path,
) -> None:
    fixture = _feature_spec_revision_graph_fixture(tmp_path)
    store = fixture["store"]
    assert isinstance(store, ArtifactStore)
    feature_id = fixture["feature_id"]
    assert isinstance(feature_id, str)
    predecessor_ref = fixture["predecessor_ref"]
    assert isinstance(predecessor_ref, ArtifactRef)
    predecessor_bytes = Path(predecessor_ref.path).read_bytes()
    before_count = len(
        store.list_feature_artifact_revisions(feature_id, "feature_spec")
    )

    result = _invoke_feature_spec_revision_graph(fixture)

    assert result["current_stage"] == "feature_spec"
    assert result["next_stage"] is None
    assert result["_next"] == ("retrieve_evidence",)
    assert "evidence_pack" not in result["artifacts"]
    assert "implementation_plan" not in result["artifacts"]
    assert len(store.list_feature_artifact_revisions(feature_id, "feature_spec")) == (
        before_count + 1
    )
    assert Path(predecessor_ref.path).read_bytes() == predecessor_bytes
    latest_ref = next(
        ref
        for ref in store.list_feature_artifacts(feature_id)
        if ref.artifact_type == "feature_spec"
    )
    assert latest_ref.artifact_hash == result["artifact_hashes"]["feature_spec"]
    assert latest_ref.artifact_hash != predecessor_ref.artifact_hash

    replay_count = len(
        store.list_feature_artifact_revisions(feature_id, "feature_spec")
    )
    with pytest.raises(ValueError, match="predecessor is not the current latest"):
        _invoke_feature_spec_revision_graph(
            fixture,
            thread_id="feature_spec_revision_gate_replay",
        )
    assert len(store.list_feature_artifact_revisions(feature_id, "feature_spec")) == (
        replay_count
    )


def test_feature_spec_revision_gate_rejects_payload_hash_drift_without_write(
    tmp_path: Path,
) -> None:
    fixture = _feature_spec_revision_graph_fixture(tmp_path)
    projection = copy.deepcopy(fixture["projection"])
    original_payload = copy.deepcopy(projection["payload"])
    projection["payload"]["message"] = "Drifted message."
    store = fixture["store"]
    assert isinstance(store, ArtifactStore)
    feature_id = fixture["feature_id"]
    assert isinstance(feature_id, str)
    before_count = len(
        store.list_feature_artifact_revisions(feature_id, "feature_spec")
    )

    with pytest.raises(ValueError, match="payload hash is not approved"):
        _invoke_feature_spec_revision_graph(
            fixture,
            projection=projection,
            approved_payload_hash=_canonical_projection_hash(original_payload),
            approved_projection_hash=_canonical_projection_hash(projection),
        )

    assert len(store.list_feature_artifact_revisions(feature_id, "feature_spec")) == (
        before_count
    )


def test_feature_spec_revision_gate_rejects_non_latest_predecessor_without_write(
    tmp_path: Path,
) -> None:
    fixture = _feature_spec_revision_graph_fixture(tmp_path)
    projection = copy.deepcopy(fixture["projection"])
    projection["payload"]["supersedes_artifact_hash"] = "f" * 64
    store = fixture["store"]
    assert isinstance(store, ArtifactStore)
    feature_id = fixture["feature_id"]
    assert isinstance(feature_id, str)
    before_count = len(
        store.list_feature_artifact_revisions(feature_id, "feature_spec")
    )

    with pytest.raises(ValueError, match="predecessor is not the current latest"):
        _invoke_feature_spec_revision_graph(fixture, projection=projection)

    assert len(store.list_feature_artifact_revisions(feature_id, "feature_spec")) == (
        before_count
    )


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("feature", "identity metadata drifted"),
        ("upstream", "RequestPlan upstream drifted"),
        ("schema", "identity metadata drifted"),
        ("producer", "identity metadata drifted"),
    ],
)
def test_feature_spec_revision_gate_rejects_identity_drift_without_write(
    tmp_path: Path,
    drift: str,
    message: str,
) -> None:
    fixture = _feature_spec_revision_graph_fixture(tmp_path)
    projection = copy.deepcopy(fixture["projection"])
    if drift == "feature":
        projection["feature_id"] = "feature_drifted"
    elif drift == "upstream":
        projection["inputs"]["upstream_artifacts"][0]["artifact_type"] = (
            "feature_spec"
        )
    elif drift == "schema":
        projection["schema_version"] = "2.0"
    else:
        projection["producer_stage"] = "evidence_retrieval"
    store = fixture["store"]
    assert isinstance(store, ArtifactStore)
    feature_id = fixture["feature_id"]
    assert isinstance(feature_id, str)
    before_count = len(
        store.list_feature_artifact_revisions(feature_id, "feature_spec")
    )

    with pytest.raises(ValueError, match=message):
        _invoke_feature_spec_revision_graph(fixture, projection=projection)

    assert len(store.list_feature_artifact_revisions(feature_id, "feature_spec")) == (
        before_count
    )


@pytest.mark.parametrize("field_drift", ["extra", "missing"])
def test_feature_spec_revision_gate_rejects_payload_field_drift_without_write(
    tmp_path: Path,
    field_drift: str,
) -> None:
    fixture = _feature_spec_revision_graph_fixture(tmp_path)
    projection = copy.deepcopy(fixture["projection"])
    if field_drift == "extra":
        projection["payload"]["unexpected_field"] = True
    else:
        projection["payload"].pop("automation_claim")
    store = fixture["store"]
    assert isinstance(store, ArtifactStore)
    feature_id = fixture["feature_id"]
    assert isinstance(feature_id, str)
    before_count = len(
        store.list_feature_artifact_revisions(feature_id, "feature_spec")
    )

    with pytest.raises(ValueError, match="payload fields do not match"):
        _invoke_feature_spec_revision_graph(fixture, projection=projection)

    assert len(store.list_feature_artifact_revisions(feature_id, "feature_spec")) == (
        before_count
    )


def test_feature_spec_revision_gate_rejects_deferred_correlation_reentry(
    tmp_path: Path,
) -> None:
    fixture = _feature_spec_revision_graph_fixture(tmp_path)
    projection = copy.deepcopy(fixture["projection"])
    projection["payload"]["operator_guided_technical_hypotheses"]["hypotheses"][
        0
    ]["id"] = "exactly_once_correlation"
    store = fixture["store"]
    assert isinstance(store, ArtifactStore)
    feature_id = fixture["feature_id"]
    assert isinstance(feature_id, str)
    before_count = len(
        store.list_feature_artifact_revisions(feature_id, "feature_spec")
    )

    with pytest.raises(ValueError, match="deferred correlation hypotheses"):
        _invoke_feature_spec_revision_graph(fixture, projection=projection)

    assert len(store.list_feature_artifact_revisions(feature_id, "feature_spec")) == (
        before_count
    )
def _build_handoff_with_diagnostic_latest(
    tmp_path: Path,
) -> tuple[
    ArtifactStore,
    dict[str, object],
    ArtifactRef,
    ArtifactRef,
    ArtifactRef,
    ArtifactRef,
]:
    store, result, old_checkpoint_ref = _successful_build_handoff(tmp_path)
    state = copy.deepcopy(result)
    state["artifacts"].pop("workflow_checkpoint")  # type: ignore[union-attr]
    state["artifact_hashes"].pop("workflow_checkpoint")  # type: ignore[union-attr]
    product_evidence = _state_artifact_ref(state, "evidence_pack")
    product_plan = _state_artifact_ref(state, "implementation_plan")
    diagnostic_evidence = _clone_as_latest_revision(
        store,
        product_evidence,
        message_suffix="diagnostic track latest",
    )
    diagnostic_plan = _clone_as_latest_revision(
        store,
        product_plan,
        message_suffix="diagnostic track latest",
        replace_upstream={"evidence_pack": diagnostic_evidence},
    )
    return (
        store,
        state,
        old_checkpoint_ref,
        product_evidence,
        product_plan,
        diagnostic_evidence,
        diagnostic_plan,
    )


def _build_handoff_with_applied_diff(
    tmp_path: Path,
    *,
    dry_run_diff_hash: str,
    apply_diff_hash: str,
) -> tuple[ArtifactStore, dict[str, object]]:
    store, state, _, _, _, _, _ = _build_handoff_with_diagnostic_latest(tmp_path)
    dry_run_ref = _clone_as_latest_revision(
        store,
        _state_artifact_ref(state, "dry_run_result"),
        message_suffix="exact diff execution",
        payload_updates={"diff_hash": dry_run_diff_hash},
        transitive_exact_types={"evidence_pack", "implementation_plan"},
    )
    state["artifacts"]["dry_run_result"] = dry_run_ref.path  # type: ignore[index]
    state["artifact_hashes"]["dry_run_result"] = (  # type: ignore[index]
        dry_run_ref.artifact_hash
    )
    apply_ref = store.write(
        feature_id=str(state["feature_id"]),
        artifact_type="isolated_apply_result",
        payload={
            "node_name": "isolated_apply",
            "stage": "isolated_apply",
            "message": "Approved patch was applied inside the isolated workspace.",
            "execution_mode": "isolated_apply",
            "actual_write_performed": True,
            "real_patch_applied": True,
            "approved_by_review": True,
            "approved_by_user": True,
            "write_scope_preapproved": True,
            "exact_diff_approved": True,
            "changed_files": ["Patches/HitFeedbackBehaviorPatch.cs"],
            "diff_hash": apply_diff_hash,
            "approved_diff_hash": apply_diff_hash,
        },
        upstream_refs=[
            _state_artifact_ref(state, "patch_proposal"),
            _state_artifact_ref(state, "proposal_review"),
            dry_run_ref,
        ],
        exact_revision_upstream_types={
            "evidence_pack",
            "implementation_plan",
        },
    )
    state["artifacts"]["isolated_apply_result"] = apply_ref.path  # type: ignore[index]
    state["artifact_hashes"]["isolated_apply_result"] = (  # type: ignore[index]
        apply_ref.artifact_hash
    )
    build_envelope = store.read(_state_artifact_ref(state, "build_result"))
    build_ref = store.write(
        feature_id=str(state["feature_id"]),
        artifact_type="build_result",
        payload=build_envelope["data"],
        status=build_envelope["status"],
        upstream_refs=[
            _state_artifact_ref(state, "dry_run_result"),
            _state_artifact_ref(state, "isolated_apply_result"),
        ],
    )
    state["artifacts"]["build_result"] = build_ref.path  # type: ignore[index]
    state["artifact_hashes"]["build_result"] = build_ref.artifact_hash  # type: ignore[index]
    state["current_stage"] = "build"
    state["next_stage"] = "runtime_evidence"
    return store, state


def test_build_checkpoint_default_still_blocks_old_product_revisions(
    tmp_path: Path,
) -> None:
    store, state, _, _, _, _, _ = _build_handoff_with_diagnostic_latest(tmp_path)

    with pytest.raises(StaleArtifactError, match="evidence_pack hash changed"):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="default latest checkpoint",
            resume_allowed_fields=(),
        )


def test_build_checkpoint_preserves_approved_product_exact_lineage(
    tmp_path: Path,
) -> None:
    (
        store,
        state,
        old_checkpoint_ref,
        product_evidence,
        product_plan,
        diagnostic_evidence,
        diagnostic_plan,
    ) = _build_handoff_with_diagnostic_latest(tmp_path)
    old_checkpoint_bytes = Path(old_checkpoint_ref.path).read_bytes()
    build_ref = _state_artifact_ref(state, "build_result")
    build = store.read(build_ref)["data"]
    dll_path = Path(build["verified_artifacts"][0]["resolved_path"])
    dll_bytes = dll_path.read_bytes()

    checkpoint_ref = WorkflowCheckpointStore(store).create_checkpoint(
        state,  # type: ignore[arg-type]
        interrupt_reason="approved product exact-lineage handoff",
        resume_allowed_fields=(),
        exact_revision_upstream_types=frozenset(
            {"evidence_pack", "implementation_plan"}
        ),
    )
    envelope = store.read(checkpoint_ref)
    checkpoint = envelope["data"]
    upstreams = {
        item["artifact_type"]: item
        for item in envelope["inputs"]["upstream_artifacts"]
    }
    decision = WorkflowCheckpointStore(store).preflight_resume(
        checkpoint_ref,
        resume_id="preflight_exact_product_lineage",
    )

    assert checkpoint["state_snapshot"]["artifacts"]["evidence_pack"] == (
        product_evidence.path
    )
    assert checkpoint["state_snapshot"]["artifacts"]["implementation_plan"] == (
        product_plan.path
    )
    assert checkpoint["state_snapshot"]["artifacts"]["evidence_pack"] != (
        diagnostic_evidence.path
    )
    assert checkpoint["state_snapshot"]["artifacts"]["implementation_plan"] != (
        diagnostic_plan.path
    )
    assert upstreams["evidence_pack"]["require_latest"] is False
    assert upstreams["implementation_plan"]["require_latest"] is False
    assert checkpoint["resume_binding"]["build_result_hash"] == build_ref.artifact_hash
    assert decision.allowed is True
    assert decision.status == "ready"
    assert Path(old_checkpoint_ref.path).read_bytes() == old_checkpoint_bytes
    assert dll_path.read_bytes() == dll_bytes


def test_build_checkpoint_resume_rejects_execution_diff_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, state, _, _, _, _, _ = _build_handoff_with_diagnostic_latest(tmp_path)
    checkpoint_store = WorkflowCheckpointStore(store)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        state,  # type: ignore[arg-type]
        interrupt_reason="approved product exact-lineage handoff",
        resume_allowed_fields=(),
        exact_revision_upstream_types=frozenset(
            {"evidence_pack", "implementation_plan"}
        ),
    )
    monkeypatch.setattr(
        checkpoint_store,
        "_persisted_execution_diff_hash",
        lambda _state: "sha256:" + "0" * 64,
    )

    decision = checkpoint_store.preflight_resume(
        checkpoint_ref,
        resume_id="preflight_mismatched_execution_diff_identity",
    )

    assert decision.allowed is False
    assert decision.status == "blocked"
    assert any(
        blocker["code"] == "CHECKPOINT_EXACT_DIFF_BINDING_MISMATCH"
        for blocker in decision.blockers
    )


def test_build_checkpoint_writes_persisted_apply_diff_to_resume_binding(
    tmp_path: Path,
) -> None:
    diff_hash = "sha256:" + "1" * 64
    store, state = _build_handoff_with_applied_diff(
        tmp_path,
        dry_run_diff_hash=diff_hash,
        apply_diff_hash=diff_hash,
    )

    checkpoint_ref = WorkflowCheckpointStore(store).create_checkpoint(
        state,  # type: ignore[arg-type]
        interrupt_reason="persisted exact Apply diff",
        resume_allowed_fields=(),
        exact_revision_upstream_types=frozenset(
            {"evidence_pack", "implementation_plan"}
        ),
    )

    checkpoint = store.read(checkpoint_ref)["data"]
    assert checkpoint["resume_binding"]["diff_hash"] == diff_hash


def test_build_checkpoint_blocks_dry_run_apply_diff_mismatch_before_write(
    tmp_path: Path,
) -> None:
    store, state = _build_handoff_with_applied_diff(
        tmp_path,
        dry_run_diff_hash="sha256:" + "1" * 64,
        apply_diff_hash="sha256:" + "2" * 64,
    )
    before_count = len(
        store.list_feature_artifact_revisions(
            str(state["feature_id"]),
            "workflow_checkpoint",
        )
    )

    with pytest.raises(
        ArtifactStoreError,
        match="DryRun/Apply exact diff identity is missing or inconsistent",
    ):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="mismatched exact Apply diff",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset(
                {"evidence_pack", "implementation_plan"}
            ),
        )

    assert len(
        store.list_feature_artifact_revisions(
            str(state["feature_id"]),
            "workflow_checkpoint",
        )
    ) == before_count


def test_build_checkpoint_blocks_two_nearest_revisions_of_one_exact_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        store,
        state,
        _,
        _,
        _,
        diagnostic_evidence,
        _,
    ) = _build_handoff_with_diagnostic_latest(tmp_path)
    checkpoint_store = WorkflowCheckpointStore(store)
    original_ancestry = checkpoint_store._build_upstream_ancestry

    def forked_ancestry(build_ref: ArtifactRef):
        ancestry, blockers = original_ancestry(build_ref)
        evidence_depths = ancestry["evidence_pack"]
        nearest_depth = min(evidence_depths.values())
        evidence_depths[
            (diagnostic_evidence.path, diagnostic_evidence.artifact_hash)
        ] = nearest_depth
        return ancestry, blockers

    monkeypatch.setattr(
        checkpoint_store,
        "_build_upstream_ancestry",
        forked_ancestry,
    )
    before_count = len(
        store.list_feature_artifact_revisions(
            str(state["feature_id"]),
            "workflow_checkpoint",
        )
    )

    with pytest.raises(ArtifactStoreError, match="unique nearest evidence_pack"):
        checkpoint_store.create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="ambiguous nearest EvidencePack",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset(
                {"evidence_pack", "implementation_plan"}
            ),
        )

    assert len(
        store.list_feature_artifact_revisions(
            str(state["feature_id"]),
            "workflow_checkpoint",
        )
    ) == before_count


def test_build_checkpoint_rejects_unsupported_exact_revision_role(
    tmp_path: Path,
) -> None:
    store, state, _, _, _, _, _ = _build_handoff_with_diagnostic_latest(tmp_path)

    with pytest.raises(
        ArtifactStoreError,
        match="unsupported.*binding_resolution",
    ):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="unsupported exact role",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset({"binding_resolution"}),
        )


@pytest.mark.parametrize("artifact_type", ["evidence_pack", "implementation_plan"])
def test_build_checkpoint_rejects_wrong_exact_role_hash(
    tmp_path: Path,
    artifact_type: str,
) -> None:
    store, state, _, _, _, _, _ = _build_handoff_with_diagnostic_latest(tmp_path)
    state["artifact_hashes"][artifact_type] = "0" * 64  # type: ignore[index]

    with pytest.raises(ArtifactStoreError, match="not the unique nearest"):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="wrong exact role hash",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset(
                {"evidence_pack", "implementation_plan"}
            ),
        )


def test_build_checkpoint_rejects_exact_role_path_hash_mismatch(
    tmp_path: Path,
) -> None:
    (
        store,
        state,
        _,
        product_evidence,
        _,
        diagnostic_evidence,
        _,
    ) = _build_handoff_with_diagnostic_latest(tmp_path)
    state["artifacts"]["evidence_pack"] = diagnostic_evidence.path  # type: ignore[index]
    state["artifact_hashes"]["evidence_pack"] = product_evidence.artifact_hash  # type: ignore[index]

    with pytest.raises(ArtifactStoreError, match="not the unique nearest"):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="path hash mismatch",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset(
                {"evidence_pack", "implementation_plan"}
            ),
        )


def test_build_checkpoint_rejects_incomplete_exact_role_set(
    tmp_path: Path,
) -> None:
    store, state, _, _, _, _, _ = _build_handoff_with_diagnostic_latest(tmp_path)

    with pytest.raises(
        ArtifactStoreError,
        match="exact revision roles are incomplete.*implementation_plan",
    ):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="incomplete exact role set",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset({"evidence_pack"}),
        )


@pytest.mark.parametrize(
    ("persisted_exact_roles", "expected_blocker"),
    [
        (
            {"feature_spec"},
            "BUILD_CHECKPOINT_EXACT_ROLE_UNSUPPORTED",
        ),
        (
            {"evidence_pack"},
            "BUILD_CHECKPOINT_EXACT_ROLE_SET_INCOMPLETE",
        ),
    ],
)
def test_build_checkpoint_preflight_rejects_invalid_persisted_exact_roles(
    tmp_path: Path,
    persisted_exact_roles: set[str],
    expected_blocker: str,
) -> None:
    store, result, checkpoint_ref = _successful_build_handoff(tmp_path)
    envelope = store.read(checkpoint_ref)
    state = envelope["data"]["state_snapshot"]
    upstream_refs = [
        ArtifactRef(
            feature_id=str(result["feature_id"]),
            artifact_type=artifact_type,
            path=str(path),
            artifact_hash=str(state["artifact_hashes"][artifact_type]),
        )
        for artifact_type, path in state["artifacts"].items()
    ]
    invalid_ref = store.write(
        feature_id=str(result["feature_id"]),
        artifact_type="workflow_checkpoint",
        payload=envelope["data"],
        status=envelope["status"],
        blockers=list(envelope.get("blockers", [])),
        trace_refs=list(envelope.get("trace_refs", [])),
        upstream_refs=upstream_refs,
        exact_revision_upstream_types=persisted_exact_roles,
    )

    decision = WorkflowCheckpointStore(store).preflight_resume(
        invalid_ref,
        resume_id="preflight_invalid_persisted_exact_roles",
    )

    assert decision.allowed is False
    assert decision.status == "blocked"
    assert any(
        blocker["code"] == expected_blocker
        for blocker in decision.blockers
    )


def test_build_checkpoint_rejects_diagnostic_latest_as_product_exact_role(
    tmp_path: Path,
) -> None:
    (
        store,
        state,
        _,
        _,
        _,
        diagnostic_evidence,
        _,
    ) = _build_handoff_with_diagnostic_latest(tmp_path)
    state["artifacts"]["evidence_pack"] = diagnostic_evidence.path  # type: ignore[index]
    state["artifact_hashes"]["evidence_pack"] = (  # type: ignore[index]
        diagnostic_evidence.artifact_hash
    )

    with pytest.raises(
        ArtifactStoreError,
        match="not the unique nearest evidence_pack ancestor",
    ):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="diagnostic latest must not replace product lineage",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset(
                {"evidence_pack", "implementation_plan"}
            ),
        )


def test_build_checkpoint_rejects_changed_new_build_dll_before_write(
    tmp_path: Path,
) -> None:
    store, state, _, _, _, _, _ = _build_handoff_with_diagnostic_latest(tmp_path)
    build = store.read(_state_artifact_ref(state, "build_result"))["data"]
    Path(build["verified_artifacts"][0]["resolved_path"]).write_bytes(b"changed")
    before_count = len(
        store.list_feature_artifact_revisions(
            str(state["feature_id"]),
            "workflow_checkpoint",
        )
    )

    with pytest.raises(ArtifactStoreError, match="Verified Build output changed"):
        WorkflowCheckpointStore(store).create_checkpoint(
            state,  # type: ignore[arg-type]
            interrupt_reason="changed Build DLL",
            resume_allowed_fields=(),
            exact_revision_upstream_types=frozenset(
                {"evidence_pack", "implementation_plan"}
            ),
        )

    assert len(
        store.list_feature_artifact_revisions(
            str(state["feature_id"]),
            "workflow_checkpoint",
        )
    ) == before_count


def test_fresh_process_continues_build_handoff_without_repeating_upstream_stages(
    tmp_path: Path,
) -> None:
    first_store, build_result, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = first_store.read(checkpoint_ref)["data"]
    before_counts = {
        artifact_type: _revision_count(
            tmp_path,
            str(build_result["feature_id"]),
            artifact_type,
        )
        for artifact_type in (
            "evidence_pack",
            "patch_proposal",
            "proposal_review",
            "dry_run_result",
            "build_result",
        )
    }

    fresh_store = ArtifactStore(tmp_path / "artifacts")
    fresh_checkpoint_store = WorkflowCheckpointStore(fresh_store)
    decision, resume_report_ref = fresh_checkpoint_store.resume(
        checkpoint_ref,
        _build_runtime_resume_payload(
            checkpoint=checkpoint,
            resume_id="resume_build_runtime_handoff_001",
        ),
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_report_ref,
    )

    fresh_graph = build_graph(
        fresh_store,
        runtime_evidence_factory=_fake_runtime_factory,
        verification_operation=_runtime_workflow_graph_operation(
            fresh_store,
            checkpoint_ref=checkpoint_ref,
            resume_report_ref=resume_report_ref,
        ),
    )
    result = fresh_graph.invoke(resumed_state)

    assert decision.allowed is True
    assert resumed_state["approvals"] == {}
    assert result["current_stage"] == "done"
    assert result["run_id"] == build_result["run_id"]
    runtime = _artifact_data(fresh_store, result, "runtime_evidence")
    assert runtime["run_id"] == build_result["run_id"]
    assert runtime["build_artifact_hash"] == build_result["artifact_hashes"][
        "build_result"
    ]
    assert "eval_report" in result["artifacts"]
    assert "workflow_summary" in result["artifacts"]
    assert {
        artifact_type: _revision_count(
            tmp_path,
            str(build_result["feature_id"]),
            artifact_type,
        )
        for artifact_type in before_counts
    } == before_counts


def test_supported_local_entry_resumes_build_handoff_without_model_or_gtfo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    (tmp_path / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": checkpoint["run_id"],
                "request_id": checkpoint["request_id"],
            }
        ),
        encoding="utf-8",
    )

    def runtime_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        return build_fake_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build.get("execution_mode")),
            acceptance_criteria=tuple(feature_spec.get("acceptance_criteria") or ()),
            runtime_verification_plan=tuple(
                feature_spec.get("runtime_verification_plan") or ()
            ),
        )

    executor_calls = []
    original_executor = local_entry_module._execute_runtime_workflow_operation

    def recording_executor(**kwargs):
        executor_calls.append(dict(kwargs))
        return original_executor(**kwargs)

    monkeypatch.setattr(
        local_entry_module,
        "_execute_runtime_workflow_operation",
        recording_executor,
    )

    summary = resume_local_runtime(
        run_root=tmp_path,
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        settings_path=tmp_path / "unused-settings.yaml",
        approved_by="human",
        allow_game_launch=False,
        runtime_plugin_destination=None,
        allow_game_directory_write=False,
        resume_id="resume_supported_entry_001",
        runtime_evidence_factory=runtime_factory,
        injected_runtime_admission={
            "status": "admitted",
            "authorization_scope": "this_resume_only",
            "requested_side_effects": ["runtime_execution"],
            "authorized_side_effects": ["runtime_execution"],
            "provider": "injected_test",
        },
    )

    assert summary["current_stage"] == "done"
    assert summary["run_id"] == checkpoint["run_id"]
    assert summary["model_call_count"] == 0
    assert summary["upstream_stages_repeated"] is False
    assert (tmp_path / "runtime_resume_result.json").is_file()
    assert len(executor_calls) == 1
    assert executor_calls[0]["operation"].operation_kind == RUNTIME_EXECUTION_KIND
    assert executor_calls[0]["operation"].variant_payload.completion_scope == (
        RUNTIME_WORKFLOW_COMPLETION
    )
    assert set(executor_calls[0]).isdisjoint(
        {
            "attempt_policy",
            "attempt_kind",
            "runtime_evidence_only",
            "runtime_terminalization_only",
            "runtime_evidence_consolidation_only",
        }
    )


def test_runtime_workflow_executor_has_one_typed_operation_authority() -> None:
    executor = local_entry_module._execute_runtime_workflow_operation
    parameters = inspect.signature(executor).parameters
    source = inspect.getsource(executor)

    assert parameters["operation"].default is inspect.Parameter.empty
    assert "attempt_policy" not in parameters
    assert "attempt_kind" not in source
    assert '"_verification_operation"' not in source
    assert "runtime_evidence_only" not in source
    assert "runtime_terminalization_only" not in source
    assert "runtime_evidence_consolidation_only" not in source


def test_local_entry_result_adapters_delegate_disposition_to_declaration() -> None:
    for helper in (
        local_entry_module._build_verification_machine_result,
        local_entry_module._runtime_execution_machine_result,
        local_entry_module._terminalization_machine_result,
        local_entry_module._consolidation_machine_result,
    ):
        source = inspect.getsource(helper)
        assert "project_verification_operation_result(" in source
        assert "execution_disposition" not in source


def test_legacy_runtime_presentation_failure_preserves_machine_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    (tmp_path / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": checkpoint["run_id"],
                "request_id": checkpoint["request_id"],
            }
        ),
        encoding="utf-8",
    )

    def runtime_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        return build_fake_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build.get("execution_mode")),
            acceptance_criteria=tuple(feature_spec.get("acceptance_criteria") or ()),
            runtime_verification_plan=tuple(
                feature_spec.get("runtime_verification_plan") or ()
            ),
        )

    projected = []
    original_projector = local_entry_module.project_verification_operation_result

    def recording_projector(**kwargs):
        result = original_projector(**kwargs)
        projected.append(result)
        return result

    original_write_text = Path.write_text

    def fail_presentation(path: Path, *args, **kwargs):
        if path.name == "runtime_resume_result.json":
            raise OSError("presentation unavailable")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(
        local_entry_module,
        "project_verification_operation_result",
        recording_projector,
    )
    monkeypatch.setattr(Path, "write_text", fail_presentation)

    with pytest.raises(VerificationOperationPresentationError) as caught:
        resume_local_runtime(
            run_root=tmp_path,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
            settings_path=tmp_path / "unused-settings.yaml",
            approved_by="human",
            allow_game_launch=False,
            runtime_plugin_destination=None,
            allow_game_directory_write=False,
            resume_id="resume_presentation_failure_001",
            runtime_evidence_factory=runtime_factory,
            injected_runtime_admission={
                "status": "admitted",
                "authorization_scope": "this_resume_only",
                "requested_side_effects": ["runtime_execution"],
                "authorized_side_effects": ["runtime_execution"],
                "provider": "injected_test",
            },
        )

    assert len(projected) == 1
    assert caught.value.verification_operation_result is projected[0]
    assert caught.value.audit_error["stage"] == "presentation"
    assert caught.value.audit_error["sink"] == "runtime_resume_result.json"
    assert not (tmp_path / "runtime_resume_result.json").exists()


def test_legacy_runtime_execution_failure_preserves_projected_machine_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    (tmp_path / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": checkpoint["run_id"],
                "request_id": checkpoint["request_id"],
            }
        ),
        encoding="utf-8",
    )

    def failed_runtime_factory(*_args, **_kwargs):
        raise OSError("runtime effect unavailable")

    projected = []
    original_projector = local_entry_module.project_verification_operation_result

    def recording_projector(**kwargs):
        result = original_projector(**kwargs)
        projected.append(result)
        return result

    monkeypatch.setattr(
        local_entry_module,
        "project_verification_operation_result",
        recording_projector,
    )

    with pytest.raises(VerificationOperationExecutionError) as caught:
        resume_local_runtime(
            run_root=tmp_path,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
            settings_path=tmp_path / "unused-settings.yaml",
            approved_by="human",
            allow_game_launch=False,
            runtime_plugin_destination=None,
            allow_game_directory_write=False,
            resume_id="resume_failed_runtime_001",
            runtime_evidence_factory=failed_runtime_factory,
            injected_runtime_admission={
                "status": "admitted",
                "authorization_scope": "this_resume_only",
                "requested_side_effects": ["runtime_execution"],
                "authorized_side_effects": ["runtime_execution"],
                "provider": "injected_test",
            },
        )

    assert len(projected) == 1
    machine_result = caught.value.verification_operation_result
    assert machine_result is projected[0]
    assert machine_result.platform_status == "blocked"
    assert machine_result.failure_stage == "runtime_execution"
    assert machine_result.execution_disposition == "platform_blocked"
    output_by_role = {item.role: item.artifact_ref for item in machine_result.outputs}
    receipt_by_role = {
        item.role: item.artifact_write_result for item in machine_result.store_receipts
    }
    assert receipt_by_role["resume_report"].outcome == "committed"
    assert output_by_role["resume_report"] == receipt_by_role["resume_report"].artifact_ref
    assert not (tmp_path / "runtime_resume_result.json").exists()


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [("blocked_before_commit", "blocked"), ("partial", "partial")],
)
def test_initial_runtime_resume_store_noncommitted_stops_before_graph_and_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected_status: str,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    (tmp_path / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": checkpoint["run_id"],
                "request_id": checkpoint["request_id"],
            }
        ),
        encoding="utf-8",
    )
    partial = outcome == "partial"
    feature_root = store.root / "features" / str(build_result["feature_id"])
    write_result = ArtifactWriteResult(
        outcome=outcome,  # type: ignore[arg-type]
        feature_id=str(build_result["feature_id"]),
        artifact_type="resume_report",
        artifact_hash="9" * 64,
        artifact_ref=None,
        revision_path=str(
            feature_root / "r" / "resume_report" / ("9" * 32 + ".json")
        ),
        latest_alias_path=str(feature_root / "resume_report.json"),
        pending_marker_path=str(
            feature_root / "p" / "resume_report" / ("9" * 32 + ".json")
        ),
        commit_started=partial,
        revision_state="valid" if partial else "absent",
        latest_alias_state="absent",
        pending_marker_state="present" if partial else "absent",
        failure_stage="latest_alias_write" if partial else "admission_validation",
        failure_class="ArtifactStoreError",
        failure_message="injected ResumeReport Store failure",
        recovery_available=partial,
        recovery_authorized=False,
    )

    def resume_with_result(selected, ref, payload):
        decision = selected.preflight_resume(ref, resume_id=payload.resume_id)
        return decision, write_result

    monkeypatch.setattr(
        WorkflowCheckpointStore,
        "resume_with_result",
        resume_with_result,
    )
    monkeypatch.setattr(
        local_entry_module,
        "build_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Graph must not run after a non-committed ResumeReport")
        ),
    )
    factory_calls = 0

    def runtime_factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("Runtime effect must not run")

    with pytest.raises(VerificationOperationExecutionError) as caught:
        resume_local_runtime(
            run_root=tmp_path,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
            settings_path=tmp_path / "unused-settings.yaml",
            approved_by="human",
            allow_game_launch=False,
            runtime_plugin_destination=None,
            allow_game_directory_write=False,
            resume_id=f"resume_store_{outcome}",
            runtime_evidence_factory=runtime_factory,
            injected_runtime_admission={
                "status": "admitted",
                "authorization_scope": "this_resume_only",
                "requested_side_effects": ["runtime_execution"],
                "authorized_side_effects": ["runtime_execution"],
                "provider": "injected_test",
            },
        )

    result = caught.value.verification_operation_result
    assert result.platform_status == expected_status
    assert result.failure_stage == "resume_report_store"
    assert result.outputs == ()
    assert len(result.store_receipts) == 1
    assert result.store_receipts[0].role == "resume_report"
    assert result.store_receipts[0].artifact_write_result == write_result
    assert factory_calls == 0


def _write_runtime_handoff_manifest(
    run_root: Path,
    *,
    checkpoint: dict[str, object],
    checkpoint_ref: ArtifactRef,
) -> None:
    snapshot = checkpoint["state_snapshot"]
    assert isinstance(snapshot, dict)
    artifacts = snapshot["artifacts"]
    artifact_hashes = snapshot["artifact_hashes"]
    assert isinstance(artifacts, dict)
    assert isinstance(artifact_hashes, dict)
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": checkpoint["run_id"],
                "request_id": checkpoint["request_id"],
                "workflow_checkpoint_ref": checkpoint_ref.path,
                "workflow_checkpoint_hash": checkpoint_ref.artifact_hash,
                "build_result_ref": artifacts["build_result"],
                "build_result_hash": artifact_hashes["build_result"],
            }
        ),
        encoding="utf-8",
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_runtime_preflight_supports_default_run_root_artifact_store(
    tmp_path: Path,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )

    result = preflight_local_runtime(
        run_root=tmp_path,
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
    )

    assert result["status"] == "READY_FOR_RUNTIME_PROFILE"
    assert result["artifact_store_root"] == str((tmp_path / "a").resolve())
    assert result["checkpoint"]["store_bound"] is True
    assert result["checkpoint"]["consumption_status"] == "unconsumed"
    assert "verification_operation_preflight_result" not in result
    assert "verification_operation_result" not in result
    assert "approval_identity_hash" not in result
    assert "approved_by" not in result
    assert "resume_id" not in result
    assert not (tmp_path / "runtime_resume_result.json").exists()


def test_real_runtime_preflight_cli_presents_advisory_without_execute_verdict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )

    exit_code = cli_module._run_preflight_runtime_command(
        Namespace(
            run_root=str(tmp_path),
            artifact_store_root=None,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
            resume_id=None,
            recover_accepted_resume=False,
            retry_runtime_observation=False,
            runtime_output_root=None,
            settings=None,
            runtime_plugin_destination=None,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "READY_FOR_RUNTIME_PROFILE"
    assert "verification_operation_preflight_result" not in payload
    assert "verification_operation_result" not in payload
    assert not (tmp_path / "runtime_resume_result.json").exists()


def test_runtime_preflight_supports_explicit_shared_artifact_store_without_writes(
    tmp_path: Path,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="shared-store",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    run_root = tmp_path / "run-root"
    _write_runtime_handoff_manifest(
        run_root,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    before = _tree_bytes(tmp_path)

    result = preflight_local_runtime(
        run_root=run_root,
        artifact_store_root=tmp_path / "shared-store",
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        resume_id="preflight_shared_store_001",
    )

    assert result["status"] == "READY_FOR_RUNTIME_PROFILE"
    assert result["writes_performed"] is False
    assert result["graph_invoked"] is False
    assert result["checkpoint_consumed"] is False
    assert result["resume_report_created"] is False
    assert result["runtime_evidence_created"] is False
    assert result["process_launched"] is False
    assert result["dll_copied"] is False
    assert _tree_bytes(tmp_path) == before


def test_runtime_profile_admission_blocks_before_checkpoint_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    destination = tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    destination.parent.mkdir(parents=True)
    before = _tree_bytes(tmp_path)
    feature_spec = _artifact_data(store, build_result, "feature_spec")
    captured_admission: dict[str, object] = {}

    monkeypatch.setattr(
        "src.mod_agent.local_entry.load_settings",
        lambda _: SimpleNamespace(runtime=SimpleNamespace(gtfo=SimpleNamespace())),
    )

    def record_admission(*args, **kwargs):
        captured_admission.update(kwargs)
        return {}

    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_admission_record",
        record_admission,
    )

    def block_profile(*args, **kwargs):
        raise LocalEntryError("profile acceptance contract blocked")

    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_profile_preflight_record",
        block_profile,
    )

    with pytest.raises(LocalEntryError, match="profile acceptance contract blocked"):
        resume_local_runtime(
            run_root=tmp_path,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
            settings_path=tmp_path / "runtime.yaml",
            approved_by="human",
            allow_game_launch=True,
            runtime_plugin_destination=destination,
            allow_game_directory_write=True,
            resume_id="resume_profile_blocked_001",
        )

    assert _tree_bytes(tmp_path) == before
    assert not (tmp_path / "runtime_resume_result.json").exists()
    assert captured_admission["acceptance_criteria"] == tuple(
        feature_spec["acceptance_criteria"]
    )


def test_runtime_preflight_rejects_wrong_artifact_store(
    tmp_path: Path,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="shared-store",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    run_root = tmp_path / "run-root"
    _write_runtime_handoff_manifest(
        run_root,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    wrong_store = tmp_path / "wrong-store"
    wrong_checkpoint = (
        wrong_store
        / "features"
        / str(build_result["feature_id"])
        / "r"
        / "workflow_checkpoint"
        / Path(checkpoint_ref.path).name
    )
    wrong_checkpoint.parent.mkdir(parents=True)
    wrong_checkpoint.write_bytes(Path(checkpoint_ref.path).read_bytes())
    manifest_path = run_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["workflow_checkpoint_ref"] = str(wrong_checkpoint)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(LocalEntryError, match="BuildResult binding is invalid"):
        preflight_local_runtime(
            run_root=run_root,
            artifact_store_root=wrong_store,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=wrong_checkpoint,
            checkpoint_hash=checkpoint_ref.artifact_hash,
        )


def test_runtime_preflight_rejects_checkpoint_outside_selected_store(
    tmp_path: Path,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="shared-store",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    run_root = tmp_path / "run-root"
    _write_runtime_handoff_manifest(
        run_root,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    external_checkpoint = tmp_path / "external-checkpoint.json"
    external_checkpoint.write_bytes(Path(checkpoint_ref.path).read_bytes())

    with pytest.raises(LocalEntryError, match="outside the selected ArtifactStore"):
        preflight_local_runtime(
            run_root=run_root,
            artifact_store_root=tmp_path / "shared-store",
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=external_checkpoint,
            checkpoint_hash=checkpoint_ref.artifact_hash,
        )


def test_runtime_preflight_rejects_manifest_checkpoint_identity_mismatch(
    tmp_path: Path,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    manifest_path = tmp_path / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["request_id"] = "wrong_request"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(LocalEntryError, match="manifest identity"):
        preflight_local_runtime(
            run_root=tmp_path,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
        )


def test_runtime_preflight_rejects_changed_verified_dll(tmp_path: Path) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    build = _artifact_data(store, build_result, "build_result")
    Path(build["verified_artifacts"][0]["resolved_path"]).write_bytes(b"changed")

    with pytest.raises(LocalEntryError, match="Build output identity changed"):
        preflight_local_runtime(
            run_root=tmp_path,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
        )


def test_runtime_preflight_rejects_stale_checkpoint_lineage(tmp_path: Path) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    feature_spec = _artifact_data(store, build_result, "feature_spec")
    store.write(
        feature_id=str(build_result["feature_id"]),
        artifact_type="feature_spec",
        payload={
            **feature_spec,
            "message": "Feature specification changed after Build.",
        },
    )

    with pytest.raises(
        LocalEntryError,
        match="Runtime continuation preflight was blocked: STALE_RESUME_REJECTED",
    ):
        preflight_local_runtime(
            run_root=tmp_path,
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
        )


def test_fresh_process_rejects_consumed_build_handoff(tmp_path: Path) -> None:
    first_store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = first_store.read(checkpoint_ref)["data"]
    first_payload = _build_runtime_resume_payload(
        checkpoint=checkpoint,
        resume_id="resume_build_runtime_once_001",
    )
    first_decision, _ = WorkflowCheckpointStore(first_store).resume(
        checkpoint_ref,
        first_payload,
    )

    fresh_store = ArtifactStore(tmp_path / "artifacts")
    second_decision, second_report_ref = WorkflowCheckpointStore(fresh_store).resume(
        checkpoint_ref,
        _build_runtime_resume_payload(
            checkpoint=checkpoint,
            resume_id="resume_build_runtime_twice_001",
        ),
    )
    second_report = fresh_store.read(second_report_ref)["data"]

    assert first_decision.allowed is True
    assert second_decision.allowed is False
    assert second_report["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"


def test_exact_accepted_resume_can_be_read_recovered_before_runtime(
    tmp_path: Path,
) -> None:
    store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = store.read(checkpoint_ref)["data"]
    resume_id = "resume_pre_runtime_recovery_001"
    decision, report_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        _build_runtime_resume_payload(
            checkpoint=checkpoint,
            resume_id=resume_id,
        ),
    )

    recovered, recovered_report_ref = WorkflowCheckpointStore(
        ArtifactStore(tmp_path / "artifacts")
    ).preflight_accepted_resume_recovery(
        checkpoint_ref,
        resume_id=resume_id,
    )

    assert decision.allowed is True
    assert recovered.allowed is True
    assert recovered.applied_updates == decision.applied_updates
    assert recovered_report_ref == report_ref
    assert len(
        store.list_feature_artifact_revisions(
            str(checkpoint["feature_id"]),
            "resume_report",
        )
    ) == 1


def _persist_observation_owned_runtime_failure(
    store: ArtifactStore,
    checkpoint_ref: ArtifactRef,
    *,
    resume_id: str,
    runtime_admission: dict[str, object] | None = None,
) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef]:
    checkpoint = store.read(checkpoint_ref)["data"]
    resume_payload = _build_runtime_resume_payload(
        checkpoint=checkpoint,
        resume_id=resume_id,
    )
    if runtime_admission is not None:
        resume_payload = ResumePayload(
            **{
                **resume_payload.to_dict(),
                "runtime_admission": runtime_admission,
            }
        )
    decision, report_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        resume_payload,
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=report_ref,
    )

    def observation_failure(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        payload = build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build.get("execution_mode")),
            evidence_items=(),
            startup_loaded=True,
            gameplay_behavior_verified=False,
            verification_status="inconclusive",
            limitations=("Operator observation requires correction.",),
            acceptance_criteria=tuple(
                feature_spec.get("acceptance_criteria") or ()
            ),
            runtime_verification_plan=tuple(
                feature_spec.get("runtime_verification_plan") or ()
            ),
            failure_ownership={
                "owner": "observation",
                "failure_class": "operator_status_semantic_conflict",
                "source_repair_allowed": False,
                "required_action": "repair_runtime_observation",
                "reason": "Operator observation requires correction.",
            },
        )
        payload["stagger_runtime_schema_version"] = (
            "gtfo_stagger_two_process_runtime_v1"
        )
        payload["stagger_runtime_attempts"] = [
            {
                "stagger_attempt_mode": "general_enabled_false",
                "plugin_deployment_binding": {
                    "restored": True,
                    "restoration_status": "restored",
                },
                "stagger_config_deployment_binding": {
                    "restored": True,
                    "restoration_status": "restored",
                },
            }
        ]
        return payload

    graph = build_graph(
        store,
        runtime_evidence_factory=observation_failure,
        verification_operation=_runtime_workflow_graph_operation(
            store,
            checkpoint_ref=checkpoint_ref,
            resume_report_ref=report_ref,
        ),
    )
    result = graph.invoke(resumed_state)
    assert result["current_stage"] == "blocked"
    return (
        report_ref,
        ArtifactRef(
            feature_id=str(checkpoint["feature_id"]),
            artifact_type="runtime_evidence",
            path=result["artifacts"]["runtime_evidence"],
            artifact_hash=result["artifact_hashes"]["runtime_evidence"],
        ),
        ArtifactRef(
            feature_id=str(checkpoint["feature_id"]),
            artifact_type="repair_plan",
            path=result["artifacts"]["repair_plan"],
            artifact_hash=result["artifact_hashes"]["repair_plan"],
        ),
    )


def test_runtime_observation_retry_reuses_exact_report_and_failure_lineage(
    tmp_path: Path,
) -> None:
    store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    resume_id = "resume_observation_retry_001"
    report_ref, runtime_ref, repair_ref = (
        _persist_observation_owned_runtime_failure(
            store,
            checkpoint_ref,
            resume_id=resume_id,
        )
    )

    decision, bound_report, bound_runtime, bound_repair, binding = (
        WorkflowCheckpointStore(store).preflight_runtime_observation_retry(
            checkpoint_ref,
            resume_id=resume_id,
        )
    )

    assert decision.allowed is True
    assert bound_report == report_ref
    assert bound_runtime == runtime_ref
    assert bound_repair == repair_ref
    assert binding == {
        "retry_number": 1,
        "retry_budget": 2,
        "retry_budget_remaining_before_attempt": 2,
        "prior_runtime_evidence_ref": runtime_ref.path,
        "prior_runtime_evidence_hash": runtime_ref.artifact_hash,
        "prior_repair_plan_ref": repair_ref.path,
        "prior_repair_plan_hash": repair_ref.artifact_hash,
        "resume_report_ref": report_ref.path,
        "resume_report_hash": report_ref.artifact_hash,
        "new_checkpoint_would_be_created": False,
        "new_resume_report_would_be_created": False,
    }
    assert len(
        store.list_feature_artifact_revisions(
            checkpoint_ref.feature_id,
            "resume_report",
        )
    ) == 1


def test_runtime_observation_retry_rejects_product_owned_latest_runtime(
    tmp_path: Path,
) -> None:
    store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    resume_id = "resume_observation_retry_product_owner_001"
    _, runtime_ref, _ = _persist_observation_owned_runtime_failure(
        store,
        checkpoint_ref,
        resume_id=resume_id,
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    snapshot = checkpoint["state_snapshot"]
    product_runtime = {
        **store.read(runtime_ref)["data"],
        "failure_ownership": {
            "owner": "product_behavior",
            "failure_class": "runtime_behavior_failed",
            "source_repair_allowed": True,
            "required_action": "repair_source",
            "reason": "Product behavior failed.",
        },
    }
    store.write(
        feature_id=checkpoint_ref.feature_id,
        artifact_type="runtime_evidence",
        payload=product_runtime,
        status="blocked",
        upstream_refs=[
            ArtifactRef(
                feature_id=checkpoint_ref.feature_id,
                artifact_type="build_result",
                path=snapshot["artifacts"]["build_result"],
                artifact_hash=snapshot["artifact_hashes"]["build_result"],
            ),
            ArtifactRef(
                feature_id=checkpoint_ref.feature_id,
                artifact_type="feature_spec",
                path=snapshot["artifacts"]["feature_spec"],
                artifact_hash=snapshot["artifact_hashes"]["feature_spec"],
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="OBSERVATION_RETRY_RUNTIME_EVIDENCE_INELIGIBLE",
    ):
        WorkflowCheckpointStore(store).preflight_runtime_observation_retry(
            checkpoint_ref,
            resume_id=resume_id,
        )


def test_initial_stagger_repair_preflight_requires_empty_separate_output_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="shared-store",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    source_root = tmp_path / "source-run"
    _write_runtime_handoff_manifest(
        source_root,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    output_root = tmp_path / "runtime-output"
    output_root.mkdir()
    destination = tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    destination.parent.mkdir(parents=True)

    monkeypatch.setattr(
        "src.mod_agent.local_entry.load_settings",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_profile_preflight_record",
        lambda *_, **__: {
            "plugin_deployment": {"destination_path": str(destination)},
            "stagger_acceptance": {"status": "ready"},
        },
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._stagger_repair_attempt_projection",
        lambda *_: {
            "repair_attempt": {"attempt_id": "repair_attempt_001"},
            "criterion_results": [],
        },
    )
    before = _tree_bytes(tmp_path)

    with pytest.raises(
        LocalEntryError,
        match="Initial Stagger repair Runtime requires an independent",
    ):
        preflight_local_runtime(
            run_root=source_root,
            artifact_store_root=tmp_path / "shared-store",
            feature_id=str(build_result["feature_id"]),
            checkpoint_path=checkpoint_ref.path,
            checkpoint_hash=checkpoint_ref.artifact_hash,
            settings_path=tmp_path / "runtime.yaml",
            runtime_plugin_destination=destination,
        )

    result = preflight_local_runtime(
        run_root=source_root,
        artifact_store_root=tmp_path / "shared-store",
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        settings_path=tmp_path / "runtime.yaml",
        runtime_plugin_destination=destination,
        runtime_output_root=output_root.resolve(),
    )

    assert result["status"] == "READY_FOR_EXTERNAL_AUTHORIZATION"
    assert result["runtime_output"]["enabled"] is True
    assert result["runtime_output"]["runtime_output_root"] == str(
        output_root.resolve()
    )
    assert result["runtime_output"]["source_run_root"] == str(
        source_root.resolve()
    )
    assert result["runtime_profile"]["deployment_backup"]["backup_root"] == str(
        (output_root / "runtime_continuation_deployment_backup").resolve()
    )
    assert result["writes_performed"] is False
    assert result["checkpoint_consumed"] is False
    assert result["process_launched"] is False
    assert result["dll_copied"] is False
    assert "verification_operation_preflight_result" not in result
    assert "verification_operation_result" not in result
    assert "approval_identity_hash" not in result
    assert "approved_by" not in result
    assert _tree_bytes(tmp_path) == before


def test_initial_stagger_repair_resume_routes_all_runtime_output_outside_build_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="shared-store",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    source_root = tmp_path / "source-run"
    _write_runtime_handoff_manifest(
        source_root,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    output_root = tmp_path / "runtime-output"
    output_root.mkdir()
    destination = tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    destination.parent.mkdir(parents=True)
    requested = ["runtime_execution", "process_launch", "game_directory_write"]
    runtime_admission = {
        "requested_side_effects": requested,
        "authorized_side_effects": requested,
        "evidence_source": "gtfo_real_runtime_automation",
        "allow_game_launch": True,
        "plugin_deployment": {
            "destination_path": str(destination),
            "destination_existed_at_admission": False,
            "destination_sha256_at_admission": None,
            "allow_game_directory_write": True,
        },
        "stagger_acceptance": {
            "config": {
                "destination_existed": False,
                "destination_sha256": None,
            }
        },
    }
    projection = {
        "repair_attempt": {
            "attempt_id": "repair_attempt_001",
            "run_id": str(checkpoint["run_id"]),
        },
        "criterion_results": [],
    }

    monkeypatch.setattr(
        "src.mod_agent.local_entry.load_settings",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_admission_record",
        lambda *_, **__: dict(runtime_admission),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_profile_preflight_record",
        lambda *_, **__: {
            "plugin_deployment": {"destination_path": str(destination)},
            "stagger_acceptance": {"status": "ready"},
        },
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._stagger_repair_attempt_projection",
        lambda *_: projection,
    )
    captured: dict[str, object] = {}

    def make_runtime_factory(**kwargs):
        captured.update(kwargs)

        def runtime_factory(
            feature_id: str,
            build: dict[str, object],
            feature_spec: dict[str, object],
        ) -> dict[str, object]:
            return build_fake_runtime_evidence_payload(
                feature_id=feature_id,
                input_execution_mode=str(build.get("execution_mode")),
                acceptance_criteria=tuple(
                    feature_spec.get("acceptance_criteria") or ()
                ),
                runtime_verification_plan=tuple(
                    feature_spec.get("runtime_verification_plan") or ()
                ),
            )

        return runtime_factory

    monkeypatch.setattr(
        "src.mod_agent.local_entry._make_deploying_runtime_evidence_factory",
        make_runtime_factory,
    )
    source_before = _tree_bytes(source_root)

    summary = resume_local_runtime(
        run_root=source_root,
        artifact_store_root=tmp_path / "shared-store",
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        settings_path=tmp_path / "runtime.yaml",
        approved_by="human",
        allow_game_launch=True,
        runtime_plugin_destination=destination,
        allow_game_directory_write=True,
        resume_id="resume_initial_stagger_repair_001",
        runtime_output_root=output_root.resolve(),
    )

    assert summary["current_stage"] == "done"
    assert summary["runtime_output_root"] == str(output_root.resolve())
    assert summary["source_run_root"] == str(source_root.resolve())
    assert summary["runtime_admission"]["runtime_output_binding"][
        "runtime_output_root"
    ] == str(output_root.resolve())
    assert captured["runtime_output_directory"] == output_root.resolve()
    assert captured["backup_directory"] == (
        output_root / "runtime_continuation_deployment_backup"
    )
    assert captured["operator_completion_directory"] == (
        output_root / "operator_completion"
    )
    assert captured["runtime_run_id"] == checkpoint["run_id"]
    assert (output_root / "runtime_resume_result.json").is_file()
    assert not (source_root / "runtime_resume_result.json").exists()
    assert _tree_bytes(source_root) == source_before


def test_runtime_observation_retry_preflight_uses_empty_separate_output_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="shared-store",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    source_root = tmp_path / "source-run"
    _write_runtime_handoff_manifest(
        source_root,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    resume_id = "resume_observation_retry_preflight_001"
    output_root = tmp_path / "retry-output"
    output_root.mkdir()
    destination = tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    destination.parent.mkdir(parents=True)
    runtime_admission = {
        "requested_side_effects": ["runtime_execution"],
        "authorized_side_effects": ["runtime_execution"],
        "evidence_source": "injected_test",
    }
    admission_snapshot = {
        "status": "admitted",
        "authorization_scope": "this_resume_only",
        "requested_side_effects": ["runtime_execution"],
        "authorized_side_effects": ["runtime_execution"],
        "provider": "injected_test",
        "runtime_admission": runtime_admission,
    }
    _persist_observation_owned_runtime_failure(
        store,
        checkpoint_ref,
        resume_id=resume_id,
        runtime_admission=admission_snapshot,
    )

    monkeypatch.setattr(
        "src.mod_agent.local_entry.load_settings",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_admission_record",
        lambda *_, **__: runtime_admission,
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_profile_preflight_record",
        lambda *_, **__: {
            "plugin_deployment": {"destination_path": str(destination)},
            "stagger_acceptance": {"status": "ready"},
        },
    )
    before = _tree_bytes(tmp_path)

    result = preflight_local_runtime(
        run_root=source_root,
        artifact_store_root=tmp_path / "shared-store",
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        settings_path=tmp_path / "runtime.yaml",
        runtime_plugin_destination=destination,
        resume_id=resume_id,
        retry_runtime_observation=True,
        runtime_output_root=output_root.resolve(),
    )

    assert result["status"] == "READY_FOR_EXTERNAL_AUTHORIZATION"
    assert result["checkpoint"]["consumption_status"] == (
        "runtime_observation_retry"
    )
    assert result["runtime_observation_retry"]["retry_number"] == 1
    assert result["runtime_observation_retry"]["runtime_output_root"] == str(
        output_root.resolve()
    )
    assert result["runtime_profile"]["runtime_observation_retry_output"][
        "empty"
    ] is True
    assert result["runtime_profile"]["prior_restoration"]["status"] == "passed"
    assert result["writes_performed"] is False
    assert result["resume_report_created"] is False
    assert result["runtime_evidence_created"] is False
    assert "verification_operation_preflight_result" not in result
    assert "verification_operation_result" not in result
    assert "approval_identity_hash" not in result
    assert "approved_by" not in result
    assert _tree_bytes(tmp_path) == before


def test_runtime_observation_retry_executes_only_runtime_with_one_resume_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="shared-store",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    source_root = tmp_path / "source-run"
    _write_runtime_handoff_manifest(
        source_root,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    output_root = tmp_path / "retry-output"
    output_root.mkdir()
    destination = tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    destination.parent.mkdir(parents=True)
    requested = ["runtime_execution", "process_launch", "game_directory_write"]
    runtime_admission = {
        "requested_side_effects": requested,
        "authorized_side_effects": requested,
        "evidence_source": "gtfo_real_runtime_automation",
        "allow_game_launch": True,
        "plugin_deployment": {
            "destination_path": str(destination),
            "destination_existed_at_admission": False,
            "destination_sha256_at_admission": None,
            "allow_game_directory_write": True,
        },
        "stagger_acceptance": {
            "config": {
                "destination_existed": False,
                "destination_sha256": None,
            }
        },
    }
    admission_snapshot = {
        "status": "admitted",
        "authorization_scope": "this_resume_only",
        "requested_side_effects": requested,
        "authorized_side_effects": requested,
        "provider": "gtfo_real_runtime_automation",
        "runtime_admission": runtime_admission,
    }
    resume_id = "resume_observation_retry_execute_001"
    _persist_observation_owned_runtime_failure(
        store,
        checkpoint_ref,
        resume_id=resume_id,
        runtime_admission=admission_snapshot,
    )

    monkeypatch.setattr(
        "src.mod_agent.local_entry.load_settings",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_admission_record",
        lambda *_, **__: runtime_admission,
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_profile_preflight_record",
        lambda *_, **__: {
            "plugin_deployment": {"destination_path": str(destination)},
            "stagger_acceptance": {"status": "ready"},
        },
    )
    captured_retry_binding: dict[str, object] = {}
    captured_operator_completion: dict[str, object] = {}

    def make_runtime_factory(**kwargs):
        captured_retry_binding.update(kwargs["runtime_observation_retry"])
        captured_operator_completion["directory"] = kwargs[
            "operator_completion_directory"
        ]

        def runtime_factory(
            feature_id: str,
            build: dict[str, object],
            feature_spec: dict[str, object],
        ) -> dict[str, object]:
            payload = build_fake_runtime_evidence_payload(
                feature_id=feature_id,
                input_execution_mode=str(build.get("execution_mode")),
                acceptance_criteria=tuple(
                    feature_spec.get("acceptance_criteria") or ()
                ),
                runtime_verification_plan=tuple(
                    feature_spec.get("runtime_verification_plan") or ()
                ),
            )
            payload["runtime_observation_retry"] = dict(
                kwargs["runtime_observation_retry"]
            )
            return payload

        return runtime_factory

    monkeypatch.setattr(
        "src.mod_agent.local_entry._make_deploying_runtime_evidence_factory",
        make_runtime_factory,
    )

    summary = resume_local_runtime(
        run_root=source_root,
        artifact_store_root=tmp_path / "shared-store",
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        settings_path=tmp_path / "runtime.yaml",
        approved_by="human",
        allow_game_launch=True,
        runtime_plugin_destination=destination,
        allow_game_directory_write=True,
        resume_id=resume_id,
        retry_runtime_observation=True,
        runtime_output_root=output_root.resolve(),
    )

    assert summary["current_stage"] == "done"
    assert summary["runtime_observation_retry"] is True
    assert summary["upstream_stages_repeated"] is False
    machine_result = summary["verification_operation_result"]
    assert all(
        item["role"] != "resume_report" for item in machine_result["outputs"]
    )
    assert all(
        item["role"] != "resume_report"
        for item in machine_result["store_receipts"]
    )
    assert captured_retry_binding["retry_number"] == 1
    assert captured_operator_completion["directory"] == (
        output_root.resolve() / "operator_completion"
    )
    assert (output_root / "runtime_resume_result.json").is_file()
    assert not (source_root / "runtime_resume_result.json").exists()
    assert len(
        store.list_feature_artifact_revisions(
            str(build_result["feature_id"]),
            "resume_report",
        )
    ) == 1
    assert len(
        store.list_feature_artifact_revisions(
            str(build_result["feature_id"]),
            "workflow_checkpoint",
        )
    ) == 1
    assert len(
        store.list_feature_artifact_revisions(
            str(build_result["feature_id"]),
            "runtime_evidence",
        )
    ) == 2


def test_runtime_recovery_preflight_reuses_report_without_writes(
    tmp_path: Path,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    resume_id = "resume_pre_runtime_recovery_preflight_001"
    _, report_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        _build_runtime_resume_payload(
            checkpoint=checkpoint,
            resume_id=resume_id,
        ),
    )
    before = _tree_bytes(tmp_path)

    result = preflight_local_runtime(
        run_root=tmp_path,
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        resume_id=resume_id,
        recover_accepted_resume=True,
    )

    assert result["status"] == "READY_FOR_RUNTIME_PROFILE"
    assert result["checkpoint"]["consumption_status"] == (
        "accepted_resume_recovery"
    )
    assert result["accepted_resume_recovery"] == {
        "enabled": True,
        "resume_id": resume_id,
        "resume_report_path": report_ref.path,
        "resume_report_hash": report_ref.artifact_hash,
        "new_resume_report_would_be_created": False,
    }
    assert result["writes_performed"] is False
    assert result["resume_report_created"] is False
    assert "verification_operation_preflight_result" not in result
    assert "verification_operation_result" not in result
    assert "approval_identity_hash" not in result
    assert "approved_by" not in result
    assert _tree_bytes(tmp_path) == before


def test_runtime_recovery_reuses_exact_admission_and_creates_no_second_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(
        tmp_path,
        artifact_directory="a",
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    _write_runtime_handoff_manifest(
        tmp_path,
        checkpoint=checkpoint,
        checkpoint_ref=checkpoint_ref,
    )
    destination = tmp_path / "BepInEx" / "plugins" / "BetterHitFeedback.dll"
    destination.parent.mkdir(parents=True)
    requested = ["runtime_execution", "process_launch", "game_directory_write"]
    runtime_admission = {
        "requested_side_effects": requested,
        "authorized_side_effects": requested,
        "evidence_source": "gtfo_real_runtime_automation",
        "allow_game_launch": True,
        "plugin_deployment": {
            "destination_path": str(destination),
            "destination_existed_at_admission": False,
            "destination_sha256_at_admission": None,
            "allow_game_directory_write": True,
        },
        "stagger_acceptance": None,
    }
    admission_snapshot = {
        "status": "admitted",
        "authorization_scope": "this_resume_only",
        "requested_side_effects": requested,
        "authorized_side_effects": requested,
        "provider": "gtfo_real_runtime_automation",
        "runtime_admission": runtime_admission,
    }
    resume_id = "resume_pre_runtime_recovery_execute_001"
    payload = ResumePayload(
        resume_id=resume_id,
        run_id=str(checkpoint["run_id"]),
        request_id=str(checkpoint["request_id"]),
        feature_id=str(checkpoint["feature_id"]),
        stage="build",
        decision="approve",
        approved_by="human",
        approved_at="2026-07-29T00:00:00Z",
        artifact_refs=tuple(checkpoint["artifact_refs"]),  # type: ignore[arg-type]
        runtime_admission=admission_snapshot,
    )
    _, report_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        payload,
    )

    monkeypatch.setattr(
        "src.mod_agent.local_entry.load_settings",
        lambda _: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_admission_record",
        lambda *_, **__: runtime_admission,
    )
    monkeypatch.setattr(
        "src.mod_agent.local_entry._runtime_profile_preflight_record",
        lambda *_, **__: {
            "plugin_deployment": {"destination_path": str(destination)}
        },
    )

    def runtime_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        return build_fake_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build.get("execution_mode")),
            acceptance_criteria=tuple(feature_spec.get("acceptance_criteria") or ()),
            runtime_verification_plan=tuple(
                feature_spec.get("runtime_verification_plan") or ()
            ),
        )

    monkeypatch.setattr(
        "src.mod_agent.local_entry._make_deploying_runtime_evidence_factory",
        lambda **_: runtime_factory,
    )

    before_preflight = _tree_bytes(tmp_path)
    preflight = preflight_local_runtime(
        run_root=tmp_path,
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        settings_path=tmp_path / "runtime.yaml",
        runtime_plugin_destination=destination,
        resume_id=resume_id,
        recover_accepted_resume=True,
    )

    assert preflight["status"] == "READY_FOR_EXTERNAL_AUTHORIZATION"
    assert (
        preflight["runtime_profile"]["accepted_resume_admission_match"] is True
    )
    assert _tree_bytes(tmp_path) == before_preflight

    summary = resume_local_runtime(
        run_root=tmp_path,
        feature_id=str(build_result["feature_id"]),
        checkpoint_path=checkpoint_ref.path,
        checkpoint_hash=checkpoint_ref.artifact_hash,
        settings_path=tmp_path / "runtime.yaml",
        approved_by="human",
        allow_game_launch=True,
        runtime_plugin_destination=destination,
        allow_game_directory_write=True,
        resume_id=resume_id,
        recover_accepted_resume=True,
    )

    assert summary["current_stage"] == "done"
    assert summary["accepted_resume_recovery"] is True
    assert summary["artifacts"]["resume_report"] == report_ref.path
    machine_result = summary["verification_operation_result"]
    assert all(
        item["role"] != "resume_report" for item in machine_result["outputs"]
    )
    assert all(
        item["role"] != "resume_report"
        for item in machine_result["store_receipts"]
    )
    assert len(
        store.list_feature_artifact_revisions(
            str(checkpoint["feature_id"]),
            "resume_report",
        )
    ) == 1


def test_accepted_resume_recovery_rejects_wrong_id_and_runtime_state(
    tmp_path: Path,
) -> None:
    store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = store.read(checkpoint_ref)["data"]
    resume_id = "resume_pre_runtime_recovery_002"
    decision, report_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        _build_runtime_resume_payload(
            checkpoint=checkpoint,
            resume_id=resume_id,
        ),
    )
    with pytest.raises(ValueError, match="resume_id does not match"):
        WorkflowCheckpointStore(store).preflight_accepted_resume_recovery(
            checkpoint_ref,
            resume_id="resume_wrong",
        )

    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=report_ref,
    )
    graph = build_graph(
        store,
        runtime_evidence_factory=_fake_runtime_factory,
        verification_operation=_runtime_workflow_graph_operation(
            store,
            checkpoint_ref=checkpoint_ref,
            resume_report_ref=report_ref,
        ),
    )
    result = graph.invoke(resumed_state)
    assert result["current_stage"] == "done"

    with pytest.raises(ValueError, match="PRIOR_RUNTIME_STATE_PRESENT"):
        WorkflowCheckpointStore(store).preflight_accepted_resume_recovery(
            checkpoint_ref,
            resume_id=resume_id,
        )


def test_build_handoff_rejects_missing_fresh_runtime_admission(
    tmp_path: Path,
) -> None:
    store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = store.read(checkpoint_ref)["data"]
    payload = _build_runtime_resume_payload(
        checkpoint=checkpoint,
        resume_id="resume_build_runtime_no_admission_001",
    )
    payload = ResumePayload(
        **{
            **payload.to_dict(),
            "runtime_admission": None,
        }
    )

    decision, report_ref = WorkflowCheckpointStore(
        ArtifactStore(tmp_path / "artifacts")
    ).resume(checkpoint_ref, payload)
    report = store.read(report_ref)["data"]

    assert decision.allowed is False
    assert any(
        blocker["code"] == "FRESH_RUNTIME_ADMISSION_MISSING"
        for blocker in report["blockers"]
    )


def test_build_handoff_rejects_changed_verified_build_bytes(
    tmp_path: Path,
) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(tmp_path)
    build = _artifact_data(store, build_result, "build_result")
    Path(build["verified_artifacts"][0]["resolved_path"]).write_bytes(b"changed")
    checkpoint = store.read(checkpoint_ref)["data"]

    decision, report_ref = WorkflowCheckpointStore(
        ArtifactStore(tmp_path / "artifacts")
    ).resume(
        checkpoint_ref,
        _build_runtime_resume_payload(
            checkpoint=checkpoint,
            resume_id="resume_build_runtime_changed_bytes_001",
        ),
    )
    report = store.read(report_ref)["data"]

    assert decision.allowed is False
    assert report["blockers"][0]["code"] == "BUILD_OUTPUT_BYTES_CHANGED"


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("run_id", "wrong_run", "RESUME_RUN_MISMATCH"),
        ("request_id", "wrong_request", "RESUME_REQUEST_MISMATCH"),
        ("feature_id", "wrong_feature", "RESUME_FEATURE_MISMATCH"),
        ("stage", "runtime_evidence", "RESUME_STAGE_MISMATCH"),
    ],
)
def test_build_handoff_rejects_wrong_resume_identity(
    tmp_path: Path,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = store.read(checkpoint_ref)["data"]
    payload_data = _build_runtime_resume_payload(
        checkpoint=checkpoint,
        resume_id=f"resume_wrong_{field}",
    ).to_dict()
    payload_data[field] = value

    decision, report_ref = WorkflowCheckpointStore(
        ArtifactStore(tmp_path / "artifacts")
    ).resume(checkpoint_ref, ResumePayload(**payload_data))
    report = store.read(report_ref)["data"]

    assert decision.allowed is False
    assert any(
        blocker["code"] == expected_code for blocker in report["blockers"]
    )


def test_build_handoff_rejects_missing_checkpoint_artifact_ref(
    tmp_path: Path,
) -> None:
    store, _, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = store.read(checkpoint_ref)["data"]
    payload_data = _build_runtime_resume_payload(
        checkpoint=checkpoint,
        resume_id="resume_missing_build_ref_001",
    ).to_dict()
    payload_data["artifact_refs"] = [
        ref
        for ref in payload_data["artifact_refs"]
        if ref != checkpoint["resume_binding"]["build_result_ref"]
    ]

    decision, report_ref = WorkflowCheckpointStore(
        ArtifactStore(tmp_path / "artifacts")
    ).resume(checkpoint_ref, ResumePayload(**payload_data))
    report = store.read(report_ref)["data"]

    assert decision.allowed is False
    assert any(
        blocker["code"] == "RESUME_ARTIFACT_REFS_MISSING"
        for blocker in report["blockers"]
    )


def test_build_handoff_rejects_stale_artifact_lineage(tmp_path: Path) -> None:
    store, build_result, checkpoint_ref = _successful_build_handoff(tmp_path)
    checkpoint = store.read(checkpoint_ref)["data"]
    feature_spec = _artifact_data(store, build_result, "feature_spec")
    changed_feature_spec = dict(feature_spec)
    changed_feature_spec["message"] = "Feature specification changed after Build."
    store.write(
        feature_id=str(build_result["feature_id"]),
        artifact_type="feature_spec",
        payload=changed_feature_spec,
    )

    decision, report_ref = WorkflowCheckpointStore(
        ArtifactStore(tmp_path / "artifacts")
    ).resume(
        checkpoint_ref,
        _build_runtime_resume_payload(
            checkpoint=checkpoint,
            resume_id="resume_stale_build_handoff_001",
        ),
    )
    report = store.read(report_ref)["data"]

    assert decision.allowed is False
    assert report["blockers"][0]["code"] == "STALE_RESUME_REJECTED"
    assert "feature_spec hash changed" in report["stale_reasons"]


def test_evidence_backed_path_reaches_done(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "done"
    assert "workflow_summary" in result["artifacts"]
    assert "blocked_report" not in result["artifacts"]
    assert result["blockers"] == []
    assert result["evidence_summary"]["can_generate_patch"] is True
    assert result["evidence_summary"]["retrieval_methods_used"] == [
        "symbol_exact",
        "text_match",
    ]
    assert result["evidence_summary"]["missing_evidence"] == []
    assert result["evidence_summary"]["timing"]["final_count"] == 2.0
    assert result["review_summary"]["allowed_next_stage"] == "dry_run_apply"
    assert result["build_summary"]["execution_mode"] == "fake"
    assert result["build_summary"]["claims_real_build_success"] is False
    assert result["runtime_summary"]["status"] == "verified"
    assert result["runtime_summary"]["acceptance_verified"] is True
    assert result["runtime_summary"]["claims_real_runtime_success"] is False
    implementation = _artifact_data(store, result, "implementation_plan")
    proposal = _artifact_data(store, result, "patch_proposal")
    edit_binding = implementation["binding_registry"]["edit_bindings"][0]
    assert edit_binding["evidence_id"] in (
        implementation["evidence_refs"]
    )
    assert edit_binding["target_span"] == (
        proposal["context_pack"]["source_snippets"][0]["span"]
    )
    assert proposal["context_pack"]["binding_registry_ref"]["artifact_hash"] == (
        result["artifact_hashes"]["implementation_plan"]
    )
    assert proposal["context_pack"]["allowed_edit_binding_ids"] == [
        "edit_binding_001",
        "edit_binding_002",
    ]
    assert proposal["context_pack"]["display_fields_authority"] == (
        "derived_non_authoritative"
    )
    assert proposal["context_pack"]["git_binding_required"] is True
    assert proposal["context_pack"]["git_binding"]["status"] == "available"
    assert proposal["context_pack"]["git_binding"]["base_revision"]
    assert proposal["context_pack"]["git_binding"]["diff_hash"].startswith("sha256:")
    assert isinstance(
        proposal["context_pack"]["git_binding"]["dirty_tree_policy"],
        dict,
    )


def test_graph_forwards_explicit_proposal_source_snippet_char_limit(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        proposal_source_snippet_char_limit=1234,
    )
    state = create_initial_state(
        run_id="run_explicit_proposal_context_budget",
        request_id="req_explicit_proposal_context_budget",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)
    proposal = _artifact_data(store, result, "patch_proposal")

    assert proposal["context_pack"]["context_budget"][
        "source_snippet_char_limit"
    ] == 1234


def test_graph_can_persist_independent_critic_and_keep_routing_deterministic(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        proposal_critic=RuleBasedProposalCritic(),
        critic_requirement="required",
    )
    state = create_initial_state(
        run_id="run_with_critic",
        request_id="req_with_critic",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    critic = _artifact_data(store, result, "critic_assessment")
    review = _artifact_data(store, result, "proposal_review")
    assert result["current_stage"] == "done"
    assert critic["verdict"] == "pass"
    assert critic["subject_artifact_hash"] == result["artifact_hashes"]["patch_proposal"]
    assert critic["independence_boundary"] == "read_only_no_route_authority"
    assert review["decision"] == "approve_dry_run"
    assert "proposal_critic" in review["checked_rules"]
    assert review["critic_gate"]["state"] == "required_succeeded"


def test_graph_fails_closed_when_required_critic_execution_fails(tmp_path: Path) -> None:
    class FailingCritic:
        def assess(self, proposal, *, subject_artifact_ref, subject_artifact_hash):
            raise RuntimeError("critic unavailable")

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        proposal_critic=FailingCritic(),
        critic_requirement="required",
    )
    state = create_initial_state(
        run_id="run_with_failed_critic",
        request_id="req_with_failed_critic",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    critic = _artifact_data(store, result, "critic_assessment")
    review = _artifact_data(store, result, "proposal_review")
    assert result["current_stage"] == "blocked"
    assert critic["verdict"] == "unresolved"
    assert review["allowed_next_stage"] is None
    assert review["critic_gate"]["state"] == "required_failed"
    assert "dry_run_result" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]


def test_graph_blocks_when_required_proposal_critic_has_no_provider(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        critic_requirement="required",
    )
    state = create_initial_state(
        run_id="run_missing_required_critic",
        request_id="req_missing_required_critic",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    review = _artifact_data(store, result, "proposal_review")
    assert result["current_stage"] == "blocked"
    assert review["decision"] == "blocked_requires_human"
    assert review["critic_gate"]["state"] == "required_failed"
    assert "critic_assessment" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]


def test_default_proposal_git_binding_uses_project_root_when_cwd_moves(
    tmp_path: Path,
    monkeypatch,
    _default_proposal_git_repository: list[dict[str, object]],
) -> None:
    monkeypatch.chdir(tmp_path)

    binding = _default_proposal_git_binding_factory()

    assert binding["status"] == "available", binding
    assert binding["base_revision"] == "b" * 40
    assert binding["diff_hash"].startswith("sha256:")
    assert _default_proposal_git_repository == [
        {
            "root": _PROJECT_ROOT,
            "git_executable": None,
        },
        {
            "root": _PROJECT_ROOT,
            "git_executable": (
                "git",
                "--git-dir",
                str(_PROJECT_ROOT / ".git"),
                "--work-tree",
                str(_PROJECT_ROOT),
            ),
        },
    ]


def test_graph_patch_proposal_context_can_require_git_binding(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        proposal_git_binding_factory=lambda: {
            "status": "available",
            "base_revision": "a" * 40,
            "branch": "codex/test",
            "is_dirty": False,
            "diff_hash": "sha256:gitdiff",
            "dirty_tree_policy": {
                "status": "clean",
                "blocks_proposal_binding": False,
                "blockers": [],
            },
        },
    )
    state = create_initial_state(
        run_id="run_git_bound_context",
        request_id="req_git_bound_context",
        user_request="default config Load runtime diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    proposal = _artifact_data(store, result, "patch_proposal")
    review = _artifact_data(store, result, "proposal_review")

    assert result["current_stage"] == "done"
    assert proposal["context_pack"]["git_binding_required"] is True
    assert proposal["context_pack"]["git_binding"]["base_revision"] == "a" * 40
    assert proposal["context_pack"]["artifact_hashes"]["evidence_pack"] == (
        result["artifact_hashes"]["evidence_pack"]
    )
    assert proposal["context_pack"]["implementation_plan_hash"] == (
        result["artifact_hashes"]["implementation_plan"]
    )
    assert proposal["context_pack"]["source_snippets"][0]["evidence_id"] in (
        proposal["evidence_refs"]
    )
    assert review["decision"] == "approve_dry_run"


def test_graph_blocks_proposal_review_when_default_git_binding_is_unavailable(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        proposal_git_binding_factory=lambda: {
            "status": "unavailable",
            "base_revision": None,
            "error": "not inside a Git working tree",
        },
    )
    state = create_initial_state(
        run_id="run_git_binding_unavailable",
        request_id="req_git_binding_unavailable",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    proposal = _artifact_data(store, result, "patch_proposal")
    review = _artifact_data(store, result, "proposal_review")

    assert result["current_stage"] == "blocked"
    assert "dry_run_result" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]
    assert proposal["context_pack"]["git_binding_required"] is True
    assert proposal["context_pack"]["git_binding"]["status"] == "unavailable"
    assert review["decision"] == "revise_proposal"
    assert any(
        finding["message"]
        == "Proposal context_pack is missing Git base revision binding."
        for finding in review["findings"]
    )


def test_langgraph_artifact_loop_can_resume_after_human_review_approval(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    checkpoint_store = WorkflowCheckpointStore(store)
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
        interrupt_after=["review_proposal"],
        require_review_approval_for_dry_run=True,
    )
    config = {"configurable": {"thread_id": "gtfo_vslice_001a_review_resume"}}
    state = create_initial_state(
        run_id="run_gtfo_vslice_001a_review_resume",
        request_id="req_gtfo_vslice_001a_review_resume",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    interrupted = graph.invoke(state, config)

    assert interrupted["current_stage"] == "proposal_review"
    assert interrupted["review_summary"]["allowed_next_stage"] == "dry_run_apply"
    assert interrupted["approvals"] == {}
    assert "evidence_pack" in interrupted["artifacts"]
    assert "implementation_plan" in interrupted["artifacts"]
    assert "patch_proposal" in interrupted["artifacts"]
    assert "proposal_review" in interrupted["artifacts"]
    assert "dry_run_result" not in interrupted["artifacts"]
    assert "workflow_summary" not in interrupted["artifacts"]
    graph_snapshot = graph.get_state(config)
    assert graph_snapshot.next == ("dry_run_apply",)

    checkpoint_ref = checkpoint_store.create_checkpoint(
        interrupted,
        interrupt_reason="proposal review requires human approval before dry run",
        resume_allowed_fields=("approvals.review",),
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    payload = ResumePayload(
        resume_id="resume_gtfo_vslice_001a_review",
        run_id="run_gtfo_vslice_001a_review_resume",
        stage="proposal_review",
        decision="approve",
        approved_by="human",
        approved_at="2026-07-09T00:00:00Z",
        artifact_refs=tuple(interrupted["artifacts"].values()),
        diff_hash=checkpoint["resume_binding"]["diff_hash"],
        notes="Approve evidence-bound proposal for controlled dry run.",
    )

    decision, resume_report_ref = checkpoint_store.resume(checkpoint_ref, payload)
    resumed_state = resumed_state_from_decision(
        decision,
        resume_report_ref=resume_report_ref,
    )
    resume_config = graph.update_state(
        config,
        resumed_state,
        as_node="review_proposal",
    )
    result = graph.invoke(None, resume_config)

    assert decision.allowed is True
    assert resumed_state["approvals"]["review"] is True
    assert resumed_state["artifacts"]["resume_report"] == resume_report_ref.path
    assert result["current_stage"] == "done"
    assert result["approvals"]["review"] is True
    assert "resume_report" in result["artifacts"]
    assert "dry_run_result" in result["artifacts"]
    assert "build_result" in result["artifacts"]
    assert "runtime_evidence" in result["artifacts"]
    assert "eval_report" in result["artifacts"]
    assert "workflow_summary" in result["artifacts"]
    assert result["evidence_summary"]["can_generate_patch"] is True
    assert result["review_summary"]["allowed_next_stage"] == "dry_run_apply"
    assert result["review_summary"]["critic_gate"]["state"] == "not_required"

    evidence_pack = _artifact_data(store, result, "evidence_pack")
    dry_run = _artifact_data(store, result, "dry_run_result")
    summary = _artifact_data(store, result, "workflow_summary")
    resume_report = store.read(resume_report_ref)["data"]

    assert evidence_pack["readiness"] == "sufficient"
    assert evidence_pack["can_generate_patch"] is True
    assert evidence_pack["authoritative_for_patch"] is True
    assert evidence_pack["identity_schema_version"] == IDENTITY_SCHEMA_VERSION
    assert evidence_pack["identity_field_mapping"] == dict(IDENTITY_FIELD_MAPPING)
    assert evidence_pack["items"][0]["source_type"] == "target_source"
    assert evidence_pack["items"][0]["retrieval_method"] == "symbol_exact"
    assert evidence_pack["items"][0]["authority"] == "mod_agent_deterministic"
    assert evidence_pack["items"][0]["symbol"] == "Load"
    assert dry_run["approved_by_review"] is True
    assert dry_run["human_approval_required"] is True
    assert dry_run["approved_by_human"] is True
    assert summary["artifact_refs"]["resume_report"] == resume_report_ref.path
    assert summary["artifact_refs"]["evidence_pack"] == result["artifacts"]["evidence_pack"]
    assert resume_report["allowed"] is True
    assert resume_report["applied_updates"]["approvals"] == {"review": True}


def test_langgraph_artifact_loop_blocks_dry_run_without_human_review_approval(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        require_review_approval_for_dry_run=True,
    )
    state = create_initial_state(
        run_id="run_gtfo_vslice_001a_missing_review_approval",
        request_id="req_gtfo_vslice_001a_missing_review_approval",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["approvals"] == {}
    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" in result["artifacts"]
    assert "patch_proposal" in result["artifacts"]
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "eval_report" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]

    dry_run_envelope = store.read(_artifact_ref(store, result, "dry_run_result"))
    dry_run = dry_run_envelope["data"]

    assert dry_run_envelope["status"] == "blocked"
    assert dry_run["approved_by_review"] is True
    assert dry_run["human_approval_required"] is True
    assert dry_run["approved_by_human"] is False
    assert any(blocker["code"] == "REVIEW_NOT_APPROVED" for blocker in result["blockers"])


def test_langgraph_artifact_loop_blocks_success_after_human_review_rejection(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    checkpoint_store = WorkflowCheckpointStore(store)
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
        interrupt_after=["review_proposal"],
        require_review_approval_for_dry_run=True,
    )
    config = {"configurable": {"thread_id": "gtfo_vslice_001a_review_reject"}}
    state = create_initial_state(
        run_id="run_gtfo_vslice_001a_review_reject",
        request_id="req_gtfo_vslice_001a_review_reject",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )
    interrupted = graph.invoke(state, config)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        interrupted,
        interrupt_reason="proposal review requires human approval before dry run",
        resume_allowed_fields=("approvals.review",),
    )
    checkpoint = store.read(checkpoint_ref)["data"]
    payload = ResumePayload(
        resume_id="resume_gtfo_vslice_001a_reject",
        run_id="run_gtfo_vslice_001a_review_reject",
        stage="proposal_review",
        decision="reject",
        approved_by="human",
        approved_at="2026-07-09T00:00:00Z",
        artifact_refs=tuple(interrupted["artifacts"].values()),
        diff_hash=checkpoint["resume_binding"]["diff_hash"],
        notes="Reject evidence-bound proposal before controlled dry run.",
    )

    decision, resume_report_ref = checkpoint_store.resume(checkpoint_ref, payload)
    resumed_state = resumed_state_from_decision(
        decision,
        resume_report_ref=resume_report_ref,
    )
    resume_config = graph.update_state(
        config,
        resumed_state,
        as_node="review_proposal",
    )
    result = graph.invoke(None, resume_config)

    assert decision.allowed is True
    assert "review" not in resumed_state["approvals"]
    assert result["current_stage"] == "blocked"
    assert "resume_report" in result["artifacts"]
    assert "dry_run_result" in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "eval_report" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]

    dry_run_envelope = store.read(_artifact_ref(store, result, "dry_run_result"))
    dry_run = dry_run_envelope["data"]
    resume_report = store.read(resume_report_ref)["data"]

    assert dry_run_envelope["status"] == "blocked"
    assert dry_run["approved_by_review"] is True
    assert dry_run["human_approval_required"] is True
    assert dry_run["approved_by_human"] is False
    assert resume_report["allowed"] is True
    assert resume_report["decision"] == "reject"
    assert resume_report["applied_updates"]["decision"] == "reject"
    assert any(blocker["code"] == "REVIEW_NOT_APPROVED" for blocker in result["blockers"])


def test_langgraph_dynamic_review_interrupt_resumes_with_command_after_approval(
    tmp_path: Path,
) -> None:
    from langgraph.types import Command

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
        enable_dynamic_review_interrupt=True,
        require_review_approval_for_dry_run=True,
    )
    config = {"configurable": {"thread_id": "gtfo_vslice_001a_dynamic_review"}}
    state = create_initial_state(
        run_id="run_gtfo_vslice_001a_dynamic_review",
        request_id="req_gtfo_vslice_001a_dynamic_review",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    interrupted = graph.invoke(state, config)

    assert "__interrupt__" in interrupted
    assert interrupted["current_stage"] == "proposal_review"
    assert "proposal_review" in interrupted["artifacts"]
    assert "dry_run_result" not in interrupted["artifacts"]
    request = interrupted["__interrupt__"][0].value
    assert request["stage"] == "proposal_review"
    assert request["reason"] == "proposal review requires human approval before dry run"
    assert request["resume_allowed_fields"] == ["approvals.review"]
    assert request["payload"]["node_name"] == "human_review_gate"
    assert request["payload"]["resume_binding"]["diff_hash"].startswith("sha256:")
    assert "dry_run_result" not in request["artifact_refs"]
    assert _revision_count(tmp_path, request["feature_id"], "workflow_checkpoint") == 0
    assert _revision_count(tmp_path, request["feature_id"], "resume_report") == 0
    assert _revision_count(tmp_path, request["feature_id"], "dry_run_result") == 0
    snapshot = graph.get_state(config)
    assert snapshot.next == ("human_review_gate",)

    result = graph.invoke(
        Command(
            resume={
                "resume_id": "resume_gtfo_vslice_001a_dynamic_review",
                "run_id": "run_gtfo_vslice_001a_dynamic_review",
                "stage": "proposal_review",
                "decision": "approve",
                "approved_by": "human",
                "approved_at": "2026-07-09T00:00:00Z",
                "artifact_refs": request["artifact_refs"],
                "diff_hash": request["payload"]["resume_binding"]["diff_hash"],
                "notes": "Approve dynamic interrupt path before controlled dry run.",
            }
        ),
        config,
    )

    assert result["current_stage"] == "done"
    assert result["approvals"]["review"] is True
    assert "workflow_checkpoint" in result["artifacts"]
    assert "resume_report" in result["artifacts"]
    assert "dry_run_result" in result["artifacts"]
    assert "workflow_summary" in result["artifacts"]

    checkpoint = _artifact_data(store, result, "workflow_checkpoint")
    resume_report = _artifact_data(store, result, "resume_report")
    dry_run = _artifact_data(store, result, "dry_run_result")
    summary = _artifact_data(store, result, "workflow_summary")

    assert checkpoint["checkpoint_stage"] == "proposal_review"
    assert checkpoint["resume_binding"]["diff_hash"] == request["payload"]["resume_binding"]["diff_hash"]
    assert resume_report["allowed"] is True
    assert resume_report["decision"] == "approve"
    assert resume_report["applied_updates"]["approvals"] == {"review": True}
    assert dry_run["human_approval_required"] is True
    assert dry_run["approved_by_human"] is True
    assert summary["artifact_refs"]["resume_report"] == result["artifacts"]["resume_report"]
    assert _revision_count(tmp_path, result["feature_id"], "workflow_checkpoint") == 1
    assert _revision_count(tmp_path, result["feature_id"], "resume_report") == 1
    assert _revision_count(tmp_path, result["feature_id"], "dry_run_result") == 1


def test_langgraph_dynamic_review_interrupt_rejection_blocks_success_artifacts(
    tmp_path: Path,
) -> None:
    from langgraph.types import Command

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
        enable_dynamic_review_interrupt=True,
        require_review_approval_for_dry_run=True,
    )
    config = {"configurable": {"thread_id": "gtfo_vslice_001a_dynamic_reject"}}
    state = create_initial_state(
        run_id="run_gtfo_vslice_001a_dynamic_reject",
        request_id="req_gtfo_vslice_001a_dynamic_reject",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    interrupted = graph.invoke(state, config)
    request = interrupted["__interrupt__"][0].value
    result = graph.invoke(
        Command(
            resume={
                "resume_id": "resume_gtfo_vslice_001a_dynamic_reject",
                "run_id": "run_gtfo_vslice_001a_dynamic_reject",
                "stage": "proposal_review",
                "decision": "reject",
                "approved_by": "human",
                "approved_at": "2026-07-09T00:00:00Z",
                "artifact_refs": request["artifact_refs"],
                "diff_hash": request["payload"]["resume_binding"]["diff_hash"],
                "notes": "Reject dynamic interrupt path before controlled dry run.",
            }
        ),
        config,
    )

    assert result["current_stage"] == "blocked"
    assert "review" not in result["approvals"]
    assert "workflow_checkpoint" in result["artifacts"]
    assert "resume_report" in result["artifacts"]
    assert "dry_run_result" in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "eval_report" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]

    resume_report = _artifact_data(store, result, "resume_report")
    dry_run = _artifact_data(store, result, "dry_run_result")

    assert resume_report["allowed"] is True
    assert resume_report["decision"] == "reject"
    assert resume_report["applied_updates"]["decision"] == "reject"
    assert dry_run["human_approval_required"] is True
    assert dry_run["approved_by_human"] is False
    assert any(blocker["code"] == "REVIEW_NOT_APPROVED" for blocker in result["blockers"])


def test_langgraph_dynamic_review_interrupt_wrong_thread_id_cannot_resume_original(
    tmp_path: Path,
) -> None:
    from langgraph.types import Command

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
        enable_dynamic_review_interrupt=True,
        require_review_approval_for_dry_run=True,
    )
    original_config = {"configurable": {"thread_id": "gtfo_vslice_001a_dynamic_original"}}
    wrong_config = {"configurable": {"thread_id": "gtfo_vslice_001a_dynamic_wrong"}}
    state = create_initial_state(
        run_id="run_gtfo_vslice_001a_dynamic_wrong_thread",
        request_id="req_gtfo_vslice_001a_dynamic_wrong_thread",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    interrupted = graph.invoke(state, original_config)
    request = interrupted["__interrupt__"][0].value

    try:
        wrong_result = graph.invoke(
            Command(
                resume={
                    "resume_id": "resume_gtfo_vslice_001a_dynamic_wrong_thread",
                    "run_id": "run_gtfo_vslice_001a_dynamic_wrong_thread",
                    "stage": "proposal_review",
                    "decision": "approve",
                    "approved_by": "human",
                    "approved_at": "2026-07-09T00:00:00Z",
                    "artifact_refs": request["artifact_refs"],
                    "diff_hash": request["payload"]["resume_binding"]["diff_hash"],
                    "notes": "Attempt to resume with a different thread id.",
                }
            ),
            wrong_config,
        )
    except KeyError as exc:
        assert exc.args == ("run_id",)
        wrong_result = None

    original_snapshot = graph.get_state(original_config)
    wrong_snapshot = graph.get_state(wrong_config)

    assert original_snapshot.next == ("human_review_gate",)
    assert wrong_snapshot.next == ("plan_request",)
    if wrong_result is not None:
        assert "dry_run_result" not in wrong_result.get("artifacts", {})
        assert "build_result" not in wrong_result.get("artifacts", {})
        assert "runtime_evidence" not in wrong_result.get("artifacts", {})
        assert "eval_report" not in wrong_result.get("artifacts", {})
        assert "workflow_summary" not in wrong_result.get("artifacts", {})
    assert _revision_count(tmp_path, request["feature_id"], "workflow_checkpoint") == 0
    assert _revision_count(tmp_path, request["feature_id"], "resume_report") == 0
    assert _revision_count(tmp_path, request["feature_id"], "dry_run_result") == 0
    assert _revision_count(tmp_path, request["feature_id"], "build_result") == 0
    assert _revision_count(tmp_path, request["feature_id"], "runtime_evidence") == 0
    assert _revision_count(tmp_path, request["feature_id"], "eval_report") == 0
    assert _revision_count(tmp_path, request["feature_id"], "workflow_summary") == 0


def test_missing_knowledge_routes_to_blocked_after_evidence(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(store)
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_domain="gtfo",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    assert "proposal_review" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "isolated_apply_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "eval_report" not in result["artifacts"]
    assert "repair_plan" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["evidence_summary"]["missing_evidence"]
    assert result["evidence_summary"]["timing"]["final_count"] == 0.0
    assert result["blockers"]
    implementation = _artifact_data(store, result, "implementation_plan")
    assert implementation["blocking"] is True
    assert implementation["proposed_changes"] == []
    assert implementation["blockers"]
    blocked_envelope = store.read(_artifact_ref(store, result, "blocked_report"))
    blocked_report = blocked_envelope["data"]
    assert blocked_envelope["status"] == "blocked"
    assert blocked_report["message"] == (
        "Workflow stopped at the blocked terminal stage."
    )
    assert blocked_report["blockers"] == result["blockers"]
    assert blocked_report["upstream_artifacts"]["evidence_pack"] == {
        "path": result["artifacts"]["evidence_pack"],
        "artifact_hash": result["artifact_hashes"]["evidence_pack"],
    }
    assert "No real retrieval" not in blocked_report["message"]


def test_explicit_exact_diff_rejection_is_not_apply_failure(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_rejected_diff",
        request_id="req_rejected_diff",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )
    completed = graph.invoke(state)
    completed["approvals"]["confirmed_write"] = True

    rejected = _run_isolated_apply(
        completed,
        store,
        isolated_apply_factory=lambda *_: (_ for _ in ()).throw(
            ExactDiffApprovalRejectedError("User rejected the displayed exact diff.")
        ),
    )

    apply_envelope = store.read(
        _artifact_ref(store, rejected, "isolated_apply_result")
    )
    assert apply_envelope["status"] == "blocked"
    assert apply_envelope["data"]["execution_mode"] == "rejected"
    assert apply_envelope["data"]["actual_write_performed"] is False
    assert rejected["blockers"][-1]["code"] == "EXACT_DIFF_REJECTED"
    assert all(
        blocker.get("code") != "ISOLATED_APPLY_FAILED"
        for blocker in rejected["blockers"]
    )


def test_stop_after_evidence_ends_before_implementation_plan(tmp_path: Path) -> None:
    pack = EvidencePack(
        query="WallCrawler",
        readiness="partial",
        can_generate_patch=False,
        blockers=(
            {
                "code": "HOOK_BEHAVIOR_UNRESOLVED",
                "message": "Method behavior remains unresolved.",
                "needed_evidence": ["method body"],
            },
        ),
        retrieval_methods_used=("exact_supplied_file_read",),
        timing={"final_count": 0.0},
    )
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        evidence_pack_factory=lambda _state, _feature: pack,
        stop_after_evidence=True,
    )
    state = create_initial_state(
        run_id="run_evidence_only",
        request_id="req_evidence_only",
        user_request="Make GTFO enemy movement use a verified WallCrawler hook.",
        target_domain="gtfo",
        target_mod="WallCrawler",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "evidence_retrieval"
    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" not in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    assert "proposal_review" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]


def test_collection_resolution_failure_routes_to_blocked_after_evidence(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        collection_resolver=CollectionResolver(settings_path=tmp_path / "missing.yaml"),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["evidence_summary"]["can_generate_patch"] is False
    assert "Collection resolution failed" in result["evidence_summary"]["gaps"][0]
    assert result["blockers"][0]["code"] == "INSUFFICIENT_EVIDENCE"
    assert "implementation_plan" in result["artifacts"]
    implementation = store.read(
        _artifact_ref(store, result, "implementation_plan")
    )["data"]
    assert implementation["blocking"] is True
    assert implementation["proposed_changes"] == []


def test_clear_chinese_request_reaches_evidence_then_planning_blocks_patch(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        evidence_pack_factory=lambda _state, feature: EvidencePack.empty(
            query=feature["target_behavior"],
            reason="Current evidence does not identify the requested behavior.",
        ),
    )
    result = graph.invoke(
        create_initial_state(
            run_id="run_bhf_negative",
            request_id="req_bhf_negative",
            user_request=(
                "我想让模组在玩家用枪打到敌人并触发踉跄时，额外显示一个短暂的黄色 X，"
                "并播放一声简短提示音。"
            ),
            target_domain="gtfo",
            target_mod="BetterHitFeedback",
        )
    )

    assert "request_planning_report" in result["artifacts"]
    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    implementation = store.read(
        _artifact_ref(store, result, "implementation_plan")
    )["data"]
    assert implementation["blocking"] is True
    assert implementation["proposed_changes"] == []


def test_rg_live_lexical_pack_commits_blocking_plan_without_patch_generation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "Example" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "public sealed class Behavior\n"
        "{\n"
        "    public void ApplyPinkMarker() { }\n"
        "    public void PreserveNormalFeedback() { }\n"
        "}\n",
        encoding="utf-8",
    )
    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="pink marker preserve normal feedback",
        search_root="generated_mods/Example",
    )
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        evidence_pack_factory=lambda _state, _feature: pack,
    )

    result = graph.invoke(
        create_initial_state(
            run_id="run_rg_live_lexical_block",
            request_id="req_rg_live_lexical_block",
            user_request="Make the marker pink while preserving normal feedback.",
            target_mod="Example",
        )
    )

    assert result["current_stage"] == "blocked"
    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    evidence = store.read(_artifact_ref(store, result, "evidence_pack"))["data"]
    implementation = store.read(
        _artifact_ref(store, result, "implementation_plan")
    )["data"]
    assert evidence["items"]
    assert evidence["readiness"] == "insufficient"
    assert evidence["authoritative_for_patch"] is False
    assert implementation["blocking"] is True
    assert implementation["proposed_changes"] == []
    assert implementation["blockers"][0]["code"] == (
        "RG_LIVE_REQUIREMENT_COVERAGE_UNPROVEN"
    )


def test_vague_request_routes_to_blocked(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="test",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "request_planning_report" in result["artifacts"]
    assert "blocked_report" in result["artifacts"]
    assert result["blockers"]
    assert result["blockers"][0]["stage"] == "request_planning"


def test_graph_trace_contains_node_started_and_finished(tmp_path: Path) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event_types = {event["event_type"] for event in result["trace_events"]}
    assert "node_started" in event_types
    assert "node_finished" in event_types
    assert any(event["node_name"] == "plan_request" for event in result["trace_events"])
    assert any(event["node_name"] == "done" for event in result["trace_events"])


def test_retrieve_evidence_trace_exposes_pack_summary(tmp_path: Path) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event = _finished_event(result, "retrieve_evidence")
    assert event["status"] == "success"
    assert event["artifact_refs"] == [result["artifacts"]["evidence_pack"]]
    assert event["details"]["readiness"] == "sufficient"
    assert event["details"]["can_generate_patch"] is True
    assert event["details"]["retrieval_methods_used"] == [
        "symbol_exact",
        "text_match",
    ]
    assert event["details"]["missing_evidence_count"] == 0
    assert event["details"]["disabled_modes"]["bm25"]
    assert event["details"]["timing"]["final_count"] == 2.0


def test_retrieve_evidence_trace_records_blocked_summary(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event = _finished_event(result, "retrieve_evidence")
    assert event["status"] == "blocked"
    assert event["details"]["readiness"] == "insufficient"
    assert event["details"]["can_generate_patch"] is False
    assert event["details"]["missing_evidence_count"] > 0
    assert event["details"]["timing"]["final_count"] == 0.0


def test_graph_writes_artifacts_through_store(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(store, knowledge_database=_knowledge_with_load_symbol(tmp_path))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    refs = store.list_feature_artifacts(result["feature_id"])
    artifact_types = {ref.artifact_type for ref in refs}
    assert "feature_spec" in artifact_types
    assert "workflow_summary" in artifact_types
    assert set(result["artifacts"]).issubset(artifact_types)


def test_graph_retrieve_evidence_can_use_injected_dense_provider(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    knowledge_database = _knowledge_with_dense_chunk(tmp_path)
    stable_version = knowledge_database.stable_index_version("knowledge_hub")
    assert stable_version is not None
    chunks = knowledge_database.list_chunks(
        collection_id="knowledge_hub",
        index_version=stable_version.index_version,
    )
    assert chunks
    graph = build_graph(
        store,
        knowledge_database=knowledge_database,
        dense_enabled=True,
        dense_provider=FakeDenseRetrievalProvider({chunks[0].chunk_id: 0.88}),
        dense_top_k=1,
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make MissingDenseOnly enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    evidence_pack = _artifact_data(store, result, "evidence_pack")
    assert "dense" in evidence_pack["retrieval_methods_used"]
    assert evidence_pack["items"][0]["retrieval_method"] == "dense"
    assert evidence_pack["items"][0]["chunk_id"] == chunks[0].chunk_id


def test_approved_path_writes_explicit_fake_execution_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(store, knowledge_database=_knowledge_with_load_symbol(tmp_path))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    dry_run = _artifact_data(store, result, "dry_run_result")
    build = _artifact_data(store, result, "build_result")
    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")
    summary = _artifact_data(store, result, "workflow_summary")

    assert dry_run["execution_mode"] == "fake"
    assert dry_run["actual_write_performed"] is False
    assert dry_run["real_patch_applied"] is False
    assert build["execution_mode"] == "fake"
    assert build["status"] == "skipped"
    assert build["real_build_performed"] is False
    assert build["build_status"] == "fake_completed"
    assert build["claims_real_build_success"] is False
    assert build["repair_handoff"]["allowed"] is False
    assert runtime["execution_mode"] == "fake"
    assert runtime["runtime_status"] == "verified"
    assert runtime["verification_status"] == "verified"
    assert runtime["acceptance_status"] == "accepted"
    assert runtime["acceptance_verified"] is True
    assert runtime["startup_loaded"] is True
    assert runtime["gameplay_behavior_verified"] is True
    assert runtime["real_runtime_performed"] is False
    assert runtime["raw_supplied_output"] is None
    assert runtime["claims_real_runtime_success"] is False
    assert runtime["acceptance_contract"]["acceptance_criteria"]
    assert evaluation["workflow_completion_status"] == "fake_execution_completed"
    assert evaluation["requested_behavior_status"] == "verified"
    assert evaluation["verdict"] == "inconclusive"
    assert evaluation["claims_real_success"] is False
    assert evaluation["evaluation_gate"]["status"] == "passed"
    assert {
        case["case_id"] for case in evaluation["evaluation_gate"]["cases"]
    } >= {
        "claim_boundary_no_false_success",
        "claim_boundary_no_false_block",
        "false_continue_after_review",
        "review_correctness",
        "dry_run_safety",
        "build_claim_boundary",
        "runtime_claim_boundary",
    }
    assert evaluation["v1_acceptance_status"] == "blocked"
    assert {
        blocker["code"] for blocker in evaluation["v1_acceptance_blockers"]
    } == {
        "REAL_BUILD_EVIDENCE_MISSING",
        "REAL_RUNTIME_MODE_REQUIRED",
        "REAL_RUNTIME_EVIDENCE_MISSING",
        "REAL_RUNTIME_SUCCESS_NOT_CLAIMED",
    }
    assert evaluation["input_acceptance_status"] == "accepted"
    assert evaluation["input_acceptance_verified"] is True
    assert evaluation["acceptance_contract"] == runtime["acceptance_contract"]
    assert summary["workflow_completion_status"] == "fake_execution_completed"
    assert summary["requested_behavior_status"] == "verified"
    assert summary["final_status"] == "inconclusive"
    assert summary["claims_real_mod_success"] is False
    assert summary["claims_real_build_success"] is False
    assert summary["claims_real_runtime_success"] is False
    assert summary["v1_acceptance_status"] == "blocked"
    assert summary["v1_acceptance_blockers"] == evaluation["v1_acceptance_blockers"]


def test_real_runtime_evidence_path_can_accept_v1_boundary(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="runtime_probe",
                    locator="runtime://probe-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime probe observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime probe observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding=_plugin_marker_binding(criteria),
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
    )
    state = create_initial_state(
        run_id="run_real_runtime",
        request_id="req_real_runtime",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    build = _artifact_data(store, result, "build_result")
    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")
    summary = _artifact_data(store, result, "workflow_summary")

    assert result["current_stage"] == "done"
    assert build["execution_mode"] == "local"
    assert build["claims_real_build_success"] is True
    assert runtime["execution_mode"] == "real"
    assert runtime["real_runtime_performed"] is True
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["acceptance_verified"] is True
    assert runtime["run_id"] == "run_real_runtime"
    assert runtime["build_artifact_ref"]["artifact_type"] == "build_result"
    assert runtime["build_artifact_hash"] == result["artifact_hashes"]["build_result"]
    assert runtime["plugin_marker_binding"]["markers"]
    assert evaluation["v1_acceptance_status"] == "accepted"
    assert evaluation["v1_acceptance_blockers"] == []
    assert evaluation["evaluation_gate"]["status"] == "passed"
    assert evaluation["workflow_completion_status"] == "real_runtime_acceptance_completed"
    assert evaluation["verdict"] == "accepted"
    assert evaluation["claims_real_success"] is True
    assert summary["final_status"] == "accepted"
    assert summary["claims_real_mod_success"] is True
    assert summary["claims_real_build_success"] is True
    assert summary["claims_real_runtime_success"] is True


def test_structured_runtime_diagnosis_routes_to_binding_gap_before_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    calls = {"binding_resolution": 0, "runtime_repair": 0}
    original_runtime_repair = RepairPlanner.from_runtime_failure

    def tracked_binding_resolution(**kwargs):
        calls["binding_resolution"] += 1
        return resolve_runtime_diagnosis_binding(**kwargs)

    def tracked_runtime_repair(self, **kwargs):
        calls["runtime_repair"] += 1
        return original_runtime_repair(self, **kwargs)

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph.resolve_runtime_diagnosis_binding",
        tracked_binding_resolution,
    )
    monkeypatch.setattr(
        RepairPlanner,
        "from_runtime_failure",
        tracked_runtime_repair,
    )

    def diagnosed_runtime_failure(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        payload = build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(),
            startup_loaded=True,
            gameplay_behavior_verified=False,
            verification_status="failed",
            raw_runtime_output=(
                "signal=STAGGER_FEEDBACK_SKIPPED "
                "visual_spawned=False "
                "visual_reason=missing_canvas_rect_for_stagger_x"
            ),
            acceptance_criteria=tuple(
                str(item)
                for item in feature_spec["acceptance_criteria"]
            ),
            runtime_verification_plan=tuple(
                str(item)
                for item in feature_spec["runtime_verification_plan"]
            ),
            failure_ownership={
                "owner": "product_behavior",
                "failure_class": "product_behavior",
                "source_repair_allowed": True,
                "required_action": "repair_product_behavior",
                "reason": "A bound product criterion is false.",
            },
        )
        payload["runtime_failure_diagnosis"] = {
            "schema_version": "stagger_runtime_failure_diagnosis_v1",
            "status": "diagnosed",
            "feature_id": feature_id,
            "failure_class": "product_behavior",
            "evidence_refs": [
                {
                    "source": "gtfo_persistent_log",
                    "locator": "BepInEx/LogOutput.log",
                }
            ],
            "responsibility_anchors": {
                "component": "ui_attachment",
                "symbol": (
                    "BetterHitFeedback.Patches."
                    "HitFeedbackBehaviorPatch.TrySpawnStaggerYellowX"
                ),
                "dependency": "HUD RectTransform",
                "repair_scope": ["canvas_binding"],
                "source_hash": None,
                "source_span": None,
            },
            "root_cause_status": "unresolved",
            "unresolved_root_causes": [
                "hud_parent_runtime_type_mismatch"
            ],
        }
        return payload

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        runtime_evidence_factory=diagnosed_runtime_failure,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
    )
    config = {"configurable": {"thread_id": "runtime_binding_gap_replay"}}
    state = create_initial_state(
        run_id="run_binding_gap",
        request_id="req_binding_gap",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state, config)
    resolution = _artifact_data(store, result, "binding_resolution")

    assert result["current_stage"] == "blocked"
    assert resolution["result_type"] == "binding_gap"
    assert resolution["binding_gap"]["gap"] is True
    assert resolution["binding_proposal_request"]["status"] == "requested"
    assert resolution["binding_proposal_request"]["repair_allowed"] is False
    assert "repair_plan" not in result["artifacts"]
    assert "binding_resolution" in result["artifacts"]
    assert result["blockers"][0]["code"] == "BINDING_GAP"
    assert any(
        event["node_name"] == "resolve_runtime_binding"
        and event["event_type"] == "node_finished"
        and event["status"] == "blocked"
        for event in result["trace_events"]
    )
    assert calls == {"binding_resolution": 1, "runtime_repair": 0}
    assert len(
        store.list_feature_artifact_revisions(
            result["feature_id"],
            "binding_resolution",
        )
    ) == 1

    replayed = graph.invoke(None, config)

    assert replayed["artifacts"]["binding_resolution"] == (
        result["artifacts"]["binding_resolution"]
    )
    assert replayed["artifact_hashes"]["binding_resolution"] == (
        result["artifact_hashes"]["binding_resolution"]
    )
    assert "repair_plan" not in replayed["artifacts"]
    assert calls == {"binding_resolution": 1, "runtime_repair": 0}
    assert len(
        store.list_feature_artifact_revisions(
            result["feature_id"],
            "binding_resolution",
        )
    ) == 1


def test_resolved_runtime_binding_is_the_only_target_consumed_by_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"binding_resolution": 0, "runtime_repair": 0}
    original_runtime_repair = RepairPlanner.from_runtime_failure

    def tracked_binding_resolution(**kwargs):
        calls["binding_resolution"] += 1
        return resolve_runtime_diagnosis_binding(**kwargs)

    def tracked_runtime_repair(self, **kwargs):
        calls["runtime_repair"] += 1
        return original_runtime_repair(self, **kwargs)

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph.resolve_runtime_diagnosis_binding",
        tracked_binding_resolution,
    )
    monkeypatch.setattr(
        RepairPlanner,
        "from_runtime_failure",
        tracked_runtime_repair,
    )
    knowledge = _knowledge_with_load_symbol(
        tmp_path,
        root_name="resolved_binding_source",
    )
    baseline_store = ArtifactStore(tmp_path / "baseline_artifacts")
    baseline = build_graph(
        baseline_store,
        knowledge_database=knowledge,
    ).invoke(
        create_initial_state(
            run_id="run_binding_baseline",
            request_id="req_binding_baseline",
            user_request="make Load enable diagnostics",
            target_mod="BetterHitFeedback",
        )
    )
    binding = _artifact_data(
        baseline_store,
        baseline,
        "implementation_plan",
    )["binding_registry"]["edit_bindings"][0]

    def diagnosed_runtime_failure(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        payload = build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(),
            startup_loaded=True,
            gameplay_behavior_verified=False,
            verification_status="failed",
            acceptance_criteria=tuple(
                str(item)
                for item in feature_spec["acceptance_criteria"]
            ),
            runtime_verification_plan=tuple(
                str(item)
                for item in feature_spec["runtime_verification_plan"]
            ),
            failure_ownership={
                "owner": "product_behavior",
                "failure_class": "product_behavior",
                "source_repair_allowed": True,
                "required_action": "repair_product_behavior",
                "reason": "A bound product criterion is false.",
            },
        )
        payload["runtime_failure_diagnosis"] = {
            "schema_version": "runtime_failure_diagnosis_v1",
            "status": "diagnosed",
            "feature_id": feature_id,
            "failure_class": "product_behavior",
            "evidence_refs": [
                {
                    "source": "runtime_probe",
                    "locator": "runtime://load",
                }
            ],
            "responsibility_anchors": {
                "component": "plugin_load",
                "symbol": binding["target_symbol"],
                "dependency": "ConfigEnabled",
                "repair_scope": ["configuration_gate"],
                "source_hash": binding["source_hash"],
                "source_span": binding["target_span"],
            },
            "root_cause_status": "unresolved",
            "unresolved_root_causes": [
                "configuration_gate_state_unknown"
            ],
        }
        return payload

    store = ArtifactStore(tmp_path / "resolved_artifacts")
    graph = build_graph(
        store,
        knowledge_database=knowledge,
        runtime_evidence_factory=diagnosed_runtime_failure,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
    )
    config = {"configurable": {"thread_id": "runtime_binding_resolved_replay"}}
    result = graph.invoke(
        create_initial_state(
            run_id="run_binding_resolved",
            request_id="req_binding_resolved",
            user_request="make Load enable diagnostics",
            target_mod="BetterHitFeedback",
        ),
        config,
    )
    resolution = _artifact_data(store, result, "binding_resolution")
    repair = _artifact_data(store, result, "repair_plan")

    assert resolution["result_type"] == "resolved_repair_target"
    assert resolution["resolved_repair_target"]["binding_id"] == (
        binding["binding_id"]
    )
    assert repair["minimal_changes"][0]["edit_binding_id"] == (
        binding["binding_id"]
    )
    assert repair["allowed_edit_binding_ids"] == [binding["binding_id"]]
    assert repair["blockers"][0]["code"] == (
        "RUNTIME_ROOT_CAUSE_UNRESOLVED"
    )
    assert result["current_stage"] == "blocked"
    assert calls == {"binding_resolution": 1, "runtime_repair": 1}
    assert len(
        store.list_feature_artifact_revisions(
            result["feature_id"],
            "binding_resolution",
        )
    ) == 1
    assert len(
        store.list_feature_artifact_revisions(
            result["feature_id"],
            "repair_plan",
        )
    ) == 1

    replayed = graph.invoke(None, config)

    assert replayed["artifacts"]["binding_resolution"] == (
        result["artifacts"]["binding_resolution"]
    )
    assert replayed["artifact_hashes"]["binding_resolution"] == (
        result["artifact_hashes"]["binding_resolution"]
    )
    assert replayed["artifacts"]["repair_plan"] == (
        result["artifacts"]["repair_plan"]
    )
    assert replayed["artifact_hashes"]["repair_plan"] == (
        result["artifact_hashes"]["repair_plan"]
    )
    assert calls == {"binding_resolution": 1, "runtime_repair": 1}
    assert len(
        store.list_feature_artifact_revisions(
            result["feature_id"],
            "binding_resolution",
        )
    ) == 1
    assert len(
        store.list_feature_artifact_revisions(
            result["feature_id"],
            "repair_plan",
        )
    ) == 1


def test_gtfo_runtime_factory_from_settings_can_feed_graph_runtime_branch(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)
    requested_behavior = "make Load enable diagnostics"
    acceptance_criteria = (
        f"Requested behavior is implemented: {requested_behavior}",
        "Every proposed change is bound to evidence.",
        "Validation output is reported with real command or artifact evidence.",
    )
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"fake exe for path validation")
    config_path = tmp_path / "BepInEx" / "config" / "BepInEx.cfg"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[Logging.Disk]\nAppendLog = false\n",
        encoding="utf-8",
    )
    acceptance_markers = {
        acceptance_criteria[0]: "GTFO_ACCEPTANCE_BEHAVIOR",
        acceptance_criteria[1]: "GTFO_ACCEPTANCE_EVIDENCE",
        acceptance_criteria[2]: "GTFO_ACCEPTANCE_VALIDATION",
    }
    settings = SimpleNamespace(
        runtime=SimpleNamespace(
            gtfo=SimpleNamespace(
                enabled=True,
                game_executable=str(executable),
                working_directory=str(tmp_path),
                launch_args=[],
                log_paths=["BepInEx/LogOutput.log"],
                screenshot_directory=str(tmp_path / "screenshots"),
                screenshot_timeout_seconds=5,
                startup_markers=["BEPINEX_CHAINLOADER_READY"],
                acceptance_markers=acceptance_markers,
                timeout_seconds=10,
                poll_interval_seconds=0.01,
                output_limit_chars=4096,
                terminate_after_capture=False,
            )
        )
    )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=make_gtfo_runtime_evidence_factory_from_settings(
            settings,
            allow_game_launch=True,
            process_launcher=lambda _: GTFOProcessHandle(pid=4242),
            log_collector=lambda _, __: GTFOLogSnapshot(
                content=(
                    "BEPINEX_CHAINLOADER_READY\n"
                    "GTFO_ACCEPTANCE_BEHAVIOR\n"
                    "GTFO_ACCEPTANCE_EVIDENCE\n"
                    "GTFO_ACCEPTANCE_VALIDATION\n"
                ),
                sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
            ),
            screenshot_capturer=lambda _, feature_id: build_screenshot_metadata(
                screenshot_id="gtfo_graph_shot",
                feature_id=feature_id,
                file_path=str(tmp_path / "screenshots" / "feature_001.png"),
                source="desktop_screenshot",
                content_hash="hash_gtfo_graph_shot",
            ),
        ),
    )
    state = create_initial_state(
        run_id="run_gtfo_runtime_settings",
        request_id="req_gtfo_runtime_settings",
        user_request=requested_behavior,
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")
    summary = _artifact_data(store, result, "workflow_summary")

    assert result["current_stage"] == "done"
    assert runtime["execution_mode"] == "real"
    assert runtime["evidence_source"] == "gtfo_real_runtime_automation"
    assert runtime["real_runtime_performed"] is True
    assert runtime["acceptance_verified"] is True
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["run_id"] == "run_gtfo_runtime_settings"
    assert runtime["build_artifact_hash"] == result["artifact_hashes"]["build_result"]
    assert runtime["screenshot_refs"] == [runtime["screenshot"]]
    assert runtime["runtime_trust_binding"]["status"] == "trusted"
    assert runtime["runtime_trust_binding"]["checks"]["run_id"] == {
        "status": "passed",
        "run_id": "run_gtfo_runtime_settings",
    }
    assert runtime["runtime_trust_binding"]["checks"]["build_artifact_hash"] == {
        "status": "passed",
        "build_artifact_hash": result["artifact_hashes"]["build_result"],
        "build_artifact_ref_hash": result["artifact_hashes"]["build_result"],
    }
    assert runtime["runtime_process"] == {
        "profile_id": "gtfo_real_runtime",
        "pid": 4242,
        "launched": True,
        "liveness_observed": True,
    }
    assert runtime["gtfo_capability_report"]["status"] == "ready"
    assert runtime["plugin_marker_binding"]["markers"] == [
        {
            "acceptance_criterion": criterion,
            "marker": acceptance_markers[criterion],
            "observed": True,
        }
        for criterion in acceptance_criteria
    ]
    assert evaluation["v1_acceptance_status"] == "accepted"
    assert summary["final_status"] == "accepted"


def test_gtfo_runtime_factory_from_settings_without_launch_approval_blocks_graph_acceptance(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)
    requested_behavior = "make Load enable diagnostics"
    acceptance_criteria = (
        f"Requested behavior is implemented: {requested_behavior}",
        "Every proposed change is bound to evidence.",
        "Validation output is reported with real command or artifact evidence.",
    )
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"fake exe for path validation")
    acceptance_markers = {
        acceptance_criteria[0]: "GTFO_ACCEPTANCE_BEHAVIOR",
        acceptance_criteria[1]: "GTFO_ACCEPTANCE_EVIDENCE",
        acceptance_criteria[2]: "GTFO_ACCEPTANCE_VALIDATION",
    }
    settings = SimpleNamespace(
        runtime=SimpleNamespace(
            gtfo=SimpleNamespace(
                enabled=True,
                game_executable=str(executable),
                working_directory=str(tmp_path),
                launch_args=[],
                log_paths=["BepInEx/LogOutput.log"],
                screenshot_directory=str(tmp_path / "screenshots"),
                screenshot_timeout_seconds=5,
                startup_markers=["BEPINEX_CHAINLOADER_READY"],
                acceptance_markers=acceptance_markers,
                timeout_seconds=10,
                poll_interval_seconds=0.01,
                output_limit_chars=4096,
                terminate_after_capture=False,
            )
        )
    )
    called = {"launcher": False, "collector": False, "capturer": False}

    def launcher(_: object) -> GTFOProcessHandle:
        called["launcher"] = True
        return GTFOProcessHandle(pid=4242)

    def collector(_: object, __: tuple[str, ...]) -> GTFOLogSnapshot:
        called["collector"] = True
        return GTFOLogSnapshot(
            content=(
                "BEPINEX_CHAINLOADER_READY\n"
                "GTFO_ACCEPTANCE_BEHAVIOR\n"
                "GTFO_ACCEPTANCE_EVIDENCE\n"
                "GTFO_ACCEPTANCE_VALIDATION\n"
            ),
            sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
        )

    def capturer(_: object, feature_id: str):
        called["capturer"] = True
        return build_screenshot_metadata(
            screenshot_id="gtfo_graph_shot",
            feature_id=feature_id,
            file_path=str(tmp_path / "screenshots" / "feature_001.png"),
            source="desktop_screenshot",
            content_hash="hash_gtfo_graph_shot",
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=make_gtfo_runtime_evidence_factory_from_settings(
            settings,
            allow_game_launch=False,
            process_launcher=launcher,
            log_collector=collector,
            screenshot_capturer=capturer,
        ),
    )
    state = create_initial_state(
        run_id="run_gtfo_runtime_settings_blocked",
        request_id="req_gtfo_runtime_settings_blocked",
        user_request=requested_behavior,
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    repair_plan = _artifact_data(store, result, "repair_plan")

    assert called == {"launcher": False, "collector": False, "capturer": False}
    assert "workflow_summary" not in result["artifacts"]
    assert result["current_stage"] == "blocked"
    assert runtime["execution_mode"] == "real"
    assert runtime["evidence_source"] == "gtfo_real_runtime_automation"
    assert runtime["real_runtime_performed"] is False
    assert runtime["acceptance_verified"] is False
    assert runtime["claims_real_runtime_success"] is False
    assert runtime["runtime_process"]["launched"] is False
    assert runtime["runtime_trust_binding"]["status"] == "blocked"
    assert runtime["gtfo_capability_report"]["status"] == "blocked"
    assert runtime["gtfo_capability_report"]["checks"]["explicit_launch_approval"] == {
        "status": "blocked",
        "required": True,
        "allow_game_launch": False,
    }
    assert runtime["failure"]["type"] == "GTFORuntimeAutomationError"
    assert result["runtime_summary"]["failure_ownership"]["owner"] == "permission"
    assert repair_plan["repair_context"]["failure_owner"] == "permission"
    assert repair_plan["repair_context"]["source_repair_allowed"] is False
    assert repair_plan["minimal_changes"] == []
    assert repair_plan["retry_count"] == 0
    assert repair_plan["blockers"][0]["code"] == "RUNTIME_PERMISSION_REQUIRED"
    feature_id = result["feature_id"]
    assert _revision_count(tmp_path, feature_id, "patch_proposal") == 1
    assert _revision_count(tmp_path, feature_id, "dry_run_result") == 1
    assert _revision_count(tmp_path, feature_id, "isolated_apply_result") == 0
    assert _revision_count(tmp_path, feature_id, "build_result") == 1
    assert _revision_count(tmp_path, feature_id, "runtime_evidence") == 1
    assert _revision_count(tmp_path, feature_id, "repair_plan") == 1


def test_build_graph_uses_gtfo_runtime_factory_from_enabled_settings(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)
    requested_behavior = "make Load enable diagnostics"
    acceptance_criteria = (
        f"Requested behavior is implemented: {requested_behavior}",
        "Every proposed change is bound to evidence.",
        "Validation output is reported with real command or artifact evidence.",
    )
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"fake exe for path validation")
    settings = SimpleNamespace(
        runtime=SimpleNamespace(
            gtfo=SimpleNamespace(
                enabled=True,
                game_executable=str(executable),
                working_directory=str(tmp_path),
                launch_args=[],
                log_paths=["BepInEx/LogOutput.log"],
                screenshot_directory=str(tmp_path / "screenshots"),
                screenshot_timeout_seconds=5,
                startup_markers=["BEPINEX_CHAINLOADER_READY"],
                acceptance_markers={
                    acceptance_criteria[0]: "GTFO_ACCEPTANCE_BEHAVIOR",
                    acceptance_criteria[1]: "GTFO_ACCEPTANCE_EVIDENCE",
                    acceptance_criteria[2]: "GTFO_ACCEPTANCE_VALIDATION",
                },
                timeout_seconds=10,
                poll_interval_seconds=0.01,
                output_limit_chars=4096,
                terminate_after_capture=False,
            )
        )
    )

    graph = build_graph(
        store,
        settings=settings,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        allow_game_launch=False,
    )
    state = create_initial_state(
        run_id="run_gtfo_runtime_settings_auto_blocked",
        request_id="req_gtfo_runtime_settings_auto_blocked",
        user_request=requested_behavior,
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")

    assert result["current_stage"] == "blocked"
    assert "workflow_summary" not in result["artifacts"]
    assert runtime["evidence_source"] == "gtfo_real_runtime_automation"
    assert runtime["real_runtime_performed"] is False
    assert runtime["acceptance_verified"] is False
    assert runtime["claims_real_runtime_success"] is False
    assert runtime["runtime_process"]["launched"] is False
    assert runtime["runtime_trust_binding"]["status"] == "blocked"
    assert runtime["gtfo_capability_report"]["status"] == "blocked"
    assert runtime["gtfo_capability_report"]["checks"]["explicit_launch_approval"] == {
        "status": "blocked",
        "required": True,
        "allow_game_launch": False,
    }


def test_gtfo_runtime_missing_screenshot_trust_binding_blocks_graph_acceptance(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)
    requested_behavior = "make Load enable diagnostics"
    acceptance_criteria = (
        f"Requested behavior is implemented: {requested_behavior}",
        "Every proposed change is bound to evidence.",
        "Validation output is reported with real command or artifact evidence.",
    )
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"fake exe for path validation")
    config_path = tmp_path / "BepInEx" / "config" / "BepInEx.cfg"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "[Logging.Disk]\nAppendLog = false\n",
        encoding="utf-8",
    )
    acceptance_markers = {
        acceptance_criteria[0]: "GTFO_ACCEPTANCE_BEHAVIOR",
        acceptance_criteria[1]: "GTFO_ACCEPTANCE_EVIDENCE",
        acceptance_criteria[2]: "GTFO_ACCEPTANCE_VALIDATION",
    }
    settings = SimpleNamespace(
        runtime=SimpleNamespace(
            gtfo=SimpleNamespace(
                enabled=True,
                game_executable=str(executable),
                working_directory=str(tmp_path),
                launch_args=[],
                log_paths=["BepInEx/LogOutput.log"],
                screenshot_directory=str(tmp_path / "screenshots"),
                screenshot_timeout_seconds=5,
                startup_markers=["BEPINEX_CHAINLOADER_READY"],
                acceptance_markers=acceptance_markers,
                timeout_seconds=10,
                poll_interval_seconds=0.01,
                output_limit_chars=4096,
                terminate_after_capture=False,
            )
        )
    )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=make_gtfo_runtime_evidence_factory_from_settings(
            settings,
            allow_game_launch=True,
            process_launcher=lambda _: GTFOProcessHandle(pid=4242),
            log_collector=lambda _, __: GTFOLogSnapshot(
                content=(
                    "BEPINEX_CHAINLOADER_READY\n"
                    "GTFO_ACCEPTANCE_BEHAVIOR\n"
                    "GTFO_ACCEPTANCE_EVIDENCE\n"
                    "GTFO_ACCEPTANCE_VALIDATION\n"
                ),
                sources=(str(tmp_path / "BepInEx" / "LogOutput.log"),),
            ),
            screenshot_capturer=lambda _, __: None,
        ),
    )
    state = create_initial_state(
        run_id="run_gtfo_runtime_missing_screenshot",
        request_id="req_gtfo_runtime_missing_screenshot",
        user_request=requested_behavior,
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")

    assert runtime["acceptance_verified"] is True
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["screenshot_refs"] == []
    assert runtime["runtime_trust_binding"]["status"] == "blocked"
    assert (
        runtime["runtime_trust_binding"]["checks"]["screenshot_runtime_artifact_linkage"][
            "status"
        ]
        == "blocked"
    )
    assert result["current_stage"] == "blocked"
    assert "workflow_summary" not in result["artifacts"]
    assert evaluation["v1_acceptance_status"] == "blocked"
    assert {
        "code": "GTFO_RUNTIME_TRUST_BINDING_MISSING",
        "message": (
            "V1 acceptance for GTFO automation requires trusted current-run log, "
            "process, marker, build, and screenshot binding."
        ),
    } in evaluation["v1_acceptance_blockers"]


def test_manual_runtime_evidence_does_not_accept_v1_boundary(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_manual_runtime_evidence_payload(
            feature_id=feature_id,
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="manual_observation",
                    source="manual_runtime_note",
                    locator="manual://note-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Manual verification observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding=_plugin_marker_binding(criteria),
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
    )
    state = create_initial_state(
        run_id="run_manual_runtime",
        request_id="req_manual_runtime",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")

    assert result["current_stage"] == "blocked"
    assert "workflow_summary" not in result["artifacts"]
    assert "blocked_report" in result["artifacts"]
    eval_ref = _artifact_ref(store, result, "eval_report")
    assert store.read(eval_ref)["status"] == "blocked"
    assert runtime["execution_mode"] == "manual"
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["acceptance_verified"] is True
    assert evaluation["v1_acceptance_status"] == "blocked"
    assert evaluation["evaluation_gate"]["status"] == "failed"
    assert {
        blocker["code"] for blocker in result["blockers"]
    } == {
        "EVAL_GATE_RUNTIME_CLAIM_BOUNDARY_EXECUTION_MODE_FAILED",
    }
    assert {
        blocker["code"] for blocker in evaluation["v1_acceptance_blockers"]
    } == {"REAL_RUNTIME_MODE_REQUIRED", "REAL_RUNTIME_EVIDENCE_MISSING"}


def test_eval_gate_insufficient_baseline_blocks_done(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="runtime_probe",
                    locator="runtime://probe-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime probe observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime probe observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding=_plugin_marker_binding(criteria),
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
        evaluation_context_factory=lambda _: {
            "baseline_status": "insufficient_baseline",
        },
    )
    state = create_initial_state(
        run_id="run_eval_baseline",
        request_id="req_eval_baseline",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    evaluation = _artifact_data(store, result, "eval_report")
    eval_ref = _artifact_ref(store, result, "eval_report")
    assert result["current_stage"] == "blocked"
    assert store.read(eval_ref)["status"] == "blocked"
    assert evaluation["evaluation_gate"]["status"] == "failed"
    assert "workflow_summary" not in result["artifacts"]
    assert "blocked_report" in result["artifacts"]
    assert any(
        blocker["code"] == "EVAL_GATE_INSUFFICIENT_BASELINE_FAILED"
        for blocker in result["blockers"]
    )


def test_real_runtime_without_success_claim_does_not_accept_v1_boundary(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        payload = build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="runtime_probe",
                    locator="runtime://probe-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime probe observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime probe observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
        )
        payload["claims_real_runtime_success"] = False
        return payload

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
    )
    state = create_initial_state(
        run_id="run_real_runtime_without_success",
        request_id="req_real_runtime_without_success",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")

    assert runtime["execution_mode"] == "real"
    assert runtime["real_runtime_performed"] is True
    assert runtime["acceptance_verified"] is True
    assert runtime["claims_real_runtime_success"] is False
    assert evaluation["v1_acceptance_status"] == "blocked"
    assert {
        blocker["code"] for blocker in evaluation["v1_acceptance_blockers"]
    } == {"REAL_RUNTIME_SUCCESS_NOT_CLAIMED"}


def test_runtime_probe_factory_can_accept_v1_boundary(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)
    requested_behavior = "make Load enable diagnostics"
    acceptance_criteria = (
        f"Requested behavior is implemented: {requested_behavior}",
        "Every proposed change is bound to evidence.",
        "Validation output is reported with real command or artifact evidence.",
    )
    profile = RuntimeProbeProfile(
        profile_id="graph_runtime_probe",
        working_directory=str(tmp_path),
        command=(
            sys.executable,
            "-c",
            (
                "print('MOD_AGENT_STARTUP_OK'); "
                "print('MOD_AGENT_ACCEPTANCE_BEHAVIOR'); "
                "print('MOD_AGENT_ACCEPTANCE_EVIDENCE'); "
                "print('MOD_AGENT_ACCEPTANCE_VALIDATION')"
            ),
        ),
        timeout_seconds=10,
        startup_markers=("MOD_AGENT_STARTUP_OK",),
        acceptance_markers={
            acceptance_criteria[0]: "MOD_AGENT_ACCEPTANCE_BEHAVIOR",
            acceptance_criteria[1]: "MOD_AGENT_ACCEPTANCE_EVIDENCE",
            acceptance_criteria[2]: "MOD_AGENT_ACCEPTANCE_VALIDATION",
        },
    )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=make_runtime_probe_evidence_factory(
            profile=profile,
            allow_execution=True,
        ),
    )
    state = create_initial_state(
        run_id="run_runtime_probe",
        request_id="req_runtime_probe",
        user_request=requested_behavior,
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")

    assert runtime["execution_mode"] == "real"
    assert runtime["evidence_source"] == "real_runtime_probe"
    assert runtime["real_runtime_performed"] is True
    assert runtime["acceptance_verified"] is True
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["raw_supplied_output"] is not None
    assert runtime["run_id"] == "run_runtime_probe"
    assert runtime["build_artifact_hash"] == result["artifact_hashes"]["build_result"]
    assert len(runtime["plugin_marker_binding"]["markers"]) == len(acceptance_criteria)
    assert evaluation["v1_acceptance_status"] == "accepted"
    assert evaluation["v1_acceptance_blockers"] == []


def test_review_block_does_not_create_fake_success_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    knowledge_database = _knowledge_with_load_symbol(tmp_path)
    policy = build_gtfo_profile(tmp_path).review_policy()
    graph = build_graph(
        store,
        knowledge_database=knowledge_database,
        domain_review_policy=policy,
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_domain="gtfo",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["review_summary"]["allowed_next_stage"] is None
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "isolated_apply_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "eval_report" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]
    source = knowledge_database.list_sources()[0]
    evidence = _artifact_data(store, result, "evidence_pack")
    proposal = _artifact_data(store, result, "patch_proposal")
    review = _artifact_data(store, result, "proposal_review")
    assert Path(source.root_path) == (tmp_path / "source").resolve()
    assert {item["source_path"] for item in evidence["items"]} == {"Plugin.cs"}
    assert proposal["files"] == ["Plugin.cs"]
    assert review["decision"] == "blocked_scope_risk"
    assert any(
        finding["rule_id"] == "scope_boundary" for finding in review["findings"]
    )


def test_default_graph_uses_domain_policy_for_unsupported_domain(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_domain_policy",
        request_id="req_domain_policy",
        user_request="default config Load runtime diagnostics",
        target_domain="unsupported",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    request_plan = _artifact_data(store, result, "request_planning_report")
    feature_spec = _artifact_data(store, result, "feature_spec")
    proposal = _artifact_data(store, result, "patch_proposal")
    assert request_plan["route"] == "quick_patch"
    assert request_plan["requires_hook_evidence"] is False
    assert request_plan["hook_requirement"] == {
        "required": False,
        "reason": "not_required",
    }
    assert feature_spec["hook_requirement"] == {
        "required": False,
        "reason": "not_required",
    }
    assert proposal["risk_assessment"]["risk_level"] == "high"
    assert result["review_summary"]["allowed_next_stage"] is None
    assert any(blocker["code"] == "DOMAIN_PROFILE" for blocker in result["blockers"])
    review = _artifact_data(store, result, "proposal_review")
    assert review["decision"] == "blocked_requires_human"
    assert any(finding["rule_id"] == "domain_profile" for finding in review["findings"])


def test_graph_uses_explicit_bound_domain_policy_for_project_relative_paths(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    knowledge_database = _knowledge_with_load_symbol(tmp_path)
    policy = (
        build_gtfo_profile(tmp_path / "source")
        .review_policy()
        .bind_target_root("mods/BetterHitFeedback")
    )
    graph = build_graph(
        store,
        knowledge_database=knowledge_database,
        domain_review_policy=policy,
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer(),
        interrupt_after=["review_proposal"],
    )
    state = create_initial_state(
        run_id="run_explicit_domain_policy",
        request_id="req_explicit_domain_policy",
        user_request="make Load enable diagnostics",
        target_domain="unsupported",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(
        state,
        {"configurable": {"thread_id": "run_explicit_domain_policy"}},
    )

    assert result["current_stage"] == "proposal_review"
    assert result["review_summary"]["allowed_next_stage"] == "dry_run_apply"
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    review = _artifact_data(store, result, "proposal_review")
    assert review["decision"] == "approve_dry_run"
    assert not any(
        finding["rule_id"] in {"domain_profile", "scope_boundary"}
        for finding in review["findings"]
    )


def _artifact_data(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
) -> dict[str, object]:
    return store.read(_artifact_ref(store, result, artifact_type))["data"]


def _artifact_ref(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
):
    for ref in store.list_feature_artifacts(str(result["feature_id"])):
        if ref.artifact_type == artifact_type:
            return ref
    raise AssertionError(f"Missing artifact: {artifact_type}")


def _finished_event(result: dict[str, object], node_name: str) -> dict[str, object]:
    for event in result["trace_events"]:
        if event["node_name"] == node_name and event["event_type"] == "node_finished":
            return event
    raise AssertionError(f"Missing finished event: {node_name}")
