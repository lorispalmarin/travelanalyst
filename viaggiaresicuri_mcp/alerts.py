"""Avvisi recenti: `/ultima_ora/{ISO3}.json`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import ValidationError

from .client import fetch
from .config import ALERTS_TTL_SECONDS, alerts_path, alerts_url, page_url
from .errors import UnexpectedPayload
from .models import Alert, Avvisi, Meta, Source

logger = logging.getLogger(__name__)

_SENZA_DATA = datetime.min.replace(tzinfo=UTC)


def alerts_source_for(iso3: str) -> Source:
    return Source(page=page_url(iso3), data=alerts_url(iso3))


def _ordina(avvisi: list[Alert]) -> list[Alert]:
    return sorted(avvisi, key=lambda a: a.published_at or _SENZA_DATA, reverse=True)


def _lista(payload: dict, chiave: str, iso3: str) -> list:
    grezzi = payload.get(chiave)
    if grezzi is None:
        raise UnexpectedPayload(f"manca la lista '{chiave}' negli avvisi di {iso3}")
    if not isinstance(grezzi, list):
        raise UnexpectedPayload(f"'{chiave}' non è una lista negli avvisi di {iso3}")
    return grezzi


def _valida_focus(grezzi: list, iso3: str) -> list[Alert]:
    """`focus` si valida voce per voce, e una voce malformata si salta.

    Asimmetria voluta rispetto a `ultima_ora`, che invece fallisce rumorosamente. `focus` è
    vuoto in tutti i Paesi osservati e porta contenuto editoriale non riferito al Paese: se un
    giorno la fonte lo popola con una forma diversa, il prezzo non deve essere che il tool degli
    avvisi smette di funzionare — sarebbe il guasto peggiore proprio dove serve di più.
    """
    voci: list[Alert] = []
    for item in grezzi:
        try:
            voci.append(Alert.model_validate(item))
        except ValidationError as exc:
            logger.warning("voce di 'focus' scartata per %s: %s", iso3, exc.errors()[0]["loc"])
    return voci


def _frase(stato: str, nome: str, quanti: int, quando: datetime | None) -> str:
    """La frase pronta per l'operatore. È nel contratto perché non venga riscritta a piacere."""
    if stato == "avvisi_presenti":
        quali = "un avviso" if quanti == 1 else f"{quanti} avvisi"
        return (
            f"La fonte è stata consultata adesso e riporta {quali} in corso per {nome}. "
            "Vanno riportati prima di ogni altra informazione."
        )
    if stato == "nessun_avviso_pubblicato":
        return (
            f"La fonte è stata consultata adesso e non riporta avvisi per {nome}. "
            "Significa che la Farnesina non ha pubblicato avvisi, non che il Paese sia sicuro."
        )
    data = f"{quando:%d/%m/%Y}" if quando else "data non disponibile"
    if quanti:
        return (
            "Non riesco a contattare la fonte ufficiale, quindi non posso verificare se ci sono "
            f"avvisi in corso adesso. L'ultima copia disponibile, del {data}, riportava gli "
            f"avvisi qui elencati per {nome}, ma potrebbero essercene di nuovi. Ti consiglio di "
            "controllare direttamente viaggiaresicuri.it prima di partire."
        )
    return (
        "Non riesco a contattare la fonte ufficiale, quindi non posso verificare se ci sono "
        f"avvisi in corso. L'ultima copia disponibile, del {data}, non ne riportava. Ti consiglio "
        "di controllare direttamente viaggiaresicuri.it prima di partire."
    )


async def leggi_avvisi(iso3: str, nome: str | None = None) -> tuple[Avvisi, Meta]:
    """Gli avvisi di un Paese con lo stato di verificabilità, non solo con la lista.

    Il TTL qui è quello degli avvisi, non quello generale: 15 minuti. Se la fonte non risponde si
    serve comunque la copia — la regola generale non cambia — ma lo stato diventa
    `non_verificabile`, perché su questo endpoint una lista vuota vecchia non è un'informazione.
    """
    scaricati = await fetch(alerts_path(iso3), ttl_seconds=ALERTS_TTL_SECONDS)
    payload = scaricati.payload
    if not isinstance(payload, dict):
        raise UnexpectedPayload(f"gli avvisi di {iso3} non sono un oggetto JSON")

    grezzi = _lista(payload, "ultima_ora", iso3)
    try:
        ultima_ora = _ordina([Alert.model_validate(item) for item in grezzi])
    except ValidationError as exc:
        raise UnexpectedPayload(
            f"un avviso di {iso3} non ha la forma attesa: "
            f"{'.'.join(str(p) for p in exc.errors()[0]['loc'])}"
        ) from exc
    focus = _ordina(_valida_focus(_lista(payload, "focus", iso3), iso3))

    quanti = len(ultima_ora) + len(focus)
    if scaricati.cache_status == "stale":
        stato = "non_verificabile"
    elif quanti:
        stato = "avvisi_presenti"
    else:
        stato = "nessun_avviso_pubblicato"

    avvisi = Avvisi(
        stato=stato,
        messaggio=_frase(stato, nome or iso3, quanti, scaricati.retrieved_at),
        ultima_ora=ultima_ora,
        focus=focus,
    )
    meta = Meta(
        last_updated=ultima_ora[0].published_at if ultima_ora else None,
        retrieved_at=scaricati.retrieved_at,
        cache_status=scaricati.cache_status,
        age_seconds=scaricati.age_seconds,
    )
    return avvisi, meta
