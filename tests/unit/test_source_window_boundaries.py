"""Fallback source windows must not borrow part of a known adjacent method."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.mod_agent.evidence import rg_live
from src.mod_agent.evidence.rg_live import _rank_distinct_match_lines, materialize_source_location
from src.mod_agent.evidence.source_window import fallback_source_window
from src.mod_agent.planning import ImplementationPlanner


def _actual_configuration(tmp_path, suffix=".cs"):
    fixture = Path(__file__).parents[1] / "fixtures/patch_eval/accurate_crosshair/AccurateCrosshair/Configuration.cs"
    raw = fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "f77ba2545051aa9fd4b31f8822fa53a47dd671a522124fc19ec2f6a3810b5601"
    path = tmp_path / ("generated_mods/AccurateCrosshair/Configuration" + suffix)
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return path, raw


def _materialize(root, path, raw, line):
    return materialize_source_location(workspace_root=root, selected_path=path,
        selected_line=line, source_bytes=raw, tokens=["configuration"])


def test_actual_header_and_constructor_are_independent_complete_read_units(tmp_path):
    path, raw = _actual_configuration(tmp_path)
    header = _materialize(tmp_path, path, raw, 5)
    constructor = _materialize(tmp_path, path, raw, 23)
    units, blocker = ImplementationPlanner._normalize_edit_units([header.to_dict(), constructor.to_dict()])
    assert blocker is None, {"header_span": header.span, "constructor_span": constructor.span, "blocker": blocker}
    assert header.span == {"start_line": 1, "end_line": 22}
    assert constructor.span == {"start_line": 23, "end_line": 27}
    assert len(units) == 2
    lines = raw.decode("utf-8").splitlines(keepends=True)
    assert header.excerpt == "".join(lines[:22])
    assert lines[4] in header.excerpt and lines[11] in header.excerpt
    assert "static Configuration()" not in header.excerpt
    assert header.source_hash == hashlib.sha256(raw).hexdigest()
    identity = f"{header.source_path}:{header.source_hash}:1:22".encode()
    assert header.evidence_id == "rg_live_" + hashlib.sha256(identity).hexdigest()[:16]
    assert header.evidence_id != "rg_live_f3b8910257b96db9"
    assert constructor.evidence_id == "rg_live_a83947aa80b459bf"
    assert header.method_name is None and path.read_bytes() == raw


def _separated_regions():
    lines = ["// padding\n"] * 42
    replacements = {1: "namespace Example\n", 2: "{\n", 3: "    public class Example\n", 4: "    {\n",
        5: "        // AnchorToken AnchorToken\n", 10: "        public void First()\n", 11: "        {\n",
        12: "            Work();\n", 13: "            Work();\n", 14: "        }\n",
        20: "        // AnchorToken\n", 25: "        public void Second()\n", 26: "        {\n",
        27: "            Work();\n", 28: "            Work();\n", 29: "        }\n",
        34: "        // AfterToken\n", 41: "    }\n", 42: "}\n"}
    for number, text in replacements.items():
        lines[number - 1] = text
    return lines


def test_retrieval_dedup_uses_the_same_smaller_window_and_keeps_other_region():
    lines = _separated_regions()
    selected = _rank_distinct_match_lines(((5, lines[4]), (20, lines[19])), ["anchortoken"], lines=lines)
    assert selected == (5, 20)


@pytest.mark.parametrize("line,expected", [(5, (1, 9)), (20, (15, 24)), (34, (30, 42))])
def test_fallback_before_between_after_methods_keeps_match_and_exact_bytes(tmp_path, line, expected):
    lines = _separated_regions()
    raw = "".join(lines).encode("utf-8")
    path = tmp_path / "Example.cs"
    path.write_bytes(raw)
    item = _materialize(tmp_path, path, raw, line)
    assert item.span == {"start_line": expected[0], "end_line": expected[1]}
    assert item.excerpt == "".join(lines[expected[0] - 1:expected[1]])
    assert expected[0] <= line <= expected[1] and lines[line - 1] in item.excerpt
    assert item.source_hash == hashlib.sha256(raw).hexdigest()
    assert item.method_name is item.method_kind is None


@pytest.mark.parametrize("line,expected,method", [
    (21, (21, 21), None), (23, (23, 27), "Configuration"), (36, (35, 48), "OnFileChanged")])
def test_fields_and_complete_method_units_are_not_cropped(tmp_path, line, expected, method):
    path, raw = _actual_configuration(tmp_path)
    item = _materialize(tmp_path, path, raw, line)
    assert item.span == {"start_line": expected[0], "end_line": expected[1]}
    assert item.method_name == method
    assert item.excerpt == "".join(raw.decode("utf-8").splitlines(keepends=True)[expected[0] - 1:expected[1]])
    if method == "OnFileChanged":
        assert item.parameter_types is None  # Incomplete identity does not shorten a known method.


def test_known_method_contains_match_even_if_method_context_is_unavailable(tmp_path, monkeypatch):
    path, raw = _actual_configuration(tmp_path)
    monkeypatch.setattr(rg_live, "_enclosing_csharp_method", lambda *_a, **_k: None)
    item = _materialize(tmp_path, path, raw, 36)
    assert item.span == {"start_line": 26, "end_line": 54}
    assert item.method_name is None
    assert item.excerpt == "".join(raw.decode("utf-8").splitlines(keepends=True)[25:54])


def test_non_csharp_fallback_retains_original_window_despite_csharp_looking_text(tmp_path):
    path, raw = _actual_configuration(tmp_path, suffix=".txt")
    assert _materialize(tmp_path, path, raw, 5).span == {"start_line": 1, "end_line": 23}


def test_no_known_methods_or_invalid_method_boundaries_keep_original_window():
    assert fallback_source_window(selected_line=25, line_count=70) == (15, 43)
    assert fallback_source_window(selected_line=25, line_count=70,
        method_spans=({"start_line": 10, "end_line": None},)) == (15, 43)


def test_matches_in_the_same_preserved_non_method_neighborhood_still_deduplicate():
    lines = _separated_regions()
    lines[7] = "        // AnchorToken\n"
    selected = _rank_distinct_match_lines(((5, lines[4]), (8, lines[7]), (20, lines[19])),
                                          ["anchortoken"], lines=lines)
    assert selected == (5, 20)
