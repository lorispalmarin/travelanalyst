"""Adapter MCP 1 nell'assistente e server MCP 2 in processi separati, senza fonte/LLM."""

import asyncio
import json
import os
import socket
from dataclasses import replace
from pathlib import Path

from assistant.agent import _avviso_di_copia_locale, _testo_di
from assistant.config import carica
from assistant.mcp_tools import tool_del_server

ROOT = Path(__file__).resolve().parent.parent
SERVER = r'''
import json, socket, sys
from datetime import UTC, datetime
from pathlib import Path
import uvicorn
from viaggiaresicuri_mcp import countries, server
from viaggiaresicuri_mcp.models import CountrySheet, Meta
fixtures = Path("tests/fixtures")
countries._index = countries.CountryIndex(json.loads((fixtures / "lista_nazioni.json").read_text()))
async def load(country):
    ref = await server._resolve(country)
    sheet = CountrySheet.model_validate(json.loads((fixtures / "ALB.json").read_text()))
    sheet.meta = Meta(retrieved_at=datetime.now(UTC), cache_status="stale", age_seconds=30000)
    return ref, sheet
server._load = load
sock = socket.socket(fileno=int(sys.argv[1]))
uvicorn.Server(uvicorn.Config(server.mcp.http_app(path="/mcp"), log_level="error")).run(sockets=[sock])
'''


async def test_adapter_http_errori_freschezza_e_riconnessione(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-no-model-call")
    executable = os.getenv("MCP_TEST_SERVER_PYTHON", str(ROOT / ".venv/bin/python"))
    with socket.socket() as sock, (tmp_path / "server.log").open("w+") as log:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        process = await asyncio.create_subprocess_exec(
            executable, "-c", SERVER, str(sock.fileno()),
            pass_fds=(sock.fileno(),), cwd=ROOT, stdout=log, stderr=log,
        )
        try:
            import httpx
            async with asyncio.timeout(15), httpx.AsyncClient() as http:
                while True:
                    assert process.returncode is None, "Il server di test non si è avviato"
                    try:
                        await http.get(f"http://127.0.0.1:{port}/mcp", timeout=0.2)
                        break
                    except httpx.TransportError:
                        await asyncio.sleep(0.05)
            settings = replace(carica(), mcp_server_url=f"http://127.0.0.1:{port}/mcp")
            for _ in range(2):
                async with tool_del_server(settings) as tools:
                    find = next(t for t in tools if t.name == "find_country")
                    assert "query" in find.args
                    result = await find.ainvoke({"type": "tool_call", "id": "ok", "name": find.name, "args": {"query": "THA"}})
                    assert json.loads(_testo_di(result))["match"]["iso3"] == "THA"
                    error = await find.ainvoke({"type": "tool_call", "id": "err", "name": find.name, "args": {"query": "zzzzzz"}})
                    assert error.status == "error"
                    assert "Nessun Paese" in _testo_di(error)
                    health = next(t for t in tools if t.name == "get_health_info")
                    stale = await health.ainvoke({"type": "tool_call", "id": "stale", "name": health.name, "args": {"country": "THA"}})
                    assert stale.status == "success", _testo_di(stale)
                    assert _avviso_di_copia_locale([stale]) is not None
                assert process.returncode is None
        finally:
            if process.returncode is None:
                process.terminate()
            await asyncio.wait_for(process.wait(), timeout=10)
            log.seek(0)
            # Il log viene mostrato da pytest soltanto in caso di fallimento.
            print(log.read())
