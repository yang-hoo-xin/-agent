"""Domain adapter contracts for game/mod ecosystems."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Protocol

from src.mod_agent.build import BuildProfile
from src.mod_agent.knowledge import SourceDefinition

GameProfileStatus = Literal["unsupported", "experimental", "supported", "deprecated"]
DomainRiskLevel = Literal["low", "medium", "high", "critical", "unknown"]


@dataclass(frozen=True)
class EvidenceQuery:
    """Domain-scoped evidence query contract."""

    query_terms: tuple[str, ...]
    required_source_types: tuple[str, ...]
    required_symbols: tuple[str, ...] = ()
    blocked_if_missing: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_terms": list(self.query_terms),
            "required_source_types": list(self.required_source_types),
            "required_symbols": list(self.required_symbols),
            "blocked_if_missing": self.blocked_if_missing,
        }


@dataclass(frozen=True)
class DomainRoute:
    """Domain-specific route and risk classification."""

    route_id: str
    risk_level: DomainRiskLevel
    risk_tags: tuple[str, ...]
    requires_game_profile: bool
    blocked: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "risk_level": self.risk_level,
            "risk_tags": list(self.risk_tags),
            "requires_game_profile": self.requires_game_profile,
            "blocked": self.blocked,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RuntimeProfile:
    """Runtime evidence hints supplied by a domain adapter."""

    profile_id: str
    log_paths: tuple[str, ...]
    startup_markers: tuple[str, ...]
    behavior_evidence_sources: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "log_paths": list(self.log_paths),
            "startup_markers": list(self.startup_markers),
            "behavior_evidence_sources": list(self.behavior_evidence_sources),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class VerificationPlan:
    """Domain-specific verification strategy."""

    required_evidence_sources: tuple[str, ...]
    acceptance_checks: tuple[str, ...]
    blocked_without: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_evidence_sources": list(self.required_evidence_sources),
            "acceptance_checks": list(self.acceptance_checks),
            "blocked_without": list(self.blocked_without),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class DomainProfile:
    """GameProfile schema from DEV_SPEC section 50.8."""

    game_id: str
    display_name: str
    runtime: str
    mod_loader: str
    harmony: str
    status: GameProfileStatus
    allowed_roots: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    build_profiles: tuple[BuildProfile, ...]
    evidence_sources: tuple[SourceDefinition, ...]
    smoke_tests: tuple[str, ...]
    known_limitations: tuple[str, ...]
    capability_report_ref: str
    project_root: str = "."

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "display_name": self.display_name,
            "runtime": self.runtime,
            "mod_loader": self.mod_loader,
            "harmony": self.harmony,
            "status": self.status,
            "allowed_roots": list(self.allowed_roots),
            "forbidden_paths": list(self.forbidden_paths),
            "build_profiles": [profile.to_dict() for profile in self.build_profiles],
            "evidence_sources": [
                {
                    "source_id": source.source_id,
                    "source_type": source.source_type,
                    "root_path": str(source.root_path),
                    "metadata": dict(source.metadata),
                    "include_generated_mods": source.include_generated_mods,
                }
                for source in self.evidence_sources
            ],
            "smoke_tests": list(self.smoke_tests),
            "known_limitations": list(self.known_limitations),
            "capability_report_ref": self.capability_report_ref,
        }

    def review_policy(self) -> "DomainReviewPolicy":
        """Return a review-time policy projection for this profile."""

        return DomainReviewPolicy(
            profile_id=self.game_id,
            status=self.status,
            allowed_roots=self.allowed_roots,
            forbidden_paths=self.forbidden_paths,
            project_root=self.project_root,
        )


@dataclass(frozen=True)
class DomainPathDecision:
    """Review decision for one target path under a domain policy."""

    allowed: bool
    rule_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class DomainReviewPolicy:
    """Read-only domain policy used by proposal review."""

    profile_id: str
    status: GameProfileStatus
    allowed_roots: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    project_root: str = "."
    target_root: str | None = None

    def allows_runtime_change(self) -> bool:
        return self.status in {"experimental", "supported"}

    def bind_target_root(self, target_root: str) -> "DomainReviewPolicy":
        """Bind project-relative proposal paths to one allowed domain root."""

        if _is_absolute_path(target_root):
            raise ValueError("Domain target root must be relative.")
        normalized = _normalize_path(target_root)
        if normalized in {"", "."}:
            raise ValueError("Domain target root must be a non-empty path.")
        decision = self._review_normalized_path(normalized)
        if not decision.allowed:
            raise ValueError(
                "Domain target root is not allowed by the domain policy: "
                f"{decision.reason}"
            )
        return replace(self, target_root=normalized)

    def review_path(self, path: str) -> DomainPathDecision:
        if self.target_root and _is_absolute_path(path):
            try:
                relative_path = Path(path).resolve().relative_to(
                    Path(self.project_root).resolve()
                )
            except ValueError:
                return DomainPathDecision(
                    allowed=False,
                    rule_id="forbidden_paths",
                    reason=(
                        "Domain policy blocks absolute target paths outside "
                        "the bound project root."
                    ),
                )
            normalized = _normalize_path(relative_path.as_posix())
        else:
            normalized = _normalize_path(path)
        unscoped_forbidden = self._review_forbidden_path(normalized)
        if unscoped_forbidden is not None:
            return unscoped_forbidden

        if self.target_root:
            if _matches_path(normalized, self.target_root):
                scoped_path = normalized
            elif any(
                _matches_path(normalized, root) for root in self.allowed_roots
            ):
                return DomainPathDecision(
                    allowed=False,
                    rule_id="scope_boundary",
                    reason="Target path is outside bound domain target root.",
                )
            else:
                scoped_path = _normalize_path(f"{self.target_root}/{normalized}")
            return self._review_normalized_path(scoped_path)

        return self._review_normalized_path(normalized)

    def _review_forbidden_path(
        self,
        normalized: str,
    ) -> DomainPathDecision | None:
        parts = set(PurePosixPath(normalized).parts)
        if ".." in parts:
            return DomainPathDecision(
                allowed=False,
                rule_id="forbidden_paths",
                reason="Domain policy blocks path traversal.",
            )
        for blocked in self.forbidden_paths:
            if _matches_path(normalized, blocked):
                return DomainPathDecision(
                    allowed=False,
                    rule_id="forbidden_paths",
                    reason=f"Domain policy forbids {blocked}.",
                )
        return None

    def _review_normalized_path(self, normalized: str) -> DomainPathDecision:
        forbidden = self._review_forbidden_path(normalized)
        if forbidden is not None:
            return forbidden
        if self.allowed_roots and not any(
            _matches_path(normalized, root) for root in self.allowed_roots
        ):
            return DomainPathDecision(
                allowed=False,
                rule_id="scope_boundary",
                reason="Target path is outside domain allowed roots.",
            )
        return DomainPathDecision(allowed=True)


class DomainAdapter(Protocol):
    """Base domain adapter protocol from DEV_SPEC section 9.2."""

    domain_name: str

    def identify_project(self, root: str) -> DomainProfile:
        ...

    def collect_knowledge_sources(self, profile: DomainProfile) -> list[SourceDefinition]:
        ...

    def classify_request(self, user_request: str) -> DomainRoute:
        ...

    def build_evidence_queries(self, feature_spec: dict[str, Any]) -> list[EvidenceQuery]:
        ...

    def safe_edit_roots(self, profile: DomainProfile) -> list[str]:
        ...

    def forbidden_paths(self, profile: DomainProfile) -> list[str]:
        ...

    def build_profile(self, profile: DomainProfile) -> BuildProfile:
        ...

    def runtime_profile(self, profile: DomainProfile) -> RuntimeProfile:
        ...

    def verification_strategy(self, feature_spec: dict[str, Any]) -> VerificationPlan:
        ...


class DomainAdapterRegistry:
    """Registry that lets new game profiles plug in without changing workflow code."""

    def __init__(self, adapters: tuple[DomainAdapter, ...] = ()) -> None:
        self._adapters = {adapter.domain_name: adapter for adapter in adapters}

    def register(self, adapter: DomainAdapter) -> None:
        self._adapters[adapter.domain_name] = adapter

    def get(self, domain_name: str) -> DomainAdapter:
        try:
            return self._adapters[domain_name]
        except KeyError as exc:
            raise KeyError(f"Unknown domain adapter: {domain_name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def _normalize_path(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/"))).strip("/")


def _is_absolute_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(path).is_absolute()
    )


def _matches_path(path: str, boundary: str) -> bool:
    normalized_boundary = _normalize_path(boundary)
    if normalized_boundary in {"", "."}:
        return True
    if "*" in normalized_boundary:
        return PurePosixPath(path).match(normalized_boundary)
    boundary_path = str(PurePosixPath(normalized_boundary))
    return path == boundary_path or path.startswith(f"{boundary_path}/")


def source_definition(
    *,
    source_id: str,
    source_type: str,
    project_root: Path,
    relative_root: str,
    include_generated_mods: bool = False,
) -> SourceDefinition:
    """Create a source definition without scanning the filesystem."""

    return SourceDefinition(
        source_id=source_id,
        source_type=source_type,
        root_path=project_root / relative_root,
        metadata={"relative_root": relative_root},
        include_generated_mods=include_generated_mods,
    )
