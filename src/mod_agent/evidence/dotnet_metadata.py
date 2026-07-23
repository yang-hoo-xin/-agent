"""Run-local .NET metadata enrichment for source-bound member access facts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import EvidenceItem, EvidencePack

DIRECT_BOOLEAN_MEMBER_ACCESS_SCHEMA = (
    "dotnet_direct_boolean_member_access_resolution_v1"
)
_DIRECT_CONSTRUCTED_GENERIC_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*<[^<>]+>$"
)


class DotNetMetadataEnrichmentError(ValueError):
    """Raised when the bounded metadata identity chain cannot be proven."""


class RunLocalMemberAccessResolver:
    """Invoke one run-local inspector and validate its exact identity report."""

    def __init__(
        self,
        inspector_dll: str | Path,
        *,
        dependency_root: str | Path,
        dotnet_executable: str = "dotnet",
        timeout_seconds: int = 120,
    ) -> None:
        self.inspector_dll = Path(inspector_dll).resolve()
        self.dependency_root = Path(dependency_root).resolve()
        self.dotnet_executable = dotnet_executable
        self.timeout_seconds = timeout_seconds

    def resolve(
        self,
        consumer_assembly: str | Path,
        *,
        consumer_declaring_type: str,
        receiver_member: str,
    ) -> dict[str, Any]:
        consumer = Path(consumer_assembly).resolve()
        if not self.inspector_dll.is_file():
            raise DotNetMetadataEnrichmentError(
                "Run-local metadata inspector is missing."
            )
        if not consumer.is_file():
            raise DotNetMetadataEnrichmentError(
                "Baseline consumer assembly is missing."
            )
        if not self.dependency_root.is_dir():
            raise DotNetMetadataEnrichmentError(
                "Run-local dependency root is missing."
            )
        if not consumer_declaring_type or not receiver_member:
            raise DotNetMetadataEnrichmentError(
                "Metadata member resolution requires exact source identities."
            )

        consumer_hash = _sha256_upper(consumer)
        command = (
            self.dotnet_executable,
            str(self.inspector_dll),
            str(consumer),
            "--resolve-direct-boolean-member-accesses",
            str(self.dependency_root),
            consumer_declaring_type,
            receiver_member,
        )
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise DotNetMetadataEnrichmentError(
                "Run-local metadata inspector failed with exit code "
                f"{completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise DotNetMetadataEnrichmentError(
                "Run-local metadata inspector returned invalid JSON."
            ) from exc
        if _sha256_upper(consumer) != consumer_hash:
            raise DotNetMetadataEnrichmentError(
                "Baseline consumer assembly changed during metadata inspection."
            )
        _validate_direct_boolean_member_access_report(
            report,
            consumer_hash=consumer_hash,
            consumer_declaring_type=consumer_declaring_type,
            receiver_member=receiver_member,
            dependency_root=self.dependency_root,
        )
        return report


def enrich_source_evidence_with_member_accesses(
    evidence_pack: EvidencePack,
    *,
    consumer_assembly: str | Path,
    resolver: RunLocalMemberAccessResolver,
) -> EvidencePack:
    """Join source declarations with compiled and dependency metadata facts."""

    enriched_items = tuple(
        _enrich_item(
            item,
            consumer_assembly=consumer_assembly,
            resolver=resolver,
        )
        for item in evidence_pack.items
    )
    return replace(evidence_pack, items=enriched_items)


def _enrich_item(
    item: EvidenceItem,
    *,
    consumer_assembly: str | Path,
    resolver: RunLocalMemberAccessResolver,
) -> EvidenceItem:
    declared_members = item.declared_members
    declaring_type = item.declaring_type_full_name
    if not isinstance(declared_members, dict) or not declaring_type:
        return item
    source_hash = item.source_hash or item.file_hash or item.doc_hash
    if not source_hash:
        raise DotNetMetadataEnrichmentError(
            "Source member enrichment requires a bound source hash."
        )

    verified: list[dict[str, Any]] = []
    for member_name, identity in sorted(declared_members.items()):
        if not isinstance(identity, dict):
            continue
        declared_type = identity.get("declared_type")
        if (
            not isinstance(declared_type, str)
            or not _DIRECT_CONSTRUCTED_GENERIC_RE.fullmatch(declared_type)
        ):
            continue
        if identity.get("member_kind") not in {"field", "property"}:
            continue
        report = resolver.resolve(
            consumer_assembly,
            consumer_declaring_type=declaring_type,
            receiver_member=member_name,
        )
        consumer = report["consumer"]
        if (
            consumer["member_kind"] != identity["member_kind"]
            or consumer["is_static"] is not identity["is_static"]
        ):
            raise DotNetMetadataEnrichmentError(
                "Source and compiled receiver member identities do not match."
            )
        for access in report["verified_member_accesses"]:
            verified.append(
                {
                    "source_receiver": {
                        "evidence_id": item.evidence_id,
                        "source_path": item.source_path,
                        "source_hash": source_hash,
                        "declaring_type": declaring_type,
                        "member_name": member_name,
                        "member_kind": identity["member_kind"],
                        "declaration_span": dict(identity["declaration_span"]),
                        "declared_type": declared_type,
                        "receiver_closed_type": consumer["receiver_closed_type"],
                    },
                    "consumer": dict(consumer),
                    "type_reference": dict(report["type_reference"]),
                    "assembly_reference": dict(report["assembly_reference"]),
                    "resolved_assembly": dict(report["resolved_assembly"]),
                    "member_access": dict(access),
                }
            )
    return replace(item, verified_member_accesses=tuple(verified))


def _validate_direct_boolean_member_access_report(
    report: object,
    *,
    consumer_hash: str,
    consumer_declaring_type: str,
    receiver_member: str,
    dependency_root: Path,
) -> None:
    if not isinstance(report, dict):
        raise DotNetMetadataEnrichmentError(
            "Metadata member-access report must be a JSON object."
        )
    if report.get("schema_version") != DIRECT_BOOLEAN_MEMBER_ACCESS_SCHEMA:
        raise DotNetMetadataEnrichmentError(
            "Metadata member-access report schema_version mismatch."
        )
    if report.get("target_code_executed") is not False:
        raise DotNetMetadataEnrichmentError(
            "Metadata member resolution did not preserve the no-execution boundary."
        )
    request = report.get("request")
    if request != {
        "consumer_declaring_type": consumer_declaring_type,
        "receiver_member": receiver_member,
    }:
        raise DotNetMetadataEnrichmentError(
            "Metadata member-access request identity mismatch."
        )
    consumer = _required_dict(report, "consumer")
    if consumer.get("assembly_sha256") != consumer_hash:
        raise DotNetMetadataEnrichmentError(
            "Metadata consumer assembly SHA256 mismatch."
        )
    if (
        consumer.get("declaring_type") != consumer_declaring_type
        or consumer.get("receiver_member") != receiver_member
    ):
        raise DotNetMetadataEnrichmentError(
            "Metadata compiled receiver identity mismatch."
        )
    for field in (
        "module_name",
        "module_mvid",
        "member_kind",
        "member_metadata_token",
        "signature_blob",
        "receiver_closed_type",
    ):
        if not isinstance(consumer.get(field), str) or not consumer[field]:
            raise DotNetMetadataEnrichmentError(
                f"Metadata consumer field {field} is missing."
            )
    if not isinstance(consumer.get("is_static"), bool):
        raise DotNetMetadataEnrichmentError(
            "Metadata consumer static-member identity is missing."
        )

    type_reference = _required_dict(report, "type_reference")
    if type_reference.get("resolution_scope_kind") != "AssemblyReference":
        raise DotNetMetadataEnrichmentError(
            "Metadata TypeRef is not bound to one direct AssemblyRef."
        )
    for field in (
        "symbol",
        "metadata_token",
        "resolution_scope_metadata_token",
    ):
        if not isinstance(type_reference.get(field), str) or not type_reference[field]:
            raise DotNetMetadataEnrichmentError(
                f"Metadata TypeRef field {field} is missing."
            )

    assembly_reference = _required_dict(report, "assembly_reference")
    resolved_assembly = _required_dict(report, "resolved_assembly")
    assembly_definition = _required_dict(
        resolved_assembly,
        "assembly_definition",
    )
    for field in ("name", "version", "culture", "public_key_token"):
        if assembly_reference.get(field) != assembly_definition.get(field):
            raise DotNetMetadataEnrichmentError(
                "AssemblyRef identity does not match the resolved AssemblyDefinition."
            )
    if not isinstance(assembly_reference.get("metadata_token"), str):
        raise DotNetMetadataEnrichmentError(
            "AssemblyRef metadata token is missing."
        )
    if (
        type_reference.get("resolution_scope_metadata_token")
        != assembly_reference.get("metadata_token")
    ):
        raise DotNetMetadataEnrichmentError(
            "TypeRef resolution scope does not match the reported AssemblyRef."
        )

    relative_path = resolved_assembly.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        raise DotNetMetadataEnrichmentError(
            "Resolved assembly relative path is missing."
        )
    physical_path = (dependency_root / relative_path).resolve()
    try:
        physical_path.relative_to(dependency_root)
    except ValueError as exc:
        raise DotNetMetadataEnrichmentError(
            "Resolved assembly escapes the run-local dependency root."
        ) from exc
    if not physical_path.is_file():
        raise DotNetMetadataEnrichmentError(
            "Resolved run-local physical assembly is missing."
        )
    if resolved_assembly.get("assembly_sha256") != _sha256_upper(physical_path):
        raise DotNetMetadataEnrichmentError(
            "Resolved run-local assembly SHA256 mismatch."
        )
    for field in ("module_name", "module_mvid"):
        if not isinstance(resolved_assembly.get(field), str) or not resolved_assembly[field]:
            raise DotNetMetadataEnrichmentError(
                f"Resolved assembly field {field} is missing."
            )

    accesses = report.get("verified_member_accesses")
    if not isinstance(accesses, list) or not accesses:
        raise DotNetMetadataEnrichmentError(
            "Metadata report contains no verified Boolean member access."
        )
    for access in accesses:
        if not isinstance(access, dict):
            raise DotNetMetadataEnrichmentError(
                "Verified member access must be an object."
            )
        if (
            access.get("member_kind") != "property"
            or access.get("access_kind") != "instance_property_get"
            or access.get("closed_result_type") != "System.Boolean"
            or access.get("declaring_type") != type_reference.get("symbol")
            or not isinstance(
                access.get("generic_result_type_parameter_index"),
                int,
            )
        ):
            raise DotNetMetadataEnrichmentError(
                "Verified member access exceeds the bounded Boolean-property contract."
            )
        for field in (
            "declaring_type",
            "declaring_type_metadata_token",
            "member_name",
            "property_metadata_token",
            "getter_metadata_token",
            "property_signature_blob",
        ):
            if not isinstance(access.get(field), str) or not access[field]:
                raise DotNetMetadataEnrichmentError(
                    f"Verified member access field {field} is missing."
                )


def _required_dict(value: dict[str, Any], key: str) -> dict[str, Any]:
    selected = value.get(key)
    if not isinstance(selected, dict):
        raise DotNetMetadataEnrichmentError(
            f"Metadata member-access report field {key} must be an object."
        )
    return selected


def _sha256_upper(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()
