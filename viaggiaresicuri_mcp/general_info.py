"""Le due guide generali di Viaggiare Sicuri: le sole informazioni non legate a un Paese.

JSON della guida -> validazione -> sezioni appiattite. Si consultano come un sommario — l'elenco
dei titoli, poi la sezione scelta — invece di cercarle: sono sette sezioni con un nome parlante, e
l'elenco intero costa meno di una singola risposta di ricerca.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import ValidationError

from .client import fetch
from .config import guide_page_url, guide_path, guide_url
from .errors import UnexpectedPayload, UnknownTopic
from .models import GuideNode, GuideRef, GuideSection, Link, Meta, Source
from .normalize import extract_links, html_to_text, link_kind

GUIDE: dict[str, str] = {
    "preparaunviaggio": "Preparare un viaggio",
    "documentidiviaggio": "Documenti di viaggio",
}

_BARRATO = re.compile(r"(?is)<s\b[^>]*>.*?</s\s*>")


def sources() -> list[Source]:
    return [Source(page=guide_page_url(nome), data=guide_url(nome)) for nome in GUIDE]


def source_of(sezione: GuideSection) -> Source:
    nome = sezione.id.split("/", 1)[0]
    return Source(page=guide_page_url(nome), data=guide_url(nome))


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


def build_sections(payloads: dict[str, Any]) -> list[GuideSection]:
    sezioni: list[GuideSection] = []
    for nome, payload in payloads.items():
        della_guida = flatten(nome, parse_guide(payload, nome))
        if not della_guida:
            raise UnexpectedPayload(f"la guida {nome} non contiene sezioni con testo")
        sezioni.extend(della_guida)
    return sezioni


async def load_guides() -> tuple[list[GuideSection], Meta]:
    """Le sezioni delle due guide e la freschezza della più vecchia delle due copie."""
    scaricate = await asyncio.gather(*(fetch(guide_path(nome)) for nome in GUIDE))
    sezioni = build_sections({nome: f.payload for nome, f in zip(GUIDE, scaricate)})
    meta = Meta(
        retrieved_at=min(f.retrieved_at for f in scaricate),
        cache_status="stale" if any(f.cache_status == "stale" for f in scaricate) else "fresh",
        age_seconds=max(f.age_seconds for f in scaricate),
    )
    return sezioni, meta


def guide_index(sezioni: list[GuideSection]) -> list[GuideRef]:
    return [GuideRef(id=s.id, breadcrumb=s.breadcrumb, chars=len(s.text)) for s in sezioni]


def guide_section(sezioni: list[GuideSection], topic: str) -> GuideSection:
    """La sezione con quell'id. Un id sbagliato è un errore che elenca i validi, non una risposta vuota."""
    for sezione in sezioni:
        if sezione.id == topic.strip():
            return sezione
    raise UnknownTopic("guide generali", [topic], [s.id for s in sezioni])
