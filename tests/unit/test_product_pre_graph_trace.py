"""Pre-Graph callbacks keep their original behavior and add measured observations."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.trace.execution_trace import current_trace, trace_operation
from src.mod_agent.patch_execution_trace import product_execution_trace, preserve_product_trace_projection
from tests.unit import test_local_entry as original


@pytest.mark.parametrize("scenario,failure_stage", [
    (original.test_pre_graph_restore_failure_records_exact_stage_and_stops, "baseline_restore"),
    (original.test_pre_graph_verifier_failure_persists_terminal_lineage, "baseline_artifact_verification"),
    (original.test_member_access_dependency_failure_is_persisted_before_graph, "compiled_artifact_member_access_dependency"),
    (original.test_pre_graph_cleanup_failure_is_terminally_bound, "pre_graph_generated_directory_cleanup"),
])
def test_original_pre_graph_failure_is_now_visible_in_same_product_trace(tmp_path, monkeypatch, scenario, failure_stage):
    # These existing scenarios inject build/inspection results; no compiler,
    # provider or game process is started by the acceptance fixture.
    scenario(tmp_path=tmp_path, monkeypatch=monkeypatch)
    run_root = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    rows = list(manifest["execution_observations"].values())
    root = next(row for row in rows if row["parent_id"] is None)
    assert root["name"] == "product.execution" and root["status"] == "failed"
    assert root["attributes"]["timing_scope"] == "product_execution_from_environment_admission"
    assert root["attributes"]["terminal_stage"] == failure_stage
    assert root["attributes"]["terminal_record_ref"] == manifest["terminal_record"]
    failures = [row for row in rows if row["name"] == "preflight.failure"]
    assert len(failures) == 1 and failures[0]["attributes"]["failure_stage"] == failure_stage
    assert failures[0]["attributes"]["timing_scope"] == "failure_decision_record_only"
    assert failures[0]["attributes"]["local_detail_refs"]["failure"] == manifest["terminal_record"]
    assert all(row["trace_id"] == root["trace_id"] and row["finished_at"] for row in rows)
    assert any(row["attributes"].get("callback_invoked") is True for row in rows)
    assert not any(row["kind"] == "generation" for row in rows)
    assert manifest["model_call_count"] == 0 and manifest["graph_invoked"] is False
    assert {"environment.settings", "environment.prepare", "source.admission"}.issubset({r["name"] for r in rows})
    assert manifest["execution_trace"]["failures"]["recorder"]["total"] == 0
    assert current_trace() is None


def test_manifest_owner_refresh_keeps_prior_observations_and_business_fields(tmp_path):
    path = tmp_path / "run_manifest.json"
    initial = {"run_id": "run-1", "request_id": "request-1", "status": "admitted"}
    path.write_text(json.dumps(initial), encoding="utf-8")
    with product_execution_trace(run_root=tmp_path, run_id="run-1", request_id="request-1",
                                 artifact_store_root=tmp_path / "a"):
        with trace_operation("workspace_preparation"):
            pass
        previous = json.loads(path.read_text(encoding="utf-8"))["execution_observations"]
        refreshed = preserve_product_trace_projection({**initial, "status": "baseline_verified", "baseline": "retained"}, tmp_path)
        path.write_text(json.dumps(refreshed), encoding="utf-8")
        assert refreshed["execution_observations"] == previous
        with trace_operation("requirements.projection"):
            pass
    final = json.loads(path.read_text(encoding="utf-8"))
    assert final["status"] == "baseline_verified" and final["baseline"] == "retained"
    assert {row["name"] for row in final["execution_observations"].values()} == {
        "product.execution", "workspace_preparation", "requirements.projection"}


def test_invalid_input_before_run_instance_does_not_create_fictional_trace(tmp_path):
    with pytest.raises(original.LocalEntryError, match="non-empty natural-language"):
        original.run_local_request(description="", target_project=tmp_path / "absent",
            workspace_base=tmp_path / "runs", settings_path=Path("absent-settings"),
            confirm_isolated_write=False, allow_build=False, allow_source_disclosure=False)
    assert not (tmp_path / "runs").exists() and current_trace() is None


@pytest.mark.parametrize("missing,stage", [
    ("settings", "environment.settings"),
    ("model", "environment.prepare"),
    ("source", "source.admission"),
])
def test_environment_and_missing_material_failure_keeps_buffered_trace_without_creating_run(tmp_path, monkeypatch, missing, stage):
    original._install_local_ollama_factory(monkeypatch)
    identity = original._ollama_identity()
    if missing == "model":
        identity["model"] = "wrong-model"
    settings = tmp_path / "absent-settings.yaml" if missing == "settings" else Path("config/settings.yaml")
    with pytest.raises((original.LocalEntryError, OSError, ValueError)) as caught:
        original.run_local_request(description="change the default setting",
            target_project=tmp_path / "absent-source", workspace_base=tmp_path / "runs",
            settings_path=settings, confirm_isolated_write=True, allow_build=True,
            allow_source_disclosure=False, diff_approval_reader=lambda _: "unused",
            local_ollama=True, ollama_model="qwen3:4b-instruct", ollama_context_window=32768,
            ollama_model_identity_reader=lambda *_: identity,
            ollama_server_version_reader=lambda *_: "0.32.1", run_id="early-run", request_id="early-task")
    error = caught.value
    rows = list(error.execution_observations.values())
    root = next(row for row in rows if row["parent_id"] is None)
    assert root["status"] == "failed" and root["attributes"]["terminal_stage"] == stage
    assert next(row for row in rows if row["name"] == stage)["status"] == "failed"
    assert not any(row["kind"] == "generation" for row in rows)
    assert error.execution_trace["failures"]["recorder"]["total"] == 0
    assert error.execution_trace["local_observation_source"] == {
        "storage": "exception.execution_observations", "persisted": False}
    assert not (tmp_path / "runs").exists()
    if missing == "source":
        observed = next(row for row in rows if row["name"] == stage)["attributes"]
        assert observed["source_directory_exists"] is False and observed["project_file_discovered"] is False
        assert observed["failure_code"] == "SOURCE_PROJECT_MATERIAL_UNAVAILABLE"


def test_buffered_trace_does_not_touch_older_manifest_when_new_invocation_fails(tmp_path):
    path = tmp_path / "run_manifest.json"
    before = b'{"run_id":"old-run","request_id":"old-request","important":"preserve"}'
    path.write_bytes(before)
    original_error = ValueError("environment unavailable")
    with pytest.raises(ValueError) as caught:
        with product_execution_trace(run_root=tmp_path, run_id="old-run", request_id="old-request",
                                     artifact_store_root=tmp_path / "a", buffer_until_manifest=True):
            with trace_operation("environment.settings"):
                raise original_error
    assert caught.value is original_error and path.read_bytes() == before
    assert original_error.execution_trace["local_observation_source"]["persisted"] is False


def test_public_run_request_error_json_exposes_early_trace_without_new_error_surface(tmp_path, capsys):
    from src.mod_agent.cli import main
    result = main(["run-request", "change the default setting", "--target-project", str(tmp_path / "absent"),
        "--settings", str(tmp_path / "missing.yaml"), "--workspace-root", str(tmp_path / "runs"),
        "--local-ollama", "--ollama-model", "qwen3:4b-instruct", "--ollama-context-window", "32768",
        "--confirm-isolated-write", "--allow-build", "--run-id", "early-cli", "--request-id", "logical-task"])
    payload = json.loads(capsys.readouterr().out)
    assert result == 2 and payload["status"] == "BLOCKED"
    assert payload["execution_trace"]["logical_request_id"] == "logical-task"
    rows = list(payload["execution_observations"].values())
    assert any(row["name"] == "environment.settings" and row["status"] == "failed" for row in rows)
    assert not (tmp_path / "runs").exists()
