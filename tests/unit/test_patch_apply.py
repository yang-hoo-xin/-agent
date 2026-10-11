from __future__ import annotations

import codecs
import hashlib
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
    assert result["unified_diff"].startswith("--- a/Patches/Behavior.cs\n")
    assert result["unified_diff_sha256"] == hashlib.sha256(
        result["unified_diff"].encode("utf-8")
    ).hexdigest()
    assert result["diff_stats"] == {
        "files": 1,
        "change_units": 1,
        "insertions": 1,
        "deletions": 1,
    }
    assert result["static_checks"] == [
        {
            "check_id": "csharp_delimiter_balance",
            "status": "passed",
            "path": "Behavior.cs",
            "limitations": (
                "This lexical check does not resolve symbols, types, overloads, "
                "or all control-flow errors."
            ),
        }
    ]
    assert source.read_text(encoding="utf-8") == "value = Color.Red;\n"


def test_dry_run_rejects_change_outside_bound_source_span(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\nother = true;\n", encoding="utf-8")
    plan = _plan()
    plan["binding_registry"]["edit_bindings"][0]["target_span"] = {
        "start_line": 2,
        "end_line": 2,
    }

    with pytest.raises(PatchApplyError, match="outside edit binding target_span"):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=_proposal(),
            implementation_plan=plan,
            review=_review(),
            allow_write=False,
        )


def test_bound_span_exact_selects_one_duplicate_without_writing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text(
        "first = Color.Red;\nsecond = Color.Red;\n",
        encoding="utf-8",
    )
    plan = _plan()
    plan["binding_registry"]["edit_bindings"][0]["target_span"] = {
        "start_line": 2,
        "end_line": 2,
    }
    proposal = _proposal()
    proposal["diff_intent"][0]["patch"]["match_mode"] = (
        "bound_span_exact"
    )
    proposal["diff_intent"][0]["patch"]["before_text"] = "Color.Red"
    proposal["diff_intent"][0]["patch"]["after_text"] = "Color.Pink"

    result = ExactTextPatchApplier().run(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
        review=_review(),
        allow_write=False,
    )

    assert result["diff_stats"]["insertions"] == 1
    assert result["diff_stats"]["deletions"] == 1
    assert result["static_checks"][0]["match_mode"] == (
        "bound_span_exact"
    )
    assert "+second = Color.Pink;" in result["unified_diff"]
    assert " first = Color.Red;" in result["unified_diff"]
    assert source.read_text(encoding="utf-8") == (
        "first = Color.Red;\nsecond = Color.Red;\n"
    )


def test_bound_span_exact_rejects_anchor_outside_bound_line(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text(
        "first = Color.Red;\nsecond = Color.Blue;\n",
        encoding="utf-8",
    )
    plan = _plan()
    plan["binding_registry"]["edit_bindings"][0]["target_span"] = {
        "start_line": 2,
        "end_line": 2,
    }
    proposal = _proposal()
    proposal["diff_intent"][0]["patch"]["match_mode"] = (
        "bound_span_exact"
    )

    with pytest.raises(
        PatchApplyError,
        match="does not match exactly once inside target_span",
    ):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=proposal,
            implementation_plan=plan,
            review=_review(),
            allow_write=False,
        )


def test_bound_span_exact_must_be_first_change_for_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text(
        "first = Color.Red;\nsecond = Color.Red;\n",
        encoding="utf-8",
    )
    plan = _plan()
    plan["binding_registry"]["edit_bindings"] = [
        {
            "binding_id": "edit_binding_001",
            "canonical_target_path": "Patches/Behavior.cs",
            "target_span": {"start_line": 1, "end_line": 1},
        },
        {
            "binding_id": "edit_binding_002",
            "canonical_target_path": "Patches/Behavior.cs",
            "target_span": {"start_line": 2, "end_line": 2},
        },
    ]
    proposal = _proposal()
    proposal["diff_intent"] = [
        {
            "change_id": "change_000",
            "edit_binding_id": "edit_binding_001",
            "patch": {
                "kind": "exact_text_replace",
                "before_text": "first = Color.Red;",
                "after_text": "first = Color.Pink;",
                "expected_occurrences": 1,
            },
        },
        {
            "change_id": "change_001",
            "edit_binding_id": "edit_binding_002",
            "patch": {
                "kind": "exact_text_replace",
                "match_mode": "bound_span_exact",
                "before_text": "Color.Red",
                "after_text": "Color.Pink",
                "expected_occurrences": 1,
            },
        },
    ]

    with pytest.raises(
        PatchApplyError,
        match="must be the first change for its file",
    ):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=proposal,
            implementation_plan=plan,
            review=_review(),
            allow_write=False,
        )


def test_dry_run_rejects_unbalanced_csharp_replacement(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_text("value = Color.Red;\n", encoding="utf-8")
    proposal = _proposal()
    proposal["diff_intent"][0]["patch"]["after_text"] = "Color.Pink }"

    with pytest.raises(PatchApplyError, match="structural check failed"):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=proposal,
            implementation_plan=_plan(),
            review=_review(),
            allow_write=False,
        )


def test_dry_run_records_new_trailing_whitespace_and_apply_preserves_exact_bytes(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_bytes(b"value = Color.Red;\nnext = true;\n")
    proposal = _proposal()
    proposal["diff_intent"][0]["patch"]["before_text"] = (
        "value = Color.Red;\n"
    )
    proposal["diff_intent"][0]["patch"]["after_text"] = (
        "value = Color.Pink;\n    \n"
    )

    applier = ExactTextPatchApplier()
    dry = applier.run(workspace_root=tmp_path, proposal=proposal,
        implementation_plan=_plan(), review=_review(), allow_write=False)
    assert dry["format_diagnostics"] == {"added_trailing_whitespace_count": 1}
    assert source.read_bytes() == b"value = Color.Red;\nnext = true;\n"
    applied = applier.run(workspace_root=tmp_path, proposal=proposal,
        implementation_plan=_plan(), review=_review(), allow_write=True,
        approved_diff_hash=dry["diff_hash"])
    assert applied["diff_hash"] == dry["diff_hash"]
    assert source.read_bytes() == b"value = Color.Pink;\n    \nnext = true;\n"


def test_dry_run_allows_unchanged_trailing_whitespace(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_bytes(b"existing = true;  \nvalue = Color.Red;\n")

    result = ExactTextPatchApplier().run(
        workspace_root=tmp_path,
        proposal=_proposal(),
        implementation_plan=_plan(),
        review=_review(),
        allow_write=False,
    )

    assert result["actual_write_performed"] is False
    assert " existing = true;  " in result["unified_diff"]


def test_dry_run_checks_added_code_that_starts_with_double_plus(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_bytes(b"counter++;\n")
    proposal = _proposal()
    proposal["diff_intent"][0]["patch"]["before_text"] = "counter++;"
    proposal["diff_intent"][0]["patch"]["after_text"] = "++counter; "

    result = ExactTextPatchApplier().run(workspace_root=tmp_path, proposal=proposal,
        implementation_plan=_plan(), review=_review(), allow_write=False)
    assert result["format_diagnostics"] == {"added_trailing_whitespace_count": 1}
    assert source.read_bytes() == b"counter++;\n"


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
    assert result["semantic_assurance_contract"] == (
        "legacy_non_semantic_exact_diff_v0"
    )
    assert result["human_semantic_review_required"] is False
    assert result["human_semantic_review_completed"] is False
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


def _dry_run_then_apply(
    *,
    workspace_root: Path,
    proposal: dict[str, object] | None = None,
    implementation_plan: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    applier = ExactTextPatchApplier()
    selected_proposal = proposal or _proposal()
    selected_plan = implementation_plan or _plan()
    dry_run = applier.run(
        workspace_root=workspace_root,
        proposal=selected_proposal,
        implementation_plan=selected_plan,
        review=_review(),
        allow_write=False,
    )
    applied = applier.run(
        workspace_root=workspace_root,
        proposal=selected_proposal,
        implementation_plan=selected_plan,
        review=_review(),
        allow_write=True,
        approved_diff_hash=str(dry_run["diff_hash"]),
    )
    return dry_run, applied


def test_exact_apply_preserves_crlf_bytes(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    before = b"header\r\nvalue = Color.Red;\r\nfooter\r\n"
    expected = b"header\r\nvalue = Color.Pink;\r\nfooter\r\n"
    source.write_bytes(before)

    dry_run, applied = _dry_run_then_apply(workspace_root=tmp_path)

    assert source.read_bytes() == expected
    assert source.read_bytes().count(b"\r\n") == before.count(b"\r\n")
    assert dry_run["changes"][0]["raw_before_sha256"] == hashlib.sha256(
        before
    ).hexdigest()
    assert applied["changes"][0]["raw_after_sha256"] == hashlib.sha256(
        expected
    ).hexdigest()


def test_crlf_scope_hash_mismatch_remains_zero_write(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    before = b"header\r\nvalue = Color.Red;\r\nfooter\r\n"
    source.write_bytes(before)

    with pytest.raises(PatchApplyError, match="diff hash"):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=_proposal(),
            implementation_plan=_plan(),
            review=_review(),
            allow_write=True,
            approved_diff_hash="sha256:normalized-scope-is-not-approved",
        )

    assert source.read_bytes() == before
    assert not source.with_name(".Behavior.cs.v2-codegen.tmp").exists()


def test_exact_apply_preserves_lf_bytes(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    before = b"header\nvalue = Color.Red;\nfooter\n"
    expected = b"header\nvalue = Color.Pink;\nfooter\n"
    source.write_bytes(before)

    _dry_run_then_apply(workspace_root=tmp_path)

    assert source.read_bytes() == expected
    assert b"\r\n" not in source.read_bytes()


def test_exact_apply_preserves_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    before = codecs.BOM_UTF8 + b"value = Color.Red;\r\n"
    expected = codecs.BOM_UTF8 + b"value = Color.Pink;\r\n"
    source.write_bytes(before)

    dry_run, applied = _dry_run_then_apply(workspace_root=tmp_path)

    assert source.read_bytes() == expected
    assert dry_run["changes"][0]["encoding"] == "utf-8-bom"
    assert dry_run["changes"][0]["bom_preserved"] is True
    assert applied["changes"][0]["bom_preserved"] is True


def test_exact_apply_preserves_mixed_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    before = b"header\r\nvalue = Color.Red;\nfooter\r\n"
    expected = b"header\r\nvalue = Color.Pink;\nfooter\r\n"
    source.write_bytes(before)

    _dry_run_then_apply(workspace_root=tmp_path)

    assert source.read_bytes() == expected


@pytest.mark.parametrize(
    ("content", "match_count"),
    [
        (b"value = Color.Blue;\n", 0),
        (b"Color.Red Color.Red\n", 2),
    ],
)
def test_dry_run_rejects_zero_or_multiple_raw_matches(
    tmp_path: Path,
    content: bytes,
    match_count: int,
) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_bytes(content)

    with pytest.raises(PatchApplyError, match=f"found {match_count}"):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=_proposal(),
            implementation_plan=_plan(),
            review=_review(),
            allow_write=False,
        )

    assert source.read_bytes() == content


def test_dry_run_and_apply_report_identical_raw_hashes(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    source.write_bytes(b"value = Color.Red;\r\n")

    dry_run, applied = _dry_run_then_apply(workspace_root=tmp_path)

    assert dry_run["diff_hash"] == applied["diff_hash"]
    assert dry_run["changes"] == applied["changes"]
    assert dry_run["changes"][0]["hash_mode"] == "raw_bytes"
    assert dry_run["changes"][0]["raw_after_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()


def test_non_utf8_target_fails_closed_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "Patches" / "Behavior.cs"
    source.parent.mkdir()
    content = codecs.BOM_UTF16_LE + "value = Color.Red;\r\n".encode("utf-16-le")
    source.write_bytes(content)

    with pytest.raises(PatchApplyError, match="not valid UTF-8"):
        ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal=_proposal(),
            implementation_plan=_plan(),
            review=_review(),
            allow_write=False,
        )

    assert source.read_bytes() == content


def test_better_hit_feedback_version_fixture_has_expected_raw_after_hash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Plugin.cs"
    source.write_bytes(_better_hit_feedback_plugin_fixture())
    plan = _plan()
    plan["binding_registry"]["edit_bindings"][0]["canonical_target_path"] = (
        "Plugin.cs"
    )
    proposal = _proposal()
    proposal["diff_intent"][0]["patch"] = {
        "kind": "exact_text_replace",
        "before_text": '    public const string VERSION = "0.1.0";',
        "after_text": '    public const string VERSION = "0.1.1";',
        "expected_occurrences": 1,
    }

    dry_run, applied = _dry_run_then_apply(
        workspace_root=tmp_path,
        proposal=proposal,
        implementation_plan=plan,
    )

    expected_before = "b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c"
    expected_after = "ba54e3b58efd75b304cb8f678ac0a8f29ea6e0c437b73fd455daaf52823ca82c"
    assert dry_run["changes"][0]["raw_before_sha256"] == expected_before
    assert dry_run["changes"][0]["raw_after_sha256"] == expected_after
    assert applied["changes"][0]["raw_after_sha256"] == expected_after
    assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_after


def _better_hit_feedback_plugin_fixture() -> bytes:
    text = """using System;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;

namespace BetterHitFeedback;

[BepInPlugin(GUID, MODNAME, VERSION)]
[BepInProcess("GTFO.exe")]
public sealed class Plugin : BasePlugin
{
    public const string GUID = "local.betterhitfeedback";
    public const string MODNAME = "BetterHitFeedback";
    public const string VERSION = "0.1.0";
    public const string FEATURE_ID = "20260607_194645_create-betterhitfeedback-for-gtfo-non-we";

    public static ManualLogSource LogSource { get; private set; } = null!;
    public static ConfigEntry<bool> EnableDiagnosticLogging { get; private set; } = null!;
    public static ConfigEntry<bool> ConfigEnabled { get; private set; } = null!;

    private Harmony? _harmony;

    public override void Load()
    {
        LogSource = Log;

        EnableDiagnosticLogging = Config.Bind(
            "General",
            "EnableDiagnosticLogging",
            false,
            "Enable diagnostic logging for hit feedback.");
        ConfigEnabled = Config.Bind(
            "General",
            "Enabled",
            true,
            "Enable the mod.");

        LogSource.LogInfo(
            $"[GTFO_MOD_AGENT] feature_id={FEATURE_ID} signal=PLUGIN_LOADED target=Plugin.Load message=runtime_evidence=present");

        try
        {
            _harmony = new Harmony(GUID);
            _harmony.PatchAll();
            LogSource.LogInfo(
                $"[GTFO_MOD_AGENT] feature_id={FEATURE_ID} signal=PATCH_APPLIED target=Harmony.PatchAll message=Diagnostic hit feedback patches registered.");
        }
        catch (Exception ex)
        {
            LogSource.LogError(
                $"[GTFO_MOD_AGENT] feature_id={FEATURE_ID} signal=RUNTIME_FAILED target=Harmony.PatchAll message=Failed to apply patches: {ex.Message}");
        }
    }

    public override bool Unload()
    {
        _harmony?.UnpatchSelf();
        LogSource.LogInfo($"{MODNAME} unloaded.");
        return base.Unload();
    }
}"""
    return text.replace("\n", "\r\n").encode("utf-8")
