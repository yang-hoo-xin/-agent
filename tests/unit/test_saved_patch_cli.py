"""Public saved-response dispatch and durable no-model continuation."""
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.mod_agent import cli
from src.mod_agent.fresh_planning_continuation import (
    _source_tree_snapshot_sha256,
    run_fresh_patch_continuation,
)
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.reviewed_patch_continuation import review_run
from tests.unit.test_saved_patch_graph import _saved_inputs


def _arguments(tmp_path):
    (tmp_path / "source").mkdir()
    selection = {
        "source_attempt_ref": {"path": str(tmp_path / "source.json"), "sha256": "a" * 64},
        "logical_budget_ref": {"path": str(tmp_path / "budget.json"), "sha256": "b" * 64},
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(selection), encoding="utf-8")
    argv = ["continue-fresh-patch", "--artifact-root", str(tmp_path / "store"),
            "--workspace-root", str(tmp_path / "source"), "--feature-id", "feature_test",
            "--feature-spec-path", str(tmp_path / "feature.json"), "--feature-spec-hash", "c" * 64,
            "--evidence-pack-path", str(tmp_path / "evidence.json"), "--evidence-pack-hash", "d" * 64,
            "--implementation-plan-path", str(tmp_path / "plan.json"), "--implementation-plan-hash", "e" * 64,
            "--attempt-id", "saved_cli_test", "--reassemble-saved-patch", str(path)]
    return argv, selection


@pytest.mark.parametrize("extra", [
    ["--ollama-model", "never_called"], ["--ollama-context-window", "32768"],
    ["--ollama-base-url", "http://127.0.0.1:11434"], ["--ollama-output-budget", "4096"],
    ["--ollama-timeout-seconds", "60"], ["--patch-agent-loop"],
    ["--patch-worker-config", "unused.json"], ["--patch-upstream-config", "unused.json"],
    ["--qualified-model-routing", "unused.json"],
])
def test_saved_cli_rejects_model_execution_controls_before_owner(tmp_path, monkeypatch, capsys, extra):
    argv, _ = _arguments(tmp_path)
    monkeypatch.setattr(cli, "run_fresh_patch_continuation",
        lambda *a, **k: pytest.fail("Conflicting model controls reached execution."))
    assert cli.main([*argv, *extra]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["first_failure"]["code"] == "PATCH_SAVED_MODEL_ARGUMENT_CONFLICT"
    assert result["new_provider_sends"] == 0


def test_saved_cli_requires_named_attempt(tmp_path, monkeypatch, capsys):
    argv, _ = _arguments(tmp_path)
    index = argv.index("--attempt-id")
    del argv[index:index + 2]
    monkeypatch.setattr(cli, "run_fresh_patch_continuation",
        lambda *a, **k: pytest.fail("Unnamed saved attempt reached execution."))
    assert cli.main(argv) == 1
    assert json.loads(capsys.readouterr().out)["first_failure"]["code"] == "PATCH_SAVED_SELECTION_INVALID"


def test_saved_cli_forwards_no_factory_and_displays_existing_review_view(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    argv, selection = _arguments(tmp_path)
    seen = []
    def run(request, **kwargs):
        assert request.saved_patch_selection == selection
        assert kwargs["patch_change_factory"] is None and kwargs["max_model_calls"] == 0
        seen.append(request)
        return SimpleNamespace(status="terminal", run_id="saved_result", to_dict=lambda: {
            "status": "terminal", "execution_counts": {"model": 0}, "run_id": "saved_result"})
    monkeypatch.setattr(cli, "run_fresh_patch_continuation", run)
    monkeypatch.setattr(cli, "LocalOllamaInitialPatchProfileV1",
        lambda *a, **k: pytest.fail("Saved mode built a model profile."))
    monkeypatch.setattr("src.mod_agent.reviewed_patch_continuation.review_run",
        lambda **k: {"status": "reviewable_diff", "unified_diff": "--- before\n+++ after\n",
                     "diff_hash": "sha256:" + "f" * 64})
    assert cli.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(seen) == 1 and result["approval_status"] == "awaiting_exact_diff_approval"
    assert result["generation_origin"] == "reused_saved_response"
    assert result["unified_diff"].startswith("--- before")
    assert result["new_provider_sends"] == 0


def test_saved_runner_records_zero_budget_and_idempotent_reviewable_result(tmp_path, monkeypatch):
    # Only old-source admission is isolated here; Graph, Store, journal, review and
    # no-write applier are real. Strict old-source admission has separate tests.
    inputs, request, admitted, _, _, _, _ = _saved_inputs(tmp_path, monkeypatch)
    selection = {
        "source_attempt_ref": admitted.saved_patch["source_attempt_ref"],
        "logical_budget_ref": {"path": str(tmp_path / "budget.json"), "sha256": "d" * 64},
    }
    object.__setattr__(request, "saved_patch_selection", selection)
    object.__setattr__(request, "attempt_id", "saved_runner")
    admitted.saved_patch["source_snapshot_sha256"] = _source_tree_snapshot_sha256(admitted.source_tree_snapshot)
    def admit(mode, *, artifact_store=None):
        assert mode is request
        if artifact_store is not None:
            assert artifact_store.root == inputs.store.root
        return admitted
    monkeypatch.setattr("src.mod_agent.fresh_planning_continuation.preflight_patch_continuation", admit)
    monkeypatch.setattr("src.mod_agent.workflow.graph.preflight_patch_continuation", admit)
    kwargs = {"patch_change_factory": None, "max_model_calls": 0,
              "dry_run_factory": make_exact_no_write_dry_run_factory(inputs.workspace)}
    before = {str(p): p.read_bytes() for p in inputs.workspace.rglob("*.cs")}
    result = run_fresh_patch_continuation(request, **kwargs)
    assert result.status == "terminal", result.to_dict()
    assert result.request_id == admitted.saved_patch["request_id"]
    assert result.execution_counts == {"fresh_coverage": 0, "model": 0, "planning": 0,
        "patch": 1, "review": 1, "dry_run": 1, "apply": 0, "build": 0, "runtime": 0}
    receipt_path = result.attempt_receipt["path"]
    from pathlib import Path
    receipt_before = Path(receipt_path).read_bytes()
    journal = json.loads(receipt_before)
    assert journal["max_model_calls"] == journal["model_call_count"] == journal["new_provider_sends"] == 0
    assert journal["logical_budget"] == admitted.saved_patch["logical_budget"]
    assert "factory_receipt" not in journal
    assert not any(row["kind"] == "generation" for row in journal.get("execution_observations", {}).values())
    view = review_run(artifact_store_root=request.artifact_store_root, workspace_root=request.workspace_root,
                      feature_id=request.feature_spec_ref.feature_id, run_id=result.run_id)
    assert view["status"] == "reviewable_diff", view
    assert view["saved_patch_reassembly"]["generation_origin"] == "reused_saved_response"
    repeated = run_fresh_patch_continuation(request, **kwargs)
    assert repeated.status == "terminal" and repeated.run_id == result.run_id
    assert Path(receipt_path).read_bytes() == receipt_before
    changed_selection = deepcopy(selection)
    changed_selection["source_attempt_ref"]["sha256"] = "e" * 64
    conflict = run_fresh_patch_continuation(replace(request, saved_patch_selection=changed_selection), **kwargs)
    assert conflict.first_failure["code"] == "PATCH_CONTINUATION_ATTEMPT_IDENTITY_CONFLICT"
    assert Path(receipt_path).read_bytes() == receipt_before
    assert before == {str(p): p.read_bytes() for p in inputs.workspace.rglob("*.cs")}
