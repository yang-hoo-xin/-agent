"""Bounded official-SDK stdio probe; every stdout line is validated as protocol."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import anyio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client import stdio


def probe_stdio(*, command, arguments, calls, output_root, cwd=None, environment=None, timeout_seconds=45):
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=False)
    chunks, processes = [], []
    terminations = []
    original_create, original_stream = stdio._create_platform_compatible_process, stdio.TextReceiveStream
    original_terminate = stdio._terminate_process_tree
    report = {"schema_version": "mcp_stdio_probe_v1", "command": command, "arguments": arguments,
              "client_sdk_version": importlib.metadata.version("mcp"), "calls": [], "status": "failed",
              "environment_override_names": sorted((environment or {}).keys()),
              "os_sandbox_claimed": False, "stdout_protocol_only": False}

    async def observe_process(*args, **kwargs):
        process = await original_create(*args, **kwargs)
        processes.append(process)
        return process

    async def observe_terminate(process):
        terminations.append({"pid": process.pid, "reason": "sdk_graceful_shutdown_timeout", "at": datetime.now(timezone.utc).isoformat()})
        return await original_terminate(process)

    class ObserveStream(original_stream):
        async def receive(self):
            value = await super().receive()
            chunks.append(value)
            # 为什么要有它：进程中断时仍保留已收到的原始协议字节，不把未完成请求补写成成功。
            with (output / "received-stream.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(value)
            return value

    async def interact():
        parameters = StdioServerParameters(command=command, args=arguments, cwd=cwd,
            env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **(environment or {})})
        with anyio.fail_after(timeout_seconds), (output / "stderr.log").open("w", encoding="utf-8") as stderr:
            async with stdio.stdio_client(parameters, errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=timeout_seconds)) as session:
                    report["initialize"] = (await session.initialize()).model_dump(mode="json", exclude_none=True)
                    report["tools"] = (await session.list_tools()).model_dump(mode="json", exclude_none=True)
                    for case in calls:
                        started = anyio.current_time()
                        accepted_at = datetime.now(timezone.utc).isoformat()
                        if "cancel_after_ms" in case:
                            with anyio.move_on_after(case["cancel_after_ms"] / 1000) as scope:
                                response = await session.call_tool(case["name"], case.get("arguments", {}))
                            report["calls"].append({"tool": case["name"], "cancelled_by_client": scope.cancel_called,
                                "provider_termination": "unknown", "elapsed_ms": (anyio.current_time() - started) * 1000})
                        else:
                            response = await session.call_tool(case["name"], case.get("arguments", {}))
                            report["calls"].append({"tool": case["name"], "elapsed_ms": (anyio.current_time() - started) * 1000,
                                "response": response.model_dump(mode="json", exclude_none=True)})
                        report["calls"][-1].update(accepted_at=accepted_at, finished_at=datetime.now(timezone.utc).isoformat())
                        with (output / "completed-calls.jsonl").open("a", encoding="utf-8") as completed:
                            completed.write(json.dumps(report["calls"][-1], ensure_ascii=False) + "\n")
                    # 为什么要有它：取消后的尾响应仍需由活着的 ClientSession 消费，先关闭会话会让 SDK 的 reader 向已关闭流写入。
                    child = processes[-1]
                    if child.stdin:
                        await child.stdin.aclose()
                    with anyio.fail_after(5):
                        await child.wait()
                    report["graceful_input_closed_before_session"] = True
                    report["status"] = "completed"

    try:
        with patch.object(stdio, "_create_platform_compatible_process", observe_process), patch.object(stdio, "TextReceiveStream", ObserveStream), patch.object(stdio, "_terminate_process_tree", observe_terminate):
            anyio.run(interact)
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        def failure(value):
            return {"type": type(value).__name__, "frames": [{"file": row.filename, "line": row.lineno, "function": row.name} for row in traceback.extract_tb(value.__traceback__)],
                    "children": [failure(child) for child in getattr(value, "exceptions", ())]}
        report["failure_structure"] = failure(error)
    finally:
        stdout = "".join(chunks)
        (output / "stdout.jsonl").write_text(stdout, encoding="utf-8")
        try:
            lines = stdout.splitlines()
            for line in lines:
                types.JSONRPCMessage.model_validate_json(line)
            report["stdout_protocol_only"] = bool(lines)
            report["stdout_line_count"] = len(lines)
        except Exception:
            report.update(status="failed", protocol_error="NON_JSONRPC_STDOUT")
        report["processes"] = [{"pid": process.pid, "exit_code": process.returncode} for process in processes]
        report["all_processes_exited"] = bool(processes) and all(process.returncode is not None for process in processes)
        report["sdk_forced_terminations"] = terminations
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, help="JSON command/arguments/calls/cwd/environment/timeout_seconds")
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    report = probe_stdio(**plan, output_root=args.output_root)
    print(json.dumps({key: report[key] for key in ("status", "stdout_protocol_only", "all_processes_exited")}))
    return 0 if report["status"] == "completed" and report["stdout_protocol_only"] and report["all_processes_exited"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
