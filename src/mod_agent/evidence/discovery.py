"""Compatibility facade for intelligent evidence discovery.

The implementation is split by responsibility:
`discovery_contract` owns schemas and model boundaries, `discovery_loop` owns
the bounded specialist loop, and `discovery_tools` owns deterministic reads.
"""

from .discovery_contract import (
    ChatEvidenceDiscoveryModel,
    EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
    EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION,
    EvidenceDiscoveryAgentModel,
    EvidenceDiscoveryDisclosure,
    EvidenceDiscoveryLocalExecution,
    EvidenceDiscoveryModel,
    EvidenceDiscoveryRequest,
    EvidenceDiscoveryResult,
    EvidenceDiscoverySource,
    EvidenceDiscoveryToolExecutor,
    ToolObservation,
    evidence_discovery_source_from_definition,
)
from .discovery_loop import EvidenceDiscoverySpecialist, IntelligentEvidencePackFactory

__all__ = [
    "ChatEvidenceDiscoveryModel",
    "EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES",
    "EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION",
    "EvidenceDiscoveryAgentModel",
    "EvidenceDiscoveryDisclosure",
    "EvidenceDiscoveryLocalExecution",
    "EvidenceDiscoveryModel",
    "EvidenceDiscoveryRequest",
    "EvidenceDiscoveryResult",
    "EvidenceDiscoverySource",
    "EvidenceDiscoverySpecialist",
    "EvidenceDiscoveryToolExecutor",
    "IntelligentEvidencePackFactory",
    "ToolObservation",
    "evidence_discovery_source_from_definition",
]
