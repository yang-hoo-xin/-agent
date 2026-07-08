"""Evidence RAG primitives for controlled code generation."""

from .dense import (
    DenseRetrievalHit,
    DenseRetrievalProvider,
    DenseRetrievalReport,
    DisabledDenseRetrievalProvider,
    FakeDenseRetrievalProvider,
    VectorStoreDenseRetrievalProvider,
    create_vector_store_dense_provider,
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
    "VectorStoreDenseRetrievalProvider",
    "create_vector_store_dense_provider",
]
