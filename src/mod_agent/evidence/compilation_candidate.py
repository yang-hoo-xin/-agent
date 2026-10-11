"""Use observed compiler locations for a bounded candidate, preserving Findings."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace

KEY = "compilation_repair_candidate"


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _derive(payload, worker_configuration_ref, feature_spec=None):
    from .models import EvidencePack
    from .requirement_coverage import is_exact_edit_target_evidence
    from .requirement_coverage import feature_spec_payload_sha256

    pack = EvidencePack.from_artifact_payload(payload)
    coverage = pack.requirement_coverage
    observation = pack.budget_summary.get("baseline_compilation_failure")
    if (pack.can_generate_patch or pack.readiness == "contradictory"
            or not isinstance(coverage, dict) or not isinstance(observation, dict)
            or observation.get("observation_kind") != "baseline_compilation_failure"
            or not pack.blockers
            or any(row.get("code") != "REQUIREMENT_COVERAGE_INSUFFICIENT" for row in pack.blockers)
            or any(row.get("relationship") == "conflict" for row in coverage["findings"])):
        return None
    identity = coverage["feature_spec_identity"]
    if feature_spec is not None and (
            identity["feature_id"] != feature_spec.get("feature_id")
            or identity["feature_spec_sha256"] != feature_spec_payload_sha256(feature_spec)
            or feature_spec.get("user_request") != pack.query):
        raise ValueError("COMPILATION_CANDIDATE_FEATURE_CHANGED")
    if (not isinstance(worker_configuration_ref, Mapping)
            or set(worker_configuration_ref) != {"path", "sha256"}
            or not isinstance(worker_configuration_ref["path"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", str(worker_configuration_ref["sha256"]))):
        return None
    ids = []
    for diagnostic in observation.get("diagnostics", []):
        if (not re.fullmatch(r"CS\d{4}", str(diagnostic.get("code")))
                or type(diagnostic.get("line")) is not int):
            return None
        matched = [item for item in pack.items if is_exact_edit_target_evidence(item)
            and item.source_path == diagnostic.get("file")
            and item.source_hash == diagnostic.get("source_sha256")
            and item.span["start_line"] <= diagnostic["line"] <= item.span["end_line"]]
        if not matched:
            return None
        ids.extend(item.evidence_id for item in matched)
    if not ids or observation.get("omitted_diagnostic_count", 0):
        return None
    questions = list(dict.fromkeys(str(gap) for row in coverage["findings"]
        for gap in row.get("unresolved_gaps", [])))
    return {
        "schema_version": "compilation_repair_candidate_v1",
        "mode": "candidate_edit_scope",
        "feature_id": identity["feature_id"],
        "feature_spec_sha256": identity["feature_spec_sha256"],
        "baseline_observation_sha256": _hash(observation),
        "findings_sha256": _hash(coverage),
        "evidence_ids": list(dict.fromkeys(ids)),
        "verification_questions": questions,
        "worker_configuration_ref": dict(worker_configuration_ref),
        "semantic_coverage_established": False,
        "authorization": "read_only_candidate_proposal; original Apply and verification boundaries remain",
    }


def attach_compilation_candidate(pack, *, feature_spec, worker_configuration_ref):
    """Attach a separate execution choice, leaving all semantic outcomes intact.

    为什么要有它：可定位源码错误允许提出候选；Findings 的不足判断仍保留，最终结果由现有实际验收决定。
    """
    scope = _derive(pack.to_artifact_payload(), worker_configuration_ref, feature_spec)
    if scope is None:
        return pack
    return replace(pack, budget_summary={**pack.budget_summary, KEY: scope})


def compilation_candidate_scope(evidence_payload, feature_spec=None):
    """Consumers use the same source/diagnostic identity without claiming support."""
    selected = evidence_payload.get("budget_summary", {}).get(KEY)
    if selected is None:
        return None
    if not isinstance(selected, dict):
        raise ValueError("COMPILATION_CANDIDATE_SCOPE_INVALID")
    expected = _derive(evidence_payload, selected.get("worker_configuration_ref"), feature_spec)
    if expected is None or selected != expected:
        raise ValueError("COMPILATION_CANDIDATE_SCOPE_CHANGED")
    from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration

    # 为什么要有它：所有消费者共用一次定义的检查器绑定检查，配置标志或模型建议不能替代实际可用的校验配置。
    reference = selected["worker_configuration_ref"]
    try:
        configuration = PatchWorkerConfiguration.load(reference["path"])
        if configuration.reference != reference or configuration.behavior_evaluator() is None:
            raise ValueError("COMPILATION_CANDIDATE_WORKER_INVALID")
    except (OSError, ValueError) as exc:
        raise ValueError("COMPILATION_CANDIDATE_WORKER_INVALID") from exc
    return deepcopy(expected)
