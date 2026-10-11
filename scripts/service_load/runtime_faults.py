"""Bounded real fault qualification for the explicitly owned Compose project only."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
PROJECT = "rag-agent-service"
WORKERS = [PROJECT + "-worker-1", PROJECT + "-worker-2"]
TERMINAL = {"completed", "failed", "timed_out", "indeterminate", "cancelled"}


def dotenv(path):
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def main():
    import redis
    from src.service_layer.store import RedisJobStore
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--duration", type=float, default=170)
    args = parser.parse_args()
    if not 60 <= args.duration <= 180:
        raise ValueError("Fault window must be bounded to 60-180 seconds")
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    env = dotenv(REPO / "deployment/service/.env")
    token, password = env["SERVICE_API_TOKEN"], env["SERVICE_REDIS_PASSWORD"]
    base = "http://127.0.0.1:" + env.get("SERVICE_HTTP_PORT", "8080")
    prom = "http://127.0.0.1:" + env.get("SERVICE_PROMETHEUS_PORT", "9095")
    client = redis.Redis(host="127.0.0.1", port=int(env.get("SERVICE_REDIS_PORT", "16379")), password=password,
        socket_timeout=3, socket_connect_timeout=3, decode_responses=True)
    store = RedisJobStore(client, namespace=env.get("SERVICE_NAMESPACE", "agent-service"))
    started = time.monotonic()
    end = started+args.duration
    steps, owned = {}, set()
    redis_may_be_stopped = False
    killed = []

    def redact(value):
        if isinstance(value, dict):
            return {k:redact(v) for k,v in value.items() if k not in {"lease_token", "_idempotency_digest", "payload"}}
        if isinstance(value, list): return [redact(v) for v in value]
        if isinstance(value, str):
            return value.replace(token,"[redacted]").replace(password,"[redacted]")
        return value

    def save(name, value):
        with (root / (name+".json")).open("x", encoding="utf-8") as stream:
            json.dump(redact(value), stream, ensure_ascii=False, indent=2)

    def command(values, *, timeout=20):
        before = time.time()
        result = subprocess.run([args.docker,*values], capture_output=True, timeout=timeout, check=False)
        record = {"command":[args.docker,*values],"started_at":before,"finished_at":time.time(),
            "exit_code":result.returncode,"stdout":result.stdout.decode("utf-8","replace"),"stderr":result.stderr.decode("utf-8","replace")}
        with (root/"docker-commands.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(redact(record),ensure_ascii=False)+"\n")
        if result.returncode: raise RuntimeError("Docker command failed: "+record["stderr"][-500:])
        return record["stdout"]

    def inspect(name, expected_service):
        template = ('{"id":{{json .Id}},"name":{{json .Name}},"hostname":{{json .Config.Hostname}},'
            '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
            '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
            '"pid":{{.State.Pid}},"started_at":{{json .State.StartedAt}},"running":{{.State.Running}}}')
        value = json.loads(command(["inspect","--format",template,name],timeout=8))
        if value["project"] != PROJECT or value["service"] != expected_service or value["name"] != "/"+name:
            raise ValueError("Container ownership mismatch")
        return value

    def http(path, body=None, *, host=base, authenticated=True, timeout=10):
        headers = {"Content-Type":"application/json"}
        if authenticated: headers["Authorization"]="Bearer "+token
        if body is not None: headers["Idempotency-Key"]="fault-"+uuid4().hex
        request = Request(host+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        then = time.time()
        try:
            with urlopen(request,timeout=timeout) as response: status, raw = response.status, response.read()
        except HTTPError as error: status, raw = error.code, error.read()
        value = json.loads(raw)
        with (root/"http-events.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(redact({"path":path,"method":"POST" if body is not None else "GET","started_at":then,"finished_at":time.time(),"status":status,"response":value}),ensure_ascii=False)+"\n")
        return status,value

    fixture = json.loads(command(["exec",PROJECT+"-api-1","cat","/work/corpus/queries.json"],timeout=8))
    chosen = fixture["queries"][0]
    def submit(timeout=60.0, attempts=1):
        body={"kind":"query","payload":{"query":chosen["query"]+" faultnonce"+uuid4().hex,"collection":fixture["collection"],
            "top_k":5,"answer":False,"rewrite":False,"rerank":False},"timeout_seconds":float(timeout),"max_attempts":attempts}
        status,value=http("/v1/jobs",body)
        if status != 202: raise RuntimeError("Fault query admission did not create a job: "+str(status))
        owned.add(value["job"]["id"])
        return value["job"]["id"]

    def wait(job_id, seconds):
        deadline=min(end,time.monotonic()+seconds)
        while time.monotonic()<deadline:
            status,job=http("/v1/jobs/"+job_id)
            if status == 200 and job["state"] in TERMINAL: return job
            time.sleep(.1)
        raise TimeoutError("Job did not reach terminal within fault window")

    def normal(job):
        domain=job.get("result") or {}
        return job["state"]=="completed" and domain.get("status")=="completed" and any(
            row.get("metadata",{}).get("source_path")==chosen["expected_source"] for row in domain.get("results",[]))

    def idle():
        metrics=store.metrics()
        if metrics["pending"] != 0: raise RuntimeError("Nonempty queue: do not disrupt active jobs")
        return metrics

    try:
        before={name:inspect(name,"worker") for name in WORKERS}
        inspect(PROJECT+"-redis-1","redis")
        if not all(v["running"] for v in before.values()): raise RuntimeError("Both owned workers must initially run")
        save("admission",{"queue":idle(),"workers":before,"scope":"No model/game workload; only owned project containers and HTTP query jobs"})
        job_id=submit(.02)
        timeout_job=wait(job_id,20)
        steps["short_budget"]={"status":"passed" if timeout_job["state"]=="timed_out" else "failed","job":timeout_job}
        save("short-budget",steps["short_budget"])

        idle()
        redis_may_be_stopped=True
        command(["compose","-p",PROJECT,"-f",str(REPO/"deployment/service/compose.yaml"),"stop","-t","2","redis"],timeout=12)
        unavailable_status,_=http("/health")
        unavailable_submission,_=http("/v1/jobs",{"kind":"query","payload":{"query":chosen["query"],"collection":fixture["collection"],"answer":False,"rewrite":False,"rerank":False},"timeout_seconds":30.0,"max_attempts":1})
        command(["start",PROJECT+"-redis-1"],timeout=10)
        redis_may_be_stopped=False
        for _ in range(30):
            try:
                if client.ping(): break
            except redis.RedisError: pass
            time.sleep(.2)
        recovery_ids=[submit() for _ in range(2)]
        recovery_jobs=[wait(j,35) for j in recovery_ids]
        after={name:inspect(name,"worker") for name in WORKERS}
        same_workers=all(before[n]["id"]==after[n]["id"] and before[n]["pid"]==after[n]["pid"] and before[n]["started_at"]==after[n]["started_at"] and after[n]["running"] for n in WORKERS)
        executed_hosts={store.get(j)["worker_id"].split(":",1)[0] for j in recovery_ids}
        all_reconnected=executed_hosts=={v["hostname"] for v in before.values()}
        steps["redis_disconnect"]={"status":"passed" if unavailable_status==503 and unavailable_submission==503 and same_workers and all(normal(j) for j in recovery_jobs) else "failed",
            "health_status_while_down":unavailable_status,"submission_status_while_down":unavailable_submission,
            "same_worker_processes":same_workers,"both_workers_executed_after_restore":all_reconnected,"scheduler_observation_scope":"Informational only; two requests are not guaranteed to use different workers","workers_after":after,"jobs":recovery_jobs}
        save("redis-disconnect",steps["redis_disconnect"])

        idle()
        crash_id=submit(attempts=2)
        observed=None
        deadline=min(end,time.monotonic()+12)
        while time.monotonic()<deadline:
            observed=store.get(crash_id)
            if observed and observed["state"] in TERMINAL: break
            if observed and observed["state"]=="running": break
            time.sleep(.01)
        if not observed or observed["state"]!="running":
            steps["worker_crash"]={"status":"not_exercised","reason":"Job completed or never became running before injection","job_id":crash_id}
        else:
            owner=observed["worker_id"]
            matching=[n for n,v in before.items() if v["hostname"]==owner.split(":",1)[0]]
            if len(matching)!=1: raise RuntimeError("Running job owner did not exactly match an owned worker hostname")
            victim=matching[0]
            current=inspect(victim,"worker")
            if current["id"]!=before[victim]["id"]: raise RuntimeError("Worker container replaced before injection")
            current_job=store.get(crash_id)
            if current_job["state"]!="running" or current_job["worker_id"]!=owner:
                steps["worker_crash"]={"status":"not_exercised","reason":"Ownership/completion race before kill","job_id":crash_id}
            else:
                killed.append(victim)
                command(["kill","--signal","KILL",victim],timeout=10)
                final=wait(crash_id,65)
                private=store.get(crash_id)
                history=[{k:r.get(k) for k in ("attempt","state","worker_id","started_at","finished_at","cost_unknown")} for r in private.get("attempts_history",[])]
                replayed=normal(final) and final["attempt"]==2 and private["worker_id"]!=owner
                race=final["attempt"]==1 and final["state"]=="completed"
                steps["worker_crash"]={"status":"passed" if replayed else "not_exercised" if race else "failed","victim":victim,
                    "owner_before":owner,"owner_after":private.get("worker_id"),"job":final,"attempts_history":history,"race_completed_before_kill":race}
        save("worker-crash",steps["worker_crash"])
    except Exception as error:
        steps["exception"]={"status":"failed","type":type(error).__name__,"message":str(error)}
    finally:
        restoration={"errors":[]}
        if redis_may_be_stopped:
            try: command(["start",PROJECT+"-redis-1"],timeout=12)
            except Exception as error: restoration["errors"].append({"operation":"restore_redis","type":type(error).__name__,"message":str(error)})
        for name in WORKERS:
            try:
                if not inspect(name,"worker")["running"]: command(["start",name],timeout=12)
            except Exception as error: restoration["errors"].append({"operation":"restore_worker","container":name,"type":type(error).__name__,"message":str(error)})
        try:
            restoration["workers"]={n:inspect(n,"worker") for n in WORKERS}
            restoration["redis"]=inspect(PROJECT+"-redis-1","redis")
            restoration["two_workers_running"]=all(v["running"] for v in restoration["workers"].values())
            restoration["health_status"]=http("/health")[0]
            status,prom_result=http("/api/v1/query?"+urlencode({"query":"up"}),host=prom,authenticated=False)
            values=prom_result.get("data",{}).get("result",[])
            restoration["prometheus_query_status"]=status
            restoration["prometheus_up"]=values
            restoration["prometheus_all_observed_up"]=bool(values) and all(float(row["value"][1])==1 for row in values)
            restoration["queue"]=store.metrics()
        except Exception as error:
            restoration["errors"].append({"type":type(error).__name__,"message":str(error)})
        save("restoration",restoration)
        passed=all(steps.get(k,{}).get("status")=="passed" for k in ("short_budget","redis_disconnect","worker_crash")) and not restoration["errors"] and restoration.get("two_workers_running") and restoration.get("health_status")==200 and restoration.get("prometheus_all_observed_up") and restoration.get("queue",{}).get("pending")==0
        result={"schema":"service-runtime-faults.v1","status":"passed" if passed else "incomplete_or_failed","steps":steps,
            "restoration":restoration,"owned_job_ids":sorted(owned),"elapsed_seconds":time.monotonic()-started,"models":0,"games":0}
        save("result",result)
        print(json.dumps({"status":result["status"],"result":str(root/"result.json"),"elapsed_seconds":result["elapsed_seconds"]}))
    return 0 if passed else 2


if __name__=="__main__":
    raise SystemExit(main())
