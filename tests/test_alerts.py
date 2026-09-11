"""Avvisi recenti: endpoint separato, tempi diversi, contratto diverso."""

from __future__ import annotations

import json

import pytest

from viaggiaresicuri_mcp import alerts as alerts_module
from viaggiaresicuri_mcp.errors import UnexpectedPayload
from viaggiaresicuri_mcp.models import Alert


@pytest.fixture
def thailandia(alerts_payloads) -> dict:
    return alerts_payloads["THA"]


@pytest.fixture
def albania(alerts_payloads) -> dict:
    return alerts_payloads["ALB"]


@pytest.fixture
def fonte(monkeypatch, thailandia, albania):
    def risolvi(path: str):
        if path.endswith("/THA.json"):
            return thailandia
        if path.endswith("/ALB.json"):
            return albania
        return {"ultima_ora": [], "focus": []}

    async def scarica(path: str):
        payload = risolvi(path)
        return json.dumps(payload, ensure_ascii=False), payload

    monkeypatch.setattr("viaggiaresicuri_mcp.client._scarica", scarica)


class TestContrattoAvvisi:
    def test_normalizza_un_avviso(self, thailandia):
        avviso = Alert.model_validate(thailandia["ultima_ora"][0])
        assert avviso.id.startswith("ULTIMORA")
        assert avviso.country_iso3 == "THA"
        assert "<p>" not in avviso.text
        assert avviso.published_at is not None

    def test_i_campi_vuoti_della_fonte_diventano_none(self):
        avviso = Alert.model_validate(
            {"id": "X", "nazione": "", "tipologia": "", "titolo": " T ", "testo": "<p>t</p>",
             "tsModifica": "1788875100"}
        )
        assert avviso.country_iso3 is None
        assert avviso.category is None
        assert avviso.title == "T"

    def test_timestamp_illeggibile_non_fa_saltare_l_avviso(self):
        avviso = Alert.model_validate(
            {"id": "X", "titolo": "T", "testo": "t", "tsModifica": "non-un-numero"}
        )
        assert avviso.published_at is None

    def test_estrae_i_link_dal_testo(self, thailandia):
        avvisi = [Alert.model_validate(a) for a in thailandia["ultima_ora"]]
        assert any(a.links for a in avvisi)


def _sorgente(monkeypatch, payload):
    async def scarica(path: str):
        return json.dumps(payload, ensure_ascii=False), payload

    monkeypatch.setattr("viaggiaresicuri_mcp.client._scarica", scarica)


# ---------------------------------------------------------------------------
# I tre stati. È la parte che conta: un array vuoto e una fonte irraggiungibile
# producono la stessa lista vuota ma significano cose opposte.

from datetime import UTC, datetime, timedelta  # noqa: E402

from viaggiaresicuri_mcp import client as client_module  # noqa: E402
from viaggiaresicuri_mcp.cache import Cache  # noqa: E402
from viaggiaresicuri_mcp.config import ALERTS_TTL_SECONDS, alerts_path  # noqa: E402
from viaggiaresicuri_mcp.errors import SourceUnavailable  # noqa: E402


@pytest.fixture
def fonte_completa(monkeypatch, alerts_payloads):
    """La fonte reale registrata: ALB vuoto, UKR e ISR con un avviso."""
    def risolvi(path: str):
        iso3 = path.rsplit("/", 1)[-1].removesuffix(".json")
        return alerts_payloads[iso3]

    async def scarica(path: str):
        payload = risolvi(path)
        return json.dumps(payload, ensure_ascii=False), payload

    monkeypatch.setattr("viaggiaresicuri_mcp.client._scarica", scarica)


class TestTreStati:
    async def test_avvisi_presenti(self, fonte_completa):
        avvisi, meta = await alerts_module.leggi_avvisi("UKR", "Ucraina")
        assert avvisi.stato == "avvisi_presenti"
        assert len(avvisi.ultima_ora) == 1
        assert avvisi.ultima_ora[0].category == "sicurezza", "la categoria è quella della fonte"
        assert meta.cache_status == "fresh"

    async def test_nessun_avviso_pubblicato(self, fonte_completa):
        """Array vuoti: non è un errore, ed è il caso normale."""
        avvisi, _ = await alerts_module.leggi_avvisi("ALB", "Albania")
        assert avvisi.stato == "nessun_avviso_pubblicato"
        assert avvisi.ultima_ora == [] and avvisi.focus == []

    async def test_il_messaggio_non_rassicura_mai(self, fonte_completa):
        avvisi, _ = await alerts_module.leggi_avvisi("ALB", "Albania")
        testo = avvisi.messaggio.lower()
        assert "non che il paese sia sicuro" in testo
        for rassicurazione in ("è sicuro", "tranquill", "nessun problema", "si può partire"):
            assert rassicurazione not in testo.replace("non che il paese sia sicuro", "")

    async def test_due_paesi_con_avviso_si_comportano_uguale(self, fonte_completa):
        for iso3 in ("UKR", "ISR"):
            avvisi, _ = await alerts_module.leggi_avvisi(iso3)
            assert avvisi.stato == "avvisi_presenti"
            assert avvisi.ultima_ora[0].published_at is not None

    async def test_timestamp_stringa_diventa_data(self, fonte_completa):
        avvisi, _ = await alerts_module.leggi_avvisi("UKR")
        quando = avvisi.ultima_ora[0].published_at
        assert isinstance(quando, datetime)
        assert quando.isoformat().startswith("2026-08-18")

    async def test_ordinati_dal_piu_recente(self, fonte_completa):
        avvisi, _ = await alerts_module.leggi_avvisi("THA")
        date = [a.published_at for a in avvisi.ultima_ora]
        assert date == sorted(date, reverse=True)


class TestNonVerificabile:
    """Il terzo stato: la fonte non risponde e la copia locale non dimostra niente."""

    @pytest.fixture
    def cache(self, tmp_path, monkeypatch):
        store = Cache(tmp_path / "cache.sqlite3")
        monkeypatch.setattr(client_module, "CACHE_ENABLED", True)
        monkeypatch.setattr(client_module, "_cache", store)
        monkeypatch.setattr(client_module, "_in_volo", {})
        return store

    async def _invecchia(self, cache, iso3, ore):
        url = client_module.url_for(alerts_path(iso3))
        entry = await cache.get(url)
        await cache.put(url, entry.body, retrieved_at=datetime.now(UTC) - timedelta(hours=ore))

    async def test_copia_vuota_non_diventa_nessun_avviso(self, cache, fonte_completa, monkeypatch):
        """Il caso che questo stato esiste per prevenire: dire "nessun avviso" da uno snapshot vecchio."""
        await alerts_module.leggi_avvisi("ALB", "Albania")          # popola la cache
        await self._invecchia(cache, "ALB", ore=9)

        async def giu(path):
            raise SourceUnavailable("connessione rifiutata")

        monkeypatch.setattr(client_module, "_scarica", giu)
        avvisi, meta = await alerts_module.leggi_avvisi("ALB", "Albania")

        assert avvisi.stato == "non_verificabile"
        assert meta.cache_status == "stale"
        assert "non posso verificare" in avvisi.messaggio
        assert "nessun avviso" not in avvisi.messaggio.lower()
        assert "viaggiaresicuri.it" in avvisi.messaggio

    async def test_copia_con_avvisi_li_riporta_ma_non_li_dichiara_completi(
        self, cache, fonte_completa, monkeypatch
    ):
        await alerts_module.leggi_avvisi("UKR", "Ucraina")
        await self._invecchia(cache, "UKR", ore=9)

        async def giu(path):
            raise SourceUnavailable("timeout")

        monkeypatch.setattr(client_module, "_scarica", giu)
        avvisi, _ = await alerts_module.leggi_avvisi("UKR", "Ucraina")

        assert avvisi.stato == "non_verificabile"
        assert len(avvisi.ultima_ora) == 1, "la copia vecchia si serve comunque"
        assert "potrebbero essercene di nuovi" in avvisi.messaggio

    async def test_il_ttl_degli_avvisi_e_quello_breve(self, cache, fonte_completa, monkeypatch):
        """15 minuti, non 6 ore: una copia di mezz'ora fa viene rivalidata."""
        chiamate: list[str] = []
        vero = client_module._scarica

        async def contando(path):
            chiamate.append(path)
            return await vero(path)

        monkeypatch.setattr(client_module, "_scarica", contando)
        await alerts_module.leggi_avvisi("ALB")
        await self._invecchia(cache, "ALB", ore=0.5)
        await alerts_module.leggi_avvisi("ALB")

        assert len(chiamate) == 2, f"con TTL {ALERTS_TTL_SECONDS}s mezz'ora è già da rivalidare"


class TestFocus:
    async def test_focus_vuoto_e_la_norma(self, fonte_completa):
        for iso3 in ("ALB", "UKR", "ISR", "THA"):
            avvisi, _ = await alerts_module.leggi_avvisi(iso3)
            assert avvisi.focus == []

    async def test_focus_popolato_si_legge_come_ultima_ora(self, monkeypatch):
        payload = {
            "ultima_ora": [],
            "focus": [{"id": "F1", "nazione": "", "tipologia": "", "titolo": "Consigli",
                       "testo": "<p>Testo</p>", "tsModifica": "1787042700"}],
        }
        _sorgente(monkeypatch, payload)
        avvisi, _ = await alerts_module.leggi_avvisi("XXX")
        assert avvisi.stato == "avvisi_presenti"
        assert avvisi.focus[0].title == "Consigli"
        assert avvisi.focus[0].text == "Testo"

    async def test_una_voce_di_focus_malformata_non_azzera_gli_avvisi(self, monkeypatch, caplog):
        """Asimmetria voluta: `focus` è tollerante, `ultima_ora` no."""
        payload = {
            "ultima_ora": [{"id": "A", "titolo": "Vero avviso", "testo": "<p>x</p>",
                            "tsModifica": "1787042700"}],
            "focus": [{"id": "F1", "testo": "<p>senza titolo</p>"}],
        }
        _sorgente(monkeypatch, payload)
        avvisi, _ = await alerts_module.leggi_avvisi("XXX")
        assert len(avvisi.ultima_ora) == 1
        assert avvisi.focus == []

    async def test_ultima_ora_malformata_fallisce_rumorosamente(self, monkeypatch):
        _sorgente(monkeypatch, {"ultima_ora": [{"id": "A", "testo": "x"}], "focus": []})
        with pytest.raises(UnexpectedPayload):
            await alerts_module.leggi_avvisi("XXX")

    async def test_manca_focus_e_un_errore_di_contratto(self, monkeypatch):
        _sorgente(monkeypatch, {"ultima_ora": []})
        with pytest.raises(UnexpectedPayload):
            await alerts_module.leggi_avvisi("XXX")

    async def test_manca_ultima_ora_e_un_errore_di_contratto(self, monkeypatch):
        _sorgente(monkeypatch, {"focus": []})
        with pytest.raises(UnexpectedPayload):
            await alerts_module.leggi_avvisi("XXX")

    async def test_payload_non_oggetto(self, monkeypatch):
        _sorgente(monkeypatch, [])
        with pytest.raises(UnexpectedPayload):
            await alerts_module.leggi_avvisi("XXX")
