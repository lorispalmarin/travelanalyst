"""Entry point del server MCP.

    python server.py
    python -m viaggiaresicuri_mcp.server
"""

from viaggiaresicuri_mcp.server import main, mcp

__all__ = ["mcp", "main"]


if __name__ == "__main__":
    main()
