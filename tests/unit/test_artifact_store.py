"""Tests for the Phase A artifact store."""

from __future__ import annotations

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
        "evidence_source_paths": [],
        "target_files": [],
        "target_symbols": [],
        "evidence_refs": [],
        "proposed_changes": [],
        "side_effect_boundaries": [],
        "test_plan": [],
        "rollback_plan": [],
        "open_questions": [],
        "blocking": False,
        "blockers": [],
    }


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
    assert Path(ref.path).parent.parent.name == "revisions"
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
        tmp_path / "artifacts" / "features" / "feature_001" / "pending_writes"
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
        tmp_path / "artifacts" / "features" / "feature_001" / "pending_writes"
    )
    pending_markers = list(pending_dir.rglob("*.json"))
    assert len(pending_markers) == 1
    revision_files = list(
        (
            tmp_path
            / "artifacts"
            / "features"
            / "feature_001"
            / "revisions"
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
        }
    ]


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
