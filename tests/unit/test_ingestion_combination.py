import hashlib
import json
import threading
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from src.core.settings import load_settings
from src.core.trace.trace_context import TraceContext
from src.core.types import Chunk
from src.ingestion.identity import ingestion_identity
from src.ingestion.transform.chunk_refiner import ChunkRefiner
from src.ingestion.transform.image_captioner import ImageCaptioner
from src.libs.embedding.ollama_embedding import OllamaEmbedding, OllamaEmbeddingError
from src.libs.llm.base_vision_llm import ImageInput
from src.libs.llm.llm_factory import LLMFactory
from src.libs.loader.file_integrity import SQLiteIntegrityChecker
from src.libs.loader.material_loader import MaterialLoader


def settings():
    result = load_settings("config/settings.yaml")
    return replace(result, embedding=replace(result.embedding, provider="ollama", model="embedding",
        dimensions=2, transport="batch", model_revision="digest-one", base_url="http://localhost:11434"),
        vision_llm=replace(result.vision_llm, provider="ollama", model="vision", enabled=True, model_revision="vision-one"))


@pytest.mark.parametrize("transport,requests", [("batch", 1), ("legacy", 3)])
def test_actual_http_batch_size_and_legacy_comparison(monkeypatch, transport, requests):
    config = settings()
    config = replace(config, embedding=replace(config.embedding, transport=transport))
    seen = []
    def handle(self, request):
        payload = json.loads(request.content)
        seen.append(payload)
        if request.url.path == "/api/embed":
            return httpx.Response(200, request=request, json={"model": "embedding", "embeddings": [[1., 2.]] * len(payload["input"]), "prompt_eval_count": 6})
        return httpx.Response(200, request=request, json={"embedding": [1., 2.]})
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    provider = OllamaEmbedding(config)
    trace = TraceContext(trace_type="ingestion")
    assert provider.embed(["one", "two", "three"], trace=trace) == [[1., 2.]] * 3
    assert len(seen) == provider.last_observation["request_count"] == requests
    if transport == "batch":
        assert seen[0]["input"] == ["one", "two", "three"] and seen[0]["truncate"] is False
    assert trace.get_stage_data("embedding_transport")["request_count"] == requests


@pytest.mark.parametrize("response", [{"embeddings": [[1.]]}, {"embeddings": []}, {"model": "wrong", "embeddings": [[1., 2.]]}])
def test_batch_shape_and_model_drift_rejected(monkeypatch, response):
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda self, request: httpx.Response(200, request=request, json=response))
    with pytest.raises(OllamaEmbeddingError):
        OllamaEmbedding(settings()).embed(["text"])


@pytest.mark.parametrize("suffix", [".cs", ".xml", ".md", ".txt"])
def test_real_text_loader_preserves_original_source(tmp_path, suffix):
    path = tmp_path / ("material" + suffix)
    content = "Original <member>文字</member>\r\n"
    path.write_bytes(content.encode("utf-8"))
    loader = MaterialLoader(None, collection="test")
    document = loader.load(path)
    assert document.text == content
    assert document.metadata["source_hash"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert document.metadata["parser"] == "utf8_text"


def test_image_cache_binds_content_model_and_prompt_with_real_completion_counts(tmp_path):
    path = tmp_path / "diagram.png"
    Image.new("RGB", (2, 2), "white").save(path)
    document = MaterialLoader(None, collection="test").load(path)
    calls = []
    class Vision:
        def chat_with_image(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content="diagnostic diagram", usage={"total_tokens": 8})
    captioner = ImageCaptioner(settings(), llm=Vision())
    def run():
        return captioner.transform([Chunk(id="c", text=document.text, metadata=dict(document.metadata))])
    assert "diagnostic diagram" in run()[0].text
    assert captioner.last_observation["api_calls"] == 1
    run()
    assert captioner.last_observation["cache_hits"] == 1 and captioner.last_observation["api_calls"] == 0
    captioner.prompt += " revised"
    run()
    assert len(calls) == 2
    captioner.settings = replace(captioner.settings, vision_llm=replace(captioner.settings.vision_llm, model_revision="vision-two"))
    run()
    assert len(calls) == 3
    Image.new("RGB", (2, 2), "black").save(path)
    run()
    assert len(calls) == 4


def test_config_revision_and_source_identity_gate_skip_and_preserve_legacy(tmp_path):
    checker = SQLiteIntegrityChecker(str(tmp_path / "history.db"))
    original = settings()
    _, fingerprint = ingestion_identity(original)
    checker.mark_success("hash", "source", "collection")
    assert checker.should_skip("hash", "collection")
    assert not checker.should_skip("hash", "collection", processing_fingerprint=fingerprint, source_path="source")
    checker.mark_success("hash", "source", "collection", processing_fingerprint=fingerprint)
    assert checker.should_skip("hash", "collection", processing_fingerprint=fingerprint, source_path="source")
    for changed in (replace(original, embedding=replace(original.embedding, model_revision="digest-two")),
                    replace(original, ingestion=replace(original.ingestion, chunk_size=127))):
        _, changed_fingerprint = ingestion_identity(changed)
        assert changed_fingerprint != fingerprint
        assert not checker.should_skip("hash", "collection", processing_fingerprint=changed_fingerprint, source_path="source")
    assert not checker.should_skip("hash", "collection", processing_fingerprint=fingerprint, source_path="other")


def test_chunk_concurrency_records_actual_overlap_and_bound():
    config = settings()
    config = replace(config, ingestion=replace(config.ingestion, max_workers=2, chunk_refiner={"use_llm": True}))
    barrier = threading.Barrier(2)
    class Model:
        def chat(self, *args, **kwargs):
            barrier.wait(timeout=3)
            return "refined"
    trace = TraceContext(trace_type="ingestion")
    chunks = [Chunk(id=str(index), text="original", metadata={"source_path": "material"}) for index in range(2)]
    result = ChunkRefiner(config, llm=Model()).transform(chunks, trace=trace)
    assert all(chunk.metadata["refined_by"] == "llm" for chunk in result)
    calls = [row["data"] for row in trace.stages if row["stage"].startswith("chunk_refinement:")]
    assert len(calls) == 2 and len({row["worker_thread"] for row in calls}) == 2
    assert max(row["started_monotonic"] for row in calls) < min(row["finished_monotonic"] for row in calls)


def test_ollama_vision_factory_uses_real_transport_contract_offline(tmp_path, monkeypatch):
    image = tmp_path / "diagram.png"
    Image.new("RGB", (2, 2), "white").save(image)
    seen = []
    def handle(self, request):
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx.Response(200, request=request, json={"model": "vision", "done": True,
            "message": {"role": "assistant", "content": "diagram"}, "prompt_eval_count": 10, "eval_count": 2})
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    trace = TraceContext(trace_type="ingestion")
    answer = LLMFactory.create_vision_llm(settings()).chat_with_image("describe", ImageInput(path=image), trace=trace)
    assert answer.content == "diagram" and answer.usage["total_tokens"] == 12
    assert len(seen) == 1 and seen[0]["messages"][-1]["images"]
    assert seen[0]["stream"] is False
    assert trace.get_stage_data("vision_transport")["status"] == "succeeded"


def test_normal_pipeline_keeps_original_lineage_and_reindexes_profile_change(tmp_path, monkeypatch):
    from tests.unit.test_incremental_ingestion_correctness import _pipeline_factory, _stored
    make, embeddings = _pipeline_factory(tmp_path, monkeypatch)
    pipeline = make("lineage")
    source = tmp_path / "member.xml"
    raw = b"<member name='Config.Bind'>original API documentation</member>"
    source.write_bytes(raw)
    def enhance(chunks, trace=None):
        return [replace(chunk, text="augmented " + chunk.text,
                        metadata={**chunk.metadata, "refined_by": "llm"}) for chunk in chunks]
    monkeypatch.setattr(pipeline.chunk_refiner, "transform", enhance)
    first = pipeline.run(str(source))
    assert first.success
    stored = _stored(pipeline, source)
    for metadata, text in zip(stored["metadatas"], stored["documents"]):
        assert text.startswith("augmented ")
        assert not metadata["original_text"].startswith("augmented ")
        assert metadata["original_span_verified"] is True
        assert metadata["source_hash"] == hashlib.sha256(raw).hexdigest()
        assert metadata["original_text_sha256"] == hashlib.sha256(metadata["original_text"].encode()).hexdigest()
    old_fingerprint = pipeline.processing_fingerprint
    pipeline.settings.embedding.model_revision = "new-revision"
    second = make("lineage")
    result = second.run(str(source))
    assert result.success and not result.stages["integrity"]["skipped"]
    assert second.processing_fingerprint != old_fingerprint
    assert embeddings["lineage"].calls


def test_source_change_during_enhancement_is_not_committed(tmp_path, monkeypatch):
    from tests.unit.test_incremental_ingestion_correctness import _pipeline_factory, _stored
    make, _ = _pipeline_factory(tmp_path, monkeypatch)
    pipeline = make("changed")
    source = tmp_path / "material.cs"
    source.write_bytes(b"class Original {}")
    def change(chunks, trace=None):
        source.write_bytes(b"class Changed {}")
        return chunks
    monkeypatch.setattr(pipeline.chunk_refiner, "transform", change)
    result = pipeline.run(str(source))
    assert not result.success and result.error == "INGESTION_SOURCE_CHANGED_BEFORE_STORAGE"
    assert not _stored(pipeline, source)["ids"]


def test_failed_caption_is_not_cached_as_success(tmp_path):
    path = tmp_path / "diagram.png"
    Image.new("RGB", (2, 2), "white").save(path)
    document = MaterialLoader(None, collection="test").load(path)
    calls = []
    class Vision:
        def chat_with_image(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content="", usage=None)
    captioner = ImageCaptioner(settings(), llm=Vision())
    for _ in range(2):
        captioner.transform([Chunk(id="c", text=document.text, metadata=dict(document.metadata))])
        assert captioner.last_observation["failed"] == 1
        assert captioner.last_observation["cache_hits"] == 0
    assert len(calls) == 2
