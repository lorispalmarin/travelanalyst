from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# La cache è spenta per default nei test, e va accesa esplicitamente da chi la sta verificando
# (tests/test_cache.py). Serve prima degli import del package, perché config.py legge l'ambiente
# al caricamento. Senza, ogni suite lascerebbe entry su disco e un test scritto per il caso
# "la fonte non risponde" verrebbe salvato da una copia lasciata lì dal test precedente.
os.environ.setdefault("VS_CACHE_ENABLED", "false")

from viaggiaresicuri_mcp.countries import CountryIndex
from viaggiaresicuri_mcp.models import CountrySheet

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def country_records() -> list[dict]:
    """Tutti i 222 paesi della fonte, senza coordinate."""
    return load_fixture("lista_nazioni.json")


@pytest.fixture(scope="session")
def index(country_records: list[dict]) -> CountryIndex:
    return CountryIndex(country_records)


@pytest.fixture(scope="session")
def alerts_payloads() -> dict[str, dict]:
    """Quattro comportamenti diversi registrati dalla fonte reale:

    ALB entrambi gli array vuoti, UKR e ISR un avviso di sicurezza a testa, THA sette avvisi su
    due categorie. Sono i casi su cui poggiano i tre stati di `get_allerte`.
    """
    return {iso: load_fixture(f"ultima_ora_{iso}.json") for iso in ("THA", "ALB", "UKR", "ISR")}


@pytest.fixture(scope="session")
def albania_payload() -> dict:
    """Scheda ricca: consolato distaccato, molti link, nessun campo vuoto rilevante."""
    return load_fixture("ALB.json")


@pytest.fixture(scope="session")
def austria_payload() -> dict:
    """Scheda con `Aree-di-particolare-cautela` vuoto: è il caso che attiva il fallback."""
    return load_fixture("AUT.json")


@pytest.fixture(scope="session")
def guide_payloads() -> dict[str, dict]:
    """Le due guide generali, registrate dalla fonte il 16 settembre 2026."""
    return {
        nome: load_fixture(f"approfondimenti_{nome}.json")
        for nome in ("preparaunviaggio", "documentidiviaggio")
    }


@pytest.fixture
def albania(albania_payload: dict) -> CountrySheet:
    return CountrySheet.model_validate(albania_payload)


@pytest.fixture
def austria(austria_payload: dict) -> CountrySheet:
    return CountrySheet.model_validate(austria_payload)


# Server e assistente usano versioni diverse dell'SDK MCP, in ambienti separati.
from importlib.util import find_spec

collect_ignore = []
if find_spec("langchain_mcp_adapters") is None:
    collect_ignore += ["test_assistant.py", "test_assistant_eval.py", "test_mcp_http.py"]
if find_spec("fastmcp") is None:
    collect_ignore += ["test_server.py", "test_cache.py"]
