"""Bounded official MCP SDK client for the existing local knowledge server."""
from __future__ import annotations

import importlib.metadata
import json
import time
import threading
from contextvars import ContextVar
from datetime import timedelta

_SESSION_LOCK = threading.Lock()
_CAPTURE_SCOPE = ContextVar("document_mcp_capture_scope", default=None)


def query_batch(configuration, requests, directory):
    import anyio
    from mcp import ClientSession, StdioServerParameters, types
    from mcp.client import stdio
    configuration.verify()
    value = configuration.value
    result = {"schema_version": "document_mcp_batch_v1", "status": "failed", "calls": [],
              "client_sdk_version": importlib.metadata.version("mcp"), "provider_termination": "unknown"}
    started = time.perf_counter()
    processes, stdout_chunks = [], []
    scope_identity = object()

    async def run():
        parameters = StdioServerParameters(command=value["python_ref"]["path"],
            args=["-m", "src.mcp_server.server", "--settings", value["server_settings_ref"]["path"]],
            cwd=value["server_root"], env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        with anyio.fail_after(value["timeout_seconds"]), (directory / "stderr.log").open("x", encoding="utf-8") as stderr:
            async with stdio.stdio_client(parameters, errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=value["timeout_seconds"])) as session:
                    result["initialize"] = (await session.initialize()).model_dump(mode="json", exclude_none=True)
                    listed = await session.list_tools()
                    tools = {tool.name: tool for tool in listed.tools}
                    if "query_knowledge_hub" not in tools:
                        raise ValueError("KNOWLEDGE_MCP_TOOL_UNAVAILABLE")
                    result["tool"] = tools["query_knowledge_hub"].model_dump(mode="json", exclude_none=True)
                    annotations = result["tool"].get("annotations", {})
                    if annotations.get("readOnlyHint") is not True or annotations.get("destructiveHint") is not False:
                        raise ValueError("KNOWLEDGE_MCP_READ_ONLY_CONTRACT_REQUIRED")
                    for arguments in requests:
                        then = time.perf_counter()
                        response = await session.call_tool("query_knowledge_hub", arguments)
                        result["calls"].append({"arguments": arguments, "elapsed_seconds": time.perf_counter() - then,
                            "response": response.model_dump(mode="json", exclude_none=True)})
                    # 为什么要有它：SDK 1.29.1退出Session后仍可能有尾响应；先在Session存活时发EOF并等待子进程，不能吞协议退出错误。
                    if len(processes) != 1 or processes[0].stdin is None:
                        raise ValueError("KNOWLEDGE_MCP_PROCESS_IDENTITY_UNAVAILABLE")
                    await processes[0].stdin.aclose()
                    with anyio.fail_after(5):
                        await processes[0].wait()
                    if processes[0].returncode != 0:
                        raise ValueError("KNOWLEDGE_MCP_SERVER_EXIT_FAILED")
        result["client_session_closed"] = True
        result["status"] = "completed"

    try:
        with _SESSION_LOCK:
            result["client_queue_seconds"] = time.perf_counter() - started
            result["client_concurrency_scope"] = "same_process_document_sessions_serialized"
            original_create, original_stream = stdio._create_platform_compatible_process, stdio.TextReceiveStream
            async def observe_process(*args, **kwargs):
                process = await original_create(*args, **kwargs)
                if _CAPTURE_SCOPE.get() is scope_identity:
                    processes.append(process)
                return process
            class ObserveStream(original_stream):
                async def receive(self):
                    chunk = await super().receive()
                    if _CAPTURE_SCOPE.get() is scope_identity:
                        stdout_chunks.append(chunk)
                        if sum(len(value.encode("utf-8")) for value in stdout_chunks) > 16 * 1024 * 1024:
                            raise ValueError("KNOWLEDGE_MCP_STDOUT_BUDGET_EXCEEDED")
                    return chunk
            token = _CAPTURE_SCOPE.set(scope_identity)
            try:
                stdio._create_platform_compatible_process = observe_process
                stdio.TextReceiveStream = ObserveStream
                anyio.run(run)
            finally:
                stdio._create_platform_compatible_process, stdio.TextReceiveStream = original_create, original_stream
                _CAPTURE_SCOPE.reset(token)
    except Exception as error:
        result["status"] = "failed"
        result["error_type"] = type(error).__name__
        result.setdefault("client_session_closed", False)
    finally:
        stdout = "".join(stdout_chunks)
        (directory / "stdout.jsonl").write_text(stdout, encoding="utf-8")
        try:
            if not stdout.strip():
                raise ValueError("KNOWLEDGE_MCP_NO_PROTOCOL_OUTPUT")
            for line in stdout.splitlines():
                types.JSONRPCMessage.model_validate_json(line)
            result["stdout_protocol_only"] = bool(stdout.strip())
        except Exception:
            result.update(status="failed", error_type="InvalidProtocolStdout", stdout_protocol_only=False)
        result["processes"] = [{"pid": process.pid, "exit_code": process.returncode} for process in processes]
        result["all_local_processes_exited"] = bool(processes) and all(process.returncode is not None for process in processes)
        result["elapsed_seconds"] = time.perf_counter() - started
        with (directory / "result.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    configuration.verify()
    return result
