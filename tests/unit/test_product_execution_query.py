"""Read-only product queries consume explicit original terminal references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.engineering_cognition import build_projection
from src.mod_agent.artifacts.store import ArtifactStore
from src.observability.patch_execution_index import project_product_execution


def _record(root: Path, result):
    root.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(result, ensure_ascii=False).encode("utf-8")
    target = root / "run_result.json"
    target.write_bytes(raw)
    manifest = {"run_id": result["run_id"], "request_id": result["request_id"],
        "terminal_stage": result["current_stage"],
        "terminal_record": {"path": str(target), "sha256": hashlib.sha256(raw).hexdigest()}}
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_explicit_product_query_preserves_recorded_model_budget_before_worker(tmp_path):
    root = tmp_path / "arbitrary-name"
    _record(root, {"run_id": "unit-run", "request_id": "unit-request", "feature_id": "unit-feature",
        "current_stage": "blocked", "model_call_count": 2,
        "model_call_budget": {"maximum": 14, "consumed": 2, "remaining": 12,
            "count_basis": "reserved_provider_invocations_not_transport_proof",
            "by_stage": {"requirement_projection": {"consumed": 1}, "requirement_findings": {"consumed": 1}}}})
    projection = build_projection("verification-claims", query="product-execution", run_root=root)
    observed = projection["data"]
    assert observed["current_stage"] == "blocked"
    assert observed["model_accounting"]["recorded_model_call_count"] == 2
    assert observed["model_accounting"]["budget"]["count_basis"] == "reserved_provider_invocations_not_transport_proof"
    assert observed["model_accounting"]["native_send_count"] is None
    assert observed["query_execution"]["model_calls_performed"] == 0


def _terminal():
    return {"run_id": "unit-run", "request_id": "unit-request", "feature_id": "unit-feature", "current_stage": "blocked"}


@pytest.mark.parametrize("stage", [None, "missing", "blocked"])
def test_original_terminal_writer_roundtrips_missing_stage(tmp_path, stage):
    from src.mod_agent.local_entry import _persist_graph_terminal_result

    summary = _terminal()
    if stage == "missing":
        summary.pop("current_stage")
    else:
        summary["current_stage"] = stage
    (tmp_path / "run_manifest.json").write_text(json.dumps({
        "run_id": summary["run_id"], "request_id": summary["request_id"]}), encoding="utf-8")
    _persist_graph_terminal_result(run_root=tmp_path, run_id=summary["run_id"],
        request_id=summary["request_id"], summary=summary, model_call_count=0,
        patch_payload_parser_entered=False, actual_write_performed=False)
    expected = "blocked" if stage == "blocked" else "unknown"
    assert project_product_execution(tmp_path)["current_stage"] == expected
    assert json.loads((tmp_path / "run_result.json").read_text(encoding="utf-8"))["current_stage"] == expected
    assert summary.get("current_stage") == (None if stage == "missing" else stage)


@pytest.mark.parametrize("stage", [None, "missing", "blocked"])
def test_historical_stage_projection_is_read_only_and_rejects_distinct_stage(tmp_path, stage):
    terminal = _terminal()
    terminal["current_stage"] = stage
    manifest = _record(tmp_path, terminal)
    if stage == "missing":
        terminal.pop("current_stage")
        raw = json.dumps(terminal).encode("utf-8")
        (tmp_path / "run_result.json").write_bytes(raw)
        manifest["terminal_record"]["sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["terminal_stage"] = "unknown"
    (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    if stage == "blocked":
        with pytest.raises(ValueError, match="product_terminal_stage_mismatch"):
            project_product_execution(tmp_path)
    else:
        assert project_product_execution(tmp_path)["current_stage"] == "unknown"
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("missing", ["manifest", "reference", "result", "counts"])
def test_missing_records_remain_unknown_not_zero(tmp_path, missing):
    root = tmp_path / "run"
    manifest = _record(root, _terminal())
    if missing == "manifest":
        (root / "run_manifest.json").unlink()
    elif missing == "reference":
        manifest.pop("terminal_record")
        (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    elif missing == "result":
        (root / "run_result.json").unlink()
    result = project_product_execution(root)
    assert result["model_accounting"]["recorded_model_call_count"] is None
    assert result["model_accounting"]["native_send_count"] is None
    assert result["upstream_responses"]["recorded_response_count"] is None
    assert all(value == "unknown" for value in result["post_stages"].values())


def test_terminal_hash_mismatch_is_rejected(tmp_path):
    _record(tmp_path, _terminal())
    (tmp_path / "run_result.json").write_bytes(b'{"changed":true}')
    with pytest.raises(ValueError, match="product_terminal_hash_mismatch"):
        project_product_execution(tmp_path)


@pytest.mark.parametrize("key", ["run_id", "request_id", "feature_id"])
def test_manifest_and_result_identity_mismatch_is_rejected(tmp_path, key):
    manifest = _record(tmp_path, _terminal())
    manifest[key] = "different-identity"
    (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="product_manifest_.*mismatch"):
        project_product_execution(tmp_path)


def test_terminal_reference_cannot_escape_explicit_root(tmp_path):
    root = tmp_path / "chosen"
    manifest = _record(root, _terminal())
    external = tmp_path / "outside.json"
    external.write_bytes((root / "run_result.json").read_bytes())
    manifest["terminal_record"]["path"] = str(external)
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="product_record_path_outside_run_root"):
        project_product_execution(root)


def test_query_does_not_infer_run_root_from_artifact_store(tmp_path):
    from scripts.engineering_cognition import EngineeringCognitionError

    with pytest.raises(EngineeringCognitionError, match="product-execution requires --run-root"):
        build_projection("verification-claims", query="product-execution", artifact_store_root=tmp_path)
    with pytest.raises(EngineeringCognitionError, match="Execution subqueries require"):
        build_projection("patch-execution", query="product-execution", artifact_store_root=tmp_path)
    with pytest.raises(ValueError, match="product_query_requires_absolute_run_root"):
        project_product_execution("relative-run")


def test_typed_not_applicable_does_not_become_changed_source(tmp_path):
    from tests.unit.test_product_execution_projection_v2 import (
        _strict_result_with_reused_patch_revision,
    )

    typed = _strict_result_with_reused_patch_revision(tmp_path)
    root = tmp_path / "explicit-run"
    _record(root, {"run_id": typed.run_id, "request_id": typed.request_id, "feature_id": typed.feature_id,
        "current_stage": "patch_proposal", "canonical_source_unchanged": False,
        "product_execution_result": typed.to_dict()})
    result = project_product_execution(root)
    assert result["typed_result_status"] == "validated"
    assert result["source_validation"]["canonical_source_status"] == "not_applicable"
    assert result["source_validation"]["source_change_status"] == "not_applicable"
    assert result["post_stages"]["build"] == result["post_stages"]["runtime"] == "not_reached"
    assert result["upstream_responses"]["recorded_response_count"] is None


def _artifact(root, name, kind, payload):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema_version": "1.0", "artifact_type": kind, "feature_id": "unit-feature",
        "producer_stage": "unit_readonly_fixture", "status": "success", "data": payload,
        "inputs": {"upstream_artifacts": []}, "blockers": [], "trace_refs": []}
    digest = ArtifactStore._stable_hash(ArtifactStore._envelope_content_for_hash(document))
    document["artifact_hash"] = digest
    path.write_text(json.dumps(document), encoding="utf-8")
    return {"feature_id": "unit-feature", "artifact_type": kind, "path": str(path), "artifact_hash": digest}


def _pending(root):
    evidence = _artifact(root, "explicit-records/evidence.json", "evidence_pack", {
        "budget_summary": {"requirement_coverage_model_audits": [
            {"model_role": "requirement_projection", "structured_output_sha256": "1" * 64},
            {"model_role": "requirement_findings", "structured_output_sha256": "2" * 64}]}})
    identity = {"run_id": "unit-run", "request_id": "unit-request", "feature_id": "unit-feature"}
    checkpoint = _artifact(root, "explicit-records/pause.json", "workflow_checkpoint", {
        **identity, "checkpoint_stage": "dry_run_apply", "state_snapshot": {**identity,
            "current_stage": "dry_run_apply", "artifacts": {"evidence_pack": evidence["path"]},
            "artifact_hashes": {"evidence_pack": evidence["artifact_hash"]}}})
    _record(root, {**identity, "current_stage": "awaiting_approval", "status": "awaiting_approval",
        "workflow_checkpoint": checkpoint, "canonical_source_unchanged": True})
    return checkpoint


def test_pending_query_reads_bound_checkpoint_and_two_upstream_responses_without_execution(tmp_path, monkeypatch):
    import socket

    _pending(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("No network in query."))
    monkeypatch.setattr(ArtifactStore, "read", lambda *a, **k: pytest.fail("No Artifact admission validator in query."))
    monkeypatch.setattr(ArtifactStore, "write", lambda *a, **k: pytest.fail("No Artifact writes in query."))
    result = project_product_execution(tmp_path)
    assert result["approval_status"] == "awaiting_approval"
    assert result["upstream_responses"]["recorded_response_count"] == 2
    assert [row["model_role"] for row in result["upstream_responses"]["records"]] == ["requirement_projection", "requirement_findings"]
    assert result["model_accounting"]["native_send_count"] is None
    assert set(result["post_stages"].values()) == {"not_reached_at_saved_pause"}
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_pending_checkpoint_hash_tampering_is_rejected(tmp_path):
    reference = _pending(tmp_path)
    path = Path(reference["path"])
    document = json.loads(path.read_text(encoding="utf-8"))
    document["data"]["request_id"] = "changed"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="product_artifact_content_hash_mismatch"):
        project_product_execution(tmp_path)
