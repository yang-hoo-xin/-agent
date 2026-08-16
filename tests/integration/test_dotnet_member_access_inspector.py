from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.mod_agent.evidence.discovery import (
    EvidenceDiscoveryRequest,
    EvidenceDiscoverySpecialist,
    evidence_discovery_source_from_definition,
)
from src.mod_agent.evidence.discovery_tools import LocalAssemblyEvidenceToolExecutor
from src.mod_agent.knowledge import SourceDefinition


def _restore_and_build(
    project: Path,
    *,
    config_file: Path,
    packages: Path,
    environment: dict[str, str],
) -> None:
    restore = subprocess.run(
        (
            "dotnet",
            "restore",
            str(project),
            "--configfile",
            str(config_file),
            "--packages",
            str(packages),
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        check=False,
    )
    assert restore.returncode == 0, restore.stderr
    build = subprocess.run(
        ("dotnet", "build", str(project), "--no-restore"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        check=False,
    )
    assert build.returncode == 0, build.stderr


@pytest.mark.skipif(shutil.which("dotnet") is None, reason="dotnet is unavailable")
def test_inspector_resolves_direct_generic_boolean_property(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "nuget.config"
    config_file.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<configuration><packageSources><clear /></packageSources></configuration>",
        encoding="utf-8",
    )
    appdata = tmp_path / "appdata"
    user_config = appdata / "NuGet" / "NuGet.Config"
    user_config.parent.mkdir(parents=True)
    shutil.copyfile(config_file, user_config)
    packages = tmp_path / "packages"
    environment = {
        **os.environ,
        "APPDATA": str(appdata),
        "NUGET_PACKAGES": str(packages),
        "NUGET_HTTP_CACHE_PATH": str(tmp_path / "http-cache"),
        "NUGET_SCRATCH": str(tmp_path / "scratch"),
        "NUGET_PLUGINS_CACHE_PATH": str(tmp_path / "plugins-cache"),
    }

    dependency = tmp_path / "Shared.Settings"
    dependency.mkdir()
    (dependency / "Shared.Settings.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<TargetFramework>net7.0</TargetFramework>"
        "<AssemblyName>Shared.Settings</AssemblyName>"
        "<Version>1.2.3</Version>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )
    (dependency / "SettingBox.cs").write_text(
        "namespace Shared;\n"
        "public sealed class SettingBox<T>\n"
        "{\n"
        "    public T IsReady { get; set; } = default!;\n"
        "    public static T StaticValue { get; set; } = default!;\n"
        "    public T this[int index] => default!;\n"
        "    public string Label => string.Empty;\n"
        "}\n",
        encoding="utf-8",
    )

    consumer = tmp_path / "Example"
    consumer.mkdir()
    (consumer / "Example.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<TargetFramework>net7.0</TargetFramework>"
        "<AssemblyName>Example</AssemblyName>"
        "</PropertyGroup><ItemGroup>"
        '<ProjectReference Include="../Shared.Settings/Shared.Settings.csproj" />'
        "</ItemGroup></Project>",
        encoding="utf-8",
    )
    (consumer / "Plugin.cs").write_text(
        "using Shared;\n"
        "namespace Example;\n"
        "public static class Plugin\n"
        "{\n"
        "    public static SettingBox<bool> SettingsHandle { get; } = new();\n"
        "    public static void PulseCorridorLights() { }\n"
        "    public static void PulseCorridorLights(int duration) { }\n"
        "}\n",
        encoding="utf-8",
    )

    repository_root = Path(__file__).resolve().parents[2]
    inspector = tmp_path / "inspector"
    inspector.mkdir()
    shutil.copyfile(
        repository_root / "scripts" / "r8_il_inspector" / "Program.cs",
        inspector / "Program.cs",
    )
    shutil.copyfile(
        repository_root
        / "scripts"
        / "r8_il_inspector"
        / "r8_il_inspector.csproj",
        inspector / "r8_il_inspector.csproj",
    )

    _restore_and_build(
        inspector / "r8_il_inspector.csproj",
        config_file=config_file,
        packages=packages,
        environment=environment,
    )
    _restore_and_build(
        consumer / "Example.csproj",
        config_file=config_file,
        packages=packages,
        environment=environment,
    )

    consumer_output = consumer / "bin" / "Debug" / "net7.0"
    completed = subprocess.run(
        (
            "dotnet",
            str(
                inspector
                / "bin"
                / "Debug"
                / "net7.0"
                / "r8_il_inspector.dll"
            ),
            str(consumer_output / "Example.dll"),
            "--resolve-direct-boolean-member-accesses",
            str(consumer_output),
            "Example.Plugin",
            "SettingsHandle",
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        env=environment,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["schema_version"] == (
        "dotnet_direct_boolean_member_access_resolution_v1"
    )
    assert report["consumer"]["member_kind"] == "property"
    assert report["consumer"]["is_static"] is True
    assert report["type_reference"]["symbol"] == "Shared.SettingBox`1"
    assert report["assembly_reference"]["name"] == "Shared.Settings"
    assert report["resolved_assembly"]["assembly_definition"]["name"] == (
        "Shared.Settings"
    )
    assert len(report["verified_member_accesses"]) == 1
    access = report["verified_member_accesses"][0]
    assert access["declaring_type"] == "Shared.SettingBox`1"
    assert access["member_name"] == "IsReady"
    assert access["member_kind"] == "property"
    assert access["access_kind"] == "instance_property_get"
    assert access["property_signature_blob"] == "28001300"
    assert access["generic_result_type_parameter_index"] == 0
    assert access["closed_result_type"] == "System.Boolean"
    assert access["declaring_type_metadata_token"].startswith("0x02")

    class _ActualPathModel:
        def __init__(self) -> None:
            self.turn = 0

        def complete(self, messages: tuple[dict[str, object], ...]) -> str:
            self.turn += 1
            if self.turn == 1:
                return json.dumps(
                    {
                        "action": "plan",
                        "planning_status": "ready",
                        "requirement_projection": {
                            "schema_version": "hook_requirement_projection_v2",
                            "behavior_goal": "Pulse corridor lights after an event.",
                            "trigger": "event completion",
                            "actor": None,
                            "target": "corridor lights",
                            "hard_constraints": [],
                            "forbidden_outcomes": [],
                            "implementation_hints": [],
                            "acceptance_signals": [],
                            "planning_blocking_questions": [{
                                "requirement_id": "req-light-pulse",
                                "question": "Which current managed method exposes the light pulse action?",
                            }],
                            "deferred_planning_or_runtime_questions": [],
                        },
                        "search_plan": {
                            "schema_version": "hook_discovery_search_plan_v3",
                            "engineering_questions": [{
                                "question_id": "question-light-pulse",
                                "question": "Which current managed method exposes the light pulse action?",
                                "requirement_ids": ["req-light-pulse"],
                            }],
                            "source_roles": [
                                {"source_id": "controlled-assembly", "role": "current_metadata_and_il"}
                            ],
                            "planned_lanes": [
                                {
                                    "lane": "managed_metadata_discovery",
                                    "tool": "search_dotnet_metadata",
                                    "source_ids": ["controlled-assembly"],
                                    "question_ids": ["question-light-pulse"],
                                },
                                {
                                    "lane": "exact_il_verification",
                                    "tool": "inspect_method_il",
                                    "source_ids": ["controlled-assembly"],
                                    "question_ids": ["question-light-pulse"],
                                },
                            ],
                            "query_families": [
                                {
                                    "family_id": "request-derived-light-pulse",
                                    "queries": ["PulseCorridorLights"],
                                    "evidence_need": "Which current managed method exposes the light pulse action?",
                                    "source_ids": ["controlled-assembly"],
                                    "tool": "search_dotnet_metadata",
                                    "question_ids": ["question-light-pulse"],
                                }
                            ],
                            "initial_stop_condition": "Stop after exact IL verification.",
                            "initial_expand_condition": "Expand once only for a recorded blocker.",
                        },
                    }
                )
            if self.turn == 2:
                return json.dumps(
                    {
                        "action": "use_tool",
                        "tool": "search_dotnet_metadata",
                        "source_id": "controlled-assembly",
                        "family_id": "request-derived-light-pulse",
                        "derived_from_observation_ids": [],
                    }
                )
            serialized = json.dumps(messages)
            if self.turn == 3:
                marker = '"candidate_ref": "'
                start = serialized.index(marker) + len(marker)
                candidate_ref = serialized[start : serialized.index('"', start)]
                return json.dumps(
                    {
                        "action": "use_tool",
                        "tool": "inspect_method_il",
                        "source_id": "controlled-assembly",
                        "arguments": {"candidate_ref": candidate_ref},
                        "evidence_need": "Verify the observed method identity and IL body.",
                        "derived_from_observation_ids": ["obs-001"],
                    }
                )
            return json.dumps(
                {
                    "action": "finish",
                    "decision": "needs_more_evidence",
                    "evidence_conclusions": [
                        {
                            "claim": "Observed inspected symbol: Example.Plugin.PulseCorridorLights.",
                            "claim_status": "observed",
                            "observation_ids": ["obs-002"],
                            "limitations": [],
                            "requirement_ids": ["req-light-pulse"],
                            "relationship": "support",
                        }
                    ],
                    "unresolved_questions": ["Runtime event timing remains unverified."],
                    "missing_capabilities": [],
                }
            )

    actual_result = EvidenceDiscoverySpecialist(
        model=_ActualPathModel(),
        tool_executor=LocalAssemblyEvidenceToolExecutor.from_inspector(
            inspector / "bin" / "Debug" / "net7.0" / "r8_il_inspector.dll"
        ),
    ).discover(
        EvidenceDiscoveryRequest(
            run_id="controlled-real-metadata-il",
            request_id="controlled-light-pulse-request",
            natural_language_request=(
                "When an event completes, briefly pulse the corridor lights."
            ),
            sources=(
                evidence_discovery_source_from_definition(SourceDefinition(
                    source_id="controlled-assembly",
                    source_type="decompiled_api",
                    root_path=consumer_output,
                    allowed_extensions=frozenset({".dll"}),
                    metadata={
                        "evidence_discovery_kind": "controlled_managed_fixture",
                        "evidence_class": "current_controlled_assembly",
                        "evidence_authority": "authoritative",
                        "description": "Controlled managed assembly for the real discovery path.",
                        "allowed_tools": [
                            "search_dotnet_metadata",
                            "inspect_method_il",
                        ],
                        "assembly_relative_paths": ["Example.dll"],
                        "version_identity": {},
                    },
                )),
            ),
            max_tool_calls=3,
            max_model_steps=4,
            require_actual_planning=True,
        )
    )

    assert [action["tool"] for action in actual_result.actions] == [
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert actual_result.observations[0].data["methods"][0]["symbol"] == (
        "Example.Plugin.PulseCorridorLights"
    )
    assert len(actual_result.observations[0].data["methods"]) == 2
    assert actual_result.observations[1].data["candidate_ref"] == (
        actual_result.observations[0].data["methods"][0]["candidate_ref"]
    )
    assert actual_result.observations[1].data["metadata_token"] == (
        actual_result.observations[0].data["methods"][0]["metadata_token"]
    )
    assert actual_result.observations[1].data["has_method_body"] is True
    assert actual_result.pack.items[0].symbol == "Example.Plugin.PulseCorridorLights"
    source = actual_result.pack.items[0]
    assert source.source_authority == "authoritative"
    assert source.source_hash == actual_result.observations[1].data["assembly_sha256"]
    assert source.module_mvid == actual_result.observations[1].data["module_mvid"]
    assert source.metadata_token == actual_result.observations[1].data["metadata_token"]
    assert source.signature_blob
    semantics = actual_result.pack.hook_discovery
    assert semantics is not None
    assert semantics["source_admission"]["admitted_evidence_ids"] == [
        source.evidence_id
    ]
    relationship = semantics["evidence_relationships"][0]
    assert relationship["requirement_id"] == "req-light-pulse"
    assert relationship["engineering_question_ids"] == ["question-light-pulse"]
    assert relationship["query_family_ids"] == ["request-derived-light-pulse"]
    assert relationship["observation_ids"] == ["obs-002"]
    assert relationship["decisive_evidence_ids"] == [source.evidence_id]
    assert access["property_metadata_token"].startswith("0x17")
    assert access["getter_metadata_token"].startswith("0x06")
    assert report["target_code_executed"] is False
