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

import asyncio

from .alerts import alerts_source_for, leggi_avvisi
from .approfondimenti import DOCUMENTI, Risultato, carica_indice, documento_url, meta_dell_indice
from .config import BASE_URL
from .countries import get_index
from .embeddings import CredenzialiMancanti, embedda_query
from .errors import CountryNotFound, SourceError, UnexpectedPayload, UnknownTopic
from .models import (
    Avvisi,
    CountryMatch,
    CountryRef,
    CountrySheet,
    Source,
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
- `meta.cache_status="stale"` significa che viaggiaresicuri.it non risponde e quello che leggi è
  una copia locale vecchia di `meta.age_seconds`: non presentarla come la situazione di adesso.
- Non sostituirti alle autorità competenti e non dare pareri legali o sanitari.

Come muoverti fra i tool:
- `key` (es. `security.local_laws`) è il valore da usare nei filtri `topics`, non `id`.
- `see_also` elenca le sezioni a cui la fonte rimanda: `security` -> get_security_info,
  `health` -> get_health_info, `entry` -> get_entry_requirements, `general` ->
  get_embassy_contacts o get_practical_info, `mobility` -> get_local_transport.
- Se una domanda non rientra in un tema, `list_country_topics` mostra l'indice completo a costo
  basso e `get_country_topics` recupera solo le voci scelte.
- `search_approfondimenti` è l'unico tool che NON parla di un Paese: serve alle domande generali
  su salute in viaggio e documenti di viaggio. Se nella domanda c'è un Paese, la risposta sta nei
  tool della scheda paese, non lì.
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
    """Requisiti di ingresso e documenti richiesti **da un Paese specifico**.

    Copre: validità residua del passaporto e documenti accettati; visto di ingresso, esenzioni e
    durata dei soggiorni; viaggi all'estero dei minori; formalità doganali e valutarie (valuta
    importabile, beni da dichiarare, animali al seguito); altre informazioni sull'ingresso.

    È il tool da usare ogni volta che la domanda nomina una destinazione. Per le regole generali
    su come si ottiene o si rinnova un documento italiano c'è `search_approfondimenti`.

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
    """Situazione sanitaria **di un Paese specifico**.

    Copre: strutture sanitarie e loro affidabilità, costi e necessità di assicurazione; malattie
    presenti nel Paese; avvertenze sanitarie su acqua, alimenti, cure dentali ed estetiche;
    vaccinazioni obbligatorie e raccomandate.

    Risponde a "cosa mi serve per *questo* Paese". Le domande su una malattia o su una pratica in
    sé — che cos'è la dengue, come si prepara una farmacia da viaggio — stanno in
    `search_approfondimenti`.

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
        meta=sheet.meta,
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


@mcp.tool
async def search_approfondimenti(query: str, top_k: int = 5) -> ToolResponse[list[Risultato]]:
    """Ricerca semantica nelle due guide tematiche del Ministero: "Salute in viaggio" e
    "Documenti di viaggio".

    Sono documenti **generali e procedurali, non riferiti a un Paese**. Usalo per domande come:
    che cos'è la dengue e come si previene; quali vaccinazioni si possono fare in gravidanza;
    cosa mettere in una farmacia da viaggio; come funziona l'assicurazione sanitaria all'estero;
    cosa fare in caso di furto o smarrimento dei documenti; come si ottiene un documento di
    viaggio provvisorio; quali documenti servono per far viaggiare un minore.

    **Non usarlo quando la domanda nomina una destinazione.** Per "quali documenti servono per
    l'Albania" si usa `get_entry_requirements`; per "quali vaccinazioni servono per il Kenya" si
    usa `get_health_info`. Questi documenti non contengono nulla di specifico per Paese, e una
    risposta presa da qui a una domanda su un Paese sarebbe fuori bersaglio.

    Restituisce i passaggi più pertinenti, ognuno con il documento e la sezione di provenienza
    (`breadcrumb`), da citare nella risposta. `top_k` controlla quanti passaggi tornano.
    """
    try:
        indice = carica_indice()
    except UnexpectedPayload as exc:
        raise ToolError(f"[index_missing] {exc}") from exc

    testo = (query or "").strip()
    if not testo:
        raise ToolError("[empty_query] La query di ricerca non può essere vuota.")

    try:
        # l'SDK degli embedding è sincrono: fuori dal loop, o blocca tutto il server
        vettore = await asyncio.to_thread(embedda_query, testo)
    except CredenzialiMancanti as exc:
        raise ToolError(f"[embedding_unavailable] {exc}") from exc
    except Exception as exc:
        raise ToolError(
            f"[embedding_unavailable] Impossibile vettorizzare la domanda: {type(exc).__name__}."
        ) from exc

    risultati = indice.cerca(vettore, top_k)
    return ToolResponse[list[Risultato]](
        topic="Approfondimenti tematici",
        data=risultati,
        updated_at=meta_dell_indice(indice).last_updated,
        sources=Source(
            page=f"{BASE_URL}/approfondimenti",
            data=documento_url(risultati[0].documento if risultati else next(iter(DOCUMENTI))),
        ),
        meta=meta_dell_indice(indice),
    )


def main() -> None:
    # stdout è il canale del protocollo MCP: log su stderr e niente banner, altrimenti
    # il client vede rumore al posto del JSON-RPC
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        indice = carica_indice()
        logger.info("indice degli approfondimenti: %s chunk", len(indice))
    except UnexpectedPayload as exc:
        # il server parte lo stesso: gli altri dieci tool non dipendono dall'indice
        logger.warning("ricerca semantica non disponibile: %s", exc)
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
