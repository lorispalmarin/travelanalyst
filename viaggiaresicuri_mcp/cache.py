"""Cache persistente dei payload della fonte.

Due funzioni, in ordine di importanza:

1. **Non scaricare un costo su un'infrastruttura pubblica.** Viaggiare Sicuri è un servizio del
   Ministero degli Affari Esteri: non espone API documentate né un contratto d'uso per client
   automatici, e i suoi contenuti si muovono sulla scala delle settimane. Un agente che rigenera
   traffico a ogni tool call non ne ricava nulla e il costo lo paga qualcun altro.
2. **Continuare a rispondere quando la fonte non risponde.**

La regola che governa tutto: **il TTL è una soglia di rivalidazione, non una scadenza di vita.**
Una entry scaduta non viene mai cancellata: superato il TTL si *tenta* di rivalidarla, e se il
tentativo fallisce si serve comunque la copia vecchia, dichiarandola. Non c'è eviction: la
retention è illimitata per costruzione, non per dimenticanza.

La rivalidazione è condizionale, e per questo ogni riga porta anche `etag` e `last_modified`: si
chiede alla fonte "è cambiato?" invece di "dammelo". Quando risponde 304 si aggiorna soltanto
`retrieved_at` — la copia è stata *verificata* adesso, pur essendo stata *scaricata* prima.

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
    url           TEXT PRIMARY KEY,
    body          TEXT NOT NULL,
    retrieved_at  REAL NOT NULL,
    bytes         INTEGER NOT NULL,
    etag          TEXT,
    last_modified TEXT
)
"""

# I validator sono arrivati dopo, e uno store già sul disco non va buttato per aggiungere due
# colonne: senza di esse la entry funziona comunque, la prima rivalidazione le riempie.
COLONNE_AGGIUNTE = ("etag", "last_modified")


@dataclass(frozen=True)
class Entry:
    """Una risposta della fonte, come è arrivata.

    `retrieved_at` è il momento dell'ultima *verifica*, non necessariamente dello scaricamento:
    un 304 conferma che il corpo è ancora quello buono e sposta la data della verifica lasciando
    il contenuto dov'è. `etag` e `last_modified` sono i validator con cui chiedere alla fonte
    "è cambiato?" senza farsi rimandare il payload.
    """

    url: str
    body: str
    retrieved_at: datetime
    etag: str | None = None
    last_modified: str | None = None

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
            presenti = {riga[1] for riga in conn.execute("PRAGMA table_info(payloads)")}
            for colonna in COLONNE_AGGIUNTE:
                if colonna not in presenti:
                    conn.execute(f"ALTER TABLE payloads ADD COLUMN {colonna} TEXT")
                    logger.info("cache: aggiunta la colonna %s allo store esistente", colonna)
            conn.commit()
            self._preparata = True
        return conn

    def _leggi(self, url: str) -> Entry | None:
        with self._connessione() as conn:
            riga = conn.execute(
                "SELECT body, retrieved_at, etag, last_modified FROM payloads WHERE url = ?",
                (url,),
            ).fetchone()
        if riga is None:
            return None
        body, quando, etag, last_modified = riga
        return Entry(
            url=url,
            body=body,
            retrieved_at=datetime.fromtimestamp(quando, tz=UTC),
            etag=etag,
            last_modified=last_modified,
        )

    def _scrivi(
        self,
        url: str,
        body: str,
        quando: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> Entry:
        with self._connessione() as conn:
            conn.execute(
                "INSERT INTO payloads (url, body, retrieved_at, bytes, etag, last_modified) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET body=excluded.body, "
                "retrieved_at=excluded.retrieved_at, bytes=excluded.bytes, "
                "etag=excluded.etag, last_modified=excluded.last_modified",
                (url, body, quando.timestamp(), len(body.encode("utf-8")), etag, last_modified),
            )
        return Entry(url=url, body=body, retrieved_at=quando, etag=etag, last_modified=last_modified)

    def _conferma(
        self,
        url: str,
        quando: datetime,
        etag: str | None,
        last_modified: str | None,
    ) -> Entry | None:
        """La fonte ha detto 304: il corpo resta, si sposta solo la data della verifica.

        I validator si sovrascrivono solo se il 304 ne porta di nuovi — la RFC lo consente e
        alcune origini lo fanno — altrimenti restano quelli che avevamo.
        """
        with self._connessione() as conn:
            conn.execute(
                "UPDATE payloads SET retrieved_at = ?, "
                "etag = COALESCE(?, etag), last_modified = COALESCE(?, last_modified) "
                "WHERE url = ?",
                (quando.timestamp(), etag, last_modified, url),
            )
        return self._leggi(url)

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

    async def put(
        self,
        url: str,
        body: str,
        retrieved_at: datetime | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> Entry:
        """Sovrascrive la entry. `retrieved_at` esplicito serve a ricostruire uno stato passato."""
        return await asyncio.to_thread(
            self._scrivi, url, body, retrieved_at or datetime.now(UTC), etag, last_modified
        )

    async def conferma(
        self,
        url: str,
        retrieved_at: datetime | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> Entry | None:
        """Registra che la copia è stata verificata adesso, senza toccarne il contenuto."""
        return await asyncio.to_thread(
            self._conferma, url, retrieved_at or datetime.now(UTC), etag, last_modified
        )

    async def stats(self) -> tuple[int, int]:
        """(numero di entry, byte totali): serve a mostrare che la retention è sotto controllo."""
        return await asyncio.to_thread(self._misura)
