from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


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
    assert access["property_metadata_token"].startswith("0x17")
    assert access["getter_metadata_token"].startswith("0x06")
    assert report["target_code_executed"] is False
