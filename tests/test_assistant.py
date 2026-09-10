"""Assistente: quello che si può verificare senza chiamare il modello."""

from __future__ import annotations

import pytest

from assistant import prompts
from assistant.config import ConfigurazioneMancante, Settings, carica
from assistant.mcp_tools import _costruisci_tool, _testo_del_risultato


class TestConfigurazione:
    def test_manca_la_chiave(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "")
        with pytest.raises(ConfigurazioneMancante) as exc:
            carica()
        assert ".env" in str(exc.value), "il messaggio deve dire come rimediare"

    def test_default_sul_modello_della_traccia(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        assert carica().model == "gpt-5.6-luna"

    def test_endpoint_azure_si_imposta_da_ambiente(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://esempio.azure.com/openai/v1/")
        settings = carica()
        assert settings.base_url == "https://esempio.azure.com/openai/v1/"
        assert "esempio.azure.com" in settings.descrizione

    def test_responses_api_attiva_per_default(self, monkeypatch):
        """gpt-5.6-luna con reasoning attivo accetta i tool solo dalla Responses API."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("OPENAI_USE_RESPONSES_API", raising=False)
        assert carica().use_responses_api is True


class TestSystemPrompt:
    """Il prompt è codice: le regole che ci mettiamo devono restarci."""

    def test_vieta_di_rispondere_a_memoria(self):
        assert "esclusivamente" in prompts.SYSTEM_PROMPT.lower()

    def test_contiene_la_regola_sul_campo_vuoto(self):
        testo = prompts.SYSTEM_PROMPT.lower()
        assert "not_published" in testo
        assert "nessun rischio" in testo

    def test_chiede_di_dichiarare_il_riassunto(self):
        assert "provenance" in prompts.SYSTEM_PROMPT

    def test_chiede_fonte_e_data(self):
        assert "updated_at" in prompts.SYSTEM_PROMPT

    def test_vieta_pareri_legali_e_sanitari(self):
        assert "legali" in prompts.SYSTEM_PROMPT and "sanitari" in prompts.SYSTEM_PROMPT

    def test_dice_di_non_alterare_numeri_e_url(self):
        testo = prompts.SYSTEM_PROMPT.lower()
        assert "non alterare" in testo and "url" in testo

    def test_indirizza_le_domande_sul_presente_alle_allerte(self):
        assert "get_recent_alerts" in prompts.SYSTEM_PROMPT

    def test_dice_dove_stanno_le_normative_locali(self):
        assert "local_laws" in prompts.SYSTEM_PROMPT


class _AgenteFinto:
    """Riproduce la forma dello stream di LangGraph, senza modello né rete."""

    def __init__(self, eventi):
        self._eventi = eventi

    async def astream(self, _input, config=None, stream_mode=None):
        for evento in self._eventi:
            yield evento


class TestTracciaEventi:
    async def _traccia(self, eventi):
        from langchain_core.messages import AIMessage, ToolMessage

        from assistant.agent import Assistente
        from assistant.config import Settings

        settings = Settings(
            api_key="x", model="m", base_url=None, use_responses_api=True,
            reasoning_effort=None, reasoning_summary="auto", python_executable="python",
            server_script=__import__("pathlib").Path("server.py"), max_steps=4,
        )
        assistente = Assistente(_AgenteFinto(eventi), [], settings)
        return [e async for e in assistente.traccia("domanda")]

    async def test_estrae_ragionamento_chiamate_e_risultati(self):
        from langchain_core.messages import AIMessage, ToolMessage

        ragionante = AIMessage(
            content=[
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Cerco il Paese"}]},
                {"type": "function_call"},
            ],
            tool_calls=[{"name": "find_country", "args": {"query": "Albania"}, "id": "1", "type": "tool_call"}],
        )
        risultato = ToolMessage(content='{"iso3": "ALB"}', name="find_country", tool_call_id="1")
        eventi = [
            ("updates", {"model": {"messages": [ragionante]}}),
            ("updates", {"tools": {"messages": [risultato]}}),
            ("messages", (AIMessage(content=[{"type": "text", "text": "Ecco"}]), {})),
        ]
        tracciato = await self._traccia(eventi)
        tipi = [e["tipo"] for e in tracciato]
        assert tipi == ["ragionamento", "tool_call", "tool_result", "testo", "fine"]
        assert tracciato[0]["testo"] == "Cerco il Paese"
        assert tracciato[1]["argomenti"] == {"query": "Albania"}
        assert tracciato[2]["caratteri"] == len('{"iso3": "ALB"}')
        assert tracciato[2]["errore"] is False
        assert tracciato[3]["delta"] == "Ecco"

    async def test_segnala_i_risultati_in_errore(self):
        from langchain_core.messages import ToolMessage

        errore = ToolMessage(
            content="ERRORE DEL TOOL: [ambiguous_country] …", name="get_health_info", tool_call_id="1"
        )
        tracciato = await self._traccia([("updates", {"tools": {"messages": [errore]}})])
        assert tracciato[0]["tipo"] == "tool_result"
        assert tracciato[0]["errore"] is True


class _Blocco:
    def __init__(self, text: str) -> None:
        self.text = text


class _Risultato:
    def __init__(self, testo: str, errore: bool = False) -> None:
        self.content = [_Blocco(testo)]
        self.is_error = errore
        self.data = None


class _Spec:
    name = "get_health_info"
    description = "Situazione sanitaria"
    input_schema = {"type": "object", "properties": {"country": {"type": "string"}}, "required": ["country"]}
    inputSchema = input_schema


class _ClientFinto:
    def __init__(self, risultato: _Risultato) -> None:
        self.risultato = risultato
        self.chiamate: list[tuple[str, dict]] = []

    async def call_tool(self, nome, argomenti, **kwargs):
        self.chiamate.append((nome, argomenti))
        return self.risultato


class TestPonteMCP:
    def test_estrae_il_testo_dai_blocchi(self):
        assert _testo_del_risultato(_Risultato("contenuto")) == "contenuto"

    def test_il_tool_riporta_nome_descrizione_e_schema(self):
        tool = _costruisci_tool(_ClientFinto(_Risultato("ok")), _Spec())
        assert tool.name == "get_health_info"
        assert tool.description == "Situazione sanitaria"
        assert tool.args_schema["properties"]["country"]["type"] == "string"

    async def test_inoltra_gli_argomenti_al_server(self):
        client = _ClientFinto(_Risultato("ok"))
        tool = _costruisci_tool(client, _Spec())
        await tool.ainvoke({"country": "Albania"})
        assert client.chiamate == [("get_health_info", {"country": "Albania"})]

    async def test_un_errore_del_tool_torna_al_modello_come_testo(self):
        """Se il Paese è ambiguo il modello deve poterlo leggere e chiedere, non schiantarsi."""
        errore = _Risultato("[ambiguous_country] 'corea' è ambiguo. Candidati: …", errore=True)
        tool = _costruisci_tool(_ClientFinto(errore), _Spec())
        risposta = await tool.ainvoke({"country": "corea"})
        assert risposta.startswith("ERRORE DEL TOOL")
        assert "ambiguous_country" in risposta
