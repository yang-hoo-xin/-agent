from __future__ import annotations

from pathlib import Path

import pytest

from src.mod_agent.execution import ExactTextPatchApplier, PatchApplyError


def _plan() -> dict[str, object]:
    return {
        "binding_registry": {
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "canonical_target_path": "Patches/Behavior.cs",
                }
            ]
        }
    }


def _proposal() -> dict[str, object]:
    return {
        "proposal_id": "proposal_001",
        "diff_intent": [
            {
                "change_id": "change_001",
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Color.Red",
                    "after_text": "Color.Pink",
                    "expected_occurrences": 1,
                },
            }
        ],
    }


def _review() -> dict[str, object]:
    return {"decision": "approve_dry_run", "allowed_next_stage": "dry_run_apply"}


def test_dry_run_validates_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\n", encoding="utf-8")

    result = ExactTextPatchApplier().run(
        workspace_root=tmp_path,
        proposal=_proposal(),
        implementation_plan=_plan(),
        review=_review(),
        allow_write=False,
    )

    assert result["actual_write_performed"] is False
    assert result["diff_hash"].startswith("sha256:")
    assert result["approved_by_user"] is False
    assert source.read_text(encoding="utf-8") == "value = Color.Red;\n"


def test_approved_isolated_apply_writes_exactly_once(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\n", encoding="utf-8")

    applier = ExactTextPatchApplier()
    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=_proposal(),
        implementation_plan=_plan(),
        review=_review(),
        allow_write=False,
    )
    result = applier.run(
        workspace_root=tmp_path,
        proposal=_proposal(),
        implementation_plan=_plan(),
        review=_review(),
        allow_write=True,
        approved_diff_hash=dry_run["diff_hash"],
    )

    assert result["real_patch_applied"] is True
    assert result["approved_by_user"] is True
    assert result["approved_diff_hash"] == dry_run["diff_hash"]
    assert source.read_text(encoding="utf-8") == "value = Color.Pink;\n"


def test_apply_rejects_missing_or_mismatched_exact_diff_hash(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\n", encoding="utf-8")

    for approved_hash in (None, "", "sha256:not-the-current-diff"):
        with pytest.raises(PatchApplyError, match="diff hash"):
            ExactTextPatchApplier().run(
                workspace_root=tmp_path,
                proposal=_proposal(),
                implementation_plan=_plan(),
                review=_review(),
                allow_write=True,
                approved_diff_hash=approved_hash,
            )

    assert source.read_text(encoding="utf-8") == "value = Color.Red;\n"


def test_diff_hash_binds_exact_after_text(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\n", encoding="utf-8")
    pink = ExactTextPatchApplier().run(
        workspace_root=tmp_path,
        proposal=_proposal(),
        implementation_plan=_plan(),
        review=_review(),
        allow_write=False,
    )
    changed = _proposal()
    changed["diff_intent"][0]["patch"]["after_text"] = "Color.Magenta"
    magenta = ExactTextPatchApplier().run(
        workspace_root=tmp_path,
        proposal=changed,
        implementation_plan=_plan(),
        review=_review(),
        allow_write=False,
    )

    assert pink["diff_hash"] != magenta["diff_hash"]


def test_approved_hash_blocks_live_source_drift_before_write(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\n", encoding="utf-8")
    applier = ExactTextPatchApplier()
    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=_proposal(),
        implementation_plan=_plan(),
        review=_review(),
        allow_write=False,
    )
    source.write_text("// external drift\nvalue = Color.Red;\n", encoding="utf-8")

    with pytest.raises(PatchApplyError, match="diff hash"):
        applier.run(
            workspace_root=tmp_path,
            proposal=_proposal(),
            implementation_plan=_plan(),
            review=_review(),
            allow_write=True,
            approved_diff_hash=dry_run["diff_hash"],
        )

    assert source.read_text(encoding="utf-8") == "// external drift\nvalue = Color.Red;\n"


def test_approved_hash_binds_proposal_and_implementation_context(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\n", encoding="utf-8")
    applier = ExactTextPatchApplier()
    dry_run = applier.run(
        workspace_root=tmp_path,
        proposal=_proposal(),
        implementation_plan=_plan(),
        review=_review(),
        allow_write=False,
    )
    changed_proposal = _proposal()
    changed_proposal["review_note"] = "changed after approval"
    changed_plan = _plan()
    changed_plan["side_effect_boundaries"] = ["changed after approval"]

    for proposal, plan in (
        (changed_proposal, _plan()),
        (_proposal(), changed_plan),
    ):
        with pytest.raises(PatchApplyError, match="diff hash"):
            applier.run(
                workspace_root=tmp_path,
                proposal=proposal,
                implementation_plan=plan,
                review=_review(),
                allow_write=True,
                approved_diff_hash=dry_run["diff_hash"],
            )

    assert source.read_text(encoding="utf-8") == "value = Color.Red;\n"


def test_apply_rejects_stale_or_ambiguous_before_text(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("Color.Red Color.Red\n", encoding="utf-8")

    with pytest.raises(PatchApplyError, match="found 2"):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=_proposal(),
            implementation_plan=_plan(),
            review=_review(),
            allow_write=True,
            approved_diff_hash="sha256:irrelevant-because-source-is-ambiguous",
        )
