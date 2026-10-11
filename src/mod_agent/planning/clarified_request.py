"""Lossless clarified user input with task-start context, never execution authority."""
from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from pathlib import Path

VERSION = "clarified_product_request_v1"
ANCHORED_VERSION = "clarified_product_request_v2"
ANCHOR_PROTOCOL = "task-intent.v4-unit-anchors"
UNIT_ROLE_PROTOCOL = "task-intent.v5-unit-roles"
START_FIELDS = ("action", "target_id", "project_name")
CONTRACT = (
    "原需求中未被用户修改的约束保留；后续用户纠正优先。"
    "助手澄清问题仅为上下文，不自行增加需求或授权。"
    "execution_start记录本次已选任务起点，不是待实现的Mod功能，也不授予执行权限。"
    "conversation_turns保留全部原文；已撤销的备选不能变成新工程要求。"
    "为什么要有它：保留完整会话证据，同时区分任务入口上下文与待实现行为。"
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def user_units(turns):
    """Host-owned exact UTF-8 identities and Python character ranges; models select IDs only."""
    rows = []
    for turn_index, turn in enumerate(turns):
        if turn["role"] not in {"original_user_request", "user_answer_or_correction"}:
            continue
        text = turn["content"]
        # 为什么要有它：固定标点边界让模型无需计算中文offset；不含边界的混合句仍为不可剥离的完整单元。
        ends = [match.end() for match in re.finditer(r"(?:[。！？!?；;，,\n]+|\.(?=\s|$))[ \t]*", text)]
        if not ends or ends[-1] != len(text):
            ends.append(len(text))
        spans, start = [], 0
        for end in ends:
            if not text[start:end].strip() and spans:
                spans[-1] = (spans[-1][0], end)
            elif end > start:
                spans.append((start, end))
            start = end
        for unit_index, (start, end) in enumerate(spans):
            row = {"turn_index": turn_index, "start": start, "end": end, "text": text[start:end]}
            row["unit_id"] = f"u{turn_index}_{unit_index}_" + _digest(row)[:10]
            rows.append(row)
    return rows


def validate_start_anchors(anchors, units, decision):
    if not isinstance(anchors, list) or len(anchors) > len(units):
        raise ValueError("CLARIFIED_START_ANCHORS_INVALID")
    by_id, seen = {row["unit_id"]: row for row in units}, set()
    for anchor in anchors:
        if (not isinstance(anchor, dict) or set(anchor) != {"unit_id", "execution_start_field", "resolved_by_unit_id"}
                or anchor.get("unit_id") not in by_id or anchor["unit_id"] in seen
                or anchor.get("execution_start_field") not in START_FIELDS
                or not isinstance(anchor.get("resolved_by_unit_id"), str)):
            raise ValueError("CLARIFIED_START_ANCHORS_INVALID")
        field = anchor["execution_start_field"]
        if decision["action"] in {"new_project", "modify_project"} and not decision[field]:
            raise ValueError("CLARIFIED_START_ANCHOR_EMPTY_FIELD")
        correction = anchor["resolved_by_unit_id"]
        if correction and (correction not in by_id or by_id[correction]["turn_index"] <= by_id[anchor["unit_id"]]["turn_index"]):
            raise ValueError("CLARIFIED_START_CORRECTION_NOT_LATER_USER")
        seen.add(anchor["unit_id"])
    by_anchor = {anchor["unit_id"]: anchor for anchor in anchors}
    for anchor in anchors:
        correction = anchor["resolved_by_unit_id"]
        if correction and (correction not in by_anchor
                or by_anchor[correction]["execution_start_field"] != anchor["execution_start_field"]):
            raise ValueError("CLARIFIED_START_CORRECTION_NOT_BOUND_TO_SAME_FIELD")
    if decision["action"] in {"new_project", "modify_project"} and units and len(seen) == len(units):
        raise ValueError("CLARIFIED_START_ALL_USER_INPUT_CONTEXT")
    return deepcopy(anchors)


def validate_unit_roles(roles, units, decision):
    """Normalize exact unit coverage without inventing model-proven correction edges."""
    if not isinstance(roles, dict) or set(roles) != {row["unit_id"] for row in units}:
        raise ValueError("CLARIFIED_UNIT_ROLES_IDENTITY_INVALID")
    allowed = {"new_project": {"keep", "action", "project_name"},
               "modify_project": {"keep", "action", "target_id"}}.get(decision["action"], {"keep"})
    if any(not isinstance(role, str) or role not in allowed for role in roles.values()):
        raise ValueError("CLARIFIED_UNIT_ROLES_ACTION_INVALID")
    if not any(role == "keep" for role in roles.values()):
        raise ValueError("CLARIFIED_UNIT_ROLES_ALL_CONTEXT")
    if any(role != "keep" and not decision[role] for role in roles.values()):
        raise ValueError("CLARIFIED_UNIT_ROLES_EMPTY_FIELD")
    # 为什么要有它：固定map避免重复unit和机械resolver边；完整用户时间顺序保留，但不宣称逐条纠正关联已被证明。
    return [{"unit_id": row["unit_id"], "execution_start_field": roles[row["unit_id"]], "resolved_by_unit_id": ""}
            for row in units if roles[row["unit_id"]] != "keep"]


def product_description(turns, decision, *, routing_binding=None):
    if len(turns) == 1:
        return turns[0]["content"]
    # 为什么要有它：完整转录需要保留发言身份及已选起点，不能把agent任务控制误投影成Mod逻辑。
    value = {"schema_version": VERSION, "interpretation_contract": CONTRACT,
        "execution_start": {key: decision[key] for key in ("action", "target_id", "project_name")},
        "conversation_turns": turns}
    if routing_binding is not None:
        value.update(schema_version=ANCHORED_VERSION, routing_binding=deepcopy(routing_binding))
    request = json.dumps(value, ensure_ascii=False, indent=2)
    projection_context(request)
    return request


def projection_context(request):
    """Read an exact representation; unrecognized literal requests retain old behavior."""
    try:
        value = json.loads(request)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") not in {VERSION, ANCHORED_VERSION}:
        return None
    expected_fields = {"schema_version", "interpretation_contract", "execution_start", "conversation_turns"}
    if value["schema_version"] == ANCHORED_VERSION:
        expected_fields.add("routing_binding")
    if set(value) != expected_fields:
        raise ValueError("CLARIFIED_PRODUCT_REQUEST_FIELDS_INVALID")
    if value["interpretation_contract"] != CONTRACT:
        raise ValueError("CLARIFIED_PRODUCT_REQUEST_CONTRACT_INVALID")
    selected = value["execution_start"]
    if (not isinstance(selected, dict) or set(selected) != {"action", "target_id", "project_name"}
            or any(not isinstance(item, str) for item in selected.values())
            or selected["action"] not in {"new_project", "modify_project"}
            or (selected["action"] == "new_project" and (selected["target_id"] or not selected["project_name"].strip()))
            or (selected["action"] == "modify_project" and (not selected["target_id"] or selected["project_name"]))):
        raise ValueError("CLARIFIED_PRODUCT_REQUEST_START_INVALID")
    turns = value["conversation_turns"]
    if not isinstance(turns, list) or len(turns) < 3 or len(turns) % 2 != 1:
        raise ValueError("CLARIFIED_PRODUCT_REQUEST_TURNS_INVALID")
    for index, turn in enumerate(turns):
        expected = ("original_user_request" if index == 0 else
                    "assistant_clarification_context" if index % 2 else "user_answer_or_correction")
        if (not isinstance(turn, dict) or set(turn) != {"role", "content"}
                or turn["role"] != expected or not isinstance(turn["content"], str) or not turn["content"].strip()):
            raise ValueError("CLARIFIED_PRODUCT_REQUEST_TURNS_INVALID")
    context = {**deepcopy(value), "authority": "interpretation_context_only",
               "current_user_message": turns[-1]["content"]}
    if value["schema_version"] == ANCHORED_VERSION:
        context["user_units"], context["eligible_context_anchors"] = _bound_units(value)
    return context


def _bound_units(value):
    binding = value["routing_binding"]
    if not isinstance(binding, dict) or set(binding) != {"conversation_id", "turn_id", "request_ref", "selection_ref"}:
        raise ValueError("CLARIFIED_ROUTING_BINDING_INVALID")
    documents = {}
    parents = []
    for kind, filename in (("request", "request.json"), ("selection", "selection.json")):
        ref = binding[kind + "_ref"]
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or not isinstance(ref["path"], str):
            raise ValueError("CLARIFIED_ROUTING_REFERENCE_INVALID")
        path = Path(ref["path"])
        if (not path.is_absolute() or path.name != filename or path.parent.parent.name != ".dsh-routing"
                or not path.parent.name.startswith("route_")):
            raise ValueError("CLARIFIED_ROUTING_REFERENCE_LOCATION_INVALID")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("CLARIFIED_ROUTING_REFERENCE_CHANGED")
        documents[kind] = json.loads(raw)
        parents.append(path.parent.resolve())
    request, selection = documents["request"], documents["selection"]
    if (parents[0] != parents[1] or not binding["conversation_id"] or not binding["turn_id"]
            or request.get("preview_only") is not False or not request.get("clarification_for")
            or request.get("conversation_id") != binding["conversation_id"]
            or request.get("turn_id") != binding["turn_id"]
            or request.get("conversation_turns") != value["conversation_turns"]
            or request.get("description") != value["conversation_turns"][-1]["content"]
            or request.get("bindings") != selection.get("bindings")
            or {key: selection.get("decision", {}).get(key) for key in START_FIELDS} != value["execution_start"]):
        raise ValueError("CLARIFIED_ROUTING_IDENTITY_CHANGED")
    provenance = selection.get("intent_provenance", {})
    units = user_units(value["conversation_turns"])
    if (provenance.get("protocol") not in {ANCHOR_PROTOCOL, UNIT_ROLE_PROTOCOL} or provenance.get("source_units_sha256") != _digest(units)
            or provenance.get("source_units") != units):
        raise ValueError("CLARIFIED_ROUTING_UNIT_BINDING_CHANGED")
    if provenance["protocol"] == UNIT_ROLE_PROTOCOL:
        anchors = validate_unit_roles(provenance.get("unit_roles"), units, value["execution_start"])
        if (provenance.get("unit_roles") != provenance.get("native_unit_roles")
                or provenance.get("execution_start_anchors") != anchors
                or provenance.get("anchor_origin") != "host_normalized_unit_roles_without_correction_edges"):
            raise ValueError("CLARIFIED_UNIT_ROLES_PROVENANCE_CHANGED")
    else:
        anchors = validate_start_anchors(provenance.get("execution_start_anchors"), units, value["execution_start"])
    return units, anchors


def source_hint_text(request):
    """Only literal user turns contribute lexical code hints; the caller keeps the full request identity."""
    context = projection_context(request)
    if context is None:
        return request
    # 为什么要有它：转录结构键和助手候选不是用户源码线索，用户原文中的同名标识符仍完整保留。
    return "\n".join(turn["content"] for turn in context["conversation_turns"]
                     if turn["role"] in {"original_user_request", "user_answer_or_correction"})


def model_context(context):
    """Local reference paths prove eligibility to the host; they are not model business text."""
    return {key: deepcopy(value) for key, value in context.items() if key != "routing_binding"}


def scoped_projection_view(payload, request, context):
    if context is None or context["schema_version"] != ANCHORED_VERSION:
        return payload
    view = model_context(context)
    text = json.dumps(view, ensure_ascii=False, sort_keys=True)
    # 为什么要有它：原件和SHA仍绑定完整输入，模型只需原文单元及有限起点，不应把本地receipt路径当业务要求。
    def rewrite(value):
        if isinstance(value, str):
            return value.replace(request, text)
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        return value
    result = rewrite(payload)
    result["literal_request_sha256"] = hashlib.sha256(request.encode("utf-8")).hexdigest()
    return result


PROJECTION_RULES = [
    "The clarified_request_context separates this agent's execution starting point from the requested Mod behavior. "
    "The selected new/modify action and target are task-start context, not functions to add to the Mod. "
    "Account for the actual requested Mod behavior and still-effective constraints using the existing input indexes. "
    "Do not invent a Mod task scheduler, continuation guard, cancellation feature or state-management implementation "
    "from instructions about starting, continuing, replacing or abandoning THIS agent task. "
    "为什么要有它：执行起点选择已经由入口处理，不能要求目标代码实现开发会话的控制命令。",
    "Read all original user turns and later corrections. Preserve unchanged user requirements; exclude explicitly "
    "withdrawn alternatives from current implementation requirements. Assistant questions and catalogue options "
    "are context, not user requirements. Do not discard the positive behavior in a mixed instruction. "
    "为什么要有它：澄清的作用是消除选择歧义，既不能丢原功能，也不能保留已撤销备选为当前义务。",
    "If the user actually requests scheduling, cancellation, task state or resume behavior INSIDE the Mod or target "
    "application, that remains a real product requirement. Distinguish the referent and requested effect, not words "
    "alone. Do not use a blanket keyword exclusion or mark an entire mixed user_request obligation out of scope. "
    "Do not add input dispositions not allowed by the existing per-index schema. "
    "为什么要有它：真正的Mod任务控制功能仍需实现，表示改进不能删需求或放宽证据覆盖门禁。",
]

ANCHORED_PROJECTION_RULES = [
    "For clarified_product_request_v2, input obligations identify exact host-generated USER source units; "
    "the whole transcript is not a second product requirement. eligible_context_anchors binds the only units "
    "that the routing selection classified as task-start context. For each of these units, either explicitly "
    "use its allowed scope_boundary disposition when the complete unit concerns this agent's chosen start, "
    "or retain it in product requirements if it also contains product behavior. Do not produce source queries "
    "or preservation requirements merely to prove the selected agent action/name/target. "
    "为什么要有它：同一原文范围须同时经过路由与投影确认，任务上下文不需要Mod源码来证明。",
    "Every unanchored USER unit remains mandatory product input and cannot receive scope_boundary. "
    "A mixed task-start/product unit and real task scheduling/cancellation/resume INSIDE the Mod must remain "
    "covered by product requirements. Never extend an anchor to neighboring text or treat the entire "
    "conversation as context. Preserve all still-effective constraints and later user corrections. "
    "为什么要有它：没有起点原文绑定的内容不得被豁免，特别是混合句和Mod内部任务控制需求。",
]
