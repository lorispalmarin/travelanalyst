"""Client di embedding, usato in due momenti molto diversi.

All'ingest (offline, `make ingest`) vettorizza i 124 chunk in poche chiamate batch; a query time,
dentro il server MCP, vettorizza una sola stringa: la domanda dell'operatore.

Configurazione con lo stesso pattern di `assistant/config.py` — tutto da ambiente, errore
leggibile se manca il necessario — ma con variabili proprie: `EMBEDDING_*` prevale, e in mancanza
si ricade su `OPENAI_*`, così una sola chiave in `.env` fa funzionare tutto senza configurare
niente due volte.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# L'API accetta un array di input: 64 chunk per chiamata bastano a fare l'intero indice in due
# richieste, restando molto sotto il limite di token per richiesta.
LOTTO = 64


class CredenzialiMancanti(RuntimeError):
    """Manca la chiave per gli embedding: va detto in chiaro, non con un traceback dell'SDK."""


@dataclass(frozen=True)
class ImpostazioniEmbedding:
    api_key: str
    model: str
    base_url: str | None
    dimensions: int | None

    @property
    def descrizione(self) -> str:
        dove = self.base_url or "api.openai.com"
        return f"{self.model} su {dove}"


def carica() -> ImpostazioniEmbedding:
    api_key = (os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise CredenzialiMancanti(
            "EMBEDDING_API_KEY (o OPENAI_API_KEY) non impostata: senza non si possono "
            "vettorizzare le domande. Copia .env.example in .env e inserisci la chiave."
        )
    dimensioni = os.getenv("EMBEDDING_DIMENSIONS")
    return ImpostazioniEmbedding(
        api_key=api_key,
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-large"),
        base_url=(os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None),
        dimensions=int(dimensioni) if dimensioni else None,
    )


def _client(impostazioni: ImpostazioniEmbedding):
    from openai import OpenAI

    parametri = {"api_key": impostazioni.api_key}
    if impostazioni.base_url:
        parametri["base_url"] = impostazioni.base_url
    return OpenAI(**parametri)


def _normalizza(matrice):
    """Vettori a norma 1: da qui in poi la similarità coseno è un prodotto scalare e basta."""
    import numpy as np

    norme = np.linalg.norm(matrice, axis=1, keepdims=True)
    norme[norme == 0] = 1.0
    return (matrice / norme).astype("float32")


def embedda(testi: Sequence[str], impostazioni: ImpostazioniEmbedding | None = None):
    """Vettori normalizzati (n × d) e token consumati, in chiamate batch."""
    import numpy as np

    impostazioni = impostazioni or carica()
    client = _client(impostazioni)
    vettori: list[list[float]] = []
    token = 0

    for inizio in range(0, len(testi), LOTTO):
        lotto = list(testi[inizio : inizio + LOTTO])
        parametri = {"model": impostazioni.model, "input": lotto}
        if impostazioni.dimensions:
            parametri["dimensions"] = impostazioni.dimensions
        risposta = client.embeddings.create(**parametri)
        # l'API non garantisce l'ordine: si riordina sull'indice dichiarato
        for dato in sorted(risposta.data, key=lambda d: d.index):
            vettori.append(dato.embedding)
        token += getattr(risposta.usage, "total_tokens", 0) or 0
        logger.info("embeddati %s/%s chunk", len(vettori), len(testi))

    return _normalizza(np.asarray(vettori, dtype="float32")), token


def embedda_query(testo: str, impostazioni: ImpostazioniEmbedding | None = None):
    """Il vettore di una singola domanda, già normalizzato."""
    matrice, _ = embedda([testo], impostazioni)
    return matrice[0]
