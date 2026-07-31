"""Read-only Stagger HUD-parent hierarchy observation preprojection."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


class StaggerHierarchyObservationError(ValueError):
    """Raised when the hierarchy observation identity or content drifts."""


def merge_stagger_hierarchy_observation(
    *,
    base_preprojection: dict[str, Any],
    hierarchy_run_dir: str | Path,
) -> dict[str, Any]:
    """Merge one bound run-local hierarchy observation without writing."""

    projection = copy.deepcopy(base_preprojection)
    root = Path(hierarchy_run_dir).resolve()
    paths = {
        "current_run_truncated_output": (
            root / "LogOutput.current_run.log"
        ).resolve(),
        "post_run_full_copy": (
            root / "LogOutput.post_run_full_copy.log"
        ).resolve(),
        "runtime_result": (root / "runtime_result.json").resolve(),
        "process_stdout": (
            root / "process_diagnostics" / "stdout.log"
        ).resolve(),
        "process_stderr": (
            root / "process_diagnostics" / "stderr.log"
        ).resolve(),
        "restored_config_backup": (
            root / "runtime_config_backup" / "original.bin"
        ).resolve(),
    }
    _expect(
        all(path.is_file() for path in paths.values()),
        "Hierarchy run files are incomplete.",
    )
    runtime_bytes = paths["runtime_result"].read_bytes()
    runtime_result = json.loads(runtime_bytes.decode("utf-8-sig"))
    _expect(
        runtime_result.get("feature_id") == projection["feature_id"],
        "Hierarchy runtime feature identity drifted.",
    )
    _expect(
        isinstance(runtime_result.get("run_id"), str)
        and bool(runtime_result["run_id"]),
        "Hierarchy runtime run_id is missing.",
    )
    scope = runtime_result.get("diagnostic_scope")
    _expect(
        isinstance(scope, dict)
        and scope.get("observation_only") is True
        and scope.get("product_acceptance_allowed") is False
        and scope.get("repair_planner_allowed") is False
        and scope.get("source_patch_allowed") is False,
        "Hierarchy runtime scope drifted.",
    )
    deployment = runtime_result["plugin_deployment_binding"]
    diagnostic_dll = Path(deployment["source_path"]).resolve()
    diagnostic_dll_hash = _file_hash(diagnostic_dll)
    _expect(
        {
            str(deployment["expected_source_sha256"]).upper(),
            str(deployment["source_sha256"]).upper(),
            str(runtime_result["build_dll_sha256"]).upper(),
        }
        == {diagnostic_dll_hash},
        "Hierarchy diagnostic DLL identity drifted.",
    )
    diagnostic_config = Path(
        runtime_result["stagger_config_deployment_binding"]["source_path"]
    ).resolve()
    diagnostic_config_hash = _file_hash(diagnostic_config)
    _expect(
        {
            diagnostic_config_hash,
            str(runtime_result["diagnostic_config_sha256"]).upper(),
            str(
                runtime_result["stagger_config_deployment_binding"][
                    "source_sha256"
                ]
            ).upper(),
        }
        == {diagnostic_config_hash},
        "Hierarchy diagnostic config identity drifted.",
    )
    product_identity = projection["product_identity"]
    product_source = Path(product_identity["source_path"]).resolve()
    relative_source = product_source.relative_to(product_source.parents[1])
    diagnostic_root = diagnostic_dll.parents[2]
    diagnostic_source = (diagnostic_root / relative_source).resolve()
    _expect(
        diagnostic_source.is_file(),
        "Hierarchy diagnostic source is missing.",
    )
    screenshot = Path(runtime_result["screenshot"]["file_path"]).resolve()
    _expect(
        screenshot.is_file()
        and _file_hash(screenshot)
        == str(runtime_result["screenshot"]["content_hash"]).upper(),
        "Hierarchy screenshot identity drifted.",
    )
    restoration = runtime_result["runtime_trust_binding"]["checks"]
    _expect(
        restoration["game_directory_restoration"]["status"] == "passed"
        and restoration["runtime_config_restoration"]["status"] == "passed",
        "Hierarchy runtime restoration is not verified.",
    )
    _expect(
        _file_hash(paths["restored_config_backup"])
        == str(
            restoration["runtime_config_restoration"][
                "destination_sha256_after_restore"
            ]
        ).upper(),
        "Hierarchy restored config backup drifted.",
    )
    current_identity = runtime_result["diagnostic_run_identity"]
    _expect(
        _file_hash(paths["current_run_truncated_output"])
        == str(current_identity["current_run_log_sha256"]).upper(),
        "Hierarchy truncated current-run output drifted.",
    )
    prefix_identity = _validate_post_run_copy(
        paths["post_run_full_copy"],
        runtime_result,
    )
    observation = _hierarchy_observation(
        paths["post_run_full_copy"].read_bytes()
    )
    hierarchy_items = _evidence_items(
        paths=paths,
        screenshot=screenshot,
        diagnostic_source=diagnostic_source,
        diagnostic_dll=diagnostic_dll,
        diagnostic_config=diagnostic_config,
        prefix_identity=prefix_identity,
    )
    projection["schema_version"] = (
        "stagger_hierarchy_repair_selection_preprojection_v1"
    )
    projection["hierarchy_observation_identity"] = {
        "run_id": runtime_result["run_id"],
        "runtime_result_path": str(paths["runtime_result"]),
        "runtime_result_sha256": hashlib.sha256(
            runtime_bytes
        ).hexdigest().upper(),
        "diagnostic_source_path": str(diagnostic_source),
        "diagnostic_source_sha256": _file_hash(diagnostic_source),
        "diagnostic_dll_path": str(diagnostic_dll),
        "diagnostic_dll_sha256": diagnostic_dll_hash,
        "diagnostic_config_path": str(diagnostic_config),
        "diagnostic_config_sha256": diagnostic_config_hash,
        "post_run_full_copy": prefix_identity,
    }
    semantic = projection["semantic_assessment"]
    semantic["status"] = (
        "ready_for_non_authoritative_repair_selection"
    )
    semantic["scope"] = (
        "direct_failure_mechanism_and_bounded_rect_transform_route"
    )
    semantic["repair_selection_allowed"] = True
    semantic["selected_rect_transform_acquisition_path"] = (
        "_lastHudParent.GetComponentInParent<RectTransform>()"
    )
    semantic["binding_scope_assessment"] = (
        "covered_by_edit_binding_004"
    )
    semantic["confirmed_mechanism"][
        "hierarchy_observation"
    ] = observation
    semantic["unresolved"] = [
        "yellow_x_product_runtime_acceptance",
        "audio_audibility",
    ]
    projection["root_cause_evidence_projection"][
        "evidence_items"
    ].extend(hierarchy_items)
    limitations = projection["root_cause_evidence_projection"][
        "immutable_limitations"
    ]
    limitations.extend(
        item
        for item in (
            "hierarchy_run_is_run_local_observation_not_formal_runtime_evidence",
            "hierarchy_full_log_is_post_run_copy",
            "hierarchy_runner_output_is_truncated_to_profile_limit",
            "hierarchy_diagnostic_dll_is_not_formal_product_build_result",
        )
        if item not in limitations
    )
    projection["materialization_admission"][
        "immutable_limitations"
    ] = list(limitations)
    projection["planner_admission"][
        "immutable_limitations"
    ] = list(limitations)
    hypothesis_projection = projection[
        "repair_hypothesis_set_projection"
    ]
    hypothesis_projection["selection_status"] = (
        "selected"
    )
    hypothesis_projection["hypotheses"] = _resolved_hypotheses(
        hypothesis_projection["hypotheses"],
        hierarchy_items,
    )
    projection["writes_performed"] = False
    projection["artifact_writes_performed"] = False
    projection["repair_planner_invoked"] = False
    projection["source_modified"] = False
    projection["build_performed"] = False
    projection["process_launched"] = False
    projection_without_hash = {
        key: value
        for key, value in projection.items()
        if key != "projection_hash"
    }
    return {
        **projection_without_hash,
        "projection_hash": (
            "sha256:"
            + hashlib.sha256(
                _canonical_json(projection_without_hash)
            ).hexdigest()
        ),
    }


def _validate_post_run_copy(
    path: Path,
    runtime_result: dict[str, Any],
) -> dict[str, Any]:
    windows = runtime_result["runtime_trust_binding"]["checks"][
        "current_run_logs"
    ]["source_windows"]
    eligible = [
        window
        for window in windows
        if isinstance(window, dict)
        and window.get("status") == "passed"
        and window.get("mode")
        == "created_or_truncated_after_prelaunch_boundary"
        and window.get("run_local_start_byte") == 0
        and isinstance(window.get("run_local_size_bytes"), int)
        and isinstance(window.get("run_local_sha256"), str)
    ]
    _expect(
        bool(eligible),
        "Hierarchy current-run source window is missing.",
    )
    window = max(
        eligible,
        key=lambda item: (
            int(item.get("generation", 0)),
            int(item["run_local_size_bytes"]),
        ),
    )
    content = path.read_bytes()
    prefix_size = int(window["run_local_size_bytes"])
    _expect(
        len(content) >= prefix_size,
        "Hierarchy post-run copy is shorter than its observed prefix.",
    )
    prefix_hash = hashlib.sha256(
        content[:prefix_size]
    ).hexdigest().upper()
    _expect(
        prefix_hash == str(window["run_local_sha256"]).upper(),
        "Hierarchy post-run copy prefix drifted.",
    )
    return {
        "path": str(path),
        "sha256": _file_hash(path),
        "size_bytes": len(content),
        "provenance": "post_run_copy_of_current_run_generation",
        "observed_prefix_sha256": prefix_hash,
        "observed_prefix_size_bytes": prefix_size,
        "observed_prefix_verified": True,
    }


def _hierarchy_observation(log_bytes: bytes) -> dict[str, Any]:
    lines = log_bytes.decode("utf-8-sig").splitlines()
    required = (
        "signal=STAGGER_HUD_PARENT_DIAGNOSTIC",
        "phase=stagger_use",
        "assignment_seen=true",
        "last_assignment_source=CanvasTrans",
        "hierarchy_observation_error=none",
        "rect_transform_route_found=true",
        "_lastHudParent.reference_null=false",
        "_lastHudParent.unity_null=false",
        "_lastHudParent.runtime_type=UnityEngine.Transform",
        "_lastHudParent.rect_transform_compatible=false",
        "_lastHudParent.parent.reference_null=false",
        "_lastHudParent.parent.unity_null=false",
        "_lastHudParent.parent.runtime_type=UnityEngine.Transform",
        "_lastHudParent.parent.rect_transform_compatible=false",
        (
            "_lastHudParent.GetComponentInParent<RectTransform>()"
            ".reference_null=false"
        ),
        (
            "_lastHudParent.GetComponentInParent<RectTransform>()"
            ".unity_null=false"
        ),
        (
            "_lastHudParent.GetComponentInParent<RectTransform>()"
            ".runtime_type=UnityEngine.RectTransform"
        ),
        (
            "_lastHudParent.GetComponentInParent<RectTransform>()"
            ".rect_transform_compatible=true"
        ),
        (
            "_lastHudParent.GetComponentInParent<RectTransform>()"
            ".identity_read_error=none"
        ),
    )
    matches = [
        (index, line)
        for index, line in enumerate(lines, start=1)
        if all(token in line for token in required)
    ]
    _expect(
        len(matches) == 1,
        "Hierarchy repair-selection observation is not unique.",
    )
    line_number, line = matches[0]
    values = {
        token.split("=", 1)[0]: token.split("=", 1)[1]
        for token in line.split()
        if "=" in token
    }
    route_prefix = (
        "_lastHudParent.GetComponentInParent<RectTransform>()"
    )
    current_id = values["_lastHudParent.unity_instance_id"]
    route_id = values[f"{route_prefix}.unity_instance_id"]
    assigned_id = values[
        "last_assigned_HUD_parent.unity_instance_id"
    ]
    _expect(
        current_id == route_id == assigned_id,
        "Hierarchy route Unity instance identity drifted.",
    )
    return {
        "evidence_line_number": line_number,
        "assignment_source": "CanvasTrans",
        "selected_transform_runtime_type": "UnityEngine.Transform",
        "parent_transform_runtime_type": "UnityEngine.Transform",
        "rect_transform_acquisition_expression": (
            "_lastHudParent.GetComponentInParent<RectTransform>()"
        ),
        "rect_transform_runtime_type": "UnityEngine.RectTransform",
        "rect_transform_compatible": True,
        "shared_unity_instance_id": current_id,
        "hierarchy_observation_error": "none",
    }


def _evidence_items(
    *,
    paths: dict[str, Path],
    screenshot: Path,
    diagnostic_source: Path,
    diagnostic_dll: Path,
    diagnostic_config: Path,
    prefix_identity: dict[str, Any],
) -> list[dict[str, Any]]:
    entries = [
        (
            "hierarchy_current_run_truncated_output",
            paths["current_run_truncated_output"],
            "runner_output_limited_current_run_bytes",
            "runner_output_limit_projection",
        ),
        (
            "hierarchy_post_run_full_copy",
            paths["post_run_full_copy"],
            "complete_post_run_log_generation",
            "post_run_copy",
        ),
        (
            "hierarchy_runtime_result",
            paths["runtime_result"],
            "diagnostic_result_payload",
            "run_local_output",
        ),
        (
            "hierarchy_screenshot",
            screenshot,
            "diagnostic_screen_capture",
            "run_local_output",
        ),
        (
            "hierarchy_restored_config_backup",
            paths["restored_config_backup"],
            "pre_run_config_restoration_bytes",
            "run_local_output",
        ),
        (
            "hierarchy_process_stdout",
            paths["process_stdout"],
            "diagnostic_process_stdout",
            "run_local_output",
        ),
        (
            "hierarchy_process_stderr",
            paths["process_stderr"],
            "diagnostic_process_stderr",
            "run_local_output",
        ),
        (
            "hierarchy_diagnostic_source",
            diagnostic_source,
            "observation_only_diagnostic_source",
            "isolated_materialization",
        ),
        (
            "hierarchy_diagnostic_dll",
            diagnostic_dll,
            "observation_only_diagnostic_dll",
            "isolated_build_output",
        ),
        (
            "hierarchy_diagnostic_config",
            diagnostic_config,
            "observation_only_diagnostic_config",
            "isolated_runtime_input",
        ),
    ]
    items = [
        {
            "evidence_id": evidence_id,
            "path": str(path),
            "sha256": _file_hash(path),
            "content_scope": content_scope,
            "provenance_class": provenance_class,
            "formal_runtime_evidence": False,
        }
        for evidence_id, path, content_scope, provenance_class in entries
    ]
    next(
        item
        for item in items
        if item["evidence_id"] == "hierarchy_post_run_full_copy"
    )["observed_prefix_identity"] = copy.deepcopy(prefix_identity)
    return items


def _resolved_hypotheses(
    hypotheses: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_ids = [
        item["evidence_id"]
        for item in evidence_items
        if item["evidence_id"]
        in {
            "hierarchy_post_run_full_copy",
            "hierarchy_runtime_result",
            "hierarchy_diagnostic_source",
            "hierarchy_diagnostic_dll",
        }
    ]
    resolved = copy.deepcopy(hypotheses)
    for item in resolved:
        hypothesis_id = item["hypothesis_id"]
        if hypothesis_id == "H1":
            item.update(
                {
                    "statement": (
                        "CanvasTrans reaches a compatible RectTransform through "
                        "_lastHudParent.GetComponentInParent<RectTransform>()."
                    ),
                    "supporting_evidence": evidence_ids,
                    "unverified_assumptions": [],
                    "binding_status": "covered_by_current_binding",
                    "proposed_operation": (
                        "Replace only the bound _lastHudParent as RectTransform "
                        "acquisition with _lastHudParent."
                        "GetComponentInParent<RectTransform>(); preserve the "
                        "existing null guard and failure reason."
                    ),
                    "required_observation": "completed",
                    "status": "supported",
                }
            )
        elif hypothesis_id == "H3":
            item.update(
                {
                    "supporting_evidence": evidence_ids,
                    "unverified_assumptions": [],
                    "required_observation": "completed",
                    "status": "rejected",
                }
            )
        else:
            item.update(
                {
                    "required_observation": "not_required_after_H1",
                    "status": "unverified",
                }
            )
    return resolved


def _file_hash(path: Path) -> str:
    _expect(path.is_file(), f"Required file is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise StaggerHierarchyObservationError(message)
