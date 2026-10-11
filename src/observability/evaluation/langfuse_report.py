"""Bounded RAG report/transport-journal bridge to Langfuse experiments.

Reuses the existing HTTP transport. Preparing a payload is offline. Publishing
requires an explicit CLI action and separately obtained disclosure permission.
No inference is rerun, and missing timing or scores are never synthesized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.observability.patch_langfuse import LangfuseHttpTransport, _attribute
from src.observability.patch_langfuse_query import _same_observed_time


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Recorded timestamps must have a timezone.")
    return stamp


def _nanos(value: str) -> str:
    stamp = _time(value)
    return str(int(stamp.timestamp()) * 1_000_000_000 + stamp.microsecond * 1000)


def _iso_nanos(value: str) -> str:
    seconds, remainder = divmod(int(value), 1_000_000_000)
    return (datetime.fromtimestamp(seconds, timezone.utc) + timedelta(microseconds=remainder // 1000)).isoformat()


def _state(value: dict) -> dict:
    return {k: value.get(k) for k in ("status", "mode", "error_category")}


def prepare_export(report: dict, journal: list[dict], *, include_public_text: bool = False) -> dict:
    """Map only observed case times and matching invocation HTTP events."""
    meta = report["run_metadata"]
    invocation = meta.get("execution_invocation_id")
    if not invocation:
        raise ValueError("A captured execution_invocation_id is required.")
    events = [row for row in journal if row.get("invocation_id") == invocation]
    if not events or not any(row.get("event") == "cli_result" for row in events):
        raise ValueError("The journal does not contain this completed CLI invocation.")
    experiment_id = meta["run_id"]
    dataset_id = meta["test_set"]["sha256"]
    if not dataset_id:
        raise ValueError("A bound dataset hash is required.")
    binding = {
        "run_id": experiment_id, "execution_invocation_id": invocation,
        "report_sha256": _hash(report), "invocation_events_sha256": _hash(events),
        "dataset_sha256": dataset_id,
        "settings_sha256": meta["settings"]["sha256"],
        "judge_settings_sha256": meta["judge_settings"]["sha256"],
        "bm25_index_sha256": meta["bm25_index"]["sha256"],
        "top_k": meta["top_k"], "dense_enabled": meta["dense_enabled"],
        "measurement_status": report["measurement_status"],
        "metric_measurements": report["metric_measurements"],
        "public_text_included": include_public_text,
        "unattempted_cases": [{"case_index": c["case_index"], "query_sha256": _hash(c["query"]),
                               "metric_measurements": c["metric_measurements"]}
                              for c in report["query_results"] if not c.get("started_at")],
    }
    for name in ("answer_model", "judge_model", "embedding_model", "judge_embedding_model"):
        value = meta.get(name)
        binding[name] = {k: value.get(k) for k in ("provider", "model", "server_revision")} if value else None
    def attempts(event):
        indexed = {}
        for row in (row for row in events if row.get("event") == event):
            if row["attempt"] in indexed:
                raise ValueError("Duplicate captured attempt identity.")
            indexed[row["attempt"]] = row
        return indexed

    requests, results = attempts("request"), attempts("result")
    if set(requests) != set(results):
        raise ValueError("Captured requests and results do not match.")
    spans, scores, items, skipped = [], [], [], []
    common = {"langfuse.experiment.id": experiment_id,
              "langfuse.experiment.name": f"rag-{experiment_id}",
              "langfuse.experiment.dataset.id": dataset_id,
              "langfuse.environment": "experiment"}
    common.update({f"langfuse.experiment.metadata.{k}": v for k, v in binding.items()})
    used_attempts = set()
    for case in report["query_results"]:
        index = case["case_index"]
        if not case.get("started_at") or not case.get("finished_at"):
            skipped.append({"case_index": index, "reason": "no_recorded_execution_time",
                            "metric_measurements": case["metric_measurements"]})
            continue
        start, end = _time(case["started_at"]), _time(case["finished_at"])
        if start > end:
            raise ValueError("Case time order is invalid.")
        trace_id = _hash([experiment_id, index])[:32]
        root_id = _hash([trace_id, "case"])[:16]
        item_id = _hash([dataset_id, index, case["query"]])
        attrs = {**common, "langfuse.experiment.item.id": item_id,
                 "langfuse.experiment.item.root_observation_id": root_id,
                 "langfuse.observation.type": "chain", "langfuse.trace.name": "RAG evaluation",
                 "langfuse.observation.metadata.case_index": index,
                 "langfuse.observation.metadata.report_sha256": binding["report_sha256"],
                 "langfuse.observation.metadata.metric_measurements": case["metric_measurements"]}
        failed = False
        for stage in ("retrieval_measurement", "answer_measurement", "evaluator_measurement"):
            attrs[f"langfuse.observation.metadata.{stage}"] = _state(case[stage])
            failed |= case[stage]["status"] == "failed_to_measure"
        contexts = [{"chunk_id": c["chunk_id"], "text_sha256": _hash(c["text"]),
                     **({"text": c["text"]} if include_public_text else {})}
                    for c in case["retrieved_contexts"]]
        observed_output = {"retrieved_contexts": contexts, "answer_sha256": _hash(case["generated_answer"])}
        observed_input = {"query_sha256": _hash(case["query"])}
        if include_public_text:
            observed_input["query"] = case["query"]
            observed_output["answer"] = case["generated_answer"]
            attrs["langfuse.experiment.item.expected_output"] = case["reference_answer"]
        attrs["langfuse.observation.input"] = observed_input
        attrs["langfuse.observation.output"] = observed_output
        attrs["langfuse.observation.level"] = "ERROR" if failed else "DEFAULT"
        spans.append({"traceId": trace_id, "spanId": root_id, "name": "rag.case", "kind": 1,
                      "startTimeUnixNano": _nanos(case["started_at"]),
                      "endTimeUnixNano": _nanos(case["finished_at"]),
                      "status": {"code": 2 if failed else 1},
                      "attributes": [_attribute(k, v) for k, v in attrs.items()]})
        item = {"case_index": index, "trace_id": trace_id, "root_id": root_id, "item_id": item_id,
                "span_ids": [root_id], "input": observed_input, "output": observed_output,
                "expected_output": case["reference_answer"] if include_public_text else None}
        items.append(item)
        for attempt, request in requests.items():
            if not start <= _time(request["utc"]) <= end:
                continue
            result = results.get(attempt)
            if result is None or not _time(request["utc"]) <= _time(result["utc"]) <= end:
                raise ValueError("Captured request has no bound completed timing.")
            if attempt in used_attempts:
                raise ValueError("Captured request belongs to overlapping cases.")
            used_attempts.add(attempt)
            span_id = _hash([trace_id, attempt])[:16]
            item["span_ids"].append(span_id)
            body = request.get("json") or {}
            if "input" in body:
                kind, operation = "embedding", "rag.scoring_embedding"
            elif "response_format" in body:
                kind, operation = "evaluator", "rag.judge"
            else:
                kind, operation = "generation", "rag.answer"
            child_attrs = {**common, "langfuse.experiment.item.id": item_id,
                           "langfuse.experiment.item.root_observation_id": root_id,
                           "langfuse.observation.type": kind,
                           "langfuse.observation.model.name": request.get("model"),
                           "langfuse.observation.metadata.http_attempt": attempt,
                           "langfuse.observation.metadata.request_sha256": request["body_sha256"],
                           "langfuse.observation.metadata.response_sha256": result.get("body_sha256"),
                           "langfuse.observation.metadata.transport_status": result["status"],
                           "langfuse.observation.metadata.classification": result.get("classification")}
            spans.append({"traceId": trace_id, "spanId": span_id, "parentSpanId": root_id,
                          "name": operation, "kind": 1, "startTimeUnixNano": _nanos(request["utc"]),
                          "endTimeUnixNano": _nanos(result["utc"]),
                          "status": {"code": 2 if result["status"] == "failed" else 1},
                          "attributes": [_attribute(k, v) for k, v in child_attrs.items()]})
        for name, value in case["metrics"].items():
            if case["metric_measurements"].get(name) != "observed":
                continue
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Only finite observed scores can be exported.")
            scores.append({"id": _hash([trace_id, name]), "traceId": trace_id, "observationId": root_id,
                           "name": name, "value": value, "dataType": "NUMERIC",
                           "comment": "Ragas measurement; not Mod correctness or delivery."})
    if set(requests) != used_attempts:
        raise ValueError("Some invocation requests have no exact case time binding.")
    if not spans:
        raise ValueError("No recorded cases can be exported.")
    times = [s["startTimeUnixNano"] for s in spans]
    export = {"experiment_id": experiment_id, "dataset_id": dataset_id, "binding": binding,
            "items": items, "skipped_cases": skipped, "scores": scores,
            "from_start_time": (datetime.fromtimestamp(min(map(int, times)) / 1e9, start.tzinfo)
                                - timedelta(seconds=1)).isoformat(),
            "to_start_time": (max(_time(c["finished_at"]) for c in report["query_results"]
                                   if c.get("finished_at")) + timedelta(seconds=1)).isoformat(),
            "otlp": {"resourceSpans": [{"resource": {"attributes": [_attribute("service.name", "rag-evaluation")]},
                                         "scopeSpans": [{"scope": {"name": "rag.evaluation", "version": "1"},
                                                         "spans": spans}]}]}}
    json.dumps(export, allow_nan=False)
    return export


def readback(export: dict, transport: LangfuseHttpTransport) -> dict:
    """One bounded query round; missing or mismatched data never counts as delivery."""
    window = {"fromStartTime": export["from_start_time"], "toStartTime": export["to_start_time"], "limit": 100}
    experiments = transport._request("GET", "/api/public/experiments", params={
        **window, "id": export["experiment_id"], "fields": "core,metadata"})
    items = transport._request("GET", "/api/public/experiment-items", params={
        **window, "experimentId": export["experiment_id"], "fields": "core,io,metadata,scores"})
    observations = [transport._request("GET", "/api/public/v2/observations", params={
        "traceId": item["trace_id"], "fields": "core,basic,metadata", "limit": 1000}) for item in export["items"]]
    scores = transport._request("GET", "/api/public/v3/scores", params={
        "traceId": ",".join(item["trace_id"] for item in export["items"]),
        "fields": "details,subject", "limit": 100})
    envelopes = [experiments, items, scores, *observations]
    if any(not isinstance(row.get("data"), list) for row in envelopes):
        raise ValueError("Invalid Langfuse readback envelope.")
    complete = not any((row.get("meta") or {}).get("cursor") for row in envelopes)
    runs = [row for row in experiments["data"] if row["id"] == export["experiment_id"]]
    complete &= len(runs) == 1 and runs[0].get("datasetId") == export["dataset_id"]
    if len(runs) == 1:
        remote_binding = runs[0].get("metadata") or {}
        complete &= (isinstance(remote_binding, dict)
                     and all(remote_binding.get(k) == v for k, v in export["binding"].items()))
    for item, observed in zip(export["items"], observations):
        roots = [row for row in items["data"] if row.get("traceId") == item["trace_id"]
                 and row.get("experimentItemId") == item["item_id"]
                 and row.get("experimentId") == export["experiment_id"]]
        complete &= len(roots) == 1 and roots[0].get("input") == item["input"] and roots[0].get("output") == item["output"]
        if len(roots) == 1:
            complete &= roots[0].get("expectedOutput") == item["expected_output"]
        complete &= set(item["span_ids"]) <= {row["id"] for row in observed["data"]
                                              if row.get("traceId") == item["trace_id"]}
        expected_spans = export["otlp"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        for span in (span for span in expected_spans if span["traceId"] == item["trace_id"]):
            matches = [row for row in observed["data"] if row.get("id") == span["spanId"]
                       and row.get("traceId") == item["trace_id"]]
            if len(matches) != 1:
                complete = False
                continue
            remote_meta = matches[0].get("metadata") or {}
            complete &= matches[0].get("parentObservationId") == span.get("parentSpanId")
            complete &= _same_observed_time(_iso_nanos(span["startTimeUnixNano"]), matches[0].get("startTime"))
            complete &= _same_observed_time(_iso_nanos(span["endTimeUnixNano"]), matches[0].get("endTime"))
            attrs = {a["key"]: a["value"] for a in span["attributes"]}
            for key in ("report_sha256", "request_sha256", "response_sha256"):
                expected = attrs.get(f"langfuse.observation.metadata.{key}")
                if expected is not None:
                    complete &= remote_meta.get(key) == expected.get("stringValue")
    for score in export["scores"]:
        matches = [row for row in scores["data"] if row.get("id") == score["id"]]
        complete &= len(matches) == 1 and matches[0].get("value") == score["value"] and matches[0].get("name") == score["name"]
        if matches:
            value = matches[0].get("value")
            complete &= (matches[0].get("dataType") == "NUMERIC"
                         and type(value) in (int, float) and math.isfinite(value))
            subject = matches[0].get("subject") or {}
            complete &= subject.get("kind") == "observation" and subject.get("id") == score["observationId"] and subject.get("traceId") == score["traceId"]
    return {"status": "verified_remote_readback" if complete else "readback_pending_or_mismatch",
            "experiments": experiments, "items": items, "observations": observations, "scores": scores}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-public-text", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--readback", action="store_true")
    parser.add_argument("--max-requests", type=int, default=32)
    parser.add_argument("--readback-rounds", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args(argv)
    if args.max_requests < 1:
        parser.error("--max-requests must be positive.")
    export = prepare_export(json.loads(args.report.read_text(encoding="utf-8")),
                            [json.loads(row) for row in args.journal.read_text(encoding="utf-8").splitlines()],
                            include_public_text=args.include_public_text)
    result = {"export": export, "status": "offline_prepared", "cloud_requests": 0}
    if args.publish or args.readback:
        transport = LangfuseHttpTransport.from_environment()
        request = transport._request

        def bounded_request(*a, **kw):
            if result["cloud_requests"] >= args.max_requests:
                raise ValueError("Cloud request budget exhausted.")
            result["cloud_requests"] += 1
            return request(*a, **kw)

        transport._request = bounded_request
        try:
            if args.publish:
                response = transport._request("POST", "/api/public/otel/v1/traces", payload=export["otlp"])
                rejected = int((response.get("partialSuccess") or {}).get("rejectedSpans") or 0)
                if rejected != 0:
                    raise ValueError("Langfuse rejected spans.")
                for score in export["scores"]:
                    transport._request("POST", "/api/public/scores", payload=score)
            result["readback_rounds"] = []
            for index in range(args.readback_rounds):
                observed = readback(export, transport)
                result["readback_rounds"].append(observed)
                result["status"] = observed["status"]
                if result["status"] == "verified_remote_readback":
                    break
                if index + 1 < args.readback_rounds:
                    time.sleep(2)
        except Exception as exc:
            result.update(status="cloud_failed", error_category=type(exc).__name__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "cloud_requests")}))
    return 0 if result["status"] in {"offline_prepared", "verified_remote_readback"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
