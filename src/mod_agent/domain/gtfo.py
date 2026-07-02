"""GTFO / BepInEx / IL2CPP / HarmonyX domain adapter contracts."""

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
    source_definition,
)

GTFO_DOMAIN_NAME = "gtfo_bepinex_il2cpp"

GTFO_ALLOWED_ROOTS = (
    "generated_mods",
    "mods",
    "src",
    "config",
)

GTFO_FORBIDDEN_PATHS = (
    "BepInEx/core",
    "BepInEx/core/*.dll",
    "GameAssembly.dll",
    "GTFO.exe",
    "interop",
    "interop/*.dll",
    "decompiled",
    "legacy_import/raw",
    "knowledge/indexes",
    "artifacts",
)


class GTFOAdapter:
    """First GameProfile adapter without leaking GTFO rules into workflow code."""

    domain_name = GTFO_DOMAIN_NAME

    def identify_project(self, root: str) -> DomainProfile:
        project_root = Path(root).resolve()
        status = "experimental" if _has_gtfo_markers(project_root) else "unsupported"
        return _profile(project_root=project_root, status=status)

    def collect_knowledge_sources(self, profile: DomainProfile):
        return list(profile.evidence_sources)

    def classify_request(self, user_request: str) -> DomainRoute:
        text = user_request.lower()
        if any(token in text for token in ("config", "setting", "default value")):
            return DomainRoute(
                route_id="config_only",
                risk_level="low",
                risk_tags=("config_only",),
                requires_game_profile=False,
                blocked=False,
                reason="Request appears limited to configuration defaults.",
            )
        if any(token in text for token in ("ui", "hud", "marker", "color", "feedback")):
            return DomainRoute(
                route_id="ui_feedback_without_hook",
                risk_level="medium",
                risk_tags=("ui_feedback_without_hook",),
                requires_game_profile=True,
                blocked=False,
                reason="UI feedback changes require domain evidence but may not require a game hook.",
            )
        if any(token in text for token in ("harmony", "hook", "patch method")):
            return DomainRoute(
                route_id="game_hook",
                risk_level="high",
                risk_tags=("game_hook",),
                requires_game_profile=True,
                blocked=False,
                reason="Harmony or hook behavior requires domain API evidence.",
            )
        if any(token in text for token in ("damage", "enemy", "runtime", "gameplay", "behavior")):
            return DomainRoute(
                route_id="runtime_behavior_change",
                risk_level="high",
                risk_tags=("runtime_behavior_change",),
                requires_game_profile=True,
                blocked=False,
                reason="Runtime behavior changes require GameProfile evidence.",
            )
        if any(token in text for token in ("il2cpp", "native", "interop", "reflection")):
            return DomainRoute(
                route_id="native_interop_reflection_heavy",
                risk_level="critical",
                risk_tags=("native/interop/reflection-heavy",),
                requires_game_profile=True,
                blocked=False,
                reason="IL2CPP/native/reflection-heavy changes are critical risk.",
            )
        return DomainRoute(
            route_id="unknown",
            risk_level="unknown",
            risk_tags=("unknown",),
            requires_game_profile=True,
            blocked=True,
            reason="Unknown GTFO request risk; block until evidence is available.",
        )

    def build_evidence_queries(self, feature_spec: dict[str, Any]) -> list[EvidenceQuery]:
        target_behavior = str(feature_spec.get("target_behavior") or "")
        target_symbols = tuple(str(item) for item in feature_spec.get("target_symbols", ()))
        risk_level = str(feature_spec.get("risk_level") or "")
        required_source_types = ["target_source", "domain_note"]
        if risk_level in {"high", "critical"}:
            required_source_types.append("decompiled_api")
        return [
            EvidenceQuery(
                query_terms=tuple(term for term in target_behavior.split() if term),
                required_source_types=tuple(dict.fromkeys(required_source_types)),
                required_symbols=target_symbols,
                blocked_if_missing=risk_level in {"high", "critical", "unknown"},
            )
        ]

    def safe_edit_roots(self, profile: DomainProfile) -> list[str]:
        return list(profile.allowed_roots)

    def forbidden_paths(self, profile: DomainProfile) -> list[str]:
        return list(profile.forbidden_paths)

    def build_profile(self, profile: DomainProfile) -> BuildProfile:
        if not profile.build_profiles:
            raise ValueError("GTFO profile has no build profile.")
        return profile.build_profiles[0]

    def runtime_profile(self, profile: DomainProfile) -> RuntimeProfile:
        return RuntimeProfile(
            profile_id="gtfo_bepinex_runtime",
            log_paths=("BepInEx/LogOutput.log", "BepInEx/logs/LogOutput.log"),
            startup_markers=("BepInEx", "Loading plugin", "Chainloader"),
            behavior_evidence_sources=("runtime_log", "manual_evidence", "screenshot"),
            limitations=(
                "Startup log evidence does not prove gameplay behavior.",
                "Screenshot evidence cannot prove Harmony hook correctness by itself.",
            ),
        )

    def verification_strategy(self, feature_spec: dict[str, Any]) -> VerificationPlan:
        risk_level = str(feature_spec.get("risk_level") or "")
        required = ["build_result", "runtime_log"]
        if risk_level in {"high", "critical"}:
            required.append("decompiled_api")
        return VerificationPlan(
            required_evidence_sources=tuple(required),
            acceptance_checks=(
                "plugin_startup_observed",
                "requested_behavior_observed_or_manual_evidence_supplied",
            ),
            blocked_without=tuple(required),
            limitations=("Build success does not prove runtime behavior.",),
        )


def build_gtfo_profile(project_root: str | Path = ".") -> DomainProfile:
    """Build the default experimental GTFO GameProfile contract."""

    return _profile(project_root=Path(project_root).resolve(), status="experimental")


def _profile(*, project_root: Path, status: str) -> DomainProfile:
    build_profile = BuildProfile(
        profile_id="gtfo_bepinex_il2cpp",
        build_system="dotnet",
        working_directory=".",
        command=("dotnet", "build"),
        timeout_seconds=120,
        expected_artifacts=(),
        log_path=None,
    )
    evidence_sources = (
        source_definition(
            source_id="gtfo_target_source",
            source_type="target_source",
            project_root=project_root,
            relative_root="generated_mods",
            include_generated_mods=True,
        ),
        source_definition(
            source_id="gtfo_reference_mods",
            source_type="reference_mod",
            project_root=project_root,
            relative_root="reference_mods",
        ),
        source_definition(
            source_id="gtfo_domain_docs",
            source_type="domain_note",
            project_root=project_root,
            relative_root="docs/knowledge",
        ),
        source_definition(
            source_id="gtfo_decompiled_api",
            source_type="decompiled_api",
            project_root=project_root,
            relative_root="decompiled",
        ),
        source_definition(
            source_id="gtfo_bepinex_logs",
            source_type="runtime_log",
            project_root=project_root,
            relative_root="BepInEx",
        ),
        source_definition(
            source_id="gtfo_prior_artifacts",
            source_type="prior_artifact",
            project_root=project_root,
            relative_root="artifacts/features",
        ),
    )
    return DomainProfile(
        game_id="gtfo",
        display_name="GTFO",
        runtime="Unity IL2CPP",
        mod_loader="BepInEx",
        harmony="HarmonyX",
        status=status,  # type: ignore[arg-type]
        allowed_roots=GTFO_ALLOWED_ROOTS,
        forbidden_paths=GTFO_FORBIDDEN_PATHS,
        build_profiles=(build_profile,),
        evidence_sources=evidence_sources,
        smoke_tests=("minimal_plugin_startup_probe",),
        known_limitations=(
            "No runtime behavior is proven without logs, manual evidence, or supplied runtime evidence.",
            "GTFO-specific behavior must stay behind this GameProfile boundary.",
        ),
        capability_report_ref="",
        project_root=str(project_root),
    )


def _has_gtfo_markers(project_root: Path) -> bool:
    if not project_root.exists() or not project_root.is_dir():
        return False
    markers = (
        project_root / "generated_mods",
        project_root / "reference_mods",
        project_root / "decompiled",
        project_root / "BepInEx",
        project_root / "docs" / "knowledge",
    )
    return any(path.exists() for path in markers) or any(project_root.glob("*.csproj"))
