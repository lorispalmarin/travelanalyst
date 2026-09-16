"""
Endpoint e parametri di rete della fonte.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# `var/` con la cache sta qui accanto, in radice di progetto
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))

BASE_URL = os.getenv("VS_BASE_URL", "https://www.viaggiaresicuri.it").rstrip("/")
USER_AGENT = os.getenv(
    "VS_USER_AGENT", "travelanalyst-mcp (assistente interno customercare)"
)

# timeout connessione e tentativi a viaggiaresicuri
TIMEOUT_SECONDS = float(os.getenv("VS_TIMEOUT_SECONDS", "15"))
MAX_ATTEMPTS = int(os.getenv("VS_MAX_ATTEMPTS", "3"))
BACKOFF_SECONDS = float(os.getenv("VS_BACKOFF_SECONDS", "0.5"))
MAX_CONNECTIONS = int(os.getenv("VS_MAX_CONNECTIONS", "8"))

# cache persistente dei payload
CACHE_ENABLED = os.getenv("VS_CACHE_ENABLED", "true").strip().lower() not in ("0", "false", "no")
CACHE_TTL_SECONDS = int(os.getenv("VS_CACHE_TTL_SECONDS", "21600"))
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


def guide_path(nome: str) -> str:
    return f"/approfondimenti/{nome}.json"


def guide_url(nome: str) -> str:
    return f"{BASE_URL}{guide_path(nome)}"


def guide_page_url(nome: str) -> str:
    return f"{BASE_URL}/approfondimenti-insights/{nome}"
