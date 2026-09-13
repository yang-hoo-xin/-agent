"""Public product entry through original graph/providers with offline HTTP/build doubles."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from src.mod_agent import cli, local_entry
from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration
from src.observability.patch_langfuse_query import join_local_journal, summarize_execution
from src.observability.patch_live_langfuse import build_patch_live_otlp
from tests.unit import test_mod_agent_cli as fixtures
from tests.unit.test_upstream_langfuse_query import cloud_row


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
