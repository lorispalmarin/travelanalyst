from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    """THA ha 7 avvisi attivi, ALB nessuno: servono entrambi i casi."""
    return {iso: load_fixture(f"ultima_ora_{iso}.json") for iso in ("THA", "ALB")}


@pytest.fixture(scope="session")
def albania_payload() -> dict:
    """Scheda ricca: consolato distaccato, molti link, nessun campo vuoto rilevante."""
    return load_fixture("ALB.json")


@pytest.fixture(scope="session")
def austria_payload() -> dict:
    """Scheda con `Aree-di-particolare-cautela` vuoto: è il caso che attiva il fallback."""
    return load_fixture("AUT.json")


@pytest.fixture
def albania(albania_payload: dict) -> CountrySheet:
    return CountrySheet.model_validate(albania_payload)


@pytest.fixture
def austria(austria_payload: dict) -> CountrySheet:
    return CountrySheet.model_validate(austria_payload)
