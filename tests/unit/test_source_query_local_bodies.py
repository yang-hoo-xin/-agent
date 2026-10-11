"""Actual rg retrieval keeps invocation bodies local without changing the result."""
from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from src.mod_agent.evidence import RgLiveEvidenceProvider
from src.mod_agent.patch_execution_trace import product_execution_trace
from src.observability.patch_live_langfuse import build_patch_live_otlp


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Source tracing is local only"))


def _workspace(tmp_path):
    workspace = tmp_path / "workspace"
    source = workspace / "generated_mods/Sample/ConfigStore.cs"
    source.parent.mkdir(parents=True)
    source.write_text("""namespace Sample
{
    public class ConfigStore
    {
        public string ConfigKey = "kept";
        public string ReadConfigKey()
        {
            return ConfigKey;
        }
    }
}
""", encoding="utf-8")
    run = tmp_path / "recorded-run"
    run.mkdir()
    (run / "run_manifest.json").write_text(json.dumps({
        "run_id": "recorded-run", "request_id": "recorded-request", "status": "running"}),
        encoding="utf-8")
    return workspace, run


def _trace(run):
    return product_execution_trace(run_root=run, run_id="recorded-run",
        request_id="recorded-request", artifact_store_root=run / "a")


def _tool(run):
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    tools = [row for row in manifest["execution_observations"].values() if row["kind"] == "tool"]
    assert len(tools) == 1
    return tools[0]


def _body(ref, run):
    path = Path(ref["path"])
    assert path.is_relative_to(run)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ref["sha256"]
    return json.loads(raw)


def test_actual_rg_query_retains_exact_input_and_complete_returned_pack(tmp_path):
    workspace, run = _workspace(tmp_path)
    inputs = {"query": "ConfigKey", "search_root": "generated_mods/Sample",
              "source_identity_query": "configuration read location", "max_items": 3}
    with _trace(run):
        result = RgLiveEvidenceProvider(workspace).collect(**inputs)
    assert result.items
    row = _tool(run)
    refs = row["attributes"].get("local_detail_refs", {})
    assert set(refs) == {"request", "response"}
    assert _body(refs["request"], run) == {
        **inputs, "source_view_policy": {
            "schema_version": "source_view_policy_v1", "small_file_max_bytes": 0}}
    assert _body(refs["response"], run) == result.to_artifact_payload()
    assert refs["request"]["sha256"] == row["attributes"]["input_payload_sha256"]
    assert refs["response"]["sha256"] == row["attributes"]["output_payload_sha256"]
    assert row["attributes"]["local_tool_body_capture"] == {
        "request": {"status": "retained"}, "response": {"status": "retained"}}
    exported = json.dumps(build_patch_live_otlp(row), ensure_ascii=False)
    assert "configuration read location" not in exported
    assert "ConfigStore.cs" not in exported and "ConfigKey" not in exported
    assert "local_body_root" not in exported and "recorded-run" not in exported
    assert refs["request"]["sha256"] in exported and refs["response"]["sha256"] in exported


@pytest.mark.parametrize("failed_role", ["request", "response", "both"])
def test_local_write_failure_is_unknown_and_preserves_actual_retrieval_result(tmp_path, monkeypatch, failed_role):
    from src.mod_agent import upstream_model_trace

    workspace, run = _workspace(tmp_path)
    provider = RgLiveEvidenceProvider(workspace)
    collect = provider._collect
    results = []

    def actual_collect(**kwargs):
        result = collect(**kwargs)
        results.append(result)
        return result

    save = upstream_model_trace._local_body

    def fail_selected(root, observation_id, role, raw):
        if failed_role == "both" or role == "tool." + failed_role + ".json":
            raise PermissionError("Controlled local observation write failure")
        return save(root, observation_id, role, raw)

    monkeypatch.setattr(provider, "_collect", actual_collect)
    monkeypatch.setattr(upstream_model_trace, "_local_body", fail_selected)
    with _trace(run):
        result = provider.collect(query="ConfigKey", search_root="generated_mods/Sample", max_items=2)
    assert len(results) == 1 and result is results[0] and result.items
    row = _tool(run)
    assert row["status"] == "completed"
    for role in ("request", "response"):
        capture = row["attributes"]["local_tool_body_capture"][role]
        if failed_role in (role, "both"):
            assert capture == {"status": "unknown", "reason": "local_body_capture_failed",
                               "error_type": "PermissionError"}
            assert role not in row["attributes"]["local_detail_refs"]
        else:
            assert capture == {"status": "retained"}


def test_capture_failure_does_not_replace_business_exception(tmp_path, monkeypatch):
    from src.mod_agent import upstream_model_trace

    workspace, run = _workspace(tmp_path)
    provider = RgLiveEvidenceProvider(workspace)
    original_error = RuntimeError("Original retrieval failure")

    def business_failure(**_kwargs):
        raise original_error

    def storage_failure(*_args):
        raise OSError("Observation storage failed")

    monkeypatch.setattr(provider, "_collect", business_failure)
    monkeypatch.setattr(upstream_model_trace, "_local_body", storage_failure)
    with pytest.raises(RuntimeError) as caught:
        with _trace(run):
            provider.collect(query="ConfigKey", search_root="generated_mods/Sample")
    assert caught.value is original_error
    row = _tool(run)
    assert row["status"] == "failed"
    assert row["attributes"]["exception_type"] == "RuntimeError"
    assert row["attributes"]["local_tool_body_capture"]["response"] == {
        "status": "unknown", "reason": "business_exception_no_returned_payload"}


def test_untraced_query_does_not_create_observation_files(tmp_path):
    workspace, run = _workspace(tmp_path)
    result = RgLiveEvidenceProvider(workspace).collect(query="ConfigKey", search_root="generated_mods/Sample")
    assert result.items
    assert not (run / "model_trace_bodies").exists()
    assert not (workspace / "model_trace_bodies").exists()


def test_trace_without_product_body_root_records_unknown_instead_of_inventing_destination(tmp_path):
    from src.core.trace.execution_trace import ExecutionTrace

    workspace, run = _workspace(tmp_path)
    trace = ExecutionTrace("unknown-root", "session", "local")
    with trace.activate():
        result = RgLiveEvidenceProvider(workspace).collect(query="ConfigKey", search_root="generated_mods/Sample")
    assert result.items
    tools = [row["data"] for row in trace.context.stages if row["data"]["kind"] == "tool"]
    captured = tools[-1]["attributes"]["local_tool_body_capture"]
    assert captured == {role: {"status": "unknown", "reason": "local_body_root_unavailable"}
                        for role in ("request", "response")}
    assert not (run / "model_trace_bodies").exists()
