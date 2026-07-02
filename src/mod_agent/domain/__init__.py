"""Domain adapter and GameProfile contracts."""

from .gtfo import GTFOAdapter, GTFO_DOMAIN_NAME, build_gtfo_profile
from .models import (
    DomainAdapter,
    DomainAdapterRegistry,
    DomainPathDecision,
    DomainProfile,
    DomainReviewPolicy,
    DomainRoute,
    EvidenceQuery,
    RuntimeProfile,
    VerificationPlan,
)
from .unsupported import UnsupportedDomainAdapter

__all__ = [
    "DomainAdapter",
    "DomainAdapterRegistry",
    "DomainPathDecision",
    "DomainProfile",
    "DomainReviewPolicy",
    "DomainRoute",
    "EvidenceQuery",
    "GTFOAdapter",
    "GTFO_DOMAIN_NAME",
    "RuntimeProfile",
    "UnsupportedDomainAdapter",
    "VerificationPlan",
    "build_gtfo_profile",
]
