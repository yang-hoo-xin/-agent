"""Contracts for Evidence RAG output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EvidenceReadiness = Literal["sufficient", "partial", "insufficient", "contradictory"]


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
            "items": [item.to_dict() for item in self.items],
            "gaps": list(self.gaps),
            "excluded": list(self.excluded),
            "blockers": list(self.blockers),
        }

    @classmethod
    def empty(cls, *, query: str, reason: str) -> "EvidencePack":
        """Return an insufficient empty pack with a blocking reason."""

        return cls(
            query=query,
            readiness="insufficient",
            can_generate_patch=False,
            gaps=(reason,),
            blockers=(
                {
                    "code": "INSUFFICIENT_EVIDENCE",
                    "message": reason,
                    "needed_evidence": [
                        "target source symbol",
                        "API reference",
                        "domain note",
                    ],
                },
            ),
        )
