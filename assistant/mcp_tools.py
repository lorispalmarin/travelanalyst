"""Connessione HTTP al server MCP e caricamento dei tool tramite l'adapter LangChain."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from .config import Settings


@asynccontextmanager
async def tool_del_server(settings: Settings) -> AsyncIterator[list[BaseTool]]:
    client = MultiServerMCPClient({
        "viaggiaresicuri": {"transport": "http", "url": settings.mcp_server_url},
    })
    async with client.session("viaggiaresicuri") as session:
        yield await load_mcp_tools(session)
