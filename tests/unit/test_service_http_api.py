"""Transport contract checks; these do not substitute for Redis or business runs."""
import hashlib
from types import SimpleNamespace

import pytest
import redis
from fastapi.testclient import TestClient

from src.service_layer.api import create_app
from src.service_layer.config import ServiceConfig
from src.service_layer.store import IdempotencyConflict, QueueFull


class Store:
    def __init__(self):
        self.client = SimpleNamespace(ping=lambda: True)
        self.calls = []
        self.error = None
        self.allowed = True

    def rate_limit(self, *args):
        return self.allowed, 2

    def submit(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        return {"id": "a" * 32, "kind": args[0], "state": "queued", "lease_token": "private-token",
                "payload": args[1]}, True

    def get(self, job_id):
        return None

    def metrics(self):
        return {"queued": 1, "running": 0, "counters": {"completed": 3, "duplicate_submits": 2}, "user_query": "PRIVATE_CONTENT"}


@pytest.fixture
def client(tmp_path):
    settings = tmp_path / "settings.yaml"
    settings.write_text("query: {}\n", encoding="utf-8")
    profile = tmp_path / "profile.json"
    profile.write_text('{"arguments": []}', encoding="utf-8")
    store = Store()
    config = ServiceConfig(settings_path=settings, work_root=tmp_path / "jobs",
                           agent_profiles={"registered": profile}, api_token="unit-test-only")
    with TestClient(create_app(config, store=store)) as http:
        yield http, store, config


HEADERS = {"Authorization": "Bearer unit-test-only", "Idempotency-Key": "one-request"}


def test_submit_binds_config_and_does_not_expose_internal_fields(client):
    http, store, config = client
    response = http.post("/v1/jobs", headers=HEADERS, json={"kind": "query", "payload": {"query": "JSON arrays"}})
    assert response.status_code == 202
    assert response.headers["location"] == "/v1/jobs/" + "a" * 32
    assert store.calls[0][1]["_settings_sha256"] == hashlib.sha256(config.settings_path.read_bytes()).hexdigest()
    assert "lease_token" not in response.json()["job"] and "payload" not in response.json()["job"]


def test_unauthorized_request_never_enters_queue(client):
    http, store, _ = client
    assert http.post("/v1/jobs", headers={"Idempotency-Key": "one"},
                     json={"kind": "query", "payload": {"query": "x"}}).status_code == 401
    assert not store.calls


@pytest.mark.parametrize("payload", [
    {"profile_id": "unknown", "description": "fix"},
    {"profile_id": "registered", "description": "fix", "execution_config": "C:/private/config"},
    {"profile_id": "registered", "description": "fix", "product_executor": "run"},
])
def test_only_registered_profile_identity_can_be_submitted(client, payload):
    http, store, _ = client
    assert http.post("/v1/jobs", headers=HEADERS, json={"kind": "agent", "payload": payload}).status_code == 422
    assert not store.calls


def test_agent_profile_is_bound_at_admission(client):
    http, store, config = client
    assert http.post("/v1/jobs", headers=HEADERS,
                     json={"kind": "agent", "payload": {"profile_id": "registered", "description": "fix"}}).status_code == 202
    assert store.calls[0][1]["_profile_sha256"] == hashlib.sha256(config.agent_profiles["registered"].read_bytes()).hexdigest()


@pytest.mark.parametrize("change", [{"timeout_seconds": True}, {"timeout_seconds": -1},
                                   {"timeout_seconds": 601}, {"max_attempts": 4}])
def test_invalid_or_excessive_budget_rejected_before_submit(client, change):
    http, store, _ = client
    body = {"kind": "query", "payload": {"query": "x"}, **change}
    assert http.post("/v1/jobs", headers=HEADERS, json=body).status_code == 422
    assert not store.calls


def test_agent_cannot_enable_automatic_retry(client):
    http, store, _ = client
    assert http.post("/v1/jobs", headers=HEADERS, json={"kind": "agent", "max_attempts": 2,
                     "payload": {"profile_id": "registered", "description": "fix"}}).status_code == 422
    assert not store.calls


@pytest.mark.parametrize("error,status", [(IdempotencyConflict("conflict"), 409),
                                          (QueueFull("full"), 429), (redis.ConnectionError("secret"), 503)])
def test_store_failures_are_not_reported_as_accepted(client, error, status):
    http, store, _ = client
    store.error = error
    response = http.post("/v1/jobs", headers=HEADERS, json={"kind": "query", "payload": {"query": "x"}})
    assert response.status_code == status
    assert "secret" not in response.text


def test_rate_limit_has_retry_after_and_does_not_enqueue(client):
    http, store, _ = client
    store.allowed = False
    response = http.post("/v1/jobs", headers=HEADERS, json={"kind": "query", "payload": {"query": "x"}})
    assert response.status_code == 429 and response.headers["retry-after"] == "2"
    assert not store.calls


def test_large_body_rejected_and_metrics_omit_arbitrary_values(client):
    http, store, _ = client
    response = http.post("/v1/jobs", headers={**HEADERS, "Content-Type": "application/json"}, content=b"x" * 70001)
    assert response.status_code == 413 and not store.calls
    text = http.get("/metrics").text
    assert "service_jobs_queued 1" in text and "PRIVATE_CONTENT" not in text and "unit-test-only" not in text
    assert "service_jobs_completed_total 3" in text
    assert "service_jobs_idempotency_hits_total 2" in text


@pytest.mark.parametrize("name,value", [("max_job_seconds", float("nan")), ("lease_seconds", float("inf")),
                                        ("poll_seconds", True), ("retention_seconds", 0)])
def test_nonfinite_or_bool_configuration_rejected(name, value):
    with pytest.raises(ValueError):
        ServiceConfig(**{name: value})
