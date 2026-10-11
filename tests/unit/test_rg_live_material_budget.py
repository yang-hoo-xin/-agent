"""Offline material-budget counterexamples; fixtures do not claim task success."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from src.mod_agent.evidence import requirement_coverage_provider as coverage
from src.mod_agent.evidence import rg_live
from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
from src.mod_agent.evidence.source_view import whole_file_source_item


def queries(*texts):
    return tuple({"query_id": f"q{i}", "query": text, "requirement_id": f"r{i}"}
                 for i, text in enumerate(texts))


def item(root, name, text=None):
    return whole_file_source_item(workspace_root=root, selected_path=root / name,
        source_bytes=(text or f"public class {Path(name).stem} {{ }}\n").encode("utf-8"))


def provider_with_lanes(tmp_path, monkeypatch, lanes, *, reuse=True):
    provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192, reuse_query_observations=reuse)
    monkeypatch.setattr(provider, "_query_batch_revision", lambda _: {
        "source_sha256": "a" * 64, "strategy_sha256": "b" * 64})
    calls = []

    def collect(*, query, search_root, max_items):
        calls.append((query, max_items))
        found = lanes.get(query, ())
        return EvidencePack(query=query, readiness="insufficient", can_generate_patch=False,
            items=tuple(found), budget_summary={"retrieval_status": "source_observations_returned" if found else "no_matches"})

    monkeypatch.setattr(provider, "collect", collect)
    return provider, calls


def test_two_requirement_queries_keep_three_collaborating_sources(tmp_path, monkeypatch):
    metadata, logic, entry = (item(tmp_path, name) for name in ("Metadata.cs", "Logic.cs", "EntryHost.cs"))
    source, calls = provider_with_lanes(tmp_path, monkeypatch, {
        "ModuleRoot": (metadata, logic), "CoreLogic": (logic, entry)})
    projected = {"requirements": [{}, {}], "relations": [], "queries": list(queries("ModuleRoot", "CoreLogic"))}
    monkeypatch.setattr(coverage, "materialize_requirement_coverage_projection", lambda **_: deepcopy(projected))
    monkeypatch.setattr(coverage, "build_requirement_coverage_pack", lambda **kwargs: kwargs["retrieved_pack"])
    received = []
    owner = coverage.RequirementCoverageEvidenceProvider(source,
        projection_factory=lambda _: {}, findings_factory=lambda projection, pack: received.append(pack) or {"findings": []})
    pack = owner.collect(query="ModuleRoot CoreLogic", search_root=".", feature_data={})
    assert {x.source_path for x in pack.items} == {"Metadata.cs", "Logic.cs", "EntryHost.cs"}
    assert all(limit == 4 for _, limit in calls)
    assert received[0].items == pack.items
    assert pack.budget_summary["source_material_budget"]["max_excerpt_utf8_bytes"] == 32768
    assert pack.budget_summary["source_material_budget_selection"]["query_count"] == 2
    assert not pack.can_generate_patch


def test_larger_query_sets_keep_the_original_material_floor(tmp_path):
    provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192)
    budget = provider.query_set_material_budget(query_count=8)
    assert budget["max_items"] == 8
    assert budget["max_excerpt_utf8_bytes"] == 65536


def test_item_limit_discloses_already_read_but_omitted_sources(tmp_path, monkeypatch):
    materials = [item(tmp_path, f"Part{i}.cs") for i in range(3)]
    provider, _ = provider_with_lanes(tmp_path, monkeypatch, {
        "One": (materials[0], materials[2]), "Two": (materials[1],)})
    pack = provider.collect_query_set(queries=queries("One", "Two"), search_root=".", max_items=2)
    omitted = pack.budget_summary["source_material_omissions"]["omitted_read_materials"]
    assert len(pack.items) == 2 and len(omitted) == 1
    assert omitted[0]["source_path"] == "Part2.cs"
    assert omitted[0]["source_hash"] == materials[2].source_hash
    assert omitted[0]["reason"] == "material_item_limit" and omitted[0]["source_read"] is True
    assert pack.budget_summary["source_material_omissions"]["omitted_ids_are_citeable"] is False


def test_byte_limit_preserves_complete_small_material_after_large_omission(tmp_path, monkeypatch):
    first, too_big, small = item(tmp_path, "First.cs", "x" * 10000), item(tmp_path, "Big.cs", "y" * 8000), item(tmp_path, "Small.cs", "z" * 500)
    provider, _ = provider_with_lanes(tmp_path, monkeypatch, {"One": (first, small), "Two": (too_big,)})
    pack = provider.collect_query_set(queries=queries("One", "Two"), search_root=".", max_items=2)
    assert [x.source_path for x in pack.items] == ["First.cs", "Small.cs"]
    assert pack.budget_summary["source_material_budget"]["retained_excerpt_utf8_bytes"] == 10500
    assert pack.excluded[0]["source_path"] == "Big.cs"
    assert pack.excluded[0]["reason"] == "source_excerpt_byte_limit"
    assert pack.items[0].excerpt == first.excerpt


def test_reuse_switch_preserves_selection_and_omission_facts(tmp_path, monkeypatch):
    materials = tuple(item(tmp_path, f"Part{i}.cs") for i in range(4))
    packs, counts = [], []
    for reuse in (True, False):
        provider, calls = provider_with_lanes(tmp_path, monkeypatch, {"Shared": materials}, reuse=reuse)
        packs.append(provider.collect_query_set(queries=queries("Shared", "Shared"), search_root=".", max_items=2))
        counts.append(len(calls))
    assert counts == [1, 2]
    assert packs[0].items == packs[1].items and packs[0].excluded == packs[1].excluded
    assert packs[0].budget_summary["source_material_omissions"] == packs[1].budget_summary["source_material_omissions"]


def test_explicit_file_query_does_not_expand_to_other_files(tmp_path, monkeypatch):
    focus, other = tmp_path / "Focus.cs", tmp_path / "Other.cs"
    focus.write_text("public class Focus { }\n")
    other.write_text("public class Other { Focus field; }\n")
    monkeypatch.setattr(rg_live.subprocess, "run", lambda command, **_: CompletedProcess(command, 0,
        f"{focus}:1:public class Focus {{ }}\n{other}:1:public class Other {{ Focus field; }}\n", ""))
    provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192)
    pack = provider.collect(query="Focus.cs", search_root=".", max_items=4)
    assert [x.source_path for x in pack.items] == ["Focus.cs"]
    assert pack.budget_summary["source_selection"]["omitted_matched_sources"] == []


def test_findings_receives_omission_facts_without_new_citation_or_authority(tmp_path):
    from tests.unit.test_requirement_coverage import _feature_data, _projection

    feature = _feature_data()
    materialized = coverage.materialize_requirement_coverage_projection(
        feature_data=feature, request=feature["user_request"], projection=_projection())
    kept, omitted = item(tmp_path, "Kept.cs"), item(tmp_path, "Unshown.cs")
    audit = {"omitted_read_materials": [{"evidence_id": omitted.evidence_id, "source_path": omitted.source_path,
        "source_hash": omitted.source_hash, "source_read": True, "reason": "material_item_limit"}],
        "semantic_coverage_claimed": False, "omitted_ids_are_citeable": False}
    pack = replace(EvidencePack.empty(query="x", reason="fixture"), items=(kept,),
        budget_summary={"source_material_budget": {"max_items": 1}, "source_material_omissions": audit})
    captured = []

    def complete(role, payload, schema):
        captured.append((deepcopy(payload), deepcopy(schema)))
        raise RuntimeError("stop_before_model")

    provider = coverage.StructuredModelRequirementCoverageProvider(complete)
    with pytest.raises(RuntimeError, match="stop_before_model"):
        provider.findings(materialized_projection=materialized, retrieved_pack=pack, request=feature["user_request"])
    payload, schema = captured[0]
    assert payload["source_material_omissions"] == audit
    assert [x["evidence_id"] for x in payload["source_observations"]] == [kept.evidence_id]
    assert omitted.evidence_id not in str(schema)
    assert any("not citeable" in rule for rule in payload["rules"])
    assert pack.can_generate_patch is False
