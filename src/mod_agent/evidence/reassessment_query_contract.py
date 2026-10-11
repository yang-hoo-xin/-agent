"""Shared Evidence query contracts for initial gaps and admitted Patch investigation.

为什么要有它：两种调查共用一个 schema 实现，但缺口语义不同，执行范围和预算仍由原调用方管理。
"""
from __future__ import annotations

from copy import deepcopy

from .reassessment import gap_investigation_targets


def query_tool_capabilities(*, upstream_search_root, source_provider=None, augmentation=None):
    from src.mod_agent.evidence.indexed_source import IndexedSourceEvidenceProvider
    from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
    source = {"search_root": str(upstream_search_root), "input_field": "query"}
    if source_provider is None or isinstance(source_provider, RgLiveEvidenceProvider):
        source.update(tool="rg_live", file_glob="*.cs",
            matching="case-insensitive OR of up to 12 extracted distinct non-stopword tokens; literal tokens, not question answering",
            output="bounded current source windows with path/hash/span; an explicit C# filename must resolve uniquely")
    elif isinstance(source_provider, IndexedSourceEvidenceProvider):
        source.update(tool="symbol_bm25", file_glob="*.cs",
            matching="exact symbol and BM25 retrieval over the bound current source index",
            output="bounded current source windows, checked against current file hashes")
    else:
        source.update(tool="configured_source_provider", matching="not_declared")
    dependency = getattr(augmentation, "query_capabilities", None)
    return {"target_source": source,
            "dependency_api": deepcopy(dependency) if dependency is not None else {
                "available": False, "status": "not_configured" if augmentation is None else "not_declared"}}


def _query_source_observation_view(item):
    """Keep query-relevant source bytes and identities without declaration-table duplication."""
    value = item.to_dict()
    return {key: deepcopy(value.get(key)) for key in (
        "evidence_id", "source_type", "source_path", "symbol", "excerpt")
        if value.get(key) is not None}


def build_reassessment_query_contract(*, feature, projection, old, feedback,
        upstream_search_root, upstream_query_limit=3,
        contract_version="requirement_queries_v3", tool_capabilities=None):
    """Build the one bounded query payload/schema shared by preview and execution."""
    from src.mod_agent.evidence.reassessment import dependency_source_diversification_required

    requirement_ids = [item["requirement_id"] for item in projection["requirements"]]
    gap_targets = gap_investigation_targets(projection, old)
    gap_ids = [row["gap_id"] for row in gap_targets]
    initial = "initial_findings_reassessment" in feedback
    allow_gapless_patch_query = not initial and contract_version in {"requirement_queries_v2", "requirement_queries_v3"}
    prior_reassessment = old.budget_summary.get("reassessment")
    prior_query_outcomes = None
    if isinstance(prior_reassessment, dict):
        prior_query_outcomes = {
            "queries": [{key: deepcopy(row.get(key)) for key in (
                "query", "metadata_queries", "authorized_source") if key in row}
                for row in prior_reassessment.get("queries", ())],
            "executions": [{key: deepcopy(row.get(key)) for key in (
                "query_sha256", "retrieval_status") if key in row}
                for row in prior_reassessment.get("per_query_execution", ())],
            "new_evidence_ids": deepcopy(prior_reassessment.get("new_evidence_ids", [])),
        }
    source_diversification = (dependency_source_diversification_required(old))
    dependency_requirement_ids = [row["requirement_id"] for row in projection["requirements"]
        if row["role"] == "pre_patch_evidence"
        and ("API" in str(row.get("text", ""))
             or any("API" in str(value) for value in row.get("query_leads", [])))]
    schema = {
        "type": "object", "additionalProperties": False, "required": ["queries"],
        "properties": {"queries": {
            "type": "array", "maxItems": upstream_query_limit,
            "items": {"type": "object", "additionalProperties": False,
                "required": ["query", "requirement_id", "gap_ids", "current_fact_needed",
                             "modification_impact", "authorized_source", "metadata_queries"], "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "requirement_id": {"type": "string", "enum": requirement_ids},
                    "gap_ids": {"type": "array", "minItems": 0 if allow_gapless_patch_query else 1, "uniqueItems": True,
                        "items": {"type": "string", "enum": gap_ids}},
                    "current_fact_needed": {"type": "string", "minLength": 1},
                    "modification_impact": {"type": "string", "minLength": 1},
                    "authorized_source": {"type": "string",
                        "enum": ["target_source", "dependency_api"]},
                    "metadata_queries": {"type": "array", "maxItems": 3,
                        "items": {"type": "string", "minLength": 1}},
                }},
        }},
    }
    if contract_version not in {"requirement_queries_v1", "requirement_queries_v2", "requirement_queries_v3"}:
        raise ValueError("PATCH_REASSESSMENT_QUERY_CONTRACT_VERSION_INVALID")
    if contract_version == "requirement_queries_v3":
        # 为什么要有它：原生生成域应表达工具前已有的字符与长度限制，避免生成合法JSON却在补查前必然被拒；旧wire不变。
        properties = schema["properties"]["queries"]["items"]["properties"]
        for field in ("query", "current_fact_needed", "modification_impact"):
            properties[field]["maxLength"] = 256
        properties["metadata_queries"]["items"].update(maxLength=128, pattern=r"^[^\s?]{1,128}$")
    if contract_version in {"requirement_queries_v2", "requirement_queries_v3"}:
        from src.mod_agent.evidence.reassessment import gap_requirement_bindings
        bindings = gap_requirement_bindings(projection, old)
        variants = []
        for requirement_id in requirement_ids:
            allowed = [gap for gap, parents in bindings.items() if requirement_id in parents]
            if allowed or allow_gapless_patch_query:
                # 为什么要有它：当前 native 后端会丢弃 oneOf 的同级约束，分支须各自携带完整对象约束。
                variant = deepcopy(schema["properties"]["queries"]["items"])
                variant["properties"]["requirement_id"] = {"type": "string", "const": requirement_id}
                if allowed:
                    variant["properties"]["gap_ids"]["items"] = {"type": "string", "enum": allowed}
                else:
                    # 为什么要有它：Patch 可以调查既有需求的新事实；不能为此伪造已接受的 Findings 缺口。
                    variant["properties"]["gap_ids"].update(maxItems=0, items={"type": "string"})
                variants.append(variant)
        if variants:
            schema["properties"]["queries"]["items"] = {"oneOf": variants}
        else:
            # 为什么要有它：初始 Findings 无已绑定缺口时不能凭空建查询，也不能向 native schema 发送空 enum。
            schema["properties"]["queries"].update(maxItems=0, items={"type": "object"})
    role = "initial_findings_queries" if initial else "upstream_evidence_queries"
    payload = {
        "message_type": "initial_findings_evidence_queries" if initial else "patch_upstream_evidence_queries",
        "feature": feature,
        "requirements": projection["requirements"], "relations": projection["relations"],
        "gap_investigation_targets": gap_targets,
        **({"prior_query_outcomes": prior_query_outcomes} if prior_query_outcomes is not None else {}),
        **({"prior_dependency_api_observation": {key: deepcopy(
            old.budget_summary["dependency_api_supplement"].get(key)) for key in (
                "status", "reason", "metadata_query_count", "visible_metadata")
                if key in old.budget_summary["dependency_api_supplement"]}}
            if old.budget_summary.get("dependency_api_supplement") is not None else {}),
        **({"source_diversification_required": True} if source_diversification else {}),
        **({"source_diversification_mode": "deterministic_bounded_source_policy",
            "source_diversification_requirement_ids": dependency_requirement_ids}
            if source_diversification else {}),
        "source_observations": [_query_source_observation_view(item) for item in old.items],
        ("coverage_feedback" if initial else "failure_feedback"): feedback,
        "search_root": upstream_search_root,
        "instruction": (
            "Choose bounded queries for current source or dependency API facts needed to resolve the gap. "
            "For a change requirement, do not query whether the requested new behavior is already implemented; "
            "query the existing configuration, input lifecycle, state guards, persistence, display, and other "
            "current mechanisms needed to plan it. Prefer concrete identifiers already present in source "
            "observations. Each source query stays in query and is at most 256 characters. When an external "
            "API fact is needed, put 1-3 "
            "compact type or member identifier substrings in metadata_queries; the metadata tool performs "
            "case-insensitive literal substring matching, so metadata_queries must not contain questions or "
            "prose. Use an empty metadata_queries list when no dependency lookup is needed. Every query must "
            "bind requirement_id and state the current_fact_needed, modification_impact, and authorized_source. Do not "
            "query a gap that merely restates requested new behavior or post-change acceptance. If prior query "
            "outcomes show no new evidence, do not repeat the same source or metadata query. Queries grant no "
            "edit permission and must not choose a Hook. gap_ids map to relation_index and gap_index in the "
            "coverage feedback findings, avoiding duplicate gap text. When source_diversification_required is "
            "true, at least one query must use dependency_api under the nonempty identifier rule above because "
            "a listed pre_patch_evidence requirement asks for an API fact and the previous source-only cycle "
            "added none. This is deterministic policy, not proof of model preference; other queries may be empty."
        ),
    }
    payload["instruction"] += (
        " For Patch investigation, use gap_ids=[] when no accepted formal gap applies to the selected requirement."
        if allow_gapless_patch_query else " Every query must bind at least one existing gap_id.")
    if contract_version in {"requirement_queries_v2", "requirement_queries_v3"}:
        payload["query_contract_version"] = contract_version
        payload["tool_capabilities"] = (deepcopy(tool_capabilities) if tool_capabilities is not None
            else query_tool_capabilities(upstream_search_root=upstream_search_root))
        payload["instruction"] += (
            " Every gap_id must belong to a relation whose parent_requirement_ids includes the selected "
            "requirement_id. This prevents independently valid IDs from dispatching a misbound query. "
            "The listed tool capabilities describe existing execution and bound sources only; they grant no "
            "additional search scope. Both fields are executed as described, not interpreted as natural-language questions.")
    if contract_version == "requirement_queries_v3":
        payload["instruction"] += (
            " Every metadata_queries item is 1-128 characters without whitespace or '?'; use a compact type/member substring, "
            "not a prose description. query, current_fact_needed and modification_impact are each at most 256 characters. "
            "为什么要有它：工具按紧凑标识符做字面搜索，原生schema与宿主校验必须表达相同的现有输入边界。")
    return {"role": role, "payload": payload, "schema": schema}

