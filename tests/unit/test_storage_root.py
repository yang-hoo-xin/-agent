from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from src.core.settings import (
    SettingsError,
    load_settings,
    require_storage_path,
    resolve_path,
    resolve_storage_path,
)
from src.ingestion.pipeline import IngestionPipeline


def configured(root):
    base = load_settings("config/settings.yaml")
    return replace(base, storage_root=str(root),
                   vector_store=replace(base.vector_store, persist_directory=str(root / "db/chroma")),
                   vision_llm=replace(base.vision_llm, enabled=False))


def test_default_paths_remain_legacy_and_explicit_roots_reject_escape(tmp_path):
    legacy = load_settings("config/settings.yaml")
    assert resolve_storage_path(legacy, "db", "bm25", "one") == resolve_path("data/db/bm25/one")
    config = configured(tmp_path / "selected")
    assert resolve_storage_path(config, "db", "history.db") == tmp_path / "selected/db/history.db"
    for parts in [("..", "other"), (str(tmp_path / "outside"),)]:
        with pytest.raises(SettingsError):
            resolve_storage_path(config, *parts)
    for value in ["relative", str(tmp_path / "outside")]:
        with pytest.raises(SettingsError):
            require_storage_path(config, value)
    for root in ["relative", "//server/share", str(tmp_path / ".." / "other")]:
        with pytest.raises(SettingsError):
            replace(config, storage_root=root)


def test_two_pipeline_roots_do_not_share_history_index_or_images(tmp_path, monkeypatch):
    import src.ingestion.pipeline as module
    from tests.unit.test_incremental_ingestion_correctness import CountingEmbedding
    monkeypatch.setattr(module.EmbeddingFactory, "create", lambda _: CountingEmbedding())
    source = tmp_path / "source.md"
    source.write_text("source material stored independently", encoding="utf-8")
    configs = [configured(tmp_path / name) for name in ("one", "two")]
    configs = [replace(c, ingestion=replace(c.ingestion, chunk_refiner={"use_llm": False},
        metadata_enricher={"use_llm": False})) for c in configs]
    pipelines = [IngestionPipeline(c, collection="same") for c in configs]
    first = pipelines[0].run(str(source))
    assert first.success
    digest = pipelines[0].integrity_checker.compute_sha256(str(source))
    assert not pipelines[1].integrity_checker.should_skip(digest, collection="same")
    second = pipelines[1].run(str(source))
    assert second.success and not second.stages["integrity"]["skipped"]
    for config, pipeline, result in zip(configs, pipelines, (first, second)):
        assert result.stages["integrity"]["storage_paths"] == pipeline.storage_paths
        assert all(Path(path).is_relative_to(config.storage_root) for path in pipeline.storage_paths.values())
        assert Path(pipeline.image_storage.db_path).is_relative_to(config.storage_root)
        assert Path(pipeline.vector_upserter.vector_store.persist_directory).is_relative_to(config.storage_root)
    image = tmp_path / "original.png"
    Image.new("RGB", (2, 2), "white").save(image)
    for config, pipeline in zip(configs, pipelines):
        loaded = pipeline.loader.load(image)
        stored = Path(loaded.metadata["images"][0]["path"])
        assert stored.is_relative_to(config.storage_root) and stored.read_bytes() == image.read_bytes()


def test_explicit_vector_root_mismatch_rejected_before_storage(tmp_path):
    config = configured(tmp_path / "chosen")
    with pytest.raises(SettingsError):
        replace(config, vector_store=replace(config.vector_store, persist_directory=str(tmp_path / "outside")))
    assert not (tmp_path / "chosen").exists()
