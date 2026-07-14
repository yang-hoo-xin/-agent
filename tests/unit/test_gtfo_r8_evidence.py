"""Focused tests for the bounded supplied GTFO R8 evidence reader."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.mod_agent.evidence.gtfo_r8 import (
    GTFOR8EvidenceProvider,
    R8EvidenceError,
    R8_EXPECTED_SHA256,
    _EXACT_SYMBOLS,
)


def _supplied_snapshot_fixture(root: Path) -> dict[str, str]:
    content_by_path = {relative_path: [] for relative_path in R8_EXPECTED_SHA256}
    for spec in _EXACT_SYMBOLS:
        content_by_path[spec.relative_path].append(spec.anchor)
    content_by_path["Datablocks/GameData_LevelLayoutDataBlock_bin.json"] = [
        json.dumps(
            {
                "Blocks": [
                    {
                        "ZoneAliasStart": 43,
                        "Zones": [{"LocalIndex": 0}],
                        "name": "R7_A1_Retrieve_L1_V2",
                        "internalEnabled": True,
                        "persistentID": 1508110819,
                    }
                ]
            }
        )
    ]
    content_by_path["Datablocks/GameData_RundownDataBlock_bin.json"] = [
        json.dumps({"Blocks": [{"TierA": [{"LevelLayoutData": 1508110819}]}]})
    ]
    expected: dict[str, str] = {}
    for relative_path, lines in content_by_path.items():
        path = root.joinpath(*relative_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = ("\n".join(lines) + "\n").encode("utf-8")
        path.write_bytes(raw)
        expected[relative_path] = hashlib.sha256(raw).hexdigest().upper()
    return expected


def test_r8_provider_reads_hashes_symbols_and_json_identity(tmp_path: Path) -> None:
    expected = _supplied_snapshot_fixture(tmp_path)

    pack = GTFOR8EvidenceProvider(
        tmp_path,
        expected_sha256=expected,
    ).collect(query="WallCrawler")

    assert pack.readiness == "partial"
    assert pack.can_generate_patch is False
    assert len(pack.items) == len(_EXACT_SYMBOLS) + 2
    assert {item.source_path for item in pack.items} == set(expected)
    assert all(item.file_hash == expected[item.source_path] for item in pack.items)
    assert {item.symbol for item in pack.items} >= {
        "ES_PathMove.CommonFixedUpdate",
        "ES_PathMove.UpdateRotation",
        "ES_PathMoveBase.UpdateRotation",
        "Blocks[0].persistentID",
        "$.Blocks[0].TierA[0].LevelLayoutData",
    }


def test_r8_provider_blocks_hash_drift(tmp_path: Path) -> None:
    expected = _supplied_snapshot_fixture(tmp_path)
    path = tmp_path / "Assets" / "Scripts" / "Modules-ASM" / "ES_PathMove.cs"
    path.write_text("changed\n", encoding="utf-8")

    with pytest.raises(R8EvidenceError, match="hash mismatch"):
        GTFOR8EvidenceProvider(tmp_path, expected_sha256=expected).collect(
            query="WallCrawler"
        )


def test_r8_provider_records_exact_stub_il_and_keeps_proposal_blocked(
    tmp_path: Path,
) -> None:
    expected = _supplied_snapshot_fixture(tmp_path)
    assembly = tmp_path / "Library" / "ScriptAssemblies" / "Modules-ASM.dll"
    report = {
        "schema_version": "r8_il_inspection_v1",
        "assembly_path": str(assembly),
        "assembly_sha256": "D" * 64,
        "module_name": "Modules-ASM.dll",
        "module_mvid": "28e7d845-eb8b-48af-a5b2-9b1addb278ae",
        "missing_symbols": [],
        "target_code_executed": False,
        "methods": [
            {
                "symbol": "ES_PathMove.CommonFixedUpdate",
                "metadata_token": "0x06000B8C",
                "attributes": "PrivateScope, Private, HideBySig",
                "impl_attributes": "IL",
                "signature_blob": "200001",
                "rva": 8282,
                "has_method_body": True,
                "il_bytes": "002A",
                "instructions": [
                    {"offset": "IL_0000", "opcode": "nop", "operand": None, "resolved": None},
                    {"offset": "IL_0001", "opcode": "ret", "operand": None, "resolved": None},
                ],
            },
            {
                "symbol": "ES_PathMove.UpdateRotation",
                "metadata_token": "0x06000B8E",
                "attributes": "PrivateScope, Family, Virtual, HideBySig",
                "impl_attributes": "IL",
                "signature_blob": "200001",
                "rva": 8282,
                "has_method_body": True,
                "il_bytes": "002A",
                "instructions": [
                    {"offset": "IL_0000", "opcode": "nop", "operand": None, "resolved": None},
                    {"offset": "IL_0001", "opcode": "ret", "operand": None, "resolved": None},
                ],
            },
            {
                "symbol": "ES_PathMoveBase.UpdateRotation",
                "metadata_token": "0x06000B93",
                "attributes": "PrivateScope, Family, Virtual, HideBySig, VtableLayoutMask, Abstract",
                "impl_attributes": "IL",
                "signature_blob": "200001",
                "rva": 0,
                "has_method_body": False,
                "il_bytes": "",
                "instructions": [],
            },
        ],
    }

    pack = GTFOR8EvidenceProvider(
        tmp_path,
        expected_sha256=expected,
    ).collect(query="WallCrawler", il_report=report)

    assert pack.readiness == "partial"
    assert pack.can_generate_patch is False
    assert "cli_metadata_il_read" in pack.retrieval_methods_used
    assert pack.blockers[0]["code"] == "R8_METHOD_BODY_STUB_ONLY"
    il_items = [item for item in pack.items if item.retrieval_method == "cli_metadata_il_read"]
    assert len(il_items) == 3
    assert {item.symbol for item in il_items} == {
        "ES_PathMove.CommonFixedUpdate",
        "ES_PathMove.UpdateRotation",
        "ES_PathMoveBase.UpdateRotation",
    }


def test_r8_provider_records_current_interop_and_reference_mod_il_without_unlocking(
    tmp_path: Path,
) -> None:
    expected = _supplied_snapshot_fixture(tmp_path)
    current_report = _minimal_bound_report(
        tmp_path / "BepInEx" / "interop" / "Modules-ASM.dll",
        "A" * 64,
        "ES_PathMove.CommonFixedUpdate",
        resolved="ES_PathMove.NativeMethodInfoPtr_CommonFixedUpdate_Private_Void_0",
    )
    reference_report = _minimal_bound_report(
        tmp_path / "BepInEx" / "plugins" / "EnemyAnimationFix.dll",
        "B" * 64,
        "EnemyAnimationFix.Patches.EnemyTargetPatches.PathfindingFix",
        resolved="Enemies.EB_InCombat.TryUpdateNavigation",
    )

    pack = GTFOR8EvidenceProvider(
        tmp_path,
        expected_sha256=expected,
    ).collect(
        query="WallCrawler",
        current_interop_report=current_report,
        reference_mod_reports={
            "plugins/Dinorush-EnemyAnimationFix/EnemyAnimationFix.dll": reference_report
        },
    )

    assert pack.readiness == "partial"
    assert pack.can_generate_patch is False
    assert pack.blockers[0]["code"] == "CURRENT_INTEROP_NATIVE_BODY_UNRESOLVED"
    assert pack.blockers[2]["code"] == "CURRENT_RUNTIME_EXECUTION_UNOBSERVED"
    assert "current_interop_metadata_il_read" in pack.retrieval_methods_used
    assert "reference_mod_metadata_il_read" in pack.retrieval_methods_used
    current_item = next(
        item
        for item in pack.items
        if item.retrieval_method == "current_interop_metadata_il_read"
    )
    reference_item = next(
        item
        for item in pack.items
        if item.retrieval_method == "reference_mod_metadata_il_read"
    )
    assert current_item.source_type == "decompiled_api"
    assert current_item.usage == "hook_target"
    assert reference_item.source_type == "reference_mod"
    assert reference_item.usage == "supporting_context"
    assert "TryUpdateNavigation" in reference_item.excerpt


def _minimal_bound_report(
    path: Path,
    assembly_hash: str,
    symbol: str,
    *,
    resolved: str,
) -> dict[str, object]:
    return {
        "schema_version": "r8_il_inspection_v1",
        "assembly_path": str(path),
        "assembly_sha256": assembly_hash,
        "module_name": path.name,
        "module_mvid": "00000000-0000-0000-0000-000000000000",
        "missing_symbols": [],
        "target_code_executed": False,
        "methods": [
            {
                "symbol": symbol,
                "metadata_token": "0x06000001",
                "attributes": "Public",
                "impl_attributes": "IL",
                "signature_blob": "200001",
                "rva": 1,
                "has_method_body": True,
                "il_bytes": "2A",
                "instructions": [
                    {
                        "offset": "IL_0000",
                        "opcode": "call",
                        "operand": "0x0A000001",
                        "resolved": resolved,
                    }
                ],
                "custom_attributes": [],
                "declaring_type_custom_attributes": [],
            }
        ],
    }
