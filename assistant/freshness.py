"""L'avviso "stiamo leggendo una copia locale", costruito dal codice e non chiesto al modello.

Il server MCP dichiara la freschezza nel campo `meta` di ogni risposta, ma dichiararla non basta:
se l'unica garanzia che l'utente lo venga a sapere è una riga nel system prompt, la garanzia non
c'è. Un modello che salta quella riga produce una risposta indistinguibile da una aggiornata, su
requisiti di ingresso e allerte di sicurezza.

Quindi l'avviso viene anteposto qui, deterministicamente, leggendo `meta.cache_status` dal
risultato del tool. Il prompt ha una regola gemella (prompts.py) con il compito opposto: dire al
modello che l'avviso c'è già, così non lo raddoppia.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

VERIFICA = "Verifica su viaggiaresicuri.it prima della partenza."


@dataclass(frozen=True)
class Freschezza:
    retrieved_at: datetime
    age_seconds: int
    last_updated: datetime | None


def _quando(valore: Any) -> datetime | None:
    if not isinstance(valore, str) or not valore:
        return None
    try:
        return datetime.fromisoformat(valore)
    except ValueError:
        return None


def estrai(contenuto: str) -> Freschezza | None:
    """La freschezza di un risultato di tool, ma solo se è `stale`. Altrimenti None.

    Tutto quello che non è un JSON con un `meta` leggibile vale None: un errore del tool arriva
    come testo, e non deve far saltare il turno.
    """
    try:
        payload = json.loads(contenuto)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta")
    if not isinstance(meta, dict) or meta.get("cache_status") != "stale":
        return None
    recuperato = _quando(meta.get("retrieved_at"))
    if recuperato is None:
        return None
    return Freschezza(
        retrieved_at=recuperato,
        age_seconds=int(meta.get("age_seconds") or 0),
        last_updated=_quando(meta.get("last_updated")),
    )


def _eta(secondi: int) -> str:
    """L'età come la si dice a voce: "circa" solo dove c'è un numero da arrotondare."""
    return "meno di un minuto fa" if secondi < 60 else f"circa {_durata(secondi)} fa"


def _durata(secondi: int) -> str:
    if secondi < 60:
        return "meno di un minuto"
    if secondi < 3600:
        minuti = max(1, secondi // 60)
        return "un minuto" if minuti == 1 else f"{minuti} minuti"
    if secondi < 86400:
        ore = secondi // 3600
        return "un'ora" if ore == 1 else f"{ore} ore"
    giorni = secondi // 86400
    return "un giorno" if giorni == 1 else f"{giorni} giorni"


def _data_e_ora(quando: datetime) -> str:
    return quando.astimezone().strftime("%d/%m/%Y alle %H:%M")


def avviso(freschezza: Freschezza) -> str:
    """Il testo da anteporre alla risposta. Dice tre date diverse perché sono tre cose diverse:
    quando abbiamo scaricato, quanto è vecchia la copia, a quando la fonte dichiarava di essere
    aggiornata."""
    parti = [
        "⚠️ **Il sito Viaggiare Sicuri non è raggiungibile in questo momento.** "
        f"Le informazioni che seguono provengono dalla copia locale recuperata il "
        f"{_data_e_ora(freschezza.retrieved_at)} ({_eta(freschezza.age_seconds)})"
    ]
    if freschezza.last_updated is not None:
        parti.append(
            f"; la scheda risultava aggiornata dalla Farnesina al "
            f"{freschezza.last_updated.astimezone().strftime('%d/%m/%Y')}"
        )
    parti.append(f". {VERIFICA}")
    return "".join(parti)
