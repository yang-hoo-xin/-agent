"""Deterministic Evidence RAG retrieval from the local Knowledge Base."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from src.mod_agent.knowledge import (
    BM25Hit,
    BM25Indexer,
    CollectionResolver,
    KnowledgeChunkRecord,
    KnowledgeDatabase,
    SourceRecord,
    SymbolIndexEntry,
    SymbolIndexer,
    chunk_record_from_knowledge_chunk,
    SymbolRecord,
    evidence_identity_from_metadata,
)
from src.mod_agent.performance import OperationUsage, PerformanceBudgetPolicy
from src.core.query_engine.tokenization import tokenize_retrieval_text

from .dense import DenseRetrievalHit, DenseRetrievalProvider, DisabledDenseRetrievalProvider
from .models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EvidenceItem,
    EvidencePack,
    EvidenceRequest,
    LEGACY_RAG_AUXILIARY_AUTHORITY,
    missing_evidence_from_blockers,
)
from .readiness import EvidenceReadinessClassifier

_TEXT_EXTENSIONS = frozenset(
    {".cs", ".json", ".yaml", ".yml", ".md", ".txt", ".log", ".cfg"}
)
_CODE_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*\b")
_CODE_IDENTIFIER_PART_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+"
)
_SOURCE_IDENTIFIER_STOPWORDS = frozenset(
    {
        "abstract",
        "base",
        "bool",
        "class",
        "collections",
        "default",
        "enum",
        "generic",
        "false",
        "float",
        "internal",
        "mono",
        "monobehaviour",
        "namespace",
        "new",
        "null",
        "override",
        "private",
        "protected",
        "public",
        "return",
        "sealed",
        "setup",
        "static",
        "string",
        "system",
        "true",
        "unityengine",
        "using",
        "vector",
        "vector3",
        "virtual",
        "void",
    }
)


class DeterministicEvidenceRetriever:
    """Retrieve symbol and text evidence without LLM calls."""

    def __init__(
        self,
        database: KnowledgeDatabase,
        readiness_classifier: EvidenceReadinessClassifier | None = None,
        bm25_indexer: BM25Indexer | None = None,
        symbol_indexer: SymbolIndexer | None = None,
        collection_id: str | None = None,
        collection_resolver: CollectionResolver | None = None,
        dense_provider: DenseRetrievalProvider | None = None,
        dense_enabled: bool = False,
        dense_required: bool = False,
        dense_top_k: int | None = None,
        performance_policy: PerformanceBudgetPolicy | None = None,
    ) -> None:
        self.database = database
        self.readiness_classifier = readiness_classifier or EvidenceReadinessClassifier()
        self.bm25_indexer = bm25_indexer or BM25Indexer(database)
        self.symbol_indexer = symbol_indexer or SymbolIndexer()
        resolution = (collection_resolver or CollectionResolver()).resolve(collection_id)
        self.collection_id = resolution.collection_id
        self.dense_provider = dense_provider or DisabledDenseRetrievalProvider()
        self.dense_enabled = dense_enabled
        self.dense_required = dense_required
        self.dense_top_k = dense_top_k
        self.performance_policy = performance_policy

    def retrieve(
        self,
        request: EvidenceRequest,
        *,
        preverified_items: tuple[EvidenceItem, ...] = (),
        preverified_lane_coverage: tuple[dict[str, object], ...] = (),
        lane_max_items: int | None = None,
    ) -> EvidencePack:
        """Retrieve evidence and classify readiness."""

        if lane_max_items is not None and lane_max_items <= 0:
            raise ValueError("lane_max_items must be positive when provided.")

        total_started = perf_counter()
        query_started = perf_counter()
        terms = self._request_terms(request)
        query_processing_ms = _elapsed_ms(query_started)
        if not terms:
            pack = EvidencePack.empty(
                query=request.query,
                reason="Request did not contain searchable identifiers or terms.",
            )
            return self._with_observability(
                pack,
                query_processing_ms=query_processing_ms,
                symbol_ms=0.0,
                bm25_ms=0.0,
                text_ms=0.0,
                readiness_ms=0.0,
                total_ms=_elapsed_ms(total_started),
                excluded_count=0,
                symbol_count=0,
                bm25_count=0,
                dense_count=0,
                text_count=0,
                bm25_disabled_reason=(
                    "BM25 was not queried because the request had no searchable terms."
                ),
                dense_ms=0.0,
                dense_disabled_reason=(
                    "Dense retrieval was not queried because the request had no searchable terms."
                ),
                dense_required=self.dense_required,
                dense_budget_summary={},
                dense_trace_refs=(),
                lane_coverage=(),
            )

        sources = self._source_map()
        allowed_source_ids = set(request.source_ids or sources)
        items: list[EvidenceItem] = list(preverified_items)
        excluded: list[dict[str, object]] = []
        seen: set[str] = {item.evidence_id for item in preverified_items}
        lane_coverage: list[dict[str, object]] = [
            dict(item) for item in preverified_lane_coverage
        ]

        lane_limit = min(request.max_items, lane_max_items or request.max_items)
        symbol_started = perf_counter()
        symbol_pool: list[EvidenceItem] = []
        symbol_seen: set[str] = set()
        symbol_pool_limit = min(256, max(32, lane_limit * 64))
        stable_version = self.database.stable_index_version(self.collection_id)
        if stable_version is not None:
            for item in self._symbol_index_items(
                terms=terms,
                sources=sources,
                allowed_source_ids=allowed_source_ids,
                index_version=stable_version.index_version,
                max_items=symbol_pool_limit,
            ):
                if item.evidence_id not in symbol_seen:
                    symbol_pool.append(item)
                    symbol_seen.add(item.evidence_id)
        for term in terms:
            for symbol in self.database.search_symbols(term, limit=symbol_pool_limit):
                if symbol.source_id not in allowed_source_ids:
                    excluded.append(
                        {
                            "source_path": symbol.source_path,
                            "reason": "source_id_not_requested",
                            "source_id": symbol.source_id,
                        }
                    )
                    continue
                item = self._symbol_item(symbol, sources)
                if item.evidence_id not in symbol_seen:
                    symbol_pool.append(item)
                    symbol_seen.add(item.evidence_id)
        symbol_items = sorted(
            symbol_pool,
            key=lambda item: self._symbol_query_relevance_key(item, terms),
        )[:lane_limit]
        for item in symbol_items:
            if item.evidence_id not in seen and len(items) < request.max_items:
                items.append(item)
                seen.add(item.evidence_id)
        symbol_ms = _elapsed_ms(symbol_started)
        symbol_count = len(symbol_items)
        lane_coverage.append(
            self._lane_coverage(
                lane="symbol_metadata",
                hit_count=symbol_count,
                status=("searched_with_results" if symbol_count else "searched_and_absent"),
                source_ids=allowed_source_ids,
            )
        )

        bm25_started = perf_counter()
        bm25_disabled_reason = ""
        bm25_count = 0
        bm25_items, bm25_disabled_reason = self._bm25_items(
            terms=terms,
            sources=sources,
            allowed_source_ids=allowed_source_ids,
            max_items=lane_limit,
        )
        for item in bm25_items:
            if item.evidence_id not in seen and len(items) < request.max_items:
                items.append(item)
                seen.add(item.evidence_id)
        bm25_count = len(bm25_items)
        bm25_ms = _elapsed_ms(bm25_started)
        lane_coverage.append(
            self._lane_coverage(
                lane="sparse_bm25",
                hit_count=bm25_count,
                status=(
                    "failed"
                    if bm25_disabled_reason
                    else "searched_with_results"
                    if bm25_count
                    else "searched_and_absent"
                ),
                source_ids=allowed_source_ids,
                failure=bm25_disabled_reason or None,
            )
        )

        dense_started = perf_counter()
        dense_items: list[EvidenceItem] = []
        dense_disabled_reason = ""
        dense_budget_summary: dict[str, object] = {}
        dense_trace_refs: tuple[str, ...] = ()
        if self.dense_enabled:
            (
                dense_items,
                dense_disabled_reason,
                dense_budget_summary,
                dense_trace_refs,
            ) = self._dense_items(
                query=request.query,
                sources=sources,
                allowed_source_ids=allowed_source_ids,
                index_version=stable_version.index_version if stable_version else None,
                max_items=request.max_items,
            )
            for item in dense_items:
                if item.evidence_id not in seen and len(items) < request.max_items:
                    items.append(item)
                    seen.add(item.evidence_id)
        else:
            dense_report = DisabledDenseRetrievalProvider().retrieve(
                query=request.query,
                chunks=(),
                top_k=0,
            )
            dense_disabled_reason = dense_report.disabled_reason
            dense_budget_summary = {"dense_retrieval": dense_report.usage_dict()}
        dense_ms = _elapsed_ms(dense_started)
        lane_coverage.append(
            self._lane_coverage(
                lane="dense",
                hit_count=len(dense_items),
                status=(
                    "not_searched"
                    if not self.dense_enabled
                    else "failed"
                    if dense_disabled_reason
                    else "searched_with_results"
                    if dense_items
                    else "searched_and_absent"
                ),
                source_ids=allowed_source_ids,
                failure=dense_disabled_reason or None,
            )
        )

        text_started = perf_counter()
        text_count = 0
        text_items = self._text_items(
            terms=terms,
            sources=sources,
            allowed_source_ids=allowed_source_ids,
            max_items=lane_limit,
        )
        for item in text_items:
            if item.evidence_id not in seen and len(items) < request.max_items:
                items.append(item)
                seen.add(item.evidence_id)
        text_count = len(text_items)
        text_ms = _elapsed_ms(text_started)
        lane_coverage.append(
            self._lane_coverage(
                lane="live_text",
                hit_count=text_count,
                status=("searched_with_results" if text_count else "searched_and_absent"),
                source_ids=allowed_source_ids,
            )
        )

        readiness_started = perf_counter()
        pack = self.readiness_classifier.classify(
            request=request,
            items=items[: request.max_items],
            excluded=excluded,
            lane_coverage=tuple(lane_coverage),
        )
        readiness_ms = _elapsed_ms(readiness_started)
        return self._with_observability(
            pack,
            query_processing_ms=query_processing_ms,
            symbol_ms=symbol_ms,
            bm25_ms=bm25_ms,
            text_ms=text_ms,
            readiness_ms=readiness_ms,
            total_ms=_elapsed_ms(total_started),
            excluded_count=len(excluded),
            symbol_count=symbol_count,
            bm25_count=bm25_count,
            dense_count=len(dense_items),
            text_count=text_count,
            bm25_disabled_reason=bm25_disabled_reason,
            dense_ms=dense_ms,
            dense_disabled_reason=dense_disabled_reason,
            dense_required=self.dense_required,
            dense_budget_summary=dense_budget_summary,
            dense_trace_refs=dense_trace_refs,
            lane_coverage=tuple(lane_coverage),
        )

    def retrieve_query_set(
        self,
        *,
        queries: tuple[dict[str, str], ...],
        source_ids: tuple[str, ...],
        per_query_lane_max_items: int = 3,
        max_items: int = 36,
        _expand_observed_identifiers: bool = True,
    ) -> EvidencePack:
        """Run each source-discovery query independently and merge bounded facts."""

        if not queries:
            raise ValueError("Source query set must not be empty.")
        if per_query_lane_max_items <= 0 or max_items <= 0:
            raise ValueError("Source query-set budgets must be positive.")
        seen_query_ids: set[str] = set()
        admitted_items: list[EvidenceItem] = []
        admitted_ids: set[str] = set()
        excluded: list[dict[str, object]] = []
        lane_facts: list[dict[str, object]] = []
        bounded_items_by_query_and_lane: dict[
            tuple[int, str], list[EvidenceItem]
        ] = {}
        disabled_modes: dict[str, str] = {}
        timing: dict[str, float] = {}
        lane_methods = {
            "symbol_metadata": "symbol_exact",
            "sparse_bm25": "bm25",
            "live_text": "text_match",
            "dense": "dense",
        }
        lane_order = tuple(lane_methods)

        for query_index, query_input in enumerate(queries):
            if set(query_input) != {"query_id", "origin", "query"}:
                raise ValueError("Source query input shape is invalid.")
            query_id = query_input["query_id"].strip()
            origin = query_input["origin"].strip()
            query = query_input["query"].strip()
            if not query_id or not origin or not query or query_id in seen_query_ids:
                raise ValueError("Source query identity or text is invalid.")
            seen_query_ids.add(query_id)
            pack = self.retrieve(
                EvidenceRequest(
                    query=query,
                    requires_hook_evidence=True,
                    source_ids=source_ids,
                    max_items=per_query_lane_max_items * 3,
                    hook_requirement={
                        "required": True,
                        "reason": "bounded_source_vocabulary_discovery",
                    },
                ),
                lane_max_items=per_query_lane_max_items,
            )
            excluded.extend(dict(item) for item in pack.excluded)
            disabled_modes.update(pack.disabled_modes)
            for key, value in pack.timing.items():
                timing[key] = round(timing.get(key, 0.0) + float(value), 3)
            coverage_by_lane = {
                str(item.get("lane")): item
                for item in pack.budget_summary.get(
                    "deterministic_lane_coverage", []
                )
                if isinstance(item, dict)
            }
            for lane in lane_order:
                method = lane_methods[lane]
                bounded_items = [
                    item for item in pack.items if item.retrieval_method == method
                ]
                bounded_refs = [item.evidence_id for item in bounded_items]
                bounded_items_by_query_and_lane[(query_index, lane)] = bounded_items
                coverage = coverage_by_lane.get(lane, {})
                bounded_hit_count = int(coverage.get("hit_count", len(bounded_refs)))
                lane_facts.append(
                    {
                        "query_index": query_index,
                        "query_id": query_id,
                        "query_origin": origin,
                        "query": query,
                        "lane": lane,
                        "status": coverage.get("status", "not_searched"),
                        "source_ids": list(source_ids),
                        "bounded_hit_count": bounded_hit_count,
                        "bounded_evidence_refs": bounded_refs,
                        "deduplicated_count": 0,
                        "truncated_count": 0,
                        "admitted_count": 0,
                        "admitted_evidence_refs": [],
                        "result_limit": per_query_lane_max_items,
                        "result_limit_reached": (
                            bounded_hit_count >= per_query_lane_max_items
                        ),
                        "failure": coverage.get("failure"),
                    }
                )

        facts_by_query_and_lane = {
            (int(fact["query_index"]), str(fact["lane"])): fact
            for fact in lane_facts
        }
        # Apply the global budget only after every query/lane has produced its
        # bounded result.  Rank -> lane -> query ordering gives every non-empty
        # query/lane bucket one opportunity before any bucket contributes its
        # second item; source index order therefore cannot starve later queries.
        for item_rank in range(per_query_lane_max_items):
            for lane in lane_order:
                for query_index in range(len(queries)):
                    bounded_items = bounded_items_by_query_and_lane.get(
                        (query_index, lane), []
                    )
                    if item_rank >= len(bounded_items):
                        continue
                    item = bounded_items[item_rank]
                    fact = facts_by_query_and_lane[(query_index, lane)]
                    if item.evidence_id in admitted_ids:
                        fact["deduplicated_count"] = (
                            int(fact["deduplicated_count"]) + 1
                        )
                        continue
                    if len(admitted_items) >= max_items:
                        fact["truncated_count"] = int(fact["truncated_count"]) + 1
                        continue
                    admitted_items.append(item)
                    admitted_ids.add(item.evidence_id)
                    admitted_refs = fact["admitted_evidence_refs"]
                    if not isinstance(admitted_refs, list):
                        raise RuntimeError("Source query admission facts are invalid.")
                    admitted_refs.append(item.evidence_id)
                    fact["admitted_count"] = int(fact["admitted_count"]) + 1

        identifier_records: list[dict[str, object]] = []
        expansion_execution: list[dict[str, object]] = []
        expansion_item_ids: list[str] = []
        combined_max_items = max_items
        if _expand_observed_identifiers and admitted_items:
            identifier_records = self._observed_source_identifiers(
                tuple(admitted_items),
                max_identifiers=16,
            )
            expansion_queries = tuple(
                {
                    "query_id": (
                        f"source_identifier_{index:02d}_"
                        f"{hashlib.sha256(str(record['identifier']).encode('utf-8')).hexdigest()[:10]}"
                    ),
                    "origin": "observed_identifier_exact_reference",
                    "query": str(record["identifier"]),
                }
                for index, record in enumerate(identifier_records, start=1)
            )
            if expansion_queries:
                expansion_max_items = min(48, max_items * 2)
                expansion_pack = self.retrieve_query_set(
                    queries=expansion_queries,
                    source_ids=source_ids,
                    per_query_lane_max_items=3,
                    max_items=expansion_max_items,
                    _expand_observed_identifiers=False,
                )
                combined_max_items += expansion_max_items
                expansion_execution = list(
                    expansion_pack.budget_summary.get("source_query_execution", [])
                )
                excluded.extend(dict(item) for item in expansion_pack.excluded)
                disabled_modes.update(expansion_pack.disabled_modes)
                for key, value in expansion_pack.timing.items():
                    timing[key] = round(timing.get(key, 0.0) + float(value), 3)
                for item in expansion_pack.items:
                    if item.evidence_id in admitted_ids:
                        continue
                    if len(admitted_items) >= combined_max_items:
                        break
                    admitted_items.append(item)
                    admitted_ids.add(item.evidence_id)
                    expansion_item_ids.append(item.evidence_id)

        return EvidencePack(
            query="bounded source query set",
            readiness="partial" if admitted_items else "insufficient",
            can_generate_patch=False,
            items=tuple(admitted_items),
            excluded=tuple(excluded),
            retrieval_methods_used=tuple(
                dict.fromkeys(item.retrieval_method for item in admitted_items)
            ),
            disabled_modes=disabled_modes,
            timing=timing,
            budget_summary={
                "source_query_execution": lane_facts,
                "query_count": len(queries),
                "per_query_lane_max_items": per_query_lane_max_items,
                "max_items": max_items,
                "combined_max_items": combined_max_items,
                "admitted_item_count": len(admitted_items),
                "observed_identifier_extraction": identifier_records,
                "bounded_identifier_reference_expansion": {
                    "performed": bool(identifier_records),
                    "query_lane_execution": expansion_execution,
                    "admitted_evidence_refs": expansion_item_ids,
                    "expansion_kind": "exact_identifier_reference_and_type_lookup",
                    "expansion_depth": 1 if identifier_records else 0,
                },
            },
            message=(
                "Bounded deterministic source queries produced supporting EvidenceItems; "
                "their readiness is not planning truth."
            ),
        )

    @classmethod
    def _observed_source_identifiers(
        cls,
        items: tuple[EvidenceItem, ...],
        *,
        max_identifiers: int,
    ) -> list[dict[str, object]]:
        refs_by_identifier: dict[str, list[str]] = {}
        form_by_identifier: dict[str, str] = {}
        for item in items:
            primary_values = (
                item.symbol,
                item.declaring_type,
                item.declaring_type_full_name,
                item.method_name,
                Path(item.source_path).stem,
            )
            raw_identifiers: list[tuple[str, str]] = []
            for value in primary_values:
                if isinstance(value, str):
                    raw_identifiers.extend(
                        (identifier, "identity_field")
                        for identifier in _CODE_IDENTIFIER_RE.findall(value)
                    )
            if isinstance(item.excerpt, str):
                raw_identifiers.extend(
                    (identifier, "source_excerpt")
                    for identifier in _CODE_IDENTIFIER_RE.findall(item.excerpt)
                )
            per_item_seen: set[str] = set()
            for identifier, origin in raw_identifiers:
                for form, form_kind in cls._identifier_forms(identifier):
                    key = form.casefold()
                    if key in per_item_seen:
                        continue
                    per_item_seen.add(key)
                    refs_by_identifier.setdefault(form, []).append(item.evidence_id)
                    form_by_identifier.setdefault(
                        form,
                        origin if form_kind == "full" else f"{origin}_component",
                    )
        ranked = sorted(
            refs_by_identifier,
            key=lambda value: (
                -cls._identifier_origin_priority(form_by_identifier[value]),
                -len(cls._identifier_components(value)),
                -len(value),
                len(set(refs_by_identifier[value])),
                value.casefold(),
            ),
        )
        return [
            {
                "identifier": identifier,
                "extraction_kind": form_by_identifier[identifier],
                "source_evidence_refs": list(
                    dict.fromkeys(refs_by_identifier[identifier])
                ),
            }
            for identifier in ranked[:max_identifiers]
        ]

    @classmethod
    def observed_identifier_selection_inventory(
        cls,
        items: tuple[EvidenceItem, ...],
        *,
        max_identifiers: int,
    ) -> list[dict[str, object]]:
        """Project bounded source facts into short model-selection identities."""

        if max_identifiers <= 0:
            raise ValueError("Observed identifier inventory budget must be positive.")
        records: dict[str, dict[str, object]] = {}

        def admit(
            *,
            identifier: str,
            extraction_kind: str,
            score: int,
            item: EvidenceItem,
        ) -> None:
            normalized = identifier.strip("._")
            if (
                len(normalized) < 4
                or normalized.casefold() in _SOURCE_IDENTIFIER_STOPWORDS
            ):
                return
            record = records.setdefault(
                normalized,
                {
                    "observed_identifier": normalized,
                    "extraction_kind": extraction_kind,
                    "score": score,
                    "source_evidence_refs": [],
                    "source_paths": [],
                    "source_fact_views": [],
                },
            )
            if score > int(record["score"]):
                record["score"] = score
                record["extraction_kind"] = extraction_kind
            evidence_refs = record["source_evidence_refs"]
            source_paths = record["source_paths"]
            source_fact_views = record["source_fact_views"]
            if (
                not isinstance(evidence_refs, list)
                or not isinstance(source_paths, list)
                or not isinstance(source_fact_views, list)
            ):
                raise RuntimeError("Observed identifier inventory record is invalid.")
            if item.evidence_id not in evidence_refs:
                evidence_refs.append(item.evidence_id)
            if item.source_path not in source_paths:
                source_paths.append(item.source_path)
            source_fact = cls._bounded_identifier_source_fact(
                item.excerpt,
                identifier=normalized,
            )
            if source_fact and source_fact not in source_fact_views:
                source_fact_views.append(source_fact)

        for item in items:
            for value in (
                item.symbol,
                item.declaring_type,
                item.declaring_type_full_name,
                item.method_name,
                Path(item.source_path).stem,
            ):
                if not isinstance(value, str):
                    continue
                for identifier in _CODE_IDENTIFIER_RE.findall(value):
                    forms = cls._identifier_forms(identifier)
                    for form, form_kind in forms:
                        admit(
                            identifier=form,
                            extraction_kind=(
                                "identity_field"
                                if form_kind == "full"
                                else "identity_field_component"
                            ),
                            score=100 if form_kind == "full" else 70,
                            item=item,
                        )
            if not isinstance(item.excerpt, str):
                continue
            for identifier in _CODE_IDENTIFIER_RE.findall(item.excerpt):
                forms = cls._identifier_forms(identifier)
                component_count = len(cls._identifier_components(identifier))
                for form, form_kind in forms:
                    if form_kind == "component":
                        score = 60
                    elif "." in identifier:
                        score = 110
                    elif component_count >= 2:
                        score = 85
                    else:
                        score = 50
                    admit(
                        identifier=form,
                        extraction_kind=(
                            "source_excerpt"
                            if form_kind == "full"
                            else "source_excerpt_component"
                        ),
                        score=score,
                        item=item,
                    )

        ranked = sorted(
            records.values(),
            key=lambda record: (
                -int(record["score"]),
                len(record["source_evidence_refs"]),
                -len(cls._identifier_components(str(record["observed_identifier"]))),
                -len(str(record["observed_identifier"])),
                str(record["observed_identifier"]).casefold(),
            ),
        )
        return [
            {
                "observed_identifier": str(record["observed_identifier"]),
                "extraction_kind": str(record["extraction_kind"]),
                "source_evidence_refs": list(record["source_evidence_refs"]),
                "source_paths": list(record["source_paths"]),
                "source_fact_views": list(record["source_fact_views"]),
            }
            for record in ranked[:max_identifiers]
        ]

    @staticmethod
    def _bounded_identifier_source_fact(
        excerpt: str,
        *,
        identifier: str,
        max_characters: int = 280,
    ) -> str:
        """Return a bounded actual-source view around an observed identifier."""

        normalized = " ".join(excerpt.split())
        if len(normalized) <= max_characters:
            return normalized
        position = normalized.casefold().find(identifier.casefold())
        if position < 0:
            return normalized[:max_characters]
        start = max(0, position - (max_characters // 3))
        end = min(len(normalized), start + max_characters)
        start = max(0, end - max_characters)
        return normalized[start:end]

    @classmethod
    def _identifier_forms(cls, identifier: str) -> tuple[tuple[str, str], ...]:
        full = identifier.strip("._")
        if not full or full.casefold() in _SOURCE_IDENTIFIER_STOPWORDS:
            return ()
        forms: list[tuple[str, str]] = []
        if len(full) >= 4:
            forms.append((full, "full"))
        for component in cls._identifier_components(full):
            if (
                len(component) >= 4
                and component.casefold() not in _SOURCE_IDENTIFIER_STOPWORDS
                and component.casefold() != full.casefold()
                and all(component.casefold() != value.casefold() for value, _ in forms)
            ):
                forms.append((component, "component"))
        return tuple(forms)

    @staticmethod
    def _identifier_components(identifier: str) -> tuple[str, ...]:
        components: list[str] = []
        for segment in re.split(r"[._]+", identifier):
            components.extend(_CODE_IDENTIFIER_PART_RE.findall(segment))
        return tuple(components)

    @staticmethod
    def _identifier_origin_priority(origin: str) -> int:
        priorities = {
            "identity_field": 4,
            "source_excerpt": 3,
            "identity_field_component": 2,
            "source_excerpt_component": 1,
        }
        return priorities.get(origin, 0)

    def _symbol_item(
        self,
        symbol: SymbolRecord,
        sources: dict[str, SourceRecord],
    ) -> EvidenceItem:
        source = sources.get(symbol.source_id)
        source_type = source.source_type if source else symbol.source_id
        return EvidenceItem(
            evidence_id=symbol.symbol_id,
            source_type=source_type,
            source_path=symbol.relative_path,
            symbol=symbol.name,
            span={
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
            },
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported=f"Symbol {symbol.name} exists in {symbol.relative_path}.",
            excerpt=symbol.excerpt,
            source_hash=symbol.content_hash,
            file_hash=symbol.content_hash,
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            source_authority=self._source_authority(source),
            risk_notes=(),
        )

    @classmethod
    def _symbol_query_relevance_key(
        cls,
        item: EvidenceItem,
        terms: tuple[str, ...],
    ) -> tuple[object, ...]:
        symbol = (item.symbol or "").casefold()
        source_path = Path(item.source_path)
        stem = source_path.stem.casefold()
        directory = str(source_path.parent).replace("\\", "/").casefold()
        excerpt = item.excerpt.casefold()
        term_keys = tuple(term.casefold() for term in terms)
        exact_code_hits = sum(
            symbol == term
            for term, original in zip(term_keys, terms)
            if any(char.isupper() for char in original) or any(
                marker in original for marker in ("_", ".")
            )
        )
        stem_hits = sum(term in stem for term in term_keys)
        symbol_hits = sum(term in symbol for term in term_keys)
        exact_hits = sum(symbol == term for term in term_keys)
        excerpt_hits = sum(term in excerpt for term in term_keys)
        directory_only_hits = sum(
            term in directory
            and term not in stem
            and term not in symbol
            and term not in excerpt
            for term in term_keys
        )
        covered_terms = sum(
            term in symbol or term in stem or term in excerpt
            for term in term_keys
        )
        return (
            -covered_terms,
            -exact_code_hits,
            -stem_hits,
            -len(cls._identifier_components(source_path.stem)),
            -symbol_hits,
            -exact_hits,
            -excerpt_hits,
            directory_only_hits,
            item.source_path.casefold(),
            symbol,
            item.evidence_id,
        )

    def _symbol_index_items(
        self,
        *,
        terms: tuple[str, ...],
        sources: dict[str, SourceRecord],
        allowed_source_ids: set[str],
        index_version: str,
        max_items: int,
    ) -> list[EvidenceItem]:
        if max_items <= 0:
            return []
        entries: list[SymbolIndexEntry] = []
        for term in terms:
            entries.extend(
                self.symbol_indexer.search_chunk_symbols(
                    self.database,
                    collection_id=self.collection_id,
                    index_version=index_version,
                    symbol=term,
                    limit=max_items,
                )
            )
            if len(entries) >= max_items:
                break
        chunk_map = self.database.chunks_by_id(
            collection_id=self.collection_id,
            index_version=index_version,
            chunk_ids=tuple(entry.chunk_id for entry in entries),
        )
        items: list[EvidenceItem] = []
        seen_entries: set[tuple[str, str, str]] = set()
        for entry in entries:
            source_id = str(entry.metadata.get("source_id", ""))
            if source_id not in allowed_source_ids:
                continue
            key = (entry.symbol, entry.symbol_kind, entry.chunk_id)
            if key in seen_entries:
                continue
            seen_entries.add(key)
            items.append(
                self._symbol_index_item(
                    entry=entry,
                    chunk=chunk_map.get(entry.chunk_id),
                    sources=sources,
                )
            )
            if len(items) >= max_items:
                break
        return items

    def _symbol_index_item(
        self,
        *,
        entry: SymbolIndexEntry,
        chunk: KnowledgeChunkRecord | None,
        sources: dict[str, SourceRecord],
    ) -> EvidenceItem:
        source_id = str(entry.metadata.get("source_id", ""))
        source = sources.get(source_id)
        source_type = source.source_type if source else str(
            entry.metadata.get("source_type", source_id)
        )
        span = None
        if entry.start_line is not None and entry.end_line is not None:
            span = {"start_line": entry.start_line, "end_line": entry.end_line}
        seed = f"{entry.index_version}:{entry.chunk_id}:{entry.symbol}:{entry.symbol_kind}"
        evidence_id = "symidx_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        excerpt = chunk.chunk_text.strip()[:240] if chunk else entry.symbol
        identity = evidence_identity_from_metadata(entry.metadata)
        if chunk is not None:
            identity["chunk_id"] = chunk.chunk_id
            identity["document_id"] = chunk.document_id
        return EvidenceItem(
            evidence_id=evidence_id,
            source_type=source_type,
            source_path=str(entry.metadata.get("relative_path", entry.source_path)),
            symbol=entry.symbol,
            span=span,
            retrieval_method="symbol_exact",
            score=1.0,
            claim_supported=(
                f"Symbol {entry.symbol} exists in chunk {entry.chunk_id} "
                f"for index version {entry.index_version}."
            ),
            excerpt=excerpt,
            **identity,
            usage=_optional_str(entry.metadata.get("usage")),
            declaring_type=_optional_str(entry.metadata.get("declaring_type")),
            method_name=_optional_str(entry.metadata.get("method_name")),
            parameter_types=_optional_str_tuple(entry.metadata.get("parameter_types")),
            return_type=_optional_str(entry.metadata.get("return_type")),
            method_kind=_optional_str(entry.metadata.get("method_kind")),
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            source_authority=self._source_authority(source),
            risk_notes=(),
        )

    def _bm25_items(
        self,
        *,
        terms: tuple[str, ...],
        sources: dict[str, SourceRecord],
        allowed_source_ids: set[str],
        max_items: int,
    ) -> tuple[list[EvidenceItem], str]:
        if max_items <= 0:
            return ([], "")
        stable_version = self.database.stable_index_version(self.collection_id)
        if stable_version is None:
            return (
                [],
                f"No stable BM25 index version exists for collection {self.collection_id}.",
            )
        hits = self.bm25_indexer.query(
            collection_id=self.collection_id,
            index_version=stable_version.index_version,
            tokens=list(terms),
            top_k=max_items,
        )
        items: list[EvidenceItem] = []
        excluded = 0
        for hit in hits:
            source_id = str(hit.metadata.get("source_id", ""))
            if source_id not in allowed_source_ids:
                excluded += 1
                continue
            items.append(self._bm25_item(hit, sources))
            if len(items) >= max_items:
                break
        if not items and excluded:
            return ([], "BM25 hits were excluded by requested source_ids.")
        return (items, "")

    def _bm25_item(
        self,
        hit: BM25Hit,
        sources: dict[str, SourceRecord],
    ) -> EvidenceItem:
        source_id = str(hit.metadata.get("source_id", ""))
        source = sources.get(source_id)
        source_type = source.source_type if source else str(
            hit.metadata.get("source_type", source_id)
        )
        hit_terms = ", ".join(hit.hit_terms)
        return EvidenceItem(
            evidence_id=f"bm25_{hit.chunk_id}",
            source_type=source_type,
            source_path=str(hit.metadata.get("relative_path", hit.source_path)),
            symbol=None,
            span=hit.span,
            retrieval_method="bm25",
            score=hit.score,
            claim_supported=(
                f"BM25 lexical match found terms [{hit_terms}] "
                f"in index version {hit.index_version}."
            ),
            excerpt=hit.excerpt,
            **evidence_identity_from_metadata(hit.metadata),
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            source_authority=self._source_authority(source),
            risk_notes=(),
        )

    def _text_items(
        self,
        *,
        terms: tuple[str, ...],
        sources: dict[str, SourceRecord],
        allowed_source_ids: set[str],
        max_items: int,
    ) -> list[EvidenceItem]:
        if max_items <= 0:
            return []
        items: list[EvidenceItem] = []
        for indexed_file in self.database.list_indexed_files():
            if indexed_file.source_id not in allowed_source_ids:
                continue
            path = Path(indexed_file.source_path)
            if path.suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            match = self._first_text_match(text, terms)
            if match is None:
                continue
            line_number, excerpt = match
            source = sources.get(indexed_file.source_id)
            source_type = source.source_type if source else indexed_file.source_id
            evidence_id = self._text_evidence_id(
                indexed_file.source_id,
                indexed_file.relative_path,
                line_number,
                indexed_file.content_hash,
            )
            items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    source_type=source_type,
                    source_path=indexed_file.relative_path,
                    symbol=None,
                    span={"start_line": line_number, "end_line": line_number},
                    retrieval_method="text_match",
                    score=0.75,
                    claim_supported=(
                        f"Text match for request term exists in "
                        f"{indexed_file.relative_path}."
                    ),
                    excerpt=excerpt,
                    source_hash=indexed_file.content_hash,
                    file_hash=indexed_file.content_hash,
                    authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
                    source_authority=self._source_authority(source),
                    risk_notes=(),
                )
            )
            if len(items) >= max_items:
                break
        return items

    def _dense_items(
        self,
        *,
        query: str,
        sources: dict[str, SourceRecord],
        allowed_source_ids: set[str],
        index_version: str | None,
        max_items: int,
    ) -> tuple[list[EvidenceItem], str, dict[str, object], tuple[str, ...]]:
        if max_items <= 0:
            return ([], "", {}, ())
        if not self.dense_enabled:
            report = DisabledDenseRetrievalProvider().retrieve(
                query=query,
                chunks=(),
                top_k=0,
            )
            return (
                [],
                report.disabled_reason,
                {"dense_retrieval": report.usage_dict()},
                (),
            )
        if index_version is None:
            return (
                [],
                f"No stable dense input chunks exist for collection {self.collection_id}.",
                {
                    "dense_retrieval": {
                        "provider": getattr(self.dense_provider, "provider_name", "unknown"),
                        "enabled": True,
                        "status": "unavailable",
                    }
                },
                (),
            )

        chunks = tuple(
            chunk_record_from_knowledge_chunk(chunk)
            for chunk in self.database.list_chunks(
                collection_id=self.collection_id,
                index_version=index_version,
            )
            if str(chunk.metadata.get("source_id", "")) in allowed_source_ids
        )
        top_k = min(max_items, self.dense_top_k or max_items)
        report = self.dense_provider.retrieve(
            query=query,
            chunks=chunks,
            top_k=top_k,
        )
        usage = OperationUsage(
            operation="retrieval",
            api_calls=report.api_calls,
            item_count=report.embedded_items,
            batch_count=report.batch_count,
            cache_enabled=report.cache_enabled,
        )
        budget_summary: dict[str, object] = {
            "dense_retrieval": {
                **report.usage_dict(),
                "usage": usage.to_dict(),
                "trace_events": list(report.trace_events),
            }
        }
        if self.performance_policy is not None:
            decision = self.performance_policy.check(usage)
            budget_summary["dense_retrieval"]["budget_decision"] = decision.to_dict()
            if not decision.allowed:
                return (
                    [],
                    f"Dense retrieval budget blocked: {decision.status}.",
                    budget_summary,
                    _dense_trace_refs(report),
                )

        chunk_map = self.database.chunks_by_id(
            collection_id=self.collection_id,
            index_version=index_version,
            chunk_ids=tuple(hit.chunk_id for hit in report.hits),
        )
        items = [
            self._dense_item(
                hit=hit,
                chunk=chunk_map[hit.chunk_id],
                sources=sources,
                provider=report.provider,
            )
            for hit in report.hits
            if hit.chunk_id in chunk_map
        ]
        return (items, report.disabled_reason, budget_summary, _dense_trace_refs(report))

    def _dense_item(
        self,
        *,
        hit: DenseRetrievalHit,
        chunk: KnowledgeChunkRecord,
        sources: dict[str, SourceRecord],
        provider: str,
    ) -> EvidenceItem:
        source_id = str(chunk.metadata.get("source_id", ""))
        source = sources.get(source_id)
        source_type = source.source_type if source else str(
            chunk.metadata.get("source_type", source_id)
        )
        start_line = chunk.metadata.get("start_line")
        end_line = chunk.metadata.get("end_line")
        span = None
        if isinstance(start_line, int) and isinstance(end_line, int):
            span = {"start_line": start_line, "end_line": end_line}
        score = float(getattr(hit, "score"))
        return EvidenceItem(
            evidence_id=f"dense_{chunk.chunk_id}",
            source_type=source_type,
            source_path=str(
                chunk.metadata.get("relative_path", chunk.metadata.get("source_path", ""))
            ),
            symbol=None,
            span=span,
            retrieval_method="dense",
            score=score,
            claim_supported=(
                f"Dense provider {provider} matched chunk {chunk.chunk_id}; "
                "dense output remains auxiliary for V1 patch gates."
            ),
            excerpt=chunk.chunk_text.strip()[:240],
            **evidence_identity_from_metadata(chunk.metadata),
            authority=LEGACY_RAG_AUXILIARY_AUTHORITY,
            source_authority=self._source_authority(source),
            risk_notes=("Dense retrieval cannot approve V1 implementation gates.",),
        )

    def _source_map(self) -> dict[str, SourceRecord]:
        return {source.source_id: source for source in self.database.list_sources()}

    @staticmethod
    def _source_authority(source: SourceRecord | None) -> str | None:
        if source is None:
            return None
        value = source.metadata.get("evidence_authority")
        return value if value in {"authoritative", "supporting", "lead"} else None

    @staticmethod
    def _lane_coverage(
        *,
        lane: str,
        hit_count: int,
        status: str,
        source_ids: set[str],
        failure: str | None = None,
    ) -> dict[str, object]:
        return {
            "lane": lane,
            "status": status,
            "hit_count": hit_count,
            "scope": {"source_ids": sorted(source_ids)},
            "failure": failure,
        }

    @staticmethod
    def _terms(query: str) -> tuple[str, ...]:
        terms: list[str] = []
        seen: set[str] = set()
        for term in tokenize_retrieval_text(query, lowercase=False):
            key = term.lower()
            if key not in seen:
                terms.append(term)
                seen.add(key)
        return tuple(terms)

    @classmethod
    def _request_terms(cls, request: EvidenceRequest) -> tuple[str, ...]:
        terms = list(cls._terms(request.query))
        search_terms = request.hook_requirement.get("search_terms", [])
        if not isinstance(search_terms, list) or not all(
            isinstance(term, str) and term.strip() for term in search_terms
        ):
            raise ValueError("hook_requirement.search_terms must be a string array.")
        seen = {term.lower() for term in terms}
        for search_term in search_terms:
            for term in cls._terms(search_term):
                if term.lower() not in seen:
                    terms.append(term)
                    seen.add(term.lower())
        return tuple(terms)

    @staticmethod
    def _first_text_match(text: str, terms: tuple[str, ...]) -> tuple[int, str] | None:
        lowered_terms = tuple(term.lower() for term in terms)
        for line_number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if any(term in lowered for term in lowered_terms):
                return line_number, line.strip()[:240]
        return None

    @staticmethod
    def _text_evidence_id(
        source_id: str,
        relative_path: str,
        line_number: int,
        content_hash: str,
    ) -> str:
        seed = f"{source_id}:{relative_path}:{line_number}:{content_hash}"
        return "ev_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _with_observability(
        pack: EvidencePack,
        *,
        query_processing_ms: float,
        symbol_ms: float,
        bm25_ms: float,
        text_ms: float,
        readiness_ms: float,
        total_ms: float,
        excluded_count: int,
        symbol_count: int,
        bm25_count: int,
        dense_count: int,
        text_count: int,
        bm25_disabled_reason: str,
        dense_ms: float,
        dense_disabled_reason: str,
        dense_required: bool,
        dense_budget_summary: dict[str, object],
        dense_trace_refs: tuple[str, ...],
        lane_coverage: tuple[dict[str, object], ...],
    ) -> EvidencePack:
        methods = tuple(
            dict.fromkeys(item.retrieval_method for item in pack.items)
        )
        timing = {
            "query_processing_ms": query_processing_ms,
            "symbol_ms": symbol_ms,
            "text_ms": text_ms,
            "bm25_ms": bm25_ms,
            "dense_ms": dense_ms,
            "fusion_ms": 0.0,
            "rerank_ms": 0.0,
            "readiness_ms": readiness_ms,
            "total_ms": total_ms,
            "final_count": float(len(pack.items)),
            "excluded_count": float(excluded_count),
            "symbol_count": float(symbol_count),
            "bm25_count": float(bm25_count),
            "dense_count": float(dense_count),
            "text_count": float(text_count),
        }
        disabled_modes = {
            "fusion": "Fusion is disabled because RRF is not implemented in this retriever.",
            "rerank": "Rerank is disabled because no reranker is configured.",
            "neural_sparse": "Neural sparse retrieval is outside the V1 retrieval path.",
        }
        if dense_disabled_reason:
            disabled_modes["dense"] = dense_disabled_reason
        if bm25_disabled_reason:
            disabled_modes["bm25"] = bm25_disabled_reason
        next_pack = replace(
            pack,
            retrieval_methods_used=methods,
            disabled_modes=disabled_modes,
            timing=timing,
            budget_summary={
                **dense_budget_summary,
                "deterministic_lane_coverage": [
                    dict(value) for value in lane_coverage
                ],
            },
            trace_refs=tuple(dict.fromkeys((*pack.trace_refs, *dense_trace_refs))),
        )
        if dense_required and dense_disabled_reason:
            blocker = {
                "code": "DENSE_RETRIEVAL_REQUIRED_FAILED",
                "message": dense_disabled_reason,
                "needed_evidence": ["dense vector retrieval result"],
            }
            blockers = (*next_pack.blockers, blocker)
            return replace(
                next_pack,
                readiness="insufficient",
                can_generate_patch=False,
                gaps=tuple(dict.fromkeys((*next_pack.gaps, dense_disabled_reason))),
                blockers=blockers,
                missing_evidence=missing_evidence_from_blockers(blockers),
                message=(
                    "Dense retrieval is required but failed; evidence pack is blocked."
                ),
            )
        return next_pack


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _dense_trace_refs(report: object) -> tuple[str, ...]:
    events = getattr(report, "trace_events", ())
    refs: list[str] = []
    for event in events:
        if isinstance(event, dict) and isinstance(event.get("event"), str):
            refs.append(str(event["event"]))
    return tuple(refs)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_str_tuple(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    return tuple(str(item) for item in value if isinstance(item, str))
