"""RAG experiment mapping and strict readback, with no network/model access."""
import copy
import json
import socket

import pytest

from src.observability.evaluation.langfuse_report import _iso_nanos, prepare_export, readback


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("No network in mapping tests"))


@pytest.fixture
def inputs():
    state = {"status": "observed", "mode": "real", "error_category": None,
             "error_message": "LOCAL_PRIVATE_EXCEPTION_TEXT"}
    meta = {"run_id": "run-1", "execution_invocation_id": "inv-1", "top_k": 3, "dense_enabled": False,
            "answer_model": {"provider": "openai", "model": "gpt-4o-2024-08-06", "server_revision": "unknown"}}
    for name in ("test_set", "settings", "judge_settings", "bm25_index"):
        meta[name] = {"path": "LOCAL_PRIVATE_PATH", "sha256": "a" * 64}
    report = {"run_metadata": meta, "measurement_status": "partial", "metric_measurements": {},
              "query_results": [{"case_index": 0, "query": "Public RFC question", "generated_answer": "Public answer",
                                 "reference_answer": "Public reference", "metrics": {"faithfulness": 0.0},
                                 "metric_measurements": {"faithfulness": "observed", "answer_relevancy": "failed_to_measure"},
                                 "retrieved_contexts": [{"chunk_id": "c1", "text": "Public source", "score": 1.0,
                                                         "metadata": {"source_path": "LOCAL_PRIVATE_PATH"}}],
                                 **{k: copy.deepcopy(state) for k in ("retrieval_measurement", "answer_measurement", "evaluator_measurement")},
                                 "started_at": "2026-09-20T01:00:00+00:00", "finished_at": "2026-09-20T01:00:10+00:00"}]}
    journal = [{"event": "request", "invocation_id": "inv-1", "attempt": 1,
                "utc": "2026-09-20T01:00:01+00:00", "json": {"messages": []},
                "model": "gpt-4o-2024-08-06", "body_sha256": "b" * 64},
               {"event": "result", "invocation_id": "inv-1", "attempt": 1,
                "utc": "2026-09-20T01:00:02+00:00", "status": "received", "body_sha256": "c" * 64},
               {"event": "cli_result", "invocation_id": "inv-1", "exit_code": 1}]
    return report, journal


def test_export_binds_actual_calls_preserves_zero_and_excludes_private_metadata(inputs):
    report, journal = inputs
    export = prepare_export(report, journal, include_public_text=True)
    text = json.dumps(export)
    assert "LOCAL_PRIVATE" not in text
    assert "Public source" in text
    assert len(export["scores"]) == 1 and export["scores"][0]["value"] == 0.0
    spans = export["otlp"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 2
    assert spans[1]["parentSpanId"] == spans[0]["spanId"]
    assert spans[0]["traceId"] == spans[1]["traceId"]
    assert "Public source" not in json.dumps(prepare_export(report, journal))


def test_unattempted_case_keeps_denominator_without_fabricated_span(inputs):
    report, journal = inputs
    unattempted = copy.deepcopy(report["query_results"][0])
    unattempted.update(case_index=1, started_at=None, finished_at=None, metrics={},
                       metric_measurements={"faithfulness": "failed_to_measure"})
    report["query_results"].append(unattempted)
    report["metric_measurements"] = {"faithfulness": {"total": 2, "observed": 1, "failed_to_measure": 1}}
    export = prepare_export(report, journal)
    assert len(export["items"]) == 1
    assert export["skipped_cases"][0]["case_index"] == 1
    assert export["binding"]["metric_measurements"]["faithfulness"]["total"] == 2


@pytest.mark.parametrize("change", ["invocation", "outside_case", "missing_result", "missing_time", "nan", "duplicate"])
def test_unbound_or_nonfinite_data_cannot_be_exported(inputs, change):
    report, journal = inputs
    if change == "invocation":
        report["run_metadata"]["execution_invocation_id"] = "other-invocation"
    elif change == "outside_case":
        journal[0]["utc"] = "2026-09-20T02:00:00+00:00"
    elif change == "missing_result":
        journal.pop(1)
    elif change == "missing_time":
        report["query_results"][0]["started_at"] = None
    elif change == "duplicate":
        journal.insert(0, copy.deepcopy(journal[0]))
    else:
        report["query_results"][0]["metrics"]["faithfulness"] = float("nan")
    with pytest.raises(ValueError):
        prepare_export(report, journal)


class ReadbackTransport:
    def __init__(self, export):
        self.export = export
        self.corrupt = False
        self.calls = []

    def _request(self, method, path, *, params):
        self.calls.append((method, path, params))
        assert method == "GET"
        export = self.export
        item = export["items"][0]
        if path == "/api/public/experiments":
            data = [{"id": export["experiment_id"], "datasetId": export["dataset_id"], "metadata": export["binding"]}]
        elif path == "/api/public/experiment-items":
            data = [{"traceId": item["trace_id"], "experimentItemId": item["item_id"],
                     "experimentId": export["experiment_id"], "input": item["input"], "output": item["output"],
                     "expectedOutput": item["expected_output"]}]
        elif path == "/api/public/v2/observations":
            data = []
            for span in export["otlp"]["resourceSpans"][0]["scopeSpans"][0]["spans"]:
                metadata = {a["key"].removeprefix("langfuse.observation.metadata."): a["value"].get("stringValue")
                            for a in span["attributes"] if a["key"].startswith("langfuse.observation.metadata.")}
                if self.corrupt:
                    metadata["report_sha256"] = "stale-report"
                data.append({"id": span["spanId"], "traceId": span["traceId"], "metadata": metadata,
                             "parentObservationId": span.get("parentSpanId"),
                             "startTime": _iso_nanos(span["startTimeUnixNano"]),
                             "endTime": _iso_nanos(span["endTimeUnixNano"])})
        else:
            assert path == "/api/public/v3/scores"
            data = [{**s, "subject": {"kind": "observation", "traceId": s["traceId"], "id": s["observationId"]}}
                    for s in export["scores"]]
        return {"data": data, "meta": {"cursor": None}}


def test_readback_requires_same_inputs_hashes_scores_and_trace_binding(inputs):
    export = prepare_export(*inputs, include_public_text=True)
    transport = ReadbackTransport(export)
    assert readback(export, transport)["status"] == "verified_remote_readback"
    assert len(transport.calls) == 4
    transport.corrupt = True
    assert readback(export, transport)["status"] == "readback_pending_or_mismatch"


@pytest.mark.parametrize("fail_post", [False, True])
def test_publish_counts_requests_and_does_not_retry_failed_send(inputs, monkeypatch, tmp_path, fail_post):
    from src.observability.evaluation.langfuse_report import LangfuseHttpTransport, main

    report, journal = inputs
    export = prepare_export(report, journal, include_public_text=True)

    class Transport(ReadbackTransport):
        def _request(self, method, path, *, params=None, payload=None):
            if method == "POST":
                self.calls.append((method, path, payload))
                if fail_post:
                    raise RuntimeError("controlled HTTP failure")
                return {"partialSuccess": {"rejectedSpans": "0"}}
            return super()._request(method, path, params=params)

    transport = Transport(export)
    monkeypatch.setattr(LangfuseHttpTransport, "from_environment", lambda: transport)
    report_path, journal_path, output = tmp_path / "report.json", tmp_path / "journal.jsonl", tmp_path / "cloud.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    journal_path.write_text("\n".join(json.dumps(row) for row in journal), encoding="utf-8")
    code = main(["--report", str(report_path), "--journal", str(journal_path), "--output", str(output),
                 "--include-public-text", "--publish", "--max-requests", "6"])
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["cloud_requests"] == (1 if fail_post else 6)
    assert code == (1 if fail_post else 0)
    assert len(transport.calls) == receipt["cloud_requests"]
    if not fail_post:
        assert receipt["status"] == "verified_remote_readback"


@pytest.mark.parametrize("defect", ["dataset", "metadata", "reference", "parent", "time", "boolean_score"])
def test_readback_rejects_mismatched_cloud_facts(inputs, defect):
    export = prepare_export(*inputs, include_public_text=True)

    class CorruptTransport(ReadbackTransport):
        def _request(self, method, path, *, params):
            result = copy.deepcopy(super()._request(method, path, params=params))
            row = result["data"][0]
            if path == "/api/public/experiments" and defect in {"dataset", "metadata"}:
                row["datasetId" if defect == "dataset" else "metadata"] = "wrong"
            elif path == "/api/public/experiment-items" and defect == "reference":
                row["expectedOutput"] = "wrong"
            elif path == "/api/public/v2/observations" and defect in {"parent", "time"}:
                row["parentObservationId" if defect == "parent" else "startTime"] = "wrong"
            elif path == "/api/public/v3/scores" and defect == "boolean_score":
                row.update(dataType="BOOLEAN", value=False)
            return result

    assert readback(export, CorruptTransport(export))["status"] == "readback_pending_or_mismatch"
