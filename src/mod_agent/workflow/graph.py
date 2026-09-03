"""LangGraph StateGraph construction for the controlled development workflow."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.mod_agent.artifact_semantics import project_artifact_write_intent
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore, ArtifactStoreError
from src.mod_agent.bindings import resolve_runtime_diagnosis_binding
from src.mod_agent.build import BuildResult, build_fake_build_result
from src.mod_agent.domain import (
    GTFO_DOMAIN_NAME,
    DomainAdapterRegistry,
    DomainReviewPolicy,
    GTFOAdapter,
    UnsupportedDomainAdapter,
)
from src.mod_agent.edit_authority_capabilities import (
    EditAuthorityCapabilityDeclaration,
    EditAuthorityStoreStepV1,
    InvalidEditAuthorityApprovalIdentityError,
    UnsupportedEditAuthorityCapabilityError,
    bind_edit_authority_exact_input_upstreams,
    edit_authority_identity_sections,
    project_edit_authority_review_result,
    resolve_edit_authority_request_capability,
    validate_edit_authority_exact_input_admission,
    validate_edit_authority_request_identity,
)
from src.mod_agent.evaluation import build_transition_eval_gate_report
from src.mod_agent.evidence import (
    DenseRetrievalProvider,
    DeterministicEvidenceRetriever,
    EvidencePack,
    EvidenceRequest,
)
from src.mod_agent.execution import ExactDiffApprovalRejectedError
from src.mod_agent.fresh_planning_continuation import (
    PlanningContinuationArtifactWriteError,
    PlanningContinuationInputV1,
    preflight_planning_continuation,
)
from src.mod_agent.git import GitCommandError, GitRepository
from src.mod_agent.knowledge import (
    CollectionResolutionError,
    CollectionResolver,
    KnowledgeDatabase,
)
from src.mod_agent.planning import (
    FeatureSpec,
    FeatureSpecBuilder,
    ImplementationPlanner,
    ModPlanningBriefBuilder,
    RequestPlan,
    RequestPlanner,
    Uncertainty,
)
from src.mod_agent.product_execution import (
    ProductExecutionContractError,
    ProductExecutionGraphModeV1,
)
from src.mod_agent.proposal import (
    CRITIC_DIMENSIONS,
    CriticAssessment,
    CriticFinding,
    PatchProposalBuilder,
    ProposalCritic,
    ProposalReviewer,
)
from src.mod_agent.proposal.models import SemanticAssuranceV1
from src.mod_agent.repair import RepairPatchProposalBuilder, RepairPlanner
from src.mod_agent.runtime import (
    build_fake_runtime_evidence_payload,
    make_gtfo_runtime_evidence_factory_from_settings,
)
from src.mod_agent.runtime.evidence import bind_runtime_evidence_context
from src.mod_agent.runtime.stagger_edit_authority import (
    StaggerEditAuthorityApprovalError,
    StaggerEditAuthorityMaterializationError,
    materialize_stagger_edit_authority_approval,
)
from src.mod_agent.runtime.stagger_planner_admission import (
    materialize_stagger_planning_approval,
)
from src.mod_agent.runtime_evidence_consolidation import (
    project_operation_payload as project_consolidated_runtime_evidence,
)
from src.mod_agent.verification_operations import (
    EVIDENCE_CONSOLIDATION_COMPLETION,
    RUNTIME_EVIDENCE_ONLY_COMPLETION,
    RUNTIME_WORKFLOW_COMPLETION,
    BuildInvocationProtocolBindingV1,
    EvidenceConsolidationOperationV1,
    NewRuntimeResumeProtocolBindingV1,
    RuntimeTerminalizationOperationV1,
    VerificationBuildOperationV1,
    VerificationOperationDeclaration,
    VerificationOperationEnvelope,
    VerificationProtocolBinding,
    resolve_verification_operation,
    validate_verification_operation_envelope,
)

from .checkpointing import (
    BUILD_CHECKPOINT_EXACT_REVISION_TYPES,
    WorkflowCheckpointStore,
)
from .interrupts import InterruptRequest, ResumePayload
from .nodes import StubNodeRunner
from .state import ModAgentState
from .transitions import (
    route_after_binding_resolution,
    route_after_build,
    route_after_dry_run,
    route_after_evaluate,
    route_after_evidence,
    route_after_feature_spec,
    route_after_human_review_gate,
    route_after_implementation_plan,
    route_after_isolated_apply,
    route_after_patch_proposal,
    route_after_plan_request,
    route_after_planning_brief,
    route_after_repair_plan,
    route_after_review,
    route_after_runtime_evidence,
    route_registry,
)
from .verification_only import (
    VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
    VerificationOnlyContinuationInput,
    VerificationOnlyRuntimeTerminalInput,
    preflight_verification_only_continuation,
    validate_verification_only_build_result,
    verification_only_lineage_matches,
    verification_only_lineage_payload,
)

GraphNode = Callable[[ModAgentState], ModAgentState]
BuildResultFactory = Callable[[str, str | None], BuildResult]
RuntimeEvidenceFactory = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
EvaluationContextFactory = Callable[[ModAgentState], dict[str, Any]]
ProposalGitBindingFactory = Callable[[], dict[str, Any]]
EvidencePackFactory = Callable[[ModAgentState, dict[str, Any]], EvidencePack]
PatchChangeFactory = Callable[
    [ModAgentState, dict[str, Any], dict[str, Any]], tuple[dict[str, Any], ...]
]
ProposalReviewContextFactory = Callable[
    [ModAgentState, dict[str, Any], dict[str, Any]],
    tuple[dict[str, Any], dict[str, Any]],
]
PatchExecutionFactory = Callable[
    [dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]
]


class _RuntimeEvidenceExecutionBoundaryError(RuntimeError):
    """Carry a platform-owned RuntimeEvidence failure stage across the Graph."""

    _ALLOWED_STAGES = frozenset(
        {"store_preflight", "runtime_execution", "post_runtime_validation"}
    )

    def __init__(self, failure_stage: str, cause: Exception) -> None:
        if failure_stage not in self._ALLOWED_STAGES:
            raise ValueError(
                f"Unsupported RuntimeEvidence failure stage: {failure_stage}"
            )
        super().__init__(str(cause))
        self.failure_stage = failure_stage
        self.failure_class = type(cause).__name__


CriticRequirement = Literal["not_required", "required"]
_FEATURE_SPEC_REVISION_APPROVAL_KEY = "feature_spec_revision"
_FEATURE_SPEC_REVISION_PROJECTION_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "feature_id",
        "producer_stage",
        "status",
        "payload",
        "inputs",
        "blockers",
        "trace_refs",
    }
)
_FEATURE_SPEC_REVISION_PAYLOAD_FIELDS = frozenset(
    {
        "acceptance_criteria",
        "admission_boundary",
        "automation_claim",
        "blocked",
        "blockers",
        "evidence_requirements",
        "feature_id",
        "hook_requirement",
        "message",
        "node_name",
        "non_goals",
        "operator_guided_technical_hypotheses",
        "revision_reason",
        "risk_level",
        "runtime_verification_plan",
        "source_lineage",
        "specification_mode",
        "stage",
        "success_marker_contract",
        "supersedes_artifact_hash",
        "target_behavior",
        "target_mod",
        "user_request",
    }
)
_DEFERRED_CORRELATION_HYPOTHESIS_IDS = frozenset(
    {
        "input_event_mapping",
        "result_event_mapping",
        "enemy_identity_mapping",
        "exactly_once_correlation",
    }
)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _verification_build_continuation(
    operation: VerificationOperationEnvelope,
) -> VerificationOnlyContinuationInput:
    declaration = resolve_verification_operation(
        validate_verification_operation_envelope(operation)
    )
    variant = operation.variant_payload
    if (
        declaration.graph_handler != "verification_build"
        or not isinstance(variant, VerificationBuildOperationV1)
    ):
        raise ValueError("Verification operation is not a Build operation.")
    return VerificationOnlyContinuationInput(
        feature_spec_ref=variant.feature_spec_ref,
        evidence_pack_ref=variant.evidence_pack_ref,
    )


def _verification_runtime_checkpoint_id(
    operation: VerificationOperationEnvelope,
) -> str:
    declaration = resolve_verification_operation(
        validate_verification_operation_envelope(operation)
    )
    if declaration.graph_handler != "runtime_execution":
        raise ValueError("Verification operation is not a Runtime execution.")
    checkpoint = operation.approval_identity.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        raise ValueError("Runtime execution identity lacks checkpoint facts.")
    checkpoint_id = checkpoint.get("checkpoint_id")
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        raise ValueError("Runtime execution checkpoint_id is invalid.")
    return checkpoint_id


def _verification_runtime_terminal_input(
    operation: VerificationOperationEnvelope,
) -> VerificationOnlyRuntimeTerminalInput:
    declaration = resolve_verification_operation(
        validate_verification_operation_envelope(operation)
    )
    variant = operation.variant_payload
    protocol = operation.protocol_binding
    if (
        declaration.graph_handler != "runtime_terminalization"
        or not isinstance(variant, RuntimeTerminalizationOperationV1)
        or not isinstance(protocol, VerificationProtocolBinding)
    ):
        raise ValueError("Verification operation is not a Runtime terminalization.")
    return VerificationOnlyRuntimeTerminalInput(
        checkpoint_ref=protocol.checkpoint_ref,
        resume_report_ref=protocol.accepted_resume_report_ref,
        runtime_evidence_ref=variant.runtime_evidence_ref,
        resume_id=protocol.resume_id,
        approved_by=protocol.approved_by,
    )


def _verification_operation_writes(
    declaration: VerificationOperationDeclaration | None,
    artifact_type: str,
) -> bool:
    return declaration is not None and artifact_type in declaration.output_artifact_types


@dataclass(frozen=True)
class _VerificationGraphControls:
    handler: str | None
    runtime_evidence_store_results: bool
    terminal_store_results: bool
    stop_after_build: bool
    persist_build_handoff: bool
    stop_after_runtime_evidence: bool


def _verification_graph_controls(
    declaration: VerificationOperationDeclaration | None,
) -> _VerificationGraphControls:
    return _VerificationGraphControls(
        handler=None if declaration is None else declaration.graph_handler,
        runtime_evidence_store_results=_verification_operation_writes(
            declaration,
            "runtime_evidence",
        ),
        terminal_store_results=any(
            _verification_operation_writes(declaration, artifact_type)
            for artifact_type in (
                "eval_report",
                "blocked_report",
                "workflow_summary",
            )
        ),
        stop_after_build=(
            declaration is not None
            and declaration.graph_handler == "verification_build"
        ),
        persist_build_handoff=(
            declaration is not None
            and declaration.graph_handler == "verification_build"
        ),
        stop_after_runtime_evidence=(
            declaration is not None
            and declaration.completion_scope
            in {
                RUNTIME_EVIDENCE_ONLY_COMPLETION,
                EVIDENCE_CONSOLIDATION_COMPLETION,
            }
        ),
    )


def _route_after_typed_runtime_evidence(state: ModAgentState) -> str:
    """Stop platform failures before product repair routing consumes no Artifact."""

    runtime_summary = state.get("runtime_summary") or {}
    if (
        runtime_summary.get("platform_failure_stage") is not None
        or (
            state.get("blockers")
            and "runtime_evidence" not in (state.get("artifacts") or {})
        )
    ):
        return "stop"
    return route_after_runtime_evidence(state)


def _validate_product_graph_start(
    state: ModAgentState,
    mode: ProductExecutionGraphModeV1,
) -> str:
    """Reject typed product request drift before the first node can act."""

    request = mode.request
    expected = {
        "run_id": request.run_id,
        "request_id": request.request_id,
        "user_request": request.user_request,
        "target_domain": request.target_domain,
        "target_mod": request.target_mod,
    }
    observed = {field: state.get(field) for field in expected}
    if observed != expected:
        raise ProductExecutionContractError(
            "Product Graph initial state changed after preflight.",
            side_effects_may_have_started=False,
        )
    if state.get("approvals") != {"confirmed_write": True}:
        raise ProductExecutionContractError(
            "Product Graph isolated-write authority changed after preflight.",
            side_effects_may_have_started=False,
        )
    return "continue"


def _validate_planning_continuation_graph_start(
    state: ModAgentState,
    mode: PlanningContinuationInputV1,
    artifact_store: ArtifactStore,
) -> str:
    """Reject exact-ref state drift before the Planning node can act."""

    admitted = preflight_planning_continuation(
        mode,
        artifact_store=artifact_store,
    )
    expected_artifacts = {
        "feature_spec": mode.feature_spec_ref.path,
        "evidence_pack": mode.evidence_pack_ref.path,
    }
    expected_hashes = {
        "feature_spec": mode.feature_spec_ref.artifact_hash,
        "evidence_pack": mode.evidence_pack_ref.artifact_hash,
    }
    if (
        state.get("feature_id") != mode.feature_spec_ref.feature_id
        or state.get("user_request") != admitted.feature_spec["user_request"]
        or state.get("target_mod") != admitted.feature_spec["target_mod"]
        or state.get("risk_level") != admitted.feature_spec["risk_level"]
        or state.get("current_stage") != "evidence_retrieval"
        or state.get("next_stage") != "implementation_plan"
        or state.get("artifacts") != expected_artifacts
        or state.get("artifact_hashes") != expected_hashes
        or state.get("approvals") != {}
        or state.get("blockers") != []
    ):
        raise ValueError(
            "Planning continuation state changed after exact-ref admission."
        )
    for field in ("run_id", "request_id", "user_request"):
        value = state.get(field)
        if type(value) is not str or not value:
            raise ValueError(
                "Planning continuation state identity is incomplete."
            )
    return "continue"


def build_graph(
    artifact_store: ArtifactStore,
    *,
    settings: Any | None = None,
    knowledge_database: KnowledgeDatabase | None = None,
    collection_id: str | None = None,
    collection_resolver: CollectionResolver | None = None,
    dense_provider: DenseRetrievalProvider | None = None,
    dense_enabled: bool = False,
    dense_required: bool = False,
    dense_top_k: int | None = None,
    domain_adapter_registry: DomainAdapterRegistry | None = None,
    domain_review_policy: DomainReviewPolicy | None = None,
    build_result_factory: BuildResultFactory | None = None,
    runtime_evidence_factory: RuntimeEvidenceFactory | None = None,
    allow_game_launch: bool = False,
    proposal_git_binding_factory: ProposalGitBindingFactory | None = None,
    use_default_proposal_git_binding: bool = True,
    evidence_pack_factory: EvidencePackFactory | None = None,
    patch_change_factory: PatchChangeFactory | None = None,
    proposal_review_context_factory: ProposalReviewContextFactory | None = None,
    proposal_source_snippet_char_limit: int = 6000,
    proposal_critic: ProposalCritic | None = None,
    critic_requirement: CriticRequirement = "not_required",
    dry_run_factory: PatchExecutionFactory | None = None,
    isolated_apply_factory: PatchExecutionFactory | None = None,
    stop_after_evidence: bool = False,
    stop_after_build: bool = False,
    persist_build_runtime_handoff: bool = False,
    build_checkpoint_exact_revision_upstream_types: frozenset[str] = frozenset(),
    edit_authority_request_ref: ArtifactRef | None = None,
    repair_planning_authority_request_ref: ArtifactRef | None = None,
    evaluation_context_factory: EvaluationContextFactory | None = None,
    require_external_evaluation: bool = False,
    require_review_approval_for_dry_run: bool = False,
    enable_dynamic_review_interrupt: bool = False,
    checkpointer: Any | None = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    feature_spec_revision_projection: Mapping[str, Any] | None = None,
    approved_feature_spec_revision_payload_hash: str | None = None,
    approved_feature_spec_revision_projection_hash: str | None = None,
    verification_operation: VerificationOperationEnvelope | None = None,
    product_execution_mode: ProductExecutionGraphModeV1 | None = None,
    planning_continuation_mode: PlanningContinuationInputV1 | None = None,
):
    """Build a compiled LangGraph graph with real planning/review routing.

    Planning, evidence retrieval, implementation planning, patch proposal, and
    review are real controlled nodes. Dry-run remains fake; build and runtime
    evidence can be injected for controlled contract tests.
    """

    if (
        enable_dynamic_review_interrupt
        or edit_authority_request_ref is not None
        or repair_planning_authority_request_ref is not None
    ) and checkpointer is None:
        raise ValueError(
            "Human approval interrupts require a LangGraph checkpointer."
        )
    validated_verification_operation = (
        None
        if verification_operation is None
        else validate_verification_operation_envelope(verification_operation)
    )
    validated_product_execution_mode = product_execution_mode
    if validated_product_execution_mode is not None and not isinstance(
        validated_product_execution_mode, ProductExecutionGraphModeV1
    ):
        raise ProductExecutionContractError(
            "product_execution_mode must be ProductExecutionGraphModeV1.",
            side_effects_may_have_started=False,
        )
    validated_planning_continuation_mode = planning_continuation_mode
    if validated_planning_continuation_mode is not None and not isinstance(
        validated_planning_continuation_mode,
        PlanningContinuationInputV1,
    ):
        raise ValueError(
            "planning_continuation_mode must be PlanningContinuationInputV1."
        )
    if (
        validated_product_execution_mode is not None
        and validated_verification_operation is not None
    ):
        raise ProductExecutionContractError(
            "Product and verification operation modes cannot share one Graph.",
            side_effects_may_have_started=False,
        )
    if validated_planning_continuation_mode is not None:
        incompatible_values = (
            settings,
            knowledge_database,
            collection_id,
            collection_resolver,
            dense_provider,
            dense_top_k,
            domain_adapter_registry,
            domain_review_policy,
            build_result_factory,
            runtime_evidence_factory,
            proposal_git_binding_factory,
            evidence_pack_factory,
            patch_change_factory,
            proposal_review_context_factory,
            proposal_critic,
            dry_run_factory,
            isolated_apply_factory,
            edit_authority_request_ref,
            repair_planning_authority_request_ref,
            evaluation_context_factory,
            checkpointer,
            feature_spec_revision_projection,
            approved_feature_spec_revision_payload_hash,
            approved_feature_spec_revision_projection_hash,
            validated_verification_operation,
            validated_product_execution_mode,
        )
        incompatible_flags = (
            dense_enabled,
            dense_required,
            allow_game_launch,
            use_default_proposal_git_binding,
            stop_after_evidence,
            stop_after_build,
            persist_build_runtime_handoff,
            bool(build_checkpoint_exact_revision_upstream_types),
            require_external_evaluation,
            require_review_approval_for_dry_run,
            enable_dynamic_review_interrupt,
            bool(interrupt_before),
            bool(interrupt_after),
            critic_requirement != "not_required",
            proposal_source_snippet_char_limit != 6000,
        )
        if any(value is not None for value in incompatible_values) or any(
            incompatible_flags
        ):
            raise ValueError(
                "Planning continuation cannot receive unrelated workflow, "
                "model, effect, approval, or stopping controls."
            )
    if validated_product_execution_mode is not None:
        if (
            stop_after_evidence
            or stop_after_build
            or persist_build_runtime_handoff
            or build_checkpoint_exact_revision_upstream_types
            or enable_dynamic_review_interrupt
            or edit_authority_request_ref is not None
            or repair_planning_authority_request_ref is not None
            or feature_spec_revision_projection is not None
            or approved_feature_spec_revision_payload_hash is not None
            or approved_feature_spec_revision_projection_hash is not None
            or interrupt_before
            or interrupt_after
        ):
            raise ProductExecutionContractError(
                "Product Graph routing comes from its typed request, not legacy "
                "stopping, authority, revision, or interrupt controls.",
                side_effects_may_have_started=False,
            )
        if build_result_factory is None:
            raise ProductExecutionContractError(
                "Product execution requires an explicit Build adapter.",
                side_effects_may_have_started=False,
            )
        if evidence_pack_factory is None or patch_change_factory is None:
            raise ProductExecutionContractError(
                "Product execution requires explicit Evidence and Patch adapters.",
                side_effects_may_have_started=False,
            )
        if dry_run_factory is None or isolated_apply_factory is None:
            raise ProductExecutionContractError(
                "Product execution requires exact Dry-run and Isolated Apply adapters.",
                side_effects_may_have_started=False,
            )
        request_scope = (
            validated_product_execution_mode.request.requested_completion_scope
        )
        if (runtime_evidence_factory is None) is not (request_scope == "compile_only"):
            raise ProductExecutionContractError(
                "Product Runtime adapter topology disagrees with completion scope.",
                side_effects_may_have_started=False,
            )
        stop_after_build = request_scope == "compile_only"
        persist_build_runtime_handoff = request_scope == "compile_only"
    operation_declaration = (
        None
        if validated_verification_operation is None
        else resolve_verification_operation(validated_verification_operation)
    )
    operation_controls = _verification_graph_controls(operation_declaration)
    operation_handler = operation_controls.handler
    if operation_declaration is not None:
        if (
            edit_authority_request_ref is not None
            or repair_planning_authority_request_ref is not None
            or feature_spec_revision_projection is not None
        ):
            raise ValueError(
                "Verification operation and another controlled Graph entry "
                "cannot share one invocation."
            )
        if (
            stop_after_evidence
            or stop_after_build
            or persist_build_runtime_handoff
            or build_checkpoint_exact_revision_upstream_types
            or allow_game_launch
            or interrupt_before
            or interrupt_after
        ):
            raise ValueError(
                "Verification operation routing, side-effect scope, stopping, "
                "checkpointing, and interrupts come from its declaration, not "
                "generic Graph controls."
            )
        if operation_handler == "verification_build":
            if build_result_factory is None:
                raise ValueError(
                    "Verification Build requires an explicit build_result_factory."
                )
            if runtime_evidence_factory is not None:
                raise ValueError(
                    "Verification Build cannot receive Runtime effect adapters."
                )
            if build_checkpoint_exact_revision_upstream_types:
                raise ValueError(
                    "Verification Build uses its declared fresh FeatureSpec and "
                    "EvidencePack lineage, not mutation exact-revision roles."
                )
        elif operation_handler == "runtime_execution":
            if build_result_factory is not None:
                raise ValueError(
                    "Runtime execution cannot receive a Build effect adapter."
                )
            if runtime_evidence_factory is None:
                raise ValueError(
                    "Runtime execution requires an explicit runtime_evidence_factory."
                )
        elif operation_handler in {
            "runtime_terminalization",
            "runtime_evidence_consolidation",
        }:
            if (
                build_result_factory is not None
                or runtime_evidence_factory is not None
                or persist_build_runtime_handoff
            ):
                raise ValueError(
                    "Store-only verification operations cannot receive effect "
                    "adapters or Build handoff configuration."
                )
        else:
            raise ValueError("Verification operation Graph handler is unsupported.")
    revision_configuration = (
        feature_spec_revision_projection,
        approved_feature_spec_revision_payload_hash,
        approved_feature_spec_revision_projection_hash,
    )
    if any(value is not None for value in revision_configuration) and not all(
        value is not None for value in revision_configuration
    ):
        raise ValueError(
            "FeatureSpec revision materialization requires the complete "
            "projection and both approved hashes."
        )
    if feature_spec_revision_projection is not None:
        if checkpointer is None:
            raise ValueError(
                "FeatureSpec revision materialization requires a LangGraph "
                "checkpointer for controlled node-level resume."
            )
        if "draft_feature_spec" not in set(interrupt_after or []):
            raise ValueError(
                "FeatureSpec revision materialization must interrupt after "
                "draft_feature_spec before any downstream node."
            )
    if (
        edit_authority_request_ref is not None
        and repair_planning_authority_request_ref is not None
    ):
        raise ValueError(
            "Edit Authority and Repair planning approval require separate "
            "graph entries."
        )
    if persist_build_runtime_handoff and not stop_after_build:
        raise ValueError(
            "Build-to-Runtime handoff persistence requires stop_after_build=True."
        )
    if (
        build_checkpoint_exact_revision_upstream_types
        and not persist_build_runtime_handoff
    ):
        raise ValueError(
            "Build checkpoint exact revision roles require persisted "
            "Build-to-Runtime handoff."
        )
    unsupported_checkpoint_exact_types = (
        set(build_checkpoint_exact_revision_upstream_types)
        - BUILD_CHECKPOINT_EXACT_REVISION_TYPES
    )
    if unsupported_checkpoint_exact_types:
        raise ValueError(
            "Build checkpoint exact revision roles are unsupported: "
            f"{sorted(unsupported_checkpoint_exact_types)}"
        )
    missing_checkpoint_exact_types = (
        BUILD_CHECKPOINT_EXACT_REVISION_TYPES
        - set(build_checkpoint_exact_revision_upstream_types)
        if build_checkpoint_exact_revision_upstream_types
        else set()
    )
    if missing_checkpoint_exact_types:
        raise ValueError(
            "Build checkpoint exact revision roles are incomplete: "
            f"{sorted(missing_checkpoint_exact_types)}"
        )
    if require_external_evaluation and evaluation_context_factory is None:
        raise ValueError("require_external_evaluation requires evaluation_context_factory")
    if (
        isinstance(proposal_source_snippet_char_limit, bool)
        or not isinstance(proposal_source_snippet_char_limit, int)
        or proposal_source_snippet_char_limit <= 0
    ):
        raise ValueError("proposal_source_snippet_char_limit must be a positive integer.")
    if critic_requirement not in {"not_required", "required"}:
        raise ValueError(
            "critic_requirement must be exactly 'not_required' or 'required'."
        )
    if critic_requirement == "not_required" and proposal_critic is not None:
        raise ValueError(
            "proposal_critic requires critic_requirement='required'; "
            "implicit triggering is not supported."
        )
    if domain_review_policy is not None and domain_adapter_registry is not None:
        raise ValueError(
            "domain_review_policy and domain_adapter_registry cannot both "
            "be supplied."
        )

    verification_build_continuation = (
        _verification_build_continuation(validated_verification_operation)
        if operation_handler == "verification_build"
        and validated_verification_operation is not None
        else None
    )
    effective_interrupt_after = list(interrupt_after or ())
    if (
        operation_controls.stop_after_runtime_evidence
        and "collect_runtime_evidence" not in effective_interrupt_after
    ):
        effective_interrupt_after.append("collect_runtime_evidence")

    stub_runner = StubNodeRunner(artifact_store)
    effective_domain_registry = domain_adapter_registry or _default_domain_adapter_registry()
    effective_runtime_evidence_factory = (
        None
        if operation_handler == "runtime_evidence_consolidation"
        else (
            runtime_evidence_factory
            or _runtime_evidence_factory_from_settings(
                settings,
                allow_game_launch=allow_game_launch,
            )
        )
    )
    effective_proposal_git_binding_factory = proposal_git_binding_factory
    if effective_proposal_git_binding_factory is None and use_default_proposal_git_binding:
        effective_proposal_git_binding_factory = _default_proposal_git_binding_factory
    graph = StateGraph(ModAgentState)

    if verification_build_continuation is not None:
        graph.add_node(
            "verification_only_admission",
            _make_real_graph_node(
                "verification_only_admission",
                lambda state: _run_verification_only_admission(
                    state,
                    artifact_store,
                    validated_verification_operation,
                ),
            ),
        )

    graph.add_node(
        "plan_request",
        _make_real_graph_node(
            "plan_request",
            lambda state: _run_plan_request(state, artifact_store),
        ),
    )
    graph.add_node(
        "draft_feature_spec",
        _make_real_graph_node(
            "draft_feature_spec",
            lambda state: _run_draft_feature_spec(
                state,
                artifact_store,
                revision_projection=feature_spec_revision_projection,
                approved_payload_hash=approved_feature_spec_revision_payload_hash,
                approved_projection_hash=(
                    approved_feature_spec_revision_projection_hash
                ),
            ),
        ),
    )
    graph.add_node(
        "planning_brief",
        _make_real_graph_node(
            "planning_brief",
            lambda state: _run_planning_brief(state, artifact_store),
        ),
    )
    graph.add_node(
        "retrieve_evidence",
        _make_real_graph_node(
            "retrieve_evidence",
            lambda state: _run_retrieve_evidence(
                state,
                artifact_store,
                knowledge_database,
                collection_id,
                collection_resolver,
                dense_provider,
                dense_enabled,
                dense_required,
                dense_top_k,
                evidence_pack_factory,
            ),
        ),
    )
    graph.add_node(
        "create_implementation_plan",
        _make_real_graph_node(
            "create_implementation_plan",
            lambda state: _run_create_implementation_plan(
                state,
                artifact_store,
                formal_requirement_coverage_required=(
                    validated_product_execution_mode is not None
                    or validated_planning_continuation_mode is not None
                ),
                use_store_result=(
                    validated_planning_continuation_mode is not None
                ),
                planning_continuation_mode=(
                    validated_planning_continuation_mode
                ),
            ),
        ),
    )
    graph.add_node(
        "generate_patch_proposal",
        _make_real_graph_node(
            "generate_patch_proposal",
            lambda state: _run_generate_patch_proposal(
                state,
                artifact_store,
                proposal_git_binding_factory=effective_proposal_git_binding_factory,
                patch_change_factory=patch_change_factory,
                source_snippet_char_limit=proposal_source_snippet_char_limit,
            ),
        ),
    )
    graph.add_node(
        "review_proposal",
        _make_real_graph_node(
            "review_proposal",
            lambda state: _run_review_proposal(
                state,
                artifact_store,
                domain_adapter_registry=effective_domain_registry,
                domain_review_policy=domain_review_policy,
                require_executable_patch=patch_change_factory is not None,
                proposal_critic=proposal_critic,
                critic_requirement=critic_requirement,
                proposal_review_context_factory=proposal_review_context_factory,
            ),
        ),
    )
    if enable_dynamic_review_interrupt:
        graph.add_node(
            "human_review_gate",
            _make_real_graph_node(
                "human_review_gate",
                lambda state: _run_dynamic_human_review_gate(state, artifact_store),
            ),
        )
    if edit_authority_request_ref is not None:
        graph.add_node(
            "stagger_edit_authority_gate",
            _make_real_graph_node(
                "stagger_edit_authority_gate",
                lambda state: _run_stagger_edit_authority_gate(
                    state,
                    artifact_store,
                    edit_authority_request_ref,
                ),
            ),
        )
    if repair_planning_authority_request_ref is not None:
        graph.add_node(
            "stagger_repair_planning_gate",
            _make_real_graph_node(
                "stagger_repair_planning_gate",
                lambda state: _run_stagger_repair_planning_gate(
                    state,
                    artifact_store,
                    repair_planning_authority_request_ref,
                ),
            ),
        )

    graph.add_node(
        "dry_run_apply",
        _make_real_graph_node(
            "dry_run_apply",
            lambda state: _run_dry_run_apply(
                state,
                artifact_store,
                require_review_approval=require_review_approval_for_dry_run,
                dry_run_factory=dry_run_factory,
            ),
        ),
    )
    if isolated_apply_factory is not None:
        graph.add_node(
            "isolated_apply",
            _make_real_graph_node(
                "isolated_apply",
                lambda state: _run_isolated_apply(
                    state,
                    artifact_store,
                    isolated_apply_factory=isolated_apply_factory,
                ),
            ),
        )
    graph.add_node(
        "build",
        _make_real_graph_node(
            "build",
            lambda state: _run_build(
                state,
                artifact_store,
                build_result_factory,
                verification_operation=validated_verification_operation,
                persist_build_runtime_handoff=(
                    persist_build_runtime_handoff
                    or operation_controls.persist_build_handoff
                ),
                exact_revision_upstream_types=(
                    build_checkpoint_exact_revision_upstream_types
                ),
            ),
        ),
    )
    graph.add_node(
        "collect_runtime_evidence",
        _make_real_graph_node(
            "collect_runtime_evidence",
            lambda state: _run_runtime_evidence(
                state,
                artifact_store,
                effective_runtime_evidence_factory,
                use_store_result=operation_controls.runtime_evidence_store_results,
                verification_operation=validated_verification_operation,
            ),
        ),
    )
    graph.add_node(
        "evaluate",
        _make_real_graph_node(
            "evaluate",
            lambda state: _run_terminal_node_with_boundary(
                state,
                lambda selected: _run_fake_evaluate(
                    selected,
                    artifact_store,
                    evaluation_context_factory,
                    require_external_evaluation,
                    use_store_result=operation_controls.terminal_store_results,
                ),
                failure_stage="eval_report_execution",
                blocker_code="EVAL_REPORT_EXECUTION_FAILED",
                use_boundary=operation_controls.terminal_store_results,
            ),
        ),
    )
    graph.add_node(
        "create_repair_plan",
        _make_real_graph_node(
            "create_repair_plan",
            lambda state: _run_create_repair_plan(
                state,
                artifact_store,
                product_execution_mode=validated_product_execution_mode,
            ),
        ),
    )
    graph.add_node(
        "resolve_runtime_binding",
        _make_real_graph_node(
            "resolve_runtime_binding",
            lambda state: _run_resolve_runtime_binding(
                state,
                artifact_store,
            ),
        ),
    )
    graph.add_node(
        "done",
        _make_real_graph_node(
            "done",
            lambda state: _run_terminal_node_with_boundary(
                state,
                lambda selected: _run_workflow_summary(
                    selected,
                    artifact_store,
                    use_store_result=operation_controls.terminal_store_results,
                ),
                failure_stage="workflow_summary_execution",
                blocker_code="WORKFLOW_SUMMARY_EXECUTION_FAILED",
                use_boundary=operation_controls.terminal_store_results,
            ),
        ),
    )
    graph.add_node(
        "blocked",
        _make_stub_graph_node(
            "blocked",
            stub_runner,
            use_store_result=operation_controls.terminal_store_results,
        ),
    )

    if (
        operation_handler == "runtime_terminalization"
        and validated_verification_operation is not None
    ):
        graph.add_conditional_edges(
            START,
            lambda state: _route_runtime_terminal_continuation_entry(
                state,
                artifact_store,
                _verification_runtime_terminal_input(
                    validated_verification_operation
                ),
            ),
            {
                "blocked": "blocked",
                "continue": "evaluate",
            },
        )
    elif (
        operation_handler == "runtime_evidence_consolidation"
        and validated_verification_operation is not None
    ):
        graph.add_conditional_edges(
            START,
            lambda state: _route_runtime_evidence_consolidation_entry(
                state,
                artifact_store,
                validated_verification_operation,
            ),
            {"continue": "collect_runtime_evidence"},
        )
    elif operation_handler == "verification_build":
        graph.add_edge(START, "verification_only_admission")
    elif (
        operation_handler == "runtime_execution"
        and validated_verification_operation is not None
    ):
        graph.add_conditional_edges(
            START,
            lambda state: _route_runtime_continuation_entry(
                state,
                artifact_store,
                validated_verification_operation,
            ),
            {"continue": "collect_runtime_evidence"},
        )
    elif validated_planning_continuation_mode is not None:
        graph.add_conditional_edges(
            START,
            lambda state: _validate_planning_continuation_graph_start(
                state,
                validated_planning_continuation_mode,
                artifact_store,
            ),
            {"continue": "create_implementation_plan"},
        )
    elif validated_product_execution_mode is not None:
        graph.add_conditional_edges(
            START,
            lambda state: _validate_product_graph_start(
                state,
                validated_product_execution_mode,
            ),
            {"continue": "plan_request"},
        )
    elif repair_planning_authority_request_ref is not None:
        graph.add_edge(START, "stagger_repair_planning_gate")
    elif edit_authority_request_ref is not None:
        graph.add_edge(START, "stagger_edit_authority_gate")
    else:
        graph.add_edge(START, "plan_request")
    if operation_handler == "verification_build":
        graph.add_conditional_edges(
            "verification_only_admission",
            lambda state: "blocked" if state["blockers"] else "continue",
            {"blocked": END, "continue": "build"},
        )
    registry = route_registry()
    graph.add_conditional_edges(
        "plan_request",
        route_after_plan_request,
        dict(registry["plan_request"]),
    )
    graph.add_conditional_edges(
        "planning_brief",
        route_after_planning_brief,
        dict(registry["planning_brief"]),
    )
    graph.add_conditional_edges(
        "draft_feature_spec",
        route_after_feature_spec,
        dict(registry["draft_feature_spec"]),
    )
    if stop_after_evidence:
        graph.add_conditional_edges(
            "retrieve_evidence",
            route_after_evidence,
            {"continue": END, "blocked": END},
        )
    else:
        graph.add_conditional_edges(
            "retrieve_evidence",
            route_after_evidence,
            dict(registry["retrieve_evidence"]),
        )
    graph.add_conditional_edges(
        "create_implementation_plan",
        route_after_implementation_plan,
        (
            {"continue": END, "blocked": END}
            if validated_planning_continuation_mode is not None
            else dict(registry["create_implementation_plan"])
        ),
    )
    graph.add_conditional_edges(
        "generate_patch_proposal",
        route_after_patch_proposal,
        dict(registry["generate_patch_proposal"]),
    )
    graph.add_conditional_edges(
        "review_proposal",
        route_after_review,
        _review_route_map(
            registry["review_proposal"],
            enable_dynamic_review_interrupt=enable_dynamic_review_interrupt,
        ),
    )
    if enable_dynamic_review_interrupt:
        graph.add_conditional_edges(
            "human_review_gate",
            route_after_human_review_gate,
            dict(registry["human_review_gate"]),
        )
    if edit_authority_request_ref is not None:
        graph.add_edge("stagger_edit_authority_gate", END)
    if repair_planning_authority_request_ref is not None:
        graph.add_edge("stagger_repair_planning_gate", END)
    dry_run_routes = dict(registry["dry_run_apply"])
    if isolated_apply_factory is not None:
        dry_run_routes["continue"] = "isolated_apply"
    graph.add_conditional_edges(
        "dry_run_apply",
        route_after_dry_run,
        dry_run_routes,
    )
    if isolated_apply_factory is not None:
        graph.add_conditional_edges(
            "isolated_apply",
            route_after_isolated_apply,
            dict(registry["isolated_apply"]),
        )
    if (
        validated_product_execution_mode is not None
        and validated_product_execution_mode.request.requested_completion_scope
        == "compile_only"
    ):
        graph.add_conditional_edges(
            "build",
            route_after_build,
            {
                "blocked": END,
                "continue": END,
                "repair": registry["build"]["repair"],
            },
        )
    elif stop_after_build or operation_controls.stop_after_build:
        graph.add_conditional_edges(
            "build",
            route_after_build,
            {"blocked": END, "continue": END, "repair": END},
        )
    else:
        graph.add_conditional_edges(
            "build",
            route_after_build,
            dict(registry["build"]),
        )
    if operation_controls.stop_after_runtime_evidence:
        graph.add_edge("collect_runtime_evidence", END)
    elif operation_handler == "runtime_execution":
        runtime_routes = dict(registry["collect_runtime_evidence"])
        runtime_routes["stop"] = END
        graph.add_conditional_edges(
            "collect_runtime_evidence",
            _route_after_typed_runtime_evidence,
            runtime_routes,
        )
    else:
        graph.add_conditional_edges(
            "collect_runtime_evidence",
            route_after_runtime_evidence,
            dict(registry["collect_runtime_evidence"]),
        )
    graph.add_conditional_edges(
        "resolve_runtime_binding",
        route_after_binding_resolution,
        dict(registry["resolve_runtime_binding"]),
    )
    graph.add_conditional_edges(
        "create_repair_plan",
        route_after_repair_plan,
        dict(registry["create_repair_plan"]),
    )
    graph.add_conditional_edges(
        "evaluate",
        (
            _route_after_terminal_evaluate
            if operation_controls.terminal_store_results
            else route_after_evaluate
        ),
        (
            {"stop": END, "blocked": "blocked", "continue": "done"}
            if operation_controls.terminal_store_results
            else dict(registry["evaluate"])
        ),
    )
    graph.add_edge("done", END)
    graph.add_edge("blocked", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        interrupt_after=effective_interrupt_after,
    )


def _review_route_map(
    route_map: dict[str, str] | Any,
    *,
    enable_dynamic_review_interrupt: bool,
) -> dict[str, str]:
    mapped = dict(route_map)
    if enable_dynamic_review_interrupt:
        mapped["continue"] = "human_review_gate"
    return mapped


def _make_real_graph_node(node_name: str, run: GraphNode) -> GraphNode:
    def _node(state: ModAgentState) -> ModAgentState:
        started = _trace_event(
            state=state,
            node_name=node_name,
            event_type="node_started",
            status="started",
            artifact_refs=[],
            summary=f"{node_name} started.",
        )
        state_with_start = _copy_state_with_trace(state, started)
        try:
            result = run(state_with_start)
        except Exception as exc:
            setattr(exc, "_mod_agent_graph_node", node_name)
            raise
        finished = _trace_event(
            state=result,
            node_name=node_name,
            event_type="node_finished",
            status=_node_status(result, node_name),
            artifact_refs=_node_artifact_refs(result, node_name),
            summary=f"{node_name} completed.",
            details=_node_trace_details(result, node_name),
        )
        return _copy_state_with_trace(result, finished)

    return _node


def _make_stub_graph_node(
    node_name: str,
    runner: StubNodeRunner,
    *,
    use_store_result: bool = False,
) -> GraphNode:
    def _node(state: ModAgentState) -> ModAgentState:
        started = _trace_event(
            state=state,
            node_name=node_name,
            event_type="node_started",
            status="started",
            artifact_refs=[],
            summary=f"{node_name} started.",
        )
        state_with_start = _copy_state_with_trace(state, started)
        additional_upstreams: tuple[ArtifactRef, ...] = ()
        if use_store_result and node_name == "blocked":
            source_type = (
                "eval_report"
                if "eval_report" in state_with_start["artifacts"]
                else "runtime_evidence"
            )
            additional_upstreams = (
                _artifact_ref_from_state(state_with_start, source_type),
            )
        try:
            result = runner.run(
                node_name,
                state_with_start,
                use_store_result=use_store_result,
                additional_upstream_refs=additional_upstreams,
            )
        except Exception as exc:
            setattr(exc, "_mod_agent_graph_node", node_name)
            raise
        finished_state = _copy_state_with_trace(
            result.state,
            result.trace_event.to_dict(),
        )
        return finished_state

    return _node


def _run_terminal_node_with_boundary(
    state: ModAgentState,
    run: GraphNode,
    *,
    failure_stage: str,
    blocker_code: str,
    use_boundary: bool,
) -> ModAgentState:
    """Normalize pre-Store terminal node failures for the public result path."""

    if not use_boundary:
        return run(state)
    try:
        return run(state)
    except Exception as exc:
        next_state = _copy_state(state)
        next_state["runtime_summary"].update(
            {
                "platform_failure_stage": failure_stage,
                "terminal_ready": False,
            }
        )
        next_state["blockers"].append(
            {
                "stage": "evaluation" if failure_stage.startswith("eval_") else "done",
                "code": blocker_code,
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
        return next_state


def _run_plan_request(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    plan = RequestPlanner().plan(
        state["user_request"],
        target_mod=state["target_mod"],
    )
    artifact_ref = artifact_store.write(
        feature_id=plan.feature_id,
        artifact_type="request_planning_report",
        payload=plan.to_artifact_payload(),
        status="blocked" if plan.blocked else "success",
    )
    next_state = _copy_state(state)
    next_state["feature_id"] = plan.feature_id
    next_state["target_mod"] = plan.target_mod
    next_state["execution_path"] = plan.route
    next_state["risk_level"] = plan.risk_level
    next_state["current_stage"] = "request_planning"
    _record_artifact(next_state, "request_planning_report", artifact_ref)
    next_state["warnings"].extend(
        uncertainty.to_dict()
        for uncertainty in plan.uncertainties
        if uncertainty.severity != "blocking"
    )
    if plan.blocked:
        next_state["blockers"].extend(
            {
                "stage": "request_planning",
                "code": uncertainty.uncertainty_id.upper(),
                "message": uncertainty.question,
            }
            for uncertainty in plan.uncertainties
            if uncertainty.severity == "blocking"
        )
    return next_state


def _run_draft_feature_spec(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    revision_projection: Mapping[str, Any] | None = None,
    approved_payload_hash: str | None = None,
    approved_projection_hash: str | None = None,
) -> ModAgentState:
    if revision_projection is not None:
        if approved_payload_hash is None or approved_projection_hash is None:
            raise ValueError(
                "FeatureSpec revision approval hashes are incomplete."
            )
        return _materialize_feature_spec_revision(
            state,
            artifact_store,
            projection=revision_projection,
            approved_payload_hash=approved_payload_hash,
            approved_projection_hash=approved_projection_hash,
        )

    plan_data = _read_artifact_data(state, artifact_store, "request_planning_report")
    plan = _request_plan_from_payload(plan_data)
    planning_brief = _read_artifact_data(state, artifact_store, "mod_planning_brief")
    feature_spec = FeatureSpecBuilder().build(
        plan,
        planning_brief=planning_brief,
    )
    artifact_ref = artifact_store.write(
        feature_id=feature_spec.feature_id,
        artifact_type="feature_spec",
        payload=feature_spec.to_artifact_payload(),
        status="blocked" if feature_spec.blocked else "success",
        upstream_refs=[
            _artifact_ref_from_state(state, "request_planning_report"),
            _artifact_ref_from_state(state, "mod_planning_brief"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "feature_spec"
    _record_artifact(next_state, "feature_spec", artifact_ref)
    if feature_spec.blocked:
        next_state["blockers"].extend(feature_spec.blockers)
    return next_state


def _run_retrieve_evidence(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    knowledge_database: KnowledgeDatabase | None,
    collection_id: str | None,
    collection_resolver: CollectionResolver | None,
    dense_provider: DenseRetrievalProvider | None,
    dense_enabled: bool,
    dense_required: bool,
    dense_top_k: int | None,
    evidence_pack_factory: EvidencePackFactory | None,
) -> ModAgentState:
    feature_data = _read_artifact_data(state, artifact_store, "feature_spec")
    if evidence_pack_factory is not None:
        pack = evidence_pack_factory(state, feature_data)
    elif knowledge_database is None:
        from src.mod_agent.evidence import EvidencePack

        pack = EvidencePack.empty(
            query=str(feature_data.get("target_behavior") or state["user_request"]),
            reason="Knowledge database is not configured for this graph run.",
        )
    else:
        request = EvidenceRequest(
            query=str(feature_data.get("target_behavior") or state["user_request"]),
            execution_path=state["execution_path"] or "standard_feature",
            requires_hook_evidence=(
                "target method" in feature_data.get("evidence_requirements", [])
            ),
            hook_requirement=_hook_requirement_from_payload(feature_data),
        )
        try:
            pack = DeterministicEvidenceRetriever(
                knowledge_database,
                collection_id=collection_id,
                collection_resolver=collection_resolver,
                dense_provider=dense_provider,
                dense_enabled=dense_enabled,
                dense_required=dense_required,
                dense_top_k=dense_top_k,
            ).retrieve(request)
        except CollectionResolutionError as exc:
            from src.mod_agent.evidence import EvidencePack

            pack = EvidencePack.empty(
                query=request.query,
                reason=f"Collection resolution failed: {exc}",
            )
    artifact_ref = artifact_store.write(
        feature_id=state["feature_id"] or state["request_id"],
        artifact_type="evidence_pack",
        payload=pack.to_artifact_payload(),
        status="success" if pack.can_generate_patch else "blocked",
        upstream_refs=[_artifact_ref_from_state(state, "feature_spec")],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "evidence_retrieval"
    next_state["evidence_summary"] = {
        "readiness": pack.readiness,
        "can_generate_patch": pack.can_generate_patch,
        "num_items": len(pack.items),
        "gaps": list(pack.gaps),
        "retrieval_methods_used": list(pack.retrieval_methods_used),
        "missing_evidence": list(pack.missing_evidence),
        "disabled_modes": dict(pack.disabled_modes),
        "timing": dict(pack.timing),
    }
    _record_artifact(next_state, "evidence_pack", artifact_ref)
    if not pack.can_generate_patch:
        next_state["blockers"].extend(pack.blockers)
    return next_state


def _run_create_implementation_plan(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    formal_requirement_coverage_required: bool = False,
    use_store_result: bool = False,
    planning_continuation_mode: PlanningContinuationInputV1 | None = None,
) -> ModAgentState:
    feature_spec = _feature_spec_from_payload(
        _read_artifact_data(state, artifact_store, "feature_spec")
    )
    evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
    implementation = ImplementationPlanner().build(
        feature_spec=feature_spec,
        evidence_pack=evidence_pack,
        formal_requirement_coverage_required=(
            formal_requirement_coverage_required
        ),
    )
    if planning_continuation_mode is not None:
        preflight_planning_continuation(
            planning_continuation_mode,
            artifact_store=artifact_store,
        )
    write_arguments = {
        "feature_id": implementation.feature_id,
        "artifact_type": "implementation_plan",
        "payload": implementation.to_artifact_payload(),
        "status": "blocked" if implementation.blocking else "success",
        "upstream_refs": [
            _artifact_ref_from_state(state, "feature_spec"),
            _artifact_ref_from_state(state, "evidence_pack"),
        ],
    }
    write_result = None
    if use_store_result:
        write_result = artifact_store.write_with_result(**write_arguments)
        artifact_ref = write_result.artifact_ref
        if write_result.outcome != "committed" or artifact_ref is None:
            raise PlanningContinuationArtifactWriteError(write_result)
    else:
        artifact_ref = artifact_store.write(**write_arguments)
    next_state = _copy_state(state)
    next_state["current_stage"] = "implementation_plan"
    _record_artifact(next_state, "implementation_plan", artifact_ref)
    if write_result is not None:
        next_state["runtime_summary"][
            "planning_artifact_write_result"
        ] = write_result.to_dict()
    if implementation.blocking:
        next_state["blockers"].extend(implementation.blockers)
    return next_state


def _run_generate_patch_proposal(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    proposal_git_binding_factory: ProposalGitBindingFactory | None = None,
    patch_change_factory: PatchChangeFactory | None = None,
    source_snippet_char_limit: int = 6000,
) -> ModAgentState:
    if state["current_stage"] == "repair_plan" and "repair_plan" in state["artifacts"]:
        repair_plan = _read_artifact_data(state, artifact_store, "repair_plan")
        implementation = _read_artifact_data(
            state,
            artifact_store,
            "implementation_plan",
        )
        evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
        if patch_change_factory is not None:
            implementation = {
                **implementation,
                "proposed_changes": list(
                    patch_change_factory(state, implementation, evidence_pack)
                ),
            }
        proposal = RepairPatchProposalBuilder().build(
            repair_plan,
            implementation_plan=implementation,
        )
        repair_context_pack = dict(proposal.context_pack)
        repair_context_pack["artifact_hashes"] = {
            key: value
            for key, value in state["artifact_hashes"].items()
            if key in {"feature_spec", "evidence_pack", "implementation_plan"}
        }
        repair_context_pack["implementation_plan_hash"] = state[
            "artifact_hashes"
        ].get("implementation_plan")
        proposal = replace(proposal, context_pack=repair_context_pack)
        upstream_refs = [
            _artifact_ref_from_state(state, "implementation_plan"),
            _artifact_ref_from_state(state, "repair_plan"),
            _artifact_ref_from_state(state, "evidence_pack"),
        ]
    else:
        implementation = _read_artifact_data(state, artifact_store, "implementation_plan")
        evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
        if patch_change_factory is not None:
            implementation = {
                **implementation,
                "proposed_changes": list(
                    patch_change_factory(state, implementation, evidence_pack)
                ),
            }
        proposal = PatchProposalBuilder().build(
            implementation,
            evidence_pack=evidence_pack,
            artifact_hashes=dict(state["artifact_hashes"]),
            git_binding=(
                proposal_git_binding_factory()
                if proposal_git_binding_factory is not None
                else None
            ),
            require_git_binding=proposal_git_binding_factory is not None,
            source_snippet_char_limit=source_snippet_char_limit,
        )
        upstream_refs = [
            _artifact_ref_from_state(state, "implementation_plan"),
            _artifact_ref_from_state(state, "evidence_pack"),
        ]
    artifact_ref = artifact_store.write(
        feature_id=proposal.feature_id,
        artifact_type="patch_proposal",
        payload=proposal.to_artifact_payload(),
        status="blocked" if proposal.blocked else "success",
        upstream_refs=upstream_refs,
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "patch_proposal"
    _record_artifact(next_state, "patch_proposal", artifact_ref)
    if proposal.blocked:
        next_state["blockers"].extend(proposal.blockers)
    return next_state


def _default_proposal_git_binding_factory() -> dict[str, Any]:
    try:
        snapshot = _project_git_repository().working_tree_snapshot()
    except GitCommandError as exc:
        return {
            "status": "unavailable",
            "base_revision": None,
            "error": str(exc),
        }
    return {
        "status": "available",
        "base_revision": snapshot.base_revision,
        "branch": snapshot.branch,
        "is_dirty": snapshot.is_dirty,
        "diff_hash": snapshot.diff_hash,
        "dirty_tree_policy": snapshot.dirty_tree_policy,
    }


def _project_git_repository() -> GitRepository:
    base_repository = GitRepository(_PROJECT_ROOT)
    git_dir = _PROJECT_ROOT / ".git"
    return GitRepository(
        _PROJECT_ROOT,
        git_executable=(
            *base_repository.git_command,
            "--git-dir",
            str(git_dir),
            "--work-tree",
            str(_PROJECT_ROOT),
        ),
    )


def _run_review_proposal(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    domain_adapter_registry: DomainAdapterRegistry | None = None,
    domain_review_policy: DomainReviewPolicy | None = None,
    require_executable_patch: bool = False,
    proposal_critic: ProposalCritic | None = None,
    critic_requirement: CriticRequirement = "not_required",
    proposal_review_context_factory: ProposalReviewContextFactory | None = None,
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    implementation_plan = _read_artifact_data(
        state,
        artifact_store,
        "implementation_plan",
    )
    evidence_pack = _read_artifact_data(state, artifact_store, "evidence_pack")
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    repair_plan = (
        _read_artifact_data(state, artifact_store, "repair_plan")
        if "repair_plan" in state["artifacts"]
        else None
    )
    if repair_plan is not None and proposal_review_context_factory is not None:
        implementation_plan, evidence_pack = proposal_review_context_factory(
            state,
            implementation_plan,
            evidence_pack,
        )
        if not isinstance(implementation_plan, dict) or not isinstance(
            evidence_pack, dict
        ):
            raise TypeError(
                "Proposal review context factory must return implementation and "
                "evidence dictionaries."
            )
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    critic_payload: dict[str, Any] | None = None
    critic_ref: ArtifactRef | None = None
    if critic_requirement == "required" and proposal_critic is not None:
        try:
            critic_assessment = proposal_critic.assess(
                proposal,
                subject_artifact_ref=proposal_ref.path,
                subject_artifact_hash=proposal_ref.artifact_hash,
            )
        except Exception as exc:  # fail closed at the external Critic boundary
            critic_assessment = CriticAssessment(
                assessor_id=type(proposal_critic).__name__ or "unidentified_critic",
                assessor_kind="unresolved",
                subject_artifact_ref=proposal_ref.path,
                subject_artifact_hash=proposal_ref.artifact_hash,
                dimension_scores={dimension: 0 for dimension in CRITIC_DIMENSIONS},
                total_score=0,
                verdict="unresolved",
                findings=(
                    CriticFinding(
                        dimension="evidence_grounding",
                        level="blocking",
                        message=f"Critic execution failed with {type(exc).__name__}.",
                    ),
                ),
                limitations=("The Critic result was not available for this review.",),
            )
        critic_payload = critic_assessment.to_artifact_payload()
        critic_ref = artifact_store.write(
            feature_id=proposal["feature_id"],
            artifact_type="critic_assessment",
            payload=critic_payload,
            status="success" if critic_assessment.verdict == "pass" else "blocked",
            upstream_refs=[
                _artifact_ref_from_state(state, "feature_spec"),
                _artifact_ref_from_state(state, "evidence_pack"),
                _artifact_ref_from_state(state, "implementation_plan"),
                proposal_ref,
            ],
            exact_revision_upstream_types={"patch_proposal"},
        )

    review = ProposalReviewer().review(
        proposal,
        evidence_pack=evidence_pack,
        repair_plan=repair_plan,
        implementation_plan=implementation_plan,
        feature_spec=feature_spec,
        artifact_hashes=dict(state["artifact_hashes"]),
        critic_assessment=critic_payload,
        require_critic_assessment=critic_requirement == "required",
        domain_policy=(
            domain_review_policy
            if domain_review_policy is not None
            else _domain_review_policy_from_state(
                state,
                domain_adapter_registry,
            )
        ),
        permission_level="dry_run_write",
        require_executable_patch=require_executable_patch,
    )
    artifact_ref = artifact_store.write(
        feature_id=proposal["feature_id"],
        artifact_type="proposal_review",
        payload=review.to_artifact_payload(),
        status="success" if review.allowed_next_stage == "dry_run_apply" else "blocked",
        upstream_refs=[proposal_ref, *([critic_ref] if critic_ref is not None else [])],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "proposal_review"
    next_state["review_summary"] = {
        "decision": review.decision,
        "allowed_next_stage": review.allowed_next_stage,
        "num_findings": len(review.findings),
        "critic_gate": dict(review.critic_gate),
        "semantic_assurance": review.semantic_assurance.to_dict(),
        "human_semantic_review_required": (
            review.human_semantic_review_required
        ),
    }
    _record_artifact(next_state, "proposal_review", artifact_ref)
    if critic_ref is not None:
        _record_artifact(next_state, "critic_assessment", critic_ref)
    if review.allowed_next_stage != "dry_run_apply":
        next_state["blockers"].extend(
            {
                "stage": "proposal_review",
                "code": finding.rule_id.upper(),
                "message": finding.message,
            }
            for finding in review.findings
            if finding.level == "blocking"
        )
    return next_state


def _domain_review_policy_from_state(
    state: ModAgentState,
    domain_adapter_registry: DomainAdapterRegistry | None,
) -> DomainReviewPolicy | None:
    """Resolve the review policy for a workflow run."""

    registry = domain_adapter_registry or _default_domain_adapter_registry()
    target_domain = state.get("target_domain")
    if not target_domain:
        return None

    adapter_name = target_domain
    if target_domain == "gtfo" and GTFO_DOMAIN_NAME in registry.names():
        adapter_name = GTFO_DOMAIN_NAME

    try:
        adapter = registry.get(adapter_name)
    except KeyError:
        adapter = UnsupportedDomainAdapter()

    return adapter.identify_project(".").review_policy()


def _run_dynamic_human_review_gate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    if review.get("allowed_next_stage") != "dry_run_apply":
        return _copy_state(state)
    if state["approvals"].get("review") is True:
        return _copy_state(state)

    request = _dynamic_review_interrupt_request(state, artifact_store)
    resume_value = interrupt(request.to_dict())

    checkpoint_store = WorkflowCheckpointStore(artifact_store)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        state,
        interrupt_reason=request.reason,
        resume_allowed_fields=("approvals.review",),
    )
    checkpoint = artifact_store.read(checkpoint_ref)["data"]
    payload = _resume_payload_from_dynamic_value(
        resume_value,
        state=state,
        checkpoint=checkpoint,
    )
    decision, resume_report_ref = checkpoint_store.resume(checkpoint_ref, payload)

    next_state = _copy_state(state)
    _record_artifact(next_state, "workflow_checkpoint", checkpoint_ref)
    _record_artifact(next_state, "resume_report", resume_report_ref)
    approvals = decision.applied_updates.get("approvals")
    if isinstance(approvals, dict):
        next_state["approvals"] = {
            **dict(next_state["approvals"]),
            **approvals,
        }
    if not decision.allowed:
        next_state["blockers"].extend(decision.blockers)
    return next_state


def _validate_graph_edit_authority_exact_inputs(
    *,
    artifact_store: ArtifactStore,
    feature_id: str,
    request: Mapping[str, Any],
    request_envelope: Mapping[str, Any],
) -> None:
    upstreams = request_envelope.get("inputs", {}).get(
        "upstream_artifacts",
        (),
    )
    if not isinstance(upstreams, list):
        raise ValueError("Edit Authority Request upstreams are invalid.")
    try:
        bindings = bind_edit_authority_exact_input_upstreams(request, upstreams)
    except InvalidEditAuthorityApprovalIdentityError as exc:
        raise ValueError(str(exc)) from exc
    if not bindings:
        return
    refs_by_identity: dict[tuple[str, str], list[ArtifactRef]] = {}
    for item in upstreams:
        if not isinstance(item, Mapping):
            raise ValueError("Edit Authority Request upstream is invalid.")
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
        for ref in artifact_store.list_feature_artifacts(feature_id)
    }
    input_facts: list[dict[str, Any]] = []
    for requirement, _ in bindings:
        key = (
            str(requirement.get("artifact_type")),
            str(requirement.get("artifact_hash")),
        )
        matches = refs_by_identity.get(key)
        if not matches:
            raise ValueError("Edit Authority exact input lineage is incomplete.")
        ref = matches.pop(0)
        artifact_store.read(ref)
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
                "recursive_fresh": artifact_store.check_freshness(ref).is_fresh,
                "exact_recursive_fresh": (
                    artifact_store.check_exact_revision_freshness(ref).is_fresh
                ),
            }
        )
    try:
        validate_edit_authority_exact_input_admission(request, input_facts)
    except InvalidEditAuthorityApprovalIdentityError as exc:
        raise ValueError(str(exc)) from exc


def _finish_stagger_edit_authority_gate(
    state: ModAgentState,
    *,
    capability: EditAuthorityCapabilityDeclaration,
    feature_id: str,
    approval_identity_hash: str,
    store_steps: tuple[EditAuthorityStoreStepV1, ...],
    payload_decision: str | None,
    resume_decision_status: str | None,
    resume_decision_allowed: bool | None,
    execution_failure_stage: str | None = None,
    platform_blockers: tuple[dict[str, Any], ...] = (),
) -> ModAgentState:
    """Project the sole machine result, then derive legacy Graph state."""

    machine_result = project_edit_authority_review_result(
        capability=capability,
        feature_id=feature_id,
        approval_identity_hash=approval_identity_hash,
        store_steps=store_steps,
        payload_decision=payload_decision,
        resume_decision_status=resume_decision_status,
        resume_decision_allowed=resume_decision_allowed,
        execution_failure_stage=execution_failure_stage,
        platform_blockers=platform_blockers,
    )
    next_state = _copy_state(state)
    next_state["edit_authority_review_result"] = machine_result.to_dict()
    for ref in (
        *machine_result.protocol_outputs,
        *machine_result.materialization_outputs,
    ):
        _record_artifact(next_state, ref.artifact_type, ref)

    if (
        machine_result.platform_status == "completed"
        and machine_result.review_outcome == "approved"
        and machine_result.materialization_status == "completed"
    ):
        next_state["current_stage"] = capability.terminal_stage
        next_state["approvals"] = {
            **dict(next_state["approvals"]),
            "edit_authority": True,
        }
        return next_state

    next_state["current_stage"] = "blocked"
    details = (
        machine_result.platform_blockers
        or machine_result.review_reasons
        or (
            {
                "stage": machine_result.failure_stage
                or "edit_authority_approval",
                "code": "EDIT_AUTHORITY_REVIEW_NOT_COMPLETED",
                "message": (
                    "Edit Authority review stopped before a complete approved "
                    "materialization."
                ),
            },
        )
    )
    next_state["blockers"].extend(copy.deepcopy(list(details)))
    return next_state


def _run_stagger_edit_authority_gate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    request_ref: ArtifactRef,
) -> ModAgentState:
    """Approve one exact request in-graph, then project bounded records."""

    feature_id = state["feature_id"] or state["request_id"]
    if request_ref.feature_id != feature_id:
        raise ValueError(
            "EditAuthorityRequest feature does not match graph state."
        )
    request_envelope = artifact_store.read_for_stage(
        request_ref,
        consumer_stage="edit_authority_approval",
    )
    request = request_envelope["data"]
    if (
        request.get("feature_id") != feature_id
        or request.get("run_id") != state["run_id"]
        or request.get("authority_granted") is not False
    ):
        raise ValueError(
            "EditAuthorityRequest identity or no-authority boundary is invalid."
        )
    _validate_graph_edit_authority_exact_inputs(
        artifact_store=artifact_store,
        feature_id=feature_id,
        request=request,
        request_envelope=request_envelope,
    )

    gate_state = _copy_state(state)
    gate_state["current_stage"] = "edit_authority_approval"
    _record_artifact(gate_state, "edit_authority_request", request_ref)
    request_payload = request.get("request_payload")
    try:
        capability, _, _ = validate_edit_authority_request_identity(
            request,
            allow_legacy=False,
        )
        identity_sections = edit_authority_identity_sections(
            request,
            allow_legacy=False,
        )
    except (
        InvalidEditAuthorityApprovalIdentityError,
        UnsupportedEditAuthorityCapabilityError,
    ) as exc:
        raise ValueError(str(exc)) from exc
    if (
        capability.checkpoint_input_mode
        == "request_and_registered_upstreams"
    ):
        for upstream in request_envelope.get("inputs", {}).get(
            "upstream_artifacts",
            (),
        ):
            if (
                isinstance(upstream, dict)
                and isinstance(upstream.get("artifact_type"), str)
                and isinstance(upstream.get("path"), str)
                and isinstance(
                    upstream.get("artifact_hash"),
                    str,
                )
            ):
                _record_artifact(
                    gate_state,
                    str(upstream["artifact_type"]),
                    ArtifactRef(
                        feature_id=feature_id,
                        artifact_type=str(
                            upstream["artifact_type"]
                        ),
                        path=str(upstream["path"]),
                        artifact_hash=str(
                            upstream["artifact_hash"]
                        ),
                    ),
                )
    execution_contract = identity_sections["execution_contract_summary"]
    allowed_actions = list(execution_contract["allowed_actions"])
    forbidden_actions = list(execution_contract["forbidden_actions"])
    interrupt_request = InterruptRequest(
        interrupt_id=f"interrupt_{uuid4().hex}",
        run_id=state["run_id"],
        feature_id=feature_id,
        stage="edit_authority_approval",
        reason=(
            "exact EditAuthorityRequest requires human approval before "
            "Registry projection"
        ),
        payload={
            "node_name": "stagger_edit_authority_gate",
            "stage": "edit_authority_approval",
            "required_decision": ["approve", "reject"],
            "edit_authority_request_revision": {
                "feature_id": request_ref.feature_id,
                "path": request_ref.path,
                "artifact_hash": request_ref.artifact_hash,
            },
            "request_hash": request["request_hash"],
            "approval_identity_mode": identity_sections["identity_mode"],
            "approval_identity_schema_version": identity_sections[
                "identity_schema_version"
            ],
            "allowed_actions": allowed_actions,
            "forbidden_actions": forbidden_actions,
        },
        resume_allowed_fields=("approvals.edit_authority",),
        artifact_refs=tuple(gate_state["artifacts"].values()),
    )
    resume_value = interrupt(interrupt_request.to_dict())

    checkpoint_store = WorkflowCheckpointStore(artifact_store)
    store_steps: list[EditAuthorityStoreStepV1] = []
    try:
        checkpoint_result = checkpoint_store.create_checkpoint_with_result(
            gate_state,
            interrupt_reason=interrupt_request.reason,
            resume_allowed_fields=("approvals.edit_authority",),
        )
    except Exception as exc:
        return _finish_stagger_edit_authority_gate(
            gate_state,
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=str(request["request_hash"]),
            store_steps=(),
            payload_decision=None,
            resume_decision_status=None,
            resume_decision_allowed=None,
            execution_failure_stage="checkpoint_construction",
            platform_blockers=(
                {
                    "stage": "checkpoint_construction",
                    "code": "EDIT_AUTHORITY_CHECKPOINT_CONSTRUCTION_FAILED",
                    "message": str(exc),
                },
            ),
        )
    store_steps.append(
        EditAuthorityStoreStepV1(
            role="workflow_checkpoint",
            store_result=checkpoint_result,
        )
    )
    checkpoint_ref = checkpoint_result.artifact_ref
    if checkpoint_result.outcome != "committed" or checkpoint_ref is None:
        return _finish_stagger_edit_authority_gate(
            gate_state,
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=str(request["request_hash"]),
            store_steps=tuple(store_steps),
            payload_decision=None,
            resume_decision_status=None,
            resume_decision_allowed=None,
        )
    try:
        checkpoint = artifact_store.read(checkpoint_ref)["data"]
        payload = _resume_payload_from_dynamic_value(
            resume_value,
            state=gate_state,
            checkpoint=checkpoint,
        )
        decision, report_result = checkpoint_store.resume_with_result(
            checkpoint_ref,
            payload,
        )
    except Exception as exc:
        return _finish_stagger_edit_authority_gate(
            gate_state,
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=str(request["request_hash"]),
            store_steps=tuple(store_steps),
            payload_decision=None,
            resume_decision_status=None,
            resume_decision_allowed=None,
            execution_failure_stage="resume_validation",
            platform_blockers=(
                {
                    "stage": "resume_validation",
                    "code": "EDIT_AUTHORITY_RESUME_VALIDATION_FAILED",
                    "message": str(exc),
                },
            ),
        )
    store_steps.append(
        EditAuthorityStoreStepV1(
            role="resume_report",
            store_result=report_result,
        )
    )
    report_ref = report_result.artifact_ref
    if report_result.outcome != "committed" or report_ref is None:
        return _finish_stagger_edit_authority_gate(
            gate_state,
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=str(request["request_hash"]),
            store_steps=tuple(store_steps),
            payload_decision=payload.decision,
            resume_decision_status=decision.status,
            resume_decision_allowed=decision.allowed,
            platform_blockers=tuple(decision.blockers),
        )
    if not decision.allowed or payload.decision != "approve":
        return _finish_stagger_edit_authority_gate(
            gate_state,
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=str(request["request_hash"]),
            store_steps=tuple(store_steps),
            payload_decision=payload.decision,
            resume_decision_status=decision.status,
            resume_decision_allowed=decision.allowed,
            platform_blockers=tuple(decision.blockers),
        )

    try:
        materialized = materialize_stagger_edit_authority_approval(
            artifact_store_root=artifact_store.root,
            feature_id=feature_id,
            edit_authority_request_path=request_ref.path,
            edit_authority_request_hash=request_ref.artifact_hash,
            resume_report_path=report_ref.path,
            resume_report_hash=report_ref.artifact_hash,
        )
        materialization_steps = materialized.get("store_steps")
        if not isinstance(materialization_steps, tuple) or any(
            not isinstance(step, EditAuthorityStoreStepV1)
            for step in materialization_steps
        ):
            raise StaggerEditAuthorityApprovalError(
                "Edit Authority materializer omitted typed Store results."
            )
        store_steps.extend(materialization_steps)
    except StaggerEditAuthorityMaterializationError as exc:
        store_steps.extend(exc.store_steps)
        return _finish_stagger_edit_authority_gate(
            gate_state,
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=str(request["request_hash"]),
            store_steps=tuple(store_steps),
            payload_decision=payload.decision,
            resume_decision_status=decision.status,
            resume_decision_allowed=decision.allowed,
            execution_failure_stage=exc.failure_stage,
            platform_blockers=(
                {
                    "stage": exc.failure_stage,
                    "code": "EDIT_AUTHORITY_MATERIALIZATION_FAILED",
                    "message": str(exc),
                },
            ),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return _finish_stagger_edit_authority_gate(
            gate_state,
            capability=capability,
            feature_id=feature_id,
            approval_identity_hash=str(request["request_hash"]),
            store_steps=tuple(store_steps),
            payload_decision=payload.decision,
            resume_decision_status=decision.status,
            resume_decision_allowed=decision.allowed,
            execution_failure_stage="materialization_validation",
            platform_blockers=(
                {
                    "stage": "materialization_validation",
                    "code": "EDIT_AUTHORITY_MATERIALIZATION_VALIDATION_FAILED",
                    "message": str(exc),
                },
            ),
        )

    return _finish_stagger_edit_authority_gate(
        gate_state,
        capability=capability,
        feature_id=feature_id,
        approval_identity_hash=str(request["request_hash"]),
        store_steps=tuple(store_steps),
        payload_decision=payload.decision,
        resume_decision_status=decision.status,
        resume_decision_allowed=decision.allowed,
    )


def _materialize_feature_spec_revision(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    projection: Mapping[str, Any],
    approved_payload_hash: str,
    approved_projection_hash: str,
) -> ModAgentState:
    """Materialize one approved FeatureSpec revision through its graph node."""

    if state["approvals"].get(_FEATURE_SPEC_REVISION_APPROVAL_KEY) is not True:
        raise ValueError(
            "FeatureSpec revision materialization lacks node-level human approval."
        )
    if set(projection) != _FEATURE_SPEC_REVISION_PROJECTION_FIELDS:
        raise ValueError(
            "FeatureSpec revision projection fields do not match the approved shape."
        )
    payload = projection.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("FeatureSpec revision payload must be an object.")
    if set(payload) != _FEATURE_SPEC_REVISION_PAYLOAD_FIELDS:
        raise ValueError(
            "FeatureSpec revision payload fields do not match the approved shape."
        )

    payload_hash = _canonical_sha256(payload)
    projection_hash = _canonical_sha256(projection)
    if payload_hash != approved_payload_hash:
        raise ValueError("FeatureSpec revision payload hash is not approved.")
    if projection_hash != approved_projection_hash:
        raise ValueError("FeatureSpec revision projection hash is not approved.")

    feature_id = state.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("FeatureSpec revision state feature_id is missing.")
    if (
        projection.get("schema_version") != "1.0"
        or projection.get("artifact_type") != "feature_spec"
        or projection.get("feature_id") != feature_id
        or projection.get("producer_stage") != "feature_spec"
        or projection.get("status") != "success"
        or projection.get("blockers") != []
        or payload.get("feature_id") != feature_id
        or payload.get("node_name") != "draft_feature_spec"
        or payload.get("stage") != "feature_spec"
    ):
        raise ValueError("FeatureSpec revision identity metadata drifted.")

    contract = artifact_store.registry.validate_write(
        artifact_type="feature_spec",
        status="success",
        payload=payload,
    )
    if (
        contract.schema_version != projection["schema_version"]
        or contract.producer_stage != projection["producer_stage"]
    ):
        raise ValueError("FeatureSpec revision Registry contract drifted.")
    _validate_feature_spec_revision_semantics(payload)

    inputs = projection.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {"upstream_artifacts"}:
        raise ValueError("FeatureSpec revision inputs do not match the approved shape.")
    upstreams = inputs.get("upstream_artifacts")
    if not isinstance(upstreams, list) or len(upstreams) != 1:
        raise ValueError(
            "FeatureSpec revision requires exactly one RequestPlan upstream."
        )
    upstream = upstreams[0]
    if (
        not isinstance(upstream, Mapping)
        or set(upstream)
        != {"artifact_type", "path", "artifact_hash", "require_latest"}
        or upstream.get("artifact_type") != "request_planning_report"
        or upstream.get("require_latest") is not True
    ):
        raise ValueError("FeatureSpec revision RequestPlan upstream drifted.")
    request_ref = ArtifactRef(
        feature_id=feature_id,
        artifact_type="request_planning_report",
        path=str(upstream["path"]),
        artifact_hash=str(upstream["artifact_hash"]),
    )
    if (
        state["artifacts"].get("request_planning_report") != request_ref.path
        or state["artifact_hashes"].get("request_planning_report")
        != request_ref.artifact_hash
    ):
        raise ValueError(
            "FeatureSpec revision state does not bind the approved RequestPlan."
        )
    artifact_store.read(request_ref)
    latest_request = _latest_feature_artifact_ref(
        artifact_store,
        feature_id=feature_id,
        artifact_type="request_planning_report",
    )
    if latest_request.artifact_hash != request_ref.artifact_hash:
        raise ValueError("FeatureSpec revision RequestPlan is not latest.")

    predecessor_hash = payload.get("supersedes_artifact_hash")
    if not isinstance(predecessor_hash, str) or not predecessor_hash:
        raise ValueError("FeatureSpec revision predecessor identity is missing.")
    latest_feature_spec = _latest_feature_artifact_ref(
        artifact_store,
        feature_id=feature_id,
        artifact_type="feature_spec",
    )
    artifact_store.read(latest_feature_spec)
    if latest_feature_spec.artifact_hash != predecessor_hash:
        raise ValueError(
            "FeatureSpec revision predecessor is not the current latest revision."
        )

    trace_refs = projection.get("trace_refs")
    if not isinstance(trace_refs, list) or any(
        not isinstance(item, str) or not item for item in trace_refs
    ):
        raise ValueError("FeatureSpec revision trace refs are invalid.")
    expected_artifact_hash = artifact_store._stable_hash(
        {
            "schema_version": projection["schema_version"],
            "artifact_type": projection["artifact_type"],
            "feature_id": feature_id,
            "producer_stage": projection["producer_stage"],
            "status": projection["status"],
            "data": dict(payload),
            "inputs": dict(inputs),
            "blockers": [],
            "trace_refs": list(trace_refs),
        }
    )
    before_revisions = artifact_store.list_feature_artifact_revisions(
        feature_id,
        "feature_spec",
    )
    if any(ref.artifact_hash == expected_artifact_hash for ref in before_revisions):
        raise ValueError(
            "FeatureSpec revision approval was already materialized and cannot replay."
        )

    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=payload,
        status="success",
        blockers=[],
        trace_refs=list(trace_refs),
        upstream_refs=[request_ref],
    )
    after_revisions = artifact_store.list_feature_artifact_revisions(
        feature_id,
        "feature_spec",
    )
    if (
        artifact_ref.artifact_hash != expected_artifact_hash
        or len(after_revisions) != len(before_revisions) + 1
    ):
        raise ValueError(
            "FeatureSpec revision materialization did not create exactly one revision."
        )

    next_state = _copy_state(state)
    next_state["current_stage"] = "feature_spec"
    next_state["next_stage"] = None
    _record_artifact(next_state, "feature_spec", artifact_ref)
    return next_state


def _validate_feature_spec_revision_semantics(payload: Mapping[str, Any]) -> None:
    hypotheses = payload.get("operator_guided_technical_hypotheses")
    if not isinstance(hypotheses, Mapping):
        raise ValueError("FeatureSpec revision hypotheses are invalid.")
    items = hypotheses.get("hypotheses")
    if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
        raise ValueError("FeatureSpec revision active hypotheses are invalid.")
    active_ids = {item.get("id") for item in items}
    if active_ids & _DEFERRED_CORRELATION_HYPOTHESIS_IDS:
        raise ValueError(
            "FeatureSpec revision reintroduced deferred correlation hypotheses."
        )
    evidence_requirements = payload.get("evidence_requirements")
    runtime_plan = payload.get("runtime_verification_plan")
    if not isinstance(evidence_requirements, list) or not isinstance(runtime_plan, list):
        raise ValueError("FeatureSpec revision verification fields are invalid.")
    if any(
        token in item
        for item in evidence_requirements
        if isinstance(item, str)
        for token in (
            "one-time consumption",
            "Dam_EnemyDamageBase.BulletDamage may",
            "ES_Hitreact.DoHitReact may",
        )
    ) or any(
        token in item
        for item in runtime_plan
        if isinstance(item, str)
        for token in ("correlation/deduplication", "same physical hit")
    ):
        raise ValueError(
            "FeatureSpec revision reintroduced deferred correlation requirements."
        )


def _latest_feature_artifact_ref(
    artifact_store: ArtifactStore,
    *,
    feature_id: str,
    artifact_type: str,
) -> ArtifactRef:
    refs = [
        ref
        for ref in artifact_store.list_feature_artifacts(feature_id)
        if ref.artifact_type == artifact_type
    ]
    if len(refs) != 1:
        raise ValueError(
            f"FeatureSpec revision expected one latest {artifact_type} Artifact."
        )
    return refs[0]


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _run_stagger_repair_planning_gate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    request_ref: ArtifactRef,
) -> ModAgentState:
    """Approve one exact planning Request before materialization or Planner."""

    feature_id = state["feature_id"] or state["request_id"]
    if request_ref.feature_id != feature_id:
        raise ValueError(
            "Repair planning Request feature does not match graph state."
        )
    request_envelope = artifact_store.read_for_stage(
        request_ref,
        consumer_stage="repair_planning_approval",
    )
    request = request_envelope["data"]
    if (
        request.get("feature_id") != feature_id
        or request.get("run_id") != state["run_id"]
        or request.get("authority_granted") is not False
        or request.get("artifact_materialization_allowed") is not False
        or request.get("repair_planner_allowed") is not False
    ):
        raise ValueError(
            "Repair planning Request identity or no-authority boundary is invalid."
        )
    gate_state = _copy_state(state)
    gate_state["current_stage"] = "repair_planning_approval"
    _record_artifact(
        gate_state,
        "repair_planning_request",
        request_ref,
    )
    interrupt_request = InterruptRequest(
        interrupt_id=f"interrupt_{uuid4().hex}",
        run_id=state["run_id"],
        feature_id=feature_id,
        stage="repair_planning_approval",
        reason=(
            "exact Repair planning Request requires human approval before "
            "Artifact materialization or RepairPlanner invocation"
        ),
        payload={
            "node_name": "stagger_repair_planning_gate",
            "stage": "repair_planning_approval",
            "required_decision": ["approve", "reject"],
            "repair_planning_authority_request_revision": {
                "feature_id": request_ref.feature_id,
                "path": request_ref.path,
                "artifact_hash": request_ref.artifact_hash,
            },
            "request_hash": request["request_hash"],
            "allowed_actions": [
                "materialize_root_cause_evidence",
                "materialize_repair_hypothesis_set",
                "invoke_repair_planner_for_semantic_decision",
                "materialize_repair_plan",
            ],
            "forbidden_actions": [
                "modify_source",
                "build",
                "launch_process",
                "write_game_directory",
                "claim_product_acceptance",
                "claim_audio_audibility",
            ],
        },
        resume_allowed_fields=("approvals.repair_planning",),
        artifact_refs=tuple(gate_state["artifacts"].values()),
    )
    resume_value = interrupt(interrupt_request.to_dict())
    checkpoint_store = WorkflowCheckpointStore(artifact_store)
    checkpoint_ref = checkpoint_store.create_checkpoint(
        gate_state,
        interrupt_reason=interrupt_request.reason,
        resume_allowed_fields=("approvals.repair_planning",),
    )
    checkpoint = artifact_store.read(checkpoint_ref)["data"]
    payload = _resume_payload_from_dynamic_value(
        resume_value,
        state=gate_state,
        checkpoint=checkpoint,
    )
    decision, report_ref = checkpoint_store.resume(
        checkpoint_ref,
        payload,
    )
    next_state = _copy_state(gate_state)
    _record_artifact(next_state, "workflow_checkpoint", checkpoint_ref)
    _record_artifact(next_state, "resume_report", report_ref)
    if not decision.allowed or payload.decision != "approve":
        next_state["current_stage"] = "blocked"
        next_state["blockers"].extend(
            decision.blockers
            or (
                {
                    "stage": "repair_planning_approval",
                    "code": "REPAIR_PLANNING_AUTHORITY_REJECTED",
                    "message": (
                        "Human review did not approve the exact Repair "
                        "planning Request."
                    ),
                },
            )
        )
        return next_state
    try:
        materialized = materialize_stagger_planning_approval(
            artifact_store_root=artifact_store.root,
            feature_id=feature_id,
            repair_planning_authority_request_path=request_ref.path,
            repair_planning_authority_request_hash=(
                request_ref.artifact_hash
            ),
            resume_report_path=report_ref.path,
            resume_report_hash=report_ref.artifact_hash,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        next_state["current_stage"] = "blocked"
        next_state["blockers"].append(
            {
                "stage": "repair_planning_approval",
                "code": "REPAIR_PLANNING_APPROVED_NOT_MATERIALIZED",
                "message": str(exc),
            }
        )
        return next_state
    for artifact_type, field_name in (
        (
            "repair_planning_approval",
            "repair_planning_authority_approval_revision",
        ),
        ("root_cause_evidence", "root_cause_evidence_revision"),
        (
            "repair_hypothesis_set",
            "repair_hypothesis_set_revision",
        ),
        ("repair_plan", "repair_plan_revision"),
    ):
        revision = materialized[field_name]
        _record_artifact(
            next_state,
            artifact_type,
            ArtifactRef(
                feature_id=feature_id,
                artifact_type=artifact_type,
                path=str(revision["path"]),
                artifact_hash=str(revision["artifact_hash"]),
            ),
        )
    next_state["current_stage"] = "repair_plan"
    next_state["approvals"] = {
        **dict(next_state["approvals"]),
        "repair_planning": True,
    }
    semantic = materialized["semantic_decision"]
    if semantic.get("decision") != "repair_ready":
        next_state["blockers"].extend(
            [
                dict(blocker)
                for blocker in semantic.get("blockers", ())
                if isinstance(blocker, dict)
            ]
        )
    return next_state


def _dynamic_review_interrupt_request(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> InterruptRequest:
    feature_id = state["feature_id"] or state["request_id"]
    return InterruptRequest(
        interrupt_id=f"interrupt_{uuid4().hex}",
        run_id=state["run_id"],
        feature_id=feature_id,
        stage="proposal_review",
        reason="proposal review requires human approval before dry run",
        payload={
            "node_name": "human_review_gate",
            "stage": "proposal_review",
            "required_decision": ["approve", "reject"],
            "resume_binding": _dynamic_review_resume_binding(state, artifact_store),
            "artifact_hashes": dict(state["artifact_hashes"]),
        },
        resume_allowed_fields=("approvals.review",),
        artifact_refs=tuple(state["artifacts"].values()),
    )


def _dynamic_review_resume_binding(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> dict[str, Any]:
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    review_ref = _artifact_ref_from_state(state, "proposal_review")
    proposal_payload = artifact_store.read(proposal_ref)["data"]
    serialized = json.dumps(
        proposal_payload.get("diff_intent") or [],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "patch_proposal_ref": proposal_ref.path,
        "patch_proposal_hash": proposal_ref.artifact_hash,
        "proposal_review_ref": review_ref.path,
        "proposal_review_hash": review_ref.artifact_hash,
        "diff_hash": "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }


def _resume_payload_from_dynamic_value(
    resume_value: Any,
    *,
    state: ModAgentState,
    checkpoint: dict[str, Any],
) -> ResumePayload:
    value = resume_value if isinstance(resume_value, dict) else {}
    return ResumePayload(
        resume_id=str(value.get("resume_id") or f"resume_{uuid4().hex}"),
        run_id=str(value.get("run_id") or state["run_id"]),
        stage=str(value.get("stage") or checkpoint.get("checkpoint_stage") or state["current_stage"]),
        decision=str(value.get("decision") or "reject"),
        approved_by=str(value.get("approved_by") or ""),
        approved_at=str(value.get("approved_at") or ""),
        artifact_refs=tuple(value.get("artifact_refs") or ()),
        diff_hash=value.get("diff_hash"),
        notes=str(value.get("notes") or ""),
        authority_request_hash=value.get("authority_request_hash"),
    )


def _default_domain_adapter_registry() -> DomainAdapterRegistry:
    """Return the default domain policy registry for workflow review gates."""

    return DomainAdapterRegistry((GTFOAdapter(), UnsupportedDomainAdapter()))


def _runtime_evidence_factory_from_settings(
    settings: Any | None,
    *,
    allow_game_launch: bool,
) -> RuntimeEvidenceFactory | None:
    if settings is None:
        return None
    runtime = getattr(settings, "runtime", None)
    gtfo = getattr(runtime, "gtfo", None)
    if gtfo is not None and getattr(gtfo, "enabled", False):
        return make_gtfo_runtime_evidence_factory_from_settings(
            settings,
            allow_game_launch=allow_game_launch,
        )
    return None


def _run_dry_run_apply(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    require_review_approval: bool = False,
    dry_run_factory: PatchExecutionFactory | None = None,
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    approved_by_review = review.get("allowed_next_stage") == "dry_run_apply"
    approved_by_human = state["approvals"].get("review") is True
    approved = approved_by_review and (
        not require_review_approval or approved_by_human
    )
    semantic_assurance, semantic_contract_present = (
        _semantic_assurance_for_execution(proposal, review)
    )
    human_semantic_review_required = (
        semantic_contract_present and semantic_assurance.verdict == "unproven"
    )
    changed_files = list(proposal.get("files") or [])
    diff_intent = list(proposal.get("diff_intent") or [])
    generated_payload = (
        dry_run_factory(
            proposal,
            _read_artifact_data(state, artifact_store, "implementation_plan"),
            review,
        )
        if dry_run_factory is not None and approved
        else None
    )
    payload = {
        "node_name": "dry_run_apply",
        "stage": "dry_run_apply",
        "message": (
            "Executable patch dry-run validated without writing source files."
            if generated_payload is not None
            else "Fake dry-run completed. No source files were written and no patch was applied."
        ),
        "execution_mode": "dry_run" if generated_payload is not None else "fake",
        "actual_write_performed": False,
        "real_patch_applied": False,
        "approved_by_review": approved_by_review,
        "human_approval_required": require_review_approval,
        "approved_by_human": approved_by_human,
        "proposal_id": proposal.get("proposal_id"),
        "review_decision": review.get("decision"),
        "semantic_assurance": semantic_assurance.to_dict(),
        "human_semantic_review_required": human_semantic_review_required,
        "human_semantic_review_completed": False,
        "human_semantic_review_result": (
            "pending" if human_semantic_review_required else "not_required"
        ),
        "human_semantic_decision_binding": None,
        "human_semantic_decision": None,
        "would_write": bool(diff_intent),
        "changed_files": changed_files,
        "diff_stats": {
            "files": len(changed_files),
            "change_units": len(diff_intent),
            "insertions": 0,
            "deletions": 0,
        },
        "limitations": [
            "Dry-run validation does not prove the isolated write or build succeeds."
            if generated_payload is not None
            else "This is an isolated fake dry-run artifact."
        ],
        **dict(generated_payload or {}),
    }
    status = "success" if approved else "blocked"
    artifact_ref = artifact_store.write(
        feature_id=proposal["feature_id"],
        artifact_type="dry_run_result",
        payload=payload,
        status=status,
        upstream_refs=[
            _artifact_ref_from_state(state, "patch_proposal"),
            _artifact_ref_from_state(state, "proposal_review"),
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "dry_run_apply"
    _record_artifact(next_state, "dry_run_result", artifact_ref)
    if not approved:
        next_state["blockers"].append(
            {
                "stage": "dry_run_apply",
                "code": "REVIEW_NOT_APPROVED",
                "message": "Dry-run cannot proceed without review approval.",
            }
        )
    return next_state


def _run_build(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    build_result_factory: BuildResultFactory | None,
    *,
    verification_operation: VerificationOperationEnvelope | None = None,
    persist_build_runtime_handoff: bool = False,
    exact_revision_upstream_types: frozenset[str] = frozenset(),
) -> ModAgentState:
    feature_id = state["feature_id"] or state["request_id"]
    build_continuation = (
        None
        if verification_operation is None
        else _verification_build_continuation(verification_operation)
    )
    if build_continuation is not None:
        preflight = preflight_verification_only_continuation(
            artifact_store,
            build_continuation,
            run_id=state["run_id"],
            request_id=state["request_id"],
            user_request=state["user_request"],
            target_mod=state["target_mod"],
        )
        if (
            state.get("feature_id") != build_continuation.feature_spec_ref.feature_id
            or preflight["status"] != "ready_for_build_authorization"
        ):
            next_state = _copy_state(state)
            next_state["current_stage"] = "build"
            next_state["build_summary"] = {
                "status": "blocked",
                "input_execution_mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
                "preflight_hash": preflight["projection_hash"],
                "platform_failure_stage": "admission",
            }
            preflight_blockers = list(preflight["blockers"])
            if (
                state.get("feature_id")
                != build_continuation.feature_spec_ref.feature_id
            ):
                preflight_blockers.append(
                    {
                        "code": "VERIFICATION_STATE_FEATURE_ID_MISMATCH",
                        "message": "Graph state feature_id changed after verification admission.",
                    }
                )
            next_state["blockers"].extend(
                {
                    "stage": "build",
                    "code": blocker["code"],
                    "message": blocker["message"],
                }
                for blocker in preflight_blockers
            )
            return next_state
        input_execution_mode = VERIFICATION_ONLY_INPUT_EXECUTION_MODE
        build_upstream_refs = [
            build_continuation.feature_spec_ref,
            build_continuation.evidence_pack_ref,
        ]
    else:
        dry_run = _read_artifact_data(state, artifact_store, "dry_run_result")
        apply_result = (
            _read_artifact_data(state, artifact_store, "isolated_apply_result")
            if "isolated_apply_result" in state["artifacts"]
            else None
        )
        input_execution_mode = (
            apply_result.get("execution_mode")
            if apply_result is not None
            else dry_run.get("execution_mode")
        )
        build_upstream_refs = [
            _artifact_ref_from_state(state, "dry_run_result"),
            *(
                [_artifact_ref_from_state(state, "isolated_apply_result")]
                if "isolated_apply_result" in state["artifacts"]
                else []
            ),
        ]
    result = (
        build_result_factory(feature_id, input_execution_mode)
        if build_result_factory is not None
        else build_fake_build_result(
            feature_id=feature_id,
            input_execution_mode=input_execution_mode,
        )
    )
    try:
        payload = result.to_artifact_payload()
        post_build_preflight = (
            preflight_verification_only_continuation(
                artifact_store,
                build_continuation,
                run_id=state["run_id"],
                request_id=state["request_id"],
                user_request=state["user_request"],
                target_mod=state["target_mod"],
            )
            if build_continuation is not None
            else None
        )
        build_validation_blockers = (
            validate_verification_only_build_result(payload, post_build_preflight)
            if post_build_preflight is not None
            else []
        )
    except Exception as exc:
        if build_continuation is None:
            raise
        next_state = _copy_state(state)
        next_state["current_stage"] = "build"
        next_state["build_summary"] = {
            "status": "blocked",
            "input_execution_mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
            "preflight_hash": preflight["projection_hash"],
            "platform_failure_stage": "post_build_validation",
        }
        next_state["blockers"].append(
            {
                "stage": "build",
                "code": "VERIFICATION_POST_BUILD_VALIDATION_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
        return next_state
    if build_continuation is not None:
        if post_build_preflight is None:
            raise AssertionError("Verification post-Build preflight is missing.")
        if (
            post_build_preflight["status"]
            != "ready_for_build_authorization"
            or post_build_preflight["projection_hash"]
            != preflight["projection_hash"]
        ):
            next_state = _copy_state(state)
            next_state["current_stage"] = "build"
            next_state["build_summary"] = {
                "status": "blocked",
                "input_execution_mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
                "preflight_hash": preflight["projection_hash"],
                "post_build_preflight_hash": post_build_preflight[
                    "projection_hash"
                ],
                "platform_failure_stage": "post_build_validation",
            }
            next_state["blockers"].append(
                {
                    "stage": "build",
                    "code": "VERIFICATION_BUILD_INPUT_DRIFT",
                    "message": (
                        "Verification source or Artifact identity changed during Build."
                    ),
                }
            )
            return next_state
        if build_validation_blockers:
            next_state = _copy_state(state)
            next_state["current_stage"] = "build"
            next_state["build_summary"] = {
                "status": "blocked",
                "input_execution_mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
                "preflight_hash": preflight["projection_hash"],
                "platform_failure_stage": "post_build_validation",
            }
            next_state["blockers"].extend(
                {
                    "stage": "build",
                    "code": blocker["code"],
                    "message": blocker["message"],
                }
                for blocker in build_validation_blockers
            )
            return next_state
        payload["verification_only_lineage"] = verification_only_lineage_payload(
            post_build_preflight
        )
    if build_continuation is not None and (
        payload.get("feature_id") != feature_id
        or payload.get("input_execution_mode")
        != VERIFICATION_ONLY_INPUT_EXECUTION_MODE
    ):
        next_state = _copy_state(state)
        next_state["current_stage"] = "build"
        next_state["build_summary"] = {
            "status": "blocked",
            "input_execution_mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
            "platform_failure_stage": "post_build_validation",
        }
        next_state["blockers"].append(
            {
                "stage": "build",
                "code": "VERIFICATION_BUILD_RESULT_IDENTITY_MISMATCH",
                "message": (
                    "BuildResult does not preserve the verification-only "
                    "Feature and input execution identity."
                ),
            }
        )
        return next_state
    build_write_result = None
    if build_continuation is not None:
        build_write_result = artifact_store.write_with_result(
            feature_id=feature_id,
            artifact_type="build_result",
            payload=payload,
            status="failed" if payload["status"] == "failed" else "success",
            upstream_refs=build_upstream_refs,
        )
        artifact_ref = build_write_result.artifact_ref
    else:
        artifact_ref = artifact_store.write(
            feature_id=feature_id,
            artifact_type="build_result",
            payload=payload,
            status="failed" if payload["status"] == "failed" else "success",
            upstream_refs=build_upstream_refs,
        )
    next_state = _copy_state(state)
    next_state["current_stage"] = "build"
    next_state["build_summary"] = {
        "status": payload["status"],
        "build_status": payload["build_status"],
        "execution_mode": payload["execution_mode"],
        "real_build_performed": payload["real_build_performed"],
        "error_class": payload["error_class"],
        "repair_handoff": payload["repair_handoff"],
        "claims_real_build_success": payload["claims_real_build_success"],
        "input_execution_mode": payload.get("input_execution_mode"),
    }
    if build_continuation is not None:
        next_state["build_summary"]["domain_status"] = payload["status"]
    if build_write_result is not None and (
        build_write_result.outcome != "committed" or artifact_ref is None
    ):
        next_state["build_summary"].update(
            {
                "status": "blocked",
                "platform_failure_stage": "build_result_store",
                "build_result_store_result": build_write_result.to_dict(),
                "workflow_checkpoint_store_result": None,
            }
        )
        next_state["blockers"].append(
            {
                "stage": "build",
                "code": "VERIFICATION_BUILD_RESULT_STORE_NOT_COMMITTED",
                "message": (
                    "Verification BuildResult did not reach a committed Store outcome."
                ),
            }
        )
        return next_state
    if artifact_ref is None:
        raise ArtifactStoreError("Committed BuildResult is missing artifact_ref.")
    _record_artifact(next_state, "build_result", artifact_ref)
    checkpoint_write_result = None
    if (
        persist_build_runtime_handoff
        and payload["status"] == "success"
        and payload["claims_real_build_success"] is True
    ):
        next_state["next_stage"] = "runtime_evidence"
        checkpoint_store = WorkflowCheckpointStore(artifact_store)
        if build_continuation is not None:
            try:
                checkpoint_write_result = checkpoint_store.create_checkpoint_with_result(
                    next_state,
                    interrupt_reason=(
                        "Successful Build is ready for fresh-process Runtime continuation."
                    ),
                    resume_allowed_fields=(),
                    exact_revision_upstream_types=exact_revision_upstream_types,
                )
            except ArtifactStoreError as exc:
                next_state["build_summary"].update(
                    {
                        "status": "blocked",
                        "platform_failure_stage": "checkpoint_prewrite",
                        "build_result_store_result": build_write_result.to_dict(),
                        "workflow_checkpoint_store_result": None,
                    }
                )
                next_state["blockers"].append(
                    {
                        "stage": "build",
                        "code": "VERIFICATION_CHECKPOINT_PREWRITE_BLOCKED",
                        "message": str(exc),
                    }
                )
                return next_state
            checkpoint_ref = checkpoint_write_result.artifact_ref
            if (
                checkpoint_write_result.outcome != "committed"
                or checkpoint_ref is None
            ):
                next_state["build_summary"].update(
                    {
                        "status": "blocked",
                        "platform_failure_stage": "checkpoint_store",
                        "build_result_store_result": build_write_result.to_dict(),
                        "workflow_checkpoint_store_result": (
                            checkpoint_write_result.to_dict()
                        ),
                    }
                )
                next_state["blockers"].append(
                    {
                        "stage": "build",
                        "code": "VERIFICATION_CHECKPOINT_STORE_NOT_COMMITTED",
                        "message": (
                            "Verification workflow checkpoint did not reach a "
                            "committed Store outcome."
                        ),
                    }
                )
                return next_state
        else:
            checkpoint_ref = checkpoint_store.create_checkpoint(
                next_state,
                interrupt_reason=(
                    "Successful Build is ready for fresh-process Runtime continuation."
                ),
                resume_allowed_fields=(),
                exact_revision_upstream_types=exact_revision_upstream_types,
            )
        _record_artifact(next_state, "workflow_checkpoint", checkpoint_ref)
    if build_continuation is not None:
        next_state["build_summary"].update(
            {
                "build_result_store_result": build_write_result.to_dict(),
                "workflow_checkpoint_store_result": (
                    None
                    if checkpoint_write_result is None
                    else checkpoint_write_result.to_dict()
                ),
                "handoff_eligible": (
                    payload["status"] == "success"
                    and payload["claims_real_build_success"] is True
                ),
            }
        )
    return next_state


def _run_verification_only_admission(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    operation: VerificationOperationEnvelope,
) -> ModAgentState:
    """Hydrate one exact no-mutation lineage after a no-write preflight."""

    envelope = validate_verification_operation_envelope(operation)
    declaration = resolve_verification_operation(envelope)
    variant = envelope.variant_payload
    protocol = envelope.protocol_binding
    if (
        declaration.graph_handler != "verification_build"
        or not isinstance(variant, VerificationBuildOperationV1)
        or not isinstance(protocol, BuildInvocationProtocolBindingV1)
    ):
        raise ValueError("Verification Build operation shape changed.")
    continuation = _verification_build_continuation(envelope)
    preflight = preflight_verification_only_continuation(
        artifact_store,
        continuation,
        run_id=state["run_id"],
        request_id=state["request_id"],
        user_request=state["user_request"],
        target_mod=state["target_mod"],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "evidence_retrieval"
    next_state["evidence_summary"] = {
        "readiness": "partial",
        "can_generate_patch": False,
        "verification_only_preflight": preflight,
    }
    operation_mismatches = []
    if state.get("run_id") != protocol.run_id:
        operation_mismatches.append("run_id")
    if state.get("request_id") != protocol.request_id:
        operation_mismatches.append("request_id")
    if state.get("user_request") != variant.user_request:
        operation_mismatches.append("user_request")
    if state.get("target_domain") != variant.target_domain:
        operation_mismatches.append("target_domain")
    if state.get("target_mod") != variant.target_mod:
        operation_mismatches.append("target_mod")
    if operation_mismatches:
        next_state["build_summary"] = {
            "status": "blocked",
            "input_execution_mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
            "preflight_hash": preflight["projection_hash"],
            "platform_failure_stage": "admission",
        }
        next_state["blockers"].append(
            {
                "stage": "evidence_retrieval",
                "code": "VERIFICATION_OPERATION_STATE_MISMATCH",
                "message": (
                    "Verification Build Graph state changed approved fields: "
                    + ", ".join(operation_mismatches)
                ),
            }
        )
        return next_state
    if preflight["status"] != "ready_for_build_authorization":
        next_state["build_summary"] = {
            "status": "blocked",
            "input_execution_mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
            "preflight_hash": preflight["projection_hash"],
            "platform_failure_stage": "admission",
        }
        next_state["blockers"].extend(
            {
                "stage": "evidence_retrieval",
                "code": blocker["code"],
                "message": blocker["message"],
            }
            for blocker in preflight["blockers"]
        )
        return next_state
    next_state["feature_id"] = continuation.feature_spec_ref.feature_id
    next_state["next_stage"] = "build"
    _record_artifact(next_state, "feature_spec", continuation.feature_spec_ref)
    _record_artifact(next_state, "evidence_pack", continuation.evidence_pack_ref)
    return next_state


def _route_runtime_continuation_entry(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    operation: VerificationOperationEnvelope,
) -> str:
    """Admit only a validated Build checkpoint into the existing Runtime node."""

    envelope = validate_verification_operation_envelope(operation)
    declaration = resolve_verification_operation(envelope)
    if declaration.graph_handler != "runtime_execution":
        raise ValueError("Verification operation is not a Runtime execution.")
    checkpoint_id = _verification_runtime_checkpoint_id(envelope)
    protocol = envelope.protocol_binding
    if not isinstance(
        protocol,
        (NewRuntimeResumeProtocolBindingV1, VerificationProtocolBinding),
    ):
        raise ValueError("Runtime execution protocol binding changed.")
    if state.get("current_stage") != "build":
        raise ValueError("Runtime continuation state must restore the Build boundary.")
    if state.get("next_stage") != "runtime_evidence":
        raise ValueError("Runtime continuation state has an unexpected next_stage.")
    if state.get("blockers"):
        raise ValueError("Runtime continuation state contains unresolved blockers.")
    for artifact_type in (
        "workflow_checkpoint",
        "resume_report",
        "feature_spec",
        "build_result",
    ):
        if artifact_type not in state.get("artifacts", {}):
            raise ValueError(
                f"Runtime continuation state is missing {artifact_type}."
            )
        if artifact_type not in state.get("artifact_hashes", {}):
            raise ValueError(
                f"Runtime continuation state is missing {artifact_type} hash."
            )
    checkpoint_ref = _artifact_ref_from_state(state, "workflow_checkpoint")
    report_ref = _artifact_ref_from_state(state, "resume_report")
    if checkpoint_ref != protocol.checkpoint_ref:
        raise ValueError(
            "Runtime continuation state changed the approved checkpoint ref."
        )
    if (
        isinstance(protocol, VerificationProtocolBinding)
        and report_ref != protocol.accepted_resume_report_ref
    ):
        raise ValueError(
            "Runtime continuation state changed the accepted ResumeReport ref."
        )
    checkpoint = artifact_store.read_for_stage(
        checkpoint_ref,
        consumer_stage="resume",
    )["data"]
    report = artifact_store.read(report_ref)["data"]
    if (
        checkpoint.get("checkpoint_id") != checkpoint_id
        or checkpoint.get("checkpoint_stage") != "build"
        or checkpoint.get("run_id") != state.get("run_id")
        or checkpoint.get("request_id") != state.get("request_id")
        or checkpoint.get("feature_id") != state.get("feature_id")
        or report.get("checkpoint_id") != checkpoint_id
        or report.get("run_id") != state.get("run_id")
        or report.get("resume_stage") != "build"
        or report.get("resume_id") != protocol.resume_id
        or report.get("approved_by") != protocol.approved_by
        or report.get("decision") != "approve"
        or report.get("allowed") is not True
    ):
        raise ValueError(
            "Runtime continuation checkpoint and resume report are not bound "
            "to the restored state."
        )
    return "continue"


def _route_runtime_terminal_continuation_entry(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    continuation: VerificationOnlyRuntimeTerminalInput,
) -> str:
    """Admit one exact committed RuntimeEvidence into terminal routing."""

    if state.get("current_stage") != "runtime_evidence":
        raise ValueError(
            "Runtime terminal continuation must restore the RuntimeEvidence boundary."
        )
    if state.get("blockers"):
        raise ValueError(
            "Runtime terminal continuation state contains unresolved blockers."
        )
    exact_refs = {
        "workflow_checkpoint": continuation.checkpoint_ref,
        "resume_report": continuation.resume_report_ref,
        "runtime_evidence": continuation.runtime_evidence_ref,
    }
    for artifact_type, expected_ref in exact_refs.items():
        actual_ref = _artifact_ref_from_state(state, artifact_type)
        if actual_ref != expected_ref:
            raise ValueError(
                f"Runtime terminal continuation state changed {artifact_type}."
            )
    decision, runtime_payload, terminal_refs = (
        WorkflowCheckpointStore(
            artifact_store
        ).preflight_runtime_terminal_continuation(
            continuation.checkpoint_ref,
            resume_report_ref=continuation.resume_report_ref,
            runtime_evidence_ref=continuation.runtime_evidence_ref,
            resume_id=continuation.resume_id,
            approved_by=continuation.approved_by,
        )
    )
    if not decision.allowed or terminal_refs:
        raise ValueError(
            "Runtime terminal continuation admission changed before Graph routing."
        )
    expected_summary = _runtime_summary_from_payload(runtime_payload)
    if state.get("runtime_summary") != expected_summary:
        raise ValueError(
            "Runtime terminal continuation summary does not match RuntimeEvidence."
        )
    return route_after_runtime_evidence(state)


def _route_runtime_evidence_consolidation_entry(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    verification_operation: VerificationOperationEnvelope,
) -> str:
    """Admit one exact implementation-evidence delta before its only write."""

    envelope = validate_verification_operation_envelope(verification_operation)
    operation = envelope.variant_payload
    protocol = envelope.protocol_binding
    if state.get("current_stage") != "runtime_evidence":
        raise ValueError(
            "RuntimeEvidence consolidation must restore the RuntimeEvidence boundary."
        )
    if state.get("blockers"):
        raise ValueError(
            "RuntimeEvidence consolidation state contains unresolved blockers."
        )
    exact_refs = {
        "workflow_checkpoint": protocol.checkpoint_ref,
        "resume_report": protocol.accepted_resume_report_ref,
        "runtime_evidence": operation.prior_runtime_evidence_ref,
        "evidence_pack": operation.evidence_pack_ref,
        "feature_spec": operation.feature_spec_ref,
        "build_result": operation.build_result_ref,
    }
    for artifact_type, expected_ref in exact_refs.items():
        if _artifact_ref_from_state(state, artifact_type) != expected_ref:
            raise ValueError(
                f"RuntimeEvidence consolidation state changed {artifact_type}."
            )
    decision, _prior_payload, child_refs = WorkflowCheckpointStore(
        artifact_store
    ).preflight_runtime_evidence_consolidation(
        protocol.checkpoint_ref,
        resume_report_ref=protocol.accepted_resume_report_ref,
        prior_runtime_evidence_ref=operation.prior_runtime_evidence_ref,
        resume_id=protocol.resume_id,
        approved_by=protocol.approved_by,
    )
    if not decision.allowed or child_refs:
        raise ValueError(
            "RuntimeEvidence consolidation admission changed before Graph routing."
        )
    project_consolidated_runtime_evidence(envelope, artifact_store)
    return "continue"


def _route_after_terminal_evaluate(state: ModAgentState) -> str:
    """Stop a terminal continuation after any non-committed EvalReport result."""

    if state["runtime_summary"].get("platform_failure_stage") in {
        "eval_report_execution",
        "eval_report_store",
    }:
        return "stop"
    return route_after_evaluate(state)


def _run_create_repair_plan(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    product_execution_mode: ProductExecutionGraphModeV1 | None = None,
) -> ModAgentState:
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    proposal_context_pack = _read_artifact_data(
        state,
        artifact_store,
        "patch_proposal",
    ).get("context_pack")
    proposal_context_for_repair = (
        {
            **proposal_context_pack,
            "source_patch_proposal_ref": proposal_ref.path,
            "source_patch_proposal_hash": proposal_ref.artifact_hash,
        }
        if isinstance(proposal_context_pack, dict)
        else None
    )
    planner = RepairPlanner()
    feature_id = state["feature_id"] or state["request_id"]
    failed_stage = state["current_stage"]
    if failed_stage == "build" and state["build_summary"].get("status") == "failed":
        build_ref = _artifact_ref_from_state(state, "build_result")
        plan = planner.from_build_failure(
            build_result=_read_artifact_data(state, artifact_store, "build_result"),
            build_result_ref=build_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
            proposal_context_pack=proposal_context_for_repair,
            implementation_plan=_read_artifact_data(
                state,
                artifact_store,
                "implementation_plan",
            ),
        )
        upstream_refs = [build_ref, proposal_ref]
    elif failed_stage in {"runtime_evidence", "binding_resolution"}:
        runtime_ref = _artifact_ref_from_state(state, "runtime_evidence")
        runtime_evidence = _read_artifact_data(
            state,
            artifact_store,
            "runtime_evidence",
        )
        binding_resolution = (
            _read_artifact_data(
                state,
                artifact_store,
                "binding_resolution",
            )
            if "binding_resolution" in state["artifacts"]
            else None
        )
        resolved_repair_target = (
            dict(binding_resolution["resolved_repair_target"])
            if isinstance(binding_resolution, dict)
            and binding_resolution.get("result_type")
            == "resolved_repair_target"
            and isinstance(
                binding_resolution.get("resolved_repair_target"),
                dict,
            )
            else {}
        )
        plan = planner.from_runtime_failure(
            runtime_evidence=runtime_evidence,
            runtime_evidence_ref=runtime_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
            proposal_context_pack=proposal_context_for_repair,
            resolved_repair_target=resolved_repair_target,
        )
        upstream_refs = [runtime_ref, proposal_ref]
        if binding_resolution is not None:
            upstream_refs.append(
                _artifact_ref_from_state(state, "binding_resolution")
            )
    elif failed_stage == "proposal_review":
        review_ref = _artifact_ref_from_state(state, "proposal_review")
        plan = planner.from_review_failure(
            proposal_review=_read_artifact_data(
                state,
                artifact_store,
                "proposal_review",
            ),
            proposal_review_ref=review_ref.path,
            retry_count=state["retry_count"],
            target_behavior=str(feature_spec.get("target_behavior") or ""),
            proposal_context_pack=proposal_context_for_repair,
            implementation_plan=_read_artifact_data(
                state,
                artifact_store,
                "implementation_plan",
            ),
        )
        upstream_refs = [review_ref, proposal_ref]
    else:
        raise ValueError(
            f"Unsupported repair-plan source stage: {failed_stage}"
        )
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="repair_plan",
        payload=plan.to_artifact_payload(),
        status="blocked" if plan.blockers else "success",
        upstream_refs=upstream_refs,
        exact_revision_upstream_types=(
            {ref.artifact_type for ref in upstream_refs}
            if product_execution_mode is not None
            else {"patch_proposal"}
        ),
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "repair_plan"
    next_state["retry_count"] = plan.retry_count
    _record_artifact(next_state, "repair_plan", artifact_ref)
    if plan.blockers:
        next_state["blockers"].extend(plan.blockers)
    return next_state


def _run_resolve_runtime_binding(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    feature_id = state["feature_id"] or state["request_id"]
    runtime_ref = _artifact_ref_from_state(state, "runtime_evidence")
    runtime_evidence = _read_artifact_data(
        state,
        artifact_store,
        "runtime_evidence",
    )
    implementation_plan_ref = _artifact_ref_from_state(
        state,
        "implementation_plan",
    )
    implementation_plan = _read_artifact_data(
        state,
        artifact_store,
        "implementation_plan",
    )
    proposal_ref = _artifact_ref_from_state(state, "patch_proposal")
    proposal = _read_artifact_data(
        state,
        artifact_store,
        "patch_proposal",
    )
    context_pack = proposal.get("context_pack")
    allowed_binding_ids = {
        str(value)
        for value in (
            context_pack.get("allowed_edit_binding_ids", ())
            if isinstance(context_pack, dict)
            else ()
        )
        if isinstance(value, str)
    }
    result = resolve_runtime_diagnosis_binding(
        diagnosis=runtime_evidence.get("runtime_failure_diagnosis"),
        feature_id=feature_id,
        run_id=state["run_id"],
        runtime_evidence_revision={
            "feature_id": runtime_ref.feature_id,
            "path": runtime_ref.path,
            "artifact_hash": runtime_ref.artifact_hash,
        },
        implementation_plan_revision={
            "feature_id": implementation_plan_ref.feature_id,
            "path": implementation_plan_ref.path,
            "artifact_hash": implementation_plan_ref.artifact_hash,
        },
        patch_proposal_revision={
            "feature_id": proposal_ref.feature_id,
            "path": proposal_ref.path,
            "artifact_hash": proposal_ref.artifact_hash,
        },
        implementation_plan=implementation_plan,
        allowed_edit_binding_ids=allowed_binding_ids,
    )
    artifact_ref = artifact_store.write(
        feature_id=feature_id,
        artifact_type="binding_resolution",
        payload=result.to_artifact_payload(),
        status="blocked" if result.blocked else "success",
        upstream_refs=[
            runtime_ref,
            implementation_plan_ref,
            proposal_ref,
        ],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "binding_resolution"
    _record_artifact(next_state, "binding_resolution", artifact_ref)
    next_state["blockers"].extend(result.blockers)
    return next_state


def _run_runtime_evidence(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    runtime_evidence_factory: RuntimeEvidenceFactory | None,
    *,
    use_store_result: bool = False,
    verification_operation: VerificationOperationEnvelope | None = None,
) -> ModAgentState:
    build = _read_artifact_data(state, artifact_store, "build_result")
    feature_spec = _read_artifact_data(state, artifact_store, "feature_spec")
    feature_id = state["feature_id"] or state["request_id"]
    build_artifact_ref = _artifact_ref_from_state(state, "build_result")
    operation_declaration = (
        None
        if verification_operation is None
        else resolve_verification_operation(
            validate_verification_operation_envelope(verification_operation)
        )
    )
    is_consolidation = (
        operation_declaration is not None
        and operation_declaration.graph_handler
        == "runtime_evidence_consolidation"
    )
    requires_verification_only_input = (
        operation_declaration is not None
        and operation_declaration.completion_scope
        != RUNTIME_WORKFLOW_COMPLETION
    )
    try:
        payload = (
            project_consolidated_runtime_evidence(
                validate_verification_operation_envelope(
                    verification_operation
                ),
                artifact_store,
            )
            if is_consolidation
            else (
                runtime_evidence_factory(feature_id, build, feature_spec)
                if runtime_evidence_factory is not None
                else build_fake_runtime_evidence_payload(
                    feature_id=feature_id,
                    input_execution_mode=build.get("execution_mode"),
                    acceptance_criteria=tuple(
                        feature_spec.get("acceptance_criteria") or ()
                    ),
                    runtime_verification_plan=tuple(
                        feature_spec.get("runtime_verification_plan") or ()
                    ),
                )
            )
        )
    except Exception as exc:
        if not use_store_result:
            raise
        if isinstance(exc, _RuntimeEvidenceExecutionBoundaryError):
            failure_stage = exc.failure_stage
            failure_class = exc.failure_class
        else:
            failure_stage = (
                "graph_consolidation_admission"
                if is_consolidation
                else "runtime_execution"
            )
            failure_class = type(exc).__name__
        next_state = _copy_state(state)
        next_state["current_stage"] = "runtime_evidence"
        next_state["runtime_summary"] = {
            "status": "blocked",
            "platform_failure_stage": failure_stage,
            "runtime_evidence_store_result": None,
            "runtime_evidence_ready": False,
            "failure_class": failure_class,
            "failure_message": str(exc),
        }
        next_state["blockers"].append(
            {
                "stage": "runtime_evidence",
                "code": (
                    "RUNTIME_EVIDENCE_STORE_PREFLIGHT_FAILED"
                    if failure_stage == "store_preflight"
                    else (
                        "RUNTIME_EVIDENCE_POST_VALIDATION_FAILED"
                        if failure_stage == "post_runtime_validation"
                        else "RUNTIME_EVIDENCE_FACTORY_FAILED"
                    )
                ),
                "message": f"{failure_class}: {exc}",
            }
        )
        return next_state
    try:
        payload = bind_runtime_evidence_context(
            payload,
            run_id=state["run_id"],
            build_artifact_ref=build_artifact_ref,
        )
        if use_store_result:
            _validate_runtime_evidence_result_identity(
                state,
                artifact_store,
                payload,
                build=build,
                build_artifact_ref=build_artifact_ref,
                requires_verification_only_input=(
                    requires_verification_only_input
                ),
            )
        acceptance_verified = bool(payload["acceptance_verified"])
    except Exception as exc:
        if not use_store_result:
            raise
        validation_stage = (
            "graph_consolidation_admission"
            if is_consolidation
            else "post_runtime_validation"
        )
        next_state = _copy_state(state)
        next_state["current_stage"] = "runtime_evidence"
        next_state["runtime_summary"] = {
            "status": "blocked",
            "platform_failure_stage": validation_stage,
            "runtime_evidence_store_result": None,
            "runtime_evidence_ready": False,
            "failure_class": type(exc).__name__,
            "failure_message": str(exc),
        }
        next_state["blockers"].append(
            {
                "stage": "runtime_evidence",
                "code": (
                    "RUNTIME_EVIDENCE_CONSOLIDATION_VALIDATION_FAILED"
                    if is_consolidation
                    else "RUNTIME_EVIDENCE_POST_VALIDATION_FAILED"
                ),
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
        return next_state
    upstream_refs = [
        build_artifact_ref,
        _artifact_ref_from_state(state, "feature_spec"),
    ]
    exact_revision_upstream_types: set[str] | None = None
    semantic_intent = None
    if is_consolidation:
        if verification_operation is None:
            raise AssertionError("Consolidation operation is missing.")
        operation = verification_operation.variant_payload
        if not isinstance(operation, EvidenceConsolidationOperationV1):
            raise AssertionError("Consolidation variant type changed.")
        upstream_refs.extend(
            [
                operation.prior_runtime_evidence_ref,
                operation.evidence_pack_ref,
            ]
        )
        exact_revision_upstream_types = {
            "runtime_evidence",
            "evidence_pack",
        }
        semantic_intent = project_artifact_write_intent(
            reader=artifact_store,
            feature_id=feature_id,
            artifact_type="runtime_evidence",
            payload=payload,
            status="blocked",
            upstream_refs=upstream_refs,
            exact_revision_upstream_types=exact_revision_upstream_types,
            blockers=(),
            trace_refs=(),
            protocol_refs=(
                verification_operation.protocol_binding.checkpoint_ref,
                verification_operation.protocol_binding.accepted_resume_report_ref,
            ),
            execution_file_bindings=(
                operation.execution_file_bindings
            ),
        )
    write_arguments = {
        "feature_id": feature_id,
        "artifact_type": "runtime_evidence",
        "payload": payload,
        "status": (
            "blocked"
            if is_consolidation
            else ("success" if acceptance_verified else "blocked")
        ),
        "upstream_refs": upstream_refs,
        "exact_revision_upstream_types": exact_revision_upstream_types,
        "semantic_intent": semantic_intent,
    }
    write_result = None
    if use_store_result:
        write_result = artifact_store.write_with_result(**write_arguments)
        artifact_ref = write_result.artifact_ref
    else:
        artifact_ref = artifact_store.write(**write_arguments)
    next_state = _copy_state(state)
    if is_consolidation:
        next_state["artifacts"].pop("runtime_evidence", None)
        next_state["artifact_hashes"].pop("runtime_evidence", None)
    next_state["current_stage"] = "runtime_evidence"
    next_state["runtime_summary"] = _runtime_summary_from_payload(payload)
    if write_result is not None:
        next_state["runtime_summary"].update(
            {
                "runtime_evidence_store_result": write_result.to_dict(),
                "runtime_evidence_ready": (
                    write_result.outcome == "committed" and artifact_ref is not None
                ),
                "platform_failure_stage": (
                    None
                    if write_result.outcome == "committed"
                    else "runtime_evidence_store"
                ),
            }
        )
    if artifact_ref is not None:
        _record_artifact(next_state, "runtime_evidence", artifact_ref)
    elif use_store_result:
        next_state["blockers"].append(
            {
                "stage": "runtime_evidence",
                "code": "RUNTIME_EVIDENCE_STORE_NOT_COMMITTED",
                "message": (
                    "RuntimeEvidence did not reach a committed Store outcome."
                ),
            }
        )
    return next_state


def _runtime_summary_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project durable RuntimeEvidence facts without ephemeral Store receipts."""

    return {
        "status": payload["verification_status"],
        "execution_mode": payload["execution_mode"],
        "real_runtime_performed": payload["real_runtime_performed"],
        "startup_loaded": payload["startup_loaded"],
        "gameplay_behavior_verified": payload["gameplay_behavior_verified"],
        "acceptance_status": payload["acceptance_status"],
        "acceptance_verified": bool(payload["acceptance_verified"]),
        "acceptance_contract": payload["acceptance_contract"],
        "claims_real_runtime_success": payload["claims_real_runtime_success"],
        "run_id": payload["run_id"],
        "build_artifact_hash": payload["build_artifact_hash"],
        "plugin_marker_binding": payload["plugin_marker_binding"],
        "screenshot_refs": payload["screenshot_refs"],
        "runtime_trust_binding": payload["runtime_trust_binding"],
        "failure_ownership": payload["failure_ownership"],
        "has_structured_diagnosis": isinstance(
            payload.get("runtime_failure_diagnosis"),
            dict,
        ),
        "plugin_deployment_binding": payload.get("plugin_deployment_binding"),
        "non_goal_preservation": payload["non_goal_preservation"],
    }


def _validate_runtime_evidence_result_identity(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    payload: Mapping[str, Any],
    *,
    build: Mapping[str, Any],
    build_artifact_ref: ArtifactRef,
    requires_verification_only_input: bool,
) -> None:
    """Validate exact post-effect RuntimeEvidence identity before Store write."""

    feature_id = state["feature_id"] or state["request_id"]
    expected_build_ref = {
        "feature_id": build_artifact_ref.feature_id,
        "artifact_type": build_artifact_ref.artifact_type,
        "path": build_artifact_ref.path,
        "artifact_hash": build_artifact_ref.artifact_hash,
    }
    expected_input_mode = build.get("input_execution_mode")
    mismatches = []
    if (
        requires_verification_only_input
        and expected_input_mode != VERIFICATION_ONLY_INPUT_EXECUTION_MODE
    ):
        mismatches.append("verification_only_input_execution_mode")
    if payload.get("feature_id") != feature_id:
        mismatches.append("feature_id")
    if payload.get("run_id") != state["run_id"]:
        mismatches.append("run_id")
    if payload.get("build_artifact_ref") != expected_build_ref:
        mismatches.append("build_artifact_ref")
    if payload.get("build_artifact_hash") != build_artifact_ref.artifact_hash:
        mismatches.append("build_artifact_hash")
    if (
        requires_verification_only_input
        and expected_input_mode is not None
        and payload.get("input_execution_mode") != expected_input_mode
    ):
        mismatches.append("input_execution_mode")
    artifact_store.registry.validate_write(
        artifact_type="runtime_evidence",
        status=("success" if payload.get("acceptance_verified") is True else "blocked"),
        payload=dict(payload),
    )
    for artifact_type in ("feature_spec", "build_result"):
        artifact_ref = _artifact_ref_from_state(state, artifact_type)
        freshness = artifact_store.check_freshness(artifact_ref)
        if not freshness.is_fresh:
            mismatches.append(f"{artifact_type}_freshness")
    if mismatches:
        raise ValueError(
            "RuntimeEvidence post-effect identity validation failed: "
            + ", ".join(sorted(mismatches))
        )


def _run_fake_evaluate(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    evaluation_context_factory: EvaluationContextFactory | None = None,
    require_external_evaluation: bool = False,
    *,
    use_store_result: bool = False,
) -> ModAgentState:
    build = _read_artifact_data(state, artifact_store, "build_result")
    runtime = _read_artifact_data(state, artifact_store, "runtime_evidence")
    verification_only = (
        build.get("input_execution_mode")
        == VERIFICATION_ONLY_INPUT_EXECUTION_MODE
    )
    verification_preflight: dict[str, Any] | None = None
    mutation_artifacts = {
        "implementation_plan",
        "patch_proposal",
        "proposal_review",
        "dry_run_result",
        "isolated_apply_result",
    }.intersection(state["artifacts"])
    if verification_only:
        review = {}
        dry_run = {}
        if {"feature_spec", "evidence_pack"}.issubset(state["artifacts"]):
            verification_preflight = preflight_verification_only_continuation(
                artifact_store,
                VerificationOnlyContinuationInput(
                    feature_spec_ref=_artifact_ref_from_state(state, "feature_spec"),
                    evidence_pack_ref=_artifact_ref_from_state(state, "evidence_pack"),
                ),
                run_id=state["run_id"],
                request_id=state["request_id"],
                user_request=state["user_request"],
                target_mod=state["target_mod"],
            )
    else:
        review = _read_artifact_data(state, artifact_store, "proposal_review")
        dry_run = _read_artifact_data(state, artifact_store, "dry_run_result")
    feature_id = state["feature_id"] or state["request_id"]
    acceptance_verified = bool(runtime.get("acceptance_verified"))
    v1_boundary = _v1_acceptance_boundary(build=build, runtime=runtime)
    v1_accepted = v1_boundary["v1_acceptance_status"] == "accepted"
    evaluation_gate = build_transition_eval_gate_report(
        review=review,
        dry_run=dry_run,
        build=build,
        runtime=runtime,
        v1_boundary=v1_boundary,
        claims_real_success=v1_accepted,
        evaluation_context=(
            evaluation_context_factory(state)
            if evaluation_context_factory is not None
            else None
        ),
        evaluation_required=require_external_evaluation,
        continuation_mode=(
            VERIFICATION_ONLY_INPUT_EXECUTION_MODE
            if verification_only
            else "mutation"
        ),
        verification_only_lineage_verified=(
            verification_preflight is not None
            and verification_preflight["status"]
            == "ready_for_build_authorization"
            and not mutation_artifacts
            and verification_only_lineage_matches(build, verification_preflight)
        ),
    )
    gate_failed = evaluation_gate.get("status") == "failed"
    accepted = v1_accepted and not gate_failed
    execution_mode = "real" if runtime.get("execution_mode") == "real" else "fake"
    workflow_completion_status = (
        "real_runtime_acceptance_completed"
        if accepted
        else ("evaluation_blocked" if gate_failed else "fake_execution_completed")
    )
    payload = {
        "node_name": "evaluate",
        "stage": "evaluation",
        "message": (
            "Evaluation completed with real build and runtime acceptance evidence."
            if accepted
            else (
                "Evaluation blocked by deterministic transition gates."
                if gate_failed
                else (
                    "Evaluation completed for a fake/local workflow path. Result "
                    "remains inconclusive for real build and runtime success."
                )
            )
        ),
        "execution_mode": execution_mode,
        "workflow_completion_status": workflow_completion_status,
        "requested_behavior_status": (
            "verified" if acceptance_verified and not gate_failed else "not_verified"
        ),
        "verdict": "accepted" if accepted else ("blocked" if gate_failed else "inconclusive"),
        "claims_real_success": accepted,
        "checks": [
            {
                "check": (
                    "verification_only_lineage_admitted"
                    if verification_only
                    else "review_gate_approved"
                ),
                "status": (
                    "passed"
                    if not verification_only
                    or (
                        verification_preflight is not None
                        and verification_preflight["status"]
                        == "ready_for_build_authorization"
                        and not mutation_artifacts
                        and verification_only_lineage_matches(
                            build,
                            verification_preflight,
                        )
                    )
                    else "failed"
                ),
            },
            {
                "check": "real_build",
                "status": "passed"
                if build.get("claims_real_build_success")
                else "not_run",
            },
            {
                "check": "real_runtime",
                "status": "passed"
                if runtime.get("claims_real_runtime_success")
                else "not_run",
            },
        ],
        "input_runtime_status": runtime.get("verification_status"),
        "input_acceptance_status": runtime.get("acceptance_status"),
        "input_acceptance_verified": acceptance_verified,
        "acceptance_contract": runtime.get("acceptance_contract"),
        "evaluation_gate": evaluation_gate,
        **v1_boundary,
    }
    gate_blockers = list(evaluation_gate.get("blockers") or [])
    write_arguments = {
        "feature_id": feature_id,
        "artifact_type": "eval_report",
        "payload": payload,
        "status": "blocked" if gate_failed else "success",
        "blockers": gate_blockers,
        "upstream_refs": [
            _artifact_ref_from_state(state, "build_result"),
            _artifact_ref_from_state(state, "runtime_evidence"),
        ],
    }
    write_result = None
    if use_store_result:
        write_result = artifact_store.write_with_result(**write_arguments)
        artifact_ref = write_result.artifact_ref
    else:
        artifact_ref = artifact_store.write(**write_arguments)
    next_state = _copy_state(state)
    next_state["current_stage"] = "evaluation"
    if artifact_ref is not None:
        _record_artifact(next_state, "eval_report", artifact_ref)
    if write_result is not None:
        eval_ready = (
            write_result.outcome == "committed" and artifact_ref is not None
        )
        next_state["runtime_summary"].update(
            {
                "eval_report_store_result": write_result.to_dict(),
                "eval_report_ready": eval_ready,
                "platform_failure_stage": (
                    None if eval_ready else "eval_report_store"
                ),
                "terminal_route": (
                    "blocked" if gate_failed and eval_ready else "evaluate"
                ),
                "terminal_ready": False,
            }
        )
        if not eval_ready:
            next_state["blockers"].append(
                {
                    "stage": "evaluation",
                    "code": "EVAL_REPORT_STORE_NOT_COMMITTED",
                    "message": "EvalReport did not reach a committed Store outcome.",
                }
            )
    if gate_failed:
        next_state["blockers"].extend(
            {
                "stage": "evaluation",
                "code": blocker.get("code", "EVAL_GATE_FAILED"),
                "message": blocker.get("message", "Evaluation gate failed."),
            }
            for blocker in gate_blockers
            if isinstance(blocker, dict)
        )
    return next_state


def _run_isolated_apply(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    isolated_apply_factory: PatchExecutionFactory,
) -> ModAgentState:
    proposal = _read_artifact_data(state, artifact_store, "patch_proposal")
    review = _read_artifact_data(state, artifact_store, "proposal_review")
    semantic_assurance, semantic_contract_present = (
        _semantic_assurance_for_execution(proposal, review)
    )
    human_semantic_review_required = (
        semantic_contract_present and semantic_assurance.verdict == "unproven"
    )
    approved_by_user = state["approvals"].get("confirmed_write") is True
    next_state = _copy_state(state)
    status = "success"
    if not approved_by_user:
        payload = {
            "execution_mode": "blocked",
            "actual_write_performed": False,
            "real_patch_applied": False,
            "approved_by_review": review.get("allowed_next_stage") == "dry_run_apply",
            "changed_files": [],
        }
        status = "blocked"
        next_state["blockers"].append(
            {
                "stage": "isolated_apply",
                "code": "ISOLATED_WRITE_NOT_APPROVED",
                "message": "Isolated patch application requires explicit user approval.",
            }
        )
    else:
        try:
            payload = isolated_apply_factory(
                proposal,
                _read_artifact_data(state, artifact_store, "implementation_plan"),
                review,
            )
        except ExactDiffApprovalRejectedError as exc:
            payload = {
                "execution_mode": "rejected",
                "actual_write_performed": False,
                "real_patch_applied": False,
                "approved_by_review": review.get("allowed_next_stage")
                == "dry_run_apply",
                "changed_files": [],
                "rejection": str(exc),
                "human_semantic_decision": exc.human_semantic_decision,
                "human_semantic_review_completed": False,
                "human_semantic_review_result": "rejected",
            }
            status = "blocked"
            next_state["blockers"].append(
                {
                    "stage": "isolated_apply",
                    "code": "EXACT_DIFF_REJECTED",
                    "message": str(exc),
                }
            )
        except Exception as exc:
            payload = {
                "execution_mode": "isolated_apply",
                "actual_write_performed": False,
                "real_patch_applied": False,
                "approved_by_review": review.get("allowed_next_stage") == "dry_run_apply",
                "changed_files": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
            status = "failed"
            next_state["blockers"].append(
                {
                    "stage": "isolated_apply",
                    "code": "ISOLATED_APPLY_FAILED",
                    "message": payload["error"],
                }
            )
    exact_diff_approved = bool(
        payload.get("approved_diff_hash")
        and payload.get("approved_diff_hash") == payload.get("diff_hash")
    )
    human_semantic_decision = payload.get("human_semantic_decision")
    human_semantic_review_completed = bool(
        payload.get("human_semantic_review_completed") is True
        and isinstance(human_semantic_decision, dict)
        and human_semantic_decision.get("decision") == "approve"
    )
    if (
        status == "success"
        and human_semantic_review_required
        and not human_semantic_review_completed
    ):
        status = "failed"
        next_state["blockers"].append(
            {
                "stage": "isolated_apply",
                "code": "HUMAN_SEMANTIC_DECISION_MISSING",
                "message": (
                    "Unproven semantic assurance requires a bound structured "
                    "human approve decision before isolated apply can succeed."
                ),
            }
        )
    complete_payload = {
        "node_name": "isolated_apply",
        "stage": "isolated_apply",
        "message": (
            "Approved patch was applied inside the isolated workspace."
            if status == "success"
            else "Isolated patch application did not complete."
        ),
        **payload,
        "write_scope_preapproved": approved_by_user,
        "approved_by_user": bool(
            payload.get("approved_by_user", approved_by_user if status == "success" else False)
        ),
        "exact_diff_approved": exact_diff_approved,
        "semantic_assurance": semantic_assurance.to_dict(),
        "human_semantic_review_required": human_semantic_review_required,
        "human_semantic_review_completed": human_semantic_review_completed,
        "human_semantic_review_result": payload.get(
            "human_semantic_review_result",
            "approved" if human_semantic_review_completed else "missing",
        ),
        "human_semantic_decision": human_semantic_decision,
    }
    artifact_ref = artifact_store.write(
        feature_id=proposal["feature_id"],
        artifact_type="isolated_apply_result",
        payload=complete_payload,
        status=status,
        upstream_refs=[
            _artifact_ref_from_state(state, "patch_proposal"),
            _artifact_ref_from_state(state, "proposal_review"),
            _artifact_ref_from_state(state, "dry_run_result"),
        ],
    )
    next_state["current_stage"] = "isolated_apply"
    _record_artifact(next_state, "isolated_apply_result", artifact_ref)
    return next_state


def _semantic_assurance_for_execution(
    proposal: dict[str, Any],
    review: dict[str, Any],
) -> tuple[SemanticAssuranceV1, bool]:
    proposal_has_contract = "semantic_assurance" in proposal
    review_has_contract = "semantic_assurance" in review
    proposal_value = proposal.get("semantic_assurance")
    review_value = review.get("semantic_assurance")
    if proposal_has_contract and not isinstance(proposal_value, dict):
        raise ValueError("Proposal semantic assurance is malformed.")
    if review_has_contract and not isinstance(review_value, dict):
        raise ValueError("Review semantic assurance is malformed.")
    proposal_assurance = (
        SemanticAssuranceV1.from_dict(proposal_value)
        if proposal_has_contract
        else SemanticAssuranceV1.unproven()
    )
    review_assurance = (
        SemanticAssuranceV1.from_dict(review_value)
        if review_has_contract
        else SemanticAssuranceV1.unproven()
    )
    if proposal_assurance != review_assurance:
        raise ValueError(
            "Proposal and review semantic assurance results do not match."
        )
    semantic_contract_present = proposal_has_contract or review_has_contract
    if semantic_contract_present and proposal_assurance.verdict != "unproven":
        raise ValueError(
            "Semantic Assurance V0 accepts only the unproven machine verdict."
        )
    if (
        semantic_contract_present
        and review.get("human_semantic_review_required") is not True
    ):
        raise ValueError(
            "Unproven semantic assurance is missing its human review obligation."
        )
    return proposal_assurance, semantic_contract_present


def _run_workflow_summary(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    *,
    use_store_result: bool = False,
) -> ModAgentState:
    eval_report = _read_artifact_data(state, artifact_store, "eval_report")
    feature_id = state["feature_id"] or state["request_id"]
    evaluation_gate = eval_report.get("evaluation_gate")
    evaluation_gate_passed = (
        isinstance(evaluation_gate, dict)
        and evaluation_gate.get("status") == "passed"
    )
    accepted = (
        eval_report.get("v1_acceptance_status") == "accepted"
        and eval_report.get("verdict") == "accepted"
        and eval_report.get("claims_real_success") is True
        and evaluation_gate_passed
    )
    evaluation_blocked = (
        eval_report.get("verdict") == "blocked" or not evaluation_gate_passed
    )
    verification_only = (
        state["build_summary"].get("input_execution_mode")
        == VERIFICATION_ONLY_INPUT_EXECUTION_MODE
    )
    durable_runtime_summary = (
        _runtime_summary_from_payload(
            _read_artifact_data(state, artifact_store, "runtime_evidence")
        )
        if use_store_result
        else dict(state["runtime_summary"])
    )
    payload = {
        "node_name": "done",
        "stage": "done",
        "message": (
            "Workflow reached done with real build and runtime acceptance evidence."
            if accepted
            else (
                "Workflow stopped because deterministic evaluation gates blocked "
                "acceptance. No real Mod success is claimed."
                if evaluation_blocked
                else
                "Workflow reached the end of the controlled fake execution loop. "
                "No real file write, real build, or real runtime success is claimed."
            )
        ),
        "execution_mode": eval_report.get("execution_mode"),
        "workflow_completion_status": eval_report.get("workflow_completion_status"),
        "requested_behavior_status": eval_report.get("requested_behavior_status"),
        "final_status": (
            "accepted" if accepted else ("blocked" if evaluation_blocked else "inconclusive")
        ),
        "claims_real_mod_success": accepted,
        "claims_real_build_success": bool(
            state["build_summary"].get("claims_real_build_success")
        ),
        "claims_real_runtime_success": bool(
            durable_runtime_summary.get("claims_real_runtime_success")
        ),
        "artifact_refs": dict(state["artifacts"]),
        "build_summary": dict(state["build_summary"]),
        "runtime_summary": durable_runtime_summary,
        "eval_verdict": eval_report.get("verdict"),
        "v1_acceptance_status": eval_report.get("v1_acceptance_status"),
        "v1_acceptance_blockers": list(eval_report.get("v1_acceptance_blockers") or []),
        "next_required_evidence": (
            []
            if accepted
            else (
                ["real build output", "real runtime or manual verification evidence"]
                if verification_only
                else [
                    "real dry-run/apply result",
                    "real build output",
                    "real runtime or manual verification evidence",
                ]
            )
        ),
    }
    write_arguments = {
        "feature_id": feature_id,
        "artifact_type": "workflow_summary",
        "payload": payload,
        "status": "success",
        "upstream_refs": [_artifact_ref_from_state(state, "eval_report")],
    }
    write_result = None
    if use_store_result:
        write_result = artifact_store.write_with_result(**write_arguments)
        artifact_ref = write_result.artifact_ref
    else:
        artifact_ref = artifact_store.write(**write_arguments)
    next_state = _copy_state(state)
    next_state["current_stage"] = "done"
    if artifact_ref is not None:
        _record_artifact(next_state, "workflow_summary", artifact_ref)
    if write_result is not None:
        summary_ready = (
            write_result.outcome == "committed" and artifact_ref is not None
        )
        next_state["runtime_summary"].update(
            {
                "workflow_summary_store_result": write_result.to_dict(),
                "workflow_summary_ready": summary_ready,
                "platform_failure_stage": (
                    None if summary_ready else "workflow_summary_store"
                ),
                "terminal_route": "done",
                "terminal_ready": summary_ready,
                "terminal_final_status": payload["final_status"],
                "terminal_claims_real_mod_success": payload[
                    "claims_real_mod_success"
                ],
            }
        )
        if not summary_ready:
            next_state["blockers"].append(
                {
                    "stage": "done",
                    "code": "WORKFLOW_SUMMARY_STORE_NOT_COMMITTED",
                    "message": (
                        "WorkflowSummary did not reach a committed Store outcome."
                    ),
                }
            )
    return next_state


def _run_planning_brief(
    state: ModAgentState,
    artifact_store: ArtifactStore,
) -> ModAgentState:
    plan_data = _read_artifact_data(state, artifact_store, "request_planning_report")
    plan = _request_plan_from_payload(plan_data)
    planning_brief = ModPlanningBriefBuilder().build(
        plan,
        target_game=state["target_domain"],
    )
    artifact_ref = artifact_store.write(
        feature_id=planning_brief.feature_id,
        artifact_type="mod_planning_brief",
        payload=planning_brief.to_artifact_payload(),
        status="blocked" if planning_brief.blocked else "success",
        upstream_refs=[_artifact_ref_from_state(state, "request_planning_report")],
    )
    next_state = _copy_state(state)
    next_state["current_stage"] = "planning_brief"
    _record_artifact(next_state, "mod_planning_brief", artifact_ref)
    if planning_brief.blocked:
        next_state["blockers"].extend(planning_brief.blockers)
    return next_state


def _v1_acceptance_boundary(
    *,
    build: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    if build.get("claims_real_build_success") is not True:
        blockers.append(
            {
                "code": "REAL_BUILD_EVIDENCE_MISSING",
                "message": "V1 acceptance requires real build success evidence.",
            }
        )
    if runtime.get("execution_mode") != "real":
        blockers.append(
            {
                "code": "REAL_RUNTIME_MODE_REQUIRED",
                "message": "V1 acceptance requires runtime evidence from real execution mode.",
            }
        )
    if runtime.get("real_runtime_performed") is not True:
        blockers.append(
            {
                "code": "REAL_RUNTIME_EVIDENCE_MISSING",
                "message": "V1 acceptance requires real runtime execution evidence.",
            }
        )
    if runtime.get("claims_real_runtime_success") is not True:
        blockers.append(
            {
                "code": "REAL_RUNTIME_SUCCESS_NOT_CLAIMED",
                "message": "V1 acceptance requires an explicit real runtime success claim.",
            }
        )
    if runtime.get("acceptance_verified") is not True:
        blockers.append(
            {
                "code": "ACCEPTANCE_NOT_VERIFIED",
                "message": "V1 acceptance requires verified runtime acceptance evidence.",
            }
        )
    if (
        runtime.get("evidence_source") == "gtfo_real_runtime_automation"
        and _runtime_trust_binding_status(runtime) != "trusted"
    ):
        blockers.append(
            {
                "code": "GTFO_RUNTIME_TRUST_BINDING_MISSING",
                "message": (
                    "V1 acceptance for GTFO automation requires trusted current-run "
                    "log, process, marker, build, and screenshot binding."
                ),
            }
        )
    return {
        "v1_acceptance_status": "blocked" if blockers else "accepted",
        "v1_acceptance_blockers": blockers,
    }


def _runtime_trust_binding_status(runtime: dict[str, Any]) -> str | None:
    binding = runtime.get("runtime_trust_binding")
    if not isinstance(binding, dict):
        return None
    return binding.get("status")


def _request_plan_from_payload(data: dict[str, Any]) -> RequestPlan:
    return RequestPlan(
        feature_id=data["feature_id"],
        user_request=data["user_request"],
        route=data["route"],
        risk_level=data["risk_level"],
        target_mod=data.get("target_mod"),
        requires_hook_evidence=bool(data["requires_hook_evidence"]),
        requires_runtime_evidence=bool(data["requires_runtime_evidence"]),
        hook_requirement=_hook_requirement_from_payload(data),
        uncertainties=tuple(
            Uncertainty(
                uncertainty_id=item["uncertainty_id"],
                severity=item["severity"],
                question=item["question"],
                allowed_resolution=tuple(item.get("allowed_resolution", ())),
                default_action=item.get("default_action", "block"),
            )
            for item in data.get("uncertainties", [])
        ),
        blocked=bool(data["blocked"]),
    )


def _feature_spec_from_payload(data: dict[str, Any]) -> FeatureSpec:
    return FeatureSpec(
        feature_id=data["feature_id"],
        user_request=data["user_request"],
        target_behavior=data["target_behavior"],
        non_goals=tuple(data["non_goals"]),
        target_mod=data.get("target_mod"),
        risk_level=data["risk_level"],
        acceptance_criteria=tuple(data["acceptance_criteria"]),
        evidence_requirements=tuple(data["evidence_requirements"]),
        runtime_verification_plan=tuple(data["runtime_verification_plan"]),
        hook_requirement=_hook_requirement_from_payload(data),
        blocked=bool(data["blocked"]),
        blockers=tuple(data.get("blockers", [])),
    )


def _hook_requirement_from_payload(data: dict[str, Any]) -> dict[str, Any]:
    hook_requirement = data.get("hook_requirement")
    if isinstance(hook_requirement, dict):
        return {
            "required": hook_requirement.get("required") is True,
            "reason": str(hook_requirement.get("reason") or "not_required"),
        }
    return {"required": False, "reason": "not_required"}


def _read_artifact_data(
    state: ModAgentState,
    artifact_store: ArtifactStore,
    artifact_type: str,
) -> dict[str, Any]:
    ref = _artifact_ref_from_state(state, artifact_type)
    envelope = artifact_store.read(ref)
    return envelope["data"]


def _artifact_ref_from_state(state: ModAgentState, artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        feature_id=state["feature_id"] or state["request_id"],
        artifact_type=artifact_type,
        path=state["artifacts"][artifact_type],
        artifact_hash=state["artifact_hashes"][artifact_type],
    )


def _record_artifact(
    state: ModAgentState,
    artifact_type: str,
    artifact_ref: ArtifactRef,
) -> None:
    state["artifacts"][artifact_type] = artifact_ref.path
    state["artifact_hashes"][artifact_type] = artifact_ref.artifact_hash


def _node_status(state: ModAgentState, node_name: str) -> str:
    if node_name == "retrieve_evidence":
        return "success" if state["evidence_summary"].get("can_generate_patch") else "blocked"
    if node_name == "review_proposal":
        return (
            "success"
            if state["review_summary"].get("allowed_next_stage") == "dry_run_apply"
            else "blocked"
        )
    if node_name == "build" and state["build_summary"]:
        return str(state["build_summary"].get("status", "success"))
    if node_name == "collect_runtime_evidence" and state["runtime_summary"]:
        return str(state["runtime_summary"].get("status", "success"))
    if node_name == "create_repair_plan":
        return "blocked" if state["blockers"] else "success"
    if node_name == "resolve_runtime_binding":
        return "blocked" if state["blockers"] else "success"
    if node_name == "done":
        return "inconclusive"
    if state["blockers"]:
        return "blocked"
    return "success"


def _node_artifact_refs(state: ModAgentState, node_name: str) -> list[str]:
    artifact_by_node = {
        "plan_request": "request_planning_report",
        "planning_brief": "mod_planning_brief",
        "draft_feature_spec": "feature_spec",
        "retrieve_evidence": "evidence_pack",
        "create_implementation_plan": "implementation_plan",
        "generate_patch_proposal": "patch_proposal",
        "review_proposal": "proposal_review",
        "human_review_gate": "resume_report",
        "dry_run_apply": "dry_run_result",
        "build": "build_result",
        "collect_runtime_evidence": "runtime_evidence",
        "resolve_runtime_binding": "binding_resolution",
        "create_repair_plan": "repair_plan",
        "evaluate": "eval_report",
        "done": "workflow_summary",
    }
    artifact_type = artifact_by_node.get(node_name)
    if artifact_type is None or artifact_type not in state["artifacts"]:
        return []
    return [state["artifacts"][artifact_type]]


def _node_trace_details(state: ModAgentState, node_name: str) -> dict[str, Any]:
    if node_name == "verification_only_admission":
        preflight = state["evidence_summary"].get("verification_only_preflight")
        if isinstance(preflight, dict):
            return {
                "status": preflight.get("status"),
                "projection_hash": preflight.get("projection_hash"),
                "source_files_verified": (
                    preflight.get("source_lineage", {}).get("all_files_verified")
                ),
            }
    if node_name == "retrieve_evidence" and state["evidence_summary"]:
        missing_evidence = list(state["evidence_summary"].get("missing_evidence") or [])
        return {
            "readiness": state["evidence_summary"].get("readiness"),
            "can_generate_patch": state["evidence_summary"].get("can_generate_patch"),
            "retrieval_methods_used": list(
                state["evidence_summary"].get("retrieval_methods_used") or []
            ),
            "missing_evidence_count": len(missing_evidence),
            "disabled_modes": dict(state["evidence_summary"].get("disabled_modes") or {}),
            "timing": dict(state["evidence_summary"].get("timing") or {}),
        }
    if node_name == "create_repair_plan" and "repair_plan" in state["artifacts"]:
        return {
            "retry_count": state["retry_count"],
            "blocked": bool(state["blockers"]),
        }
    if (
        node_name == "resolve_runtime_binding"
        and "binding_resolution" in state["artifacts"]
    ):
        return {
            "result_type": (
                "binding_gap" if state["blockers"] else "resolved_repair_target"
            ),
            "blocked": bool(state["blockers"]),
        }
    return {}


def _trace_event(
    *,
    state: ModAgentState,
    node_name: str,
    event_type: str,
    status: str,
    artifact_refs: list[str],
    summary: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "event_id": f"evt_{uuid4().hex}",
        "run_id": state["run_id"],
        "feature_id": state.get("feature_id") or state["request_id"],
        "node_name": node_name,
        "stage": state["current_stage"],
        "event_type": event_type,
        "status": status,
        "artifact_refs": artifact_refs,
        "summary": summary,
    }
    if details:
        event["details"] = details
    return event


def _copy_state_with_trace(
    state: ModAgentState,
    trace_event: dict[str, Any],
) -> ModAgentState:
    next_state = _copy_state(state)
    next_state["trace_events"].append(trace_event)
    return next_state


def _copy_state(state: ModAgentState) -> ModAgentState:
    return ModAgentState(
        run_id=state["run_id"],
        request_id=state["request_id"],
        feature_id=state["feature_id"],
        user_request=state["user_request"],
        target_domain=state["target_domain"],
        target_mod=state["target_mod"],
        execution_path=state["execution_path"],
        risk_level=state["risk_level"],
        current_stage=state["current_stage"],
        next_stage=state["next_stage"],
        artifacts=dict(state["artifacts"]),
        artifact_hashes=dict(state["artifact_hashes"]),
        approvals=dict(state["approvals"]),
        blockers=list(state["blockers"]),
        warnings=list(state["warnings"]),
        evidence_summary=dict(state["evidence_summary"]),
        review_summary=dict(state["review_summary"]),
        build_summary=dict(state["build_summary"]),
        runtime_summary=dict(state["runtime_summary"]),
        edit_authority_review_result=copy.deepcopy(
            state.get("edit_authority_review_result")
        ),
        trace_events=list(state["trace_events"]),
        retry_count=state["retry_count"],
    )
