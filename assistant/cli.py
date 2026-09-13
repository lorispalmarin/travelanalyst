"""CLI dell'assistente: una REPL che mostra anche quali tool sta usando.

Il trace dei tool non è decorativo: serve a far vedere — in demo e in debug — che la risposta
viene dal server MCP e non dalla memoria del modello.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .agent import Assistente, apri_assistente
from .config import ConfigurazioneMancante, carica

GRIGIO, GIALLO, VERDE, ROSSO, RESET, BOLD = (
    "\033[90m", "\033[33m", "\033[32m", "\033[31m", "\033[0m", "\033[1m",
)

AIUTO = """
Comandi:
  /nuovo    dimentica la conversazione e riparte da zero
  /tool     elenca i tool disponibili sul server
  /aiuto    questo messaggio
  /esci     esce (anche Ctrl-D)

Esempi di domande:
  Che documenti servono per la Thailandia?
  Un cliente ha perso il passaporto a Valona, chi contatto?
  Posso portare i miei farmaci negli Emirati?
  Si può partire per la Thailandia adesso?
""".strip()


def _silenzia_log() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    for nome in ("httpx", "httpcore", "mcp", "fastmcp", "openai"):
        logging.getLogger(nome).setLevel(logging.WARNING)


async def _leggi(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def _rispondi(assistente: Assistente, domanda: str) -> None:
    in_testo = False
    try:
        async for tipo, pezzo in assistente.eventi(domanda):
            if tipo == "tool":
                print(f"{GRIGIO}  → {pezzo}{RESET}", file=sys.stderr, flush=True)
            elif tipo == "avviso":
                # arriva prima del testo per costruzione: vedi assistant/freshness.py
                print(f"\n{GIALLO}{pezzo}{RESET}")
            elif tipo == "testo" and pezzo:
                if not in_testo:
                    print()
                    in_testo = True
                print(pezzo, end="", flush=True)
    except Exception as exc:  # la CLI non deve morire per una domanda andata storta
        print(f"\n{ROSSO}Errore durante la risposta: {type(exc).__name__}: {exc}{RESET}")
        return
    print("\n" if in_testo else f"{GRIGIO}(nessuna risposta){RESET}")


async def repl() -> int:
    _silenzia_log()
    try:
        settings = carica()
    except ConfigurazioneMancante as exc:
        print(f"{ROSSO}{exc}{RESET}", file=sys.stderr)
        return 2

    print(f"{GRIGIO}connessione al server MCP…{RESET}", file=sys.stderr)
    try:
        async with apri_assistente(settings) as assistente:
            print(f"\n{BOLD}Assistente Viaggiare Sicuri{RESET}")
            print(f"{GRIGIO}{settings.descrizione} · {len(assistente.tools)} tool · /aiuto per i comandi{RESET}\n")

            while True:
                try:
                    domanda = (await _leggi(f"{VERDE}› {RESET}")).strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 0

                if not domanda:
                    continue
                if domanda in ("/esci", "/quit", "/exit"):
                    return 0
                if domanda == "/aiuto":
                    print(AIUTO)
                    continue
                if domanda == "/tool":
                    for nome in assistente.nomi_tool:
                        print(f"  {nome}")
                    continue
                if domanda == "/nuovo":
                    assistente.nuova_conversazione()
                    print(f"{GRIGIO}conversazione azzerata{RESET}")
                    continue

                await _rispondi(assistente, domanda)
    except Exception as exc:
        print(f"{ROSSO}Impossibile avviare l'assistente: {type(exc).__name__}: {exc}{RESET}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(asyncio.run(repl()))


if __name__ == "__main__":
    main()
