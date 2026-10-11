import json
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
from src.mod_agent.evidence.small_project_context import context_policy
from src.mod_agent.evidence.source_view import whole_file_source_item


def provider(tmp_path, monkeypatch, *, status="no_matches", enabled=True):
    result = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192,
                                   small_project_context_policy=context_policy(enabled=enabled))
    def collect(**kwargs):
        return replace(EvidencePack.empty(query=kwargs["query"], reason="empty"),
                       budget_summary={"retrieval_status": status})
    monkeypatch.setattr(result, "collect", collect)
    return result


def query(value, *, identity=None, max_items=4, root="."):
    return value.collect_query_set(queries=({"query_id": "q", "query": "future-setting",
                                            "requirement_id": "r"},),
                                   source_identity_query=identity, search_root=root, max_items=max_items)


def test_empty_small_project_retains_exact_bytes_without_inventing_matches(tmp_path, monkeypatch):
    source = tmp_path / "DifferentName.cs"
    raw = b"namespace Other;\r\npublic class Empty {}\r\n"
    source.write_bytes(raw)
    pack = query(provider(tmp_path, monkeypatch))
    assert pack.items == (whole_file_source_item(workspace_root=tmp_path, selected_path=source, source_bytes=raw),)
    assert pack.readiness == "insufficient" and pack.can_generate_patch is False
    assert pack.budget_summary["per_query_execution"][0]["retrieval_status"] == "no_matches"
    assert pack.budget_summary["per_query_execution"][0]["evidence_ids"] == []
    audit = pack.budget_summary["small_project_context"]
    assert audit["bytes_read"] == len(raw)
    assert audit["evidence_ids"] == [pack.items[0].evidence_id]
    assert audit["lexical_match_claimed"] is audit["semantic_support_claimed"] is False


@pytest.mark.parametrize("count,size,max_items,reason", [
    (5, 30, 8, "file_limit_exceeded"), (2, 30, 1, "file_limit_exceeded"),
    (1, 8193, 4, "file_size_limit_exceeded"), (2, 4097, 4, "total_byte_limit_exceeded"),
])
def test_over_limit_discards_whole_context(tmp_path, monkeypatch, count, size, max_items, reason):
    for index in range(count):
        (tmp_path / f"Source{index}.cs").write_bytes(b"a" * size)
    pack = query(provider(tmp_path, monkeypatch), max_items=max_items)
    assert not pack.items
    assert pack.budget_summary["small_project_context"]["reason"] == reason
    assert pack.budget_summary["small_project_context"]["bytes_read"] == 0


def test_entry_budget_bounds_enumeration(tmp_path, monkeypatch):
    for index in range(257):
        (tmp_path / f"file{index}.txt").write_bytes(b"")
    pack = query(provider(tmp_path, monkeypatch))
    assert not pack.items
    assert pack.budget_summary["small_project_context"]["reason"] == "entry_limit_reached"
    assert pack.budget_summary["small_project_context"]["enumerated_entries"] == 256


@pytest.mark.parametrize("status,identity,enabled", [
    ("tool_failed", None, True), ("source_scope_rejected", None, True),
    ("source_decode_failed", None, True), ("requested_source_no_matches", None, True),
    ("no_matches", "Missing.cs", True), ("no_matches", None, False),
])
def test_errors_explicit_identity_and_disabled_policy_never_fallback(tmp_path, monkeypatch, status, identity, enabled):
    (tmp_path / "Other.cs").write_text("class Other {}", encoding="utf-8")
    pack = query(provider(tmp_path, monkeypatch, status=status, enabled=enabled), identity=identity)
    assert not pack.items and "small_project_context" not in pack.budget_summary


def test_build_directories_excluded_and_invalid_utf8_not_partially_returned(tmp_path, monkeypatch):
    for name in ("obj", "bin", ".git"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "Generated.cs").write_bytes(b"a" * 9000)
    (tmp_path / "Good.cs").write_bytes(b"class Good {}")
    selected = provider(tmp_path, monkeypatch)
    assert len(query(selected).items) == 1
    (tmp_path / "Invalid.cs").write_bytes(b"\xff")
    assert not query(selected).items


def test_reparse_file_rejected_without_following_link(tmp_path, monkeypatch):
    source = tmp_path / "Bad.cs"
    source.write_text("class Bad {}", encoding="utf-8")
    original = Path.lstat
    def lstat(path):
        if path == source:
            return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        return original(path)
    monkeypatch.setattr(Path, "lstat", lstat)
    pack = query(provider(tmp_path, monkeypatch))
    assert not pack.items
    assert pack.budget_summary["small_project_context"]["reason"] == "source_entry_not_plain"


def test_manifest_restores_selected_policy_and_missing_field_disables_it(tmp_path):
    manifest = tmp_path / "run_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    assert RgLiveEvidenceProvider(tmp_path).small_project_context_policy["enabled"] is False
    manifest.write_text(json.dumps({"small_project_context_policy": context_policy(enabled=True)}), encoding="utf-8")
    assert RgLiveEvidenceProvider(tmp_path).small_project_context_policy == context_policy(enabled=True)


def test_context_cannot_escape_existing_search_root(tmp_path, monkeypatch):
    (tmp_path / "Small").mkdir()
    (tmp_path / "Other.cs").write_bytes(b"class Other {}")
    assert not query(provider(tmp_path, monkeypatch), root="Small").items
    assert not query(provider(tmp_path, monkeypatch), root="../").items


def test_real_lexical_miss_uses_context_and_real_match_does_not(tmp_path):
    (tmp_path / "Empty.cs").write_bytes(b"namespace Demo; public class Empty {}")
    actual = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192,
                                   small_project_context_policy=context_policy(enabled=True))
    missed = query(actual)
    assert len(missed.items) == 1
    assert missed.budget_summary["per_query_execution"][0]["retrieval_status"] == "no_matches"
    matched = actual.collect_query_set(queries=({"query_id": "q", "query": "Demo",
        "requirement_id": "r"},), search_root=".", max_items=1)
    assert len(matched.items) == 1
    assert "small_project_context" not in matched.budget_summary
    assert matched.items[0].evidence_id == missed.items[0].evidence_id
