"""Recompute latency, completed-job throughput and failures from retained JSONL."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def percentile(values, quantile):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile*len(ordered))-1)] if ordered else None


def latency(values):
    return {"count": len(values), "p50_ms": percentile(values, .5), "p95_ms": percentile(values, .95),
        "max_ms": max(values) if values else None}


def summarize(rows):
    runs = {r["run_id"] for r in rows}
    if len(runs) != 1:
        raise ValueError("Summarize exactly one run id; do not merge separate runs or startup conditions")
    starts = [r for r in rows if r["event"] == "run_start"]
    stops = [r for r in rows if r["event"] == "run_stop"]
    begins = {r["operation_id"]: r for r in rows if r["event"] == "operation_start"}
    ends = [r for r in rows if r["event"] == "operation_end"]
    if len({r["operation_id"] for r in ends}) != len(ends):
        raise ValueError("Duplicate operation_end records; input files may overlap")
    http = [r for r in rows if r["event"] == "http"]
    if not starts:
        raise ValueError("No run_start; observation window is unknown")
    start = min(r["at"] for r in starts)
    stop = max([r["at"] for r in stops] + [r["finished_at"] for r in ends] + [start])
    seconds = stop-start
    modes = sorted({r["mode"] for r in begins.values()})
    groups = {}
    for mode in modes:
        initial = {k:r for k,r in begins.items() if r["mode"] == mode}
        terminal = [r for r in ends if r["mode"] == mode]
        admissions = [r for r in http if r["mode"] == mode and r["method"] == "POST"]
        polls = [r for r in http if r["mode"] == mode and r["method"] == "GET"]
        success = [r for r in terminal if r["outcome"] == "completed"]
        distinct = {}
        for r in success:
            previous = distinct.get(r["job_id"])
            if previous is None or r["started_at"] < previous["started_at"]:
                distinct[r["job_id"]] = r
        missing = sorted(set(initial)-{r["operation_id"] for r in terminal})
        counts = Counter(r["outcome"] for r in terminal)
        failed = len(terminal)-len(success)
        observed = [r for r in terminal if r.get("job_state") is not None]
        first_attempt = [r for r in observed if r.get("attempt") == 1]
        def intervals(left, right):
            return [(r[right]-r[left])*1000 for r in first_attempt
                if isinstance(r.get(left), (int, float)) and isinstance(r.get(right), (int, float))
                and r[right] >= r[left]]
        groups[mode] = {
            "operations_started": len(initial), "operations_with_final_observation": len(terminal),
            "unobserved_operation_ids": missing, "outcomes": dict(counts),
            "failed_or_interrupted_operations": failed, "unobserved_operations": len(missing),
            "failure_fraction_all_started": (failed+len(missing))/len(initial) if initial else None,
            "client_observation_timeouts": counts["client_observation_timeout"], "server_timeouts": counts["server_timed_out"],
            "admission_http_latency": latency([r["elapsed_ms"] for r in admissions]),
            "admission_http_statuses": dict(Counter(str(r["status"]) for r in admissions)),
            "http_submissions": len(admissions), "created_submissions": sum(r.get("created") is True for r in admissions),
            "idempotent_replayed_submissions": sum(r.get("created") is False and r["status"] == 200 for r in admissions),
            "admission_http_requests_per_second": len(admissions)/seconds if seconds > 0 else None,
            "poll_http_latency": latency([r["elapsed_ms"] for r in polls]),
            "poll_http_statuses": dict(Counter(str(r["status"]) for r in polls)),
            "job_observed_e2e_all_outcomes": latency([r["elapsed_ms"] for r in terminal]),
            "job_observed_e2e_success": latency([r["elapsed_ms"] for r in distinct.values()]),
            "server_first_attempt_queue": latency(intervals("job_created_at", "job_started_at")),
            "server_first_attempt_execution": latency(intervals("job_started_at", "job_finished_at")),
            "distinct_successful_jobs": len(distinct),
            "completed_jobs_per_second": len(distinct)/seconds if seconds > 0 else None,
            "cache_results_observed": dict(Counter(str(r.get("cache_result")) for r in observed)),
            "cache_hit_jobs": len({r["job_id"] for r in observed if r.get("cache_result") == "hit"}),
            "idempotency_checks_passed": sum(r.get("duplicate_verified") is True for r in terminal),
            "idempotency_checks_failed": sum(r.get("duplicate_verified") is False for r in terminal),
        }
    return {"schema": "service-load-summary.v1", "run_id": next(iter(runs)), "window_seconds": seconds,
        "window_start_unix": start, "window_end_unix": stop, "run_stop_observed": bool(stops), "groups": groups,
        "percentile_method": "nearest rank: sorted[ceil(q*N)-1]; no interpolation",
        "measurement_scope": "Client-observed closed-loop async sparse queries. Job latency includes admission, queue, worker startup/execution, polling and sample writing; success requires completed domain result plus expected source. Missing finals remain failures/unknown, never successes.",
        "throughput_denominator": "full observed run window including drain; count distinct successful job ids, not 202 responses",
        "limits": ["No LLM/dense/rerank performance measured", "No production-scale corpus generalization", "Client-observed terminal delay includes poll interval", "Separate container/host resource samples must be attached; absent resources are unknown"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows, refs, invalid = [], [], []
    for path in args.inputs:
        raw = path.read_bytes()
        refs.append({"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        for i,line in enumerate(raw.splitlines(), 1):
            try:
                value = json.loads(line)
                if value.get("schema") != "service-load-sample.v1":
                    raise ValueError("Wrong sample schema")
                rows.append(value)
            except (ValueError, AttributeError):
                invalid.append({"path": str(path), "line": i, "sha256": hashlib.sha256(line).hexdigest()})
    result = summarize(rows)
    result.update(raw_sample_refs=refs, malformed_lines=invalid, raw_samples_complete=not invalid)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(args.output), "groups": result["groups"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
