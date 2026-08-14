"""Deterministic Evidence RAG retrieval from the local Knowledge Base."""

from __future__ import annotations

import hashlib
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

_TEXT_EXTENSIONS = frozenset({".json", ".yaml", ".yml", ".md", ".txt", ".log", ".cfg"})


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
    ) -> EvidencePack:
        """Retrieve evidence and classify readiness."""

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
            )

        sources = self._source_map()
        allowed_source_ids = set(request.source_ids or sources)
        items: list[EvidenceItem] = list(preverified_items)
        excluded: list[dict[str, object]] = []
        seen: set[str] = {item.evidence_id for item in preverified_items}
        lane_coverage: list[dict[str, object]] = [
            dict(item) for item in preverified_lane_coverage
        ]

        symbol_started = perf_counter()
        stable_version = self.database.stable_index_version(self.collection_id)
        if stable_version is not None:
            for item in self._symbol_index_items(
                terms=terms,
                sources=sources,
                allowed_source_ids=allowed_source_ids,
                index_version=stable_version.index_version,
                max_items=request.max_items,
            ):
                if item.evidence_id not in seen:
                    items.append(item)
                    seen.add(item.evidence_id)
                if len(items) >= request.max_items:
                    break
        if len(items) < request.max_items:
            for term in terms:
                for symbol in self.database.search_symbols(term, limit=request.max_items):
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
                    if item.evidence_id not in seen:
                        items.append(item)
                        seen.add(item.evidence_id)
                    if len(items) >= request.max_items:
                        break
                if len(items) >= request.max_items:
                    break
        symbol_ms = _elapsed_ms(symbol_started)
        symbol_count = len(
            [item for item in items if item.retrieval_method == "symbol_exact"]
        )
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
            max_items=request.max_items,
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
            max_items=request.max_items,
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
        )

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
            budget_summary=dense_budget_summary,
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
