"""Prepare and probe the public lease-scope subject worker; never start Docker.

The worker contains no hidden checks or expected values. A trusted judge can
send operation inputs and compare the returned observations outside the
untrusted runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.prepare_patch_sft_data import ref, save, toolchain  # noqa: E402

WORKER_SOURCE = r'''
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

public sealed class OperationRequest
{
    public string FailOpen { get; set; }
    public string[] Records { get; set; } = Array.Empty<string>();
    public string ThrowOnRecord { get; set; }
    public bool PreopenCallerHandle { get; set; }
}
public sealed class CallbackObservation
{
    public string Record { get; set; }
    public int Active { get; set; }
    public string[] OpenHandles { get; set; }
}
public sealed class HandleObservation
{
    public string Name { get; set; }
    public int DisposeCount { get; set; }
}
public static class Program
{
    public static int Main()
    {
        var request = JsonSerializer.Deserialize<OperationRequest>(Console.In.ReadToEnd());
        if (request == null) return 2;
        var context = new LeaseContext { FailOpen = request.FailOpen };
        LeaseHandle caller = request.PreopenCallerHandle ? context.Open("caller-owned") : null;
        var pipeline = new ExportPipeline();
        var emitted = new List<string>();
        var callbacks = new List<CallbackObservation>();
        var callbackError = new InvalidOperationException("public-callback-error");
        int? completed = null;
        string exceptionType = null;
        var callbackIdentityPreserved = false;
        try
        {
            completed = pipeline.Apply(context, request.Records, record =>
            {
                emitted.Add(record);
                callbacks.Add(new CallbackObservation {
                    Record = record,
                    Active = context.Active,
                    OpenHandles = context.Handles.Where(item => item.DisposeCount == 0)
                        .Select(item => item.Name).ToArray()
                });
                if (record == request.ThrowOnRecord) throw callbackError;
            });
        }
        catch (Exception error)
        {
            exceptionType = error.GetType().FullName;
            callbackIdentityPreserved = Object.ReferenceEquals(error, callbackError);
        }
        var response = new {
            completed,
            exception_type = exceptionType,
            callback_exception_identity_preserved = callbackIdentityPreserved,
            active = context.Active,
            events = context.Events.ToArray(),
            emitted = emitted.ToArray(),
            callbacks = callbacks.ToArray(),
            handles = context.Handles.Select(item => new HandleObservation {
                Name = item.Name, DisposeCount = item.DisposeCount }).ToArray(),
            caller_owned_dispose_count = caller == null ? (int?)null : caller.DisposeCount
        };
        Console.Out.Write(JsonSerializer.Serialize(response));
        return 0;
    }
}
'''


def _compile(source, output):
    tools = toolchain()
    worker = output / "SubjectWorker.cs"
    subject = output / "Subject.cs"
    worker.write_text(WORKER_SOURCE, encoding="utf-8", newline="\n")
    subject.write_bytes(Path(source).read_bytes())
    assembly, response = output / "SubjectWorker.dll", output / "compile.rsp"
    response.write_text("\n".join(["/nologo", "/target:exe", "/langversion:latest",
        f'/out:"{assembly}"', *(f'/r:"{item["path"]}"' for item in tools["references"]),
        f'"{subject}"', f'"{worker}"']), encoding="utf-8")
    environment = {name: os.environ[name] for name in
                   ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP")
                   if name in os.environ}
    environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
    result = subprocess.run([tools["dotnet"]["path"], tools["compiler"]["path"], "@" + str(response)],
        cwd=output, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=40)
    receipt = {"exit_code": result.returncode,
        "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
        "assembly_ref": ref(assembly) if assembly.is_file() else None,
        "subject_ref": ref(subject), "worker_ref": ref(worker), "toolchain": tools}
    save(output / "compilation.json", receipt)
    if result.returncode:
        raise ValueError("LEASE_SCOPE_WORKER_COMPILATION_FAILED")
    save(output / "SubjectWorker.runtimeconfig.json", {"runtimeOptions": {"tfm": "net7.0",
        "framework": {"name": "Microsoft.NETCore.App", "version": "7.0.11"}}})
    return tools, assembly


def _invoke(dotnet, assembly, value, output, name):
    result = subprocess.run([dotnet, str(assembly)], input=json.dumps(value), cwd=assembly.parent,
        capture_output=True, text=True, encoding="utf-8", timeout=15)
    if result.returncode:
        raise ValueError("LEASE_SCOPE_WORKER_INVOCATION_FAILED")
    response = json.loads(result.stdout)
    return save(output / (name + ".json"), {"request_sha256": hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "response": response, "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest()})


def prepare(*, source, output_root):
    source, output = Path(source).resolve(strict=True), Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=False)
    tools, assembly = _compile(source, output)
    probes = [
        ("normal", {"Records": ["a", "b"]}),
        ("partial-open-failure", {"FailOpen": "writer", "Records": ["a"]}),
        ("callback-failure", {"Records": ["a"], "ThrowOnRecord": "a"}),
        ("caller-owned", {"Records": [], "PreopenCallerHandle": True}),
    ]
    refs = [_invoke(tools["dotnet"]["path"], assembly, value, output, name)
            for name, value in probes]
    schema = {"schema_version": "lease_scope_subject_operation_v1",
        "input_fields": {"FailOpen": "string|null", "Records": "string[]",
                         "ThrowOnRecord": "string|null", "PreopenCallerHandle": "boolean"},
        "output_fields": ["completed", "exception_type", "callback_exception_identity_preserved",
                          "active", "events", "emitted", "callbacks", "handles",
                          "caller_owned_dispose_count"],
        "contains_expected_values": False,
        "scope": "public lease-scope development adapter; not hidden judge or Agent score"}
    schema_ref = save(output / "operation-schema.json", schema)
    command_ref = save(output / "local-worker-command.json", {
        "executable_ref": ref(Path(tools["dotnet"]["path"])),
        "argv": [str(assembly)], "cwd": str(output), "timeout_seconds": 15,
        "isolation": "none_development_probe_only"})
    development_cases = {"schema_version": "lease_scope_trusted_cases_v1",
        "task_id": "private_eval_20260909_lease_scope_001",
        "eligibility": "development_only_not_held_out_after_adapter_design",
        "cases": [
            {"case_id": "normal", "operation": {"Records": ["a", "b"]}, "assertions": [
                {"path": ["completed"], "equals": 2}, {"path": ["active"], "equals": 0},
                {"path": ["emitted"], "equals": ["a", "b"]}]},
            {"case_id": "partial-open-failure", "operation": {"FailOpen": "writer", "Records": ["a"]},
             "assertions": [{"path": ["exception_type"], "equals": "LeaseFault"},
                            {"path": ["active"], "equals": 0},
                            {"path": ["handles", 0, "DisposeCount"], "equals": 1}]},
            {"case_id": "callback-failure", "operation": {"Records": ["a"], "ThrowOnRecord": "a"},
             "assertions": [{"path": ["exception_type"], "equals": "System.InvalidOperationException"},
                            {"path": ["callback_exception_identity_preserved"], "equals": True},
                            {"path": ["active"], "equals": 0}]},
            {"case_id": "caller-owned", "operation": {"Records": [], "PreopenCallerHandle": True},
             "assertions": [{"path": ["completed"], "equals": 0},
                            {"path": ["active"], "equals": 1},
                            {"path": ["caller_owned_dispose_count"], "equals": 0}]}
        ]}
    cases_ref = save(output / "development-cases.json", development_cases)
    container_plan = {"status": "blocked_docker_daemon_and_image_not_authorized",
        "trusted_side": "hidden cases and expected values remain outside the container",
        "untrusted_side": "SubjectWorker.dll plus submitted Subject only",
        "required_docker_flags": ["--network=none", "--read-only", "--cap-drop=ALL",
                                  "--security-opt=no-new-privileges", "--pids-limit", "--memory", "--cpus"],
        "mounts": ["one read-only public worker/subject directory", "one tmpfs scratch"],
        "forbidden_mounts": ["sealed root", "hidden Program/checks", "reference implementations",
                             "judge reports", "repository or user profile"],
        "image": None, "daemon_started": False, "model_calls": 0}
    plan_ref = save(output / "container-plan.json", container_plan)
    summary = {"status": "public_worker_compiled_and_probed", "task_id": "private_eval_20260909_lease_scope_001",
        "eligibility": "development_only_not_held_out_after_adapter_design",
        "subject_source_sha256": ref(source)["sha256"], "worker_assembly_ref": ref(assembly),
        "operation_schema_ref": schema_ref, "local_worker_command_ref": command_ref,
        "development_cases_ref": cases_ref, "container_plan_ref": plan_ref, "probe_refs": refs,
        "probe_count": len(refs), "hidden_material_used": False, "model_calls": 0,
        "untrusted_container_execution": "not_run"}
    return save(output / "summary.json", summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(source=args.source, output_root=args.output_root)
    except Exception as exc:
        print(json.dumps({"status": "blocked", "failure_class": type(exc).__name__}))
        return 2
    print(json.dumps({"status": "public_worker_compiled_and_probed", "summary_ref": result,
                      "model_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
