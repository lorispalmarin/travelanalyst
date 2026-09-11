"""Ingest e ricerca sugli approfondimenti tematici.

Tutto offline: la parte di ingest gira su un albero sintetico, quella di ricerca sull'indice
committato in `data/` e sui vettori delle query di prova salvati come fixture. Nessuna chiamata
di rete, nessuna credenziale: chi valuta il progetto clona ed esegue.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from viaggiaresicuri_mcp.approfondimenti import (
    DOCUMENTI,
    MAX_CARATTERI,
    QUERY_DI_PROVA,
    breadcrumb_di,
    cammina,
    carica_indice,
    chunk_del_documento,
    chunk_del_nodo,
    html_a_testo,
    radice,
    scarica_indice,
)
from viaggiaresicuri_mcp.errors import UnexpectedPayload

FIXTURES = Path(__file__).parent / "fixtures"


# Riproduce le forme che contano nella fonte: contenitori vuoti, tre livelli di annidamento,
# HTML con elenco, link ed entità.
ALBERO = {
    "saluteinviaggio": [
        {
            "id": "contenitore",
            "nome": "Malattie del viaggiatore",
            "contenuto": "",                       # nodo vuoto: niente chunk, ma si scende
            "sezioni": [
                {
                    "id": "dengue",
                    "nome": "Dengue",
                    "contenuto": "<p>La dengue &egrave; trasmessa da zanzare.</p>"
                                 '<ul><li>Usare repellenti</li><li>Zanzariere</li></ul>'
                                 '<p>Vedi <a href="https://www.salute.gov.it/x">Ministero</a>.</p>',
                    "sezioni": [
                        {
                            "id": "terzolivello",
                            "nome": "Dengue grave",
                            "contenuto": "<p>Richiede ricovero.</p>",
                            "sezioni": [],
                        }
                    ],
                },
                {"id": "vuoto", "nome": "Sezione senza testo", "contenuto": "   ", "sezioni": []},
            ],
        }
    ]
}


class TestWalk:
    def test_produce_un_nodo_per_ogni_contenuto(self):
        visti = list(cammina(radice(ALBERO, "saluteinviaggio")))
        assert [c[-1] for c, _ in visti] == ["Dengue", "Dengue grave"]

    def test_i_nodi_vuoti_non_generano_chunk_fantasma(self):
        """Un contenitore senza testo non è un chunk, ma non interrompe la discesa."""
        chunks = chunk_del_documento(ALBERO, "saluteinviaggio")
        assert all(c.testo.strip() for c in chunks)
        assert not any("Sezione senza testo" in c.breadcrumb for c in chunks)
        assert any("Dengue grave" in c.breadcrumb for c in chunks), "i figli si raggiungono comunque"

    def test_scende_fino_al_terzo_livello(self):
        chunks = chunk_del_documento(ALBERO, "saluteinviaggio")
        profondo = [c for c in chunks if c.breadcrumb.endswith("Dengue grave")][0]
        assert profondo.breadcrumb == (
            "Salute in viaggio > Malattie del viaggiatore > Dengue > Dengue grave"
        )

    def test_radice_inattesa_fallisce_invece_di_svuotarsi(self):
        with pytest.raises(UnexpectedPayload):
            radice({"altro": []}, "saluteinviaggio")


class TestBreadcrumb:
    def test_parte_dal_titolo_del_documento(self):
        assert breadcrumb_di("saluteinviaggio", ("Preparare un viaggio", "Consulto medico")) == (
            "Salute in viaggio > Preparare un viaggio > Consulto medico"
        )

    def test_non_ripete_il_titolo(self):
        """In `documentidiviaggio` il nodo di primo livello si chiama come il documento."""
        assert breadcrumb_di("documentidiviaggio", ("Documenti di viaggio", "Furto")) == (
            "Documenti di viaggio > Furto"
        )


class TestPuliziaHtml:
    def test_decodifica_le_entita(self):
        assert "è" in html_a_testo("<p>La dengue &egrave; una malattia.</p>")
        assert "’" in html_a_testo("<p>l&rsquo;estero</p>")

    def test_le_liste_diventano_elenchi_puntati(self):
        testo = html_a_testo("<ul><li>Cerotti</li><li>Termometro</li></ul>")
        assert "- Cerotti" in testo and "- Termometro" in testo

    def test_le_celle_restano_sulla_stessa_riga(self):
        """La fonte va a capo fra `</td>` e `<td>`: senza inglobarlo, ogni cella finirebbe sola."""
        testo = html_a_testo("<table><tbody><tr><td>Colera</td>\n<td>Orale</td></tr></tbody></table>")
        assert "Colera | Orale" in testo

    def test_toglie_i_tag_di_stile(self):
        assert html_a_testo('<p><span style="color:black"><strong>Testo</strong></span></p>') == "Testo"


class TestChunk:
    def test_il_breadcrumb_e_in_testa_e_gli_url_in_coda(self):
        chunk = chunk_del_nodo("saluteinviaggio", ("Malattie del viaggiatore", "Dengue"),
                               ALBERO["saluteinviaggio"][0]["sezioni"][0]["contenuto"])[0]
        assert chunk.testo.startswith("[Salute in viaggio > Malattie del viaggiatore > Dengue]\n")
        assert chunk.testo.rstrip().endswith("https://www.salute.gov.it/x")

    def test_un_nodo_lungo_si_spezza_ripetendo_il_breadcrumb(self):
        paragrafo = "<p>" + ("Testo di prova ripetuto. " * 40) + "</p>"
        pezzi = chunk_del_nodo("saluteinviaggio", ("A", "B"), paragrafo * 4)
        assert len(pezzi) > 1
        assert all(p.testo.startswith("[Salute in viaggio > A > B]\n") for p in pezzi)
        assert all(len(p.testo) <= MAX_CARATTERI * 1.3 for p in pezzi)

    def test_gli_id_sono_unici(self):
        chunks = chunk_del_documento(ALBERO, "saluteinviaggio")
        assert len({c.chunk_id for c in chunks}) == len(chunks)


@pytest.fixture(scope="module")
def indice():
    scarica_indice()
    yield carica_indice()
    scarica_indice()


@pytest.fixture(scope="module")
def query_di_prova() -> dict[str, np.ndarray]:
    """Vettori delle query salvati dall'ingest: provano il retrieval vero senza credenziali."""
    with np.load(FIXTURES / "query_prova.npz", allow_pickle=False) as archivio:
        return {str(q): v for q, v in zip(archivio["query"], archivio["vettori"])}


class TestIndiceCommittato:
    def test_copre_entrambi_i_documenti(self, indice):
        documenti = {c["documento"] for c in indice.chunks}
        assert documenti == set(DOCUMENTI)

    def test_nessun_chunk_vuoto_o_senza_citazione(self, indice):
        for chunk in indice.chunks:
            assert chunk["testo"].strip()
            assert chunk["breadcrumb"].strip()
            assert chunk["url"].startswith("https://www.viaggiaresicuri.it/approfondimenti/")

    def test_i_vettori_sono_normalizzati(self, indice):
        """A norma 1 il coseno è un prodotto scalare: è l'ipotesi su cui poggia `cerca`."""
        norme = np.linalg.norm(indice.matrice, axis=1)
        assert np.allclose(norme, 1.0, atol=1e-4)

    def test_le_query_di_prova_sono_quelle_dichiarate(self, query_di_prova):
        assert set(query_di_prova) == set(QUERY_DI_PROVA)


class TestRicerca:
    def test_dengue(self, indice, query_di_prova):
        primo = indice.cerca(query_di_prova["dengue"], top_k=3)[0]
        assert primo.breadcrumb.endswith("Dengue")
        assert primo.documento == "saluteinviaggio"

    def test_vaccinazioni_in_gravidanza(self, indice, query_di_prova):
        primo = indice.cerca(query_di_prova["vaccinazioni in gravidanza"], top_k=3)[0]
        assert primo.breadcrumb.endswith("Donne in gravidanza")

    def test_assicurazione_sanitaria(self, indice, query_di_prova):
        primo = indice.cerca(query_di_prova["assicurazione sanitaria per l'estero"], top_k=3)[0]
        assert primo.breadcrumb.endswith("Assicurazione sanitaria")

    def test_smarrimento_del_passaporto(self, indice, query_di_prova):
        """Qui il chunk giusto arriva **secondo**, non primo, ed è un limite misurato.

        In testa finisce "Restituzione di carte identità italiane rinvenute all'estero", che parla
        anch'esso di documenti persi all'estero: la somiglianza semantica non distingue fra
        smarrire e ritrovare. Lo prenderebbe un segnale lessicale — il titolo giusto contiene la
        parola "smarrimento" — cioè ricerca ibrida, fuori dallo scope dichiarato. Il test fissa il
        comportamento reale invece di allentare l'asserzione fino a farla passare.
        """
        primi = indice.cerca(query_di_prova["smarrimento del passaporto"], top_k=3)
        assert all(r.documento == "documentidiviaggio" for r in primi[:2])
        atteso = [r for r in primi if "Furto o smarrimento" in r.breadcrumb]
        assert atteso, "il chunk sul furto/smarrimento deve essere fra i primi tre"
        assert primi.index(atteso[0]) <= 1, "e non oltre la seconda posizione"

    def test_top_k_limita_i_risultati(self, indice, query_di_prova):
        assert len(indice.cerca(query_di_prova["dengue"], top_k=1)) == 1
        assert len(indice.cerca(query_di_prova["dengue"], top_k=200)) == len(indice)

    def test_i_punteggi_sono_decrescenti(self, indice, query_di_prova):
        punteggi = [r.score for r in indice.cerca(query_di_prova["dengue"], top_k=5)]
        assert punteggi == sorted(punteggi, reverse=True)
