"""Tests for the Phase A artifact store."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import src.mod_agent.artifacts.store as artifact_store_module
from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    StaleArtifactError,
)
from src.mod_agent.artifacts.registry import (
    ArtifactContract,
    ArtifactTypeRegistry,
)
from src.mod_agent.artifacts.store import ArtifactStorePreflightError
from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION


def _payload(stage: str = "feature_spec") -> dict[str, str]:
    return {
        "node_name": "draft_feature_spec",
        "stage": stage,
        "message": "stub",
    }


def _feature_payload() -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "stub",
        "feature_id": "feature_001",
        "user_request": "Load",
        "target_behavior": "Load",
        "non_goals": [],
        "target_mod": None,
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _request_payload() -> dict[str, object]:
    return {
        "node_name": "plan_request",
        "stage": "request_planning",
        "message": "stub",
        "feature_id": "feature_001",
        "user_request": "Load",
        "route": "standard_feature",
        "risk_level": "medium",
        "target_mod": None,
        "requires_hook_evidence": True,
        "requires_runtime_evidence": False,
        "uncertainties": [],
        "blocked": False,
    }


def _evidence_payload() -> dict[str, object]:
    return {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "stub",
        "query": "Load",
        "readiness": "insufficient",
        "can_generate_patch": False,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": False,
        "identity_schema_version": IDENTITY_SCHEMA_VERSION,
        "identity_field_mapping": dict(IDENTITY_FIELD_MAPPING),
        "items": [],
        "gaps": ["stub"],
        "excluded": [],
        "blockers": [],
        "retrieval_methods_used": [],
        "missing_evidence": [],
        "disabled_modes": {},
        "timing": {},
        "trace_refs": [],
    }


def _changed_feature_payload() -> dict[str, object]:
    payload = _feature_payload()
    payload["message"] = "changed"
    payload["target_behavior"] = "changed"
    return payload


def _implementation_payload() -> dict[str, object]:
    return {
        "node_name": "create_implementation_plan",
        "stage": "implementation_plan",
        "message": "stub",
        "feature_id": "feature_001",
        "evidence_source_paths": ["Plugin.cs"],
        "target_files": ["Plugin.cs"],
        "target_symbols": ["Load"],
        "evidence_refs": ["ev_001"],
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "evidence_id": "ev_001",
                    "canonical_target_path": "Plugin.cs",
                    "source_type": "target_source",
                    "target_symbol": "Load",
                    "target_span": {"start_line": 1, "end_line": 10},
                }
            ],
            "supporting_bindings": [],
        },
        "proposed_changes": [
            {
                "change_id": "chg_001",
                "edit_binding_id": "edit_binding_001",
                "supporting_binding_ids": [],
            }
        ],
        "side_effect_boundaries": [],
        "test_plan": [],
        "rollback_plan": [],
        "open_questions": [],
        "blocking": False,
        "blockers": [],
    }


def _legacy_edit_authority_approval_payload() -> dict[str, object]:
    proposal = {
        "schema_version": "stagger_edit_authority_proposal_v1",
        "feature_id": "feature_001",
    }
    approval_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            proposal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "node_name": "approve_stagger_edit_authority",
        "stage": "edit_authority_approval",
        "message": "Historical authority shape.",
        "status": "approved",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "approval_hash": approval_hash,
        "approved_by": "user",
        "approval_scope": [
            "runtime_failure_ownership_reclassification",
            "new_exact_edit_binding",
        ],
        "approved_proposal": proposal,
        "stored_runtime_failure_ownership": {
            "owner": "observation",
            "source_repair_allowed": False,
        },
        "approved_runtime_failure_ownership": {
            "owner": "product_behavior",
            "source_repair_allowed": True,
        },
        "allowed_edit_binding_ids": ["edit_binding_004"],
        "allowed_evidence_ids": ["stagger_repair_001"],
        "runtime_evidence_mutation_allowed": False,
        "old_patch_proposal_mutation_allowed": False,
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }


def test_request_bound_approval_requires_exact_request_and_resume_refs(
    tmp_path: Path,
) -> None:
    statuses = frozenset({"success"})
    simple_contracts = [
        ArtifactContract(
            artifact_type=artifact_type,
            schema_version="1.0",
            required_fields=frozenset({"node_name", "stage", "message"}),
            producer_stage=artifact_type,
            consumer_stages=frozenset({"edit_authority_request"}),
            allowed_statuses=statuses,
        )
        for artifact_type in (
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
            "resume_report",
        )
    ]
    default_registry = ArtifactTypeRegistry()
    registry = ArtifactTypeRegistry(
        contracts=[
            *simple_contracts,
            default_registry.get("edit_authority_request"),
            default_registry.get("edit_authority_approval"),
        ]
    )
    store = ArtifactStore(tmp_path / "artifacts", registry=registry)
    upstream_refs = {}
    for artifact_type in (
        "feature_spec",
        "runtime_evidence",
        "implementation_plan",
        "patch_proposal",
        "resume_report",
    ):
        payload = {
            "node_name": artifact_type,
            "stage": artifact_type,
            "message": "stub",
        }
        if artifact_type == "implementation_plan":
            payload["blocking"] = True
        upstream_refs[artifact_type] = store.write(
            feature_id="feature_001",
            artifact_type=artifact_type,
            payload=payload,
        )
    request_payload = {
        "schema_version": "stagger_edit_authority_request_v1",
        "proposal": {},
        "source_root": str(tmp_path),
        "projected_ids": {
            "binding_id": "edit_binding_004",
            "change_id": "chg_004",
            "evidence_id": "stagger_repair_001",
        },
    }
    request_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            request_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request_ref = store.write(
        feature_id="feature_001",
        artifact_type="edit_authority_request",
        payload={
            "node_name": "request_stagger_edit_authority",
            "stage": "edit_authority_request",
            "message": "Awaiting approval.",
            "status": "pending_human_approval",
            "feature_id": "feature_001",
            "run_id": "run_001",
            "request_hash": request_hash,
            "request_payload": request_payload,
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_allowed": False,
            "source_patch_allowed": False,
        },
        upstream_refs=[
            upstream_refs["feature_spec"],
            upstream_refs["runtime_evidence"],
            upstream_refs["implementation_plan"],
            upstream_refs["patch_proposal"],
        ],
        exact_revision_upstream_types={
            "feature_spec",
            "runtime_evidence",
            "implementation_plan",
            "patch_proposal",
        },
    )
    resume_ref = upstream_refs["resume_report"]
    approval_payload = {
        "node_name": "approve_stagger_edit_authority",
        "stage": "edit_authority_approval",
        "message": "Approved.",
        "status": "approved",
        "feature_id": "feature_001",
        "run_id": "run_001",
        "authority_source": "edit_authority_request",
        "approval_hash": request_hash,
        "request_hash": request_hash,
        "approved_by": "user",
        "approved_at": "2026-07-30T12:00:00+08:00",
        "resume_id": "resume_001",
        "decision": "approve",
        "edit_authority_request_revision": {
            "feature_id": "feature_001",
            "path": request_ref.path,
            "artifact_hash": request_ref.artifact_hash,
        },
        "resume_report_revision": {
            "feature_id": "feature_001",
            "path": resume_ref.path,
            "artifact_hash": resume_ref.artifact_hash,
        },
        "allowed_actions": [
            "create_evidence_pack_revision",
            "create_implementation_plan_revision",
            "resolve_exact_edit_binding",
        ],
        "forbidden_actions": [
            "invoke_repair_planner",
            "modify_source",
            "build",
            "launch_process",
            "write_game_directory",
        ],
        "repair_planner_allowed": False,
        "source_patch_allowed": False,
    }

    with pytest.raises(
        ArtifactStoreError,
        match="requires exact revision upstream",
    ):
        store.write(
            feature_id="feature_001",
            artifact_type="edit_authority_approval",
            payload=approval_payload,
            upstream_refs=[request_ref, resume_ref],
        )

    approval_ref = store.write(
        feature_id="feature_001",
        artifact_type="edit_authority_approval",
        payload=approval_payload,
        upstream_refs=[request_ref, resume_ref],
        exact_revision_upstream_types={
            "edit_authority_request",
            "resume_report",
        },
    )

    assert store.read(approval_ref)["data"]["request_hash"] == request_hash


def test_store_rejects_new_legacy_edit_authority_approval_write(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(
        ArtifactStoreError,
        match="must originate from an exact EditAuthorityRequest",
    ):
        store.write(
            feature_id="feature_001",
            artifact_type="edit_authority_approval",
            payload=_legacy_edit_authority_approval_payload(),
        )


def test_existing_binding_reauthorization_store_requires_all_exact_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_id = "feature_001"
    monkeypatch.setattr(
        store,
        "read",
        lambda item: {
            "feature_id": item.feature_id,
            "artifact_type": item.artifact_type,
        },
    )
    monkeypatch.setattr(
        store,
        "_check_upstream_write_freshness",
        lambda item, require_latest: type(
            "Freshness",
            (),
            {"is_fresh": True, "stale_reasons": ()},
        )(),
    )

    def ref(
        artifact_type: str,
        name: str,
        fill: str,
    ) -> ArtifactRef:
        return ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=str(tmp_path / f"{name}.json"),
            artifact_hash=fill * 64,
        )

    refs = {
        "feature_spec": ref("feature_spec", "feature", "1"),
        "runtime_evidence": ref(
            "runtime_evidence",
            "runtime",
            "2",
        ),
        "predecessor_plan": ref(
            "implementation_plan",
            "predecessor-plan",
            "3",
        ),
        "current_plan": ref(
            "implementation_plan",
            "current-plan",
            "4",
        ),
        "patch_proposal": ref(
            "patch_proposal",
            "proposal",
            "5",
        ),
        "previous_resolution": ref(
            "binding_resolution",
            "previous-resolution",
            "6",
        ),
        "request": ref(
            "edit_authority_request",
            "request",
            "7",
        ),
        "approval": ref(
            "edit_authority_approval",
            "approval",
            "8",
        ),
        "evidence": ref("evidence_pack", "evidence", "9"),
    }

    def revision(item: ArtifactRef) -> dict[str, str]:
        return {
            "feature_id": feature_id,
            "path": item.path,
            "artifact_hash": item.artifact_hash,
        }

    payload = {
        "authority_contract_version": (
            "edit_authority_existing_binding_reauthorization_v1"
        ),
        "edit_authority_request_revision": revision(refs["request"]),
        "edit_authority_approval_revision": revision(refs["approval"]),
        "evidence_pack_revision": revision(refs["evidence"]),
        "runtime_evidence_revision": revision(refs["runtime_evidence"]),
        "implementation_plan_revision": revision(refs["current_plan"]),
        "patch_proposal_revision": revision(refs["patch_proposal"]),
        "predecessor_implementation_plan_revision": revision(
            refs["predecessor_plan"]
        ),
        "previous_binding_resolution_revision": revision(
            refs["previous_resolution"]
        ),
    }
    upstream_refs = list(refs.values())
    exact_types = {
        item.artifact_type for item in upstream_refs
    }
    contract = ArtifactContract(
        artifact_type="binding_resolution",
        schema_version="1.0",
        required_fields=frozenset(),
        producer_stage="binding_resolution",
        consumer_stages=frozenset(),
        allowed_statuses=frozenset({"success"}),
    )

    store._validate_upstream_refs(
        feature_id=feature_id,
        artifact_type="binding_resolution",
        contract=contract,
        payload=payload,
        status="success",
        upstream_refs=upstream_refs,
        allow_stale_upstreams=False,
        exact_revision_upstream_types=exact_types,
    )

    not_exact = set(exact_types)
    not_exact.remove("runtime_evidence")
    with pytest.raises(
        ArtifactStoreError,
        match="requires exact request, approval, and evidence upstreams",
    ):
        store._validate_upstream_refs(
            feature_id=feature_id,
            artifact_type="binding_resolution",
            contract=contract,
            payload=payload,
            status="success",
            upstream_refs=upstream_refs,
            allow_stale_upstreams=False,
            exact_revision_upstream_types=not_exact,
        )

    wrong_role = dict(payload)
    wrong_role["predecessor_implementation_plan_revision"] = {
        "feature_id": feature_id,
        "path": str(tmp_path / "other-plan.json"),
        "artifact_hash": "a" * 64,
    }
    with pytest.raises(
        ArtifactStoreError,
        match="predecessor_implementation_plan_revision",
    ):
        store._validate_upstream_refs(
            feature_id=feature_id,
            artifact_type="binding_resolution",
            contract=contract,
            payload=wrong_role,
            status="success",
            upstream_refs=upstream_refs,
            allow_stale_upstreams=False,
            exact_revision_upstream_types=exact_types,
        )


def test_stagger_observation_request_store_requires_every_exact_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_id = "feature_001"
    monkeypatch.setattr(
        store,
        "read",
        lambda item: {
            "feature_id": item.feature_id,
            "artifact_type": item.artifact_type,
        },
    )
    monkeypatch.setattr(
        store,
        "_check_upstream_write_freshness",
        lambda item, require_latest: type(
            "Freshness",
            (),
            {"is_fresh": True, "stale_reasons": ()},
        )(),
    )

    def ref(artifact_type: str, fill: str) -> ArtifactRef:
        return ArtifactRef(
            feature_id=feature_id,
            artifact_type=artifact_type,
            path=str(tmp_path / f"{artifact_type}.json"),
            artifact_hash=fill * 64,
        )

    refs = {
        "feature_spec": ref("feature_spec", "1"),
        "runtime_evidence": ref("runtime_evidence", "2"),
        "implementation_plan": ref("implementation_plan", "3"),
        "patch_proposal": ref("patch_proposal", "4"),
        "binding_resolution": ref("binding_resolution", "5"),
        "edit_authority_approval": ref("edit_authority_approval", "6"),
        "evidence_pack": ref("evidence_pack", "7"),
    }

    def revision(item: ArtifactRef) -> dict[str, str]:
        return {
            "feature_id": feature_id,
            "path": item.path,
            "artifact_hash": item.artifact_hash,
        }

    request_payload = {
        "schema_version": (
            "stagger_hud_parent_diagnostic_execution_authority_request_v2"
        ),
        "source_root": str(tmp_path),
        "proposal": {
            "feature_spec_revision": revision(refs["feature_spec"]),
            "runtime_evidence_revision": revision(
                refs["runtime_evidence"]
            ),
            "current_implementation_plan_revision": revision(
                refs["implementation_plan"]
            ),
            "patch_proposal_revision": revision(refs["patch_proposal"]),
            "existing_binding_resolution_revision": revision(
                refs["binding_resolution"]
            ),
            "existing_edit_authority_approval_revision": revision(
                refs["edit_authority_approval"]
            ),
            "evidence_pack_revision": revision(refs["evidence_pack"]),
        },
    }
    payload = {"request_payload": request_payload}
    upstream_refs = list(refs.values())
    exact_types = set(refs)
    contract = ArtifactContract(
        artifact_type="edit_authority_request",
        schema_version="1.0",
        required_fields=frozenset(),
        producer_stage="edit_authority_request",
        consumer_stages=frozenset(),
        allowed_statuses=frozenset({"success"}),
    )

    store._validate_upstream_refs(
        feature_id=feature_id,
        artifact_type="edit_authority_request",
        contract=contract,
        payload=payload,
        status="success",
        upstream_refs=upstream_refs,
        allow_stale_upstreams=False,
        exact_revision_upstream_types=exact_types,
    )

    not_exact = set(exact_types)
    not_exact.remove("edit_authority_approval")
    with pytest.raises(
        ArtifactStoreError,
        match="requires every exact technical and authority role",
    ):
        store._validate_upstream_refs(
            feature_id=feature_id,
            artifact_type="edit_authority_request",
            contract=contract,
            payload=payload,
            status="success",
            upstream_refs=upstream_refs,
            allow_stale_upstreams=False,
            exact_revision_upstream_types=not_exact,
        )

    wrong_role = json.loads(json.dumps(payload))
    wrong_role["request_payload"]["proposal"][
        "evidence_pack_revision"
    ]["artifact_hash"] = "a" * 64
    with pytest.raises(
        ArtifactStoreError,
        match="revision roles do not match",
    ):
        store._validate_upstream_refs(
            feature_id=feature_id,
            artifact_type="edit_authority_request",
            contract=contract,
            payload=wrong_role,
            status="success",
            upstream_refs=upstream_refs,
            allow_stale_upstreams=False,
            exact_revision_upstream_types=exact_types,
        )


def test_write_wraps_payload_in_envelope(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
        status="stubbed",
        trace_refs=["trace_001"],
    )

    envelope = store.read(ref)
    assert envelope["schema_version"] == "1.0"
    assert envelope["artifact_type"] == "feature_spec"
    assert envelope["feature_id"] == "feature_001"
    assert envelope["status"] == "stubbed"
    assert envelope["producer_stage"] == "feature_spec"
    assert envelope["data"] == _feature_payload()
    assert envelope["inputs"] == {"upstream_artifacts": []}
    assert envelope["trace_refs"] == ["trace_001"]
    assert ref.artifact_hash == envelope["artifact_hash"]


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    ref = store.write(
        feature_id="feature_001",
        artifact_type="request_planning_report",
        payload=_request_payload(),
    )

    assert Path(ref.path).exists()
    assert Path(ref.path).parent.name == "request_planning_report"
    assert Path(ref.path).parent.parent.name == "r"
    assert len(Path(ref.path).stem) == 32
    assert (
        tmp_path / "artifacts" / "features" / "feature_001" / "request_planning_report.json"
    ).exists()


def test_write_leaves_no_atomic_temp_files(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    assert list((tmp_path / "artifacts").rglob(".tmp-*")) == []


def test_write_removes_pending_marker_after_success(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    pending_dir = (
        tmp_path / "artifacts" / "features" / "feature_001" / "p"
    )
    assert list(pending_dir.rglob("*.json")) == []


def test_write_cleans_atomic_temp_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("src.mod_agent.artifacts.store.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        store.write(
            feature_id="feature_001",
            artifact_type="feature_spec",
            payload=_feature_payload(),
        )

    assert list((tmp_path / "artifacts").rglob(".tmp-*")) == []


def test_recover_pending_write_restores_latest_from_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    original_replace = artifact_store_module.os.replace

    def fail_latest_replace(source: Path, destination: Path) -> None:
        if Path(destination).name == "feature_spec.json":
            raise OSError("latest replace failed")
        original_replace(source, destination)

    monkeypatch.setattr(artifact_store_module.os, "replace", fail_latest_replace)

    with pytest.raises(OSError, match="latest replace failed"):
        store.write(
            feature_id="feature_001",
            artifact_type="feature_spec",
            payload=_feature_payload(),
        )

    pending_dir = (
        tmp_path / "artifacts" / "features" / "feature_001" / "p"
    )
    pending_markers = list(pending_dir.rglob("*.json"))
    assert len(pending_markers) == 1
    revision_files = list(
        (
            tmp_path
            / "artifacts"
            / "features"
            / "feature_001"
            / "r"
            / "feature_spec"
        ).glob("*.json")
    )
    assert len(revision_files) == 1
    latest_path = tmp_path / "artifacts" / "features" / "feature_001" / "feature_spec.json"
    assert not latest_path.exists()

    revision_envelope = json.loads(revision_files[0].read_text(encoding="utf-8"))
    monkeypatch.setattr(artifact_store_module.os, "replace", original_replace)

    recovery = store.recover_pending_writes()

    assert recovery == [
        {
            "feature_id": "feature_001",
            "artifact_type": "feature_spec",
            "artifact_hash": revision_envelope["artifact_hash"],
            "status": "recovered",
        }
    ]
    assert json.loads(latest_path.read_text(encoding="utf-8")) == revision_envelope
    assert list(pending_dir.rglob("*.json")) == []


def test_write_reuses_valid_legacy_revision_without_copying_it(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    new_path = Path(first.path)
    legacy_path = (
        tmp_path
        / "artifacts"
        / "features"
        / "feature_001"
        / "revisions"
        / "feature_spec"
        / f"{first.artifact_hash}.json"
    )
    legacy_path.parent.mkdir(parents=True)
    new_path.replace(legacy_path)

    second = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    assert second.path == str(legacy_path.resolve())
    assert second.artifact_hash == first.artifact_hash
    assert store.read(second)["artifact_hash"] == first.artifact_hash
    assert not new_path.exists()


def test_write_rejects_short_revision_locator_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(
        ArtifactStore,
        "_physical_locator",
        staticmethod(lambda _artifact_hash: "0" * 32),
    )
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    with pytest.raises(ArtifactStoreError, match="revision locator collision"):
        store.write(
            feature_id="feature_001",
            artifact_type="feature_spec",
            payload=_changed_feature_payload(),
        )


def test_write_rejects_short_pending_locator_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(
        ArtifactStore,
        "_physical_locator",
        staticmethod(lambda _artifact_hash: "0" * 32),
    )
    other_hash = "a" * 64
    pending_path = store._pending_write_path(
        "feature_001",
        "feature_spec",
        other_hash,
    )
    revision_path = store._revision_artifact_path(
        "feature_001",
        "feature_spec",
        other_hash,
    )
    latest_path = store._artifact_path("feature_001", "feature_spec")
    pending_path.parent.mkdir(parents=True)
    pending_path.write_text(
        store._serialize_pending_write(
            feature_id="feature_001",
            artifact_type="feature_spec",
            artifact_hash=other_hash,
            revision_path=revision_path,
            latest_path=latest_path,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactStoreError, match="pending locator collision"):
        store.write(
            feature_id="feature_001",
            artifact_type="feature_spec",
            payload=_feature_payload(),
        )


def test_explicit_ref_rejects_feature_and_type_identity_mismatch(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    with pytest.raises(ArtifactStoreError, match="feature_id mismatch"):
        store.read(
            ArtifactRef(
                feature_id="feature_002",
                artifact_type=ref.artifact_type,
                path=ref.path,
                artifact_hash=ref.artifact_hash,
            )
        )
    with pytest.raises(ArtifactStoreError, match="artifact_type mismatch"):
        store.read(
            ArtifactRef(
                feature_id=ref.feature_id,
                artifact_type="evidence_pack",
                path=ref.path,
                artifact_hash=ref.artifact_hash,
            )
        )


def test_preflight_uses_compact_real_paths_and_leaves_no_artifact_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = str(tmp_path.resolve())
    filler_length = max(1, 130 - len(base) - 1)
    root = tmp_path / ("a" * filler_length)
    store = ArtifactStore(root)
    feature_id = "feature_8eae153e6c04"
    artifact_types = (
        "request_planning_report",
        "mod_planning_brief",
        "feature_spec",
        "evidence_pack",
    )
    synthetic_hash = "0" * 64
    pending_path = store._pending_write_path(
        feature_id,
        "request_planning_report",
        synthetic_hash,
    )
    revision_path = store._revision_artifact_path(
        feature_id,
        "request_planning_report",
        synthetic_hash,
    )
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = artifact_store_module.os.replace

    def record_replace(source: Path, destination: Path) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        assert source_path.parent == destination_path.parent
        replace_calls.append((source_path, destination_path))
        original_replace(source, destination)

    monkeypatch.setattr(artifact_store_module.os, "replace", record_replace)

    store.preflight_atomic_commit(
        feature_id=feature_id,
        artifact_types=artifact_types,
    )

    if len(str(root.resolve())) == 130:
        assert len(str(pending_path)) == 224
        assert len(str(revision_path)) == 224
    assert len(replace_calls) == len(artifact_types) * 3
    assert not root.exists() or list(root.rglob("*.json")) == []


def test_long_artifact_root_commits_request_planning_artifact(
    tmp_path: Path,
) -> None:
    base = str(tmp_path.resolve())
    filler_length = max(1, 130 - len(base) - 1)
    root = tmp_path / ("b" * filler_length)
    store = ArtifactStore(root)

    ref = store.write(
        feature_id="feature_8eae153e6c04",
        artifact_type="request_planning_report",
        payload={**_request_payload(), "feature_id": "feature_8eae153e6c04"},
    )

    assert Path(ref.path).exists()
    assert Path(ref.path).parent.parent.name == "r"
    assert len(Path(ref.path).stem) == 32
    if len(str(root.resolve())) == 130:
        assert len(ref.path) == 224
    latest = (
        root
        / "features"
        / "feature_8eae153e6c04"
        / "request_planning_report.json"
    )
    assert latest.exists()
    assert list((root / "features").rglob(".tmp-*")) == []
    assert list((root / "features").rglob("p/**/*.json")) == []


def test_preflight_wraps_only_recognized_replace_path_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    def fail_replace(_source: Path, _destination: Path) -> None:
        error = FileNotFoundError("path is not addressable")
        error.winerror = 3
        raise error

    monkeypatch.setattr(artifact_store_module.os, "replace", fail_replace)

    with pytest.raises(ArtifactStorePreflightError) as captured:
        store.preflight_atomic_commit(
            feature_id="feature_001",
            artifact_types=("request_planning_report",),
        )

    error = captured.value
    assert error.artifact_type == "request_planning_report"
    assert error.path_role == "pending_marker"
    assert error.source_path_length < error.target_path_length
    assert error.target_parent_exists is True
    assert error.winerror == 3
    assert not (tmp_path / "artifacts").exists()


def test_preflight_does_not_reclassify_unknown_replace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise PermissionError("replace is denied")

    monkeypatch.setattr(artifact_store_module.os, "replace", fail_replace)

    with pytest.raises(PermissionError, match="replace is denied"):
        store.preflight_atomic_commit(
            feature_id="feature_001",
            artifact_types=("request_planning_report",),
        )


def test_list_feature_artifacts_returns_refs(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    second = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[first],
    )

    refs = store.list_feature_artifacts("feature_001")

    assert {ref.artifact_type for ref in refs} == {"feature_spec", "evidence_pack"}
    assert {ref.artifact_hash for ref in refs} == {
        first.artifact_hash,
        second.artifact_hash,
    }


def test_write_preserves_immutable_revisions_and_latest_pointer(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    first = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    second = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_changed_feature_payload(),
    )

    assert first.path != second.path
    assert Path(first.path).exists()
    assert Path(second.path).exists()
    assert store.read(first)["artifact_hash"] == first.artifact_hash
    latest_refs = store.list_feature_artifacts("feature_001")
    assert len(latest_refs) == 1
    assert latest_refs[0].artifact_hash == second.artifact_hash
    assert Path(latest_refs[0].path).name == "feature_spec.json"


def test_freshness_rejects_tampered_latest_pointer(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    latest_path = tmp_path / "artifacts" / "features" / "feature_001" / "feature_spec.json"
    envelope = json.loads(latest_path.read_text(encoding="utf-8"))
    envelope["data"]["message"] = "tampered latest"
    latest_path.write_text(json.dumps(envelope), encoding="utf-8")

    freshness = store.check_freshness(evidence_pack)

    assert freshness.status == "stale"
    assert freshness.stale_reasons == [
        "feature_spec latest invalid: Artifact content hash mismatch"
    ]


def test_required_upstream_artifacts_are_enforced(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStoreError, match="missing required upstream artifacts"):
        store.write(
            feature_id="feature_001",
            artifact_type="evidence_pack",
            payload=_evidence_payload(),
        )


def test_required_upstream_artifacts_are_recorded(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )

    envelope = store.read(evidence_pack)
    assert envelope["inputs"]["upstream_artifacts"] == [
        {
            "artifact_type": "feature_spec",
            "path": feature_spec.path,
            "artifact_hash": feature_spec.artifact_hash,
            "require_latest": True,
        }
    ]


def test_exact_revision_upstream_is_not_stale_when_latest_pointer_advances(
    tmp_path: Path,
) -> None:
    def patch_proposal_payload(message: str) -> dict[str, object]:
        return {
            "node_name": "draft_patch_proposal",
            "stage": "patch_proposal",
            "message": message,
            "proposal_id": message.replace(" ", "_"),
            "feature_id": "feature_001",
            "summary": message,
            "files": [],
            "evidence_refs": [],
            "diff_intent": [],
            "change_units": [],
            "context_pack": {},
            "scope_boundary": {
                "allowed_files": [],
                "forbidden_files": [],
                "max_files_changed": 0,
            },
            "risk_assessment": {},
            "expected_tests": [],
            "no_op_status": {"is_no_op": False},
            "rollback_hints": [],
            "manual_review_notes": [],
            "blocked": False,
            "blockers": [],
        }

    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    implementation_plan = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec, evidence_pack],
    )
    patch_proposal_v1 = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload=patch_proposal_payload("proposal v1"),
        upstream_refs=[feature_spec, evidence_pack, implementation_plan],
    )
    proposal_review = store.write(
        feature_id="feature_001",
        artifact_type="proposal_review",
        payload={
            "node_name": "review_proposal",
            "stage": "proposal_review",
            "message": "review",
            "decision": "approve_dry_run",
            "findings": [],
            "required_changes": [],
            "allowed_next_stage": "dry_run_apply",
            "checked_rules": [],
            "trace_metrics": {
                "num_changes_checked": 1,
                "num_blocking_findings": 0,
            },
        },
        upstream_refs=[patch_proposal_v1],
    )
    dry_run_result = store.write(
        feature_id="feature_001",
        artifact_type="dry_run_result",
        payload={
            "node_name": "dry_run_apply",
            "stage": "dry_run_apply",
            "message": "dry run",
        },
        upstream_refs=[patch_proposal_v1, proposal_review],
    )
    build_result = store.write(
        feature_id="feature_001",
        artifact_type="build_result",
        payload={
            "node_name": "build",
            "stage": "build",
            "message": "failed build",
            "feature_id": "feature_001",
            "execution_mode": "supplied",
            "status": "failed",
            "command": ["dotnet", "build"],
            "exit_code": 1,
            "stdout_path": None,
            "stderr_path": None,
            "errors": [],
            "warnings": [],
            "duration_ms": 0,
            "error_class": "compile_error",
            "diagnostics": [],
            "repair_handoff": {},
            "expected_artifacts": [],
            "verified_artifacts": [],
            "artifact_verification": {},
            "real_build_performed": False,
            "claims_real_build_success": False,
        },
        status="blocked",
        upstream_refs=[dry_run_result],
    )
    repair_plan = store.write(
        feature_id="feature_001",
        artifact_type="repair_plan",
        payload={
            "node_name": "create_repair_plan",
            "stage": "repair_plan",
            "message": "repair",
            "repair_id": "repair_001",
            "feature_id": "feature_001",
            "failure_source": "build_result",
            "failure_class": "compile_error",
            "failure_evidence": {"summary": "compiler error"},
            "evidence_refs": [],
            "root_cause_hypotheses": [],
            "hypothesis": "compiler error",
            "recommended_fix_strategy": "repair scoped proposal",
            "minimal_changes": [],
            "retry_count": 1,
            "retry_budget": 1,
            "retry_budget_remaining": 0,
            "retry_exhausted": False,
            "scope_expansion_allowed": False,
            "stop_condition": "stop after repair",
            "forbidden_regressions": [],
            "requires_new_evidence": False,
            "allowed_next_stage": "generate_patch_proposal",
            "blockers": [],
        },
        upstream_refs=[build_result, patch_proposal_v1],
        exact_revision_upstream_types={"patch_proposal"},
    )

    store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload=patch_proposal_payload("proposal v2"),
        upstream_refs=[feature_spec, evidence_pack, implementation_plan],
    )

    envelope = store.read(repair_plan)
    patch_upstreams = [
        upstream
        for upstream in envelope["inputs"]["upstream_artifacts"]
        if upstream["artifact_type"] == "patch_proposal"
    ]
    assert patch_upstreams[0]["require_latest"] is False
    assert store.check_direct_freshness(repair_plan).status == "fresh"


def test_recursive_freshness_preserves_exact_revision_subgraph(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec_v1 = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack_v1 = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec_v1],
    )
    implementation_plan_v1 = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec_v1, evidence_pack_v1],
    )
    patch_proposal_v1 = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload={
            "node_name": "draft_patch_proposal",
            "stage": "patch_proposal",
            "message": "proposal v1",
            "proposal_id": "proposal_v1",
            "feature_id": "feature_001",
            "summary": "proposal v1",
            "files": [],
            "evidence_refs": [],
            "diff_intent": [],
            "change_units": [],
            "context_pack": {},
            "scope_boundary": {
                "allowed_files": [],
                "forbidden_files": [],
                "max_files_changed": 0,
            },
            "risk_assessment": {},
            "expected_tests": [],
            "no_op_status": {"is_no_op": False},
            "rollback_hints": [],
            "manual_review_notes": [],
            "blocked": False,
            "blockers": [],
        },
        upstream_refs=[feature_spec_v1, evidence_pack_v1, implementation_plan_v1],
    )
    build_result = store.write(
        feature_id="feature_001",
        artifact_type="build_result",
        payload={
            "node_name": "build",
            "stage": "build",
            "message": "failed build",
            "feature_id": "feature_001",
            "execution_mode": "supplied",
            "status": "failed",
            "command": ["dotnet", "build"],
            "exit_code": 1,
            "stdout_path": None,
            "stderr_path": None,
            "errors": [],
            "warnings": [],
            "duration_ms": 0,
            "error_class": "compile_error",
            "diagnostics": [],
            "repair_handoff": {},
            "expected_artifacts": [],
            "verified_artifacts": [],
            "artifact_verification": {},
            "real_build_performed": False,
            "claims_real_build_success": False,
        },
        status="blocked",
        upstream_refs=[
            store.write(
                feature_id="feature_001",
                artifact_type="dry_run_result",
                payload={
                    "node_name": "dry_run_apply",
                    "stage": "dry_run_apply",
                    "message": "dry run",
                },
                upstream_refs=[
                    patch_proposal_v1,
                    store.write(
                        feature_id="feature_001",
                        artifact_type="proposal_review",
                        payload={
                            "node_name": "review_proposal",
                            "stage": "proposal_review",
                            "message": "review",
                            "decision": "approve_dry_run",
                            "findings": [],
                            "required_changes": [],
                            "allowed_next_stage": "dry_run_apply",
                            "checked_rules": [],
                            "trace_metrics": {
                                "num_changes_checked": 1,
                                "num_blocking_findings": 0,
                            },
                        },
                        upstream_refs=[patch_proposal_v1],
                    ),
                ],
            )
        ],
    )
    repair_plan = store.write(
        feature_id="feature_001",
        artifact_type="repair_plan",
        payload={
            "node_name": "create_repair_plan",
            "stage": "repair_plan",
            "message": "repair",
            "repair_id": "repair_001",
            "feature_id": "feature_001",
            "failure_source": "build_result",
            "failure_class": "compile_error",
            "failure_evidence": {"summary": "compiler error"},
            "evidence_refs": [],
            "root_cause_hypotheses": [],
            "hypothesis": "compiler error",
            "recommended_fix_strategy": "repair scoped proposal",
            "minimal_changes": [],
            "retry_count": 1,
            "retry_budget": 1,
            "retry_budget_remaining": 0,
            "retry_exhausted": False,
            "scope_expansion_allowed": False,
            "stop_condition": "stop after repair",
            "forbidden_regressions": [],
            "requires_new_evidence": False,
            "allowed_next_stage": "generate_patch_proposal",
            "blockers": [],
        },
        upstream_refs=[build_result, patch_proposal_v1],
        exact_revision_upstream_types={"build_result", "patch_proposal"},
    )

    feature_payload_v2 = _feature_payload()
    feature_payload_v2["message"] = "feature v2"
    feature_spec_v2 = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=feature_payload_v2,
    )
    evidence_pack_v2 = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec_v2],
    )
    store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload=_implementation_payload(),
        upstream_refs=[feature_spec_v2, evidence_pack_v2],
    )

    freshness = store.check_freshness(repair_plan)
    assert freshness.status == "fresh", freshness.stale_reasons

    exact_feature_envelope = json.loads(
        Path(feature_spec_v1.path).read_text(encoding="utf-8")
    )
    exact_feature_envelope["data"]["message"] = "tampered exact revision"
    Path(feature_spec_v1.path).write_text(
        json.dumps(exact_feature_envelope),
        encoding="utf-8",
    )

    tampered_freshness = store.check_freshness(repair_plan)
    assert tampered_freshness.status == "stale"
    assert (
        "feature_spec invalid: Artifact content hash mismatch"
        in tampered_freshness.stale_reasons
    )


def test_exact_revision_freshness_ignores_latest_pointer_drift(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_v1 = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_v1 = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_v1],
    )
    feature_payload_v2 = _feature_payload()
    feature_payload_v2["message"] = "feature v2"
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=feature_payload_v2,
    )

    assert store.check_freshness(evidence_v1).status == "stale"
    exact = store.check_exact_revision_freshness(evidence_v1)
    assert exact.status == "fresh"
    assert exact.stale_reasons == []


def test_cross_feature_upstream_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )

    with pytest.raises(ArtifactStoreError, match="feature_id mismatch"):
        store.write(
            feature_id="feature_002",
            artifact_type="evidence_pack",
            payload=_evidence_payload(),
            upstream_refs=[feature_spec],
        )


def test_stale_upstream_rejected_on_write(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    evidence_pack = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload=_evidence_payload(),
        upstream_refs=[feature_spec],
    )
    changed_feature_spec = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_changed_feature_payload(),
    )

    with pytest.raises(StaleArtifactError, match="feature_spec hash changed"):
        store.write(
            feature_id="feature_001",
            artifact_type="implementation_plan",
            payload=_implementation_payload(),
            upstream_refs=[changed_feature_spec, evidence_pack],
        )


def test_exists_returns_false_for_missing_ref(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = ArtifactRef(
        feature_id="feature_001",
        artifact_type="feature_spec",
        path=str(tmp_path / "artifacts" / "features" / "feature_001" / "feature_spec.json"),
        artifact_hash="missing",
    )

    assert store.exists(ref) is False


def test_invalid_artifact_type_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStoreError, match="Invalid artifact_type"):
        store.write(
            feature_id="feature_001",
            artifact_type="../feature_spec",
            payload={},
        )


def test_path_traversal_blocked_on_feature_id(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStoreError, match="Invalid feature_id"):
        store.write(
            feature_id="../outside",
            artifact_type="feature_spec",
            payload={},
        )


def test_path_traversal_blocked_on_read(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = ArtifactRef(
        feature_id="feature_001",
        artifact_type="feature_spec",
        path=str(tmp_path / "outside.json"),
        artifact_hash="abc",
    )

    with pytest.raises(ArtifactStoreError, match="escape artifact root"):
        store.read(ref)


def test_hash_mismatch_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    tampered = ArtifactRef(
        feature_id=ref.feature_id,
        artifact_type=ref.artifact_type,
        path=ref.path,
        artifact_hash="wrong",
    )

    with pytest.raises(ArtifactStoreError, match="hash mismatch"):
        store.read(tampered)


def test_tampered_content_rejected_when_ref_hash_still_matches(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    path = Path(ref.path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["data"]["message"] = "tampered"
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ArtifactStoreError, match="content hash mismatch"):
        store.read(ref)


def test_unexpected_envelope_field_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    path = Path(ref.path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["metadata"] = {"source": "tampered"}
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ArtifactStoreError, match="unexpected fields"):
        store.read(ref)


def test_missing_envelope_field_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_payload(),
    )
    path = Path(ref.path)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    del envelope["trace_refs"]
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ArtifactStoreError, match="missing fields"):
        store.read(ref)
