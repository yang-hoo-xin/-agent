"""Wire-level JSON-RPC adapter for the controlled-agent MCP tool surface."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .tools import (
    CONTROLLED_AGENT_TOOL_NAMES,
    DANGEROUS_TOOL_NAMES,
    ControlledAgentMCPToolSurface,
)

CONTROLLED_AGENT_MCP_SERVER_NAME = "controlled-agent-mcp-tools"
CONTROLLED_AGENT_MCP_SERVER_VERSION = "0.1.0"
DEFAULT_MCP_PROTOCOL_VERSION = "2025-06-18"


class ControlledAgentJSONRPCErrorCodes:
    """Standard JSON-RPC 2.0 error codes used by the controlled-agent adapter."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


@dataclass(frozen=True)
class ControlledAgentMCPJsonRpcAdapter:
    """Translate JSON-RPC MCP requests into safe controlled-agent tool calls."""

    tool_surface: ControlledAgentMCPToolSurface

    def handle_json(self, raw_message: str) -> dict[str, Any] | None:
        """Handle a raw JSON-RPC message string."""

        try:
            request = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            return _error_response(
                request_id=None,
                code=ControlledAgentJSONRPCErrorCodes.PARSE_ERROR,
                message="Parse error",
                data={"detail": str(exc)},
            )
        return self.handle_request(request)

    def handle_request(self, request: Any) -> dict[str, Any] | None:
        """Handle a decoded JSON-RPC request object."""

        if not isinstance(request, dict):
            return _error_response(
                request_id=None,
                code=ControlledAgentJSONRPCErrorCodes.INVALID_REQUEST,
                message="Invalid Request",
                data={"detail": "JSON-RPC request must be an object."},
            )

        request_id = request.get("id")
        is_notification = "id" not in request
        method = request.get("method")
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            if is_notification:
                return None
            return _error_response(
                request_id=request_id,
                code=ControlledAgentJSONRPCErrorCodes.INVALID_REQUEST,
                message="Invalid Request",
                data={"detail": "Request must include jsonrpc='2.0' and string method."},
            )

        try:
            if method == "initialize":
                return self._handle_initialize(request_id, request, is_notification)
            if method == "notifications/initialized":
                return None
            if method == "tools/list":
                return self._handle_tools_list(request_id, is_notification)
            if method == "tools/call":
                return self._handle_tools_call(request_id, request, is_notification)
            if is_notification:
                return None
            return _error_response(
                request_id=request_id,
                code=ControlledAgentJSONRPCErrorCodes.METHOD_NOT_FOUND,
                message="Method not found",
                data={"method": method},
            )
        except Exception as exc:  # pragma: no cover - defensive protocol guard.
            if is_notification:
                return None
            return _error_response(
                request_id=request_id,
                code=ControlledAgentJSONRPCErrorCodes.INTERNAL_ERROR,
                message="Internal error",
                data={"detail": str(exc)},
            )

    def _handle_initialize(
        self,
        request_id: Any,
        request: dict[str, Any],
        is_notification: bool,
    ) -> dict[str, Any] | None:
        if is_notification:
            return None
        params = request.get("params", {})
        if not isinstance(params, dict):
            return _invalid_params(request_id, "initialize params must be an object.")
        protocol_version = params.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version.strip():
            protocol_version = DEFAULT_MCP_PROTOCOL_VERSION
        return _result_response(
            request_id=request_id,
            result={
                "protocolVersion": protocol_version.strip(),
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": CONTROLLED_AGENT_MCP_SERVER_NAME,
                    "version": CONTROLLED_AGENT_MCP_SERVER_VERSION,
                },
            },
        )

    def _handle_tools_list(
        self,
        request_id: Any,
        is_notification: bool,
    ) -> dict[str, Any] | None:
        if is_notification:
            return None
        return _result_response(
            request_id=request_id,
            result={"tools": self.tool_surface.list_tools()},
        )

    def _handle_tools_call(
        self,
        request_id: Any,
        request: dict[str, Any],
        is_notification: bool,
    ) -> dict[str, Any] | None:
        if is_notification:
            return None
        params = request.get("params")
        if not isinstance(params, dict):
            return _invalid_params(request_id, "tools/call params must be an object.")
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            return _invalid_params(request_id, "tools/call params.name must be a string.")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _invalid_params(
                request_id,
                "tools/call params.arguments must be an object when provided.",
            )
        tool_name = name.strip()
        if tool_name in DANGEROUS_TOOL_NAMES or tool_name not in CONTROLLED_AGENT_TOOL_NAMES:
            return _error_response(
                request_id=request_id,
                code=ControlledAgentJSONRPCErrorCodes.METHOD_NOT_FOUND,
                message="Tool not found",
                data={
                    "tool": tool_name,
                    "exposed_tools": list(CONTROLLED_AGENT_TOOL_NAMES),
                    "dangerous_tools_exposed": False,
                },
            )
        return _result_response(
            request_id=request_id,
            result=self.tool_surface.call_tool(tool_name, arguments),
        )


def _invalid_params(request_id: Any, detail: str) -> dict[str, Any]:
    return _error_response(
        request_id=request_id,
        code=ControlledAgentJSONRPCErrorCodes.INVALID_PARAMS,
        message="Invalid params",
        data={"detail": detail},
    )


def _result_response(*, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def _error_response(
    *,
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }
