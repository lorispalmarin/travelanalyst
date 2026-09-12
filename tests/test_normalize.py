from __future__ import annotations

import pytest

from viaggiaresicuri_mcp.normalize import (
    extract_links,
    html_to_text,
    link_kind,
    find_see_also,
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


class TestSeeAlso:
    """I rimandi si estraggono, non si rimuovono: il testo resta quello della fonte."""

    def test_estrae_il_rimando_lasciando_il_testo_intatto(self):
        testo = (
            "Si raccomanda di adottare le normali precauzioni. "
            "Per maggiori informazioni, consultare la Sezione “Sicurezza” di questa Scheda."
        )
        assert find_see_also(testo) == ["security"]

    def test_riconosce_piu_sezioni(self):
        testo = "Consultare la sezione Situazione Sanitaria e la sezione Requisiti di ingresso di questa Scheda."
        assert set(find_see_also(testo)) == {"health", "entry"}

    def test_nessun_rimando_nessun_riferimento(self):
        assert find_see_also("Si raccomanda di consultare il proprio medico prima della partenza.") == []

    def test_un_nodo_fatto_solo_di_rimando_resta_comunque_compilato(self):
        """Gabon: la fonte dice solo "consultare la Sezione Requisiti di Ingresso".

        Il nodo resta `available` con quel testo e un `see_also` che dice all'agente dove
        andare. Prima diventava vuoto, cioè si buttava l'unica cosa che la fonte aveva scritto.
        """
        testo = 'Consultare la Sezione "Requisiti di Ingresso" di questa Scheda.'
        assert find_see_also(testo) == ["entry"]

    def test_testo_vuoto(self):
        assert find_see_also("") == []

    def test_sezione_sicurezza_aerea_non_e_la_sezione_sicurezza(self):
        # Aruba: è l'approfondimento curato con ENAC, una risorsa esterna
        testo = (
            'Si invita a consultare la Sezione "Sicurezza aerea" curata con ENAC, oltre al '
            "sito della Commissione Europea."
        )
        assert find_see_also(testo) == []

    def test_rinvio_a_risorsa_esterna_non_e_un_see_also(self):
        testo = "Viaggiatori con animali domestici: consultare il sito dell'Ambasciata a Brasilia."
        assert find_see_also(testo) == []


class TestIntegritaDelTesto:
    """Il testo della fonte arriva all'operatore come è scritto, HTML a parte."""

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
        assert html_to_text(f"<p>{testo}</p>") == testo


class TestRimandiMistiAContenuto:
    """Una frase che contiene un rimando porta spesso anche la risposta: sta tutto nel testo."""

    def test_il_contenuto_accanto_al_rimando_resta_e_il_riferimento_si_estrae(self):
        # Lituania: la risposta è "Passaporto oppure CIE"
        testo = (
            "Passaporto oppure CIE (https://www.viaggiaresicuri.it/approfondimenti-insights/"
            "documentidiviaggio): consultare la Sezione “Requisiti di Ingresso” di questa Scheda."
        )
        assert find_see_also(testo) == ["entry"]
        assert html_to_text(f"<p>{testo}</p>") == testo

    def test_riconosce_il_rimando_anche_senza_spazio_dopo_il_punto(self):
        # Regno Unito: la fonte scrive "Scheda.Per" attaccato
        testo = (
            "Nessuna: per informazioni sulle malattie presenti, consultare la Sezione "
            "“Situazione Sanitaria” di questa Scheda.Per ulteriori indicazioni si raccomanda "
            "di consultare il proprio medico."
        )
        assert find_see_also(testo) == ["health"]
