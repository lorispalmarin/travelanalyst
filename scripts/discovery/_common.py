"""Utility condivise dagli script di esplorazione delle fonti Viaggiare Sicuri."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from html import unescape

BASE = "https://www.viaggiaresicuri.it"
TIMEOUT = 30
UA = "travelanalyst-discovery/0.1"

SEZIONI = [
    "infoCronologiaAggiornamenti",
    "infoPrimopiano",
    "infoGenerali",
    "infoRequisitiIngresso",
    "infoSicurezza",
    "infoSituazioneSanitaria",
    "infoMobilita",
]


def fetch_json(path: str) -> dict | list:
    url = path if path.startswith("http") else f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_json_safe(path: str) -> tuple[dict | list | None, str | None]:
    try:
        return fetch_json(path), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, type(exc).__name__


def die(message: str, code: int = 1) -> None:
    print(f"errore: {message}", file=sys.stderr)
    raise SystemExit(code)


def load_countries() -> list[dict]:
    try:
        return fetch_json("/schede_paese/lista_nazioni.json")
    except Exception as exc:
        die(f"impossibile scaricare lista_nazioni.json ({exc})")


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def resolve_country(query: str, countries: list[dict] | None = None) -> dict:
    """Accetta ISO3, ISO2 o nome italiano (accenti e maiuscole indifferenti)."""
    countries = countries or load_countries()
    q = query.strip()
    qs = slug(q)

    for c in countries:
        if q.upper() == c["Codice-3"] or q.upper() == c["Codice-2"]:
            return c
    exact = [c for c in countries if slug(c["Nome"]) == qs]
    if exact:
        return exact[0]

    partial = [c for c in countries if qs and qs in slug(c["Nome"])]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        nomi = ", ".join(f"{c['Nome']} ({c['Codice-3']})" for c in partial[:12])
        die(f"'{query}' è ambiguo. Candidati: {nomi}", 2)
    die(f"nessun paese trovato per '{query}'", 2)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</li\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_links(html: str | None) -> list[tuple[str, str]]:
    if not html:
        return []
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        out.append((html_to_text(m.group(2)) or "(senza testo)", m.group(1)))
    return out


def rule(title: str = "", width: int = 88) -> None:
    if title:
        print(f"\n{'=' * width}\n{title}\n{'=' * width}")
    else:
        print("-" * width)


def preview(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + " [...]"


def pdf_urls(iso3: str) -> dict[str, str]:
    return {
        "scheda": f"{BASE}/schede_paese/pdf/{iso3}.pdf",
        "contatti": f"{BASE}/schede_paese/pdf/{iso3}_contactDetails.pdf",
        "pagina": f"{BASE}/find-country/country/{iso3}",
    }
