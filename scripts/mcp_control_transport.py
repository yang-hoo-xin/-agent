"""Evaluation-only loopback forwarding recorder; never substitutes a model response.

为什么要有它：SDK 只返回最终结果时，取消触发必须由真实上游正文证明，不能把 reservation 当已发送。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class NativeRecorder:
    def __init__(self, *, output, upstream, models, max_calls, max_tokens, embedding_model=None, max_embeddings=0, timeout=240):
        address = urlsplit(upstream)
        if (address.scheme != "http" or address.hostname not in {"127.0.0.1", "localhost", "::1"}
                or address.path not in {"", "/"} or address.username or address.password or address.query or address.fragment):
            raise ValueError("CONTROL_LOOPBACK_UPSTREAM_REQUIRED")
        self.address, self.models = address, set(models)
        self.max_calls, self.max_tokens, self.timeout = max_calls, max_tokens, timeout
        self.embedding_model, self.max_embeddings = embedding_model, max_embeddings
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.rows, self.lock = [], threading.Lock()
        self.active = threading.BoundedSemaphore(2)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2_000_000:
                        raise ValueError("CONTROL_BODY_SIZE_INVALID")
                    body = self.rfile.read(length)
                    request = json.loads(body)
                    owner.validate(self.path, request)
                    with owner.lock:
                        kind = "generation" if self.path == "/api/chat" else "embedding"
                        limit = owner.max_calls if kind == "generation" else owner.max_embeddings
                        if sum(r["kind"] == kind for r in owner.rows) >= limit:
                            raise ValueError("CONTROL_TRANSPORT_BUDGET_EXHAUSTED")
                        row = {"ordinal": len(owner.rows) + 1, "model": request["model"],
                               "kind": kind, "path": self.path,
                               "role": "answer" if kind == "generation" and request.get("stream") is True and not request.get("format") else kind,
                               "body_sha256": hashlib.sha256(body).hexdigest(), "accepted_monotonic": time.monotonic(),
                               "transport_started": False, "first_content_monotonic": None, "finished": False,
                               "native_usage": None, "client_disconnected": False, "provider_termination": "unknown"}
                        owner.rows.append(row)
                except (ValueError, KeyError, TypeError):
                    self.send_error(400, "CONTROL_REQUEST_REJECTED")
                    return
                directory = owner.output / str(row["ordinal"])
                directory.mkdir()
                (directory / "request.json").write_bytes(body)
                connection = http.client.HTTPConnection(owner.address.hostname, owner.address.port or 80, timeout=owner.timeout)
                try:
                    if not owner.active.acquire(timeout=owner.timeout):
                        raise TimeoutError("CONTROL_UPSTREAM_CONCURRENCY_LIMIT")
                    try:
                        connection.request("POST", self.path, body, {"Content-Type": "application/json"})
                        row["transport_started"] = True
                        row["transport_started_monotonic"] = time.monotonic()
                        response = connection.getresponse()
                        row["http_status"] = response.status
                        self.send_response(response.status)
                        self.send_header("Content-Type", "application/x-ndjson")
                        self.end_headers()
                        with (directory / "native-response.jsonl").open("wb") as raw:
                            while line := response.readline():
                                raw.write(line)
                                raw.flush()
                                try:
                                    value = json.loads(line)
                                    if value.get("message", {}).get("content") and row["first_content_monotonic"] is None:
                                        row["first_content_monotonic"] = time.monotonic()
                                    if value.get("done") is True:
                                        row["native_done"] = True
                                        if all(type(value.get(k)) is int for k in ("prompt_eval_count", "eval_count")):
                                            row["native_usage"] = {k: value[k] for k in ("prompt_eval_count", "eval_count")}
                                except (ValueError, AttributeError):
                                    row["native_parse_error"] = True
                                if not row["client_disconnected"]:
                                    try:
                                        self.wfile.write(line)
                                        self.wfile.flush()
                                    except (OSError, BrokenPipeError):
                                        row["client_disconnected"] = True
                                # 为什么要有它：客户端取消后继续只读耗尽这个有界上游响应，以保留实际成本；不声称服务端被终止。
                    finally:
                        owner.active.release()
                except Exception as error:
                    row["error_type"] = type(error).__name__
                finally:
                    connection.close()
                    row.update(finished=True, finished_monotonic=time.monotonic())
                    (directory / "observation.json").write_text(json.dumps(row, indent=2), encoding="utf-8")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def validate(self, path, request):
        if not isinstance(request, dict):
            raise ValueError("CONTROL_REQUEST_OBJECT_REQUIRED")
        if path in {"/api/embed", "/api/embeddings"}:
            value = request.get("input", request.get("prompt"))
            if (request.get("model") != self.embedding_model or not isinstance(value, (str, list))
                    or isinstance(value, list) and (not 1 <= len(value) <= 2 or not all(isinstance(v, str) and v for v in value))):
                raise ValueError("CONTROL_EMBEDDING_OUTSIDE_PLAN")
            return
        if (path != "/api/chat" or request.get("model") not in self.models or type(request.get("stream")) is not bool
                or type(request.get("options", {}).get("num_predict")) is not int
                or not 0 < request["options"]["num_predict"] <= self.max_tokens):
            raise ValueError("CONTROL_REQUEST_OUTSIDE_PLAN")

    def start(self):
        self.thread.start()
        return "http://127.0.0.1:" + str(self.server.server_port)

    def stop(self, drain_seconds=None):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        # 为什么要有它：失败路径也须等待已发送有界请求结算，未耗尽的请求明确保留未知，不能宣称后台结束。
        deadline = time.monotonic() + (self.timeout + 5 if drain_seconds is None else drain_seconds)
        while any(not row["finished"] for row in self.snapshot()) and time.monotonic() < deadline:
            time.sleep(0.05)
        return all(row["finished"] for row in self.snapshot())

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.rows))


def midcall_proof(row):
    """Actual native final usage is mandatory; absent usage remains unknown."""
    usage = row.get("native_usage")
    return bool(row.get("transport_started") and row.get("http_status") == 200 and row.get("native_done") is True
                and row.get("first_content_monotonic") is not None
                and isinstance(usage, dict) and usage.get("eval_count", 0) > 0)
