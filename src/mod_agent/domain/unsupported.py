"""Unsupported domain adapter used when no GameProfile is available."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.mod_agent.build import BuildProfile

from .models import (
    DomainProfile,
    DomainRoute,
    EvidenceQuery,
    RuntimeProfile,
    VerificationPlan,
)


class UnsupportedDomainAdapter:
    """Adapter that permits generic planning but blocks game-specific changes."""

    domain_name = "unsupported"

    def identify_project(self, root: str) -> DomainProfile:
        project_root = Path(root).resolve()
        return DomainProfile(
            game_id="unsupported",
            display_name="Unsupported Domain",
            runtime="unknown",
            mod_loader="unknown",
            harmony="unknown",
            status="unsupported",
            allowed_roots=(),
            forbidden_paths=(),
            build_profiles=(),
            evidence_sources=(),
            smoke_tests=(),
            known_limitations=("No GameProfile is available for game-specific runtime changes.",),
            capability_report_ref="",
            project_root=str(project_root),
        )

    def collect_knowledge_sources(self, profile: DomainProfile):
        return []

    def classify_request(self, user_request: str) -> DomainRoute:
        return DomainRoute(
            route_id="unknown_domain",
            risk_level="unknown",
            risk_tags=("unknown_domain",),
            requires_game_profile=True,
            blocked=True,
            reason="No GameProfile is available.",
        )

    def build_evidence_queries(self, feature_spec: dict[str, Any]) -> list[EvidenceQuery]:
        return [
            EvidenceQuery(
                query_terms=tuple(str(feature_spec.get("target_behavior") or "").split()),
                required_source_types=("domain_note",),
                blocked_if_missing=True,
            )
        ]

    def safe_edit_roots(self, profile: DomainProfile) -> list[str]:
        return []

    def forbidden_paths(self, profile: DomainProfile) -> list[str]:
        return []

    def build_profile(self, profile: DomainProfile) -> BuildProfile:
        raise ValueError("Unsupported domain has no build profile.")

    def runtime_profile(self, profile: DomainProfile) -> RuntimeProfile:
        return RuntimeProfile(
            profile_id="unsupported_runtime",
            log_paths=(),
            startup_markers=(),
            behavior_evidence_sources=(),
            limitations=("Runtime evidence is unavailable without a GameProfile.",),
        )

    def verification_strategy(self, feature_spec: dict[str, Any]) -> VerificationPlan:
        return VerificationPlan(
            required_evidence_sources=("game_profile",),
            acceptance_checks=(),
            blocked_without=("game_profile",),
            limitations=("Game-specific runtime changes must be blocked.",),
        )
