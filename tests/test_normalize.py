from __future__ import annotations

import pytest

from viaggiaresicuri_mcp.normalize import (
    extract_links,
    html_to_text,
    link_kind,
    split_see_also,
)


class TestHtmlToText:
    def test_decodifica_le_entita_non_decodificate_dalla_fonte(self):
        assert html_to_text("<p>dell&rsquo;Albania &amp; dell&#039;Italia</p>") == (
            "dell’Albania & dell'Italia"
        )

    def test_i_paragrafi_diventano_righe_vuote(self):
        assert html_to_text("<p>uno</p><p>due</p>") == "uno\n\ndue"

    def test_br_diventa_a_capo_singolo(self):
        assert html_to_text("Tirana<br />Telefono: 123") == "Tirana\nTelefono: 123"

    def test_rimuove_le_righe_decorative(self):
        # l'Austria chiude la sezione con una riga di asterischi
        assert html_to_text("<p>testo</p><p>*****************</p>") == "testo"

    def test_stringa_vuota_e_none(self):
        assert html_to_text(None) == ""
        assert html_to_text("") == ""
        assert html_to_text("<p></p>") == ""


class TestExtractLinks:
    def test_i_recapiti_consolari_sopravvivono_allo_strip(self):
        html = '<a href="mailto:consolato.valona@esteri.it">consolato.valona@esteri.it</a>'
        assert extract_links(html) == [("consolato.valona@esteri.it", "mailto:consolato.valona@esteri.it")]

    def test_deduplica_lo_stesso_url(self):
        html = '<a href="https://x.it">uno</a> <a href="https://x.it">due</a>'
        assert len(extract_links(html)) == 1

    def test_ignora_le_ancore_interne(self):
        assert extract_links('<a href="#top">su</a>') == []

    @pytest.mark.parametrize(
        "url,atteso",
        [("mailto:a@b.it", "email"), ("tel:+390612345", "phone"), ("https://esteri.it", "web")],
    )
    def test_tipo_del_link(self, url: str, atteso: str):
        assert link_kind(url) == atteso


class TestSplitSeeAlso:
    def test_estrae_il_rimando_e_lo_toglie_dal_testo(self):
        testo = (
            "Si raccomanda di adottare le normali precauzioni. "
            "Per maggiori informazioni, consultare la Sezione “Sicurezza” di questa Scheda."
        )
        pulito, refs = split_see_also(testo)
        assert refs == ["security"]
        assert "consultare" not in pulito
        assert pulito.startswith("Si raccomanda")

    def test_riconosce_piu_sezioni(self):
        testo = "Consultare la sezione Situazione Sanitaria e la sezione Requisiti di ingresso di questa Scheda."
        pulito, refs = split_see_also(testo)
        assert set(refs) == {"health", "entry"}
        assert pulito == ""

    def test_non_tocca_le_frasi_senza_rimando(self):
        testo = "Si raccomanda di consultare il proprio medico prima della partenza."
        pulito, refs = split_see_also(testo)
        assert refs == []
        assert pulito == testo

    def test_un_nodo_fatto_solo_di_rimando_resta_vuoto(self):
        # caso Thailandia: il nodo di primo piano è solo un puntatore
        testo = (
            "Nel Paese sono presenti alcune aree che richiedono una particolare cautela. "
            "Si raccomanda di consultare attentamente la Sezione “Sicurezza” di questa Scheda."
        )
        pulito, refs = split_see_also(testo)
        assert refs == ["security"]
        assert "Sezione" not in pulito

    def test_testo_vuoto(self):
        assert split_see_also("") == ("", [])


class TestIntegritaDelTesto:
    """Il punto non è sempre fine frase: dentro numeri, URL ed email va lasciato stare."""

    @pytest.mark.parametrize(
        "testo",
        [
            "Cellulare di emergenza +355 (0) 68.20.27.064 per i connazionali.",
            "E-mail: segramb.tirana@esteri.it per la Cancelleria.",
            "Mezzi di sussistenza di norma 20.000 THB in contanti per passeggero.",
            "Registrazione su https://tdac.immigration.go.th/arrival-card prima della partenza.",
        ],
    )
    def test_il_testo_non_viene_alterato(self, testo: str):
        pulito, _ = split_see_also(testo)
        assert pulito == testo


class TestRimandiMistiAContenuto:
    """Una frase che contiene un rimando ma anche una risposta non si butta via."""

    def test_conserva_il_contenuto_accanto_al_rimando(self):
        # Lituania: la risposta è "Passaporto oppure CIE"
        testo = (
            "Passaporto oppure CIE (https://www.viaggiaresicuri.it/approfondimenti-insights/"
            "documentidiviaggio): consultare la Sezione “Requisiti di Ingresso” di questa Scheda."
        )
        pulito, refs = split_see_also(testo)
        assert "Passaporto oppure CIE" in pulito
        assert refs == ["entry"]

    def test_conserva_la_risposta_anche_senza_spazio_dopo_il_punto(self):
        # Regno Unito: "Nessuna" è la risposta sulle vaccinazioni obbligatorie,
        # e la fonte scrive "Scheda.Per" attaccato
        testo = (
            "Nessuna: per informazioni sulle malattie presenti, consultare la Sezione "
            "“Situazione Sanitaria” di questa Scheda.Per ulteriori indicazioni si raccomanda "
            "di consultare il proprio medico."
        )
        pulito, refs = split_see_also(testo)
        assert pulito.startswith("Nessuna")
        assert "proprio medico" in pulito
        assert refs == ["health"]

    def test_sezione_sicurezza_aerea_non_e_la_sezione_sicurezza(self):
        # Aruba: è l'approfondimento curato con ENAC, una risorsa esterna
        testo = (
            'Si invita a consultare la Sezione "Sicurezza aerea" curata con ENAC, oltre al '
            "sito della Commissione Europea."
        )
        pulito, refs = split_see_also(testo)
        assert refs == []
        assert pulito == testo

    def test_rinvio_a_risorsa_esterna_resta_nel_testo(self):
        testo = "Viaggiatori con animali domestici: consultare il sito dell'Ambasciata a Brasilia."
        pulito, refs = split_see_also(testo)
        assert pulito == testo
        assert refs == []
