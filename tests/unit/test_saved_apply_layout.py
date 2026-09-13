"""Saved product layout through original review/apply admission; temporary fixtures only."""
from dataclasses import replace
import json
from pathlib import Path
import socket

import pytest

from src.mod_agent.fresh_planning_continuation import preflight_patch_continuation, run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.reviewed_patch_continuation import prepare_reviewed_patch_apply, apply_reviewed_patch, review_run
from tests.unit.test_saved_patch_admission import saved_case


@pytest.fixture
def saved_product(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *args: pytest.fail("No network/model in saved Apply fixture."))
    request, admitted, _, _, _ = saved_case(tmp_path, product_layout=True)
    assert Path(request.artifact_store_root).is_relative_to(Path(request.workspace_root))
    # This is the real saved admission; no replacement preflight or fake saved
    # selection is used. Compilation records are explicitly synthetic fixtures.
    preflight_patch_continuation(request)
    result = run_fresh_patch_continuation(request, patch_change_factory=None, max_model_calls=0,
        dry_run_factory=make_exact_no_write_dry_run_factory(request.workspace_root))
    assert result.status == "terminal", result.to_dict()
    assert result.execution_counts["model"] == 0
    config = dict(artifact_store_root=request.artifact_store_root, workspace_root=request.workspace_root,
                  feature_id=request.feature_spec_ref.feature_id, run_id=result.run_id)
    assert review_run(**config)["status"] == "reviewable_diff"
    isolation = tmp_path / "isolated"
    isolation.mkdir()
    return request, admitted, result, {**config, "isolated_root": str(isolation)}


def test_saved_product_layout_reaches_original_apply_admission(saved_product):
    _, _, _, config = saved_product
    source = Path(config["workspace_root"])
    source_before = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*.cs")}
    prepared = prepare_reviewed_patch_apply(**config, operation_id="saved-layout-apply")
    assert prepared["status"] == "reviewable_diff"
    binding = prepared["apply_preparation"]["binding"]
    store_relative = Path(config["artifact_store_root"]).relative_to(source)
    assert binding["excluded_copy_paths"] == [store_relative.as_posix()]
    result = apply_reviewed_patch(**config, displayed_binding=binding,
        human_semantic_decision={**binding["human_semantic_decision_binding"],
                                 "decision": "approve", "reviewer_identity": "fixture-human"})
    assert result["status"] == "applied_in_isolation", result
    assert result["model_calls_performed"] == result["builds_performed"] == result["runtime_executions_performed"] == 0
    assert result["source_workspace_written"] is False and result["product_source_writes_performed"] is True
    assert source_before == {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*.cs")}
    destination = Path(result["isolated_workspace"])
    assert not (destination / store_relative).exists()
    for relative, before in source_before.items():
        expected = before.replace(b"KeepExistingFeedback();", b"KeepExistingFeedback();\n        RecordRuntimeMarker();")
        assert (destination / relative).read_bytes() == expected
    stored = json.loads(Path(result["isolated_apply_result"]["path"]).read_text(encoding="utf-8"))
    assert stored["status"] == "success" and stored["data"]["approved_diff_hash"] == binding["diff_hash"]


def test_ordinary_fresh_still_rejects_product_store_overlap(saved_product):
    request, *_ = saved_product
    with pytest.raises(ValueError) as caught:
        preflight_patch_continuation(replace(request, saved_patch_selection=None))
    assert caught.value.code == "PATCH_CONTINUATION_ROOTS_OVERLAP"


@pytest.mark.parametrize("damage", ["source_drift", "wrong_approval"])
def test_saved_apply_rejects_source_drift_or_wrong_approval_without_copy_or_write(saved_product, damage):
    _, _, _, config = saved_product
    prepared = prepare_reviewed_patch_apply(**config, operation_id="saved-layout-negative")
    binding = prepared["apply_preparation"]["binding"]
    decision = {**binding["human_semantic_decision_binding"], "decision": "approve", "reviewer_identity": "fixture-human"}
    source = Path(config["workspace_root"])
    if damage == "source_drift":
        target = source / "generated_mods" / "SyntheticMod" / "Behavior.cs"
        target.write_bytes(target.read_bytes() + b"// user changed source after viewing diff\n")
        expected_error = "APPLY_REVIEW_SOURCE_CHANGED"
    else:
        decision["diff_hash"] = "sha256:" + "0" * 64
        expected_error = "diff_hash does not match"
    source_before = {str(path): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    with pytest.raises((ValueError, RuntimeError), match=expected_error):
        apply_reviewed_patch(**config, displayed_binding=binding, human_semantic_decision=decision)
    assert source_before == {str(path): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    assert not Path(binding["isolated_workspace"]).exists()
    assert list(Path(config["isolated_root"]).iterdir()) == []
