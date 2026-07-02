"""Tests for the Phase A artifact store."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    StaleArtifactError,
)


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
    assert Path(ref.path).parent.name == "feature_001"


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
