"""Metadata-only native observations for new Patch runs, with a bounded sink.

Mapping follows https://langfuse.com/integrations/native/opentelemetry and
https://langfuse.com/docs/observability/features/token-and-cost-tracking .
No SDK, environment/credential lookup, product state or durable retry ledger is
introduced. HTTP acceptance is recorded separately from remote readback.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import Counter, OrderedDict, deque
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.observability.patch_langfuse import (
    MAX_PAYLOAD_BYTES,
    LangfuseHttpTransport,
    _read_verified_json,
    _verified_check_counts,
)

LIVE_MAPPING_VERSION = "patch_live_langfuse_metadata_v3"
OTLP_ENDPOINT = "/api/public/otel/v1/traces"
SCORE_ENDPOINT = "/api/public/scores"
LIVE_BEHAVIOR_SCORE_NAME = "local_check_pass_fraction"
VERIFIED_SCORE_BASIS = "report_binds_retained_code_and_exact_matrix_local_checks"
SYMBOL_CHECK_OPERATION = "evidence.symbol_materialization"
SYMBOL_CHECK_SCORE_NAME = "indexed_symbol_declaration_match"
SYMBOL_CHECK_BASIS = "indexed_declaration_materialization_v1"
_SYMBOL_STATUSES = {"exact_declaration", "declaration_mismatch", "source_window_unconfirmed",
                    "partial_selection", "not_applicable", "unknown"}
_KINDS = frozenset({"span", "generation", "tool", "agent", "chain", "retriever", "guardrail", "evaluator", "embedding", "event"})
_DIGEST = re.compile(r"(?:sha256:)?[a-f0-9]{64}\Z")
_MACHINE_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
_METADATA_LABELS = frozenset({"provider", "response_origin", "tool_name", "source_kind", "status",
    "workflow_node", "workflow_status", "terminal_stage", "failure_code", "verification_status", "failure_owner", "execution_origin",
    "admission_result", "result_code", "timing_scope", "validator", "exception_type", "score_basis",
    "model_role", "reason_status", "route_decision", "trace_scope", "retrieval_status", "decision",
    "decision_status", "readiness", "input_role", "material_delivery_status", "selection_mode", "local_body_status",
    "from_node", "selected_route", "selected_next_node", "route_selector", "material_capture_status",
    "route_input_summary_scope", "route_input_summary_status", "route_output_summary_status",
    "failure_stage", "execution_phase", "fact_delivery_status", "symbol_check_status", "symbol_lookup_method", "context_admission_mode"})
_METADATA_NUMBERS = frozenset({"turn_index", "response_received", "response_complete", "http_status", "usage_available", "byte_count", "reused",
    "evaluation_index", "checks_run", "checks_failed", "transport_started", "request_bytes", "file_count",
    "proposal_admitted", "callback_invoked", "tool_dispatch_performed", "encoded_payload_bytes", "observation_queued",
    "model_consumption_proven", "read_cost", "prepared_before_dispatch", "dispatch_started", "request_registered",
    "upstream_execution_performed", "exit_code", "timed_out", "process_index", "process_count",
    "score_eligible", "verification_executions", "model_input_assembled", "unresolved_gap_count",
    "tool_exit_code", "evidence_item_count", "query_count", "requirement_count", "relation_count",
    "projection_fallback_used", "findings_invocation_performed", "can_generate_patch", "provider_failure_count",
    "callback_returned", "source_directory_exists", "project_file_discovered", "local_manifest_created",
    "input_member_access_count", "output_member_access_count", "added_member_access_count", "removed_member_access_count",
    "produced_member_access_fact_count", "provider_request_constructed", "provider_request_admitted",
    "exact_prompt_tokens_available_pre_call", "context_calibration_used"})
_METADATA_HASHES = frozenset({"request_sha256", "response_sha256", "observation_sha256",
    "behavior_report_sha256", "output_code_sha256", "output_sha256", "generated_changes_sha256", "baseline_sha256",
    "response_content_sha256", "source_snapshot_sha256", "encoded_payload_sha256", "arguments_sha256", "verification_matrix_sha256",
    "input_payload_sha256", "feature_payload_sha256", "evidence_payload_sha256", "structured_output_sha256",
    "materialized_projection_sha256", "output_payload_sha256", "reason_sha256", "query_sha256", "route_input_sha256",
    "input_member_access_facts_sha256", "output_member_access_facts_sha256", "produced_member_access_facts_sha256",
    "symbol_check_sha256", "provider_body_sha256"})
_IDENTITY_ATTRIBUTES = frozenset({"source_observation_id", "binding_id", "provider_response_id"})
_GATE_LABELS = {"failure_boundary": "provider_request_gate",
    "failure_classification": "provider_request_context_budget_exceeded"}
_GATE_NUMBERS = frozenset({"provider_body_utf8_bytes", "configured_num_ctx", "num_predict", "conservative_required_context",
    "estimated_prompt_tokens", "estimated_required_context", "observed_calibration_count"})
_UPSTREAM_ENUM_LABELS = {
    "context_admission_mode": {"provider_body_utf8_proxy_plus_output_budget_v1", "same_model_observed_prompt_ratio_upper_bound_v1"},
    "decision": {"patch_allowed", "patch_blocked", "select_targets", "needs_evidence", "retain_current_plan"},
    "decision_status": {"preparing", "running", "selected", "blocked", "retained_current_plan"},
    "readiness": {"sufficient", "partial", "insufficient", "contradictory"},
    "retrieval_status": {"source_scope_rejected", "source_root_missing", "query_terms_missing", "tool_failed",
        "no_matches", "source_identity_ambiguous", "requested_source_no_matches", "source_decode_failed", "source_observations_returned"},
    "local_body_status": {"request_write_failed", "response_write_failed", "response_tools_write_failed", "response_metadata_unavailable"},
    "reason_status": {"reason_unavailable", "model_rationale_local_only"},
    "trace_scope": {"product_execution"},
    "fact_delivery_status": {"evidence_pack_enriched_model_delivery_unproven", "evidence_pack_assembled_model_delivery_unproven"},
    "symbol_check_status": _SYMBOL_STATUSES,
    "symbol_lookup_method": {"symbol_exact", "bm25"},
}
ALLOWED_ATTRIBUTE_KEYS = _METADATA_LABELS | _METADATA_NUMBERS | _METADATA_HASHES | {
    "model", "usage", "call_id", "tool_call_id", "artifact_refs", "consumed_tool_results", "tool_call_ids",
    "consumed_materials", "produced_materials", "selected_evidence_ids", "relationship_counts", "local_detail_refs",
    "terminal_record_ref"} | _IDENTITY_ATTRIBUTES | frozenset(_GATE_LABELS) | _GATE_NUMBERS


def _materials(value: Any) -> list[dict] | None:
    """Export exact material identities, excluding paths and all source text."""
    if not isinstance(value, (tuple, list)):
        return None
    result = []
    for item in value[:256]:
        if not isinstance(item, Mapping):
            continue
        kept = {}
        for key in ("source_hash", "excerpt_sha256"):
            digest = item.get(key)
            if isinstance(digest, str) and _DIGEST.fullmatch(digest):
                kept[key] = digest
        identity = item.get("evidence_id")
        if isinstance(identity, str) and 0 < len(identity) <= 300:
            kept["evidence_id_sha256"] = _hash_text(identity)
        source_type = _machine_text(item.get("source_type"))
        if source_type is not None:
            kept["source_type"] = source_type
        # Partial identities may be shown, but a query must not join them as proof.
        if kept:
            result.append(kept)
    return result


def _symbol_check_metadata(attributes):
    """Read one local check receipt; raw declarations never enter this projection."""
    receipt = attributes.get("symbol_check")
    if not isinstance(receipt, Mapping):
        return {}
    try:
        if (_hash_text(_json(receipt).decode("utf-8")) != attributes.get("symbol_check_sha256")
                or receipt.get("basis") != SYMBOL_CHECK_BASIS or not isinstance(receipt.get("checks"), list)):
            return {}
        rows = []
        for item in receipt["checks"][:64]:
            if not isinstance(item, Mapping):
                return {}
            declaration, source, materialized = item.get("declaration"), item.get("source"), item.get("materialized")
            if not isinstance(declaration, Mapping) or not isinstance(source, Mapping):
                return {}
            kept = {"declaration_sha256": hashlib.sha256(_json(declaration)).hexdigest(),
                    "declaration_checked": item.get("declaration_checked") is True,
                    "status": item.get("status") if item.get("status") in _SYMBOL_STATUSES | {"not_materialized"} else "unknown"}
            for key, value in (("indexed_source_sha256", declaration.get("source_hash")),
                               ("live_source_sha256", source.get("source_hash"))):
                if isinstance(value, str) and _DIGEST.fullmatch(value):
                    kept[key] = value
            for key, value in (("signature_sha256", declaration.get("signature")),
                               ("source_declaration_line_sha256", source.get("declaration_line"))):
                if isinstance(value, str):
                    kept[key] = _hash_text(value)
            for key in ("start_line", "end_line"):
                if type(declaration.get(key)) is int and declaration[key] >= 1:
                    kept["indexed_" + key] = declaration[key]
            if isinstance(materialized, Mapping):
                kept["materialized_sha256"] = hashlib.sha256(_json(materialized)).hexdigest()
                for key in ("source_hash", "excerpt_sha256"):
                    value = materialized.get(key)
                    if isinstance(value, str) and _DIGEST.fullmatch(value):
                        kept["materialized_" + key] = value
                span = materialized.get("span", {})
                if isinstance(span, Mapping):
                    for key in ("start_line", "end_line"):
                        if type(span.get(key)) is int and span[key] >= 1:
                            kept["materialized_" + key] = span[key]
            rows.append(kept)
        return {"symbol_check_basis": SYMBOL_CHECK_BASIS, "symbol_declaration_checks": rows,
                "symbol_declaration_count": len(receipt["checks"]),
                "symbol_materialized_count": sum(isinstance(item.get("materialized"), Mapping) for item in receipt["checks"]),
                "symbol_check_projection_complete": len(receipt["checks"]) <= 64,
                "symbol_check_summary": {
                    "exact_declaration": "已核对索引声明、当前源码声明及物化方法起点一致。",
                    "declaration_mismatch": "实际声明一致性检查发现错位，原物化流程已拒绝。",
                    "source_window_unconfirmed": "仅得到源码窗口，未确认完整方法声明一致。",
                    "partial_selection": "声明集合只物化了一部分，不计完整检查通过。",
                    "not_applicable": "本次不属于精确符号声明检查，不计通过分。",
                    "unknown": "声明检查没有形成可确认结果。",
                }.get(receipt.get("status"), "声明检查结果未知。") + "不代表需求相关性或任务完成。"}
    except (TypeError, ValueError, KeyError):
        return {}


def _decision_metadata(attributes: Mapping) -> dict:
    """Summarize recorded structure; never relay free-form model explanations."""
    result = {}
    details = attributes.get("local_detail_refs")
    if isinstance(details, Mapping):
        kept = {}
        for role in ("request", "response", "planning_receipt", "response_tools", "failure"):
            item = details.get(role)
            digest = item.get("sha256") if isinstance(item, Mapping) else None
            if isinstance(digest, str) and _DIGEST.fullmatch(digest):
                kept[role] = {"sha256": digest}
        if kept:
            result["local_detail_refs"] = kept
    terminal = attributes.get("terminal_record_ref")
    digest = terminal.get("sha256") if isinstance(terminal, Mapping) else None
    if isinstance(digest, str) and _DIGEST.fullmatch(digest):
        result["terminal_record_ref"] = {"sha256": digest}
    for key in ("consumed_materials", "produced_materials"):
        materials = _materials(attributes.get(key))
        if materials is not None:
            result[key] = materials
            result[key + "_truncated"] = len(attributes[key]) > 256
    selected = attributes.get("selected_evidence_ids")
    if isinstance(selected, (tuple, list)):
        result["selected_evidence_id_sha256s"] = [_hash_text(value) for value in selected[:256]
            if isinstance(value, str) and 0 < len(value) <= 300]
        result["selected_evidence_ids_truncated"] = len(selected) > 256
    raw = attributes.get("relationship_counts")
    if isinstance(raw, Mapping):
        counts = {key: raw[key] for key in ("support", "conflict", "missing")
                  if type(raw.get(key)) is int and raw[key] >= 0}
        if counts:
            result["relationship_counts"] = counts
    pieces = []
    if type(attributes.get("source_directory_exists")) is bool:
        pieces.append("材料目录存在" if attributes["source_directory_exists"] else "材料目录不存在")
    if type(attributes.get("project_file_discovered")) is bool:
        pieces.append("已发现项目文件" if attributes["project_file_discovered"] else "未发现项目文件")
    failure_stage = _machine_text(attributes.get("failure_stage"))
    if failure_stage is not None:
        pieces.append("记录失败阶段 " + failure_stage)
    for key, label in (("input_member_access_count", "增强前API事实"), ("output_member_access_count", "增强后API事实"),
                       ("added_member_access_count", "新增API事实"), ("removed_member_access_count", "移除API事实"),
                       ("produced_member_access_fact_count", "最终证据包API事实")):
        if type(attributes.get(key)) is int and attributes[key] >= 0:
            pieces.append(label + str(attributes[key]) + "项")
    fact_delivery = attributes.get("fact_delivery_status")
    if isinstance(fact_delivery, str) and fact_delivery in _UPSTREAM_ENUM_LABELS["fact_delivery_status"]:
        pieces.append("整包API事实是否传给模型尚未证明")
    for key, label in (("requirement_count", "物化需求"), ("relation_count", "关系"), ("query_count", "检索查询")):
        if type(attributes.get(key)) is int and attributes[key] >= 0:
            pieces.append(label + str(attributes[key]) + "项")
    retrieval_labels = {"source_scope_rejected": "材料范围未准入", "source_root_missing": "材料目录不存在",
        "query_terms_missing": "缺少检索词", "tool_failed": "检索工具失败", "no_matches": "该次检索无匹配",
        "source_identity_ambiguous": "材料身份不唯一", "requested_source_no_matches": "指定材料无匹配",
        "source_decode_failed": "材料解码失败", "source_observations_returned": "已返回源码观察"}
    if isinstance(attributes.get("retrieval_status"), str) and attributes["retrieval_status"] in retrieval_labels:
        pieces.append(retrieval_labels[attributes["retrieval_status"]])
    decision_labels = {"patch_allowed": "确定性判断允许进入Patch", "patch_blocked": "确定性判断阻止进入Patch",
        "select_targets": "模型选择修改目标", "needs_evidence": "模型请求补充证据", "retain_current_plan": "模型建议保留原Plan"}
    if isinstance(attributes.get("decision"), str) and attributes["decision"] in decision_labels:
        pieces.append(decision_labels[attributes["decision"]])
    from_node = _machine_text(attributes.get("from_node"))
    selected_next = attributes.get("selected_next_node")
    next_node = selected_next if selected_next == "__end__" else _machine_text(selected_next)
    if from_node is not None and next_node is not None:
        pieces.append("已选择路线 " + from_node + " → " + next_node + "（后续是否执行另查）")
    if "relationship_counts" in result:
        labels = {"support": "支持", "conflict": "冲突", "missing": "缺证"}
        pieces.append("结构化判断：" + "，".join(labels[key] + str(value)
                      for key, value in result["relationship_counts"].items()))
    if "selected_evidence_id_sha256s" in result:
        pieces.append("记录选择证据" + str(len(result["selected_evidence_id_sha256s"])) + "项")
    for key, label in (("produced_materials", "记录返回材料"), ("consumed_materials", "记录输入材料")):
        if key in result:
            pieces.append(label + str(len(result[key])) + "项")
    if type(attributes.get("unresolved_gap_count")) is int and attributes["unresolved_gap_count"] >= 0:
        pieces.append("未解决缺口" + str(attributes["unresolved_gap_count"]) + "项")
    if pieces:
        result["decision_summary"] = "；".join(pieces) + "。计数不证明语义正确或实际模型消费。"
        result["decision_summary_origin"] = "system_fact_from_recorded_structure"
        if "relationship_counts" in result or "selected_evidence_id_sha256s" in result:
            mode, role, decision = attributes.get("selection_mode"), attributes.get("model_role"), attributes.get("decision")
            model_claim = (mode == "model" or isinstance(role, str) and role in {
                "requirement_findings", "requirement_findings_correction", "planning"}
                or isinstance(decision, str) and decision in {"select_targets", "needs_evidence", "retain_current_plan"})
            result["decision_claim_origin"] = ("model_claim_requires_validation" if model_claim
                else "injected_claim_requires_validation" if mode == "injected" else "recorded_claim_origin_unknown")
    return result


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _machine_text(value: Any) -> str | None:
    if (isinstance(value, str) and _MACHINE_TEXT.fullmatch(value)
            and ":/" not in value and ".." not in value):
        return value
    return None


def _identity(value: Any, size: int, domain: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 300:
        raise ValueError("LIVE_OBSERVATION_ID_INVALID")
    if re.fullmatch(r"[0-9a-f]{" + str(size) + "}", value) and set(value) != {"0"}:
        return value
    return _hash_text(domain + ":" + value)[:size]


def live_trace_id(value: str) -> str:
    return _identity(value, 32, "patch-trace")


def live_observation_id(value: str) -> str:
    return _identity(value, 16, "patch-observation")


def _utc_nanos(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError("LIVE_OBSERVATION_TIME_REQUIRED")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("LIVE_OBSERVATION_TIMEZONE_REQUIRED")
    delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def _attribute(key: str, value: Any) -> dict:
    if type(value) is bool:
        encoded = {"boolValue": value}
    elif type(value) is int:
        encoded = {"intValue": str(value)}
    elif type(value) is float:
        encoded = {"doubleValue": value}
    else:
        encoded = {"stringValue": value if isinstance(value, str) else _json(value).decode("utf-8")}
    return {"key": key, "value": encoded}


def _usage(attributes: Mapping) -> tuple[dict | None, str]:
    if attributes.get("usage_available") is not True:
        return None, "unknown"
    raw = attributes.get("usage")
    if not isinstance(raw, Mapping) or any(type(raw.get(key)) is not int or raw[key] < 0
        for key in ("input_tokens", "output_tokens")):
        return None, "invalid_counts"
    buckets = {"input": raw["input_tokens"], "output": raw["output_tokens"]}
    for field, aggregate, subtype in (("cached_input_tokens", "input", "input_cached_tokens"),
                                     ("reasoning_tokens", "output", "output_reasoning_tokens")):
        if field not in raw:
            continue
        if type(raw[field]) is not int or not 0 <= raw[field] <= buckets[aggregate]:
            return None, "invalid_inclusive_subtype"
        buckets[aggregate] -= raw[field]
        buckets[subtype] = raw[field]
    return buckets, "inclusive_provider_counts_to_exclusive_buckets"


def _metadata(attributes: Mapping) -> dict:
    result = {key: value for key, value in _GATE_LABELS.items() if attributes.get(key) == value}
    result.update(_decision_metadata(attributes))
    result.update(_symbol_check_metadata(attributes))
    audit = attributes.get("requirement_findings_attempt_audit")
    if isinstance(audit, (list, tuple)):
        result["requirement_findings_attempt_audit"] = _findings_audit(audit)
        result["requirement_findings_attempt_audit_sha256"] = hashlib.sha256(_json(audit)).hexdigest()
    for key in _GATE_NUMBERS:
        value = attributes.get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    for key in _METADATA_LABELS:
        raw_value = attributes.get(key)
        if key == "selected_next_node" and raw_value == "__end__":
            result[key] = raw_value
            continue
        if key == "route_selector" and isinstance(raw_value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", raw_value):
            result[key] = raw_value
            continue
        value = _machine_text(attributes.get(key))
        if key in _UPSTREAM_ENUM_LABELS and value not in _UPSTREAM_ENUM_LABELS[key]:
            continue
        if key == "exception_type" and (value is None or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", value)):
            continue
        if value is not None:
            result[key] = value
    for key in _METADATA_NUMBERS:
        value = attributes.get(key)
        if type(value) in (bool, int) or type(value) is float and math.isfinite(value):
            result[key] = value
    for key in _METADATA_HASHES:
        value = attributes.get(key)
        if isinstance(value, str) and _DIGEST.fullmatch(value):
            result[key] = value
    call_ids = {attributes[key] for key in ("call_id", "tool_call_id")
        if isinstance(attributes.get(key), str) and len(attributes[key]) <= 300}
    if len(call_ids) == 1:
        result["call_id_sha256"] = _hash_text(next(iter(call_ids)))
    elif len(call_ids) > 1:
        result["call_identity_conflict"] = True
    for key in _IDENTITY_ATTRIBUTES:
        if isinstance(attributes.get(key), str) and len(attributes[key]) <= 300:
            result[key + "_sha256"] = _hash_text(attributes[key])
    calls = attributes.get("tool_call_ids")
    if isinstance(calls, (tuple, list)):
        result["tool_call_id_sha256s"] = [_hash_text(value) for value in calls[:64]
            if isinstance(value, str) and len(value) <= 300]
    consumed = attributes.get("consumed_tool_results")
    if isinstance(consumed, (tuple, list)):
        result["consumed_tool_results"] = []
        for item in consumed[:64]:
            if not isinstance(item, Mapping):
                continue
            kept = {}
            if isinstance(item.get("call_id"), str) and len(item["call_id"]) <= 300:
                kept["call_id_sha256"] = _hash_text(item["call_id"])
            value = item.get("observation_sha256")
            if isinstance(value, str) and _DIGEST.fullmatch(value):
                kept["observation_sha256"] = value
            if kept:
                result["consumed_tool_results"].append(kept)
    refs = attributes.get("artifact_refs")
    if isinstance(refs, Mapping):
        refs = list(refs.values())[:32]
    if isinstance(refs, (tuple, list)):
        result["artifact_refs"] = []
        for item in refs[:32]:
            if not isinstance(item, Mapping):
                continue
            kept = {}
            for key in ("type", "artifact_type"):
                if _machine_text(item.get(key)) is not None:
                    kept[key] = item[key]
            for key in ("hash", "artifact_hash", "sha256"):
                if isinstance(item.get(key), str) and _DIGEST.fullmatch(item[key]):
                    kept[key] = item[key]
            if type(item.get("revision")) is int and item["revision"] >= 0:
                kept["revision"] = item["revision"]
            if kept:
                result["artifact_refs"].append(kept)
    return result


def _findings_audit(rows) -> list[dict]:
    """Project the native audit without model free text or source identifiers."""
    result = []
    known_errors = {"REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID",
                    "REQUIREMENT_COVERAGE_FINDING_INVALID", "PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED"}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("status") not in {"accepted", "rejected", "failed"}:
            continue
        kept = {"status": row["status"]}
        if type(row.get("attempt_index")) is int and row["attempt_index"] > 0:
            kept["attempt_index"] = row["attempt_index"]
        error = row.get("error_code")
        kept["error_code"] = error if error is None or isinstance(error, str) and error in known_errors else "unclassified_error"
        if isinstance(error, str):
            kept["error_sha256"] = _hash_text(error)
        for key in ("rejected_output_sha256", "correction_payload_sha256", "response_schema_sha256"):
            if isinstance(row.get(key), str) and _DIGEST.fullmatch(row[key]):
                kept[key] = row[key]
        if type(row.get("correction_payload_prepared")) is bool:
            kept["correction_payload_prepared"] = row["correction_payload_prepared"]
        diagnostic = row.get("diagnostic")
        if isinstance(diagnostic, Mapping):
            summary = {"diagnostic_sha256": hashlib.sha256(_json(diagnostic)).hexdigest()}
            if type(diagnostic.get("relation_index")) is int:
                summary["relation_index"] = diagnostic["relation_index"]
            for field, name in (("edit_target_evidence_ids", "edit_target_count"),
                                ("evidence_ids", "evidence_count"), ("unresolved_gaps", "unresolved_gap_count")):
                if isinstance(diagnostic.get(field), list):
                    summary[name] = len(diagnostic[field])
                    summary[field + "_sha256"] = hashlib.sha256(_json(diagnostic[field])).hexdigest()
            kept["diagnostic"] = summary
        boundary = row.get("call_boundary")
        if isinstance(boundary, Mapping):
            summary = {}
            if boundary.get("budget_stage") == "requirement_findings":
                summary["budget_stage"] = boundary["budget_stage"]
            for key in ("reservation_succeeded", "model_request_invoked", "model_transport_started"):
                if type(boundary.get(key)) is bool:
                    summary[key] = boundary[key]
            budget = boundary.get("budget")
            if isinstance(budget, Mapping):
                def counts(value):
                    return {key: value[key] for key in ("maximum", "consumed", "remaining")
                            if type(value.get(key)) is int and value[key] >= 0}
                selected = counts(budget)
                stages = budget.get("by_stage")
                if isinstance(stages, Mapping):
                    selected["by_stage"] = {role: counts(stages[role]) for role in (
                        "requirement_projection", "requirement_findings", "planning", "initial_patch", "repair")
                        if isinstance(stages.get(role), Mapping)}
                summary["budget"] = selected
            kept["call_boundary"] = summary
        result.append(kept)
    return result


def prepare_product_journal_export(journal_path, expected_sha256, *, trace_id) -> dict:
    """Prepare finished native observations with their original times, no I/O sink.

    Unlike Patch historical snapshots, these rows already have recorded native
    identities and timing. Never invent an absent row or populate an old audit.
    """
    journal = _read_verified_json({"path": str(journal_path), "sha256": expected_sha256,
                                   "integrity": "verified_bytes"})
    if journal is None or not isinstance(journal.get("execution_observations"), dict):
        raise ValueError("PRODUCT_JOURNAL_IDENTITY_INVALID")
    rows = list(journal["execution_observations"].values())
    if not rows or any(not isinstance(row, Mapping) or live_trace_id(row.get("trace_id")) != trace_id for row in rows):
        raise ValueError("PRODUCT_JOURNAL_TRACE_MISMATCH")
    spans = []
    for row in rows:
        payload = build_patch_live_otlp(row)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        span["attributes"] = [a for a in span["attributes"] if a["key"] not in {
            "langfuse.observation.metadata.historical_import", "langfuse.trace.tags"}]
        span["attributes"].extend([
            _attribute("langfuse.observation.metadata.historical_import", True),
            _attribute("langfuse.observation.metadata.timing_basis", "recorded_original_execution"),
            _attribute("langfuse.observation.metadata.source_journal_sha256", expected_sha256),
            _attribute("langfuse.observation.metadata.source_run_id_sha256", _hash_text(journal["run_id"])),
            {"key": "langfuse.trace.tags", "value": {"arrayValue": {"values": [
                {"stringValue": "retained_native_observations"}, {"stringValue": "metadata_only"}]}}},
        ])
        spans.append(span)
    identities = [span["spanId"] for span in spans]
    if len(set(identities)) != len(identities) or any(
            span.get("parentSpanId") is not None and span["parentSpanId"] not in identities for span in spans):
        raise ValueError("PRODUCT_JOURNAL_TREE_INVALID")
    prepared = {"trace_id": trace_id, "run_id": journal["run_id"],
                "source_journal_sha256": expected_sha256, "observation_ids": identities, "scores": [],
                "otlp": {"resourceSpans": [{"resource": {"attributes": [_attribute("service.name", "mod-agent-execution")]},
                                           "scopeSpans": [{"scope": {"name": "mod_agent.patch_live", "version": LIVE_MAPPING_VERSION},
                                                           "spans": spans}]}]}}
    if len(_json(prepared["otlp"])) > MAX_PAYLOAD_BYTES:
        raise ValueError("PRODUCT_JOURNAL_EXPORT_TOO_LARGE")
    return prepared


def _native_status(row: Mapping, attributes: Mapping) -> tuple[str, str]:
    """Expose business negatives while preserving the observation's execution status."""
    if row["name"] == SYMBOL_CHECK_OPERATION:
        status = attributes.get("symbol_check_status")
        status = status if isinstance(status, str) and status in _SYMBOL_STATUSES else "unknown"
        level = "ERROR" if row["status"] == "failed" or status == "declaration_mismatch" else (
            "DEFAULT" if status in {"exact_declaration", "not_applicable"} else "WARNING")
        return level, f"symbol_check_status={status};declaration_identity_not_task_quality"
    if row["status"] == "failed":
        exception = _metadata(attributes).get("exception_type")
        return "ERROR", "operation_failed" + (":" + exception if exception else "")
    if isinstance(attributes.get("decision"), str) and attributes["decision"] in {"patch_blocked", "needs_evidence"}:
        return "WARNING", f"decision={attributes['decision']};operation_completed;not_task_acceptance"
    if isinstance(attributes.get("retrieval_status"), str) and attributes["retrieval_status"] in {"source_scope_rejected", "source_root_missing", "query_terms_missing",
            "tool_failed", "no_matches", "source_identity_ambiguous", "requested_source_no_matches", "source_decode_failed"}:
        return "WARNING", f"retrieval_status={attributes['retrieval_status']};not_semantic_root_cause"
    if row["name"] == "patch.verify":
        status = attributes.get("verification_status")
        if status not in {"passed", "behavior_failed", "needs_evidence", "infrastructure_failed", "identity_failed"}:
            status = "unknown"
        origin = attributes.get("execution_origin")
        if origin not in {"executed", "reused", "unknown", "incomplete"}:
            origin = "unknown"
        level = "WARNING" if status in {"behavior_failed", "needs_evidence", "infrastructure_failed", "identity_failed"} else "DEFAULT"
        return level, f"verification_status={status};execution_origin={origin};not_task_acceptance"
    workflow = attributes.get("workflow_status")
    if workflow in {"partial", "blocked", "failed"}:
        return "WARNING", f"workflow_status={workflow};operation_completed;not_task_acceptance"
    return "DEFAULT", "operation_completed;not_task_acceptance"


def verified_behavior_trace_attributes(report: Mapping, model_response: Mapping) -> dict:
    """Read existing bound proof, returning only counts and hashes for new traces.

    Reuses the historical importer's exact matrix checks without importing history.
    Failure to prove a score is metadata, never a verifier/product exception.
    """
    unavailable = {"score_eligible": False, "score_basis": "not_emitted_missing_or_inconsistent_bound_verification"}
    try:
        if (not isinstance(report, Mapping) or not isinstance(model_response, Mapping)
                or report.get("admission") != "accepted" or report.get("callback_invoked") is not True
                or report.get("execution_origin") != "executed"
                or report.get("status") not in {"passed", "behavior_failed"}):
            return unavailable
        response_hash = model_response.get("output_sha256")
        if (not isinstance(response_hash, str) or not _DIGEST.fullmatch(response_hash)
                or report.get("model_response_sha256") != response_hash):
            return unavailable
        response_path = Path(model_response["path"])
        if response_path.stat().st_size > MAX_PAYLOAD_BYTES:
            return unavailable
        response_bytes = response_path.read_bytes()
        if len(response_bytes) > MAX_PAYLOAD_BYTES or hashlib.sha256(response_bytes).hexdigest() != response_hash:
            return unavailable
        # This adapter supplies the historical reader's reference shape; that
        # reader still rereads the bytes and independently verifies each hash.
        retained_refs = {key: {**dict(report[key]), "integrity": "verified_bytes"}
                         for key in ("report_ref", "verification_ref")}
        persisted = _read_verified_json(retained_refs["report_ref"])
        code = report.get("materialized_code_identity")
        if (persisted is None or not isinstance(code, Mapping) or not code
                or ("model_response_sha256" in persisted and persisted["model_response_sha256"] != response_hash)
                or any(not isinstance(report.get(key), str) or not _DIGEST.fullmatch(report[key])
                       for key in ("generated_changes_sha256", "source_snapshot_sha256"))
                or any(not isinstance(code.get(key), str) or not _DIGEST.fullmatch(code[key])
                       for key in ("baseline_sha256", "code_sha256"))
                or code != persisted.get("materialized_code_identity")
                or report.get("generated_changes_sha256") != persisted.get("generated_changes_sha256")):
            return unavailable
        evaluation = {
            **dict(report), **retained_refs, "execution_observation": "executed",
            "generated_changes_report_link": "matching_explicit_identity",
            "materialized_code_report_link": "matching_explicit_identity",
            "code_response_link": "matching_explicit_response_hash",
            "code_response_refs": [{"integrity": "verified_bytes", "output_sha256": response_hash}],
        }
        counts = _verified_check_counts(evaluation)
        if counts is None:
            return unavailable
        checks, failed = counts
        return {"score_eligible": True, "score_basis": VERIFIED_SCORE_BASIS,
                "checks_run": checks, "checks_failed": failed,
                "verification_executions": report["verification_summary"]["executions"],
                "verification_matrix_sha256": report["verification_ref"]["sha256"],
                "source_snapshot_sha256": report["source_snapshot_sha256"],
                "admission_result": "accepted"}
    except Exception:
        # Observability proof cannot change an already-admitted verifier result.
        return {"score_eligible": False, "score_basis": "not_emitted_proof_projection_failed"}


def _build_symbol_check_scores(row, attributes):
    receipt = attributes.get("symbol_check")
    if not isinstance(receipt, Mapping):
        return ()
    try:
        if (row.get("kind") != "span" or receipt.get("basis") != SYMBOL_CHECK_BASIS
                or receipt.get("observation_id") != row.get("id") or receipt.get("trace_id") != row.get("trace_id")
                or receipt.get("lookup_method") != "symbol_exact"
                or attributes.get("symbol_lookup_method") != "symbol_exact"
                or attributes.get("symbol_check_status") != receipt.get("status")
                or hashlib.sha256(_json(receipt)).hexdigest() != attributes.get("symbol_check_sha256")):
            return ()
        rows = receipt.get("checks")
        if not isinstance(rows, list) or not rows or len(rows) > 64:
            return ()
        passed, mismatched = [], []
        for item in rows:
            declaration, source, actual = item["declaration"], item["source"], item["materialized"]
            if (item.get("declaration_checked") is not True or not isinstance(declaration, Mapping)
                    or not isinstance(source, Mapping) or not all(isinstance(part.get("source_hash"), str)
                    and _DIGEST.fullmatch(part["source_hash"]) for part in (declaration, source))
                    or not isinstance(declaration.get("signature"), str) or not declaration["signature"]
                    or not isinstance(source.get("declaration_line"), str)
                    or type(declaration.get("start_line")) is not int or declaration["start_line"] < 1):
                return ()
            declaration_matches = (declaration["source_hash"] == source["source_hash"]
                                   and declaration["signature"] == source["declaration_line"])
            positive_method = (isinstance(actual, Mapping) and declaration.get("kind") == "method"
                               and actual.get("method_name") is not None)
            materialized_matches = (positive_method and isinstance(actual.get("span"), Mapping)
                and actual.get("method_name") == declaration.get("name")
                and actual["span"].get("start_line") == declaration["start_line"])
            original_guard_mismatch = (not declaration_matches or positive_method and not materialized_matches)
            mismatched.append(item.get("status") == "declaration_mismatch" and original_guard_mismatch)
            passed.append(item.get("status") == "exact_declaration" and declaration_matches and materialized_matches
                and actual.get("method_kind") == "method" and actual.get("source_hash") == source["source_hash"]
                and declaration.get("source_path") == source.get("source_path") == actual.get("source_ref")
                and actual.get("source_path") == source.get("relative_path")
                and isinstance(actual.get("excerpt_sha256"), str) and _DIGEST.fullmatch(actual["excerpt_sha256"]) is not None)
        if receipt["status"] == "exact_declaration" and row.get("status") == "completed" and all(passed):
            value = 1
        elif receipt["status"] == "declaration_mismatch" and row.get("status") == "failed" and any(mismatched):
            value = 0
        else:
            return ()
        trace_id, span_id = live_trace_id(row["trace_id"]), live_observation_id(row["id"])
        return ({"id": _hash_text(f"{trace_id}:{span_id}:{SYMBOL_CHECK_SCORE_NAME}"), "traceId": trace_id,
            "observationId": span_id, "name": SYMBOL_CHECK_SCORE_NAME, "dataType": "NUMERIC", "value": value,
            "comment": "Executed indexed declaration/materialization consistency check; not relevance, behavior or task acceptance."},)
    except (KeyError, TypeError, ValueError):
        return ()


def build_patch_live_scores(row: Mapping) -> tuple[dict, ...]:
    """Score executed local checks, never an absent check or task-delivery claim."""
    attrs = row.get("attributes") if isinstance(row.get("attributes"), Mapping) else {}
    if row.get("name") == SYMBOL_CHECK_OPERATION:
        return _build_symbol_check_scores(row, attrs)
    status = attrs.get("verification_status")
    checks, failed, executions = (attrs.get(key) for key in ("checks_run", "checks_failed", "verification_executions"))
    if (row.get("name") != "patch.verify" or row.get("status") != "completed"
            or attrs.get("score_eligible") is not True or attrs.get("score_basis") != VERIFIED_SCORE_BASIS
            or attrs.get("admission_result") != "accepted" or attrs.get("execution_origin") != "executed"
            or attrs.get("callback_invoked") is not True or status not in {"passed", "behavior_failed"}
            or type(checks) is not int or checks < 1 or type(failed) is not int or not 0 <= failed <= checks
            or type(executions) is not int or executions < 1
            or (status == "passed") != (failed == 0)
            or any(not isinstance(attrs.get(key), str) or not _DIGEST.fullmatch(attrs[key]) for key in (
                "behavior_report_sha256", "output_code_sha256", "output_sha256", "generated_changes_sha256",
                "source_snapshot_sha256", "verification_matrix_sha256"))):
        return ()
    trace_id, span_id = live_trace_id(row["trace_id"]), live_observation_id(row["id"])
    return ({"id": _hash_text(f"{trace_id}:{span_id}:{LIVE_BEHAVIOR_SCORE_NAME}"),
             "traceId": trace_id, "observationId": span_id, "name": LIVE_BEHAVIOR_SCORE_NAME,
             "value": (checks - failed) / checks, "dataType": "NUMERIC",
             "comment": f"live_metadata; {checks - failed}/{checks} bound executed local checks; not task acceptance, Mod delivery or Runtime."},)


def build_patch_live_otlp(row: Mapping) -> dict:
    """Map a completed neutral observation; never create missing timing facts."""
    if not isinstance(row, Mapping) or row.get("status") not in {"completed", "failed"}:
        raise ValueError("LIVE_OBSERVATION_NOT_FINISHED")
    kind, name = row.get("kind"), row.get("name")
    if kind not in _KINDS or not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("LIVE_OBSERVATION_KIND_OR_NAME_INVALID")
    started, finished = _utc_nanos(row.get("started_at")), _utc_nanos(row.get("finished_at"))
    if not 0 < started <= finished:
        raise ValueError("LIVE_OBSERVATION_TIME_ORDER_INVALID")
    attributes = row.get("attributes") if isinstance(row.get("attributes"), Mapping) else {}
    metadata = _metadata(attributes)
    metadata.update(mapping_version=LIVE_MAPPING_VERSION, metadata_only=True,
        source_prompt_output_included=False, historical_import=False, observation_status=row["status"])
    elapsed = row.get("elapsed_ms")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        metadata["recorded_elapsed_ms"] = elapsed
    level, status_message = _native_status(row, attributes)
    attrs = [_attribute("langfuse.observation.type", kind),
             _attribute("langfuse.trace.name", "Product execution" if attributes.get("trace_scope") == "product_execution" else "Patch execution"),
             {"key": "langfuse.trace.tags", "value": {"arrayValue": {"values": [
                 {"stringValue": "live_execution"}, {"stringValue": "metadata_only"}]}}},
             _attribute("langfuse.observation.level", level),
             _attribute("langfuse.observation.status_message", status_message)]
    if row.get("session_id") is not None:
        session = _machine_text(row["session_id"])
        if session is None:
            raise ValueError("LIVE_OBSERVATION_SESSION_INVALID")
        attrs.append(_attribute("session.id", session))
    if row.get("environment") is not None:
        environment = _machine_text(row["environment"])
        if environment is None:
            raise ValueError("LIVE_OBSERVATION_ENVIRONMENT_INVALID")
        attrs.append(_attribute("langfuse.environment", environment))
    if kind == "generation":
        model = _machine_text(attributes.get("model"))
        if model is not None:
            attrs.append(_attribute("langfuse.observation.model.name", model))
        usage, usage_status = _usage(attributes)
        metadata["usage_mapping_status"] = usage_status
        if usage is not None:
            attrs.append(_attribute("langfuse.observation.usage_details", usage))
    attrs.extend(_attribute("langfuse.observation.metadata." + key, value) for key, value in sorted(metadata.items()))
    span = {"traceId": live_trace_id(row.get("trace_id")), "spanId": live_observation_id(row.get("id")),
            "name": name, "kind": 1, "startTimeUnixNano": str(started), "endTimeUnixNano": str(finished),
            "status": {"code": 2 if row["status"] == "failed" else 1}, "attributes": attrs}
    if row.get("parent_id") is not None:
        parent = live_observation_id(row["parent_id"])
        if parent == span["spanId"]:
            raise ValueError("LIVE_OBSERVATION_SELF_PARENT")
        span["parentSpanId"] = parent
    return {"resourceSpans": [{"resource": {"attributes": [_attribute("service.name", "mod-agent-execution")]},
        "scopeSpans": [{"scope": {"name": "mod_agent.patch_live", "version": LIVE_MAPPING_VERSION}, "spans": [span]}]}]}


class PatchLiveLangfuseSink:
    """Nonblocking publisher; one bounded queue, one daemon HTTP worker, no retry.

    shutdown closes admission immediately and drains until its total deadline.
    An already-running transport cannot be killed by Python: timeout returns
    pending/worker_alive, and that worker may finish later. No process-level
    cancellation, durable delivery or remote readback is implied.
    """

    def __init__(self, transport: LangfuseHttpTransport, *, max_queue_size=128, max_recent_ids=2048,
                 max_payload_bytes=65536):
        if (not callable(getattr(transport, "_request", None)) or type(max_queue_size) is not int
                or not 1 <= max_queue_size <= 1024 or type(max_recent_ids) is not int or not 1 <= max_recent_ids <= 8192
                or type(max_payload_bytes) is not int or not 1024 <= max_payload_bytes <= 262144):
            raise ValueError("LIVE_SINK_CONFIGURATION_INVALID")
        self._transport = transport
        self._capacity, self._recent_capacity, self._max_payload = max_queue_size, max_recent_ids, max_payload_bytes
        self._condition = threading.Condition()
        self._queue = deque()
        self._recent = OrderedDict()
        self._pending = {}
        self._counts = Counter()
        self._active = 0
        self._closed = False
        self._last_error = None
        self._thread = threading.Thread(target=self._drain, name="patch-langfuse-export", daemon=True)
        self._thread.start()

    def publish(self, row: Mapping) -> None:
        with self._condition:
            if self._closed:
                self._counts["rejected_after_shutdown"] += 1
                return
            self._counts["received"] += 1
        if isinstance(row, Mapping) and row.get("status") == "running" and row.get("finished_at") is None:
            with self._condition:
                self._counts["running_not_exported"] += 1
            return
        try:
            payload = build_patch_live_otlp(row)
            scores = build_patch_live_scores(row)
            raw = _json({"observation": payload, "scores": scores})
            if len(raw) > self._max_payload:
                raise ValueError("LIVE_OBSERVATION_PAYLOAD_TOO_LARGE")
            span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            key = (span["traceId"], span["spanId"])
            digest = hashlib.sha256(raw).hexdigest()
        except Exception:
            with self._condition:
                self._counts["invalid_records"] += 1
            return
        with self._condition:
            if self._closed:
                self._counts["rejected_after_shutdown"] += 1
            elif key in self._pending or key in self._recent:
                prior = self._pending.get(key, self._recent.get(key))
                self._counts["duplicate_records" if prior == digest else "conflicting_updates"] += 1
            elif len(self._queue) >= self._capacity:
                self._counts["queue_dropped"] += 1
            else:
                self._queue.append((payload, scores, key))
                self._pending[key] = digest
                self._recent[key] = digest
                while len(self._recent) > self._recent_capacity:
                    self._recent.popitem(last=False)
                self._counts["queued"] += 1
                self._counts["score_queued"] += len(scores)
                self._condition.notify_all()

    def _drain(self):
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue and self._closed:
                    return
                payload, scores, key = self._queue.popleft()
                self._active = 1
                self._counts["post_attempts"] += 1
            try:
                response = self._transport._request("POST", OTLP_ENDPOINT, payload=payload)
                if not isinstance(response, Mapping) or not isinstance(response.get("partialSuccess", {}), Mapping):
                    raise ValueError("LIVE_OTLP_RESPONSE_INVALID")
                partial = response.get("partialSuccess", {})
                rejected = int(partial.get("rejectedSpans", 0))
                if rejected < 0:
                    raise ValueError("LIVE_OTLP_RESPONSE_INVALID")
                with self._condition:
                    self._counts["partial_responses" if rejected else "http_accepted"] += 1
                if rejected:
                    with self._condition:
                        self._counts["score_skipped_unaccepted_observation"] += len(scores)
                else:
                    for score in scores:
                        with self._condition:
                            self._counts["score_post_attempts"] += 1
                        try:
                            self._transport._request("POST", SCORE_ENDPOINT, payload=score)
                            with self._condition:
                                self._counts["score_http_accepted"] += 1
                        except Exception as exc:
                            with self._condition:
                                self._counts["score_send_failures"] += 1
                                self._last_error = type(exc).__name__
            except Exception as exc:
                with self._condition:
                    self._counts["send_failures"] += 1
                    self._counts["score_skipped_unaccepted_observation"] += len(scores)
                    self._last_error = type(exc).__name__  # Never retain the exception text or request headers.
            finally:
                with self._condition:
                    self._active = 0
                    self._pending.pop(key, None)
                    self._condition.notify_all()

    def stats(self) -> dict:
        with self._condition:
            return {**{key: self._counts[key] for key in (
                "received", "running_not_exported", "queued", "duplicate_records", "conflicting_updates",
                "invalid_records", "queue_dropped", "post_attempts", "http_accepted", "partial_responses",
                "send_failures", "rejected_after_shutdown", "score_queued", "score_post_attempts",
                "score_http_accepted", "score_send_failures", "score_skipped_unaccepted_observation")},
                "pending": len(self._queue) + self._active, "queued_pending": len(self._queue),
                "active_sends": self._active, "closed_to_new_records": self._closed,
                "worker_alive": self._thread.is_alive(), "last_error_type": self._last_error,
                "remote_readback": "not_performed", "delivery_scope": "http_acceptance_not_verified_remote_delivery",
                "retry_policy": "no_automatic_post_retry", "deduplication_scope": "bounded_process_local_recent_ids"}

    @staticmethod
    def _deadline(timeout_millis):
        if type(timeout_millis) not in (int, float) or not math.isfinite(timeout_millis) or not 0 <= timeout_millis <= 120000:
            raise ValueError("LIVE_SINK_DEADLINE_INVALID")
        return time.monotonic() + timeout_millis / 1000

    def _wait(self, deadline):
        with self._condition:
            while self._queue or self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
        result = self.stats()
        return {**result, "deadline_exhausted": result["pending"] > 0}

    def flush(self, *, timeout_millis=2000) -> dict:
        return self._wait(self._deadline(timeout_millis))

    def shutdown(self, *, timeout_millis=2000) -> dict:
        deadline = self._deadline(timeout_millis)
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._wait(deadline)
        self._thread.join(max(0, deadline - time.monotonic()))
        result = self.stats()
        return {**result, "deadline_exhausted": result["pending"] > 0 or result["worker_alive"]}
