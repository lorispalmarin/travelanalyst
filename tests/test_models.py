from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from viaggiaresicuri_mcp.models import CountrySheet, Topic, with_fallback


class TestContrattoScheda:
    def test_valida_una_scheda_reale(self, albania: CountrySheet):
        assert albania.updated_at.year >= 2024
        assert albania.entry.nodes.passport.status == "available"
        assert albania.unknown_sections == []

    def test_i_28_nodi_sono_tutti_presenti(self, albania: CountrySheet):
        sezioni = ["changelog", "highlights", "general", "entry", "security", "health", "mobility"]
        totale = sum(len(getattr(albania, s).nodes.topics()) for s in sezioni)
        assert totale == 28

    def test_un_nodo_mancante_fa_fallire_la_validazione(self, albania_payload: dict):
        """Se la fonte toglie un nodo dobbiamo accorgercene, non restituire mezza scheda."""
        rotto = copy.deepcopy(albania_payload)
        del rotto["infoRequisitiIngresso"]["nodi"]["Visto-di-ingresso"]
        with pytest.raises(ValidationError) as exc:
            CountrySheet.model_validate(rotto)
        # l'errore cita la chiave della fonte, non il nome del campo: è ciò che serve per capire
        # cosa è cambiato a monte
        assert "infoRequisitiIngresso.nodi.Visto-di-ingresso" in str(exc.value)

    def test_una_sezione_mancante_fa_fallire_la_validazione(self, albania_payload: dict):
        rotto = copy.deepcopy(albania_payload)
        del rotto["infoSicurezza"]
        with pytest.raises(ValidationError):
            CountrySheet.model_validate(rotto)

    def test_un_nodo_nuovo_non_rompe_ma_resta_visibile(self, albania_payload: dict):
        """Una modifica additiva della fonte non deve spegnere il server, ma va vista."""
        esteso = copy.deepcopy(albania_payload)
        esteso["infoSicurezza"]["nodi"]["Nodo-Nuovo"] = {
            "titolo": "Nodo nuovo",
            "contenuto": "<p>contenuto</p>",
            "ordinamento": 9,
        }
        sheet = CountrySheet.model_validate(esteso)
        assert sheet.security.nodes.unknown == ["Nodo-Nuovo"]
        assert len(sheet.security.nodes.topics()) == 7

    def test_una_sezione_nuova_non_rompe_ma_resta_visibile(self, albania_payload: dict):
        esteso = copy.deepcopy(albania_payload)
        esteso["infoNuovaSezione"] = {"id": "x", "titolo": "x", "ordinamento": 9, "nodi": {}}
        sheet = CountrySheet.model_validate(esteso)
        assert sheet.unknown_sections == ["infoNuovaSezione"]


class TestNormalizzazioneNelContratto:
    def test_id_preso_dalla_chiave_del_dizionario(self, albania: CountrySheet):
        assert albania.entry.nodes.visa.id == "Visto-di-ingresso"

    def test_html_grezzo_non_finisce_nel_modello(self, albania: CountrySheet):
        assert "<p>" not in albania.entry.nodes.passport.text

    def test_i_contatti_consolari_conservano_i_link(self, albania: CountrySheet):
        links = albania.general.nodes.embassy_and_consulates.links
        assert any(link.kind == "email" for link in links)
        assert any("valona" in link.url.lower() for link in links)

    def test_campo_vuoto_diventa_not_published(self, albania: CountrySheet):
        # `Documentazione-necessaria` è vuoto in tutti i 222 paesi
        assert albania.general.nodes.required_documents.status == "not_published"
        assert albania.general.nodes.required_documents.text == ""


class TestFallback:
    def test_il_dettaglio_pubblicato_ha_la_precedenza(self, albania: CountrySheet):
        merged = with_fallback(
            albania.security.nodes.caution_areas, albania.highlights.nodes.caution_areas
        )
        assert merged.provenance == "detail"
        assert merged is albania.security.nodes.caution_areas

    def test_se_il_dettaglio_e_vuoto_usa_il_riassunto_dichiarandolo(self, austria: CountrySheet):
        detail = austria.security.nodes.caution_areas
        assert detail.status == "not_published", "la fixture Austria non ha più il campo vuoto"
        merged = with_fallback(detail, austria.highlights.nodes.caution_areas)
        assert merged.provenance == "summary"
        assert merged.status == "available"
        assert merged.id == detail.id
        assert "normali precauzioni" in merged.text

    def test_se_entrambi_sono_vuoti_resta_not_published(self):
        vuoto = Topic(id="x", title="x", text="", status="not_published")
        merged = with_fallback(vuoto, vuoto)
        assert merged.status == "not_published"
