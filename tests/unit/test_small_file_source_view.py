"""Small current C# files use one complete source unit without invented methods."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.evidence.requirement_coverage import (
    default_feature_requirement_projection,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.evidence.requirement_coverage_provider import build_requirement_coverage_pack
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider, materialize_source_location
from src.mod_agent.evidence.source_view import run_small_file_max_bytes, source_view_policy
from src.mod_agent.execution.patch_apply import PatchApplyError, materialize_exact_text_patch
from src.mod_agent.planning import FeatureSpec, ImplementationPlanner
from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopError,
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
)


def _configuration(tmp_path):
    fixture = Path(__file__).parents[1] / "fixtures/patch_eval/accurate_crosshair/AccurateCrosshair/Configuration.cs"
    raw = fixture.read_bytes()
    assert len(raw) == 3923 and len(raw.decode("utf-8").splitlines()) == 80
    assert hashlib.sha256(raw).hexdigest() == "f77ba2545051aa9fd4b31f8822fa53a47dd671a522124fc19ec2f6a3810b5601"
    path = tmp_path / "generated_mods/AccurateCrosshair/Configuration.cs"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return path, raw


def test_configuration_view_includes_binding_read_write_flow(tmp_path):
    path, raw = _configuration(tmp_path)
    legacy = materialize_source_location(workspace_root=tmp_path, selected_path=path,
        selected_line=5, source_bytes=raw, tokens=["configuration"])
    assert "BindAll" not in legacy.excerpt
    provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192)
    selected = provider.collect(query="FollowsRecoil", search_root="generated_mods/AccurateCrosshair", max_items=1)
    assert len(selected.items) == 1
    item = selected.items[0]
    assert "BindAll" in item.excerpt
    assert item.excerpt == raw.decode("utf-8") and item.span == {"start_line": 1, "end_line": 80}
    assert item.source_hash == hashlib.sha256(raw).hexdigest() and path.read_bytes() == raw
    assert item.method_name is item.method_kind is item.declaring_type is None


def _formal_pack(item):
    feature = FeatureSpec(feature_id="whole-config", user_request="Change the FollowsRecoil default and preserve saved settings.",
        target_behavior="Use the requested default with existing explicit configuration retained.",
        non_goals=("Preserve other configuration keys.",), target_mod="AccurateCrosshair", risk_level="low",
        acceptance_criteria=("The default and explicit saved settings behave as requested.",),
        evidence_requirements=("Current complete configuration source.",), runtime_verification_plan=())
    payload = feature.to_artifact_payload()
    projection = materialize_requirement_coverage_projection(feature_data=payload,
        request=feature.user_request, projection=default_feature_requirement_projection(payload))
    findings = {"findings": []}
    for index, requirement in enumerate(projection["requirements"], 1):
        deferred = requirement["role"] == "post_change_acceptance"
        findings["findings"].append({"relation_index": index,
            "relationship": "missing" if deferred else "support",
            "evidence_ids": [] if deferred else [item.evidence_id],
            "edit_target_evidence_ids": [item.evidence_id] if requirement["role"] == "change" else [],
            "unresolved_gaps": ["Observe changed behavior after implementation."] if deferred else []})
    pack = build_requirement_coverage_pack(query=feature.user_request, materialized_projection=projection,
        retrieved_pack=EvidencePack(query=feature.user_request, readiness="partial", can_generate_patch=False,
            items=(item,)), findings=findings).to_artifact_payload()
    return feature, pack


def test_whole_file_enters_real_model_view_and_original_binding_materializer(tmp_path):
    path, raw = _configuration(tmp_path)
    item = materialize_source_location(workspace_root=tmp_path, selected_path=path, selected_line=5,
        source_bytes=raw, tokens=["configuration"], small_file_max_bytes=8192)
    feature, pack = _formal_pack(item)
    selector = ModelPlanningTargetSelector(client=SimpleNamespace(provider="offline", model="no-model"),
        workspace_root=tmp_path, receipt_path=tmp_path / "unused.json")
    request = selector.prepare(feature.to_artifact_payload(), pack)
    source = request.messages[1].content["source_observations"][0]
    assert source["excerpt"] == raw.decode("utf-8-sig")
    assert all(value in source["excerpt"] for value in ("FollowsRecoil", "BindAll", "OnFileChanged"))
    assert request.messages[1].content["allowed_edit_evidence_ids"] == [item.evidence_id]
    assert item.symbol is item.method_name is item.declaring_type is None
    plan = ImplementationPlanner().build(feature_spec=feature, evidence_pack=pack,
        formal_requirement_coverage_required=True, planning_target_evidence_ids=(item.evidence_id,))
    assert not plan.blocking
    payload = plan.to_artifact_payload()
    binding = payload["binding_registry"]["edit_bindings"][0]
    assert binding["target_span"] == {"start_line": 1, "end_line": 80}
    inspector = PlanBoundSourceInspector(workspace_root=tmp_path, implementation_plan=payload,
        policy=PatchAgentLoopPolicy())
    assert inspector.available_binding_ids == (binding["binding_id"],)
    before = next(line for line in raw.decode("utf-8").splitlines(keepends=True)
                  if "FollowsRecoil" in line and "true" in line)
    changes = [{"edit_binding_id": binding["binding_id"], "patch": {"kind": "exact_text_replace",
        "before_text": before, "after_text": before.replace("true", "false", 1), "expected_occurrences": 1}}]
    result = materialize_exact_text_patch(workspace_root=tmp_path, diff_intent=changes, implementation_plan=payload)
    assert result.files[item.source_path] != raw and path.read_bytes() == raw
    changed = deepcopy(payload)
    changed["binding_registry"]["edit_bindings"][0]["source_hash"] = "0" * 64
    with pytest.raises(PatchApplyError, match="source_hash"):
        materialize_exact_text_patch(workspace_root=tmp_path, diff_intent=changes, implementation_plan=changed)
    changed["binding_registry"]["edit_bindings"][0]["canonical_target_path"] = "../outside.cs"
    with pytest.raises(PatchApplyError, match="workspace-relative|escapes"):
        materialize_exact_text_patch(workspace_root=tmp_path, diff_intent=changes, implementation_plan=changed)
    path.write_bytes(raw + b"// source changed\n")
    with pytest.raises(PatchAgentLoopError, match="SOURCE_HASH_MISMATCH"):
        PlanBoundSourceInspector(workspace_root=tmp_path, implementation_plan=payload, policy=PatchAgentLoopPolicy())


def test_same_file_matches_and_query_lanes_use_one_unit_and_keep_other_file(tmp_path):
    path, _ = _configuration(tmp_path)
    other = path.with_name("Other.cs")
    other.write_text("class Other { bool FollowsRecoil; void BindAll() {} }\n", encoding="utf-8")
    provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192)
    one = provider.collect(query="FollowsRecoil BindAll", search_root="generated_mods", max_items=2)
    assert len(one.items) == len({item.source_path for item in one.items}) == 2
    queries = tuple({"query_id": f"q{index}", "requirement_id": "r1", "query": query}
                    for index, query in enumerate(("FollowsRecoil", "BindAll"), 1))
    combined = provider.collect_query_set(queries=queries, search_root="generated_mods", max_items=2)
    assert len(combined.items) == len({item.evidence_id for item in combined.items}) == 2
    assert all(row["evidence_ids"] for row in combined.budget_summary["per_query_execution"])


def test_byte_boundary_crlf_bom_and_disabled_method_consumers(tmp_path):
    path, raw = _configuration(tmp_path)
    crlf = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    path.write_bytes(crlf)
    whole = materialize_source_location(workspace_root=tmp_path, selected_path=path, selected_line=23,
        source_bytes=crlf, tokens=[], small_file_max_bytes=len(crlf))
    assert whole.excerpt.encode("utf-8") == crlf and whole.span == {"start_line": 1, "end_line": 80}
    assert whole.source_hash == hashlib.sha256(crlf).hexdigest()
    for threshold in (0, len(crlf) - 1):
        method = materialize_source_location(workspace_root=tmp_path, selected_path=path, selected_line=23,
            source_bytes=crlf, tokens=[], small_file_max_bytes=threshold)
        assert method.method_name == "Configuration" and method.span == {"start_line": 23, "end_line": 27}
    assert RgLiveEvidenceProvider(tmp_path).small_file_max_bytes == 0
    with pytest.raises(ValueError, match="SELECTED_LINE_INVALID"):
        materialize_source_location(workspace_root=tmp_path, selected_path=path, selected_line=81,
            source_bytes=crlf, tokens=[], small_file_max_bytes=8192)
    with pytest.raises(ValueError, match="SOURCE_VIEW_PATH_ESCAPE"):
        materialize_source_location(workspace_root=tmp_path, selected_path=tmp_path.parent / "Outside.cs",
            selected_line=1, source_bytes=crlf, tokens=[], small_file_max_bytes=8192)


def test_run_policy_restores_same_units_and_legacy_absence_keeps_old_view(tmp_path):
    path, raw = _configuration(tmp_path)
    manifest = tmp_path / "run_manifest.json"
    assert run_small_file_max_bytes(tmp_path) == 0
    manifest.write_text(json.dumps({"run_id": "old"}), encoding="utf-8")
    assert run_small_file_max_bytes(tmp_path) == 0
    policy = source_view_policy(8192)
    manifest.write_text(json.dumps({"run_id": "new", "source_view_policy": policy}), encoding="utf-8")
    provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=run_small_file_max_bytes(tmp_path))
    item = provider.collect(query="FollowsRecoil", search_root="generated_mods", max_items=1).items[0]
    fresh = materialize_source_location(workspace_root=tmp_path, selected_path=path, selected_line=5,
        source_bytes=raw, tokens=[], small_file_max_bytes=8192)
    assert item.to_dict() == fresh.to_dict()
    for malformed in ({"schema_version": "wrong", "small_file_max_bytes": 8192},
                      {"schema_version": "source_view_policy_v1", "small_file_max_bytes": True}, None):
        manifest.write_text(json.dumps({"source_view_policy": malformed}), encoding="utf-8")
        with pytest.raises(ValueError, match="SOURCE_VIEW"):
            run_small_file_max_bytes(tmp_path)


@pytest.mark.parametrize("value", [-1, True, "8192", None])
def test_invalid_size_policy_is_rejected(value, tmp_path):
    with pytest.raises(ValueError, match="SOURCE_VIEW_SMALL_FILE_LIMIT_INVALID"):
        RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=value)
