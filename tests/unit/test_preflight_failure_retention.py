"""Durable early failures through the public CLI; no model, network or Build."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.core.trace.execution_trace import ExecutionTrace, current_trace, trace_operation
from src.core.trace.trace_collector import TraceCollector
from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration, product_execution_trace


_REPO = Path(__file__).resolve().parents[2]
_CLI_BOOTSTRAP = """
import socket, sys
from pathlib import Path
import src.core.trace.trace_collector as collector
collector._DEFAULT_TRACES_PATH = Path(sys.argv[1])
def forbid_network(*args, **kwargs):
    raise AssertionError('No network is authorized by this deterministic test.')
socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
from src.mod_agent.cli import main
raise SystemExit(main(sys.argv[2:]))
"""
_INDEPENDENT_READER = """
import hashlib, json, sys
from pathlib import Path
reference = json.loads(sys.argv[1])
path = Path(reference['path'])
assert path.is_absolute()
raw = path.read_bytes()
assert hashlib.sha256(raw).hexdigest() == reference['sha256']
document = json.loads(raw)
rows = list(document['execution_observations'].values())
assert rows and all(row['finished_at'] and row['status'] != 'running' for row in rows)
roots = [row for row in rows if row['parent_id'] is None]
assert len(roots) == 1 and roots[0]['status'] == 'failed'
assert all(row['trace_id'] == document['execution_trace']['trace_id'] for row in rows)
assert not any(row['kind'] == 'generation' for row in rows)
from src.observability.dashboard.services.trace_service import TraceService
queried = TraceService(traces_path=Path(sys.argv[2]), include_raw=True).get_trace(document['execution_trace']['trace_id'])
assert queried == document
print(json.dumps(document, ensure_ascii=False))
"""


def _run_python(code, *args):
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", code, *map(str, args)],
        cwd=_REPO, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)


def _cli(tmp_path, *, description="change the existing default", allow_build=True):
    anchor = tmp_path / "trace-log" / "traces.jsonl"
    args = ["run-request", description, "--target-project", str(tmp_path / "absent-source"),
        "--settings", str(tmp_path / "missing-settings.yaml"), "--workspace-root", str(tmp_path / "runs"),
        "--local-ollama", "--ollama-model", "qwen3:4b-instruct", "--ollama-context-window", "32768",
        "--confirm-isolated-write", "--run-id", "retained-run", "--request-id", "logical-request"]
    if allow_build:
        args.append("--allow-build")
    process = _run_python(_CLI_BOOTSTRAP, anchor, *args)
    assert process.returncode == 2, process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "BLOCKED"
    return result, anchor


def _failed_document(trace_id="a" * 32):
    observations = {}
    trace = ExecutionTrace(trace_id, "session", "test", root_name="product.execution",
                           recorder=lambda row: observations.update({row["id"]: row}))
    with pytest.raises(ValueError):
        with trace.activate():
            with trace_operation("environment.settings"):
                raise ValueError("settings unavailable")
    return {"run_id": "retained-run", "request_id": "logical-request",
        "execution_trace": {"trace_id": trace_id, "session_id": trace.session_id},
        "execution_observations": observations}


def _reference(result):
    reference = result["execution_trace"]["local_observation_source"]
    assert reference["persisted"] is True
    assert reference["storage"] == "execution_trace_file"
    assert reference["json_pointer"] == "/execution_observations"
    assert Path(reference["path"]).is_absolute()
    return reference


def test_public_cli_failure_survives_exit_and_same_run_retry_does_not_overwrite(tmp_path):
    first, anchor = _cli(tmp_path)
    first_ref = _reference(first)
    expected = anchor.parent / "execution" / (first["execution_trace"]["trace_id"] + ".json")
    assert Path(first_ref["path"]) == expected
    before = expected.read_bytes()
    # A separate interpreter has no access to the first process's exception or
    # collector object; it reconstructs the tree only from the returned file ref.
    reader = _run_python(_INDEPENDENT_READER, json.dumps(first_ref), anchor)
    assert reader.returncode == 0, reader.stderr
    document = json.loads(reader.stdout)
    assert document["run_id"] == "retained-run" and document["request_id"] == "logical-request"
    assert document["execution_observations"] == first["execution_observations"]
    assert any(row["name"] == "environment.settings" and row["status"] == "failed"
               for row in document["execution_observations"].values())
    second, _ = _cli(tmp_path)
    second_ref = _reference(second)
    assert second_ref["path"] != first_ref["path"] and expected.read_bytes() == before
    assert first["execution_trace"]["session_id"] == second["execution_trace"]["session_id"]
    assert len(list((anchor.parent / "execution").glob("*.json"))) == 2
    assert not (tmp_path / "runs").exists()


def test_execution_collector_syncs_before_publish_and_never_replaces_existing_trace(tmp_path, monkeypatch):
    anchor = tmp_path / "trace-log" / "traces.jsonl"
    collector = TraceCollector(anchor)
    document = _failed_document()
    synchronized_sizes = []
    original_fsync = os.fsync
    def sync(fd):
        # A small buffered JSON write must be flushed before fsync; the OS must
        # already see nonempty bytes. Call the real filesystem sync as well.
        synchronized_sizes.append(os.fstat(fd).st_size)
        assert synchronized_sizes[-1] > 0
        return original_fsync(fd)
    monkeypatch.setattr(os, "fsync", sync)
    reference = collector.collect_execution(document)
    path = anchor.parent / "execution" / (document["execution_trace"]["trace_id"] + ".json")
    raw = path.read_bytes()
    assert synchronized_sizes and reference == {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}
    assert json.loads(raw) == document
    with pytest.raises(FileExistsError):
        collector.collect_execution({**document, "request_id": "another-request"})
    assert path.read_bytes() == raw


def test_default_trace_anchor_is_selected_at_construction_time(tmp_path, monkeypatch):
    import src.core.trace.trace_collector as owner
    anchor = tmp_path / "chosen-at-runtime" / "traces.jsonl"
    monkeypatch.setattr(owner, "_DEFAULT_TRACES_PATH", anchor)
    assert TraceCollector().path == anchor


def test_bad_cloud_preserves_business_error_and_durable_local_tree_without_old_manifest_write(tmp_path):
    class BadCloud:
        def publish(self, row):
            raise OSError("cloud disconnected")
        def shutdown(self, **kwargs):
            raise OSError("cloud disconnected")
    planned = tmp_path / "old-run"
    planned.mkdir()
    manifest = planned / "run_manifest.json"
    before = b'{"run_id":"retained-run","request_id":"logical-request","old":true}'
    manifest.write_bytes(before)
    config = PatchExecutionTraceConfiguration(sink=BadCloud(), failure_traces_path=tmp_path / "trace-log" / "traces.jsonl")
    original_error = ValueError("source directory absent")
    with pytest.raises(ValueError) as caught:
        with product_execution_trace(run_root=planned, run_id="retained-run", request_id="logical-request",
                                     artifact_store_root=planned / "a", configuration=config, buffer_until_manifest=True):
            with trace_operation("source.admission"):
                raise original_error
    assert caught.value is original_error and manifest.read_bytes() == before
    reference = _reference({"execution_trace": original_error.execution_trace})
    raw = Path(reference["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == reference["sha256"]
    assert json.loads(raw)["execution_observations"] == original_error.execution_observations
    assert original_error.execution_trace["failures"]["sink"]["total"] > 0
    assert current_trace() is None


def test_local_storage_failure_preserves_same_exception_and_reports_unpersisted_tree(tmp_path, monkeypatch):
    def fail_sync(fd):
        raise OSError("disk unavailable")
    monkeypatch.setattr(os, "fsync", fail_sync)
    config = PatchExecutionTraceConfiguration(failure_traces_path=tmp_path / "trace-log" / "traces.jsonl")
    original_error = RuntimeError("original environment error")
    with pytest.raises(RuntimeError) as caught:
        with product_execution_trace(run_root=tmp_path / "uncreated", run_id="retained-run", request_id="logical-request",
                                     artifact_store_root=tmp_path / "uncreated" / "a", configuration=config, buffer_until_manifest=True):
            with trace_operation("environment.prepare"):
                raise original_error
    assert caught.value is original_error
    summary = original_error.execution_trace
    assert summary["local_observation_source"]["persisted"] is False
    assert summary["local_persistence"] == {"status": "failed", "error_type": "OSError"}
    assert original_error.execution_observations
    assert all(row["finished_at"] and row["status"] == "failed" for row in original_error.execution_observations.values())
    assert not (tmp_path / "uncreated").exists() and current_trace() is None
    assert not list((tmp_path / "trace-log" / "execution").iterdir())


def test_successful_manifest_uses_existing_record_and_creates_no_early_failure_file(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    manifest = run_root / "run_manifest.json"
    manifest.write_text(json.dumps({"run_id": "retained-run", "request_id": "logical-request", "status": "done"}))
    anchor = tmp_path / "trace-log" / "traces.jsonl"
    config = PatchExecutionTraceConfiguration(failure_traces_path=anchor)
    with product_execution_trace(run_root=run_root, run_id="retained-run", request_id="logical-request",
                                 artifact_store_root=run_root / "a", configuration=config):
        with trace_operation("requirements.projection"):
            pass
    document = json.loads(manifest.read_text(encoding="utf-8"))
    assert document["status"] == "done" and document["execution_observations"]
    assert document["execution_trace"]["local_observation_source"]["path"] == str(manifest)
    assert not (anchor.parent / "execution").exists()


@pytest.mark.parametrize("description,allow_build", [("", True), ("change setting", False)])
def test_basic_input_or_authorization_rejection_creates_no_execution_trace(tmp_path, description, allow_build):
    result, anchor = _cli(tmp_path, description=description, allow_build=allow_build)
    assert "execution_trace" not in result and "execution_observations" not in result
    assert not anchor.parent.exists() and not (tmp_path / "runs").exists()
