import hashlib
from pathlib import Path

import pytest

from src.mod_agent.evidence import RgLiveEvidenceProvider


ACTUAL10_QUERY_LEADS = (
    "AccurateCrosshair General Settings Accurate Spread Enabled",
    "AccurateCrosshair config schema settings reference",
    "AccurateCrosshair source code spread calculation logic",
    "AccurateCrosshair target source or API evidence",
    "AccurateCrosshair config or text evidence",
    "AccurateCrosshair current source or docs evidence",
    "AccurateCrosshair config schema or settings reference",
    "AccurateCrosshair compile or static validation",
    "AccurateCrosshair runtime verification plan",
)

FRESH_COVERAGE_QUERY_SET = (
    {
        "query_id": "query_f954f68f1a95e0a95c2f",
        "query": "Accurate Spread Enabled configuration",
        "requirement_id": "requirement_a476d29ffd1c10ad91ee",
    },
    {
        "query_id": "query_facaac1a61d631334397",
        "query": "crosshairSize raw value retention",
        "requirement_id": "requirement_a476d29ffd1c10ad91ee",
    },
    {
        "query_id": "query_a74014a840fe9851135b",
        "query": "accurate spread calculation bypass logic",
        "requirement_id": "requirement_a476d29ffd1c10ad91ee",
    },
    {
        "query_id": "query_16f168648a21cb04fadc",
        "query": "existing crosshair behaviors",
        "requirement_id": "requirement_30da24706aa4de0be3f4",
    },
    {
        "query_id": "query_df1b917fbb0cb15b7ef3",
        "query": "crosshair rendering logic preservation",
        "requirement_id": "requirement_30da24706aa4de0be3f4",
    },
    {
        "query_id": "query_4edc6b6e3ef6da6a2039",
        "query": "source code for spread calculation",
        "requirement_id": "requirement_d924b496285926bfe2a6",
    },
    {
        "query_id": "query_c5bdbae4734a49d436a6",
        "query": "configuration schema for crosshair settings",
        "requirement_id": "requirement_d924b496285926bfe2a6",
    },
    {
        "query_id": "query_291de5e6f9ebf9478095",
        "query": "API documentation for crosshairSize",
        "requirement_id": "requirement_d924b496285926bfe2a6",
    },
)


def _write_actual10_source_fixture(root: Path) -> Path:
    source_root = root / "generated_mods" / "AccurateCrosshair"
    patches = source_root / "CrosshairPatches"
    patches.mkdir(parents=True)
    (source_root / "Configuration.cs").write_text(
        "using BepInEx.Configuration;\n"
        "\n"
        "namespace AccurateCrosshair\n"
        "{\n"
        "    public static class Configuration\n"
        "    {\n"
        "        public static bool FollowsRecoil { get; private set; } = true;\n"
        "        public static bool PopEnabled { get; private set; } = false;\n"
        "\n"
        "        private static ConfigFile configFile;\n"
        "\n"
        "        static Configuration()\n"
        "        {\n"
        "            configFile = new ConfigFile(Paths.ConfigPath + \".cfg\");\n"
        "            BindAll(configFile);\n"
        "        }\n"
        "\n"
        "        private static void BindAll(ConfigFile config)\n"
        "        {\n"
        "            string section = \"General Settings\";\n"
        "            string key = \"Follow Recoil\";\n"
        "            FollowsRecoil = config.Bind(section, key, FollowsRecoil).Value;\n"
        "            key = \"First Shot Display Mode\";\n"
        "            config.Bind(section, key, \"Inner\");\n"
        "            key = \"Pop Enabled\";\n"
        "            PopEnabled = config.Bind(section, key, PopEnabled).Value;\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (patches / "SpreadPatches.cs").write_text(
        "namespace AccurateCrosshair.CrosshairPatches\n"
        "{\n"
        "    internal static class SpreadPatches\n"
        "    {\n"
        "        private static float _targetSpread;\n"
        "\n"
        "        private static bool OverrideCrosshairSize(ref float crosshairSize)\n"
        "        {\n"
        "            float spread;\n"
        "            spread = aimSpread + hipFireSpread;\n"
        "            _targetSpread = spread;\n"
        "            crosshairSize = GetCrosshairSize();\n"
        "            return true;\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (source_root / "Loader.cs").write_text(
        "namespace AccurateCrosshair\n"
        "{\n"
        "    internal sealed class Loader\n"
        "    {\n"
        "        // target source API evidence; current source docs evidence.\n"
        "        // compile static validation; runtime verification plan.\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    return source_root


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


def test_rg_live_provider_blocks_search_root_outside_workspace(tmp_path: Path) -> None:
    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="BoundarySignal",
        search_root="../outside-workspace",
    )

    assert pack.items == ()
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.blockers[0]["code"] == "INSUFFICIENT_EVIDENCE"
    assert pack.blockers[0]["message"].startswith("Search root escapes workspace:")


def test_rg_live_query_set_rejects_insufficient_item_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="^RG_LIVE_QUERY_SET_BUDGET_INVALID$"):
        RgLiveEvidenceProvider(tmp_path).collect_query_set(
            queries=(
                {
                    "query_id": "query_one",
                    "query": "BoundarySignal",
                    "requirement_id": "requirement_one",
                },
            ),
            search_root="generated_mods/Example",
            max_items=0,
        )


def test_rg_live_query_set_rejects_duplicate_query_id(tmp_path: Path) -> None:
    source = tmp_path / "generated_mods" / "Example" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text("public sealed class Behavior {}\n", encoding="utf-8")
    queries = (
        {
            "query_id": "query_repeated",
            "query": "Behavior",
            "requirement_id": "requirement_one",
        },
        {
            "query_id": "query_repeated",
            "query": "Behavior",
            "requirement_id": "requirement_two",
        },
    )

    with pytest.raises(ValueError, match="^RG_LIVE_QUERY_SET_ID_DUPLICATE$"):
        RgLiveEvidenceProvider(tmp_path).collect_query_set(
            queries=queries,
            search_root="generated_mods/Example",
            max_items=len(queries),
        )


def test_rg_live_query_set_uses_spare_budget_for_second_source_occurrences(
    tmp_path: Path,
) -> None:
    root = tmp_path / "generated_mods" / "Example"
    root.mkdir(parents=True)
    behavior = root / "Behavior.cs"
    behavior.write_text(
        "namespace Example;\n"
        "public static class Behavior\n"
        "{\n"
        "    public static void ApplyToggle()\n"
        "    {\n"
        "        // toggle enabled configuration authority behavior\n"
        "        // toggle enabled configuration authority behavior\n"
        "        // toggle enabled configuration authority behavior\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    configuration = root / "Configuration.cs"
    configuration.write_text(
        "namespace Example;\n"
        "public static class Configuration\n"
        "{\n"
        "    public static bool ToggleEnabled { get; private set; } = true;\n"
        "\n"
        "    private static void OnFileChanged()\n"
        "    {\n"
        "        ToggleEnabled = ReadToggleEnabledConfiguration();\n"
        "    }\n"
        "\n"
        "    private static void BindAll()\n"
        "    {\n"
        "        ToggleEnabled = BindToggleEnabledConfigurationAuthority();\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    queries = (
        {
            "query_id": "query_toggle_one",
            "query": "toggle enabled configuration authority",
            "requirement_id": "requirement_toggle_one",
        },
        {
            "query_id": "query_toggle_two",
            "query": "toggle enabled configuration authority",
            "requirement_id": "requirement_toggle_two",
        },
    )

    provider = RgLiveEvidenceProvider(tmp_path)
    first = provider.collect_query_set(
        queries=queries,
        search_root="generated_mods/Example",
        max_items=4,
    )
    second = provider.collect_query_set(
        queries=queries,
        search_root="generated_mods/Example",
        max_items=4,
    )

    first_identity = [
        (
            item.evidence_id,
            item.source_path,
            item.method_name,
            item.span,
            item.source_hash,
        )
        for item in first.items
    ]
    assert first_identity == [
        (
            item.evidence_id,
            item.source_path,
            item.method_name,
            item.span,
            item.source_hash,
        )
        for item in second.items
    ]
    assert len(first.items) == 4
    assert first.items[0].source_path.endswith("/Behavior.cs")
    assert {item.method_name for item in first.items} >= {
        "ApplyToggle",
        "OnFileChanged",
        "BindAll",
    }
    assert any(
        "public static bool ToggleEnabled" in item.excerpt
        for item in first.items
    )
    assert all(item.span and item.source_hash for item in first.items)
    assert len({item.evidence_id for item in first.items}) == len(first.items)
    expected_ids = [item.evidence_id for item in first.items]
    assert [
        row["evidence_ids"]
        for row in first.budget_summary["per_query_execution"]
    ] == [expected_ids, expected_ids]
    assert first.timing["final_count"] == 4.0
    assert first.budget_summary["max_items"] == 4
    assert first.readiness == "insufficient"
    assert first.can_generate_patch is False
    assert first.to_artifact_payload()["authoritative_for_patch"] is False


def test_fresh_coverage_query_set_retains_four_site_current_source_evidence() -> None:
    fixture_root = Path(__file__).parents[1] / "fixtures"
    source_root = fixture_root / "actual15_four_site_source"
    expected_source_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_root.glob("*.cs")
    }

    pack = RgLiveEvidenceProvider(fixture_root).collect_query_set(
        queries=FRESH_COVERAGE_QUERY_SET,
        search_root="actual15_four_site_source",
        max_items=8,
    )

    assert len(pack.items) <= 8
    assert any(
        "public static bool FollowsRecoil" in item.excerpt
        for item in pack.items
    )
    assert {item.method_name for item in pack.items} >= {
        "OnFileChanged",
        "BindAll",
        "OverrideCrosshairSize",
    }
    assert all(
        item.source_hash
        == expected_source_hashes[Path(item.source_path).name]
        for item in pack.items
    )
    assert [
        row["query_id"]
        for row in pack.budget_summary["per_query_execution"]
    ] == [row["query_id"] for row in FRESH_COVERAGE_QUERY_SET]
    assert pack.budget_summary["all_queries_executed"] is True
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False


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


def test_actual10_configuration_query_selects_bind_all_method_span(
    tmp_path: Path,
) -> None:
    source_root = _write_actual10_source_fixture(tmp_path)
    source = source_root / "Configuration.cs"

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="AccurateCrosshair config schema settings reference",
        search_root="generated_mods/AccurateCrosshair",
    )

    item = pack.items[0]
    assert item.source_path == "generated_mods/AccurateCrosshair/Configuration.cs"
    assert item.source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert item.source_hash == item.file_hash == item.doc_hash
    assert item.span == {"start_line": 18, "end_line": 29}
    assert item.excerpt.splitlines()[0] == (
        "        private static void BindAll(ConfigFile config)"
    )
    assert "config.Bind(section, key, FollowsRecoil).Value" in item.excerpt
    assert item.symbol == "BindAll"
    assert item.method_name == "BindAll"
    assert item.declaring_type == "Configuration"
    assert item.declaring_type_full_name == "AccurateCrosshair.Configuration"


def test_actual10_spread_query_selects_override_method_span(tmp_path: Path) -> None:
    source_root = _write_actual10_source_fixture(tmp_path)
    source = source_root / "CrosshairPatches" / "SpreadPatches.cs"

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="AccurateCrosshair source code spread calculation logic",
        search_root="generated_mods/AccurateCrosshair",
    )

    item = pack.items[0]
    assert item.source_path == (
        "generated_mods/AccurateCrosshair/CrosshairPatches/SpreadPatches.cs"
    )
    assert item.source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert item.span == {"start_line": 7, "end_line": 16}
    assert item.excerpt.splitlines()[0] == (
        "        private static bool OverrideCrosshairSize(ref float crosshairSize)"
    )
    assert "spread = aimSpread + hipFireSpread;" in item.excerpt
    assert "crosshairSize = GetCrosshairSize();" in item.excerpt
    assert item.method_name == "OverrideCrosshairSize"
    assert item.declaring_type == "SpreadPatches"
    assert item.declaring_type_full_name == (
        "AccurateCrosshair.CrosshairPatches.SpreadPatches"
    )


def test_rg_live_non_method_match_keeps_bounded_context_without_symbol_fabrication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "Example" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "namespace Example\n"
        "{\n"
        "    public sealed class Behavior\n"
        "    {\n"
        "        public void EarlierMethod()\n"
        "        {\n"
        "            UseEarlierSignal();\n"
        "        }\n"
        "\n"
        "        private static string BoundarySignal = \"class-level\";\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect(
        query="BoundarySignal",
        search_root="generated_mods/Example",
    )

    item = pack.items[0]
    assert item.span == {"start_line": 1, "end_line": 12}
    assert item.method_name is None
    assert item.method_kind is None
    assert item.declaring_type is None


def test_actual10_query_set_retains_three_files_and_upgrades_method_evidence(
    tmp_path: Path,
) -> None:
    _write_actual10_source_fixture(tmp_path)
    queries = tuple(
        {
            "query_id": f"actual10_query_{index}",
            "query": query,
            "requirement_id": f"actual10_requirement_{index}",
        }
        for index, query in enumerate(ACTUAL10_QUERY_LEADS, 1)
    )

    pack = RgLiveEvidenceProvider(tmp_path).collect_query_set(
        queries=queries,
        search_root="generated_mods/AccurateCrosshair",
        max_items=len(queries),
    )

    assert pack.budget_summary["query_count"] == 9
    assert pack.budget_summary["all_queries_executed"] is True
    retained_ids = {item.evidence_id for item in pack.items}
    assert all(
        execution["evidence_ids"]
        and len(execution["evidence_ids"])
        == len(set(execution["evidence_ids"]))
        and set(execution["evidence_ids"]).issubset(retained_ids)
        for execution in pack.budget_summary["per_query_execution"]
    )
    assert any(
        len(execution["evidence_ids"]) > 1
        for execution in pack.budget_summary["per_query_execution"]
    )
    assert {
        item.source_path.rsplit("/", 1)[-1]
        for item in pack.items
    } == {"Configuration.cs", "Loader.cs", "SpreadPatches.cs"}
    configuration_items = [
        item for item in pack.items if item.source_path.endswith("/Configuration.cs")
    ]
    spread_items = [
        item for item in pack.items if item.source_path.endswith("/SpreadPatches.cs")
    ]
    assert configuration_items
    assert spread_items
    assert any(item.method_name == "BindAll" for item in configuration_items)
    assert any("config.Bind" in item.excerpt for item in configuration_items)
    assert any(item.method_name == "OverrideCrosshairSize" for item in spread_items)
    assert any("aimSpread + hipFireSpread" in item.excerpt for item in spread_items)
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.to_artifact_payload()["authoritative_for_patch"] is False
