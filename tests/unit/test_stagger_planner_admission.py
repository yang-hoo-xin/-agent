from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactStore, ArtifactTypeRegistry
from src.mod_agent.repair import RepairPlanner
from src.mod_agent.runtime import stagger_planner_admission as module
from src.mod_agent.workflow import (
    WorkflowCheckpointStore,
    build_graph,
    create_initial_state,
)


FEATURE_ID = "feature_stagger"
PLANNING_RUN_ID = "stagger_repair_planning_001"
SYMBOL = (
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "TrySpawnStaggerYellowX"
)


def _revision(artifact_type: str, value: str) -> dict[str, str]:
    return {
        "feature_id": FEATURE_ID,
        "artifact_type": artifact_type,
        "path": f"C:/store/{artifact_type}_{value}.json",
        "artifact_hash": value * 64,
    }


def _hypotheses() -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_id": "H1",
            "statement": "A verified route exists inside the bound method.",
            "proposed_edit_location": SYMBOL,
            "supporting_evidence": ["The downcast is the direct failure."],
            "unverified_assumptions": ["The route has not been observed."],
            "binding_status": "requires_semantic_decision",
            "required_observation": "Inspect the exact object hierarchy.",
            "status": "unverified",
        },
        {
            "hypothesis_id": "H3",
            "statement": "The selector must return another object.",
            "proposed_edit_location": (
                "BetterHitFeedback.Patches."
                "HitFeedbackBehaviorPatch.TryGetLayerHudParent"
            ),
            "supporting_evidence": ["The selector returns CanvasTrans."],
            "unverified_assumptions": ["Another selector input is valid."],
            "binding_status": "outside_current_binding",
            "required_observation": "Inspect exact selector outputs.",
            "status": "unverified",
        },
    ]


def _preprojection() -> dict[str, Any]:
    lineage = {
        artifact_type: _revision(artifact_type, marker)
        for artifact_type, marker in (
            ("feature_spec", "a"),
            ("build_result", "b"),
            ("implementation_plan", "c"),
            ("patch_proposal", "d"),
            ("binding_resolution", "e"),
            ("runtime_evidence", "f"),
        )
    }
    return {
        "feature_id": FEATURE_ID,
        "projection_hash": "sha256:" + ("1" * 64),
        "formal_lineage": lineage,
        "freshness": {
            artifact_type: {
                "exact_revision_status": "fresh",
                "latest_match": True,
            }
            for artifact_type in lineage
        },
        "materialization_admission": {
            "status": "blocked",
            "blockers": ["planning_authority_not_materialized"],
        },
        "product_identity": {
            "source_path": "C:/product/Patches/HitFeedbackBehaviorPatch.cs",
            "source_sha256": "2" * 64,
            "build_dll_path": "C:/product/bin/Debug/BetterHitFeedback.dll",
            "build_dll_sha256": "3" * 64,
        },
        "diagnostic_identity": {
            "source_path": "C:/diagnostic/Patches/HitFeedbackBehaviorPatch.cs",
            "source_sha256": "4" * 64,
            "build_dll_path": "C:/diagnostic/bin/Debug/BetterHitFeedback.dll",
            "build_dll_sha256": "5" * 64,
            "config_path": "C:/diagnostic/diagnostic.cfg",
            "config_sha256": "6" * 64,
        },
        "runtime_result_identity": {
            "path": "C:/run_002/runtime_result.json",
            "sha256": "7" * 64,
            "run_id": None,
            "build_artifact_ref": None,
            "build_artifact_hash": None,
        },
        "binding_identity": {
            "binding_id": "edit_binding_004",
            "canonical_target_path": "Patches/HitFeedbackBehaviorPatch.cs",
            "target_symbol": SYMBOL,
            "target_span": {"start_line": 979, "end_line": 984},
            "source_hash": "2" * 64,
            "operation_owner": "proposed_changes.chg_004",
            "operation": (
                "replace_hud_recttransform_acquisition_"
                "and_null_guard_only"
            ),
            "root_cause_status": "unresolved",
        },
        "acceptance": {
            "failed_feature_spec_criterion": "yellow X is visible",
        },
        "semantic_assessment": {
            "status": (
                "ready_for_non_authoritative_direct_mechanism_only"
            ),
            "failure_owner": "product_behavior",
            "direct_failure_mechanism": "confirmed",
            "confirmed_mechanism": {
                "selected_parent_source": "CanvasTrans",
                "selected_parent_runtime_type": "UnityEngine.Transform",
                "selected_parent_rect_transform_compatible": False,
            },
            "excluded_for_observed_event": [
                "hud_parent_reference_null",
            ],
            "unresolved": [
                "correct_rect_transform_acquisition_path",
            ],
        },
        "root_cause_evidence_projection": {
            "evidence_items": [
                {
                    "evidence_id": "current_run_log",
                    "path": "C:/run_002/LogOutput.current_run.log",
                    "sha256": "8" * 64,
                    "content_scope": (
                        "current_run_bytes_after_prelaunch_boundary"
                    ),
                    "provenance_class": "post_run_copy",
                    "formal_runtime_evidence": False,
                }
            ],
            "evidence_gaps": [
                {
                    "expected_evidence_id": (
                        "run_001_previous_runtime_result"
                    ),
                    "status": "missing",
                    "reason": "wrapper_output_was_overwritten_before_preservation",
                    "recoverable": False,
                }
            ],
            "immutable_limitations": [
                "runtime_result_run_id_missing",
                "run_002_is_post_run_copy_not_formal_runtime_evidence",
            ],
        },
        "repair_hypothesis_set_projection": {
            "hypotheses": _hypotheses(),
        },
    }


def _binding_resolution() -> dict[str, Any]:
    return {
        "feature_id": FEATURE_ID,
        "result_type": "resolved_repair_target",
        "allowed_edit_binding_ids": ["edit_binding_004"],
        "resolved_repair_target": {
            "status": "resolved",
            "binding_id": "edit_binding_004",
            "canonical_target_path": (
                "Patches/HitFeedbackBehaviorPatch.cs"
            ),
            "responsibility_anchors": {
                "symbol": SYMBOL,
            },
        },
    }


def test_request_preprojection_is_deterministic_and_grants_no_authority(
    monkeypatch: Any,
) -> None:
    root = _preprojection()
    monkeypatch.setattr(
        module,
        "preflight_stagger_run_002_root_cause",
        lambda **kwargs: copy.deepcopy(root),
    )

    first = module.preproject_stagger_planning_authority(
        artifact_store_root=Path("C:/store"),
        feature_id=FEATURE_ID,
        binding_resolution_hash="e" * 64,
        run_dir=Path("C:/run_002"),
        planning_run_id=PLANNING_RUN_ID,
    )
    second = module.preproject_stagger_planning_authority(
        artifact_store_root=Path("C:/store"),
        feature_id=FEATURE_ID,
        binding_resolution_hash="e" * 64,
        run_dir=Path("C:/run_002"),
        planning_run_id=PLANNING_RUN_ID,
    )

    assert first == second
    assert first["request_hash"].startswith("sha256:")
    assert first["authority_granted"] is False
    assert first["artifact_materialization_allowed"] is False
    assert first["repair_planner_allowed"] is False
    assert first["writes_performed"] is False
    ArtifactTypeRegistry().validate_write(
        artifact_type="repair_planning_request",
        status="success",
        payload=first["request_artifact_payload"],
    )


def test_request_materialization_fits_deep_windows_store_root(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    root = _preprojection()
    monkeypatch.setattr(
        module,
        "preflight_stagger_run_002_root_cause",
        lambda **kwargs: copy.deepcopy(root),
    )
    projection = module.preproject_stagger_planning_authority(
        artifact_store_root=tmp_path / "unused",
        feature_id=FEATURE_ID,
        binding_resolution_hash="e" * 64,
        run_dir=tmp_path / "run_002",
        planning_run_id=PLANNING_RUN_ID,
    )
    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get("repair_planning_request"),
        required_upstream_artifacts=frozenset(),
        required_exact_revision_upstream_artifacts=frozenset(),
    )
    registry = ArtifactTypeRegistry(contracts=[request_contract])
    padding = "x" * max(1, 162 - len(str(tmp_path)) - 1)
    store_root = tmp_path / padding
    store = ArtifactStore(store_root, registry=registry)

    request_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="repair_planning_request",
        payload=projection["request_artifact_payload"],
    )

    assert Path(request_ref.path).is_file()
    assert len(request_ref.path) < 260


def test_generated_evidence_contracts_preserve_claim_boundaries() -> None:
    preprojection = _preprojection()
    root = module._root_cause_evidence_core(
        preprojection,
        planning_run_id=PLANNING_RUN_ID,
    )
    request_ref = _revision(
        "repair_planning_request",
        "9",
    )
    approval_ref = _revision(
        "repair_planning_approval",
        "a",
    )
    binding_ref = preprojection["formal_lineage"][
        "binding_resolution"
    ]
    root.update(
        {
            "repair_planning_authority_request_revision": request_ref,
            "repair_planning_authority_approval_revision": approval_ref,
            "binding_resolution_revision": binding_ref,
        }
    )
    hypothesis_set = module._repair_hypothesis_set_core(
        preprojection,
        planning_run_id=PLANNING_RUN_ID,
    )
    hypothesis_set.update(
        {
            "repair_planning_authority_approval_revision": approval_ref,
            "root_cause_evidence_revision": _revision(
                "root_cause_evidence",
                "b",
            ),
            "binding_resolution_revision": binding_ref,
        }
    )
    registry = ArtifactTypeRegistry()

    registry.validate_write(
        artifact_type="root_cause_evidence",
        status="success",
        payload=root,
    )
    registry.validate_write(
        artifact_type="repair_hypothesis_set",
        status="success",
        payload=hypothesis_set,
    )
    assert root["formal_runtime_evidence"] is False
    assert root["product_acceptance"] == "not_evaluated"
    assert root["audio_audibility"] == "not_evaluated"
    assert root["evidence_gaps"][0]["recoverable"] is False


def test_current_binding_accepts_latest_alias_for_exact_revision() -> None:
    exact_ref = module.ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="binding_resolution",
        path="C:/store/r/binding_resolution/exact.json",
        artifact_hash="e" * 64,
    )

    class Store:
        @staticmethod
        def list_feature_artifacts(feature_id: str) -> list[Any]:
            assert feature_id == FEATURE_ID
            return [
                module.ArtifactRef(
                    feature_id=FEATURE_ID,
                    artifact_type="binding_resolution",
                    path="C:/store/binding_resolution.json",
                    artifact_hash="e" * 64,
                )
            ]

    module._validate_current_binding_revision(
        store=Store(),
        feature_id=FEATURE_ID,
        binding_ref=exact_ref,
    )


def test_planner_returns_evidence_insufficient_without_selecting_a_fix() -> None:
    preprojection = _preprojection()
    root = module._root_cause_evidence_core(
        preprojection,
        planning_run_id=PLANNING_RUN_ID,
    )
    hypothesis_set = module._repair_hypothesis_set_core(
        preprojection,
        planning_run_id=PLANNING_RUN_ID,
    )

    decision = RepairPlanner.assess_stagger_semantic_decision(
        root_cause_evidence=root,
        repair_hypothesis_set=hypothesis_set,
        binding_resolution=_binding_resolution(),
    )
    plan = RepairPlanner().from_stagger_semantic_failure(
        root_cause_evidence=root,
        root_cause_evidence_ref="C:/store/root.json",
        repair_hypothesis_set=hypothesis_set,
        repair_hypothesis_set_ref="C:/store/hypotheses.json",
        binding_resolution=_binding_resolution(),
        binding_resolution_ref="C:/store/binding.json",
        retry_count=0,
    )

    assert decision.decision == "evidence_insufficient"
    assert decision.to_dict()["authority_granted"] is False
    assert plan.semantic_decision["decision"] == "evidence_insufficient"
    assert plan.minimal_changes == ()
    assert plan.allowed_next_stage is None
    assert plan.retry_count == 0


def test_planner_distinguishes_binding_gap_from_repair_ready() -> None:
    preprojection = _preprojection()
    root = module._root_cause_evidence_core(
        preprojection,
        planning_run_id=PLANNING_RUN_ID,
    )
    outside = module._repair_hypothesis_set_core(
        preprojection,
        planning_run_id=PLANNING_RUN_ID,
    )
    outside["hypotheses"][1]["status"] = "supported"

    outside_decision = RepairPlanner.assess_stagger_semantic_decision(
        root_cause_evidence=root,
        repair_hypothesis_set=outside,
        binding_resolution=_binding_resolution(),
    )

    inside = module._repair_hypothesis_set_core(
        preprojection,
        planning_run_id=PLANNING_RUN_ID,
    )
    inside["hypotheses"][0].update(
        {
            "status": "supported",
            "binding_status": "covered_by_current_binding",
            "proposed_operation": (
                "use_verified_rect_transform_route"
            ),
        }
    )
    ready_decision = RepairPlanner.assess_stagger_semantic_decision(
        root_cause_evidence=root,
        repair_hypothesis_set=inside,
        binding_resolution=_binding_resolution(),
    )

    assert outside_decision.decision == "binding_insufficient"
    assert ready_decision.decision == "repair_ready"
    assert ready_decision.blockers == ()


def test_graph_interrupt_binds_exact_request_before_materialization(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    from langgraph.types import Command

    root = _preprojection()
    monkeypatch.setattr(
        module,
        "preflight_stagger_run_002_root_cause",
        lambda **kwargs: copy.deepcopy(root),
    )
    projection = module.preproject_stagger_planning_authority(
        artifact_store_root=tmp_path / "unused",
        feature_id=FEATURE_ID,
        binding_resolution_hash="e" * 64,
        run_dir=tmp_path / "run_002",
        planning_run_id=PLANNING_RUN_ID,
    )
    default_registry = ArtifactTypeRegistry()
    request_contract = replace(
        default_registry.get(
            "repair_planning_request"
        ),
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
    request_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="repair_planning_request",
        payload=projection["request_artifact_payload"],
    )
    calls: list[dict[str, Any]] = []

    def materialize(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        revisions = {
            field_name: {
                "feature_id": FEATURE_ID,
                "artifact_type": artifact_type,
                "path": str(tmp_path / f"{artifact_type}.json"),
                "artifact_hash": marker * 64,
            }
            for artifact_type, field_name, marker in (
                (
                    "repair_planning_approval",
                    "repair_planning_authority_approval_revision",
                    "1",
                ),
                (
                    "root_cause_evidence",
                    "root_cause_evidence_revision",
                    "2",
                ),
                (
                    "repair_hypothesis_set",
                    "repair_hypothesis_set_revision",
                    "3",
                ),
                ("repair_plan", "repair_plan_revision", "4"),
            )
        }
        return {
            **revisions,
            "semantic_decision": {
                "decision": "evidence_insufficient",
                "blockers": [
                    {
                        "stage": "repair_plan",
                        "code": (
                            "STAGGER_RECT_TRANSFORM_SOURCE_UNRESOLVED"
                        ),
                        "message": "More bounded evidence is required.",
                    }
                ],
            },
        }

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph."
        "materialize_stagger_planning_approval",
        materialize,
    )
    graph = build_graph(
        store,
        repair_planning_authority_request_ref=request_ref,
        checkpointer=(
            WorkflowCheckpointStore.langgraph_memory_checkpointer()
        ),
    )
    config = {
        "configurable": {
            "thread_id": "stagger_repair_planning_graph_001"
        }
    }
    state = create_initial_state(
        run_id=PLANNING_RUN_ID,
        request_id=FEATURE_ID,
        user_request="Approve exact Stagger planning materialization.",
    )
    state["feature_id"] = FEATURE_ID

    interrupted = graph.invoke(state, config)

    assert "__interrupt__" in interrupted
    request = interrupted["__interrupt__"][0].value
    assert request["stage"] == "repair_planning_approval"
    assert (
        request["payload"]["request_hash"]
        == projection["request_hash"]
    )
    assert calls == []

    result = graph.invoke(
        Command(
            resume={
                "resume_id": "resume_stagger_repair_planning_001",
                "run_id": PLANNING_RUN_ID,
                "stage": "repair_planning_approval",
                "decision": "approve",
                "approved_by": "user",
                "approved_at": "2026-07-31T12:00:00+08:00",
                "artifact_refs": request["artifact_refs"],
                "authority_request_hash": projection["request_hash"],
            }
        ),
        config,
    )

    assert len(calls) == 1
    assert calls[0][
        "repair_planning_authority_request_hash"
    ] == request_ref.artifact_hash
    assert result["current_stage"] == "repair_plan"
    assert result["approvals"]["repair_planning"] is True
    assert result["artifacts"]["repair_plan"].endswith(
        "repair_plan.json"
    )
    assert any(
        blocker["code"]
        == "STAGGER_RECT_TRANSFORM_SOURCE_UNRESOLVED"
        for blocker in result["blockers"]
    )
