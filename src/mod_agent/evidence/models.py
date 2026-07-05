"""Contracts for Evidence RAG output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION

EvidenceReadiness = Literal["sufficient", "partial", "insufficient", "contradictory"]
EvidenceAuthority = Literal["mod_agent_deterministic", "legacy_rag_auxiliary"]
DETERMINISTIC_EVIDENCE_AUTHORITY = "mod_agent_deterministic"
LEGACY_RAG_AUXILIARY_AUTHORITY = "legacy_rag_auxiliary"
EVIDENCE_PACK_AUTHORITY = "mod_agent_deterministic_evidence"


@dataclass(frozen=True)
class EvidenceRequest:
    """Retrieval input produced by planning or feature-spec stages."""

    query: str
    execution_path: str = "standard_feature"
    requires_hook_evidence: bool = True
    source_ids: tuple[str, ...] = ()
    max_items: int = 10


@dataclass(frozen=True)
class EvidenceItem:
    """Single evidence item bound to source, method, and claim."""

    evidence_id: str
    source_type: str
    source_path: str
    symbol: str | None
    span: dict[str, int] | None
    retrieval_method: str
    score: float
    claim_supported: str
    excerpt: str
    chunk_id: str | None = None
    document_id: str | None = None
    source_ref: str | None = None
    source_hash: str | None = None
    file_hash: str | None = None
    doc_hash: str | None = None
    authority: EvidenceAuthority = LEGACY_RAG_AUXILIARY_AUTHORITY
    risk_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable evidence."""

        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "span": self.span,
            "retrieval_method": self.retrieval_method,
            "score": self.score,
            "claim_supported": self.claim_supported,
            "excerpt": self.excerpt,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "file_hash": self.file_hash,
            "doc_hash": self.doc_hash,
            "authority": self.authority,
            "risk_notes": list(self.risk_notes),
        }


@dataclass(frozen=True)
class EvidencePack:
    """Evidence RAG output consumed by implementation planning and review."""

    query: str
    readiness: EvidenceReadiness
    can_generate_patch: bool
    items: tuple[EvidenceItem, ...] = ()
    gaps: tuple[str, ...] = ()
    excluded: tuple[dict[str, Any], ...] = ()
    blockers: tuple[dict[str, Any], ...] = ()
    retrieval_methods_used: tuple[str, ...] = ()
    missing_evidence: tuple[dict[str, Any], ...] = ()
    disabled_modes: dict[str, str] = field(default_factory=dict)
    timing: dict[str, float] = field(default_factory=dict)
    budget_summary: dict[str, Any] = field(default_factory=dict)
    trace_refs: tuple[str, ...] = ()
    message: str = ""

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the evidence_pack artifact contract."""

        message = self.message or (
            f"Evidence readiness is {self.readiness}; "
            f"{len(self.items)} evidence items retrieved."
        )
        return {
            "node_name": "retrieve_evidence",
            "stage": "evidence_retrieval",
            "message": message,
            "query": self.query,
            "readiness": self.readiness,
            "can_generate_patch": self.can_generate_patch,
            "authority": EVIDENCE_PACK_AUTHORITY,
            "authoritative_for_patch": self.can_generate_patch,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "identity_field_mapping": dict(IDENTITY_FIELD_MAPPING),
            "items": [item.to_dict() for item in self.items],
            "gaps": list(self.gaps),
            "excluded": list(self.excluded),
            "blockers": list(self.blockers),
            "retrieval_methods_used": list(self.retrieval_methods_used),
            "missing_evidence": list(self.missing_evidence),
            "disabled_modes": dict(self.disabled_modes),
            "timing": dict(self.timing),
            "budget_summary": dict(self.budget_summary),
            "trace_refs": list(self.trace_refs),
        }

    @classmethod
    def empty(cls, *, query: str, reason: str) -> "EvidencePack":
        """Return an insufficient empty pack with a blocking reason."""

        blockers = (
            {
                "code": "INSUFFICIENT_EVIDENCE",
                "message": reason,
                "needed_evidence": [
                    "target source symbol",
                    "API reference",
                    "domain note",
                ],
            },
        )
        return cls(
            query=query,
            readiness="insufficient",
            can_generate_patch=False,
            gaps=(reason,),
            blockers=blockers,
            missing_evidence=missing_evidence_from_blockers(blockers),
            disabled_modes={
                "deterministic": reason,
                "bm25": "BM25 inverted index is not available for this evidence pack.",
                "dense": "Dense retrieval is not available for this evidence pack.",
                "fusion": "Fusion is not available for this evidence pack.",
                "rerank": "Rerank is not available for this evidence pack.",
                "neural_sparse": "Neural sparse retrieval is outside the V1 retrieval path.",
            },
            timing={
                "query_processing_ms": 0.0,
                "symbol_ms": 0.0,
                "text_ms": 0.0,
                "bm25_ms": 0.0,
                "dense_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "readiness_ms": 0.0,
                "total_ms": 0.0,
                "final_count": 0.0,
                "excluded_count": 0.0,
            },
        )


def missing_evidence_from_blockers(
    blockers: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Build structured missing evidence entries from readiness blockers."""

    missing: list[dict[str, Any]] = []
    for blocker in blockers:
        blocker_code = str(blocker.get("code", "UNKNOWN_BLOCKER"))
        blocker_message = str(blocker.get("message", "Evidence is missing."))
        for needed in blocker.get("needed_evidence", []):
            missing.append(
                {
                    "needed_evidence": str(needed),
                    "blocker_code": blocker_code,
                    "reason": blocker_message,
                }
            )
    return tuple(missing)
