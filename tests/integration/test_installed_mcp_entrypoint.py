"""Opt-in wheel-install acceptance with the locked SDK's real stdio client.

Set MCP_INSTALLED_EXECUTABLE to the console command produced by an actual
wheel installation. This test never substitutes a script or module invocation
for that command and calls no knowledge, embedding or model tool.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
from datetime import timedelta
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client import stdio


@pytest.mark.integration
def test_installed_command_initializes_lists_original_tools_and_exits_cleanly(tmp_path, monkeypatch):
    command = os.environ.get("MCP_INSTALLED_EXECUTABLE")
    if not command:
        pytest.skip("Requires a wheel-installed MCP_INSTALLED_EXECUTABLE; module-only smoke is insufficient.")
    executable = Path(command).resolve(strict=True)
    assert executable.name in {"mcp-server", "mcp-server.exe"}
    stdout_chunks, processes = [], []
    original_create = stdio._create_platform_compatible_process
    original_text_stream = stdio.TextReceiveStream

    async def observe_process(*args, **kwargs):
        process = await original_create(*args, **kwargs)
        processes.append(process)
        return process

    class ObservedTextReceiveStream(original_text_stream):
        async def receive(self):
            text = await super().receive()
            stdout_chunks.append(text)
            return text

    # These client-side observers preserve the actual process, bytes and SDK
    # parsing. No server, protocol response or business dependency is mocked.
    monkeypatch.setattr(stdio, "_create_platform_compatible_process", observe_process)
    monkeypatch.setattr(stdio, "TextReceiveStream", ObservedTextReceiveStream)
    stderr_path = tmp_path / "server-stderr.log"
    observed = {}

    async def interact():
        parameters = StdioServerParameters(command=str(executable), args=[], cwd=str(tmp_path),
            env={"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        with anyio.fail_after(45), stderr_path.open("w", encoding="utf-8") as stderr:
            async with stdio.stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream,
                                         read_timeout_seconds=timedelta(seconds=35)) as session:
                    initialized = await session.initialize()
                    listed = await session.list_tools()
                    observed.update(protocol_version=initialized.protocolVersion,
                        server_name=initialized.serverInfo.name,
                        tool_names=sorted(tool.name for tool in listed.tools))
                    assert initialized.protocolVersion == types.LATEST_PROTOCOL_VERSION
                    assert initialized.capabilities.tools is not None
                    assert observed["tool_names"] == ["get_document_summary", "list_collections", "query_knowledge_hub"]

    anyio.run(interact)
    lines = [line for line in "".join(stdout_chunks).splitlines() if line]
    assert len(lines) >= 2
    for line in lines:
        types.JSONRPCMessage.model_validate_json(line)
    assert len(processes) == 1 and processes[0].returncode == 0
    receipt = {**observed, "installed_executable": str(executable), "server_exit_code": processes[0].returncode,
        "client_sdk_version": importlib.metadata.version("mcp"), "stdout_lines": len(lines),
        "stdout_protocol_only": True, "knowledge_tools_called": 0, "model_calls": 0}
    receipt_path = os.environ.get("MCP_ENTRYPOINT_RECEIPT_PATH")
    if receipt_path:
        Path(receipt_path).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
