"""Interfaccia web dell'assistente.

Una pagina sola, che mostra da un lato il ragionamento del modello e le chiamate ai tool MCP
mentre accadono, dall'altro la risposta che si compone token per token. Serve a rendere
verificabile a occhio quello che l'assistente sta facendo: da dove viene ogni informazione.

    uvicorn assistant.web:app --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from .agent import Assistente, apri_assistente
from .config import ConfigurazioneMancante, carica

logger = logging.getLogger(__name__)

PAGINA = Path(__file__).parent / "static" / "index.html"

_stato: dict[str, object] = {}
_lucchetto = asyncio.Lock()


@asynccontextmanager
async def ciclo_di_vita(app: FastAPI) -> AsyncIterator[None]:
    """Il server MCP resta acceso per tutta la vita dell'applicazione."""
    settings = carica()
    async with apri_assistente(settings) as assistente:
        _stato["assistente"] = assistente
        logger.info("assistente pronto: %s", settings.descrizione)
        yield
    _stato.clear()


app = FastAPI(title="Assistente Viaggiare Sicuri", lifespan=ciclo_di_vita)


def _assistente() -> Assistente:
    assistente = _stato.get("assistente")
    if assistente is None:
        raise RuntimeError("assistente non inizializzato")
    return assistente  # type: ignore[return-value]


@app.get("/", response_class=HTMLResponse)
async def pagina() -> str:
    return PAGINA.read_text(encoding="utf-8")


@app.get("/api/stato")
async def stato() -> dict[str, object]:
    assistente = _assistente()
    return {
        "modello": assistente.settings.descrizione,
        "tool": assistente.nomi_tool,
    }


@app.post("/api/nuova")
async def nuova() -> dict[str, bool]:
    _assistente().nuova_conversazione()
    return {"ok": True}


def _sse(evento: dict[str, object]) -> str:
    return f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"


@app.get("/api/chiedi")
async def chiedi(domanda: str, request: Request) -> StreamingResponse:
    async def flusso() -> AsyncIterator[str]:
        # Una domanda alla volta: l'agente ha uno stato di conversazione condiviso. Il rilascio
        # è in un finally esplicito perché un client che chiude la connessione a metà chiude
        # anche questo generatore, e un lucchetto rimasto preso bloccherebbe tutte le domande
        # successive.
        if _lucchetto.locked():
            yield _sse({"tipo": "errore", "messaggio": "Un'altra domanda è già in corso."})
            return
        await _lucchetto.acquire()
        try:
            async for evento in _assistente().traccia(domanda):
                if await request.is_disconnected():
                    break
                yield _sse(evento)
        except ConfigurazioneMancante as exc:
            yield _sse({"tipo": "errore", "messaggio": str(exc)})
        except Exception as exc:  # la pagina deve dire cosa è andato storto
            logger.exception("errore durante la risposta")
            yield _sse({"tipo": "errore", "messaggio": f"{type(exc).__name__}: {exc}"})
        finally:
            _lucchetto.release()

    return StreamingResponse(
        flusso(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    """Avvia il server.

    Il default resta `127.0.0.1`, così un'esecuzione locale non si espone alla rete per
    distrazione. In un container serve invece `0.0.0.0`, altrimenti la porta pubblicata non
    raggiunge niente: è il Dockerfile a impostare `WEB_HOST`, non questo default.
    """
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        app,
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("WEB_PORT", "8000")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
