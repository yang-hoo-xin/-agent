"""Wire-level tests for controlled-agent MCP JSON-RPC adapter."""

from __future__ import annotations

from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.mcp import (
    CONTROLLED_AGENT_TOOL_NAMES,
    DANGEROUS_TOOL_NAMES,
    ControlledAgentJSONRPCErrorCodes,
    ControlledAgentMCPJsonRpcAdapter,
    ControlledAgentMCPToolSurface,
)


def test_initialize_returns_protocol_capabilities_and_server_info(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "pytest-client", "version": "1.0.0"},
                "capabilities": {},
            },
        }
    )

    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    result = response["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"] == {
        "name": "controlled-agent-mcp-tools",
        "version": "0.1.0",
    }


def test_initialize_uses_default_protocol_version_without_params(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize"}
    )

    assert response is not None
    assert response["result"]["protocolVersion"] == "2025-06-18"


def test_initialize_rejects_malformed_params(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_request(
        {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": []}
    )

    assert response is not None
    assert response["error"]["code"] == ControlledAgentJSONRPCErrorCodes.INVALID_PARAMS


def test_tools_list_returns_only_safe_tool_schemas(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    response = adapter.handle_request(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}}
    )

    assert response is not None
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 4
    tools = response["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert tool_names == set(CONTROLLED_AGENT_TOOL_NAMES)
    assert tool_names.isdisjoint(DANGEROUS_TOOL_NAMES)
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }


def test_tools_call_returns_structured_content_and_refs(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload=_feature_spec_payload(),
        trace_refs=["trace_feature_spec"],
    )
    adapter = ControlledAgentMCPJsonRpcAdapter(ControlledAgentMCPToolSurface(store))

    response = adapter.handle_request(
        {
            "jsonrpc": "2.0",
            "id": "call_001",
            "method": "tools/call",
            "params": {
                "name": "get_feature_status",
                "arguments": {"feature_id": "feature_001"},
            },
        }
    )

    assert response is not None
    result = response["result"]
    latest_feature_ref = next(
        ref
        for ref in store.list_feature_artifacts("feature_001")
        if ref.artifact_type == "feature_spec"
    )
    assert result["structuredContent"]["feature_id"] == "feature_001"
    assert isinstance(result["content"], list)
    assert result["content"][0]["type"] == "text"
    assert result["content"][1]["type"] == "text"
    assert result["artifact_refs"] == [_artifact_ref_string(latest_feature_ref)]
    assert result["trace_refs"] == ["trace_feature_spec"]
    assert result["isError"] is False


def test_tools_call_unknown_tool_is_protocol_error(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "not_exposed", "arguments": {}},
        }
    )

    assert response is not None
    assert "result" not in response
    assert response["error"]["code"] == ControlledAgentJSONRPCErrorCodes.METHOD_NOT_FOUND
    assert response["error"]["data"]["tool"] == "not_exposed"
    assert response["error"]["data"]["dangerous_tools_exposed"] is False


def test_tools_call_dangerous_tool_is_hidden_protocol_error(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "run_game", "arguments": {}},
        }
    )

    assert response is not None
    assert response["error"]["code"] == ControlledAgentJSONRPCErrorCodes.METHOD_NOT_FOUND
    assert "run_game" not in response["error"]["data"]["exposed_tools"]


def test_invalid_params_are_jsonrpc_invalid_params(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "list_features", "arguments": []},
        }
    )

    assert response is not None
    assert response["error"]["code"] == ControlledAgentJSONRPCErrorCodes.INVALID_PARAMS


def test_parse_error_uses_jsonrpc_parse_error(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_json("{not json")

    assert response is not None
    assert response["id"] is None
    assert response["error"]["code"] == ControlledAgentJSONRPCErrorCodes.PARSE_ERROR


def test_notifications_do_not_emit_responses(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    assert (
        adapter.handle_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        is None
    )
    assert (
        adapter.handle_request({"jsonrpc": "2.0", "method": "tools/list", "params": {}})
        is None
    )


def test_unknown_jsonrpc_method_is_method_not_found(tmp_path: Path) -> None:
    response = _adapter(tmp_path).handle_request(
        {"jsonrpc": "2.0", "id": 6, "method": "resources/list", "params": {}}
    )

    assert response is not None
    assert response["error"]["code"] == ControlledAgentJSONRPCErrorCodes.METHOD_NOT_FOUND
    assert response["error"]["data"] == {"method": "resources/list"}


def _adapter(tmp_path: Path) -> ControlledAgentMCPJsonRpcAdapter:
    return ControlledAgentMCPJsonRpcAdapter(
        ControlledAgentMCPToolSurface(ArtifactStore(tmp_path / "artifacts"))
    )


def _feature_spec_payload() -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "Feature spec ready.",
        "feature_id": "feature_001",
        "user_request": "Change marker color.",
        "target_behavior": "Marker color changes.",
        "non_goals": [],
        "target_mod": "ExampleMod",
        "risk_level": "low",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _artifact_ref_string(ref: ArtifactRef) -> str:
    return f"{ref.feature_id}:{ref.artifact_type}:{Path(ref.path).name}:{ref.artifact_hash}"
