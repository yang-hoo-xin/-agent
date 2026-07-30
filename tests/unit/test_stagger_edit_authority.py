"""Tests for the exact no-write Stagger Edit Authority preflight."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.runtime import (
    StaggerEditAuthorityPreflightError,
    create_stagger_existing_binding_reauthorization_request,
    create_stagger_edit_authority_request,
    create_stagger_hud_parent_observation_authority_request,
    preflight_stagger_existing_binding_reauthorization,
    preflight_stagger_edit_authority,
    preflight_stagger_hud_parent_observation_authority,
)
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.artifacts.registry import (
    ArtifactRegistryError,
    ArtifactTypeRegistry,
)
from src.mod_agent.runtime import (
    stagger_edit_authority as edit_authority_module,
)
from src.mod_agent.runtime.stagger_edit_authority import (
    materialize_stagger_edit_authority_approval,
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
CURRENT_IMPLEMENTATION_PLAN_HASH = "8" * 64
EXISTING_BINDING_RESOLUTION_HASH = "9" * 64


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

    def check_exact_revision_freshness(self, ref):
        return self.check_freshness(ref)

    def list_feature_artifacts(self, feature_id: str) -> list[ArtifactRef]:
        assert feature_id == FEATURE_ID
        return [
            ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="feature_spec",
                path=str(self.root.parent / "feature-spec.json"),
                artifact_hash=FEATURE_SPEC_HASH,
            ),
            ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="runtime_evidence",
                path=str(self.root.parent / "runtime-evidence.json"),
                artifact_hash=RUNTIME_EVIDENCE_HASH,
            ),
            ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="implementation_plan",
                path=str(self.root.parent / "implementation-plan.json"),
                artifact_hash=IMPLEMENTATION_PLAN_HASH,
            ),
            ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="patch_proposal",
                path=str(self.root.parent / "patch-proposal.json"),
                artifact_hash=PATCH_PROPOSAL_HASH,
            ),
        ]

    def list_feature_artifact_revisions(
        self,
        feature_id: str,
        artifact_type: str,
    ) -> list[ArtifactRef]:
        return [
            ref
            for ref in self.list_feature_artifacts(feature_id)
            if ref.artifact_type == artifact_type
        ]

    def write(self, **_):
        raise AssertionError("The preflight must never write an Artifact.")


class _RoleAwareArtifactStore:
    envelopes_by_path: dict[str, dict[str, object]] = {}
    latest_by_type: dict[str, ArtifactRef] = {}
    revisions_by_type: dict[str, list[ArtifactRef]] = {}
    writes: list[dict[str, object]] = []
    preflight_types: tuple[str, ...] = ()

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def read(self, ref: ArtifactRef):
        return copy.deepcopy(
            self.__class__.envelopes_by_path[
                str(Path(ref.path).resolve())
            ]
        )

    def check_freshness(self, _ref):
        return SimpleNamespace(is_fresh=True, stale_reasons=[])

    def check_exact_revision_freshness(self, _ref):
        return SimpleNamespace(is_fresh=True, stale_reasons=[])

    def list_feature_artifacts(self, feature_id: str):
        assert feature_id == FEATURE_ID
        return list(self.__class__.latest_by_type.values())

    def list_feature_artifact_revisions(
        self,
        feature_id: str,
        artifact_type: str,
    ):
        assert feature_id == FEATURE_ID
        return list(
            self.__class__.revisions_by_type.get(artifact_type, ())
        )

    def preflight_atomic_commit(
        self,
        *,
        feature_id: str,
        artifact_types: tuple[str, ...],
    ) -> None:
        assert feature_id == FEATURE_ID
        self.__class__.preflight_types = tuple(artifact_types)

    def write(
        self,
        *,
        feature_id: str,
        artifact_type: str,
        payload: dict[str, object],
        status: str,
        upstream_refs: list[ArtifactRef],
        exact_revision_upstream_types: set[str],
        **_kwargs,
    ) -> ArtifactRef:
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=str(self.root / artifact_type / f"{digest[:32]}.json"),
            artifact_hash=digest,
        )
        envelope = {
            "status": status,
            "data": copy.deepcopy(payload),
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": item.artifact_type,
                        "artifact_hash": item.artifact_hash,
                        "path": item.path,
                    }
                    for item in upstream_refs
                ]
            },
        }
        self.__class__.envelopes_by_path[
            str(Path(ref.path).resolve())
        ] = envelope
        self.__class__.latest_by_type[artifact_type] = ref
        self.__class__.revisions_by_type.setdefault(
            artifact_type,
            [],
        ).append(ref)
        self.__class__.writes.append(
            {
                "artifact_type": artifact_type,
                "payload": copy.deepcopy(payload),
                "upstream_refs": list(upstream_refs),
                "exact_revision_upstream_types": set(
                    exact_revision_upstream_types
                ),
                "ref": ref,
            }
        )
        return ref


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
        "node_name": "create_implementation_plan",
        "stage": "implementation_plan",
        "message": "Existing plan.",
        "feature_id": FEATURE_ID,
        "evidence_source_paths": [TARGET_PATH],
        "target_files": [TARGET_PATH],
        "target_symbols": [
            (
                "BetterHitFeedback.Patches."
                "HitFeedbackBehaviorPatch.AddParallelMarkerPair"
            )
        ],
        "evidence_refs": ["existing_visual_evidence"],
        "proposed_changes": [
            {
                "change_id": "chg_002",
                "edit_binding_id": "edit_binding_002",
            }
        ],
        "side_effect_boundaries": [],
        "test_plan": ["focused validation"],
        "rollback_plan": ["Rollback chg_002."],
        "open_questions": [],
        "blocking": False,
        "blockers": [],
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
                    },
                    {
                        "artifact_type": "evidence_pack",
                        "artifact_hash": "5" * 64,
                        "path": "evidence-pack.json",
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
        "evidence_pack": {
            "status": "success",
            "data": {
                "node_name": "retrieve_evidence",
                "stage": "evidence_retrieval",
                "message": "Existing evidence.",
                "query": "Stagger feedback",
                "readiness": "sufficient",
                "can_generate_patch": True,
                "authority": "current_source",
                "authoritative_for_patch": True,
                "identity_schema_version": "evidence_identity_v1",
                "identity_field_mapping": {},
                "items": [
                    {
                        "evidence_id": "existing_visual_evidence",
                        "source_type": "target_source",
                        "source_path": TARGET_PATH,
                        "symbol": (
                            "BetterHitFeedback.Patches."
                            "HitFeedbackBehaviorPatch."
                            "AddParallelMarkerPair"
                        ),
                        "span": {
                            "start_line": 881,
                            "end_line": 907,
                        },
                    }
                ],
                "gaps": [],
                "excluded": [],
                "blockers": [],
                "retrieval_methods_used": ["current_source"],
                "missing_evidence": [],
                "disabled_modes": [],
                "timing": {},
                "trace_refs": [],
            },
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "feature_spec",
                        "artifact_hash": FEATURE_SPEC_HASH,
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


def _existing_binding_setup(
    tmp_path: Path,
) -> dict[str, object]:
    source_root = _source_root(tmp_path)
    source_path = source_root / TARGET_PATH
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    paths = {
        "feature_spec": tmp_path / "feature-spec.json",
        "runtime_evidence": tmp_path / "runtime-evidence.json",
        "predecessor_plan": tmp_path / "predecessor-plan.json",
        "patch_proposal": tmp_path / "patch-proposal.json",
        "current_plan": tmp_path / "current-plan.json",
        "existing_resolution": tmp_path / "existing-resolution.json",
        "evidence_pack": tmp_path / "evidence-pack.json",
        "old_approval": tmp_path / "old-approval.json",
    }
    base = _envelopes()
    predecessor_envelope = copy.deepcopy(base["implementation_plan"])
    predecessor_plan = predecessor_envelope["data"]
    assert isinstance(predecessor_plan, dict)
    current_plan = copy.deepcopy(predecessor_plan)
    bindings = current_plan["binding_registry"]["edit_bindings"]
    assert isinstance(bindings, list)
    bindings.append(
        {
            "authority": "human_exact_edit_authority",
            "binding_id": "edit_binding_004",
            "canonical_target_path": TARGET_PATH,
            "claim_supported": "Existing exact Stagger repair scope.",
            "evidence_id": "stagger_repair_evidence",
            "source_hash": source_hash,
            "source_type": "target_source",
            "target_span": {"start_line": 7, "end_line": 11},
            "target_symbol": TARGET_SYMBOL,
            "usage": "edit_target_scope",
        }
    )
    changes = current_plan["proposed_changes"]
    assert isinstance(changes, list)
    changes.append(
        {
            "change_id": "chg_004",
            "change_type": "repair_hud_recttransform_acquisition",
            "edit_binding_id": "edit_binding_004",
            "operation": (
                "replace_hud_recttransform_acquisition_and_null_guard_only"
            ),
        }
    )
    feature_spec = copy.deepcopy(base["feature_spec"]["data"])
    runtime_evidence = copy.deepcopy(
        base["runtime_evidence"]["data"]
    )
    assert isinstance(feature_spec, dict)
    assert isinstance(runtime_evidence, dict)
    diagnosis, _, replayed_ownership = (
        edit_authority_module._replay_stagger_visual_failure(
            feature_id=FEATURE_ID,
            feature_spec=feature_spec,
            runtime_evidence=runtime_evidence,
        )
    )
    bound_diagnosis = copy.deepcopy(diagnosis)
    anchors = bound_diagnosis["responsibility_anchors"]
    anchors["canonical_target_path"] = TARGET_PATH
    anchors["source_hash"] = source_hash
    anchors["source_span"] = {"start_line": 7, "end_line": 11}
    revisions = {
        "runtime": {
            "feature_id": FEATURE_ID,
            "path": str(paths["runtime_evidence"]),
            "artifact_hash": RUNTIME_EVIDENCE_HASH,
        },
        "current_plan": {
            "feature_id": FEATURE_ID,
            "path": str(paths["current_plan"]),
            "artifact_hash": CURRENT_IMPLEMENTATION_PLAN_HASH,
        },
        "proposal": {
            "feature_id": FEATURE_ID,
            "path": str(paths["patch_proposal"]),
            "artifact_hash": PATCH_PROPOSAL_HASH,
        },
    }
    resolution = (
        edit_authority_module.resolve_runtime_diagnosis_binding(
            diagnosis=bound_diagnosis,
            feature_id=FEATURE_ID,
            run_id=RUN_ID,
            runtime_evidence_revision=revisions["runtime"],
            implementation_plan_revision=revisions["current_plan"],
            patch_proposal_revision=revisions["proposal"],
            implementation_plan=current_plan,
            allowed_edit_binding_ids={"edit_binding_004"},
        ).to_artifact_payload()
    )
    resolution["authority_source"] = "edit_authority_approval"
    resolution["edit_authority_approval_revision"] = {
        "feature_id": FEATURE_ID,
        "path": str(paths["old_approval"]),
        "artifact_hash": "a" * 64,
    }
    resolution["evidence_pack_revision"] = {
        "feature_id": FEATURE_ID,
        "path": str(paths["evidence_pack"]),
        "artifact_hash": "5" * 64,
    }
    resolution["approved_runtime_failure_ownership"] = replayed_ownership
    resolution["repair_planner_allowed"] = False
    resolution["source_patch_allowed"] = False
    envelopes = {
        str(paths["feature_spec"].resolve()): {
            "data": feature_spec,
            "inputs": {"upstream_artifacts": []},
        },
        str(paths["runtime_evidence"].resolve()): copy.deepcopy(
            base["runtime_evidence"]
        ),
        str(paths["predecessor_plan"].resolve()): predecessor_envelope,
        str(paths["patch_proposal"].resolve()): copy.deepcopy(
            base["patch_proposal"]
        ),
        str(paths["current_plan"].resolve()): {
            "data": current_plan,
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "feature_spec",
                        "artifact_hash": FEATURE_SPEC_HASH,
                        "path": str(paths["feature_spec"]),
                    },
                    {
                        "artifact_type": "evidence_pack",
                        "artifact_hash": "5" * 64,
                        "path": str(paths["evidence_pack"]),
                    },
                    {
                        "artifact_type": "edit_authority_approval",
                        "artifact_hash": "a" * 64,
                        "path": str(paths["old_approval"]),
                    },
                    {
                        "artifact_type": "implementation_plan",
                        "artifact_hash": IMPLEMENTATION_PLAN_HASH,
                        "path": str(paths["predecessor_plan"]),
                    },
                ]
            },
        },
        str(paths["existing_resolution"].resolve()): {
            "data": resolution,
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": "runtime_evidence",
                        "artifact_hash": RUNTIME_EVIDENCE_HASH,
                        "path": str(paths["runtime_evidence"]),
                    },
                    {
                        "artifact_type": "implementation_plan",
                        "artifact_hash": (
                            CURRENT_IMPLEMENTATION_PLAN_HASH
                        ),
                        "path": str(paths["current_plan"]),
                    },
                    {
                        "artifact_type": "patch_proposal",
                        "artifact_hash": PATCH_PROPOSAL_HASH,
                        "path": str(paths["patch_proposal"]),
                    },
                    {
                        "artifact_type": "edit_authority_approval",
                        "artifact_hash": "a" * 64,
                        "path": str(paths["old_approval"]),
                    },
                    {
                        "artifact_type": "evidence_pack",
                        "artifact_hash": "5" * 64,
                        "path": str(paths["evidence_pack"]),
                    },
                ]
            },
        },
        str(paths["evidence_pack"].resolve()): copy.deepcopy(
            base["evidence_pack"]
        ),
        str(paths["old_approval"].resolve()): {
            "data": {"status": "approved"},
            "inputs": {"upstream_artifacts": []},
        },
    }
    refs = {
        "feature_spec": ArtifactRef(
            FEATURE_ID,
            "feature_spec",
            str(paths["feature_spec"]),
            FEATURE_SPEC_HASH,
        ),
        "runtime_evidence": ArtifactRef(
            FEATURE_ID,
            "runtime_evidence",
            str(paths["runtime_evidence"]),
            RUNTIME_EVIDENCE_HASH,
        ),
        "predecessor_plan": ArtifactRef(
            FEATURE_ID,
            "implementation_plan",
            str(paths["predecessor_plan"]),
            IMPLEMENTATION_PLAN_HASH,
        ),
        "patch_proposal": ArtifactRef(
            FEATURE_ID,
            "patch_proposal",
            str(paths["patch_proposal"]),
            PATCH_PROPOSAL_HASH,
        ),
        "current_plan": ArtifactRef(
            FEATURE_ID,
            "implementation_plan",
            str(paths["current_plan"]),
            CURRENT_IMPLEMENTATION_PLAN_HASH,
        ),
        "existing_resolution": ArtifactRef(
            FEATURE_ID,
            "binding_resolution",
            str(paths["existing_resolution"]),
            EXISTING_BINDING_RESOLUTION_HASH,
        ),
        "evidence_pack": ArtifactRef(
            FEATURE_ID,
            "evidence_pack",
            str(paths["evidence_pack"]),
            "5" * 64,
        ),
    }
    _RoleAwareArtifactStore.envelopes_by_path = envelopes
    _RoleAwareArtifactStore.latest_by_type = {
        "feature_spec": refs["feature_spec"],
        "runtime_evidence": refs["runtime_evidence"],
        "implementation_plan": refs["current_plan"],
        "patch_proposal": refs["patch_proposal"],
        "binding_resolution": refs["existing_resolution"],
        "evidence_pack": refs["evidence_pack"],
    }
    _RoleAwareArtifactStore.revisions_by_type = {
        "feature_spec": [refs["feature_spec"]],
        "runtime_evidence": [refs["runtime_evidence"]],
        "implementation_plan": [
            refs["predecessor_plan"],
            refs["current_plan"],
        ],
        "patch_proposal": [refs["patch_proposal"]],
        "binding_resolution": [refs["existing_resolution"]],
        "evidence_pack": [refs["evidence_pack"]],
    }
    _RoleAwareArtifactStore.writes = []
    _RoleAwareArtifactStore.preflight_types = ()
    return {
        "artifact_store_root": tmp_path / "artifacts",
        "feature_id": FEATURE_ID,
        "run_id": RUN_ID,
        "feature_spec_path": paths["feature_spec"],
        "feature_spec_hash": FEATURE_SPEC_HASH,
        "runtime_evidence_path": paths["runtime_evidence"],
        "runtime_evidence_hash": RUNTIME_EVIDENCE_HASH,
        "predecessor_implementation_plan_path": paths[
            "predecessor_plan"
        ],
        "predecessor_implementation_plan_hash": IMPLEMENTATION_PLAN_HASH,
        "patch_proposal_path": paths["patch_proposal"],
        "patch_proposal_hash": PATCH_PROPOSAL_HASH,
        "current_implementation_plan_path": paths["current_plan"],
        "current_implementation_plan_hash": (
            CURRENT_IMPLEMENTATION_PLAN_HASH
        ),
        "existing_binding_resolution_path": paths[
            "existing_resolution"
        ],
        "existing_binding_resolution_hash": (
            EXISTING_BINDING_RESOLUTION_HASH
        ),
        "source_root": source_root,
        "canonical_target_path": TARGET_PATH,
        "target_symbol": TARGET_SYMBOL,
        "target_start_line": 7,
        "target_end_line": 11,
    }


def _observation_authority_setup(
    tmp_path: Path,
) -> dict[str, object]:
    existing_args = _existing_binding_setup(tmp_path)
    source_root = Path(existing_args["source_root"])
    source_path = source_root / TARGET_PATH
    lines = [f"// filler {index}" for index in range(1, 985)]
    lines[296] = (
        "        public static void ShowHitIndicator_Prefix("
        "CrosshairGuiLayer __instance, Vector3 worldPos, bool isWeakspot, "
        "bool isFriendly, bool noDamage)"
    )
    lines[300] = (
        "                _lastHudParent = "
        "TryGetLayerHudParent(__instance);"
    )
    lines[334] = (
        "                _lastHudParent = "
        "TryGetLayerHudParent(__instance);"
    )
    lines[972] = (
        "        private static bool TrySpawnStaggerYellowX("
        "Vector3 worldPos, out string reason)"
    )
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
    source_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    current_plan_ref = _RoleAwareArtifactStore.latest_by_type[
        "implementation_plan"
    ]
    current_plan = _RoleAwareArtifactStore.envelopes_by_path[
        str(Path(current_plan_ref.path).resolve())
    ]["data"]
    binding = next(
        item
        for item in current_plan["binding_registry"]["edit_bindings"]
        if item.get("binding_id") == "edit_binding_004"
    )
    binding["source_hash"] = source_hash
    binding["target_span"] = {"start_line": 979, "end_line": 984}
    resolution_ref = _RoleAwareArtifactStore.latest_by_type[
        "binding_resolution"
    ]
    resolution = _RoleAwareArtifactStore.envelopes_by_path[
        str(Path(resolution_ref.path).resolve())
    ]["data"]
    resolution["authority_contract_version"] = (
        "edit_authority_existing_binding_reauthorization_v1"
    )
    resolution["resolved_repair_target"]["source_hash"] = source_hash
    resolution["resolved_repair_target"]["target_span"] = {
        "start_line": 979,
        "end_line": 984,
    }
    approval_path = tmp_path / "old-approval.json"
    approval_ref = ArtifactRef(
        FEATURE_ID,
        "edit_authority_approval",
        str(approval_path),
        "a" * 64,
    )
    _RoleAwareArtifactStore.envelopes_by_path[
        str(approval_path.resolve())
    ] = {
        "data": {
            "feature_id": FEATURE_ID,
            "run_id": RUN_ID,
            "status": "approved",
            "authority_contract_version": (
                "edit_authority_existing_binding_reauthorization_v1"
            ),
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        "inputs": {"upstream_artifacts": []},
    }
    _RoleAwareArtifactStore.latest_by_type[
        "edit_authority_approval"
    ] = approval_ref
    _RoleAwareArtifactStore.revisions_by_type[
        "edit_authority_approval"
    ] = [approval_ref]
    evidence_ref = _RoleAwareArtifactStore.latest_by_type["evidence_pack"]
    return {
        "artifact_store_root": existing_args["artifact_store_root"],
        "feature_id": FEATURE_ID,
        "run_id": RUN_ID,
        "feature_spec_path": existing_args["feature_spec_path"],
        "feature_spec_hash": FEATURE_SPEC_HASH,
        "runtime_evidence_path": existing_args["runtime_evidence_path"],
        "runtime_evidence_hash": RUNTIME_EVIDENCE_HASH,
        "current_implementation_plan_path": current_plan_ref.path,
        "current_implementation_plan_hash": current_plan_ref.artifact_hash,
        "patch_proposal_path": existing_args["patch_proposal_path"],
        "patch_proposal_hash": PATCH_PROPOSAL_HASH,
        "existing_binding_resolution_path": resolution_ref.path,
        "existing_binding_resolution_hash": resolution_ref.artifact_hash,
        "existing_edit_authority_approval_path": approval_ref.path,
        "existing_edit_authority_approval_hash": approval_ref.artifact_hash,
        "evidence_pack_path": evidence_ref.path,
        "evidence_pack_hash": evidence_ref.artifact_hash,
        "source_root": source_root,
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
    assert first["status"] == "READY_TO_CREATE_EDIT_AUTHORITY_REQUEST"
    assert first["proposal_hash"].startswith("sha256:")
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


def test_existing_binding_reauthorization_preflight_is_exact_and_no_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _existing_binding_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )

    first = preflight_stagger_existing_binding_reauthorization(**args)
    second = preflight_stagger_existing_binding_reauthorization(**args)

    assert first == second
    assert first["status"] == (
        "READY_TO_CREATE_EXISTING_BINDING_REAUTHORIZATION_REQUEST"
    )
    assert first["writes_performed"] is False
    assert first["artifact_writes_performed"] is False
    assert _RoleAwareArtifactStore.writes == []
    proposal = first["proposal"]
    assert proposal["binding_id"] == "edit_binding_004"
    assert proposal["root_cause_status"] == "unresolved"
    assert proposal["projection_boundary"] == {
        "new_edit_binding_allowed": False,
        "evidence_pack_revision_allowed": False,
        "implementation_plan_revision_allowed": False,
        "binding_resolution_revision_allowed": True,
        "technical_semantics_change_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }
    assert proposal[
        "predecessor_implementation_plan_revision"
    ]["artifact_hash"] == IMPLEMENTATION_PLAN_HASH
    assert proposal[
        "current_implementation_plan_revision"
    ]["artifact_hash"] == CURRENT_IMPLEMENTATION_PLAN_HASH


def test_existing_binding_reauthorization_blocks_proposal_plan_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _existing_binding_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )
    proposal_path = str(
        Path(args["patch_proposal_path"]).resolve()
    )
    proposal = _RoleAwareArtifactStore.envelopes_by_path[
        proposal_path
    ]["data"]
    assert isinstance(proposal, dict)
    proposal["context_pack"]["binding_registry_ref"][
        "artifact_hash"
    ] = CURRENT_IMPLEMENTATION_PLAN_HASH

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="predecessor ImplementationPlan",
    ):
        preflight_stagger_existing_binding_reauthorization(**args)

    assert _RoleAwareArtifactStore.writes == []


def test_existing_binding_reauthorization_blocks_binding_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _existing_binding_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )
    plan_path = str(
        Path(args["current_implementation_plan_path"]).resolve()
    )
    plan = _RoleAwareArtifactStore.envelopes_by_path[
        plan_path
    ]["data"]
    assert isinstance(plan, dict)
    binding = next(
        item
        for item in plan["binding_registry"]["edit_bindings"]
        if item.get("binding_id") == "edit_binding_004"
    )
    binding["source_hash"] = "f" * 64

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="no longer matches",
    ):
        preflight_stagger_existing_binding_reauthorization(**args)

    assert _RoleAwareArtifactStore.writes == []


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


class _WritableArtifactStore(_ReadOnlyArtifactStore):
    writes: list[dict[str, object]] = []
    preflight_types: tuple[str, ...] = ()

    def list_feature_artifacts(self, feature_id: str) -> list[ArtifactRef]:
        assert feature_id == FEATURE_ID
        latest = {
            "feature_spec": ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="feature_spec",
                path=str(self.root.parent / "feature-spec.json"),
                artifact_hash=FEATURE_SPEC_HASH,
            ),
            "runtime_evidence": ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="runtime_evidence",
                path=str(self.root.parent / "runtime-evidence.json"),
                artifact_hash=RUNTIME_EVIDENCE_HASH,
            ),
            "implementation_plan": ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="implementation_plan",
                path=str(self.root.parent / "implementation-plan.json"),
                artifact_hash=IMPLEMENTATION_PLAN_HASH,
            ),
            "patch_proposal": ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="patch_proposal",
                path=str(self.root.parent / "patch-proposal.json"),
                artifact_hash=PATCH_PROPOSAL_HASH,
            ),
        }
        for write in self.__class__.writes:
            ref = write.get("ref")
            if isinstance(ref, ArtifactRef):
                latest[ref.artifact_type] = ref
        return list(latest.values())

    def list_feature_artifact_revisions(
        self,
        feature_id: str,
        artifact_type: str,
    ) -> list[ArtifactRef]:
        return [
            ref
            for ref in self.list_feature_artifacts(feature_id)
            if ref.artifact_type == artifact_type
        ]

    def preflight_atomic_commit(
        self,
        *,
        feature_id: str,
        artifact_types: tuple[str, ...],
    ) -> None:
        assert feature_id == FEATURE_ID
        self.__class__.preflight_types = artifact_types

    def write(
        self,
        *,
        feature_id: str,
        artifact_type: str,
        payload,
        status: str = "success",
        upstream_refs=None,
        exact_revision_upstream_types=None,
        **_,
    ) -> ArtifactRef:
        assert feature_id == FEATURE_ID
        ArtifactTypeRegistry().validate_write(
            artifact_type=artifact_type,
            status=status,
            payload=dict(payload),
        )
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=str(
                self.root
                / "features"
                / feature_id
                / "r"
                / artifact_type
                / f"{digest[:32]}.json"
            ),
            artifact_hash=digest,
        )
        self.__class__.writes.append(
            {
                "artifact_type": artifact_type,
                "payload": copy.deepcopy(dict(payload)),
                "upstream_types": [
                    item.artifact_type
                    for item in (upstream_refs or [])
                ],
                "exact_revision_upstream_types": set(
                    exact_revision_upstream_types or set()
                ),
                "ref": ref,
            }
        )
        self.__class__.envelopes[artifact_type] = {
            "status": status,
            "data": copy.deepcopy(dict(payload)),
            "inputs": {
                "upstream_artifacts": [
                    {
                        "artifact_type": item.artifact_type,
                        "artifact_hash": item.artifact_hash,
                        "path": item.path,
                    }
                    for item in (upstream_refs or [])
                ]
            },
        }
        return ref


def test_request_writes_only_non_authoritative_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _preflight_args(tmp_path)
    _WritableArtifactStore.envelopes = _envelopes()
    _WritableArtifactStore.stale_types = set()
    _WritableArtifactStore.read_types = []
    _WritableArtifactStore.freshness_types = []
    _WritableArtifactStore.writes = []
    _WritableArtifactStore.preflight_types = ()
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _WritableArtifactStore,
    )
    source_path = Path(args["source_root"]) / TARGET_PATH
    source_hash_before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    result = create_stagger_edit_authority_request(**args)

    assert result["status"] == "EDIT_AUTHORITY_REQUEST_CREATED"
    assert result["written_artifact_types"] == ["edit_authority_request"]
    assert result["authority_granted"] is False
    assert result["registry_mutation_allowed"] is False
    assert result["repair_planner_invoked"] is False
    assert result["repair_allowed"] is False
    assert result["source_patch_allowed"] is False
    assert result["source_modified"] is False
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == (
        source_hash_before
    )
    assert [
        item["artifact_type"]
        for item in _WritableArtifactStore.writes
    ] == result["written_artifact_types"]
    request_write = _WritableArtifactStore.writes[0]
    assert request_write["upstream_types"] == [
        "feature_spec",
        "runtime_evidence",
        "implementation_plan",
        "patch_proposal",
    ]
    request_payload = request_write["payload"]
    assert request_payload["authority_granted"] is False
    assert request_payload["request_payload"]["projected_ids"] == {
        "binding_id": "edit_binding_003",
        "change_id": "chg_003",
        "evidence_id": request_payload["request_payload"][
            "projected_ids"
        ]["evidence_id"],
    }


def test_existing_binding_request_writes_no_authority_or_new_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _existing_binding_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )

    result = create_stagger_existing_binding_reauthorization_request(
        **args
    )

    assert result["status"] == (
        "EXISTING_BINDING_REAUTHORIZATION_REQUEST_CREATED"
    )
    assert result["written_artifact_types"] == [
        "edit_authority_request"
    ]
    assert result["authority_granted"] is False
    assert result["registry_mutation_allowed"] is False
    assert result["source_patch_allowed"] is False
    assert [
        item["artifact_type"]
        for item in _RoleAwareArtifactStore.writes
    ] == ["edit_authority_request"]
    request_write = _RoleAwareArtifactStore.writes[0]
    upstream_types = [
        ref.artifact_type
        for ref in request_write["upstream_refs"]
    ]
    assert upstream_types.count("implementation_plan") == 2
    assert "binding_resolution" in upstream_types
    request = request_write["payload"]
    assert request["request_payload"]["schema_version"] == (
        "stagger_existing_binding_reauthorization_request_v1"
    )
    assert "projected_ids" not in request["request_payload"]


def test_existing_binding_materialization_writes_only_approval_and_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _existing_binding_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )
    request_result = (
        create_stagger_existing_binding_reauthorization_request(**args)
    )
    request_revision = request_result[
        "edit_authority_request_revision"
    ]
    request_ref = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="edit_authority_request",
        path=request_revision["path"],
        artifact_hash=request_revision["artifact_hash"],
    )
    checkpoint_ref = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="workflow_checkpoint",
        path=str(tmp_path / "checkpoint-existing-binding.json"),
        artifact_hash="6" * 64,
    )
    report_ref = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="resume_report",
        path=str(tmp_path / "resume-existing-binding.json"),
        artifact_hash="7" * 64,
    )
    _RoleAwareArtifactStore.envelopes_by_path[
        str(Path(checkpoint_ref.path).resolve())
    ] = {
        "data": {
            "checkpoint_stage": "edit_authority_approval",
            "run_id": RUN_ID,
            "feature_id": FEATURE_ID,
            "state_snapshot": {
                "artifacts": {
                    "edit_authority_request": request_ref.path,
                },
                "artifact_hashes": {
                    "edit_authority_request": (
                        request_ref.artifact_hash
                    ),
                },
            },
            "resume_binding": {
                "edit_authority_request_ref": request_ref.path,
                "edit_authority_request_artifact_hash": (
                    request_ref.artifact_hash
                ),
                "edit_authority_request_hash": request_result[
                    "request_hash"
                ],
            },
        },
        "inputs": {"upstream_artifacts": []},
    }
    _RoleAwareArtifactStore.envelopes_by_path[
        str(Path(report_ref.path).resolve())
    ] = {
        "data": {
            "resume_id": "resume_existing_binding_001",
            "status": "accepted",
            "allowed": True,
            "decision": "approve",
            "resume_stage": "edit_authority_approval",
            "run_id": RUN_ID,
            "approved_by": "user",
            "approved_at": "2026-07-30T12:00:00+08:00",
            "authority_request_hash": request_result["request_hash"],
        },
        "inputs": {
            "upstream_artifacts": [
                {
                    "artifact_type": "workflow_checkpoint",
                    "path": checkpoint_ref.path,
                    "artifact_hash": checkpoint_ref.artifact_hash,
                }
            ]
        },
    }

    result = materialize_stagger_edit_authority_approval(
        artifact_store_root=args["artifact_store_root"],
        feature_id=FEATURE_ID,
        edit_authority_request_path=request_ref.path,
        edit_authority_request_hash=request_ref.artifact_hash,
        resume_report_path=report_ref.path,
        resume_report_hash=report_ref.artifact_hash,
    )

    assert result["status"] == "EXISTING_EDIT_AUTHORITY_REAUTHORIZED"
    assert result["written_artifact_types"] == [
        "edit_authority_approval",
        "binding_resolution",
    ]
    assert result["new_edit_binding_created"] is False
    assert result["implementation_plan_modified"] is False
    assert result["evidence_pack_modified"] is False
    assert result["repair_planner_invoked"] is False
    assert result["source_patch_allowed"] is False
    assert _RoleAwareArtifactStore.preflight_types == (
        "edit_authority_approval",
        "binding_resolution",
    )
    all_written_types = [
        item["artifact_type"]
        for item in _RoleAwareArtifactStore.writes
    ]
    assert all_written_types == [
        "edit_authority_request",
        "edit_authority_approval",
        "binding_resolution",
    ]
    approval = _RoleAwareArtifactStore.writes[1]["payload"]
    assert approval["allowed_actions"] == [
        "reauthorize_existing_edit_binding",
        "create_binding_resolution_revision",
    ]
    resolution = _RoleAwareArtifactStore.writes[2]["payload"]
    assert resolution["authority_contract_version"] == (
        "edit_authority_existing_binding_reauthorization_v1"
    )
    assert resolution["previous_binding_resolution_revision"][
        "artifact_hash"
    ] == EXISTING_BINDING_RESOLUTION_HASH


def test_request_creation_preserves_preflight_no_source_write(
    tmp_path: Path,
) -> None:
    args = _preflight_args(tmp_path)
    source_path = Path(args["source_root"]) / TARGET_PATH
    source_hash_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    preflight_stagger_edit_authority(**args)

    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == (
        source_hash_before
    )
    assert _ReadOnlyArtifactStore.read_types == [
        "feature_spec",
        "runtime_evidence",
        "implementation_plan",
        "patch_proposal",
    ]


def test_graph_resume_materialization_keeps_approval_permission_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _preflight_args(tmp_path)
    _WritableArtifactStore.envelopes = _envelopes()
    _WritableArtifactStore.stale_types = set()
    _WritableArtifactStore.read_types = []
    _WritableArtifactStore.freshness_types = []
    _WritableArtifactStore.writes = []
    _WritableArtifactStore.preflight_types = ()
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _WritableArtifactStore,
    )
    request_result = create_stagger_edit_authority_request(**args)
    request_revision = request_result[
        "edit_authority_request_revision"
    ]
    request_ref = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="edit_authority_request",
        path=request_revision["path"],
        artifact_hash=request_revision["artifact_hash"],
    )
    checkpoint_ref = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="workflow_checkpoint",
        path=str(tmp_path / "checkpoint.json"),
        artifact_hash="6" * 64,
    )
    _WritableArtifactStore.envelopes["workflow_checkpoint"] = {
        "data": {
            "checkpoint_stage": "edit_authority_approval",
            "run_id": RUN_ID,
            "feature_id": FEATURE_ID,
            "state_snapshot": {
                "artifacts": {
                    "edit_authority_request": request_ref.path,
                },
                "artifact_hashes": {
                    "edit_authority_request": request_ref.artifact_hash,
                },
            },
            "resume_binding": {
                "edit_authority_request_ref": request_ref.path,
                "edit_authority_request_artifact_hash": (
                    request_ref.artifact_hash
                ),
                "edit_authority_request_hash": request_result[
                    "request_hash"
                ],
            },
        },
        "inputs": {"upstream_artifacts": []},
    }
    report_ref = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="resume_report",
        path=str(tmp_path / "resume-report.json"),
        artifact_hash="7" * 64,
    )
    _WritableArtifactStore.envelopes["resume_report"] = {
        "data": {
            "resume_id": "resume_edit_authority_001",
            "status": "accepted",
            "allowed": True,
            "decision": "approve",
            "resume_stage": "edit_authority_approval",
            "run_id": RUN_ID,
            "approved_by": "user",
            "approved_at": "2026-07-30T12:00:00+08:00",
            "authority_request_hash": request_result["request_hash"],
        },
        "inputs": {
            "upstream_artifacts": [
                {
                    "artifact_type": "workflow_checkpoint",
                    "path": checkpoint_ref.path,
                    "artifact_hash": checkpoint_ref.artifact_hash,
                }
            ]
        },
    }

    result = materialize_stagger_edit_authority_approval(
        artifact_store_root=args["artifact_store_root"],
        feature_id=FEATURE_ID,
        edit_authority_request_path=request_ref.path,
        edit_authority_request_hash=request_ref.artifact_hash,
        resume_report_path=report_ref.path,
        resume_report_hash=report_ref.artifact_hash,
    )

    assert result["status"] == "EXACT_EDIT_AUTHORITY_RESOLVED"
    assert result["written_artifact_types"] == [
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
        "binding_resolution",
    ]
    approval = _WritableArtifactStore.writes[1]["payload"]
    assert approval["authority_source"] == "edit_authority_request"
    assert approval["request_hash"] == request_result["request_hash"]
    assert approval["repair_planner_allowed"] is False
    assert approval["source_patch_allowed"] is False
    assert "approved_proposal" not in approval
    assert "approved_runtime_failure_ownership" not in approval
    assert result["resolved_repair_target"]["binding_id"] == (
        "edit_binding_003"
    )


def test_request_creation_blocks_noncurrent_plan_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _preflight_args(tmp_path)
    _WritableArtifactStore.envelopes = _envelopes()
    _WritableArtifactStore.stale_types = set()
    _WritableArtifactStore.read_types = []
    _WritableArtifactStore.freshness_types = []
    _WritableArtifactStore.writes = [
        {
            "ref": ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="implementation_plan",
                path=str(tmp_path / "new-plan.json"),
                artifact_hash="9" * 64,
            )
        }
    ]
    _WritableArtifactStore.preflight_types = ()
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _WritableArtifactStore,
    )

    with pytest.raises(
        edit_authority_module.StaggerEditAuthorityApprovalError,
        match="implementation_plan is no longer the current revision",
    ):
        create_stagger_edit_authority_request(**args)

    assert all(
        write.get("artifact_type") != "edit_authority_request"
        for write in _WritableArtifactStore.writes
    )


def test_request_creation_blocks_same_hash_at_noncurrent_plan_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _preflight_args(tmp_path)
    _WritableArtifactStore.envelopes = _envelopes()
    _WritableArtifactStore.stale_types = set()
    _WritableArtifactStore.read_types = []
    _WritableArtifactStore.freshness_types = []
    _WritableArtifactStore.writes = [
        {
            "ref": ArtifactRef(
                feature_id=FEATURE_ID,
                artifact_type="implementation_plan",
                path=str(tmp_path / "same-bytes-new-revision.json"),
                artifact_hash=IMPLEMENTATION_PLAN_HASH,
            )
        }
    ]
    _WritableArtifactStore.preflight_types = ()
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _WritableArtifactStore,
    )

    with pytest.raises(
        edit_authority_module.StaggerEditAuthorityApprovalError,
        match="implementation_plan is no longer the current revision",
    ):
        create_stagger_edit_authority_request(**args)

    assert all(
        write.get("artifact_type") != "edit_authority_request"
        for write in _WritableArtifactStore.writes
    )


def test_observation_authority_preflight_projects_two_exact_no_write_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _observation_authority_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )
    source_path = Path(args["source_root"]) / TARGET_PATH
    source_hash_before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    first = preflight_stagger_hud_parent_observation_authority(**args)
    second = preflight_stagger_hud_parent_observation_authority(**args)

    assert first == second
    assert first["status"] == (
        "READY_TO_CREATE_STAGGER_HUD_PARENT_OBSERVATION_AUTHORITY_REQUEST"
    )
    assert first["writes_performed"] is False
    assert first["registry_mutation_allowed"] is False
    assert first["repair_allowed"] is False
    assert _RoleAwareArtifactStore.writes == []
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == (
        source_hash_before
    )
    bindings = first["proposal"]["diagnostic_bindings"]
    assert [
        (item["binding_id"], item["change_id"], item["target_span"])
        for item in bindings
    ] == [
        (
            "edit_binding_005",
            "chg_005",
            {"start_line": 301, "end_line": 301},
        ),
        (
            "edit_binding_006",
            "chg_006",
            {"start_line": 979, "end_line": 984},
        ),
    ]
    assert first["proposal"]["claim_boundary"] == {
        "observation_only": True,
        "product_behavior_change_allowed": False,
        "runtime_evidence_mutation_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
        "build_allowed": False,
        "process_launch_allowed": False,
        "game_directory_write_allowed": False,
        "diagnostic_result_counts_as_product_acceptance": False,
    }


def test_observation_authority_preflight_blocks_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _observation_authority_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )
    source_path = Path(args["source_root"]) / TARGET_PATH
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "// drift\n",
        encoding="utf-8",
    )

    with pytest.raises(
        StaggerEditAuthorityPreflightError,
        match="edit_binding_004 does not match",
    ):
        preflight_stagger_hud_parent_observation_authority(**args)

    assert _RoleAwareArtifactStore.writes == []


def test_observation_authority_request_and_graph_materialization_stop_at_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _observation_authority_setup(tmp_path)
    monkeypatch.setattr(
        edit_authority_module,
        "ArtifactStore",
        _RoleAwareArtifactStore,
    )
    request_result = (
        create_stagger_hud_parent_observation_authority_request(**args)
    )
    assert request_result["written_artifact_types"] == [
        "edit_authority_request"
    ]
    request_revision = request_result["edit_authority_request_revision"]
    request_ref = ArtifactRef(
        FEATURE_ID,
        "edit_authority_request",
        request_revision["path"],
        request_revision["artifact_hash"],
    )
    checkpoint_ref = ArtifactRef(
        FEATURE_ID,
        "workflow_checkpoint",
        str(tmp_path / "observation-checkpoint.json"),
        "6" * 64,
    )
    report_ref = ArtifactRef(
        FEATURE_ID,
        "resume_report",
        str(tmp_path / "observation-resume.json"),
        "7" * 64,
    )
    _RoleAwareArtifactStore.envelopes_by_path[
        str(Path(checkpoint_ref.path).resolve())
    ] = {
        "data": {
            "checkpoint_stage": "edit_authority_approval",
            "run_id": RUN_ID,
            "feature_id": FEATURE_ID,
            "state_snapshot": {
                "artifacts": {
                    "edit_authority_request": request_ref.path,
                },
                "artifact_hashes": {
                    "edit_authority_request": request_ref.artifact_hash,
                },
            },
            "resume_binding": {
                "edit_authority_request_ref": request_ref.path,
                "edit_authority_request_artifact_hash": (
                    request_ref.artifact_hash
                ),
                "edit_authority_request_hash": request_result["request_hash"],
            },
        },
        "inputs": {"upstream_artifacts": []},
    }
    _RoleAwareArtifactStore.envelopes_by_path[
        str(Path(report_ref.path).resolve())
    ] = {
        "data": {
            "resume_id": "resume_observation_authority_001",
            "status": "accepted",
            "allowed": True,
            "decision": "approve",
            "resume_stage": "edit_authority_approval",
            "run_id": RUN_ID,
            "approved_by": "user",
            "approved_at": "2026-07-30T16:30:00+08:00",
            "authority_request_hash": request_result["request_hash"],
        },
        "inputs": {
            "upstream_artifacts": [
                {
                    "artifact_type": "workflow_checkpoint",
                    "path": checkpoint_ref.path,
                    "artifact_hash": checkpoint_ref.artifact_hash,
                }
            ]
        },
    }

    result = materialize_stagger_edit_authority_approval(
        artifact_store_root=args["artifact_store_root"],
        feature_id=FEATURE_ID,
        edit_authority_request_path=request_ref.path,
        edit_authority_request_hash=request_ref.artifact_hash,
        resume_report_path=report_ref.path,
        resume_report_hash=report_ref.artifact_hash,
    )

    assert result["status"] == (
        "STAGGER_HUD_PARENT_OBSERVATION_PLAN_AUTHORIZED"
    )
    assert result["written_artifact_types"] == [
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
    ]
    assert result["allowed_edit_binding_ids"] == [
        "edit_binding_005",
        "edit_binding_006",
    ]
    assert result["binding_resolution_written"] is False
    assert result["repair_planner_invoked"] is False
    assert result["source_patch_allowed"] is False
    assert _RoleAwareArtifactStore.preflight_types == (
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
    )
    written_types = [
        item["artifact_type"]
        for item in _RoleAwareArtifactStore.writes
    ]
    assert written_types == [
        "edit_authority_request",
        "edit_authority_approval",
        "evidence_pack",
        "implementation_plan",
    ]
    approval = _RoleAwareArtifactStore.writes[1]["payload"]
    assert approval["authority_contract_version"] == (
        "edit_authority_stagger_hud_parent_observation_plan_v1"
    )
    assert approval["allowed_actions"] == [
        "create_observation_evidence_pack_revision",
        "create_diagnostic_implementation_plan_revision",
        "create_observation_only_edit_bindings",
    ]
    plan = _RoleAwareArtifactStore.writes[3]["payload"]
    diagnostic_scope = plan["diagnostic_scope"]
    assert diagnostic_scope["edit_binding_ids"] == [
        "edit_binding_005",
        "edit_binding_006",
    ]
    assert diagnostic_scope["repair_planner_allowed"] is False
    assert diagnostic_scope["source_patch_allowed"] is False
    ArtifactTypeRegistry().validate_write(
        artifact_type="implementation_plan",
        status="success",
        payload=plan,
    )
    diagnostic_binding = next(
        item
        for item in plan["binding_registry"]["edit_bindings"]
        if item.get("binding_id") == "edit_binding_005"
    )
    diagnostic_binding["source_patch_allowed"] = True
    with pytest.raises(
        ArtifactRegistryError,
        match="exceeds its approved scope",
    ):
        ArtifactTypeRegistry().validate_write(
            artifact_type="implementation_plan",
            status="success",
            payload=plan,
        )
