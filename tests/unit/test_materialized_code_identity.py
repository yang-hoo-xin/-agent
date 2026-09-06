from __future__ import annotations

import codecs
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.execution.patch_apply import (
    ExactTextPatchApplier,
    PatchApplyError,
    materialize_exact_text_patch,
)


def _inputs(tmp_path: Path) -> tuple[dict, list[dict], bytes]:
    baseline = codecs.BOM_UTF8 + b"value = Color.Red;\r\nflag = false;\r\n"
    (tmp_path / "Behavior.cs").write_bytes(baseline)
    plan = {
        "binding_registry": {
            "edit_bindings": [
                {
                    "binding_id": f"edit_binding_{index:03d}",
                    "canonical_target_path": "Behavior.cs",
                    "source_hash": hashlib.sha256(baseline).hexdigest(),
                    "target_span": {"start_line": index, "end_line": index},
                }
                for index in (1, 2)
            ]
        }
    }
    changes = [
        {
            "change_id": f"change_{index:03d}",
            "edit_binding_id": f"edit_binding_{index:03d}",
            "rationale": "Synthetic fixture; this is not a behavior verdict.",
            "patch": {
                "kind": "exact_text_replace",
                "before_text": before,
                "after_text": after,
                "expected_occurrences": 1,
            },
        }
        for index, before, after in (
            (1, "Color.Red", "Color.Pink"),
            (2, "false", "true"),
        )
    ]
    return plan, changes, baseline


def test_compare_materialized_code_against_failed_version_not_base_diff(
    tmp_path: Path,
) -> None:
    plan, changes, baseline = _inputs(tmp_path)
    failed = materialize_exact_text_patch(
        workspace_root=tmp_path, diff_intent=changes, implementation_plan=plan,
    )
    repeated = deepcopy(changes)
    for change in repeated:
        change["rationale"] = "Different explanation for unchanged code."
    repeated = json.loads(json.dumps(repeated[::-1], sort_keys=True))
    resubmitted = materialize_exact_text_patch(
        workspace_root=tmp_path, diff_intent=repeated, implementation_plan=plan,
    )

    assert failed.files == resubmitted.files
    assert failed.code_sha256 == resubmitted.code_sha256
    assert failed.baseline_sha256 == resubmitted.baseline_sha256
    assert failed.code_sha256 != failed.baseline_sha256
    assert failed.baseline_files == {"Behavior.cs": baseline}
    assert failed.files == {
        "Behavior.cs": codecs.BOM_UTF8 + b"value = Color.Pink;\r\nflag = true;\r\n"
    }
    assert (tmp_path / "Behavior.cs").read_bytes() == baseline


def test_different_output_identity_is_not_a_repair_verdict(tmp_path: Path) -> None:
    plan, changes, _ = _inputs(tmp_path)
    previous = materialize_exact_text_patch(
        workspace_root=tmp_path, diff_intent=changes, implementation_plan=plan,
    )
    changes[0]["patch"]["after_text"] = "Color.Magenta"
    revised = materialize_exact_text_patch(
        workspace_root=tmp_path, diff_intent=changes, implementation_plan=plan,
    )

    assert previous.code_sha256 != revised.code_sha256
    assert previous.baseline_sha256 == revised.baseline_sha256
    assert not hasattr(revised, "behavior_passed")
    assert not hasattr(revised, "approved_by_review")


def test_materialization_rejects_drift_outside_replaced_text(tmp_path: Path) -> None:
    plan, changes, baseline = _inputs(tmp_path)
    (tmp_path / "Behavior.cs").write_bytes(baseline + b"other = true;\r\n")

    with pytest.raises(PatchApplyError, match="source_hash"):
        materialize_exact_text_patch(
            workspace_root=tmp_path, diff_intent=changes, implementation_plan=plan,
        )


@pytest.mark.parametrize("defect", ["span", "occurrences", "bom"])
def test_no_write_materialization_keeps_existing_exact_patch_checks(
    tmp_path: Path, defect: str,
) -> None:
    plan, changes, baseline = _inputs(tmp_path)
    if defect == "span":
        plan["binding_registry"]["edit_bindings"][0]["target_span"] = {
            "start_line": 2, "end_line": 2,
        }
        expected_error = "outside edit binding target_span"
    elif defect == "occurrences":
        changes[0]["patch"]["expected_occurrences"] = 2
        expected_error = "expected one live source match"
    else:
        changes[0]["patch"]["before_text"] = "\ufeffvalue = Color.Red;"
        changes[0]["patch"]["after_text"] = "value = Color.Pink;"
        expected_error = "preserve the UTF-8 BOM"

    with pytest.raises(PatchApplyError, match=expected_error):
        materialize_exact_text_patch(
            workspace_root=tmp_path, diff_intent=changes, implementation_plan=plan,
        )
    assert (tmp_path / "Behavior.cs").read_bytes() == baseline


def test_formal_dry_run_uses_same_materialized_bytes_and_retains_review_gate(
    tmp_path: Path,
) -> None:
    plan, changes, baseline = _inputs(tmp_path)
    proposal = {"proposal_id": "proposal_001", "diff_intent": changes}
    materialized = materialize_exact_text_patch(
        workspace_root=tmp_path, diff_intent=changes, implementation_plan=plan,
    )

    with pytest.raises(PatchApplyError, match="review did not allow"):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path, proposal=proposal, implementation_plan=plan,
            review={"allowed_next_stage": "repair"}, allow_write=False,
        )
    dry_run = ExactTextPatchApplier().run(
        workspace_root=tmp_path, proposal=proposal, implementation_plan=plan,
        review={"allowed_next_stage": "dry_run_apply"}, allow_write=False,
    )

    assert dry_run["changes"][-1]["raw_after_sha256"] == hashlib.sha256(
        materialized.files["Behavior.cs"]
    ).hexdigest()
    assert dry_run["actual_write_performed"] is False
    assert (tmp_path / "Behavior.cs").read_bytes() == baseline
