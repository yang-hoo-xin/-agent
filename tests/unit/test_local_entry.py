from pathlib import Path

import pytest

from src.mod_agent.local_entry import (
    LocalEntryError,
    _project_text_property,
    _resolve_project_path_property,
    _sanitized_endpoint_url,
    _source_disclosure_record,
    _verify_source_disclosure,
    run_local_request,
)


def test_resolve_project_path_property_uses_project_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "generated_mods" / "BetterHitFeedback"
    project_dir.mkdir(parents=True)
    expected = tmp_path / "local_refs" / "gtfo_r8" / "BepInEx"
    expected.mkdir(parents=True)
    project_file = project_dir / "BetterHitFeedback.csproj"
    project_file.write_text(
        "<Project><PropertyGroup>"
        "<BepInExDir>..\\..\\local_refs\\gtfo_r8\\BepInEx</BepInExDir>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )

    resolved = _resolve_project_path_property(
        project_file,
        property_name="BepInExDir",
    )

    assert resolved == expected.resolve()


def test_resolve_project_path_property_rejects_missing_property(tmp_path: Path) -> None:
    project_file = tmp_path / "Target.csproj"
    project_file.write_text("<Project />", encoding="utf-8")

    with pytest.raises(LocalEntryError, match="does not define BepInExDir"):
        _resolve_project_path_property(project_file, property_name="BepInExDir")


def test_run_request_blocks_source_access_without_explicit_disclosure_consent(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "runs"

    with pytest.raises(LocalEntryError, match="--allow-source-disclosure"):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=workspace,
            settings_path=tmp_path / "missing-settings.yaml",
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
        )

    assert not workspace.exists()


def test_source_disclosure_record_is_explicit_and_does_not_contain_api_key() -> None:
    record = _source_disclosure_record(
        provider="openai",
        model="qwen3.6-plus",
        base_url="https://example.invalid/compatible-mode/v1",
        approved_at="2026-07-12T00:00:00+00:00",
    )

    assert record == {
        "approved": True,
        "approved_at": "2026-07-12T00:00:00+00:00",
        "approval_actor_type": "local_cli_invoker",
        "consent_mechanism": "--allow-source-disclosure",
        "destination": {
            "provider": "openai",
            "model": "qwen3.6-plus",
            "base_url": "https://example.invalid/compatible-mode/v1",
        },
        "approved_data_classes": [
            "natural_language_request",
            "retrieved_local_source_excerpts",
            "binding_registry",
            "side_effect_boundaries",
        ],
        "requested_data_classes": [
            "natural_language_request",
            "retrieved_local_source_excerpts",
            "binding_registry",
            "side_effect_boundaries",
        ],
        "scope": "this_run_only",
    }
    assert "api_key" not in str(record).lower()


def test_source_disclosure_blocks_unapproved_new_data_class() -> None:
    record = _source_disclosure_record(
        provider="openai",
        model="qwen3.6-plus",
        base_url="https://example.invalid/compatible-mode/v1",
        approved_at="2026-07-12T00:00:00+00:00",
    )

    with pytest.raises(LocalEntryError, match="runtime_logs"):
        _verify_source_disclosure(
            record,
            requested_data_classes=("retrieved_local_source_excerpts", "runtime_logs"),
        )


def test_endpoint_metadata_strips_userinfo_query_and_fragment() -> None:
    sanitized = _sanitized_endpoint_url(
        "https://local-key@example.invalid/compatible/v1?token=secret#fragment"
    )

    assert sanitized == "https://example.invalid/compatible/v1"
    assert "local-key" not in sanitized
    assert "secret" not in sanitized


def test_project_text_property_reads_non_better_hit_feedback_assembly(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "AnotherMod.csproj"
    project_file.write_text(
        "<Project><PropertyGroup><AssemblyName>AnotherMod</AssemblyName>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )

    assert (
        _project_text_property(project_file, property_name="AssemblyName")
        == "AnotherMod"
    )
