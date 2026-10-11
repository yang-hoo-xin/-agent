"""Six evidence questions over one retained Patch attempt; never an executor.

References are resolved only through the caller's existing checked-reference reader.
Neither this projection nor a complete set of tool results establishes semantic recall.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.mod_agent.local_entry import LocalEntryError, _restore_patch_agent_context


def _object(value):
    return value if isinstance(value, Mapping) else {}


def _rows(value):
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _fields(value, *names):
    return {name: value[name] for name in names if name in value
            and isinstance(value[name], (str, int, float, bool, type(None)))}


def _stage(stage_id, title, status, conclusion, method, refs, observations, unknowns, next_step):
    return {"stage_id": stage_id, "title": title, "status": status,
            "conclusion": conclusion, "method": method, "evidence_refs": refs,
            "observations": observations, "unknowns": unknowns, "next_verification": next_step}


def _message(value):
    content = value.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return {}
    return _object(content)


def _verified_requests(attempt, check_reference):
    requests = []
    for turn in _rows(attempt.get("worker_turns")):
        if turn.get("normalized_request_identity") != "matched":
            continue
        checked, document = check_reference(turn.get("request_ref"))
        if checked.get("integrity") != "verified_bytes":
            continue
        contexts = []
        for message in _rows(document.get("messages")):
            payload = _message(message)
            if "edit_binding_contexts" not in payload:
                continue
            try:
                contexts.append(_restore_patch_agent_context(payload))
            except (LocalEntryError, ValueError, TypeError):
                continue
        requests.append((turn, checked, document, contexts))
    return requests


def _materials(selected, check_reference):
    documents, refs = {}, {}
    for name in ("evidence_pack", "implementation_plan", "feature_spec"):
        if name not in selected:
            refs[name] = {"integrity": "unverifiable_reference"}
            documents[name] = {}
            continue
        checked, document = check_reference(selected[name])
        refs[name] = checked
        documents[name] = (_object(document.get("data"))
                           if checked.get("integrity") == "verified_artifact" else {})
    items = _rows(documents["evidence_pack"].get("items"))
    sources = []
    for item in items:
        row = _fields(item, "evidence_id", "source_type", "source_path", "source_ref", "source_hash")
        row["retained_excerpt"] = isinstance(item.get("excerpt"), str) and bool(item["excerpt"])
        if item.get("source_type") == "target_source":
            raw_path = item.get("source_ref")
            if isinstance(raw_path, str) and "://" not in raw_path:
                row["current_source_ref"] = check_reference({
                    "path": raw_path, "sha256": item.get("source_hash")})[0]
            else:
                row["current_source_ref"] = {"integrity": "unverifiable_reference"}
        else:
            # Registered API evidence may use a source:// identity, not a file path.
            row["current_source_ref"] = None
        sources.append(row)
    source_counts = dict(Counter(_object(row["current_source_ref"]).get("integrity")
                                for row in sources if row["current_source_ref"] is not None))
    problems = any(ref.get("integrity") != "verified_artifact" for ref in refs.values())
    problems = problems or any(key != "verified_bytes" for key in source_counts)
    stage = _stage("material_availability", "材料存在与可取得", "references_need_attention" if problems
                   else "bound_materials_retained", "已核验选定材料及其明确绑定的本地源码；缺失引用不等于整个材料不存在。",
                   "复用 Artifact/字节哈希核验；仅跟随选定 Evidence 的 target_source.source_ref，保留原始哈希，不搜索其他路径。",
                   list(refs.values()), {"selected_artifacts": refs, "evidence_item_count": len(items),
                   "sources": sources, "current_source_integrity_counts": source_counts},
                   ["未绑定或未检索材料是否存在未知。", "本次源码读取核验与历史运行时可用性分别记录；API 留存片段不证明当前依赖行为。"],
                   "若需补材料，先列明缺少的事实及其准确来源；修复缺失引用前保留原始运行身份。")
    return stage, documents, refs


def _plan_recall(journal, documents, refs, requests):
    plan = documents["implementation_plan"]
    registry = _object(plan.get("binding_registry"))
    items_by_id = {}
    for item in _rows(documents["evidence_pack"].get("items")):
        if isinstance(item.get("evidence_id"), str):
            items_by_id.setdefault(item["evidence_id"], []).append(item)
    bindings = []
    for kind, field in (("edit", "edit_bindings"), ("supporting", "supporting_bindings")):
        for binding in _rows(registry.get(field)):
            matches = items_by_id.get(binding.get("evidence_id"), [])
            evidence = matches[0] if len(matches) == 1 else {}
            row = {"kind": kind, **_fields(binding, "binding_id", "evidence_id", "source_type",
                   "canonical_target_path", "source_path", "target_symbol", "source_hash")}
            row["target_span"] = _fields(_object(binding.get("target_span")), "start_line", "end_line")
            field_pairs = (("canonical_target_path" if kind == "edit" else "source_path", "source_path"),
                           ("source_type", "source_type"), ("target_span", "span"), ("target_symbol", "symbol"))
            row["evidence_match"] = ("exact_identity_fields_match" if len(matches) == 1
                and all(binding.get(left) == evidence.get(right) for left, right in field_pairs)
                else "identity_fields_mismatch" if len(matches) == 1 else "unknown_or_ambiguous")
            row["evidence_source_hash"] = evidence.get("source_hash")
            row["source_hash_binding"] = (
                "unverified_evidence_identity" if row["evidence_match"] != "exact_identity_fields_match" else
                "missing_in_plan_resolved_from_evidence" if binding.get("source_hash") is None
                and isinstance(evidence.get("source_hash"), str) else "missing" if binding.get("source_hash") is None
                else "mismatch" if isinstance(evidence.get("source_hash"), str)
                and binding["source_hash"] != evidence["source_hash"] else "matched" if evidence
                and binding.get("source_hash") == evidence.get("source_hash") else "plan_hash_only")
            bindings.append(row)
    scope = []
    for turn, checked, request, contexts in requests:
        readable = []
        for tool in _rows(request.get("tools")):
            if tool.get("name") == "inspect_plan_binding_source":
                readable.extend(_strings(_object(_object(_object(tool.get("parameters")).get(
                    "properties")).get("binding_id")).get("enum")))
        for context in contexts:
            schema = _object(context.get("required_output_schema"))
            changes = _object(_object(schema.get("properties")).get("changes"))
            item_schema = _object(changes.get("items"))
            units = _rows(context.get("required_change_units"))
            scope.append({**_fields(turn, "segment_index", "turn_index"), "request_ref": checked,
                "allowed_edit_binding_ids": _strings(context.get("allowed_edit_binding_ids")),
                "edit_context_binding_ids": list(_object(context.get("edit_binding_contexts"))),
                "supporting_context_binding_ids": [item.get("binding_id") for item in _rows(context.get("supporting_evidence"))],
                "tool_readable_binding_ids": readable, "tool_readable_binding_count": len(readable),
                "required_change_unit_count": len(units),
                "required_change_units": [{**_fields(unit, "change_id", "edit_binding_id", "operation", "change_type"),
                    "supporting_binding_ids": _strings(unit.get("supporting_binding_ids"))} for unit in units],
                "output_changes_constraint": {**_fields(changes, "type", "minItems", "maxItems"),
                    "item_required_fields": _strings(item_schema.get("required")),
                    "edit_binding_id_enum": _strings(_object(_object(item_schema.get("properties")).get("edit_binding_id")).get("enum"))}})
    latest = _object(_object(journal.get("latest_observations")).get("implementation_plan"))
    return _stage("necessary_fact_recall", "必要事实召回与固定 Plan 范围", "unknown_necessary_fact_coverage",
        "固定 Plan 的绑定、实际可读范围和输出项约束可核验；必要事实是否齐全、每个必改项是否必要仍未知。",
        "逐项读取选定 Plan 与已核验实际请求；复用输入表展开；依据实际工具 binding_id.enum 统计读取范围。",
        [refs["implementation_plan"], refs["evidence_pack"], *[row[1] for row in requests]],
        {"continuation_selection": journal.get("continuation_selection"),
         "selected_is_latest": latest.get("selected_is_latest"),
         "latest_selection_scope": "explicit_historical_selection_is_not_source_drift",
         "edit_binding_count": sum(row["kind"] == "edit" for row in bindings),
         "supporting_binding_count": sum(row["kind"] == "supporting" for row in bindings),
         "bindings": bindings, "request_scopes": scope,
         "necessary_fact_denominator": None, "necessary_fact_recall": None},
        ["缺少与本次需求和证据绑定的评测事实清单，不能计算必要事实召回率。",
         "完整工具返回、固定 Plan 内覆盖率和语义证据充分性是不同问题。",
         "必交变更项的数量可核验，其必要性和超时因果不能从数量推出。"],
        "显式提供本次需求的必要事实清单、每项支持/反证来源及验收规则；再逐项核对现有 Plan 和请求。")


def _delivery(attempt, requests):
    linked = {(turn.get("segment_index"), link.get("observation_id"), link.get("observation_sha256"))
              for turn, _, _, _ in requests for link in _rows(turn.get("observation_request_links"))
              if link.get("binding_status") == "matched"}
    observations = []
    for tool in _rows(attempt.get("tool_execution")):
        for observation in _rows(tool.get("returned_observations")):
            identity = (tool.get("segment_index"), observation.get("observation_id"), observation.get("observation_sha256"))
            observations.append({**_fields(tool, "segment_index", "phase", "turn_index", "binding_id", "tool_call_id"),
                **_fields(observation, "observation_id", "observation_sha256", "admitted_to_model", "consumed_in_model_turn"),
                "request_binding": "matched_retained_request" if identity in linked else
                "not_found_in_verified_retained_requests" if requests else "unknown_no_verified_request"})
    unmatched = sum(row["request_binding"] != "matched_retained_request" for row in observations)
    status = ("partial_or_unknown_delivery" if unmatched or not requests else
              "retained_request_links_verified" if observations else "no_source_observation_record")
    return _stage("request_delivery", "工具结果进入实际请求", status,
        "分别核验工具结果、留存请求和后续响应；请求中含有材料不等于模型理解或结论正确。",
        "复用原请求规范哈希、工具载荷哈希及源码引用展开核验，不以 admitted_to_model 声明代替实际请求内容。",
        [row[1] for row in requests], {"verified_request_count": len(requests),
        "source_observations": observations, "observations_without_matched_request_count": unmatched,
        "request_links": [{**_fields(turn, "segment_index", "turn_index"), "request_ref": checked,
            "response_after_request_observed": turn.get("response_after_request_observed"),
            "observation_request_links": turn.get("observation_request_links", []),
            "failure_feedback_links": turn.get("failure_feedback_links", [])} for turn, checked, _, _ in requests]},
        ["缺少响应不证明请求未发出；未找到匹配请求也不证明历史上从未传递。", "材料进入请求不证明模型正确使用了材料。"],
        "对未匹配结果检查该次调用的准确请求引用和载荷身份，再以需求断言或行为验证判断模型是否正确使用。")


def _alignment(journal, refs, requests):
    factory = _object(journal.get("factory_receipt"))
    loop = _object(factory.get("patch_agent_loop"))
    updates = [{**_fields(row, "turn_index", "tool_call_id", "status", "error_code", "feedback_queued")}
               for row in _rows(loop.get("investigation_trace"))]
    return _stage("judgment_alignment", "判断与需求及证据一致性", "unknown_semantic_alignment",
        "当前仅能定位模型公开调查动作及反馈身份；未建立其判断符合需求和证据的语义结论。",
        "公开 investigation_trace 是动作记录；需求、事实和生成结果必须由显式断言及绑定验证结果共同核对。",
        [refs["feature_spec"], refs["evidence_pack"], *[row[1] for row in requests]],
        {"investigation_updates": updates, "explicit_alignment_assessment": "not_supplied",
         "model_understanding": "not_established"},
        ["被接受的调查更新也不构成正确理解的证明。", "输出变更理由或重复已见符号不能替代需求一致性评测。"],
        "提供面向本次需求的明确一致性/冲突断言，绑定源码、需求、模型结果和反例；由相应检查核验。")


def _verification(journal, attempt, check_reference):
    evaluations = []
    for evaluation in _rows(attempt.get("behavior_evaluations")):
        checked, report = check_reference(evaluation.get("report_ref"))
        same_changes = evaluation.get("generated_changes_report_link") == "matching_explicit_identity"
        status_matches = isinstance(report.get("status"), str) and report["status"] == evaluation.get("status")
        bound = checked.get("integrity") == "verified_bytes" and same_changes and status_matches
        origin = evaluation.get("execution_observation")
        verdict = "executed_bound_report" if bound and origin == "executed" else (
            "reused_bound_report" if bound and origin == "reused" else "unknown_execution_or_report_binding")
        evaluations.append({**_fields(evaluation, "segment_index", "evaluation_index", "status", "generated_changes_sha256", "execution_observation"),
            "report_ref": checked, "result_binding": verdict,
            "verification_summary": evaluation.get("verification_summary"),
            "checks": evaluation.get("checks", []), "code_response_link": evaluation.get("code_response_link")})
    repair = _object(journal.get("repair_context"))
    prior = check_reference(repair["failure_report_ref"])[0] if "failure_report_ref" in repair else None
    stage_status = "current_verification_reported" if evaluations else "no_current_verification_record"
    return _stage("code_verification", "代码与验证结果", stage_status,
        "区分当前代码验证、复用结果与历史失败反馈；缺少当前验证记录不算通过或行为失败。",
        "复用原执行来源判定，并交叉核对报告字节、报告状态和 generated_changes_sha256；不运行验证器。",
        [row["report_ref"] for row in evaluations] + ([prior] if prior else []),
        {"current_evaluations": evaluations, "current_evaluation_count": len(evaluations),
         "prior_failure_report_ref": prior, "prior_failure_scope": "historical_input_not_current_attempt_execution",
         "proposal_admitted": journal.get("proposal_admitted"),
         "formal_downstream": _object(attempt.get("failure_summary")).get("formal_downstream", {})},
        ["报告存在不证明本次执行；旧失败报告不能转记成本次代码验证。", "本地检查不替代适用的正式 Build 或游戏 Runtime。"],
        "若已有完整新代码，先核验其精确身份和对应报告；若未生成代码，先处理当前首个执行失败，再决定下一次验证。")


def _reliability(journal, attempt, requests):
    factory = _object(journal.get("factory_receipt"))
    observations = _object(journal.get("execution_observations"))
    turns = []
    verified = {(turn.get("segment_index"), turn.get("turn_index"), checked.get("path")): checked
                for turn, checked, _, _ in requests}
    segments = _rows(journal.get("patch_execution_segments"))
    source_turns = [{"segment_index": segment.get("segment_index"), **turn}
                    for segment in segments for turn in _rows(_object(segment.get("factory_receipt")).get("worker_turns"))]
    if not segments:
        source_turns = _rows(factory.get("worker_turns"))
    for raw_turn in source_turns:
        raw_path = _object(raw_turn.get("request_ref")).get("path")
        key = (raw_turn.get("segment_index"), raw_turn.get("turn_index"), raw_path)
        checked = verified.get(key, {})
        projected = [row for row in _rows(attempt.get("worker_turns"))
                     if (row.get("segment_index"), row.get("turn_index"),
                         _object(row.get("request_ref")).get("path")) == key]
        turn = projected[0] if len(projected) == 1 else {}
        observation = _object(observations.get(raw_turn.get("model_request_observation_id")))
        attributes = _object(observation.get("attributes"))
        bound = bool(checked) and attributes.get("request_sha256") == raw_turn.get("request_sha256")
        error = raw_turn.get("error")
        timeout = isinstance(error, str) and "timed out" in error
        sent = attributes.get("transport_started") if bound else None
        responded = turn.get("response_after_request_observed")
        turns.append({**_fields(raw_turn, "segment_index", "turn_index", "status", "error_type"),
            "request_ref": checked or turn.get("request_ref"),
            "native_observation_id": observation.get("id"), "native_request_identity_matched": bound,
            "transport_started": sent, "response_after_request_observed": responded,
            "recorded_timeout": timeout, "elapsed_ms": observation.get("elapsed_ms") if bound else None,
            "boundary": "timeout_after_transport_started" if timeout and sent is True else
            "timeout_send_unconfirmed" if timeout else "response_retained" if responded else
            "transport_started_without_retained_response" if sent is True else "unknown_send_or_response"})
    counts = dict(Counter(row["boundary"] for row in turns))
    return _stage("execution_reliability", "运行、存储与超时", "execution_failure_recorded" if any(row["recorded_timeout"] for row in turns)
        else "execution_observations_projected", "运行失败、引用保存问题与语义失败分别报告；超时无响应不能改写成输入未发送。",
        "按 model_request_observation_id 与精确 request_sha256 关联原生记录；超时取自原记录明确的 timed out 文本，非耗时推断。",
        [attempt.get("journal_ref", {})], {"turns": turns, "boundary_counts": counts,
            "journal_call_count": journal.get("model_call_count"),
            "reference_integrity_counts": attempt.get("reference_integrity_counts", {}),
            "storage_scope": "current_bound_reference_integrity_not_durable_storage_reliability",
            "stopped_at": _object(attempt.get("failure_summary")).get("stopped_at", {})},
        ["transport_started 是原生观测标记，不是独立网络抓包。", "留存引用通过不证明长期保存、恢复或远程传输可靠性。",
         "超时记录不能独立区分模型、服务端计算、网络或客户端的根因。"],
        "针对首个已记录运行失败做精确请求离线诊断，保留输入哈希和超时证据；新的模型尝试仍遵守原授权边界。")


def build_investigation_chain(journal: Mapping[str, Any], attempt: Mapping[str, Any], check_reference) -> dict[str, Any]:
    """Build the six-stage read-only view from the selected journal and checked refs."""
    material, documents, refs = _materials(_object(journal.get("selected_artifacts")), check_reference)
    requests = _verified_requests(attempt, check_reference)
    return {"schema_version": "patch_investigation_chain_v1", "authority": "non_authoritative",
        "stages": [material, _plan_recall(journal, documents, refs, requests),
                   _delivery(attempt, requests), _alignment(journal, refs, requests),
                   _verification(journal, attempt, check_reference), _reliability(journal, attempt, requests)],
        "limitations": ["只读再生视图；不写 Artifact、不调用模型、不执行验证或授予权限。",
                        "没有明确评测事实与一致性断言时，必要材料完整性和模型正确理解保持未知。"]}
