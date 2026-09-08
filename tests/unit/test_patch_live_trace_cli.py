"""Prospective tracing through the production external Patch/Repair entry.

HTTP model responses and the existing marker verifier are synthetic. This tests
the execution mechanism, not model quality, a real compiler, or Cloud delivery.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx

from src.mod_agent.external_patch import run_external_patch_continuation
from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.observability.patch_live_langfuse import build_patch_live_otlp, live_observation_id
from tests.unit.test_external_patch import _consent, _run
from tests.unit.test_external_patch import _install as _install_external
from tests.unit.test_fresh_planning_continuation import _patch_request, _source_hashes
from tests.unit.test_patch_submission_cli import _case, _install, _profile_json


def _journal(result):
    return json.loads(Path(result.attempt_receipt["path"]).read_text(encoding="utf-8"))


def _observations(result):
    by_id = _journal(result)["execution_observations"]
    assert all(key == row["id"] for key, row in by_id.items())
    return sorted(by_id.values(), key=lambda row: (row["started_at"], row["id"]))


def _run_with_trace(case, profile, consent, configuration, *, request=None):
    return run_external_patch_continuation(request or case.request, profile=profile,
        worker_configuration=PatchWorkerConfiguration.load(case.config_path),
        source_disclosure=consent, approved_source_files=_source_hashes(case.inputs.workspace),
        execution_trace_configuration=configuration)


class _RecordingSink:
    def __init__(self, *, fail=False):
        self.rows = []
        self.shutdown_calls = []
        self.fail = fail

    def publish(self, row):
        self.rows.append(row)
        if self.fail:
            raise RuntimeError("Service unavailable; confidential details stay local.")

    def shutdown(self, *, timeout_millis):
        self.shutdown_calls.append(timeout_millis)
        if self.fail:
            raise TimeoutError("Observability service unavailable.")
        return {"status": "offline_test_sink"}


class _FirstFinishedOtlpSink:
    """Freeze what a one-shot sender sees, before any late journal-only update."""

    def __init__(self):
        self.payloads = {}

    def publish(self, row):
        if row["finished_at"] is not None and row["id"] not in self.payloads:
            self.payloads[row["id"]] = build_patch_live_otlp(row)

    def shutdown(self, *, timeout_millis):
        return {"status": "offline_otlp_mapping", "timeout_millis": timeout_millis}


def _otlp_span(payload):
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def _otlp_attributes(span):
    return {row["key"]: next(iter(row["value"].values())) for row in span["attributes"]}


def _otlp_metadata(span):
    prefix = "langfuse.observation.metadata."
    return {key.removeprefix(prefix): value for key, value in _otlp_attributes(span).items()
            if key.startswith(prefix)}


def _assert_complete_tree(rows):
    assert rows
    by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows), "Journal must upsert observations, not append each update."
    roots = [row for row in rows if row["parent_id"] is None]
    assert len(roots) == 1
    assert len({row["trace_id"] for row in rows}) == 1
    assert len({row["session_id"] for row in rows}) == 1
    for row in rows:
        assert row["status"] in {"completed", "failed"}
        started = datetime.fromisoformat(row["started_at"])
        finished = datetime.fromisoformat(row["finished_at"])
        assert started.tzinfo is not None and finished.tzinfo is not None
        assert finished >= started and row["elapsed_ms"] >= 0
        if row["parent_id"] is not None:
            parent = by_id[row["parent_id"]]
            assert parent["trace_id"] == row["trace_id"]
            assert datetime.fromisoformat(parent["started_at"]) <= started
            assert datetime.fromisoformat(parent["finished_at"]) >= finished
        # Every branch must terminate at the root, rather than cycle.
        seen = {row["id"]}
        parent_id = row["parent_id"]
        while parent_id is not None:
            assert parent_id not in seen
            seen.add(parent_id)
            parent_id = by_id[parent_id]["parent_id"]


def test_public_repair_records_each_actual_send_and_closes_original_execution_tree(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["read", "prose", "failed", "read", "passed"])
    before = _source_hashes(case.inputs.workspace)

    result = _run(case, profile, _consent(profile))

    assert result.status == "terminal", result.to_dict()
    assert result.execution_counts["model"] == len(transport.wires) == 5
    assert result.execution_counts["review"] == result.execution_counts["dry_run"] == 1
    assert result.execution_counts["apply"] == result.execution_counts["build"] == result.execution_counts["runtime"] == 0
    assert _source_hashes(case.inputs.workspace) == before
    rows = _observations(result)
    _assert_complete_tree(rows)
    generations = [row for row in rows if row["kind"] == "generation"]
    requests = [row for row in rows if row["name"] == "model.request"]
    assert len(generations) == len(requests) == 5
    assert all(row["name"] == "patch.generate" for row in generations)
    assert all(row["status"] == "completed" for row in generations)
    assert {row["parent_id"] for row in generations} == {row["id"] for row in requests}
    receipt = _journal(result)["factory_receipt"]
    for generation, turn in zip(generations, receipt["worker_turns"], strict=True):
        attributes = generation["attributes"]
        assert attributes["turn_index"] == turn["turn_index"]
        assert generation["parent_id"] == turn["model_request_observation_id"]
        assert attributes["request_sha256"] == turn["request_sha256"]
        assert attributes["response_sha256"] == turn["response_ref"]["sha256"]
        assert attributes["request_bytes"] == len(Path(turn["request_ref"]["path"]).read_bytes())
        assert attributes["usage_available"] is True
        assert attributes["usage"] == {"input_tokens": 250, "output_tokens": 60}
        assert attributes["response_origin"] == "live_provider_response"
    tools = [row for row in rows if row["name"] == "source.inspect"]
    assert len(tools) == len(transport.reads) == 2
    for tool in tools:
        attributes = tool["attributes"]
        issuing = generations[attributes["turn_index"] - 1]
        assert attributes["tool_call_id"] in issuing["attributes"]["tool_call_ids"]
        assert attributes["binding_id"] in transport.reads
        assert attributes["observation_queued"] is True
        assert attributes["encoded_payload_bytes"] > 0
        consumed = {item["call_id"]: item["observation_sha256"]
                    for row in generations if row["attributes"]["turn_index"] > attributes["turn_index"]
                    for item in row["attributes"]["consumed_tool_results"]}
        assert consumed[attributes["tool_call_id"]] == attributes["encoded_payload_sha256"]
    submissions = [row for row in rows if row["name"] == "patch.submission"]
    assert [row["status"] for row in submissions] == ["failed", "completed", "completed"]
    assert all(row["attributes"]["behavior_validation_performed"] is False for row in submissions)
    verifications = [row for row in rows if row["name"] == "patch.verify"]
    reports = receipt["patch_agent_loop"]["behavior_evaluations"]
    assert len(verifications) == len(reports) == 2
    assert [row["attributes"]["verification_status"] for row in verifications] == ["behavior_failed", "passed"]
    for verification, report in zip(verifications, reports, strict=True):
        attributes = verification["attributes"]
        assert attributes["generated_changes_sha256"] == report["generated_changes_sha256"]
        assert attributes["output_sha256"] == report["model_response_sha256"]
        assert attributes["output_sha256"] in {row["attributes"]["output_sha256"] for row in generations}
        assert attributes["behavior_report_sha256"] == report["report_ref"]["sha256"]
        assert attributes["output_code_sha256"] == report["materialized_code_identity"]["code_sha256"]
        assert attributes["callback_invoked"] is True and attributes["execution_origin"] == "executed"
        materialized = [row for row in rows
                        if row["name"] == "patch.materialize" and row["parent_id"] == verification["id"]]
        assert len(materialized) == 1
        assert materialized[0]["attributes"]["output_code_sha256"] == attributes["output_code_sha256"]
    assert len([row for row in rows if row["name"] == "proposal.review"]) == 1
    assert len([row for row in rows if row["name"] == "patch.dry_run"]) == 1
    assert not any(row["attributes"].get("workflow_node") in {
        "apply", "build", "collect_runtime_evidence"} for row in rows)
    assert len(list(case.reports.glob("report-*.json"))) == 2
    assert "unit-test-secret" not in json.dumps(rows)
    assert "PreserveFeedback must remain unchanged." not in json.dumps(rows)
    assert all(output not in json.dumps(rows) for output in transport.outputs)


def test_terminal_cache_does_not_reexecute_or_rewrite_observation_history(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["passed"])
    sink = _RecordingSink()
    configuration = PatchExecutionTraceConfiguration(environment="offline-acceptance", sink=sink)
    first = _run_with_trace(case, profile, _consent(profile), configuration)
    assert first.status == "terminal", first.to_dict()
    path = Path(first.attempt_receipt["path"])
    original = path.read_bytes()
    calls = list(transport.calls)
    published = len(sink.rows)
    shutdown_calls = list(sink.shutdown_calls)

    resumed = _run_with_trace(case, profile, _consent(profile), configuration)

    assert resumed.patch_proposal_artifact == first.patch_proposal_artifact
    assert transport.calls == calls
    assert path.read_bytes() == original
    assert len(sink.rows) == published and sink.shutdown_calls == shutdown_calls
    assert len([row for row in _observations(resumed) if row["kind"] == "generation"]) == 1


def test_disclosure_rejected_before_execution_never_records_a_generation(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, [])

    result = _run(case, profile, _consent(profile, feedback=False))

    assert result.status != "terminal"
    assert result.execution_counts["model"] == 0 and transport.calls == []
    rows = _observations(result)
    _assert_complete_tree(rows)
    assert not any(row["kind"] == "generation" for row in rows)


def test_feedback_admission_failure_records_one_generation_for_two_model_requests(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["prose"])
    initial = replace(_patch_request(case.inputs), attempt_id="trace-format-feedback-unapproved")

    result = _run(case, profile, _consent(profile, feedback=False), request=initial)

    assert result.status != "terminal" and len(transport.wires) == 1
    rows = _observations(result)
    _assert_complete_tree(rows)
    generations = [row for row in rows if row["kind"] == "generation"]
    requests = [row for row in rows if row["name"] == "model.request"]
    assert len(generations) == 1 and len(requests) == 2
    assert requests[-1]["status"] == "failed"
    assert requests[-1]["id"] not in {row["parent_id"] for row in generations}


def test_http_timeout_has_real_failed_generation_without_fake_response_usage(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install_external(monkeypatch, timeout=True)

    result = _run(case, profile, _consent(profile))

    assert result.status != "terminal" and len(transport.wires) == 1
    rows = _observations(result)
    _assert_complete_tree(rows)
    generations = [row for row in rows if row["kind"] == "generation"]
    assert len(generations) == 1
    observed = generations[0]
    assert observed["status"] == "failed"
    assert observed["attributes"].get("response_received") is not True
    assert "usage" not in observed["attributes"]
    assert "unit-test-secret" not in json.dumps(rows)


def test_complete_http_response_with_invalid_json_remains_received_without_normalized_output(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    original = _install(monkeypatch, [])
    sent = []
    body = b'{"incomplete":'

    def respond(request):
        if request.method == "GET":
            return original(request)
        sent.append(request.content)
        return httpx.Response(200, content=body, request=request)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
                        lambda _self, request: transport.handle_request(request))

    result = _run(case, profile, _consent(profile))

    assert result.status != "terminal"
    assert result.execution_counts["model"] == len(sent) == 1
    journal = _journal(result)
    receipt = journal["factory_receipt"]
    physical_response = receipt["external_provider_requests"][0]
    assert physical_response["response_received"] is True
    assert physical_response["response_body_complete"] is True
    assert physical_response["http_status"] == 200
    assert physical_response["json_parse_status"] == "rejected"
    assert receipt["worker_turns"][0]["status"] == "failed"
    assert "response_ref" not in receipt["worker_turns"][0]
    rows = _observations(result)
    _assert_complete_tree(rows)
    generations = [row for row in rows if row["kind"] == "generation"]
    assert len(generations) == 1 and generations[0]["status"] == "failed"
    attributes = generations[0]["attributes"]
    assert attributes["response_received"] is True
    assert attributes["response_complete"] is True
    assert attributes["http_status"] == 200
    assert attributes["usage_available"] is False
    assert "usage" not in attributes
    assert "response_sha256" not in attributes and "output_sha256" not in attributes
    assert "unit-test-secret" not in json.dumps(rows)


def test_unavailable_observability_sink_preserves_product_result_and_local_tree(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["read", "prose", "failed", "read", "passed"])
    sink = _RecordingSink(fail=True)
    configuration = PatchExecutionTraceConfiguration(environment="offline-acceptance", sink=sink,
                                                     shutdown_timeout_millis=125)

    result = _run_with_trace(case, profile, _consent(profile), configuration)

    assert result.status == "terminal", result.to_dict()
    assert result.execution_counts["model"] == len(transport.wires) == 5
    assert result.execution_counts["review"] == result.execution_counts["dry_run"] == 1
    rows = _observations(result)
    _assert_complete_tree(rows)
    assert all(row["environment"] == "offline-acceptance" for row in rows)
    assert sink.shutdown_calls == [125]
    summary = _journal(result)["execution_trace"]
    assert summary["failures"]["sink"]["total"] == len(sink.rows) > 0
    assert summary["failures"]["sink"]["by_exception_type"] == {"RuntimeError": len(sink.rows)}
    assert summary["export"] == {"status": "failed_open", "error_type": "TimeoutError"}
    assert summary["cloud_readback"] == "not_performed"
    assert "confidential details" not in json.dumps(summary)


def test_distinct_attempts_have_distinct_traces_and_same_existing_feature_session(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["passed", "passed"])

    first = _run(case, profile, _consent(profile))
    second_request = replace(case.request, attempt_id="independent-trace-same-feature")
    second = _run(case, profile, _consent(profile), request=second_request)

    assert first.status == second.status == "terminal"
    assert len(transport.wires) == 2
    first_summary = _journal(first)["execution_trace"]
    second_summary = _journal(second)["execution_trace"]
    assert first_summary["trace_id"] != second_summary["trace_id"]
    assert first_summary["session_id"] == second_summary["session_id"]
    assert first_summary["mode"] == second_summary["mode"] == "local_only"
    # Correlation alone is not an approval/restart lifecycle acceptance.


def test_first_finished_otlp_keeps_tool_consumption_artifact_and_terminal_bindings(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["read", "prose", "failed", "read", "passed"])
    sink = _FirstFinishedOtlpSink()
    configuration = PatchExecutionTraceConfiguration(environment="offline-acceptance", sink=sink)

    result = _run_with_trace(case, profile, _consent(profile), configuration)

    assert result.status == "terminal", result.to_dict()
    assert result.execution_counts["model"] == len(transport.wires) == 5
    local_rows = _observations(result)
    assert set(sink.payloads) == {row["id"] for row in local_rows}
    spans = [_otlp_span(payload) for payload in sink.payloads.values()]
    by_id = {span["spanId"]: span for span in spans}
    assert set(by_id) == {live_observation_id(row["id"]) for row in local_rows}
    assert len({span["traceId"] for span in spans}) == 1
    for span in spans:
        if "parentSpanId" in span:
            assert span["parentSpanId"] in by_id
        assert int(span["endTimeUnixNano"]) >= int(span["startTimeUnixNano"]) > 0
        metadata = _otlp_metadata(span)
        assert metadata["metadata_only"] is True
        assert metadata["historical_import"] is False
        assert metadata["source_prompt_output_included"] is False
    generations = [span for span in spans
                   if _otlp_attributes(span)["langfuse.observation.type"] == "generation"]
    assert len(generations) == 5
    metadata_by_turn = {int(_otlp_metadata(span)["turn_index"]): _otlp_metadata(span)
                        for span in generations}
    for generation in generations:
        attributes = _otlp_attributes(generation)
        assert attributes["langfuse.observation.model.name"] == profile.model
        assert json.loads(attributes["langfuse.observation.usage_details"]) == {"input": 250, "output": 60}
    inspections = [span for span in spans if span["name"] == "source.inspect"]
    assert len(inspections) == 2
    for inspection in inspections:
        metadata = _otlp_metadata(inspection)
        turn = int(metadata["turn_index"])
        call_hash = metadata["call_id_sha256"]
        assert call_hash in json.loads(metadata_by_turn[turn]["tool_call_id_sha256s"])
        consumed = {row["call_id_sha256"]: row["observation_sha256"]
                    for next_turn, values in metadata_by_turn.items() if next_turn > turn
                    for row in json.loads(values["consumed_tool_results"])}
        assert consumed[call_hash] == metadata["encoded_payload_sha256"]
        assert metadata["observation_queued"] is True
    for name, artifact in (("proposal.review", result.proposal_review_artifact),
                           ("patch.dry_run", result.dry_run_artifact)):
        selected = [span for span in spans if span["name"] == name]
        assert len(selected) == 1
        refs = json.loads(_otlp_metadata(selected[0])["artifact_refs"])
        assert refs == [{"artifact_type": artifact["artifact_type"], "artifact_hash": artifact["artifact_hash"]}]
    roots = [span for span in spans if "parentSpanId" not in span]
    assert len(roots) == 1
    root_metadata = _otlp_metadata(roots[0])
    assert root_metadata["workflow_status"] == result.status
    assert root_metadata["terminal_stage"] == result.terminal_stage
    assert root_metadata["proposal_admitted"] is True
    serialized = json.dumps(sink.payloads)
    assert "unit-test-secret" not in serialized
    assert "PreserveFeedback must remain unchanged." not in serialized
    assert all(output not in serialized for output in transport.outputs)
    assert str(case.inputs.workspace) not in serialized
