import hashlib
import json
from dataclasses import replace

import httpx

from src.core.query_engine.query_service import QueryRequest
from src.core.settings import QuerySettings, load_settings
from src.libs.llm.ollama_llm import OllamaLLM
from tests.unit.test_query_service import make_service


def test_normal_rewrite_uses_real_native_adapter_and_persists_before_transport(tmp_path, monkeypatch):
    config = QuerySettings(rewrite_enabled=True, context_window=16384)
    service, _, _, _, _ = make_service(tmp_path, config=config)
    settings = load_settings("config/settings.yaml")
    settings = replace(settings, storage_root=str(tmp_path),
        vector_store=replace(settings.vector_store, persist_directory=str(tmp_path / "chroma")),
        llm=replace(settings.llm, provider="ollama", model="native-test", base_url="http://127.0.0.1:11434"), query=config)
    service.settings = settings
    service.llm = OllamaLLM(settings, context_window=16384)
    sent = []
    def handle(self, request):
        files = list((tmp_path / "query_requests").glob("*.json"))
        assert len(files) == 1
        frozen = json.loads(files[0].read_bytes())
        assert frozen["body_sha256"] == hashlib.sha256(request.content).hexdigest()
        assert json.loads(frozen["body_utf8"])["format"]["required"] == ["query"]
        sent.append(request)
        return httpx.Response(200, request=request, json={"model": "native-test", "done": True,
            "done_reason": "stop", "message": {"role": "assistant", "content": '{"query":"precise lookup"}'},
            "prompt_eval_count": 10, "eval_count": 5})
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    result = service.query(QueryRequest(query="lookup", collection="docs", answer=False, rerank=False))
    row = result.to_dict()
    assert row["status"] == "completed", row["error"]
    assert len(sent) == row["usage"]["rewrite_transport_calls"] == 1
    assert row["usage"]["rewrite_tokens"]["total_tokens"] == 15
    assert "rewrite_request_ref" in result.evidence
    assert "body_utf8" not in json.dumps(row)
