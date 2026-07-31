from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.mod_agent.runtime.stagger_root_cause as module
from src.mod_agent.artifacts import ArtifactRef


FEATURE_ID = "feature_4f4c63c3802d"
BINDING_HASH = (
    "0786c8cf0618fc209662ec2d9c79cad5"
    "fa6a57c2401647035727548a03c03200"
)
PLAN_HASH = (
    "d18dfd13858b4820781198c05155a2b6"
    "59d171e7a257facd79d95f53fae4f619"
)
RUNTIME_HASH = (
    "3c1554faf998d491d2c09930a923334e"
    "c7bb4d4157301f4c2b99f13428646f33"
)
BUILD_HASH = (
    "215025bd406c09062e44297982a29d9a"
    "bde587b4ea04b4c0ebc26344a6b5040f"
)
FEATURE_HASH = (
    "bbd473ce1072b2f605afa9a3ef782269"
    "5249e4781f77ca810e6b61fcf3c8a190"
)
PATCH_HASH = "a" * 64


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _source() -> bytes:
    lines = ["// unchanged"] * 984
    lines[978:984] = [
        (
            "RectTransform? canvasRect = "
            "_lastHudParent as RectTransform;"
        ),
        "if (canvasRect == null)",
        "{",
        'reason = "missing_canvas_rect_for_stagger_x";',
        "return false;",
        "}",
    ]
    return "\n".join(lines).encode()


def _log() -> bytes:
    lines = ["noise"] * 620
    prefix = "feature_id=product_feature "
    lines[611] = prefix + (
        "signal=STAGGER_HUD_PARENT_DIAGNOSTIC "
        "phase=selection event_sequence=1 "
        "assignment_source=CanvasTrans "
        "selected.reference_null=false "
        "selected.unity_null=false "
        "selected.unity_instance_id=-18580 "
        "selected.runtime_type=UnityEngine.Transform "
        "selected.rect_transform_compatible=false"
    )
    lines[618] = prefix + (
        "signal=STAGGER_HUD_PARENT_DIAGNOSTIC "
        "phase=stagger_use event_sequence=2 "
        "assignment_seen=true "
        "crosshair_instance_changed=false "
        "hud_parent_identity_changed=false "
        "_lastHudParent.reference_null=false "
        "_lastHudParent.unity_null=false "
        "_lastHudParent.unity_instance_id=-18580 "
        "_lastHudParent.runtime_type=UnityEngine.Transform "
        "_lastHudParent.rect_transform_compatible=false "
        "last_assigned_HUD_parent.unity_instance_id=-18580 "
        "last_assignment_source=CanvasTrans"
    )
    lines[619] = prefix + (
        "signal=STAGGER_FEEDBACK_SKIPPED "
        "reaction_type=Light visual_spawned=False "
        "visual_reason=missing_canvas_rect_for_stagger_x "
        "audio_event_accepted=True playing_id=618"
    )
    return "\n".join(lines).encode()


def _lineage(
    product_dll: Path,
    source_hash: str,
) -> dict[str, dict[str, Any]]:
    binding = {
        "binding_id": "edit_binding_004",
        "canonical_target_path": (
            "Patches/HitFeedbackBehaviorPatch.cs"
        ),
        "target_symbol": module._SYMBOL,
        "target_span": {
            "start_line": 979,
            "end_line": 984,
        },
        "source_hash": source_hash,
    }
    change = {
        "change_id": "chg_004",
        "edit_binding_id": "edit_binding_004",
        "operation": (
            "replace_hud_recttransform_acquisition_"
            "and_null_guard_only"
        ),
    }
    target = {
        "binding_id": "edit_binding_004",
        "root_cause_status": "unresolved",
        "responsibility_anchors": {
            "source_hash": source_hash,
            "source_span": {
                "start_line": 979,
                "end_line": 984,
            },
        },
    }
    envelopes = {
        "feature_spec": {
            "data": {
                "acceptance_criteria": [
                    module._VISUAL_CRITERION
                ]
            }
        },
        "build_result": {
            "data": {
                "verified_artifacts": [
                    {
                        "path": (
                            "bin/Debug/"
                            "BetterHitFeedback.dll"
                        ),
                        "resolved_path": str(product_dll),
                        "sha256": _sha(
                            product_dll.read_bytes()
                        ),
                    }
                ]
            }
        },
        "implementation_plan": {
            "data": {
                "binding_registry": {
                    "edit_bindings": [binding]
                },
                "proposed_changes": [change],
            }
        },
        "patch_proposal": {"data": {}},
        "binding_resolution": {
            "data": {
                "allowed_edit_binding_ids": [
                    "edit_binding_004"
                ],
                "resolved_repair_target": target,
                "repair_planner_allowed": False,
                "source_patch_allowed": False,
            }
        },
        "runtime_evidence": {"data": {}},
    }
    hashes = {
        "feature_spec": FEATURE_HASH,
        "build_result": BUILD_HASH,
        "implementation_plan": PLAN_HASH,
        "patch_proposal": PATCH_HASH,
        "binding_resolution": BINDING_HASH,
        "runtime_evidence": RUNTIME_HASH,
    }
    return {
        role: {
            "envelope": envelope,
            "identity": {
                "artifact_type": role,
                "artifact_hash": hashes[role],
                "path": f"store/{role}.json",
            },
            "freshness": {
                "exact_revision_status": "fresh",
                "exact_revision_reasons": [],
                "recursive_status": (
                    "stale"
                    if role == "implementation_plan"
                    else "fresh"
                ),
                "recursive_reasons": (
                    ["evidence_pack hash changed"]
                    if role == "implementation_plan"
                    else []
                ),
                "latest_hash": hashes[role],
                "latest_match": True,
            },
        }
        for role, envelope in envelopes.items()
    }


def _inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    product_root = tmp_path / "product"
    product_dll = (
        product_root
        / "bin"
        / "Debug"
        / "BetterHitFeedback.dll"
    )
    product_source = (
        product_root
        / "Patches"
        / "HitFeedbackBehaviorPatch.cs"
    )
    product_dll.parent.mkdir(parents=True)
    product_source.parent.mkdir(parents=True)
    product_dll.write_bytes(b"product dll")
    source = _source()
    product_source.write_bytes(source)

    diagnostic_root = tmp_path / "diagnostic"
    diagnostic_dll = (
        diagnostic_root
        / "bin"
        / "Debug"
        / "BetterHitFeedback.dll"
    )
    diagnostic_source = (
        diagnostic_root
        / "Patches"
        / "HitFeedbackBehaviorPatch.cs"
    )
    diagnostic_dll.parent.mkdir(parents=True)
    diagnostic_source.parent.mkdir(parents=True)
    diagnostic_dll.write_bytes(b"diagnostic dll")
    diagnostic_source.write_bytes(
        source + b"\n// observation only"
    )
    diagnostic_config = (
        tmp_path / "general_enabled_true_diagnostic.cfg"
    )
    diagnostic_config.write_bytes(b"diagnostic config")

    run_dir = tmp_path / "run_002"
    run_dir.mkdir()
    screenshot = b"screenshot"
    restored_config = b"original config"
    (
        run_dir / "LogOutput.current_run.log"
    ).write_bytes(_log())
    (
        run_dir
        / "feature_4f4c63c3802d_gtfo_runtime.png"
    ).write_bytes(screenshot)
    (
        run_dir / "runtime_config_original.bin"
    ).write_bytes(restored_config)
    (run_dir / "process_stdout.log").write_bytes(b"")
    (run_dir / "process_stderr.log").write_bytes(b"")
    (run_dir / "RUN_SUMMARY.md").write_text(
        "derived summary",
        encoding="utf-8",
    )
    runtime_result = {
        "feature_id": FEATURE_ID,
        "run_id": None,
        "build_artifact_ref": None,
        "build_artifact_hash": None,
        "build_dll_sha256": _sha(
            diagnostic_dll.read_bytes()
        ),
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
            "source_sha256": _sha(
                diagnostic_dll.read_bytes()
            ),
        },
        "stagger_config_deployment_binding": {
            "source_path": str(diagnostic_config),
            "source_sha256": _sha(
                diagnostic_config.read_bytes()
            ),
        },
        "acceptance_contract": {
            "acceptance_criteria": [
                (
                    "Current-run Stagger HUD parent "
                    "diagnostic reached phase=stagger_use."
                )
            ]
        },
        "screenshot": {
            "content_hash": _sha(screenshot),
            "file_path": str(
                tmp_path / "run_001" / "old.png"
            ),
        },
        "runtime_trust_binding": {
            "checks": {
                "runtime_config_restoration": {
                    "destination_sha256_after_restore": (
                        _sha(restored_config)
                    )
                }
            }
        },
    }
    (
        run_dir / "runtime_result.json"
    ).write_text(
        json.dumps(runtime_result),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "_resolve_lineage",
        lambda store, feature_id, binding_hash: (
            _lineage(product_dll, _sha(source))
        ),
    )
    return {
        "artifact_store_root": tmp_path / "store",
        "feature_id": FEATURE_ID,
        "binding_resolution_hash": BINDING_HASH,
        "run_dir": run_dir,
    }


def test_semantic_ready_but_side_effect_admissions_blocked_and_hash_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    before = sorted(
        path.relative_to(tmp_path)
        for path in tmp_path.rglob("*")
    )

    first = module.preflight_stagger_run_002_root_cause(
        **inputs
    )
    second = module.preflight_stagger_run_002_root_cause(
        **inputs
    )

    after = sorted(
        path.relative_to(tmp_path)
        for path in tmp_path.rglob("*")
    )
    assert before == after
    assert first == second
    assert first["projection_hash"].startswith("sha256:")
    assert first["semantic_assessment"]["status"] == (
        "ready_for_non_authoritative_direct_mechanism_only"
    )
    assert (
        first["semantic_assessment"]["authoritative"]
        is False
    )
    assert (
        first["semantic_assessment"]["repair_selection_allowed"]
        is False
    )
    assert (
        first["materialization_admission"]["status"]
        == "blocked"
    )
    assert (
        first["planner_admission"]["status"]
        == "blocked"
    )
    assert first["materialization_admission"]["blockers"] == [
        "planning_authority_not_materialized"
    ]
    assert (
        "implementation_plan_recursive_stale"
        in first["materialization_admission"][
            "immutable_limitations"
        ]
    )
    evidence = first[
        "root_cause_evidence_projection"
    ]["evidence_items"][0]
    assert evidence["content_scope"] == (
        "current_run_bytes_after_prelaunch_boundary"
    )
    assert evidence["provenance_class"] == (
        "post_run_copy"
    )
    gaps = first[
        "root_cause_evidence_projection"
    ]["evidence_gaps"]
    assert [item["status"] for item in gaps] == [
        "missing",
        "missing",
    ]
    assert first["writes_performed"] is False
    assert first["artifact_writes_performed"] is False
    assert first["repair_planner_invoked"] is False


def test_projection_hash_changes_when_bound_run_content_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    first = module.preflight_stagger_run_002_root_cause(
        **inputs
    )
    summary = (
        Path(inputs["run_dir"]) / "RUN_SUMMARY.md"
    )
    summary.write_text(
        "derived summary revision",
        encoding="utf-8",
    )

    second = module.preflight_stagger_run_002_root_cause(
        **inputs
    )

    assert (
        first["projection_hash"]
        != second["projection_hash"]
    )


def test_rejects_runtime_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs(tmp_path, monkeypatch)
    log_path = (
        Path(inputs["run_dir"])
        / "LogOutput.current_run.log"
    )
    log_path.write_bytes(
        log_path.read_bytes().replace(
            b"hud_parent_identity_changed=false",
            b"hud_parent_identity_changed=true",
        )
    )

    with pytest.raises(
        module.StaggerRootCausePreflightError,
        match="Diagnostic record is not unique",
    ):
        module.preflight_stagger_run_002_root_cause(
            **inputs
        )


class _FakeStore:
    def __init__(
        self,
        envelopes: dict[str, dict[str, Any]],
    ) -> None:
        self.envelopes = envelopes
        self.refs = {
            role: ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type=role,
                path=f"store/{role}.json",
                artifact_hash=envelope["artifact_hash"],
            )
            for role, envelope in envelopes.items()
        }

    def list_feature_artifact_revisions(
        self,
        feature_id: str,
        artifact_type: str,
    ) -> list[ArtifactRef]:
        return [self.refs[artifact_type]]

    def list_feature_artifacts(
        self,
        feature_id: str,
    ) -> list[ArtifactRef]:
        return list(self.refs.values())

    def read(
        self,
        ref: ArtifactRef,
    ) -> dict[str, Any]:
        return self.envelopes[ref.artifact_type]

    def check_exact_revision_freshness(
        self,
        ref: ArtifactRef,
    ) -> Any:
        return SimpleNamespace(
            status="fresh",
            stale_reasons=[],
        )

    def check_freshness(
        self,
        ref: ArtifactRef,
    ) -> Any:
        return SimpleNamespace(
            status="fresh",
            stale_reasons=[],
        )


def test_resolves_registered_transitive_lineage() -> None:
    def ref(
        artifact_type: str,
        artifact_hash: str,
    ) -> dict[str, Any]:
        return {
            "artifact_type": artifact_type,
            "artifact_hash": artifact_hash,
            "feature_id": FEATURE_ID,
            "path": f"store/{artifact_type}.json",
            "require_latest": False,
        }

    envelopes = {
        "binding_resolution": {
            "artifact_hash": BINDING_HASH,
            "data": {
                "implementation_plan_revision": ref(
                    "implementation_plan",
                    PLAN_HASH,
                ),
                "runtime_evidence_revision": ref(
                    "runtime_evidence",
                    RUNTIME_HASH,
                ),
                "patch_proposal_revision": ref(
                    "patch_proposal",
                    PATCH_HASH,
                ),
            },
            "inputs": {
                "upstream_artifacts": [
                    ref(
                        "implementation_plan",
                        PLAN_HASH,
                    ),
                    ref(
                        "runtime_evidence",
                        RUNTIME_HASH,
                    ),
                    ref(
                        "patch_proposal",
                        PATCH_HASH,
                    ),
                ]
            },
        },
        "implementation_plan": {
            "artifact_hash": PLAN_HASH,
            "data": {},
            "inputs": {"upstream_artifacts": []},
        },
        "runtime_evidence": {
            "artifact_hash": RUNTIME_HASH,
            "data": {
                "build_artifact_hash": BUILD_HASH,
                "build_artifact_ref": ref(
                    "build_result",
                    BUILD_HASH,
                ),
            },
            "inputs": {
                "upstream_artifacts": [
                    ref("build_result", BUILD_HASH),
                    ref("feature_spec", FEATURE_HASH),
                ]
            },
        },
        "patch_proposal": {
            "artifact_hash": PATCH_HASH,
            "data": {},
            "inputs": {"upstream_artifacts": []},
        },
        "build_result": {
            "artifact_hash": BUILD_HASH,
            "data": {},
            "inputs": {"upstream_artifacts": []},
        },
        "feature_spec": {
            "artifact_hash": FEATURE_HASH,
            "data": {},
            "inputs": {"upstream_artifacts": []},
        },
    }

    result = module._resolve_lineage(
        _FakeStore(envelopes),
        FEATURE_ID,
        BINDING_HASH,
    )

    assert result["binding_resolution"]["identity"][
        "artifact_hash"
    ] == BINDING_HASH
    assert result["implementation_plan"]["identity"][
        "artifact_hash"
    ] == PLAN_HASH
    assert result["runtime_evidence"]["identity"][
        "artifact_hash"
    ] == RUNTIME_HASH
    assert result["patch_proposal"]["identity"][
        "artifact_hash"
    ] == PATCH_HASH
    assert result["build_result"]["identity"][
        "artifact_hash"
    ] == BUILD_HASH
    assert result["feature_spec"]["identity"][
        "artifact_hash"
    ] == FEATURE_HASH
