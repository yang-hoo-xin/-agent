"""Artifact type registry and contract declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactContract:
    """Contract for a registered artifact type."""

    artifact_type: str
    schema_version: str
    required_fields: frozenset[str]
    producer_stage: str
    consumer_stages: frozenset[str]
    allowed_statuses: frozenset[str]
    required_upstream_artifacts: frozenset[str] = frozenset()
    dashboard_projection: tuple[str, ...] = ()
    eval_visibility: bool = True


class ArtifactRegistryError(ValueError):
    """Raised when an artifact contract is missing or violated."""


class ArtifactTypeRegistry:
    """Producer-consumer registry for artifact contracts."""

    def __init__(self, contracts: list[ArtifactContract] | None = None) -> None:
        self._contracts = {
            contract.artifact_type: contract
            for contract in (contracts or default_artifact_contracts())
        }

    def get(self, artifact_type: str) -> ArtifactContract:
        """Return the contract for an artifact type."""

        try:
            return self._contracts[artifact_type]
        except KeyError as exc:
            raise ArtifactRegistryError(f"Unregistered artifact_type: {artifact_type}") from exc

    def validate_write(
        self,
        *,
        artifact_type: str,
        status: str,
        payload: dict[str, Any],
    ) -> ArtifactContract:
        """Validate artifact type, status, and required payload fields."""

        contract = self.get(artifact_type)
        if status not in contract.allowed_statuses:
            raise ArtifactRegistryError(
                f"Status {status!r} is not allowed for {artifact_type!r}"
            )
        missing = sorted(field for field in contract.required_fields if field not in payload)
        if missing:
            raise ArtifactRegistryError(
                f"Artifact {artifact_type!r} missing required fields: {missing}"
            )
        return contract

    def validate_envelope(self, envelope: dict[str, Any]) -> ArtifactContract:
        """Validate envelope-level contract fields."""

        artifact_type = envelope.get("artifact_type")
        if not isinstance(artifact_type, str):
            raise ArtifactRegistryError("Artifact envelope missing artifact_type")
        contract = self.get(artifact_type)
        if envelope.get("schema_version") != contract.schema_version:
            raise ArtifactRegistryError(
                f"Unsupported schema_version for {artifact_type!r}: "
                f"{envelope.get('schema_version')!r}"
            )
        if envelope.get("producer_stage") != contract.producer_stage:
            raise ArtifactRegistryError(
                f"Invalid producer_stage for {artifact_type!r}: "
                f"{envelope.get('producer_stage')!r}"
            )
        status = envelope.get("status")
        if status not in contract.allowed_statuses:
            raise ArtifactRegistryError(
                f"Status {status!r} is not allowed for {artifact_type!r}"
            )
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise ArtifactRegistryError("Artifact envelope data must be a mapping")
        missing = sorted(field for field in contract.required_fields if field not in data)
        if missing:
            raise ArtifactRegistryError(
                f"Artifact {artifact_type!r} missing required fields: {missing}"
            )
        return contract

    def validate_consumer(self, artifact_type: str, consumer_stage: str) -> None:
        """Validate that a stage may consume an artifact type."""

        contract = self.get(artifact_type)
        if consumer_stage not in contract.consumer_stages:
            raise ArtifactRegistryError(
                f"{consumer_stage!r} is not a registered consumer for {artifact_type!r}"
            )

    def artifact_types(self) -> frozenset[str]:
        """Return registered artifact type names."""

        return frozenset(self._contracts)


def default_artifact_contracts() -> list[ArtifactContract]:
    """Return the first controlled workflow artifact contracts."""

    statuses = frozenset({"success", "blocked", "failed", "stubbed", "skipped"})
    return [
        ArtifactContract(
            artifact_type="request_planning_report",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "user_request",
                    "route",
                    "risk_level",
                    "requires_hook_evidence",
                    "requires_runtime_evidence",
                    "uncertainties",
                    "blocked",
                }
            ),
            producer_stage="request_planning",
            consumer_stages=frozenset(
                {"planning_brief", "draft_feature_spec", "blocked", "dashboard"}
            ),
            allowed_statuses=statuses,
            dashboard_projection=("message", "route", "risk_level", "blocked"),
        ),
        ArtifactContract(
            artifact_type="mod_planning_brief",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "decision",
                    "user_intent",
                    "request_type",
                    "knowledge_query_plan",
                    "retrieved_experience",
                    "planning_options",
                    "selected_plan",
                    "handoff",
                    "verification_boundary",
                    "next_action",
                    "blocked",
                    "blockers",
                }
            ),
            producer_stage="planning_brief",
            consumer_stages=frozenset(
                {"draft_feature_spec", "retrieve_evidence", "dashboard"}
            ),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"request_planning_report"}),
            dashboard_projection=("message", "decision", "request_type", "next_action"),
        ),
        ArtifactContract(
            artifact_type="feature_spec",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "user_request",
                    "target_behavior",
                    "non_goals",
                    "target_mod",
                    "risk_level",
                    "acceptance_criteria",
                    "evidence_requirements",
                    "runtime_verification_plan",
                    "blocked",
                    "blockers",
                }
            ),
            producer_stage="feature_spec",
            consumer_stages=frozenset(
                {"retrieve_evidence", "create_implementation_plan", "dashboard"}
            ),
            allowed_statuses=statuses,
            dashboard_projection=("message", "target_behavior", "risk_level", "blocked"),
        ),
        ArtifactContract(
            artifact_type="evidence_pack",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "query",
                    "readiness",
                    "can_generate_patch",
                    "authority",
                    "authoritative_for_patch",
                    "identity_schema_version",
                    "identity_field_mapping",
                    "items",
                    "gaps",
                    "excluded",
                    "blockers",
                    "retrieval_methods_used",
                    "missing_evidence",
                    "disabled_modes",
                    "timing",
                    "trace_refs",
                }
            ),
            producer_stage="evidence_retrieval",
            consumer_stages=frozenset(
                {"create_implementation_plan", "generate_patch_proposal", "dashboard"}
            ),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"feature_spec"}),
            dashboard_projection=(
                "message",
                "readiness",
                "can_generate_patch",
                "authority",
                "authoritative_for_patch",
                "budget_summary",
            ),
        ),
        ArtifactContract(
            artifact_type="implementation_plan",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "evidence_source_paths",
                    "target_files",
                    "target_symbols",
                    "evidence_refs",
                    "proposed_changes",
                    "side_effect_boundaries",
                    "test_plan",
                    "rollback_plan",
                    "open_questions",
                    "blocking",
                    "blockers",
                }
            ),
            producer_stage="implementation_plan",
            consumer_stages=frozenset({"generate_patch_proposal", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"feature_spec", "evidence_pack"}),
            dashboard_projection=("message", "target_files", "blocking"),
        ),
        ArtifactContract(
            artifact_type="patch_proposal",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "proposal_id",
                    "feature_id",
                    "summary",
                    "files",
                    "diff_intent",
                    "evidence_refs",
                    "scope_boundary",
                    "risk_assessment",
                    "expected_tests",
                    "manual_review_notes",
                    "blocked",
                    "blockers",
                }
            ),
            producer_stage="patch_proposal",
            consumer_stages=frozenset({"review_proposal", "dry_run_apply", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"implementation_plan", "evidence_pack"}),
            dashboard_projection=("message", "files", "blocked"),
        ),
        ArtifactContract(
            artifact_type="proposal_review",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "decision",
                    "findings",
                    "required_changes",
                    "allowed_next_stage",
                    "checked_rules",
                    "trace_metrics",
                }
            ),
            producer_stage="proposal_review",
            consumer_stages=frozenset({"dry_run_apply", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"patch_proposal"}),
            dashboard_projection=("message", "decision", "allowed_next_stage"),
        ),
        ArtifactContract(
            artifact_type="dry_run_result",
            schema_version="1.0",
            required_fields=frozenset({"node_name", "stage", "message"}),
            producer_stage="dry_run_apply",
            consumer_stages=frozenset({"build", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"patch_proposal", "proposal_review"}),
            dashboard_projection=("message",),
        ),
        ArtifactContract(
            artifact_type="build_result",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "execution_mode",
                    "status",
                    "command",
                    "exit_code",
                    "stdout_path",
                    "stderr_path",
                    "errors",
                    "warnings",
                    "duration_ms",
                    "error_class",
                    "diagnostics",
                    "repair_handoff",
                    "expected_artifacts",
                    "verified_artifacts",
                    "artifact_verification",
                    "real_build_performed",
                    "claims_real_build_success",
                }
            ),
            producer_stage="build",
            consumer_stages=frozenset(
                {"collect_runtime_evidence", "evaluate", "repair_plan", "dashboard"}
            ),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"dry_run_result"}),
            dashboard_projection=("message", "status", "error_class"),
        ),
        ArtifactContract(
            artifact_type="runtime_evidence",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "execution_mode",
                    "evidence_source",
                    "startup_loaded",
                    "gameplay_behavior_verified",
                    "evidence_items",
                    "verification_status",
                    "acceptance_status",
                    "acceptance_verified",
                    "acceptance_contract",
                    "raw_supplied_output",
                    "sources",
                    "non_goals_checked",
                    "limitations",
                    "real_runtime_performed",
                    "claims_real_runtime_success",
                }
            ),
            producer_stage="runtime_evidence",
            consumer_stages=frozenset({"evaluate", "repair_plan", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"build_result"}),
            dashboard_projection=("message",),
        ),
        ArtifactContract(
            artifact_type="manual_evidence",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "execution_mode",
                    "evidence_source",
                    "startup_loaded",
                    "gameplay_behavior_verified",
                    "evidence_items",
                    "verification_status",
                    "acceptance_status",
                    "acceptance_verified",
                    "acceptance_contract",
                    "raw_supplied_output",
                    "sources",
                    "non_goals_checked",
                    "limitations",
                    "real_runtime_performed",
                    "claims_real_runtime_success",
                }
            ),
            producer_stage="runtime_evidence",
            consumer_stages=frozenset({"evaluate", "repair_plan", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"build_result"}),
            dashboard_projection=("message", "verification_status", "acceptance_status"),
        ),
        ArtifactContract(
            artifact_type="screenshot_registry",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "feature_id",
                    "screenshot_count",
                    "captioned_count",
                    "missing_caption_count",
                    "screenshots",
                    "verification_status",
                    "acceptance_status",
                    "claims_real_runtime_success",
                    "limitations",
                }
            ),
            producer_stage="runtime_evidence",
            consumer_stages=frozenset({"evaluate", "repair_plan", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"build_result"}),
            dashboard_projection=(
                "message",
                "screenshot_count",
                "captioned_count",
                "verification_status",
                "acceptance_status",
            ),
        ),
        ArtifactContract(
            artifact_type="repair_plan",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "repair_id",
                    "feature_id",
                    "failure_source",
                    "failure_class",
                    "failure_evidence",
                    "evidence_refs",
                    "root_cause_hypotheses",
                    "hypothesis",
                    "recommended_fix_strategy",
                    "minimal_changes",
                    "retry_count",
                    "retry_budget",
                    "retry_budget_remaining",
                    "retry_exhausted",
                    "scope_expansion_allowed",
                    "stop_condition",
                    "forbidden_regressions",
                    "requires_new_evidence",
                    "allowed_next_stage",
                    "blockers",
                }
            ),
            producer_stage="repair_plan",
            consumer_stages=frozenset({"generate_patch_proposal", "dashboard"}),
            allowed_statuses=statuses,
            dashboard_projection=(
                "message",
                "failure_source",
                "failure_class",
                "retry_budget_remaining",
            ),
        ),
        ArtifactContract(
            artifact_type="eval_report",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "execution_mode",
                    "workflow_completion_status",
                    "requested_behavior_status",
                    "verdict",
                    "claims_real_success",
                    "input_acceptance_status",
                    "input_acceptance_verified",
                    "acceptance_contract",
                    "v1_acceptance_status",
                    "v1_acceptance_blockers",
                }
            ),
            producer_stage="evaluation",
            consumer_stages=frozenset({"done", "dashboard"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"build_result"}),
            dashboard_projection=(
                "message",
                "workflow_completion_status",
                "requested_behavior_status",
            ),
        ),
        ArtifactContract(
            artifact_type="workflow_trace",
            schema_version="1.0",
            required_fields=frozenset({"node_name", "stage", "message"}),
            producer_stage="workflow",
            consumer_stages=frozenset({"dashboard", "eval"}),
            allowed_statuses=statuses,
            eval_visibility=True,
        ),
        ArtifactContract(
            artifact_type="workflow_checkpoint",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "checkpoint_id",
                    "run_id",
                    "feature_id",
                    "request_id",
                    "checkpoint_stage",
                    "status",
                    "state_snapshot",
                    "artifact_refs",
                    "artifact_hashes",
                    "resume_binding",
                    "resume_allowed_fields",
                    "interrupt_reason",
                    "checkpoint_policy",
                }
            ),
            producer_stage="checkpoint",
            consumer_stages=frozenset({"resume", "dashboard", "eval"}),
            allowed_statuses=statuses,
            dashboard_projection=(
                "message",
                "checkpoint_id",
                "checkpoint_stage",
                "status",
            ),
            eval_visibility=True,
        ),
        ArtifactContract(
            artifact_type="resume_report",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "resume_id",
                    "checkpoint_id",
                    "run_id",
                    "resume_stage",
                    "decision",
                    "status",
                    "allowed",
                    "reason",
                    "applied_updates",
                    "stale_reasons",
                    "blockers",
                }
            ),
            producer_stage="resume",
            consumer_stages=frozenset({"dashboard", "eval"}),
            allowed_statuses=statuses,
            required_upstream_artifacts=frozenset({"workflow_checkpoint"}),
            dashboard_projection=(
                "message",
                "resume_id",
                "resume_stage",
                "allowed",
            ),
            eval_visibility=True,
        ),
        ArtifactContract(
            artifact_type="job_status",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "job_id",
                    "job_type",
                    "status",
                    "created_at",
                    "started_at",
                    "finished_at",
                    "artifact_refs",
                    "trace_refs",
                    "error",
                }
            ),
            producer_stage="mcp_job",
            consumer_stages=frozenset({"dashboard", "eval", "mcp"}),
            allowed_statuses=statuses,
            dashboard_projection=(
                "message",
                "job_id",
                "job_type",
                "status",
                "artifact_refs",
                "budget_summary",
            ),
            eval_visibility=True,
        ),
        ArtifactContract(
            artifact_type="git_change_record",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "record_id",
                    "commit_sha",
                    "changed_files",
                    "replay_command",
                    "rollback_hint",
                }
            ),
            producer_stage="git_audit",
            consumer_stages=frozenset({"dashboard", "eval", "repair_plan"}),
            allowed_statuses=statuses,
            dashboard_projection=(
                "message",
                "commit_sha",
                "changed_files",
                "rollback_hint",
            ),
            eval_visibility=True,
        ),
        ArtifactContract(
            artifact_type="knowledge_index_report",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "source_id",
                    "total_files",
                    "indexed_files",
                    "skipped_files",
                    "failed_files",
                    "symbols_indexed",
                }
            ),
            producer_stage="knowledge_index",
            consumer_stages=frozenset({"retrieve_evidence", "dashboard", "eval"}),
            allowed_statuses=statuses,
            dashboard_projection=(
                "message",
                "source_id",
                "total_files",
                "indexed_files",
                "skipped_files",
                "symbols_indexed",
            ),
        ),
        ArtifactContract(
            artifact_type="workflow_summary",
            schema_version="1.0",
            required_fields=frozenset(
                {
                    "node_name",
                    "stage",
                    "message",
                    "execution_mode",
                    "workflow_completion_status",
                    "requested_behavior_status",
                    "final_status",
                    "claims_real_mod_success",
                    "claims_real_build_success",
                    "claims_real_runtime_success",
                    "v1_acceptance_status",
                    "v1_acceptance_blockers",
                }
            ),
            producer_stage="done",
            consumer_stages=frozenset({"dashboard", "eval"}),
            allowed_statuses=statuses,
            dashboard_projection=(
                "message",
                "workflow_completion_status",
                "requested_behavior_status",
            ),
        ),
        ArtifactContract(
            artifact_type="blocked_report",
            schema_version="1.0",
            required_fields=frozenset({"node_name", "stage", "message"}),
            producer_stage="blocked",
            consumer_stages=frozenset({"dashboard", "eval"}),
            allowed_statuses=statuses,
            dashboard_projection=("message",),
        ),
    ]
