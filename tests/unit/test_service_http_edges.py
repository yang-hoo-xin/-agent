"""Real ASGI transport counterexamples with a queue double, not Redis load tests.

为什么要有它：入站拒绝本身必须可序列化，HTTP或作业完成也不能冒充领域任务已交付。
"""
from __future__ import annotations

import pytest
import redis
from fastapi.testclient import TestClient

from src.service_layer.api import create_app
from src.service_layer.config import ServiceConfig
from tests.unit.test_service_http_api import HEADERS, Store


@pytest.fixture
def edge_client(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text("query: {}\n", encoding="utf-8")
    profile = tmp_path / "profile.json"
    profile.write_text('{"arguments": []}', encoding="utf-8")
    store = Store()
    config = ServiceConfig(settings_path=settings, work_root=tmp_path / "jobs",
                           agent_profiles={"registered": profile}, api_token="unit-test-only")
    with TestClient(create_app(config, store=store), raise_server_exceptions=False) as client:
        yield client, store


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("location", ["timeout", "filter"])
def test_nonfinite_json_is_client_error_not_server_failure(edge_client, literal, location):
    client, store = edge_client
    body = ('{"kind":"query","payload":{"query":"hello"},"timeout_seconds":' + literal + '}') if location == "timeout" else (
        '{"kind":"query","payload":{"query":"hello","filters":{"value":' + literal + '}}}')
    response = client.post("/v1/jobs", headers={**HEADERS, "Content-Type": "application/json"}, content=body.encode())
    assert response.status_code in {400, 422}, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), dict)
    assert not store.calls


@pytest.mark.parametrize("escaped", [r"\ud800", r"\udfff"])
def test_lone_surrogate_is_rejected_without_breaking_error_response(edge_client, escaped):
    client, store = edge_client
    body = ('{"kind":"query","payload":{"query":"' + escaped + '"}}').encode()
    response = client.post("/v1/jobs", headers={**HEADERS, "Content-Type": "application/json"}, content=body)
    assert response.status_code in {400, 422}, response.text
    assert isinstance(response.json(), dict)
    assert not store.calls


def test_valid_chinese_and_astral_character_are_still_accepted(edge_client):
    client, store = edge_client
    text = "请解释这段代码 🚀"
    response = client.post("/v1/jobs", headers=HEADERS, json={"kind": "query", "payload": {"query": text}})
    assert response.status_code == 202
    assert store.calls[0][1]["query"] == text


def test_completed_job_preserves_domain_non_delivery(edge_client):
    client, store = edge_client
    store.get = lambda job_id: {"id": job_id, "kind": "agent", "state": "completed", "lease_token": "PRIVATE_LEASE",
                               "result": {"status": "partial", "delivery_complete": False, "runtime_status": "not_executed"}}
    response = client.get("/v1/jobs/" + "a" * 32, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert body["result"] == {"status": "partial", "delivery_complete": False, "runtime_status": "not_executed"}
    assert "lease_token" not in body and "PRIVATE_LEASE" not in response.text


def test_status_redis_failure_is_safe_503(edge_client):
    client, store = edge_client
    def broken(job_id):
        raise redis.ConnectionError("FAKE_PASSWORD_DO_NOT_ECHO")
    store.get = broken
    response = client.get("/v1/jobs/" + "a" * 32, headers=HEADERS)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert "FAKE_PASSWORD_DO_NOT_ECHO" not in response.text


def test_metrics_use_route_templates_not_job_identifiers(edge_client):
    client, _ = edge_client
    marker = "f" * 32
    assert client.get("/v1/jobs/" + marker, headers=HEADERS).status_code == 404
    assert client.get("/unregistered-private-marker").status_code == 404
    text = client.get("/metrics").text
    assert 'route="/v1/jobs/{job_id}"' in text
    assert 'route="unmatched"' in text
    assert marker not in text and "unregistered-private-marker" not in text
