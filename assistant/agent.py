"""Costruzione dell'assistente: modello LangChain + tool del server MCP.

Il server gira come processo separato via stdio, non importato in-process: è la configurazione
che userebbe un cliente vero, ed è l'unica che dimostra che il server funziona anche fuori da
questo codice. I tool non sono scritti a mano ma generati dagli schemi che il server pubblica,
quindi l'assistente non può usare nient'altro che quelli — che è il vincolo dello scenario.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from .config import Settings, carica
from .mcp_tools import tool_del_server
from .prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def costruisci_modello(settings: Settings) -> ChatOpenAI:
    parametri: dict[str, Any] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "use_responses_api": settings.use_responses_api,
    }
    if settings.base_url:
        parametri["base_url"] = settings.base_url
    reasoning: dict[str, Any] = {}
    if settings.reasoning_effort:
        reasoning["effort"] = settings.reasoning_effort
    if settings.reasoning_summary and settings.use_responses_api:
        reasoning["summary"] = settings.reasoning_summary
    if reasoning:
        parametri["reasoning"] = reasoning
    # niente temperature: gpt-5.6-luna accetta solo il valore di default
    return ChatOpenAI(**parametri)


@dataclass
class Risposta:
    testo: str
    tool_usati: list[str]


class Assistente:
    """Un agente con i suoi tool, già collegato al server MCP."""

    def __init__(self, agent: Any, tools: Sequence[BaseTool], settings: Settings) -> None:
        self._agent = agent
        self.tools = list(tools)
        self.settings = settings
        self._thread = {
            "configurable": {"thread_id": "cli"},
            "recursion_limit": settings.max_steps * 2,
        }

    @property
    def nomi_tool(self) -> list[str]:
        return [t.name for t in self.tools]

    def nuova_conversazione(self) -> None:
        """Cambia thread: lo storico precedente non entra più nel contesto."""
        precedente = self._thread["configurable"]["thread_id"]
        numero = int(precedente.rsplit("-", 1)[-1]) + 1 if "-" in precedente else 1
        self._thread["configurable"]["thread_id"] = f"cli-{numero}"

    async def chiedi(self, domanda: str) -> Risposta:
        stato = await self._agent.ainvoke(
            {"messages": [HumanMessage(content=domanda)]}, config=self._thread
        )
        messaggi: list[BaseMessage] = stato["messages"]
        return Risposta(testo=_ultimo_testo(messaggi), tool_usati=_tool_chiamati(messaggi))

    async def traccia(self, domanda: str) -> AsyncIterator[dict[str, Any]]:
        """Emette gli eventi dell'agente man mano che accadono.

        Il ragionamento arriva dal canale `updates` a passo concluso (il reasoning grezzo del
        modello è cifrato, il riassunto no), il testo della risposta dal canale `messages` token
        per token. Sono due flussi con tempi diversi: la UI li tiene in due pannelli distinti
        proprio per questo.
        """
        async for modalita, pezzo in self._agent.astream(
            {"messages": [HumanMessage(content=domanda)]},
            config=self._thread,
            stream_mode=["updates", "messages"],
        ):
            if modalita == "updates":
                for _nodo, dati in (pezzo or {}).items():
                    for messaggio in (dati or {}).get("messages", []) or []:
                        for testo in _ragionamenti(messaggio):
                            yield {"tipo": "ragionamento", "testo": testo}
                        for chiamata in getattr(messaggio, "tool_calls", None) or []:
                            yield {
                                "tipo": "tool_call",
                                "nome": chiamata.get("name"),
                                "argomenti": chiamata.get("args") or {},
                            }
                        if isinstance(messaggio, ToolMessage):
                            contenuto = messaggio.content if isinstance(messaggio.content, str) else str(messaggio.content)
                            yield {
                                "tipo": "tool_result",
                                "nome": messaggio.name,
                                "caratteri": len(contenuto),
                                "errore": contenuto.startswith("ERRORE DEL TOOL"),
                                "anteprima": contenuto[:2000],
                            }
            elif modalita == "messages":
                messaggio = pezzo[0] if isinstance(pezzo, tuple) else pezzo
                testo = _testo_di(messaggio)
                if testo and isinstance(messaggio, AIMessage):
                    yield {"tipo": "testo", "delta": testo}
        yield {"tipo": "fine"}

    async def eventi(self, domanda: str) -> AsyncIterator[tuple[str, str]]:
        """Versione semplificata per la CLI: ("tool", nome) e ("testo", pezzo)."""
        async for evento in self.traccia(domanda):
            if evento["tipo"] == "tool_call":
                yield "tool", evento["nome"]
            elif evento["tipo"] == "testo":
                yield "testo", evento["delta"]


def _testo_di(messaggio: BaseMessage) -> str:
    contenuto = getattr(messaggio, "content", "")
    if isinstance(contenuto, str):
        return contenuto
    pezzi = []
    for blocco in contenuto or []:
        if isinstance(blocco, str):
            pezzi.append(blocco)
        elif isinstance(blocco, dict) and blocco.get("type") == "text":
            pezzi.append(blocco.get("text", ""))
    return "".join(pezzi)


def _ragionamenti(messaggio: BaseMessage) -> list[str]:
    """I riassunti di ragionamento allegati a un messaggio, se il modello li espone."""
    contenuto = getattr(messaggio, "content", None)
    if not isinstance(contenuto, list):
        return []
    testi: list[str] = []
    for blocco in contenuto:
        if not isinstance(blocco, dict) or blocco.get("type") != "reasoning":
            continue
        for parte in blocco.get("summary") or []:
            testo = parte.get("text") if isinstance(parte, dict) else str(parte)
            if testo and testo.strip():
                testi.append(testo.strip())
    return testi


def _ultimo_testo(messaggi: Sequence[BaseMessage]) -> str:
    for messaggio in reversed(messaggi):
        if isinstance(messaggio, AIMessage):
            testo = _testo_di(messaggio).strip()
            if testo:
                return testo
    return ""


def _tool_chiamati(messaggi: Sequence[BaseMessage]) -> list[str]:
    nomi: list[str] = []
    for messaggio in messaggi:
        for chiamata in getattr(messaggio, "tool_calls", None) or []:
            nome = chiamata.get("name") if isinstance(chiamata, dict) else getattr(chiamata, "name", None)
            if nome:
                nomi.append(nome)
        if isinstance(messaggio, ToolMessage) and messaggio.name:
            nomi.append(messaggio.name)
    # dedup conservando l'ordine di chiamata
    visti: set[str] = set()
    return [n for n in nomi if not (n in visti or visti.add(n))]


@asynccontextmanager
async def apri_assistente(settings: Settings | None = None) -> AsyncIterator[Assistente]:
    """Avvia il server MCP, carica i tool e costruisce l'agente."""
    settings = settings or carica()

    async with tool_del_server(settings) as tools:
        agent = create_agent(
            model=costruisci_modello(settings),
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            checkpointer=InMemorySaver(),
            name="assistente-viaggiaresicuri",
        )
        yield Assistente(agent, tools, settings)
