"""La cache: la regola è che il TTL rivalida, non scade.

Questi test esistono per fissare un comportamento che è l'opposto del default di quasi tutte le
librerie di cache: una entry scaduta **non** viene buttata. Se qualcuno un giorno la "aggiusta"
verso il comportamento standard, qui si accorge di cosa sta rompendo.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import Client

from viaggiaresicuri_mcp import client as client_module
from viaggiaresicuri_mcp.cache import Cache
from viaggiaresicuri_mcp.countries import reset_index
from viaggiaresicuri_mcp.errors import SourceNotFound, SourceUnavailable, UnexpectedPayload
from viaggiaresicuri_mcp.server import mcp

PERCORSO = "/schede_paese/ALB.json"
ORIGINALE = {"valore": "prima"}
AGGIORNATO = {"valore": "dopo"}


class Fonte:
    """Doppio del trasporto: conta le richieste e sa fingersi irraggiungibile."""

    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.chiamate: list[str] = []
        self.guasto: Exception | None = None

    async def __call__(self, path: str):
        self.chiamate.append(path)
        if self.guasto is not None:
            raise self.guasto
        if path not in self.payloads:
            raise SourceNotFound(path)
        payload = self.payloads[path]
        return json.dumps(payload, ensure_ascii=False), payload


@pytest.fixture
def cache(tmp_path, monkeypatch) -> Cache:
    """Cache accesa su un file usa e getta. Ogni test parte da uno store vuoto."""
    store = Cache(tmp_path / "cache.sqlite3")
    monkeypatch.setattr(client_module, "CACHE_ENABLED", True)
    monkeypatch.setattr(client_module, "_cache", store)
    # i lucchetti di single-flight sono legati al loop che li ha attesi: ogni test ha il suo
    monkeypatch.setattr(client_module, "_in_volo", {})
    return store


@pytest.fixture
def fonte(monkeypatch) -> Fonte:
    doppio = Fonte({PERCORSO: ORIGINALE})
    monkeypatch.setattr(client_module, "_scarica", doppio)
    return doppio


async def invecchia(cache: Cache, path: str, ore: float) -> None:
    """Riscrive la entry come se fosse stata scaricata `ore` fa."""
    url = client_module.url_for(path)
    entry = await cache.get(url)
    assert entry is not None
    await cache.put(url, entry.body, retrieved_at=datetime.now(UTC) - timedelta(hours=ore))


class TestSoglia:
    async def test_dentro_il_ttl_non_tocca_la_rete(self, cache, fonte, monkeypatch):
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        primo = await client_module.fetch(PERCORSO)
        secondo = await client_module.fetch(PERCORSO)

        assert fonte.chiamate == [PERCORSO], "la seconda lettura deve venire dal disco"
        assert primo.payload == secondo.payload == ORIGINALE
        assert secondo.cache_status == "fresh"

    async def test_l_eta_servita_e_quella_vera_non_zero(self, cache, fonte, monkeypatch):
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        await client_module.fetch(PERCORSO)
        await invecchia(cache, PERCORSO, ore=3)

        servito = await client_module.fetch(PERCORSO)
        assert servito.cache_status == "fresh", "3 ore con TTL 6 è ancora dentro la soglia"
        assert 10700 < servito.age_seconds < 10900
        assert len(fonte.chiamate) == 1

    async def test_oltre_il_ttl_rivalida(self, cache, fonte, monkeypatch):
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        await client_module.fetch(PERCORSO)
        await invecchia(cache, PERCORSO, ore=7)
        fonte.payloads[PERCORSO] = AGGIORNATO

        servito = await client_module.fetch(PERCORSO)
        assert len(fonte.chiamate) == 2
        assert servito.payload == AGGIORNATO
        assert servito.cache_status == "fresh"
        assert servito.age_seconds == 0


class TestFonteIrraggiungibile:
    async def test_serve_la_copia_vecchia_di_ore(self, cache, fonte, monkeypatch):
        """Il caso che giustifica tutto: TTL 6 ore, sito giù da 8, la risposta deve arrivare lo stesso."""
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        await client_module.fetch(PERCORSO)
        await invecchia(cache, PERCORSO, ore=8)
        fonte.guasto = SourceUnavailable("connessione rifiutata")

        servito = await client_module.fetch(PERCORSO)
        assert servito.payload == ORIGINALE, "la entry scaduta non deve essere stata cancellata"
        assert servito.cache_status == "stale"
        assert servito.age_seconds > 6 * 3600
        assert len(fonte.chiamate) == 2, "il refetch va tentato, non saltato"

    async def test_la_copia_resta_anche_dopo_giorni(self, cache, fonte, monkeypatch):
        """Nessuna eviction legata all'età: 30 giorni non sono diversi da 8 ore."""
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        await client_module.fetch(PERCORSO)
        await invecchia(cache, PERCORSO, ore=24 * 30)
        fonte.guasto = SourceUnavailable("timeout")

        servito = await client_module.fetch(PERCORSO)
        assert servito.cache_status == "stale"
        assert servito.payload == ORIGINALE

    async def test_senza_copia_e_un_errore_esplicito(self, cache, fonte):
        """Cache miss + fonte giù: si fallisce. L'alternativa sarebbe far rispondere il modello a memoria."""
        fonte.guasto = SourceUnavailable("DNS non risolve")
        with pytest.raises(SourceUnavailable):
            await client_module.fetch(PERCORSO)

    async def test_un_404_non_viene_coperto_dalla_copia(self, cache, fonte, monkeypatch):
        """404 è la fonte che *risponde*: mascherarlo nasconderebbe un cambio di contratto."""
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 0)
        await client_module.fetch(PERCORSO)
        fonte.guasto = SourceNotFound(PERCORSO)
        with pytest.raises(SourceNotFound):
            await client_module.fetch(PERCORSO)


class TestIntegritaDelloStore:
    async def test_si_cacha_il_payload_grezzo(self, cache, fonte):
        """Sotto la normalizzazione: ogni riga è un payload della fonte, riusabile come fixture."""
        await client_module.fetch(PERCORSO)
        entry = await cache.get(client_module.url_for(PERCORSO))
        assert json.loads(entry.body) == ORIGINALE

    async def test_un_corpo_non_json_non_entra_in_cache(self, cache, monkeypatch):
        async def html(path: str):
            raise UnexpectedPayload("non ha restituito JSON valido")

        monkeypatch.setattr(client_module, "_scarica", html)
        with pytest.raises(UnexpectedPayload):
            await client_module.fetch(PERCORSO)
        assert await cache.stats() == (0, 0)

    async def test_una_sola_richiesta_in_volo_per_url(self, cache, fonte, monkeypatch):
        """Due tool chiamati in parallelo sullo stesso Paese non devono raddoppiare il traffico."""
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        await asyncio.gather(*(client_module.fetch(PERCORSO) for _ in range(5)))
        assert fonte.chiamate == [PERCORSO]

    async def test_la_cache_sopravvive_al_processo(self, tmp_path, fonte, monkeypatch):
        """Il server MCP viene spento e riacceso a ogni sessione: lo store deve stare su disco."""
        monkeypatch.setattr(client_module, "CACHE_ENABLED", True)
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        monkeypatch.setattr(client_module, "_in_volo", {})
        percorso = tmp_path / "cache.sqlite3"

        monkeypatch.setattr(client_module, "_cache", Cache(percorso))
        await client_module.fetch(PERCORSO)

        monkeypatch.setattr(client_module, "_cache", Cache(percorso))  # "riavvio"
        monkeypatch.setattr(client_module, "_in_volo", {})
        servito = await client_module.fetch(PERCORSO)
        assert servito.payload == ORIGINALE
        assert fonte.chiamate == [PERCORSO]


class TestArrivaFinoAlTool:
    """La cache non deve restare un fatto interno: lo stato si legge nel contratto del tool."""

    @pytest.fixture
    def fonte_reale(self, monkeypatch, country_records, albania_payload):
        doppio = Fonte({
            "/schede_paese/lista_nazioni.json": country_records,
            "/schede_paese/ALB.json": albania_payload,
        })
        monkeypatch.setattr(client_module, "_scarica", doppio)
        reset_index()
        yield doppio
        reset_index()

    async def _chiama(self, nome: str, **argomenti) -> dict:
        async with Client(mcp) as c:
            risultato = await c.call_tool(nome, argomenti)
            return json.loads(risultato.content[0].text)

    async def test_meta_presente_su_una_risposta_fresca(self, cache, fonte_reale, monkeypatch):
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        risposta = await self._chiama("get_entry_requirements", country="Albania")
        meta = risposta["meta"]
        assert meta["cache_status"] == "fresh"
        assert meta["age_seconds"] == 0
        assert meta["last_updated"] == risposta["updated_at"]
        assert meta["retrieved_at"]

    async def test_meta_dichiara_la_copia_vecchia(self, cache, fonte_reale, monkeypatch):
        monkeypatch.setattr(client_module, "CACHE_TTL_SECONDS", 21600)
        await self._chiama("get_entry_requirements", country="Albania")

        await invecchia(cache, "/schede_paese/ALB.json", ore=9)
        await invecchia(cache, "/schede_paese/lista_nazioni.json", ore=9)
        fonte_reale.guasto = SourceUnavailable("la fonte non risponde")

        risposta = await self._chiama("get_entry_requirements", country="Albania")
        assert risposta["meta"]["cache_status"] == "stale"
        assert risposta["meta"]["age_seconds"] > 8 * 3600
        assert risposta["data"], "la risposta deve comunque contenere i contenuti"
