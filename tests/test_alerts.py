"""Avvisi recenti: endpoint separato, tempi diversi, contratto diverso."""

from __future__ import annotations

import copy

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
    async def fetch(path: str):
        if path.endswith("/THA.json"):
            return thailandia
        if path.endswith("/ALB.json"):
            return albania
        return {"ultima_ora": [], "focus": []}

    monkeypatch.setattr("viaggiaresicuri_mcp.alerts.fetch_json", fetch)


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


class TestFetchAlerts:
    async def test_ordina_dal_piu_recente(self, fonte):
        avvisi = await alerts_module.fetch_alerts("THA")
        date = [a.published_at for a in avvisi if a.published_at]
        assert date == sorted(date, reverse=True)

    async def test_nessun_avviso_non_e_un_errore(self, fonte):
        assert await alerts_module.fetch_alerts("ALB") == []

    async def test_payload_senza_ultima_ora(self, monkeypatch):
        async def fetch(path: str):
            return {"focus": []}

        monkeypatch.setattr("viaggiaresicuri_mcp.alerts.fetch_json", fetch)
        with pytest.raises(UnexpectedPayload):
            await alerts_module.fetch_alerts("THA")

    async def test_payload_non_oggetto(self, monkeypatch):
        async def fetch(path: str):
            return []

        monkeypatch.setattr("viaggiaresicuri_mcp.alerts.fetch_json", fetch)
        with pytest.raises(UnexpectedPayload):
            await alerts_module.fetch_alerts("THA")

    async def test_avviso_malformato_fallisce_rumorosamente(self, monkeypatch, thailandia):
        rotto = copy.deepcopy(thailandia)
        del rotto["ultima_ora"][0]["titolo"]

        async def fetch(path: str):
            return rotto

        monkeypatch.setattr("viaggiaresicuri_mcp.alerts.fetch_json", fetch)
        with pytest.raises(UnexpectedPayload):
            await alerts_module.fetch_alerts("THA")
