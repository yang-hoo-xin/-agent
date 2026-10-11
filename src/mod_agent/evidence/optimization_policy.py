"""Persisted execution choices for isolated online optimization comparisons."""
import json
from pathlib import Path


def optimization_policy(*, reuse_query_observations=True, compress_findings_input=True):
    if type(reuse_query_observations) is not bool or type(compress_findings_input) is not bool:
        raise ValueError("EVIDENCE_OPTIMIZATION_POLICY_INVALID")
    return {"reuse_query_observations": reuse_query_observations,
            "compress_findings_input": compress_findings_input}


def run_optimization_policy(run_root):
    # 为什么要有它：续接继承原任务的实际策略；历史未记载字段保留既有默认，已记载的 False 不能被默认值覆盖。
    path = Path(run_root) / "run_manifest.json"
    if not path.exists():
        return optimization_policy()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if "evidence_optimization" not in manifest:
        return optimization_policy()
    value = manifest["evidence_optimization"]
    if not isinstance(value, dict) or set(value) != {"reuse_query_observations", "compress_findings_input"}:
        raise ValueError("EVIDENCE_OPTIMIZATION_POLICY_INVALID")
    return optimization_policy(**value)
