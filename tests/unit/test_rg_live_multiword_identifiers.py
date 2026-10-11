"""Explicit code names keep declaration priority in natural-language queries."""
import hashlib

import pytest

from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider


def _provider(tmp_path):
    (tmp_path / "Owner.cs").write_text(
        "namespace API;\npublic class SettingsApi\n{\n"
        "    public static int SetLimit(int value) => value;\n}\n", encoding="utf-8")
    (tmp_path / "Consumer.cs").write_text(
        "public class Consumer\n{\n" + "\n".join(
            f"    public int Read{i}() => SettingsApi.SetLimit(1); // API definition method signature configuration runtime"
            for i in range(30)) + "\n}\n", encoding="utf-8")
    return RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192)


@pytest.mark.parametrize("query", [
    "API.SettingsApi definition and SetLimit method signature",
    "SettingsApi type definition",
    "SetLimit method signature",
])
def test_multiword_identifier_definition_beats_repeated_callers(tmp_path, query):
    provider = _provider(tmp_path)
    pack = provider.collect_query_set(
        queries=({"query_id": "q1", "requirement_id": "r1", "query": query},),
        search_root=".", max_items=1)
    assert len(pack.items) == 1
    item = pack.items[0]
    assert item.source_path == "Owner.cs"
    assert item.excerpt == (tmp_path / "Owner.cs").read_bytes().decode("utf-8")
    assert item.source_hash == hashlib.sha256((tmp_path / "Owner.cs").read_bytes()).hexdigest()
    assert pack.can_generate_patch is False
    assert pack.readiness == "insufficient"
    assert pack.budget_summary["max_items"] == 1
    assert pack.budget_summary["per_query_execution"] == [{
        "query_id": "q1", "requirement_id": "r1",
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "retrieval_status": "source_observations_returned", "evidence_ids": [item.evidence_id],
        "observation_reused": False, "reused_from_lane": None,
        "source_revision": provider._query_batch_revision("."),
    }]
    assert "request_identifier_queries" not in pack.budget_summary


def test_semantic_multiword_query_keeps_content_frequency_order(tmp_path):
    provider = _provider(tmp_path)
    (tmp_path / "Configuration.cs").write_text(
        "public class Configuration\n{\n    // runtime\n}\n", encoding="utf-8")
    pack = provider.collect(query="configuration runtime", search_root=".", max_items=1)
    assert pack.items[0].source_path == "Consumer.cs"


def test_explicit_filename_scope_is_not_overridden_by_named_type(tmp_path):
    provider = _provider(tmp_path)
    pack = provider.collect(query="SettingsApi definition in Consumer.cs", search_root=".", max_items=1)
    assert pack.items[0].source_path == "Consumer.cs"
    assert pack.can_generate_patch is False


def test_missing_named_declaration_does_not_invent_material(tmp_path):
    provider = _provider(tmp_path)
    pack = provider.collect(query="MissingApi missingMethod", search_root=".", max_items=1)
    assert pack.items == ()
    assert pack.can_generate_patch is False
