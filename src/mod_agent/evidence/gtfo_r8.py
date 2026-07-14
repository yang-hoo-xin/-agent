"""Read the explicitly supplied GTFO R8 snapshot into a bounded evidence pack."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EvidenceItem,
    EvidencePack,
    missing_evidence_from_blockers,
)


R8_EXPECTED_SHA256: dict[str, str] = {
    "Assets/Scripts/Modules-ASM/ES_PathMove.cs": "092CDB08DAC61D0847D173AA189D5C114E96460FFEBFC57D66C02231443ACBD5",
    "Assets/Scripts/Modules-ASM/ES_PathMoveBase.cs": "CBC5BE7E277DD49065CCC613C5184D7F0F777A2F5C1881E70FB5BF6A12AECC17",
    "Assets/Scripts/Modules-ASM/Enemies/EnemyAgent.cs": "DF0434B497E6293378708E3640521F6B01BE03FE8470A0C37E3E557F1D6B62D3",
    "Assets/Scripts/Modules-ASM/Enemies/EnemyLocomotion.cs": "55A5A8BFAA85CE7E91AB7187A5615469C97DBD4E67266333971E14B3540DDEC4",
    "Assets/Scripts/Modules-ASM/AIGraph/AIG_CourseNode.cs": "0CE67E4ECEA125044648F7AA969564CEAF3136D95E7397607BA1804C1EBC44C8",
    "Assets/Scripts/Modules-ASM/LevelGeneration/LG_Zone.cs": "0798F031D42FA9235F098761C044E6BDCF0E6C0D98D12A03FF8D28328BE57291",
    "Assets/Scripts/Modules-ASM/GameData/LevelLayoutDataBlock.cs": "2A236C4F1FD8A32BB23864F1140DE78ECD35D053159E69DED7754CF5BB7E8E8A",
    "Assets/Scripts/Modules-ASM/GameData/ExpeditionZoneData.cs": "2F5141477B448841B7D4592FFDA691EFAF07CE96E5E386AF1759CD778CC160D1",
    "Assets/Scripts/Modules-ASM/GameData/ExpeditionInTierData.cs": "36DBB3E4B73ABBC9548CF9C3F0A089C9484DFECC69C99E0A4D52BED30A02D81F",
    "Datablocks/GameData_LevelLayoutDataBlock_bin.json": "1B70C20F55F7205AE32FCA65ED805A70173F5C3126EC25EDA27E4CEBF24C79E7",
    "Datablocks/GameData_RundownDataBlock_bin.json": "5EBFE2CB25D0ADCECB5C622C781F0C142B55B2C16807EF5F0E1406C069B9667D",
}


class R8EvidenceError(ValueError):
    """Raised when the supplied snapshot does not match the verified evidence set."""


@dataclass(frozen=True)
class _ExactSymbol:
    relative_path: str
    symbol: str
    anchor: str
    claim: str
    usage: str = "supporting_context"
    declaring_type: str | None = None
    method_name: str | None = None
    parameter_types: tuple[str, ...] | None = None
    return_type: str | None = None
    method_kind: str | None = None
    risk_notes: tuple[str, ...] = ()


_EXACT_SYMBOLS = (
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/ES_PathMove.cs",
        "ES_PathMove.CommonFixedUpdate",
        "private void CommonFixedUpdate()",
        "The supplied R8 source declares ES_PathMove.CommonFixedUpdate with no parameters.",
        usage="hook_target",
        declaring_type="ES_PathMove",
        method_name="CommonFixedUpdate",
        parameter_types=(),
        return_type="System.Void",
        method_kind="instance_method",
        risk_notes=("The supplied source shows an empty method body; runtime behavior is unresolved.",),
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/ES_PathMove.cs",
        "ES_PathMove.UpdateRotation",
        "protected override void UpdateRotation()",
        "The supplied R8 source declares ES_PathMove.UpdateRotation with no parameters.",
        usage="hook_target",
        declaring_type="ES_PathMove",
        method_name="UpdateRotation",
        parameter_types=(),
        return_type="System.Void",
        method_kind="instance_method",
        risk_notes=("The supplied source shows an empty method body; rotation semantics are unresolved.",),
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/ES_PathMoveBase.cs",
        "ES_PathMoveBase.UpdateRotation",
        "protected abstract void UpdateRotation();",
        "The supplied R8 source declares ES_PathMoveBase.UpdateRotation as an abstract method.",
        usage="hook_target",
        declaring_type="ES_PathMoveBase",
        method_name="UpdateRotation",
        parameter_types=(),
        return_type="System.Void",
        method_kind="instance_method",
        risk_notes=("The abstract declaration does not prove concrete runtime rotation behavior.",),
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/Enemies/EnemyAgent.cs",
        "EnemyAgent.Locomotion",
        "public EnemyLocomotion Locomotion;",
        "EnemyAgent exposes an EnemyLocomotion field in the supplied R8 source.",
        declaring_type="EnemyAgent",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/Enemies/EnemyAgent.cs",
        "EnemyAgent.EnemyDataID",
        "public uint EnemyDataID;",
        "EnemyAgent exposes the exact EnemyDataID field in the supplied R8 source.",
        declaring_type="EnemyAgent",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/Enemies/EnemyAgent.cs",
        "EnemyAgent.CourseNode",
        "public override AIG_CourseNode CourseNode",
        "EnemyAgent exposes an AIG_CourseNode CourseNode property in the supplied R8 source.",
        declaring_type="EnemyAgent",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/Enemies/EnemyLocomotion.cs",
        "EnemyLocomotion.PathMove",
        "public ES_PathMoveBase PathMove;",
        "EnemyLocomotion exposes an ES_PathMoveBase PathMove field in the supplied R8 source.",
        declaring_type="EnemyLocomotion",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/AIGraph/AIG_CourseNode.cs",
        "AIG_CourseNode.m_zone",
        "public LG_Zone m_zone;",
        "AIG_CourseNode exposes an LG_Zone m_zone field in the supplied R8 source.",
        declaring_type="AIG_CourseNode",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/LevelGeneration/LG_Zone.cs",
        "LG_Zone.LocalIndex",
        "public eLocalZoneIndex LocalIndex",
        "LG_Zone exposes the exact LocalIndex property in the supplied R8 source.",
        declaring_type="LG_Zone",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/GameData/LevelLayoutDataBlock.cs",
        "LevelLayoutDataBlock.ZoneAliasStart",
        "public int ZoneAliasStart { get; set; }",
        "LevelLayoutDataBlock declares the exact ZoneAliasStart property.",
        declaring_type="GameData.LevelLayoutDataBlock",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/GameData/LevelLayoutDataBlock.cs",
        "LevelLayoutDataBlock.Zones",
        "public List<ExpeditionZoneData> Zones { get; set; }",
        "LevelLayoutDataBlock declares the exact Zones property.",
        declaring_type="GameData.LevelLayoutDataBlock",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/GameData/ExpeditionZoneData.cs",
        "ExpeditionZoneData.LocalIndex",
        "public eLocalZoneIndex LocalIndex { get; set; }",
        "ExpeditionZoneData declares the exact LocalIndex property.",
        declaring_type="GameData.ExpeditionZoneData",
    ),
    _ExactSymbol(
        "Assets/Scripts/Modules-ASM/GameData/ExpeditionInTierData.cs",
        "ExpeditionInTierData.LevelLayoutData",
        "public uint LevelLayoutData { get; set; }",
        "ExpeditionInTierData declares the exact LevelLayoutData property.",
        declaring_type="GameData.ExpeditionInTierData",
    ),
)


class GTFOR8EvidenceProvider:
    """Collect only the pre-verified R8 files and exact symbols for WallCrawler."""

    def __init__(
        self,
        evidence_root: str | Path,
        *,
        expected_sha256: Mapping[str, str] = R8_EXPECTED_SHA256,
    ) -> None:
        self.evidence_root = Path(evidence_root).resolve()
        self.expected_sha256 = dict(expected_sha256)

    def collect(
        self,
        *,
        query: str,
        il_report: dict[str, Any] | None = None,
        current_interop_report: dict[str, Any] | None = None,
        reference_mod_reports: Mapping[str, dict[str, Any]] | None = None,
    ) -> EvidencePack:
        started = time.perf_counter()
        if not self.evidence_root.is_dir():
            raise R8EvidenceError(f"R8 evidence root does not exist: {self.evidence_root}")

        file_data: dict[str, tuple[Path, bytes, str]] = {}
        for relative_path, expected_hash in self.expected_sha256.items():
            path = self.evidence_root.joinpath(*relative_path.split("/"))
            if not path.is_file():
                raise R8EvidenceError(f"Required R8 evidence file is missing: {relative_path}")
            raw = path.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest().upper()
            if actual_hash != expected_hash.upper():
                raise R8EvidenceError(
                    f"R8 evidence hash mismatch for {relative_path}: {actual_hash}"
                )
            file_data[relative_path] = (path, raw, actual_hash)

        items = [self._symbol_item(spec, file_data) for spec in _EXACT_SYMBOLS]
        items.extend(self._json_identity_items(file_data))
        if il_report is None:
            method_blocker = {
                "code": "R8_METHOD_BEHAVIOR_UNRESOLVED",
                "message": "The supplied ES_PathMove method bodies are empty and do not prove interception behavior.",
                "needed_evidence": ["trustworthy method body or IL for ES_PathMove.CommonFixedUpdate and ES_PathMove.UpdateRotation"],
            }
            method_gap = "Method behavior is absent from the supplied C# bodies."
            il_methods: tuple[str, ...] = ()
        else:
            il_items, stub_only = self._il_items(il_report)
            items.extend(il_items)
            if stub_only:
                method_blocker = {
                    "code": "R8_METHOD_BODY_STUB_ONLY",
                    "message": "The hash-bound R8 assembly contains only nop/ret bodies for the two concrete methods and no body for the abstract method.",
                    "needed_evidence": ["a non-stub current assembly or native IL2CPP method evidence for the exact movement and rotation path"],
                }
                method_gap = "The supplied R8 assembly is a metadata/stub assembly for the inspected methods."
            else:
                method_blocker = {
                    "code": "R8_METHOD_SEMANTICS_NOT_YET_BOUND",
                    "message": "IL exists, but this bounded inspection does not establish surface movement semantics.",
                    "needed_evidence": ["exact IL call and field evidence connecting the inspected methods to surface movement"],
                }
                method_gap = "Inspected IL does not yet prove wall, slope, or ceiling movement semantics."
            il_methods = ("cli_metadata_il_read",)
        if current_interop_report is not None:
            items.extend(
                self._bound_report_items(
                    current_interop_report,
                    source_type="decompiled_api",
                    source_path="interop/Modules-ASM.dll",
                    retrieval_method="current_interop_metadata_il_read",
                    hook_targets={
                        "ES_PathMove.CommonFixedUpdate",
                        "ES_PathMove.UpdateRotation",
                        "ES_PathMoveBase.UpdateRotation",
                    },
                )
            )
            method_blocker = {
                "code": "CURRENT_INTEROP_NATIVE_BODY_UNRESOLVED",
                "message": "The current generated interop assembly exposes exact managed wrappers and native method pointers, but not the native movement implementation.",
                "needed_evidence": ["native method evidence or current source that establishes the movement and rotation semantics behind the exact wrappers"],
            }
            method_gap = "Current interop wrappers prove target identity and callable access, not native movement semantics."
            il_methods = (*il_methods, "current_interop_metadata_il_read")
        reference_mod_reports = reference_mod_reports or {}
        for source_path, report in reference_mod_reports.items():
            items.extend(
                self._bound_report_items(
                    report,
                    source_type="reference_mod",
                    source_path=source_path,
                    retrieval_method="reference_mod_metadata_il_read",
                    hook_targets=set(),
                )
            )
        if reference_mod_reports:
            il_methods = (*il_methods, "reference_mod_metadata_il_read")
        blockers = (
            method_blocker,
            {
                "code": "SURFACE_MOVEMENT_API_UNRESOLVED",
                "message": "No supplied source proves wall, slope, ceiling, surface-normal, or navigation behavior.",
                "needed_evidence": ["current source or API evidence for surface detection, orientation, and non-horizontal navigation"],
            },
            (
                {
                    "code": "CURRENT_RUNTIME_EXECUTION_UNOBSERVED",
                    "message": "The current installed interop bytes are hash-bound, but no game process or gameplay behavior was observed.",
                    "needed_evidence": ["separately approved runtime evidence for the selected exact Hook and acceptance behavior"],
                }
                if current_interop_report is not None
                else {
                    "code": "CURRENT_RUNTIME_BINDING_UNVERIFIED",
                    "message": "The supplied R8 snapshot is not bound to a currently running GTFO build.",
                    "needed_evidence": ["current game build identity and matching current API or symbol evidence"],
                }
            ),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return EvidencePack(
            query=query,
            readiness="partial",
            can_generate_patch=False,
            items=tuple(items),
            gaps=(
                method_gap,
                "Surface detection and non-horizontal navigation APIs remain unresolved.",
                "No traceable community map configuration was included in this evidence root.",
                *(
                    (
                        "The inspected reference Mods demonstrate Harmony interception, position mutation, and ordinary INavigation recovery only; they do not demonstrate wall or ceiling traversal.",
                    )
                    if reference_mod_reports
                    else ()
                ),
            ),
            blockers=blockers,
            retrieval_methods_used=(
                "exact_supplied_file_read",
                "sha256",
                "exact_json_identity_binding",
                *il_methods,
            ),
            missing_evidence=missing_evidence_from_blockers(blockers),
            disabled_modes={
                "bm25": "Not required for the exact supplied-file slice.",
                "dense": "Not required for the exact supplied-file slice.",
                "fusion": "Not required for the exact supplied-file slice.",
                "rerank": "Not required for the exact supplied-file slice.",
            },
            timing={
                "query_processing_ms": 0.0,
                "symbol_ms": elapsed_ms,
                "text_ms": 0.0,
                "bm25_ms": 0.0,
                "dense_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "readiness_ms": 0.0,
                "total_ms": elapsed_ms,
                "final_count": float(len(items)),
                "excluded_count": 0.0,
            },
            trace_refs=(
                *tuple(f"sha256:{file_data[path][2]}" for path in self.expected_sha256),
                *(
                    (f"sha256:{il_report['assembly_sha256']}",)
                    if il_report is not None
                    else ()
                ),
                *(
                    (f"sha256:{current_interop_report['assembly_sha256']}",)
                    if current_interop_report is not None
                    else ()
                ),
                *tuple(
                    f"sha256:{report['assembly_sha256']}"
                    for report in reference_mod_reports.values()
                ),
            ),
            message=(
                "The approved GTFO R8 snapshot was read and hash-verified. "
                + (
                    "Exact CLI metadata/IL was also recorded. "
                    if il_report is not None
                    else ""
                )
                + (
                    "Current interop wrapper IL was hash-bound. "
                    if current_interop_report is not None
                    else ""
                )
                + (
                    "Reference Mod patch IL was hash-bound. "
                    if reference_mod_reports
                    else ""
                )
                + "Exact symbols and one PersistentID linkage were recorded; implementation remains blocked."
            ),
        )

    def _bound_report_items(
        self,
        report: dict[str, Any],
        *,
        source_type: str,
        source_path: str,
        retrieval_method: str,
        hook_targets: set[str],
    ) -> list[EvidenceItem]:
        assembly_path = Path(str(report["assembly_path"])).resolve()
        assembly_hash = str(report["assembly_sha256"])
        module_mvid = str(report["module_mvid"])
        items: list[EvidenceItem] = []
        for method in report["methods"]:
            symbol = str(method["symbol"])
            declaring_type, method_name = symbol.rsplit(".", 1)
            instructions = method.get("instructions") or []
            resolved_refs = sorted(
                {
                    str(instruction["resolved"])
                    for instruction in instructions
                    if instruction.get("resolved")
                }
            )
            excerpt = {
                "module_mvid": module_mvid,
                "metadata_token": method["metadata_token"],
                "attributes": method["attributes"],
                "impl_attributes": method["impl_attributes"],
                "signature_blob": method["signature_blob"],
                "rva": method.get("rva", 0),
                "has_method_body": method.get("has_method_body") is True,
                "il_bytes": method.get("il_bytes") or "",
                "resolved_refs": resolved_refs,
                "custom_attributes": method.get("custom_attributes") or [],
                "declaring_type_custom_attributes": method.get(
                    "declaring_type_custom_attributes"
                )
                or [],
            }
            items.append(
                EvidenceItem(
                    evidence_id="bound_il_"
                    + hashlib.sha256(
                        f"{assembly_hash}:{symbol}:{method['metadata_token']}".encode(
                            "utf-8"
                        )
                    ).hexdigest()[:20],
                    source_type=source_type,
                    source_path=source_path,
                    symbol=symbol,
                    span=None,
                    retrieval_method=retrieval_method,
                    score=1.0,
                    claim_supported=(
                        f"Hash-bound CLI metadata records token {method['metadata_token']}, "
                        f"RVA {method.get('rva', 0)}, exact custom attributes, and exact resolved IL references."
                    ),
                    excerpt=json.dumps(
                        excerpt,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    source_ref=str(assembly_path),
                    source_hash=assembly_hash,
                    file_hash=assembly_hash,
                    usage="hook_target" if symbol in hook_targets else "supporting_context",
                    declaring_type=declaring_type,
                    method_name=method_name,
                    authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
                    risk_notes=(
                        "CLI metadata inspection did not load or execute the target assembly.",
                    ),
                )
            )
        return items

    def _il_items(
        self,
        report: dict[str, Any],
    ) -> tuple[list[EvidenceItem], bool]:
        assembly_path = Path(str(report["assembly_path"])).resolve()
        assembly_hash = str(report["assembly_sha256"])
        module_mvid = str(report["module_mvid"])
        items: list[EvidenceItem] = []
        method_shapes: dict[str, tuple[bool, list[str], str, int]] = {}
        for method in report["methods"]:
            symbol = str(method["symbol"])
            instructions = method.get("instructions") or []
            opcodes = [str(instruction.get("opcode")) for instruction in instructions]
            has_body = method.get("has_method_body") is True
            il_bytes = str(method.get("il_bytes") or "")
            rva = int(method.get("rva") or 0)
            method_shapes[symbol] = (has_body, opcodes, il_bytes, rva)
            declaring_type, method_name = symbol.rsplit(".", 1)
            items.append(
                EvidenceItem(
                    evidence_id="r8_il_" + hashlib.sha256(
                        f"{assembly_hash}:{symbol}:{method['metadata_token']}".encode("utf-8")
                    ).hexdigest()[:20],
                    source_type="decompiled_api",
                    source_path="Library/ScriptAssemblies/Modules-ASM.dll",
                    symbol=symbol,
                    span=None,
                    retrieval_method="cli_metadata_il_read",
                    score=1.0,
                    claim_supported=(
                        f"Hash-bound CLI metadata records token {method['metadata_token']}, "
                        f"RVA {rva}, IL bytes {il_bytes or '<none>'}, and opcodes {opcodes}."
                    ),
                    excerpt=json.dumps(
                        {
                            "module_mvid": module_mvid,
                            "metadata_token": method["metadata_token"],
                            "attributes": method["attributes"],
                            "impl_attributes": method["impl_attributes"],
                            "signature_blob": method["signature_blob"],
                            "rva": rva,
                            "has_method_body": has_body,
                            "il_bytes": il_bytes,
                            "instructions": instructions,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    source_ref=str(assembly_path),
                    source_hash=assembly_hash,
                    file_hash=assembly_hash,
                    usage="hook_target",
                    declaring_type=declaring_type,
                    method_name=method_name,
                    parameter_types=(),
                    return_type="System.Void",
                    method_kind="instance_method",
                    authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
                    risk_notes=(
                        "CLI metadata inspection did not load or execute the target assembly.",
                    ),
                )
            )
        stub_only = (
            method_shapes.get("ES_PathMove.CommonFixedUpdate") == (True, ["nop", "ret"], "002A", 8282)
            and method_shapes.get("ES_PathMove.UpdateRotation") == (True, ["nop", "ret"], "002A", 8282)
            and method_shapes.get("ES_PathMoveBase.UpdateRotation") == (False, [], "", 0)
        )
        return items, stub_only

    def _symbol_item(
        self,
        spec: _ExactSymbol,
        file_data: dict[str, tuple[Path, bytes, str]],
    ) -> EvidenceItem:
        path, raw, file_hash = file_data[spec.relative_path]
        lines = raw.decode("utf-8-sig").splitlines()
        matches = [index for index, line in enumerate(lines) if line.strip() == spec.anchor]
        if len(matches) != 1:
            raise R8EvidenceError(
                f"Expected exactly one exact symbol anchor in {spec.relative_path}: {spec.anchor}"
            )
        anchor_index = matches[0]
        start_index = max(0, anchor_index - 2)
        end_index = min(len(lines), anchor_index + 4)
        identity = f"{spec.relative_path}:{spec.symbol}:{file_hash}"
        return EvidenceItem(
            evidence_id="r8_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20],
            source_type="decompiled_api",
            source_path=spec.relative_path,
            symbol=spec.symbol,
            span={"start_line": start_index + 1, "end_line": end_index},
            retrieval_method="exact_supplied_file_read",
            score=1.0,
            claim_supported=spec.claim,
            excerpt="\n".join(lines[start_index:end_index]),
            source_ref=str(path),
            source_hash=file_hash,
            file_hash=file_hash,
            usage=spec.usage,
            declaring_type=spec.declaring_type,
            method_name=spec.method_name,
            parameter_types=spec.parameter_types,
            return_type=spec.return_type,
            method_kind=spec.method_kind,
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            risk_notes=spec.risk_notes,
        )

    def _json_identity_items(
        self,
        file_data: dict[str, tuple[Path, bytes, str]],
    ) -> list[EvidenceItem]:
        layout_relative = "Datablocks/GameData_LevelLayoutDataBlock_bin.json"
        rundown_relative = "Datablocks/GameData_RundownDataBlock_bin.json"
        layout_path, layout_raw, layout_hash = file_data[layout_relative]
        rundown_path, rundown_raw, rundown_hash = file_data[rundown_relative]
        layout = json.loads(layout_raw.decode("utf-8-sig"))
        rundown = json.loads(rundown_raw.decode("utf-8-sig"))
        layout_blocks = layout.get("Blocks")
        if not isinstance(layout_blocks, list):
            raise R8EvidenceError("Level layout JSON does not contain an exact Blocks list.")
        matching_indexes = [
            index
            for index, block in enumerate(layout_blocks)
            if isinstance(block, dict) and block.get("persistentID") == 1508110819
        ]
        if len(matching_indexes) != 1:
            raise R8EvidenceError("Expected one level layout block with persistentID 1508110819.")
        layout_index = matching_indexes[0]
        layout_block = layout_blocks[layout_index]
        if "ZoneAliasStart" not in layout_block or not isinstance(layout_block.get("Zones"), list):
            raise R8EvidenceError("The bound layout block lacks exact ZoneAliasStart or Zones fields.")
        rundown_paths = _find_exact_key_value_paths(rundown, "LevelLayoutData", 1508110819)
        if not rundown_paths:
            raise R8EvidenceError("Rundown JSON does not reference LevelLayoutData 1508110819.")

        layout_symbol = f"Blocks[{layout_index}].persistentID"
        rundown_symbol = rundown_paths[0]
        zone_local_indexes = [
            zone.get("LocalIndex")
            for zone in layout_block["Zones"]
            if isinstance(zone, dict) and "LocalIndex" in zone
        ]
        return [
            EvidenceItem(
                evidence_id="r8_json_layout_1508110819",
                source_type="domain_note",
                source_path=layout_relative,
                symbol=layout_symbol,
                span=None,
                retrieval_method="exact_json_identity_binding",
                score=1.0,
                claim_supported=(
                    "The supplied layout JSON contains persistentID 1508110819 with exact ZoneAliasStart and Zones fields."
                ),
                excerpt=json.dumps(
                    {
                        "ZoneAliasStart": layout_block["ZoneAliasStart"],
                        "Zones": [
                            {"LocalIndex": local_index}
                            for local_index in zone_local_indexes
                        ],
                        "name": layout_block.get("name"),
                        "internalEnabled": layout_block.get("internalEnabled"),
                        "persistentID": layout_block["persistentID"],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                source_ref=str(layout_path),
                source_hash=layout_hash,
                file_hash=layout_hash,
                usage="supporting_context",
                authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            ),
            EvidenceItem(
                evidence_id="r8_json_rundown_layout_1508110819",
                source_type="domain_note",
                source_path=rundown_relative,
                symbol=rundown_symbol,
                span=None,
                retrieval_method="exact_json_identity_binding",
                score=1.0,
                claim_supported=(
                    "The supplied rundown JSON references LevelLayoutData 1508110819."
                ),
                excerpt=json.dumps({"LevelLayoutData": 1508110819}, separators=(",", ":")),
                source_ref=str(rundown_path),
                source_hash=rundown_hash,
                file_hash=rundown_hash,
                usage="supporting_context",
                authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            ),
        ]


def _find_exact_key_value_paths(value: object, key: str, expected: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            item_path = f"{path}.{item_key}"
            if item_key == key and item_value == expected:
                found.append(item_path)
            found.extend(_find_exact_key_value_paths(item_value, key, expected, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_exact_key_value_paths(item, key, expected, f"{path}[{index}]"))
    return found
