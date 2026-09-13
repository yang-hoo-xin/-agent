"""Public product entry through original graph/providers with offline HTTP/build doubles."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from src.mod_agent import cli, local_entry
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration
from src.mod_agent.upstream_trace import payload_sha256
from src.observability.patch_langfuse_query import join_local_journal, summarize_execution
from src.observability.patch_live_langfuse import build_patch_live_otlp
from tests.unit import test_mod_agent_cli as fixtures
from tests.unit.test_upstream_langfuse_query import cloud_row


def test_initial_findings_reassessment_trace_binds_both_evidence_revisions_without_repair(tmp_path, monkeypatch, capsys):
    """Offline HTTP/baseline compiler; real rg, original Graph and local trace joins."""
    observed = fixtures._public_patch_upstream_scenario(tmp_path, monkeypatch, capsys, initial_findings_gap=True)
    result = observed.result
    assert observed.exit_code == 0 and result["status"] == "awaiting_approval", result
    manifest_path = Path(result["run_root"]) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = list(manifest["execution_observations"].values())
    roots = [row for row in rows if row["parent_id"] is None]
    assert len(roots) == 1 and roots[0]["name"] == "product.execution"
    assert len({row["trace_id"] for row in rows}) == len({row["session_id"] for row in rows}) == 1
    generations = [row for row in rows if row["kind"] == "generation"]
    assert len(generations) == len(observed.requests) == manifest["model_call_count"] == 6
    assert sum(row["name"] == "requirements.project" for row in generations) == 1
    assert sum(row["name"] == "requirements.findings" for row in generations) == 2
    assert sum(row["name"] == "planning.select" for row in generations) == 1
    assert sum(row["name"] == "patch.generate" for row in generations) == 1
    query = [row for row in generations if row["attributes"].get("model_role") == "initial_findings_queries"]
    assert len(query) == 1 and query[0]["name"] == "evidence.query"
    assert all(row["finished_at"] for row in rows)
    for row in generations:
        if row["name"] == "patch.generate":
            continue
        for role in ("request", "response"):
            ref = row["attributes"]["local_detail_refs"][role]
            assert hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
    store = ArtifactStore(Path(result["run_root"]) / "a")
    evidence_refs = store.list_feature_artifact_revisions(result["feature_id"], "evidence_pack")
    evidence = [store.semantic_read_immutable(ref) for ref in evidence_refs]
    assert len(evidence) == 2
    initial = next(row for row in evidence if row["status"] == "blocked")
    final = next(row for row in evidence if row["status"] == "success")
    for key in ("projection_identity", "requirements", "relations", "input_obligations", "input_dispositions"):
        assert initial["data"]["requirement_coverage"][key] == final["data"]["requirement_coverage"][key]
    assert initial["data"]["can_generate_patch"] is False and final["data"]["can_generate_patch"] is True
    assert store.list_feature_artifact_revisions(result["feature_id"], "repair_plan") == []
    planning = next(row for row in rows if row["name"] == "planning.decision")
    assert planning["attributes"]["evidence_payload_sha256"] == payload_sha256(final["data"])
    assert any(row["name"] == "proposal.review" for row in rows)
    assert any(row["name"] == "patch.dry_run" for row in rows)
    projected = [dict(cloud_row(row), traceId=roots[0]["trace_id"]) for row in rows]
    queried = summarize_execution(roots[0]["trace_id"], projected)
    joined = join_local_journal(queried, manifest_path,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(), artifact_roots=[tmp_path])
    assert joined["missing_parent_observation_ids"] == []
    assert all(row["binding"] == "verified_journal_and_observation_mapping"
        for row in joined["local_evidence"]["observations"])
    details = [detail for row in joined["local_evidence"]["observations"] for detail in row["details"]]
    assert details and all(detail["file_binding"] == "verified_bytes" for detail in details)
    added = observed.searches[-1][1].items[0]
    links = [row for row in joined["material_consumption_links"]
        if row["material"]["evidence_id_sha256"] == hashlib.sha256(added.evidence_id.encode()).hexdigest()]
    assert links and all(row["binding"] == "matched_excerpt_in_responded_request" for row in links)
    assert result["actual_write_performed"] is False


def test_product_patch_upstream_trace_keeps_one_task_and_current_material_lineage(tmp_path, monkeypatch, capsys):
    """Offline transport and baseline compiler; no Cloud, Apply or real model."""
    observed = fixtures._public_patch_upstream_scenario(tmp_path, monkeypatch, capsys)
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", observed.result
    manifest_path = next((tmp_path / "runs").glob("*/run_manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = list(manifest["execution_observations"].values())
    roots = [row for row in rows if row["parent_id"] is None]
    assert len(roots) == 1 and roots[0]["name"] == "product.execution"
    assert len({row["trace_id"] for row in rows}) == len({row["session_id"] for row in rows}) == 1
    assert all(row["finished_at"] for row in rows)
    generation_rows = [row for row in rows if row["kind"] == "generation"]
    assert len(generation_rows) == len(observed.requests) == manifest["model_call_count"] == 8
    searches = [row for row in rows if row["name"] == "evidence.source_query"]
    assert any(row["attributes"]["query_sha256"] == hashlib.sha256(b"RefreshSharedState").hexdigest()
        and row["attributes"]["tool_dispatch_performed"] is True for row in searches)
    assert sum(row["name"] == "planning.select" for row in generation_rows) == 2
    assert sum(row["name"] == "patch.generate" for row in generation_rows) == 2
    assert sum(row["name"] == "evidence.query" for row in generation_rows) == 1
    assert sum(row["name"] == "requirements.findings" for row in generation_rows) == 2
    for row in generation_rows:
        if row["name"] == "patch.generate":
            continue  # Patch has the original worker journal body references.
        for role in ("request", "response"):
            ref = row["attributes"]["local_detail_refs"][role]
            assert hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
    assert any(row["name"] == "proposal.review" for row in rows)
    assert any(row["name"] == "patch.dry_run" for row in rows)
    journals = [json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        for row in observed.result["patch_execution_receipts"]]
    assert len(journals) == 2
    for journal in journals:
        assert journal["continuation_selection"] == "product_graph_current_implementation_plan"
        assert journal["execution_trace"]["trace_id"] == roots[0]["trace_id"]
        assert journal["request_id"] == manifest["request_id"]
        assert journal["parent_run_id"] == manifest["run_id"]
        assert journal["model_call_count"] == 1
    assert journals[0]["selected_artifacts"]["feature_spec"] == journals[-1]["selected_artifacts"]["feature_spec"]
    assert journals[0]["selected_artifacts"]["evidence_pack"] != journals[-1]["selected_artifacts"]["evidence_pack"]
    assert journals[0]["selected_artifacts"]["implementation_plan"] != journals[-1]["selected_artifacts"]["implementation_plan"]
    evidence_ref = journals[-1]["selected_artifacts"]["evidence_pack"]
    evidence = json.loads(Path(evidence_ref["path"]).read_text(encoding="utf-8"))
    assert evidence["artifact_hash"] == evidence_ref["artifact_hash"]
    # Artifact identity and the canonical data payload are different hashes.
    # The second Planning decision must consume the exact new Artifact data.
    planning = sorted([row for row in rows if row["name"] == "planning.decision"],
        key=lambda row: row["started_at"])
    assert planning[-1]["attributes"]["evidence_payload_sha256"] == payload_sha256(evidence["data"])
    assert planning[0]["attributes"]["evidence_payload_sha256"] != planning[-1]["attributes"]["evidence_payload_sha256"]
    projected = [dict(cloud_row(row), traceId=roots[0]["trace_id"]) for row in rows]
    queried = summarize_execution(roots[0]["trace_id"], projected)
    joined = join_local_journal(queried, manifest_path,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(), artifact_roots=[tmp_path])
    assert joined["missing_parent_observation_ids"] == []
    assert all(row["binding"] == "verified_journal_and_observation_mapping"
        for row in joined["local_evidence"]["observations"])
    details = [detail for row in joined["local_evidence"]["observations"] for detail in row["details"]]
    assert details and all(detail["file_binding"] == "verified_bytes" for detail in details)
    added_item = observed.searches[-1][1].items[0]
    links = [link for link in joined["material_consumption_links"]
        if link["material"]["evidence_id_sha256"] == hashlib.sha256(added_item.evidence_id.encode()).hexdigest()]
    assert links and all(link["binding"] == "matched_excerpt_in_responded_request" for link in links)
    assert all(link["material"]["excerpt_sha256"] == hashlib.sha256(added_item.excerpt.encode()).hexdigest()
        for link in links)
    assert observed.result["actual_write_performed"] is False


@pytest.mark.parametrize("mode", ["ready", "missing_findings", "sink_unavailable"])
def test_public_upstream_to_patch_trace_preserves_calls_decisions_and_materials(tmp_path, monkeypatch, capsys, mode):
    real_chat = local_entry.OllamaLLM.chat
    install = fixtures._install_public_run_request_native_chat
    requests = []

    def install_transport(patcher, deterministic_chat):
        install(patcher, deterministic_chat)
        original = httpx.HTTPTransport.handle_request
        def http_response(transport, request):
            payload = json.loads(request.content)
            requests.append(payload)
            for message in payload["messages"]:
                if message["role"] != "user":
                    continue
                try:
                    context = json.loads(message["content"])
                except (ValueError, TypeError):
                    continue
                coverage = fixtures._formal_coverage_model_response(context)
                if coverage is not None:
                    if mode == "missing_findings" and "findings" in coverage:
                        for row in coverage["findings"]:
                            row.update(relationship="missing", evidence_ids=[], edit_target_evidence_ids=[],
                                       unresolved_gaps=["Offline fixture reports insufficient evidence."])
                    return httpx.Response(200, request=request, json={"model": payload["model"],
                        "message": {"role": "assistant", "content": json.dumps(coverage)}, "done": True,
                        "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
            return original(transport, request)
        patcher.setattr(httpx.HTTPTransport, "handle_request", http_response)
        # Restore the real upstream serializer/admission/HTTP boundary too.
        patcher.setattr(local_entry.OllamaLLM, "chat", real_chat)

    monkeypatch.setattr(fixtures, "_install_public_run_request_native_chat", install_transport)
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("No actual network or model request"))
    completed = []
    ordinary_main = fixtures.main

    class FixtureFinished(Exception):
        pass

    def run_with_model_planning(arguments):
        offset = arguments.index("--planning-target-evidence-id")
        arguments = arguments[:offset] + arguments[offset + 2:]
        if mode == "missing_findings":
            # This existing trace case covers a gap with no reassessment provider;
            # the separate initial-Findings trace exercises actual recovery.
            adapters_type = local_entry.ProductExecutionAdaptersV1

            def without_reassessment(**kwargs):
                kwargs["initial_findings_reassessment_factory"] = None
                return adapters_type(**kwargs)

            monkeypatch.setattr(local_entry, "ProductExecutionAdaptersV1", without_reassessment)
        code = ordinary_main([*arguments, "--defer-approval"])
        completed.append((code, json.loads(capsys.readouterr().out)))
        raise FixtureFinished

    monkeypatch.setattr(fixtures, "main", run_with_model_planning)
    if mode == "sink_unavailable":
        class BrokenSink:
            def publish(self, row):
                raise OSError("PRIVATE_SINK_FAILURE")
            def shutdown(self, **kwargs):
                return {"status": "unavailable"}
        monkeypatch.setattr(cli, "_execution_trace_configuration", lambda args:
                            PatchExecutionTraceConfiguration(sink=BrokenSink()))
    with pytest.raises(FixtureFinished):
        fixtures.test_cli_run_request_real_public_product_executor_compile_success(tmp_path, monkeypatch, capsys)
    manifest_path = next((tmp_path / "runs").glob("*/run_manifest.json"))
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = list(document["execution_observations"].values())
    roots = [r for r in rows if r["parent_id"] is None]
    assert len(roots) == 1 and roots[0]["name"] == "product.execution"
    assert len({r["trace_id"] for r in rows}) == len({r["session_id"] for r in rows}) == 1
    ids = {r["id"] for r in rows}
    assert all(r["parent_id"] is None or r["parent_id"] in ids for r in rows)
    assert all(r["finished_at"] for r in rows)
    generations = [r for r in rows if r["kind"] == "generation"]
    assert len(generations) == len(requests)
    assert {"requirements.project", "requirements.findings"} <= {r["name"] for r in generations}
    assert any(r["name"] == "evidence.source_query" and r["kind"] == "tool" for r in rows)
    assert any(r["name"] == "workflow.route" for r in rows)
    assert {"environment.settings", "environment.prepare", "source.admission", "evidence.assemble"} <= {r["name"] for r in rows}
    # Exercise the same export/query/local-join contract on this complete product
    # invocation. These are offline mapped rows, never an actual Cloud readback.
    projected = [dict(cloud_row(row), traceId=roots[0]["trace_id"]) for row in rows]
    queried = summarize_execution(roots[0]["trace_id"], projected)
    joined = join_local_journal(queried, manifest_path,
        hashlib.sha256(manifest_path.read_bytes()).hexdigest(), artifact_roots=[tmp_path])
    assert joined["missing_parent_observation_ids"] == []
    assert all(row["binding"] == "verified_journal_and_observation_mapping"
               for row in joined["local_evidence"]["observations"])
    local_details = [detail for row in joined["local_evidence"]["observations"] for detail in row["details"]]
    assert local_details and all(detail["file_binding"] == "verified_bytes" for detail in local_details)
    assert any(link["binding"] == "matched_excerpt_in_responded_request"
               for link in joined["material_consumption_links"])
    for row in generations:
        if row["name"] == "patch.generate":
            continue  # Patch retains its established request files in its own journal.
        refs = row["attributes"]["local_detail_refs"]
        for role in ("request", "response"):
            ref = refs[role]
            assert hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
        assert row["attributes"]["usage"] == {"input_tokens": 10, "output_tokens": 20}
    cloud = json.dumps([build_patch_live_otlp(row) for row in rows], ensure_ascii=False)
    assert "PRIVATE_SINK_FAILURE" not in cloud and str(tmp_path) not in cloud
    assert "PRODUCT_TEST_CHANGE" not in cloud
    assert "system_fact_from_recorded_structure" in cloud
    if mode == "missing_findings":
        assert not any(r["name"] in {"planning.select", "patch.generate", "proposal.review"} for r in rows)
        assert any(r["attributes"].get("decision") == "patch_blocked" for r in rows)
    else:
        code, result = completed[0]
        assert code == 0 and result["status"] == "awaiting_approval"
        assert {"planning.select", "patch.generate"} <= {r["name"] for r in generations}
        assembled = next(r for r in rows if r["name"] == "evidence.assemble")
        planning = next(r for r in rows if r["name"] == "planning.decision")
        assert assembled["attributes"]["output_payload_sha256"] == planning["attributes"]["evidence_payload_sha256"]
        assert any(r["name"] == "proposal.review" for r in rows)
        assert any(r["name"] == "patch.dry_run" for r in rows)
        journal_path = Path(result["patch_execution_receipts"][0]["path"])
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        assert journal["execution_trace"]["trace_id"] == roots[0]["trace_id"]
        assert all(r["name"] not in {"requirements.project", "requirements.findings", "planning.select"}
                   for r in journal["execution_observations"].values())
        assert journal["model_call_count"] == sum(r["name"] == "patch.generate" for r in generations)
        assert result["actual_write_performed"] is False
    assert document["model_call_count"] == len(requests)
