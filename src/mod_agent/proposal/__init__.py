"""Patch proposal and review gate primitives."""

from .builder import PatchProposalBuilder
from .code_generator import (
    PATCH_RESPONSE_CONTRACT_ID,
    PATCH_RESPONSE_CONTRACT_VERSION,
    GeneratedPatch,
    LLMExactPatchGenerator,
    PatchGenerationError,
)
from .critic import (
    CRITIC_DIMENSIONS,
    CRITIC_PASS_THRESHOLD,
    CRITIC_POLICY_VERSION,
    CriticAssessment,
    CriticFinding,
    ProposalCritic,
    RuleBasedProposalCritic,
)
from .models import PatchProposal, ProposalReview, ReviewFinding
from .reviewer import ProposalReviewer

__all__ = [
    "CRITIC_DIMENSIONS",
    "CRITIC_POLICY_VERSION",
    "CRITIC_PASS_THRESHOLD",
    "CriticAssessment",
    "CriticFinding",
    "PatchProposal",
    "PatchProposalBuilder",
    "ProposalCritic",
    "ProposalReview",
    "ProposalReviewer",
    "RuleBasedProposalCritic",
    "ReviewFinding",
    "GeneratedPatch",
    "LLMExactPatchGenerator",
    "PATCH_RESPONSE_CONTRACT_ID",
    "PATCH_RESPONSE_CONTRACT_VERSION",
    "PatchGenerationError",
]
