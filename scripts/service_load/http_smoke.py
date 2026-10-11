"""Real HTTP / Redis / worker smoke; no mocked retrieval or generated success."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    assert not args.output.exists()
    token = os.environ["SERVICE_API_TOKEN"]
    records = []

    def call(method, path, body=None, key=None, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + token
        if key:
            headers["Idempotency-Key"] = key
        request = Request(args.url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method=method)
        start = time.monotonic()
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            response = error
        raw = response.read().decode()
        assert token not in raw, "Response exposed authentication token"
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        return {"status": response.status, "body": value, "elapsed_seconds": time.monotonic() - start}

    def retain(name, value, passed):
        records.append({"check": name, "passed": bool(passed), "response": value})

    payload = {"kind": "query", "payload": {"query": "BM25Indexer inverted postings IDF",
        "collection": "service_load", "top_k": 5, "answer": False, "rewrite": False, "rerank": False},
        "timeout_seconds": 60.0}
    key = "http-smoke-" + uuid4().hex
    try:
        row = call("GET", "/health"); retain("real_redis_health", row, row["status"] == 200)
        row = call("POST", "/v1/jobs", payload, key, auth=False)
        retain("unauthorized_rejected", row, row["status"] == 401)
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: call("POST", "/v1/jobs", payload, key), range(8)))
        ids = {r["body"]["job"]["id"] for r in responses if r["status"] in {200, 202}}
        retain("concurrent_idempotency", responses,
               len(ids) == 1 and sum(r["body"].get("created") is True for r in responses) == 1
               and all(r["status"] in {200, 202} for r in responses))
        job_id = next(iter(ids))
        altered = {**payload, "payload": {**payload["payload"], "query": "different request"}}
        row = call("POST", "/v1/jobs", altered, key)
        retain("idempotency_conflict", row, row["status"] == 409)

        def wait(job):
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                row = call("GET", "/v1/jobs/" + job)
                if row["body"].get("state") in {"completed", "failed", "timed_out", "indeterminate", "cancelled"}:
                    return row
                time.sleep(0.1)
            raise TimeoutError("Job did not reach a terminal state")

        row = wait(job_id)
        result = row["body"].get("result") or {}
        good = (row["body"]["state"] == "completed" and result.get("status") == "completed"
                and any(x.get("metadata", {}).get("source_path") == "src/ingestion/storage/bm25_indexer.py"
                        for x in result.get("results", [])))
        retain("actual_query_completion_and_expected_source", row, good)
        second = call("POST", "/v1/jobs", payload, key + "-cache")
        row = wait(second["body"]["job"]["id"])
        retain("redis_cache_between_independent_jobs", row,
               second["body"]["job"]["id"] != job_id and row["body"].get("result", {}).get("cache", {}).get("result") == "hit")
        row = call("GET", "/v1/jobs/not-an-id"); retain("invalid_job_id", row, row["status"] == 404)
        row = call("GET", "/metrics")
        retain("prometheus_queue_and_bounded_labels", row,
               row["status"] == 200 and "service_jobs_completed_total" in row["body"] and job_id not in row["body"])
    except Exception as error:
        records.append({"check": "execution", "passed": False, "error_type": type(error).__name__, "message": str(error)})
    finally:
        value = {"scope": "Real HTTP, Redis, worker subprocess and BM25/Chroma; no model or game",
                 "passed": all(r["passed"] for r in records), "checks": records}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"passed": value["passed"], "checks": len(records), "output": str(args.output)}))
    return 0 if value["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
