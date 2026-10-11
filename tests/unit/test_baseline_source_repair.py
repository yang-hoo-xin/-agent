"""Broken incoming source reaches the normal workflow with observed diagnostics."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from src.mod_agent import local_entry
from src.mod_agent.build.baseline_repair import classify_source_compilation_failure
from src.mod_agent.build.baseline_repair import validated_baseline_repair_observation
from tests.unit.test_dsh_run_request import _call, _install_execution_boundaries
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401


@pytest.mark.parametrize("failure", ["source", "restore", "msbuild", "mixed", "bare-mixed", "outside", "drift", "generated", "global"])
def test_only_bound_source_compiler_errors_are_repairable(tmp_path, failure):
    root = tmp_path / "project"
    root.mkdir()
    path = root / "Plugin.cs"
    path.write_text("class Plugin { MissingType field; }", encoding="utf-8")
    expected = {"Plugin.cs": hashlib.sha256(path.read_bytes()).hexdigest()}
    execution = {"restore_exit_code": 0, "build_exit_code": 1}
    output = f"{path}(1,16): error CS0246: MissingType was not found [{root / 'Mod.csproj'}]"
    if failure == "restore":
        execution["restore_exit_code"] = 1
    elif failure == "msbuild":
        output = "error MSB0001: build tools failed"
    elif failure in {"mixed", "bare-mixed"}:
        output += "\n" + ("tool: " if failure == "mixed" else "") + "error MSB0001: build tools failed"
    elif failure == "outside":
        output = output.replace(str(path), str(tmp_path / "Other.cs"))
    elif failure == "drift":
        path.write_text("changed", encoding="utf-8")
    elif failure == "generated":
        generated = root / "obj" / "Generated.cs"
        generated.parent.mkdir()
        generated.write_bytes(path.read_bytes())
        expected["obj/Generated.cs"] = expected["Plugin.cs"]
        output = output.replace(str(path), str(generated))
    elif failure == "global":
        output += "\nCSC : error CS0006: Missing dependency"
    observed = classify_source_compilation_failure(execution=execution, output=output,
        project_root=root, expected_sources=expected)
    if failure == "source":
        assert len(observed) == 1
        assert observed[0]["file"] == "Plugin.cs"
        assert observed[0]["source_sha256"] == expected["Plugin.cs"]
        assert str(root) not in observed[0]["message"]
    else:
        assert observed == ()


def test_broken_source_enters_normal_graph_with_diagnostics_at_every_model_stage(
    execution_config, monkeypatch, capsys,
):
    target, roles, builds = _install_execution_boundaries(execution_config.parent, monkeypatch)
    source = target / "Plugin.cs"
    source.write_text("namespace Example; public sealed class Plugin { MissingType field; public void Load() {} }\n",
                      encoding="utf-8")
    original = source.read_bytes()
    transport = httpx.HTTPTransport.handle_request
    observed = []

    def recording_transport(self, request):
        if request.method == "POST" and request.url.path == "/api/chat":
            body = json.loads(request.content)
            user = json.loads(next(row["content"] for row in body["messages"] if row["role"] == "user"))
            if "patch_agent_context_encoding" in user:
                user = local_entry._restore_patch_agent_context(user)
            observed.append(user)
        return transport(self, request)

    def failed_compiler(profile):
        builds.append(profile)
        artifact = profile.working_directory / "bin/Debug/Example.dll"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"stale DLL is not a successful baseline")
        return local_entry.NuGetIsolatedBuildExecution(
            restore_exit_code=0, build_exit_code=1, restore_stdout="restore ok", restore_stderr="",
            build_stdout=f"{profile.working_directory / 'Plugin.cs'}(1,49): error CS0246: MissingType was not found",
            build_stderr="", duration_ms=1)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", recording_transport)
    monkeypatch.setattr(local_entry, "_run_nuget_isolated_build", failed_compiler)
    request = "修复 Load 所在 Mod 的编译错误，保留现有功能。"
    code = _call(execution_config, request, monkeypatch)
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert result["status"] == "awaiting_approval"
    assert roles == ["product_requirement_projection", "product_requirement_findings", "planning", "patch"]
    assert len(observed) == 4
    for payload in observed:
        diagnostic = payload["baseline_compilation_failure"]["diagnostics"][0]
        assert diagnostic["file"] == "generated_mods/Example/Plugin.cs"
        assert diagnostic["code"] == "CS0246"
        assert "error_class" not in diagnostic
        assert diagnostic["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert observed[0]["request"] == request
    assert len(builds) == 1
    assert source.read_bytes() == original
    assert result["actual_write_performed"] is False
    root = Path(result["run_root"])
    manifest = json.loads((root / "run_manifest.json").read_bytes())
    baseline = manifest["baseline_build"]
    assert baseline["build_exit_code"] == 1 and baseline["artifact_usable"] is False
    assert baseline["stdout_sha256"] == hashlib.sha256(Path(baseline["stdout_path"]).read_bytes()).hexdigest()
    legacy = deepcopy(manifest)
    prior_view = legacy["baseline_build"]["repair_observation"]
    prior_view["interpretation"] = "The original recorded diagnostic guidance."
    prior_view["diagnostics"][0]["error_class"] = "missing_reference"
    assert validated_baseline_repair_observation(legacy, root) == prior_view
    for key, value in (("line", 999), ("code", "CS9999"), ("message", "fabricated"), ("error_class", "fabricated")):
        damaged = deepcopy(legacy)
        damaged["baseline_build"]["repair_observation"]["diagnostics"][0][key] = value
        with pytest.raises(ValueError, match="BASELINE_CHANGED"):
            validated_baseline_repair_observation(damaged, root)
    evidence = [json.loads(p.read_bytes()) for p in (root / "a").rglob("*.json")]
    assert any(row.get("artifact_type") == "evidence_pack"
               and row["data"]["budget_summary"].get("baseline_compilation_failure") for row in evidence)
