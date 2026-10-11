"""Run selected existing pytest cases and summarize identity-bound evidence.

The manifest maps semantic scenarios to pytest selectors; this reuses the
repository's existing checks, rather than introducing another product scorer.
为什么要有它：模块、场景、参数案例和重复执行分别计数，不能用断言数充当真实任务数。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    nodes = manifest["nodes"]
    seen = set()
    for row in nodes:
        selector = row["nodeid"]
        if selector in seen or "::" not in selector or not selector.startswith("tests/"):
            raise ValueError("Duplicate or non-test selector: " + selector)
        if ".." in Path(selector.split("::")[0]).parts:
            raise ValueError("Selector escapes source root")
        seen.add(selector)
        for key in ("module_id", "scenario_id", "assertion", "evidence_kind"):
            if not row.get(key):
                raise ValueError("Missing case contract: " + key)
    if not nodes:
        raise ValueError("Empty selection")
    return manifest


def owner(nodeid, nodes):
    matches = [row for row in nodes if nodeid == row["nodeid"] or
               nodeid.startswith(row["nodeid"] + "[") or nodeid.startswith(row["nodeid"] + "::")]
    if len(matches) != 1:
        raise ValueError("Missing or overlapping case ownership: " + nodeid)
    return matches[0]


def summarize_events(events, nodes):
    collected, started, phases, errors = [], [], {}, []
    for event in events:
        kind = event["kind"]
        if kind == "collected":
            collected.extend(event["nodeids"])
        elif kind == "started":
            started.append(event["nodeid"])
        elif kind == "phase":
            phases.setdefault(event["nodeid"], []).append(event)
        elif kind == "collection_error":
            errors.append(event)
    # 为什么要有它：重复日志或重复选中不能放大样本量；参数实例仍保留独立 case_id。
    if len(set(started)) != len(started) or len(set(collected)) != len(collected):
        raise ValueError("Duplicate case events within one invocation")
    if not set(started).issubset(collected):
        raise ValueError("Executed case missing from collection")
    rows = []
    for nodeid in collected:
        spec = owner(nodeid, nodes)
        reports = phases.get(nodeid, [])
        by_phase = {report["phase"]: report for report in reports}
        if len(by_phase) != len(reports):
            raise ValueError("Duplicate phase report")
        if any(report["outcome"] == "failed" for report in reports):
            status = "failed" if by_phase.get("call", {}).get("outcome") == "failed" else "error"
        elif any(report.get("wasxfail") for report in reports):
            status = "expected_failure_or_xpass"
        elif any(report["outcome"] == "skipped" for report in reports):
            status = "skipped"
        elif all(by_phase.get(phase, {}).get("outcome") == "passed" for phase in ("setup", "call", "teardown")):
            status = "passed"
        else:
            status = "incomplete" if nodeid in started else "not_executed"
        rows.append({**spec, "case_id": nodeid, "started": nodeid in started,
                     "call_executed": "call" in by_phase, "status": status,
                     "elapsed_seconds": sum(report["duration_seconds"] for report in reports)})
    matched = {row["nodeid"] for row in rows}
    missing = [row["nodeid"] for row in nodes if row["nodeid"] not in matched]
    return {"cases": rows, "collection_errors": errors, "missing_selectors": missing,
            "collected_cases": len(collected), "started_cases": len(started),
            "call_executions": sum(row["call_executed"] for row in rows),
            "status_counts": dict(Counter(row["status"] for row in rows))}


def verify_source(source, receipt):
    root = source.resolve()
    changed = []
    for name, expected in receipt["files"].items():
        target = root / name
        if not target.resolve().is_relative_to(root) or target.is_symlink():
            raise ValueError("Snapshot path escape")
        expected_hash = expected["sha256"] if isinstance(expected, dict) else expected
        if not target.is_file() or digest(target) != expected_hash:
            changed.append(name)
    return changed


def run(args):
    manifest = read_manifest(args.manifest)
    manifest_hash, receipt_hash = digest(args.manifest), digest(args.receipt)
    source = args.source.resolve()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8-sig"))
    if verify_source(source, receipt):
        raise ValueError("Snapshot changed before execution")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    nodes = [row for row in manifest["nodes"] if not args.module or row["module_id"] in args.module]
    if not nodes:
        raise ValueError("Empty selected modules")
    temporary = Path(tempfile.mkdtemp(prefix="medd-")) / "t"
    events_path = output / "events.jsonl"
    command = [str(args.python.resolve()), "-B", "-m", "pytest", "-q", "--tb=short", "-o", "addopts=",
               "-p", "scripts.module_evaluation_plugin", "-p", "no:cacheprovider",
               "--basetemp", str(temporary), "--junitxml", str(output / "junit.xml")]
    command.extend(row["nodeid"] for row in nodes)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               MODULE_EVALUATION_EVENTS=str(events_path), PYTHONPATH=str(source))
    write_once(output / "command.json", {"argv": command, "cwd": str(source),
        "manifest": {"path": str(args.manifest.resolve()), "sha256": digest(args.manifest)},
        "receipt": {"path": str(args.receipt.resolve()), "sha256": digest(args.receipt)},
        "started_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "launcher_python": sys.version, "modules": args.module or "all", "timeout_seconds": args.timeout,
        "temporary_test_artifacts": str(temporary), "environment_recorded": "only explicit nonsecret overrides",
        "overrides": {key: env[key] for key in ("PYTHONUTF8", "PYTHONDONTWRITEBYTECODE", "MODULE_EVALUATION_EVENTS", "PYTHONPATH")}})
    began = time.perf_counter()
    timed_out = False
    with (output / "stdout.txt").open("w", encoding="utf-8") as stdout, (output / "stderr.txt").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=source, env=env, stdout=stdout, stderr=stderr)
        try:
            exit_code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=stderr, stderr=stderr, check=False)
            else:
                process.kill()
            exit_code = process.wait(timeout=30)
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()] if events_path.exists() else []
    result = summarize_events(events, nodes)
    changed = verify_source(source, receipt)
    result.update(schema_version="module_evaluation_run.v1", elapsed_seconds=time.perf_counter() - began,
                  finished_utc=datetime.now(timezone.utc).isoformat(), pytest_exit_code=exit_code,
                  timed_out=timed_out, changed_source_paths=changed, source_binding_stable=not changed,
                  manifest_sha256=manifest_hash, receipt_sha256=receipt_hash,
                  model_tokens=None, inference_cost=None,
                  evidence_scope="selected engineering checks; not independent Mod deliveries")
    result["control_inputs_changed"] = digest(args.manifest) != manifest_hash or digest(args.receipt) != receipt_hash
    result["source_binding_stable"] = not changed and not result["control_inputs_changed"]
    write_once(output / "result.json", result)
    print(json.dumps({key: result[key] for key in ("collected_cases", "started_cases", "call_executions", "status_counts", "elapsed_seconds", "pytest_exit_code", "missing_selectors", "changed_source_paths")}, ensure_ascii=False))
    return 0 if exit_code == 0 and not timed_out and result["source_binding_stable"] and not result["missing_selectors"] else 1


def aggregate(paths):
    attempts, identities, hashes = [], set(), set()
    for path in paths:
        path = path.resolve()
        value_hash = digest(path)
        if path in identities or value_hash in hashes:
            raise ValueError("Duplicate run reference")
        identities.add(path)
        hashes.add(value_hash)
        result = json.loads(path.read_text(encoding="utf-8"))
        attempts.append({"path": str(path), "sha256": digest(path), "result": result})
    cases = [row for attempt in attempts for row in attempt["result"]["cases"]]
    started = [row for row in cases if row["started"]]
    complete = [row for attempt in attempts if attempt["result"]["source_binding_stable"]
                for row in attempt["result"]["cases"] if row["status"] == "passed"]
    return {"schema_version": "module_evaluation_summary.v1", "run_refs": [{key: a[key] for key in ("path", "sha256")} for a in attempts],
        "batch_invocations": len(attempts), "unique_started_cases": len({row["case_id"] for row in started}),
        "case_attempts": len(started), "call_executions": sum(row["call_executed"] for row in cases),
        "case_status_counts": dict(Counter(row["status"] for row in cases)),
        "modules_attempted": sorted({row["module_id"] for row in started}),
        "scenarios_attempted": sorted({(row["module_id"], row["scenario_id"]) for row in started}),
        "unique_passed_cases": len({row["case_id"] for row in complete}),
        "elapsed_seconds": sum(a["result"]["elapsed_seconds"] for a in attempts),
        "versions": sorted({a["result"]["receipt_sha256"] for a in attempts}),
        "invalid_binding_runs": [a["path"] for a in attempts if not a["result"]["source_binding_stable"]],
        "collection_errors": sum(len(a["result"]["collection_errors"]) for a in attempts),
        "missing_selectors_by_run": {a["path"]: a["result"]["missing_selectors"] for a in attempts if a["result"]["missing_selectors"]},
        "abnormal_runs": [{"path": a["path"], "timed_out": a["result"].get("timed_out"),
                           "pytest_exit_code": a["result"].get("pytest_exit_code")}
                          for a in attempts if a["result"].get("timed_out") or a["result"].get("pytest_exit_code") not in (0, None)],
        "claim_boundary": "engineering verification cases; repeats are attempts, not new tasks; defects require separate adjudicated evidence"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    execute = sub.add_parser("run")
    for flag in ("manifest", "source", "receipt", "output"):
        execute.add_argument("--" + flag, type=Path, required=True)
    execute.add_argument("--python", type=Path, default=Path(sys.executable))
    execute.add_argument("--timeout", type=int, default=300)
    execute.add_argument("--module", action="append")
    report = sub.add_parser("summarize")
    report.add_argument("results", nargs="+", type=Path)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "run":
        return run(args)
    result = aggregate(args.results)
    write_once(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
