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
from .discovery import (
    ChatEvidenceDiscoveryModel,
    EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
    EvidenceDiscoveryDisclosure,
    EvidenceDiscoveryAgentModel,
    EvidenceDiscoveryRequest,
    EvidenceDiscoveryResult,
    EvidenceDiscoverySource,
    EvidenceDiscoverySpecialist,
    IntelligentEvidencePackFactory,
    ToolObservation,
    evidence_discovery_source_from_definition,
)
from .gtfo_r8 import GTFOR8EvidenceProvider, R8EvidenceError
from .discovery_tools import LocalAssemblyEvidenceToolExecutor
from .r8_il import (
    BoundILInspectionRunner,
    MetadataSearchRunner,
    R8ILInspectionError,
    R8ILInspectionRunner,
)
from .readiness import EvidenceReadinessClassifier
from .retriever import DeterministicEvidenceRetriever
from .rg_live import RgLiveEvidenceProvider

__all__ = [
    "DenseRetrievalHit",
    "DenseRetrievalProvider",
    "DenseRetrievalReport",
    "DeterministicEvidenceRetriever",
    "RgLiveEvidenceProvider",
    "DisabledDenseRetrievalProvider",
    "EvidenceItem",
    "EvidencePack",
    "EvidenceDiscoveryRequest",
    "EvidenceDiscoveryDisclosure",
    "EvidenceDiscoveryAgentModel",
    "EvidenceDiscoveryResult",
    "EvidenceDiscoverySource",
    "EvidenceDiscoverySpecialist",
    "evidence_discovery_source_from_definition",
    "IntelligentEvidencePackFactory",
    "ChatEvidenceDiscoveryModel",
    "EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES",
    "MetadataSearchRunner",
    "GTFOR8EvidenceProvider",
    "LocalAssemblyEvidenceToolExecutor",
    "R8EvidenceError",
    "BoundILInspectionRunner",
    "R8ILInspectionError",
    "R8ILInspectionRunner",
    "EvidenceReadiness",
    "EvidenceReadinessClassifier",
    "EvidenceRequest",
    "ToolObservation",
    "FakeDenseRetrievalProvider",
    "VectorStoreDenseRetrievalProvider",
    "create_vector_store_dense_provider",
]
