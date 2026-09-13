from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.mod_agent.upstream_trace import payload_sha256

from src.mod_agent.evidence.dotnet_metadata import (
    DotNetMetadataEnrichmentError,
    RunLocalMemberAccessResolver,
    enrich_source_evidence_with_member_accesses,
)
from src.mod_agent.evidence.models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EvidenceItem,
    EvidencePack,
)


def _sha256_upper(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _report(
    *,
    consumer_hash: str,
    dependency_hash: str,
) -> dict[str, object]:
    assembly_identity = {
        "name": "Shared.Settings",
        "version": "1.2.3.4",
        "culture": "",
        "public_key_token": "",
    }
    return {
        "schema_version": "dotnet_direct_boolean_member_access_resolution_v1",
        "request": {
            "consumer_declaring_type": "Example.Plugin",
            "receiver_member": "SettingsHandle",
        },
        "consumer": {
            "assembly_sha256": consumer_hash,
            "module_name": "Example.dll",
            "module_mvid": "00000000-0000-0000-0000-000000000001",
            "declaring_type": "Example.Plugin",
            "receiver_member": "SettingsHandle",
            "member_kind": "property",
            "is_static": True,
            "member_metadata_token": "0x17000001",
            "signature_blob": "0800",
            "receiver_closed_type": "Shared.SettingBox`1<System.Boolean>",
        },
        "type_reference": {
            "symbol": "Shared.SettingBox`1",
            "metadata_token": "0x01000001",
            "resolution_scope_kind": "AssemblyReference",
            "resolution_scope_metadata_token": "0x23000001",
        },
        "assembly_reference": {
            "metadata_token": "0x23000001",
            **assembly_identity,
            "flags": "0",
            "hash_value": "",
        },
        "resolved_assembly": {
            "relative_path": "core/Shared.Settings.dll",
            "assembly_sha256": dependency_hash,
            "module_name": "Shared.Settings.dll",
            "module_mvid": "00000000-0000-0000-0000-000000000002",
            "assembly_definition": {
                **assembly_identity,
                "flags": "0",
            },
        },
        "verified_member_accesses": [
            {
                "declaring_type": "Shared.SettingBox`1",
                "declaring_type_metadata_token": "0x02000001",
                "member_name": "IsReady",
                "member_kind": "property",
                "access_kind": "instance_property_get",
                "property_metadata_token": "0x17000001",
                "getter_metadata_token": "0x06000001",
                "property_signature_blob": "28001300",
                "generic_result_type_parameter_index": 0,
                "closed_result_type": "System.Boolean",
            }
        ],
        "target_code_executed": False,
    }


def test_run_local_member_access_resolver_validates_full_identity_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspector = tmp_path / "inspector.dll"
    inspector.write_bytes(b"inspector")
    consumer = tmp_path / "Example.dll"
    consumer.write_bytes(b"consumer")
    dependency = tmp_path / "dependencies" / "core" / "Shared.Settings.dll"
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"dependency")
    report = _report(
        consumer_hash=_sha256_upper(b"consumer"),
        dependency_hash=_sha256_upper(b"dependency"),
    )

    def run(command, **kwargs):
        assert command[-2:] == ("Example.Plugin", "SettingsHandle")
        assert kwargs["timeout"] == 120
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(report),
            stderr="",
        )

    monkeypatch.setattr(
        "src.mod_agent.evidence.dotnet_metadata.subprocess.run",
        run,
    )

    resolved = RunLocalMemberAccessResolver(
        inspector,
        dependency_root=tmp_path / "dependencies",
    ).resolve(
        consumer,
        consumer_declaring_type="Example.Plugin",
        receiver_member="SettingsHandle",
    )

    assert resolved["assembly_reference"]["name"] == "Shared.Settings"
    assert resolved["verified_member_accesses"][0]["member_name"] == "IsReady"


def test_run_local_member_access_resolver_rejects_assembly_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspector = tmp_path / "inspector.dll"
    inspector.write_bytes(b"inspector")
    consumer = tmp_path / "Example.dll"
    consumer.write_bytes(b"consumer")
    dependency = tmp_path / "dependencies" / "core" / "Shared.Settings.dll"
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"dependency")
    report = _report(
        consumer_hash=_sha256_upper(b"consumer"),
        dependency_hash=_sha256_upper(b"dependency"),
    )
    report["resolved_assembly"]["assembly_definition"]["version"] = "9.9.9.9"
    monkeypatch.setattr(
        "src.mod_agent.evidence.dotnet_metadata.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(report),
            stderr="",
        ),
    )

    with pytest.raises(
        DotNetMetadataEnrichmentError,
        match="AssemblyRef identity",
    ):
        RunLocalMemberAccessResolver(
            inspector,
            dependency_root=tmp_path / "dependencies",
        ).resolve(
            consumer,
            consumer_declaring_type="Example.Plugin",
            receiver_member="SettingsHandle",
        )


def test_run_local_member_access_resolver_rejects_assembly_scope_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspector = tmp_path / "inspector.dll"
    inspector.write_bytes(b"inspector")
    consumer = tmp_path / "Example.dll"
    consumer.write_bytes(b"consumer")
    dependency = tmp_path / "dependencies" / "core" / "Shared.Settings.dll"
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"dependency")
    report = _report(
        consumer_hash=_sha256_upper(b"consumer"),
        dependency_hash=_sha256_upper(b"dependency"),
    )
    report["type_reference"]["resolution_scope_metadata_token"] = "0x23000002"
    monkeypatch.setattr(
        "src.mod_agent.evidence.dotnet_metadata.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(report),
            stderr="",
        ),
    )

    with pytest.raises(
        DotNetMetadataEnrichmentError,
        match="TypeRef resolution scope",
    ):
        RunLocalMemberAccessResolver(
            inspector,
            dependency_root=tmp_path / "dependencies",
        ).resolve(
            consumer,
            consumer_declaring_type="Example.Plugin",
            receiver_member="SettingsHandle",
        )


def test_enrichment_binds_source_receiver_and_compiled_member_identity() -> None:
    report = _report(
        consumer_hash="A" * 64,
        dependency_hash="B" * 64,
    )

    class Resolver:
        def resolve(self, consumer_assembly, **kwargs):
            assert Path(consumer_assembly).name == "Example.dll"
            assert kwargs == {
                "consumer_declaring_type": "Example.Plugin",
                "receiver_member": "SettingsHandle",
            }
            return report

    item = EvidenceItem(
        evidence_id="ev_001",
        source_type="target_source",
        source_path="generated_mods/Example/Plugin.cs",
        symbol="Load",
        span={"start_line": 10, "end_line": 20},
        retrieval_method="rg_live_read",
        score=1.0,
        claim_supported="Current source contains Load.",
        excerpt="public void Load() {}",
        source_hash="C" * 64,
        declaring_type="Plugin",
        declaring_type_full_name="Example.Plugin",
        method_name="Load",
        return_type="void",
        method_kind="method",
        declared_member_types={"SettingsHandle": "SettingBox<bool>"},
        declared_members={
            "SettingsHandle": {
                "member_name": "SettingsHandle",
                "member_kind": "property",
                "declared_type": "SettingBox<bool>",
                "declaring_type": "Example.Plugin",
                "declaration_span": {"start_line": 5, "end_line": 5},
                "is_static": True,
            }
        },
        authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
    )
    pack = EvidencePack(
        query="startup",
        readiness="sufficient",
        can_generate_patch=True,
        items=(item,),
    )

    trace = ExecutionTrace("member-enrichment-test", "task", "test")
    with trace.activate():
        enriched = enrich_source_evidence_with_member_accesses(
            pack,
            consumer_assembly=Path("Example.dll"),
            resolver=Resolver(),
        )
        same = enrich_source_evidence_with_member_accesses(
            enriched, consumer_assembly=Path("Example.dll"), resolver=Resolver())
    rows = list({stage["data"]["id"]: stage["data"] for stage in trace.context.stages}.values())
    observations = [row for row in rows if row["name"] == "evidence.member_access_enrich"]
    first, second = [row["attributes"] for row in observations]
    assert first["input_payload_sha256"] == payload_sha256(pack.to_artifact_payload())
    assert first["output_payload_sha256"] == payload_sha256(enriched.to_artifact_payload())
    assert first["input_member_access_count"] == 0
    assert first["output_member_access_count"] == first["added_member_access_count"] == 1
    assert first["removed_member_access_count"] == 0
    assert second["input_payload_sha256"] == first["output_payload_sha256"]
    assert second["added_member_access_count"] == second["removed_member_access_count"] == 0
    assert second["output_payload_sha256"] == payload_sha256(same.to_artifact_payload())
    assert first["fact_delivery_status"] == "evidence_pack_enriched_model_delivery_unproven"
    assert not any(row["kind"] == "generation" for row in rows)

    fact = enriched.items[0].verified_member_accesses[0]
    assert fact["source_receiver"] == {
        "evidence_id": "ev_001",
        "source_path": "generated_mods/Example/Plugin.cs",
        "source_hash": "C" * 64,
        "declaring_type": "Example.Plugin",
        "member_name": "SettingsHandle",
        "member_kind": "property",
        "declaration_span": {"start_line": 5, "end_line": 5},
        "declared_type": "SettingBox<bool>",
        "receiver_closed_type": "Shared.SettingBox`1<System.Boolean>",
    }
    assert fact["consumer"]["member_metadata_token"] == "0x17000001"
    assert fact["assembly_reference"]["metadata_token"] == "0x23000001"
    assert fact["member_access"]["closed_result_type"] == "System.Boolean"
