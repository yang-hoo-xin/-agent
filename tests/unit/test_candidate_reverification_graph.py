"""Retained candidate verification reaches the original Graph without provider calls."""
from dataclasses import fields
import json
from pathlib import Path

import pytest

from src.mod_agent.fresh_planning_continuation import PatchContinuationInputV1, run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from tests.unit import test_saved_candidate_reverification as candidate_cases

case = candidate_cases.case


def request_from(case):
    original, _, _ = case
    values = {field.name: getattr(original, field.name) for field in fields(PatchContinuationInputV1)}
    values.update(saved_patch_selection=None, attempt_id="candidate-graph-once")
    return PatchContinuationInputV1(**values)


def test_real_graph_reverifies_once_and_replays_without_new_evaluation(case, tmp_path, monkeypatch):
    from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
    monkeypatch.setattr(LocalOllamaInitialPatchAdapter, "__call__", lambda *a: pytest.fail("provider factory must not run"))
    request = request_from(case)
    def run():
        return run_fresh_patch_continuation(request, patch_change_factory=None, max_model_calls=0,
            dry_run_factory=make_exact_no_write_dry_run_factory(request.workspace_root))
    first = run()
    assert first.status == "terminal", first.to_dict()
    assert first.terminal_stage == "dry_run_apply"
    assert first.execution_counts["model"] == 0
    assert first.execution_counts["patch"] == first.execution_counts["review"] == first.execution_counts["dry_run"] == 1
    assert (tmp_path / "calls.txt").read_text() == "1"
    repeated = run()
    assert repeated.status == "terminal" and repeated.run_id == first.run_id
    assert (tmp_path / "calls.txt").read_text() == "1"


def test_candidate_graph_rejects_model_adapter_before_verification(case, tmp_path):
    request = request_from(case)
    result = run_fresh_patch_continuation(request, patch_change_factory=lambda *a: pytest.fail("no provider"), max_model_calls=0,
        dry_run_factory=make_exact_no_write_dry_run_factory(request.workspace_root))
    assert result.status == "blocked"
    assert not (tmp_path / "calls.txt").exists()


def test_verifier_scratch_csharp_is_not_mistaken_for_target_source_drift(case, tmp_path):
    from tests.unit.test_saved_patch_admission import _ref, _save
    request = request_from(case)
    config = json.loads(Path(request.worker_configuration_ref["path"]).read_bytes())
    source = Path(config["behavior_evaluator"]["factory_ref"]["path"])
    scratch = Path(request.workspace_root) / "checks/compiled_copy.cs"
    source.write_text(source.read_text(encoding="utf-8").replace('count=root/"calls.txt"',
        f'Path({str(scratch.parent)!r}).mkdir(parents=True,exist_ok=True)\n        Path({str(scratch)!r}).write_text("class CompiledCopy {{}}")\n        count=root/"calls.txt"'), encoding="utf-8")
    config["behavior_evaluator"]["factory_ref"] = _ref(source)
    from dataclasses import replace
    request = replace(request, worker_configuration_ref=_save(Path(request.worker_configuration_ref["path"]), config))
    result = run_fresh_patch_continuation(request, patch_change_factory=None, max_model_calls=0,
        dry_run_factory=make_exact_no_write_dry_run_factory(request.workspace_root))
    assert result.status == "terminal", result.to_dict()
    assert result.source_modified_during_run is False and scratch.exists()
