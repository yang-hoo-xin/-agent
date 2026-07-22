import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.libs.llm import LLMFactory, OllamaLLM
from src.mod_agent.local_entry import (
    LOCAL_DIAGNOSTIC_CONTENT_FILENAME,
    LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES,
    CompiledArtifactInspectionProfile,
    LocalEntryError,
    NuGetIsolatedBuildExecution,
    _assert_no_absolute_local_paths,
    _assert_ollama_model_identity_stable,
    _build_run_local_il_inspector,
    _create_nuget_isolated_build_profile,
    _external_evidence_items,
    _local_model_admission_record,
    _local_no_external_disclosure_record,
    _persist_local_failure_diagnostics,
    _project_text_property,
    _read_ollama_server_version,
    _resolve_project_path_property,
    _run_nuget_isolated_build,
    _sanitized_endpoint_url,
    _select_ollama_model_identity,
    _source_disclosure_record,
    _verify_bepin_plugin_identity,
    _verify_exact_snapshot_change,
    _verify_source_disclosure,
    run_local_request,
)

_OLLAMA_DIGEST = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"


def _nuget_isolated_profile(tmp_path: Path):
    run_root = tmp_path / "run"
    project = run_root / "generated_mods" / "BetterHitFeedback"
    bepinex = run_root / "build_dependencies" / "BepInEx"
    project.mkdir(parents=True)
    bepinex.mkdir(parents=True)
    config = project / "nuget.config"
    config.write_text("<configuration />", encoding="utf-8")
    return _create_nuget_isolated_build_profile(
        run_root=run_root,
        working_directory=project,
        config_file=config,
        bepinex_dir=bepinex,
        timeout_seconds=120,
    )


def _ollama_identity(*, digest: str = _OLLAMA_DIGEST) -> dict[str, object]:
    return {
        "name": "qwen3:4b-instruct",
        "model": "qwen3:4b-instruct",
        "digest": digest,
        "modified_at": "2026-07-16T14:06:42.9800065+08:00",
        "size": 2497293803,
        "details": {
            "parameter_size": "4.0B",
            "quantization_level": "Q4_K_M",
        },
        "capabilities": ["completion", "tools"],
        "base_url": "http://127.0.0.1:11434",
    }


def test_nuget_isolated_profile_binds_explicit_run_local_inputs(
    tmp_path: Path,
) -> None:
    profile = _nuget_isolated_profile(tmp_path)

    assert profile.profile_id == "v2_codegen_real_local_dotnet_nuget_isolated"
    assert profile.restore_command == (
        "dotnet",
        "restore",
        "--configfile",
        str(profile.config_file),
        "--packages",
        str(profile.packages_path),
        f"-p:BepInExDir={profile.bepinex_dir}",
    )
    assert profile.build_command == (
        "dotnet",
        "build",
        "--no-restore",
        f"-p:BepInExDir={profile.bepinex_dir}",
    )
    assert profile.environment == {
        "NUGET_PACKAGES": str(profile.packages_path),
        "NUGET_HTTP_CACHE_PATH": str(profile.http_cache_path),
        "NUGET_SCRATCH": str(profile.scratch_path),
        "NUGET_PLUGINS_CACHE_PATH": str(profile.plugins_cache_path),
        "APPDATA": str(profile.appdata_path),
    }
    assert profile.timeout_seconds == 120
    assert profile.to_dict()["fully_hermetic_build_claimed"] is False
    for path in (
        profile.config_file,
        profile.packages_path,
        profile.http_cache_path,
        profile.scratch_path,
        profile.plugins_cache_path,
        profile.appdata_path,
        profile.user_config_file,
        profile.additional_user_config_path,
        profile.bepinex_dir,
    ):
        path.relative_to(profile.run_root)
    serialized = profile.to_dict()
    assert serialized["user_config_file"] == str(profile.user_config_file)
    assert serialized["user_config_source_sha256"] == hashlib.sha256(
        profile.config_file.read_bytes()
    ).hexdigest()


def test_nuget_isolated_runner_restores_then_builds_with_same_profile(
    tmp_path: Path,
) -> None:
    profile = _nuget_isolated_profile(tmp_path)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="restore ok" if command == profile.restore_command else "build ok",
            stderr="",
        )

    first = _run_nuget_isolated_build(profile, command_runner=run)
    second = _run_nuget_isolated_build(profile, command_runner=run)

    assert [item[0] for item in calls] == [
        profile.restore_command,
        profile.build_command,
        profile.restore_command,
        profile.build_command,
    ]
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.restore_exit_code == 0
    assert first.build_exit_code == 0
    for _, kwargs in calls:
        assert kwargs["cwd"] == profile.working_directory
        assert kwargs["timeout"] == 120
        assert kwargs["check"] is False
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        for key, value in profile.environment.items():
            assert environment[key] == value
    for path in profile.environment.values():
        assert Path(path).is_dir()
    assert profile.user_config_file.read_bytes() == profile.config_file.read_bytes()
    assert profile.additional_user_config_path.is_dir()


def test_nuget_isolated_runner_rejects_run_local_user_config_drift(
    tmp_path: Path,
) -> None:
    profile = _nuget_isolated_profile(tmp_path)
    profile.user_config_file.parent.mkdir(parents=True)
    profile.user_config_file.write_text(
        "<configuration><drift /></configuration>",
        encoding="utf-8",
    )

    with pytest.raises(LocalEntryError, match="user config does not match"):
        _run_nuget_isolated_build(profile, command_runner=MagicMock())


def test_nuget_isolated_runner_stops_when_restore_fails(tmp_path: Path) -> None:
    profile = _nuget_isolated_profile(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fail_restore(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="restore failed",
        )

    result = _run_nuget_isolated_build(profile, command_runner=fail_restore)

    assert calls == [profile.restore_command]
    assert result.exit_code == 1
    assert result.restore_exit_code == 1
    assert result.build_exit_code is None
    assert result.to_dict()["build_executed"] is False


def test_nuget_isolated_profile_rejects_paths_outside_run_root(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    project = tmp_path / "outside-project"
    config = project / "nuget.config"
    bepinex = run_root / "build_dependencies" / "BepInEx"
    project.mkdir()
    config.write_text("<configuration />", encoding="utf-8")
    bepinex.mkdir(parents=True)

    with pytest.raises(LocalEntryError, match="working_directory must remain"):
        _create_nuget_isolated_build_profile(
            run_root=run_root,
            working_directory=project,
            config_file=config,
            bepinex_dir=bepinex,
            timeout_seconds=120,
        )


def test_nuget_isolated_runner_propagates_timeout_fail_closed(
    tmp_path: Path,
) -> None:
    profile = _nuget_isolated_profile(tmp_path)

    def time_out(command, **_):
        raise subprocess.TimeoutExpired(command, timeout=120)

    with pytest.raises(subprocess.TimeoutExpired):
        _run_nuget_isolated_build(profile, command_runner=time_out)


def test_run_local_inspector_build_is_source_and_output_hash_bound(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "tracked-inspector"
    project_dir.mkdir()
    project = project_dir / "r8_il_inspector.csproj"
    project.write_text("<Project Sdk=\"Microsoft.NET.Sdk\" />", encoding="utf-8")
    (project_dir / "Program.cs").write_text(
        "internal static class Program { static void Main() {} }",
        encoding="utf-8",
    )
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "build":
            output = Path(command[command.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "r8_il_inspector.dll").write_bytes(b"compiled inspector")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = _build_run_local_il_inspector(
        CompiledArtifactInspectionProfile(
            project_path=project,
            method_symbol="Example.Plugin.Load",
            expected_guid="example.mod",
            expected_name="Example",
            expected_version="1.0.0",
        ),
        run_root=run_root,
        command_runner=run,
    )

    assert len(calls) == 2
    assert calls[0][0][0:2] == ("dotnet", "restore")
    assert calls[1][0][0:2] == ("dotnet", "build")
    assert "--no-restore" in calls[1][0]
    assert result["source_project_sha256"] == hashlib.sha256(
        project.read_bytes()
    ).hexdigest()
    assert result["inspector_sha256"] == hashlib.sha256(
        b"compiled inspector"
    ).hexdigest()
    assert result["fully_hermetic_build_claimed"] is False
    for _, kwargs in calls:
        environment = kwargs["env"]
        for name in (
            "NUGET_PACKAGES",
            "NUGET_HTTP_CACHE_PATH",
            "NUGET_SCRATCH",
            "NUGET_PLUGINS_CACHE_PATH",
            "APPDATA",
        ):
            Path(environment[name]).resolve().relative_to(run_root.resolve())
    record = json.loads(
        (
            run_root
            / "verification_tools"
            / "r8_il_inspector"
            / "verification_tool_build.json"
        ).read_text(encoding="utf-8")
    )
    assert record == result


def test_run_local_inspector_build_records_restore_failure_without_build(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "tracked-inspector"
    project_dir.mkdir()
    project = project_dir / "r8_il_inspector.csproj"
    project.write_text("<Project Sdk=\"Microsoft.NET.Sdk\" />", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    calls: list[tuple[str, ...]] = []

    def fail_restore(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, 7, stdout="", stderr="failed")

    with pytest.raises(LocalEntryError, match="restore failed with exit code 7"):
        _build_run_local_il_inspector(
            CompiledArtifactInspectionProfile(
                project_path=project,
                method_symbol="Example.Plugin.Load",
                expected_guid="example.mod",
                expected_name="Example",
                expected_version="1.0.0",
            ),
            run_root=run_root,
            command_runner=fail_restore,
        )

    assert len(calls) == 1
    record = json.loads(
        (
            run_root
            / "verification_tools"
            / "r8_il_inspector"
            / "verification_tool_build.json"
        ).read_text(encoding="utf-8")
    )
    assert record["restore_exit_code"] == 7
    assert record["build_exit_code"] is None
    assert record["inspector_exists"] is False


def test_resolve_project_path_property_uses_project_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "generated_mods" / "BetterHitFeedback"
    project_dir.mkdir(parents=True)
    expected = tmp_path / "local_refs" / "gtfo_r8" / "BepInEx"
    expected.mkdir(parents=True)
    project_file = project_dir / "BetterHitFeedback.csproj"
    project_file.write_text(
        "<Project><PropertyGroup>"
        "<BepInExDir>..\\..\\local_refs\\gtfo_r8\\BepInEx</BepInExDir>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )

    resolved = _resolve_project_path_property(
        project_file,
        property_name="BepInExDir",
    )

    assert resolved == expected.resolve()


def test_resolve_project_path_property_rejects_missing_property(tmp_path: Path) -> None:
    project_file = tmp_path / "Target.csproj"
    project_file.write_text("<Project />", encoding="utf-8")

    with pytest.raises(LocalEntryError, match="does not define BepInExDir"):
        _resolve_project_path_property(project_file, property_name="BepInExDir")


def _local_run_test_target(tmp_path: Path) -> Path:
    source = tmp_path / "canonical" / "BetterHitFeedback"
    source.mkdir(parents=True)
    bepinex = tmp_path / "references" / "BepInEx"
    bepinex.mkdir(parents=True)
    (source / "BetterHitFeedback.csproj").write_text(
        "<Project><PropertyGroup>"
        "<AssemblyName>BetterHitFeedback</AssemblyName>"
        f"<BepInExDir>{bepinex}</BepInExDir>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )
    (source / "Plugin.cs").write_text(
        "namespace BetterHitFeedback; public sealed class Plugin {}\n",
        encoding="utf-8",
    )
    (source / "nuget.config").write_text(
        "<configuration />",
        encoding="utf-8",
    )
    return source


def _install_local_ollama_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    def create(settings, **kwargs):
        return OllamaLLM(settings, **kwargs)

    monkeypatch.setattr(LLMFactory, "create", staticmethod(create))


def test_pre_graph_verifier_failure_persists_terminal_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _local_run_test_target(tmp_path)
    workspace = tmp_path / "runs"
    _install_local_ollama_factory(monkeypatch)
    inspector_project = tmp_path / "tracked-inspector" / "r8_il_inspector.csproj"
    inspector_project.parent.mkdir()
    inspector_project.write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\" />",
        encoding="utf-8",
    )

    def build(profile):
        artifact = profile.working_directory / "bin" / "Debug" / "BetterHitFeedback.dll"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"baseline")
        return NuGetIsolatedBuildExecution(
            restore_exit_code=0,
            build_exit_code=0,
            restore_stdout="restore ok",
            restore_stderr="",
            build_stdout="build ok",
            build_stderr="",
            duration_ms=12,
        )

    monkeypatch.setattr("src.mod_agent.local_entry._run_nuget_isolated_build", build)

    def build_inspector(_profile, *, run_root, **_):
        inspector = run_root / "verification_tools" / "r8_il_inspector.dll"
        inspector.parent.mkdir(parents=True)
        inspector.write_bytes(b"inspector")
        return {
            "inspector_path": str(inspector),
            "inspector_sha256": hashlib.sha256(b"inspector").hexdigest(),
        }

    monkeypatch.setattr(
        "src.mod_agent.local_entry._build_run_local_il_inspector",
        build_inspector,
    )

    def fail_verification(_artifact: Path, *, inspector_path: Path, **_) -> dict[str, object]:
        assert inspector_path.read_bytes() == b"inspector"
        raise LocalEntryError("compiled identity mismatch")

    monkeypatch.setattr(
        "src.mod_agent.local_entry._verify_bepin_plugin_identity",
        fail_verification,
    )

    with pytest.raises(LocalEntryError, match="compiled identity mismatch"):
        run_local_request(
            description="make General.Enabled control startup patch registration",
            target_project=source,
            workspace_base=workspace,
            settings_path=Path("config/settings.yaml"),
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
            compiled_artifact_inspection_profile=CompiledArtifactInspectionProfile(
                project_path=inspector_project,
                method_symbol="BetterHitFeedback.Plugin.Load",
                expected_guid="local.betterhitfeedback",
                expected_name="BetterHitFeedback",
                expected_version="0.1.0",
            ),
            local_ollama=True,
            ollama_model="qwen3:4b-instruct",
            ollama_model_identity_reader=lambda *_: _ollama_identity(),
            ollama_server_version_reader=lambda *_: "0.32.1",
        )

    run_root = next(path for path in workspace.iterdir() if path.is_dir())
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    failure_path = run_root / "run_failure.json"
    failure_bytes = failure_path.read_bytes()
    failure = json.loads(failure_bytes)
    assert manifest["run_id"] == failure["run_id"]
    assert manifest["request_id"] == failure["request_id"]
    assert manifest["status"] == "failed"
    assert manifest["terminal_failure_stage"] == "baseline_artifact_verification"
    assert manifest["terminal_record"] == {
        "path": str(failure_path),
        "sha256": hashlib.sha256(failure_bytes).hexdigest(),
    }
    assert failure["failure_stage"] == "baseline_artifact_verification"
    assert failure["model_call_count"] == 0
    assert failure["graph_invoked"] is False
    assert failure["patch_payload_parser_entered"] is False
    assert failure["actual_write_performed"] is False
    assert failure["baseline_build"]["artifact_exists"] is True
    assert failure["verification_tool_build"]["inspector_sha256"] == hashlib.sha256(
        b"inspector"
    ).hexdigest()
    assert not (run_root / "a").exists()
    assert (source / "Plugin.cs").read_text(encoding="utf-8").endswith("{}\n")


def test_pre_graph_restore_failure_records_exact_stage_and_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _local_run_test_target(tmp_path)
    workspace = tmp_path / "runs"
    _install_local_ollama_factory(monkeypatch)

    def fail_restore(_profile):
        return NuGetIsolatedBuildExecution(
            restore_exit_code=9,
            build_exit_code=None,
            restore_stdout="",
            restore_stderr="restore failed",
            build_stdout="",
            build_stderr="",
            duration_ms=4,
        )

    monkeypatch.setattr(
        "src.mod_agent.local_entry._run_nuget_isolated_build",
        fail_restore,
    )

    with pytest.raises(LocalEntryError, match="baseline build failed"):
        run_local_request(
            description="make General.Enabled control startup patch registration",
            target_project=source,
            workspace_base=workspace,
            settings_path=Path("config/settings.yaml"),
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
            local_ollama=True,
            ollama_model="qwen3:4b-instruct",
            ollama_model_identity_reader=lambda *_: _ollama_identity(),
            ollama_server_version_reader=lambda *_: "0.32.1",
        )

    run_root = next(path for path in workspace.iterdir() if path.is_dir())
    failure = json.loads((run_root / "run_failure.json").read_text(encoding="utf-8"))
    assert failure["failure_stage"] == "baseline_restore"
    assert failure["baseline_build"]["restore_exit_code"] == 9
    assert failure["baseline_build"]["build_executed"] is False
    assert failure["model_call_count"] == 0
    assert failure["graph_invoked"] is False
    assert not (run_root / "a").exists()


def test_run_request_blocks_source_access_without_explicit_disclosure_consent(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "runs"

    with pytest.raises(LocalEntryError, match="--allow-source-disclosure"):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=workspace,
            settings_path=tmp_path / "missing-settings.yaml",
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
        )

    assert not workspace.exists()


def test_local_run_selects_ollama_without_api_key_or_external_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def create(settings, **kwargs):
        captured["settings"] = settings
        captured["kwargs"] = kwargs
        llm = OllamaLLM(settings, **kwargs)
        captured["llm"] = llm
        return llm

    monkeypatch.setattr(LLMFactory, "create", staticmethod(create))
    monkeypatch.delenv("LOCAL_OLLAMA_UNUSED_API_KEY", raising=False)

    with pytest.raises(LocalEntryError, match="Target project"):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=tmp_path / "runs",
            settings_path=Path("config/settings.yaml"),
            api_key_env="LOCAL_OLLAMA_UNUSED_API_KEY",
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
            local_ollama=True,
            ollama_base_url="http://127.0.0.1:11434",
            ollama_model="qwen3:4b-instruct",
            ollama_max_output_tokens=3072,
            ollama_model_identity_reader=lambda *_: _ollama_identity(),
            ollama_server_version_reader=lambda *_: "0.32.1",
        )

    settings = captured["settings"]
    assert settings.llm.provider == "ollama"
    assert settings.llm.model == "qwen3:4b-instruct"
    assert settings.llm.max_tokens == 3072
    assert isinstance(captured["llm"], OllamaLLM)
    assert captured["kwargs"] == {"base_url": "http://127.0.0.1:11434"}
    assert not (tmp_path / "runs").exists()


def test_local_run_rejects_external_disclosure_boundary_mix(
    tmp_path: Path,
) -> None:
    with pytest.raises(LocalEntryError, match="exactly one model boundary"):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=tmp_path / "runs",
            settings_path=tmp_path / "missing-settings.yaml",
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=True,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
            local_ollama=True,
            ollama_model="qwen3:4b-instruct",
        )

    assert not (tmp_path / "runs").exists()


def test_local_run_requires_exact_model_without_inference(tmp_path: Path) -> None:
    with pytest.raises(LocalEntryError, match="exact --ollama-model"):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=tmp_path / "runs",
            settings_path=Path("config/settings.yaml"),
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
            local_ollama=True,
            ollama_model=None,
        )


def test_local_run_rejects_non_literal_loopback_before_catalog_read(
    tmp_path: Path,
) -> None:
    catalog_read = False

    def read_identity(*_):
        nonlocal catalog_read
        catalog_read = True
        return _ollama_identity()

    with pytest.raises(
        LocalEntryError,
        match="LOCAL_AGENT_ENDPOINT_MUST_BE_LITERAL_LOOPBACK_HTTP_ORIGIN",
    ):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=tmp_path / "runs",
            settings_path=Path("config/settings.yaml"),
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
            local_ollama=True,
            ollama_base_url="http://192.168.1.9:11434",
            ollama_model="qwen3:4b-instruct",
            ollama_model_identity_reader=read_identity,
        )

    assert catalog_read is False


def test_local_provider_initialization_failure_has_no_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fail(settings, **kwargs):
        calls.append(settings.llm.provider)
        raise RuntimeError("local provider unavailable")

    monkeypatch.setattr(LLMFactory, "create", staticmethod(fail))

    with pytest.raises(LocalEntryError, match="Local Ollama initialization failed"):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=tmp_path / "runs",
            settings_path=Path("config/settings.yaml"),
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
            local_ollama=True,
            ollama_model="qwen3:4b-instruct",
            ollama_model_identity_reader=lambda *_: _ollama_identity(),
            ollama_server_version_reader=lambda *_: "0.32.1",
        )

    assert calls == ["ollama"]


def test_read_ollama_server_version_uses_literal_local_transport_profile() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"version": "0.32.1"}

    with patch("httpx.Client") as client:
        client.return_value.__enter__.return_value.get.return_value = response
        version = _read_ollama_server_version("http://127.0.0.1:11434")

    assert version == "0.32.1"
    client.assert_called_once_with(
        timeout=10.0,
        trust_env=False,
        follow_redirects=False,
    )
    client.return_value.__enter__.return_value.get.assert_called_once_with(
        "http://127.0.0.1:11434/api/version"
    )


def test_local_failure_content_is_preserved_exactly_within_policy_limit(
    tmp_path: Path,
) -> None:
    content = "Patch failure 内容\r\n"
    error = LocalEntryError("patch failed")
    error.diagnostic_content = content
    error.diagnostics = {
        "failure_classification": "malformed_structured_output",
        "message_content": content,
    }

    diagnostics = _persist_local_failure_diagnostics(
        run_root=tmp_path,
        error=error,
        enabled=True,
    )

    assert diagnostics is not None
    retention = diagnostics["diagnostic_content"]
    assert retention["max_utf8_bytes"] == 262_144
    assert retention["utf8_bytes"] == len(content.encode("utf-8"))
    assert retention["retained"] is True
    assert "message_content" not in diagnostics
    assert (tmp_path / LOCAL_DIAGNOSTIC_CONTENT_FILENAME).read_bytes() == content.encode(
        "utf-8"
    )


def test_local_failure_content_over_policy_limit_is_not_written_or_truncated(
    tmp_path: Path,
) -> None:
    content = "界" * ((LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES // 3) + 1)
    error = LocalEntryError("patch failed")
    error.diagnostic_content = content

    diagnostics = _persist_local_failure_diagnostics(
        run_root=tmp_path,
        error=error,
        enabled=True,
    )

    assert diagnostics is not None
    retention = diagnostics["diagnostic_content"]
    assert retention["utf8_bytes"] > LOCAL_DIAGNOSTIC_CONTENT_MAX_BYTES
    assert retention["retained"] is False
    assert retention["path"] is None
    assert retention["not_retained_reason"] == "policy_limit_exceeded"
    assert diagnostics["diagnostic_sufficiency"] == "reduced"
    assert not (tmp_path / LOCAL_DIAGNOSTIC_CONTENT_FILENAME).exists()


def test_external_run_still_requires_api_key_after_disclosure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_EXTERNAL_KEY", raising=False)

    with pytest.raises(LocalEntryError, match="MISSING_EXTERNAL_KEY"):
        run_local_request(
            description="change a local source file",
            target_project=tmp_path / "missing-target",
            workspace_base=tmp_path / "runs",
            settings_path=Path("config/settings.yaml"),
            api_key_env="MISSING_EXTERNAL_KEY",
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=True,
            diff_approval_reader=lambda dry_run: str(dry_run["diff_hash"]),
        )


def test_source_disclosure_record_is_explicit_and_does_not_contain_api_key() -> None:
    record = _source_disclosure_record(
        provider="openai",
        model="qwen3.6-plus",
        base_url="https://example.invalid/compatible-mode/v1",
        approved_at="2026-07-12T00:00:00+00:00",
    )

    assert record == {
        "approved": True,
        "approved_at": "2026-07-12T00:00:00+00:00",
        "approval_id": None,
        "approval_actor_type": "local_cli_invoker",
        "consent_mechanism": "--allow-source-disclosure",
        "provider_adapter": None,
        "destination": {
            "provider": "openai",
            "model": "qwen3.6-plus",
            "base_url": "https://example.invalid/compatible-mode/v1",
            "request_url": None,
        },
        "approved_data_classes": [
            "natural_language_request",
            "retrieved_local_source_excerpts",
            "binding_registry",
            "side_effect_boundaries",
        ],
        "requested_data_classes": [
            "natural_language_request",
            "retrieved_local_source_excerpts",
            "binding_registry",
            "side_effect_boundaries",
        ],
        "scope": "this_run_only",
    }
    assert "api_key" not in str(record).lower()


def test_local_admission_records_local_execution_without_external_disclosure() -> None:
    no_disclosure = _local_no_external_disclosure_record()
    admission = _local_model_admission_record(
        model_identity=_ollama_identity(),
        provider_adapter="src.libs.llm.ollama_llm.OllamaLLM",
    )

    assert no_disclosure["occurred"] is False
    assert no_disclosure["approved"] is False
    assert no_disclosure["approved_data_classes"] == []
    assert admission == {
        "provider": "ollama",
        "model": "qwen3:4b-instruct",
        "model_digest": _OLLAMA_DIGEST,
        "provider_adapter": "src.libs.llm.ollama_llm.OllamaLLM",
        "execution_locality": "local",
        "base_url": "http://127.0.0.1:11434",
        "destination": "http://127.0.0.1:11434/api/chat",
        "external_disclosure_occurred": False,
        "api_key_required": False,
        "api_key_read": False,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "machine_local",
    }


def test_ollama_catalog_binds_one_exact_model_identity() -> None:
    identity = _select_ollama_model_identity(
        {
            "models": [
                {
                    "name": "qwen3:4b-instruct",
                    "model": "qwen3:4b-instruct",
                    "digest": _OLLAMA_DIGEST,
                    "modified_at": "2026-07-16T14:06:42.9800065+08:00",
                    "size": 2497293803,
                    "details": {
                        "parameter_size": "4.0B",
                        "quantization_level": "Q4_K_M",
                    },
                    "capabilities": ["completion", "tools"],
                }
            ]
        },
        base_url="http://127.0.0.1:11434",
        expected_model="qwen3:4b-instruct",
    )

    assert identity == _ollama_identity()


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ({"models": []}, "OLLAMA_MODEL_LIST_EMPTY"),
        (
            {
                "models": [
                    {
                        "name": "another-model",
                        "model": "another-model",
                        "digest": "1" * 64,
                        "details": {},
                        "capabilities": ["completion"],
                    }
                ]
            },
            "OLLAMA_MODEL_NOT_EXACTLY_PRESENT",
        ),
    ),
)
def test_ollama_catalog_fails_closed_without_exact_model(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(LocalEntryError, match=message):
        _select_ollama_model_identity(
            payload,
            base_url="http://127.0.0.1:11434",
            expected_model="qwen3:4b-instruct",
        )


def test_ollama_model_digest_drift_fails_closed() -> None:
    with pytest.raises(LocalEntryError, match="OLLAMA_MODEL_DIGEST_DRIFT"):
        _assert_ollama_model_identity_stable(
            expected=_ollama_identity(),
            observed=_ollama_identity(digest="1" * 64),
        )


def test_external_evidence_replaces_absolute_source_ref() -> None:
    sanitized = _external_evidence_items(
        [
            {
                "evidence_id": "evidence_001",
                "source_type": "target_source",
                "source_path": "generated_mods/BetterHitFeedback/Plugin.cs",
                "source_ref": r"C:\private\Plugin.cs",
                "excerpt": 'public const string VERSION = "0.1.0";',
            }
        ]
    )

    assert sanitized[0]["source_ref"] == (
        "source://target_source/generated_mods/BetterHitFeedback/Plugin.cs"
    )
    _assert_no_absolute_local_paths(sanitized)


def test_external_payload_rejects_absolute_local_path() -> None:
    with pytest.raises(LocalEntryError, match="absolute local path"):
        _assert_no_absolute_local_paths({"source_ref": r"C:\private\Plugin.cs"})


def test_exact_snapshot_change_requires_only_bound_file() -> None:
    before = [
        {"path": "Plugin.cs", "sha256": "before", "size": 10},
        {"path": "Other.cs", "sha256": "same", "size": 20},
    ]
    after = [
        {"path": "Plugin.cs", "sha256": "after", "size": 10},
        {"path": "Other.cs", "sha256": "same", "size": 20},
    ]

    result = _verify_exact_snapshot_change(
        before,
        after,
        relative_path="Plugin.cs",
        before_sha256="before",
        after_sha256="after",
    )

    assert result["status"] == "passed"
    assert result["changed_paths"] == ["Plugin.cs"]


def test_bepin_plugin_identity_reads_compiled_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "BetterHitFeedback.dll"
    artifact.write_bytes(b"compiled")
    inspector = tmp_path / "r8_il_inspector.dll"
    inspector.write_bytes(b"inspector")

    class Completed:
        returncode = 0
        stderr = ""
        stdout = (
            '{"schema_version":"r8_il_inspection_v1","methods":['
            '{"symbol":"BetterHitFeedback.Plugin.Load",'
            '"declaring_type_custom_attributes":['
            '{"constructor":"BepInEx.BepInPlugin..ctor",'
            '"printable_ascii_runs":["local.betterhitfeedback",'
            '"BetterHitFeedback","0.1.0"]}]}],'
            '"target_code_executed":false}'
        )

    monkeypatch.setattr("src.mod_agent.local_entry.subprocess.run", lambda *_, **__: Completed())

    result = _verify_bepin_plugin_identity(
        artifact,
        inspector_path=inspector,
        method_symbol="BetterHitFeedback.Plugin.Load",
        expected_guid="local.betterhitfeedback",
        expected_name="BetterHitFeedback",
        expected_version="0.1.0",
    )

    assert result["status"] == "passed"
    assert result["bepin_plugin"]["version"] == "0.1.0"
    assert result["target_code_executed"] is False


def test_source_disclosure_blocks_unapproved_new_data_class() -> None:
    record = _source_disclosure_record(
        provider="openai",
        model="qwen3.6-plus",
        base_url="https://example.invalid/compatible-mode/v1",
        approved_at="2026-07-12T00:00:00+00:00",
    )

    with pytest.raises(LocalEntryError, match="runtime_logs"):
        _verify_source_disclosure(
            record,
            requested_data_classes=("retrieved_local_source_excerpts", "runtime_logs"),
        )


def test_endpoint_metadata_strips_userinfo_query_and_fragment() -> None:
    sanitized = _sanitized_endpoint_url(
        "https://local-key@example.invalid/compatible/v1?token=secret#fragment"
    )

    assert sanitized == "https://example.invalid/compatible/v1"
    assert "local-key" not in sanitized
    assert "secret" not in sanitized


def test_project_text_property_reads_non_better_hit_feedback_assembly(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "AnotherMod.csproj"
    project_file.write_text(
        "<Project><PropertyGroup><AssemblyName>AnotherMod</AssemblyName>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )

    assert (
        _project_text_property(project_file, property_name="AssemblyName")
        == "AnotherMod"
    )
