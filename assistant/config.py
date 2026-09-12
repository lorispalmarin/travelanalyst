"""Configurazione dell'assistente.

Tutto da ambiente, così passare dall'endpoint OpenAI a quello Azure della traccia è un cambio
di `.env` e non di codice.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Il server MCP si avvia come modulo, non come file. Un percorso costruito da `__file__`
# funzionerebbe solo con un'installazione editabile: dentro un container il pacchetto sta in
# site-packages e `server.py` — che esiste per i launcher esterni — non è più accanto ad esso.
SERVER_MODULE = "viaggiaresicuri_mcp.server"

load_dotenv(ROOT / ".env")


class ConfigurazioneMancante(RuntimeError):
    """Manca qualcosa senza cui l'assistente non può partire: va detto in chiaro, non con un traceback."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str | None
    use_responses_api: bool
    reasoning_effort: str | None
    reasoning_summary: str | None
    python_executable: str
    server_module: str
    max_steps: int

    @property
    def descrizione(self) -> str:
        via = "Responses API" if self.use_responses_api else "Chat Completions"
        dove = self.base_url or "api.openai.com"
        return f"{self.model} via {via} su {dove}"


def carica() -> Settings:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ConfigurazioneMancante(
            "OPENAI_API_KEY non impostata. Copia .env.example in .env e inserisci la chiave."
        )

    # gpt-5.6-luna ragiona di default, e con il reasoning attivo i tool passano solo dalla
    # Responses API. L'alternativa sarebbe Chat Completions con reasoning_effort="none", che
    # però spegne il ragionamento proprio dove serve: scegliere ed enchainare i tool.
    use_responses = os.getenv("OPENAI_USE_RESPONSES_API", "true").lower() not in ("0", "false", "no")

    return Settings(
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        use_responses_api=use_responses,
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT") or None,
        # il riassunto del ragionamento è ciò che la UI mostra nella traccia: il reasoning
        # grezzo arriva cifrato, il sommario no
        reasoning_summary=os.getenv("OPENAI_REASONING_SUMMARY", "auto") or None,
        python_executable=os.getenv("MCP_PYTHON", sys.executable),
        server_module=os.getenv("MCP_SERVER_MODULE", SERVER_MODULE),
        max_steps=int(os.getenv("ASSISTANT_MAX_STEPS", "12")),
    )
