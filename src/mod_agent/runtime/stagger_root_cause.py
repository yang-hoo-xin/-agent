"""Read-only Stagger run_002 root-cause preprojection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from ..artifacts import ArtifactStore


_VISUAL_CRITERION = (
    "With General.Enabled=true, a locally owned player's weapon hit that actually "
    "produces the selected enemy reaction shows one additional short-lived yellow X "
    "at that hit position."
)
_SYMBOL = (
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "TrySpawnStaggerYellowX"
)
_SOURCE_BLOCK = (
    "RectTransform? canvasRect = _lastHudParent as RectTransform;",
    "if (canvasRect == null)",
    "{",
    'reason = "missing_canvas_rect_for_stagger_x";',
    "return false;",
    "}",
)
_RUN_FILES = {
    "current_run_log": "LogOutput.current_run.log",
    "runtime_result": "runtime_result.json",
    "screenshot": "feature_4f4c63c3802d_gtfo_runtime.png",
    "restored_config_backup": "runtime_config_original.bin",
    "process_stdout": "process_stdout.log",
    "process_stderr": "process_stderr.log",
    "run_summary": "RUN_SUMMARY.md",
}


class StaggerRootCausePreflightError(ValueError):
    """Raised when the selected Stagger identities do not match."""


def preflight_stagger_run_002_root_cause(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    binding_resolution_hash: str,
    run_dir: str | Path,
) -> dict[str, Any]:
    """Resolve Store lineage and return a deterministic no-write projection."""

    store = ArtifactStore(artifact_store_root)
    lineage = _resolve_lineage(store, feature_id, binding_resolution_hash)
    feature = lineage["feature_spec"]["envelope"]["data"]
    build = lineage["build_result"]["envelope"]["data"]
    plan = lineage["implementation_plan"]["envelope"]["data"]
    resolution = lineage["binding_resolution"]["envelope"]["data"]

    criteria = feature["acceptance_criteria"]
    _expect(
        isinstance(criteria, list) and criteria.count(_VISUAL_CRITERION) == 1,
        "The exact yellow-X criterion is not unique in FeatureSpec.",
    )
    binding = _one(
        plan["binding_registry"]["edit_bindings"],
        "binding_id",
        "edit_binding_004",
    )
    change = _one(
        plan["proposed_changes"],
        "edit_binding_id",
        "edit_binding_004",
    )
    target = resolution["resolved_repair_target"]
    binding_identity = _binding_identity(binding, change, target, resolution)

    build_artifact = _one(
        build["verified_artifacts"],
        "path",
        "bin/Debug/BetterHitFeedback.dll",
    )
    product_dll = Path(build_artifact["resolved_path"]).resolve()
    product_dll_hash = _file_hash(product_dll)
    _expect(
        product_dll_hash == build_artifact["sha256"].upper(),
        "Build DLL drifted.",
    )
    product_root = _project_root(product_dll, build_artifact["path"])
    product_source = (
        product_root
        / Path(
            *PurePosixPath(
                binding_identity["canonical_target_path"]
            ).parts
        )
    ).resolve()
    source_bytes = product_source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest().upper()
    _expect(
        source_hash == binding_identity["source_hash"],
        "Product source drifted.",
    )
    _validate_source(source_bytes, binding_identity["target_span"])

    resolved_run_dir = Path(run_dir).resolve()
    paths = {
        evidence_id: (resolved_run_dir / filename).resolve()
        for evidence_id, filename in _RUN_FILES.items()
    }
    _expect(
        all(path.is_file() for path in paths.values()),
        "run_002 files missing.",
    )
    runtime_bytes = paths["runtime_result"].read_bytes()
    runtime_result = json.loads(runtime_bytes.decode("utf-8-sig"))
    _expect(
        runtime_result["feature_id"] == feature_id,
        "runtime_result feature drifted.",
    )
    scope = runtime_result["diagnostic_scope"]
    _expect(
        scope["observation_only"] is True
        and scope["product_acceptance_allowed"] is False
        and scope["repair_planner_allowed"] is False
        and scope["source_patch_allowed"] is False,
        "runtime_result diagnostic scope drifted.",
    )

    deployment = runtime_result["plugin_deployment_binding"]
    diagnostic_dll = Path(deployment["source_path"]).resolve()
    diagnostic_dll_hash = _file_hash(diagnostic_dll)
    _expect(
        {
            deployment["expected_source_sha256"].upper(),
            deployment["source_sha256"].upper(),
            runtime_result["build_dll_sha256"].upper(),
        }
        == {diagnostic_dll_hash},
        "Diagnostic DLL identity drifted.",
    )
    diagnostic_root = _project_root(
        diagnostic_dll,
        build_artifact["path"],
    )
    diagnostic_source = (
        diagnostic_root
        / Path(
            *PurePosixPath(
                binding_identity["canonical_target_path"]
            ).parts
        )
    ).resolve()
    diagnostic_config = Path(
        runtime_result["stagger_config_deployment_binding"]["source_path"]
    ).resolve()
    diagnostic_config_hash = _file_hash(diagnostic_config)
    _expect(
        diagnostic_config_hash
        == runtime_result["diagnostic_config_sha256"].upper()
        == runtime_result["stagger_config_deployment_binding"][
            "source_sha256"
        ].upper(),
        "Diagnostic config identity drifted.",
    )

    evidence_items = _evidence_items(paths, runtime_result)
    mechanism = _mechanism(
        paths["current_run_log"].read_bytes(),
        binding_identity["target_span"],
    )
    freshness_blockers = _freshness_blockers(lineage)
    lineage_blockers = _run_lineage_blockers(
        runtime_result,
        product_dll_hash=product_dll_hash,
        diagnostic_dll_hash=diagnostic_dll_hash,
    )
    immutable_limitations = [
        *freshness_blockers,
        *lineage_blockers,
    ]

    projection = {
        "schema_version": "stagger_run_002_root_cause_preprojection_v1",
        "projection_status": "complete",
        "feature_id": feature_id,
        "formal_lineage": {
            role: lineage[role]["identity"] for role in lineage
        },
        "freshness": {
            role: lineage[role]["freshness"] for role in lineage
        },
        "product_identity": {
            "source_path": str(product_source),
            "source_sha256": source_hash,
            "build_dll_path": str(product_dll),
            "build_dll_sha256": product_dll_hash,
        },
        "diagnostic_identity": {
            "source_path": str(diagnostic_source),
            "source_sha256": _file_hash(diagnostic_source),
            "build_dll_path": str(diagnostic_dll),
            "build_dll_sha256": diagnostic_dll_hash,
            "config_path": str(diagnostic_config),
            "config_sha256": diagnostic_config_hash,
        },
        "runtime_result_identity": {
            "path": str(paths["runtime_result"]),
            "sha256": hashlib.sha256(runtime_bytes).hexdigest().upper(),
            "run_id": runtime_result.get("run_id"),
            "build_artifact_ref": runtime_result.get("build_artifact_ref"),
            "build_artifact_hash": runtime_result.get("build_artifact_hash"),
        },
        "binding_identity": binding_identity,
        "acceptance": {
            "failed_feature_spec_criterion": _VISUAL_CRITERION,
            "runtime_diagnostic_criteria": runtime_result[
                "acceptance_contract"
            ]["acceptance_criteria"],
            "product_acceptance": "not_evaluated",
        },
        "semantic_assessment": {
            "status": "ready_for_non_authoritative_direct_mechanism_only",
            "authoritative": False,
            "scope": "direct_failure_mechanism_only",
            "repair_selection_allowed": False,
            "artifact_claim_allowed": False,
            "failure_owner": "product_behavior",
            "direct_failure_mechanism": "confirmed",
            "confirmed_mechanism": mechanism,
            "excluded_for_observed_event": [
                "hud_parent_reference_null",
                "hud_parent_unity_destroyed_null",
                "hud_parent_identity_changed",
                "crosshair_instance_changed",
            ],
            "unresolved": [
                "correct_rect_transform_acquisition_path",
                "edit_binding_004_scope_sufficiency",
            ],
            "audio_audibility": "not_evaluated",
            "yellow_x_repaired": False,
        },
        "root_cause_evidence_projection": {
            "materialized": False,
            "evidence_items": evidence_items,
            "evidence_gaps": _evidence_gaps(
                resolved_run_dir,
                runtime_result,
            ),
            "immutable_limitations": immutable_limitations,
        },
        "repair_hypothesis_set_projection": {
            "materialized": False,
            "hypotheses": _hypotheses(),
        },
        "materialization_admission": {
            "status": "blocked",
            "blockers": [
                "planning_authority_not_materialized",
            ],
            "immutable_limitations": immutable_limitations,
        },
        "planner_admission": {
            "status": "blocked",
            "allowed_semantic_decisions_after_admission": [
                "repair_ready",
                "evidence_insufficient",
                "binding_insufficient",
            ],
            "blockers": [
                "materialization_admission_blocked",
                "planning_authority_not_materialized",
                "root_cause_evidence_not_materialized",
                "repair_hypothesis_set_not_materialized",
            ],
            "immutable_limitations": immutable_limitations,
        },
        "authority": {
            "artifact_creation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
            "build_allowed": False,
            "runtime_allowed": False,
        },
        "writes_performed": False,
        "artifact_writes_performed": False,
        "repair_planner_invoked": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }
    return {
        **projection,
        "projection_hash": (
            "sha256:"
            + hashlib.sha256(
                _canonical_json(projection)
            ).hexdigest()
        ),
    }


def _resolve_lineage(
    store: ArtifactStore,
    feature_id: str,
    binding_hash: str,
) -> dict[str, dict[str, Any]]:
    resolution = _load(
        store,
        feature_id,
        "binding_resolution",
        binding_hash,
    )
    data = resolution["envelope"]["data"]
    plan_hash = data["implementation_plan_revision"]["artifact_hash"]
    runtime_hash = data["runtime_evidence_revision"]["artifact_hash"]
    patch_hash = data["patch_proposal_revision"]["artifact_hash"]
    plan = _load(
        store,
        feature_id,
        "implementation_plan",
        plan_hash,
    )
    runtime = _load(
        store,
        feature_id,
        "runtime_evidence",
        runtime_hash,
    )
    runtime_data = runtime["envelope"]["data"]
    build_hash = runtime_data["build_artifact_ref"]["artifact_hash"]
    _expect(
        runtime_data["build_artifact_hash"] == build_hash,
        "Build link drifted.",
    )
    feature_link = _one(
        runtime["envelope"]["inputs"]["upstream_artifacts"],
        "artifact_type",
        "feature_spec",
    )
    _require_upstream(
        resolution["envelope"],
        "implementation_plan",
        plan_hash,
    )
    _require_upstream(
        resolution["envelope"],
        "runtime_evidence",
        runtime_hash,
    )
    _require_upstream(
        resolution["envelope"],
        "patch_proposal",
        patch_hash,
    )
    _require_upstream(
        runtime["envelope"],
        "build_result",
        build_hash,
    )
    return {
        "feature_spec": _load(
            store,
            feature_id,
            "feature_spec",
            feature_link["artifact_hash"],
        ),
        "build_result": _load(
            store,
            feature_id,
            "build_result",
            build_hash,
        ),
        "implementation_plan": plan,
        "patch_proposal": _load(
            store,
            feature_id,
            "patch_proposal",
            patch_hash,
        ),
        "binding_resolution": resolution,
        "runtime_evidence": runtime,
    }


def _load(
    store: ArtifactStore,
    feature_id: str,
    artifact_type: str,
    artifact_hash: str,
) -> dict[str, Any]:
    matches = [
        ref
        for ref in store.list_feature_artifact_revisions(
            feature_id,
            artifact_type,
        )
        if ref.artifact_hash == artifact_hash
    ]
    _expect(
        len(matches) == 1,
        f"{artifact_type} revision is not unique.",
    )
    ref = matches[0]
    envelope = store.read(ref)
    latest = {
        item.artifact_type: item
        for item in store.list_feature_artifacts(feature_id)
    }.get(artifact_type)
    exact = store.check_exact_revision_freshness(ref)
    recursive = store.check_freshness(ref)
    return {
        "envelope": envelope,
        "identity": {
            "artifact_type": artifact_type,
            "artifact_hash": artifact_hash,
            "path": ref.path,
        },
        "freshness": {
            "exact_revision_status": exact.status,
            "exact_revision_reasons": list(exact.stale_reasons),
            "recursive_status": recursive.status,
            "recursive_reasons": list(recursive.stale_reasons),
            "latest_hash": (
                None if latest is None else latest.artifact_hash
            ),
            "latest_match": (
                latest is not None
                and latest.artifact_hash == artifact_hash
            ),
        },
    }


def _binding_identity(
    binding: dict[str, Any],
    change: dict[str, Any],
    target: dict[str, Any],
    resolution: dict[str, Any],
) -> dict[str, Any]:
    identity = {
        "binding_id": binding["binding_id"],
        "canonical_target_path": binding["canonical_target_path"],
        "target_symbol": binding["target_symbol"],
        "target_span": binding["target_span"],
        "source_hash": binding["source_hash"].upper(),
        "operation_owner": f"proposed_changes.{change['change_id']}",
        "operation": change["operation"],
        "root_cause_status": target["root_cause_status"],
    }
    expected_non_hash = {
        "binding_id": "edit_binding_004",
        "canonical_target_path": "Patches/HitFeedbackBehaviorPatch.cs",
        "target_symbol": _SYMBOL,
        "target_span": {"start_line": 979, "end_line": 984},
        "operation_owner": "proposed_changes.chg_004",
        "operation": "replace_hud_recttransform_acquisition_and_null_guard_only",
        "root_cause_status": "unresolved",
    }
    _expect(
        {
            key: value
            for key, value in identity.items()
            if key != "source_hash"
        }
        == expected_non_hash,
        "Binding or chg_004 identity drifted.",
    )
    _expect(
        resolution["allowed_edit_binding_ids"] == ["edit_binding_004"]
        and target["binding_id"] == "edit_binding_004"
        and target["responsibility_anchors"]["source_hash"].upper()
        == identity["source_hash"]
        and target["responsibility_anchors"]["source_span"]
        == identity["target_span"]
        and resolution["repair_planner_allowed"] is False
        and resolution["source_patch_allowed"] is False,
        "BindingResolution authority drifted.",
    )
    return identity


def _evidence_items(
    paths: dict[str, Path],
    runtime_result: dict[str, Any],
) -> list[dict[str, Any]]:
    _expect(
        runtime_result["screenshot"]["content_hash"].upper()
        == _file_hash(paths["screenshot"]),
        "Screenshot identity drifted.",
    )
    restored_hash = runtime_result[
        "runtime_trust_binding"
    ]["checks"]["runtime_config_restoration"][
        "destination_sha256_after_restore"
    ].upper()
    _expect(
        restored_hash == _file_hash(paths["restored_config_backup"]),
        "Restored config identity drifted.",
    )
    scopes = {
        "current_run_log": "current_run_bytes_after_prelaunch_boundary",
        "runtime_result": "diagnostic_result_payload",
        "screenshot": "diagnostic_screen_capture",
        "restored_config_backup": "pre_run_config_restoration_bytes",
        "process_stdout": "diagnostic_process_stdout",
        "process_stderr": "diagnostic_process_stderr",
        "run_summary": "derived_run_summary",
    }
    return [
        {
            "evidence_id": evidence_id,
            "path": str(paths[evidence_id]),
            "sha256": _file_hash(paths[evidence_id]),
            "content_scope": scopes[evidence_id],
            "provenance_class": (
                "derived_summary"
                if evidence_id == "run_summary"
                else "post_run_copy"
            ),
            "formal_runtime_evidence": False,
        }
        for evidence_id in _RUN_FILES
    ]


def _evidence_gaps(
    run_dir: Path,
    runtime_result: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "expected_evidence_id": "run_001_previous_runtime_result",
            "expected_path": str(
                run_dir.parent / "run_001" / "runtime_result.json"
            ),
            "status": "missing",
            "reason": "wrapper_output_was_overwritten_before_preservation",
            "recoverable": False,
        },
        {
            "expected_evidence_id": "run_001_previous_screenshot",
            "expected_path": runtime_result["screenshot"]["file_path"],
            "status": "missing",
            "reason": "wrapper_output_was_overwritten_before_preservation",
            "recoverable": False,
        },
    ]


def _mechanism(
    log_bytes: bytes,
    span: dict[str, int],
) -> dict[str, Any]:
    lines = log_bytes.decode("utf-8-sig").splitlines()
    selection_line, selection = _record(
        lines,
        (
            "signal=STAGGER_HUD_PARENT_DIAGNOSTIC",
            "phase=selection",
            "event_sequence=1",
            "assignment_source=CanvasTrans",
            "selected.reference_null=false",
            "selected.unity_null=false",
            "selected.runtime_type=UnityEngine.Transform",
            "selected.rect_transform_compatible=false",
        ),
    )
    use_line, use = _record(
        lines,
        (
            "signal=STAGGER_HUD_PARENT_DIAGNOSTIC",
            "phase=stagger_use",
            "event_sequence=2",
            "assignment_seen=true",
            "crosshair_instance_changed=false",
            "hud_parent_identity_changed=false",
            "_lastHudParent.reference_null=false",
            "_lastHudParent.unity_null=false",
            "_lastHudParent.runtime_type=UnityEngine.Transform",
            "_lastHudParent.rect_transform_compatible=false",
            "last_assignment_source=CanvasTrans",
        ),
    )
    skipped_line, skipped = _record(
        lines,
        (
            "signal=STAGGER_FEEDBACK_SKIPPED",
            "reaction_type=Light",
            "visual_spawned=False",
            "visual_reason=missing_canvas_rect_for_stagger_x",
            "audio_event_accepted=True",
        ),
    )
    selected_id = selection["selected.unity_instance_id"]
    _expect(
        selection_line < use_line < skipped_line,
        "Diagnostic order drifted.",
    )
    _expect(
        {
            use["_lastHudParent.unity_instance_id"],
            use["last_assigned_HUD_parent.unity_instance_id"],
        }
        == {selected_id},
        "HUD parent identity drifted.",
    )
    marker_ids = {
        selection["feature_id"],
        use["feature_id"],
        skipped["feature_id"],
    }
    _expect(
        len(marker_ids) == 1,
        "Runtime marker feature ids differ.",
    )
    playing_id = int(skipped["playing_id"])
    _expect(
        playing_id != 0,
        "Accepted audio playing id is zero.",
    )
    return {
        "selected_parent_source": "CanvasTrans",
        "selected_parent_runtime_type": "UnityEngine.Transform",
        "selected_parent_rect_transform_compatible": False,
        "selected_unity_instance_id": selected_id,
        "runtime_marker_feature_id": marker_ids.pop(),
        "source_symbol": _SYMBOL,
        "source_expression": "_lastHudParent as RectTransform",
        "early_return_reason": "missing_canvas_rect_for_stagger_x",
        "reaction_type": "Light",
        "audio_event_accepted": True,
        "playing_id": playing_id,
        "evidence_line_numbers": {
            "selection": selection_line,
            "stagger_use": use_line,
            "visual_skip": skipped_line,
            "source_downcast": span["start_line"],
            "source_early_return_end": span["end_line"],
        },
    }


def _freshness_blockers(
    lineage: dict[str, dict[str, Any]],
) -> list[str]:
    blockers = [
        f"{role}_{kind}_stale"
        for role, item in lineage.items()
        for kind, status in (
            (
                "exact_revision",
                item["freshness"]["exact_revision_status"],
            ),
            (
                "recursive",
                item["freshness"]["recursive_status"],
            ),
        )
        if status != "fresh"
    ]
    blockers.extend(
        f"{role}_not_latest"
        for role, item in lineage.items()
        if not item["freshness"]["latest_match"]
    )
    return blockers


def _run_lineage_blockers(
    runtime_result: dict[str, Any],
    *,
    product_dll_hash: str,
    diagnostic_dll_hash: str,
) -> list[str]:
    blockers = [
        name
        for name, value in (
            (
                "runtime_result_run_id_missing",
                runtime_result.get("run_id"),
            ),
            (
                "runtime_result_build_artifact_ref_missing",
                runtime_result.get("build_artifact_ref"),
            ),
            (
                "runtime_result_build_artifact_hash_missing",
                runtime_result.get("build_artifact_hash"),
            ),
        )
        if value is None
    ]
    if product_dll_hash != diagnostic_dll_hash:
        blockers.append(
            "diagnostic_dll_not_formally_linked_to_product_build_result"
        )
    blockers.append(
        "run_002_is_post_run_copy_not_formal_runtime_evidence"
    )
    return blockers


def _hypotheses() -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_id": "H1",
            "statement": (
                "A RectTransform is reachable from CanvasTrans "
                "without changing its selector."
            ),
            "proposed_edit_location": _SYMBOL,
            "supporting_evidence": [
                "CanvasTrans is stable and is UnityEngine.Transform.",
            ],
            "unverified_assumptions": [
                "A compatible RectTransform is reachable from CanvasTrans.",
            ],
            "binding_status": "requires_semantic_decision",
            "required_observation": (
                "Read the concrete CanvasTrans hierarchy and component types."
            ),
            "status": "unverified",
        },
        {
            "hypothesis_id": "H2",
            "statement": (
                "CrosshairGuiLayer exposes another "
                "RectTransform-compatible UI root."
            ),
            "proposed_edit_location": "unresolved",
            "supporting_evidence": [],
            "unverified_assumptions": [
                "CrosshairGuiLayer exposes a distinct UI root member.",
            ],
            "binding_status": "requires_exact_member_evidence",
            "required_observation": (
                "Inspect exact CrosshairGuiLayer members from current metadata."
            ),
            "status": "unverified",
        },
        {
            "hypothesis_id": "H3",
            "statement": (
                "TryGetLayerHudParent must select "
                "a different UI object."
            ),
            "proposed_edit_location": (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                "TryGetLayerHudParent"
            ),
            "supporting_evidence": [
                "The current selector returns CanvasTrans.",
            ],
            "unverified_assumptions": [
                "A different object should be selected before Stagger use.",
            ],
            "binding_status": "outside_current_binding",
            "required_observation": (
                "Compare exact selector sources and their runtime component types."
            ),
            "status": "unverified",
        },
        {
            "hypothesis_id": "H4",
            "statement": (
                "CanvasTrans exposes another verified route "
                "to a compatible UI object."
            ),
            "proposed_edit_location": _SYMBOL,
            "supporting_evidence": [
                "The current failure occurs only at the RectTransform downcast.",
            ],
            "unverified_assumptions": [
                "A verified member or parent path yields RectTransform.",
            ],
            "binding_status": "requires_semantic_decision",
            "required_observation": (
                "Inspect exact Unity object relationships for CanvasTrans."
            ),
            "status": "unverified",
        },
    ]


def _require_upstream(
    envelope: dict[str, Any],
    artifact_type: str,
    artifact_hash: str,
) -> None:
    upstream = _one(
        envelope["inputs"]["upstream_artifacts"],
        "artifact_hash",
        artifact_hash,
    )
    _expect(
        upstream["artifact_type"] == artifact_type,
        "Upstream type drifted.",
    )


def _validate_source(
    content: bytes,
    span: dict[str, int],
) -> None:
    lines = content.decode("utf-8-sig").splitlines()
    start = span["start_line"]
    end = span["end_line"]
    _expect(
        end <= len(lines)
        and tuple(
            line.strip()
            for line in lines[start - 1 : end]
        )
        == _SOURCE_BLOCK,
        "Bound source span drifted.",
    )


def _project_root(
    resolved_file: Path,
    relative_path: str,
) -> Path:
    relative = PurePosixPath(relative_path)
    _expect(
        not relative.is_absolute()
        and ".." not in relative.parts,
        "Unsafe path.",
    )
    root = resolved_file
    for _ in relative.parts:
        root = root.parent
    _expect(
        (root / Path(*relative.parts)).resolve()
        == resolved_file,
        "Build path lineage drifted.",
    )
    return root


def _one(
    values: Any,
    key: str,
    value: str,
) -> dict[str, Any]:
    matches = [
        item
        for item in values
        if isinstance(item, dict)
        and item.get(key) == value
    ]
    _expect(
        len(matches) == 1,
        f"{key}={value} is not unique.",
    )
    return matches[0]


def _record(
    lines: list[str],
    tokens: tuple[str, ...],
) -> tuple[int, dict[str, str]]:
    matches = [
        (index, line)
        for index, line in enumerate(
            lines,
            start=1,
        )
        if all(token in line for token in tokens)
    ]
    _expect(
        len(matches) == 1,
        "Diagnostic record is not unique.",
    )
    line_number, line = matches[0]
    return line_number, {
        token.split("=", 1)[0]: token.split("=", 1)[1]
        for token in line.split()
        if "=" in token
    }


def _file_hash(path: Path) -> str:
    _expect(
        path.is_file(),
        f"Required file is missing: {path}",
    )
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest().upper()


def _expect(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise StaggerRootCausePreflightError(message)


def _canonical_json(
    value: dict[str, Any],
) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
