"""Protocol/accounting checks, explicitly not performance measurements."""
import importlib.util
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protocol = load("protocol")
summary = load("summarize")


def terminal(state="completed", domain_status="completed", source="test/source", cache="hit"):
    return {"id": "a"*32, "state": state, "result": {"status": domain_status, "results": [{"metadata": {"source_path": source}}],
        "cache": {"result": cache, "binding_available": True}, "usage": {"answer_transport_calls": 0, "rewrite_transport_calls": 0}}}


def test_idempotency_does_not_double_count_work():
    rows, calls = [], []
    def transport(method,path,body,key,timeout):
        calls.append((method,path,body,key))
        if method == "POST":
            return (202 if len(calls)==1 else 200), {"created": len(calls)==1, "job": {"id": "a"*32, "state": "queued"}}
        return 200, terminal()
    result = protocol.operation(transport, rows.append, mode="idempotency", query="hello", collection="load", expected_source="test/source", sleep=lambda _:None)
    assert result["outcome"] == "completed" and result["duplicate_verified"] is True
    assert calls[0][2:] == calls[1][2:]
    rows = [{"event":"run_start","at":0}, *rows, {"event":"run_stop","at":result["finished_at"]}]
    for row in rows: row["run_id"]="test"
    group=summary.summarize(rows)["groups"]["idempotency"]
    assert group["http_submissions"]==2 and group["distinct_successful_jobs"]==1
    assert group["idempotent_replayed_submissions"]==1 and group["cache_hit_jobs"]==1


def test_completed_queue_with_failed_domain_is_not_success():
    rows=[]
    def transport(*args): return 202,{"created":True,"job":terminal(domain_status="failed")}
    result=protocol.operation(transport,rows.append,mode="cache",query="hello",collection="load",expected_source="test/source")
    assert result["outcome"]=="domain_failed"


def test_wrong_source_is_not_success():
    result=protocol.operation(lambda *a:(202,{"created":True,"job":terminal(source="wrong")}),lambda _:None,
        mode="unique",query="hello",collection="load",expected_source="test/source")
    assert result["outcome"]=="domain_failed"


def test_timeout_keeps_pending_job_and_sample():
    now=[0.0];rows=[]
    def sleep(value): now[0]+=value
    def transport(method,*args):
        job={"id":"a"*32,"state":"queued"}
        return (202,{"created":True,"job":job}) if method=="POST" else (200,job)
    result=protocol.operation(transport,rows.append,mode="cache",query="hi",collection="load",expected_source="source",
        timeout=1,poll_interval=.5,clock=lambda:now[0],sleep=sleep)
    assert result["outcome"]=="client_observation_timeout" and result["job_id"]=="a"*32
    assert rows[-1]["event"]=="operation_end" and rows[-1]["elapsed_ms"]==1000


def test_missing_final_and_failure_remain_in_denominator():
    rows=[{"event":"run_start","at":0},{"event":"run_stop","at":10},
        {"event":"operation_start","operation_id":"one","mode":"unique"},
        {"event":"operation_start","operation_id":"two","mode":"unique"},
        {"event":"operation_end","operation_id":"one","mode":"unique","outcome":"admission_rejected","elapsed_ms":3,"finished_at":1}]
    for row in rows:row["run_id"]="test"
    result=summary.summarize(rows)["groups"]["unique"]
    assert result["failure_fraction_all_started"]==1 and result["unobserved_operations"]==1
    assert result["completed_jobs_per_second"]==0


def test_percentile_small_samples_is_explicit():
    assert summary.percentile([10,100,30,20],.5)==20
    assert summary.percentile([10,100,30,20],.95)==100
    assert summary.percentile([],.95) is None


def test_phase_latencies_exclude_retried_job_start_timestamp():
    rows=[{"event":"run_start","at":0},{"event":"run_stop","at":20}]
    for index,attempt in enumerate([1,2]):
        rows += [{"event":"operation_start","operation_id":str(index),"mode":"cache"},
            {"event":"operation_end","operation_id":str(index),"mode":"cache","outcome":"completed",
                "job_id":str(index),"job_state":"completed","started_at":0,"finished_at":10,"elapsed_ms":10000,
                "attempt":attempt,"job_created_at":1,"job_started_at":3,"job_finished_at":5}]
    for row in rows:row["run_id"]="test"
    group=summary.summarize(rows)["groups"]["cache"]
    assert group["server_first_attempt_queue"]=={"count":1,"p50_ms":2000,"p95_ms":2000,"max_ms":2000}
    assert group["server_first_attempt_execution"]["count"]==1
