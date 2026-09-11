"""Client HTTP verso Viaggiare Sicuri: un solo punto di rete per tutto il server.

Le eccezioni di httpx non escono da qui: vengono tradotte negli errori di `errors.py`,
così i tool non devono conoscere la libreria di trasporto.

Sopra il trasporto sta la cache (`cache.py`), con una semantica precisa:

    entry presente, età < TTL   -> si serve dalla cache, zero rete            (fresh)
    entry presente, età >= TTL  -> si tenta il refetch
                                     riuscito -> si aggiorna e si serve       (fresh)
                                     fallito  -> si serve la copia vecchia    (stale)
    entry assente,  refetch fallito -> errore esplicito, nessun ripiego

Il terzo caso è il solo in cui l'assistente non può rispondere, ed è giusto così: l'alternativa
sarebbe lasciare che il modello risponda a memoria su requisiti di ingresso e rischi di
sicurezza, che è esattamente quello che questo progetto esiste per impedire.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from .cache import Cache, Entry
from .config import (
    BACKOFF_SECONDS,
    BASE_URL,
    CACHE_ENABLED,
    CACHE_PATH,
    CACHE_TTL_SECONDS,
    MAX_ATTEMPTS,
    MAX_CONNECTIONS,
    TIMEOUT_SECONDS,
    USER_AGENT,
)
from .errors import SourceNotFound, SourceUnavailable, UnexpectedPayload

logger = logging.getLogger(__name__)

CacheStatus = Literal["fresh", "stale"]

_client: httpx.AsyncClient | None = None
_cache: Cache | None = None
_in_volo: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class Fetched:
    """Un payload più la sua provenienza. Chi lo riceve non deve indovinare quanto è vecchio."""

    payload: Any
    retrieved_at: datetime
    cache_status: CacheStatus
    age_seconds: int


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            limits=httpx.Limits(max_connections=MAX_CONNECTIONS),
            follow_redirects=True,
        )
    return _client


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache(CACHE_PATH)
    return _cache


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def url_for(path: str) -> str:
    """La chiave della cache: l'URL assoluto, così un cambio di BASE_URL non riusa le entry."""
    return f"{BASE_URL}{path}"


async def _scarica(path: str) -> tuple[str, Any]:
    """GET con retry su errori transitori. 404 e payload malformati non si ritentano.

    Restituisce il corpo grezzo *e* il payload decodificato: il primo è quello che finisce in
    cache, il secondo evita di riparsare. Un corpo che non è JSON non entra mai in cache.
    """
    client = get_client()
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.get(path)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            logger.warning("tentativo %s/%s fallito per %s: %s", attempt, MAX_ATTEMPTS, path, exc)
        else:
            if response.status_code == 404:
                raise SourceNotFound(f"{path} non esiste sulla fonte")
            if response.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}", request=response.request, response=response
                )
                logger.warning("tentativo %s/%s: %s ha risposto %s", attempt, MAX_ATTEMPTS, path,
                               response.status_code)
            elif response.status_code >= 400:
                raise SourceUnavailable(f"{path} ha risposto HTTP {response.status_code}")
            else:
                body = response.text
                try:
                    return body, json.loads(body)
                except (json.JSONDecodeError, ValueError) as exc:
                    raise UnexpectedPayload(f"{path} non ha restituito JSON valido") from exc

        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))

    raise SourceUnavailable(f"{path} non raggiungibile dopo {MAX_ATTEMPTS} tentativi") from last_error


async def fetch_json(path: str) -> Any:
    """Solo rete, nessuna cache. Resta il punto d'ingresso di chi vuole il dato di sicuro fresco."""
    _, payload = await _scarica(path)
    return payload


def _da_entry(entry: Entry, stato: CacheStatus) -> Fetched:
    return Fetched(
        payload=entry.payload(),
        retrieved_at=entry.retrieved_at,
        cache_status=stato,
        age_seconds=entry.age_seconds(),
    )


async def fetch(path: str, ttl_seconds: int | None = None) -> Fetched:
    """Il punto d'ingresso di tutto il server: payload + stato di freschezza.

    `ttl_seconds` abbassa la soglia di rivalidazione per questa chiamata. Serve a un solo
    chiamante — gli avvisi, che si rivalidano ogni 15 minuti invece di 6 ore — ed è di proposito
    un parametro e non una tabella di TTL per tipo di contenuto: le eccezioni si dichiarano dove
    si usano, e una sola eccezione non è un sistema.
    """
    ttl = CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if not CACHE_ENABLED:
        payload = await fetch_json(path)
        return Fetched(payload, datetime.now(UTC), "fresh", 0)

    url = url_for(path)
    # Una sola richiesta in volo per URL: due tool chiamati in parallelo sullo stesso Paese
    # leggono la stessa scheda, e duplicare la richiesta verso una fonte pubblica è gratuito
    # solo per noi.
    lucchetto = _in_volo.setdefault(url, asyncio.Lock())
    async with lucchetto:
        cache = get_cache()
        entry = await cache.get(url)

        if entry is not None:
            eta = entry.age_seconds()
            if eta < ttl:
                return _da_entry(entry, "fresh")

        try:
            body, payload = await _scarica(path)
        except SourceUnavailable as exc:
            # La fonte non risponde. Se abbiamo una copia la serviamo comunque, qualunque sia la
            # sua età: nessuna eviction l'ha rimossa proprio per questo momento. 404 e payload
            # non-JSON invece passano: sono la fonte che *risponde*, e coprirli con una copia
            # vecchia nasconderebbe un cambio di contratto.
            if entry is None:
                raise
            logger.warning(
                "fonte non raggiungibile (%s): servo la copia del %s per %s",
                exc, entry.retrieved_at.isoformat(timespec="seconds"), url,
            )
            return _da_entry(entry, "stale")

        aggiornata = await cache.put(url, body)
        return Fetched(payload, aggiornata.retrieved_at, "fresh", 0)
