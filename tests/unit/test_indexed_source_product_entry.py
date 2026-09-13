"""Selectable local source index through run-request with deterministic HTTP.

The compiler callback is the existing baseline double. No model, embedding,
compiler, product Apply, game, or Cloud service is executed by these tests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.upstream_trace import payload_sha256
from src.observability.patch_langfuse_query import join_local_journal, summarize_execution
from tests.unit.test_mod_agent_cli import _public_patch_upstream_scenario
from tests.unit.test_upstream_langfuse_query import cloud_row


def _indexed_sources(root):
    (root / "Plugin.cs").write_text(
        "namespace Example;\npublic sealed class Plugin\n{\n"
        "    public void Load() {}\n}\n", encoding="utf-8")
    (root / "SharedState.cs").write_text(
        "namespace Example;\npublic sealed class SharedState\n{\n"
        "    public void RefreshSharedState()\n    {\n"
        "        // 状态同步\n    }\n}\n", encoding="utf-8")


def _complete_patch_lines(content):
    for change in content["changes"]:
        change["after_text"] = "\n".join(line.rstrip(" \t")
            for line in change["after_text"].splitlines()) + "\n"
    return content


def _indexed_case(tmp_path, monkeypatch, capsys, trigger):
    from src.mod_agent.evidence.indexed_source import IndexedSourceEvidenceProvider

    indexed_searches = []
    collect = IndexedSourceEvidenceProvider.collect_query_set

    def observe(provider, **kwargs):
        result = collect(provider, **kwargs)
        indexed_searches.append((provider, kwargs, result))
        return result

    monkeypatch.setattr(IndexedSourceEvidenceProvider, "collect_query_set", observe)
    observed = _public_patch_upstream_scenario(
        tmp_path, monkeypatch, capsys, source_retrieval_mode="indexed_source",
        source_setup=_indexed_sources, upstream_query="状态同步",
        patch_response_transform=_complete_patch_lines,
        initial_findings_gap=trigger == "A", fail_first=trigger == "C",
        request_patch_upstream=trigger in {"B", "C"}, task_limit=10 if trigger == "C" else 9,
    )
    observed.indexed_searches = indexed_searches
    return observed


@pytest.mark.parametrize("trigger", ["initial", "A", "B", "C"])
def test_run_request_indexed_source_reaches_current_evidence_and_original_review(
    tmp_path, monkeypatch, capsys, trigger,
):
    observed = _indexed_case(tmp_path, monkeypatch, capsys, trigger)
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", observed.result
    assert len(observed.indexed_searches) == (1 if trigger == "initial" else 2)
    assert len({id(provider) for provider, _, _ in observed.indexed_searches}) == 1
    assert all(kwargs["search_root"] == "generated_mods/Example" for _, kwargs, _ in observed.indexed_searches)
    assert observed.searches == [], "Selected index must not silently dispatch the rg provider."
    provider = observed.indexed_searches[0][0]
    assert provider.database.db_path.is_file()
    for _, _, pack in observed.indexed_searches:
        provenance = pack.budget_summary["indexed_source"]
        assert provider.database.stable_index_version(provenance["collection_id"]).index_version == provenance["index_version"]
        assert provenance["snapshot_schema_version"] != "bounded_source_chunks_v1"
        assert pack.budget_summary["dense_enabled"] is False
        assert all(item.retrieval_method == "indexed_source" for item in pack.items)
    initial_hits = [hit for row in observed.indexed_searches[0][2].budget_summary["per_query_execution"]
        for hit in row["indexed_hits"]]
    assert any(hit["retrieval_method"] == "symbol_exact" for hit in initial_hits)
    if trigger != "initial":
        from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider

        added = observed.indexed_searches[-1][2]
        added_hits = [hit for row in added.budget_summary["per_query_execution"] for hit in row["indexed_hits"]]
        assert any(hit["retrieval_method"] == "bm25" and set(hit["materialized_evidence_ids"]) & {
            item.evidence_id for item in added.items
        } for hit in added_hits)
        # Compare exactly the same current source and query after the run. The
        # ASCII-only rg query representation has no terms for this Chinese lead.
        rg_result = RgLiveEvidenceProvider(observed.result["run_root"]).collect(
            query="状态同步", search_root="generated_mods/Example", max_items=1)
        assert rg_result.items == () and rg_result.budget_summary["retrieval_status"] == "query_terms_missing"
    store = ArtifactStore(Path(observed.result["run_root"]) / "a")
    current = json.loads(Path(observed.result["artifacts"]["evidence_pack"]).read_text(encoding="utf-8"))
    assert current["data"]["can_generate_patch"] is True
    for item in current["data"]["items"]:
        source = Path(observed.result["run_root"]) / item["source_path"]
        assert source.resolve().is_relative_to(Path(observed.result["run_root"]) / "generated_mods" / "Example")
        assert item["source_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert source.read_bytes() == observed.source_bytes[source.name]
    plan = json.loads(Path(observed.result["artifacts"]["implementation_plan"]).read_text(encoding="utf-8"))
    evidence_upstream = next(row for row in plan["inputs"]["upstream_artifacts"] if row["artifact_type"] == "evidence_pack")
    assert evidence_upstream["artifact_hash"] == current["artifact_hash"]
    evidence_versions = [store.semantic_read_immutable(ref)["data"]
        for ref in store.list_feature_artifact_revisions(observed.result["feature_id"], "evidence_pack")]
    assert len(evidence_versions) == (1 if trigger == "initial" else 2)
    for evidence in evidence_versions:
        assert evidence["requirement_coverage"]["projection_identity"] == current["data"]["requirement_coverage"]["projection_identity"]
        assert evidence["requirement_coverage"]["requirements"] == current["data"]["requirement_coverage"]["requirements"]
    assert len(observed.patch_contexts[-1]["required_change_units"]) == (1 if trigger == "initial" else 2)
    if trigger != "initial":
        assert "状态同步" in json.dumps(observed.findings[-1], ensure_ascii=False)
        assert "状态同步" in json.dumps(observed.patch_contexts[-1], ensure_ascii=False)
    if trigger == "C":
        assert len(observed.evaluations) == 2
        first_context, failed = observed.evaluations[0]
        final_context, passed = observed.evaluations[-1]
        assert failed["status"] == "behavior_failed" and passed["status"] == "passed"
        assert first_context["implementation_plan_ref"] != final_context["implementation_plan_ref"]
        assert first_context["generated_changes_sha256"] != final_context["generated_changes_sha256"]
        assert failed["observations"][0]["check_id"] == passed["observations"][0]["check_id"]
        feedback = next(row for row in observed.worker_requests[-1] if row.get("message_type") == "patch_replanned_context")
        assert feedback["validator_feedback"]["generated_changes_sha256"] == failed["generated_changes_sha256"]
    assert observed.result["actual_write_performed"] is False
    assert observed.result["approval_recorded"] is False
    assert observed.result["builds_performed"] == observed.result["runtime_executions_performed"] == 0


def test_run_request_indexed_source_trace_binds_new_bm25_material_to_planning_and_patch(
    tmp_path, monkeypatch, capsys,
):
    observed = _indexed_case(tmp_path, monkeypatch, capsys, "A")
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", observed.result
    manifest_path = Path(observed.result["run_root"]) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = list(manifest["execution_observations"].values())
    roots = [row for row in rows if row["parent_id"] is None]
    assert len(roots) == 1 and roots[0]["name"] == "product.execution"
    generations = [row for row in rows if row["kind"] == "generation"]
    assert len(generations) == manifest["model_call_count"] == len(observed.requests) == 6
    searches = [row for row in rows if row["name"] == "evidence.source_query"]
    assert len(searches) >= 2
    assert all(row["attributes"]["provider"] == "indexed_source" for row in searches)
    assert all(row["attributes"]["tool_dispatch_performed"] is True for row in searches)
    added = observed.indexed_searches[-1][2].items[0]
    assert any(row["attributes"]["query_sha256"] == hashlib.sha256("状态同步".encode()).hexdigest()
        and any(item["evidence_id"] == added.evidence_id for item in row["attributes"]["produced_materials"])
        for row in searches)
    evidence = json.loads(Path(observed.result["artifacts"]["evidence_pack"]).read_text(encoding="utf-8"))
    planning = next(row for row in rows if row["name"] == "planning.decision")
    assert planning["attributes"]["evidence_payload_sha256"] == payload_sha256(evidence["data"])
    assert "状态同步" in json.dumps(observed.patch_contexts[-1], ensure_ascii=False)
    for row in generations:
        if row["name"] == "patch.generate":
            continue
        for role in ("request", "response"):
            ref = row["attributes"]["local_detail_refs"][role]
            assert hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
    projected = [dict(cloud_row(row), traceId=roots[0]["trace_id"]) for row in rows]
    queried = summarize_execution(roots[0]["trace_id"], projected)
    joined = join_local_journal(queried, manifest_path,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(), artifact_roots=[tmp_path])
    assert joined["missing_parent_observation_ids"] == []
    assert all(row["binding"] == "verified_journal_and_observation_mapping"
        for row in joined["local_evidence"]["observations"])
    links = [row for row in joined["material_consumption_links"]
        if row["material"]["evidence_id_sha256"] == hashlib.sha256(added.evidence_id.encode()).hexdigest()]
    assert links and all(row["binding"] == "matched_excerpt_in_responded_request" for row in links)


def test_run_request_indexed_source_failure_stops_without_rg_fallback(tmp_path, monkeypatch, capsys):
    from src.mod_agent.evidence.indexed_source import IndexedSourceEvidenceProvider

    def unavailable(*_args, **_kwargs):
        raise ValueError("INDEXED_SOURCE_INDEXING_FAILED")

    monkeypatch.setattr(IndexedSourceEvidenceProvider, "_prepare_snapshot", unavailable)
    observed = _indexed_case(tmp_path, monkeypatch, capsys, "A")
    assert observed.exit_code != 0, observed.result
    assert observed.roles == ["product_requirement_projection"]
    assert observed.searches == []
    assert observed.findings == observed.planning == observed.patch_contexts == []
    assert "INDEXED_SOURCE_INDEXING_FAILED" in json.dumps(observed.result["product_execution_result"]["blockers"])
    assert observed.result["actual_write_performed"] is False
