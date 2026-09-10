"""Avvisi recenti: `/ultima_ora/{ISO3}.json`.

Endpoint separato dalla scheda paese e con tempi diversi: la scheda si aggiorna a mesi, gli
avvisi a ore. Un'allerta in corso non è recuperabile dalla scheda — per la Thailandia le
inondazioni del nord non compaiono in nessun nodo della scheda.

`totale.json` non serve qui: è un feed globale troncato a poche decine di elementi, quindi non
contiene tutti gli avvisi di un singolo Paese. Per Paese fa fede l'endpoint per Paese.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from .client import fetch_json
from .config import alerts_path, alerts_url, page_url
from .errors import UnexpectedPayload
from .models import Alert, Source

_SENZA_DATA = datetime.min.replace(tzinfo=UTC)


def alerts_source_for(iso3: str) -> Source:
    return Source(page=page_url(iso3), data=alerts_url(iso3))


async def fetch_alerts(iso3: str) -> list[Alert]:
    """Avvisi del Paese, dal più recente. Lista vuota se la fonte non ne pubblica."""
    payload = await fetch_json(alerts_path(iso3))
    if not isinstance(payload, dict):
        raise UnexpectedPayload(f"gli avvisi di {iso3} non sono un oggetto JSON")

    grezzi = payload.get("ultima_ora")
    if grezzi is None:
        raise UnexpectedPayload(f"manca la lista 'ultima_ora' negli avvisi di {iso3}")
    if not isinstance(grezzi, list):
        raise UnexpectedPayload(f"'ultima_ora' non è una lista negli avvisi di {iso3}")

    try:
        avvisi = [Alert.model_validate(item) for item in grezzi]
    except ValidationError as exc:
        raise UnexpectedPayload(
            f"un avviso di {iso3} non ha la forma attesa: "
            f"{'.'.join(str(p) for p in exc.errors()[0]['loc'])}"
        ) from exc

    return sorted(avvisi, key=lambda a: a.published_at or _SENZA_DATA, reverse=True)
