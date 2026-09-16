"""Guide generali: validazione, appiattimento, sommario e lettura della sezione. Offline."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from viaggiaresicuri_mcp.client import Fetched
from viaggiaresicuri_mcp.errors import UnexpectedPayload, UnknownTopic
from viaggiaresicuri_mcp.general_info import (
    build_sections,
    flatten,
    guide_index,
    guide_section,
    load_guides,
    parse_guide,
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
            build_sections({"preparaunviaggio": vuota})


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
        sezioni = build_sections(guide_payloads)
        assert len(sezioni) == 7
        assert len({s.id for s in sezioni}) == 7
        assert sum(s.id.startswith("documentidiviaggio/") for s in sezioni) == 4


class TestSommarioELettura:
    def test_il_sommario_ha_una_voce_per_sezione(self, guide_payloads):
        sezioni = build_sections(guide_payloads)
        voci = guide_index(sezioni)
        assert [v.id for v in voci] == [s.id for s in sezioni]
        assert all(v.chars == len(s.text) for v, s in zip(voci, sezioni))

    def test_la_sezione_si_prende_per_id(self, guide_payloads):
        sezioni = build_sections(guide_payloads)
        scelta = guide_section(sezioni, "documentidiviaggio/furtosmarrimentodidocumenti")
        assert "Documento di viaggio provvisorio" in scelta.text

    def test_un_id_inesistente_elenca_quelli_validi(self, guide_payloads):
        """Una risposta vuota verrebbe letta come "la fonte non pubblica niente su questo tema"."""
        with pytest.raises(UnknownTopic) as exc:
            guide_section(build_sections(guide_payloads), "documentidiviaggio/inventato")
        assert "preparaunviaggio/saluteinviaggio" in str(exc.value)


async def test_basta_una_guida_da_copia_locale_per_dichiarare_la_risposta_stale(monkeypatch, guide_payloads):
    adesso = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

    async def finto_fetch(path: str, ttl_seconds: int | None = None) -> Fetched:
        nome = path.rsplit("/", 1)[-1].removesuffix(".json")
        if nome == "documentidiviaggio":
            return Fetched(guide_payloads[nome], adesso, "stale", 30000)
        return Fetched(guide_payloads[nome], adesso, "fresh", 0)

    monkeypatch.setattr("viaggiaresicuri_mcp.general_info.fetch", finto_fetch)
    sezioni, meta = await load_guides()
    assert len(sezioni) == 7
    assert meta.cache_status == "stale"
    assert meta.age_seconds == 30000
