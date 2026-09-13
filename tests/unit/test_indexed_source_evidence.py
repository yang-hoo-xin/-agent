"""Physical source facts over the existing index; no models or compilation."""
from __future__ import annotations

import hashlib
import json

import pytest

from src.mod_agent.evidence.indexed_source import IndexedSourceEvidenceProvider


def _source(tmp_path):
    root = tmp_path / "generated_mods" / "Example"
    root.mkdir(parents=True)
    source = root / "State.cs"
    lines = ["namespace Example;", "public sealed class State", "{", "    public void HandleState()", "    {"]
    lines.extend(f"        int step{number} = {number};" for number in range(100))
    lines.extend(['        string note = "状态同步";', "    }", "}"])
    raw = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    source.write_bytes(raw)
    return root, source, raw, lines


def _query(text, query_id="query_001", requirement_id="requirement_001"):
    return {"query_id": query_id, "query": text, "requirement_id": requirement_id}


def test_indexed_source_preserves_found_configuration_in_findings_with_four_item_budget(tmp_path, monkeypatch):
    """Real indexes reach the Findings completion boundary; no model is called."""
    from src.mod_agent.evidence import (
        StructuredModelRequirementCoverageProvider,
        default_feature_requirement_projection,
        materialize_requirement_coverage_projection,
    )
    from src.mod_agent.evidence.requirement_coverage_provider import _source_observation_model_view
    from src.mod_agent.evidence.retriever import DeterministicEvidenceRetriever
    from tests.unit.test_requirement_coverage import _feature_data

    root = tmp_path / "generated_mods" / "Example"
    root.mkdir(parents=True)
    recoil = root / "RecoilState.cs"
    recoil.write_text(
        "namespace Example;\npublic sealed class RecoilState\n{\n"
        "    public void StartRecoil()\n    {\n    }\n"
        "    public void StopRecoil()\n    {\n    }\n"
        "    public void RefreshRecoil()\n    {\n    }\n"
        "    public void ResetRecoil()\n    {\n    }\n}\n", encoding="utf-8")
    preferences = root / "Preferences.cs"
    configuration_lines = [
        "namespace Example;", "public sealed class Preferences", "{",
        "    public string[] ReadOptions()", "    {",
        '        string section = "General Settings";',
        '        string key = "Follow Recoil";',
        "        return new[] { section, key };", "    }", "}",
    ]
    configuration_bytes = ("\r\n".join(configuration_lines) + "\r\n").encode("utf-8")
    preferences.write_bytes(configuration_bytes)
    original_bm25 = DeterministicEvidenceRetriever._bm25_items
    found_lexical_items = []

    def observe_bm25(retriever, **kwargs):
        items, failure = original_bm25(retriever, **kwargs)
        found_lexical_items.extend(items)
        return items, failure

    monkeypatch.setattr(DeterministicEvidenceRetriever, "_bm25_items", observe_bm25)
    provider = IndexedSourceEvidenceProvider(tmp_path, tmp_path / "a" / "source_index")
    query = _query("Follow Recoil General Settings")
    pack = provider.collect_query_set(queries=(query,), search_root=root.relative_to(tmp_path), max_items=4)
    lanes = pack.budget_summary["per_query_execution"][0]["deterministic_lane_coverage"]
    assert next(row for row in lanes if row["lane"] == "symbol_metadata")["hit_count"] >= 4
    assert any(item.source_path == preferences.name and '"Follow Recoil"' in item.excerpt
               for item in found_lexical_items), "The real BM25 lane must find the configuration literals."
    feature = _feature_data()
    feature.update(user_request=query["query"], target_behavior="Read the current Follow Recoil configuration.",
                   evidence_requirements=["Read the General Settings binding."], non_goals=[],
                   acceptance_criteria=[], runtime_verification_plan=[])
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature, request=query["query"], projection=default_feature_requirement_projection(feature))
    captured = []

    class FindingsInputCapturedError(RuntimeError):
        """Stop before any completion or fabricated semantic finding."""

    def capture_findings_input(role, payload, schema):
        captured.append((role, payload, schema))
        raise FindingsInputCapturedError()

    semantic_provider = StructuredModelRequirementCoverageProvider(capture_findings_input)
    with pytest.raises(FindingsInputCapturedError):
        semantic_provider.findings(materialized_projection=materialized, retrieved_pack=pack,
                                   request=query["query"])
    assert len(captured) == 1 and captured[0][0] == "requirement_findings"
    findings_payload = captured[0][1]
    assert findings_payload["message_type"] == "product_requirement_findings"
    source_observations = findings_payload["source_observations"]
    assert source_observations == [_source_observation_model_view(item.to_dict()) for item in pack.items]
    projected_configuration = [row for row in source_observations
                               if row["source_path"] == preferences.relative_to(tmp_path).as_posix()]
    assert projected_configuration, "Found configuration was lost before the actual Findings completion input."
    configuration_item = next(item for item in pack.items
                              if item.source_path == projected_configuration[0]["source_path"])
    assert configuration_item.source_ref == str(preferences.resolve())
    assert configuration_item.source_hash == hashlib.sha256(configuration_bytes).hexdigest()
    assert configuration_item.span == {"start_line": 4, "end_line": 9}
    assert projected_configuration[0]["excerpt"] == "\r\n".join(configuration_lines[3:9]) + "\r\n"
    assert any(item.source_path == recoil.relative_to(tmp_path).as_posix() for item in pack.items)
    assert len(pack.items) <= pack.budget_summary["max_items"] == 4
    assert pack.budget_summary["query_count"] == 1
    assert sum(len(item.excerpt.encode("utf-8")) for item in pack.items) <= 16384
    assert len(json.dumps({"source_observations": source_observations}, ensure_ascii=False).encode("utf-8")) <= 32768
    assert pack.can_generate_patch is False
    assert preferences.read_bytes() == configuration_bytes


def test_indexed_source_materializes_complete_live_method_and_stable_cross_lane_identity(tmp_path):
    root, source, raw, lines = _source(tmp_path)
    provider = IndexedSourceEvidenceProvider(tmp_path, tmp_path / "a" / "source_index")
    symbol = provider.collect_query_set(queries=(_query("HandleState"),),
        search_root=root.relative_to(tmp_path), max_items=1)
    lexical = provider.collect_query_set(queries=(_query("状态同步"),),
        search_root=root.relative_to(tmp_path), max_items=1)
    assert len(symbol.items) == len(lexical.items) == 1
    assert symbol.items[0].to_dict() == lexical.items[0].to_dict()
    item = lexical.items[0]
    assert item.source_ref == str(source.resolve())
    assert item.source_path == "generated_mods/Example/State.cs"
    assert item.source_hash == hashlib.sha256(raw).hexdigest()
    assert item.excerpt == "\r\n".join(lines[3:-1]) + "\r\n"
    assert item.span == {"start_line": 4, "end_line": len(lines) - 1}
    assert item.method_name == "HandleState" and item.declaring_type_full_name == "Example.State"
    assert len(item.excerpt) > 240 and item.span["end_line"] - item.span["start_line"] > 80
    assert item.retrieval_method == "indexed_source"
    assert symbol.budget_summary["per_query_execution"][0]["indexed_hits"][0]["retrieval_method"] == "symbol_exact"
    assert lexical.budget_summary["per_query_execution"][0]["indexed_hits"][0]["retrieval_method"] == "bm25"
    assert lexical.can_generate_patch is False
    assert provider.database.db_path.is_file()


def test_indexed_source_keeps_original_query_identities_and_global_allowance(tmp_path):
    root, _source_path, _raw, _lines = _source(tmp_path)
    (root / "Other.cs").write_text(
        "public sealed class Other\n{\n    public void OtherState()\n    {\n    }\n}\n", encoding="utf-8")
    provider = IndexedSourceEvidenceProvider(tmp_path, tmp_path / "a" / "source_index")
    queries = (_query("HandleState", "original_query_A", "original_requirement_A"),
        _query("OtherState", "original_query_B", "original_requirement_B"))
    pack = provider.collect_query_set(queries=queries, search_root=root.relative_to(tmp_path), max_items=2)
    assert len(pack.items) == 2
    assert [row["query_id"] for row in pack.budget_summary["per_query_execution"]] == [item["query_id"] for item in queries]
    assert [row["requirement_id"] for row in pack.budget_summary["per_query_execution"]] == [item["requirement_id"] for item in queries]
    assert pack.budget_summary["query_count"] == pack.budget_summary["max_items"] == 2
    assert pack.budget_summary["all_queries_executed"] is True
    assert {item.method_name for item in pack.items} == {"HandleState", "OtherState"}
    other = tmp_path / "generated_mods" / "AnotherProject"
    other.mkdir()
    with pytest.raises(ValueError, match="INDEXED_SOURCE_SCOPE_CHANGED"):
        provider.collect_query_set(queries=(_query("HandleState"),), search_root=other.relative_to(tmp_path), max_items=1)


def test_indexed_source_rejects_source_change_during_lookup(tmp_path, monkeypatch):
    root, source, raw, _lines = _source(tmp_path)
    provider = IndexedSourceEvidenceProvider(tmp_path, tmp_path / "a" / "source_index")
    provider.collect_query_set(queries=(_query("HandleState"),), search_root=root.relative_to(tmp_path), max_items=1)
    retrieve = provider._retriever.retrieve

    def mutate_then_retrieve(request, **kwargs):
        source.write_bytes(raw + b"// changed during lookup\r\n")
        return retrieve(request, **kwargs)

    monkeypatch.setattr(provider._retriever, "retrieve", mutate_then_retrieve)
    with pytest.raises(ValueError):
        provider.collect_query_set(queries=(_query("状态同步"),), search_root=root.relative_to(tmp_path), max_items=1)


@pytest.mark.parametrize("caller_first", [False, True])
def test_indexed_exact_symbol_keeps_declaration_when_caller_matches_more_terms(tmp_path, monkeypatch, caller_first):
    root = tmp_path / "generated_mods" / "Example"
    root.mkdir(parents=True)
    declaration = ["    public void HandleState()", "    {", "    }"]
    caller = ["    public void RunAudit()", "    {", "        // audit",
              "        HandleState();", "        HandleState();", "    }"]
    lines = ["namespace Example;", "public sealed class State", "{",
             *(caller + declaration if caller_first else declaration + caller), "}"]
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    source = root / "State.cs"
    source.write_bytes(raw)
    provider = IndexedSourceEvidenceProvider(tmp_path, tmp_path / "a" / "source_index")
    observed_hits = []
    materialize = provider._materialize_hit

    def record_hit(hit, query, max_items):
        observed_hits.append(hit)
        return materialize(hit, query, max_items)

    monkeypatch.setattr(provider, "_materialize_hit", record_hit)
    pack = provider.collect_query_set(queries=(_query("HandleState audit"),),
        search_root=root.relative_to(tmp_path), max_items=1)
    assert observed_hits[0].symbol == "HandleState"
    assert observed_hits[0].retrieval_method == "symbol_exact"
    assert observed_hits[0].span == {"start_line": 1, "end_line": len(lines)}
    assert len(pack.items) == 1 and pack.items[0].method_name == "HandleState"
    start = lines.index(declaration[0]) + 1
    assert pack.items[0].span == {"start_line": start, "end_line": start + 2}
    assert pack.items[0].excerpt == "\n".join(declaration) + "\n"
    assert pack.items[0].source_hash == hashlib.sha256(raw).hexdigest()
    assert pack.budget_summary["max_items"] == 1
    assert pack.budget_summary["per_query_execution"][0]["evidence_ids"] == [pack.items[0].evidence_id]
    assert pack.can_generate_patch is False
    assert source.read_bytes() == raw
