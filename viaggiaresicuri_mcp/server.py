"""Server MCP su Viaggiare Sicuri.

I tool non sono un calco della fonte: sono viste sul contratto, tagliate sul bisogno di chi
lavora al customer care. Le descrizioni elencano esplicitamente cosa contiene ogni sezione,
perché è su quelle che il modello sceglie: senza, nessuno indovinerebbe che le regole su
farmaci e alcol stanno sotto "Sicurezza".
"""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .alerts import alerts_source_for, fetch_alerts
from .countries import get_index
from .errors import CountryNotFound, SourceError, UnknownTopic
from .models import (
    Alert,
    CountryMatch,
    CountryRef,
    CountrySheet,
    Topic,
    TopicRef,
    ToolResponse,
)
from .sheet import contacts_source_for, fetch_sheet, iter_topics, section_topics, source_for, topic_map

logger = logging.getLogger(__name__)

INSTRUCTIONS = """
Fonte unica: viaggiaresicuri.it (Unità di Crisi, Ministero degli Affari Esteri).

Regole non negoziabili quando usi questi dati:
- `status="not_published"` significa che la fonte non ha pubblicato nulla su quel punto. Non
  significa che non ci sia un rischio: non presentarlo mai come assenza di pericolo.
- `provenance="summary"` indica un contenuto preso dalla scheda di sintesi perché il dettaglio
  non è pubblicato: dichiaralo invece di spacciarlo per approfondimento.
- Cita sempre la fonte e la data di aggiornamento presenti nella risposta.
- Non sostituirti alle autorità competenti e non dare pareri legali o sanitari.

Come muoverti fra i tool:
- `key` (es. `security.local_laws`) è il valore da usare nei filtri `topics`, non `id`.
- `see_also` elenca le sezioni a cui la fonte rimanda: `security` -> get_security_info,
  `health` -> get_health_info, `entry` -> get_entry_requirements, `general` ->
  get_embassy_contacts o get_practical_info, `mobility` -> get_local_transport.
- Se una domanda non rientra in un tema, `list_country_topics` mostra l'indice completo a costo
  basso e `get_country_topics` recupera solo le voci scelte.
""".strip()

mcp = FastMCP(name="viaggiaresicuri", instructions=INSTRUCTIONS)


async def _index() -> "object":
    try:
        return await get_index()
    except SourceError as exc:
        raise ToolError(f"[{exc.code}] Elenco dei Paesi non disponibile: {exc}") from exc


async def _resolve(country: str) -> CountryRef:
    index = await _index()
    try:
        match = index.resolve(country)
    except CountryNotFound as exc:
        raise ToolError(
            f"[{exc.code}] Nessun Paese corrisponde a {country!r}. "
            "Chiedi all'operatore il nome completo o il codice ISO3."
        ) from exc

    if match.match is None:
        candidates = ", ".join(f"{c.name} ({c.iso3})" for c in match.candidates)
        raise ToolError(
            f"[ambiguous_country] {country!r} è ambiguo. Candidati: {candidates}. "
            "Chiedi all'operatore quale intende, oppure richiama il tool con il codice ISO3."
        )
    return match.match


async def _load(country: str) -> tuple[CountryRef, CountrySheet]:
    ref = await _resolve(country)
    try:
        sheet = await fetch_sheet(ref.iso3, ref)
    except SourceError as exc:
        raise ToolError(f"[{exc.code}] Scheda di {ref.name} non disponibile: {exc}") from exc
    return ref, sheet


def _topics(sheet: CountrySheet, section: str, only: list[str] | None) -> list[Topic]:
    try:
        return section_topics(sheet, section, only)
    except UnknownTopic as exc:
        raise ToolError(f"[{exc.code}] {exc}") from exc


def _respond(
    ref: CountryRef, sheet: CountrySheet, topic: str, topics: list[Topic], *, contacts: bool = False
) -> ToolResponse[list[Topic]]:
    return ToolResponse[list[Topic]](
        country=ref,
        topic=topic,
        data=topics,
        updated_at=sheet.updated_at,
        sources=contacts_source_for(ref.iso3) if contacts else source_for(ref.iso3),
    )


@mcp.tool
async def find_country(query: str) -> CountryMatch:
    """Risolve il nome di un Paese nel codice usato dalla fonte.

    Accetta nome italiano o inglese, forme colloquiali e codici ISO (THA, TH). Se la richiesta
    è ambigua restituisce i candidati senza sceglierne uno: ad esempio "Corea" corrisponde sia
    alla Corea del Sud sia alla Corea del Nord.
    """
    index = await _index()
    try:
        return index.resolve(query)
    except CountryNotFound as exc:
        raise ToolError(f"[{exc.code}] Nessun Paese corrisponde a {query!r}.") from exc


@mcp.tool
async def get_entry_requirements(country: str, topics: list[str] | None = None) -> ToolResponse[list[Topic]]:
    """Requisiti di ingresso e documenti di viaggio.

    Copre: validità residua del passaporto e documenti accettati; visto di ingresso, esenzioni e
    durata dei soggiorni; viaggi all'estero dei minori; formalità doganali e valutarie (valuta
    importabile, beni da dichiarare, animali al seguito); altre informazioni sull'ingresso.

    `topics` opzionale per restringere: passport, visa, minors, customs, other. Utile perché su
    alcuni Paesi questa sezione è molto lunga.
    """
    ref, sheet = await _load(country)
    return _respond(ref, sheet, "Requisiti di ingresso", _topics(sheet, "entry", topics))


@mcp.tool
async def get_security_info(country: str, topics: list[str] | None = None) -> ToolResponse[list[Topic]]:
    """Sicurezza, avvertenze e normative locali.

    Copre: ordine pubblico e criminalità; rischio terrorismo; rischi ambientali e calamità
    naturali; aree di particolare cautela e zone sconsigliate; avvertenze; **normative locali
    rilevanti**, cioè droga e psicofarmaci, alcol, comportamenti sanzionati, regole su
    fotografia, abbigliamento e condotta; informazioni per le aziende.

    Da usare anche per domande su leggi locali e su cosa è vietato o punito nel Paese.

    `topics` opzionale: general, terrorism, natural_risks, caution_areas, warnings, local_laws,
    business_info.
    """
    ref, sheet = await _load(country)
    return _respond(ref, sheet, "Sicurezza", _topics(sheet, "security", topics))


@mcp.tool
async def get_health_info(country: str, topics: list[str] | None = None) -> ToolResponse[list[Topic]]:
    """Situazione sanitaria e raccomandazioni di salute.

    Copre: strutture sanitarie e loro affidabilità, costi e necessità di assicurazione; malattie
    presenti nel Paese; avvertenze sanitarie su acqua, alimenti, cure dentali ed estetiche;
    vaccinazioni obbligatorie e raccomandate.

    `topics` opzionale: facilities, diseases, warnings, vaccinations. Su alcuni Paesi la sezione
    supera i 2.800 token, quindi conviene filtrare quando la domanda è mirata (es. i vaccini).
    """
    ref, sheet = await _load(country)
    return _respond(ref, sheet, "Situazione sanitaria", _topics(sheet, "health", topics))


@mcp.tool
async def get_local_transport(country: str) -> ToolResponse[list[Topic]]:
    """Mobilità e trasporti locali.

    Copre: guida e patente richiesta, condizioni della rete stradale, sicurezza degli
    spostamenti, trasporto pubblico, taxi, collegamenti aerei e ferroviari interni.
    """
    ref, sheet = await _load(country)
    return _respond(ref, sheet, "Mobilità e trasporti", _topics(sheet, "mobility", None))


@mcp.tool
async def get_embassy_contacts(country: str) -> ToolResponse[list[Topic]]:
    """Recapiti di Ambasciata e Consolati italiani nel Paese.

    Indirizzi, centralini, email, siti e numeri di emergenza per connazionali attivi 24 ore su
    24, inclusi i consolati nelle città diverse dalla capitale. La risposta contiene anche il
    link al PDF di una pagina con i soli contatti, da inoltrare al viaggiatore in difficoltà.
    """
    ref, sheet = await _load(country)
    topics = _topics(sheet, "general", ["embassy_and_consulates"])
    return _respond(ref, sheet, "Ambasciata e consolati", topics, contacts=True)


@mcp.tool
async def get_practical_info(country: str) -> ToolResponse[list[Topic]]:
    """Dati del Paese e informazioni pratiche.

    Copre: capitale, popolazione, fuso orario, lingue, religioni, moneta e cambio, prefissi
    telefonici, copertura della rete mobile e accesso a Internet; numeri di emergenza locali
    (polizia, pronto soccorso) e istituti italiani di cultura.
    """
    ref, sheet = await _load(country)
    topics = _topics(sheet, "general", ["country_data", "useful_info"])
    return _respond(ref, sheet, "Informazioni pratiche", topics)


@mcp.tool
async def get_recent_alerts(country: str) -> ToolResponse[list[Alert]]:
    """Allerte, comunicazioni urgenti e avvisi recenti pubblicati per il Paese.

    Da usare per ogni domanda sul presente: "si può partire adesso", "cosa sta succedendo",
    scioperi, alluvioni, eruzioni, epidemie, disordini, chiusure di aeroporti o frontiere.
    Sono un endpoint separato dalla scheda paese e cambiano nel giro di ore: quello che c'è qui
    non si trova nella scheda, e viceversa.

    Ogni avviso riporta la data di pubblicazione. Una lista vuota significa che la fonte non ha
    avvisi attivi per quel Paese: non significa che sia tutto tranquillo, e va detto così.
    """
    ref = await _resolve(country)
    try:
        avvisi = await fetch_alerts(ref.iso3)
    except SourceError as exc:
        raise ToolError(f"[{exc.code}] Avvisi per {ref.name} non disponibili: {exc}") from exc

    return ToolResponse[list[Alert]](
        country=ref,
        topic="Allerte e avvisi recenti",
        data=avvisi,
        updated_at=avvisi[0].published_at if avvisi else None,
        sources=alerts_source_for(ref.iso3),
    )


@mcp.tool
async def list_country_topics(country: str) -> ToolResponse[list[TopicRef]]:
    """Indice di tutti i 28 argomenti della scheda di un Paese: chiave, titolo, stato, dimensione.

    Costa poche centinaia di token e non contiene testo. È il modo più economico di rispondere a
    una domanda specifica: leggi l'indice, scegli le chiavi utili e chiama `get_country_topics`.
    Conviene anche quando la domanda tocca argomenti di sezioni diverse, o quando serve sapere
    in anticipo quanto pesa un contenuto prima di chiederlo.
    """
    ref, sheet = await _load(country)
    resolved = topic_map(sheet)
    entries = [
        TopicRef(
            key=f"{section}.{field}",
            title=topic.title,
            status=resolved[f"{section}.{field}"].status,
            chars=len(resolved[f"{section}.{field}"].text),
        )
        for section, field, topic in iter_topics(sheet)
    ]
    return ToolResponse[list[TopicRef]](
        country=ref,
        topic="Indice degli argomenti",
        data=entries,
        updated_at=sheet.updated_at,
        sources=source_for(ref.iso3),
    )


@mcp.tool
async def get_country_topics(country: str, keys: list[str]) -> ToolResponse[list[Topic]]:
    """Restituisce argomenti specifici della scheda, indicati per chiave.

    Le chiavi sono quelle di `list_country_topics`, nella forma `sezione.argomento`
    (per esempio `security.local_laws` o `entry.minors`).
    """
    ref, sheet = await _load(country)
    resolved = topic_map(sheet)
    unknown = [k for k in keys if k not in resolved]
    if unknown:
        raise ToolError(
            f"Chiavi non valide: {', '.join(unknown)}. "
            "Usa list_country_topics per l'elenco delle chiavi disponibili."
        )
    return _respond(ref, sheet, "Argomenti selezionati", [resolved[k] for k in keys])


def main() -> None:
    # stdout è il canale del protocollo MCP: log su stderr e niente banner, altrimenti
    # il client vede rumore al posto del JSON-RPC
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
