"""Tests for controlled build adapter contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore, ArtifactStoreError
from src.mod_agent.build import (
    BuildAdapter,
    BuildCommandResult,
    BuildErrorClassifier,
    BuildProfile,
    BuildProfileRegistry,
    build_fake_build_result,
)


def _profile(working_directory: str = "generated_mods/BetterHitFeedback") -> BuildProfile:
    return BuildProfile(
        profile_id="test_dotnet",
        build_system="dotnet",
        working_directory=working_directory,
        command=("dotnet", "build"),
        timeout_seconds=120,
        expected_artifacts=("bin/Debug/BetterHitFeedback.dll",),
    )


def _profile_with_expected(
    *,
    working_directory: str,
    expected_artifacts: tuple[str, ...],
) -> BuildProfile:
    return BuildProfile(
        profile_id="test_dotnet",
        build_system="dotnet",
        working_directory=working_directory,
        command=("dotnet", "build"),
        timeout_seconds=120,
        expected_artifacts=expected_artifacts,
    )


def test_error_classifier_extracts_missing_reference_diagnostic() -> None:
    output = (
        "Plugin.cs(42,17): error CS0246: The type or namespace name "
        "'SomeType' could not be found"
    )

    error_class, diagnostics = BuildErrorClassifier().classify(output)

    assert error_class == "missing_reference"
    assert diagnostics[0].file == "Plugin.cs"
    assert diagnostics[0].line == 42
    assert diagnostics[0].column == 17
    assert diagnostics[0].code == "CS0246"
    assert diagnostics[0].severity == "error"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Plugin.cs(1,1): error CS1002: ; expected", "syntax_error"),
        ("Plugin.cs(1,1): error CS0234: namespace missing", "namespace_error"),
        ("Plugin.cs(1,1): error CS1061: method missing", "api_mismatch"),
        ("Plugin.cs(1,1): error CS0122: inaccessible", "il2cpp_access_error"),
        ("runtime config binding failed", "config_binding_error"),
        ("unsafe path access denied", "unsafe_path_error"),
    ],
)
def test_error_classifier_taxonomy(output: str, expected: str) -> None:
    error_class, _ = BuildErrorClassifier().classify(output)

    assert error_class == expected


def test_supplied_build_output_is_classified_without_running_command() -> None:
    result = BuildAdapter().from_supplied_output(
        feature_id="feature_001",
        profile=_profile(),
        exit_code=1,
        stderr="Plugin.cs(12,3): error CS1061: method missing",
        duration_ms=15,
    )
    payload = result.to_artifact_payload()

    assert payload["execution_mode"] == "supplied_output"
    assert payload["status"] == "failed"
    assert payload["error_class"] == "api_mismatch"
    assert payload["repair_handoff"]["allowed"] is True
    assert payload["real_build_performed"] is False
    assert payload["claims_real_build_success"] is False
    assert payload["diagnostics"][0]["code"] == "CS1061"


def test_local_build_requires_explicit_execution_approval() -> None:
    called = False

    def runner(profile: BuildProfile) -> BuildCommandResult:
        nonlocal called
        called = True
        return BuildCommandResult(exit_code=0, stdout="ok")

    result = BuildAdapter().run_local(
        feature_id="feature_001",
        profile=_profile(),
        command_runner=runner,
        allow_execution=False,
    )

    assert called is False
    assert result.execution_mode == "local"
    assert result.status == "skipped"
    assert result.real_build_performed is False
    assert result.claims_real_build_success is False


def test_local_build_with_zero_exit_without_expected_artifact_does_not_claim_success(
    tmp_path: Path,
) -> None:
    def runner(profile: BuildProfile) -> BuildCommandResult:
        assert profile.profile_id == "test_dotnet"
        return BuildCommandResult(exit_code=0, stdout="Build succeeded", duration_ms=9)

    result = BuildAdapter().run_local(
        feature_id="feature_001",
        profile=_profile(working_directory=str(tmp_path)),
        command_runner=runner,
        allow_execution=True,
    )
    payload = result.to_artifact_payload()

    assert result.status == "failed"
    assert result.build_status == "artifact_verification_failed"
    assert result.real_build_performed is True
    assert result.claims_real_build_success is False
    assert payload["artifact_verification"]["status"] == "failed"
    assert payload["artifact_verification"]["blockers"][0]["code"] == (
        "EXPECTED_ARTIFACT_MISSING"
    )
    assert payload["repair_handoff"]["allowed"] is True
    assert payload["repair_handoff"]["failure_evidence_refs"] == [
        "artifact_verification"
    ]


def test_local_build_claims_success_only_after_expected_artifact_verified(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "bin" / "Debug" / "BetterHitFeedback.dll"

    def runner(profile: BuildProfile) -> BuildCommandResult:
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"verified dll bytes")
        return BuildCommandResult(exit_code=0, stdout="Build succeeded", duration_ms=9)

    result = BuildAdapter().run_local(
        feature_id="feature_001",
        profile=_profile(working_directory=str(tmp_path)),
        command_runner=runner,
        allow_execution=True,
    )
    payload = result.to_artifact_payload()

    assert result.status == "success"
    assert result.real_build_performed is True
    assert result.claims_real_build_success is True
    assert payload["artifact_verification"]["status"] == "verified"
    assert payload["verified_artifacts"][0]["path"] == "bin/Debug/BetterHitFeedback.dll"
    assert payload["verified_artifacts"][0]["sha256"]
    assert payload["verified_artifacts"][0]["mtime"] > 0
    assert payload["repair_handoff"]["allowed"] is False


def test_local_build_blocks_unsafe_expected_artifact_path(tmp_path: Path) -> None:
    def runner(profile: BuildProfile) -> BuildCommandResult:
        return BuildCommandResult(exit_code=0, stdout="Build succeeded", duration_ms=9)

    result = BuildAdapter().run_local(
        feature_id="feature_001",
        profile=_profile_with_expected(
            working_directory=str(tmp_path),
            expected_artifacts=("../outside.dll",),
        ),
        command_runner=runner,
        allow_execution=True,
    )
    payload = result.to_artifact_payload()

    assert result.status == "failed"
    assert result.claims_real_build_success is False
    assert payload["artifact_verification"]["status"] == "failed"
    assert payload["artifact_verification"]["blockers"][0]["code"] == (
        "UNSAFE_EXPECTED_ARTIFACT_PATH"
    )
    assert payload["repair_handoff"]["allowed"] is True


def test_fake_build_result_never_claims_real_build_success() -> None:
    payload = build_fake_build_result(
        feature_id="feature_001",
        input_execution_mode="fake",
    ).to_artifact_payload()

    assert payload["execution_mode"] == "fake"
    assert payload["status"] == "skipped"
    assert payload["build_status"] == "fake_success"
    assert payload["real_build_performed"] is False
    assert payload["claims_real_build_success"] is False


def test_build_result_artifact_contract_requires_structured_fields(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStoreError, match="missing required fields"):
        store.write(
            feature_id="feature_001",
            artifact_type="build_result",
            payload={"node_name": "build", "stage": "build", "message": "too small"},
        )


def test_build_profile_registry_reads_config_shape() -> None:
    registry = BuildProfileRegistry.from_config(
        {
            "build": {
                "profiles": [
                    {
                        "profile_id": "gtfo_bepinex_il2cpp",
                        "build_system": "dotnet",
                        "working_directory": "generated_mods/BetterHitFeedback",
                        "command": ["dotnet", "build"],
                        "timeout_seconds": 120,
                        "expected_artifacts": ["bin/Debug/BetterHitFeedback.dll"],
                    }
                ]
            }
        }
    )

    profile = registry.get("gtfo_bepinex_il2cpp")
    assert profile.command == ("dotnet", "build")
    assert profile.expected_artifacts == ("bin/Debug/BetterHitFeedback.dll",)
