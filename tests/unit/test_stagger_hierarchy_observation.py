from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from src.mod_agent.runtime.stagger_hierarchy_observation import (
    StaggerHierarchyObservationError,
    merge_stagger_hierarchy_observation,
)
from src.mod_agent.runtime.stagger_root_cause import _hypotheses


FEATURE_ID = "feature_4f4c63c3802d"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _base(product_source: Path) -> dict[str, Any]:
    return {
        "schema_version": "base",
        "feature_id": FEATURE_ID,
        "projection_hash": "sha256:base",
        "product_identity": {
            "source_path": str(product_source),
        },
        "semantic_assessment": {
            "status": (
                "ready_for_non_authoritative_direct_mechanism_only"
            ),
            "authoritative": False,
            "scope": "direct_failure_mechanism_only",
            "repair_selection_allowed": False,
            "artifact_claim_allowed": False,
            "failure_owner": "product_behavior",
            "direct_failure_mechanism": "confirmed",
            "confirmed_mechanism": {},
            "unresolved": [
                "correct_rect_transform_acquisition_path",
                "edit_binding_004_scope_sufficiency",
            ],
        },
        "root_cause_evidence_projection": {
            "evidence_items": [],
            "immutable_limitations": [],
        },
        "repair_hypothesis_set_projection": {
            "hypotheses": _hypotheses(),
        },
        "materialization_admission": {
            "immutable_limitations": [],
        },
        "planner_admission": {
            "immutable_limitations": [],
        },
    }


def _hierarchy_line() -> bytes:
    return (
        "[Info] signal=STAGGER_HUD_PARENT_DIAGNOSTIC "
        "phase=stagger_use event_sequence=10 assignment_seen=true "
        "last_assignment_source=CanvasTrans "
        "hierarchy_observation_error=none "
        "rect_transform_route_found=true "
        "_lastHudParent.reference_null=false "
        "_lastHudParent.unity_null=false "
        "_lastHudParent.unity_instance_id=-18580 "
        "_lastHudParent.runtime_type=UnityEngine.Transform "
        "_lastHudParent.rect_transform_compatible=false "
        "_lastHudParent.parent.reference_null=false "
        "_lastHudParent.parent.unity_null=false "
        "_lastHudParent.parent.unity_instance_id=-6800 "
        "_lastHudParent.parent.runtime_type=UnityEngine.Transform "
        "_lastHudParent.parent.rect_transform_compatible=false "
        "_lastHudParent.GetComponentInParent<RectTransform>()"
        ".reference_null=false "
        "_lastHudParent.GetComponentInParent<RectTransform>()"
        ".unity_null=false "
        "_lastHudParent.GetComponentInParent<RectTransform>()"
        ".unity_instance_id=-18580 "
        "_lastHudParent.GetComponentInParent<RectTransform>()"
        ".runtime_type=UnityEngine.RectTransform "
        "_lastHudParent.GetComponentInParent<RectTransform>()"
        ".rect_transform_compatible=true "
        "_lastHudParent.GetComponentInParent<RectTransform>()"
        ".identity_read_error=none "
        "last_assigned_HUD_parent.unity_instance_id=-18580\n"
    ).encode()


def _inputs(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    product_source = (
        tmp_path
        / "product"
        / "BetterHitFeedback"
        / "Patches"
        / "HitFeedbackBehaviorPatch.cs"
    )
    product_source.parent.mkdir(parents=True)
    product_source.write_bytes(b"product")
    diagnostic_root = (
        tmp_path / "diagnostic" / "BetterHitFeedback"
    )
    diagnostic_source = (
        diagnostic_root / "Patches" / "HitFeedbackBehaviorPatch.cs"
    )
    diagnostic_dll = (
        diagnostic_root / "bin" / "Debug" / "BetterHitFeedback.dll"
    )
    diagnostic_source.parent.mkdir(parents=True)
    diagnostic_dll.parent.mkdir(parents=True)
    diagnostic_source.write_bytes(b"diagnostic source")
    diagnostic_dll.write_bytes(b"diagnostic dll")
    diagnostic_config = tmp_path / "diagnostic.cfg"
    diagnostic_config.write_bytes(b"diagnostic config")
    run = tmp_path / "runtime_output"
    (run / "process_diagnostics").mkdir(parents=True)
    (run / "runtime_config_backup").mkdir()
    (run / "runtime_captures").mkdir()
    truncated = b"limited output\n"
    full = b"startup\n" + _hierarchy_line() + b"shutdown\n"
    observed_size = len(full) - len(b"shutdown\n")
    (run / "LogOutput.current_run.log").write_bytes(truncated)
    (run / "LogOutput.post_run_full_copy.log").write_bytes(full)
    (run / "process_diagnostics" / "stdout.log").write_bytes(b"")
    (run / "process_diagnostics" / "stderr.log").write_bytes(b"")
    restored = b"restored config"
    (run / "runtime_config_backup" / "original.bin").write_bytes(
        restored
    )
    screenshot = run / "runtime_captures" / "runtime.png"
    screenshot.write_bytes(b"screenshot")
    runtime_result = {
        "feature_id": FEATURE_ID,
        "run_id": "hierarchy_run_003",
        "build_dll_sha256": _sha(diagnostic_dll.read_bytes()),
        "diagnostic_config_sha256": _sha(
            diagnostic_config.read_bytes()
        ),
        "diagnostic_scope": {
            "observation_only": True,
            "product_acceptance_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        "plugin_deployment_binding": {
            "source_path": str(diagnostic_dll),
            "expected_source_sha256": _sha(
                diagnostic_dll.read_bytes()
            ),
            "source_sha256": _sha(diagnostic_dll.read_bytes()),
        },
        "stagger_config_deployment_binding": {
            "source_path": str(diagnostic_config),
            "source_sha256": _sha(diagnostic_config.read_bytes()),
        },
        "screenshot": {
            "file_path": str(screenshot),
            "content_hash": _sha(screenshot.read_bytes()),
        },
        "diagnostic_run_identity": {
            "current_run_log_sha256": _sha(truncated),
        },
        "runtime_trust_binding": {
            "checks": {
                "game_directory_restoration": {"status": "passed"},
                "runtime_config_restoration": {
                    "status": "passed",
                    "destination_sha256_after_restore": _sha(restored),
                },
                "current_run_logs": {
                    "source_windows": [
                        {
                            "generation": 2,
                            "mode": (
                                "created_or_truncated_after_"
                                "prelaunch_boundary"
                            ),
                            "path": "GTFO.LogOutput.log",
                            "run_local_sha256": _sha(
                                full[:observed_size]
                            ),
                            "run_local_size_bytes": observed_size,
                            "run_local_start_byte": 0,
                            "status": "passed",
                        }
                    ]
                },
            }
        },
    }
    (run / "runtime_result.json").write_text(
        json.dumps(runtime_result),
        encoding="utf-8",
    )
    return _base(product_source), run


def test_real_route_selects_one_binding_covered_hypothesis(
    tmp_path: Path,
) -> None:
    base, run = _inputs(tmp_path)

    first = merge_stagger_hierarchy_observation(
        base_preprojection=base,
        hierarchy_run_dir=run,
    )
    second = merge_stagger_hierarchy_observation(
        base_preprojection=base,
        hierarchy_run_dir=run,
    )

    assert first == second
    assert first["projection_hash"].startswith("sha256:")
    assert first["semantic_assessment"]["status"] == (
        "ready_for_non_authoritative_repair_selection"
    )
    assert first["semantic_assessment"]["authoritative"] is False
    assert first["semantic_assessment"][
        "selected_rect_transform_acquisition_path"
    ] == "_lastHudParent.GetComponentInParent<RectTransform>()"
    supported = [
        item
        for item in first["repair_hypothesis_set_projection"][
            "hypotheses"
        ]
        if item["status"] == "supported"
    ]
    assert [item["hypothesis_id"] for item in supported] == ["H1"]
    assert first["repair_hypothesis_set_projection"][
        "selection_status"
    ] == "selected"
    assert supported[0]["binding_status"] == (
        "covered_by_current_binding"
    )
    assert first["writes_performed"] is False
    assert first["repair_planner_invoked"] is False


def test_rejects_post_run_copy_prefix_drift(tmp_path: Path) -> None:
    base, run = _inputs(tmp_path)
    full = run / "LogOutput.post_run_full_copy.log"
    full.write_bytes(b"drifted\n" + full.read_bytes())

    with pytest.raises(
        StaggerHierarchyObservationError,
        match="prefix drifted",
    ):
        merge_stagger_hierarchy_observation(
            base_preprojection=base,
            hierarchy_run_dir=run,
        )
