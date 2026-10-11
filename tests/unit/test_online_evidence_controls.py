"""Online comparison switches change execution/representation, not evidence authority."""
from copy import deepcopy

import pytest

from src.mod_agent.evidence import materialize_requirement_coverage_projection
from src.mod_agent.evidence.model_view import expand_findings_input_text
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
    make_requirement_coverage_evidence_provider,
)
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
from tests.unit.test_rg_live_query_reuse import count_dispatch, fixture, queries
from tests.unit.test_requirement_coverage import (
    _feature_data, _projection, _write_sources,
)


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", [], {}])
def test_switches_require_actual_booleans(tmp_path, invalid):
    with pytest.raises(ValueError, match="QUERY_OBSERVATION_REUSE_INVALID"):
        RgLiveEvidenceProvider(tmp_path, reuse_query_observations=invalid)
    with pytest.raises(ValueError, match="INPUT_COMPRESSION_INVALID"):
        StructuredModelRequirementCoverageProvider(lambda *_: None, compress_findings_input=invalid)
    with pytest.raises(ValueError, match="INPUT_COMPRESSION_INVALID"):
        make_requirement_coverage_evidence_provider(object(), complete_json=lambda *_: None,
            compress_findings_input=invalid)


@pytest.mark.parametrize("repeated", [True, False])
def test_query_switch_preserves_bytes_hashes_and_all_lane_mappings(tmp_path, monkeypatch, repeated):
    _, root = fixture(tmp_path)
    (root / "Consumer.cs").write_text("public class Consumer { bool Configuration = false; }\n")
    calls = count_dispatch(monkeypatch)
    q = queries("Configuration", "Configuration" if repeated else "Consumer", "Absent")
    packs = []
    counts = []
    for enabled in (False, True):
        start = len(calls)
        provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192,
            reuse_query_observations=enabled)
        pack = provider.collect_query_set(queries=q, search_root=root, max_items=4,
            source_identity_query="Plugin.cs")
        assert provider.reuse_query_observations is enabled
        assert pack.budget_summary["query_observation_reuse"].get("enabled", True) is enabled
        counts.append(len(calls) - start)
        result = pack.to_artifact_payload()
        result.pop("timing")
        result["budget_summary"].pop("query_observation_reuse")
        for row in result["budget_summary"]["per_query_execution"]:
            row.pop("observation_reused")
            row.pop("reused_from_lane")
        packs.append(result)
    assert counts == ([4, 3] if repeated else [4, 4])
    assert packs[0] == packs[1]
    assert len(packs[0]["items"]) == 2
    assert not packs[0]["can_generate_patch"]


@pytest.mark.parametrize("enabled", [False, True])
def test_source_drift_rejection_is_not_disabled_by_comparison_switch(tmp_path, monkeypatch, enabled):
    _, root = fixture(tmp_path)
    provider = RgLiveEvidenceProvider(tmp_path, reuse_query_observations=enabled)
    actual = provider.collect
    def collect(**kwargs):
        pack = actual(**kwargs)
        (root / "Plugin.cs").write_text("public class Changed {}\n")
        return pack
    monkeypatch.setattr(provider, "collect", collect)
    with pytest.raises(ValueError, match="RG_LIVE_QUERY_SET_SOURCE_CHANGED"):
        provider.collect_query_set(queries=queries("Configuration", "Configuration"),
            search_root=root, max_items=2)


@pytest.mark.parametrize("long_repeated", [False, True])
@pytest.mark.parametrize("reassessment", [False, True])
def test_findings_switch_changes_only_reversible_representation(tmp_path, long_repeated, reassessment):
    _write_sources(tmp_path)
    feature = _feature_data()
    projection = _projection()
    if long_repeated:
        text = "ChangeMarker preserves every current API and configuration obligation. " * 35
        feature["user_request"] = feature["target_behavior"] = text
        projection["requirements"][0]["text"] = text
    materialized = materialize_requirement_coverage_projection(feature_data=feature,
        request=feature["user_request"], projection=projection)
    retrieved = RgLiveEvidenceProvider(tmp_path).collect_query_set(
        queries=tuple(materialized["queries"]), search_root="generated_mods/SyntheticMod",
        max_items=len(materialized["queries"]))
    calls, outputs = [], []
    def complete(role, payload, schema):
        calls.append((role, deepcopy(payload), deepcopy(schema)))
        return {"findings": [{"relation_index": row["relation_index"], "relationship": "missing",
            "evidence_ids": [], "edit_target_evidence_ids": [],
            "unresolved_gaps": ["Current callback ownership remains unverified."]}
            for row in payload["relations"]]}
    for enabled in (False, True):
        owner = make_requirement_coverage_evidence_provider(object(), complete_json=complete,
            compress_findings_input=enabled)
        provider = owner.semantic_provider
        assert provider.compress_findings_input is enabled
        outputs.append(provider.findings(materialized_projection=materialized,
            retrieved_pack=retrieved, request=feature["user_request"],
            semantic_feedback={"previous_gaps": ["callback ownership"]} if reassessment else None))
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0] and calls[0][2] == calls[1][2]
    raw, candidate = calls[0][1], calls[1][1]
    assert "findings_input_text_encoding" not in raw
    assert ("findings_input_text_encoding" in candidate) is long_repeated
    assert expand_findings_input_text(candidate) == raw
    assert candidate["source_observations"] == raw["source_observations"]
    assert candidate["rules"] == raw["rules"]
    assert outputs[0] == outputs[1]
    assert all(row["relationship"] == "missing" for row in outputs[0]["findings"])


def test_default_settings_keep_optimized_behavior(tmp_path):
    assert RgLiveEvidenceProvider(tmp_path).reuse_query_observations is True
    assert StructuredModelRequirementCoverageProvider(lambda *_: None).compress_findings_input is True
