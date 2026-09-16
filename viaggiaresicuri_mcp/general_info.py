"""Ricerca full-text nelle guide tematiche, le sole informazioni della fonte non legate a un Paese.

JSON della guida -> validazione -> sezioni appiattite -> indice BM25 in memoria -> prime `top_k`.
Niente embedding e niente artefatti su disco: l'indice si costruisce dal payload servito dal client.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import Counter
from typing import Any

from pydantic import ValidationError

from .client import fetch
from .config import guide_page_url, guide_path, guide_url
from .countries import fold
from .errors import UnexpectedPayload
from .models import GuideHit, GuideNode, GuideSection, Link, Meta, Source
from .normalize import extract_links, html_to_text, link_kind

# Le due guide che il sito pubblica oggi sotto /approfondimenti-insights, con il titolo che usa
# la navigazione: la radice del JSON porta solo il nome tecnico.
GUIDE: dict[str, str] = {
    "preparaunviaggio": "Preparare un viaggio",
    "documentidiviaggio": "Documenti di viaggio",
}

MAX_RISULTATI = 5
K1 = 1.2
B = 0.75

# La redazione corregge i refusi barrandoli invece di cancellarli: "punge <s>p</s>l'uomo".
_BARRATO = re.compile(r"(?is)<s\b[^>]*>.*?</s\s*>")
_VOCALI_FINALI = re.compile(r"[aeiou]+$")

STOPWORDS = frozenset("""
il lo la gli le un uno una
di da in su per tra fra con col coi
del dello della dei degli delle dell al allo alla ai agli alle all
dal dallo dalla dai dagli dalle dall nel nello nella nei negli nelle nell
sul sullo sulla sui sugli sulle sull
ed od ma se che anche come ne pero oppure quindi cioe
mi ti si ci vi me te io tu lui lei noi voi loro
suo sua suoi sue mio mia miei mie tuo tua tuoi tue
questo questa questi queste quello quella quelli quelle quel quest
cui chi cosa cos quale quali qual quanto quanta quanti quante quando dove perche
sono sia siano essere ho hai ha abbiamo avete hanno avere
puo possono posso devo deve devono serve servono bisogna fare
non piu po molto gia ancora solo
""".split())


def sources() -> list[Source]:
    return [Source(page=guide_page_url(nome), data=guide_url(nome)) for nome in GUIDE]


def tokenize(testo: str) -> list[str]:
    """Minuscole senza accenti, senza parole vuote, singolare e plurale sulla stessa radice."""
    return [_radice(p) for p in fold(testo).split() if len(p) > 1 and p not in STOPWORDS]


def _radice(parola: str) -> str:
    radice = _VOCALI_FINALI.sub("", parola)
    return radice if len(radice) >= 3 else parola


def parse_guide(payload: Any, nome: str) -> list[GuideNode]:
    radice = payload.get(nome) if isinstance(payload, dict) else None
    if not isinstance(radice, list) or not radice:
        raise UnexpectedPayload(f"la guida {nome} non ha la lista '{nome}' in radice")
    try:
        return [GuideNode.model_validate(nodo) for nodo in radice]
    except ValidationError as exc:
        raise UnexpectedPayload(
            f"la guida {nome} non ha la forma attesa: "
            f"{'.'.join(str(p) for p in exc.errors()[0]['loc'])}"
        ) from exc


def _breadcrumb(parti: list[str]) -> str:
    # In `documentidiviaggio` l'unico contenitore si chiama come la guida.
    tenute = [p for i, p in enumerate(parti) if i == 0 or p.casefold() != parti[i - 1].casefold()]
    return " > ".join(tenute)


def flatten(nome: str, nodi: list[GuideNode], antenati: tuple[str, ...] = ()) -> list[GuideSection]:
    """Le sezioni con testo, in ordine d'albero. Un contenitore vuoto non è una sezione ma si attraversa."""
    sezioni: list[GuideSection] = []
    for nodo in nodi:
        percorso = (*antenati, nodo.title.strip())
        html = _BARRATO.sub("", nodo.html)
        testo = html_to_text(html)
        if testo:
            sezioni.append(
                GuideSection(
                    id=f"{nome}/{nodo.id}",
                    breadcrumb=_breadcrumb([GUIDE[nome], *percorso]),
                    title=percorso[-1],
                    text=testo,
                    links=[Link(text=t, url=u, kind=link_kind(u)) for t, u in extract_links(html)],
                    page=guide_page_url(nome),
                )
            )
        sezioni.extend(flatten(nome, nodo.children, percorso))
    return sezioni


class FullTextIndex:
    """BM25 in memoria sulle sezioni delle guide."""

    def __init__(self, sezioni: list[GuideSection]) -> None:
        self.sezioni = sezioni
        self._frequenze = [Counter(tokenize(s.title) + tokenize(s.text)) for s in sezioni]
        self._lunghezze = [sum(f.values()) for f in self._frequenze]
        self._lunghezza_media = sum(self._lunghezze) / len(sezioni)
        presenze = Counter(termine for f in self._frequenze for termine in f)
        n = len(sezioni)
        self._idf = {t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in presenze.items()}

    def search(self, query: str, top_k: int) -> list[GuideHit]:
        termini = set(tokenize(query)) & self._idf.keys()
        punteggi: list[tuple[float, int]] = []
        for i, frequenze in enumerate(self._frequenze):
            norma = K1 * (1 - B + B * self._lunghezze[i] / self._lunghezza_media)
            score = sum(
                self._idf[t] * frequenze[t] * (K1 + 1) / (frequenze[t] + norma)
                for t in termini
                if t in frequenze
            )
            if score > 0:
                punteggi.append((score, i))
        punteggi.sort(key=lambda coppia: (-coppia[0], coppia[1]))
        return [
            GuideHit(**self.sezioni[i].model_dump(), score=round(score, 3))
            for score, i in punteggi[:top_k]
        ]


def build_index(payloads: dict[str, Any]) -> FullTextIndex:
    sezioni: list[GuideSection] = []
    for nome, payload in payloads.items():
        della_guida = flatten(nome, parse_guide(payload, nome))
        if not della_guida:
            raise UnexpectedPayload(f"la guida {nome} non contiene sezioni con testo")
        sezioni.extend(della_guida)
    return FullTextIndex(sezioni)


async def search_guides(query: str, top_k: int = 3) -> tuple[list[GuideHit], Meta]:
    scaricate = await asyncio.gather(*(fetch(guide_path(nome)) for nome in GUIDE))
    # Nessuna memoizzazione: 52 sezioni si indicizzano in circa 25 ms, e così l'indice segue la cache.
    indice = build_index({nome: f.payload for nome, f in zip(GUIDE, scaricate)})
    meta = Meta(
        retrieved_at=min(f.retrieved_at for f in scaricate),
        cache_status="stale" if any(f.cache_status == "stale" for f in scaricate) else "fresh",
        age_seconds=max(f.age_seconds for f in scaricate),
    )
    return indice.search(query, top_k), meta
