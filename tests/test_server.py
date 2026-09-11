"""I tool MCP, con la fonte sostituita dalle fixture: nessuna rete, comportamento reale."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from viaggiaresicuri_mcp.countries import reset_index
from viaggiaresicuri_mcp.errors import SourceNotFound
from viaggiaresicuri_mcp.server import mcp


@pytest.fixture(autouse=True)
def fonte_finta(monkeypatch, country_records, albania_payload, austria_payload, alerts_payloads):
    def risolvi(path: str):
        if path.endswith("lista_nazioni.json"):
            return country_records
        if path.startswith("/ultima_ora/"):
            iso3 = path.rsplit("/", 1)[-1].removesuffix(".json")
            if iso3 in alerts_payloads:
                return alerts_payloads[iso3]
            return {"ultima_ora": [], "focus": []}
        if path.endswith("/ALB.json"):
            return albania_payload
        if path.endswith("/AUT.json"):
            return austria_payload
        raise SourceNotFound(path)

    async def scarica(path: str):
        payload = risolvi(path)
        return json.dumps(payload, ensure_ascii=False), payload

    # Si sostituisce il trasporto, non i tre moduli che lo usano: sotto la cache, così lo stesso
    # doppio vale con la cache accesa o spenta.
    monkeypatch.setattr("viaggiaresicuri_mcp.client._scarica", scarica)
    reset_index()
    yield
    reset_index()


async def chiama(nome: str, **argomenti) -> dict:
    async with Client(mcp) as client:
        result = await client.call_tool(nome, argomenti)
        return json.loads(result.content[0].text)


class TestSuperficieDeiTool:
    async def test_tool_registrati(self):
        async with Client(mcp) as client:
            nomi = {t.name for t in await client.list_tools()}
        assert nomi == {
            "find_country",
            "get_entry_requirements",
            "get_security_info",
            "get_health_info",
            "get_local_transport",
            "get_embassy_contacts",
            "get_practical_info",
            "list_country_topics",
            "get_country_topics",
            "search_approfondimenti",
            "get_allerte",
        }

    async def test_ogni_descrizione_elenca_i_contenuti(self):
        """Il modello sceglie sulla descrizione: se è vaga, sbaglia tool."""
        async with Client(mcp) as client:
            per_nome = {t.name: t.description or "" for t in await client.list_tools()}
        assert "normative locali" in per_nome["get_security_info"].lower()
        assert "minori" in per_nome["get_entry_requirements"].lower()
        assert "emergenza" in per_nome["get_embassy_contacts"].lower()


class TestRisposte:
    async def test_requisiti_di_ingresso(self):
        payload = await chiama("get_entry_requirements", country="Albania")
        assert payload["country"]["iso3"] == "ALB"
        assert len(payload["data"]) == 5
        assert payload["sources"]["page"].endswith("/ALB")
        assert payload["updated_at"]

    async def test_filtro_sui_topic(self):
        payload = await chiama("get_entry_requirements", country="ALB", topics=["visa"])
        assert [t["id"] for t in payload["data"]] == ["Visto-di-ingresso"]

    async def test_ogni_risposta_porta_il_disclaimer(self):
        payload = await chiama("get_health_info", country="Albania")
        assert "verificare le indicazioni ufficiali" in payload["notice"]

    async def test_contatti_puntano_al_pdf_di_una_pagina(self):
        payload = await chiama("get_embassy_contacts", country="Albania")
        assert payload["sources"]["pdf"].endswith("_contactDetails.pdf")
        assert any(link["kind"] == "email" for link in payload["data"][0]["links"])

    async def test_fallback_dichiarato_nella_risposta(self):
        payload = await chiama("get_security_info", country="Austria", topics=["caution_areas"])
        topic = payload["data"][0]
        assert topic["provenance"] == "summary"
        assert topic["status"] == "available"

    async def test_campo_non_pubblicato_resta_esplicito(self):
        payload = await chiama("get_practical_info", country="Albania")
        stati = {t["id"]: t["status"] for t in payload["data"]}
        assert set(stati.values()) <= {"available", "not_published"}


class TestIndiceEFetch:
    async def test_indice_copre_tutti_i_nodi(self):
        payload = await chiama("list_country_topics", country="Albania")
        chiavi = [voce["key"] for voce in payload["data"]]
        assert len(chiavi) == 28
        assert len(set(chiavi)) == 28
        assert "security.local_laws" in chiavi

    async def test_indice_costa_molto_meno_dei_contenuti(self):
        indice = await chiama("list_country_topics", country="Albania")
        peso_indice = len(json.dumps(indice, ensure_ascii=False))
        peso_totale = sum(voce["chars"] for voce in indice["data"])
        assert peso_indice < peso_totale / 3

    async def test_fetch_per_chiave(self):
        payload = await chiama(
            "get_country_topics", country="Albania", keys=["entry.minors", "security.local_laws"]
        )
        assert [t["id"] for t in payload["data"]] == [
            "Viaggi-all-estero-dei-minori",
            "Normative-locali-rilevanti",
        ]

    async def test_chiave_inesistente_spiega_come_rimediare(self):
        with pytest.raises(Exception) as exc:
            await chiama("get_country_topics", country="Albania", keys=["pippo.pluto"])
        assert "list_country_topics" in str(exc.value)


class TestFiltroArgomenti:
    """Un filtro che non matcha nulla deve fallire: una lista vuota verrebbe letta come
    "la fonte non pubblica niente su questo tema"."""

    async def test_chiave_inventata_e_un_errore_non_una_risposta_vuota(self):
        with pytest.raises(Exception) as exc:
            await chiama("get_security_info", country="Albania", topics=["droga"])
        messaggio = str(exc.value)
        assert "unknown_topic" in messaggio
        assert "local_laws" in messaggio, "l'errore deve elencare i valori ammessi"

    async def test_accetta_anche_l_id_della_fonte(self):
        """È l'id che il modello vede nelle risposte, quindi è quello che tenderà a riusare."""
        per_id = await chiama(
            "get_security_info", country="Albania", topics=["Normative-locali-rilevanti"]
        )
        per_campo = await chiama("get_security_info", country="Albania", topics=["local_laws"])
        assert [t["id"] for t in per_id["data"]] == [t["id"] for t in per_campo["data"]]

    async def test_accetta_la_chiave_completa(self):
        payload = await chiama(
            "get_security_info", country="Albania", topics=["security.local_laws"]
        )
        assert [t["id"] for t in payload["data"]] == ["Normative-locali-rilevanti"]

    async def test_la_risposta_espone_la_chiave_da_usare_nei_filtri(self):
        payload = await chiama("get_security_info", country="Albania", topics=["local_laws"])
        assert payload["data"][0]["key"] == "security.local_laws"

    async def test_anche_la_sanita_ha_il_filtro(self):
        payload = await chiama("get_health_info", country="Albania", topics=["vaccinations"])
        assert len(payload["data"]) == 1


class TestErrori:
    async def test_paese_ambiguo_elenca_i_candidati(self):
        with pytest.raises(Exception) as exc:
            await chiama("get_health_info", country="corea")
        messaggio = str(exc.value)
        assert "ambiguo" in messaggio
        assert "KOR" in messaggio and "PRK" in messaggio

    async def test_paese_inesistente(self):
        with pytest.raises(Exception) as exc:
            await chiama("get_health_info", country="zzzzzz")
        assert "Nessun Paese" in str(exc.value)

    async def test_fonte_non_disponibile_non_espone_eccezioni_grezze(self):
        with pytest.raises(Exception) as exc:
            await chiama("get_health_info", country="Brasile")  # fuori dalle fixture
        messaggio = str(exc.value)
        assert "non disponibile" in messaggio
        assert "httpx" not in messaggio

    async def test_find_country_restituisce_i_candidati_senza_scegliere(self):
        payload = await chiama("find_country", query="corea")
        assert payload["match"] is None
        assert {c["iso3"] for c in payload["candidates"]} == {"KOR", "PRK"}


class TestAllerte:
    """Il tool: i tre stati devono arrivare fino al contratto di risposta."""

    async def test_stato_e_messaggio_arrivano_nella_risposta(self):
        payload = await chiama("get_allerte", iso3="UKR")
        dati = payload["data"]
        assert dati["stato"] == "avvisi_presenti"
        assert dati["messaggio"]
        assert payload["country"]["iso3"] == "UKR"
        assert payload["meta"]["cache_status"] == "fresh"

    async def test_paese_senza_avvisi_non_e_un_errore(self):
        payload = await chiama("get_allerte", iso3="ALB")
        assert payload["data"]["stato"] == "nessun_avviso_pubblicato"
        assert payload["data"]["ultima_ora"] == []
        assert "non che il Paese sia sicuro" in payload["data"]["messaggio"]

    async def test_accetta_anche_il_nome_del_paese(self):
        """La docstring chiede l'ISO3, ma un nome non deve dare un 404 incomprensibile."""
        payload = await chiama("get_allerte", iso3="Ucraina")
        assert payload["country"]["iso3"] == "UKR"

    async def test_la_categoria_resta_quella_della_fonte(self):
        payload = await chiama("get_allerte", iso3="THA")
        categorie = {a["category"] for a in payload["data"]["ultima_ora"]}
        assert categorie == {"sicurezza", "sanita"}, "non si reinventa la tassonomia"

    async def test_la_descrizione_dice_quando_chiamarlo_e_quando_no(self):
        """È l'unico tool che si chiama senza che l'abbiano chiesto: la descrizione deve dire
        sia quando conviene sia quando è una chiamata sprecata, o torna il riflesso a ogni turno."""
        async with Client(mcp) as client:
            per_nome = {t.name: (t.description or "").lower() for t in await client.list_tools()}
        descrizione = per_nome["get_allerte"]
        assert "anche se le allerte non sono state chieste" in descrizione
        assert "sprecata" in descrizione
