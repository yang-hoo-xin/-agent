"""Evidence readiness classification."""

from __future__ import annotations

from .models import (
    EvidenceItem,
    EvidencePack,
    EvidenceReadiness,
    EvidenceRequest,
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    missing_evidence_from_blockers,
)

HOOK_SOURCE_TYPES = frozenset({"target_source", "reference_mod", "decompiled_api"})
HOOK_METHODS = frozenset({"symbol", "symbol_exact", "symbol_substring"})
AUTHORITATIVE_ITEM_AUTHORITY = DETERMINISTIC_EVIDENCE_AUTHORITY


class EvidenceReadinessClassifier:
    """Classify whether evidence is enough to allow patch proposal generation."""

    def classify(
        self,
        *,
        request: EvidenceRequest,
        items: list[EvidenceItem],
        excluded: list[dict[str, object]] | None = None,
    ) -> EvidencePack:
        """Return an evidence pack with readiness and blockers."""

        if not items:
            return EvidencePack.empty(
                query=request.query,
                reason="No source, API, artifact, log, or domain evidence matched the request.",
            )

        authoritative_items = [
            item for item in items if item.authority == AUTHORITATIVE_ITEM_AUTHORITY
        ]
        if not authoritative_items:
            blockers = (
                {
                    "code": "AUXILIARY_RETRIEVAL_NOT_AUTHORITATIVE",
                    "message": (
                        "Auxiliary or legacy retrieval output cannot approve "
                        "controlled implementation."
                    ),
                    "needed_evidence": ["mod_agent deterministic evidence pack"],
                },
            )
            return EvidencePack(
                query=request.query,
                readiness="partial",
                can_generate_patch=False,
                items=tuple(items),
                excluded=tuple(excluded or []),
                gaps=("Only auxiliary retrieval output was available.",),
                blockers=blockers,
                missing_evidence=missing_evidence_from_blockers(blockers),
            )

        if any("contradiction" in note.lower() for item in items for note in item.risk_notes):
            blockers = (
                {
                    "code": "CONTRADICTORY_EVIDENCE",
                    "message": "Retrieved evidence contains contradiction risk notes.",
                    "needed_evidence": ["consistent source/API/log evidence"],
                },
            )
            return EvidencePack(
                query=request.query,
                readiness="contradictory",
                can_generate_patch=False,
                items=tuple(items),
                excluded=tuple(excluded or []),
                gaps=("Evidence contains contradiction risk notes.",),
                blockers=blockers,
                missing_evidence=missing_evidence_from_blockers(blockers),
            )

        if request.execution_path == "quick_patch" and not request.requires_hook_evidence:
            return self._pack(
                request=request,
                readiness="sufficient",
                items=authoritative_items,
                excluded=excluded or [],
                message="Quick patch evidence is sufficient without hook evidence.",
            )

        if request.requires_hook_evidence and not self._has_hook_evidence(authoritative_items):
            blockers = (
                {
                    "code": "INSUFFICIENT_HOOK_EVIDENCE",
                    "message": (
                        "No source/API evidence identifies a safe hook for the "
                        "requested runtime behavior."
                    ),
                    "needed_evidence": [
                        "target method",
                        "call timing",
                        "side effect boundary",
                    ],
                },
            )
            return EvidencePack(
                query=request.query,
                readiness="partial",
                can_generate_patch=False,
                items=tuple(items),
                excluded=tuple(excluded or []),
                gaps=("No target/source/API symbol evidence identifies a safe hook.",),
                blockers=blockers,
                missing_evidence=missing_evidence_from_blockers(blockers),
            )

        return self._pack(
            request=request,
            readiness="sufficient",
            items=authoritative_items,
            excluded=excluded or [],
            message="Evidence is sufficient for implementation planning.",
        )

    @staticmethod
    def _has_hook_evidence(items: list[EvidenceItem]) -> bool:
        return any(
            item.source_type in HOOK_SOURCE_TYPES
            and item.retrieval_method in HOOK_METHODS
            and item.symbol
            for item in items
        )

    @staticmethod
    def _pack(
        *,
        request: EvidenceRequest,
        readiness: EvidenceReadiness,
        items: list[EvidenceItem],
        excluded: list[dict[str, object]],
        message: str,
    ) -> EvidencePack:
        return EvidencePack(
            query=request.query,
            readiness=readiness,
            can_generate_patch=readiness == "sufficient",
            items=tuple(items),
            excluded=tuple(excluded),
            message=message,
        )
