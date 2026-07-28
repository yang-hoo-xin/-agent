"""Tests for settings loading and validation."""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from src.core.settings import SettingsError, load_settings


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_load_settings_success(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
        - mrr
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    performance:
      operations:
        retrieval:
          max_api_calls: 0
          max_items: 20
          max_duration_ms: 5000
          max_concurrency: 1
          cache_enabled: true
          on_exceed: block
    ingestion:
      chunk_size: 1000
      chunk_overlap: 200
      splitter: recursive
      batch_size: 100
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    settings = load_settings(settings_path)

    assert settings.llm.provider == "openai"
    assert settings.embedding.dimensions == 1536
    assert settings.vector_store.collection_name == "knowledge_hub"
    assert settings.retrieval.rrf_k == 60
    assert settings.retrieval.dense_enabled is False
    assert settings.retrieval.dense_provider == "disabled"
    assert settings.retrieval.dense_failure_policy == "degrade"
    assert settings.rerank.provider == "none"
    assert settings.evaluation.metrics == ["hit_rate", "mrr"]
    assert settings.observability.log_level == "INFO"
    assert settings.performance is not None
    assert settings.performance.operations["retrieval"].max_items == 20
    assert settings.performance.operations["retrieval"].on_exceed == "block"
    assert settings.ingestion is not None


def test_retrieval_dense_provider_settings_are_explicit(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_enabled: true
      dense_provider: fake
      dense_failure_policy: block
      dense_top_k: 5
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    settings = load_settings(settings_path, allow_test_providers=True)

    assert settings.retrieval.dense_enabled is True
    assert settings.retrieval.dense_provider == "fake"
    assert settings.retrieval.dense_failure_policy == "block"
    assert settings.retrieval.dense_top_k == 5


def test_retrieval_vector_store_dense_provider_settings_are_allowed(
    tmp_path: Path,
) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_enabled: true
      dense_provider: vector_store
      dense_top_k: 5
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    settings = load_settings(settings_path)

    assert settings.retrieval.dense_enabled is True
    assert settings.retrieval.dense_provider == "vector_store"
    assert settings.retrieval.dense_top_k == 5


def test_retrieval_fake_dense_provider_requires_test_opt_in(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_enabled: true
      dense_provider: fake
      dense_top_k: 5
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="allow_test_providers"):
        load_settings(settings_path)


def test_runtime_gtfo_settings_parse_explicit_real_automation_config(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    runtime:
      gtfo:
        enabled: true
        game_executable: C:/Games/GTFO/GTFO.exe
        working_directory: C:/Games/GTFO
        launch_args:
          - -screen-fullscreen
          - "0"
        log_paths:
          - BepInEx/LogOutput.log
        screenshot_directory: ./artifacts/runtime/screenshots
        screenshot_timeout_seconds: 9
        startup_markers:
          - Chainloader
        acceptance_markers:
          "Requested behavior is implemented: make Load enable diagnostics": BETTER_HIT_FEEDBACK_ACCEPTANCE_OK
        timeout_seconds: 180
        poll_interval_seconds: 0.5
        output_limit_chars: 4096
        terminate_after_capture: true
        operator_completion_required: true
        operator_completion_timeout_seconds: 900
        stagger_acceptance:
          enabled: true
          config_path: C:/Games/GTFO/BepInEx/config/local.betterhitfeedback.cfg
          disabled_config_path: C:/Runtime/general_enabled_false.cfg
          disabled_config_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
          enabled_config_path: C:/Runtime/general_enabled_true.cfg
          enabled_config_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    settings = load_settings(settings_path)

    assert settings.runtime is not None
    assert settings.runtime.gtfo is not None
    assert settings.runtime.gtfo.enabled is True
    assert settings.runtime.gtfo.game_executable == "C:/Games/GTFO/GTFO.exe"
    assert settings.runtime.gtfo.working_directory == "C:/Games/GTFO"
    assert settings.runtime.gtfo.launch_args == ["-screen-fullscreen", "0"]
    assert settings.runtime.gtfo.log_paths == ["BepInEx/LogOutput.log"]
    assert settings.runtime.gtfo.screenshot_timeout_seconds == 9
    assert settings.runtime.gtfo.startup_markers == ["Chainloader"]
    assert settings.runtime.gtfo.acceptance_markers == {
        "Requested behavior is implemented: make Load enable diagnostics": (
            "BETTER_HIT_FEEDBACK_ACCEPTANCE_OK"
        )
    }
    assert settings.runtime.gtfo.timeout_seconds == 180
    assert settings.runtime.gtfo.poll_interval_seconds == 0.5
    assert settings.runtime.gtfo.output_limit_chars == 4096
    assert settings.runtime.gtfo.terminate_after_capture is True
    assert settings.runtime.gtfo.operator_completion_required is True
    assert settings.runtime.gtfo.operator_completion_timeout_seconds == 900
    assert settings.runtime.gtfo.stagger_acceptance is not None
    assert settings.runtime.gtfo.stagger_acceptance.enabled is True
    assert settings.runtime.gtfo.stagger_acceptance.config_path == (
        "C:/Games/GTFO/BepInEx/config/local.betterhitfeedback.cfg"
    )
    assert settings.runtime.gtfo.stagger_acceptance.disabled_config_path == (
        "C:/Runtime/general_enabled_false.cfg"
    )
    assert settings.runtime.gtfo.stagger_acceptance.disabled_config_sha256 == (
        "a" * 64
    )
    assert settings.runtime.gtfo.stagger_acceptance.enabled_config_path == (
        "C:/Runtime/general_enabled_true.cfg"
    )
    assert settings.runtime.gtfo.stagger_acceptance.enabled_config_sha256 == (
        "b" * 64
    )


def test_runtime_gtfo_settings_reject_invalid_poll_interval(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    runtime:
      gtfo:
        poll_interval_seconds: 0
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="runtime.gtfo.poll_interval_seconds"):
        load_settings(settings_path)


def test_runtime_gtfo_settings_reject_invalid_screenshot_timeout(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    runtime:
      gtfo:
        screenshot_timeout_seconds: 0
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="runtime.gtfo.screenshot_timeout_seconds"):
        load_settings(settings_path)


def test_runtime_gtfo_settings_reject_invalid_operator_completion_timeout(
    tmp_path: Path,
) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    runtime:
      gtfo:
        operator_completion_timeout_seconds: 0
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(
        SettingsError,
        match="runtime.gtfo.operator_completion_timeout_seconds",
    ):
        load_settings(settings_path)


def test_runtime_gtfo_settings_reject_invalid_acceptance_markers(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    runtime:
      gtfo:
        acceptance_markers:
          - not-a-mapping
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="runtime.gtfo.acceptance_markers"):
        load_settings(settings_path)


def test_retrieval_dense_provider_rejects_unknown_provider(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_provider: openai
      dense_top_k: 5
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="retrieval.dense_provider"):
        load_settings(settings_path)


def test_retrieval_dense_failure_policy_rejects_unknown_policy(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_provider: vector_store
      dense_failure_policy: ignore
      dense_top_k: 5
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="retrieval.dense_failure_policy"):
        load_settings(settings_path)


def test_performance_settings_reject_invalid_on_exceed(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    performance:
      operations:
        retrieval:
          on_exceed: warn
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="performance.operations.retrieval.on_exceed"):
        load_settings(settings_path)


def test_performance_settings_reject_zero_max_concurrency(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    performance:
      operations:
        retrieval:
          max_concurrency: 0
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(
        SettingsError,
        match="performance.operations.retrieval.max_concurrency",
    ):
        load_settings(settings_path)


def test_missing_required_field_raises_error(tmp_path: Path) -> None:
    config = """
    llm:
      provider: openai
      model: gpt-4o-mini
      temperature: 0.0
      max_tokens: 1024
    embedding:
      model: text-embedding-3-small
      dimensions: 1536
    vector_store:
      provider: chroma
      persist_directory: ./data/db/chroma
      collection_name: knowledge_hub
    retrieval:
      dense_top_k: 20
      sparse_top_k: 20
      fusion_top_k: 10
      rrf_k: 60
    rerank:
      enabled: false
      provider: none
      model: cross-encoder/ms-marco-MiniLM-L-6-v2
      top_k: 5
    evaluation:
      enabled: false
      provider: custom
      metrics:
        - hit_rate
    observability:
      log_level: INFO
      trace_enabled: true
      trace_file: ./logs/traces.jsonl
      structured_logging: true
    """
    settings_path = tmp_path / "settings.yaml"
    _write_yaml(settings_path, config)

    with pytest.raises(SettingsError, match="embedding.provider"):
        load_settings(settings_path)
