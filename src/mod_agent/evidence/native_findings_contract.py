"""Explicit model-owned planning readiness, distinct from implementation acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

VERSION = "planning_readiness_v1"
RELATIONSHIPS = {"ready": "support", "needs_current_evidence": "missing", "conflicting_current_evidence": "conflict"}
BEHAVIOR_STATUSES = ["not_yet_implemented", "already_present", "not_assessed", "not_applicable"]
RULES = [
    "Return one native findings item for every listed relation_index. Judge planning_readiness from current source/API facts, "
    "then separately report requested_behavior_status. These are different questions. An implementation that still needs changes "
    "may have enough observed current facts to plan those changes. 为什么要有它：前置规划依据与后置功能实现须使用不同字段，不能把尚未实现直接映射为缺证。",
    "current_evidence_ids must cite only supplied source_observations. current_basis briefly states what those actual observations "
    "establish about the current code, insertion locations or APIs; an observed empty implementation is an existing fact, not proof "
    "of external API contracts. Never infer ready solely from a desired feature or a nonempty source list. 为什么要有它：可规划的判断必须由模型引用当前材料承担，宿主和材料数量都不能代替语义支持。",
    "Use planning_readiness=ready only when cited current facts suffice to plan this relation, with blocking_current_facts=[]. "
    "Use needs_current_evidence when a SPECIFIC current fact is still unknown, giving fact_needed and its planning_impact; partial "
    "current citations may be retained. Use conflicting_current_evidence only with citations and explain the unresolved current "
    "conflict in blocking_current_facts. Do not put future behavior absence or failed future acceptance in blocking_current_facts. "
    "为什么要有它：真正妨碍规划的当前知识缺口仍必须阻断，同时补查不能搜索尚待生成的实现作为前提。",
    "requested_behavior_status records only whether the desired behavior appears already implemented in the shown current source: "
    "not_yet_implemented, already_present, not_assessed, or not_applicable for a relation about current knowledge/preservation only. "
    "It does not grant correctness, test success or execution authority and does not determine planning_readiness. "
    "为什么要有它：声明待实现或看似已存在都不能绕过后续编译、行为验收及授权。",
    "edit_target_evidence_ids is an optional planning hint: only exact admitted target-source IDs, a subset of current_evidence_ids, "
    "for a ready relation with a change parent and no blocking_current_facts. Keep it empty otherwise. Reassess old gaps against "
    "new observations without changing either the user requirements or the evidence. 为什么要有它：改动位置提示不等于编辑权限，缺证与保留约束不能为推进流程而删除。",
]


def schema(*, relation_indexes, evidence_ids, edit_target_evidence_ids):
    ids = {"type": "array", "uniqueItems": True,
           "items": {"type": "string", **({"enum": list(evidence_ids)} if evidence_ids else {})},
           **({"maxItems": 0} if not evidence_ids else {})}
    editable = {"type": "array", "uniqueItems": True,
        "items": {"type": "string", **({"enum": list(edit_target_evidence_ids)} if edit_target_evidence_ids else {})},
        **({"maxItems": 0} if not edit_target_evidence_ids else {})}
    base = {"type": "object", "additionalProperties": False, "required": [
        "relation_index", "planning_readiness", "current_evidence_ids", "current_basis",
        "requested_behavior_status", "blocking_current_facts", "edit_target_evidence_ids"], "properties": {
        "relation_index": {"type": "integer", "enum": list(relation_indexes)},
        "planning_readiness": {"type": "string"}, "current_evidence_ids": ids,
        "current_basis": {"type": "string", "minLength": 1, "maxLength": 384},
        "requested_behavior_status": {"type": "string", "enum": BEHAVIOR_STATUSES},
        "blocking_current_facts": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["fact_needed", "planning_impact"],
            "properties": {key: {"type": "string", "minLength": 1, "maxLength": 256}
                           for key in ("fact_needed", "planning_impact")}}},
        "edit_target_evidence_ids": editable}}
    variants = []
    for readiness in RELATIONSHIPS:
        if readiness != "needs_current_evidence" and not evidence_ids:
            continue
        # 为什么要有它：每个native分支携带完整对象约束，避免oneOf同级字段被转换器丢弃。
        branch = deepcopy(base)
        fields = branch["properties"]
        fields["planning_readiness"]["const"] = readiness
        if readiness == "ready":
            fields["current_evidence_ids"]["minItems"] = 1
            fields["blocking_current_facts"]["maxItems"] = 0
        else:
            fields["blocking_current_facts"]["minItems"] = 1
            fields["edit_target_evidence_ids"]["maxItems"] = 0
            if readiness == "conflicting_current_evidence":
                fields["current_evidence_ids"]["minItems"] = 1
        variants.append(branch)
    return {"type": "object", "additionalProperties": False, "required": ["findings"], "properties": {
        "findings": {"type": "array", "minItems": len(relation_indexes), "maxItems": len(relation_indexes),
                     "items": {"oneOf": variants}}}}


def materialize(ordered_native):
    """Map the admitted model decision only; requested implementation status never grants support."""
    # 为什么要有它：输出模式变清楚不能变成宿主代判支持，现有coverage只接收模型已作出的当前规划判断。
    return {"findings": [{"relation_index": row["relation_index"],
        "relationship": RELATIONSHIPS[row["planning_readiness"]],
        "evidence_ids": deepcopy(row["current_evidence_ids"]),
        "edit_target_evidence_ids": deepcopy(row["edit_target_evidence_ids"]),
        "unresolved_gaps": ["Current fact needed: " + gap["fact_needed"] + "; Blocks planning: " + gap["planning_impact"]
                            for gap in row["blocking_current_facts"]]}
        for row in ordered_native["findings"]]}


def provenance(raw, materialized):
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode()).hexdigest()
    source = Path(__file__).resolve()
    return {"contract_version": VERSION, "native_response": deepcopy(raw), "native_response_sha256": digest(raw),
        "hash_basis": "canonical_json_utf8",
        "mapped_findings": deepcopy(materialized), "mapping_admitted": materialized is not None,
        "mapped_findings_sha256": digest(materialized), "readiness_mapping": deepcopy(RELATIONSHIPS),
        "semantic_origin": "model_current_planning_readiness_not_host_inferred_support",
        "requested_behavior_status_changes_coverage": False, "grants_execution_authority": False,
        "materializer_ref": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}}
