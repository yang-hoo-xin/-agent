"""Read-only local tools for bounded intelligent assembly evidence discovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .discovery_contract import EvidenceDiscoverySource, ToolObservation
from .models import DETERMINISTIC_EVIDENCE_AUTHORITY, EvidenceItem
from .r8_il import BoundILInspectionRunner, MetadataSearchRunner, R8ILInspectionError


class MetadataRunner(Protocol):
    def search(
        self,
        assembly_path: str | Path,
        *,
        queries: tuple[str, ...],
    ) -> dict[str, Any]:
        ...


class ExactILRunnerFactory(Protocol):
    def __call__(self, symbols: tuple[str, ...]) -> BoundILInspectionRunner:
        ...


@dataclass(frozen=True)
class _ObservedMethod:
    source_id: str
    assembly_path: Path
    relative_path: str
    assembly_sha256: str
    module_mvid: str
    symbol: str
    metadata_token: str


class LocalAssemblyEvidenceToolExecutor:
    """Search authorized roots and inspect only run-observed exact method identities."""

    def __init__(
        self,
        *,
        metadata_runner: MetadataRunner,
        il_runner_factory: ExactILRunnerFactory,
        max_assemblies_per_search: int = 256,
        max_results_per_search: int = 50,
        max_model_instructions: int = 160,
        max_model_observation_bytes: int = 16_384,
    ) -> None:
        if min(
            max_assemblies_per_search,
            max_results_per_search,
            max_model_instructions,
            max_model_observation_bytes,
        ) <= 0:
            raise ValueError("Assembly evidence tool budgets must be positive.")
        self.metadata_runner = metadata_runner
        self.il_runner_factory = il_runner_factory
        self.max_assemblies_per_search = max_assemblies_per_search
        self.max_results_per_search = max_results_per_search
        self.max_model_instructions = max_model_instructions
        self.max_model_observation_bytes = max_model_observation_bytes
        self._observed_methods: dict[str, _ObservedMethod] = {}

    @classmethod
    def from_inspector(
        cls,
        inspector_dll: str | Path,
        *,
        dotnet_executable: str = "dotnet",
        max_assemblies_per_search: int = 256,
        max_results_per_search: int = 50,
        max_model_instructions: int = 160,
        max_model_observation_bytes: int = 16_384,
    ) -> "LocalAssemblyEvidenceToolExecutor":
        inspector = Path(inspector_dll).resolve()
        return cls(
            metadata_runner=MetadataSearchRunner(
                inspector,
                dotnet_executable=dotnet_executable,
            ),
            il_runner_factory=lambda symbols: BoundILInspectionRunner(
                inspector,
                symbols=symbols,
                dotnet_executable=dotnet_executable,
            ),
            max_assemblies_per_search=max_assemblies_per_search,
            max_results_per_search=max_results_per_search,
            max_model_instructions=max_model_instructions,
            max_model_observation_bytes=max_model_observation_bytes,
        )

    def execute(
        self,
        *,
        action: dict[str, object],
        source: EvidenceDiscoverySource,
        observation_id: str,
    ) -> ToolObservation:
        tool = str(action.get("tool") or "")
        if tool == "search_dotnet_metadata":
            arguments = action["arguments"]
            assert isinstance(arguments, dict)
            return self._search(
                source=source,
                observation_id=observation_id,
                queries=tuple(str(item) for item in arguments["queries"]),
                result_kinds=tuple(str(item) for item in arguments["result_kinds"]),
                limit_per_kind=int(arguments["limit_per_kind"]),
            )
        if tool == "inspect_method_il":
            arguments = action["arguments"]
            assert isinstance(arguments, dict)
            return self._inspect(
                source=source,
                observation_id=observation_id,
                method_id=str(arguments["method_id"]),
            )
        raise ValueError("UNKNOWN_EVIDENCE_TOOL")

    def _search(
        self,
        *,
        source: EvidenceDiscoverySource,
        observation_id: str,
        queries: tuple[str, ...],
        result_kinds: tuple[str, ...],
        limit_per_kind: int,
    ) -> ToolObservation:
        if not result_kinds or any(
            item not in {"methods", "types", "fields"} for item in result_kinds
        ):
            raise ValueError("METADATA_SEARCH_RESULT_KINDS_INVALID")
        if limit_per_kind <= 0 or limit_per_kind > self.max_results_per_search:
            raise ValueError("METADATA_SEARCH_LIMIT_INVALID")
        root = Path(source.root_path)
        if source.assembly_relative_paths:
            assemblies = [
                (root / relative_path).resolve()
                for relative_path in source.assembly_relative_paths
            ]
        else:
            assemblies = sorted(
                (path.resolve() for path in root.rglob("*.dll") if path.is_file()),
                key=lambda path: path.relative_to(root).as_posix(),
            )
        if len(assemblies) > self.max_assemblies_per_search:
            raise ValueError("ASSEMBLY_SEARCH_SOURCE_EXCEEDS_BUDGET")
        expected_identity = dict(source.version_identity or {})
        if (
            any(
                field in expected_identity
                for field in ("assembly_sha256", "module_mvid")
            )
            and len(assemblies) != 1
        ):
            raise ValueError("SOURCE_VERSION_IDENTITY_REQUIRES_ONE_ASSEMBLY")
        methods: list[dict[str, object]] = []
        types: list[dict[str, object]] = []
        fields: list[dict[str, object]] = []
        assembly_views: list[dict[str, object]] = []
        matched_counts = {"methods": 0, "types": 0, "fields": 0}
        truncated_by_kind = {"methods": False, "types": False, "fields": False}
        unreadable_count = 0
        searched_count = 0
        truncated = False
        for assembly in assemblies:
            _require_inside(assembly, root)
            try:
                report = self.metadata_runner.search(assembly, queries=queries)
            except R8ILInspectionError:
                unreadable_count += 1
                continue
            searched_count += 1
            relative_path = assembly.relative_to(root).as_posix()
            assembly_hash = str(report["assembly_sha256"])
            module_mvid = str(report["module_mvid"])
            if (
                expected_identity.get("assembly_sha256", assembly_hash)
                != assembly_hash
                or expected_identity.get("module_mvid", module_mvid) != module_mvid
            ):
                raise ValueError("SOURCE_VERSION_IDENTITY_MISMATCH")
            assembly_id = _stable_id(
                "assembly",
                source.source_id,
                relative_path,
                assembly_hash,
                module_mvid,
            )
            assembly_views.append(
                {
                    "assembly_id": assembly_id,
                    "relative_path": relative_path,
                    "assembly_sha256": assembly_hash,
                    "module_mvid": module_mvid,
                }
            )
            raw_methods = report["methods"]
            raw_types = report["types"]
            raw_fields = report["fields"]
            if not all(isinstance(rows, list) for rows in (raw_methods, raw_types, raw_fields)):
                raise ValueError("METADATA_RESULT_ROWS_INVALID")
            matched_counts["methods"] += len(raw_methods)
            matched_counts["types"] += len(raw_types)
            matched_counts["fields"] += len(raw_fields)
            if "methods" in result_kinds:
                for raw in raw_methods:
                    if len(methods) >= limit_per_kind:
                        truncated = True
                        truncated_by_kind["methods"] = True
                        break
                    if not isinstance(raw, dict):
                        raise ValueError("METADATA_METHOD_RESULT_INVALID")
                    symbol = str(raw["symbol"])
                    metadata_token = str(raw["metadata_token"])
                    method_id = _stable_id(
                        "method", assembly_id, metadata_token, symbol
                    )
                    observed = _ObservedMethod(
                        source_id=source.source_id,
                        assembly_path=assembly,
                        relative_path=relative_path,
                        assembly_sha256=assembly_hash,
                        module_mvid=module_mvid,
                        symbol=symbol,
                        metadata_token=metadata_token,
                    )
                    self._observed_methods[method_id] = observed
                    methods.append(
                        {
                            "method_id": method_id,
                            "assembly_id": assembly_id,
                            "symbol": symbol,
                            "metadata_token": metadata_token,
                            "has_method_body": raw.get("has_method_body") is True,
                        }
                    )
            if "types" in result_kinds:
                remaining = limit_per_kind - len(types)
                types.extend(
                    _public_metadata_rows(
                        raw_types,
                        assembly_id=assembly_id,
                        limit=remaining,
                    )
                )
                if len(raw_types) > max(remaining, 0):
                    truncated = True
                    truncated_by_kind["types"] = True
            if "fields" in result_kinds:
                remaining = limit_per_kind - len(fields)
                fields.extend(
                    _public_metadata_rows(
                        raw_fields,
                        assembly_id=assembly_id,
                        limit=remaining,
                    )
                )
                if len(raw_fields) > max(remaining, 0):
                    truncated = True
                    truncated_by_kind["fields"] = True
            if all(
                kind not in result_kinds
                or len({"methods": methods, "types": types, "fields": fields}[kind])
                >= limit_per_kind
                for kind in ("methods", "types", "fields")
            ):
                if assembly != assemblies[-1]:
                    truncated = True
                break
        data: dict[str, object] = {
            "queries": list(queries),
            "requested_result_kinds": list(result_kinds),
            "limit_per_kind": limit_per_kind,
            "assemblies_discovered": len(assemblies),
            "managed_assemblies_searched": searched_count,
            "unreadable_or_non_managed_assemblies": unreadable_count,
            "assemblies": assembly_views,
            "matched_counts": matched_counts,
            "returned_counts": {
                "methods": len(methods),
                "types": len(types),
                "fields": len(fields),
            },
            "truncated_by_kind": truncated_by_kind,
            "results_truncated": truncated,
            "methods": methods,
            "types": types,
            "fields": fields,
            "target_code_executed": False,
        }
        observation = ToolObservation(
            observation_id=observation_id,
            tool="search_dotnet_metadata",
            source_id=source.source_id,
            summary=(
                f"Searched {searched_count} managed assemblies and observed "
                f"{len(methods)} exact methods."
            ),
            data=data,
        )
        while _model_view_size(observation) > self.max_model_observation_bytes:
            removable = None
            for field_name in ("fields", "types", "methods", "assemblies"):
                rows = data[field_name]
                assert isinstance(rows, list)
                if rows:
                    removable = rows
                    break
            if removable is None:
                raise ValueError("SEARCH_OBSERVATION_BASE_EXCEEDS_TOOL_BUDGET")
            removable.pop()
            data["results_truncated"] = True
            if field_name in truncated_by_kind:
                truncated_by_kind[field_name] = True
        returned_counts = data["returned_counts"]
        assert isinstance(returned_counts, dict)
        returned_counts.update(
            {
                "methods": len(data["methods"]),
                "types": len(data["types"]),
                "fields": len(data["fields"]),
            }
        )
        visible_methods = data["methods"]
        assert isinstance(visible_methods, list)
        return ToolObservation(
            observation_id=observation_id,
            tool="search_dotnet_metadata",
            source_id=source.source_id,
            summary=(
                f"Searched {searched_count} managed assemblies and returned "
                f"{len(visible_methods)} exact methods within the model observation budget."
            ),
            data=data,
        )

    def _inspect(
        self,
        *,
        source: EvidenceDiscoverySource,
        observation_id: str,
        method_id: str,
    ) -> ToolObservation:
        observed = self._observed_methods.get(method_id)
        if observed is None:
            raise ValueError("UNVERIFIED_METHOD_REFERENCE")
        if observed.source_id != source.source_id:
            raise ValueError("METHOD_SOURCE_MISMATCH")
        root = Path(source.root_path)
        assembly = observed.assembly_path.resolve()
        _require_inside(assembly, root)
        report = self.il_runner_factory((observed.symbol,)).inspect(assembly)
        if (
            report.get("assembly_sha256") != observed.assembly_sha256
            or report.get("module_mvid") != observed.module_mvid
        ):
            raise ValueError("OBSERVED_ASSEMBLY_IDENTITY_CHANGED")
        methods = report.get("methods")
        if not isinstance(methods, list) or len(methods) != 1 or not isinstance(methods[0], dict):
            raise ValueError("EXACT_METHOD_REPORT_INVALID")
        method = methods[0]
        if (
            method.get("symbol") != observed.symbol
            or method.get("metadata_token") != observed.metadata_token
        ):
            raise ValueError("OBSERVED_METHOD_IDENTITY_CHANGED")
        instructions = method.get("instructions") or []
        if not isinstance(instructions, list):
            raise ValueError("EXACT_METHOD_INSTRUCTIONS_INVALID")
        model_instructions = instructions[: self.max_model_instructions]
        resolved_refs = sorted(
            {
                str(item["resolved"])
                for item in instructions
                if isinstance(item, dict) and item.get("resolved")
            }
        )
        excerpt = {
            "module_mvid": observed.module_mvid,
            "metadata_token": observed.metadata_token,
            "attributes": method.get("attributes"),
            "impl_attributes": method.get("impl_attributes"),
            "signature_blob": method.get("signature_blob"),
            "rva": method.get("rva", 0),
            "has_method_body": method.get("has_method_body") is True,
            "il_bytes": method.get("il_bytes") or "",
            "instructions": instructions,
            "custom_attributes": method.get("custom_attributes") or [],
            "declaring_type_custom_attributes": method.get(
                "declaring_type_custom_attributes"
            )
            or [],
        }
        declaring_type, method_name = observed.symbol.rsplit(".", 1)
        item = EvidenceItem(
            evidence_id=_stable_id(
                "evidence",
                observed.assembly_sha256,
                observed.module_mvid,
                observed.metadata_token,
                observed.symbol,
            ),
            source_type=source.source_type,
            source_path=observed.relative_path,
            symbol=observed.symbol,
            span=None,
            retrieval_method="agent_selected_cli_metadata_il_read",
            score=1.0,
            claim_supported=(
                f"Hash-bound CLI metadata records token {observed.metadata_token}, "
                f"RVA {method.get('rva', 0)}, and an exact IL body read."
            ),
            excerpt=json.dumps(excerpt, ensure_ascii=False, separators=(",", ":")),
            source_ref=f"source://{source.source_id}/{observed.relative_path}",
            source_hash=observed.assembly_sha256,
            file_hash=observed.assembly_sha256,
            usage="hook_evidence",
            declaring_type=declaring_type,
            method_name=method_name,
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            risk_notes=(
                "CLI metadata inspection did not load or execute the target assembly.",
            ),
        )
        return ToolObservation(
            observation_id=observation_id,
            tool="inspect_method_il",
            source_id=source.source_id,
            summary=(
                f"Read exact IL for observed method {observed.symbol}; "
                f"{len(instructions)} instructions were present."
            ),
            data={
                "method_id": method_id,
                "relative_path": observed.relative_path,
                "assembly_sha256": observed.assembly_sha256,
                "module_mvid": observed.module_mvid,
                "symbol": observed.symbol,
                "metadata_token": observed.metadata_token,
                "has_method_body": method.get("has_method_body") is True,
                "rva": method.get("rva", 0),
                "instruction_count": len(instructions),
                "instructions": model_instructions,
                "instructions_truncated": len(instructions) > len(model_instructions),
                "resolved_refs": resolved_refs,
                "target_code_executed": False,
            },
            evidence_items=(item,),
        )


def _public_metadata_rows(
    rows: object,
    *,
    assembly_id: str,
    limit: int,
) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        raise ValueError("METADATA_RESULT_ROWS_INVALID")
    result: list[dict[str, object]] = []
    for raw in rows[: max(limit, 0)]:
        if not isinstance(raw, dict):
            raise ValueError("METADATA_RESULT_ROW_INVALID")
        result.append(
            {
                "assembly_id": assembly_id,
                "symbol": str(raw["symbol"]),
                "metadata_token": str(raw["metadata_token"]),
            }
        )
    return result


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{kind}_{digest}"


def _require_inside(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("ASSEMBLY_PATH_OUTSIDE_AUTHORIZED_SOURCE") from exc


def _model_view_size(observation: ToolObservation) -> int:
    return len(
        json.dumps(
            observation.model_view(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
