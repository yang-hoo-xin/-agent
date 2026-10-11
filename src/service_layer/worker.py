"""Leased Redis jobs, one bounded isolated backend process per attempt."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from src.service_layer.execute import REPO, execute_process, reference, save


def backend_configuration(config):
    """Only server-owned routing/storage settings; credentials travel in child env."""
    return {"namespace": config.namespace, "work_root": str(config.work_root),
            "settings_path": str(config.settings_path),
            "agent_profiles": {key: str(value) for key, value in config.agent_profiles.items()},
            "query_cache_ttl": config.query_cache_ttl}


class LeaseHeartbeat:
    def __init__(self, store, job, lease_seconds):
        self.store, self.job, self.lease_seconds = store, job, lease_seconds
        self.stopped, self.lost = threading.Event(), threading.Event()
        self.error_type = None
        self.thread = threading.Thread(target=self._run, name="service-lease-heartbeat", daemon=True)

    def _run(self):
        interval = max(0.05, min(5.0, self.lease_seconds / 3))
        while not self.stopped.wait(interval):
            try:
                owned = self.store.heartbeat(self.job["id"], self.job["lease_token"], self.lease_seconds)
                if owned is not True:
                    self.lost.set()
                    return
            except Exception as error:
                # 为什么要有它：Redis故障不能当作仍持有租约；原进程仍受绝对deadline约束，但不能发布晚到结果。
                self.error_type = type(error).__name__
                self.lost.set()
                return

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        self.thread.join(timeout=max(1.0, self.lease_seconds))
        if self.thread.is_alive():
            self.lost.set()


def _attempt_directory(config, job):
    if not isinstance(job.get("id"), str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", job["id"]) is None:
        raise ValueError("SERVICE_JOB_ID_INVALID")
    if type(job.get("attempt")) is not int or job["attempt"] < 1:
        raise ValueError("SERVICE_ATTEMPT_INVALID")
    root = Path(config.work_root).resolve()
    path = root / "jobs" / job["id"] / (str(job["attempt"]) + "-" + uuid4().hex[:12])
    if not path.resolve().is_relative_to(root):
        raise ValueError("SERVICE_ATTEMPT_PATH_ESCAPE")
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    return path


def run_once(store, config, *, worker_id, runner=execute_process):
    claimed_at = time.monotonic()
    job = store.claim(worker_id, config.lease_seconds)
    if job is None:
        return False
    path = _attempt_directory(config, job)
    timeout = job.get("timeout_seconds")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("SERVICE_JOB_TIMEOUT_INVALID")
    timeout = min(timeout, config.max_job_seconds)
    deadline = claimed_at + timeout
    request = {"schema": "service-attempt-request.v1", "job": {
        "id": job["id"], "kind": job["kind"], "payload": job["payload"],
        "attempt": job["attempt"], "timeout_seconds": timeout}, "server_config": backend_configuration(config)}
    request_ref = save(path / "request.json", request)
    result_path = path / "result.json"
    environment = os.environ.copy()
    environment.pop("SERVICE_API_TOKEN", None)
    environment["SERVICE_CHILD_REDIS_URL"] = config.redis_url
    command = [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).with_name("execute.py").resolve()),
               "--request", str(path / "request.json"), "--result", str(result_path)]
    heartbeat = LeaseHeartbeat(store, job, config.lease_seconds)
    heartbeat.start()
    evidence = {"schema": "service-attempt-evidence.v1", "job_id": job["id"], "attempt": job["attempt"],
                "request_ref": request_ref, "command": command, "deadline_monotonic": deadline,
                "publication": "not_attempted", "local_process_cancel_on_lease_loss": True}
    envelope = None
    publication_attempted = False
    try:
        # Leave a small bounded margin for durable terminal publication; never refresh the original deadline.
        process = runner(command, cwd=REPO, output=path / "process", deadline=deadline-min(1.0, timeout*0.05),
                         environment=environment, cancel_event=heartbeat.lost)
        evidence["process"] = process
        heartbeat.stop()
        if result_path.is_file():
            envelope = json.loads(result_path.read_bytes())
            if (not isinstance(envelope, dict) or envelope.get("schema") != "service-attempt-result.v1"
                    or envelope.get("job_id") != job["id"] or envelope.get("attempt") != job["attempt"]
                    or type(envelope.get("ok")) is not bool or type(envelope.get("safe_retry")) is not bool
                    or envelope.get("ok") is True and not isinstance(envelope.get("result"), dict)):
                raise ValueError("SERVICE_CHILD_RESULT_BINDING_INVALID")
            evidence["result_ref"] = reference(result_path)
        if process.get("timeout") or process.get("status") == "deadline_exhausted_before_start":
            state = "indeterminate" if job["kind"] == "agent" else "timed_out"
            error = {"code": "JOB_DEADLINE_EXCEEDED", "provider_server_state": "unknown"}
        elif (process.get("status") == "infrastructure_failed" or process.get("cancelled")
              or process.get("exit_code") != 0 or envelope is None):
            state = "indeterminate" if job["kind"] == "agent" else "failed"
            error = {"code": "CHILD_PROCESS_RESULT_UNAVAILABLE", "cost_unknown": True}
        elif envelope["ok"]:
            state, error = "completed", None
        else:
            state = "indeterminate" if job["kind"] == "agent" and envelope.get("execution_state") != "not_started" else "failed"
            error = envelope.get("error") or {"code": "BACKEND_EXECUTION_FAILED"}
        if heartbeat.lost.is_set():
            evidence.update(publication="suppressed_lease_lost", heartbeat_error_type=heartbeat.error_type)
        else:
            # 为什么要有它：租约失效后结果只留在原attempt证据，Redis的token fence决定是否允许发布，不能复写新owner结果。
            safe_retry = (job["kind"] == "query" and envelope is not None and envelope.get("safe_retry") is True
                          and process.get("exit_code") == 0 and not process.get("timeout") and envelope.get("ok") is False
                          and envelope.get("execution_state") == "not_started" and isinstance(error, dict)
                          and error.get("code") == "QUERY_CACHE_UNAVAILABLE_BEFORE_EXECUTION")
            if safe_retry:
                publication_attempted = True
                published = store.retry(job["id"], job["lease_token"], error, config.retry_delay_seconds)
            else:
                publication_attempted = True
                published = store.finish(job["id"], job["lease_token"], state,
                                         result=envelope.get("result") if state == "completed" else None, error=error)
            evidence.update(publication="accepted" if published is True else "suppressed_fence_rejected",
                            requested_state="retry" if safe_retry else state)
    except Exception as error:
        evidence.update(error_type=type(error).__name__)
        if publication_attempted:
            # 为什么要有它：Redis回复丢失时首次写入可能已成功，不能再用不确定终态覆盖这次结果或触发第二次重排。
            evidence.update(publication="store_response_unknown", publication_error_type=type(error).__name__)
        elif not heartbeat.lost.is_set():
            try:
                published = store.finish(job["id"], job["lease_token"], "indeterminate" if job["kind"] == "agent" else "failed",
                    error={"code": "WORKER_ATTEMPT_UNCERTAIN", "type": type(error).__name__, "cost_unknown": True})
                evidence["publication"] = "accepted_uncertain" if published is True else "suppressed_fence_rejected"
            except Exception as publication_error:
                evidence.update(publication="store_unavailable", publication_error_type=type(publication_error).__name__)
    finally:
        heartbeat.stop()
        evidence["lease_lost"] = heartbeat.lost.is_set()
        save(path / "attempt.json", evidence)
    return True


def main(argv=None):
    import redis

    from src.service_layer.config import ServiceConfig
    from src.service_layer.store import RedisJobStore

    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--worker-id", default=socket.gethostname() + ":" + str(os.getpid()) + ":" + uuid4().hex[:8])
    args = parser.parse_args(argv)
    config = ServiceConfig.from_env()
    client = redis.Redis.from_url(config.redis_url, socket_connect_timeout=3, socket_timeout=3)
    store = RedisJobStore(client, namespace=config.namespace, retention_seconds=config.retention_seconds,
                         max_pending=config.max_pending)
    failures = 0
    while True:
        try:
            store.recover_expired()
            worked = run_once(store, config, worker_id=args.worker_id)
        except redis.RedisError as error:
            # 为什么要有它：连接暂断不能终止常驻worker；只重试队列轮询，未知Agent仍由原租约恢复规则终结，不能本地重新派发。
            transient = (isinstance(error, (redis.ConnectionError, redis.TimeoutError,
                                           redis.exceptions.BusyLoadingError))
                         and not isinstance(error, redis.exceptions.AuthenticationError))
            retry = transient and not args.once
            failures = min(failures + 1, 16)
            delay = min(30.0, max(config.poll_seconds, config.retry_delay_seconds) * 2 ** (failures-1))
            # 为什么要有它：Redis异常文本可能包含连接URL/密码；诊断只保存类型、是否续试和退避时间，不打印原异常。
            print(json.dumps({"event":"worker_store_unavailable", "error_type":type(error).__name__,
                "retry":retry, "retry_delay_seconds":delay if retry else None}), file=sys.stderr, flush=True)
            if not retry:
                return 2
            time.sleep(delay)
            continue
        failures = 0
        if args.once:
            return 0
        if not worked:
            time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
