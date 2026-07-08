"""Local read-only HTTP API for controlled-agent artifact inspection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from src.mod_agent.artifacts import ArtifactStore, ArtifactStoreError
from src.mod_agent.dashboard import DashboardProjectionBuilder


@dataclass(frozen=True)
class HttpApiResponse:
    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class ModAgentHttpApi:
    """Local safe read-only API over the artifact store and dashboard projection."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def handle_get(self, raw_path: str) -> HttpApiResponse:
        parsed = urlparse(raw_path)
        parts = _path_parts(parsed.path)
        try:
            if parts == ("health",):
                return _json_response(
                    200,
                    {
                        "status": "ok",
                        "service": "mod_agent_http_api",
                        "mode": "read_only",
                        "deployment": "local_dev_only",
                    },
                )
            if parts == ("features",):
                return _json_response(
                    200,
                    {
                        "features": self.artifact_store.list_feature_ids(),
                    },
                )
            if len(parts) == 3 and parts[0] == "features":
                feature_id = parts[1]
                action = parts[2]
                if action == "artifacts":
                    return _json_response(200, self._feature_artifacts(feature_id))
                if action == "dashboard":
                    projection = DashboardProjectionBuilder(
                        self.artifact_store
                    ).build_feature_projection(feature_id)
                    return _json_response(200, projection)
                if action == "status":
                    projection = DashboardProjectionBuilder(
                        self.artifact_store
                    ).build_feature_projection(feature_id)
                    return _json_response(
                        200,
                        {
                            "feature_id": feature_id,
                            "status": projection.get("status"),
                            "workflow": projection.get("workflow"),
                            "blockers": projection.get("blockers") or [],
                            "missing_artifacts": projection.get("missing_artifacts")
                            or [],
                        },
                    )
            return _json_response(
                404,
                {
                    "error": "not_found",
                    "message": "Unknown read-only API route.",
                },
            )
        except ArtifactStoreError as exc:
            return _json_response(
                400,
                {
                    "error": "artifact_store_error",
                    "message": str(exc),
                },
            )

    def handle_post(self, raw_path: str) -> HttpApiResponse:
        parts = _path_parts(urlparse(raw_path).path)
        if parts in {
            ("confirmed_apply",),
            ("copy_to_game_directory",),
            ("run_external_game",),
            ("delete_artifacts",),
        }:
            return _json_response(
                403,
                {
                    "error": "required_approval",
                    "message": "Dangerous tools are not executed by the HTTP API.",
                    "required_approval": True,
                    "route": "/" + "/".join(parts),
                },
            )
        return _json_response(
            405,
            {
                "error": "method_not_allowed",
                "message": "This API is read-only.",
            },
            headers={"Allow": "GET"},
        )

    def _feature_artifacts(self, feature_id: str) -> dict[str, Any]:
        refs = self.artifact_store.list_feature_artifacts(feature_id)
        return {
            "feature_id": feature_id,
            "artifacts": [
                {
                    "artifact_type": ref.artifact_type,
                    "artifact_hash": ref.artifact_hash,
                    "artifact_file": Path(ref.path).name,
                }
                for ref in refs
            ],
        }


def run_http_server(
    *,
    artifact_root: str | Path = "artifacts",
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_absolute_artifact_root: bool = False,
) -> ThreadingHTTPServer:
    """Run the local read-only API server until interrupted."""

    api = ModAgentHttpApi(
        ArtifactStore(
            _resolve_artifact_root(
                artifact_root,
                allow_absolute_artifact_root=allow_absolute_artifact_root,
            )
        )
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            _write_response(self, api.handle_get(self.path))

        def do_POST(self) -> None:  # noqa: N802
            _write_response(self, api.handle_post(self.path))

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()
    return server


def _resolve_artifact_root(
    artifact_root: str | Path,
    *,
    allow_absolute_artifact_root: bool = False,
) -> Path:
    root = Path(artifact_root)
    if root.is_absolute():
        if not allow_absolute_artifact_root:
            raise ArtifactStoreError(
                "Absolute artifact_root requires allow_absolute_artifact_root=True."
            )
        return root.resolve()
    resolved = (Path.cwd() / root).resolve()
    try:
        resolved.relative_to(Path.cwd().resolve())
    except ValueError as exc:
        raise ArtifactStoreError("Relative artifact_root cannot escape the project root.") from exc
    return resolved


def _write_response(handler: BaseHTTPRequestHandler, response: HttpApiResponse) -> None:
    body = (
        json.dumps(response.payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    handler.send_response(response.status_code)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body)),
        **response.headers,
    }
    for key, value in headers.items():
        handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


def _json_response(
    status_code: int,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> HttpApiResponse:
    return HttpApiResponse(
        status_code=status_code,
        payload=payload,
        headers=dict(headers or {}),
    )


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part for part in (unquote(item) for item in path.split("/")) if part)
