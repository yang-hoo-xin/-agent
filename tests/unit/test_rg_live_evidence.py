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
