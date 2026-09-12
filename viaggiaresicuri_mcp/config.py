"""Endpoint e parametri di rete della fonte.

Tutto è sovrascrivibile da variabile d'ambiente: serve per puntare il server a un doppio della
fonte e provare gli scenari di guasto (payload alterato, timeout) senza toccare il codice.
"""

from __future__ import annotations

import os
from pathlib import Path

# `var/` con la cache sta accanto al pacchetto, in radice di progetto.
ROOT = Path(__file__).resolve().parent.parent
# L'indice semantico invece è un asset *del pacchetto*, risolto rispetto al modulo e non alla
# radice: così funziona anche installato in site-packages, dove una radice di progetto non c'è.
DATA = Path(__file__).resolve().parent / "data"

BASE_URL = os.getenv("VS_BASE_URL", "https://www.viaggiaresicuri.it").rstrip("/")
USER_AGENT = os.getenv(
    "VS_USER_AGENT", "travelanalyst-mcp/0.1 (assistente interno; contatto: customercare)"
)

TIMEOUT_SECONDS = float(os.getenv("VS_TIMEOUT_SECONDS", "15"))
MAX_ATTEMPTS = int(os.getenv("VS_MAX_ATTEMPTS", "3"))
BACKOFF_SECONDS = float(os.getenv("VS_BACKOFF_SECONDS", "0.5"))
MAX_CONNECTIONS = int(os.getenv("VS_MAX_CONNECTIONS", "8"))

# Cache persistente dei payload. Il TTL è la soglia oltre la quale si *tenta* una rivalidazione,
# non un'età alla quale la entry viene buttata: vedi cache.py. 6 ore è un compromesso unico su
# contenuti con ritmi molto diversi — il limite è dichiarato nel README.
CACHE_ENABLED = os.getenv("VS_CACHE_ENABLED", "true").strip().lower() not in ("0", "false", "no")
CACHE_TTL_SECONDS = int(os.getenv("VS_CACHE_TTL_SECONDS", "21600"))
# L'unica eccezione al TTL unico, e resta un'eccezione: non c'è un sistema di TTL per tipo di
# contenuto, c'è questo endpoint. Motivazione nell'ADR del README — non è la frequenza di
# aggiornamento (le allerte si muovono a settimane) ma l'asimmetria del costo d'errore.
ALERTS_TTL_SECONDS = int(os.getenv("VS_ALERTS_TTL_SECONDS", "900"))

CACHE_PATH = Path(os.getenv("VS_CACHE_PATH", str(ROOT / "var" / "cache.sqlite3")))


def countries_path() -> str:
    return "/schede_paese/lista_nazioni.json"


def sheet_path(iso3: str) -> str:
    return f"/schede_paese/{iso3}.json"


def alerts_path(iso3: str) -> str:
    return f"/ultima_ora/{iso3}.json"


def all_alerts_path() -> str:
    return "/ultima_ora/totale.json"


def page_url(iso3: str) -> str:
    return f"{BASE_URL}/find-country/country/{iso3}"


def alerts_url(iso3: str) -> str:
    return f"{BASE_URL}{alerts_path(iso3)}"


def sheet_url(iso3: str) -> str:
    return f"{BASE_URL}{sheet_path(iso3)}"


def sheet_pdf_url(iso3: str) -> str:
    return f"{BASE_URL}/schede_paese/pdf/{iso3}.pdf"


def contacts_pdf_url(iso3: str) -> str:
    return f"{BASE_URL}/schede_paese/pdf/{iso3}_contactDetails.pdf"
