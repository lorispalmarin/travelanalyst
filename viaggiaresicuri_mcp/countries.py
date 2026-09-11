"""Risoluzione del paese: da quello che scrive l'operatore al codice ISO3 usato dagli endpoint.

La fonte usa nomi ufficiali italiani, che spesso non contengono il nome comune: la Cina è
"Repubblica Popolare Cinese" e la Russia "Federazione Russa". Il fuzzy matching da solo non
basta, quindi c'è una tabella di alias per i casi dove italiano, inglese e parlato divergono.

Quando la richiesta è ambigua non si indovina: si restituiscono i candidati.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata

from rapidfuzz import fuzz, process

from .config import countries_path
from .errors import CountryNotFound, UnexpectedPayload
from .client import fetch
from .models import CountryMatch, CountryRef

# Alias -> ISO3. Coperti i casi dove il nome della fonte non contiene il nome comune,
# le forme inglesi che il fuzzy sbaglierebbe, e il parlato del customer care.
ALIASES: dict[str, str] = {
    "usa": "USA", "stati uniti": "USA", "united states": "USA",
    "united states of america": "USA", "america": "USA",
    "uk": "GBR", "united kingdom": "GBR", "gran bretagna": "GBR",
    "inghilterra": "GBR", "england": "GBR", "britain": "GBR",
    "cina": "CHN", "china": "CHN",
    "russia": "RUS",
    "olanda": "NLD", "holland": "NLD", "netherlands": "NLD",
    "corea del sud": "KOR", "south korea": "KOR",
    "corea del nord": "PRK", "north korea": "PRK",
    "japan": "JPN", "germany": "DEU", "spain": "ESP", "france": "FRA",
    "switzerland": "CHE", "sweden": "SWE", "norway": "NOR", "denmark": "DNK",
    "poland": "POL", "hungary": "HUN", "greece": "GRC", "egypt": "EGY",
    "portugal": "PRT", "belgium": "BEL", "ireland": "IRL", "iceland": "ISL",
    "croatia": "HRV", "turkey": "TUR", "turkiye": "TUR", "ukraine": "UKR",
    "israel": "ISR", "morocco": "MAR", "brazil": "BRA", "mexico": "MEX",
    "thailand": "THA", "new zealand": "NZL", "cambodia": "KHM", "maldives": "MDV",
    "sudafrica": "ZAF", "south africa": "ZAF",
    "saudi arabia": "SAU", "arabia saudita": "SAU",
    "repubblica ceca": "CZE", "czech republic": "CZE", "czechia": "CZE", "cechia": "CZE",
    "costa d avorio": "CIV", "ivory coast": "CIV",
    "emirati": "ARE", "emirati arabi": "ARE", "uae": "ARE", "dubai": "ARE", "abu dhabi": "ARE",
    "birmania": "MMR", "burma": "MMR",
    "dominican republic": "DOM", "cape verde": "CPV",
    # Località e isole che l'operatore nomina al posto del Paese. Senza queste, "Ibiza"
    # finirebbe sul fuzzy e il candidato più vicino sarebbe la Libia.
    "bali": "IDN", "zanzibar": "TZA",
    "ibiza": "ESP", "maiorca": "ESP", "majorca": "ESP", "minorca": "ESP",
    "baleari": "ESP", "canarie": "ESP", "tenerife": "ESP", "fuerteventura": "ESP",
    "lanzarote": "ESP", "gran canaria": "ESP",
    "madeira": "PRT", "azzorre": "PRT",
    "creta": "GRC", "rodi": "GRC", "santorini": "GRC", "mykonos": "GRC", "corfu": "GRC",
    "sharm el sheikh": "EGY", "hurghada": "EGY", "marsa alam": "EGY",
    "phuket": "THA", "koh samui": "THA", "bangkok": "THA",
    "marrakech": "MAR", "sharm": "EGY",
    "new york": "USA", "miami": "USA", "california": "USA",
    "londra": "GBR", "parigi": "FRA", "barcellona": "ESP", "madrid": "ESP",
}


def fold(text: str) -> str:
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
        if folded in ALIASES:
            return CountryMatch(match=self._by_iso3[ALIASES[folded]], confidence="alias")
        if folded in self._folded:
            return CountryMatch(match=self._folded[folded], confidence="exact")

        contained = [ref for name, ref in self._folded.items() if folded in name]
        if len(contained) == 1:
            return CountryMatch(match=contained[0], confidence="alias")
        if len(contained) > 1:
            return CountryMatch(candidates=contained[:8])

        scored = process.extract(folded, self._names, scorer=fuzz.WRatio, limit=5)
        if not scored:
            raise CountryNotFound(query)

        best_name, best_score, _ = scored[0]
        runner_up = scored[1][1] if len(scored) > 1 else 0
        if best_score >= 90 and best_score - runner_up >= 8:
            return CountryMatch(match=self._folded[best_name], confidence="fuzzy")

        # Un solo candidato debole non è un'ambiguità, è un match che non regge: proporlo
        # sarebbe peggio del silenzio. "Ibiza" assomiglia a "Libia" all'80%, e suggerire la
        # Libia a chi parte per le Baleari non è un errore neutro. I refusi veri stanno sopra 90
        # con distacco netto (tailandia/thailandia = 95).
        plausibili = [self._folded[name] for name, score, _ in scored if score >= 85]
        if len(plausibili) < 2:
            raise CountryNotFound(query)
        return CountryMatch(candidates=plausibili)


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
