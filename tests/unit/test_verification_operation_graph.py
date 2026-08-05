from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.runtime_evidence_consolidation import (
    DELTA_SCHEMA_VERSION,
    FEATURE_ADAPTER,
    TARGET_SOURCE_LOGICAL_PATH,
    _FILE_ROLES,
    _STAGGER_C4_CRITERION,
    _STAGGER_C4_EVIDENCE_IDS,
)
from src.mod_agent.verification_operations import (
    EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
    EVIDENCE_CONSOLIDATION_KIND,
    RUNTIME_EXECUTION_CONTRACT_VERSION,
    RUNTIME_EXECUTION_KIND,
    RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
    RUNTIME_TERMINALIZATION_KIND,
    VERIFICATION_BUILD_CONTRACT_VERSION,
    VERIFICATION_BUILD_KIND,
    AcceptedResumeRecoveryAttemptV1,
    BuildInvocationProtocolBindingV1,
    EvidenceConsolidationOperationV1,
    ImplementationEvidenceFileBinding,
    InitialAttemptV1,
    NewRuntimeResumeProtocolBindingV1,
    ObservationRetryAttemptV1,
    RuntimeExecutionOperationV1,
    RuntimeTerminalizationOperationV1,
    VerificationAttemptPolicy,
    VerificationBuildOperationV1,
    VerificationCheckpointIdentityV1,
    VerificationOperationEnvelope,
    VerificationOperationSpec,
    VerificationProtocolBinding,
    project_verification_operation,
    resolve_verification_operation,
)
from src.mod_agent.workflow.graph import (
    _route_runtime_continuation_entry,
    _verification_graph_controls,
    build_graph,
)


FEATURE_ID = "feature_verification_operation_graph"


def _ref(root: Path, artifact_type: str, fill: str) -> ArtifactRef:
    return ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type=artifact_type,
        path=str((root / f"{artifact_type}_{fill}.json").resolve()),
        artifact_hash=fill * 64,
    )


def _runtime_checkpoint_identity() -> VerificationCheckpointIdentityV1:
    return VerificationCheckpointIdentityV1(
        checkpoint_id="checkpoint_graph_v1",
        run_id="run_graph_v1",
        request_id="request_graph_v1",
    )


def _consolidation_delta() -> dict[str, object]:
    criterion_hash = hashlib.sha256(
        _STAGGER_C4_CRITERION.encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": DELTA_SCHEMA_VERSION,
        "feature_adapter": FEATURE_ADAPTER,
        "criterion_id": f"sha256:{criterion_hash}",
        "acceptance_criterion": _STAGGER_C4_CRITERION,
        "before": {"outcome": "not_observed", "evidence_strength": "none"},
        "after": {
            "outcome": "true",
            "evidence_strength": "bound_implementation_evidence",
        },
        "evidence_ids": list(_STAGGER_C4_EVIDENCE_IDS),
        "file_roles": list(_FILE_ROLES),
        "evidence_level": "implementation",
        "new_build_performed": False,
        "new_runtime_performed": False,
        "product_source_modified": False,
    }


def _operation_envelopes(root: Path) -> dict[str, VerificationOperationEnvelope]:
    feature_ref = _ref(root, "feature_spec", "a")
    evidence_ref = _ref(root, "evidence_pack", "b")
    build_ref = _ref(root, "build_result", "c")
    checkpoint_ref = _ref(root, "workflow_checkpoint", "d")
    report_ref = _ref(root, "resume_report", "e")
    runtime_ref = _ref(root, "runtime_evidence", "f")
    repair_ref = _ref(root, "repair_plan", "1")
    checkpoint_identity = _runtime_checkpoint_identity()
    new_resume = NewRuntimeResumeProtocolBindingV1(
        checkpoint_ref=checkpoint_ref,
        resume_id="resume_graph_v1",
        approved_by="human",
    )
    accepted_resume = VerificationProtocolBinding(
        checkpoint_ref=checkpoint_ref,
        accepted_resume_report_ref=report_ref,
        resume_id="resume_graph_v1",
        approved_by="human",
    )

    def project(
        spec: VerificationOperationSpec,
        *,
        checkpoint_bound: bool,
    ) -> VerificationOperationEnvelope:
        return project_verification_operation(
            spec,
            checkpoint_identity=(checkpoint_identity if checkpoint_bound else None),
        )

    runtime_scope = {"runtime_profile_hash": "sha256:" + "2" * 64}
    bindings = (
        ImplementationEvidenceFileBinding(
            role="source_contract_report",
            absolute_path=str((root / "source_contract_report.json").resolve()),
            content_sha256="3" * 64,
        ),
        ImplementationEvidenceFileBinding(
            role="source_contract_report_repeat",
            absolute_path=str(
                (root / "source_contract_report_repeat.json").resolve()
            ),
            content_sha256="4" * 64,
        ),
        ImplementationEvidenceFileBinding(
            role="target_source",
            absolute_path=str((root / "HitFeedbackBehaviorPatch.cs").resolve()),
            content_sha256="5" * 64,
            logical_target_path=TARGET_SOURCE_LOGICAL_PATH,
        ),
    )
    return {
        "build": project(
            VerificationOperationSpec(
                operation_kind=VERIFICATION_BUILD_KIND,
                operation_contract_version=VERIFICATION_BUILD_CONTRACT_VERSION,
                attempt_policy=InitialAttemptV1(),
                protocol_binding=BuildInvocationProtocolBindingV1(
                    run_id="run_graph_v1",
                    request_id="request_graph_v1",
                ),
                variant_payload=VerificationBuildOperationV1(
                    feature_spec_ref=feature_ref,
                    evidence_pack_ref=evidence_ref,
                    user_request="Verify the existing implementation.",
                    target_domain="gtfo",
                    target_mod="BetterHitFeedback",
                ),
            ),
            checkpoint_bound=False,
        ),
        "runtime_evidence_only": project(
            VerificationOperationSpec(
                operation_kind=RUNTIME_EXECUTION_KIND,
                operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
                attempt_policy=InitialAttemptV1(),
                protocol_binding=new_resume,
                variant_payload=RuntimeExecutionOperationV1(
                    completion_scope="runtime_evidence_only",
                    runtime_action_scope=runtime_scope,
                ),
            ),
            checkpoint_bound=True,
        ),
        "runtime_workflow": project(
            VerificationOperationSpec(
                operation_kind=RUNTIME_EXECUTION_KIND,
                operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
                attempt_policy=InitialAttemptV1(),
                protocol_binding=new_resume,
                variant_payload=RuntimeExecutionOperationV1(
                    completion_scope="runtime_workflow",
                    runtime_action_scope=runtime_scope,
                ),
            ),
            checkpoint_bound=True,
        ),
        "runtime_retry": project(
            VerificationOperationSpec(
                operation_kind=RUNTIME_EXECUTION_KIND,
                operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
                attempt_policy=ObservationRetryAttemptV1(
                    prior_runtime_evidence_ref=runtime_ref,
                    repair_plan_ref=repair_ref,
                    retry_number=1,
                    retry_budget=2,
                    retry_budget_remaining=1,
                    current_attempt_approved_by="human",
                ),
                protocol_binding=accepted_resume,
                variant_payload=RuntimeExecutionOperationV1(
                    completion_scope="runtime_workflow",
                    runtime_action_scope=runtime_scope,
                ),
            ),
            checkpoint_bound=True,
        ),
        "runtime_recovery": project(
            VerificationOperationSpec(
                operation_kind=RUNTIME_EXECUTION_KIND,
                operation_contract_version=RUNTIME_EXECUTION_CONTRACT_VERSION,
                attempt_policy=AcceptedResumeRecoveryAttemptV1(
                    accepted_resume_report_ref=report_ref,
                    recovery_of_resume_id="resume_graph_v1",
                    current_attempt_approved_by="human",
                ),
                protocol_binding=accepted_resume,
                variant_payload=RuntimeExecutionOperationV1(
                    completion_scope="runtime_workflow",
                    runtime_action_scope=runtime_scope,
                ),
            ),
            checkpoint_bound=True,
        ),
        "terminal": project(
            VerificationOperationSpec(
                operation_kind=RUNTIME_TERMINALIZATION_KIND,
                operation_contract_version=RUNTIME_TERMINALIZATION_CONTRACT_VERSION,
                attempt_policy=InitialAttemptV1(),
                protocol_binding=accepted_resume,
                variant_payload=RuntimeTerminalizationOperationV1(
                    runtime_evidence_ref=runtime_ref,
                ),
            ),
            checkpoint_bound=True,
        ),
        "consolidation": project(
            VerificationOperationSpec(
                operation_kind=EVIDENCE_CONSOLIDATION_KIND,
                operation_contract_version=EVIDENCE_CONSOLIDATION_CONTRACT_VERSION,
                attempt_policy=VerificationAttemptPolicy(
                    attempt_budget=1,
                    retry_allowed=False,
                    recovery_allowed=False,
                ),
                protocol_binding=accepted_resume,
                variant_payload=EvidenceConsolidationOperationV1(
                    feature_spec_ref=feature_ref,
                    build_result_ref=build_ref,
                    prior_runtime_evidence_ref=runtime_ref,
                    evidence_pack_ref=evidence_ref,
                    canonical_delta=_consolidation_delta(),
                    execution_file_bindings=bindings,
                ),
            ),
            checkpoint_bound=False,
        ),
    }


def test_graph_api_has_no_legacy_c6_selector_parameters() -> None:
    parameters = set(inspect.signature(build_graph).parameters)
    assert parameters.isdisjoint(
        {
            "verification_only_continuation",
            "runtime_terminal_continuation",
            "runtime_continuation_checkpoint_id",
            "runtime_evidence_write_results",
            "runtime_terminal_write_results",
        }
    )
    assert {"stop_after_build", "interrupt_after"}.issubset(parameters)


def test_declarations_determine_all_seven_graph_control_shapes(tmp_path: Path) -> None:
    envelopes = _operation_envelopes(tmp_path)
    expected = {
        "build": (
            "verification_build",
            False,
            False,
            True,
            True,
            False,
        ),
        "runtime_evidence_only": (
            "runtime_execution",
            True,
            False,
            False,
            False,
            True,
        ),
        "runtime_workflow": (
            "runtime_execution",
            True,
            True,
            False,
            False,
            False,
        ),
        "runtime_retry": (
            "runtime_execution",
            True,
            True,
            False,
            False,
            False,
        ),
        "runtime_recovery": (
            "runtime_execution",
            True,
            True,
            False,
            False,
            False,
        ),
        "terminal": (
            "runtime_terminalization",
            False,
            True,
            False,
            False,
            False,
        ),
        "consolidation": (
            "runtime_evidence_consolidation",
            True,
            False,
            False,
            False,
            True,
        ),
    }
    for name, envelope in envelopes.items():
        controls = _verification_graph_controls(
            resolve_verification_operation(envelope)
        )
        assert (
            controls.handler,
            controls.runtime_evidence_store_results,
            controls.terminal_store_results,
            controls.stop_after_build,
            controls.persist_build_handoff,
            controls.stop_after_runtime_evidence,
        ) == expected[name]


def test_seven_shapes_compile_to_declaration_owned_routes(tmp_path: Path) -> None:
    envelopes = _operation_envelopes(tmp_path)
    expected_start_targets = {
        "build": {"verification_only_admission"},
        "runtime_evidence_only": {"collect_runtime_evidence"},
        "runtime_workflow": {"collect_runtime_evidence"},
        "runtime_retry": {"collect_runtime_evidence"},
        "runtime_recovery": {"collect_runtime_evidence"},
        "terminal": {"blocked", "evaluate"},
        "consolidation": {"collect_runtime_evidence"},
    }
    for name, envelope in envelopes.items():
        declaration = resolve_verification_operation(envelope)
        graph = build_graph(
            ArtifactStore(tmp_path / f"store_{name}"),
            verification_operation=envelope,
            build_result_factory=(
                (lambda _feature_id, _mode: None)
                if declaration.graph_handler == "verification_build"
                else None
            ),
            runtime_evidence_factory=(
                (lambda _feature_id, _build, _feature_spec: {})
                if declaration.graph_handler == "runtime_execution"
                else None
            ),
            use_default_proposal_git_binding=False,
        )
        graph_view = graph.get_graph()
        start_targets = {
            edge.target for edge in graph_view.edges if edge.source == "__start__"
        }
        assert start_targets == expected_start_targets[name]
        assert graph.interrupt_after_nodes == (
            ["collect_runtime_evidence"]
            if name in {"runtime_evidence_only", "consolidation"}
            else []
        )
        collect_targets = {
            edge.target
            for edge in graph_view.edges
            if edge.source == "collect_runtime_evidence"
        }
        if name in {"runtime_evidence_only", "consolidation"}:
            assert collect_targets == {"__end__"}
        elif name in {"runtime_workflow", "runtime_retry", "runtime_recovery"}:
            assert "evaluate" in collect_targets


@pytest.mark.parametrize(
    "generic_override",
    [
        {"stop_after_build": True},
        {"interrupt_after": ["collect_runtime_evidence"]},
        {"allow_game_launch": True},
    ],
)
def test_typed_operation_rejects_generic_route_authority(
    tmp_path: Path,
    generic_override: dict[str, object],
) -> None:
    operation = _operation_envelopes(tmp_path)["runtime_evidence_only"]
    with pytest.raises(ValueError, match="come from its declaration"):
        build_graph(
            ArtifactStore(tmp_path / "store_override"),
            verification_operation=operation,
            runtime_evidence_factory=lambda _feature_id, _build, _feature_spec: {},
            use_default_proposal_git_binding=False,
            **generic_override,
        )


def test_runtime_entry_uses_typed_exact_checkpoint_ref(tmp_path: Path) -> None:
    operation = _operation_envelopes(tmp_path)["runtime_evidence_only"]
    protocol = operation.protocol_binding
    state = {
        "current_stage": "build",
        "next_stage": "runtime_evidence",
        "blockers": [],
        "run_id": "run_graph_v1",
        "request_id": "request_graph_v1",
        "feature_id": FEATURE_ID,
        "artifacts": {
            "workflow_checkpoint": str(
                (tmp_path / "different_checkpoint_revision.json").resolve()
            ),
            "resume_report": str((tmp_path / "resume_report.json").resolve()),
            "feature_spec": str((tmp_path / "feature_spec.json").resolve()),
            "build_result": str((tmp_path / "build_result.json").resolve()),
        },
        "artifact_hashes": {
            "workflow_checkpoint": protocol.checkpoint_ref.artifact_hash,
            "resume_report": "e" * 64,
            "feature_spec": "a" * 64,
            "build_result": "c" * 64,
        },
    }
    with pytest.raises(ValueError, match="approved checkpoint ref"):
        _route_runtime_continuation_entry(
            state,
            ArtifactStore(tmp_path / "store_checkpoint_drift"),
            operation,
        )


def test_generic_non_c6_graph_controls_remain_available(tmp_path: Path) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "store_generic"),
        stop_after_build=True,
        interrupt_after=["build"],
        use_default_proposal_git_binding=False,
    )
    assert graph.interrupt_after_nodes == ["build"]
    start_targets = {
        edge.target for edge in graph.get_graph().edges if edge.source == "__start__"
    }
    assert start_targets == {"plan_request"}
