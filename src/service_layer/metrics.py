"""Finite Redis-backed queue measurements, shared by API and worker processes."""
import math


def queue_metrics(snapshot):
    output = []
    counters = snapshot.get("counters", {})
    names = {"retried": "retries", "lease_expired": "expired_leases",
             "idempotency_hits": "duplicate_submits"}
    # 为什么要有它：只导出已知数值指标，Redis内部字段、任务正文和任意标签不进入Prometheus。
    for name, metric_type in {
        "queued": "gauge", "running": "gauge", "submitted": "counter", "completed": "counter",
        "failed": "counter", "timed_out": "counter", "indeterminate": "counter", "cancelled": "counter",
        "retried": "counter", "lease_expired": "counter", "idempotency_hits": "counter",
        "idempotency_conflicts": "counter", "queue_rejections": "counter",
        "late_writes_rejected": "counter", "claimed": "counter",
    }.items():
        # 为什么要有它：真实RedisStore把累计事件放在counters内，不能以测试替身的扁平结构吞掉所有完成/失败指标。
        value = snapshot.get(name) if metric_type == "gauge" else counters.get(names.get(name, name), 0)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            continue
        metric = "service_jobs_" + name + ("_total" if metric_type == "counter" else "")
        output.extend((f"# TYPE {metric} {metric_type}", f"{metric} {value}"))
    return ("\n".join(output) + "\n").encode()
