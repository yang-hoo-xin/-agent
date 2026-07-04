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
    SymbolRecord,
    evidence_identity_from_metadata,
)

from .models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EvidenceItem,
    EvidencePack,
    EvidenceRequest,
)
from .readiness import EvidenceReadinessClassifier

_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{1,}")
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
    ) -> None:
        self.database = database
        self.readiness_classifier = readiness_classifier or EvidenceReadinessClassifier()
        self.bm25_indexer = bm25_indexer or BM25Indexer(database)
        self.symbol_indexer = symbol_indexer or SymbolIndexer()
        resolution = (collection_resolver or CollectionResolver()).resolve(collection_id)
        self.collection_id = resolution.collection_id

    def retrieve(self, request: EvidenceRequest) -> EvidencePack:
        """Retrieve evidence and classify readiness."""

        total_started = perf_counter()
        query_started = perf_counter()
        terms = self._terms(request.query)
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
                text_count=0,
                bm25_disabled_reason=(
                    "BM25 was not queried because the request had no searchable terms."
                ),
            )

        sources = self._source_map()
        allowed_source_ids = set(request.source_ids or sources)
        items: list[EvidenceItem] = []
        excluded: list[dict[str, object]] = []
        seen: set[str] = set()

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

        bm25_started = perf_counter()
        bm25_disabled_reason = ""
        bm25_count = 0
        if len(items) < request.max_items:
            bm25_items, bm25_disabled_reason = self._bm25_items(
                terms=terms,
                sources=sources,
                allowed_source_ids=allowed_source_ids,
                max_items=request.max_items - len(items),
            )
            for item in bm25_items:
                if item.evidence_id not in seen:
                    items.append(item)
                    seen.add(item.evidence_id)
            bm25_count = len(bm25_items)
        bm25_ms = _elapsed_ms(bm25_started)

        text_started = perf_counter()
        text_count = 0
        if len(items) < request.max_items:
            text_items = self._text_items(
                terms=terms,
                sources=sources,
                allowed_source_ids=allowed_source_ids,
                max_items=request.max_items - len(items),
            )
            for item in text_items:
                if item.evidence_id not in seen:
                    items.append(item)
                    seen.add(item.evidence_id)
            text_count = len(text_items)
        text_ms = _elapsed_ms(text_started)

        readiness_started = perf_counter()
        pack = self.readiness_classifier.classify(
            request=request,
            items=items[: request.max_items],
            excluded=excluded,
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
            symbol_count=len([item for item in items if item.retrieval_method == "symbol_exact"]),
            bm25_count=bm25_count,
            text_count=text_count,
            bm25_disabled_reason=bm25_disabled_reason,
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
            source_path=symbol.source_path,
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
            source_path=entry.source_path,
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
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
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
            source_path=hit.source_path,
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
                    source_path=indexed_file.source_path,
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
                    risk_notes=(),
                )
            )
            if len(items) >= max_items:
                break
        return items

    def _source_map(self) -> dict[str, SourceRecord]:
        return {source.source_id: source for source in self.database.list_sources()}

    @staticmethod
    def _terms(query: str) -> tuple[str, ...]:
        terms: list[str] = []
        seen: set[str] = set()
        for match in _TERM_RE.finditer(query):
            term = match.group(0)
            key = term.lower()
            if key not in seen:
                terms.append(term)
                seen.add(key)
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
        text_count: int,
        bm25_disabled_reason: str,
    ) -> EvidencePack:
        methods = tuple(
            dict.fromkeys(item.retrieval_method for item in pack.items)
        )
        timing = {
            "query_processing_ms": query_processing_ms,
            "symbol_ms": symbol_ms,
            "text_ms": text_ms,
            "bm25_ms": bm25_ms,
            "dense_ms": 0.0,
            "fusion_ms": 0.0,
            "rerank_ms": 0.0,
            "readiness_ms": readiness_ms,
            "total_ms": total_ms,
            "final_count": float(len(pack.items)),
            "excluded_count": float(excluded_count),
            "symbol_count": float(symbol_count),
            "bm25_count": float(bm25_count),
            "text_count": float(text_count),
        }
        disabled_modes = {
            "dense": "Dense retrieval is disabled until embedding and vector index are configured.",
            "fusion": "Fusion is disabled because RRF is not implemented in this retriever.",
            "rerank": "Rerank is disabled because no reranker is configured.",
            "neural_sparse": "Neural sparse retrieval is outside the V1 retrieval path.",
        }
        if bm25_disabled_reason:
            disabled_modes["bm25"] = bm25_disabled_reason
        return replace(
            pack,
            retrieval_methods_used=methods,
            disabled_modes=disabled_modes,
            timing=timing,
        )


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)
