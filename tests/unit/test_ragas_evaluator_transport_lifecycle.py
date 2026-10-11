"""Exercise real Ragas/OpenAI async lifetimes over loopback HTTP keep-alive."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import openai
import pytest

from src.core.settings import EmbeddingSettings, LLMSettings
from src.observability.evaluation.ragas_evaluator import RagasEvaluator


class _KeepAliveServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        self.requests = []
        self.connections = []
        self.completions = 0
        super().__init__(("127.0.0.1", 0), _Handler)

    def get_request(self):
        connection, address = super().get_request()
        self.connections.append(connection)
        return connection, address


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def do_POST(self):  # noqa: N802 - stdlib HTTP handler protocol
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, self.client_address[1], body))
        if self.path == "/v1/chat/completions":
            outputs = [
                {"statements": ["Paris is the capital of France."]},
                {"statements": [{"statement": "Paris is the capital of France.", "reason": "The context says so.", "verdict": 1}]},
                {"question": "What is the capital of France?", "noncommittal": 0},
                {"question": "What is the capital of France?", "noncommittal": 0},
                {"question": "What is the capital of France?", "noncommittal": 0},
                {"reason": "The context contains the answer.", "verdict": 1},
            ]
            output = outputs[self.server.completions % len(outputs)]
            self.server.completions += 1
            response = {
                "id": "fixed-local-response", "object": "chat.completion", "created": 0,
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(output)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        elif self.path == "/v1/embeddings":
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            response = {
                "object": "list", "model": body["model"],
                "data": [{"object": "embedding", "index": index, "embedding": [1.0, 0.0]} for index, _ in enumerate(inputs)],
                "usage": {"prompt_tokens": len(inputs), "total_tokens": len(inputs)},
            }
        else:
            self.send_error(404)
            return
        encoded = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(encoded)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def test_evaluate_three_metrics_twice_closes_clients_on_their_request_loop(monkeypatch):
    """Two evaluations must reuse connections within, then close each call's clients."""
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")
    from ragas import _analytics

    _analytics.do_not_track.cache_clear()
    server = _KeepAliveServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    clients = []
    request_loops = {}
    close_loops = {}
    original_client = openai.AsyncOpenAI

    class RecordingAsyncOpenAI(original_client):
        def __init__(self, **kwargs):
            async def observe_request(request):
                assert request.url.host == "127.0.0.1"
                assert request.url.port == server.server_port
                request_loops.setdefault(id(self), []).append(asyncio.get_running_loop())

            kwargs["http_client"] = httpx.AsyncClient(
                trust_env=False, timeout=3.0, event_hooks={"request": [observe_request]},
            )
            kwargs["timeout"] = 3.0
            super().__init__(**kwargs)
            clients.append(self)

        async def close(self):
            close_loops[id(self)] = asyncio.get_running_loop()
            await super().close()

    monkeypatch.setattr(openai, "AsyncOpenAI", RecordingAsyncOpenAI)
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    settings = SimpleNamespace(
        llm=LLMSettings(provider="openai", model="local-judge", temperature=0.0, max_tokens=128, api_key="test-placeholder", base_url=endpoint),
        embedding=EmbeddingSettings(provider="openai", model="local-embedding", dimensions=2, api_key="test-placeholder", base_url=endpoint),
    )
    evaluator = RagasEvaluator(settings=settings, metrics=["faithfulness", "answer_relevancy", "context_precision"])
    try:
        for _ in range(2):
            scores = evaluator.evaluate(
                query="What is the capital of France?",
                retrieved_chunks=[{"text": "Paris is the capital of France."}],
                generated_answer="Paris is the capital of France.",
            )
            assert scores == pytest.approx({"faithfulness": 1.0, "answer_relevancy": 1.0, "context_precision": 1.0})
            assert all(client.is_closed() for client in clients)
        assert len(clients) == 4
        assert len(server.requests) == 16  # Six judge and two embedding requests per call.
        for client in clients:
            loops = request_loops[id(client)]
            assert loops
            assert all(loop is loops[0] for loop in loops)
            assert close_loops[id(client)] is loops[0]
        for path in ("/v1/chat/completions", "/v1/embeddings"):
            ports = [port for request_path, port, _ in server.requests if request_path == path]
            assert len(set(ports)) == 2  # Each evaluation owns one reusable connection.
    finally:
        for client in clients:
            if not client.is_closed():
                try:
                    asyncio.run(client.close())
                except RuntimeError:
                    # The failing pre-fix owner may already have closed the request loop.
                    pass
        server.shutdown()
        for connection in server.connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        server.server_close()
        thread.join(timeout=3)
        _analytics.do_not_track.cache_clear()
        assert all(client.is_closed() for client in clients)
        assert not thread.is_alive()
        assert server.socket.fileno() == -1
