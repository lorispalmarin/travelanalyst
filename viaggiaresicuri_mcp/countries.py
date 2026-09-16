"""Risoluzione del paese: dal nome al codice ISO3 usato dagli endpoint.
Quando la richiesta è ambigua non si sceglie: si restituiscono i candidati.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata

from .config import countries_path
from .errors import CountryNotFound, UnexpectedPayload
from .client import fetch
from .models import CountryMatch, CountryRef


def _contiene_parola(nome: str, pezzo: str) -> bool:
    return re.search(rf"\b{re.escape(pezzo)}\b", nome) is not None


def fold(text: str) -> str:
    """ 
    Normalizzazione del testo 
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", stripped.lower())).strip()


class CountryIndex:
    def __init__(self, records: list[dict]) -> None:
        self.refs = [
            CountryRef(name=r["Nome"], iso3=r["Codice-3"], iso2=r["Codice-2"])
            for r in records
            if r.get("Nome") and r.get("Codice-3")
        ]
        self._by_iso3 = {ref.iso3.upper(): ref for ref in self.refs}
        self._by_iso2 = {ref.iso2.upper(): ref for ref in self.refs if ref.iso2}
        self._folded = {fold(ref.name): ref for ref in self.refs}
        self._names = list(self._folded)

    def all(self) -> list[CountryRef]:
        return list(self.refs)

    def by_iso3(self, iso3: str) -> CountryRef | None:
        return self._by_iso3.get(iso3.upper())

    def resolve(self, query: str) -> CountryMatch:
        raw = (query or "").strip()
        if not raw:
            raise CountryNotFound(query)
        folded = fold(raw)

        if len(raw) == 3 and raw.upper() in self._by_iso3:
            return CountryMatch(match=self._by_iso3[raw.upper()], confidence="exact")
        if len(raw) == 2 and raw.upper() in self._by_iso2:
            return CountryMatch(match=self._by_iso2[raw.upper()], confidence="exact")
        if folded in self._folded:
            return CountryMatch(match=self._folded[folded], confidence="exact")

        parziali = [ref for nome, ref in self._folded.items() if _contiene_parola(nome, folded)]
        if len(parziali) == 1:
            return CountryMatch(match=parziali[0], confidence="partial")
        if len(parziali) > 1:
            return CountryMatch(candidates=parziali[:8])

        raise CountryNotFound(query)


_index: CountryIndex | None = None
_lock = asyncio.Lock()


async def get_index() -> CountryIndex:
    """L'elenco paesi è una risorsa di bootstrap: si scarica una volta e resta in memoria.

    Il memo in processo non sostituisce la cache su disco: passa comunque da `client.fetch`,
    così dopo un riavvio con la fonte giù i nomi dei Paesi si risolvono lo stesso. Sono 222
    record che cambiano raramente e servono a ogni singola chiamata per tradurre il nome in ISO3.
    """
    global _index
    if _index is None:
        async with _lock:
            if _index is None:
                payload = (await fetch(countries_path())).payload
                if not isinstance(payload, list) or not payload:
                    raise UnexpectedPayload("lista_nazioni.json non è una lista popolata")
                _index = CountryIndex(payload)
    return _index


def reset_index() -> None:
    global _index
    _index = None
