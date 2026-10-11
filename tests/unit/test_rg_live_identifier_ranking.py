"""Named source definitions must survive a bounded caller-heavy search."""
import shutil
from pathlib import Path

from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider, _rank_files


def test_configuration_definition_not_starved_by_callers(tmp_path):
    fixture = Path(__file__).parents[1] / "fixtures/patch_eval/accurate_crosshair/AccurateCrosshair"
    target = tmp_path / "generated_mods/AccurateCrosshair"
    shutil.copytree(fixture, target)
    for name, count in (("FirstCaller", 20), ("SecondCaller", 30)):
        methods = "\n".join(f"public bool Value{i}() => Configuration.FollowsRecoil;" for i in range(count))
        (target / f"{name}.cs").write_text(f"class {name} {{\n{methods}\n}}", encoding="utf-8")
    pack = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192).collect(
        query="configuration", search_root="generated_mods/AccurateCrosshair", max_items=2)
    assert len(pack.items) == 2
    assert pack.items[0].source_path == "generated_mods/AccurateCrosshair/Configuration.cs"
    assert pack.items[0].excerpt == (target / "Configuration.cs").read_bytes().decode("utf-8")
    assert pack.can_generate_patch is False


def test_named_type_definition_precedes_repeated_caller_mentions():
    owner, consumer = Path("Options.cs"), Path("Consumer.cs")
    matches = [(owner, 1, "public class Settings {}"),
               *[(consumer, n, "var x = Settings.Load();") for n in range(1, 20)]]
    assert _rank_files(matches, ["settings"], requested_path=None)[0][0] == owner


def test_named_file_precedes_repeated_usage_without_a_type_declaration():
    owner, consumer = Path("Settings.cs"), Path("Consumer.cs")
    matches = [(owner, 1, "// Settings construction"),
               *[(consumer, n, "var x = Settings.Load();") for n in range(1, 20)]]
    assert _rank_files(matches, ["settings"], requested_path=None)[0][0] == owner


def test_explicit_source_selection_still_filters_named_definition():
    owner, requested = Path("Settings.cs"), Path("Consumer.cs")
    matches = [(owner, 1, "public class Settings {}"), (requested, 1, "Settings.Load();")]
    assert [p for p, _ in _rank_files(matches, ["settings"], requested_path=requested)] == [requested]


def test_nonidentifier_query_keeps_existing_content_ranking():
    first, second = Path("A.cs"), Path("B.cs")
    matches = [(first, 1, "// current value"), (second, 1, "// current value"),
               (second, 2, "// preserve value")]
    assert _rank_files(matches, ["value"], requested_path=None)[0][0] == second
