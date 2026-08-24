from pathlib import Path

from src.mod_agent.evidence import RgLiveEvidenceProvider


def test_rg_live_provider_returns_hashed_live_target_source(tmp_path: Path) -> None:
    source = tmp_path / "generated_mods" / "BetterHitFeedback" / "Patches" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "public static readonly Color KillMarkerColor = Color.Red;\n",
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="Make the kill marker pink without changing normal hit feedback.",
        search_root="generated_mods/BetterHitFeedback",
    )

    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.retrieval_methods_used == ("rg_live_read",)
    assert pack.items[0].source_path == (
        "generated_mods/BetterHitFeedback/Patches/Behavior.cs"
    )
    assert pack.items[0].file_hash
    assert "KillMarkerColor" in pack.items[0].excerpt
    assert pack.items[0].authority == "mod_agent_deterministic"
    assert pack.blockers == (
        {
            "code": "RG_LIVE_REQUIREMENT_COVERAGE_UNPROVEN",
            "message": (
                "Live lexical source observations do not establish explicit, "
                "verifiable requirement coverage."
            ),
            "needed_evidence": [
                "explicit requirement-to-evidence coverage",
            ],
        },
    )
    artifact = pack.to_artifact_payload()
    assert artifact["readiness"] == "insufficient"
    assert artifact["can_generate_patch"] is False
    assert artifact["authoritative_for_patch"] is False


def test_rg_live_provider_preserves_crlf_for_raw_exact_patch_binding(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "BetterHitFeedback" / "Plugin.cs"
    source.parent.mkdir(parents=True)
    raw_source = (
        b"public sealed class Plugin\r\n"
        b"{\r\n"
        b"    private bool ConfigEnabled = true;\r\n"
        b"}\r\n"
    )
    source.write_bytes(raw_source)

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="ConfigEnabled startup",
        search_root="generated_mods/BetterHitFeedback",
    )

    excerpt = pack.items[0].excerpt
    assert "\r\n" in excerpt
    assert "\n" not in excerpt.replace("\r\n", "")
    assert excerpt.encode("utf-8") in raw_source


def test_rg_live_provider_honors_one_exact_requested_source_filename(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated_mods" / "BetterHitFeedback"
    plugin = root / "Plugin.cs"
    reference = root / "Patches" / "Behavior.cs"
    reference.parent.mkdir(parents=True)
    plugin.write_text(
        "public sealed class Plugin\n"
        "{\n"
        "    public static object LogSource { get; private set; }\n"
        "\n"
        "    public void Load()\n"
        "    {\n"
        '        LogSource.Info("signal=PLUGIN_LOADED");\n'
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    reference.write_text(
        "public static class Behavior\n"
        "{\n"
        "    private static object Log => Plugin.LogSource;\n"
        "    private static object ConfigEnabled;\n"
        "}\n",
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query=(
            "PLUGIN_LOADED LogSource ConfigEnabled Plugin Load startup marker. "
            "Modify only Plugin.cs."
        ),
        search_root="generated_mods/BetterHitFeedback",
    )

    assert pack.can_generate_patch is False
    assert pack.items[0].source_path == "generated_mods/BetterHitFeedback/Plugin.cs"
    assert pack.items[0].method_name == "Load"
    assert "signal=PLUGIN_LOADED" in pack.items[0].excerpt


def test_rg_live_provider_preserves_exact_filename_identity_from_raw_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated_mods" / "BetterHitFeedback"
    root.mkdir(parents=True)
    (root / "Plugin.cs").write_text(
        'public sealed class Plugin { string marker = "PLUGIN_LOADED"; }\n',
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="modify only plugin.cs plugin_loaded.",
        source_identity_query="Modify only Plugin.cs PLUGIN_LOADED.",
        search_root="generated_mods/BetterHitFeedback",
    )

    assert pack.can_generate_patch is False
    assert pack.items[0].source_path == "generated_mods/BetterHitFeedback/Plugin.cs"


def test_rg_live_multiple_lexical_matches_do_not_proxy_requirement_coverage(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated_mods" / "Example"
    root.mkdir(parents=True)
    (root / "Behavior.cs").write_text(
        "public sealed class Behavior\n"
        "{\n"
        "    public void ApplyMarker() { MarkerColor = Pink; }\n"
        "    public void PreserveMarker() { MarkerColor = Original; }\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "Secondary.cs").write_text(
        "public sealed class Secondary { string MarkerColor = Pink; }\n",
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="marker color pink preserve original",
        search_root="generated_mods/Example",
    )

    assert len(pack.items) == 1
    assert pack.items[0].source_hash
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.blockers[0]["code"] == "RG_LIVE_REQUIREMENT_COVERAGE_UNPROVEN"


def test_rg_live_preservation_observation_remains_non_authoritative(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "Example" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "public sealed class Behavior\n"
        "{\n"
        "    public void PreserveOriginalFeedback()\n"
        "    {\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="preserve original feedback",
        search_root="generated_mods/Example",
    )

    assert pack.items[0].method_name == "PreserveOriginalFeedback"
    assert "PreserveOriginalFeedback" in pack.items[0].excerpt
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.to_artifact_payload()["authoritative_for_patch"] is False


def test_rg_live_provider_blocks_duplicate_exact_requested_source_filename(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated_mods" / "BetterHitFeedback"
    for relative in ("Plugin.cs", "Nested/Plugin.cs"):
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            'public sealed class Plugin { string marker = "PLUGIN_LOADED"; }\n',
            encoding="utf-8",
        )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="Modify only Plugin.cs PLUGIN_LOADED.",
        search_root="generated_mods/BetterHitFeedback",
    )

    assert pack.can_generate_patch is False
    assert pack.blockers[0]["message"].startswith(
        "The explicitly requested C# filename did not resolve to exactly one current source file."
    )
    assert "filename='Plugin.cs'; resolved_count=2;" in pack.blockers[0]["message"]


def test_rg_live_provider_blocks_requested_file_without_request_term_match(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated_mods" / "BetterHitFeedback"
    root.mkdir(parents=True)
    (root / "Plugin.cs").write_text(
        "public sealed class Empty {}\n",
        encoding="utf-8",
    )
    (root / "Behavior.cs").write_text(
        'public sealed class Behavior { string marker = "PLUGIN_LOADED"; }\n',
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="Modify only Plugin.cs PLUGIN_LOADED.",
        search_root="generated_mods/BetterHitFeedback",
    )

    assert pack.can_generate_patch is False
    assert (
        pack.blockers[0]["message"]
        == "The explicitly requested C# source file contained no request-term match."
    )


def test_rg_live_provider_binds_enclosing_csharp_method_declaration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "BetterHitFeedback" / "Plugin.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "public sealed class Plugin\n"
        "{\n"
        "    public override void Load()\n"
        "    {\n"
        + "".join(f"        var filler{index} = {index};\n" for index in range(12))
        + "        ConfigEnabled = Config.Bind(\"General\", \"Enabled\", true);\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="General Enabled startup",
        search_root="generated_mods/BetterHitFeedback",
    )

    item = pack.items[0]
    assert item.excerpt.splitlines()[0] == "    public override void Load()"
    assert item.symbol == "Load"
    assert item.declaring_type == "Plugin"
    assert item.method_name == "Load"
    assert item.parameter_types == ()
    assert item.return_type == "void"
    assert item.method_kind == "method"
    assert item.span is not None
    assert item.span["start_line"] == 3


def test_rg_live_provider_binds_declared_member_types_from_containing_type(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "Example" / "Plugin.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "namespace Example;\n"
        "\n"
        "public sealed class Plugin\n"
        "{\n"
        "    public static ConfigEntry<bool> ConfigEnabled { get; private set; } = null!;\n"
        "    private bool PrimitiveEnabled = true;\n"
        "\n"
        "    public override void Load()\n"
        "    {\n"
        "        var ConfigEnabled = Config.Bind(\"General\", \"Enabled\", true);\n"
        "        ApplyStartup();\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="ApplyStartup",
        search_root="generated_mods/Example",
    )

    assert pack.items[0].declared_member_types == {
        "ConfigEnabled": "ConfigEntry<bool>",
        "PrimitiveEnabled": "bool",
    }
    assert pack.items[0].to_dict()["declared_member_types"] == {
        "ConfigEnabled": "ConfigEntry<bool>",
        "PrimitiveEnabled": "bool",
    }
    assert pack.items[0].declaring_type_full_name == "Example.Plugin"
    assert pack.items[0].declared_members == {
        "ConfigEnabled": {
            "member_name": "ConfigEnabled",
            "member_kind": "property",
            "declared_type": "ConfigEntry<bool>",
            "declaring_type": "Example.Plugin",
            "declaration_span": {"start_line": 5, "end_line": 5},
            "is_static": True,
        },
        "PrimitiveEnabled": {
            "member_name": "PrimitiveEnabled",
            "member_kind": "field",
            "declared_type": "bool",
            "declaring_type": "Example.Plugin",
            "declaration_span": {"start_line": 6, "end_line": 6},
            "is_static": False,
        },
    }
