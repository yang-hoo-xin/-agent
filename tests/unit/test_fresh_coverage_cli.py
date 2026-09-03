from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.settings import load_settings
from src.libs.llm import ChatResponse, OllamaLLM
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.cli import main
from src.mod_agent.evidence import EvidencePack
from src.mod_agent.fresh_coverage import (
    FreshCoverageError,
    FreshCoverageProgressReporter,
    LocalOllamaRequirementCoverageCompletion,
    create_local_ollama_requirement_coverage_completion,
)
from src.mod_agent.model_admission import ModelAdmissionError
from src.mod_agent.planning import FeatureSpec
from src.mod_agent.requirement_coverage_model import (
    parse_requirement_coverage_json_object,
)

_MODEL_DIGEST = "a" * 64
_MODEL_IDENTITY = {
    "name": "test-coverage-model",
    "model": "test-coverage-model",
    "digest": _MODEL_DIGEST,
    "modified_at": "2026-09-02T00:00:00Z",
    "size": 1,
    "details": {"context_length": 8192},
    "capabilities": ["completion"],
    "base_url": "http://127.0.0.1:11434",
}


class _ExternalLLM:
    def __init__(self, completion) -> None:
        self.completion = completion

    def chat(self, messages, **kwargs):
        payload = json.loads(messages[1].content)
        role = {
            "product_requirement_projection": "requirement_projection",
            "product_requirement_projection_correction": (
                "requirement_projection_correction"
            ),
            "product_requirement_findings": "requirement_findings",
            "product_requirement_findings_correction": (
                "requirement_findings_correction"
            ),
        }[payload["message_type"]]
        value = self.completion(role, payload, kwargs["response_format"])
        recorder = kwargs.get("provider_request_recorder")
        if callable(recorder):
            recorder({"body_sha256": "b" * 64, "body_utf8": "not retained"})
        return ChatResponse(
            content=json.dumps(value, ensure_ascii=False),
            model="test-coverage-model",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            raw_response={"done": True},
        )


def _real_ollama_llm(completion, monkeypatch) -> OllamaLLM:
    settings = load_settings("config/settings.yaml")
    settings = replace(
        settings,
        llm=replace(
            settings.llm,
            provider="ollama",
            model="test-coverage-model",
            max_tokens=1024,
            api_key=None,
            base_url="http://127.0.0.1:11434",
        ),
    )
    llm = OllamaLLM(
        settings,
        base_url="http://127.0.0.1:11434",
        context_window=8192,
    )

    def chat(messages, **kwargs):
        assert kwargs.get("stream_response") is True
        payload = json.loads(messages[1].content)
        role = {
            "product_requirement_projection": "requirement_projection",
            "product_requirement_projection_correction": (
                "requirement_projection_correction"
            ),
            "product_requirement_findings": "requirement_findings",
            "product_requirement_findings_correction": (
                "requirement_findings_correction"
            ),
        }[payload["message_type"]]
        value = completion(role, payload, kwargs["response_format"])
        recorder = kwargs.get("provider_request_recorder")
        if callable(recorder):
            recorder({"body_sha256": "b" * 64, "body_utf8": "not retained"})
        activity_recorder = kwargs.get("stream_activity_recorder")
        if callable(activity_recorder):
            activity_recorder(
                {
                    "chunk_index": 1,
                    "done": True,
                    "content_utf8_bytes": 17,
                    "cumulative_content_utf8_bytes": 17,
                }
            )
        return ChatResponse(
            content=json.dumps(value, ensure_ascii=False),
            model="test-coverage-model",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            raw_response={"done": True},
        )

    monkeypatch.setattr(llm, "chat", chat)
    return llm


def _local_completion(
    completion,
    monkeypatch,
) -> LocalOllamaRequirementCoverageCompletion:
    return LocalOllamaRequirementCoverageCompletion(
        llm=_real_ollama_llm(completion, monkeypatch),
        base_url="http://127.0.0.1:11434",
        model="test-coverage-model",
        model_identity=deepcopy(_MODEL_IDENTITY),
        context_window=8192,
        output_budget=1024,
        server_version="test-server",
    )


@pytest.mark.parametrize(
    ("content", "error_code"),
    [
        ('{"value":1,"value":2}', "REQUIREMENT_COVERAGE_MODEL_DUPLICATE_JSON_KEY"),
        ('{"value":NaN}', "REQUIREMENT_COVERAGE_MODEL_NON_FINITE_JSON"),
        ('{"value":Infinity}', "REQUIREMENT_COVERAGE_MODEL_NON_FINITE_JSON"),
        ('{"value":1e999}', "REQUIREMENT_COVERAGE_MODEL_NON_FINITE_JSON"),
    ],
)
def test_requirement_coverage_response_parser_rejects_non_canonical_json(
    content: str,
    error_code: str,
) -> None:
    with pytest.raises(ValueError, match=error_code):
        parse_requirement_coverage_json_object(content)


def test_local_ollama_completion_rejects_arbitrary_external_llm() -> None:
    with pytest.raises(
        FreshCoverageError,
        match="FRESH_COVERAGE_OLLAMA_ADAPTER_BINDING_INVALID",
    ):
        LocalOllamaRequirementCoverageCompletion(
            llm=_ExternalLLM(lambda *_args: {}),
            base_url="http://127.0.0.1:11434",
            model="test-coverage-model",
            model_identity=deepcopy(_MODEL_IDENTITY),
            context_window=8192,
            output_budget=1024,
            server_version="test-server",
        )


@pytest.mark.parametrize(
    ("field_name", "drifted_value"),
    [
        ("base_url", "https://external.invalid"),
        ("model", "drifted-model"),
        ("context_window", 4096),
    ],
)
def test_local_ollama_completion_rechecks_binding_before_chat(
    monkeypatch,
    field_name: str,
    drifted_value: object,
) -> None:
    provider_calls = 0

    def handler(_role, _payload, _schema):
        nonlocal provider_calls
        provider_calls += 1
        return {"accepted": True}

    completion = _local_completion(handler, monkeypatch)
    setattr(completion.llm, field_name, drifted_value)
    with pytest.raises(
        FreshCoverageError,
        match="FRESH_COVERAGE_OLLAMA_ADAPTER_BINDING_INVALID",
    ):
        completion(
            "requirement_projection",
            {"message_type": "product_requirement_projection"},
            {"type": "object"},
        )
    assert provider_calls == 0


def test_local_ollama_completion_rechecks_binding_after_chat(monkeypatch) -> None:
    provider_calls = 0

    def handler(_role, _payload, _schema):
        nonlocal provider_calls
        provider_calls += 1
        return {"accepted": True}

    completion = _local_completion(handler, monkeypatch)
    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.read_ollama_model_identity",
        lambda _base_url, _model: deepcopy(_MODEL_IDENTITY),
    )
    original_chat = completion.llm.chat

    def drift_after_chat(messages, **kwargs):
        response = original_chat(messages, **kwargs)
        completion.llm.base_url = "https://external.invalid"
        return response

    monkeypatch.setattr(completion.llm, "chat", drift_after_chat)
    with pytest.raises(
        FreshCoverageError,
        match="FRESH_COVERAGE_OLLAMA_ADAPTER_BINDING_INVALID",
    ):
        completion(
            "requirement_projection",
            {"message_type": "product_requirement_projection"},
            {"type": "object"},
        )
    assert provider_calls == 1


def test_local_ollama_completion_rejects_identity_base_url_mismatch(
    monkeypatch,
) -> None:
    llm = _real_ollama_llm(lambda *_args: {}, monkeypatch)
    mismatched_identity = deepcopy(_MODEL_IDENTITY)
    mismatched_identity["base_url"] = "http://127.0.0.1:11435"
    with pytest.raises(ModelAdmissionError, match="OLLAMA_MODEL_BASE_URL_MISMATCH"):
        LocalOllamaRequirementCoverageCompletion(
            llm=llm,
            base_url="http://127.0.0.1:11434",
            model="test-coverage-model",
            model_identity=mismatched_identity,
            context_window=8192,
            output_budget=1024,
            server_version="test-server",
        )


def test_local_ollama_completion_composes_exact_admission_and_shared_adapter(
    monkeypatch,
) -> None:
    identity_reads: list[tuple[str, str]] = []
    server_reads: list[str] = []
    factory_calls: list[tuple[object, dict[str, object]]] = []
    provider_roles: list[str] = []

    def read_identity(base_url, model):
        identity_reads.append((base_url, model))
        return deepcopy(_MODEL_IDENTITY)

    def handler(role, _payload, schema):
        provider_roles.append(role)
        assert schema == {"type": "object"}
        return {"accepted": True}

    fake_llm = _real_ollama_llm(handler, monkeypatch)

    def create_llm(settings, **options):
        factory_calls.append((settings, dict(options)))
        return fake_llm

    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.read_ollama_model_identity",
        read_identity,
    )
    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.read_ollama_server_version",
        lambda base_url: server_reads.append(base_url) or "test-server",
    )
    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.LLMFactory.create",
        create_llm,
    )

    completion = create_local_ollama_requirement_coverage_completion(
        settings_path="config/settings.yaml",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="test-coverage-model",
        ollama_context_window=8192,
        ollama_output_budget=1024,
    )
    output = completion(
        "requirement_projection",
        {"message_type": "product_requirement_projection"},
        {"type": "object"},
    )

    assert output == {"accepted": True}
    assert provider_roles == ["requirement_projection"]
    assert identity_reads == [
        ("http://127.0.0.1:11434", "test-coverage-model"),
        ("http://127.0.0.1:11434", "test-coverage-model"),
        ("http://127.0.0.1:11434", "test-coverage-model"),
    ]
    assert server_reads == ["http://127.0.0.1:11434"]
    assert len(factory_calls) == 1
    selected_settings, options = factory_calls[0]
    assert selected_settings.llm.provider == "ollama"
    assert selected_settings.llm.model == "test-coverage-model"
    assert selected_settings.llm.max_tokens == 1024
    assert options == {
        "base_url": "http://127.0.0.1:11434",
        "context_window": 8192,
    }
    assert completion.model_admission["external_disclosure_occurred"] is False
    assert completion.model_admission["source_disclosure"]["occurred"] is False
    assert completion.model_admission["automatic_provider_fallback"] is False
    assert completion.model_admission["automatic_external_retry"] is False
    assert completion.model_admission["response_transport"] == (
        "ollama_ndjson_stream_v1"
    )
    assert completion.model_admission["provider_request_resumable"] is False
    assert completion.model_admission["stream_content_disclosed"] is False


def test_progress_reporter_heartbeats_before_and_after_stream_activity() -> None:
    events: list[dict[str, object]] = []
    heartbeat_observed = threading.Event()
    post_stream_heartbeat_observed = threading.Event()

    def sink(event: dict[str, object]) -> None:
        events.append(event)
        if event["event"] == "heartbeat":
            heartbeat_observed.set()
            if event["stream_chunk_count"] == 1:
                post_stream_heartbeat_observed.set()

    reporter = FreshCoverageProgressReporter(
        sink,
        heartbeat_interval_seconds=0.01,
        execution_id="fresh-test-execution",
    )
    reporter.start()
    reporter.model_call_started(
        role="requirement_projection",
        attempt_index=1,
    )
    assert heartbeat_observed.wait(1.0)
    reporter.record_stream_activity(
        {
            "chunk_index": 1,
            "done": False,
            "content_utf8_bytes": 4,
        }
    )
    assert post_stream_heartbeat_observed.wait(1.0)
    reporter.model_call_finished(status="succeeded", error_code=None)
    reporter.finish(status="terminal", terminal_stage="requirement_coverage")
    event_count_after_finish = len(events)
    threading.Event().wait(0.03)

    assert len(events) == event_count_after_finish
    heartbeat = next(event for event in events if event["event"] == "heartbeat")
    assert heartbeat["execution_id"] == "fresh-test-execution"
    assert heartbeat["claim_scope"] == "operational_liveness_only"
    assert heartbeat["heartbeat_interval_seconds"] == 0.01
    assert heartbeat["model_role"] == "requirement_projection"
    assert heartbeat["attempt_index"] == 1
    assert heartbeat["stream_chunk_count"] == 0
    assert heartbeat["stream_content_utf8_bytes"] == 0
    assert heartbeat["seconds_since_stream_activity"] is None
    assert "content" not in heartbeat
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    first_stream_state = next(
        event for event in events if event["stream_chunk_count"] == 1
    )
    assert first_stream_state["event"] == "stream_started"
    assert events[-1]["event"] == "run_finished"


def test_progress_reporter_sink_failure_is_non_authoritative() -> None:
    reporter = FreshCoverageProgressReporter(
        lambda _event: (_ for _ in ()).throw(RuntimeError("sink failed")),
        heartbeat_interval_seconds=0.01,
        execution_id="fresh-failing-sink",
    )

    reporter.start()
    reporter.model_call_started(
        role="requirement_projection",
        attempt_index=1,
    )
    reporter.record_stream_activity(
        {
            "chunk_index": 1,
            "done": True,
            "content_utf8_bytes": 1,
        }
    )
    reporter.model_call_finished(status="succeeded", error_code=None)
    reporter.finish(status="terminal", terminal_stage="requirement_coverage")


def test_progress_reporter_thread_start_failure_is_non_authoritative(
    monkeypatch,
) -> None:
    events: list[dict[str, object]] = []

    def fail_start(_thread) -> None:
        raise RuntimeError("thread start failed")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    reporter = FreshCoverageProgressReporter(
        events.append,
        heartbeat_interval_seconds=0.01,
        execution_id="fresh-thread-start-failure",
    )

    reporter.start()
    reporter.model_call_started(
        role="requirement_projection",
        attempt_index=1,
    )
    reporter.model_call_finished(status="succeeded", error_code=None)
    reporter.finish(status="terminal", terminal_stage="requirement_coverage")

    unavailable = next(
        event for event in events if event["event"] == "heartbeat_unavailable"
    )
    assert unavailable["status"] == "degraded"
    assert unavailable["error_code"] == "FRESH_COVERAGE_HEARTBEAT_START_FAILED"
    assert events[-1]["event"] == "run_finished"


@pytest.mark.parametrize("drift_read_index", [2, 3])
def test_local_ollama_completion_checks_identity_before_and_after_model_call(
    monkeypatch,
    drift_read_index: int,
) -> None:
    read_count = 0
    provider_calls = 0

    def read_identity(_base_url, _model):
        nonlocal read_count
        read_count += 1
        identity = deepcopy(_MODEL_IDENTITY)
        if read_count == drift_read_index:
            identity["digest"] = "c" * 64
        return identity

    def handler(_role, _payload, _schema):
        nonlocal provider_calls
        provider_calls += 1
        return {"accepted": True}

    fake_llm = _real_ollama_llm(handler, monkeypatch)
    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.read_ollama_model_identity",
        read_identity,
    )
    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.read_ollama_server_version",
        lambda _base_url: "test-server",
    )
    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.LLMFactory.create",
        lambda _settings, **_options: fake_llm,
    )
    completion = create_local_ollama_requirement_coverage_completion(
        settings_path="config/settings.yaml",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="test-coverage-model",
        ollama_context_window=8192,
        ollama_output_budget=1024,
    )

    with pytest.raises(ModelAdmissionError, match="OLLAMA_MODEL_DIGEST_DRIFT"):
        completion(
            "requirement_projection",
            {"message_type": "product_requirement_projection"},
            {"type": "object"},
        )
    assert provider_calls == (0 if drift_read_index == 2 else 1)


def _feature_payload() -> dict[str, object]:
    return FeatureSpec(
        feature_id="feature_fresh_coverage",
        user_request="Change the marker to ChangeMarker.",
        target_behavior="Use ChangeMarker for the marker behavior.",
        non_goals=(),
        target_mod="SyntheticMod",
        risk_level="medium",
        acceptance_criteria=("Observe ChangeMarker after the change.",),
        evidence_requirements=(),
        runtime_verification_plan=(),
    ).to_artifact_payload()


def _projection() -> dict[str, object]:
    return {
        "requirements": [
            {
                "role": "change",
                "text": "Use ChangeMarker for the marker behavior.",
                "input_obligation_indexes": [1, 2],
                "query_leads": ["ChangeMarker"],
            }
        ],
        "input_dispositions": [],
    }


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    workspace = tmp_path / "workspace"
    source_root = workspace / "generated_mods" / "SyntheticMod"
    source_root.mkdir(parents=True)
    source = source_root / "Marker.cs"
    source.write_text(
        "namespace Synthetic;\n"
        "public class Marker\n"
        "{\n"
        "    public void Update()\n"
        "    {\n"
        "        var ChangeMarker = 1;\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    feature_path = tmp_path / "feature_spec.json"
    feature_path.write_text(
        json.dumps(_feature_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    return workspace, source_root, source, feature_path


def _successful_completion(roles: list[str]):
    def complete(role, payload, _schema):
        roles.append(role)
        if role == "requirement_projection":
            return deepcopy(_projection())
        if role == "requirement_findings":
            evidence_id = payload["source_observations"][0]["evidence_id"]
            return {
                "findings_by_relation": {
                    str(relation["relation_index"]): {
                        "relationship": "support",
                        "evidence_ids": [evidence_id],
                        "unresolved_gaps": [],
                    }
                    for relation in payload["relations"]
                }
            }
        raise AssertionError(role)

    return complete


def _run_cli(
    *,
    tmp_path: Path,
    feature_path: Path,
    workspace: Path,
    completion,
    monkeypatch,
) -> int:
    adapter = _local_completion(completion, monkeypatch)

    def create_completion(**kwargs):
        adapter.stream_activity_recorder = kwargs.get(
            "stream_activity_recorder"
        )
        return adapter

    monkeypatch.setattr(
        "src.mod_agent.cli.create_local_ollama_requirement_coverage_completion",
        create_completion,
    )
    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.read_ollama_model_identity",
        lambda _base_url, _model: deepcopy(_MODEL_IDENTITY),
    )
    return main(
        [
            "fresh-coverage",
            "--local-ollama",
            "--ollama-model",
            "test-coverage-model",
            "--ollama-context-window",
            "8192",
            "--feature-spec",
            str(feature_path),
            "--workspace-root",
            str(workspace),
            "--search-root",
            "generated_mods/SyntheticMod",
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )


def _assert_result_shape(result: dict[str, object]) -> None:
    assert set(result) == {
        "result_type",
        "status",
        "command",
        "terminal_stage",
        "first_failure",
        "readiness",
        "can_generate_patch",
        "query",
        "query_count",
        "item_count",
        "max_items",
        "model_execution",
        "feature_spec_artifact",
        "evidence_pack_artifact",
        "stopped_before",
        "execution_counts",
        "source_modified",
        "duration_seconds",
        "reason",
    }
    assert result["result_type"] == "fresh_requirement_coverage_result_v1"
    assert isinstance(result["duration_seconds"], float)
    assert result["duration_seconds"] >= 0.0


def test_fresh_coverage_cli_persists_success_and_stops_before_planning(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, source, feature_path = _write_inputs(tmp_path)
    source_before = hashlib.sha256(source.read_bytes()).hexdigest()
    roles: list[str] = []

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=_successful_completion(roles),
        monkeypatch=monkeypatch,
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    progress_events = [
        json.loads(line) for line in captured.err.splitlines() if line.strip()
    ]
    _assert_result_shape(result)
    assert exit_code == 0
    assert result["status"] == "terminal"
    assert result["terminal_stage"] == "requirement_coverage"
    assert result["first_failure"] is None
    assert result["readiness"] == "sufficient"
    assert result["can_generate_patch"] is True
    assert result["query_count"] == 1
    assert result["item_count"] == 1
    assert result["max_items"] == 1
    assert result["model_execution"]["roles"] == [
        "requirement_projection",
        "requirement_findings",
    ]
    assert result["model_execution"]["call_count"] == 2
    assert result["model_execution"]["correction_count"] == 0
    assert result["model_execution"]["budget"]["maximum_total_calls"] == 4
    for attempt in result["model_execution"]["attempts"]:
        assert attempt["status"] == "accepted"
        assert attempt["error_code"] is None
        assert attempt["duration_seconds"] >= 0.0
        for hash_field in (
            "payload_canonical_sha256",
            "schema_canonical_sha256",
            "output_canonical_sha256",
        ):
            assert len(attempt[hash_field]) == 64
    assert result["execution_counts"] == {
        "planning": 0,
        "patch": 0,
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }
    assert result["stopped_before"] == "implementation_planning"
    assert result["source_modified"] is False
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_before
    assert roles == result["model_execution"]["roles"]
    assert progress_events[0]["event"] == "run_started"
    assert progress_events[-1]["event"] == "run_finished"
    assert {
        event["event"] for event in progress_events
    } >= {
        "model_call_started",
        "stream_started",
        "stream_completed",
        "model_call_finished",
    }
    execution_ids = {event["execution_id"] for event in progress_events}
    assert len(execution_ids) == 1
    assert all(
        event["progress_type"] == "fresh_coverage_progress_v1"
        for event in progress_events
    )
    progress_text = captured.err
    for forbidden in (
        "Change the marker to ChangeMarker.",
        "generated_mods/SyntheticMod",
        str(workspace),
        '"message_type"',
        '"findings_by_relation"',
    ):
        assert forbidden not in progress_text

    store = ArtifactStore(tmp_path / "artifacts")
    evidence = store.read(ArtifactRef(**result["evidence_pack_artifact"]))["data"]
    assert evidence["readiness"] == "sufficient"
    assert evidence["can_generate_patch"] is True
    assert evidence["budget_summary"]["fresh_coverage_model_execution"] == (
        result["model_execution"]
    )
    artifact_types = {
        path.stem
        for path in (
            tmp_path / "artifacts" / "features" / "feature_fresh_coverage"
        ).glob("*.json")
    }
    assert artifact_types == {"feature_spec", "evidence_pack"}


def test_fresh_coverage_cli_frozen_duplicate_relation_indexes_fail_closed(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, source, feature_path = _write_inputs(tmp_path)
    source_before = source.read_bytes()
    frozen_path = (
        Path(__file__).parents[1]
        / "fixtures"
        / "requirement_findings_duplicate_relation_indexes.json"
    )
    frozen = json.loads(frozen_path.read_bytes())
    assert [item["relation_index"] for item in frozen["findings"]].count(1) > 1
    roles: list[str] = []

    def complete(role, _payload, _schema):
        roles.append(role)
        if role == "requirement_projection":
            return deepcopy(_projection())
        if role in {
            "requirement_findings",
            "requirement_findings_correction",
        }:
            return deepcopy(frozen)
        raise AssertionError(role)

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=complete,
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 1
    assert result["status"] == "blocked"
    assert result["terminal_stage"] == "requirement_coverage"
    assert result["first_failure"] == {
        "code": "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
        "stage": "requirement_findings",
    }
    assert result["readiness"] == "insufficient"
    assert result["can_generate_patch"] is False
    assert result["model_execution"]["roles"] == [
        "requirement_projection",
        "requirement_findings",
        "requirement_findings_correction",
    ]
    assert result["model_execution"]["call_count"] == 3
    assert result["model_execution"]["correction_count"] == 1
    assert [
        (attempt["role"], attempt["status"], attempt["error_code"])
        for attempt in result["model_execution"]["attempts"]
    ] == [
        ("requirement_projection", "accepted", None),
        (
            "requirement_findings",
            "rejected",
            "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
        ),
        (
            "requirement_findings_correction",
            "rejected",
            "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
        ),
    ]
    assert result["model_execution"]["call_count"] < (
        result["model_execution"]["budget"]["maximum_total_calls"]
    )
    assert result["execution_counts"] == {
        "planning": 0,
        "patch": 0,
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }
    assert source.read_bytes() == source_before
    assert roles == result["model_execution"]["roles"]


def test_fresh_coverage_cli_reports_recovered_first_failure_without_recomputing(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, source, feature_path = _write_inputs(tmp_path)
    source_before = source.read_bytes()
    roles: list[str] = []

    def complete(role, payload, _schema):
        roles.append(role)
        if role == "requirement_projection":
            return deepcopy(_projection())
        if role == "requirement_findings":
            return {"findings": []}
        if role == "requirement_findings_correction":
            evidence_id = payload["source_observations"][0]["evidence_id"]
            return {
                "findings_by_relation": {
                    str(relation["relation_index"]): {
                        "relationship": "support",
                        "evidence_ids": [evidence_id],
                        "unresolved_gaps": [],
                    }
                    for relation in payload["relations"]
                }
            }
        raise AssertionError(role)

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=complete,
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 0
    assert result["status"] == "terminal"
    assert result["first_failure"] == {
        "code": "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
        "stage": "requirement_findings",
    }
    assert result["readiness"] == "sufficient"
    assert result["can_generate_patch"] is True
    assert result["model_execution"]["roles"] == roles == [
        "requirement_projection",
        "requirement_findings",
        "requirement_findings_correction",
    ]
    assert result["model_execution"]["correction_count"] == 1
    assert [
        (attempt["role"], attempt["status"], attempt["error_code"])
        for attempt in result["model_execution"]["attempts"]
    ] == [
        ("requirement_projection", "accepted", None),
        (
            "requirement_findings",
            "rejected",
            "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
        ),
        ("requirement_findings_correction", "accepted", None),
    ]
    assert source.read_bytes() == source_before


def test_fresh_coverage_cli_requires_explicit_local_model_boundary(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, _source, feature_path = _write_inputs(tmp_path)
    factory_called = False

    def forbidden_factory(**_kwargs):
        nonlocal factory_called
        factory_called = True
        raise AssertionError("model factory must remain unreachable")

    monkeypatch.setattr(
        "src.mod_agent.cli.create_local_ollama_requirement_coverage_completion",
        forbidden_factory,
    )

    exit_code = main(
        [
            "fresh-coverage",
            "--feature-spec",
            str(feature_path),
            "--workspace-root",
            str(workspace),
            "--search-root",
            "generated_mods/SyntheticMod",
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {
        "code": "FRESH_COVERAGE_MODEL_BOUNDARY_NOT_AUTHORIZED",
        "stage": "model_admission",
    }
    assert result["readiness"] is None
    assert result["can_generate_patch"] is False
    assert result["model_execution"]["call_count"] == 0
    assert result["feature_spec_artifact"] is None
    assert result["evidence_pack_artifact"] is None
    assert result["execution_counts"] == {
        "planning": 0,
        "patch": 0,
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }
    assert factory_called is False


def test_fresh_coverage_cli_provider_runtime_error_retains_failed_attempt(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, source, feature_path = _write_inputs(tmp_path)
    source_before = source.read_bytes()

    def fail_provider(_role, _payload, _schema):
        raise RuntimeError("injected provider failure")

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=fail_provider,
        monkeypatch=monkeypatch,
    )

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    progress_events = [
        json.loads(line) for line in captured.err.splitlines() if line.strip()
    ]
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["status"] == "blocked"
    assert result["terminal_stage"] == "requirement_projection"
    assert result["first_failure"] == {
        "code": "FRESH_COVERAGE_MODEL_COMPLETION_FAILED",
        "stage": "requirement_projection",
    }
    assert result["reason"] == "FRESH_COVERAGE_MODEL_COMPLETION_FAILED"
    assert "injected provider failure" not in json.dumps(result)
    assert "injected provider failure" not in captured.err
    assert progress_events[-1]["event"] == "run_finished"
    assert progress_events[-1]["status"] == "blocked"
    assert result["readiness"] is None
    assert result["can_generate_patch"] is False
    assert result["feature_spec_artifact"]["artifact_type"] == "feature_spec"
    assert result["evidence_pack_artifact"] is None
    execution = result["model_execution"]
    assert execution["roles"] == ["requirement_projection"]
    assert execution["call_count"] == 1
    assert execution["correction_count"] == 0
    assert execution["budget"]["automatic_retry"] is False
    assert execution["budget"]["automatic_provider_fallback"] is False
    assert execution["attempts"] == [
        {
            **execution["attempts"][0],
            "attempt_index": 1,
            "role": "requirement_projection",
            "status": "failed",
            "error_code": "FRESH_COVERAGE_MODEL_COMPLETION_FAILED",
            "output_canonical_sha256": None,
        }
    ]
    assert execution["attempts"][0]["duration_seconds"] >= 0.0
    assert len(execution["attempts"][0]["payload_canonical_sha256"]) == 64
    assert len(execution["attempts"][0]["schema_canonical_sha256"]) == 64
    assert result["execution_counts"] == {
        "planning": 0,
        "patch": 0,
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }
    assert source.read_bytes() == source_before
    store = ArtifactStore(tmp_path / "artifacts")
    store.read(ArtifactRef(**result["feature_spec_artifact"]))
    assert {
        path.stem
        for path in (
            tmp_path / "artifacts" / "features" / "feature_fresh_coverage"
        ).glob("*.json")
    } == {"feature_spec"}


def test_fresh_coverage_cli_source_drift_retains_run_facts(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, source, feature_path = _write_inputs(tmp_path)

    def complete(role, payload, _schema):
        if role == "requirement_projection":
            return deepcopy(_projection())
        if role == "requirement_findings":
            source.write_text("changed during coverage\n", encoding="utf-8")
            evidence_id = payload["source_observations"][0]["evidence_id"]
            return {
                "findings_by_relation": {
                    str(relation["relation_index"]): {
                        "relationship": "support",
                        "evidence_ids": [evidence_id],
                        "unresolved_gaps": [],
                    }
                    for relation in payload["relations"]
                }
            }
        raise AssertionError(role)

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=complete,
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {
        "code": "FRESH_COVERAGE_SOURCE_CHANGED",
        "stage": "source_integrity",
    }
    assert result["source_modified"] is True
    assert result["model_execution"]["call_count"] == 2
    assert result["model_execution"]["roles"] == [
        "requirement_projection",
        "requirement_findings",
    ]
    assert result["feature_spec_artifact"]["artifact_type"] == "feature_spec"
    assert result["evidence_pack_artifact"] is None
    assert {
        path.stem
        for path in (
            tmp_path / "artifacts" / "features" / "feature_fresh_coverage"
        ).glob("*.json")
    } == {"feature_spec"}


def test_source_drift_preserves_earlier_recovered_model_rejection(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, source, feature_path = _write_inputs(tmp_path)

    def complete(role, payload, _schema):
        if role == "requirement_projection":
            return deepcopy(_projection())
        if role == "requirement_findings":
            return {"findings": []}
        if role == "requirement_findings_correction":
            source.write_text("changed after recovered rejection\n", encoding="utf-8")
            evidence_id = payload["source_observations"][0]["evidence_id"]
            return {
                "findings_by_relation": {
                    str(relation["relation_index"]): {
                        "relationship": "support",
                        "evidence_ids": [evidence_id],
                        "unresolved_gaps": [],
                    }
                    for relation in payload["relations"]
                }
            }
        raise AssertionError(role)

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=complete,
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {
        "code": "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
        "stage": "requirement_findings",
    }
    assert result["terminal_stage"] == "source_integrity"
    assert result["reason"] == "FRESH_COVERAGE_SOURCE_CHANGED"
    assert result["source_modified"] is True
    assert result["model_execution"]["call_count"] == 3
    assert result["feature_spec_artifact"]["artifact_type"] == "feature_spec"
    assert result["evidence_pack_artifact"] is None


def test_post_provider_source_snapshot_failure_retains_runner_facts(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, _source, feature_path = _write_inputs(tmp_path)
    from src.mod_agent import fresh_coverage as fresh_module

    original_snapshot = fresh_module._source_snapshot
    snapshot_calls = 0

    def fail_second_snapshot(root):
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 2:
            raise OSError(r"C:\private\source\secret.cs")
        return original_snapshot(root)

    monkeypatch.setattr(fresh_module, "_source_snapshot", fail_second_snapshot)
    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=_successful_completion([]),
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {
        "code": "FRESH_COVERAGE_SOURCE_SNAPSHOT_FAILED",
        "stage": "source_integrity",
    }
    assert result["terminal_stage"] == "source_integrity"
    assert result["reason"] == "FRESH_COVERAGE_SOURCE_SNAPSHOT_FAILED"
    assert result["source_modified"] is None
    assert result["model_execution"]["call_count"] == 2
    assert result["feature_spec_artifact"]["artifact_type"] == "feature_spec"
    assert result["evidence_pack_artifact"] is None
    assert "private" not in json.dumps(result)


def test_provider_failure_snapshot_error_does_not_hide_original_first_failure(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, _source, feature_path = _write_inputs(tmp_path)
    from src.mod_agent import fresh_coverage as fresh_module

    original_snapshot = fresh_module._source_snapshot
    snapshot_calls = 0

    def fail_second_snapshot(root):
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 2:
            raise OSError(r"C:\private\source\secret.cs")
        return original_snapshot(root)

    def fail_provider(_role, _payload, _schema):
        raise RuntimeError("provider details must not escape")

    monkeypatch.setattr(fresh_module, "_source_snapshot", fail_second_snapshot)
    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=fail_provider,
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {
        "code": "FRESH_COVERAGE_MODEL_COMPLETION_FAILED",
        "stage": "requirement_projection",
    }
    assert result["terminal_stage"] == "source_integrity"
    assert result["reason"] == "FRESH_COVERAGE_SOURCE_SNAPSHOT_FAILED"
    assert result["source_modified"] is None
    assert result["model_execution"]["call_count"] == 1
    assert result["feature_spec_artifact"]["artifact_type"] == "feature_spec"
    assert result["evidence_pack_artifact"] is None
    serialized = json.dumps(result)
    assert "private" not in serialized
    assert "provider details" not in serialized


def test_fresh_coverage_cli_invalid_budget_is_runner_owned(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, _source, feature_path = _write_inputs(tmp_path)

    class InvalidBudgetProvider:
        def collect(self, **_kwargs):
            return EvidencePack(
                query="bounded query",
                readiness="insufficient",
                can_generate_patch=False,
                budget_summary={"query_count": "one", "max_items": 1},
            )

    monkeypatch.setattr(
        "src.mod_agent.fresh_coverage.make_requirement_coverage_evidence_provider",
        lambda *_args, **_kwargs: InvalidBudgetProvider(),
    )
    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=_successful_completion([]),
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {
        "code": "FRESH_COVERAGE_BUDGET_SUMMARY_INVALID",
        "stage": "requirement_coverage",
    }
    assert result["feature_spec_artifact"]["artifact_type"] == "feature_spec"
    assert result["evidence_pack_artifact"] is None
    assert result["model_execution"]["call_count"] == 0


def test_fresh_coverage_cli_evidence_store_failure_is_runner_owned(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    workspace, _source_root, _source, feature_path = _write_inputs(tmp_path)
    monkeypatch.setattr(
        ArtifactStore,
        "write_with_result",
        lambda _self, **_kwargs: SimpleNamespace(
            outcome="partial",
            artifact_ref=None,
        ),
    )
    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=_successful_completion([]),
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {
        "code": "FRESH_COVERAGE_EVIDENCE_PACK_STORE_FAILED",
        "stage": "evidence_pack_store",
    }
    assert result["feature_spec_artifact"]["artifact_type"] == "feature_spec"
    assert result["evidence_pack_artifact"] is None
    assert result["model_execution"]["call_count"] == 2


@pytest.mark.parametrize(
    ("raw_json", "error_code"),
    [
        (
            '{"feature_id":"one","feature_id":"two"}',
            "FRESH_COVERAGE_FEATURE_SPEC_DUPLICATE_KEY",
        ),
        ('{"value":NaN}', "FRESH_COVERAGE_FEATURE_SPEC_NON_FINITE_NUMBER"),
        ('{"value":Infinity}', "FRESH_COVERAGE_FEATURE_SPEC_NON_FINITE_NUMBER"),
        ('{"value":-Infinity}', "FRESH_COVERAGE_FEATURE_SPEC_NON_FINITE_NUMBER"),
        ('{"value":1e999}', "FRESH_COVERAGE_FEATURE_SPEC_NON_FINITE_NUMBER"),
    ],
)
def test_fresh_coverage_cli_rejects_non_canonical_feature_spec_json(
    tmp_path: Path,
    capsys,
    monkeypatch,
    raw_json: str,
    error_code: str,
) -> None:
    workspace, _source_root, _source, feature_path = _write_inputs(tmp_path)
    feature_path.write_text(raw_json, encoding="utf-8")
    invoked = False

    def forbidden_completion(_role, _payload, _schema):
        nonlocal invoked
        invoked = True
        raise AssertionError("completion must remain unreachable")

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=forbidden_completion,
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {"code": error_code, "stage": "request"}
    assert result["model_execution"]["call_count"] == 0
    assert result["feature_spec_artifact"] is None
    assert result["evidence_pack_artifact"] is None
    assert invoked is False


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "error_code"),
    [
        (
            "risk_level",
            {"value": "medium"},
            "FRESH_COVERAGE_FEATURE_SPEC_RISK_LEVEL_INVALID",
        ),
        (
            "hook_requirement",
            "not-an-object",
            "FRESH_COVERAGE_FEATURE_SPEC_HOOK_REQUIREMENT_INVALID",
        ),
    ],
)
def test_fresh_coverage_cli_strict_feature_spec_rehydrate_is_zero_write(
    tmp_path: Path,
    capsys,
    monkeypatch,
    field_name: str,
    invalid_value: object,
    error_code: str,
) -> None:
    workspace, _source_root, _source, feature_path = _write_inputs(tmp_path)
    payload = _feature_payload()
    payload[field_name] = invalid_value
    feature_path.write_text(json.dumps(payload), encoding="utf-8")
    invoked = False

    def forbidden_completion(_role, _payload, _schema):
        nonlocal invoked
        invoked = True
        raise AssertionError("completion must remain unreachable")

    exit_code = _run_cli(
        tmp_path=tmp_path,
        feature_path=feature_path,
        workspace=workspace,
        completion=forbidden_completion,
        monkeypatch=monkeypatch,
    )

    result = json.loads(capsys.readouterr().out)
    _assert_result_shape(result)
    assert exit_code == 2
    assert result["first_failure"] == {"code": error_code, "stage": "request"}
    assert result["model_execution"]["call_count"] == 0
    assert result["feature_spec_artifact"] is None
    assert result["evidence_pack_artifact"] is None
    assert not (tmp_path / "artifacts").exists()
    assert invoked is False
