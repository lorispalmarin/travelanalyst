"""Il progetto deve funzionare anche installato, non solo in editabile.

Questi test nascono da due guasti trovati costruendo l'immagine Docker, entrambi invisibili in
sviluppo: l'assistente cercava `server.py` accanto al pacchetto, e la pagina della UI e l'indice
semantico non erano dichiarati come package data. Con `pip install -e` tutti e due i percorsi
esistono per caso, perché il pacchetto sta nella radice del progetto; con un'installazione
normale no.

Non si costruisce una wheel: si verifica che nessun percorso risalga fuori dal pacchetto e che
`pyproject.toml` dichiari i file non-Python.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import assistant
import viaggiaresicuri_mcp
from assistant.config import SERVER_MODULE
from assistant.web import PAGINA
from viaggiaresicuri_mcp.approfondimenti import INDICE, VETTORI

PACCHETTO_MCP = Path(viaggiaresicuri_mcp.__file__).resolve().parent
PACCHETTO_ASSISTENTE = Path(assistant.__file__).resolve().parent
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


class TestAssetDentroIlPacchetto:
    def test_lindice_semantico_e_un_asset_del_pacchetto(self):
        for percorso in (INDICE, VETTORI):
            assert percorso.resolve().is_relative_to(PACCHETTO_MCP), (
                f"{percorso} sta fuori dal pacchetto: installato in site-packages non ci sarebbe"
            )

    def test_la_pagina_della_ui_e_un_asset_del_pacchetto(self):
        assert PAGINA.resolve().is_relative_to(PACCHETTO_ASSISTENTE)

    def test_gli_asset_esistono_davvero(self):
        for percorso in (INDICE, VETTORI, PAGINA):
            assert percorso.exists(), f"manca {percorso}"


class TestDichiarazioniDiPyproject:
    def test_i_file_non_python_sono_dichiarati(self):
        """Senza `package-data` un'installazione porta solo i .py, e il guasto si vede in container."""
        dati = tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]["package-data"]
        assert any("static" in schema for schema in dati["assistant"])
        assert any("data" in schema for schema in dati["viaggiaresicuri_mcp"])

    def test_pytest_e_configurato_in_un_posto_solo(self):
        """La configurazione stava anche in pytest.ini: due file che possono divergere."""
        dati = tomllib.loads(PYPROJECT.read_text())
        assert "ini_options" in dati["tool"]["pytest"]
        assert not (PYPROJECT.parent / "pytest.ini").exists()


class TestAvvioDelServer:
    def test_il_server_mcp_si_avvia_come_modulo(self):
        """Non come percorso a un file: un percorso da `__file__` vale solo in editabile."""
        assert SERVER_MODULE == "viaggiaresicuri_mcp.server"

    def test_il_modulo_dichiara_un_entry_point_eseguibile(self):
        from viaggiaresicuri_mcp import server

        assert callable(server.main)
