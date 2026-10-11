"""Bind ingestion reuse to parser, transformation, prompt and declared model revisions."""
import hashlib
import json

from src.core.settings import resolve_path


def ingestion_identity(settings):
    selected = getattr(settings, "ingestion", None)
    ingestion = {key: getattr(selected, key, None) for key in (
        "chunk_size", "chunk_overlap", "splitter", "batch_size", "chunk_refiner", "metadata_enricher",
        "max_workers", "image_max_workers", "model_revisions", "extensions", "strict_transforms")} if selected else None
    def model(config):
        if config is None:
            return None
        return {key: getattr(config, key, None) for key in (
            "provider", "model", "model_revision", "base_url", "dimensions", "transport",
            "temperature", "max_tokens", "enabled", "max_image_size", "context_window", "timeout")}
    prompts = {}
    for name in ("chunk_refinement.txt", "metadata_enrichment.txt", "image_captioning.txt"):
        path = resolve_path("config/prompts/" + name)
        prompts[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    # 为什么要有它：同一配置下解析或清洗代码的修复也会改变索引内容，旧 hash 命中不能掩盖源码升级。
    implementation = {}
    for relative in ("src/libs/loader/material_loader.py", "src/libs/loader/pdf_loader.py",
                     "src/ingestion/chunking/document_chunker.py", "src/ingestion/pipeline.py",
                     "src/ingestion/transform/chunk_refiner.py", "src/ingestion/transform/metadata_enricher.py",
                     "src/ingestion/transform/image_captioner.py", "src/libs/embedding/ollama_embedding.py",
                     "src/core/query_engine/tokenization.py", "src/ingestion/embedding/sparse_encoder.py"):
        path = resolve_path(relative)
        implementation[relative] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    identity = {"schema_version": "ingestion_identity_v2", "implementation_sha256": implementation, "parser_version": "material_loader_v1",
                "ingestion": ingestion, "llm": model(getattr(settings, "llm", None)),
                "embedding": model(settings.embedding), "vision": model(settings.vision_llm),
                "prompt_hashes": prompts}
    if identity["llm"] is not None:
        identity["llm"]["model_revision"] = (getattr(selected, "model_revisions", None) or {}).get("llm")
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return identity, digest
