"""Host-only hot-start wrapper; the frozen task runner keeps its original deadline."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:11434"
WARMUP_PROMPT = "Return one letter: A"
WARMUP_SECONDS = 180
POLL_SECONDS = 5


def ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read(reference):
    if ref(reference["path"]) != reference:
        raise ValueError("BOUND_INPUT_CHANGED")
    return json.loads(Path(reference["path"]).read_bytes())


def save(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return ref(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("LOCAL_OLLAMA_REDIRECT_REJECTED")


def request_api(endpoint, payload, timeout):
    # 为什么要有它：host 预热只访问固定本地服务，禁用代理和重定向，不能从协议内容取得外发地址。
    if endpoint not in {"/api/version", "/api/tags", "/api/ps", "/api/generate"}:
        raise ValueError("UNSUPPORTED_LOCAL_ENDPOINT")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=max(0.01, timeout)) as response:
        return response.read()


def classification(records):
    statuses = [record["classification"] for record in records]
    if "deviation" in statuses:
        return "deviation"
    if not statuses or "unknown" in statuses:
        return "unknown"
    return "hot_verified"


def residency(value, config):
    # 为什么要有它：本热批固定单模型驻留，额外模型会改变显存与资源条件，不能计作可比热启动。
    if not isinstance(value.get("models"), list):
        return "unknown", "RESIDENCY_MODEL_LIST_MISSING"
    if len(value["models"]) > 1:
        return "deviation", "ADDITIONAL_MODEL_RESIDENT"
    rows = [
        row
        for row in value.get("models", [])
        if row.get("name", row.get("model")) == config["model"]
    ]
    if len(rows) != 1:
        return "deviation", "FIXED_MODEL_NOT_UNIQUELY_RESIDENT"
    row = rows[0]
    for key in ("digest", "context_length", "size_vram"):
        if key not in row:
            return "unknown", "RESIDENCY_FIELD_MISSING:" + key
    if row["digest"] != config["digest"] or row["context_length"] != config["context_window"]:
        return "deviation", "RESIDENT_MODEL_OR_CONTEXT_CHANGED"
    if type(row["size_vram"]) not in (int, float) or row["size_vram"] <= 0:
        return "deviation", "GPU_RESIDENCY_NOT_OBSERVED"
    return "hot_verified", "MODEL_DIGEST_CONTEXT_AND_GPU_RESIDENCY_OBSERVED"


def validate(protocol_ref, trial_id, allow_runtime):
    protocol = read(protocol_ref)
    rows = [row for row in protocol["trials"] if row["trial_id"] == trial_id]
    if len(rows) != 1:
        raise ValueError("REGISTERED_TRIAL_REQUIRED")
    trial = read(rows[0]["trial_ref"])
    if trial.get("runtime_required") and not allow_runtime:
        raise ValueError("RUNTIME_NOT_STARTED_OPERATOR_UNAVAILABLE")
    if Path(trial["output_root"]).exists():
        raise ValueError("TRIAL_ALREADY_STARTED")
    config = protocol["common_configuration"]
    if (
        config["context_window"] != 65536
        or config["temperature"] != 0
        or protocol["wall_seconds"] != 900
    ):
        raise ValueError("FIXED_HOT_CONFIGURATION_CHANGED")
    snapshot = read(protocol["platform_snapshot_ref"])
    runner = Path(snapshot["snapshot_root"]) / "scripts/run_context_online_ab.py"
    if ref(runner)["sha256"] != snapshot["files"]["scripts/run_context_online_ab.py"]["sha256"]:
        raise ValueError("FROZEN_RUNNER_CHANGED")
    expected_version = protocol.get("startup_condition", {}).get("expected_service_version")
    if not isinstance(expected_version, str) or not expected_version:
        raise ValueError("FIXED_SERVICE_VERSION_REQUIRED")
    return protocol, trial, config, runner, expected_version


def command_for(runner, protocol_ref, trial_id, allow_runtime, preflight=False):
    command = [
        sys.executable,
        "-I",
        "-B",
        "-X",
        "utf8",
        str(runner),
        "--protocol",
        protocol_ref["path"],
        "--trial-id",
        trial_id,
    ]
    if preflight:
        command.append("--preflight-only")
    if allow_runtime:
        command.append("--allow-runtime")
    return command


def preflight(command, output):
    with (
        (output / "preflight.stdout.bin").open("xb") as stdout,
        (output / "preflight.stderr.bin").open("xb") as stderr,
    ):
        return subprocess.run(
            command, stdout=stdout, stderr=stderr, timeout=180, check=False
        ).returncode


def launch(command, output):
    stdout = (output / "task.stdout.bin").open("xb")
    stderr = (output / "task.stderr.bin").open("xb")
    try:
        return subprocess.Popen(command, stdout=stdout, stderr=stderr)
    finally:
        stdout.close()
        stderr.close()


def run(
    protocol_ref,
    trial_id,
    *,
    allow_runtime=False,
    api=request_api,
    preflight_runner=preflight,
    launcher=launch,
):
    protocol, trial, config, runner, expected_version = validate(
        protocol_ref, trial_id, allow_runtime
    )
    output = Path(trial["output_root"]).parent / (trial_id + "-startup-hot-v1")
    output.mkdir(parents=True, exist_ok=False)
    startup = {
        "schema": "context-online-ab.startup.v1",
        "startup_condition_version": "hot-v1",
        "condition_classification": "unknown",
        "trial_id": trial_id,
        "protocol_ref": protocol_ref,
        "warmup_ref": None,
        "residency_refs": [],
        "task_started": False,
        "service_version_expected": expected_version,
        "wrapper_ref": ref(__file__),
        "frozen_runner_ref": ref(runner),
    }
    samples = []
    stop = threading.Event()
    thread = None
    task = None
    task_returncode = None
    try:
        preflight_command = command_for(runner, protocol_ref, trial_id, allow_runtime, True)
        save(output / "preflight-command.json", preflight_command)
        code = preflight_runner(preflight_command, output)
        if code != 0:
            raise ValueError("FROZEN_PREFLIGHT_FAILED:" + str(code))
        warm_started = time.monotonic()
        deadline = warm_started + WARMUP_SECONDS

        def fetch(endpoint, payload, stem):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("WARMUP_BUDGET_EXHAUSTED")
            request_ref = save(
                output / (stem + "-request.json"), {"url": BASE_URL + endpoint, "body": payload}
            )
            raw = api(endpoint, payload, remaining)
            path = output / (stem + "-response.json")
            path.write_bytes(raw)
            return json.loads(raw), request_ref, ref(path)

        version, _, version_ref = fetch("/api/version", None, "version")
        startup["service_version_ref"] = version_ref
        if version.get("version") != expected_version:
            startup["condition_classification"] = "deviation"
            raise ValueError("SERVICE_VERSION_CHANGED")
        tags, _, tags_ref = fetch("/api/tags", None, "manifest")
        startup["model_manifest_ref"] = tags_ref
        matches = [
            row
            for row in tags.get("models", [])
            if row.get("name", row.get("model")) == config["model"]
        ]
        if len(matches) != 1 or matches[0].get("digest") != config["digest"]:
            startup["condition_classification"] = "deviation"
            raise ValueError("FIXED_MODEL_MANIFEST_CHANGED")
        payload = {
            "model": config["model"],
            "prompt": WARMUP_PROMPT,
            "stream": False,
            "keep_alive": -1,
            "options": {"num_ctx": 65536, "temperature": 0, "num_predict": 1},
        }
        before_generate = time.monotonic()
        generated, request_ref, response_ref = fetch("/api/generate", payload, "warmup")
        elapsed = time.monotonic() - before_generate
        startup["warmup_ref"] = save(
            output / "warmup.json",
            {
                "request_ref": request_ref,
                "response_ref": response_ref,
                "elapsed_seconds": elapsed,
                "preparation_elapsed_seconds": time.monotonic() - warm_started,
                "input_tokens": generated.get("prompt_eval_count"),
                "output_tokens": generated.get("eval_count"),
                "cached_input_tokens": generated.get("cached_input_tokens"),
                "load_ns": generated.get("load_duration"),
                "eval_ns": generated.get("eval_duration"),
                "native_usage": {
                    key: value
                    for key, value in generated.items()
                    if key.endswith("count") or key.endswith("duration")
                },
                "separate_from_task_budget": True,
            },
        )
        if (
            generated.get("done") is not True
            or generated.get("error")
            or generated.get("model") != config["model"]
        ):
            raise ValueError("WARMUP_NOT_COMPLETED")
        if time.monotonic() >= deadline:
            raise TimeoutError("WARMUP_BUDGET_EXHAUSTED")

        def sample():
            number = len(samples)
            started = time.monotonic()
            record = {
                "observed_monotonic_seconds": started,
                "phase": "during_task" if startup["task_started"] else "pre_task",
            }
            try:
                raw = api(
                    "/api/ps",
                    None,
                    min(POLL_SECONDS, max(0.01, deadline - time.monotonic()))
                    if not startup["task_started"]
                    else POLL_SECONDS,
                )
                path = output / ("residency-" + str(number) + "-response.json")
                path.write_bytes(raw)
                status, reason = residency(json.loads(raw), config)
                record.update(classification=status, reason=reason, response_ref=ref(path))
            except Exception as exc:
                record.update(classification="unknown", reason=type(exc).__name__ + ": " + str(exc))
            samples.append(record)
            startup["residency_refs"].append(
                save(output / ("residency-" + str(number) + ".json"), record)
            )

        sample()
        startup["condition_classification"] = classification(samples)
        if time.monotonic() >= deadline:
            raise TimeoutError("WARMUP_BUDGET_EXHAUSTED")
        if startup["condition_classification"] != "hot_verified":
            raise ValueError("HOT_RESIDENCY_NOT_VERIFIED")
        save(output / "startup-before-task.json", startup)
        command = command_for(runner, protocol_ref, trial_id, allow_runtime)
        save(output / "task-command.json", command)
        # 为什么要有它：预热在正式计时外完成，调用原冻结 runner 后由它拥有900秒截止，监视线程只读驻留、不发保活生成。
        task = launcher(command, output)
        startup["task_started"] = True

        def observe():
            while not stop.wait(POLL_SECONDS):
                sample()

        thread = threading.Thread(target=observe, name="online-ab-residency", daemon=False)
        thread.start()
        task_returncode = task.wait()
        stop.set()
        thread.join()
        sample()
        startup["condition_classification"] = classification(samples)
    except Exception as exc:
        startup["error"] = type(exc).__name__ + ": " + str(exc)
    finally:
        stop.set()
        if thread is not None:
            thread.join()
        startup["task_returncode"] = task_returncode
        startup_ref = save(output / "startup.json", startup)
        result = {
            "schema": "context-online-ab.hot-wrapper-result.v1",
            "trial_id": trial_id,
            "startup_ref": startup_ref,
            "task_started": startup["task_started"],
            "agent_started": startup["task_started"],
            "success": None if not startup["task_started"] else (task_returncode == 0),
            "returncode": task_returncode,
            "condition_classification": startup["condition_classification"],
            "task_result_ref": ref(Path(trial["output_root"]) / "result.json")
            if (Path(trial["output_root"]) / "result.json").is_file()
            else None,
            "stdout_ref": ref(output / "task.stdout.bin")
            if (output / "task.stdout.bin").exists()
            else None,
            "stderr_ref": ref(output / "task.stderr.bin")
            if (output / "task.stderr.bin").exists()
            else None,
        }
        save(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--allow-runtime", action="store_true")
    args = parser.parse_args()
    result = run(ref(args.protocol), args.trial_id, allow_runtime=args.allow_runtime)
    print(json.dumps(result))
    return 0 if result["task_started"] and result["returncode"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
