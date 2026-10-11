"""Execute a bounded, sequential Locust matrix with same-window container samples."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def ref(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--locust-python", required=True)
    p.add_argument("--docker", default="docker")
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--url", default="http://127.0.0.1:8080")
    a = p.parse_args()
    if not 10 <= a.seconds <= 600:
        raise ValueError("Run duration must be between 10 and 600 seconds")
    root = a.output.resolve(); root.mkdir(parents=True, exist_ok=False)
    values = dict(line.split("=", 1) for line in (REPO/"deployment/service/.env").read_text().splitlines()
                  if line and not line.startswith("#"))
    environment = os.environ.copy()
    environment.update(SERVICE_API_TOKEN=values["SERVICE_API_TOKEN"], SERVICE_LOAD_TIMEOUT="90",
                       SERVICE_LOAD_POLL_SECONDS="0.1", PYTHONDONTWRITEBYTECODE="1")
    for name in ("queries.json", "manifest.json"):
        subprocess.run([a.docker, "cp", "rag-agent-service-api-1:/work/corpus/" + name, str(root/name)], check=True)
    environment["SERVICE_LOAD_QUERIES"] = str(root/"queries.json")
    subprocess.run([a.locust_python, "-I", "-B", "-X", "utf8", "-m", "locust", "--version"], check=True)
    versions = subprocess.run([a.locust_python, "-I", "-B", "-X", "utf8", "-m", "pip", "freeze"], capture_output=True)
    # uv environments may omit pip; obtain the actual distribution versions without installing it.
    if versions.returncode:
        versions = subprocess.run([a.locust_python, "-I", "-B", "-X", "utf8", "-c",
            "import importlib.metadata as m;print('\\n'.join(sorted(d.metadata['Name']+'=='+d.version for d in m.distributions())))"], capture_output=True, check=True)
    (root/"load-generator-versions.txt").write_bytes(versions.stdout)
    containers = {"api": ["rag-agent-service-api-1"], "worker": ["rag-agent-service-worker-1", "rag-agent-service-worker-2"],
                  "redis": ["rag-agent-service-redis-1"], "prometheus": ["rag-agent-service-prometheus-1"]}
    inspection = subprocess.run([a.docker, "inspect", "--format", "{{.Name}} {{.Image}} {{.State.StartedAt}}",
        *[n for names in containers.values() for n in names]], capture_output=True, check=True)
    (root/"container-identities.txt").write_bytes(inspection.stdout)
    matrix = [("unique", 1), ("unique", 4), ("unique", 12), ("cache", 4), ("idempotency", 4)]
    write(root/"protocol.json", {"matrix": matrix, "run_seconds": a.seconds, "workers": 2,
        "settings": "Existing source-bound sparse-only Compose fixture", "rate_limit_per_minute": 120,
        "startup": "Existing service after documented smoke/fault tests; preserve observed cache hits/misses, no hidden model warmup",
        "scope": "Single measured run per condition; completion includes drain; not LLM/production capacity",
        "source_refs": [ref(HERE/name) for name in ("run_matrix.py", "locustfile.py", "protocol.py", "summarize.py", "resources.py")],
        "corpus_ref": ref(root/"manifest.json")})
    results = []
    for mode, users in matrix:
        label = mode + "-u" + str(users)
        folder = root/label; folder.mkdir()
        environment.update(SERVICE_LOAD_MODE=mode, SERVICE_LOAD_RUN_ID=label,
                           SERVICE_LOAD_OUTPUT=str(folder))
        stop = folder/"resource.stop"
        resource_command = [sys.executable, "-B", str(HERE/"resources.py"), "sample", "--docker", a.docker,
            "--project", "rag-agent-service", "--run-id", label, "--duration", str(a.seconds+120), "--interval", "2",
            "--output", str(folder/"resources.jsonl"), "--stop-file", str(stop)]
        for role, names in containers.items():
            for name in names:
                resource_command += ["--container", role + "=" + name]
        command = [a.locust_python, "-I", "-B", "-X", "utf8", "-m", "locust", "-f", str(HERE/"locustfile.py"), "--host", a.url,
                   "--headless", "-u", str(users), "-r", str(users), "-t", str(a.seconds) + "s",
                   "--stop-timeout", "100", "--csv", str(folder/"locust")]
        begin = time.time()
        with (folder/"resources-process.log").open("xb") as resource_log, (folder/"locust-process.log").open("xb") as load_log:
            sampler = subprocess.Popen(resource_command, stdout=resource_log, stderr=subprocess.STDOUT)
            try:
                load = subprocess.run(command, env=environment, stdout=load_log, stderr=subprocess.STDOUT, timeout=a.seconds+120)
                code = load.returncode
            except subprocess.TimeoutExpired:
                code = None
            finally:
                stop.write_text("Load process ended", encoding="utf-8")
                sampler.wait(timeout=20)
        receipt = {"run_id": label, "command": command, "exit_code": code, "sampler_exit_code": sampler.returncode,
                   "started_at": begin, "finished_at": time.time()}
        write(folder/"process.json", receipt)
        raws = list(folder.glob(label + ".*.jsonl"))
        if raws:
            subprocess.run([sys.executable, "-B", str(HERE/"summarize.py"), *map(str, raws), "--output", str(folder/"summary.json")], check=True, stdout=subprocess.DEVNULL)
            summary = json.loads((folder/"summary.json").read_bytes())
            subprocess.run([sys.executable, "-B", str(HERE/"resources.py"), "summarize", str(folder/"resources.jsonl"),
                "--window-start", str(summary["window_start_unix"]), "--window-end", str(summary["window_end_unix"]),
                "--output", str(folder/"resources-summary.json")], check=True, stdout=subprocess.DEVNULL)
            receipt["summary_ref"] = ref(folder/"summary.json")
        results.append(receipt)
        print(json.dumps({"run_id": label, "exit_code": code, "summary_ready": bool(raws)}), flush=True)
    write(root/"runs.json", results)


if __name__ == "__main__":
    main()
