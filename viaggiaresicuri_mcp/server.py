"""Server MCP su Viaggiare Sicuri.
"""

from __future__ import annotations

import logging
import sys
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

import asyncio

from .alerts import alerts_source_for, leggi_avvisi
from .config import MCP_HOST, MCP_PORT
from .countries import get_index
from .errors import CountryNotFound, SourceError, UnknownTopic
from .general_info import MAX_RISULTATI, search_guides
from .general_info import sources as guide_sources
from .models import (
    Avvisi,
    CountryMatch,
    CountryRef,
    CountrySheet,
    GuideHit,
    Source,
    Topic,
    ToolResponse,
)
from .sheet import contacts_source_for, fetch_sheet, section_topics, source_for

logger = logging.getLogger(__name__)

INSTRUCTIONS = """
Fonte unica: viaggiaresicuri.it (Unità di Crisi, Ministero degli Affari Esteri).

Regole non negoziabili quando usi questi dati:
- `status="not_published"` significa che la fonte non ha pubblicato nulla su quel punto. Non
  significa che non ci sia un rischio: non presentarlo mai come assenza di pericolo.
- `provenance="summary"` indica un contenuto preso dalla scheda di sintesi perché il dettaglio
  non è pubblicato: dichiaralo invece di spacciarlo per approfondimento.
- Cita sempre la fonte e la data di aggiornamento presenti nella risposta.
- `meta.cache_status="stale"` significa che viaggiaresicuri.it non risponde e quello che leggi è
  una copia locale vecchia di `meta.age_seconds`: non presentarla come la situazione di adesso.
- Non sostituirti alle autorità competenti e non dare pareri legali o sanitari.

Come muoverti fra i tool:
- `key` (es. `security.local_laws`) è il valore da usare nei filtri `topics`, non `id`.
- `see_also` elenca le sezioni a cui la fonte rimanda: `security` -> get_security_info,
  `health` -> get_health_info, `entry` -> get_entry_requirements, `general` ->
  get_embassy_contacts o get_practical_info, `mobility` -> get_local_transport.
- `search_general_information` è l'unico tool senza Paese: cerca per parole nelle guide
  tematiche e restituisce sezioni candidate, non risposte. Le guide non hanno una data di
  aggiornamento.
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
            f"[{exc.code}] Nessun Paese corrisponde a {country!r}. Richiama il tool con il nome "
            "ufficiale italiano del Paese o con il suo codice ISO3."
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
        meta=sheet.meta,
    )


@mcp.tool
async def find_country(query: str) -> CountryMatch:
    """Risolve il nome di un Paese nel codice ISO3 usato dalla fonte.

    Accetta il nome ufficiale italiano dell'elenco del Ministero (`Paesi Bassi`, `Federazione
    Russa`, `Repubblica Popolare Cinese`), un codice ISO (`THA`, `TH`), o una parte non ambigua
    del nome (`Stati Uniti`). **Non** accetta nomi inglesi, forme colloquiali ("olanda"),
    località ("Bali", "Phuket") né refusi: la traduzione e la geografia le fai tu prima di
    chiamare, e se il nome non è riconosciuto l'errore ti dice di riprovare con quello ufficiale.

    Se la richiesta è ambigua restituisce i candidati senza sceglierne uno: "Corea" corrisponde
    sia alla Corea del Sud sia alla Corea del Nord.
    """
    index = await _index()
    try:
        return index.resolve(query)
    except CountryNotFound as exc:
        raise ToolError(f"[{exc.code}] Nessun Paese corrisponde a {query!r}.") from exc


@mcp.tool
async def get_entry_requirements(country: str, topics: list[str] | None = None) -> ToolResponse[list[Topic]]:
    """Requisiti di ingresso e documenti richiesti **da un Paese specifico**.

    Copre: validità residua del passaporto e documenti accettati; visto di ingresso, esenzioni e
    durata dei soggiorni; viaggi all'estero dei minori; formalità doganali e valutarie (valuta
    importabile, beni da dichiarare, animali al seguito); altre informazioni sull'ingresso.

    Risponde a "cosa chiede *questo* Paese per farmi entrare". Le regole italiane sui documenti
    per l'espatrio, uguali per ogni destinazione — documenti dei minori, furto o smarrimento
    all'estero — stanno in search_general_information.

    `topics` opzionale per restringere: passport, visa, minors, customs, other. Utile perché su
    alcuni Paesi questa sezione è molto lunga.
    """
    ref, sheet = await _load(country)
    return _respond(ref, sheet, "Requisiti di ingresso", _topics(sheet, "entry", topics))


@mcp.tool
async def get_security_info(country: str, topics: list[str] | None = None) -> ToolResponse[list[Topic]]:
    """Sicurezza, avvertenze e normative locali di un Paese specifico.

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
    """Situazione sanitaria **di un Paese specifico**.

    Copre: strutture sanitarie e loro affidabilità, costi e necessità di assicurazione; malattie
    presenti nel Paese; avvertenze sanitarie su acqua, alimenti, cure dentali ed estetiche;
    vaccinazioni obbligatorie e raccomandate.

    Risponde a "cosa mi serve per *questo* Paese". Le domande su una malattia in sé — che cos'è
    la dengue, come si trasmette — non sono fra le fonti di questo server: la guida generale si
    limita a rimandare al Ministero della Salute, ed è quel rimando che restituisce
    search_general_information.

    `topics` opzionale: facilities, diseases, warnings, vaccinations.
    """
    ref, sheet = await _load(country)
    return _respond(ref, sheet, "Situazione sanitaria", _topics(sheet, "health", topics))


@mcp.tool
async def get_local_transport(country: str) -> ToolResponse[list[Topic]]:
    """Mobilità e trasporti locali di un Paese specifico.

    Copre: guida e patente richiesta, condizioni della rete stradale, sicurezza degli
    spostamenti, trasporto pubblico, taxi, collegamenti aerei e ferroviari interni.
    """
    ref, sheet = await _load(country)
    return _respond(ref, sheet, "Mobilità e trasporti", _topics(sheet, "mobility", None))


@mcp.tool
async def get_embassy_contacts(country: str) -> ToolResponse[list[Topic]]:
    """Recapiti di Ambasciata e Consolati italiani di un Paese specifico.

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
async def get_allerte(iso3: str) -> ToolResponse[Avvisi]:
    """Allerte e avvisi in corso pubblicati dalla Farnesina per un Paese.

    **Vale la pena chiamarlo anche se le allerte non sono state chieste**, ogni volta che un avviso
    in corso cambierebbe la risposta o il modo in cui va inquadrata: chi domanda quali documenti
    servono per l'Ucraina deve sapere che tutti i viaggi verso l'Ucraina sono sconsigliati,
    altrimenti la risposta è corretta e inutile. Su una domanda puntuale che un avviso non
    sposterebbe — quale patente serve, il numero dell'ambasciata — è invece una chiamata sprecata.
    Una chiamata per Paese: il risultato vale per tutto il resto della conversazione.

    `iso3` è il codice a tre lettere, quello che restituisce `find_country`.

    La risposta distingue **tre** stati, e non due, nel campo `stato`:
    - `avvisi_presenti`: la fonte è stata consultata adesso e pubblica avvisi.
    - `nessun_avviso_pubblicato`: consultata adesso, non ne pubblica. Vuol dire che la Farnesina
      non ha pubblicato nulla, **non** che il Paese sia sicuro: non presentarlo come una
      rassicurazione.
    - `non_verificabile`: la fonte non risponde e questa è una copia locale. Da una copia vecchia
      senza avvisi **non** segue che non ce ne siano adesso: dillo, non affermare l'assenza.

    Il campo `messaggio` contiene la frase già scritta per l'operatore, adatta allo stato:
    riportala così com'è invece di riformularla.

    Ogni voce porta `category` (la categoria della fonte: "sicurezza", "sanita", …),
    `published_at` e il testo ripulito. `focus` sono comunicazioni non legate al Paese.
    """
    ref = await _resolve(iso3)
    try:
        avvisi, meta = await leggi_avvisi(ref.iso3, ref.name)
    except SourceError as exc:
        raise ToolError(f"[{exc.code}] Avvisi per {ref.name} non disponibili: {exc}") from exc

    return ToolResponse[Avvisi](
        country=ref,
        topic="Allerte e avvisi in corso",
        data=avvisi,
        updated_at=meta.last_updated,
        sources=alerts_source_for(ref.iso3),
        meta=meta,
    )


@mcp.tool
async def search_general_information(
    query: str, top_k: Annotated[int, Field(ge=1, le=MAX_RISULTATI)] = 3
) -> ToolResponse[list[GuideHit]]:
    """Cerca nelle due guide generali di Viaggiare Sicuri: informazioni **non legate a un Paese**.

    "Preparare un viaggio": consulto medico prima della partenza e farmaci da portare con sé;
    certificati sanitari (dispositivi medicali, terapie croniche, esenzione dalla febbre gialla,
    tessera TEAM, test HIV per soggiorni lunghi); viaggiatori vulnerabili e cane guida;
    assicurazione di viaggio e sanitaria dentro e fuori dall'UE, prestiti consolari; pacchetti
    turistici, recesso e obblighi del tour operator. "Documenti di viaggio": passaporto e carta
    d'identità per l'espatrio, CIE, documenti dei minori, furto o smarrimento all'estero e
    documento di viaggio provvisorio (ETD), restituzione dei documenti ritrovati.

    Sono due guide brevi, sette sezioni in tutto: **non** contengono schede sulle singole
    malattie — per quelle rimandano al Ministero della Salute — né i requisiti di un Paese, che
    stanno in get_entry_requirements e get_health_info.

    La ricerca è per parole, non per significato: scrivi `query` con i termini che userebbe la
    guida (`smarrimento passaporto estero`, `vaccinazioni gravidanza`). Restituisce le `top_k`
    sezioni con più corrispondenze, ciascuna con il percorso nella guida e la pagina da citare.
    Sono candidate, non risposte: usa solo quelle che rispondono davvero. Una lista vuota, o
    nessuna sezione pertinente, vuol dire che le guide non trattano il tema: dillo invece di
    rispondere a memoria.
    """
    try:
        risultati, meta = await search_guides(query, top_k)
    except SourceError as exc:
        raise ToolError(f"[{exc.code}] Guide tematiche non disponibili: {exc}") from exc

    return ToolResponse[list[GuideHit]](
        topic="Guide tematiche",
        data=risultati,
        sources=guide_sources(),
        meta=meta,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT, path="/mcp", show_banner=False)


if __name__ == "__main__":
    main()
