"""Historical exporter uses real HTTP serialization with an isolated fake server."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from src.mod_agent.fresh_planning_continuation import _canonical_sha256
from src.observability.patch_langfuse import (
    LangfuseHttpTransport,
    PatchLangfuseError,
    prepare_patch_import,
)
from tests.unit.test_patch_execution_index import _fixture, _retain

IMPORT_TIME = datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc)


def _case(tmp_path):
    root, path, journal, _ = _fixture(tmp_path)
    code = {"baseline_sha256": "sha256:" + "a" * 64, "code_sha256": "sha256:" + "b" * 64,
            "files": ["SECRET_PROJECT_PATH.cs"]}
    matrix = _retain(tmp_path / "checks/matrix.json", {
        "executions": 2, "checks": [{"check": "ONE", "passed": True, "actual": "SECRET_ACTUAL_SOURCE"},
                                    {"check": "TWO", "passed": False, "expected": "SECRET_EXPECTED_SOURCE"}]})
    report = _retain(tmp_path / "checks/report.json", {"status": "behavior_failed", "generated_changes_sha256": "c" * 64,
        "materialized_code_identity": code, "verification_ref": matrix, "prompt": "SECRET_PROMPT",
        "execution_origin": "executed", "source_snapshot_sha256": "d" * 64,
        "verification_summary": {"checks": 2, "failed_checks": 1, "executions": 2}})
    factory = journal["factory_receipt"]
    response = factory["worker_turns"][0]["response_ref"]
    factory["worker_turns"][0]["usage"] = {"input_tokens": 17, "output_tokens": 4, "total_tokens": 21}
    journal["model_call_count"] = 1
    journal["max_model_calls"] = 5
    journal["failure"] = {"code": "PATCH_BEHAVIOR_CORRECTION_FAILED", "message": "SECRET_DIAGNOSTIC"}
    evaluation = factory["patch_agent_loop"]["behavior_evaluations"][0]
    evaluation.update(report_ref=report, verification_ref=matrix, admission="accepted", execution_origin="executed",
        callback_invoked=True, generated_changes_sha256="c" * 64, model_response_sha256=response["sha256"],
        source_snapshot_sha256="d" * 64, materialized_code_identity=code,
        verification_summary={"checks": 2, "failed_checks": 1, "executions": 2})
    journal["terminal_result"].update(reason="SECRET_FAILURE_TEXT", product_source_writes_performed=False)
    journal["terminal_result_sha256"] = _canonical_sha256(journal["terminal_result"])
    _retain(path, journal)
    return root, path, journal, matrix


def _prepare(root, path):
    return prepare_patch_import(root, attempt_locator=str(path), imported_at=IMPORT_TIME)


class _Backend:
    def __init__(self, *, partial=False, timeout=False, read_delay=0):
        self.calls = []
        self.observations = {}
        self.scores = {}
        self.partial, self.timeout, self.read_delay = partial, timeout, read_delay

    def __call__(self, request):
        assert request.url.host == "langfuse.example" and request.url.scheme == "https"
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.headers["x-langfuse-ingestion-version"] == "4"
        payload = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, payload))
        if request.method == "GET" and request.url.path == "/api/public/v2/observations":
            assert request.url.params["fields"] == "core,basic,metadata"
            rows = list(self.observations.values())
            if rows and self.read_delay:
                self.read_delay -= 1
                rows = []
            return httpx.Response(200, json={"data": rows, "meta": {"cursor": None}}, request=request)
        if request.method == "GET" and request.url.path == "/api/public/v3/scores":
            score = self.scores.get(request.url.params["id"])
            return httpx.Response(200, json={"data": [score] if score else [], "meta": {}}, request=request)
        if request.method == "POST" and request.url.path == "/api/public/otel/v1/traces":
            if self.timeout:
                raise httpx.ReadTimeout("SECRET_PROVIDER_EXCEPTION", request=request)
            for span in payload["resourceSpans"][0]["scopeSpans"][0]["spans"]:
                attributes = {row["key"]: row["value"] for row in span["attributes"]}
                metadata = {key.removeprefix("langfuse.observation.metadata."): value.get("stringValue")
                            for key, value in attributes.items() if key.startswith("langfuse.observation.metadata.")}
                self.observations[span["spanId"]] = {"id": span["spanId"], "traceId": span["traceId"], "metadata": metadata}
            return httpx.Response(200, json={"partialSuccess": {"rejectedSpans": "1"}} if self.partial else {}, request=request)
        if request.method == "POST" and request.url.path == "/api/public/scores":
            self.scores[payload["id"]] = {**payload, "subject": {"kind": "observation", "id": payload["observationId"],
                                                               "traceId": payload["traceId"]}}
            return httpx.Response(200, json={"id": payload["id"]}, request=request)
        raise AssertionError((request.method, request.url.path))


def _transport(monkeypatch, **options):
    backend = _Backend(**options)
    transport = httpx.MockTransport(backend)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Real network forbidden in export tests.")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)
    client = LangfuseHttpTransport("https://langfuse.example", "pk-test", "sk-test", readback_delay_seconds=0)
    return client, backend


def test_metadata_preview_retains_facts_without_prompt_code_paths_or_invented_original_time(tmp_path, monkeypatch):
    root, path, _, _ = _case(tmp_path)
    _, backend = _transport(monkeypatch)
    before = {str(file): file.read_bytes() for file in tmp_path.rglob("*.json")}
    batch = _prepare(root, path)
    serialized = json.dumps(batch.preview())
    assert "SECRET" not in serialized and "DO_NOT_PROJECT" not in serialized
    assert str(tmp_path) not in serialized and "SECRET_PROJECT_PATH" not in serialized
    spans = batch.otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(batch.trace_id) == 32 and all(len(span["spanId"]) == 16 for span in spans)
    assert all(span["startTimeUnixNano"] == span["endTimeUnixNano"] == "1788768000000000000" for span in spans)
    assert batch.preview()["original_event_time"] == "unknown"
    assert batch.scores[0]["value"] == 0.5
    assert backend.calls == []
    assert {str(file): file.read_bytes() for file in tmp_path.rglob("*.json")} == before
    other = prepare_patch_import(root, attempt_locator=str(path), imported_at=datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert other.trace_id == batch.trace_id and other.observation_ids == batch.observation_ids
    assert other.scores == batch.scores


def test_http_import_readback_and_second_import_do_not_duplicate_spans_or_scores(tmp_path, monkeypatch):
    root, path, _, _ = _case(tmp_path)
    batch = _prepare(root, path)
    client, backend = _transport(monkeypatch)
    result = client.import_history(batch)
    assert result["status"] == "verified_remote_readback", result
    assert result["observation_posts"] == 1 and result["score_posts"] == 1
    assert client.read_observation(batch.trace_id, batch.observation_ids[0])["id"] == batch.observation_ids[0]
    assert client.read_score(batch.scores[0]["id"])["value"] == 0.5
    posts = [call for call in backend.calls if call[0] == "POST"]
    second = client.import_history(batch)
    assert second["status"] == "already_present" and second["observation_posts"] == second["score_posts"] == 0
    assert [call for call in backend.calls if call[0] == "POST"] == posts
    assert "sk-test" not in repr(client) and "pk-test" not in repr(client)


def test_delayed_read_visibility_is_bounded_without_post_retry(tmp_path, monkeypatch):
    root, path, _, _ = _case(tmp_path)
    client, backend = _transport(monkeypatch, read_delay=2)
    result = client.import_history(_prepare(root, path))
    assert result["status"] == "verified_remote_readback"
    assert len([call for call in backend.calls if call[:2] == ("POST", "/api/public/otel/v1/traces")]) == 1


@pytest.mark.parametrize("mode", ["timeout", "partial", "pending"])
def test_uncertain_or_partial_delivery_never_claims_success_or_automatically_resends(tmp_path, monkeypatch, mode):
    root, path, _, _ = _case(tmp_path)
    batch = _prepare(root, path)
    client, backend = _transport(monkeypatch, timeout=mode == "timeout", partial=mode == "partial", read_delay=10 if mode == "pending" else 0)
    result = client.import_history(batch)
    assert result["status"] == {"timeout": "export_failed_open", "partial": "partial_ingestion", "pending": "readback_pending"}[mode]
    assert "SECRET_PROVIDER_EXCEPTION" not in json.dumps(result)
    before = len([call for call in backend.calls if call[0] == "POST"])
    second = client.import_history(batch)
    assert second["status"] in {"reconciliation_required_no_resend", "already_present"}
    assert len([call for call in backend.calls if call[0] == "POST"]) == before
    assert result["product_state_changed"] is False


def test_source_drift_after_preparation_stops_before_any_http(tmp_path, monkeypatch):
    root, path, journal, _ = _case(tmp_path)
    batch = _prepare(root, path)
    journal["factory_receipt"]["worker_turns"][0]["status"] = "requested"
    _retain(path, journal)
    client, backend = _transport(monkeypatch)
    result = client.import_history(batch)
    assert result["error_code"] == "HISTORICAL_SOURCE_CHANGED_SINCE_PREPARATION"
    assert backend.calls == []


@pytest.mark.parametrize("invalid", ["missing_terminal_hash", "terminal_hash_mismatch", "not_executed", "matrix_incomplete"])
def test_missing_or_corrupt_evidence_cannot_create_a_behavior_score(tmp_path, invalid):
    root, path, journal, matrix = _case(tmp_path)
    if invalid == "missing_terminal_hash":
        del journal["terminal_result_sha256"]
    elif invalid == "terminal_hash_mismatch":
        journal["terminal_result_sha256"] = "0" * 64
    elif invalid == "not_executed":
        journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]["execution_origin"] = "unknown"
    else:
        changed = json.loads(Path(matrix["path"]).read_bytes())
        changed["checks"].pop()
        replacement = _retain(Path(matrix["path"]), changed)
        journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]["verification_ref"] = replacement
    _retain(path, journal)
    if invalid.startswith("missing_terminal") or invalid == "terminal_hash_mismatch":
        with pytest.raises(PatchLangfuseError, match="VERIFIED_TERMINAL"):
            _prepare(root, path)
    else:
        assert _prepare(root, path).scores == ()


def test_unrelated_matrix_with_identical_counts_cannot_borrow_report_score(tmp_path):
    root, path, journal, _ = _case(tmp_path)
    unrelated = _retain(tmp_path / "other/matrix.json", {
        "executions": 2, "checks": [{"check": "UNRELATED_A", "passed": True},
                                    {"check": "UNRELATED_B", "passed": False}],
    })
    journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]["verification_ref"] = unrelated
    _retain(path, journal)
    imported = _prepare(root, path)
    assert imported.observation_ids  # Metadata import is still available.
    assert imported.scores == ()


@pytest.mark.parametrize("invalid", ["missing_matrix_link", "matrix_code_mismatch", "persisted_not_executed",
                                      "missing_code_bytes", "report_denominator_mismatch"])
def test_score_requires_complete_agreeing_report_matrix_and_retained_code(tmp_path, invalid):
    root, path, journal, _ = _case(tmp_path)
    evaluation = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]
    report_path = Path(evaluation["report_ref"]["path"])
    report = json.loads(report_path.read_bytes())
    if invalid == "missing_matrix_link":
        del report["verification_ref"]
    elif invalid == "matrix_code_mismatch":
        matrix_path = Path(evaluation["verification_ref"]["path"])
        matrix = json.loads(matrix_path.read_bytes())
        matrix["materialized_code_identity"] = {**evaluation["materialized_code_identity"], "code_sha256": "sha256:" + "f" * 64}
        replacement = _retain(matrix_path, matrix)
        report["verification_ref"] = replacement
        evaluation["verification_ref"] = replacement
    elif invalid == "persisted_not_executed":
        report["execution_origin"] = "incomplete"
    elif invalid == "missing_code_bytes":
        # The original declared hash still matches; the referenced response no longer does.
        Path(journal["factory_receipt"]["model_responses"][0]["path"]).write_bytes(b"changed response")
    else:
        report["verification_summary"]["checks"] = 3
    evaluation["report_ref"] = _retain(report_path, report)
    _retain(path, journal)
    imported = _prepare(root, path)
    assert imported.scores == () and imported.observation_ids
    behavior = next(span for span in imported.otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
        if span["name"] == "historical.behavior_verification_record")
    attributes = {entry["key"]: entry["value"] for entry in behavior["attributes"]}
    assert attributes["langfuse.observation.metadata.score_eligible"] == {"boolValue": False}


def test_explicit_matrix_identities_must_agree_with_the_bound_report(tmp_path):
    root, path, journal, _ = _case(tmp_path)
    evaluation = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]
    matrix_path = Path(evaluation["verification_ref"]["path"])
    matrix = json.loads(matrix_path.read_bytes())
    matrix.update({key: evaluation[key] for key in (
        "source_snapshot_sha256", "generated_changes_sha256", "materialized_code_identity")})
    evaluation["verification_ref"] = _retain(matrix_path, matrix)
    report_path = Path(evaluation["report_ref"]["path"])
    report = json.loads(report_path.read_bytes())
    report["verification_ref"] = evaluation["verification_ref"]
    evaluation["report_ref"] = _retain(report_path, report)
    _retain(path, journal)
    assert _prepare(root, path).scores[0]["value"] == 0.5


def test_payload_mutation_cannot_smuggle_source_through_a_prepared_batch(tmp_path, monkeypatch):
    root, path, _, _ = _case(tmp_path)
    batch = _prepare(root, path)
    batch.otlp["resourceSpans"][0]["resource"]["attributes"].append({"key": "source", "value": {"stringValue": "SECRET_SOURCE"}})
    client, backend = _transport(monkeypatch)
    assert client.import_history(batch)["error_code"] == "HISTORICAL_SOURCE_CHANGED_SINCE_PREPARATION"
    assert backend.calls == []


def test_environment_keys_are_not_loaded_for_prepare_or_logged(tmp_path, monkeypatch):
    root, path, _, _ = _case(tmp_path)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "SECRET_KEY_VALUE")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "PUBLIC_KEY_VALUE")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")
    batch = _prepare(root, path)
    assert "SECRET_KEY_VALUE" not in json.dumps(batch.preview())
    assert "SECRET_KEY_VALUE" not in repr(LangfuseHttpTransport.from_environment())


def test_free_text_and_secret_shaped_machine_labels_are_hashed(tmp_path):
    root, path, journal, _ = _case(tmp_path)
    journal["factory_receipt"]["worker_turns"][0]["status"] = "SECRET_VALID_LABEL"
    journal["failure"]["code"] = "SECRET_MACHINE_DIAGNOSTIC"
    _retain(path, journal)
    value = json.dumps(_prepare(root, path).preview())
    assert "SECRET_VALID_LABEL" not in value and "SECRET_MACHINE_DIAGNOSTIC" not in value
    assert "redacted:sha256:" in value


@pytest.mark.parametrize("url", ["http://remote.example", "https://user:password@example.com", "https://example.com/?secret=x"])
def test_unsafe_endpoint_forms_are_rejected_without_network(url):
    with pytest.raises(PatchLangfuseError, match="BASE_URL"):
        LangfuseHttpTransport(url, "pk", "sk")
