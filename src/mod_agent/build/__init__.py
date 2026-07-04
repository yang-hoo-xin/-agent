"""Build adapter contracts for controlled build validation."""

from .adapter import (
    BuildAdapter,
    BuildCommandResult,
    BuildDiagnostic,
    BuildErrorClassifier,
    BuildProfile,
    BuildProfileRegistry,
    BuildResult,
    build_fake_build_result,
)

__all__ = [
    "BuildAdapter",
    "BuildCommandResult",
    "BuildDiagnostic",
    "BuildErrorClassifier",
    "BuildProfile",
    "BuildProfileRegistry",
    "BuildResult",
    "build_fake_build_result",
]
