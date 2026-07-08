"""Tests for read-only controlled-agent HTTP API routing."""

from __future__ import annotations

import pytest

from src.mod_agent.api import ModAgentHttpApi
from src.mod_agent.api.http_server import _resolve_artifact_root
from src.mod_agent.artifacts import ArtifactStore, ArtifactStoreError


def test_http_api_health_and_empty_feature_list(tmp_path) -> None:
    api = ModAgentHttpApi(ArtifactStore(tmp_path / "artifacts"))

    health = api.handle_get("/health")
    features = api.handle_get("/features")

    assert health.status_code == 200
    assert health.payload == {
        "status": "ok",
        "service": "mod_agent_http_api",
        "mode": "read_only",
        "deployment": "local_dev_only",
    }
    assert features.status_code == 200
    assert features.payload == {"features": []}


def test_http_api_lists_artifacts_and_dashboard_projection(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_spec_payload(),
    )
    api = ModAgentHttpApi(store)

    features = api.handle_get("/features")
    artifacts = api.handle_get("/features/feature_001/artifacts")
    dashboard = api.handle_get("/features/feature_001/dashboard")
    status = api.handle_get("/features/feature_001/status")

    assert features.payload == {"features": ["feature_001"]}
    assert artifacts.status_code == 200
    assert artifacts.payload["feature_id"] == "feature_001"
    assert artifacts.payload["artifacts"][0]["artifact_type"] == "feature_spec"
    assert dashboard.status_code == 200
    assert dashboard.payload["feature_id"] == "feature_001"
    assert dashboard.payload["artifacts"][0]["artifact_type"] == "feature_spec"
    assert status.status_code == 200
    assert status.payload["feature_id"] == "feature_001"
    assert status.payload["status"] == "available"
    assert "workflow" in status.payload


def test_http_api_blocks_dangerous_post_with_required_approval(tmp_path) -> None:
    api = ModAgentHttpApi(ArtifactStore(tmp_path / "artifacts"))

    response = api.handle_post("/run_external_game")

    assert response.status_code == 403
    assert response.payload["error"] == "required_approval"
    assert response.payload["required_approval"] is True
    assert response.payload["route"] == "/run_external_game"


def test_http_api_rejects_unknown_route(tmp_path) -> None:
    api = ModAgentHttpApi(ArtifactStore(tmp_path / "artifacts"))

    response = api.handle_get("/unknown")

    assert response.status_code == 404
    assert response.payload["error"] == "not_found"


def test_http_api_artifact_root_rejects_absolute_path_without_opt_in(tmp_path) -> None:
    with pytest.raises(ArtifactStoreError, match="allow_absolute_artifact_root"):
        _resolve_artifact_root(tmp_path)

    assert _resolve_artifact_root(
        tmp_path,
        allow_absolute_artifact_root=True,
    ) == tmp_path.resolve()


def _feature_spec_payload() -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "feature spec ready",
        "feature_id": "feature_001",
        "user_request": "Enable diagnostics",
        "target_behavior": "Enable diagnostics",
        "non_goals": [],
        "target_mod": "BetterHitFeedback",
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }
