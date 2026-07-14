"""Read exact method IL from the supplied R8 assembly without loading target code."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

R8_MODULES_ASM_SHA256 = "DD0C57D5C527E78B40FAB798456EDD73413DA0F140995A63FCA3619C36C32698"
R8_IL_SYMBOLS = (
    "ES_PathMove.CommonFixedUpdate",
    "ES_PathMove.UpdateRotation",
    "ES_PathMoveBase.UpdateRotation",
)


class R8ILInspectionError(ValueError):
    """Raised when local metadata inspection cannot produce a bound exact report."""


class R8ILInspectionRunner:
    """Invoke the local PEReader helper and validate its exact JSON output."""

    def __init__(
        self,
        inspector_dll: str | Path,
        *,
        dotnet_executable: str = "dotnet",
    ) -> None:
        self.inspector_dll = Path(inspector_dll).resolve()
        self.dotnet_executable = dotnet_executable

    def inspect(self, assembly_path: str | Path) -> dict[str, Any]:
        assembly = Path(assembly_path).resolve()
        if not self.inspector_dll.is_file():
            raise R8ILInspectionError(
                f"R8 IL inspector is not built: {self.inspector_dll}"
            )
        if not assembly.is_file():
            raise R8ILInspectionError(f"R8 assembly is missing: {assembly}")
        assembly_hash = hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
        if assembly_hash != R8_MODULES_ASM_SHA256:
            raise R8ILInspectionError(
                f"R8 Modules-ASM.dll hash mismatch: {assembly_hash}"
            )
        return BoundILInspectionRunner(
            self.inspector_dll,
            symbols=R8_IL_SYMBOLS,
            dotnet_executable=self.dotnet_executable,
        ).inspect(assembly)


class BoundILInspectionRunner:
    """Read an explicitly supplied exact symbol set and bind the report to live bytes."""

    def __init__(
        self,
        inspector_dll: str | Path,
        *,
        symbols: tuple[str, ...],
        dotnet_executable: str = "dotnet",
    ) -> None:
        if not symbols or len(set(symbols)) != len(symbols):
            raise R8ILInspectionError("IL inspection requires unique exact symbols.")
        self.inspector_dll = Path(inspector_dll).resolve()
        self.symbols = symbols
        self.dotnet_executable = dotnet_executable

    def inspect(self, assembly_path: str | Path) -> dict[str, Any]:
        assembly = Path(assembly_path).resolve()
        if not self.inspector_dll.is_file():
            raise R8ILInspectionError(
                f"IL inspector is not built: {self.inspector_dll}"
            )
        if not assembly.is_file():
            raise R8ILInspectionError(f"Assembly is missing: {assembly}")
        assembly_hash = hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
        completed = subprocess.run(
            (
                self.dotnet_executable,
                str(self.inspector_dll),
                str(assembly),
                *self.symbols,
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
        )
        if completed.returncode != 0:
            raise R8ILInspectionError(
                f"R8 IL inspector exited {completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise R8ILInspectionError("IL inspector returned invalid JSON.") from exc
        post_hash = hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
        if post_hash != assembly_hash:
            raise R8ILInspectionError("Assembly bytes changed during IL inspection.")
        _validate_il_report(
            report,
            assembly=assembly,
            assembly_hash=assembly_hash,
            expected_symbols=self.symbols,
        )
        return report


class MetadataSearchRunner:
    """Search literal metadata text in one supplied managed assembly."""

    def __init__(
        self,
        inspector_dll: str | Path,
        *,
        dotnet_executable: str = "dotnet",
    ) -> None:
        self.inspector_dll = Path(inspector_dll).resolve()
        self.dotnet_executable = dotnet_executable

    def search(
        self,
        assembly_path: str | Path,
        *,
        queries: tuple[str, ...],
    ) -> dict[str, Any]:
        assembly = Path(assembly_path).resolve()
        if not queries or any(not query.strip() for query in queries):
            raise R8ILInspectionError("Metadata search requires non-empty literal queries.")
        if not self.inspector_dll.is_file():
            raise R8ILInspectionError(
                f"IL inspector is not built: {self.inspector_dll}"
            )
        if not assembly.is_file():
            raise R8ILInspectionError(f"Assembly is missing: {assembly}")
        assembly_hash = hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
        completed = subprocess.run(
            (
                self.dotnet_executable,
                str(self.inspector_dll),
                str(assembly),
                "--find-metadata",
                *queries,
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
        )
        if completed.returncode != 0:
            raise R8ILInspectionError(
                f"Metadata inspector exited {completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise R8ILInspectionError("Metadata inspector returned invalid JSON.") from exc
        post_hash = hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
        if post_hash != assembly_hash:
            raise R8ILInspectionError("Assembly bytes changed during metadata search.")
        _validate_metadata_report(
            report,
            assembly=assembly,
            assembly_hash=assembly_hash,
            expected_queries=queries,
        )
        return report


def _validate_il_report(
    report: object,
    *,
    assembly: Path,
    assembly_hash: str,
    expected_symbols: tuple[str, ...] = R8_IL_SYMBOLS,
) -> None:
    if not isinstance(report, dict):
        raise R8ILInspectionError("R8 IL report must be a JSON object.")
    if report.get("schema_version") != "r8_il_inspection_v1":
        raise R8ILInspectionError("R8 IL report schema_version mismatch.")
    if Path(str(report.get("assembly_path"))).resolve() != assembly:
        raise R8ILInspectionError("R8 IL report assembly_path mismatch.")
    if report.get("assembly_sha256") != assembly_hash:
        raise R8ILInspectionError("R8 IL report assembly_sha256 mismatch.")
    if report.get("target_code_executed") is not False:
        raise R8ILInspectionError("R8 IL report did not preserve the no-execution boundary.")
    if report.get("missing_symbols") != []:
        raise R8ILInspectionError("R8 IL report is missing one or more exact symbols.")
    methods = report.get("methods")
    if not isinstance(methods, list):
        raise R8ILInspectionError("R8 IL report methods must be a list.")
    reported_symbols = [
        method.get("symbol") for method in methods if isinstance(method, dict)
    ]
    if (
        len(methods) != len(expected_symbols)
        or set(reported_symbols) != set(expected_symbols)
    ):
        raise R8ILInspectionError("R8 IL report exact symbol set mismatch.")


def _validate_metadata_report(
    report: object,
    *,
    assembly: Path,
    assembly_hash: str,
    expected_queries: tuple[str, ...],
) -> None:
    if not isinstance(report, dict):
        raise R8ILInspectionError("Metadata report must be a JSON object.")
    if report.get("schema_version") != "cli_metadata_search_v1":
        raise R8ILInspectionError("Metadata report schema_version mismatch.")
    if Path(str(report.get("assembly_path"))).resolve() != assembly:
        raise R8ILInspectionError("Metadata report assembly_path mismatch.")
    if report.get("assembly_sha256") != assembly_hash:
        raise R8ILInspectionError("Metadata report assembly_sha256 mismatch.")
    if report.get("queries") != list(expected_queries):
        raise R8ILInspectionError("Metadata report query binding mismatch.")
    if report.get("target_code_executed") is not False:
        raise R8ILInspectionError("Metadata search did not preserve the no-execution boundary.")
    if not isinstance(report.get("module_mvid"), str) or not report["module_mvid"]:
        raise R8ILInspectionError("Metadata report module_mvid is missing.")
    for field in ("types", "methods", "fields"):
        if not isinstance(report.get(field), list):
            raise R8ILInspectionError(f"Metadata report {field} must be a list.")
