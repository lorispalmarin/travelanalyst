"""Recupero e composizione della scheda paese.

Tutto il server passa da `fetch_sheet`: un solo punto di validazione della scheda. La rete e
la cache stanno un livello sotto, in `client.fetch`, che restituisce il payload insieme alla sua
provenienza; qui la provenienza viene attaccata alla scheda e da lì finisce nel `meta` dei tool.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import ValidationError

from .config import contacts_pdf_url, page_url, sheet_path, sheet_pdf_url, sheet_url
from .errors import UnexpectedPayload, UnknownTopic
from .client import fetch
from .models import CountryRef, CountrySheet, Meta, Source, Topic, with_fallback

SECTION_FIELDS = ("highlights", "general", "entry", "security", "health", "mobility", "changelog")

# Se il nodo di dettaglio è vuoto si usa il riassunto di primo piano, dichiarandolo.
# Con i dati attuali scatta solo il primo: gli altri sono mappati ma dormienti.
FALLBACKS: dict[str, str] = {
    "security.caution_areas": "highlights.caution_areas",
    "entry.passport": "highlights.documents_and_visas",
    "health.vaccinations": "highlights.vaccinations",
    "general.embassy_and_consulates": "highlights.embassy",
    "general.country_data": "highlights.currency",
}


def source_for(iso3: str) -> Source:
    return Source(page=page_url(iso3), data=sheet_url(iso3), pdf=sheet_pdf_url(iso3))


def contacts_source_for(iso3: str) -> Source:
    return Source(page=page_url(iso3), data=sheet_url(iso3), pdf=contacts_pdf_url(iso3))


async def fetch_sheet(iso3: str, country: CountryRef | None = None) -> CountrySheet:
    scaricata = await fetch(sheet_path(iso3))
    try:
        sheet = CountrySheet.model_validate(scaricata.payload)
    except ValidationError as exc:
        raise UnexpectedPayload(
            f"la scheda di {iso3} non ha la forma attesa: {exc.error_count()} campi non validi "
            f"(primo: {'.'.join(str(p) for p in exc.errors()[0]['loc'])})"
        ) from exc
    sheet.country = country
    sheet.meta = Meta(
        last_updated=sheet.updated_at,
        retrieved_at=scaricata.retrieved_at,
        cache_status=scaricata.cache_status,
        age_seconds=scaricata.age_seconds,
    )
    return sheet


def iter_topics(sheet: CountrySheet) -> Iterator[tuple[str, str, Topic]]:
    """Percorre la scheda restituendo (sezione, campo, nodo) senza applicare fallback."""
    for section_name in SECTION_FIELDS:
        section = getattr(sheet, section_name)
        nodes = section.nodes
        for field in type(nodes).model_fields:
            yield section_name, field, getattr(nodes, field)


def topic_map(sheet: CountrySheet) -> dict[str, Topic]:
    """Mappa `sezione.campo` -> nodo, con la chiave valorizzata e i fallback già applicati."""
    raw = {
        f"{section}.{field}": topic.model_copy(update={"key": f"{section}.{field}"})
        for section, field, topic in iter_topics(sheet)
    }
    resolved = dict(raw)
    for detail_key, summary_key in FALLBACKS.items():
        detail, summary = raw.get(detail_key), raw.get(summary_key)
        if detail is not None and summary is not None:
            resolved[detail_key] = with_fallback(detail, summary)
    return resolved


def section_topics(sheet: CountrySheet, section_name: str, only: list[str] | None = None) -> list[Topic]:
    """I nodi di una sezione, con fallback applicati e filtro opzionale.

    Il filtro accetta il nome del campo (`local_laws`), la chiave completa
    (`security.local_laws`) o l'id della fonte (`Normative-locali-rilevanti`), perché sono tutti
    valori che il modello vede passare nelle risposte. Un valore non riconosciuto è un errore,
    non una lista vuota.
    """
    resolved = topic_map(sheet)
    nodes = getattr(sheet, section_name).nodes
    fields = list(type(nodes).model_fields)
    if not only:
        return [resolved[f"{section_name}.{field}"] for field in fields]

    per_source_id = {getattr(nodes, field).id: field for field in fields}
    scelti: list[str] = []
    ignoti: list[str] = []
    for richiesto in only:
        valore = richiesto.strip()
        campo = None
        if valore in fields:
            campo = valore
        elif valore.startswith(f"{section_name}.") and valore.split(".", 1)[1] in fields:
            campo = valore.split(".", 1)[1]
        elif valore in per_source_id:
            campo = per_source_id[valore]
        if campo is None:
            ignoti.append(richiesto)
        elif campo not in scelti:
            scelti.append(campo)

    if ignoti:
        raise UnknownTopic(section_name, ignoti, fields)
    return [resolved[f"{section_name}.{field}"] for field in scelti]
