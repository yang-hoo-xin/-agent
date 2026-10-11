"""Minimal live-workspace rg evidence provider for the real V2 slice."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from src.core.trace.execution_trace import trace_operation
from src.mod_agent.upstream_trace import (
    material_identities,
    observe_local_tool_bodies,
    payload_sha256,
    update_observation,
)

from .models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EvidenceItem,
    EvidencePack,
    missing_evidence_from_blockers,
)
from .small_project_context import (
    collect_small_project_context,
    run_context_policy,
    validate_context_policy,
)
from .source_view import is_small_csharp_file, source_view_policy, whole_file_source_item
from .source_window import fallback_source_window

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_CSHARP_FILENAME_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.-]*\.cs\b")
_RG_LINE_RE = re.compile(r"^(.*\.cs):(\d+):(.*)$", re.IGNORECASE)
_CSHARP_METHOD_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|virtual|override|abstract|"
    r"sealed|async|extern|unsafe|new|partial)\s+)*"
    r"(?P<return_type>[A-Za-z_][A-Za-z0-9_.<>,?\[\]]*)\s+"
    r"(?P<method_name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\((?P<parameters>[^)]*)\)\s*(?:\{|(?P<expression_body>=>[^\r\n]*;))?\s*$"
)
_CSHARP_TYPE_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|abstract|sealed|partial)\s+)*"
    r"(?:class|struct|record)\s+(?P<type_name>[A-Za-z_][A-Za-z0-9_]*)\b"
)
_CSHARP_FILE_SCOPED_NAMESPACE_RE = re.compile(
    r"^namespace\s+(?P<namespace>[A-Za-z_][A-Za-z0-9_.]*)\s*;\s*$"
)
_CSHARP_BLOCK_NAMESPACE_RE = re.compile(
    r"^namespace\s+(?P<namespace>[A-Za-z_][A-Za-z0-9_.]*)\s*(?:\{|$)"
)
_CSHARP_MEMBER_DECLARATION_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|readonly|const|volatile|"
    r"required|new)\s+)*"
    r"(?P<declared_type>[A-Za-z_][A-Za-z0-9_.]*(?:\s*<[^;={}()]+>)?"
    r"(?:\s*\[\s*\])*\??)\s+"
    r"(?P<member_name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<declaration_suffix>\{|=|;)"
)
_STOP_WORDS = {
    "and",
    "change",
    "changing",
    "color",
    "make",
    "other",
    "the",
    "this",
    "without",
}


class RgLiveEvidenceProvider:
    """Collect bounded source-bound live excerpts without maintaining an index."""

    def __init__(self, workspace_root: str | Path, *, rg_executable: str = "rg",
                 small_file_max_bytes: int = 0, small_project_context_policy: dict | None = None,
                 reuse_query_observations: bool = True) -> None:
        if type(reuse_query_observations) is not bool:
            raise ValueError("RG_LIVE_QUERY_OBSERVATION_REUSE_INVALID")
        self._reuse_query_observations = reuse_query_observations
        self.workspace_root = Path(workspace_root).resolve()
        self.rg_executable = rg_executable
        self.small_file_max_bytes = source_view_policy(small_file_max_bytes)["small_file_max_bytes"]
        self.small_project_context_policy = (run_context_policy(self.workspace_root)
            if small_project_context_policy is None else validate_context_policy(small_project_context_policy))

    @property
    def reuse_query_observations(self) -> bool:
        return self._reuse_query_observations

    @property
    def source_view_policy(self) -> dict[str, object]:
        return source_view_policy(self.small_file_max_bytes)

    def query_set_material_budget(self, *, query_count: int, max_items: int | None = None) -> dict[str, object]:
        """Keep query obligations separate from the bounded source-material count."""
        policy = self.small_project_context_policy
        selected = max(query_count, policy["max_files"]) if max_items is None else max_items
        # 为什么要有它：少数需求可能跨多个协作文件；保留旧查询数量下限，不把空命中兜底8192字节误用为所有项目总限。
        byte_unit = max(self.small_file_max_bytes, policy["max_total_bytes"])
        return {"schema_version": "rg_live_source_material_budget_v1", "query_count": query_count,
                "scope": "query_set_retained_source_excerpts_not_total_model_request_or_read_io",
                "max_items": selected, "max_source_files": selected,
                "small_project_material_floor": policy["max_files"],
                "max_excerpt_utf8_bytes": selected * byte_unit, "byte_unit": byte_unit,
                "omission_metadata_limit": policy["max_entries"],
                "selection_basis": "explicit_max_items" if max_items is not None else "max_query_count_and_small_project_material_floor",
                "source_view_policy": self.source_view_policy,
                "small_project_limits": {key: policy[key] for key in ("max_files", "max_total_bytes", "max_entries")},
                "fallback_enabled": policy["enabled"], "semantic_coverage_claimed": False}

    def collect(
        self,
        *,
        query: str,
        search_root: str | Path,
        source_identity_query: str | None = None,
        max_items: int = 1,
    ) -> EvidencePack:
        input_payload = {"query": query, "search_root": str(search_root),
                         "source_identity_query": source_identity_query, "max_items": max_items,
                         "source_view_policy": self.source_view_policy}
        with trace_operation("evidence.source_query", kind="tool", attributes={
            "input_payload_sha256": payload_sha256(input_payload),
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "tool_dispatch_performed": False,
        }) as span:
            with observe_local_tool_bodies(span, input_payload) as record_result:
                result = self._collect(query=query, search_root=search_root,
                    source_identity_query=source_identity_query, max_items=max_items, span=span)
                result_payload = result.to_artifact_payload()
                record_result(result_payload)
            update_observation(span,
                produced_materials=material_identities(result.items),
                evidence_item_count=len(result.items),
                output_payload_sha256=payload_sha256(result_payload),
                decision_summary_origin="deterministic_structured_result",
                decision_summary=f"当前源码查询返回 {len(result.items)} 份材料。",
            )
            return result

    def _collect(
        self, *, query: str, search_root: str | Path,
        source_identity_query: str | None, max_items: int, span,
    ) -> EvidencePack:
        started = time.perf_counter()
        def empty(status, reason):
            return replace(EvidencePack.empty(query=query, reason=reason),
                budget_summary={"retrieval_status": status,
                                "source_view_policy": self.source_view_policy})
        if (
            isinstance(max_items, bool)
            or not isinstance(max_items, int)
            or max_items < 1
        ):
            raise ValueError("RG_LIVE_ITEM_BUDGET_INVALID")
        root = (self.workspace_root / search_root).resolve()
        try:
            root.relative_to(self.workspace_root)
        except ValueError as exc:
            update_observation(span, retrieval_status="source_scope_rejected")
            return empty("source_scope_rejected", f"Search root escapes workspace: {exc}")
        if not root.is_dir():
            update_observation(span, retrieval_status="source_root_missing")
            return empty("source_root_missing", "Configured target source root is missing.")

        tokens = _query_tokens(query)
        if not tokens:
            update_observation(span, retrieval_status="query_terms_missing")
            return empty("query_terms_missing", "Request has no usable rg search terms.")
        pattern = "|".join(re.escape(token) for token in tokens)
        command = (
            self.rg_executable,
            "--line-number",
            "--ignore-case",
            "--glob",
            "*.cs",
            "--max-count",
            "80",
            pattern,
            str(root),
        )
        update_observation(span, tool_dispatch_attempted=True)
        completed = subprocess.run(
            command,
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        update_observation(span, tool_dispatch_performed=True)
        if completed.returncode not in {0, 1}:
            update_observation(span, retrieval_status="tool_failed", tool_exit_code=completed.returncode)
            return empty(
                "tool_failed",
                reason=f"rg failed with exit code {completed.returncode}: {completed.stderr.strip()}",
            )
        matches = _parse_matches(completed.stdout)
        if not matches:
            update_observation(span, retrieval_status="no_matches", tool_exit_code=completed.returncode)
            return empty("no_matches", "rg found no live C# source matches.")

        requested_filename = _requested_csharp_filename(
            source_identity_query if source_identity_query is not None else query
        )
        requested_path: Path | None = None
        if requested_filename is not None:
            requested_paths = tuple(
                sorted(
                    (
                        path.resolve()
                        for path in root.rglob("*.cs")
                        if path.name == requested_filename
                    ),
                    key=lambda path: path.as_posix(),
                )
            )
            if len(requested_paths) != 1:
                update_observation(span, retrieval_status="source_identity_ambiguous")
                return empty(
                    "source_identity_ambiguous",
                    reason=(
                        "The explicitly requested C# filename did not resolve to "
                        "exactly one current source file. "
                        f"filename={requested_filename!r}; "
                        f"resolved_count={len(requested_paths)}; "
                        "resolved_paths="
                        f"{[path.as_posix() for path in requested_paths]!r}."
                    ),
                )
            requested_path = requested_paths[0]
            if not any(path == requested_path for path, _, _ in matches):
                update_observation(span, retrieval_status="requested_source_no_matches")
                return empty(
                    "requested_source_no_matches",
                    reason=(
                        "The explicitly requested C# source file contained no "
                        "request-term match."
                    ),
                )
        try:
            selected_locations, source_cache = _rank_evidence_locations(
                matches,
                tokens,
                requested_path=requested_path,
                max_items=max_items,
                small_file_max_bytes=self.small_file_max_bytes,
                identifier_tokens=tuple(_query_tokens(" ".join(_request_source_identifiers(query)))),
            )
        except UnicodeDecodeError as exc:
            update_observation(span, retrieval_status="source_decode_failed")
            return empty(
                "source_decode_failed",
                reason=f"Selected live C# source is not valid UTF-8: {exc}",
            )
        items = [
            materialize_source_location(
                workspace_root=self.workspace_root, selected_path=selected_path,
                selected_line=selected_line, source_bytes=source_cache[selected_path][0], tokens=tokens,
                small_file_max_bytes=self.small_file_max_bytes,
            )
            for selected_path, selected_line in selected_locations
        ]
        selected_paths = {path for path, _ in selected_locations}
        eligible_paths = {path for path, _, _ in matches if requested_path is None or path == requested_path}
        omitted_paths = sorted(eligible_paths - selected_paths, key=lambda path: path.as_posix())
        omission_limit = self.small_project_context_policy["max_entries"]
        lane_omissions = [{"source_path": path.relative_to(self.workspace_root).as_posix(),
            "reason": "per_query_material_limit", "source_read": path in source_cache,
            "match_observed": True, "source_hash": source_cache[path][2] if path in source_cache else None}
            for path in omitted_paths[:omission_limit]]
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        update_observation(span, retrieval_status="source_observations_returned", tool_exit_code=completed.returncode)
        coverage_blocker = {
            "code": "RG_LIVE_REQUIREMENT_COVERAGE_UNPROVEN",
            "message": (
                "Live lexical source observations do not establish explicit, "
                "verifiable requirement coverage."
            ),
            "needed_evidence": [
                "explicit requirement-to-evidence coverage",
            ],
        }
        return EvidencePack(
            query=query,
            readiness="insufficient",
            can_generate_patch=False,
            items=tuple(items),
            gaps=(
                "Explicit requirement coverage is not established by rg lexical matches.",
            ),
            blockers=(coverage_blocker,),
            missing_evidence=(
                {
                    "needed_evidence": "explicit requirement-to-evidence coverage",
                    "blocker_code": coverage_blocker["code"],
                    "reason": coverage_blocker["message"],
                },
            ),
            retrieval_methods_used=("rg_live_read",),
            budget_summary={"retrieval_status": "source_observations_returned",
                            "source_view_policy": self.source_view_policy,
                            "source_selection": {"matched_source_files": len(eligible_paths),
                                "materialized_source_files": len(selected_paths),
                                "omitted_matched_sources": lane_omissions,
                                "omitted_matched_source_count": len(omitted_paths),
                                "omission_metadata_complete": len(omitted_paths) <= omission_limit}},
            disabled_modes={
                "bm25": "Not selected by the completed directional decision.",
                "dense": "Not selected by the completed directional decision.",
                "fusion": "Not selected by the completed directional decision.",
                "rerank": "Not selected by the completed directional decision.",
            },
            timing={
                "query_processing_ms": 0.0,
                "symbol_ms": 0.0,
                "text_ms": elapsed_ms,
                "bm25_ms": 0.0,
                "dense_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "readiness_ms": 0.0,
                "total_ms": elapsed_ms,
                "final_count": float(len(items)),
                "excluded_count": 0.0,
            },
            message=(
                "rg plus live file read retained one source-authentic lexical "
                "observation; patch authority remains blocked without explicit "
                "requirement coverage."
                if len(items) == 1
                else (
                    "rg plus live file read retained bounded source-authentic "
                    "lexical observations; patch authority remains blocked without "
                    "explicit requirement coverage."
                )
            ),
        )

    def _query_batch_revision(self, search_root: str | Path) -> dict[str, str] | None:
        """Bind reusable lexical results to exact local source and search settings."""
        root = (self.workspace_root / search_root).resolve()
        if not root.is_relative_to(self.workspace_root) or not root.is_dir():
            return None
        # 为什么要有它：只在本次非Git隔离源码批次内共享；外部rg配置/Git忽略规则不在版本合同内时仍走原始实时查询。
        if os.environ.get("RIPGREP_CONFIG_PATH") or any((p / ".git").exists() for p in (root, *root.parents)):
            return None
        files = []
        pending = [root]
        try:
            while pending:
                directory = pending.pop()
                for entry in sorted(os.scandir(directory), key=lambda row: row.name):
                    metadata = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        return None
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    elif path.suffix.lower() == ".cs" or path.name in {".ignore", ".gitignore", ".rgignore"}:
                        files.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
            for parent in root.parents:
                for name in (".ignore", ".gitignore", ".rgignore"):
                    path = parent / name
                    if path.is_file():
                        files.append((str(path), hashlib.sha256(path.read_bytes()).hexdigest()))
        except OSError:
            return None
        return {"source_sha256": payload_sha256({"root": str(root), "files": sorted(files)}),
                "strategy_sha256": payload_sha256({"rg_executable": self.rg_executable,
                    "source_view_policy": self.source_view_policy, "command_contract": "rg_live_v1",
                    "small_project_context_policy": self.small_project_context_policy})}

    def collect_query_set(
        self,
        *,
        queries: tuple[dict[str, str], ...],
        search_root: str | Path,
        max_items: int,
        source_identity_query: str | None = None,
    ) -> EvidencePack:
        """Resolve every obligation lane, sharing identical version-bound queries within this batch."""

        if (
            not queries
            or isinstance(max_items, bool)
            or not isinstance(max_items, int)
            or max_items < len(queries)
            or len(queries) > 64
        ):
            raise ValueError("RG_LIVE_QUERY_SET_BUDGET_INVALID")
        seen_query_ids: set[str] = set()
        lane_items: list[tuple[EvidenceItem, ...]] = []
        query_rows: list[dict[str, str]] = []
        total_ms = 0.0
        identifier_lanes: list[tuple[EvidenceItem, ...]] = []
        identifier_rows: list[dict[str, object]] = []
        observations: dict[tuple[str, str, str, int], tuple[EvidencePack, str]] = {}
        material_budget = self.query_set_material_budget(query_count=len(queries), max_items=max_items)
        lane_omissions: dict[str, dict[str, object]] = {}
        lane_omission_metadata_complete = True
        dispatch_count = reuse_count = 0
        source_revision: str | None = None
        validation_ms = 0.0

        def collect_lane(text: str, origin: str):
            nonlocal dispatch_count, reuse_count, source_revision, validation_ms, lane_omission_metadata_complete
            before_clock = time.perf_counter()
            before = self._query_batch_revision(search_root)
            validation_ms += (time.perf_counter() - before_clock) * 1000.0
            if before is not None:
                if source_revision is not None and source_revision != before["source_sha256"]:
                    raise ValueError("RG_LIVE_QUERY_SET_SOURCE_CHANGED")
                source_revision = before["source_sha256"]
            key = ((before["source_sha256"], before["strategy_sha256"], text, max_items)
                   if before is not None else None)
            # 为什么要有它：在线对照只切换同批观察复用，两组均执行相同源码版本检查和材料保留规则。
            if self.reuse_query_observations and key is not None and key in observations:
                pack, first_origin = observations[key]
                reuse_count += 1
                return deepcopy(pack), {"observation_reused": True,
                    "reused_from_lane": first_origin, "source_revision": before}, 0.0
            pack = self.collect(query=text, search_root=search_root, max_items=max_items)
            selection = pack.budget_summary.get("source_selection", {})
            lane_omission_metadata_complete = lane_omission_metadata_complete and selection.get("omission_metadata_complete", True)
            for omitted in selection.get("omitted_matched_sources", []):
                lane_omissions[str(omitted["source_path"])] = deepcopy(omitted)
            dispatch_count += 1
            after_clock = time.perf_counter()
            after = self._query_batch_revision(search_root)
            validation_ms += (time.perf_counter() - after_clock) * 1000.0
            # 为什么要有它：跨源码版本不能拼成一个当前证据包，源树在调查中变化则显式失败；新调用会重新读取。
            if before is not None and after is not None and before["source_sha256"] != after["source_sha256"]:
                raise ValueError("RG_LIVE_QUERY_SET_SOURCE_CHANGED")
            if self.reuse_query_observations and key is not None and before == after and pack.budget_summary.get("retrieval_status") in {
                    "source_observations_returned", "no_matches", "requested_source_no_matches"}:
                observations[key] = deepcopy(pack), origin
            return pack, {"observation_reused": False, "reused_from_lane": None,
                          "source_revision": before}, float(pack.timing.get("total_ms", 0.0))
        # 为什么要有它：模型的粗类别查询不能抹去用户明确写出的源码标识符；这些只增加检索线索，不授予语义支持或编辑权限。
        for identifier in _request_source_identifiers(source_identity_query or ""):
            lane_pack, reuse, lane_ms = collect_lane(identifier, f"request_identifier:{len(identifier_rows)}")
            total_ms += lane_ms
            identifier_lanes.append(lane_pack.items)
            identifier_rows.append({
                "query": identifier,
                "origin": "user_request_identifier",
                **reuse,
                "request_sha256": hashlib.sha256(source_identity_query.encode("utf-8")).hexdigest(),
                "retrieval_status": lane_pack.budget_summary.get("retrieval_status", "unknown"),
            })
        for query in queries:
            if set(query) != {"query_id", "query", "requirement_id"} or any(
                not isinstance(query.get(key), str) or not query[key].strip()
                for key in ("query_id", "query", "requirement_id")
            ):
                raise ValueError("RG_LIVE_QUERY_SET_ENTRY_INVALID")
            query_id = str(query["query_id"])
            if query_id in seen_query_ids:
                raise ValueError("RG_LIVE_QUERY_SET_ID_DUPLICATE")
            seen_query_ids.add(query_id)
            lane_pack, reuse, lane_ms = collect_lane(str(query["query"]), query_id)
            total_ms += lane_ms
            lane_items.append(lane_pack.items)
            query_rows.append(
                {
                    "query_id": query_id,
                    **reuse,
                    "retrieval_status": lane_pack.budget_summary.get("retrieval_status", "unknown"),
                    "requirement_id": str(query["requirement_id"]),
                    "query_sha256": hashlib.sha256(
                        str(query["query"]).encode("utf-8")
                    ).hexdigest(),
                }
            )
        items: list[EvidenceItem] = []
        selected_by_occurrence: dict[tuple[str, ...], EvidenceItem] = {}
        selected_item_ids: set[str] = set()
        retained_bytes = 0
        omitted_reasons: dict[tuple[str, ...], str] = {}

        def retain(item: EvidenceItem) -> None:
            nonlocal retained_bytes
            occurrence = _evidence_occurrence_key(item)
            if occurrence in selected_by_occurrence:
                return
            if len(items) >= max_items:
                omitted_reasons[occurrence] = "material_item_limit"
                return
            item_bytes = len(item.excerpt.encode("utf-8"))
            if retained_bytes + item_bytes > material_budget["max_excerpt_utf8_bytes"]:
                omitted_reasons[occurrence] = "source_excerpt_byte_limit"
                return
            if item.evidence_id in selected_item_ids:
                raise ValueError("RG_LIVE_EVIDENCE_ID_COLLISION")
            selected_by_occurrence[occurrence] = item
            selected_item_ids.add(item.evidence_id)
            items.append(item)
            retained_bytes += item_bytes

        # 为什么要有它：在原材料上限内先保留明确源码线索的最佳材料，再保留投影查询；重复材料归并后剩余额度用于次级命中。
        for lane in (*identifier_lanes, *lane_items):
            if lane:
                retain(lane[0])
        # 为什么要有它：明确标识符查询的次级命中也是已取得的真实源码，不能在有剩余额度时静默遗漏。
        for lane in (*identifier_lanes, *lane_items):
            for item in lane[1:]:
                retain(item)

        query_execution: list[dict[str, object]] = []
        for row, lane in zip(query_rows, lane_items, strict=True):
            lane_evidence_ids: list[str] = []
            for item in lane:
                retained = selected_by_occurrence.get(
                    _evidence_occurrence_key(item)
                )
                if (
                    retained is not None
                    and retained.evidence_id not in lane_evidence_ids
                ):
                    lane_evidence_ids.append(retained.evidence_id)
            query_execution.append(
                {**row, "evidence_ids": lane_evidence_ids}
            )
        for row, lane in zip(identifier_rows, identifier_lanes, strict=True):
            row["evidence_ids"] = list(dict.fromkeys(
                selected_by_occurrence[_evidence_occurrence_key(item)].evidence_id
                for item in lane if _evidence_occurrence_key(item) in selected_by_occurrence
            ))
        all_occurrences = {
            _evidence_occurrence_key(item)
            for lane in (*identifier_lanes, *lane_items)
            for item in lane
        }
        context_audit = None
        if (self.small_project_context_policy["enabled"] and self.small_file_max_bytes > 0
                and not items
                and all(row["retrieval_status"] == "no_matches" for row in (*query_rows, *identifier_rows))
                and not any(_requested_csharp_filename(text) for text in (
                    source_identity_query or "", *(str(row["query"]) for row in queries)))):
            context_started = time.perf_counter()
            context_items, context_audit = collect_small_project_context(
                workspace_root=self.workspace_root, search_root=search_root, max_items=max_items,
                small_file_max_bytes=self.small_file_max_bytes, policy=self.small_project_context_policy)
            total_ms += (time.perf_counter() - context_started) * 1000.0
            for item in context_items:
                retain(item)
                all_occurrences.add(_evidence_occurrence_key(item))
        # 为什么要有它：被检索预算省略的源码不能伪装成没有命中；只传来源/哈希/原因，不新增可引用材料或修改权限。
        observed_materials = {_evidence_occurrence_key(item): item
            for lane in (*identifier_lanes, *lane_items) for item in lane}
        omitted_materials = [{"evidence_id": item.evidence_id, "source_path": item.source_path,
            "source_hash": item.source_hash, "span": item.span,
            "excerpt_sha256": hashlib.sha256(item.excerpt.encode("utf-8")).hexdigest(),
            "excerpt_utf8_bytes": len(item.excerpt.encode("utf-8")), "source_read": True,
            "reason": omitted_reasons.get(occurrence, "material_item_limit")}
            for occurrence, item in observed_materials.items() if occurrence not in selected_by_occurrence]
        selected_paths = {item.source_path for item in items}
        unmatched_materials = [value for path, value in lane_omissions.items() if path not in selected_paths]
        omission_limit = int(material_budget["omission_metadata_limit"])
        material_budget.update(retained_items=len(items), retained_source_files=len(selected_paths),
                               retained_excerpt_utf8_bytes=retained_bytes)
        omission_audit = {"schema_version": "rg_live_source_omissions_v1",
            "scope": "query_set_selection_before_any_later_augmentation",
            "omitted_read_materials": omitted_materials[:omission_limit],
            "omitted_read_material_count": len(omitted_materials),
            "matched_sources_not_materialized": unmatched_materials[:omission_limit],
            "matched_sources_not_materialized_known_count": len(unmatched_materials),
            "omission_metadata_complete": lane_omission_metadata_complete and
                len(omitted_materials) <= omission_limit and len(unmatched_materials) <= omission_limit,
            "semantic_coverage_claimed": False, "omitted_ids_are_citeable": False}
        # 为什么要有它：续接身份必须可重建；源码复核耗时属于timing，不能混入确定性预算/来源字段。
        total_ms += validation_ms
        blocker = {
            "code": "RG_LIVE_REQUIREMENT_COVERAGE_UNPROVEN",
            "message": (
                "Bounded live query execution does not itself establish explicit "
                "requirement coverage."
            ),
            "needed_evidence": ["explicit requirement-to-evidence findings"],
        }
        return EvidencePack(
            query="\n".join(str(query["query"]) for query in queries),
            readiness="insufficient",
            can_generate_patch=False,
            items=tuple(items),
            excluded=tuple(omitted_materials[:omission_limit]),
            gaps=("Explicit requirement coverage findings are not yet resolved.",),
            blockers=(blocker,),
            retrieval_methods_used=("rg_live_query_set", "rg_live_read",
                *(("bounded_small_project_context",) if context_audit is not None else ())),
            missing_evidence=missing_evidence_from_blockers((blocker,)),
            disabled_modes={
                "bm25": "Not used by the current live-source query-set owner.",
                "dense": "Dense retrieval is disabled for this ProductExecution path.",
                "fusion": "Fusion is disabled for this ProductExecution path.",
                "rerank": "Reranking is disabled for this ProductExecution path.",
            },
            timing={
                "query_processing_ms": 0.0,
                "symbol_ms": 0.0,
                "text_ms": total_ms,
                "bm25_ms": 0.0,
                "dense_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "readiness_ms": 0.0,
                "total_ms": total_ms,
                "final_count": float(len(items)),
                "excluded_count": float(
                    len(all_occurrences) - len(selected_by_occurrence)
                ),
            },
            budget_summary={
                "source_view_policy": self.source_view_policy,
                "source_material_budget": material_budget,
                "source_material_omissions": omission_audit,
                **({"small_project_context": context_audit} if context_audit is not None else {}),
                "query_count": len(queries),
                "query_observation_reuse": {"scope": "same_collect_query_set_exact_source_and_strategy",
                    # 为什么要有它：默认开启保持历史包的确定性形状；False 对照显式留痕，完整策略另由运行 manifest 记录。
                    **({"enabled": False} if not self.reuse_query_observations else {}),
                    "collect_calls": dispatch_count, "reused_lanes": reuse_count},
                "max_items": max_items,
                "per_query_execution": query_execution,
                **({"request_identifier_queries": identifier_rows} if identifier_rows else {}),
                "all_queries_executed": all(row["retrieval_status"] in {
                    "source_observations_returned", "no_matches", "requested_source_no_matches"}
                    for row in query_execution),
                "dense_enabled": False,
            },
            message=(
                "Every focused query resolved against current live source with any shared observation identified; semantic "
                "coverage remains owned by the requirement coverage projection."
            ),
        )


def materialize_source_location(
    *, workspace_root: Path, selected_path: Path, selected_line: int,
    source_bytes: bytes, tokens: list[str], small_file_max_bytes: int = 0,
) -> EvidenceItem:
    """Project exact live bytes into the existing complete source-unit contract."""
    lines = source_bytes.decode("utf-8").splitlines(keepends=True)
    if not 1 <= selected_line <= len(lines):
        raise ValueError("LIVE_SOURCE_SELECTED_LINE_INVALID")
    source_view_policy(small_file_max_bytes)
    if is_small_csharp_file(selected_path, source_bytes, small_file_max_bytes):
        return whole_file_source_item(workspace_root=workspace_root,
            selected_path=selected_path, source_bytes=source_bytes)
    file_hash = hashlib.sha256(source_bytes).hexdigest()
    method_spans = _csharp_method_source_spans(lines)
    method_context = _enclosing_csharp_method(
        lines,
        selected_line=selected_line,
        method_spans=method_spans,
    )
    source_context = method_context or _enclosing_csharp_field(
        lines, selected_line=selected_line
    )
    fallback_start, fallback_end = fallback_source_window(
        selected_line=selected_line, line_count=len(lines),
        method_spans=method_spans if selected_path.suffix.lower() == ".cs" else (),
    )
    start_line = (
        int(source_context["start_line"])
        if source_context is not None
        else fallback_start
    )
    end_line = (
        int(source_context["end_line"])
        if source_context is not None
        else fallback_end
    )
    excerpt = (
        str(source_context["source_text"])
        if source_context is not None
        else "".join(lines[start_line - 1 : end_line])
    )
    relative = selected_path.relative_to(workspace_root).as_posix()
    evidence_id = "rg_live_" + hashlib.sha256(
        f"{relative}:{file_hash}:{start_line}:{end_line}".encode()
    ).hexdigest()[:16]
    symbol = (
        str(source_context["symbol"])
        if source_context is not None
        else _best_symbol(excerpt, tokens)
    )
    declared_members = (
        _declared_csharp_members(
            lines,
            declaring_type=str(source_context["declaring_type"]),
            declaring_type_full_name=str(
                source_context["declaring_type_full_name"]
            ),
        )
        if source_context is not None
        and source_context.get("declaring_type") is not None
        and source_context.get("declaring_type_full_name") is not None
        else None
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type="target_source",
        source_path=relative,
        symbol=symbol,
        span={"start_line": start_line, "end_line": end_line},
        retrieval_method="rg_live_read",
        score=1.0,
        claim_supported=(
            f"Live source contains request terms near {symbol or relative}."
        ),
        excerpt=excerpt,
        chunk_id=f"live:{relative}:{start_line}:{end_line}",
        document_id=f"live:{relative}",
        source_ref=str(selected_path),
        source_hash=file_hash,
        file_hash=file_hash,
        doc_hash=file_hash,
        authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
        declaring_type=(
            str(source_context["declaring_type"])
            if source_context is not None
            and source_context.get("declaring_type") is not None
            else None
        ),
        method_name=(
            str(method_context["method_name"])
            if method_context is not None
            else None
        ),
        parameter_types=(
            tuple(method_context["parameter_types"])
            if method_context is not None
            and method_context.get("parameter_types") is not None
            else None
        ),
        return_type=(
            str(method_context["return_type"])
            if method_context is not None
            else None
        ),
        method_kind="method" if method_context is not None else None,
        declared_member_types=(
            {
                name: str(identity["declared_type"])
                for name, identity in (declared_members or {}).items()
            }
            if declared_members is not None
            else None
        ),
        declaring_type_full_name=(
            str(source_context["declaring_type_full_name"])
            if source_context is not None
            and source_context.get("declaring_type_full_name") is not None
            else None
        ),
        declared_members=declared_members,
    )


def _query_tokens(query: str) -> list[str]:
    return list(
        dict.fromkeys(
            token.lower()
            for token in _TOKEN_RE.findall(query)
            if token.lower() not in _STOP_WORDS
        )
    )[:12]


def _request_source_identifiers(request: str) -> tuple[str, ...]:
    """Bounded lexical hints from explicit code spellings, never inferred targets."""
    from src.mod_agent.planning.clarified_request import source_hint_text
    request = source_hint_text(request)
    hints: list[str] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", request):
        value = match.group()
        if value.endswith(".cs"):
            hints.append(value)
        elif "." in value:
            hints.extend(value.split("."))
        elif (re.search(r"[a-z][A-Z]|[A-Z]{2}[a-z]|[a-zA-Z]_[a-zA-Z]", value)
              or request[match.end():].startswith("(")):
            hints.append(value)
    return tuple(dict.fromkeys(hint for hint in hints if _query_tokens(hint)))[:8]


def _parse_matches(raw: str) -> list[tuple[Path, int, str]]:
    matches: list[tuple[Path, int, str]] = []
    for line in raw.splitlines():
        match = _RG_LINE_RE.match(line)
        if match:
            matches.append((Path(match.group(1)).resolve(), int(match.group(2)), match.group(3)))
    return matches


def _requested_csharp_filename(query: str) -> str | None:
    filenames = tuple(dict.fromkeys(_CSHARP_FILENAME_RE.findall(query)))
    return filenames[0] if len(filenames) == 1 else None


def _rank_evidence_locations(
    matches: list[tuple[Path, int, str]],
    tokens: list[str],
    *,
    requested_path: Path | None,
    max_items: int,
    small_file_max_bytes: int = 0,
    identifier_tokens: tuple[str, ...] = (),
) -> tuple[
    tuple[tuple[Path, int], ...],
    dict[Path, tuple[bytes, list[str], str]],
]:
    """Keep one primary occurrence, then ranked secondary-source occurrences."""

    ranked_files = _rank_files(
        matches,
        tokens,
        requested_path=requested_path,
        identifier_tokens=identifier_tokens,
    )
    source_cache: dict[Path, tuple[bytes, list[str], str]] = {}

    def ranked_lines(
        path: Path,
        path_matches: list[tuple[int, str]],
    ) -> tuple[int, ...]:
        source_bytes = path.read_bytes()
        lines = source_bytes.decode("utf-8").splitlines(keepends=True)
        source_cache[path] = (
            source_bytes,
            lines,
            hashlib.sha256(source_bytes).hexdigest(),
        )
        if is_small_csharp_file(path, source_bytes, small_file_max_bytes):
            return (min(line_number for line_number, _ in path_matches),)
        return _rank_distinct_match_lines(
            tuple(path_matches),
            tokens,
            lines=lines,
        )

    primary_path, primary_matches = ranked_files[0]
    primary_lines = ranked_lines(primary_path, primary_matches)
    locations: list[tuple[Path, int]] = [(primary_path, primary_lines[0])]
    if len(locations) >= max_items:
        return tuple(locations), source_cache
    # A dominant primary file already has one representative. Explore ranked
    # secondary sources before spending the same lane on primary-file repeats.
    for path, path_matches in ranked_files[1:]:
        for line_number in ranked_lines(path, path_matches):
            locations.append((path, line_number))
            if len(locations) >= max_items:
                return tuple(locations), source_cache
    for line_number in primary_lines[1:]:
        locations.append((primary_path, line_number))
        if len(locations) >= max_items:
            break
    return tuple(locations), source_cache


def _rank_files(
    matches: list[tuple[Path, int, str]],
    tokens: list[str],
    *,
    requested_path: Path | None,
    identifier_tokens: tuple[str, ...] = (),
) -> list[tuple[Path, list[tuple[int, str]]]]:
    declaration_tokens = frozenset(tokens if len(tokens) == 1 else identifier_tokens)
    by_path: dict[Path, list[tuple[int, str]]] = {}
    for path, line_number, text in matches:
        by_path.setdefault(path, []).append((line_number, text))
    eligible = (
        {
            path: path_matches
            for path, path_matches in by_path.items()
            if path == requested_path
        }
        if requested_path is not None
        else by_path
    )
    return sorted(
        eligible.items(),
        key=lambda item: (
            # 为什么要有它：查询附带自然语言说明时仍优先定位明确代码标识符的同名定义，避免被调用频次挤出；不含标识符的多词查询保持原排序。
            -int(any(
                (declaration := _CSHARP_TYPE_RE.match(text.strip())) is not None
                and declaration.group("type_name").lower() in declaration_tokens
                for _, text in item[1]
            )),
            -int(any(
                (declaration := _CSHARP_METHOD_RE.match(text.strip())) is not None
                and declaration.group("method_name").lower() in declaration_tokens
                for _, text in item[1]
            )),
            -int(item[0].stem.lower() in declaration_tokens),
            -sum(
                sum(1 for token in tokens if token in text.lower())
                for _, text in item[1]
            ),
            -len(item[1]),
            item[0].as_posix(),
        ),
    )


def _rank_distinct_match_lines(
    matches: tuple[tuple[int, str], ...],
    tokens: list[str],
    *,
    lines: list[str],
) -> tuple[int, ...]:
    method_spans = _csharp_method_source_spans(lines)

    def match_key(match: tuple[int, str]) -> tuple[int, int, int, int, int, int]:
        line_number, text = match
        method_rank, match_context = _csharp_method_match_context(
            lines,
            selected_line=line_number,
            method_spans=method_spans,
        )
        lowered_text = text.lower()
        lowered_context = match_context.lower()
        return (
            -sum(lowered_context.count(token) for token in tokens),
            -sum(1 for token in tokens if token in lowered_context),
            -sum(lowered_text.count(token) for token in tokens),
            -method_rank,
            min(
                (
                    index
                    for index, token in enumerate(tokens)
                    if token in lowered_text
                ),
                default=len(tokens),
            ),
            line_number,
        )

    def method_occurrence_key(
        line_number: int,
    ) -> tuple[str, int, int] | None:
        for span in method_spans:
            start_line = int(span["start_line"])
            end_line = int(span["end_line"])
            if start_line <= line_number <= end_line:
                return ("method", start_line, end_line)
        field = _enclosing_csharp_field(lines, selected_line=line_number)
        if field is not None:
            return ("field", int(field["start_line"]), int(field["end_line"]))
        return None

    ranked_lines: list[int] = []
    seen_occurrences: set[tuple[str, int, int]] = set()
    retained_non_method_spans: list[tuple[int, int]] = []
    for line_number, _ in sorted(matches, key=match_key):
        occurrence = method_occurrence_key(line_number)
        if occurrence is not None:
            if occurrence in seen_occurrences:
                continue
            seen_occurrences.add(occurrence)
        else:
            if any(
                start_line <= line_number <= end_line
                for start_line, end_line in retained_non_method_spans
            ):
                continue
            retained_non_method_spans.append(
                fallback_source_window(selected_line=line_number,
                    line_count=len(lines), method_spans=method_spans)
            )
        ranked_lines.append(line_number)
    return tuple(ranked_lines)


def _evidence_occurrence_key(item: EvidenceItem) -> tuple[str, ...]:
    span = item.span if isinstance(item.span, dict) else {}
    source_hash = item.source_hash or item.file_hash or item.doc_hash or ""
    return (
        "span",
        item.source_path,
        source_hash,
        str(span.get("start_line")),
        str(span.get("end_line")),
    )


def _best_symbol(excerpt: str, tokens: list[str]) -> str | None:
    identifiers = _TOKEN_RE.findall(excerpt)
    scored = sorted(
        identifiers,
        key=lambda identifier: (
            -sum(
                1
                for token in tokens
                if token in identifier.lower() or identifier.lower() in token
            ),
            identifiers.index(identifier),
        ),
    )
    if scored and any(
        token in scored[0].lower() or scored[0].lower() in token for token in tokens
    ):
        return scored[0]
    return identifiers[0] if identifiers else None


def _enclosing_csharp_method(
    lines: list[str],
    *,
    selected_line: int,
    method_spans: tuple[dict[str, object], ...] | None = None,
) -> dict[str, object] | None:
    """Return the complete C# method span containing one selected line."""

    spans = (
        _csharp_method_source_spans(lines)
        if method_spans is None
        else method_spans
    )
    containing_span = next(
        (
            span
            for span in spans
            if int(span["start_line"])
            <= selected_line
            <= int(span["end_line"])
        ),
        None,
    )
    if containing_span is None:
        return None
    start_line = int(containing_span["start_line"])
    match = _CSHARP_METHOD_RE.fullmatch(lines[start_line - 1].strip())
    if match is None:
        return None
    parameters = match.group("parameters").strip()
    declaring_type = _nearest_csharp_type(lines, before_line=start_line)
    namespace = _nearest_csharp_namespace(lines, before_line=start_line)
    declaring_type_full_name = (
        f"{namespace}.{declaring_type}"
        if namespace is not None and declaring_type is not None
        else declaring_type
    )
    return {
        **containing_span,
        "symbol": match.group("method_name"),
        "declaration_line": start_line,
        "declaring_type": declaring_type,
        "declaring_type_full_name": declaring_type_full_name,
        "method_name": match.group("method_name"),
        "parameter_types": () if not parameters else None,
        "return_type": match.group("return_type"),
    }


def _enclosing_csharp_field(
    lines: list[str], *, selected_line: int
) -> dict[str, object] | None:
    """Use an existing complete single-line field declaration as its source unit."""

    if not 1 <= selected_line <= len(lines):
        return None
    line = lines[selected_line - 1]
    if not _single_csharp_statement_line(line):
        return None
    declaring_type = _nearest_csharp_type(lines, before_line=selected_line)
    if declaring_type is None:
        return None
    namespace = _nearest_csharp_namespace(lines, before_line=selected_line)
    full_name = f"{namespace}.{declaring_type}" if namespace else declaring_type
    members = _declared_csharp_members(
        lines, declaring_type=declaring_type, declaring_type_full_name=full_name
    )
    for member in members.values():
        if member["member_kind"] != "field":
            continue
        span = member["declaration_span"]
        if span == {"start_line": selected_line, "end_line": selected_line}:
            return {
                **span,
                "source_text": line,
                "symbol": member["member_name"],
                "declaring_type": declaring_type,
                "declaring_type_full_name": full_name,
            }
    return None


def _csharp_method_match_rank(
    lines: list[str],
    *,
    selected_line: int,
    method_spans: tuple[dict[str, object], ...] | None = None,
) -> int:
    """Rank a match only when it belongs to a complete C# method source span."""

    rank, _ = _csharp_method_match_context(
        lines,
        selected_line=selected_line,
        method_spans=method_spans,
    )
    return rank


def _csharp_method_match_context(
    lines: list[str],
    *,
    selected_line: int,
    method_spans: tuple[dict[str, object], ...] | None = None,
) -> tuple[int, str]:
    """Return verified method rank and bounded scoring context for one match."""

    spans = (
        _csharp_method_source_spans(lines)
        if method_spans is None
        else method_spans
    )
    for span in spans:
        start_line = int(span["start_line"])
        end_line = int(span["end_line"])
        if start_line < selected_line <= end_line:
            return 2, str(span["source_text"])
        if selected_line == start_line:
            return 1, str(span["source_text"])
    if 1 <= selected_line <= len(lines):
        value = lines[selected_line - 1].strip()
        if (
            _CSHARP_METHOD_RE.fullmatch(value) is not None
            and "{" in value
            and "}" in value
        ):
            return 2, lines[selected_line - 1]
        return 0, lines[selected_line - 1]
    return 0, ""


def _csharp_method_source_spans(lines: list[str]) -> tuple[dict[str, object], ...]:
    """Return non-overlapping complete C# method source spans."""

    spans: list[dict[str, object]] = []
    occupied_through = 0
    declaration_state = "code"
    for index, line in enumerate(lines):
        initial_state = declaration_state
        _, declaration_state = _csharp_brace_delta(line, initial_state=declaration_state)
        if index + 1 <= occupied_through or initial_state != "code":
            continue
        match = _CSHARP_METHOD_RE.fullmatch(line.strip())
        if match is None:
            continue
        if match.group("expression_body") and not _single_csharp_statement_line(line):
            continue
        depth = 0
        entered_body = False
        lexical_state = "code"
        end_line: int | None = index + 1 if match.group("expression_body") else None
        if end_line is None:
            for body_index in range(index, len(lines)):
                brace_delta, lexical_state = _csharp_brace_delta(
                    lines[body_index],
                    initial_state=lexical_state,
                )
                depth += brace_delta
                if depth > 0:
                    entered_body = True
                elif entered_body:
                    end_line = body_index + 1
                    break
        if end_line is None:
            continue
        start_line = index + 1
        spans.append(
            {
                "method_name": match.group("method_name"),
                "start_line": start_line,
                "end_line": end_line,
                "source_text": "".join(lines[index:end_line]),
            }
        )
        occupied_through = end_line
    return tuple(spans)


def _nearest_csharp_type(lines: list[str], *, before_line: int) -> str | None:
    nearest_type = None
    lexical_state = "code"
    for line in lines[: max(0, before_line)]:
        if lexical_state == "code":
            match = _CSHARP_TYPE_RE.match(line.strip())
            if match is not None:
                nearest_type = match.group("type_name")
        _, lexical_state = _csharp_brace_delta(line, initial_state=lexical_state)
    return nearest_type


def _nearest_csharp_namespace(lines: list[str], *, before_line: int) -> str | None:
    for index in range(min(before_line, len(lines)) - 1, -1, -1):
        value = lines[index].strip()
        match = _CSHARP_FILE_SCOPED_NAMESPACE_RE.match(value)
        if match is None:
            match = _CSHARP_BLOCK_NAMESPACE_RE.match(value)
        if match is not None:
            return match.group("namespace")
    return None


def _declared_csharp_member_types(
    lines: list[str],
    *,
    declaring_type: str,
) -> dict[str, str]:
    """Extract exact field/property types at one containing C# type level."""

    namespace = _nearest_csharp_namespace(lines, before_line=len(lines))
    declaring_type_full_name = (
        f"{namespace}.{declaring_type}" if namespace is not None else declaring_type
    )
    return {
        name: str(identity["declared_type"])
        for name, identity in _declared_csharp_members(
            lines,
            declaring_type=declaring_type,
            declaring_type_full_name=declaring_type_full_name,
        ).items()
    }


def _declared_csharp_members(
    lines: list[str],
    *,
    declaring_type: str,
    declaring_type_full_name: str,
) -> dict[str, dict[str, object]]:
    """Extract source-bound class-level member declarations for one C# type."""

    declaration_index: int | None = None
    lexical_state = "code"
    for index, line in enumerate(lines):
        if lexical_state == "code":
            match = _CSHARP_TYPE_RE.match(line.strip())
            if match is not None and match.group("type_name") == declaring_type:
                declaration_index = index
                break
        _, lexical_state = _csharp_brace_delta(line, initial_state=lexical_state)
    if declaration_index is None:
        return {}

    members: dict[str, dict[str, object]] = {}
    brace_depth = 0
    entered_type = False
    lexical_state = "code"
    for line_index, line in enumerate(
        lines[declaration_index:],
        start=declaration_index + 1,
    ):
        if entered_type and brace_depth == 1 and lexical_state == "code":
            match = _CSHARP_MEMBER_DECLARATION_RE.match(line.strip())
            if match is not None:
                member_name = match.group("member_name")
                declared_type = re.sub(r"\s+", "", match.group("declared_type"))
                identity = {
                    "member_name": member_name,
                    "member_kind": (
                        "property"
                        if match.group("declaration_suffix") == "{"
                        else "field"
                    ),
                    "declared_type": declared_type,
                    "declaring_type": declaring_type_full_name,
                    "declaration_span": {
                        "start_line": line_index,
                        "end_line": line_index,
                    },
                    "is_static": bool(
                        re.search(
                            r"\bstatic\b",
                            line.strip()[: match.start("declared_type")],
                        )
                    ),
                }
                previous = members.get(member_name)
                if previous is None or previous == identity:
                    members[member_name] = identity
                else:
                    members.pop(member_name, None)
        brace_delta, lexical_state = _csharp_brace_delta(
            line,
            initial_state=lexical_state,
        )
        brace_depth += brace_delta
        if brace_depth > 0:
            entered_type = True
        elif entered_type:
            break
    return dict(sorted(members.items()))


def _single_csharp_statement_line(value: str) -> bool:
    semicolons: list[int] = []
    _csharp_brace_delta(value, initial_state="code", code_semicolons=semicolons)
    return len(semicolons) == 1 and not value[semicolons[0] + 1 :].strip()


def _csharp_brace_delta(
    value: str,
    *,
    initial_state: str,
    code_semicolons: list[int] | None = None,
) -> tuple[int, str]:
    """Count structural braces while ignoring C# comments and string literals."""

    delta = 0
    index = 0
    state = initial_state
    while index < len(value):
        current = value[index]
        following = value[index + 1] if index + 1 < len(value) else ""
        if state == "code":
            if current == "/" and following == "/":
                break
            if current == "/" and following == "*":
                state = "block_comment"
                index += 2
                continue
            if current == '"':
                state = "verbatim_string" if index > 0 and value[index - 1] == "@" else "string"
                index += 1
                continue
            if current == "'":
                state = "character"
                index += 1
                continue
            if current == "{":
                delta += 1
            elif current == "}":
                delta -= 1
            elif current == ";" and code_semicolons is not None:
                code_semicolons.append(index)
            index += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                state = "code"
                index += 2
            else:
                index += 1
            continue
        if state == "verbatim_string":
            if current == '"' and following == '"':
                index += 2
            elif current == '"':
                state = "code"
                index += 1
            else:
                index += 1
            continue
        if current == "\\":
            index += 2
            continue
        if (state == "string" and current == '"') or (
            state == "character" and current == "'"
        ):
            state = "code"
        index += 1
    return delta, state
