"""Focused tests for the Stagger diagnostic no-write exact diff."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.runtime import (
    StaggerDiagnosticDiffPreflightError,
    preflight_stagger_hud_parent_diagnostic_exact_diff,
)
from src.mod_agent.runtime import stagger_diagnostic_diff as diff_module


FEATURE_ID = "feature_001"
RUN_ID = "runtime_001"
SOURCE_PATH = "Patches/HitFeedbackBehaviorPatch.cs"
SOURCE_SYMBOLS = (
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "ShowHitIndicator_Prefix",
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "TrySpawnStaggerYellowX",
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch._lastHudParent",
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "TryGetLayerHudParent",
)
OPERATIONS = (
    "insert_observation_only_hud_parent_selection_state_after_"
    "existing_assignment",
    "insert_observation_only_hud_parent_use_state_before_existing_"
    "cast_and_guard",
    "insert_bounded_observation_state_after_existing_hud_parent_field",
    "insert_observation_identity_helpers_before_existing_hud_parent_"
    "resolver",
)
SPANS = (
    {"start_line": 301, "end_line": 301},
    {"start_line": 979, "end_line": 984},
    {"start_line": 27, "end_line": 27},
    {"start_line": 2511, "end_line": 2511},
)


class _NoWriteStore:
    envelopes: dict[str, dict[str, object]] = {}
    latest: dict[str, ArtifactRef] = {}
    revisions: dict[str, list[ArtifactRef]] = {}
    stale_types: set[str] = set()

    def __init__(self, _root: str | Path) -> None:
        pass

    def read(self, ref: ArtifactRef):
        return copy.deepcopy(
            self.__class__.envelopes[str(Path(ref.path).resolve())]
        )

    def list_feature_artifacts(self, feature_id: str):
        assert feature_id == FEATURE_ID
        return list(self.__class__.latest.values())

    def list_feature_artifact_revisions(
        self,
        feature_id: str,
        artifact_type: str,
    ):
        assert feature_id == FEATURE_ID
        return list(self.__class__.revisions.get(artifact_type, ()))

    def check_exact_revision_freshness(self, ref: ArtifactRef):
        return SimpleNamespace(
            is_fresh=ref.artifact_type not in self.__class__.stale_types,
            stale_reasons=(
                []
                if ref.artifact_type not in self.__class__.stale_types
                else ["test drift"]
            ),
        )

    def write(self, **_kwargs):
        raise AssertionError("Exact-diff preflight must not write Artifacts.")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _setup(tmp_path: Path) -> dict[str, object]:
    source_root = tmp_path / "source"
    source_path = source_root / SOURCE_PATH
    source_path.parent.mkdir(parents=True)
    lines = [f"// filler {index}" for index in range(1, 2530)]
    lines[26] = "        private static Transform? _lastHudParent;"
    lines[300] = (
        "                _lastHudParent = "
        "TryGetLayerHudParent(__instance);"
    )
    lines[334] = lines[300]
    lines[978:984] = [
        (
            "                RectTransform? canvasRect = "
            "_lastHudParent as RectTransform;"
        ),
        "                if (canvasRect == null)",
        "                {",
        '                    reason = "missing_canvas_rect_for_stagger_x";',
        "                    return false;",
        "                }",
    ]
    lines[2510] = (
        "        private static Transform? "
        "TryGetLayerHudParent(CrosshairGuiLayer? layer)"
    )
    source_path.write_bytes(
        ("\n".join(lines) + "\n").encode("utf-8")
    )
    plugin_path = source_root / "Plugin.cs"
    plugin_path.write_bytes(
        (
            "public static ConfigEntry<bool> EnableDiagnosticLogging "
            "{ get; private set; } = null!;\n"
            'Config.Bind("General", "EnableDiagnosticLogging", false, "test");\n'
        ).encode("utf-8")
    )
    dependency_assemblies: list[dict[str, str]] = []
    for role in (
        "unity_core_module",
        "modules_asm",
        "il2cpp_interop_runtime",
    ):
        dependency_path = tmp_path / "dependencies" / f"{role}.dll"
        dependency_path.parent.mkdir(parents=True, exist_ok=True)
        dependency_path.write_bytes(role.encode("ascii"))
        dependency_assemblies.append(
            {
                "role": role,
                "path": str(dependency_path),
                "sha256": _sha256(dependency_path),
            }
        )

    source_hash = _sha256(source_path)
    plugin_hash = _sha256(plugin_path)
    refs = {
        "edit_authority_approval": ArtifactRef(
            FEATURE_ID,
            "edit_authority_approval",
            str(tmp_path / "approval.json"),
            "1" * 64,
        ),
        "evidence_pack": ArtifactRef(
            FEATURE_ID,
            "evidence_pack",
            str(tmp_path / "evidence.json"),
            "2" * 64,
        ),
        "implementation_plan": ArtifactRef(
            FEATURE_ID,
            "implementation_plan",
            str(tmp_path / "plan.json"),
            "3" * 64,
        ),
    }
    approval_revision = {
        "feature_id": FEATURE_ID,
        "path": refs["edit_authority_approval"].path,
        "artifact_hash": refs["edit_authority_approval"].artifact_hash,
    }
    bindings = []
    changes = []
    evidence_items = []
    for index, (symbol, operation, span) in enumerate(
        zip(SOURCE_SYMBOLS, OPERATIONS, SPANS, strict=True),
        start=7,
    ):
        binding_id = f"edit_binding_{index:03d}"
        change_id = f"chg_{index:03d}"
        evidence_id = "stagger_observation_scope_" + binding_id
        bindings.append(
            {
                "binding_id": binding_id,
                "canonical_target_path": SOURCE_PATH,
                "source_hash": source_hash,
                "target_symbol": symbol,
                "target_span": dict(span),
                "evidence_id": evidence_id,
                "repair_planner_allowed": False,
                "source_patch_allowed": False,
            }
        )
        changes.append(
            {
                "change_id": change_id,
                "edit_binding_id": binding_id,
                "operation": operation,
            }
        )
        evidence_items.append(
            {
                "evidence_id": evidence_id,
                "source_path": SOURCE_PATH,
                "source_hash": source_hash,
                "symbol": symbol,
                "span": dict(span),
            }
        )
    evidence_items.extend(
        [
            {
                "evidence_id": "stagger_diagnostic_config_gate",
                "source_path": "Plugin.cs",
                "source_hash": plugin_hash,
                "source_ref": str(plugin_path),
            },
            {
                "evidence_id": "stagger_diagnostic_identity_api",
                "dependency_assemblies": dependency_assemblies,
            },
        ]
    )
    approval = {
        "feature_id": FEATURE_ID,
        "run_id": RUN_ID,
        "status": "approved",
        "decision": "approve",
        "authority_source": "edit_authority_request",
        "authority_contract_version": (
            "edit_authority_stagger_hud_parent_diagnostic_plan_v2"
        ),
        "request_hash": "sha256:" + ("a" * 64),
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
        "allowed_actions": [
            "create_observation_evidence_pack_revision",
            "create_diagnostic_only_implementation_plan_revision",
            "create_exact_bounded_observation_bindings",
        ],
        "forbidden_actions": [
            "create_binding_resolution_revision",
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ],
    }
    evidence = {"items": evidence_items}
    plan = {
        "feature_id": FEATURE_ID,
        "diagnostic_scope": {
            "schema_version": (
                "stagger_hud_parent_diagnostic_execution_authority_v2"
            ),
            "root_cause_status": "unresolved",
            "observation_only": True,
            "product_acceptance_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
            "selected_binding_ids": [
                f"edit_binding_{index:03d}" for index in range(7, 11)
            ],
            "selected_change_ids": [
                f"chg_{index:03d}" for index in range(7, 11)
            ],
            "new_plan_contains_only_selected_bindings": True,
            "new_plan_contains_only_selected_changes": True,
            "edit_authority_approval_revision": approval_revision,
        },
        "test_plan": {
            "schema_version": (
                "stagger_hud_parent_diagnostic_test_plan_v1"
            ),
            "product_acceptance_allowed": False,
            "repair_planner_allowed": False,
        },
        "binding_registry": {
            "edit_bindings": bindings,
            "supporting_bindings": [],
        },
        "proposed_changes": changes,
    }
    envelopes = {
        refs["edit_authority_approval"].path: {
            "data": approval,
            "inputs": {"upstream_artifacts": []},
        },
        refs["evidence_pack"].path: {
            "data": evidence,
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "edit_authority_approval",
                        "artifact_hash": refs[
                            "edit_authority_approval"
                        ].artifact_hash,
                    }
                ]
            },
        },
        refs["implementation_plan"].path: {
            "data": plan,
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "edit_authority_approval",
                        "artifact_hash": refs[
                            "edit_authority_approval"
                        ].artifact_hash,
                    },
                    {
                        "artifact_type": "evidence_pack",
                        "artifact_hash": refs["evidence_pack"].artifact_hash,
                    },
                ]
            },
        },
    }
    _NoWriteStore.envelopes = {
        str(Path(path).resolve()): envelope
        for path, envelope in envelopes.items()
    }
    _NoWriteStore.latest = {
        role: ref for role, ref in refs.items()
    }
    _NoWriteStore.revisions = {
        role: [ref] for role, ref in refs.items()
    }
    _NoWriteStore.stale_types = set()
    return {
        "artifact_store_root": tmp_path / "store",
        "feature_id": FEATURE_ID,
        "run_id": RUN_ID,
        "edit_authority_approval_path": refs[
            "edit_authority_approval"
        ].path,
        "edit_authority_approval_hash": refs[
            "edit_authority_approval"
        ].artifact_hash,
        "evidence_pack_path": refs["evidence_pack"].path,
        "evidence_pack_hash": refs["evidence_pack"].artifact_hash,
        "implementation_plan_path": refs["implementation_plan"].path,
        "implementation_plan_hash": refs[
            "implementation_plan"
        ].artifact_hash,
        "source_root": source_root,
    }


def test_exact_diff_is_deterministic_and_zero_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _setup(tmp_path)
    monkeypatch.setattr(diff_module, "ArtifactStore", _NoWriteStore)
    source_path = Path(args["source_root"]) / SOURCE_PATH
    source_before = source_path.read_bytes()

    first = preflight_stagger_hud_parent_diagnostic_exact_diff(**args)
    second = preflight_stagger_hud_parent_diagnostic_exact_diff(**args)

    assert first == second
    assert first["status"] == (
        "READY_FOR_STAGGER_HUD_PARENT_DIAGNOSTIC_DIFF_APPROVAL"
    )
    assert first["selected_binding_ids"] == [
        "edit_binding_007",
        "edit_binding_008",
        "edit_binding_009",
        "edit_binding_010",
    ]
    assert first["diff_stats"]["change_units"] == 4
    assert first["diff_stats"]["files"] == 1
    assert first["writes_performed"] is False
    assert first["artifact_writes_performed"] is False
    assert first["source_patch_allowed"] is False
    assert "signal=STAGGER_HUD_PARENT_DIAGNOSTIC" in (
        first["unified_diff"]
    )
    assert "Plugin.EnableDiagnosticLogging.Value" in (
        first["unified_diff"]
    )
    assert source_path.read_bytes() == source_before


def test_exact_diff_blocks_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _setup(tmp_path)
    monkeypatch.setattr(diff_module, "ArtifactStore", _NoWriteStore)
    source_path = Path(args["source_root"]) / SOURCE_PATH
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "// drift\n",
        encoding="utf-8",
    )

    with pytest.raises(
        StaggerDiagnosticDiffPreflightError,
        match="source hash does not match",
    ):
        preflight_stagger_hud_parent_diagnostic_exact_diff(**args)


def test_exact_diff_blocks_stale_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _setup(tmp_path)
    monkeypatch.setattr(diff_module, "ArtifactStore", _NoWriteStore)
    _NoWriteStore.stale_types = {"implementation_plan"}

    with pytest.raises(
        StaggerDiagnosticDiffPreflightError,
        match="inputs are stale",
    ):
        preflight_stagger_hud_parent_diagnostic_exact_diff(**args)
