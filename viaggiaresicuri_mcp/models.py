"""Contratto della scheda paese di Viaggiare Sicuri.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .normalize import html_to_text, link_kind, extract_links, find_see_also

DISCLAIMER = (
    "Informazioni di orientamento preliminare tratte da viaggiaresicuri.it (Ministero degli "
    "Affari Esteri). Possono variare: prima della partenza verificare le indicazioni ufficiali "
    "applicabili al caso specifico. Non sostituiscono pareri legali o sanitari."
)

TopicStatus = Literal["available", "not_published"]
Provenance = Literal["detail", "summary"]
CacheStatus = Literal["fresh", "stale"]


class Link(BaseModel):
    text: str
    url: str
    kind: Literal["web", "email", "phone"]


class Topic(BaseModel):
    """Un nodo foglia della scheda, normalizzato.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    key: str | None = None 
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
        text = html_to_text(raw)
        links = [
            Link(text=label, url=url, kind=link_kind(url)) for label, url in extract_links(raw)
        ]
        return {
            **data,
            "text": text,
            "status": "available" if text.strip() else "not_published",
            "see_also": find_see_also(text),
            "links": links,
        }


class Nodes(BaseModel):
    """Contenitore dei nodi di una sezione.
    
    I nodi nuovi non rompono nulla ma finiscono in `unknown`, così una modifica additiva della fonte resta visibile.
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
    confidence: Literal["exact", "partial"] | None = None


class Meta(BaseModel):
    """Da dove viene questa risposta e quando. Mai una cache silenziosa.
    """

    last_updated: datetime | None = None   # dalla fonte: updateDate della scheda, o l'avviso più recente
    retrieved_at: datetime                 # quando abbiamo scaricato davvero il payload
    cache_status: CacheStatus              # "stale" = la fonte non risponde, questa è la copia locale
    age_seconds: int                       # età della copia servita


class CountrySheet(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    country: CountryRef | None = None
    meta: Meta | None = None
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


StatoAvvisi = Literal["avvisi_presenti", "nessun_avviso_pubblicato", "non_verificabile"]


class Avvisi(BaseModel):
    """Gli avvisi di un Paese
    """

    stato: StatoAvvisi
    messaggio: str              # la frase da riportare all'operatore, già scritta: non parafrasarla
    ultima_ora: list[Alert] = Field(default_factory=list)
    focus: list[Alert] = Field(default_factory=list)


class TopicRef(BaseModel):
    """Voce dell'indice degli argomenti: abbastanza per scegliere, troppo poco per rispondere."""

    key: str
    title: str
    status: TopicStatus
    chars: int


class GuideNode(BaseModel):
    """Un nodo di `/approfondimenti/{nome}.json`. I contenitori hanno `contenuto` vuoto."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str = Field(alias="nome")
    html: str = Field(default="", alias="contenuto")
    children: list[GuideNode] = Field(default_factory=list, alias="sezioni")


class GuideSection(BaseModel):
    """Una sezione con testo di una guida tematica: l'unità che si indicizza e si restituisce."""

    id: str                 # "{guida}/{id della fonte}", refusi della fonte compresi
    breadcrumb: str         # "Salute in viaggio > Malattie del viaggiatore > Dengue"
    title: str
    text: str
    links: list[Link] = Field(default_factory=list)
    page: str               # pagina della guida sul sito, da citare


class GuideHit(GuideSection):
    score: float


class Source(BaseModel):
    page: str
    data: str
    pdf: str | None = None



T = TypeVar("T")


class ToolResponse(BaseModel, Generic[T]):
    """Envelope comune a tutti i tool
    """

    country: CountryRef | None = None
    topic: str
    data: T
    updated_at: datetime | None = None
    sources: Source | list[Source]
    meta: Meta | None = None
    notice: str = DISCLAIMER
