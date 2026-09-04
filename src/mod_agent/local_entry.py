"""Minimal local product entry that assembles the existing controlled graph."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import ntpath
import os
import re
import shutil
import stat as stat_module
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from langgraph.types import Command

from src.core.settings import load_settings
from src.libs.llm import (
    ChatResponse,
    LLMFactory,
    Message,
    OllamaLLM,
    validate_loopback_http_base_url,
)
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.artifacts.store import ArtifactWriteResult
from src.mod_agent.build import (
    BuildAdapter,
    BuildCommandResult,
    BuildProfile,
    BuildResult,
)
from src.mod_agent.evidence import (
    RgLiveEvidenceProvider,
    make_requirement_coverage_evidence_provider,
)
from src.mod_agent.evidence.rg_live import _csharp_method_source_spans
from src.mod_agent.edit_authority_capabilities import (
    EditAuthorityCapabilityDeclaration,
    EditAuthorityReviewResultV1,
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
from src.mod_agent.git.admission import StrictGitAdmission
from src.mod_agent.proposal import (
    PATCH_RESPONSE_CONTRACT_ID,
    PATCH_RESPONSE_CONTRACT_VERSION,
    LLMExactPatchGenerator,
    PatchGenerationError,
)
from src.mod_agent.product_execution import (
    ProductExecutionContractError,
    ProductExecutionInputBindingV1,
    ProductExecutionRequestV1,
)
from src.mod_agent.model_admission import (
    ModelAdmissionError,
    assert_ollama_model_identity_stable as _shared_assert_ollama_model_identity_stable,
    local_model_admission_record,
    local_no_external_disclosure_record,
    read_ollama_model_identity as _shared_read_ollama_model_identity,
    read_ollama_server_version as _shared_read_ollama_server_version,
    select_ollama_model_identity as _shared_select_ollama_model_identity,
    validate_ollama_context_window as _shared_validate_ollama_context_window,
    validate_ollama_model_identity as _shared_validate_ollama_model_identity,
)
from src.mod_agent.product_executor import (
    PATCH_PROVIDER_PAYLOAD_DISCLOSURE_BINDINGS,
    SOURCE_DISCLOSURE_DATA_CLASSES,
    LocalEntryError,
    ProductExecutionAdaptersV1,
    ProductExecutionPresentationError,
    _bind_owner_validated_runtime_evidence_factory,
    _external_model_admission_record,
    _runtime_admission_record,
    _sanitized_endpoint_url,
    _source_disclosure_record,
    _verify_source_revision_binding,
    execute_product_execution,
    preflight_product_execution,
    source_snapshot as _product_source_snapshot,
    source_snapshot_sha256 as _product_source_snapshot_sha256,
)
from src.mod_agent.requirement_coverage_model import (
    parse_requirement_coverage_json_object,
    request_requirement_coverage_model,
)
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
    EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
    EVIDENCE_CONSOLIDATION_KIND,
    PREFLIGHT_RESULT_CONTRACT_VERSION,
    RUNTIME_EVIDENCE_ONLY_COMPLETION,
    RUNTIME_EXECUTION_CONTRACT_VERSION,
    RUNTIME_EXECUTION_KIND,
    RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
    RUNTIME_TERMINALIZATION_KIND,
    RUNTIME_WORKFLOW_COMPLETION,
    VERIFICATION_BUILD_CONTRACT_VERSION,
    VERIFICATION_BUILD_KIND,
    AcceptedResumeRecoveryAttemptV1,
    BuildInvocationProtocolBindingV1,
    BuildVerificationResultV1,
    EvidenceConsolidationResultV1,
    InitialAttemptV1,
    NewRuntimeResumeProtocolBindingV1,
    ObservationRetryAttemptV1,
    RuntimeExecutionOperationV1,
    RuntimeExecutionResultV1,
    RuntimeTerminalizationOperationV1,
    RuntimeTerminalizationResultV1,
    VerificationBuildOperationV1,
    VerificationCheckpointIdentityV1,
    VerificationOperationBlockerV1,
    VerificationOperationEnvelope,
    VerificationOperationPreflightResultV1,
    VerificationOperationResultV1,
    VerificationOperationSpec,
    VerificationOperationStoreReceiptV1,
    VerificationProtocolBinding,
    _ordered_store_attempt_roles,
    artifact_ref_to_dict,
    project_rejected_verification_operation_result,
    project_verification_operation,
    project_verification_operation_result,
    resolve_verification_operation,
    validate_verification_operation_envelope,
)

_request_requirement_coverage_model = request_requirement_coverage_model
_local_model_admission_record = local_model_admission_record
_local_no_external_disclosure_record = local_no_external_disclosure_record


class EditAuthorityPresentationError(LocalEntryError):
    """Carry frozen Edit Authority machine truth across presentation failure."""

    def __init__(
        self,
        message: str,
        *,
        edit_authority_review_result: EditAuthorityReviewResultV1,
        presentation_error: Mapping[str, str],
        audit_error: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.edit_authority_review_result = edit_authority_review_result
        self.presentation_error = dict(presentation_error)
        self.audit_error = dict(audit_error) if audit_error is not None else None


class VerificationOperationExecutionError(LocalEntryError):
    """Legacy compatibility error carrying the authoritative machine result."""

    def __init__(
        self,
        message: str,
        verification_operation_result: VerificationOperationResultV1,
    ) -> None:
        super().__init__(message)
        self.verification_operation_result = verification_operation_result


class VerificationOperationPresentationError(LocalEntryError):
    """Presentation failure that does not replace the machine result."""

    def __init__(
        self,
        message: str,
        verification_operation_result: VerificationOperationResultV1,
        *,
        audit_error: Mapping[str, Any],
    ) -> None:
        super().__init__(message)
        self.verification_operation_result = verification_operation_result
        self.audit_error = dict(audit_error)


def _verification_blockers(
    blockers: list[dict[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    default_stage: str,
) -> tuple[VerificationOperationBlockerV1, ...]:
    projected: list[VerificationOperationBlockerV1] = []
    for item in blockers:
        stage = str(item.get("stage") or default_stage)
        code = str(item.get("code") or "VERIFICATION_OPERATION_BLOCKED")
        message = str(item.get("message") or "Verification operation was blocked.")
        projected.append(
            VerificationOperationBlockerV1(
                stage=stage,
                code=code,
                message=message,
            )
        )
    if not projected:
        projected.append(
            VerificationOperationBlockerV1(
                stage=default_stage,
                code="VERIFICATION_OPERATION_BLOCKED",
                message="Verification operation was blocked.",
            )
        )
    return tuple(projected)


def _artifact_ref_from_projection(value: object) -> ArtifactRef | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "feature_id",
        "artifact_type",
        "path",
        "artifact_hash",
    }:
        raise LocalEntryError("Verification ArtifactRef projection fields changed.")
    values = {
        field: value[field]
        for field in ("feature_id", "artifact_type", "path", "artifact_hash")
    }
    if any(type(item) is not str or not item for item in values.values()):
        raise LocalEntryError("Verification ArtifactRef projection is invalid.")
    return ArtifactRef(**values)


def _verification_store_receipts(
    projections: tuple[tuple[str, object], ...],
) -> tuple[VerificationOperationStoreReceiptV1, ...]:
    receipts: list[VerificationOperationStoreReceiptV1] = []
    for role, projection in projections:
        if projection is None:
            continue
        if isinstance(projection, ArtifactWriteResult):
            result = projection
        elif isinstance(projection, Mapping):
            result = ArtifactWriteResult.from_dict(projection)
        else:
            raise LocalEntryError(
                "Verification Store receipt is not an ArtifactWriteResult projection."
            )
        receipts.append(
            VerificationOperationStoreReceiptV1(
                role=role,
                artifact_write_result=result,
            )
        )
    return tuple(receipts)


def _verification_preflight_result(
    *,
    envelope: VerificationOperationEnvelope | None,
    operation_kind: str | None,
    operation_contract_version: str | None,
    status: str,
    failure_stage: str | None = None,
    identity_resolution_status: str = "identity_resolved",
    blockers: tuple[VerificationOperationBlockerV1, ...] = (),
    audit_snapshot: Mapping[str, Any] | None = None,
) -> VerificationOperationPreflightResultV1:
    return VerificationOperationPreflightResultV1(
        result_contract_version=PREFLIGHT_RESULT_CONTRACT_VERSION,
        preflight_status=status,
        identity_resolution_status=identity_resolution_status,
        operation_kind=operation_kind,
        operation_contract_version=operation_contract_version,
        envelope=envelope,
        approval_identity_hash=(
            None if envelope is None else envelope.approval_identity_hash
        ),
        failure_stage=failure_stage,
        blockers=blockers,
        audit_snapshot=dict(audit_snapshot or {}),
    )


def _rejected_verification_result(
    *,
    operation_kind: str | None,
    operation_contract_version: str | None,
    approval_identity_hash: str | None,
    identity_resolution_status: str,
    failure_stage: str,
    blockers: tuple[VerificationOperationBlockerV1, ...],
    audit_snapshot: Mapping[str, Any] | None = None,
) -> VerificationOperationResultV1:
    return project_rejected_verification_operation_result(
        operation_kind=operation_kind,
        operation_contract_version=operation_contract_version,
        approval_identity_hash=approval_identity_hash,
        identity_resolution_status=identity_resolution_status,
        failure_stage=failure_stage,
        blockers=blockers,
        audit_snapshot=audit_snapshot,
    )


def _rejected_execution_result_from_preflight(
    preflight: VerificationOperationPreflightResultV1,
) -> VerificationOperationResultV1:
    """Preserve an unresolved preflight's exact identity resolution facts."""

    if (
        preflight.preflight_status != "blocked"
        or preflight.envelope is not None
        or preflight.approval_identity_hash is not None
        or preflight.identity_resolution_status
        not in {"unresolved", "declaration_resolved"}
        or preflight.failure_stage not in {"authorization", "admission"}
    ):
        raise LocalEntryError(
            "Runtime preflight rejection cannot be projected without changing facts."
        )
    return _rejected_verification_result(
        operation_kind=preflight.operation_kind,
        operation_contract_version=preflight.operation_contract_version,
        approval_identity_hash=None,
        identity_resolution_status=preflight.identity_resolution_status,
        failure_stage=preflight.failure_stage,
        blockers=preflight.blockers,
        audit_snapshot=preflight.audit_snapshot,
    )


LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES = 262_144
LOCAL_DIAGNOSTIC_CONTENT_FILENAME = "patch_generation_failure_message_content.txt"
EXACT_DIFF_REJECTION_TOKEN = "REJECTED_BY_USER"
_INITIAL_PATCH_GENERATION_CALL_BUDGET = 2
_REPAIR_PATCH_GENERATION_CALL_BUDGET = 2
OllamaModelIdentityReader = Callable[[str, str], dict[str, Any]]
OllamaServerVersionReader = Callable[[str], str]
LOCAL_OLLAMA_PATCH_PROFILE_VERSION = "local_ollama_initial_patch_profile_v1"


@dataclass(frozen=True)
class LocalOllamaInitialPatchProfileV1:
    """One explicit loopback-only model profile for exact initial Patch."""

    profile_version: Literal["local_ollama_initial_patch_profile_v1"]
    base_url: str
    model: str
    context_window: int
    output_budget: int
    timeout_seconds: float

    def __post_init__(self) -> None:
        if self.profile_version != LOCAL_OLLAMA_PATCH_PROFILE_VERSION:
            raise LocalEntryError("LOCAL_PATCH_PROFILE_VERSION_INVALID")
        try:
            normalized = validate_loopback_http_base_url(self.base_url)
        except ValueError as exc:
            raise LocalEntryError("LOCAL_PATCH_BASE_URL_INVALID") from exc
        if normalized != self.base_url:
            raise LocalEntryError("LOCAL_PATCH_BASE_URL_NOT_NORMALIZED")
        if not isinstance(self.model, str) or not self.model.strip():
            raise LocalEntryError("LOCAL_PATCH_MODEL_INVALID")
        for value, field_name in (
            (self.context_window, "CONTEXT_WINDOW"),
            (self.output_budget, "OUTPUT_BUDGET"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise LocalEntryError(f"LOCAL_PATCH_{field_name}_INVALID")
        if self.context_window <= self.output_budget:
            raise LocalEntryError("LOCAL_PATCH_CONTEXT_WINDOW_NOT_GREATER_THAN_OUTPUT")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise LocalEntryError("LOCAL_PATCH_TIMEOUT_INVALID")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_version": self.profile_version,
            "provider": "ollama",
            "execution_locality": "local",
            "base_url": self.base_url,
            "model": self.model,
            "context_window": self.context_window,
            "output_budget": self.output_budget,
            "timeout_seconds": float(self.timeout_seconds),
            "temperature": 0.0,
            "native_json_schema": True,
            "automatic_retry": False,
            "automatic_provider_fallback": False,
        }


class _PatchResponseCapturingLLM:
    def __init__(
        self,
        delegate: Any,
        response_recorder: Callable[[ChatResponse], None],
    ) -> None:
        self._delegate = delegate
        self._response_recorder = response_recorder

    def chat(self, messages: list[Message], trace: Any | None = None, **kwargs: Any):
        response = self._delegate.chat(messages, trace=trace, **kwargs)
        self._response_recorder(response)
        return response


def _local_patch_response_sidecar_path(
    artifact_root: Path,
    *,
    run_id: str,
) -> Path:
    locator = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:32]
    return artifact_root / "cr" / f"{locator}.response.txt"


def _write_local_patch_response_sidecar(
    destination: Path,
    content: str,
) -> dict[str, Any]:
    content_bytes = content.encode("utf-8")
    temporary = destination.with_name(
        f".{destination.name[:32]}.{uuid4().hex[:16]}.tmp"
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("xb") as stream:
            stream.write(content_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_bytes() != content_bytes:
                raise LocalEntryError(
                    "LOCAL_PATCH_RESPONSE_SIDECAR_CONTENT_CONFLICT"
                )
    except LocalEntryError:
        raise
    except OSError as exc:
        raise LocalEntryError("LOCAL_PATCH_RESPONSE_SIDECAR_WRITE_FAILED") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "path": str(destination),
        "output_sha256": hashlib.sha256(content_bytes).hexdigest(),
        "output_utf8_bytes": len(content_bytes),
        "encoding": "utf-8",
        "retained": True,
    }


class LocalOllamaInitialPatchAdapter:
    """Generate one native-schema Patch response with a queryable call receipt."""

    def __init__(
        self,
        *,
        profile: LocalOllamaInitialPatchProfileV1,
        artifact_store: ArtifactStore,
        identity_reader: OllamaModelIdentityReader | None = None,
        llm_factory: Callable[[LocalOllamaInitialPatchProfileV1], Any] | None = None,
    ) -> None:
        self.profile = profile
        self.artifact_store = artifact_store
        self.identity_reader = identity_reader or _read_ollama_model_identity
        self.llm_factory = llm_factory or self._default_llm
        self._attempt_recorder: Callable[[Mapping[str, Any]], None] | None = None
        self._invocation_count = 0
        self._response_sidecar_path: Path | None = None
        self._receipt: dict[str, Any] = {
            "adapter": "LocalOllamaInitialPatchAdapter",
            "profile": profile.to_dict(),
            "patch_response_contract": {
                "contract_id": PATCH_RESPONSE_CONTRACT_ID,
                "contract_version": PATCH_RESPONSE_CONTRACT_VERSION,
                "schema_sha256": None,
            },
            "status": "not_started",
            "model_call_count": 0,
            "provider_request": None,
            "model_response": None,
            "failure": None,
        }

    def bind_attempt_recorder(
        self,
        recorder: Callable[[Mapping[str, Any]], None],
    ) -> None:
        if self._invocation_count != 0 or self._attempt_recorder is not None:
            raise LocalEntryError("LOCAL_PATCH_ATTEMPT_RECORDER_ALREADY_BOUND")
        if not callable(recorder):
            raise LocalEntryError("LOCAL_PATCH_ATTEMPT_RECORDER_INVALID")
        self._attempt_recorder = recorder

    def patch_attempt_receipt(self) -> dict[str, Any]:
        return json.loads(
            json.dumps(
                self._receipt,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        )

    def __call__(
        self,
        state: dict[str, Any],
        implementation: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        if self._attempt_recorder is None:
            raise LocalEntryError("LOCAL_PATCH_ATTEMPT_RECORDER_NOT_BOUND")
        if self._invocation_count != 0:
            raise LocalEntryError("LOCAL_PATCH_MODEL_CALL_ALREADY_CONSUMED")
        self._invocation_count = 1
        started = time.perf_counter()
        try:
            identity = self.identity_reader(self.profile.base_url, self.profile.model)
            _validate_ollama_model_identity(
                identity,
                expected_base_url=self.profile.base_url,
                expected_model=self.profile.model,
            )
            model_context_limit = _validate_ollama_context_window(
                identity,
                requested_context_window=self.profile.context_window,
            )
            feature_spec = self._read_feature_spec(state)
            planned_changes = [
                dict(item)
                for item in implementation.get("proposed_changes") or []
                if isinstance(item, dict)
            ]
            obligations = _patch_generation_obligation_projection(
                feature_spec=feature_spec,
                implementation=implementation,
                planned_changes=planned_changes,
            )
            model_input = {
                "request": state["user_request"],
                "evidence": _external_evidence_items(
                    [
                        dict(item)
                        for item in evidence_pack.get("items") or []
                        if isinstance(item, dict)
                    ]
                ),
                "binding_registry": dict(
                    implementation.get("binding_registry") or {}
                ),
                "required_change_units": obligations["required_change_units"],
                "side_effect_boundaries": obligations["side_effect_boundaries"],
                "target_behavior": obligations["target_behavior"],
                "acceptance_criteria": obligations["acceptance_criteria"],
                "runtime_verification_plan": obligations[
                    "runtime_verification_plan"
                ],
            }
            _assert_no_absolute_local_paths(model_input)
            self._receipt.update(
                {
                    "status": "ready_for_provider_invocation",
                    "model_identity": dict(identity),
                    "model_context_limit": model_context_limit,
                    "model_input_sha256": _sha256_json(model_input),
                    "required_change_count": len(
                        obligations["required_change_units"]
                    ),
                }
            )
            self._emit("local_patch_model_admitted")
            run_id = state.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise LocalEntryError("LOCAL_PATCH_RUN_ID_INVALID")
            self._response_sidecar_path = _local_patch_response_sidecar_path(
                self.artifact_store.root,
                run_id=run_id,
            )
            llm = _PatchResponseCapturingLLM(
                self.llm_factory(self.profile),
                self._record_response,
            )
            generator = LLMExactPatchGenerator(llm)

            def post_response_admission(response: ChatResponse) -> None:
                if response.model != self.profile.model:
                    raise LocalEntryError("OLLAMA_RESPONSE_MODEL_IDENTITY_MISMATCH")
                observed = self.identity_reader(
                    self.profile.base_url,
                    self.profile.model,
                )
                _validate_ollama_model_identity(
                    observed,
                    expected_base_url=self.profile.base_url,
                    expected_model=self.profile.model,
                )
                _assert_ollama_model_identity_stable(
                    expected=identity,
                    observed=observed,
                )
                _validate_ollama_context_window(
                    observed,
                    requested_context_window=self.profile.context_window,
                )
                self._receipt["post_response_model_identity"] = dict(observed)
                self._emit("local_patch_post_response_model_admitted")

            generated = generator.generate(
                user_request=str(model_input["request"]),
                evidence_items=list(model_input["evidence"]),
                binding_registry=dict(model_input["binding_registry"]),
                constraints=list(model_input["side_effect_boundaries"]),
                target_behavior=str(model_input["target_behavior"]),
                acceptance_criteria=list(model_input["acceptance_criteria"]),
                runtime_verification_plan=list(
                    model_input["runtime_verification_plan"]
                ),
                required_change_units=list(model_input["required_change_units"]),
                required_validation_by_binding={
                    str(item["edit_binding_id"]): list(
                        item["expected_validation"]
                    )
                    for item in model_input["required_change_units"]
                },
                require_native_schema=True,
                provider_request_recorder=self._record_provider_request,
                post_response_admission=post_response_admission,
            )
            overlaid = _overlay_generated_patch_changes_on_plan(
                planned_changes=planned_changes,
                generated_changes=generated.changes,
            )
            changes = tuple(
                {
                    **change,
                    "generation": {
                        "provider": "ollama",
                        "model": generated.model,
                        "model_digest": identity["digest"],
                        "usage": generated.usage,
                        "profile_version": self.profile.profile_version,
                        "patch_response_contract": dict(
                            self._receipt["patch_response_contract"]
                        ),
                        "model_input_sha256": self._receipt[
                            "model_input_sha256"
                        ],
                        "model_response_sha256": self._receipt[
                            "model_response"
                        ]["output_sha256"],
                    },
                }
                for change in overlaid
            )
            self._receipt.update(
                {
                    "status": "completed",
                    "duration_seconds": time.perf_counter() - started,
                    "generated_changes_sha256": _sha256_json(changes),
                    "generated_change_count": len(changes),
                }
            )
            self._emit("local_patch_generation_completed")
            return changes
        except Exception as exc:
            self._receipt.update(
                {
                    "status": "failed",
                    "duration_seconds": time.perf_counter() - started,
                    "failure": _local_patch_failure_receipt(exc),
                }
            )
            self._emit("local_patch_generation_failed")
            raise

    def _read_feature_spec(self, state: Mapping[str, Any]) -> dict[str, Any]:
        artifacts = state.get("artifacts")
        hashes = state.get("artifact_hashes")
        feature_id = state.get("feature_id")
        if not isinstance(artifacts, Mapping) or not isinstance(hashes, Mapping):
            raise LocalEntryError("LOCAL_PATCH_FEATURE_SPEC_REF_MISSING")
        path = artifacts.get("feature_spec")
        artifact_hash = hashes.get("feature_spec")
        if not all(isinstance(value, str) and value for value in (feature_id, path, artifact_hash)):
            raise LocalEntryError("LOCAL_PATCH_FEATURE_SPEC_REF_MISSING")
        return self.artifact_store.read(
            ArtifactRef(
                feature_id=str(feature_id),
                artifact_type="feature_spec",
                path=str(path),
                artifact_hash=str(artifact_hash),
            )
        )["data"]

    def _record_provider_request(self, provider_request: dict[str, Any]) -> None:
        if self._receipt["model_call_count"] != 0:
            raise LocalEntryError("LOCAL_PATCH_MODEL_CALL_COUNT_EXCEEDED")
        self._receipt["model_call_count"] = 1
        self._receipt["status"] = "provider_invocation_recorded"
        self._receipt["provider_request"] = {
            key: provider_request.get(key)
            for key in (
                "method",
                "destination",
                "body_sha256",
                "body_size_bytes",
                "timeout_seconds",
                "trust_environment",
                "follow_redirects",
                "context_admission",
                "model",
                "output_budget",
                "context_window",
                "temperature",
                "messages_sha256",
                "response_format_sha256",
            )
        }
        self._receipt["patch_response_contract"]["schema_sha256"] = (
            provider_request.get("response_format_sha256")
        )
        self._emit("local_patch_provider_invocation_recorded")

    def _record_response(self, response: ChatResponse) -> None:
        if self._response_sidecar_path is None:
            raise LocalEntryError("LOCAL_PATCH_RESPONSE_SIDECAR_PATH_MISSING")
        sidecar = _write_local_patch_response_sidecar(
            self._response_sidecar_path,
            response.content,
        )
        raw = response.raw_response if isinstance(response.raw_response, Mapping) else {}
        self._receipt["model_response"] = {
            "model": response.model,
            **sidecar,
            "usage": response.usage,
            "done": raw.get("done"),
            "done_reason": raw.get("done_reason"),
        }
        self._receipt["status"] = "model_response_persisted"
        self._emit("local_patch_model_response_persisted")

    def _emit(self, phase: str) -> None:
        if self._attempt_recorder is None:
            raise LocalEntryError("LOCAL_PATCH_ATTEMPT_RECORDER_NOT_BOUND")
        self._attempt_recorder(
            {
                "phase": phase,
                "factory_receipt": self.patch_attempt_receipt(),
                "model_call_count": self._receipt["model_call_count"],
            }
        )

    @staticmethod
    def _default_llm(profile: LocalOllamaInitialPatchProfileV1) -> OllamaLLM:
        settings = SimpleNamespace(
            llm=SimpleNamespace(
                model=profile.model,
                temperature=0.0,
                max_tokens=profile.output_budget,
            )
        )
        return OllamaLLM(
            settings,
            base_url=profile.base_url,
            timeout=float(profile.timeout_seconds),
            context_window=profile.context_window,
        )


def _local_patch_failure_receipt(exc: BaseException) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        current_diagnostics = getattr(current, "diagnostics", None)
        if isinstance(current_diagnostics, Mapping):
            diagnostics.update(dict(current_diagnostics))
        current = current.__cause__ or current.__context__
    message_content = diagnostics.pop("message_content", None)
    if isinstance(message_content, str):
        encoded = message_content.encode("utf-8")
        diagnostics["model_output"] = {
            "present": True,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "utf8_bytes": len(encoded),
        }
    return {
        "failure_class": type(exc).__name__,
        "failure_code": str(getattr(exc, "code", type(exc).__name__)),
        "message": str(exc),
        "diagnostics": diagnostics,
    }


def make_exact_no_write_dry_run_factory(
    workspace_root: str | Path,
) -> Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]:
    """Bind the existing exact-text applier to one no-write workspace."""

    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise LocalEntryError("LOCAL_PATCH_WORKSPACE_ROOT_INVALID")
    applier = ExactTextPatchApplier()

    def dry_run(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        return applier.run(
            workspace_root=root,
            proposal=proposal,
            implementation_plan=implementation,
            review=review,
            allow_write=False,
        )

    return dry_run


_LOCAL_PATCH_FROZEN_RESUME_IDENTITY_FIELDS = frozenset(
    {
        "run_id",
        "request_id",
        "feature_id",
        "model_role",
        "role_ordinal",
        "model_call_ordinal",
        "remaining_call_budget",
        "frozen_attempt_call_budget",
        "model",
        "output_budget",
        "context_window",
        "model_context_limit",
        "ollama_server_version",
        "model_identity",
        "source_revision_binding",
        "source_snapshot_sha256",
        "request_sha256",
        "model_input_payload_sha256",
        "artifact_bindings",
        "binding_registry_sha256",
        "evidence_sha256",
        "editable_paths",
        "change_scope",
    }
)


def _build_local_patch_frozen_resume_identity(
    *,
    run_id: str,
    request_id: str,
    feature_id: str,
    model_role: str,
    model_call_count: int,
    initial_patch_call_count: int,
    repair_call_count: int,
    model: str,
    output_budget: int,
    context_window: int,
    model_context_limit: int,
    ollama_server_version: str,
    model_identity: Mapping[str, Any],
    source_revision_binding: Mapping[str, Any],
    source_snapshot_sha256: str,
    request_sha256: str,
    model_input_payload_sha256: str,
    feature_spec_ref: str,
    feature_spec_hash: str,
    evidence_pack_ref: str,
    evidence_pack_hash: str,
    implementation_plan_ref: str,
    implementation_plan_hash: str,
    repair_plan_ref: str | None,
    repair_plan_hash: str | None,
    build_result_ref: str | None,
    build_result_hash: str | None,
    binding_registry_sha256: str,
    evidence_sha256: str,
    editable_paths: list[str],
    change_scope: list[str],
) -> dict[str, Any]:
    """Freeze the exact current owners needed for one Patch resume."""

    remaining_call_budget = _patch_generation_calls_remaining(
        model_role,
        initial_patch_call_count=initial_patch_call_count,
        repair_call_count=repair_call_count,
    )
    if model_role == "initial_patch":
        role_ordinal = initial_patch_call_count + 1
    elif model_role == "repair":
        role_ordinal = repair_call_count + 1
    else:
        raise LocalEntryError("LOCAL_PATCH_GENERATION_MODEL_ROLE_INVALID")
    identity = {
        "run_id": run_id,
        "request_id": request_id,
        "feature_id": feature_id,
        "model_role": model_role,
        "role_ordinal": role_ordinal,
        "model_call_ordinal": model_call_count + 1,
        "remaining_call_budget": remaining_call_budget,
        "frozen_attempt_call_budget": 1,
        "model": model,
        "output_budget": output_budget,
        "context_window": context_window,
        "model_context_limit": model_context_limit,
        "ollama_server_version": ollama_server_version,
        "model_identity": dict(model_identity),
        "source_revision_binding": dict(source_revision_binding),
        "source_snapshot_sha256": source_snapshot_sha256,
        "request_sha256": request_sha256,
        "model_input_payload_sha256": model_input_payload_sha256,
        "artifact_bindings": {
            "feature_spec_ref": feature_spec_ref,
            "feature_spec_hash": feature_spec_hash,
            "evidence_pack_ref": evidence_pack_ref,
            "evidence_pack_hash": evidence_pack_hash,
            "implementation_plan_ref": implementation_plan_ref,
            "implementation_plan_hash": implementation_plan_hash,
            "repair_plan_ref": repair_plan_ref,
            "repair_plan_hash": repair_plan_hash,
            "build_result_ref": build_result_ref,
            "build_result_hash": build_result_hash,
        },
        "binding_registry_sha256": binding_registry_sha256,
        "evidence_sha256": evidence_sha256,
        "editable_paths": list(editable_paths),
        "change_scope": list(change_scope),
    }
    if set(identity) != _LOCAL_PATCH_FROZEN_RESUME_IDENTITY_FIELDS:
        raise LocalEntryError("LOCAL_PATCH_FROZEN_RESUME_IDENTITY_FIELDS_INVALID")
    for field_name in (
        "run_id",
        "request_id",
        "feature_id",
        "model",
        "ollama_server_version",
        "source_snapshot_sha256",
        "request_sha256",
        "model_input_payload_sha256",
        "binding_registry_sha256",
        "evidence_sha256",
    ):
        value = identity[field_name]
        if not isinstance(value, str) or not value.strip():
            raise LocalEntryError(
                f"LOCAL_PATCH_FROZEN_RESUME_{field_name.upper()}_INVALID"
            )
    if model_role not in {"initial_patch", "repair"}:
        raise LocalEntryError("LOCAL_PATCH_GENERATION_MODEL_ROLE_INVALID")
    for field_name in (
        "role_ordinal",
        "model_call_ordinal",
        "remaining_call_budget",
        "output_budget",
        "context_window",
        "model_context_limit",
    ):
        value = identity[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise LocalEntryError(
                f"LOCAL_PATCH_FROZEN_RESUME_{field_name.upper()}_INVALID"
            )
    if not identity["model_identity"] or not identity["source_revision_binding"]:
        raise LocalEntryError("LOCAL_PATCH_FROZEN_RESUME_OWNER_BINDING_INVALID")
    artifact_bindings = identity["artifact_bindings"]
    for field_name in (
        "feature_spec_ref",
        "feature_spec_hash",
        "evidence_pack_ref",
        "evidence_pack_hash",
        "implementation_plan_ref",
        "implementation_plan_hash",
    ):
        value = artifact_bindings[field_name]
        if not isinstance(value, str) or not value.strip():
            raise LocalEntryError(
                f"LOCAL_PATCH_FROZEN_RESUME_{field_name.upper()}_INVALID"
            )
    for ref_field, hash_field in (
        ("repair_plan_ref", "repair_plan_hash"),
        ("build_result_ref", "build_result_hash"),
    ):
        ref_value = artifact_bindings[ref_field]
        hash_value = artifact_bindings[hash_field]
        if (ref_value is None) != (hash_value is None):
            raise LocalEntryError(
                "LOCAL_PATCH_FROZEN_RESUME_OPTIONAL_ARTIFACT_IDENTITY_INVALID"
            )
        if ref_value is not None and (
            not isinstance(ref_value, str)
            or not ref_value.strip()
            or not isinstance(hash_value, str)
            or not hash_value.strip()
        ):
            raise LocalEntryError(
                "LOCAL_PATCH_FROZEN_RESUME_OPTIONAL_ARTIFACT_IDENTITY_INVALID"
            )
    if not identity["editable_paths"] or not all(
        isinstance(item, str) and item.strip()
        for field_name in ("editable_paths", "change_scope")
        for item in identity[field_name]
    ):
        raise LocalEntryError("LOCAL_PATCH_FROZEN_RESUME_SCOPE_INVALID")
    return identity


def _atomic_write_frozen_patch_attempt(
    destination: Path,
    attempt: Mapping[str, Any],
) -> None:
    """Atomically replace and fully read back one run-local frozen attempt."""

    destination = destination.resolve()
    if not destination.parent.is_dir():
        raise LocalEntryError("Frozen Patch attempt directory is missing.")
    payload = (
        json.dumps(
            dict(attempt),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    temporary = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )
    replaced = False
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        replaced = True
        if destination.read_bytes() != payload:
            raise LocalEntryError("Frozen Patch attempt readback mismatch.")
        loaded = _strict_frozen_patch_attempt_json(payload.decode("utf-8"))
        if loaded != dict(attempt):
            raise LocalEntryError("Frozen Patch attempt JSON readback mismatch.")
    except Exception:
        if temporary.exists():
            temporary.unlink()
        if replaced and destination.exists():
            destination.unlink()
        raise


def _strict_frozen_patch_attempt_json(text: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_nonstandard_number(value: str) -> Any:
        raise ValueError(f"non-standard JSON number: {value}")

    return json.loads(
        text,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonstandard_number,
    )


def _read_frozen_patch_attempt(source: Path) -> dict[str, Any]:
    try:
        raw = source.read_bytes()
        loaded = _strict_frozen_patch_attempt_json(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LocalEntryError(
            f"Frozen Patch attempt cannot be read exactly: {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise LocalEntryError("Frozen Patch attempt root must be an object.")
    return loaded


def _prepare_local_frozen_patch_attempt(
    *,
    generator: LLMExactPatchGenerator,
    destination: Path,
    resume_identity: Mapping[str, Any],
    generation_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Create one run-local paused Patch attempt without invoking HTTP."""

    claim_path = destination.with_name(f"{destination.name}.resume.claim")
    if destination.exists() or claim_path.exists():
        raise LocalEntryError("Frozen Patch attempt already exists.")
    if set(resume_identity) != _LOCAL_PATCH_FROZEN_RESUME_IDENTITY_FIELDS:
        raise LocalEntryError("LOCAL_PATCH_FROZEN_RESUME_IDENTITY_FIELDS_INVALID")
    return generator.prepare_frozen_native(
        resume_identity=resume_identity,
        frozen_attempt_recorder=lambda value: _atomic_write_frozen_patch_attempt(
            destination,
            value,
        ),
        **dict(generation_inputs),
    )


def _claim_local_frozen_patch_resume(
    *,
    source: Path,
    current_resume_identity: Mapping[str, Any],
) -> Path:
    """Acquire the attempt's single-machine filesystem consumption right."""

    claim_path = source.with_name(f"{source.name}.resume.claim")
    claim = {
        "schema_version": "frozen_native_patch_resume_claim_v1",
        "source_name": source.name,
        "resume_identity_sha256": _sha256_json(dict(current_resume_identity)),
        "consumed_once": True,
    }
    payload = (
        json.dumps(claim, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with claim_path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise LocalEntryError(
            "LOCAL_PATCH_FROZEN_ATTEMPT_CONSUMED_OR_IN_PROGRESS"
        ) from exc
    if claim_path.read_bytes() != payload:
        raise LocalEntryError("Frozen Patch resume claim readback mismatch.")
    return claim_path


def _resume_local_frozen_patch_attempt(
    *,
    generator: LLMExactPatchGenerator,
    source: Path,
    current_resume_identity: Mapping[str, Any],
    post_response_admission: Callable[[ChatResponse], None] | None = None,
) -> Any:
    """Resume one run-local frozen attempt through a single provider send."""

    if set(current_resume_identity) != _LOCAL_PATCH_FROZEN_RESUME_IDENTITY_FIELDS:
        raise LocalEntryError("LOCAL_PATCH_FROZEN_RESUME_IDENTITY_FIELDS_INVALID")
    generator.validate_frozen_native(
        _read_frozen_patch_attempt(source),
        current_resume_identity=current_resume_identity,
    )
    _claim_local_frozen_patch_resume(
        source=source,
        current_resume_identity=current_resume_identity,
    )
    revalidated_attempt = generator.validate_frozen_native(
        _read_frozen_patch_attempt(source),
        current_resume_identity=current_resume_identity,
    )
    return generator.resume_frozen_native(
        frozen_attempt_loader=lambda: revalidated_attempt,
        frozen_attempt_recorder=lambda value: _atomic_write_frozen_patch_attempt(
            source,
            value,
        ),
        current_resume_identity=current_resume_identity,
        post_response_admission=post_response_admission,
    )


def _patch_generation_calls_remaining(
    model_role: str,
    *,
    initial_patch_call_count: int,
    repair_call_count: int,
) -> int:
    """Return the current role's bounded provider calls before this invocation."""

    if initial_patch_call_count < 0 or repair_call_count < 0:
        raise LocalEntryError("LOCAL_PATCH_GENERATION_CALL_COUNT_INVALID")
    if model_role == "initial_patch":
        remaining = _INITIAL_PATCH_GENERATION_CALL_BUDGET - initial_patch_call_count
    elif model_role == "repair":
        remaining = _REPAIR_PATCH_GENERATION_CALL_BUDGET - repair_call_count
    else:
        raise LocalEntryError("LOCAL_PATCH_GENERATION_MODEL_ROLE_INVALID")
    if remaining <= 0:
        raise LocalEntryError("LOCAL_PATCH_GENERATION_CALL_BUDGET_EXHAUSTED")
    return remaining


def _local_patch_generation_correction_allowed(
    model_role: str,
    *,
    initial_patch_call_count: int,
) -> bool:
    """Reserve one local provider call for each bounded RepairPlan attempt."""

    return (
        model_role == "initial_patch"
        and initial_patch_call_count < _INITIAL_PATCH_GENERATION_CALL_BUDGET
    )


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
    machine_projection = result.get("edit_authority_review_result")
    if not isinstance(machine_projection, Mapping):
        raise LocalEntryError(
            "Edit Authority graph omitted its structured machine result."
        )
    try:
        machine_result = EditAuthorityReviewResultV1.from_dict(
            machine_projection,
            capability=admission.capability,
            feature_id=feature_id,
            approval_identity_hash=authority_request_hash,
        )
    except ValueError as exc:
        raise LocalEntryError(
            f"Edit Authority graph result is invalid: {exc}"
        ) from exc
    try:
        after_counts = {
            artifact_type: len(
                admission.store.list_feature_artifact_revisions(
                    feature_id,
                    artifact_type,
                )
            )
            for artifact_type in write_types
        }
    except Exception as exc:
        error_projection = {
            "error_class": type(exc).__name__,
            "error_message": str(exc),
        }
        raise EditAuthorityPresentationError(
            "Edit Authority audit projection failed after machine result.",
            edit_authority_review_result=machine_result,
            presentation_error=error_projection,
            audit_error=error_projection,
        ) from exc
    writes_performed = machine_result.artifact_store_commit_started
    capability_succeeded = (
        machine_result.platform_status == "completed"
        and machine_result.review_outcome == "approved"
        and machine_result.materialization_status == "completed"
    )
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
        "edit_authority_review_result": machine_result.to_dict(),
        "audit_snapshot": {
            "artifact_revision_counts_before": before_counts,
            "artifact_revision_counts_after": after_counts,
            "writes_performed": writes_performed,
            "artifact_writes_performed": (
                machine_result.artifact_store_writes_committed
            ),
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
    attempt_policy: InitialAttemptV1 | ObservationRetryAttemptV1 | AcceptedResumeRecoveryAttemptV1 = field(
        default_factory=InitialAttemptV1
    )
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
class RunLocalGameFolderBindingV1:
    """Exact read-only GameFolder dependency identity for one local run."""

    source_root: str
    snapshot_sha256: str
    file_count: int
    property_name: Literal["GameFolder"] = "GameFolder"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_root, str)
            or not self.source_root
            or not isinstance(self.snapshot_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256) is None
            or isinstance(self.file_count, bool)
            or not isinstance(self.file_count, int)
            or self.file_count <= 0
            or self.property_name != "GameFolder"
        ):
            raise ValueError("Run-local GameFolder binding is invalid.")

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_version": "run_local_game_folder_binding_v1",
            "source_root": self.source_root,
            "snapshot_sha256": self.snapshot_sha256,
            "file_count": self.file_count,
            "property_name": self.property_name,
        }


@dataclass(frozen=True)
class _RunLocalGameFolderSourceIdentity:
    source_root: Path
    snapshot: tuple[dict[str, object], ...]
    snapshot_sha256: str
    file_count: int


def _binary_tree_snapshot(root: Path) -> tuple[dict[str, object], ...]:
    selected_root = root.resolve(strict=True)
    walk_root = _directory_copy_path_argument(
        selected_root,
        windows=os.name == "nt",
    )
    records: list[dict[str, object]] = []

    def fail_walk(error: OSError) -> None:
        raise LocalEntryError(
            "GameFolder dependency snapshot traversal failed."
        ) from error

    def require_plain_entry(
        path_text: str | os.PathLike[str],
        *,
        directory: bool,
    ) -> os.stat_result:
        try:
            entry_stat = os.lstat(path_text)
        except OSError as exc:
            raise LocalEntryError(
                "GameFolder dependency snapshot entry could not be inspected."
            ) from exc
        reparse_mask = getattr(
            stat_module,
            "FILE_ATTRIBUTE_REPARSE_POINT",
            0x400,
        )
        if stat_module.S_ISLNK(entry_stat.st_mode) or bool(
            getattr(entry_stat, "st_file_attributes", 0) & reparse_mask
        ):
            raise LocalEntryError(
                "GameFolder dependency snapshot rejects symlink or reparse entries."
            )
        expected = (
            stat_module.S_ISDIR(entry_stat.st_mode)
            if directory
            else stat_module.S_ISREG(entry_stat.st_mode)
        )
        if not expected:
            raise LocalEntryError(
                "GameFolder dependency snapshot rejects non-regular entries."
            )
        return entry_stat

    for current_root, directory_names, file_names in os.walk(
        walk_root,
        topdown=True,
        onerror=fail_walk,
        followlinks=False,
    ):
        directory_names.sort(key=lambda name: name.encode("utf-8"))
        file_names.sort(key=lambda name: name.encode("utf-8"))
        for directory_name in directory_names:
            require_plain_entry(
                os.path.join(current_root, directory_name),
                directory=True,
            )
        for file_name in file_names:
            file_path = os.path.join(current_root, file_name)
            entry_stat = require_plain_entry(file_path, directory=False)
            relative_path = Path(os.path.relpath(file_path, walk_root)).as_posix()
            if relative_path in ("", ".") or relative_path.startswith("../"):
                raise LocalEntryError(
                    "GameFolder dependency snapshot relative path escaped its root."
                )
            digest = hashlib.sha256()
            try:
                with open(file_path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError as exc:
                raise LocalEntryError(
                    "GameFolder dependency snapshot file could not be read."
                ) from exc
            records.append(
                {
                    "path": relative_path,
                    "sha256": digest.hexdigest(),
                    "size": entry_stat.st_size,
                }
            )
    return tuple(
        sorted(records, key=lambda item: str(item["path"]).encode("utf-8"))
    )


def _binary_tree_snapshot_sha256(snapshot: tuple[dict[str, object], ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            list(snapshot),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _windows_extended_length_path(path_text: str) -> str:
    """Project one validated absolute Windows path into Win32 long-path form."""

    normalized = ntpath.normpath(path_text)
    if normalized.startswith("\\\\?\\"):
        return normalized
    if normalized.startswith("\\\\.\\") or not ntpath.isabs(normalized):
        raise LocalEntryError(
            "Extended-length copy paths must be absolute filesystem paths."
        )
    if normalized.startswith("\\\\"):
        return "\\\\?\\UNC\\" + normalized[2:]
    drive, tail = ntpath.splitdrive(normalized)
    if re.fullmatch(r"[A-Za-z]:", drive) is None or not tail.startswith("\\"):
        raise LocalEntryError(
            "Extended-length copy paths must use an absolute drive or UNC root."
        )
    return "\\\\?\\" + normalized


def _directory_copy_path_argument(
    path: Path,
    *,
    windows: bool,
) -> Path | str:
    if not windows:
        return path
    return _windows_extended_length_path(str(path))


def _copy_validated_directory_tree(*, source: Path, destination: Path) -> None:
    """Copy roots whose identity and containment were already validated."""

    windows = os.name == "nt"
    shutil.copytree(
        _directory_copy_path_argument(source, windows=windows),
        _directory_copy_path_argument(destination, windows=windows),
        copy_function=shutil.copy2,
    )


def _validate_game_folder_build_binding(
    binding: RunLocalGameFolderBindingV1,
    *,
    canonical_source_root: Path,
) -> _RunLocalGameFolderSourceIdentity:
    source = Path(binding.source_root)
    if not source.is_absolute():
        raise LocalEntryError("GameFolder dependency source_root must be absolute.")
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise LocalEntryError("GameFolder dependency source_root is missing.")
    canonical = canonical_source_root.resolve(strict=True)
    try:
        source.relative_to(canonical)
    except ValueError:
        pass
    else:
        raise LocalEntryError(
            "GameFolder dependency source cannot be inside canonical product source."
        )
    try:
        canonical.relative_to(source)
    except ValueError:
        pass
    else:
        raise LocalEntryError(
            "GameFolder dependency source cannot contain canonical product source."
        )
    snapshot = _binary_tree_snapshot(source)
    observed_hash = _binary_tree_snapshot_sha256(snapshot)
    if len(snapshot) != binding.file_count:
        raise LocalEntryError("GameFolder dependency file count drifted.")
    if observed_hash != binding.snapshot_sha256:
        raise LocalEntryError("GameFolder dependency snapshot SHA256 drifted.")
    return _RunLocalGameFolderSourceIdentity(
        source_root=source,
        snapshot=snapshot,
        snapshot_sha256=observed_hash,
        file_count=len(snapshot),
    )


def _materialize_game_folder_build_dependency(
    identity: _RunLocalGameFolderSourceIdentity,
    *,
    run_root: Path,
) -> dict[str, object]:
    root = run_root.resolve(strict=True)
    destination = root / "build_dependencies" / "GameFolder"
    _require_run_local_build_path(
        root=root,
        path=destination,
        label="game_folder_dir",
    )
    if destination.exists():
        raise LocalEntryError("Run-local GameFolder dependency destination already exists.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_validated_directory_tree(
        source=identity.source_root,
        destination=destination,
    )
    copied_snapshot = _binary_tree_snapshot(destination)
    copied_hash = _binary_tree_snapshot_sha256(copied_snapshot)
    source_after_copy = _binary_tree_snapshot(identity.source_root)
    if source_after_copy != identity.snapshot:
        raise LocalEntryError("GameFolder dependency source changed during copy.")
    if copied_snapshot != identity.snapshot or copied_hash != identity.snapshot_sha256:
        raise LocalEntryError("Run-local GameFolder dependency copy identity drifted.")
    return {
        "binding_version": "run_local_game_folder_binding_v1",
        "property_name": "GameFolder",
        "source_root": str(identity.source_root),
        "source_snapshot_sha256": identity.snapshot_sha256,
        "source_file_count": identity.file_count,
        "isolated_copy": str(destination),
        "copy_snapshot_sha256": copied_hash,
        "copy_file_count": len(copied_snapshot),
        "build_uses_isolated_copy": True,
    }


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
    bepinex_dir: Path | None
    game_folder_dir: Path | None
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
            "bepinex_dir": (
                str(self.bepinex_dir) if self.bepinex_dir is not None else None
            ),
            "game_folder_dir": (
                str(self.game_folder_dir)
                if self.game_folder_dir is not None
                else None
            ),
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
    bepinex_dir: Path | None,
    timeout_seconds: int,
    game_folder_dir: Path | None = None,
) -> NuGetIsolatedBuildProfile:
    root = run_root.resolve()
    working = working_directory.resolve()
    config = config_file.resolve()
    bepinex = bepinex_dir.resolve() if bepinex_dir is not None else None
    game_folder = (
        game_folder_dir.resolve() if game_folder_dir is not None else None
    )
    for label, path in (
        ("working_directory", working),
        ("config_file", config),
    ):
        _require_run_local_build_path(root=root, path=path, label=label)
    if bepinex is not None:
        _require_run_local_build_path(
            root=root,
            path=bepinex,
            label="bepinex_dir",
        )
    if game_folder is not None:
        _require_run_local_build_path(
            root=root,
            path=game_folder,
            label="game_folder_dir",
        )
    if not working.is_dir():
        raise LocalEntryError("NuGet-isolated build working directory is missing.")
    if not config.is_file():
        raise LocalEntryError("NuGet-isolated build config file is missing.")
    if bepinex is not None and not bepinex.is_dir():
        raise LocalEntryError("NuGet-isolated build BepInEx directory is missing.")
    if game_folder is not None and not game_folder.is_dir():
        raise LocalEntryError("NuGet-isolated build GameFolder directory is missing.")
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
    bepinex_arguments = (
        (f"-p:BepInExDir={bepinex}",) if bepinex is not None else ()
    )
    game_folder_arguments = (
        (f"-p:GameFolder={game_folder}",) if game_folder is not None else ()
    )
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
        game_folder_dir=game_folder,
        timeout_seconds=timeout_seconds,
        restore_command=(
            "dotnet",
            "restore",
            "--configfile",
            str(config),
            "--packages",
            str(packages),
            *bepinex_arguments,
            *game_folder_arguments,
        ),
        build_command=(
            "dotnet",
            "build",
            "--no-restore",
            *bepinex_arguments,
            *game_folder_arguments,
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


def _run_nuget_isolated_verification_command(
    profile: NuGetIsolatedBuildProfile,
    command: tuple[str, ...],
    *,
    command_runner: Callable[..., Any] = subprocess.run,
) -> BuildCommandResult:
    if not command or not all(
        isinstance(part, str) and part for part in command
    ):
        raise LocalEntryError(
            "Run-local objective verification command must contain non-empty strings."
        )
    environment = os.environ.copy()
    environment.update(profile.environment)
    started = time.perf_counter()
    completed = command_runner(
        command,
        cwd=profile.working_directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=profile.timeout_seconds,
        check=False,
        env=environment,
    )
    return BuildCommandResult(
        exit_code=int(completed.returncode),
        stdout=str(completed.stdout or ""),
        stderr=str(completed.stderr or ""),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _bind_objective_failure_to_single_changed_file(
    result: BuildCommandResult,
    changed_files: tuple[str, ...],
) -> BuildCommandResult:
    if result.exit_code == 0 or len(changed_files) != 1:
        return result
    changed_file = changed_files[0]
    observed = "\n".join(
        value.strip()
        for value in (result.stdout, result.stderr)
        if value.strip()
    )
    diagnostic = (
        f"{changed_file}(1,1): error IA0001: "
        f"Objective verification failed with exit code {result.exit_code}."
    )
    if observed:
        diagnostic += f" Observation: {observed}"
    return BuildCommandResult(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=diagnostic,
        duration_ms=result.duration_ms,
    )


def _canonicalize_run_local_build_diagnostic_paths(
    result: BuildResult,
    *,
    run_root: Path,
    isolated_target_root: Path,
) -> BuildResult:
    """Project proven run-local target paths back to canonical workspace paths."""

    root = run_root.resolve()
    target = isolated_target_root.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise LocalEntryError(
            "Run-local build target must remain inside the isolated run root."
        ) from exc

    def project(diagnostic: Any) -> Any:
        raw_file = diagnostic.file
        if not isinstance(raw_file, str) or not raw_file:
            return diagnostic
        raw_path = Path(raw_file)
        if not raw_path.is_absolute():
            return diagnostic
        resolved = raw_path.resolve()
        try:
            resolved.relative_to(target)
        except ValueError:
            return diagnostic
        return replace(
            diagnostic,
            file=resolved.relative_to(root).as_posix(),
        )

    return replace(
        result,
        diagnostics=tuple(project(item) for item in result.diagnostics),
        warnings=tuple(project(item) for item in result.warnings),
    )


def _repair_history_fact_constraints(
    *,
    patch_proposal: Mapping[str, Any],
    patch_proposal_hash: str,
    build_result: Mapping[str, Any],
    build_result_hash: str,
    run_id: str,
    request_id: str,
) -> tuple[str, ...]:
    """Project prior execution facts without exposing historical editable text."""

    changed_scope = [
        {
            key: item.get(key)
            for key in ("change_id", "edit_binding_id", "operation")
        }
        for item in patch_proposal.get("diff_intent") or []
        if isinstance(item, Mapping)
    ]
    facts = {
        "run_identity": {
            "run_id": run_id,
            "request_id": request_id,
        },
        "committed_artifacts": {
            "patch_proposal": patch_proposal_hash,
            "build_result": build_result_hash,
        },
        "prior_change_scope": changed_scope,
        "objective_transition": {
            "before_prior_patch": "unavailable_in_current_run",
            "after_prior_patch": {
                "exit_code": build_result.get("exit_code"),
            },
        },
    }
    return (
        (
            "Current live-source evidence is the only editable source and the only "
            "source from which before_text may be copied. Historical action facts "
            "contain no editable code and must not be reconstructed into before_text."
        ),
        (
            "The objective command failed after the prior applied action, so the live "
            "source does not yet satisfy the request. Produce a real behavior change "
            "without assuming a specific repair."
        ),
        "Non-editable prior execution facts: "
        + json.dumps(facts, ensure_ascii=False, sort_keys=True),
    )


def _unique_repair_diagnostics(
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one provider-facing copy of each exact current Build diagnostic."""

    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in diagnostics:
        identity = json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        projected.append(dict(item))
    return projected


def _repair_provider_constraints(
    *,
    base_constraints: list[str],
    diagnostics: list[dict[str, Any]],
    history_constraints: tuple[str, ...],
) -> list[str]:
    """Project one provider-facing copy of each Repair diagnostic message."""

    projected = [str(item) for item in base_constraints]
    projected.append(
        "Use the supplied objective verification diagnostics to produce a "
        "different repair; do not repeat the prior failed behavior."
    )
    seen_messages: set[str] = set()
    for item in diagnostics:
        raw_message = item.get("message")
        if not raw_message:
            continue
        message = str(raw_message)
        if message in seen_messages:
            continue
        seen_messages.add(message)
        projected.append(message)
    projected.extend(history_constraints)
    return projected


def _patch_generation_obligation_projection(
    *,
    feature_spec: Mapping[str, Any],
    implementation: Mapping[str, Any],
    planned_changes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project exact feature-wide obligations and evidence-bound change identities."""

    def exact_string_list(
        owner: Mapping[str, Any],
        field_name: str,
        *,
        allow_empty: bool,
    ) -> list[str]:
        raw = owner.get(field_name)
        if not isinstance(raw, (list, tuple)) or (
            not allow_empty and not raw
        ):
            raise LocalEntryError(
                f"Patch generation {field_name} must be a"
                + (" list." if allow_empty else " non-empty list.")
            )
        if any(
            not isinstance(item, str) or not item.strip()
            for item in raw
        ):
            raise LocalEntryError(
                f"Patch generation {field_name} must contain only non-empty strings."
            )
        return list(raw)

    target_behavior = feature_spec.get("target_behavior")
    if not isinstance(target_behavior, str) or not target_behavior.strip():
        raise LocalEntryError(
            "Patch generation target_behavior must be a non-empty string."
        )
    acceptance_criteria = exact_string_list(
        feature_spec,
        "acceptance_criteria",
        allow_empty=False,
    )
    runtime_verification_plan = exact_string_list(
        feature_spec,
        "runtime_verification_plan",
        allow_empty=False,
    )
    side_effect_boundaries = exact_string_list(
        implementation,
        "side_effect_boundaries",
        allow_empty=True,
    )
    if not planned_changes:
        raise LocalEntryError(
            "Patch generation requires at least one proposed change."
        )

    required_change_units: list[dict[str, Any]] = []
    seen_change_ids: set[str] = set()
    seen_identities: set[tuple[str, str]] = set()
    for index, item in enumerate(planned_changes, start=1):
        identity, expected_validation = (
            _validated_plan_change_identity_and_validation(item, index=index)
        )
        if identity[0] in seen_change_ids or identity in seen_identities:
            raise LocalEntryError(
                "Patch generation Plan change identity is duplicated."
            )
        seen_change_ids.add(identity[0])
        seen_identities.add(identity)
        required_change_units.append(
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
            | {"expected_validation": expected_validation}
        )

    return {
        "target_behavior": target_behavior,
        "required_change_units": required_change_units,
        "side_effect_boundaries": side_effect_boundaries,
        "acceptance_criteria": acceptance_criteria,
        "runtime_verification_plan": runtime_verification_plan,
    }


def _validated_plan_change_identity_and_validation(
    item: Mapping[str, Any],
    *,
    index: int,
) -> tuple[tuple[str, str], list[str]]:
    change_id = item.get("change_id")
    edit_binding_id = item.get("edit_binding_id")
    if not isinstance(change_id, str) or not change_id:
        raise LocalEntryError(
            f"Patch generation proposed change {index} change_id is invalid."
        )
    if not isinstance(edit_binding_id, str) or not edit_binding_id:
        raise LocalEntryError(
            f"Patch generation proposed change {index} edit_binding_id is invalid."
        )
    raw_validation = item.get("expected_validation")
    if not isinstance(raw_validation, (list, tuple)) or not raw_validation:
        raise LocalEntryError(
            f"Patch generation proposed change {index} expected_validation "
            "must be a non-empty list."
        )
    if any(
        not isinstance(value, str) or not value.strip()
        for value in raw_validation
    ):
        raise LocalEntryError(
            f"Patch generation proposed change {index} expected_validation "
            "must contain only non-empty strings."
        )
    expected_validation = list(raw_validation)
    if len(set(expected_validation)) != len(expected_validation):
        raise LocalEntryError(
            f"Patch generation proposed change {index} expected_validation "
            "must not contain duplicates."
        )
    return (change_id, edit_binding_id), expected_validation


def _overlay_generated_patch_changes_on_plan(
    *,
    planned_changes: list[dict[str, Any]],
    generated_changes: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Bind generated patch bytes to exact Plan identity and validation."""

    planned_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    seen_change_ids: set[str] = set()
    for index, planned in enumerate(planned_changes, start=1):
        identity, _ = _validated_plan_change_identity_and_validation(
            planned,
            index=index,
        )
        if identity[0] in seen_change_ids or identity in planned_by_identity:
            raise LocalEntryError(
                "Patch generation Plan change identity is duplicated."
            )
        seen_change_ids.add(identity[0])
        planned_by_identity[identity] = planned

    overlaid: list[dict[str, Any]] = []
    generated_identities: set[tuple[str, str]] = set()
    for index, generated in enumerate(generated_changes, start=1):
        change_id = generated.get("change_id")
        edit_binding_id = generated.get("edit_binding_id")
        if not isinstance(change_id, str) or not isinstance(edit_binding_id, str):
            raise LocalEntryError(
                f"Generated patch change {index} identity is invalid."
            )
        identity = (change_id, edit_binding_id)
        planned = planned_by_identity.get(identity)
        if planned is None:
            raise LocalEntryError(
                "Generated patch is outside implementation-plan change units."
            )
        if identity in generated_identities:
            raise LocalEntryError("Generated patch change identity is duplicated.")
        generated_identities.add(identity)
        _, expected_validation = _validated_plan_change_identity_and_validation(
            planned,
            index=index,
        )
        if generated.get("expected_validation") != expected_validation:
            raise LocalEntryError(
                "Generated patch expected_validation does not match its exact "
                "implementation-plan change identity."
            )
        overlaid.append(
            {
                **planned,
                "rationale": generated["rationale"],
                "expected_validation": expected_validation,
                "rollback_hint": generated["rollback_hint"],
                "patch": generated["patch"],
            }
        )

    if generated_identities != set(planned_by_identity):
        raise LocalEntryError(
            "Generated patch does not cover every implementation-plan change identity."
        )
    return tuple(overlaid)


@dataclass(frozen=True)
class _RuntimeRepairSpan:
    selection_id: str
    source_hash: str
    start_line: int
    end_line: int
    before_text: str
    method_name: str

    def model_view(self) -> dict[str, Any]:
        return {
            "selection_id": self.selection_id,
            "source_hash": self.source_hash,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "unit_kind": "csharp_method",
            "method_name": self.method_name,
            "display_text": self.before_text,
        }


def _runtime_source_diagnostic_lines(
    diagnostics: tuple[Mapping[str, Any], ...] | None,
    *,
    source_path: Path,
    working_root: Path,
) -> tuple[int, ...]:
    if not diagnostics:
        return ()
    try:
        canonical_source = source_path.resolve()
    except OSError:
        return ()
    canonical_source_norm = canonical_source.as_posix().casefold()
    result: list[int] = []
    for item in diagnostics:
        if not isinstance(item, Mapping):
            continue
        raw_file = item.get("file")
        if not isinstance(raw_file, str):
            continue
        try:
            raw_line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        if raw_line < 1:
            continue
        try:
            diag_path = Path(raw_file)
            resolved_diag_path = (
                diag_path if diag_path.is_absolute() else working_root / diag_path
            ).resolve()
        except OSError:
            continue
        if resolved_diag_path.as_posix().casefold() == canonical_source_norm:
            result.append(raw_line)
    return tuple(sorted(set(result)))


def _runtime_repair_spans(
    live_text: str,
    *,
    source_hash: str,
    max_spans: int = 24,
    diagnostic_lines: tuple[int, ...] = (),
) -> tuple[_RuntimeRepairSpan, ...]:
    """Create bounded, non-overlapping complete-method repair handles."""

    if not live_text or max_spans < 1:
        return ()
    lines = live_text.splitlines(keepends=True)
    source_spans = [
        {
            "start_line": int(item["start_line"]),
            "end_line": int(item["end_line"]),
            "method_name": str(item["method_name"]),
            "source_text": str(item["source_text"]),
        }
        for item in _csharp_method_source_spans(lines)
    ]
    if diagnostic_lines:
        missing_diagnostics = []
        for line in diagnostic_lines:
            candidate = int(line)
            if not 1 <= candidate <= len(lines):
                continue
            for span in source_spans:
                if span["start_line"] <= candidate <= span["end_line"]:
                    break
            else:
                missing_diagnostics.append(candidate)
        if missing_diagnostics:
            diagnostic_segments: list[tuple[int, int]] = [
                (min(missing_diagnostics), max(missing_diagnostics))
            ]
            for source_span in sorted(source_spans, key=lambda item: item["start_line"]):
                span_start = source_span["start_line"]
                span_end = source_span["end_line"]
                remaining_segments: list[tuple[int, int]] = []
                for segment_start, segment_end in diagnostic_segments:
                    if segment_end < span_start or segment_start > span_end:
                        remaining_segments.append((segment_start, segment_end))
                        continue
                    if segment_start < span_start:
                        remaining_segments.append((segment_start, span_start - 1))
                    if segment_end > span_end:
                        remaining_segments.append((span_end + 1, segment_end))
                diagnostic_segments = remaining_segments
            for segment_start, segment_end in sorted(diagnostic_segments):
                if segment_start > segment_end:
                    continue
                source_spans.append(
                    {
                        "start_line": segment_start,
                        "end_line": segment_end,
                        "method_name": "diagnostic_bound_region",
                        "source_text": "".join(
                            lines[segment_start - 1 : segment_end]
                        ),
                    }
                )
    spans = sorted(source_spans, key=lambda item: item["start_line"])
    spans = spans[:max_spans]
    return tuple(
        _RuntimeRepairSpan(
            selection_id=f"s{index:02d}",
            source_hash=source_hash,
            start_line=int(span["start_line"]),
            end_line=int(span["end_line"]),
            before_text=str(span["source_text"]),
            method_name=str(span["method_name"]),
        )
        for index, span in enumerate(spans, start=1)
        if live_text.count(str(span["source_text"])) == 1
    )


def _objective_verification_source_views(
    working_directory: Path,
    *,
    max_files: int = 4,
    max_total_chars: int = 12000,
) -> tuple[dict[str, Any], ...]:
    """Read a bounded current C# verification view without inferring an answer."""

    root = working_directory.resolve()
    if not root.is_dir() or max_files < 1 or max_total_chars < 1:
        return ()
    views: list[dict[str, Any]] = []
    used_chars = 0
    paths = sorted(
        (
            path
            for path in root.rglob("*.cs")
            if not {"bin", "obj"}.intersection(
                part.lower() for part in path.relative_to(root).parts
            )
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in paths:
        if len(views) >= max_files:
            break
        source_bytes = path.read_bytes()
        try:
            source_text = source_bytes.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if used_chars + len(source_text) > max_total_chars:
            continue
        used_chars += len(source_text)
        views.append(
            {
                "source_path": path.relative_to(root).as_posix(),
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "source_text": source_text,
            }
        )
    return tuple(views)


def _repair_span_response_schema(
    spans: tuple[_RuntimeRepairSpan, ...],
) -> dict[str, Any]:
    selection_ids = [span.selection_id for span in spans]
    if not selection_ids:
        raise LocalEntryError("Repair span selection requires current-source spans.")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["selection_id", "replacement_text", "rationale"],
        "properties": {
            "selection_id": {"type": "string", "enum": selection_ids},
            "replacement_text": {"type": "string", "minLength": 1},
            "rationale": {"type": "string", "minLength": 1},
        },
    }


def _materialize_repair_span_change(
    raw_response: str,
    *,
    spans: tuple[_RuntimeRepairSpan, ...],
    required_change: Mapping[str, Any],
    expected_validation: tuple[str, ...],
) -> dict[str, Any]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise PatchGenerationError(
            f"Repair span output is not strict JSON: {exc}.",
            diagnostic_content=raw_response,
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "selection_id",
        "replacement_text",
        "rationale",
    }:
        raise PatchGenerationError(
            "Repair span output must contain exactly selection_id, "
            "replacement_text, and rationale.",
            diagnostic_content=raw_response,
        )
    selection_id = payload.get("selection_id")
    replacement_text = payload.get("replacement_text")
    rationale = payload.get("rationale")
    selected = next(
        (span for span in spans if span.selection_id == selection_id),
        None,
    )
    if selected is None:
        raise PatchGenerationError(
            "Repair span output selected an unknown runtime handle.",
            diagnostic_content=raw_response,
        )
    if not isinstance(replacement_text, str) or not replacement_text:
        raise PatchGenerationError(
            "Repair replacement_text must be non-empty.",
            diagnostic_content=raw_response,
        )
    if replacement_text == selected.before_text:
        raise PatchGenerationError(
            "Repair replacement_text must change the selected live-source span.",
            diagnostic_content=raw_response,
        )
    if not isinstance(rationale, str) or not rationale:
        raise PatchGenerationError(
            "Repair rationale must be non-empty.",
            diagnostic_content=raw_response,
        )
    return {
        "change_id": str(required_change.get("change_id") or ""),
        "change_type": "modify_behavior",
        "edit_binding_id": str(required_change.get("edit_binding_id") or ""),
        "operation": "exact_text_replace",
        "rationale": rationale,
        "expected_validation": list(expected_validation),
        "rollback_hint": "Restore the selected live-source span.",
        "patch": {
            "kind": "exact_text_replace",
            "before_text": selected.before_text,
            "after_text": replacement_text,
            "expected_occurrences": 1,
        },
    }


def _implementation_with_runtime_repair_bindings(
    implementation: Mapping[str, Any],
    *,
    runtime_bindings: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Project current run-local source identities into Repair execution."""

    registry = implementation.get("binding_registry")
    if not isinstance(registry, Mapping):
        raise LocalEntryError("Repair execution requires an implementation binding registry.")
    original_bindings = {
        str(item.get("binding_id") or ""): item
        for item in registry.get("edit_bindings") or []
        if isinstance(item, Mapping) and item.get("binding_id")
    }
    revised_bindings = {
        str(item.get("binding_id") or ""): item
        for item in runtime_bindings
        if isinstance(item, Mapping) and item.get("binding_id")
    }
    if not revised_bindings or not set(revised_bindings).issubset(original_bindings):
        raise LocalEntryError(
            "Repair execution bindings must revise existing edit bindings exactly once."
        )
    for binding_id, revised in revised_bindings.items():
        original = original_bindings[binding_id]
        if revised.get("canonical_target_path") != original.get(
            "canonical_target_path"
        ):
            raise LocalEntryError("Repair execution cannot change an edit binding path.")
        if not isinstance(revised.get("source_hash"), str) or not revised.get(
            "source_hash"
        ):
            raise LocalEntryError("Repair execution binding source_hash is missing.")
        span = revised.get("target_span")
        if (
            not isinstance(span, Mapping)
            or not isinstance(span.get("start_line"), int)
            or not isinstance(span.get("end_line"), int)
            or span["start_line"] <= 0
            or span["end_line"] < span["start_line"]
        ):
            raise LocalEntryError("Repair execution binding target_span is invalid.")
    projected_bindings = [
        dict(revised_bindings.get(binding_id, original))
        for binding_id, original in original_bindings.items()
    ]
    return {
        **dict(implementation),
        "binding_registry": {
            **dict(registry),
            "edit_bindings": projected_bindings,
        },
    }


def _repair_review_context(
    implementation: Mapping[str, Any],
    evidence_pack: Mapping[str, Any],
    *,
    runtime_bindings: tuple[dict[str, Any], ...],
    runtime_evidence: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind formal Repair review to the same current live source as generation."""

    projected_implementation = _implementation_with_runtime_repair_bindings(
        implementation,
        runtime_bindings=runtime_bindings,
    )
    if not runtime_evidence:
        raise LocalEntryError("Repair review requires current run-local evidence.")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for item in runtime_evidence:
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise LocalEntryError("Repair review evidence identity is missing.")
        if evidence_id in evidence_by_id:
            raise LocalEntryError("Repair review evidence identity is ambiguous.")
        evidence_by_id[evidence_id] = dict(item)
    for binding in runtime_bindings:
        evidence_id = binding.get("evidence_id")
        evidence = evidence_by_id.get(str(evidence_id or ""))
        if evidence is None:
            raise LocalEntryError(
                "Repair review binding does not resolve to current run-local evidence."
            )
        source_hash = binding.get("source_hash")
        if (
            evidence.get("source_path") != binding.get("canonical_target_path")
            or evidence.get("source_hash") != source_hash
            or evidence.get("file_hash") != source_hash
            or evidence.get("doc_hash") != source_hash
        ):
            raise LocalEntryError(
                "Repair review evidence does not match its current source binding."
            )
        excerpt = evidence.get("excerpt")
        if (
            not isinstance(excerpt, str)
            or hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != source_hash
        ):
            raise LocalEntryError(
                "Repair review evidence excerpt does not match its source hash."
            )
    original_items = [
        dict(item)
        for item in evidence_pack.get("items") or []
        if isinstance(item, Mapping)
        and str(item.get("evidence_id") or "") not in evidence_by_id
    ]
    projected_evidence_pack = {
        **dict(evidence_pack),
        "items": [*original_items, *evidence_by_id.values()],
    }
    return projected_implementation, projected_evidence_pack


def _read_utf8_source_snapshot(source_path: Path) -> tuple[str, str]:
    """Read one raw source snapshot and derive its exact text and byte hash."""

    source_bytes = source_path.read_bytes()
    return (
        source_bytes.decode("utf-8"),
        hashlib.sha256(source_bytes).hexdigest(),
    )


class _MaterializedRepairPatchLLM:
    """Feed a deterministically materialized repair through the existing validator."""

    def __init__(self, *, response: ChatResponse) -> None:
        self._response = response

    def chat(self, _messages: list[Message], **_kwargs: Any) -> ChatResponse:
        return self._response


def _require_run_local_build_path(*, root: Path, path: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise LocalEntryError(
            f"NuGet-isolated build {label} must remain inside the run workspace."
        ) from exc


def _create_run_local_member_access_resolver(
    *,
    inspector_path: Path,
    run_root: Path,
) -> RunLocalMemberAccessResolver:
    root = run_root.resolve()
    dependency_paths = (
        root / "build_dependencies" / "BepInEx",
        root / "build_dependencies" / "GameFolder" / "BepInEx",
    )
    for dependency_path in dependency_paths:
        resolved_dependency = dependency_path.resolve()
        try:
            _require_run_local_build_path(
                root=root,
                path=resolved_dependency,
                label="compiled artifact member access dependency_root",
            )
        except LocalEntryError:
            continue
        if resolved_dependency.is_dir():
            return RunLocalMemberAccessResolver(
                inspector_path,
                dependency_root=resolved_dependency,
            )
    raise LocalEntryError(
        "Run-local compiled artifact member access dependency root is missing."
    )


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
    verification_operation: VerificationOperationSpec | None = None,
    feature_id: str | None = None,
    feature_spec_path: str | Path | None = None,
    feature_spec_hash: str | None = None,
    evidence_pack_path: str | Path | None = None,
    evidence_pack_hash: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    user_request: str | None = None,
    target_domain: str | None = None,
    target_mod: str | None = None,
) -> dict[str, Any] | VerificationOperationPreflightResultV1:
    """Read-validate a verification-only Build without probing Store writes."""

    legacy_values = (
        feature_id,
        feature_spec_path,
        feature_spec_hash,
        evidence_pack_path,
        evidence_pack_hash,
        run_id,
        request_id,
        user_request,
        target_domain,
        target_mod,
    )
    typed_call = verification_operation is not None
    if typed_call and any(value is not None for value in legacy_values):
        return _verification_preflight_result(
            envelope=None,
            operation_kind=None,
            operation_contract_version=None,
            status="blocked",
            failure_stage="authorization",
            identity_resolution_status="unresolved",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "authorization",
                        "code": "VERIFICATION_OPERATION_LEGACY_MIXED",
                        "message": "Typed Build operation cannot mix legacy identity inputs.",
                    }
                ],
                default_stage="authorization",
            ),
        )
    if not typed_call:
        required = {
            "feature_id": feature_id,
            "feature_spec_path": feature_spec_path,
            "feature_spec_hash": feature_spec_hash,
            "evidence_pack_path": evidence_pack_path,
            "evidence_pack_hash": evidence_pack_hash,
            "run_id": run_id,
            "request_id": request_id,
            "user_request": user_request,
            "target_domain": target_domain,
        }
        if any(value is None for value in required.values()):
            raise TypeError("Legacy verification Build inputs are incomplete.")
        verification_operation = VerificationOperationSpec(
            operation_kind=VERIFICATION_BUILD_KIND,
            operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=BuildInvocationProtocolBindingV1(
                run_id=str(run_id),
                request_id=str(request_id),
            ),
            variant_payload=VerificationBuildOperationV1(
                feature_spec_ref=ArtifactRef(
                    feature_id=str(feature_id),
                    artifact_type="feature_spec",
                    path=str(Path(feature_spec_path).resolve()),
                    artifact_hash=str(feature_spec_hash),
                ),
                evidence_pack_ref=ArtifactRef(
                    feature_id=str(feature_id),
                    artifact_type="evidence_pack",
                    path=str(Path(evidence_pack_path).resolve()),
                    artifact_hash=str(evidence_pack_hash),
                ),
                user_request=str(user_request),
                target_domain=str(target_domain),
                target_mod=target_mod,
            ),
        )
    try:
        declaration = resolve_verification_operation(verification_operation)
    except (TypeError, ValueError) as exc:
        if not typed_call:
            raise LocalEntryError(str(exc)) from exc
        return _verification_preflight_result(
            envelope=None,
            operation_kind=None,
            operation_contract_version=None,
            status="blocked",
            failure_stage="authorization",
            identity_resolution_status="unresolved",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "authorization",
                        "code": "VERIFICATION_OPERATION_UNSUPPORTED",
                        "message": str(exc),
                    }
                ],
                default_stage="authorization",
            ),
        )
    if declaration.operation_kind != VERIFICATION_BUILD_KIND:
        blocker = _verification_blockers(
            [
                {
                    "stage": "authorization",
                    "code": "VERIFICATION_BUILD_OPERATION_REQUIRED",
                    "message": "Build public entry requires verification_build.",
                }
            ],
            default_stage="authorization",
        )
        if typed_call:
            return _verification_preflight_result(
                envelope=None,
                operation_kind=None,
                operation_contract_version=None,
                status="blocked",
                failure_stage="authorization",
                identity_resolution_status="unresolved",
                blockers=blocker,
            )
        raise LocalEntryError(blocker[0].message)
    variant = verification_operation.variant_payload
    protocol = verification_operation.protocol_binding
    try:
        _, _, preflight = _verification_only_build_admission(
        artifact_store_root=artifact_store_root,
            feature_id=variant.feature_spec_ref.feature_id,
            feature_spec_path=variant.feature_spec_ref.path,
            feature_spec_hash=variant.feature_spec_ref.artifact_hash,
            evidence_pack_path=variant.evidence_pack_ref.path,
            evidence_pack_hash=variant.evidence_pack_ref.artifact_hash,
            run_id=protocol.run_id,
            request_id=protocol.request_id,
            user_request=variant.user_request,
            target_mod=variant.target_mod,
        )
        envelope = project_verification_operation(verification_operation)
    except (LocalEntryError, OSError, TypeError, ValueError) as exc:
        if not typed_call:
            raise
        return _verification_preflight_result(
            envelope=None,
            operation_kind=declaration.operation_kind,
            operation_contract_version=declaration.operation_contract_version,
            status="blocked",
            failure_stage="admission",
            identity_resolution_status="declaration_resolved",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "admission",
                        "code": "VERIFICATION_BUILD_ADMISSION_FAILED",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                ],
                default_stage="admission",
            ),
        )
    ready = preflight["status"] == "ready_for_build_authorization"
    machine_result = _verification_preflight_result(
        envelope=envelope,
        operation_kind=envelope.operation_kind,
        operation_contract_version=envelope.operation_contract_version,
        status="ready" if ready else "blocked",
        failure_stage=None if ready else "admission",
        blockers=(
            ()
            if ready
            else _verification_blockers(
                list(preflight.get("blockers") or ()),
                default_stage="admission",
            )
        ),
        audit_snapshot={"legacy_compatibility": not typed_call},
    )
    if typed_call:
        return machine_result
    return {
        "status": preflight["status"],
        "command": "preflight-verification-only-build-continuation",
        "feature_id": variant.feature_spec_ref.feature_id,
        "run_id": protocol.run_id,
        "request_id": protocol.request_id,
        "target_domain": variant.target_domain,
        "target_mod": variant.target_mod,
        "verification_only_preflight": preflight,
        "verification_operation_preflight_result": machine_result.to_dict(),
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


def _build_verification_machine_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: Mapping[str, Any],
) -> VerificationOperationResultV1:
    build_projection = public_result.get("build_result")
    checkpoint_projection = public_result.get("workflow_checkpoint")
    build_ref = _artifact_ref_from_projection(
        build_projection.get("artifact_ref")
        if isinstance(build_projection, Mapping)
        else None
    )
    checkpoint_ref = _artifact_ref_from_projection(
        checkpoint_projection.get("artifact_ref")
        if isinstance(checkpoint_projection, Mapping)
        else None
    )
    build_execution = public_result.get("build_execution")
    domain_status_value = (
        build_execution.get("domain_status")
        if isinstance(build_execution, Mapping)
        else None
    )
    domain_status = (
        "succeeded"
        if domain_status_value == "success"
        else "failed"
        if domain_status_value == "failed"
        else "unknown"
    )
    claims_success = bool(
        isinstance(build_execution, Mapping)
        and build_execution.get("claims_real_build_success") is True
        and build_ref is not None
    )
    handoff_ready = public_result.get("handoff_ready") is True
    variant = BuildVerificationResultV1(
        domain_build_status=domain_status,
        claims_real_build_success=claims_success,
        build_result_ref=build_ref,
        workflow_checkpoint_ref=checkpoint_ref,
        handoff_ready=handoff_ready,
    )
    platform_status = _exact_verification_platform_status(public_result)
    receipts = _verification_store_receipts(
        (
            (
                "build_result",
                build_projection.get("store_result")
                if isinstance(build_projection, Mapping)
                else None,
            ),
            (
                "workflow_checkpoint",
                checkpoint_projection.get("store_result")
                if isinstance(checkpoint_projection, Mapping)
                else None,
            ),
        )
    )
    blockers = _verification_blockers(
        list(public_result.get("blockers") or ()),
        default_stage=str(public_result.get("failure_stage") or "admission"),
    ) if platform_status == "blocked" else tuple(
        _verification_blockers(
            list(public_result.get("blockers") or ()),
            default_stage=str(public_result.get("failure_stage") or "admission"),
        )
    ) if public_result.get("blockers") else ()
    return project_verification_operation_result(
        envelope=envelope,
        platform_status=platform_status,
        failure_stage=public_result.get("failure_stage"),
        side_effects_may_have_started=bool(
            isinstance(build_execution, Mapping)
            and build_execution.get("side_effects_may_have_started") is True
        ),
        store_receipts=receipts,
        blockers=blockers,
        variant_result=variant,
        audit_snapshot={
            "compatibility_mode": "typed_current",
        },
    )


def _finalize_build_public_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: dict[str, Any],
    typed_call: bool,
) -> dict[str, Any] | VerificationOperationResultV1:
    machine_result = _build_verification_machine_result(
        envelope=envelope,
        public_result=public_result,
    )
    if typed_call:
        return machine_result
    public_result["verification_operation_result"] = machine_result.to_dict()
    return public_result


def execute_verification_only_build_continuation(
    *,
    artifact_store_root: str | Path,
    verification_operation: VerificationOperationEnvelope | None = None,
    expected_approval_identity_hash: str | None = None,
    feature_id: str | None = None,
    feature_spec_path: str | Path | None = None,
    feature_spec_hash: str | None = None,
    evidence_pack_path: str | Path | None = None,
    evidence_pack_hash: str | None = None,
    run_id: str | None = None,
    request_id: str | None = None,
    user_request: str | None = None,
    target_domain: str | None = None,
    target_mod: str | None = None,
    build_result_factory: Callable[[str, str | None], BuildResult],
    allow_build_execution: bool,
) -> dict[str, Any] | VerificationOperationResultV1:
    """Execute one admitted verification-only Build through the public graph."""

    if not callable(build_result_factory):
        raise TypeError("build_result_factory must be callable.")
    legacy_values = (
        feature_id,
        feature_spec_path,
        feature_spec_hash,
        evidence_pack_path,
        evidence_pack_hash,
        run_id,
        request_id,
        user_request,
        target_domain,
        target_mod,
    )
    typed_call = verification_operation is not None
    if typed_call and any(value is not None for value in legacy_values):
        return _rejected_verification_result(
            operation_kind=None,
            operation_contract_version=None,
            approval_identity_hash=None,
            identity_resolution_status="unresolved",
            failure_stage="authorization",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "authorization",
                        "code": "VERIFICATION_OPERATION_LEGACY_MIXED",
                        "message": "Typed Build operation cannot mix legacy identity inputs.",
                    }
                ],
                default_stage="authorization",
            ),
        )
    if not typed_call:
        required = {
            "feature_id": feature_id,
            "feature_spec_path": feature_spec_path,
            "feature_spec_hash": feature_spec_hash,
            "evidence_pack_path": evidence_pack_path,
            "evidence_pack_hash": evidence_pack_hash,
            "run_id": run_id,
            "request_id": request_id,
            "user_request": user_request,
            "target_domain": target_domain,
        }
        if any(value is None for value in required.values()):
            raise TypeError("Legacy verification Build inputs are incomplete.")
        spec = VerificationOperationSpec(
            operation_kind=VERIFICATION_BUILD_KIND,
            operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=BuildInvocationProtocolBindingV1(
                run_id=str(run_id),
                request_id=str(request_id),
            ),
            variant_payload=VerificationBuildOperationV1(
                feature_spec_ref=ArtifactRef(
                    feature_id=str(feature_id),
                    artifact_type="feature_spec",
                    path=str(Path(feature_spec_path).resolve()),
                    artifact_hash=str(feature_spec_hash),
                ),
                evidence_pack_ref=ArtifactRef(
                    feature_id=str(feature_id),
                    artifact_type="evidence_pack",
                    path=str(Path(evidence_pack_path).resolve()),
                    artifact_hash=str(evidence_pack_hash),
                ),
                user_request=str(user_request),
                target_domain=str(target_domain),
                target_mod=target_mod,
            ),
        )
        verification_operation = project_verification_operation(spec)
    try:
        envelope = validate_verification_operation_envelope(
            verification_operation
        )
        declaration = resolve_verification_operation(envelope)
    except (TypeError, ValueError) as exc:
        if not typed_call:
            raise LocalEntryError(str(exc)) from exc
        return _rejected_verification_result(
            operation_kind=None,
            operation_contract_version=None,
            approval_identity_hash=None,
            identity_resolution_status="unresolved",
            failure_stage="authorization",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "authorization",
                        "code": "VERIFICATION_OPERATION_UNSUPPORTED",
                        "message": str(exc),
                    }
                ],
                default_stage="authorization",
            ),
        )
    if declaration.operation_kind != VERIFICATION_BUILD_KIND:
        return _rejected_verification_result(
            operation_kind=None,
            operation_contract_version=None,
            approval_identity_hash=None,
            identity_resolution_status="unresolved",
            failure_stage="authorization",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "authorization",
                        "code": "VERIFICATION_BUILD_OPERATION_REQUIRED",
                        "message": "Build public entry requires verification_build.",
                    }
                ],
                default_stage="authorization",
            ),
        )
    if typed_call and (
        not isinstance(expected_approval_identity_hash, str)
        or not hmac.compare_digest(
            expected_approval_identity_hash,
            envelope.approval_identity_hash,
        )
    ):
        public_result = _verification_only_build_terminal_result(
            status="blocked",
            failure_stage="authorization",
            feature_id=envelope.variant_payload.feature_spec_ref.feature_id,
            run_id=envelope.protocol_binding.run_id,
            request_id=envelope.protocol_binding.request_id,
            target_domain=envelope.variant_payload.target_domain,
            target_mod=envelope.variant_payload.target_mod,
            preflight={},
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "authorization",
                    "code": "VERIFICATION_OPERATION_APPROVAL_HASH_MISMATCH",
                    "message": "Expected Build approval identity hash changed.",
                }
            ],
        )
        return _finalize_build_public_result(
            envelope=envelope,
            public_result=public_result,
            typed_call=True,
        )
    variant = envelope.variant_payload
    protocol = envelope.protocol_binding
    store, continuation, preflight = _verification_only_build_admission(
        artifact_store_root=artifact_store_root,
        feature_id=variant.feature_spec_ref.feature_id,
        feature_spec_path=variant.feature_spec_ref.path,
        feature_spec_hash=variant.feature_spec_ref.artifact_hash,
        evidence_pack_path=variant.evidence_pack_ref.path,
        evidence_pack_hash=variant.evidence_pack_ref.artifact_hash,
        run_id=protocol.run_id,
        request_id=protocol.request_id,
        user_request=variant.user_request,
        target_mod=variant.target_mod,
    )
    feature_id = variant.feature_spec_ref.feature_id
    run_id = protocol.run_id
    request_id = protocol.request_id
    target_domain = variant.target_domain
    target_mod = variant.target_mod
    if not allow_build_execution:
        public_result = _verification_only_build_terminal_result(
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
        return _finalize_build_public_result(
            envelope=envelope,
            public_result=public_result,
            typed_call=typed_call,
        )
    if preflight["status"] != "ready_for_build_authorization":
        public_result = _verification_only_build_terminal_result(
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
        return _finalize_build_public_result(
            envelope=envelope,
            public_result=public_result,
            typed_call=typed_call,
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
        verification_operation=envelope,
    )
    initial_state = create_initial_state(
        run_id=run_id,
        request_id=request_id,
        user_request=variant.user_request,
        target_domain=target_domain,
        target_mod=target_mod,
    )
    try:
        graph_result = graph.invoke(initial_state)
    except Exception as exc:
        stage = execution_failure_stage or "admission"
        public_result = _verification_only_build_terminal_result(
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
        return _finalize_build_public_result(
            envelope=envelope,
            public_result=public_result,
            typed_call=typed_call,
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

    public_result = _verification_only_build_terminal_result(
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
    return _finalize_build_public_result(
        envelope=envelope,
        public_result=public_result,
        typed_call=typed_call,
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
    ordered_summary: dict[str, Any] = {}
    for key in sorted(summary):
        value = summary[key]
        ordered_summary[key] = (
            value
            if key == "product_execution_result"
            else _sort_graph_terminal_json_objects(value)
        )
    result_bytes = (
        json.dumps(ordered_summary, ensure_ascii=False, indent=2) + "\n"
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


def _sort_graph_terminal_json_objects(value: Any) -> Any:
    """Retain legacy recursive key ordering outside the owner result subtree."""

    if isinstance(value, dict):
        return {
            key: _sort_graph_terminal_json_objects(value[key])
            for key in sorted(value)
        }
    if isinstance(value, list):
        return [_sort_graph_terminal_json_objects(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sort_graph_terminal_json_objects(item) for item in value)
    return value


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
    reader: Callable[[dict[str, Any]], str | Mapping[str, Any]],
    dry_run: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    raw_approval = reader(dict(dry_run))
    if isinstance(raw_approval, Mapping):
        semantic_decision = dict(raw_approval)
    elif isinstance(raw_approval, str):
        approval_text = raw_approval.strip()
        if approval_text == EXACT_DIFF_REJECTION_TOKEN:
            if dry_run.get("human_semantic_review_required") is True:
                raise LocalEntryError(
                    "Unproven semantic assurance requires a structured reject "
                    "decision bound to the current exact diff."
                )
            raise ExactDiffApprovalRejectedError(
                "User rejected the displayed exact diff."
            )
        semantic_decision = None
        if dry_run.get("human_semantic_review_required") is True:
            try:
                parsed = json.loads(approval_text)
            except json.JSONDecodeError as exc:
                raise LocalEntryError(
                    "Unproven semantic assurance requires one structured human "
                    "semantic decision JSON object from the exact-diff approval flow."
                ) from exc
            if not isinstance(parsed, Mapping):
                raise LocalEntryError(
                    "Unproven semantic assurance requires one structured human "
                    "semantic decision JSON object from the exact-diff approval flow."
                )
            semantic_decision = dict(parsed)
        else:
            return approval_text, None
    else:
        raise LocalEntryError(
            "Exact-diff approval reader must return a string or JSON object."
        )
    approved_diff_hash = semantic_decision.get("diff_hash")
    if not isinstance(approved_diff_hash, str):
        raise LocalEntryError(
            "Structured human semantic decision diff_hash must be a string."
        )
    return approved_diff_hash, semantic_decision


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
    diff_approval_reader: (
        Callable[[dict[str, Any]], str | Mapping[str, Any]] | None
    ) = None,
    source_disclosure_approval_id: str | None = None,
    source_revision_binding: Mapping[str, str] | None = None,
    source_git_admission: StrictGitAdmission | None = None,
    game_folder_build_binding: RunLocalGameFolderBindingV1 | None = None,
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
    ollama_timeout_seconds: float | None = None,
    repair_ollama_model: str | None = None,
    repair_ollama_timeout_seconds: float | None = None,
    ollama_max_output_tokens: int = 4096,
    ollama_context_window: int | None = None,
    ollama_model_identity_reader: OllamaModelIdentityReader | None = None,
    ollama_server_version_reader: OllamaServerVersionReader | None = None,
    objective_verification_command: tuple[str, ...] | None = None,
    requirement_coverage_projection_factory: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    requirement_coverage_findings_factory: (
        Callable[[Mapping[str, Any], Any], Mapping[str, Any]] | None
    ) = None,
    planning_target_evidence_ids: tuple[str, ...] = (),
    run_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run one request through the existing graph against an isolated target copy."""

    if (run_id is None) != (request_id is None):
        raise LocalEntryError(
            "run-request explicit run_id and request_id must be supplied together."
        )
    if run_id is not None and (
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id) is None
        or not isinstance(request_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", request_id) is None
    ):
        raise LocalEntryError("run-request explicit run identity is invalid.")
    if not description.strip():
        raise LocalEntryError("run-request requires a non-empty natural-language request.")
    if not isinstance(planning_target_evidence_ids, tuple) or any(
        type(value) is not str or not value
        for value in planning_target_evidence_ids
    ):
        raise LocalEntryError(
            "run-request Planning target evidence IDs must be exact non-empty strings."
        )
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
    if game_folder_build_binding is not None and not isinstance(
        game_folder_build_binding, RunLocalGameFolderBindingV1
    ):
        raise LocalEntryError(
            "run-request game_folder_build_binding must be RunLocalGameFolderBindingV1."
        )
    if repair_ollama_model is not None and not local_ollama:
        raise LocalEntryError(
            "A Repair Ollama model can only be selected for local Ollama execution."
        )
    if ollama_timeout_seconds is not None:
        if not local_ollama:
            raise LocalEntryError(
                "Main Ollama timeout can only be configured for local Ollama execution."
            )
        if (
            isinstance(ollama_timeout_seconds, bool)
            or not isinstance(ollama_timeout_seconds, (int, float))
            or not math.isfinite(float(ollama_timeout_seconds))
            or ollama_timeout_seconds <= 0
        ):
            raise LocalEntryError(
                "Main Ollama timeout seconds must be a positive finite number."
            )
    if repair_ollama_timeout_seconds is not None:
        if repair_ollama_model is None:
            raise LocalEntryError(
                "A Repair Ollama timeout requires an explicit Repair Ollama model."
            )
        if (
            isinstance(repair_ollama_timeout_seconds, bool)
            or not isinstance(repair_ollama_timeout_seconds, (int, float))
            or not math.isfinite(float(repair_ollama_timeout_seconds))
            or repair_ollama_timeout_seconds <= 0
        ):
            raise LocalEntryError(
                "Repair Ollama timeout seconds must be a positive finite number."
            )
    if objective_verification_command is not None and (
        not objective_verification_command
        or not all(
            isinstance(part, str) and part
            for part in objective_verification_command
        )
    ):
        raise LocalEntryError(
            "run-request objective verification command must contain non-empty strings."
        )
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
    local_model_identity: dict[str, Any] | None = None
    repair_local_model_identity: dict[str, Any] | None = None
    local_ollama_server_version: str | None = None
    repair_llm: Any | None = None
    repair_model_context_limit: int | None = None
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
            llm_options: dict[str, Any] = {
                "base_url": llm_base_url,
                "context_window": ollama_context_window,
            }
            if ollama_timeout_seconds is not None:
                llm_options["timeout"] = float(ollama_timeout_seconds)
            llm = LLMFactory.create(
                settings,
                **llm_options,
            )
        except Exception as exc:
            raise LocalEntryError(
                f"Local Ollama initialization failed: {type(exc).__name__}."
            ) from exc
        if not isinstance(llm, OllamaLLM):
            raise LocalEntryError("Local model selection did not create OllamaLLM.")
        if repair_ollama_model is not None:
            repair_local_model_identity = identity_reader(
                llm_base_url,
                repair_ollama_model,
            )
            _validate_ollama_model_identity(
                repair_local_model_identity,
                expected_base_url=llm_base_url,
                expected_model=repair_ollama_model,
            )
            repair_model_context_limit = _validate_ollama_context_window(
                repair_local_model_identity,
                requested_context_window=ollama_context_window,
            )
            repair_settings = replace(
                settings,
                llm=replace(
                    settings.llm,
                    provider="ollama",
                    model=repair_ollama_model,
                    max_tokens=ollama_max_output_tokens,
                    api_key=None,
                    base_url=llm_base_url,
                ),
            )
            try:
                repair_llm_options: dict[str, Any] = {
                    "base_url": llm_base_url,
                    "context_window": ollama_context_window,
                }
                if repair_ollama_timeout_seconds is not None:
                    repair_llm_options["timeout"] = float(
                        repair_ollama_timeout_seconds
                    )
                repair_llm = LLMFactory.create(
                    repair_settings,
                    **repair_llm_options,
                )
            except Exception as exc:
                raise LocalEntryError(
                    "Local Repair Ollama initialization failed: "
                    f"{type(exc).__name__}."
                ) from exc
            if not isinstance(repair_llm, OllamaLLM):
                raise LocalEntryError(
                    "Local Repair model selection did not create OllamaLLM."
                )
        source_disclosure = local_no_external_disclosure_record()
        model_admission = local_model_admission_record(
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
        strict_git_admission=source_git_admission,
    )
    base = Path(workspace_base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    if run_id is None:
        run_id = uuid4().hex[:8]
        request_id = f"request_{run_id}"
    assert request_id is not None
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
        "repair_local_model_identity": repair_local_model_identity,
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
        "game_folder_build_binding": (
            game_folder_build_binding.to_dict()
            if game_folder_build_binding is not None
            else None
        ),
        "game_folder_build_dependency": None,
    }
    (run_root / "run_manifest.json").write_text(
        json.dumps(initial_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    game_folder_dependency: dict[str, object] | None = None
    isolated_game_folder_dir: Path | None = None
    if game_folder_build_binding is not None:
        game_folder_source_identity = _run_pre_graph_step(
            failure_stage="build_dependency_snapshot",
            action=lambda: _validate_game_folder_build_binding(
                game_folder_build_binding,
                canonical_source_root=source,
            ),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra={
                "game_folder_build_binding": game_folder_build_binding.to_dict()
            },
        )
        game_folder_dependency = _run_pre_graph_step(
            failure_stage="build_dependency_copy",
            action=lambda: _materialize_game_folder_build_dependency(
                game_folder_source_identity,
                run_root=run_root,
            ),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra={
                "game_folder_build_binding": game_folder_build_binding.to_dict(),
                "game_folder_source_identity": {
                    "source_root": str(game_folder_source_identity.source_root),
                    "snapshot_sha256": game_folder_source_identity.snapshot_sha256,
                    "file_count": game_folder_source_identity.file_count,
                },
            },
        )
        isolated_game_folder_dir = Path(
            str(game_folder_dependency["isolated_copy"])
        )
        initial_manifest["game_folder_build_dependency"] = dict(
            game_folder_dependency
        )
        (run_root / "run_manifest.json").write_text(
            json.dumps(initial_manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
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
        action=lambda: (
            _optional_project_text_property(
                source_project,
                property_name="AssemblyName",
            )
            or source_project.stem
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    source_bepinex_value = _run_pre_graph_step(
        failure_stage="baseline_profile",
        action=lambda: _optional_project_text_property(
            source_project,
            property_name="BepInExDir",
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    source_bepinex_dir = (
        Path(source_bepinex_value.replace("\\", os.sep))
        if source_bepinex_value is not None
        else None
    )
    if source_bepinex_dir is not None and not source_bepinex_dir.is_absolute():
        source_bepinex_dir = (source_project.parent / source_bepinex_dir).resolve()
    elif source_bepinex_dir is not None:
        source_bepinex_dir = source_bepinex_dir.resolve()
    if source_bepinex_dir is not None and not source_bepinex_dir.is_dir():
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
    isolated_bepinex_dir: Path | None = None
    if source_bepinex_dir is not None:
        isolated_bepinex_dir = run_root / "build_dependencies" / "BepInEx"
        isolated_bepinex_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_pre_graph_step(
            failure_stage="build_dependency_preparation",
            action=lambda: shutil.copytree(source_bepinex_dir, isolated_bepinex_dir),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
        )
    isolated_nuget_config = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<configuration><packageSources><clear /></packageSources></configuration>\n"
    )
    for copied_project_root in (target_copy, baseline_copy):
        copied_config = copied_project_root / "nuget.config"
        if not copied_config.exists():
            copied_config.write_bytes(isolated_nuget_config)
    build_profile_stage = (
        "build_dependency_profile"
        if game_folder_build_binding is not None
        else "baseline_profile"
    )
    nuget_build_profile = _run_pre_graph_step(
        failure_stage=build_profile_stage,
        action=lambda: _create_nuget_isolated_build_profile(
            run_root=run_root,
            working_directory=target_copy,
            config_file=target_copy / "nuget.config",
            bepinex_dir=isolated_bepinex_dir,
            timeout_seconds=120,
            game_folder_dir=isolated_game_folder_dir,
        ),
        run_root=run_root,
        run_id=run_id,
        request_id=request_id,
        source_revision_binding=source_revision_binding,
        model_admission=model_admission,
    )
    baseline_build_profile = _run_pre_graph_step(
        failure_stage=build_profile_stage,
        action=lambda: _create_nuget_isolated_build_profile(
            run_root=run_root,
            working_directory=baseline_copy,
            config_file=baseline_copy / "nuget.config",
            bepinex_dir=isolated_bepinex_dir,
            timeout_seconds=120,
            game_folder_dir=isolated_game_folder_dir,
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
        extra={
            "verification_tool_build": verification_tool_build,
            "game_folder_build_dependency": game_folder_dependency,
        },
    )
    baseline_stdout.write_text(baseline.stdout, encoding="utf-8")
    baseline_stderr.write_text(baseline.stderr, encoding="utf-8")
    target_framework = _optional_project_text_property(
        source_project,
        property_name="TargetFramework",
    )
    append_target_framework = _optional_project_text_property(
        source_project,
        property_name="AppendTargetFrameworkToOutputPath",
    )
    append_target_framework_directory = (
        target_framework is not None
        and append_target_framework != "false"
    )
    expected_artifact = (
        f"bin/Debug/{target_framework}/{assembly_name}.dll"
        if append_target_framework_directory
        else f"bin/Debug/{assembly_name}.dll"
    )
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
                "game_folder_build_dependency": game_folder_dependency,
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
    member_access_resolver = None
    if inspector_path is not None:
        member_access_resolver = _run_pre_graph_step(
            failure_stage="compiled_artifact_member_access_dependency",
            action=lambda: _create_run_local_member_access_resolver(
                inspector_path=inspector_path,
                run_root=run_root,
            ),
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            source_revision_binding=source_revision_binding,
            model_admission=model_admission,
            extra={
                "baseline_build": baseline_result,
                "verification_tool_build": verification_tool_build,
                "game_folder_build_dependency": game_folder_dependency,
            },
        )
    artifact_store = ArtifactStore(run_root / "a")
    build_stdout = run_root / "build.stdout.log"
    build_stderr = run_root / "build.stderr.log"
    pending_dry_run: dict[str, Any] | None = None
    runtime_repair_bindings: tuple[dict[str, Any], ...] | None = None
    runtime_repair_evidence: tuple[dict[str, Any], ...] | None = None
    external_model_input_audit: dict[str, Any] | None = None
    local_model_input_audit: dict[str, Any] | None = None
    model_call_count = 0
    initial_patch_model_call_count = 0
    repair_model_call_count = 0
    requirement_coverage_model_audits: list[dict[str, Any]] = []

    def complete_requirement_coverage_json(
        role: str,
        payload: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        nonlocal external_model_input_audit, local_model_input_audit
        nonlocal model_call_count
        data_classes = (
            ("natural_language_request",)
            if role.startswith("requirement_projection")
            else (
                "natural_language_request",
                "retrieved_local_source_excerpts",
                "run_local_api_member_metadata_facts",
            )
        )
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
                requested_data_classes=data_classes,
            )
        exact_payload = dict(payload)
        _assert_no_absolute_local_paths(exact_payload)
        response, provider_request = request_requirement_coverage_model(
            llm=llm,
            payload=exact_payload,
            schema=schema,
            max_output_tokens=ollama_max_output_tokens,
            capture_provider_request=local_ollama,
        )
        if local_ollama:
            observed_identity = identity_reader(llm_base_url, str(ollama_model))
            _validate_ollama_model_identity(
                observed_identity,
                expected_base_url=llm_base_url,
                expected_model=str(ollama_model),
            )
            _assert_ollama_model_identity_stable(
                expected=local_model_identity,
                observed=observed_identity,
            )
        audit = {
            "model_role": role,
            "payload_sha256": _sha256_json(exact_payload),
            "structured_output_sha256": hashlib.sha256(
                response.content.encode("utf-8")
            ).hexdigest(),
            "data_classes": list(data_classes),
            "model_identity": (
                dict(local_model_identity)
                if local_model_identity is not None
                else dict(model_admission.get("destination") or {})
            ),
            "provider_adapter": model_admission.get("provider_adapter"),
            "execution_locality": model_admission.get("execution_locality"),
            "provider_request": provider_request,
            "automatic_provider_fallback": False,
            "automatic_retry": False,
            "absolute_local_paths_present": False,
            "api_key_in_payload": False,
        }
        requirement_coverage_model_audits.append(audit)
        model_call_count += 1
        audit_path = run_root / (
            f"requirement_coverage_model_input_audit_{model_call_count}.json"
        )
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if local_ollama:
            local_model_input_audit = audit
        else:
            external_model_input_audit = audit
        return parse_requirement_coverage_json_object(response.content)

    requirement_coverage_provider = make_requirement_coverage_evidence_provider(
        evidence_provider,
        complete_json=complete_requirement_coverage_json,
        projection_factory=requirement_coverage_projection_factory,
        findings_factory=requirement_coverage_findings_factory,
    )

    def evidence_factory(state: dict[str, Any], feature_data: dict[str, Any]):
        evidence_pack = requirement_coverage_provider.collect(
            query=str(state["user_request"]),
            search_root=f"generated_mods/{source.name}",
            feature_data=feature_data,
        )
        evidence_pack = replace(
            evidence_pack,
            budget_summary={
                **evidence_pack.budget_summary,
                "requirement_coverage_model_audits": [
                    dict(item) for item in requirement_coverage_model_audits
                ],
            },
        )
        if member_access_resolver is None or not evidence_pack.can_generate_patch:
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
                requirement_coverage=None,
                gaps=(
                    *evidence_pack.gaps,
                    "Run-local .NET member semantics remain unresolved.",
                ),
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
        nonlocal runtime_repair_bindings, runtime_repair_evidence
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
        external_evidence = _external_evidence_items(
            list(evidence_pack.get("items") or [])
        )
        generation_binding_registry = dict(
            implementation.get("binding_registry") or {}
        )
        planned_changes = [
            dict(item)
            for item in implementation.get("proposed_changes") or []
            if isinstance(item, dict)
        ]
        feature_spec_ref_path = state.get("artifacts", {}).get("feature_spec")
        feature_spec_ref_hash = state.get("artifact_hashes", {}).get(
            "feature_spec"
        )
        if not isinstance(feature_spec_ref_path, str) or not isinstance(
            feature_spec_ref_hash,
            str,
        ):
            raise LocalEntryError(
                "Patch generation requires the committed FeatureSpec."
            )
        feature_spec = artifact_store.read(
            ArtifactRef(
                feature_id=str(state.get("feature_id") or state["request_id"]),
                artifact_type="feature_spec",
                path=feature_spec_ref_path,
                artifact_hash=feature_spec_ref_hash,
            )
        )["data"]
        repair_plan: dict[str, Any] | None = None
        repair_observation: dict[str, Any] | None = None
        repair_history_constraints: tuple[str, ...] = ()
        repair_spans: tuple[_RuntimeRepairSpan, ...] = ()
        repair_ref_path = state.get("artifacts", {}).get("repair_plan")
        repair_ref_hash = state.get("artifact_hashes", {}).get("repair_plan")
        if isinstance(repair_ref_path, str) and isinstance(repair_ref_hash, str):
            feature_id = str(state.get("feature_id") or state["request_id"])
            repair_plan = artifact_store.read(
                ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="repair_plan",
                    path=repair_ref_path,
                    artifact_hash=repair_ref_hash,
                )
            )["data"]
            build_ref_path = state.get("artifacts", {}).get("build_result")
            build_ref_hash = state.get("artifact_hashes", {}).get("build_result")
            if not isinstance(build_ref_path, str) or not isinstance(
                build_ref_hash,
                str,
            ):
                raise LocalEntryError(
                    "Repair patch generation requires the committed BuildResult."
                )
            build_observation = artifact_store.read(
                ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="build_result",
                    path=build_ref_path,
                    artifact_hash=build_ref_hash,
                )
            )["data"]
            source_proposal = repair_plan.get("source_proposal")
            if not isinstance(source_proposal, Mapping):
                raise LocalEntryError(
                    "Repair patch generation requires its committed source proposal."
                )
            source_proposal_ref = source_proposal.get("ref")
            source_proposal_hash = source_proposal.get("hash")
            if not isinstance(source_proposal_ref, str) or not isinstance(
                source_proposal_hash, str
            ):
                raise LocalEntryError(
                    "Repair source proposal identity is incomplete."
                )
            source_proposal_data = artifact_store.read(
                ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="patch_proposal",
                    path=source_proposal_ref,
                    artifact_hash=source_proposal_hash,
                )
            )["data"]
            repair_history_constraints = _repair_history_fact_constraints(
                patch_proposal=source_proposal_data,
                patch_proposal_hash=source_proposal_hash,
                build_result=build_observation,
                build_result_hash=build_ref_hash,
                run_id=run_id,
                request_id=str(state["request_id"]),
            )
            repair_diagnostics = _unique_repair_diagnostics(
                [
                    {
                        key: item.get(key)
                        for key in (
                            "file",
                            "line",
                            "column",
                            "code",
                            "severity",
                            "message",
                            "error_class",
                        )
                    }
                    for item in build_observation.get("diagnostics") or []
                    if isinstance(item, dict)
                ]
            )
            objective_failed = any(
                item.get("code") == "IA0001" for item in repair_diagnostics
            )
            repair_observation = {
                "failure_class": (
                    "objective_test_failure"
                    if objective_failed
                    else repair_plan.get("failure_class")
                ),
                "hypothesis": (
                    "The project compiled, but the bound objective executable returned "
                    "a nonzero result after observing behavior that did not satisfy the "
                    "request."
                    if objective_failed
                    else repair_plan.get("hypothesis")
                ),
                "diagnostics": repair_diagnostics,
                "objective_verification": (
                    {
                        "command": list(objective_verification_command),
                        "current_source_views": list(
                            _objective_verification_source_views(target_copy)
                        ),
                    }
                    if objective_failed
                    and objective_verification_command is not None
                    else None
                ),
            }
            original_by_binding = {
                str(item.get("edit_binding_id") or ""): item
                for item in planned_changes
                if item.get("edit_binding_id")
            }
            planned_changes = [
                {
                    **dict(
                        original_by_binding.get(
                            str(item.get("edit_binding_id") or ""),
                            {},
                        )
                    ),
                    **dict(item),
                    "change_type": "modify_behavior",
                }
                for item in repair_plan.get("minimal_changes") or []
                if isinstance(item, dict)
            ]
            allowed_repair_bindings = {
                str(value)
                for value in repair_plan.get("allowed_edit_binding_ids") or []
            }
            binding_items = [
                dict(item)
                for item in generation_binding_registry.get("edit_bindings") or []
                if isinstance(item, dict)
            ]
            evidence_by_id = {
                str(item.get("evidence_id") or ""): item
                for item in external_evidence
                if item.get("evidence_id")
            }
            repair_evidence: list[dict[str, Any]] = []
            revised_bindings: list[dict[str, Any]] = []
            for binding in binding_items:
                binding_id = str(binding.get("binding_id") or "")
                if binding_id not in allowed_repair_bindings:
                    continue
                relative_path = str(binding.get("canonical_target_path") or "")
                live_path = (run_root / relative_path).resolve()
                try:
                    live_path.relative_to(run_root.resolve())
                except ValueError as exc:
                    raise LocalEntryError(
                        "Repair edit binding escapes the isolated workspace."
                    ) from exc
                if not live_path.is_file():
                    raise LocalEntryError(
                        "Repair edit binding target is missing from the isolated workspace."
                    )
                live_text, live_hash = _read_utf8_source_snapshot(live_path)
                if len(allowed_repair_bindings) == 1:
                    diagnostics_for_spans: tuple[Mapping[str, Any], ...] | None = None
                    if repair_observation is not None:
                        current_diagnostics = repair_observation.get("diagnostics")
                        if isinstance(current_diagnostics, list):
                            diagnostics_for_spans = tuple(current_diagnostics)
                        elif isinstance(current_diagnostics, tuple):
                            diagnostics_for_spans = current_diagnostics
                    repair_spans = _runtime_repair_spans(
                        live_text,
                        source_hash=live_hash,
                        diagnostic_lines=_runtime_source_diagnostic_lines(
                            diagnostics_for_spans,
                            source_path=live_path,
                            working_root=run_root,
                        ),
                    )
                repair_evidence_id = f"repair_live_{live_hash[:16]}"
                prior = evidence_by_id.get(str(binding.get("evidence_id") or ""), {})
                repair_evidence.append(
                    {
                        **prior,
                        "evidence_id": repair_evidence_id,
                        "document_id": f"repair:{relative_path}",
                        "chunk_id": f"repair:{relative_path}:1:{len(live_text.splitlines())}",
                        "source_ref": f"source://isolated_repair/{relative_path}",
                        "source_path": relative_path,
                        "source_hash": live_hash,
                        "file_hash": live_hash,
                        "doc_hash": live_hash,
                        "excerpt": live_text,
                        "span": {
                            "start_line": 1,
                            "end_line": len(live_text.splitlines()),
                        },
                        "claim_supported": (
                            "Current isolated source after the approved prior apply."
                        ),
                    }
                )
                revised_bindings.append(
                    {
                        **binding,
                        "evidence_id": repair_evidence_id,
                        "source_hash": live_hash,
                        "target_span": {
                            "start_line": 1,
                            "end_line": len(live_text.splitlines()),
                        },
                    }
                )
            if len(revised_bindings) != len(allowed_repair_bindings):
                raise LocalEntryError(
                    "Repair generation could not resolve every allowed edit binding."
                )
            external_evidence = repair_evidence
            generation_binding_registry = {
                **generation_binding_registry,
                "edit_bindings": revised_bindings,
            }
            runtime_repair_bindings = tuple(dict(item) for item in revised_bindings)
            runtime_repair_evidence = tuple(dict(item) for item in repair_evidence)
        obligation_projection = _patch_generation_obligation_projection(
            feature_spec=feature_spec,
            implementation=implementation,
            planned_changes=planned_changes,
        )
        required_change_units = obligation_projection["required_change_units"]
        side_effect_boundaries = obligation_projection["side_effect_boundaries"]
        target_behavior = obligation_projection["target_behavior"]
        acceptance_criteria = obligation_projection["acceptance_criteria"]
        runtime_verification_plan = obligation_projection[
            "runtime_verification_plan"
        ]
        if repair_observation is not None:
            side_effect_boundaries = _repair_provider_constraints(
                base_constraints=side_effect_boundaries,
                diagnostics=repair_observation["diagnostics"],
                history_constraints=repair_history_constraints,
            )
        model_input = {
            "request": state["user_request"],
            "evidence": external_evidence,
            "binding_registry": generation_binding_registry,
            "required_change_units": required_change_units,
            "side_effect_boundaries": side_effect_boundaries,
            "target_behavior": target_behavior,
            "acceptance_criteria": acceptance_criteria,
            "runtime_verification_plan": runtime_verification_plan,
            "repair_observation": repair_observation,
            "repair_span_inventory": [
                span.model_view() for span in repair_spans
            ],
        }
        patch_disclosure_data_classes = (
            _patch_model_input_disclosure_data_classes(model_input)
        )
        if not local_ollama:
            _verify_patch_model_input_disclosure(
                source_disclosure,
                model_input=model_input,
            )
        _assert_no_absolute_local_paths(model_input)
        model_input_audit = {
            "approval_id": source_disclosure.get("approval_id"),
            "provider_adapter": model_admission.get("provider_adapter"),
            "destination": model_admission.get("destination"),
            "approved_data_classes": source_disclosure.get("approved_data_classes"),
            "requested_data_classes": (
                []
                if local_ollama
                else list(patch_disclosure_data_classes)
            ),
            "payload_sha256": _sha256_json(model_input),
            "absolute_local_paths_present": False,
            "api_key_in_payload": False,
            "automatic_provider_fallback": False,
            "automatic_external_retry": False,
            "execution_locality": model_admission.get("execution_locality"),
            "external_disclosure_occurred": not local_ollama,
        }
        selected_llm = (
            repair_llm
            if repair_observation is not None and repair_llm is not None
            else llm
        )
        selected_model = (
            repair_ollama_model
            if repair_observation is not None and repair_ollama_model is not None
            else ollama_model
        )
        selected_model_identity = (
            repair_local_model_identity
            if repair_observation is not None
            and repair_local_model_identity is not None
            else local_model_identity
        )
        selected_model_context_limit = (
            repair_model_context_limit
            if repair_observation is not None
            and repair_model_context_limit is not None
            else local_model_context_limit
        )
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
            nonlocal initial_patch_model_call_count
            nonlocal local_model_input_audit, model_call_count
            nonlocal repair_model_call_count
            if not local_ollama:
                raise LocalEntryError(
                    "Local provider request recorder cannot be used externally."
                )
            model_role = (
                "repair" if repair_observation is not None else "initial_patch"
            )
            remaining_call_budget = _patch_generation_calls_remaining(
                model_role,
                initial_patch_call_count=initial_patch_model_call_count,
                repair_call_count=repair_model_call_count,
            )
            if local_ollama_server_version is None or selected_model_identity is None:
                raise LocalEntryError("Local Ollama environment binding is missing.")
            attempt = {
                **model_input_audit,
                "status": "ready_for_provider_invocation",
                "run_id": run_id,
                "request_id": state["request_id"],
                "model_call_count": model_call_count,
                "remaining_call_budget": remaining_call_budget,
                "output_budget": ollama_max_output_tokens,
                "context_window": ollama_context_window,
                "model_context_limit": selected_model_context_limit,
                "ollama_server_version": local_ollama_server_version,
                "model_identity": dict(selected_model_identity),
                "model_role": model_role,
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
                    "repair_plan_ref": state["artifacts"].get("repair_plan"),
                    "repair_plan_hash": state["artifact_hashes"].get("repair_plan"),
                    "build_result_ref": state["artifacts"].get("build_result"),
                    "build_result_hash": state["artifact_hashes"].get("build_result"),
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
                    "explicit_role_model_routing": repair_ollama_model is not None,
                },
            }
            audit_path = run_root / f"local_model_input_audit_{model_call_count + 1}.json"
            audit_path.write_text(
                json.dumps(attempt, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            (run_root / "local_model_input_audit.json").write_text(
                audit_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            local_model_input_audit = attempt
            model_call_count += 1
            if model_role == "initial_patch":
                initial_patch_model_call_count += 1
            else:
                repair_model_call_count += 1

        def enforce_post_response_model_binding(_: Any) -> None:
            if selected_model_identity is None or selected_model is None:
                raise LocalEntryError("Local Ollama model identity is missing.")
            observed_identity = identity_reader(llm_base_url, selected_model)
            _validate_ollama_model_identity(
                observed_identity,
                expected_base_url=llm_base_url,
                expected_model=selected_model,
            )
            _assert_ollama_model_identity_stable(
                expected=selected_model_identity,
                observed=observed_identity,
            )
            _validate_ollama_context_window(
                observed_identity,
                requested_context_window=ollama_context_window,
            )

        required_validation_by_binding: dict[str, list[str]] = {}
        generation_constraints = list(model_input["side_effect_boundaries"])

        def generate_span_repair(selected_constraints: list[str]):
            if len(required_change_units) != 1 or not repair_spans:
                raise LocalEntryError(
                    "Runtime span repair requires one change unit and one current-source "
                    "span inventory."
                )
            schema = _repair_span_response_schema(repair_spans)
            response = selected_llm.chat(
                [
                    Message(
                        role="system",
                        content=(
                            "Repair the current live source using the objective failure "
                            "observation. Select exactly one supplied runtime selection_id "
                            "and return replacement_text for that complete displayed span. "
                            "Do not return a path, hash, line range, before_text, edit "
                            "binding, or historical source. replacement_text must change "
                            "executable behavior and must not equal display_text. Return "
                            "strict JSON only."
                        ),
                    ),
                    Message(
                        role="user",
                        content=json.dumps(
                            {
                                "request": model_input["request"],
                                "constraints": selected_constraints,
                                "repair_observation": repair_observation,
                                "runtime_spans": model_input[
                                    "repair_span_inventory"
                                ],
                                "required_output_schema": schema,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                ],
                temperature=0.0,
                max_tokens=ollama_max_output_tokens,
                response_format=schema,
                provider_request_recorder=record_local_provider_request,
            )
            enforce_post_response_model_binding(response)
            (run_root / f"repair_span_selection_{model_call_count}.json").write_text(
                json.dumps(
                    {
                        "content": response.content,
                        "model": response.model,
                        "usage": response.usage,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            required_change = required_change_units[0]
            materialized_change = _materialize_repair_span_change(
                response.content,
                spans=repair_spans,
                required_change=required_change,
                expected_validation=tuple(
                    required_change.get("expected_validation") or ()
                ),
            )
            materialized_response = ChatResponse(
                content=json.dumps(
                    {"changes": [materialized_change]},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                model=response.model,
                usage=response.usage,
                raw_response=response.raw_response,
            )
            return LLMExactPatchGenerator(
                _MaterializedRepairPatchLLM(response=materialized_response)
            ).generate(
                user_request=str(model_input["request"]),
                evidence_items=list(model_input["evidence"]),
                binding_registry=dict(model_input["binding_registry"]),
                constraints=selected_constraints,
                target_behavior=str(model_input["target_behavior"]),
                acceptance_criteria=list(model_input["acceptance_criteria"]),
                runtime_verification_plan=list(
                    model_input["runtime_verification_plan"]
                ),
                required_change_units=required_change_units,
                required_validation_by_binding=required_validation_by_binding,
                require_native_schema=False,
            )

        def generate_patch(selected_constraints: list[str]):
            if repair_observation is not None and local_ollama:
                return generate_span_repair(selected_constraints)
            return generator.generate(
                user_request=str(model_input["request"]),
                evidence_items=list(model_input["evidence"]),
                binding_registry=dict(model_input["binding_registry"]),
                constraints=selected_constraints,
                target_behavior=str(model_input["target_behavior"]),
                acceptance_criteria=list(model_input["acceptance_criteria"]),
                runtime_verification_plan=list(
                    model_input["runtime_verification_plan"]
                ),
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

        try:
            generated = generate_patch(generation_constraints)
        except PatchGenerationError as exc:
            model_role = (
                "repair" if repair_observation is not None else "initial_patch"
            )
            correction_allowed = (
                _local_patch_generation_correction_allowed(
                    model_role,
                    initial_patch_call_count=initial_patch_model_call_count,
                )
                if local_ollama
                else True
            )
            failure_record = {
                "failure_type": type(exc).__name__,
                "failure_message": str(exc),
                "diagnostic_content": getattr(exc, "diagnostic_content", None),
                "diagnostics": dict(getattr(exc, "diagnostics", {}) or {}),
                "model_call_count_after_failure": model_call_count,
                "correction_allowed": correction_allowed,
            }
            failure_path = (
                run_root
                / f"patch_generation_failure_{model_call_count}.json"
            )
            failure_path.write_text(
                json.dumps(
                    failure_record,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            if not correction_allowed:
                raise
            correction_constraint = (
                "The previous response failed deterministic patch validation: "
                f"{exc}. Return one corrected response using the same schema, "
                "required change units, evidence, and edit bindings. Do not "
                "repeat the invalid patch."
            )
            generated = generate_patch(
                [
                    *generation_constraints,
                    correction_constraint,
                ]
            )
        if local_ollama and generated.model != selected_model:
            raise LocalEntryError("OLLAMA_RESPONSE_MODEL_IDENTITY_MISMATCH")
        overlaid_changes = _overlay_generated_patch_changes_on_plan(
            planned_changes=planned_changes,
            generated_changes=generated.changes,
        )
        changes: list[dict[str, Any]] = []
        for overlaid_change in overlaid_changes:
            changes.append(
                {
                    **overlaid_change,
                    "generation": {
                        "provider": settings.llm.provider,
                        "model": generated.model,
                        "model_digest": (
                            selected_model_identity.get("digest")
                            if selected_model_identity is not None
                            else None
                        ),
                        "usage": generated.usage,
                        "api_key_env": None if local_ollama else api_key_env,
                    },
                }
            )
        return tuple(changes)

    def proposal_review_context_factory(
        _state: dict[str, Any],
        implementation: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if runtime_repair_bindings is None or runtime_repair_evidence is None:
            raise LocalEntryError(
                "Repair review context is unavailable before Repair generation."
            )
        return _repair_review_context(
            implementation,
            evidence_pack,
            runtime_bindings=runtime_repair_bindings,
            runtime_evidence=runtime_repair_evidence,
        )

    def dry_run_factory(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal pending_dry_run
        execution_implementation = (
            _implementation_with_runtime_repair_bindings(
                implementation,
                runtime_bindings=runtime_repair_bindings,
            )
            if runtime_repair_bindings is not None
            else implementation
        )
        pending_dry_run = applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=execution_implementation,
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
        execution_implementation = (
            _implementation_with_runtime_repair_bindings(
                implementation,
                runtime_bindings=runtime_repair_bindings,
            )
            if runtime_repair_bindings is not None
            else implementation
        )
        approved_diff_hash, human_semantic_decision = _read_exact_diff_approval(
            diff_approval_reader,
            pending_dry_run,
        )
        return applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=execution_implementation,
            review=review,
            allow_write=True,
            approved_diff_hash=approved_diff_hash,
            human_semantic_decision=human_semantic_decision,
        )

    def build_result_factory(feature_id: str, input_execution_mode: str | None):
        final_command = (
            objective_verification_command
            if objective_verification_command is not None
            else nuget_build_profile.build_command
        )
        profile = BuildProfile(
            profile_id=nuget_build_profile.profile_id,
            build_system="dotnet",
            working_directory=str(target_copy),
            command=final_command,
            timeout_seconds=nuget_build_profile.timeout_seconds,
            expected_artifacts=(expected_artifact,),
        )

        def command_runner(selected: BuildProfile) -> BuildCommandResult:
            if selected.command != final_command:
                raise LocalEntryError("Final build command does not match the bound profile.")
            completed = _run_nuget_isolated_build(nuget_build_profile)
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.exit_code
            duration_ms = completed.duration_ms
            if exit_code == 0 and objective_verification_command is not None:
                objective = _run_nuget_isolated_verification_command(
                    nuget_build_profile,
                    objective_verification_command,
                )
                changed_files = tuple(
                    str(path)
                    for path in (
                        pending_dry_run.get("changed_files")
                        if isinstance(pending_dry_run, Mapping)
                        else ()
                    )
                    or ()
                )
                objective = _bind_objective_failure_to_single_changed_file(
                    objective,
                    changed_files,
                )
                stdout = _join_build_phase_output(
                    ("nuget-isolated build", stdout),
                    ("objective verification", objective.stdout),
                )
                stderr = _join_build_phase_output(
                    ("nuget-isolated build", stderr),
                    ("objective verification", objective.stderr),
                )
                exit_code = objective.exit_code
                duration_ms += objective.duration_ms
            build_stdout.write_text(stdout, encoding="utf-8")
            build_stderr.write_text(stderr, encoding="utf-8")
            return BuildCommandResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )

        build_result = BuildAdapter().run_local(
            feature_id=feature_id,
            profile=profile,
            command_runner=command_runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )
        return _canonicalize_run_local_build_diagnostic_paths(
            build_result,
            run_root=run_root,
            isolated_target_root=target_copy,
        )

    direct_stagger_admission = runtime_admission.get("stagger_acceptance")
    direct_stagger_config = (
        direct_stagger_admission.get("config")
        if isinstance(direct_stagger_admission, Mapping)
        else None
    )
    raw_runtime_evidence_factory = (
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
    runtime_evidence_factory = (
        _bind_owner_validated_runtime_evidence_factory(
            raw_runtime_evidence_factory,
            settings=settings,
            allow_game_launch=allow_game_launch,
            runtime_plugin_destination=runtime_plugin_destination,
            allow_game_directory_write=allow_game_directory_write,
            expected_runtime_admission=runtime_admission,
        )
        if raw_runtime_evidence_factory is not None
        and runtime_plugin_destination is not None
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
        "objective_verification_command": (
            list(objective_verification_command)
            if objective_verification_command is not None
            else None
        ),
        "model": settings.llm.model,
        "model_admission": model_admission,
        "local_model_identity": local_model_identity,
        "repair_local_model_identity": repair_local_model_identity,
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
            "source": (
                str(source_bepinex_dir)
                if source_bepinex_dir is not None
                else None
            ),
            "isolated_copy": (
                str(isolated_bepinex_dir)
                if isolated_bepinex_dir is not None
                else None
            ),
            "build_uses_isolated_copy": isolated_bepinex_dir is not None,
            "game_folder": (
                dict(game_folder_dependency)
                if game_folder_dependency is not None
                else None
            ),
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

    product_request = ProductExecutionRequestV1(
        contract_version="1",
        run_id=run_id,
        request_id=request_id,
        user_request=description,
        target_domain="gtfo",
        target_mod=source.name,
        requested_completion_scope=(
            "runtime_workflow" if run_gtfo_runtime else "compile_only"
        ),
        repair_budget=2,
        isolated_workspace_root=str(run_root),
        isolated_target_root=str(target_copy.resolve()),
        source_root=str(source),
        artifact_store_root=str(artifact_store.root),
        source_snapshot_sha256=initial_source_snapshot_sha256,
        isolated_source_snapshot_sha256=_source_snapshot_sha256(
            _source_snapshot(target_copy)
        ),
        input_bindings=(
            ProductExecutionInputBindingV1.create(
                "source_revision_binding",
                dict(source_revision_binding) if source_revision_binding else None,
            ),
            ProductExecutionInputBindingV1.create(
                "source_disclosure", source_disclosure
            ),
            ProductExecutionInputBindingV1.create(
                "model_admission", model_admission
            ),
            ProductExecutionInputBindingV1.create(
                "runtime_admission", runtime_admission
            ),
        ),
        completion_classification=tuple(
            sorted(
                (
                    (str(key), value)
                    for key, value in dict(completion_classification or {}).items()
                ),
                key=lambda item: item[0].encode("utf-8"),
            )
        ),
        confirmed_isolated_write=True,
        allow_build=True,
    )
    product_adapters = ProductExecutionAdaptersV1(
        evidence_pack_factory=evidence_factory,
        planning_target_selection_factory=(
            lambda _feature, _evidence: planning_target_evidence_ids
        )
        if planning_target_evidence_ids
        else None,
        patch_change_factory=patch_change_factory,
        dry_run_factory=dry_run_factory,
        isolated_apply_factory=isolated_apply_factory,
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
        compiled_artifact_verifier=active_compiled_artifact_verifier,
        source_change_verifier=source_change_verifier,
        proposal_review_context_factory=proposal_review_context_factory,
    )
    product_preflight = preflight_product_execution(
        product_request,
        product_adapters,
        artifact_store,
        strict_git_admission=source_git_admission,
    )
    if product_preflight.preflight_status != "ready":
        raise LocalEntryError(
            "Product execution preflight was blocked: "
            + "; ".join(item.message for item in product_preflight.blockers)
        )
    with _working_directory(run_root):
        try:
            product_result = execute_product_execution(
                product_preflight,
                product_adapters,
                artifact_store,
                strict_git_admission=source_git_admission,
            )
        except ProductExecutionContractError:
            raise
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
            raise LocalEntryError(
                f"Controlled product executor failed: {type(exc).__name__}: {exc}"
            ) from exc

    product_result_projection = product_result.to_dict()
    output_paths = {
        item.artifact_role: item.artifact_ref.path for item in product_result.outputs
    }
    validation_details = {
        item.detail_kind: item.payload
        for item in product_result.validation_facts.details
    }
    variant_projection = product_result.variant_result.to_dict()
    build_summary = {
        "status": variant_projection.get("build_status", "not_reached"),
        "claims_real_build_success": variant_projection.get(
            "claims_real_build_success"
        ),
    }
    runtime_summary = {
        key: variant_projection.get(key)
        for key in ("runtime_status", "eval_verdict", "final_status")
        if key in variant_projection
    }
    runtime_chain_roles = (
        "build_result",
        "runtime_evidence",
        "eval_report",
        "workflow_summary",
    )
    runtime_verification_chain = {
        "requested": run_gtfo_runtime,
        "artifact_refs": {
            role: output_paths.get(role) for role in runtime_chain_roles
        },
        "workflow_chain_completed": bool(
            run_gtfo_runtime
            and product_result.execution_disposition == "succeeded"
            and all(output_paths.get(role) for role in runtime_chain_roles)
        ),
    }
    output_readback = validation_details.get("output_readback") or []
    isolated_apply_payload = next(
        (
            item.get("data")
            for item in output_readback
            if isinstance(item, Mapping)
            and item.get("artifact_type") == "isolated_apply_result"
        ),
        {},
    )
    actual_write_performed = bool(
        isinstance(isolated_apply_payload, Mapping)
        and isolated_apply_payload.get("actual_write_performed") is True
    )
    patch_payload_parser_entered = "patch_proposal" in output_paths
    selected_classification = dict(product_request.completion_classification)
    final_artifact_verification = validation_details.get("compiled_artifact")
    source_change_verification = validation_details.get("source_change")
    canonical_source_unchanged = (
        product_result.validation_facts.canonical_source_status == "passed"
    )

    summary = {
        "run_id": run_id,
        "current_stage": product_result.terminal_node,
        "feature_id": product_result.feature_id,
        "blockers": [item.to_dict() for item in product_result.blockers],
        "artifacts": output_paths,
        "build_summary": build_summary,
        "runtime_summary": runtime_summary,
        "runtime_admission": runtime_admission,
        "runtime_verification_chain": runtime_verification_chain,
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
        "repair_local_model_identity": repair_local_model_identity,
        "verification_tool_build": verification_tool_build,
        "baseline_artifact_verification": baseline_result.get(
            "compiled_artifact_verification"
        ),
        "final_artifact_verification": final_artifact_verification,
        "canonical_source_unchanged": canonical_source_unchanged,
        "initial_isolated_source_snapshot": initial_source_snapshot,
        "final_isolated_source_snapshot": (
            source_change_verification.get("final_snapshot")
            if isinstance(source_change_verification, Mapping)
            else None
        ),
        "source_change_verification": source_change_verification,
        "completion_classification": selected_classification,
        "product_execution_result": product_result_projection,
    }
    try:
        _persist_graph_terminal_result(
            run_root=run_root,
            run_id=run_id,
            request_id=request_id,
            summary=summary,
            model_call_count=model_call_count,
            patch_payload_parser_entered=patch_payload_parser_entered,
            actual_write_performed=actual_write_performed,
        )
    except Exception as exc:
        raise ProductExecutionPresentationError(
            product_execution_result=product_result,
            failure_class=type(exc).__name__,
            failure_message=str(exc) or type(exc).__name__,
            sink="run_manifest_and_result_json",
        ) from exc
    return summary


def _load_runtime_continuation_handoff(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    resume_id: str | None = None,
    attempt_policy: InitialAttemptV1 | ObservationRetryAttemptV1 | AcceptedResumeRecoveryAttemptV1 | None = None,
    require_manifest: bool = True,
    allow_blocked_resume: bool = False,
    require_current_build_output: bool = True,
) -> _RuntimeContinuationHandoff:
    attempt = InitialAttemptV1() if attempt_policy is None else attempt_policy
    if not isinstance(
        attempt,
        (InitialAttemptV1, ObservationRetryAttemptV1, AcceptedResumeRecoveryAttemptV1),
    ):
        raise LocalEntryError("Runtime continuation attempt policy is not registered.")
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
        if isinstance(attempt, ObservationRetryAttemptV1):
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
        elif isinstance(attempt, AcceptedResumeRecoveryAttemptV1):
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
        isinstance(attempt, ObservationRetryAttemptV1)
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
        attempt_policy=attempt,
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


def _preflight_runtime_operation_compatibility(
    *,
    run_root: str | Path,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    artifact_store_root: str | Path | None = None,
    resume_id: str | None = None,
    attempt_policy: InitialAttemptV1 | ObservationRetryAttemptV1 | AcceptedResumeRecoveryAttemptV1 | None = None,
    runtime_output_root: str | Path | None = None,
    settings_path: str | Path | None = None,
    runtime_plugin_destination: str | Path | None = None,
    approved_by: str | None = None,
    injected_runtime_admission: Mapping[str, Any] | None = None,
    completion_scope: str = RUNTIME_WORKFLOW_COMPLETION,
    advisory_attempt_mode: str | None = None,
) -> dict[str, Any]:
    """Read-validate one Runtime continuation without writing or entering graph."""

    if advisory_attempt_mode not in {
        None,
        "initial",
        "observation_retry",
        "accepted_resume_recovery",
    }:
        raise LocalEntryError("Runtime advisory attempt mode is not registered.")
    if advisory_attempt_mode is not None and attempt_policy is not None:
        raise LocalEntryError(
            "Runtime advisory preflight cannot accept an execution attempt binding."
        )
    attempt = InitialAttemptV1() if attempt_policy is None else attempt_policy
    if not isinstance(
        attempt,
        (InitialAttemptV1, ObservationRetryAttemptV1, AcceptedResumeRecoveryAttemptV1),
    ):
        raise LocalEntryError("Runtime continuation attempt policy is not registered.")
    is_retry = (
        advisory_attempt_mode == "observation_retry"
        if advisory_attempt_mode is not None
        else isinstance(attempt, ObservationRetryAttemptV1)
    )
    is_recovery = (
        advisory_attempt_mode == "accepted_resume_recovery"
        if advisory_attempt_mode is not None
        else isinstance(attempt, AcceptedResumeRecoveryAttemptV1)
    )
    if completion_scope not in {
        RUNTIME_EVIDENCE_ONLY_COMPLETION,
        RUNTIME_WORKFLOW_COMPLETION,
    }:
        raise LocalEntryError("Runtime execution completion scope is not registered.")
    if completion_scope == RUNTIME_EVIDENCE_ONLY_COMPLETION:
        if not isinstance(attempt, InitialAttemptV1):
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
    if is_retry and runtime_output_root is None:
        raise LocalEntryError(
            "Runtime observation retry requires runtime_output_root."
        )
    if runtime_output_root is not None and not Path(runtime_output_root).is_absolute():
        raise LocalEntryError(
            "Stagger Runtime output root must be absolute."
        )
    if is_retry and (
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
        attempt_policy=attempt,
        require_manifest=completion_scope != RUNTIME_EVIDENCE_ONLY_COMPLETION,
        allow_blocked_resume=(
            completion_scope == RUNTIME_EVIDENCE_ONLY_COMPLETION
            or is_retry
            or is_recovery
        ),
    )
    if advisory_attempt_mode is not None and (is_retry or is_recovery):
        checkpoint_store = WorkflowCheckpointStore(handoff.artifact_store)
        if not isinstance(resume_id, str) or not resume_id:
            raise LocalEntryError(
                "Runtime retry or recovery advisory requires the exact resume_id."
            )
        if is_retry:
            (
                recovery_decision,
                recovery_report_ref,
                prior_runtime_ref,
                prior_repair_plan_ref,
                observation_retry_binding,
            ) = checkpoint_store.preflight_runtime_observation_retry(
                handoff.checkpoint_ref,
                resume_id=resume_id,
            )
            handoff = replace(
                handoff,
                recovery_decision=recovery_decision,
                recovery_resume_report_ref=recovery_report_ref,
                prior_runtime_evidence_ref=prior_runtime_ref,
                prior_repair_plan_ref=prior_repair_plan_ref,
                observation_retry_binding=observation_retry_binding,
                resume_readiness=recovery_decision,
            )
        else:
            recovery_decision, recovery_report_ref = (
                checkpoint_store.preflight_accepted_resume_recovery(
                    handoff.checkpoint_ref,
                    resume_id=resume_id,
                )
            )
            handoff = replace(
                handoff,
                recovery_decision=recovery_decision,
                recovery_resume_report_ref=recovery_report_ref,
                resume_readiness=recovery_decision,
            )
    if completion_scope == RUNTIME_EVIDENCE_ONLY_COMPLETION:
        runtime_admission = dict(injected_runtime_admission)
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
    if is_recovery and accepted_output_binding is not None:
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
        if is_retry
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
                if is_retry
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
                    if is_retry
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
        if is_retry:
            if runtime_output_report is None:
                raise LocalEntryError(
                    "Runtime observation retry output binding is missing."
                )
            runtime_profile["runtime_observation_retry_output"] = (
                runtime_output_report
            )
            runtime_profile["prior_restoration"] = retry_restoration
        if (
            (is_retry or is_recovery)
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
        and not is_retry
        and not is_recovery
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
                if is_retry
                else (
                    "accepted_resume_recovery"
                    if is_recovery
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
            if isinstance(
                attempt,
                AcceptedResumeRecoveryAttemptV1,
            )
            or is_recovery
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
            if is_retry
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


def _runtime_operation_checkpoint_identity(
    *,
    artifact_store_root: str | Path,
    checkpoint_ref: ArtifactRef,
) -> VerificationCheckpointIdentityV1:
    store = ArtifactStore(Path(artifact_store_root).resolve())
    checkpoint = store.read(checkpoint_ref)["data"]
    if not isinstance(checkpoint, Mapping):
        raise LocalEntryError("Verification checkpoint payload is invalid.")
    try:
        return VerificationCheckpointIdentityV1(
            checkpoint_id=str(checkpoint["checkpoint_id"]),
            run_id=str(checkpoint["run_id"]),
            request_id=str(checkpoint["request_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LocalEntryError(
            "Verification checkpoint identity is unavailable."
        ) from exc


def _resolve_legacy_runtime_attempt_policy(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    resume_id: str | None,
    approved_by: str | None,
    retry_runtime_observation: bool,
    recover_accepted_resume: bool,
) -> InitialAttemptV1 | ObservationRetryAttemptV1 | AcceptedResumeRecoveryAttemptV1:
    """Normalize legacy selectors once into an exact registered attempt."""

    if retry_runtime_observation and recover_accepted_resume:
        raise LocalEntryError("Runtime retry and recovery selectors cannot be mixed.")
    if not retry_runtime_observation and not recover_accepted_resume:
        return InitialAttemptV1()
    if not isinstance(resume_id, str) or not resume_id:
        raise LocalEntryError("Runtime retry or recovery requires the exact resume_id.")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise LocalEntryError("Runtime retry or recovery requires approved_by.")
    root = Path(run_root).resolve()
    store_root = (
        Path(artifact_store_root).resolve()
        if artifact_store_root is not None
        else (root / "a").resolve()
    )
    checkpoint_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="workflow_checkpoint",
        path=str(Path(checkpoint_path).resolve()),
        artifact_hash=checkpoint_hash,
    )
    checkpoint_store = WorkflowCheckpointStore(ArtifactStore(store_root))
    try:
        if retry_runtime_observation:
            (
                decision,
                _report_ref,
                prior_runtime_ref,
                repair_plan_ref,
                retry_binding,
            ) = checkpoint_store.preflight_runtime_observation_retry(
                checkpoint_ref,
                resume_id=resume_id,
            )
            remaining_before = retry_binding.get(
                "retry_budget_remaining_before_attempt"
            )
            if (
                not decision.allowed
                or type(remaining_before) is not int
                or type(retry_binding.get("retry_number")) is not int
                or type(retry_binding.get("retry_budget")) is not int
            ):
                raise LocalEntryError(
                    "Runtime observation retry attempt binding is incomplete."
                )
            return ObservationRetryAttemptV1(
                prior_runtime_evidence_ref=prior_runtime_ref,
                repair_plan_ref=repair_plan_ref,
                retry_number=retry_binding["retry_number"],
                retry_budget=retry_binding["retry_budget"],
                retry_budget_remaining=max(remaining_before - 1, 0),
                current_attempt_approved_by=approved_by,
            )
        decision, report_ref = checkpoint_store.preflight_accepted_resume_recovery(
            checkpoint_ref,
            resume_id=resume_id,
        )
        if not decision.allowed:
            raise LocalEntryError("Accepted resume recovery is not allowed.")
        return AcceptedResumeRecoveryAttemptV1(
            accepted_resume_report_ref=report_ref,
            recovery_of_resume_id=resume_id,
            current_attempt_approved_by=approved_by,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise LocalEntryError(
            f"Legacy Runtime attempt normalization failed: {exc}"
        ) from exc


def _typed_runtime_preflight(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path,
    spec: VerificationOperationSpec,
) -> tuple[VerificationOperationPreflightResultV1, dict[str, Any] | None]:
    try:
        declaration = resolve_verification_operation(spec)
    except (TypeError, ValueError) as exc:
        return (
            _verification_preflight_result(
                envelope=None,
                operation_kind=None,
                operation_contract_version=None,
                status="blocked",
                failure_stage="authorization",
                identity_resolution_status="unresolved",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "authorization",
                            "code": "VERIFICATION_OPERATION_UNSUPPORTED",
                            "message": str(exc),
                        }
                    ],
                    default_stage="authorization",
                ),
            ),
            None,
        )
    if declaration.operation_kind == VERIFICATION_BUILD_KIND:
        return (
            _verification_preflight_result(
                envelope=None,
                operation_kind=None,
                operation_contract_version=None,
                status="blocked",
                failure_stage="authorization",
                identity_resolution_status="unresolved",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "authorization",
                            "code": "RUNTIME_OPERATION_REQUIRED",
                            "message": "Runtime public entry does not accept Build operations.",
                        }
                    ],
                    default_stage="authorization",
                ),
            ),
            None,
        )
    protocol = spec.protocol_binding
    try:
        checkpoint_identity = (
            None
            if not declaration.requires_checkpoint_identity
            else _runtime_operation_checkpoint_identity(
                artifact_store_root=artifact_store_root,
                checkpoint_ref=protocol.checkpoint_ref,
            )
        )
        envelope = project_verification_operation(
            spec,
            checkpoint_identity=checkpoint_identity,
        )
    except (LocalEntryError, OSError, TypeError, ValueError) as exc:
        return (
            _verification_preflight_result(
                envelope=None,
                operation_kind=declaration.operation_kind,
                operation_contract_version=declaration.operation_contract_version,
                status="blocked",
                failure_stage="admission",
                identity_resolution_status="declaration_resolved",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "admission",
                            "code": "VERIFICATION_OPERATION_IDENTITY_UNAVAILABLE",
                            "message": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                    default_stage="admission",
                ),
            ),
            None,
        )
    legacy_projection: dict[str, Any]
    try:
        if declaration.operation_kind == EVIDENCE_CONSOLIDATION_KIND:
            legacy_projection = _preflight_runtime_evidence_consolidation(
                verification_operation=spec,
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
            )
            ready = legacy_projection["status"] == (
                "READY_FOR_RUNTIME_EVIDENCE_CONSOLIDATION"
            )
        elif declaration.operation_kind == RUNTIME_TERMINALIZATION_KIND:
            variant = spec.variant_payload
            legacy_projection = _preflight_runtime_terminal_continuation(
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
                accepted_resume_report_path=(
                    protocol.accepted_resume_report_ref.path
                ),
                accepted_resume_report_hash=(
                    protocol.accepted_resume_report_ref.artifact_hash
                ),
                runtime_evidence_path=variant.runtime_evidence_ref.path,
                runtime_evidence_hash=variant.runtime_evidence_ref.artifact_hash,
                resume_id=protocol.resume_id,
                approved_by=protocol.approved_by,
            )
            ready = legacy_projection["status"] == (
                "READY_FOR_RUNTIME_TERMINALIZATION"
            )
        elif declaration.shape_id == "runtime_execution_initial_evidence_only":
            legacy_projection = _preflight_runtime_operation_compatibility(
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
                resume_id=protocol.resume_id,
                approved_by=protocol.approved_by,
                injected_runtime_admission=spec.variant_payload.runtime_action_scope,
                completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
            )
            ready = legacy_projection["status"] == "READY_FOR_RUNTIME_EXECUTION"
        else:
            handoff = _load_runtime_continuation_handoff(
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
                resume_id=protocol.resume_id,
                attempt_policy=spec.attempt_policy,
                require_manifest=True,
            )
            ready = bool(
                handoff.resume_readiness is not None
                and handoff.resume_readiness.allowed
            )
            legacy_projection = {
                "status": "READY_FOR_RUNTIME_EXECUTION" if ready else "BLOCKED",
                "writes_performed": False,
                "graph_invoked": False,
                "identity": {
                    "run_id": handoff.checkpoint["run_id"],
                    "request_id": handoff.checkpoint["request_id"],
                    "feature_id": handoff.checkpoint["feature_id"],
                },
                "checkpoint": _artifact_ref_projection(handoff.checkpoint_ref),
                "resume_decision": (
                    None
                    if handoff.resume_readiness is None
                    else handoff.resume_readiness.to_dict()
                ),
                "blockers": (
                    []
                    if handoff.resume_readiness is None
                    else list(handoff.resume_readiness.blockers)
                ),
            }
    except (LocalEntryError, OSError, TypeError, ValueError) as exc:
        return (
            _verification_preflight_result(
                envelope=envelope,
                operation_kind=envelope.operation_kind,
                operation_contract_version=envelope.operation_contract_version,
                status="blocked",
                failure_stage="admission",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "admission",
                            "code": "VERIFICATION_RUNTIME_ADMISSION_FAILED",
                            "message": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                    default_stage="admission",
                ),
            ),
            None,
        )
    machine_result = _verification_preflight_result(
        envelope=envelope,
        operation_kind=envelope.operation_kind,
        operation_contract_version=envelope.operation_contract_version,
        status="ready" if ready else "blocked",
        failure_stage=None if ready else "admission",
        blockers=(
            ()
            if ready
            else _verification_blockers(
                list(legacy_projection.get("blockers") or ()),
                default_stage="admission",
            )
        ),
        audit_snapshot={"writes_performed": False},
    )
    return machine_result, legacy_projection


def _legacy_runtime_evidence_only_spec(
    *,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    resume_id: str,
    approved_by: str,
    injected_runtime_admission: Mapping[str, Any] | None,
) -> VerificationOperationSpec:
    """Normalize the exact legacy C6.2 selector into the typed contract."""

    try:
        return VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=NewRuntimeResumeProtocolBindingV1(
                checkpoint_ref=ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="workflow_checkpoint",
                    path=str(Path(checkpoint_path).resolve()),
                    artifact_hash=checkpoint_hash,
                ),
                resume_id=resume_id,
                approved_by=approved_by,
            ),
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
                runtime_action_scope=_runtime_resume_admission_snapshot(
                    injected_runtime_admission
                ),
            ),
        )
    except (TypeError, ValueError) as exc:
        raise LocalEntryError(
            "Runtime execution identity contains a non-JSON value."
        ) from exc


def _legacy_runtime_terminalization_spec(
    *,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    accepted_resume_report_path: str | Path,
    accepted_resume_report_hash: str,
    runtime_evidence_path: str | Path,
    runtime_evidence_hash: str,
    resume_id: str,
    approved_by: str,
) -> VerificationOperationSpec:
    """Normalize the exact legacy C6.3 selector into the typed contract."""

    return VerificationOperationSpec(
        operation_kind=RUNTIME_TERMINALIZATION_KIND,
        operation_contract_version=RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
        attempt_policy=InitialAttemptV1(),
        protocol_binding=VerificationProtocolBinding(
            checkpoint_ref=ArtifactRef(
                feature_id=feature_id,
                artifact_type="workflow_checkpoint",
                path=str(Path(checkpoint_path).resolve()),
                artifact_hash=checkpoint_hash,
            ),
            accepted_resume_report_ref=ArtifactRef(
                feature_id=feature_id,
                artifact_type="resume_report",
                path=str(Path(accepted_resume_report_path).resolve()),
                artifact_hash=accepted_resume_report_hash,
            ),
            resume_id=resume_id,
            approved_by=approved_by,
        ),
        variant_payload=RuntimeTerminalizationOperationV1(
            runtime_evidence_ref=ArtifactRef(
                feature_id=feature_id,
                artifact_type="runtime_evidence",
                path=str(Path(runtime_evidence_path).resolve()),
                artifact_hash=runtime_evidence_hash,
            )
        ),
    )


def preflight_local_runtime(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None = None,
    verification_operation: VerificationOperationSpec | None = None,
    feature_id: str | None = None,
    checkpoint_path: str | Path | None = None,
    checkpoint_hash: str | None = None,
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
    accepted_resume_report_path: str | Path | None = None,
    accepted_resume_report_hash: str | None = None,
    runtime_evidence_path: str | Path | None = None,
    runtime_evidence_hash: str | None = None,
) -> dict[str, Any] | VerificationOperationPreflightResultV1:
    """Normalize legacy selectors once or preflight one typed Runtime operation."""

    typed_call = verification_operation is not None
    legacy_identity_values = (
        feature_id,
        checkpoint_path,
        checkpoint_hash,
        resume_id,
        approved_by,
        injected_runtime_admission,
        accepted_resume_report_path,
        accepted_resume_report_hash,
        runtime_evidence_path,
        runtime_evidence_hash,
    )
    legacy_scope_selected = any(
        (
            recover_accepted_resume,
            retry_runtime_observation,
            runtime_evidence_only,
            runtime_terminalization_only,
            runtime_output_root is not None,
            settings_path is not None,
            runtime_plugin_destination is not None,
        )
    )
    if typed_call:
        if artifact_store_root is None:
            return _verification_preflight_result(
                envelope=None,
                operation_kind=None,
                operation_contract_version=None,
                status="blocked",
                failure_stage="authorization",
                identity_resolution_status="unresolved",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "authorization",
                            "code": "VERIFICATION_STORE_ROOT_REQUIRED",
                            "message": "Typed Runtime operation requires artifact_store_root.",
                        }
                    ],
                    default_stage="authorization",
                ),
            )
        if legacy_scope_selected or any(
            value is not None for value in legacy_identity_values
        ):
            return _verification_preflight_result(
                envelope=None,
                operation_kind=None,
                operation_contract_version=None,
                status="blocked",
                failure_stage="authorization",
                identity_resolution_status="unresolved",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "authorization",
                            "code": "VERIFICATION_OPERATION_LEGACY_MIXED",
                            "message": "Typed Runtime operation cannot mix legacy selectors.",
                        }
                    ],
                    default_stage="authorization",
                ),
            )
        result, _ = _typed_runtime_preflight(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            spec=verification_operation,
        )
        return result
    if feature_id is None or checkpoint_path is None or checkpoint_hash is None:
        raise TypeError("Legacy Runtime identity inputs are incomplete.")
    if runtime_terminalization_only:
        if (
            runtime_evidence_only
            or recover_accepted_resume
            or retry_runtime_observation
            or runtime_output_root is not None
            or settings_path is not None
            or runtime_plugin_destination is not None
            or injected_runtime_admission is not None
            or accepted_resume_report_path is None
            or accepted_resume_report_hash is None
            or runtime_evidence_path is None
            or runtime_evidence_hash is None
            or resume_id is None
            or approved_by is None
        ):
            raise LocalEntryError(
                "Runtime Store-only continuation inputs are incomplete or mixed."
            )
        exact_spec = _legacy_runtime_terminalization_spec(
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
        machine_result, legacy_result = _typed_runtime_preflight(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            spec=exact_spec,
        )
        if legacy_result is None:
            legacy_result = {
                "status": "BLOCKED",
                "command": "preflight-runtime-terminalization",
                "writes_performed": False,
                "graph_invoked": False,
                "checkpoint_consumed": False,
                "blockers": [item.to_dict() for item in machine_result.blockers],
            }
        legacy_result["verification_operation_preflight_result"] = (
            machine_result.to_dict()
        )
    elif runtime_evidence_only:
        if (
            recover_accepted_resume
            or retry_runtime_observation
            or runtime_output_root is not None
            or settings_path is not None
            or runtime_plugin_destination is not None
            or accepted_resume_report_path is not None
            or accepted_resume_report_hash is not None
            or runtime_evidence_path is not None
            or runtime_evidence_hash is not None
            or resume_id is None
            or approved_by is None
            or artifact_store_root is None
        ):
            raise LocalEntryError(
                "RuntimeEvidence-only preflight inputs are incomplete or mixed."
            )
        exact_spec = _legacy_runtime_evidence_only_spec(
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            resume_id=resume_id,
            approved_by=approved_by,
            injected_runtime_admission=injected_runtime_admission,
        )
        machine_result, legacy_result = _typed_runtime_preflight(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            spec=exact_spec,
        )
        if legacy_result is None:
            legacy_result = {
                "status": "BLOCKED",
                "command": "preflight-runtime-evidence-only",
                "writes_performed": False,
                "graph_invoked": False,
                "checkpoint_consumed": False,
                "resume_report_created": False,
                "runtime_evidence_created": False,
                "process_launched": False,
                "dll_copied": False,
                "blockers": [item.to_dict() for item in machine_result.blockers],
            }
        legacy_result["verification_operation_preflight_result"] = (
            machine_result.to_dict()
        )
    else:
        if retry_runtime_observation and recover_accepted_resume:
            raise LocalEntryError(
                "Runtime retry and recovery selectors cannot be mixed."
            )
        advisory_attempt_mode = (
            "observation_retry"
            if retry_runtime_observation
            else "accepted_resume_recovery"
            if recover_accepted_resume
            else "initial"
        )
        legacy_result = _preflight_runtime_operation_compatibility(
            run_root=run_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            artifact_store_root=artifact_store_root,
            resume_id=resume_id,
            attempt_policy=None,
            runtime_output_root=runtime_output_root,
            settings_path=settings_path,
            runtime_plugin_destination=runtime_plugin_destination,
            approved_by=approved_by,
            injected_runtime_admission=injected_runtime_admission,
            completion_scope=RUNTIME_WORKFLOW_COMPLETION,
            advisory_attempt_mode=advisory_attempt_mode,
        )
    # Identity-incomplete default/retry/recovery mappings remain advisory and
    # deliberately omit VerificationOperationPreflightResultV1.
    return legacy_result


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
    operation: VerificationOperationEnvelope,
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    """Execute one admitted RuntimeEvidence-only continuation."""

    operation = validate_verification_operation_envelope(operation)
    declaration = resolve_verification_operation(operation)
    if declaration.shape_id != "runtime_execution_initial_evidence_only":
        raise LocalEntryError(
            "RuntimeEvidence-only executor received the wrong operation."
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
    if operation.approval_identity_hash != actual_identity_hash:
        return _runtime_evidence_only_terminal_result(
            status="blocked",
            failure_stage="authorization",
            preflight=preflight,
            factory_invocation_count=0,
            blockers=[
                {
                    "stage": "runtime_evidence",
                    "code": "RUNTIME_EXECUTION_TYPED_IDENTITY_MISMATCH",
                    "message": "Typed Runtime execution identity changed.",
                }
            ],
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
        verification_operation=operation,
        use_default_proposal_git_binding=False,
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
        preflight = _preflight_runtime_evidence_consolidation(
            verification_operation=validated_operation.to_spec(),
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
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
            use_default_proposal_git_binding=False,
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
    operation: VerificationOperationEnvelope,
) -> dict[str, Any]:
    """Execute one Store-only terminal continuation through the StateGraph."""

    operation = validate_verification_operation_envelope(operation)
    if resolve_verification_operation(operation).operation_kind != RUNTIME_TERMINALIZATION_KIND:
        raise LocalEntryError("Runtime terminal executor received the wrong operation.")

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
    if operation.approval_identity_hash != actual_identity_hash:
        return _runtime_terminal_public_result(
            status="blocked",
            failure_stage="authorization",
            preflight=preflight,
            blockers=[
                {
                    "stage": "runtime_terminalization",
                    "code": "RUNTIME_TERMINAL_TYPED_IDENTITY_MISMATCH",
                    "message": "Typed Runtime terminal identity changed.",
                }
            ],
        )
    graph = build_graph(
        handoff.build_handoff.artifact_store,
        verification_operation=operation,
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


def _normalize_legacy_runtime_workflow_operation(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None,
    feature_id: str,
    checkpoint_path: str | Path,
    checkpoint_hash: str,
    settings_path: str | Path | None,
    approved_by: str,
    allow_game_launch: bool,
    runtime_plugin_destination: str | Path | None,
    allow_game_directory_write: bool,
    resume_id: str | None,
    runtime_output_root: str | Path | None,
    injected_runtime_admission: Mapping[str, Any] | None,
    attempt_policy: InitialAttemptV1 | ObservationRetryAttemptV1 | AcceptedResumeRecoveryAttemptV1,
) -> VerificationOperationEnvelope:
    """Normalize one legacy execute call before any Runtime side effect."""

    selected_resume_id = resume_id or f"resume_{uuid4().hex}"
    handoff = _load_runtime_continuation_handoff(
        run_root=run_root,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        checkpoint_path=checkpoint_path,
        checkpoint_hash=checkpoint_hash,
        resume_id=selected_resume_id,
        attempt_policy=attempt_policy,
    )
    checkpoint_ref = handoff.checkpoint_ref
    checkpoint = handoff.checkpoint
    accepted_output_binding = _accepted_runtime_output_binding(handoff)
    if not isinstance(attempt_policy, InitialAttemptV1):
        decision = handoff.recovery_decision
        if decision is None:
            raise LocalEntryError(
                "Accepted Runtime attempt is missing its exact ResumeReport decision."
            )
        runtime_admission = decision.applied_updates.get("runtime_admission")
        if not isinstance(runtime_admission, Mapping):
            raise LocalEntryError(
                "Accepted Runtime attempt is missing its exact Runtime admission."
            )
        runtime_admission = dict(runtime_admission)
    elif injected_runtime_admission is not None:
        runtime_admission = dict(injected_runtime_admission)
    else:
        settings = load_settings(settings_path)
        acceptance_criteria = handoff.feature_spec.get("acceptance_criteria")
        exact_acceptance_criteria = (
            tuple(acceptance_criteria)
            if isinstance(acceptance_criteria, list)
            and all(isinstance(item, str) and bool(item) for item in acceptance_criteria)
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
        if accepted_output_binding is not None:
            runtime_admission["runtime_output_binding"] = dict(
                accepted_output_binding
            )
        elif runtime_output_root is not None:
            retry_binding = handoff.observation_retry_binding or {}
            output_report = _runtime_observation_retry_output_report(
                source_run_root=handoff.run_root,
                runtime_output_root=runtime_output_root,
                feature_id=feature_id,
                stagger_enabled=(
                    runtime_admission.get("stagger_acceptance") is not None
                ),
                stagger_modes=(
                    tuple(str(item) for item in retry_binding.get("retry_modes", ()))
                    if "retry_modes" in retry_binding
                    else None
                ),
            )
            runtime_admission["runtime_output_binding"] = (
                _runtime_output_admission_binding(output_report)
            )

    if isinstance(attempt_policy, ObservationRetryAttemptV1):
        report_ref = handoff.recovery_resume_report_ref
        if report_ref is None:
            raise LocalEntryError(
                "Runtime observation retry is missing its accepted ResumeReport."
            )
        report = handoff.artifact_store.read(report_ref)["data"]
        protocol_binding: VerificationProtocolBinding | NewRuntimeResumeProtocolBindingV1 = (
            VerificationProtocolBinding(
                checkpoint_ref=checkpoint_ref,
                accepted_resume_report_ref=report_ref,
                resume_id=selected_resume_id,
                approved_by=str(report["approved_by"]),
            )
        )
    elif isinstance(attempt_policy, AcceptedResumeRecoveryAttemptV1):
        report_ref = handoff.recovery_resume_report_ref
        if report_ref is None:
            raise LocalEntryError(
                "Accepted resume recovery is missing its ResumeReport."
            )
        report = handoff.artifact_store.read(report_ref)["data"]
        protocol_binding = VerificationProtocolBinding(
            checkpoint_ref=checkpoint_ref,
            accepted_resume_report_ref=report_ref,
            resume_id=selected_resume_id,
            approved_by=str(report["approved_by"]),
        )
    else:
        protocol_binding = NewRuntimeResumeProtocolBindingV1(
            checkpoint_ref=checkpoint_ref,
            resume_id=selected_resume_id,
            approved_by=approved_by,
        )
    return project_verification_operation(
        VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=attempt_policy,
            protocol_binding=protocol_binding,
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


def _execute_runtime_workflow_operation(
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
    runtime_output_root: str | Path | None = None,
    runtime_evidence_factory: (
        Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]] | None
    ) = None,
    injected_runtime_admission: Mapping[str, Any] | None = None,
    operation: VerificationOperationEnvelope,
) -> dict[str, Any]:
    """Execute one already-normalized Runtime workflow operation."""

    approved_operation = validate_verification_operation_envelope(operation)
    declaration = resolve_verification_operation(approved_operation)
    if (
        declaration.operation_kind != RUNTIME_EXECUTION_KIND
        or declaration.completion_scope != RUNTIME_WORKFLOW_COMPLETION
    ):
        raise LocalEntryError(
            "Runtime workflow executor received the wrong operation."
        )
    attempt = approved_operation.attempt_policy
    protocol = approved_operation.protocol_binding
    if not isinstance(
        attempt,
        (InitialAttemptV1, ObservationRetryAttemptV1, AcceptedResumeRecoveryAttemptV1),
    ):
        raise LocalEntryError("Runtime workflow attempt policy is not registered.")
    is_retry = isinstance(attempt, ObservationRetryAttemptV1)
    is_recovery = isinstance(attempt, AcceptedResumeRecoveryAttemptV1)
    if not isinstance(
        protocol,
        (NewRuntimeResumeProtocolBindingV1, VerificationProtocolBinding),
    ):
        raise LocalEntryError("Runtime workflow protocol binding is invalid.")
    if (
        protocol.checkpoint_ref.feature_id != feature_id
        or protocol.checkpoint_ref.path != str(Path(checkpoint_path).resolve())
        or protocol.checkpoint_ref.artifact_hash != checkpoint_hash
    ):
        raise LocalEntryError("Runtime workflow checkpoint identity changed.")
    if approved_by != (
        attempt.current_attempt_approved_by
        if isinstance(
            attempt,
            (ObservationRetryAttemptV1, AcceptedResumeRecoveryAttemptV1),
        )
        else protocol.approved_by
    ):
        raise LocalEntryError("Runtime workflow approver identity changed.")
    if resume_id is not None and resume_id != protocol.resume_id:
        raise LocalEntryError("Runtime workflow resume identity changed.")
    if is_retry and runtime_output_root is None:
        raise LocalEntryError(
            "Runtime observation retry requires runtime_output_root."
        )
    if runtime_output_root is not None and not Path(runtime_output_root).is_absolute():
        raise LocalEntryError(
            "Stagger Runtime output root must be absolute."
        )
    if (
        not isinstance(attempt, InitialAttemptV1)
    ) and injected_runtime_admission is not None:
        raise LocalEntryError(
            "Accepted ResumeReport reuse does not accept injected Runtime admission."
        )
    selected_resume_id = protocol.resume_id
    handoff = _load_runtime_continuation_handoff(
        run_root=run_root,
        artifact_store_root=artifact_store_root,
        feature_id=feature_id,
        checkpoint_path=checkpoint_path,
        checkpoint_hash=checkpoint_hash,
        resume_id=selected_resume_id,
        attempt_policy=attempt,
    )
    accepted_output_binding = _accepted_runtime_output_binding(handoff)
    selected_runtime_output_root = runtime_output_root
    if is_recovery and accepted_output_binding is not None:
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
                if is_retry
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
            and isinstance(attempt, InitialAttemptV1)
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
                    if is_retry
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
        if is_retry:
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
            and not is_retry
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
                if is_retry
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
                        if is_retry
                        else None
                    ),
                )
            ),
        )

    admission_snapshot = _runtime_resume_admission_snapshot(runtime_admission)
    approved_action_scope = dict(
        approved_operation.variant_payload.runtime_action_scope
    )
    revalidated_action_scope = (
        admission_snapshot
        if not isinstance(attempt, InitialAttemptV1)
        else runtime_admission
    )
    if approved_action_scope != revalidated_action_scope:
        raise LocalEntryError(
            "Runtime workflow action scope changed during execution admission."
        )
    checkpoint_identity = VerificationCheckpointIdentityV1(
        checkpoint_id=str(checkpoint["checkpoint_id"]),
        run_id=str(checkpoint["run_id"]),
        request_id=str(checkpoint["request_id"]),
    )
    if is_retry:
        retry_binding = handoff.observation_retry_binding
        report_ref = handoff.recovery_resume_report_ref
        prior_runtime_ref = handoff.prior_runtime_evidence_ref
        repair_plan_ref = handoff.prior_repair_plan_ref
        if (
            not isinstance(retry_binding, Mapping)
            or report_ref is None
            or prior_runtime_ref is None
            or repair_plan_ref is None
        ):
            raise LocalEntryError("Runtime observation retry typed binding is incomplete.")
        report = artifact_store.read(report_ref)["data"]
        remaining_before = retry_binding.get(
            "retry_budget_remaining_before_attempt"
        )
        if type(remaining_before) is not int:
            raise LocalEntryError("Runtime observation retry budget is incomplete.")
        operation_spec = VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=ObservationRetryAttemptV1(
                prior_runtime_evidence_ref=prior_runtime_ref,
                repair_plan_ref=repair_plan_ref,
                retry_number=int(retry_binding["retry_number"]),
                retry_budget=int(retry_binding["retry_budget"]),
                retry_budget_remaining=max(remaining_before - 1, 0),
                current_attempt_approved_by=approved_by,
            ),
            protocol_binding=VerificationProtocolBinding(
                checkpoint_ref=checkpoint_ref,
                accepted_resume_report_ref=report_ref,
                resume_id=selected_resume_id,
                approved_by=str(report["approved_by"]),
            ),
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope=RUNTIME_WORKFLOW_COMPLETION,
                runtime_action_scope=approved_action_scope,
            ),
        )
    elif is_recovery:
        report_ref = handoff.recovery_resume_report_ref
        if report_ref is None:
            raise LocalEntryError("Accepted resume recovery typed binding is incomplete.")
        report = artifact_store.read(report_ref)["data"]
        operation_spec = VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=AcceptedResumeRecoveryAttemptV1(
                accepted_resume_report_ref=report_ref,
                recovery_of_resume_id=selected_resume_id,
                current_attempt_approved_by=approved_by,
            ),
            protocol_binding=VerificationProtocolBinding(
                checkpoint_ref=checkpoint_ref,
                accepted_resume_report_ref=report_ref,
                resume_id=selected_resume_id,
                approved_by=str(report["approved_by"]),
            ),
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope=RUNTIME_WORKFLOW_COMPLETION,
                runtime_action_scope=approved_action_scope,
            ),
        )
    else:
        operation_spec = VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=NewRuntimeResumeProtocolBindingV1(
                checkpoint_ref=checkpoint_ref,
                resume_id=selected_resume_id,
                approved_by=approved_by,
            ),
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope=RUNTIME_WORKFLOW_COMPLETION,
                runtime_action_scope=approved_action_scope,
            ),
        )
    runtime_operation = project_verification_operation(
        operation_spec,
        checkpoint_identity=checkpoint_identity,
    )
    if (
        approved_operation.operation_kind != runtime_operation.operation_kind
        or approved_operation.operation_contract_version
        != runtime_operation.operation_contract_version
        or approved_operation.approval_identity
        != runtime_operation.approval_identity
        or not hmac.compare_digest(
            approved_operation.approval_identity_hash,
            runtime_operation.approval_identity_hash,
        )
    ):
        raise LocalEntryError(
            "Runtime workflow operation changed during execution admission."
        )
    runtime_operation = approved_operation
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
    resume_projection: dict[str, Any] | None = None

    def stop_before_runtime_graph(
        *,
        status: str,
        failure_stage: str,
        blockers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "status": status,
            "failure_stage": failure_stage,
            "operator_input_required": False,
            "side_effects_may_have_started": False,
            "run_id": checkpoint["run_id"],
            "request_id": checkpoint["request_id"],
            "feature_id": checkpoint["feature_id"],
            "resume_id": payload.resume_id,
            "accepted_resume_recovery": is_recovery,
            "runtime_observation_retry": is_retry,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "current_stage": "build",
            "artifacts": {},
            "artifact_hashes": {},
            "runtime_summary": {
                "platform_failure_stage": failure_stage,
                "side_effects_may_have_started": False,
            },
            "resume_report": resume_projection,
            "blockers": blockers,
        }

    if not isinstance(attempt, InitialAttemptV1):
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
        try:
            decision, resume_write_result = checkpoint_store.resume_with_result(
                checkpoint_ref,
                payload,
            )
        except Exception as exc:
            return stop_before_runtime_graph(
                status="blocked",
                failure_stage="resume_admission",
                blockers=[
                    {
                        "stage": "resume_admission",
                        "code": "RUNTIME_RESUME_ADMISSION_FAILED",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                ],
            )
        resume_projection = {
            "artifact_ref": (
                None
                if resume_write_result.artifact_ref is None
                else _artifact_ref_projection(resume_write_result.artifact_ref)
            ),
            "store_result": resume_write_result.to_dict(),
            "decision": decision.to_dict(),
        }
        if resume_write_result.outcome != "committed":
            return stop_before_runtime_graph(
                status=(
                    "partial"
                    if resume_write_result.outcome == "partial"
                    else "blocked"
                ),
                failure_stage="resume_report_store",
                blockers=(
                    list(decision.blockers)
                    or [
                        {
                            "stage": "resume_report_store",
                            "code": "RUNTIME_RESUME_REPORT_STORE_INCOMPLETE",
                            "message": (
                                "ResumeReport Store outcome was "
                                f"{resume_write_result.outcome}."
                            ),
                        }
                    ]
                ),
            )
        resume_report_ref = resume_write_result.artifact_ref
        if not decision.allowed or resume_report_ref is None:
            return stop_before_runtime_graph(
                status="blocked",
                failure_stage="resume_admission",
                blockers=(
                    list(decision.blockers)
                    or [
                        {
                            "stage": "resume_admission",
                            "code": "RUNTIME_RESUME_DECISION_BLOCKED",
                            "message": "ResumeReport was committed but resume was blocked.",
                        }
                    ]
                ),
            )
    if not decision.allowed:
        blocker_codes = [
            str(blocker.get("code"))
            for blocker in decision.blockers
            if isinstance(blocker, Mapping)
        ]
        raise LocalEntryError(
            "Runtime continuation resume was blocked: " + ", ".join(blocker_codes)
        )
    try:
        resumed_state = resumed_state_from_decision(
            decision,
            checkpoint_ref=checkpoint_ref,
            resume_report_ref=resume_report_ref,
        )
    except Exception as exc:
        return stop_before_runtime_graph(
            status="blocked",
            failure_stage="resume_admission",
            blockers=[
                {
                    "stage": "resume_admission",
                    "code": "RUNTIME_RESUMED_STATE_RECONSTRUCTION_FAILED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
        )
    graph = build_graph(
        artifact_store,
        runtime_evidence_factory=graph_runtime_factory,
        verification_operation=runtime_operation,
        use_default_proposal_git_binding=False,
    )
    try:
        result = graph.invoke(resumed_state)
    except Exception as exc:
        raise LocalEntryError(
            f"Runtime continuation graph failed: {type(exc).__name__}: {exc}"
        ) from exc

    runtime_summary = dict(result["runtime_summary"])
    platform_failure_stage = runtime_summary.get("platform_failure_stage")
    runtime_store_result = runtime_summary.get("runtime_evidence_store_result")
    runtime_store_outcome = (
        runtime_store_result.get("outcome")
        if isinstance(runtime_store_result, Mapping)
        else None
    )
    platform_status = (
        "partial"
        if runtime_store_outcome == "partial"
        else "blocked"
        if platform_failure_stage is not None
        else "completed"
    )
    runtime_summary["side_effects_may_have_started"] = (
        platform_failure_stage != "store_preflight"
    )
    summary = {
        "status": platform_status,
        "failure_stage": platform_failure_stage,
        "operator_input_required": False,
        "side_effects_may_have_started": runtime_summary[
            "side_effects_may_have_started"
        ],
        "run_id": result["run_id"],
        "request_id": result["request_id"],
        "feature_id": result["feature_id"],
        "resume_id": payload.resume_id,
        "accepted_resume_recovery": is_recovery,
        "runtime_observation_retry": is_retry,
        "runtime_observation_retry_binding": (
            {
                **dict(handoff.observation_retry_binding or {}),
                "runtime_output_root": str(root),
            }
            if is_retry
            else None
        ),
        "checkpoint_id": checkpoint["checkpoint_id"],
        "current_stage": result["current_stage"],
        "artifacts": result["artifacts"],
        "artifact_hashes": result["artifact_hashes"],
        "runtime_summary": runtime_summary,
        "resume_report": resume_projection,
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
    return summary


def _operation_result_refs_from_artifacts(
    public_result: Mapping[str, Any],
    *,
    feature_id: str,
) -> dict[str, ArtifactRef]:
    refs: dict[str, ArtifactRef] = {}
    artifacts = public_result.get("artifacts")
    hashes = public_result.get("artifact_hashes")
    if not isinstance(artifacts, Mapping) or not isinstance(hashes, Mapping):
        return refs
    for artifact_type, path in artifacts.items():
        artifact_hash = hashes.get(artifact_type)
        if isinstance(path, str) and isinstance(artifact_hash, str):
            refs[str(artifact_type)] = ArtifactRef(
                feature_id=feature_id,
                artifact_type=str(artifact_type),
                path=path,
                artifact_hash=artifact_hash,
            )
    return refs


def _exact_verification_platform_status(
    public_result: Mapping[str, Any],
) -> str:
    status = public_result.get("status")
    if status not in {"completed", "blocked", "partial"}:
        raise LocalEntryError(
            "Verification execution did not provide an exact platform status."
        )
    return str(status)


def _runtime_execution_machine_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: Mapping[str, Any],
) -> VerificationOperationResultV1:
    feature_id = envelope.protocol_binding.checkpoint_ref.feature_id
    artifact_refs = _operation_result_refs_from_artifacts(
        public_result,
        feature_id=feature_id,
    )
    resume_projection = public_result.get("resume_report")
    runtime_projection = public_result.get("runtime_evidence")
    resume_ref = _artifact_ref_from_projection(
        resume_projection.get("artifact_ref")
        if isinstance(resume_projection, Mapping)
        else None
    ) or artifact_refs.get("resume_report")
    if not isinstance(envelope.attempt_policy, InitialAttemptV1):
        # Accepted retry/recovery reports are protocol inputs, not outputs of
        # the current attempt.
        resume_ref = None
    runtime_ref = _artifact_ref_from_projection(
        runtime_projection.get("artifact_ref")
        if isinstance(runtime_projection, Mapping)
        else None
    ) or artifact_refs.get("runtime_evidence")
    terminal_refs = tuple(
        artifact_refs[item]
        for item in ("blocked_report", "eval_report", "workflow_summary")
        if item in artifact_refs
    )
    runtime_execution = public_result.get("runtime_execution")
    runtime_summary = public_result.get("runtime_summary")
    source_summary = (
        runtime_execution
        if isinstance(runtime_execution, Mapping)
        else runtime_summary
        if isinstance(runtime_summary, Mapping)
        else {}
    )
    raw_domain_status = (
        source_summary.get("acceptance_status")
        or source_summary.get("status")
    )
    domain_status = (
        str(raw_domain_status)
        if raw_domain_status in {"accepted", "blocked", "inconclusive"}
        else "unknown"
    )
    completion_scope = envelope.variant_payload.completion_scope
    platform_status = _exact_verification_platform_status(public_result)
    failure_stage = public_result.get("failure_stage")
    operator_input_required = public_result.get("operator_input_required") is True
    variant = RuntimeExecutionResultV1(
        completion_scope=completion_scope,
        domain_runtime_status=domain_status,
        resume_report_ref=resume_ref,
        runtime_evidence_ref=runtime_ref,
        terminal_refs=terminal_refs,
        operator_input_required=operator_input_required,
    )
    declaration = resolve_verification_operation(envelope)
    runtime_summary_mapping = (
        runtime_summary if isinstance(runtime_summary, Mapping) else {}
    )
    receipt_projections: dict[str, object] = {}
    if isinstance(resume_projection, Mapping) and resume_projection.get(
        "store_result"
    ) is not None:
        receipt_projections["resume_report"] = resume_projection["store_result"]
    runtime_store_result = (
        runtime_projection.get("store_result")
        if isinstance(runtime_projection, Mapping)
        else None
    ) or runtime_summary_mapping.get("runtime_evidence_store_result")
    if runtime_store_result is not None:
        receipt_projections["runtime_evidence"] = runtime_store_result
    for role in ("blocked_report", "eval_report", "workflow_summary"):
        projection = runtime_summary_mapping.get(f"{role}_store_result")
        if projection is not None:
            receipt_projections[role] = projection
    ordered_receipt_roles = _ordered_store_attempt_roles(
        declaration,
        tuple(receipt_projections),
    )
    receipts = _verification_store_receipts(
        tuple((role, receipt_projections[role]) for role in ordered_receipt_roles)
    )
    blocker_items = list(public_result.get("blockers") or ())
    blockers = (
        _verification_blockers(
            blocker_items,
            default_stage=str(failure_stage or "admission"),
        )
        if platform_status == "blocked" or blocker_items
        else ()
    )
    return project_verification_operation_result(
        envelope=envelope,
        platform_status=platform_status,
        failure_stage=failure_stage,
        side_effects_may_have_started=bool(
            source_summary.get("side_effects_may_have_started") is True
            or source_summary.get("factory_invocation_count", 0)
        ),
        store_receipts=receipts,
        blockers=blockers,
        variant_result=variant,
        audit_snapshot={"compatibility_mode": "typed_current"},
    )


def _terminalization_machine_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: Mapping[str, Any],
) -> VerificationOperationResultV1:
    projections = {
        role: public_result.get(role)
        for role in ("blocked_report", "eval_report", "workflow_summary")
    }
    refs = {
        role: _artifact_ref_from_projection(
            value.get("artifact_ref") if isinstance(value, Mapping) else None
        )
        for role, value in projections.items()
    }
    runtime_summary = public_result.get("runtime_summary")
    acceptance_value = (
        runtime_summary.get("acceptance_status")
        if isinstance(runtime_summary, Mapping)
        else None
    )
    domain_status = (
        str(acceptance_value)
        if acceptance_value in {"accepted", "blocked", "inconclusive"}
        else "unknown"
    )
    variant = RuntimeTerminalizationResultV1(
        domain_acceptance_status=domain_status,
        runtime_evidence_ref=envelope.variant_payload.runtime_evidence_ref,
        eval_report_ref=refs["eval_report"],
        blocked_report_ref=refs["blocked_report"],
        workflow_summary_ref=refs["workflow_summary"],
    )
    platform_status = _exact_verification_platform_status(public_result)
    declaration = resolve_verification_operation(envelope)
    receipt_projections = {
        role: value["store_result"]
        for role, value in projections.items()
        if isinstance(value, Mapping) and value.get("store_result") is not None
    }
    ordered_receipt_roles = _ordered_store_attempt_roles(
        declaration,
        tuple(receipt_projections),
    )
    receipts = _verification_store_receipts(
        tuple((role, receipt_projections[role]) for role in ordered_receipt_roles)
    )
    blocker_items = list(public_result.get("blockers") or ())
    blockers = (
        _verification_blockers(
            blocker_items,
            default_stage=str(public_result.get("failure_stage") or "terminal_admission"),
        )
        if platform_status == "blocked" or blocker_items
        else ()
    )
    return project_verification_operation_result(
        envelope=envelope,
        platform_status=platform_status,
        failure_stage=public_result.get("failure_stage"),
        side_effects_may_have_started=False,
        store_receipts=receipts,
        blockers=blockers,
        variant_result=variant,
        audit_snapshot={"compatibility_mode": "typed_current"},
    )


def _consolidation_machine_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: Mapping[str, Any],
) -> VerificationOperationResultV1:
    runtime_projection = public_result.get("runtime_evidence")
    runtime_ref = _artifact_ref_from_projection(
        runtime_projection.get("artifact_ref")
        if isinstance(runtime_projection, Mapping)
        else None
    )
    preflight = public_result.get("runtime_evidence_consolidation_preflight")
    intent = (
        preflight.get("artifact_write_intent")
        if isinstance(preflight, Mapping)
        else None
    )
    derived_payload_hash = public_result.get(
        "derived_runtime_evidence_payload_hash"
    )
    semantic_binding_key = (
        intent.get("semantic_binding_key")
        if isinstance(intent, Mapping)
        else None
    )
    semantic_binding_version = (
        intent.get("semantic_binding_version")
        if isinstance(intent, Mapping)
        else None
    )
    if not all(
        type(value) is str and value
        for value in (
            derived_payload_hash,
            semantic_binding_key,
            semantic_binding_version,
        )
    ):
        if runtime_ref is not None or (
            isinstance(runtime_projection, Mapping)
            and runtime_projection.get("store_result") is not None
        ):
            raise LocalEntryError(
                "Committed consolidation result is missing trusted machine facts."
            )
        return _rejected_verification_result(
            operation_kind=envelope.operation_kind,
            operation_contract_version=envelope.operation_contract_version,
            approval_identity_hash=envelope.approval_identity_hash,
            identity_resolution_status="approved_identity_only",
            failure_stage="admission",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "admission",
                        "code": "VERIFICATION_OPERATION_IDENTITY_UNAVAILABLE",
                        "message": (
                            "Consolidation result lacks trusted payload or semantic "
                            "binding facts."
                        ),
                    }
                ],
                default_stage="admission",
            ),
        )
    variant = EvidenceConsolidationResultV1(
        prior_runtime_evidence_ref=(
            envelope.variant_payload.prior_runtime_evidence_ref
        ),
        runtime_evidence_ref=runtime_ref,
        derived_payload_hash=derived_payload_hash,
        semantic_binding_key=semantic_binding_key,
        semantic_binding_version=semantic_binding_version,
    )
    platform_status = _exact_verification_platform_status(public_result)
    receipt = (
        runtime_projection.get("store_result")
        if isinstance(runtime_projection, Mapping)
        else None
    )
    blocker_items = list(public_result.get("blockers") or ())
    return project_verification_operation_result(
        envelope=envelope,
        platform_status=platform_status,
        failure_stage=public_result.get("failure_stage"),
        side_effects_may_have_started=False,
        store_receipts=_verification_store_receipts(
            (("runtime_evidence", receipt),)
        ),
        blockers=(
            _verification_blockers(
                blocker_items,
                default_stage=str(
                    public_result.get("failure_stage") or "consolidation_admission"
                ),
            )
            if platform_status == "blocked" or blocker_items
            else ()
        ),
        variant_result=variant,
        audit_snapshot={"compatibility_mode": "typed_current"},
    )


def _runtime_machine_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: Mapping[str, Any],
) -> VerificationOperationResultV1:
    declaration = resolve_verification_operation(envelope)
    if declaration.operation_kind == RUNTIME_EXECUTION_KIND:
        return _runtime_execution_machine_result(
            envelope=envelope,
            public_result=public_result,
        )
    if declaration.operation_kind == RUNTIME_TERMINALIZATION_KIND:
        return _terminalization_machine_result(
            envelope=envelope,
            public_result=public_result,
        )
    if declaration.operation_kind == EVIDENCE_CONSOLIDATION_KIND:
        return _consolidation_machine_result(
            envelope=envelope,
            public_result=public_result,
        )
    raise LocalEntryError("Runtime public result received a Build operation.")


def _finalize_runtime_public_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: dict[str, Any],
    typed_call: bool,
) -> dict[str, Any] | VerificationOperationResultV1:
    machine_result = _runtime_machine_result(
        envelope=envelope,
        public_result=public_result,
    )
    if typed_call:
        return machine_result
    public_result["verification_operation_result"] = machine_result.to_dict()
    return public_result


def _present_legacy_runtime_workflow_result(
    *,
    envelope: VerificationOperationEnvelope,
    public_result: dict[str, Any],
) -> dict[str, Any]:
    """Fix the machine result before writing the optional legacy JSON sink."""

    machine_result = _runtime_machine_result(
        envelope=envelope,
        public_result=public_result,
    )
    public_result["verification_operation_result"] = machine_result.to_dict()
    if machine_result.platform_status != "completed":
        raise VerificationOperationExecutionError(
            "Legacy Runtime execution did not complete.",
            machine_result,
        )
    output_root = public_result.get("runtime_output_root")
    if not isinstance(output_root, str) or not output_root:
        raise VerificationOperationPresentationError(
            "Runtime Presentation root is unavailable.",
            machine_result,
            audit_error={
                "stage": "presentation",
                "sink": "runtime_resume_result.json",
                "error_type": "RuntimePresentationRootUnavailable",
            },
        )
    result_path = Path(output_root) / "runtime_resume_result.json"
    try:
        result_path.write_text(
            json.dumps(public_result, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise VerificationOperationPresentationError(
            f"Runtime Presentation failed: {type(exc).__name__}: {exc}",
            machine_result,
            audit_error={
                "stage": "presentation",
                "sink": "runtime_resume_result.json",
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        ) from exc
    return public_result


def resume_local_runtime(
    *,
    run_root: str | Path,
    artifact_store_root: str | Path | None = None,
    verification_operation: VerificationOperationEnvelope | None = None,
    expected_approval_identity_hash: str | None = None,
    feature_id: str | None = None,
    checkpoint_path: str | Path | None = None,
    checkpoint_hash: str | None = None,
    settings_path: str | Path | None = None,
    approved_by: str | None = None,
    allow_game_launch: bool = False,
    runtime_plugin_destination: str | Path | None = None,
    allow_game_directory_write: bool = False,
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
    accepted_resume_report_path: str | Path | None = None,
    accepted_resume_report_hash: str | None = None,
    runtime_evidence_path: str | Path | None = None,
    runtime_evidence_hash: str | None = None,
    expected_runtime_terminal_identity_hash: str | None = None,
) -> dict[str, Any] | VerificationOperationResultV1:
    """Normalize legacy Runtime selectors or execute one typed operation."""

    if runtime_evidence_factory is not None and not callable(runtime_evidence_factory):
        raise TypeError("runtime_evidence_factory must be callable.")
    typed_call = verification_operation is not None
    legacy_identity_values = (
        feature_id,
        checkpoint_path,
        checkpoint_hash,
        approved_by,
        resume_id,
        injected_runtime_admission,
        expected_runtime_execution_identity_hash,
        expected_runtime_terminal_identity_hash,
        accepted_resume_report_path,
        accepted_resume_report_hash,
        runtime_evidence_path,
        runtime_evidence_hash,
    )
    if typed_call and (
        any(value is not None for value in legacy_identity_values)
        or recover_accepted_resume
        or retry_runtime_observation
        or runtime_evidence_only
        or runtime_terminalization_only
    ):
        return _rejected_verification_result(
            operation_kind=None,
            operation_contract_version=None,
            approval_identity_hash=None,
            identity_resolution_status="unresolved",
            failure_stage="authorization",
            blockers=_verification_blockers(
                [
                    {
                        "stage": "authorization",
                        "code": "VERIFICATION_OPERATION_LEGACY_MIXED",
                        "message": "Typed Runtime operation cannot mix legacy selectors.",
                    }
                ],
                default_stage="authorization",
            ),
        )
    if typed_call:
        try:
            envelope = validate_verification_operation_envelope(
                verification_operation
            )
            declaration = resolve_verification_operation(envelope)
        except (TypeError, ValueError) as exc:
            return _rejected_verification_result(
                operation_kind=None,
                operation_contract_version=None,
                approval_identity_hash=None,
                identity_resolution_status="unresolved",
                failure_stage="authorization",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "authorization",
                            "code": "VERIFICATION_OPERATION_UNSUPPORTED",
                            "message": str(exc),
                        }
                    ],
                    default_stage="authorization",
                ),
            )
        if declaration.operation_kind == VERIFICATION_BUILD_KIND:
            return _rejected_verification_result(
                operation_kind=None,
                operation_contract_version=None,
                approval_identity_hash=None,
                identity_resolution_status="unresolved",
                failure_stage="authorization",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "authorization",
                            "code": "RUNTIME_OPERATION_REQUIRED",
                            "message": "Runtime public entry does not accept Build operations.",
                        }
                    ],
                    default_stage="authorization",
                ),
            )
        expected_valid = isinstance(expected_approval_identity_hash, str)
        if not expected_valid or not hmac.compare_digest(
            str(expected_approval_identity_hash),
            envelope.approval_identity_hash,
        ):
            return _rejected_verification_result(
                operation_kind=envelope.operation_kind,
                operation_contract_version=envelope.operation_contract_version,
                approval_identity_hash=None,
                identity_resolution_status="declaration_resolved",
                failure_stage="authorization",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "authorization",
                            "code": "VERIFICATION_OPERATION_APPROVAL_HASH_MISMATCH",
                            "message": "Expected Runtime approval identity hash changed.",
                        }
                    ],
                    default_stage="authorization",
                ),
            )
        if artifact_store_root is None:
            return _rejected_verification_result(
                operation_kind=envelope.operation_kind,
                operation_contract_version=envelope.operation_contract_version,
                approval_identity_hash=envelope.approval_identity_hash,
                identity_resolution_status="approved_identity_only",
                failure_stage="admission",
                blockers=_verification_blockers(
                    [
                        {
                            "stage": "admission",
                            "code": "VERIFICATION_STORE_ROOT_REQUIRED",
                            "message": "Typed Runtime operation requires artifact_store_root.",
                        }
                    ],
                    default_stage="admission",
                ),
            )
        preflight_result, preflight_projection = _typed_runtime_preflight(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            spec=envelope.to_spec(),
        )
        if preflight_result.preflight_status != "ready":
            if preflight_result.identity_resolution_status == "declaration_resolved":
                return _rejected_verification_result(
                    operation_kind=envelope.operation_kind,
                    operation_contract_version=envelope.operation_contract_version,
                    approval_identity_hash=envelope.approval_identity_hash,
                    identity_resolution_status="approved_identity_only",
                    failure_stage="admission",
                    blockers=preflight_result.blockers,
                )
            public_result = {
                "status": "blocked",
                "failure_stage": "admission",
                "blockers": [item.to_dict() for item in preflight_result.blockers],
            }
            return _finalize_runtime_public_result(
                envelope=envelope,
                public_result=public_result,
                typed_call=True,
            )
        protocol = envelope.protocol_binding
        variant = envelope.variant_payload
        if declaration.operation_kind == EVIDENCE_CONSOLIDATION_KIND:
            public_result = _execute_runtime_evidence_consolidation(
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
                operation=envelope,
                expected_identity_hash=envelope.approval_identity_hash,
            )
        elif declaration.operation_kind == RUNTIME_TERMINALIZATION_KIND:
            public_result = _execute_runtime_terminal_continuation(
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
                accepted_resume_report_path=protocol.accepted_resume_report_ref.path,
                accepted_resume_report_hash=protocol.accepted_resume_report_ref.artifact_hash,
                runtime_evidence_path=variant.runtime_evidence_ref.path,
                runtime_evidence_hash=variant.runtime_evidence_ref.artifact_hash,
                approved_by=protocol.approved_by,
                resume_id=protocol.resume_id,
                expected_runtime_terminal_identity_hash=envelope.approval_identity_hash,
                operation=envelope,
            )
        elif declaration.shape_id == "runtime_execution_initial_evidence_only":
            if preflight_projection is None:
                return _rejected_verification_result(
                    operation_kind=envelope.operation_kind,
                    operation_contract_version=envelope.operation_contract_version,
                    approval_identity_hash=envelope.approval_identity_hash,
                    identity_resolution_status="approved_identity_only",
                    failure_stage="admission",
                    blockers=_verification_blockers(
                        [
                            {
                                "stage": "admission",
                                "code": "VERIFICATION_RUNTIME_ADMISSION_UNAVAILABLE",
                                "message": "Runtime preflight projection is unavailable.",
                            }
                        ],
                        default_stage="admission",
                    ),
                )
            public_result = _execute_runtime_evidence_only_continuation(
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
                approved_by=protocol.approved_by,
                resume_id=protocol.resume_id,
                runtime_evidence_factory=runtime_evidence_factory,
                injected_runtime_admission=variant.runtime_action_scope,
                expected_runtime_execution_identity_hash=envelope.approval_identity_hash,
                operation=envelope,
                preflight=preflight_projection,
            )
        else:
            attempt = envelope.attempt_policy
            current_approver = (
                attempt.current_attempt_approved_by
                if isinstance(
                    attempt,
                    (ObservationRetryAttemptV1, AcceptedResumeRecoveryAttemptV1),
                )
                else protocol.approved_by
            )
            public_result = _execute_runtime_workflow_operation(
                run_root=run_root,
                artifact_store_root=artifact_store_root,
                feature_id=protocol.checkpoint_ref.feature_id,
                checkpoint_path=protocol.checkpoint_ref.path,
                checkpoint_hash=protocol.checkpoint_ref.artifact_hash,
                settings_path=settings_path,
                approved_by=current_approver,
                allow_game_launch=allow_game_launch,
                runtime_plugin_destination=runtime_plugin_destination,
                allow_game_directory_write=allow_game_directory_write,
                resume_id=protocol.resume_id,
                runtime_output_root=runtime_output_root,
                runtime_evidence_factory=runtime_evidence_factory,
                injected_runtime_admission=(
                    variant.runtime_action_scope
                    if isinstance(attempt, InitialAttemptV1)
                    else None
                ),
                operation=envelope,
            )
        return _finalize_runtime_public_result(
            envelope=envelope,
            public_result=public_result,
            typed_call=True,
        )

    if feature_id is None or checkpoint_path is None or checkpoint_hash is None:
        raise TypeError("Legacy Runtime identity inputs are incomplete.")
    if approved_by is None:
        raise TypeError("Legacy Runtime approved_by is required.")
    normalized_operation: VerificationOperationEnvelope | None = None
    if runtime_terminalization_only:
        if (
            artifact_store_root is None
            or accepted_resume_report_path is None
            or accepted_resume_report_hash is None
            or runtime_evidence_path is None
            or runtime_evidence_hash is None
            or resume_id is None
        ):
            raise LocalEntryError(
                "Runtime terminalization legacy inputs are incomplete."
            )
        terminal_spec = VerificationOperationSpec(
            operation_kind=RUNTIME_TERMINALIZATION_KIND,
            operation_contract_version=RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=VerificationProtocolBinding(
                checkpoint_ref=ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="workflow_checkpoint",
                    path=str(Path(checkpoint_path).resolve()),
                    artifact_hash=checkpoint_hash,
                ),
                accepted_resume_report_ref=ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="resume_report",
                    path=str(Path(accepted_resume_report_path).resolve()),
                    artifact_hash=accepted_resume_report_hash,
                ),
                resume_id=resume_id,
                approved_by=approved_by,
            ),
            variant_payload=RuntimeTerminalizationOperationV1(
                runtime_evidence_ref=ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="runtime_evidence",
                    path=str(Path(runtime_evidence_path).resolve()),
                    artifact_hash=runtime_evidence_hash,
                )
            ),
        )
        terminal_preflight, _terminal_projection = _typed_runtime_preflight(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            spec=terminal_spec,
        )
        if terminal_preflight.preflight_status != "ready":
            if terminal_preflight.envelope is None:
                machine_result = _rejected_execution_result_from_preflight(
                    terminal_preflight
                )
            else:
                machine_result = _finalize_runtime_public_result(
                    envelope=terminal_preflight.envelope,
                    public_result={
                        "status": "blocked",
                        "failure_stage": terminal_preflight.failure_stage,
                        "blockers": [
                            item.to_dict() for item in terminal_preflight.blockers
                        ],
                    },
                    typed_call=True,
                )
            return {
                "status": "blocked",
                "failure_stage": terminal_preflight.failure_stage,
                "blockers": [item.to_dict() for item in terminal_preflight.blockers],
                "verification_operation_result": machine_result.to_dict(),
            }
        normalized_operation = terminal_preflight.envelope
        if (
            allow_game_launch
            or allow_game_directory_write
            or runtime_plugin_destination is not None
            or runtime_evidence_factory is not None
            or injected_runtime_admission is not None
            or runtime_output_root is not None
        ):
            legacy_result = _runtime_terminal_public_result(
                status="blocked",
                failure_stage="authorization",
                preflight=_terminal_projection,
                blockers=[
                    {
                        "stage": "runtime_terminalization",
                        "code": "RUNTIME_TERMINAL_SIDE_EFFECT_SCOPE_INVALID",
                        "message": (
                            "Runtime terminalization is a Store-only continuation."
                        ),
                    }
                ],
            )
        else:
            legacy_result = _execute_runtime_terminal_continuation(
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
                operation=normalized_operation,
            )
    elif runtime_evidence_only:
        if recover_accepted_resume or retry_runtime_observation:
            raise LocalEntryError(
                "RuntimeEvidence-only continuation supports only an initial resume."
            )
        if artifact_store_root is None or resume_id is None:
            raise LocalEntryError(
                "RuntimeEvidence-only legacy inputs are incomplete."
            )
        evidence_spec = VerificationOperationSpec(
            operation_kind=RUNTIME_EXECUTION_KIND,
            operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
            attempt_policy=InitialAttemptV1(),
            protocol_binding=NewRuntimeResumeProtocolBindingV1(
                checkpoint_ref=ArtifactRef(
                    feature_id=feature_id,
                    artifact_type="workflow_checkpoint",
                    path=str(Path(checkpoint_path).resolve()),
                    artifact_hash=checkpoint_hash,
                ),
                resume_id=resume_id,
                approved_by=approved_by,
            ),
            variant_payload=RuntimeExecutionOperationV1(
                completion_scope=RUNTIME_EVIDENCE_ONLY_COMPLETION,
                runtime_action_scope=_runtime_resume_admission_snapshot(
                    injected_runtime_admission
                ),
            ),
        )
        evidence_preflight, evidence_projection = _typed_runtime_preflight(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            spec=evidence_spec,
        )
        if (
            evidence_preflight.preflight_status != "ready"
            or evidence_projection is None
        ):
            if evidence_preflight.envelope is not None:
                public_result = {
                    "status": "blocked",
                    "failure_stage": evidence_preflight.failure_stage,
                    "blockers": [
                        item.to_dict() for item in evidence_preflight.blockers
                    ],
                }
                machine_result = _finalize_runtime_public_result(
                    envelope=evidence_preflight.envelope,
                    public_result=public_result,
                    typed_call=True,
                )
            else:
                machine_result = _rejected_execution_result_from_preflight(
                    evidence_preflight
                )
            return {
                "status": "blocked",
                "failure_stage": evidence_preflight.failure_stage,
                "blockers": [item.to_dict() for item in evidence_preflight.blockers],
                "verification_operation_result": machine_result.to_dict(),
            }
        normalized_operation = evidence_preflight.envelope
        legacy_result = _execute_runtime_evidence_only_continuation(
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
            operation=normalized_operation,
            preflight=evidence_projection,
        )
    else:
        attempt_policy = _resolve_legacy_runtime_attempt_policy(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            resume_id=resume_id,
            approved_by=approved_by,
            retry_runtime_observation=retry_runtime_observation,
            recover_accepted_resume=recover_accepted_resume,
        )
        normalized_operation = _normalize_legacy_runtime_workflow_operation(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            settings_path=settings_path,
            approved_by=approved_by,
            allow_game_launch=allow_game_launch,
            runtime_plugin_destination=runtime_plugin_destination,
            allow_game_directory_write=allow_game_directory_write,
            resume_id=resume_id,
            runtime_output_root=runtime_output_root,
            injected_runtime_admission=injected_runtime_admission,
            attempt_policy=attempt_policy,
        )
        legacy_result = _execute_runtime_workflow_operation(
            run_root=run_root,
            artifact_store_root=artifact_store_root,
            feature_id=feature_id,
            checkpoint_path=checkpoint_path,
            checkpoint_hash=checkpoint_hash,
            settings_path=settings_path,
            approved_by=approved_by,
            allow_game_launch=allow_game_launch,
            runtime_plugin_destination=runtime_plugin_destination,
            allow_game_directory_write=allow_game_directory_write,
            resume_id=resume_id,
            runtime_output_root=runtime_output_root,
            runtime_evidence_factory=runtime_evidence_factory,
            injected_runtime_admission=injected_runtime_admission,
            operation=normalized_operation,
        )
    if normalized_operation is None:
        raise LocalEntryError("Legacy Runtime operation was not normalized.")
    normalized_declaration = resolve_verification_operation(normalized_operation)
    if (
        normalized_declaration.operation_kind == RUNTIME_EXECUTION_KIND
        and normalized_declaration.completion_scope
        == RUNTIME_WORKFLOW_COMPLETION
    ):
        return _present_legacy_runtime_workflow_result(
            envelope=normalized_operation,
            public_result=legacy_result,
        )
    return _finalize_runtime_public_result(
        envelope=normalized_operation,
        public_result=legacy_result,
        typed_call=False,
    )


def _source_snapshot(root: Path) -> list[dict[str, Any]]:
    return _product_source_snapshot(root)


def _source_snapshot_sha256(snapshot: list[dict[str, Any]]) -> str:
    return _product_source_snapshot_sha256(snapshot)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _read_ollama_model_identity(base_url: str, model: str) -> dict[str, Any]:
    try:
        return _shared_read_ollama_model_identity(base_url, model)
    except (ModelAdmissionError, ValueError) as exc:
        raise LocalEntryError(str(exc)) from exc


def _read_ollama_server_version(base_url: str) -> str:
    try:
        return _shared_read_ollama_server_version(base_url)
    except (ModelAdmissionError, ValueError) as exc:
        raise LocalEntryError(str(exc)) from exc


def _select_ollama_model_identity(
    payload: Any,
    *,
    base_url: str,
    expected_model: str,
) -> dict[str, Any]:
    try:
        return _shared_select_ollama_model_identity(
            payload,
            base_url=base_url,
            expected_model=expected_model,
        )
    except ModelAdmissionError as exc:
        raise LocalEntryError(str(exc)) from exc


def _validate_ollama_model_identity(
    identity: Mapping[str, Any],
    *,
    expected_base_url: str,
    expected_model: str,
) -> None:
    try:
        _shared_validate_ollama_model_identity(
            identity,
            expected_base_url=expected_base_url,
            expected_model=expected_model,
        )
    except ModelAdmissionError as exc:
        raise LocalEntryError(str(exc)) from exc


def _validate_ollama_context_window(
    identity: Mapping[str, Any],
    *,
    requested_context_window: int | None,
) -> int:
    try:
        return _shared_validate_ollama_context_window(
            identity,
            requested_context_window=requested_context_window,
        )
    except ModelAdmissionError as exc:
        raise LocalEntryError(str(exc)) from exc


def _assert_ollama_model_identity_stable(
    *,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> None:
    try:
        _shared_assert_ollama_model_identity_stable(
            expected=expected,
            observed=observed,
        )
    except ModelAdmissionError as exc:
        raise LocalEntryError(str(exc)) from exc


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


def _patch_model_input_disclosure_data_classes(
    model_input: Mapping[str, Any],
) -> tuple[str, ...]:
    required: set[str] = set()
    for model_input_fields, _, data_classes in (
        PATCH_PROVIDER_PAYLOAD_DISCLOSURE_BINDINGS
    ):
        if all(field in model_input for field in model_input_fields):
            required.update(data_classes)
    return tuple(
        data_class
        for data_class in SOURCE_DISCLOSURE_DATA_CLASSES
        if data_class in required
    )


def _verify_patch_model_input_disclosure(
    record: dict[str, Any],
    *,
    model_input: Mapping[str, Any],
) -> None:
    requested_data_classes = _patch_model_input_disclosure_data_classes(model_input)
    recorded_requested = record.get("requested_data_classes")
    if recorded_requested != list(requested_data_classes):
        raise LocalEntryError(
            "Source disclosure requested_data_classes do not match the actual "
            "Patch provider payload fields."
        )
    _verify_source_disclosure(
        record,
        requested_data_classes=requested_data_classes,
    )
    if record.get("approved_data_classes") != list(requested_data_classes):
        raise LocalEntryError(
            "Source disclosure approved_data_classes do not match the actual "
            "Patch provider payload fields."
        )


def _resolve_project_path_property(project_file: Path, *, property_name: str) -> Path:
    value = Path(
        _project_text_property(project_file, property_name=property_name).replace(
            "\\", os.sep
        )
    )
    return value.resolve() if value.is_absolute() else (project_file.parent / value).resolve()


def _optional_project_text_property(
    project_file: Path,
    *,
    property_name: str,
) -> str | None:
    root = ET.parse(project_file).getroot()
    values = [
        item.text.strip()
        for item in root.iter(property_name)
        if isinstance(item.text, str) and item.text.strip()
    ]
    if not values:
        return None
    if len(values) != 1:
        raise LocalEntryError(
            f"Project file must define at most one non-empty {property_name}."
        )
    return values[0]


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


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)
