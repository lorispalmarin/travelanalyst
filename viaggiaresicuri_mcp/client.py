"""Client HTTP verso Viaggiare Sicuri: un solo punto di rete per tutto il server.

Le eccezioni di httpx non escono da qui: vengono tradotte negli errori di `errors.py`,
così i tool non devono conoscere la libreria di trasporto.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from .config import (
    BACKOFF_SECONDS,
    BASE_URL,
    MAX_ATTEMPTS,
    MAX_CONNECTIONS,
    TIMEOUT_SECONDS,
    USER_AGENT,
)
from .errors import SourceNotFound, SourceUnavailable, UnexpectedPayload

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


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


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def fetch_json(path: str) -> Any:
    """GET con retry su errori transitori. 404 e payload malformati non si ritentano."""
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
                try:
                    return response.json()
                except (json.JSONDecodeError, ValueError) as exc:
                    raise UnexpectedPayload(f"{path} non ha restituito JSON valido") from exc

        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(BACKOFF_SECONDS * 2 ** (attempt - 1))

    raise SourceUnavailable(f"{path} non raggiungibile dopo {MAX_ATTEMPTS} tentativi") from last_error
