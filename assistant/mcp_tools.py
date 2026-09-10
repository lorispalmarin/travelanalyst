"""Ponte fra il server MCP e i tool di LangChain.

Perché non `langchain-mcp-adapters`: la libreria, anche all'ultima versione, richiede `mcp<2.0`,
mentre FastMCP 4 richiede `mcp>=2`. Le due cose non stanno insieme in nessuna combinazione di
versioni, e installarle nello stesso ambiente retrocede `mcp` rompendo il server. Fra il
retrocedere FastMCP e lo scrivere questa cinquantina di righe, la seconda costa meno e non
vincola il server alle versioni di una libreria di terze parti.

Il ponte non definisce nessun tool: li legge da quelli che il server pubblica. È anche la
garanzia che l'assistente non possa usare nient'altro, che è il vincolo dello scenario.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport
from langchain_core.tools import StructuredTool

from .config import Settings

logger = logging.getLogger(__name__)


def _testo_del_risultato(risultato: Any) -> str:
    pezzi: list[str] = []
    for blocco in getattr(risultato, "content", None) or []:
        testo = getattr(blocco, "text", None)
        if testo:
            pezzi.append(testo)
    if pezzi:
        return "\n".join(pezzi)
    dati = getattr(risultato, "data", None)
    return "" if dati is None else str(dati)


def _costruisci_tool(client: Client, spec: Any) -> StructuredTool:
    nome = spec.name

    async def esegui(**argomenti: Any) -> str:
        risultato = await client.call_tool(nome, argomenti, raise_on_error=False)
        testo = _testo_del_risultato(risultato)
        if getattr(risultato, "is_error", False):
            # L'errore torna al modello come contenuto, non come eccezione: deve poterlo leggere
            # e reagire — se il Paese è ambiguo la risposta giusta è chiedere all'operatore,
            # non interrompere la conversazione.
            logger.info("tool %s ha risposto con errore: %s", nome, testo[:120])
            return f"ERRORE DEL TOOL: {testo}"
        return testo

    return StructuredTool(
        name=nome,
        description=spec.description or "",
        args_schema=getattr(spec, "input_schema", None) or spec.inputSchema,
        coroutine=esegui,
    )


@asynccontextmanager
async def tool_del_server(settings: Settings) -> AsyncIterator[list[StructuredTool]]:
    """Avvia il server MCP come processo separato e ne espone i tool a LangChain."""
    transport = PythonStdioTransport(
        script_path=settings.server_script,
        python_cmd=settings.python_executable,
    )
    async with Client(transport) as client:
        specifiche = await client.list_tools()
        tools = [_costruisci_tool(client, spec) for spec in specifiche]
        logger.info("caricati %s tool dal server MCP", len(tools))
        yield tools
