"""Guide generali: validazione, appiattimento, parole e indice. Offline, senza rete."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from viaggiaresicuri_mcp.client import Fetched
from viaggiaresicuri_mcp.errors import UnexpectedPayload
from viaggiaresicuri_mcp.general_info import (
    FullTextIndex,
    build_index,
    flatten,
    parse_guide,
    search_guides,
    tokenize,
)
from viaggiaresicuri_mcp.models import GuideSection

PREPARA = {
    "preparaunviaggio": [
        {
            "id": "preparaunviaggio",
            "nome": "Preparare un viaggio",
            "contenuto": "",
            "sezioni": [
                {
                    "id": "saluteinviaggio",
                    "nome": "Salute in viaggio",
                    "contenuto": "<p>Il consulto medico &egrave; consigliato prima di partire.</p>"
                    '<p>Vedi <a href="https://www.salute.gov.it/malattie">Ministero</a>.</p>',
                },
                {"id": "vuota", "nome": "Sezione senza testo", "contenuto": " "},
            ],
        },
        {
            "id": "assicurazionediviaggio",
            "nome": "Assicurazione di viaggio e sanitaria",
            "contenuto": "<p>Il massimale deve coprire il rimpatrio <s>p</s>sanitario.</p>",
        },
    ]
}

DOCUMENTI = {
    "documentidiviaggio": [
        {
            "id": "documentidiviaggio",
            "nome": "Documenti di viaggio",
            "contenuto": "",
            "sezioni": [{"id": "furto", "nome": "Furto o smarrimento", "contenuto": "<p>Denuncia.</p>"}],
        }
    ]
}


def _sezioni(payload: dict, nome: str) -> list[GuideSection]:
    return flatten(nome, parse_guide(payload, nome))


def _sezione(id: str, titolo: str, testo: str) -> GuideSection:
    return GuideSection(id=id, breadcrumb=titolo, title=titolo, text=testo, page="https://esempio")


class TestValidazione:
    def test_radice_inattesa_fallisce_invece_di_svuotarsi(self):
        with pytest.raises(UnexpectedPayload):
            parse_guide({"altro": []}, "preparaunviaggio")
        with pytest.raises(UnexpectedPayload):
            parse_guide({"preparaunviaggio": []}, "preparaunviaggio")

    def test_un_nodo_senza_nome_fallisce(self):
        with pytest.raises(UnexpectedPayload):
            parse_guide({"preparaunviaggio": [{"id": "x", "contenuto": "<p>t</p>"}]}, "preparaunviaggio")

    def test_una_guida_senza_testo_e_un_errore(self):
        vuota = {"preparaunviaggio": [{"id": "c", "nome": "Contenitore", "contenuto": ""}]}
        with pytest.raises(UnexpectedPayload):
            build_index({"preparaunviaggio": vuota})


class TestAppiattimento:
    def test_i_contenitori_si_attraversano_ma_non_sono_sezioni(self):
        assert [s.id for s in _sezioni(PREPARA, "preparaunviaggio")] == [
            "preparaunviaggio/saluteinviaggio",
            "preparaunviaggio/assicurazionediviaggio",
        ]

    def test_il_breadcrumb_parte_dal_titolo_della_guida(self):
        salute = _sezioni(PREPARA, "preparaunviaggio")[0]
        assert salute.breadcrumb == "Preparare un viaggio > Salute in viaggio"
        assert salute.page.endswith("/approfondimenti-insights/preparaunviaggio")

    def test_non_ripete_il_titolo_della_guida(self):
        [furto] = _sezioni(DOCUMENTI, "documentidiviaggio")
        assert furto.breadcrumb == "Documenti di viaggio > Furto o smarrimento"

    def test_il_testo_barrato_e_una_correzione_e_si_scarta(self):
        assicurazione = _sezioni(PREPARA, "preparaunviaggio")[1]
        assert "il rimpatrio sanitario" in assicurazione.text

    def test_i_link_restano_anche_senza_tag(self):
        salute = _sezioni(PREPARA, "preparaunviaggio")[0]
        assert "<" not in salute.text and "è consigliato" in salute.text
        assert [link.url for link in salute.links] == ["https://www.salute.gov.it/malattie"]

    def test_le_guide_registrate(self, guide_payloads):
        sezioni = build_index(guide_payloads).sezioni
        assert len(sezioni) == 7
        assert len({s.id for s in sezioni}) == 7
        assert sum(s.id.startswith("documentidiviaggio/") for s in sezioni) == 4


class TestParole:
    def test_minuscole_accenti_e_parole_vuote(self):
        assert tokenize("Che cos'è la Febbre Gialla?") == tokenize("febbre gialla")

    def test_singolare_e_plurale_sulla_stessa_radice(self):
        for singolare, plurale in [("passaporto", "passaporti"), ("certificato", "certificati"), ("viaggio", "viaggi")]:
            assert tokenize(singolare) == tokenize(plurale)

    def test_l_apostrofo_separa_le_parole(self):
        assert tokenize("dell’estero") == tokenize("estero")


class TestIndice:
    def test_anche_il_titolo_e_indicizzato(self):
        indice = FullTextIndex([
            _sezione("g/pacchetti", "Pacchetti turistici", "Il recesso è disciplinato dal Codice."),
            _sezione("g/documenti", "Documenti di viaggio", "Il passaporto deve essere valido."),
        ])
        assert [h.id for h in indice.search("pacchetti", 2)] == ["g/pacchetti"]

    def test_senza_parole_in_comune_nessun_risultato(self, guide_payloads):
        assert build_index(guide_payloads).search("criptovalute", 3) == []

    def test_top_k_e_punteggi_decrescenti(self, guide_payloads):
        risultati = build_index(guide_payloads).search("viaggio", 5)
        assert len(risultati) == 5
        assert [r.score for r in risultati] == sorted((r.score for r in risultati), reverse=True)


async def test_basta_una_guida_da_copia_locale_per_dichiarare_la_risposta_stale(monkeypatch, guide_payloads):
    adesso = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    async def finto_fetch(path: str, ttl_seconds: int | None = None) -> Fetched:
        nome = path.rsplit("/", 1)[-1].removesuffix(".json")
        if nome == "documentidiviaggio":
            return Fetched(guide_payloads[nome], adesso, "stale", 30000)
        return Fetched(guide_payloads[nome], adesso, "fresh", 0)

    monkeypatch.setattr("viaggiaresicuri_mcp.general_info.fetch", finto_fetch)
    _, meta = await search_guides("passaporto")
    assert meta.cache_status == "stale"
    assert meta.age_seconds == 30000
