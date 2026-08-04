"""Minimal local product entry that assembles the existing controlled graph."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from langgraph.types import Command

from src.core.settings import load_settings
from src.libs.llm import LLMFactory, OllamaLLM, validate_loopback_http_base_url
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.build import (
    BuildAdapter,
    BuildCommandResult,
    BuildProfile,
    BuildResult,
)
from src.mod_agent.evidence import RgLiveEvidenceProvider
from src.mod_agent.edit_authority_capabilities import (
    EditAuthorityCapabilityDeclaration,
    InvalidEditAuthorityApprovalIdentityError,
    UnsupportedEditAuthorityCapabilityError,
    bind_edit_authority_exact_input_upstreams,
    edit_authority_identity_sections,
    require_edit_authority_public_operation,
    resolve_edit_authority_request_capability,
    validate_edit_authority_exact_input_admission,
    validate_edit_authority_request_identity,
)
from src.mod_agent.evidence.dotnet_metadata import (
    DotNetMetadataEnrichmentError,
    RunLocalMemberAccessResolver,
    enrich_source_evidence_with_member_accesses,
)
from src.mod_agent.execution import ExactDiffApprovalRejectedError, ExactTextPatchApplier
from src.mod_agent.planning.request_planner import requested_scope_text
from src.mod_agent.proposal import LLMExactPatchGenerator
from src.mod_agent.runtime import (
    GTFORuntimeAutomationError,
    bind_plugin_deployment_to_runtime_payload,
    build_gtfo_runtime_capability_report,
    build_gtfo_stagger_acceptance_report,
    make_operator_completion_file_reader,
    make_gtfo_runtime_evidence_factory_from_settings,
    make_gtfo_stagger_runtime_evidence_factory,
    profile_from_settings,
    stagger_profile_from_settings,
    temporarily_deploy_verified_plugin,
)
from src.mod_agent.runtime.stagger_diagnosis import (
    build_stagger_observation_retry_criterion_binding,
    build_stagger_repair_attempt_projection,
    inherit_stagger_repair_attempt_prior_results,
)
from src.mod_agent.workflow import (
    ResumeDecision,
    ResumePayload,
    ResumeValidator,
    VerificationOnlyContinuationInput,
    VerificationOnlyRuntimeTerminalInput,
    WorkflowCheckpointStore,
    build_graph,
    create_initial_state,
    preflight_verification_only_continuation,
    resumed_state_from_decision,
)
from src.mod_agent.action_identity import hash_canonical_value
from src.mod_agent.artifact_semantics import (
    ArtifactWriteIntent,
    project_artifact_write_intent,
)
from src.mod_agent.workflow.graph import (
    _RuntimeEvidenceExecutionBoundaryError,
    _runtime_summary_from_payload,
)
from src.mod_agent.runtime_evidence_consolidation import (
    logical_identity as consolidation_logical_identity,
    project_operation_payload as project_runtime_evidence_consolidation_payload,
    runtime_evidence_consolidation_child_refs,
)
from src.mod_agent.verification_operations import (
    EVIDENCE_CONSOLIDATION_KIND,
    VerificationOperationEnvelope,
    VerificationOperationSpec,
    project_verification_operation,
    resolve_verification_operation,
    validate_verification_operation_envelope,
)


class LocalEntryError(RuntimeError):
    """Raised when the local real-slice entry cannot start truthfully."""


SOURCE_DISCLOSURE_DATA_CLASSES = (
    "natural_language_request",
    "retrieved_local_source_excerpts",
    "run_local_api_member_metadata_facts",
    "binding_registry",
    "side_effect_boundaries",
)
LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES = 262_144
LOCAL_DIAGNOSTIC_CONTENT_FILENAME = "patch_generation_failure_message_content.txt"
EXACT_DIFF_REJECTION_TOKEN = "REJECTED_BY_USER"
OllamaModelIdentityReader = Callable[[str, str], dict[str, Any]]
OllamaServerVersionReader = Callable[[str], str]
@dataclass(frozen=True)
class _EditAuthorityReviewAdmission:
    store: ArtifactStore
    request_ref: ArtifactRef
    request: dict[str, Any]
    request_envelope: dict[str, Any]
    run_id: str
    capability: EditAuthorityCapabilityDeclaration
    identity_sections: dict[str, Any]


def _validate_edit_authority_public_exact_inputs(
    *,
    store: ArtifactStore,
    feature_id: str,
    request: Mapping[str, Any],
    request_envelope: Mapping[str, Any],
) -> None:
    upstreams = request_envelope.get("inputs", {}).get(
        "upstream_artifacts",
        (),
    )
    if not isinstance(upstreams, list):
        raise LocalEntryError(
            "Edit Authority Request upstream projection is invalid."
        )
    try:
        bindings = bind_edit_authority_exact_input_upstreams(request, upstreams)
    except InvalidEditAuthorityApprovalIdentityError as exc:
        raise LocalEntryError(str(exc)) from exc
    if not bindings:
        return
    refs_by_identity: dict[tuple[str, str], list[ArtifactRef]] = {}
    for item in upstreams:
        if not isinstance(item, Mapping):
            raise LocalEntryError(
                "Edit Authority Request upstream entry is invalid."
            )
        ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type=str(item.get("artifact_type", "")),
            path=str(item.get("path", "")),
            artifact_hash=str(item.get("artifact_hash", "")),
        )
        refs_by_identity.setdefault(
            (ref.artifact_type, ref.artifact_hash),
            [],
        ).append(ref)
    latest_by_type = {
        ref.artifact_type: ref
        for ref in store.list_feature_artifacts(feature_id)
    }
    input_facts: list[dict[str, Any]] = []
    for requirement, _ in bindings:
        key = (
            str(requirement.get("artifact_type")),
            str(requirement.get("artifact_hash")),
        )
        matches = refs_by_identity.get(key)
        if not matches:
            raise LocalEntryError(
                "Edit Authority exact input is absent from its Request lineage."
            )
        ref = matches.pop(0)
        store.read(ref)
        latest = latest_by_type.get(ref.artifact_type)
        input_facts.append(
            {
                "role": requirement["role"],
                "artifact_type": ref.artifact_type,
                "artifact_hash": ref.artifact_hash,
                "registered": True,
                "latest_artifact_hash": (
                    latest.artifact_hash if latest is not None else None
                ),
                "recursive_fresh": store.check_freshness(ref).is_fresh,
                "exact_recursive_fresh": (
                    store.check_exact_revision_freshness(ref).is_fresh
                ),
            }
        )
    try:
        validate_edit_authority_exact_input_admission(request, input_facts)
    except InvalidEditAuthorityApprovalIdentityError as exc:
        raise LocalEntryError(str(exc)) from exc


def _admit_stagger_edit_authority_review(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    edit_authority_request_path: str | Path,
    edit_authority_request_hash: str,
    authority_request_hash: str,
) -> _EditAuthorityReviewAdmission:
    store = ArtifactStore(artifact_store_root)
    request_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        path=str(Path(edit_authority_request_path).resolve()),
        artifact_hash=edit_authority_request_hash,
    )
    try:
        request_envelope = store.read_for_stage(
            request_ref,
            consumer_stage="edit_authority_approval",
        )
        freshness = store.check_freshness(request_ref)
        latest_refs = {
            ref.artifact_type: ref
            for ref in store.list_feature_artifacts(feature_id)
        }
    except (OSError, RuntimeError, ValueError) as exc:
        raise LocalEntryError(
            f"Edit Authority Request admission failed: {exc}"
        ) from exc
    latest_request_ref = latest_refs.get("edit_authority_request")
    request_revision_paths = {
        str(Path(revision.path).resolve())
        for revision in store.list_feature_artifact_revisions(
            feature_id,
            "edit_authority_request",
        )
        if revision.artifact_hash == request_ref.artifact_hash
    }
    if (
        not freshness.is_fresh
        or latest_request_ref is None
        or latest_request_ref.artifact_hash != request_ref.artifact_hash
        or str(Path(request_ref.path).resolve())
        not in request_revision_paths
    ):
        raise LocalEntryError(
            "Edit Authority review requires the fresh current Request "
            "revision with the exact path and Artifact hash."
        )
    request = request_envelope["data"]
    if (
        request.get("feature_id") != feature_id
        or request.get("request_hash") != authority_request_hash
        or request.get("authority_granted") is not False
        or request.get("registry_mutation_allowed") is not False
        or request.get("repair_planner_allowed") is not False
        or request.get("source_patch_allowed") is not False
    ):
        raise LocalEntryError(
            "Edit Authority review input does not match the exact "
            "no-authority Request."
        )
    run_id = request.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise LocalEntryError(
            "Edit Authority Request run_id is missing."
        )
    try:
        capability, _, _ = validate_edit_authority_request_identity(
            request,
            allow_legacy=False,
        )
        identity_sections = edit_authority_identity_sections(
            request,
            allow_legacy=False,
        )
        _validate_edit_authority_public_exact_inputs(
            store=store,
            feature_id=feature_id,
            request=request,
            request_envelope=request_envelope,
        )
    except (
        InvalidEditAuthorityApprovalIdentityError,
        UnsupportedEditAuthorityCapabilityError,
    ) as exc:
        raise LocalEntryError(str(exc)) from exc
    return _EditAuthorityReviewAdmission(
        store=store,
        request_ref=request_ref,
        request=request,
        request_envelope=request_envelope,
        run_id=run_id,
        capability=capability,
        identity_sections=identity_sections,
    )


def _expected_edit_authority_checkpoint_refs(
    admission: _EditAuthorityReviewAdmission,
) -> list[str]:
    if admission.capability.checkpoint_input_mode == "request_only":
        return [admission.request_ref.path]
    upstreams = admission.request_envelope.get("inputs", {}).get(
        "upstream_artifacts",
        (),
    )
    artifact_paths: dict[str, str] = {}
    for upstream in upstreams:
        if (
            isinstance(upstream, dict)
            and isinstance(upstream.get("artifact_type"), str)
            and isinstance(upstream.get("path"), str)
            and isinstance(upstream.get("artifact_hash"), str)
        ):
            artifact_paths[str(upstream["artifact_type"])] = str(
                upstream["path"]
            )
    return [admission.request_ref.path, *artifact_paths.values()]


def _invoke_stagger_edit_authority_interrupt(
    *,
    admission: _EditAuthorityReviewAdmission,
    feature_id: str,
    authority_request_hash: str,
    thread_id: str,
) -> tuple[Any, list[str], Any, dict[str, Any]]:
    graph = build_graph(
        admission.store,
        edit_authority_request_ref=admission.request_ref,
        checkpointer=(
            WorkflowCheckpointStore.langgraph_memory_checkpointer()
        ),
        use_default_proposal_git_binding=False,
    )
    state = create_initial_state(
        run_id=admission.run_id,
        request_id=feature_id,
        user_request=(
            "Review the exact BetterHitFeedback Stagger Edit Authority "
            "Request."
        ),
        target_domain="gtfo",
        target_mod="BetterHitFeedback",
    )
    state["feature_id"] = feature_id
    config = {"configurable": {"thread_id": thread_id}}
    try:
        interrupted_state = graph.invoke(state, config)
    except Exception as exc:
        raise LocalEntryError(
            "Edit Authority graph failed before its human interrupt: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    interrupts = interrupted_state.get("__interrupt__")
    if (
        not isinstance(interrupts, (list, tuple))
        or len(interrupts) != 1
    ):
        raise LocalEntryError(
            "Edit Authority graph did not expose exactly one human "
            "interrupt."
        )
    interrupt_value = getattr(interrupts[0], "value", None)
    interrupt_payload = (
        interrupt_value.get("payload")
        if isinstance(interrupt_value, dict)
        else None
    )
    if (
        not isinstance(interrupt_payload, dict)
        or interrupt_value.get("stage") != "edit_authority_approval"
        or interrupt_payload.get("request_hash")
        != authority_request_hash
    ):
        raise LocalEntryError(
            "Edit Authority graph interrupt does not bind the approved "
            "Request hash."
        )
    artifact_refs = interrupt_value.get("artifact_refs")
    if not isinstance(artifact_refs, list) or not artifact_refs:
        raise LocalEntryError(
            "Edit Authority graph interrupt has no exact Artifact refs."
        )
    return graph, list(artifact_refs), config, interrupt_value


def preflight_stagger_edit_authority_review(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    edit_authority_request_path: str | Path,
    edit_authority_request_hash: str,
    authority_request_hash: str,
) -> dict[str, Any]:
    """Validate the Graph review entry without writing or resuming."""

    admission = _admit_stagger_edit_authority_review(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        edit_authority_request_path=edit_authority_request_path,
        edit_authority_request_hash=edit_authority_request_hash,
        authority_request_hash=authority_request_hash,
    )
    try:
        require_edit_authority_public_operation(
            admission.capability,
            "preflight",
        )
    except UnsupportedEditAuthorityCapabilityError as exc:
        raise LocalEntryError(str(exc)) from exc
    write_types = admission.capability.review_write_artifact_types
    before_counts = {
        artifact_type: len(
            admission.store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in write_types
    }
    _, artifact_refs, _, interrupt_value = (
        _invoke_stagger_edit_authority_interrupt(
            admission=admission,
            feature_id=feature_id,
            authority_request_hash=authority_request_hash,
            thread_id=f"preflight_edit_authority_{uuid4().hex}",
        )
    )
    expected_refs = _expected_edit_authority_checkpoint_refs(admission)
    if artifact_refs != expected_refs:
        raise LocalEntryError(
            "Stagger authority review checkpoint projection does not "
            "match the capability declaration."
        )
    after_counts = {
        artifact_type: len(
            admission.store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in write_types
    }
    if after_counts != before_counts:
        raise LocalEntryError(
            "Edit Authority review preflight changed Artifact revisions."
        )
    return {
        "status": admission.capability.preflight_success_status,
        "command": "preflight-stagger-edit-authority-review",
        "feature_id": feature_id,
        "run_id": admission.run_id,
        "request_hash": authority_request_hash,
        "approval_identity_mode": admission.identity_sections[
            "identity_mode"
        ],
        "approval_identity_schema_version": admission.identity_sections[
            "identity_schema_version"
        ],
        "approval_identity": admission.identity_sections[
            "approval_identity"
        ],
        "execution_contract_summary": admission.identity_sections[
            "execution_contract_summary"
        ],
        "audit_snapshot": {
            "artifact_revision_counts": after_counts,
            "writes_performed": False,
            "artifact_writes_performed": False,
        },
        "edit_authority_request_revision": {
            "feature_id": feature_id,
            "path": admission.request_ref.path,
            "artifact_hash": admission.request_ref.artifact_hash,
        },
        "checkpoint_artifact_refs": artifact_refs,
        "allowed_actions": list(
            interrupt_value["payload"]["allowed_actions"]
        ),
        "forbidden_actions": list(
            interrupt_value["payload"]["forbidden_actions"]
        ),
        "artifact_revision_counts": after_counts,
        "writes_performed": False,
        "artifact_writes_performed": False,
        "approval_written": False,
        "binding_resolution_written": False,
        "repair_planner_invoked": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }


def resume_stagger_edit_authority_review(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    edit_authority_request_path: str | Path,
    edit_authority_request_hash: str,
    authority_request_hash: str,
    resume_id: str,
    decision: str,
    approved_by: str,
    approved_at: str,
) -> dict[str, Any]:
    """Carry one exact human decision through the existing graph gate."""

    admission = _admit_stagger_edit_authority_review(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        edit_authority_request_path=edit_authority_request_path,
        edit_authority_request_hash=edit_authority_request_hash,
        authority_request_hash=authority_request_hash,
    )
    try:
        require_edit_authority_public_operation(
            admission.capability,
            "resume",
        )
    except UnsupportedEditAuthorityCapabilityError as exc:
        raise LocalEntryError(str(exc)) from exc
    write_types = admission.capability.review_write_artifact_types
    before_counts = {
        artifact_type: len(
            admission.store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in write_types
    }
    graph, artifact_refs, config, _ = (
        _invoke_stagger_edit_authority_interrupt(
            admission=admission,
            feature_id=feature_id,
            authority_request_hash=authority_request_hash,
            thread_id=resume_id,
        )
    )
    try:
        result = graph.invoke(
            Command(
                resume={
                    "resume_id": resume_id,
                    "run_id": admission.run_id,
                    "stage": "edit_authority_approval",
                    "decision": decision,
                    "approved_by": approved_by,
                    "approved_at": approved_at,
                    "artifact_refs": artifact_refs,
                    "authority_request_hash": authority_request_hash,
                }
            ),
            config,
        )
    except Exception as exc:
        raise LocalEntryError(
            "Edit Authority graph resume failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    artifact_types = set(result.get("artifacts") or {})
    if "repair_plan" in artifact_types:
        raise LocalEntryError(
            "Edit Authority graph exceeded its stop-before-RepairPlanner "
            "boundary."
        )
    expected_artifact_types = {
        artifact_type
        for artifact_type, _ in (
            admission.capability.materialized_artifact_fields
        )
    }
    capability_succeeded = (
        result.get("current_stage") == admission.capability.terminal_stage
        and expected_artifact_types.issubset(artifact_types)
        and (
            "binding_resolution" in expected_artifact_types
            or "binding_resolution" not in artifact_types
        )
    )
    after_counts = {
        artifact_type: len(
            admission.store.list_feature_artifact_revisions(
                feature_id,
                artifact_type,
            )
        )
        for artifact_type in write_types
    }
    writes_performed = after_counts != before_counts
    return {
        "status": (
            admission.capability.public_success_status
            if capability_succeeded
            else "BLOCKED"
        ),
        "command": "resume-stagger-edit-authority-review",
        "feature_id": feature_id,
        "run_id": admission.run_id,
        "resume_id": resume_id,
        "decision": decision,
        "request_hash": authority_request_hash,
        "approval_identity_mode": admission.identity_sections[
            "identity_mode"
        ],
        "approval_identity_schema_version": admission.identity_sections[
            "identity_schema_version"
        ],
        "approval_identity": admission.identity_sections[
            "approval_identity"
        ],
        "execution_contract_summary": admission.identity_sections[
            "execution_contract_summary"
        ],
        "audit_snapshot": {
            "artifact_revision_counts_before": before_counts,
            "artifact_revision_counts_after": after_counts,
            "writes_performed": writes_performed,
            "artifact_writes_performed": writes_performed,
        },
        "current_stage": result.get("current_stage"),
        "artifacts": dict(result.get("artifacts") or {}),
        "artifact_hashes": dict(result.get("artifact_hashes") or {}),
        "blockers": list(result.get("blockers") or ()),
        "repair_planner_invoked": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }


@dataclass(frozen=True)
class _RuntimeContinuationHandoff:
    """Read-validated Build handoff shared by preflight and actual resume."""

    run_root: Path
    artifact_store_root: Path
    artifact_store: ArtifactStore
    checkpoint_ref: ArtifactRef
    checkpoint: dict[str, Any]
    manifest: dict[str, Any]
    feature_spec_ref: ArtifactRef
    feature_spec: dict[str, Any]
    build_ref: ArtifactRef
    build: dict[str, Any]
    accepted_resume_recovery: bool = False
    runtime_observation_retry: bool = False
    recovery_decision: ResumeDecision | None = None
    recovery_resume_report_ref: ArtifactRef | None = None
    prior_runtime_evidence_ref: ArtifactRef | None = None
    prior_repair_plan_ref: ArtifactRef | None = None
    observation_retry_binding: Mapping[str, Any] | None = None
    resume_readiness: ResumeDecision | None = None


@dataclass(frozen=True)
class _RuntimeTerminalHandoff:
    """Exact immutable inputs for one post-Runtime terminal continuation."""

    build_handoff: _RuntimeContinuationHandoff
    resume_report_ref: ArtifactRef
    runtime_evidence_ref: ArtifactRef
    runtime_evidence: dict[str, Any]
    decision: ResumeDecision
    existing_terminal_refs: tuple[ArtifactRef, ...]


@dataclass(frozen=True)
class _RuntimeEvidenceConsolidationHandoff:
    """Exact inputs and derived output for one no-Runtime consolidation."""

    build_handoff: _RuntimeContinuationHandoff
    resume_report_ref: ArtifactRef
    prior_runtime_evidence_ref: ArtifactRef
    evidence_pack_ref: ArtifactRef
    decision: ResumeDecision
    existing_child_refs: tuple[ArtifactRef, ...]
    operation: VerificationOperationEnvelope
    semantic_intent: ArtifactWriteIntent | None
    derived_payload: Mapping[str, Any] | None
    derived_payload_hash: str | None


@dataclass(frozen=True)
class NuGetIsolatedBuildProfile:
    """Run-local NuGet restore and build inputs for one delivery workspace."""

    profile_id: str
    run_root: Path
    working_directory: Path
    config_file: Path
    packages_path: Path
    http_cache_path: Path
    scratch_path: Path
    plugins_cache_path: Path
    appdata_path: Path
    user_config_file: Path
    additional_user_config_path: Path
    bepinex_dir: Path
    timeout_seconds: int
    restore_command: tuple[str, ...]
    build_command: tuple[str, ...]

    @property
    def environment(self) -> dict[str, str]:
        return {
            "NUGET_PACKAGES": str(self.packages_path),
            "NUGET_HTTP_CACHE_PATH": str(self.http_cache_path),
            "NUGET_SCRATCH": str(self.scratch_path),
            "NUGET_PLUGINS_CACHE_PATH": str(self.plugins_cache_path),
            "APPDATA": str(self.appdata_path),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "scope": "run_local_nuget_config_and_writable_cache_isolation",
            "fully_hermetic_build_claimed": False,
            "working_directory": str(self.working_directory),
            "config_file": str(self.config_file),
            "packages_path": str(self.packages_path),
            "http_cache_path": str(self.http_cache_path),
            "scratch_path": str(self.scratch_path),
            "plugins_cache_path": str(self.plugins_cache_path),
            "appdata_path": str(self.appdata_path),
            "user_config_file": str(self.user_config_file),
            "additional_user_config_path": str(
                self.additional_user_config_path
            ),
            "user_config_source_sha256": hashlib.sha256(
                self.config_file.read_bytes()
            ).hexdigest(),
            "bepinex_dir": str(self.bepinex_dir),
            "timeout_seconds": self.timeout_seconds,
            "restore_command": list(self.restore_command),
            "build_command": list(self.build_command),
            "environment": self.environment,
        }


@dataclass(frozen=True)
class NuGetIsolatedBuildExecution:
    """Observed restore/build subprocess outcome for the bounded profile."""

    restore_exit_code: int
    build_exit_code: int | None
    restore_stdout: str
    restore_stderr: str
    build_stdout: str
    build_stderr: str
    duration_ms: int

    @property
    def exit_code(self) -> int:
        return (
            self.restore_exit_code
            if self.restore_exit_code != 0
            else int(self.build_exit_code or 0)
        )

    @property
    def stdout(self) -> str:
        return _join_build_phase_output(
            ("dotnet restore", self.restore_stdout),
            ("dotnet build --no-restore", self.build_stdout),
        )

    @property
    def stderr(self) -> str:
        return _join_build_phase_output(
            ("dotnet restore", self.restore_stderr),
            ("dotnet build --no-restore", self.build_stderr),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "restore_exit_code": self.restore_exit_code,
            "build_exit_code": self.build_exit_code,
            "build_executed": self.build_exit_code is not None,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class CompiledArtifactInspectionProfile:
    """Tracked inspector source and expected plugin identity for one local run."""

    project_path: Path
    method_symbol: str
    expected_guid: str
    expected_name: str
    expected_version: str
    timeout_seconds: int = 120

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_path": str(self.project_path.resolve()),
            "method_symbol": self.method_symbol,
            "expected_guid": self.expected_guid,
            "expected_name": self.expected_name,
            "expected_version": self.expected_version,
            "timeout_seconds": self.timeout_seconds,
        }


def _create_nuget_isolated_build_profile(
    *,
    run_root: Path,
    working_directory: Path,
    config_file: Path,
    bepinex_dir: Path,
    timeout_seconds: int,
) -> NuGetIsolatedBuildProfile:
    root = run_root.resolve()
    working = working_directory.resolve()
    config = config_file.resolve()
    bepinex = bepinex_dir.resolve()
    for label, path in (
        ("working_directory", working),
        ("config_file", config),
        ("bepinex_dir", bepinex),
    ):
        _require_run_local_build_path(root=root, path=path, label=label)
    if not working.is_dir():
        raise LocalEntryError("NuGet-isolated build working directory is missing.")
    if not config.is_file():
        raise LocalEntryError("NuGet-isolated build config file is missing.")
    if not bepinex.is_dir():
        raise LocalEntryError("NuGet-isolated build BepInEx directory is missing.")
    if timeout_seconds <= 0:
        raise LocalEntryError("NuGet-isolated build timeout must be positive.")

    nuget_root = root / "build_environment" / "nuget"
    packages = nuget_root / "packages"
    http_cache = nuget_root / "http-cache"
    scratch = nuget_root / "scratch"
    plugins_cache = nuget_root / "plugins-cache"
    appdata = root / "build_environment" / "appdata"
    user_config = appdata / "NuGet" / "NuGet.Config"
    additional_user_config = appdata / "NuGet" / "config"
    bepinex_property = f"-p:BepInExDir={bepinex}"
    return NuGetIsolatedBuildProfile(
        profile_id="v2_codegen_real_local_dotnet_nuget_isolated",
        run_root=root,
        working_directory=working,
        config_file=config,
        packages_path=packages,
        http_cache_path=http_cache,
        scratch_path=scratch,
        plugins_cache_path=plugins_cache,
        appdata_path=appdata,
        user_config_file=user_config,
        additional_user_config_path=additional_user_config,
        bepinex_dir=bepinex,
        timeout_seconds=timeout_seconds,
        restore_command=(
            "dotnet",
            "restore",
            "--configfile",
            str(config),
            "--packages",
            str(packages),
            bepinex_property,
        ),
        build_command=(
            "dotnet",
            "build",
            "--no-restore",
            bepinex_property,
        ),
    )


def _run_nuget_isolated_build(
    profile: NuGetIsolatedBuildProfile,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
) -> NuGetIsolatedBuildExecution:
    for path in (
        profile.packages_path,
        profile.http_cache_path,
        profile.scratch_path,
        profile.plugins_cache_path,
        profile.additional_user_config_path,
    ):
        path.mkdir(parents=True, exist_ok=True)
    source_config = profile.config_file.read_bytes()
    if profile.user_config_file.exists():
        if profile.user_config_file.read_bytes() != source_config:
            raise LocalEntryError(
                "Run-local NuGet user config does not match the bound config file."
            )
    else:
        profile.user_config_file.write_bytes(source_config)
    environment = os.environ.copy()
    environment.update(profile.environment)
    common = {
        "cwd": profile.working_directory,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": profile.timeout_seconds,
        "check": False,
        "env": environment,
    }
    started = time.perf_counter()
    restore = command_runner(profile.restore_command, **common)
    if restore.returncode != 0:
        return NuGetIsolatedBuildExecution(
            restore_exit_code=int(restore.returncode),
            build_exit_code=None,
            restore_stdout=str(restore.stdout or ""),
            restore_stderr=str(restore.stderr or ""),
            build_stdout="",
            build_stderr="",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    build = command_runner(profile.build_command, **common)
    return NuGetIsolatedBuildExecution(
        restore_exit_code=int(restore.returncode),
        build_exit_code=int(build.returncode),
        restore_stdout=str(restore.stdout or ""),
        restore_stderr=str(restore.stderr or ""),
        build_stdout=str(build.stdout or ""),
        build_stderr=str(build.stderr or ""),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _require_run_local_build_path(*, root: Path, path: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise LocalEntryError(
            f"NuGet-isolated build {label} must remain inside the run workspace."
        ) from exc


def _join_build_phase_output(*phases: tuple[str, str]) -> str:
    selected = [f"[{label}]\n{output}" for label, output in phases if output]
    return "\n".join(selected)


def _verification_only_build_admission(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    feature_spec_path: str | Path,
    feature_spec_hash: str,
    evidence_pack_path: str | Path,
    evidence_pack_hash: str,
    run_id: str,
    request_id: str,
    user_request: str,
    target_mod: str | None,
) -> tuple[ArtifactStore, VerificationOnlyContinuationInput, dict[str, Any]]:
    root_path = Path(artifact_store_root)
    feature_path = Path(feature_spec_path)
    evidence_path = Path(evidence_pack_path)
    if not root_path.is_absolute():
        raise LocalEntryError("artifact_store_root must be absolute.")
    if not feature_path.is_absolute() or not evidence_path.is_absolute():
        raise LocalEntryError(
            "Verification-only Build Artifact paths must be absolute."
        )
    store = ArtifactStore(root_path)
    continuation = VerificationOnlyContinuationInput(
        feature_spec_ref=ArtifactRef(
            feature_id=feature_id,
            artifact_type="feature_spec",
            path=str(feature_path.resolve()),
            artifact_hash=feature_spec_hash,
        ),
        evidence_pack_ref=ArtifactRef(
            feature_id=feature_id,
            artifact_type="evidence_pack",
            path=str(evidence_path.resolve()),
            artifact_hash=evidence_pack_hash,
        ),
    )
    preflight = preflight_verification_only_continuation(
        store,
        continuation,
        run_id=run_id,
        request_id=request_id,
        user_request=user_request,
        target_mod=target_mod,
    )
    return store, continuation, preflight


def preflight_verification_only_build_continuation(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    feature_spec_path: str | Path,
    feature_spec_hash: str,
    evidence_pack_path: str | Path,
    evidence_pack_hash: str,
    run_id: str,
    request_id: str,
    user_request: str,
    target_domain: str | None,
    target_mod: str | None,
) -> dict[str, Any]:
    """Read-validate a verification-only Build without probing Store writes."""

    _, _, preflight = _verification_only_build_admission(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        feature_spec_path=feature_spec_path,
        feature_spec_hash=feature_spec_hash,
        evidence_pack_path=evidence_pack_path,
        evidence_pack_hash=evidence_pack_hash,
        run_id=run_id,
        request_id=request_id,
        user_request=user_request,
        target_mod=target_mod,
    )
    return {
        "status": preflight["status"],
        "command": "preflight-verification-only-build-continuation",
        "feature_id": feature_id,
        "run_id": run_id,
        "request_id": request_id,
        "target_domain": target_domain,
        "target_mod": target_mod,
        "verification_only_preflight": preflight,
        "writes_performed": False,
        "artifact_writes_performed": False,
        "build_invoked": False,
        "automatic_retry_count": 0,
        "recovery_performed": False,
    }


def _verification_only_build_terminal_result(
    *,
    status: str,
    failure_stage: str | None,
    feature_id: str,
    run_id: str,
    request_id: str,
    target_domain: str | None,
    target_mod: str | None,
    preflight: Mapping[str, Any],
    factory_invocation_count: int,
    build_summary: Mapping[str, Any] | None = None,
    build_result: Mapping[str, Any] | None = None,
    workflow_checkpoint: Mapping[str, Any] | None = None,
    handoff_ready: bool = False,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    summary = dict(build_summary or {})
    return {
        "status": status,
        "failure_stage": failure_stage,
        "feature_id": feature_id,
        "run_id": run_id,
        "request_id": request_id,
        "target_domain": target_domain,
        "target_mod": target_mod,
        "verification_only_preflight": dict(preflight),
        "build_execution": {
            "factory_invocation_count": factory_invocation_count,
            "side_effects_may_have_started": factory_invocation_count > 0,
            "domain_status": summary.get("domain_status"),
            "build_status": summary.get("build_status"),
            "real_build_performed": summary.get("real_build_performed"),
            "claims_real_build_success": summary.get(
                "claims_real_build_success"
            ),
        },
        "build_result": None if build_result is None else dict(build_result),
        "workflow_checkpoint": (
            None if workflow_checkpoint is None else dict(workflow_checkpoint)
        ),
        "handoff_ready": handoff_ready,
        "blockers": list(blockers or ()),
        "automatic_retry_count": 0,
        "recovery_performed": False,
    }


def execute_verification_only_build_continuation(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    feature_spec_path: str | Path,
    feature_spec_hash: str,
    evidence_pack_path: str | Path,
    evidence_pack_hash: str,
    run_id: str,
    request_id: str,
    user_request: str,
    target_domain: str | None,
    target_mod: str | None,
    build_result_factory: Callable[[str, str | None], BuildResult],
    allow_build_execution: bool,
) -> dict[str, Any]:
    """Execute one admitted verification-only Build through the public graph."""

    store, continuation, preflight = _verification_only_build_admission(
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        feature_spec_path=feature_spec_path,
        feature_spec_hash=feature_spec_hash,
        evidence_pack_path=evidence_pack_path,
        evidence_pack_hash=evidence_pack_hash,
        run_id=run_id,
        request_id=request_id,
        user_request=user_request,
        target_mod=target_mod,
    )
    if not allow_build_execution:
        return _verification_only_build_terminal_result(
            status="blocked",
            failure_stage="authorization",
            feature_id=feature_id,
            run_id=run_id,
            request_id=request_id,
            target_domain=target_domain,
            target_mod=target_mod,
            preflight=preflight,
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "build",
                    "code": "VERIFICATION_BUILD_EXECUTION_NOT_AUTHORIZED",
                    "message": "Verification-only Build execution is not authorized.",
                }
            ],
        )
    if preflight["status"] != "ready_for_build_authorization":
        return _verification_only_build_terminal_result(
            status="blocked",
            failure_stage="admission",
            feature_id=feature_id,
            run_id=run_id,
            request_id=request_id,
            target_domain=target_domain,
            target_mod=target_mod,
            preflight=preflight,
            factory_invocation_count=0,
            blockers=list(preflight["blockers"]),
        )

    caller_factory_invocations = 0
    effect_wrapper_invocations = 0
    execution_failure_stage: str | None = None

    def admitted_build_result_factory(
        selected_feature_id: str,
        input_execution_mode: str | None,
    ) -> BuildResult:
        nonlocal caller_factory_invocations
        nonlocal effect_wrapper_invocations
        nonlocal execution_failure_stage
        if effect_wrapper_invocations != 0:
            execution_failure_stage = "build_execution"
            raise LocalEntryError(
                "Verification-only Build effect wrapper was invoked more than once."
            )
        effect_wrapper_invocations = 1
        try:
            store.preflight_atomic_commit(
                feature_id=feature_id,
                artifact_types=("build_result", "workflow_checkpoint"),
            )
        except Exception:
            execution_failure_stage = "store_preflight"
            raise
        caller_factory_invocations = 1
        execution_failure_stage = "build_execution"
        return build_result_factory(selected_feature_id, input_execution_mode)

    graph = build_graph(
        store,
        build_result_factory=admitted_build_result_factory,
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    )
    initial_state = create_initial_state(
        run_id=run_id,
        request_id=request_id,
        user_request=user_request,
        target_domain=target_domain,
        target_mod=target_mod,
    )
    try:
        graph_result = graph.invoke(initial_state)
    except Exception as exc:
        stage = execution_failure_stage or "admission"
        return _verification_only_build_terminal_result(
            status="blocked",
            failure_stage=stage,
            feature_id=feature_id,
            run_id=run_id,
            request_id=request_id,
            target_domain=target_domain,
            target_mod=target_mod,
            preflight=preflight,
            factory_invocation_count=caller_factory_invocations,
            blockers=[
                {
                    "stage": "build",
                    "code": "VERIFICATION_BUILD_PUBLIC_EXECUTION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )

    summary = dict(graph_result.get("build_summary") or {})
    graph_blockers = list(graph_result.get("blockers") or ())
    build_store_result = summary.get("build_result_store_result")
    checkpoint_store_result = summary.get("workflow_checkpoint_store_result")
    build_ref = None
    if "build_result" in graph_result.get("artifacts", {}):
        build_ref = {
            "feature_id": feature_id,
            "artifact_type": "build_result",
            "path": graph_result["artifacts"]["build_result"],
            "artifact_hash": graph_result["artifact_hashes"]["build_result"],
        }
    checkpoint_ref = None
    checkpoint_resume = None
    checkpoint_resume_error = None
    if "workflow_checkpoint" in graph_result.get("artifacts", {}):
        checkpoint_artifact_ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type="workflow_checkpoint",
            path=graph_result["artifacts"]["workflow_checkpoint"],
            artifact_hash=graph_result["artifact_hashes"]["workflow_checkpoint"],
        )
        checkpoint_ref = {
            "feature_id": feature_id,
            "artifact_type": "workflow_checkpoint",
            "path": checkpoint_artifact_ref.path,
            "artifact_hash": checkpoint_artifact_ref.artifact_hash,
        }
        try:
            decision = WorkflowCheckpointStore(store).preflight_resume(
                checkpoint_artifact_ref
            )
            checkpoint_resume = {
                "status": decision.status,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "blockers": list(decision.blockers),
            }
        except Exception as exc:
            checkpoint_resume_error = {
                "stage": "build",
                "code": "VERIFICATION_CHECKPOINT_RESUME_PREFLIGHT_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
            }
            graph_blockers.append(checkpoint_resume_error)

    build_result_projection = None
    if build_store_result is not None or build_ref is not None:
        build_result_projection = {
            "artifact_ref": build_ref,
            "payload_status": summary.get("domain_status"),
            "store_result": build_store_result,
        }
    checkpoint_projection = None
    if checkpoint_store_result is not None or checkpoint_ref is not None:
        checkpoint_projection = {
            "artifact_ref": checkpoint_ref,
            "store_result": checkpoint_store_result,
            "resume_preflight": checkpoint_resume,
        }

    failure_stage = summary.get("platform_failure_stage")
    outer_status = "blocked" if failure_stage is not None else "completed"
    for store_result in (build_store_result, checkpoint_store_result):
        if isinstance(store_result, Mapping) and store_result.get("outcome") == "partial":
            outer_status = "partial"
    if (
        failure_stage is None
        and summary.get("domain_status") == "success"
        and summary.get("claims_real_build_success") is not True
    ):
        outer_status = "blocked"
        failure_stage = "handoff_eligibility"
    handoff_ready = bool(
        checkpoint_ref is not None
        and checkpoint_resume is not None
        and checkpoint_resume["allowed"] is True
        and outer_status == "completed"
    )
    if (
        checkpoint_resume_error is not None
        and checkpoint_ref is not None
        and outer_status == "completed"
    ):
        outer_status = "blocked"
        failure_stage = "checkpoint_resume_preflight"
    elif checkpoint_ref is not None and not handoff_ready and outer_status == "completed":
        outer_status = "blocked"
        failure_stage = "checkpoint_resume_preflight"

    return _verification_only_build_terminal_result(
        status=outer_status,
        failure_stage=failure_stage,
        feature_id=feature_id,
        run_id=run_id,
        request_id=request_id,
        target_domain=target_domain,
        target_mod=target_mod,
        preflight=preflight,
        factory_invocation_count=caller_factory_invocations,
        build_summary=summary,
        build_result=build_result_projection,
        workflow_checkpoint=checkpoint_projection,
        handoff_ready=handoff_ready,
        blockers=graph_blockers,
    )


def _remove_generated_build_directory(
    directory: Path,
    *,
    tree_remover: Callable[..., Any] = shutil.rmtree,
) -> dict[str, Any]:
    """Remove one generated build directory while tolerating vanished entries."""

    selected = directory.resolve()
    ignored_missing_paths: list[str] = []
    cleanup_attempt_count = 0
    directory_not_empty_retry_count = 0

    def handle_error(
        _operation: Callable[..., Any],
        failed_path: str,
        error_info: tuple[type[BaseException], BaseException, Any],
    ) -> None:
        error = error_info[1]
        if isinstance(error, FileNotFoundError):
            ignored_missing_paths.append(str(failed_path))
            return
        raise error

    while selected.exists():
        cleanup_attempt_count += 1
        try:
            tree_remover(selected, onerror=handle_error)
        except OSError as error:
            if (
                getattr(error, "winerror", None) == 145
                and directory_not_empty_retry_count == 0
            ):
                directory_not_empty_retry_count = 1
                continue
            raise
        break
    if selected.exists():
        raise LocalEntryError("Generated build directory remains after cleanup.")
    return {
        "path": str(selected),
        "removed": True,
        "ignored_missing_paths": ignored_missing_paths,
        "cleanup_attempt_count": cleanup_attempt_count,
        "directory_not_empty_retry_count": directory_not_empty_retry_count,
    }


def _build_run_local_il_inspector(
    profile: CompiledArtifactInspectionProfile,
    *,
    run_root: Path,
    command_runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Build the tracked inspector source inside one run-local tool workspace."""

    root = run_root.resolve()
    project = profile.project_path.resolve()
    if not project.is_file() or project.suffix.lower() != ".csproj":
        raise LocalEntryError("Configured IL inspector project is missing.")
    if profile.timeout_seconds <= 0:
        raise LocalEntryError("IL inspector build timeout must be positive.")

    tool_root = root / "verification_tools" / "r8_il_inspector"
    source_root = tool_root / "source"
    output_root = tool_root / "output"
    environment_root = tool_root / "build_environment"
    nuget_root = environment_root / "nuget"
    packages = nuget_root / "packages"
    http_cache = nuget_root / "http-cache"
    scratch = nuget_root / "scratch"
    plugins_cache = nuget_root / "plugins-cache"
    appdata = environment_root / "appdata"
    additional_user_config = appdata / "NuGet" / "config"
    user_config = appdata / "NuGet" / "NuGet.Config"
    config = tool_root / "nuget.config"
    restore_stdout = tool_root / "restore.stdout.log"
    restore_stderr = tool_root / "restore.stderr.log"
    build_stdout = tool_root / "build.stdout.log"
    build_stderr = tool_root / "build.stderr.log"
    record_path = tool_root / "verification_tool_build.json"

    for path in (
        tool_root,
        packages,
        http_cache,
        scratch,
        plugins_cache,
        additional_user_config,
        output_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        project.parent,
        source_root,
        ignore=shutil.ignore_patterns("bin", "obj", ".git", ".idea"),
    )
    copied_project = source_root / project.name
    if not copied_project.is_file():
        raise LocalEntryError("Run-local IL inspector project copy is missing.")
    config_bytes = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<configuration><packageSources><clear /></packageSources></configuration>\n"
    )
    config.write_bytes(config_bytes)
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_bytes(config_bytes)

    environment = os.environ.copy()
    isolated_environment = {
        "NUGET_PACKAGES": str(packages),
        "NUGET_HTTP_CACHE_PATH": str(http_cache),
        "NUGET_SCRATCH": str(scratch),
        "NUGET_PLUGINS_CACHE_PATH": str(plugins_cache),
        "APPDATA": str(appdata),
    }
    environment.update(isolated_environment)
    restore_command = (
        "dotnet",
        "restore",
        str(copied_project),
        "--configfile",
        str(config),
        "--packages",
        str(packages),
    )
    build_command = (
        "dotnet",
        "build",
        str(copied_project),
        "--no-restore",
        "--output",
        str(output_root),
    )
    common = {
        "cwd": source_root,
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": profile.timeout_seconds,
        "check": False,
        "env": environment,
    }
    started = time.perf_counter()
    restore = command_runner(restore_command, **common)
    restore_stdout.write_text(str(restore.stdout or ""), encoding="utf-8")
    restore_stderr.write_text(str(restore.stderr or ""), encoding="utf-8")
    build = None
    if restore.returncode == 0:
        build = command_runner(build_command, **common)
        build_stdout.write_text(str(build.stdout or ""), encoding="utf-8")
        build_stderr.write_text(str(build.stderr or ""), encoding="utf-8")
    else:
        build_stdout.write_text("", encoding="utf-8")
        build_stderr.write_text("", encoding="utf-8")

    inspector = output_root / f"{copied_project.stem}.dll"
    source_snapshot = _source_snapshot(source_root)
    record = {
        "profile_id": "run_local_r8_il_inspector_dotnet_nuget_isolated",
        "fully_hermetic_build_claimed": False,
        "source_project": str(project),
        "source_project_sha256": hashlib.sha256(project.read_bytes()).hexdigest(),
        "source_snapshot_sha256": _source_snapshot_sha256(source_snapshot),
        "copied_project": str(copied_project),
        "restore_command": list(restore_command),
        "build_command": list(build_command),
        "environment": isolated_environment,
        "timeout_seconds": profile.timeout_seconds,
        "restore_exit_code": int(restore.returncode),
        "build_exit_code": int(build.returncode) if build is not None else None,
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "restore_stdout_path": str(restore_stdout),
        "restore_stderr_path": str(restore_stderr),
        "build_stdout_path": str(build_stdout),
        "build_stderr_path": str(build_stderr),
        "inspector_path": str(inspector),
        "inspector_exists": inspector.is_file(),
        "inspector_sha256": (
            hashlib.sha256(inspector.read_bytes()).hexdigest()
            if inspector.is_file()
            else None
        ),
    }
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if restore.returncode != 0:
        raise LocalEntryError(
            f"Run-local IL inspector restore failed with exit code {restore.returncode}."
        )
    if build is None or build.returncode != 0:
        exit_code = None if build is None else build.returncode
        raise LocalEntryError(
            f"Run-local IL inspector build failed with exit code {exit_code}."
        )
    if not inspector.is_file():
        raise LocalEntryError("Run-local IL inspector build produced no inspector DLL.")
    return record


def _persist_pre_graph_failure(
    *,
    run_root: Path,
    run_id: str,
    request_id: str,
    failure_stage: str,
    error: BaseException,
    source_revision_binding: Mapping[str, str] | None,
    model_admission: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> None:
    failure = {
        "run_id": run_id,
        "request_id": request_id,
        "current_stage": "failed_before_graph",
        "failure_stage": failure_stage,
        "error_type": type(error).__name__,
        "error": str(error),
        "model_call_count": 0,
        "graph_invoked": False,
        "patch_payload_parser_entered": False,
        "actual_write_performed": False,
        "source_revision_binding": dict(source_revision_binding or {}),
        "model_admission": dict(model_admission),
        "run_root": str(run_root),
    }
    if extra:
        failure.update(dict(extra))
    try:
        failure_path = run_root / "run_failure.json"
        failure_bytes = (
            json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        failure_path.write_bytes(failure_bytes)
        manifest_path = run_root / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("run_id") != run_id
            or manifest.get("request_id") != request_id
        ):
            return
        manifest.update(
            {
                "status": "failed",
                "terminal_failure_stage": failure_stage,
                "terminal_record": {
                    "path": str(failure_path),
                    "sha256": hashlib.sha256(failure_bytes).hexdigest(),
                },
                "model_call_count": 0,
                "graph_invoked": False,
                "patch_payload_parser_entered": False,
                "actual_write_performed": False,
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def _run_pre_graph_step(
    *,
    failure_stage: str,
    action: Callable[[], Any],
    run_root: Path,
    run_id: str,
    request_id: str,
    source_revision_binding: Mapping[str, str] | None,
    model_admission: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> Any:
    try:
        return action()
    except Exception as exc:
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage=failure_stage,
            error=exc,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra=extra,
        )
        raise


def _persist_graph_terminal_result(
    *,
    run_root: Path,
    run_id: str,
    request_id: str,
    summary: Mapping[str, Any],
    model_call_count: int,
    patch_payload_parser_entered: bool,
    actual_write_performed: bool,
) -> None:
    manifest_path = run_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id or manifest.get("request_id") != request_id:
        raise LocalEntryError("Run manifest identity changed before terminal projection.")
    result_path = run_root / "run_result.json"
    result_bytes = (
        json.dumps(dict(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    result_path.write_bytes(result_bytes)
    terminal_stage = str(summary.get("current_stage") or "unknown")
    manifest.update(
        {
            "status": terminal_stage,
            "terminal_stage": terminal_stage,
            "terminal_record": {
                "path": str(result_path),
                "sha256": hashlib.sha256(result_bytes).hexdigest(),
            },
            "model_call_count": model_call_count,
            "graph_invoked": True,
            "patch_payload_parser_entered": patch_payload_parser_entered,
            "actual_write_performed": actual_write_performed,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _persist_graph_terminal_failure(
    *,
    run_root: Path,
    run_id: str,
    request_id: str,
    error: BaseException,
    model_call_count: int,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = getattr(error, "diagnostics", None)
    diagnostic_record = dict(diagnostics) if isinstance(diagnostics, Mapping) else {}
    patch_payload_parser_entered = (
        diagnostic_record.get("failure_boundary")
        == "deterministic_patch_validation"
    )
    failure = {
        "run_id": run_id,
        "request_id": request_id,
        "current_stage": "failed_after_graph_invocation",
        "failure_stage": diagnostic_record.get("failure_boundary")
        or "graph_invocation",
        "error_type": type(error).__name__,
        "error": str(error),
        "model_call_count": model_call_count,
        "graph_invoked": True,
        "patch_payload_parser_entered": patch_payload_parser_entered,
        "actual_write_performed": False,
        "run_root": str(run_root),
    }
    if extra:
        failure.update(dict(extra))
    manifest_path = run_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("run_id") != run_id or manifest.get("request_id") != request_id:
        raise LocalEntryError("Run manifest identity changed before failure projection.")
    failure_path = run_root / "run_failure.json"
    failure_bytes = (
        json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    failure_path.write_bytes(failure_bytes)
    manifest.update(
        {
            "status": "failed",
            "terminal_failure_stage": failure["failure_stage"],
            "terminal_record": {
                "path": str(failure_path),
                "sha256": hashlib.sha256(failure_bytes).hexdigest(),
            },
            "model_call_count": model_call_count,
            "graph_invoked": True,
            "patch_payload_parser_entered": patch_payload_parser_entered,
            "actual_write_performed": False,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return failure


def _read_exact_diff_approval(
    reader: Callable[[dict[str, Any]], str],
    dry_run: Mapping[str, Any],
) -> str:
    approval = reader(dict(dry_run)).strip()
    if approval == EXACT_DIFF_REJECTION_TOKEN:
        raise ExactDiffApprovalRejectedError("User rejected the displayed exact diff.")
    return approval


def _verify_final_compiled_artifact_if_built(
    *,
    graph_result: Mapping[str, Any],
    target_copy: Path,
    expected_artifact: Path,
    verifier: Callable[[Path, str], dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if graph_result.get("build_summary", {}).get("claims_real_build_success") is not True:
        return None
    if verifier is None:
        return None
    final_artifact = target_copy / expected_artifact
    if not final_artifact.is_file():
        raise LocalEntryError("Final compiled artifact is missing after the graph build.")
    return verifier(final_artifact, "final")


def _runtime_admission_record(
    settings: Any,
    *,
    run_gtfo_runtime: bool,
    allow_game_launch: bool,
    runtime_plugin_destination: str | Path | None,
    allow_game_directory_write: bool,
    acceptance_criteria: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Bind one run's requested Runtime boundary before any mutable action."""

    runtime = getattr(settings, "runtime", None)
    gtfo = getattr(runtime, "gtfo", None)
    settings_enabled = bool(gtfo is not None and getattr(gtfo, "enabled", False))
    if allow_game_launch and not run_gtfo_runtime:
        raise LocalEntryError(
            "--allow-game-launch requires --run-gtfo-runtime for the same run."
        )
    if (
        runtime_plugin_destination is not None or allow_game_directory_write
    ) and not run_gtfo_runtime:
        raise LocalEntryError(
            "Runtime plugin deployment requires --run-gtfo-runtime for the same run."
        )
    if not run_gtfo_runtime:
        return {
            "requested": False,
            "evidence_source": None,
            "allow_game_launch": False,
            "authorization_scope": None,
            "settings_enabled": settings_enabled,
            "profile": None,
            "capability_report": None,
            "plugin_deployment": {
                "requested": False,
                "destination_path": None,
                "allow_game_directory_write": False,
                "restore_after_runtime": False,
                "performed_by_run_request": False,
                "verified_deployed_artifact_hash": False,
            },
        }
    if not settings_enabled:
        raise LocalEntryError(
            "--run-gtfo-runtime requires runtime.gtfo.enabled=true in the selected "
            "settings file."
        )
    if runtime_plugin_destination is None:
        raise LocalEntryError(
            "--run-gtfo-runtime requires --runtime-plugin-destination so the "
            "physical DLL loaded by GTFO can be bound to this run's Build."
        )
    if not allow_game_directory_write:
        raise LocalEntryError(
            "--run-gtfo-runtime requires --allow-game-directory-write for "
            "run-scoped plugin deployment and restoration."
        )
    try:
        profile = profile_from_settings(settings)
        capability_report = build_gtfo_runtime_capability_report(
            profile,
            allow_game_launch=allow_game_launch,
            acceptance_criteria=acceptance_criteria,
        )
    except GTFORuntimeAutomationError as exc:
        raise LocalEntryError(f"GTFO Runtime admission failed: {exc}") from exc
    if capability_report["status"] != "ready":
        raise LocalEntryError(
            "GTFO Runtime admission blocked: "
            + "; ".join(str(item) for item in capability_report["blockers"])
        )
    destination_input = Path(runtime_plugin_destination)
    if not destination_input.is_absolute():
        raise LocalEntryError(
            "--runtime-plugin-destination must be an absolute .dll path."
        )
    destination = destination_input.resolve()
    working_directory = Path(profile.working_directory).resolve()
    try:
        destination.relative_to(working_directory)
    except ValueError as exc:
        raise LocalEntryError(
            "--runtime-plugin-destination must remain inside the configured "
            "runtime.gtfo.working_directory."
        ) from exc
    if destination.suffix.lower() != ".dll":
        raise LocalEntryError(
            "--runtime-plugin-destination must identify one .dll file."
        )
    if not destination.parent.is_dir():
        raise LocalEntryError(
            "Runtime plugin destination directory does not exist: "
            f"{destination.parent}"
        )
    if profile.terminate_after_capture is not True:
        raise LocalEntryError(
            "Run-scoped plugin deployment requires "
            "runtime.gtfo.terminate_after_capture=true before launch."
        )
    stagger_profile = stagger_profile_from_settings(settings)
    stagger_acceptance = None
    if stagger_profile is not None:
        if profile.operator_completion_required is not True:
            raise LocalEntryError(
                "Two-process stagger Runtime requires "
                "runtime.gtfo.operator_completion_required=true."
            )
        stagger_acceptance = build_gtfo_stagger_acceptance_report(
            stagger_profile,
            working_directory=profile.working_directory,
            acceptance_criteria=acceptance_criteria,
        )
        if stagger_acceptance["status"] != "ready":
            raise LocalEntryError(
                "GTFO stagger Runtime admission blocked: "
                + "; ".join(
                    str(item) for item in stagger_acceptance["blockers"]
                )
            )
    return {
        "requested": True,
        "evidence_source": "gtfo_real_runtime_automation",
        "capability_scope": "runtime_harness_preflight",
        "allow_game_launch": allow_game_launch,
        "authorization_scope": "this_run_only" if allow_game_launch else None,
        "settings_enabled": True,
        "profile": {
            "profile_id": profile.profile_id,
            "game_executable": profile.game_executable,
            "working_directory": profile.working_directory,
            "launch_args": list(profile.launch_args),
            "log_paths": list(profile.log_paths),
            "screenshot_directory": profile.screenshot_directory,
            "screenshot_timeout_seconds": profile.screenshot_timeout_seconds,
            "startup_markers": list(profile.startup_markers),
            "acceptance_markers": dict(profile.acceptance_markers),
            "timeout_seconds": profile.timeout_seconds,
            "poll_interval_seconds": profile.poll_interval_seconds,
            "output_limit_chars": profile.output_limit_chars,
            "terminate_after_capture": profile.terminate_after_capture,
            "operator_completion_required": profile.operator_completion_required,
            "operator_completion_timeout_seconds": (
                profile.operator_completion_timeout_seconds
            ),
        },
        "capability_report": capability_report,
        "stagger_acceptance": stagger_acceptance,
        "plugin_deployment": {
            "requested": True,
            "destination_path": str(destination),
            "allow_game_directory_write": True,
            "restore_after_runtime": True,
            "performed_by_run_request": True,
            "verified_deployed_artifact_hash": False,
            "destination_existed_at_admission": destination.is_file(),
            "destination_sha256_at_admission": (
                hashlib.sha256(destination.read_bytes()).hexdigest()
                if destination.is_file()
                else None
            ),
        },
    }


def _runtime_resume_admission_snapshot(
    runtime_admission: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact admission payload bound to a Build resume."""

    return {
        "status": "admitted",
        "authorization_scope": "this_resume_only",
        "requested_side_effects": list(
            runtime_admission.get("requested_side_effects")
            or ["runtime_execution", "process_launch", "game_directory_write"]
        ),
        "authorized_side_effects": list(
            runtime_admission.get("authorized_side_effects")
            or (
                ["runtime_execution", "process_launch", "game_directory_write"]
                if (
                    runtime_admission.get("allow_game_launch") is True
                    and (
                        runtime_admission.get("plugin_deployment") or {}
                    ).get("allow_game_directory_write")
                    is True
                )
                else []
            )
        ),
        "provider": runtime_admission.get("evidence_source")
        or runtime_admission.get("provider"),
        "runtime_admission": dict(runtime_admission),
    }


def _runtime_graph_options(
    settings: Any,
    *,
    run_gtfo_runtime: bool,
    allow_game_launch: bool,
) -> dict[str, Any]:
    """Select compile-only or Runtime-through-terminal graph routing."""

    return {
        "settings": settings if run_gtfo_runtime else None,
        "allow_game_launch": allow_game_launch if run_gtfo_runtime else False,
        "stop_after_build": not run_gtfo_runtime,
    }


def _runtime_verification_chain(
    graph_result: Mapping[str, Any],
    *,
    requested: bool,
) -> dict[str, Any]:
    """Project the Runtime-to-terminal Artifact chain into the run result."""

    artifacts = graph_result.get("artifacts") or {}
    refs = {
        artifact_type: artifacts.get(artifact_type)
        for artifact_type in (
            "build_result",
            "runtime_evidence",
            "eval_report",
            "workflow_summary",
        )
    }
    return {
        "requested": requested,
        "artifact_refs": refs,
        "workflow_chain_completed": bool(
            requested
            and graph_result.get("current_stage") == "done"
            and all(isinstance(ref, str) and ref for ref in refs.values())
        ),
    }


def _verified_build_artifact_sha256(
    build: Mapping[str, Any],
    *,
    expected_artifact: str,
) -> str:
    """Read the one verified physical build hash used for deployment."""

    if build.get("claims_real_build_success") is not True:
        raise LocalEntryError(
            "Runtime plugin deployment requires a successful real Build."
        )
    matches = [
        item
        for item in build.get("verified_artifacts") or ()
        if isinstance(item, Mapping) and item.get("path") == expected_artifact
    ]
    if len(matches) != 1:
        raise LocalEntryError(
            "Runtime plugin deployment requires exactly one verified expected artifact."
        )
    artifact_sha256 = matches[0].get("sha256")
    if not isinstance(artifact_sha256, str) or not artifact_sha256:
        raise LocalEntryError(
            "Verified expected artifact is missing its physical SHA256."
        )
    return artifact_sha256


def _make_deploying_runtime_evidence_factory(
    *,
    settings: Any,
    allow_game_launch: bool,
    allow_game_directory_write: bool,
    build_artifact_path: Path,
    expected_artifact: str,
    destination_path: Path,
    backup_directory: Path,
    expected_destination_existed: bool | None = None,
    expected_destination_sha256: str | None = None,
    expected_config_destination_existed: bool | None = None,
    expected_config_destination_sha256: str | None = None,
    runtime_output_directory: Path | None = None,
    runtime_observation_retry: Mapping[str, Any] | None = None,
    operator_completion_directory: Path | None = None,
    runtime_run_id: str | None = None,
    repair_attempt_projection: Mapping[str, Any] | None = None,
    runtime_attempt_namespace: str | None = None,
) -> Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Wrap the existing GTFO runner with verified temporary deployment."""

    stagger_profile = stagger_profile_from_settings(settings)
    if stagger_profile is not None:
        base_profile = profile_from_settings(settings)
        if runtime_output_directory is not None:
            base_profile = replace(
                base_profile,
                screenshot_directory=str(
                    runtime_output_directory / "runtime_captures"
                ),
            )
        stagger_factory = make_gtfo_stagger_runtime_evidence_factory(
            base_profile=base_profile,
            stagger_profile=stagger_profile,
            allow_game_launch=allow_game_launch,
            allow_game_directory_write=allow_game_directory_write,
            build_artifact_path=build_artifact_path,
            expected_artifact=expected_artifact,
            plugin_destination_path=destination_path,
            backup_directory=backup_directory,
            expected_plugin_destination_existed=expected_destination_existed,
            expected_plugin_destination_sha256=expected_destination_sha256,
            expected_config_destination_existed=(
                expected_config_destination_existed
            ),
            expected_config_destination_sha256=(
                expected_config_destination_sha256
            ),
            operator_completion_reader=(
                make_operator_completion_file_reader(
                    operator_completion_directory
                )
                if operator_completion_directory is not None
                else None
            ),
            attempt_output_root=runtime_output_directory,
            run_id=runtime_run_id,
            repair_attempt_projection=repair_attempt_projection,
            runtime_attempt_namespace=runtime_attempt_namespace,
            observation_retry_binding=runtime_observation_retry,
        )
        if runtime_observation_retry is None:
            return stagger_factory

        def retry_stagger_factory(
            feature_id: str,
            build: dict[str, Any],
            feature_spec: dict[str, Any],
        ) -> dict[str, Any]:
            payload = stagger_factory(feature_id, build, feature_spec)
            payload["runtime_observation_retry"] = dict(
                runtime_observation_retry
            )
            return payload

        return retry_stagger_factory

    if runtime_output_directory is not None or runtime_observation_retry is not None:
        raise LocalEntryError(
            "Runtime output isolation is supported only for the reviewed "
            "Stagger profile."
        )

    base_factory = make_gtfo_runtime_evidence_factory_from_settings(
        settings,
        allow_game_launch=allow_game_launch,
        process_diagnostic_directory=(
            backup_directory.parent / "runtime_process_diagnostics"
        ),
    )

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, Any],
        feature_spec: dict[str, Any],
    ) -> dict[str, Any]:
        expected_sha256 = _verified_build_artifact_sha256(
            build,
            expected_artifact=expected_artifact,
        )
        with temporarily_deploy_verified_plugin(
            source_path=build_artifact_path,
            destination_path=destination_path,
            backup_directory=backup_directory,
            expected_source_sha256=expected_sha256,
            allow_game_directory_write=allow_game_directory_write,
            expected_destination_existed=expected_destination_existed,
            expected_destination_sha256=expected_destination_sha256,
        ) as deployment:
            payload = base_factory(feature_id, build, feature_spec)
        return bind_plugin_deployment_to_runtime_payload(
            payload,
            deployment=deployment,
        )

    return runtime_evidence_factory


def run_local_request(
    *,
    description: str,
    target_project: str | Path,
    workspace_base: str | Path,
    settings_path: str | Path,
    api_key_env: str = "DASHSCOPE_API_KEY",
    base_url_env: str = "DASHSCOPE_BASE_URL",
    confirm_isolated_write: bool,
    allow_build: bool,
    allow_source_disclosure: bool,
    run_gtfo_runtime: bool = False,
    allow_game_launch: bool = False,
    runtime_plugin_destination: str | Path | None = None,
    allow_game_directory_write: bool = False,
    diff_approval_reader: Callable[[dict[str, Any]], str] | None = None,
    source_disclosure_approval_id: str | None = None,
    source_revision_binding: Mapping[str, str] | None = None,
    compiled_artifact_verifier: Callable[[Path, str], dict[str, Any]] | None = None,
    compiled_artifact_inspection_profile: (
        CompiledArtifactInspectionProfile | None
    ) = None,
    source_change_verifier: (
        Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]] | None
    ) = None,
    completion_classification: Mapping[str, bool] | None = None,
    local_ollama: bool = False,
    ollama_base_url: str = "http://127.0.0.1:11434",
    ollama_model: str | None = None,
    ollama_max_output_tokens: int = 4096,
    ollama_context_window: int | None = None,
    ollama_model_identity_reader: OllamaModelIdentityReader | None = None,
    ollama_server_version_reader: OllamaServerVersionReader | None = None,
) -> dict[str, Any]:
    """Run one request through the existing graph against an isolated target copy."""

    if not description.strip():
        raise LocalEntryError("run-request requires a non-empty natural-language request.")
    if local_ollama and allow_source_disclosure:
        raise LocalEntryError(
            "Choose exactly one model boundary: --local-ollama or "
            "--allow-source-disclosure."
        )
    if not local_ollama and not allow_source_disclosure:
        raise LocalEntryError(
            "run-request requires --allow-source-disclosure before reading local "
            "target source or calling the configured external LLM."
        )
    if not confirm_isolated_write:
        raise LocalEntryError("run-request requires --confirm-isolated-write.")
    if not allow_build:
        raise LocalEntryError("run-request requires --allow-build for the real build step.")
    if diff_approval_reader is None:
        raise LocalEntryError("run-request requires an exact diff approval reader.")
    if (
        compiled_artifact_verifier is not None
        and compiled_artifact_inspection_profile is not None
    ):
        raise LocalEntryError(
            "Choose either an injected compiled artifact verifier or a run-local "
            "inspection profile."
        )
    settings = load_settings(settings_path)
    runtime_admission = _runtime_admission_record(
        settings,
        run_gtfo_runtime=run_gtfo_runtime,
        allow_game_launch=allow_game_launch,
        runtime_plugin_destination=runtime_plugin_destination,
        allow_game_directory_write=allow_game_directory_write,
    )
    runtime_graph_options = _runtime_graph_options(
        settings,
        run_gtfo_runtime=run_gtfo_runtime,
        allow_game_launch=allow_game_launch,
    )
    local_model_identity: dict[str, Any] | None = None
    local_ollama_server_version: str | None = None
    identity_reader = ollama_model_identity_reader or _read_ollama_model_identity
    server_version_reader = (
        ollama_server_version_reader or _read_ollama_server_version
    )
    api_key: str | None = None
    if local_ollama:
        if not isinstance(ollama_model, str) or not ollama_model.strip():
            raise LocalEntryError(
                "run-request --local-ollama requires an exact --ollama-model "
                "read from /api/tags."
            )
        if ollama_max_output_tokens <= 0:
            raise LocalEntryError("--ollama-max-output-tokens must be positive.")
        if ollama_context_window is None:
            raise LocalEntryError(
                "run-request --local-ollama requires an explicit "
                "--ollama-context-window."
            )
        if (
            isinstance(ollama_context_window, bool)
            or not isinstance(ollama_context_window, int)
            or ollama_context_window <= 0
        ):
            raise LocalEntryError("--ollama-context-window must be a positive integer.")
        if ollama_context_window <= ollama_max_output_tokens:
            raise LocalEntryError(
                "--ollama-context-window must exceed "
                "--ollama-max-output-tokens."
            )
        try:
            llm_base_url = validate_loopback_http_base_url(ollama_base_url)
        except ValueError as exc:
            raise LocalEntryError(str(exc)) from exc
        local_model_identity = identity_reader(llm_base_url, ollama_model)
        _validate_ollama_model_identity(
            local_model_identity,
            expected_base_url=llm_base_url,
            expected_model=ollama_model,
        )
        local_model_context_limit = _validate_ollama_context_window(
            local_model_identity,
            requested_context_window=ollama_context_window,
        )
        local_ollama_server_version = server_version_reader(llm_base_url)
        settings = replace(
            settings,
            llm=replace(
                settings.llm,
                provider="ollama",
                model=ollama_model,
                max_tokens=ollama_max_output_tokens,
                api_key=None,
                base_url=llm_base_url,
            ),
        )
        try:
            llm = LLMFactory.create(
                settings,
                base_url=llm_base_url,
                context_window=ollama_context_window,
            )
        except Exception as exc:
            raise LocalEntryError(
                f"Local Ollama initialization failed: {type(exc).__name__}."
            ) from exc
        if not isinstance(llm, OllamaLLM):
            raise LocalEntryError("Local model selection did not create OllamaLLM.")
        source_disclosure = _local_no_external_disclosure_record()
        model_admission = _local_model_admission_record(
            model_identity=local_model_identity,
            provider_adapter=f"{type(llm).__module__}.{type(llm).__qualname__}",
        )
    else:
        local_model_context_limit = None
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LocalEntryError(
                f"Required API key environment variable is missing: {api_key_env}"
            )
        llm_base_url = os.environ.get(base_url_env) or settings.llm.base_url
        if not llm_base_url:
            raise LocalEntryError(
                "Required LLM base URL is missing from settings and environment: "
                f"{base_url_env}"
            )
        _sanitized_endpoint_url(llm_base_url)
        llm = LLMFactory.create(
            settings,
            api_key=api_key,
            base_url=llm_base_url,
        )
    started_at = datetime.now(timezone.utc).isoformat()
    if not local_ollama:
        source_disclosure = _source_disclosure_record(
            provider=settings.llm.provider,
            model=settings.llm.model,
            base_url=llm_base_url,
            approved_at=started_at,
            approval_id=source_disclosure_approval_id,
            provider_adapter=f"{type(llm).__module__}.{type(llm).__qualname__}",
            destination_url=(
                f"{str(getattr(llm, 'base_url')).rstrip('/')}/chat/completions"
                if getattr(llm, "base_url", None)
                else None
            ),
        )
        model_admission = _external_model_admission_record(source_disclosure)

    ollama_patch_generation_profile = (
        {
            "stream": False,
            "think": False,
            "tools_sent": False,
            "native_json_schema_required": True,
            "output_budget": ollama_max_output_tokens,
            "context_window": ollama_context_window,
            "model_context_limit": local_model_context_limit,
            "pre_call_context_admission": (
                "provider_body_utf8_proxy_plus_output_budget_v1"
            ),
            "exact_prompt_tokens_available_pre_call": False,
            "timeout_seconds": getattr(llm, "timeout", None),
            "trust_environment": False,
            "follow_redirects": False,
            "automatic_provider_fallback": False,
            "automatic_retry": False,
            "model_switching": False,
            "diagnostic_content_max_utf8_bytes": (
                LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES
            ),
        }
        if local_ollama
        else None
    )

    source = Path(target_project).resolve()
    if not source.is_dir() or not any(source.glob("*.csproj")):
        raise LocalEntryError("Target project must be an existing directory with a .csproj file.")
    initial_source_snapshot = _source_snapshot(source)
    initial_source_snapshot_sha256 = _source_snapshot_sha256(initial_source_snapshot)
    _verify_source_revision_binding(
        source=source,
        snapshot=initial_source_snapshot,
        snapshot_sha256=initial_source_snapshot_sha256,
        binding=source_revision_binding,
    )
    base = Path(workspace_base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex[:8]
    request_id = f"request_{run_id}"
    run_root = (base / run_id).resolve()
    run_root.mkdir(parents=True)
    initial_manifest = {
        "run_id": run_id,
        "request_id": request_id,
        "status": "admitted",
        "started_at": started_at,
        "request": description,
        "target_source": str(source),
        "target_source_provenance": "externally_produced_read_only_input",
        "isolated_workspace": str(run_root),
        "source_snapshot": initial_source_snapshot,
        "source_snapshot_sha256": initial_source_snapshot_sha256,
        "source_revision_binding": dict(source_revision_binding or {}),
        "model": settings.llm.model,
        "model_admission": model_admission,
        "local_model_identity": local_model_identity,
        "ollama_server_version": local_ollama_server_version,
        "ollama_patch_generation_profile": ollama_patch_generation_profile,
        "source_disclosure": source_disclosure,
        "runtime_admission": runtime_admission,
        "compiled_artifact_inspection_profile": (
            compiled_artifact_inspection_profile.to_dict()
            if compiled_artifact_inspection_profile is not None
            else None
        ),
        "model_call_count": 0,
        "graph_invoked": False,
        "patch_payload_parser_entered": False,
        "actual_write_performed": False,
    }
    (run_root / "run_manifest.json").write_text(
        json.dumps(initial_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    target_copy = run_root / "generated_mods" / source.name
    baseline_copy = run_root / "baseline_source" / source.name
    target_copy.parent.mkdir(parents=True)
    baseline_copy.parent.mkdir(parents=True)
    _run_pre_graph_step(
        failure_stage="workspace_preparation",
        action=lambda: tuple(
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns("bin", "obj", ".git", ".idea"),
            )
            for destination in (target_copy, baseline_copy)
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    source_projects = tuple(source.glob("*.csproj"))
    if len(source_projects) != 1:
        error = LocalEntryError(
            "Target project must contain exactly one top-level .csproj file."
        )
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage="workspace_preparation",
            error=error,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
        )
        raise error
    source_project = source_projects[0]
    assembly_name = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _project_text_property(
            source_project,
            property_name="AssemblyName",
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    source_bepinex_dir = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _resolve_project_path_property(
            source_project,
            property_name="BepInExDir",
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    if not source_bepinex_dir.is_dir():
        error = LocalEntryError(f"Resolved BepInExDir is missing: {source_bepinex_dir}")
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage="baseline_profile",
            error=error,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
        )
        raise error
    isolated_bepinex_dir = run_root / "build_dependencies" / "BepInEx"
    isolated_bepinex_dir.parent.mkdir(parents=True)
    _run_pre_graph_step(
        failure_stage="build_dependency_preparation",
        action=lambda: shutil.copytree(source_bepinex_dir, isolated_bepinex_dir),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    nuget_build_profile = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _create_nuget_isolated_build_profile(
            run_root=run_root,
            working_directory=target_copy,
            config_file=target_copy / "nuget.config",
            bepinex_dir=isolated_bepinex_dir,
            timeout_seconds=120,
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    baseline_build_profile = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _create_nuget_isolated_build_profile(
            run_root=run_root,
            working_directory=baseline_copy,
            config_file=baseline_copy / "nuget.config",
            bepinex_dir=isolated_bepinex_dir,
            timeout_seconds=120,
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    verification_tool_build = None
    inspector_path: Path | None = None
    active_compiled_artifact_verifier = compiled_artifact_verifier
    if compiled_artifact_inspection_profile is not None:
        verification_tool_build = _run_pre_graph_step(
            failure_stage="verification_tool_build",
            action=lambda: _build_run_local_il_inspector(
                compiled_artifact_inspection_profile,
                run_root=run_root,
            ),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
        )
        inspector_path = Path(str(verification_tool_build["inspector_path"]))

        def verify_compiled_artifact(artifact: Path, stage: str) -> dict[str, Any]:
            return {
                **_verify_bepin_plugin_identity(
                    artifact,
                    inspector_path=inspector_path,
                    method_symbol=compiled_artifact_inspection_profile.method_symbol,
                    expected_guid=compiled_artifact_inspection_profile.expected_guid,
                    expected_name=compiled_artifact_inspection_profile.expected_name,
                    expected_version=compiled_artifact_inspection_profile.expected_version,
                ),
                "verification_stage": stage,
                "verification_tool_sha256": verification_tool_build[
                    "inspector_sha256"
                ],
            }

        active_compiled_artifact_verifier = verify_compiled_artifact
    baseline_stdout = run_root / "baseline_build.stdout.log"
    baseline_stderr = run_root / "baseline_build.stderr.log"
    baseline = _run_pre_graph_step(
        failure_stage="baseline_build",
        action=lambda: _run_nuget_isolated_build(baseline_build_profile),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
        extra={"verification_tool_build": verification_tool_build},
    )
    baseline_stdout.write_text(baseline.stdout, encoding="utf-8")
    baseline_stderr.write_text(baseline.stderr, encoding="utf-8")
    expected_artifact = f"bin/Debug/{assembly_name}.dll"
    if run_gtfo_runtime:
        admitted_destination = Path(
            str(runtime_admission["plugin_deployment"]["destination_path"])
        )
        if admitted_destination.name != f"{assembly_name}.dll":
            error = LocalEntryError(
                "Runtime plugin destination filename must exactly match the "
                f"built assembly name: {assembly_name}.dll"
            )
            _persist_pre_graph_failure(
                run_root=run_root,
                run_id=run_id,
                request_id=request_id,
                failure_stage="runtime_admission",
                error=error,
                source_revision_binding=source_revision_binding,
                model_admission=model_admission,
            )
            raise error
    baseline_artifact = baseline_copy / expected_artifact
    baseline_stat = baseline_artifact.stat() if baseline_artifact.is_file() else None
    baseline_result = {
        **baseline.to_dict(),
        "artifact_exists": baseline_artifact.is_file(),
        "artifact_sha256": (
            hashlib.sha256(baseline_artifact.read_bytes()).hexdigest()
            if baseline_artifact.is_file()
            else None
        ),
        "artifact_path": str(baseline_artifact),
        "artifact_size_bytes": baseline_stat.st_size if baseline_stat is not None else None,
        "artifact_mtime_utc": (
            datetime.fromtimestamp(baseline_stat.st_mtime, tz=timezone.utc).isoformat()
            if baseline_stat is not None
            else None
        ),
        "stdout_path": str(baseline_stdout),
        "stderr_path": str(baseline_stderr),
        "build_profile": baseline_build_profile.to_dict(),
    }
    if baseline.exit_code != 0 or not baseline_result["artifact_exists"]:
        failure_stage = (
            "baseline_restore"
            if baseline.restore_exit_code != 0
            else "baseline_build"
            if baseline.build_exit_code not in (None, 0)
            else "baseline_artifact_missing"
        )
        error = LocalEntryError(
            "Unmodified isolated baseline build failed; code generation was not started."
        )
        _persist_pre_graph_failure(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            failure_stage=failure_stage,
            error=error,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra={
                "baseline_build": baseline_result,
                "verification_tool_build": verification_tool_build,
            },
        )
        raise error
    if baseline_artifact.is_file() and active_compiled_artifact_verifier is not None:
        baseline_result["compiled_artifact_verification"] = _run_pre_graph_step(
            failure_stage="baseline_artifact_verification",
            action=lambda: active_compiled_artifact_verifier(
                baseline_artifact,
                "baseline",
            ),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra={
                "baseline_build": baseline_result,
                "verification_tool_build": verification_tool_build,
            },
        )
    generator = LLMExactPatchGenerator(llm)
    applier = ExactTextPatchApplier()
    evidence_provider = RgLiveEvidenceProvider(run_root)
    member_access_resolver = (
        RunLocalMemberAccessResolver(
            inspector_path,
            dependency_root=isolated_bepinex_dir,
        )
        if inspector_path is not None
        else None
    )
    artifact_store = ArtifactStore(run_root / "a")
    build_stdout = run_root / "build.stdout.log"
    build_stderr = run_root / "build.stderr.log"
    pending_dry_run: dict[str, Any] | None = None
    external_model_input_audit: dict[str, Any] | None = None
    local_model_input_audit: dict[str, Any] | None = None
    model_call_count = 0

    def evidence_factory(state: dict[str, Any], _: dict[str, Any]):
        evidence_pack = evidence_provider.collect(
            query=requested_scope_text(state["user_request"]),
            search_root=f"generated_mods/{source.name}",
            source_identity_query=state["user_request"],
        )
        if member_access_resolver is None:
            return evidence_pack
        try:
            return enrich_source_evidence_with_member_accesses(
                evidence_pack,
                consumer_assembly=baseline_artifact,
                resolver=member_access_resolver,
            )
        except DotNetMetadataEnrichmentError as exc:
            blocker = {
                "code": "DOTNET_MEMBER_ACCESS_UNRESOLVED",
                "message": str(exc),
                "needed_evidence": [
                    "source-bound compiled receiver identity",
                    "AssemblyRef-bound run-local dependency",
                    "public readable direct Boolean property",
                ],
            }
            return replace(
                evidence_pack,
                readiness="insufficient",
                can_generate_patch=False,
                blockers=(*evidence_pack.blockers, blocker),
                missing_evidence=(
                    *evidence_pack.missing_evidence,
                    {
                        "needed_evidence": "verified .NET member access",
                        "blocker_code": blocker["code"],
                        "reason": blocker["message"],
                    },
                ),
                message=(
                    "Source evidence was found, but run-local .NET member "
                    f"semantics could not be bound: {exc}"
                ),
            )

    def patch_change_factory(
        state: dict[str, Any],
        implementation: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        nonlocal external_model_input_audit, local_model_input_audit, model_call_count
        if local_ollama:
            if local_model_identity is None or ollama_model is None:
                raise LocalEntryError("Local Ollama model identity is missing.")
            current_identity = identity_reader(llm_base_url, ollama_model)
            _validate_ollama_model_identity(
                current_identity,
                expected_base_url=llm_base_url,
                expected_model=ollama_model,
            )
            _assert_ollama_model_identity_stable(
                expected=local_model_identity,
                observed=current_identity,
            )
            _validate_ollama_context_window(
                current_identity,
                requested_context_window=ollama_context_window,
            )
        else:
            _verify_source_disclosure(
                source_disclosure,
                requested_data_classes=SOURCE_DISCLOSURE_DATA_CLASSES,
            )
        external_evidence = _external_evidence_items(
            list(evidence_pack.get("items") or [])
        )
        required_change_units = [
            {
                key: item.get(key)
                for key in (
                    "change_id",
                    "change_type",
                    "edit_binding_id",
                    "hook_target_binding_id",
                    "supporting_binding_ids",
                    "operation",
                )
            }
            for item in implementation.get("proposed_changes") or []
            if isinstance(item, dict)
        ]
        model_input = {
            "request": state["user_request"],
            "evidence": external_evidence,
            "binding_registry": dict(implementation.get("binding_registry") or {}),
            "required_change_units": required_change_units,
            "side_effect_boundaries": [
                str(item) for item in implementation.get("side_effect_boundaries") or []
            ],
        }
        _assert_no_absolute_local_paths(model_input)
        model_input_audit = {
            "approval_id": source_disclosure.get("approval_id"),
            "provider_adapter": model_admission.get("provider_adapter"),
            "destination": model_admission.get("destination"),
            "approved_data_classes": source_disclosure.get("approved_data_classes"),
            "payload_sha256": _sha256_json(model_input),
            "absolute_local_paths_present": False,
            "api_key_in_payload": False,
            "automatic_provider_fallback": False,
            "automatic_external_retry": False,
            "execution_locality": model_admission.get("execution_locality"),
            "external_disclosure_occurred": not local_ollama,
        }
        if not local_ollama:
            (run_root / "external_model_input_audit.json").write_text(
                json.dumps(
                    model_input_audit,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            external_model_input_audit = model_input_audit
        def record_local_provider_request(provider_request: dict[str, Any]) -> None:
            nonlocal local_model_input_audit, model_call_count
            if not local_ollama:
                raise LocalEntryError(
                    "Local provider request recorder cannot be used externally."
                )
            if local_model_input_audit is not None or model_call_count != 0:
                raise LocalEntryError("LOCAL_PATCH_GENERATION_CALL_ALREADY_RECORDED")
            if local_ollama_server_version is None or local_model_identity is None:
                raise LocalEntryError("Local Ollama environment binding is missing.")
            attempt = {
                **model_input_audit,
                "status": "ready_for_provider_invocation",
                "run_id": run_id,
                "request_id": state["request_id"],
                "model_call_count": 0,
                "remaining_call_budget": 1,
                "output_budget": ollama_max_output_tokens,
                "context_window": ollama_context_window,
                "model_context_limit": local_model_context_limit,
                "ollama_server_version": local_ollama_server_version,
                "model_identity": dict(local_model_identity),
                "source_revision_binding": dict(source_revision_binding or {}),
                "source_snapshot_sha256": initial_source_snapshot_sha256,
                "generation_input_binding": {
                    "request_sha256": hashlib.sha256(
                        str(model_input["request"]).encode("utf-8")
                    ).hexdigest(),
                    "evidence_pack_ref": state["artifacts"].get("evidence_pack"),
                    "evidence_pack_hash": state["artifact_hashes"].get(
                        "evidence_pack"
                    ),
                    "implementation_plan_ref": state["artifacts"].get(
                        "implementation_plan"
                    ),
                    "implementation_plan_hash": state["artifact_hashes"].get(
                        "implementation_plan"
                    ),
                    "editable_paths": [
                        str(item) for item in implementation.get("target_files") or []
                    ],
                    "change_scope": [
                        str(item)
                        for item in implementation.get("side_effect_boundaries") or []
                    ],
                },
                "provider_request": dict(provider_request),
                "provider_request_profile": {
                    "stream": False,
                    "think": False,
                    "tools_sent": False,
                    "native_json_schema_requested": True,
                    "timeout_seconds": provider_request.get("timeout_seconds"),
                    "trust_environment": provider_request.get("trust_environment"),
                    "follow_redirects": provider_request.get("follow_redirects"),
                    "automatic_provider_fallback": False,
                    "automatic_retry": False,
                    "model_switching": False,
                },
            }
            (run_root / "local_model_input_audit.json").write_text(
                json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            local_model_input_audit = attempt
            model_call_count = 1

        def enforce_post_response_model_binding(_: Any) -> None:
            if local_model_identity is None or ollama_model is None:
                raise LocalEntryError("Local Ollama model identity is missing.")
            observed_identity = identity_reader(llm_base_url, ollama_model)
            _validate_ollama_model_identity(
                observed_identity,
                expected_base_url=llm_base_url,
                expected_model=ollama_model,
            )
            _assert_ollama_model_identity_stable(
                expected=local_model_identity,
                observed=observed_identity,
            )
            _validate_ollama_context_window(
                observed_identity,
                requested_context_window=ollama_context_window,
            )

        required_validation_by_binding = {
            str(item["edit_binding_id"]): [
                str(value) for value in item.get("expected_validation") or []
            ]
            for item in implementation.get("proposed_changes") or []
            if isinstance(item, dict) and item.get("edit_binding_id")
        }
        generated = generator.generate(
            user_request=str(model_input["request"]),
            evidence_items=list(model_input["evidence"]),
            binding_registry=dict(model_input["binding_registry"]),
            constraints=list(model_input["side_effect_boundaries"]),
            required_change_units=required_change_units,
            required_validation_by_binding=required_validation_by_binding,
            require_native_schema=local_ollama,
            provider_request_recorder=(
                record_local_provider_request if local_ollama else None
            ),
            post_response_admission=(
                enforce_post_response_model_binding if local_ollama else None
            ),
        )
        if local_ollama and generated.model != ollama_model:
            raise LocalEntryError("OLLAMA_RESPONSE_MODEL_IDENTITY_MISMATCH")
        planned_by_unit = {
            (
                str(item.get("change_id") or ""),
                str(item.get("edit_binding_id") or ""),
            ): item
            for item in implementation.get("proposed_changes") or []
            if isinstance(item, dict)
            and item.get("change_id")
            and item.get("edit_binding_id")
        }
        changes: list[dict[str, Any]] = []
        for generated_change in generated.changes:
            binding_id = str(generated_change["edit_binding_id"])
            change_id = str(generated_change["change_id"])
            planned = planned_by_unit.get((change_id, binding_id))
            if planned is None:
                raise LocalEntryError(
                    "Generated patch is outside implementation-plan change units."
                )
            changes.append(
                {
                    **planned,
                    "rationale": generated_change["rationale"],
                    "expected_validation": generated_change["expected_validation"],
                    "rollback_hint": generated_change["rollback_hint"],
                    "patch": generated_change["patch"],
                    "generation": {
                        "provider": settings.llm.provider,
                        "model": generated.model,
                        "model_digest": (
                            local_model_identity.get("digest")
                            if local_model_identity is not None
                            else None
                        ),
                        "usage": generated.usage,
                        "api_key_env": None if local_ollama else api_key_env,
                    },
                }
            )
        return tuple(changes)

    def dry_run_factory(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal pending_dry_run
        pending_dry_run = applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=implementation,
            review=review,
            allow_write=False,
        )
        return pending_dry_run

    def isolated_apply_factory(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        if pending_dry_run is None:
            raise LocalEntryError("Exact diff approval requested before dry-run completed.")
        approved_diff_hash = _read_exact_diff_approval(
            diff_approval_reader,
            pending_dry_run,
        )
        return applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=implementation,
            review=review,
            allow_write=True,
            approved_diff_hash=approved_diff_hash,
        )

    def build_result_factory(feature_id: str, input_execution_mode: str | None):
        profile = BuildProfile(
            profile_id=nuget_build_profile.profile_id,
            build_system="dotnet",
            working_directory=str(target_copy),
            command=nuget_build_profile.build_command,
            timeout_seconds=nuget_build_profile.timeout_seconds,
            expected_artifacts=(expected_artifact,),
        )

        def command_runner(selected: BuildProfile) -> BuildCommandResult:
            if selected.command != nuget_build_profile.build_command:
                raise LocalEntryError("Final build command does not match the bound profile.")
            completed = _run_nuget_isolated_build(nuget_build_profile)
            build_stdout.write_text(completed.stdout, encoding="utf-8")
            build_stderr.write_text(completed.stderr, encoding="utf-8")
            return BuildCommandResult(
                exit_code=completed.exit_code,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=completed.duration_ms,
            )

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=profile,
            command_runner=command_runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    direct_stagger_admission = runtime_admission.get("stagger_acceptance")
    direct_stagger_config = (
        direct_stagger_admission.get("config")
        if isinstance(direct_stagger_admission, Mapping)
        else None
    )
    runtime_evidence_factory = (
        _make_deploying_runtime_evidence_factory(
            settings=settings,
            allow_game_launch=allow_game_launch,
            allow_game_directory_write=allow_game_directory_write,
            build_artifact_path=target_copy / expected_artifact,
            expected_artifact=expected_artifact,
            destination_path=Path(
                str(runtime_admission["plugin_deployment"]["destination_path"])
            ),
            backup_directory=run_root / "runtime_deployment_backup",
            expected_destination_existed=bool(
                runtime_admission["plugin_deployment"][
                    "destination_existed_at_admission"
                ]
            ),
            expected_destination_sha256=runtime_admission["plugin_deployment"][
                "destination_sha256_at_admission"
            ],
            expected_config_destination_existed=(
                bool(direct_stagger_config["destination_existed"])
                if isinstance(direct_stagger_config, Mapping)
                else None
            ),
            expected_config_destination_sha256=(
                direct_stagger_config.get("destination_sha256")
                if isinstance(direct_stagger_config, Mapping)
                else None
            ),
        )
        if run_gtfo_runtime
        else None
    )

    manifest = {
        "run_id": run_id,
        "request_id": request_id,
        "status": "baseline_verified",
        "started_at": started_at,
        "request": description,
        "target_source": str(source),
        "target_source_provenance": "externally_produced_read_only_input",
        "isolated_workspace": str(run_root),
        "source_snapshot": initial_source_snapshot,
        "source_snapshot_sha256": initial_source_snapshot_sha256,
        "source_revision_binding": dict(source_revision_binding or {}),
        "model": settings.llm.model,
        "model_admission": model_admission,
        "local_model_identity": local_model_identity,
        "ollama_server_version": local_ollama_server_version,
        "ollama_patch_generation_profile": ollama_patch_generation_profile,
        "base_url": _sanitized_endpoint_url(llm_base_url),
        "base_url_env": None if local_ollama else base_url_env,
        "base_url_env_present": (
            False if local_ollama else bool(os.environ.get(base_url_env))
        ),
        "api_key_env": None if local_ollama else api_key_env,
        "api_key_required": not local_ollama,
        "api_key_read": not local_ollama,
        "api_key_present": False if local_ollama else True,
        "api_key_value_persisted": False,
        "source_disclosure": source_disclosure,
        "runtime_admission": runtime_admission,
        "assembly_name": assembly_name,
        "build_dependency": {
            "source": str(source_bepinex_dir),
            "isolated_copy": str(isolated_bepinex_dir),
            "build_uses_isolated_copy": True,
        },
        "nuget_isolated_build_profile": nuget_build_profile.to_dict(),
        "compiled_artifact_inspection_profile": (
            compiled_artifact_inspection_profile.to_dict()
            if compiled_artifact_inspection_profile is not None
            else None
        ),
        "verification_tool_build": verification_tool_build,
        "baseline_build": baseline_result,
        "model_call_count": 0,
        "graph_invoked": False,
        "patch_payload_parser_entered": False,
        "actual_write_performed": False,
        "limits": [
            "No claim that the external BetterHitFeedback project was generated by this platform.",
            (
                "No real GTFO launch or gameplay validation is performed."
                if not run_gtfo_runtime
                else (
                    "Runtime evidence proves only the process, logs, markers, and "
                    "screenshot facts bound by this run."
                )
            ),
            (
                (
                    "run-request does not deploy the built plugin into the GTFO "
                    "game directory or verify a deployed DLL hash."
                )
                if not run_gtfo_runtime
                else (
                    "The verified built plugin is deployed only for this Runtime "
                    "capture and the destination is restored afterward."
                )
            ),
            (
                "The dotnet process executes user-authorized project build logic "
                "and is not an OS sandbox."
            ),
        ],
    }
    (run_root / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _run_pre_graph_step(
        failure_stage="pre_graph_generated_directory_cleanup",
        action=lambda: tuple(
            _remove_generated_build_directory(generated_directory)
            for generated_directory in (target_copy / "bin", target_copy / "obj")
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
        extra={
            "baseline_build": baseline_result,
            "verification_tool_build": verification_tool_build,
        },
    )

    graph = build_graph(
        artifact_store,
        evidence_pack_factory=evidence_factory,
        patch_change_factory=patch_change_factory,
        dry_run_factory=dry_run_factory,
        isolated_apply_factory=isolated_apply_factory,
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
        use_default_proposal_git_binding=False,
        persist_build_runtime_handoff=not run_gtfo_runtime,
        **runtime_graph_options,
    )
    state = create_initial_state(
        run_id=run_id,
        request_id=request_id,
        user_request=description,
        target_domain="gtfo",
        target_mod=source.name,
        confirmed_isolated_write=True,
    )
    with _working_directory(run_root):
        try:
            result = graph.invoke(state)
        except Exception as exc:
            provider_failure = _persist_local_failure_diagnostics(
                run_root=run_root,
                error=exc,
                enabled=local_ollama,
            )
            _persist_graph_terminal_failure(
                run_root=run_root,
                run_id=run_id,
                request_id=request_id,
                error=exc,
                model_call_count=model_call_count,
                extra=(
                    {"provider_failure": provider_failure}
                    if provider_failure is not None
                    else None
                ),
            )
            raise LocalEntryError(f"Controlled graph failed: {type(exc).__name__}: {exc}") from exc

    final_build_succeeded = (
        result.get("build_summary", {}).get("claims_real_build_success") is True
    )
    final_artifact_verification = _verify_final_compiled_artifact_if_built(
        graph_result=result,
        target_copy=target_copy,
        expected_artifact=expected_artifact,
        verifier=active_compiled_artifact_verifier,
    )
    final_canonical_snapshot = _source_snapshot(source)
    canonical_source_unchanged = (
        final_canonical_snapshot == initial_source_snapshot
        and _source_snapshot_sha256(final_canonical_snapshot)
        == initial_source_snapshot_sha256
    )
    if not canonical_source_unchanged:
        raise LocalEntryError("Canonical source changed during the isolated run.")
    final_isolated_snapshot = _source_snapshot(target_copy)
    source_change_verification = None
    if final_build_succeeded and source_change_verifier is not None:
        source_change_verification = source_change_verifier(
            initial_source_snapshot,
            final_isolated_snapshot,
        )
    actual_write_performed = final_isolated_snapshot != initial_source_snapshot
    patch_payload_parser_entered = "patch_proposal" in (result.get("artifacts") or {})
    selected_classification = dict(completion_classification or {})
    if selected_classification:
        if result.get("build_summary", {}).get("claims_real_build_success") is not True:
            raise LocalEntryError(
                "Completion classification requires a real successful build."
            )
        if active_compiled_artifact_verifier is None or source_change_verifier is None:
            raise LocalEntryError(
                "Completion classification requires compiled artifact and source change verification."
            )

    summary = {
        "run_id": run_id,
        "current_stage": result["current_stage"],
        "feature_id": result.get("feature_id"),
        "blockers": result.get("blockers") or [],
        "artifacts": result.get("artifacts") or {},
        "build_summary": result.get("build_summary") or {},
        "runtime_summary": result.get("runtime_summary") or {},
        "runtime_admission": runtime_admission,
        "runtime_verification_chain": _runtime_verification_chain(
            result,
            requested=run_gtfo_runtime,
        ),
        "run_root": str(run_root),
        "build_stdout": str(build_stdout) if build_stdout.exists() else None,
        "build_stderr": str(build_stderr) if build_stderr.exists() else None,
        "source_revision_binding": dict(source_revision_binding or {}),
        "external_model_input_audit": external_model_input_audit,
        "local_model_input_audit": local_model_input_audit,
        "model_call_count": model_call_count,
        "graph_invoked": True,
        "patch_payload_parser_entered": patch_payload_parser_entered,
        "actual_write_performed": actual_write_performed,
        "model_admission": model_admission,
        "local_model_identity": local_model_identity,
        "verification_tool_build": verification_tool_build,
        "baseline_artifact_verification": baseline_result.get(
            "compiled_artifact_verification"
        ),
        "final_artifact_verification": final_artifact_verification,
        "canonical_source_unchanged": canonical_source_unchanged,
        "initial_isolated_source_snapshot": initial_source_snapshot,
        "final_isolated_source_snapshot": final_isolated_snapshot,
        "source_change_verification": source_change_verification,
        "completion_classification": selected_classification,
    }
    _persist_graph_terminal_result(
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        summary=summary,
        model_call_count=model_call_count,
        patch_payload_parser_entered=patch_payload_parser_entered,
        actual_write_performed=actual_write_performed,
    )
    return summary


def _load_runtime_continuation_handoff(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    resume_id: str | None = None,
    recover_accepted_resume: bool = False,
    retry_runtime_observation: bool = False,
    require_manifest: bool = True,
    allow_blocked_resume: bool = False,
    require_current_build_output: bool = True,
) -> _RuntimeContinuationHandoff:
    if recover_accepted_resume and retry_runtime_observation:
        raise LocalEntryError(
            "Accepted resume recovery and Runtime observation retry are "
            "mutually exclusive."
        )
    root = Path(run_root).resolve()
    if not root.is_dir():
        raise LocalEntryError("Runtime continuation run_root does not exist.")
    store_root = (
        Path(artifact_store_root).resolve()
        if artifact_store_root is not None
        else (root / "a").resolve()
    )
    if not store_root.is_dir():
        raise LocalEntryError("Runtime continuation ArtifactStore root does not exist.")
    resolved_checkpoint_path = Path(checkpoint_path).resolve()
    try:
        resolved_checkpoint_path.relative_to(store_root)
    except ValueError as exc:
        raise LocalEntryError(
            "Runtime continuation checkpoint is outside the selected ArtifactStore root."
        ) from exc

    artifact_store = ArtifactStore(store_root)
    checkpoint_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="workflow_checkpoint",
        path=str(resolved_checkpoint_path),
        artifact_hash=checkpoint_hash,
    )
    try:
        checkpoint = artifact_store.read(checkpoint_ref)["data"]
    except (OSError, ValueError) as exc:
        raise LocalEntryError(f"Runtime continuation checkpoint is invalid: {exc}") from exc
    if checkpoint.get("feature_id") != feature_id:
        raise LocalEntryError(
            "Runtime continuation feature_id does not match checkpoint."
        )
    if checkpoint.get("checkpoint_stage") != "build":
        raise LocalEntryError(
            "Runtime continuation requires a Build-stage checkpoint."
        )

    manifest: dict[str, Any] = {}
    if require_manifest:
        manifest_path = root / "run_manifest.json"
        if not manifest_path.is_file():
            raise LocalEntryError("Runtime continuation run_manifest.json is missing.")
        try:
            manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LocalEntryError(
                f"Runtime continuation run_manifest.json is invalid: {exc}"
            ) from exc
        if not isinstance(manifest_value, dict):
            raise LocalEntryError(
                "Runtime continuation run_manifest.json must contain an object."
            )
        manifest = manifest_value
        if (
            manifest.get("run_id") != checkpoint.get("run_id")
            or manifest.get("request_id") != checkpoint.get("request_id")
            or (
                manifest.get("feature_id") is not None
                and manifest.get("feature_id") != checkpoint.get("feature_id")
            )
        ):
            raise LocalEntryError(
                "Runtime continuation manifest identity does not match checkpoint."
            )
        manifest_checkpoint_ref = manifest.get("workflow_checkpoint_ref")
        manifest_checkpoint_hash = manifest.get("workflow_checkpoint_hash")
        if (
            manifest_checkpoint_ref is not None
            and Path(str(manifest_checkpoint_ref)).resolve()
            != resolved_checkpoint_path
        ) or (
            manifest_checkpoint_hash is not None
            and manifest_checkpoint_hash != checkpoint_hash
        ):
            raise LocalEntryError(
                "Runtime continuation manifest checkpoint binding does not match."
            )

    try:
        snapshot = checkpoint["state_snapshot"]
        feature_spec_ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type="feature_spec",
            path=snapshot["artifacts"]["feature_spec"],
            artifact_hash=snapshot["artifact_hashes"]["feature_spec"],
        )
        build_ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type="build_result",
            path=snapshot["artifacts"]["build_result"],
            artifact_hash=snapshot["artifact_hashes"]["build_result"],
        )
        feature_spec = artifact_store.read(feature_spec_ref)["data"]
        build = artifact_store.read(build_ref)["data"]
    except (KeyError, TypeError, OSError, ValueError) as exc:
        raise LocalEntryError(
            f"Runtime continuation BuildResult binding is invalid: {exc}"
        ) from exc
    if build.get("feature_id") != feature_id:
        raise LocalEntryError(
            "Runtime continuation BuildResult feature_id does not match checkpoint."
        )
    if require_manifest:
        manifest_build_ref = manifest.get("build_result_ref")
        manifest_build_hash = manifest.get("build_result_hash")
        if (
            manifest_build_ref is not None
            and Path(str(manifest_build_ref)).resolve()
            != Path(build_ref.path).resolve()
        ) or (
            manifest_build_hash is not None
            and manifest_build_hash != build_ref.artifact_hash
        ):
            raise LocalEntryError(
                "Runtime continuation manifest BuildResult binding does not match."
            )

    verified_artifacts = [
        item
        for item in build.get("verified_artifacts") or []
        if isinstance(item, Mapping)
    ]
    if len(verified_artifacts) != 1:
        raise LocalEntryError(
            "Runtime continuation requires exactly one verified Build output."
        )
    verified_artifact = verified_artifacts[0]
    resolved_path = verified_artifact.get("resolved_path")
    expected_hash = verified_artifact.get("sha256")
    expected_size = verified_artifact.get("size_bytes")
    expected_mtime = verified_artifact.get("mtime")
    if (
        not isinstance(resolved_path, str)
        or not isinstance(expected_hash, str)
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or isinstance(expected_mtime, bool)
        or not isinstance(expected_mtime, (int, float))
    ):
        raise LocalEntryError(
            "Runtime continuation Build output binding is incomplete."
        )
    if require_current_build_output:
        build_output = Path(resolved_path)
        if not build_output.is_file():
            raise LocalEntryError(
                "Runtime continuation verified Build output is missing."
            )
        stat = build_output.stat()
        if (
            hashlib.sha256(build_output.read_bytes()).hexdigest() != expected_hash
            or stat.st_size != expected_size
            or stat.st_mtime != float(expected_mtime)
        ):
            raise LocalEntryError(
                "Runtime continuation verified Build output identity changed."
            )

    recovery_decision = None
    recovery_resume_report_ref = None
    prior_runtime_evidence_ref = None
    prior_repair_plan_ref = None
    observation_retry_binding = None
    try:
        checkpoint_store = WorkflowCheckpointStore(artifact_store)
        if retry_runtime_observation:
            if resume_id is None:
                raise LocalEntryError(
                    "Runtime observation retry requires the exact --resume-id."
                )
            (
                recovery_decision,
                recovery_resume_report_ref,
                prior_runtime_evidence_ref,
                prior_repair_plan_ref,
                observation_retry_binding,
            ) = checkpoint_store.preflight_runtime_observation_retry(
                checkpoint_ref,
                resume_id=resume_id,
            )
            readiness = recovery_decision
        elif recover_accepted_resume:
            if resume_id is None:
                raise LocalEntryError(
                    "Accepted resume recovery requires the exact --resume-id."
                )
            (
                recovery_decision,
                recovery_resume_report_ref,
            ) = checkpoint_store.preflight_accepted_resume_recovery(
                checkpoint_ref,
                resume_id=resume_id,
            )
            readiness = recovery_decision
        else:
            readiness = checkpoint_store.preflight_resume(
                checkpoint_ref,
                resume_id=resume_id,
            )
    except (OSError, ValueError) as exc:
        raise LocalEntryError(
            f"Runtime continuation checkpoint preflight failed: {exc}"
        ) from exc
    if not readiness.allowed and not allow_blocked_resume:
        blocker_codes = [
            str(blocker.get("code"))
            for blocker in readiness.blockers
            if isinstance(blocker, Mapping)
        ]
        raise LocalEntryError(
            "Runtime continuation preflight was blocked: "
            + ", ".join(blocker_codes)
        )
    if (
        retry_runtime_observation
        and prior_runtime_evidence_ref is not None
        and observation_retry_binding is not None
    ):
        prior_runtime = artifact_store.read(prior_runtime_evidence_ref)["data"]
        if prior_runtime.get("criterion_results") is not None:
            try:
                observation_retry_binding.update(
                    build_stagger_observation_retry_criterion_binding(
                        prior_runtime,
                        checkpoint,
                    )
                )
            except ValueError as exc:
                raise LocalEntryError(
                    "Runtime observation retry CriterionResult preflight failed: "
                    f"{exc}"
                ) from exc

    return _RuntimeContinuationHandoff(
        run_root=root,
        artifact_store_root=store_root,
        artifact_store=artifact_store,
        checkpoint_ref=checkpoint_ref,
        checkpoint=checkpoint,
        manifest=manifest,
        feature_spec_ref=feature_spec_ref,
        feature_spec=feature_spec,
        build_ref=build_ref,
        build=build,
        accepted_resume_recovery=recover_accepted_resume,
        runtime_observation_retry=retry_runtime_observation,
        recovery_decision=recovery_decision,
        recovery_resume_report_ref=recovery_resume_report_ref,
        prior_runtime_evidence_ref=prior_runtime_evidence_ref,
        prior_repair_plan_ref=prior_repair_plan_ref,
        observation_retry_binding=observation_retry_binding,
        resume_readiness=readiness,
    )


def _stagger_repair_attempt_projection(
    handoff: _RuntimeContinuationHandoff,
    runtime_profile: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve the current repair lineage into a no-write Runtime ledger."""

    if not isinstance(runtime_profile, Mapping) or not isinstance(
        runtime_profile.get("stagger_acceptance"),
        Mapping,
    ):
        return None
    snapshot = handoff.checkpoint.get("state_snapshot")
    if not isinstance(snapshot, Mapping):
        raise LocalEntryError("Stagger RepairAttempt checkpoint snapshot is missing.")
    artifacts = snapshot.get("artifacts")
    artifact_hashes = snapshot.get("artifact_hashes")
    if not isinstance(artifacts, Mapping) or not isinstance(
        artifact_hashes,
        Mapping,
    ):
        raise LocalEntryError("Stagger RepairAttempt Artifact bindings are missing.")
    if "repair_plan" not in artifacts and "repair_plan" not in artifact_hashes:
        return None
    required_types = (
        "root_cause_evidence",
        "repair_plan",
        "isolated_apply_result",
    )
    if any(
        artifact_type not in artifacts or artifact_type not in artifact_hashes
        for artifact_type in required_types
    ):
        raise LocalEntryError(
            "Stagger RepairAttempt exact lineage is incomplete."
        )
    manifest_inputs = handoff.manifest.get("input_artifacts")
    if not isinstance(manifest_inputs, Mapping):
        raise LocalEntryError(
            "Stagger RepairAttempt Build manifest input lineage is missing."
        )

    refs: dict[str, ArtifactRef] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for artifact_type in required_types:
        path = artifacts.get(artifact_type)
        artifact_hash = artifact_hashes.get(artifact_type)
        manifest_identity = manifest_inputs.get(artifact_type)
        if (
            not isinstance(path, str)
            or not isinstance(artifact_hash, str)
            or not isinstance(manifest_identity, Mapping)
            or manifest_identity.get("path") != path
            or manifest_identity.get("artifact_hash") != artifact_hash
        ):
            raise LocalEntryError(
                "Stagger RepairAttempt Build manifest lineage does not match "
                f"checkpoint role {artifact_type}."
            )
        ref = ArtifactRef(
            feature_id=str(handoff.checkpoint["feature_id"]),
            artifact_type=artifact_type,
            path=path,
            artifact_hash=artifact_hash,
        )
        try:
            payload = handoff.artifact_store.read(ref)["data"]
        except (OSError, ValueError) as exc:
            raise LocalEntryError(
                f"Stagger RepairAttempt {artifact_type} is invalid: {exc}"
            ) from exc
        refs[artifact_type] = ref
        payloads[artifact_type] = payload

    apply_payload = payloads["isolated_apply_result"]
    changes = apply_payload.get("changes")
    if not isinstance(changes, list) or len(changes) != 1:
        raise LocalEntryError(
            "Stagger RepairAttempt requires the one-change isolated Apply."
        )
    change = changes[0]
    if not isinstance(change, Mapping):
        raise LocalEntryError("Stagger isolated Apply change is invalid.")
    diff_hash = apply_payload.get("diff_hash")
    resume_binding = handoff.checkpoint.get("resume_binding")
    if (
        not isinstance(diff_hash, str)
        or not isinstance(resume_binding, Mapping)
        or resume_binding.get("diff_hash") != diff_hash
    ):
        raise LocalEntryError(
            "Stagger RepairAttempt diff does not match checkpoint handoff."
        )
    source_hash_before = change.get("before_sha256")
    source_sha256 = change.get("after_sha256")
    if (
        not isinstance(source_hash_before, str)
        or not isinstance(source_sha256, str)
        or handoff.manifest.get("target_sha256") != source_sha256
    ):
        raise LocalEntryError(
            "Stagger RepairAttempt source identity does not match Build manifest."
        )
    source_snapshot_sha256 = handoff.manifest.get("source_snapshot_sha256")
    if not isinstance(source_snapshot_sha256, str):
        raise LocalEntryError(
            "Stagger RepairAttempt Build source snapshot identity is missing."
        )
    verified_artifacts = handoff.build.get("verified_artifacts")
    if not isinstance(verified_artifacts, list) or len(verified_artifacts) != 1:
        raise LocalEntryError("Stagger RepairAttempt Build output is not unique.")
    dll_sha256 = verified_artifacts[0].get("sha256")
    if not isinstance(dll_sha256, str):
        raise LocalEntryError("Stagger RepairAttempt DLL identity is missing.")
    acceptance_boundary = runtime_profile.get("acceptance_boundary")
    marker_criterion = (
        acceptance_boundary.get("feature_spec_marker_criterion")
        if isinstance(acceptance_boundary, Mapping)
        else None
    )
    acceptance_criteria = handoff.feature_spec.get("acceptance_criteria")
    if (
        not isinstance(marker_criterion, str)
        or not isinstance(acceptance_criteria, list)
        or any(not isinstance(item, str) for item in acceptance_criteria)
    ):
        raise LocalEntryError(
            "Stagger RepairAttempt criterion ownership is incomplete."
        )
    try:
        projection = build_stagger_repair_attempt_projection(
            feature_id=str(handoff.checkpoint["feature_id"]),
            run_id=str(handoff.checkpoint["run_id"]),
            repair_plan=payloads["repair_plan"],
            repair_plan_ref={
                "path": refs["repair_plan"].path,
                "artifact_hash": refs["repair_plan"].artifact_hash,
            },
            root_cause_evidence=payloads["root_cause_evidence"],
            root_cause_evidence_ref={
                "path": refs["root_cause_evidence"].path,
                "artifact_hash": refs["root_cause_evidence"].artifact_hash,
            },
            isolated_apply_result_ref={
                "path": refs["isolated_apply_result"].path,
                "artifact_hash": refs["isolated_apply_result"].artifact_hash,
            },
            build_result_ref={
                "path": handoff.build_ref.path,
                "artifact_hash": handoff.build_ref.artifact_hash,
            },
            acceptance_criteria=tuple(acceptance_criteria),
            marker_criteria=frozenset({marker_criterion}),
            source_hash_before=source_hash_before,
            source_sha256=source_sha256,
            source_snapshot_sha256=source_snapshot_sha256,
            dll_sha256=dll_sha256,
            diff_hash=diff_hash,
        )
        retry_binding = handoff.observation_retry_binding
        if retry_binding is not None and "inherited_criterion_results" in retry_binding:
            projection = inherit_stagger_repair_attempt_prior_results(
                projection,
                prior_criterion_results=tuple(
                    item
                    for item in retry_binding.get(
                        "inherited_criterion_results", ()
                    )
                    if isinstance(item, Mapping)
                ),
                prior_runtime_evidence_ref={
                    "path": retry_binding.get("prior_runtime_evidence_ref"),
                    "artifact_hash": retry_binding.get(
                        "prior_runtime_evidence_hash"
                    ),
                },
                retry_number=retry_binding.get("retry_number"),
            )
        return projection
    except ValueError as exc:
        raise LocalEntryError(
            f"Stagger RepairAttempt projection is invalid: {exc}"
        ) from exc


def _stagger_runtime_attempt_namespace(
    projection: Mapping[str, Any],
    *,
    runtime_observation_retry: Mapping[str, Any] | None,
) -> str:
    repair_attempt = projection.get("repair_attempt")
    if not isinstance(repair_attempt, Mapping):
        raise LocalEntryError("Stagger RepairAttempt projection is incomplete.")
    attempt_id = repair_attempt.get("attempt_id")
    run_id = repair_attempt.get("run_id")
    if not isinstance(attempt_id, str) or not isinstance(run_id, str):
        raise LocalEntryError("Stagger Runtime attempt namespace is incomplete.")
    if runtime_observation_retry is None:
        execution_id = "initial"
    else:
        retry_number = runtime_observation_retry.get("retry_number")
        if isinstance(retry_number, bool) or not isinstance(retry_number, int):
            raise LocalEntryError(
                "Stagger Runtime observation retry number is missing."
            )
        execution_id = f"observation_retry_{retry_number}"
    return f"{attempt_id}:{run_id}:{execution_id}"


def _runtime_continuation_backup_report(
    run_root: Path,
    *,
    stagger_enabled: bool,
    stagger_modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Read-validate compact deployment backup paths and existing material state."""

    backup_root = run_root / "runtime_continuation_deployment_backup"
    if backup_root.exists() and not backup_root.is_dir():
        raise LocalEntryError(
            "Runtime continuation deployment backup root is not a directory."
        )
    material_entries = (
        sorted(
            str(path)
            for path in backup_root.rglob("*")
            if path.is_file() or path.is_symlink()
        )
        if backup_root.is_dir()
        else []
    )
    if material_entries:
        raise LocalEntryError(
            "Runtime continuation found unresolved prior deployment backup state."
        )
    modes = (
        stagger_modes
        if stagger_enabled and stagger_modes is not None
        else (
            ("general_enabled_false", "general_enabled_true")
            if stagger_enabled
            else ("single_process",)
        )
    )
    if not modes:
        raise LocalEntryError("Stagger Runtime requires at least one mode.")
    relative_paths = (
        tuple(
            relative_path
            for mode in modes
            for relative_path in (
                f"{mode}/plugin/original.bin",
                f"{mode}/config/original.bin",
            )
        )
        if stagger_enabled
        else ("original.bin",)
    )
    planned_paths = [
        str((backup_root / Path(relative_path)).resolve())
        for relative_path in relative_paths
    ]
    maximum_path_chars = max(len(path) for path in planned_paths)
    diagnostic_relative_paths = (
        tuple(
            relative_path
            for mode in modes
            for relative_path in (
                f"runtime_process_diagnostics/{mode}/stdout.log",
                f"runtime_process_diagnostics/{mode}/stderr.log",
            )
        )
        if stagger_enabled
        else (
            "runtime_process_diagnostics/stdout.log",
            "runtime_process_diagnostics/stderr.log",
        )
    )
    planned_diagnostic_paths = [
        str((run_root / Path(relative_path)).resolve())
        for relative_path in diagnostic_relative_paths
    ]
    maximum_diagnostic_path_chars = max(
        len(path) for path in planned_diagnostic_paths
    )
    if os.name == "nt" and (
        maximum_path_chars >= 260 or maximum_diagnostic_path_chars >= 260
    ):
        raise LocalEntryError(
            "Runtime continuation compact Runtime output path exceeds the "
            "Windows 259-character file-path boundary."
        )
    return {
        "status": "ready",
        "backup_root": str(backup_root.resolve()),
        "planned_backup_paths": planned_paths,
        "maximum_path_chars": maximum_path_chars,
        "planned_process_diagnostic_paths": planned_diagnostic_paths,
        "maximum_process_diagnostic_path_chars": (
            maximum_diagnostic_path_chars
        ),
        "existing_material_entries": material_entries,
        "empty_directories_reusable": True,
        "writes_performed": False,
    }


def _runtime_observation_retry_output_report(
    *,
    source_run_root: Path,
    runtime_output_root: str | Path,
    feature_id: str,
    stagger_enabled: bool,
    stagger_modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Read-validate a fresh output root for one Stagger Runtime attempt."""

    output_input = Path(runtime_output_root)
    if not output_input.is_absolute():
        raise LocalEntryError(
            "Stagger Runtime output root must be absolute."
        )
    output_root = output_input.resolve()
    if not output_root.is_dir():
        raise LocalEntryError(
            "Stagger Runtime output root does not exist."
        )
    source_root = source_run_root.resolve()
    try:
        output_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise LocalEntryError(
            "Stagger Runtime output root must remain outside the source "
            "Build run root."
        )
    try:
        source_root.relative_to(output_root)
    except ValueError:
        pass
    else:
        raise LocalEntryError(
            "Stagger Runtime output root cannot contain the source Build run "
            "root."
        )
    existing_entries = sorted(str(path.resolve()) for path in output_root.iterdir())
    if existing_entries:
        raise LocalEntryError(
            "Stagger Runtime output root must be empty."
        )

    deployment_backup = _runtime_continuation_backup_report(
        output_root,
        stagger_enabled=stagger_enabled,
        stagger_modes=stagger_modes,
    )
    modes = (
        (
            stagger_modes
            if stagger_modes is not None
            else ("general_enabled_false", "general_enabled_true")
        )
        if stagger_enabled
        else ("single_process",)
    )
    planned_capture_paths = [
        str(
            (
                output_root
                / "runtime_captures"
                / mode
                / f"{feature_id}_gtfo_runtime.png"
            ).resolve()
        )
        for mode in modes
    ]
    planned_result_path = str((output_root / "runtime_resume_result.json").resolve())
    operator_completion_directory = (
        output_root / "operator_completion"
        if stagger_enabled
        else None
    )
    maximum_operator_completion_path_chars = (
        max(
            len(
                str(
                    (
                        operator_completion_directory
                        / (
                            "operator_"
                            + ("f" * 32)
                            + suffix
                        )
                    ).resolve()
                )
            )
            for suffix in (
                ".request.json",
                ".response.json",
                ".confirmation.json",
            )
        )
        if operator_completion_directory is not None
        else 0
    )
    maximum_output_path_chars = max(
        len(path)
        for path in (
            *planned_capture_paths,
            planned_result_path,
            *deployment_backup["planned_backup_paths"],
            *deployment_backup["planned_process_diagnostic_paths"],
        )
    )
    maximum_output_path_chars = max(
        maximum_output_path_chars,
        maximum_operator_completion_path_chars,
    )
    if os.name == "nt" and maximum_output_path_chars >= 260:
        raise LocalEntryError(
            "Stagger Runtime output path exceeds the Windows "
            "259-character file-path boundary."
        )
    return {
        "status": "ready",
        "runtime_output_root": str(output_root),
        "source_run_root": str(source_root),
        "empty": True,
        "existing_entries": [],
        "planned_capture_paths": planned_capture_paths,
        "planned_result_path": planned_result_path,
        "operator_completion_exchange": (
            {
                "status": "ready",
                "directory": str(operator_completion_directory.resolve()),
                "request_identity_source": (
                    "GTFOOperatorCompletionRequest.request_id"
                ),
                "response_path_source": (
                    "request_file.response_path_suffix"
                ),
                "confirmation_path_source": (
                    "request_file.confirmation_path_suffix"
                ),
                "confirmation_identity": (
                    "confirmation_file.response_sha256"
                ),
                "maximum_path_chars": (
                    maximum_operator_completion_path_chars
                ),
                "writes_performed": False,
            }
            if operator_completion_directory is not None
            else None
        ),
        "maximum_output_path_chars": maximum_output_path_chars,
        "deployment_backup": deployment_backup,
        "writes_performed": False,
    }


def _verification_only_runtime_execution_identity(
    *,
    handoff: _RuntimeContinuationHandoff,
    resume_id: str,
    approved_by: str,
    runtime_admission: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Build the stable cross-call identity for one RuntimeEvidence action."""

    identity = {
        "schema_version": "verification_only_runtime_execution_identity_v1",
        "hash_domain": "mod_agent.verification_only_runtime_execution_identity.v1",
        "checkpoint": {
            "artifact_type": handoff.checkpoint_ref.artifact_type,
            "artifact_hash": handoff.checkpoint_ref.artifact_hash,
            "feature_id": handoff.checkpoint_ref.feature_id,
            "checkpoint_id": handoff.checkpoint["checkpoint_id"],
            "run_id": handoff.checkpoint["run_id"],
            "request_id": handoff.checkpoint["request_id"],
        },
        "resume_id": resume_id,
        "approved_by": approved_by,
        "runtime_admission": dict(runtime_admission),
    }
    try:
        serialized = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LocalEntryError(
            "Runtime execution identity contains a non-JSON value."
        ) from exc
    canonical_identity = json.loads(serialized.decode("utf-8"))
    return canonical_identity, "sha256:" + hashlib.sha256(serialized).hexdigest()


def _artifact_logical_identity(ref: ArtifactRef) -> dict[str, str]:
    return {
        "artifact_type": ref.artifact_type,
        "artifact_hash": ref.artifact_hash,
        "feature_id": ref.feature_id,
    }


def _artifact_ref_projection(ref: ArtifactRef) -> dict[str, str]:
    return {**_artifact_logical_identity(ref), "path": ref.path}


def _verification_only_runtime_terminal_identity(
    *,
    handoff: _RuntimeTerminalHandoff,
    resume_id: str,
    approved_by: str,
) -> tuple[dict[str, Any], str]:
    """Build the stable identity for one Store-only terminal action."""

    checkpoint = handoff.build_handoff.checkpoint
    identity = {
        "schema_version": "verification_only_runtime_terminal_identity_v1",
        "hash_domain": "mod_agent.verification_only_runtime_terminal_identity.v1",
        "checkpoint": {
            **_artifact_logical_identity(handoff.build_handoff.checkpoint_ref),
            "checkpoint_id": checkpoint["checkpoint_id"],
            "run_id": checkpoint["run_id"],
            "request_id": checkpoint["request_id"],
        },
        "resume_report": _artifact_logical_identity(handoff.resume_report_ref),
        "runtime_evidence": _artifact_logical_identity(
            handoff.runtime_evidence_ref
        ),
        "resume_id": resume_id,
        "approved_by": approved_by,
        "terminal_result_scope": {
            "allowed_artifact_types": [
                "blocked_report",
                "eval_report",
                "workflow_summary",
            ],
            "automatic_retry_count": 0,
            "recovery_allowed": False,
        },
    }
    try:
        serialized = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LocalEntryError(
            "Runtime terminal identity contains a non-JSON value."
        ) from exc
    return (
        json.loads(serialized.decode("utf-8")),
        "sha256:" + hashlib.sha256(serialized).hexdigest(),
    )


def _exact_runtime_terminal_revision_ref(
    store: ArtifactStore,
    *,
    feature_id: str,
    artifact_type: str,
    path: str | Path,
    artifact_hash: str,
) -> ArtifactRef:
    """Resolve one supplied Store path to its exact immutable revision ref."""

    resolved_path = Path(path).resolve()
    try:
        resolved_path.relative_to(store.root.resolve())
    except ValueError as exc:
        raise LocalEntryError(
            f"Runtime terminal {artifact_type} is outside ArtifactStore root."
        ) from exc
    matches = [
        ref
        for ref in store.list_feature_artifact_revisions(
            feature_id,
            artifact_type,
        )
        if ref.artifact_hash == artifact_hash
        and Path(ref.path).resolve() == resolved_path
    ]
    if len(matches) != 1:
        raise LocalEntryError(
            f"Runtime terminal {artifact_type} is not one exact immutable revision."
        )
    store.read(matches[0])
    return matches[0]


def _load_runtime_terminal_handoff(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    accepted_resume_report_path: str | Path,
    accepted_resume_report_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    resume_id: str,
    approved_by: str,
) -> _RuntimeTerminalHandoff:
    """Read and validate the exact immutable post-Runtime continuation inputs."""

    build_handoff = _load_runtime_continuation_handoff(
        run_root=run_root,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        checkpoint_path=checkpoint_path,
        checkpoint_hash=checkpoint_hash,
        resume_id=resume_id,
        require_manifest=False,
        allow_blocked_resume=True,
        require_current_build_output=False,
    )
    store = build_handoff.artifact_store
    exact_checkpoint_ref = _exact_runtime_terminal_revision_ref(
        store,
        feature_id=feature_id,
        artifact_type="workflow_checkpoint",
        path=checkpoint_path,
        artifact_hash=checkpoint_hash,
    )
    if exact_checkpoint_ref != build_handoff.checkpoint_ref:
        raise LocalEntryError(
            "Runtime terminal workflow_checkpoint identity changed during admission."
        )
    resume_report_ref = _exact_runtime_terminal_revision_ref(
        store,
        feature_id=feature_id,
        artifact_type="resume_report",
        path=accepted_resume_report_path,
        artifact_hash=accepted_resume_report_hash,
    )
    runtime_evidence_ref = _exact_runtime_terminal_revision_ref(
        store,
        feature_id=feature_id,
        artifact_type="runtime_evidence",
        path=runtime_evidence_path,
        artifact_hash=runtime_evidence_hash,
    )
    try:
        decision, runtime_evidence, existing_terminal_refs = (
            WorkflowCheckpointStore(
                store
            ).preflight_runtime_terminal_continuation(
                build_handoff.checkpoint_ref,
                resume_report_ref=resume_report_ref,
                runtime_evidence_ref=runtime_evidence_ref,
                resume_id=resume_id,
                approved_by=approved_by,
            )
        )
    except (OSError, ValueError) as exc:
        raise LocalEntryError(
            f"Runtime terminal continuation preflight failed: {exc}"
        ) from exc
    return _RuntimeTerminalHandoff(
        build_handoff=build_handoff,
        resume_report_ref=resume_report_ref,
        runtime_evidence_ref=runtime_evidence_ref,
        runtime_evidence=runtime_evidence,
        decision=decision,
        existing_terminal_refs=existing_terminal_refs,
    )


def _preflight_runtime_terminal_continuation(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    accepted_resume_report_path: str | Path,
    accepted_resume_report_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    resume_id: str,
    approved_by: str,
) -> dict[str, Any]:
    handoff = _load_runtime_terminal_handoff(
        run_root=run_root,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        checkpoint_path=checkpoint_path,
        checkpoint_hash=checkpoint_hash,
        accepted_resume_report_path=accepted_resume_report_path,
        accepted_resume_report_hash=accepted_resume_report_hash,
        runtime_evidence_path=runtime_evidence_path,
        runtime_evidence_hash=runtime_evidence_hash,
        resume_id=resume_id,
        approved_by=approved_by,
    )
    identity, identity_hash = _verification_only_runtime_terminal_identity(
        handoff=handoff,
        resume_id=resume_id,
        approved_by=approved_by,
    )
    return {
        "status": (
            "READY_FOR_RUNTIME_TERMINALIZATION"
            if handoff.decision.allowed
            else "BLOCKED"
        ),
        "command": "preflight-runtime-terminalization-only",
        "writes_performed": False,
        "graph_invoked": False,
        "checkpoint_consumed": True,
        "resume_report_created": False,
        "runtime_evidence_created": False,
        "runtime_factory_invoked": False,
        "process_launched": False,
        "dll_copied": False,
        "manifest_required": False,
        "identity": {
            "run_id": handoff.build_handoff.checkpoint["run_id"],
            "request_id": handoff.build_handoff.checkpoint["request_id"],
            "feature_id": feature_id,
        },
        "checkpoint": {
            "path": handoff.build_handoff.checkpoint_ref.path,
            "artifact_hash": handoff.build_handoff.checkpoint_ref.artifact_hash,
            "checkpoint_id": handoff.build_handoff.checkpoint["checkpoint_id"],
        },
        "accepted_resume_report": {
            "path": handoff.resume_report_ref.path,
            "artifact_hash": handoff.resume_report_ref.artifact_hash,
        },
        "runtime_evidence": {
            "path": handoff.runtime_evidence_ref.path,
            "artifact_hash": handoff.runtime_evidence_ref.artifact_hash,
            "verification_status": handoff.runtime_evidence.get(
                "verification_status"
            ),
            "acceptance_status": handoff.runtime_evidence.get(
                "acceptance_status"
            ),
            "acceptance_verified": handoff.runtime_evidence.get(
                "acceptance_verified"
            ),
        },
        "runtime_terminal_execution_identity": identity,
        "runtime_terminal_execution_identity_hash": identity_hash,
        "terminal_result_scope": identity["terminal_result_scope"],
        "existing_terminal_artifacts": [
            _artifact_logical_identity(ref)
            for ref in handoff.existing_terminal_refs
        ],
        "resume_decision": handoff.decision.to_dict(),
        "blockers": list(handoff.decision.blockers),
    }


def _load_runtime_evidence_consolidation_handoff(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    operation: VerificationOperationEnvelope,
) -> _RuntimeEvidenceConsolidationHandoff:
    """Read and validate one exact no-Runtime consolidation action."""

    envelope = validate_verification_operation_envelope(operation)
    declaration = resolve_verification_operation(envelope)
    if declaration.operation_kind != EVIDENCE_CONSOLIDATION_KIND:
        raise LocalEntryError("Verification operation is not evidence consolidation.")
    protocol = envelope.protocol_binding
    variant = envelope.variant_payload
    if (
        protocol.checkpoint_ref.feature_id != feature_id
        or protocol.checkpoint_ref.path != str(Path(checkpoint_path).resolve())
        or protocol.checkpoint_ref.artifact_hash != checkpoint_hash
    ):
        raise LocalEntryError("Verification operation checkpoint input changed.")
    build_handoff = _load_runtime_continuation_handoff(
        run_root=run_root,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        checkpoint_path=checkpoint_path,
        checkpoint_hash=checkpoint_hash,
        resume_id=protocol.resume_id,
        require_manifest=False,
        allow_blocked_resume=True,
        require_current_build_output=False,
    )
    store = build_handoff.artifact_store
    exact_checkpoint_ref = _exact_runtime_terminal_revision_ref(
        store,
        feature_id=feature_id,
        artifact_type="workflow_checkpoint",
        path=checkpoint_path,
        artifact_hash=checkpoint_hash,
    )
    if exact_checkpoint_ref != build_handoff.checkpoint_ref:
        raise LocalEntryError(
            "RuntimeEvidence consolidation checkpoint identity changed."
        )
    exact_refs = tuple(
        _exact_runtime_terminal_revision_ref(
            store,
            feature_id=feature_id,
            artifact_type=ref.artifact_type,
            path=ref.path,
            artifact_hash=ref.artifact_hash,
        )
        for ref in (
            protocol.accepted_resume_report_ref,
            variant.prior_runtime_evidence_ref,
            variant.evidence_pack_ref,
            variant.feature_spec_ref,
            variant.build_result_ref,
        )
    )
    (
        resume_report_ref,
        prior_runtime_ref,
        evidence_pack_ref,
        feature_spec_ref,
        build_result_ref,
    ) = exact_refs
    if (
        resume_report_ref != protocol.accepted_resume_report_ref
        or prior_runtime_ref != variant.prior_runtime_evidence_ref
        or evidence_pack_ref != variant.evidence_pack_ref
        or feature_spec_ref != build_handoff.feature_spec_ref
        or build_result_ref != build_handoff.build_ref
    ):
        raise LocalEntryError("Verification operation exact inputs changed.")
    decision, prior_payload, _ = WorkflowCheckpointStore(
        store
    ).preflight_runtime_evidence_consolidation(
        build_handoff.checkpoint_ref,
        resume_report_ref=resume_report_ref,
        prior_runtime_evidence_ref=prior_runtime_ref,
        resume_id=protocol.resume_id,
        approved_by=protocol.approved_by,
    )
    existing_child_refs = runtime_evidence_consolidation_child_refs(
        store,
        feature_id=feature_id,
        prior_ref=prior_runtime_ref,
        feature_adapter=str(variant.canonical_delta.get("feature_adapter") or ""),
    )
    derived_payload = None
    semantic_intent = None
    upstream_refs = (
        build_handoff.build_ref,
        build_handoff.feature_spec_ref,
        prior_runtime_ref,
        evidence_pack_ref,
    )
    if decision.allowed and not existing_child_refs:
        derived_payload = project_runtime_evidence_consolidation_payload(
            envelope,
            store,
        )
        semantic_intent = project_artifact_write_intent(
            reader=store,
            feature_id=feature_id,
            artifact_type="runtime_evidence",
            payload=derived_payload,
            status="blocked",
            upstream_refs=upstream_refs,
            exact_revision_upstream_types={"runtime_evidence", "evidence_pack"},
            blockers=(),
            trace_refs=(),
            protocol_refs=(build_handoff.checkpoint_ref, resume_report_ref),
            execution_file_bindings=variant.execution_file_bindings,
        )
    return _RuntimeEvidenceConsolidationHandoff(
        build_handoff=build_handoff,
        resume_report_ref=resume_report_ref,
        prior_runtime_evidence_ref=prior_runtime_ref,
        evidence_pack_ref=evidence_pack_ref,
        decision=decision,
        existing_child_refs=existing_child_refs,
        operation=envelope,
        semantic_intent=semantic_intent,
        derived_payload=derived_payload,
        derived_payload_hash=(
            None
            if derived_payload is None
            else hash_canonical_value(derived_payload)
        ),
    )


def _preflight_runtime_evidence_consolidation(
    *,
    verification_operation: VerificationOperationSpec,
    **kwargs: Any,
) -> dict[str, Any]:
    """Project one exact no-write implementation-evidence action."""

    envelope = project_verification_operation(verification_operation)
    handoff = _load_runtime_evidence_consolidation_handoff(
        operation=envelope,
        **kwargs,
    )
    variant = envelope.variant_payload
    return {
        "status": (
            "READY_FOR_RUNTIME_EVIDENCE_CONSOLIDATION"
            if handoff.decision.allowed and not handoff.existing_child_refs
            else "BLOCKED"
        ),
        "command": "preflight-verification-operation",
        "writes_performed": False,
        "graph_invoked": False,
        "checkpoint_consumed": True,
        "resume_report_created": False,
        "runtime_evidence_created": False,
        "runtime_factory_invoked": False,
        "process_launched": False,
        "dll_copied": False,
        "manifest_required": False,
        "identity": {
            "run_id": handoff.build_handoff.checkpoint["run_id"],
            "request_id": handoff.build_handoff.checkpoint["request_id"],
            "feature_id": envelope.protocol_binding.checkpoint_ref.feature_id,
        },
        "verification_operation": envelope,
        "checkpoint": _artifact_ref_projection(
            envelope.protocol_binding.checkpoint_ref
        ),
        "accepted_resume_report": _artifact_ref_projection(
            envelope.protocol_binding.accepted_resume_report_ref
        ),
        "prior_runtime_evidence": _artifact_ref_projection(
            variant.prior_runtime_evidence_ref
        ),
        "evidence_pack": _artifact_ref_projection(variant.evidence_pack_ref),
        "canonical_delta": dict(variant.canonical_delta),
        "canonical_delta_hash": hash_canonical_value(variant.canonical_delta),
        "execution_file_bindings": [
            {
                "role": item.role,
                "absolute_path": item.absolute_path,
                "content_sha256": item.content_sha256,
                "logical_target_path": item.logical_target_path,
            }
            for item in variant.execution_file_bindings
        ],
        "approval_identity": dict(envelope.approval_identity),
        "approval_identity_hash": envelope.approval_identity_hash,
        "artifact_write_intent": (
            None
            if handoff.semantic_intent is None
            else {
                "schema_version": handoff.semantic_intent.schema_version,
                "semantic_binding_key": (
                    handoff.semantic_intent.semantic_binding_key
                ),
                "semantic_binding_version": (
                    handoff.semantic_intent.semantic_binding_version
                ),
                "expected_payload_hash": (
                    handoff.semantic_intent.expected_payload_hash
                ),
                "expected_artifact_hash": (
                    handoff.semantic_intent.expected_artifact_hash
                ),
                "commit_conflict_key_hash": (
                    handoff.semantic_intent.commit_conflict_key_hash
                ),
            }
        ),
        "runtime_evidence_consolidation_identity": dict(
            envelope.approval_identity
        ),
        "runtime_evidence_consolidation_identity_hash": envelope.approval_identity_hash,
        "derived_runtime_evidence_payload_hash": handoff.derived_payload_hash,
        "existing_child_refs": [
            _artifact_ref_projection(ref) for ref in handoff.existing_child_refs
        ],
        "decision": handoff.decision.to_dict(),
        "blockers": list(handoff.decision.blockers),
        "new_build_performed": False,
        "new_runtime_performed": False,
        "product_source_modified": False,
    }


def _verification_only_runtime_resume_payload(
    *,
    handoff: _RuntimeContinuationHandoff,
    resume_id: str,
    approved_by: str,
    runtime_admission: Mapping[str, Any],
    approved_at: str,
) -> ResumePayload:
    """Build the exact payload shared by Runtime preflight and execution."""

    return ResumePayload(
        resume_id=resume_id,
        run_id=str(handoff.checkpoint["run_id"]),
        request_id=str(handoff.checkpoint["request_id"]),
        feature_id=str(handoff.checkpoint["feature_id"]),
        stage="build",
        decision="approve",
        approved_by=approved_by,
        approved_at=approved_at,
        artifact_refs=tuple(handoff.checkpoint["artifact_refs"]),
        notes="Initial verification-only RuntimeEvidence continuation.",
        runtime_admission=dict(runtime_admission),
    )


def _runtime_output_admission_binding(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Select the immutable output identity persisted in a Runtime admission."""

    return {
        "runtime_output_root": report["runtime_output_root"],
        "source_run_root": report["source_run_root"],
        "planned_result_path": report["planned_result_path"],
        "planned_capture_paths": list(report["planned_capture_paths"]),
        "operator_completion_directory": (
            None
            if report.get("operator_completion_exchange") is None
            else report["operator_completion_exchange"]["directory"]
        ),
        "empty_at_admission": report.get("empty") is True,
    }


def _accepted_runtime_output_binding(
    handoff: _RuntimeContinuationHandoff,
) -> dict[str, Any] | None:
    """Read an exact initial output binding from an accepted ResumeReport."""

    decision = handoff.recovery_decision
    if decision is None:
        return None
    snapshot = decision.applied_updates.get("runtime_admission")
    runtime_admission = (
        snapshot.get("runtime_admission")
        if isinstance(snapshot, Mapping)
        else None
    )
    binding = (
        runtime_admission.get("runtime_output_binding")
        if isinstance(runtime_admission, Mapping)
        else None
    )
    return dict(binding) if isinstance(binding, Mapping) else None


def _runtime_observation_retry_restoration_report(
    handoff: _RuntimeContinuationHandoff,
) -> dict[str, Any]:
    """Require exact prior Stagger deployment restoration before retry."""

    prior_ref = handoff.prior_runtime_evidence_ref
    if prior_ref is None:
        raise LocalEntryError(
            "Runtime observation retry prior RuntimeEvidence binding is missing."
        )
    prior_runtime = handoff.artifact_store.read(prior_ref)["data"]
    attempts = prior_runtime.get("stagger_runtime_attempts")
    if (
        not isinstance(attempts, list)
        or not attempts
        or any(not isinstance(item, Mapping) for item in attempts)
    ):
        raise LocalEntryError(
            "Runtime observation retry requires prior Stagger attempt "
            "restoration evidence."
        )
    attempt_reports: list[dict[str, Any]] = []
    for item in attempts:
        mode = item.get("stagger_attempt_mode")
        plugin = item.get("plugin_deployment_binding")
        config = item.get("stagger_config_deployment_binding")
        if (
            not isinstance(mode, str)
            or not mode
            or not isinstance(plugin, Mapping)
            or plugin.get("restored") is not True
            or plugin.get("restoration_status") != "restored"
            or not isinstance(config, Mapping)
            or config.get("restored") is not True
            or config.get("restoration_status") != "restored"
        ):
            raise LocalEntryError(
                "Runtime observation retry prior deployment restoration is "
                "incomplete."
            )
        attempt_reports.append(
            {
                "mode": mode,
                "plugin_restoration_status": "restored",
                "config_restoration_status": "restored",
            }
        )
    return {
        "status": "passed",
        "prior_runtime_evidence_ref": prior_ref.path,
        "prior_runtime_evidence_hash": prior_ref.artifact_hash,
        "attempts": attempt_reports,
    }


def preflight_local_runtime(
    *,
    run_root: str | Path,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    artifact_store_root: str | Path | None = None,
    resume_id: str | None = None,
    recover_accepted_resume: bool = False,
    retry_runtime_observation: bool = False,
    runtime_output_root: str | Path | None = None,
    settings_path: str | Path | None = None,
    runtime_plugin_destination: str | Path | None = None,
    approved_by: str | None = None,
    injected_runtime_admission: Mapping[str, Any] | None = None,
    runtime_evidence_only: bool = False,
    runtime_terminalization_only: bool = False,
    verification_operation: VerificationOperationSpec | None = None,
    accepted_resume_report_path: str | Path | None = None,
    accepted_resume_report_hash: str | None = None,
    runtime_evidence_path: str | Path | None = None,
    runtime_evidence_hash: str | None = None,
) -> dict[str, Any]:
    """Read-validate one Runtime continuation without writing or entering graph."""

    if verification_operation is not None:
        if (
            runtime_evidence_only
            or runtime_terminalization_only
            or recover_accepted_resume
            or retry_runtime_observation
            or injected_runtime_admission is not None
            or runtime_output_root is not None
            or runtime_plugin_destination is not None
            or settings_path is not None
        ):
            raise LocalEntryError(
                "Typed verification operation cannot mix with legacy Runtime scope."
            )
        protocol = verification_operation.protocol_binding
        if resume_id not in {None, protocol.resume_id} or approved_by not in {
            None,
            protocol.approved_by,
        }:
            raise LocalEntryError(
                "Typed verification operation protocol identity changed."
            )
        return _preflight_runtime_evidence_consolidation(
            verification_operation=verification_operation,
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
        )
    if runtime_terminalization_only:
        if (
            runtime_evidence_only
            or recover_accepted_resume
            or retry_runtime_observation
            or injected_runtime_admission is not None
            or runtime_output_root is not None
            or runtime_plugin_destination is not None
        ):
            raise LocalEntryError(
                "Runtime terminalization is a separate Store-only continuation."
            )
        if not isinstance(resume_id, str) or not resume_id:
            raise LocalEntryError(
                "Runtime terminalization requires the exact resume_id."
            )
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise LocalEntryError(
                "Runtime terminalization requires exact approved_by."
            )
        if (
            accepted_resume_report_path is None
            or not isinstance(accepted_resume_report_hash, str)
            or runtime_evidence_path is None
            or not isinstance(runtime_evidence_hash, str)
        ):
            raise LocalEntryError(
                "Runtime terminalization requires exact ResumeReport and "
                "RuntimeEvidence refs."
            )
        return _preflight_runtime_terminal_continuation(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            accepted_resume_report_path=accepted_resume_report_path,
            accepted_resume_report_hash=accepted_resume_report_hash,
            runtime_evidence_path=runtime_evidence_path,
            runtime_evidence_hash=runtime_evidence_hash,
            resume_id=resume_id,
            approved_by=approved_by,
        )
    if runtime_evidence_only:
        if recover_accepted_resume or retry_runtime_observation:
            raise LocalEntryError(
                "RuntimeEvidence-only continuation supports only an initial resume."
            )
        if not isinstance(resume_id, str) or not resume_id:
            raise LocalEntryError(
                "RuntimeEvidence-only continuation requires the exact resume_id."
            )
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise LocalEntryError(
                "RuntimeEvidence-only continuation requires exact approved_by."
            )
        if not isinstance(injected_runtime_admission, Mapping):
            raise LocalEntryError(
                "RuntimeEvidence-only continuation requires injected Runtime admission."
            )
    if retry_runtime_observation and runtime_output_root is None:
        raise LocalEntryError(
            "Runtime observation retry requires runtime_output_root."
        )
    if runtime_output_root is not None and not Path(runtime_output_root).is_absolute():
        raise LocalEntryError(
            "Stagger Runtime output root must be absolute."
        )
    if retry_runtime_observation and (
        settings_path is None or runtime_plugin_destination is None
    ):
        raise LocalEntryError(
            "Runtime observation retry preflight requires the reviewed Runtime "
            "profile and plugin destination."
        )
    handoff = _load_runtime_continuation_handoff(
        run_root=run_root,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        checkpoint_path=checkpoint_path,
        checkpoint_hash=checkpoint_hash,
        resume_id=resume_id,
        recover_accepted_resume=recover_accepted_resume,
        retry_runtime_observation=retry_runtime_observation,
        require_manifest=not runtime_evidence_only,
        allow_blocked_resume=runtime_evidence_only,
    )
    if runtime_evidence_only:
        runtime_admission = _runtime_resume_admission_snapshot(
            injected_runtime_admission
        )
        resume_payload = _verification_only_runtime_resume_payload(
            handoff=handoff,
            resume_id=resume_id,
            approved_by=approved_by,
            runtime_admission=runtime_admission,
            approved_at="",
        )
        readiness = handoff.resume_readiness
        payload_decision = ResumeValidator().validate(
            resume_payload,
            checkpoint=handoff.checkpoint,
        )
        decision = payload_decision
        if readiness is not None and not readiness.allowed:
            decision = ResumeDecision(
                status="blocked",
                allowed=False,
                reason="Runtime continuation preflight failed validation.",
                applied_updates={},
                blockers=tuple(readiness.blockers) + tuple(payload_decision.blockers),
                stale_reasons=tuple(readiness.stale_reasons),
            )
        execution_identity, execution_identity_hash = (
            _verification_only_runtime_execution_identity(
                handoff=handoff,
                resume_id=resume_id,
                approved_by=approved_by,
                runtime_admission=runtime_admission,
            )
        )
        build_artifact = handoff.build["verified_artifacts"][0]
        blocker_codes = {
            str(blocker.get("code"))
            for blocker in decision.blockers
            if isinstance(blocker, Mapping)
        }
        return {
            "status": (
                "READY_FOR_RUNTIME_EXECUTION"
                if decision.allowed
                else "BLOCKED"
            ),
            "command": "preflight-runtime-evidence-only",
            "writes_performed": False,
            "graph_invoked": False,
            "checkpoint_consumed": False,
            "resume_report_created": False,
            "runtime_evidence_created": False,
            "process_launched": False,
            "dll_copied": False,
            "run_root": str(handoff.run_root),
            "artifact_store_root": str(handoff.artifact_store_root),
            "identity": {
                "run_id": handoff.checkpoint["run_id"],
                "request_id": handoff.checkpoint["request_id"],
                "feature_id": handoff.checkpoint["feature_id"],
            },
            "checkpoint": {
                "checkpoint_id": handoff.checkpoint["checkpoint_id"],
                "checkpoint_stage": handoff.checkpoint["checkpoint_stage"],
                "path": handoff.checkpoint_ref.path,
                "artifact_hash": handoff.checkpoint_ref.artifact_hash,
                "store_bound": True,
                "lineage_status": (
                    "invalid"
                    if any("LINEAGE" in code for code in blocker_codes)
                    else "valid"
                ),
                "freshness_status": (
                    "stale"
                    if decision.stale_reasons
                    or "STALE_RESUME_REJECTED" in blocker_codes
                    else "fresh"
                ),
                "consumption_status": (
                    "consumed"
                    if "DOUBLE_RESUME_REJECTED" in blocker_codes
                    else "unconsumed"
                ),
                "next_graph_node": (
                    handoff.checkpoint.get("resume_binding") or {}
                ).get("next_graph_node"),
            },
            "build_result": {
                "path": handoff.build_ref.path,
                "artifact_hash": handoff.build_ref.artifact_hash,
                "status": handoff.build.get("status"),
                "claims_real_build_success": handoff.build.get(
                    "claims_real_build_success"
                ),
                "verified_artifact": dict(build_artifact),
            },
            "runtime_admission": execution_identity["runtime_admission"],
            "resume_decision": decision.to_dict(),
            "runtime_execution_identity": execution_identity,
            "runtime_execution_identity_hash": execution_identity_hash,
            "manifest_required": False,
            "external_action_gate": {
                "status": (
                    "admitted" if decision.allowed else "blocked"
                ),
                "required_permissions": list(
                    runtime_admission.get("requested_side_effects") or ()
                ),
                "authorized_permissions": list(
                    runtime_admission.get("authorized_side_effects") or ()
                ),
            },
            "blockers": list(decision.blockers),
        }
    accepted_output_binding = _accepted_runtime_output_binding(handoff)
    selected_runtime_output_root = runtime_output_root
    if recover_accepted_resume and accepted_output_binding is not None:
        bound_output_root = accepted_output_binding.get("runtime_output_root")
        if not isinstance(bound_output_root, str) or not bound_output_root:
            raise LocalEntryError(
                "Accepted Runtime output binding is incomplete."
            )
        if (
            runtime_output_root is not None
            and Path(runtime_output_root).resolve()
            != Path(bound_output_root).resolve()
        ):
            raise LocalEntryError(
                "Accepted resume recovery Runtime output root changed from the "
                "original ResumeReport."
            )
        selected_runtime_output_root = bound_output_root
    retry_restoration = (
        _runtime_observation_retry_restoration_report(handoff)
        if retry_runtime_observation
        else None
    )
    build_artifact = handoff.build["verified_artifacts"][0]
    runtime_profile = None
    external_action_gate = {
        "status": "runtime_profile_required",
        "required_permissions": [
            "runtime_execution",
            "process_launch",
            "game_directory_write",
        ],
        "authorized_permissions": [],
    }
    status = "READY_FOR_RUNTIME_PROFILE"
    runtime_output_report = None
    if settings_path is not None or runtime_plugin_destination is not None:
        if settings_path is None or runtime_plugin_destination is None:
            raise LocalEntryError(
                "Runtime continuation preflight requires both settings_path and "
                "runtime_plugin_destination when validating a Runtime profile."
            )
        settings = load_settings(settings_path)
        runtime_profile = _runtime_profile_preflight_record(
            settings,
            runtime_plugin_destination=runtime_plugin_destination,
            feature_spec=handoff.feature_spec,
            runtime_output_root=selected_runtime_output_root,
            selected_acceptance_criteria=(
                tuple(
                    str(item)
                    for item in (handoff.observation_retry_binding or {}).get(
                        "retry_acceptance_criteria", ()
                    )
                )
                if retry_runtime_observation
                and "retry_acceptance_criteria"
                in (handoff.observation_retry_binding or {})
                else None
            ),
        )
        if Path(str(build_artifact["path"])).name != Path(
            str(runtime_profile["plugin_deployment"]["destination_path"])
        ).name:
            raise LocalEntryError(
                "Runtime continuation destination filename does not match Build output."
            )
        if selected_runtime_output_root is not None:
            runtime_output_report = _runtime_observation_retry_output_report(
                source_run_root=handoff.run_root,
                runtime_output_root=selected_runtime_output_root,
                feature_id=feature_id,
                stagger_enabled=(
                    runtime_profile.get("stagger_acceptance") is not None
                ),
                stagger_modes=(
                    tuple(
                        str(item)
                        for item in (handoff.observation_retry_binding or {}).get(
                            "retry_modes", ()
                        )
                    )
                    if retry_runtime_observation
                    and "retry_modes" in (handoff.observation_retry_binding or {})
                    else None
                ),
            )
            runtime_profile["deployment_backup"] = runtime_output_report[
                "deployment_backup"
            ]
        else:
            runtime_profile["deployment_backup"] = (
                _runtime_continuation_backup_report(
                    handoff.run_root,
                    stagger_enabled=(
                        runtime_profile.get("stagger_acceptance") is not None
                    ),
                )
            )
        if retry_runtime_observation:
            if runtime_output_report is None:
                raise LocalEntryError(
                    "Runtime observation retry output binding is missing."
                )
            runtime_profile["runtime_observation_retry_output"] = (
                runtime_output_report
            )
            runtime_profile["prior_restoration"] = retry_restoration
        if (
            handoff.accepted_resume_recovery
            or handoff.runtime_observation_retry
        ):
            acceptance_criteria = handoff.feature_spec.get("acceptance_criteria")
            exact_acceptance_criteria = (
                tuple(acceptance_criteria)
                if isinstance(acceptance_criteria, list)
                and all(
                    isinstance(item, str) and bool(item)
                    for item in acceptance_criteria
                )
                else ()
            )
            current_runtime_admission = _runtime_admission_record(
                settings,
                run_gtfo_runtime=True,
                allow_game_launch=True,
                runtime_plugin_destination=runtime_plugin_destination,
                allow_game_directory_write=True,
                acceptance_criteria=exact_acceptance_criteria,
            )
            if accepted_output_binding is not None:
                current_runtime_admission["runtime_output_binding"] = dict(
                    accepted_output_binding
                )
            recovery_decision = handoff.recovery_decision
            if recovery_decision is None:
                raise LocalEntryError(
                    "Accepted resume recovery binding is incomplete."
                )
            if (
                recovery_decision.applied_updates.get("runtime_admission")
                != _runtime_resume_admission_snapshot(current_runtime_admission)
            ):
                raise LocalEntryError(
                    "Accepted resume recovery Runtime admission changed from the "
                    "original ResumeReport."
                )
            runtime_profile["accepted_resume_admission_match"] = True
        external_action_gate = {
            "status": "awaiting_separate_authorization",
            "required_permissions": [
                "runtime_execution",
                "process_launch",
                "game_directory_write",
            ],
            "authorized_permissions": [],
        }
        status = "READY_FOR_EXTERNAL_AUTHORIZATION"

    repair_attempt_projection = _stagger_repair_attempt_projection(
        handoff,
        runtime_profile,
    )
    if (
        repair_attempt_projection is not None
        and not recover_accepted_resume
        and not retry_runtime_observation
        and runtime_output_report is None
    ):
        raise LocalEntryError(
            "Initial Stagger repair Runtime requires an independent absolute "
            "empty runtime_output_root."
        )
    return {
        "status": status,
        "command": "preflight-runtime",
        "writes_performed": False,
        "graph_invoked": False,
        "checkpoint_consumed": False,
        "resume_report_created": False,
        "runtime_evidence_created": False,
        "process_launched": False,
        "dll_copied": False,
        "run_root": str(handoff.run_root),
        "artifact_store_root": str(handoff.artifact_store_root),
        "identity": {
            "run_id": handoff.checkpoint["run_id"],
            "request_id": handoff.checkpoint["request_id"],
            "feature_id": handoff.checkpoint["feature_id"],
        },
        "checkpoint": {
            "checkpoint_id": handoff.checkpoint["checkpoint_id"],
            "checkpoint_stage": handoff.checkpoint["checkpoint_stage"],
            "path": handoff.checkpoint_ref.path,
            "artifact_hash": handoff.checkpoint_ref.artifact_hash,
            "store_bound": True,
            "lineage_status": "valid",
            "freshness_status": "fresh",
            "consumption_status": (
                "runtime_observation_retry"
                if handoff.runtime_observation_retry
                else (
                    "accepted_resume_recovery"
                    if handoff.accepted_resume_recovery
                    else "unconsumed"
                )
            ),
            "next_graph_node": (
                handoff.checkpoint.get("resume_binding") or {}
            ).get("next_graph_node"),
        },
        "build_result": {
            "path": handoff.build_ref.path,
            "artifact_hash": handoff.build_ref.artifact_hash,
            "status": handoff.build.get("status"),
            "claims_real_build_success": handoff.build.get(
                "claims_real_build_success"
            ),
            "verified_artifact": dict(build_artifact),
        },
        "repair_attempt_preflight": (
            {
                "status": "ready",
                "writes_performed": False,
                "artifact_writes_performed": False,
                "repair_attempt": repair_attempt_projection["repair_attempt"],
                "criterion_results": repair_attempt_projection[
                    "criterion_results"
                ],
            }
            if repair_attempt_projection is not None
            else {"status": "not_applicable"}
        ),
        "runtime_profile": runtime_profile,
        "accepted_resume_recovery": (
            {
                "enabled": True,
                "resume_id": resume_id,
                "resume_report_path": (
                    None
                    if handoff.recovery_resume_report_ref is None
                    else handoff.recovery_resume_report_ref.path
                ),
                "resume_report_hash": (
                    None
                    if handoff.recovery_resume_report_ref is None
                    else handoff.recovery_resume_report_ref.artifact_hash
                ),
                "new_resume_report_would_be_created": False,
            }
            if handoff.accepted_resume_recovery
            else {"enabled": False}
        ),
        "runtime_observation_retry": (
            {
                "enabled": True,
                **dict(handoff.observation_retry_binding or {}),
                "runtime_output_root": str(
                    Path(selected_runtime_output_root).resolve()
                ),
                "prior_restoration": retry_restoration,
            }
            if handoff.runtime_observation_retry
            else {"enabled": False}
        ),
        "runtime_output": (
            {
                "enabled": True,
                **dict(runtime_output_report),
            }
            if runtime_output_report is not None
            else {"enabled": False}
        ),
        "external_action_gate": external_action_gate,
    }


def _runtime_profile_preflight_record(
    settings: Any,
    *,
    runtime_plugin_destination: str | Path,
    feature_spec: Mapping[str, Any],
    runtime_output_root: str | Path | None = None,
    selected_acceptance_criteria: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Validate one configured Runtime profile without granting external authority."""

    runtime = getattr(settings, "runtime", None)
    gtfo = getattr(runtime, "gtfo", None)
    if gtfo is None or getattr(gtfo, "enabled", False) is not True:
        raise LocalEntryError(
            "Runtime continuation preflight requires runtime.gtfo.enabled=true."
        )
    try:
        profile = profile_from_settings(settings)
    except GTFORuntimeAutomationError as exc:
        raise LocalEntryError(f"GTFO Runtime preflight failed: {exc}") from exc
    stagger_profile = stagger_profile_from_settings(settings)
    if runtime_output_root is not None:
        if stagger_profile is None:
            raise LocalEntryError(
                "Runtime output isolation is supported only for the reviewed "
                "Stagger profile."
            )
        profile = replace(
            profile,
            screenshot_directory=str(
                Path(runtime_output_root).resolve() / "runtime_captures"
            ),
        )
    destination_input = Path(runtime_plugin_destination)
    if not destination_input.is_absolute():
        raise LocalEntryError(
            "runtime_plugin_destination must be an absolute .dll path."
        )
    destination = destination_input.resolve()
    working_directory = Path(profile.working_directory).resolve()
    try:
        destination.relative_to(working_directory)
    except ValueError as exc:
        raise LocalEntryError(
            "runtime_plugin_destination must remain inside "
            "runtime.gtfo.working_directory."
        ) from exc
    if destination.suffix.lower() != ".dll":
        raise LocalEntryError(
            "runtime_plugin_destination must identify one .dll file."
        )
    if not destination.parent.is_dir():
        raise LocalEntryError(
            "Runtime plugin destination directory does not exist: "
            f"{destination.parent}"
        )
    if profile.terminate_after_capture is not True:
        raise LocalEntryError(
            "Runtime continuation requires "
            "runtime.gtfo.terminate_after_capture=true."
        )
    acceptance_criteria = feature_spec.get("acceptance_criteria")
    marker_contract = feature_spec.get("success_marker_contract")
    if (
        not isinstance(acceptance_criteria, list)
        or not acceptance_criteria
        or any(not isinstance(item, str) or not item for item in acceptance_criteria)
        or not isinstance(marker_contract, Mapping)
    ):
        raise LocalEntryError(
            "Runtime continuation FeatureSpec marker contract is incomplete."
        )
    signal = marker_contract.get("signal")
    required_facts = marker_contract.get("code_level_required_facts")
    runtime_claim_limit = marker_contract.get("runtime_claim_limit")
    if (
        not isinstance(signal, str)
        or not signal
        or not isinstance(required_facts, list)
        or not required_facts
        or any(not isinstance(item, str) or not item for item in required_facts)
        or not isinstance(runtime_claim_limit, str)
        or not runtime_claim_limit
    ):
        raise LocalEntryError(
            "Runtime continuation FeatureSpec success_marker_contract is invalid."
        )
    marker_criteria = [
        criterion
        for criterion in acceptance_criteria
        if signal in criterion and all(fact in criterion for fact in required_facts)
    ]
    if len(marker_criteria) != 1:
        raise LocalEntryError(
            "Runtime continuation FeatureSpec does not bind one exact marker criterion."
        )
    configured_marker_criteria = set(profile.acceptance_markers)
    if configured_marker_criteria != {marker_criteria[0]}:
        raise LocalEntryError(
            "Runtime continuation acceptance_markers must bind only the exact "
            "FeatureSpec marker criterion."
        )
    configured_marker = profile.acceptance_markers[marker_criteria[0]]
    required_marker_parts = [f"signal={signal}", *required_facts]
    if any(part not in configured_marker for part in required_marker_parts):
        raise LocalEntryError(
            "Runtime continuation acceptance marker omits required marker fields."
        )
    if any(signal in marker for marker in profile.startup_markers):
        raise LocalEntryError(
            "Runtime continuation product marker cannot be a startup marker."
        )
    try:
        capability_report = build_gtfo_runtime_capability_report(
            profile,
            allow_game_launch=True,
            acceptance_criteria=tuple(acceptance_criteria),
        )
    except GTFORuntimeAutomationError as exc:
        raise LocalEntryError(f"GTFO Runtime preflight failed: {exc}") from exc
    if capability_report["status"] != "ready":
        raise LocalEntryError(
            "GTFO Runtime preflight blocked: "
            + "; ".join(str(item) for item in capability_report["blockers"])
        )
    capability_checks = dict(capability_report["checks"])
    capability_checks["explicit_launch_approval"] = {
        "status": "not_granted_preflight_only",
        "required": True,
        "allow_game_launch": False,
    }
    capability_report = {
        **capability_report,
        "checks": capability_checks,
        "would_launch": False,
        "authorization_status": "not_granted_preflight_only",
    }
    stagger_acceptance = None
    if stagger_profile is not None:
        if profile.operator_completion_required is not True:
            raise LocalEntryError(
                "Two-process stagger Runtime requires "
                "runtime.gtfo.operator_completion_required=true."
            )
        stagger_acceptance = build_gtfo_stagger_acceptance_report(
            stagger_profile,
            working_directory=profile.working_directory,
            acceptance_criteria=tuple(acceptance_criteria),
            selected_acceptance_criteria=selected_acceptance_criteria,
        )
        if stagger_acceptance["status"] != "ready":
            raise LocalEntryError(
                "GTFO stagger Runtime preflight blocked: "
                + "; ".join(
                    str(item) for item in stagger_acceptance["blockers"]
                )
            )
    return {
        "enabled": True,
        "profile": {
            "profile_id": profile.profile_id,
            "game_executable": profile.game_executable,
            "working_directory": profile.working_directory,
            "launch_args": list(profile.launch_args),
            "log_paths": list(profile.log_paths),
            "screenshot_directory": profile.screenshot_directory,
            "screenshot_timeout_seconds": profile.screenshot_timeout_seconds,
            "startup_markers": list(profile.startup_markers),
            "acceptance_markers": dict(profile.acceptance_markers),
            "timeout_seconds": profile.timeout_seconds,
            "poll_interval_seconds": profile.poll_interval_seconds,
            "output_limit_chars": profile.output_limit_chars,
            "terminate_after_capture": profile.terminate_after_capture,
            "operator_completion_required": profile.operator_completion_required,
            "operator_completion_timeout_seconds": (
                profile.operator_completion_timeout_seconds
            ),
        },
        "capability_report": capability_report,
        "stagger_acceptance": stagger_acceptance,
        "acceptance_boundary": {
            "feature_spec_marker_criterion": marker_criteria[0],
            "configured_marker": configured_marker,
            "success_marker_contract": dict(marker_contract),
            "marker_does_not_prove_visual_or_audio": True,
            "remaining_acceptance_criteria_require_separate_observation": [
                criterion
                for criterion in acceptance_criteria
                if criterion != marker_criteria[0]
            ],
        },
        "plugin_deployment": {
            "destination_path": str(destination),
            "allow_game_directory_write": False,
            "restore_after_runtime": True,
            "performed": False,
            "destination_existed_at_preflight": destination.is_file(),
            "destination_sha256_at_preflight": (
                hashlib.sha256(destination.read_bytes()).hexdigest()
                if destination.is_file()
                else None
            ),
            "recovery_boundary": (
                "restore the exact preflight destination bytes when present; "
                "otherwise remove only the deployed destination DLL"
            ),
        },
    }


def _runtime_evidence_only_terminal_result(
    *,
    status: str,
    failure_stage: str | None,
    preflight: Mapping[str, Any] | None,
    factory_invocation_count: int,
    resume_report: Mapping[str, Any] | None = None,
    runtime_evidence: Mapping[str, Any] | None = None,
    runtime_summary: Mapping[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_preflight = dict(preflight or {})
    selected_summary = dict(runtime_summary or {})
    identity = selected_preflight.get("identity")
    checkpoint = selected_preflight.get("checkpoint")
    return {
        "status": status,
        "failure_stage": failure_stage,
        "feature_id": (
            identity.get("feature_id") if isinstance(identity, Mapping) else None
        ),
        "run_id": identity.get("run_id") if isinstance(identity, Mapping) else None,
        "request_id": (
            identity.get("request_id") if isinstance(identity, Mapping) else None
        ),
        "resume_id": (
            (selected_preflight.get("runtime_execution_identity") or {}).get(
                "resume_id"
            )
        ),
        "checkpoint_id": (
            checkpoint.get("checkpoint_id")
            if isinstance(checkpoint, Mapping)
            else None
        ),
        "runtime_execution_identity": selected_preflight.get(
            "runtime_execution_identity"
        ),
        "runtime_execution_identity_hash": selected_preflight.get(
            "runtime_execution_identity_hash"
        ),
        "runtime_preflight": selected_preflight or None,
        "runtime_execution": {
            "factory_invocation_count": factory_invocation_count,
            "side_effects_may_have_started": factory_invocation_count > 0,
            "verification_status": selected_summary.get("status"),
            "acceptance_status": selected_summary.get("acceptance_status"),
            "acceptance_verified": selected_summary.get("acceptance_verified"),
            "claims_real_runtime_success": selected_summary.get(
                "claims_real_runtime_success"
            ),
        },
        "resume_report": None if resume_report is None else dict(resume_report),
        "runtime_evidence": (
            None if runtime_evidence is None else dict(runtime_evidence)
        ),
        "runtime_evidence_ready": bool(
            runtime_evidence is not None
            and runtime_evidence.get("artifact_ref") is not None
            and (runtime_evidence.get("store_result") or {}).get("outcome")
            == "committed"
        ),
        "blockers": list(blockers or ()),
        "automatic_retry_count": 0,
        "recovery_performed": False,
        "presentation_written": False,
    }


def _validate_runtime_handoff_build_output(
    handoff: _RuntimeContinuationHandoff,
) -> None:
    """Revalidate the exact Build output after the Runtime factory returns."""

    artifacts = handoff.build.get("verified_artifacts") or []
    if len(artifacts) != 1 or not isinstance(artifacts[0], Mapping):
        raise LocalEntryError(
            "Runtime continuation Build output binding is incomplete."
        )
    artifact = artifacts[0]
    path = Path(str(artifact.get("resolved_path") or ""))
    try:
        stat = path.stat()
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise LocalEntryError(
            f"Runtime continuation Build output cannot be revalidated: {exc}"
        ) from exc
    if (
        not path.is_file()
        or actual_hash != artifact.get("sha256")
        or stat.st_size != artifact.get("size_bytes")
        or stat.st_mtime != float(artifact.get("mtime"))
    ):
        raise LocalEntryError(
            "Runtime continuation verified Build output identity changed."
        )


def _execute_runtime_evidence_only_continuation(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    approved_by: str,
    resume_id: str | None,
    runtime_evidence_factory: Callable[
        [str, dict[str, Any], dict[str, Any]], dict[str, Any]
    ] | None,
    injected_runtime_admission: Mapping[str, Any] | None,
    expected_runtime_execution_identity_hash: str | None,
) -> dict[str, Any]:
    """Execute one admitted RuntimeEvidence-only continuation."""

    try:
        preflight = preflight_local_runtime(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            resume_id=resume_id,
            approved_by=approved_by,
            injected_runtime_admission=injected_runtime_admission,
            runtime_evidence_only=True,
        )
    except LocalEntryError as exc:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="admission",
            preflight=None,
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": "RUNTIME_EVIDENCE_PREFLIGHT_BLOCKED",
                    "message": str(exc),
                }
            ],
        )
    actual_identity_hash = str(preflight["runtime_execution_identity_hash"])
    expected_identity_is_valid = bool(
        isinstance(expected_runtime_execution_identity_hash, str)
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            expected_runtime_execution_identity_hash,
        )
    )
    if not expected_identity_is_valid or not hmac.compare_digest(
        str(expected_runtime_execution_identity_hash),
        actual_identity_hash,
    ):
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="authorization",
            preflight=preflight,
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": (
                        "RUNTIME_EXECUTION_IDENTITY_MISMATCH"
                        if expected_identity_is_valid
                        else "RUNTIME_EXECUTION_IDENTITY_REQUIRED"
                    ),
                    "message": (
                        "Runtime execution inputs changed after the reviewed preflight."
                    ),
                }
            ],
        )
    if preflight["status"] != "READY_FOR_RUNTIME_EXECUTION":
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="admission",
            preflight=preflight,
            factory_invocation_count=0,
            blockers=list(preflight.get("blockers") or ()),
        )
    if runtime_evidence_factory is None:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="admission",
            preflight=preflight,
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": "RUNTIME_EVIDENCE_FACTORY_REQUIRED",
                    "message": (
                        "RuntimeEvidence-only continuation requires an injected "
                        "Runtime factory."
                    ),
                }
            ],
        )

    try:
        handoff = _load_runtime_continuation_handoff(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            resume_id=resume_id,
            require_manifest=False,
            allow_blocked_resume=True,
        )
    except LocalEntryError as exc:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="admission",
            preflight=preflight,
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": "RUNTIME_HANDOFF_REVALIDATION_FAILED",
                    "message": str(exc),
                }
            ],
        )
    if handoff.resume_readiness is None or not handoff.resume_readiness.allowed:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="admission",
            preflight=preflight,
            factory_invocation_count=0,
            blockers=(
                []
                if handoff.resume_readiness is None
                else list(handoff.resume_readiness.blockers)
            ),
        )
    try:
        payload = _verification_only_runtime_resume_payload(
            handoff=handoff,
            resume_id=str(resume_id),
            approved_by=approved_by,
            runtime_admission=preflight["runtime_admission"],
            approved_at=datetime.now(timezone.utc).isoformat(),
        )
        checkpoint_store = WorkflowCheckpointStore(handoff.artifact_store)
        decision, resume_write_result = checkpoint_store.resume_with_result(
            handoff.checkpoint_ref,
            payload,
        )
    except Exception as exc:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="resume_admission",
            preflight=preflight,
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": "RUNTIME_RESUME_ADMISSION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )
    resume_projection = {
        "artifact_ref": (
            None
            if resume_write_result.artifact_ref is None
            else {
                "feature_id": resume_write_result.artifact_ref.feature_id,
                "artifact_type": resume_write_result.artifact_ref.artifact_type,
                "path": resume_write_result.artifact_ref.path,
                "artifact_hash": resume_write_result.artifact_ref.artifact_hash,
            }
        ),
        "store_result": resume_write_result.to_dict(),
        "decision": decision.to_dict(),
    }
    if resume_write_result.outcome != "committed":
        return _runtime_evidence_only_terminal_result(
            status=(
                "partial" if resume_write_result.outcome == "partial" else "blocked"
            ),
            failure_stage="resume_report_store",
            preflight=preflight,
            factory_invocation_count=0,
            resume_report=resume_projection,
            blockers=list(decision.blockers),
        )
    if not decision.allowed or resume_write_result.artifact_ref is None:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="resume_admission",
            preflight=preflight,
            factory_invocation_count=0,
            resume_report=resume_projection,
            blockers=list(decision.blockers),
        )

    try:
        resumed_state = resumed_state_from_decision(
            decision,
            checkpoint_ref=handoff.checkpoint_ref,
            resume_report_ref=resume_write_result.artifact_ref,
        )
    except Exception as exc:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="resume_admission",
            preflight=preflight,
            factory_invocation_count=0,
            resume_report=resume_projection,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": "RUNTIME_RESUMED_STATE_RECONSTRUCTION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )
    caller_factory_invocations = 0
    effect_wrapper_invocations = 0

    def admitted_runtime_evidence_factory(
        selected_feature_id: str,
        build: dict[str, Any],
        feature_spec: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal caller_factory_invocations
        nonlocal effect_wrapper_invocations
        if effect_wrapper_invocations != 0:
            raise LocalEntryError(
                "RuntimeEvidence effect wrapper was invoked more than once."
            )
        effect_wrapper_invocations = 1
        try:
            handoff.artifact_store.preflight_atomic_commit(
                feature_id=feature_id,
                artifact_types=("runtime_evidence",),
            )
        except Exception as exc:
            raise _RuntimeEvidenceExecutionBoundaryError(
                "store_preflight",
                exc,
            ) from exc
        caller_factory_invocations = 1
        try:
            result = runtime_evidence_factory(
                selected_feature_id,
                build,
                feature_spec,
            )
        except Exception as exc:
            raise _RuntimeEvidenceExecutionBoundaryError(
                "runtime_execution",
                exc,
            ) from exc
        try:
            _validate_runtime_handoff_build_output(handoff)
        except Exception as exc:
            raise _RuntimeEvidenceExecutionBoundaryError(
                "post_runtime_validation",
                exc,
            ) from exc
        return result

    graph = build_graph(
        handoff.artifact_store,
        runtime_evidence_factory=admitted_runtime_evidence_factory,
        runtime_evidence_write_results=True,
        runtime_continuation_checkpoint_id=str(
            handoff.checkpoint["checkpoint_id"]
        ),
        use_default_proposal_git_binding=False,
        interrupt_after=["collect_runtime_evidence"],
    )
    try:
        graph_result = graph.invoke(resumed_state)
    except Exception as exc:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage=(
                "graph_admission"
                if caller_factory_invocations == 0
                else "post_runtime_validation"
            ),
            preflight=preflight,
            factory_invocation_count=caller_factory_invocations,
            resume_report=resume_projection,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": "RUNTIME_EVIDENCE_GRAPH_EXECUTION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )

    runtime_summary = dict(graph_result.get("runtime_summary") or {})
    runtime_store_result = runtime_summary.get("runtime_evidence_store_result")
    runtime_ref = None
    if "runtime_evidence" in graph_result.get("artifacts", {}):
        runtime_ref = {
            "feature_id": feature_id,
            "artifact_type": "runtime_evidence",
            "path": graph_result["artifacts"]["runtime_evidence"],
            "artifact_hash": graph_result["artifact_hashes"]["runtime_evidence"],
        }
    runtime_projection = (
        None
        if runtime_store_result is None and runtime_ref is None
        else {
            "artifact_ref": runtime_ref,
            "store_result": runtime_store_result,
            "verification_status": runtime_summary.get("status"),
            "acceptance_status": runtime_summary.get("acceptance_status"),
            "acceptance_verified": runtime_summary.get("acceptance_verified"),
        }
    )
    failure_stage = runtime_summary.get("platform_failure_stage")
    outer_status = "completed" if failure_stage is None else "blocked"
    if (
        isinstance(runtime_store_result, Mapping)
        and runtime_store_result.get("outcome") == "partial"
    ):
        outer_status = "partial"
    return _runtime_evidence_only_terminal_result(
        status=outer_status,
        failure_stage=failure_stage,
        preflight=preflight,
        factory_invocation_count=caller_factory_invocations,
        resume_report=resume_projection,
        runtime_evidence=runtime_projection,
        runtime_summary=runtime_summary,
        blockers=list(graph_result.get("blockers") or ()),
    )


def _runtime_evidence_consolidation_public_result(
    *,
    status: str,
    failure_stage: str | None,
    preflight: Mapping[str, Any] | None,
    runtime_evidence: Mapping[str, Any] | None = None,
    runtime_summary: Mapping[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected = dict(preflight or {})
    summary = dict(runtime_summary or {})
    return {
        "status": status,
        "failure_stage": failure_stage,
        "feature_id": (selected.get("identity") or {}).get("feature_id"),
        "run_id": (selected.get("identity") or {}).get("run_id"),
        "request_id": (selected.get("identity") or {}).get("request_id"),
        "resume_id": (
            selected.get("runtime_evidence_consolidation_identity") or {}
        ).get("protocol_binding", {}).get("resume_id"),
        "runtime_evidence_consolidation_identity": selected.get(
            "runtime_evidence_consolidation_identity"
        ),
        "runtime_evidence_consolidation_identity_hash": selected.get(
            "runtime_evidence_consolidation_identity_hash"
        ),
        "canonical_delta_hash": selected.get("canonical_delta_hash"),
        "derived_runtime_evidence_payload_hash": selected.get(
            "derived_runtime_evidence_payload_hash"
        ),
        "runtime_evidence_consolidation_preflight": selected or None,
        "runtime_evidence": (
            None if runtime_evidence is None else dict(runtime_evidence)
        ),
        "domain_result": {
            "criterion_id": (selected.get("canonical_delta") or {}).get(
                "criterion_id"
            ),
            "before": (selected.get("canonical_delta") or {}).get("before"),
            "after": (selected.get("canonical_delta") or {}).get("after"),
            "acceptance_status": summary.get("acceptance_status"),
            "acceptance_verified": summary.get("acceptance_verified"),
            "claims_real_runtime_success": summary.get(
                "claims_real_runtime_success"
            ),
        },
        "new_build_performed": False,
        "new_runtime_performed": False,
        "product_source_modified": False,
        "runtime_factory_invocation_count": 0,
        "automatic_retry_count": 0,
        "recovery_performed": False,
        "presentation_written": False,
        "blockers": list(blockers or ()),
    }


def _execute_runtime_evidence_consolidation(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    operation: VerificationOperationEnvelope,
    expected_identity_hash: str | None,
) -> dict[str, Any]:
    """Execute one admitted Store-only RuntimeEvidence consolidation."""

    try:
        validated_operation = validate_verification_operation_envelope(operation)
        protocol = validated_operation.protocol_binding
        preflight = preflight_local_runtime(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            resume_id=protocol.resume_id,
            approved_by=protocol.approved_by,
            verification_operation=validated_operation.to_spec(),
        )
    except (LocalEntryError, OSError, ValueError) as exc:
        return _runtime_evidence_consolidation_public_result(
            status="blocked",
            failure_stage="consolidation_admission",
            preflight=None,
            blockers=[
                {
                    "stage": "runtime_evidence_consolidation",
                    "code": "RUNTIME_EVIDENCE_CONSOLIDATION_ADMISSION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )
    actual_identity_hash = str(
        preflight["approval_identity_hash"]
    )
    expected_hash_is_valid = bool(
        isinstance(expected_identity_hash, str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", expected_identity_hash)
    )
    if not expected_hash_is_valid or not hmac.compare_digest(
        str(expected_identity_hash),
        actual_identity_hash,
    ):
        return _runtime_evidence_consolidation_public_result(
            status="blocked",
            failure_stage="authorization",
            preflight=preflight,
            blockers=[
                {
                    "stage": "runtime_evidence_consolidation",
                    "code": (
                        "RUNTIME_EVIDENCE_CONSOLIDATION_IDENTITY_MISMATCH"
                        if expected_hash_is_valid
                        else "RUNTIME_EVIDENCE_CONSOLIDATION_IDENTITY_REQUIRED"
                    ),
                    "message": "Consolidation action changed after preflight.",
                }
            ],
        )
    if preflight["status"] != "READY_FOR_RUNTIME_EVIDENCE_CONSOLIDATION":
        return _runtime_evidence_consolidation_public_result(
            status="blocked",
            failure_stage="consolidation_admission",
            preflight=preflight,
            blockers=list(preflight.get("blockers") or ()),
        )
    try:
        handoff = _load_runtime_evidence_consolidation_handoff(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            operation=validated_operation,
        )
        if handoff.operation.approval_identity_hash != actual_identity_hash:
            raise LocalEntryError(
                "RuntimeEvidence consolidation identity drifted before Graph."
            )
        state = resumed_state_from_decision(
            handoff.decision,
            checkpoint_ref=handoff.build_handoff.checkpoint_ref,
            resume_report_ref=handoff.resume_report_ref,
        )
        state["artifacts"]["runtime_evidence"] = (
            handoff.prior_runtime_evidence_ref.path
        )
        state["artifact_hashes"]["runtime_evidence"] = (
            handoff.prior_runtime_evidence_ref.artifact_hash
        )
        state["artifacts"]["evidence_pack"] = handoff.evidence_pack_ref.path
        state["artifact_hashes"]["evidence_pack"] = (
            handoff.evidence_pack_ref.artifact_hash
        )
        prior_payload = handoff.build_handoff.artifact_store.read(
            handoff.prior_runtime_evidence_ref
        )["data"]
        state["runtime_summary"] = _runtime_summary_from_payload(prior_payload)
        state["current_stage"] = "runtime_evidence"
        graph = build_graph(
            handoff.build_handoff.artifact_store,
            verification_operation=handoff.operation,
            runtime_evidence_write_results=True,
            use_default_proposal_git_binding=False,
            interrupt_after=["collect_runtime_evidence"],
        )
        graph_result = graph.invoke(state)
    except Exception as exc:
        return _runtime_evidence_consolidation_public_result(
            status="blocked",
            failure_stage="graph_consolidation_admission",
            preflight=preflight,
            blockers=[
                {
                    "stage": "runtime_evidence_consolidation",
                    "code": "RUNTIME_EVIDENCE_CONSOLIDATION_GRAPH_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )

    runtime_summary = dict(graph_result.get("runtime_summary") or {})
    store_result = runtime_summary.get("runtime_evidence_store_result")
    runtime_ref = None
    artifact_path = (graph_result.get("artifacts") or {}).get(
        "runtime_evidence"
    )
    artifact_hash = (graph_result.get("artifact_hashes") or {}).get(
        "runtime_evidence"
    )
    if isinstance(artifact_path, str) and isinstance(artifact_hash, str):
        runtime_ref = {
            "feature_id": feature_id,
            "artifact_type": "runtime_evidence",
            "path": artifact_path,
            "artifact_hash": artifact_hash,
        }
    runtime_projection = (
        None
        if store_result is None and runtime_ref is None
        else {"artifact_ref": runtime_ref, "store_result": store_result}
    )
    failure_stage = runtime_summary.get("platform_failure_stage")
    outer_status = "completed" if failure_stage is None else "blocked"
    if isinstance(store_result, Mapping):
        if store_result.get("outcome") == "partial":
            outer_status = "partial"
        elif store_result.get("outcome") == "blocked_before_commit":
            outer_status = "blocked"
    return _runtime_evidence_consolidation_public_result(
        status=outer_status,
        failure_stage=failure_stage,
        preflight=preflight,
        runtime_evidence=runtime_projection,
        runtime_summary=runtime_summary,
        blockers=list(graph_result.get("blockers") or ()),
    )


def _runtime_terminal_artifact_projection(
    state: Mapping[str, Any],
    artifact_type: str,
    store_result_key: str,
) -> dict[str, Any] | None:
    runtime_summary = state.get("runtime_summary") or {}
    store_result = runtime_summary.get(store_result_key)
    artifact_path = (state.get("artifacts") or {}).get(artifact_type)
    artifact_hash = (state.get("artifact_hashes") or {}).get(artifact_type)
    if store_result is None and artifact_path is None:
        return None
    return {
        "artifact_ref": (
            None
            if artifact_path is None or artifact_hash is None
            else {
                "feature_id": state.get("feature_id") or state.get("request_id"),
                "artifact_type": artifact_type,
                "path": artifact_path,
                "artifact_hash": artifact_hash,
            }
        ),
        "store_result": store_result,
    }


def _runtime_terminal_public_result(
    *,
    status: str,
    failure_stage: str | None,
    preflight: Mapping[str, Any] | None,
    state: Mapping[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_state = state or {}
    runtime_summary = dict(selected_state.get("runtime_summary") or {})
    return {
        "status": status,
        "failure_stage": failure_stage,
        "operation": "runtime_terminalization_only",
        "runtime_terminal_execution_identity": (
            None
            if preflight is None
            else preflight.get("runtime_terminal_execution_identity")
        ),
        "runtime_terminal_execution_identity_hash": (
            None
            if preflight is None
            else preflight.get("runtime_terminal_execution_identity_hash")
        ),
        "runtime_preflight": None if preflight is None else dict(preflight),
        "inputs": (
            None
            if preflight is None
            else {
                "checkpoint": preflight.get("checkpoint"),
                "accepted_resume_report": preflight.get(
                    "accepted_resume_report"
                ),
                "runtime_evidence": preflight.get("runtime_evidence"),
            }
        ),
        "blocked_report": _runtime_terminal_artifact_projection(
            selected_state,
            "blocked_report",
            "blocked_report_store_result",
        ),
        "eval_report": _runtime_terminal_artifact_projection(
            selected_state,
            "eval_report",
            "eval_report_store_result",
        ),
        "workflow_summary": _runtime_terminal_artifact_projection(
            selected_state,
            "workflow_summary",
            "workflow_summary_store_result",
        ),
        "terminal_route": runtime_summary.get("terminal_route"),
        "terminal_ready": runtime_summary.get("terminal_ready") is True,
        "domain_result": {
            "final_status": runtime_summary.get("terminal_final_status"),
            "claims_real_mod_success": runtime_summary.get(
                "terminal_claims_real_mod_success"
            ),
            "runtime_acceptance_status": runtime_summary.get(
                "acceptance_status"
            ),
            "runtime_acceptance_verified": runtime_summary.get(
                "acceptance_verified"
            ),
        },
        "blockers": list(blockers or selected_state.get("blockers") or ()),
        "automatic_retry_count": 0,
        "recovery_performed": False,
        "presentation_written": False,
        "runtime_factory_invocation_count": 0,
        "process_launched": False,
        "game_directory_write_performed": False,
    }


def _execute_runtime_terminal_continuation(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    accepted_resume_report_path: str | Path,
    accepted_resume_report_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    approved_by: str,
    resume_id: str,
    expected_runtime_terminal_identity_hash: str | None,
) -> dict[str, Any]:
    """Execute one Store-only terminal continuation through the StateGraph."""

    try:
        preflight = _preflight_runtime_terminal_continuation(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            accepted_resume_report_path=accepted_resume_report_path,
            accepted_resume_report_hash=accepted_resume_report_hash,
            runtime_evidence_path=runtime_evidence_path,
            runtime_evidence_hash=runtime_evidence_hash,
            resume_id=resume_id,
            approved_by=approved_by,
        )
    except LocalEntryError as exc:
        return _runtime_terminal_public_result(
            status="blocked",
            failure_stage="terminal_admission",
            preflight=None,
            blockers=[
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_ADMISSION_FAILED",
                    "message": str(exc),
                }
            ],
        )
    actual_identity_hash = str(
        preflight["runtime_terminal_execution_identity_hash"]
    )
    expected_identity_is_valid = bool(
        isinstance(expected_runtime_terminal_identity_hash, str)
        and re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            expected_runtime_terminal_identity_hash,
        )
    )
    if not expected_identity_is_valid or not hmac.compare_digest(
        str(expected_runtime_terminal_identity_hash),
        actual_identity_hash,
    ):
        return _runtime_terminal_public_result(
            status="blocked",
            failure_stage="authorization",
            preflight=preflight,
            blockers=[
                {
                    "stage": "runtime_terminalization",
                    "code": (
                        "RUNTIME_TERMINAL_IDENTITY_MISMATCH"
                        if expected_identity_is_valid
                        else "RUNTIME_TERMINAL_IDENTITY_REQUIRED"
                    ),
                    "message": (
                        "Runtime terminal inputs changed after reviewed preflight."
                    ),
                }
            ],
        )
    if preflight["status"] != "READY_FOR_RUNTIME_TERMINALIZATION":
        return _runtime_terminal_public_result(
            status="blocked",
            failure_stage="terminal_admission",
            preflight=preflight,
            blockers=list(preflight.get("blockers") or ()),
        )

    try:
        handoff = _load_runtime_terminal_handoff(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            accepted_resume_report_path=accepted_resume_report_path,
            accepted_resume_report_hash=accepted_resume_report_hash,
            runtime_evidence_path=runtime_evidence_path,
            runtime_evidence_hash=runtime_evidence_hash,
            resume_id=resume_id,
            approved_by=approved_by,
        )
        if not handoff.decision.allowed or handoff.existing_terminal_refs:
            raise LocalEntryError(
                "Runtime terminal admission changed before Graph entry."
            )
        state = resumed_state_from_decision(
            handoff.decision,
            checkpoint_ref=handoff.build_handoff.checkpoint_ref,
            resume_report_ref=handoff.resume_report_ref,
        )
        state["artifacts"] = {
            **dict(state["artifacts"]),
            "runtime_evidence": handoff.runtime_evidence_ref.path,
        }
        state["artifact_hashes"] = {
            **dict(state["artifact_hashes"]),
            "runtime_evidence": handoff.runtime_evidence_ref.artifact_hash,
        }
        state["current_stage"] = "runtime_evidence"
        state["next_stage"] = None
        state["runtime_summary"] = _runtime_summary_from_payload(
            handoff.runtime_evidence
        )
    except Exception as exc:
        return _runtime_terminal_public_result(
            status="blocked",
            failure_stage="terminal_admission",
            preflight=preflight,
            blockers=[
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_STATE_RECONSTRUCTION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )

    terminal_input = VerificationOnlyRuntimeTerminalInput(
        checkpoint_ref=handoff.build_handoff.checkpoint_ref,
        resume_report_ref=handoff.resume_report_ref,
        runtime_evidence_ref=handoff.runtime_evidence_ref,
        resume_id=resume_id,
        approved_by=approved_by,
    )
    graph = build_graph(
        handoff.build_handoff.artifact_store,
        runtime_terminal_continuation=terminal_input,
        runtime_terminal_write_results=True,
        use_default_proposal_git_binding=False,
    )
    try:
        graph_result = graph.invoke(state)
    except Exception as exc:
        return _runtime_terminal_public_result(
            status="blocked",
            failure_stage="graph_terminal_admission",
            preflight=preflight,
            state=state,
            blockers=[
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_GRAPH_ADMISSION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )

    runtime_summary = dict(graph_result.get("runtime_summary") or {})
    failure_stage = runtime_summary.get("platform_failure_stage")
    terminal_ready = runtime_summary.get("terminal_ready") is True
    outer_status = "completed" if terminal_ready else "blocked"
    for result_key in (
        "eval_report_store_result",
        "blocked_report_store_result",
        "workflow_summary_store_result",
    ):
        result = runtime_summary.get(result_key)
        if isinstance(result, Mapping) and result.get("outcome") == "partial":
            outer_status = "partial"
            break
    return _runtime_terminal_public_result(
        status=outer_status,
        failure_stage=failure_stage,
        preflight=preflight,
        state=graph_result,
    )


def resume_local_runtime(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None = None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    settings_path: str | Path | None = None,
    approved_by: str,
    allow_game_launch: bool,
    runtime_plugin_destination: str | Path | None,
    allow_game_directory_write: bool,
    resume_id: str | None = None,
    recover_accepted_resume: bool = False,
    retry_runtime_observation: bool = False,
    runtime_output_root: str | Path | None = None,
    runtime_evidence_factory: (
        Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]] | None
    ) = None,
    injected_runtime_admission: Mapping[str, Any] | None = None,
    runtime_evidence_only: bool = False,
    expected_runtime_execution_identity_hash: str | None = None,
    runtime_terminalization_only: bool = False,
    verification_operation: VerificationOperationEnvelope | None = None,
    expected_approval_identity_hash: str | None = None,
    accepted_resume_report_path: str | Path | None = None,
    accepted_resume_report_hash: str | None = None,
    runtime_evidence_path: str | Path | None = None,
    runtime_evidence_hash: str | None = None,
    expected_runtime_terminal_identity_hash: str | None = None,
) -> dict[str, Any]:
    """Continue one validated Build handoff through the existing Runtime graph."""

    if verification_operation is not None:
        authorization_blockers: list[dict[str, Any]] = []
        try:
            operation = validate_verification_operation_envelope(
                verification_operation
            )
        except ValueError as exc:
            operation = None
            authorization_blockers.append(
                {
                    "stage": "verification_operation",
                    "code": "VERIFICATION_OPERATION_INVALID",
                    "message": str(exc),
                }
            )
        if not approved_by.strip():
            authorization_blockers.append(
                {
                    "stage": "verification_operation",
                    "code": "VERIFICATION_OPERATION_APPROVER_REQUIRED",
                    "message": "Verification operation requires exact approved_by.",
                }
            )
        if operation is not None and (
            approved_by != operation.protocol_binding.approved_by
            or resume_id not in {None, operation.protocol_binding.resume_id}
        ):
            authorization_blockers.append(
                {
                    "stage": "verification_operation",
                    "code": "VERIFICATION_OPERATION_PROTOCOL_MISMATCH",
                    "message": "Verification operation protocol identity changed.",
                }
            )
        if (
            runtime_evidence_only
            or runtime_terminalization_only
            or recover_accepted_resume
            or retry_runtime_observation
            or runtime_output_root is not None
            or runtime_evidence_factory is not None
            or injected_runtime_admission is not None
            or allow_game_launch
            or allow_game_directory_write
            or runtime_plugin_destination is not None
            or settings_path is not None
            or accepted_resume_report_path is not None
            or accepted_resume_report_hash is not None
            or runtime_evidence_path is not None
            or runtime_evidence_hash is not None
        ):
            authorization_blockers.append(
                {
                    "stage": "verification_operation",
                    "code": "VERIFICATION_OPERATION_SCOPE_INVALID",
                    "message": "Typed operation cannot mix with legacy Runtime scope.",
                }
            )
        if authorization_blockers:
            return _runtime_evidence_consolidation_public_result(
                status="blocked",
                failure_stage="authorization",
                preflight=None,
                blockers=authorization_blockers,
            )
        return _execute_runtime_evidence_consolidation(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            operation=operation,
            expected_identity_hash=expected_approval_identity_hash,
        )
    if runtime_terminalization_only:
        authorization_blockers: list[dict[str, Any]] = []
        if not approved_by.strip():
            authorization_blockers.append(
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_APPROVER_REQUIRED",
                    "message": "Runtime terminalization requires exact approved_by.",
                }
            )
        if (
            runtime_evidence_only
            or verification_operation is not None
            or recover_accepted_resume
            or retry_runtime_observation
            or runtime_output_root is not None
            or runtime_evidence_factory is not None
            or injected_runtime_admission is not None
            or allow_game_launch
            or allow_game_directory_write
            or runtime_plugin_destination is not None
        ):
            authorization_blockers.append(
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_SIDE_EFFECT_SCOPE_INVALID",
                    "message": (
                        "Runtime terminalization permits only Store terminal writes."
                    ),
                }
            )
        if not isinstance(resume_id, str) or not resume_id:
            authorization_blockers.append(
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_RESUME_ID_REQUIRED",
                    "message": (
                        "Runtime terminalization requires the exact resume_id."
                    ),
                }
            )
        if (
            accepted_resume_report_path is None
            or not isinstance(accepted_resume_report_hash, str)
            or runtime_evidence_path is None
            or not isinstance(runtime_evidence_hash, str)
        ):
            authorization_blockers.append(
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_EXACT_REFS_REQUIRED",
                    "message": (
                        "Runtime terminalization requires exact ResumeReport and "
                        "RuntimeEvidence refs."
                    ),
                }
            )
        if authorization_blockers:
            return _runtime_terminal_public_result(
                status="blocked",
                failure_stage="authorization",
                preflight=None,
                blockers=authorization_blockers,
            )
        return _execute_runtime_terminal_continuation(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            accepted_resume_report_path=accepted_resume_report_path,
            accepted_resume_report_hash=accepted_resume_report_hash,
            runtime_evidence_path=runtime_evidence_path,
            runtime_evidence_hash=runtime_evidence_hash,
            approved_by=approved_by,
            resume_id=resume_id,
            expected_runtime_terminal_identity_hash=(
                expected_runtime_terminal_identity_hash
            ),
        )
    if not approved_by.strip():
        raise LocalEntryError("Runtime continuation requires approved_by.")
    if runtime_evidence_only:
        if recover_accepted_resume or retry_runtime_observation:
            raise LocalEntryError(
                "RuntimeEvidence-only continuation supports only an initial resume."
            )
        return _execute_runtime_evidence_only_continuation(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            approved_by=approved_by,
            resume_id=resume_id,
            runtime_evidence_factory=runtime_evidence_factory,
            injected_runtime_admission=injected_runtime_admission,
            expected_runtime_execution_identity_hash=(
                expected_runtime_execution_identity_hash
            ),
        )
    if recover_accepted_resume and resume_id is None:
        raise LocalEntryError(
            "Accepted resume recovery requires the exact prior resume_id."
        )
    if retry_runtime_observation and resume_id is None:
        raise LocalEntryError(
            "Runtime observation retry requires the exact prior resume_id."
        )
    if recover_accepted_resume and retry_runtime_observation:
        raise LocalEntryError(
            "Accepted resume recovery and Runtime observation retry are "
            "mutually exclusive."
        )
    if retry_runtime_observation and runtime_output_root is None:
        raise LocalEntryError(
            "Runtime observation retry requires runtime_output_root."
        )
    if runtime_output_root is not None and not Path(runtime_output_root).is_absolute():
        raise LocalEntryError(
            "Stagger Runtime output root must be absolute."
        )
    if (
        recover_accepted_resume or retry_runtime_observation
    ) and injected_runtime_admission is not None:
        raise LocalEntryError(
            "Accepted ResumeReport reuse does not accept injected Runtime admission."
        )
    selected_resume_id = resume_id or f"resume_{uuid4().hex}"
    handoff = _load_runtime_continuation_handoff(
        run_root=run_root,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        checkpoint_path=checkpoint_path,
        checkpoint_hash=checkpoint_hash,
        resume_id=selected_resume_id,
        recover_accepted_resume=recover_accepted_resume,
        retry_runtime_observation=retry_runtime_observation,
    )
    accepted_output_binding = _accepted_runtime_output_binding(handoff)
    selected_runtime_output_root = runtime_output_root
    if recover_accepted_resume and accepted_output_binding is not None:
        bound_output_root = accepted_output_binding.get("runtime_output_root")
        if not isinstance(bound_output_root, str) or not bound_output_root:
            raise LocalEntryError(
                "Accepted Runtime output binding is incomplete."
            )
        if (
            runtime_output_root is not None
            and Path(runtime_output_root).resolve()
            != Path(bound_output_root).resolve()
        ):
            raise LocalEntryError(
                "Accepted resume recovery Runtime output root changed from the "
                "original ResumeReport."
            )
        selected_runtime_output_root = bound_output_root
    source_root = handoff.run_root
    root = (
        Path(selected_runtime_output_root).resolve()
        if selected_runtime_output_root is not None
        else source_root
    )
    artifact_store = handoff.artifact_store
    checkpoint_ref = handoff.checkpoint_ref
    checkpoint = handoff.checkpoint
    repair_attempt_projection: dict[str, Any] | None = None

    if injected_runtime_admission is not None:
        if runtime_evidence_factory is None:
            raise LocalEntryError(
                "Injected Runtime admission requires an injected Runtime factory."
            )
        runtime_admission = dict(injected_runtime_admission)
        graph_runtime_factory = runtime_evidence_factory
    else:
        settings = load_settings(settings_path)
        feature_acceptance_criteria = handoff.feature_spec.get(
            "acceptance_criteria"
        )
        exact_acceptance_criteria = (
            tuple(feature_acceptance_criteria)
            if isinstance(feature_acceptance_criteria, list)
            and all(
                isinstance(item, str) and bool(item)
                for item in feature_acceptance_criteria
            )
            else ()
        )
        runtime_admission = _runtime_admission_record(
            settings,
            run_gtfo_runtime=True,
            allow_game_launch=allow_game_launch,
            runtime_plugin_destination=runtime_plugin_destination,
            allow_game_directory_write=allow_game_directory_write,
            acceptance_criteria=exact_acceptance_criteria,
        )
        runtime_profile_record = _runtime_profile_preflight_record(
            settings,
            runtime_plugin_destination=runtime_plugin_destination,
            feature_spec=handoff.feature_spec,
            runtime_output_root=(
                root if selected_runtime_output_root is not None else None
            ),
            selected_acceptance_criteria=(
                tuple(
                    str(item)
                    for item in (handoff.observation_retry_binding or {}).get(
                        "retry_acceptance_criteria", ()
                    )
                )
                if retry_runtime_observation
                and "retry_acceptance_criteria"
                in (handoff.observation_retry_binding or {})
                else None
            ),
        )
        repair_attempt_projection = _stagger_repair_attempt_projection(
            handoff,
            runtime_profile_record,
        )
        if (
            repair_attempt_projection is not None
            and not recover_accepted_resume
            and not retry_runtime_observation
            and selected_runtime_output_root is None
        ):
            raise LocalEntryError(
                "Initial Stagger repair Runtime requires an independent "
                "absolute empty runtime_output_root."
            )
        build = handoff.build
        verified_artifacts = [
            item
            for item in build.get("verified_artifacts") or []
            if isinstance(item, Mapping)
        ]
        if len(verified_artifacts) != 1:
            raise LocalEntryError(
                "Runtime continuation requires exactly one verified Build output."
            )
        verified_artifact = verified_artifacts[0]
        resolved_path = verified_artifact.get("resolved_path")
        relative_path = verified_artifact.get("path")
        if not isinstance(resolved_path, str) or not isinstance(relative_path, str):
            raise LocalEntryError(
                "Runtime continuation Build output binding is incomplete."
            )
        destination = Path(
            str(runtime_admission["plugin_deployment"]["destination_path"])
        )
        if destination.name != Path(relative_path).name:
            raise LocalEntryError(
                "Runtime continuation destination filename does not match Build output."
            )
        backup_directory = root / "runtime_continuation_deployment_backup"
        if selected_runtime_output_root is not None:
            runtime_output_report = _runtime_observation_retry_output_report(
                source_run_root=source_root,
                runtime_output_root=root,
                feature_id=feature_id,
                stagger_enabled=(
                    runtime_admission.get("stagger_acceptance") is not None
                ),
                stagger_modes=(
                    tuple(
                        str(item)
                        for item in (handoff.observation_retry_binding or {}).get(
                            "retry_modes", ()
                        )
                    )
                    if retry_runtime_observation
                    and "retry_modes" in (handoff.observation_retry_binding or {})
                    else None
                ),
            )
            backup_report = runtime_output_report["deployment_backup"]
        else:
            runtime_output_report = None
            backup_report = _runtime_continuation_backup_report(
                root,
                stagger_enabled=(
                    runtime_admission.get("stagger_acceptance") is not None
                ),
            )
        if retry_runtime_observation:
            if runtime_output_report is None:
                raise LocalEntryError(
                    "Runtime observation retry output binding is missing."
                )
            _runtime_observation_retry_restoration_report(handoff)
        if accepted_output_binding is not None:
            runtime_admission["runtime_output_binding"] = dict(
                accepted_output_binding
            )
        elif (
            runtime_output_report is not None
            and not retry_runtime_observation
        ):
            runtime_admission["runtime_output_binding"] = (
                _runtime_output_admission_binding(runtime_output_report)
            )
        stagger_admission = runtime_admission.get("stagger_acceptance")
        stagger_config = (
            stagger_admission.get("config")
            if isinstance(stagger_admission, Mapping)
            else None
        )
        graph_runtime_factory = _make_deploying_runtime_evidence_factory(
            settings=settings,
            allow_game_launch=allow_game_launch,
            allow_game_directory_write=allow_game_directory_write,
            build_artifact_path=Path(resolved_path),
            expected_artifact=relative_path,
            destination_path=destination,
            backup_directory=backup_directory,
            expected_destination_existed=bool(
                runtime_admission["plugin_deployment"][
                    "destination_existed_at_admission"
                ]
            ),
            expected_destination_sha256=runtime_admission["plugin_deployment"][
                "destination_sha256_at_admission"
            ],
            expected_config_destination_existed=(
                bool(stagger_config["destination_existed"])
                if isinstance(stagger_config, Mapping)
                else None
            ),
            expected_config_destination_sha256=(
                stagger_config.get("destination_sha256")
                if isinstance(stagger_config, Mapping)
                else None
            ),
            runtime_output_directory=(
                root if selected_runtime_output_root is not None else None
            ),
            runtime_observation_retry=(
                {
                    **dict(handoff.observation_retry_binding or {}),
                    "runtime_output_root": str(root),
                }
                if retry_runtime_observation
                else None
            ),
            operator_completion_directory=(
                root / "operator_completion"
                if selected_runtime_output_root is not None
                else None
            ),
            runtime_run_id=str(checkpoint["run_id"]),
            repair_attempt_projection=repair_attempt_projection,
            runtime_attempt_namespace=(
                None
                if repair_attempt_projection is None
                else _stagger_runtime_attempt_namespace(
                    repair_attempt_projection,
                    runtime_observation_retry=(
                        handoff.observation_retry_binding
                        if retry_runtime_observation
                        else None
                    ),
                )
            ),
        )

    admission_snapshot = _runtime_resume_admission_snapshot(runtime_admission)
    payload = ResumePayload(
        resume_id=selected_resume_id,
        run_id=str(checkpoint["run_id"]),
        request_id=str(checkpoint["request_id"]),
        feature_id=str(checkpoint["feature_id"]),
        stage="build",
        decision="approve",
        approved_by=approved_by,
        approved_at=datetime.now(timezone.utc).isoformat(),
        artifact_refs=tuple(checkpoint["artifact_refs"]),
        notes="Fresh-process Build-to-Runtime continuation.",
        runtime_admission=admission_snapshot,
    )
    checkpoint_store = WorkflowCheckpointStore(artifact_store)
    if recover_accepted_resume or retry_runtime_observation:
        decision = handoff.recovery_decision
        resume_report_ref = handoff.recovery_resume_report_ref
        if decision is None or resume_report_ref is None:
            raise LocalEntryError(
                "Accepted resume recovery binding is incomplete."
            )
        original_admission = decision.applied_updates.get("runtime_admission")
        if original_admission != admission_snapshot:
            raise LocalEntryError(
                "Accepted ResumeReport Runtime admission changed from the "
                "original admission."
            )
    else:
        decision, resume_report_ref = checkpoint_store.resume(checkpoint_ref, payload)
    if not decision.allowed:
        blocker_codes = [
            str(blocker.get("code"))
            for blocker in decision.blockers
            if isinstance(blocker, Mapping)
        ]
        raise LocalEntryError(
            "Runtime continuation resume was blocked: " + ", ".join(blocker_codes)
        )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_report_ref,
    )
    graph = build_graph(
        artifact_store,
        runtime_evidence_factory=graph_runtime_factory,
        runtime_continuation_checkpoint_id=str(checkpoint["checkpoint_id"]),
        use_default_proposal_git_binding=False,
    )
    try:
        result = graph.invoke(resumed_state)
    except Exception as exc:
        raise LocalEntryError(
            f"Runtime continuation graph failed: {type(exc).__name__}: {exc}"
        ) from exc

    summary = {
        "run_id": result["run_id"],
        "request_id": result["request_id"],
        "feature_id": result["feature_id"],
        "resume_id": payload.resume_id,
        "accepted_resume_recovery": recover_accepted_resume,
        "runtime_observation_retry": retry_runtime_observation,
        "runtime_observation_retry_binding": (
            {
                **dict(handoff.observation_retry_binding or {}),
                "runtime_output_root": str(root),
            }
            if retry_runtime_observation
            else None
        ),
        "checkpoint_id": checkpoint["checkpoint_id"],
        "current_stage": result["current_stage"],
        "artifacts": result["artifacts"],
        "runtime_summary": result["runtime_summary"],
        "runtime_admission": runtime_admission,
        "deployment_backup": (
            backup_report if injected_runtime_admission is None else None
        ),
        "runtime_output_root": str(root),
        "source_run_root": str(source_root),
        "runtime_verification_chain": _runtime_verification_chain(
            result,
            requested=True,
        ),
        "model_call_count": 0,
        "upstream_stages_repeated": False,
    }
    result_path = root / "runtime_resume_result.json"
    result_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _source_snapshot(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and "bin" not in path.parts and "obj" not in path.parts
    ]


def _source_snapshot_sha256(snapshot: list[dict[str, Any]]) -> str:
    return _sha256_json(snapshot)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_source_revision_binding(
    *,
    source: Path,
    snapshot: list[dict[str, Any]],
    snapshot_sha256: str,
    binding: Mapping[str, str] | None,
) -> None:
    if binding is None:
        return
    expected_snapshot = binding.get("complete_snapshot_sha256")
    if expected_snapshot != snapshot_sha256:
        raise LocalEntryError("Canonical source complete snapshot SHA256 does not match binding.")
    plugin_entry = next(
        (item for item in snapshot if item.get("path") == "Plugin.cs"),
        None,
    )
    if plugin_entry is None:
        raise LocalEntryError("Canonical source binding requires Plugin.cs.")
    if binding.get("plugin_cs_sha256") != plugin_entry.get("sha256"):
        raise LocalEntryError("Canonical source Plugin.cs SHA256 does not match binding.")
    if not binding.get("repository_head") or not binding.get("subtree_tree"):
        raise LocalEntryError("Canonical source binding requires repository_head and subtree_tree.")


def _external_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in items:
        selected = dict(item)
        source_path = selected.get("source_path")
        source_type = selected.get("source_type")
        if isinstance(source_path, str) and isinstance(source_type, str):
            selected["source_ref"] = f"source://{source_type}/{source_path}"
        else:
            selected.pop("source_ref", None)
        sanitized.append(selected)
    return sanitized


def _assert_no_absolute_local_paths(value: Any) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _assert_no_absolute_local_paths(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _assert_no_absolute_local_paths(nested)
        return
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        return
    if Path(value).is_absolute() or (
        len(value) >= 3
        and value[0].isalpha()
        and value[1] == ":"
        and value[2] in {"/", "\\"}
    ):
        raise LocalEntryError("External model payload contains an absolute local path.")


def _verify_exact_snapshot_change(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    relative_path: str,
    before_sha256: str,
    after_sha256: str,
) -> dict[str, Any]:
    before_by_path = {str(item["path"]): item for item in before}
    after_by_path = {str(item["path"]): item for item in after}
    changed_paths = sorted(
        path
        for path in set(before_by_path) | set(after_by_path)
        if before_by_path.get(path) != after_by_path.get(path)
    )
    if changed_paths != [relative_path]:
        raise LocalEntryError("Isolated source changes do not match the approved file scope.")
    selected_before = before_by_path[relative_path]
    selected_after = after_by_path[relative_path]
    if selected_before.get("sha256") != before_sha256:
        raise LocalEntryError("Isolated source before SHA256 does not match approval binding.")
    if selected_after.get("sha256") != after_sha256:
        raise LocalEntryError("Isolated source after SHA256 does not match approved exact change.")
    return {
        "status": "passed",
        "changed_paths": changed_paths,
        "relative_path": relative_path,
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
    }


def _verify_bepin_plugin_identity(
    artifact_path: str | Path,
    *,
    inspector_path: str | Path,
    method_symbol: str,
    expected_guid: str,
    expected_name: str,
    expected_version: str,
) -> dict[str, Any]:
    artifact = Path(artifact_path).resolve()
    inspector = Path(inspector_path).resolve()
    if not artifact.is_file():
        raise LocalEntryError("Compiled artifact is missing for metadata inspection.")
    if not inspector.is_file():
        raise LocalEntryError("Configured IL inspector is missing.")
    completed = subprocess.run(
        ("dotnet", str(inspector), str(artifact), method_symbol),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise LocalEntryError(
            f"Compiled artifact inspection failed with exit code {completed.returncode}."
        )
    try:
        inspection = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LocalEntryError("Compiled artifact inspector returned invalid JSON.") from exc
    methods = inspection.get("methods") if isinstance(inspection, dict) else None
    matching_methods = [
        item
        for item in methods or []
        if isinstance(item, dict) and item.get("symbol") == method_symbol
    ]
    if len(matching_methods) != 1:
        raise LocalEntryError("Compiled artifact inspector did not resolve one exact method.")
    plugin_attributes = [
        item
        for item in matching_methods[0].get("declaring_type_custom_attributes") or []
        if isinstance(item, dict)
        and item.get("constructor") == "BepInEx.BepInPlugin..ctor"
    ]
    if len(plugin_attributes) != 1:
        raise LocalEntryError("Compiled artifact does not contain one BepInPlugin identity.")
    observed_identity = plugin_attributes[0].get("printable_ascii_runs")
    expected_identity = [expected_guid, expected_name, expected_version]
    if observed_identity != expected_identity:
        raise LocalEntryError("Compiled BepInPlugin identity does not match expected values.")
    stat = artifact.stat()
    return {
        "status": "passed",
        "artifact_path": str(artifact),
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "artifact_size_bytes": stat.st_size,
        "artifact_mtime_utc": datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        "inspector_path": str(inspector),
        "inspector_sha256": hashlib.sha256(inspector.read_bytes()).hexdigest(),
        "inspector_schema_version": inspection.get("schema_version"),
        "method_symbol": method_symbol,
        "bepin_plugin": {
            "guid": expected_guid,
            "name": expected_name,
            "version": expected_version,
        },
        "target_code_executed": inspection.get("target_code_executed"),
    }


def _source_disclosure_record(
    *,
    provider: str,
    model: str,
    base_url: str | None,
    approved_at: str,
    approval_id: str | None = None,
    provider_adapter: str | None = None,
    destination_url: str | None = None,
) -> dict[str, Any]:
    return {
        "approved": True,
        "approved_at": approved_at,
        "approval_id": approval_id,
        "approval_actor_type": "local_cli_invoker",
        "consent_mechanism": "--allow-source-disclosure",
        "provider_adapter": provider_adapter,
        "destination": {
            "provider": provider,
            "model": model,
            "base_url": _sanitized_endpoint_url(base_url),
            "request_url": _sanitized_endpoint_url(destination_url),
        },
        "approved_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "requested_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "scope": "this_run_only",
    }


def _local_no_external_disclosure_record() -> dict[str, Any]:
    return {
        "occurred": False,
        "approved": False,
        "approved_at": None,
        "approval_id": None,
        "approval_actor_type": None,
        "consent_mechanism": None,
        "provider_adapter": None,
        "destination": None,
        "approved_data_classes": [],
        "requested_data_classes": [],
        "scope": "this_run_only",
        "reason": "local_model_execution",
    }


def _local_model_admission_record(
    *,
    model_identity: Mapping[str, Any],
    provider_adapter: str,
) -> dict[str, Any]:
    base_url = str(model_identity["base_url"])
    return {
        "provider": "ollama",
        "model": str(model_identity["name"]),
        "model_digest": str(model_identity["digest"]),
        "provider_adapter": provider_adapter,
        "execution_locality": "local",
        "base_url": base_url,
        "destination": f"{base_url}/api/chat",
        "external_disclosure_occurred": False,
        "api_key_required": False,
        "api_key_read": False,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "machine_local",
    }


def _persist_local_failure_diagnostics(
    *,
    run_root: Path,
    error: BaseException,
    enabled: bool,
) -> dict[str, Any] | None:
    if not enabled:
        return None
    diagnostics: dict[str, Any] = {}
    diagnostic_content: str | None = None
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        current_diagnostics = getattr(current, "diagnostics", None)
        if isinstance(current_diagnostics, Mapping):
            diagnostics.update(current_diagnostics)
            embedded_content = current_diagnostics.get("message_content")
            if diagnostic_content is None and isinstance(embedded_content, str):
                diagnostic_content = embedded_content
        current_content = getattr(current, "diagnostic_content", None)
        if diagnostic_content is None and isinstance(current_content, str):
            diagnostic_content = current_content
        current = current.__cause__ or current.__context__
    diagnostics.pop("message_content", None)
    diagnostics["failure_attribution"] = "unknown"
    if diagnostic_content is None:
        diagnostics["diagnostic_content"] = {
            "present": False,
            "retained": False,
            "max_utf8_bytes": LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES,
        }
        return diagnostics

    content_bytes = diagnostic_content.encode("utf-8")
    retention = {
        "present": True,
        "utf8_bytes": len(content_bytes),
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
        "max_utf8_bytes": LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES,
        "retained": False,
        "path": None,
    }
    if len(content_bytes) <= LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES:
        destination = run_root / LOCAL_DIAGNOSTIC_CONTENT_FILENAME
        try:
            destination.write_bytes(content_bytes)
        except OSError as exc:
            retention["retention_error"] = type(exc).__name__
            diagnostics["diagnostic_sufficiency"] = "insufficient"
        else:
            retention["retained"] = True
            retention["path"] = str(destination)
    else:
        diagnostics["diagnostic_sufficiency"] = "reduced"
        retention["not_retained_reason"] = "policy_limit_exceeded"
    diagnostics["diagnostic_content"] = retention
    return diagnostics


def _external_model_admission_record(
    source_disclosure: Mapping[str, Any],
) -> dict[str, Any]:
    destination = source_disclosure.get("destination")
    destination_data = destination if isinstance(destination, dict) else {}
    return {
        "provider": destination_data.get("provider"),
        "model": destination_data.get("model"),
        "model_digest": None,
        "provider_adapter": source_disclosure.get("provider_adapter"),
        "execution_locality": "external",
        "base_url": destination_data.get("base_url"),
        "destination": destination_data.get("request_url"),
        "external_disclosure_occurred": True,
        "api_key_required": True,
        "api_key_read": True,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "external_provider",
    }


def _read_ollama_model_identity(base_url: str, model: str) -> dict[str, Any]:
    normalized_base_url = validate_loopback_http_base_url(base_url)
    try:
        import httpx

        with httpx.Client(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{normalized_base_url}/api/tags")
        if response.status_code != 200:
            raise LocalEntryError(
                f"OLLAMA_MODEL_CATALOG_HTTP_{response.status_code}"
            )
        payload = response.json()
    except LocalEntryError:
        raise
    except Exception as exc:
        raise LocalEntryError(
            f"OLLAMA_MODEL_CATALOG_UNAVAILABLE:{type(exc).__name__}"
        ) from exc
    return _select_ollama_model_identity(
        payload,
        base_url=normalized_base_url,
        expected_model=model,
    )


def _read_ollama_server_version(base_url: str) -> str:
    normalized_base_url = validate_loopback_http_base_url(base_url)
    try:
        import httpx

        with httpx.Client(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{normalized_base_url}/api/version")
        if response.status_code != 200:
            raise LocalEntryError(
                f"OLLAMA_SERVER_VERSION_HTTP_{response.status_code}"
            )
        payload = response.json()
    except LocalEntryError:
        raise
    except Exception as exc:
        raise LocalEntryError(
            f"OLLAMA_SERVER_VERSION_UNAVAILABLE:{type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise LocalEntryError("OLLAMA_SERVER_VERSION_SHAPE_INVALID")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise LocalEntryError("OLLAMA_SERVER_VERSION_MISSING")
    return version


def _select_ollama_model_identity(
    payload: Any,
    *,
    base_url: str,
    expected_model: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise LocalEntryError("OLLAMA_MODEL_CATALOG_SHAPE_INVALID")
    models = payload["models"]
    if not models:
        raise LocalEntryError("OLLAMA_MODEL_LIST_EMPTY")
    matches = [
        item
        for item in models
        if isinstance(item, dict) and item.get("name") == expected_model
    ]
    if len(matches) != 1:
        raise LocalEntryError("OLLAMA_MODEL_NOT_EXACTLY_PRESENT")
    selected = matches[0]
    identity = {
        "name": selected.get("name"),
        "model": selected.get("model"),
        "digest": selected.get("digest"),
        "modified_at": selected.get("modified_at"),
        "size": selected.get("size"),
        "details": selected.get("details"),
        "capabilities": selected.get("capabilities"),
        "base_url": base_url,
    }
    _validate_ollama_model_identity(
        identity,
        expected_base_url=base_url,
        expected_model=expected_model,
    )
    return identity


def _validate_ollama_model_identity(
    identity: Mapping[str, Any],
    *,
    expected_base_url: str,
    expected_model: str,
) -> None:
    if identity.get("name") != expected_model:
        raise LocalEntryError("OLLAMA_MODEL_NAME_MISMATCH")
    if identity.get("model") != expected_model:
        raise LocalEntryError("OLLAMA_MODEL_IDENTITY_MISMATCH")
    if identity.get("base_url") != expected_base_url:
        raise LocalEntryError("OLLAMA_MODEL_BASE_URL_MISMATCH")
    digest = identity.get("digest")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise LocalEntryError("OLLAMA_MODEL_DIGEST_INVALID")
    if not isinstance(identity.get("details"), dict):
        raise LocalEntryError("OLLAMA_MODEL_DETAILS_INVALID")
    capabilities = identity.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise LocalEntryError("OLLAMA_MODEL_CAPABILITIES_INVALID")


def _validate_ollama_context_window(
    identity: Mapping[str, Any],
    *,
    requested_context_window: int | None,
) -> int:
    if (
        requested_context_window is None
        or isinstance(requested_context_window, bool)
        or not isinstance(requested_context_window, int)
        or requested_context_window <= 0
    ):
        raise LocalEntryError("OLLAMA_CONTEXT_WINDOW_INVALID")
    details = identity.get("details")
    context_limit = (
        details.get("context_length") if isinstance(details, Mapping) else None
    )
    if (
        isinstance(context_limit, bool)
        or not isinstance(context_limit, int)
        or context_limit <= 0
    ):
        raise LocalEntryError("OLLAMA_MODEL_CONTEXT_LENGTH_INVALID")
    if requested_context_window > context_limit:
        raise LocalEntryError("OLLAMA_CONTEXT_WINDOW_EXCEEDS_MODEL_LIMIT")
    return context_limit


def _assert_ollama_model_identity_stable(
    *,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> None:
    if expected.get("name") != observed.get("name"):
        raise LocalEntryError("OLLAMA_MODEL_NAME_DRIFT")
    if expected.get("digest") != observed.get("digest"):
        raise LocalEntryError("OLLAMA_MODEL_DIGEST_DRIFT")


def _verify_source_disclosure(
    record: dict[str, Any],
    *,
    requested_data_classes: tuple[str, ...],
) -> None:
    if record.get("approved") is not True:
        raise LocalEntryError("Source disclosure is not explicitly approved.")
    approved = record.get("approved_data_classes")
    if not isinstance(approved, list):
        raise LocalEntryError("Source disclosure approved_data_classes is missing.")
    unapproved = sorted(set(requested_data_classes) - {str(item) for item in approved})
    if unapproved:
        raise LocalEntryError(
            "Source disclosure does not approve requested data classes: "
            + ", ".join(unapproved)
        )


def _resolve_project_path_property(project_file: Path, *, property_name: str) -> Path:
    value = Path(
        _project_text_property(project_file, property_name=property_name).replace(
            "\\", os.sep
        )
    )
    return value.resolve() if value.is_absolute() else (project_file.parent / value).resolve()


def _project_text_property(project_file: Path, *, property_name: str) -> str:
    root = ET.parse(project_file).getroot()
    values = [
        item.text.strip()
        for item in root.iter(property_name)
        if isinstance(item.text, str) and item.text.strip()
    ]
    if not values:
        raise LocalEntryError(f"Project file does not define {property_name}.")
    if len(values) != 1:
        raise LocalEntryError(
            f"Project file must define exactly one non-empty {property_name}."
        )
    return values[0]


def _sanitized_endpoint_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    parsed = urlsplit(base_url)
    if not parsed.scheme or parsed.hostname is None:
        raise LocalEntryError("Configured LLM base_url is not a valid absolute URL.")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    try:
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    except ValueError as exc:
        raise LocalEntryError("Configured LLM base_url has an invalid port.") from exc
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)
