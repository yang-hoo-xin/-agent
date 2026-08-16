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


@dataclass(frozen=True)
class _CandidateBinding:
    run_id: str
    observation_id: str
    source_id: str
    method_id: str


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
        self._run_id: str | None = None
        self._observed_methods: dict[str, _ObservedMethod] = {}
        self._candidate_bindings: dict[str, _CandidateBinding] = {}

    def begin_run(self, *, run_id: str) -> None:
        if not run_id.strip():
            raise ValueError("EVIDENCE_TOOL_RUN_ID_INVALID")
        self._run_id = run_id
        self._observed_methods.clear()
        self._candidate_bindings.clear()

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
                candidate_ref=str(arguments["candidate_ref"]),
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
        if self._run_id is None:
            raise ValueError("EVIDENCE_TOOL_RUN_NOT_STARTED")
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
        method_pool: list[dict[str, object]] = []
        type_pool: list[dict[str, object]] = []
        field_pool: list[dict[str, object]] = []
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
            for raw in raw_methods:
                if not isinstance(raw, dict):
                    raise ValueError("METADATA_METHOD_RESULT_INVALID")
                symbol = str(raw["symbol"])
                metadata_token = str(raw["metadata_token"])
                method_pool.append(
                    {
                        "assembly_id": assembly_id,
                        "symbol": symbol,
                        "metadata_token": metadata_token,
                        "has_method_body": raw.get("has_method_body") is True,
                        "matched_queries": _matched_queries(symbol, queries),
                        "observed": _ObservedMethod(
                            source_id=source.source_id,
                            assembly_path=assembly,
                            relative_path=relative_path,
                            assembly_sha256=assembly_hash,
                            module_mvid=module_mvid,
                            symbol=symbol,
                            metadata_token=metadata_token,
                        ),
                    }
                )
            type_pool.extend(
                _public_metadata_rows(
                    raw_types,
                    assembly_id=assembly_id,
                    queries=queries,
                )
            )
            field_pool.extend(
                _public_metadata_rows(
                    raw_fields,
                    assembly_id=assembly_id,
                    queries=queries,
                )
            )
        method_pool.sort(key=lambda row: _metadata_relevance_key(row, queries))
        type_pool.sort(key=lambda row: _metadata_relevance_key(row, queries))
        field_pool.sort(key=lambda row: _metadata_relevance_key(row, queries))
        methods: list[dict[str, object]] = []
        if "methods" in result_kinds:
            for row in _fair_metadata_window(
                method_pool,
                queries=queries,
                limit=limit_per_kind,
            ):
                observed = row["observed"]
                assert isinstance(observed, _ObservedMethod)
                method_id = _stable_id(
                    "method",
                    str(row["assembly_id"]),
                    observed.metadata_token,
                    observed.symbol,
                )
                self._observed_methods[method_id] = observed
                candidate_ref = _stable_id(
                    "candidate",
                    self._run_id,
                    source.source_id,
                    observation_id,
                    method_id,
                )
                self._candidate_bindings[candidate_ref] = _CandidateBinding(
                    run_id=self._run_id,
                    observation_id=observation_id,
                    source_id=source.source_id,
                    method_id=method_id,
                )
                methods.append(
                    {
                        "candidate_ref": candidate_ref,
                        "method_id": method_id,
                        "assembly_id": row["assembly_id"],
                        "symbol": row["symbol"],
                        "metadata_token": row["metadata_token"],
                        "has_method_body": row["has_method_body"],
                        "matched_queries": row["matched_queries"],
                    }
                )
        types = type_pool[:limit_per_kind] if "types" in result_kinds else []
        fields = field_pool[:limit_per_kind] if "fields" in result_kinds else []
        pools = {"methods": method_pool, "types": type_pool, "fields": field_pool}
        returned = {"methods": methods, "types": types, "fields": fields}
        for kind in ("methods", "types", "fields"):
            if kind in result_kinds and len(pools[kind]) > len(returned[kind]):
                truncated = True
                truncated_by_kind[kind] = True
        matched_query_counts = _per_query_counts(queries, pools)
        data: dict[str, object] = {
            "queries": list(queries),
            "requested_result_kinds": list(result_kinds),
            "limit_per_kind": limit_per_kind,
            "assemblies_discovered": len(assemblies),
            "managed_assemblies_searched": searched_count,
            "unreadable_or_non_managed_assemblies": unreadable_count,
            "assemblies": assembly_views,
            "matched_counts": matched_counts,
            "matched_query_counts": matched_query_counts,
            "returned_counts": {
                "methods": len(methods),
                "types": len(types),
                "fields": len(fields),
            },
            "returned_query_counts": _per_query_counts(
                queries,
                {"methods": methods, "types": types, "fields": fields},
            ),
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
                f"Searched {searched_count} managed assemblies and returned "
                f"{len(methods)} exact methods within the model observation budget."
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
        data["returned_query_counts"] = _per_query_counts(
            queries,
            {
                "methods": data["methods"],
                "types": data["types"],
                "fields": data["fields"],
            },
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
        candidate_ref: str,
    ) -> ToolObservation:
        if self._run_id is None:
            raise ValueError("EVIDENCE_TOOL_RUN_NOT_STARTED")
        binding = self._candidate_bindings.get(candidate_ref)
        if binding is None or binding.run_id != self._run_id:
            raise ValueError("UNVERIFIED_CANDIDATE_REFERENCE")
        if binding.source_id != source.source_id:
            raise ValueError("CANDIDATE_SOURCE_MISMATCH")
        method_id = binding.method_id
        observed = self._observed_methods.get(method_id)
        if observed is None:
            raise ValueError("UNVERIFIED_METHOD_REFERENCE")
        if observed.source_id != source.source_id:
            raise ValueError("METHOD_SOURCE_MISMATCH")
        root = Path(source.root_path)
        assembly = observed.assembly_path.resolve()
        _require_inside(assembly, root)
        report = self.il_runner_factory((observed.symbol,)).inspect_observed_method(
            assembly,
            assembly_sha256=observed.assembly_sha256,
            module_mvid=observed.module_mvid,
            metadata_token=observed.metadata_token,
        )
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
            module_mvid=observed.module_mvid,
            metadata_token=observed.metadata_token,
            signature_blob=str(method.get("signature_blob") or ""),
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            source_authority=source.source_authority,
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
                "candidate_ref": candidate_ref,
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
    queries: tuple[str, ...],
) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        raise ValueError("METADATA_RESULT_ROWS_INVALID")
    result: list[dict[str, object]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("METADATA_RESULT_ROW_INVALID")
        result.append(
            {
                "assembly_id": assembly_id,
                "symbol": str(raw["symbol"]),
                "metadata_token": str(raw["metadata_token"]),
                "matched_queries": _matched_queries(str(raw["symbol"]), queries),
            }
        )
    return result


def _matched_queries(symbol: str, queries: tuple[str, ...]) -> list[str]:
    normalized_symbol = symbol.casefold()
    return [query for query in queries if query.casefold() in normalized_symbol]


def _metadata_relevance_key(
    row: dict[str, object], queries: tuple[str, ...]
) -> tuple[object, ...]:
    matched = row.get("matched_queries")
    if not isinstance(matched, list) or not matched:
        raise ValueError("METADATA_MATCH_BINDING_INVALID")
    query_order = {query: index for index, query in enumerate(queries)}
    matched_strings = [str(value) for value in matched]
    return (
        -len(matched_strings),
        -max(len(value) for value in matched_strings),
        -sum(len(value) for value in matched_strings),
        min(query_order[value] for value in matched_strings),
        str(row["symbol"]).casefold(),
        str(row["metadata_token"]),
    )


def _fair_metadata_window(
    rows: list[dict[str, object]],
    *,
    queries: tuple[str, ...],
    limit: int,
) -> list[dict[str, object]]:
    """Interleave exact query views within one shared method budget."""

    query_rows: dict[str, list[dict[str, object]]] = {}
    for query in queries:
        query_rows[query] = [
            row
            for row in rows
            if query in row.get("matched_queries", [])
        ]

    selected: list[dict[str, object]] = []
    selected_keys: set[tuple[str, str, str]] = set()
    while len(selected) < limit:
        progressed = False
        for query in queries:
            queue = query_rows[query]
            while queue:
                row = queue.pop(0)
                key = (
                    str(row["assembly_id"]),
                    str(row["symbol"]),
                    str(row["metadata_token"]),
                )
                if key in selected_keys:
                    continue
                selected.append(row)
                selected_keys.add(key)
                progressed = True
                break
            if len(selected) == limit:
                break
        if not progressed:
            break
    return selected


def _per_query_counts(
    queries: tuple[str, ...],
    rows_by_kind: dict[str, list[dict[str, object]]],
) -> dict[str, dict[str, int]]:
    return {
        query: {
            kind: sum(
                1
                for row in rows_by_kind[kind]
                if query in row.get("matched_queries", [])
            )
            for kind in ("methods", "types", "fields")
        }
        for query in queries
    }


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
