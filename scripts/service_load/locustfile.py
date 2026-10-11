"""Run one explicit workload per invocation; token comes only from environment."""
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from gevent import sleep
from locust import HttpUser, constant, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))
from protocol import operation

_stream = None
_run_id = None


def record(row):
    _stream.write(json.dumps({"schema": "service-load-sample.v1", "run_id": _run_id, **row}, ensure_ascii=False, allow_nan=False) + "\n")
    _stream.flush()


@events.test_start.add_listener
def start(environment, **kwargs):
    global _stream, _run_id
    if not os.environ.get("SERVICE_API_TOKEN"):
        raise ValueError("SERVICE_API_TOKEN is required")
    _run_id = os.environ.get("SERVICE_LOAD_RUN_ID") or uuid4().hex
    if not _run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in _run_id):
        raise ValueError("Run id must be a simple label")
    folder = Path(os.environ.get("SERVICE_LOAD_OUTPUT", "artifacts/service-load"))
    folder.mkdir(parents=True, exist_ok=True)
    _stream = (folder / f"{_run_id}.{os.getpid()}.jsonl").open("x", encoding="utf-8")
    record({"event": "run_start", "at": time.time(), "mode": os.environ.get("SERVICE_LOAD_MODE", "unique"),
        "scope": "Closed-loop HTTP async BM25 query jobs, no answer/rewrite/dense/rerank models; includes child startup, queue, polling and raw sample writing overhead",
        "pid": os.getpid(), "users": getattr(environment.parsed_options, "num_users", None),
        "poll_interval": float(os.environ.get("SERVICE_LOAD_POLL_SECONDS", ".1")),
        "operation_timeout": float(os.environ.get("SERVICE_LOAD_TIMEOUT", "90"))})


@events.test_stop.add_listener
def stop(environment, **kwargs):
    if _stream is not None:
        record({"event": "run_stop", "at": time.time()})


class SparseQueryUser(HttpUser):
    wait_time = constant(0)

    def on_start(self):
        self.mode = os.environ.get("SERVICE_LOAD_MODE", "unique")
        fixture = json.loads(Path(os.environ["SERVICE_LOAD_QUERIES"]).read_bytes())
        self.collection, self.queries = fixture["collection"], fixture["queries"]
        self.position = 0
        self.client.headers.update({"Authorization": "Bearer " + os.environ["SERVICE_API_TOKEN"]})

    def transport(self, method, path, body, key, timeout):
        headers = {"Idempotency-Key": key} if key else {}
        with self.client.request(method, path, json=body, headers=headers, timeout=timeout,
                name="submit" if method == "POST" else "poll", catch_response=True) as response:
            try:
                value = response.json()
            except ValueError:
                response.failure("Invalid JSON response")
                raise ValueError("Invalid JSON response") from None
            return response.status_code, value

    @task
    def query(self):
        item = self.queries[self.position % len(self.queries)]
        self.position += 1
        row = operation(self.transport, record, mode=self.mode, query=item["query"], collection=self.collection,
            expected_source=item["expected_source"], timeout=float(os.environ.get("SERVICE_LOAD_TIMEOUT", "90")),
            poll_interval=float(os.environ.get("SERVICE_LOAD_POLL_SECONDS", ".1")), sleep=sleep)
        self.environment.events.request.fire(request_type="JOB", name=self.mode, response_time=row["elapsed_ms"],
            response_length=0, exception=None if row["outcome"] == "completed" else RuntimeError(row["outcome"]),
            context={"job_id": row["job_id"], "outcome": row["outcome"]})
