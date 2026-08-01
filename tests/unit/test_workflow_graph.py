"""Tests for the Phase A LangGraph workflow skeleton."""

from __future__ import annotations

import copy
import json
import hashlib
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    StaleArtifactError,
)
from src.mod_agent.artifacts.registry import (
    ArtifactContract,
    ArtifactTypeRegistry,
)
from src.mod_agent.bindings import resolve_runtime_diagnosis_binding
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.domain import DomainAdapterRegistry, build_gtfo_profile
from src.mod_agent.evidence import EvidencePack, FakeDenseRetrievalProvider
from src.mod_agent.execution import ExactDiffApprovalRejectedError
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
    LocalEntryError,
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
from src.mod_agent.workflow import (
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


def test_external_evaluation_requirement_requires_factory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="evaluation_context_factory"):
        build_graph(
            ArtifactStore(tmp_path / "artifacts"),
            require_external_evaluation=True,
        )


@pytest.mark.parametrize("materialization_fails", [False, True])
def test_stagger_edit_authority_approval_runs_only_through_graph_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    materialization_fails: bool,
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
    )
    captured: dict[str, object] = {}

    def materialize(**kwargs):
        captured.update(kwargs)
        if materialization_fails:
            raise RuntimeError("projection stopped after approval")
        return {
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
            "thread_id": (
                "stagger_edit_authority_graph_failed"
                if materialization_fails
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
                "decision": "approve",
                "approved_by": "user",
                "approved_at": "2026-07-30T12:00:00+08:00",
                "artifact_refs": request["artifact_refs"],
                "authority_request_hash": request_hash,
            }
        ),
        config,
    )

    assert captured["edit_authority_request_path"] == request_ref.path
    assert captured["edit_authority_request_hash"] == (
        request_ref.artifact_hash
    )
    assert "resume_report" in result["artifacts"]
    if materialization_fails:
        assert result["current_stage"] == "blocked"
        assert "binding_resolution" not in result["artifacts"]
        assert result["approvals"].get("edit_authority") is not True
        assert any(
            blocker["code"]
            == "EDIT_AUTHORITY_APPROVED_NOT_MATERIALIZED"
            for blocker in result["blockers"]
        )
    else:
        assert result["current_stage"] == "binding_resolution"
        assert result["approvals"]["edit_authority"] is True
        assert "binding_resolution" in result["artifacts"]


def test_existing_binding_reauthorization_exposes_narrow_graph_actions(
    tmp_path: Path,
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
    request_ref = store.write(
        feature_id="feature_existing_binding",
        artifact_type="edit_authority_request",
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


def test_stagger_diagnostic_authority_graph_stops_at_diagnostic_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        "schema_version": (
            "stagger_hud_parent_diagnostic_execution_authority_request_v2"
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
    request_ref = store.write(
        feature_id="feature_observation_authority",
        artifact_type="edit_authority_request",
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

    def materialize(**_kwargs):
        return {
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


def test_existing_binding_review_preserves_exact_request_subgraph(
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
    request_ref = store.write(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
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
    preflight = preflight_stagger_edit_authority_review(
        artifact_store_root=tmp_path / "artifacts",
        feature_id=feature_id,
        edit_authority_request_path=request_ref.path,
        edit_authority_request_hash=request_ref.artifact_hash,
        authority_request_hash=request_hash,
    )

    assert preflight["status"] == (
        "READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION"
    )
    assert preflight["checkpoint_artifact_refs"] == [
        request_ref.path
    ]
    assert preflight["artifact_revision_counts"] == before_counts
    assert preflight["writes_performed"] is False

    def materialize(**_kwargs):
        return {
            field_name: {
                "feature_id": feature_id,
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
                (
                    "binding_resolution",
                    "binding_resolution_revision",
                ),
            )
        }

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "materialize_stagger_edit_authority_approval",
        materialize,
    )
    result = resume_stagger_edit_authority_review(
        artifact_store_root=tmp_path / "artifacts",
        feature_id=feature_id,
        edit_authority_request_path=request_ref.path,
        edit_authority_request_hash=request_ref.artifact_hash,
        authority_request_hash=request_hash,
        resume_id="resume_existing_binding_exact_001",
        decision="approve",
        approved_by="user",
        approved_at="2026-07-30T12:00:00+08:00",
    )

    assert result["status"] == "EXACT_EDIT_AUTHORITY_RESOLVED"
    assert len(
        store.list_feature_artifact_revisions(
            feature_id,
            "workflow_checkpoint",
        )
    ) == 1
    assert len(
        store.list_feature_artifact_revisions(
            feature_id,
            "resume_report",
        )
    ) == 1


def test_original_edit_authority_request_keeps_upstream_projection(
    tmp_path: Path,
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
    request_ref = store.write(
        feature_id="feature_original_request",
        artifact_type="edit_authority_request",
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

    interrupted = graph.invoke(
        state,
        {
            "configurable": {
                "thread_id": "original_authority_request_001"
            }
        },
    )

    assert set(
        interrupted["__interrupt__"][0].value["artifact_refs"]
    ) == {request_ref.path, feature_ref.path}


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
    request_ref = store.write(
        feature_id="feature_edit_authority_entry",
        artifact_type="edit_authority_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Awaiting graph approval.",
            "status": "pending_human_approval",
            "feature_id": "feature_edit_authority_entry",
            "run_id": "run_edit_authority_entry",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
    )

    def materialize(**_kwargs):
        return {
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

    monkeypatch.setattr(
        "src.mod_agent.local_entry.ArtifactStore",
        lambda _root: store,
    )
    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "materialize_stagger_edit_authority_approval",
        materialize,
    )

    result = resume_stagger_edit_authority_review(
        artifact_store_root=tmp_path / "artifacts",
        feature_id="feature_edit_authority_entry",
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

    def forbidden_build(_: str, __: str | None):
        raise AssertionError("Build must not repeat during Runtime continuation.")

    fresh_graph = build_graph(
        fresh_store,
        build_result_factory=forbidden_build,
        runtime_continuation_checkpoint_id=checkpoint["checkpoint_id"],
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
        runtime_continuation_checkpoint_id=str(checkpoint["checkpoint_id"]),
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
        runtime_continuation_checkpoint_id=checkpoint["checkpoint_id"],
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
    assert result["evidence_summary"]["retrieval_methods_used"] == ["symbol_exact"]
    assert result["evidence_summary"]["missing_evidence"] == []
    assert result["evidence_summary"]["timing"]["final_count"] == 1.0
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
    assert proposal["context_pack"]["allowed_edit_binding_ids"] == ["edit_binding_001"]
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
    assert "implementation_plan" not in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    assert "proposal_review" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["evidence_summary"]["missing_evidence"]
    assert result["evidence_summary"]["timing"]["final_count"] == 0.0
    assert result["blockers"]
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
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
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
    assert event["details"]["retrieval_methods_used"] == ["symbol_exact"]
    assert event["details"]["missing_evidence_count"] == 0
    assert event["details"]["disabled_modes"]["bm25"]
    assert event["details"]["timing"]["final_count"] == 1.0


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
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path, root_name="secrets"),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["review_summary"]["allowed_next_stage"] is None
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]


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
