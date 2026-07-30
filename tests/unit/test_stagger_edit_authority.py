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
    create_stagger_edit_authority_request,
    preflight_stagger_edit_authority,
)
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.artifacts.registry import ArtifactTypeRegistry
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
