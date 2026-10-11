"""MCP Server entry point using official MCP SDK.

This module implements the MCP server using the official Python MCP SDK
with stdio transport. It ensures stdout only contains protocol messages
while all logs go to stderr.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from src.mcp_server.protocol_handler import create_mcp_server
from src.observability.logger import get_logger

if TYPE_CHECKING:
    pass


SERVER_NAME = "repoforge"
SERVER_VERSION = "0.1.0"


def _redirect_all_loggers_to_stderr() -> None:
    """Redirect all root logger handlers to stderr.

    MCP stdio transport reserves stdout for JSON-RPC messages.
    Any logging to stdout corrupts the protocol stream.
    """
    import logging as _logging

    root = _logging.getLogger()
    root.setLevel(_logging.INFO)
    stderr_handler = _logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        _logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    # Replace any existing stream handlers that might point to stdout
    for handler in root.handlers[:]:
        if isinstance(handler, _logging.StreamHandler) and not isinstance(
            handler, _logging.FileHandler
        ):
            root.removeHandler(handler)
    root.addHandler(stderr_handler)


def _preload_heavy_imports() -> None:
    """Eagerly import heavy third-party modules in the **main thread**.

    MCP SDK uses anyio + background threads for stdin/stdout I/O.
    When a tool handler runs ``asyncio.to_thread(fn)``, *fn* executes in
    a new worker thread.  If it tries to ``import chromadb`` (which
    transitively pulls in onnxruntime, numpy, sqlite3 C extensions …),
    that import can deadlock with the stdin-reader thread because both
    compete for Python's global *import lock*.

    Pre-importing here – before anyio spins up its I/O threads – avoids
    the deadlock entirely: subsequent ``import`` statements in worker
    threads simply hit ``sys.modules`` and return immediately.
    """
    # chromadb is the heaviest culprit (onnxruntime, numpy, …)
    try:
        import chromadb  # noqa: F401
        import chromadb.config  # noqa: F401
    except ImportError:
        pass  # optional at install time

    # Internal modules that tools lazy-import inside asyncio.to_thread
    try:
        import src.core.query_engine.query_processor  # noqa: F401
        import src.core.query_engine.hybrid_search  # noqa: F401
        import src.core.query_engine.dense_retriever  # noqa: F401
        import src.core.query_engine.sparse_retriever  # noqa: F401
        import src.core.query_engine.reranker  # noqa: F401
        import src.ingestion.storage.bm25_indexer  # noqa: F401
        import src.libs.embedding.embedding_factory  # noqa: F401
        import src.libs.vector_store.vector_store_factory  # noqa: F401
    except ImportError:
        pass


async def run_stdio_server_async(*, settings_path=None, artifact_store_path=None) -> int:
    """Run MCP server over stdio asynchronously.

    Returns:
        Exit code.
    """
    # Import here to avoid import errors if mcp not installed
    import mcp.server.stdio
    import anyio
    from src.core.settings import load_settings, require_storage_path
    from src.mcp_server.protocol_handler import ProtocolHandler
    from src.mcp_server.safety import Redactor, install_log_redaction
    from src.mod_agent.artifacts import ArtifactStore

    settings = load_settings(settings_path)
    redactor = Redactor.configured(settings)
    install_log_redaction(redactor)
    artifact_store = None
    if artifact_store_path is not None:
        from types import SimpleNamespace
        root = Path(artifact_store_path)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("MCP_ARTIFACT_STORE_MUST_EXIST")
        require_storage_path(SimpleNamespace(storage_root=str(root)), root)
        artifact_store = ArtifactStore(root)

    # Ensure ALL logging goes to stderr (stdout is reserved for JSON-RPC)
    _redirect_all_loggers_to_stderr()

    # Pre-load heavy deps in main thread to prevent import-lock deadlocks
    # when tool handlers later call asyncio.to_thread().
    _preload_heavy_imports()

    logger = get_logger(log_level="INFO")
    logger.info("Starting MCP server (stdio transport) with official SDK.")

    # Create server with protocol handler
    protocol = ProtocolHandler(SERVER_NAME, SERVER_VERSION, redactor=redactor)
    server = create_mcp_server(SERVER_NAME, SERVER_VERSION, protocol_handler=protocol,
                               settings=settings, artifact_store=artifact_store)
    identity = subprocess.run(["whoami"], capture_output=True, text=True, check=False, timeout=5)
    logger.info("MCP execution boundary %s", json.dumps({
        "pid": os.getpid(), "os_identity": identity.stdout.strip() if identity.returncode == 0 else "unavailable",
        "knowledge_store": str(require_storage_path(settings, settings.vector_store.persist_directory)),
        "artifact_store": str(artifact_store.root) if artifact_store is not None else None,
        "os_sandbox_claimed": False, "inherits_process_environment": True,
        "outbound": "configured query providers only; stdio transport has no remote listener"}))

    # Run with stdio transport
    protocol_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        async with mcp.server.stdio.stdio_server(stdout=anyio.wrap_file(protocol_stdout)) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        pending = getattr(protocol, "cancel_pending", lambda: 0)()
        logger.info("MCP stopped accepting requests; cancellation requested for %d local calls; provider termination unknown", pending)
        sys.stdout = protocol_stdout

    logger.info("MCP server shutting down.")
    return 0


def run_stdio_server(**kwargs) -> int:
    """Run MCP server over stdio (synchronous wrapper).

    Returns:
        Exit code.
    """
    return asyncio.run(run_stdio_server_async(**kwargs))


def main(argv=None) -> int:
    """Entry point for stdio MCP server."""
    from src.mcp_server.safety import Redactor, RedactingTextStream
    original_stderr = sys.stderr
    sys.stderr = RedactingTextStream(original_stderr, Redactor.configured())
    parser = argparse.ArgumentParser(description="Local stdio knowledge and read-only artifact MCP server")
    parser.add_argument("--settings")
    parser.add_argument("--artifact-store", help="Existing absolute artifact store directory; exposes read-only artifact tools")
    protocol_stdout = sys.stdout
    try:
        args = parser.parse_args(argv)
        # 为什么要有它：第三方导入和业务print不能写进stdio协议，SDK获得独立的原stdout句柄。
        sys.stdout = sys.stderr
        _preload_heavy_imports()
        sys.stdout = protocol_stdout
        return run_stdio_server(settings_path=args.settings, artifact_store_path=args.artifact_store)
    except (OSError, ValueError, RuntimeError) as error:
        print("MCP_STARTUP_FAILED: " + type(error).__name__, file=sys.stderr)
        return 2
    finally:
        sys.stdout = protocol_stdout
        sys.stderr = original_stderr


if __name__ == "__main__":
    sys.exit(main())
