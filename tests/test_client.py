"""Il livello di rete: qui si verificano i rami che dal vivo non si possono provocare."""

from __future__ import annotations

import httpx
import pytest

from viaggiaresicuri_mcp import client as http_module
from viaggiaresicuri_mcp.errors import SourceNotFound, SourceUnavailable, UnexpectedPayload


@pytest.fixture(autouse=True)
async def chiudi_client():
    yield
    await http_module.aclose()


def _installa(monkeypatch, handler) -> list[int]:
    """Sostituisce il client con uno su trasporto finto e conta i tentativi."""
    chiamate: list[int] = []

    def tracciante(request: httpx.Request) -> httpx.Response:
        chiamate.append(1)
        return handler(request)

    client = httpx.AsyncClient(
        base_url="https://esempio.test", transport=httpx.MockTransport(tracciante)
    )
    monkeypatch.setattr(http_module, "_client", client)
    monkeypatch.setattr(http_module, "BACKOFF_SECONDS", 0)
    return chiamate


async def test_risposta_valida(monkeypatch):
    _installa(monkeypatch, lambda r: httpx.Response(200, json={"ok": True}))
    assert await http_module.fetch_json("/x.json") == {"ok": True}


async def test_404_non_si_ritenta(monkeypatch):
    chiamate = _installa(monkeypatch, lambda r: httpx.Response(404))
    with pytest.raises(SourceNotFound):
        await http_module.fetch_json("/manca.json")
    assert len(chiamate) == 1


async def test_500_si_ritenta_e_poi_fallisce(monkeypatch):
    chiamate = _installa(monkeypatch, lambda r: httpx.Response(500))
    with pytest.raises(SourceUnavailable):
        await http_module.fetch_json("/x.json")
    assert len(chiamate) == http_module.MAX_ATTEMPTS


async def test_500_transitorio_viene_recuperato(monkeypatch):
    stato = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        stato["n"] += 1
        if stato["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    _installa(monkeypatch, handler)
    assert await http_module.fetch_json("/x.json") == {"ok": True}
    assert stato["n"] == 2


async def test_timeout_si_ritenta(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    chiamate = _installa(monkeypatch, handler)
    with pytest.raises(SourceUnavailable):
        await http_module.fetch_json("/x.json")
    assert len(chiamate) == http_module.MAX_ATTEMPTS


async def test_json_malformato_non_si_ritenta(monkeypatch):
    chiamate = _installa(monkeypatch, lambda r: httpx.Response(200, text="<html>errore</html>"))
    with pytest.raises(UnexpectedPayload):
        await http_module.fetch_json("/x.json")
    assert len(chiamate) == 1


async def test_403_non_si_ritenta(monkeypatch):
    chiamate = _installa(monkeypatch, lambda r: httpx.Response(403))
    with pytest.raises(SourceUnavailable):
        await http_module.fetch_json("/x.json")
    assert len(chiamate) == 1
