"""Fixed-file subprocess backend and bounded process execution for service workers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
    return reference(path)


def execute_process(argv, *, cwd, output, deadline, environment=None, cancel_event=None):
    # 为什么要有它：失租后旧owner必须及时停止其自有进程树，不能仅拒发结果而允许工具一直运行到原deadline。
    if cancel_event is not None and cancel_event.is_set():
        return {"status": "cancelled_before_start", "started": False, "cancelled": True, "timeout": False}
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"status": "deadline_exhausted_before_start", "started": False}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    process, job = None, None
    started = time.monotonic()
    result = {"argv": argv, "cwd": str(cwd), "started_at": datetime.now(timezone.utc).isoformat(),
              "started": False, "timeout": False, "cancelled": False}
    try:
        if os.name == "nt":
            from scripts.run_benchmark_arm import WindowsJob
            job = WindowsJob()
        with (output / "stdout.bin").open("xb") as stdout, (output / "stderr.bin").open("xb") as stderr:
            options = ({"creationflags": subprocess.CREATE_NO_WINDOW | 0x00000004}
                       if job is not None else {"start_new_session": True})
            process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       env=environment, **options)
            if job is not None:
                job.start(process)
            result.update(started=True, process_id=process.pid,
                          process_tree_ownership="Windows Job Object" if job is not None else "POSIX process group")
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    result["cancelled"] = True
                    break
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    result["timeout"] = True
                    break
                try:
                    process.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    pass
            if result["cancelled"] or result["timeout"]:
                if job is not None:
                    job.terminate()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait(timeout=10)
            result["exit_code"] = process.returncode
    except Exception as error:
        result.update(status="infrastructure_failed", error_type=type(error).__name__)
    finally:
        if process is not None and job is None:
            # 为什么要有它：同一作业的工具后代不能在父进程返回后继续产生副作用；仅清理本次创建的进程组。
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as error:
                result.update(status="infrastructure_failed", cleanup_error_type=type(error).__name__)
        if job is not None:
            job.close()
        if process is not None and process.poll() is None:
            # Assignment/resume can fail before the child belongs to the Job Object.
            process.kill()
            process.wait(timeout=10)
    result.update(status=result.get("status", "cancelled" if result["cancelled"] else "timed_out" if result["timeout"] else "exited"),
                  finished_at=datetime.now(timezone.utc).isoformat(), wall_seconds=time.monotonic()-started,
                  stdout_ref=reference(output / "stdout.bin") if (output / "stdout.bin").exists() else None,
                  stderr_ref=reference(output / "stderr.bin") if (output / "stderr.bin").exists() else None,
                  owned_process_tree_cleanup="unknown" if result.get("cleanup_error_type") else
                  "job_closed_kill_on_close" if job is not None else "owned_process_group_terminated" if process is not None else "no_process_created",
                  provider_server_state="not_established_by_client_process_cleanup")
    save(output / "process.json", result)
    return result


def execute_request(request_path, result_path):
    from src.service_layer.backends import BackendError, public_result, run_agent, run_query

    request = json.loads(Path(request_path).read_bytes())
    if set(request) != {"schema", "job", "server_config"} or request["schema"] != "service-attempt-request.v1":
        raise ValueError("SERVICE_REQUEST_SCHEMA_INVALID")
    job, server = request["job"], request["server_config"]
    config = SimpleNamespace(**server, redis_url=os.environ.get("SERVICE_CHILD_REDIS_URL", ""))
    known_secrets = [config.redis_url]
    if config.redis_url:
        known_secrets.append(urlsplit(config.redis_url).password)
    known_secrets.extend(value for key, value in os.environ.items()
                         if any(part in key.upper() for part in ("API_KEY", "API_TOKEN", "SECRET", "ACCESS_TOKEN")))
    try:
        if job["kind"] == "query":
            business = run_query(job["payload"], config, job_id=job["id"], timeout_seconds=job["timeout_seconds"])
        elif job["kind"] == "agent":
            business = run_agent(job["payload"], config, job_id=job["id"])
        else:
            raise BackendError("JOB_KIND_UNSUPPORTED")
        # 为什么要有它：原业务结果本地留证，公开结果不得包含私有provider包或服务凭据；completed不改写业务成功含义。
        save(Path(result_path).with_name("business-result.private.json"), business)
        envelope = {"schema": "service-attempt-result.v1", "job_id": job["id"], "attempt": job["attempt"],
                    "ok": True, "safe_retry": False, "business_status": business.get("status"),
                    "result": public_result(business, known_secrets)}
    except Exception as error:
        envelope = {"schema": "service-attempt-result.v1", "job_id": job["id"], "attempt": job["attempt"],
                    "ok": False, "safe_retry": isinstance(error, BackendError) and error.safe_retry and job["kind"] == "query",
                    "execution_state": "not_started" if isinstance(error, BackendError) else "unknown",
                    "error": {"code": error.code if isinstance(error, BackendError) else "BACKEND_EXECUTION_FAILED",
                              "type": type(error).__name__}}
    save(result_path, envelope)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    return execute_request(args.request, args.result)


if __name__ == "__main__":
    raise SystemExit(main())
