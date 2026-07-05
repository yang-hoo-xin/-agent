"""Evidence RAG primitives for controlled code generation."""

from .dense import (
    DenseRetrievalHit,
    DenseRetrievalProvider,
    DenseRetrievalReport,
    DisabledDenseRetrievalProvider,
    FakeDenseRetrievalProvider,
)
from .models import EvidenceItem, EvidencePack, EvidenceReadiness, EvidenceRequest
from .readiness import EvidenceReadinessClassifier
from .retriever import DeterministicEvidenceRetriever

__all__ = [
    "DenseRetrievalHit",
    "DenseRetrievalProvider",
    "DenseRetrievalReport",
    "DeterministicEvidenceRetriever",
    "DisabledDenseRetrievalProvider",
    "EvidenceItem",
    "EvidencePack",
    "EvidenceReadiness",
    "EvidenceReadinessClassifier",
    "EvidenceRequest",
    "FakeDenseRetrievalProvider",
]
