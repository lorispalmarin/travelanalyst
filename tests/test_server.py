"""I tool MCP, con la fonte sostituita dalle fixture: nessuna rete, comportamento reale."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from viaggiaresicuri_mcp.countries import reset_index
from viaggiaresicuri_mcp.errors import SourceNotFound, SourceUnavailable
from viaggiaresicuri_mcp.client import Risposta
from viaggiaresicuri_mcp.server import mcp


@pytest.fixture(autouse=True)
def fonte_finta(
    monkeypatch, country_records, albania_payload, austria_payload, alerts_payloads, guide_payloads
):
    def risolvi(path: str):
        if path.endswith("lista_nazioni.json"):
            return country_records
        if path.startswith("/ultima_ora/"):
            iso3 = path.rsplit("/", 1)[-1].removesuffix(".json")
            if iso3 in alerts_payloads:
                return alerts_payloads[iso3]
            return {"ultima_ora": [], "focus": []}
        if path.startswith("/approfondimenti/"):
            return guide_payloads[path.rsplit("/", 1)[-1].removesuffix(".json")]
        if path.endswith("/ALB.json"):
            return albania_payload
        if path.endswith("/AUT.json"):
            return austria_payload
        raise SourceNotFound(path)

    async def scarica(path: str, condizionali=None):
        payload = risolvi(path)
        return Risposta(
            modificato=True,
            body=json.dumps(payload, ensure_ascii=False),
            payload=payload,
            etag=f'"{path}"',
            last_modified=None,
        )

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
            "get_allerte",
            "list_general_topics",
            "get_general_info",
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


class TestGuideGenerali:
    """I due tool senza Paese: il sommario delle guide e la sezione scelta."""

    async def test_il_sommario_elenca_tutte_le_sezioni(self):
        payload = await chiama("list_general_topics")
        assert payload["country"] is None
        assert len(payload["data"]) == 7
        assert {v["id"].split("/")[0] for v in payload["data"]} == {
            "preparaunviaggio",
            "documentidiviaggio",
        }
        assert all(v["chars"] > 0 and " > " in v["breadcrumb"] for v in payload["data"])
        assert {s["data"].rsplit("/", 1)[-1] for s in payload["sources"]} == {
            "preparaunviaggio.json",
            "documentidiviaggio.json",
        }

    async def test_il_sommario_sta_in_poche_righe(self):
        """È il motivo del disegno: l'elenco intero costa meno di una singola sezione."""
        payload = await chiama("list_general_topics")
        assert len(json.dumps(payload["data"], ensure_ascii=False)) < 1200

    async def test_la_sezione_arriva_con_percorso_pagina_e_avvertenza(self):
        payload = await chiama(
            "get_general_info", topic="documentidiviaggio/furtosmarrimentodidocumenti"
        )
        sezione = payload["data"]
        assert sezione["breadcrumb"].startswith("Documenti di viaggio > ")
        assert "Documento di viaggio provvisorio" in sezione["text"]
        assert "/approfondimenti-insights/documentidiviaggio" in sezione["page"]
        assert payload["sources"]["page"] == sezione["page"]
        assert payload["updated_at"] is None, "le guide non dichiarano una data di aggiornamento"
        assert "verificare le indicazioni ufficiali" in payload["notice"]

    async def test_un_id_inesistente_elenca_quelli_validi(self):
        with pytest.raises(Exception) as exc:
            await chiama("get_general_info", topic="documentidiviaggio/inventato")
        messaggio = str(exc.value)
        assert "unknown_topic" in messaggio
        assert "documentidiviaggio/furtosmarrimentodidocumenti" in messaggio

    async def test_guide_irraggiungibili_senza_copia_sono_un_errore_esplicito(self, monkeypatch):
        async def giu(path: str, condizionali=None):
            raise SourceUnavailable(f"{path} non raggiungibile")

        monkeypatch.setattr("viaggiaresicuri_mcp.client._scarica", giu)
        with pytest.raises(Exception) as exc:
            await chiama("list_general_topics")
        assert "source_unavailable" in str(exc.value)

    async def test_le_descrizioni_portano_dal_sommario_alla_sezione(self):
        async with Client(mcp) as client:
            per_nome = {t.name: (t.description or "").lower() for t in await client.list_tools()}
        assert "senza un paese" in per_nome["list_general_topics"]
        assert "get_general_info" in per_nome["list_general_topics"]
        assert "list_general_topics" in per_nome["get_general_info"]


class TestAvvioDelServer:
    def test_il_server_mcp_si_avvia_in_http(self, monkeypatch):
        from viaggiaresicuri_mcp import server

        chiamata = {}
        monkeypatch.setattr(server.mcp, "run", lambda **kwargs: chiamata.update(kwargs))
        server.main()
        assert chiamata["transport"] == "http"
        assert chiamata["path"] == "/mcp"
        assert chiamata["host"] == server.MCP_HOST
        assert chiamata["port"] == server.MCP_PORT

    def test_il_modulo_dichiara_un_entry_point_eseguibile(self):
        from viaggiaresicuri_mcp import server

        assert callable(server.main)
