"""Entry point del server MCP.

Serve ai launcher che caricano il server indicando un file — `fastmcp run server.py`, la
configurazione di Claude Desktop, i vari `mcp.json`. Quei launcher importano il file come
modulo isolato, quindi gli import relativi interni al pacchetto non funzionerebbero: qui si
importa il pacchetto per nome e si espone l'istanza `mcp` che il launcher cerca.

    fastmcp run server.py
    python server.py
    python -m viaggiaresicuri_mcp.server
"""

from viaggiaresicuri_mcp.server import main, mcp

__all__ = ["mcp", "main"]


if __name__ == "__main__":
    main()
