"""Fixed C# worker boundaries; real Docker calibration is explicitly selected."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.evaluation import restricted_csharp as worker


def _prepared_compilation(tmp_path):
    root = tmp_path / "prepared"
    assembly = root / "compiler-output"
    assembly.mkdir(parents=True)
    (assembly / "Subject.dll").write_bytes(b"approved compilation bytes")
    (assembly / "Subject.runtimeconfig.json").write_bytes(b"{}")
    binary = worker._ref(assembly / "Subject.dll")
    config = worker._ref(assembly / "Subject.runtimeconfig.json")
    receipt = worker._save(root / "compilation.json", {
        "schema_version": "restricted_csharp_compilation_v1", "sdk_version": worker.SDK_VERSION,
        "runtime_version": worker.RUNTIME_VERSION, "image": worker.IMAGE,
        "succeeded": True, "binary_ref": binary, "runtimeconfig_ref": config})
    return worker.CSharpCompilation(str(root), True, binary, config, receipt)


def test_verified_bytes_are_the_only_bytes_published_for_execution(tmp_path, monkeypatch):
    compilation = _prepared_compilation(tmp_path)
    binary = Path(compilation.binary_ref["path"])
    read_bytes = Path.read_bytes
    changed = False
    executed = []

    def change_after_verified_read(path):
        nonlocal changed
        value = read_bytes(path)
        if path == binary and not changed:
            changed = True
            path.write_bytes(b"changed after reference verification")
        return value

    def execute(root, *, mounts, **_kwargs):
        actual = (mounts["/assembly"][0] / "Subject.dll").read_bytes()
        assert worker._hash(actual) == compilation.binary_ref["sha256"]
        executed.append(actual)
        return {"completed": True, "exit_code": 0, "container_state": {"ExitCode": 0}}

    monkeypatch.setattr(Path, "read_bytes", change_after_verified_read)
    monkeypatch.setattr(worker, "_execute", execute)
    worker.run_csharp(compilation=compilation, operation={}, output_root=tmp_path / "run")
    assert changed and executed == [b"approved compilation bytes"]


@pytest.mark.parametrize("cause", ["timeout", "overflow"])
def test_attach_reaps_its_real_child_when_stop_callback_raises(monkeypatch, cause):
    children = []
    actual_popen = subprocess.Popen
    failure = RuntimeError("injected stop failure")

    def capture(*args, **kwargs):
        child = actual_popen(*args, **kwargs)
        children.append(child)
        return child

    def stop():
        raise failure

    monkeypatch.setattr(worker.subprocess, "Popen", capture)
    child_code = "import time; time.sleep(30)"
    if cause == "overflow":
        child_code = "import sys,time; sys.stdout.write('x'*2097152); sys.stdout.flush(); time.sleep(30)"
    try:
        with pytest.raises(RuntimeError, match="injected stop failure") as raised:
            worker._attach([sys.executable, "-B", "-c", child_code],
                stdin=b"", timeout=0.05 if cause == "timeout" else 5, stop=stop)
        assert raised.value is failure
        assert children[0].poll() is not None
        assert failure.attach_execution["local_process_reaped"] is True
        assert failure.attach_execution["local_cleanup_errors"] == []
        assert len(failure.attach_execution["stdout"].encode()) <= worker.OUTPUT_LIMIT
        assert failure.attach_execution["output_limit_exceeded"] is (cause == "overflow")
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


def test_compiler_rejects_source_staging_drift_before_execution(tmp_path, monkeypatch):
    write_bytes = Path.write_bytes

    def corrupt_staged_source(path, value):
        if path.name == "Worker.cs" and path.parent.name == "public-input":
            return write_bytes(path, b"changed during staging")
        return write_bytes(path, value)

    monkeypatch.setattr(Path, "write_bytes", corrupt_staged_source)
    monkeypatch.setattr(worker, "_execute", lambda *_args, **_kwargs: pytest.fail("Drift reached compiler"))
    with pytest.raises(ValueError, match="INPUT_STAGING_CHANGED"):
        worker.compile_csharp(sources={"Worker.cs": b"approved source"}, output_root=tmp_path / "compile")


def test_compiler_rejects_binary_drift_during_receipt_publication(tmp_path, monkeypatch):
    binary = tmp_path / "compile/compiler-output/Subject.dll"
    read_bytes = Path.read_bytes
    changed = False

    def execute(root, **_kwargs):
        binary.write_bytes(b"compiled original")
        result = {"completed": True, "exit_code": 0, "container_state": {"ExitCode": 0}}
        worker._save(root / "execution.json", result)
        return result

    def change_after_snapshot(path):
        nonlocal changed
        value = read_bytes(path)
        if path == binary and not changed:
            changed = True
            path.write_bytes(b"changed during receipt publication")
        return value

    monkeypatch.setattr(worker, "_execute", execute)
    monkeypatch.setattr(Path, "read_bytes", change_after_snapshot)
    with pytest.raises(ValueError, match="BINARY_CHANGED"):
        worker.compile_csharp(sources={"Worker.cs": b"approved source"}, output_root=tmp_path / "compile")
    assert changed


def test_runtime_rejects_assembly_staging_drift_before_container(tmp_path, monkeypatch):
    compilation = _prepared_compilation(tmp_path)
    write_bytes = Path.write_bytes

    def corrupt_staged_assembly(path, value):
        if path.name == "Subject.dll" and path.parent.name == "public-assembly":
            return write_bytes(path, b"corrupted during publication")
        return write_bytes(path, value)

    monkeypatch.setattr(Path, "write_bytes", corrupt_staged_assembly)
    monkeypatch.setattr(worker, "_execute", lambda *_args, **_kwargs: pytest.fail("Drift reached runtime"))
    with pytest.raises(ValueError, match="ASSEMBLY_STAGING_CHANGED"):
        worker.run_csharp(compilation=compilation, operation={}, output_root=tmp_path / "run")


@pytest.mark.parametrize("name", ["../secret.cs", "/secret.cs", "x\\secret.cs", "x\n.cs",
                                  "-@options.rsp", "x.csproj", "a/../b.cs"])
def test_source_names_cannot_supply_commands_or_escape_input(name, tmp_path):
    with pytest.raises(ValueError, match="SOURCE_PATH_INVALID"):
        worker.compile_csharp(sources={name: b"public class Example {}"}, output_root=tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_windows_source_collision_and_source_limit_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="SOURCE_PATH_COLLISION"):
        worker.compile_csharp(sources={"A.cs": b"a", "a.cs": b"b"}, output_root=tmp_path / "collision")
    with pytest.raises(ValueError, match="SOURCE_LIMIT"):
        worker.compile_csharp(sources={"A.cs": b"a" * (worker.SOURCE_LIMIT + 1)}, output_root=tmp_path / "oversize")
    assert not (tmp_path / "collision").exists() and not (tmp_path / "oversize").exists()


def _inspect_document(tmp_path):
    mounts = {"/assembly": (tmp_path, True)}
    document = {"Config": {"Image": worker.IMAGE, "User": "65534:65534",
        "Entrypoint": ["dotnet"], "Cmd": ["/assembly/Subject.dll"],
        "Labels": {"codex.restricted-csharp": "token"}, "Env": list(worker._ENV)},
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
            "CapDrop": ["ALL"], "CapAdd": None, "SecurityOpt": ["no-new-privileges"],
            "PidsLimit": 64, "Memory": 1_073_741_824, "MemorySwap": 1_073_741_824,
            "NanoCpus": 1_000_000_000, "Tmpfs": {
                "/tmp": "rw,nosuid,nodev,noexec,size=64m",
                "/operation-output": "rw,nosuid,nodev,noexec,size=64m"},
            "Init": True, "Devices": None, "VolumesFrom": None, "PidMode": "",
            "LogConfig": {"Type": "none"}},
        "Mounts": [{"Type": "bind", "Destination": "/assembly", "Source": str(tmp_path), "RW": False}]}
    return document, mounts


@pytest.mark.parametrize("scope, key, value", [
    ("Config", "User", "0"), ("Config", "Image", "sdk:latest"),
    ("Config", "Cmd", ["/assembly/Subject.dll", "extra"]),
    ("HostConfig", "NetworkMode", "host"), ("HostConfig", "ReadonlyRootfs", False),
    ("HostConfig", "Privileged", True), ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
    ("HostConfig", "SecurityOpt", []), ("HostConfig", "PidsLimit", 0),
    ("HostConfig", "Memory", 0), ("HostConfig", "NanoCpus", 0),
    ("HostConfig", "Tmpfs", {}), ("HostConfig", "PidMode", "host"),
])
def test_actual_inspect_must_match_fixed_policy(tmp_path, scope, key, value):
    document, mounts = _inspect_document(tmp_path)
    worker._verify_inspect(document, token="token", entrypoint="dotnet",
        command=["/assembly/Subject.dll"], mounts=mounts, runtime=True)
    document[scope][key] = value
    with pytest.raises(ValueError, match="INSPECT_POLICY_MISMATCH"):
        worker._verify_inspect(document, token="token", entrypoint="dotnet",
            command=["/assembly/Subject.dll"], mounts=mounts, runtime=True)


def test_extra_or_writable_runtime_mount_is_rejected(tmp_path):
    original, mounts = _inspect_document(tmp_path)
    for change in ("extra", "writable", "source"):
        document = deepcopy(original)
        if change == "extra":
            document["Mounts"].append({"Type": "bind", "Destination": "/private", "Source": str(tmp_path), "RW": False})
        elif change == "writable":
            document["Mounts"][0]["RW"] = True
        else:
            document["Mounts"][0]["Source"] = str(tmp_path / "unapproved")
        with pytest.raises(ValueError, match="INSPECT_POLICY_MISMATCH"):
            worker._verify_inspect(document, token="token", entrypoint="dotnet",
                command=["/assembly/Subject.dll"], mounts=mounts, runtime=True)


PUBLIC_WORKER = r'''using System;
using System.IO;
using System.Net.Sockets;
using System.Text.Json;
using System.Threading;
public static class Program {
    static string Limit(string first, string fallback) {
        return File.ReadAllText(File.Exists(first) ? first : fallback).Trim();
    }
    public static void Main() {
        using var document = JsonDocument.Parse(Console.In.ReadToEnd());
        var input = document.RootElement;
        var mode = input.GetProperty("mode").GetString();
        if (mode == "throw") throw new InvalidOperationException("public calibration exception");
        if (mode == "sleep") Thread.Sleep(Timeout.Infinite);
        if (mode == "overflow") { Console.Write(new string('x', 2097152)); return; }
        if (mode == "echo") { Console.WriteLine(input.GetRawText()); return; }
        bool writeDenied = false, hiddenReadDenied = false, networkDenied = false;
        try { File.WriteAllText("/assembly/write-probe.txt", "must-not-write"); }
        catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { writeDenied = true; }
        try { File.ReadAllText(input.GetProperty("private_candidate").GetString()); }
        catch (Exception e) when (e is IOException || e is UnauthorizedAccessException) { hiddenReadDenied = true; }
        try { using var socket = new TcpClient(); socket.Connect("192.0.2.1", 80); }
        catch (SocketException) { networkDenied = true; }
        File.WriteAllText("/operation-output/created.txt", "ephemeral operation output");
        Console.WriteLine(JsonSerializer.Serialize(new { write_denied = writeDenied,
            hidden_read_denied = hiddenReadDenied, network_denied = networkDenied,
            temp_output_writable = File.Exists("/operation-output/created.txt"),
            source_visible = File.Exists("/inputs/Worker.cs"),
            memory_limit = Limit("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
            pids_limit = Limit("/sys/fs/cgroup/pids.max", "/sys/fs/cgroup/pids/pids.max") }));
    }
}
'''


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("CODEX_CSHARP_CONTAINER_TEST") != "1",
                    reason="Explicit real Docker calibration selection is required.")
def test_real_public_compilation_runtime_and_isolation(tmp_path):
    root = Path(os.environ.get("CODEX_CSHARP_PROBE_ROOT", str(tmp_path)))
    root.mkdir(parents=True, exist_ok=True)
    compilation = worker.compile_csharp(sources={"Worker.cs": PUBLIC_WORKER.encode()},
        output_root=root / "compilation")
    assert compilation.succeeded
    echo = worker.run_csharp(compilation=compilation, operation={"mode": "echo", "text": "public"},
        output_root=root / "echo")
    assert echo["completed"] and echo["exit_code"] == echo["container_state"]["ExitCode"] == 0
    assert json.loads(echo["stdout"]) == {"mode": "echo", "text": "public"}
    private = root / "unmounted-private-sentinel.txt"
    private.write_text("nonsensitive-host-sentinel", encoding="utf-8")
    relative = private.resolve().as_posix().split(":", 1)[-1]
    candidate = "/run/desktop/mnt/host/c" + relative
    boundary = worker.run_csharp(compilation=compilation,
        operation={"mode": "boundary", "private_candidate": candidate}, output_root=root / "boundary")
    observed = json.loads(boundary["stdout"])
    assert observed == {"write_denied": True, "hidden_read_denied": True, "network_denied": True,
        "temp_output_writable": True, "source_visible": False, "memory_limit": "1073741824", "pids_limit": "64"}
    assert not boundary["runtime_file_outputs_returned"] and not boundary["runtime_files_persistent"]
    assert private.read_text() == "nonsensitive-host-sentinel"
    thrown = worker.run_csharp(compilation=compilation, operation={"mode": "throw"}, output_root=root / "exception")
    assert thrown["completed"] and thrown["container_state"]["ExitCode"] != 0
    assert "public calibration exception" in thrown["stderr"]
    overflow = worker.run_csharp(compilation=compilation, operation={"mode": "overflow"}, output_root=root / "overflow")
    assert overflow["output_limit_exceeded"] and not overflow["completed"]
    assert len(overflow["stdout"].encode()) <= worker.OUTPUT_LIMIT
    timed = worker.run_csharp(compilation=compilation, operation={"mode": "sleep"}, output_root=root / "timeout")
    assert timed["timed_out"] and not timed["completed"] and not timed["container_state"]["Running"]
    failed = worker.compile_csharp(sources={"Invalid.cs": b"deliberately invalid C sharp"},
        output_root=root / "compiler-error")
    assert not failed.succeeded
    failed_execution = json.loads((Path(failed.output_root) / "execution.json").read_text())
    assert failed_execution["completed"] and "error CS" in failed_execution["stdout"]
    with pytest.raises(ValueError, match="COMPILATION_NOT_ADMITTED"):
        worker.run_csharp(compilation=failed, operation={}, output_root=root / "should-not-run")
    binary = Path(compilation.binary_ref["path"])
    binary.write_bytes(binary.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="BINARY_CHANGED"):
        worker.run_csharp(compilation=compilation, operation={}, output_root=root / "changed-binary")
    worker._save(root / "binary-tamper.json", {"original_ref": compilation.binary_ref,
        "tampered_ref": worker._ref(binary), "rejected_before_container_creation": True,
        "original_bytes_retained_in": str(root / "echo/public-assembly/Subject.dll")})


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("CODEX_CSHARP_CONTAINER_TEST") != "1",
                    reason="Explicit real Docker calibration selection is required.")
def test_real_stop_failure_preserves_error_and_reaps_client(tmp_path, monkeypatch):
    root = Path(os.environ.get("CODEX_CSHARP_PROBE_ROOT", str(tmp_path)))
    root.mkdir(parents=True, exist_ok=True)
    compilation = worker.compile_csharp(sources={"Worker.cs": PUBLIC_WORKER.encode()},
        output_root=root / "verified-compilation")
    assert compilation.succeeded
    echo = worker.run_csharp(compilation=compilation, operation={"mode": "echo"}, output_root=root / "verified-copy")
    assert echo["completed"] and json.loads(echo["stdout"]) == {"mode": "echo"}
    command = worker._command
    failure = RuntimeError("injected stop callback failure with real container still running")

    def fail_stop(directory, name, arguments):
        if name == "kill":
            worker._save(directory / "injected-stop-failure.json", {"argv_not_executed": arguments,
                "error": str(failure), "purpose": "exercise local-client and outer-container cleanup"})
            raise failure
        return command(directory, name, arguments)

    monkeypatch.setattr(worker, "_command", fail_stop)
    stopped = root / "stop-failure"
    with pytest.raises(RuntimeError, match="injected stop callback failure") as raised:
        worker.run_csharp(compilation=compilation, operation={"mode": "sleep"}, output_root=stopped)
    assert raised.value is failure
    captured = json.loads((stopped / "attach-failure.json").read_text())
    assert captured["error"] == str(failure)
    assert captured["execution"]["local_process_reaped"] is True
    assert captured["execution"]["timed_out"] is True
    assert captured["execution"]["local_cleanup_errors"] == []
    created = json.loads((stopped / "create.json").read_text())["stdout"].strip()
    cleanup = json.loads((stopped / "cleanup.json").read_text())
    assert cleanup["exit_code"] == 0 and cleanup["argv"][-1] == created
    absent = command(stopped, "verify-container-removed", [*worker._docker(), "inspect", created])
    assert absent.returncode != 0 and b"no such object" in absent.stderr.lower()
