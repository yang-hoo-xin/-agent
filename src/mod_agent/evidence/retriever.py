"""Deterministic Evidence RAG retrieval from the local Knowledge Base."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from src.mod_agent.knowledge import KnowledgeDatabase, SourceRecord, SymbolRecord

from .models import EvidenceItem, EvidencePack, EvidenceRequest
from .readiness import EvidenceReadinessClassifier

_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{1,}")
_TEXT_EXTENSIONS = frozenset({".json", ".yaml", ".yml", ".md", ".txt", ".log", ".cfg"})


class DeterministicEvidenceRetriever:
    """Retrieve symbol and text evidence without LLM calls."""

    def __init__(
        self,
        database: KnowledgeDatabase,
        readiness_classifier: EvidenceReadinessClassifier | None = None,
    ) -> None:
        self.database = database
        self.readiness_classifier = readiness_classifier or EvidenceReadinessClassifier()

    def retrieve(self, request: EvidenceRequest) -> EvidencePack:
        """Retrieve evidence and classify readiness."""

        terms = self._terms(request.query)
        if not terms:
            return EvidencePack.empty(
                query=request.query,
                reason="Request did not contain searchable identifiers or terms.",
            )

        sources = self._source_map()
        allowed_source_ids = set(request.source_ids or sources)
        items: list[EvidenceItem] = []
        excluded: list[dict[str, object]] = []
        seen: set[str] = set()

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

        if len(items) < request.max_items:
            for item in self._text_items(
                terms=terms,
                sources=sources,
                allowed_source_ids=allowed_source_ids,
                max_items=request.max_items - len(items),
            ):
                if item.evidence_id not in seen:
                    items.append(item)
                    seen.add(item.evidence_id)

        return self.readiness_classifier.classify(
            request=request,
            items=items[: request.max_items],
            excluded=excluded,
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
