"""Tests for the exact no-write Stagger Edit Authority preflight."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.runtime import (
    StaggerEditAuthorityPreflightError,
    preflight_stagger_edit_authority,
)
from src.mod_agent.runtime import (
    stagger_edit_authority as edit_authority_module,
)
from src.mod_agent.runtime.stagger_diagnosis import (
    STAGGER_VISUAL_ACCEPTANCE_CRITERION,
)


FEATURE_ID = "feature_001"
RUN_ID = "runtime_001"
TARGET_PATH = "Patches/HitFeedbackBehaviorPatch.cs"
TARGET_SYMBOL = (
    "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
    "TrySpawnStaggerYellowX"
)
FEATURE_SPEC_HASH = "1" * 64
RUNTIME_EVIDENCE_HASH = "2" * 64
IMPLEMENTATION_PLAN_HASH = "3" * 64
PATCH_PROPOSAL_HASH = "4" * 64


class _ReadOnlyArtifactStore:
    envelopes: dict[str, dict[str, object]] = {}
    stale_types: set[str] = set()
    read_types: list[str] = []
    freshness_types: list[str] = []

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def read(self, ref):
        self.__class__.read_types.append(ref.artifact_type)
        return copy.deepcopy(self.__class__.envelopes[ref.artifact_type])

    def check_freshness(self, ref):
        self.__class__.freshness_types.append(ref.artifact_type)
        if ref.artifact_type in self.__class__.stale_types:
            return SimpleNamespace(
                is_fresh=False,
                stale_reasons=["upstream hash changed"],
            )
        return SimpleNamespace(is_fresh=True, stale_reasons=[])

    def write(self, **_):
        raise AssertionError("The preflight must never write an Artifact.")


def _source_root(tmp_path: Path) -> Path:
    source_root = tmp_path / "source"
    source_path = source_root / TARGET_PATH
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "internal static class HitFeedbackBehaviorPatch\n"
        "{\n"
        "    private static bool TrySpawnStaggerYellowX("
        "Vector3 worldPos, out string reason)\n"
        "    {\n"
        "        try\n"
        "        {\n"
        "            RectTransform? canvasRect = _lastHudParent as RectTransform;\n"
        "            if (canvasRect == null)\n"
        "            {\n"
        '                reason = "missing_canvas_rect_for_stagger_x";\n'
        "                return false;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return source_root


def _envelopes() -> dict[str, dict[str, object]]:
    trust_checks = {
        check_name: {"status": "passed"}
        for check_name in (
            "feature_id",
            "runtime_process_identity",
            "current_run_logs",
            "plugin_load_marker",
            "deployed_plugin_artifact_hash",
            "runtime_config_identity",
        )
    }
    runtime_evidence = {
        "feature_id": FEATURE_ID,
        "run_id": RUN_ID,
        "failure_ownership": {
            "owner": "observation",
            "failure_class": "stagger_runtime_attempt_incomplete",
            "source_repair_allowed": False,
            "required_action": "repair_runtime_observation",
            "reason": "The original combined attempt was incomplete.",
        },
        "acceptance_contract": {
            "acceptance_criteria": [
                STAGGER_VISUAL_ACCEPTANCE_CRITERION
            ]
        },
        "operator_semantic_consistency": {"status": "consistent"},
        "stagger_runtime_attempts": [
            {"stagger_attempt_mode": "general_enabled_false"},
            {
                "stagger_attempt_mode": "general_enabled_true",
                "raw_supplied_output": (
                    "signal=STAGGER_FEEDBACK_SKIPPED "
                    "visual_spawned=False "
                    "visual_reason=missing_canvas_rect_for_stagger_x"
                ),
                "runtime_trust_binding": {"checks": trust_checks},
                "evidence_items": [
                    {
                        "source": "gtfo_persistent_log",
                        "locator": "run-local-log",
                        "supports_acceptance": [],
                    }
                ],
                "operator_completion": {
                    "request_sha256": "operator-sha256",
                    "semantic_consistency": {"status": "consistent"},
                    "observations": [
                        {
                            "acceptance_criterion": (
                                STAGGER_VISUAL_ACCEPTANCE_CRITERION
                            ),
                            "criterion_sha256": "criterion-sha256",
                            "semantic_consistency": "consistent",
                            "status": "failed",
                        }
                    ],
                },
            },
        ],
    }
    implementation_plan = {
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_002",
                    "evidence_id": "existing_visual_evidence",
                    "canonical_target_path": TARGET_PATH,
                    "source_type": "target_source",
                    "target_symbol": (
                        "BetterHitFeedback.Patches."
                        "HitFeedbackBehaviorPatch.AddParallelMarkerPair"
                    ),
                    "target_span": {
                        "start_line": 881,
                        "end_line": 907,
                    },
                    "source_hash": "0" * 64,
                }
            ],
            "supporting_bindings": [],
        }
    }
    patch_proposal = {
        "feature_id": FEATURE_ID,
        "context_pack": {
            "allowed_edit_binding_ids": ["edit_binding_002"],
            "binding_registry_ref": {
                "artifact_type": "implementation_plan",
                "artifact_hash": IMPLEMENTATION_PLAN_HASH,
            },
        },
    }
    return {
        "feature_spec": {
            "data": {
                "acceptance_criteria": [
                    STAGGER_VISUAL_ACCEPTANCE_CRITERION
                ]
            },
            "inputs": {"upstream_artifacts": []},
        },
        "runtime_evidence": {
            "data": runtime_evidence,
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "feature_spec",
                        "artifact_hash": FEATURE_SPEC_HASH,
                    }
                ]
            },
        },
        "implementation_plan": {
            "data": implementation_plan,
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "feature_spec",
                        "artifact_hash": FEATURE_SPEC_HASH,
                    }
                ]
            },
        },
        "patch_proposal": {
            "data": patch_proposal,
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "implementation_plan",
                        "artifact_hash": IMPLEMENTATION_PLAN_HASH,
                    }
                ]
            },
        },
    }


def _preflight_args(tmp_path: Path) -> dict[str, object]:
    return {
        "artifact_store_root": tmp_path / "artifacts",
        "feature_id": FEATURE_ID,
        "run_id": RUN_ID,
        "feature_spec_path": tmp_path / "feature-spec.json",
        "feature_spec_hash": FEATURE_SPEC_HASH,
        "runtime_evidence_path": tmp_path / "runtime-evidence.json",
        "runtime_evidence_hash": RUNTIME_EVIDENCE_HASH,
        "implementation_plan_path": tmp_path / "implementation-plan.json",
        "implementation_plan_hash": IMPLEMENTATION_PLAN_HASH,
        "patch_proposal_path": tmp_path / "patch-proposal.json",
        "patch_proposal_hash": PATCH_PROPOSAL_HASH,
        "source_root": _source_root(tmp_path),
        "canonical_target_path": TARGET_PATH,
        "target_symbol": TARGET_SYMBOL,
        "target_start_line": 7,
        "target_end_line": 11,
        "proposed_operation": (
            "replace_hud_recttransform_acquisition_and_null_guard_only"
        ),
    }


@pytest.fixture(autouse=True)
def _read_only_store(monkeypatch: pytest.MonkeyPatch):
    _ReadOnlyArtifactStore.envelopes = _envelopes()
    _ReadOnlyArtifactStore.stale_types = set()
    _ReadOnlyArtifactStore.read_types = []
    _ReadOnlyArtifactStore.freshness_types = []
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _ReadOnlyArtifactStore,
    )


def test_preflight_emits_exact_stable_proposal_without_writing(
    tmp_path: Path,
) -> None:
    args = _preflight_args(tmp_path)

    first = preflight_stagger_edit_authority(**args)
    second = preflight_stagger_edit_authority(**args)

    assert first == second
    assert first["status"] == "AWAITING_EXACT_EDIT_AUTHORITY_APPROVAL"
    assert first["approval_hash"].startswith("sha256:")
    assert first["approval_required"] is True
    assert first["registry_mutation_allowed"] is False
    assert first["repair_allowed"] is False
    assert first["writes_performed"] is False
    assert first["artifact_writes_performed"] is False
    assert first["repair_planner_invoked"] is False
    assert first["source_modified"] is False
    assert first["build_performed"] is False
    assert first["process_launched"] is False
    proposal = first["proposal"]
    assert proposal["proposed_target_symbol"] == TARGET_SYMBOL
    assert proposal["proposed_exact_span"] == {
        "start_line": 7,
        "end_line": 11,
    }
    assert proposal["existing_binding_gap"]["gap_reasons"] == [
        "missing_symbol_binding"
    ]
    assert proposal["ownership_review"][
        "stored_runtime_failure_ownership"
    ]["owner"] == "observation"
    assert proposal["ownership_review"][
        "replayed_runtime_failure_ownership"
    ]["owner"] == "product_behavior"
    assert proposal["ownership_review"][
        "runtime_evidence_mutation_allowed"
    ] is False
    assert proposal["approval_scope"] == [
        "runtime_failure_ownership_reclassification",
        "new_exact_edit_binding",
    ]
    assert _ReadOnlyArtifactStore.read_types == [
        "feature_spec",
        "runtime_evidence",
        "implementation_plan",
        "patch_proposal",
    ] * 2


def test_preflight_blocks_stale_runtime_evidence(tmp_path: Path) -> None:
    args = _preflight_args(tmp_path)
    _ReadOnlyArtifactStore.stale_types = {"runtime_evidence"}

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="RuntimeEvidence|runtime_evidence",
    ):
        preflight_stagger_edit_authority(**args)


def test_preflight_blocks_feature_spec_runtime_contract_mismatch(
    tmp_path: Path,
) -> None:
    args = _preflight_args(tmp_path)
    runtime_data = _ReadOnlyArtifactStore.envelopes[
        "runtime_evidence"
    ]["data"]
    assert isinstance(runtime_data, dict)
    runtime_data["acceptance_contract"] = {
        "acceptance_criteria": ["different exact criterion"]
    }

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="do not exactly match",
    ):
        preflight_stagger_edit_authority(**args)


def test_preflight_blocks_plan_from_different_feature_spec(
    tmp_path: Path,
) -> None:
    args = _preflight_args(tmp_path)
    plan_envelope = _ReadOnlyArtifactStore.envelopes[
        "implementation_plan"
    ]
    plan_envelope["inputs"] = {
        "upstream_artifacts": [
            {
                "artifact_type": "feature_spec",
                "artifact_hash": "9" * 64,
            }
        ]
    }

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="ImplementationPlan",
    ):
        preflight_stagger_edit_authority(**args)


def test_preflight_blocks_span_without_dependency_guard(
    tmp_path: Path,
) -> None:
    args = _preflight_args(tmp_path)
    args["target_start_line"] = 1
    args["target_end_line"] = 5

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="does not contain",
    ):
        preflight_stagger_edit_authority(**args)


def test_preflight_blocks_when_existing_authority_already_resolves(
    tmp_path: Path,
) -> None:
    args = _preflight_args(tmp_path)
    first = preflight_stagger_edit_authority(**args)
    source_hash = first["proposal"]["current_source"]["sha256"]
    plan_data = _ReadOnlyArtifactStore.envelopes[
        "implementation_plan"
    ]["data"]
    assert isinstance(plan_data, dict)
    registry = plan_data["binding_registry"]
    assert isinstance(registry, dict)
    bindings = registry["edit_bindings"]
    assert isinstance(bindings, list)
    binding = bindings[0]
    assert isinstance(binding, dict)
    binding["target_symbol"] = TARGET_SYMBOL
    binding["source_hash"] = source_hash
    binding["target_span"] = {"start_line": 7, "end_line": 11}

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="required Binding Gap",
    ):
        preflight_stagger_edit_authority(**args)
