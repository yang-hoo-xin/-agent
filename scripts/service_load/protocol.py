"""Measured asynchronous-query flow, independent of the load generator."""
import hashlib
import json
import time
from uuid import uuid4

TERMINAL = {"completed", "failed", "timed_out", "indeterminate", "cancelled"}


def operation(transport, record, *, mode, query, collection, expected_source, timeout=90.0,
              poll_interval=0.1, sleep=time.sleep, clock=time.monotonic, wall=time.time):
    """transport(method, path, body, key, timeout) -> (HTTP status, JSON value).

    Poll waits implement the HTTP protocol; the server always executes real retrieval.
    """
    if mode not in {"unique", "cache", "idempotency"}:
        raise ValueError("Unknown workload mode")
    if timeout <= 0 or poll_interval <= 0:
        raise ValueError("Positive timeout and poll interval required")
    operation_id = uuid4().hex
    query_text = query + " requestnonce" + operation_id if mode == "unique" else query
    body = {"kind": "query", "payload": {"query": query_text, "collection": collection, "top_k": 5,
        "answer": False, "rewrite": False, "rerank": False, "request_id": operation_id},
        "timeout_seconds": float(timeout), "max_attempts": 1}
    start, start_wall = clock(), wall()
    record({"event": "operation_start", "operation_id": operation_id, "mode": mode, "at": start_wall,
        "query_sha256": hashlib.sha256(query_text.encode()).hexdigest(), "expected_source": expected_source})
    result = {"event": "operation_end", "operation_id": operation_id, "mode": mode, "started_at": start_wall,
        "job_id": None, "created": None, "outcome": "interrupted", "poll_count": 0, "duplicate_verified": None}

    def request(method, path, key=None):
        remaining = timeout - (clock() - start)
        if remaining <= 0:
            raise TimeoutError("CLIENT_OBSERVATION_TIMEOUT")
        before, before_wall = clock(), wall()
        status, data, error = None, None, None
        try:
            status, data = transport(method, path, body if method == "POST" else None, key, min(15.0, remaining))
            return status, data
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            record({"event": "http", "operation_id": operation_id, "mode": mode, "method": method,
                "route": "/v1/jobs" if method == "POST" else "/v1/jobs/{job_id}", "at": before_wall,
                "elapsed_ms": (clock()-before)*1000, "status": status, "error_type": error,
                "created": data.get("created") if isinstance(data, dict) and method == "POST" else None})

    try:
        status, admitted = request("POST", "/v1/jobs", operation_id)
        if status not in {200, 202}:
            result.update(outcome="admission_rejected", admission_status=status)
            return result
        job = admitted["job"]
        result.update(job_id=job["id"], created=admitted.get("created"), admission_status=status)
        if mode == "idempotency":
            status2, replay = request("POST", "/v1/jobs", operation_id)
            same = status2 == 200 and replay.get("created") is False and replay.get("job", {}).get("id") == job["id"]
            result["duplicate_verified"] = same
            if not same:
                result.update(outcome="idempotency_failed", replay_status=status2)
                return result
        while job.get("state") not in TERMINAL:
            remaining = timeout - (clock()-start)
            if remaining <= 0:
                raise TimeoutError("CLIENT_OBSERVATION_TIMEOUT")
            sleep(min(poll_interval, remaining))
            status, job = request("GET", "/v1/jobs/" + result["job_id"])
            result["poll_count"] += 1
            if status != 200:
                result.update(outcome="poll_failed", poll_status=status)
                return result
        domain = job.get("result") or {}
        found = any(row.get("metadata", {}).get("source_path") == expected_source for row in domain.get("results", []))
        usage = domain.get("usage", {})
        no_model = usage.get("answer_transport_calls") == 0 and usage.get("rewrite_transport_calls") == 0
        valid = job["state"] == "completed" and domain.get("status") == "completed" and found and no_model
        result.update(outcome="completed" if valid else "domain_failed", job_state=job["state"],
            domain_status=domain.get("status"), expected_source_found=found, no_answer_or_rewrite_calls=no_model,
            cache_result=domain.get("cache", {}).get("result"), cache_binding_available=domain.get("cache", {}).get("binding_available"),
            job_created_at=job.get("created_at"), job_started_at=job.get("started_at"), job_finished_at=job.get("finished_at"),
            attempt=job.get("attempt"), domain_result=domain, job_error=job.get("error"))
        if job["state"] == "timed_out" or domain.get("status") == "timed_out":
            result["outcome"] = "server_timed_out"
        return result
    except TimeoutError:
        result["outcome"] = "client_observation_timeout"
        return result
    except Exception as exc:
        result.update(outcome="transport_or_protocol_failed", error_type=type(exc).__name__)
        return result
    finally:
        # 为什么要有它：Locust停止时中断的任务仍计入原始样本，不能只保留完成者造成幸存者偏差。
        result.update(finished_at=wall(), elapsed_ms=(clock()-start)*1000)
        record(result)
