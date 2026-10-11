"""Bounded, explicit-container Docker stats sampling and reproducible summaries."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import time

ROLES = {"api", "worker", "redis", "prometheus"}
SCHEMA = "service-resource-sample.v1"
SCOPE = "Explicit project containers only; Docker CLI stats units, not host-total resources or external LLM/GPU/load-generator usage"


def finite_positive(value, name, maximum):
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be finite, positive and <= {maximum}")
    return value


def targets(values, project):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", project):
        raise ValueError("Project must be a simple Compose project name")
    selected = {}
    for value in values:
        role, separator, name = value.partition("=")
        if not separator or role not in ROLES or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ValueError("Specify role=exact-container-name for api, worker, redis or prometheus")
        # Scope: explicitly named project containers. 为什么要有它：绝不能因漏参数退化为扫描所有容器，也不采集未授权的其他应用。
        if not re.fullmatch(re.escape(project) + r"[-_]" + role + r"[-_]\d+", name):
            raise ValueError("Container name must match the selected Compose project and role")
        if name in selected:
            raise ValueError("Duplicate container name")
        selected[name] = role
    if not selected:
        raise ValueError("At least one explicit container is required")
    return selected


def memory_bytes(value):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(B|kB|KB|MB|GB|TB|KiB|MiB|GiB|TiB)\s*", value)
    if not match:
        raise ValueError("Unknown Docker memory unit")
    number, unit = match.groups()
    factors = {"B":1,"kB":1000,"KB":1000,"MB":1000**2,"GB":1000**3,"TB":1000**4,
        "KiB":1024,"MiB":1024**2,"GiB":1024**3,"TiB":1024**4}
    converted = float(number)*factors[unit]
    if not math.isfinite(converted):
        raise ValueError("Nonfinite memory observation")
    return converted


def parse_row(raw):
    result = {"raw": raw, "cpu_percent": None, "memory_bytes": None, "memory_limit_bytes": None, "parse_errors": []}
    cpu = raw.get("CPUPerc", "")
    if isinstance(cpu, str) and re.fullmatch(r"\d+(?:\.\d+)?%", cpu.strip()):
        converted = float(cpu.strip()[:-1])
        if math.isfinite(converted):
            result["cpu_percent"] = converted
        else:
            result["parse_errors"].append("cpu_unavailable_or_invalid")
    else:
        result["parse_errors"].append("cpu_unavailable_or_invalid")
    usage = raw.get("MemUsage", "")
    try:
        pieces = usage.split("/")
        if len(pieces) not in {1, 2}:
            raise ValueError("Invalid memory field")
        result["memory_bytes"] = memory_bytes(pieces[0])
        if len(pieces) == 2:
            result["memory_limit_bytes"] = memory_bytes(pieces[1])
    except (AttributeError, TypeError, ValueError):
        result["parse_errors"].append("memory_unavailable_or_invalid")
    return result


def decode_sample(stdout, expected):
    parsed, errors = {}, []
    for line_number, line in enumerate(stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            name = raw.get("Name")
            if name not in expected or name in parsed:
                raise ValueError("Unexpected or duplicate container")
            parsed[name] = {"role": expected[name], **parse_row(raw)}
        except (ValueError, AttributeError, TypeError) as error:
            errors.append({"line": line_number, "error": str(error)})
    missing = sorted(set(expected)-set(parsed))
    complete = not errors and not missing and all(not row["parse_errors"] for row in parsed.values())
    return {"containers": parsed, "missing_containers": missing, "output_errors": errors, "complete": complete}


def sample(*, docker, selected, project, run_id, output, interval, duration, command_timeout, stop_file=None):
    selected = targets([role+"="+name for name,role in selected.items()], project)
    finite_positive(interval, "interval", 60)
    finite_positive(duration, "duration", 86400)
    finite_positive(command_timeout, "command_timeout", 60)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("Use the same simple run id as the Locust run")
    command = [docker, "stats", "--no-stream", "--format", "json", *selected]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    count = 0
    with output.open("x", encoding="utf-8") as stream:
        def write(value):
            stream.write(json.dumps({"schema":SCHEMA,"run_id":run_id,**value}, ensure_ascii=False, allow_nan=False)+"\n")
            stream.flush()
        write({"event":"resource_start","at":time.time(),"project":project,"targets":selected,"command":command,
            "interval_seconds":interval,"duration_seconds":duration,"command_timeout_seconds":command_timeout,"scope":SCOPE})
        try:
            # 为什么要有它：负载收尾后可正常结束采样并写停止记录，不必杀采样器而留下未归属的docker子进程。
            while time.monotonic()-start < duration and not (stop_file and Path(stop_file).exists()):
                before = time.monotonic()
                begun = time.time()
                remaining = duration-(before-start)
                exit_code, error, stdout, stderr = None, None, "", ""
                try:
                    completed = subprocess.run(command, capture_output=True, timeout=min(command_timeout, remaining), check=False)
                    exit_code = completed.returncode
                    stdout, stderr = completed.stdout.decode("utf-8", "replace"), completed.stderr.decode("utf-8", "replace")
                except subprocess.TimeoutExpired as exc:
                    error = "docker_stats_timeout"
                    stdout = (exc.stdout or b"").decode("utf-8", "replace")
                    stderr = (exc.stderr or b"").decode("utf-8", "replace")
                except OSError as exc:
                    error = type(exc).__name__
                    stderr = str(exc)
                decoded = decode_sample(stdout, selected)
                decoded["complete"] = decoded["complete"] and exit_code == 0
                write({"event":"resource_sample","sample_index":count,"started_at":begun,"finished_at":time.time(),
                    "elapsed_seconds":time.monotonic()-before,"exit_code":exit_code,"error":error,
                    "stdout":stdout,"stderr":stderr,**decoded})
                count += 1
                left = duration-(time.monotonic()-start)
                wait = min(left, max(0, interval-(time.monotonic()-before)))
                if wait > 0:
                    time.sleep(wait)
        finally:
            write({"event":"resource_stop","at":time.time(),"samples":count,"elapsed_seconds":time.monotonic()-start})
    return count


def resource_summary(rows, window_start=None, window_end=None):
    if any(value is not None and not math.isfinite(value) for value in (window_start, window_end)):
        raise ValueError("Window timestamps must be finite")
    starts = [r for r in rows if r.get("event") == "resource_start"]
    if len(starts) != 1 or len({r["run_id"] for r in rows}) != 1:
        raise ValueError("One resource collection run required")
    selected = starts[0]["targets"]
    all_samples = [r for r in rows if r.get("event") == "resource_sample"]
    samples = [r for r in all_samples if (window_start is None or r["started_at"] >= window_start)
        and (window_end is None or r["finished_at"] <= window_end)]
    if len({r["sample_index"] for r in samples}) != len(samples):
        raise ValueError("Duplicate resource sample indices")
    if window_start is not None and window_end is not None and window_end <= window_start:
        raise ValueError("Resource observation window must be increasing")
    def stats(values):
        return {"samples":len(values),"mean":statistics.fmean(values) if values else None,"peak":max(values) if values else None}
    containers = {}
    for name,role in selected.items():
        values = [r["containers"][name] for r in samples if r.get("exit_code") == 0 and name in r["containers"]]
        containers[name] = {"role":role,"cpu_percent":stats([r["cpu_percent"] for r in values if r["cpu_percent"] is not None]),
            "memory_bytes":stats([r["memory_bytes"] for r in values if r["memory_bytes"] is not None]),
            "missing_or_command_failed_samples":len(samples)-len(values),
            "metric_parse_error_samples":sum(bool(r["parse_errors"]) for r in values)}
    complete = [r for r in samples if r.get("complete") is True and set(r["containers"]) == set(selected)]
    # 为什么要有它：仅在同一stats调用完整获得全部容器时相加，不能相加各自不同时间的峰值或将缺失值当零。
    totals = [{"sample_index":r["sample_index"],"started_at":r["started_at"],"finished_at":r["finished_at"],
        "cpu_percent":sum(v["cpu_percent"] for v in r["containers"].values()),
        "memory_bytes":sum(v["memory_bytes"] for v in r["containers"].values())} for r in complete]
    peaks = {metric: max(totals, key=lambda r:r[metric]) if totals else None for metric in ("cpu_percent","memory_bytes")}
    return {"schema":"service-resource-summary.v1","run_id":starts[0]["run_id"],"scope":SCOPE,
        "window_start":window_start,"window_end":window_end,"window_selection":"whole command interval must be inside selected window",
        "samples_total":len(all_samples),"samples_selected":len(samples),"complete_group_samples":len(complete),
        "incomplete_group_samples":len(samples)-len(complete),"containers":containers,
        "same_sample_totals":{"cpu_percent":stats([r["cpu_percent"] for r in totals]),"memory_bytes":stats([r["memory_bytes"] for r in totals]),"peak_samples":peaks},
        "statistics_scope":"Arithmetic mean and observed peak over samples, not time-weighted mean or continuous peak. One command groups observations but does not guarantee atomic kernel sampling.",
        "docker_memory_scope":"On Linux docker stats CLI subtracts inactive file cache; preserve original MemUsage and CPUPerc strings. Values are rounded CLI observations. CPU is Docker's percent and may exceed 100; not normalized host-total utilization.",
        "excluded":"Host OS, Docker VM/daemon overhead, external LLM/GPU, load generator and unrelated containers are not included."}


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("sample")
    collect.add_argument("--container", action="append", required=True, help="role=exact-compose-container-name")
    collect.add_argument("--project", default="rag-agent-service")
    collect.add_argument("--docker", default="docker")
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--interval", type=float, default=2)
    collect.add_argument("--duration", type=float, required=True)
    collect.add_argument("--command-timeout", type=float, default=10)
    collect.add_argument("--stop-file", type=Path)
    report = commands.add_parser("summarize")
    report.add_argument("input", type=Path)
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--window-start", type=float)
    report.add_argument("--window-end", type=float)
    args = parser.parse_args()
    if args.command == "sample":
        count = sample(docker=args.docker, selected=targets(args.container,args.project), project=args.project,
            run_id=args.run_id, output=args.output, interval=args.interval, duration=args.duration, command_timeout=args.command_timeout, stop_file=args.stop_file)
        print(json.dumps({"samples":count,"output":str(args.output)}))
    else:
        raw = args.input.read_bytes()
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if any(row.get("schema") != SCHEMA for row in rows):
            raise ValueError("Unexpected resource schema")
        result = resource_summary(rows,args.window_start,args.window_end)
        result["raw_ref"]={"path":str(args.input.resolve()),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}
        with args.output.open("x",encoding="utf-8") as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2)
        print(json.dumps({"output":str(args.output),"complete_group_samples":result["complete_group_samples"]}))


if __name__ == "__main__":
    main()
