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

    assert pack.can_generate_patch is True
    assert pack.retrieval_methods_used == ("rg_live_read",)
    assert pack.items[0].source_path == (
        "generated_mods/BetterHitFeedback/Patches/Behavior.cs"
    )
    assert pack.items[0].file_hash
    assert "KillMarkerColor" in pack.items[0].excerpt


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
