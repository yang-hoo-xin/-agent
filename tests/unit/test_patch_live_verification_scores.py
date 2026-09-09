"""Bound live verifier scores and sink behavior; all HTTP and records are local fixtures."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
from src.observability.patch_langfuse import LangfuseHttpTransport
from src.observability.patch_live_langfuse import (
    LIVE_BEHAVIOR_SCORE_NAME,
    OTLP_ENDPOINT,
    SCORE_ENDPOINT,
    PatchLiveLangfuseSink,
    build_patch_live_otlp,
    build_patch_live_scores,
    verified_behavior_trace_attributes,
)
from tests.unit.test_patch_execution_index import _retain
from tests.unit.test_patch_langfuse import _case
from tests.unit.test_patch_live_langfuse import _attributes, _row


def _verification(tmp_path):
    _, _, journal, _ = _case(tmp_path)
    factory = journal["factory_receipt"]
    report = deepcopy(factory["patch_agent_loop"]["behavior_evaluations"][0])
    response = deepcopy(factory["model_responses"][0])
    return report, response


def _verification_row(report, response):
    row = _row(kind="span", attributes={
        "verification_status": report["status"], "execution_origin": report["execution_origin"],
        "callback_invoked": report["callback_invoked"],
        "behavior_report_sha256": report["report_ref"]["sha256"],
        "output_code_sha256": report["materialized_code_identity"]["code_sha256"],
        "output_sha256": response["output_sha256"], "generated_changes_sha256": report["generated_changes_sha256"],
        **verified_behavior_trace_attributes(report, response),
    })
    row["name"] = "patch.verify"
    return row


def test_verified_matrix_produces_bound_local_fraction_without_secret_or_task_claim(tmp_path):
    report, response = _verification(tmp_path)
    row = _verification_row(report, response)
    scores = build_patch_live_scores(row)
    assert len(scores) == 1
    score = scores[0]
    assert score["traceId"] == row["trace_id"] and score["observationId"] == row["id"]
    assert score["name"] == LIVE_BEHAVIOR_SCORE_NAME and score["dataType"] == "NUMERIC"
    assert score["value"] == 0.5
    assert "not task acceptance" in score["comment"]
    exported = json.dumps({"observation": build_patch_live_otlp(row), "scores": scores})
    assert "SECRET" not in exported and "DO_NOT_PROJECT" not in exported and str(tmp_path) not in exported
    assert build_patch_live_scores(deepcopy(row)) == scores


@pytest.mark.parametrize("damage", ["response", "report", "matrix", "missing_matrix", "unexecuted", "reused", "unadmitted", "summary_mismatch"])
def test_absent_or_inconsistent_proof_produces_no_behavior_score(tmp_path, damage):
    report, response = _verification(tmp_path)
    if damage in {"response", "report", "matrix"}:
        target = response if damage == "response" else report["report_ref" if damage == "report" else "verification_ref"]
        Path(target["path"]).write_text("{}", encoding="utf-8")
    elif damage == "missing_matrix":
        report.pop("verification_ref")
    elif damage == "unexecuted":
        report["execution_origin"] = "unknown"
    elif damage == "reused":
        report.update(execution_origin="reused", callback_invoked=False)
    elif damage == "unadmitted":
        report["admission"] = "pending"
    else:
        report["verification_summary"]["checks"] = 3
    result = verified_behavior_trace_attributes(report, response)
    assert result["score_eligible"] is False
    assert "checks_run" not in result
    assert build_patch_live_scores(_verification_row(report, response)) == ()


@pytest.mark.parametrize("change", [
    {"checks_run": 0}, {"checks_run": True}, {"checks_run": -1},
    {"checks_failed": -1}, {"checks_failed": 3}, {"checks_failed": False},
    {"verification_executions": 0}, {"verification_executions": True},
    {"verification_status": "passed"}, {"execution_origin": "incomplete"},
    {"callback_invoked": False}, {"score_eligible": False}, {"admission_result": "rejected"},
    {"output_code_sha256": "C:/SECRET/code.cs"}, {"verification_matrix_sha256": None},
])
def test_untrusted_trace_counts_and_states_cannot_become_numeric_zero(tmp_path, change):
    report, response = _verification(tmp_path)
    row = _verification_row(report, response)
    row["attributes"].update(change)
    assert build_patch_live_scores(row) == ()


@pytest.mark.parametrize("passed", [False, True], ids=["executed-zero", "executed-one"])
def test_executed_extreme_scores_are_not_inferred_from_unknown_execution(tmp_path, passed):
    report, response = _verification(tmp_path)
    matrix_path = Path(report["verification_ref"]["path"])
    matrix = json.loads(matrix_path.read_text())
    for check in matrix["checks"]:
        check["passed"] = passed
    report["verification_ref"] = _retain(matrix_path, matrix)
    report["verification_summary"]["failed_checks"] = 0 if passed else 2
    report["status"] = "passed" if passed else "behavior_failed"
    report_path = Path(report["report_ref"]["path"])
    persisted = json.loads(report_path.read_text())
    persisted["verification_ref"] = report["verification_ref"]
    persisted["verification_summary"] = report["verification_summary"]
    persisted["status"] = report["status"]
    report["report_ref"] = _retain(report_path, persisted)
    row = _verification_row(report, response)
    assert build_patch_live_scores(row)[0]["value"] == float(passed)
    row["attributes"]["execution_origin"] = "unknown"
    assert build_patch_live_scores(row) == ()


@pytest.mark.parametrize("reply_hash", ["e" * 64, None])
def test_rehashed_report_cannot_contradict_current_response_even_when_code_matches(tmp_path, reply_hash):
    report, response = _verification(tmp_path)
    report_path = Path(report["report_ref"]["path"])
    persisted = json.loads(report_path.read_text())
    assert persisted["materialized_code_identity"] == report["materialized_code_identity"]
    persisted["model_response_sha256"] = reply_hash
    report["report_ref"] = _retain(report_path, persisted)
    assert verified_behavior_trace_attributes(report, response)["score_eligible"] is False
    assert build_patch_live_scores(_verification_row(report, response)) == ()


def _score_transport(monkeypatch, *, score_error=False, reject_span=False):
    calls = []

    def handle(request):
        assert request.method == "POST" and request.url.host == "langfuse.example"
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == OTLP_ENDPOINT:
            return httpx.Response(200, json={"partialSuccess": {"rejectedSpans": "1"}} if reject_span else {}, request=request)
        assert request.url.path == SCORE_ENDPOINT
        if score_error:
            raise httpx.ReadTimeout("SECRET_SCORE_TRANSPORT_MESSAGE", request=request)
        return httpx.Response(200, json={"id": payload["id"]}, request=request)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("No real Cloud writes"))
    monkeypatch.setattr("socket.socket.connect_ex", lambda *a, **k: pytest.fail("No real Cloud writes"))
    return LangfuseHttpTransport("https://langfuse.example", "pk-offline", "sk-offline", timeout_seconds=0.1), calls


def test_one_bounded_queue_posts_observation_then_score_and_deduplicates_both(tmp_path, monkeypatch):
    report, response = _verification(tmp_path)
    row = _verification_row(report, response)
    transport, calls = _score_transport(monkeypatch)
    sink = PatchLiveLangfuseSink(transport)
    sink.publish(row)
    sink.publish(deepcopy(row))
    result = sink.shutdown(timeout_millis=1000)
    assert [path for path, _ in calls] == [OTLP_ENDPOINT, SCORE_ENDPOINT]
    assert result["http_accepted"] == result["score_http_accepted"] == result["score_post_attempts"] == 1
    assert result["duplicate_records"] == 1 and result["remote_readback"] == "not_performed"
    assert "SECRET" not in json.dumps(calls)


@pytest.mark.parametrize("failure", ["score", "observation"])
def test_score_failure_is_separate_and_unaccepted_observation_cannot_create_orphan_score(tmp_path, monkeypatch, failure):
    report, response = _verification(tmp_path)
    row = _verification_row(report, response)
    transport, calls = _score_transport(monkeypatch, score_error=failure == "score", reject_span=failure == "observation")
    sink = PatchLiveLangfuseSink(transport)
    sink.publish(row)
    sink.flush(timeout_millis=1000)
    sink.publish(row)
    result = sink.shutdown(timeout_millis=1000)
    assert result["score_http_accepted"] == 0 and result["duplicate_records"] == 1
    if failure == "score":
        assert result["http_accepted"] == result["score_post_attempts"] == result["score_send_failures"] == 1
        assert len(calls) == 2
    else:
        assert result["partial_responses"] == result["score_skipped_unaccepted_observation"] == 1
        assert result["score_post_attempts"] == 0 and len(calls) == 1
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("projection_error", [False, True], ids=["bound-score", "projection-failure-open"])
def test_real_verifier_trace_producer_adds_only_verified_count_projection(tmp_path, monkeypatch, projection_error):
    report, response = _verification(tmp_path)
    adapter = LocalOllamaInitialPatchAdapter.__new__(LocalOllamaInitialPatchAdapter)
    adapter._receipt = {"model_response": response, "patch_agent_loop": {"behavior_evaluations": []}}
    monkeypatch.setattr(adapter, "_evaluate_generated_behavior_once", lambda *_args: report)
    if projection_error:
        def failed_projection(*_args):
            raise RuntimeError("SECRET_PROOF_ERROR")
        monkeypatch.setattr("src.observability.patch_live_langfuse._verified_check_counts", failed_projection)
    rows = []
    trace = ExecutionTrace("live-verifier-test", "session-test", "test", recorder=rows.append)
    with trace.activate():
        returned = adapter._evaluate_generated_behavior(SimpleNamespace(changes=[]), None)
    assert returned is report
    observed = next(row for row in reversed(rows) if row["name"] == "patch.verify" and row["status"] == "completed")
    assert observed["attributes"]["score_eligible"] is (not projection_error)
    if projection_error:
        assert "checks_run" not in observed["attributes"]
        assert build_patch_live_scores(observed) == ()
        assert "SECRET" not in json.dumps(build_patch_live_otlp(observed))
    else:
        assert observed["attributes"]["checks_run"] == 2
        assert len(build_patch_live_scores(observed)) == 1
