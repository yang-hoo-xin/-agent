"""Local CLI for the Evidence-Grounded Controlled Code Generation Agent Platform."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from .artifacts.store import ArtifactStorePreflightError
from .edit_authority_capabilities import (
    parse_current_edit_authority_review_result,
)
from .evidence import R8EvidenceError, R8ILInspectionError
from .evidence_only import EvidenceOnlyError, run_gtfo_r8_evidence_only
from .intelligent_evidence_only import (
    IntelligentEvidenceEntryError,
    run_intelligent_evidence_only,
)
from .local_entry import (
    EditAuthorityPresentationError,
    LocalEntryError,
    preflight_local_runtime,
    preflight_stagger_edit_authority_review,
    resume_stagger_edit_authority_review,
    resume_local_runtime,
    run_local_request,
)
from .planning import ModPlanningBriefBuilder, RequestPlanner
from .product_execution import (
    ProductExecutionContractError,
    ProductExecutionResultV1,
)
from .product_executor import ProductExecutionPresentationError
from .runtime import (
    StaggerDiagnosticDiffPreflightError,
    StaggerEditAuthorityApprovalError,
    StaggerEditAuthorityPreflightError,
    create_stagger_existing_binding_reauthorization_request,
    create_stagger_edit_authority_request,
    create_stagger_hud_parent_observation_authority_request,
    preflight_stagger_existing_binding_reauthorization,
    preflight_stagger_edit_authority,
    preflight_stagger_hud_parent_diagnostic_exact_diff,
    preflight_stagger_hud_parent_observation_authority,
)
from .tools import PermissionModel


@dataclass(frozen=True)
class PlanRequestResult:
    """Structured no-write planning result returned by plan-request."""

    status: str
    command: str
    request: str
    execution_mode: str
    writes_performed: bool
    stopped_before: str
    request_planning_report: dict[str, object]
    mod_planning_brief: dict[str, object]


def plan_request(
    description: str,
    *,
    target_game: str | None = None,
    target_mod: str | None = None,
) -> PlanRequestResult:
    """Run request planning and stop before feature specification."""

    request_plan = RequestPlanner().plan(description, target_mod=target_mod)
    planning_brief = ModPlanningBriefBuilder().build_planning_only(
        request_plan,
        target_game=target_game,
    )
    return PlanRequestResult(
        status=planning_brief.decision,
        command="plan-request",
        request=description,
        execution_mode="planning_only",
        writes_performed=False,
        stopped_before="feature_spec",
        request_planning_report=request_plan.to_artifact_payload(),
        mod_planning_brief=planning_brief.to_artifact_payload(),
    )


def _add_stagger_edit_authority_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("--artifact-store-root", required=True)
    parser.add_argument("--feature-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--feature-spec-path", required=True)
    parser.add_argument("--feature-spec-hash", required=True)
    parser.add_argument("--runtime-evidence-path", required=True)
    parser.add_argument("--runtime-evidence-hash", required=True)
    parser.add_argument("--implementation-plan-path", required=True)
    parser.add_argument("--implementation-plan-hash", required=True)
    parser.add_argument("--patch-proposal-path", required=True)
    parser.add_argument("--patch-proposal-hash", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--canonical-target-path", required=True)
    parser.add_argument("--target-symbol", required=True)
    parser.add_argument("--target-start-line", required=True, type=int)
    parser.add_argument("--target-end-line", required=True, type=int)
    parser.add_argument("--proposed-operation", required=True)


def _stagger_edit_authority_arguments(
    args: argparse.Namespace,
) -> dict[str, object]:
    return {
        "artifact_store_root": args.artifact_store_root,
        "feature_id": args.feature_id,
        "run_id": args.run_id,
        "feature_spec_path": args.feature_spec_path,
        "feature_spec_hash": args.feature_spec_hash,
        "runtime_evidence_path": args.runtime_evidence_path,
        "runtime_evidence_hash": args.runtime_evidence_hash,
        "implementation_plan_path": args.implementation_plan_path,
        "implementation_plan_hash": args.implementation_plan_hash,
        "patch_proposal_path": args.patch_proposal_path,
        "patch_proposal_hash": args.patch_proposal_hash,
        "source_root": args.source_root,
        "canonical_target_path": args.canonical_target_path,
        "target_symbol": args.target_symbol,
        "target_start_line": args.target_start_line,
        "target_end_line": args.target_end_line,
        "proposed_operation": args.proposed_operation,
    }


def _add_stagger_existing_binding_reauthorization_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("--artifact-store-root", required=True)
    parser.add_argument("--feature-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--feature-spec-path", required=True)
    parser.add_argument("--feature-spec-hash", required=True)
    parser.add_argument("--runtime-evidence-path", required=True)
    parser.add_argument("--runtime-evidence-hash", required=True)
    parser.add_argument(
        "--predecessor-implementation-plan-path",
        required=True,
    )
    parser.add_argument(
        "--predecessor-implementation-plan-hash",
        required=True,
    )
    parser.add_argument("--patch-proposal-path", required=True)
    parser.add_argument("--patch-proposal-hash", required=True)
    parser.add_argument(
        "--current-implementation-plan-path",
        required=True,
    )
    parser.add_argument(
        "--current-implementation-plan-hash",
        required=True,
    )
    parser.add_argument(
        "--existing-binding-resolution-path",
        required=True,
    )
    parser.add_argument(
        "--existing-binding-resolution-hash",
        required=True,
    )
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--canonical-target-path", required=True)
    parser.add_argument("--target-symbol", required=True)
    parser.add_argument("--target-start-line", required=True, type=int)
    parser.add_argument("--target-end-line", required=True, type=int)


def _stagger_existing_binding_reauthorization_arguments(
    args: argparse.Namespace,
) -> dict[str, object]:
    return {
        "artifact_store_root": args.artifact_store_root,
        "feature_id": args.feature_id,
        "run_id": args.run_id,
        "feature_spec_path": args.feature_spec_path,
        "feature_spec_hash": args.feature_spec_hash,
        "runtime_evidence_path": args.runtime_evidence_path,
        "runtime_evidence_hash": args.runtime_evidence_hash,
        "predecessor_implementation_plan_path": (
            args.predecessor_implementation_plan_path
        ),
        "predecessor_implementation_plan_hash": (
            args.predecessor_implementation_plan_hash
        ),
        "patch_proposal_path": args.patch_proposal_path,
        "patch_proposal_hash": args.patch_proposal_hash,
        "current_implementation_plan_path": (
            args.current_implementation_plan_path
        ),
        "current_implementation_plan_hash": (
            args.current_implementation_plan_hash
        ),
        "existing_binding_resolution_path": (
            args.existing_binding_resolution_path
        ),
        "existing_binding_resolution_hash": (
            args.existing_binding_resolution_hash
        ),
        "source_root": args.source_root,
        "canonical_target_path": args.canonical_target_path,
        "target_symbol": args.target_symbol,
        "target_start_line": args.target_start_line,
        "target_end_line": args.target_end_line,
    }


def _add_stagger_observation_authority_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("--artifact-store-root", required=True)
    parser.add_argument("--feature-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--feature-spec-path", required=True)
    parser.add_argument("--feature-spec-hash", required=True)
    parser.add_argument("--runtime-evidence-path", required=True)
    parser.add_argument("--runtime-evidence-hash", required=True)
    parser.add_argument("--current-implementation-plan-path", required=True)
    parser.add_argument("--current-implementation-plan-hash", required=True)
    parser.add_argument("--patch-proposal-path", required=True)
    parser.add_argument("--patch-proposal-hash", required=True)
    parser.add_argument("--existing-binding-resolution-path", required=True)
    parser.add_argument("--existing-binding-resolution-hash", required=True)
    parser.add_argument(
        "--existing-edit-authority-approval-path",
        required=True,
    )
    parser.add_argument(
        "--existing-edit-authority-approval-hash",
        required=True,
    )
    parser.add_argument("--evidence-pack-path", required=True)
    parser.add_argument("--evidence-pack-hash", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--build-dependency-root", required=True)
    parser.add_argument("--unity-core-module-hash", required=True)
    parser.add_argument("--modules-asm-hash", required=True)
    parser.add_argument("--il2cpp-interop-runtime-hash", required=True)


def _stagger_observation_authority_arguments(
    args: argparse.Namespace,
) -> dict[str, object]:
    return {
        "artifact_store_root": args.artifact_store_root,
        "feature_id": args.feature_id,
        "run_id": args.run_id,
        "feature_spec_path": args.feature_spec_path,
        "feature_spec_hash": args.feature_spec_hash,
        "runtime_evidence_path": args.runtime_evidence_path,
        "runtime_evidence_hash": args.runtime_evidence_hash,
        "current_implementation_plan_path": (
            args.current_implementation_plan_path
        ),
        "current_implementation_plan_hash": (
            args.current_implementation_plan_hash
        ),
        "patch_proposal_path": args.patch_proposal_path,
        "patch_proposal_hash": args.patch_proposal_hash,
        "existing_binding_resolution_path": (
            args.existing_binding_resolution_path
        ),
        "existing_binding_resolution_hash": (
            args.existing_binding_resolution_hash
        ),
        "existing_edit_authority_approval_path": (
            args.existing_edit_authority_approval_path
        ),
        "existing_edit_authority_approval_hash": (
            args.existing_edit_authority_approval_hash
        ),
        "evidence_pack_path": args.evidence_pack_path,
        "evidence_pack_hash": args.evidence_pack_hash,
        "source_root": args.source_root,
        "build_dependency_root": args.build_dependency_root,
        "unity_core_module_hash": args.unity_core_module_hash,
        "modules_asm_hash": args.modules_asm_hash,
        "il2cpp_interop_runtime_hash": (
            args.il2cpp_interop_runtime_hash
        ),
    }


def _add_stagger_diagnostic_diff_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("--artifact-store-root", required=True)
    parser.add_argument("--feature-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--edit-authority-approval-path", required=True)
    parser.add_argument("--edit-authority-approval-hash", required=True)
    parser.add_argument("--evidence-pack-path", required=True)
    parser.add_argument("--evidence-pack-hash", required=True)
    parser.add_argument("--implementation-plan-path", required=True)
    parser.add_argument("--implementation-plan-hash", required=True)
    parser.add_argument("--source-root", required=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""

    parser = argparse.ArgumentParser(
        prog="mod-agent",
        description="Evidence-Grounded Controlled Code Generation Agent Platform CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan-request",
        help="Create a no-write request plan and planning brief.",
    )
    plan_parser.add_argument("description", help="Natural-language request description.")
    plan_parser.add_argument("--target-game")
    plan_parser.add_argument("--target-mod")

    evidence_parser = subparsers.add_parser(
        "evidence-request",
        help="Read the approved GTFO R8 snapshot and stop before implementation planning.",
    )
    evidence_parser.add_argument("description", help="Natural-language Mod request.")
    evidence_parser.add_argument("--evidence-root", required=True)
    evidence_parser.add_argument("--artifact-root", default="artifacts/evidence_only")
    evidence_parser.add_argument("--target-mod", default="WallCrawler")
    evidence_parser.add_argument("--assembly-path")
    evidence_parser.add_argument("--current-interop-path")
    evidence_parser.add_argument("--enemy-animation-fix-path")
    evidence_parser.add_argument("--stuck-enemy-fix-path")

    intelligent_evidence_parser = subparsers.add_parser(
        "intelligent-evidence-request",
        help="Let the Evidence specialist select read-only assembly tools and stop after evidence.",
    )
    intelligent_evidence_parser.add_argument(
        "description", help="Natural-language evidence request."
    )
    intelligent_evidence_parser.add_argument("--source-registry", required=True)
    intelligent_evidence_parser.add_argument(
        "--artifact-root", default="artifacts/intelligent_evidence_only"
    )
    intelligent_evidence_parser.add_argument("--settings", default="config/settings.yaml")
    intelligent_evidence_parser.add_argument("--target-domain", default="gtfo")
    intelligent_evidence_parser.add_argument("--target-mod", default="WallCrawler")
    intelligent_evidence_parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    intelligent_evidence_parser.add_argument(
        "--base-url-env", default="DASHSCOPE_BASE_URL"
    )
    intelligent_evidence_parser.add_argument(
        "--allow-evidence-disclosure",
        action="store_true",
        help=(
            "Approve this run to send the natural-language request, path-hidden source "
            "views, and metadata/IL tool observations to the configured model."
        ),
    )
    intelligent_evidence_parser.add_argument(
        "--local-ollama",
        action="store_true",
        help=(
            "Use Ollama through a literal loopback endpoint; no external model "
            "disclosure is authorized."
        ),
    )
    intelligent_evidence_parser.add_argument(
        "--ollama-base-url", default="http://127.0.0.1:11434"
    )
    intelligent_evidence_parser.add_argument(
        "--ollama-model", default="qwen3:4b-instruct"
    )
    intelligent_evidence_parser.add_argument(
        "--ollama-max-output-tokens", type=int, default=4096
    )

    apply_parser = subparsers.add_parser(
        "apply-patch",
        help="Blocked placeholder for future patch application.",
    )
    apply_parser.add_argument("--confirm", action="store_true", help="Request confirmed apply.")

    run_parser = subparsers.add_parser(
        "run-request",
        help="Run one controlled request against an isolated copy of a real target project.",
    )
    run_parser.add_argument("description", help="Natural-language Mod request.")
    run_parser.add_argument("--target-project", required=True)
    run_parser.add_argument(
        "--workspace-root",
        default="workspaces/v2_codegen_real_001",
    )
    run_parser.add_argument("--settings", default="config/settings.yaml")
    run_parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    run_parser.add_argument("--base-url-env", default="DASHSCOPE_BASE_URL")
    run_parser.add_argument(
        "--local-ollama",
        action="store_true",
        help=(
            "Use Ollama through a literal loopback endpoint for this run; "
            "no external source disclosure is authorized."
        ),
    )
    run_parser.add_argument(
        "--ollama-base-url", default="http://127.0.0.1:11434"
    )
    run_parser.add_argument("--ollama-model")
    run_parser.add_argument(
        "--ollama-max-output-tokens", type=int, default=4096
    )
    run_parser.add_argument("--ollama-context-window", type=int)
    run_parser.add_argument(
        "--allow-source-disclosure",
        action="store_true",
        help=(
            "Explicitly allow this run to send retrieved local source excerpts "
            "and binding context to the configured external LLM."
        ),
    )
    run_parser.add_argument("--confirm-isolated-write", action="store_true")
    run_parser.add_argument("--allow-build", action="store_true")
    run_parser.add_argument(
        "--run-gtfo-runtime",
        action="store_true",
        help=(
            "Continue the admitted run after Build through configured GTFO Runtime "
            "Verification, Evaluation, and Terminal Record."
        ),
    )
    run_parser.add_argument(
        "--allow-game-launch",
        action="store_true",
        help=(
            "Authorize this run only to launch GTFO through the configured Runtime "
            "profile; requires --run-gtfo-runtime."
        ),
    )
    run_parser.add_argument(
        "--runtime-plugin-destination",
        help=(
            "Absolute game-directory DLL path for the verified final Build; "
            "requires Runtime and game-directory write approval."
        ),
    )
    run_parser.add_argument(
        "--allow-game-directory-write",
        action="store_true",
        help=(
            "Authorize this run only to deploy the verified final DLL and restore "
            "the destination after Runtime capture."
        ),
    )
    resume_runtime_parser = subparsers.add_parser(
        "resume-runtime",
        help=(
            "Continue a validated successful Build checkpoint through the "
            "existing Runtime, Evaluation, and Terminal graph path."
        ),
    )
    resume_runtime_parser.add_argument("--run-root", required=True)
    resume_runtime_parser.add_argument("--artifact-store-root")
    resume_runtime_parser.add_argument("--feature-id", required=True)
    resume_runtime_parser.add_argument("--checkpoint-path", required=True)
    resume_runtime_parser.add_argument("--checkpoint-hash", required=True)
    resume_runtime_parser.add_argument("--resume-id")
    resume_runtime_parser.add_argument(
        "--recover-accepted-resume",
        action="store_true",
        help=(
            "Reuse the exact accepted ResumeReport for a bounded pre-Runtime "
            "recovery; requires --resume-id and creates no second ResumeReport."
        ),
    )
    resume_runtime_parser.add_argument(
        "--retry-runtime-observation",
        action="store_true",
        help=(
            "Reuse the exact accepted ResumeReport only when the latest "
            "RuntimeEvidence and RepairPlan require a bounded observation retry."
        ),
    )
    resume_runtime_parser.add_argument(
        "--runtime-output-root",
        help=(
            "Absolute empty run-local output directory required for an initial "
            "Stagger repair Runtime and for --retry-runtime-observation."
        ),
    )
    resume_runtime_parser.add_argument("--approved-by", required=True)
    resume_runtime_parser.add_argument("--settings", default="config/settings.yaml")
    resume_runtime_parser.add_argument("--allow-game-launch", action="store_true")
    resume_runtime_parser.add_argument(
        "--runtime-plugin-destination",
        required=True,
    )
    resume_runtime_parser.add_argument(
        "--allow-game-directory-write",
        action="store_true",
    )
    preflight_runtime_parser = subparsers.add_parser(
        "preflight-runtime",
        help=(
            "Read-validate a Build-to-Runtime continuation without writing, "
            "consuming the checkpoint, entering the graph, copying a DLL, or "
            "launching a process."
        ),
    )
    preflight_runtime_parser.add_argument("--run-root", required=True)
    preflight_runtime_parser.add_argument("--artifact-store-root")
    preflight_runtime_parser.add_argument("--feature-id", required=True)
    preflight_runtime_parser.add_argument("--checkpoint-path", required=True)
    preflight_runtime_parser.add_argument("--checkpoint-hash", required=True)
    preflight_runtime_parser.add_argument("--resume-id")
    preflight_runtime_parser.add_argument(
        "--recover-accepted-resume",
        action="store_true",
        help=(
            "Read-validate the exact accepted ResumeReport recovery boundary "
            "without writing or launching."
        ),
    )
    preflight_runtime_parser.add_argument(
        "--retry-runtime-observation",
        action="store_true",
        help=(
            "Read-validate an observation-owned Runtime retry without writing "
            "or launching."
        ),
    )
    preflight_runtime_parser.add_argument(
        "--runtime-output-root",
        help=(
            "Absolute empty run-local output directory required for an initial "
            "Stagger repair Runtime and for --retry-runtime-observation."
        ),
    )
    preflight_runtime_parser.add_argument("--settings")
    preflight_runtime_parser.add_argument("--runtime-plugin-destination")
    stagger_edit_authority_parser = subparsers.add_parser(
        "preflight-stagger-edit-authority",
        help=(
            "Read-validate the current Stagger Runtime failure and emit an "
            "exact no-write Edit Authority proposal."
        ),
    )
    _add_stagger_edit_authority_arguments(
        stagger_edit_authority_parser
    )
    request_stagger_edit_authority_parser = subparsers.add_parser(
        "request-stagger-edit-authority",
        help=(
            "Persist one exact technical request without granting Edit "
            "Authority or mutating the Registry."
        ),
    )
    _add_stagger_edit_authority_arguments(
        request_stagger_edit_authority_parser
    )
    preflight_existing_binding_parser = subparsers.add_parser(
        "preflight-stagger-existing-binding-reauthorization",
        help=(
            "Read-validate the exact existing Stagger repair binding and "
            "emit a no-write reauthorization request payload."
        ),
    )
    _add_stagger_existing_binding_reauthorization_arguments(
        preflight_existing_binding_parser
    )
    request_existing_binding_parser = subparsers.add_parser(
        "request-stagger-existing-binding-reauthorization",
        help=(
            "Persist one no-authority request for the exact existing "
            "Stagger repair binding."
        ),
    )
    _add_stagger_existing_binding_reauthorization_arguments(
        request_existing_binding_parser
    )
    preflight_observation_authority_parser = subparsers.add_parser(
        "preflight-stagger-hud-parent-observation-authority",
        help=(
            "Read-validate the complete bounded Stagger HUD parent "
            "diagnostic Plan and emit a no-write authority proposal."
        ),
    )
    _add_stagger_observation_authority_arguments(
        preflight_observation_authority_parser
    )
    request_observation_authority_parser = subparsers.add_parser(
        "request-stagger-hud-parent-observation-authority",
        help=(
            "Persist one no-authority Request for the complete bounded "
            "Stagger HUD parent diagnostic Plan."
        ),
    )
    _add_stagger_observation_authority_arguments(
        request_observation_authority_parser
    )
    stagger_diagnostic_diff_parser = subparsers.add_parser(
        "preflight-stagger-hud-parent-diagnostic-exact-diff",
        help=(
            "Generate the exact four-change Stagger HUD diagnostic diff "
            "without writing source or Artifacts."
        ),
    )
    _add_stagger_diagnostic_diff_arguments(
        stagger_diagnostic_diff_parser
    )
    preflight_stagger_review_parser = subparsers.add_parser(
        "preflight-stagger-edit-authority-review",
        help=(
            "Enter the exact Graph review interrupt without writing a "
            "checkpoint, ResumeReport, Approval, or BindingResolution."
        ),
    )
    preflight_stagger_review_parser.add_argument(
        "--artifact-store-root",
        required=True,
    )
    preflight_stagger_review_parser.add_argument(
        "--feature-id",
        required=True,
    )
    preflight_stagger_review_parser.add_argument(
        "--request-path",
        required=True,
    )
    preflight_stagger_review_parser.add_argument(
        "--request-artifact-hash",
        required=True,
    )
    preflight_stagger_review_parser.add_argument(
        "--authority-request-hash",
        required=True,
    )
    resume_stagger_edit_authority_parser = subparsers.add_parser(
        "resume-stagger-edit-authority-review",
        help=(
            "Carry one exact human decision through the existing LangGraph "
            "Edit Authority interrupt/resume gate."
        ),
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--artifact-store-root",
        required=True,
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--feature-id",
        required=True,
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--request-path",
        required=True,
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--request-artifact-hash",
        required=True,
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--authority-request-hash",
        required=True,
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--resume-id",
        required=True,
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--decision",
        required=True,
        choices=("approve", "reject"),
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--approved-by",
        required=True,
    )
    resume_stagger_edit_authority_parser.add_argument(
        "--approved-at",
        required=True,
    )

    return parser


_VERIFICATION_OPERATION_EXIT_CODES = {
    "succeeded": 0,
    "domain_blocked": 1,
    "operator_input_required": 1,
    "platform_blocked": 2,
    "partial": 2,
}

_LEGACY_ADVISORY_READY_STATUSES = {
    "READY_FOR_RUNTIME_PROFILE",
    "READY_FOR_EXTERNAL_AUTHORIZATION",
}


def _verification_operation_exit_code(result: object) -> int:
    """Map one public verification result to its declaration-owned exit."""

    if not isinstance(result, Mapping):
        return 2
    operation_result = result.get("verification_operation_result")
    if not isinstance(operation_result, Mapping):
        return 2
    disposition = operation_result.get("execution_disposition")
    if not isinstance(disposition, str):
        return 2
    return _VERIFICATION_OPERATION_EXIT_CODES.get(disposition, 2)


def _verification_preflight_exit_code(result: object) -> int:
    """Map one execution-grade preflight result."""

    if not isinstance(result, Mapping):
        return 2
    operation_result = result.get("verification_operation_preflight_result")
    if not isinstance(operation_result, Mapping):
        return 2
    return 0 if operation_result.get("preflight_status") == "ready" else 2


def _legacy_advisory_preflight_exit_code(result: object) -> int:
    """Preserve the exact CLI-only legacy advisory mapping boundary."""

    if not isinstance(result, Mapping):
        return 2
    if (
        "verification_operation_preflight_result" in result
        or "verification_operation_result" in result
    ):
        return 2
    return 0 if result.get("status") in _LEGACY_ADVISORY_READY_STATUSES else 2


def _edit_authority_review_exit_code(result: object) -> int:
    """Project the declaration-owned Edit Authority result to CLI exit status."""

    if not isinstance(result, Mapping):
        return 2
    projection = result.get("edit_authority_review_result")
    feature_id = result.get("feature_id")
    approval_identity_hash = result.get("request_hash")
    if (
        not isinstance(projection, Mapping)
        or type(feature_id) is not str
        or not feature_id
        or type(approval_identity_hash) is not str
        or not approval_identity_hash
    ):
        return 2
    try:
        machine_result = parse_current_edit_authority_review_result(
            projection,
            feature_id=feature_id,
            approval_identity_hash=approval_identity_hash,
        )
    except ValueError:
        return 2
    return (
        0
        if machine_result.platform_status == "completed"
        and machine_result.review_outcome == "approved"
        and machine_result.materialization_status == "completed"
        else 2
    )


def _run_preflight_runtime_command(args: argparse.Namespace) -> int:
    """Prepare one legacy Runtime preflight call and present its public result."""

    try:
        result = preflight_local_runtime(
            run_root=args.run_root,
            artifact_store_root=args.artifact_store_root,
            feature_id=args.feature_id,
            checkpoint_path=args.checkpoint_path,
            checkpoint_hash=args.checkpoint_hash,
            resume_id=args.resume_id,
            recover_accepted_resume=bool(args.recover_accepted_resume),
            retry_runtime_observation=bool(args.retry_runtime_observation),
            runtime_output_root=args.runtime_output_root,
            settings_path=args.settings,
            runtime_plugin_destination=args.runtime_plugin_destination,
        )
    except LocalEntryError as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "command": "preflight-runtime",
                    "reason": str(exc),
                    "writes_performed": False,
                    "graph_invoked": False,
                    "checkpoint_consumed": False,
                    "resume_report_created": False,
                    "runtime_evidence_created": False,
                    "process_launched": False,
                    "dll_copied": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return _legacy_advisory_preflight_exit_code(result)


def _run_resume_runtime_command(args: argparse.Namespace) -> int:
    """Prepare one legacy Runtime execution call and present its public result."""

    try:
        result = resume_local_runtime(
            run_root=args.run_root,
            artifact_store_root=args.artifact_store_root,
            feature_id=args.feature_id,
            checkpoint_path=args.checkpoint_path,
            checkpoint_hash=args.checkpoint_hash,
            resume_id=args.resume_id,
            recover_accepted_resume=bool(args.recover_accepted_resume),
            retry_runtime_observation=bool(args.retry_runtime_observation),
            runtime_output_root=args.runtime_output_root,
            approved_by=args.approved_by,
            settings_path=args.settings,
            allow_game_launch=bool(args.allow_game_launch),
            runtime_plugin_destination=args.runtime_plugin_destination,
            allow_game_directory_write=bool(args.allow_game_directory_write),
        )
    except LocalEntryError as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "command": "resume-runtime",
                    "reason": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return _verification_operation_exit_code(result)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local controlled-development CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "plan-request":
        result = plan_request(
            args.description,
            target_game=args.target_game,
            target_mod=args.target_mod,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "apply-patch":
        decision = PermissionModel().decide("confirmed_write")
        print(
            json.dumps(
                {
                    "status": "BLOCKED" if not decision.allowed else "allowed",
                    "command": "apply-patch",
                    "reason": decision.reason,
                    "required_approval": decision.required_approval,
                    "confirmed": bool(args.confirm),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "evidence-request":
        try:
            result = run_gtfo_r8_evidence_only(
                description=args.description,
                evidence_root=args.evidence_root,
                artifact_root=args.artifact_root,
                target_mod=args.target_mod,
                assembly_path=args.assembly_path,
                current_interop_path=args.current_interop_path,
                enemy_animation_fix_path=args.enemy_animation_fix_path,
                stuck_enemy_fix_path=args.stuck_enemy_fix_path,
            )
        except (
            EvidenceOnlyError,
            R8EvidenceError,
            R8ILInspectionError,
            OSError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {"status": "BLOCKED", "command": "evidence-request", "reason": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "intelligent-evidence-request":
        try:
            result = run_intelligent_evidence_only(
                description=args.description,
                source_registry_path=args.source_registry,
                artifact_root=args.artifact_root,
                settings_path=args.settings,
                allow_evidence_disclosure=bool(args.allow_evidence_disclosure),
                target_domain=args.target_domain,
                target_mod=args.target_mod,
                api_key_env=args.api_key_env,
                base_url_env=args.base_url_env,
                local_ollama=bool(args.local_ollama),
                ollama_base_url=args.ollama_base_url,
                ollama_model=args.ollama_model,
                ollama_max_output_tokens=args.ollama_max_output_tokens,
            )
        except ArtifactStorePreflightError as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": "intelligent-evidence-request",
                        "reason": str(exc),
                        "diagnostic": {
                            "category": "infrastructure_preflight_failure",
                            "component": "artifact_store",
                            "stage": "artifact_preflight",
                            "code": "artifact_path_unaddressable",
                            "operation": "os.replace",
                            "model_execution_started": False,
                            "tool_execution_started": False,
                            "model_call_count": 0,
                            "tool_call_count": 0,
                            "details": {
                                "artifact_type": exc.artifact_type,
                                "path_role": exc.path_role,
                                "source_path_length": exc.source_path_length,
                                "target_path_length": exc.target_path_length,
                                "target_parent_exists": exc.target_parent_exists,
                                "winerror": exc.winerror,
                            },
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        except (IntelligentEvidenceEntryError, OSError, RuntimeError, ValueError) as exc:
            blocked_payload: dict[str, object] = {
                "status": "BLOCKED",
                "command": "intelligent-evidence-request",
                "reason": str(exc),
            }
            if isinstance(exc, IntelligentEvidenceEntryError) and exc.diagnostic:
                blocked_payload["diagnostic"] = dict(exc.diagnostic)
                if exc.diagnostic.get("run_status") == "budget_exhausted":
                    blocked_payload["status"] = "budget_exhausted"
            print(
                json.dumps(
                    blocked_payload,
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-request":
        def read_diff_approval(dry_run: dict[str, object]) -> str:
            print(
                json.dumps(
                    {
                        "status": "AWAITING_EXACT_DIFF_APPROVAL",
                        "diff_hash": dry_run.get("diff_hash"),
                        "context_hashes": dry_run.get("context_hashes"),
                        "unified_diff": dry_run.get("unified_diff"),
                        "unified_diff_sha256": dry_run.get(
                            "unified_diff_sha256"
                        ),
                        "unified_diff_bytes": dry_run.get("unified_diff_bytes"),
                        "diff_stats": dry_run.get("diff_stats"),
                        "static_checks": dry_run.get("static_checks"),
                        "diff_preview": dry_run.get("diff_preview"),
                        "instruction": (
                            "Paste the exact diff_hash to approve isolated apply; "
                            "enter REJECTED_BY_USER to explicitly reject it; any "
                            "other input blocks the write as a hash mismatch."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            print("Exact diff hash approval: ", end="", file=sys.stderr, flush=True)
            return sys.stdin.readline().strip()

        try:
            result = run_local_request(
                description=args.description,
                target_project=args.target_project,
                workspace_base=args.workspace_root,
                settings_path=args.settings,
                api_key_env=args.api_key_env,
                base_url_env=args.base_url_env,
                confirm_isolated_write=bool(args.confirm_isolated_write),
                allow_build=bool(args.allow_build),
                allow_source_disclosure=bool(args.allow_source_disclosure),
                run_gtfo_runtime=bool(args.run_gtfo_runtime),
                allow_game_launch=bool(args.allow_game_launch),
                runtime_plugin_destination=args.runtime_plugin_destination,
                allow_game_directory_write=bool(args.allow_game_directory_write),
                diff_approval_reader=read_diff_approval,
                local_ollama=bool(args.local_ollama),
                ollama_base_url=args.ollama_base_url,
                ollama_model=args.ollama_model,
                ollama_max_output_tokens=args.ollama_max_output_tokens,
                ollama_context_window=args.ollama_context_window,
            )
        except ProductExecutionPresentationError as exc:
            print(
                json.dumps(
                    {
                        "status": "PRESENTATION_FAILED",
                        "product_execution_result": (
                            exc.product_execution_result.to_dict()
                        ),
                        "audit_error": {
                            "failure_class": exc.failure_class,
                            "failure_message": exc.failure_message,
                            "sink": exc.sink,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        except ProductExecutionContractError as exc:
            print(
                json.dumps(
                    {
                        "status": "CONTRACT_ERROR",
                        "reason": exc.reason,
                        "side_effects_may_have_started": (
                            exc.side_effects_may_have_started
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        except LocalEntryError as exc:
            print(
                json.dumps(
                    {"status": "BLOCKED", "reason": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        structured = result.get("product_execution_result")
        if not isinstance(structured, Mapping):
            return 2
        try:
            machine_result = ProductExecutionResultV1.from_dict(structured)
        except (ProductExecutionContractError, ValueError, TypeError):
            return 2
        return {
            "succeeded": 0,
            "domain_blocked": 1,
            "platform_blocked": 2,
            "partial": 2,
        }[machine_result.execution_disposition]

    if args.command == "preflight-stagger-edit-authority":
        try:
            result = preflight_stagger_edit_authority(
                **_stagger_edit_authority_arguments(args)
            )
        except (
            StaggerEditAuthorityPreflightError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": "preflight-stagger-edit-authority",
                        "reason": str(exc),
                        "approval_required": False,
                        "registry_mutation_allowed": False,
                        "repair_allowed": False,
                        "writes_performed": False,
                        "artifact_writes_performed": False,
                        "repair_planner_invoked": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "request-stagger-edit-authority":
        try:
            result = create_stagger_edit_authority_request(
                **_stagger_edit_authority_arguments(args),
            )
        except (
            StaggerEditAuthorityApprovalError,
            StaggerEditAuthorityPreflightError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": "request-stagger-edit-authority",
                        "reason": str(exc),
                        "writes_performed": None,
                        "artifact_store_inspection_required": True,
                        "repair_planner_invoked": False,
                        "repair_allowed": False,
                        "source_patch_allowed": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if (
        args.command
        == "preflight-stagger-existing-binding-reauthorization"
    ):
        try:
            result = preflight_stagger_existing_binding_reauthorization(
                **_stagger_existing_binding_reauthorization_arguments(
                    args
                )
            )
        except (
            StaggerEditAuthorityPreflightError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": args.command,
                        "reason": str(exc),
                        "approval_required": False,
                        "registry_mutation_allowed": False,
                        "repair_allowed": False,
                        "writes_performed": False,
                        "artifact_writes_performed": False,
                        "repair_planner_invoked": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if (
        args.command
        == "request-stagger-existing-binding-reauthorization"
    ):
        try:
            result = (
                create_stagger_existing_binding_reauthorization_request(
                    **_stagger_existing_binding_reauthorization_arguments(
                        args
                    )
                )
            )
        except (
            StaggerEditAuthorityApprovalError,
            StaggerEditAuthorityPreflightError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": args.command,
                        "reason": str(exc),
                        "writes_performed": None,
                        "artifact_store_inspection_required": True,
                        "repair_planner_invoked": False,
                        "repair_allowed": False,
                        "source_patch_allowed": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if (
        args.command
        == "preflight-stagger-hud-parent-observation-authority"
    ):
        try:
            result = preflight_stagger_hud_parent_observation_authority(
                **_stagger_observation_authority_arguments(args)
            )
        except (
            StaggerEditAuthorityPreflightError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": args.command,
                        "reason": str(exc),
                        "approval_required": False,
                        "registry_mutation_allowed": False,
                        "repair_allowed": False,
                        "writes_performed": False,
                        "artifact_writes_performed": False,
                        "repair_planner_invoked": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if (
        args.command
        == "request-stagger-hud-parent-observation-authority"
    ):
        try:
            result = (
                create_stagger_hud_parent_observation_authority_request(
                    **_stagger_observation_authority_arguments(args)
                )
            )
        except (
            StaggerEditAuthorityApprovalError,
            StaggerEditAuthorityPreflightError,
            OSError,
            RuntimeError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": args.command,
                        "reason": str(exc),
                        "writes_performed": None,
                        "artifact_store_inspection_required": True,
                        "repair_planner_invoked": False,
                        "repair_allowed": False,
                        "source_patch_allowed": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if (
        args.command
        == "preflight-stagger-hud-parent-diagnostic-exact-diff"
    ):
        try:
            result = preflight_stagger_hud_parent_diagnostic_exact_diff(
                artifact_store_root=args.artifact_store_root,
                feature_id=args.feature_id,
                run_id=args.run_id,
                edit_authority_approval_path=(
                    args.edit_authority_approval_path
                ),
                edit_authority_approval_hash=(
                    args.edit_authority_approval_hash
                ),
                evidence_pack_path=args.evidence_pack_path,
                evidence_pack_hash=args.evidence_pack_hash,
                implementation_plan_path=args.implementation_plan_path,
                implementation_plan_hash=args.implementation_plan_hash,
                source_root=args.source_root,
            )
        except StaggerDiagnosticDiffPreflightError as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": (
                            "preflight-stagger-hud-parent-diagnostic-"
                            "exact-diff"
                        ),
                        "reason": str(exc),
                        "writes_performed": False,
                        "artifact_writes_performed": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "preflight-stagger-edit-authority-review":
        try:
            result = preflight_stagger_edit_authority_review(
                artifact_store_root=args.artifact_store_root,
                feature_id=args.feature_id,
                edit_authority_request_path=args.request_path,
                edit_authority_request_hash=(
                    args.request_artifact_hash
                ),
                authority_request_hash=args.authority_request_hash,
            )
        except LocalEntryError as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": (
                            "preflight-stagger-edit-authority-review"
                        ),
                        "reason": str(exc),
                        "writes_performed": False,
                        "artifact_writes_performed": False,
                        "repair_planner_invoked": False,
                        "source_patch_allowed": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "resume-stagger-edit-authority-review":
        try:
            result = resume_stagger_edit_authority_review(
                artifact_store_root=args.artifact_store_root,
                feature_id=args.feature_id,
                edit_authority_request_path=args.request_path,
                edit_authority_request_hash=args.request_artifact_hash,
                authority_request_hash=args.authority_request_hash,
                resume_id=args.resume_id,
                decision=args.decision,
                approved_by=args.approved_by,
                approved_at=args.approved_at,
            )
        except EditAuthorityPresentationError as exc:
            print(
                json.dumps(
                    {
                        "result_type": "edit_authority_presentation_error_v1",
                        "status": "PRESENTATION_FAILED",
                        "command": "resume-stagger-edit-authority-review",
                        "reason": str(exc),
                        "edit_authority_review_result": (
                            exc.edit_authority_review_result.to_dict()
                        ),
                        "presentation_error": exc.presentation_error,
                        "audit_error": exc.audit_error,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        except (LocalEntryError, OSError, RuntimeError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": (
                            "resume-stagger-edit-authority-review"
                        ),
                        "reason": str(exc),
                        "artifact_store_inspection_required": True,
                        "repair_planner_invoked": False,
                        "source_patch_allowed": False,
                        "source_modified": False,
                        "build_performed": False,
                        "process_launched": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return _edit_authority_review_exit_code(result)

    if args.command == "preflight-runtime":
        return _run_preflight_runtime_command(args)

    if args.command == "resume-runtime":
        return _run_resume_runtime_command(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
