"""Contratto della scheda paese di Viaggiare Sicuri.

I modelli ricalcano la struttura reale dell'endpoint `/schede_paese/{ISO3}.json`:
7 sezioni, 28 nodi, tutti presenti in 222 paesi su 222 (censimento in docs/schede-paese.md).
Gli alias sono le chiavi della fonte; i nomi dei campi sono la nostra superficie.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .normalize import html_to_text, link_kind, extract_links, split_see_also

DISCLAIMER = (
    "Informazioni di orientamento preliminare tratte da viaggiaresicuri.it (Ministero degli "
    "Affari Esteri). Possono variare: prima della partenza verificare le indicazioni ufficiali "
    "applicabili al caso specifico. Non sostituiscono pareri legali o sanitari."
)

TopicStatus = Literal["available", "not_published"]
Provenance = Literal["detail", "summary"]


class Link(BaseModel):
    text: str
    url: str
    kind: Literal["web", "email", "phone"]


class Topic(BaseModel):
    """Un nodo foglia della scheda, normalizzato.

    `status="not_published"` significa che la fonte non ha pubblicato nulla su questo punto.
    Non significa assenza di rischio, e non va mai presentato come tale.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    key: str | None = None  # "security.local_laws": è il valore da usare nei filtri dei tool
    title: str = Field(alias="titolo")
    order: int = Field(default=0, alias="ordinamento")
    text: str
    status: TopicStatus
    see_also: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    provenance: Provenance = "detail"

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "contenuto" not in data:
            return data
        raw = data.get("contenuto") or ""
        text, see_also = split_see_also(html_to_text(raw))
        links = [
            Link(text=label, url=url, kind=link_kind(url)) for label, url in extract_links(raw)
        ]
        return {
            **data,
            "text": text,
            "status": "available" if text.strip() else "not_published",
            "see_also": see_also,
            "links": links,
        }


class Nodes(BaseModel):
    """Contenitore dei nodi di una sezione.

    I nodi dichiarati sono obbligatori: se la fonte ne toglie uno la validazione fallisce,
    invece di restituire in silenzio una scheda a metà. I nodi nuovi non rompono nulla ma
    finiscono in `unknown`, così una modifica additiva della fonte resta visibile.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _inject_ids(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {
            key: {"id": key, **value} if isinstance(value, dict) and "id" not in value else value
            for key, value in data.items()
        }

    @property
    def unknown(self) -> list[str]:
        return sorted(self.model_extra or {})

    def topics(self) -> list[Topic]:
        return [getattr(self, name) for name in type(self).model_fields]


class ChangelogNodes(Nodes):
    changelog: Topic = Field(alias="Cronologia-aggiornamenti")


class HighlightsNodes(Nodes):
    documents_and_visas: Topic = Field(alias="Documenti-e-visti")
    vaccinations: Topic = Field(alias="Vaccinazioni")
    currency: Topic = Field(alias="Moneta")
    caution_areas: Topic = Field(alias="Aree-di-particolare-cautela")
    embassy: Topic = Field(alias="Ambasciata")


class GeneralNodes(Nodes):
    country_data: Topic = Field(alias="Dati-paese")
    embassy_and_consulates: Topic = Field(alias="Ambasciate-e-Consolati")
    useful_info: Topic = Field(alias="Informazioni-utili")
    business_guidance: Topic = Field(alias="Indicazioni-per-operatori-economici")
    required_documents: Topic = Field(alias="Documentazione-necessaria")


class EntryNodes(Nodes):
    passport: Topic = Field(alias="Passaporto")
    visa: Topic = Field(alias="Visto-di-ingresso")
    minors: Topic = Field(alias="Viaggi-all-estero-dei-minori")
    customs: Topic = Field(alias="Formalit--doganali-e-valutarie")
    other: Topic = Field(alias="Altre-informazioni")


class SecurityNodes(Nodes):
    general: Topic = Field(alias="Indicazioni-generali")
    terrorism: Topic = Field(alias="Rischio-terrorismo")
    natural_risks: Topic = Field(alias="Rischi-ambientali-e-naturali")
    caution_areas: Topic = Field(alias="Aree-di-particolare-cautela")
    warnings: Topic = Field(alias="Avvertenze")
    local_laws: Topic = Field(alias="Normative-locali-rilevanti")
    business_info: Topic = Field(alias="Informazioni-per-le-aziende")


class HealthNodes(Nodes):
    facilities: Topic = Field(alias="Strutture-sanitarie")
    diseases: Topic = Field(alias="Malattie-presenti")
    warnings: Topic = Field(alias="Avvertenze")
    vaccinations: Topic = Field(alias="Vaccinazioni-obbligatorie")


class MobilityNodes(Nodes):
    mobility: Topic = Field(alias="Mobilita")


NodesT = TypeVar("NodesT", bound=Nodes)


class Section(BaseModel, Generic[NodesT]):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str = Field(alias="titolo")
    order: int = Field(default=0, alias="ordinamento")
    nodes: NodesT = Field(alias="nodi")


class CountryRef(BaseModel):
    name: str
    iso3: str
    iso2: str


class CountryMatch(BaseModel):
    """Esito della risoluzione di un paese. Se ambiguo non si sceglie: si restituiscono i candidati."""

    match: CountryRef | None = None
    candidates: list[CountryRef] = Field(default_factory=list)
    confidence: Literal["exact", "alias", "fuzzy"] | None = None


class CountrySheet(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    country: CountryRef | None = None
    updated_at: datetime = Field(alias="updateDate")

    changelog: Section[ChangelogNodes] = Field(alias="infoCronologiaAggiornamenti")
    highlights: Section[HighlightsNodes] = Field(alias="infoPrimopiano")
    general: Section[GeneralNodes] = Field(alias="infoGenerali")
    entry: Section[EntryNodes] = Field(alias="infoRequisitiIngresso")
    security: Section[SecurityNodes] = Field(alias="infoSicurezza")
    health: Section[HealthNodes] = Field(alias="infoSituazioneSanitaria")
    mobility: Section[MobilityNodes] = Field(alias="infoMobilita")

    @property
    def unknown_sections(self) -> list[str]:
        return sorted(self.model_extra or {})


def with_fallback(detail: Topic, summary: Topic) -> Topic:
    """Se il dettaglio non è pubblicato usa il riassunto di primo piano, dichiarandolo.

    Serve perché la fonte lascia vuoti i nodi di dettaglio: `Aree-di-particolare-cautela` è vuoto
    nel 37% dei paesi, e nella quasi totalità dei casi il primo piano una risposta ce l'ha.

    In una manciata di paesi però anche il primo piano è composto dal solo rimando alla sezione
    di dettaglio, che a sua volta è vuota: la fonte rimanda a se stessa a vuoto. Lì si resta sul
    dettaglio, così la risposta è "non pubblicato" e non un riassunto che non riassume niente.
    """
    if detail.status == "available" or summary.status != "available":
        return detail
    return summary.model_copy(
        update={
            "id": detail.id,
            "key": detail.key,
            "title": detail.title,
            "provenance": "summary",
        }
    )


class Alert(BaseModel):
    """Un avviso di `/ultima_ora/{ISO3}.json`.

    Vive fuori dalla scheda paese e cambia molto più in fretta: le parole di un'allerta in corso
    (un'alluvione, uno sciopero, un'eruzione) non compaiono da nessuna parte nella scheda.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    country_iso3: str | None = Field(default=None, alias="nazione")
    category: str | None = Field(default=None, alias="tipologia")
    title: str = Field(alias="titolo")
    text: str
    published_at: datetime | None = None
    links: list[Link] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "testo" not in data:
            return data
        raw = data.get("testo") or ""
        timestamp = data.get("tsModifica")
        try:
            published = datetime.fromtimestamp(int(timestamp), tz=UTC) if timestamp else None
        except (TypeError, ValueError):
            published = None
        normalized = {
            **data,
            "text": html_to_text(raw),
            "published_at": published,
            "links": [
                Link(text=label, url=url, kind=link_kind(url)) for label, url in extract_links(raw)
            ],
            # la fonte usa "" invece di null su questi due
            "nazione": (data.get("nazione") or None),
            "tipologia": (data.get("tipologia") or None),
        }
        # il titolo si ripulisce solo se c'è: se manca deve fallire la validazione, non essere
        # inventato vuoto
        if "titolo" in data:
            normalized["titolo"] = (data.get("titolo") or "").strip()
        return normalized


class TopicRef(BaseModel):
    """Voce dell'indice degli argomenti: abbastanza per scegliere, troppo poco per rispondere."""

    key: str
    title: str
    status: TopicStatus
    chars: int


class Source(BaseModel):
    page: str
    data: str
    pdf: str | None = None


T = TypeVar("T")


class ToolResponse(BaseModel, Generic[T]):
    """Envelope comune a tutti i tool. Le allerte della fase B useranno lo stesso guscio."""

    country: CountryRef
    topic: str
    data: T
    updated_at: datetime | None = None
    sources: Source
    notice: str = DISCLAIMER
