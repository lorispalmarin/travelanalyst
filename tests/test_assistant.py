"""Assistente: quello che si può verificare senza chiamare il modello."""

from __future__ import annotations

import json
import time

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
        assert "get_allerte" in prompts.SYSTEM_PROMPT

    def test_gli_avvisi_in_corso_aprono_la_risposta(self):
        """Dove vanno gli avvisi quando ci sono: è il cuore della sezione, deve restare."""
        testo = prompts.SYSTEM_PROMPT
        assert "in testa alla risposta" in testo
        assert "Una volta per Paese" in testo, "una sola chiamata per Paese, non una per turno"

    def test_il_controllo_delle_allerte_e_una_scelta_con_due_rami(self):
        """Non più un riflesso a ogni turno: il prompt deve dire quando sì e quando no."""
        testo = prompts.SYSTEM_PROMPT
        assert "**Chiamalo**" in testo and "**Non chiamarlo**" in testo
        assert "non per abitudine" in testo

    def test_nomina_tutti_e_tre_gli_stati_degli_avvisi(self):
        testo = prompts.SYSTEM_PROMPT
        for stato in ("avvisi_presenti", "nessun_avviso_pubblicato", "non_verificabile"):
            assert stato in testo

    def test_vieta_di_leggere_l_assenza_di_avvisi_come_sicurezza(self):
        testo = prompts.SYSTEM_PROMPT
        assert "mai" in testo and "rassicurazione" in testo
        assert "non affermare l'assenza" in testo

    def test_dice_dove_stanno_le_normative_locali(self):
        assert "local_laws" in prompts.SYSTEM_PROMPT

    def test_separa_la_ricerca_generale_dai_tool_paese(self):
        testo = prompts.SYSTEM_PROMPT
        assert "search_approfondimenti" in testo
        assert "non nominano un Paese" in testo
        assert "breadcrumb" in testo


class _AgenteFinto:
    """Riproduce la forma dello stream di LangGraph, senza modello né rete."""

    def __init__(self, eventi, messaggi=None):
        self._eventi = eventi
        self._messaggi = messaggi or []

    async def astream(self, _input, config=None, stream_mode=None):
        for evento in self._eventi:
            yield evento

    async def ainvoke(self, _input, config=None):
        return {"messages": self._messaggi}


class TestTracciaEventi:
    async def _assistente(self, eventi, messaggi=None):
        from assistant.agent import Assistente
        from assistant.config import Settings

        settings = Settings(
            api_key="x", model="m", base_url=None, use_responses_api=True,
            reasoning_effort=None, reasoning_summary="auto", python_executable="python",
            server_script=__import__("pathlib").Path("server.py"), max_steps=4,
        )
        return Assistente(_AgenteFinto(eventi, messaggi), [], settings)

    async def _traccia(self, eventi):
        assistente = await self._assistente(eventi)
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


# ---------------------------------------------------------------------------
# La cache non deve essere silenziosa nemmeno lato assistente.

RISPOSTA_STALE = {
    "country": {"name": "Albania", "iso3": "ALB", "iso2": "AL"},
    "topic": "Requisiti di ingresso",
    "data": [],
    "updated_at": "2026-07-30T22:00:00Z",
    "meta": {
        "last_updated": "2026-07-30T22:00:00+00:00",
        "retrieved_at": "2026-09-10T08:30:00+00:00",
        "cache_status": "stale",
        "age_seconds": 30600,
    },
}


@pytest.fixture
def fuso_di_roma(monkeypatch):
    """L'assistente è per operatori italiani: le date si guardano da lì, non dal fuso della CI."""
    monkeypatch.setenv("TZ", "Europe/Rome")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class TestFreschezza:
    def test_riconosce_una_risposta_da_copia_locale(self):
        from assistant.freshness import estrai

        freschezza = estrai(json.dumps(RISPOSTA_STALE))
        assert freschezza is not None
        assert freschezza.age_seconds == 30600
        assert freschezza.last_updated is not None

    def test_una_risposta_fresca_non_produce_avvisi(self):
        from assistant.freshness import estrai

        fresca = json.loads(json.dumps(RISPOSTA_STALE))
        fresca["meta"]["cache_status"] = "fresh"
        assert estrai(json.dumps(fresca)) is None

    def test_un_errore_del_tool_non_fa_saltare_il_turno(self):
        from assistant.freshness import estrai

        assert estrai("ERRORE DEL TOOL: [ambiguous_country] …") is None

    def test_una_risposta_senza_meta_non_produce_avvisi(self):
        from assistant.freshness import estrai

        assert estrai(json.dumps({"data": []})) is None

    def test_l_avviso_dice_quando_e_quanto_vecchia(self, fuso_di_roma):
        """Le date si mostrano nel fuso di chi legge, non in UTC.

        Non è un dettaglio cosmetico: la fonte pubblica `updateDate` come `2026-07-30T22:00:00Z`,
        che è la mezzanotte del 31 luglio a Roma. Renderizzata in UTC diventerebbe "30/07",
        un giorno prima di quello che l'operatore vede sul sito.
        """
        from assistant.freshness import avviso, estrai

        testo = avviso(estrai(json.dumps(RISPOSTA_STALE)))
        assert "non è raggiungibile" in testo
        assert "10/09/2026 alle 10:30" in testo, "quando abbiamo scaricato, ora italiana"
        assert "8 ore" in testo, "l'età della copia, in parole"
        assert "31/07/2026" in testo, "la data dichiarata dalla fonte, come si legge sul sito"
        assert "viaggiaresicuri.it" in testo

    @pytest.mark.parametrize("secondi,atteso", [
        (6, "meno di un minuto"),
        (90, "un minuto"),
        (3600, "un'ora"),
        (30600, "8 ore"),
        (86400, "un giorno"),
        (400000, "4 giorni"),
    ])
    def test_l_eta_si_legge_in_parole(self, secondi, atteso):
        from assistant.freshness import _durata

        assert _durata(secondi) == atteso

    def test_sotto_il_minuto_niente_circa(self):
        """"circa meno di un minuto" è un'approssimazione di un'approssimazione."""
        from assistant.freshness import _eta

        assert _eta(6) == "meno di un minuto fa"
        assert _eta(30600) == "circa 8 ore fa"

    def test_senza_data_della_fonte_la_frase_si_accorcia(self):
        """Gli avvisi di un Paese senza allerte non hanno una data da dichiarare."""
        from assistant.freshness import avviso, estrai

        senza = json.loads(json.dumps(RISPOSTA_STALE))
        senza["meta"]["last_updated"] = None
        testo = avviso(estrai(json.dumps(senza)))
        assert "Farnesina" not in testo
        assert testo.endswith("prima della partenza.")


class TestAvvisoNelTurno(TestTracciaEventi):
    """L'avviso è anteposto dal codice: non dipende dal fatto che il modello lo scriva."""

    async def test_arriva_prima_del_testo_della_risposta(self):
        from langchain_core.messages import AIMessage, ToolMessage

        eventi = [
            ("updates", {"tools": {"messages": [
                ToolMessage(content=json.dumps(RISPOSTA_STALE), name="get_entry_requirements",
                            tool_call_id="1")
            ]}}),
            ("messages", (AIMessage(content=[{"type": "text", "text": "Per l'Albania"}]), {})),
        ]
        tracciato = await self._traccia(eventi)
        tipi = [e["tipo"] for e in tracciato]
        assert tipi == ["tool_result", "avviso", "testo", "fine"]
        assert "non è raggiungibile" in tracciato[1]["testo"]

    async def test_non_si_ripete_su_piu_tool(self):
        from langchain_core.messages import ToolMessage

        uno = ToolMessage(content=json.dumps(RISPOSTA_STALE), name="a", tool_call_id="1")
        due = ToolMessage(content=json.dumps(RISPOSTA_STALE), name="b", tool_call_id="2")
        eventi = [("updates", {"tools": {"messages": [uno, due]}})]
        tracciato = await self._traccia(eventi)
        assert [e["tipo"] for e in tracciato].count("avviso") == 1

    async def test_una_risposta_fresca_non_lo_emette(self):
        from langchain_core.messages import ToolMessage

        fresca = json.loads(json.dumps(RISPOSTA_STALE))
        fresca["meta"]["cache_status"] = "fresh"
        eventi = [("updates", {"tools": {"messages": [
            ToolMessage(content=json.dumps(fresca), name="a", tool_call_id="1")
        ]}})]
        tracciato = await self._traccia(eventi)
        assert "avviso" not in [e["tipo"] for e in tracciato]

    async def test_anche_la_risposta_non_streaming_si_apre_con_l_avviso(self):
        from langchain_core.messages import AIMessage, ToolMessage

        messaggi = [
            ToolMessage(content=json.dumps(RISPOSTA_STALE), name="get_entry_requirements",
                        tool_call_id="1"),
            AIMessage(content="Per l'Albania serve la carta d'identità."),
        ]
        assistente = await self._assistente([], messaggi)
        risposta = await assistente.chiedi("documenti per l'Albania")
        assert risposta.testo.startswith("⚠️")
        assert risposta.testo.rstrip().endswith("carta d'identità.")


class TestPromptSullaCache:
    def test_dice_al_modello_di_non_raddoppiare_l_avviso(self):
        testo = prompts.SYSTEM_PROMPT
        assert "cache_status" in testo
        assert "non ripeterlo" in testo.lower()

    def test_vieta_di_dedurre_calma_da_una_copia_vecchia(self):
        assert "non ce n'erano al momento dell'ultimo scaricamento" in prompts.SYSTEM_PROMPT


class TestTurnoCorrente(TestTracciaEventi):
    """`chiedi` deve descrivere il turno, non tutta la conversazione."""

    async def test_i_tool_sono_quelli_del_turno_non_dei_precedenti(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        messaggi = [
            HumanMessage(content="prima domanda"),
            ToolMessage(content="{}", name="get_entry_requirements", tool_call_id="1"),
            AIMessage(content="prima risposta"),
            HumanMessage(content="seconda domanda"),
            ToolMessage(content="{}", name="get_health_info", tool_call_id="2"),
            AIMessage(content="seconda risposta"),
        ]
        assistente = await self._assistente([], messaggi)
        risposta = await assistente.chiedi("seconda domanda")
        assert risposta.tool_usati == ["get_health_info"]
        assert risposta.testo == "seconda risposta"

    async def test_un_avviso_stale_vecchio_non_si_ripresenta(self):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        messaggi = [
            HumanMessage(content="prima"),
            ToolMessage(content=json.dumps(RISPOSTA_STALE), name="a", tool_call_id="1"),
            AIMessage(content="prima risposta"),
            HumanMessage(content="seconda"),
            ToolMessage(content='{"data": []}', name="b", tool_call_id="2"),
            AIMessage(content="seconda risposta"),
        ]
        assistente = await self._assistente([], messaggi)
        risposta = await assistente.chiedi("seconda")
        assert not risposta.testo.startswith("⚠️"), "la fonte ha risposto in questo turno"
