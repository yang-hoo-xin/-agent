"""Compatibility entry point for the actual SDK-based stdio MCP server."""

import sys


def main() -> int:
    """Keep ``python main.py`` on the same protocol-only entry as installation."""
    from src.mcp_server.server import main as server_main

    return server_main()


if __name__ == "__main__":
    sys.exit(main())
