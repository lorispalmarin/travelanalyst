"""Cache persistente dei payload della fonte.

Due funzioni, in ordine di importanza:

1. **Non scaricare un costo su un'infrastruttura pubblica.** Viaggiare Sicuri è un servizio del
   Ministero degli Affari Esteri: non espone API documentate né un contratto d'uso per client
   automatici, e i suoi contenuti si muovono sulla scala delle settimane. Un agente che rigenera
   traffico a ogni tool call non ne ricava nulla e il costo lo paga qualcun altro.
2. **Continuare a rispondere quando la fonte non risponde.**

La regola che governa tutto: **il TTL è una soglia di rivalidazione, non una scadenza di vita.**
Una entry scaduta non viene mai cancellata: superato il TTL si *tenta* il refetch, e se il
tentativo fallisce si serve comunque la copia vecchia, dichiarandola. Non c'è eviction: la
retention è illimitata per costruzione, non per dimenticanza.

Si cacha il corpo grezzo della risposta, sotto il livello di normalizzazione: un cambio di
parsing non invalida la cache, e ogni riga è un payload della fonte riusabile come fixture.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS payloads (
    url          TEXT PRIMARY KEY,
    body         TEXT NOT NULL,
    retrieved_at REAL NOT NULL,
    bytes        INTEGER NOT NULL
)
"""


@dataclass(frozen=True)
class Entry:
    """Una risposta della fonte, come è arrivata."""

    url: str
    body: str
    retrieved_at: datetime

    def age_seconds(self, now: float | None = None) -> int:
        adesso = time.time() if now is None else now
        return max(0, int(adesso - self.retrieved_at.timestamp()))

    def payload(self) -> Any:
        return json.loads(self.body)


class Cache:
    """Store SQLite su file. Una connessione per operazione, aperta nel thread che la esegue.

    SQLite e non Redis o diskcache: la cache deve sopravvivere al riavvio del processo (il server
    MCP viene avviato e fermato dal client a ogni sessione) senza aggiungere un servizio da
    installare né una dipendenza in più. Il corpus completo della fonte sta sotto i 10 MB.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._preparata = False

    # -- livello sincrono (gira in un thread) --------------------------------

    def _connessione(self) -> sqlite3.Connection:
        if not self._preparata:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        if not self._preparata:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(SCHEMA)
            conn.commit()
            self._preparata = True
        return conn

    def _leggi(self, url: str) -> Entry | None:
        with self._connessione() as conn:
            riga = conn.execute(
                "SELECT body, retrieved_at FROM payloads WHERE url = ?", (url,)
            ).fetchone()
        if riga is None:
            return None
        body, quando = riga
        return Entry(url=url, body=body, retrieved_at=datetime.fromtimestamp(quando, tz=UTC))

    def _scrivi(self, url: str, body: str, quando: datetime) -> Entry:
        with self._connessione() as conn:
            conn.execute(
                "INSERT INTO payloads (url, body, retrieved_at, bytes) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET body=excluded.body, "
                "retrieved_at=excluded.retrieved_at, bytes=excluded.bytes",
                (url, body, quando.timestamp(), len(body.encode("utf-8"))),
            )
        return Entry(url=url, body=body, retrieved_at=quando)

    def _misura(self) -> tuple[int, int]:
        with self._connessione() as conn:
            righe, byte = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM payloads"
            ).fetchone()
        return int(righe), int(byte)

    # -- superficie asincrona ------------------------------------------------

    async def get(self, url: str) -> Entry | None:
        """La entry per quell'URL, qualunque sia la sua età. None se non l'abbiamo mai vista."""
        return await asyncio.to_thread(self._leggi, url)

    async def put(self, url: str, body: str, retrieved_at: datetime | None = None) -> Entry:
        """Sovrascrive la entry. `retrieved_at` esplicito serve a ricostruire uno stato passato."""
        return await asyncio.to_thread(self._scrivi, url, body, retrieved_at or datetime.now(UTC))

    async def stats(self) -> tuple[int, int]:
        """(numero di entry, byte totali): serve a mostrare che la retention è sotto controllo."""
        return await asyncio.to_thread(self._misura)
