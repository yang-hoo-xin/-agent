"""BM25 lexical sparse inverted index over persisted chunks."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .database import KnowledgeDatabase
from .models import BM25Hit, BM25IndexResult, KnowledgeChunkRecord

_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")


class BM25Indexer:
    """Build and query a local BM25 inverted index stored in SQLite."""

    def __init__(
        self,
        database: KnowledgeDatabase,
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.database = database
        self.k1 = k1
        self.b = b

    def index(
        self,
        *,
        collection_id: str,
        index_version: str,
        chunks: list[KnowledgeChunkRecord] | None = None,
    ) -> BM25IndexResult:
        """Replace BM25 terms and postings for one chunk index version."""

        indexed_chunks = chunks
        if indexed_chunks is None:
            indexed_chunks = self.database.list_chunks(
                collection_id=collection_id,
                index_version=index_version,
            )

        per_chunk_terms: dict[str, Counter[str]] = {}
        term_doc_freqs: dict[str, int] = defaultdict(int)
        postings: dict[tuple[str, str], int] = {}

        for chunk in indexed_chunks:
            counts = Counter(tokenize_bm25(chunk.text_for_retrieval))
            per_chunk_terms[chunk.chunk_id] = counts
            for term, term_freq in counts.items():
                term_doc_freqs[term] += 1
                postings[(term, chunk.chunk_id)] = term_freq

        self.database.replace_bm25_index(
            collection_id=collection_id,
            index_version=index_version,
            term_doc_freqs=dict(term_doc_freqs),
            postings=postings,
        )
        return BM25IndexResult(
            collection_id=collection_id,
            index_version=index_version,
            chunk_count=len(indexed_chunks),
            term_count=len(term_doc_freqs),
            posting_count=len(postings),
        )

    def query(
        self,
        *,
        collection_id: str,
        index_version: str,
        tokens: list[str],
        top_k: int,
    ) -> list[BM25Hit]:
        """Query the inverted index and return ranked chunk hits."""

        if top_k <= 0:
            return []
        query_terms = tuple(dict.fromkeys(normalize_bm25_token(token) for token in tokens))
        query_terms = tuple(term for term in query_terms if term)
        if not query_terms:
            return []

        term_doc_freqs = self.database.bm25_term_doc_freqs(
            collection_id=collection_id,
            index_version=index_version,
        )
        matched_terms = tuple(term for term in query_terms if term in term_doc_freqs)
        if not matched_terms:
            return []

        chunks = self.database.list_chunks(
            collection_id=collection_id,
            index_version=index_version,
        )
        if not chunks:
            return []
        chunk_map = {chunk.chunk_id: chunk for chunk in chunks}
        doc_lengths = {
            chunk.chunk_id: len(tokenize_bm25(chunk.text_for_retrieval))
            for chunk in chunks
        }
        avg_doc_length = sum(doc_lengths.values()) / len(doc_lengths)
        if avg_doc_length <= 0:
            avg_doc_length = 1.0

        postings = self.database.bm25_postings_for_terms(
            collection_id=collection_id,
            index_version=index_version,
            terms=matched_terms,
        )
        scores: dict[str, float] = defaultdict(float)
        hit_terms_by_chunk: dict[str, set[str]] = defaultdict(set)
        term_freqs_by_chunk: dict[str, dict[str, int]] = defaultdict(dict)
        document_count = len(chunks)

        for posting in postings:
            term = str(posting["term"])
            chunk_id = str(posting["chunk_id"])
            term_freq = int(posting["term_freq"])
            doc_freq = term_doc_freqs[term]
            doc_length = max(1, doc_lengths.get(chunk_id, 1))
            scores[chunk_id] += self._score(
                term_freq=term_freq,
                doc_freq=doc_freq,
                document_count=document_count,
                doc_length=doc_length,
                avg_doc_length=avg_doc_length,
            )
            hit_terms_by_chunk[chunk_id].add(term)
            term_freqs_by_chunk[chunk_id][term] = term_freq

        ranked_chunk_ids = sorted(
            scores,
            key=lambda chunk_id: (-scores[chunk_id], chunk_id),
        )[:top_k]
        return [
            self._hit(
                chunk=chunk_map[chunk_id],
                score=scores[chunk_id],
                hit_terms=tuple(
                    term for term in query_terms if term in hit_terms_by_chunk[chunk_id]
                ),
                term_frequencies=term_freqs_by_chunk[chunk_id],
            )
            for chunk_id in ranked_chunk_ids
            if chunk_id in chunk_map
        ]

    def query_text(
        self,
        *,
        collection_id: str,
        index_version: str,
        query: str,
        top_k: int,
    ) -> list[BM25Hit]:
        """Tokenize query text and query BM25."""

        return self.query(
            collection_id=collection_id,
            index_version=index_version,
            tokens=list(tokenize_bm25(query)),
            top_k=top_k,
        )

    def _score(
        self,
        *,
        term_freq: int,
        doc_freq: int,
        document_count: int,
        doc_length: int,
        avg_doc_length: float,
    ) -> float:
        idf = math.log(1 + (document_count - doc_freq + 0.5) / (doc_freq + 0.5))
        numerator = term_freq * (self.k1 + 1)
        denominator = term_freq + self.k1 * (
            1 - self.b + self.b * (doc_length / avg_doc_length)
        )
        return idf * (numerator / denominator)

    @staticmethod
    def _hit(
        *,
        chunk: KnowledgeChunkRecord,
        score: float,
        hit_terms: tuple[str, ...],
        term_frequencies: dict[str, int],
    ) -> BM25Hit:
        start_line = chunk.metadata.get("start_line")
        end_line = chunk.metadata.get("end_line")
        span = None
        if isinstance(start_line, int) and isinstance(end_line, int):
            span = {"start_line": start_line, "end_line": end_line}
        return BM25Hit(
            collection_id=chunk.collection_id,
            index_version=chunk.index_version,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            score=round(score, 6),
            hit_terms=hit_terms,
            term_frequencies=dict(term_frequencies),
            source_path=str(chunk.metadata.get("source_path", "")),
            span=span,
            excerpt=chunk.chunk_text.strip()[:240],
            metadata=dict(chunk.metadata),
        )


def tokenize_bm25(text: str) -> tuple[str, ...]:
    """Normalize text into BM25 lexical tokens."""

    tokens = [normalize_bm25_token(match.group(0)) for match in _TOKEN_RE.finditer(text)]
    return tuple(token for token in tokens if token)


def normalize_bm25_token(token: str) -> str:
    """Normalize one BM25 token without semantic expansion."""

    return token.strip().lower()
