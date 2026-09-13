"""Adapt the existing symbol/BM25 index to current-source Findings inputs.

The index chooses locations. Current file bytes supply the complete source
facts, and the existing Findings owner alone decides requirement coverage.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from src.core.trace.execution_trace import trace_operation
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.knowledge.indexer import RETRIEVAL_SNAPSHOT_VERSION
from src.mod_agent.upstream_trace import material_identities, payload_sha256, update_observation

from .models import EvidencePack, EvidenceRequest, missing_evidence_from_blockers
from .retriever import DeterministicEvidenceRetriever
from .rg_live import _rank_distinct_match_lines, materialize_source_location


class IndexedSourceEvidenceProvider:
    """One run-local, source-only adapter; no model, embeddings or extra queries."""

    def __init__(self, workspace_root: str | Path, index_root: str | Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.index_root = Path(index_root).resolve()
        if not self.index_root.is_relative_to(self.workspace_root):
            raise ValueError("INDEXED_SOURCE_INDEX_ROOT_OUTSIDE_WORKSPACE")
        self.database: KnowledgeDatabase | None = None
        self._source_root: Path | None = None
        self._registry: SourceRegistry | None = None
        self._indexer: IncrementalIndexer | None = None
        self._retriever: DeterministicEvidenceRetriever | None = None
        self._source_id = "run_request_source"
        self._collection_id = "run_request_source"

    def _prepare_snapshot(self, search_root):
        # The old version normalizes physical file bytes and cannot supply the
        # source hash contract required by Product Findings and Planning.
        if RETRIEVAL_SNAPSHOT_VERSION != "bounded_source_chunks_v2":
            raise ValueError("INDEXED_SOURCE_PHYSICAL_SNAPSHOT_REQUIRED")
        relative = Path(search_root)
        selected = (self.workspace_root / relative).resolve()
        if (relative.is_absolute() or len(relative.parts) != 2
                or relative.parts[0] != "generated_mods" or ".." in relative.parts
                or not selected.is_relative_to(self.workspace_root) or not selected.is_dir()
                or self.index_root.is_relative_to(selected)):
            raise ValueError("INDEXED_SOURCE_SCOPE_INVALID")
        if self._source_root is not None and selected != self._source_root:
            raise ValueError("INDEXED_SOURCE_SCOPE_CHANGED")
        if self.database is None:
            self.database = KnowledgeDatabase(self.index_root / "knowledge.db")
            self._source_root = selected
            self._registry = SourceRegistry(self.database)
            self._registry.register(SourceDefinition(source_id=self._source_id,
                source_type="target_source", root_path=selected,
                allowed_extensions=frozenset({".cs"}), include_generated_mods=True))
            self._indexer = IncrementalIndexer(database=self.database, source_registry=self._registry)
            self._retriever = DeterministicEvidenceRetriever(database=self.database,
                collection_id=self._collection_id, dense_enabled=False)
        source_hash = self._registry.source_content_hash(self._source_id)
        report = self._indexer.index_source(self._source_id)
        if not report.scan_completed or report.failed_files or report.total_files == 0:
            raise ValueError("INDEXED_SOURCE_INDEXING_FAILED")
        version = self._indexer.build_retrieval_snapshot(self._source_id, collection_id=self._collection_id)
        if self._registry.source_content_hash(self._source_id) != source_hash:
            raise ValueError("INDEXED_SOURCE_CHANGED_DURING_RETRIEVAL")
        return source_hash, version

    def _materialize_hit(self, hit, query, max_items):
        if hit.source_type != "target_source" or hit.retrieval_method not in {"symbol_exact", "bm25"}:
            return []
        relative = Path(hit.source_path)
        path = (self._source_root / relative).resolve()
        if (relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(self._source_root)
                or path.suffix != ".cs" or not path.is_file()):
            raise ValueError("INDEXED_SOURCE_HIT_PATH_INVALID")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != hit.source_hash:
            raise ValueError("INDEXED_SOURCE_HIT_HASH_MISMATCH")
        lines = raw.decode("utf-8").splitlines(keepends=True)
        span = hit.span
        if (not isinstance(span, dict) or type(span.get("start_line")) is not int
                or type(span.get("end_line")) is not int
                or not 1 <= span["start_line"] <= span["end_line"] <= len(lines)):
            raise ValueError("INDEXED_SOURCE_HIT_SPAN_INVALID")
        terms = [term.lower() for term in self._retriever._terms(query)]
        matches = tuple((number, lines[number - 1])
            for number in range(span["start_line"], span["end_line"] + 1)
            if (hit.symbol in lines[number - 1] if hit.retrieval_method == "symbol_exact" and hit.symbol
                else any(term in lines[number - 1].lower() for term in terms)))
        if not matches:
            raise ValueError("INDEXED_SOURCE_HIT_TEXT_MISMATCH")
        facts = []
        for number in _rank_distinct_match_lines(matches, terms, lines=lines)[:max_items]:
            live = materialize_source_location(workspace_root=self.workspace_root, selected_path=path,
                selected_line=number, source_bytes=raw, tokens=[])
            identity = f"{live.source_path}:{live.source_hash}:{live.span['start_line']}:{live.span['end_line']}"
            facts.append(replace(live,
                evidence_id="indexed_source_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16],
                retrieval_method="indexed_source", score=1.0,
                symbol=live.symbol if live.declaring_type is not None else None,
                claim_supported="Indexed lookup resolved this exact current source span; requirement coverage remains unassessed."))
        return facts

    def collect_query_set(self, *, queries, search_root, max_items):
        if (not isinstance(queries, tuple) or not queries or len(queries) > 64
                or type(max_items) is not int or max_items < len(queries)):
            raise ValueError("INDEXED_SOURCE_QUERY_SET_BUDGET_INVALID")
        seen_queries = set()
        for query in queries:
            if (not isinstance(query, dict) or set(query) != {"query_id", "query", "requirement_id"}
                    or any(type(query[key]) is not str or not query[key].strip() for key in query)
                    or query["query_id"] in seen_queries):
                raise ValueError("INDEXED_SOURCE_QUERY_SET_ENTRY_INVALID")
            seen_queries.add(query["query_id"])
        started = perf_counter()
        with trace_operation("evidence.indexed_source_snapshot", attributes={"source_scope": str(search_root)}) as span:
            source_hash, version = self._prepare_snapshot(search_root)
            update_observation(span, source_snapshot_sha256=source_hash, index_version=version.index_version,
                collection_id=version.collection_id, snapshot_schema_version=RETRIEVAL_SNAPSHOT_VERSION)
        lanes, rows = [], []
        for query in queries:
            with trace_operation("evidence.source_query", kind="tool", attributes={
                    "input_payload_sha256": payload_sha256(query), "provider": "indexed_source",
                    "query_sha256": hashlib.sha256(query["query"].encode("utf-8")).hexdigest(),
                    "tool_dispatch_performed": False}) as span:
                if not self._retriever._terms(query["query"]):
                    raise ValueError("INDEXED_SOURCE_QUERY_TERMS_MISSING")
                result = self._retriever.retrieve(EvidenceRequest(query=query["query"],
                    requires_hook_evidence=False, source_ids=(self._source_id,), max_items=max_items),
                    lane_max_items=max_items)
                coverage = result.budget_summary["deterministic_lane_coverage"]
                if any(row["status"] == "failed" for row in coverage if row["lane"] in {"symbol_metadata", "sparse_bm25"}):
                    raise ValueError("INDEXED_SOURCE_RETRIEVAL_FAILED")
                facts, indexed_hits = {}, []
                for hit in result.items:
                    if hit.retrieval_method not in {"symbol_exact", "bm25"}:
                        continue
                    materialized = self._materialize_hit(hit, query["query"], max_items)
                    for fact in materialized:
                        if fact.evidence_id in facts and facts[fact.evidence_id] != fact:
                            raise ValueError("INDEXED_SOURCE_FACT_IDENTITY_CONFLICT")
                        if len(facts) < max_items:
                            facts[fact.evidence_id] = fact
                    indexed_hits.append({"evidence_id": hit.evidence_id, "retrieval_method": hit.retrieval_method,
                        "score": hit.score, "chunk_id": hit.chunk_id, "source_hash": hit.source_hash,
                        "span": dict(hit.span), "materialized_evidence_ids": [item.evidence_id for item in materialized]})
                lane = tuple(facts.values())
                status = "source_observations_returned" if lane else "no_matches"
                lanes.append(lane)
                rows.append({"query_id": query["query_id"], "requirement_id": query["requirement_id"],
                    "query_sha256": hashlib.sha256(query["query"].encode("utf-8")).hexdigest(),
                    "retrieval_status": status, "indexed_hits": indexed_hits,
                    "deterministic_lane_coverage": coverage})
                update_observation(span, tool_dispatch_performed=True, retrieval_status=status,
                    produced_materials=material_identities(lane), evidence_item_count=len(lane),
                    index_version=version.index_version)
        selected = {}
        for lane in lanes:
            if lane:
                selected.setdefault(lane[0].evidence_id, lane[0])
        for lane in lanes:
            for fact in lane:
                if len(selected) < max_items:
                    selected.setdefault(fact.evidence_id, fact)
        for row, lane in zip(rows, lanes, strict=True):
            row["evidence_ids"] = [fact.evidence_id for fact in lane if fact.evidence_id in selected]
        if self._registry.source_content_hash(self._source_id) != source_hash:
            raise ValueError("INDEXED_SOURCE_CHANGED_DURING_RETRIEVAL")
        blocker = {"code": "INDEXED_SOURCE_REQUIREMENT_COVERAGE_UNPROVEN",
            "message": "Indexed source retrieval does not decide requirement coverage.",
            "needed_evidence": ["explicit requirement-to-evidence findings"]}
        return EvidencePack(query="\n".join(query["query"] for query in queries),
            readiness="insufficient", can_generate_patch=False, items=tuple(selected.values()),
            gaps=("Explicit requirement coverage findings are not yet resolved.",), blockers=(blocker,),
            missing_evidence=missing_evidence_from_blockers((blocker,)),
            retrieval_methods_used=("indexed_source", "symbol_exact", "bm25"),
            disabled_modes={"dense": "Not selected for indexed-source product retrieval.",
                "fusion": "Not selected for indexed-source product retrieval.",
                "rerank": "Not selected for indexed-source product retrieval."},
            timing={"total_ms": (perf_counter() - started) * 1000},
            budget_summary={"query_count": len(queries), "max_items": max_items,
                "per_query_execution": rows, "all_queries_executed": True, "dense_enabled": False,
                "indexed_source": {"collection_id": version.collection_id, "index_version": version.index_version,
                    "snapshot_schema_version": RETRIEVAL_SNAPSHOT_VERSION, "source_snapshot_sha256": source_hash}},
            message="Current source bytes were retrieved through the existing symbol/BM25 index; Findings remain required.")
